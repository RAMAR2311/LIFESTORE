import sys
from decimal import Decimal
from datetime import datetime
from app import create_app
from models import db, Product, StockAdjustment, User

def add_sample_products():
    app = create_app()
    with app.app_context():
        admin = User.query.filter_by(rol='admin').first()
        if not admin:
            admin = User.query.first()
        admin_id = admin.id if admin else 1

        print("=== AGREGANDO PRODUCTOS Y CELULARES DE EJEMPLO ===")

        # Lista de Celulares de Ejemplo
        celulares_ejemplo = [
            {
                "sku": "CEL-SMP-IP15PM",
                "nombre": "Celular Apple iPhone 15 Pro Max Titanio Natural 256GB",
                "marca": "Apple",
                "modelo_celular": "iPhone 15 Pro Max",
                "estado_celular": "Nuevo",
                "color": "Titanio Natural",
                "bateria": "100%",
                "memoria": "256GB",
                "imei": "359102847163920",
                "imei2": "359102847163921",
                "precio_costo": Decimal("4200000.00"),
                "precio_minimo": Decimal("4700000.00"),
                "precio_sugerido": Decimal("5100000.00"),
                "proveedor": "Importaciones Apple S.A.S",
                "inventario": "LOCAL 136",
                "observacion": "Celular completamente nuevo en caja sellada con 1 año de garantía de fabricante."
            },
            {
                "sku": "CEL-SMP-IP15P",
                "nombre": "Celular Apple iPhone 15 Pro Titanio Negro 128GB",
                "marca": "Apple",
                "modelo_celular": "iPhone 15 Pro",
                "estado_celular": "Usado",
                "color": "Titanio Negro",
                "bateria": "96%",
                "memoria": "128GB",
                "imei": "358491028374619",
                "imei2": "358491028374620",
                "precio_costo": Decimal("3400000.00"),
                "precio_minimo": Decimal("3850000.00"),
                "precio_sugerido": Decimal("4200000.00"),
                "proveedor": "Distribuidora Celulares S.A.S",
                "inventario": "LOCAL 197",
                "observacion": "Estado estético 9.8/10, sin rayones en pantalla, incluye cable de carga original."
            },
            {
                "sku": "CEL-SMP-IP14",
                "nombre": "Celular Apple iPhone 14 Azul 128GB",
                "marca": "Apple",
                "modelo_celular": "iPhone 14",
                "estado_celular": "Usado",
                "color": "Azul",
                "bateria": "89%",
                "memoria": "128GB",
                "imei": "357283910248572",
                "imei2": "357283910248573",
                "precio_costo": Decimal("2100000.00"),
                "precio_minimo": Decimal("2450000.00"),
                "precio_sugerido": Decimal("2700000.00"),
                "proveedor": "Distribuidora Celulares S.A.S",
                "inventario": "LOCAL 136",
                "observacion": "Excelente estado general, batería al 89%, testeado 100% funcional."
            },
            {
                "sku": "CEL-SMP-IP13",
                "nombre": "Celular Apple iPhone 13 Blanco Estelar 128GB",
                "marca": "Apple",
                "modelo_celular": "iPhone 13",
                "estado_celular": "Nuevo",
                "color": "Blanco Estelar",
                "bateria": "100%",
                "memoria": "128GB",
                "imei": "356192837465019",
                "imei2": "356192837465020",
                "precio_costo": Decimal("1850000.00"),
                "precio_minimo": Decimal("2150000.00"),
                "precio_sugerido": Decimal("2390000.00"),
                "proveedor": "Importaciones Tech",
                "inventario": "LOCAL 197",
                "observacion": "Equipo nuevo con accesorios originales."
            },
            {
                "sku": "CEL-SMP-S24U",
                "nombre": "Celular Samsung Galaxy S24 Ultra Gris Titanio 512GB",
                "marca": "Samsung",
                "modelo_celular": "Galaxy S24 Ultra",
                "estado_celular": "Nuevo",
                "color": "Gris Titanio",
                "bateria": "100%",
                "memoria": "512GB",
                "imei": "354928173645012",
                "imei2": "354928173645013",
                "precio_costo": Decimal("4100000.00"),
                "precio_minimo": Decimal("4600000.00"),
                "precio_sugerido": Decimal("4990000.00"),
                "proveedor": "Samsung Colombia SAS",
                "inventario": "LOCAL 136",
                "observacion": "Incluye S-Pen original, pantalla Dynamic AMOLED 2X, cámara 200MP."
            },
            {
                "sku": "CEL-SMP-S23FE",
                "nombre": "Celular Samsung Galaxy S23 FE Menta 256GB",
                "marca": "Samsung",
                "modelo_celular": "Galaxy S23 FE",
                "estado_celular": "Nuevo",
                "color": "Menta",
                "bateria": "100%",
                "memoria": "256GB",
                "imei": "353817264509182",
                "imei2": "353817264509183",
                "precio_costo": Decimal("1650000.00"),
                "precio_minimo": Decimal("1950000.00"),
                "precio_sugerido": Decimal("2190000.00"),
                "proveedor": "Distribuidora Celulares S.A.S",
                "inventario": "LOCAL 197",
                "observacion": "Caja sellada, garantía de 1 año con centro de servicio autorizado."
            },
            {
                "sku": "CEL-SMP-A54",
                "nombre": "Celular Samsung Galaxy A54 5G Violeta 128GB",
                "marca": "Samsung",
                "modelo_celular": "Galaxy A54 5G",
                "estado_celular": "Nuevo",
                "color": "Violeta",
                "bateria": "100%",
                "memoria": "128GB",
                "imei": "352716253419082",
                "imei2": "352716253419083",
                "precio_costo": Decimal("850000.00"),
                "precio_minimo": Decimal("1050000.00"),
                "precio_sugerido": Decimal("1190000.00"),
                "proveedor": "Distribuidora Celulares S.A.S",
                "inventario": "LOCAL 136",
                "observacion": "Resistente al agua IP67, pantalla Super AMOLED 120Hz."
            },
            {
                "sku": "CEL-SMP-RN13P",
                "nombre": "Celular Xiaomi Redmi Note 13 Pro 5G Negro 256GB",
                "marca": "Xiaomi",
                "modelo_celular": "Redmi Note 13 Pro 5G",
                "estado_celular": "Nuevo",
                "color": "Negro Medianoche",
                "bateria": "100%",
                "memoria": "256GB",
                "imei": "351928374650129",
                "imei2": "351928374650130",
                "precio_costo": Decimal("920000.00"),
                "precio_minimo": Decimal("1150000.00"),
                "precio_sugerido": Decimal("1290000.00"),
                "proveedor": "Xiaomi Direct Import",
                "inventario": "LOCAL 197",
                "observacion": "Cámara de 200MP con OIS, carga ultra rápida de 67W."
            },
            {
                "sku": "CEL-SMP-POCOF5",
                "nombre": "Celular Xiaomi Poco F5 Pro Blanco 512GB",
                "marca": "Xiaomi",
                "modelo_celular": "Poco F5 Pro",
                "estado_celular": "Usado",
                "color": "Blanco",
                "bateria": "94%",
                "memoria": "512GB",
                "imei": "350817263549018",
                "imei2": "350817263549019",
                "precio_costo": Decimal("1300000.00"),
                "precio_minimo": Decimal("1550000.00"),
                "precio_sugerido": Decimal("1750000.00"),
                "proveedor": "Importaciones Tech",
                "inventario": "LOCAL 136",
                "observacion": "Procesador Snapdragon 8+ Gen 1, pantalla 2K WQHD+, perfecto estado gamer."
            },
            {
                "sku": "CEL-SMP-MOTOE40",
                "nombre": "Celular Motorola Edge 40 Neo Azul 256GB",
                "marca": "Motorola",
                "modelo_celular": "Edge 40 Neo",
                "estado_celular": "Nuevo",
                "color": "Caneel Bay Azul",
                "bateria": "100%",
                "memoria": "256GB",
                "imei": "359716253409182",
                "imei2": "359716253409183",
                "precio_costo": Decimal("890000.00"),
                "precio_minimo": Decimal("1080000.00"),
                "precio_sugerido": Decimal("1220000.00"),
                "proveedor": "Motorola Direct",
                "inventario": "LOCAL 197",
                "observacion": "Diseño ultradelgado cuero vegano Pantone, protección IP68."
            },
            {
                "sku": "CEL-SMP-PIXEL8P",
                "nombre": "Celular Google Pixel 8 Pro Celeste 256GB",
                "marca": "Google",
                "modelo_celular": "Pixel 8 Pro",
                "estado_celular": "Usado",
                "color": "Celeste (Bay)",
                "bateria": "98%",
                "memoria": "256GB",
                "imei": "358615243309182",
                "imei2": "358615243309183",
                "precio_costo": Decimal("2400000.00"),
                "precio_minimo": Decimal("2800000.00"),
                "precio_sugerido": Decimal("3100000.00"),
                "proveedor": "Importaciones USA",
                "inventario": "LOCAL 136",
                "observacion": "Cámara con IA avanzada Google Tensor G3, libre de todo."
            },
            {
                "sku": "CEL-SMP-HONORML",
                "nombre": "Celular Honor Magic 6 Lite Verde 256GB",
                "marca": "Honor",
                "modelo_celular": "Magic 6 Lite",
                "estado_celular": "Nuevo",
                "color": "Verde Esmeralda",
                "bateria": "100%",
                "memoria": "256GB",
                "imei": "357514233209182",
                "imei2": "357514233209183",
                "precio_costo": Decimal("950000.00"),
                "precio_minimo": Decimal("1180000.00"),
                "precio_sugerido": Decimal("1350000.00"),
                "proveedor": "Honor Colombia",
                "inventario": "LOCAL 197",
                "observacion": "Pantalla Ultra Resistente anti-caídas, batería de 5300mAh."
            }
        ]

        # Lista de Accesorios / Tienda de Ejemplo
        accesorios_ejemplo = [
            {
                "sku": "ACC-ANK-65W",
                "nombre": "Cargador Rápido Anker Nano II 65W GaN USB-C",
                "tipo_inventario": "tienda",
                "cantidad_stock": 18,
                "precio_costo": Decimal("85000.00"),
                "precio_minimo": Decimal("130000.00"),
                "precio_sugerido": Decimal("155000.00"),
                "observacion": "Cargador ultracompacto para laptops, MacBooks e iPhones."
            },
            {
                "sku": "ACC-MAG-CASE15",
                "nombre": "Funda Transparente MagSafe Anticaídas iPhone 15",
                "tipo_inventario": "tienda",
                "cantidad_stock": 35,
                "precio_costo": Decimal("18000.00"),
                "precio_minimo": Decimal("35000.00"),
                "precio_sugerido": Decimal("49000.00"),
                "observacion": "Bordes reforzados y anillo magnético de alta potencia."
            },
            {
                "sku": "ACC-SCR-9DHD",
                "nombre": "Vidrio Templado Cerámico 9D Anti-Espía Privacidad",
                "tipo_inventario": "tienda",
                "cantidad_stock": 60,
                "precio_costo": Decimal("8000.00"),
                "precio_minimo": Decimal("20000.00"),
                "precio_sugerido": Decimal("28000.00"),
                "observacion": "Protección de privacidad 180° y máxima resistencia a impactos."
            },
            {
                "sku": "ACC-GBUDS2-PRO",
                "nombre": "Audífonos Inalámbricos Samsung Galaxy Buds 2 Pro",
                "tipo_inventario": "tienda",
                "cantidad_stock": 10,
                "precio_costo": Decimal("380000.00"),
                "precio_minimo": Decimal("520000.00"),
                "precio_sugerido": Decimal("590000.00"),
                "observacion": "Sonido Hi-Fi de 24 bits, cancelación activa de ruido inteligente."
            },
            {
                "sku": "ACC-PBANK-10K",
                "nombre": "Batería Portátil PowerBank MagSafe 10.000mAh 20W",
                "tipo_inventario": "tienda",
                "cantidad_stock": 14,
                "precio_costo": Decimal("75000.00"),
                "precio_minimo": Decimal("120000.00"),
                "precio_sugerido": Decimal("145000.00"),
                "observacion": "Carga inalámbrica magnética + puerto USB-C bidireccional."
            }
        ]

        inserted_count = 0

        # Insertar Celulares
        for data in celulares_ejemplo:
            existing = Product.query.filter((Product.sku == data["sku"]) | (Product.imei == data["imei"])).first()
            if not existing:
                p = Product(
                    sku=data["sku"],
                    nombre=data["nombre"],
                    tipo_inventario="celulares",
                    cantidad_stock=1, # 1 unidad con IMEI específico
                    precio_costo=data["precio_costo"],
                    precio_minimo=data["precio_minimo"],
                    precio_sugerido=data["precio_sugerido"],
                    imei=data["imei"],
                    imei2=data["imei2"],
                    marca=data["marca"],
                    modelo_celular=data["modelo_celular"],
                    estado_celular=data["estado_celular"],
                    color=data["color"],
                    bateria=data["bateria"],
                    memoria=data["memoria"],
                    proveedor=data["proveedor"],
                    inventario=data["inventario"],
                    observacion=data["observacion"]
                )
                db.session.add(p)
                db.session.flush()

                adj = StockAdjustment(
                    product_id=p.id,
                    admin_id=admin_id,
                    tipo_movimiento="Creación Inicial (Ejemplo Celular)",
                    stock_anterior=0,
                    stock_nuevo=1
                )
                db.session.add(adj)
                inserted_count += 1
                print(f" Celular agregado: {data['nombre']} (IMEI: {data['imei']})")

        # Insertar Accesorios
        for data in accesorios_ejemplo:
            existing = Product.query.filter_by(sku=data["sku"]).first()
            if not existing:
                p = Product(
                    sku=data["sku"],
                    nombre=data["nombre"],
                    tipo_inventario=data["tipo_inventario"],
                    cantidad_stock=data["cantidad_stock"],
                    precio_costo=data["precio_costo"],
                    precio_minimo=data["precio_minimo"],
                    precio_sugerido=data["precio_sugerido"],
                    observacion=data["observacion"]
                )
                db.session.add(p)
                db.session.flush()

                adj = StockAdjustment(
                    product_id=p.id,
                    admin_id=admin_id,
                    tipo_movimiento="Creación Inicial (Ejemplo Accesorio)",
                    stock_anterior=0,
                    stock_nuevo=data["cantidad_stock"]
                )
                db.session.add(adj)
                inserted_count += 1
                print(f" Accesorio agregado: {data['nombre']} (Stock: {data['cantidad_stock']})")

        db.session.commit()
        print(f"\n¡Éxito! Se insertaron {inserted_count} productos de ejemplo correctamente.")

if __name__ == '__main__':
    add_sample_products()
