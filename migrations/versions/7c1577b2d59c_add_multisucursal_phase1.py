"""add_multisucursal_phase1

Revision ID: 7c1577b2d59c
Revises: 0efadbc94b52
Create Date: 2026-10-22 09:27:20.432879

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '7c1577b2d59c'
down_revision = '0efadbc94b52'
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_tables = inspector.get_table_names()

    # 1. Crear tabla branches si no existe
    if 'branches' not in existing_tables:
        op.create_table('branches',
            sa.Column('id', sa.Integer(), nullable=False),
            sa.Column('nombre', sa.String(length=100), nullable=False),
            sa.Column('codigo', sa.String(length=20), nullable=False),
            sa.Column('tipo', sa.String(length=20), nullable=False, server_default='tienda'),
            sa.Column('direccion', sa.String(length=200), nullable=True),
            sa.Column('telefono', sa.String(length=50), nullable=True),
            sa.Column('activa', sa.Boolean(), nullable=True, server_default=sa.true()),
            sa.Column('created_at', sa.DateTime(), nullable=True),
            sa.PrimaryKeyConstraint('id'),
            sa.UniqueConstraint('codigo'),
            sa.UniqueConstraint('nombre')
        )

    # 2. Crear tabla branch_stocks
    if 'branch_stocks' not in existing_tables:
        op.create_table('branch_stocks',
            sa.Column('id', sa.Integer(), nullable=False),
            sa.Column('branch_id', sa.Integer(), nullable=False),
            sa.Column('product_id', sa.Integer(), nullable=False),
            sa.Column('variant_id', sa.Integer(), nullable=True),
            sa.Column('cantidad', sa.Integer(), nullable=False, server_default='0'),
            sa.Column('updated_at', sa.DateTime(), nullable=True),
            sa.ForeignKeyConstraint(['branch_id'], ['branches.id'], ),
            sa.ForeignKeyConstraint(['product_id'], ['products.id'], ),
            sa.ForeignKeyConstraint(['variant_id'], ['product_variants.id'], ),
            sa.PrimaryKeyConstraint('id'),
            sa.UniqueConstraint('branch_id', 'product_id', 'variant_id', name='uq_branch_product_variant')
        )
        op.create_index(op.f('ix_branch_stocks_branch_id'), 'branch_stocks', ['branch_id'], unique=False)
        op.create_index(op.f('ix_branch_stocks_product_id'), 'branch_stocks', ['product_id'], unique=False)
        op.create_index(op.f('ix_branch_stocks_variant_id'), 'branch_stocks', ['variant_id'], unique=False)

    # 3. Crear tabla stock_transfers
    if 'stock_transfers' not in existing_tables:
        op.create_table('stock_transfers',
            sa.Column('id', sa.Integer(), nullable=False),
            sa.Column('origin_branch_id', sa.Integer(), nullable=False),
            sa.Column('destination_branch_id', sa.Integer(), nullable=False),
            sa.Column('created_by_id', sa.Integer(), nullable=False),
            sa.Column('received_by_id', sa.Integer(), nullable=True),
            sa.Column('status', sa.String(length=20), nullable=False, server_default='PENDIENTE'),
            sa.Column('notas', sa.Text(), nullable=True),
            sa.Column('created_at', sa.DateTime(), nullable=True),
            sa.Column('resolved_at', sa.DateTime(), nullable=True),
            sa.ForeignKeyConstraint(['created_by_id'], ['users.id'], ),
            sa.ForeignKeyConstraint(['destination_branch_id'], ['branches.id'], ),
            sa.ForeignKeyConstraint(['origin_branch_id'], ['branches.id'], ),
            sa.ForeignKeyConstraint(['received_by_id'], ['users.id'], ),
            sa.PrimaryKeyConstraint('id')
        )

    # 4. Crear tabla stock_transfer_items
    if 'stock_transfer_items' not in existing_tables:
        op.create_table('stock_transfer_items',
            sa.Column('id', sa.Integer(), nullable=False),
            sa.Column('transfer_id', sa.Integer(), nullable=False),
            sa.Column('product_id', sa.Integer(), nullable=False),
            sa.Column('variant_id', sa.Integer(), nullable=True),
            sa.Column('cantidad', sa.Integer(), nullable=False),
            sa.ForeignKeyConstraint(['product_id'], ['products.id'], ),
            sa.ForeignKeyConstraint(['transfer_id'], ['stock_transfers.id'], ),
            sa.ForeignKeyConstraint(['variant_id'], ['product_variants.id'], ),
            sa.PrimaryKeyConstraint('id')
        )

    # 5. Agregar columnas e índices branch_id a tablas existentes si no existen
    target_tables = [
        'users', 'sales', 'arqueo_caja', 'stock_adjustments',
        'maneos', 'expenses', 'warranties', 'retomas'
    ]
    for table_name in target_tables:
        if table_name in existing_tables:
            columns = [c['name'] for c in inspector.get_columns(table_name)]
            with op.batch_alter_table(table_name, schema=None) as batch_op:
                if 'branch_id' not in columns:
                    batch_op.add_column(sa.Column('branch_id', sa.Integer(), nullable=True))
                    batch_op.create_foreign_key(f'fk_{table_name}_branch_id', 'branches', ['branch_id'], ['id'])
                try:
                    batch_op.create_index(batch_op.f(f'ix_{table_name}_branch_id'), ['branch_id'], unique=False)
                except Exception:
                    pass


def downgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    with op.batch_alter_table('warranties', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_warranties_branch_id'))

    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_users_branch_id'))

    with op.batch_alter_table('stock_adjustments', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_stock_adjustments_branch_id'))

    with op.batch_alter_table('sales', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_sales_branch_id'))

    with op.batch_alter_table('retomas', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_retomas_branch_id'))

    with op.batch_alter_table('maneos', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_maneos_branch_id'))

    with op.batch_alter_table('expenses', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_expenses_branch_id'))

    with op.batch_alter_table('arqueo_caja', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_arqueo_caja_branch_id'))

    # ### end Alembic commands ###
