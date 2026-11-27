import os
from werkzeug.utils import secure_filename
from flask import Blueprint, render_template, request, redirect, url_for, flash, session, abort, current_app
from flask_login import login_required, current_user
from models import (
    db, Vale, Asesor, Branch, User, Expense, Sale, SalePayment, CashShift, AuditLog, obtener_hora_bogota
)
from decorators import admin_required
from decimal import Decimal
from datetime import datetime

vales_bp = Blueprint('vales_bp', __name__)

METODOS_PAGO_VALE = [
    ('efectivo', '💵 Efectivo', 'fa-money-bill-wave'),
    ('nequi', '📱 Nequi', 'fa-mobile-screen'),
    ('bancolombia', '🏦 Bancolombia', 'fa-building-columns'),
    ('daviplata', '📲 Daviplata', 'fa-mobile-retro'),
    ('davivienda', '🏦 Davivienda', 'fa-building-columns'),
    ('bold', '💳 Bold', 'fa-bolt'),
]


def get_active_branch_for_user():
    """Determina la sucursal activa según el rol del usuario en sesión."""
    if current_user.rol in ['vendedor', 'bodega', 'vendedor_bodega']:
        if current_user.branch_id:
            return current_user.branch_id
        b_def = Branch.query.filter_by(activa=True, tipo='tienda').order_by(Branch.id.asc()).first()
        return b_def.id if b_def else None
    active_b = session.get('active_branch_id')
    return int(active_b) if active_b else None


def _calcular_saldos_por_local_y_metodo():
    """
    Calcula el saldo disponible de cada Local comercial (tipo='tienda') desglosado
    por cada método de pago (Efectivo, Nequi, Bancolombia, Daviplata, Davivienda, Bold).
    """
    hoy = obtener_hora_bogota().date()
    locales = Branch.query.filter_by(activa=True, tipo='tienda').order_by(Branch.nombre.asc()).all()
    resultado = {}

    for b in locales:
        turno_abierto = CashShift.query.filter_by(branch_id=b.id, estado='ABIERTA').first()
        base_efectivo_hoy = float(turno_abierto.base_inicial_efectivo or 0) if turno_abierto else 0.0

        # Ventas de este local
        ventas_local = Sale.query.filter_by(branch_id=b.id).all()
        gastos_local = Expense.query.filter_by(branch_id=b.id).all()

        recaudo_total = {k: 0.0 for k, _, _ in METODOS_PAGO_VALE}
        recaudo_hoy = {k: 0.0 for k, _, _ in METODOS_PAGO_VALE}
        recaudo_hoy['efectivo'] += base_efectivo_hoy

        for v in ventas_local:
            es_hoy = bool(v.fecha_venta and v.fecha_venta.date() == hoy)
            if v.pagos:
                for p in v.pagos:
                    m = (p.metodo_pago or 'efectivo').lower().strip()
                    if m == 'bolt':
                        m = 'bold'
                    if m in recaudo_total:
                        val = float(p.monto or 0)
                        recaudo_total[m] += val
                        if es_hoy:
                            recaudo_hoy[m] += val
            else:
                m = (v.metodo_pago or 'efectivo').lower().strip()
                if m == 'bolt':
                    m = 'bold'
                if m in recaudo_total:
                    val = float(v.monto_total or 0)
                    recaudo_total[m] += val
                    if es_hoy:
                        recaudo_hoy[m] += val

        gasto_total = {k: 0.0 for k, _, _ in METODOS_PAGO_VALE}
        gasto_hoy = {k: 0.0 for k, _, _ in METODOS_PAGO_VALE}

        for g in gastos_local:
            es_hoy = bool(g.fecha_gasto and g.fecha_gasto.date() == hoy)
            m = (g.metodo_pago or 'efectivo').lower().strip()
            if m == 'bolt':
                m = 'bold'
            if m in gasto_total:
                val = float(g.monto or 0)
                gasto_total[m] += val
                if es_hoy:
                    gasto_hoy[m] += val

        metodos_info = {}
        total_local = 0.0
        for m_key, m_label, m_icon in METODOS_PAGO_VALE:
            disp_hoy = recaudo_hoy[m_key] - gasto_hoy[m_key]
            disp_acum = recaudo_total[m_key] - gasto_total[m_key]
            # Si hay base de caja hoy o saldo acumulado histórico, tomamos el disponible real (>= 0)
            saldo_disp = max(0.0, max(disp_hoy, disp_acum))
            metodos_info[m_key] = {
                'codigo': m_key,
                'label': m_label,
                'icono': m_icon,
                'saldo': round(saldo_disp),
                'saldo_hoy': round(max(0.0, disp_hoy)),
                'saldo_acumulado': round(max(0.0, disp_acum))
            }
            total_local += saldo_disp

        resultado[b.id] = {
            'branch_id': b.id,
            'nombre': b.nombre,
            'codigo': b.codigo,
            'total_disponible': round(total_local),
            'metodos': metodos_info
        }

    return locales, resultado


def _sincronizar_arqueo_cerrado_por_vale(branch_id, fecha_dt):
    """
    Si el vale pertenece a un día y local que YA tenía un cierre de caja (ArqueoCaja),
    actualiza automáticamente gastos_del_dia en ese ArqueoCaja sin necesidad de reabrir la caja.
    Además, si la caja había sido cerrada como 'Cuadrada' (diferencia == 0) porque el cajero
    sumó el vale como si aún estuviera en efectivo, ajusta efectivo_fisico en la misma proporción
    para que el arqueo refleje el gasto real sin generar un descuadre artificial.
    """
    if not branch_id or not fecha_dt:
        return False
    from models import ArqueoCaja
    fecha_d = fecha_dt.date() if hasattr(fecha_dt, 'date') else fecha_dt
    arqueo = ArqueoCaja.query.filter_by(
        fecha_arqueo=fecha_d,
        branch_id=branch_id,
        tipo_arqueo='general'
    ).first()
    if not arqueo:
        return False

    gastos_efec = Expense.query.filter(
        db.func.date(Expense.fecha_gasto) == fecha_d,
        Expense.tipo_gasto == 'Gasto Diario',
        Expense.branch_id == branch_id
    ).all()
    nuevo_gastos_dia = float(sum(g.monto for g in gastos_efec if (g.metodo_pago or 'efectivo').lower() == 'efectivo'))
    gastos_ant = float(arqueo.gastos_del_dia or 0)
    delta_gastos = nuevo_gastos_dia - gastos_ant

    arqueo.gastos_del_dia = Decimal(str(round(nuevo_gastos_dia, 2)))
    esperado_nuevo = float(arqueo.base_inicial or 0) + float(arqueo.total_efectivo_sistema or 0) - nuevo_gastos_dia

    # Si estaba cuadrada (porque contaron el dinero como si no hubiera salido el vale),
    # descontamos el delta del efectivo_fisico registrado para que siga cuadrada con el gasto incluido.
    if abs(float(arqueo.diferencia or 0)) < 1.0 and delta_gastos != 0:
        arqueo.efectivo_fisico = Decimal(str(round(max(0.0, float(arqueo.efectivo_fisico or 0) - delta_gastos), 2)))

    arqueo.diferencia = Decimal(str(round(float(arqueo.efectivo_fisico or 0) - esperado_nuevo, 2)))
    return True


def _sincronizar_gasto_vale(vale, branch_obj, metodo_pago, user_id):
    """Crea o actualiza el registro de Gasto (Expense) asociado a un Vale aprobado."""
    nombre_asesor = vale.asesor.nombre if vale.asesor else f'Asesor #{vale.asesor_id}'
    desc_gasto = f"[VALE #VAL-{vale.id:04d}] Asesor: {nombre_asesor} ({metodo_pago.capitalize()})"
    if vale.concepto:
        desc_gasto += f" — {vale.concepto}"
    if vale.observacion_resolucion:
        desc_gasto += f" ({vale.observacion_resolucion})"
    desc_gasto = desc_gasto[:255]

    fecha_ref = vale.fecha_resolucion or vale.fecha_solicitud or obtener_hora_bogota()

    if vale.expense_id:
        gasto_existente = Expense.query.get(vale.expense_id)
        if gasto_existente:
            branch_ant_id = gasto_existente.branch_id
            gasto_existente.monto = vale.monto
            gasto_existente.metodo_pago = metodo_pago
            gasto_existente.branch_id = branch_obj.id
            gasto_existente.sucursal = branch_obj.nombre
            gasto_existente.descripcion = desc_gasto
            db.session.flush()
            if branch_ant_id and branch_ant_id != branch_obj.id:
                _sincronizar_arqueo_cerrado_por_vale(branch_ant_id, gasto_existente.fecha_gasto or fecha_ref)
            _sincronizar_arqueo_cerrado_por_vale(branch_obj.id, gasto_existente.fecha_gasto or fecha_ref)
            return gasto_existente

    nuevo_gasto = Expense(
        usuario_id=user_id,
        tipo_gasto='Gasto Diario',
        categoria='Vale de Asesor',
        descripcion=desc_gasto,
        monto=vale.monto,
        metodo_pago=metodo_pago,
        sucursal=branch_obj.nombre,
        branch_id=branch_obj.id,
        fecha_gasto=fecha_ref
    )
    db.session.add(nuevo_gasto)
    db.session.flush()
    vale.expense_id = nuevo_gasto.id
    _sincronizar_arqueo_cerrado_por_vale(branch_obj.id, fecha_ref)
    return nuevo_gasto


@vales_bp.route('/', methods=['GET'])
@login_required
def index():
    """
    Vista unificada del módulo de Vales:
    - Si es Vendedor: muestra el formulario para solicitar un vale seleccionando el asesor y el monto,
      junto con el historial y trazabilidad de los vales solicitados en su sede/usuario.
    - Si es Administrador: muestra el panel de bandeja de solicitudes recibidas para aceptar o rechazar,
      mostrando en qué local está la persona que lo pidió y el saldo disponible de cada método de pago en ese local.
    """
    # Backfill automático para vales que hayan sido aprobados antes de esta actualización sin generar Expense
    vales_sin_gasto = Vale.query.filter_by(estado='APROBADO', expense_id=None).all()
    if vales_sin_gasto:
        default_tienda = Branch.query.filter_by(activa=True, tipo='tienda').order_by(Branch.id.asc()).first()
        changed_backfill = False
        for vs in vales_sin_gasto:
            target_b_id = vs.branch_id or (vs.solicitado_por.branch_id if vs.solicitado_por else None)
            b_obj = Branch.query.get(target_b_id) if target_b_id else default_tienda
            if b_obj and b_obj.tipo != 'tienda' and default_tienda:
                b_obj = default_tienda
            if b_obj:
                vs.branch_id = b_obj.id
                vs.metodo_pago = vs.metodo_pago or 'efectivo'
                _sincronizar_gasto_vale(vs, b_obj, vs.metodo_pago, vs.resuelto_por_id or current_user.id)
                changed_backfill = True
        if changed_backfill:
            try:
                db.session.commit()
            except Exception:
                db.session.rollback()

    asesores_activos = Asesor.query.filter_by(activo=True).order_by(Asesor.nombre.asc()).all()
    todos_asesores = Asesor.query.order_by(Asesor.nombre.asc()).all()
    locales_tienda, saldos_locales = _calcular_saldos_por_local_y_metodo()

    estado_filtro = request.args.get('estado', '').strip().upper()
    asesor_id_filtro = request.args.get('asesor_id', type=int)
    fecha_filtro = request.args.get('fecha', '').strip()

    query = Vale.query

    # Filtrado según perfil
    if current_user.rol not in ['admin', 'coordinador']:
        if current_user.branch_id:
            query = query.filter(
                (Vale.branch_id == current_user.branch_id) | (Vale.solicitado_por_id == current_user.id)
            )
        else:
            query = query.filter(Vale.solicitado_por_id == current_user.id)
    else:
        active_b = session.get('active_branch_id')
        if active_b:
            query = query.filter(Vale.branch_id == int(active_b))

    if estado_filtro in ['PENDIENTE', 'APROBADO', 'RECHAZADO']:
        query = query.filter(Vale.estado == estado_filtro)

    if asesor_id_filtro:
        query = query.filter(Vale.asesor_id == asesor_id_filtro)

    if fecha_filtro:
        try:
            f_obj = datetime.strptime(fecha_filtro, '%Y-%m-%d').date()
            query = query.filter(db.func.date(Vale.fecha_solicitud) == f_obj)
        except ValueError:
            pass

    vales = query.order_by(Vale.fecha_solicitud.desc()).all()

    base_kpi_q = Vale.query
    if current_user.rol not in ['admin', 'coordinador']:
        if current_user.branch_id:
            base_kpi_q = base_kpi_q.filter(
                (Vale.branch_id == current_user.branch_id) | (Vale.solicitado_por_id == current_user.id)
            )
        else:
            base_kpi_q = base_kpi_q.filter(Vale.solicitado_por_id == current_user.id)
    else:
        active_b = session.get('active_branch_id')
        if active_b:
            base_kpi_q = base_kpi_q.filter(Vale.branch_id == int(active_b))

    todos_contexto = base_kpi_q.all()
    pendientes_list = [v for v in todos_contexto if v.estado == 'PENDIENTE']
    aprobados_list = [v for v in todos_contexto if v.estado == 'APROBADO']
    rechazados_list = [v for v in todos_contexto if v.estado == 'RECHAZADO']

    kpis = {
        'pendientes_count': len(pendientes_list),
        'pendientes_monto': sum((v.monto or Decimal('0')) for v in pendientes_list),
        'aprobados_count': len(aprobados_list),
        'aprobados_monto': sum((v.monto or Decimal('0')) for v in aprobados_list),
        'rechazados_count': len(rechazados_list),
        'rechazados_monto': sum((v.monto or Decimal('0')) for v in rechazados_list),
        'total_count': len(todos_contexto)
    }

    return render_template(
        'vales/index.html',
        vales=vales,
        asesores_activos=asesores_activos,
        todos_asesores=todos_asesores,
        locales_tienda=locales_tienda,
        saldos_locales=saldos_locales,
        metodos_pago_vale=METODOS_PAGO_VALE,
        estado_filtro=estado_filtro,
        asesor_id_filtro=asesor_id_filtro,
        fecha_filtro=fecha_filtro,
        kpis=kpis
    )


@vales_bp.route('/solicitar', methods=['POST'])
@login_required
def solicitar():
    """Permite al vendedor (o admin) enviar una solicitud de vale indicando el asesor, local y la cantidad."""
    asesor_id = request.form.get('asesor_id', type=int)
    monto_raw = request.form.get('monto', '0')
    concepto = request.form.get('concepto', '').strip()
    branch_form_id = request.form.get('branch_id', type=int)

    if not asesor_id:
        flash('Debes seleccionar el asesor que solicita el vale.', 'danger')
        return redirect(url_for('vales_bp.index'))

    asesor = Asesor.query.get(asesor_id)
    if not asesor or not asesor.activo:
        flash('El asesor seleccionado no existe o no se encuentra activo.', 'danger')
        return redirect(url_for('vales_bp.index'))

    codigo_ingresado = (request.form.get('codigo_asesor') or '').strip().upper()
    codigo_esperado = (asesor.codigo or f"ASE-{asesor.id:03d}").strip().upper()
    if not codigo_ingresado or codigo_ingresado != codigo_esperado:
        flash(f"El código personal ingresado para el asesor '{asesor.nombre}' es incorrecto.", 'danger')
        return redirect(url_for('vales_bp.index'))

    try:
        monto_clean = str(monto_raw).replace('$', '').replace('.', '').replace(',', '').strip()
        monto = Decimal(monto_clean)
        if monto <= 0:
            raise ValueError('La cantidad debe ser mayor a $0.')
    except Exception:
        flash('Ingresa una cantidad de dinero válida mayor a $0.', 'danger')
        return redirect(url_for('vales_bp.index'))

    branch_id = branch_form_id or get_active_branch_for_user()
    if not branch_id:
        b_def = Branch.query.filter_by(activa=True, tipo='tienda').order_by(Branch.id.asc()).first()
        branch_id = b_def.id if b_def else None

    comprobante_rel = None
    if 'comprobante' in request.files:
        file = request.files['comprobante']
        if file and file.filename:
            allowed_exts = {'.png', '.jpg', '.jpeg', '.webp', '.pdf'}
            ext = os.path.splitext(file.filename)[1].lower()
            if ext in allowed_exts:
                upload_folder = os.path.join(current_app.config['UPLOAD_FOLDER'], 'vales')
                os.makedirs(upload_folder, exist_ok=True)
                timestamp = datetime.now().strftime('%Y%m%d_%H%M%S_%f')
                clean_name = secure_filename(file.filename)
                fname = f"vale_{timestamp}_{clean_name}"
                file.save(os.path.join(upload_folder, fname))
                comprobante_rel = f"uploads/vales/{fname}"

    try:
        nuevo_vale = Vale(
            asesor_id=asesor.id,
            solicitado_por_id=current_user.id,
            branch_id=branch_id,
            monto=monto,
            concepto=concepto or None,
            comprobante=comprobante_rel,
            estado='PENDIENTE',
            fecha_solicitud=obtener_hora_bogota()
        )
        db.session.add(nuevo_vale)
        db.session.flush()

        AuditLog.registrar(
            action='SOLICITUD_VALE',
            user_id=current_user.id,
            motivo=f"Solicitud de vale #{nuevo_vale.id} para el asesor '{asesor.nombre}' por ${float(monto):,.0f}. {('Motivo: ' + concepto) if concepto else ''}",
            target_id=nuevo_vale.id,
            target_type='VALE'
        )

        db.session.commit()
        flash(f"Solicitud de vale #VAL-{nuevo_vale.id:04d} para '{asesor.nombre}' por ${float(monto):,.0f} enviada exitosamente al administrador.", 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Error al enviar la solicitud de vale: {str(e)}', 'danger')

    return redirect(url_for('vales_bp.index'))


@vales_bp.route('/<int:id>/aprobar', methods=['POST'])
@login_required
@admin_required
def aprobar(id):
    """
    El Administrador aprueba la solicitud de vale seleccionando el Local y el Método de Pago
    de donde salió el dinero, generando automáticamente el Gasto en ese local y el movimiento en Bancos.
    """
    vale = Vale.query.get_or_404(id)
    if vale.estado != 'PENDIENTE':
        flash(f'El vale #VAL-{vale.id:04d} ya fue procesado anteriormente ({vale.estado}).', 'warning')
        return redirect(url_for('vales_bp.index'))

    branch_id_pago = request.form.get('branch_id_pago', type=int) or vale.branch_id or (vale.solicitado_por.branch_id if vale.solicitado_por else None)
    metodo_pago = (request.form.get('metodo_pago') or 'efectivo').strip().lower()
    observacion = request.form.get('observacion_resolucion', '').strip()

    branch_obj = Branch.query.get(branch_id_pago) if branch_id_pago else None
    if not branch_obj or branch_obj.tipo != 'tienda':
        branch_obj = Branch.query.filter_by(activa=True, tipo='tienda').order_by(Branch.id.asc()).first()

    if not branch_obj:
        flash('Debes seleccionar un Local comercial válido de donde salió el dinero del vale.', 'danger')
        return redirect(url_for('vales_bp.index'))

    comprobante_rel = None
    if 'comprobante' in request.files:
        file = request.files['comprobante']
        if file and file.filename:
            allowed_exts = {'.png', '.jpg', '.jpeg', '.webp', '.pdf'}
            ext = os.path.splitext(file.filename)[1].lower()
            if ext in allowed_exts:
                upload_folder = os.path.join(current_app.config['UPLOAD_FOLDER'], 'vales')
                os.makedirs(upload_folder, exist_ok=True)
                timestamp = datetime.now().strftime('%Y%m%d_%H%M%S_%f')
                clean_name = secure_filename(file.filename)
                fname = f"vale_{timestamp}_{clean_name}"
                file.save(os.path.join(upload_folder, fname))
                comprobante_rel = f"uploads/vales/{fname}"

    try:
        vale.estado = 'APROBADO'
        vale.branch_id = branch_obj.id
        vale.metodo_pago = metodo_pago
        vale.resuelto_por_id = current_user.id
        vale.observacion_resolucion = observacion or f'Autorizado y pagado desde {branch_obj.nombre} ({metodo_pago.capitalize()}).'
        vale.fecha_resolucion = obtener_hora_bogota()
        if comprobante_rel:
            vale.comprobante = comprobante_rel

        # 1. Generar automáticamente el Gasto (Expense) en el Local seleccionado
        gasto_vale = _sincronizar_gasto_vale(vale, branch_obj, metodo_pago, current_user.id)

        # 2. Descontar en Bancos / Métodos de Pago
        from services.bank_service import registrar_movimiento_banco
        nombre_asesor = vale.asesor.nombre if vale.asesor else 'Asesor'
        registrar_movimiento_banco(
            codigo_metodo=metodo_pago,
            monto=vale.monto,
            tipo_movimiento='EGRESO',
            origen='GASTO',
            descripcion=f'Vale #VAL-{vale.id:04d} a {nombre_asesor} [Desde: {branch_obj.nombre}]',
            referencia_id=gasto_vale.id,
            usuario_id=current_user.id
        )

        AuditLog.registrar(
            action='APROBACION_VALE',
            user_id=current_user.id,
            motivo=(
                f"Aprobación de vale #VAL-{vale.id:04d} para '{nombre_asesor}' por ${float(vale.monto):,.0f}. "
                f"Pagado desde {branch_obj.nombre} en {metodo_pago.capitalize()} (Gasto #{gasto_vale.id}). "
                f"Nota: {vale.observacion_resolucion}"
            ),
            target_id=vale.id,
            target_type='VALE'
        )

        db.session.commit()
        flash(
            f"✅ Vale #VAL-{vale.id:04d} de '{nombre_asesor}' por ${int(vale.monto):,} APROBADO. "
            f"Se generó el Gasto automáticamente en {branch_obj.nombre} ({metodo_pago.capitalize()}) y se descontó del saldo.".replace(',', '.'),
            'success'
        )
    except Exception as e:
        db.session.rollback()
        flash(f'Error al aprobar el vale: {str(e)}', 'danger')

    return redirect(url_for('vales_bp.index'))


@vales_bp.route('/<int:id>/actualizar-origen', methods=['POST'])
@login_required
@admin_required
def actualizar_origen_pago(id):
    """Permite al Administrador actualizar el Local o el Método de Pago de un vale ya aprobado y sincronizar su gasto."""
    vale = Vale.query.get_or_404(id)
    if vale.estado != 'APROBADO':
        flash('Solo se puede actualizar el origen de pago de un vale aprobado.', 'warning')
        return redirect(url_for('vales_bp.index'))

    branch_id_pago = request.form.get('branch_id_pago', type=int)
    metodo_pago = (request.form.get('metodo_pago') or 'efectivo').strip().lower()
    branch_obj = Branch.query.get(branch_id_pago) if branch_id_pago else None

    if not branch_obj or branch_obj.tipo != 'tienda':
        flash('Selecciona un Local comercial válido.', 'danger')
        return redirect(url_for('vales_bp.index'))

    try:
        metodo_ant = (vale.metodo_pago or 'efectivo').strip().lower()
        vale.branch_id = branch_obj.id
        vale.metodo_pago = metodo_pago
        gasto_vale = _sincronizar_gasto_vale(vale, branch_obj, metodo_pago, current_user.id)

        if metodo_ant != metodo_pago and (vale.monto or 0) > 0:
            from services.bank_service import registrar_movimiento_banco
            nombre_asesor = vale.asesor.nombre if vale.asesor else 'Asesor'
            registrar_movimiento_banco(
                codigo_metodo=metodo_ant,
                monto=vale.monto,
                tipo_movimiento='INGRESO',
                origen='AJUSTE_MANUAL',
                descripcion=f'Cambio método de Vale #VAL-{vale.id:04d} ({nombre_asesor})',
                referencia_id=gasto_vale.id,
                usuario_id=current_user.id
            )
            registrar_movimiento_banco(
                codigo_metodo=metodo_pago,
                monto=vale.monto,
                tipo_movimiento='EGRESO',
                origen='GASTO',
                descripcion=f'Vale #VAL-{vale.id:04d} a {nombre_asesor} [Desde: {branch_obj.nombre}]',
                referencia_id=gasto_vale.id,
                usuario_id=current_user.id
            )

        AuditLog.registrar(
            action='ACTUALIZACION_PAGO_VALE',
            user_id=current_user.id,
            motivo=f"Actualización de origen de pago del vale #VAL-{vale.id:04d}: Local {branch_obj.nombre}, Método {metodo_pago.capitalize()} (Gasto #{gasto_vale.id}).",
            target_id=vale.id,
            target_type='VALE'
        )
        db.session.commit()
        flash(
            f"✅ Origen de pago del vale #VAL-{vale.id:04d} actualizado a {branch_obj.nombre} ({metodo_pago.capitalize()}). "
            f"El Gasto y el Cierre de Caja (Arqueo) de ese día se actualizaron automáticamente sin necesidad de reabrir caja.",
            'success'
        )
    except Exception as e:
        db.session.rollback()
        flash(f'Error al actualizar el vale: {str(e)}', 'danger')

    return redirect(url_for('vales_bp.index'))


@vales_bp.route('/<int:id>/rechazar', methods=['POST'])
@login_required
@admin_required
def rechazar(id):
    """El Administrador rechaza la solicitud de vale y queda la trazabilidad."""
    vale = Vale.query.get_or_404(id)
    if vale.estado != 'PENDIENTE':
        flash(f'El vale #VAL-{vale.id:04d} ya fue procesado anteriormente ({vale.estado}).', 'warning')
        return redirect(url_for('vales_bp.index'))

    observacion = request.form.get('observacion_resolucion', '').strip()

    try:
        vale.estado = 'RECHAZADO'
        vale.resuelto_por_id = current_user.id
        vale.observacion_resolucion = observacion or 'Solicitud rechazada por administración.'
        vale.fecha_resolucion = obtener_hora_bogota()

        AuditLog.registrar(
            action='RECHAZO_VALE',
            user_id=current_user.id,
            motivo=f"Rechazo de vale #VAL-{vale.id:04d} para el asesor '{vale.asesor.nombre if vale.asesor else 'N/A'}' por ${float(vale.monto):,.0f}. Motivo: {vale.observacion_resolucion}",
            target_id=vale.id,
            target_type='VALE'
        )

        db.session.commit()
        flash(f"Vale #VAL-{vale.id:04d} de '{vale.asesor.nombre}' RECHAZADO.", 'info')
    except Exception as e:
        db.session.rollback()
        flash(f'Error al rechazar el vale: {str(e)}', 'danger')

    return redirect(url_for('vales_bp.index'))


@vales_bp.route('/<int:id>/adjuntar_comprobante', methods=['POST'])
@login_required
def adjuntar_comprobante(id):
    """Permite adjuntar o actualizar el soporte/comprobante de pago del vale."""
    vale = Vale.query.get_or_404(id)
    if 'comprobante' not in request.files:
        flash('No seleccionaste ningún archivo para adjuntar.', 'warning')
        return redirect(url_for('vales_bp.index'))

    file = request.files['comprobante']
    if not file or not file.filename:
        flash('Archivo no válido.', 'danger')
        return redirect(url_for('vales_bp.index'))

    allowed_exts = {'.png', '.jpg', '.jpeg', '.webp', '.pdf'}
    ext = os.path.splitext(file.filename)[1].lower()
    if ext not in allowed_exts:
        flash('Formato no permitido. Solo imágenes (.jpg, .jpeg, .png, .webp) o documentos PDF.', 'danger')
        return redirect(url_for('vales_bp.index'))

    try:
        upload_folder = os.path.join(current_app.config['UPLOAD_FOLDER'], 'vales')
        os.makedirs(upload_folder, exist_ok=True)
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S_%f')
        clean_name = secure_filename(file.filename)
        fname = f"vale_{timestamp}_{clean_name}"
        file.save(os.path.join(upload_folder, fname))
        vale.comprobante = f"uploads/vales/{fname}"
        db.session.commit()
        flash(f'Comprobante adjuntado exitosamente al vale #VAL-{vale.id:04d}.', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Error al subir el comprobante: {str(e)}', 'danger')

    return redirect(url_for('vales_bp.index'))


@vales_bp.route('/<int:id>/reversar', methods=['POST'])
@login_required
@admin_required
def reversar(id):
    """
    Permite al Administrador reversar un vale ya aprobado/rechazado (o eliminarlo)
    exigiendo obligatoriamente el PIN de seguridad (1234).
    - Elimina el Gasto (Expense) asociado para que deje de descontar en el local.
    - Reversa el movimiento en Bancos si estaba aprobado.
    - Puede devolver el vale a estado PENDIENTE (para volver a aprobarlo eligiendo local y método)
      o eliminarlo definitivamente.
    """
    token_ingresado = (request.form.get('token_secreto') or '').strip()
    expected_token = os.environ.get('DELETE_TOKEN', '1234').strip()
    if not token_ingresado or token_ingresado != expected_token:
        flash('🚫 PIN de seguridad incorrecto. Operación de reversión cancelada.', 'danger')
        return redirect(url_for('vales_bp.index'))

    vale = Vale.query.get_or_404(id)
    accion = (request.form.get('accion_reversion') or 'pendiente').strip().lower()
    motivo = (request.form.get('motivo_reversion') or 'Reversión autorizada con PIN para reprocesar vale.').strip()

    try:
        nombre_asesor = vale.asesor.nombre if vale.asesor else 'Asesor'
        monto_val = vale.monto or Decimal('0')
        estado_anterior = vale.estado
        metodo_anterior = (vale.metodo_pago or 'efectivo').strip().lower()
        sede_nombre = vale.branch.nombre if vale.branch else 'Local'
        gasto_id_eliminado = vale.expense_id

        # 1. Si tenía Gasto (Expense) asociado, eliminarlo y sincronizar arqueo cerrado si existía
        fecha_gasto_ant = vale.fecha_resolucion or vale.fecha_solicitud
        branch_id_ant = vale.branch_id
        if vale.expense_id:
            gasto_asociado = Expense.query.get(vale.expense_id)
            if gasto_asociado:
                fecha_gasto_ant = gasto_asociado.fecha_gasto or fecha_gasto_ant
                branch_id_ant = gasto_asociado.branch_id or branch_id_ant
            vale.expense_id = None
            db.session.flush()
            if gasto_asociado:
                db.session.delete(gasto_asociado)
                db.session.flush()
            if branch_id_ant and fecha_gasto_ant:
                _sincronizar_arqueo_cerrado_por_vale(branch_id_ant, fecha_gasto_ant)

        # 2. Si estaba APROBADO, devolver el saldo en Bancos / Métodos de pago
        if estado_anterior == 'APROBADO' and monto_val > 0:
            from services.bank_service import registrar_movimiento_banco
            registrar_movimiento_banco(
                codigo_metodo=metodo_anterior,
                monto=monto_val,
                tipo_movimiento='INGRESO',
                origen='AJUSTE_MANUAL',
                descripcion=f'Reversión de Vale #VAL-{vale.id:04d} ({nombre_asesor}) [PIN Autorizado - {sede_nombre}]',
                referencia_id=vale.id,
                usuario_id=current_user.id
            )

        if accion == 'eliminar':
            vale_num = vale.id
            AuditLog.registrar(
                action='ELIMINACION_VALE',
                user_id=current_user.id,
                motivo=(
                    f"Eliminación definitiva de vale #VAL-{vale_num:04d} ({nombre_asesor}) por ${float(monto_val):,.0f} "
                    f"[Estado previo: {estado_anterior}, Gasto eliminado: #{gasto_id_eliminado or 'N/A'}]. Motivo: {motivo}"
                ),
                target_id=vale_num,
                target_type='VALE'
            )
            db.session.delete(vale)
            db.session.commit()
            flash(
                f"🗑️ Vale #VAL-{vale_num:04d} de '{nombre_asesor}' eliminado definitivamente y gasto/saldo revertido.",
                'warning'
            )
        else:
            # Devolver a PENDIENTE para que el Administrador pueda aceptarlo nuevamente
            vale.estado = 'PENDIENTE'
            vale.resuelto_por_id = None
            vale.fecha_resolucion = None
            vale.observacion_resolucion = None
            vale.metodo_pago = None

            AuditLog.registrar(
                action='REVERSION_VALE',
                user_id=current_user.id,
                motivo=(
                    f"Reversión a PENDIENTE del vale #VAL-{vale.id:04d} ({nombre_asesor}) por ${float(monto_val):,.0f} "
                    f"[Estado previo: {estado_anterior}, Gasto anulado: #{gasto_id_eliminado or 'N/A'}]. Motivo: {motivo}"
                ),
                target_id=vale.id,
                target_type='VALE'
            )
            db.session.commit()
            flash(
                f"🔄 Vale #VAL-{vale.id:04d} de '{nombre_asesor}' por ${int(monto_val):,} revertido a PENDIENTE. "
                f"El gasto previo fue anulado y ya puedes darle 'Aceptar' nuevamente.".replace(',', '.'),
                'success'
            )
    except Exception as e:
        db.session.rollback()
        flash(f'Error al reversar el vale: {str(e)}', 'danger')

    return redirect(url_for('vales_bp.index'))
