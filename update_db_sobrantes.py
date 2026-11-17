from app import create_app
from models import db, SobranteLog

app = create_app()

with app.app_context():
    print("[INFO] Actualizando la base de datos para el módulo Log de Sobrantes...")
    
    # 1. Crear tabla sobrantes_log y agregar columnas a arqueo_caja si no existen
    db.create_all()
    
    # Inspeccionar columnas en la base de datos local
    inspector = db.inspect(db.engine)
    columns_arqueo = [c['name'] for c in inspector.get_columns('arqueo_caja')]
    
    columns_retomas = [c['name'] for c in inspector.get_columns('retomas')]
    columns_sale_details = [c['name'] for c in inspector.get_columns('sale_details')]
    
    with db.engine.connect() as conn:
        if 'efectivo_fisico' not in columns_arqueo:
            conn.execute(db.text("ALTER TABLE arqueo_caja ADD COLUMN efectivo_fisico NUMERIC(14, 2) DEFAULT 0.0"))
            print("  + Agregada columna 'efectivo_fisico' a tabla arqueo_caja")
        if 'diferencia' not in columns_arqueo:
            conn.execute(db.text("ALTER TABLE arqueo_caja ADD COLUMN diferencia NUMERIC(14, 2) DEFAULT 0.0"))
            print("  + Agregada columna 'diferencia' a tabla arqueo_caja")
        if 'observacion_diferencia' not in columns_arqueo:
            conn.execute(db.text("ALTER TABLE arqueo_caja ADD COLUMN observacion_diferencia TEXT"))
            print("  + Agregada columna 'observacion_diferencia' a tabla arqueo_caja")
            
        if 'ok_contabilidad' not in columns_retomas:
            conn.execute(db.text("ALTER TABLE retomas ADD COLUMN ok_contabilidad BOOLEAN DEFAULT FALSE"))
            print("  + Agregada columna 'ok_contabilidad' a tabla retomas")

        if 'ok_contabilidad' not in columns_sale_details:
            conn.execute(db.text("ALTER TABLE sale_details ADD COLUMN ok_contabilidad BOOLEAN DEFAULT FALSE"))
            print("  + Agregada columna 'ok_contabilidad' a tabla sale_details")
            
        if 'ok_inventario' not in columns_sale_details:
            conn.execute(db.text("ALTER TABLE sale_details ADD COLUMN ok_inventario BOOLEAN DEFAULT FALSE"))
            print("  + Agregada columna 'ok_inventario' a tabla sale_details")
            
        conn.commit()

    print("[ÉXITO] Base de datos actualizada correctamente.")
