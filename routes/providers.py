import os
from datetime import datetime
import pytz
from werkzeug.utils import secure_filename
from flask import Blueprint, render_template, request, redirect, url_for, flash, current_app, jsonify
from flask_login import login_required, current_user
from models import db, Provider, ProviderInvoice, ProviderPayment
from decorators import admin_required

providers_bp = Blueprint('providers_bp', __name__)

ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'pdf'}

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

@providers_bp.route('/')
@login_required
@admin_required
def list_providers():
    proveedores = Provider.query.order_by(Provider.nombre.asc()).all()
    return render_template('providers/list.html', proveedores=proveedores)

@providers_bp.route('/crear', methods=['POST'])
@login_required
@admin_required
def create_provider():
    nombre = request.form.get('nombre', '').strip()
    empresa = request.form.get('empresa', '').strip()
    telefono = request.form.get('telefono', '').strip()

    if not nombre:
        flash('El nombre del proveedor es obligatorio.', 'danger')
        return redirect(url_for('providers_bp.list_providers'))

    nuevo_proveedor = Provider(
        nombre=nombre,
        empresa=empresa,
        telefono=telefono
    )
    db.session.add(nuevo_proveedor)
    db.session.commit()
    
    flash('Proveedor registrado exitosamente.', 'success')
    return redirect(url_for('providers_bp.list_providers'))

@providers_bp.route('/api/crear_rapido', methods=['POST'])
@login_required
def create_provider_api():
    nombre = request.form.get('nombre', '').strip()
    empresa = request.form.get('empresa', '').strip()
    telefono = request.form.get('telefono', '').strip()

    if not nombre:
        return jsonify({'success': False, 'message': 'El nombre del proveedor es obligatorio.'}), 400

    existente = Provider.query.filter(Provider.nombre.ilike(nombre)).first()
    if existente:
        return jsonify({
            'success': True,
            'provider': {'id': existente.id, 'nombre': existente.nombre},
            'message': 'El proveedor ya existía.'
        })

    nuevo_proveedor = Provider(
        nombre=nombre,
        empresa=empresa,
        telefono=telefono
    )
    db.session.add(nuevo_proveedor)
    db.session.commit()
    
    return jsonify({
        'success': True,
        'provider': {
            'id': nuevo_proveedor.id,
            'nombre': nuevo_proveedor.nombre
        }
    })

@providers_bp.route('/<int:id>')
@login_required
@admin_required
def detail(id):
    proveedor = Provider.query.get_or_404(id)
    # The models use @property to calculate totals automatically.
    facturas = ProviderInvoice.query.filter_by(provider_id=id).order_by(ProviderInvoice.fecha_factura.desc()).all()
    pagos = ProviderPayment.query.filter_by(provider_id=id).order_by(ProviderPayment.fecha_pago.desc()).all()
    
    from models import Product, SaleDetail
    from sqlalchemy.orm import selectinload, joinedload
    from sqlalchemy import or_
    
    try:
        # Filtrar productos del proveedor excluyendo copias residuales con -EXT o estado 'Enviado'
        celulares_raw = Product.query.options(
            selectinload(Product.detalles_venta).joinedload(SaleDetail.venta)
        ).filter(
            Product.tipo_inventario.in_(['celulares', 'externos']),
            Product.proveedor.ilike(proveedor.nombre.strip()),
            or_(Product.imei == None, ~Product.imei.like('%-EXT')),
            or_(Product.estado_celular == None, Product.estado_celular != 'Enviado')
        ).order_by(Product.fecha_creacion.desc()).all()

        # Mapear ventas asociadas a cada celular (por detalles de venta, ProviderInvoice o por IMEI base)
        celulares = []
        for c in celulares_raw:
            sale_id = None
            if c.detalles_venta and len(c.detalles_venta) > 0:
                sale_id = c.detalles_venta[0].sale_id
            
            clean_imei = (c.imei or '').replace('-EXT', '').strip()
            # 1. Si no lo tiene directamente, buscar en facturas del proveedor generadas con ese IMEI
            if not sale_id and clean_imei and len(clean_imei) >= 6:
                try:
                    inv = ProviderInvoice.query.filter(
                        ProviderInvoice.provider_id == id,
                        (ProviderInvoice.numero_factura.ilike(f"%{clean_imei}%") | ProviderInvoice.descripcion.ilike(f"%{clean_imei}%"))
                    ).first()
                    if inv and inv.sale_id_detected:
                        sale_id = inv.sale_id_detected
                except Exception:
                    pass

            # 2. Si aún no, buscar si el IMEI estuvo en otro producto vendido (ej. producto externo anterior)
            if not sale_id and clean_imei and len(clean_imei) >= 6:
                try:
                    other_prod = Product.query.options(
                        selectinload(Product.detalles_venta)
                    ).filter(
                        (Product.imei == clean_imei) | (Product.imei == f"{clean_imei}-EXT") | (Product.imei2 == clean_imei),
                        Product.id != c.id
                    ).first()
                    if other_prod and other_prod.detalles_venta and len(other_prod.detalles_venta) > 0:
                        sale_id = other_prod.detalles_venta[0].sale_id
                except Exception:
                    pass
            
            c.sale_id_display = sale_id
            celulares.append(c)

    except Exception as err:
        current_app.logger.error(f"Error cargando celulares del proveedor: {err}", exc_info=True)
        celulares = []

    return render_template('providers/detail.html', 
                           proveedor=proveedor, 
                           facturas=facturas, 
                           pagos=pagos,
                           celulares=celulares)

@providers_bp.route('/<int:id>/invoice', methods=['POST'])
@login_required
@admin_required
def add_invoice(id):
    proveedor = Provider.query.get_or_404(id)
    
    try:
        monto_total = float(request.form.get('monto_total', 0))
    except ValueError:
        monto_total = 0.0

    if monto_total <= 0:
        flash('El monto de la factura debe ser mayor a 0.', 'danger')
        return redirect(url_for('providers_bp.detail', id=id))

    numero_factura = request.form.get('numero_factura', '').strip()
    descripcion = request.form.get('descripcion', '').strip()
    
    sale_id_val = request.form.get('sale_id', '').strip()
    sale_id = int(sale_id_val) if sale_id_val and sale_id_val.isdigit() else None
    
    filename = None
    if 'comprobante' in request.files:
        file = request.files['comprobante']
        if file and file.filename != '' and allowed_file(file.filename):
            ext = file.filename.rsplit('.', 1)[1].lower()
            timestamp = datetime.now(pytz.timezone('America/Bogota')).strftime('%Y%m%d%H%M%S')
            filename = f"prov_{id}_{timestamp}.{ext}"
            
            # Ensure the directory exists
            upload_folder = os.path.join(current_app.static_folder, 'uploads', 'providers')
            os.makedirs(upload_folder, exist_ok=True)
            
            file_path = os.path.join(upload_folder, filename)
            file.save(file_path)

    nueva_factura = ProviderInvoice(
        provider_id=id,
        sale_id=sale_id,
        monto_total=monto_total,
        numero_factura=numero_factura,
        descripcion=descripcion,
        comprobante=filename
    )
    
    db.session.add(nueva_factura)
    db.session.commit()
    
    flash('Factura registrada correctamente.', 'success')
    return redirect(url_for('providers_bp.detail', id=id))

@providers_bp.route('/<int:id>/payment', methods=['POST'])
@login_required
@admin_required
def add_payment(id):
    proveedor = Provider.query.get_or_404(id)
    
    try:
        monto_abonado = float(request.form.get('monto_abonado', 0))
    except ValueError:
        monto_abonado = 0.0

    if monto_abonado <= 0:
        flash('El monto del abono debe ser mayor a 0.', 'danger')
        return redirect(url_for('providers_bp.detail', id=id))

    observacion = request.form.get('observacion', '').strip()
    metodo_pago = request.form.get('metodo_pago', 'efectivo').strip()
    
    nuevo_pago = ProviderPayment(
        provider_id=id,
        monto_abonado=monto_abonado,
        metodo_pago=metodo_pago,
        observacion=observacion
    )
    
    db.session.add(nuevo_pago)
    db.session.flush()

    # --- INTEGRACIÓN CON BANCOS: DESCONTAR ABONO DEL MÉTODO ESCOGIDO ---
    from services.bank_service import registrar_movimiento_banco
    proveedor = Provider.query.get(id)
    nombre_prov = proveedor.nombre if proveedor else f'ID {id}'
    registrar_movimiento_banco(
        codigo_metodo=metodo_pago,
        monto=monto_abonado,
        tipo_movimiento='EGRESO',
        origen='ABONO_PROVEEDOR',
        descripcion=f'Abono a Proveedor: {nombre_prov} (Abono #{nuevo_pago.id})',
        referencia_id=nuevo_pago.id,
        usuario_id=current_user.id
    )

    db.session.commit()
    
    flash(f'Abono registrado correctamente y descontado de Bancos ({metodo_pago.capitalize()}).', 'success')
    return redirect(url_for('providers_bp.detail', id=id))

@providers_bp.route('/eliminar/<int:id>', methods=['POST'])
@login_required
@admin_required
def delete_provider(id):
    proveedor = Provider.query.get_or_404(id)
    
    # Delete physical files
    facturas = ProviderInvoice.query.filter_by(provider_id=id).all()
    upload_folder = os.path.join(current_app.static_folder, 'uploads', 'providers')
    for f in facturas:
        if f.comprobante:
            file_path = os.path.join(upload_folder, f.comprobante)
            if os.path.exists(file_path):
                try:
                    os.remove(file_path)
                except:
                    pass
    
    db.session.delete(proveedor)
    db.session.commit()
    
    flash('Proveedor eliminado correctamente.', 'success')
    return redirect(url_for('providers_bp.list_providers'))

@providers_bp.route('/editar/<int:id>', methods=['POST'])
@login_required
@admin_required
def edit_provider(id):
    proveedor = Provider.query.get_or_404(id)
    nombre = request.form.get('nombre', '').strip()
    empresa = request.form.get('empresa', '').strip()
    telefono = request.form.get('telefono', '').strip()

    if not nombre:
        flash('El nombre del proveedor es obligatorio.', 'danger')
        return redirect(request.referrer or url_for('providers_bp.list_providers'))

    proveedor.nombre = nombre
    proveedor.empresa = empresa
    proveedor.telefono = telefono

    try:
        db.session.commit()
        flash(f'Proveedor "{nombre}" actualizado correctamente.', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Error al actualizar el proveedor: {str(e)}', 'danger')

    return redirect(request.referrer or url_for('providers_bp.list_providers'))

@providers_bp.route('/payment/eliminar/<int:payment_id>', methods=['POST'])
@login_required
@admin_required
def delete_payment(payment_id):
    pago = ProviderPayment.query.get_or_404(payment_id)
    provider_id = pago.provider_id
    try:
        from services.bank_service import revertir_movimiento_banco
        revertir_movimiento_banco(origen='ABONO_PROVEEDOR', referencia_id=payment_id)

        db.session.delete(pago)
        db.session.commit()
        flash('Abono eliminado correctamente y reversado en Bancos.', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Error al eliminar el abono: {str(e)}', 'danger')

    return redirect(url_for('providers_bp.detail', id=provider_id))

@providers_bp.route('/invoice/eliminar/<int:invoice_id>', methods=['POST'])
@login_required
@admin_required
def delete_invoice(invoice_id):
    factura = ProviderInvoice.query.get_or_404(invoice_id)
    provider_id = factura.provider_id
    try:
        if factura.comprobante:
            upload_folder = os.path.join(current_app.static_folder, 'uploads', 'providers')
            file_path = os.path.join(upload_folder, factura.comprobante)
            if os.path.exists(file_path):
                try:
                    os.remove(file_path)
                except:
                    pass

        db.session.delete(factura)
        db.session.commit()
        flash('Factura eliminada correctamente.', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Error al eliminar la factura: {str(e)}', 'danger')

    return redirect(url_for('providers_bp.detail', id=provider_id))

@providers_bp.route('/invoice/editar/<int:invoice_id>', methods=['POST'])
@login_required
@admin_required
def edit_invoice(invoice_id):
    factura = ProviderInvoice.query.get_or_404(invoice_id)
    provider_id = factura.provider_id

    try:
        monto_total = float(request.form.get('monto_total', 0))
    except ValueError:
        monto_total = 0.0

    if monto_total <= 0:
        flash('El monto de la factura debe ser mayor a 0.', 'danger')
        return redirect(url_for('providers_bp.detail', id=provider_id))

    factura.monto_total = monto_total
    factura.numero_factura = request.form.get('numero_factura', '').strip()
    factura.descripcion = request.form.get('descripcion', '').strip()
    
    sale_id_val = request.form.get('sale_id', '').strip()
    factura.sale_id = int(sale_id_val) if sale_id_val and sale_id_val.isdigit() else None

    if 'comprobante' in request.files:
        file = request.files['comprobante']
        if file and file.filename != '' and allowed_file(file.filename):
            ext = file.filename.rsplit('.', 1)[1].lower()
            timestamp = datetime.now(pytz.timezone('America/Bogota')).strftime('%Y%m%d%H%M%S')
            filename = f"prov_{provider_id}_{timestamp}.{ext}"

            upload_folder = os.path.join(current_app.static_folder, 'uploads', 'providers')
            os.makedirs(upload_folder, exist_ok=True)

            if factura.comprobante:
                old_path = os.path.join(upload_folder, factura.comprobante)
                if os.path.exists(old_path):
                    try:
                        os.remove(old_path)
                    except:
                        pass

            file_path = os.path.join(upload_folder, filename)
            file.save(file_path)
            factura.comprobante = filename

    try:
        db.session.commit()
        flash('Factura actualizada correctamente.', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Error al actualizar la factura: {str(e)}', 'danger')

    return redirect(url_for('providers_bp.detail', id=provider_id))

@providers_bp.route('/payment/editar/<int:payment_id>', methods=['POST'])
@login_required
@admin_required
def edit_payment(payment_id):
    pago = ProviderPayment.query.get_or_404(payment_id)
    provider_id = pago.provider_id

    try:
        monto_abonado = float(request.form.get('monto_abonado', 0))
    except ValueError:
        monto_abonado = 0.0

    if monto_abonado <= 0:
        flash('El monto del abono debe ser mayor a 0.', 'danger')
        return redirect(url_for('providers_bp.detail', id=provider_id))

    pago.monto_abonado = monto_abonado
    pago.observacion = request.form.get('observacion', '').strip()

    try:
        db.session.commit()
        flash('Abono actualizado correctamente.', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Error al actualizar el abono: {str(e)}', 'danger')

    return redirect(url_for('providers_bp.detail', id=provider_id))
