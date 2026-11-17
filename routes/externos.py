from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify, current_app, send_file
from flask_login import login_required, current_user
from models import db, Product
from decorators import admin_required
from datetime import datetime
import pytz
import os
import pandas as pd
import io
from decimal import Decimal

externos_bp = Blueprint('externos_bp', __name__)

def obtener_hora_bogota():
    return datetime.now(pytz.timezone('America/Bogota')).replace(tzinfo=None)

from sqlalchemy.orm import joinedload

@externos_bp.route('/')
@login_required
def inventario():
    q = request.args.get('q', '').strip()
    page = request.args.get('page', 1, type=int)
    per_page = 20

    base_query = Product.query.options(
        joinedload(Product.detalles_venta),
        joinedload(Product.retoma_origen)
    ).filter(
        Product.tipo_inventario == 'externos',
        ~Product.sku.like('EXTACC-%')
    )

    if q:
        from sqlalchemy import or_
        base_query = base_query.filter(
            or_(
                Product.marca.ilike(f'%{q}%'),
                Product.modelo_celular.ilike(f'%{q}%'),
                Product.imei.ilike(f'%{q}%'),
                Product.imei2.ilike(f'%{q}%'),
                Product.proveedor.ilike(f'%{q}%'),
            )
        )

    paginacion = base_query.order_by(Product.fecha_creacion.desc()).paginate(
        page=page, per_page=per_page, error_out=False
    )

    return render_template('externos/inventario.html',
                           celulares=paginacion.items,
                           paginacion=paginacion,
                           q=q)

@externos_bp.route('/accesorios')
@login_required
def inventario_accesorios():
    q = request.args.get('q', '').strip()
    page = request.args.get('page', 1, type=int)
    per_page = 20

    base_query = Product.query.options(
        joinedload(Product.detalles_venta),
        joinedload(Product.retoma_origen)
    ).filter(
        Product.tipo_inventario == 'externos',
        Product.sku.like('EXTACC-%')
    )

    if q:
        from sqlalchemy import or_
        base_query = base_query.filter(
            or_(
                Product.marca.ilike(f'%{q}%'),
                Product.nombre.ilike(f'%{q}%'),
                Product.proveedor.ilike(f'%{q}%'),
            )
        )

    paginacion = base_query.order_by(Product.fecha_creacion.desc()).paginate(
        page=page, per_page=per_page, error_out=False
    )

    return render_template('externos/inventario_accesorios.html',
                           accesorios=paginacion.items,
                           paginacion=paginacion,
                           q=q)

from sqlalchemy.exc import IntegrityError

@externos_bp.route('/nuevo', methods=['GET', 'POST'])
@login_required
@admin_required
def nuevo_externo():
    if request.method == 'POST':
        marca = request.form.get('marca', '').strip()
        modelo_celular = request.form.get('modelo_celular', '').strip()
        color = request.form.get('color', '').strip()
        bateria = request.form.get('bateria', '').strip()
        memoria = request.form.get('memoria', '').strip()
        imei = request.form.get('imei', '').strip() or None
        imei2 = request.form.get('imei2', '').strip() or None
        proveedor = request.form.get('proveedor', '').strip()
        
        if imei:
            existente = Product.query.filter_by(imei=imei).first()
            if existente:
                flash(f'El IMEI "{imei}" ya se encuentra registrado en el sistema (Producto: {existente.nombre}).', 'danger')
                return render_template('externos/form_externo.html', celular=None)

        precio_costo_str = request.form.get('precio_costo', '0').replace(',', '')
        precio_sugerido_str = request.form.get('precio_sugerido', '0').replace(',', '')
        
        nombre_completo = f"Externo {marca} {modelo_celular} {color} {memoria}".strip()
        sku_base = f"EXT-{datetime.now().strftime('%Y%m%d%H%M%S')}"
        
        precio_sugerido = float(precio_sugerido_str) if precio_sugerido_str else 0.0

        nuevo = Product(
            nombre=nombre_completo,
            sku=sku_base,
            tipo_inventario='externos',
            cantidad_stock=1,
            precio_costo=float(precio_costo_str) if precio_costo_str else 0.0,
            precio_minimo=precio_sugerido, # El minimo toma el sugerido invisiblemente
            precio_sugerido=precio_sugerido,
            marca=marca,
            modelo_celular=modelo_celular,
            color=color,
            bateria=bateria,
            memoria=memoria,
            imei=imei,
            imei2=imei2,
            proveedor=proveedor
        )
        
        try:
            db.session.add(nuevo)
            db.session.commit()
            flash('Celular externo ingresado exitosamente.', 'success')
            return redirect(url_for('externos_bp.inventario'))
            
        except IntegrityError:
            db.session.rollback()
            flash(f'El IMEI "{imei}" ya existe registrado en la base de datos.', 'danger')
        except Exception as e:
            db.session.rollback()
            flash(f'Error al registrar el celular externo: {str(e)}', 'danger')

    return render_template('externos/form_externo.html', celular=None)

@externos_bp.route('/api/nuevo_desde_caja', methods=['POST'])
@login_required
def api_nuevo_desde_caja():
    # AJAX endpoint for POS
    marca = request.form.get('marca', '').strip()
    modelo_celular = request.form.get('modelo_celular', '').strip()
    color = request.form.get('color', '').strip()
    bateria = request.form.get('bateria', '').strip()
    memoria = request.form.get('memoria', '').strip()
    imei = request.form.get('imei', '').strip() or None
    imei2 = request.form.get('imei2', '').strip() or None
    proveedor = request.form.get('proveedor', '').strip()
    
    if imei:
        existente = Product.query.filter_by(imei=imei).first()
        if existente:
            return jsonify({'success': False, 'message': f'El IMEI "{imei}" ya se encuentra registrado en el sistema ({existente.nombre}).'}), 400

    precio_costo_str = request.form.get('precio_costo', '0').replace(',', '')
    precio_sugerido_str = request.form.get('precio_sugerido', '0').replace(',', '')
    
    nombre_completo = f"Externo {marca} {modelo_celular} {color} {memoria}".strip()
    sku_base = f"EXT-{datetime.now().strftime('%Y%m%d%H%M%S')}"
    
    precio_sugerido = float(precio_sugerido_str) if precio_sugerido_str else 0.0

    nuevo = Product(
        nombre=nombre_completo,
        sku=sku_base,
        tipo_inventario='externos',
        cantidad_stock=1,
        precio_costo=float(precio_costo_str) if precio_costo_str else 0.0,
        precio_minimo=precio_sugerido,
        precio_sugerido=precio_sugerido,
        marca=marca,
        modelo_celular=modelo_celular,
        color=color,
        bateria=bateria,
        memoria=memoria,
        imei=imei,
        imei2=imei2,
        proveedor=proveedor
    )
    
    try:
        db.session.add(nuevo)
        db.session.flush()

        target_branch_id = current_user.branch_id if current_user.rol in ['vendedor', 'bodega'] else (session.get('active_branch_id') or 1)
        from services.stock_service import get_or_create_branch_stock, sync_global_product_stock
        bs = get_or_create_branch_stock(int(target_branch_id), nuevo.id, None)
        bs.cantidad = 1
        sync_global_product_stock(nuevo.id, None)

        db.session.commit()
        return jsonify({
            'success': True,
            'product': {
                'id': nuevo.id,
                'sku': nuevo.sku,
                'nombre': nuevo.nombre,
                'precio_sugerido': float(nuevo.precio_sugerido),
                'precio_minimo': float(nuevo.precio_minimo),
                'stock': nuevo.cantidad_stock,
                'es_manual': False
            }
        })
    except IntegrityError:
        db.session.rollback()
        return jsonify({'success': False, 'message': f'El IMEI "{imei}" ya existe en el sistema.'}), 400
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': str(e)}), 500

@externos_bp.route('/api_nuevo_accesorio_caja', methods=['POST'])
@login_required
def api_nuevo_accesorio_caja():
    # AJAX endpoint para accesorios externos desde caja
    nombre_accesorio = request.form.get('nombre_accesorio', '').strip()
    marca = request.form.get('marca', '').strip()
    proveedor = request.form.get('proveedor', '').strip()
    
    precio_costo_str = request.form.get('precio_costo', '0').replace(',', '')
    precio_sugerido_str = request.form.get('precio_sugerido', '0').replace(',', '')
    
    nombre_completo = f"Acc. Externo {marca} {nombre_accesorio}".strip()
    sku_base = f"EXTACC-{datetime.now().strftime('%Y%m%d%H%M%S')}"
    
    precio_sugerido = float(precio_sugerido_str) if precio_sugerido_str else 0.0

    nuevo = Product(
        nombre=nombre_completo,
        sku=sku_base,
        tipo_inventario='externos',
        cantidad_stock=1,
        precio_costo=float(precio_costo_str) if precio_costo_str else 0.0,
        precio_minimo=precio_sugerido,
        precio_sugerido=precio_sugerido,
        marca=marca,
        proveedor=proveedor
    )
    
    try:
        db.session.add(nuevo)
        db.session.flush()

        target_branch_id = current_user.branch_id if current_user.rol in ['vendedor', 'bodega'] else (session.get('active_branch_id') or 1)
        from services.stock_service import get_or_create_branch_stock, sync_global_product_stock
        bs = get_or_create_branch_stock(int(target_branch_id), nuevo.id, None)
        bs.cantidad = 1
        sync_global_product_stock(nuevo.id, None)

        db.session.commit()
        return jsonify({
            'success': True,
            'product': {
                'id': nuevo.id,
                'sku': nuevo.sku,
                'nombre': nuevo.nombre,
                'precio_sugerido': float(nuevo.precio_sugerido),
                'precio_minimo': float(nuevo.precio_minimo),
                'stock': nuevo.cantidad_stock,
                'es_manual': False
            }
        })
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': str(e)}), 500


@externos_bp.route('/editar/<int:id>', methods=['GET', 'POST'])
@login_required
@admin_required
def editar_externo(id):
    celular = Product.query.get_or_404(id)
    if celular.tipo_inventario != 'externos':
        flash('El producto seleccionado no es un externo.', 'danger')
        return redirect(url_for('externos_bp.inventario'))
        
    if request.method == 'POST':
        celular.marca = request.form.get('marca', '').strip()
        celular.modelo_celular = request.form.get('modelo_celular', '').strip()
        celular.color = request.form.get('color', '').strip()
        celular.bateria = request.form.get('bateria', '').strip()
        celular.memoria = request.form.get('memoria', '').strip()
        celular.imei = request.form.get('imei', '').strip()
        celular.imei2 = request.form.get('imei2', '').strip()
        celular.proveedor = request.form.get('proveedor', '').strip()
        
        precio_costo_str = request.form.get('precio_costo', str(celular.precio_costo)).replace(',', '')
        precio_sugerido_str = request.form.get('precio_sugerido', str(celular.precio_sugerido)).replace(',', '')
        
        celular.precio_costo = float(precio_costo_str) if precio_costo_str else 0.0
        precio_sugerido = float(precio_sugerido_str) if precio_sugerido_str else 0.0
        celular.precio_sugerido = precio_sugerido
        celular.precio_minimo = precio_sugerido # Reflejado silenciosamente
        
        celular.nombre = f"Externo {celular.marca} {celular.modelo_celular} {celular.color} {celular.memoria}".strip()

        try:
            db.session.commit()
            flash('Celular externo actualizado correctamente.', 'success')
            return redirect(url_for('externos_bp.inventario'))
        except Exception as e:
            db.session.rollback()
            flash(f'Error al actualizar: {str(e)}', 'danger')
            
    return render_template('externos/form_externo.html', celular=celular)

@externos_bp.route('/eliminar/<int:id>', methods=['POST'])
@login_required
@admin_required
def eliminar_externo(id):
    celular = Product.query.get_or_404(id)
    if celular.tipo_inventario != 'externos':
        flash('El producto seleccionado no es externo.', 'danger')
        return redirect(url_for('externos_bp.inventario'))
        
    try:
        db.session.delete(celular)
        db.session.commit()
        flash('Celular externo eliminado del sistema.', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Error al eliminar el celular: {str(e)}', 'danger')
        
    return redirect(url_for('externos_bp.inventario'))


@externos_bp.route('/enviar_inventario/<int:id>', methods=['POST'])
@login_required
@admin_required
def enviar_inventario(id):
    celular = Product.query.get_or_404(id)
    if celular.tipo_inventario != 'externos':
        flash('El producto seleccionado no es externo.', 'danger')
        return redirect(url_for('externos_bp.inventario'))
        
    try:
        # Los productos externos ya fueron vendidos al pedirse; pasan al inventario general como Vendidos (stock 0)
        celular.tipo_inventario = 'celulares'
        if not celular.sku.endswith('-INV'):
            celular.sku = celular.sku + '-INV'
        celular.estado_celular = 'Vendido'
        celular.cantidad_stock = 0
            
        db.session.commit()
        flash('El producto externo ha sido pasado al Inventario de Celulares en la sección de Vendidos.', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Error al mover el producto: {str(e)}', 'danger')
        
    return redirect(url_for('externos_bp.inventario'))


@externos_bp.route('/enviar_inventario_masivo', methods=['POST'])
@login_required
@admin_required
def enviar_inventario_masivo():
    producto_ids = request.form.getlist('producto_ids')
    if not producto_ids:
        flash('No seleccionaste ningún producto para enviar al inventario.', 'warning')
        return redirect(url_for('externos_bp.inventario'))
        
    exitosos = 0
    errores = 0
    try:
        for p_id in producto_ids:
            try:
                c_id = int(p_id)
                celular = Product.query.get(c_id)
                if not celular or celular.tipo_inventario != 'externos' or celular.estado_celular == 'Enviado':
                    continue
                
                # Los productos externos ya fueron vendidos; pasan a celulares como Vendidos (stock 0)
                celular.tipo_inventario = 'celulares'
                if not celular.sku.endswith('-INV'):
                    celular.sku = celular.sku + '-INV'
                celular.estado_celular = 'Vendido'
                celular.cantidad_stock = 0
                
                exitosos += 1
            except Exception:
                errores += 1
                
        db.session.commit()
        if exitosos > 0:
            flash(f'¡Éxito! Se pasaron {exitosos} productos externos al inventario de celulares como Vendidos.', 'success')
        if errores > 0:
            flash(f'No se pudieron procesar {errores} producto(s).', 'warning')
    except Exception as e:
        db.session.rollback()
        flash(f'Error al procesar el envío masivo: {str(e)}', 'danger')
        
    return redirect(url_for('externos_bp.inventario'))


@externos_bp.route('/descargar_plantilla')
@login_required
@admin_required
def descargar_plantilla():
    columnas = ['MARCA', 'REFERENCIA', 'CAPACIDAD', 'BATERIA', 'COLOR', 'IMEI', 'IMEI2', 'PROVEEDOR', 'COSTO', 'PRECIO SUGERIDO']
    df = pd.DataFrame(columns=columnas)
    
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        df.to_excel(writer, index=False, sheet_name='Plantilla Externos')
    
    output.seek(0)
    return send_file(output, download_name='plantilla_externos.xlsx', as_attachment=True, mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')

@externos_bp.route('/importar_excel', methods=['POST'])
@login_required
@admin_required
def importar_excel():
    if 'archivo_excel' not in request.files:
        flash('No se subió ningún archivo.', 'danger')
        return redirect(url_for('externos_bp.inventario'))
        
    file = request.files['archivo_excel']
    if file.filename == '':
        flash('El archivo está vacío.', 'danger')
        return redirect(url_for('externos_bp.inventario'))
        
    if not file.filename.endswith(('.xlsx', '.xls')):
        flash('Formato de archivo no válido. Debe ser Excel (.xlsx o .xls).', 'danger')
        return redirect(url_for('externos_bp.inventario'))
        
    try:
        df = pd.read_excel(file)
        df.columns = df.columns.str.strip().str.upper()
        
        columnas_esperadas = ['MARCA', 'REFERENCIA', 'CAPACIDAD', 'BATERIA', 'COLOR', 'IMEI', 'IMEI2', 'PROVEEDOR', 'COSTO', 'PRECIO SUGERIDO']
        
        for col in columnas_esperadas:
            if col not in df.columns:
                flash(f'El archivo no tiene la columna requerida: {col}', 'danger')
                return redirect(url_for('externos_bp.inventario'))
                
        df = df.fillna('')
        
        exitosos = 0
        omitidos = 0
        
        for index, row in df.iterrows():
            imei1 = str(row['IMEI']).strip()
            if not imei1:
                continue
                
            if imei1.endswith('.0'):
                imei1 = imei1[:-2]
                
            existente = Product.query.filter(Product.imei == imei1, Product.cantidad_stock > 0).first()
            if existente:
                omitidos += 1
                continue
                
            marca = str(row['MARCA']).strip()
            referencia = str(row['REFERENCIA']).strip()
            memoria = str(row['CAPACIDAD']).strip()
            bateria_raw = str(row['BATERIA']).strip()
            bateria = bateria_raw
            if bateria_raw:
                if not bateria_raw.endswith('%'):
                    try:
                        val = float(bateria_raw)
                        if val <= 1.0 and val > 0:
                            bateria = f"{int(val * 100)}%"
                        else:
                            bateria = f"{int(val)}%"
                    except ValueError:
                        pass
            color = str(row['COLOR']).strip()
            
            imei2 = str(row['IMEI2']).strip()
            if imei2.endswith('.0'):
                imei2 = imei2[:-2]
                
            proveedor = str(row['PROVEEDOR']).strip()
            
            # Limpiar precios de simbolos $ o comas
            def limpiar_precio(val):
                s = str(val).replace('$', '').replace(',', '').strip()
                try:
                    return float(s) if s else 0.0
                except:
                    return 0.0

            costo = limpiar_precio(row['COSTO'])
            sugerido = limpiar_precio(row['PRECIO SUGERIDO'])
            
            nombre_completo = f"Externo {marca} {referencia} {color} {memoria}".strip()
            sku_base = f"EXT-{datetime.now().strftime('%Y%m%d%H%M%S')}-{index}"
            
            nuevo_cel = Product(
                nombre=nombre_completo,
                sku=sku_base,
                tipo_inventario='externos',
                cantidad_stock=1,
                precio_costo=costo,
                precio_minimo=sugerido,
                precio_sugerido=sugerido,
                marca=marca,
                modelo_celular=referencia,
                color=color,
                bateria=bateria,
                memoria=memoria,
                imei=imei1,
                imei2=imei2,
                proveedor=proveedor
            )
            
            db.session.add(nuevo_cel)
            exitosos += 1
            
        db.session.commit()
        
        if omitidos > 0:
            flash(f'Carga completada: {exitosos} externos subidos. Se omitieron {omitidos} porque el IMEI ya existía en el sistema.', 'warning')
        else:
            flash(f'Carga Masiva completada: {exitosos} externos subidos exitosamente.', 'success')
            
        return redirect(url_for('externos_bp.inventario'))
        
    except Exception as e:
        db.session.rollback()
        flash(f'Ocurrió un error al procesar el archivo: {str(e)}', 'danger')
        return redirect(url_for('externos_bp.inventario'))
