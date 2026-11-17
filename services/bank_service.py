from decimal import Decimal
from models import db, BankAccount, BankTransaction, obtener_hora_bogota

def normalizar_codigo_metodo(metodo):
    """Normaliza strings de métodos de pago para coincidir con BankAccount.codigo"""
    if not metodo:
        return 'efectivo'
    m = str(metodo).strip().lower()
    if 'nequi' in m:
        return 'nequi'
    elif 'bancolombia' in m:
        return 'bancolombia'
    elif 'daviplata' in m:
        return 'daviplata'
    elif 'davivienda' in m:
        return 'davivienda'
    elif 'addi' in m:
        return 'addi'
    elif 'sitecredito' in m or 'sistecrédito' in m or 'sistecredito' in m:
        return 'sitecredito'
    elif 'tarjeta' in m or 'credito' in m or 'datafono' in m or 'bold' in m or 'bolt' in m:
        return 'tarjeta_credito'
    elif 'efectivo' in m or 'cash' in m:
        return 'efectivo'
    elif 'transferencia' in m:
        return 'transferencia'
    return m

def registrar_movimiento_banco(codigo_metodo, monto, tipo_movimiento, origen, descripcion, referencia_id=None, usuario_id=None):
    """
    Registra una transacción bancaria y actualiza el saldo de la cuenta correspondiente.
    
    :param codigo_metodo: 'efectivo', 'nequi', 'bancolombia', etc.
    :param monto: Decimal o float positivo
    :param tipo_movimiento: 'INGRESO', 'EGRESO', 'AJUSTE'
    :param origen: 'ARQUEO_CIERRE', 'ABONO_PROVEEDOR', 'GASTO', 'AJUSTE_MANUAL'
    :param descripcion: Texto explicativo
    :param referencia_id: ID del registro que originó la transacción (Arqueo, Abono, Gasto)
    :param usuario_id: ID del usuario que ejecuta la acción
    """
    monto_dec = Decimal(str(monto or 0))
    if monto_dec <= Decimal('0.00'):
        return None

    codigo_limpio = normalizar_codigo_metodo(codigo_metodo)
    
    cuenta = BankAccount.query.filter_by(codigo=codigo_limpio).first()
    if not cuenta:
        # Si no existe, crear la cuenta automáticamente
        nombre_display = codigo_limpio.capitalize()
        cuenta = BankAccount(
            codigo=codigo_limpio,
            nombre=nombre_display,
            tipo='banco' if codigo_limpio != 'efectivo' else 'efectivo',
            saldo_actual=Decimal('0.00'),
            activo=True
        )
        db.session.add(cuenta)
        db.session.flush()

    saldo_anterior = Decimal(str(cuenta.saldo_actual or 0))

    if tipo_movimiento == 'INGRESO':
        saldo_nuevo = saldo_anterior + monto_dec
    elif tipo_movimiento == 'EGRESO':
        saldo_nuevo = saldo_anterior - monto_dec
    else: # AJUSTE u otros
        saldo_nuevo = saldo_anterior + monto_dec

    cuenta.saldo_actual = saldo_nuevo
    cuenta.fecha_actualizacion = obtener_hora_bogota()

    transaccion = BankTransaction(
        account_id=cuenta.id,
        tipo_movimiento=tipo_movimiento,
        origen=origen,
        monto=monto_dec,
        saldo_anterior=saldo_anterior,
        saldo_nuevo=saldo_nuevo,
        descripcion=descripcion,
        referencia_id=referencia_id,
        usuario_id=usuario_id,
        fecha=obtener_hora_bogota()
    )

    db.session.add(transaccion)
    return transaccion

def revertir_movimiento_banco(origen, referencia_id):
    """
    Reversa y elimina el movimiento bancario asociado a un origen y referencia_id
    cuando se elimina un Gasto o un Abono a Proveedor. Restaura el saldo de la cuenta.
    """
    movimientos = BankTransaction.query.filter_by(origen=origen, referencia_id=referencia_id).all()
    for mov in movimientos:
        cuenta = BankAccount.query.get(mov.account_id)
        if cuenta:
            monto_dec = Decimal(str(mov.monto or 0))
            saldo_actual = Decimal(str(cuenta.saldo_actual or 0))
            # Si era EGRESO (se restó dinero), al eliminarlo devolvemos el dinero (sumamos)
            if mov.tipo_movimiento == 'EGRESO':
                cuenta.saldo_actual = saldo_actual + monto_dec
            # Si era INGRESO (se sumó dinero), al eliminarlo lo restamos
            elif mov.tipo_movimiento == 'INGRESO':
                cuenta.saldo_actual = saldo_actual - monto_dec
            cuenta.fecha_actualizacion = obtener_hora_bogota()
        
        db.session.delete(mov)

