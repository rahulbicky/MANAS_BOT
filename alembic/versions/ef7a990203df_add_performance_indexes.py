"""add_performance_indexes

Revision ID: ef7a990203df
Revises: 9e29316857d6
Create Date: 2026-11-21 13:35:09.128487

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'ef7a990203df'
down_revision: Union[str, Sequence[str], None] = '9e29316857d6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema with performance composite indexes."""
    # 1. chat_logs_v2: optimize monthly quota check and timeline queries
    op.create_index(
        'ix_chat_logs_v2_tenant_id_created_at',
        'chat_logs_v2',
        ['tenant_id', 'created_at'],
        unique=False,
    )
    # 2. leads: optimize tenant lead listing and sorting
    op.create_index(
        'ix_leads_tenant_id_created_at',
        'leads',
        ['tenant_id', 'created_at'],
        unique=False,
    )
    # 3. faqs: optimize active FAQ retrieval by tenant
    op.create_index(
        'ix_faqs_tenant_id_is_active',
        'faqs',
        ['tenant_id', 'is_active'],
        unique=False,
    )
    # 4. knowledge_documents: optimize active document search
    op.create_index(
        'ix_knowledge_documents_tenant_id_is_active',
        'knowledge_documents',
        ['tenant_id', 'is_active'],
        unique=False,
    )
    # 5. chat_feedback: optimize session feedback lookup
    op.create_index(
        'ix_chat_feedback_tenant_id_session_id',
        'chat_feedback',
        ['tenant_id', 'session_id'],
        unique=False,
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index('ix_chat_feedback_tenant_id_session_id', table_name='chat_feedback')
    op.drop_index('ix_knowledge_documents_tenant_id_is_active', table_name='knowledge_documents')
    op.drop_index('ix_faqs_tenant_id_is_active', table_name='faqs')
    op.drop_index('ix_leads_tenant_id_created_at', table_name='leads')
    op.drop_index('ix_chat_logs_v2_tenant_id_created_at', table_name='chat_logs_v2')
