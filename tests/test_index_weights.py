"""Índice de produção configurável e regressão da fórmula inicial."""

from __future__ import annotations

import tempfile
import unittest
from decimal import Decimal
from pathlib import Path

import pandas as pd

from database.connection import create_db_engine, init_schema
from database.repository import (
    DEFAULT_INDEX_WEIGHTS,
    add_production_index,
    aggregate_member_production,
    calculate_production_index,
    create_indicator,
    create_occurrence_type,
    get_member_production,
    insert_occurrence,
    insert_result,
    list_index_weight_items,
    load_index_weights,
    parse_weight,
    save_index_weights,
    set_indicator_active,
)


def _engine():
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp.close()
    engine = create_db_engine(f"sqlite:///{Path(tmp.name).as_posix()}")
    init_schema(engine)
    return engine, tmp.name


def _payload(**overrides) -> dict:
    row = {
        "data": "2026-01-10",
        "modalidade": "FT",
        "equipe": "FORÇA TÁTICA 3034",
        "pelotao": "1° PELOTÃO",
        "abordados": 0,
        "carros": 0,
        "motos": 0,
        "bopm": 0,
        "ocorrencias": 0,
        "pessoas_presas": 0,
        "condenados_capturados": 0,
        "veiculos_recuperados": 0,
        "observacao": "",
        "efetivo": "",
    }
    row.update(overrides)
    return row


class WeightParsingTests(unittest.TestCase):
    def test_accepts_decimal_and_rejects_invalid(self):
        self.assertEqual(parse_weight("2.5"), Decimal("2.5000"))
        self.assertEqual(parse_weight(0), Decimal("0.0000"))
        with self.assertRaises(ValueError):
            parse_weight(-1)
        with self.assertRaises(ValueError):
            parse_weight("abc")
        with self.assertRaises(ValueError):
            parse_weight(float("nan"))
        with self.assertRaises(ValueError):
            parse_weight(float("inf"))


class IndexFormulaTests(unittest.TestCase):
    def test_default_formula_regression(self):
        metrics = {
            "abordados": 10,
            "carros": 2,
            "motos": 1,
            "ocorrencias": 1,
        }
        self.assertEqual(
            calculate_production_index(metrics, DEFAULT_INDEX_WEIGHTS),
            Decimal("28"),
        )

    def test_weight_change(self):
        weights = dict(DEFAULT_INDEX_WEIGHTS)
        weights["abordados"] = Decimal("3")
        weights["ocorrencias"] = Decimal("10")
        metrics = {
            "abordados": 10,
            "carros": 2,
            "motos": 1,
            "ocorrencias": 1,
        }
        self.assertEqual(calculate_production_index(metrics, weights), Decimal("43"))

    def test_dynamic_indicator_decimal_weight(self):
        weights = dict(DEFAULT_INDEX_WEIGHTS)
        weights["teste_score"] = Decimal("7.5")
        metrics = {"abordados": 0, "carros": 0, "motos": 0, "ocorrencias": 0, "teste_score": 2}
        self.assertEqual(calculate_production_index(metrics, weights), Decimal("15.0"))

    def test_zero_weight_does_not_score(self):
        weights = dict(DEFAULT_INDEX_WEIGHTS)
        weights["teste_score"] = Decimal("0")
        metrics = {"teste_score": 100, "abordados": 0, "carros": 0, "motos": 0, "ocorrencias": 0}
        self.assertEqual(calculate_production_index(metrics, weights), Decimal("0"))

    def test_dataframe_uses_same_rule(self):
        df = pd.DataFrame(
            [{"abordados": 10, "carros": 2, "motos": 1, "ocorrencias": 1}]
        )
        scored = add_production_index(df, DEFAULT_INDEX_WEIGHTS)
        self.assertEqual(float(scored.iloc[0]["indice_producao"]), 28.0)


class IndexPersistenceTests(unittest.TestCase):
    def setUp(self):
        self.engine, self.path = _engine()

    def tearDown(self):
        self.engine.dispose()
        Path(self.path).unlink(missing_ok=True)

    def test_seed_is_idempotent_and_matches_legacy(self):
        first = load_index_weights(self.engine)
        second = load_index_weights(self.engine)
        self.assertEqual(first["abordados"], Decimal("2"))
        self.assertEqual(first["carros"], Decimal("1"))
        self.assertEqual(first["motos"], Decimal("1"))
        self.assertEqual(first["ocorrencias"], Decimal("5"))
        self.assertEqual(first["bopm"], Decimal("0"))
        self.assertEqual(first, second)
        keys = [item["metric_key"] for item in list_index_weight_items(self.engine)]
        self.assertEqual(len(keys), len(set(keys)))

    def test_save_is_transactional_and_recalculates(self):
        save_index_weights(
            self.engine,
            {
                "abordados": 3,
                "carros": 1,
                "motos": 1,
                "ocorrencias": 10,
            },
        )
        weights = load_index_weights(self.engine)
        metrics = {
            "abordados": 10,
            "carros": 2,
            "motos": 1,
            "ocorrencias": 1,
        }
        self.assertEqual(calculate_production_index(metrics, weights), Decimal("43"))

    def test_dynamic_indicator_weight_and_inactive_history(self):
        created = create_indicator(self.engine, "Teste Score")
        save_index_weights(self.engine, {created["slug"]: Decimal("7.5")})
        rid = insert_result(
            self.engine,
            _payload(
                abordados=0,
                extras={created["id"]: 2},
                efetivo="CB PAULINO",
            ),
        )
        self.assertTrue(rid)
        set_indicator_active(self.engine, created["id"], False)
        production = aggregate_member_production(self.engine)
        row = production[production["member_name"] == "CB PAULINO"].iloc[0]
        self.assertEqual(float(row["indice_producao"]), 15.0)
        self.assertEqual(int(row[created["slug"]]), 2)

    def test_member_production_follows_new_weights(self):
        insert_result(
            self.engine,
            _payload(
                abordados=10,
                carros=2,
                motos=1,
                ocorrencias=1,
                pessoas_presas=2,
                efetivo="CB PAULINO / SD BATISTA",
            ),
        )
        insert_result(
            self.engine,
            _payload(
                data="2026-01-11",
                abordados=5,
                carros=1,
                motos=2,
                ocorrencias=0,
                pessoas_presas=1,
                efetivo="CB PAULINO / SD GARCIA",
            ),
        )
        production = aggregate_member_production(self.engine)
        paulino = production[production["member_name"] == "CB PAULINO"].iloc[0]
        self.assertEqual(int(paulino["services"]), 2)
        self.assertEqual(float(paulino["indice_producao"]), 41.0)

        save_index_weights(self.engine, {"pessoas_presas": 10})
        production = aggregate_member_production(self.engine)
        paulino = production[production["member_name"] == "CB PAULINO"].iloc[0]
        batista = production[production["member_name"] == "SD BATISTA"].iloc[0]
        garcia = production[production["member_name"] == "SD GARCIA"].iloc[0]
        self.assertEqual(float(paulino["indice_producao"]), 71.0)
        self.assertEqual(float(batista["indice_producao"]), 48.0)
        self.assertEqual(float(garcia["indice_producao"]), 23.0)

    def test_join_does_not_multiply_with_weighted_index(self):
        created = create_indicator(self.engine, "Teste Extra")
        rid = insert_result(
            self.engine,
            _payload(
                abordados=10,
                carros=2,
                motos=1,
                ocorrencias=1,
                efetivo="CB PAULINO / SD BATISTA",
                extras={created["id"]: 3},
            ),
        )
        occ_type = create_occurrence_type(self.engine, "T99", "TESTE")
        insert_occurrence(
            self.engine,
            {
                "result_id": rid,
                "occurrence_type_id": occ_type["id"],
                "seizures": [
                    {"category": "ARMA", "item": "A", "quantity": 1, "unit": "UN"},
                    {"category": "ARMA", "item": "B", "quantity": 1, "unit": "UN"},
                ],
            },
        )
        insert_occurrence(
            self.engine,
            {
                "result_id": rid,
                "occurrence_type_id": occ_type["id"],
                "seizures": [
                    {"category": "MUNICAO", "item": "C", "quantity": 1, "unit": "UN"},
                ],
            },
        )
        production = aggregate_member_production(self.engine)
        paulino = production[production["member_name"] == "CB PAULINO"].iloc[0]
        self.assertEqual(int(paulino["services"]), 1)
        self.assertEqual(int(paulino["abordados"]), 10)
        self.assertEqual(float(paulino["indice_producao"]), 28.0)


class MemberIndexVectorTests(unittest.TestCase):
    def test_weighted_participation_without_engine(self):
        df = pd.DataFrame(
            [
                {
                    "id": 1,
                    "abordados": 10,
                    "carros": 2,
                    "motos": 1,
                    "ocorrencias": 1,
                    "pessoas_presas": 2,
                },
                {
                    "id": 2,
                    "abordados": 5,
                    "carros": 1,
                    "motos": 2,
                    "ocorrencias": 0,
                    "pessoas_presas": 1,
                },
            ]
        )
        members = {
            1: ["CB PAULINO", "SD BATISTA"],
            2: ["CB PAULINO", "SD GARCIA"],
        }
        weights = dict(DEFAULT_INDEX_WEIGHTS)
        weights["pessoas_presas"] = Decimal("10")
        production = get_member_production(df, members, weights=weights)
        paulino = production[production["member_name"] == "CB PAULINO"].iloc[0]
        self.assertEqual(int(paulino["services"]), 2)
        self.assertEqual(float(paulino["indice_producao"]), 71.0)


if __name__ == "__main__":
    unittest.main()
