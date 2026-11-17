from flask import Blueprint, render_template, request, redirect, url_for, flash, session
from flask_login import login_required, current_user
from models import db, Product, ProductVariant, Maneo, StockAdjustment, Sale, SaleDetail, SalePayment, SaleClient, Branch, obtener_hora_bogota
from services.stock_service import get_or_create_branch_stock, sync_global_product_stock

maneos_bp = Blueprint('maneos_bp', __name__)

@maneos_bp.route('/')
@login_required
def index():
    if current_user.rol not in ['admin', 'vendedor', 'bodega']:
        flash('Acceso denegado.', 'danger')
        return redirect(url_for('index'))

    query_activos = Maneo.query.filter_by(estado='PENDIENTE')
    query_historial = Maneo.query.filter(Maneo.estado != 'PENDIENTE')

    # Filtrado por sucursal
    if current_user.rol == 'vendedor':
        if current_user.branch_id:
            query_activos = query_activos.filter(Maneo.branch_id == current_user.branch_id)
            query_historial = query_historial.filter(Maneo.branch_id == current_user.branch_id)
    else:
        active_b_id = session.get('active_branch_id')
        if active_b_id:
            query_activos = query_activos.filter(Maneo.branch_id == int(active_b_id))
            query_historial = query_historial.filter(Maneo.branch_id == int(active_b_id))

    activos = query_activos.order_by(Maneo.fecha_prestamo.desc()).all()
    historial = query_historial.order_by(Maneo.fecha_resolucion.desc()).limit(50).all()
    return render_template('maneos/index.html', activos=activos, historial=historial)

@maneos_bp.route('/prestar', methods=['POST'])
@login_required
def prestar():
    if current_user.rol not in ['admin', 'vendedor', 'bodega']:
        flash('Acceso denegado.', 'danger')
        return redirect(url_for('maneos_bp.index'))

    sku_busqueda = request.form.get('sku_busqueda', '').strip()
    local_vecino = request.form.get('local_vecino', '').strip()
    cantidad = int(request.form.get('cantidad', 1))

    if not sku_busqueda or not local_vecino or cantidad < 1:
        flash("Todos los campos son obligatorios y la cantidad debe ser mayor a 0.", "danger")
        return redirect(url_for('maneos_bp.index'))

    # Determinar la sucursal de donde sale el maneo
    if current_user.rol in ['vendedor', 'bodega']:
        maneo_branch_id = current_user.branch_id
        if not maneo_branch_id:
            b_def = Branch.query.filter_by(activa=True).order_by(Branch.id.asc()).first()
            maneo_branch_id = b_def.id if b_def else 1
    else:
        active_b = session.get('active_branch_id')
        if active_b:
            maneo_branch_id = int(active_b)
        else:
            b_def = Branch.query.filter_by(activa=True).order_by(Branch.id.asc()).first()
            maneo_branch_id = b_def.id if b_def else 1

    branch_obj = Branch.query.get(maneo_branch_id)
    branch_nom = branch_obj.nombre if branch_obj else 'Principal'

    # Buscar el producto o variante por SKU
    producto = Product.query.filter_by(sku=sku_busqueda).first()
    variant_id = request.form.get('variant_id')
    variante = None

    if not producto:
        flash(f"No se encontró ningún producto con el SKU: {sku_busqueda}", "warning")
        return redirect(url_for('maneos_bp.index'))

    if producto.variantes:
        if not variant_id:
            flash(f"El producto '{producto.nombre}' tiene subcategorías. Debes especificar cuál vas a prestar.", "warning")
            return redirect(url_for('maneos_bp.index'))
            
        variante = ProductVariant.query.get(variant_id)
        if not variante or variante.product_id != producto.id:
            flash("Variante inválida.", "danger")
            return redirect(url_for('maneos_bp.index'))

        b_stock = get_or_create_branch_stock(maneo_branch_id, producto.id, variante.id, for_update=True)
        if b_stock.cantidad < cantidad:
            flash(f"Stock insuficiente en '{branch_nom}'. Solo hay {b_stock.cantidad} unidades disponibles de esta subcategoría.", "danger")
            return redirect(url_for('maneos_bp.index'))
            
        # Descontar Inventario Local y sincronizar
        stock_anterior = b_stock.cantidad
        b_stock.cantidad -= cantidad
        sync_global_product_stock(producto.id, variante.id)
        
        ajuste = StockAdjustment(
            product_id=producto.id,
            admin_id=current_user.id,
            branch_id=maneo_branch_id,
            tipo_movimiento=f"Préstamo (Maneo) a {local_vecino} (Subcat: {variante.nombre_variante}) en {branch_nom}",
            stock_anterior=stock_anterior,
            stock_nuevo=b_stock.cantidad
        )
        db.session.add(ajuste)
    else:
        b_stock = get_or_create_branch_stock(maneo_branch_id, producto.id, None, for_update=True)
        if b_stock.cantidad < cantidad:
            flash(f"Stock insuficiente en '{branch_nom}'. Solo hay {b_stock.cantidad} unidades disponibles.", "danger")
            return redirect(url_for('maneos_bp.index'))
            
        # Descontar Inventario Base Local y sincronizar
        stock_anterior = b_stock.cantidad
        b_stock.cantidad -= cantidad
        sync_global_product_stock(producto.id, None)
        
        ajuste = StockAdjustment(
            product_id=producto.id,
            admin_id=current_user.id,
            branch_id=maneo_branch_id,
            tipo_movimiento=f"Préstamo (Maneo) a {local_vecino} en {branch_nom}",
            stock_anterior=stock_anterior,
            stock_nuevo=b_stock.cantidad
        )
        db.session.add(ajuste)

    # 1. Crear el Maneo
    nuevo_maneo = Maneo(
        product_id=producto.id,
        variant_id=variante.id if variante else None,
        branch_id=maneo_branch_id,
        local_vecino=local_vecino,
        cantidad=cantidad,
        estado='PENDIENTE'
    )
    db.session.add(nuevo_maneo)

    try:
        db.session.commit()
        flash(f"Préstamo registrado exitosamente para {local_vecino} desde {branch_nom}.", "success")
    except Exception as e:
        db.session.rollback()
        flash(f"Error al registrar el préstamo: {e}", "danger")

    return redirect(url_for('maneos_bp.index'))

@maneos_bp.route('/facturar/<int:id>', methods=['POST'])
@login_required
def facturar(id):
    if current_user.rol not in ['admin', 'vendedor', 'bodega']:
        flash('Acceso denegado.', 'danger')
        return redirect(url_for('maneos_bp.index'))

    maneo = Maneo.query.get_or_404(id)
    if maneo.estado != 'PENDIENTE':
        flash("Este maneo ya fue resuelto.", "warning")
        return redirect(url_for('maneos_bp.index'))

    # Opciones de facturación (puede venir del form)
    sugerido = maneo.variante.precio_sugerido if maneo.variant_id and maneo.variante else maneo.producto.precio_sugerido
    precio_unidad = float(request.form.get('precio_unidad', sugerido))
    metodo_pago = request.form.get('metodo_pago', 'efectivo')
    
    # Datos del cliente
    cliente_nombre = request.form.get('cliente_nombre', '').strip()
    cliente_documento = request.form.get('cliente_documento', '').strip()
    cliente_telefono = request.form.get('cliente_telefono', '').strip()

    es_celular = (maneo.producto.tipo_inventario == 'celulares' or bool(maneo.producto.imei))
    if es_celular and (not cliente_nombre or not cliente_documento):
        flash("Para facturar un celular prestado en maneo, es obligatorio indicar el nombre y documento del cliente.", "warning")
        return redirect(url_for('maneos_bp.index'))

    total_venta = precio_unidad * maneo.cantidad
    maneo_branch = maneo.branch_id or (current_user.branch_id or 1)
    b_obj = Branch.query.get(maneo_branch)
    branch_nom = b_obj.nombre if b_obj else 'Principal'

    # Crear la Venta
    nueva_venta = Sale(
        vendedor_id=current_user.id,
        branch_id=maneo_branch,
        sucursal=branch_nom,
        monto_total=total_venta,
        metodo_pago=metodo_pago,
        tipo_venta='celulares' if es_celular else 'general'
    )
    db.session.add(nueva_venta)
    db.session.flush()

    # Añadir detalle
    detalle = SaleDetail(
        sale_id=nueva_venta.id,
        product_id=maneo.product_id,
        variant_id=maneo.variant_id,
        cantidad_vendida=maneo.cantidad,
        precio_venta_final=precio_unidad
    )
    db.session.add(detalle)

    # Añadir pago (SalePayment)
    pago = SalePayment(
        sale_id=nueva_venta.id,
        metodo_pago=metodo_pago,
        monto=total_venta
    )
    db.session.add(pago)

    # Añadir cliente si fue proporcionado
    if cliente_nombre:
        cliente = SaleClient(
            sale_id=nueva_venta.id,
            nombre=cliente_nombre,
            documento=cliente_documento or '0',
            telefono=cliente_telefono or ''
        )
        db.session.add(cliente)

    # Actualizar estado del Maneo
    maneo.estado = 'FACTURADO'
    maneo.fecha_resolucion = obtener_hora_bogota()

    try:
        db.session.commit()
        flash(f"Maneo facturado correctamente en {branch_nom}. Venta #{nueva_venta.id} registrada por ${total_venta:,.0f}.", "success")
    except Exception as e:
        db.session.rollback()
        flash(f"Error al facturar el maneo: {e}", "danger")

    return redirect(url_for('maneos_bp.index'))

@maneos_bp.route('/devolver/<int:id>', methods=['POST'])
@login_required
def devolver(id):
    if current_user.rol not in ['admin', 'vendedor', 'bodega']:
        flash('Acceso denegado.', 'danger')
        return redirect(url_for('maneos_bp.index'))

    maneo = Maneo.query.get_or_404(id)
    if maneo.estado != 'PENDIENTE':
        flash("Este maneo ya fue resuelto.", "warning")
        return redirect(url_for('maneos_bp.index'))

    # 1. Actualizar estado
    maneo.estado = 'DEVUELTO'
    maneo.fecha_resolucion = obtener_hora_bogota()

    # 2. Devolver stock a la sucursal de origen
    maneo_branch = maneo.branch_id or (current_user.branch_id or 1)
    b_obj = Branch.query.get(maneo_branch)
    branch_nom = b_obj.nombre if b_obj else 'Principal'
    producto = maneo.producto
    
    if maneo.variant_id:
        b_stock = get_or_create_branch_stock(maneo_branch, producto.id, maneo.variant_id, for_update=True)
        stock_anterior = b_stock.cantidad
        b_stock.cantidad += maneo.cantidad
        sync_global_product_stock(producto.id, maneo.variant_id)

        var_nom = maneo.variante.nombre_variante if maneo.variante else ''
        ajuste = StockAdjustment(
            product_id=producto.id,
            admin_id=current_user.id,
            branch_id=maneo_branch,
            tipo_movimiento=f"Devolución de Maneo de {maneo.local_vecino} (Subcat: {var_nom}) en {branch_nom}",
            stock_anterior=stock_anterior,
            stock_nuevo=b_stock.cantidad
        )
        db.session.add(ajuste)
    else:
        b_stock = get_or_create_branch_stock(maneo_branch, producto.id, None, for_update=True)
        stock_anterior = b_stock.cantidad
        b_stock.cantidad += maneo.cantidad
        sync_global_product_stock(producto.id, None)

        ajuste = StockAdjustment(
            product_id=producto.id,
            admin_id=current_user.id,
            branch_id=maneo_branch,
            tipo_movimiento=f"Devolución de Maneo de {maneo.local_vecino} en {branch_nom}",
            stock_anterior=stock_anterior,
            stock_nuevo=b_stock.cantidad
        )
        db.session.add(ajuste)

    try:
        db.session.commit()
        flash(f"Maneo devuelto. {maneo.cantidad} unidades regresaron al stock de {branch_nom}.", "success")
    except Exception as e:
        db.session.rollback()
        flash(f"Error al devolver el maneo: {e}", "danger")

    return redirect(url_for('maneos_bp.index'))
