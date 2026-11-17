import json
from decimal import Decimal, InvalidOperation
from datetime import datetime
import pytz
from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify
from flask_login import login_required, current_user
from models import db, Product, ProductVariant, Provider, PurchaseOrder, PurchaseOrderItem, obtener_hora_bogota
from decorators import admin_required

purchases_bp = Blueprint('purchases_bp', __name__)

@purchases_bp.route('/')
@login_required
@admin_required
def index():
    compras = PurchaseOrder.query.order_by(PurchaseOrder.fecha_compra.desc()).all()
    proveedores = Provider.query.order_by(Provider.nombre.asc()).all()
    return render_template('compras/index.html', compras=compras, proveedores=proveedores)

@purchases_bp.route('/nueva')
@login_required
@admin_required
def nueva():
    tipo = request.args.get('tipo', 'accesorios')
    proveedores = Provider.query.order_by(Provider.nombre.asc()).all()
    return render_template('compras/nueva.html', tipo=tipo, proveedores=proveedores)

@purchases_bp.route('/detalle/<int:id>')
@login_required
@admin_required
def detalle(id):
    compra = PurchaseOrder.query.get_or_404(id)
    return render_template('compras/detalle.html', compra=compra)

@purchases_bp.route('/api/buscar_productos')
@login_required
@admin_required
def api_buscar_productos():
    tipo = request.args.get('tipo', 'accesorios')
    q = request.args.get('q', '').strip()

    query = Product.query
    if tipo == 'celulares':
        query = query.filter(Product.tipo_inventario == 'celulares')
    else:
        query = query.filter(Product.tipo_inventario.in_(['tienda', 'bodega', 'accesorios']))

    if q:
        query = query.filter(
            (Product.nombre.ilike(f'%{q}%')) |
            (Product.sku.ilike(f'%{q}%')) |
            (Product.imei.ilike(f'%{q}%')) |
            (Product.imei2.ilike(f'%{q}%')) |
            (Product.marca.ilike(f'%{q}%')) |
            (Product.modelo_celular.ilike(f'%{q}%'))
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
@admin_required
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
@admin_required
def guardar():
    try:
        tipo_inventario = request.form.get('tipo_inventario', 'accesorios')
        provider_id = request.form.get('provider_id')
        provider_id = int(provider_id) if provider_id and provider_id.isdigit() else None
        numero_factura = request.form.get('numero_factura', '').strip()
        observaciones = request.form.get('observaciones', '').strip()
        items_json = request.form.get('items_json', '[]')

        items = json.loads(items_json)
        if not items:
            flash('Debes ingresar al menos un producto a la compra.', 'danger')
            return redirect(url_for('purchases_bp.nueva', tipo=tipo_inventario))

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

            # Actualizar stock y costos en producto/variante
            if var_id:
                variante = ProductVariant.query.get(var_id)
                if variante:
                    variante.cantidad_stock += cantidad
                    variante.precio_costo = costo_unitario
            else:
                producto.cantidad_stock += cantidad
                if costo_unitario > 0:
                    producto.precio_costo = costo_unitario

            # Si es celular y se provee nuevo IMEI
            imei = it.get('imei', '').strip() if it.get('imei') else None
            imei2 = it.get('imei2', '').strip() if it.get('imei2') else None
            if imei and not producto.imei:
                producto.imei = imei
            if imei2 and not producto.imei2:
                producto.imei2 = imei2

            # Crear item de compra
            item_compra = PurchaseOrderItem(
                purchase_order_id=compra.id,
                product_id=prod_id,
                variant_id=var_id,
                cantidad=cantidad,
                costo_unitario=costo_unitario,
                subtotal=subtotal,
                imei=imei,
                imei2=imei2
            )
            db.session.add(item_compra)

        compra.total_costo = total_costo
        db.session.commit()

        flash(f'Compra #{compra.id} registrada con éxito. Se incrementó el inventario correspondiente.', 'success')
        return redirect(url_for('purchases_bp.detalle', id=compra.id))

    except Exception as e:
        db.session.rollback()
        flash(f'Error al procesar la compra: {str(e)}', 'danger')
        return redirect(url_for('purchases_bp.nueva', tipo=request.form.get('tipo_inventario', 'accesorios')))
