from app import create_app
from models import db

def run_migrations():
    app = create_app()
    with app.app_context():
        queries = [
            ("provider_invoices.sale_id", "ALTER TABLE provider_invoices ADD COLUMN sale_id INTEGER REFERENCES sales(id) ON DELETE SET NULL;"),
            ("sales.provider_id", "ALTER TABLE sales ADD COLUMN provider_id INTEGER REFERENCES providers(id) ON DELETE SET NULL;"),
            ("sales.asesor_id", "ALTER TABLE sales ADD COLUMN asesor_id INTEGER REFERENCES asesores(id) ON DELETE SET NULL;"),
            ("retomas.arreglos", "ALTER TABLE retomas ADD COLUMN arreglos NUMERIC(10, 2) DEFAULT 0.0;"),
            ("retomas.ok_contabilidad", "ALTER TABLE retomas ADD COLUMN ok_contabilidad BOOLEAN DEFAULT FALSE;"),
            ("sale_details.ok_contabilidad", "ALTER TABLE sale_details ADD COLUMN ok_contabilidad BOOLEAN DEFAULT FALSE;"),
            ("sale_details.ok_inventario", "ALTER TABLE sale_details ADD COLUMN ok_inventario BOOLEAN DEFAULT FALSE;"),
            ("arqueo_caja.efectivo_fisico", "ALTER TABLE arqueo_caja ADD COLUMN efectivo_fisico NUMERIC(14, 2) DEFAULT 0.0;"),
            ("arqueo_caja.diferencia", "ALTER TABLE arqueo_caja ADD COLUMN diferencia NUMERIC(14, 2) DEFAULT 0.0;"),
            ("arqueo_caja.observacion_diferencia", "ALTER TABLE arqueo_caja ADD COLUMN observacion_diferencia TEXT;")
        ]
        
        print("=== ACTUALIZANDO ESQUEMA DE BASE DE DATOS ===")
        for col_name, q in queries:
            try:
                db.session.execute(db.text(q))
                db.session.commit()
                print(f"[EXITO] Columna '{col_name}' añadida a la base de datos.")
            except Exception as e:
                db.session.rollback()
                print(f"[OMITIDO] Columna '{col_name}' ya existía o no requiere cambios.")

if __name__ == '__main__':
    run_migrations()
