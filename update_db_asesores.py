from app import create_app
from models import db

def run_migration():
    app = create_app()
    with app.app_context():
        # 1. Crear tabla asesores si no existe (SQLAlchemy db.create_all() creará la nueva tabla automáticamente)
        try:
            db.create_all()
            print("Tabla 'asesores' validada/creada exitosamente.")
        except Exception as e:
            print(f"Error al validar/crear tablas: {e}")
            
        # 2. Agregar columna asesor_id a la tabla sales
        try:
            db.session.execute(db.text("ALTER TABLE sales ADD COLUMN asesor_id INTEGER"))
            db.session.commit()
            print("Columna 'asesor_id' agregada exitosamente a la tabla 'sales'.")
        except Exception as e:
            db.session.rollback()
            print(f"No se pudo agregar 'asesor_id' a 'sales' (tal vez ya existe): {e}")

if __name__ == '__main__':
    run_migration()
