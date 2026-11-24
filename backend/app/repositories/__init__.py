"""
backend/app/repositories/__init__.py
------------------------------------
Repository layer for database operations across ManasBot.
"""
from .chat_repo import ChatRepository
from .tenant_repo import TenantRepository

__all__ = ["ChatRepository", "TenantRepository"]
