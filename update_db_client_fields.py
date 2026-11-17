import sys
import os

from app import create_app
from models import db

def run_migration():
    app = create_app()
    with app.app_context():
        # SQLite / Postgres unified alter table
        columns = [
            ("email", "VARCHAR(120)"),
            ("direccion", "VARCHAR(200)")
        ]
        for col_name, col_type in columns:
            try:
                db.session.execute(db.text(f"ALTER TABLE sale_clients ADD COLUMN {col_name} {col_type}"))
                db.session.commit()
                print(f"Columna '{col_name}' agregada exitosamente.")
            except Exception as e:
                db.session.rollback()
                print(f"No se pudo agregar '{col_name}' (tal vez ya existe): {e}")

if __name__ == '__main__':
    run_migration()
