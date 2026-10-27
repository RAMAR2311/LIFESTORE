from flask import Blueprint, render_template, request, jsonify, redirect, url_for, flash, session
from flask_login import login_required, current_user
from models import db, Sale, SaleDetail, Warranty, Product, SaleClient, Branch

warranties_bp = Blueprint('warranties_bp', __name__)

@warranties_bp.route('/')
@login_required
def index():
    if current_user.rol not in ['admin', 'vendedor', 'bodega']:
        flash('Acceso denegado.', 'danger')
        return redirect(url_for('index'))
    
    query = Warranty.query
    
    # Restricción de Sucursales:
    # Vendedor solo ve las garantías radicadas en su sucursal
    if current_user.rol == 'vendedor':
        if current_user.branch_id:
            query = query.filter(Warranty.branch_id == current_user.branch_id)
    else:
        # Admin y Bodega: si seleccionaron una sucursal en el switcher global, filtrar por esa sucursal
        active_b_id = session.get('active_branch_id')
        if active_b_id:
            query = query.filter(Warranty.branch_id == int(active_b_id))

    from models import Technician
    tecnicos_disponibles = Technician.query.filter_by(activo=True).order_by(Technician.nombre.asc()).all()
    warranties = query.order_by(Warranty.created_at.desc()).all()
    return render_template('warranties/index.html', warranties=warranties, tecnicos_disponibles=tecnicos_disponibles)

@warranties_bp.route('/api/search', methods=['GET'])
@login_required
def search_sale():
    query = request.args.get('q', '').strip()
    if not query:
        return jsonify({'success': False, 'message': 'Escribe un término de búsqueda.'})

    sale = None
    
    # 1. Intentar buscar por ID de Factura (número exacto)
    if query.isdigit():
        sale = Sale.query.get(int(query))

    # 2. Si no se encontró, buscar por Cédula de cliente
    if not sale:
        client = SaleClient.query.filter_by(documento=query).order_by(SaleClient.id.desc()).first()
        if client:
            sale = client.venta

    # 3. Si no se encontró, buscar por IMEI en SaleDetail
    if not sale:
        detail = SaleDetail.query.join(Product).filter(
            db.or_(
                Product.imei == query,
                Product.imei2 == query,
                SaleDetail.nombre_manual.ilike(f'%{query}%')
            )
        ).order_by(SaleDetail.id.desc()).first()
        if detail:
            sale = detail.venta

    if not sale:
        return jsonify({'success': False, 'message': 'No se encontró ninguna factura asociada a ese ID, Cédula o IMEI.'})

    # Preparar detalles de la factura
    details_data = []
    for d in sale.detalles:
        details_data.append({
            'detail_id': d.id,
            'product_id': d.product_id,
            'nombre': d.nombre_manual or (d.producto.nombre if d.producto else 'Desconocido'),
            'cantidad': d.cantidad_vendida,
            'precio': str(d.precio_venta_final)
        })

    client_doc = sale.cliente.documento if sale.cliente else 'N/A'
    client_name = sale.cliente.nombre if sale.cliente else 'N/A'
    sucursal_origen = sale.branch.nombre if getattr(sale, 'branch', None) else (sale.sucursal or 'Principal')

    return jsonify({
        'success': True,
        'sale': {
            'id': sale.id,
            'fecha': sale.fecha_venta.strftime('%d/%m/%Y %I:%M %p'),
            'total': str(sale.monto_total),
            'cliente_doc': client_doc,
            'cliente_nombre': client_name,
            'sucursal': sucursal_origen
        },
        'details': details_data
    })

@warranties_bp.route('/nueva', methods=['POST'])
@login_required
def create_warranty():
    sale_id = request.form.get('sale_id')
    detail_index_str = request.form.get('detail_index') # formato "product_id|nombre_manual"
    reason = request.form.get('reason', '').strip()

    if not sale_id or not detail_index_str or not reason:
        flash('Todos los campos son obligatorios.', 'danger')
        return redirect(url_for('warranties_bp.index'))

    # Parse detail
    parts = detail_index_str.split('|')
    product_id_str = parts[0]
    nombre_manual = parts[1] if len(parts) > 1 else None

    product_id = int(product_id_str) if product_id_str != 'None' else None

    # Determinar la sucursal física donde se radica el reclamo
    if current_user.rol in ['vendedor', 'bodega']:
        receiving_branch_id = current_user.branch_id
        if not receiving_branch_id:
            branch_def = Branch.query.filter_by(activa=True).order_by(Branch.id.asc()).first()
            receiving_branch_id = branch_def.id if branch_def else 1
    else:
        active_b = session.get('active_branch_id')
        if active_b:
            receiving_branch_id = int(active_b)
        else:
            branch_def = Branch.query.filter_by(activa=True).order_by(Branch.id.asc()).first()
            receiving_branch_id = branch_def.id if branch_def else 1

    # Checklist inicial de recepción
    estado_estetico = request.form.get('estado_estetico', 'Bueno').strip()
    detalles_esteticos = request.form.get('detalles_esteticos', '').strip()
    porcentaje_bateria = request.form.get('porcentaje_bateria', type=int)

    warranty = Warranty()
    warranty.sale_id = sale_id
    warranty.branch_id = receiving_branch_id
    warranty.product_id = product_id
    warranty.nombre_manual = nombre_manual
    warranty.quantity = 1
    warranty.reason = reason
    warranty.motivo_reportado = reason
    warranty.recibido_por_id = current_user.id
    warranty.estado_estetico = estado_estetico
    warranty.detalles_esteticos = detalles_esteticos
    warranty.porcentaje_bateria = porcentaje_bateria
    db.session.add(warranty)
    db.session.commit()

    flash('Garantía registrada exitosamente con checklist inicial de custodia.', 'success')
    return redirect(url_for('warranties_bp.ticket', id=warranty.id))

@warranties_bp.route('/ticket/<int:id>')
@login_required
def ticket(id):
    warranty = Warranty.query.get_or_404(id)
    return render_template('warranties/ticket.html', warranty=warranty)

@warranties_bp.route('/entregar/<int:id>', methods=['POST'])
@login_required
def entregar_garantia(id):
    from models import obtener_hora_bogota, AuditLog
    warranty = Warranty.query.get_or_404(id)
    soporte = request.form.get('soporte_entrega', '').strip()
    notas = request.form.get('notas_entrega', '').strip()

    warranty.resolution = 'Entregada'
    warranty.entregado_por_id = current_user.id
    warranty.fecha_entrega = obtener_hora_bogota()
    warranty.firma_o_soporte_entrega = soporte or 'Entregado a conformidad y satisfacción del cliente'
    if notas:
        warranty.admin_notes = f"Entrega: {notas} | {warranty.admin_notes or ''}".strip()

    AuditLog.registrar(
        action='ENTREGA_GARANTIA',
        user_id=current_user.id,
        motivo=f'Entrega y liquidación física de garantía #{warranty.id}. Soporte: {warranty.firma_o_soporte_entrega}',
        target_id=warranty.id,
        target_type='WARRANTY'
    )
    db.session.commit()

    flash(f'Garantía #{warranty.id} marcada como ENTREGADA a satisfacción del cliente.', 'success')
    return redirect(url_for('warranties_bp.index'))

@warranties_bp.route('/api/update_status/<int:id>', methods=['POST'])
@login_required
def update_status(id):
    from models import obtener_hora_bogota, AuditLog
    warranty = Warranty.query.get_or_404(id)
    data = request.get_json()
    new_status = data.get('status')
    admin_notes = data.get('admin_notes')
    
    if new_status:
        warranty.resolution = new_status
        if new_status == 'Entregada' and not warranty.entregado_por_id:
            warranty.entregado_por_id = current_user.id
            warranty.fecha_entrega = obtener_hora_bogota()
            warranty.firma_o_soporte_entrega = 'Entregado a conformidad en punto de venta'
        if admin_notes:
            warranty.admin_notes = admin_notes
        db.session.commit()
        return jsonify({'success': True, 'message': 'Estado actualizado correctamente.'})
    
    return jsonify({'success': False, 'error': 'Estado no válido.'}), 400
