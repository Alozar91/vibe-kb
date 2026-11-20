"""Импорт всех моделей для Alembic autogenerate (app/models/__init__.py).

Каждый новый модуль моделей добавлять сюда — иначе autogenerate не увидит таблицу.
"""

from app.models.base import AuditMixin, Base, PkMixin, SoftDeleteMixin

__all__ = ["AuditMixin", "Base", "PkMixin", "SoftDeleteMixin"]
