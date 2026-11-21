"""etap0 initial schema

Revision ID: a24d0e15bfae
Revises:
Create Date: 2026-11-20 23:27:49.996271

Начальная схема по data-model.md: 17 таблиц + FTS-колонки + индексы.
Enum-типы создаются идемпотентно (повторный upgrade не падает).
"""

from collections.abc import Sequence

import alembic.op as op
import pgvector.sqlalchemy  # noqa: F401 — рендер VECTOR в DDL
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

import app.models.types  # noqa: F401 — рендер Ltree в DDL

# revision identifiers, used by Alembic.
revision: str = "a24d0e15bfae"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Enum-типы, создаваемые идемпотентно (data-model.md §3, §4, §5.1, §6, §13)
ENUM_TYPES: dict[str, tuple[str, ...]] = {
    "material_status": ("draft", "on_review", "confirmed", "archived", "deleted"),
    "group_role": ("reader", "editor", "reviewer", "owner"),
    "attribute_type": ("string", "number", "date", "bool", "select", "multi_select"),
    "text_extracted": ("success", "failed", "unsupported"),
    "av_status": ("pending", "clean", "infected", "skipped_stub"),
    "job_step": ("av", "extract", "chunk", "embed", "preview"),
    "job_status": ("pending", "running", "done", "failed"),
}


def _ensure_enum_types() -> None:
    """CREATE TYPE IF NOT EXISTS через DO-блок (НФТ-9: идемпотентность)."""

    for name, values in ENUM_TYPES.items():
        vals = ", ".join(f"'{v}'" for v in values)
        op.execute(
            f"DO $$ BEGIN "
            f"IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = '{name}') THEN "
            f"CREATE TYPE {name} AS ENUM ({vals}); "
            f"END IF; END $$;"
        )


def upgrade() -> None:
    """Upgrade schema."""
    # Расширения: vector (pgvector), ltree (пути групп), uuid-ossp (uuid_nil для uq_groups_name_alive)
    op.execute('CREATE EXTENSION IF NOT EXISTS vector')
    op.execute('CREATE EXTENSION IF NOT EXISTS ltree')
    op.execute('CREATE EXTENSION IF NOT EXISTS "uuid-ossp"')

    _ensure_enum_types()

    op.create_table("attribute_defs",
    sa.Column("key", sa.Text(), nullable=False),
    sa.Column("name", sa.Text(), nullable=False),
    sa.Column("type", sa.Enum(*ENUM_TYPES["attribute_type"], name="attribute_type", create_type=False), nullable=False),
    sa.Column("options", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column("is_active", sa.Boolean(), nullable=False),
    sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
    sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    sa.PrimaryKeyConstraint("id", name=op.f("pk_attribute_defs")),
    sa.UniqueConstraint("key", name=op.f("uq_attribute_defs_key"))
    )
    op.create_table("audit_log",
    sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
    sa.Column("at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    sa.Column("actor_id", sa.UUID(), nullable=True),
    sa.Column("action", sa.Text(), nullable=False),
    sa.Column("object_type", sa.Text(), nullable=True),
    sa.Column("object_id", sa.UUID(), nullable=True),
    sa.Column("details", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column("request_id", sa.UUID(), nullable=True),
    sa.PrimaryKeyConstraint("id", name=op.f("pk_audit_log"))
    )
    op.create_table("chunker_registry",
    sa.Column("name", sa.Text(), nullable=False),
    sa.Column("code_hash", sa.Text(), nullable=True),
    sa.Column("builtin", sa.Boolean(), nullable=False),
    sa.Column("params_schema", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column("is_loaded", sa.Boolean(), nullable=False),
    sa.Column("error", sa.Text(), nullable=True),
    sa.PrimaryKeyConstraint("name", name=op.f("pk_chunker_registry"))
    )
    op.create_table("files",
    sa.Column("storage_key", sa.Text(), nullable=False),
    sa.Column("original_filename", sa.Text(), nullable=False),
    sa.Column("mime", sa.Text(), nullable=False),
    sa.Column("size", sa.BigInteger(), nullable=False),
    sa.Column("sha256", sa.Text(), nullable=False),
    sa.Column("preview_key", sa.Text(), nullable=True),
    sa.Column("text_extracted", sa.Enum(*ENUM_TYPES["text_extracted"], name="text_extracted", create_type=False), nullable=False),
    sa.Column("av_status", sa.Enum(*ENUM_TYPES["av_status"], name="av_status", create_type=False), nullable=False),
    sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
    sa.PrimaryKeyConstraint("id", name=op.f("pk_files")),
    sa.UniqueConstraint("sha256", "size", name="uq_files_sha_size")
    )
    op.create_table("groups",
    sa.Column("parent_id", sa.UUID(), nullable=True),
    sa.Column("name", sa.Text(), nullable=False),
    sa.Column("description", sa.Text(), nullable=True),
    sa.Column("path", app.models.types.Ltree(), nullable=False),
    sa.Column("is_deleted", sa.Boolean(), nullable=False),
    sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
    sa.Column("deleted_by", sa.UUID(), nullable=True),
    sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
    sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    sa.ForeignKeyConstraint(["parent_id"], ["groups.id"], name=op.f("fk_groups_parent_id_groups")),
    sa.PrimaryKeyConstraint("id", name=op.f("pk_groups"))
    )
    op.create_table("jobs",
    sa.Column("material_id", sa.UUID(), nullable=True),
    sa.Column("version_id", sa.UUID(), nullable=False),
    sa.Column("step", sa.Enum(*ENUM_TYPES["job_step"], name="job_step", create_type=False), nullable=False),
    sa.Column("status", sa.Enum(*ENUM_TYPES["job_status"], name="job_status", create_type=False), nullable=False),
    sa.Column("attempts", sa.Integer(), nullable=False),
    sa.Column("error", sa.Text(), nullable=True),
    sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
    sa.PrimaryKeyConstraint("id", name=op.f("pk_jobs")),
    sa.UniqueConstraint("version_id", "step", name="uq_jobs_version_step")
    )
    op.create_table("notification_deliveries",
    sa.Column("event_id", sa.UUID(), nullable=False),
    sa.Column("recipient_id", sa.UUID(), nullable=False),
    sa.Column("channel", sa.Text(), nullable=False),
    sa.Column("status", sa.Text(), nullable=False),
    sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
    sa.Column("idempotency_key", sa.Text(), nullable=False),
    sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
    sa.PrimaryKeyConstraint("id", name=op.f("pk_notification_deliveries")),
    sa.UniqueConstraint("idempotency_key", name="uq_notification_deliveries_key")
    )
    op.create_table("notification_events",
    sa.Column("code", sa.Text(), nullable=False),
    sa.Column("title", sa.Text(), nullable=False),
    sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
    sa.PrimaryKeyConstraint("id", name=op.f("pk_notification_events")),
    sa.UniqueConstraint("code", name=op.f("uq_notification_events_code"))
    )
    op.create_table("notification_subscriptions",
    sa.Column("event_code", sa.Text(), nullable=False),
    sa.Column("role", sa.Text(), nullable=False),
    sa.Column("channel", sa.Text(), nullable=False),
    sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
    sa.PrimaryKeyConstraint("id", name=op.f("pk_notification_subscriptions"))
    )
    op.create_table("settings",
    sa.Column("key", sa.Text(), nullable=False),
    sa.Column("value", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column("updated_by", sa.UUID(), nullable=True),
    sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    sa.PrimaryKeyConstraint("key", name=op.f("pk_settings"))
    )
    op.create_table("users",
    sa.Column("keycloak_sub", sa.Text(), nullable=False),
    sa.Column("username", sa.Text(), nullable=False),
    sa.Column("display_name", sa.Text(), nullable=False),
    sa.Column("email", sa.Text(), nullable=True),
    sa.Column("is_local", sa.Boolean(), nullable=False),
    sa.Column("is_blocked", sa.Boolean(), nullable=False),
    sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
    sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    sa.PrimaryKeyConstraint("id", name=op.f("pk_users")),
    sa.UniqueConstraint("keycloak_sub", name=op.f("uq_users_keycloak_sub")),
    sa.UniqueConstraint("username", name=op.f("uq_users_username"))
    )
    op.create_table("group_roles",
    sa.Column("user_id", sa.UUID(), nullable=False),
    sa.Column("group_id", sa.UUID(), nullable=False),
    sa.Column("role", sa.Enum(*ENUM_TYPES["group_role"], name="group_role", create_type=False), nullable=False),
    sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
    sa.ForeignKeyConstraint(["group_id"], ["groups.id"], name=op.f("fk_group_roles_group_id_groups")),
    sa.ForeignKeyConstraint(["user_id"], ["users.id"], name=op.f("fk_group_roles_user_id_users")),
    sa.PrimaryKeyConstraint("id", name=op.f("pk_group_roles")),
    sa.UniqueConstraint("user_id", "group_id", name="uq_group_roles_user_group")
    )
    op.create_table("chunker_configs",
    sa.Column("group_id", sa.UUID(), nullable=False),
    sa.Column("chunker_name", sa.Text(), nullable=False),
    sa.Column("params", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
    sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    sa.ForeignKeyConstraint(["group_id"], ["groups.id"], name=op.f("fk_chunker_configs_group_id_groups")),
    sa.PrimaryKeyConstraint("id", name=op.f("pk_chunker_configs")),
    sa.UniqueConstraint("group_id", name=op.f("uq_chunker_configs_group_id"))
    )
    op.create_table("materials",
    sa.Column("group_id", sa.UUID(), nullable=False),
    sa.Column("name", sa.Text(), nullable=False),
    sa.Column("status", sa.Enum(*ENUM_TYPES["material_status"], name="material_status", create_type=False), server_default="draft", nullable=False),
    sa.Column("author_id", sa.UUID(), nullable=False),
    sa.Column("current_version_id", sa.UUID(), nullable=True),
    sa.Column("is_deleted", sa.Boolean(), nullable=False),
    sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
    sa.Column("deleted_by", sa.UUID(), nullable=True),
    sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
    sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    sa.ForeignKeyConstraint(["author_id"], ["users.id"], name=op.f("fk_materials_author_id_users")),
    sa.ForeignKeyConstraint(["group_id"], ["groups.id"], name=op.f("fk_materials_group_id_groups")),
    sa.PrimaryKeyConstraint("id", name=op.f("pk_materials"))
    )
    op.create_table("material_versions",
    sa.Column("material_id", sa.UUID(), nullable=False),
    sa.Column("version_no", sa.Integer(), nullable=False),
    sa.Column("file_id", sa.UUID(), nullable=False),
    sa.Column("description", sa.Text(), nullable=True),
    sa.Column("external_links", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column("attributes", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column("change_comment", sa.Text(), nullable=False),
    sa.Column("created_by", sa.UUID(), nullable=False),
    sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    sa.Column("reviewers", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column("confirmed_by", sa.UUID(), nullable=True),
    sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=True),
    sa.Column("chunker_name", sa.Text(), nullable=True),
    sa.Column("chunker_version", sa.Text(), nullable=True),
    sa.Column("file_sha256", sa.Text(), nullable=False),
    sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
    sa.ForeignKeyConstraint(["file_id"], ["files.id"], name=op.f("fk_material_versions_file_id_files")),
    sa.ForeignKeyConstraint(["material_id"], ["materials.id"], name=op.f("fk_material_versions_material_id_materials")),
    sa.PrimaryKeyConstraint("id", name=op.f("pk_material_versions"))
    )
    op.create_table("chunks",
    sa.Column("material_id", sa.UUID(), nullable=False),
    sa.Column("version_id", sa.UUID(), nullable=False),
    sa.Column("chunk_index", sa.Integer(), nullable=False),
    sa.Column("parent_index", sa.Integer(), nullable=True),
    sa.Column("chunker_name", sa.Text(), nullable=False),
    sa.Column("chunker_version", sa.Text(), nullable=False),
    sa.Column("text", sa.Text(), nullable=False),
    sa.Column("metadata", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column("embedding", pgvector.sqlalchemy.vector.VECTOR(dim=1024), nullable=False),
    sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
    sa.ForeignKeyConstraint(["material_id"], ["materials.id"], name=op.f("fk_chunks_material_id_materials")),
    sa.ForeignKeyConstraint(["version_id"], ["material_versions.id"], name=op.f("fk_chunks_version_id_material_versions")),
    sa.PrimaryKeyConstraint("id", name=op.f("pk_chunks")),
    sa.UniqueConstraint("version_id", "chunk_index", "chunker_name", name="uq_chunks_version_index_chunker")
    )
    op.create_table("material_links",
    sa.Column("child_id", sa.UUID(), nullable=False),
    sa.Column("parent_id", sa.UUID(), nullable=False),
    sa.Column("parent_version_id", sa.UUID(), nullable=False),
    sa.Column("created_by", sa.UUID(), nullable=False),
    sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
    sa.ForeignKeyConstraint(["child_id"], ["materials.id"], name=op.f("fk_material_links_child_id_materials")),
    sa.ForeignKeyConstraint(["parent_id"], ["materials.id"], name=op.f("fk_material_links_parent_id_materials")),
    sa.ForeignKeyConstraint(["parent_version_id"], ["material_versions.id"], name=op.f("fk_material_links_parent_version_id_material_versions")),
    sa.PrimaryKeyConstraint("id", name=op.f("pk_material_links")),
    sa.UniqueConstraint("child_id", name="uq_material_links_child")
    )
    op.create_table("status_journal",
    sa.Column("material_id", sa.UUID(), nullable=False),
    sa.Column("version_id", sa.UUID(), nullable=False),
    sa.Column("from_status", sa.Enum(*ENUM_TYPES["material_status"], name="material_status", create_type=False), nullable=False),
    sa.Column("to_status", sa.Enum(*ENUM_TYPES["material_status"], name="material_status", create_type=False), nullable=False),
    sa.Column("actor_id", sa.UUID(), nullable=False),
    sa.Column("request_id", sa.UUID(), nullable=True),
    sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
    sa.ForeignKeyConstraint(["material_id"], ["materials.id"], name=op.f("fk_status_journal_material_id_materials")),
    sa.ForeignKeyConstraint(["version_id"], ["material_versions.id"], name=op.f("fk_status_journal_version_id_material_versions")),
    sa.PrimaryKeyConstraint("id", name=op.f("pk_status_journal"))
    )

    # --- FTS-колонки (data-model §8.1): заполняются сервисно ---
    op.execute("ALTER TABLE materials ADD COLUMN name_tsv tsvector")
    op.execute("ALTER TABLE material_versions ADD COLUMN description_tsv tsvector")
    op.execute("ALTER TABLE groups ADD COLUMN name_tsv tsvector, ADD COLUMN description_tsv tsvector")

    # --- Индексы data-model.md ---
    # ГРП-2: уникальность имени живой группы в рамках родителя
    op.execute("CREATE UNIQUE INDEX uq_groups_name_alive ON groups (coalesce(parent_id, uuid_nil()), lower(trim(name))) WHERE NOT is_deleted")
    # Быстрое раскрытие поддерева (ltree GiST)
    op.execute("CREATE INDEX ix_groups_path ON groups USING gist (path)")
    # МАТ-4: уникальность имени живого материала в группе
    op.execute("CREATE UNIQUE INDEX uq_materials_name_alive ON materials (group_id, lower(trim(name))) WHERE NOT is_deleted")
    # НФТ-9: идемпотентность переходов статусов
    op.execute("CREATE UNIQUE INDEX uq_status_journal_request ON status_journal (request_id) WHERE request_id IS NOT NULL")
    # ПСК-1: GIN по атрибутам версий
    op.execute("CREATE INDEX ix_material_versions_attributes ON material_versions USING gin (attributes)")
    # FTS GIN-индексы
    op.execute("CREATE INDEX ix_materials_name_tsv ON materials USING gin (name_tsv)")
    op.execute("CREATE INDEX ix_material_versions_description_tsv ON material_versions USING gin (description_tsv)")
    op.execute("CREATE INDEX ix_groups_name_tsv ON groups USING gin (name_tsv)")
    op.execute("CREATE INDEX ix_groups_description_tsv ON groups USING gin (description_tsv)")
    # ПСК-5/§14: HNSW по векторам (halfvec — компактный индекс, косинусная близость)
    op.execute("CREATE INDEX ix_chunks_embedding_hnsw ON chunks USING hnsw ((embedding::halfvec(1024)) halfvec_cosine_ops)")
    # GIN по metadata чанков
    op.execute("CREATE INDEX ix_chunks_metadata ON chunks USING gin (metadata)")
    # Пайплайн (ЧНК-1): embedding появляется на шаге embed
    op.execute("ALTER TABLE chunks ALTER COLUMN embedding DROP NOT NULL")
    # FTS-колонки чанков (data-model §8)
    op.execute("ALTER TABLE chunks ADD COLUMN tsv_ru tsvector")
    op.execute("ALTER TABLE chunks ADD COLUMN tsv_en tsvector")
    op.execute("CREATE INDEX ix_chunks_tsv_ru ON chunks USING gin (tsv_ru)")
    op.execute("CREATE INDEX ix_chunks_tsv_en ON chunks USING gin (tsv_en)")


def downgrade() -> None:
    """Downgrade schema."""
    # 1) Сервисные индексы и FTS-колонки (таблицы ещё существуют)
    op.execute("DROP INDEX IF EXISTS uq_groups_name_alive")
    op.execute("DROP INDEX IF EXISTS ix_groups_path")
    op.execute("DROP INDEX IF EXISTS uq_materials_name_alive")
    op.execute("DROP INDEX IF EXISTS uq_status_journal_request")
    op.execute("DROP INDEX IF EXISTS ix_material_versions_attributes")
    op.execute("DROP INDEX IF EXISTS ix_materials_name_tsv")
    op.execute("DROP INDEX IF EXISTS ix_material_versions_description_tsv")
    op.execute("DROP INDEX IF EXISTS ix_groups_name_tsv")
    op.execute("DROP INDEX IF EXISTS ix_groups_description_tsv")
    op.execute("DROP INDEX IF EXISTS ix_chunks_tsv_en")
    op.execute("DROP INDEX IF EXISTS ix_chunks_tsv_ru")
    op.execute("ALTER TABLE chunks DROP COLUMN IF EXISTS tsv_en")
    op.execute("ALTER TABLE chunks DROP COLUMN IF EXISTS tsv_ru")
    op.execute("ALTER TABLE chunks ALTER COLUMN embedding SET NOT NULL")
    op.execute("DROP INDEX IF EXISTS ix_chunks_metadata")
    op.execute("DROP INDEX IF EXISTS ix_chunks_embedding_hnsw")
    op.execute("ALTER TABLE groups DROP COLUMN IF EXISTS name_tsv, DROP COLUMN IF EXISTS description_tsv")
    op.execute("ALTER TABLE material_versions DROP COLUMN IF EXISTS description_tsv")
    op.execute("ALTER TABLE materials DROP COLUMN IF EXISTS name_tsv")

    # 2) Таблицы в порядке зависимостей
    op.drop_table("status_journal")
    op.drop_table("material_links")
    op.drop_table("chunks")
    op.drop_table("material_versions")
    op.drop_table("materials")
    op.drop_table("chunker_configs")
    op.drop_table("group_roles")
    op.drop_table("users")
    op.drop_table("settings")
    op.drop_table("notification_subscriptions")
    op.drop_table("notification_events")
    op.drop_table("notification_deliveries")
    op.drop_table("jobs")
    op.drop_table("groups")
    op.drop_table("files")
    op.drop_table("chunker_registry")
    op.drop_table("audit_log")
    op.drop_table("attribute_defs")

    # 3) Enum-типы — в самом конце
    for name in ENUM_TYPES:
        op.execute(f"DROP TYPE IF EXISTS {name}")
    op.execute('DROP EXTENSION IF EXISTS "uuid-ossp"')
