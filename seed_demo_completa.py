"""Script de generación de datos de prueba para demostración integral (Fase Final LifeStore).
Ejecución: `python seed_demo_completa.py` o `python -m flask seed-demo-completa`

Cubre:
1. Turno de Caja con Alerta de Horario (Apertura 09:45 AM con 15 min de retraso).
2. Asesores Carlos Gómez y Laura Restrepo asignados al turno.
3. Venta con método 'abono_tercero' ($100.000) a proveedor "Carmacel" + $50.000 en Efectivo.
4. Venta con Retoma de celular ($700.000) y saldo en Nequi ($1.800.000).
5. Venta de equipo proveniente de retoma para disparar la Bolsa de Comisión 15% compartida.
6. Registro de Anticipo de Comisiones ($50.000) a Carlos Gómez con Comprobante REC-COM.
7. Cierre de Turno Tardío (08:15 PM / 20:15 con 45 min de retraso) y Arqueo Cuadrado en $200.000.
"""
import sys
if hasattr(sys.stdout, 'reconfigure'):
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass

import os
import json
import random
from decimal import Decimal
from datetime import datetime, date, time

from wsgi import app
from models import (
    db, Branch, User, Asesor, Product, ProductVariant, BranchStock,
    CashShift, ArqueoCaja, Sale, SaleDetail, SalePayment, SaleClient,
    Retoma, Provider, ProviderPayment, ProviderInvoice, CommissionPayment,
    obtener_hora_bogota
)
from services.stock_service import get_or_create_branch_stock, sync_global_product_stock
from werkzeug.security import generate_password_hash

def run_seed_demo_completa():
    print("\n" + "=" * 75)
    print(" [*] INICIANDO SEED DEMO COMPLETA - LIFESTORE (ENTREGA Y VALIDACIÓN)")
    print("=" * 75)

    with app.app_context():
        # -----------------------------------------------------------------
        # 1. Asegurar Sucursales, Proveedor, Asesores y Cajero
        # -----------------------------------------------------------------
        print("\n[1/6] Asegurando entidades base (Sucursal, Asesores, Proveedor)...")
        
        # Tienda Local 1
        tienda1 = Branch.query.filter((Branch.codigo == 'LOC1') | (Branch.nombre == 'Local 1')).first()
        if not tienda1:
            tienda1 = Branch(
                nombre="Local 1",
                codigo="LOC1",
                tipo="tienda",
                direccion="Centro Comercial Monterrey, Local 102",
                telefono="3009998877",
                nombre_comercial="Life Store - Monterrey",
                nit="901.458.789-2",
                prefijo_factura="LOC1",
                ultimo_consecutivo=0,
                activa=True
            )
            db.session.add(tienda1)
            db.session.flush()
        else:
            tienda1.activa = True
            tienda1.tipo = 'tienda'

        # Usuario Cajero / Vendedor para Local 1
        vendedor1 = User.query.filter_by(email="vendedor1@test.com").first()
        if not vendedor1:
            vendedor1 = User(
                nombre="Vendedor Local 1",
                email="vendedor1@test.com",
                password_hash=generate_password_hash("Test1234"),
                rol="vendedor",
                sucursal=tienda1.nombre,
                branch_id=tienda1.id
            )
            db.session.add(vendedor1)
            db.session.flush()
        else:
            vendedor1.branch_id = tienda1.id

        # Usuario Administrador
        admin_user = User.query.filter(User.rol == 'admin').first()
        if not admin_user:
            admin_user = User(
                nombre="Admin General",
                email="admin@lifestore.com",
                password_hash=generate_password_hash("Admin1234*"),
                rol="admin",
                sucursal="Todas"
            )
            db.session.add(admin_user)
            db.session.flush()

        # Asesores Carlos Gómez y Laura Restrepo
        carlos = Asesor.query.filter_by(nombre="Carlos Gómez").first()
        if not carlos:
            carlos = Asesor(nombre="Carlos Gómez", activo=True)
            db.session.add(carlos)
            db.session.flush()

        laura = Asesor.query.filter_by(nombre="Laura Restrepo").first()
        if not laura:
            laura = Asesor(nombre="Laura Restrepo", activo=True)
            db.session.add(laura)
            db.session.flush()

        # Proveedor "Carmacel"
        proveedor = Provider.query.filter_by(nombre="Carmacel").first()
        if not proveedor:
            proveedor = Provider(
                nombre="Carmacel",
                empresa="Carmacel Repuestos y Accesorios S.A.S.",
                telefono="3125556677"
            )
            db.session.add(proveedor)
            db.session.flush()
            # Factura inicial de deuda para tener saldo pendiente
            inv = ProviderInvoice(
                provider_id=proveedor.id,
                monto_total=Decimal('1500000.00'),
                numero_factura="FAC-CARM-001",
                descripcion="Inventario inicial repuestos y pantallas"
            )
            db.session.add(inv)

        print(f"      [OK] Tienda: {tienda1.nombre} (ID {tienda1.id}, Prefijo: {tienda1.prefijo_factura})")
        print(f"      [OK] Cajero: {vendedor1.nombre} ({vendedor1.email})")
        print(f"      [OK] Asesores: {carlos.nombre} (ID {carlos.id}) & {laura.nombre} (ID {laura.id})")
        print(f"      [OK] Proveedor: {proveedor.nombre} (Saldo: ${proveedor.saldo_pendiente:,.0f})")

        # -----------------------------------------------------------------
        # 2. Simular Turno de Caja con Alerta de Horario (Apertura 09:45 AM)
        # -----------------------------------------------------------------
        print("\n[2/6] Simulando Turno de Caja con Alerta de Apertura Tardía (09:45 AM)...")
        hoy = obtener_hora_bogota()
        fecha_apertura_sim = datetime.combine(hoy.date(), time(9, 45, 0))

        # Cerrar turnos previos abiertos en la sede si existen para evitar solapamiento
        turnos_previos = CashShift.query.filter_by(branch_id=tienda1.id, estado='ABIERTA').all()
        for tp in turnos_previos:
            tp.estado = 'CERRADA'
            tp.fecha_cierre = fecha_apertura_sim

        base_inicial_monto = Decimal('150000.00')
        minutos_retraso_ap = 15  # 9:45 AM vs 9:30 AM límite oficial

        shift_demo = CashShift(
            branch_id=tienda1.id,
            opened_by_id=vendedor1.id,
            fecha_apertura=fecha_apertura_sim,
            base_inicial_efectivo=base_inicial_monto,
            asesores_ids=json.dumps([carlos.id, laura.id]),
            notas_apertura="Apertura simulada para auditoría de horario demo",
            estado='ABIERTA',
            apertura_tardia=True,
            minutos_retraso_apertura=minutos_retraso_ap
        )
        db.session.add(shift_demo)
        db.session.flush()

        print(f"      [OK] Turno #{shift_demo.id} abierto a las {shift_demo.fecha_apertura.strftime('%I:%M %p')}")
        print(f"      [ALERTA] apertura_tardia = True ({shift_demo.minutos_retraso_apertura} minutos de retraso sobre las 9:30 AM)")
        print(f"      [OK] Asesores asignados: Carlos Gómez y Laura Restrepo")
        print(f"      [OK] Base inicial en caja física: ${base_inicial_monto:,.0f}")

        # -----------------------------------------------------------------
        # 3. Simular Venta con Abono a Proveedor ($100.000 a Carmacel + $50.000 Efectivo)
        # -----------------------------------------------------------------
        print("\n[3/6] Simulando Venta con Método 'Abono a Terceros / Proveedor'...")
        
        # Producto para la venta
        prod_accesorio = Product.query.filter_by(nombre="Audífonos AirPods Pro OEM").first()
        if not prod_accesorio:
            prod_accesorio = Product(
                nombre="Audífonos AirPods Pro OEM",
                sku=f"ACC-AIRP-{random.randint(1000, 9999)}",
                tipo_inventario="tienda",
                precio_costo=Decimal('80000.00'),
                precio_sugerido=Decimal('150000.00'),
                precio_minimo=Decimal('120000.00'),
                cantidad_stock=20
            )
            db.session.add(prod_accesorio)
            db.session.flush()

        bs_acc = get_or_create_branch_stock(tienda1.id, prod_accesorio.id)
        if bs_acc.cantidad < 2:
            bs_acc.cantidad = 10
            sync_global_product_stock(prod_accesorio.id)

        tienda1.ultimo_consecutivo = (tienda1.ultimo_consecutivo or 0) + 1
        num_factura_abono = f"{tienda1.prefijo_factura}-{tienda1.ultimo_consecutivo}"
        hora_vta1 = datetime.combine(hoy.date(), time(11, 20, 0))

        venta_abono = Sale(
            vendedor_id=vendedor1.id,
            asesor_id=carlos.id,
            branch_id=tienda1.id,
            shift_id=shift_demo.id,
            numero_factura=num_factura_abono,
            monto_total=Decimal('150000.00'),
            metodo_pago='mixto',
            fecha_venta=hora_vta1
        )
        db.session.add(venta_abono)
        db.session.flush()

        # Detalle
        det_vta1 = SaleDetail(
            sale_id=venta_abono.id,
            product_id=prod_accesorio.id,
            cantidad_vendida=1,
            precio_venta_final=Decimal('150000.00')
        )
        db.session.add(det_vta1)
        bs_acc.cantidad -= 1
        sync_global_product_stock(prod_accesorio.id)

        # Pagos Mixtos: $100.000 Abono a Proveedor + $50.000 Efectivo
        comprobante_soporte = f"TR-NEQUI-{random.randint(100000, 999999)}"
        pago_abono = SalePayment(
            sale_id=venta_abono.id,
            metodo_pago='abono_tercero',
            monto=Decimal('100000.00'),
            provider_id=proveedor.id,
            comprobante=comprobante_soporte
        )
        pago_efectivo = SalePayment(
            sale_id=venta_abono.id,
            metodo_pago='efectivo',
            monto=Decimal('50000.00')
        )
        db.session.add(pago_abono)
        db.session.add(pago_efectivo)

        # Crear ProviderPayment asociado para rebajar la deuda del proveedor
        abono_prov_record = ProviderPayment(
            provider_id=proveedor.id,
            monto_abonado=Decimal('100000.00'),
            metodo_pago='abono_tercero',
            observacion=f"Abono por Factura #{venta_abono.id} ({num_factura_abono}) - Soporte: {comprobante_soporte}",
            fecha_pago=hora_vta1
        )
        db.session.add(abono_prov_record)

        print(f"      [OK] Factura #{venta_abono.id} ({num_factura_abono}) por $150.000")
        print(f"           - Abono a Proveedor '{proveedor.nombre}': $100.000 (Soporte: {comprobante_soporte})")
        print(f"           - Efectivo en caja: $50.000")
        print(f"           - Nuevo Saldo Proveedor '{proveedor.nombre}': ${proveedor.saldo_pendiente:,.0f}")

        # -----------------------------------------------------------------
        # 4. Simular Venta con Retoma y Venta de Retoma con Bolsa 15% Compartida
        # -----------------------------------------------------------------
        print("\n[4/6] Simulando Venta con Retoma y Venta de Retoma con Bolsa 15%...")
        
        # A. Celular de Vitrina para vender con retoma
        imei_nuevo = f"35{random.randint(1000000000000, 9999999999999)}"
        cel_vitrina = Product(
            nombre="iPhone 13 128GB Midnight (Vitrina)",
            sku=f"CEL-IP13-{random.randint(1000, 9999)}",
            modelo_celular="iPhone 13",
            imei=imei_nuevo,
            tipo_inventario="celulares",
            precio_costo=Decimal('1900000.00'),
            precio_sugerido=Decimal('2500000.00'),
            precio_minimo=Decimal('2300000.00'),
            cantidad_stock=1
        )
        db.session.add(cel_vitrina)
        db.session.flush()
        bs_cel = get_or_create_branch_stock(tienda1.id, cel_vitrina.id)
        bs_cel.cantidad = 1
        sync_global_product_stock(cel_vitrina.id)

        tienda1.ultimo_consecutivo += 1
        num_factura_cel = f"{tienda1.prefijo_factura}-{tienda1.ultimo_consecutivo}"
        hora_vta2 = datetime.combine(hoy.date(), time(14, 30, 0))

        # Cliente entrega retoma de $700.000 y paga saldo de $1.800.000 por Nequi
        valor_cel_vitrina = Decimal('2500000.00')
        valor_retoma_recibida = Decimal('700000.00')
        saldo_a_pagar_cel = valor_cel_vitrina - valor_retoma_recibida # $1.800.000

        venta_retoma = Sale(
            vendedor_id=vendedor1.id,
            asesor_id=carlos.id,
            branch_id=tienda1.id,
            shift_id=shift_demo.id,
            numero_factura=num_factura_cel,
            monto_total=saldo_a_pagar_cel,
            metodo_pago='nequi',
            fecha_venta=hora_vta2
        )
        db.session.add(venta_retoma)
        db.session.flush()

        det_vta2 = SaleDetail(
            sale_id=venta_retoma.id,
            product_id=cel_vitrina.id,
            cantidad_vendida=1,
            precio_venta_final=valor_cel_vitrina
        )
        db.session.add(det_vta2)
        bs_cel.cantidad = 0
        sync_global_product_stock(cel_vitrina.id)

        # Pago de la venta
        pago_nequi = SalePayment(
            sale_id=venta_retoma.id,
            metodo_pago='nequi',
            monto=saldo_a_pagar_cel
        )
        db.session.add(pago_nequi)

        # Registro de la Retoma recibida del cliente
        imei_usado = f"35{random.randint(1000000000000, 9999999999999)}"
        retoma_recibida = Retoma(
            sale_id=venta_retoma.id,
            branch_id=tienda1.id,
            modelo="iPhone 11 64GB Negro (Usado)",
            marca="Apple",
            valor_retoma=valor_retoma_recibida,
            arreglos=Decimal('0.00'),
            imei1=imei_usado,
            color="Negro",
            bateria="84%",
            memoria="64GB",
            estado='en_evaluacion',
            vendedor_id=vendedor1.id
        )
        db.session.add(retoma_recibida)

        # Datos del Cliente para la factura
        cliente_fac = SaleClient(
            sale_id=venta_retoma.id,
            nombre="Andrés Felipe Mendoza",
            documento="1020304050",
            telefono="3147890123",
            email="andres.mendoza@gmail.com",
            direccion="Calle 45 # 12-30 Apto 402"
        )
        db.session.add(cliente_fac)

        print(f"      [OK] Factura con Retoma #{venta_retoma.id} ({num_factura_cel})")
        print(f"           - Celular: {cel_vitrina.nombre} ($2.500.000)")
        print(f"           - Retoma Recibida: -${valor_retoma_recibida:,.0f} ({retoma_recibida.modelo})")
        print(f"           - Saldo Pagado en Nequi: ${saldo_a_pagar_cel:,.0f}")

        # B. Simular Venta de un Celular previamente reacondicionado de Retoma
        # para detonar la Bolsa de Comisión del 15% repartida entre Carlos y Laura
        imei_retoma_vendida = f"35{random.randint(1000000000000, 9999999999999)}"
        prod_retoma_vendido = Product(
            nombre="iPhone 12 128GB Azul (Reacondicionado Retoma)",
            sku=f"RET-IP12-{random.randint(1000, 9999)}",
            modelo_celular="iPhone 12",
            imei=imei_retoma_vendida,
            tipo_inventario="celulares",
            precio_costo=Decimal('1300000.00'),
            precio_sugerido=Decimal('1800000.00'),
            precio_minimo=Decimal('1600000.00'),
            cantidad_stock=1
        )
        db.session.add(prod_retoma_vendido)
        db.session.flush()

        retoma_historica = Retoma(
            sale_id=venta_retoma.id,
            branch_id=tienda1.id,
            modelo="iPhone 12 128GB Azul",
            marca="Apple",
            valor_retoma=Decimal('1200000.00'), # Costo base retoma
            arreglos=Decimal('100000.00'),     # Batería / Mantenimiento
            imei1=imei_retoma_vendida,
            estado='aprobado',
            producto_generado_id=prod_retoma_vendido.id,
            vendedor_id=vendedor1.id
        )
        db.session.add(retoma_historica)
        db.session.flush()

        # Venta de este equipo de retoma durante el turno
        tienda1.ultimo_consecutivo += 1
        num_factura_retoma_vta = f"{tienda1.prefijo_factura}-{tienda1.ultimo_consecutivo}"
        hora_vta3 = datetime.combine(hoy.date(), time(16, 45, 0))

        venta_retoma_operacion = Sale(
            vendedor_id=vendedor1.id,
            asesor_id=laura.id,
            branch_id=tienda1.id,
            shift_id=shift_demo.id,
            numero_factura=num_factura_retoma_vta,
            monto_total=Decimal('1800000.00'),
            metodo_pago='transferencia',
            fecha_venta=hora_vta3
        )
        db.session.add(venta_retoma_operacion)
        db.session.flush()

        det_vta3 = SaleDetail(
            sale_id=venta_retoma_operacion.id,
            product_id=prod_retoma_vendido.id,
            cantidad_vendida=1,
            precio_venta_final=Decimal('1800000.00')
        )
        db.session.add(det_vta3)
        pago_retoma_vta = SalePayment(
            sale_id=venta_retoma_operacion.id,
            metodo_pago='transferencia',
            monto=Decimal('1800000.00')
        )
        db.session.add(pago_retoma_vta)

        # Cálculo de la bolsa 15%:
        # Venta: $1.800.000 - Costo: $1.200.000 - Arreglos: $100.000 = Utilidad Neta $500.000
        # Bolsa 15% = $75.000 / 2 asesores = $37.500 para Carlos y $37.500 para Laura
        utilidad_retoma_calc = Decimal('1800000') - Decimal('1200000') - Decimal('100000')
        bolsa_total_calc = utilidad_retoma_calc * Decimal('0.15')
        cuota_asesor_calc = bolsa_total_calc / 2

        print(f"      [OK] Venta de Equipo de Retoma #{venta_retoma_operacion.id} ({num_factura_retoma_vta}):")
        print(f"           - Precio Venta: $1.800.000 | Costo: $1.200.000 | Arreglos: $100.000")
        print(f"           - Utilidad Neta: ${utilidad_retoma_calc:,.0f} -> Bolsa 15%: ${bolsa_total_calc:,.0f}")
        print(f"           - Reparto equitativo en turno: ${cuota_asesor_calc:,.0f} a Carlos Gómez y ${cuota_asesor_calc:,.0f} a Laura Restrepo")

        # -----------------------------------------------------------------
        # 5. Simular Anticipo de Comisiones a Carlos Gómez ($50.000)
        # -----------------------------------------------------------------
        print("\n[5/6] Simulando Anticipo de Comisiones a Carlos Gómez ($50.000)...")
        hora_anticipo = datetime.combine(hoy.date(), time(17, 30, 0))

        anticipo_carlos = CommissionPayment(
            asesor_id=carlos.id,
            monto=Decimal('50000.00'),
            tipo_pago='ANTICIPO',
            metodo_pago='efectivo',
            fecha_pago=hora_anticipo,
            registrado_por_id=admin_user.id,
            notas="Anticipo solicitado para transporte y refrigerio de jornada"
        )
        db.session.add(anticipo_carlos)
        db.session.flush()

        print(f"      [OK] Anticipo Folio: REC-COM-{anticipo_carlos.id:05d}")
        print(f"           - Beneficiario: {carlos.nombre}")
        print(f"           - Monto: $50.000 en Efectivo")
        print(f"           - Registrado por: {admin_user.nombre}")

        # -----------------------------------------------------------------
        # 6. Simular Cierre de Turno Tardío (08:15 PM / 20:15) y Arqueo Físico
        # -----------------------------------------------------------------
        print("\n[6/6] Simulando Cierre de Turno Tardío (08:15 PM) y Arqueo Cuadrado...")
        fecha_cierre_sim = datetime.combine(hoy.date(), time(20, 15, 0))
        minutos_retraso_ci = 45 # 20:15 vs 19:30 límite oficial

        shift_demo.estado = 'CERRADA'
        shift_demo.fecha_cierre = fecha_cierre_sim
        shift_demo.cierre_tardio = True
        shift_demo.minutos_retraso_cierre = minutos_retraso_ci
        shift_demo.notas_cierre = "Cierre realizado a las 20:15 tras atención del último cliente"

        # Arqueo de Caja:
        # Base inicial: $150.000
        # Efectivo ingresado por ventas: $50.000 (Venta 1). Nota: Los $100.000 fueron abono a proveedor y NO suman.
        # Efectivo Físico esperado en caja: $150.000 + $50.000 = $200.000
        total_efectivo_caja = Decimal('200000.00')

        arqueo_demo = ArqueoCaja(
            vendedor_id=vendedor1.id,
            fecha_arqueo=hoy.date(),
            tipo_arqueo='general',
            sucursal=tienda1.nombre,
            branch_id=tienda1.id,
            shift_id=shift_demo.id,
            base_inicial=base_inicial_monto,
            gastos_del_dia=Decimal('0.00'),
            total_efectivo_sistema=Decimal('50000.00'),
            total_transferencia_sistema=Decimal('3600000.00'), # $1.800.000 Nequi + $1.800.000 Transferencia
            total_retomas_sistema=Decimal('700000.00'),
            efectivo_fisico=total_efectivo_caja,
            diferencia=Decimal('0.00'),
            observacion_diferencia="Caja cuadrada al 100%. El abono a proveedor por $100.000 no alteró el efectivo físico.",
            fecha_creacion=fecha_cierre_sim
        )
        db.session.add(arqueo_demo)
        db.session.commit()

        print(f"      [OK] Turno #{shift_demo.id} cerrado exitosamente a las {shift_demo.fecha_cierre.strftime('%I:%M %p')}")
        print(f"      [ALERTA] cierre_tardio = True ({shift_demo.minutos_retraso_cierre} minutos de retraso sobre las 19:30)")
        print(f"      [CUADRE CONTABLE PERFECTO]:")
        print(f"           - Base Inicial:              ${base_inicial_monto:,.0f}")
        print(f"           - Efectivo Ventas:           +$50.000")
        print(f"           - Abono a Terceros Carmacel:  $100.000 (Excluido de caja física)")
        print(f"           --------------------------------------------------------")
        print(f"           - Efectivo Físico en Mano:    ${total_efectivo_caja:,.0f}")
        print(f"           - Diferencia Arqueo:          $0 (CUADRADA)")

        # -----------------------------------------------------------------
        # Resumen Final con Enlaces de Validación Visual Web
        # -----------------------------------------------------------------
        print("\n" + "=" * 75)
        print(" [OK] ¡DEMO GENERADA CON ÉXITO! RUTAS DE REVISIÓN VISUAL:")
        print("=" * 75)
        print(f" 1. Dashboard Admin (Banner Alertas Horario Apertura/Cierre):")
        print(f"    --> http://localhost:5001/admin/dashboard\n")
        print(f" 2. Auditoría Detallada de Turnos (Badges Retraso Apertura y Cierre):")
        print(f"    --> http://localhost:5001/turnos/auditoria\n")
        print(f" 3. Liquidación de Comisiones Carlos Gómez (Vitrina + Bolsa 15% + Anticipo):")
        print(f"    --> http://localhost:5001/admin/ventas-vendedores?asesor_id={carlos.id}\n")
        print(f" 4. Liquidación de Comisiones Laura Restrepo (Bolsa 15% Retomas):")
        print(f"    --> http://localhost:5001/admin/ventas-vendedores?asesor_id={laura.id}\n")
        print(f" 5. Comprobante Imprimible de Comisión (Folio REC-COM-{anticipo_carlos.id:05d}):")
        print(f"    --> http://localhost:5001/admin/comisiones/recibo/{anticipo_carlos.id}\n")
        print(f" 6. Factura con Retoma y Datos Comerciales de Sede (Media Carta / Ticket):")
        print(f"    --> http://localhost:5001/sales/ticket/{venta_retoma.id}")
        print(f"    --> http://localhost:5001/sales/factura_impresion/{venta_retoma.id}\n")
        print(f" 7. Venta con Abono a Proveedor (Ver pagos mixtos):")
        print(f"    --> http://localhost:5001/sales/ticket/{venta_abono.id}")
        print("=" * 75 + "\n")

if __name__ == '__main__':
    run_seed_demo_completa()
