from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify, session
from flask_login import login_required, current_user
from models import db, Technician, TechnicalService, Product, Warranty, Branch, AuditLog
from datetime import datetime, date
import pytz

support_bp = Blueprint('support_bp', __name__)

TIPOS_ARREGLO = [
    'Cambio de Pantalla / Display',
    'Cambio de Batería',
    'Pin de Carga / Puerto USB',
    'Cámara Frontal / Trasera',
    'Micrófono / Altavoz / Auricular',
    'Tapa Trasera / Carcasa / Chasis',
    'Reparación de Placa / Corto / IC',
    'Falla de Señal / Antena / Baseband',
    'Software / Flasheo / Reinstalación',
    'Mantenimiento / Limpieza / Humedad',
    'Botones / Flex de Encendido o Volumen',
    'Diagnóstico General / Revisión'
]

def obtener_hora_bogota():
    tz = pytz.timezone('America/Bogota')
    return datetime.now(tz)

@support_bp.route('/')
@login_required
def index():
    """Tablero principal de Soporte Técnico."""
    filtro_origen = request.args.get('origen', '').strip() # 'INVENTARIO', 'GARANTIA' o vacío
    filtro_tecnico = request.args.get('tecnico_id', type=int)
    filtro_tipo = request.args.get('tipo_arreglo', '').strip()
    filtro_estado = request.args.get('estado', '').strip() # 'EN_REVISION', 'EN_REPARACION', 'REPARADO', etc.
    q = request.args.get('q', '').strip()

    query = TechnicalService.query

    # Restricción por sucursal (para vendedores)
    if current_user.rol == 'vendedor':
        if current_user.branch_id:
            query = query.filter(TechnicalService.branch_id == current_user.branch_id)
    else:
        active_b_id = session.get('active_branch_id')
        if active_b_id:
            query = query.filter(TechnicalService.branch_id == int(active_b_id))

    # Filtros avanzados
    if filtro_origen:
        query = query.filter(TechnicalService.origen == filtro_origen)
    if filtro_tecnico:
        query = query.filter(TechnicalService.technician_id == filtro_tecnico)
    if filtro_tipo:
        query = query.filter(TechnicalService.tipo_arreglo == filtro_tipo)
    if filtro_estado:
        query = query.filter(TechnicalService.estado == filtro_estado)
    if q:
        query = query.filter(
            db.or_(
                TechnicalService.imei.ilike(f'%{q}%'),
                TechnicalService.modelo.ilike(f'%{q}%'),
                TechnicalService.marca.ilike(f'%{q}%'),
                TechnicalService.motivo_falla.ilike(f'%{q}%')
            )
        )

    servicios = query.order_by(TechnicalService.fecha_ingreso.desc()).all()
    tecnicos = Technician.query.order_by(Technician.nombre.asc()).all()

    # Conteos rápidos para badges de estados
    base_counts = TechnicalService.query
    if current_user.rol == 'vendedor' and current_user.branch_id:
        base_counts = base_counts.filter(TechnicalService.branch_id == current_user.branch_id)
    elif session.get('active_branch_id'):
        base_counts = base_counts.filter(TechnicalService.branch_id == int(session.get('active_branch_id')))

    en_taller_count = base_counts.filter(TechnicalService.estado.in_(['EN_REVISION', 'EN_REPARACION'])).count()
    reparados_count = base_counts.filter(TechnicalService.estado == 'REPARADO').count()
    inventario_count = base_counts.filter(TechnicalService.origen == 'INVENTARIO').count()
    garantia_count = base_counts.filter(TechnicalService.origen == 'GARANTIA').count()

    return render_template(
        'support/index.html',
        servicios=servicios,
        tecnicos=tecnicos,
        tipos_arreglo=TIPOS_ARREGLO,
        filtro_origen=filtro_origen,
        filtro_tecnico=filtro_tecnico,
        filtro_tipo=filtro_tipo,
        filtro_estado=filtro_estado,
        q=q,
        en_taller_count=en_taller_count,
        reparados_count=reparados_count,
        inventario_count=inventario_count,
        garantia_count=garantia_count
    )

@support_bp.route('/tecnicos', methods=['POST'])
@login_required
def crear_tecnico():
    """Crear o registrar un técnico / taller externo."""
    if current_user.rol not in ['admin', 'bodega', 'vendedor', 'vendedor_bodega']:
        flash('No tienes permisos para crear técnicos.', 'danger')
        return redirect(url_for('support_bp.index'))

    nombre = request.form.get('nombre', '').strip()
    telefono = request.form.get('telefono', '').strip()
    especialidad = request.form.get('especialidad', '').strip()
    direccion_taller = request.form.get('direccion_taller', '').strip()

    if not nombre:
        flash('El nombre del técnico o taller es obligatorio.', 'warning')
        return redirect(url_for('support_bp.index'))

    nuevo_tecnico = Technician(
        nombre=nombre,
        telefono=telefono,
        especialidad=especialidad,
        direccion_taller=direccion_taller,
        activo=True
    )
    db.session.add(nuevo_tecnico)
    db.session.commit()

    AuditLog.registrar(
        action='CREAR_TECNICO',
        user_id=current_user.id,
        motivo=f'Registro de nuevo técnico {nombre}',
        target_id=nuevo_tecnico.id,
        target_type='TECHNICIAN'
    )

    flash(f'Técnico "{nombre}" creado con éxito.', 'success')
    return redirect(url_for('support_bp.index'))

@support_bp.route('/enviar_desde_inventario/<int:product_id>', methods=['POST'])
@login_required
def enviar_desde_inventario(product_id):
    """Envía un celular del inventario directo a soporte técnico."""
    producto = Product.query.get_or_404(product_id)

    if producto.tipo_inventario != 'celulares':
        flash('Solo se pueden enviar celulares al soporte técnico.', 'danger')
        return redirect(url_for('celulares_bp.inventario'))

    technician_id = request.form.get('technician_id', type=int)
    tipo_arreglo = request.form.get('tipo_arreglo', '').strip() or 'Diagnóstico General / Revisión'
    motivo_falla = request.form.get('motivo_falla', '').strip()
    fecha_estimada_str = request.form.get('fecha_estimada', '').strip()

    if not motivo_falla:
        flash('Debe especificar el motivo o falla que presenta el equipo.', 'warning')
        return redirect(url_for('celulares_bp.inventario'))

    fecha_estimada = None
    if fecha_estimada_str:
        try:
            fecha_estimada = datetime.strptime(fecha_estimada_str, '%Y-%m-%d').date()
        except ValueError:
            pass

    # Sucursal actual del usuario o seleccionada
    branch_id = current_user.branch_id
    if not branch_id:
        active_b = session.get('active_branch_id')
        branch_id = int(active_b) if active_b else None

    # Crear la orden de servicio técnico
    servicio = TechnicalService(
        origen='INVENTARIO',
        product_id=producto.id,
        branch_id=branch_id,
        technician_id=technician_id,
        created_by_id=current_user.id,
        marca=producto.marca,
        modelo=producto.modelo_celular or producto.nombre,
        imei=producto.imei,
        color=producto.color,
        motivo_falla=motivo_falla,
        tipo_arreglo=tipo_arreglo,
        estado='EN_REVISION',
        fecha_estimada=fecha_estimada
    )
    db.session.add(servicio)

    # Nota en observaciones del producto para alertar en inventario
    producto.observacion = f"[EN TALLER / SOPORTE TÉCNICO]: {motivo_falla} | Falla: {tipo_arreglo}"
    db.session.commit()

    AuditLog.registrar(
        action='ENVIO_SOPORTE_INVENTARIO',
        user_id=current_user.id,
        motivo=f'Envío de celular IMEI {producto.imei} a soporte técnico por {tipo_arreglo}',
        target_id=servicio.id,
        target_type='TECHNICAL_SERVICE'
    )

    flash(f'Celular {producto.modelo_celular or producto.nombre} (IMEI: {producto.imei}) enviado exitosamente a Soporte Técnico.', 'success')
    return redirect(url_for('support_bp.index'))

@support_bp.route('/enviar_desde_garantia/<int:warranty_id>', methods=['POST'])
@login_required
def enviar_desde_garantia(warranty_id):
    """Envía un equipo con garantía radicada al taller de soporte técnico."""
    garantia = Warranty.query.get_or_404(warranty_id)

    technician_id = request.form.get('technician_id', type=int)
    tipo_arreglo = request.form.get('tipo_arreglo', '').strip() or 'Garantía / Reparación de Falla'
    motivo_falla = request.form.get('motivo_falla', '').strip() or (garantia.motivo_reportado or garantia.reason)
    fecha_estimada_str = request.form.get('fecha_estimada', '').strip()

    fecha_estimada = None
    if fecha_estimada_str:
        try:
            fecha_estimada = datetime.strptime(fecha_estimada_str, '%Y-%m-%d').date()
        except ValueError:
            pass

    # Datos del celular asociado a la garantía
    prod = garantia.product
    imei = prod.imei if (prod and prod.imei) else None
    marca = prod.marca if prod else 'N/A'
    modelo = prod.modelo_celular if prod else (garantia.nombre_manual or (prod.nombre if prod else 'Equipo Garantía'))
    color = prod.color if prod else None

    servicio = TechnicalService(
        origen='GARANTIA',
        warranty_id=garantia.id,
        product_id=prod.id if prod else None,
        branch_id=garantia.branch_id,
        technician_id=technician_id,
        created_by_id=current_user.id,
        marca=marca,
        modelo=modelo,
        imei=imei,
        color=color,
        motivo_falla=motivo_falla,
        tipo_arreglo=tipo_arreglo,
        estado='EN_REVISION',
        fecha_estimada=fecha_estimada
    )
    db.session.add(servicio)

    garantia.admin_notes = f"[EN TALLER TÉCNICO]: Asignado para reparación de {tipo_arreglo}."
    db.session.commit()

    AuditLog.registrar(
        action='ENVIO_SOPORTE_GARANTIA',
        user_id=current_user.id,
        motivo=f'Garantía #{garantia.id} enviada a soporte técnico por {tipo_arreglo}',
        target_id=servicio.id,
        target_type='TECHNICAL_SERVICE'
    )

    flash(f'Garantía #{garantia.id} derivada exitosamente al módulo de Soporte Técnico.', 'success')
    return redirect(url_for('support_bp.index'))

@support_bp.route('/actualizar_estado/<int:id>', methods=['POST'])
@login_required
def actualizar_estado(id):
    """Actualiza estado, diagnóstico, solución y costo de un servicio técnico."""
    servicio = TechnicalService.query.get_or_404(id)

    nuevo_estado = request.form.get('estado', '').strip()
    diagnostico = request.form.get('diagnostico_tecnico', '').strip()
    solucion = request.form.get('solucion_aplicada', '').strip()
    costo_str = request.form.get('costo_reparacion', '').strip()
    technician_id = request.form.get('technician_id', type=int)

    if nuevo_estado:
        servicio.estado = nuevo_estado
    if diagnostico:
        servicio.diagnostico_tecnico = diagnostico
    if solucion:
        servicio.solucion_aplicada = solucion
    if technician_id:
        servicio.technician_id = technician_id
    if costo_str:
        try:
            servicio.costo_reparacion = float(costo_str.replace(',', '').replace('$', '').strip())
        except ValueError:
            pass

    if nuevo_estado in ['REPARADO', 'ENTREGADO', 'NO_REPARABLE']:
        servicio.fecha_salida = obtener_hora_bogota()
        servicio.resolved_by_id = current_user.id

        # Si viene de inventario y fue reparado, limpiar la observación de taller
        if servicio.origen == 'INVENTARIO' and servicio.producto:
            if nuevo_estado == 'REPARADO':
                servicio.producto.observacion = f"[REPARADO EN TALLER {datetime.now().strftime('%d/%m/%Y')}]: {solucion or 'Listo para la venta'}"
        
        # Si viene de garantía y fue reparado, reflejar en garantía
        if servicio.origen == 'GARANTIA' and servicio.garantia:
            if nuevo_estado == 'REPARADO':
                servicio.garantia.admin_notes = f"[REPARADO EN SOPORTE TÉCNICO]: {solucion or 'Listo para entrega al cliente'}"

    db.session.commit()

    AuditLog.registrar(
        action='ACTUALIZAR_SOPORTE',
        user_id=current_user.id,
        motivo=f'Actualización de servicio #{servicio.id} a estado {nuevo_estado}',
        target_id=servicio.id,
        target_type='TECHNICAL_SERVICE'
    )

    flash('Servicio técnico actualizado correctamente.', 'success')
    return redirect(url_for('support_bp.index'))

