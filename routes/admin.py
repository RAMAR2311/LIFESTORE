import os
import uuid
import re
from flask import Blueprint, render_template, abort, request, redirect, url_for, flash, session, jsonify, current_app
from flask_login import login_required, current_user
from models import db, Product, ProductVariant, Sale, User, Maneo, SaleDetail, SalePayment, StockAdjustment, Expense, Branch, CommissionPayment, CashShift, Retoma, Asesor, obtener_hora_bogota, AuditLog
from sqlalchemy import or_
from sqlalchemy.sql import func
from werkzeug.security import generate_password_hash
from werkzeug.utils import secure_filename
from decorators import admin_required
from decimal import Decimal
from datetime import datetime

admin_bp = Blueprint('admin_bp', __name__)

def get_next_branch_code(tipo='tienda'):
    """Calcula automáticamente el siguiente código correlativo según el tipo de sede."""
    prefix = 'LOC' if tipo == 'tienda' else 'BOD'
    branches = Branch.query.all()
    existing_nums = []
    for b in branches:
        code = (b.codigo or '').upper().strip()
        if prefix == 'BOD' and code == 'BOD':
            existing_nums.append(1)
        match = re.search(rf'^{prefix}(\d+)$', code)
        if match:
            existing_nums.append(int(match.group(1)))
    next_num = max(existing_nums) + 1 if existing_nums else (1 if prefix != 'BOD' else 2)
    return f"{prefix}{next_num}"


def procesar_logo_sucursal(file_storage, codigo):
    """
    Procesa, normaliza y adapta inteligentemente la imagen del logo subida para que quede perfecta en la factura.
    - Soporta PNG, JPG, JPEG, WEBP, SVG.
    - Si la imagen es gigante o pequeña, la recorta (quita bordes vacíos) y redimensiona proporcionalmente a máx 400x140.
    - Preserva transparencia y la guarda optimizada en static/uploads/logos/.
    """
    if not file_storage or file_storage.filename == '':
        return None

    ext = os.path.splitext(file_storage.filename)[1].lower()
    if ext not in ['.png', '.jpg', '.jpeg', '.webp', '.svg']:
        return None

    logo_folder = os.path.join(current_app.config['UPLOAD_FOLDER'], 'logos')
    os.makedirs(logo_folder, exist_ok=True)

    if ext == '.svg':
        clean_svg_name = secure_filename(f"logo_{codigo.lower()}_{uuid.uuid4().hex[:6]}.svg")
        file_storage.save(os.path.join(logo_folder, clean_svg_name))
        return f"/static/uploads/logos/{clean_svg_name}"

    try:
        from PIL import Image
        im = Image.open(file_storage.stream)
        if im.mode not in ('RGBA', 'RGB'):
            im = im.convert('RGBA')

        # Recortar márgenes transparentes si aplica
        if im.mode == 'RGBA':
            bbox = im.getbbox()
            if bbox:
                im = im.crop(bbox)

        # Redimensionar proporcionalmente para factura (máximo 400x140 manteniendo proporción)
        im.thumbnail((400, 140), Image.Resampling.LANCZOS)
        clean_png_name = secure_filename(f"logo_{codigo.lower()}_{uuid.uuid4().hex[:6]}.png")
        final_path = os.path.join(logo_folder, clean_png_name)
        im.save(final_path, 'PNG', optimize=True)
        return f"/static/uploads/logos/{clean_png_name}"
    except Exception as e:
        file_storage.seek(0)
        clean_filename = secure_filename(f"logo_{codigo.lower()}_{uuid.uuid4().hex[:6]}{ext}")
        file_storage.save(os.path.join(logo_folder, clean_filename))
        return f"/static/uploads/logos/{clean_filename}"


@admin_bp.route('/api/siguiente-codigo-sede', methods=['GET'])
@login_required
@admin_required
def api_siguiente_codigo_sede():
    """Retorna en vivo el siguiente código sugerido según el tipo de sede seleccionado."""
    tipo = request.args.get('tipo', 'tienda').strip().lower()
    codigo_sugerido = get_next_branch_code(tipo)
    return jsonify({'success': True, 'tipo': tipo, 'codigo': codigo_sugerido})

@admin_bp.route('/vendedores', methods=['GET', 'POST'])
@login_required
@admin_required
def vendedores():
    if request.method == 'POST':
        nombre = request.form.get('nombre')
        email = request.form.get('email')
        telefono = request.form.get('telefono')
        password = request.form.get('password')
        rol = request.form.get('rol', 'vendedor')
        branch_id = request.form.get('branch_id', type=int)
        
        # Validar obligatoriedad de branch_id para roles operativos (vendedor / bodega)
        if rol in ['vendedor', 'bodega'] and not branch_id:
            flash("La Sucursal asignada es obligatoria para usuarios con rol de Vendedor o Bodega.", "danger")
            return redirect(url_for('admin_bp.vendedores'))
        
        # Validar branch
        branch_obj = Branch.query.get(branch_id) if branch_id else None
        sucursal_nombre = branch_obj.nombre if branch_obj else ('GLOBAL' if rol == 'admin' else 'PRINCIPAL')
        
        # Se previene registrar vendedores con un mismo email para preservar la unicidad de las credenciales de acceso
        if User.query.filter_by(email=email).first():
            flash('Acción Denegada: Ese correo ya le pertenece a otro usuario.', 'danger')
        else:
            try:
                # Se aplica un hash a la contraseña para evitar guardar texto plano, previniendo exposición en caso de brechas
                nuevo_usuario = User(
                    nombre=nombre.strip(),
                    email=email.strip(),
                    telefono=telefono.strip() if telefono else None,
                    password_hash=generate_password_hash(password),
                    rol=rol,
                    sucursal=sucursal_nombre,
                    branch_id=branch_id
                )
                db.session.add(nuevo_usuario)
                db.session.commit()
                flash(f"¡Usuario '{nombre}' registrado con rol '{rol}' exitosamente!", "success")
            except Exception as e:
                db.session.rollback()
                flash('Ocurrió un error en la base de datos al intentar registrar al usuario.', 'danger')
            
        return redirect(url_for('admin_bp.vendedores'))
        
    # Se pasa la lista para poblar la tabla HTML de gestión de personal
    # Mostramos todos los usuarios que no son eliminados
    lista_vendedores = User.query.filter(User.rol != 'eliminado').order_by(User.nombre).all()
    todas_sucursales = Branch.query.filter_by(activa=True).order_by(Branch.nombre).all()
    return render_template('admin/vendedores.html', vendedores=lista_vendedores, sucursales=todas_sucursales)

@admin_bp.route('/vendedores/<int:id>/eliminar', methods=['POST'])
@login_required
@admin_required
def eliminar_vendedor(id):
    usuario = User.query.get_or_404(id)
    if usuario.id == current_user.id:
        flash("No puedes eliminar tu propia cuenta.", "danger")
        return redirect(url_for('admin_bp.vendedores'))
        
    try:
        # En lugar de hacer un delete() duro que rompe las llaves foráneas (ventas, facturas), hacemos un soft delete
        usuario.rol = 'eliminado'
        usuario.email = f"eliminado_{usuario.id}_{usuario.email}"
        db.session.commit()
        flash(f"¡Usuario '{usuario.nombre}' eliminado exitosamente!", "success")
    except Exception as e:
        db.session.rollback()
        flash("Ocurrió un error al intentar eliminar el usuario.", "danger")
        
    return redirect(url_for('admin_bp.vendedores'))

@admin_bp.route('/vendedores/<int:id>/editar', methods=['POST'])
@login_required
@admin_required
def editar_vendedor(id):
    usuario = User.query.get_or_404(id)
        
    nombre = request.form.get('nombre')
    telefono = request.form.get('telefono')
    rol = request.form.get('rol')
    password = request.form.get('password')
    branch_id_raw = request.form.get('branch_id')
    
    if usuario.id == current_user.id and rol and rol != 'admin':
        flash("No puedes quitarte tus propios permisos de administrador.", "danger")
        return redirect(url_for('admin_bp.vendedores'))
    
    try:
        if nombre:
            usuario.nombre = nombre.strip()
        if telefono is not None:
            usuario.telefono = telefono.strip()
        if rol:
            usuario.rol = rol
            
        target_rol = rol or usuario.rol
        if target_rol in ['vendedor', 'bodega']:
            if not branch_id_raw or branch_id_raw in ['', 'None']:
                if not usuario.branch_id:
                    flash("La Sucursal asignada es obligatoria para usuarios con rol de Vendedor o Bodega.", "danger")
                    return redirect(url_for('admin_bp.vendedores'))
            
        if branch_id_raw is not None:
            if branch_id_raw == '' or branch_id_raw == 'None':
                if target_rol in ['vendedor', 'bodega']:
                    flash("No puedes desasignar la sucursal de un Vendedor o Bodeguero.", "danger")
                    return redirect(url_for('admin_bp.vendedores'))
                usuario.branch_id = None
                usuario.sucursal = 'GLOBAL' if usuario.rol == 'admin' else 'PRINCIPAL'
            else:
                b_id = int(branch_id_raw)
                b_obj = Branch.query.get(b_id)
                usuario.branch_id = b_id
                if b_obj:
                    usuario.sucursal = b_obj.nombre

        if password and password.strip():
            usuario.password_hash = generate_password_hash(password)
            
        db.session.commit()
        flash(f"¡Usuario '{usuario.nombre}' actualizado exitosamente!", "success")
    except Exception as e:
        db.session.rollback()
        flash("Ocurrió un error al intentar actualizar el usuario.", "danger")
        
    return redirect(url_for('admin_bp.vendedores'))

from datetime import datetime, timedelta

@admin_bp.route('/dashboard')
@login_required
@admin_required
def dashboard():
    from models import Product, Sale, Maneo, Provider, Warranty, PriceApproval, BankAccount, SalePayment
    
    hoy = obtener_hora_bogota()
    periodo = request.args.get('periodo', 'mes').lower()
    mes_filtro = request.args.get('mes')

    MESES_ES = {
        1: 'Enero', 2: 'Febrero', 3: 'Marzo', 4: 'Abril',
        5: 'Mayo', 6: 'Junio', 7: 'Julio', 8: 'Agosto',
        9: 'Septiembre', 10: 'Octubre', 11: 'Noviembre', 12: 'Diciembre'
    }
    MESES_CORTO_ES = {
        1: 'Ene', 2: 'Feb', 3: 'Mar', 4: 'Abr',
        5: 'May', 6: 'Jun', 7: 'Jul', 8: 'Ago',
        9: 'Sep', 10: 'Oct', 11: 'Nov', 12: 'Dic'
    }

    # 1. Definición del rango temporal según el filtro seleccionado
    if mes_filtro and periodo == 'mes':
        try:
            año, mes = map(int, mes_filtro.split('-'))
            inicio_periodo = datetime(año, mes, 1, 0, 0, 0)
            if mes == 12:
                fin_periodo = datetime(año + 1, 1, 1, 0, 0, 0)
            else:
                fin_periodo = datetime(año, mes + 1, 1, 0, 0, 0)
            nombre_mes = MESES_ES.get(mes, f"Mes {mes}")
            texto_periodo = f"{nombre_mes} {año}"
        except Exception:
            inicio_periodo = hoy.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
            fin_periodo = hoy.replace(year=hoy.year + 1, month=1, day=1, hour=0, minute=0, second=0, microsecond=0) if hoy.month == 12 else hoy.replace(month=hoy.month + 1, day=1, hour=0, minute=0, second=0, microsecond=0)
            mes_filtro = hoy.strftime('%Y-%m')
            texto_periodo = f"{MESES_ES.get(hoy.month, '')} {hoy.year}"
    elif periodo == 'dia':
        inicio_periodo = hoy.replace(hour=0, minute=0, second=0, microsecond=0)
        fin_periodo = inicio_periodo + timedelta(days=1)
        texto_periodo = f"Hoy ({hoy.strftime('%d/%m/%Y')})"
        mes_filtro = hoy.strftime('%Y-%m')
    elif periodo == 'semana':
        # Semana actual de lunes a domingo
        inicio_periodo = (hoy - timedelta(days=hoy.weekday())).replace(hour=0, minute=0, second=0, microsecond=0)
        fin_periodo = inicio_periodo + timedelta(days=7)
        domingo = inicio_periodo + timedelta(days=6)
        texto_periodo = f"Semana ({inicio_periodo.day} {MESES_CORTO_ES.get(inicio_periodo.month, '')} - {domingo.day} {MESES_CORTO_ES.get(domingo.month, '')})"
        mes_filtro = hoy.strftime('%Y-%m')
    elif periodo == 'quincena':
        if hoy.day <= 15:
            inicio_periodo = hoy.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
            fin_periodo = hoy.replace(day=16, hour=0, minute=0, second=0, microsecond=0)
            texto_periodo = f"1ª Quincena (1-15 {MESES_CORTO_ES.get(hoy.month, '')})"
        else:
            inicio_periodo = hoy.replace(day=16, hour=0, minute=0, second=0, microsecond=0)
            fin_periodo = hoy.replace(year=hoy.year + 1, month=1, day=1, hour=0, minute=0, second=0, microsecond=0) if hoy.month == 12 else hoy.replace(month=hoy.month + 1, day=1, hour=0, minute=0, second=0, microsecond=0)
            ultimo_dia = (fin_periodo - timedelta(days=1)).day
            texto_periodo = f"2ª Quincena (16-{ultimo_dia} {MESES_CORTO_ES.get(hoy.month, '')})"
        mes_filtro = hoy.strftime('%Y-%m')
    else:
        periodo = 'mes'
        inicio_periodo = hoy.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        fin_periodo = hoy.replace(year=hoy.year + 1, month=1, day=1, hour=0, minute=0, second=0, microsecond=0) if hoy.month == 12 else hoy.replace(month=hoy.month + 1, day=1, hour=0, minute=0, second=0, microsecond=0)
        mes_filtro = hoy.strftime('%Y-%m')
        texto_periodo = f"{MESES_ES.get(hoy.month, '')} {hoy.year}"

    from flask import session
    from models import Branch, BranchStock

    active_branch_id = session.get('active_branch_id')
    active_branch_obj = Branch.query.get(active_branch_id) if active_branch_id else None

    # 2. Métricas de Ventas en el período (filtradas por sucursal si hay una seleccionada)
    ventas_query = Sale.query.filter(Sale.fecha_venta >= inicio_periodo, Sale.fecha_venta < fin_periodo)
    if active_branch_id:
        ventas_query = ventas_query.filter(Sale.branch_id == active_branch_id)

    total_ventas = db.session.query(func.sum(Sale.monto_total)).filter(
        Sale.fecha_venta >= inicio_periodo, Sale.fecha_venta < fin_periodo
    )
    if active_branch_id:
        total_ventas = total_ventas.filter(Sale.branch_id == active_branch_id)
    total_ventas = total_ventas.scalar() or 0.0

    conteo_ventas = ventas_query.count()

    # 3. Métricas de Bancos y Medios Digitales
    saldo_bancos_total = db.session.query(func.sum(BankAccount.saldo_actual)).filter(BankAccount.tipo != 'efectivo', BankAccount.activo == True).scalar() or 0.0
    
    recaudo_pagos_q = db.session.query(func.sum(SalePayment.monto))\
        .join(Sale, SalePayment.sale_id == Sale.id)\
        .filter(Sale.fecha_venta >= inicio_periodo, Sale.fecha_venta < fin_periodo)\
        .filter(SalePayment.metodo_pago.notin_(['efectivo', 'retoma']))
    if active_branch_id:
        recaudo_pagos_q = recaudo_pagos_q.filter(Sale.branch_id == active_branch_id)
    recaudo_pagos = recaudo_pagos_q.scalar() or 0.0
        
    ventas_con_pagos = db.session.query(SalePayment.sale_id).distinct()
    recaudo_directo_q = db.session.query(func.sum(Sale.monto_total))\
        .filter(Sale.fecha_venta >= inicio_periodo, Sale.fecha_venta < fin_periodo)\
        .filter(~Sale.id.in_(ventas_con_pagos))\
        .filter(Sale.metodo_pago.notin_(['efectivo', 'retoma']))
    if active_branch_id:
        recaudo_directo_q = recaudo_directo_q.filter(Sale.branch_id == active_branch_id)
    recaudo_directo = recaudo_directo_q.scalar() or 0.0
        
    recaudo_bancos_periodo = float(recaudo_pagos) + float(recaudo_directo)

    # 4. Métricas de Inventario y Operaciones
    if active_branch_id:
        total_productos = db.session.query(func.count(func.distinct(BranchStock.product_id))).filter(
            BranchStock.branch_id == active_branch_id,
            BranchStock.cantidad > 0
        ).scalar() or 0
        productos_bajo_stock = db.session.query(func.count(func.distinct(BranchStock.product_id))).filter(
            BranchStock.branch_id == active_branch_id,
            BranchStock.cantidad <= 5
        ).scalar() or 0
        maneos_activos = Maneo.query.filter_by(estado='PENDIENTE', branch_id=active_branch_id).count()
        garantias_pendientes = Warranty.query.filter_by(resolution='Pendiente', branch_id=active_branch_id).count()
    else:
        total_productos = Product.query.count()
        productos_bajo_stock = Product.query.filter(Product.cantidad_stock <= 10).count()
        maneos_activos = Maneo.query.filter_by(estado='PENDIENTE').count()
        garantias_pendientes = Warranty.query.filter_by(resolution='Pendiente').count()

    proveedores_activos = Provider.query.count()
    aprobaciones_pendientes = PriceApproval.query.filter_by(estado='pendiente').count()

    # 4.1 KPIs y Flujo de Traslados de la Jornada (Hoy)
    from models import StockTransfer, StockTransferItem
    inicio_hoy = hoy.replace(hour=0, minute=0, second=0, microsecond=0)
    fin_hoy = inicio_hoy + timedelta(days=1)

    # 1. En Tránsito (Pendientes)
    q_traslados_pend = StockTransfer.query.filter_by(status='PENDIENTE')
    if active_branch_id:
        q_traslados_pend = q_traslados_pend.filter(
            (StockTransfer.origin_branch_id == active_branch_id) | (StockTransfer.destination_branch_id == active_branch_id)
        )
    traslados_pendientes_count = q_traslados_pend.count()

    # 2. Enviados Hoy hacia Tiendas (origen bodega -> destino tienda)
    q_env_hoy = db.session.query(StockTransfer).join(
        Branch, StockTransfer.destination_branch_id == Branch.id
    ).filter(
        StockTransfer.created_at >= inicio_hoy,
        StockTransfer.created_at < fin_hoy,
        Branch.tipo == 'tienda'
    )
    if active_branch_id:
        q_env_hoy = q_env_hoy.filter(
            (StockTransfer.origin_branch_id == active_branch_id) | (StockTransfer.destination_branch_id == active_branch_id)
        )
    enviados_hoy_tiendas = q_env_hoy.count()

    # 3. Devoluciones / Retornos a Bodega Hoy
    q_ret_hoy = db.session.query(StockTransfer).join(
        Branch, StockTransfer.destination_branch_id == Branch.id
    ).filter(
        StockTransfer.created_at >= inicio_hoy,
        StockTransfer.created_at < fin_hoy,
        Branch.tipo == 'bodega'
    )
    if active_branch_id:
        q_ret_hoy = q_ret_hoy.filter(
            (StockTransfer.origin_branch_id == active_branch_id) | (StockTransfer.destination_branch_id == active_branch_id)
        )
    retornos_hoy_bodega = q_ret_hoy.count()

    # 4. Completados y Rechazados Hoy
    q_comp_hoy = StockTransfer.query.filter(
        StockTransfer.resolved_at >= inicio_hoy,
        StockTransfer.resolved_at < fin_hoy,
        StockTransfer.status == 'ACEPTADO'
    )
    q_rech_hoy = StockTransfer.query.filter(
        StockTransfer.resolved_at >= inicio_hoy,
        StockTransfer.resolved_at < fin_hoy,
        StockTransfer.status == 'RECHAZADO'
    )
    if active_branch_id:
        q_comp_hoy = q_comp_hoy.filter(
            (StockTransfer.origin_branch_id == active_branch_id) | (StockTransfer.destination_branch_id == active_branch_id)
        )
        q_rech_hoy = q_rech_hoy.filter(
            (StockTransfer.origin_branch_id == active_branch_id) | (StockTransfer.destination_branch_id == active_branch_id)
        )
    completados_hoy = q_comp_hoy.count()
    rechazados_hoy = q_rech_hoy.count()
    total_resueltos_hoy = completados_hoy + rechazados_hoy
    tasa_exito_recepcion = round((completados_hoy / total_resueltos_hoy * 100), 1) if total_resueltos_hoy > 0 else 100.0

    # 5. Lista rápida de Traslados Activos y de la Jornada
    q_jornada = StockTransfer.query.filter(
        (StockTransfer.status == 'PENDIENTE') | (StockTransfer.created_at >= inicio_hoy)
    )
    if active_branch_id:
        q_jornada = q_jornada.filter(
            (StockTransfer.origin_branch_id == active_branch_id) | (StockTransfer.destination_branch_id == active_branch_id)
        )
    traslados_jornada = q_jornada.order_by(
        StockTransfer.status.asc(), # PENDIENTE primero
        StockTransfer.created_at.desc()
    ).limit(15).all()

    # 5. Si es vista global (active_branch_id is None), calcular resumen comparativo por sucursal
    comparativa_sucursales = []
    if not active_branch_id:
        todas_sucursales = Branch.query.filter_by(activa=True).all()
        for b in todas_sucursales:
            v_sum = db.session.query(func.sum(Sale.monto_total)).filter(
                Sale.branch_id == b.id,
                Sale.fecha_venta >= inicio_periodo,
                Sale.fecha_venta < fin_periodo
            ).scalar() or 0.0

            v_count = Sale.query.filter(
                Sale.branch_id == b.id,
                Sale.fecha_venta >= inicio_periodo,
                Sale.fecha_venta < fin_periodo
            ).count()

            g_sum = db.session.query(func.sum(Expense.monto)).filter(
                Expense.branch_id == b.id,
                Expense.fecha_gasto >= inicio_periodo,
                Expense.fecha_gasto < fin_periodo
            ).scalar() or 0.0

            comparativa_sucursales.append({
                'id': b.id,
                'nombre': b.nombre,
                'codigo': b.codigo,
                'tipo': b.tipo,
                'ventas_total': float(v_sum),
                'conteo_ventas': v_count,
                'gastos_total': float(g_sum)
            })

    # 6. Alertas de Horario en Puntos de Venta (Aperturas > 9:30 AM o Cierres > 7:30 PM)
    from models import CashShift, Asesor
    turnos_alertas_q = CashShift.query.filter(
        (CashShift.apertura_tardia == True) | (CashShift.cierre_tardio == True),
        CashShift.fecha_apertura >= inicio_hoy
    ).order_by(CashShift.fecha_apertura.desc())
    if active_branch_id:
        turnos_alertas_q = turnos_alertas_q.filter(CashShift.branch_id == active_branch_id)
    turnos_con_alerta = turnos_alertas_q.all()
    todos_asesores_map = {a.id: a.nombre for a in Asesor.query.all()}

    return render_template('admin/dashboard.html', 
                           total_productos=total_productos,
                           productos_bajo_stock=productos_bajo_stock,
                           total_ventas=total_ventas,
                           conteo_ventas=conteo_ventas,
                           saldo_bancos_total=saldo_bancos_total,
                           recaudo_bancos_periodo=recaudo_bancos_periodo,
                           periodo_actual=periodo,
                           mes_filtro=mes_filtro,
                           texto_periodo=texto_periodo,
                           maneos_activos=maneos_activos,
                           proveedores_activos=proveedores_activos,
                           garantias_pendientes=garantias_pendientes,
                           aprobaciones_pendientes=aprobaciones_pendientes,
                           active_branch_obj=active_branch_obj,
                           comparativa_sucursales=comparativa_sucursales,
                           traslados_pendientes_count=traslados_pendientes_count,
                           enviados_hoy_tiendas=enviados_hoy_tiendas,
                           retornos_hoy_bodega=retornos_hoy_bodega,
                           completados_hoy=completados_hoy,
                           rechazados_hoy=rechazados_hoy,
                           tasa_exito_recepcion=tasa_exito_recepcion,
                           traslados_jornada=traslados_jornada,
                           turnos_con_alerta=turnos_con_alerta,
                           todos_asesores_map=todos_asesores_map)

@admin_bp.route('/aprobaciones')
@login_required
@admin_required
def aprobaciones():
    from models import PriceApproval
    from flask import request
    
    page = request.args.get('page', 1, type=int)
    paginated_lista = PriceApproval.query.order_by(PriceApproval.fecha_solicitud.desc()).paginate(page=page, per_page=25, error_out=False)
    return render_template('admin/aprobaciones.html', aprobaciones=paginated_lista)
@admin_bp.route('/maneos')
@login_required
def maneos():
    lista_maneos = Maneo.query.order_by(Maneo.fecha_prestamo.desc()).all()
    # Priorizar PENDIENTE temporalmente
    lista_maneos.sort(key=lambda m: 0 if m.estado == 'PENDIENTE' else 1)
    
    # Obtener productos activos con stock > 0 para el selector rápido de préstamos
    productos = Product.query.filter(Product.cantidad_stock > 0).order_by(Product.tipo_inventario.desc(), Product.nombre).all()
    return render_template('admin/maneos.html', maneos=lista_maneos, productos=productos)

@admin_bp.route('/maneos/prestar', methods=['POST'])
@login_required
def maneos_prestar():
    sku = request.form.get('sku', '').strip()
    cantidad = int(request.form.get('cantidad', 1))
    local_vecino = request.form.get('local_vecino', '').strip()
    variant_id_str = request.form.get('variant_id')

    if not sku:
        flash('Asegúrate de escanear o ingresar un SKU o IMEI válido.', 'danger')
        return redirect(url_for('admin_bp.maneos'))

    if not local_vecino:
        flash('Debes especificar el nombre del local vecino o persona.', 'danger')
        return redirect(url_for('admin_bp.maneos'))

    # Buscar por SKU, IMEI o IMEI2
    from sqlalchemy import or_
    producto = Product.query.filter(
        or_(
            Product.sku == sku,
            Product.imei == sku,
            Product.imei2 == sku
        )
    ).first()

    # Si no se encontró directo, intentar buscar en variantes si tiene IMEI o subcategoría
    if not producto:
        variante_busqueda = ProductVariant.query.filter(ProductVariant.nombre_variante.ilike(f"%{sku}%")).first()
        if variante_busqueda:
            producto = variante_busqueda.producto
            if not variant_id_str:
                variant_id_str = str(variante_busqueda.id)

    if not producto:
        flash(f'Error: No se encontró ningún producto o celular con el SKU o IMEI "{sku}".', 'danger')
        return redirect(url_for('admin_bp.maneos'))

    es_celular = (producto.tipo_inventario == 'celulares' or bool(producto.imei))
    if es_celular:
        cantidad = 1 # Cada celular físico con IMEI se presta de forma individual

    # Determinar si se seleccionó una variante
    variante = None
    if variant_id_str and variant_id_str.strip():
        variante = ProductVariant.query.get(int(variant_id_str))
        if not variante or variante.product_id != producto.id:
            flash('La subcategoría seleccionada no pertenece a este producto.', 'danger')
            return redirect(url_for('admin_bp.maneos'))
        
        if variante.cantidad_stock < cantidad:
            flash(f'Stock insuficiente en la subcategoría "{variante.nombre_variante}" para prestar {cantidad} uds. (Stock actual: {variante.cantidad_stock}).', 'danger')
            return redirect(url_for('admin_bp.maneos'))
    else:
        if producto.cantidad_stock < cantidad:
            flash(f'Stock insuficiente para prestar {cantidad} unids. (Stock actual: {producto.cantidad_stock}).', 'danger')
            return redirect(url_for('admin_bp.maneos'))

    try:
        # Descontar stock de la variante o del producto base
        if variante:
            stock_anterior = variante.cantidad_stock
            variante.cantidad_stock -= cantidad
            producto.cantidad_stock -= cantidad
        else:
            stock_anterior = producto.cantidad_stock
            producto.cantidad_stock -= cantidad

        nuevo_maneo = Maneo(
            product_id=producto.id,
            variant_id=variante.id if variante else None,
            local_vecino=local_vecino,
            cantidad=cantidad,
            estado='PENDIENTE'
        )
        db.session.add(nuevo_maneo)

        # Registro detallado en el Kardex
        detalle_extra = ''
        if es_celular and producto.imei:
            detalle_extra = f' [IMEI: {producto.imei}]'
        elif variante:
            detalle_extra = f' [{variante.nombre_variante}]'

        ajuste = StockAdjustment(
            product_id=producto.id,
            admin_id=current_user.id,
            tipo_movimiento=f'Préstamo (Maneo) a {local_vecino}{detalle_extra}',
            stock_anterior=stock_anterior,
            stock_nuevo=variante.cantidad_stock if variante else producto.cantidad_stock
        )
        db.session.add(ajuste)

        db.session.commit()
        flash(f'Maneo de "{producto.nombre}" prestado a {local_vecino} registrado y stock descontado exitosamente.', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Error al registrar el maneo: {str(e)}', 'danger')

    return redirect(url_for('admin_bp.maneos'))

@admin_bp.route('/maneos/facturar/<int:id>', methods=['POST'])
@login_required
def maneos_facturar(id):
    maneo = Maneo.query.get_or_404(id)
    if maneo.estado != 'PENDIENTE':
        flash('Este maneo ya fue resuelto.', 'warning')
        return redirect(url_for('admin_bp.maneos'))
    
    # Determinar precios según variante o producto base
    if maneo.variante:
        precio_sugerido_ref = float(maneo.variante.precio_sugerido or maneo.producto.precio_sugerido)
        precio_costo_ref = float(maneo.variante.precio_costo or maneo.producto.precio_costo)
        precio_minimo_ref = float(maneo.variante.precio_minimo or maneo.producto.precio_minimo)
    else:
        precio_sugerido_ref = float(maneo.producto.precio_sugerido)
        precio_costo_ref = float(maneo.producto.precio_costo)
        precio_minimo_ref = float(maneo.producto.precio_minimo)

    precio_venta = float(request.form.get('precio_venta', precio_sugerido_ref))
    cantidad_vendida = int(request.form.get('cantidad_vendida', maneo.cantidad))

    if cantidad_vendida <= 0 or cantidad_vendida > maneo.cantidad:
        flash(f'Operación rechazada: La cantidad vendida ({cantidad_vendida}) es inválida.', 'danger')
        return redirect(url_for('admin_bp.maneos'))

    precio_limite = precio_costo_ref if current_user.rol == 'admin' else precio_minimo_ref

    if float(precio_venta) < float(precio_limite):
        flash(f'Operación rechazada: El precio ingresado (${precio_venta}) es menor al límite autorizado para tu perfil de usuario (${precio_limite}).', 'danger')
        return redirect(url_for('admin_bp.maneos'))

    try:
        cantidad_no_vendida = maneo.cantidad - cantidad_vendida

        maneo.estado = 'FACTURADO'
        maneo.fecha_resolucion = obtener_hora_bogota()

        # Si hubo un cobro parcial, las unidades restantes vuelven al inventario
        if cantidad_no_vendida > 0:
            if maneo.variante:
                stock_anterior = maneo.variante.cantidad_stock
                maneo.variante.cantidad_stock += cantidad_no_vendida
                stock_nuevo = maneo.variante.cantidad_stock
            else:
                stock_anterior = maneo.producto.cantidad_stock
                maneo.producto.cantidad_stock += cantidad_no_vendida
                stock_nuevo = maneo.producto.cantidad_stock

            variante_label = f' [{maneo.variante.nombre_variante}]' if maneo.variante else ''
            ajuste_retorno = StockAdjustment(
                product_id=maneo.product_id,
                admin_id=current_user.id,
                tipo_movimiento=f'Dev. Parcial de Maneo ({maneo.local_vecino}){variante_label}',
                stock_anterior=stock_anterior,
                stock_nuevo=stock_nuevo
            )
            db.session.add(ajuste_retorno)
            
            # Actualizamos la cantidad del maneo a la realmente facturada para que el historial sea claro
            maneo.cantidad = cantidad_vendida

        metodo_pago_seleccionado = request.form.get('metodo_pago', 'efectivo')
        
        sucursal_actual = 'PRINCIPAL'
        es_celular = (maneo.producto.tipo_inventario == 'celulares' or bool(maneo.producto.imei))

        # Registrar la venta real del Maneo
        nueva_venta = Sale(
            vendedor_id=current_user.id,
            monto_total=(precio_venta * cantidad_vendida),
            metodo_pago=metodo_pago_seleccionado,
            sucursal=sucursal_actual,
            tipo_venta='celulares' if es_celular else 'general'
        )
        db.session.add(nueva_venta)
        db.session.flush() # forzar DB a darnos un ID para nueva_venta
        
        detalle = SaleDetail(
            sale_id=nueva_venta.id,
            product_id=maneo.product_id,
            variant_id=maneo.variant_id,
            cantidad_vendida=cantidad_vendida,
            precio_venta_final=precio_venta
        )
        db.session.add(detalle)

        # Registrar el pago en SalePayment para consistencia con pagos mixtos
        pago = SalePayment(
            sale_id=nueva_venta.id,
            metodo_pago=metodo_pago_seleccionado,
            monto=(precio_venta * cantidad_vendida)
        )
        db.session.add(pago)

        # Facturación automática al proveedor si es un celular/externo con proveedor y costo
        prod = maneo.producto
        if prod.proveedor and prod.tipo_inventario in ['celulares', 'externos']:
            from models import Provider, ProviderInvoice
            provider_obj = Provider.query.filter(Provider.nombre.ilike(prod.proveedor.strip())).first()
            if provider_obj and prod.precio_costo and prod.precio_costo > 0:
                ref_factura = prod.modelo_celular if prod.modelo_celular else prod.nombre
                if prod.imei:
                    ref_factura = f"{ref_factura} (IMEI: {prod.imei})"
                factura_prov = ProviderInvoice(
                    provider_id=provider_obj.id,
                    sale_id=nueva_venta.id,
                    monto_total=(prod.precio_costo * cantidad_vendida),
                    numero_factura=ref_factura,
                    descripcion=f"Facturación Maneo #{maneo.id} (Local: {maneo.local_vecino})"
                )
                db.session.add(factura_prov)
        
        db.session.commit()

        if cantidad_no_vendida > 0:
            flash(f'Maneo facturado parcialmente. Se registró la venta de ${precio_venta * cantidad_vendida} y se devolvieron {cantidad_no_vendida} uds al inventario.', 'success')
        else:
            flash(f'Maneo facturado totalmente. Se registró la venta de ${precio_venta * cantidad_vendida} en la caja.', 'success')
    except Exception as e:
        db.session.rollback()
        flash('Error al facturar el maneo.', 'danger')

    return redirect(url_for('admin_bp.maneos'))

@admin_bp.route('/maneos/devolver/<int:id>', methods=['POST'])
@login_required
def maneos_devolver(id):
    maneo = Maneo.query.get_or_404(id)
    if maneo.estado != 'PENDIENTE':
        flash('Este maneo ya fue resuelto.', 'warning')
        return redirect(url_for('admin_bp.maneos'))

    cantidad_devuelta = int(request.form.get('cantidad_devuelta', maneo.cantidad))

    if cantidad_devuelta <= 0:
        flash('La cantidad a devolver debe ser mayor a 0.', 'danger')
        return redirect(url_for('admin_bp.maneos'))

    if cantidad_devuelta > maneo.cantidad:
        flash(f'No puedes devolver más de {maneo.cantidad} unidades (las que están prestadas).', 'danger')
        return redirect(url_for('admin_bp.maneos'))

    try:
        # Devolver stock a la variante o al producto base
        if maneo.variante:
            stock_anterior = maneo.variante.cantidad_stock
            maneo.variante.cantidad_stock += cantidad_devuelta
            stock_nuevo = maneo.variante.cantidad_stock
        else:
            stock_anterior = maneo.producto.cantidad_stock
            maneo.producto.cantidad_stock += cantidad_devuelta
            stock_nuevo = maneo.producto.cantidad_stock

        variante_label = f' [{maneo.variante.nombre_variante}]' if maneo.variante else ''

        # Registro en el Kardex del retorno
        ajuste = StockAdjustment(
            product_id=maneo.product_id,
            admin_id=current_user.id,
            tipo_movimiento=f'Devolución de Maneo ({maneo.local_vecino}){variante_label}',
            stock_anterior=stock_anterior,
            stock_nuevo=stock_nuevo
        )
        db.session.add(ajuste)

        # Determinar si es devolución total o parcial
        if cantidad_devuelta >= maneo.cantidad:
            # Devolución total: se cierra el maneo
            maneo.estado = 'DEVUELTO'
            maneo.fecha_resolucion = obtener_hora_bogota()
            db.session.commit()
            flash(f'Maneo cerrado. Se devolvieron {cantidad_devuelta} unidades al inventario.', 'success')
        else:
            # Devolución parcial: se reduce la cantidad y el maneo sigue PENDIENTE
            unidades_restantes = maneo.cantidad - cantidad_devuelta
            maneo.cantidad = unidades_restantes
            db.session.commit()
            flash(f'Devolución parcial registrada. Se devolvieron {cantidad_devuelta} uds al inventario. Quedan {unidades_restantes} uds pendientes de cobrar.', 'info')

    except Exception as e:
        db.session.rollback()
        flash('Error al procesar la devolución.', 'danger')

    return redirect(url_for('admin_bp.maneos'))

@admin_bp.route('/balance-financiero', methods=['GET', 'POST'])
@login_required
@admin_required
def balance_financiero():
    if request.method == 'POST':
        fecha_inicio_str = request.form.get('fecha_inicio')
        fecha_fin_str = request.form.get('fecha_fin')
        ambito = request.form.get('ambito', 'consolidado')
    else:
        fecha_inicio_str = request.args.get('fecha_inicio')
        fecha_fin_str = request.args.get('fecha_fin')
        ambito = request.args.get('ambito', 'consolidado')

    hoy = obtener_hora_bogota()
    import calendar
    if not fecha_inicio_str or not fecha_fin_str:
        # Por defecto, el mes actual
        primer_dia = hoy.replace(day=1)
        ultimo_dia_mes = calendar.monthrange(hoy.year, hoy.month)[1]
        ultimo_dia = hoy.replace(day=ultimo_dia_mes)
        
        fecha_inicio_str = primer_dia.strftime('%Y-%m-%d')
        fecha_fin_str = ultimo_dia.strftime('%Y-%m-%d')

    from datetime import datetime, timedelta
    try:
        inicio_dt = datetime.strptime(fecha_inicio_str, '%Y-%m-%d')
        fin_dt = datetime.strptime(fecha_fin_str, '%Y-%m-%d')
        # Avanzamos límite al inicio del siguiente día matemáticamente
        fin_dt_query = fin_dt + timedelta(days=1)
    except ValueError:
        flash("Formato de fecha inválido.", "danger")
        return redirect(url_for('admin_bp.dashboard'))

    from flask import session
    from models import Retoma, Cliente, Provider, Expense, Sale, SaleDetail, Product, Branch, BranchStock

    active_branch_id = session.get('active_branch_id')
    active_branch_obj = Branch.query.get(active_branch_id) if active_branch_id else None
    ambito = active_branch_obj.nombre if active_branch_obj else 'Consolidado Global'

    # ----------------------------------------------------
    # 1. CARGA DE VENTAS SEGÚN PERÍODO (FILTRADA POR SUCURSAL SI APLICA)
    # ----------------------------------------------------
    sales_q = Sale.query.filter(Sale.fecha_venta >= inicio_dt, Sale.fecha_venta < fin_dt_query)
    if active_branch_id:
        sales_q = sales_q.filter(Sale.branch_id == active_branch_id)
    ventas_query = sales_q.all()

    def calcular_metricas_ventas(lista_ventas):
        brutas = Decimal('0.00')
        costos = Decimal('0.00')
        efectivo = Decimal('0.00')
        transferencia = Decimal('0.00')
        retoma = Decimal('0.00')

        for v in lista_ventas:
            for d in v.detalles:
                cant = d.cantidad_vendida or 1
                pv = Decimal(str(d.precio_venta_final or 0))
                brutas += (pv * cant)

                if d.nombre_manual:
                    costos += Decimal(str(d.precio_costo_manual or 0)) * cant
                elif d.variant_id:
                    var = d.variante
                    p = d.producto or (var.producto if var else None)
                    c_u = (var.precio_costo if (var and var.precio_costo is not None) else (p.precio_costo if p else Decimal('0.00'))) or Decimal('0.00')
                    costos += Decimal(str(c_u)) * cant
                elif d.product_id:
                    p = d.producto
                    if p:
                        costos += Decimal(str(p.precio_costo or 0)) * cant

            if v.pagos:
                for p in v.pagos:
                    if p.metodo_pago == 'efectivo':
                        efectivo += Decimal(str(p.monto or 0))
                    elif p.metodo_pago != 'retoma':
                        transferencia += Decimal(str(p.monto or 0))
            else:
                if v.metodo_pago == 'efectivo':
                    efectivo += Decimal(str(v.monto_total or 0))
                elif v.metodo_pago != 'retoma':
                    transferencia += Decimal(str(v.monto_total or 0))

            for r in v.retomas_asociadas:
                retoma += Decimal(str(r.valor_retoma or 0))

        utilidad = brutas - costos
        margen = (utilidad / brutas * 100) if brutas > 0 else Decimal('0.00')

        return {
            'ventas_brutas': float(brutas),
            'costos_directos': float(costos),
            'utilidad_bruta': float(utilidad),
            'margen_bruto_pct': float(margen),
            'ventas_efectivo': float(efectivo),
            'ventas_transferencia': float(transferencia),
            'ventas_retoma': float(retoma),
            'cantidad_ventas': len(lista_ventas)
        }

    res_activo = calcular_metricas_ventas(ventas_query)

    # ----------------------------------------------------
    # 2. GASTOS Y COSTOS INDIRECTOS (FILTRADOS POR SUCURSAL SI APLICA)
    # ----------------------------------------------------
    exp_q = Expense.query.filter(Expense.fecha_gasto >= inicio_dt, Expense.fecha_gasto < fin_dt_query)
    if active_branch_id:
        exp_q = exp_q.filter(Expense.branch_id == active_branch_id)
    gastos_auditar = exp_q.all()

    costos_indirectos = sum(Decimal(str(g.monto or 0)) for g in gastos_auditar if g.tipo_gasto == 'Costo Indirecto')
    gastos_operacionales = sum(
        Decimal(str(g.monto or 0)) for g in gastos_auditar
        if g.tipo_gasto == 'Gasto Diario' and (g.categoria or '').strip().lower() != 'pago prod. externo'
    )

    # ----------------------------------------------------
    # 3. CONSOLIDACIÓN P&L (RESULTADOS OPERATIVOS)
    # ----------------------------------------------------
    total_ingresos = Decimal(str(res_activo['ventas_brutas']))
    costos_directos = Decimal(str(res_activo['costos_directos']))
    utilidad_bruta = Decimal(str(res_activo['utilidad_bruta']))
    margen_bruto_pct = res_activo['margen_bruto_pct']

    total_salidas = costos_directos + costos_indirectos + gastos_operacionales
    balance_neto = total_ingresos - total_salidas
    margen_neto_pct = float((balance_neto / total_ingresos * 100)) if total_ingresos > 0 else 0.0

    # ----------------------------------------------------
    # 4. BALANCE GENERAL PATRIMONIAL (SITUACIÓN A LA FECHA)
    # ----------------------------------------------------
    inventario_celulares_propios = Decimal('0.00')
    inventario_celulares_externos = Decimal('0.00')
    inventario_accesorios = Decimal('0.00')
    inventario_total = Decimal('0.00')

    detalle_accesorios = []
    productos_stock = Product.query.filter(Product.cantidad_stock > 0).all()
    for p in productos_stock:
        if p.variantes:
            val_p = sum(
                Decimal(str((v.precio_costo if v.precio_costo is not None else p.precio_costo) or 0)) * v.cantidad_stock
                for v in p.variantes
            )
        else:
            val_p = Decimal(str(p.precio_costo or 0)) * p.cantidad_stock

        inventario_total += val_p

        # Clasificación transparente:
        # 1. Celulares Externos (consignación/prestados no enviados al inventario propio)
        if p.tipo_inventario == 'externos' or (p.sku and p.sku.startswith('EXT-')):
            inventario_celulares_externos += val_p
        # 2. Celulares Propios (con IMEI, modelo celular o tipo celulares)
        elif p.tipo_inventario == 'celulares' or bool(p.imei) or bool(p.modelo_celular):
            inventario_celulares_propios += val_p
        # 3. Accesorios y otros artículos de tienda
        else:
            inventario_accesorios += val_p
            if p.variantes:
                for v in p.variantes:
                    if (v.cantidad_stock or 0) > 0:
                        c_u = float(v.precio_costo or p.precio_costo or 0)
                        detalle_accesorios.append({
                            'id': p.id,
                            'nombre': f"{p.nombre} ({v.nombre_variante})",
                            'sku': p.sku,
                            'stock': v.cantidad_stock,
                            'costo_u': c_u,
                            'costo_total': c_u * v.cantidad_stock,
                            'inventario': 'PRINCIPAL'
                        })
            else:
                c_u = float(p.precio_costo or 0)
                detalle_accesorios.append({
                    'id': p.id,
                    'nombre': p.nombre,
                    'sku': p.sku,
                    'stock': p.cantidad_stock,
                    'costo_u': c_u,
                    'costo_total': c_u * p.cantidad_stock,
                    'inventario': 'PRINCIPAL'
                })

    inventario_celulares_total = inventario_celulares_propios + inventario_celulares_externos
    inventario_activo = inventario_total

    cartera_clientes = sum(Decimal(str(c.deuda_total or 0)) for c in Cliente.query.all() if (c.deuda_total or 0) > 0)
    cuentas_por_pagar_proveedores = sum(
        Decimal(str(prov.saldo_pendiente or 0)) for prov in Provider.query.all() if (prov.saldo_pendiente or 0) > 0
    )

    total_activos = inventario_activo + cartera_clientes
    total_pasivos = cuentas_por_pagar_proveedores
    patrimonio_neto = total_activos - total_pasivos

    datos_financieros = {
        'ambito': ambito,
        # Métricas del ámbito activo
        'total_ingresos': float(total_ingresos),
        'ventas_efectivo': res_activo['ventas_efectivo'],
        'ventas_transferencia': res_activo['ventas_transferencia'],
        'ventas_retoma': res_activo['ventas_retoma'],
        'cantidad_ventas': res_activo['cantidad_ventas'],
        'costos_directos': float(costos_directos),
        'utilidad_bruta': float(utilidad_bruta),
        'margen_bruto_pct': float(margen_bruto_pct),
        'costos_indirectos': float(costos_indirectos),
        'gastos_operacionales': float(gastos_operacionales),
        'total_salidas': float(total_salidas),
        'balance_neto': float(balance_neto),
        'margen_neto_pct': float(margen_neto_pct),
        'res_136': res_activo,
        'res_197': res_activo,
        # Balance General Patrimonial
        'inventario_valorado_total': float(inventario_total),
        'inventario_valorado_136': float(inventario_total),
        'inventario_valorado_197': 0.0,
        'inventario_valorado_activo': float(inventario_activo),
        'inventario_valorado_celulares': float(inventario_celulares_total),
        'inventario_celulares_propios': float(inventario_celulares_propios),
        'inventario_celulares_externos': float(inventario_celulares_externos),
        'inventario_valorado_accesorios': float(inventario_accesorios),
        'detalle_accesorios': detalle_accesorios,
        'conteo_accesorios': len(detalle_accesorios),
        'cartera_clientes': float(cartera_clientes),
        'total_activos': float(total_activos),
        'cuentas_por_pagar_proveedores': float(cuentas_por_pagar_proveedores),
        'total_pasivos': float(total_pasivos),
        'patrimonio_neto': float(patrimonio_neto)
    }

    return render_template(
        'admin/balance_reporte.html',
        fecha_inicio=fecha_inicio_str,
        fecha_fin=fecha_fin_str,
        fecha_generacion=hoy.strftime('%Y-%m-%d %H:%M'),
        datos=datos_financieros
    )

@admin_bp.route('/limpiar-accesorios-prueba', methods=['POST'])
@login_required
@admin_required
def limpiar_accesorios_prueba():
    prods = Product.query.filter(
        Product.tipo_inventario.notin_(['celulares', 'externos']),
        (Product.imei == None) | (Product.imei == '')
    ).all()

    modificados = 0
    for p in prods:
        if p.cantidad_stock > 0:
            p.cantidad_stock = 0
            modificados += 1
        if p.variantes:
            for v in p.variantes:
                if (v.cantidad_stock or 0) > 0:
                    v.cantidad_stock = 0
                    modificados += 1

    try:
        db.session.commit()
        flash(f'Inventario de accesorios/prueba ajustado a 0 unidades con éxito ({modificados} ítems actualizados).', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Error al ajustar inventario: {str(e)}', 'danger')

    fecha_inicio = request.form.get('fecha_inicio', '')
    fecha_fin = request.form.get('fecha_fin', '')
    ambito = request.form.get('ambito', 'consolidado')
    return redirect(url_for('admin_bp.balance_financiero', fecha_inicio=fecha_inicio, fecha_fin=fecha_fin, ambito=ambito))

def numero_a_letras(numero):
    """Convierte un número a letras en pesos colombianos (PESOS M/CTE)."""
    try:
        n = int(round(float(numero)))
    except (ValueError, TypeError):
        return ""
    if n == 0:
        return "CERO PESOS M/CTE"
    if n < 0:
        return "MENOS " + numero_a_letras(abs(n))

    unidades = ["", "UN", "DOS", "TRES", "CUATRO", "CINCO", "SEIS", "SIETE", "OCHO", "NUEVE"]
    decenas_10 = ["DIEZ", "ONCE", "DOCE", "TRECE", "CATORCE", "QUINCE", "DIECISEIS", "DIECISIETE", "DIECIOCHO", "DIECINUEVE"]
    decenas = ["", "DIEZ", "VEINTE", "TREINTA", "CUARENTA", "CINCUENTA", "SESENTA", "SETENTA", "OCHENTA", "NOVENTA"]
    veintis = ["VEINTE", "VEINTIUN", "VEINTIDOS", "VEINTITRES", "VEINTICUATRO", "VEINTICINCO", "VEINTISEIS", "VEINTISIETE", "VEINTIOCHO", "VEINTINUEVE"]
    centenas = ["", "CIENTO", "DOSCIENTOS", "TRESCIENTOS", "CUATROCIENTOS", "QUINIENTOS", "SEISCIENTOS", "SETECIENTOS", "OCHOCIENTOS", "NOVECIENTOS"]

    def _seccion(num):
        if num == 0:
            return ""
        if num == 100:
            return "CIEN"
        c = num // 100
        resto = num % 100
        cadena = centenas[c] if c < len(centenas) else ""
        if resto == 0:
            return cadena
        if cadena:
            cadena += " "
        if 10 <= resto <= 19:
            cadena += decenas_10[resto - 10]
        elif 20 <= resto <= 29:
            cadena += veintis[resto - 20]
        else:
            d = resto // 10
            u = resto % 10
            cadena += decenas[d]
            if d > 0 and u > 0:
                cadena += " Y " + unidades[u]
            elif u > 0:
                cadena += unidades[u]
        return cadena.strip()

    millones = n // 1000000
    miles = (n % 1000000) // 1000
    unidades_final = n % 1000

    partes = []
    if millones > 0:
        if millones == 1:
            partes.append("UN MILLON")
        else:
            partes.append(f"{_seccion(millones)} MILLONES")
    if miles > 0:
        if miles == 1:
            partes.append("MIL")
        else:
            partes.append(f"{_seccion(miles)} MIL")
    if unidades_final > 0:
        partes.append(_seccion(unidades_final))

    return " ".join(partes).strip() + " PESOS M/CTE"


@admin_bp.route('/ventas-vendedores', methods=['GET'])
@login_required
@admin_required
def ventas_vendedores():
    import calendar
    from datetime import datetime
    
    # Obtener todos los asesores (ordenados por nombre)
    asesores_lista = Asesor.query.order_by(Asesor.nombre).all()
    
    asesor_id = request.args.get('asesor_id', type=int)
    mes_seleccionado = request.args.get('mes', '').strip()
    porcentaje_comision_str = request.args.get('porcentaje_comision', '2.0').strip()
    
    try:
        porcentaje_num = Decimal(str(porcentaje_comision_str).replace('%', '').replace(',', '.').strip())
    except Exception:
        porcentaje_num = Decimal('2.0')

    # Si no hay mes seleccionado, por defecto usar el mes actual
    if not mes_seleccionado:
        mes_seleccionado = obtener_hora_bogota().strftime('%Y-%m')
        
    ventas = []
    ventas_procesadas = []
    retomas_procesadas = []
    pagos_comisiones = []
    asesor_filtro = None
    
    total_ventas_mes = Decimal('0.0')
    total_monto_vitrina = Decimal('0.0')
    total_comision_vitrina = Decimal('0.0')
    total_comision_retomas = Decimal('0.0')
    total_comision_mes = Decimal('0.0')
    total_anticipos = Decimal('0.0')
    total_liquidado = Decimal('0.0')
    saldo_pendiente = Decimal('0.0')
    
    if asesor_id:
        asesor_filtro = Asesor.query.get(asesor_id)
        if asesor_filtro:
            try:
                year, month = map(int, mes_seleccionado.split('-'))
                last_day = calendar.monthrange(year, month)[1]
                start_date = datetime(year, month, 1, 0, 0, 0)
                end_date = datetime(year, month, last_day, 23, 59, 59)
                
                # 1. Ventas de Vitrina asociadas al asesor
                ventas = Sale.query.filter(
                    Sale.asesor_id == asesor_id,
                    Sale.fecha_venta >= start_date,
                    Sale.fecha_venta <= end_date
                ).order_by(Sale.fecha_venta.desc()).all()
                
                total_ventas_mes = sum(v.monto_total for v in ventas)

                for v in ventas:
                    monto_vitrina_venta = Decimal('0.0')
                    items_list = []

                    for d in v.detalles:
                        cant = d.cantidad_vendida or 1
                        precio_u = Decimal(str(d.precio_venta_final or 0))
                        subtot = precio_u * Decimal(str(cant))
                        monto_vitrina_venta += subtot
                        nom_item = d.producto.nombre if d.producto else (d.nombre_manual or 'Producto')
                        imei_item = d.producto.imei if (d.producto and d.producto.imei) else 'N/A'
                        items_list.append({
                            'nombre': nom_item,
                            'imei': imei_item,
                            'cantidad': cant,
                            'precio': precio_u,
                            'subtotal': subtot
                        })

                    comision_venta = monto_vitrina_venta * (porcentaje_num / Decimal('100.0'))
                    total_monto_vitrina += monto_vitrina_venta
                    total_comision_vitrina += comision_venta

                    ventas_procesadas.append({
                        'sale': v,
                        'monto_vitrina': monto_vitrina_venta,
                        'items_list': items_list,
                        'comision_venta': comision_venta
                    })

                # 2. Retomas: Bolsa del 15% sobre utilidad neta repartida entre asesores de turno
                todas_ventas_mes = Sale.query.filter(
                    Sale.fecha_venta >= start_date,
                    Sale.fecha_venta <= end_date
                ).order_by(Sale.fecha_venta.desc()).all()

                for v_mes in todas_ventas_mes:
                    shift_obj = v_mes.shift
                    if not shift_obj and v_mes.branch_id:
                        shift_obj = CashShift.query.filter(
                            CashShift.branch_id == v_mes.branch_id,
                            CashShift.fecha_apertura <= v_mes.fecha_venta,
                            or_(CashShift.fecha_cierre >= v_mes.fecha_venta, CashShift.fecha_cierre == None)
                        ).first()

                    asesores_turno_ids = shift_obj.lista_asesores_ids if shift_obj else []
                    if not asesores_turno_ids:
                        asesores_turno_ids = [v_mes.asesor_id] if v_mes.asesor_id else []

                    # Si el asesor consultado integró el turno de esa venta
                    if asesor_id in asesores_turno_ids:
                        num_asesores_turno = max(1, len(asesores_turno_ids))
                        for det in v_mes.detalles:
                            retomas_origen = []
                            if det.producto and det.producto.retoma_origen:
                                retomas_origen = det.producto.retoma_origen
                            elif det.producto_id:
                                retomas_origen = Retoma.query.filter_by(producto_generado_id=det.producto_id).all()

                            for ret_item in retomas_origen:
                                precio_vta = Decimal(str(det.precio_venta_final or 0))
                                costo_ret = Decimal(str(ret_item.valor_retoma or 0))
                                arreglos_val = Decimal(str(ret_item.arreglos or 0))
                                utilidad_neta = precio_vta - costo_ret - arreglos_val

                                if utilidad_neta > 0:
                                    bolsa_15 = utilidad_neta * Decimal('0.15')
                                    cuota_asesor = bolsa_15 / Decimal(str(num_asesores_turno))
                                    total_comision_retomas += cuota_asesor
                                    retomas_procesadas.append({
                                        'venta': v_mes,
                                        'retoma': ret_item,
                                        'producto_nombre': det.producto.nombre if det.producto else ret_item.modelo,
                                        'precio_venta': precio_vta,
                                        'costo_retoma': costo_ret,
                                        'arreglos': arreglos_val,
                                        'utilidad_neta': utilidad_neta,
                                        'bolsa_total': bolsa_15,
                                        'num_asesores': num_asesores_turno,
                                        'cuota_asesor': cuota_asesor
                                    })

                # 3. Consolidado Acumulado del Mes
                total_comision_mes = total_comision_vitrina + total_comision_retomas

                # 4. Historial de Anticipos y Pagos del Asesor en el Mes
                pagos_comisiones = CommissionPayment.query.filter(
                    CommissionPayment.asesor_id == asesor_id,
                    CommissionPayment.fecha_pago >= start_date,
                    CommissionPayment.fecha_pago <= end_date
                ).order_by(CommissionPayment.fecha_pago.desc()).all()

                for p in pagos_comisiones:
                    monto_pago = Decimal(str(p.monto or 0))
                    if p.tipo_pago == 'ANTICIPO':
                        total_anticipos += monto_pago
                    else:
                        total_liquidado += monto_pago

                total_pagado = total_anticipos + total_liquidado
                saldo_pendiente = max(Decimal('0.0'), total_comision_mes - total_pagado)

            except Exception as e:
                flash(f"Error al procesar comisiones: {str(e)}", 'danger')
                
    return render_template(
        'admin/ventas_vendedores.html',
        asesores=asesores_lista,
        asesor_id=asesor_id,
        asesor_filtro=asesor_filtro,
        mes_seleccionado=mes_seleccionado,
        porcentaje_comision=float(porcentaje_num),
        ventas=ventas,
        ventas_procesadas=ventas_procesadas,
        retomas_procesadas=retomas_procesadas,
        pagos_comisiones=pagos_comisiones,
        total_ventas_mes=total_ventas_mes,
        total_monto_vitrina=total_monto_vitrina,
        total_comision_vitrina=total_comision_vitrina,
        total_comision_retomas=total_comision_retomas,
        total_comision_mes=total_comision_mes,
        total_anticipos=total_anticipos,
        total_liquidado=total_liquidado,
        saldo_pendiente=saldo_pendiente
    )


@admin_bp.route('/comisiones/anticipo', methods=['POST'])
@login_required
@admin_required
def registrar_anticipo_comision():
    asesor_id = request.form.get('asesor_id', type=int)
    monto_raw = request.form.get('monto', '0')
    metodo_pago = request.form.get('metodo_pago', 'efectivo')
    notas = request.form.get('notas', '').strip()
    mes_origen = request.form.get('mes', obtener_hora_bogota().strftime('%Y-%m'))
    porcentaje = request.form.get('porcentaje_comision', '2.0')

    asesor = Asesor.query.get_or_404(asesor_id)
    try:
        monto_clean = str(monto_raw).replace('$', '').replace('.', '').replace(',', '').strip()
        monto = Decimal(monto_clean)
        if monto <= 0:
            raise ValueError("El monto debe ser mayor a 0.")
    except Exception as e:
        flash(f"Monto inválido para el anticipo: {str(e)}", "danger")
        return redirect(url_for('admin_bp.ventas_vendedores', asesor_id=asesor_id, mes=mes_origen, porcentaje_comision=porcentaje))

    try:
        nuevo_pago = CommissionPayment(
            asesor_id=asesor.id,
            monto=monto,
            tipo_pago='ANTICIPO',
            metodo_pago=metodo_pago,
            fecha_pago=obtener_hora_bogota(),
            registrado_por_id=current_user.id,
            notas=notas
        )
        db.session.add(nuevo_pago)
        db.session.commit()
        flash(f"Anticipo por ${monto:,.0f} registrado con éxito para {asesor.nombre}.", "success")
        return redirect(url_for('admin_bp.recibo_comision', payment_id=nuevo_pago.id))
    except Exception as e:
        db.session.rollback()
        flash(f"Error al registrar anticipo: {str(e)}", "danger")
        return redirect(url_for('admin_bp.ventas_vendedores', asesor_id=asesor_id, mes=mes_origen, porcentaje_comision=porcentaje))


@admin_bp.route('/comisiones/liquidar', methods=['POST'])
@login_required
@admin_required
def liquidar_saldo_comision():
    asesor_id = request.form.get('asesor_id', type=int)
    monto_raw = request.form.get('monto', '0')
    metodo_pago = request.form.get('metodo_pago', 'efectivo')
    notas = request.form.get('notas', '').strip()
    mes_origen = request.form.get('mes', obtener_hora_bogota().strftime('%Y-%m'))
    porcentaje = request.form.get('porcentaje_comision', '2.0')

    asesor = Asesor.query.get_or_404(asesor_id)
    try:
        monto_clean = str(monto_raw).replace('$', '').replace('.', '').replace(',', '').strip()
        monto = Decimal(monto_clean)
        if monto <= 0:
            raise ValueError("El monto a liquidar debe ser mayor a 0.")
    except Exception as e:
        flash(f"Monto de liquidación inválido: {str(e)}", "danger")
        return redirect(url_for('admin_bp.ventas_vendedores', asesor_id=asesor_id, mes=mes_origen, porcentaje_comision=porcentaje))

    try:
        nuevo_pago = CommissionPayment(
            asesor_id=asesor.id,
            monto=monto,
            tipo_pago='LIQUIDACION_TOTAL',
            metodo_pago=metodo_pago,
            fecha_pago=obtener_hora_bogota(),
            registrado_por_id=current_user.id,
            notas=notas
        )
        db.session.add(nuevo_pago)
        db.session.commit()
        flash(f"Liquidación por ${monto:,.0f} registrada con éxito para {asesor.nombre}.", "success")
        return redirect(url_for('admin_bp.recibo_comision', payment_id=nuevo_pago.id))
    except Exception as e:
        db.session.rollback()
        flash(f"Error al liquidar saldo: {str(e)}", "danger")
        return redirect(url_for('admin_bp.ventas_vendedores', asesor_id=asesor_id, mes=mes_origen, porcentaje_comision=porcentaje))


@admin_bp.route('/comisiones/recibo/<int:payment_id>', methods=['GET'])
@login_required
@admin_required
def recibo_comision(payment_id):
    pago = CommissionPayment.query.get_or_404(payment_id)
    asesor = pago.asesor
    monto_en_letras = numero_a_letras(pago.monto)
    
    # Sucursal para encabezado
    active_b_id = session.get('active_branch_id') or (current_user.branch_id if current_user.branch_id else 1)
    sucursal = Branch.query.get(active_b_id)
    if not sucursal:
        sucursal = Branch.query.first()

    # Calcular saldo pendiente del asesor en el mes del pago
    import calendar
    fecha_pago = pago.fecha_pago
    year, month = fecha_pago.year, fecha_pago.month
    last_day = calendar.monthrange(year, month)[1]
    start_date = datetime(year, month, 1, 0, 0, 0)
    end_date = datetime(year, month, last_day, 23, 59, 59)

    # Ventas de vitrina
    ventas = Sale.query.filter(Sale.asesor_id == asesor.id, Sale.fecha_venta >= start_date, Sale.fecha_venta <= end_date).all()
    comision_vitrina = sum(sum((d.precio_venta_final or 0) * (d.cantidad_vendida or 1) for d in v.detalles) for v in ventas) * Decimal('0.02')

    # Retomas
    comision_retomas = Decimal('0.0')
    todas_v = Sale.query.filter(Sale.fecha_venta >= start_date, Sale.fecha_venta <= end_date).all()
    for v_m in todas_v:
        s_obj = v_m.shift
        a_ids = s_obj.lista_asesores_ids if s_obj else ([v_m.asesor_id] if v_m.asesor_id else [])
        if asesor.id in a_ids:
            n_ases = max(1, len(a_ids))
            for d in v_m.detalles:
                rets = d.producto.retoma_origen if (d.producto and d.producto.retoma_origen) else []
                for r in rets:
                    uneta = Decimal(str(d.precio_venta_final or 0)) - Decimal(str(r.valor_retoma or 0)) - Decimal(str(r.arreglos or 0))
                    if uneta > 0:
                        comision_retomas += (uneta * Decimal('0.15')) / Decimal(str(n_ases))

    total_generado = comision_vitrina + comision_retomas
    # Pagos hasta este pago inclusive
    pagos_anteriores = CommissionPayment.query.filter(
        CommissionPayment.asesor_id == asesor.id,
        CommissionPayment.fecha_pago >= start_date,
        CommissionPayment.fecha_pago <= pago.fecha_pago
    ).all()
    total_abonado = sum(p.monto for p in pagos_anteriores)
    saldo_restante = max(Decimal('0.0'), total_generado - total_abonado)

    return render_template(
        'admin/comprobante_comision.html',
        pago=pago,
        asesor=asesor,
        sucursal=sucursal,
        monto_en_letras=monto_en_letras,
        saldo_restante=saldo_restante
    )

@admin_bp.route('/asesores', methods=['GET', 'POST'])
@login_required
@admin_required
def asesores():
    from models import Asesor
    if request.method == 'POST':
        nombre = request.form.get('nombre')
        if not nombre or not nombre.strip():
            flash('Acción Denegada: El nombre del asesor no puede estar vacío.', 'danger')
        else:
            try:
                nuevo_asesor = Asesor(nombre=nombre.strip(), activo=True)
                db.session.add(nuevo_asesor)
                db.session.commit()
                flash(f"¡Asesor '{nombre.strip()}' registrado exitosamente!", "success")
            except Exception as e:
                db.session.rollback()
                flash('Ocurrió un error al registrar el asesor.', 'danger')
        return redirect(url_for('admin_bp.asesores'))
        
    lista_asesores = Asesor.query.order_by(Asesor.nombre).all()
    return render_template('admin/asesores.html', asesores=lista_asesores)

@admin_bp.route('/asesores/<int:id>/editar', methods=['POST'])
@login_required
@admin_required
def editar_asesor(id):
    from models import Asesor
    asesor = Asesor.query.get_or_404(id)
    nombre = request.form.get('nombre')
    if not nombre or not nombre.strip():
        flash('El nombre del asesor no puede estar vacío.', 'danger')
    else:
        try:
            asesor.nombre = nombre.strip()
            db.session.commit()
            flash('Asesor actualizado correctamente.', 'success')
        except Exception as e:
            db.session.rollback()
            flash('Error al actualizar el asesor.', 'danger')
    return redirect(url_for('admin_bp.asesores'))

@admin_bp.route('/asesores/<int:id>/toggle', methods=['POST'])
@login_required
@admin_required
def toggle_asesor(id):
    from models import Asesor
    asesor = Asesor.query.get_or_404(id)
    try:
        asesor.activo = not asesor.activo
        db.session.commit()
        estado = "activado" if asesor.activo else "desactivado"
        flash(f"Asesor '{asesor.nombre}' {estado} correctamente.", "success")
    except Exception as e:
        db.session.rollback()
        flash('Error al cambiar el estado del asesor.', 'danger')
    return redirect(url_for('admin_bp.asesores'))

# ==========================================
# RUTAS DE GESTIÓN DE SUCURSALES (FASE 2)
# ==========================================

@admin_bp.route('/switch-branch', methods=['POST'])
@login_required
@admin_required
def switch_branch():
    """Cambia la sucursal activa en la sesión del administrador o restablece a vista global."""
    branch_id_raw = request.form.get('branch_id')
    if not branch_id_raw or branch_id_raw == 'None' or branch_id_raw == 'all':
        session.pop('active_branch_id', None)
        flash("Modo de visualización cambiado a: 'Todas las Sedes (Global)'.", "info")
    else:
        try:
            branch_id = int(branch_id_raw)
            branch = Branch.query.get(branch_id)
            if branch:
                session['active_branch_id'] = branch.id
                flash(f"Modo de visualización cambiado a: '{branch.nombre}'.", "success")
            else:
                session.pop('active_branch_id', None)
        except (ValueError, TypeError):
            session.pop('active_branch_id', None)

    return redirect(request.referrer or url_for('admin_bp.dashboard'))

@admin_bp.route('/sucursales/siguiente-codigo')
@login_required
@admin_required
def siguiente_codigo():
    """Retorna vía JSON el siguiente código correlativo disponible según el tipo de sede."""
    tipo = request.args.get('tipo', 'tienda')
    return jsonify({'codigo': get_next_branch_code(tipo)})

@admin_bp.route('/sucursales', methods=['GET', 'POST'])
@login_required
@admin_required
def sucursales():
    """Listado y creación de sucursales con código automático y carga de logo."""
    if request.method == 'POST':
        nombre = request.form.get('nombre', '').strip()
        codigo = request.form.get('codigo', '').strip().upper()
        tipo = request.form.get('tipo', 'tienda').strip()
        direccion = request.form.get('direccion', '').strip()
        telefono = request.form.get('telefono', '').strip()
        nombre_comercial = request.form.get('nombre_comercial', '').strip()
        nit = request.form.get('nit', '').strip()
        prefijo_factura = (request.form.get('prefijo_factura', '').strip() or 'FAC').upper()
        ultimo_consecutivo = request.form.get('ultimo_consecutivo', type=int) or 0
        resolucion_dian = request.form.get('resolucion_dian', '').strip()

        # Si el usuario no especificó código, auto-generarlo automáticamente
        if not codigo:
            codigo = get_next_branch_code(tipo)

        # Procesamiento y adaptación inteligente de archivo de logo adjunto
        logo_url = None
        if 'logo_file' in request.files:
            logo_url = procesar_logo_sucursal(request.files['logo_file'], codigo)

        if not logo_url:
            logo_url = request.form.get('logo_url', '').strip() or None

        if not nombre or not codigo:
            flash("El nombre y el código de la sucursal son obligatorios.", "danger")
            return redirect(url_for('admin_bp.sucursales'))

        if Branch.query.filter(Branch.codigo == codigo).first():
            flash(f"Ya existe una sucursal con el código '{codigo}'. Por favor usa otro.", "danger")
            return redirect(url_for('admin_bp.sucursales'))

        try:
            nueva_sucursal = Branch(
                nombre=nombre,
                codigo=codigo,
                tipo=tipo,
                direccion=direccion or None,
                telefono=telefono or None,
                nombre_comercial=nombre_comercial or None,
                nit=nit or None,
                prefijo_factura=prefijo_factura,
                ultimo_consecutivo=ultimo_consecutivo,
                logo_url=logo_url or None,
                resolucion_dian=resolucion_dian or None,
                activa=True
            )
            db.session.add(nueva_sucursal)
            db.session.commit()
            flash(f"Sucursal '{nombre}' creada exitosamente con código {codigo}.", "success")
        except Exception as e:
            db.session.rollback()
            flash(f"Error al crear sucursal: {str(e)}", "danger")

        return redirect(url_for('admin_bp.sucursales'))

    lista_sucursales = Branch.query.order_by(Branch.tipo.desc(), Branch.nombre.asc()).all()
    next_loc_code = get_next_branch_code('tienda')
    next_bod_code = get_next_branch_code('bodega')
    return render_template('admin/sucursales.html', sucursales=lista_sucursales, next_loc_code=next_loc_code, next_bod_code=next_bod_code)

@admin_bp.route('/sucursales/<int:id>/editar', methods=['POST'])
@login_required
@admin_required
def editar_sucursal(id):
    """Edición de datos comerciales, operativos y logo de una sucursal."""
    branch = Branch.query.get_or_404(id)
    nombre = request.form.get('nombre', '').strip()
    codigo = request.form.get('codigo', '').strip().upper()
    tipo = request.form.get('tipo', branch.tipo).strip()
    direccion = request.form.get('direccion', '').strip()
    telefono = request.form.get('telefono', '').strip()
    nombre_comercial = request.form.get('nombre_comercial', '').strip()
    nit = request.form.get('nit', '').strip()
    prefijo_factura = (request.form.get('prefijo_factura', '').strip() or branch.prefijo_factura or 'FAC').upper()
    ultimo_consecutivo = request.form.get('ultimo_consecutivo', type=int)
    resolucion_dian = request.form.get('resolucion_dian', '').strip()
    eliminar_logo = request.form.get('eliminar_logo') == '1'

    if not nombre or not codigo:
        flash("El nombre y el código son obligatorios.", "danger")
        return redirect(url_for('admin_bp.sucursales'))

    existente = Branch.query.filter((Branch.id != id) & (Branch.codigo == codigo)).first()
    if existente:
        flash(f"Ya existe otra sucursal con el código '{codigo}'.", "danger")
        return redirect(url_for('admin_bp.sucursales'))

    # Procesamiento y adaptación de archivo de logo
    logo_url = branch.logo_url
    if eliminar_logo:
        logo_url = None

    if 'logo_file' in request.files:
        nuevo_logo = procesar_logo_sucursal(request.files['logo_file'], codigo)
        if nuevo_logo:
            logo_url = nuevo_logo

    try:
        branch.nombre = nombre
        branch.codigo = codigo
        branch.tipo = tipo
        branch.direccion = direccion or None
        branch.telefono = telefono or None
        branch.nombre_comercial = nombre_comercial or None
        branch.nit = nit or None
        branch.prefijo_factura = prefijo_factura
        if ultimo_consecutivo is not None:
            branch.ultimo_consecutivo = ultimo_consecutivo
        branch.logo_url = logo_url
        branch.resolucion_dian = resolucion_dian or None
        db.session.commit()
        flash(f"Sucursal '{nombre}' actualizada correctamente.", "success")
    except Exception as e:
        db.session.rollback()
        flash(f"Error al actualizar sucursal: {str(e)}", "danger")

    return redirect(url_for('admin_bp.sucursales'))

@admin_bp.route('/sucursales/<int:id>/toggle', methods=['POST'])
@login_required
@admin_required
def toggle_sucursal(id):
    """Activa o desactiva una sucursal."""
    branch = Branch.query.get_or_404(id)
    try:
        branch.activa = not branch.activa
        db.session.commit()
        estado = "activada" if branch.activa else "desactivada"
        flash(f"Sucursal '{branch.nombre}' {estado} correctamente.", "success")
    except Exception as e:
        db.session.rollback()
        flash(f"Error al cambiar estado de sucursal: {str(e)}", "danger")

    return redirect(url_for('admin_bp.sucursales'))


@admin_bp.route('/auditoria', methods=['GET'])
@login_required
@admin_required
def auditoria():
    """Bitácora ejecutiva de decisiones administrativas de alto impacto y custodia."""
    page = request.args.get('page', 1, type=int)
    filtro_accion = request.args.get('accion', '').strip()
    filtro_usuario = request.args.get('usuario_id', type=int)
    filtro_fecha = request.args.get('fecha', '').strip()

    query = AuditLog.query

    if filtro_accion:
        query = query.filter(AuditLog.action == filtro_accion)
    if filtro_usuario:
        query = query.filter(AuditLog.user_id == filtro_usuario)
    if filtro_fecha:
        try:
            f_obj = datetime.strptime(filtro_fecha, '%Y-%m-%d').date()
            query = query.filter(db.func.date(AuditLog.timestamp) == f_obj)
        except ValueError:
            pass

    logs_paginados = query.order_by(AuditLog.timestamp.desc()).paginate(page=page, per_page=25, error_out=False)

    usuarios = User.query.filter_by(activo=True).order_by(User.nombre.asc()).all()
    acciones_disponibles = [
        ('APROBACION_PRECIO_MINIMO', 'Aprobación de Precio Mínimo'),
        ('RECHAZO_PRECIO_MINIMO', 'Rechazo de Precio Mínimo'),
        ('CANCELACION_VENTA', 'Cancelación de Venta'),
        ('RECEPCION_TRASLADO', 'Recepción de Traslado'),
        ('RECHAZO_TRASLADO', 'Rechazo de Traslado'),
        ('ENTREGA_GARANTIA', 'Entrega de Garantía'),
        ('REAPERTURA_TURNO', 'Reapertura de Turno'),
        ('SOLICITUD_VALE', 'Solicitud de Vale'),
        ('APROBACION_VALE', 'Aprobación de Vale'),
        ('RECHAZO_VALE', 'Rechazo de Vale')
    ]

    return render_template(
        'admin/auditoria.html',
        logs=logs_paginados,
        usuarios=usuarios,
        acciones_disponibles=acciones_disponibles,
        filtro_accion=filtro_accion,
        filtro_usuario=filtro_usuario,
        filtro_fecha=filtro_fecha
    )


