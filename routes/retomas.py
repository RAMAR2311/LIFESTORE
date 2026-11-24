import re
from flask import Blueprint, request, flash, redirect, render_template, url_for, jsonify
from flask_login import login_required, current_user
from models import db, Product, Retoma, obtener_hora_bogota, AuditLog, TechnicalService, Branch, Technician, Asesor
from decorators import admin_required
from decimal import Decimal
from sqlalchemy.orm import joinedload
from sqlalchemy import or_

retomas_bp = Blueprint('retomas_bp', __name__)

@retomas_bp.route('/cuarentena', methods=['GET'])
@login_required
@admin_required
def cuarentena():
    q = request.args.get('q', '').strip()
    page = request.args.get('page', 1, type=int)
    per_page = 20

    # Base query: all retomas
    base_query = Retoma.query.options(
        joinedload(Retoma.venta),
        joinedload(Retoma.producto_generado).joinedload(Product.detalles_venta)
    )

    # Optional text search
    if q:
        base_query = base_query.filter(
            or_(
                Retoma.marca.ilike(f'%{q}%'),
                Retoma.modelo.ilike(f'%{q}%'),
                Retoma.imei1.ilike(f'%{q}%'),
                Retoma.imei2.ilike(f'%{q}%'),
            )
        )

    paginacion = base_query.order_by(Retoma.fecha_registro.desc()).paginate(
        page=page, per_page=per_page, error_out=False
    )
    
    for r_item in paginacion.items:
        r_item.es_reingreso = False
        if r_item.imei1:
            prod_previo = Product.query.filter(
                ((Product.imei == r_item.imei1) | (Product.imei2 == r_item.imei1)),
                Product.cantidad_stock == 0
            ).first()
            if prod_previo:
                r_item.es_reingreso = True

    from models import Technician, Asesor, Branch
    tecnicos_disponibles = Technician.query.filter_by(activo=True).order_by(Technician.nombre.asc()).all()
    asesores_disponibles = Asesor.query.filter_by(activo=True).order_by(Asesor.nombre.asc()).all()
    sucursales_disponibles = Branch.query.filter_by(activa=True).order_by(Branch.id.asc()).all()

    return render_template('retomas/cuarentena.html',
                           retomas=paginacion.items,
                           paginacion=paginacion,
                           tecnicos_disponibles=tecnicos_disponibles,
                           asesores_disponibles=asesores_disponibles,
                           sucursales_disponibles=sucursales_disponibles,
                           q=q)

@retomas_bp.route('/crear', methods=['POST'])
@login_required
@admin_required
def crear_retoma_directa():
    # Detectar si viene en lote (arrays) o individual
    modelos = request.form.getlist('modelo[]')
    marcas = request.form.getlist('marca[]')
    imeis1 = request.form.getlist('imei1[]')
    imeis2 = request.form.getlist('imei2[]')
    colores = request.form.getlist('color[]')
    baterias = request.form.getlist('bateria[]')
    memorias = request.form.getlist('memoria[]')
    valores_raw = request.form.getlist('valor_retoma[]')
    observaciones_list = request.form.getlist('observaciones[]')

    # Si no vienen en arrays, tomar valores simples para compatibilidad
    if not modelos and request.form.get('modelo'):
        modelos = [request.form.get('modelo')]
        marcas = [request.form.get('marca')]
        imeis1 = [request.form.get('imei1')]
        imeis2 = [request.form.get('imei2')]
        colores = [request.form.get('color')]
        baterias = [request.form.get('bateria')]
        memorias = [request.form.get('memoria')]
        valores_raw = [request.form.get('valor_retoma')]
        observaciones_list = [request.form.get('observaciones')]

    if not modelos or not imeis1:
        flash('Debes ingresar al menos un equipo con modelo e IMEI.', 'danger')
        return redirect(url_for('retomas_bp.cuarentena'))

    # Datos compartidos del lote
    proveedor = request.form.get('proveedor', '').strip() or 'Cliente'
    branch_id_input = request.form.get('branch_id', type=int)
    asesor_id_input = request.form.get('asesor_retoma_id', type=int)
    target_branch_id = branch_id_input or current_user.branch_id or 1

    # Validar duplicados dentro del mismo lote enviado
    vistos_en_lote = set()
    equipos_a_crear = []

    for i in range(len(modelos)):
        mod = (modelos[i] or '').strip()
        mrc = (marcas[i] or '').strip() if i < len(marcas) else ''
        im1 = (imeis1[i] or '').strip() if i < len(imeis1) else ''
        im2 = (imeis2[i] or '').strip() if i < len(imeis2) else ''
        col = (colores[i] or '').strip() if i < len(colores) else ''
        bat = (baterias[i] or '').strip() if i < len(baterias) else ''
        mem = (memorias[i] or '').strip() if i < len(memorias) else ''
        v_raw = valores_raw[i] if i < len(valores_raw) else '0'
        obs = (observaciones_list[i] or '').strip() if i < len(observaciones_list) else ''

        if not mod or not im1:
            continue

        if im1 in vistos_en_lote:
            flash(f'El IMEI "{im1}" está repetido dentro del mismo lote.', 'danger')
            return redirect(url_for('retomas_bp.cuarentena'))
        vistos_en_lote.add(im1)

        # Validar en base de datos
        retoma_existente = Retoma.query.filter_by(imei1=im1, estado='en_evaluacion').first()
        if retoma_existente:
            flash(f'El IMEI "{im1}" ({mod}) ya está registrado en evaluación (Retoma #{retoma_existente.id}).', 'danger')
            return redirect(url_for('retomas_bp.cuarentena'))

        prod_activo = Product.query.filter_by(imei=im1).first()
        if prod_activo and prod_activo.total_stock > 0:
            flash(f'El IMEI "{im1}" ({mod}) ya pertenece a un celular activo en stock ({prod_activo.nombre}).', 'danger')
            return redirect(url_for('retomas_bp.cuarentena'))

        # Limpiar valor
        val_clean = re.sub(r'[^\d.]', '', str(v_raw).replace(',', ''))
        try:
            val_dec = Decimal(val_clean)
        except:
            val_dec = Decimal('0')

        if val_dec <= 0:
            flash(f'Debes ingresar un valor de retoma válido mayor a $0 para el equipo "{mod}".', 'danger')
            return redirect(url_for('retomas_bp.cuarentena'))

        equipos_a_crear.append({
            'modelo': mod,
            'marca': mrc,
            'imei1': im1,
            'imei2': im2 or None,
            'color': col or None,
            'bateria': bat or None,
            'memoria': mem or None,
            'valor_retoma': val_dec,
            'observaciones': obs or None
        })

    if not equipos_a_crear:
        flash('No se encontraron equipos válidos para registrar.', 'danger')
        return redirect(url_for('retomas_bp.cuarentena'))

    try:
        creados = []
        for eq in equipos_a_crear:
            nueva_retoma = Retoma(
                sale_id=None,
                modelo=eq['modelo'],
                marca=eq['marca'],
                proveedor=proveedor,
                valor_retoma=eq['valor_retoma'],
                arreglos=Decimal('0.00'),
                imei1=eq['imei1'],
                imei2=eq['imei2'],
                color=eq['color'],
                bateria=eq['bateria'],
                memoria=eq['memoria'],
                observaciones=eq['observaciones'],
                estado='en_evaluacion',
                ok_contabilidad=False,
                ok_venta=False,
                vendedor_id=current_user.id,
                branch_id=target_branch_id,
                asesor_retoma_id=asesor_id_input
            )
            db.session.add(nueva_retoma)
            creados.append(nueva_retoma)

        db.session.commit()

        # Registro en auditoría
        detalles_log = f"Lote de {len(creados)} retoma(s) directas creado: " + ", ".join([f"#{r.id} ({r.marca} {r.modelo} - IMEI {r.imei1})" for r in creados])
        log = AuditLog(
            user_id=current_user.id,
            action='CREAR_RETOMAS_LOTE',
            details=detalles_log
        )
        db.session.add(log)
        db.session.commit()

        if len(creados) == 1:
            flash(f'Retoma #{creados[0].id} ({creados[0].marca} {creados[0].modelo}) registrada exitosamente en Cuarentena.', 'success')
        else:
            flash(f'¡Se registraron exitosamente {len(creados)} retomas en Cuarentena!', 'success')

    except Exception as e:
        db.session.rollback()
        flash(f'Error al registrar las retomas: {str(e)}', 'danger')

    return redirect(url_for('retomas_bp.cuarentena'))

@retomas_bp.route('/aprobar/<int:id>', methods=['POST'])
@login_required
@admin_required
def aprobar_retoma(id):
    retoma = Retoma.query.get_or_404(id)
    if retoma.estado != 'en_evaluacion':
        flash('Esta retoma ya fue procesada.', 'warning')
        return redirect(url_for('retomas_bp.cuarentena'))

    nombre_definitivo = request.form.get('nombre_definitivo')
    precio_sugerido = request.form.get('precio_sugerido')
    precio_minimo = request.form.get('precio_minimo', precio_sugerido)
    arreglos = request.form.get('arreglos', '0')
    bateria_input = request.form.get('bateria', retoma.bateria or '').strip()
    inventario_input = request.form.get('inventario', '').strip() or 'PRINCIPAL'
    
    if not nombre_definitivo or not precio_sugerido:
        flash('Faltan datos obligatorios para crear el producto.', 'danger')
        return redirect(url_for('retomas_bp.cuarentena'))

    try:
        arreglos_val = Decimal(arreglos)
    except:
        arreglos_val = Decimal('0')

    # Guardar costo de arreglos y nueva batería en la retoma
    retoma.arreglos = arreglos_val
    if bateria_input:
        retoma.bateria = bateria_input

    # Determinar la sucursal de destino para la retoma
    target_branch_id = retoma.branch_id
    if not target_branch_id:
        target_branch_id = current_user.branch_id or 1
    
    from models import Branch, StockAdjustment
    from services.stock_service import get_or_create_branch_stock, sync_global_product_stock

    branch_obj = Branch.query.get(target_branch_id)
    branch_nom = branch_obj.nombre if branch_obj else 'Principal'

    costo_total_retoma = retoma.valor_retoma + arreglos_val
    precio_min_dec = Decimal(precio_minimo)
    precio_sug_dec = Decimal(precio_sugerido)

    imei1_val = (retoma.imei1 or '').strip()
    imei2_val = (retoma.imei2 or '').strip() or None

    try:
        producto_final = None
        es_reingreso = False

        if imei1_val:
            prod_existente = Product.query.filter_by(imei=imei1_val).first()
            if prod_existente:
                if prod_existente.total_stock > 0 or prod_existente.cantidad_stock > 0:
                    flash(f'El IMEI "{imei1_val}" ya está registrado y activo con stock en el inventario ({prod_existente.nombre}).', 'danger')
                    return redirect(url_for('retomas_bp.cuarentena'))
                
                # REINGRESO INTELIGENTE DE IMEI EXISTENTE:
                # NO duplicar el Product (evita violar unique constraint).
                # Se reactiva el producto existente con nuevos datos y +1 stock en la sucursal de retoma.
                prod_existente.nombre = nombre_definitivo
                prod_existente.precio_costo = costo_total_retoma
                prod_existente.precio_minimo = precio_min_dec
                prod_existente.precio_sugerido = precio_sug_dec
                prod_existente.estado_celular = 'Usado'
                prod_existente.inventario = inventario_input
                if bateria_input:
                    prod_existente.bateria = bateria_input
                if retoma.observaciones:
                    prod_existente.observacion = f"{prod_existente.observacion or ''} | Retoma #{retoma.id}: {retoma.observaciones}".strip(' |')
                
                producto_final = prod_existente
                es_reingreso = True

        if not producto_final:
            nuevo_sku = f"RET-{retoma.id}-{obtener_hora_bogota().strftime('%Y%m%d%H%M%S')}"
            producto_final = Product(
                nombre=nombre_definitivo,
                sku=nuevo_sku,
                tipo_inventario='celulares',
                inventario=inventario_input,
                cantidad_stock=0, # Se actualizará vía BranchStock + sync_global
                precio_costo=costo_total_retoma,
                precio_minimo=precio_min_dec,
                precio_sugerido=precio_sug_dec,
                observacion=retoma.observaciones,
                imei=imei1_val,
                imei2=imei2_val,
                color=retoma.color,
                bateria=bateria_input or retoma.bateria,
                memoria=retoma.memoria,
                proveedor=retoma.proveedor or 'Cliente',
                marca=retoma.marca or '',
                modelo_celular=retoma.modelo,
                estado_celular='Usado'
            )
            db.session.add(producto_final)
            db.session.flush()

        # Sumar +1 en BranchStock para la sucursal donde se recibió la retoma
        b_stock = get_or_create_branch_stock(target_branch_id, producto_final.id, None, for_update=True)
        stock_ant = b_stock.cantidad
        b_stock.cantidad += 1
        sync_global_product_stock(producto_final.id, None)

        # Registrar StockAdjustment con branch_id
        tipo_mov = 'REINGRESO_RETOMA' if es_reingreso else 'INGRESO_RETOMA'
        ajuste = StockAdjustment(
            product_id=producto_final.id,
            admin_id=current_user.id,
            branch_id=target_branch_id,
            tipo_movimiento=f"{tipo_mov} (Retoma #{retoma.id} en {branch_nom})",
            stock_anterior=stock_ant,
            stock_nuevo=b_stock.cantidad
        )
        db.session.add(ajuste)

        retoma.producto_generado_id = producto_final.id
        retoma.estado = 'aprobado'
        db.session.commit()
        
        msg = f'Retoma aprobada con éxito como {"reingreso de celular previo" if es_reingreso else "nuevo producto"} en sucursal {branch_nom}.'
        flash(msg, 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Error al procesar la aprobación de la retoma: {str(e)}', 'danger')
        
    return redirect(url_for('retomas_bp.cuarentena'))

@retomas_bp.route('/eliminar/<int:id>', methods=['POST'])
@login_required
@admin_required
def eliminar_retoma(id):
    retoma = Retoma.query.get_or_404(id)
    try:
        # Si la retoma generó un producto que sigue sin venderse en stock, eliminarlo también
        if retoma.producto_generado and retoma.producto_generado.cantidad_stock > 0:
            db.session.delete(retoma.producto_generado)

        db.session.delete(retoma)
        db.session.commit()
        flash('Retoma eliminada correctamente.', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Error al eliminar la retoma: {str(e)}', 'danger')

    return redirect(url_for('retomas_bp.cuarentena'))

@retomas_bp.route('/editar/<int:id>', methods=['POST'])
@login_required
@admin_required
def editar_retoma(id):
    retoma = Retoma.query.get_or_404(id)

    marca = request.form.get('marca', '').strip()
    modelo = request.form.get('modelo', '').strip()
    memoria = request.form.get('memoria', '').strip()
    color = request.form.get('color', '').strip()
    bateria = request.form.get('bateria', '').strip()
    imei1 = request.form.get('imei1', '').strip()
    imei2 = request.form.get('imei2', '').strip() or None
    valor_retoma_raw = request.form.get('valor_retoma', '0')
    observaciones = request.form.get('observaciones', '').strip()

    if not modelo or not imei1:
        flash('El modelo y el IMEI 1 son obligatorios.', 'danger')
        return redirect(url_for('retomas_bp.cuarentena'))

    # Verificar IMEI 1 duplicado en retomas (excluyendo la actual)
    existente = Retoma.query.filter(Retoma.imei1 == imei1, Retoma.id != id).first()
    if existente:
        flash(f'El IMEI 1 "{imei1}" ya está registrado en otra retoma.', 'danger')
        return redirect(url_for('retomas_bp.cuarentena'))

    try:
        clean_val = re.sub(r'[^\d.]', '', str(valor_retoma_raw))
        valor_retoma = Decimal(clean_val) if clean_val else retoma.valor_retoma
    except:
        valor_retoma = retoma.valor_retoma

    retoma.marca = marca
    retoma.modelo = modelo
    retoma.memoria = memoria
    retoma.color = color
    retoma.bateria = bateria
    retoma.imei1 = imei1
    retoma.imei2 = imei2
    retoma.valor_retoma = valor_retoma
    retoma.observaciones = observaciones

    # Si la retoma ya había generado un producto en el inventario, mantener el producto sincronizado
    if retoma.producto_generado:
        prod = retoma.producto_generado
        prod.marca = marca
        prod.modelo_celular = modelo
        prod.memoria = memoria
        prod.color = color
        prod.bateria = bateria
        prod.imei = imei1
        prod.imei2 = imei2
        prod.precio_costo = valor_retoma + (retoma.arreglos or Decimal('0.00'))
        prod.observacion = observaciones
        if prod.nombre:
            clean_marca = (marca or '').strip()
            clean_modelo = (modelo or '').strip()
            if clean_marca and clean_marca.lower() in clean_modelo.lower():
                nombre_base = clean_modelo
            else:
                nombre_base = f"{clean_marca} {clean_modelo}".strip() if clean_marca else clean_modelo
            prod.nombre = re.sub(r'\s*\([Uu]sado\)', '', nombre_base).strip()

    try:
        db.session.commit()
        flash('Retoma actualizada exitosamente.', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Error al actualizar la retoma: {str(e)}', 'danger')

    return redirect(url_for('retomas_bp.cuarentena'))

@retomas_bp.route('/toggle_ok_contabilidad/<int:id>', methods=['POST'])
@login_required
@admin_required
def toggle_ok_contabilidad(id):
    retoma = Retoma.query.get_or_404(id)
    retoma.ok_contabilidad = not retoma.ok_contabilidad
    db.session.commit()

    if request.headers.get('X-Requested-With') == 'XMLHttpRequest' or request.is_json:
        return jsonify({
            'success': True,
            'ok_contabilidad': retoma.ok_contabilidad,
            'message': 'Estado de contabilidad actualizado.'
        })

    flash(f"Estado OK Contabilidad actualizado a {'Aprobado' if retoma.ok_contabilidad else 'Pendiente'}.", "success")
    return redirect(request.referrer or url_for('retomas_bp.cuarentena'))

@retomas_bp.route('/toggle_ok_venta/<int:id>', methods=['POST'])
@login_required
@admin_required
def toggle_ok_venta(id):
    retoma = Retoma.query.get_or_404(id)
    retoma.ok_venta = not retoma.ok_venta
    db.session.commit()

    if request.headers.get('X-Requested-With') == 'XMLHttpRequest' or request.is_json:
        return jsonify({
            'success': True,
            'ok_venta': retoma.ok_venta,
            'message': 'Estado de OK Venta actualizado.'
        })

    flash(f"Estado OK Venta actualizado a {'Aprobado' if retoma.ok_venta else 'Pendiente'}.", "success")
    return redirect(request.referrer or url_for('retomas_bp.cuarentena'))

@retomas_bp.route('/enviar-soporte-lote', methods=['POST'])
@login_required
@admin_required
def enviar_soporte_lote():
    """Envía un grupo de equipos de retoma en lote a soporte técnico."""
    ids_str = request.form.get('selected_ids', '').strip()
    if not ids_str:
        flash('No seleccionaste ninguna retoma para enviar a soporte.', 'warning')
        return redirect(url_for('retomas_bp.cuarentena'))

    ids = [int(x) for x in ids_str.split(',') if x.strip().isdigit()]
    if not ids:
        flash('Lista de retomas inválida.', 'warning')
        return redirect(url_for('retomas_bp.cuarentena'))

    technician_id = request.form.get('technician_id', type=int)
    asesor_id = request.form.get('asesor_id', type=int)
    tipo_arreglo = request.form.get('tipo_arreglo', '').strip()
    if tipo_arreglo == 'Otro':
        otro_tipo = request.form.get('tipo_arreglo_otro', '').strip()
        if otro_tipo:
            tipo_arreglo = f"Otro: {otro_tipo}"
    if not tipo_arreglo:
        tipo_arreglo = 'Diagnóstico General / Revisión'
    motivo_falla = request.form.get('motivo_falla', '').strip() or 'Envío en lote a revisión técnica'
    fecha_estimada_str = request.form.get('fecha_estimada', '').strip()

    fecha_estimada = None
    if fecha_estimada_str:
        try:
            from datetime import datetime
            fecha_estimada = datetime.strptime(fecha_estimada_str, '%Y-%m-%d').date()
        except ValueError:
            pass

    user_branch_default = current_user.branch_id
    if not user_branch_default:
        from models import Branch
        default_b = Branch.query.filter_by(activa=True).first()
        user_branch_default = default_b.id if default_b else 1

    from models import TechnicalService, AuditLog
    retomas_list = Retoma.query.filter(Retoma.id.in_(ids)).all()

    enviados = 0
    try:
        for r in retomas_list:
            r_branch_id = r.branch_id or user_branch_default

            servicio = TechnicalService(
                origen='RETOMA',
                retoma_id=r.id,
                product_id=r.producto_generado_id,
                branch_id=r_branch_id,
                technician_id=technician_id,
                asesor_id=asesor_id or r.asesor_retoma_id,
                created_by_id=current_user.id,
                marca=r.marca,
                modelo=r.modelo,
                imei=r.imei1,
                color=r.color,
                motivo_falla=motivo_falla,
                tipo_arreglo=tipo_arreglo,
                estado='EN_REVISION',
                fecha_estimada=fecha_estimada
            )
            db.session.add(servicio)
            r.estado = 'en_soporte'
            r.observaciones = f"[EN TALLER / SOPORTE TÉCNICO]: {motivo_falla} | Falla: {tipo_arreglo}. " + (r.observaciones or '')
            enviados += 1

        db.session.commit()

        AuditLog.registrar(
            action='ENVIO_SOPORTE_RETOMAS_LOTE',
            user_id=current_user.id,
            motivo=f'Envío en lote de {enviados} retomas a soporte técnico ({tipo_arreglo})',
            target_id=None,
            target_type='TECHNICAL_SERVICE_BATCH'
        )

        flash(f'¡Éxito! Se enviaron {enviados} equipos de retoma a Soporte Técnico.', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Error al enviar retomas a soporte: {str(e)}', 'danger')

    return redirect(url_for('retomas_bp.cuarentena'))

@retomas_bp.route('/eliminar-lote', methods=['POST'])
@login_required
@admin_required
def eliminar_retomas_lote():
    """Elimina en lote retomas seleccionadas con confirmación de token secreto."""
    import os
    token_ingresado = request.form.get('token_secreto', '').strip()
    token_correcto = os.environ.get('DELETE_TOKEN', '1234').strip()

    if not token_ingresado or token_ingresado != token_correcto:
        flash('Token secreto incorrecto. Eliminación en lote cancelada.', 'danger')
        return redirect(url_for('retomas_bp.cuarentena'))

    ids_str = request.form.get('selected_ids', '').strip()
    if not ids_str:
        flash('No seleccionaste ninguna retoma para eliminar.', 'warning')
        return redirect(url_for('retomas_bp.cuarentena'))

    ids = [int(x) for x in ids_str.split(',') if x.strip().isdigit()]
    if not ids:
        flash('Lista de retomas inválida.', 'warning')
        return redirect(url_for('retomas_bp.cuarentena'))

    from models import AuditLog
    retomas_list = Retoma.query.filter(Retoma.id.in_(ids)).all()
    eliminados = 0

    try:
        for r in retomas_list:
            # Si ya tiene un producto aprobado vendido, no permitir eliminar
            if r.producto_generado and r.producto_generado.detalles_venta:
                continue

            db.session.delete(r)
            eliminados += 1

        db.session.commit()

        AuditLog.registrar(
            action='ELIMINACION_RETOMAS_LOTE',
            user_id=current_user.id,
            motivo=f'Eliminación en lote de {eliminados} retomas mediante token de seguridad',
            target_id=None,
            target_type='RETOMA_BATCH'
        )

        flash(f'Se eliminaron correctamente {eliminados} retomas del sistema.', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Error al eliminar retomas en lote: {str(e)}', 'danger')

    return redirect(url_for('retomas_bp.cuarentena'))
