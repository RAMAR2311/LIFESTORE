"""trazabilidad_custodia_auditoria

Revision ID: 8f2b3c4d5e6f
Revises: 5e29a1b0c111
Create Date: 2026-10-23 15:45:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '8f2b3c4d5e6f'
down_revision = '5e29a1b0c111'
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_tables = inspector.get_table_names()

    # 1. Columnas de custodia en stock_transfers
    if 'stock_transfers' in existing_tables:
        cols_transfers = [c['name'] for c in inspector.get_columns('stock_transfers')]
        with op.batch_alter_table('stock_transfers', schema=None) as batch_op:
            if 'enviado_por_id' not in cols_transfers:
                batch_op.add_column(sa.Column('enviado_por_id', sa.Integer(), nullable=True))
                batch_op.create_foreign_key('fk_stock_transfers_enviado_por_id', 'users', ['enviado_por_id'], ['id'])
            if 'recibido_por_id' not in cols_transfers:
                batch_op.add_column(sa.Column('recibido_por_id', sa.Integer(), nullable=True))
                batch_op.create_foreign_key('fk_stock_transfers_recibido_por_id', 'users', ['recibido_por_id'], ['id'])
            if 'observaciones_entrega' not in cols_transfers:
                batch_op.add_column(sa.Column('observaciones_entrega', sa.Text(), nullable=True))
            if 'observaciones_recepcion' not in cols_transfers:
                batch_op.add_column(sa.Column('observaciones_recepcion', sa.Text(), nullable=True))

    # 2. Columnas en arqueo_caja
    if 'arqueo_caja' in existing_tables:
        cols_arqueo = [c['name'] for c in inspector.get_columns('arqueo_caja')]
        with op.batch_alter_table('arqueo_caja', schema=None) as batch_op:
            if 'closed_by_id' not in cols_arqueo:
                batch_op.add_column(sa.Column('closed_by_id', sa.Integer(), nullable=True))
                batch_op.create_foreign_key('fk_arqueo_caja_closed_by_id', 'users', ['closed_by_id'], ['id'])

    # 3. Columnas de trazabilidad en warranties
    if 'warranties' in existing_tables:
        cols_warranties = [c['name'] for c in inspector.get_columns('warranties')]
        with op.batch_alter_table('warranties', schema=None) as batch_op:
            if 'recibido_por_id' not in cols_warranties:
                batch_op.add_column(sa.Column('recibido_por_id', sa.Integer(), nullable=True))
                batch_op.create_foreign_key('fk_warranties_recibido_por_id', 'users', ['recibido_por_id'], ['id'])
            if 'estado_estetico' not in cols_warranties:
                batch_op.add_column(sa.Column('estado_estetico', sa.String(length=100), nullable=True))
            if 'detalles_esteticos' not in cols_warranties:
                batch_op.add_column(sa.Column('detalles_esteticos', sa.Text(), nullable=True))
            if 'porcentaje_bateria' not in cols_warranties:
                batch_op.add_column(sa.Column('porcentaje_bateria', sa.String(length=20), nullable=True))
            if 'motivo_reportado' not in cols_warranties:
                batch_op.add_column(sa.Column('motivo_reportado', sa.Text(), nullable=True))
            if 'entregado_por_id' not in cols_warranties:
                batch_op.add_column(sa.Column('entregado_por_id', sa.Integer(), nullable=True))
                batch_op.create_foreign_key('fk_warranties_entregado_por_id', 'users', ['entregado_por_id'], ['id'])
            if 'fecha_entrega' not in cols_warranties:
                batch_op.add_column(sa.Column('fecha_entrega', sa.DateTime(), nullable=True))
            if 'firma_o_soporte_entrega' not in cols_warranties:
                batch_op.add_column(sa.Column('firma_o_soporte_entrega', sa.String(length=255), nullable=True))

    # 4. Crear tabla audit_logs si no existe
    if 'audit_logs' not in existing_tables:
        op.create_table('audit_logs',
            sa.Column('id', sa.Integer(), nullable=False),
            sa.Column('action', sa.String(length=100), nullable=False),
            sa.Column('user_id', sa.Integer(), nullable=False),
            sa.Column('target_id', sa.Integer(), nullable=True),
            sa.Column('target_type', sa.String(length=50), nullable=True),
            sa.Column('timestamp', sa.DateTime(), nullable=False),
            sa.Column('motivo', sa.Text(), nullable=True),
            sa.Column('detalles', sa.Text(), nullable=True),
            sa.ForeignKeyConstraint(['user_id'], ['users.id'], name='fk_audit_logs_user_id'),
            sa.PrimaryKeyConstraint('id')
        )
        with op.batch_alter_table('audit_logs', schema=None) as batch_op:
            batch_op.create_index('ix_audit_logs_action', ['action'], unique=False)
            batch_op.create_index('ix_audit_logs_user_id', ['user_id'], unique=False)
            batch_op.create_index('ix_audit_logs_timestamp', ['timestamp'], unique=False)


def downgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_tables = inspector.get_table_names()

    if 'audit_logs' in existing_tables:
        op.drop_table('audit_logs')

    if 'warranties' in existing_tables:
        cols_warranties = [c['name'] for c in inspector.get_columns('warranties')]
        with op.batch_alter_table('warranties', schema=None) as batch_op:
            for col in ['firma_o_soporte_entrega', 'fecha_entrega', 'entregado_por_id', 'motivo_reportado', 'porcentaje_bateria', 'detalles_esteticos', 'estado_estetico', 'recibido_por_id']:
                if col in cols_warranties:
                    batch_op.drop_column(col)

    if 'arqueo_caja' in existing_tables:
        cols_arqueo = [c['name'] for c in inspector.get_columns('arqueo_caja')]
        with op.batch_alter_table('arqueo_caja', schema=None) as batch_op:
            if 'closed_by_id' in cols_arqueo:
                batch_op.drop_column('closed_by_id')

    if 'stock_transfers' in existing_tables:
        cols_transfers = [c['name'] for c in inspector.get_columns('stock_transfers')]
        with op.batch_alter_table('stock_transfers', schema=None) as batch_op:
            for col in ['observaciones_recepcion', 'observaciones_entrega', 'recibido_por_id', 'enviado_por_id']:
                if col in cols_transfers:
                    batch_op.drop_column(col)
