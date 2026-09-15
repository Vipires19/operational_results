"""Migra registros do SQLite local para PostgreSQL.

Não é executado pelo Streamlit. Rode manualmente após configurar DATABASE_URL.

Uso (na raiz do projeto):

    python scripts/migrate_sqlite_to_postgres.py

Windows (PowerShell):

    $env:DATABASE_URL = "postgresql://USER:PASSWORD@HOST:PORT/DATABASE?sslmode=require"
    python scripts/migrate_sqlite_to_postgres.py
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import pandas as pd
from sqlalchemy import create_engine, func, select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert

from database.connection import (
    DB_PATH,
    create_db_engine,
    index_weights,
    init_schema,
    operational_indicators,
    read_database_url,
    result_indicator_values,
    resultados,
)


def load_dotenv_file(path: Path) -> None:
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, _, value = stripped.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Migra resultados do SQLite local para PostgreSQL."
    )
    parser.add_argument(
        "--sqlite",
        type=Path,
        default=DB_PATH,
        help="Caminho do arquivo SQLite de origem.",
    )
    return parser.parse_args()


def normalize_rows(df: pd.DataFrame) -> list[dict]:
    rows = []
    for record in df.to_dict(orient="records"):
        data = record.get("data")
        if hasattr(data, "strftime"):
            data = data.strftime("%Y-%m-%d")
        else:
            data = str(data)[:10]

        rows.append(
            {
                "id": int(record["id"]),
                "data": data,
                "modalidade": str(record.get("modalidade") or "").strip(),
                "equipe": str(record.get("equipe") or "").strip(),
                "pelotao": str(record.get("pelotao") or "").strip(),
                "abordados": int(record.get("abordados") or 0),
                "carros": int(record.get("carros") or 0),
                "motos": int(record.get("motos") or 0),
                "bopm": int(record.get("bopm") or 0),
                "ocorrencias": int(record.get("ocorrencias") or 0),
                "observacao": record.get("observacao") or "",
                "created_at": str(
                    record.get("created_at")
                    or pd.Timestamp.now().isoformat(timespec="seconds")
                ),
            }
        )
    return rows


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8")
        except Exception:
            pass

    load_dotenv_file(ROOT / ".env")
    args = parse_args()
    sqlite_path = args.sqlite.resolve()

    if not sqlite_path.exists():
        print(f"SQLite não encontrado: {sqlite_path}")
        return 1

    database_url = read_database_url()
    if not database_url:
        print(
            "DATABASE_URL não configurada. "
            "Defina no ambiente ou no arquivo .env."
        )
        return 1

    sqlite_engine = create_engine(f"sqlite:///{sqlite_path.as_posix()}")
    try:
        source = pd.read_sql("SELECT * FROM resultados ORDER BY id", sqlite_engine)
        try:
            src_indicators = pd.read_sql(
                "SELECT * FROM operational_indicators ORDER BY id", sqlite_engine
            )
        except Exception:
            src_indicators = pd.DataFrame()
        try:
            src_values = pd.read_sql(
                "SELECT * FROM result_indicator_values ORDER BY id", sqlite_engine
            )
        except Exception:
            src_values = pd.DataFrame()
        try:
            src_weights = pd.read_sql("SELECT * FROM index_weights", sqlite_engine)
        except Exception:
            src_weights = pd.DataFrame()
    except Exception as exc:
        print(f"Falha ao ler o SQLite: {exc}")
        return 1
    finally:
        sqlite_engine.dispose()

    try:
        pg_engine = create_db_engine(database_url)
        if pg_engine.dialect.name != "postgresql":
            print("DATABASE_URL não aponta para PostgreSQL.")
            return 1
        init_schema(pg_engine)
    except Exception as exc:
        print("Falha ao conectar no PostgreSQL. Verifique DATABASE_URL.")
        print(f"Detalhe: {type(exc).__name__}")
        return 1

    if source.empty and src_indicators.empty:
        print("Nenhum registro encontrado no SQLite.")
        pg_engine.dispose()
        return 0

    rows = normalize_rows(source) if not source.empty else []

    try:
        with pg_engine.begin() as conn:
            before = conn.execute(
                select(func.count()).select_from(resultados)
            ).scalar_one()

            if rows:
                conn.execute(
                    pg_insert(resultados)
                    .values(rows)
                    .on_conflict_do_nothing(index_elements=["id"])
                )

            after = conn.execute(
                select(func.count()).select_from(resultados)
            ).scalar_one()

            if rows:
                conn.execute(
                    text(
                        "SELECT setval("
                        "pg_get_serial_sequence('resultados', 'id'), "
                        "COALESCE((SELECT MAX(id) FROM resultados), 1)"
                        ")"
                    )
                )

            id_map = {}
            if not src_indicators.empty:
                existing = {
                    row.slug: int(row.id)
                    for row in conn.execute(
                        select(
                            operational_indicators.c.id,
                            operational_indicators.c.slug,
                        )
                    )
                }
                for record in src_indicators.to_dict(orient="records"):
                    slug = str(record["slug"])
                    old_id = int(record["id"])
                    if slug in existing:
                        id_map[old_id] = existing[slug]
                        continue
                    inserted = conn.execute(
                        operational_indicators.insert()
                        .values(
                            name=record["name"],
                            slug=slug,
                            active=int(record.get("active") or 1),
                            created_at=str(
                                record.get("created_at")
                                or pd.Timestamp.now().isoformat(timespec="seconds")
                            ),
                        )
                        .returning(operational_indicators.c.id)
                    )
                    new_id = int(inserted.scalar_one())
                    id_map[old_id] = new_id
                    existing[slug] = new_id

            if not src_values.empty:
                value_rows = []
                for record in src_values.to_dict(orient="records"):
                    old_ind = int(record["indicator_id"])
                    if old_ind not in id_map:
                        continue
                    value_rows.append(
                        {
                            "result_id": int(record["result_id"]),
                            "indicator_id": id_map[old_ind],
                            "value": int(record.get("value") or 0),
                            "created_at": str(
                                record.get("created_at")
                                or pd.Timestamp.now().isoformat(timespec="seconds")
                            ),
                        }
                    )
                if value_rows:
                    conn.execute(
                        pg_insert(result_indicator_values)
                        .values(value_rows)
                        .on_conflict_do_nothing(
                            index_elements=["result_id", "indicator_id"]
                        )
                    )

            if not src_weights.empty:
                weight_rows = []
                for record in src_weights.to_dict(orient="records"):
                    key = str(record.get("metric_key") or "").strip()
                    if not key:
                        continue
                    weight_rows.append(
                        {
                            "metric_key": key,
                            "weight": record.get("weight") or 0,
                            "updated_at": str(
                                record.get("updated_at")
                                or pd.Timestamp.now().isoformat(timespec="seconds")
                            ),
                        }
                    )
                for row in weight_rows:
                    conn.execute(
                        pg_insert(index_weights)
                        .values(row)
                        .on_conflict_do_update(
                            index_elements=["metric_key"],
                            set_={
                                "weight": row["weight"],
                                "updated_at": row["updated_at"],
                            },
                        )
                    )
    except Exception as exc:
        print("Falha ao inserir registros no PostgreSQL.")
        print(f"Detalhe: {type(exc).__name__}: {exc}")
        return 1
    finally:
        pg_engine.dispose()

    inserted = int(after) - int(before)
    skipped = len(rows) - inserted
    print(f"Registros no SQLite: {len(rows)}")
    print(f"Migrados: {inserted}")
    print(f"Ignorados (já existiam): {skipped}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
