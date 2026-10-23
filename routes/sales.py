from flask import Blueprint, request, jsonify, flash, redirect, render_template, abort, url_for, send_file, session, current_app
from flask_login import login_required, current_user
from models import db, Product, ProductVariant, Sale, SaleDetail, SalePayment, SaleClient, Expense, Retoma, obtener_hora_bogota, PriceApproval, Asesor, Provider, Branch, BranchStock, CashShift
from decorators import admin_required
from decimal import Decimal
from datetime import datetime, timedelta
from sqlalchemy import or_
from sqlalchemy.orm import joinedload

sales_bp = Blueprint('sales_bp', __name__)

def obtener_turno_sucursal(branch_id):
    """Verifica si existe un turno de caja abierto en la sucursal."""
    return CashShift.query.filter_by(branch_id=branch_id, estado='ABIERTA').first()

@sales_bp.route('/nueva', methods=['GET', 'POST'])
@login_required # Importante: Te bloqueará el acceso si no hay current_user logeado (Flask-Login)
def procesar_venta():
    if request.method == 'GET':
        # Validar turno de caja abierto ÚNICAMENTE si la sucursal es de tipo 'tienda'
        # Las sucursales con tipo == 'bodega' quedan completamente exentas
        user_branch_id = current_user.branch_id if current_user.rol in ['vendedor', 'bodega'] else (session.get('active_branch_id') or 1)
        user_branch = Branch.query.get(user_branch_id)
        es_tienda = bool(user_branch and user_branch.tipo == 'tienda')
        turno_activo = obtener_turno_sucursal(user_branch_id) if es_tienda else None

        if es_tienda and not turno_activo and current_user.rol == 'vendedor':
            flash(f"Atención: La tienda '{user_branch.nombre}' requiere la Apertura de Caja de tu turno antes de comenzar a registrar ventas.", "warning")
            return redirect(url_for('arqueo_bp.abrir_turno'))

        asesores = Asesor.query.filter_by(activo=True).order_by(Asesor.nombre).all()
        providers = Provider.query.order_by(Provider.nombre).all()
        return render_template('sales/nueva.html', asesores=asesores, providers=providers, turno_activo=turno_activo, sucursal_actual=user_branch)

    """
    Se espera que los datos vengan en el cuerpo de la petición (JSON)
    Ej: {'items': [{ 'product_id': 1, 'cantidad': 2, 'precio_final': 15.50}, ...], 'metodo_pago': 'transferencia'}
    """
    data = request.get_json()
    items = data.get('items', [])
    pagos_data = data.get('pagos', [])  # Nuevo: array de pagos mixtos
    metodo_pago_legacy = data.get('metodo_pago', 'efectivo')  # Retrocompatibilidad
    asesor_id = data.get('asesor_id')
    provider_id = data.get('provider_id')
    
    if not items:
        return jsonify({'error': 'No se enviaron productos para la venta'}), 400

    # Si no se envían pagos en el nuevo formato, crear uno único con el método legacy
    if not pagos_data:
        pagos_data = [{'metodo_pago': metodo_pago_legacy, 'monto': None}]  # monto=None se llenará con el total

    try:
        # Determinar el método de pago principal (para la columna legacy de retrocompatibilidad)
        if len(pagos_data) == 1:
            metodo_pago_principal = pagos_data[0].get('metodo_pago', 'efectivo')
        else:
            metodo_pago_principal = 'mixto'

        # Manejar Fecha de Venta para registros de fechas anteriores
        fecha_venta_str = data.get('fecha_venta')
        fecha_venta_obj = obtener_hora_bogota()
        if fecha_venta_str:
            try:
                fecha_seleccionada = datetime.strptime(fecha_venta_str, '%Y-%m-%d').date()
                if fecha_seleccionada != fecha_venta_obj.date():
                    # Si no es hoy, combinamos la fecha seleccionada con la hora actual para conservar secuencialidad de hora de registro
                    fecha_venta_obj = datetime.combine(fecha_seleccionada, fecha_venta_obj.time())
            except ValueError:
                pass # Fallback silencioso a la hora actual si el formato falla

        # Validar tipo de venta (Celulares vs General) y evitar mezcla
        tipo_venta_detectado = None
        for item in items:
            es_manual = item.get('es_manual', False)
            precio_venta_final = Decimal(str(item.get('precio_final', '0.00')))
            variant_id = item.get('variant_id')

            if es_manual:
                tipo_item = 'general'
            else:
                prod_id = item.get('product_id')
                producto_check = Product.query.get(prod_id)
                if not producto_check:
                    return jsonify({'error': f"El producto con ID {prod_id} no existe."}), 400
                
                # Validar precio mínimo y consultar aprobaciones remotas si es menor
                if current_user.rol != 'admin' and precio_venta_final < producto_check.precio_minimo:
                    aprobacion = PriceApproval.query.filter_by(
                        vendedor_id=current_user.id,
                        product_id=prod_id,
                        variant_id=variant_id,
                        estado='aprobado'
                    ).filter(PriceApproval.precio_aprobado <= precio_venta_final).first()
                    
                    if not aprobacion:
                        return jsonify({'error': f'El precio de {producto_check.nombre} (${precio_venta_final}) es inferior al mínimo permitido y no tiene aprobación remota válida.'}), 400
                    else:
                        # Marcar la aprobación como 'completada'
                        aprobacion.estado = 'completada'
                
                tipo_item = 'celulares' if producto_check.tipo_inventario == 'celulares' else 'general'
            
            if tipo_venta_detectado is None:
                tipo_venta_detectado = tipo_item
            elif tipo_item == 'celulares':
                tipo_venta_detectado = 'celulares'
        
        tipo_venta_detectado = tipo_venta_detectado or 'general'

        # Determinar la Sucursal de la Venta (sale_branch_id)
        if current_user.rol in ['vendedor', 'bodega']:
            sale_branch_id = current_user.branch_id
            if not sale_branch_id:
                branch_defecto = Branch.query.filter_by(activa=True).order_by(Branch.id.asc()).first()
                sale_branch_id = branch_defecto.id if branch_defecto else 1
        else:
            # Para administradores: usa sucursal activa seleccionada o 'Principal'
            active_b = session.get('active_branch_id')
            if active_b:
                sale_branch_id = int(active_b)
            else:
                branch_princ = Branch.query.filter((Branch.nombre.ilike('%principal%')) | (Branch.codigo == 'LOC1')).first()
                if not branch_princ:
                    branch_princ = Branch.query.filter_by(activa=True).order_by(Branch.id.asc()).first()
                sale_branch_id = branch_princ.id if branch_princ else 1

        sale_branch = Branch.query.with_for_update().get(sale_branch_id)
        if not sale_branch:
            return jsonify({'error': 'La sucursal asignada a la venta no existe.'}), 400
        sale_branch_nombre = sale_branch.nombre

        # Validar turno de caja abierto ÚNICAMENTE si la sucursal es de tipo 'tienda'
        # Las bodegas quedan completamente exentas de turnos, bases iniciales y asignación de asesores
        if sale_branch.tipo == 'tienda':
            turno_activo = CashShift.query.filter_by(branch_id=sale_branch_id, estado='ABIERTA').first()
            if not turno_activo and current_user.rol == 'vendedor':
                return jsonify({'error': f"Caja cerrada: La tienda '{sale_branch_nombre}' requiere un turno de caja abierto para registrar ventas. Debe abrir turno primero."}), 403
        else:
            turno_activo = None

        # Consecutivo por Sede seguro y atómico con with_for_update
        sale_branch.ultimo_consecutivo = (sale_branch.ultimo_consecutivo or 0) + 1
        prefijo_sede = sale_branch.prefijo_factura or 'FAC'
        numero_factura_generado = f"{prefijo_sede}-{sale_branch.ultimo_consecutivo}"

        nueva_venta = Sale(
            vendedor_id=current_user.id,
            asesor_id=asesor_id,
            provider_id=provider_id,
            monto_total=Decimal('0.00'),
            metodo_pago=metodo_pago_principal,
            fecha_venta=fecha_venta_obj,
            tipo_venta=tipo_venta_detectado,
            sucursal=sale_branch_nombre,
            branch_id=sale_branch_id,
            numero_factura=numero_factura_generado,
            shift_id=turno_activo.id if turno_activo else None
        )
        db.session.add(nueva_venta)
        db.session.flush()

        monto_total = Decimal('0.00')

        from services.stock_service import get_or_create_branch_stock, sync_global_product_stock

        for item in items:
            product_id = item.get('product_id')
            variant_id = item.get('variant_id') # Posible variante
            cantidad_vendida = int(item.get('cantidad', 0))
            precio_venta_final = Decimal(str(item.get('precio_final', '0.00')))
            es_manual = item.get('es_manual', False)
            es_obsequio = item.get('es_obsequio', False)

            if cantidad_vendida <= 0:
                raise ValueError("La cantidad vendida debe ser mayor a 0.")

            if es_manual:
                # Producto manual (prestado) — no descuenta stock
                nombre_manual = item.get('nombre_manual', 'Producto Externo')
                precio_costo_manual = Decimal(str(item.get('precio_costo', '0.00')))

                detalle = SaleDetail(
                    sale_id=nueva_venta.id,
                    product_id=None,
                    variant_id=None,
                    cantidad_vendida=cantidad_vendida,
                    precio_venta_final=precio_venta_final,
                    nombre_manual=nombre_manual,
                    precio_costo_manual=precio_costo_manual
                )
                db.session.add(detalle)
                monto_total += (precio_venta_final * cantidad_vendida)

                # Crear el gasto automático para descontar el ingreso prestado del balance final
                if precio_costo_manual > 0:
                    gasto_externo = Expense(
                        usuario_id=current_user.id,
                        tipo_gasto='Gasto Diario',
                        categoria='Pago Prod. Externo',
                        descripcion=f"Pago por producto manual prestado: {nombre_manual}",
                        monto=(precio_costo_manual * cantidad_vendida),
                        fecha_gasto=fecha_venta_obj,
                        sucursal=sale_branch_nombre,
                        branch_id=sale_branch_id
                    )
                    db.session.add(gasto_externo)
            else:
                # Producto del inventario propio con bloqueo a nivel de sucursal
                producto = Product.query.with_for_update().get(product_id)
                
                if not producto:
                    raise ValueError(f"El producto con ID {product_id} no existe.")

                # Bloqueo y validación de stock local en BranchStock
                branch_stock = get_or_create_branch_stock(sale_branch_id, producto.id, variant_id, for_update=True)
                
                if variant_id:
                    variante = ProductVariant.query.with_for_update().get(variant_id)
                    if not variante:
                        raise ValueError(f"La variante con ID {variant_id} no existe.")
                    
                    if branch_stock.cantidad < cantidad_vendida:
                        raise ValueError(
                            f"Stock insuficiente en la sucursal '{sale_branch_nombre}' para '{producto.nombre} ({variante.nombre_variante})'. "
                            f"Disponible local: {branch_stock.cantidad}, Solicitado: {cantidad_vendida}."
                        )
                    
                    stock_anterior_local = branch_stock.cantidad
                    branch_stock.cantidad -= cantidad_vendida
                    sync_global_product_stock(producto.id, variant_id)

                    precio_limite_autorizado = variante.precio_costo if current_user.rol == 'admin' else variante.precio_minimo
                    
                    from models import StockAdjustment
                    ajuste = StockAdjustment(
                        product_id=producto.id,
                        admin_id=current_user.id,
                        branch_id=sale_branch_id,
                        tipo_movimiento=f"Venta Tienda (Subcat: {variante.nombre_variante}) #{nueva_venta.id}",
                        stock_anterior=stock_anterior_local,
                        stock_nuevo=branch_stock.cantidad
                    )
                    db.session.add(ajuste)
                else:
                    if branch_stock.cantidad < cantidad_vendida:
                        raise ValueError(
                            f"Stock insuficiente en la sucursal '{sale_branch_nombre}' para '{producto.nombre}'. "
                            f"Disponible local: {branch_stock.cantidad}, Solicitado: {cantidad_vendida}."
                        )
                    
                    stock_anterior_local = branch_stock.cantidad
                    branch_stock.cantidad -= cantidad_vendida
                    sync_global_product_stock(producto.id, None)

                    precio_limite_autorizado = producto.precio_costo if current_user.rol == 'admin' else producto.precio_minimo
                    
                    from models import StockAdjustment
                    ajuste = StockAdjustment(
                        product_id=producto.id,
                        admin_id=current_user.id,
                        branch_id=sale_branch_id,
                        tipo_movimiento=f"Venta Tienda #{nueva_venta.id}",
                        stock_anterior=stock_anterior_local,
                        stock_nuevo=branch_stock.cantidad
                    )
                    db.session.add(ajuste)

                if not es_obsequio and precio_venta_final < precio_limite_autorizado:
                    raise ValueError(f"No autorizado: El precio ({precio_venta_final}) del producto '{producto.nombre}' está por debajo del límite permitido ({precio_limite_autorizado}).")

                detalle = SaleDetail(
                    sale_id=nueva_venta.id,
                    product_id=producto.id,
                    variant_id=variant_id,
                    cantidad_vendida=cantidad_vendida,
                    precio_venta_final=precio_venta_final
                )
                db.session.add(detalle)
                db.session.flush()
                
                # Facturación automática al proveedor para productos asociados a un proveedor
                if producto.proveedor and producto.tipo_inventario in ['celulares', 'externos']:
                    provider_obj = Provider.query.filter(Provider.nombre.ilike(producto.proveedor.strip())).first()
                    if provider_obj and producto.precio_costo and producto.precio_costo > 0:
                        from models import ProviderInvoice
                        ref_factura = producto.modelo_celular if producto.modelo_celular else producto.nombre
                        if producto.imei:
                            ref_factura = f"{ref_factura} (IMEI: {producto.imei})"
                        # Crear la factura de deuda al proveedor
                        factura_prov = ProviderInvoice(
                            provider_id=provider_obj.id,
                            sale_id=nueva_venta.id,
                            monto_total=(producto.precio_costo * cantidad_vendida),
                            numero_factura=ref_factura,
                            descripcion=f"Venta #{nueva_venta.id}"
                        )
                        db.session.add(factura_prov)
                
                monto_total += (precio_venta_final * cantidad_vendida)

        # Manejar información de Retoma (soporta 1 o múltiples retomas)
        retoma_data_input = data.get('retoma_data')
        retomas_list = []
        if retoma_data_input:
            if isinstance(retoma_data_input, list):
                retomas_list = retoma_data_input
            elif isinstance(retoma_data_input, dict):
                retomas_list = [retoma_data_input]

        monto_retomas_total = Decimal('0.00')
        for r_item in retomas_list:
            v_retoma = Decimal(str(r_item.get('valor_retoma', 0)))
            if v_retoma <= 0:
                raise ValueError("El monto acreditado por cada retoma debe ser mayor a 0.")
            monto_retomas_total += v_retoma

        monto_total = max(Decimal('0.00'), monto_total - monto_retomas_total)

        nueva_venta.monto_total = monto_total

        # Registrar los pagos mixtos en la tabla sale_payments
        total_pagos = Decimal('0.00')
        for pago_info in pagos_data:
            metodo = pago_info.get('metodo_pago', 'efectivo')
            monto_pago = pago_info.get('monto')
            p_provider_id = pago_info.get('provider_id') or provider_id
            p_comprobante = pago_info.get('comprobante', '').strip() if pago_info.get('comprobante') else None
            
            if monto_pago is None:
                # Si solo hay un pago sin monto explícito, asignar el total completo
                monto_pago = monto_total
            else:
                monto_pago = Decimal(str(monto_pago))
            
            if monto_pago <= 0:
                if monto_total == 0:
                    continue # Salto el pago si el total a pagar es 0 (ej. cubierto 100% por retoma)
                raise ValueError(f"El monto del pago por '{metodo}' debe ser mayor a 0.")
            
            # Validación y contabilidad para Método de Pago: Abono a Terceros / Proveedor
            if metodo == 'abono_tercero':
                if not p_provider_id:
                    raise ValueError("El método 'Abono a Terceros / Proveedor' exige obligatoriamente seleccionar el Proveedor destinatario.")
                if not p_comprobante:
                    raise ValueError("El método 'Abono a Terceros / Proveedor' exige obligatoriamente adjuntar el número o foto de soporte/comprobante.")
                
                prov_dest = Provider.query.get(p_provider_id)
                if not prov_dest:
                    raise ValueError(f"El proveedor seleccionado (ID {p_provider_id}) no existe en el sistema.")
                
                from models import ProviderPayment
                nuevo_abono_prov = ProviderPayment(
                    provider_id=prov_dest.id,
                    monto_abonado=monto_pago,
                    metodo_pago='abono_tercero',
                    observacion=f"Abono directo por Venta #{nueva_venta.id} - Soporte: {p_comprobante}",
                    fecha_pago=fecha_venta_obj
                )
                db.session.add(nuevo_abono_prov)

            pago = SalePayment(
                sale_id=nueva_venta.id,
                metodo_pago=metodo,
                monto=monto_pago,
                provider_id=p_provider_id if metodo == 'abono_tercero' else None,
                comprobante=p_comprobante if metodo == 'abono_tercero' else None
            )
            db.session.add(pago)
            total_pagos += monto_pago

        # Si el total a pagar es 0 (cubierto 100% por retoma) y no hay pagos guardados:
        if monto_total == 0 and not nueva_venta.pagos:
            pago_retoma = SalePayment(
                sale_id=nueva_venta.id,
                metodo_pago='retoma',
                monto=Decimal('0.00')
            )
            db.session.add(pago_retoma)

        # Validar que la suma de pagos cubra el total de la venta
        if total_pagos != monto_total:
            raise ValueError(f"La suma de los pagos (${total_pagos}) no coincide con el total de la venta (${monto_total}). Diferencia: ${monto_total - total_pagos}.")

        # Crear los registros de Retoma si aplican (con validaciones de IMEI único)
        imeis_procesados = set()
        for r_item in retomas_list:
            modelo_val = r_item.get('modelo', '').strip()
            imei1_val = r_item.get('imei1', '').strip()
            v_retoma = Decimal(str(r_item.get('valor_retoma', 0)))

            if not modelo_val or not imei1_val:
                raise ValueError("El modelo y el IMEI 1 son obligatorios para cada retoma.")

            if imei1_val in imeis_procesados:
                raise ValueError(f"El IMEI '{imei1_val}' está repetido en la lista de retomas de esta factura.")
            imeis_procesados.add(imei1_val)

            # 1. Verificar si hay una retoma PENDIENTE por evaluar con el mismo IMEI
            retoma_pendiente = Retoma.query.filter_by(imei1=imei1_val, estado='en_evaluacion').first()
            if retoma_pendiente:
                raise ValueError(f"El IMEI 1 '{imei1_val}' ya se encuentra registrado en la retoma #{retoma_pendiente.id} (pendiente en cuarentena).")

            # 2. Verificar si el IMEI pertenece a un celular actualmente disponible en stock
            producto_activo = Product.query.filter(
                ((Product.imei == imei1_val) | (Product.imei2 == imei1_val)),
                Product.cantidad_stock > 0
            ).first()
            if producto_activo:
                raise ValueError(f"El IMEI '{imei1_val}' pertenece a un equipo disponible en el inventario activo ({producto_activo.nombre}).")

            retoma_registro = Retoma(
                sale_id=nueva_venta.id,
                branch_id=sale_branch_id,
                modelo=modelo_val,
                marca=r_item.get('marca', '').strip(),
                proveedor='Cliente',
                valor_retoma=v_retoma,
                imei1=imei1_val,
                imei2=r_item.get('imei2', '').strip(),
                color=r_item.get('color', '').strip(),
                bateria=r_item.get('bateria', '').strip(),
                memoria=r_item.get('memoria', '').strip(),
                observaciones=r_item.get('observaciones', '').strip(),
                vendedor_id=current_user.id
            )
            db.session.add(retoma_registro)

        cliente_data = data.get('cliente')
        if cliente_data and isinstance(cliente_data, dict):
            cliente = SaleClient(
                sale_id=nueva_venta.id,
                nombre=cliente_data.get('nombre', 'Desconocido').strip(),
                documento=cliente_data.get('documento', '0').strip(),
                telefono=cliente_data.get('telefono', '').strip(),
                email=cliente_data.get('email', '').strip() if cliente_data.get('email') else None,
                direccion=cliente_data.get('direccion', '').strip() if cliente_data.get('direccion') else None
            )
            db.session.add(cliente)

        db.session.commit()
        
        return jsonify({
            'success': True, 
            'message': 'Venta registrada e inventario descontado con éxito.',
            'sale_id': nueva_venta.id,
            'numero_factura': nueva_venta.numero_factura,
            'total': str(monto_total)
        }), 201

    except ValueError as val_err:
        db.session.rollback()
        return jsonify({'error': str(val_err)}), 400
        
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Error procesando venta: {str(e)}", exc_info=True)
        return jsonify({'error': f'Error en el servidor al procesar la venta: {str(e)}'}), 500

# Endpoint API asíncrono para el escáner del Punto de Venta
@sales_bp.route('/api/producto/<path:sku>', methods=['GET'])
@login_required
def api_buscar_producto(sku):
    producto = Product.query.filter(
        Product.tipo_inventario.in_(['tienda', 'celulares', 'externos']),
        or_(
            Product.sku == sku,
            Product.imei == sku,
            Product.imei2 == sku
        )
    ).first()
    auto_select_variant = None
    
    if not producto:
        # Búsqueda por IMEI en variantes de celulares
        variante = ProductVariant.query.join(Product).filter(
            Product.tipo_inventario == 'celulares',
            ProductVariant.nombre_variante.like(f"%{sku}%")
        ).first()
        
        if variante:
            producto = variante.producto
            auto_select_variant = variante.id
        else:
            return jsonify({'error': 'Código SKU o IMEI no encontrado en el sistema'}), 404
        
    # Determinar sucursal para consulta de stock
    active_b_id = current_user.branch_id if current_user.rol in ['vendedor', 'bodega'] else session.get('active_branch_id')
    
    if active_b_id:
        from services.stock_service import get_or_create_branch_stock
        stock_prod_local = get_or_create_branch_stock(int(active_b_id), producto.id, None).cantidad
        variantes_data = []
        for v in producto.variantes:
            v_stock_local = get_or_create_branch_stock(int(active_b_id), producto.id, v.id).cantidad
            variantes_data.append({
                "id": v.id,
                "nombre": v.nombre_variante,
                "stock": v_stock_local,
                "precio_minimo": float(v.precio_minimo or producto.precio_minimo),
                "precio_limite": float(v.precio_costo or producto.precio_costo) if current_user.rol == 'admin' else float(v.precio_minimo or producto.precio_minimo),
                "precio_sugerido": float(v.precio_sugerido or producto.precio_sugerido)
            })
        stock_disponible = stock_prod_local if not producto.variantes else sum(vd['stock'] for vd in variantes_data)
    else:
        stock_disponible = producto.total_stock
        variantes_data = [
            {
                "id": v.id,
                "nombre": v.nombre_variante,
                "stock": v.cantidad_stock,
                "precio_minimo": float(v.precio_minimo or producto.precio_minimo),
                "precio_limite": float(v.precio_costo or producto.precio_costo) if current_user.rol == 'admin' else float(v.precio_minimo or producto.precio_minimo),
                "precio_sugerido": float(v.precio_sugerido or producto.precio_sugerido)
            }
            for v in producto.variantes
        ]

    return jsonify({
        'id': producto.id,
        'nombre': producto.nombre,
        'sku': producto.sku,
        'tipo_inventario': producto.tipo_inventario,
        'cantidad_stock': stock_disponible,
        'precio_minimo': float(producto.precio_minimo),
        'precio_limite': float(producto.precio_costo) if current_user.rol == 'admin' else float(producto.precio_minimo),
        'precio_sugerido': float(producto.precio_sugerido),
        'imei': producto.imei,
        'imei2': producto.imei2,
        'variantes': variantes_data,
        'auto_select_variant': auto_select_variant
    })

# Ruta para la Impresión del formato de Factura/Recibo POS y Garantía Multisede
@sales_bp.route('/recibo/<int:sale_id>', methods=['GET'])
@login_required # Proteger confidencialidad del cajero
def imprimir_ticket(sale_id):
    # Regla: Retorna 404 si alguien ingresa un ID falso
    venta = Sale.query.get_or_404(sale_id)
    formato = request.args.get('format', 'factura')
    if formato == 'ticket':
        return render_template('sales/ticket.html', venta=venta)
    return render_template('sales/factura_impresion.html', venta=venta)

@sales_bp.route('/factura/<int:sale_id>', methods=['GET'])
@login_required
def imprimir_factura(sale_id):
    venta = Sale.query.get_or_404(sale_id)
    return render_template('sales/factura_impresion.html', venta=venta)

# Endpoint Historial de Ventas (Administradores)
@sales_bp.route('/historial', methods=['GET'])
@login_required
@admin_required
def historial():
    # Calcular el valor exacto de 'HOY' en Bogotá
    page = request.args.get('page', 1, type=int)
    hoy_bogota = obtener_hora_bogota().strftime('%Y-%m-%d')
    
    # Si existen los args, los usa, de lo contrario colapsa a HOY por defecto
    fecha_inicio = request.args.get('fecha_inicio', hoy_bogota)
    fecha_fin = request.args.get('fecha_fin', hoy_bogota)
    
    # Optimización: eager loading (evita N+1 con joinedload)
    query = Sale.query.options(joinedload(Sale.vendedor))
    
    # Motor de búsqueda por Rango Restricto
    if fecha_inicio:
        inicio_dt = datetime.strptime(fecha_inicio, '%Y-%m-%d')
        query = query.filter(Sale.fecha_venta >= inicio_dt)
        
    if fecha_fin:
        fin_dt = datetime.strptime(fecha_fin, '%Y-%m-%d')
        # Sumar 1 día matemáticamente para incluir los registros hasta las 23:59:59 del último día
        query = query.filter(Sale.fecha_venta < fin_dt + timedelta(days=1))
        
    # Todas las ventas para cálculo de totales
    todas_las_ventas = query.order_by(Sale.fecha_venta.desc()).all()
    
    # Paginación a 30 registros por página
    paginacion = query.order_by(Sale.fecha_venta.desc()).paginate(page=page, per_page=30, error_out=False)
    ventas = paginacion.items
    
    # Auditar y cruzar sumatorios de métricas de pago
    # Sistema híbrido: usa SalePayment si existe, caso contrario cae al metodo_pago legacy
    total_efectivo = Decimal('0')
    total_bancolombia = Decimal('0')
    total_daviplata = Decimal('0')
    total_tarjeta_credito = Decimal('0')
    total_addi = Decimal('0')
    total_sitecredito = Decimal('0')
    total_otros = Decimal('0')  # Para retomas, nequi viejo, etc.
    total_retomas = Decimal('0')
    total_mixto = 0  # Contador de ventas con pago mixto

    for v in todas_las_ventas:
        if v.pagos:  # Pagos nuevos con tabla sale_payments
            for pago in v.pagos:
                if pago.metodo_pago == 'efectivo':
                    total_efectivo += pago.monto
                elif pago.metodo_pago == 'bancolombia':
                    total_bancolombia += pago.monto
                elif pago.metodo_pago == 'daviplata':
                    total_daviplata += pago.monto
                elif pago.metodo_pago == 'tarjeta_credito':
                    total_tarjeta_credito += pago.monto
                elif pago.metodo_pago == 'addi':
                    total_addi += pago.monto
                elif pago.metodo_pago == 'sitecredito':
                    total_sitecredito += pago.monto
                else:
                    total_otros += pago.monto
            if len(v.pagos) > 1:
                total_mixto += 1
        else:  # Retrocompatibilidad con ventas antiguas sin SalePayment
            if v.metodo_pago == 'efectivo':
                total_efectivo += v.monto_total
            elif v.metodo_pago == 'bancolombia':
                total_bancolombia += v.monto_total
            elif v.metodo_pago == 'daviplata':
                total_daviplata += v.monto_total
            elif v.metodo_pago == 'tarjeta_credito':
                total_tarjeta_credito += v.monto_total
            elif v.metodo_pago == 'addi':
                total_addi += v.monto_total
            elif v.metodo_pago == 'sitecredito':
                total_sitecredito += v.monto_total
            else:
                total_otros += v.monto_total

    # Envío al Engine de HTML
    return render_template('sales/historial.html', 
                           ventas=ventas, 
                           paginacion=paginacion,
                           total_efectivo=total_efectivo,
                           total_bancolombia=total_bancolombia,
                           total_daviplata=total_daviplata,
                           total_tarjeta_credito=total_tarjeta_credito,
                           total_addi=total_addi,
                           total_sitecredito=total_sitecredito,
                           total_otros=total_otros,
                           total_mixto=total_mixto,
                           fecha_inicio=fecha_inicio,
                           fecha_fin=fecha_fin)


@sales_bp.route('/exportar-excel', methods=['GET'])
@login_required
@admin_required
def exportar_excel():
    import io
    import pandas as pd
    from decimal import Decimal
    from datetime import datetime, timedelta

    hoy_bogota = obtener_hora_bogota().strftime('%Y-%m-%d')
    fecha_inicio = request.args.get('fecha_inicio', hoy_bogota)
    fecha_fin = request.args.get('fecha_fin', hoy_bogota)

    query = Sale.query.options(
        joinedload(Sale.vendedor),
        joinedload(Sale.asesor),
        joinedload(Sale.detalles).joinedload(SaleDetail.producto),
        joinedload(Sale.detalles).joinedload(SaleDetail.variante),
        joinedload(Sale.pagos),
        joinedload(Sale.retomas_asociadas)
    )

    if fecha_inicio:
        inicio_dt = datetime.strptime(fecha_inicio, '%Y-%m-%d')
        query = query.filter(Sale.fecha_venta >= inicio_dt)

    if fecha_fin:
        fin_dt = datetime.strptime(fecha_fin, '%Y-%m-%d')
        query = query.filter(Sale.fecha_venta < fin_dt + timedelta(days=1))

    ventas = query.order_by(Sale.fecha_venta.asc()).all()

    filas = []
    for v in ventas:
        ticket_str = f"#{v.id:05d}"
        fecha_str = v.fecha_venta.strftime('%Y-%m-%d %H:%M') if v.fecha_venta else ''
        vendedor_str = v.vendedor.nombre if v.vendedor else 'N/A'
        asesor_str = v.asesor.nombre if v.asesor else 'N/A'
        sucursal_str = v.sucursal or 'PRINCIPAL'
        metodo_pago_str = v.metodo_pago_display
        retomas_valor_total = sum(Decimal(str(r.valor_retoma or 0)) for r in v.retomas_asociadas)
        retomas_info_str = ", ".join(f"{r.modelo} (IMEI: {r.imei1})" for r in v.retomas_asociadas) if v.retomas_asociadas else ""
        
        # Detalle de vía de pago clarificado si incluye retoma
        if retomas_valor_total > 0 and 'retoma' not in metodo_pago_str.lower():
            if float(v.monto_total or 0) > 0:
                metodo_pago_str = f"{metodo_pago_str} + Retoma"
            else:
                metodo_pago_str = "Retoma (100%)"

        if not v.detalles:
            filas.append({
                'Ticket': ticket_str,
                'Fecha': fecha_str,
                'Vendedor': vendedor_str,
                'Asesor': asesor_str,
                'Sucursal': sucursal_str,
                'Producto / Artículo': 'Venta sin detalle específico',
                'Cant.': 1,
                'Costo Unitario ($)': 0.0,
                'Costo Total ($)': 0.0,
                'Precio Venta Unitario ($)': float(v.monto_total or 0),
                'Precio Venta Total ($)': float(v.monto_total or 0),
                'Utilidad Bruta ($)': float(v.monto_total or 0),
                'Margen (%)': 100.0,
                'Vía de Pago': metodo_pago_str,
                'Valor Retoma ($)': float(retomas_valor_total),
                'Equipo(s) Recibido en Retoma': retomas_info_str
            })
            continue

        for idx, d in enumerate(v.detalles):
            cant = d.cantidad_vendida or 1
            precio_venta_u = Decimal(str(d.precio_venta_final or 0))
            precio_venta_tot = precio_venta_u * cant

            # Determinar nombre del producto y costo
            if d.nombre_manual:
                prod_nombre = f"{d.nombre_manual} (Externo/Manual)"
                costo_u = Decimal(str(d.precio_costo_manual or 0))
            elif d.variant_id:
                vari = d.variante
                prod = d.producto or (vari.producto if vari else None)
                p_nombre = prod.nombre if prod else 'Producto'
                v_nombre = vari.nombre_variante if vari else ''
                prod_nombre = f"{p_nombre} [{v_nombre}]"
                costo_u = Decimal(str((vari.precio_costo if (vari and vari.precio_costo is not None) else (prod.precio_costo if prod else 0)) or 0))
            elif d.product_id:
                prod = d.producto
                if prod:
                    if prod.imei:
                        prod_nombre = f"{prod.nombre} (IMEI: {prod.imei})"
                    else:
                        prod_nombre = prod.nombre
                    costo_u = Decimal(str(prod.precio_costo or 0))
                else:
                    prod_nombre = f"Producto ID {d.product_id}"
                    costo_u = Decimal('0.00')
            else:
                prod_nombre = 'Artículo sin identificar'
                costo_u = Decimal('0.00')

            costo_tot = costo_u * cant
            utilidad_bruta = precio_venta_tot - costo_tot
            margen_pct = round(float((utilidad_bruta / precio_venta_tot * 100)), 1) if precio_venta_tot > 0 else 0.0

            # Si el ticket tiene varios productos, asignar el valor de la retoma solo a la primera fila
            # para evitar que una suma general de la columna en Excel duplique el valor de las retomas
            val_retoma_fila = float(retomas_valor_total) if idx == 0 else 0.0
            detalle_retoma_fila = retomas_info_str if idx == 0 else (f"(Retoma incluida en {ticket_str})" if retomas_info_str else "")

            filas.append({
                'Ticket': ticket_str,
                'Fecha': fecha_str,
                'Vendedor': vendedor_str,
                'Asesor': asesor_str,
                'Sucursal': sucursal_str,
                'Producto / Artículo': prod_nombre,
                'Cant.': cant,
                'Costo Unitario ($)': float(costo_u),
                'Costo Total ($)': float(costo_tot),
                'Precio Venta Unitario ($)': float(precio_venta_u),
                'Precio Venta Total ($)': float(precio_venta_tot),
                'Utilidad Bruta ($)': float(utilidad_bruta),
                'Margen (%)': margen_pct,
                'Vía de Pago': metodo_pago_str,
                'Valor Retoma ($)': val_retoma_fila,
                'Equipo(s) Recibido en Retoma': detalle_retoma_fila
            })

    df = pd.DataFrame(filas)
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        df.to_excel(writer, index=False, sheet_name='Reporte_Ventas_Costos')
        ws = writer.sheets['Reporte_Ventas_Costos']
        # Ajustar ancho de columnas
        for col in ws.columns:
            max_len = max(len(str(cell.value or '')) for cell in col)
            col_letter = col[0].column_letter
            ws.column_dimensions[col_letter].width = max(max_len + 3, 12)

    output.seek(0)
    filename = f"Reporte_Ventas_Costos_{fecha_inicio}_al_{fecha_fin}.xlsx"
    return send_file(
        output,
        mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        as_attachment=True,
        download_name=filename
    )


# Endpoint Visor de Ventas del Día para Cajeros (Solo lectura, se resetea cada día)
@sales_bp.route('/ventas_hoy', methods=['GET'])
@login_required
def ventas_hoy():
    # Obtener la fecha de hoy
    hoy_bogota = obtener_hora_bogota().date()
    # Para la consulta requerimos abarcar desde las 00:00:00 hasta las 23:59:59
    inicio_dt = datetime.combine(hoy_bogota, datetime.min.time())
    fin_dt = datetime.combine(hoy_bogota, datetime.max.time())
    
    # Consultar todas las ventas de este día (sin importar si es admin o vendedor)
    query = Sale.query.options(joinedload(Sale.vendedor)).filter(
        Sale.fecha_venta >= inicio_dt,
        Sale.fecha_venta <= fin_dt
    )
    
    # Si no es admin, solo ve sus propias ventas
    if current_user.rol != 'admin':
        query = query.filter(Sale.vendedor_id == current_user.id)
        
    ventas = query.order_by(Sale.fecha_venta.desc()).all()
    
    # Acumuladores de las ventas de hoy
    total_efectivo = Decimal('0')
    total_transferencias = Decimal('0')
    total_mixto = 0
    
    for v in ventas:
        if v.pagos:
            for pago in v.pagos:
                if pago.metodo_pago == 'efectivo':
                    total_efectivo += pago.monto
                else: 
                    total_transferencias += pago.monto
            if len(v.pagos) > 1:
                total_mixto += 1
        else:
            if v.metodo_pago == 'efectivo':
                total_efectivo += v.monto_total
            else:
                total_transferencias += v.monto_total
                
    return render_template('sales/ventas_hoy.html',
                           ventas=ventas,
                           total_efectivo=total_efectivo,
                           total_transferencias=total_transferencias,
                           total_mixto=total_mixto,
                           hoy=hoy_bogota.strftime('%Y-%m-%d'))


# Endpoint para Anular/Eliminar Venta Histórica
@sales_bp.route('/eliminar/<int:sale_id>', methods=['POST'])
@login_required
@admin_required
def eliminar_venta(sale_id):
    venta = Sale.query.get_or_404(sale_id)
    
    try:
        # Revertir Stock
        from models import StockAdjustment
        for detalle in venta.detalles:
            if detalle.variant_id:
                variante = ProductVariant.query.with_for_update().get(detalle.variant_id)
                if variante:
                    stock_anterior = variante.cantidad_stock
                    variante.cantidad_stock += detalle.cantidad_vendida
                    
                    ajuste = StockAdjustment(
                        product_id=detalle.product_id,
                        admin_id=current_user.id,
                        tipo_movimiento=f"Anulación Venta #{venta.id} (Subcat: {variante.nombre_variante})",
                        stock_anterior=stock_anterior,
                        stock_nuevo=variante.cantidad_stock
                    )
                    db.session.add(ajuste)
                    
                producto = Product.query.with_for_update().get(detalle.product_id)
                if producto:
                    producto.cantidad_stock += detalle.cantidad_vendida
            elif detalle.product_id:
                producto = Product.query.with_for_update().get(detalle.product_id)
                if producto:
                    stock_anterior = producto.cantidad_stock
                    producto.cantidad_stock += detalle.cantidad_vendida
                    
                    ajuste = StockAdjustment(
                        product_id=producto.id,
                        admin_id=current_user.id,
                        tipo_movimiento=f"Anulación Venta #{venta.id}",
                        stock_anterior=stock_anterior,
                        stock_nuevo=producto.cantidad_stock
                    )
                    db.session.add(ajuste)
                    
        # Verificar y eliminar Retomas asociadas
        if hasattr(venta, 'retomas_asociadas') and venta.retomas_asociadas:
            for retoma in venta.retomas_asociadas:
                if retoma.estado == 'aprobado':
                    raise ValueError("No se puede anular la venta porque tiene una retoma asociada que ya fue aprobada e ingresada al inventario.")
                db.session.delete(retoma)

        # Eliminar Venta y Detalles (Cascada)
        from models import AuditLog
        motivo_anulacion = request.form.get('motivo_anulacion', 'Cancelación y reversión de inventario por decisión administrativa')
        monto_anulado = float(venta.monto_total or 0)
        
        AuditLog.registrar(
            action='CANCELACION_VENTA',
            user_id=current_user.id,
            motivo=f'Anulación total de Factura #{sale_id} por ${monto_anulado:,.2f}. Motivo: {motivo_anulacion}',
            target_id=sale_id,
            target_type='SALE'
        )

        db.session.delete(venta)
        db.session.commit()
        flash('Venta anulada y stock devuelto exitosamente.', 'success')
        
    except ValueError as ve:
        db.session.rollback()
        flash(str(ve), 'warning')
    except Exception as e:
        db.session.rollback()
        flash('Ocurrió un error al anular la venta.', 'danger')
        
    return redirect(url_for('sales_bp.historial'))

# Endpoint Catálogo Estricto de solo vista para Operarios
@sales_bp.route('/catalogo', methods=['GET'])
@login_required 
def catalogo():
    query_str = request.args.get('q', '').strip()
    page = request.args.get('page', 1, type=int)
    
    base_query = Product.query.filter(
        Product.tipo_inventario.in_(['tienda', 'celulares']),
        Product.cantidad_stock > 0
    )

    if current_user.rol == 'vendedor':
        user_branch_id = current_user.branch_id or 1
        base_query = base_query.join(
            BranchStock,
            (BranchStock.product_id == Product.id) & (BranchStock.branch_id == user_branch_id)
        ).filter(BranchStock.cantidad > 0)
    
    if query_str:
        # Motor de similitud Case-Insensitive (Like)
        search_term = f"%{query_str}%"
        base_query = base_query.filter(
            or_(
                Product.sku.ilike(search_term), 
                Product.nombre.ilike(search_term)
            )
        )
        
    paginacion = base_query.order_by(Product.nombre).paginate(page=page, per_page=20, error_out=False)
        
    return render_template('sales/catalogo.html', productos=paginacion.items, paginacion=paginacion, q=query_str)

@sales_bp.route('/caja_visual', methods=['GET'])
@login_required
def caja_visual():
    from models import obtener_hora_bogota
    hoy_bogota = obtener_hora_bogota()
    
    user_branch_id = current_user.branch_id if current_user.rol in ['vendedor', 'bodega'] else (session.get('active_branch_id') or 1)
    sucursal_obj = Branch.query.get(user_branch_id)
    es_tienda = bool(sucursal_obj and sucursal_obj.tipo == 'tienda')
    turno_activo = obtener_turno_sucursal(user_branch_id) if es_tienda else None

    # Exigencia de apertura de caja y asesores aplica ÚNICAMENTE a sucursales de tipo 'tienda'
    if es_tienda and not turno_activo and current_user.rol == 'vendedor':
        flash(f"Debes abrir turno de caja antes de realizar ventas en la tienda '{sucursal_obj.nombre}'.", "warning")
        return redirect(url_for('arqueo_bp.abrir_turno'))

    if current_user.rol == 'vendedor':
        productos_query = Product.query.join(
            BranchStock,
            (BranchStock.product_id == Product.id) & (BranchStock.branch_id == user_branch_id)
        ).filter(
            Product.tipo_inventario.in_(['tienda', 'celulares']),
            BranchStock.cantidad > 0
        ).order_by(Product.nombre.asc()).all()
        productos = productos_query
    else:
        productos_query = Product.query.filter(Product.tipo_inventario.in_(['tienda', 'celulares'])).order_by(Product.nombre.asc()).all()
        productos = [p for p in productos_query if p.total_stock > 0]
    
    asesores = Asesor.query.filter_by(activo=True).order_by(Asesor.nombre).all()
    providers = Provider.query.order_by(Provider.nombre).all()
    sucursal_obj = Branch.query.get(user_branch_id)
    
    return render_template(
        'sales/caja_visual.html', 
        productos=productos, 
        asesores=asesores, 
        providers=providers, 
        hoy=hoy_bogota.strftime('%Y-%m-%d'),
        turno_activo=turno_activo,
        sucursal_actual=sucursal_obj
    )


# Endpoint para Editar Métodos de Pago y Valor de Venta
@sales_bp.route('/editar_pago/<int:sale_id>', methods=['POST'])
@login_required
@admin_required
def editar_pago_venta(sale_id):
    venta = Sale.query.get_or_404(sale_id)
    
    try:
        # Extraer listas dinámicas de métodos y montos si se enviaron
        metodos_lista = request.form.getlist('payment_method[]')
        montos_lista = request.form.getlist('payment_amount[]')
        
        pagos_procesados = []
        if metodos_lista and montos_lista:
            for met, mon in zip(metodos_lista, montos_lista):
                met = met.strip() if met else ''
                mon_str = str(mon).replace('$', '').replace(',', '').replace('.', '').strip() if mon else ''
                if met and mon_str:
                    try:
                        mon_val = Decimal(mon_str)
                        if mon_val > 0:
                            pagos_procesados.append((met, mon_val))
                    except:
                        pass
        
        # Si no vino como lista (caso fallback o llamada legacy directa con IDs)
        if not pagos_procesados:
            if venta.pagos:
                for pago in venta.pagos:
                    nuevo_metodo = request.form.get(f'payment_method_{pago.id}') or pago.metodo_pago
                    monto_str = request.form.get(f'payment_amount_{pago.id}')
                    if monto_str is not None and monto_str.strip() != '':
                        monto_limpio = Decimal(str(monto_str).replace('$', '').replace(',', '').replace('.', '').strip())
                    else:
                        monto_limpio = pago.monto
                    if nuevo_metodo and monto_limpio > 0:
                        pagos_procesados.append((nuevo_metodo, monto_limpio))
            else:
                nuevo_metodo_legacy = request.form.get('sale_metodo_pago') or venta.metodo_pago
                monto_str = request.form.get('sale_monto_total')
                if monto_str is not None and monto_str.strip() != '':
                    nuevo_monto = Decimal(str(monto_str).replace('$', '').replace(',', '').replace('.', '').strip())
                else:
                    nuevo_monto = Decimal(str(venta.monto_total))
                if nuevo_metodo_legacy and nuevo_monto > 0:
                    pagos_procesados.append((nuevo_metodo_legacy, nuevo_monto))

        if not pagos_procesados:
            flash('Debes ingresar al menos un método de pago con monto mayor a 0.', 'warning')
            return redirect(url_for('sales_bp.historial'))

        # Limpiar pagos antiguos de la venta y recrearlos con los nuevos datos
        SalePayment.query.filter_by(sale_id=venta.id).delete()
        
        nuevo_total = Decimal('0')
        for met, mon_val in pagos_procesados:
            nuevo_pago = SalePayment(
                sale_id=venta.id,
                metodo_pago=met,
                monto=mon_val
            )
            db.session.add(nuevo_pago)
            nuevo_total += mon_val

        monto_anterior = Decimal(str(venta.monto_total)) if venta.monto_total else Decimal('0')
        venta.monto_total = nuevo_total
        venta.metodo_pago = pagos_procesados[0][0] if len(pagos_procesados) == 1 else 'mixto'

        # Ajustar detalles de venta si cambió el total
        if venta.detalles and nuevo_total != monto_anterior and monto_anterior > 0:
            factor = nuevo_total / monto_anterior
            for d in venta.detalles:
                d.precio_venta_final = (Decimal(str(d.precio_venta_final)) * factor).quantize(Decimal('1'))
        elif venta.detalles and len(venta.detalles) == 1 and nuevo_total != monto_anterior:
            venta.detalles[0].precio_venta_final = nuevo_total

        db.session.commit()
        flash('Venta y métodos de pago actualizados correctamente.', 'success')
        
    except Exception as e:
        db.session.rollback()
        flash(f'Ocurrió un error al actualizar la venta: {str(e)}', 'danger')
        
    return redirect(url_for('sales_bp.historial'))
