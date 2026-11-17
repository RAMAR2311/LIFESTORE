from app import create_app
from models import db

def migrar_a_sucursal_unica():
    app = create_app()
    with app.app_context():
        try:
            print("Iniciando unificación de sucursales a 'PRINCIPAL'...")
            
            u_count = db.session.execute(db.text("UPDATE users SET sucursal = 'PRINCIPAL'")).rowcount
            s_count = db.session.execute(db.text("UPDATE sales SET sucursal = 'PRINCIPAL'")).rowcount
            e_count = db.session.execute(db.text("UPDATE expenses SET sucursal = 'PRINCIPAL'")).rowcount
            a_count = db.session.execute(db.text("UPDATE arqueo_caja SET sucursal = 'PRINCIPAL'")).rowcount
            
            # Check if sobrantes_log exists and update
            try:
                sob_count = db.session.execute(db.text("UPDATE sobrantes_log SET sucursal = 'PRINCIPAL'")).rowcount
            except Exception as e_sob:
                sob_count = 0
                print(f"Nota en sobrantes_log: {e_sob}")
                
            # Actualizar inventario en productos si decían LOCAL 136 o LOCAL 197
            try:
                p_count = db.session.execute(db.text("UPDATE products SET inventario = 'PRINCIPAL' WHERE inventario IN ('LOCAL 136', 'LOCAL 197', 'LOCAL 137')")).rowcount
            except Exception as e_p:
                p_count = 0
                print(f"Nota en products: {e_p}")

            db.session.commit()
            print("¡Unificación completada con éxito!")
            print(f"- Usuarios unificados: {u_count}")
            print(f"- Ventas unificadas: {s_count}")
            print(f"- Gastos unificados: {e_count}")
            print(f"- Arqueos unificados: {a_count}")
            print(f"- Sobrantes unificados: {sob_count}")
            print(f"- Productos (inventario) unificados: {p_count}")
        except Exception as e:
            db.session.rollback()
            print(f"Error al ejecutar la unificación: {e}")

if __name__ == '__main__':
    migrar_a_sucursal_unica()
