import os
import re
import io
import json
import uuid
from datetime import datetime
import pandas as pd
from flask import Blueprint, request, flash, redirect, render_template, url_for, jsonify, session, current_app
from flask_login import login_required, current_user
from models import (
    db, Product, Retoma, obtener_hora_bogota, AuditLog, TechnicalService, 
    Branch, Technician, Asesor, RetomaImportBatch, BranchStock, StockAdjustment, SaleDetail
)
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
    codigo_asesor_input = (request.form.get('codigo_asesor') or '').strip().upper()
    target_branch_id = branch_id_input or current_user.branch_id or 1

    # Blindaje de Seguridad: Identificación y validación obligatoria mediante Código de Asesor
    if not codigo_asesor_input:
        flash('Debes ingresar tu Código de Asesor para certificar la retoma.', 'danger')
        return redirect(url_for('retomas_bp.cuarentena'))

    asesor_obj = None
    asesores_activos = Asesor.query.filter_by(activo=True).all()
    for asr in asesores_activos:
        cod_esperado = (asr.codigo or f"ASE-{asr.id:03d}").strip().upper()
        if codigo_asesor_input == cod_esperado:
            asesor_obj = asr
            break

    if not asesor_obj and asesor_id_input:
        asr_cand = Asesor.query.get(asesor_id_input)
        if asr_cand and asr_cand.activo:
            cod_esperado = (asr_cand.codigo or f"ASE-{asr_cand.id:03d}").strip().upper()
            if codigo_asesor_input == cod_esperado:
                asesor_obj = asr_cand

    if not asesor_obj:
        flash(f"Código de asesor '{codigo_asesor_input}' no reconocido o el asesor no se encuentra activo.", 'danger')
        return redirect(url_for('retomas_bp.cuarentena'))

    asesor_id_input = asesor_obj.id

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
        detalles_log = f"Lote de {len(creados)} retoma(s) directas creado por Asesor {asesor_obj.nombre} (Código verificado): " + ", ".join([f"#{r.id} ({r.marca} {r.modelo} - IMEI {r.imei1})" for r in creados])
        log = AuditLog(
            user_id=current_user.id,
            action='CREAR_RETOMAS_LOTE',
            details=detalles_log
        )
        db.session.add(log)
        db.session.commit()

        if len(creados) == 1:
            flash(f'Retoma #{creados[0].id} ({creados[0].marca} {creados[0].modelo}) registrada exitosamente en Cuarentena por el asesor {asesor_obj.nombre}.', 'success')
        else:
            flash(f'¡Se registraron exitosamente {len(creados)} retomas en Cuarentena a nombre del asesor {asesor_obj.nombre}!', 'success')

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


# ==========================================================
# CARGA MASIVA DE RETOMAS DIRECTAS A INVENTARIO CON ROLLBACK
# ==========================================================

@retomas_bp.route('/importar_masivo', methods=['GET'])
@login_required
@admin_required
def importar_masivo():
    batches = RetomaImportBatch.query.order_by(RetomaImportBatch.fecha_creacion.desc()).limit(25).all()
    sucursales = Branch.query.filter_by(activa=True).order_by(Branch.id.asc()).all()
    asesores = Asesor.query.filter_by(activo=True).order_by(Asesor.nombre.asc()).all()
    
    lotes_procesados = []
    for b in batches:
        detalles = {}
        try:
            detalles = json.loads(b.detalles_json or '{}')
        except:
            pass
        lotes_procesados.append({
            'obj': b,
            'retoma_ids': detalles.get('retoma_ids', []),
            'product_ids': detalles.get('product_ids', []),
            'resumen_asesores': detalles.get('resumen_asesores', {})
        })

    return render_template('retomas/importar_masivo.html', 
                           batches=lotes_procesados, 
                           sucursales=sucursales, 
                           asesores=asesores)


@retomas_bp.route('/importar_masivo/preview', methods=['POST'])
@login_required
@admin_required
def importar_masivo_preview():
    if 'archivo' not in request.files:
        flash('No se seleccionó ningún archivo.', 'danger')
        return redirect(url_for('retomas_bp.importar_masivo'))

    file = request.files['archivo']
    if not file or file.filename == '':
        flash('El archivo seleccionado está vacío.', 'danger')
        return redirect(url_for('retomas_bp.importar_masivo'))

    filename_lower = file.filename.lower()
    if not (filename_lower.endswith('.xlsx') or filename_lower.endswith('.xls') or filename_lower.endswith('.csv')):
        flash('Formato de archivo no válido. Debe ser Excel (.xlsx, .xls) o CSV (.csv).', 'danger')
        return redirect(url_for('retomas_bp.importar_masivo'))

    default_branch_id = request.form.get('default_branch_id', type=int) or current_user.branch_id or 1

    try:
        if filename_lower.endswith('.csv'):
            content = file.read()
            try:
                decoded = content.decode('utf-8')
            except UnicodeDecodeError:
                decoded = content.decode('latin1', errors='replace')
            sep = ';' if ';' in decoded[:1000] else ','
            df = pd.read_csv(io.StringIO(decoded), sep=sep, dtype=str)
        else:
            df = pd.read_excel(file, dtype=str)

        def norm_col(c):
            c = str(c).strip().lower()
            c = c.replace('á', 'a').replace('é', 'e').replace('í', 'i').replace('ó', 'o').replace('ú', 'u')
            c = c.replace('.', '').replace('_', ' ').replace('-', ' ')
            return ' '.join(c.split())

        col_map = {}
        for original in df.columns:
            n = norm_col(original)
            if 'codigo asesor' in n or 'asesor' in n or 'cod asesor' in n:
                col_map['codigo_asesor'] = original
            elif 'marca' in n or 'brand' in n:
                col_map['marca'] = original
            elif 'modelo' in n or 'referencia' in n:
                col_map['modelo'] = original
            elif 'almacenamiento' in n or 'capacidad' in n or 'memoria' in n:
                col_map['almacenamiento'] = original
            elif 'imei 1' in n or 'imei1' in n or 'serial' in n or n == 'imei':
                col_map['imei1'] = original
            elif 'imei 2' in n or 'imei2' in n:
                col_map['imei2'] = original
            elif 'color' in n:
                col_map['color'] = original
            elif 'bateria' in n:
                col_map['bateria'] = original
            elif 'valor retoma' in n or 'costo' in n or 'retoma' in n:
                col_map['valor_retoma'] = original
            elif 'precio minimo' in n or 'p minimo' in n or 'minimo' in n:
                col_map['precio_minimo'] = original
            elif 'precio sugerido' in n or 'p sugerido' in n or 'sugerido' in n or 'precio venta' in n:
                col_map['precio_sugerido'] = original
            elif 'arreglo' in n or 'reparacion' in n:
                col_map['arreglos'] = original
            elif 'proveedor' in n or 'cliente' in n:
                col_map['proveedor'] = original
            elif 'sede' in n or 'sucursal' in n or 'branch' in n:
                col_map['sede'] = original
            elif 'observacion' in n or 'detalle' in n:
                col_map['observaciones'] = original

        if 'imei1' not in col_map or 'modelo' not in col_map:
            flash("El archivo debe contener al menos las columnas 'modelo' y 'imei1' (o serial).", 'danger')
            return redirect(url_for('retomas_bp.importar_masivo'))

        df = df.fillna('')

        todas_sucursales = Branch.query.filter_by(activa=True).all()
        branch_by_name = {b.nombre.strip().lower(): b for b in todas_sucursales}
        branch_by_code = {b.codigo.strip().lower(): b for b in todas_sucursales if b.codigo}
        branch_by_id = {b.id: b for b in todas_sucursales}
        default_branch = branch_by_id.get(default_branch_id) or (todas_sucursales[0] if todas_sucursales else None)

        todos_asesores = Asesor.query.filter_by(activo=True).all()
        asesor_by_code = {}
        asesor_by_id_map = {}
        for a in todos_asesores:
            asesor_by_id_map[str(a.id)] = a
            if a.codigo:
                cod_clean = a.codigo.strip().upper()
                asesor_by_code[cod_clean] = a
                # Fallback con ceros a la izquierda y sin ceros si el código es numérico
                if cod_clean.isdigit():
                    num_val = int(cod_clean)
                    asesor_by_code[str(num_val)] = a
                    asesor_by_code[str(num_val).zfill(3)] = a
                    asesor_by_code[str(num_val).zfill(2)] = a
            asesor_by_code[f"ASE-{a.id:03d}"] = a
            asesor_by_code[f"ASE-{a.id}"] = a

        def limpiar_texto(val):
            if val is None:
                return ''
            s = str(val).strip()
            if s.endswith('.0'):
                s = s[:-2].strip()
            return s

        def es_vacio(val):
            if val is None:
                return True
            s = str(val).strip().lower()
            return s in ('', 'nan', 'none', 'null', 'n/a', 'na')

        def limpiar_monto(val):
            if es_vacio(val):
                return Decimal('0.00')
            s = str(val).replace('$', '').replace(',', '').replace(' ', '').strip()
            try:
                return Decimal(s)
            except:
                return Decimal('0.00')

        filas_procesadas = []
        alertas = []
        vistos_archivo = set()
        resumen_asesores = {}
        resumen_sedes = {}
        total_costo = Decimal('0.00')

        for idx, row in df.iterrows():
            fila_num = idx + 2
            
            # 1. Serial / IMEI 1 preservando formato exacto de texto
            raw_imei1 = limpiar_texto(row[col_map['imei1']])
            
            if es_vacio(raw_imei1):
                alertas.append({'fila': fila_num, 'tipo': 'danger', 'msg': 'Fila omitida por IMEI1/Serial vacío.'})
                continue

            if raw_imei1 in vistos_archivo:
                alertas.append({'fila': fila_num, 'tipo': 'danger', 'msg': f'Serial/IMEI "{raw_imei1}" duplicado dentro del mismo archivo.'})
                continue
            vistos_archivo.add(raw_imei1)

            # Validar que no esté activo en Product con stock > 0
            prod_activo = Product.query.filter(Product.imei == raw_imei1, Product.cantidad_stock > 0).first()
            if prod_activo:
                alertas.append({'fila': fila_num, 'tipo': 'danger', 'msg': f'El serial "{raw_imei1}" ya está activo en inventario con stock ({prod_activo.nombre}).'})
                continue

            modelo = str(row[col_map['modelo']]).strip()
            marca = str(row.get(col_map.get('marca', ''), '')).strip()
            almacenamiento = str(row.get(col_map.get('almacenamiento', ''), '')).strip()
            color = str(row.get(col_map.get('color', ''), '')).strip()
            
            raw_bat = str(row.get(col_map.get('bateria', ''), '')).strip()
            bateria = raw_bat
            if raw_bat:
                try:
                    num_bat = float(raw_bat.replace('%', ''))
                    if 0 < num_bat <= 1.0:
                        bateria = f"{int(num_bat * 100)}%"
                    else:
                        bateria = f"{int(num_bat)}%"
                except:
                    bateria = raw_bat

            raw_imei2 = limpiar_texto(row.get(col_map.get('imei2', ''), ''))

            # 3. Asesor con normalización segura y fallback zfill(3)
            raw_asesor = limpiar_texto(row.get(col_map.get('codigo_asesor', ''), ''))
            asesor_obj = None
            asesor_nombre = "Sin asesor / Sin comisión"
            asesor_id = None

            if not es_vacio(raw_asesor):
                cod_lookup = raw_asesor.upper()
                asesor_obj = asesor_by_code.get(cod_lookup)
                
                # Fallback con relleno de ceros zfill(3) si viene sin ceros (ej. "4" -> "004")
                if not asesor_obj and raw_asesor.isdigit():
                    num_int_str = str(int(raw_asesor))
                    asesor_obj = asesor_by_code.get(raw_asesor.zfill(3)) or \
                                 asesor_by_code.get(raw_asesor.zfill(2)) or \
                                 asesor_by_code.get(f"ASE-{raw_asesor.zfill(3)}") or \
                                 asesor_by_id_map.get(num_int_str)

                if asesor_obj:
                    asesor_nombre = asesor_obj.nombre
                    asesor_id = asesor_obj.id
                else:
                    asesor_nombre = f"Código '{raw_asesor}' no encontrado"
                    alertas.append({
                        'fila': fila_num, 
                        'tipo': 'warning', 
                        'msg': f'Código de asesor "{raw_asesor}" no encontrado en asesores activos. Quedará sin comisión de recepción a menos que se corrija.'
                    })
            else:
                # Si viene vacío/None/NaN: No es un error ni una alerta bloqueante
                raw_asesor = None

            resumen_asesores[asesor_nombre] = resumen_asesores.get(asesor_nombre, 0) + 1

            # 4. Sede
            raw_sede = limpiar_texto(row.get(col_map.get('sede', ''), ''))
            branch_obj = None
            if raw_sede:
                s_lower = raw_sede.lower()
                branch_obj = branch_by_code.get(s_lower) or branch_by_name.get(s_lower)
                if not branch_obj and raw_sede.isdigit():
                    branch_obj = branch_by_id.get(int(raw_sede))

            if not branch_obj:
                branch_obj = default_branch

            branch_id = branch_obj.id if branch_obj else 1
            branch_nom = branch_obj.nombre if branch_obj else 'Principal'
            resumen_sedes[branch_nom] = resumen_sedes.get(branch_nom, 0) + 1

            # Costos y Precios
            v_ret = limpiar_monto(row.get(col_map.get('valor_retoma', ''), 0))
            v_arr = limpiar_monto(row.get(col_map.get('arreglos', ''), 0))
            p_sug = limpiar_monto(row.get(col_map.get('precio_sugerido', ''), 0))
            p_min = limpiar_monto(row.get(col_map.get('precio_minimo', ''), 0))

            costo_total = v_ret + v_arr
            if p_sug <= 0:
                p_sug = (costo_total * Decimal('1.30')).quantize(Decimal('1'))
            if p_min <= 0:
                p_min = (costo_total * Decimal('1.15')).quantize(Decimal('1'))

            total_costo += v_ret

            proveedor = str(row.get(col_map.get('proveedor', ''), '')).strip() or 'Cliente'
            observaciones = str(row.get(col_map.get('observaciones', ''), '')).strip()

            nombre_producto = f"{marca} {modelo} {almacenamiento}".strip()
            if not nombre_producto:
                nombre_producto = f"Equipo {raw_imei1}"

            filas_procesadas.append({
                'fila': fila_num,
                'codigo_asesor': raw_asesor,
                'asesor_id': asesor_id,
                'asesor_nombre': asesor_nombre,
                'marca': marca,
                'modelo': modelo,
                'almacenamiento': almacenamiento,
                'nombre_producto': nombre_producto,
                'imei1': raw_imei1,
                'imei2': raw_imei2 or None,
                'color': color or None,
                'bateria': bateria or None,
                'valor_retoma': float(v_ret),
                'arreglos': float(v_arr),
                'precio_minimo': float(p_min),
                'precio_sugerido': float(p_sug),
                'proveedor': proveedor,
                'branch_id': branch_id,
                'branch_nombre': branch_nom,
                'observaciones': observaciones
            })

        if not filas_procesadas:
            flash('No se encontraron filas válidas para procesar.', 'danger')
            return redirect(url_for('retomas_bp.importar_masivo'))

        # Guardar en archivo temporal en disco (evita exceder el límite de cookie de Nginx 502 Bad Gateway)
        session.pop('import_retomas_preview', None)
        preview_token = str(uuid.uuid4())
        tmp_dir = os.path.join(current_app.instance_path, 'tmp_retomas_preview')
        os.makedirs(tmp_dir, exist_ok=True)
        tmp_path = os.path.join(tmp_dir, f'{preview_token}.json')
        with open(tmp_path, 'w', encoding='utf-8') as tf:
            json.dump({
                'archivo_nombre': file.filename,
                'filas': filas_procesadas,
                'default_branch_id': default_branch_id,
                'total_costo': float(total_costo),
                'resumen_asesores': resumen_asesores
            }, tf, ensure_ascii=False)

        return render_template('retomas/importar_masivo_preview.html',
                               preview_token=preview_token,
                               archivo_nombre=file.filename,
                               filas=filas_procesadas,
                               total_equipos=len(filas_procesadas),
                               total_costo=total_costo,
                               resumen_asesores=resumen_asesores,
                               resumen_sedes=resumen_sedes,
                               alertas=alertas)

    except Exception as e:
        flash(f'Error procesando el archivo: {str(e)}', 'danger')
        return redirect(url_for('retomas_bp.importar_masivo'))


@retomas_bp.route('/importar_masivo/ejecutar', methods=['POST'])
@login_required
@admin_required
def importar_masivo_ejecutar():
    preview_token = (request.form.get('preview_token') or '').strip()
    if not preview_token or not re.match(r'^[a-f0-9\-]+$', preview_token):
        flash('Sesión de carga inválida o expirada. Por favor sube el archivo nuevamente.', 'warning')
        return redirect(url_for('retomas_bp.importar_masivo'))

    tmp_path = os.path.join(current_app.instance_path, 'tmp_retomas_preview', f'{preview_token}.json')
    if not os.path.exists(tmp_path):
        flash('No hay datos en espera de confirmación o el archivo temporal expiró. Por favor sube el archivo nuevamente.', 'warning')
        return redirect(url_for('retomas_bp.importar_masivo'))

    try:
        with open(tmp_path, 'r', encoding='utf-8') as tf:
            preview_data = json.load(tf)
    except Exception:
        flash('Error leyendo los datos temporales de carga. Por favor sube el archivo nuevamente.', 'danger')
        return redirect(url_for('retomas_bp.importar_masivo'))

    if not preview_data or not preview_data.get('filas'):
        flash('No hay datos en espera de confirmación. Por favor sube el archivo nuevamente.', 'warning')
        return redirect(url_for('retomas_bp.importar_masivo'))

    filas = preview_data['filas']
    archivo_nombre = preview_data.get('archivo_nombre', 'importacion_masiva.xlsx')
    resumen_asesores = preview_data.get('resumen_asesores', {})
    batch_code = f"BATCH-RET-{datetime.now().strftime('%Y%m%d%H%M%S')}"

    from services.stock_service import get_or_create_branch_stock, sync_global_product_stock

    retomas_creadas_ids = []
    productos_creados_ids = []
    total_costo_lote = Decimal('0.00')
    primary_branch_id = filas[0]['branch_id'] if filas else (current_user.branch_id or 1)

    try:
        for f in filas:
            val_ret = Decimal(str(f['valor_retoma']))
            arr_val = Decimal(str(f['arreglos']))
            costo_total = val_ret + arr_val
            p_min = Decimal(str(f['precio_minimo']))
            p_sug = Decimal(str(f['precio_sugerido']))
            total_costo_lote += val_ret

            # 1. Crear Retoma en estado 'aprobado'
            nueva_retoma = Retoma(
                sale_id=None,
                modelo=f['modelo'],
                marca=f['marca'],
                proveedor=f['proveedor'],
                valor_retoma=val_ret,
                arreglos=arr_val,
                imei1=f['imei1'],
                imei2=f['imei2'],
                color=f['color'],
                bateria=f['bateria'],
                memoria=f['almacenamiento'],
                observaciones=f"{f['observaciones']} [Lote: {batch_code}]".strip(),
                estado='aprobado',
                ok_contabilidad=True,
                ok_venta=True,
                vendedor_id=current_user.id,
                branch_id=f['branch_id'],
                asesor_retoma_id=f['asesor_id']
            )
            db.session.add(nueva_retoma)
            db.session.flush()

            # 2. Crear Product en estado 'Usado' y tipo_inventario 'celulares'
            nuevo_sku = f"RET-{nueva_retoma.id}-{datetime.now().strftime('%Y%m%d%H%M%S%f')[:22]}"
            nuevo_prod = Product(
                nombre=f['nombre_producto'],
                sku=nuevo_sku,
                tipo_inventario='celulares',
                estado_celular='Usado',
                cantidad_stock=0,
                precio_costo=costo_total,
                precio_minimo=p_min,
                precio_sugerido=p_sug,
                observacion=f"Carga Masiva Retoma [{batch_code}]. {f['observaciones']}".strip(),
                imei=f['imei1'],
                imei2=f['imei2'],
                color=f['color'],
                bateria=f['bateria'],
                memoria=f['almacenamiento'],
                proveedor=f['proveedor'],
                marca=f['marca'],
                modelo_celular=f['modelo'],
                inventario=f['branch_nombre'].upper()
            )
            db.session.add(nuevo_prod)
            db.session.flush()

            # 3. Enlazar Retoma con Producto
            nueva_retoma.producto_generado_id = nuevo_prod.id

            # 4. Asignar stock en BranchStock y sincronizar global
            b_stock = get_or_create_branch_stock(f['branch_id'], nuevo_prod.id, None, for_update=True)
            stock_ant = b_stock.cantidad
            b_stock.cantidad += 1
            sync_global_product_stock(nuevo_prod.id, None)

            # 5. Registro de ajuste / auditoría de stock
            ajuste = StockAdjustment(
                product_id=nuevo_prod.id,
                admin_id=current_user.id,
                branch_id=f['branch_id'],
                tipo_movimiento=f"INGRESO_RETOMA_LOTE ({batch_code} en {f['branch_nombre']})",
                stock_anterior=stock_ant,
                stock_nuevo=b_stock.cantidad
            )
            db.session.add(ajuste)

            retomas_creadas_ids.append(nueva_retoma.id)
            productos_creados_ids.append(nuevo_prod.id)

        # 6. Registrar el Lote en RetomaImportBatch
        batch = RetomaImportBatch(
            batch_code=batch_code,
            user_id=current_user.id,
            branch_id=primary_branch_id,
            total_equipos=len(retomas_creadas_ids),
            total_costo=total_costo_lote,
            estado='COMPLETADO',
            archivo_nombre=archivo_nombre,
            detalles_json=json.dumps({
                'retoma_ids': retomas_creadas_ids,
                'product_ids': productos_creados_ids,
                'resumen_asesores': resumen_asesores
            })
        )
        db.session.add(batch)

        # 7. Auditoría global
        AuditLog.registrar(
            action='IMPORTACION_MASIVA_RETOMAS',
            user_id=current_user.id,
            motivo=f'Carga masiva de {len(retomas_creadas_ids)} retomas directas a inventario ({batch_code})',
            target_id=batch.id,
            target_type='RETOMA_BATCH',
            detalles=f'Archivo: {archivo_nombre}. Total costo: ${total_costo_lote:,.2f}'
        )

        db.session.commit()
        session.pop('import_retomas_preview', None)
        try:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)
        except Exception:
            pass

        flash(f'¡Carga masiva exitosa! Se importaron y pusieron a la venta {len(retomas_creadas_ids)} equipos de retoma bajo el lote {batch_code}.', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Error ejecutando la carga masiva: {str(e)}', 'danger')

    return redirect(url_for('retomas_bp.importar_masivo'))


@retomas_bp.route('/importar_masivo/deshacer/<int:batch_id>', methods=['POST'])
@login_required
@admin_required
def importar_masivo_deshacer(batch_id):
    batch = RetomaImportBatch.query.get_or_404(batch_id)

    if batch.estado == 'REVERTIDO':
        flash('Este lote ya se encuentra revertido.', 'warning')
        return redirect(url_for('retomas_bp.importar_masivo'))

    detalles = {}
    try:
        detalles = json.loads(batch.detalles_json or '{}')
    except:
        pass

    retoma_ids = detalles.get('retoma_ids', [])
    product_ids = detalles.get('product_ids', [])

    if not product_ids and not retoma_ids:
        flash('No se encontraron registros asociados a este lote.', 'danger')
        return redirect(url_for('retomas_bp.importar_masivo'))

    # 1. Validar si alguno ya fue vendido
    vendidos = []
    for pid in product_ids:
        detalle = SaleDetail.query.filter_by(product_id=pid).first()
        if detalle:
            prod = Product.query.get(pid)
            nombre_p = prod.nombre if prod else f'Producto #{pid}'
            imei_p = prod.imei if prod else 'N/A'
            vendidos.append(f"{nombre_p} (Serial: {imei_p}, Venta #{detalle.sale_id})")

    if vendidos:
        msg = f"No es posible revertir el lote {batch.batch_code} porque ya registra {len(vendidos)} venta(s): " + ", ".join(vendidos[:3])
        if len(vendidos) > 3:
            msg += f" y {len(vendidos)-3} más."
        flash(msg, 'danger')
        return redirect(url_for('retomas_bp.importar_masivo'))

    # 2. Eliminación atómica segura
    try:
        # Eliminar stocks y movimientos
        BranchStock.query.filter(BranchStock.product_id.in_(product_ids)).delete(synchronize_session=False)
        StockAdjustment.query.filter(StockAdjustment.product_id.in_(product_ids)).delete(synchronize_session=False)

        # Desvincular de retomas y eliminar retomas
        Retoma.query.filter(Retoma.id.in_(retoma_ids)).delete(synchronize_session=False)

        # Eliminar productos
        Product.query.filter(Product.id.in_(product_ids)).delete(synchronize_session=False)

        batch.estado = 'REVERTIDO'
        batch.fecha_reversion = obtener_hora_bogota()

        AuditLog.registrar(
            action='DESHACER_LOTE_RETOMAS',
            user_id=current_user.id,
            motivo=f'Rollback exitoso de lote {batch.batch_code}',
            target_id=batch.id,
            target_type='RETOMA_BATCH',
            detalles=f'Se eliminaron {len(retoma_ids)} retomas y {len(product_ids)} productos de inventario sin ventas.'
        )

        db.session.commit()
        flash(f'Lote {batch.batch_code} revertido exitosamente. Se eliminaron los {len(product_ids)} equipos de inventario y retomas de forma limpia.', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Error al deshacer el lote: {str(e)}', 'danger')

    return redirect(url_for('retomas_bp.importar_masivo'))
