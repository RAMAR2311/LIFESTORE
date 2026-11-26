"""
Sembrador integral de datos de demostración para TODOS los módulos de LifeStore.
Ejecución: python seed_all_modules_demo.py
"""
import json
from decimal import Decimal
from datetime import datetime, timedelta, time
from werkzeug.security import generate_password_hash

from app import create_app
from models import (
    db, Branch, BranchStock, User, Asesor, Product, ProductVariant,
    Sale, SaleDetail, SalePayment, SaleClient, CashShift, ArqueoCaja, SobranteLog,
    Retoma, RetomaImportBatch, Provider, ProviderInvoice, ProviderPayment,
    PurchaseOrder, PurchaseOrderItem, Warranty, AccessoryLoss,
    Technician, TechnicalService, StockTransfer, StockTransferItem,
    ExchangePartner, DeviceExchange, Maneo, Expense, Vale, CommissionPayment,
    BankAccount, BankTransaction, PriceApproval, GiftCombo, GiftComboItem,
    StockAdjustment, AuditLog, Cliente, FacturaBodega, FacturaBodegaDetalle, AbonoBodega,
    obtener_hora_bogota
)
from services.stock_service import get_or_create_branch_stock, sync_global_product_stock


def seed_all():
    app = create_app()
    with app.app_context():
        db.create_all()
        hoy = obtener_hora_bogota()
        ayer = hoy - timedelta(days=1)
        hace_5_meses = hoy - timedelta(days=150)

        # ------------------------------------------------------------------
        # 1. SUCURSALES Y BODEGA
        # ------------------------------------------------------------------
        def ensure_branch(codigo, nombre, tipo, direccion, tel, comercial, nit, prefijo):
            b = Branch.query.filter((Branch.codigo == codigo) | (Branch.nombre == nombre)).first()
            if not b:
                b = Branch(
                    codigo=codigo, nombre=nombre, tipo=tipo, direccion=direccion,
                    telefono=tel, nombre_comercial=comercial, nit=nit,
                    prefijo_factura=prefijo, ultimo_consecutivo=10, activa=True
                )
                db.session.add(b)
                db.session.flush()
            else:
                b.activa = True
                b.tipo = tipo
                b.nombre_comercial = b.nombre_comercial or comercial
                b.nit = b.nit or nit
                b.prefijo_factura = b.prefijo_factura or prefijo
            return b

        loc181 = ensure_branch(
            'LOC181', 'LOCAL 181', 'tienda',
            'Carrera 38 # 9-32 Centro Comercial Caribe Local 181', '3212320759',
            'DOLIFE TECHNOLOGY S.A.S.', '902048858', 'REM181'
        )
        loc2140 = ensure_branch(
            'LOC2140', 'LOCAL 2140', 'tienda',
            'Carrera 38 # 9-32 Centro Comercial Caribe Local 2140', '3197556892',
            'LIFE STORE AS', '901458789-2', 'FAC2140'
        )
        bodega = ensure_branch(
            'BOD', 'BODEGA PRINCIPAL', 'bodega',
            'Centro Logístico Bodega Central Piso 2', '3004455667',
            'LIFESTORE BODEGA CENTRAL', '901458789-2', 'BOD'
        )

        # ------------------------------------------------------------------
        # 2. USUARIOS Y ASESORES
        # ------------------------------------------------------------------
        def ensure_user(email, nombre, rol, branch_obj=None, pwd='Admin123'):
            u = User.query.filter_by(email=email).first()
            if not u:
                u = User(
                    nombre=nombre, email=email,
                    password_hash=generate_password_hash(pwd),
                    rol=rol,
                    branch_id=branch_obj.id if branch_obj else None,
                    sucursal=branch_obj.nombre if branch_obj else 'PRINCIPAL'
                )
                db.session.add(u)
                db.session.flush()
            return u

        admin = ensure_user('admin@lifestore.com', 'Administrador LifeStore', 'admin', None, 'Admin123')
        cajero181 = ensure_user('local181@lifestore.com', 'Cajero Local 181', 'vendedor', loc181, 'Local123')
        cajero2140 = ensure_user('local2140@lifestore.com', 'Cajero Local 2140', 'vendedor', loc2140, 'Local123')
        bodeguero = ensure_user('bodega@lifestore.com', 'Jefe de Bodega', 'bodega', bodega, 'Bodega123')
        coordinador = ensure_user('coordinador@lifestore.com', 'Coordinador Comercial', 'coordinador', loc181, 'Coord123')

        asesores_spec = [
            ('ASE-01', 'Sebastian Prieto', 1400000),
            ('ASE-02', 'Danna Diaz', 1400000),
            ('ASE-03', 'Javier Rodriguez', 1350000),
            ('ASE-04', 'Johana Galindo', 1350000),
            ('ASE-05', 'Carlos Gómez', 1500000),
        ]
        asesores_list = []
        for cod, nom, sal in asesores_spec:
            a = Asesor.query.filter((Asesor.codigo == cod) | (Asesor.nombre == nom)).first()
            if not a:
                a = Asesor(codigo=cod, nombre=nom, salario_base=sal, activo=True)
                db.session.add(a)
                db.session.flush()
            else:
                a.activo = True
                if not a.salario_base or float(a.salario_base) == 0:
                    a.salario_base = sal
            asesores_list.append(a)
        ase1, ase2, ase3, ase4, ase5 = asesores_list

        # ------------------------------------------------------------------
        # 3. PROVEEDORES
        # ------------------------------------------------------------------
        def ensure_provider(nombre, empresa, tel):
            p = Provider.query.filter_by(nombre=nombre).first()
            if not p:
                p = Provider(nombre=nombre, empresa=empresa, telefono=tel)
                db.session.add(p)
                db.session.flush()
            return p

        prov_gio = ensure_provider('GIOTECH', 'Giotech Mayorista Apple & Samsung', '3115090853')
        prov_car = ensure_provider('CARMACEL', 'Carmacel Repuestos y Equipos S.A.S.', '3125556677')
        prov_imp = ensure_provider('IMPORTACIONES CARIBE', 'Importaciones Tecnológicas Caribe', '3158899001')

        # ------------------------------------------------------------------
        # 4. INVENTARIO DE CELULARES (ACTIVOS + ESTANCADOS)
        # ------------------------------------------------------------------
        celulares_demo = [
            ('CEL-IP16PM-256-NAT', 'Apple', 'iPhone 16 Pro Max', '256GB', '100%', 'TITANIO NATURAL', '359110029384711', 4200000, 4550000, 4790000, loc181, 'GIOTECH', hoy),
            ('CEL-IP16P-128-NEG', 'Apple', 'iPhone 16 Pro', '128GB', '100%', 'TITANIO NEGRO', '359110029384712', 3500000, 3850000, 3990000, loc181, 'GIOTECH', hoy),
            ('CEL-IP16P-256-DES', 'Apple', 'iPhone 16 Pro', '256GB', '98%', 'TITANIO DESIERTO', '359110029384713', 3750000, 4100000, 4290000, loc2140, 'GIOTECH', hoy),
            ('CEL-IP15PM-256-AZU', 'Apple', 'iPhone 15 Pro Max', '256GB', '94%', 'AZUL TITANIO', '359110029384714', 3250000, 3590000, 3750000, loc2140, 'CARMACEL', hoy),
            ('CEL-IP15PM-512-BLA', 'Apple', 'iPhone 15 Pro Max', '512GB', '96%', 'BLANCO TITANIO', '359110029384715', 3600000, 3950000, 4150000, loc181, 'CARMACEL', hoy),
            ('CEL-IP14PM-256-MOR', 'Apple', 'iPhone 14 Pro Max', '256GB', '89%', 'MORADO OSCURO', '359110029384716', 2550000, 2850000, 2990000, loc181, 'GIOTECH', hoy),
            ('CEL-IP13-128-BLA', 'Apple', 'iPhone 13', '128GB', '91%', 'BLANCO ESTELAR', '359110029384717', 1480000, 1720000, 1850000, loc2140, 'Cliente Retoma', hoy),
            ('CEL-S24U-512-GRI', 'Samsung', 'Galaxy S24 Ultra', '512GB', '100%', 'GRIS TITANIO', '359110029384718', 3600000, 3950000, 4190000, bodega, 'IMPORTACIONES CARIBE', hoy),
            # 2 Equipos estancados (> 4 meses) para el módulo Alertas de Equipos
            ('CEL-IP12P-128-ORO-EST', 'Apple', 'iPhone 12 Pro', '128GB', '84%', 'DORADO', '359110029384719', 1350000, 1580000, 1690000, loc181, 'CARMACEL', hace_5_meses),
            ('CEL-IP11PM-256-VER-EST', 'Apple', 'iPhone 11 Pro Max', '256GB', '82%', 'VERDE NOCHE', '359110029384720', 1150000, 1380000, 1490000, loc2140, 'GIOTECH', hace_5_meses),
        ]
        cel_objs = []
        for sku, marca, mod, mem, bat, col, imei, cos, pmin, psug, sede_obj, prov_nom, f_crea in celulares_demo:
            c = Product.query.filter((Product.imei == imei) | (Product.sku == sku)).first()
            if not c:
                c = Product(
                    sku=sku,
                    nombre=f"{marca} {mod} {mem} {col}",
                    marca=marca,
                    modelo_celular=mod,
                    memoria=mem,
                    bateria=bat,
                    color=col,
                    imei=imei,
                    tipo_inventario='celulares',
                    estado_celular='Seminuevo' if bat != '100%' else 'Nuevo',
                    precio_costo=Decimal(str(cos)),
                    precio_minimo=Decimal(str(pmin)),
                    precio_sugerido=Decimal(str(psug)),
                    proveedor=prov_nom,
                    inventario=sede_obj.nombre,
                    cantidad_stock=1,
                    fecha_creacion=f_crea
                )
                db.session.add(c)
                db.session.flush()
                bs = get_or_create_branch_stock(sede_obj.id, c.id, None)
                bs.cantidad = 1
                db.session.flush()
                sync_global_product_stock(c.id, None)
            cel_objs.append(c)

        # ------------------------------------------------------------------
        # 5. INVENTARIO DE ACCESORIOS + VARIANTES + COMBOS DE OBSEQUIOS
        # ------------------------------------------------------------------
        accesorios_demo = [
            ('ACC-VID-15PM', 'VIDRIO TEMPLADO 9D IPHONE 15 PRO MAX', 4500, 15000, 25000, 45, 35, 120),
            ('ACC-VID-16PM', 'VIDRIO TEMPLADO PRIVACIDAD IPHONE 16 PRO MAX', 6500, 20000, 35000, 30, 28, 90),
            ('ACC-CAR-20W-ORI', 'CARGADOR APPLE 20W ORIGINAL USB-C BLANCO', 32000, 65000, 100000, 22, 18, 60),
            ('ACC-CAB-CL1-BLA', 'CABLE TIPO C A LIGHTNING 1M CERTIFICADO BLANCO', 12000, 25000, 45000, 35, 30, 80),
            ('ACC-CAB-CC2-TRZ', 'CABLE USB-C A USB-C 2M TRENZADO 60W', 14000, 28000, 48000, 25, 20, 50),
            ('ACC-MAG-BAT-5K', 'BATERIA MAGSAFE BATTERY PACK 5000MAH', 48000, 85000, 120000, 12, 10, 30),
            ('ACC-AIR-PRO2-OEM', 'AUDIFONOS AIRPODS PRO 2DA GEN USB-C', 65000, 115000, 160000, 15, 12, 40),
            ('ACC-PRO-CAM-15P', 'PROTECTOR DE CAMARA METALICO IPHONE 15/16 PRO', 5000, 15000, 25000, 40, 35, 100),
        ]
        acc_objs = []
        for sku, nom, cos, pmin, psug, st181, st2140, stbod in accesorios_demo:
            p = Product.query.filter_by(sku=sku).first()
            if not p:
                p = Product(
                    sku=sku, nombre=nom, tipo_inventario='tienda',
                    precio_costo=Decimal(str(cos)),
                    precio_minimo=Decimal(str(pmin)),
                    precio_sugerido=Decimal(str(psug)),
                    cantidad_stock=st181 + st2140 + stbod
                )
                db.session.add(p)
                db.session.flush()
            for br, cant in [(loc181, st181), (loc2140, st2140), (bodega, stbod)]:
                bs = get_or_create_branch_stock(br.id, p.id, None)
                if (bs.cantidad or 0) < 5:
                    bs.cantidad = cant
            db.session.flush()
            sync_global_product_stock(p.id, None)
            acc_objs.append(p)

        # Accesorio con Variantes (Subcategorías)
        funda_padre = Product.query.filter_by(sku='ACC-SIL-15PM-VAR').first()
        if not funda_padre:
            funda_padre = Product(
                sku='ACC-SIL-15PM-VAR',
                nombre='SILICONE CASE MAGSAFE IPHONE 15 PRO MAX',
                tipo_inventario='tienda',
                precio_costo=Decimal('14000'),
                precio_minimo=Decimal('30000'),
                precio_sugerido=Decimal('45000'),
                cantidad_stock=0
            )
            db.session.add(funda_padre)
            db.session.flush()
            for col_var, c181, c2140 in [('Negro Mate', 12, 10), ('Azul Tormenta', 8, 9), ('Rosa Pastel', 10, 7)]:
                pv = ProductVariant(
                    product_id=funda_padre.id,
                    nombre_variante=col_var,
                    precio_costo=Decimal('14000'),
                    precio_minimo=Decimal('30000'),
                    precio_sugerido=Decimal('45000'),
                    cantidad_stock=c181 + c2140
                )
                db.session.add(pv)
                db.session.flush()
                bs1 = get_or_create_branch_stock(loc181.id, funda_padre.id, pv.id)
                bs1.cantidad = c181
                bs2 = get_or_create_branch_stock(loc2140.id, funda_padre.id, pv.id)
                bs2.cantidad = c2140
                db.session.flush()
                sync_global_product_stock(funda_padre.id, pv.id)

        # Combo de Obsequios para el POS
        if GiftCombo.query.count() == 0:
            combo1 = GiftCombo(
                nombre='Combo Full Protección (Vidrio 9D + Cable + Protector Cámara)',
                descripcion='Combo de obsequio por compra de celular en tienda',
                activo=True
            )
            db.session.add(combo1)
            db.session.flush()
            db.session.add(GiftComboItem(combo_id=combo1.id, product_id=acc_objs[0].id, cantidad=1))
            db.session.add(GiftComboItem(combo_id=combo1.id, product_id=acc_objs[3].id, cantidad=1))
            db.session.add(GiftComboItem(combo_id=combo1.id, product_id=acc_objs[7].id, cantidad=1))

        # ------------------------------------------------------------------
        # 6. CELULARES Y ACCESORIOS EXTERNOS
        # ------------------------------------------------------------------
        ext_cel = Product.query.filter_by(sku='EXT-WATCH-U2').first()
        if not ext_cel:
            ext_cel = Product(
                sku='EXT-WATCH-U2',
                nombre='Apple ULTRA 2 49MM Negro (Black)',
                marca='Apple',
                modelo_celular='Apple Watch Ultra 2 49mm',
                memoria='64GB',
                color='Negro (Black)',
                imei='GFH4928173645-EXT',
                tipo_inventario='externos',
                proveedor='GIOTECH',
                precio_costo=Decimal('2650000'),
                precio_minimo=Decimal('2900000'),
                precio_sugerido=Decimal('3150000'),
                cantidad_stock=1
            )
            db.session.add(ext_cel)
            db.session.flush()
            bs_ext = get_or_create_branch_stock(loc2140.id, ext_cel.id, None)
            bs_ext.cantidad = 1

        # ------------------------------------------------------------------
        # 7. COMPRAS (ÓRDENES DE COMPRA) Y FACTURAS DE PROVEEDORES + ABONOS
        # ------------------------------------------------------------------
        if PurchaseOrder.query.count() == 0:
            po1 = PurchaseOrder(
                tipo_inventario='celulares',
                provider_id=prov_gio.id,
                usuario_id=admin.id,
                numero_factura='FAC-GIO-2026-089',
                observaciones='Compra de lote iPhone 16 Pro y 16 Pro Max nuevos para vitrina',
                total_costo=Decimal('11450000'),
                fecha_compra=ayer
            )
            db.session.add(po1)
            db.session.flush()
            for cel_item in cel_objs[:3]:
                db.session.add(PurchaseOrderItem(
                    purchase_order_id=po1.id,
                    product_id=cel_item.id,
                    cantidad=1,
                    costo_unitario=cel_item.precio_costo,
                    subtotal=cel_item.precio_costo,
                    imei=cel_item.imei
                ))

            po2 = PurchaseOrder(
                tipo_inventario='accesorios',
                provider_id=prov_car.id,
                usuario_id=admin.id,
                numero_factura='FAC-CAR-2026-412',
                observaciones='Surtido mensual de cargadores 20W, cables certificados y vidrios 9D',
                total_costo=Decimal('1480000'),
                fecha_compra=hoy
            )
            db.session.add(po2)
            db.session.flush()
            db.session.add(PurchaseOrderItem(
                purchase_order_id=po2.id,
                product_id=acc_objs[2].id,
                cantidad=30,
                costo_unitario=Decimal('32000'),
                subtotal=Decimal('960000')
            ))
            db.session.add(PurchaseOrderItem(
                purchase_order_id=po2.id,
                product_id=acc_objs[3].id,
                cantidad=40,
                costo_unitario=Decimal('13000'),
                subtotal=Decimal('520000')
            ))

        if ProviderInvoice.query.count() == 0:
            db.session.add(ProviderInvoice(
                provider_id=prov_gio.id,
                monto_total=Decimal('4850000'),
                numero_factura='GIO-9941',
                descripcion='iPhone 15 Pro Max 256GB + Apple Watch Ultra 2',
                fecha_factura=ayer
            ))
            db.session.add(ProviderInvoice(
                provider_id=prov_car.id,
                monto_total=Decimal('1480000'),
                numero_factura='FAC-CAR-2026-412',
                descripcion='Lote accesorios originales y cables USB-C',
                fecha_factura=hoy
            ))
            db.session.flush()

        # ------------------------------------------------------------------
        # 8. TURNOS DE CAJA, VENTAS DEL DÍA (LOCAL 181 Y LOCAL 2140), ARQUEOS Y SOBRANTES
        # ------------------------------------------------------------------
        turno_181 = CashShift.query.filter_by(branch_id=loc181.id, estado='ABIERTA').first()
        if not turno_181:
            turno_181 = CashShift(
                branch_id=loc181.id,
                opened_by_id=cajero181.id,
                base_inicial_efectivo=Decimal('200000'),
                asesores_ids=json.dumps([ase1.id, ase2.id]),
                estado='ABIERTA',
                fecha_apertura=datetime.combine(hoy.date(), time(9, 15, 0)),
                notas_apertura='Apertura puntual turno mañana Local 181',
                apertura_tardia=False,
                minutos_retraso_apertura=0
            )
            db.session.add(turno_181)
            db.session.flush()

        turno_2140 = CashShift.query.filter_by(branch_id=loc2140.id, estado='ABIERTA').first()
        if not turno_2140:
            turno_2140 = CashShift(
                branch_id=loc2140.id,
                opened_by_id=cajero2140.id,
                base_inicial_efectivo=Decimal('250000'),
                asesores_ids=json.dumps([ase3.id, ase4.id]),
                estado='ABIERTA',
                fecha_apertura=datetime.combine(hoy.date(), time(9, 48, 0)),
                notas_apertura='Apertura con tráfico en centro comercial Local 2140',
                apertura_tardia=True,
                minutos_retraso_apertura=18
            )
            db.session.add(turno_2140)
            db.session.flush()

        # Venta reciente en Local 2140 (con Efectivo + Bancolombia para que Local 2140 tenga saldo a favor para abonos)
        vta_2140 = Sale.query.filter_by(numero_factura='FAC2140-35').first()
        if not vta_2140:
            vta_2140 = Sale(
                vendedor_id=cajero2140.id,
                asesor_id=ase3.id,
                branch_id=loc2140.id,
                sucursal=loc2140.nombre,
                shift_id=turno_2140.id,
                numero_factura='FAC2140-35',
                monto_total=Decimal('4290000'),
                metodo_pago='mixto',
                tipo_venta='celulares',
                canal_venta='Punto físico',
                tiene_obsequio=True,
                costo_total_obsequios=Decimal('16500'),
                ingreso_neto_real=Decimal('4273500'),
                fecha_venta=hoy - timedelta(hours=1)
            )
            db.session.add(vta_2140)
            db.session.flush()
            db.session.add(SaleClient(
                sale_id=vta_2140.id,
                nombre='ANDRES FELIPE MONTOYA',
                documento='1032489512',
                telefono='3147896541',
                email='andres.montoya@empresa.co',
                direccion='Cra 15 # 88-64 Bogotá'
            ))
            db.session.add(SaleDetail(
                sale_id=vta_2140.id,
                product_id=cel_objs[2].id,
                cantidad_vendida=1,
                precio_venta_final=Decimal('4290000'),
                costo_unitario=cel_objs[2].precio_costo
            ))
            db.session.add(SaleDetail(
                sale_id=vta_2140.id,
                product_id=acc_objs[0].id,
                cantidad_vendida=1,
                precio_venta_final=Decimal('0'),
                costo_unitario=acc_objs[0].precio_costo,
                es_obsequio=True
            ))
            db.session.add(SalePayment(sale_id=vta_2140.id, metodo_pago='efectivo', monto=Decimal('2290000')))
            db.session.add(SalePayment(sale_id=vta_2140.id, metodo_pago='bancolombia', monto=Decimal('2000000')))
            db.session.flush()

        # Abono a proveedor GIOTECH pagado desde Local 2140 (con gasto reflejado en el cierre del local)
        if ProviderPayment.query.filter_by(provider_id=prov_gio.id).count() == 0:
            gasto_abono = Expense(
                usuario_id=admin.id,
                tipo_gasto='Gasto Diario',
                categoria='Abono a Proveedor',
                descripcion='[ABONO PROVEEDOR] GIOTECH (Efectivo) — Abono inicial lote iPhone',
                monto=Decimal('850000'),
                metodo_pago='efectivo',
                sucursal=loc2140.nombre,
                branch_id=loc2140.id,
                fecha_gasto=hoy
            )
            db.session.add(gasto_abono)
            db.session.flush()
            db.session.add(ProviderPayment(
                provider_id=prov_gio.id,
                branch_id=loc2140.id,
                expense_id=gasto_abono.id,
                monto_abonado=Decimal('850000'),
                metodo_pago='efectivo',
                observacion='Abono en efectivo desde caja Local 2140',
                fecha_pago=hoy
            ))

        # Gasto operativo adicional en Local 181
        if Expense.query.filter_by(branch_id=loc181.id).count() == 0:
            db.session.add(Expense(
                usuario_id=cajero181.id,
                tipo_gasto='Gasto Diario',
                categoria='Insumos y Papelería',
                descripcion='Compra de bolsas contramarcadas, alcohol isopropílico y paños de limpieza',
                monto=Decimal('35000'),
                metodo_pago='efectivo',
                sucursal=loc181.nombre,
                branch_id=loc181.id,
                fecha_gasto=hoy
            ))

        # Arqueo histórico cerrado del día anterior + Log de Sobrantes
        if ArqueoCaja.query.count() == 0:
            arq = ArqueoCaja(
                vendedor_id=cajero181.id,
                closed_by_id=cajero181.id,
                fecha_arqueo=ayer.date(),
                tipo_arqueo='general',
                sucursal=loc181.nombre,
                branch_id=loc181.id,
                base_inicial=Decimal('200000'),
                gastos_del_dia=Decimal('25000'),
                observaciones_gastos='Domicilio mensajería motorizado',
                total_efectivo_sistema=Decimal('950000'),
                total_transferencia_sistema=Decimal('1850000'),
                efectivo_fisico=Decimal('1145000'),
                diferencia=Decimal('20000'),
                observacion_diferencia='Sobrante de $20.000 por cambio no reclamado de instalación de vidrio',
                tiene_obsequio=True,
                costo_total_obsequios=Decimal('12000'),
                ingreso_neto_real=Decimal('2763000'),
                fecha_creacion=ayer
            )
            db.session.add(arq)
            db.session.flush()
            db.session.add(SobranteLog(
                arqueo_id=arq.id,
                vendedor_id=cajero181.id,
                sucursal=loc181.nombre,
                fecha_arqueo=ayer.date(),
                monto_esperado=Decimal('1125000'),
                efectivo_fisico=Decimal('1145000'),
                monto_sobrante=Decimal('20000'),
                justificacion='Sobrante verificado en conteo físico de billetes al cierre del turno'
            ))

        # ------------------------------------------------------------------
        # 9. RETOMAS (EN CUARENTENA / EVALUACIÓN Y APROBADAS) + LOTE DE IMPORTACIÓN
        # ------------------------------------------------------------------
        if Retoma.query.count() == 0:
            r1 = Retoma(
                sale_id=vta_2140.id,
                modelo='iPhone 13 Pro 128GB',
                marca='Apple',
                proveedor='Cliente Mostrador',
                valor_retoma=Decimal('1550000'),
                arreglos=Decimal('80000'),
                imei1='357894120984512',
                color='AZUL SIERRA',
                bateria='86%',
                memoria='128GB',
                observaciones='Recibido en parte de pago por iPhone 16 Pro. Requiere mantenimiento preventivo de auricular.',
                estado='en_evaluacion',
                vendedor_id=cajero2140.id,
                asesor_retoma_id=ase3.id,
                asesores_recepcion_ids=json.dumps([ase3.id, ase4.id]),
                branch_id=loc2140.id
            )
            r2 = Retoma(
                sale_id=None,
                modelo='iPhone 14 128GB',
                marca='Apple',
                proveedor='Cliente Retoma Directa',
                valor_retoma=Decimal('1700000'),
                arreglos=Decimal('0'),
                imei1='357894120984599',
                color='MEDIANOCHE',
                bateria='92%',
                memoria='128GB',
                observaciones='Impecable, listo y aprobado para pasar a vitrina.',
                estado='aprobado',
                ok_contabilidad=True,
                ok_venta=True,
                producto_generado_id=cel_objs[6].id,
                vendedor_id=cajero181.id,
                asesor_retoma_id=ase1.id,
                asesores_recepcion_ids=json.dumps([ase1.id]),
                branch_id=loc181.id
            )
            db.session.add_all([r1, r2])
            db.session.flush()

        if SobranteLog.query.count() == 0:
            arq_first = ArqueoCaja.query.order_by(ArqueoCaja.id.desc()).first()
            db.session.add(SobranteLog(
                arqueo_id=arq_first.id if arq_first else None,
                vendedor_id=cajero181.id,
                sucursal=loc181.nombre,
                fecha_arqueo=ayer.date(),
                monto_esperado=Decimal('1125000'),
                efectivo_fisico=Decimal('1145000'),
                monto_sobrante=Decimal('20000'),
                justificacion='Sobrante verificado en conteo físico de billetes al cierre del turno'
            ))

        if RetomaImportBatch.query.count() == 0:
            ret_list = Retoma.query.limit(2).all()
            db.session.add(RetomaImportBatch(
                batch_code='BATCH-RET-20261125-DEMO',
                user_id=admin.id,
                branch_id=loc181.id,
                total_equipos=len(ret_list) or 2,
                total_costo=Decimal('3250000'),
                estado='COMPLETADO',
                archivo_nombre='retomas_noviembre_demo.xlsx',
                detalles_json=json.dumps({
                    'retoma_ids': [r.id for r in ret_list],
                    'product_ids': [cel_objs[6].id],
                    'resumen_asesores': {'Sebastian Prieto': 1, 'Javier Rodriguez': 1}
                })
            ))

        if Vale.query.count() < 2:
            db.session.add(Vale(
                asesor_id=ase2.id,
                solicitado_por_id=cajero181.id,
                resuelto_por_id=admin.id,
                branch_id=loc181.id,
                monto=Decimal('120000'),
                concepto='Vale autorizado descontable de nómina/comisiones del mes',
                estado='APROBADO',
                observacion_resolucion='Aprobado por gerencia y entregado en efectivo',
                fecha_solicitud=ayer,
                fecha_resolucion=ayer
            ))

        # ------------------------------------------------------------------
        # 10. SOPORTE TÉCNICO / TALLER
        # ------------------------------------------------------------------
        tec1 = Technician.query.filter_by(nombre='Ing. Andrés Bermúdez (Microelectrónica Apple)').first()
        if not tec1:
            tec1 = Technician(
                nombre='Ing. Andrés Bermúdez (Microelectrónica Apple)',
                telefono='3104567890',
                especialidad='Face ID, Pantallas OLED y Placas iPhone',
                direccion_taller='Laboratorio Central Local 205',
                activo=True
            )
            db.session.add(tec1)
            db.session.flush()

        tec2 = Technician.query.filter_by(nombre='Taller Certificado AppleCare Express').first()
        if not tec2:
            tec2 = Technician(
                nombre='Taller Certificado AppleCare Express',
                telefono='3189876543',
                especialidad='Baterías Originales, Flex y Cámaras',
                direccion_taller='Centro Comercial Caribe Piso 3 Of. 312',
                activo=True
            )
            db.session.add(tec2)
            db.session.flush()

        if TechnicalService.query.count() == 0:
            db.session.add(TechnicalService(
                origen='INVENTARIO',
                product_id=cel_objs[5].id,
                branch_id=loc181.id,
                technician_id=tec1.id,
                asesor_id=ase1.id,
                created_by_id=admin.id,
                marca='Apple',
                modelo='iPhone 14 Pro Max 256GB',
                imei=cel_objs[5].imei,
                color='MORADO OSCURO',
                motivo_falla='Limpieza profunda de malla de altavoz y calibración de True Tone antes de exhibición.',
                tipo_arreglo='Micrófono / Altavoz / Auricular',
                estado='EN_REPARACION',
                costo_reparacion=Decimal('45000'),
                diagnostico_tecnico='Malla obstruida; se realiza ultrasonido y cambio de sello impermeable.',
                fecha_estimada=(hoy + timedelta(days=1)).date()
            ))
            w_cel = Warranty.query.join(Product).filter(Product.tipo_inventario == 'celulares').first()
            db.session.add(TechnicalService(
                origen='GARANTIA',
                product_id=w_cel.product_id if w_cel else cel_objs[6].id,
                warranty_id=w_cel.id if w_cel else None,
                branch_id=loc181.id,
                technician_id=tec2.id,
                asesor_id=ase2.id,
                created_by_id=admin.id,
                resolved_by_id=admin.id,
                marca='Apple',
                modelo='iPhone 13 128GB',
                imei=cel_objs[6].imei,
                color='BLANCO ESTELAR',
                motivo_falla='Revisión de puerto de carga Lightning por falso contacto.',
                tipo_arreglo='Pin de Carga / Puerto USB',
                estado='REPARADO',
                costo_reparacion=Decimal('60000'),
                diagnostico_tecnico='Pin de carga desgastado.',
                solucion_aplicada='Se instaló flex de carga original nuevo y se probó carga rápida 20W al 100%.',
                fecha_salida=hoy
            ))

        # ------------------------------------------------------------------
        # 11. TRASLADOS ENTRE SUCURSALES (ACEPTADOS CON OJITO + PENDIENTES)
        # ------------------------------------------------------------------
        if StockTransfer.query.count() == 0:
            tr1 = StockTransfer(
                origin_branch_id=bodega.id,
                destination_branch_id=loc181.id,
                created_by_id=bodeguero.id,
                received_by_id=cajero181.id,
                enviado_por_id=bodeguero.id,
                recibido_por_id=cajero181.id,
                observaciones_entrega='Despacho urgente de accesorios sellados para vitrina Local 181',
                observaciones_recepcion='Recibido completo y verificado por SKU en mostrador',
                status='ACEPTADO',
                notas='Surtido de cargadores 20W y vidrios templados 15/16 Pro Max',
                created_at=ayer,
                resolved_at=ayer + timedelta(minutes=25)
            )
            db.session.add(tr1)
            db.session.flush()
            db.session.add(StockTransferItem(transfer_id=tr1.id, product_id=acc_objs[0].id, cantidad=10))
            db.session.add(StockTransferItem(transfer_id=tr1.id, product_id=acc_objs[2].id, cantidad=6))
            db.session.add(StockTransferItem(transfer_id=tr1.id, product_id=acc_objs[3].id, cantidad=8))

            tr2 = StockTransfer(
                origin_branch_id=bodega.id,
                destination_branch_id=loc2140.id,
                created_by_id=bodeguero.id,
                enviado_por_id=bodeguero.id,
                observaciones_entrega='Envío de AirPods Pro 2 y Baterías MagSafe para fin de semana',
                status='PENDIENTE',
                notas='Pendiente de recepción en Local 2140',
                created_at=hoy
            )
            db.session.add(tr2)
            db.session.flush()
            db.session.add(StockTransferItem(transfer_id=tr2.id, product_id=acc_objs[5].id, cantidad=4))
            db.session.add(StockTransferItem(transfer_id=tr2.id, product_id=acc_objs[6].id, cantidad=5))

        # ------------------------------------------------------------------
        # 12. CAMBIOS DE CELULARES CON TERCEROS Y MANEOS
        # ------------------------------------------------------------------
        partner1 = ExchangePartner.query.filter_by(nombre='Celulares Express Monterrey (Aliado)').first()
        if not partner1:
            partner1 = ExchangePartner(
                nombre='Celulares Express Monterrey (Aliado)',
                contacto='3118765432',
                documento_o_nit='901223344-1',
                direccion='C.C. Caribe Local 145',
                activo=True
            )
            db.session.add(partner1)
            db.session.flush()

        if DeviceExchange.query.count() == 0:
            db.session.add(DeviceExchange(
                partner_id=partner1.id,
                user_id=admin.id,
                asesor_id=ase1.id,
                branch_id=loc181.id,
                product_salida_id=cel_objs[4].id,
                imei_salida=cel_objs[4].imei,
                modelo_salida='iPhone 15 Pro Max 512GB Blanco',
                costo_salida=cel_objs[4].precio_costo,
                tipo_flujo='SALIDA_PRIMERO',
                estado='PENDIENTE',
                motivo_salida='Se entregó 512GB Blanco a cambio de un 512GB Titanio Natural para cliente en espera.'
            ))
            db.session.add(DeviceExchange(
                partner_id=partner1.id,
                user_id=admin.id,
                asesor_id=ase3.id,
                resolved_by_id=admin.id,
                branch_id=loc2140.id,
                product_salida_id=cel_objs[1].id,
                imei_salida=cel_objs[1].imei,
                modelo_salida='iPhone 16 Pro 128GB Azul',
                costo_salida=Decimal('3500000'),
                product_entrada_id=cel_objs[1].id,
                marca_entrada='Apple',
                modelo_entrada='iPhone 16 Pro',
                color_entrada='TITANIO NEGRO',
                memoria_entrada='128GB',
                imei1_entrada=cel_objs[1].imei,
                costo_entrada=Decimal('3500000'),
                precio_minimo_entrada=Decimal('3850000'),
                precio_sugerido_entrada=Decimal('3990000'),
                tipo_flujo='SALIDA_PRIMERO',
                estado='COMPLETADO',
                motivo_salida='Cambio de color Azul por Negro solicitado por cliente.',
                observacion_resolucion='Recibido equipo Titanio Negro 100% batería y sellos verificados.',
                fecha_resolucion=hoy
            ))

        if Maneo.query.count() == 0:
            db.session.add(Maneo(
                product_id=acc_objs[6].id,
                local_vecino='Tecnología & Fundas Caribe Local 190',
                branch_id=loc181.id,
                cantidad=2,
                estado='PENDIENTE',
                fecha_prestamo=hoy
            ))
            db.session.add(Maneo(
                product_id=acc_objs[5].id,
                local_vecino='iShop Mayorista Local 2110',
                branch_id=loc2140.id,
                cantidad=1,
                estado='FACTURADO',
                fecha_prestamo=ayer,
                fecha_resolucion=hoy
            ))

        # ------------------------------------------------------------------
        # 13. VALES DE ASESORES, COMISIONES, APROBACIONES DE PRECIO Y BANCOS
        # ------------------------------------------------------------------
        if Vale.query.count() == 0:
            db.session.add(Vale(
                asesor_id=ase1.id,
                solicitado_por_id=cajero181.id,
                branch_id=loc181.id,
                monto=Decimal('80000'),
                concepto='Adelanto de quincena para transporte y almuerzo',
                estado='PENDIENTE',
                fecha_solicitud=hoy
            ))
            db.session.add(Vale(
                asesor_id=ase2.id,
                solicitado_por_id=cajero181.id,
                resuelto_por_id=admin.id,
                branch_id=loc181.id,
                monto=Decimal('120000'),
                concepto='Vale autorizado descontable de nómina/comisiones del mes',
                estado='APROBADO',
                observacion_resolucion='Aprobado por gerencia y entregado en efectivo',
                fecha_solicitud=ayer,
                fecha_resolucion=ayer
            ))

        if CommissionPayment.query.count() == 0:
            db.session.add(CommissionPayment(
                asesor_id=ase1.id,
                monto=Decimal('90000'),
                tipo_pago='ANTICIPO',
                metodo_pago='nequi',
                registrado_por_id=admin.id,
                notas='Anticipo de comisiones por cumplimiento de meta semanal'
            ))

        if PriceApproval.query.count() == 0:
            db.session.add(PriceApproval(
                vendedor_id=cajero181.id,
                product_id=cel_objs[0].id,
                precio_original=Decimal('4550000'),
                precio_solicitado=Decimal('4480000'),
                estado='pendiente'
            ))
            db.session.add(PriceApproval(
                vendedor_id=cajero2140.id,
                product_id=cel_objs[3].id,
                precio_original=Decimal('3590000'),
                precio_solicitado=Decimal('3520000'),
                precio_aprobado=Decimal('3520000'),
                estado='aprobado',
                admin_id=admin.id,
                fecha_resolucion=hoy
            ))

        # Cuentas Bancarias / Métodos de Pago con Saldos y Movimientos
        cuentas_spec = [
            ('efectivo', 'Efectivo Caja Mayor', 'efectivo', 'fa-money-bill-wave', 6850000),
            ('bancolombia', 'Bancolombia Empresarial', 'banco', 'fa-building-columns', 14200000),
            ('nequi', 'Nequi Corporativo', 'banco', 'fa-mobile-screen-button', 5430000),
            ('daviplata', 'Daviplata Negocios', 'banco', 'fa-mobile-retro', 2150000),
            ('bold', 'Bold (Datáfono)', 'tarjeta', 'fa-bolt', 3890000),
            ('addi', 'Addi Cupo Aliado', 'credito_digital', 'fa-bag-shopping', 4600000),
            ('sitecredito', 'Sistecrédito', 'credito_digital', 'fa-id-card', 3100000),
        ]
        for cod, nom, tipo, ico, saldo in cuentas_spec:
            cta = BankAccount.query.filter_by(codigo=cod).first()
            if not cta:
                cta = BankAccount(codigo=cod, nombre=nom, tipo=tipo, icono=ico, saldo_actual=Decimal(str(saldo)), activo=True)
                db.session.add(cta)
                db.session.flush()
                db.session.add(BankTransaction(
                    account_id=cta.id,
                    tipo_movimiento='INGRESO',
                    origen='ARQUEO_CIERRE',
                    monto=Decimal(str(saldo)),
                    saldo_anterior=Decimal('0'),
                    saldo_nuevo=Decimal(str(saldo)),
                    descripcion=f'Recaudo acumulado de ventas y cierres de turno ({nom})',
                    usuario_id=admin.id
                ))
            elif float(cta.saldo_actual or 0) == 0:
                cta.saldo_actual = Decimal(str(saldo))

        # ------------------------------------------------------------------
        # 14. CLIENTES MAYORISTAS / CRÉDITO BODEGA Y BITÁCORA DE AUDITORÍA
        # ------------------------------------------------------------------
        if Cliente.query.count() == 0:
            cli1 = Cliente(
                nombre_o_razon_social='DISTRIBUIDORA MOVIL DEL VALLE S.A.S.',
                documento_o_nit='901345678-9',
                telefono='3176543210',
                email='compras@movildelvalle.com',
                direccion='Calle 13 # 18-45 Cali',
                creado_por_id=admin.id
            )
            db.session.add(cli1)
            db.session.flush()
            fb = FacturaBodega(
                cliente_id=cli1.id,
                usuario_id=admin.id,
                numero_factura='BOD-CR-001',
                monto_total=Decimal('2400000'),
                modalidad='credito',
                estado='Parcial'
            )
            db.session.add(fb)
            db.session.flush()
            db.session.add(FacturaBodegaDetalle(
                factura_id=fb.id,
                producto_id=acc_objs[2].id,
                cantidad=30,
                precio_venta=Decimal('80000')
            ))
            db.session.add(AbonoBodega(
                cliente_id=cli1.id,
                factura_id=fb.id,
                usuario_id=admin.id,
                monto=Decimal('1000000'),
                metodo_pago='bancolombia',
                observacion='Primer abono por transferencia Bancolombia'
            ))

        if AuditLog.query.count() < 3:
            AuditLog.registrar(
                action='APROBACION_PRECIO_MINIMO',
                user_id=admin.id,
                target_id=cel_objs[3].id,
                target_type='DISCOUNT_APPROVAL',
                motivo='Se autorizó descuento especial de $70.000 por pago de contado en Local 2140.'
            )
            AuditLog.registrar(
                action='REGISTRO_PERDIDA_ACCESORIO',
                user_id=admin.id,
                target_id=1,
                target_type='ACCESSORY_LOSS',
                motivo='Baja de 1x Vidrio Templado 9D iPhone 15 Pro Max por rotura durante instalación en mostrador.'
            )
            AuditLog.registrar(
                action='ABONO_PROVEEDOR_DESDE_LOCAL',
                user_id=admin.id,
                target_id=prov_gio.id,
                target_type='PROVIDER_PAYMENT',
                motivo='Abono de $850.000 a proveedor GIOTECH pagado en efectivo desde caja de LOCAL 2140.'
            )

        db.session.commit()

        print("=== RESUMEN DE DATOS DEMO SEMBRADOS ===")
        print(f"Sucursales: {Branch.query.count()}")
        print(f"Usuarios: {User.query.count()} | Asesores: {Asesor.query.count()}")
        print(f"Celulares en Inventario: {Product.query.filter_by(tipo_inventario='celulares').count()}")
        print(f"Accesorios en Inventario: {Product.query.filter(Product.tipo_inventario != 'celulares').count()}")
        print(f"Ventas / Facturas: {Sale.query.count()}")
        print(f"Turnos de Caja: {CashShift.query.count()} | Arqueos: {ArqueoCaja.query.count()} | Sobrantes: {SobranteLog.query.count()}")
        print(f"Retomas: {Retoma.query.count()} | Lotes Retomas: {RetomaImportBatch.query.count()}")
        print(f"Proveedores: {Provider.query.count()} | Compras: {PurchaseOrder.query.count()} | Abonos Prov: {ProviderPayment.query.count()}")
        print(f"Garantias: {Warranty.query.count()} | Perdidas Accesorios: {AccessoryLoss.query.count()}")
        print(f"Soporte Tecnico: {TechnicalService.query.count()} | Tecnicos: {Technician.query.count()}")
        print(f"Traslados: {StockTransfer.query.count()} | Cambios Celulares: {DeviceExchange.query.count()} | Maneos: {Maneo.query.count()}")
        print(f"Vales: {Vale.query.count()} | Gastos: {Expense.query.count()} | Cuentas Bancos: {BankAccount.query.count()}")
        print(f"Combos Obsequios: {GiftCombo.query.count()} | Auditoria: {AuditLog.query.count()}")


if __name__ == '__main__':
    seed_all()
