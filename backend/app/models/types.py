"""PostgreSQL-специфичные типы, которых нет в SQLAlchemy из коробки."""

from typing import Any

from sqlalchemy.types import UserDefinedType


class Ltree(UserDefinedType):
    """Материализованный путь группы ('root.b.c.d'), data-model §2."""

    def get_col_spec(self, **kw: Any) -> str:
        return "ltree"
