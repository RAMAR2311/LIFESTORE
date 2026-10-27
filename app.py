import os
from dotenv import load_dotenv
load_dotenv()  # Carga variables desde .env (incluye OPENAI_API_KEY)
from flask import Flask, redirect, url_for, send_from_directory, session
from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate
from flask_login import LoginManager, current_user
from flask_wtf.csrf import CSRFProtect

# Importar la instancia de db y modelos desde models
from models import (
    db, User, Branch, BranchStock, StockTransfer, StockTransferItem,
    Product, ProductVariant, Sale, ArqueoCaja, StockAdjustment, Maneo, Expense, Warranty, Retoma, Vale
)

def create_app():
    app = Flask(__name__)
    
    # Configuración mediante variables de entorno (con fallback inteligente a SQLite si Postgres no está activo)
    app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'dev-key-super-secreta')
    
    raw_db_url = os.environ.get('DATABASE_URL') or os.environ.get('SQLALCHEMY_DATABASE_URI') or 'postgresql://postgres:admin123@localhost:5432/RC'
    
    # Verificar si PostgreSQL está disponible
    if raw_db_url and raw_db_url.startswith('postgresql'):
        try:
            from sqlalchemy import create_engine
            engine = create_engine(raw_db_url, connect_args={'connect_timeout': 2})
            with engine.connect() as conn:
                pass
            app.config['SQLALCHEMY_DATABASE_URI'] = raw_db_url
        except Exception:
            os.makedirs(app.instance_path, exist_ok=True)
            instance_db = os.path.join(app.instance_path, 'crm_inventory.db')
            root_db = os.path.join(app.root_path, 'crm_inventory.db')
            if os.path.exists(root_db):
                app.config['SQLALCHEMY_DATABASE_URI'] = f'sqlite:///{root_db}'
            else:
                app.config['SQLALCHEMY_DATABASE_URI'] = f'sqlite:///{instance_db}'
            print(f"[INFO] PostgreSQL no disponible localmente. Usando SQLite: {app.config['SQLALCHEMY_DATABASE_URI']}")
    else:
        if raw_db_url and 'sqlite' in raw_db_url:
            os.makedirs(app.instance_path, exist_ok=True)
        app.config['SQLALCHEMY_DATABASE_URI'] = raw_db_url
    
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
    app.config['UPLOAD_FOLDER'] = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'static', 'uploads')
    os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

    # Inicializar Extensiones
    db.init_app(app)
    Migrate(app, db)
    CSRFProtect(app)
    
    login_manager = LoginManager()
    login_manager.login_view = 'auth_bp.login'
    login_manager.init_app(app)

    @login_manager.user_loader
    def load_user(user_id):
        return User.query.get(int(user_id))

    # Importar y Registrar Blueprints
    from routes.sales import sales_bp
    from routes.inventory import inventory_bp
    from routes.auth import auth_bp
    from routes.arqueo import arqueo_bp
    from routes.gastos import gastos_bp
    
    app.register_blueprint(sales_bp, url_prefix='/sales')
    app.register_blueprint(inventory_bp, url_prefix='/inventory')
    app.register_blueprint(auth_bp, url_prefix='/auth')
    app.register_blueprint(arqueo_bp, url_prefix='/arqueo')
    app.register_blueprint(gastos_bp, url_prefix='/gastos')
    
    # Registro de Blueprint Admin
    from routes.admin import admin_bp
    app.register_blueprint(admin_bp, url_prefix='/admin')

    # Registro de Blueprint Bodega
    from routes.bodega import bodega_bp
    app.register_blueprint(bodega_bp, url_prefix='/bodega')

    # Registro de Blueprint Celulares
    from routes.celulares import celulares_bp
    app.register_blueprint(celulares_bp, url_prefix='/celulares')

    # Registro de Blueprint Externos
    from routes.externos import externos_bp
    app.register_blueprint(externos_bp, url_prefix='/externos')

    # Registro de Blueprint Retomas
    from routes.retomas import retomas_bp
    app.register_blueprint(retomas_bp, url_prefix='/retomas')

    # Registro de Blueprint Proveedores
    from routes.providers import providers_bp
    app.register_blueprint(providers_bp, url_prefix='/proveedores')

    # Registro de Blueprint Garantías
    from routes.warranties import warranties_bp
    app.register_blueprint(warranties_bp, url_prefix='/garantias')

    # Registro de Blueprint Aprobaciones
    from routes.approvals import approvals_bp
    app.register_blueprint(approvals_bp)

    # Registro de Blueprint ZENIC (Asistente IA)
    from routes.zenic import zenic_bp
    app.register_blueprint(zenic_bp, url_prefix='/zenic')

    # Registro de Blueprint Compras
    from routes.purchases import purchases_bp
    app.register_blueprint(purchases_bp, url_prefix='/compras')

    # Registro de Blueprint Bancos
    from routes.bancos import bancos_bp
    app.register_blueprint(bancos_bp, url_prefix='/bancos')

    # Registro de Blueprint Traslados entre Sucursales
    from routes.transfers import transfers_bp
    app.register_blueprint(transfers_bp, url_prefix='/transfers')

    # Registro de Blueprint Vales de Asesores
    from routes.vales import vales_bp
    app.register_blueprint(vales_bp, url_prefix='/vales')

    # Registro de Blueprint Soporte Técnico
    from routes.support import support_bp
    app.register_blueprint(support_bp, url_prefix='/soporte')


    @app.template_filter('cop')
    def cop_filter(value):
        if value is None:
            return "0"
        try:
            # Formateo a moneda colombiana (separador de miles con coma, como pidió el usuario)
            return "{:,.0f}".format(float(value))
        except (ValueError, TypeError):
            return value

    def get_active_branch_id():
        """Helper global para obtener el branch_id activo según rol y sesión."""
        if not current_user.is_authenticated:
            return None
        if current_user.rol == 'admin':
            return session.get('active_branch_id')
        if current_user.rol in ['vendedor', 'bodega', 'vendedor_bodega']:
            return current_user.branch_id
        return None

    @app.context_processor
    def inject_branch_context():
        """Inyecta el helper de sucursal activa, las sucursales y traslados pendientes en todas las plantillas."""
        active_id = get_active_branch_id()
        active_branch = Branch.query.get(active_id) if active_id else None
        
        # Conteo de traslados pendientes por recibir para la sucursal activa o usuario
        pending_transfers_count = 0
        pending_vales_count = 0
        pending_support_count = 0
        if current_user.is_authenticated:
            from models import StockTransfer, Vale, TechnicalService
            q_pend = StockTransfer.query.filter_by(status='PENDIENTE')
            if current_user.rol != 'admin':
                if current_user.branch_id:
                    q_pend = q_pend.filter(StockTransfer.destination_branch_id == current_user.branch_id)
            elif active_id:
                q_pend = q_pend.filter(StockTransfer.destination_branch_id == active_id)
            pending_transfers_count = q_pend.count()

            q_vales = Vale.query.filter_by(estado='PENDIENTE')
            if current_user.rol != 'admin':
                if current_user.branch_id:
                    q_vales = q_vales.filter(
                        (Vale.branch_id == current_user.branch_id) | (Vale.solicitado_por_id == current_user.id)
                    )
                else:
                    q_vales = q_vales.filter(Vale.solicitado_por_id == current_user.id)
            elif active_id:
                q_vales = q_vales.filter(Vale.branch_id == active_id)
            pending_vales_count = q_vales.count()

            q_sup = TechnicalService.query.filter(TechnicalService.estado.in_(['EN_REVISION', 'EN_REPARACION']))
            if current_user.rol != 'admin':
                if current_user.branch_id:
                    q_sup = q_sup.filter(TechnicalService.branch_id == current_user.branch_id)
            elif active_id:
                q_sup = q_sup.filter(TechnicalService.branch_id == active_id)
            pending_support_count = q_sup.count()

        return {
            'get_active_branch_id': get_active_branch_id,
            'active_branch_id': active_id,
            'active_branch': active_branch,
            'all_branches': Branch.query.filter_by(activa=True).all() if current_user.is_authenticated else [],
            'pending_transfers_count': pending_transfers_count,
            'pending_vales_count': pending_vales_count,
            'pending_support_count': pending_support_count
        }

    @app.route('/')
    def index():
        # Redirección de sesión y rol de usuario
        if not current_user.is_authenticated:
            return redirect(url_for('auth_bp.login'))
            
        if current_user.rol == 'admin':
            return redirect(url_for('admin_bp.dashboard'))
            
        if current_user.rol == 'bodega':
            return redirect(url_for('inventory_bp.index'))

        # Por defecto, Vendedores van directo a Caja Visual
        return redirect(url_for('sales_bp.caja_visual'))

    @app.route('/sw.js')
    def service_worker():
        response = send_from_directory(os.path.join(app.root_path, 'static'), 'sw.js', mimetype='application/javascript')
        response.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
        response.headers['Service-Worker-Allowed'] = '/'
        return response

    @app.route('/manifest.json')
    def manifest():
        return send_from_directory(os.path.join(app.root_path, 'static'), 'manifest.json', mimetype='application/manifest+json')

    # Auto-parcheador de esquema de base de datos para prevenir errores 500 en producción por columnas faltantes
    with app.app_context():
        try:
            db.create_all()
        except Exception:
            db.session.rollback()
        queries = [
            "ALTER TABLE provider_invoices ADD COLUMN sale_id INTEGER REFERENCES sales(id) ON DELETE SET NULL;",
            "ALTER TABLE sales ADD COLUMN provider_id INTEGER REFERENCES providers(id) ON DELETE SET NULL;",
            "ALTER TABLE sales ADD COLUMN asesor_id INTEGER REFERENCES asesores(id) ON DELETE SET NULL;",
            "ALTER TABLE retomas ADD COLUMN arreglos NUMERIC(10, 2) DEFAULT 0.0;",
            "ALTER TABLE retomas ADD COLUMN ok_contabilidad BOOLEAN DEFAULT FALSE;",
            "ALTER TABLE retomas ADD COLUMN ok_venta BOOLEAN DEFAULT FALSE;",
            "ALTER TABLE sale_details ADD COLUMN ok_contabilidad BOOLEAN DEFAULT FALSE;",
            "ALTER TABLE sale_details ADD COLUMN ok_inventario BOOLEAN DEFAULT FALSE;",
            "ALTER TABLE arqueo_caja ADD COLUMN efectivo_fisico NUMERIC(14, 2) DEFAULT 0.0;",
            "ALTER TABLE arqueo_caja ADD COLUMN diferencia NUMERIC(14, 2) DEFAULT 0.0;",
            "ALTER TABLE arqueo_caja ADD COLUMN observacion_diferencia TEXT;",
            "ALTER TABLE users ADD COLUMN branch_id INTEGER REFERENCES branches(id) ON DELETE SET NULL;",
            "ALTER TABLE sales ADD COLUMN branch_id INTEGER REFERENCES branches(id) ON DELETE SET NULL;",
            "ALTER TABLE arqueo_caja ADD COLUMN branch_id INTEGER REFERENCES branches(id) ON DELETE SET NULL;",
            "ALTER TABLE stock_adjustments ADD COLUMN branch_id INTEGER REFERENCES branches(id) ON DELETE SET NULL;",
            "ALTER TABLE maneos ADD COLUMN branch_id INTEGER REFERENCES branches(id) ON DELETE SET NULL;",
            "ALTER TABLE expenses ADD COLUMN branch_id INTEGER REFERENCES branches(id) ON DELETE SET NULL;",
            "ALTER TABLE warranties ADD COLUMN branch_id INTEGER REFERENCES branches(id) ON DELETE SET NULL;",
            "ALTER TABLE retomas ADD COLUMN branch_id INTEGER REFERENCES branches(id) ON DELETE SET NULL;"
        ]
        for q in queries:
            try:
                db.session.execute(db.text(q))
                db.session.commit()
            except Exception:
                db.session.rollback()

    @app.cli.command('init-branches')
    def init_branches_command():
        """Inicializa sucursales base (Principal y Bodega Central), migra registros existentes y puebla BranchStock."""
        print("[INIT-BRANCHES] Iniciando proceso de migración de sucursales...")
        
        # 1. Asegurar existencia de tablas
        db.create_all()

        # 2. Crear o recuperar sucursales por defecto
        principal = Branch.query.filter_by(codigo='PRIN').first()
        if not principal:
            principal = Branch(
                nombre='Principal',
                codigo='PRIN',
                tipo='tienda',
                direccion='Sede Principal',
                activa=True
            )
            db.session.add(principal)
            db.session.flush()
            print(f"[INIT-BRANCHES] Creada sucursal 'Principal' (ID={principal.id}, Código=PRIN).")
        else:
            print(f"[INIT-BRANCHES] Sucursal 'Principal' ya existe (ID={principal.id}).")

        bodega = Branch.query.filter_by(codigo='BOD').first()
        if not bodega:
            bodega = Branch(
                nombre='Bodega Central',
                codigo='BOD',
                tipo='bodega',
                direccion='Bodega Central',
                activa=True
            )
            db.session.add(bodega)
            db.session.flush()
            print(f"[INIT-BRANCHES] Creada sucursal 'Bodega Central' (ID={bodega.id}, Código=BOD).")
        else:
            print(f"[INIT-BRANCHES] Sucursal 'Bodega Central' ya existe (ID={bodega.id}).")

        # 3. Asignar branch_id a Users existentes
        users_updated = 0
        for u in User.query.filter(User.branch_id.is_(None)).all():
            if u.rol == 'admin':
                # Para admin puede ser NULL o Principal por conveniencia
                u.branch_id = None
            elif u.rol in ['bodega', 'vendedor_bodega']:
                u.branch_id = bodega.id
            else:
                u.branch_id = principal.id
            users_updated += 1
        print(f"[INIT-BRANCHES] Usuarios actualizados con branch_id: {users_updated}")

        # 4. Asignar branch_id a registros históricos existentes con branch_id == None
        def migrate_records(model_class, model_name):
            count = 0
            if hasattr(model_class, 'branch_id'):
                records = model_class.query.filter(model_class.branch_id.is_(None)).all()
                for r in records:
                    r.branch_id = principal.id
                    count += 1
            print(f"[INIT-BRANCHES] Registros actualizados en {model_name}: {count}")
            return count

        migrate_records(Sale, 'Sale')
        migrate_records(ArqueoCaja, 'ArqueoCaja')
        migrate_records(StockAdjustment, 'StockAdjustment')
        migrate_records(Maneo, 'Maneo')
        migrate_records(Expense, 'Expense')
        migrate_records(Warranty, 'Warranty')
        migrate_records(Retoma, 'Retoma')

        # 5. Poblar BranchStock a partir de Product y ProductVariant
        stocks_created = 0
        stocks_updated = 0

        # Primero productos sin variantes
        productos = Product.query.all()
        for p in productos:
            target_branch = bodega if p.tipo_inventario == 'bodega' else principal
            
            if not p.variantes:
                # Producto simple
                bs = BranchStock.query.filter_by(
                    branch_id=target_branch.id,
                    product_id=p.id,
                    variant_id=None
                ).first()
                if not bs:
                    bs = BranchStock(
                        branch_id=target_branch.id,
                        product_id=p.id,
                        variant_id=None,
                        cantidad=p.cantidad_stock or 0
                    )
                    db.session.add(bs)
                    stocks_created += 1
                else:
                    if bs.cantidad == 0 and (p.cantidad_stock or 0) > 0:
                        bs.cantidad = p.cantidad_stock
                        stocks_updated += 1
            else:
                # Producto con variantes
                for v in p.variantes:
                    bs = BranchStock.query.filter_by(
                        branch_id=target_branch.id,
                        product_id=p.id,
                        variant_id=v.id
                    ).first()
                    if not bs:
                        bs = BranchStock(
                            branch_id=target_branch.id,
                            product_id=p.id,
                            variant_id=v.id,
                            cantidad=v.cantidad_stock or 0
                        )
                        db.session.add(bs)
                        stocks_created += 1
                    else:
                        if bs.cantidad == 0 and (v.cantidad_stock or 0) > 0:
                            bs.cantidad = v.cantidad_stock
                            stocks_updated += 1

        db.session.commit()
        print(f"[INIT-BRANCHES] BranchStock completado: {stocks_created} creados, {stocks_updated} actualizados.")
        print("[INIT-BRANCHES] ¡Migración de sucursales completada exitosamente!")

    @app.cli.command('test-multisucursal')
    def test_multisucursal_command():
        """Genera datos de prueba limpios y ejecuta el flujo multisucursal de extremo a extremo."""
        from test_multisucursal import run_multisucursal_test
        run_multisucursal_test()

    @app.cli.command('seed-demo-completa')
    def seed_demo_completa_command():
        """Genera escenario integral para revisión visual de alertas de horario, comisiones y abono a proveedor."""
        from seed_demo_completa import run_seed_demo_completa
        run_seed_demo_completa()

    return app

if __name__ == '__main__':
    app = create_app()
    
    # ---------------- LÓGICA DE INICIALIZACIÓN ----------------
    with app.app_context():
        from models import db, User
        from werkzeug.security import generate_password_hash
        
        # Aseguramos que las tablas existan sin romper migraciones
        db.create_all()
        
        # Crear la carpeta de imágenes si no existe
        os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
        
        # Verificamos e instanciamos al Administrador si no existe
        if not User.query.filter_by(email='admin@lifestore.com').first():
            master_admin = User(
                nombre='Administrador LifeStore',
                email='admin@lifestore.com',
                password_hash=generate_password_hash('Admin123'),
                rol='admin'
            )
            db.session.add(master_admin)
            db.session.commit()
            print("[INFO] Usuario maestro 'admin@lifestore.com' verificado/creado con éxito.")
            
    port = int(os.environ.get('PORT', 5001))
    print(f"\n[INFO] Servidor iniciado correctamente en puerto {port}.")
    print(f"[INFO] Abre tu navegador en: http://localhost:{port} o http://127.0.0.1:{port}\n")
    app.run(host='0.0.0.0', port=port, debug=True)
