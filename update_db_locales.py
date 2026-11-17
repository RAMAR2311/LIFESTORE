from app import create_app
from models import db

def update_locales():
    app = create_app()
    with app.app_context():
        try:
            # 1. Actualizar usuarios
            u_count = db.session.execute(db.text("UPDATE users SET sucursal = 'LOCAL 197' WHERE sucursal = 'LOCAL 137'")).rowcount
            
            # 2. Actualizar ventas
            s_count = db.session.execute(db.text("UPDATE sales SET sucursal = 'LOCAL 197' WHERE sucursal = 'LOCAL 137'")).rowcount
            
            # 3. Actualizar gastos
            e_count = db.session.execute(db.text("UPDATE expenses SET sucursal = 'LOCAL 197' WHERE sucursal = 'LOCAL 137'")).rowcount
            
            # 4. Actualizar arqueo_caja
            a_count = db.session.execute(db.text("UPDATE arqueo_caja SET sucursal = 'LOCAL 197' WHERE sucursal = 'LOCAL 137'")).rowcount
            
            db.session.commit()
            print("Migración de sucursal finalizada con éxito:")
            print(f"- Usuarios actualizados: {u_count}")
            print(f"- Ventas actualizadas: {s_count}")
            print(f"- Gastos actualizados: {e_count}")
            print(f"- Arqueos actualizados: {a_count}")
        except Exception as e:
            db.session.rollback()
            print(f"Error al migrar los registros de sucursal: {e}")

if __name__ == '__main__':
    update_locales()
