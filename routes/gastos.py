from flask import Blueprint, render_template, request, redirect, url_for, flash
from flask_login import login_required, current_user
from models import db, Expense, obtener_hora_bogota
from decorators import admin_required
from sqlalchemy import extract
from datetime import datetime

gastos_bp = Blueprint('gastos_bp', __name__)

@gastos_bp.route('/', methods=['GET', 'POST'])
@login_required
def index():
    if request.method == 'POST':
        tipo_gasto = request.form.get('tipo_gasto')
        
        # Restricción de seguridad backend: Vendedores sólo registran gastos operativos
        if current_user.rol != 'admin':
            tipo_gasto = 'Gasto Diario'
            
        categoria = request.form.get('categoria')
        descripcion = request.form.get('descripcion')
        montos = request.form.getlist('monto[]')
        metodos_pago = request.form.getlist('metodo_pago[]')
        
        # Compatibilidad con formulario antiguo (sin arrays)
        if not montos:
            monto_single = request.form.get('monto')
            if monto_single:
                montos = [monto_single]
                metodos_pago = [request.form.get('metodo_pago', 'efectivo')]

        fecha_str = request.form.get('fecha_gasto')

        # Use the provided date or fallback to current datetime
        if fecha_str:
            try:
                fecha_obj = datetime.strptime(fecha_str, '%Y-%m-%d')
            except ValueError:
                fecha_obj = obtener_hora_bogota()
        else:
            fecha_obj = obtener_hora_bogota()

        # Determinar branch_id para el gasto
        from models import Branch
        from flask import session
        if current_user.rol in ['vendedor', 'bodega']:
            gasto_branch_id = current_user.branch_id
            if not gasto_branch_id:
                b_def = Branch.query.filter_by(activa=True).order_by(Branch.id.asc()).first()
                gasto_branch_id = b_def.id if b_def else 1
        else:
            active_b = session.get('active_branch_id')
            if active_b:
                gasto_branch_id = int(active_b)
            else:
                b_def = Branch.query.filter_by(activa=True).order_by(Branch.id.asc()).first()
                gasto_branch_id = b_def.id if b_def else 1

        b_obj = Branch.query.get(gasto_branch_id)
        gasto_branch_nombre = b_obj.nombre if b_obj else 'PRINCIPAL'

        try:
            from services.bank_service import registrar_movimiento_banco
            for monto, metodo in zip(montos, metodos_pago):
                valor_float = float(monto)
                if valor_float > 0:
                    nuevo_gasto = Expense(
                        usuario_id=current_user.id,
                        tipo_gasto=tipo_gasto,
                        categoria=categoria,
                        descripcion=descripcion,
                        monto=valor_float,
                        metodo_pago=metodo,
                        fecha_gasto=fecha_obj,
                        sucursal=gasto_branch_nombre,
                        branch_id=gasto_branch_id
                    )
                    db.session.add(nuevo_gasto)
                    db.session.flush()

                    # Regla de negocio solicitada:
                    # Descontar del módulo de bancos A MENOS que sea Gasto Diario en Efectivo
                    # (ya que el gasto diario en efectivo se descuenta directamente en el arqueo del día).
                    es_gasto_diario_efectivo = (tipo_gasto == 'Gasto Diario' and str(metodo).lower() == 'efectivo')
                    if not es_gasto_diario_efectivo:
                        registrar_movimiento_banco(
                            codigo_metodo=metodo,
                            monto=valor_float,
                            tipo_movimiento='EGRESO',
                            origen='GASTO',
                            descripcion=f'Gasto: {categoria} - {descripcion or ""} (Gasto #{nuevo_gasto.id})',
                            referencia_id=nuevo_gasto.id,
                            usuario_id=current_user.id
                        )

            db.session.commit()
            flash('Gasto registrado exitosamente.', 'success')
        except Exception as e:
            db.session.rollback()
            flash(f'Error al registrar el gasto: {str(e)}', 'danger')
        
        return redirect(url_for('gastos_bp.index'))

    # GET Logic (Filters current month expenses)
    ahora = obtener_hora_bogota()
    mes_actual = ahora.month
    anio_actual = ahora.year

    # Consultamos registros del mes y del año actual
    query = Expense.query.filter(
        extract('month', Expense.fecha_gasto) == mes_actual,
        extract('year', Expense.fecha_gasto) == anio_actual
    )
    
    # Restricción de visibilidad por Sucursal / Rol: 
    # Vendedor solo puede ver y listar los gastos de su propia sucursal
    from flask import session
    if current_user.rol == 'vendedor':
        if current_user.branch_id:
            query = query.filter(Expense.branch_id == current_user.branch_id)
        else:
            query = query.filter(Expense.usuario_id == current_user.id)
    else:
        # Admin y Bodega: si seleccionaron una sucursal en el switcher global, filtrar por esa sucursal
        active_b_id = session.get('active_branch_id')
        if active_b_id:
            query = query.filter(Expense.branch_id == int(active_b_id))
        
    gastos_mes = query.order_by(Expense.fecha_gasto.desc()).all()

    total_diarios = sum((g.monto for g in gastos_mes if g.tipo_gasto == 'Gasto Diario'))
    total_indirectos = sum((g.monto for g in gastos_mes if g.tipo_gasto == 'Costo Indirecto'))

    # Provide today's date formatted for HTML5 <input type="date">
    hoy_str = ahora.strftime('%Y-%m-%d')
    return render_template('gastos/index.html', gastos=gastos_mes, total_diarios=total_diarios, total_indirectos=total_indirectos, hoy=hoy_str)

@gastos_bp.route('/<int:id>/eliminar', methods=['POST'])
@login_required
@admin_required
def eliminar_gasto(id):
    gasto = Expense.query.get_or_404(id)
    descripcion = gasto.descripcion or gasto.categoria
    try:
        from services.bank_service import revertir_movimiento_banco
        revertir_movimiento_banco(origen='GASTO', referencia_id=id)

        db.session.delete(gasto)
        db.session.commit()
        flash(f'Gasto "{descripcion}" eliminado correctamente y actualizado en Bancos.', 'success')
    except Exception as e:
        db.session.rollback()
        flash('Error al intentar eliminar el gasto.', 'danger')

    return redirect(url_for('gastos_bp.index'))
