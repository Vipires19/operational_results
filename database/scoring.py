"""Cálculo do Índice de Produção. Sem dependência de engine/SQLAlchemy."""

from __future__ import annotations

from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

import pandas as pd

APOIOS_SLUG = "apoios_operacionais"

FIXED_INDEX_METRICS: list[tuple[str, str, Decimal]] = [
    ("abordados", "Abordados", Decimal("2")),
    ("carros", "Carros", Decimal("1")),
    ("motos", "Motos", Decimal("1")),
    ("bopm", "BOPM", Decimal("0")),
    ("ocorrencias", "Ocorrências", Decimal("5")),
    (APOIOS_SLUG, "Apoios Operacionais", Decimal("0")),
    ("pessoas_presas", "Pessoas presas", Decimal("0")),
    ("condenados_capturados", "Condenados capturados", Decimal("0")),
    ("veiculos_recuperados", "Veículos recuperados", Decimal("0")),
]

DEFAULT_INDEX_WEIGHTS = {key: weight for key, _label, weight in FIXED_INDEX_METRICS}
FIXED_INDEX_LABELS = {key: label for key, label, _weight in FIXED_INDEX_METRICS}
FIXED_INDEX_KEYS = [key for key, _label, _weight in FIXED_INDEX_METRICS]


def parse_weight(value) -> Decimal:
    if value is None:
        raise ValueError("Informe um peso numérico maior ou igual a zero.")
    if isinstance(value, bool):
        raise ValueError("Peso inválido.")
    if isinstance(value, float) and (
        value != value or value in (float("inf"), float("-inf"))
    ):
        raise ValueError("Peso inválido.")
    text = str(value).strip().replace(" ", "").replace(",", ".")
    try:
        number = Decimal(text)
    except (InvalidOperation, ValueError) as exc:
        raise ValueError("Peso inválido.") from exc
    if not number.is_finite():
        raise ValueError("Peso inválido.")
    if number < 0:
        raise ValueError("O peso não pode ser negativo.")
    return number.quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)


def calculate_production_index(
    metrics,
    weights: dict[str, Decimal] | None = None,
) -> Decimal:
    """Σ (valor da métrica × peso atual). Fonte única do Índice de Produção."""
    resolved = weights if weights is not None else DEFAULT_INDEX_WEIGHTS
    getter = metrics.get if hasattr(metrics, "get") else None
    total = Decimal("0")
    for key, raw_weight in resolved.items():
        weight = (
            raw_weight
            if isinstance(raw_weight, Decimal)
            else parse_weight(raw_weight)
        )
        if weight == 0:
            continue
        if getter is not None:
            raw_value = getter(key, 0)
        else:
            raw_value = metrics[key] if key in metrics else 0
        try:
            value = Decimal(str(int(raw_value or 0)))
        except (TypeError, ValueError):
            value = Decimal("0")
        total += value * weight
    return total


def add_production_index(
    df: pd.DataFrame,
    weights: dict[str, Decimal] | None = None,
) -> pd.DataFrame:
    out = df.copy()
    resolved = weights if weights is not None else DEFAULT_INDEX_WEIGHTS
    if out.empty:
        out["indice_producao"] = pd.Series(dtype="float64")
        return out
    score = pd.Series(0.0, index=out.index, dtype="float64")
    for key, raw_weight in resolved.items():
        weight = float(
            raw_weight
            if isinstance(raw_weight, Decimal)
            else parse_weight(raw_weight)
        )
        if weight == 0 or key not in out.columns:
            continue
        values = pd.to_numeric(out[key], errors="coerce").fillna(0)
        score = score + values.astype(float) * weight
    out["indice_producao"] = score
    return out
