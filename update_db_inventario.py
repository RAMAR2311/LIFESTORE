import psycopg2
import os

# Intenta obtener la URL de la base de datos desde las variables de entorno
db_url = os.environ.get('DATABASE_URL', 'postgresql://postgres:admin123@localhost:5432/RC')

try:
    print(f"Conectando a la base de datos...")
    conn = psycopg2.connect(db_url)
    cur = conn.cursor()
    
    print("Agregando la columna 'inventario' a la tabla 'products'...")
    cur.execute('ALTER TABLE products ADD COLUMN inventario VARCHAR(100);')
    
    conn.commit()
    print("¡La columna se agregó exitosamente!")
    
    cur.close()
    conn.close()
except psycopg2.errors.DuplicateColumn:
    print("La columna 'inventario' ya existe en la tabla 'products'. No se requieren cambios.")
except Exception as e:
    print(f"Ocurrió un error: {str(e)}")
