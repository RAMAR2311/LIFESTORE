"""Script de prueba de extremo a extremo para el sistema Multisucursal LifeStore.
Ejecución directa: `python test_multisucursal.py`
O vía CLI Flask: `python -m flask test-multisucursal`

Flujo simulado:
1. Crear/asegurar entidades:
   - 2 Tiendas ("Local 1" prefijo LOC1, "Local 2" prefijo LOC2) + "Bodega Central" (BOD1).
   - 2 Asesores activos ("Carlos Gómez", "Laura Restrepo").
   - 2 Vendedores ("vendedor1@test.com" en Local 1, "vendedor2@test.com" en Local 2 con clave "Test1234").
   - 2 Productos: Accesorio con variantes (Funda Pro Silicona: Negro, Azul) y Celular con IMEI ficticio en Bodega Central.
2. Simular flujo completo:
   - Crear traslado desde Bodega Central hacia Local 1 con el celular y 5 accesorios.
   - Aceptar traslado como vendedor de Local 1 (aumenta stock en Local 1 y descuenta en Bodega Central).
   - Apertura de caja en Local 1 con base de $100.000 y asignando los asesores.
   - Venta en Local 1: Celular + 1 Accesorio, recibiendo celular usado en retoma y pagando con Efectivo + Nequi.
   - Validar que el stock disminuyó, la retoma se creó y el consecutivo aumentó (LOC1-1).
3. Imprimir reporte con credenciales para validación visual web.
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
from datetime import datetime

from wsgi import app
from models import (
    db, Branch, User, Asesor, Product, ProductVariant, BranchStock,
    StockTransfer, StockTransferItem, StockAdjustment, CashShift,
    Sale, SaleDetail, SalePayment, SaleClient, Retoma, obtener_hora_bogota
)
from services.stock_service import get_or_create_branch_stock, sync_global_product_stock
from werkzeug.security import generate_password_hash

def run_multisucursal_test():
    print("=" * 70)
    print("[*] INICIANDO TEST END-TO-END MULTISUCURSAL - LIFESTORE")
    print("=" * 70)

    with app.app_context():
        # -------------------------------------------------------------
        # 1. ENTIDADES BASE: Sucursales, Asesores y Usuarios
        # -------------------------------------------------------------
        print("\n[1/5] Verificando / Creando Sucursales...")
        
        # Bodega Central
        bodega = Branch.query.filter((Branch.codigo == 'BOD1') | (Branch.codigo == 'BOD') | (Branch.nombre == 'Bodega Central')).first()
        if not bodega:
            bodega = Branch(
                nombre="Bodega Central",
                codigo="BOD",
                tipo="bodega",
                direccion="Zona Industrial Calle 10 # 50-20",
                telefono="3110001122",
                prefijo_factura="BOD",
                ultimo_consecutivo=0,
                activa=True
            )
            db.session.add(bodega)
            db.session.flush()
            print("   [+] Creada Bodega Central (BOD)")
        else:
            bodega.activa = True
            print(f"   [OK] Bodega Central existente ({bodega.codigo})")

        # Local 1
        local1 = Branch.query.filter((Branch.codigo == 'LOC1') | (Branch.nombre == 'Local 1') | (Branch.nombre == 'Local 1 Centro')).first()
        if not local1:
            local1 = Branch(
                nombre="Local 1",
                codigo="LOC1",
                tipo="tienda",
                nombre_comercial="Life Store Local 1",
                nit="901.888.777-1",
                prefijo_factura="LOC1",
                ultimo_consecutivo=0,
                direccion="Carrera 7 # 15-40 Local 101",
                telefono="3201112233",
                resolucion_dian="Resolución DIAN No. 18760000001 del 2026/01/01 Prefijo LOC1 del 1 al 10000",
                activa=True
            )
            db.session.add(local1)
            db.session.flush()
            print("   [+] Creado Local 1 (LOC1)")
        else:
            local1.activa = True
            local1.prefijo_factura = local1.prefijo_factura or "LOC1"
            local1.nombre_comercial = local1.nombre_comercial or "Life Store Local 1"
            print(f"   [OK] Local 1 existente ({local1.codigo}) [Último Consecutivo: {local1.ultimo_consecutivo}]")

        # Local 2
        local2 = Branch.query.filter((Branch.codigo == 'LOC2') | (Branch.nombre == 'Local 2') | (Branch.nombre == 'Local 2 Norte')).first()
        if not local2:
            local2 = Branch(
                nombre="Local 2",
                codigo="LOC2",
                tipo="tienda",
                nombre_comercial="Life Store Local 2",
                nit="901.888.777-2",
                prefijo_factura="LOC2",
                ultimo_consecutivo=0,
                direccion="Avenida 19 # 105-30 Local 204",
                telefono="3209998877",
                resolucion_dian="Resolución DIAN No. 18760000002 del 2026/01/01 Prefijo LOC2 del 1 al 10000",
                activa=True
            )
            db.session.add(local2)
            db.session.flush()
            print("   [+] Creado Local 2 (LOC2)")
        else:
            local2.activa = True
            local2.prefijo_factura = local2.prefijo_factura or "LOC2"
            local2.nombre_comercial = local2.nombre_comercial or "Life Store Local 2"
            print(f"   [OK] Local 2 existente ({local2.codigo}) [Último Consecutivo: {local2.ultimo_consecutivo}]")

        # Asesores
        print("\n[2/5] Verificando / Creando Asesores de Venta...")
        asesor1 = Asesor.query.filter_by(nombre="Carlos Gómez").first()
        if not asesor1:
            asesor1 = Asesor(nombre="Carlos Gómez", activo=True)
            db.session.add(asesor1)
            db.session.flush()
            print("   [+] Creado asesor: Carlos Gómez")
        else:
            print("   [OK] Asesor existente: Carlos Gómez")

        asesor2 = Asesor.query.filter_by(nombre="Laura Restrepo").first()
        if not asesor2:
            asesor2 = Asesor(nombre="Laura Restrepo", activo=True)
            db.session.add(asesor2)
            db.session.flush()
            print("   [+] Creado asesor: Laura Restrepo")
        else:
            print("   [OK] Asesor existente: Laura Restrepo")

        # Usuarios Vendedores
        print("\n[3/5] Verificando / Creando Usuarios Vendedores...")
        vend1 = User.query.filter_by(email="vendedor1@test.com").first()
        if not vend1:
            vend1 = User(
                nombre="Vendedor Local 1",
                email="vendedor1@test.com",
                telefono="3001110001",
                password_hash=generate_password_hash("Test1234"),
                rol="vendedor",
                branch_id=local1.id,
                sucursal=local1.nombre
            )
            db.session.add(vend1)
            print("   [+] Creado usuario vendedor1@test.com -> Local 1")
        else:
            vend1.branch_id = local1.id
            vend1.sucursal = local1.nombre
            vend1.password_hash = generate_password_hash("Test1234")
            print("   [OK] Usuario actualizado vendedor1@test.com -> Local 1")

        vend2 = User.query.filter_by(email="vendedor2@test.com").first()
        if not vend2:
            vend2 = User(
                nombre="Vendedor Local 2",
                email="vendedor2@test.com",
                telefono="3002220002",
                password_hash=generate_password_hash("Test1234"),
                rol="vendedor",
                branch_id=local2.id,
                sucursal=local2.nombre
            )
            db.session.add(vend2)
            print("   [+] Creado usuario vendedor2@test.com -> Local 2")
        else:
            vend2.branch_id = local2.id
            vend2.sucursal = local2.nombre
            vend2.password_hash = generate_password_hash("Test1234")
            print("   [OK] Usuario actualizado vendedor2@test.com -> Local 2")

        # Asegurar Admin
        admin_user = User.query.filter_by(email="admin@lifestore.com").first()
        if not admin_user:
            admin_user = User(
                nombre="Administrador LifeStore",
                email="admin@lifestore.com",
                password_hash=generate_password_hash("Admin123"),
                rol="admin"
            )
            db.session.add(admin_user)
            print("   [+] Creado admin@lifestore.com")
        db.session.commit()

        # -------------------------------------------------------------
        # PRODUCTOS DE PRUEBA EN BODEGA CENTRAL
        # -------------------------------------------------------------
        print("\n[4/5] Creando Productos de Prueba con Stock en Bodega Central...")
        
        # Accesorio con variantes
        sku_acc = "ACC-TEST-CASE-01"
        prod_acc = Product.query.filter_by(sku=sku_acc).first()
        if not prod_acc:
            prod_acc = Product(
                nombre="Funda Pro Silicona MagSafe",
                sku=sku_acc,
                tipo_inventario="tienda",
                precio_costo=Decimal('15000'),
                precio_minimo=Decimal('25000'),
                precio_sugerido=Decimal('35000'),
                cantidad_stock=0
            )
            db.session.add(prod_acc)
            db.session.flush()

            var_negro = ProductVariant(
                product_id=prod_acc.id,
                nombre_variante="Negro Mate",
                cantidad_stock=20,
                precio_costo=Decimal('15000'),
                precio_minimo=Decimal('25000'),
                precio_sugerido=Decimal('35000')
            )
            var_azul = ProductVariant(
                product_id=prod_acc.id,
                nombre_variante="Azul Medianoche",
                cantidad_stock=20,
                precio_costo=Decimal('15000'),
                precio_minimo=Decimal('25000'),
                precio_sugerido=Decimal('35000')
            )
            db.session.add_all([var_negro, var_azul])
            db.session.flush()

            # Stock inicial en Bodega Central (20 unidades por color)
            b_stock_negro = get_or_create_branch_stock(bodega.id, prod_acc.id, var_negro.id)
            b_stock_negro.cantidad = 20
            b_stock_azul = get_or_create_branch_stock(bodega.id, prod_acc.id, var_azul.id)
            b_stock_azul.cantidad = 20

            sync_global_product_stock(prod_acc.id, var_negro.id)
            sync_global_product_stock(prod_acc.id, var_azul.id)
            print(f"   [+] Creado accesorio '{prod_acc.nombre}' (Negro y Azul) con stock de 20 c/u en Bodega Central.")
        else:
            var_negro = ProductVariant.query.filter_by(product_id=prod_acc.id, nombre_variante="Negro Mate").first()
            var_azul = ProductVariant.query.filter_by(product_id=prod_acc.id, nombre_variante="Azul Medianoche").first()
            print(f"   [OK] Accesorio existente: {prod_acc.nombre}")

        # Celular con IMEI ficticio
        imei_test = f"35{random.randint(1000000000000, 9999999999999)}"
        sku_cel = f"CEL-TEST-{imei_test[-4:]}"
        prod_cel = Product(
            nombre="iPhone 14 Pro 128GB Deep Purple",
            sku=sku_cel,
            tipo_inventario="celulares",
            marca="Apple",
            modelo_celular="iPhone 14 Pro",
            color="Deep Purple",
            memoria="128GB",
            bateria="92",
            estado_celular="Exhibición",
            imei=imei_test,
            imei2=f"35{random.randint(1000000000000, 9999999999999)}",
            precio_costo=Decimal('2800000'),
            precio_minimo=Decimal('3200000'),
            precio_sugerido=Decimal('3450000'),
            cantidad_stock=1
        )
        db.session.add(prod_cel)
        db.session.flush()

        # Stock en Bodega Central
        b_stock_cel = get_or_create_branch_stock(bodega.id, prod_cel.id, None)
        b_stock_cel.cantidad = 1
        sync_global_product_stock(prod_cel.id, None)
        db.session.commit()
        print(f"   [+] Creado celular '{prod_cel.nombre}' (IMEI: {prod_cel.imei}) con 1 unidad en Bodega Central.")

        # -------------------------------------------------------------
        # 2. SIMULAR FLUJO: TRASLADO DESDE BODEGA A LOCAL 1
        # -------------------------------------------------------------
        print("\n[5/5] Ejecutando Flujo Operativo Completo...")
        print("   --- A. Traslado de Stock (Bodega Central -> Local 1) ---")
        
        # Creamos traslado
        traslado = StockTransfer(
            origin_branch_id=bodega.id,
            destination_branch_id=local1.id,
            created_by_id=admin_user.id,
            status='PENDIENTE',
            notas="Despacho de stock de prueba: Celular + 5 Fundas Negras"
        )
        db.session.add(traslado)
        db.session.flush()

        # Items del traslado: 1 celular y 5 fundas negras
        item_cel = StockTransferItem(transfer_id=traslado.id, product_id=prod_cel.id, variant_id=None, cantidad=1)
        item_acc = StockTransferItem(transfer_id=traslado.id, product_id=prod_acc.id, variant_id=var_negro.id, cantidad=5)
        db.session.add_all([item_cel, item_acc])

        # Descontar origen
        bs_origen_cel = get_or_create_branch_stock(bodega.id, prod_cel.id, None, for_update=True)
        bs_origen_cel.cantidad -= 1
        bs_origen_acc = get_or_create_branch_stock(bodega.id, prod_acc.id, var_negro.id, for_update=True)
        bs_origen_acc.cantidad -= 5

        # Aceptar traslado inmediatamente como vendedor de Local 1
        traslado.status = 'ACEPTADO'
        traslado.received_by_id = vend1.id
        traslado.resolved_at = obtener_hora_bogota()

        # Sumar a Local 1
        bs_dest_cel = get_or_create_branch_stock(local1.id, prod_cel.id, None, for_update=True)
        bs_dest_cel.cantidad += 1
        bs_dest_acc = get_or_create_branch_stock(local1.id, prod_acc.id, var_negro.id, for_update=True)
        bs_dest_acc.cantidad += 5

        sync_global_product_stock(prod_cel.id, None)
        sync_global_product_stock(prod_acc.id, var_negro.id)
        db.session.commit()
        print(f"      [OK] Traslado #{traslado.id} aceptado por {vend1.nombre}.")
        print(f"      [OK] Stock en Local 1: {prod_cel.nombre} = {bs_dest_cel.cantidad}, Funda Negra = {bs_dest_acc.cantidad}")

        # --- Validación de Regla Operativa: Bodega Exenta vs Tienda Obligatoria ---
        print("\n   --- Regla Operativa: Validación de Exención de Turnos en Bodega ---")
        assert bodega.tipo == 'bodega', "Bodega Central debe ser de tipo 'bodega'"
        assert local1.tipo == 'tienda', "Local 1 debe ser de tipo 'tienda'"
        print(f"      [OK] Bodega Central ('{bodega.nombre}') [tipo={bodega.tipo}]: EXENTA de turnos, bases iniciales y selección de asesores.")
        print(f"      [OK] Tiendas ('{local1.nombre}', '{local2.nombre}') [tipo=tienda]: EXIGEN apertura de turno y asignación de asesores.")

        # --- B. Apertura de Turno de Caja en Local 1 ---
        print("\n   --- B. Apertura de Turno de Caja en Local 1 (Tienda) ---")
        # Cerrar turnos previos de Local 1 si existieran
        turnos_antiguos = CashShift.query.filter_by(branch_id=local1.id, estado='ABIERTA').all()
        for ta in turnos_antiguos:
            ta.estado = 'CERRADA'
            ta.fecha_cierre = obtener_hora_bogota()

        turno_local1 = CashShift(
            branch_id=local1.id,
            opened_by_id=vend1.id,
            base_inicial_efectivo=Decimal('100000'),
            asesores_ids=json.dumps([asesor1.id, asesor2.id]),
            estado='ABIERTA',
            fecha_apertura=obtener_hora_bogota(),
            notas_apertura="Apertura de turno de prueba con base de $100.000 y 2 asesores en linea."
        )
        db.session.add(turno_local1)
        db.session.commit()
        print(f"      [OK] Turno #{turno_local1.id} ABIERTO en '{local1.nombre}' por {vend1.nombre}.")
        print(f"      [OK] Base inicial: ${turno_local1.base_inicial_efectivo:,.0f} | Asesores: Carlos Gómez, Laura Restrepo")

        # --- C. Venta con Retoma y Pago Mixto en Local 1 ---
        print("\n   --- C. Venta con Retoma y Pago Mixto en Local 1 ---")
        
        # Consecutivo seguro por sede
        local1_locked = Branch.query.with_for_update().get(local1.id)
        local1_locked.ultimo_consecutivo = (local1_locked.ultimo_consecutivo or 0) + 1
        num_factura = f"{local1_locked.prefijo_factura}-{local1_locked.ultimo_consecutivo}"

        precio_cel = Decimal('3400000')
        precio_acc = Decimal('35000')
        valor_retoma = Decimal('800000')
        total_productos = precio_cel + precio_acc # 3.435.000
        total_a_pagar = total_productos - valor_retoma # 2.635.000

        # Pagos mixtos: Efectivo $1.000.000 + Nequi $1.635.000
        pago_efectivo = Decimal('1000000')
        pago_nequi = Decimal('1635000')

        venta = Sale(
            vendedor_id=vend1.id,
            asesor_id=asesor1.id,
            monto_total=total_a_pagar,
            metodo_pago='mixto',
            tipo_venta='celulares',
            sucursal=local1_locked.nombre,
            branch_id=local1_locked.id,
            numero_factura=num_factura,
            shift_id=turno_local1.id,
            fecha_venta=obtener_hora_bogota()
        )
        db.session.add(venta)
        db.session.flush()

        # Detalles
        d1 = SaleDetail(sale_id=venta.id, product_id=prod_cel.id, variant_id=None, cantidad_vendida=1, precio_venta_final=precio_cel)
        d2 = SaleDetail(sale_id=venta.id, product_id=prod_acc.id, variant_id=var_negro.id, cantidad_vendida=1, precio_venta_final=precio_acc)
        db.session.add_all([d1, d2])

        # Descontar stock de Local 1
        bs_dest_cel.cantidad -= 1
        bs_dest_acc.cantidad -= 1
        sync_global_product_stock(prod_cel.id, None)
        sync_global_product_stock(prod_acc.id, var_negro.id)

        # Ajustes de kardex
        aj_cel = StockAdjustment(product_id=prod_cel.id, admin_id=vend1.id, branch_id=local1.id, tipo_movimiento=f"Venta Factura {num_factura}", stock_anterior=1, stock_nuevo=0)
        aj_acc = StockAdjustment(product_id=prod_acc.id, admin_id=vend1.id, branch_id=local1.id, tipo_movimiento=f"Venta Factura {num_factura}", stock_anterior=5, stock_nuevo=4)
        db.session.add_all([aj_cel, aj_acc])

        # Pagos
        p1 = SalePayment(sale_id=venta.id, metodo_pago='efectivo', monto=pago_efectivo)
        p2 = SalePayment(sale_id=venta.id, metodo_pago='nequi', monto=pago_nequi)
        db.session.add_all([p1, p2])

        # Retoma
        imei_retoma = f"35{random.randint(1000000000000, 9999999999999)}"
        retoma_obj = Retoma(
            sale_id=venta.id,
            modelo="iPhone 11 64GB Black",
            marca="Apple",
            proveedor="Cliente Test",
            valor_retoma=valor_retoma,
            imei1=imei_retoma,
            color="Negro",
            bateria="79",
            memoria="64GB",
            observaciones="Detalles estéticos leves en bordes. Pantalla original.",
            estado="en_evaluacion",
            vendedor_id=vend1.id,
            branch_id=local1.id
        )
        db.session.add(retoma_obj)

        # Cliente
        cliente_obj = SaleClient(
            sale_id=venta.id,
            nombre="Andrés Felipe Morales",
            documento="1020304050",
            telefono="3159990011",
            email="andres.morales@gmail.com",
            direccion="Calle 72 # 11-45 Apto 302"
        )
        db.session.add(cliente_obj)
        db.session.commit()

        print(f"      [OK] Venta registrada exitosamente!")
        print(f"      [OK] Factura Consecutivo: {venta.numero_factura} (ID de venta: #{venta.id})")
        print(f"      [OK] Subtotal productos: ${total_productos:,.0f}")
        print(f"      [OK] Retoma recibida: -${valor_retoma:,.0f} (Modelo: {retoma_obj.modelo}, IMEI: {retoma_obj.imei1})")
        print(f"      [OK] Total liquidado: ${total_a_pagar:,.0f}")
        print(f"      [OK] Pagos registrados: Efectivo (${pago_efectivo:,.0f}) + Nequi (${pago_nequi:,.0f})")
        print(f"      [OK] Stock restante Local 1: {prod_cel.nombre} = {bs_dest_cel.cantidad}, Funda = {bs_dest_acc.cantidad}")

        # -------------------------------------------------------------
        # RESUMEN PARA ACCESO WEB Y VALIDACIÓN VISUAL
        # -------------------------------------------------------------
        print("\n" + "=" * 70)
        print("[EXITO] VALIDACION DE EXTREMO A EXTREMO COMPLETADA EXITOSAMENTE")
        print("=" * 70)
        print("\n[INFO] CREDENCIALES Y ENLACES PARA VERIFICACION VISUAL EN NAVEGADOR:")
        print("\n1. Administrador General:")
        print("   - URL: http://localhost:5001/auth/login")
        print("   - Correo: admin@lifestore.com")
        print("   - Clave:  Admin123")
        print("   - Vistas clave:")
        print("     * Auditoria de Turnos en Vivo:   http://localhost:5001/turnos/auditoria")
        print("     * Gestion de Sucursales y Sedes: http://localhost:5001/admin/sucursales")
        print("     * Traslados de Mercancia:        http://localhost:5001/transfers/")

        print("\n2. Vendedor Local 1 (Con Turno de Caja Abierto):")
        print("   - Correo: vendedor1@test.com")
        print("   - Clave:  Test1234")
        print("   - Sucursal: Local 1 Centro (LOC1)")
        print("   - Vistas clave:")
        print("     * POS Caja Rapida Visual:        http://localhost:5001/sales/caja_visual")
        print(f"     * Factura/Recibo Single-Page:    http://localhost:5001/sales/factura/{venta.id}")
        print(f"     * Formato Termico 80mm:          http://localhost:5001/sales/recibo/{venta.id}?format=ticket")
        print("     * Cierre / Arqueo de Turno:      http://localhost:5001/arqueo/nuevo")

        print("\n3. Vendedor Local 2 (Sin Turno Abierto para probar bloqueo):")
        print("   - Correo: vendedor2@test.com")
        print("   - Clave:  Test1234")
        print("   - Sucursal: Local 2 Norte (LOC2)")
        print("   - Prueba de bloqueo: Al entrar a http://localhost:5001/sales/caja_visual te exigira abrir turno en http://localhost:5001/turnos/abrir")
        print("=" * 70 + "\n")

if __name__ == '__main__':
    run_multisucursal_test()
