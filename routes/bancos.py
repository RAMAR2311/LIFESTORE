from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify
from flask_login import login_required, current_user
from models import db, BankAccount, BankTransaction, obtener_hora_bogota
from decorators import admin_required
from services.bank_service import registrar_movimiento_banco
from decimal import Decimal

bancos_bp = Blueprint('bancos_bp', __name__)

@bancos_bp.route('/', methods=['GET'])
@login_required
def index():
    if current_user.rol == 'coordinador':
        flash('Tu perfil no tiene acceso al módulo de Bancos.', 'warning')
        return redirect(url_for('celulares_bp.inventario'))

    """Pantalla principal del módulo de Bancos: saldo por cada método de pago e historial de movimientos."""
    cuentas = BankAccount.query.filter_by(activo=True).order_by(BankAccount.id.asc()).all()

    # Filtros de historial
    account_id = request.args.get('account_id', type=int)
    tipo_mov = request.args.get('tipo_movimiento', '').strip()
    fecha_inicio = request.args.get('fecha_inicio', '').strip()
    fecha_fin = request.args.get('fecha_fin', '').strip()

    query = BankTransaction.query

    if account_id:
        query = query.filter(BankTransaction.account_id == account_id)
    if tipo_mov in ['INGRESO', 'EGRESO', 'AJUSTE']:
        query = query.filter(BankTransaction.tipo_movimiento == tipo_mov)
    if fecha_inicio:
        try:
            from datetime import datetime
            dt_ini = datetime.strptime(fecha_inicio, '%Y-%m-%d')
            query = query.filter(BankTransaction.fecha >= dt_ini)
        except ValueError:
            pass
    if fecha_fin:
        try:
            from datetime import datetime, time
            dt_fin = datetime.strptime(fecha_fin, '%Y-%m-%d')
            dt_fin = datetime.combine(dt_fin.date(), time(23, 59, 59))
            query = query.filter(BankTransaction.fecha <= dt_fin)
        except ValueError:
            pass

    movimientos = query.order_by(BankTransaction.fecha.desc()).limit(150).all()

    # Totales consolidados
    total_en_bancos = sum((c.saldo_actual for c in cuentas if c.codigo != 'efectivo'), Decimal('0.00'))
    total_efectivo = sum((c.saldo_actual for c in cuentas if c.codigo == 'efectivo'), Decimal('0.00'))
    total_global = sum((c.saldo_actual for c in cuentas), Decimal('0.00'))

    return render_template(
        'bancos/index.html',
        cuentas=cuentas,
        movimientos=movimientos,
        total_en_bancos=total_en_bancos,
        total_efectivo=total_efectivo,
        total_global=total_global,
        selected_account_id=account_id,
        selected_tipo=tipo_mov,
        fecha_inicio=fecha_inicio,
        fecha_fin=fecha_fin
    )

@bancos_bp.route('/ajuste_manual', methods=['POST'])
@login_required
@admin_required
def ajuste_manual():
    """Permite al administrador realizar ajustes de saldo directo con justificación para auditoría."""
    account_id = request.form.get('account_id', type=int)
    tipo_ajuste = request.form.get('tipo_ajuste', 'INGRESO') # 'INGRESO' o 'EGRESO'
    monto = request.form.get('monto', type=float)
    motivo = request.form.get('motivo', '').strip()

    if not account_id or not monto or monto <= 0:
        flash('Datos de ajuste inválidos. El monto debe ser mayor a 0.', 'danger')
        return redirect(url_for('bancos_bp.index'))

    cuenta = BankAccount.query.get_or_404(account_id)

    try:
        registrar_movimiento_banco(
            codigo_metodo=cuenta.codigo,
            monto=monto,
            tipo_movimiento=tipo_ajuste,
            origen='AJUSTE_MANUAL',
            descripcion=f'Ajuste Manual: {motivo or "Sin motivo especificado"}',
            usuario_id=current_user.id
        )
        db.session.commit()
        flash(f'Ajuste manual aplicado a {cuenta.nombre} exitosamente.', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Error al procesar el ajuste manual: {str(e)}', 'danger')

    return redirect(url_for('bancos_bp.index'))

@bancos_bp.route('/transferir_a_caja_mayor', methods=['POST'])
@login_required
@admin_required
def transferir_a_caja_mayor():
    """Transfiere dinero desde un banco/método digital hacia la Caja Mayor (Efectivo)."""
    origen_id = request.form.get('origen_id', type=int)
    monto = request.form.get('monto', type=float)
    motivo = request.form.get('motivo', '').strip()

    if not origen_id or not monto or monto <= 0:
        flash('Datos de transferencia inválidos. El monto debe ser mayor a 0.', 'danger')
        return redirect(url_for('bancos_bp.index'))

    cuenta_origen = BankAccount.query.get_or_404(origen_id)

    if cuenta_origen.codigo == 'efectivo':
        flash('No puedes transferir de Efectivo hacia Efectivo.', 'warning')
        return redirect(url_for('bancos_bp.index'))

    try:
        detalle_origen = f'Retiro/Traslado hacia Efectivo Caja Mayor: {motivo or "Sin detalle"}'
        detalle_destino = f'Ingreso traslado desde {cuenta_origen.nombre}: {motivo or "Sin detalle"}'

        # 1. Egresar del banco origen
        registrar_movimiento_banco(
            codigo_metodo=cuenta_origen.codigo,
            monto=monto,
            tipo_movimiento='EGRESO',
            origen='TRASLADO_A_CAJA',
            descripcion=detalle_origen,
            usuario_id=current_user.id
        )

        # 2. Ingresar a Efectivo Caja Mayor
        registrar_movimiento_banco(
            codigo_metodo='efectivo',
            monto=monto,
            tipo_movimiento='INGRESO',
            origen='TRASLADO_A_CAJA',
            descripcion=detalle_destino,
            usuario_id=current_user.id
        )

        db.session.commit()
        flash(f'Transferencia de ${monto:,.0f} desde {cuenta_origen.nombre} a Efectivo Caja Mayor realizada con éxito.', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Error al realizar la transferencia: {str(e)}', 'danger')

    return redirect(url_for('bancos_bp.index'))

