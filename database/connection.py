"""Conexão SQLite (local) ou PostgreSQL (produção)."""

from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path

from sqlalchemy import (
    CheckConstraint,
    Column,
    ForeignKey,
    Index,
    Integer,
    MetaData,
    Numeric,
    Table,
    Text,
    UniqueConstraint,
    create_engine,
    event,
    inspect,
    select,
    text,
)
from sqlalchemy.engine import Engine
from sqlalchemy.pool import NullPool

from database.scoring import FIXED_INDEX_METRICS

BASE_DIR = Path(__file__).resolve().parent.parent
DB_PATH = BASE_DIR / "data" / "resultado_operacional.db"

metadata = MetaData()

resultados = Table(
    "resultados",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("data", Text, nullable=False),
    Column("modalidade", Text, nullable=False),
    Column("equipe", Text, nullable=False),
    Column("pelotao", Text, nullable=False),
    Column("abordados", Integer, nullable=False, server_default="0"),
    Column("carros", Integer, nullable=False, server_default="0"),
    Column("motos", Integer, nullable=False, server_default="0"),
    Column("bopm", Integer, nullable=False, server_default="0"),
    Column("ocorrencias", Integer, nullable=False, server_default="0"),
    Column("pessoas_presas", Integer, nullable=False, server_default="0"),
    Column("condenados_capturados", Integer, nullable=False, server_default="0"),
    Column("veiculos_recuperados", Integer, nullable=False, server_default="0"),
    Column("observacao", Text),
    Column("created_at", Text, nullable=False),
    CheckConstraint("abordados >= 0", name="ck_resultados_abordados"),
    CheckConstraint("carros >= 0", name="ck_resultados_carros"),
    CheckConstraint("motos >= 0", name="ck_resultados_motos"),
    CheckConstraint("bopm >= 0", name="ck_resultados_bopm"),
    CheckConstraint("ocorrencias >= 0", name="ck_resultados_ocorrencias"),
    CheckConstraint("pessoas_presas >= 0", name="ck_resultados_pessoas_presas"),
    CheckConstraint(
        "condenados_capturados >= 0", name="ck_resultados_condenados"
    ),
    CheckConstraint(
        "veiculos_recuperados >= 0", name="ck_resultados_veiculos"
    ),
    Index("ix_resultados_data", "data"),
    Index("ix_resultados_equipe", "equipe"),
    Index("ix_resultados_pelotao", "pelotao"),
)

operational_indicators = Table(
    "operational_indicators",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("name", Text, nullable=False),
    Column("slug", Text, nullable=False),
    Column("active", Integer, nullable=False, server_default="1"),
    Column("created_at", Text, nullable=False),
    UniqueConstraint("slug", name="uq_operational_indicators_slug"),
)

result_indicator_values = Table(
    "result_indicator_values",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column(
        "result_id",
        Integer,
        ForeignKey("resultados.id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column(
        "indicator_id",
        Integer,
        ForeignKey("operational_indicators.id"),
        nullable=False,
    ),
    Column("value", Integer, nullable=False),
    Column("created_at", Text, nullable=False),
    CheckConstraint("value >= 0", name="ck_result_indicator_value"),
    UniqueConstraint(
        "result_id",
        "indicator_id",
        name="uq_result_indicator_values_pair",
    ),
    Index("ix_result_indicator_values_result_id", "result_id"),
    Index("ix_result_indicator_values_indicator_id", "indicator_id"),
)

index_weights = Table(
    "index_weights",
    metadata,
    Column("metric_key", Text, primary_key=True),
    Column("weight", Numeric(12, 4), nullable=False, server_default="0"),
    Column("updated_at", Text, nullable=False),
    CheckConstraint("weight >= 0", name="ck_index_weights_weight"),
)

result_members = Table(
    "result_members",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column(
        "result_id",
        Integer,
        ForeignKey("resultados.id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column("member_name", Text, nullable=False),
    Column("created_at", Text, nullable=False),
    CheckConstraint("member_name <> ''", name="ck_result_members_name"),
    UniqueConstraint(
        "result_id",
        "member_name",
        name="uq_result_members_pair",
    ),
    Index("ix_result_members_result_id", "result_id"),
    Index("ix_result_members_name", "member_name"),
)

occurrence_types = Table(
    "occurrence_types",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("code", Text, nullable=False),
    Column("name", Text, nullable=False),
    Column("kpi_category", Text, nullable=False, server_default=""),
    Column("active", Integer, nullable=False, server_default="1"),
    Column("created_at", Text, nullable=False),
    UniqueConstraint("code", name="uq_occurrence_types_code"),
)

occurrences = Table(
    "occurrences",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column(
        "result_id",
        Integer,
        ForeignKey("resultados.id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column(
        "occurrence_type_id",
        Integer,
        ForeignKey("occurrence_types.id"),
        nullable=False,
    ),
    Column("bopm", Text),
    Column("bopc", Text),
    Column("observation", Text),
    Column("created_at", Text, nullable=False),
    Index("ix_occurrences_result_id", "result_id"),
    Index("ix_occurrences_type_id", "occurrence_type_id"),
)

occurrence_seizures = Table(
    "occurrence_seizures",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column(
        "occurrence_id",
        Integer,
        ForeignKey("occurrences.id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column("category", Text, nullable=False),
    Column("item", Text, nullable=False),
    Column("quantity", Numeric(14, 3), nullable=False),
    Column("unit", Text, nullable=False),
    Column("created_at", Text, nullable=False),
    CheckConstraint("quantity > 0", name="ck_occurrence_seizures_qty"),
    CheckConstraint("item <> ''", name="ck_occurrence_seizures_item"),
    Index("ix_occurrence_seizures_occurrence_id", "occurrence_id"),
    Index("ix_occurrence_seizures_category", "category"),
)

DEFAULT_EXTRA_INDICATOR = {
    "name": "Apoios Operacionais",
    "slug": "apoios_operacionais",
}

RESULTADOS_NEW_COLUMNS = (
    "pessoas_presas",
    "condenados_capturados",
    "veiculos_recuperados",
)

FIXED_RESULT_SLUGS = (
    "abordados",
    "carros",
    "motos",
    "bopm",
    "ocorrencias",
    *RESULTADOS_NEW_COLUMNS,
)


def read_database_url() -> str | None:
    """Lê DATABASE_URL do ambiente ou de st.secrets. Nunca registra o valor."""
    env_url = os.environ.get("DATABASE_URL", "").strip()
    if env_url:
        return env_url

    try:
        import streamlit as st

        secrets = st.secrets
        if "DATABASE_URL" in secrets:
            return str(secrets["DATABASE_URL"]).strip() or None

        postgres = secrets.get("postgres")
        if postgres and postgres.get("DATABASE_URL"):
            return str(postgres["DATABASE_URL"]).strip() or None

        connections = secrets.get("connections")
        if connections:
            pg = connections.get("postgresql")
            if pg and pg.get("url"):
                return str(pg["url"]).strip() or None
    except Exception:
        return None

    return None


def normalize_database_url(url: str) -> str:
    url = url.strip()
    if url.startswith("postgres://"):
        url = "postgresql://" + url[len("postgres://") :]
    if url.startswith("postgresql://"):
        url = "postgresql+psycopg://" + url[len("postgresql://") :]
    return url


def create_db_engine(url: str | None = None) -> Engine:
    raw = url if url is not None else read_database_url()

    if raw:
        db_url = normalize_database_url(raw)
        uses_pooler = "pooler" in db_url.lower()
        kwargs: dict = {"pool_pre_ping": True, "pool_recycle": 300}
        if uses_pooler:
            kwargs["poolclass"] = NullPool
        else:
            kwargs["pool_size"] = 2
            kwargs["max_overflow"] = 2
        engine = create_engine(db_url, **kwargs)
        if engine.dialect.name == "sqlite":
            event.listen(engine, "connect", _enable_sqlite_foreign_keys)
        return engine

    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    engine = create_engine(
        f"sqlite:///{DB_PATH.as_posix()}",
        connect_args={"check_same_thread": False},
        pool_pre_ping=True,
    )
    event.listen(engine, "connect", _enable_sqlite_foreign_keys)
    return engine


def _enable_sqlite_foreign_keys(dbapi_connection, _connection_record) -> None:
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()


def _ensure_resultados_columns(engine: Engine) -> None:
    existing = {col["name"] for col in inspect(engine).get_columns("resultados")}
    with engine.begin() as conn:
        for name in RESULTADOS_NEW_COLUMNS:
            if name in existing:
                continue
            conn.execute(
                text(
                    f"ALTER TABLE resultados ADD COLUMN {name} "
                    "INTEGER NOT NULL DEFAULT 0"
                )
            )


def init_schema(engine: Engine) -> None:
    metadata.create_all(engine)
    _ensure_resultados_columns(engine)
    with engine.begin() as conn:
        conn.execute(
            text("CREATE INDEX IF NOT EXISTS ix_resultados_data ON resultados (data)")
        )
        conn.execute(
            text(
                "CREATE INDEX IF NOT EXISTS ix_resultados_equipe ON resultados (equipe)"
            )
        )
        conn.execute(
            text(
                "CREATE INDEX IF NOT EXISTS ix_resultados_pelotao ON resultados (pelotao)"
            )
        )
        conn.execute(
            text(
                "CREATE INDEX IF NOT EXISTS ix_result_indicator_values_result_id "
                "ON result_indicator_values (result_id)"
            )
        )
        conn.execute(
            text(
                "CREATE INDEX IF NOT EXISTS ix_result_indicator_values_indicator_id "
                "ON result_indicator_values (indicator_id)"
            )
        )
        conn.execute(
            text(
                "CREATE INDEX IF NOT EXISTS ix_result_members_result_id "
                "ON result_members (result_id)"
            )
        )
        conn.execute(
            text(
                "CREATE INDEX IF NOT EXISTS ix_result_members_name "
                "ON result_members (member_name)"
            )
        )
        conn.execute(
            text(
                "CREATE INDEX IF NOT EXISTS ix_occurrences_result_id "
                "ON occurrences (result_id)"
            )
        )
        conn.execute(
            text(
                "CREATE INDEX IF NOT EXISTS ix_occurrence_seizures_occurrence_id "
                "ON occurrence_seizures (occurrence_id)"
            )
        )
    _seed_default_indicators(engine)
    _deactivate_reserved_dynamic_indicators(engine)
    ensure_index_weights(engine)


def ensure_index_weights(engine: Engine) -> None:
    now = datetime.now().isoformat(timespec="seconds")
    with engine.begin() as conn:
        existing = {
            str(row.metric_key)
            for row in conn.execute(select(index_weights.c.metric_key))
        }
        payloads = []
        for key, _label, weight in FIXED_INDEX_METRICS:
            if key in existing:
                continue
            payloads.append(
                {"metric_key": key, "weight": weight, "updated_at": now}
            )
            existing.add(key)
        extra_slugs = [
            str(row.slug)
            for row in conn.execute(select(operational_indicators.c.slug))
            if str(row.slug) not in existing
        ]
        for slug in extra_slugs:
            payloads.append(
                {"metric_key": slug, "weight": 0, "updated_at": now}
            )
            existing.add(slug)
        if payloads:
            conn.execute(index_weights.insert(), payloads)


def _seed_default_indicators(engine: Engine) -> None:
    slug = DEFAULT_EXTRA_INDICATOR["slug"]
    with engine.begin() as conn:
        exists = conn.execute(
            select(operational_indicators.c.id).where(
                operational_indicators.c.slug == slug
            )
        ).first()
        if exists:
            return
        conn.execute(
            operational_indicators.insert().values(
                name=DEFAULT_EXTRA_INDICATOR["name"],
                slug=slug,
                active=1,
                created_at=datetime.now().isoformat(timespec="seconds"),
            )
        )


def _deactivate_reserved_dynamic_indicators(engine: Engine) -> None:
    """Indicadores extras cujo slug colide com coluna fixa de resultados saem do uso ativo."""
    with engine.begin() as conn:
        conn.execute(
            operational_indicators.update()
            .where(operational_indicators.c.slug.in_(FIXED_RESULT_SLUGS))
            .values(active=0)
        )


def get_engine() -> Engine:
    engine = create_db_engine()
    init_schema(engine)
    return engine


def backend_label(engine: Engine) -> str:
    if engine.dialect.name == "postgresql":
        return "PostgreSQL"
    return "SQLite local"
