from flask import Blueprint, render_template, abort, request, redirect, url_for, flash
from flask_login import login_required, current_user
from models import db, Product, ProductVariant, Sale, User, Maneo, SaleDetail, SalePayment, StockAdjustment, Expense, obtener_hora_bogota
from sqlalchemy.sql import func
from werkzeug.security import generate_password_hash
from decorators import admin_required
from decimal import Decimal
from datetime import datetime

admin_bp = Blueprint('admin_bp', __name__)

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
        sucursal = 'PRINCIPAL'
        
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
                    sucursal=sucursal
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
    return render_template('admin/vendedores.html', vendedores=lista_vendedores)

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
        usuario.sucursal = 'PRINCIPAL'
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

    # 1. Definición del rango temporal según el filtro seleccionado
    if mes_filtro and periodo == 'mes':
        try:
            año, mes = map(int, mes_filtro.split('-'))
            inicio_periodo = datetime(año, mes, 1, 0, 0, 0)
            if mes == 12:
                fin_periodo = datetime(año + 1, 1, 1, 0, 0, 0)
            else:
                fin_periodo = datetime(año, mes + 1, 1, 0, 0, 0)
            texto_periodo = f"Mes {mes_filtro}"
        except Exception:
            inicio_periodo = hoy.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
            fin_periodo = hoy.replace(year=hoy.year + 1, month=1, day=1, hour=0, minute=0, second=0, microsecond=0) if hoy.month == 12 else hoy.replace(month=hoy.month + 1, day=1, hour=0, minute=0, second=0, microsecond=0)
            mes_filtro = hoy.strftime('%Y-%m')
            texto_periodo = "Mes Actual"
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
        texto_periodo = f"Semana ({inicio_periodo.strftime('%d %b')} - {domingo.strftime('%d %b')})"
        mes_filtro = hoy.strftime('%Y-%m')
    elif periodo == 'quincena':
        if hoy.day <= 15:
            inicio_periodo = hoy.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
            fin_periodo = hoy.replace(day=16, hour=0, minute=0, second=0, microsecond=0)
            texto_periodo = f"1ª Quincena (1-15 {hoy.strftime('%b')})"
        else:
            inicio_periodo = hoy.replace(day=16, hour=0, minute=0, second=0, microsecond=0)
            fin_periodo = hoy.replace(year=hoy.year + 1, month=1, day=1, hour=0, minute=0, second=0, microsecond=0) if hoy.month == 12 else hoy.replace(month=hoy.month + 1, day=1, hour=0, minute=0, second=0, microsecond=0)
            ultimo_dia = (fin_periodo - timedelta(days=1)).day
            texto_periodo = f"2ª Quincena (16-{ultimo_dia} {hoy.strftime('%b')})"
        mes_filtro = hoy.strftime('%Y-%m')
    else:
        periodo = 'mes'
        inicio_periodo = hoy.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        fin_periodo = hoy.replace(year=hoy.year + 1, month=1, day=1, hour=0, minute=0, second=0, microsecond=0) if hoy.month == 12 else hoy.replace(month=hoy.month + 1, day=1, hour=0, minute=0, second=0, microsecond=0)
        mes_filtro = hoy.strftime('%Y-%m')
        texto_periodo = hoy.strftime('%B %Y').capitalize()

    # 2. Métricas de Ventas en el período
    total_ventas = db.session.query(func.sum(Sale.monto_total)).filter(Sale.fecha_venta >= inicio_periodo, Sale.fecha_venta < fin_periodo).scalar() or 0.0
    conteo_ventas = Sale.query.filter(Sale.fecha_venta >= inicio_periodo, Sale.fecha_venta < fin_periodo).count()

    # 3. Métricas de Bancos y Medios Digitales
    # Saldo total actual acumulado en cuentas bancarias activas
    saldo_bancos_total = db.session.query(func.sum(BankAccount.saldo_actual)).filter(BankAccount.tipo != 'efectivo', BankAccount.activo == True).scalar() or 0.0
    
    # Recaudos recibidos por bancos en el período (Nequi, Bancolombia, Daviplata, etc.)
    recaudo_pagos = db.session.query(func.sum(SalePayment.monto))\
        .join(Sale, SalePayment.sale_id == Sale.id)\
        .filter(Sale.fecha_venta >= inicio_periodo, Sale.fecha_venta < fin_periodo)\
        .filter(SalePayment.metodo_pago.notin_(['efectivo', 'retoma']))\
        .scalar() or 0.0
        
    ventas_con_pagos = db.session.query(SalePayment.sale_id).distinct()
    recaudo_directo = db.session.query(func.sum(Sale.monto_total))\
        .filter(Sale.fecha_venta >= inicio_periodo, Sale.fecha_venta < fin_periodo)\
        .filter(~Sale.id.in_(ventas_con_pagos))\
        .filter(Sale.metodo_pago.notin_(['efectivo', 'retoma']))\
        .scalar() or 0.0
        
    recaudo_bancos_periodo = float(recaudo_pagos) + float(recaudo_directo)

    # 4. Métricas de Inventario y Operaciones
    total_productos = Product.query.count()
    productos_bajo_stock = Product.query.filter(Product.cantidad_stock <= 10).count()
    maneos_activos = Maneo.query.filter_by(estado='PENDIENTE').count()
    proveedores_activos = Provider.query.count()
    garantias_pendientes = Warranty.query.filter_by(resolution='Pendiente').count()
    aprobaciones_pendientes = PriceApproval.query.filter_by(estado='pendiente').count()

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
                           aprobaciones_pendientes=aprobaciones_pendientes)

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

    from models import Retoma, Cliente, Provider, Expense, Sale, SaleDetail, Product

    # ----------------------------------------------------
    # ÁMBITO UNIFICADO (Tienda Principal)
    # ----------------------------------------------------
    ambito = 'consolidado'

    # ----------------------------------------------------
    # 1. CARGA DE VENTAS SEGÚN PERÍODO (UNIFICADO)
    # ----------------------------------------------------
    ventas_query = Sale.query.filter(Sale.fecha_venta >= inicio_dt, Sale.fecha_venta < fin_dt_query).all()

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
    # 2. GASTOS Y COSTOS INDIRECTOS (UNIFICADO)
    # ----------------------------------------------------
    gastos_auditar = Expense.query.filter(Expense.fecha_gasto >= inicio_dt, Expense.fecha_gasto < fin_dt_query).all()

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

@admin_bp.route('/ventas-vendedores', methods=['GET'])
@login_required
@admin_required
def ventas_vendedores():
    from models import Asesor, Sale
    import calendar
    from datetime import datetime
    
    # Obtener todos los asesores (ordenados por nombre)
    asesores_lista = Asesor.query.order_by(Asesor.nombre).all()
    
    asesor_id = request.args.get('asesor_id', type=int)
    mes_seleccionado = request.args.get('mes', '').strip()
    valor_comision_str = request.args.get('valor_comision', '20000').strip()
    
    try:
        val_comision_num = Decimal(valor_comision_str.replace('.', '').replace(',', '').replace('$', ''))
    except:
        val_comision_num = Decimal('20000')

    # Si no hay mes seleccionado, por defecto usar el mes actual
    if not mes_seleccionado:
        mes_seleccionado = obtener_hora_bogota().strftime('%Y-%m')
        
    ventas = []
    ventas_procesadas = []
    asesor_filtro = None
    total_ventas_mes = Decimal('0.0')
    total_celulares_mes = 0
    total_monto_celulares = Decimal('0.0')
    total_comision_mes = Decimal('0.0')
    
    if asesor_id:
        asesor_filtro = Asesor.query.get(asesor_id)
        if asesor_filtro:
            try:
                year, month = map(int, mes_seleccionado.split('-'))
                last_day = calendar.monthrange(year, month)[1]
                start_date = datetime(year, month, 1, 0, 0, 0)
                end_date = datetime(year, month, last_day, 23, 59, 59)
                
                # Obtener todas las ventas asociadas al asesor en ese rango de fechas
                ventas = Sale.query.filter(
                    Sale.asesor_id == asesor_id,
                    Sale.fecha_venta >= start_date,
                    Sale.fecha_venta <= end_date
                ).order_by(Sale.fecha_venta.desc()).all()
                
                total_ventas_mes = sum(v.monto_total for v in ventas)

                for v in ventas:
                    cant_celulares_venta = 0
                    monto_celulares_venta = Decimal('0.0')
                    celulares_list = []

                    for d in v.detalles:
                        if d.producto and d.producto.tipo_inventario in ['celulares', 'externos']:
                            cant = d.cantidad_vendida or 1
                            cant_celulares_venta += cant
                            monto_celulares_venta += Decimal(str(d.precio_venta_final)) * Decimal(str(cant))
                            celulares_list.append({
                                'nombre': d.producto.nombre,
                                'imei': d.producto.imei or 'N/A',
                                'cantidad': cant,
                                'precio': d.precio_venta_final
                            })

                    total_celulares_mes += cant_celulares_venta
                    total_monto_celulares += monto_celulares_venta

                    ventas_procesadas.append({
                        'sale': v,
                        'cant_celulares': cant_celulares_venta,
                        'monto_celulares': monto_celulares_venta,
                        'celulares_list': celulares_list,
                        'comision_venta': Decimal(str(cant_celulares_venta)) * val_comision_num
                    })

                total_comision_mes = Decimal(str(total_celulares_mes)) * val_comision_num
            except Exception as e:
                flash(f"Error al procesar las fechas del mes seleccionado: {str(e)}", 'danger')
                
    return render_template(
        'admin/ventas_vendedores.html',
        asesores=asesores_lista,
        asesor_id=asesor_id,
        asesor_filtro=asesor_filtro,
        mes_seleccionado=mes_seleccionado,
        valor_comision=int(val_comision_num),
        ventas=ventas,
        ventas_procesadas=ventas_procesadas,
        total_ventas_mes=total_ventas_mes,
        total_celulares_mes=total_celulares_mes,
        total_monto_celulares=total_monto_celulares,
        total_comision_mes=total_comision_mes
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
