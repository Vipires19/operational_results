import logging
from datetime import date, datetime

import pandas as pd
import streamlit as st

from charts.dashboard import area_daily, horizontal_bar
from database.connection import backend_label, get_engine
from database.repository import (
    attach_extra_columns,
    create_indicator,
    delete_indicator,
    delete_result,
    get_result_extra_values,
    indicator_usage_counts,
    insert_many,
    insert_result,
    list_active_indicators,
    list_indicators,
    load_data,
    load_extras_wide,
    set_indicator_active,
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

METRIC_COLS = ["abordados", "carros", "motos", "bopm", "ocorrencias"]

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
        background: #f8fafc;
        border: 1px solid #e2e8f0;
        border-radius: 10px;
        padding: 0.7rem 0.9rem;
    }
    [data-testid="stMetricValue"] {
        font-size: 1.65rem;
        color: #0f172a;
    }
    [data-testid="stMetricLabel"] {
        color: #475569;
    }
    .small-muted {
        color: #64748b;
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


def extra_slugs(catalog: list[dict]) -> list[str]:
    return [item["slug"] for item in catalog]


def chart_labels(catalog: list[dict]) -> dict[str, str]:
    labels = dict(INDICATOR_LABELS)
    for item in catalog:
        labels[item["slug"]] = item["name"]
    return labels


def chart_keys(catalog: list[dict], include_index: bool = True) -> list[str]:
    keys = []
    if include_index:
        keys.append("indice_producao")
    keys.extend(METRIC_COLS)
    keys.extend(extra_slugs(catalog))
    return keys


def table_config(columns: list[str], catalog: list[dict] | None = None) -> dict:
    extra = set(extra_slugs(catalog or []))
    config = {}
    for col in columns:
        label = COLUMN_LABELS.get(col, col)
        if col in extra:
            name = next((i["name"] for i in (catalog or []) if i["slug"] == col), col)
            config[col] = number_column(name)
        elif col in METRIC_COLS or col == "indice_producao":
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
    cols = [c for c in [*METRIC_COLS, *slugs] if c in df.columns]
    grouped = df.groupby(by, as_index=False)[cols].sum()
    return add_score(grouped)


def ensure_metric_column(df: pd.DataFrame, metric: str) -> pd.DataFrame:
    out = df.copy()
    if metric not in out.columns:
        out[metric] = 0
    return out


def show_dashboard(df: pd.DataFrame, catalog: list[dict]) -> None:
    st.title("📊 Resultado Operacional")
    st.caption(
        "Controle e análise de produção operacional "
        "por dia, equipe, pelotão e modalidade."
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
    st.divider()

    if f.empty:
        st.warning("Nenhum resultado encontrado para os filtros selecionados.")
        return

    slugs = extra_slugs(catalog)
    labels = chart_labels(catalog)
    ranking_keys = chart_keys(catalog, include_index=True)
    extra_keys = chart_keys(catalog, include_index=False)

    left, right = st.columns([1.15, 1])

    with left:
        title_col, metric_col = st.columns([1.4, 1])
        title_col.subheader("🏆 Ranking de equipes")
        ranking_metric = metric_col.selectbox(
            "Indicador",
            ranking_keys,
            format_func=lambda x: labels.get(x, x),
            key="ranking_metric",
            label_visibility="collapsed",
        )
        ranking = ensure_metric_column(aggregate(f, "equipe", slugs), ranking_metric)
        plot_chart(horizontal_bar(ranking, ranking_metric, "equipe"))

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
        plot_chart(horizontal_bar(by_pelotao, pelotao_metric, "pelotao"))

    with right:
        title_col, metric_col = st.columns([1.4, 1])
        title_col.subheader("🚔 Resultados por modalidade")
        modalidade_metric = metric_col.selectbox(
            "Indicador por modalidade",
            extra_keys,
            format_func=lambda x: labels.get(x, x),
            key="modalidade_metric",
            label_visibility="collapsed",
        )
        by_mod = ensure_metric_column(aggregate(f, "modalidade", slugs), modalidade_metric)
        plot_chart(horizontal_bar(by_mod, modalidade_metric, "modalidade"))

    st.subheader("📋 Ranking detalhado")
    ranking_display = ranking.sort_values("indice_producao", ascending=False).copy()
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
    st.dataframe(
        ranking_display[ranking_cols],
        width="stretch",
        hide_index=True,
        column_config={
            "Posição": number_column("Posição"),
            **table_config(ranking_cols[1:]),
        },
    )

    st.subheader("📅 Resultado por dia")
    daily_display = daily.sort_values("data", ascending=False).copy()
    daily_display["data"] = daily_display["data"].dt.strftime("%d/%m/%Y")
    daily_cols = ["data", *METRIC_COLS, "indice_producao"]
    st.dataframe(
        daily_display[daily_cols],
        width="stretch",
        hide_index=True,
        column_config=table_config(daily_cols),
    )

    st.subheader("📑 Tabela operacional detalhada")
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


def show_lancamento(engine, df: pd.DataFrame) -> None:
    st.title("➕ Lançar resultado")
    st.caption("Registre o resultado de um serviço operacional.")

    pelotoes = options_from_data(df, "pelotao", PELOTOES_PADRAO)
    modalidades = options_from_data(df, "modalidade", MODALIDADES_PADRAO)
    active_extras = list_active_indicators(engine)

    with st.form("novo_resultado", clear_on_submit=True):
        c1, c2, c3 = st.columns(3)
        data_reg = c1.date_input("Data", date.today())
        modalidade = c2.selectbox("Modalidade", modalidades)
        equipe = c3.text_input("Equipe", placeholder="Ex.: TÁTICO COMANDO")

        c1, c2 = st.columns(2)
        pelotao = c1.selectbox("PELOTÃO", pelotoes)
        observacao = c2.text_area("Observação (opcional)", height=80)

        st.markdown("### Indicadores")
        c = st.columns(5)
        abordados = c[0].number_input("Abordados", min_value=0, step=1)
        carros = c[1].number_input("Carros", min_value=0, step=1)
        motos = c[2].number_input("Motos", min_value=0, step=1)
        bopm = c[3].number_input("BOPM", min_value=0, step=1)
        ocorrencias = c[4].number_input("Ocorrências", min_value=0, step=1)

        extra_inputs: dict[int, int] = {}
        if active_extras:
            st.markdown("### Indicadores adicionais")
            extra_cols = st.columns(min(3, len(active_extras)))
            for idx, item in enumerate(active_extras):
                extra_inputs[item["id"]] = extra_cols[idx % len(extra_cols)].number_input(
                    item["name"],
                    min_value=0,
                    step=1,
                    key=f"extra_ind_{item['id']}",
                )

        submitted = st.form_submit_button("Salvar resultado", type="primary")

    if not submitted:
        return

    if not equipe.strip():
        st.error("Informe a equipe.")
        return
    if not pelotao.strip():
        st.error("Informe o pelotão.")
        return

    extras = {ind_id: int(value) for ind_id, value in extra_inputs.items() if int(value) > 0}

    try:
        insert_result(
            engine,
            {
                "data": datetime.combine(data_reg, datetime.min.time()),
                "modalidade": modalidade.strip(),
                "equipe": equipe.strip().upper(),
                "pelotao": pelotao.strip().upper(),
                "abordados": int(abordados),
                "carros": int(carros),
                "motos": int(motos),
                "bopm": int(bopm),
                "ocorrencias": int(ocorrencias),
                "observacao": observacao.strip(),
                "extras": extras,
            },
        )
    except Exception:
        logger.exception("Falha ao salvar resultado.")
        st.error("Não foi possível salvar o resultado. Tente novamente.")
        return

    st.success("Resultado salvo com sucesso.")
    st.rerun()


@st.dialog("Detalhes do Resultado Operacional", width="large")
def show_result_details(record: pd.Series, extras: list[dict]) -> None:
    st.caption(f"ID {int(record['id'])}")
    c1, c2 = st.columns(2)
    c1.markdown(f"**Data:** {record['data'].strftime('%d/%m/%Y')}")
    c2.markdown(f"**Modalidade:** {record['modalidade']}")
    c1.markdown(f"**Equipe:** {record['equipe']}")
    c2.markdown(f"**Pelotão:** {record['pelotao']}")

    st.divider()
    metrics = st.columns(6)
    metrics[0].metric("Abordados", fmt_int(record["abordados"]))
    metrics[1].metric("Carros", fmt_int(record["carros"]))
    metrics[2].metric("Motos", fmt_int(record["motos"]))
    metrics[3].metric("BOPM", fmt_int(record["bopm"]))
    metrics[4].metric("Ocorrências", fmt_int(record["ocorrencias"]))
    score = int(
        record["abordados"] * 2
        + record["carros"]
        + record["motos"]
        + record["ocorrencias"] * 5
    )
    metrics[5].metric("Índice", fmt_int(score))

    extras_shown = [item for item in extras if int(item["value"]) > 0]
    if extras_shown:
        st.markdown("**Indicadores adicionais**")
        for item in extras_shown:
            st.write(f"{item['name']}: **{fmt_int(item['value'])}**")

    observacao = str(record.get("observacao") or "").strip()
    st.markdown("**Observação**")
    if observacao:
        st.info(observacao)
    else:
        st.caption("Este registro não possui observação.")

    created = str(record.get("created_at") or "").strip()
    if created:
        st.caption(f"Criado em: {created}")


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
    st.caption("Selecione uma linha para ver a observação completa e os indicadores adicionais.")

    selected_pos = event.selection.rows if event and event.selection else []
    selected_record = df.iloc[selected_pos[0]] if selected_pos else None

    actions = st.columns([1, 1, 2])
    with actions[0]:
        if st.button("Ver detalhes", disabled=selected_record is None, type="primary"):
            extras = get_result_extra_values(engine, int(selected_record["id"]))
            show_result_details(selected_record, extras)

    st.divider()
    st.subheader("Excluir registro")
    selected = st.selectbox("Selecione o ID", df["id"].tolist())

    if st.button("Excluir selecionado"):
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
    options = {f"{item['name']} ({'ativo' if item['active'] else 'inativo'})": item for item in catalog}
    chosen_label = st.selectbox("Indicador", list(options.keys()))
    chosen = options[chosen_label]
    c1, c2, c3 = st.columns(3)
    if c1.button("Ativar"):
        set_indicator_active(engine, chosen["id"], True)
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
        "nos gráficos e na exportação."
    )


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
    catalog = list_indicators(engine)
    extra_by_header = {item["name"].strip().upper(): item for item in catalog}
    extra_headers = [col for col in df.columns if col in extra_by_header]

    cols = required + (["BOPM"] if has_bopm else []) + extra_headers
    df = df[cols].copy()
    df["DATA"] = pd.to_datetime(df["DATA"], errors="coerce")
    df = df.dropna(subset=["DATA", "MODALIDADE", "EQUIPE", "PELOTÃO"])

    metric_excel = ["ABORDADOS", "CARROS", "MOTOS", "OCORRENCIAS"]
    if has_bopm:
        metric_excel.append("BOPM")
    for col in [*metric_excel, *extra_headers]:
        df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0).astype(int)
        if (df[col] < 0).any():
            raise ValueError(f"A coluna {col} contém valores negativos.")

    for col in ["MODALIDADE", "EQUIPE", "PELOTÃO"]:
        df[col] = df[col].astype(str).str.strip()

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
        rows.append(
            {
                "data": row["DATA"],
                "modalidade": row["MODALIDADE"],
                "equipe": row["EQUIPE"],
                "pelotao": row["PELOTÃO"],
                "abordados": int(row["ABORDADOS"]),
                "carros": int(row["CARROS"]),
                "motos": int(row["MOTOS"]),
                "bopm": int(row["BOPM"]) if has_bopm else 0,
                "ocorrencias": int(row["OCORRENCIAS"]),
                "observacao": "",
                "extras": extras,
            }
        )

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


def show_exportacao(df: pd.DataFrame, catalog: list[dict]) -> None:
    st.title("📤 Exportar dados")

    if df.empty:
        st.info("Nenhum dado para exportar.")
        return

    export = df.copy()
    export["data"] = export["data"].dt.strftime("%d/%m/%Y")
    extra_cols = [item["slug"] for item in catalog if item["slug"] in export.columns]
    export = export[
        [
            "data",
            "modalidade",
            "equipe",
            "pelotao",
            *METRIC_COLS,
            *extra_cols,
            "observacao",
        ]
    ]
    rename = {
        "data": "DATA",
        "modalidade": "MODALIDADE",
        "equipe": "EQUIPE",
        "pelotao": "PELOTÃO",
        "abordados": "ABORDADOS",
        "carros": "CARROS",
        "motos": "MOTOS",
        "bopm": "BOPM",
        "ocorrencias": "OCORRENCIAS",
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
            "⚙️ Indicadores",
            "📥 Importar Excel",
            "📤 Exportar dados",
        ],
    )

    if page == "📊 Dashboard":
        show_dashboard(df, catalog)
    elif page == "➕ Lançar resultado":
        show_lancamento(engine, df)
    elif page == "📋 Registros":
        show_registros(engine, df)
    elif page == "⚙️ Indicadores":
        show_indicadores(engine)
    elif page == "📥 Importar Excel":
        show_importacao(engine)
    elif page == "📤 Exportar dados":
        show_exportacao(df, catalog)


if __name__ == "__main__":
    main()
