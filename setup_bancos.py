from app import create_app
from models import db, BankAccount
from decimal import Decimal

def setup_bancos():
    app = create_app()
    with app.app_context():
        # 1. Crear tablas nuevas si no existen
        db.create_all()

        # 2. Agregar columna metodo_pago a provider_payments si falta
        try:
            db.session.execute(db.text("ALTER TABLE provider_payments ADD COLUMN metodo_pago VARCHAR(50) DEFAULT 'efectivo';"))
            db.session.commit()
            print("[EXITO] Columna 'metodo_pago' agregada a provider_payments.")
        except Exception as e:
            db.session.rollback()
            print("[INFO] Columna 'metodo_pago' en provider_payments ya existía o no requiere cambios.")

        # 3. Inicializar métodos de pago por defecto en bank_accounts
        metodos_default = [
            {'codigo': 'efectivo', 'nombre': 'Efectivo en Caja', 'tipo': 'efectivo', 'icono': 'fa-money-bill-wave'},
            {'codigo': 'nequi', 'nombre': 'Nequi', 'tipo': 'banco', 'icono': 'fa-mobile-screen'},
            {'codigo': 'bancolombia', 'nombre': 'Bancolombia', 'tipo': 'banco', 'icono': 'fa-building-columns'},
            {'codigo': 'daviplata', 'nombre': 'Daviplata', 'tipo': 'banco', 'icono': 'fa-wallet'},
            {'codigo': 'davivienda', 'nombre': 'Davivienda', 'tipo': 'banco', 'icono': 'fa-building-columns'},
            {'codigo': 'addi', 'nombre': 'Addi', 'tipo': 'credito_digital', 'icono': 'fa-bag-shopping'},
            {'codigo': 'sitecredito', 'nombre': 'Sitecredito', 'tipo': 'credito_digital', 'icono': 'fa-credit-card'},
            {'codigo': 'tarjeta_credito', 'nombre': 'Tarjeta de Crédito / Datafono', 'tipo': 'tarjeta', 'icono': 'fa-credit-card'},
            {'codigo': 'transferencia', 'nombre': 'Otras Transferencias', 'tipo': 'banco', 'icono': 'fa-money-bill-transfer'},
        ]

        for m in metodos_default:
            cuenta = BankAccount.query.filter_by(codigo=m['codigo']).first()
            if not cuenta:
                nueva = BankAccount(
                    codigo=m['codigo'],
                    nombre=m['nombre'],
                    tipo=m['tipo'],
                    icono=m['icono'],
                    saldo_actual=Decimal('0.00'),
                    activo=True
                )
                db.session.add(nueva)
                print(f"[CREADO] Método de pago / banco '{m['nombre']}' registrado.")
            else:
                print(f"[EXISTE] Método '{cuenta.nombre}' ya registrado.")

        db.session.commit()
        print("=== CONFIGURACIÓN DE BANCOS Y MIGRACIÓN COMPLETADA CON ÉXITO ===")

if __name__ == '__main__':
    setup_bancos()
