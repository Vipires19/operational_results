"""Contabilização e identidade do efetivo na produção individual."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import pandas as pd

from database.connection import create_db_engine, init_schema
from database.repository import (
    APOIOS_SLUG,
    aggregate_member_production,
    attach_extra_columns,
    coerce_members,
    create_occurrence_type,
    format_members,
    get_member_production,
    get_result_members,
    insert_occurrence,
    insert_result,
    list_indicators,
    load_data,
    load_extras_wide,
    load_members_map,
    normalize_member_name,
    parse_members,
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


def _row(production: pd.DataFrame, name: str) -> pd.Series:
    matched = production[production["member_name"] == name]
    if matched.empty:
        raise AssertionError(f"{name} não apareceu no ranking: {production}")
    return matched.iloc[0]


class NormalizeMemberNameTests(unittest.TestCase):
    def test_trim_upper_collapse_spaces(self):
        self.assertEqual(normalize_member_name("  cb   paulino  "), "CB PAULINO")
        self.assertEqual(normalize_member_name("cb paulino"), "CB PAULINO")
        self.assertEqual(normalize_member_name(" CB PAULINO "), "CB PAULINO")
        self.assertEqual(normalize_member_name("CB  PAULINO"), "CB PAULINO")
        self.assertEqual(normalize_member_name(""), "")
        self.assertEqual(normalize_member_name("   "), "")

    def test_rank_remains_part_of_identity(self):
        self.assertEqual(normalize_member_name("CB MORETTO"), "CB MORETTO")
        self.assertEqual(normalize_member_name("SD MORETTO"), "SD MORETTO")
        self.assertNotEqual(
            normalize_member_name("CB MORETTO"),
            normalize_member_name("SD MORETTO"),
        )


class ParseMembersTests(unittest.TestCase):
    def test_split_and_preserve_order(self):
        self.assertEqual(
            parse_members(
                "TEN CARVALHO / SGT SILVA / CB PAULINO / SD BATISTA"
            ),
            ["TEN CARVALHO", "SGT SILVA", "CB PAULINO", "SD BATISTA"],
        )

    def test_dedupe_same_result(self):
        self.assertEqual(
            parse_members("CB PAULINO / SD BATISTA / CB PAULINO"),
            ["CB PAULINO", "SD BATISTA"],
        )

    def test_newlines_and_empty_parts(self):
        self.assertEqual(
            parse_members("\nCB PAULINO\n\n / / SD BATISTA / "),
            ["CB PAULINO", "SD BATISTA"],
        )

    def test_coerce_list(self):
        self.assertEqual(
            coerce_members([" cb paulino ", "SD BATISTA", "CB  PAULINO"]),
            ["CB PAULINO", "SD BATISTA"],
        )

    def test_format_members_uses_same_rule(self):
        self.assertEqual(
            format_members([" cb  paulino", "SD BATISTA", "CB PAULINO"]),
            "CB PAULINO / SD BATISTA",
        )


class MemberProductionTests(unittest.TestCase):
    def test_required_scenario_participation_not_division(self):
        df = pd.DataFrame(
            [
                {
                    "id": 1,
                    "abordados": 10,
                    "carros": 2,
                    "motos": 1,
                    "bopm": 0,
                    "ocorrencias": 1,
                    "pessoas_presas": 0,
                    "condenados_capturados": 0,
                    "veiculos_recuperados": 0,
                    APOIOS_SLUG: 0,
                },
                {
                    "id": 2,
                    "abordados": 5,
                    "carros": 1,
                    "motos": 2,
                    "bopm": 0,
                    "ocorrencias": 0,
                    "pessoas_presas": 0,
                    "condenados_capturados": 0,
                    "veiculos_recuperados": 0,
                    APOIOS_SLUG: 0,
                },
            ]
        )
        members_map = {
            1: ["CB PAULINO", "SD BATISTA"],
            2: ["CB PAULINO", "SD GARCIA"],
        }
        production = get_member_production(df, members_map)

        paulino = _row(production, "CB PAULINO")
        self.assertEqual(int(paulino["services"]), 2)
        self.assertEqual(int(paulino["abordados"]), 15)
        self.assertEqual(int(paulino["carros"]), 3)
        self.assertEqual(int(paulino["motos"]), 3)
        self.assertEqual(int(paulino["ocorrencias"]), 1)
        self.assertEqual(int(paulino["indice_producao"]), 41)

        batista = _row(production, "SD BATISTA")
        self.assertEqual(int(batista["services"]), 1)
        self.assertEqual(int(batista["abordados"]), 10)
        self.assertEqual(int(batista["carros"]), 2)
        self.assertEqual(int(batista["motos"]), 1)
        self.assertEqual(int(batista["ocorrencias"]), 1)
        self.assertEqual(int(batista["indice_producao"]), 28)

        garcia = _row(production, "SD GARCIA")
        self.assertEqual(int(garcia["services"]), 1)
        self.assertEqual(int(garcia["abordados"]), 5)
        self.assertEqual(int(garcia["carros"]), 1)
        self.assertEqual(int(garcia["motos"]), 2)
        self.assertEqual(int(garcia["ocorrencias"]), 0)
        self.assertEqual(int(garcia["indice_producao"]), 13)

        total_company = int(df["abordados"].sum())
        self.assertEqual(total_company, 15)
        self.assertGreater(int(production["abordados"].sum()), total_company)

    def test_normalization_collapses_safe_variants(self):
        df = pd.DataFrame(
            [
                {"id": 1, "abordados": 10, "carros": 0, "motos": 0, "ocorrencias": 0},
                {"id": 2, "abordados": 5, "carros": 0, "motos": 0, "ocorrencias": 0},
                {"id": 3, "abordados": 1, "carros": 0, "motos": 0, "ocorrencias": 0},
            ]
        )
        members_map = {
            1: ["CB PAULINO"],
            2: [" cb paulino "],
            3: ["CB   PAULINO"],
        }
        production = get_member_production(df, members_map)
        self.assertEqual(list(production["member_name"]), ["CB PAULINO"])
        self.assertEqual(int(production.iloc[0]["services"]), 3)
        self.assertEqual(int(production.iloc[0]["abordados"]), 16)

    def test_rank_keeps_distinct_people(self):
        df = pd.DataFrame(
            [
                {"id": 1, "abordados": 4, "carros": 0, "motos": 0, "ocorrencias": 0},
                {"id": 2, "abordados": 7, "carros": 0, "motos": 0, "ocorrencias": 0},
            ]
        )
        production = get_member_production(
            df, {1: ["CB MORETTO"], 2: ["SD MORETTO"]}
        )
        names = set(production["member_name"])
        self.assertEqual(names, {"CB MORETTO", "SD MORETTO"})
        self.assertEqual(int(_row(production, "CB MORETTO")["abordados"]), 4)
        self.assertEqual(int(_row(production, "SD MORETTO")["abordados"]), 7)

    def test_duplicate_in_same_result_counts_once(self):
        df = pd.DataFrame(
            [{"id": 10, "abordados": 10, "carros": 2, "motos": 1, "ocorrencias": 1}]
        )
        production = get_member_production(
            df, {10: ["CB PAULINO", "SD BATISTA", "CB PAULINO", " cb paulino "]}
        )
        paulino = _row(production, "CB PAULINO")
        self.assertEqual(int(paulino["services"]), 1)
        self.assertEqual(int(paulino["abordados"]), 10)
        self.assertEqual(int(paulino["indice_producao"]), 28)
        self.assertEqual(len(production), 2)

    def test_join_multiplication_does_not_inflate_metrics(self):
        # Simula um DataFrame já inflado por JOIN de ocorrências/apreensões.
        duplicated = pd.DataFrame(
            [
                {"id": 1, "abordados": 10, "carros": 2, "motos": 1, "ocorrencias": 1},
                {"id": 1, "abordados": 10, "carros": 2, "motos": 1, "ocorrencias": 1},
                {"id": 1, "abordados": 10, "carros": 2, "motos": 1, "ocorrencias": 1},
            ]
        )
        production = get_member_production(duplicated, {1: ["CB PAULINO"]})
        paulino = _row(production, "CB PAULINO")
        self.assertEqual(int(paulino["services"]), 1)
        self.assertEqual(int(paulino["abordados"]), 10)
        self.assertEqual(int(paulino["indice_producao"]), 28)

    def test_services_are_distinct_results_not_extra_rows(self):
        df = pd.DataFrame(
            [{"id": 10, "abordados": 10, "carros": 2, "motos": 1, "ocorrencias": 1}]
        )
        production = get_member_production(df, {10: ["CB PAULINO"]})
        self.assertEqual(int(production.iloc[0]["services"]), 1)

    def test_ambiguous_pm_variant_is_not_merged(self):
        df = pd.DataFrame(
            [
                {"id": 1, "abordados": 3, "carros": 0, "motos": 0, "ocorrencias": 0},
                {"id": 2, "abordados": 4, "carros": 0, "motos": 0, "ocorrencias": 0},
            ]
        )
        production = get_member_production(
            df, {1: ["CB PAULINO"], 2: ["CB PM PAULINO"]}
        )
        self.assertEqual(set(production["member_name"]), {"CB PAULINO", "CB PM PAULINO"})


class MemberPersistenceTests(unittest.TestCase):
    def setUp(self):
        self.engine, self.path = _engine()

    def tearDown(self):
        self.engine.dispose()
        Path(self.path).unlink(missing_ok=True)

    def test_insert_normalizes_and_dedupes(self):
        result_id = insert_result(
            self.engine,
            _payload(efetivo="CB PAULINO / SD BATISTA / CB PAULINO /  cb  paulino "),
        )
        members = get_result_members(self.engine, result_id)
        self.assertEqual(members, ["CB PAULINO", "SD BATISTA"])

    def test_card_order_is_launch_order(self):
        result_id = insert_result(
            self.engine,
            _payload(
                efetivo="TEN CARVALHO / SGT SILVA / CB PAULINO / SD BATISTA"
            ),
        )
        self.assertEqual(
            get_result_members(self.engine, result_id),
            ["TEN CARVALHO", "SGT SILVA", "CB PAULINO", "SD BATISTA"],
        )
        self.assertEqual(
            load_members_map(self.engine)[result_id],
            ["TEN CARVALHO", "SGT SILVA", "CB PAULINO", "SD BATISTA"],
        )

    def test_occurrences_and_seizures_do_not_multiply_production(self):
        apoios = next(
            item for item in list_indicators(self.engine) if item["slug"] == APOIOS_SLUG
        )
        rid = insert_result(
            self.engine,
            _payload(
                abordados=10,
                carros=2,
                motos=1,
                ocorrencias=1,
                efetivo="CB PAULINO / SD BATISTA",
                extras={apoios["id"]: 2},
            ),
        )
        occ_type = create_occurrence_type(self.engine, "T01", "TESTE")
        insert_occurrence(
            self.engine,
            {
                "result_id": rid,
                "occurrence_type_id": occ_type["id"],
                "bopm": "1",
                "seizures": [
                    {"category": "ARMA", "item": "PISTOLA", "quantity": 1, "unit": "UN"},
                    {"category": "ARMA", "item": "REVOLVER", "quantity": 1, "unit": "UN"},
                ],
            },
        )
        insert_occurrence(
            self.engine,
            {
                "result_id": rid,
                "occurrence_type_id": occ_type["id"],
                "bopm": "2",
                "seizures": [
                    {"category": "DROGA", "item": "MACONHA", "quantity": 10, "unit": "G"},
                    {"category": "MUNICAO", "item": "9MM", "quantity": 5, "unit": "UN"},
                ],
            },
        )
        production = aggregate_member_production(self.engine)
        paulino = _row(production, "CB PAULINO")
        self.assertEqual(int(paulino["services"]), 1)
        self.assertEqual(int(paulino["abordados"]), 10)
        self.assertEqual(int(paulino["indice_producao"]), 28)
        self.assertEqual(int(paulino[APOIOS_SLUG]), 2)

        extras = attach_extra_columns(
            load_data(self.engine),
            load_extras_wide(self.engine),
            list_indicators(self.engine),
        )
        self.assertEqual(len(extras), 1)
        self.assertEqual(int(extras.iloc[0]["abordados"]), 10)


if __name__ == "__main__":
    unittest.main()
