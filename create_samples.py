from app import create_app
from models import db, Product, ProductVariant, StockAdjustment, User

def create_sample_products():
    app = create_app()
    with app.app_context():
        # Get an admin user for the stock adjustments
        admin = User.query.filter_by(rol='admin').first()
        if not admin:
            admin = User.query.first()
            
        admin_id = admin.id if admin else 1

        print("Creating sample products...")

        # 1. Product without variants
        prod1 = Product(
            sku="ACC-USB-001",
            nombre="Cable USB-C a USB-C Trenzado 2m",
            tipo_inventario="tienda",
            cantidad_stock=45,
            precio_costo=5000,
            precio_minimo=12000,
            precio_sugerido=15000,
            observacion="Cable de carga rápida, muy resistente."
        )
        db.session.add(prod1)
        db.session.flush()

        adj1 = StockAdjustment(
            product_id=prod1.id,
            admin_id=admin_id,
            tipo_movimiento='Creación Inicial (Ejemplo)',
            stock_anterior=0,
            stock_nuevo=45
        )
        db.session.add(adj1)

        # 2. Product with variants (Different Colors)
        prod2 = Product(
            sku="AUD-BT-005",
            nombre="Audífonos Inalámbricos ProMax",
            tipo_inventario="tienda",
            cantidad_stock=0, # Base stock is 0 when there are variants
            precio_costo=35000,
            precio_minimo=65000,
            precio_sugerido=80000,
            observacion="Alta calidad de sonido con cancelación de ruido activa."
        )
        db.session.add(prod2)
        db.session.flush()

        variantes_prod2 = [
            ("Negro Mate", 15, 35000, 65000, 80000),
            ("Blanco Perla", 8, 35000, 65000, 80000),
            ("Edición Roja", 5, 38000, 70000, 90000) # Slightly more expensive
        ]

        for nombre, stock, costo, min_p, sug_p in variantes_prod2:
            v = ProductVariant(
                product_id=prod2.id,
                nombre_variante=nombre,
                cantidad_stock=stock,
                precio_costo=costo,
                precio_minimo=min_p,
                precio_sugerido=sug_p
            )
            db.session.add(v)
            
            adj = StockAdjustment(
                product_id=prod2.id,
                admin_id=admin_id,
                tipo_movimiento=f'Creación Subcategoría: {nombre}',
                stock_anterior=0,
                stock_nuevo=stock
            )
            db.session.add(adj)

        # 3. Product with variants (Different Storage/Sizes)
        prod3 = Product(
            sku="MEM-SD-128",
            nombre="Memoria MicroSD Extreme",
            tipo_inventario="tienda", 
            cantidad_stock=0,
            precio_costo=20000,
            precio_minimo=35000,
            precio_sugerido=45000
        )
        db.session.add(prod3)
        db.session.flush()

        variantes_prod3 = [
            ("64 GB", 30, 15000, 25000, 35000),
            ("128 GB", 20, 20000, 35000, 45000),
            ("256 GB", 10, 40000, 65000, 80000)
        ]

        for nombre, stock, costo, min_p, sug_p in variantes_prod3:
            v = ProductVariant(
                product_id=prod3.id,
                nombre_variante=nombre,
                cantidad_stock=stock,
                precio_costo=costo,
                precio_minimo=min_p,
                precio_sugerido=sug_p
            )
            db.session.add(v)
            
            adj = StockAdjustment(
                product_id=prod3.id,
                admin_id=admin_id,
                tipo_movimiento=f'Creación Subcategoría: {nombre}',
                stock_anterior=0,
                stock_nuevo=stock
            )
            db.session.add(adj)

        db.session.commit()
        print("Sample products with variants created successfully!")

if __name__ == '__main__':
    create_sample_products()
