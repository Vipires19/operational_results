"""Acesso aos registros operacionais, efetivo, ocorrências e apreensões."""

from __future__ import annotations

import re
import unicodedata
from datetime import datetime
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

import pandas as pd
from sqlalchemy import delete, func, select
from sqlalchemy.engine import Connection, Engine

from database.connection import (
    occurrence_seizures,
    occurrence_types,
    occurrences,
    operational_indicators,
    result_indicator_values,
    result_members,
    resultados,
)

METRIC_COLS = ["abordados", "carros", "motos", "bopm", "ocorrencias"]
PRODUCTIVITY_COLS = [
    "pessoas_presas",
    "condenados_capturados",
    "veiculos_recuperados",
]
RESULT_METRIC_COLS = METRIC_COLS + PRODUCTIVITY_COLS

APOIOS_SLUG = "apoios_operacionais"

RESERVED_SLUGS = {
    *RESULT_METRIC_COLS,
    "indice_producao",
    "observacao",
    "data",
    "equipe",
    "pelotao",
    "modalidade",
    "id",
    "created_at",
    "obs",
    "efetivo",
}

KPI_CATEGORY_LABELS = {
    "": "Nenhuma",
    "ROUBO": "Roubo",
    "FURTO": "Furto",
    "ROUBO_VEICULO": "Roubo de veículo",
    "FURTO_VEICULO": "Furto de veículo",
}

SEIZURE_CATEGORIES = ("DROGA", "OBJETO", "ARMA", "MUNICAO", "DINHEIRO")
SEIZURE_KPI_CATEGORIES = ("DROGA", "ARMA", "MUNICAO", "DINHEIRO")

COUNT_CATEGORIES = {"OBJETO", "ARMA", "MUNICAO"}


def _as_date_str(value) -> str:
    if hasattr(value, "strftime"):
        return value.strftime("%Y-%m-%d")
    return str(value)[:10]


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _validate_metrics(row: dict) -> None:
    for col in RESULT_METRIC_COLS:
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


def parse_members(raw: str | None) -> list[str]:
    if not raw:
        return []
    names = []
    seen = set()
    for part in str(raw).replace("\n", "/").split("/"):
        name = " ".join(part.split()).upper()
        if not name or name in seen:
            continue
        seen.add(name)
        names.append(name)
    return names


def format_members(names: list[str]) -> str:
    return " / ".join(names)


def normalize_item(value: str) -> str:
    return " ".join((value or "").split()).upper()


def _to_decimal(value) -> Decimal:
    text = str(value).strip().replace(" ", "").replace(",", ".")
    try:
        number = Decimal(text)
    except (InvalidOperation, ValueError) as exc:
        raise ValueError("Quantidade inválida.") from exc
    if number <= 0:
        raise ValueError("A quantidade deve ser maior que zero.")
    return number


def normalize_seizure(category: str, item: str, quantity, unit: str | None) -> dict:
    cat = normalize_item(category)
    if cat not in SEIZURE_CATEGORIES:
        raise ValueError("Categoria de apreensão inválida.")
    clean_item = normalize_item(item)
    if not clean_item:
        raise ValueError("Informe o item da apreensão.")

    raw_unit = (unit or "").strip().lower()
    qty = _to_decimal(quantity)

    if cat == "DROGA":
        if raw_unit in {"kg", "quilo", "quilos"}:
            qty = qty * Decimal("1000")
        stored_unit = "g"
        qty = qty.quantize(Decimal("0.001"), rounding=ROUND_HALF_UP)
    elif cat == "DINHEIRO":
        stored_unit = "BRL"
        qty = qty.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    else:
        if qty != qty.to_integral_value():
            raise ValueError(f"{cat} exige quantidade inteira.")
        qty = qty.to_integral_value()
        stored_unit = "un"

    return {
        "category": cat,
        "item": clean_item,
        "quantity": qty,
        "unit": stored_unit,
    }


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
                created_at=_now(),
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
    query = select(
        result_indicator_values.c.indicator_id,
        func.count().label("n"),
    ).group_by(result_indicator_values.c.indicator_id)
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
        for col in RESULT_METRIC_COLS:
            if col not in df.columns:
                df[col] = pd.Series(dtype="int64")
        return df

    df["data"] = pd.to_datetime(df["data"])
    for col in RESULT_METRIC_COLS:
        if col not in df.columns:
            df[col] = 0
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
            operational_indicators.c.id,
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
            "indicator_id": int(row.id),
            "name": row.name,
            "slug": row.slug,
            "active": bool(row.active),
            "value": int(row.value),
        }
        for row in rows
    ]


def load_members_map(engine: Engine) -> dict[int, list[str]]:
    query = select(result_members).order_by(
        result_members.c.result_id, result_members.c.id
    )
    mapping: dict[int, list[str]] = {}
    with engine.connect() as conn:
        for row in conn.execute(query):
            mapping.setdefault(int(row.result_id), []).append(row.member_name)
    return mapping


def get_result_members(engine: Engine, result_id: int) -> list[str]:
    return load_members_map(engine).get(int(result_id), [])


def count_occurrences_by_result(engine: Engine) -> dict[int, int]:
    query = select(
        occurrences.c.result_id,
        func.count().label("n"),
    ).group_by(occurrences.c.result_id)
    with engine.connect() as conn:
        return {int(row.result_id): int(row.n) for row in conn.execute(query)}


def count_occurrences_for_result(engine: Engine, result_id: int) -> int:
    return count_occurrences_by_result(engine).get(int(result_id), 0)


def _save_extra_values(
    conn: Connection,
    result_id: int,
    extras: dict | None,
) -> None:
    if not extras:
        return
    now = _now()
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


def _save_members(conn: Connection, result_id: int, names: list[str]) -> None:
    if not names:
        return
    now = _now()
    conn.execute(
        result_members.insert(),
        [
            {
                "result_id": int(result_id),
                "member_name": name,
                "created_at": now,
            }
            for name in names
        ],
    )


def _result_values(payload: dict) -> dict:
    return {
        "data": _as_date_str(payload["data"]),
        "modalidade": payload["modalidade"],
        "equipe": payload["equipe"],
        "pelotao": payload["pelotao"],
        "abordados": payload["abordados"],
        "carros": payload["carros"],
        "motos": payload["motos"],
        "bopm": payload.get("bopm", 0),
        "ocorrencias": payload["ocorrencias"],
        "pessoas_presas": payload.get("pessoas_presas", 0),
        "condenados_capturados": payload.get("condenados_capturados", 0),
        "veiculos_recuperados": payload.get("veiculos_recuperados", 0),
        "observacao": payload.get("observacao") or "",
    }


def _split_result_payload(row: dict) -> tuple[dict, dict, list[str]]:
    payload = dict(row)
    extras = payload.pop("extras", None) or {}
    members = payload.pop("members", None)
    if members is None:
        members = parse_members(payload.pop("efetivo", ""))
    _validate_metrics(payload)
    return payload, extras, members


def _insert_result_row(conn: Connection, payload: dict) -> int:
    result = conn.execute(
        resultados.insert()
        .values(**_result_values(payload), created_at=_now())
        .returning(resultados.c.id)
    )
    return int(result.scalar_one())


def insert_result(engine: Engine, row: dict) -> int:
    payload, extras, members = _split_result_payload(row)
    with engine.begin() as conn:
        result_id = _insert_result_row(conn, payload)
        _save_members(conn, result_id, members)
        _save_extra_values(conn, result_id, extras)
        return result_id


def insert_many(engine: Engine, rows: list[dict]) -> int:
    if not rows:
        return 0
    with engine.begin() as conn:
        for row in rows:
            payload, extras, members = _split_result_payload(row)
            result_id = _insert_result_row(conn, payload)
            _save_members(conn, result_id, members)
            _save_extra_values(conn, result_id, extras)
    return len(rows)


def update_result(engine: Engine, result_id: int, row: dict) -> None:
    payload, extras, members = _split_result_payload(row)
    with engine.begin() as conn:
        updated = conn.execute(
            resultados.update()
            .where(resultados.c.id == int(result_id))
            .values(**_result_values(payload))
        )
        if updated.rowcount == 0:
            raise ValueError("Resultado não encontrado.")
        conn.execute(
            delete(result_members).where(
                result_members.c.result_id == int(result_id)
            )
        )
        _save_members(conn, int(result_id), members)
        conn.execute(
            delete(result_indicator_values).where(
                result_indicator_values.c.result_id == int(result_id)
            )
        )
        _save_extra_values(conn, int(result_id), extras)


def delete_result(engine: Engine, result_id: int) -> None:
    rid = int(result_id)
    with engine.begin() as conn:
        occ_ids = [
            int(row.id)
            for row in conn.execute(
                select(occurrences.c.id).where(occurrences.c.result_id == rid)
            )
        ]
        if occ_ids:
            conn.execute(
                delete(occurrence_seizures).where(
                    occurrence_seizures.c.occurrence_id.in_(occ_ids)
                )
            )
            conn.execute(delete(occurrences).where(occurrences.c.result_id == rid))
        conn.execute(delete(result_members).where(result_members.c.result_id == rid))
        conn.execute(
            delete(result_indicator_values).where(
                result_indicator_values.c.result_id == rid
            )
        )
        conn.execute(delete(resultados).where(resultados.c.id == rid))


def list_results_by_date(engine: Engine, day) -> list[dict]:
    day_str = _as_date_str(day)
    query = (
        select(resultados)
        .where(resultados.c.data == day_str)
        .order_by(resultados.c.equipe, resultados.c.id)
    )
    with engine.connect() as conn:
        rows = conn.execute(query).all()
    return [
        {
            "id": int(row.id),
            "data": row.data,
            "equipe": row.equipe,
            "pelotao": row.pelotao,
            "modalidade": row.modalidade,
        }
        for row in rows
    ]


def _type_to_dict(row) -> dict:
    return {
        "id": int(row.id),
        "code": row.code,
        "name": row.name,
        "kpi_category": row.kpi_category or "",
        "active": bool(row.active),
        "created_at": row.created_at,
    }


def list_occurrence_types(engine: Engine, active_only: bool = False) -> list[dict]:
    query = select(occurrence_types).order_by(
        occurrence_types.c.code, occurrence_types.c.name
    )
    if active_only:
        query = query.where(occurrence_types.c.active == 1)
    with engine.connect() as conn:
        return [_type_to_dict(row) for row in conn.execute(query)]


def create_occurrence_type(
    engine: Engine,
    code: str,
    name: str,
    kpi_category: str = "",
) -> dict:
    clean_code = " ".join((code or "").split()).upper()
    clean_name = " ".join((name or "").split()).upper()
    category = (kpi_category or "").strip().upper()
    if category == "NENHUMA":
        category = ""
    if not clean_code:
        raise ValueError("Informe o código do tipo.")
    if not clean_name:
        raise ValueError("Informe o nome do tipo.")
    if category not in KPI_CATEGORY_LABELS:
        raise ValueError("Categoria de KPI inválida.")

    with engine.begin() as conn:
        existing = conn.execute(select(occurrence_types.c.code)).all()
        if any(row.code.casefold() == clean_code.casefold() for row in existing):
            raise ValueError("Já existe um tipo com esse código.")
        result = conn.execute(
            occurrence_types.insert()
            .values(
                code=clean_code,
                name=clean_name,
                kpi_category=category,
                active=1,
                created_at=_now(),
            )
            .returning(occurrence_types.c.id)
        )
        type_id = int(result.scalar_one())
    return next(item for item in list_occurrence_types(engine) if item["id"] == type_id)


def set_occurrence_type_active(engine: Engine, type_id: int, active: bool) -> None:
    with engine.begin() as conn:
        conn.execute(
            occurrence_types.update()
            .where(occurrence_types.c.id == int(type_id))
            .values(active=1 if active else 0)
        )


def occurrence_type_usage_counts(engine: Engine) -> dict[int, int]:
    query = select(
        occurrences.c.occurrence_type_id,
        func.count().label("n"),
    ).group_by(occurrences.c.occurrence_type_id)
    with engine.connect() as conn:
        return {
            int(row.occurrence_type_id): int(row.n) for row in conn.execute(query)
        }


def delete_occurrence_type(engine: Engine, type_id: int) -> None:
    if occurrence_type_usage_counts(engine).get(int(type_id), 0) > 0:
        raise ValueError(
            "Este tipo já possui histórico. Desative-o em vez de excluir."
        )
    with engine.begin() as conn:
        conn.execute(
            delete(occurrence_types).where(occurrence_types.c.id == int(type_id))
        )


def _save_seizures(
    conn: Connection, occurrence_id: int, seizures: list[dict] | None
) -> None:
    if not seizures:
        return
    now = _now()
    payloads = []
    for raw in seizures:
        item = normalize_seizure(
            raw.get("category", ""),
            raw.get("item", ""),
            raw.get("quantity"),
            raw.get("unit"),
        )
        payloads.append(
            {
                "occurrence_id": int(occurrence_id),
                "category": item["category"],
                "item": item["item"],
                "quantity": item["quantity"],
                "unit": item["unit"],
                "created_at": now,
            }
        )
    if payloads:
        conn.execute(occurrence_seizures.insert(), payloads)


def insert_occurrence(engine: Engine, row: dict) -> int:
    result_id = int(row["result_id"])
    type_id = int(row["occurrence_type_id"])
    seizures = row.get("seizures") or []
    with engine.begin() as conn:
        result = conn.execute(
            occurrences.insert()
            .values(
                result_id=result_id,
                occurrence_type_id=type_id,
                bopm=(row.get("bopm") or "").strip(),
                bopc=(row.get("bopc") or "").strip(),
                observation=(row.get("observation") or "").strip(),
                created_at=_now(),
            )
            .returning(occurrences.c.id)
        )
        occ_id = int(result.scalar_one())
        _save_seizures(conn, occ_id, seizures)
        return occ_id


def update_occurrence(engine: Engine, occurrence_id: int, row: dict) -> None:
    seizures = row.get("seizures") or []
    with engine.begin() as conn:
        updated = conn.execute(
            occurrences.update()
            .where(occurrences.c.id == int(occurrence_id))
            .values(
                result_id=int(row["result_id"]),
                occurrence_type_id=int(row["occurrence_type_id"]),
                bopm=(row.get("bopm") or "").strip(),
                bopc=(row.get("bopc") or "").strip(),
                observation=(row.get("observation") or "").strip(),
            )
        )
        if updated.rowcount == 0:
            raise ValueError("Ocorrência não encontrada.")
        conn.execute(
            delete(occurrence_seizures).where(
                occurrence_seizures.c.occurrence_id == int(occurrence_id)
            )
        )
        _save_seizures(conn, int(occurrence_id), seizures)


def delete_occurrence(engine: Engine, occurrence_id: int) -> None:
    with engine.begin() as conn:
        conn.execute(
            delete(occurrence_seizures).where(
                occurrence_seizures.c.occurrence_id == int(occurrence_id)
            )
        )
        conn.execute(
            delete(occurrences).where(occurrences.c.id == int(occurrence_id))
        )


def load_occurrences(engine: Engine) -> pd.DataFrame:
    query = (
        select(
            occurrences.c.id,
            occurrences.c.result_id,
            occurrences.c.occurrence_type_id,
            occurrences.c.bopm,
            occurrences.c.bopc,
            occurrences.c.observation,
            occurrences.c.created_at,
            resultados.c.data,
            resultados.c.equipe,
            resultados.c.pelotao,
            resultados.c.modalidade,
            occurrence_types.c.code,
            occurrence_types.c.name.label("type_name"),
            occurrence_types.c.kpi_category,
        )
        .select_from(
            occurrences.join(
                resultados, occurrences.c.result_id == resultados.c.id
            ).join(
                occurrence_types,
                occurrences.c.occurrence_type_id == occurrence_types.c.id,
            )
        )
        .order_by(resultados.c.data.desc(), occurrences.c.id.desc())
    )
    with engine.connect() as conn:
        df = pd.read_sql(query, conn)
    if df.empty:
        return df
    df["data"] = pd.to_datetime(df["data"])
    for col in ("bopm", "bopc", "observation"):
        df[col] = df[col].fillna("").astype(str)
    return df


def get_occurrence_seizures(engine: Engine, occurrence_id: int) -> list[dict]:
    query = (
        select(occurrence_seizures)
        .where(occurrence_seizures.c.occurrence_id == int(occurrence_id))
        .order_by(occurrence_seizures.c.id)
    )
    with engine.connect() as conn:
        rows = conn.execute(query).all()
    return [
        {
            "id": int(row.id),
            "category": row.category,
            "item": row.item,
            "quantity": Decimal(str(row.quantity)),
            "unit": row.unit,
        }
        for row in rows
    ]


def load_seizures_map(engine: Engine) -> dict[int, list[dict]]:
    query = select(occurrence_seizures).order_by(occurrence_seizures.c.id)
    mapping: dict[int, list[dict]] = {}
    with engine.connect() as conn:
        for row in conn.execute(query):
            mapping.setdefault(int(row.occurrence_id), []).append(
                {
                    "id": int(row.id),
                    "category": row.category,
                    "item": row.item,
                    "quantity": Decimal(str(row.quantity)),
                    "unit": row.unit,
                }
            )
    return mapping


def list_linked_occurrences(engine: Engine, result_id: int) -> list[dict]:
    query = (
        select(
            occurrences.c.id,
            occurrences.c.bopm,
            occurrence_types.c.code,
            occurrence_types.c.name,
        )
        .select_from(
            occurrences.join(
                occurrence_types,
                occurrences.c.occurrence_type_id == occurrence_types.c.id,
            )
        )
        .where(occurrences.c.result_id == int(result_id))
        .order_by(occurrences.c.id)
    )
    with engine.connect() as conn:
        rows = conn.execute(query).all()
    return [
        {
            "id": int(row.id),
            "code": row.code,
            "name": row.name,
            "bopm": row.bopm or "",
        }
        for row in rows
    ]


def aggregate_member_production(
    engine: Engine,
    start: str | None = None,
    end: str | None = None,
) -> pd.DataFrame:
    df = attach_extra_columns(
        load_data(engine), load_extras_wide(engine), list_indicators(engine)
    )
    if df.empty:
        return df
    if start:
        df = df[df["data"].dt.strftime("%Y-%m-%d") >= start]
    if end:
        df = df[df["data"].dt.strftime("%Y-%m-%d") <= end]
    members_map = load_members_map(engine)
    rows = []
    for _, result in df.iterrows():
        names = members_map.get(int(result["id"]), [])
        score = (
            int(result["abordados"]) * 2
            + int(result["carros"])
            + int(result["motos"])
            + int(result["ocorrencias"]) * 5
        )
        for name in names:
            rows.append(
                {
                    "member_name": name,
                    "services": 1,
                    "abordados": int(result["abordados"]),
                    "carros": int(result["carros"]),
                    "motos": int(result["motos"]),
                    "bopm": int(result["bopm"]),
                    "ocorrencias": int(result["ocorrencias"]),
                    "apoios": int(result.get(APOIOS_SLUG, 0) or 0),
                    "pessoas_presas": int(result.get("pessoas_presas", 0) or 0),
                    "condenados_capturados": int(
                        result.get("condenados_capturados", 0) or 0
                    ),
                    "veiculos_recuperados": int(
                        result.get("veiculos_recuperados", 0) or 0
                    ),
                    "indice_producao": score,
                }
            )
    if not rows:
        return pd.DataFrame()
    out = pd.DataFrame(rows)
    return out.groupby("member_name", as_index=False).sum(numeric_only=True)


def occurrence_kpis(
    engine: Engine,
    start: str | None = None,
    end: str | None = None,
) -> dict[str, int]:
    df = load_occurrences(engine)
    totals = {
        "roubos": 0,
        "furtos": 0,
        "roubos_veiculo": 0,
        "furtos_veiculo": 0,
    }
    if df.empty:
        return totals
    if start:
        df = df[df["data"].dt.strftime("%Y-%m-%d") >= start]
    if end:
        df = df[df["data"].dt.strftime("%Y-%m-%d") <= end]
    mapping = {
        "ROUBO": "roubos",
        "FURTO": "furtos",
        "ROUBO_VEICULO": "roubos_veiculo",
        "FURTO_VEICULO": "furtos_veiculo",
    }
    for category, key in mapping.items():
        totals[key] = int((df["kpi_category"] == category).sum())
    return totals


def seizure_kpis(
    engine: Engine,
    start: str | None = None,
    end: str | None = None,
) -> dict[str, Decimal]:
    occ = load_occurrences(engine)
    totals = {cat: Decimal("0") for cat in SEIZURE_KPI_CATEGORIES}
    if occ.empty:
        return totals
    if start:
        occ = occ[occ["data"].dt.strftime("%Y-%m-%d") >= start]
    if end:
        occ = occ[occ["data"].dt.strftime("%Y-%m-%d") <= end]
    valid_ids = set(occ["id"].astype(int).tolist())
    if not valid_ids:
        return totals
    query = select(
        occurrence_seizures.c.category,
        func.sum(occurrence_seizures.c.quantity).label("total"),
    ).where(
        occurrence_seizures.c.occurrence_id.in_(valid_ids),
        occurrence_seizures.c.category.in_(SEIZURE_KPI_CATEGORIES),
    ).group_by(occurrence_seizures.c.category)
    with engine.connect() as conn:
        for row in conn.execute(query):
            totals[str(row.category)] = Decimal(str(row.total or 0))
    return totals
