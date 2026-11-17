from flask import Blueprint, render_template, request, redirect, url_for, flash, session, abort
from flask_login import login_required, current_user
from models import db, Vale, Asesor, Branch, User, AuditLog, obtener_hora_bogota
from decorators import admin_required
from decimal import Decimal
from datetime import datetime

vales_bp = Blueprint('vales_bp', __name__)


def get_active_branch_for_user():
    """Determina la sucursal activa según el rol del usuario en sesión."""
    if current_user.rol in ['vendedor', 'bodega', 'vendedor_bodega']:
        if current_user.branch_id:
            return current_user.branch_id
        b_def = Branch.query.filter_by(activa=True).order_by(Branch.id.asc()).first()
        return b_def.id if b_def else None
    active_b = session.get('active_branch_id')
    return int(active_b) if active_b else None


@vales_bp.route('/', methods=['GET'])
@login_required
def index():
    """
    Vista unificada del módulo de Vales:
    - Si es Vendedor: muestra el formulario para solicitar un vale seleccionando el asesor y el monto,
      junto con el historial y trazabilidad de los vales solicitados en su sede/usuario.
    - Si es Administrador: muestra el panel de bandeja de solicitudes recibidas para aceptar o rechazar,
      filtros avanzados y la trazabilidad completa de todos los vales.
    """
    asesores_activos = Asesor.query.filter_by(activo=True).order_by(Asesor.nombre.asc()).all()
    todos_asesores = Asesor.query.order_by(Asesor.nombre.asc()).all()

    estado_filtro = request.args.get('estado', '').strip().upper()
    asesor_id_filtro = request.args.get('asesor_id', type=int)
    fecha_filtro = request.args.get('fecha', '').strip()

    query = Vale.query

    # Filtrado según perfil
    if current_user.rol != 'admin':
        if current_user.branch_id:
            query = query.filter(
                (Vale.branch_id == current_user.branch_id) | (Vale.solicitado_por_id == current_user.id)
            )
        else:
            query = query.filter(Vale.solicitado_por_id == current_user.id)
    else:
        active_b = session.get('active_branch_id')
        if active_b:
            query = query.filter(Vale.branch_id == int(active_b))

    if estado_filtro in ['PENDIENTE', 'APROBADO', 'RECHAZADO']:
        query = query.filter(Vale.estado == estado_filtro)

    if asesor_id_filtro:
        query = query.filter(Vale.asesor_id == asesor_id_filtro)

    if fecha_filtro:
        try:
            f_obj = datetime.strptime(fecha_filtro, '%Y-%m-%d').date()
            query = query.filter(db.func.date(Vale.fecha_solicitud) == f_obj)
        except ValueError:
            pass

    # Ordenar pendientes primero o por fecha descendente
    vales = query.order_by(Vale.fecha_solicitud.desc()).all()

    # Métricas de resumen sobre la consulta base (sin filtro de estado puntual para mostrar KPIs globales del contexto)
    base_kpi_q = Vale.query
    if current_user.rol != 'admin':
        if current_user.branch_id:
            base_kpi_q = base_kpi_q.filter(
                (Vale.branch_id == current_user.branch_id) | (Vale.solicitado_por_id == current_user.id)
            )
        else:
            base_kpi_q = base_kpi_q.filter(Vale.solicitado_por_id == current_user.id)
    else:
        active_b = session.get('active_branch_id')
        if active_b:
            base_kpi_q = base_kpi_q.filter(Vale.branch_id == int(active_b))

    todos_contexto = base_kpi_q.all()
    pendientes_list = [v for v in todos_contexto if v.estado == 'PENDIENTE']
    aprobados_list = [v for v in todos_contexto if v.estado == 'APROBADO']
    rechazados_list = [v for v in todos_contexto if v.estado == 'RECHAZADO']

    kpis = {
        'pendientes_count': len(pendientes_list),
        'pendientes_monto': sum((v.monto or Decimal('0')) for v in pendientes_list),
        'aprobados_count': len(aprobados_list),
        'aprobados_monto': sum((v.monto or Decimal('0')) for v in aprobados_list),
        'rechazados_count': len(rechazados_list),
        'rechazados_monto': sum((v.monto or Decimal('0')) for v in rechazados_list),
        'total_count': len(todos_contexto)
    }

    return render_template(
        'vales/index.html',
        vales=vales,
        asesores_activos=asesores_activos,
        todos_asesores=todos_asesores,
        estado_filtro=estado_filtro,
        asesor_id_filtro=asesor_id_filtro,
        fecha_filtro=fecha_filtro,
        kpis=kpis
    )


@vales_bp.route('/solicitar', methods=['POST'])
@login_required
def solicitar():
    """Permite al vendedor (o usuario en sesión) enviar una solicitud de vale indicando el asesor y la cantidad."""
    asesor_id = request.form.get('asesor_id', type=int)
    monto_raw = request.form.get('monto', '0')
    concepto = request.form.get('concepto', '').strip()

    if not asesor_id:
        flash('Debes seleccionar el asesor que solicita el vale.', 'danger')
        return redirect(url_for('vales_bp.index'))

    asesor = Asesor.query.get(asesor_id)
    if not asesor or not asesor.activo:
        flash('El asesor seleccionado no existe o no se encuentra activo.', 'danger')
        return redirect(url_for('vales_bp.index'))

    try:
        monto_clean = str(monto_raw).replace('$', '').replace('.', '').replace(',', '').strip()
        monto = Decimal(monto_clean)
        if monto <= 0:
            raise ValueError('La cantidad debe ser mayor a $0.')
    except Exception:
        flash('Ingresa una cantidad de dinero válida mayor a $0.', 'danger')
        return redirect(url_for('vales_bp.index'))

    branch_id = get_active_branch_for_user()

    try:
        nuevo_vale = Vale(
            asesor_id=asesor.id,
            solicitado_por_id=current_user.id,
            branch_id=branch_id,
            monto=monto,
            concepto=concepto or None,
            estado='PENDIENTE',
            fecha_solicitud=obtener_hora_bogota()
        )
        db.session.add(nuevo_vale)
        db.session.flush()

        AuditLog.registrar(
            action='SOLICITUD_VALE',
            user_id=current_user.id,
            motivo=f"Solicitud de vale #{nuevo_vale.id} para el asesor '{asesor.nombre}' por ${float(monto):,.0f}. {('Motivo: ' + concepto) if concepto else ''}",
            target_id=nuevo_vale.id,
            target_type='VALE'
        )

        db.session.commit()
        flash(f"Solicitud de vale #VAL-{nuevo_vale.id:04d} para '{asesor.nombre}' por ${float(monto):,.0f} enviada exitosamente al administrador.", 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Error al enviar la solicitud de vale: {str(e)}', 'danger')

    return redirect(url_for('vales_bp.index'))


@vales_bp.route('/<int:id>/aprobar', methods=['POST'])
@login_required
@admin_required
def aprobar(id):
    """El Administrador aprueba la solicitud de vale y queda la trazabilidad."""
    vale = Vale.query.get_or_404(id)
    if vale.estado != 'PENDIENTE':
        flash(f'El vale #VAL-{vale.id:04d} ya fue procesado anteriormente ({vale.estado}).', 'warning')
        return redirect(url_for('vales_bp.index'))

    observacion = request.form.get('observacion_resolucion', '').strip()

    try:
        vale.estado = 'APROBADO'
        vale.resuelto_por_id = current_user.id
        vale.observacion_resolucion = observacion or 'Vale autorizado por administración.'
        vale.fecha_resolucion = obtener_hora_bogota()

        AuditLog.registrar(
            action='APROBACION_VALE',
            user_id=current_user.id,
            motivo=f"Aprobación de vale #VAL-{vale.id:04d} para el asesor '{vale.asesor.nombre if vale.asesor else 'N/A'}' por ${float(vale.monto):,.0f}. Nota: {vale.observacion_resolucion}",
            target_id=vale.id,
            target_type='VALE'
        )

        db.session.commit()
        flash(f"Vale #VAL-{vale.id:04d} de '{vale.asesor.nombre}' por ${float(vale.monto):,.0f} APROBADO correctamente.", 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Error al aprobar el vale: {str(e)}', 'danger')

    return redirect(url_for('vales_bp.index'))


@vales_bp.route('/<int:id>/rechazar', methods=['POST'])
@login_required
@admin_required
def rechazar(id):
    """El Administrador rechaza la solicitud de vale y queda la trazabilidad."""
    vale = Vale.query.get_or_404(id)
    if vale.estado != 'PENDIENTE':
        flash(f'El vale #VAL-{vale.id:04d} ya fue procesado anteriormente ({vale.estado}).', 'warning')
        return redirect(url_for('vales_bp.index'))

    observacion = request.form.get('observacion_resolucion', '').strip()

    try:
        vale.estado = 'RECHAZADO'
        vale.resuelto_por_id = current_user.id
        vale.observacion_resolucion = observacion or 'Solicitud rechazada por administración.'
        vale.fecha_resolucion = obtener_hora_bogota()

        AuditLog.registrar(
            action='RECHAZO_VALE',
            user_id=current_user.id,
            motivo=f"Rechazo de vale #VAL-{vale.id:04d} para el asesor '{vale.asesor.nombre if vale.asesor else 'N/A'}' por ${float(vale.monto):,.0f}. Motivo: {vale.observacion_resolucion}",
            target_id=vale.id,
            target_type='VALE'
        )

        db.session.commit()
        flash(f"Vale #VAL-{vale.id:04d} de '{vale.asesor.nombre}' RECHAZADO.", 'info')
    except Exception as e:
        db.session.rollback()
        flash(f'Error al rechazar el vale: {str(e)}', 'danger')

    return redirect(url_for('vales_bp.index'))
