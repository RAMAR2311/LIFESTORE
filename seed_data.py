import os
from decimal import Decimal
from datetime import datetime, timedelta
from app import create_app
from models import (
    db, Product, ProductVariant, Sale, SaleDetail, SalePayment, 
    SaleClient, Asesor, User, Provider, ArqueoCaja, obtener_hora_bogota
)
from werkzeug.security import generate_password_hash

def seed_data():
    app = create_app()
    with app.app_context():
        print("Iniciando la inserción de datos de prueba...")

        # 1. Crear Vendedores / Usuarios de prueba si no existen
        admin = User.query.filter_by(email="admin@lifestore.com").first()
        if not admin:
            admin = User(
                nombre="Administrador LifeStore",
                email="admin@lifestore.com",
                telefono="3001234567",
                rol="admin",
                sucursal="PRINCIPAL",
                password_hash=generate_password_hash("Admin123")
            )
            db.session.add(admin)
            print("Administrador creado: admin@lifestore.com / Admin123")

        vendedor = User.query.filter_by(email="vendedor@lifestore.com").first()
        if not vendedor:
            vendedor = User(
                nombre="Cajero Central",
                email="vendedor@lifestore.com",
                telefono="3007654321",
                rol="vendedor",
                sucursal="PRINCIPAL",
                password_hash=generate_password_hash("ventas123")
            )
            db.session.add(vendedor)
            print("Vendedor creado: vendedor@lifestore.com / ventas123")

        db.session.commit()

        # 2. Crear Asesores de Venta
        asesor1 = Asesor.query.filter_by(nombre="Juan Pérez").first()
        if not asesor1:
            asesor1 = Asesor(nombre="Juan Pérez", activo=True)
            db.session.add(asesor1)
            
        asesor2 = Asesor.query.filter_by(nombre="Carolina Gómez").first()
        if not asesor2:
            asesor2 = Asesor(nombre="Carolina Gómez", activo=True)
            db.session.add(asesor2)

        asesor3 = Asesor.query.filter_by(nombre="Andrés Mendoza").first()
        if not asesor3:
            asesor3 = Asesor(nombre="Andrés Mendoza", activo=True)
            db.session.add(asesor3)

        db.session.commit()
        print("Asesores de prueba creados.")

        # 3. Crear Proveedores de prueba
        prov1 = Provider.query.filter_by(nombre="Distribuidora Celulares S.A.S").first()
        if not prov1:
            prov1 = Provider(
                nombre="Distribuidora Celulares S.A.S",
                empresa="Distribuidora Celulares S.A.S",
                telefono="3109876543"
            )
            db.session.add(prov1)

        prov2 = Provider.query.filter_by(nombre="Accesorios y Tecnología Mayorista").first()
        if not prov2:
            prov2 = Provider(
                nombre="Accesorios y Tecnología Mayorista",
                empresa="Accesorios y Tecnología Mayorista",
                telefono="3201234567"
            )
            db.session.add(prov2)

        db.session.commit()
        print("Proveedores de prueba creados.")

        # 4. Crear Productos (Accesorios y Celulares)
        p_acc1 = Product.query.filter_by(sku="ACC-001").first()
        if not p_acc1:
            p_acc1 = Product(
                nombre="Audífonos AirPods Pro 2da Gen",
                sku="ACC-001",
                tipo_inventario="tienda",
                cantidad_stock=25,
                precio_costo=Decimal("450000.00"),
                precio_minimo=Decimal("580000.00"),
                precio_sugerido=Decimal("650000.00"),
                observacion="Sonido de alta definición y cancelación activa de ruido"
            )
            db.session.add(p_acc1)

        p_acc2 = Product.query.filter_by(sku="ACC-002").first()
        if not p_acc2:
            p_acc2 = Product(
                nombre="Cargador Carga Rápida 20W Apple",
                sku="ACC-002",
                tipo_inventario="tienda",
                cantidad_stock=50,
                precio_costo=Decimal("45000.00"),
                precio_minimo=Decimal("65000.00"),
                precio_sugerido=Decimal("89000.00"),
                observacion="Adaptador de corriente USB-C de carga ultra rápida"
            )
            db.session.add(p_acc2)

        p_cel1 = Product.query.filter_by(sku="CEL-001").first()
        if not p_cel1:
            p_cel1 = Product(
                nombre="iPhone 13 Pro Max 128GB - Grafito",
                sku="CEL-001",
                tipo_inventario="celulares",
                cantidad_stock=1,
                precio_costo=Decimal("2100000.00"),
                precio_minimo=Decimal("2600000.00"),
                precio_sugerido=Decimal("2800000.00"),
                imei="358901234567891",
                imei2="358901234567892",
                marca="Apple",
                modelo_celular="iPhone 13 Pro Max",
                estado_celular="Usado",
                color="Grafito",
                bateria="88%",
                memoria="128GB",
                proveedor="Distribuidora Celulares S.A.S",
                observacion="Pantalla original con leves marcas de uso, 8 meses de garantía."
            )
            db.session.add(p_cel1)

        p_cel2 = Product.query.filter_by(sku="CEL-002").first()
        if not p_cel2:
            p_cel2 = Product(
                nombre="Samsung Galaxy S22 Ultra 256GB",
                sku="CEL-002",
                tipo_inventario="celulares",
                cantidad_stock=1,
                precio_costo=Decimal("1800000.00"),
                precio_minimo=Decimal("2200000.00"),
                precio_sugerido=Decimal("2450000.00"),
                imei="352345678901234",
                imei2="352345678901235",
                marca="Samsung",
                modelo_celular="Galaxy S22 Ultra",
                estado_celular="Nuevo",
                color="Negro",
                bateria="100%",
                memoria="256GB",
                proveedor="Distribuidora Celulares S.A.S",
                observacion="Caja sellada de fábrica, 1 año de garantía."
            )
            db.session.add(p_cel2)

        db.session.commit()
        print("Productos de prueba creados.")

        # 5. Crear Ventas de prueba
        # Venta 1: Venta de celulares del Asesor 1
        sale1 = Sale.query.filter_by(id=1).first()
        if not sale1:
            sale1 = Sale(
                vendedor_id=vendedor.id if vendedor else admin.id,
                asesor_id=asesor1.id,
                monto_total=Decimal("2750000.00"),
                metodo_pago="efectivo",
                tipo_venta="celulares",
                sucursal="PRINCIPAL",
                fecha_venta=obtener_hora_bogota() - timedelta(days=2)
            )
            db.session.add(sale1)
            db.session.flush()

            # Detalle
            det1 = SaleDetail(
                sale_id=sale1.id,
                product_id=p_cel1.id,
                cantidad_vendida=1,
                precio_venta_final=Decimal("2750000.00")
            )
            db.session.add(det1)

            # Pagos
            pago1 = SalePayment(
                sale_id=sale1.id,
                metodo_pago="efectivo",
                monto=Decimal("2750000.00")
            )
            db.session.add(pago1)

            # Cliente
            cli1 = SaleClient(
                sale_id=sale1.id,
                nombre="Jhon Aparicio",
                documento="1004910859",
                telefono="3505422680",
                email="jhon.aparicio@icloud.com",
                direccion="Calle 52b Bis #851"
            )
            db.session.add(cli1)

        # Venta 2: Venta de accesorios del Asesor 2 (Pago Dividido)
        sale2 = Sale.query.filter_by(id=2).first()
        if not sale2:
            sale2 = Sale(
                vendedor_id=admin.id,
                asesor_id=asesor2.id,
                monto_total=Decimal("739000.00"),
                metodo_pago="mixto",
                tipo_venta="general",
                sucursal="PRINCIPAL",
                fecha_venta=obtener_hora_bogota() - timedelta(days=1)
            )
            db.session.add(sale2)
            db.session.flush()

            # Detalle 1: AirPods
            det2_1 = SaleDetail(
                sale_id=sale2.id,
                product_id=p_acc1.id,
                cantidad_vendida=1,
                precio_venta_final=Decimal("650000.00")
            )
            db.session.add(det2_1)

            # Detalle 2: Cargador
            det2_2 = SaleDetail(
                sale_id=sale2.id,
                product_id=p_acc2.id,
                cantidad_vendida=1,
                precio_venta_final=Decimal("89000.00")
            )
            db.session.add(det2_2)

            # Pagos Divididos
            pago2_1 = SalePayment(
                sale_id=sale2.id,
                metodo_pago="efectivo",
                monto=Decimal("300000.00")
            )
            pago2_2 = SalePayment(
                sale_id=sale2.id,
                metodo_pago="bancolombia",
                monto=Decimal("439000.00")
            )
            db.session.add(pago2_1)
            db.session.add(pago2_2)

            # Cliente
            cli2 = SaleClient(
                sale_id=sale2.id,
                nombre="Milena Restrepo",
                documento="1017483921",
                telefono="3125556789",
                email="milena@gmail.com",
                direccion="Avenida del Río #45-12"
            )
            db.session.add(cli2)

        db.session.commit()
        print("Ventas y clientes de prueba insertados.")

        # 6. Crear un Arqueo de Caja de prueba cerrado
        fecha_arqueo = obtener_hora_bogota().date() - timedelta(days=1)
        arq_existente = ArqueoCaja.query.filter_by(
            fecha_arqueo=fecha_arqueo, 
            tipo_arqueo="general"
        ).first()
        
        if not arq_existente:
            arq = ArqueoCaja(
                fecha_arqueo=fecha_arqueo,
                vendedor_id=admin.id,
                sucursal="PRINCIPAL",
                tipo_arqueo="general",
                base_inicial=200000.0,
                total_efectivo_sistema=300000.0,      # El pago efectivo de la venta 2
                total_transferencia_sistema=439000.0, # El pago por Bancolombia de la venta 2
                gastos_del_dia=0.0,
                observaciones_gastos="Sin novedades de gastos el día de ayer."
            )
            db.session.add(arq)
            db.session.commit()
            print("Arqueo de prueba cerrado registrado exitosamente.")

        print("\n¡Datos de prueba sembrados exitosamente!")
        print("Usuarios de prueba para login:")
        print("- Admin: admin@lifestore.com / contraseña: Admin123")
        print("- Vendedor: vendedor@lifestore.com / contraseña: ventas123")

if __name__ == '__main__':
    seed_data()
