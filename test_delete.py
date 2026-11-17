import logging
import traceback
from app import create_app
from models import db, Sale, ProductVariant, Product, SaleClient

logging.basicConfig(level=logging.INFO)
app = create_app()
with app.app_context():
    try:
        venta = Sale.query.get(12)
        print('Venta:', venta.id)
        for detalle in venta.detalles:
            if detalle.variant_id:
                variante = ProductVariant.query.with_for_update().get(detalle.variant_id)
                producto = Product.query.with_for_update().get(detalle.product_id)
                print('Variante:', variante.id, 'Producto:', producto.id)
            else:
                producto = Product.query.with_for_update().get(detalle.product_id)
                print('Producto:', producto.id)
        
        # Eliminar cliente asociado si existe
        cliente = SaleClient.query.filter_by(sale_id=venta.id).first()
        if cliente:
            print('Eliminando cliente:', cliente.id)
            db.session.delete(cliente)
            
        db.session.delete(venta)
        db.session.commit()
        print('Success')
    except Exception as e:
        print('Error:', e)
        traceback.print_exc()
        db.session.rollback()
