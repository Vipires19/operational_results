"""Acesso aos registros operacionais e indicadores adicionais."""

from __future__ import annotations

import re
import unicodedata
from datetime import datetime

import pandas as pd
from sqlalchemy import delete, func, select
from sqlalchemy.engine import Connection, Engine

from database.connection import (
    operational_indicators,
    result_indicator_values,
    resultados,
)

METRIC_COLS = ["abordados", "carros", "motos", "bopm", "ocorrencias"]

RESERVED_SLUGS = {
    "abordados",
    "carros",
    "motos",
    "bopm",
    "ocorrencias",
    "indice_producao",
    "observacao",
    "data",
    "equipe",
    "pelotao",
    "modalidade",
    "id",
    "created_at",
    "obs",
}


def _as_date_str(value) -> str:
    if hasattr(value, "strftime"):
        return value.strftime("%Y-%m-%d")
    return str(value)[:10]


def _validate_metrics(row: dict) -> None:
    for col in METRIC_COLS:
        value = int(row.get(col, 0) or 0)
        if value < 0:
            raise ValueError(f"{col} não pode ser negativo.")
        row[col] = value


def normalize_indicator_name(name: str) -> str:
    return " ".join((name or "").split()).casefold()


def slugify(name: str) -> str:
    stripped = " ".join((name or "").split())
    nfkd = unicodedata.normalize("NFKD", stripped)
    ascii_text = "".join(ch for ch in nfkd if not unicodedata.combining(ch))
    ascii_text = ascii_text.lower()
    ascii_text = re.sub(r"[^a-z0-9]+", "_", ascii_text).strip("_")
    return ascii_text or "indicador"


def _row_to_indicator(row) -> dict:
    return {
        "id": int(row.id),
        "name": row.name,
        "slug": row.slug,
        "active": bool(row.active),
        "created_at": row.created_at,
    }


def list_indicators(engine: Engine, active_only: bool = False) -> list[dict]:
    query = select(operational_indicators).order_by(operational_indicators.c.name)
    if active_only:
        query = query.where(operational_indicators.c.active == 1)
    with engine.connect() as conn:
        return [_row_to_indicator(row) for row in conn.execute(query)]


def list_active_indicators(engine: Engine) -> list[dict]:
    return list_indicators(engine, active_only=True)


def _name_exists(conn: Connection, name: str, ignore_id: int | None = None) -> bool:
    target = normalize_indicator_name(name)
    query = select(operational_indicators.c.id, operational_indicators.c.name)
    for row in conn.execute(query):
        if ignore_id is not None and int(row.id) == ignore_id:
            continue
        if normalize_indicator_name(row.name) == target:
            return True
    return False


def _unique_slug(conn: Connection, base: str) -> str:
    slug = base
    suffix = 2
    while conn.execute(
        select(operational_indicators.c.id).where(
            operational_indicators.c.slug == slug
        )
    ).first():
        slug = f"{base}_{suffix}"
        suffix += 1
    return slug


def create_indicator(engine: Engine, name: str) -> dict:
    clean_name = " ".join((name or "").split())
    if not clean_name:
        raise ValueError("Informe o nome do indicador.")

    base_slug = slugify(clean_name)
    if base_slug in RESERVED_SLUGS:
        raise ValueError("Esse nome conflita com um indicador fixo do sistema.")

    with engine.begin() as conn:
        if _name_exists(conn, clean_name):
            raise ValueError("Já existe um indicador com esse nome.")
        slug = _unique_slug(conn, base_slug)
        result = conn.execute(
            operational_indicators.insert()
            .values(
                name=clean_name,
                slug=slug,
                active=1,
                created_at=datetime.now().isoformat(timespec="seconds"),
            )
            .returning(operational_indicators.c.id)
        )
        indicator_id = int(result.scalar_one())

    created = [i for i in list_indicators(engine) if i["id"] == indicator_id]
    return created[0]


def set_indicator_active(engine: Engine, indicator_id: int, active: bool) -> None:
    with engine.begin() as conn:
        conn.execute(
            operational_indicators.update()
            .where(operational_indicators.c.id == int(indicator_id))
            .values(active=1 if active else 0)
        )


def indicator_usage_counts(engine: Engine) -> dict[int, int]:
    query = (
        select(
            result_indicator_values.c.indicator_id,
            func.count().label("n"),
        )
        .group_by(result_indicator_values.c.indicator_id)
    )
    with engine.connect() as conn:
        return {int(row.indicator_id): int(row.n) for row in conn.execute(query)}


def indicator_usage_count(engine: Engine, indicator_id: int) -> int:
    return indicator_usage_counts(engine).get(int(indicator_id), 0)


def delete_indicator(engine: Engine, indicator_id: int) -> None:
    if indicator_usage_count(engine, indicator_id) > 0:
        raise ValueError(
            "Este indicador já possui histórico. Desative-o em vez de excluir."
        )
    with engine.begin() as conn:
        conn.execute(
            delete(operational_indicators).where(
                operational_indicators.c.id == int(indicator_id)
            )
        )


def load_data(engine: Engine) -> pd.DataFrame:
    query = select(resultados).order_by(
        resultados.c.data.desc(),
        resultados.c.id.desc(),
    )
    with engine.connect() as conn:
        df = pd.read_sql(query, conn)

    if df.empty:
        return df

    df["data"] = pd.to_datetime(df["data"])
    for col in METRIC_COLS:
        df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0).astype(int)
    if "observacao" in df.columns:
        df["observacao"] = df["observacao"].fillna("").astype(str)
    return df


def load_extras_wide(engine: Engine) -> pd.DataFrame:
    query = (
        select(
            result_indicator_values.c.result_id,
            operational_indicators.c.slug,
            result_indicator_values.c.value,
        )
        .select_from(
            result_indicator_values.join(
                operational_indicators,
                result_indicator_values.c.indicator_id
                == operational_indicators.c.id,
            )
        )
    )
    with engine.connect() as conn:
        long_df = pd.read_sql(query, conn)

    if long_df.empty:
        return pd.DataFrame(columns=["result_id"])

    wide = long_df.pivot_table(
        index="result_id",
        columns="slug",
        values="value",
        aggfunc="sum",
        fill_value=0,
    ).reset_index()
    wide.columns.name = None
    return wide


def attach_extra_columns(
    df: pd.DataFrame,
    extras_wide: pd.DataFrame,
    catalog: list[dict],
) -> pd.DataFrame:
    out = df.copy()
    slugs = [item["slug"] for item in catalog]

    if not extras_wide.empty and "id" in out.columns and not out.empty:
        out = out.merge(
            extras_wide,
            how="left",
            left_on="id",
            right_on="result_id",
        )
        if "result_id" in out.columns:
            out = out.drop(columns=["result_id"])

    for slug in slugs:
        if slug not in out.columns:
            out[slug] = 0
        elif not out.empty:
            out[slug] = pd.to_numeric(out[slug], errors="coerce").fillna(0).astype(int)
        else:
            out[slug] = pd.Series(dtype="int64")
    return out


def get_result_extra_values(engine: Engine, result_id: int) -> list[dict]:
    query = (
        select(
            operational_indicators.c.name,
            operational_indicators.c.slug,
            operational_indicators.c.active,
            result_indicator_values.c.value,
        )
        .select_from(
            result_indicator_values.join(
                operational_indicators,
                result_indicator_values.c.indicator_id
                == operational_indicators.c.id,
            )
        )
        .where(result_indicator_values.c.result_id == int(result_id))
        .order_by(operational_indicators.c.name)
    )
    with engine.connect() as conn:
        rows = conn.execute(query).all()
    return [
        {
            "name": row.name,
            "slug": row.slug,
            "active": bool(row.active),
            "value": int(row.value),
        }
        for row in rows
    ]


def _save_extra_values(
    conn: Connection,
    result_id: int,
    extras: dict | None,
) -> None:
    if not extras:
        return
    now = datetime.now().isoformat(timespec="seconds")
    payloads = []
    for indicator_id, raw_value in extras.items():
        value = int(raw_value or 0)
        if value < 0:
            raise ValueError("Indicador adicional não pode ser negativo.")
        if value == 0:
            continue
        payloads.append(
            {
                "result_id": int(result_id),
                "indicator_id": int(indicator_id),
                "value": value,
                "created_at": now,
            }
        )
    if payloads:
        conn.execute(result_indicator_values.insert(), payloads)


def _insert_result_row(conn: Connection, payload: dict) -> int:
    result = conn.execute(
        resultados.insert()
        .values(
            data=_as_date_str(payload["data"]),
            modalidade=payload["modalidade"],
            equipe=payload["equipe"],
            pelotao=payload["pelotao"],
            abordados=payload["abordados"],
            carros=payload["carros"],
            motos=payload["motos"],
            bopm=payload.get("bopm", 0),
            ocorrencias=payload["ocorrencias"],
            observacao=payload.get("observacao") or "",
            created_at=datetime.now().isoformat(timespec="seconds"),
        )
        .returning(resultados.c.id)
    )
    return int(result.scalar_one())


def insert_result(engine: Engine, row: dict) -> int:
    payload = dict(row)
    extras = payload.pop("extras", None) or {}
    _validate_metrics(payload)

    with engine.begin() as conn:
        result_id = _insert_result_row(conn, payload)
        _save_extra_values(conn, result_id, extras)
        return result_id


def insert_many(engine: Engine, rows: list[dict]) -> int:
    if not rows:
        return 0

    with engine.begin() as conn:
        for row in rows:
            payload = dict(row)
            extras = payload.pop("extras", None) or {}
            _validate_metrics(payload)
            result_id = _insert_result_row(conn, payload)
            _save_extra_values(conn, result_id, extras)
    return len(rows)


def delete_result(engine: Engine, result_id: int) -> None:
    with engine.begin() as conn:
        conn.execute(
            delete(result_indicator_values).where(
                result_indicator_values.c.result_id == int(result_id)
            )
        )
        conn.execute(
            delete(resultados).where(resultados.c.id == int(result_id))
        )
