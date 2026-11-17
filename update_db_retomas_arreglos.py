import sys
import os

from app import create_app
from models import db

def run_migration():
    app = create_app()
    with app.app_context():
        try:
            db.session.execute(db.text("ALTER TABLE retomas ADD COLUMN arreglos NUMERIC(10, 2) DEFAULT 0.0"))
            db.session.commit()
            print("Columna 'arreglos' agregada exitosamente a la tabla 'retomas'.")
        except Exception as e:
            db.session.rollback()
            print(f"No se pudo agregar 'arreglos' (tal vez ya existe): {e}")

if __name__ == '__main__':
    run_migration()
