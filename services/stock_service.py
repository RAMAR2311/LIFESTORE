from models import db, BranchStock, Product, ProductVariant
from sqlalchemy.sql import func

def get_or_create_branch_stock(branch_id, product_id, variant_id=None, for_update=False):
    """
    Busca o crea de forma segura un registro en BranchStock.
    Maneja la comparación en SQL de variant_id cuando es None (NULL != NULL en UniqueConstraint).
    """
    query = BranchStock.query.filter(
        BranchStock.branch_id == branch_id,
        BranchStock.product_id == product_id
    )
    if variant_id is None:
        query = query.filter(BranchStock.variant_id.is_(None))
    else:
        query = query.filter(BranchStock.variant_id == variant_id)

    if for_update:
        query = query.with_for_update()

    stock_record = query.first()

    if not stock_record:
        stock_record = BranchStock(
            branch_id=branch_id,
            product_id=product_id,
            variant_id=variant_id,
            cantidad=0
        )
        db.session.add(stock_record)
        db.session.flush()

    return stock_record

def sync_global_product_stock(product_id, variant_id=None):
    """
    Calcula la suma de BranchStock.cantidad en todas las sucursales para ese producto
    (y variante si aplica) y sincroniza Product.cantidad_stock y ProductVariant.cantidad_stock
    como la sumatoria global para mantener retrocompatibilidad total.
    """
    producto = Product.query.get(product_id)
    if not producto:
        return 0

    if variant_id is not None:
        # Sincronizar la variante específica
        variante = ProductVariant.query.get(variant_id)
        if variante:
            total_var = db.session.query(func.coalesce(func.sum(BranchStock.cantidad), 0)).filter(
                BranchStock.product_id == product_id,
                BranchStock.variant_id == variant_id
            ).scalar() or 0
            variante.cantidad_stock = int(total_var)

        # Sincronizar el total del producto padre como la suma de todas sus variantes
        total_todas_variantes = db.session.query(func.coalesce(func.sum(BranchStock.cantidad), 0)).filter(
            BranchStock.product_id == product_id,
            BranchStock.variant_id.isnot(None)
        ).scalar() or 0
        producto.cantidad_stock = int(total_todas_variantes)
        return int(total_todas_variantes)
    else:
        # Producto simple sin variante
        total_prod = db.session.query(func.coalesce(func.sum(BranchStock.cantidad), 0)).filter(
            BranchStock.product_id == product_id,
            BranchStock.variant_id.is_(None)
        ).scalar() or 0
        producto.cantidad_stock = int(total_prod)
        return int(total_prod)

def get_product_stock_distribution(product_id, variant_id=None):
    """
    Retorna una lista de diccionarios con el stock por sucursal para un producto/variante:
    [{'branch_id': 1, 'branch_name': 'Principal', 'branch_code': 'PRIN', 'tipo': 'tienda', 'cantidad': 5}, ...]
    """
    from models import Branch
    branches = Branch.query.filter_by(activa=True).order_by(Branch.tipo.desc(), Branch.nombre.asc()).all()
    distribucion = []
    
    for b in branches:
        query = BranchStock.query.filter(
            BranchStock.branch_id == b.id,
            BranchStock.product_id == product_id
        )
        if variant_id is None:
            # Si el producto tiene variantes registradas, sumamos todas las variantes de esa sucursal
            from models import ProductVariant
            tiene_vars = ProductVariant.query.filter_by(product_id=product_id).first()
            if tiene_vars:
                query = query.filter(BranchStock.variant_id.isnot(None))
                cant = db.session.query(func.coalesce(func.sum(BranchStock.cantidad), 0)).filter(
                    BranchStock.branch_id == b.id,
                    BranchStock.product_id == product_id,
                    BranchStock.variant_id.isnot(None)
                ).scalar() or 0
            else:
                query = query.filter(BranchStock.variant_id.is_(None))
                bs = query.first()
                cant = bs.cantidad if bs else 0
        else:
            query = query.filter(BranchStock.variant_id == variant_id)
            bs = query.first()
            cant = bs.cantidad if bs else 0
        
        distribucion.append({
            'branch_id': b.id,
            'branch_name': b.nombre,
            'branch_code': b.codigo,
            'tipo': b.tipo,
            'cantidad': cant
        })
    return distribucion
