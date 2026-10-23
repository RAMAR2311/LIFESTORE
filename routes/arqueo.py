from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify, session
from flask_login import login_required, current_user
from models import db, Sale, SalePayment, ArqueoCaja, Expense, SobranteLog, CashShift, Branch, Asesor, User
from sqlalchemy.orm import joinedload
from decorators import admin_required
from datetime import datetime, date, time
from decimal import Decimal
import re
import json
import pytz

arqueo_bp = Blueprint('arqueo_bp', __name__)

def obtener_hora_bogota():
    return datetime.now(pytz.timezone('America/Bogota')).replace(tzinfo=None)

def get_current_branch_id():
    """Obtiene el ID de sucursal del contexto actual de forma unificada."""
    if current_user.rol in ['vendedor', 'bodega']:
        if current_user.branch_id:
            return current_user.branch_id
        b_def = Branch.query.filter_by(activa=True).order_by(Branch.id.asc()).first()
        return b_def.id if b_def else 1
    active_b = session.get('active_branch_id')
    if active_b:
        return int(active_b)
    b_def = Branch.query.filter_by(activa=True).order_by(Branch.id.asc()).first()
    return b_def.id if b_def else 1

def obtener_turno_abierto(branch_id):
    """Retorna el turno activo (estado 'ABIERTA') para la sucursal indicada."""
    return CashShift.query.filter_by(branch_id=branch_id, estado='ABIERTA').first()

@arqueo_bp.route('/turnos/abrir', methods=['GET', 'POST'])
@login_required
def abrir_turno():
    """Apertura de turno de caja por sucursal.
    Aplica ÚNICAMENTE a sucursales de tipo 'tienda'.
    Las sucursales con tipo 'bodega' quedan completamente exentas."""
    branch_id = request.args.get('branch_id', type=int) or get_current_branch_id()
    sucursal = Branch.query.get_or_404(branch_id)

    # Regla: Las sucursales de tipo bodega quedan completamente exentas de turnos
    if sucursal.tipo == 'bodega':
        flash(f"La sucursal '{sucursal.nombre}' es de tipo Bodega (Centro Logístico) y está completamente exenta de turnos de caja y selección de asesores.", "info")
        if current_user.rol in ['bodega', 'vendedor_bodega']:
            return redirect(url_for('bodega_bp.dashboard'))
        return redirect(url_for('sales_bp.caja_visual'))

    turno_existente = obtener_turno_abierto(branch_id)
    if turno_existente:
        flash(f"La tienda '{sucursal.nombre}' ya tiene un turno abierto por {turno_existente.opened_by.nombre} desde {turno_existente.fecha_apertura.strftime('%I:%M %p')}.", "info")
        return redirect(url_for('sales_bp.caja_visual'))

    if request.method == 'POST':
        base_raw = request.form.get('base_inicial_efectivo', '0')
        base_clean = str(base_raw).replace('$', '').replace('.', '').replace(',', '').strip()
        try:
            base_inicial = Decimal(base_clean or '0')
        except Exception:
            base_inicial = Decimal('0')

        asesores_ids = request.form.getlist('asesores_ids')
        notas = request.form.get('notas_apertura', '').strip()

        ahora_apertura = obtener_hora_bogota()
        apertura_tardia = False
        minutos_retraso = 0

        # Regla de Horario: Horario oficial 9:00 AM con gabela/tolerancia hasta las 9:30 AM
        if ahora_apertura.time() > time(9, 30):
            apertura_tardia = True
            dt_limite_apertura = datetime.combine(ahora_apertura.date(), time(9, 30))
            minutos_retraso = max(0, int((ahora_apertura - dt_limite_apertura).total_seconds() // 60))

        nuevo_turno = CashShift(
            branch_id=branch_id,
            opened_by_id=current_user.id,
            base_inicial_efectivo=base_inicial,
            asesores_ids=json.dumps([int(x) for x in asesores_ids if str(x).isdigit()]),
            estado='ABIERTA',
            fecha_apertura=ahora_apertura,
            notas_apertura=notas or None,
            apertura_tardia=apertura_tardia,
            minutos_retraso_apertura=minutos_retraso
        )

        try:
            db.session.add(nuevo_turno)
            db.session.commit()
            if apertura_tardia:
                flash(f"Turno de caja abierto en '{sucursal.nombre}' con base de ${base_inicial:,.0f}. (Aviso: Se registró Apertura Tardía con {minutos_retraso} min de retraso tras tolerancia de 9:30 AM).", "warning")
            else:
                flash(f"Turno de caja abierto exitosamente en '{sucursal.nombre}' con base de ${base_inicial:,.0f}.", "success")
            return redirect(url_for('sales_bp.caja_visual'))
        except Exception as e:
            db.session.rollback()
            flash(f"Error al abrir turno de caja: {str(e)}", "danger")

    asesores_activos = Asesor.query.filter_by(activo=True).order_by(Asesor.nombre.asc()).all()
    return render_template('arqueo/abrir_turno.html', sucursal=sucursal, asesores=asesores_activos)

@arqueo_bp.route('/turnos/auditoria', methods=['GET'])
@login_required
@admin_required
def auditoria_turnos():
    """Vista de auditoría para Admin: Monitorea qué sucursales tienen caja abierta hoy,
    quién la abrió, monto de base y qué asesores están de turno."""
    sucursales = Branch.query.filter_by(activa=True).order_by(Branch.tipo.desc(), Branch.nombre.asc()).all()
    hoy = obtener_hora_bogota().date()

    turnos_abiertos = CashShift.query.filter_by(estado='ABIERTA').all()
    turnos_por_branch = {t.branch_id: t for t in turnos_abiertos}

    # Historial reciente de turnos de hoy
    historial_hoy = CashShift.query.filter(
        db.func.date(CashShift.fecha_apertura) == hoy
    ).order_by(CashShift.fecha_apertura.desc()).all()

    todos_asesores = {a.id: a.nombre for a in Asesor.query.all()}

    return render_template(
        'arqueo/auditoria_turnos.html',
        sucursales=sucursales,
        turnos_por_branch=turnos_por_branch,
        historial_hoy=historial_hoy,
        todos_asesores=todos_asesores,
        hoy=hoy
    )


def calcular_totales_dia(ventas_del_dia):
    """Calcula los totales de efectivo, transferencias y retomas del día.
    Usa SalePayment si está disponible, de lo contrario usa metodo_pago legacy."""
    total_efectivo = Decimal('0')
    total_transferencia = Decimal('0')
    total_retomas = Decimal('0')
    
    for v in ventas_del_dia:
        if v.pagos:  # Ventas nuevas con tabla sale_payments
            for pago in v.pagos:
                if pago.metodo_pago == 'efectivo':
                    total_efectivo += pago.monto
                elif pago.metodo_pago == 'retoma':
                    total_retomas += pago.monto
                elif pago.metodo_pago == 'abono_tercero':
                    # Este monto va directo al proveedor, NO suma al efectivo físico del cajero
                    pass
                else:  # nequi, bancolombia, daviplata, transferencia, etc
                    total_transferencia += pago.monto
        else:  # Retrocompatibilidad con ventas antiguas
            if v.metodo_pago == 'efectivo':
                total_efectivo += v.monto_total
            elif v.metodo_pago == 'retoma':
                total_retomas += v.monto_total
            elif v.metodo_pago == 'abono_tercero':
                pass
            elif v.metodo_pago in ['addi', 'sitecredito', 'bancolombia', 'davivienda', 'tarjeta_credito', 'transferencia']:
                total_transferencia += v.monto_total

        # Sumar retomas registradas en la nueva tabla (como descuento)
        if getattr(v, 'retomas_asociadas', None):
            for retoma in v.retomas_asociadas:
                total_retomas += retoma.valor_retoma
    
    return total_efectivo, total_transferencia, total_retomas

def calcular_desglose_metodos_dia(ventas_del_dia):
    """Calcula el total recaudado desglosado exactamente por cada método de pago individual."""
    desglose = {}
    for v in ventas_del_dia:
        if v.pagos:
            for p in v.pagos:
                metodo = p.metodo_pago.lower() if p.metodo_pago else 'efectivo'
                if metodo != 'retoma':
                    desglose[metodo] = desglose.get(metodo, Decimal('0')) + Decimal(str(p.monto or 0))
        else:
            metodo = v.metodo_pago.lower() if v.metodo_pago else 'efectivo'
            if metodo != 'retoma':
                desglose[metodo] = desglose.get(metodo, Decimal('0')) + Decimal(str(v.monto_total or 0))
    return desglose

def procesar_unidades_ch(ventas):
    desglose = []
    total_general_ch = Decimal('0')
    
    for v in ventas:
        for detalle in v.detalles:
            nombre = ""
            if detalle.producto:
                nombre = detalle.producto.nombre
            elif detalle.nombre_manual:
                nombre = detalle.nombre_manual
                
            subcategoria = ""
            if detalle.variante:
                subcategoria = detalle.variante.nombre_variante
            
            # Buscar el patrón 'CH', opcionalmente con espacio y/o 'x', seguido de un número
            match_nombre = re.search(r'CH\s*x?(\d+)', nombre, re.IGNORECASE)
            match_sub = re.search(r'CH\s*x?(\d+)', subcategoria, re.IGNORECASE)
            
            valor_extraido = None
            error_formato = False
            
            # Prioridad: nombre del producto
            if match_nombre:
                try:
                    valor_extraido = int(match_nombre.group(1))
                except ValueError:
                    error_formato = True
            elif match_sub:
                try:
                    valor_extraido = int(match_sub.group(1))
                except ValueError:
                    error_formato = True
            else:
                # Si se detecta 'CH' pero no hay un número válido después
                if re.search(r'CH', nombre, re.IGNORECASE) or re.search(r'CH', subcategoria, re.IGNORECASE):
                    error_formato = True
            
            if valor_extraido is not None:
                valor_unitario = valor_extraido * 1000
                cantidad = detalle.cantidad_vendida
                subtotal = Decimal(str(valor_unitario * cantidad))
                
                desglose.append({
                    'nombre': f"{nombre} ({subcategoria})" if subcategoria else nombre,
                    'cantidad': cantidad,
                    'valor_unitario': valor_unitario,
                    'subtotal': subtotal,
                    'error': False
                })
                total_general_ch += subtotal
            elif error_formato:
                desglose.append({
                    'nombre': f"{nombre} ({subcategoria})" if subcategoria else nombre,
                    'cantidad': detalle.cantidad_vendida,
                    'valor_unitario': 0,
                    'subtotal': Decimal('0'),
                    'error': 'Error de formato en descripción'
                })
                
    return desglose, total_general_ch

def procesar_celulares(ventas):
    total_celulares = Decimal('0')
    for v in ventas:
        for detalle in v.detalles:
            if detalle.producto and detalle.producto.tipo_inventario == 'celulares':
                if detalle.variant_id and detalle.variante:
                    costo = detalle.variante.precio_costo or 0
                else:
                    costo = detalle.producto.precio_costo or 0
                total_celulares += Decimal(str(costo * detalle.cantidad_vendida))
    return total_celulares

@arqueo_bp.route('/nuevo', methods=['GET', 'POST'])
@login_required
def nuevo():
    from flask import session
    from models import Branch

    # Determinar la sucursal del arqueo
    if current_user.rol in ['vendedor', 'bodega']:
        arqueo_branch_id = current_user.branch_id
        if not arqueo_branch_id:
            b_def = Branch.query.filter_by(activa=True).order_by(Branch.id.asc()).first()
            arqueo_branch_id = b_def.id if b_def else 1
    else:
        active_b = session.get('active_branch_id')
        if active_b:
            arqueo_branch_id = int(active_b)
        else:
            b_def = Branch.query.filter_by(activa=True).order_by(Branch.id.asc()).first()
            arqueo_branch_id = b_def.id if b_def else 1

    b_obj = Branch.query.get(arqueo_branch_id)
    arqueo_branch_nombre = b_obj.nombre if b_obj else 'PRINCIPAL'

    # Obtener fecha de la URL o usar hoy
    fecha_str = request.args.get('fecha', obtener_hora_bogota().strftime('%Y-%m-%d'))
    try:
        fecha_seleccionada = datetime.strptime(fecha_str, '%Y-%m-%d').date()
    except ValueError:
        fecha_seleccionada = obtener_hora_bogota().date()
        fecha_str = fecha_seleccionada.strftime('%Y-%m-%d')

    # Calcular ventas del día aisladas por sucursal
    ventas_query = Sale.query.filter(
        db.func.date(Sale.fecha_venta) == fecha_seleccionada,
        Sale.tipo_venta.in_(['general', 'celulares']),
        Sale.branch_id == arqueo_branch_id
    )
    if current_user.rol == 'vendedor':
        ventas_query = ventas_query.filter(Sale.vendedor_id == current_user.id)

    ventas_del_dia = ventas_query.order_by(Sale.fecha_venta.asc()).all()
    total_efectivo, total_transferencia, total_retomas = calcular_totales_dia(ventas_del_dia)

    # Calcular gastos del día aislados por sucursal
    gastos_query = Expense.query.filter(
        db.func.date(Expense.fecha_gasto) == fecha_seleccionada,
        Expense.tipo_gasto == 'Gasto Diario',
        Expense.branch_id == arqueo_branch_id
    )
    if current_user.rol == 'vendedor':
        gastos_query = gastos_query.filter(Expense.usuario_id == current_user.id)

    gastos_diarios_registros = gastos_query.all()
    gastos_automaticos = float(sum(g.monto for g in gastos_diarios_registros))

    # Gastos externos del día por sucursal
    gastos_ext_query = Expense.query.filter(
        db.func.date(Expense.fecha_gasto) == fecha_seleccionada,
        Expense.categoria == 'Pago Prod. Externo',
        Expense.branch_id == arqueo_branch_id
    )
    if current_user.rol == 'vendedor':
        gastos_ext_query = gastos_ext_query.filter(Expense.usuario_id == current_user.id)
    gastos_externos_registros = gastos_ext_query.all()
    gastos_externos = float(sum(g.monto for g in gastos_externos_registros))

    # Verificar si ya existe un arqueo para esa fecha y sucursal
    arqueo_existente_q = ArqueoCaja.query.filter(
        ArqueoCaja.fecha_arqueo == fecha_seleccionada,
        ArqueoCaja.tipo_arqueo == 'general',
        ArqueoCaja.branch_id == arqueo_branch_id
    )
    if current_user.rol == 'vendedor':
        arqueo_existente_q = arqueo_existente_q.filter(ArqueoCaja.vendedor_id == current_user.id)
    arqueo_existente = arqueo_existente_q.first()

    # Obtener el turno abierto para esta sucursal
    turno_abierto = CashShift.query.filter_by(branch_id=arqueo_branch_id, estado='ABIERTA').first()
    base_inicial_sugerida = float(turno_abierto.base_inicial_efectivo) if turno_abierto else 0.0

    if request.method == 'POST':
        if arqueo_existente:
            flash('Ya existe un arqueo cerrado para esta fecha en esta sucursal. No se puede duplicar.', 'warning')
            return redirect(url_for('arqueo_bp.reporte', fecha_inicio=fecha_str, fecha_fin=fecha_str))

        base_inicial = float(request.form.get('base_inicial', base_inicial_sugerida))
        efectivo_fisico_val = float(request.form.get('efectivo_fisico', 0.0) or 0.0)
        observacion_diferencia = request.form.get('observacion_diferencia', '').strip()
        
        # Recalcular gastos automáticos por seguridad en el backend
        gastos_recalc_q = Expense.query.filter(
            db.func.date(Expense.fecha_gasto) == fecha_seleccionada,
            Expense.tipo_gasto == 'Gasto Diario',
            Expense.branch_id == arqueo_branch_id
        )
        if current_user.rol == 'vendedor':
            gastos_recalc_q = gastos_recalc_q.filter(Expense.usuario_id == current_user.id)
        gastos_del_dia = float(sum(g.monto for g in gastos_recalc_q.all()))
        
        observaciones_gastos = request.form.get('observaciones_gastos', '').strip()

        # Calcular monto esperado en efectivo y diferencia (Sobrante / Faltante)
        esperado_efectivo = float(base_inicial) + float(total_efectivo) - float(gastos_del_dia)
        diferencia_val = efectivo_fisico_val - esperado_efectivo

        nuevo_arqueo = ArqueoCaja(
            vendedor_id=current_user.id,
            branch_id=arqueo_branch_id,
            fecha_arqueo=fecha_seleccionada,
            base_inicial=base_inicial,
            gastos_del_dia=gastos_del_dia,
            observaciones_gastos=observaciones_gastos,
            total_efectivo_sistema=total_efectivo,
            total_transferencia_sistema=total_transferencia,
            total_unidades_ch=Decimal('0.00'),
            total_celulares=Decimal('0.00'),
            total_retomas_sistema=total_retomas,
            tipo_arqueo='general',
            sucursal=arqueo_branch_nombre,
            efectivo_fisico=efectivo_fisico_val,
            diferencia=diferencia_val,
            observacion_diferencia=observacion_diferencia,
            shift_id=turno_abierto.id if turno_abierto else None,
            closed_by_id=current_user.id
        )

        try:
            db.session.add(nuevo_arqueo)
            db.session.flush()

            # Cerrar el turno de caja abierto para esta sucursal si existe
            if turno_abierto:
                turno_abierto.estado = 'CERRADA'
                turno_abierto.closed_by_id = current_user.id
                ahora_cierre = obtener_hora_bogota()
                turno_abierto.fecha_cierre = ahora_cierre
                turno_abierto.arqueo_id = nuevo_arqueo.id

                # Regla de Horario: Horario límite de cierre 7:30 PM (19:30)
                if ahora_cierre.time() > time(19, 30):
                    turno_abierto.cierre_tardio = True
                    dt_limite_cierre = datetime.combine(ahora_cierre.date(), time(19, 30))
                    turno_abierto.minutos_retraso_cierre = max(0, int((ahora_cierre - dt_limite_cierre).total_seconds() // 60))

            # Si hay un SOBRANTE de caja (diferencia a favor > 0), registrar en el Log de Sobrantes
            if diferencia_val > 0:
                log_sobrante = SobranteLog(
                    arqueo_id=nuevo_arqueo.id,
                    vendedor_id=current_user.id,
                    sucursal=arqueo_branch_nombre,
                    fecha_arqueo=fecha_seleccionada,
                    monto_esperado=Decimal(str(esperado_efectivo)),
                    efectivo_fisico=Decimal(str(efectivo_fisico_val)),
                    monto_sobrante=Decimal(str(diferencia_val)),
                    justificacion=observacion_diferencia
                )
                db.session.add(log_sobrante)

            # --- INTEGRACIÓN CON MÓDULO BANCOS ---
            from services.bank_service import registrar_movimiento_banco
            desglose_bancos = calcular_desglose_metodos_dia(ventas_del_dia)
            for metodo_cod, monto_metodo in desglose_bancos.items():
                if monto_metodo > 0:
                    registrar_movimiento_banco(
                        codigo_metodo=metodo_cod,
                        monto=monto_metodo,
                        tipo_movimiento='INGRESO',
                        origen='ARQUEO_CIERRE',
                        descripcion=f'Cierre Arqueo #{nuevo_arqueo.id} ({arqueo_branch_nombre} - {fecha_seleccionada})',
                        referencia_id=nuevo_arqueo.id,
                        usuario_id=current_user.id
                    )

            db.session.commit()
            flash(f'Arqueo de caja guardado exitosamente para {arqueo_branch_nombre}, turno cerrado y acreditado a Bancos.', 'success')
            return redirect(url_for('arqueo_bp.reporte', fecha_inicio=fecha_str, fecha_fin=fecha_str))
        except Exception as e:
            db.session.rollback()
            flash(f'Ocurrió un error al guardar el arqueo de caja: {str(e)}', 'danger')

    return render_template(
        'arqueo/form.html',
        fecha=fecha_str,
        total_efectivo=total_efectivo,
        total_transferencia=total_transferencia,
        arqueo_existente=arqueo_existente,
        gastos_automaticos=gastos_automaticos,
        gastos_externos=gastos_externos,
        ventas_del_dia=ventas_del_dia,
        branch_nombre=arqueo_branch_nombre
    )

@arqueo_bp.route('/reporte', methods=['GET'])
@login_required
def reporte():
    from flask import session
    fecha_inicio_str = request.args.get('fecha_inicio', obtener_hora_bogota().strftime('%Y-%m-%d'))
    fecha_fin_str = request.args.get('fecha_fin', obtener_hora_bogota().strftime('%Y-%m-%d'))

    try:
        fecha_inicio = datetime.strptime(fecha_inicio_str, '%Y-%m-%d').date()
        fecha_fin = datetime.strptime(fecha_fin_str, '%Y-%m-%d').date()
    except ValueError:
        fecha_inicio = obtener_hora_bogota().date()
        fecha_fin = obtener_hora_bogota().date()

    # BLOQUEO DE SEGURIDAD: Los vendedores no pueden ver días anteriores
    if current_user.rol != 'admin':
        hoy = obtener_hora_bogota().date()
        fecha_inicio = hoy
        fecha_fin = hoy
        fecha_inicio_str = hoy.strftime('%Y-%m-%d')
        fecha_fin_str = hoy.strftime('%Y-%m-%d')

    query = ArqueoCaja.query.filter(
        ArqueoCaja.fecha_arqueo >= fecha_inicio,
        ArqueoCaja.fecha_arqueo <= fecha_fin,
        ArqueoCaja.tipo_arqueo == 'general'
    )

    # Filtrar por sucursal
    if current_user.rol == 'vendedor':
        if current_user.branch_id:
            query = query.filter(ArqueoCaja.branch_id == current_user.branch_id)
    else:
        active_b_id = session.get('active_branch_id')
        if active_b_id:
            query = query.filter(ArqueoCaja.branch_id == int(active_b_id))

    arqueos = query.order_by(ArqueoCaja.fecha_arqueo.desc()).all()

    # Cálculos globales para el reporte
    resumen = {
        'total_base': sum(a.base_inicial for a in arqueos),
        'total_efectivo': sum(a.total_efectivo_sistema for a in arqueos),
        'total_transferencia': sum(a.total_transferencia_sistema for a in arqueos),
        'total_gastos': sum(a.gastos_del_dia for a in arqueos)
    }

    # Calcular los gastos por productos externos en este rango de fechas y sucursal
    gastos_externos_query = Expense.query.filter(
        db.func.date(Expense.fecha_gasto) >= fecha_inicio,
        db.func.date(Expense.fecha_gasto) <= fecha_fin,
        Expense.categoria == 'Pago Prod. Externo'
    )
    if current_user.rol == 'vendedor':
        if current_user.branch_id:
            gastos_externos_query = gastos_externos_query.filter(Expense.branch_id == current_user.branch_id)
    else:
        active_b_id = session.get('active_branch_id')
        if active_b_id:
            gastos_externos_query = gastos_externos_query.filter(Expense.branch_id == int(active_b_id))
    gastos_externos_registros = gastos_externos_query.all()
    resumen['total_gastos_externos'] = sum(g.monto for g in gastos_externos_registros)
    
    resumen['total_recaudado_bruto'] = resumen['total_efectivo'] + resumen['total_transferencia']
    resumen['total_recaudado_neto'] = resumen['total_recaudado_bruto'] - resumen['total_gastos']
    
    # Calcular los gastos que fueron pagados en EFECTIVO
    gastos_efectivo_query = Expense.query.filter(
        db.func.date(Expense.fecha_gasto) >= fecha_inicio,
        db.func.date(Expense.fecha_gasto) <= fecha_fin,
        Expense.tipo_gasto == 'Gasto Diario',
        Expense.metodo_pago == 'efectivo'
    )
    if current_user.rol == 'vendedor':
        if current_user.branch_id:
            gastos_efectivo_query = gastos_efectivo_query.filter(Expense.branch_id == current_user.branch_id)
    else:
        active_b_id = session.get('active_branch_id')
        if active_b_id:
            gastos_efectivo_query = gastos_efectivo_query.filter(Expense.branch_id == int(active_b_id))
    gastos_efectivo_registros = gastos_efectivo_query.all()
    resumen['total_gastos_efectivo'] = sum(g.monto for g in gastos_efectivo_registros)

    # El efectivo esperado en caja descuenta gastos en EFECTIVO
    resumen['efectivo_esperado'] = (resumen['total_base'] + resumen['total_efectivo']) - resumen['total_gastos_efectivo']
    resumen['total_sobrantes'] = sum((Decimal(str(a.diferencia)) for a in arqueos if a.diferencia and a.diferencia > 0), Decimal('0.00'))
    resumen['total_faltantes'] = sum((Decimal(str(abs(a.diferencia))) for a in arqueos if a.diferencia and a.diferencia < 0), Decimal('0.00'))

    # Obtener todas las ventas del periodo para el detalle en la "tirilla"
    ventas_query = Sale.query.filter(
        db.func.date(Sale.fecha_venta) >= fecha_inicio,
        db.func.date(Sale.fecha_venta) <= fecha_fin,
        Sale.tipo_venta.in_(['general', 'celulares'])
    )
    if current_user.rol == 'vendedor':
        if current_user.branch_id:
            ventas_query = ventas_query.filter(Sale.branch_id == current_user.branch_id)
    else:
        active_b_id = session.get('active_branch_id')
        if active_b_id:
            ventas_query = ventas_query.filter(Sale.branch_id == int(active_b_id))
    ventas_periodo = ventas_query.order_by(Sale.fecha_venta.asc()).all()

    fecha_generacion = obtener_hora_bogota().strftime('%Y-%m-%d %H:%M')

    # Obtener todos los gastos del periodo para el reporte detallado
    gastos_query = Expense.query.filter(
        db.func.date(Expense.fecha_gasto) >= fecha_inicio,
        db.func.date(Expense.fecha_gasto) <= fecha_fin
    )
    if current_user.rol == 'vendedor':
        if current_user.branch_id:
            gastos_query = gastos_query.filter(Expense.branch_id == current_user.branch_id)
    else:
        active_b_id = session.get('active_branch_id')
        if active_b_id:
            gastos_query = gastos_query.filter(Expense.branch_id == int(active_b_id))
    gastos_periodo = gastos_query.order_by(Expense.fecha_gasto.asc()).all()

    return render_template(
        'arqueo/reporte.html',
        arqueos=arqueos,
        resumen=resumen,
        fecha_inicio=fecha_inicio_str,
        fecha_fin=fecha_fin_str,
        fecha_generacion=fecha_generacion,
        ventas_periodo=ventas_periodo,
        gastos_periodo=gastos_periodo
    )

@arqueo_bp.route('/revertir/<int:id>', methods=['POST'])
@login_required
@admin_required
def revertir_arqueo(id):
    arqueo = ArqueoCaja.query.get_or_404(id)
    fecha_str = arqueo.fecha_arqueo.strftime('%Y-%m-%d')
    try:
        SobranteLog.query.filter_by(arqueo_id=arqueo.id).delete()
        db.session.delete(arqueo)
        db.session.commit()
        flash(f"El arqueo de caja del {fecha_str} ha sido revertido exitosamente.", "success")
    except Exception as e:
        db.session.rollback()
        flash("Ocurrió un error al revertir el arqueo de caja.", "danger")
    return redirect(url_for('arqueo_bp.reporte'))

@arqueo_bp.route('/sobrantes', methods=['GET'])
@login_required
def log_sobrantes():
    fecha_inicio_str = request.args.get('fecha_inicio', '')
    fecha_fin_str = request.args.get('fecha_fin', '')
    q = request.args.get('q', '').strip()

    base_query = SobranteLog.query.options(
        joinedload(SobranteLog.vendedor),
        joinedload(SobranteLog.arqueo)
    )

    if fecha_inicio_str:
        try:
            f_ini = datetime.strptime(fecha_inicio_str, '%Y-%m-%d').date()
            base_query = base_query.filter(SobranteLog.fecha_arqueo >= f_ini)
        except ValueError:
            pass

    if fecha_fin_str:
        try:
            f_fin = datetime.strptime(fecha_fin_str, '%Y-%m-%d').date()
            base_query = base_query.filter(SobranteLog.fecha_arqueo <= f_fin)
        except ValueError:
            pass

    if q:
        from models import User
        base_query = base_query.join(User).filter(
            db.or_(
                SobranteLog.justificacion.ilike(f'%{q}%'),
                User.nombre.ilike(f'%{q}%')
            )
        )

    sobrantes = base_query.order_by(SobranteLog.fecha_registro.desc()).all()

    # Cálculos KPIs
    total_sobrantes_monto = sum((s.monto_sobrante for s in sobrantes), Decimal('0.00')) if sobrantes else Decimal('0.00')
    total_registros = len(sobrantes)
    mayor_sobrante = max((s.monto_sobrante for s in sobrantes), default=Decimal('0.00'))

    return render_template('arqueo/sobrantes.html',
                           sobrantes=sobrantes,
                           total_sobrantes_monto=total_sobrantes_monto,
                           total_registros=total_registros,
                           mayor_sobrante=mayor_sobrante,
                           fecha_inicio=fecha_inicio_str,
                           fecha_fin=fecha_fin_str,
                           q=q)

@arqueo_bp.route('/ticket', methods=['GET'])
@login_required
def imprimir_ticket_arqueo():
    fecha_str = request.args.get('fecha', obtener_hora_bogota().strftime('%Y-%m-%d'))
    
    try:
        fecha_obj = datetime.strptime(fecha_str, '%Y-%m-%d').date()
    except ValueError:
        fecha_obj = obtener_hora_bogota().date()
        fecha_str = fecha_obj.strftime('%Y-%m-%d')
        
    arqueo = ArqueoCaja.query.filter_by(fecha_arqueo=fecha_obj, tipo_arqueo='general').first()
    
    ventas = Sale.query.filter(
        db.func.date(Sale.fecha_venta) == fecha_obj,
        Sale.tipo_venta.in_(['general', 'celulares'])
    ).order_by(Sale.fecha_venta.asc()).all()
    
    gastos = Expense.query.filter(
        db.func.date(Expense.fecha_gasto) == fecha_obj
    ).all()
    
    total_efectivo = 0
    total_transferencia = 0
    total_ventas = 0
    
    for v in ventas:
        total_ventas += float(v.monto_total or 0)
        if v.pagos and len(v.pagos) > 0:
            for p in v.pagos:
                if p.metodo_pago.lower() == 'efectivo':
                    total_efectivo += float(p.monto or 0)
                else:
                    total_transferencia += float(p.monto or 0)
        else:
            if v.metodo_pago and v.metodo_pago.lower() == 'efectivo':
                total_efectivo += float(v.monto_total or 0)
            else:
                total_transferencia += float(v.monto_total or 0)
                
    total_gastos = sum(float(g.monto or 0) for g in gastos)
    fecha_generacion = obtener_hora_bogota().strftime('%d/%m/%Y %I:%M %p')
    
    # Buscar turno de caja asociado para trazabilidad de custodia
    turno = None
    if arqueo and arqueo.shift_id:
        turno = CashShift.query.get(arqueo.shift_id)
    if not turno:
        turno = CashShift.query.filter(
            db.func.date(CashShift.fecha_apertura) == fecha_obj
        ).order_by(CashShift.fecha_apertura.desc()).first()

    todos_asesores = {a.id: a.nombre for a in Asesor.query.all()}
    asesores_nombres = []
    if turno and turno.lista_asesores_ids:
        asesores_nombres = [todos_asesores.get(aid, f"Asesor #{aid}") for aid in turno.lista_asesores_ids]

    return render_template(
        'arqueo/ticket.html',
        fecha=fecha_obj.strftime('%d/%m/%Y'),
        fecha_str=fecha_str,
        fecha_generacion=fecha_generacion,
        arqueo=arqueo,
        turno=turno,
        asesores_nombres=asesores_nombres,
        ventas=ventas,
        gastos=gastos,
        total_efectivo=total_efectivo,
        total_transferencia=total_transferencia,
        total_ventas=total_ventas,
        total_gastos=total_gastos,
        sucursal='TIENDA PRINCIPAL'
    )
