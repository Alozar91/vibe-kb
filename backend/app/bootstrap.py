"""Bootstrap стенда (ПРВ-8, deployment.md §5.5): пользователи + корневая группа + первичные роли.

Запускается автоматически при старте api-контейнера (docker-compose.test.yml).
Идемпотентен: повторный запуск ничего не ломает (НФТ-9).
"""

from __future__ import annotations

import logging

from app.common.db import create_db_engine, create_session_factory
from app.models.enums import GroupRole as GroupRoleEnum
from app.models.identity import Group, GroupRole, User
from app.models.pipeline import Setting

log = logging.getLogger("kb.bootstrap")


def _get_or_create_user(session, sub: str, username: str, display: str, email: str) -> User:
    user = session.query(User).filter_by(keycloak_sub=sub).first()
    if user is None:
        user = User(
            keycloak_sub=sub, username=username, display_name=display, email=email, is_local=True
        )
        session.add(user)
        session.flush()
    return user


def _get_or_create_group(session, name: str, parent_id=None) -> Group:
    import uuid as _uuid

    group = session.query(Group).filter(Group.name == name, Group.is_deleted.is_(False)).first()
    if group is None:
        group = Group(id=_uuid.uuid4(), name=name, parent_id=parent_id)
        if parent_id is None:
            group.path = f"g{group.id.hex[:8]}"
        else:
            parent = session.get(Group, parent_id)
            group.path = f"{parent.path}.g{group.id.hex[:8]}"
        session.add(group)
        session.flush()
        from app.domain.search.indexing import index_group

        index_group(session, group.id)  # ПСК-1: tsv корневой группы
    return group


def main() -> None:
    engine = create_db_engine()
    session = create_session_factory(engine)()
    try:
        # 1. Системные настройки (НФТ-5: не секреты)
        defaults = {
            "upload.max_size_mb": {"value": 50},
            "default_chunker": {"name": "recursive", "params": {"size": 1500, "overlap": 200}},
            "fts.languages": {"languages": ["russian", "english"]},
        }
        for key, value in defaults.items():
            if session.get(Setting, key) is None:
                session.add(Setting(key=key, value=value))

        # 2. Пользователи стенда (АУТ-3: локальные; sub согласован с JWT Keycloak)
        alice = _get_or_create_user(session, "alice", "alice", "Алиса Системова", "alice@merch-vibe.ru")
        boris = _get_or_create_user(session, "boris", "boris", "Борис Редакторов", "boris@merch-vibe.ru")
        vera = _get_or_create_user(session, "vera", "vera", "Вера Проверяева", "vera@merch-vibe.ru")
        grigorij = _get_or_create_user(session, "grigorij", "grigorij", "Григорий Читателев", "grigorij@merch-vibe.ru")

        # 3. Корневая группа + первичные роли (ПРВ-8: выдаёт системный админ)
        root = _get_or_create_group(session, "Корпоративная база знаний")
        roles = {
            alice: GroupRoleEnum.OWNER,
            boris: GroupRoleEnum.EDITOR,
            vera: GroupRoleEnum.REVIEWER,
            grigorij: GroupRoleEnum.READER,
        }
        for user, role in roles.items():
            existing = session.query(GroupRole).filter_by(user_id=user.id, group_id=root.id).first()
            if existing is None:
                session.add(GroupRole(user_id=user.id, group_id=root.id, role=role))

        # 4. Справочник событий уведомлений (УВЕД-3)
        from app.domain.notifications.service import seed_events

        seed_events(session)

        # 5. Реестр чанкеров (ЧНК-3/8: builtin видны в админке)
        from app.domain.indexing.plugins import reload_plugins

        reload_plugins(session)

        session.commit()
        log.info("bootstrap завершён: root group=%s, 4 пользователя, роли выданы", root.id)
        print(f"bootstrap OK: root group {root.id}")
    finally:
        session.close()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    main()
