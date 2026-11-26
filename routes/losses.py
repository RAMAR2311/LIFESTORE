from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify, session
from flask_login import login_required, current_user
from decimal import Decimal
from datetime import datetime, timedelta
from models import (
    db, AccessoryLoss, Product, ProductVariant, Branch, BranchStock,
    Warranty, Sale, Asesor, StockAdjustment, AuditLog, obtener_hora_bogota
)
from services.stock_service import get_or_create_branch_stock, sync_global_product_stock

losses_bp = Blueprint('losses_bp', __name__)

MOTIVOS_PERDIDA = [
    'Daño en instalación / operación (Ej: Vidrio templado)',
    'Garantía de Cliente (Reposición por accesorio defectuoso)',
    'Defectuoso de fábrica / Caja averiada',
    'Daño en vitrina / exhibición',
    'Otro motivo operativo'
]


def _resolver_sucursal_operacion(branch_id_form=None):
    """Determina la sucursal sobre la cual se descuenta el stock de la pérdida."""
    if current_user.rol in ['vendedor', 'bodega', 'vendedor_bodega']:
        if current_user.branch_id:
            return current_user.branch_id
        b_def = Branch.query.filter_by(activa=True).order_by(Branch.id.asc()).first()
        return b_def.id if b_def else 1

    if branch_id_form and str(branch_id_form).isdigit():
        return int(branch_id_form)
    active_b = session.get('active_branch_id')
    if active_b:
        return int(active_b)
    b_def = Branch.query.filter_by(activa=True).order_by(Branch.id.asc()).first()
    return b_def.id if b_def else 1


@losses_bp.route('/')
@login_required
def index():
    if current_user.rol not in ['admin', 'vendedor', 'bodega', 'coordinador']:
        flash('Acceso denegado.', 'danger')
        return redirect(url_for('index'))

    filtro_origen = request.args.get('origen', '').strip()  # 'OPERACION', 'GARANTIA' o ''
    filtro_estado = request.args.get('estado', 'ACTIVA').strip()  # 'ACTIVA', 'ANULADA', 'TODAS'
    branch_param = request.args.get('branch_id', '').strip()
    fecha_inicio = request.args.get('fecha_inicio', '').strip()
    fecha_fin = request.args.get('fecha_fin', '').strip()
    preselect_product_id = request.args.get('product_id', type=int)

    active_b_id = None
    if current_user.rol in ['vendedor', 'bodega']:
        active_b_id = current_user.branch_id
    else:
        if branch_param in ('all', '0'):
            active_b_id = None
        elif branch_param.isdigit():
            active_b_id = int(branch_param)
        else:
            active_b_id = session.get('active_branch_id')

    query = AccessoryLoss.query

    if active_b_id:
        query = query.filter(AccessoryLoss.branch_id == active_b_id)

    if filtro_origen in ('OPERACION', 'GARANTIA'):
        query = query.filter(AccessoryLoss.origen == filtro_origen)

    if filtro_estado in ('ACTIVA', 'ANULADA'):
        query = query.filter(AccessoryLoss.estado == filtro_estado)

    if fecha_inicio:
        try:
            dt_ini = datetime.strptime(fecha_inicio, '%Y-%m-%d')
            query = query.filter(AccessoryLoss.fecha_registro >= dt_ini)
        except ValueError:
            pass

    if fecha_fin:
        try:
            dt_fin = datetime.strptime(fecha_fin, '%Y-%m-%d') + timedelta(days=1)
            query = query.filter(AccessoryLoss.fecha_registro < dt_fin)
        except ValueError:
            pass

    perdidas = query.order_by(AccessoryLoss.fecha_registro.desc()).all()

    # KPIs sobre las pérdidas ACTIVAS del filtro actual
    kpi_query = AccessoryLoss.query.filter_by(estado='ACTIVA')
    if active_b_id:
        kpi_query = kpi_query.filter(AccessoryLoss.branch_id == active_b_id)
    if fecha_inicio:
        try:
            kpi_query = kpi_query.filter(AccessoryLoss.fecha_registro >= datetime.strptime(fecha_inicio, '%Y-%m-%d'))
        except ValueError:
            pass
    if fecha_fin:
        try:
            kpi_query = kpi_query.filter(AccessoryLoss.fecha_registro < datetime.strptime(fecha_fin, '%Y-%m-%d') + timedelta(days=1))
        except ValueError:
            pass

    activas_list = kpi_query.all()
    total_unidades = sum(p.cantidad for p in activas_list)
    total_costo = sum(Decimal(str(p.costo_total or 0)) for p in activas_list)
    unidades_operacion = sum(p.cantidad for p in activas_list if p.origen == 'OPERACION')
    unidades_garantia = sum(p.cantidad for p in activas_list if p.origen == 'GARANTIA')
    costo_operacion = sum(Decimal(str(p.costo_total or 0)) for p in activas_list if p.origen == 'OPERACION')
    costo_garantia = sum(Decimal(str(p.costo_total or 0)) for p in activas_list if p.origen == 'GARANTIA')

    # Cargar EXCLUSIVAMENTE accesorios (Candado estricto: tipo_inventario != 'celulares')
    accesorios = Product.query.filter(
        Product.tipo_inventario != 'celulares'
    ).order_by(Product.nombre.asc()).all()

    # Mapa de stock por producto y sucursal para mostrar en el selector
    branch_target_id = active_b_id or _resolver_sucursal_operacion()
    stocks_local = {}
    if branch_target_id:
        bs_rows = BranchStock.query.filter_by(branch_id=branch_target_id).all()
        for bs in bs_rows:
            key = f"{bs.product_id}_{bs.variant_id or 0}"
            stocks_local[key] = (stocks_local.get(key, 0) + (bs.cantidad or 0))
            if bs.variant_id is not None:
                parent_key = f"{bs.product_id}_total"
                stocks_local[parent_key] = (stocks_local.get(parent_key, 0) + (bs.cantidad or 0))

    sucursales = Branch.query.filter_by(activa=True).order_by(Branch.tipo.desc(), Branch.nombre.asc()).all()
    asesores = Asesor.query.filter_by(activo=True).order_by(Asesor.nombre.asc()).all()

    return render_template(
        'losses/index.html',
        perdidas=perdidas,
        accesorios=accesorios,
        stocks_local=stocks_local,
        sucursales=sucursales,
        asesores=asesores,
        motivos_perdida=MOTIVOS_PERDIDA,
        active_b_id=active_b_id,
        branch_target_id=branch_target_id,
        filtro_origen=filtro_origen,
        filtro_estado=filtro_estado,
        fecha_inicio=fecha_inicio,
        fecha_fin=fecha_fin,
        preselect_product_id=preselect_product_id,
        total_unidades=total_unidades,
        total_costo=total_costo,
        unidades_operacion=unidades_operacion,
        unidades_garantia=unidades_garantia,
        costo_operacion=costo_operacion,
        costo_garantia=costo_garantia
    )


@losses_bp.route('/api/variantes/<int:product_id>', methods=['GET'])
@login_required
def api_variantes_accesorio(product_id):
    """Devuelve las variantes y el stock por sucursal de un accesorio."""
    prod = Product.query.get_or_404(product_id)
    if prod.tipo_inventario == 'celulares':
        return jsonify({
            'success': False,
            'error': '🚫 Bloqueado: Este artículo pertenece al Inventario de Celulares y no puede enviarse a Pérdidas.'
        }), 400

    branch_id = request.args.get('branch_id', type=int) or _resolver_sucursal_operacion()
    variantes_data = []
    if prod.variantes:
        for v in prod.variantes:
            bs = BranchStock.query.filter_by(
                branch_id=branch_id,
                product_id=prod.id,
                variant_id=v.id
            ).first()
            stock_sede = bs.cantidad if bs else 0
            variantes_data.append({
                'id': v.id,
                'nombre': v.nombre_variante,
                'stock_sede': stock_sede,
                'stock_global': v.cantidad_stock or 0,
                'costo': float(v.precio_costo or prod.precio_costo or 0)
            })

    bs_main = BranchStock.query.filter_by(
        branch_id=branch_id,
        product_id=prod.id,
        variant_id=None
    ).first()
    stock_plano_sede = bs_main.cantidad if bs_main else 0

    return jsonify({
        'success': True,
        'product_id': prod.id,
        'nombre': prod.nombre,
        'sku': prod.sku,
        'tiene_variantes': len(variantes_data) > 0,
        'stock_sede': stock_plano_sede,
        'stock_global': prod.cantidad_stock or 0,
        'costo': float(prod.precio_costo or 0),
        'variantes': variantes_data
    })


@losses_bp.route('/registrar', methods=['POST'])
@login_required
def registrar_perdida():
    """Registra una pérdida o merma directa de un accesorio en la operación (ej. vidrio templado dañado)."""
    product_id = request.form.get('product_id', type=int)
    variant_id = request.form.get('variant_id', type=int) or None
    branch_id = _resolver_sucursal_operacion(request.form.get('branch_id'))
    asesor_id = request.form.get('asesor_id', type=int) or None
    cantidad = request.form.get('cantidad', 1, type=int)
    tipo_motivo = request.form.get('tipo_motivo', 'Daño en instalación / operación (Ej: Vidrio templado)').strip()
    motivo_detalle = request.form.get('motivo_detalle', '').strip()
    descontar_stock = request.form.get('descontar_stock', '1') == '1'

    if not product_id or cantidad <= 0:
        flash('Debes seleccionar un accesorio válido y una cantidad mayor a cero.', 'danger')
        return redirect(url_for('losses_bp.index'))

    producto = Product.query.get_or_404(product_id)

    # CANDADO ESTRICTO: Prohibido dar de baja celulares en el módulo de pérdidas
    if producto.tipo_inventario == 'celulares' or (producto.imei and producto.imei.strip()):
        flash('🚫 Operación Bloqueada: Los equipos del Inventario de Celulares NO pueden sacarse como pérdida. Deben gestionarse por Soporte Técnico.', 'danger')
        return redirect(url_for('losses_bp.index'))

    variante = None
    if producto.variantes:
        if not variant_id:
            flash(f'El accesorio "{producto.nombre}" maneja subcategorías/variantes. Selecciona cuál variante se dañó.', 'warning')
            return redirect(url_for('losses_bp.index'))
        variante = ProductVariant.query.filter_by(id=variant_id, product_id=producto.id).first()
        if not variante:
            flash('La variante seleccionada no pertenece a este accesorio.', 'danger')
            return redirect(url_for('losses_bp.index'))

    sucursal = Branch.query.get(branch_id)
    nombre_sede = sucursal.nombre if sucursal else 'Sede Principal'

    if descontar_stock:
        bs = get_or_create_branch_stock(branch_id=branch_id, product_id=producto.id, variant_id=variant_id, for_update=True)
        if (bs.cantidad or 0) < cantidad:
            flash(
                f'Stock insuficiente en {nombre_sede}: intentas dar de baja {cantidad} uds. de '
                f'"{producto.nombre}{" - " + variante.nombre_variante if variante else ""}", pero solo hay {bs.cantidad or 0} en stock local.',
                'danger'
            )
            return redirect(url_for('losses_bp.index'))

        stock_anterior = bs.cantidad or 0
        bs.cantidad = stock_anterior - cantidad
        db.session.flush()
        sync_global_product_stock(producto.id, variant_id=variant_id)

        ajuste = StockAdjustment(
            product_id=producto.id,
            admin_id=current_user.id,
            branch_id=branch_id,
            tipo_movimiento=f"Baja por Pérdida/Merma ({tipo_motivo[:40]})",
            stock_anterior=stock_anterior,
            stock_nuevo=bs.cantidad
        )
        db.session.add(ajuste)

    costo_unit = Decimal(str((variante.precio_costo if (variante and variante.precio_costo) else producto.precio_costo) or 0))
    costo_tot = costo_unit * Decimal(str(cantidad))

    loss = AccessoryLoss(
        origen='OPERACION',
        tipo_motivo=tipo_motivo,
        motivo_detalle=motivo_detalle or tipo_motivo,
        product_id=producto.id,
        variant_id=variant_id,
        branch_id=branch_id,
        asesor_id=asesor_id,
        user_id=current_user.id,
        cantidad=cantidad,
        costo_unitario=costo_unit,
        costo_total=costo_tot,
        desconto_stock=descontar_stock,
        estado='ACTIVA',
        fecha_registro=obtener_hora_bogota()
    )
    db.session.add(loss)
    db.session.flush()

    AuditLog.registrar(
        action='REGISTRO_PERDIDA_ACCESORIO',
        user_id=current_user.id,
        target_id=loss.id,
        target_type='ACCESSORY_LOSS',
        motivo=f"Pérdida operativa en {nombre_sede}: {cantidad}x {producto.nombre} ({producto.sku}). Motivo: {tipo_motivo}. {motivo_detalle}",
        detalles=f'{{"product_id": {producto.id}, "variant_id": {variant_id or "null"}, "cantidad": {cantidad}, "costo_total": {float(costo_tot)}}}'
    )
    db.session.commit()

    flash(
        f'✅ Pérdida registrada correctamente: {cantidad}x "{producto.nombre}" '
        f'({"descontado del stock de " + nombre_sede if descontar_stock else "sin descuento de stock"}). '
        f'Costo registrado: ${int(costo_tot):,}.'.replace(',', '.'),
        'success'
    )
    return redirect(url_for('losses_bp.index'))


@losses_bp.route('/desde-garantia/<int:warranty_id>', methods=['POST'])
@login_required
def registrar_desde_garantia(warranty_id):
    """Envía un accesorio recibido por garantía al módulo de Pérdidas y descuenta del stock la unidad nueva entregada en reposición."""
    warranty = Warranty.query.get_or_404(warranty_id)

    # Producto que sale de stock en reposición (puede ser el mismo de la garantía u otro accesorio elegido en el buscador)
    reponer_product_id = request.form.get('product_id', type=int) or warranty.product_id
    variant_id = request.form.get('variant_id', type=int) or warranty.variant_id or None
    branch_id = _resolver_sucursal_operacion(request.form.get('branch_id') or warranty.branch_id)
    asesor_id = request.form.get('asesor_id', type=int) or warranty.asesor_id
    cantidad = request.form.get('cantidad', warranty.quantity or 1, type=int)
    reponer_stock = request.form.get('reponer_stock', '1') == '1'
    notas_resolucion = request.form.get('notas_resolucion', '').strip()
    soporte_entrega = request.form.get('soporte_entrega', '').strip() or 'Reposición de accesorio nuevo por garantía'

    if not reponer_product_id:
        flash('Selecciona en el buscador el accesorio del inventario para procesar la baja y reposición.', 'danger')
        return redirect(url_for('warranties_bp.index'))

    producto_reposicion = Product.query.get_or_404(reponer_product_id)
    producto_danado = warranty.product if warranty.product else producto_reposicion

    # CANDADO ESTRICTO: Si el producto es del inventario de celulares, bloquear envío a pérdidas
    if producto_reposicion.tipo_inventario == 'celulares' or (producto_reposicion.imei and producto_reposicion.imei.strip()):
        flash('🚫 Operación Bloqueada: Los equipos del Inventario de Celulares NO pueden enviarse a Pérdidas. Deben derivarse a Soporte Técnico.', 'danger')
        return redirect(url_for('warranties_bp.index'))
    if producto_danado and (producto_danado.tipo_inventario == 'celulares' or (producto_danado.imei and producto_danado.imei.strip())):
        flash('🚫 Operación Bloqueada: Esta garantía corresponde a un Celular y no puede enviarse a Pérdidas.', 'danger')
        return redirect(url_for('warranties_bp.index'))

    variante = None
    if variant_id:
        variante = ProductVariant.query.filter_by(id=variant_id, product_id=producto_reposicion.id).first()
    elif producto_reposicion.variantes and len(producto_reposicion.variantes) == 1:
        variante = producto_reposicion.variantes[0]
        variant_id = variante.id

    sucursal = Branch.query.get(branch_id)
    nombre_sede = sucursal.nombre if sucursal else 'Sede Principal'

    stock_anterior = None
    stock_nuevo = None
    if reponer_stock:
        bs = get_or_create_branch_stock(branch_id=branch_id, product_id=producto_reposicion.id, variant_id=variant_id, for_update=True)
        if (bs.cantidad or 0) < cantidad:
            flash(
                f'No hay suficiente stock en {nombre_sede} para entregar el accesorio nuevo de reposición '
                f'("{producto_reposicion.nombre}": disponible {bs.cantidad or 0} uds., requerido {cantidad} uds.).',
                'danger'
            )
            return redirect(url_for('warranties_bp.index'))

        stock_anterior = bs.cantidad or 0
        bs.cantidad = stock_anterior - cantidad
        stock_nuevo = bs.cantidad
        db.session.flush()
        sync_global_product_stock(producto_reposicion.id, variant_id=variant_id)

        ajuste = StockAdjustment(
            product_id=producto_reposicion.id,
            admin_id=current_user.id,
            branch_id=branch_id,
            tipo_movimiento=f"Reposición por Garantía #{warranty.id} (Fac #{warranty.sale_id}) -> Pérdida",
            stock_anterior=stock_anterior,
            stock_nuevo=bs.cantidad
        )
        db.session.add(ajuste)

    costo_unit = Decimal(str((variante.precio_costo if (variante and variante.precio_costo) else producto_reposicion.precio_costo) or 0))
    costo_tot = costo_unit * Decimal(str(cantidad))

    nombre_danado_txt = producto_danado.nombre if producto_danado else (warranty.nombre_manual or producto_reposicion.nombre)
    nombre_repuesto_txt = f"{producto_reposicion.nombre}{' (' + variante.nombre_variante + ')' if variante else ''}"

    if reponer_stock:
        if producto_danado and producto_danado.id != producto_reposicion.id:
            flujo_txt = f"Entró dañado: {nombre_danado_txt} | Salió en reposición: {cantidad}x {nombre_repuesto_txt} (Stock {nombre_sede}: {stock_anterior} -> {stock_nuevo})"
        else:
            flujo_txt = f"Entró dañado a Pérdidas y salió 1 nuevo de stock ({nombre_sede}: {stock_anterior} -> {stock_nuevo} uds.)"
    else:
        flujo_txt = f"Entró dañado a Pérdidas sin descontar reposición de stock"

    detalle_motivo = (
        f"Garantía #{warranty.id} (Fac #{warranty.sale_id}) · {flujo_txt} · Falla: {warranty.motivo_reportado or warranty.reason}"
    )
    if notas_resolucion:
        detalle_motivo += f" · Nota: {notas_resolucion}"

    loss = AccessoryLoss(
        origen='GARANTIA',
        tipo_motivo='Garantía de Cliente (Reposición por accesorio defectuoso)',
        motivo_detalle=detalle_motivo,
        product_id=producto_reposicion.id,
        variant_id=variant_id,
        warranty_id=warranty.id,
        sale_id=warranty.sale_id,
        branch_id=branch_id,
        asesor_id=asesor_id,
        user_id=current_user.id,
        cantidad=cantidad,
        costo_unitario=costo_unit,
        costo_total=costo_tot,
        desconto_stock=reponer_stock,
        estado='ACTIVA',
        fecha_registro=obtener_hora_bogota()
    )
    db.session.add(loss)

    # Actualizar estado de la garantía
    if not warranty.product_id:
        warranty.product_id = producto_reposicion.id
    warranty.variant_id = variant_id
    warranty.resolution = 'Repuesto (Pérdida)'
    warranty.entregado_por_id = current_user.id
    warranty.fecha_entrega = obtener_hora_bogota()
    warranty.firma_o_soporte_entrega = soporte_entrega
    nota_extra = f"Enviado a Pérdidas (#{loss.id}) y {'repuesto con ' + nombre_repuesto_txt + ' de ' + nombre_sede if reponer_stock else 'dado de baja'}. {notas_resolucion}".strip()
    warranty.admin_notes = f"{nota_extra} | {warranty.admin_notes or ''}".strip(' |')

    db.session.flush()

    AuditLog.registrar(
        action='GARANTIA_ACCESORIO_A_PERDIDA',
        user_id=current_user.id,
        target_id=warranty.id,
        target_type='WARRANTY',
        motivo=f"Garantía #{warranty.id} enviada a Pérdidas (#{loss.id}). {flujo_txt}.",
        detalles=f'{{"loss_id": {loss.id}, "product_id": {producto_reposicion.id}, "cantidad": {cantidad}, "costo_total": {float(costo_tot)}}}'
    )
    db.session.commit()

    flash(
        f'✅ Garantía #{warranty.id} procesada: el accesorio dañado quedó registrado en el Módulo de Pérdidas '
        f'{"y se descontó -" + str(cantidad) + " ud. nueva de " + nombre_repuesto_txt + " del stock de " + nombre_sede + " (Stock: " + str(stock_anterior) + " → " + str(stock_nuevo) + ")" if reponer_stock else ""}.',
        'success'
    )
    return redirect(url_for('warranties_bp.index'))


@losses_bp.route('/anular/<int:loss_id>', methods=['POST'])
@login_required
def anular_perdida(loss_id):
    """Permite al administrador anular un registro de pérdida y devolver las unidades al stock de la sucursal."""
    if current_user.rol != 'admin':
        flash('Solo el administrador puede anular registros de pérdidas.', 'danger')
        return redirect(url_for('losses_bp.index'))

    loss = AccessoryLoss.query.get_or_404(loss_id)
    if loss.estado == 'ANULADA':
        flash('Esta pérdida ya se encontraba anulada.', 'warning')
        return redirect(url_for('losses_bp.index'))

    motivo_anulacion = request.form.get('motivo_anulacion', 'Anulación / Reversión por administrador').strip()

    if loss.desconto_stock and loss.product_id:
        bs = get_or_create_branch_stock(
            branch_id=loss.branch_id,
            product_id=loss.product_id,
            variant_id=loss.variant_id,
            for_update=True
        )
        stock_anterior = bs.cantidad or 0
        bs.cantidad = stock_anterior + loss.cantidad
        db.session.flush()
        sync_global_product_stock(loss.product_id, variant_id=loss.variant_id)

        ajuste = StockAdjustment(
            product_id=loss.product_id,
            admin_id=current_user.id,
            branch_id=loss.branch_id,
            tipo_movimiento=f"Reversión de Pérdida #{loss.id}",
            stock_anterior=stock_anterior,
            stock_nuevo=bs.cantidad
        )
        db.session.add(ajuste)

    loss.estado = 'ANULADA'
    loss.anulado_por_id = current_user.id
    loss.fecha_anulacion = obtener_hora_bogota()
    loss.motivo_anulacion = motivo_anulacion

    AuditLog.registrar(
        action='ANULACION_PERDIDA_ACCESORIO',
        user_id=current_user.id,
        target_id=loss.id,
        target_type='ACCESSORY_LOSS',
        motivo=f"Anulación de pérdida #{loss.id} ({loss.cantidad}x {loss.producto.nombre if loss.producto else ''}). Motivo: {motivo_anulacion}"
    )
    db.session.commit()

    flash(f'🔄 Pérdida #{loss.id} anulada correctamente. El stock fue restaurado en la sede.', 'info')
    return redirect(url_for('losses_bp.index'))
