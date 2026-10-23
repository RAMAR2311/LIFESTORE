from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify, session, abort
from flask_login import login_required, current_user
from models import db, Branch, Product, ProductVariant, BranchStock, StockTransfer, StockTransferItem, StockAdjustment, obtener_hora_bogota, AuditLog
from services.stock_service import get_or_create_branch_stock, sync_global_product_stock

transfers_bp = Blueprint('transfers_bp', __name__)

@transfers_bp.route('/', methods=['GET'])
@login_required
def index():
    tab = request.args.get('tab', 'pendientes').strip()

    active_b_id = None
    if current_user.rol == 'admin':
        active_b_id = session.get('active_branch_id')
    else:
        active_b_id = current_user.branch_id

    # 1. Pendientes por recibir
    query_pendientes = StockTransfer.query.filter_by(status='PENDIENTE')
    if current_user.rol != 'admin':
        query_pendientes = query_pendientes.filter(StockTransfer.destination_branch_id == active_b_id)
    elif active_b_id:
        query_pendientes = query_pendientes.filter(StockTransfer.destination_branch_id == active_b_id)
    pendientes = query_pendientes.order_by(StockTransfer.created_at.desc()).all()

    # 2. Enviados
    query_enviados = StockTransfer.query
    if current_user.rol != 'admin':
        query_enviados = query_enviados.filter(StockTransfer.origin_branch_id == active_b_id)
    elif active_b_id:
        query_enviados = query_enviados.filter(StockTransfer.origin_branch_id == active_b_id)
    enviados = query_enviados.order_by(StockTransfer.created_at.desc()).all()

    # 3. Historial (Aceptados y Rechazados)
    query_historial = StockTransfer.query.filter(StockTransfer.status.in_(['ACEPTADO', 'RECHAZADO']))
    if current_user.rol != 'admin':
        query_historial = query_historial.filter(
            (StockTransfer.origin_branch_id == active_b_id) | (StockTransfer.destination_branch_id == active_b_id)
        )
    elif active_b_id:
        query_historial = query_historial.filter(
            (StockTransfer.origin_branch_id == active_b_id) | (StockTransfer.destination_branch_id == active_b_id)
        )
    historial = query_historial.order_by(StockTransfer.resolved_at.desc()).limit(50).all()

    return render_template(
        'transfers/index.html',
        tab=tab,
        pendientes=pendientes,
        enviados=enviados,
        historial=historial,
        active_b_id=active_b_id
    )

@transfers_bp.route('/nuevo', methods=['GET', 'POST'])
@login_required
def nuevo():
    sucursales_activas = Branch.query.filter_by(activa=True).order_by(Branch.tipo.desc(), Branch.nombre.asc()).all()

    # Determinar origen permitido según el rol
    user_branch_id = current_user.branch_id
    if current_user.rol != 'admin' and not user_branch_id:
        default_tienda = Branch.query.filter_by(tipo='tienda', activa=True).first()
        user_branch_id = default_tienda.id if default_tienda else 1

    if request.method == 'POST':
        if current_user.rol == 'admin':
            origin_branch_id = request.form.get('origin_branch_id', type=int)
        else:
            origin_branch_id = user_branch_id

        destination_branch_id = request.form.get('destination_branch_id', type=int)
        observaciones_entrega = request.form.get('observaciones_entrega', request.form.get('notas', '')).strip()
        notas = observaciones_entrega

        p_ids = request.form.getlist('product_id[]')
        v_ids = request.form.getlist('variant_id[]')
        cantidades = request.form.getlist('cantidad[]')

        if not origin_branch_id or not destination_branch_id:
            flash('Debes seleccionar la sucursal de origen y de destino.', 'danger')
            return redirect(url_for('transfers_bp.nuevo'))

        if origin_branch_id == destination_branch_id:
            flash('La sucursal de destino no puede ser la misma de origen.', 'warning')
            return redirect(url_for('transfers_bp.nuevo'))

        if not p_ids or len(p_ids) == 0:
            flash('Debes agregar al menos un producto al traslado.', 'warning')
            return redirect(url_for('transfers_bp.nuevo'))

        try:
            nuevo_traslado = StockTransfer(
                origin_branch_id=origin_branch_id,
                destination_branch_id=destination_branch_id,
                created_by_id=current_user.id,
                enviado_por_id=current_user.id,
                status='PENDIENTE',
                notas=notas,
                observaciones_entrega=observaciones_entrega
            )
            db.session.add(nuevo_traslado)
            db.session.flush()

            # Procesar cada ítem del traslado con bloqueo for_update
            items_creados = 0
            for i in range(len(p_ids)):
                if not p_ids[i]: continue
                pid = int(p_ids[i])
                vid = int(v_ids[i]) if (i < len(v_ids) and v_ids[i]) else None
                cant = int(cantidades[i] or 0) if i < len(cantidades) else 0

                if cant <= 0:
                    continue

                # 1. Bloquear y verificar stock de origen
                b_stock_origen = get_or_create_branch_stock(origin_branch_id, pid, vid, for_update=True)
                
                prod = Product.query.get(pid)
                prod_nombre = prod.nombre if prod else f'Producto #{pid}'

                if b_stock_origen.cantidad < cant:
                    db.session.rollback()
                    flash(f'Stock insuficiente en el origen para "{prod_nombre}". Disponible: {b_stock_origen.cantidad}, Solicitado: {cant}', 'danger')
                    return redirect(url_for('transfers_bp.nuevo'))

                # 2. Descontar inmediatamente del origen ("En Tránsito")
                stock_ant = b_stock_origen.cantidad
                b_stock_origen.cantidad -= cant
                sync_global_product_stock(pid, vid)

                # 3. Registrar ítem de traslado
                item = StockTransferItem(
                    transfer_id=nuevo_traslado.id,
                    product_id=pid,
                    variant_id=vid,
                    cantidad=cant
                )
                db.session.add(item)

                # 4. Registrar movimiento en StockAdjustment
                ajuste = StockAdjustment(
                    product_id=pid,
                    admin_id=current_user.id,
                    branch_id=origin_branch_id,
                    tipo_movimiento=f'TRASLADO_SALIDA hacia #{destination_branch_id} (Traslado #{nuevo_traslado.id})',
                    stock_anterior=stock_ant,
                    stock_nuevo=b_stock_origen.cantidad
                )
                db.session.add(ajuste)
                items_creados += 1

            if items_creados == 0:
                db.session.rollback()
                flash('No se añadieron ítems válidos con cantidad mayor a 0.', 'warning')
                return redirect(url_for('transfers_bp.nuevo'))

            db.session.commit()
            flash(f'Traslado #{nuevo_traslado.id} creado con éxito y puesto en estado PENDIENTE.', 'success')
            return redirect(url_for('transfers_bp.index'))

        except Exception as e:
            db.session.rollback()
            flash(f'Error al crear el traslado: {str(e)}', 'danger')
            return redirect(url_for('transfers_bp.nuevo'))

    # Para el formulario GET: lista de productos disponibles en el origen
    origen_id_inicial = user_branch_id if current_user.rol != 'admin' else (session.get('active_branch_id') or 1)
    return render_template(
        'transfers/nuevo.html',
        sucursales=sucursales_activas,
        user_branch_id=user_branch_id,
        origen_id_inicial=origen_id_inicial
    )

@transfers_bp.route('/<int:id>/accept', methods=['POST'])
@login_required
def accept(id):
    traslado = StockTransfer.query.get_or_404(id)

    if traslado.status != 'PENDIENTE':
        flash('Este traslado ya no se encuentra en estado PENDIENTE.', 'warning')
        return redirect(url_for('transfers_bp.index'))

    # Validar permisos: Destino o Admin
    es_admin = (current_user.rol == 'admin')
    es_destino = (current_user.branch_id == traslado.destination_branch_id)

    if not (es_admin or es_destino):
        flash('Solo un usuario asignado a la sucursal de destino o un Administrador puede aceptar este traslado.', 'danger')
        return redirect(url_for('transfers_bp.index'))

    # El creador no puede auto-aceptarse a menos que pertenezca al destino o sea admin
    if current_user.id == traslado.created_by_id and not es_admin and not es_destino:
        flash('No puedes auto-aceptar un traslado que tú mismo enviaste sin pertenecer a la sede destino.', 'danger')
        return redirect(url_for('transfers_bp.index'))

    observaciones_recepcion = request.form.get('observaciones_recepcion', '').strip()

    try:
        traslado.status = 'ACEPTADO'
        traslado.received_by_id = current_user.id
        traslado.recibido_por_id = current_user.id
        traslado.observaciones_recepcion = observaciones_recepcion
        traslado.resolved_at = obtener_hora_bogota()

        for item in traslado.items:
            b_stock_dest = get_or_create_branch_stock(traslado.destination_branch_id, item.product_id, item.variant_id, for_update=True)
            stock_ant = b_stock_dest.cantidad
            b_stock_dest.cantidad += item.cantidad
            sync_global_product_stock(item.product_id, item.variant_id)

            ajuste = StockAdjustment(
                product_id=item.product_id,
                admin_id=current_user.id,
                branch_id=traslado.destination_branch_id,
                tipo_movimiento=f'TRASLADO_ENTRADA desde #{traslado.origin_branch_id} (Traslado #{traslado.id})',
                stock_anterior=stock_ant,
                stock_nuevo=b_stock_dest.cantidad
            )
            db.session.add(ajuste)

        AuditLog.registrar(
            action='RECEPCION_TRASLADO',
            user_id=current_user.id,
            motivo=f'Recepción conforme de traslado #{traslado.id}. Novedades: {observaciones_recepcion or "Ninguna"}',
            target_id=traslado.id,
            target_type='TRANSFER'
        )

        db.session.commit()
        flash(f'Traslado #{traslado.id} ACEPTADO correctamente. Mercancía verificada e ingresada al stock de la sucursal destino.', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Error al aceptar el traslado: {str(e)}', 'danger')

    return redirect(url_for('transfers_bp.index'))

@transfers_bp.route('/<int:id>/reject', methods=['POST'])
@login_required
def reject(id):
    traslado = StockTransfer.query.get_or_404(id)

    if traslado.status != 'PENDIENTE':
        flash('Este traslado ya no se encuentra en estado PENDIENTE.', 'warning')
        return redirect(url_for('transfers_bp.index'))

    es_admin = (current_user.rol == 'admin')
    es_destino = (current_user.branch_id == traslado.destination_branch_id)

    if not (es_admin or es_destino):
        flash('Solo un usuario asignado a la sucursal de destino o un Administrador puede rechazar este traslado.', 'danger')
        return redirect(url_for('transfers_bp.index'))

    motivo = request.form.get('motivo', '').strip()

    try:
        traslado.status = 'RECHAZADO'
        traslado.received_by_id = current_user.id
        traslado.recibido_por_id = current_user.id
        traslado.observaciones_recepcion = f"RECHAZADO: {motivo}"
        traslado.resolved_at = obtener_hora_bogota()
        if motivo:
            traslado.notas = f"Motivo Rechazo: {motivo} | {traslado.notas or ''}".strip()

        AuditLog.registrar(
            action='RECHAZO_TRASLADO',
            user_id=current_user.id,
            motivo=f'Rechazo de traslado #{traslado.id}. Motivo: {motivo or "Sin justificación"}',
            target_id=traslado.id,
            target_type='TRANSFER'
        )

        # Reintegrar automáticamente al origen
        for item in traslado.items:
            b_stock_origen = get_or_create_branch_stock(traslado.origin_branch_id, item.product_id, item.variant_id, for_update=True)
            stock_ant = b_stock_origen.cantidad
            b_stock_origen.cantidad += item.cantidad
            sync_global_product_stock(item.product_id, item.variant_id)

            ajuste = StockAdjustment(
                product_id=item.product_id,
                admin_id=current_user.id,
                branch_id=traslado.origin_branch_id,
                tipo_movimiento=f'TRASLADO_RECHAZADO_REINTEGRO (Traslado #{traslado.id})',
                stock_anterior=stock_ant,
                stock_nuevo=b_stock_origen.cantidad
            )
            db.session.add(ajuste)

        db.session.commit()
        flash(f'Traslado #{traslado.id} RECHAZADO. El inventario ha sido reintegrado automáticamente a la sucursal de origen.', 'info')
    except Exception as e:
        db.session.rollback()
        flash(f'Error al rechazar el traslado: {str(e)}', 'danger')

    return redirect(url_for('transfers_bp.index'))

@transfers_bp.route('/api/productos-origen')
@login_required
def api_productos_origen():
    """Retorna los productos y variantes disponibles con stock > 0 en la sucursal de origen seleccionada."""
    branch_id = request.args.get('branch_id', type=int)
    if not branch_id:
        return jsonify([])

    stocks = BranchStock.query.filter(
        BranchStock.branch_id == branch_id,
        BranchStock.cantidad > 0
    ).all()

    items = []
    for s in stocks:
        if s.product:
            var_nombre = s.variant.nombre_variante if s.variant else None
            nombre_label = f"{s.product.nombre} ({var_nombre})" if var_nombre else s.product.nombre
            if s.product.imei:
                nombre_label += f" [IMEI: {s.product.imei}]"

            items.append({
                'product_id': s.product_id,
                'variant_id': s.variant_id,
                'sku': s.product.sku,
                'nombre': nombre_label,
                'stock_disponible': s.cantidad
            })

    return jsonify(items)

@transfers_bp.route('/api/buscar-imei', methods=['GET'])
@login_required
def api_buscar_imei():
    """Consulta en vivo para despacho ágil de celulares por escaneo directo de IMEI."""
    imei = request.args.get('imei', '').strip()
    branch_id = request.args.get('branch_id', type=int)

    if not imei:
        return jsonify({'error': 'Debes ingresar un número de IMEI para buscar.'}), 400

    if not branch_id:
        return jsonify({'error': 'Debes seleccionar una sucursal de origen antes de escanear.'}), 400

    from sqlalchemy import or_, func
    producto = Product.query.filter(
        or_(
            func.lower(Product.imei) == imei.lower(),
            func.lower(Product.imei2) == imei.lower()
        )
    ).first()

    if not producto:
        return jsonify({'error': f'El IMEI "{imei}" no está registrado en el inventario.'}), 404

    # Validar existencias activas en esa sede
    b_stock = BranchStock.query.filter_by(
        branch_id=branch_id,
        product_id=producto.id
    ).first()

    if not b_stock or b_stock.cantidad <= 0:
        # Verificar si está en otra sucursal para feedback inmediato
        otra_sede = BranchStock.query.filter(
            BranchStock.product_id == producto.id,
            BranchStock.cantidad > 0
        ).first()
        if otra_sede and otra_sede.branch:
            return jsonify({
                'error': f'El IMEI no se encuentra disponible en la sucursal de origen seleccionada (se encuentra en {otra_sede.branch.nombre}).'
            }), 400
        return jsonify({
            'error': f'El IMEI no se encuentra disponible en la sucursal de origen seleccionada.'
        }), 400

    return jsonify({
        'id': producto.id,
        'nombre': producto.nombre,
        'marca': producto.marca or '',
        'modelo_celular': producto.modelo_celular or '',
        'imei': producto.imei,
        'color': producto.color or '',
        'memoria': producto.memoria or '',
        'disponible': True
    })

from datetime import datetime, timedelta
import calendar

@transfers_bp.route('/trazabilidad', methods=['GET'])
@login_required
def trazabilidad():
    """
    Centro de Historial y Trazabilidad Avanzada (Kardex Multisucursal con Filtros de Rango).
    Exclusivo para roles admin y bodega (o vendedor con permiso de lectura local).
    """
    if current_user.rol not in ['admin', 'bodega', 'vendedor_bodega']:
        flash('Acceso restringido a administradores y personal de bodega.', 'warning')
        return redirect(url_for('sales_bp.index'))

    rango = request.args.get('rango', 'mes').lower()
    branch_filter = request.args.get('branch_id', type=str)
    tipo_filtro = request.args.get('tipo', '').strip()
    query_busqueda = request.args.get('q', '').strip()
    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 50, type=int)
    if per_page not in [25, 50, 100]:
        per_page = 50

    hoy = obtener_hora_bogota()
    hoy_date = hoy.date()

    fecha_inicio_str = request.args.get('fecha_inicio', '').strip()
    fecha_fin_str = request.args.get('fecha_fin', '').strip()

    # Cálculo del rango temporal
    if rango == 'hoy':
        dt_inicio = datetime(hoy.year, hoy.month, hoy.day, 0, 0, 0)
        dt_fin = dt_inicio + timedelta(days=1)
        label_rango = f"Hoy ({hoy.strftime('%d/%m/%Y')})"
    elif rango == '7dias':
        dt_inicio = (hoy - timedelta(days=7)).replace(hour=0, minute=0, second=0, microsecond=0)
        dt_fin = (hoy + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
        label_rango = "Últimos 7 días"
    elif rango == 'quincena':
        # Primera quincena (1-15) o Segunda quincena (16-fin de mes)
        if hoy.day <= 15:
            dt_inicio = datetime(hoy.year, hoy.month, 1, 0, 0, 0)
            dt_fin = datetime(hoy.year, hoy.month, 16, 0, 0, 0)
            label_rango = f"1ª Quincena {hoy.strftime('%B %Y')} (1 - 15)"
        else:
            _, ult_dia = calendar.monthrange(hoy.year, hoy.month)
            dt_inicio = datetime(hoy.year, hoy.month, 16, 0, 0, 0)
            if hoy.month == 12:
                dt_fin = datetime(hoy.year + 1, 1, 1, 0, 0, 0)
            else:
                dt_fin = datetime(hoy.year, hoy.month + 1, 1, 0, 0, 0)
            label_rango = f"2ª Quincena {hoy.strftime('%B %Y')} (16 - {ult_dia})"
    elif rango == 'custom' and fecha_inicio_str and fecha_fin_str:
        try:
            d_ini = datetime.strptime(fecha_inicio_str, '%Y-%m-%d')
            d_fin = datetime.strptime(fecha_fin_str, '%Y-%m-%d')
            dt_inicio = d_ini.replace(hour=0, minute=0, second=0)
            dt_fin = d_fin.replace(hour=23, minute=59, second=59, microsecond=999999)
            label_rango = f"Personalizado: {fecha_inicio_str} al {fecha_fin_str}"
        except Exception:
            dt_inicio = datetime(hoy.year, hoy.month, 1, 0, 0, 0)
            dt_fin = (hoy + timedelta(days=1)).replace(hour=0, minute=0, second=0)
            label_rango = f"Este Mes ({hoy.strftime('%B %Y')})"
    else: # 'mes' por defecto
        rango = 'mes'
        dt_inicio = datetime(hoy.year, hoy.month, 1, 0, 0, 0)
        if hoy.month == 12:
            dt_fin = datetime(hoy.year + 1, 1, 1, 0, 0, 0)
        else:
            dt_fin = datetime(hoy.year, hoy.month + 1, 1, 0, 0, 0)
        label_rango = f"Este Mes ({hoy.strftime('%B %Y')})"

    # Construcción de la consulta Kardex (StockAdjustment)
    query = StockAdjustment.query.join(Product, StockAdjustment.product_id == Product.id)

    # Filtro temporal
    query = query.filter(StockAdjustment.fecha_ajuste >= dt_inicio, StockAdjustment.fecha_ajuste < dt_fin)

    # Filtro de sucursal
    if current_user.rol != 'admin':
        # Bodega solo ve su bodega asignada a menos que sea global
        if current_user.branch_id:
            query = query.filter(StockAdjustment.branch_id == current_user.branch_id)
            branch_filter = str(current_user.branch_id)
    else:
        if branch_filter and branch_filter not in ['all', '', 'None']:
            try:
                b_id = int(branch_filter)
                query = query.filter(StockAdjustment.branch_id == b_id)
            except ValueError:
                pass

    # Filtro por tipo de movimiento
    if tipo_filtro:
        query = query.filter(StockAdjustment.tipo_movimiento.ilike(f'%{tipo_filtro}%'))

    # Buscador de Producto / SKU / IMEI
    if query_busqueda:
        from sqlalchemy import or_
        query = query.filter(
            or_(
                Product.sku.ilike(f'%{query_busqueda}%'),
                Product.nombre.ilike(f'%{query_busqueda}%'),
                Product.imei.ilike(f'%{query_busqueda}%')
            )
        )

    # Orden cronológico descendente
    query = query.order_by(StockAdjustment.fecha_ajuste.desc())

    # Paginación
    paginacion = query.paginate(page=page, per_page=per_page, error_out=False)

    # Catálogo de sucursales para el filtro
    sucursales = Branch.query.filter_by(activa=True).order_by(Branch.tipo.desc(), Branch.nombre.asc()).all()

    # Tipos predefinidos de movimiento
    tipos_movimiento = [
        ('TRASLADO', 'Traslados (Salidas/Entradas)'),
        ('VENTA', 'Ventas POS'),
        ('RETOMA', 'Retomas de Clientes'),
        ('COMPRA', 'Ingresos de Proveedor / Compras'),
        ('GARANTIA', 'Garantías y Soporte'),
        ('AJUSTE', 'Ajustes Manuales de Inventario'),
        ('MANEO', 'Maneos / Préstamos')
    ]

    return render_template(
        'transfers/trazabilidad.html',
        movimientos=paginacion.items,
        paginacion=paginacion,
        rango=rango,
        label_rango=label_rango,
        fecha_inicio=fecha_inicio_str or dt_inicio.strftime('%Y-%m-%d'),
        fecha_fin=fecha_fin_str or (dt_fin - timedelta(days=1)).strftime('%Y-%m-%d'),
        sucursales=sucursales,
        branch_filter=branch_filter,
        tipo_filtro=tipo_filtro,
        tipos_movimiento=tipos_movimiento,
        query_busqueda=query_busqueda,
        per_page=per_page
    )

@transfers_bp.route('/historial')
@login_required
def historial_alias():
    """Redirección amigable a la bitácora de trazabilidad."""
    return redirect(url_for('transfers_bp.trazabilidad', **request.args))
