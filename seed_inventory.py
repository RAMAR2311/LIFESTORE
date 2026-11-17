import csv
import sys
from app import create_app
from models import db, Product

def seed_inventory_from_csv(csv_filepath='inventario.csv'):
    app = create_app()
    with app.app_context():
        try:
            with open(csv_filepath, mode='r', encoding='utf-8') as file:
                reader = csv.DictReader(file)
                productos_a_insertar = []
                
                fila_actual = 1
                
                for row in reader:
                    fila_actual += 1
                    try:
                        item = dict(
                            nombre=row['nombre'].strip(),
                            sku=row['sku'].strip(),
                            cantidad_stock=int(row['cantidad_stock'].strip()),
                            precio_minimo=float(row['precio_minimo'].strip()),
                            precio_sugerido=float(row['precio_sugerido'].strip())
                        )
                        productos_a_insertar.append(item)
                        
                    except (KeyError, ValueError) as format_error:
                        print(f"[ERROR] Detectado leyendo el CSV en la FILA {fila_actual}: {format_error}")
                        print(f"-> Contenido problematico: {row}")
                        print("-> Abortando. Ningun registro fue modificado.")
                        return

                if not productos_a_insertar:
                    print("[ADVERTENCIA] El archivo CSV esta vacio.")
                    return

                try:
                    db.session.bulk_insert_mappings(Product, productos_a_insertar)
                    db.session.commit()
                    print(f"[EXITO] Se importaron masivamente {len(productos_a_insertar)} productos de forma segura.")
                
                except Exception as insert_error:
                    db.session.rollback()
                    print(f"[ERROR] Ocurrio un fallo en base de datos: {insert_error}")
                    print("-> Se ejecuto Rollback. La base de datos sigue intacta.")

        except FileNotFoundError:
            print(f"[ERROR] No se encontro el archivo '{csv_filepath}'.")
        except Exception as unexpected_error:
            print(f"[ERROR] Hubo un error al leer el archivo: {unexpected_error}")


if __name__ == '__main__':
    ruta = sys.argv[1] if len(sys.argv) > 1 else 'inventario.csv'
    seed_inventory_from_csv(ruta)
