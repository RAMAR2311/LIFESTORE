from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify, current_app, send_file, session
from flask_login import login_required, current_user
from sqlalchemy import or_
from models import db, Product, Sale, SaleDetail, SalePayment, ProductVariant, ArqueoCaja, Maneo, StockAdjustment, Branch, BranchStock
from services.stock_service import get_or_create_branch_stock, sync_global_product_stock
from decorators import admin_required
from datetime import datetime
import pytz
import os
from werkzeug.utils import secure_filename
from decimal import Decimal

celulares_bp = Blueprint('celulares_bp', __name__)

def _resolve_celular_branch_id(form_branch_id=None):
    if current_user.rol == 'bodega':
        if current_user.branch_id:
            return current_user.branch_id
        bodega_b = Branch.query.filter_by(tipo='bodega', activa=True).first()
        if bodega_b:
            return bodega_b.id
    elif current_user.rol == 'vendedor':
        if current_user.branch_id:
            return current_user.branch_id

    if form_branch_id:
        return int(form_branch_id)
    if session.get('active_branch_id'):
        return int(session['active_branch_id'])

    default_b = Branch.query.filter_by(activa=True).first()
    return default_b.id if default_b else 1

def obtener_hora_bogota():
    return datetime.now(pytz.timezone('America/Bogota')).replace(tzinfo=None)

@celulares_bp.route('/inventario')
@login_required
def inventario():
    q = request.args.get('q', '').strip()
    # Permitir filtrar por múltiples referencias
    referencias_seleccionadas = request.args.getlist('referencias')
    # Soporte por si viene una sola referencia como 'referencia' o separada por comas
    if not referencias_seleccionadas and request.args.get('referencia'):
        referencias_seleccionadas = [r.strip() for r in request.args.get('referencia').split(',') if r.strip()]
    estado = request.args.get('estado', 'activos').strip()
    page = request.args.get('page', 1, type=int)
    per_page = 20

    # Query for all celulares to calculate KPIs
    todos_celulares = Product.query.filter_by(tipo_inventario='celulares').all()
    
    stock_activo = 0
    costo_total = 0.0
    ventas_estimadas = 0.0
    
    for c in todos_celulares:
        if c.cantidad_stock > 0:
            stock_activo += c.cantidad_stock
            costo_total += float(c.precio_costo) * c.cantidad_stock
            ventas_estimadas += float(c.precio_sugerido) * c.cantidad_stock

    # Obtener lista única y ordenada de referencias para el filtro desplegable
    referencias_query = db.session.query(Product.modelo_celular).filter(
        Product.tipo_inventario == 'celulares',
        Product.modelo_celular != None,
        Product.modelo_celular != ''
    ).distinct().order_by(Product.modelo_celular.asc()).all()
    referencias_disponibles = [r[0] for r in referencias_query if r[0]]

    # Celulares actualmente prestados a locales vecinos (Maneo pendiente)
    celulares_en_maneo = Product.query.filter(
        Product.tipo_inventario == 'celulares',
        Product.maneos.any(Maneo.estado == 'PENDIENTE')
    ).count()

    from models import TechnicalService
    celulares_en_soporte = Product.query.filter(
        Product.tipo_inventario == 'celulares',
        Product.servicios_tecnicos.any(TechnicalService.estado.in_(['EN_REVISION', 'EN_REPARACION']))
    ).count()

    from models import TechnicalService
    celulares_en_soporte = Product.query.filter(
        Product.tipo_inventario == 'celulares',
        Product.servicios_tecnicos.any(TechnicalService.estado.in_(['EN_REVISION', 'EN_REPARACION']))
    ).count()

    active_b_id = None
    if current_user.rol == 'admin':
        active_b_id = session.get('active_branch_id')
    elif current_user.rol in ['vendedor', 'bodega', 'vendedor_bodega']:
        active_b_id = current_user.branch_id

    from sqlalchemy.orm import selectinload, joinedload

    # Base query for table with eager loading of ventas and maneos
    base_query = Product.query.options(
        selectinload(Product.detalles_venta).joinedload(SaleDetail.venta),
        selectinload(Product.maneos),
        selectinload(Product.servicios_tecnicos).joinedload(TechnicalService.technician),
        selectinload(Product.branch_stocks).joinedload(BranchStock.branch)
    ).filter_by(tipo_inventario='celulares')

    # Rol vendedor: aislamiento estricto por sucursal
    if current_user.rol == 'vendedor':
        if not active_b_id:
            default_b = Branch.query.filter_by(tipo='tienda', activa=True).first()
            active_b_id = default_b.id if default_b else 1
        
        base_query = base_query.join(
            BranchStock,
            (BranchStock.product_id == Product.id) & (BranchStock.branch_id == active_b_id)
        ).filter(BranchStock.cantidad > 0)
    elif current_user.rol == 'admin' and active_b_id is not None:
        # Si el admin filtró una sucursal específica
        base_query = base_query.join(
            BranchStock,
            (BranchStock.product_id == Product.id) & (BranchStock.branch_id == active_b_id)
        ).filter(BranchStock.cantidad > 0)

    if estado == 'activos':
        base_query = base_query.filter(Product.cantidad_stock > 0)
    elif estado == 'maneo':
        base_query = base_query.filter(Product.maneos.any(Maneo.estado == 'PENDIENTE'))
    elif estado == 'soporte':
        base_query = base_query.filter(Product.servicios_tecnicos.any(TechnicalService.estado.in_(['EN_REVISION', 'EN_REPARACION'])))
    elif estado == 'vendidos':
        # Vendidos reales: sin stock y que no estén en préstamo de maneo ni en soporte
        base_query = base_query.filter(
            Product.cantidad_stock == 0,
            ~Product.maneos.any(Maneo.estado == 'PENDIENTE'),
            ~Product.servicios_tecnicos.any(TechnicalService.estado.in_(['EN_REVISION', 'EN_REPARACION']))
        )

    if referencias_seleccionadas:
        base_query = base_query.filter(Product.modelo_celular.in_(referencias_seleccionadas))

    if q:
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

    # Mapa de ubicación actual (sucursal con cantidad > 0) para cada celular
    celular_ubicaciones = {}
    for c in paginacion.items:
        # Buscar en sus branch_stocks la que tenga cantidad > 0
        ubicacion = None
        for bs in c.branch_stocks:
            if bs.cantidad > 0 and bs.branch:
                ubicacion = {
                    'nombre': bs.branch.nombre,
                    'codigo': bs.branch.codigo,
                    'tipo': bs.branch.tipo
                }
                break
        celular_ubicaciones[c.id] = ubicacion

    from models import Technician
    tecnicos_disponibles = Technician.query.filter_by(activo=True).order_by(Technician.nombre.asc()).all()
    sucursales_activas = Branch.query.filter_by(activa=True).order_by(Branch.tipo.desc(), Branch.nombre.asc()).all()

    return render_template('celulares/inventario.html',
                           tecnicos_disponibles=tecnicos_disponibles, 
                           celulares=paginacion.items,
                           paginacion=paginacion,
                           q=q,
                           referencias_seleccionadas=referencias_seleccionadas,
                           referencia=referencias_seleccionadas[0] if len(referencias_seleccionadas) == 1 else '',
                           referencias_disponibles=referencias_disponibles,
                           estado=estado,
                           stock_activo=stock_activo,
                           costo_total=costo_total,
                           ventas_estimadas=ventas_estimadas,
                           celulares_en_maneo=celulares_en_maneo,
                           celular_ubicaciones=celular_ubicaciones,
                           sucursales_activas=sucursales_activas,
                           active_b_id=active_b_id)

@celulares_bp.route('/prestar/<int:id>', methods=['POST'])
@login_required
def prestar_celular(id):
    celular = Product.query.get_or_404(id)
    if celular.tipo_inventario != 'celulares' and not celular.imei:
        flash('El producto seleccionado no es un celular válido.', 'danger')
        return redirect(url_for('celulares_bp.inventario'))

    if celular.cantidad_stock <= 0:
        flash(f'El celular "{celular.nombre}" no tiene unidades disponibles en stock para prestar.', 'danger')
        return redirect(url_for('celulares_bp.inventario'))

    local_vecino = request.form.get('local_vecino', '').strip()
    if not local_vecino:
        flash('Debes indicar el nombre del local vecino o persona que recibe el celular.', 'danger')
        return redirect(url_for('celulares_bp.inventario'))

    try:
        stock_anterior = celular.cantidad_stock
        celular.cantidad_stock -= 1

        nuevo_maneo = Maneo(
            product_id=celular.id,
            local_vecino=local_vecino,
            cantidad=1,
            estado='PENDIENTE'
        )
        db.session.add(nuevo_maneo)

        ajuste = StockAdjustment(
            product_id=celular.id,
            admin_id=current_user.id,
            tipo_movimiento=f'Préstamo (Maneo) a {local_vecino} [IMEI: {celular.imei or celular.sku}]',
            stock_anterior=stock_anterior,
            stock_nuevo=celular.cantidad_stock
        )
        db.session.add(ajuste)

        db.session.commit()
        flash(f'Celular {celular.nombre} (IMEI: {celular.imei}) entregado como préstamo a "{local_vecino}".', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Error al registrar el préstamo del celular: {str(e)}', 'danger')

    return redirect(url_for('celulares_bp.inventario', estado='maneo'))


from sqlalchemy.exc import IntegrityError

@celulares_bp.route('/nuevo', methods=['GET', 'POST'])
@login_required
@admin_required
def nuevo_celular():
    if request.method == 'POST':
        marca = request.form.get('marca', '').strip()
        modelo_celular = request.form.get('modelo_celular', '').strip()
        color = request.form.get('color', '').strip()
        bateria = request.form.get('bateria', '').strip()
        memoria = request.form.get('memoria', '').strip()
        imei = request.form.get('imei', '').strip() or None
        imei2 = request.form.get('imei2', '').strip() or None
        proveedor = request.form.get('proveedor', '').strip()
        inventario = request.form.get('inventario', '').strip()

        if imei:
            existente = Product.query.filter_by(imei=imei).first()
            if existente:
                flash(f'El IMEI "{imei}" ya se encuentra registrado en el sistema (Producto: {existente.nombre}). No se pueden duplicar IMEIs.', 'danger')
                return render_template('celulares/form_celular.html', celular=None)
        
        precio_costo_str = request.form.get('precio_costo', '0').replace(',', '')
        precio_sugerido_str = request.form.get('precio_sugerido', '0').replace(',', '')
        precio_minimo_str = request.form.get('precio_minimo', '0').replace(',', '')
        
        tipo_dispositivo = request.form.get('tipo_dispositivo', 'Celular').strip()
        if tipo_dispositivo and tipo_dispositivo != 'Otro':
            nombre_completo = f"{tipo_dispositivo} {marca} {modelo_celular} {color} {memoria}".strip()
        else:
            nombre_completo = f"{marca} {modelo_celular} {color} {memoria}".strip()
            
        sku_base = f"CEL-{datetime.now().strftime('%Y%m%d%H%M%S')}"

        imagen_filename = None
        if 'imagen' in request.files:
            file = request.files['imagen']
            if file and file.filename != '':
                filename = secure_filename(file.filename)
                filename = f"{datetime.now().strftime('%Y%m%d%H%M%S')}_{filename}"
                upload_folder = current_app.config['UPLOAD_FOLDER']
                if not os.path.exists(upload_folder):
                    os.makedirs(upload_folder)
                file.save(os.path.join(upload_folder, filename))
                imagen_filename = filename
        
        nuevo = Product(
            nombre=nombre_completo,
            sku=sku_base,
            tipo_inventario='celulares',
            cantidad_stock=1, # Siempre 1 porque es un registro único
            precio_costo=float(precio_costo_str) if precio_costo_str else 0.0,
            precio_minimo=float(precio_minimo_str) if precio_minimo_str else 0.0,
            precio_sugerido=float(precio_sugerido_str) if precio_sugerido_str else 0.0,
            marca=marca,
            modelo_celular=modelo_celular,
            color=color,
            bateria=bateria,
            memoria=memoria,
            imei=imei,
            imei2=imei2,
            proveedor=proveedor,
            inventario=inventario,
            imagen=imagen_filename
        )
        
        target_branch_id = _resolve_celular_branch_id(request.form.get('branch_id'))

        try:
            db.session.add(nuevo)
            db.session.flush()

            # Asignar a la sucursal seleccionada
            b_stock = get_or_create_branch_stock(target_branch_id, nuevo.id, None)
            b_stock.cantidad = 1
            sync_global_product_stock(nuevo.id, None)

            ajuste = StockAdjustment(
                product_id=nuevo.id,
                admin_id=current_user.id,
                branch_id=target_branch_id,
                tipo_movimiento='Ingreso Dispositivo Celular',
                stock_anterior=0,
                stock_nuevo=1
            )
            db.session.add(ajuste)
            db.session.commit()
            flash(f'{tipo_dispositivo} ingresado al inventario exitosamente.', 'success')
            return redirect(url_for('celulares_bp.inventario'))
            
        except IntegrityError:
            db.session.rollback()
            flash(f'El IMEI "{imei}" ya existe registrado en la base de datos.', 'danger')
        except Exception as e:
            db.session.rollback()
            flash(f'Error al registrar el dispositivo: {str(e)}', 'danger')

    sucursales_activas = Branch.query.order_by(Branch.tipo.desc(), Branch.nombre.asc()).all()
    default_branch_id = _resolve_celular_branch_id()
    return render_template('celulares/form_celular.html', celular=None, sucursales=sucursales_activas, default_branch_id=default_branch_id)

@celulares_bp.route('/editar/<int:id>', methods=['GET', 'POST'])
@login_required
@admin_required
def editar_celular(id):
    celular = Product.query.get_or_404(id)
    if celular.tipo_inventario != 'celulares':
        flash('El producto seleccionado no pertenece a este inventario.', 'danger')
        return redirect(url_for('celulares_bp.inventario'))
        
    if request.method == 'POST':
        imei_val = request.form.get('imei', '').strip() or None
        imei2_val = request.form.get('imei2', '').strip() or None

        if imei_val:
            existente = Product.query.filter(Product.imei == imei_val, Product.id != id).first()
            if existente:
                flash(f'El IMEI "{imei_val}" ya pertenece a otro celular registrado ({existente.nombre}).', 'danger')
                sucursales_activas = Branch.query.order_by(Branch.tipo.desc(), Branch.nombre.asc()).all()
                current_b_id = None
                for bs in celular.branch_stocks:
                    if bs.cantidad > 0:
                        current_b_id = bs.branch_id
                        break
                if not current_b_id and sucursales_activas:
                    current_b_id = sucursales_activas[0].id
                return render_template('celulares/form_celular.html', celular=celular, sucursales=sucursales_activas, default_branch_id=current_b_id)

        celular.marca = request.form.get('marca', '').strip()
        celular.modelo_celular = request.form.get('modelo_celular', '').strip()
        celular.color = request.form.get('color', '').strip()
        celular.bateria = request.form.get('bateria', '').strip()
        celular.memoria = request.form.get('memoria', '').strip()
        celular.imei = imei_val
        celular.imei2 = imei2_val
        celular.proveedor = request.form.get('proveedor', '').strip()
        celular.inventario = request.form.get('inventario', '').strip()
        
        tipo_dispositivo = request.form.get('tipo_dispositivo', 'Celular').strip()
        if tipo_dispositivo and tipo_dispositivo != 'Otro':
            celular.nombre = f"{tipo_dispositivo} {celular.marca} {celular.modelo_celular} {celular.color} {celular.memoria}".strip()
        else:
            celular.nombre = f"{celular.marca} {celular.modelo_celular} {celular.color} {celular.memoria}".strip()
            
        precio_costo_str = request.form.get('precio_costo', '0').replace(',', '')
        precio_sugerido_str = request.form.get('precio_sugerido', '0').replace(',', '')
        precio_minimo_str = request.form.get('precio_minimo', '0').replace(',', '')
        
        celular.precio_costo = float(precio_costo_str) if precio_costo_str else 0.0
        celular.precio_minimo = float(precio_minimo_str) if precio_minimo_str else 0.0
        celular.precio_sugerido = float(precio_sugerido_str) if precio_sugerido_str else 0.0
        
        if 'imagen' in request.files:
            file = request.files['imagen']
            if file and file.filename != '':
                filename = secure_filename(file.filename)
                filename = f"{datetime.now().strftime('%Y%m%d%H%M%S')}_{filename}"
                upload_folder = current_app.config['UPLOAD_FOLDER']
                if not os.path.exists(upload_folder):
                    os.makedirs(upload_folder)
                file.save(os.path.join(upload_folder, filename))
                celular.imagen = filename
            
        # Reubicación / Asignación de Sucursal o Bodega
        nueva_branch_id = request.form.get('branch_id')
        if nueva_branch_id:
            try:
                target_b_id = int(nueva_branch_id)
                # Reasignar stock: poner en 0 en otras sedes y 1 en la sede destino
                for bs in celular.branch_stocks:
                    if bs.branch_id == target_b_id:
                        bs.cantidad = 1
                    else:
                        bs.cantidad = 0
                # Si no existía el registro de branch_stock para esa sede, crearlo
                b_stock = get_or_create_branch_stock(target_b_id, celular.id, None)
                b_stock.cantidad = 1
                sync_global_product_stock(celular.id, None)
            except Exception as e_stock:
                current_app.logger.warning(f"Error reasignando sucursal a celular {celular.id}: {e_stock}")

        try:
            db.session.commit()
            flash('Celular actualizado exitosamente.', 'success')
            return redirect(url_for('celulares_bp.inventario'))
        except IntegrityError:
            db.session.rollback()
            flash(f'El IMEI "{imei_val}" ya pertenece a otro celular registrado.', 'danger')
        except Exception as e:
            db.session.rollback()
            flash(f'Error al actualizar: {str(e)}', 'danger')
            
    sucursales_activas = Branch.query.order_by(Branch.tipo.desc(), Branch.nombre.asc()).all()
    # Identificar la sucursal actual del equipo
    current_b_id = None
    for bs in celular.branch_stocks:
        if bs.cantidad > 0:
            current_b_id = bs.branch_id
            break
    if not current_b_id and sucursales_activas:
        current_b_id = sucursales_activas[0].id

    return render_template('celulares/form_celular.html', celular=celular, sucursales=sucursales_activas, default_branch_id=current_b_id)

@celulares_bp.route('/eliminar/<int:id>', methods=['POST'])
@login_required
@admin_required
def eliminar_celular(id):
    celular = Product.query.get_or_404(id)
    if celular.tipo_inventario != 'celulares':
        flash('No es un celular', 'danger')
        return redirect(url_for('celulares_bp.inventario'))
        
    if celular.detalles_venta:
        flash('No se puede eliminar porque ya tiene ventas asociadas.', 'danger')
        return redirect(url_for('celulares_bp.inventario'))
        
    
    try:
        db.session.delete(celular)
        db.session.commit()
        flash('Modelo de celular eliminado exitosamente.', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Error al eliminar el modelo: {str(e)}', 'danger')
        
    return redirect(url_for('celulares_bp.inventario'))

@celulares_bp.route('/api/referencias-modelos', methods=['GET'])
@login_required
def api_referencias_modelos():
    """Devuelve las referencias de celulares con conteo de equipos activos y precios promedio."""
    modelos = db.session.query(
        Product.modelo_celular,
        db.func.count(Product.id).label('total'),
        db.func.min(Product.precio_minimo).label('min_p_minimo'),
        db.func.max(Product.precio_minimo).label('max_p_minimo'),
        db.func.min(Product.precio_sugerido).label('min_p_sugerido'),
        db.func.max(Product.precio_sugerido).label('max_p_sugerido'),
        db.func.min(Product.precio_costo).label('min_p_costo'),
        db.func.max(Product.precio_costo).label('max_p_costo')
    ).filter(
        Product.tipo_inventario == 'celulares',
        Product.modelo_celular != None,
        Product.modelo_celular != '',
        Product.cantidad_stock > 0
    ).group_by(Product.modelo_celular).order_by(Product.modelo_celular.asc()).all()

    data = []
    for m in modelos:
        data.append({
            'modelo': m.modelo_celular,
            'cantidad': m.total,
            'precio_minimo': float(m.max_p_minimo or 0),
            'precio_sugerido': float(m.max_p_sugerido or 0),
            'precio_costo': float(m.max_p_costo or 0)
        })
    return jsonify({'success': True, 'modelos': data})

@celulares_bp.route('/editar_precios_masivo', methods=['POST'])
@login_required
@admin_required
def editar_precios_masivo():
    """Actualiza masivamente los precios (costo, mínimo y sugerido) de una referencia seleccionada."""
    modelo_celular = request.form.get('modelo_celular', '').strip()
    aplicar_costo = request.form.get('aplicar_costo') == 'on'
    aplicar_minimo = request.form.get('aplicar_minimo') == 'on'
    aplicar_sugerido = request.form.get('aplicar_sugerido') == 'on'

    costo_str = request.form.get('nuevo_precio_costo', '').replace('$', '').replace('.', '').replace(',', '').strip()
    minimo_str = request.form.get('nuevo_precio_minimo', '').replace('$', '').replace('.', '').replace(',', '').strip()
    sugerido_str = request.form.get('nuevo_precio_sugerido', '').replace('$', '').replace('.', '').replace(',', '').strip()

    if not modelo_celular:
        flash('Debe seleccionar una referencia o modelo.', 'warning')
        return redirect(url_for('celulares_bp.inventario'))

    if not (aplicar_costo or aplicar_minimo or aplicar_sugerido):
        flash('Debe marcar al menos un precio para actualizar (Costo, Mínimo o Sugerido).', 'warning')
        return redirect(url_for('celulares_bp.inventario'))

    # Buscar celulares con ese modelo
    celulares = Product.query.filter(
        Product.tipo_inventario == 'celulares',
        Product.modelo_celular == modelo_celular,
        Product.cantidad_stock > 0
    ).all()

    if not celulares:
        flash(f'No se encontraron celulares activos de la referencia "{modelo_celular}".', 'info')
        return redirect(url_for('celulares_bp.inventario'))

    count = 0
    for cel in celulares:
        if aplicar_costo and costo_str:
            cel.precio_costo = float(costo_str)
        if aplicar_minimo and minimo_str:
            cel.precio_minimo = float(minimo_str)
        if aplicar_sugerido and sugerido_str:
            cel.precio_sugerido = float(sugerido_str)
        count += 1

    db.session.commit()

    from models import AuditLog
    detalles_cambio = f"Ref: {modelo_celular} | Total: {count} equipos | "
    if aplicar_sugerido and sugerido_str: detalles_cambio += f"Sugerido: ${sugerido_str} "
    if aplicar_minimo and minimo_str: detalles_cambio += f"Minimo: ${minimo_str} "
    if aplicar_costo and costo_str: detalles_cambio += f"Costo: ${costo_str}"

    AuditLog.registrar(
        action='ACTUALIZACION_MASIVA_PRECIOS',
        user_id=current_user.id,
        motivo=f'Edición masiva de precios para la referencia {modelo_celular} ({count} equipos)',
        detalles=detalles_cambio
    )

    flash(f'¡Precios actualizados con éxito en {count} celular(es) de la referencia "{modelo_celular}"!', 'success')
    return redirect(url_for('celulares_bp.inventario', referencia=modelo_celular))

@celulares_bp.route('/clientes')
@login_required
@admin_required
def clientes():
    from models import SaleClient
    # Subconsulta para obtener el ID de registro más reciente para cada documento único
    subquery = db.session.query(
        db.func.max(SaleClient.id)
    ).group_by(SaleClient.documento).subquery()
    
    # Obtener los clientes correspondientes a esos IDs ordenados por nombre
    clientes_lista = SaleClient.query.filter(
        SaleClient.id.in_(subquery)
    ).order_by(SaleClient.nombre).all()
    
    return render_template('celulares/clientes.html', clientes=clientes_lista)

@celulares_bp.route('/clientes/detalle/<documento>')
@login_required
@admin_required
def detalle_cliente(documento):
    from models import SaleClient
    # Obtener todas las compras asociadas a este documento
    registros = SaleClient.query.filter_by(documento=documento).order_by(SaleClient.id.desc()).all()
    if not registros:
        flash('Cliente no encontrado.', 'warning')
        return redirect(url_for('celulares_bp.clientes'))
    cliente_info = registros[0]
    return render_template('celulares/detalle_cliente.html',
                           cliente=cliente_info,
                           registros=registros)

@celulares_bp.route('/api/cliente/buscar')
@login_required
def api_buscar_cliente():
    from models import SaleClient
    documento = request.args.get('documento', '').strip()
    if not documento:
        return jsonify({'encontrado': False})
    cliente = SaleClient.query.filter_by(documento=documento).order_by(SaleClient.id.desc()).first()
    if cliente:
        return jsonify({
            'encontrado': True, 
            'nombre': cliente.nombre, 
            'telefono': cliente.telefono,
            'email': cliente.email or '',
            'direccion': cliente.direccion or ''
        })
    return jsonify({'encontrado': False})

@celulares_bp.route('/venta', methods=['GET', 'POST'])
@login_required
def venta():
    # Mostrar solo celulares que están en stock
    celulares_disponibles = Product.query.filter(
        Product.tipo_inventario == 'celulares',
        Product.cantidad_stock > 0
    ).all()
    
    if request.method == 'POST':
        celular_id = request.form.get('celular_id')
        precio_venta_final = float(request.form.get('precio_venta_final', 0.0))
        
        # Pagos mixtos
        metodos_pago = request.form.getlist('metodo_pago[]')
        montos_pago = request.form.getlist('monto_pago[]')
        
        if not celular_id or not metodos_pago or not montos_pago:
            flash('Datos incompletos para la venta.', 'danger')
            return redirect(url_for('celulares_bp.venta'))
            
        celular = Product.query.get(celular_id)
        if not celular or celular.cantidad_stock < 1:
            flash('El celular seleccionado no está disponible en stock.', 'danger')
            return redirect(url_for('celulares_bp.venta'))
            
        if precio_venta_final < float(celular.precio_minimo) and current_user.rol != 'admin':
            flash(f'El precio de venta no puede ser menor al mínimo permitido (${celular.precio_minimo:,.2f}).', 'danger')
            return redirect(url_for('celulares_bp.venta'))
            
        # Crear la Venta General (Se registrará en cajas)
        nueva_venta = Sale(
            vendedor_id=current_user.id,
            monto_total=precio_venta_final,
            # metode_pago is legacy, we can put the primary one or 'mixto'
            metodo_pago=metodos_pago[0] if len(metodos_pago) == 1 else 'mixto',
            tipo_venta='celulares'
        )
        db.session.add(nueva_venta)
        db.session.flush()
        
        # Registrar pagos
        suma_pagos = 0.0
        for mp, monto in zip(metodos_pago, montos_pago):
            monto_float = float(monto)
            if monto_float > 0:
                pago = SalePayment(
                    sale_id=nueva_venta.id,
                    metodo_pago=mp,
                    monto=monto_float
                )
                db.session.add(pago)
                suma_pagos += monto_float
                
        if abs(suma_pagos - precio_venta_final) > 0.01:
            db.session.rollback()
            flash('La suma de los métodos de pago no coincide con el total de la venta.', 'danger')
            return redirect(url_for('celulares_bp.venta'))
            
        # Registrar detalle
        detalle = SaleDetail(
            sale_id=nueva_venta.id,
            product_id=celular.id,
            cantidad_vendida=1,
            precio_venta_final=precio_venta_final
        )
        db.session.add(detalle)
        
        # Descontar stock
        celular.cantidad_stock -= 1

        # Registrar factura al proveedor si corresponde
        if celular.proveedor:
            from models import Provider, ProviderInvoice
            provider_obj = Provider.query.filter(Provider.nombre.ilike(celular.proveedor.strip())).first()
            if provider_obj and celular.precio_costo and float(celular.precio_costo) > 0:
                ref_factura = celular.modelo_celular if celular.modelo_celular else celular.nombre
                if celular.imei:
                    ref_factura = f"{ref_factura} (IMEI: {celular.imei})"
                factura_prov = ProviderInvoice(
                    provider_id=provider_obj.id,
                    sale_id=nueva_venta.id,
                    monto_total=float(celular.precio_costo),
                    numero_factura=ref_factura,
                    descripcion=f"Venta #{nueva_venta.id}"
                )
                db.session.add(factura_prov)
        
        try:
            db.session.commit()
            flash('Venta de celular registrada exitosamente.', 'success')
            return redirect(url_for('celulares_bp.historial_ventas'))
        except Exception as e:
            db.session.rollback()
            flash(f'Error al registrar la venta: {str(e)}', 'danger')
            
    return render_template('celulares/venta.html', celulares=celulares_disponibles)

@celulares_bp.route('/ventas/historial')
@login_required
def historial_ventas():
    filtro_inventario = request.args.get('inventario', '').strip()
    
    # Obtener opciones únicas de inventario para el filtro
    inventarios_disponibles = db.session.query(Product.inventario).filter(
        Product.tipo_inventario == 'celulares',
        Product.inventario != None,
        Product.inventario != ''
    ).distinct().all()
    inventarios_disponibles = [inv[0] for inv in inventarios_disponibles if inv[0]]

    # Obtener las ventas donde haya al menos un detalle de un producto tipo 'celulares'
    query = Sale.query.join(SaleDetail).join(Product).filter(
        Product.tipo_inventario == 'celulares'
    )
    
    if filtro_inventario:
        query = query.filter(Product.inventario == filtro_inventario)
        
    ventas_celulares = query.order_by(Sale.fecha_venta.desc()).all()
    
    # Para la vista, queremos mostrar datos específicos
    datos_historial = []
    for v in ventas_celulares:
        # En caso de ventas mixtas, filtramos solo los detalles de celulares (aunque usualmente será 1)
        detalles_cel = [d for d in v.detalles if d.producto and d.producto.tipo_inventario == 'celulares']
        for d in detalles_cel:
            datos_historial.append({
                'id_detalle': d.id,
                'id_venta': v.id,
                'fecha': v.fecha_venta,
                'vendedor': v.vendedor.nombre,
                'celular': f"{d.producto.nombre} (IMEI: {d.producto.imei or 'N/A'})",
                'inventario': d.producto.inventario or 'N/A',
                'precio_venta': d.precio_venta_final,
                'metodo_pago': v.metodo_pago_display,
                'ok_contabilidad': getattr(d, 'ok_contabilidad', False),
                'ok_inventario': getattr(d, 'ok_inventario', False)
            })
            
    return render_template('celulares/historial_ventas.html', 
                           historial=datos_historial, 
                           inventarios_disponibles=inventarios_disponibles,
                           filtro_inventario=filtro_inventario)

@celulares_bp.route('/toggle_ok_contabilidad/<int:detail_id>', methods=['POST'])
@login_required
@admin_required
def toggle_ok_contabilidad(detail_id):
    detalle = SaleDetail.query.get_or_404(detail_id)
    detalle.ok_contabilidad = not detalle.ok_contabilidad
    db.session.commit()
    return jsonify({'success': True, 'ok_contabilidad': detalle.ok_contabilidad})

@celulares_bp.route('/toggle_ok_inventario/<int:detail_id>', methods=['POST'])
@login_required
@admin_required
def toggle_ok_inventario(detail_id):
    detalle = SaleDetail.query.get_or_404(detail_id)
    detalle.ok_inventario = not detalle.ok_inventario
    db.session.commit()
    return jsonify({'success': True, 'ok_inventario': detalle.ok_inventario})



import pandas as pd
import io

@celulares_bp.route('/descargar_plantilla')
@login_required
@admin_required
def descargar_plantilla():
    import openpyxl
    from openpyxl.worksheet.datavalidation import DataValidation
    from openpyxl.styles import Font, PatternFill, Alignment

    wb = openpyxl.Workbook()
    ws_main = wb.active
    ws_main.title = 'Plantilla Celulares'

    # Catálogo enfocado: Apple, Samsung y Ray-Ban Meta
    catalogo_tipos = [
        'Celular',
        'Computador',
        'Tablet',
        'Gafas Inteligentes',
        'Smartwatch',
        'Otro'
    ]

    catalogo_marcas = [
        'Apple',
        'Samsung',
        'Ray-Ban Meta'
    ]

    catalogo_modelos = [
        # Apple - iPhones
        'iPhone 11', 'iPhone 11 Pro', 'iPhone 11 Pro Max',
        'iPhone 12', 'iPhone 12 Mini', 'iPhone 12 Pro', 'iPhone 12 Pro Max',
        'iPhone 13', 'iPhone 13 Mini', 'iPhone 13 Pro', 'iPhone 13 Pro Max',
        'iPhone 14', 'iPhone 14 Plus', 'iPhone 14 Pro', 'iPhone 14 Pro Max',
        'iPhone 15', 'iPhone 15 Plus', 'iPhone 15 Pro', 'iPhone 15 Pro Max',
        'iPhone 16', 'iPhone 16 Plus', 'iPhone 16 Pro', 'iPhone 16 Pro Max',
        'iPhone 17', 'iPhone 17 Plus', 'iPhone 17 Pro', 'iPhone 17 Pro Max',
        'iPhone 18', 'iPhone 18 Plus', 'iPhone 18 Pro', 'iPhone 18 Pro Max',
        # Apple - iPads, MacBooks & AirPods
        'iPad 10ma Gen (A16 Bionic)', 'iPad 11na Gen', 'iPad Mini 6', 'iPad Mini 7',
        'iPad Air 5 (M1)', 'iPad Air 11" (M2)', 'iPad Air 13" (M2)',
        'iPad Pro 11" (M2)', 'iPad Pro 12.9" (M2)', 'iPad Pro 11" (M4 OLED)', 'iPad Pro 13" (M4 OLED)',
        'MacBook Air 13" (M1)', 'MacBook Air 13" (M2)', 'MacBook Air 15" (M2)',
        'MacBook Air 13" (M3)', 'MacBook Air 15" (M3)',
        'MacBook Pro 14" (M3 / Pro / Max)', 'MacBook Pro 16" (M3 Pro / Max)',
        'MacBook Pro 14" (M4 / Pro / Max)', 'MacBook Pro 16" (M4 Pro / Max)',
        'AirPods 3ra Generación', 'AirPods 4ta Generación', 'AirPods 4ta Generación con ANC',
        'AirPods Pro 2da Generación (USB-C)', 'AirPods Max (Lightning)', 'AirPods Max (USB-C)',
        # Samsung - Serie S, Z Fold/Flip, Tabs y Buds
        'Galaxy S24', 'Galaxy S24 Plus', 'Galaxy S24 Ultra', 'Galaxy S24 FE',
        'Galaxy S25', 'Galaxy S25 Plus', 'Galaxy S25 Ultra', 'Galaxy S25 Slim',
        'Galaxy Z Fold 6', 'Galaxy Z Flip 6', 'Galaxy Z Fold 7', 'Galaxy Z Flip 7',
        'Galaxy Tab S9', 'Galaxy Tab S9 Plus', 'Galaxy Tab S9 Ultra', 'Galaxy Tab S9 FE',
        'Galaxy Tab S10 Plus', 'Galaxy Tab S10 Ultra',
        'Galaxy Buds 3', 'Galaxy Buds 3 Pro',
        # Ray-Ban Meta
        'Ray-Ban Meta Wayfarer',
        'Ray-Ban Meta Headliner',
        'Ray-Ban Meta Skyler'
    ]

    # Hoja oculta con las listas del catálogo
    ws_cat = wb.create_sheet(title='_Catalogos')
    ws_cat.sheet_state = 'hidden'

    for idx, item in enumerate(catalogo_tipos, start=1):
        ws_cat.cell(row=idx, column=1, value=item)
    for idx, item in enumerate(catalogo_marcas, start=1):
        ws_cat.cell(row=idx, column=2, value=item)
    for idx, item in enumerate(catalogo_modelos, start=1):
        ws_cat.cell(row=idx, column=3, value=item)

    # Cabeceras
    columnas = [
        'TIPO DISPOSITIVO', 'MARCA', 'REFERENCIA', 'CAPACIDAD', 
        'BATERIA', 'COLOR', 'IMEI 1', 'IMEI 2', 'PROVEEDOR', 
        'INVENTARIO', 'COSTO', 'P. MINIMO', 'P. SUGERIDO'
    ]

    header_font = Font(name='Calibri', size=11, bold=True, color='FFFFFF')
    header_fill = PatternFill(start_color='1E293B', end_color='1E293B', fill_type='solid')
    align_center = Alignment(horizontal='center', vertical='center')

    for col_idx, col_name in enumerate(columnas, start=1):
        cell = ws_main.cell(row=1, column=col_idx, value=col_name)
        cell.font = header_font
        cell.fill = header_fill
        cell.alignment = align_center

    # Validaciones de Datos (Listas desplegables en Excel)
    dv_tipo = DataValidation(type='list', formula1=f"='_Catalogos'!$A$1:$A${len(catalogo_tipos)}", allow_blank=True)
    dv_tipo.error = 'Seleccione un tipo de dispositivo válido'
    dv_tipo.errorTitle = 'Tipo Inválido'
    ws_main.add_data_validation(dv_tipo)
    dv_tipo.add('A2:A1000')

    dv_marca = DataValidation(type='list', formula1=f"='_Catalogos'!$B$1:$B${len(catalogo_marcas)}", allow_blank=True)
    dv_marca.error = 'Seleccione una marca válida (Apple, Samsung o Ray-Ban Meta)'
    dv_marca.errorTitle = 'Marca Inválida'
    ws_main.add_data_validation(dv_marca)
    dv_marca.add('B2:B1000')

    dv_modelo = DataValidation(type='list', formula1=f"='_Catalogos'!$C$1:$C${len(catalogo_modelos)}", allow_blank=True)
    dv_modelo.error = 'Seleccione una referencia/modelo del catálogo'
    dv_modelo.errorTitle = 'Referencia Inválida'
    ws_main.add_data_validation(dv_modelo)
    dv_modelo.add('C2:C1000')

    # Anchos de columna cómodos para visualización
    column_widths = {
        'A': 22, 'B': 18, 'C': 34, 'D': 16,
        'E': 14, 'F': 16, 'G': 20, 'H': 20,
        'I': 20, 'J': 18, 'K': 16, 'L': 16, 'M': 16
    }
    for col, width in column_widths.items():
        ws_main.column_dimensions[col].width = width

    output = io.BytesIO()
    wb.save(output)
    output.seek(0)
    return send_file(output, download_name='plantilla_celulares.xlsx', as_attachment=True, mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')

@celulares_bp.route('/importar_excel', methods=['POST'])
@login_required
@admin_required
def importar_excel():
    if 'archivo_excel' not in request.files:
        flash('No se subió ningún archivo.', 'danger')
        return redirect(url_for('celulares_bp.inventario'))
        
    file = request.files['archivo_excel']
    if file.filename == '':
        flash('El archivo está vacío.', 'danger')
        return redirect(url_for('celulares_bp.inventario'))
        
    if not file.filename.endswith(('.xlsx', '.xls')):
        flash('Formato de archivo no válido. Debe ser Excel (.xlsx o .xls).', 'danger')
        return redirect(url_for('celulares_bp.inventario'))
        
    try:
        df = pd.read_excel(file)
        # Limpiar nombres de columnas (quitar espacios extra y pasarlas a mayúsculas)
        df.columns = df.columns.str.strip().str.upper()
        
        columnas_esperadas = ['MARCA', 'REFERENCIA', 'CAPACIDAD', 'BATERIA', 'COLOR', 'IMEI 1', 'IMEI 2', 'PROVEEDOR', 'INVENTARIO', 'COSTO', 'P. MINIMO', 'P. SUGERIDO']
        
        for col in columnas_esperadas:
            if col not in df.columns:
                flash(f'El archivo no tiene la columna requerida: {col}', 'danger')
                return redirect(url_for('celulares_bp.inventario'))
                
        # Limpiar NaNs
        df = df.fillna('')
        
        exitosos = 0
        omitidos = 0
        
        for index, row in df.iterrows():
            imei1 = str(row['IMEI 1']).strip()
            # Si el IMEI está vacío, omitimos la fila
            if not imei1:
                continue
                
            # Limpiamos decimales en caso de que pandas haya leido el IMEI como float e.g. 123456.0
            if imei1.endswith('.0'):
                imei1 = imei1[:-2]
                
            # Verificar si existe el IMEI actualmente activo en stock
            existente = Product.query.filter(Product.imei == imei1, Product.tipo_inventario == 'celulares', Product.cantidad_stock > 0).first()
            if existente:
                omitidos += 1
                continue
                
            tipo_disp_raw = str(row.get('TIPO DISPOSITIVO', '')).strip()
            if not tipo_disp_raw:
                tipo_disp = 'Celular'
            elif tipo_disp_raw.lower() in ['otro', 'ninguno', 'n/a']:
                tipo_disp = ''
            else:
                tipo_disp = tipo_disp_raw

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
            
            imei2 = str(row['IMEI 2']).strip()
            if imei2.endswith('.0'):
                imei2 = imei2[:-2]
                
            proveedor = str(row['PROVEEDOR']).strip()
            inventario = str(row.get('INVENTARIO', '')).strip()
            
            # Limpiar precios (quitar $ y comas/puntos si vienen como texto)
            def clean_price(val):
                val = str(val).strip().replace('$', '').replace(',', '').replace(' ', '')
                try:
                    return float(val) if val else 0.0
                except:
                    return 0.0
                    
            costo = clean_price(row['COSTO'])
            minimo = clean_price(row['P. MINIMO'])
            sugerido = clean_price(row['P. SUGERIDO'])
            
            if tipo_disp:
                nombre_completo = f"{tipo_disp} {marca} {referencia} {color} {memoria}".strip()
            else:
                nombre_completo = f"{marca} {referencia} {color} {memoria}".strip()
            sku_base = f"CEL-{datetime.now().strftime('%Y%m%d%H%M%S%f')}" # %f para evitar skus duplicados en el mismo segundo
            
            nuevo = Product(
                nombre=nombre_completo,
                sku=sku_base,
                tipo_inventario='celulares',
                cantidad_stock=1,
                precio_costo=costo,
                precio_minimo=minimo,
                precio_sugerido=sugerido,
                marca=marca,
                modelo_celular=referencia,
                color=color,
                bateria=bateria,
                memoria=memoria,
                imei=imei1,
                imei2=imei2,
                proveedor=proveedor,
                inventario=inventario
            )
            
            db.session.add(nuevo)
            db.session.flush()

            # Multisucursal: Asignar a sucursal de destino y registrar en Kardex
            target_branch_id = _resolve_celular_branch_id(request.form.get('branch_id'))
            b_stock = get_or_create_branch_stock(target_branch_id, nuevo.id, None)
            b_stock.cantidad = 1
            sync_global_product_stock(nuevo.id, None)

            ajuste = StockAdjustment(
                product_id=nuevo.id,
                admin_id=current_user.id,
                branch_id=target_branch_id,
                tipo_movimiento='Ingreso Masivo Celulares (Excel)',
                stock_anterior=0,
                stock_nuevo=1
            )
            db.session.add(ajuste)
            exitosos += 1
            
        db.session.commit()
        
        mensaje = f'Carga Masiva completada: {exitosos} equipos subidos exitosamente.'
        if omitidos > 0:
            mensaje += f' Se omitieron {omitidos} equipos porque el IMEI 1 ya existía en el sistema.'
            
        flash(mensaje, 'success' if exitosos > 0 else 'warning')
        
    except Exception as e:
        db.session.rollback()
        flash(f'Ocurrió un error procesando el Excel: {str(e)}', 'danger')
        
    return redirect(url_for('celulares_bp.inventario'))


@celulares_bp.route('/trazabilidad', methods=['GET'])
@login_required
def trazabilidad():
    imei_query = request.args.get('imei', '').strip()
    clean_imei = imei_query.replace('-EXT', '').strip()
    
    eventos = []
    producto_info = None
    
    if clean_imei:
        # 1. Buscar productos que contengan el IMEI (históricos o activos)
        productos = Product.query.filter(
            or_(
                Product.imei == clean_imei,
                Product.imei2 == clean_imei,
                Product.imei == f"{clean_imei}-EXT",
                Product.imei.like(f"%{clean_imei}%"),
                Product.imei2.like(f"%{clean_imei}%")
            )
        ).all()
        
        # Guardar info principal del equipo si se encuentra
        if productos:
            p_latest = productos[-1] # El registro más reciente
            producto_info = {
                'id': p_latest.id,
                'nombre': p_latest.nombre,
                'marca': p_latest.marca,
                'modelo': p_latest.modelo_celular,
                'color': p_latest.color,
                'bateria': p_latest.bateria,
                'memoria': p_latest.memoria,
                'imei1': p_latest.imei,
                'imei2': p_latest.imei2,
                'proveedor': p_latest.proveedor,
                'inventario': p_latest.inventario,
                'stock_actual': p_latest.total_stock,
                'precio_costo': p_latest.precio_costo,
                'precio_sugerido': p_latest.precio_sugerido
            }

        p_ids = [p.id for p in productos]

        # Evento 1: Ingreso a inventario (para cada producto encontrado)
        for p in productos:
            eventos.append({
                'tipo': 'COMPRA_INGRESO',
                'titulo': f'Ingreso a Inventario ({p.inventario or "Tienda"})',
                'fecha': p.fecha_creacion,
                'icono': 'fa-solid fa-boxes-stacked text-primary',
                'badge_color': 'bg-primary text-white',
                'detalles': {
                    'Producto': p.nombre,
                    'Proveedor': p.proveedor or 'Cliente/Externo',
                    'Inventario': p.inventario or 'N/A',
                    'Precio Costo': f"${float(p.precio_costo or 0):,.0f}".replace(',', '.'),
                    'Precio Sugerido': f"${float(p.precio_sugerido or 0):,.0f}".replace(',', '.'),
                    'Estado Stock': 'En Stock (Disponible)' if p.total_stock > 0 else 'Agotado (Vendido)'
                }
            })

        # Evento 1.1: Ajustes e Ingresos de Stock (StockAdjustment) con sucursal
        from models import StockAdjustment
        if p_ids:
            ajustes = StockAdjustment.query.filter(StockAdjustment.product_id.in_(p_ids)).all()
            for aj in ajustes:
                branch_name = aj.branch.nombre if aj.branch else 'Sede Central'
                admin_name = aj.admin.nombre if aj.admin else 'Sistema'
                eventos.append({
                    'tipo': 'AJUSTE_STOCK',
                    'titulo': f'Movimiento: {aj.tipo_movimiento}',
                    'fecha': aj.fecha_ajuste,
                    'icono': 'fa-solid fa-sliders text-secondary',
                    'badge_color': 'bg-secondary text-white',
                    'detalles': {
                        'Sucursal': branch_name,
                        'Registrado por': admin_name,
                        'Stock Anterior': aj.stock_anterior,
                        'Stock Nuevo': aj.stock_nuevo,
                        'Tipo': aj.tipo_movimiento
                    }
                })

        # Evento 1.2: Traslados entre sedes (StockTransferItem -> StockTransfer)
        from models import StockTransferItem, StockTransfer
        if p_ids:
            transf_items = StockTransferItem.query.filter(StockTransferItem.product_id.in_(p_ids)).all()
            for ti in transf_items:
                t = ti.transferencia
                if t:
                    origen_nom = t.origen.nombre if t.origen else 'N/A'
                    destino_nom = t.destino.nombre if t.destino else 'N/A'
                    solicitante = t.solicitante.nombre if t.solicitante else 'N/A'
                    receptor = t.receptor.nombre if t.receptor else 'Pendiente'
                    eventos.append({
                        'tipo': 'TRASLADO',
                        'titulo': f'Traslado entre Sedes: {origen_nom} ➔ {destino_nom}',
                        'fecha': t.fecha_creacion,
                        'icono': 'fa-solid fa-truck-arrow-right text-info',
                        'badge_color': 'bg-info text-dark',
                        'detalles': {
                            'Transferencia': f"#{t.id} - {t.numero_guia}",
                            'Ruta': f"{origen_nom} ➔ {destino_nom}",
                            'Estado': t.estado.upper(),
                            'Cantidad': ti.cantidad,
                            'Enviado por': solicitante,
                            'Recibido por': receptor,
                            'Fecha Recibido': t.fecha_recepcion.strftime('%d/%m/%Y %H:%M') if t.fecha_recepcion else 'Pendiente'
                        }
                    })

        # 2. Buscar Ventas (SaleDetail) vinculadas a los productos o al IMEI
        from models import ProviderInvoice
        
        # Buscar también productos hermanos (ej. si existió con -EXT o duplicado)
        hermanos = Product.query.filter(
            or_(
                Product.imei == f"{clean_imei}-EXT",
                Product.imei == clean_imei,
                Product.imei2 == clean_imei
            )
        ).all()
        for h in hermanos:
            if h.id not in p_ids:
                p_ids.append(h.id)

        # Buscar ventas directas en SaleDetail
        detalles_venta = []
        if p_ids:
            detalles_venta = SaleDetail.query.filter(SaleDetail.product_id.in_(p_ids)).all()
        
        ventas_procesadas = set()
        for d in detalles_venta:
            v = d.venta
            if not v or v.id in ventas_procesadas:
                continue
            ventas_procesadas.add(v.id)
            
            cliente_nombre = 'Cliente General'
            if hasattr(v, 'cliente') and v.cliente:
                cliente_nombre = f"{v.cliente.nombre} (Doc: {v.cliente.documento})"
            
            branch_venta = v.branch.nombre if getattr(v, 'branch', None) else (v.sucursal or 'N/A')
                
            eventos.append({
                'tipo': 'VENTA',
                'titulo': f'Venta de Celular (Factura #{v.id})',
                'fecha': v.fecha_venta,
                'icono': 'fa-solid fa-cart-shopping text-success',
                'badge_color': 'bg-success text-white',
                'sale_id': v.id,
                'detalles': {
                    'Factura': f"#{v.id}",
                    'Cliente': cliente_nombre,
                    'Vendedor': v.vendedor.nombre if v.vendedor else 'N/A',
                    'Sucursal': branch_venta,
                    'Precio Venta Final': f"${float(d.precio_venta_final or 0):,.0f}".replace(',', '.'),
                    'Método de Pago': v.metodo_pago_display,
                    'OK Contabilidad': 'SÍ' if d.ok_contabilidad else 'NO',
                    'OK Inventario': 'SÍ' if d.ok_inventario else 'NO'
                }
            })

        # Si aún no encontró la venta en SaleDetail, buscar a través de ProviderInvoice generada para este IMEI
        if clean_imei:
            invoices_prov = ProviderInvoice.query.filter(
                or_(
                    ProviderInvoice.numero_factura.ilike(f"%{clean_imei}%"),
                    ProviderInvoice.descripcion.ilike(f"%{clean_imei}%")
                )
            ).all()
            for inv in invoices_prov:
                if inv.sale and inv.sale.id not in ventas_procesadas:
                    v = inv.sale
                    ventas_procesadas.add(v.id)
                    cliente_nombre = 'Cliente General'
                    if hasattr(v, 'cliente') and v.cliente:
                        cliente_nombre = f"{v.cliente.nombre} (Doc: {v.cliente.documento})"
                    
                    branch_venta = v.branch.nombre if getattr(v, 'branch', None) else (v.sucursal or 'N/A')

                    eventos.append({
                        'tipo': 'VENTA',
                        'titulo': f'Venta de Celular (Factura #{v.id})',
                        'fecha': v.fecha_venta,
                        'icono': 'fa-solid fa-cart-shopping text-success',
                        'badge_color': 'bg-success text-white',
                        'sale_id': v.id,
                        'detalles': {
                            'Factura': f"#{v.id}",
                            'Cliente': cliente_nombre,
                            'Vendedor': v.vendedor.nombre if v.vendedor else 'N/A',
                            'Sucursal': branch_venta,
                            'Monto Venta': f"${float(v.monto_total or 0):,.0f}".replace(',', '.'),
                            'Método de Pago': v.metodo_pago_display,
                            'Proveedor Liquidado': inv.provider.nombre if inv.provider else 'N/A'
                        }
                    })

        # 3. Buscar Retomas (Retoma) vinculadas al IMEI
        from models import Retoma
        retomas = Retoma.query.filter(
            or_(
                Retoma.imei1 == clean_imei,
                Retoma.imei2 == clean_imei,
                Retoma.imei1.like(f"%{clean_imei}%"),
                Retoma.imei2.like(f"%{clean_imei}%")
            )
        ).all()

        for r in retomas:
            branch_retoma = r.branch.nombre if getattr(r, 'branch', None) else (r.venta.sucursal if r.venta else 'N/A')
            eventos.append({
                'tipo': 'RETOMA',
                'titulo': f'Recibido como Retoma (Retoma #{r.id})',
                'fecha': r.fecha_registro,
                'icono': 'fa-solid fa-recycle text-warning',
                'badge_color': 'bg-warning text-dark',
                'sale_id': r.sale_id,
                'detalles': {
                    'Equipo Entregado': f"{r.marca or ''} {r.modelo}".strip(),
                    'Sucursal Receptor': branch_retoma,
                    'Valor de Retoma': f"${float(r.valor_retoma or 0):,.0f}".replace(',', '.'),
                    'Costo Arreglos': f"${float(r.arreglos or 0):,.0f}".replace(',', '.'),
                    'Vendedor Receptor': r.vendedor.nombre if r.vendedor else 'N/A',
                    'Estado': r.estado.upper(),
                    'OK Contabilidad': 'SÍ' if r.ok_contabilidad else 'NO',
                    'Observaciones': r.observaciones or 'Sin notas'
                }
            })

        # 4. Buscar Préstamos de Maneo vinculados
        for p in productos:
            for m in p.maneos:
                branch_maneo = m.branch.nombre if getattr(m, 'branch', None) else 'N/A'
                eventos.append({
                    'tipo': 'MANEO',
                    'titulo': f'Préstamo a Local Vecino ({m.local_vecino})',
                    'fecha': m.fecha_prestamo,
                    'icono': 'fa-solid fa-handshake text-info',
                    'badge_color': 'bg-info text-dark',
                    'detalles': {
                        'Sucursal Origen': branch_maneo,
                        'Local Receptor': m.local_vecino,
                        'Estado': m.estado,
                        'Fecha Préstamo': m.fecha_prestamo.strftime('%d/%m/%Y %H:%M') if m.fecha_prestamo else 'N/A',
                        'Fecha Resolución': m.fecha_resolucion.strftime('%d/%m/%Y %H:%M') if m.fecha_resolucion else 'Pendiente'
                    }
                })

        # 5. Buscar Garantías vinculadas a las ventas del IMEI o producto
        from models import Warranty
        warranties_encontradas = []
        if p_ids:
            warranties_encontradas.extend(Warranty.query.filter(Warranty.product_id.in_(p_ids)).all())
        if ventas_procesadas:
            w_ventas = Warranty.query.filter(Warranty.sale_id.in_(list(ventas_procesadas))).all()
            for wv in w_ventas:
                if wv not in warranties_encontradas:
                    warranties_encontradas.append(wv)
        
        for w in warranties_encontradas:
            branch_garantia = w.branch.nombre if getattr(w, 'branch', None) else 'N/A'
            eventos.append({
                'tipo': 'GARANTIA',
                'titulo': f'Reclamo de Garantía #{w.id}',
                'fecha': w.created_at,
                'icono': 'fa-solid fa-shield-halved text-danger',
                'badge_color': 'bg-danger text-white',
                'detalles': {
                    'Garantía': f"#{w.id}",
                    'Sucursal Receptora': branch_garantia,
                    'Motivo': w.reason,
                    'Estado': w.resolution,
                    'Factura Venta': f"#{w.sale_id}" if w.sale_id else 'N/A',
                    'Notas': w.admin_notes or 'Sin observaciones'
                }
            })

        # Ordenar eventos cronológicamente (de más antiguo a más reciente)
        eventos.sort(key=lambda x: x['fecha'] if x['fecha'] else datetime.min)

    return render_template('celulares/trazabilidad.html',
                           imei=clean_imei,
                           producto_info=producto_info,
                           eventos=eventos)

