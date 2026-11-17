from flask import Blueprint, request, jsonify
from flask_login import login_required, current_user
from models import db, PriceApproval, Product, obtener_hora_bogota

approvals_bp = Blueprint('approvals_bp', __name__)

@approvals_bp.route('/api/precio/solicitar', methods=['POST'])
@login_required
def solicitar_aprobacion():
    """
    Crea una solicitud de aprobación de precio por debajo del mínimo sugerido.
    """
    data = request.get_json()
    product_id = data.get('product_id')
    variant_id = data.get('variant_id') # opcional
    precio_original = data.get('precio_original')
    precio_solicitado = data.get('precio_solicitado')

    if not product_id or precio_original is None or precio_solicitado is None:
        return jsonify({'error': 'Faltan datos obligatorios para la solicitud.'}), 400

    # Cancelar solicitudes previas pendientes del mismo vendedor para el mismo producto/variante
    pendientes = PriceApproval.query.filter_by(
        vendedor_id=current_user.id,
        product_id=product_id,
        variant_id=variant_id,
        estado='pendiente'
    ).all()
    
    for p in pendientes:
        p.estado = 'cancelada'
    
    # Crear nueva solicitud
    nueva = PriceApproval(
        vendedor_id=current_user.id,
        product_id=product_id,
        variant_id=variant_id,
        precio_original=precio_original,
        precio_solicitado=precio_solicitado,
        estado='pendiente'
    )
    db.session.add(nueva)
    db.session.commit()

    return jsonify({'success': True, 'solicitud_id': nueva.id, 'mensaje': 'Solicitud enviada al administrador.'})

@approvals_bp.route('/api/precio/estado/<int:id>', methods=['GET'])
@login_required
def estado_aprobacion(id):
    """
    Endpoint de polling para el cajero (POS). Verifica si el admin ya resolvió la solicitud.
    """
    solicitud = PriceApproval.query.get(id)
    if not solicitud:
        return jsonify({'error': 'Solicitud no encontrada'}), 404
        
    if solicitud.vendedor_id != current_user.id and current_user.rol != 'admin':
        return jsonify({'error': 'No tienes permiso'}), 403

    return jsonify({
        'estado': solicitud.estado,
        'precio_aprobado': str(solicitud.precio_aprobado) if solicitud.precio_aprobado else None,
        'motivo_rechazo': solicitud.motivo_rechazo
    })

@approvals_bp.route('/api/aprobaciones/pendientes', methods=['GET'])
@login_required
def listar_pendientes():
    """
    Endpoint de polling para el Administrador.
    """
    if current_user.rol != 'admin':
        return jsonify({'error': 'Acceso denegado'}), 403

    pendientes = PriceApproval.query.filter_by(estado='pendiente').order_by(PriceApproval.fecha_solicitud.asc()).all()
    
    resultados = []
    for p in pendientes:
        resultados.append({
            'id': p.id,
            'vendedor': p.vendedor.nombre if p.vendedor else 'Desconocido',
            'producto': p.product.nombre if p.product else 'Producto N/A',
            'precio_original': str(p.precio_original),
            'precio_solicitado': str(p.precio_solicitado),
            'fecha_solicitud': p.fecha_solicitud.strftime('%H:%M:%S')
        })

    return jsonify({'pendientes': resultados})

@approvals_bp.route('/api/aprobaciones/<int:id>/aprobar', methods=['POST'])
@login_required
def aprobar_solicitud(id):
    if current_user.rol != 'admin':
        return jsonify({'error': 'Acceso denegado'}), 403

    solicitud = PriceApproval.query.get(id)
    if not solicitud or solicitud.estado != 'pendiente':
        return jsonify({'error': 'Solicitud no válida o ya fue procesada'}), 400

    data = request.get_json() or {}
    precio_aprobado = data.get('precio_aprobado')
    
    if precio_aprobado is None or precio_aprobado == '':
        precio_aprobado = solicitud.precio_solicitado
        
    solicitud.precio_aprobado = precio_aprobado
    solicitud.estado = 'aprobado'
    solicitud.admin_id = current_user.id
    solicitud.fecha_resolucion = obtener_hora_bogota()

    from models import AuditLog
    AuditLog.registrar(
        action='APROBACION_PRECIO_MINIMO',
        user_id=current_user.id,
        motivo=f'Aprobación de precio especial ${float(precio_aprobado):,.2f} (Precio Mínimo: ${float(solicitud.precio_minimo):,.2f}) para "{solicitud.producto.nombre if solicitud.producto else "Producto"}". Solicitado por: {solicitud.vendedor.nombre if solicitud.vendedor else "Asesor"}',
        target_id=solicitud.id,
        target_type='DISCOUNT_APPROVAL'
    )
    db.session.commit()

    return jsonify({'success': True, 'mensaje': 'Aprobada'})

@approvals_bp.route('/api/aprobaciones/<int:id>/rechazar', methods=['POST'])
@login_required
def rechazar_solicitud(id):
    if current_user.rol != 'admin':
        return jsonify({'error': 'Acceso denegado'}), 403

    solicitud = PriceApproval.query.get(id)
    if not solicitud or solicitud.estado != 'pendiente':
        return jsonify({'error': 'Solicitud no válida o ya fue procesada'}), 400

    data = request.get_json() or {}
    motivo = data.get('motivo', 'Precio no autorizado.')

    solicitud.estado = 'rechazado'
    solicitud.motivo_rechazo = motivo
    solicitud.admin_id = current_user.id
    solicitud.fecha_resolucion = obtener_hora_bogota()

    from models import AuditLog
    AuditLog.registrar(
        action='RECHAZO_PRECIO_MINIMO',
        user_id=current_user.id,
        motivo=f'Rechazo de descuento para "{solicitud.producto.nombre if solicitud.producto else "Producto"}". Motivo: {motivo}',
        target_id=solicitud.id,
        target_type='DISCOUNT_APPROVAL'
    )
    db.session.commit()

    return jsonify({'success': True, 'mensaje': 'Rechazada'})
