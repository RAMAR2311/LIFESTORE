from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify, session
from flask_login import login_required, current_user
from models import db, ExchangePartner, DeviceExchange, Product, Branch, StockAdjustment, AuditLog
from services.stock_service import get_or_create_branch_stock, sync_global_product_stock
from datetime import datetime
from decimal import Decimal
import pytz

exchanges_bp = Blueprint('exchanges_bp', __name__)

def obtener_hora_bogota():
    tz = pytz.timezone('America/Bogota')
    return datetime.now(tz).replace(tzinfo=None)

@exchanges_bp.route('/')
@login_required
def index():
    """Listado principal de cambios de celulares e historial."""
    filtro_estado = request.args.get('estado', '').strip() # 'PENDIENTE', 'COMPLETADO', 'DEVUELTO'
    filtro_partner = request.args.get('partner_id', type=int)
    q = request.args.get('q', '').strip()

    query = DeviceExchange.query

    # Restricción por sede si es vendedor
    if current_user.rol == 'vendedor':
        if current_user.branch_id:
            query = query.filter(DeviceExchange.branch_id == current_user.branch_id)
    else:
        active_b_id = session.get('active_branch_id')
        if active_b_id:
            query = query.filter(DeviceExchange.branch_id == int(active_b_id))

    if filtro_estado:
        query = query.filter(DeviceExchange.estado == filtro_estado)
    if filtro_partner:
        query = query.filter(DeviceExchange.partner_id == filtro_partner)
    if q:
        query = query.filter(
            db.or_(
                DeviceExchange.imei_salida.ilike(f'%{q}%'),
                DeviceExchange.modelo_salida.ilike(f'%{q}%'),
                DeviceExchange.imei1_entrada.ilike(f'%{q}%'),
                DeviceExchange.modelo_entrada.ilike(f'%{q}%'),
                DeviceExchange.motivo_salida.ilike(f'%{q}%')
            )
        )

    cambios = query.order_by(DeviceExchange.fecha_salida.desc()).all()
    partners = ExchangePartner.query.filter_by(activo=True).order_by(ExchangePartner.nombre.asc()).all()
    sucursales = Branch.query.order_by(Branch.tipo.desc(), Branch.nombre.asc()).all()
    from models import Asesor
    asesores = Asesor.query.filter_by(activo=True).order_by(Asesor.nombre.asc()).all()

    # Conteos para métricas
    base_counts = DeviceExchange.query
    if current_user.rol == 'vendedor' and current_user.branch_id:
        base_counts = base_counts.filter(DeviceExchange.branch_id == current_user.branch_id)
    elif session.get('active_branch_id'):
        base_counts = base_counts.filter(DeviceExchange.branch_id == int(session.get('active_branch_id')))

    pendientes_count = base_counts.filter_by(estado='PENDIENTE').count()
    completados_count = base_counts.filter_by(estado='COMPLETADO').count()
    devueltos_count = base_counts.filter_by(estado='DEVUELTO').count()

    # Celulares disponibles en inventario para entregar al saldar cambios ENTRADA_PRIMERO
    celulares_disp_q = Product.query.filter(
        Product.tipo_inventario == 'celulares',
        Product.cantidad_stock > 0
    )
    if current_user.rol == 'vendedor' and current_user.branch_id:
        celulares_disp_q = celulares_disp_q.join(
            BranchStock,
            (BranchStock.product_id == Product.id) & (BranchStock.branch_id == current_user.branch_id)
        ).filter(BranchStock.cantidad > 0)
    celulares_disponibles = celulares_disp_q.order_by(Product.nombre.asc()).all()

    return render_template(
        'exchanges/index.html',
        cambios=cambios,
        partners=partners,
        sucursales=sucursales,
        asesores=asesores,
        celulares_disponibles=celulares_disponibles,
        filtro_estado=filtro_estado,
        filtro_partner=filtro_partner,
        q=q,
        pendientes_count=pendientes_count,
        completados_count=completados_count,
        devueltos_count=devueltos_count
    )

@exchanges_bp.route('/aliados/crear', methods=['POST'])
@login_required
def crear_aliado():
    """Registrar un nuevo aliado o empresa externa para canjes."""
    nombre = request.form.get('nombre', '').strip()
    contacto = request.form.get('contacto', '').strip()
    documento_o_nit = request.form.get('documento_o_nit', '').strip()
    direccion = request.form.get('direccion', '').strip()

    if not nombre:
        flash('El nombre de la empresa o persona es obligatorio.', 'warning')
        return redirect(request.referrer or url_for('exchanges_bp.index'))

    partner = ExchangePartner(
        nombre=nombre,
        contacto=contacto or None,
        documento_o_nit=documento_o_nit or None,
        direccion=direccion or None,
        activo=True
    )
    db.session.add(partner)
    db.session.commit()

    AuditLog.registrar(
        action='CREAR_ALIADO_CAMBIO',
        user_id=current_user.id,
        motivo=f'Registro de nuevo aliado comercial para canjes: {nombre}',
        target_id=partner.id,
        target_type='EXCHANGE_PARTNER'
    )

    flash(f'Aliado comercial "{nombre}" registrado correctamente.', 'success')
    return redirect(request.referrer or url_for('exchanges_bp.index'))

@exchanges_bp.route('/salida/<int:product_id>', methods=['POST'])
@login_required
def registrar_salida_cambio(product_id):
    """Envía un celular del inventario hacia el módulo de cambio con un tercero."""
    celular = Product.query.get_or_404(product_id)

    if celular.tipo_inventario != 'celulares' and not celular.imei:
        flash('Solo se pueden enviar celulares al módulo de cambio.', 'danger')
        return redirect(url_for('celulares_bp.inventario'))

    if celular.cantidad_stock <= 0:
        flash(f'El equipo "{celular.nombre}" no tiene unidades en stock para entregar.', 'warning')
        return redirect(url_for('celulares_bp.inventario'))

    partner_id = request.form.get('partner_id', type=int)
    asesor_id = request.form.get('asesor_id', type=int)
    nuevo_partner_nombre = request.form.get('nuevo_partner_nombre', '').strip()
    motivo_salida = request.form.get('motivo_salida', '').strip()

    # Si escribió un nuevo aliado directo en el modal
    if not partner_id and nuevo_partner_nombre:
        partner = ExchangePartner(nombre=nuevo_partner_nombre, contacto=request.form.get('nuevo_partner_contacto', '').strip() or None, activo=True)
        db.session.add(partner)
        db.session.flush()
        partner_id = partner.id

    if not partner_id:
        flash('Debes seleccionar o ingresar la persona/empresa a la que entregas el celular.', 'warning')
        return redirect(url_for('celulares_bp.inventario'))

    # Determinar sede actual del equipo
    branch_id = current_user.branch_id or (session.get('active_branch_id') or 1)
    for bs in celular.branch_stocks:
        if bs.cantidad > 0:
            branch_id = bs.branch_id
            break

    try:
        # Descontar stock de la sede y sincronizar global
        b_stock = get_or_create_branch_stock(branch_id, celular.id, None, for_update=True)
        stock_anterior = b_stock.cantidad
        b_stock.cantidad = max(0, b_stock.cantidad - 1)
        sync_global_product_stock(celular.id, None)

        partner_obj = ExchangePartner.query.get(partner_id)
        partner_nombre = partner_obj.nombre if partner_obj else 'Aliado Externo'

        # Registrar el canje
        cambio = DeviceExchange(
            partner_id=partner_id,
            user_id=current_user.id,
            asesor_id=asesor_id,
            branch_id=branch_id,
            product_salida_id=celular.id,
            imei_salida=celular.imei,
            modelo_salida=celular.modelo_celular or celular.nombre,
            costo_salida=celular.precio_costo,
            estado='PENDIENTE',
            motivo_salida=motivo_salida or f"Entregado a {partner_nombre} a cambio de otro equipo",
            fecha_salida=obtener_hora_bogota()
        )
        db.session.add(cambio)

        # Kardex / Ajuste de auditoría
        ajuste = StockAdjustment(
            product_id=celular.id,
            admin_id=current_user.id,
            branch_id=branch_id,
            tipo_movimiento=f'Salida por Cambio a {partner_nombre} [IMEI: {celular.imei or celular.sku}]',
            stock_anterior=stock_anterior,
            stock_nuevo=b_stock.cantidad
        )
        db.session.add(ajuste)

        AuditLog.registrar(
            action='SALIDA_CAMBIO_CELULAR',
            user_id=current_user.id,
            motivo=f'Salida de celular {celular.modelo_celular or celular.nombre} (IMEI {celular.imei}) entregado a {partner_nombre}',
            target_id=cambio.id,
            target_type='DEVICE_EXCHANGE'
        )

        db.session.commit()
        flash(f'Celular entregado a "{partner_nombre}". Ha quedado registrado en el módulo de Cambios de Celulares.', 'success')
        return redirect(url_for('exchanges_bp.index'))

    except Exception as e:
        db.session.rollback()
        flash(f'Error al procesar la salida a cambio: {str(e)}', 'danger')
        return redirect(url_for('celulares_bp.inventario'))

@exchanges_bp.route('/recibir/<int:exchange_id>', methods=['POST'])
@login_required
def recibir_celular_cambio(exchange_id):
    """Recibe el nuevo celular que entregan a cambio, registrándolo en el inventario."""
    cambio = DeviceExchange.query.get_or_404(exchange_id)

    if cambio.estado != 'PENDIENTE':
        flash('Este canje ya fue cerrado previamente.', 'warning')
        return redirect(url_for('exchanges_bp.index'))

    # Datos del nuevo equipo
    marca = request.form.get('marca_entrada', '').strip()
    modelo = request.form.get('modelo_entrada', '').strip()
    if modelo == '__OTRO__':
        modelo = request.form.get('modelo_entrada_custom', '').strip()
    color = request.form.get('color_entrada', '').strip()
    if color == '__OTRO__':
        color = request.form.get('color_entrada_custom', '').strip()
    memoria = request.form.get('memoria_entrada', '').strip()
    if memoria == '__OTRO__':
        memoria = request.form.get('memoria_entrada_custom', '').strip()
    bateria = request.form.get('bateria_entrada', '').strip()
    imei1 = request.form.get('imei1_entrada', '').strip()
    imei2 = request.form.get('imei2_entrada', '').strip() or None
    inventario = request.form.get('inventario_entrada', 'Usado').strip()

    costo_str = request.form.get('costo_entrada', '0').replace('$', '').replace('.', '').replace(',', '').strip()
    minimo_str = request.form.get('precio_minimo_entrada', '0').replace('$', '').replace('.', '').replace(',', '').strip()
    sugerido_str = request.form.get('precio_sugerido_entrada', '0').replace('$', '').replace('.', '').replace(',', '').strip()
    asesor_id = request.form.get('asesor_id', type=int)
    dest_branch_id = request.form.get('branch_id', type=int) or cambio.branch_id
    obs_resolucion = request.form.get('observacion_resolucion', '').strip()

    if not modelo or not imei1:
        flash('El modelo y el IMEI 1 del nuevo celular son obligatorios.', 'warning')
        return redirect(url_for('exchanges_bp.index'))

    # Validar que el nuevo IMEI no exista ya activo
    existente = Product.query.filter_by(imei=imei1).first()
    if existente:
        flash(f'El IMEI "{imei1}" ya está registrado en el sistema con el producto "{existente.nombre}". Verifica los datos.', 'danger')
        return redirect(url_for('exchanges_bp.index'))

    try:
        costo_val = Decimal(costo_str or '0')
        minimo_val = Decimal(minimo_str or '0')
        sugerido_val = Decimal(sugerido_str or '0')

        # Si no colocaron costo, por defecto toma el costo del equipo que salió
        if costo_val == 0 and cambio.costo_salida:
            costo_val = Decimal(str(cambio.costo_salida))

        sku_nuevo = f"CEL-{datetime.now().strftime('%Y%m%d%H%M%S')}"
        nombre_nuevo = f"Celular {marca} {modelo} {color} {memoria}".strip()

        # Crear el nuevo producto en el inventario
        nuevo_cel = Product(
            nombre=nombre_nuevo,
            sku=sku_nuevo,
            tipo_inventario='celulares',
            cantidad_stock=0,
            precio_costo=costo_val,
            precio_minimo=minimo_val,
            precio_sugerido=sugerido_val,
            imei=imei1,
            imei2=imei2,
            marca=marca,
            modelo_celular=modelo,
            estado_celular='Usado',
            color=color or None,
            bateria=bateria or None,
            memoria=memoria or None,
            proveedor=f"Cambio con {cambio.partner.nombre if cambio.partner else 'Tercero'}",
            inventario=inventario,
            observacion=f"Ingresado por cambio de mercancía #{cambio.id} (Salió: {cambio.modelo_salida} IMEI: {cambio.imei_salida})"
        )
        db.session.add(nuevo_cel)
        db.session.flush()

        # Asignar 1 unidad a la sede seleccionada
        b_stock = get_or_create_branch_stock(dest_branch_id, nuevo_cel.id, None)
        b_stock.cantidad = 1
        sync_global_product_stock(nuevo_cel.id, None)

        # Registrar ajuste de stock
        ajuste = StockAdjustment(
            product_id=nuevo_cel.id,
            admin_id=current_user.id,
            branch_id=dest_branch_id,
            tipo_movimiento=f'Ingreso por Cambio #{cambio.id} ({cambio.partner.nombre if cambio.partner else ""})',
            stock_anterior=0,
            stock_nuevo=1
        )
        db.session.add(ajuste)

        # Actualizar datos del cambio
        cambio.estado = 'COMPLETADO'
        if asesor_id:
            cambio.asesor_id = asesor_id
        cambio.product_entrada_id = nuevo_cel.id
        cambio.marca_entrada = marca
        cambio.modelo_entrada = modelo
        cambio.color_entrada = color
        cambio.memoria_entrada = memoria
        cambio.imei1_entrada = imei1
        cambio.imei2_entrada = imei2
        cambio.costo_entrada = costo_val
        cambio.precio_minimo_entrada = minimo_val
        cambio.precio_sugerido_entrada = sugerido_val
        cambio.resolved_by_id = current_user.id
        cambio.fecha_resolucion = obtener_hora_bogota()
        cambio.observacion_resolucion = obs_resolucion or f"Recibido {modelo} ({color}) IMEI: {imei1}"

        AuditLog.registrar(
            action='RECIBIR_CAMBIO_CELULAR',
            user_id=current_user.id,
            motivo=f'Completado cambio #{cambio.id}. Ingresó {nombre_nuevo} (IMEI {imei1})',
            target_id=cambio.id,
            target_type='DEVICE_EXCHANGE'
        )

        db.session.commit()
        flash(f'¡Cambio completado con éxito! Se ingresó el nuevo celular "{nombre_nuevo}" al inventario.', 'success')
        return redirect(url_for('exchanges_bp.index'))

    except Exception as e:
        db.session.rollback()
        flash(f'Error al registrar el equipo recibido: {str(e)}', 'danger')
        return redirect(url_for('exchanges_bp.index'))

@exchanges_bp.route('/devolver/<int:exchange_id>', methods=['POST'])
@login_required
def devolver_al_inventario(exchange_id):
    """Cancela el cambio y reintegra el celular original al inventario activo."""
    cambio = DeviceExchange.query.get_or_404(exchange_id)

    if cambio.estado != 'PENDIENTE':
        flash('Este canje ya fue resuelto previamente.', 'warning')
        return redirect(url_for('exchanges_bp.index'))

    celular = cambio.producto_salida
    branch_id = cambio.branch_id or (current_user.branch_id or 1)

    try:
        # Reingresar 1 unidad a la sucursal de origen
        b_stock = get_or_create_branch_stock(branch_id, celular.id, None, for_update=True)
        stock_anterior = b_stock.cantidad
        b_stock.cantidad += 1
        sync_global_product_stock(celular.id, None)

        cambio.estado = 'DEVUELTO'
        cambio.resolved_by_id = current_user.id
        cambio.fecha_resolucion = obtener_hora_bogota()
        cambio.observacion_resolucion = request.form.get('observacion_devolucion', '').strip() or 'Cambio cancelado. Equipo devuelto al inventario.'

        ajuste = StockAdjustment(
            product_id=celular.id,
            admin_id=current_user.id,
            branch_id=branch_id,
            tipo_movimiento=f'Devolución de Cambio #{cambio.id} de {cambio.partner.nombre if cambio.partner else "Tercero"}',
            stock_anterior=stock_anterior,
            stock_nuevo=b_stock.cantidad
        )
        db.session.add(ajuste)

        AuditLog.registrar(
            action='DEVOLVER_CAMBIO_CELULAR',
            user_id=current_user.id,
            motivo=f'Devolución de cambio #{cambio.id}. Reingresó {celular.nombre} al stock activo',
            target_id=cambio.id,
            target_type='DEVICE_EXCHANGE'
        )

        db.session.commit()
        flash(f'El celular "{celular.nombre}" ha sido devuelto al inventario activo exitosamente.', 'success')
        return redirect(url_for('exchanges_bp.index'))

    except Exception as e:
        db.session.rollback()
        flash(f'Error al devolver el equipo al inventario: {str(e)}', 'danger')
        return redirect(url_for('exchanges_bp.index'))


# ==========================================================
# FLUJO INVERSO: ME ENTREGAN EL CELULAR PRIMERO (QUEDO PENDIENTE DE ENTREGAR)
# ==========================================================

@exchanges_bp.route('/entrada', methods=['POST'])
@login_required
def registrar_entrada_cambio():
    """Registra un celular que me entregan primero a cambio; entra al stock y deja pendiente mi entrega."""
    partner_id = request.form.get('partner_id', type=int)
    nuevo_partner_nombre = request.form.get('nuevo_partner_nombre', '').strip()
    asesor_id = request.form.get('asesor_id', type=int)
    dest_branch_id = request.form.get('branch_id', type=int) or current_user.branch_id or (session.get('active_branch_id') or 1)
    motivo_salida = request.form.get('motivo_salida', '').strip()

    if not partner_id and nuevo_partner_nombre:
        partner = ExchangePartner(
            nombre=nuevo_partner_nombre,
            contacto=request.form.get('nuevo_partner_contacto', '').strip() or None,
            activo=True
        )
        db.session.add(partner)
        db.session.flush()
        partner_id = partner.id

    if not partner_id:
        flash('Debes seleccionar o registrar el aliado/persona que entrega el celular.', 'warning')
        return redirect(url_for('exchanges_bp.index'))

    marca = request.form.get('marca_entrada', '').strip()
    modelo = request.form.get('modelo_entrada', '').strip()
    color = request.form.get('color_entrada', '').strip()
    memoria = request.form.get('memoria_entrada', '').strip()
    bateria = request.form.get('bateria_entrada', '').strip()
    imei1 = request.form.get('imei1_entrada', '').strip()
    imei2 = request.form.get('imei2_entrada', '').strip() or None
    inventario = request.form.get('inventario_entrada', 'Usado').strip()

    costo_str = request.form.get('costo_entrada', '0').replace('$', '').replace('.', '').replace(',', '').strip()
    minimo_str = request.form.get('precio_minimo_entrada', '0').replace('$', '').replace('.', '').replace(',', '').strip()
    sugerido_str = request.form.get('precio_sugerido_entrada', '0').replace('$', '').replace('.', '').replace(',', '').strip()

    if not modelo or not imei1:
        flash('El modelo y el IMEI 1 del celular recibido son obligatorios.', 'warning')
        return redirect(url_for('exchanges_bp.index'))

    existente = Product.query.filter_by(imei=imei1).first()
    if existente and existente.cantidad_stock > 0:
        flash(f'El IMEI "{imei1}" ya está activo en inventario ({existente.nombre}).', 'danger')
        return redirect(url_for('exchanges_bp.index'))

    try:
        costo_val = Decimal(costo_str or '0')
        minimo_val = Decimal(minimo_str or '0')
        sugerido_val = Decimal(sugerido_str or '0')

        partner_obj = ExchangePartner.query.get(partner_id)
        partner_nombre = partner_obj.nombre if partner_obj else 'Aliado Externo'

        sku_nuevo = f"CAM-{datetime.now().strftime('%Y%m%d%H%M%S')}"
        nombre_nuevo = f"Celular {marca} {modelo} {color} {memoria}".strip()

        nuevo_cel = Product(
            nombre=nombre_nuevo,
            sku=sku_nuevo,
            tipo_inventario='celulares',
            cantidad_stock=0,
            precio_costo=costo_val,
            precio_minimo=minimo_val,
            precio_sugerido=sugerido_val,
            imei=imei1,
            imei2=imei2,
            marca=marca,
            modelo_celular=modelo,
            estado_celular='Usado',
            color=color or None,
            bateria=bateria or None,
            memoria=memoria or None,
            proveedor=f"Cambio con {partner_nombre}",
            inventario=inventario,
            observacion=f"Ingresado por cambio (Pendiente por entregar equipo nuestro a {partner_nombre})."
        )
        db.session.add(nuevo_cel)
        db.session.flush()

        b_stock = get_or_create_branch_stock(dest_branch_id, nuevo_cel.id, None)
        b_stock.cantidad = 1
        sync_global_product_stock(nuevo_cel.id, None)

        cambio = DeviceExchange(
            partner_id=partner_id,
            user_id=current_user.id,
            asesor_id=asesor_id,
            branch_id=dest_branch_id,
            product_salida_id=None,
            imei_salida=None,
            modelo_salida=None,
            costo_salida=Decimal('0.00'),
            product_entrada_id=nuevo_cel.id,
            marca_entrada=marca,
            modelo_entrada=modelo,
            color_entrada=color,
            memoria_entrada=memoria,
            imei1_entrada=imei1,
            imei2_entrada=imei2,
            costo_entrada=costo_val,
            precio_minimo_entrada=minimo_val,
            precio_sugerido_entrada=sugerido_val,
            tipo_flujo='ENTRADA_PRIMERO',
            estado='PENDIENTE',
            motivo_salida=motivo_salida or f"Recibido de {partner_nombre}; pendiente entregar equipo nuestro a cambio",
            fecha_salida=obtener_hora_bogota()
        )
        db.session.add(cambio)
        db.session.flush()

        ajuste = StockAdjustment(
            product_id=nuevo_cel.id,
            admin_id=current_user.id,
            branch_id=dest_branch_id,
            tipo_movimiento=f'Entrada por Cambio #{cambio.id} (Pendiente entrega a {partner_nombre})',
            stock_anterior=0,
            stock_nuevo=1
        )
        db.session.add(ajuste)

        AuditLog.registrar(
            action='ENTRADA_CAMBIO_CELULAR',
            user_id=current_user.id,
            motivo=f'Recibido celular {nombre_nuevo} (IMEI {imei1}) de {partner_nombre}, quedando pendiente entregar equipo nuestro.',
            target_id=cambio.id,
            target_type='DEVICE_EXCHANGE'
        )

        db.session.commit()
        flash(f'Celular "{nombre_nuevo}" ingresado al inventario. El cambio #{cambio.id} quedó PENDIENTE por entregar tu equipo a "{partner_nombre}".', 'success')
        return redirect(url_for('exchanges_bp.index'))

    except Exception as e:
        db.session.rollback()
        flash(f'Error al registrar entrada de cambio: {str(e)}', 'danger')
        return redirect(url_for('exchanges_bp.index'))


@exchanges_bp.route('/entregar/<int:exchange_id>', methods=['POST'])
@login_required
def entregar_celular_cambio(exchange_id):
    """Entrega un celular de nuestro inventario para saldar y completar un cambio ENTRADA_PRIMERO."""
    cambio = DeviceExchange.query.get_or_404(exchange_id)
    if cambio.estado != 'PENDIENTE' or cambio.tipo_flujo != 'ENTRADA_PRIMERO':
        flash('Este cambio no está pendiente de entrega.', 'warning')
        return redirect(url_for('exchanges_bp.index'))

    product_salida_id = request.form.get('product_salida_id', type=int)
    asesor_id = request.form.get('asesor_id', type=int)
    obs_resolucion = request.form.get('observacion_resolucion', '').strip()

    if not product_salida_id:
        flash('Debes seleccionar el celular de tu inventario que estás entregando.', 'warning')
        return redirect(url_for('exchanges_bp.index'))

    celular = Product.query.get_or_404(product_salida_id)
    if celular.cantidad_stock <= 0:
        flash(f'El equipo "{celular.nombre}" no tiene stock disponible.', 'danger')
        return redirect(url_for('exchanges_bp.index'))

    # Determinar sede donde está el equipo a entregar
    branch_salida_id = cambio.branch_id or (current_user.branch_id or 1)
    for bs in celular.branch_stocks:
        if bs.cantidad > 0:
            branch_salida_id = bs.branch_id
            break

    try:
        b_stock = get_or_create_branch_stock(branch_salida_id, celular.id, None, for_update=True)
        if b_stock.cantidad <= 0:
            flash(f'No hay stock disponible de "{celular.nombre}" en la sede seleccionada.', 'danger')
            return redirect(url_for('exchanges_bp.index'))

        stock_ant = b_stock.cantidad
        b_stock.cantidad -= 1
        sync_global_product_stock(celular.id, None)

        cambio.product_salida_id = celular.id
        cambio.imei_salida = celular.imei
        cambio.modelo_salida = celular.modelo_celular or celular.nombre
        cambio.costo_salida = celular.precio_costo
        if asesor_id:
            cambio.asesor_id = asesor_id
        cambio.estado = 'COMPLETADO'
        cambio.resolved_by_id = current_user.id
        cambio.fecha_resolucion = obtener_hora_bogota()
        cambio.observacion_resolucion = obs_resolucion or f"Entregado {celular.modelo_celular or celular.nombre} (IMEI: {celular.imei}) para saldar cambio"

        partner_nom = cambio.partner.nombre if cambio.partner else 'Aliado'
        ajuste = StockAdjustment(
            product_id=celular.id,
            admin_id=current_user.id,
            branch_id=branch_salida_id,
            tipo_movimiento=f'Salida para saldar Cambio #{cambio.id} ({partner_nom})',
            stock_anterior=stock_ant,
            stock_nuevo=b_stock.cantidad
        )
        db.session.add(ajuste)

        AuditLog.registrar(
            action='ENTREGAR_CAMBIO_CELULAR',
            user_id=current_user.id,
            motivo=f'Saldado cambio #{cambio.id}. Se entregó {celular.nombre} (IMEI {celular.imei}) a {partner_nom}',
            target_id=cambio.id,
            target_type='DEVICE_EXCHANGE'
        )

        db.session.commit()
        flash(f'¡Cambio #{cambio.id} completado! Se descontó "{celular.nombre}" del inventario y quedó saldado.', 'success')
        return redirect(url_for('exchanges_bp.index'))

    except Exception as e:
        db.session.rollback()
        flash(f'Error al registrar entrega del cambio: {str(e)}', 'danger')
        return redirect(url_for('exchanges_bp.index'))


@exchanges_bp.route('/cancelar-entrada/<int:exchange_id>', methods=['POST'])
@login_required
def cancelar_entrada_cambio(exchange_id):
    """Cancela un cambio ENTRADA_PRIMERO devolviendo el equipo recibido al aliado (si no se ha vendido)."""
    cambio = DeviceExchange.query.get_or_404(exchange_id)
    if cambio.estado != 'PENDIENTE' or cambio.tipo_flujo != 'ENTRADA_PRIMERO':
        flash('Este cambio no se puede cancelar por esta vía.', 'warning')
        return redirect(url_for('exchanges_bp.index'))

    prod_entrada = cambio.producto_entrada
    if not prod_entrada or prod_entrada.cantidad_stock <= 0:
        flash('No se puede devolver el equipo recibido porque ya fue vendido o no tiene stock en inventario. Debes saldar el cambio entregando otro celular.', 'danger')
        return redirect(url_for('exchanges_bp.index'))

    branch_id = cambio.branch_id or (current_user.branch_id or 1)
    for bs in prod_entrada.branch_stocks:
        if bs.cantidad > 0:
            branch_id = bs.branch_id
            break

    try:
        b_stock = get_or_create_branch_stock(branch_id, prod_entrada.id, None, for_update=True)
        stock_ant = b_stock.cantidad
        b_stock.cantidad = max(0, b_stock.cantidad - 1)
        sync_global_product_stock(prod_entrada.id, None)

        cambio.estado = 'DEVUELTO'
        cambio.resolved_by_id = current_user.id
        cambio.fecha_resolucion = obtener_hora_bogota()
        cambio.observacion_resolucion = request.form.get('observacion_devolucion', '').strip() or 'Cambio cancelado. Se devolvió el celular recibido al aliado.'

        ajuste = StockAdjustment(
            product_id=prod_entrada.id,
            admin_id=current_user.id,
            branch_id=branch_id,
            tipo_movimiento=f'Cancelación de Cambio #{cambio.id} (Devolución a aliado)',
            stock_anterior=stock_ant,
            stock_nuevo=b_stock.cantidad
        )
        db.session.add(ajuste)

        AuditLog.registrar(
            action='CANCELAR_ENTRADA_CAMBIO_CELULAR',
            user_id=current_user.id,
            motivo=f'Cancelado cambio #{cambio.id}. Se retiró del stock {prod_entrada.nombre} por devolución al aliado.',
            target_id=cambio.id,
            target_type='DEVICE_EXCHANGE'
        )

        db.session.commit()
        flash(f'Cambio #{cambio.id} cancelado y "{prod_entrada.nombre}" retirado del inventario.', 'success')
        return redirect(url_for('exchanges_bp.index'))

    except Exception as e:
        db.session.rollback()
        flash(f'Error al cancelar el cambio: {str(e)}', 'danger')
        return redirect(url_for('exchanges_bp.index'))

