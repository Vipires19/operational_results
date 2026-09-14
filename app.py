import logging
from datetime import date, datetime

import pandas as pd
import streamlit as st

from charts.dashboard import area_daily, horizontal_bar
from database.connection import backend_label, get_engine
from database.repository import (
    APOIOS_SLUG,
    KPI_CATEGORY_LABELS,
    PRODUCTIVITY_COLS,
    RESERVED_SLUGS,
    SEIZURE_CATEGORIES,
    assert_unique_columns,
    attach_extra_columns,
    count_occurrences_for_result,
    dynamic_catalog,
    create_indicator,
    create_occurrence_type,
    delete_indicator,
    delete_occurrence,
    delete_occurrence_type,
    delete_result,
    format_members,
    get_member_production,
    get_occurrence_seizures,
    get_result_extra_values,
    get_result_members,
    indicator_usage_counts,
    insert_occurrence,
    insert_many,
    insert_result,
    list_active_indicators,
    list_indicators,
    list_linked_occurrences,
    list_occurrence_types,
    list_results_by_date,
    load_data,
    load_extras_wide,
    load_members_map,
    load_occurrences,
    load_occurrences_map,
    load_seizure_summary_by_result,
    occurrence_type_usage_counts,
    set_indicator_active,
    set_occurrence_type_active,
    update_occurrence,
    update_result,
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

METRIC_COLS = ["abordados", "carros", "motos", "bopm", "ocorrencias"]
PRODUCTIVITY_LABELS = {
    "pessoas_presas": "Pessoas presas",
    "condenados_capturados": "Condenados capturados",
    "veiculos_recuperados": "Veículos recuperados",
}

INDICATOR_LABELS = {
    "indice_producao": "Índice de produção",
    "abordados": "Abordados",
    "carros": "Carros",
    "motos": "Motos",
    "bopm": "BOPM",
    "ocorrencias": "Ocorrências",
}

COLUMN_LABELS = {
    "id": "ID",
    "data": "Data",
    "modalidade": "Modalidade",
    "equipe": "Equipe",
    "pelotao": "Pelotão",
    "abordados": "Abordados",
    "carros": "Carros",
    "motos": "Motos",
    "bopm": "BOPM",
    "ocorrencias": "Ocorrências",
    "pessoas_presas": "Pessoas presas",
    "condenados_capturados": "Condenados capturados",
    "veiculos_recuperados": "Veículos recuperados",
    "efetivo": "Efetivo",
    "indice_producao": "Índice",
    "observacao": "Observação",
    "obs": "Obs.",
}

PELOTOES_PADRAO = ["1° PELOTÃO", "2° PELOTÃO"]
MODALIDADES_PADRAO = ["FT", "ROCAM"]

st.set_page_config(
    page_title="Resultado Operacional",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded",
)

CSS = """
<style>
    .block-container {
        padding-top: 1.2rem;
        padding-bottom: 2rem;
        max-width: 1400px;
    }
    [data-testid="stMetric"] {
        background: var(--secondary-background-color);
        border: 1px solid rgba(148, 163, 184, 0.35);
        border-radius: 10px;
        padding: 0.7rem 0.9rem;
    }
    [data-testid="stMetricValue"] {
        font-size: 1.65rem;
        color: var(--text-color);
    }
    [data-testid="stMetricLabel"] {
        color: var(--text-color);
        opacity: 0.78;
    }
    .small-muted {
        color: var(--text-color);
        opacity: 0.7;
        font-size: .9rem;
    }
</style>
"""

st.markdown(CSS, unsafe_allow_html=True)


@st.cache_resource
def get_cached_engine():
    return get_engine()


def fmt_int(value) -> str:
    return f"{int(value):,}".replace(",", ".")


def fmt_date_long(value) -> str:
    day = value.date() if hasattr(value, "date") else value
    meses = (
        "janeiro",
        "fevereiro",
        "março",
        "abril",
        "maio",
        "junho",
        "julho",
        "agosto",
        "setembro",
        "outubro",
        "novembro",
        "dezembro",
    )
    return f"{day.day} de {meses[day.month - 1]} de {day.year}"


def fmt_kg_from_grams(grams) -> str:
    kg = float(grams) / 1000
    return f"{kg:.3f}".replace(".", ",") + " kg"


def iter_chunks(items: list, size: int = 3):
    for i in range(0, len(items), size):
        yield items[i : i + size]


def metric_lines(pairs: list[tuple[str, str]]) -> str:
    return "  \n".join(f"{label}: **{value}**" for label, value in pairs)


def production_score(df: pd.DataFrame) -> pd.Series:
    """
    Índice simples de produção para ranking.

    Pesos atuais:
    - Abordados: x2
    - Carros: x1
    - Motos: x1
    - Ocorrências: x5

    O BOPM permanece como indicador individual,
    mas não entra no índice atualmente.
    """
    return (
        df["abordados"] * 2
        + df["carros"] * 1
        + df["motos"] * 1
        + df["ocorrencias"] * 5
    )


def add_score(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    if out.empty:
        out["indice_producao"] = pd.Series(dtype="int64")
        return out
    out["indice_producao"] = production_score(out)
    return out


def filtered_data(df, start, end, modalidades, pelotoes, equipes):
    if df.empty:
        return df.copy()

    out = df[(df["data"].dt.date >= start) & (df["data"].dt.date <= end)].copy()

    if modalidades:
        out = out[out["modalidade"].isin(modalidades)]
    if pelotoes:
        out = out[out["pelotao"].isin(pelotoes)]
    if equipes:
        out = out[out["equipe"].isin(equipes)]

    return out


def plot_chart(fig):
    st.plotly_chart(fig, width="stretch")


def number_column(label: str) -> st.column_config.NumberColumn:
    return st.column_config.NumberColumn(label, format="%d")


def unique_keep_order(items: list[str]) -> list[str]:
    seen = set()
    ordered = []
    for item in items:
        if item in seen:
            continue
        seen.add(item)
        ordered.append(item)
    return ordered


def extra_slugs(catalog: list[dict]) -> list[str]:
    return unique_keep_order([item["slug"] for item in dynamic_catalog(catalog)])


def chart_labels(catalog: list[dict]) -> dict[str, str]:
    labels = dict(INDICATOR_LABELS)
    labels.update(PRODUCTIVITY_LABELS)
    for item in catalog:
        if item["slug"] not in RESERVED_SLUGS:
            labels[item["slug"]] = item["name"]
    return labels


def chart_keys(catalog: list[dict], include_index: bool = True) -> list[str]:
    keys = []
    if include_index:
        keys.append("indice_producao")
    keys.extend(METRIC_COLS)
    keys.extend(PRODUCTIVITY_COLS)
    keys.extend(extra_slugs(catalog))
    return unique_keep_order(keys)


def table_config(columns: list[str], catalog: list[dict] | None = None) -> dict:
    extra = set(extra_slugs(catalog or []))
    config = {}
    for col in columns:
        label = COLUMN_LABELS.get(col, col)
        if col in extra:
            name = next((i["name"] for i in (catalog or []) if i["slug"] == col), col)
            config[col] = number_column(name)
        elif col in METRIC_COLS or col in PRODUCTIVITY_COLS or col == "indice_producao":
            config[col] = number_column(label)
        elif col == "id":
            config[col] = number_column(label)
        elif col == "obs":
            config[col] = st.column_config.TextColumn("Obs.", width="small")
        else:
            config[col] = st.column_config.TextColumn(label)
    return config


def obs_flag(series: pd.Series) -> pd.Series:
    return series.fillna("").astype(str).str.strip().map(lambda text: "📝" if text else "")


def show_kpi_row(f: pd.DataFrame) -> None:
    totals = {col: int(f[col].sum()) if not f.empty else 0 for col in METRIC_COLS}
    indice = int(production_score(f).sum()) if not f.empty else 0
    n_equipes = int(f["equipe"].nunique()) if not f.empty else 0
    n_dias = int(f["data"].dt.date.nunique()) if not f.empty else 0
    media_diaria = int(round(indice / n_dias)) if n_dias else 0

    cols = st.columns(6)
    cols[0].metric("Abordados", fmt_int(totals["abordados"]))
    cols[1].metric("Carros", fmt_int(totals["carros"]))
    cols[2].metric("Motos", fmt_int(totals["motos"]))
    cols[3].metric("BOPM", fmt_int(totals["bopm"]))
    cols[4].metric("Ocorrências", fmt_int(totals["ocorrencias"]))
    cols[5].metric("Índice de produção", fmt_int(indice))

    st.caption(
        f"{n_equipes} equipe(s) · {n_dias} dia(s) no período · "
        f"média diária do índice: **{fmt_int(media_diaria)}**"
    )


def aggregate(df: pd.DataFrame, by: str, slugs: list[str]) -> pd.DataFrame:
    assert_unique_columns(df, "aggregate:entrada")
    cols = unique_keep_order(
        [c for c in [*METRIC_COLS, *PRODUCTIVITY_COLS, *slugs] if c in df.columns]
    )
    grouped = df.groupby(by, as_index=False)[cols].sum()
    assert_unique_columns(grouped, "aggregate:saida")
    return add_score(grouped)


def ensure_metric_column(df: pd.DataFrame, metric: str) -> pd.DataFrame:
    assert_unique_columns(df, "ensure_metric_column")
    out = df.copy()
    if metric not in out.columns:
        out[metric] = 0
    assert_unique_columns(out, "ensure_metric_column:saida")
    return out


def show_dashboard(engine, df: pd.DataFrame, catalog: list[dict]) -> None:
    st.title("📊 Resultado Operacional")
    st.caption(
        "Leitura executiva da produção operacional "
        "por efetivo, pelotão, modalidade e último serviço."
    )

    if df.empty:
        st.info(
            "Ainda não há resultados cadastrados. "
            "Use **Lançar resultado** ou **Importar Excel**."
        )
        return

    min_date = df["data"].min().date()
    max_date = df["data"].max().date()

    if st.session_state.pop("_clear_filters", False):
        st.session_state.filtro_start = min_date
        st.session_state.filtro_end = max_date
        st.session_state.filtro_modalidade = []
        st.session_state.filtro_pelotao = []
        st.session_state.filtro_equipe = []

    if "filtro_start" not in st.session_state:
        st.session_state.filtro_start = min_date
    if "filtro_end" not in st.session_state:
        st.session_state.filtro_end = max_date

    if st.session_state.filtro_start < min_date:
        st.session_state.filtro_start = min_date
    if st.session_state.filtro_end > max_date:
        st.session_state.filtro_end = max_date

    with st.sidebar:
        st.header("Filtros")

        start = st.date_input(
            "Data inicial",
            min_value=min_date,
            max_value=max_date,
            key="filtro_start",
        )
        end = st.date_input(
            "Data final",
            min_value=min_date,
            max_value=max_date,
            key="filtro_end",
        )

        modalidades_opts = sorted(df["modalidade"].dropna().unique().tolist())
        pelotoes_opts = sorted(df["pelotao"].dropna().unique().tolist())
        equipes_opts = sorted(df["equipe"].dropna().unique().tolist())

        modalidades = st.multiselect(
            "Modalidade",
            modalidades_opts,
            key="filtro_modalidade",
            help="Vazio = todas.",
        )
        pelotoes = st.multiselect(
            "Pelotão",
            pelotoes_opts,
            key="filtro_pelotao",
            help="Vazio = todos.",
        )
        equipes = st.multiselect(
            "Equipe",
            equipes_opts,
            key="filtro_equipe",
            help="Vazio = todas.",
        )

        if st.button("Limpar filtros", width="stretch"):
            st.session_state._clear_filters = True
            st.rerun()

    if start > end:
        st.error("A data inicial não pode ser posterior à data final.")
        return

    f = filtered_data(df, start, end, modalidades, pelotoes, equipes)
    show_kpi_row(f)

    if f.empty:
        st.warning("Nenhum resultado encontrado para os filtros selecionados.")
        return

    slugs = extra_slugs(catalog)
    labels = chart_labels(catalog)
    ranking_keys = chart_keys(catalog, include_index=True)
    extra_keys = chart_keys(catalog, include_index=False)
    members_map = load_members_map(engine)

    show_latest_results(f, members_map, engine)
    show_individual_and_daily(f, members_map, slugs, labels, ranking_keys)
    show_pelotao_and_modalidade(f, slugs, labels, ranking_keys, extra_keys)
    show_detailed_analyses(f, slugs)


def show_latest_results(f: pd.DataFrame, members_map: dict, engine) -> None:
    latest_ts = f["data"].max()
    latest = f[f["data"] == latest_ts].sort_values(["equipe", "id"])
    records = latest.to_dict("records")
    result_ids = [int(row["id"]) for row in records]
    occ_map = load_occurrences_map(engine, result_ids)
    seizure_map = load_seizure_summary_by_result(engine, result_ids)

    st.subheader("🚔 Último Resultado Operacional")
    st.caption(
        f"{fmt_date_long(latest_ts)} · último dia com dados dentro dos filtros"
    )

    for chunk in iter_chunks(records, 3):
        cols = st.columns(len(chunk))
        for col, record in zip(cols, chunk):
            with col:
                render_latest_result_card(
                    record,
                    members_map.get(int(record["id"]), []),
                    occ_map.get(int(record["id"]), []),
                    seizure_map.get(int(record["id"]), {}),
                )


def render_latest_result_card(
    record: dict,
    members: list[str],
    occurrences: list[dict],
    seizures: dict,
) -> None:
    score = int(
        record["abordados"] * 2
        + record["carros"]
        + record["motos"]
        + record["ocorrencias"] * 5
    )
    apoios = int(record.get(APOIOS_SLUG, 0) or 0)
    bopm = int(record.get("bopm", 0) or 0)

    with st.container(border=True):
        st.markdown(f"**{record['equipe']}**")
        st.caption(f"{record['pelotao']} • {record['modalidade']}")
        st.caption(f"Índice: {fmt_int(score)}")

        if members:
            st.markdown("  \n".join(str(name) for name in members))
        else:
            st.caption("Efetivo não informado")

        left, right = st.columns(2)
        left.markdown("**Resultado operacional**")
        left.markdown(
            metric_lines(
                [
                    ("Abordados", fmt_int(record["abordados"])),
                    ("Carros", fmt_int(record["carros"])),
                    ("Motos", fmt_int(record["motos"])),
                    ("Ocorrências", fmt_int(record["ocorrencias"])),
                    ("Apoios", fmt_int(apoios)),
                ]
            )
        )
        if bopm:
            left.caption(f"BOPM: {fmt_int(bopm)}")

        right.markdown("**Produtividade**")
        right.markdown(
            metric_lines(
                [
                    ("Pessoas presas", fmt_int(record.get("pessoas_presas", 0))),
                    (
                        "Condenados capturados",
                        fmt_int(record.get("condenados_capturados", 0)),
                    ),
                    (
                        "Veículos recuperados",
                        fmt_int(record.get("veiculos_recuperados", 0)),
                    ),
                ]
            )
        )

        if occurrences:
            st.markdown("**Ocorrências**")
            st.markdown(
                "  \n".join(
                    f"{item['code']} — {item['name']}" for item in occurrences
                )
            )

        seizure_lines = []
        droga = seizures.get("DROGA")
        if droga:
            seizure_lines.append(f"Drogas: {fmt_kg_from_grams(droga)}")
        arma = seizures.get("ARMA")
        if arma:
            seizure_lines.append(f"Armas: {fmt_int(arma)}")
        municao = seizures.get("MUNICAO")
        if municao:
            seizure_lines.append(f"Munições: {fmt_int(municao)}")
        if seizure_lines:
            st.markdown("**Apreensões**")
            st.markdown("  \n".join(seizure_lines))


def show_individual_and_daily(
    f: pd.DataFrame,
    members_map: dict,
    slugs: list[str],
    labels: dict[str, str],
    ranking_keys: list[str],
) -> None:
    left, right = st.columns([1.15, 1])
    with left:
        title_col, metric_col, top_col = st.columns([1.35, 1, 0.7])
        title_col.subheader("🏆 Produção individual")
        ranking_metric = metric_col.selectbox(
            "Indicador",
            ranking_keys,
            format_func=lambda x: labels.get(x, x),
            key="ranking_metric",
            label_visibility="collapsed",
        )
        top_label = top_col.selectbox(
            "Quantidade",
            ["Top 5", "Top 10", "Top 15", "Todos"],
            index=1,
            key="ranking_top",
            label_visibility="collapsed",
        )
        production = get_member_production(f, members_map, slugs)
        if production.empty:
            st.info(
                "Ainda não há efetivo estruturado suficiente "
                "para gerar o ranking individual."
            )
        else:
            ranked = ensure_metric_column(production, ranking_metric)
            ranked = ranked.sort_values(ranking_metric, ascending=False)
            limits = {"Top 5": 5, "Top 10": 10, "Top 15": 15, "Todos": None}
            limit = limits[top_label]
            if limit:
                ranked = ranked.head(limit)
            plot_chart(
                horizontal_bar(
                    ranked,
                    ranking_metric,
                    "member_name",
                    value_label=labels.get(ranking_metric, ranking_metric),
                    services_col="services",
                )
            )
            st.caption(
                "Cada policial recebe o resultado dos serviços em que participou."
            )

    with right:
        st.subheader("📈 Evolução diária")
        daily = (
            f.groupby("data", as_index=False)[METRIC_COLS]
            .sum()
            .sort_values("data")
        )
        daily = add_score(daily)
        show_ma = len(daily) >= 7
        if show_ma:
            daily["mm7"] = daily["indice_producao"].rolling(7, min_periods=7).mean()
        plot_chart(area_daily(daily, show_ma=show_ma))
        if show_ma:
            st.caption("Linha tracejada: média móvel de 7 dias.")


def show_pelotao_and_modalidade(
    f: pd.DataFrame,
    slugs: list[str],
    labels: dict[str, str],
    ranking_keys: list[str],
    extra_keys: list[str],
) -> None:
    left, right = st.columns([1.15, 1])
    with left:
        title_col, metric_col = st.columns([1.4, 1])
        title_col.subheader("🎖️ Produção por pelotão")
        pelotao_metric = metric_col.selectbox(
            "Indicador do pelotão",
            ranking_keys,
            format_func=lambda x: labels.get(x, x),
            key="pelotao_metric",
            label_visibility="collapsed",
        )
        by_pelotao = ensure_metric_column(aggregate(f, "pelotao", slugs), pelotao_metric)
        plot_chart(
            horizontal_bar(
                by_pelotao,
                pelotao_metric,
                "pelotao",
                value_label=labels.get(pelotao_metric, pelotao_metric),
            )
        )

    with right:
        title_col, metric_col = st.columns([1.4, 1])
        title_col.subheader("🚓 Resultados por modalidade")
        modalidade_metric = metric_col.selectbox(
            "Indicador por modalidade",
            extra_keys,
            format_func=lambda x: labels.get(x, x),
            key="modalidade_metric",
            label_visibility="collapsed",
        )
        by_mod = ensure_metric_column(aggregate(f, "modalidade", slugs), modalidade_metric)
        plot_chart(
            horizontal_bar(
                by_mod,
                modalidade_metric,
                "modalidade",
                value_label=labels.get(modalidade_metric, modalidade_metric),
            )
        )


def show_detailed_analyses(f: pd.DataFrame, slugs: list[str]) -> None:
    with st.expander("📋 Análises detalhadas", expanded=False):
        by_equipe = aggregate(f, "equipe", slugs)
        ranking_display = by_equipe.sort_values(
            "indice_producao", ascending=False
        ).copy()
        ranking_display.insert(0, "Posição", range(1, len(ranking_display) + 1))
        ranking_cols = [
            "Posição",
            "equipe",
            "abordados",
            "carros",
            "motos",
            "bopm",
            "ocorrencias",
            "indice_producao",
        ]
        st.markdown("**Produção por equipe**")
        st.dataframe(
            ranking_display[ranking_cols],
            width="stretch",
            hide_index=True,
            column_config={
                "Posição": number_column("Posição"),
                **table_config(ranking_cols[1:]),
            },
        )

        daily = (
            f.groupby("data", as_index=False)[METRIC_COLS]
            .sum()
            .sort_values("data", ascending=False)
        )
        daily = add_score(daily)
        daily_display = daily.copy()
        daily_display["data"] = daily_display["data"].dt.strftime("%d/%m/%Y")
        daily_cols = ["data", *METRIC_COLS, "indice_producao"]
        st.markdown("**Resultado por dia**")
        st.dataframe(
            daily_display[daily_cols],
            width="stretch",
            hide_index=True,
            column_config=table_config(daily_cols),
        )

        detail = add_score(f).sort_values(["data", "id"], ascending=[False, False])
        detail_view = detail.copy()
        detail_view["data"] = detail_view["data"].dt.strftime("%d/%m/%Y")
        detail_view["obs"] = obs_flag(detail_view.get("observacao", pd.Series(dtype=str)))
        detail_cols = [
            "data",
            "modalidade",
            "equipe",
            "pelotao",
            *METRIC_COLS,
            "indice_producao",
            "obs",
        ]
        st.markdown("**Tabela operacional**")
        st.dataframe(
            detail_view[detail_cols],
            width="stretch",
            hide_index=True,
            column_config=table_config(detail_cols),
        )


def options_from_data(df: pd.DataFrame, column: str, defaults: list[str]) -> list[str]:
    values = set(defaults)
    if not df.empty:
        values.update(df[column].dropna().astype(str).str.strip().tolist())
    return sorted(v for v in values if v)


def split_apoios(active_extras: list[dict]) -> tuple[dict | None, list[dict]]:
    apoios = next((item for item in active_extras if item["slug"] == APOIOS_SLUG), None)
    others = [
        item
        for item in active_extras
        if item["slug"] != APOIOS_SLUG and item["slug"] not in RESERVED_SLUGS
    ]
    return apoios, others


def extras_from_inputs(values: dict[int, int]) -> dict[int, int]:
    return {ind_id: int(value) for ind_id, value in values.items() if int(value) > 0}


def extra_value_map(extras: list[dict]) -> dict[int, int]:
    return {int(item["indicator_id"]): int(item["value"]) for item in extras}


def fmt_qty(value, unit: str) -> str:
    raw = f"{value:.3f}".rstrip("0").rstrip(".")
    raw = raw.replace(".", ",")
    if unit == "g":
        grams = float(value)
        if grams >= 1000:
            kg = f"{grams / 1000:.3f}".rstrip("0").rstrip(".").replace(".", ",")
            return f"{raw} g ({kg} kg)"
        return f"{raw} g"
    if unit == "BRL":
        return f"R$ {raw}"
    return f"{raw} {unit}"


def render_result_fields(df, engine, defaults: dict | None = None, key_prefix: str = "new"):
    defaults = defaults or {}
    pelotoes = options_from_data(df, "pelotao", PELOTOES_PADRAO)
    modalidades = options_from_data(df, "modalidade", MODALIDADES_PADRAO)
    active_extras = list_active_indicators(engine)
    extra_defaults = defaults.get("extras", {})

    st.markdown("### Dados do serviço")
    c1, c2, c3 = st.columns(3)
    data_reg = c1.date_input(
        "Data",
        defaults.get("data", date.today()),
        key=f"{key_prefix}_data",
    )
    modalidade_opts = modalidades
    modalidade_default = defaults.get("modalidade")
    modalidade_index = (
        modalidade_opts.index(modalidade_default)
        if modalidade_default in modalidade_opts
        else 0
    )
    modalidade = c2.selectbox(
        "Modalidade",
        modalidade_opts,
        index=modalidade_index,
        key=f"{key_prefix}_modalidade",
    )
    equipe = c3.text_input(
        "Equipe",
        value=defaults.get("equipe", ""),
        placeholder="Ex.: FORÇA TÁTICA 3034",
        key=f"{key_prefix}_equipe",
    )

    c1, c2 = st.columns(2)
    pelotao_default = defaults.get("pelotao")
    pelotao_index = (
        pelotoes.index(pelotao_default) if pelotao_default in pelotoes else 0
    )
    pelotao = c1.selectbox(
        "Pelotão",
        pelotoes,
        index=pelotao_index,
        key=f"{key_prefix}_pelotao",
    )
    efetivo = c2.text_input(
        "Efetivo da equipe",
        value=defaults.get("efetivo", ""),
        placeholder="CB PAULINO / SD RUSTIGUELLI / SD BATISTA",
        key=f"{key_prefix}_efetivo",
        help="Separe os nomes com / . Graduação faz parte da identidade.",
    )

    st.markdown("### Resultados operacionais")
    c = st.columns(6)
    abordados = c[0].number_input(
        "Abordados", min_value=0, step=1, value=int(defaults.get("abordados", 0)),
        key=f"{key_prefix}_abordados",
    )
    carros = c[1].number_input(
        "Carros", min_value=0, step=1, value=int(defaults.get("carros", 0)),
        key=f"{key_prefix}_carros",
    )
    motos = c[2].number_input(
        "Motos", min_value=0, step=1, value=int(defaults.get("motos", 0)),
        key=f"{key_prefix}_motos",
    )
    bopm = c[3].number_input(
        "BOPM", min_value=0, step=1, value=int(defaults.get("bopm", 0)),
        key=f"{key_prefix}_bopm",
    )
    ocorrencias = c[4].number_input(
        "Ocorrências", min_value=0, step=1, value=int(defaults.get("ocorrencias", 0)),
        key=f"{key_prefix}_ocorrencias",
    )
    extra_inputs: dict[int, int] = {}
    apoios, other_extras = split_apoios(active_extras)
    if apoios:
        extra_inputs[apoios["id"]] = c[5].number_input(
            "Apoios",
            min_value=0,
            step=1,
            value=int(extra_defaults.get(apoios["id"], 0)),
            key=f"{key_prefix}_apoios",
        )
    else:
        c[5].caption("Apoios inativo")

    st.markdown("### Produtividade")
    p = st.columns(3)
    pessoas_presas = p[0].number_input(
        "Pessoas presas",
        min_value=0,
        step=1,
        value=int(defaults.get("pessoas_presas", 0)),
        key=f"{key_prefix}_pessoas",
    )
    condenados = p[1].number_input(
        "Condenados capturados",
        min_value=0,
        step=1,
        value=int(defaults.get("condenados_capturados", 0)),
        key=f"{key_prefix}_condenados",
    )
    veiculos = p[2].number_input(
        "Veículos recuperados",
        min_value=0,
        step=1,
        value=int(defaults.get("veiculos_recuperados", 0)),
        key=f"{key_prefix}_veiculos",
    )

    if other_extras:
        st.markdown("### Indicadores adicionais")
        extra_cols = st.columns(min(3, len(other_extras)))
        for idx, item in enumerate(other_extras):
            extra_inputs[item["id"]] = extra_cols[idx % len(extra_cols)].number_input(
                item["name"],
                min_value=0,
                step=1,
                value=int(extra_defaults.get(item["id"], 0)),
                key=f"{key_prefix}_extra_{item['id']}",
            )

    st.markdown("### Observação")
    observacao = st.text_area(
        "Observação (opcional)",
        value=defaults.get("observacao", ""),
        height=80,
        key=f"{key_prefix}_obs",
        label_visibility="collapsed",
    )

    return {
        "data": datetime.combine(data_reg, datetime.min.time()),
        "modalidade": modalidade.strip(),
        "equipe": equipe.strip().upper(),
        "pelotao": pelotao.strip().upper(),
        "efetivo": efetivo,
        "abordados": int(abordados),
        "carros": int(carros),
        "motos": int(motos),
        "bopm": int(bopm),
        "ocorrencias": int(ocorrencias),
        "pessoas_presas": int(pessoas_presas),
        "condenados_capturados": int(condenados),
        "veiculos_recuperados": int(veiculos),
        "observacao": observacao.strip(),
        "extras": extras_from_inputs(extra_inputs),
    }


def show_lancamento(engine, df: pd.DataFrame) -> None:
    st.title("➕ Lançar resultado")
    st.caption("Registre o resultado de um serviço operacional.")

    with st.form("novo_resultado", clear_on_submit=True):
        payload = render_result_fields(df, engine, key_prefix="new")
        submitted = st.form_submit_button("Salvar resultado", type="primary")

    if not submitted:
        return
    if not payload["equipe"]:
        st.error("Informe a equipe.")
        return
    if not payload["pelotao"]:
        st.error("Informe o pelotão.")
        return

    try:
        insert_result(engine, payload)
    except Exception:
        logger.exception("Falha ao salvar resultado.")
        st.error("Não foi possível salvar o resultado. Tente novamente.")
        return

    st.success("Resultado salvo com sucesso.")
    st.rerun()


@st.dialog("Detalhes do Resultado Operacional", width="large")
def show_result_details(engine, record: pd.Series, extras: list[dict]) -> None:
    result_id = int(record["id"])
    st.caption(f"ID {result_id}")

    st.markdown("**Dados do serviço**")
    c1, c2 = st.columns(2)
    c1.markdown(f"**Data:** {record['data'].strftime('%d/%m/%Y')}")
    c2.markdown(f"**Modalidade:** {record['modalidade']}")
    c1.markdown(f"**Equipe:** {record['equipe']}")
    c2.markdown(f"**Pelotão:** {record['pelotao']}")

    members = get_result_members(engine, result_id)
    if members:
        st.markdown("**Efetivo da equipe**")
        st.write(format_members(members))

    st.markdown("**Resultados operacionais**")
    metrics = st.columns(6)
    metrics[0].metric("Abordados", fmt_int(record["abordados"]))
    metrics[1].metric("Carros", fmt_int(record["carros"]))
    metrics[2].metric("Motos", fmt_int(record["motos"]))
    metrics[3].metric("BOPM", fmt_int(record["bopm"]))
    metrics[4].metric("Ocorrências", fmt_int(record["ocorrencias"]))
    apoios = next((item for item in extras if item["slug"] == APOIOS_SLUG), None)
    metrics[5].metric("Apoios", fmt_int(apoios["value"] if apoios else 0))

    st.markdown("**Produtividade**")
    prod = st.columns(4)
    prod[0].metric("Pessoas presas", fmt_int(record.get("pessoas_presas", 0)))
    prod[1].metric("Condenados capturados", fmt_int(record.get("condenados_capturados", 0)))
    prod[2].metric("Veículos recuperados", fmt_int(record.get("veiculos_recuperados", 0)))
    score = int(
        record["abordados"] * 2
        + record["carros"]
        + record["motos"]
        + record["ocorrencias"] * 5
    )
    prod[3].metric("Índice", fmt_int(score))

    extras_shown = [
        item
        for item in extras
        if int(item["value"]) > 0
        and item["slug"] != APOIOS_SLUG
        and item["slug"] not in RESERVED_SLUGS
    ]
    if extras_shown:
        st.markdown("**Indicadores adicionais**")
        for item in extras_shown:
            st.write(f"{item['name']}: **{fmt_int(item['value'])}**")

    linked = list_linked_occurrences(engine, result_id)
    if linked:
        st.markdown("**Ocorrências vinculadas**")
        for item in linked:
            bopm = f" · BOPM {item['bopm']}" if item["bopm"] else ""
            st.write(f"{item['code']} — {item['name']}{bopm}")

    observacao = str(record.get("observacao") or "").strip()
    st.markdown("**Observação**")
    if observacao:
        st.info(observacao)
    else:
        st.caption("Este registro não possui observação.")

    created = str(record.get("created_at") or "").strip()
    if created:
        st.caption(f"Criado em: {created}")


def record_defaults(engine, record: pd.Series) -> dict:
    extras = extra_value_map(get_result_extra_values(engine, int(record["id"])))
    data_val = record["data"]
    if hasattr(data_val, "date"):
        data_val = data_val.date()
    return {
        "data": data_val,
        "modalidade": record["modalidade"],
        "equipe": record["equipe"],
        "pelotao": record["pelotao"],
        "efetivo": format_members(get_result_members(engine, int(record["id"]))),
        "abordados": int(record["abordados"]),
        "carros": int(record["carros"]),
        "motos": int(record["motos"]),
        "bopm": int(record["bopm"]),
        "ocorrencias": int(record["ocorrencias"]),
        "pessoas_presas": int(record.get("pessoas_presas", 0) or 0),
        "condenados_capturados": int(record.get("condenados_capturados", 0) or 0),
        "veiculos_recuperados": int(record.get("veiculos_recuperados", 0) or 0),
        "observacao": str(record.get("observacao") or ""),
        "extras": extras,
    }


def show_registros(engine, df: pd.DataFrame) -> None:
    st.title("📋 Registros")

    if df.empty:
        st.info("Nenhum registro cadastrado.")
        return

    display = df.copy()
    display["data"] = display["data"].dt.strftime("%d/%m/%Y")
    display["obs"] = obs_flag(display.get("observacao", pd.Series(dtype=str)))
    cols = [
        "id",
        "data",
        "modalidade",
        "equipe",
        "pelotao",
        *METRIC_COLS,
        "obs",
    ]
    event = st.dataframe(
        display[cols],
        width="stretch",
        hide_index=True,
        column_config=table_config(cols),
        on_select="rerun",
        selection_mode="single-row",
        key="registros_table",
    )
    st.caption("Selecione uma linha para ver detalhes ou editar.")

    selected_pos = event.selection.rows if event and event.selection else []
    selected_record = df.iloc[selected_pos[0]] if selected_pos else None

    actions = st.columns(3)
    with actions[0]:
        if st.button("Ver detalhes", disabled=selected_record is None, type="primary"):
            extras = get_result_extra_values(engine, int(selected_record["id"]))
            show_result_details(engine, selected_record, extras)
    with actions[1]:
        if st.button("Editar resultado", disabled=selected_record is None):
            st.session_state.edit_result_id = int(selected_record["id"])

    if st.session_state.get("edit_result_id"):
        edit_id = int(st.session_state.edit_result_id)
        edit_rows = df[df["id"] == edit_id]
        if edit_rows.empty:
            st.session_state.edit_result_id = None
        else:
            st.divider()
            st.subheader(f"Editar resultado #{edit_id}")
            defaults = record_defaults(engine, edit_rows.iloc[0])
            with st.form("editar_resultado"):
                payload = render_result_fields(
                    df, engine, defaults=defaults, key_prefix=f"edit_{edit_id}"
                )
                c1, c2 = st.columns(2)
                saved = c1.form_submit_button("Salvar alterações", type="primary")
                cancelled = c2.form_submit_button("Cancelar")
            if cancelled:
                st.session_state.edit_result_id = None
                st.rerun()
            if saved:
                if not payload["equipe"] or not payload["pelotao"]:
                    st.error("Informe equipe e pelotão.")
                else:
                    try:
                        update_result(engine, edit_id, payload)
                    except Exception:
                        logger.exception("Falha ao editar resultado.")
                        st.error("Não foi possível salvar a edição.")
                    else:
                        st.session_state.edit_result_id = None
                        st.success("Resultado atualizado.")
                        st.rerun()

    st.divider()
    st.subheader("Excluir registro")
    selected = st.selectbox("Selecione o ID", df["id"].tolist())
    occ_count = count_occurrences_for_result(engine, selected)
    if occ_count:
        st.warning(
            f"Este resultado possui {occ_count} ocorrência(s) vinculada(s). "
            "A exclusão também removerá essas ocorrências e suas apreensões."
        )
        confirm = st.checkbox(
            "Confirmo a exclusão do resultado, ocorrências e apreensões."
        )
    else:
        confirm = True

    if st.button("Excluir selecionado", disabled=not confirm):
        try:
            delete_result(engine, selected)
        except Exception:
            logger.exception("Falha ao excluir registro id=%s", selected)
            st.error("Não foi possível excluir o registro.")
            return
        st.success(f"Registro {selected} excluído.")
        st.rerun()


def show_indicadores(engine) -> None:
    st.title("⚙️ Indicadores")
    st.caption(
        "Cadastre métricas complementares sem alterar os indicadores fixos "
        "nem o índice de produção."
    )

    with st.form("novo_indicador"):
        name = st.text_input("Nome do indicador", placeholder="Ex.: Veículos Recuperados")
        submitted = st.form_submit_button("Criar indicador", type="primary")
    if submitted:
        try:
            created = create_indicator(engine, name)
        except ValueError as exc:
            st.error(str(exc))
        except Exception:
            logger.exception("Falha ao criar indicador.")
            st.error("Não foi possível criar o indicador.")
        else:
            st.success(f"Indicador **{created['name']}** criado.")
            st.rerun()

    catalog = list_indicators(engine)
    if not catalog:
        st.info("Nenhum indicador adicional cadastrado.")
        return
    dynamic_items = [item for item in catalog if item["slug"] not in RESERVED_SLUGS]

    usage = indicator_usage_counts(engine)
    rows = []
    for item in catalog:
        rows.append(
            {
                "ID": item["id"],
                "Nome": item["name"],
                "Slug": item["slug"],
                "Status": "Ativo" if item["active"] else "Inativo",
                "Uso": usage.get(item["id"], 0),
            }
        )
    st.dataframe(pd.DataFrame(rows), width="stretch", hide_index=True)

    st.subheader("Ativar / desativar")
    if not dynamic_items:
        st.caption("Não há indicadores dinâmicos para ativar ou desativar.")
        return
    options = {
        f"{item['name']} ({'ativo' if item['active'] else 'inativo'})": item
        for item in dynamic_items
    }
    chosen_label = st.selectbox("Indicador", list(options.keys()))
    chosen = options[chosen_label]
    c1, c2, c3 = st.columns(3)
    if c1.button("Ativar"):
        try:
            set_indicator_active(engine, chosen["id"], True)
        except ValueError as exc:
            st.error(str(exc))
        else:
            st.rerun()
    if c2.button("Desativar"):
        set_indicator_active(engine, chosen["id"], False)
        st.rerun()
    if c3.button("Excluir se sem histórico"):
        try:
            delete_indicator(engine, chosen["id"])
        except ValueError as exc:
            st.error(str(exc))
        else:
            st.success("Indicador excluído.")
            st.rerun()

    st.caption(
        "Indicadores inativos saem do lançamento, mas permanecem no histórico, "
        "nos gráficos e na exportação. Campos fixos de resultados "
        "(pessoas presas, condenados capturados e veículos recuperados) "
        "não podem ser cadastrados ou reativados como indicadores dinâmicos."
    )


def seizure_unit_options(category: str) -> list[str]:
    if category == "DROGA":
        return ["g", "kg"]
    if category == "DINHEIRO":
        return ["BRL"]
    return ["un"]


def collect_seizure_inputs(prefix: str, count: int) -> list[dict]:
    seizures = []
    for idx in range(count):
        cat = st.session_state.get(f"{prefix}_cat_{idx}", "OBJETO")
        item = st.session_state.get(f"{prefix}_item_{idx}", "")
        qty = st.session_state.get(f"{prefix}_qty_{idx}", 0)
        unit = st.session_state.get(f"{prefix}_unit_{idx}", "un")
        if str(item).strip() and float(qty or 0) > 0:
            seizures.append(
                {
                    "category": cat,
                    "item": item,
                    "quantity": qty,
                    "unit": unit,
                }
            )
    return seizures


def render_seizure_rows(prefix: str, count: int, defaults: list[dict] | None = None) -> None:
    defaults = defaults or []
    for idx in range(count):
        current = defaults[idx] if idx < len(defaults) else {}
        cat_key = f"{prefix}_cat_{idx}"
        item_key = f"{prefix}_item_{idx}"
        qty_key = f"{prefix}_qty_{idx}"
        unit_key = f"{prefix}_unit_{idx}"
        if cat_key not in st.session_state:
            st.session_state[cat_key] = current.get("category", "OBJETO")
        if item_key not in st.session_state:
            st.session_state[item_key] = current.get("item", "")
        if qty_key not in st.session_state:
            qty = current.get("quantity", 0)
            st.session_state[qty_key] = float(qty or 0)
        st.markdown(f"**Apreensão {idx + 1}**")
        c1, c2, c3, c4 = st.columns([1.2, 1.4, 1, 0.8])
        chosen_cat = c1.selectbox(
            "Categoria",
            list(SEIZURE_CATEGORIES),
            key=cat_key,
        )
        c2.text_input("Item", key=item_key)
        step = 0.1 if chosen_cat in {"DROGA", "DINHEIRO"} else 1.0
        c3.number_input("Quantidade", min_value=0.0, step=step, key=qty_key)
        units = seizure_unit_options(chosen_cat)
        if unit_key not in st.session_state or st.session_state[unit_key] not in units:
            preferred = current.get("unit", units[0])
            st.session_state[unit_key] = preferred if preferred in units else units[0]
        c4.selectbox("Unidade", units, key=unit_key)


@st.dialog("Detalhes da ocorrência", width="large")
def show_occurrence_details(engine, row: pd.Series) -> None:
    st.markdown(f"**{row['code']} — {row['type_name']}**")
    st.write(f"Data: {row['data'].strftime('%d/%m/%Y')}")
    st.write(f"BOPM: {row['bopm'] or '—'}")
    st.write(f"BOPC: {row['bopc'] or '—'}")
    st.write(f"Equipe: {row['equipe']}")
    st.write(f"Pelotão: {row['pelotao']}")
    st.write(f"Modalidade: {row['modalidade']}")
    members = get_result_members(engine, int(row["result_id"]))
    st.markdown("**Efetivo envolvido**")
    st.write(format_members(members) if members else "Sem efetivo registrado neste resultado.")
    seizures = get_occurrence_seizures(engine, int(row["id"]))
    if seizures:
        st.markdown("**Apreensões**")
        for item in seizures:
            st.write(
                f"{item['category']} · {item['item']} · "
                f"{fmt_qty(item['quantity'], item['unit'])}"
            )
    observation = str(row.get("observation") or "").strip()
    st.markdown("**Observação**")
    st.write(observation or "—")


def show_ocorrencias(engine, df: pd.DataFrame) -> None:
    st.title("🚨 Ocorrências")
    st.caption(
        "Detalhamento analítico vinculado ao resultado da equipe. "
        "O campo Ocorrências do resultado permanece o consolidado oficial."
    )

    with st.expander("Tipos de ocorrência"):
        with st.form("novo_tipo_ocorrencia"):
            c1, c2, c3 = st.columns(3)
            code = c1.text_input("Código", placeholder="B04")
            name = c2.text_input("Nome", placeholder="ROUBO")
            kpi_labels = list(KPI_CATEGORY_LABELS.values())
            kpi_keys = list(KPI_CATEGORY_LABELS.keys())
            kpi_label = c3.selectbox("Categoria para KPI", kpi_labels)
            if st.form_submit_button("Criar tipo", type="primary"):
                kpi_value = kpi_keys[kpi_labels.index(kpi_label)]
                try:
                    created = create_occurrence_type(engine, code, name, kpi_value)
                except ValueError as exc:
                    st.error(str(exc))
                except Exception:
                    logger.exception("Falha ao criar tipo de ocorrência.")
                    st.error("Não foi possível criar o tipo.")
                else:
                    st.success(f"Tipo {created['code']} criado.")
                    st.rerun()

        types = list_occurrence_types(engine)
        if types:
            usage = occurrence_type_usage_counts(engine)
            type_rows = [
                {
                    "Código": item["code"],
                    "Nome": item["name"],
                    "KPI": KPI_CATEGORY_LABELS.get(item["kpi_category"], "Nenhuma"),
                    "Status": "Ativo" if item["active"] else "Inativo",
                    "Uso": usage.get(item["id"], 0),
                }
                for item in types
            ]
            st.dataframe(pd.DataFrame(type_rows), width="stretch", hide_index=True)
            options = {
                f"{item['code']} — {item['name']}": item for item in types
            }
            chosen_label = st.selectbox("Tipo", list(options.keys()), key="occ_type_manage")
            chosen = options[chosen_label]
            c1, c2, c3 = st.columns(3)
            if c1.button("Ativar tipo"):
                set_occurrence_type_active(engine, chosen["id"], True)
                st.rerun()
            if c2.button("Desativar tipo"):
                set_occurrence_type_active(engine, chosen["id"], False)
                st.rerun()
            if c3.button("Excluir tipo sem histórico"):
                try:
                    delete_occurrence_type(engine, chosen["id"])
                except ValueError as exc:
                    st.error(str(exc))
                else:
                    st.success("Tipo excluído.")
                    st.rerun()

    st.subheader("Nova ocorrência")
    occ_date = st.date_input("Data da ocorrência", date.today(), key="occ_date")
    day_results = list_results_by_date(engine, occ_date)
    active_types = list_occurrence_types(engine, active_only=True)

    if "occ_seizure_rows" not in st.session_state:
        st.session_state.occ_seizure_rows = 1
    if st.button("+ Adicionar apreensão"):
        st.session_state.occ_seizure_rows += 1
        st.rerun()
    render_seizure_rows("new_occ", st.session_state.occ_seizure_rows)

    if not day_results:
        st.info("Não há resultados lançados nesta data para vincular a equipe.")
    elif not active_types:
        st.info("Cadastre um tipo de ocorrência ativo antes de lançar.")
    else:
        with st.form("nova_ocorrencia"):
            type_opts = {f"{item['code']} — {item['name']}": item["id"] for item in active_types}
            type_label = st.selectbox("Tipo / Código", list(type_opts.keys()))
            c1, c2 = st.columns(2)
            bopm = c1.text_input("BOPM")
            bopc = c2.text_input("BOPC")
            result_opts = {
                f"{item['equipe']} · {item['modalidade']} (#{item['id']})": item["id"]
                for item in day_results
            }
            result_label = st.selectbox("Equipe vinculada", list(result_opts.keys()))
            observation = st.text_area("Observação", height=80)
            saved = st.form_submit_button("Salvar ocorrência", type="primary")
        if saved:
            try:
                insert_occurrence(
                    engine,
                    {
                        "result_id": result_opts[result_label],
                        "occurrence_type_id": type_opts[type_label],
                        "bopm": bopm,
                        "bopc": bopc,
                        "observation": observation,
                        "seizures": collect_seizure_inputs(
                            "new_occ", st.session_state.occ_seizure_rows
                        ),
                    },
                )
            except ValueError as exc:
                st.error(str(exc))
            except Exception:
                logger.exception("Falha ao salvar ocorrência.")
                st.error("Não foi possível salvar a ocorrência.")
            else:
                st.session_state.occ_seizure_rows = 1
                st.success("Ocorrência salva.")
                st.rerun()

    occ_df = load_occurrences(engine)
    st.subheader("Listagem")
    if occ_df.empty:
        st.info("Nenhuma ocorrência cadastrada.")
        return

    min_date = occ_df["data"].min().date()
    max_date = occ_df["data"].max().date()
    f1, f2, f3, f4 = st.columns(4)
    start = f1.date_input("Início", min_date, key="occ_filtro_start")
    end = f2.date_input("Fim", max_date, key="occ_filtro_end")
    type_filter = f3.multiselect(
        "Tipo", sorted(occ_df["code"].dropna().unique().tolist()), key="occ_filtro_tipo"
    )
    equipe_filter = f4.multiselect(
        "Equipe", sorted(occ_df["equipe"].dropna().unique().tolist()), key="occ_filtro_equipe"
    )
    f5, f6 = st.columns(2)
    pelotao_filter = f5.multiselect(
        "Pelotão", sorted(occ_df["pelotao"].dropna().unique().tolist()), key="occ_filtro_pelotao"
    )
    modalidade_filter = f6.multiselect(
        "Modalidade",
        sorted(occ_df["modalidade"].dropna().unique().tolist()),
        key="occ_filtro_mod",
    )

    filtered = occ_df[
        (occ_df["data"].dt.date >= start) & (occ_df["data"].dt.date <= end)
    ].copy()
    if type_filter:
        filtered = filtered[filtered["code"].isin(type_filter)]
    if equipe_filter:
        filtered = filtered[filtered["equipe"].isin(equipe_filter)]
    if pelotao_filter:
        filtered = filtered[filtered["pelotao"].isin(pelotao_filter)]
    if modalidade_filter:
        filtered = filtered[filtered["modalidade"].isin(modalidade_filter)]

    if filtered.empty:
        st.warning("Nenhum resultado encontrado para os filtros selecionados.")
        return

    view = filtered.copy()
    view["data"] = view["data"].dt.strftime("%d/%m/%Y")
    list_cols = ["data", "code", "type_name", "bopm", "bopc", "equipe"]
    event = st.dataframe(
        view[list_cols].rename(
            columns={"code": "Código", "type_name": "Tipo", "equipe": "Equipe", "data": "Data"}
        ),
        width="stretch",
        hide_index=True,
        on_select="rerun",
        selection_mode="single-row",
        key="ocorrencias_table",
    )
    selected_pos = event.selection.rows if event and event.selection else []
    selected_occ = filtered.iloc[selected_pos[0]] if selected_pos else None

    a1, a2, a3 = st.columns(3)
    with a1:
        if st.button("Ver detalhes da ocorrência", disabled=selected_occ is None):
            show_occurrence_details(engine, selected_occ)
    with a2:
        if st.button("Editar ocorrência", disabled=selected_occ is None):
            st.session_state.edit_occ_id = int(selected_occ["id"])
    with a3:
        if selected_occ is not None and st.button("Excluir ocorrência"):
            st.session_state.delete_occ_id = int(selected_occ["id"])

    if st.session_state.get("delete_occ_id"):
        st.warning("A exclusão remove também as apreensões desta ocorrência.")
        c1, c2 = st.columns(2)
        if c1.button("Confirmar exclusão da ocorrência"):
            delete_occurrence(engine, int(st.session_state.delete_occ_id))
            st.session_state.delete_occ_id = None
            st.success("Ocorrência excluída.")
            st.rerun()
        if c2.button("Cancelar exclusão"):
            st.session_state.delete_occ_id = None
            st.rerun()

    if st.session_state.get("edit_occ_id"):
        edit_id = int(st.session_state.edit_occ_id)
        edit_rows = occ_df[occ_df["id"] == edit_id]
        if edit_rows.empty:
            st.session_state.edit_occ_id = None
        else:
            row = edit_rows.iloc[0]
            st.divider()
            st.subheader(f"Editar ocorrência #{edit_id}")
            seizures = get_occurrence_seizures(engine, edit_id)
            if "edit_occ_seizure_rows" not in st.session_state:
                st.session_state.edit_occ_seizure_rows = max(len(seizures), 1)
            if st.button("+ Adicionar apreensão na edição"):
                st.session_state.edit_occ_seizure_rows += 1
                st.rerun()
            render_seizure_rows(
                "edit_occ",
                st.session_state.edit_occ_seizure_rows,
                defaults=seizures,
            )
            all_types = list_occurrence_types(engine)
            type_opts = {f"{item['code']} — {item['name']}": item["id"] for item in all_types}
            current_type = f"{row['code']} — {row['type_name']}"
            day_results = list_results_by_date(engine, row["data"].date())
            if not any(item["id"] == int(row["result_id"]) for item in day_results):
                day_results.append(
                    {
                        "id": int(row["result_id"]),
                        "equipe": row["equipe"],
                        "modalidade": row["modalidade"],
                    }
                )
            result_opts = {
                f"{item['equipe']} · {item.get('modalidade', '')} (#{item['id']})": item["id"]
                for item in day_results
            }
            current_result = next(
                (
                    label
                    for label, value in result_opts.items()
                    if value == int(row["result_id"])
                ),
                list(result_opts.keys())[0],
            )
            with st.form("editar_ocorrencia"):
                type_label = st.selectbox(
                    "Tipo / Código",
                    list(type_opts.keys()),
                    index=list(type_opts.keys()).index(current_type)
                    if current_type in type_opts
                    else 0,
                )
                c1, c2 = st.columns(2)
                bopm = c1.text_input("BOPM", value=row["bopm"])
                bopc = c2.text_input("BOPC", value=row["bopc"])
                result_label = st.selectbox(
                    "Equipe vinculada",
                    list(result_opts.keys()),
                    index=list(result_opts.keys()).index(current_result),
                )
                observation = st.text_area(
                    "Observação", value=row["observation"], height=80
                )
                c1, c2 = st.columns(2)
                saved = c1.form_submit_button("Salvar ocorrência", type="primary")
                cancelled = c2.form_submit_button("Cancelar")
            if cancelled:
                st.session_state.edit_occ_id = None
                st.session_state.pop("edit_occ_seizure_rows", None)
                st.rerun()
            if saved:
                try:
                    update_occurrence(
                        engine,
                        edit_id,
                        {
                            "result_id": result_opts[result_label],
                            "occurrence_type_id": type_opts[type_label],
                            "bopm": bopm,
                            "bopc": bopc,
                            "observation": observation,
                            "seizures": collect_seizure_inputs(
                                "edit_occ", st.session_state.edit_occ_seizure_rows
                            ),
                        },
                    )
                except ValueError as exc:
                    st.error(str(exc))
                except Exception:
                    logger.exception("Falha ao editar ocorrência.")
                    st.error("Não foi possível salvar a ocorrência.")
                else:
                    st.session_state.edit_occ_id = None
                    st.session_state.pop("edit_occ_seizure_rows", None)
                    st.success("Ocorrência atualizada.")
                    st.rerun()


def import_excel(engine, uploaded_file) -> int:
    raw = pd.read_excel(uploaded_file, header=None)
    header_idx = None

    for i in range(min(len(raw), 30)):
        vals = [str(v).strip().upper() for v in raw.iloc[i].tolist()]
        if "DATA" in vals and "MODALIDADE" in vals and "EQUIPE" in vals:
            header_idx = i
            break

    if header_idx is None:
        raise ValueError("Não encontrei a linha de cabeçalho esperada na planilha.")

    df = raw.iloc[header_idx + 1 :].copy()
    headers = [
        str(v).strip().upper() if pd.notna(v) else ""
        for v in raw.iloc[header_idx]
    ]
    df.columns = headers
    if not pd.Index(df.columns).is_unique:
        duplicated = pd.Index(df.columns)[pd.Index(df.columns).duplicated()].unique().tolist()
        raise ValueError(
            f"A planilha possui colunas duplicadas no cabeçalho: {', '.join(duplicated)}."
        )

    required = [
        "DATA",
        "MODALIDADE",
        "EQUIPE",
        "PELOTÃO",
        "ABORDADOS",
        "CARROS",
        "MOTOS",
        "OCORRENCIAS",
    ]
    missing = [c for c in required if c not in df.columns]
    if missing:
        raise ValueError(f"Colunas ausentes: {', '.join(missing)}")

    has_bopm = "BOPM" in df.columns
    optional_fixed = {
        "PESSOAS PRESAS": "pessoas_presas",
        "CONDENADOS CAPTURADOS": "condenados_capturados",
        "VEICULOS RECUPERADOS": "veiculos_recuperados",
        "VEÍCULOS RECUPERADOS": "veiculos_recuperados",
    }
    efetivo_col = "EFETIVO" if "EFETIVO" in df.columns else None
    catalog = list_indicators(engine)
    extra_by_header = {
        item["name"].strip().upper(): item
        for item in catalog
        if item["slug"] not in RESERVED_SLUGS
    }
    extra_headers = [
        col
        for col in unique_keep_order(list(df.columns))
        if col in extra_by_header and col not in optional_fixed
    ]
    optional_present = [col for col in optional_fixed if col in df.columns]

    cols = unique_keep_order(
        required
        + (["BOPM"] if has_bopm else [])
        + optional_present
        + ([efetivo_col] if efetivo_col else [])
        + extra_headers
    )
    df = df[cols].copy()
    df["DATA"] = pd.to_datetime(df["DATA"], errors="coerce")
    df = df.dropna(subset=["DATA", "MODALIDADE", "EQUIPE", "PELOTÃO"])

    metric_excel = ["ABORDADOS", "CARROS", "MOTOS", "OCORRENCIAS"]
    if has_bopm:
        metric_excel.append("BOPM")
    metric_excel.extend(optional_present)
    for col in [*metric_excel, *extra_headers]:
        df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0).astype(int)
        if (df[col] < 0).any():
            raise ValueError(f"A coluna {col} contém valores negativos.")

    for col in ["MODALIDADE", "EQUIPE", "PELOTÃO"]:
        df[col] = df[col].astype(str).str.strip()
    if efetivo_col:
        df[efetivo_col] = df[efetivo_col].fillna("").astype(str)

    df = df[
        (df["MODALIDADE"] != "")
        & (df["EQUIPE"] != "")
        & (df["PELOTÃO"] != "")
    ]

    rows = []
    for _, row in df.iterrows():
        extras = {}
        for header in extra_headers:
            value = int(row[header])
            if value > 0:
                extras[extra_by_header[header]["id"]] = value
        payload = {
            "data": row["DATA"],
            "modalidade": row["MODALIDADE"],
            "equipe": row["EQUIPE"],
            "pelotao": row["PELOTÃO"],
            "abordados": int(row["ABORDADOS"]),
            "carros": int(row["CARROS"]),
            "motos": int(row["MOTOS"]),
            "bopm": int(row["BOPM"]) if has_bopm else 0,
            "ocorrencias": int(row["OCORRENCIAS"]),
            "pessoas_presas": 0,
            "condenados_capturados": 0,
            "veiculos_recuperados": 0,
            "observacao": "",
            "extras": extras,
            "efetivo": row[efetivo_col] if efetivo_col else "",
        }
        if "PESSOAS PRESAS" in df.columns:
            payload["pessoas_presas"] = int(row["PESSOAS PRESAS"])
        if "CONDENADOS CAPTURADOS" in df.columns:
            payload["condenados_capturados"] = int(row["CONDENADOS CAPTURADOS"])
        if "VEICULOS RECUPERADOS" in df.columns:
            payload["veiculos_recuperados"] = int(row["VEICULOS RECUPERADOS"])
        elif "VEÍCULOS RECUPERADOS" in df.columns:
            payload["veiculos_recuperados"] = int(row["VEÍCULOS RECUPERADOS"])
        rows.append(payload)

    return insert_many(engine, rows)


def show_importacao(engine) -> None:
    st.title("📥 Importar Excel")
    st.caption("Importe a planilha atual para dentro do banco do aplicativo.")

    uploaded = st.file_uploader("Selecione um arquivo .xlsx", type=["xlsx"])
    if not uploaded:
        return

    try:
        uploaded.seek(0)
        raw = pd.read_excel(uploaded, header=None)
        st.write("Pré-visualização:")
        st.dataframe(raw.head(10), width="stretch", hide_index=True)
    except Exception as exc:
        logger.exception("Falha ao ler Excel.")
        st.error(f"Erro ao ler a planilha: {exc}")
        return

    if st.button("Importar registros", type="primary"):
        try:
            uploaded.seek(0)
            count = import_excel(engine, uploaded)
        except ValueError as exc:
            st.error(str(exc))
            return
        except Exception:
            logger.exception("Falha ao importar Excel.")
            st.error("Não foi possível importar a planilha. Verifique o arquivo e tente novamente.")
            return

        st.success(f"{count} registro(s) importado(s) com sucesso.")
        st.rerun()


def show_exportacao(df: pd.DataFrame, catalog: list[dict], engine) -> None:
    st.title("📤 Exportar dados")

    if df.empty:
        st.info("Nenhum dado para exportar.")
        return

    export = df.copy()
    export["data"] = export["data"].dt.strftime("%d/%m/%Y")
    members_map = load_members_map(engine)
    export["efetivo"] = export["id"].map(
        lambda rid: format_members(members_map.get(int(rid), []))
    )
    extra_cols = [
        slug for slug in extra_slugs(catalog) if slug in export.columns
    ]
    export_cols = unique_keep_order(
        [
            "data",
            "modalidade",
            "equipe",
            "pelotao",
            "efetivo",
            *METRIC_COLS,
            *PRODUCTIVITY_COLS,
            *extra_cols,
            "observacao",
        ]
    )
    export = export[export_cols]
    rename = {
        "data": "DATA",
        "modalidade": "MODALIDADE",
        "equipe": "EQUIPE",
        "pelotao": "PELOTÃO",
        "efetivo": "EFETIVO",
        "abordados": "ABORDADOS",
        "carros": "CARROS",
        "motos": "MOTOS",
        "bopm": "BOPM",
        "ocorrencias": "OCORRENCIAS",
        "pessoas_presas": "PESSOAS PRESAS",
        "condenados_capturados": "CONDENADOS CAPTURADOS",
        "veiculos_recuperados": "VEICULOS RECUPERADOS",
        "observacao": "OBSERVACAO",
    }
    for item in catalog:
        if item["slug"] in extra_cols:
            rename[item["slug"]] = item["name"].upper()
    export = export.rename(columns=rename)

    st.dataframe(export, width="stretch", hide_index=True)

    csv = export.to_csv(index=False, sep=";", encoding="utf-8-sig")
    st.download_button(
        "Baixar CSV",
        data=csv,
        file_name="resultado_operacional.csv",
        mime="text/csv",
    )


def main() -> None:
    try:
        engine = get_cached_engine()
        catalog = list_indicators(engine)
        df = attach_extra_columns(load_data(engine), load_extras_wide(engine), catalog)
        assert_unique_columns(df, "dataframe principal")
    except Exception:
        logger.exception("Falha ao iniciar conexão com o banco.")
        st.error(
            "Não foi possível conectar ao banco de dados. "
            "Verifique a configuração de DATABASE_URL ou o arquivo SQLite local."
        )
        st.stop()

    st.sidebar.title("🚔 Resultado Operacional")
    st.sidebar.caption(f"Banco: {backend_label(engine)}")

    page = st.sidebar.radio(
        "Navegação",
        [
            "📊 Dashboard",
            "➕ Lançar resultado",
            "📋 Registros",
            "🚨 Ocorrências",
            "⚙️ Indicadores",
            "📥 Importar Excel",
            "📤 Exportar dados",
        ],
    )

    if page == "📊 Dashboard":
        show_dashboard(engine, df, catalog)
    elif page == "➕ Lançar resultado":
        show_lancamento(engine, df)
    elif page == "📋 Registros":
        show_registros(engine, df)
    elif page == "🚨 Ocorrências":
        show_ocorrencias(engine, df)
    elif page == "⚙️ Indicadores":
        show_indicadores(engine)
    elif page == "📥 Importar Excel":
        show_importacao(engine)
    elif page == "📤 Exportar dados":
        show_exportacao(df, catalog, engine)


if __name__ == "__main__":
    main()
