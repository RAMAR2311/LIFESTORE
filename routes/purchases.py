import json
from decimal import Decimal, InvalidOperation
from datetime import datetime
import pytz
from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify, session
from flask_login import login_required, current_user
from models import db, Product, ProductVariant, Provider, ProviderInvoice, PurchaseOrder, PurchaseOrderItem, Branch, BranchStock, StockAdjustment, obtener_hora_bogota
from services.stock_service import get_or_create_branch_stock, sync_global_product_stock
from decorators import admin_required

purchases_bp = Blueprint('purchases_bp', __name__)

def _resolve_purchase_branch_id(form_branch_id=None):
    if form_branch_id and str(form_branch_id).isdigit():
        return int(form_branch_id)
    if current_user.branch_id:
        return int(current_user.branch_id)
    if session.get('active_branch_id'):
        return int(session['active_branch_id'])
    b_def = Branch.query.filter_by(activa=True).order_by(Branch.id.asc()).first()
    return b_def.id if b_def else 1

@purchases_bp.route('/')
@login_required
def index():
    # Auto-sincronizar compras anteriores que no tenían BranchStock o IMEI vinculado en el producto
    try:
        ordenes_previas = PurchaseOrder.query.order_by(PurchaseOrder.fecha_compra.desc()).all()
        default_b_id = _resolve_purchase_branch_id()
        cambios_sync = False
        for oc in ordenes_previas:
            prov_nom = oc.proveedor.nombre if oc.proveedor else None
            for item in oc.items:
                p = item.producto
                if not p:
                    continue
                if item.imei and not p.imei:
                    Exist = Product.query.filter(Product.imei == item.imei, Product.id != p.id).first()
                    if not Exist:
                        p.imei = item.imei
                        cambios_sync = True
                if item.imei2 and not p.imei2:
                    p.imei2 = item.imei2
                    cambios_sync = True
                if prov_nom and not p.proveedor:
                    p.proveedor = prov_nom
                    cambios_sync = True
                # Si el producto tiene cantidad_stock > 0 pero ninguna fila en BranchStock (y no tiene ventas), inicializar su BranchStock
                total_bs = db.session.query(db.func.coalesce(db.func.sum(BranchStock.cantidad), 0)).filter(
                    BranchStock.product_id == p.id
                ).scalar() or 0
                if total_bs == 0 and p.cantidad_stock > 0:
                    bs = get_or_create_branch_stock(default_b_id, p.id, item.variant_id)
                    bs.cantidad = p.cantidad_stock
                    cambios_sync = True
        if cambios_sync:
            db.session.commit()
    except Exception:
        db.session.rollback()

    compras = PurchaseOrder.query.order_by(PurchaseOrder.fecha_compra.desc()).all()
    proveedores = Provider.query.order_by(Provider.nombre.asc()).all()
    compras_externas = Product.query.filter_by(tipo_inventario='externos').order_by(Product.fecha_creacion.desc()).limit(100).all()
    return render_template('compras/index.html', compras=compras, proveedores=proveedores, compras_externas=compras_externas)

@purchases_bp.route('/nueva')
@login_required
def nueva():
    tipo = request.args.get('tipo', 'accesorios')
    proveedores = Provider.query.order_by(Provider.nombre.asc()).all()
    sucursales = Branch.query.filter_by(activa=True).order_by(Branch.tipo.desc(), Branch.nombre.asc()).all()
    active_b_id = _resolve_purchase_branch_id()
    
    # Obtener todas las referencias registradas en inventario
    referencias_existentes = [r[0] for r in db.session.query(Product.modelo_celular).filter(
        Product.tipo_inventario == 'celulares',
        Product.modelo_celular.isnot(None),
        Product.modelo_celular != ''
    ).distinct().order_by(Product.modelo_celular.asc()).all() if r[0]]

    return render_template(
        'compras/nueva.html',
        tipo=tipo,
        proveedores=proveedores,
        sucursales=sucursales,
        active_b_id=active_b_id,
        referencias_existentes=referencias_existentes
    )

@purchases_bp.route('/detalle/<int:id>')
@login_required
def detalle(id):
    compra = PurchaseOrder.query.get_or_404(id)
    return render_template('compras/detalle.html', compra=compra)

@purchases_bp.route('/api/buscar_productos')
@login_required
def api_buscar_productos():
    tipo = request.args.get('tipo', 'accesorios')
    q = request.args.get('q', '').strip()

    query = Product.query
    if tipo == 'celulares':
        query = query.filter(Product.tipo_inventario == 'celulares')
    else:
        query = query.filter(Product.tipo_inventario.in_(['tienda', 'bodega', 'accesorios']))

    if q:
        from sqlalchemy import or_
        for token in q.split():
            t = token.strip()
            if t:
                query = query.filter(
                    or_(
                        Product.nombre.ilike(f'%{t}%'),
                        Product.sku.ilike(f'%{t}%'),
                        Product.imei.ilike(f'%{t}%'),
                        Product.imei2.ilike(f'%{t}%'),
                        Product.marca.ilike(f'%{t}%'),
                        Product.modelo_celular.ilike(f'%{t}%')
                    )
                )

    productos = query.order_by(Product.nombre.asc()).limit(30).all()

    resultados = []
    for p in productos:
        variantes_data = []
        for v in p.variantes:
            variantes_data.append({
                'id': v.id,
                'nombre': v.nombre_variante,
                'stock': v.cantidad_stock,
                'costo': float(v.precio_costo) if v.precio_costo else (float(p.precio_costo) if p.precio_costo else 0.0)
            })

        resultados.append({
            'id': p.id,
            'nombre': p.nombre,
            'sku': p.sku,
            'marca': p.marca or '',
            'modelo': p.modelo_celular or '',
            'imei': p.imei or '',
            'tipo_inventario': p.tipo_inventario,
            'stock': p.cantidad_stock,
            'costo': float(p.precio_costo) if p.precio_costo else 0.0,
            'variantes': variantes_data
        })

    return jsonify({'productos': resultados})

@purchases_bp.route('/api/crear_producto_rapido', methods=['POST'])
@login_required
def api_crear_producto_rapido():
    """
    Crea un producto o celular en el catálogo directamente desde la orden de compra
    cuando se escanea un código/IMEI/serial que no existía.
    """
    try:
        data = request.get_json() or {}
        tipo = data.get('tipo_inventario', 'accesorios')
        codigo = str(data.get('codigo', '')).strip()
        nombre = str(data.get('nombre', '')).strip()

        if tipo == 'celulares':
            imei_principal = str(data.get('imei') or codigo).strip()
            imei2_val = str(data.get('imei2', '')).strip() or None
            marca_val = data.get('marca', '').strip()
            modelo_val = data.get('modelo', '').strip()

            if not imei_principal:
                return jsonify({'success': False, 'message': 'El serial / IMEI principal es obligatorio.', 'error': 'El serial / IMEI principal es obligatorio.'}), 400

            if not nombre:
                nombre = f"{marca_val} {modelo_val}".strip() or f"Celular {imei_principal}"
        else:
            if not nombre:
                return jsonify({'success': False, 'message': 'El nombre del producto es obligatorio.', 'error': 'El nombre del producto es obligatorio.'}), 400

        try:
            costo = Decimal(str(data.get('costo', 0)))
        except (ValueError, TypeError, InvalidOperation):
            costo = Decimal('0.00')

        try:
            p_sugerido = Decimal(str(data.get('precio_sugerido', costo)))
        except:
            p_sugerido = costo

        try:
            p_minimo = Decimal(str(data.get('precio_minimo', costo)))
        except:
            p_minimo = costo

        if tipo == 'celulares':
            imei_principal = str(data.get('imei') or codigo).strip()
            imei2_val = str(data.get('imei2', '')).strip() or None
            marca_val = data.get('marca', '').strip()
            modelo_val = data.get('modelo', '').strip()

            if not imei_principal:
                return jsonify({'success': False, 'message': 'El serial / IMEI principal es obligatorio.', 'error': 'El serial / IMEI principal es obligatorio.'}), 400

            nombre_final = f"{marca_val} {modelo_val}".strip() or f"Celular IMEI {imei_principal}"

            # Verificar si ya existe este serial/IMEI en la base de datos
            existente = Product.query.filter(
                (Product.imei == imei_principal) | 
                (Product.sku == imei_principal) | 
                (Product.imei2 == imei_principal)
            ).first()
            if existente:
                return jsonify({'success': False, 'message': f'Ya existe un equipo registrado con el IMEI/Serial {imei_principal}: {existente.nombre}', 'error': f'Ya existe un equipo registrado con el IMEI/Serial {imei_principal}'}), 400

            nuevo = Product(
                nombre=nombre_final,
                sku=imei_principal,
                tipo_inventario='celulares',
                cantidad_stock=0, # Se incrementará en 1 al confirmar la orden de compra
                precio_costo=costo,
                precio_sugerido=p_sugerido,
                precio_minimo=p_minimo,
                imei=imei_principal,
                imei2=imei2_val,
                marca=marca_val or None,
                modelo_celular=modelo_val or None,
                color=data.get('color', '').strip() or None,
                memoria=data.get('memoria', '').strip() or None,
                bateria=data.get('bateria', '').strip() or None,
                estado_celular=data.get('estado', 'Nuevo')
            )
            db.session.add(nuevo)
            db.session.commit()

            return jsonify({
                'success': True,
                'producto': {
                    'id': nuevo.id,
                    'nombre': nuevo.nombre,
                    'sku': nuevo.sku,
                    'imei': nuevo.imei or '',
                    'imei2': nuevo.imei2 or '',
                    'marca': nuevo.marca or '',
                    'modelo': nuevo.modelo_celular or '',
                    'tipo_inventario': 'celulares',
                    'stock': 0,
                    'costo': float(nuevo.precio_costo),
                    'variantes': []
                }
            })

        else: # Accesorios y tecnología general
            sku_val = str(data.get('sku') or codigo).strip() or f"ACC-{int(datetime.now().timestamp())}"
            existente = Product.query.filter_by(sku=sku_val).first()
            if existente:
                return jsonify({'success': False, 'message': f'Ya existe un producto con el código SKU {sku_val}: {existente.nombre}', 'error': f'Ya existe un producto con el código SKU {sku_val}'}), 400

            nuevo = Product(
                nombre=nombre,
                sku=sku_val,
                tipo_inventario='tienda',
                cantidad_stock=0,
                precio_costo=costo,
                precio_sugerido=p_sugerido,
                precio_minimo=p_minimo
            )
            db.session.add(nuevo)
            db.session.commit()

            return jsonify({
                'success': True,
                'producto': {
                    'id': nuevo.id,
                    'nombre': nuevo.nombre,
                    'sku': nuevo.sku,
                    'tipo_inventario': 'accesorios',
                    'stock': 0,
                    'costo': float(nuevo.precio_costo),
                    'variantes': []
                }
            })

    except Exception as e:
        db.session.rollback()
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'message': f'Error en base de datos: {str(e)}', 'error': str(e)}), 500


@purchases_bp.route('/guardar', methods=['POST'])
@login_required
def guardar():
    try:
        tipo_inventario = request.form.get('tipo_inventario', 'accesorios')
        provider_id = request.form.get('provider_id')
        provider_id = int(provider_id) if provider_id and provider_id.isdigit() else None
        target_branch_id = _resolve_purchase_branch_id(request.form.get('branch_id'))
        numero_factura = request.form.get('numero_factura', '').strip()
        observaciones = request.form.get('observaciones', '').strip()
        items_json = request.form.get('items_json', '[]')

        items = json.loads(items_json)
        if not items:
            flash('Debes ingresar al menos un producto a la compra.', 'danger')
            return redirect(url_for('purchases_bp.nueva', tipo=tipo_inventario))

        proveedor_obj = Provider.query.get(provider_id) if provider_id else None
        proveedor_nombre = proveedor_obj.nombre if proveedor_obj else None

        total_costo = Decimal('0.00')

        # Crear orden de compra
        compra = PurchaseOrder(
            tipo_inventario=tipo_inventario,
            provider_id=provider_id,
            usuario_id=current_user.id,
            numero_factura=numero_factura,
            observaciones=observaciones,
            total_costo=Decimal('0.00'),
            fecha_compra=obtener_hora_bogota()
        )
        db.session.add(compra)
        db.session.flush()

        descripciones_factura_prov = []

        for it in items:
            prod_id = int(it.get('product_id'))
            var_id = it.get('variant_id')
            var_id = int(var_id) if var_id else None
            cantidad = int(it.get('cantidad', 1))
            costo_unitario = Decimal(str(it.get('costo_unitario', 0)))
            subtotal = costo_unitario * cantidad
            total_costo += subtotal

            producto = Product.query.get(prod_id)
            if not producto:
                continue

            imei = it.get('imei', '').strip() if it.get('imei') else None
            imei2 = it.get('imei2', '').strip() if it.get('imei2') else None

            # Si es celular y seleccionaron un producto existente que ya tenía un IMEI distinto, crear una nueva unidad Product para no sobrescribir el otro IMEI
            if imei and producto.imei and producto.imei.strip().lower() != imei.lower():
                existente_imei = Product.query.filter(
                    (Product.imei == imei) | (Product.sku == imei)
                ).first()
                if existente_imei:
                    producto = existente_imei
                    prod_id = producto.id
                else:
                    nuevo_clon = Product(
                        nombre=producto.nombre,
                        sku=imei,
                        tipo_inventario=producto.tipo_inventario,
                        cantidad_stock=0,
                        precio_costo=costo_unitario if costo_unitario > 0 else producto.precio_costo,
                        precio_minimo=producto.precio_minimo,
                        precio_sugerido=producto.precio_sugerido,
                        imei=imei,
                        imei2=imei2,
                        marca=producto.marca,
                        modelo_celular=producto.modelo_celular,
                        color=producto.color,
                        memoria=producto.memoria,
                        bateria=producto.bateria,
                        estado_celular=producto.estado_celular or 'Nuevo',
                        proveedor=proveedor_nombre or producto.proveedor
                    )
                    db.session.add(nuevo_clon)
                    db.session.flush()
                    producto = nuevo_clon
                    prod_id = producto.id
            else:
                if imei:
                    producto.imei = imei
                if imei2:
                    producto.imei2 = imei2

            if proveedor_nombre:
                producto.proveedor = proveedor_nombre

            # Actualizar stock real en BranchStock y sincronizar Product / ProductVariant
            if var_id:
                variante = ProductVariant.query.get(var_id)
                if variante and costo_unitario > 0:
                    variante.precio_costo = costo_unitario
                b_stock = get_or_create_branch_stock(target_branch_id, prod_id, var_id)
                stock_ant = b_stock.cantidad
                b_stock.cantidad += cantidad
                sync_global_product_stock(prod_id, var_id)
            else:
                if costo_unitario > 0:
                    producto.precio_costo = costo_unitario
                b_stock = get_or_create_branch_stock(target_branch_id, prod_id, None)
                stock_ant = b_stock.cantidad
                b_stock.cantidad += cantidad
                sync_global_product_stock(prod_id, None)

            # Registrar movimiento en Kardex (StockAdjustment)
            ajuste = StockAdjustment(
                product_id=prod_id,
                admin_id=current_user.id,
                branch_id=target_branch_id,
                tipo_movimiento=f'COMPRA #{compra.id}' + (f' ({proveedor_nombre})' if proveedor_nombre else '') + (f' [IMEI: {producto.imei}]' if producto.imei else ''),
                stock_anterior=stock_ant,
                stock_nuevo=b_stock.cantidad
            )
            db.session.add(ajuste)

            # Crear item de compra (guardando siempre el IMEI del item o del producto)
            imei_final = imei or producto.imei
            imei2_final = imei2 or producto.imei2
            item_compra = PurchaseOrderItem(
                purchase_order_id=compra.id,
                product_id=prod_id,
                variant_id=var_id,
                cantidad=cantidad,
                costo_unitario=costo_unitario,
                subtotal=subtotal,
                imei=imei_final,
                imei2=imei2_final
            )
            db.session.add(item_compra)

            desc_item = f"{cantidad}x {producto.nombre}"
            if imei_final:
                desc_item += f" (IMEI: {imei_final})"
            descripciones_factura_prov.append(desc_item)

        compra.total_costo = total_costo

        # Si se seleccionó un proveedor y el costo es > 0, registrar también la factura en la cuenta del proveedor
        if provider_id and total_costo > 0:
            ref_fac = numero_factura or f"COMPRA-{compra.id:04d}"
            factura_prov = ProviderInvoice(
                provider_id=provider_id,
                monto_total=float(total_costo),
                numero_factura=ref_fac,
                descripcion=f"Orden de Compra #{compra.id:04d}: " + ", ".join(descripciones_factura_prov)[:220]
            )
            db.session.add(factura_prov)

        db.session.commit()

        flash(f'Compra #{compra.id:04d} registrada con éxito. El stock y seriales ya están disponibles en el inventario.', 'success')
        return redirect(url_for('purchases_bp.detalle', id=compra.id))

    except Exception as e:
        db.session.rollback()
        flash(f'Error al procesar la compra: {str(e)}', 'danger')
        return redirect(url_for('purchases_bp.nueva', tipo=request.form.get('tipo_inventario', 'accesorios')))
