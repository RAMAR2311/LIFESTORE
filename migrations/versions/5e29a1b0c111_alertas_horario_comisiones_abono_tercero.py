"""alertas_horario_comisiones_abono_tercero

Revision ID: 5e29a1b0c111
Revises: 31b4d28a5042
Create Date: 2026-10-23 13:25:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '5e29a1b0c111'
down_revision = '31b4d28a5042'
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_tables = inspector.get_table_names()

    # 1. Agregar columnas a cash_shifts si no existen
    if 'cash_shifts' in existing_tables:
        cols_cash_shifts = [c['name'] for c in inspector.get_columns('cash_shifts')]
        with op.batch_alter_table('cash_shifts', schema=None) as batch_op:
            if 'apertura_tardia' not in cols_cash_shifts:
                batch_op.add_column(sa.Column('apertura_tardia', sa.Boolean(), nullable=False, server_default='0'))
            if 'minutos_retraso_apertura' not in cols_cash_shifts:
                batch_op.add_column(sa.Column('minutos_retraso_apertura', sa.Integer(), nullable=False, server_default='0'))
            if 'cierre_tardio' not in cols_cash_shifts:
                batch_op.add_column(sa.Column('cierre_tardio', sa.Boolean(), nullable=False, server_default='0'))
            if 'minutos_retraso_cierre' not in cols_cash_shifts:
                batch_op.add_column(sa.Column('minutos_retraso_cierre', sa.Integer(), nullable=False, server_default='0'))

    # 2. Agregar columnas a sale_payments si no existen
    if 'sale_payments' in existing_tables:
        cols_sale_payments = [c['name'] for c in inspector.get_columns('sale_payments')]
        with op.batch_alter_table('sale_payments', schema=None) as batch_op:
            if 'provider_id' not in cols_sale_payments:
                batch_op.add_column(sa.Column('provider_id', sa.Integer(), nullable=True))
                batch_op.create_foreign_key('fk_sale_payments_provider_id', 'providers', ['provider_id'], ['id'])
            if 'comprobante' not in cols_sale_payments:
                batch_op.add_column(sa.Column('comprobante', sa.String(length=255), nullable=True))

    # 3. Crear tabla commission_payments si no existe
    if 'commission_payments' not in existing_tables:
        op.create_table('commission_payments',
            sa.Column('id', sa.Integer(), nullable=False),
            sa.Column('asesor_id', sa.Integer(), nullable=False),
            sa.Column('monto', sa.Numeric(precision=14, scale=2), nullable=False),
            sa.Column('tipo_pago', sa.String(length=50), nullable=False),
            sa.Column('metodo_pago', sa.String(length=50), nullable=False, server_default='efectivo'),
            sa.Column('fecha_pago', sa.DateTime(), nullable=False),
            sa.Column('registrado_por_id', sa.Integer(), nullable=False),
            sa.Column('notas', sa.Text(), nullable=True),
            sa.ForeignKeyConstraint(['asesor_id'], ['asesores.id'], name='fk_commission_payments_asesor_id'),
            sa.ForeignKeyConstraint(['registrado_por_id'], ['users.id'], name='fk_commission_payments_user_id'),
            sa.PrimaryKeyConstraint('id')
        )
        with op.batch_alter_table('commission_payments', schema=None) as batch_op:
            batch_op.create_index('ix_commission_payments_asesor_id', ['asesor_id'], unique=False)


def downgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_tables = inspector.get_table_names()

    if 'commission_payments' in existing_tables:
        op.drop_table('commission_payments')

    if 'sale_payments' in existing_tables:
        cols_sale_payments = [c['name'] for c in inspector.get_columns('sale_payments')]
        with op.batch_alter_table('sale_payments', schema=None) as batch_op:
            if 'comprobante' in cols_sale_payments:
                batch_op.drop_column('comprobante')
            if 'provider_id' in cols_sale_payments:
                batch_op.drop_constraint('fk_sale_payments_provider_id', type_='foreignkey')
                batch_op.drop_column('provider_id')

    if 'cash_shifts' in existing_tables:
        cols_cash_shifts = [c['name'] for c in inspector.get_columns('cash_shifts')]
        with op.batch_alter_table('cash_shifts', schema=None) as batch_op:
            if 'minutos_retraso_cierre' in cols_cash_shifts:
                batch_op.drop_column('minutos_retraso_cierre')
            if 'cierre_tardio' in cols_cash_shifts:
                batch_op.drop_column('cierre_tardio')
            if 'minutos_retraso_apertura' in cols_cash_shifts:
                batch_op.drop_column('minutos_retraso_apertura')
            if 'apertura_tardia' in cols_cash_shifts:
                batch_op.drop_column('apertura_tardia')
