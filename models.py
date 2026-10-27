from flask_sqlalchemy import SQLAlchemy
from flask_login import UserMixin
from datetime import datetime
import pytz

db = SQLAlchemy()

def obtener_hora_bogota():
    """Inyecta el uso de red horario en Colombia a nivel de sistema operativo."""
    return datetime.now(pytz.timezone('America/Bogota')).replace(tzinfo=None)

class Branch(db.Model):
    __tablename__ = 'branches'

    id = db.Column(db.Integer, primary_key=True)
    nombre = db.Column(db.String(100), nullable=False, unique=True)
    codigo = db.Column(db.String(20), nullable=False, unique=True)
    tipo = db.Column(db.String(20), nullable=False, default='tienda')  # 'tienda' o 'bodega'
    direccion = db.Column(db.String(200), nullable=True)
    telefono = db.Column(db.String(50), nullable=True)
    activa = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=obtener_hora_bogota)

    # Campos comerciales independientes para facturación multisede
    nombre_comercial = db.Column(db.String(150), nullable=True)
    nit = db.Column(db.String(50), nullable=True)
    prefijo_factura = db.Column(db.String(10), default='FAC', nullable=False)
    ultimo_consecutivo = db.Column(db.Integer, default=0, nullable=False)
    logo_url = db.Column(db.String(255), nullable=True)
    resolucion_dian = db.Column(db.Text, nullable=True)

    # Relaciones inversas
    usuarios = db.relationship('User', backref='branch', lazy=True)
    ventas = db.relationship('Sale', backref='branch', lazy=True)
    arqueos = db.relationship('ArqueoCaja', backref='branch', lazy=True)
    turnos_caja = db.relationship('CashShift', backref='branch', lazy=True)
    ajustes_stock = db.relationship('StockAdjustment', backref='branch', lazy=True)
    maneos = db.relationship('Maneo', backref='branch', lazy=True)
    gastos = db.relationship('Expense', backref='branch', lazy=True)
    garantias = db.relationship('Warranty', backref='branch', lazy=True)
    retomas = db.relationship('Retoma', backref='branch', lazy=True)
    stocks = db.relationship('BranchStock', backref='branch', lazy=True, cascade='all, delete-orphan')

    def __init__(self, **kwargs):
        super(Branch, self).__init__(**kwargs)


class CashShift(db.Model):
    """Modelo para control de apertura y cierre de turno de caja por sucursal."""
    __tablename__ = 'cash_shifts'

    id = db.Column(db.Integer, primary_key=True)
    branch_id = db.Column(db.Integer, db.ForeignKey('branches.id'), nullable=False, index=True)
    opened_by_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    closed_by_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    base_inicial_efectivo = db.Column(db.Numeric(14, 2), nullable=False, default=0.0)
    asesores_ids = db.Column(db.Text, nullable=True) # JSON o lista separada por comas de IDs de asesores de turno
    estado = db.Column(db.String(20), nullable=False, default='ABIERTA', index=True) # 'ABIERTA', 'CERRADA'
    fecha_apertura = db.Column(db.DateTime, default=obtener_hora_bogota, nullable=False)
    fecha_cierre = db.Column(db.DateTime, nullable=True)
    notas_apertura = db.Column(db.Text, nullable=True)
    arqueo_id = db.Column(db.Integer, db.ForeignKey('arqueo_caja.id'), nullable=True)
    apertura_tardia = db.Column(db.Boolean, default=False, nullable=False)
    minutos_retraso_apertura = db.Column(db.Integer, default=0, nullable=False)
    cierre_tardio = db.Column(db.Boolean, default=False, nullable=False)
    minutos_retraso_cierre = db.Column(db.Integer, default=0, nullable=False)

    opened_by = db.relationship('User', foreign_keys=[opened_by_id], backref='turnos_abiertos')
    closed_by = db.relationship('User', foreign_keys=[closed_by_id], backref='turnos_cerrados')
    arqueo = db.relationship('ArqueoCaja', foreign_keys=[arqueo_id], backref=db.backref('turno_rel', uselist=False))

    def __init__(self, **kwargs):
        super(CashShift, self).__init__(**kwargs)

    @property
    def lista_asesores_ids(self):
        if not self.asesores_ids:
            return []
        import json
        try:
            return json.loads(self.asesores_ids)
        except Exception:
            return [int(x.strip()) for x in self.asesores_ids.split(',') if x.strip().isdigit()]

    @property
    def asesores_obj(self):
        ids = self.lista_asesores_ids
        if not ids:
            return []
        return Asesor.query.filter(Asesor.id.in_(ids)).all()



class BranchStock(db.Model):
    __tablename__ = 'branch_stocks'

    id = db.Column(db.Integer, primary_key=True)
    branch_id = db.Column(db.Integer, db.ForeignKey('branches.id'), nullable=False, index=True)
    product_id = db.Column(db.Integer, db.ForeignKey('products.id'), nullable=False, index=True)
    variant_id = db.Column(db.Integer, db.ForeignKey('product_variants.id'), nullable=True, index=True)
    cantidad = db.Column(db.Integer, nullable=False, default=0)
    updated_at = db.Column(db.DateTime, default=obtener_hora_bogota, onupdate=obtener_hora_bogota)

    product = db.relationship('Product', backref=db.backref('branch_stocks', lazy=True, cascade='all, delete-orphan'))
    variant = db.relationship('ProductVariant', backref=db.backref('branch_stocks', lazy=True, cascade='all, delete-orphan'))

    __table_args__ = (
        db.UniqueConstraint('branch_id', 'product_id', 'variant_id', name='uq_branch_product_variant'),
    )

    def __init__(self, **kwargs):
        super(BranchStock, self).__init__(**kwargs)


class StockTransfer(db.Model):
    __tablename__ = 'stock_transfers'

    id = db.Column(db.Integer, primary_key=True)
    origin_branch_id = db.Column(db.Integer, db.ForeignKey('branches.id'), nullable=False)
    destination_branch_id = db.Column(db.Integer, db.ForeignKey('branches.id'), nullable=False)
    created_by_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    received_by_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    
    # Responsables explícitos de custodia física
    enviado_por_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    recibido_por_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    observaciones_entrega = db.Column(db.Text, nullable=True)
    observaciones_recepcion = db.Column(db.Text, nullable=True)

    status = db.Column(db.String(20), nullable=False, default='PENDIENTE')  # 'PENDIENTE', 'ACEPTADO', 'RECHAZADO'
    notas = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=obtener_hora_bogota)
    resolved_at = db.Column(db.DateTime, nullable=True)

    origin_branch = db.relationship('Branch', foreign_keys=[origin_branch_id], backref=db.backref('transfers_sent', lazy=True))
    destination_branch = db.relationship('Branch', foreign_keys=[destination_branch_id], backref=db.backref('transfers_received', lazy=True))
    created_by = db.relationship('User', foreign_keys=[created_by_id], backref=db.backref('transfers_created', lazy=True))
    received_by = db.relationship('User', foreign_keys=[received_by_id], backref=db.backref('transfers_received_user', lazy=True))
    enviado_por = db.relationship('User', foreign_keys=[enviado_por_id], backref=db.backref('traslados_despachados', lazy=True))
    recibido_por = db.relationship('User', foreign_keys=[recibido_por_id], backref=db.backref('traslados_recibidos', lazy=True))
    items = db.relationship('StockTransferItem', backref='transfer', lazy=True, cascade='all, delete-orphan')

    def __init__(self, **kwargs):
        super(StockTransfer, self).__init__(**kwargs)

    @property
    def usuario_despacha(self):
        return self.enviado_por or self.created_by

    @property
    def usuario_recibe(self):
        return self.recibido_por or self.received_by


class StockTransferItem(db.Model):
    __tablename__ = 'stock_transfer_items'

    id = db.Column(db.Integer, primary_key=True)
    transfer_id = db.Column(db.Integer, db.ForeignKey('stock_transfers.id'), nullable=False)
    product_id = db.Column(db.Integer, db.ForeignKey('products.id'), nullable=False)
    variant_id = db.Column(db.Integer, db.ForeignKey('product_variants.id'), nullable=True)
    cantidad = db.Column(db.Integer, nullable=False)

    product = db.relationship('Product')
    variant = db.relationship('ProductVariant')

    def __init__(self, **kwargs):
        super(StockTransferItem, self).__init__(**kwargs)


class User(UserMixin, db.Model):
    __tablename__ = 'users'
    
    id = db.Column(db.Integer, primary_key=True)
    nombre = db.Column(db.String(100), nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False, index=True)
    telefono = db.Column(db.String(20)) # Nuevo Campo de Contacto (Nullable por Defecto)
    password_hash = db.Column(db.String(256), nullable=False)
    rol = db.Column(db.String(50), nullable=False, default='vendedor')
    sucursal = db.Column(db.String(100), nullable=False, default='PRINCIPAL')
    branch_id = db.Column(db.Integer, db.ForeignKey('branches.id'), nullable=True, index=True)
    
    ventas = db.relationship('Sale', foreign_keys='Sale.vendedor_id', backref='vendedor', lazy=True)
    ajustes_stock = db.relationship('StockAdjustment', backref='admin', lazy=True)
    arqueos = db.relationship('ArqueoCaja', foreign_keys='ArqueoCaja.vendedor_id', backref='cajero', lazy=True, overlaps="arqueos_registrados,vendedor")

    def __init__(self, nombre=None, email=None, telefono=None, password_hash=None, rol=None, branch_id=None, **kwargs):
        if nombre is not None: kwargs['nombre'] = nombre
        if email is not None: kwargs['email'] = email
        if telefono is not None: kwargs['telefono'] = telefono
        if password_hash is not None: kwargs['password_hash'] = password_hash
        if rol is not None: kwargs['rol'] = rol
        if branch_id is not None: kwargs['branch_id'] = branch_id
        if 'sucursal' in kwargs: pass
        super(User, self).__init__(**kwargs)

class Product(db.Model):
    __tablename__ = 'products'
    
    id = db.Column(db.Integer, primary_key=True)
    nombre = db.Column(db.String(150), nullable=False)
    sku = db.Column(db.String(50), unique=True, nullable=False, index=True)
    tipo_inventario = db.Column(db.String(50), nullable=False, server_default='tienda') # 'tienda' o 'bodega'
    cantidad_stock = db.Column(db.Integer, nullable=False, default=0)
    precio_costo = db.Column(db.Numeric(10, 2), nullable=False, default=0.00) # El Costo de Bodega
    precio_minimo = db.Column(db.Numeric(10, 2), nullable=False)
    precio_sugerido = db.Column(db.Numeric(10, 2), nullable=False)
    imagen = db.Column(db.String(255), nullable=True) # Nombre de la foto subida
    observacion = db.Column(db.Text, nullable=True) # Nota descriptiva
    fecha_creacion = db.Column(db.DateTime, default=obtener_hora_bogota)
    
    # Campos específicos para módulo de celulares (tipo_inventario='celulares')
    imei = db.Column(db.String(50), unique=True, nullable=True, index=True)
    imei2 = db.Column(db.String(50), nullable=True)
    marca = db.Column(db.String(100), nullable=True)
    modelo_celular = db.Column(db.String(100), nullable=True)
    estado_celular = db.Column(db.String(50), nullable=True, default='Nuevo') # Nuevo, Usado
    color = db.Column(db.String(50), nullable=True)
    bateria = db.Column(db.String(20), nullable=True) # % o descripción
    memoria = db.Column(db.String(50), nullable=True) # Capacidad (Ej: 128GB)
    proveedor = db.Column(db.String(150), nullable=True)
    inventario = db.Column(db.String(100), nullable=True)
    
    detalles_venta = db.relationship('SaleDetail', backref='producto', lazy=True)
    ajustes_stock = db.relationship('StockAdjustment', backref='producto_rel', lazy=True, cascade="all, delete-orphan")
    variantes = db.relationship('ProductVariant', backref='producto', lazy=True, cascade="all, delete-orphan")

    def __init__(self, **kwargs):
        super(Product, self).__init__(**kwargs)

    @property
    def total_stock(self):
        if self.variantes:
            return sum(v.cantidad_stock for v in self.variantes)
        return self.cantidad_stock

    @property
    def rango_precios(self):
        if not self.variantes:
            return None
        precios = [v.precio_sugerido for v in self.variantes if v.precio_sugerido is not None]
        if not precios:
            return None
        min_p = min(precios)
        max_p = max(precios)
        if min_p == max_p:
            return min_p
        return (min_p, max_p)

    @property
    def rango_costos(self):
        if not self.variantes:
            return None
        precios = [v.precio_costo for v in self.variantes if v.precio_costo is not None]
        if not precios:
            return None
        min_p = min(precios)
        max_p = max(precios)
        if min_p == max_p:
            return min_p
        return (min_p, max_p)

    @property
    def rango_minimos(self):
        if not self.variantes:
            return None
        precios = [v.precio_minimo for v in self.variantes if v.precio_minimo is not None]
        if not precios:
            return None
        min_p = min(precios)
        max_p = max(precios)
        if min_p == max_p:
            return min_p
        return (min_p, max_p)

    @property
    def maneo_activo(self):
        if not self.maneos:
            return None
        for m in self.maneos:
            if m.estado == 'PENDIENTE':
                return m
        return None

    @property
    def soporte_activo(self):
        if not self.servicios_tecnicos:
            return None
        for s in self.servicios_tecnicos:
            if s.estado in ['EN_REVISION', 'EN_REPARACION']:
                return s
        return None

    @property
    def cambio_activo(self):
        if not self.cambios_salida:
            return None
        for c in self.cambios_salida:
            if c.estado == 'PENDIENTE':
                return c
        return None

    @property
    def cambio_activo(self):
        if not self.cambios_salida:
            return None
        for c in self.cambios_salida:
            if c.estado == 'PENDIENTE':
                return c
        return None

class ProductVariant(db.Model):
    __tablename__ = 'product_variants'

    id = db.Column(db.Integer, primary_key=True)
    product_id = db.Column(db.Integer, db.ForeignKey('products.id'), nullable=False)
    nombre_variante = db.Column(db.String(100), nullable=False)
    cantidad_stock = db.Column(db.Integer, nullable=False, default=0)
    
    # Nuevos precios específicos para variantes
    precio_costo = db.Column(db.Numeric(10, 2), nullable=True) 
    precio_minimo = db.Column(db.Numeric(10, 2), nullable=True)
    precio_sugerido = db.Column(db.Numeric(10, 2), nullable=True)

    def __init__(self, **kwargs):
        super(ProductVariant, self).__init__(**kwargs)

class Sale(db.Model):
    __tablename__ = 'sales'
    
    id = db.Column(db.Integer, primary_key=True)
    vendedor_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    fecha_venta = db.Column(db.DateTime, default=obtener_hora_bogota)
    monto_total = db.Column(db.Numeric(10, 2), nullable=False, default=0.0)
    metodo_pago = db.Column(db.String(50), nullable=False, default='efectivo')
    tipo_venta = db.Column(db.String(50), nullable=False, server_default='general') # 'general' o 'celulares'
    sucursal = db.Column(db.String(100), nullable=False, default='PRINCIPAL')
    branch_id = db.Column(db.Integer, db.ForeignKey('branches.id'), nullable=True, index=True)
    numero_factura = db.Column(db.String(50), nullable=True, index=True) # ej: "FAC-1", "SUR-102"
    shift_id = db.Column(db.Integer, db.ForeignKey('cash_shifts.id'), nullable=True, index=True)
    
    detalles = db.relationship('SaleDetail', backref='venta', lazy=True, cascade="all, delete-orphan")
    pagos = db.relationship('SalePayment', backref='venta', lazy=True, cascade="all, delete-orphan")
    cliente = db.relationship('SaleClient', backref='venta', lazy=True, cascade="all, delete-orphan", uselist=False)
    turno = db.relationship('CashShift', backref=db.backref('ventas', lazy=True))
    asesor_id = db.Column(db.Integer, db.ForeignKey('asesores.id'), nullable=True)
    asesor = db.relationship('Asesor', backref=db.backref('ventas', lazy=True))
    provider_id = db.Column(db.Integer, db.ForeignKey('providers.id'), nullable=True)
    provider = db.relationship('Provider', backref=db.backref('ventas', lazy=True))

    def __init__(self, **kwargs):
        super(Sale, self).__init__(**kwargs)

    @property
    def metodo_pago_display(self):
        """Retorna un resumen legible del método de pago.
        Si es pago único, retorna el nombre del método.
        Si es mixto, retorna 'Pago Mixto' con desglose."""
        if not self.pagos:
            # Retrocompatibilidad con ventas antiguas que solo tienen metodo_pago
            return self.metodo_pago.capitalize() if self.metodo_pago else 'Efectivo'
        if len(self.pagos) == 1:
            return self.pagos[0].metodo_pago.capitalize()
        return 'Pago Mixto'

class SalePayment(db.Model):
    """Modelo para soportar pagos mixtos/parciales por venta.
    Permite registrar múltiples métodos de pago en una sola venta.
    Ej: $50.000 en efectivo + $30.000 por Nequi = $80.000 total."""
    __tablename__ = 'sale_payments'

    id = db.Column(db.Integer, primary_key=True)
    sale_id = db.Column(db.Integer, db.ForeignKey('sales.id'), nullable=False)
    metodo_pago = db.Column(db.String(50), nullable=False)  # efectivo, nequi, bancolombia, daviplata, abono_tercero
    monto = db.Column(db.Numeric(10, 2), nullable=False)
    provider_id = db.Column(db.Integer, db.ForeignKey('providers.id'), nullable=True)
    comprobante = db.Column(db.String(255), nullable=True)

    provider = db.relationship('Provider', backref=db.backref('sale_payments', lazy=True))

    def __init__(self, **kwargs):
        super(SalePayment, self).__init__(**kwargs)

class SaleClient(db.Model):
    """Modelo para almacenar los datos del cliente, especialmente requerido en ventas de celulares."""
    __tablename__ = 'sale_clients'
    
    id = db.Column(db.Integer, primary_key=True)
    sale_id = db.Column(db.Integer, db.ForeignKey('sales.id'), nullable=False, unique=True)
    nombre = db.Column(db.String(150), nullable=False)
    documento = db.Column(db.String(50), nullable=False, index=True)
    telefono = db.Column(db.String(50), nullable=False)
    email = db.Column(db.String(120), nullable=True)
    direccion = db.Column(db.String(200), nullable=True)
    
    # Relación configurada desde Sale

    def __init__(self, **kwargs):
        super(SaleClient, self).__init__(**kwargs)

class SaleDetail(db.Model):
    __tablename__ = 'sale_details'
    
    id = db.Column(db.Integer, primary_key=True)
    sale_id = db.Column(db.Integer, db.ForeignKey('sales.id'), nullable=False)
    product_id = db.Column(db.Integer, db.ForeignKey('products.id'), nullable=True)
    variant_id = db.Column(db.Integer, db.ForeignKey('product_variants.id'), nullable=True)
    cantidad_vendida = db.Column(db.Integer, nullable=False)
    precio_venta_final = db.Column(db.Numeric(10, 2), nullable=False)
    # Campos para productos manuales (prestados de otros locales)
    nombre_manual = db.Column(db.String(200), nullable=True)
    precio_costo_manual = db.Column(db.Numeric(10, 2), nullable=True)
    ok_contabilidad = db.Column(db.Boolean, default=False, nullable=False)
    ok_inventario = db.Column(db.Boolean, default=False, nullable=False)

    variante = db.relationship('ProductVariant', backref='ventas_rel', lazy=True)

    def __init__(self, **kwargs):
        super(SaleDetail, self).__init__(**kwargs)

class StockAdjustment(db.Model):
    __tablename__ = 'stock_adjustments'
    
    id = db.Column(db.Integer, primary_key=True)
    product_id = db.Column(db.Integer, db.ForeignKey('products.id'), nullable=False)
    admin_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    branch_id = db.Column(db.Integer, db.ForeignKey('branches.id'), nullable=True, index=True)
    tipo_movimiento = db.Column(db.String(100), nullable=True) # Ej: Creación Inicial, Ajuste Manual
    stock_anterior = db.Column(db.Integer, nullable=False)
    stock_nuevo = db.Column(db.Integer, nullable=False)
    fecha_ajuste = db.Column(db.DateTime, default=obtener_hora_bogota)

    def __init__(self, **kwargs):
        super(StockAdjustment, self).__init__(**kwargs)

class Retoma(db.Model):
    __tablename__ = 'retomas'
    
    id = db.Column(db.Integer, primary_key=True)
    sale_id = db.Column(db.Integer, db.ForeignKey('sales.id'), nullable=False)
    modelo = db.Column(db.String(150), nullable=False)
    marca = db.Column(db.String(100), nullable=True)
    proveedor = db.Column(db.String(150), nullable=True, default='Cliente')
    valor_retoma = db.Column(db.Numeric(10, 2), nullable=False)
    arreglos = db.Column(db.Numeric(10, 2), nullable=True, default=0.0)
    imei1 = db.Column(db.String(50), nullable=False, unique=True)
    imei2 = db.Column(db.String(50), nullable=True)
    color = db.Column(db.String(50), nullable=True)
    bateria = db.Column(db.String(50), nullable=True)
    memoria = db.Column(db.String(50), nullable=True)
    observaciones = db.Column(db.Text, nullable=True)
    estado = db.Column(db.String(50), nullable=False, default='en_evaluacion') # en_evaluacion, aprobado
    ok_contabilidad = db.Column(db.Boolean, default=False, nullable=False)
    ok_venta = db.Column(db.Boolean, default=False, nullable=False)
    producto_generado_id = db.Column(db.Integer, db.ForeignKey('products.id'), nullable=True)
    fecha_registro = db.Column(db.DateTime, default=obtener_hora_bogota)
    vendedor_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    asesor_retoma_id = db.Column(db.Integer, db.ForeignKey('asesores.id'), nullable=True, index=True)
    branch_id = db.Column(db.Integer, db.ForeignKey('branches.id'), nullable=True, index=True)

    venta = db.relationship('Sale', backref='retomas_asociadas', lazy=True)
    vendedor = db.relationship('User', backref='retomas_registradas', lazy=True)
    asesor_retoma = db.relationship('Asesor', foreign_keys=[asesor_retoma_id], backref='retomas_realizadas', lazy=True)
    producto_generado = db.relationship('Product', backref='retoma_origen', lazy=True)

    def __init__(self, **kwargs):
        super(Retoma, self).__init__(**kwargs)

class ArqueoCaja(db.Model):
    __tablename__ = 'arqueo_caja'
    
    id = db.Column(db.Integer, primary_key=True)
    vendedor_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    fecha_arqueo = db.Column(db.Date, nullable=False)
    tipo_arqueo = db.Column(db.String(50), nullable=False, server_default='general') # 'general' o 'celulares'
    sucursal = db.Column(db.String(100), nullable=False, default='PRINCIPAL')
    branch_id = db.Column(db.Integer, db.ForeignKey('branches.id'), nullable=True, index=True)
    base_inicial = db.Column(db.Numeric(14, 2), nullable=False, default=0.0)
    gastos_del_dia = db.Column(db.Numeric(14, 2), nullable=False, default=0.0)
    observaciones_gastos = db.Column(db.String(255), nullable=True)
    total_efectivo_sistema = db.Column(db.Numeric(14, 2), nullable=False, default=0.0)
    total_transferencia_sistema = db.Column(db.Numeric(14, 2), nullable=False, default=0.0)
    total_unidades_ch = db.Column(db.Numeric(14, 2), nullable=False, default=0.0)
    total_celulares = db.Column(db.Numeric(14, 2), nullable=False, default=0.0)
    total_retomas_sistema = db.Column(db.Numeric(14, 2), nullable=False, default=0.0)
    efectivo_fisico = db.Column(db.Numeric(14, 2), nullable=True, default=0.0)
    diferencia = db.Column(db.Numeric(14, 2), nullable=True, default=0.0)
    observacion_diferencia = db.Column(db.Text, nullable=True)
    shift_id = db.Column(db.Integer, db.ForeignKey('cash_shifts.id'), nullable=True, index=True)
    closed_by_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True) # Responsable específico de cierre y conteo
    fecha_creacion = db.Column(db.DateTime, default=obtener_hora_bogota)

    vendedor = db.relationship('User', foreign_keys=[vendedor_id], backref=db.backref('arqueos_registrados', overlaps="arqueos,cajero"), lazy=True, overlaps="arqueos,cajero")
    closed_by = db.relationship('User', foreign_keys=[closed_by_id], backref=db.backref('arqueos_cerrados_custodia', lazy=True))

    def __init__(self, **kwargs):
        super(ArqueoCaja, self).__init__(**kwargs)

    @property
    def cajero_cierre(self):
        """Retorna el usuario responsable que contó el efectivo y ejecutó el arqueo."""
        return self.closed_by or self.vendedor


class SobranteLog(db.Model):
    __tablename__ = 'sobrantes_log'

    id = db.Column(db.Integer, primary_key=True)
    arqueo_id = db.Column(db.Integer, db.ForeignKey('arqueo_caja.id', ondelete='CASCADE'), nullable=True)
    vendedor_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    sucursal = db.Column(db.String(100), nullable=False, default='PRINCIPAL')
    fecha_arqueo = db.Column(db.Date, nullable=False)
    monto_esperado = db.Column(db.Numeric(14, 2), nullable=False, default=0.0)
    efectivo_fisico = db.Column(db.Numeric(14, 2), nullable=False, default=0.0)
    monto_sobrante = db.Column(db.Numeric(14, 2), nullable=False, default=0.0)
    justificacion = db.Column(db.Text, nullable=True)
    fecha_registro = db.Column(db.DateTime, default=obtener_hora_bogota)

    arqueo = db.relationship('ArqueoCaja', backref='sobrantes_rel', lazy=True)
    vendedor = db.relationship('User', backref='sobrantes_registrados', lazy=True)

    def __init__(self, **kwargs):
        super(SobranteLog, self).__init__(**kwargs)

class Maneo(db.Model):
    __tablename__ = 'maneos'

    id = db.Column(db.Integer, primary_key=True)
    product_id = db.Column(db.Integer, db.ForeignKey('products.id'), nullable=False)
    variant_id = db.Column(db.Integer, db.ForeignKey('product_variants.id'), nullable=True)
    local_vecino = db.Column(db.String(150), nullable=False)
    branch_id = db.Column(db.Integer, db.ForeignKey('branches.id'), nullable=True, index=True)
    cantidad = db.Column(db.Integer, nullable=False)
    estado = db.Column(db.String(50), nullable=False, default='PENDIENTE') # PENDIENTE, FACTURADO, DEVUELTO
    fecha_prestamo = db.Column(db.DateTime, default=obtener_hora_bogota)
    fecha_resolucion = db.Column(db.DateTime, nullable=True)

    producto = db.relationship('Product', backref='maneos', lazy=True)
    variante = db.relationship('ProductVariant', backref='maneos_rel', lazy=True)

    def __init__(self, **kwargs):
        super(Maneo, self).__init__(**kwargs)

class Expense(db.Model):
    __tablename__ = 'expenses'
    
    id = db.Column(db.Integer, primary_key=True)
    usuario_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    tipo_gasto = db.Column(db.String(50), nullable=False) # 'Gasto Diario' o 'Costo Indirecto'
    categoria = db.Column(db.String(100), nullable=False)
    descripcion = db.Column(db.String(255), nullable=True)
    monto = db.Column(db.Numeric(10, 2), nullable=False)
    metodo_pago = db.Column(db.String(50), nullable=False, default='efectivo')
    sucursal = db.Column(db.String(100), nullable=False, default='PRINCIPAL')
    branch_id = db.Column(db.Integer, db.ForeignKey('branches.id'), nullable=True, index=True)
    fecha_gasto = db.Column(db.DateTime, default=obtener_hora_bogota)

    usuario = db.relationship('User', backref='gastos', lazy=True)

    def __init__(self, **kwargs):
        super(Expense, self).__init__(**kwargs)

class Cliente(db.Model):
    __tablename__ = 'clientes'

    id = db.Column(db.Integer, primary_key=True)
    nombre_o_razon_social = db.Column(db.String(150), nullable=False)
    documento_o_nit = db.Column(db.String(50), unique=True, nullable=False, index=True)
    telefono = db.Column(db.String(50), nullable=False)
    email = db.Column(db.String(120), nullable=True)
    direccion = db.Column(db.String(255), nullable=True)
    creado_por_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True) # ID del vendedor/admin que lo creó
    fecha_registro = db.Column(db.DateTime, default=obtener_hora_bogota)

    facturas = db.relationship('FacturaBodega', backref='cliente', lazy=True)
    abonos = db.relationship('AbonoBodega', backref='cliente', lazy=True)

    def __init__(self, **kwargs):
        super(Cliente, self).__init__(**kwargs)

    @property
    def total_contado(self):
        return sum(f.monto_total for f in self.facturas if f.modalidad == 'contado')

    @property
    def total_credito(self):
        return sum(f.monto_total for f in self.facturas if f.modalidad == 'credito')

    @property
    def total_abonado(self):
        # Solo sumamos abonos que NO son de facturas de contado (los de contado ya se reflejan en total_contado)
        return sum(a.monto for a in self.abonos if not (a.factura and a.factura.modalidad == 'contado'))

    @property
    def deuda_total(self):
        # La deuda es el total de crédito menos lo abonado a crédito o a cuenta global
        return self.total_credito - self.total_abonado

    @property
    def estado_global(self):
        return "Con Deuda" if self.deuda_total > 0 else "Al Día"

class FacturaBodega(db.Model):
    __tablename__ = 'facturas_bodega'

    id = db.Column(db.Integer, primary_key=True)
    cliente_id = db.Column(db.Integer, db.ForeignKey('clientes.id'), nullable=False)
    usuario_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    numero_factura = db.Column(db.String(100), nullable=False)
    archivo_ruta = db.Column(db.String(255), nullable=True)
    monto_total = db.Column(db.Numeric(10, 2), nullable=False, default=0.0)
    modalidad = db.Column(db.String(50), nullable=False, default='credito') # contado o credito
    estado = db.Column(db.String(50), nullable=False, default='Pendiente') # Pendiente, Parcial, Pagado
    fecha_subida = db.Column(db.DateTime, default=obtener_hora_bogota)

    usuario = db.relationship('User', backref='facturas_subidas', lazy=True)
    abonos = db.relationship('AbonoBodega', backref='factura', lazy=True, cascade="all, delete-orphan")
    detalles = db.relationship('FacturaBodegaDetalle', backref='factura', lazy=True, cascade="all, delete-orphan")

    def __init__(self, **kwargs):
        super(FacturaBodega, self).__init__(**kwargs)

    @property
    def saldo_pendiente(self):
        # Esta propiedad se vuelve menos relevante con abonos globales, 
        # pero podemos mantenerla como una referencia teórica si no hay abonos.
        # Sin embargo, para no romper código existente, la dejamos así por ahora.
        total_abonado_factura = sum(abono.monto for abono in self.abonos) or 0
        return self.monto_total - total_abonado_factura

class FacturaBodegaDetalle(db.Model):
    __tablename__ = 'facturas_bodega_detalles'

    id = db.Column(db.Integer, primary_key=True)
    factura_id = db.Column(db.Integer, db.ForeignKey('facturas_bodega.id'), nullable=False)
    producto_id = db.Column(db.Integer, db.ForeignKey('products.id'), nullable=False)
    variant_id = db.Column(db.Integer, db.ForeignKey('product_variants.id'), nullable=True)
    cantidad = db.Column(db.Integer, nullable=False)
    precio_venta = db.Column(db.Numeric(10, 2), nullable=True) # Opcional para futuros análisis

    producto = db.relationship('Product', backref='detalles_factura_bodega', lazy=True)
    variante = db.relationship('ProductVariant', backref='detalles_factura_bodega_rel', lazy=True)

    def __init__(self, **kwargs):
        super(FacturaBodegaDetalle, self).__init__(**kwargs)

class AbonoBodega(db.Model):
    __tablename__ = 'abonos_bodega'

    id = db.Column(db.Integer, primary_key=True)
    cliente_id = db.Column(db.Integer, db.ForeignKey('clientes.id'), nullable=False)
    factura_id = db.Column(db.Integer, db.ForeignKey('facturas_bodega.id'), nullable=True)
    usuario_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    monto = db.Column(db.Numeric(10, 2), nullable=False)
    metodo_pago = db.Column(db.String(50), nullable=False, default='efectivo')
    observacion = db.Column(db.String(255), nullable=True)
    fecha_abono = db.Column(db.DateTime, default=obtener_hora_bogota)

    usuario = db.relationship('User', backref='abonos_registrados', lazy=True)

    def __init__(self, **kwargs):
        super(AbonoBodega, self).__init__(**kwargs)


class Provider(db.Model):
    __tablename__ = 'providers'

    id = db.Column(db.Integer, primary_key=True)
    nombre = db.Column(db.String(150), nullable=False)
    empresa = db.Column(db.String(150), nullable=True)
    telefono = db.Column(db.String(50), nullable=True)
    fecha_creacion = db.Column(db.DateTime, default=obtener_hora_bogota)

    # Relaciones en cascada
    facturas = db.relationship('ProviderInvoice', backref='provider', lazy=True, cascade='all, delete-orphan')
    pagos = db.relationship('ProviderPayment', backref='provider', lazy=True, cascade='all, delete-orphan')

    def __init__(self, **kwargs):
        super(Provider, self).__init__(**kwargs)

    @property
    def total_facturado(self):
        total_invoices = sum(f.monto_total for f in self.facturas)
        total_sales_cost = 0
        if self.ventas:
            for s in self.ventas:
                for d in s.detalles:
                    if d.producto and d.producto.precio_costo:
                        total_sales_cost += d.producto.precio_costo * d.cantidad_vendida
        from decimal import Decimal
        return Decimal(str(total_invoices or 0)) + Decimal(str(total_sales_cost or 0))
    
    @property
    def total_abonado(self):
        return sum(p.monto_abonado for p in self.pagos)
    
    @property
    def saldo_pendiente(self):
        return self.total_facturado - self.total_abonado

class ProviderInvoice(db.Model):
    __tablename__ = 'provider_invoices'

    id = db.Column(db.Integer, primary_key=True)
    provider_id = db.Column(db.Integer, db.ForeignKey('providers.id'), nullable=False)
    sale_id = db.Column(db.Integer, db.ForeignKey('sales.id'), nullable=True)
    monto_total = db.Column(db.Numeric(12, 2), nullable=False)
    numero_factura = db.Column(db.String(100), nullable=True)
    descripcion = db.Column(db.String(255), nullable=True)
    comprobante = db.Column(db.String(255), nullable=True)
    fecha_factura = db.Column(db.DateTime, default=obtener_hora_bogota)

    sale = db.relationship('Sale', backref=db.backref('provider_invoices', lazy=True))

    def __init__(self, **kwargs):
        super(ProviderInvoice, self).__init__(**kwargs)

    @property
    def sale_id_detected(self):
        if self.sale_id:
            return self.sale_id
        if self.descripcion:
            import re
            match = re.search(r'(?:Venta\s*#?|#)?(\d+)', str(self.descripcion), re.IGNORECASE)
            if match:
                try:
                    return int(match.group(1))
                except ValueError:
                    pass
        return None

    @property
    def producto_detectado(self):
        import re
        texto = f"{self.numero_factura or ''} {self.descripcion or ''}"
        match = re.search(r'\b(35\d{13,15}|\d{15})\b', texto)
        if match:
            imei_buscado = match.group(1)
            p = Product.query.filter((Product.imei == imei_buscado) | (Product.imei2 == imei_buscado)).first()
            if p:
                return p
        return None

class ProviderPayment(db.Model):
    __tablename__ = 'provider_payments'

    id = db.Column(db.Integer, primary_key=True)
    provider_id = db.Column(db.Integer, db.ForeignKey('providers.id'), nullable=False)
    monto_abonado = db.Column(db.Numeric(12, 2), nullable=False)
    metodo_pago = db.Column(db.String(50), nullable=False, default='efectivo')
    observacion = db.Column(db.String(255), nullable=True)
    fecha_pago = db.Column(db.DateTime, default=obtener_hora_bogota)

    def __init__(self, **kwargs):
        super(ProviderPayment, self).__init__(**kwargs)

class Warranty(db.Model):
    __tablename__ = 'warranties'
    id = db.Column(db.Integer, primary_key=True)
    sale_id = db.Column(db.Integer, db.ForeignKey('sales.id'), nullable=False)
    branch_id = db.Column(db.Integer, db.ForeignKey('branches.id'), nullable=True, index=True)
    product_id = db.Column(db.Integer, db.ForeignKey('products.id'), nullable=True)
    nombre_manual = db.Column(db.String(200), nullable=True)
    quantity = db.Column(db.Integer, default=1)
    reason = db.Column(db.Text, nullable=False)
    resolution = db.Column(db.String(50), default='Pendiente')
    admin_notes = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=obtener_hora_bogota)

    # Trazabilidad y Custodia: Recepción
    recibido_por_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    estado_estetico = db.Column(db.String(100), nullable=True) # ej: 'Excelente', 'Buen Estado', 'Rayones Leves', 'Golpes Visibles'
    detalles_esteticos = db.Column(db.Text, nullable=True)
    porcentaje_bateria = db.Column(db.String(20), nullable=True)
    motivo_reportado = db.Column(db.Text, nullable=True)

    # Trazabilidad y Custodia: Entrega al Cliente
    entregado_por_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    fecha_entrega = db.Column(db.DateTime, nullable=True)
    firma_o_soporte_entrega = db.Column(db.String(255), nullable=True)

    # Relaciones
    sale = db.relationship('Sale', backref=db.backref('warranties', lazy=True))
    product = db.relationship('Product', backref=db.backref('warranties', lazy=True))
    recibido_por = db.relationship('User', foreign_keys=[recibido_por_id], backref=db.backref('garantias_recibidas', lazy=True))
    entregado_por = db.relationship('User', foreign_keys=[entregado_por_id], backref=db.backref('garantias_entregadas', lazy=True))

    @property
    def tiempo_transcurrido(self):
        tz = pytz.timezone('America/Bogota')
        now = datetime.now(tz).replace(tzinfo=None)
        
        diff = now - self.created_at
        days = diff.days
        seconds = diff.seconds
        
        if days > 0:
            return f"Hace {days} día{'s' if days > 1 else ''}"
        elif seconds >= 3600:
            hours = seconds // 3600
            return f"Hace {hours} hora{'s' if hours > 1 else ''}"
        elif seconds >= 60:
            minutes = seconds // 60
            return f"Hace {minutes} minuto{'s' if minutes > 1 else ''}"
        else:
            return "Hace un momento"
    @property
    def estado_actual(self):
        tz = pytz.timezone('America/Bogota')
        now = datetime.now(tz).replace(tzinfo=None)
        diff = now - self.created_at
        
        # Si sigue pendiente y pasaron más de 5 días, está demorado
        if self.resolution.lower() == 'pendiente' and diff.days > 5:
            return 'Demorado'
        return self.resolution

class PriceApproval(db.Model):
    __tablename__ = 'price_approvals'
    id = db.Column(db.Integer, primary_key=True)
    vendedor_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    product_id = db.Column(db.Integer, db.ForeignKey('products.id'), nullable=False)
    variant_id = db.Column(db.Integer, nullable=True) # opcional
    precio_original = db.Column(db.Numeric(10, 2), nullable=False)
    precio_solicitado = db.Column(db.Numeric(10, 2), nullable=False)
    precio_aprobado = db.Column(db.Numeric(10, 2), nullable=True)
    estado = db.Column(db.String(20), default='pendiente', index=True)
    admin_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    motivo_rechazo = db.Column(db.String(255), nullable=True)
    fecha_solicitud = db.Column(db.DateTime, default=obtener_hora_bogota)
    fecha_resolucion = db.Column(db.DateTime, nullable=True)

    # Relaciones
    vendedor = db.relationship('User', foreign_keys=[vendedor_id])
    admin = db.relationship('User', foreign_keys=[admin_id])
    product = db.relationship('Product')

class Asesor(db.Model):
    __tablename__ = 'asesores'
    id = db.Column(db.Integer, primary_key=True)
    nombre = db.Column(db.String(100), nullable=False)
    salario_base = db.Column(db.Numeric(14, 2), default=0.0, nullable=False)
    activo = db.Column(db.Boolean, default=True, nullable=False)
    created_at = db.Column(db.DateTime, default=obtener_hora_bogota)

    def __init__(self, **kwargs):
        super(Asesor, self).__init__(**kwargs)


class PurchaseOrder(db.Model):
    __tablename__ = 'purchase_orders'

    id = db.Column(db.Integer, primary_key=True)
    tipo_inventario = db.Column(db.String(50), nullable=False, default='accesorios') # 'celulares' o 'accesorios'
    provider_id = db.Column(db.Integer, db.ForeignKey('providers.id'), nullable=True)
    usuario_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    numero_factura = db.Column(db.String(100), nullable=True)
    observaciones = db.Column(db.Text, nullable=True)
    total_costo = db.Column(db.Numeric(12, 2), nullable=False, default=0.00)
    fecha_compra = db.Column(db.DateTime, default=obtener_hora_bogota)

    # Relaciones
    proveedor = db.relationship('Provider', backref=db.backref('compras', lazy=True))
    usuario = db.relationship('User', foreign_keys=[usuario_id])
    items = db.relationship('PurchaseOrderItem', backref='compra', lazy=True, cascade='all, delete-orphan')

    def __init__(self, **kwargs):
        super(PurchaseOrder, self).__init__(**kwargs)


class PurchaseOrderItem(db.Model):
    __tablename__ = 'purchase_order_items'

    id = db.Column(db.Integer, primary_key=True)
    purchase_order_id = db.Column(db.Integer, db.ForeignKey('purchase_orders.id'), nullable=False)
    product_id = db.Column(db.Integer, db.ForeignKey('products.id'), nullable=False)
    variant_id = db.Column(db.Integer, db.ForeignKey('product_variants.id'), nullable=True)
    cantidad = db.Column(db.Integer, nullable=False, default=1)
    costo_unitario = db.Column(db.Numeric(10, 2), nullable=False, default=0.00)
    subtotal = db.Column(db.Numeric(12, 2), nullable=False, default=0.00)

    # Para celulares con IMEI
    imei = db.Column(db.String(50), nullable=True)
    imei2 = db.Column(db.String(50), nullable=True)

    # Relaciones
    producto = db.relationship('Product')
    variante = db.relationship('ProductVariant')

    def __init__(self, **kwargs):
        super(PurchaseOrderItem, self).__init__(**kwargs)


class BankAccount(db.Model):
    """Modelo para representar los Métodos de Pago / Cuentas Bancarias y su saldo acumulado."""
    __tablename__ = 'bank_accounts'

    id = db.Column(db.Integer, primary_key=True)
    codigo = db.Column(db.String(50), unique=True, nullable=False, index=True) # ej: efectivo, nequi, bancolombia, daviplata, addi, sitecredito, tarjeta_credito
    nombre = db.Column(db.String(100), nullable=False) # ej: Nequi, Bancolombia, Efectivo en Caja
    tipo = db.Column(db.String(50), nullable=False, default='banco') # 'efectivo', 'banco', 'credito_digital', 'tarjeta'
    icono = db.Column(db.String(50), nullable=True, default='fa-building-columns')
    saldo_actual = db.Column(db.Numeric(14, 2), nullable=False, default=0.00)
    activo = db.Column(db.Boolean, default=True, nullable=False)
    fecha_actualizacion = db.Column(db.DateTime, default=obtener_hora_bogota, onupdate=obtener_hora_bogota)

    movimientos = db.relationship('BankTransaction', backref='cuenta', lazy=True, cascade='all, delete-orphan', order_by='desc(BankTransaction.fecha)')

    def __init__(self, **kwargs):
        super(BankAccount, self).__init__(**kwargs)


class BankTransaction(db.Model):
    """Historial completo de sumas (entradas) y descuentos (salidas) por cuenta bancaria/método de pago."""
    __tablename__ = 'bank_transactions'

    id = db.Column(db.Integer, primary_key=True)
    account_id = db.Column(db.Integer, db.ForeignKey('bank_accounts.id'), nullable=False)
    tipo_movimiento = db.Column(db.String(20), nullable=False) # 'INGRESO' o 'EGRESO' o 'AJUSTE'
    origen = db.Column(db.String(50), nullable=False) # 'ARQUEO_CIERRE', 'ABONO_PROVEEDOR', 'GASTO', 'AJUSTE_MANUAL'
    monto = db.Column(db.Numeric(14, 2), nullable=False)
    saldo_anterior = db.Column(db.Numeric(14, 2), nullable=False, default=0.00)
    saldo_nuevo = db.Column(db.Numeric(14, 2), nullable=False, default=0.00)
    descripcion = db.Column(db.String(255), nullable=True)
    referencia_id = db.Column(db.Integer, nullable=True) # ID de Arqueo, Abono o Gasto
    usuario_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    fecha = db.Column(db.DateTime, default=obtener_hora_bogota, index=True)

    usuario = db.relationship('User', foreign_keys=[usuario_id])

    def __init__(self, **kwargs):
        super(BankTransaction, self).__init__(**kwargs)


class CommissionPayment(db.Model):
    """Modelo para registrar anticipos y liquidaciones de comisiones a asesores."""
    __tablename__ = 'commission_payments'

    id = db.Column(db.Integer, primary_key=True)
    asesor_id = db.Column(db.Integer, db.ForeignKey('asesores.id'), nullable=False, index=True)
    monto = db.Column(db.Numeric(14, 2), nullable=False)
    tipo_pago = db.Column(db.String(50), nullable=False)  # 'ANTICIPO', 'LIQUIDACION_TOTAL'
    metodo_pago = db.Column(db.String(50), nullable=False, default='efectivo') # 'efectivo', 'nequi', 'bancolombia', 'daviplata'
    fecha_pago = db.Column(db.DateTime, default=obtener_hora_bogota, nullable=False)
    registrado_por_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    notas = db.Column(db.Text, nullable=True)

    asesor = db.relationship('Asesor', backref=db.backref('pagos_comisiones', lazy=True, cascade='all, delete-orphan'))
    registrado_por = db.relationship('User', backref='comisiones_registradas', lazy=True)

    def __init__(self, **kwargs):
        super(CommissionPayment, self).__init__(**kwargs)


class AuditLog(db.Model):
    """Bitácora y registro de decisiones administrativas de alto impacto y custodia."""
    __tablename__ = 'audit_logs'

    id = db.Column(db.Integer, primary_key=True)
    action = db.Column(db.String(100), nullable=False, index=True) # ej. 'APROBACION_PRECIO_MINIMO', 'CANCELACION_VENTA', 'REAPERTURA_TURNO', 'AUTORIZACION_CAMBIO'
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, index=True)
    target_id = db.Column(db.Integer, nullable=True) # ID del registro afectado (Venta, Turno, Garantía, etc.)
    target_type = db.Column(db.String(50), nullable=True) # 'SALE', 'CASH_SHIFT', 'DISCOUNT_APPROVAL', 'WARRANTY', 'TRANSFER', 'VALE'
    timestamp = db.Column(db.DateTime, default=obtener_hora_bogota, nullable=False, index=True)
    motivo = db.Column(db.Text, nullable=False) # Justificación obligatoria
    detalles = db.Column(db.Text, nullable=True) # Contexto o datos adicionales en JSON / texto

    user = db.relationship('User', foreign_keys=[user_id], backref=db.backref('auditorias_realizadas', lazy='dynamic'))

    def __init__(self, **kwargs):
        super(AuditLog, self).__init__(**kwargs)

    @classmethod
    def registrar(cls, action, user_id, motivo, target_id=None, target_type=None, detalles=None):
        """Helper para registrar rápidamente un evento de auditoría administrativa."""
        log = cls(
            action=action,
            user_id=user_id,
            target_id=target_id,
            target_type=target_type,
            motivo=motivo,
            detalles=detalles,
            timestamp=obtener_hora_bogota()
        )
        db.session.add(log)
        return log


class Vale(db.Model):
    """Modelo para gestionar solicitudes de vales de asesores y su trazabilidad de aprobación/rechazo."""
    __tablename__ = 'vales'

    id = db.Column(db.Integer, primary_key=True)
    asesor_id = db.Column(db.Integer, db.ForeignKey('asesores.id'), nullable=False, index=True)
    solicitado_por_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, index=True)
    branch_id = db.Column(db.Integer, db.ForeignKey('branches.id'), nullable=True, index=True)
    monto = db.Column(db.Numeric(14, 2), nullable=False)
    concepto = db.Column(db.Text, nullable=True)
    estado = db.Column(db.String(20), nullable=False, default='PENDIENTE', index=True)  # 'PENDIENTE', 'APROBADO', 'RECHAZADO'
    resuelto_por_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    observacion_resolucion = db.Column(db.Text, nullable=True)
    fecha_solicitud = db.Column(db.DateTime, default=obtener_hora_bogota, nullable=False, index=True)
    fecha_resolucion = db.Column(db.DateTime, nullable=True)

    asesor = db.relationship('Asesor', backref=db.backref('vales', lazy=True, cascade='all, delete-orphan'))
    solicitado_por = db.relationship('User', foreign_keys=[solicitado_por_id], backref=db.backref('vales_solicitados', lazy=True))
    resuelto_por = db.relationship('User', foreign_keys=[resuelto_por_id], backref=db.backref('vales_resueltos', lazy=True))
    branch = db.relationship('Branch', backref=db.backref('vales', lazy=True))

    def __init__(self, **kwargs):
        super(Vale, self).__init__(**kwargs)

class Technician(db.Model):
    """Modelo de Tecnicos / Talleres encargados de reparaciones y soporte tecnico."""
    __tablename__ = 'technicians'

    id = db.Column(db.Integer, primary_key=True)
    nombre = db.Column(db.String(120), nullable=False)
    telefono = db.Column(db.String(50), nullable=True)
    especialidad = db.Column(db.String(150), nullable=True)
    direccion_taller = db.Column(db.String(200), nullable=True)
    activo = db.Column(db.Boolean, default=True, nullable=False)
    created_at = db.Column(db.DateTime, default=obtener_hora_bogota)

    servicios = db.relationship('TechnicalService', backref='technician', lazy=True)

    def __init__(self, **kwargs):
        super(Technician, self).__init__(**kwargs)


class TechnicalService(db.Model):
    """Ordenes de soporte tecnico / reparacion para celulares de Inventario o Garantias."""
    __tablename__ = 'technical_services'

    id = db.Column(db.Integer, primary_key=True)
    origen = db.Column(db.String(20), nullable=False, default='INVENTARIO', index=True) # 'INVENTARIO' o 'GARANTIA'
    
    product_id = db.Column(db.Integer, db.ForeignKey('products.id'), nullable=True, index=True)
    warranty_id = db.Column(db.Integer, db.ForeignKey('warranties.id'), nullable=True, index=True)
    branch_id = db.Column(db.Integer, db.ForeignKey('branches.id'), nullable=True, index=True)
    technician_id = db.Column(db.Integer, db.ForeignKey('technicians.id'), nullable=True, index=True)
    created_by_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    resolved_by_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)

    marca = db.Column(db.String(100), nullable=True)
    modelo = db.Column(db.String(150), nullable=True)
    imei = db.Column(db.String(50), nullable=True, index=True)
    color = db.Column(db.String(50), nullable=True)

    motivo_falla = db.Column(db.Text, nullable=False)
    tipo_arreglo = db.Column(db.String(100), nullable=False, default='General', index=True)
    estado = db.Column(db.String(30), nullable=False, default='EN_REVISION', index=True) # EN_REVISION, EN_REPARACION, REPARADO, NO_REPARABLE, ENTREGADO
    
    costo_reparacion = db.Column(db.Numeric(12, 2), nullable=True, default=0.0)
    diagnostico_tecnico = db.Column(db.Text, nullable=True)
    solucion_aplicada = db.Column(db.Text, nullable=True)

    fecha_ingreso = db.Column(db.DateTime, default=obtener_hora_bogota, nullable=False, index=True)
    fecha_estimada = db.Column(db.Date, nullable=True)
    fecha_salida = db.Column(db.DateTime, nullable=True)

    producto = db.relationship('Product', backref=db.backref('servicios_tecnicos', lazy=True))
    garantia = db.relationship('Warranty', backref=db.backref('servicios_tecnicos', lazy=True))
    branch = db.relationship('Branch', backref=db.backref('servicios_tecnicos', lazy=True))
    created_by = db.relationship('User', foreign_keys=[created_by_id], backref=db.backref('servicios_creados', lazy=True))
    resolved_by = db.relationship('User', foreign_keys=[resolved_by_id], backref=db.backref('servicios_resueltos', lazy=True))

    def __init__(self, **kwargs):
        super(TechnicalService, self).__init__(**kwargs)


class ExchangePartner(db.Model):
    """Aliados comerciales, empresas o personas con las que se realizan intercambios/cambios de mercancía."""
    __tablename__ = 'exchange_partners'

    id = db.Column(db.Integer, primary_key=True)
    nombre = db.Column(db.String(150), nullable=False)
    contacto = db.Column(db.String(50), nullable=True) # Teléfono / WhatsApp
    documento_o_nit = db.Column(db.String(50), nullable=True)
    direccion = db.Column(db.String(200), nullable=True)
    activo = db.Column(db.Boolean, default=True, nullable=False)
    created_at = db.Column(db.DateTime, default=obtener_hora_bogota)

    cambios = db.relationship('DeviceExchange', backref='partner', lazy=True)

    def __init__(self, **kwargs):
        super(ExchangePartner, self).__init__(**kwargs)


class DeviceExchange(db.Model):
    """Registro de intercambios de celulares con terceros (salida de un equipo a cambio de otro)."""
    __tablename__ = 'device_exchanges'

    id = db.Column(db.Integer, primary_key=True)
    partner_id = db.Column(db.Integer, db.ForeignKey('exchange_partners.id'), nullable=False, index=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, index=True)
    resolved_by_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    branch_id = db.Column(db.Integer, db.ForeignKey('branches.id'), nullable=True, index=True)

    # Equipo que sale del inventario
    product_salida_id = db.Column(db.Integer, db.ForeignKey('products.id'), nullable=False, index=True)
    imei_salida = db.Column(db.String(50), nullable=True, index=True)
    modelo_salida = db.Column(db.String(150), nullable=True)
    costo_salida = db.Column(db.Numeric(12, 2), nullable=True, default=0.0)

    # Equipo que se recibe a cambio (cuando se completa)
    product_entrada_id = db.Column(db.Integer, db.ForeignKey('products.id'), nullable=True, index=True)
    marca_entrada = db.Column(db.String(100), nullable=True)
    modelo_entrada = db.Column(db.String(150), nullable=True)
    color_entrada = db.Column(db.String(50), nullable=True)
    memoria_entrada = db.Column(db.String(50), nullable=True)
    imei1_entrada = db.Column(db.String(50), nullable=True, index=True)
    imei2_entrada = db.Column(db.String(50), nullable=True)
    costo_entrada = db.Column(db.Numeric(12, 2), nullable=True, default=0.0)
    precio_minimo_entrada = db.Column(db.Numeric(12, 2), nullable=True, default=0.0)
    precio_sugerido_entrada = db.Column(db.Numeric(12, 2), nullable=True, default=0.0)

    # Estado y Trazabilidad: 'PENDIENTE', 'COMPLETADO', 'DEVUELTO'
    estado = db.Column(db.String(20), nullable=False, default='PENDIENTE', index=True)
    motivo_salida = db.Column(db.Text, nullable=True)
    observacion_resolucion = db.Column(db.Text, nullable=True)
    fecha_salida = db.Column(db.DateTime, default=obtener_hora_bogota, nullable=False, index=True)
    fecha_resolucion = db.Column(db.DateTime, nullable=True)

    # Relaciones
    producto_salida = db.relationship('Product', foreign_keys=[product_salida_id], backref=db.backref('cambios_salida', lazy=True))
    producto_entrada = db.relationship('Product', foreign_keys=[product_entrada_id], backref=db.backref('cambios_entrada', lazy=True))
    usuario = db.relationship('User', foreign_keys=[user_id], backref=db.backref('cambios_registrados', lazy=True))
    resolved_by = db.relationship('User', foreign_keys=[resolved_by_id], backref=db.backref('cambios_resueltos', lazy=True))
    branch = db.relationship('Branch', backref=db.backref('cambios_mercancia', lazy=True))

    def __init__(self, **kwargs):
        super(DeviceExchange, self).__init__(**kwargs)

