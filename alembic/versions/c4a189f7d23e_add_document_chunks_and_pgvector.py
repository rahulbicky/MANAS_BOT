"""add_document_chunks_and_pgvector

Revision ID: c4a189f7d23e
Revises: ef7a990203df
Create Date: 2026-11-21 15:20:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from pgvector.sqlalchemy import Vector


# revision identifiers, used by Alembic.
revision: str = 'c4a189f7d23e'
down_revision: Union[str, Sequence[str], None] = 'ef7a990203df'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Enable vector extension, create document_chunks table, and add HNSW + relational indexes."""
    bind = op.get_bind()
    is_postgres = bind.dialect.name == "postgresql"

    # 1. Enable pgvector extension on PostgreSQL
    if is_postgres:
        op.execute("CREATE EXTENSION IF NOT EXISTS vector;")

    # 2. Create document_chunks table
    op.create_table(
        'document_chunks',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('document_id', sa.String(), nullable=False),
        sa.Column('tenant_id', sa.String(), nullable=False),
        sa.Column('chunk_index', sa.Integer(), nullable=False),
        sa.Column('chunk_text', sa.Text(), nullable=False),
        sa.Column('token_count', sa.Integer(), nullable=True, server_default='0'),
        sa.Column('embedding', Vector(384), nullable=False),
        sa.Column('is_active', sa.Boolean(), nullable=True, server_default=sa.true()),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['document_id'], ['knowledge_documents.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )

    # 3. Create relational composite indexes for tenant and document lookups
    op.create_index(
        'ix_document_chunks_tenant_id_is_active',
        'document_chunks',
        ['tenant_id', 'is_active'],
        unique=False,
    )
    op.create_index(
        'ix_document_chunks_document_id',
        'document_chunks',
        ['document_id'],
        unique=False,
    )

    # 4. Create HNSW vector index using cosine distance
    if is_postgres:
        op.create_index(
            'ix_document_chunks_embedding_hnsw',
            'document_chunks',
            ['embedding'],
            postgresql_using='hnsw',
            postgresql_with={'m': 16, 'ef_construction': 64},
            postgresql_ops={'embedding': 'vector_cosine_ops'},
        )


def downgrade() -> None:
    """Drop document_chunks table and indexes."""
    bind = op.get_bind()
    is_postgres = bind.dialect.name == "postgresql"

    if is_postgres:
        op.drop_index('ix_document_chunks_embedding_hnsw', table_name='document_chunks')
    op.drop_index('ix_document_chunks_document_id', table_name='document_chunks')
    op.drop_index('ix_document_chunks_tenant_id_is_active', table_name='document_chunks')
    op.drop_table('document_chunks')
