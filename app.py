import sqlite3
from pathlib import Path
from datetime import date, datetime

import pandas as pd
import plotly.express as px
import streamlit as st


# ============================================================
# CONFIGURAÇÃO
# ============================================================

BASE_DIR = Path(__file__).resolve().parent
DB_PATH = BASE_DIR / "data" / "resultado_operacional.db"

st.set_page_config(
    page_title="Resultado Operacional",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded",
)

CSS = """
<style>
    .block-container {
        padding-top: 1.5rem;
        padding-bottom: 2rem;
    }

    [data-testid="stMetricValue"] {
        font-size: 1.8rem;
    }

    .small-muted {
        color: #64748b;
        font-size: .9rem;
    }
</style>
"""

st.markdown(CSS, unsafe_allow_html=True)


# ============================================================
# BANCO DE DADOS
# ============================================================

def get_conn():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(DB_PATH)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS resultados (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            data TEXT NOT NULL,
            modalidade TEXT NOT NULL,
            equipe TEXT NOT NULL,
            pelotao TEXT NOT NULL,
            abordados INTEGER NOT NULL DEFAULT 0,
            carros INTEGER NOT NULL DEFAULT 0,
            motos INTEGER NOT NULL DEFAULT 0,
            bopm INTEGER NOT NULL DEFAULT 0,
            ocorrencias INTEGER NOT NULL DEFAULT 0,
            observacao TEXT,
            created_at TEXT NOT NULL
        )
    """)

    conn.commit()

    return conn


def load_data():
    conn = get_conn()

    df = pd.read_sql_query(
        "SELECT * FROM resultados ORDER BY data DESC, id DESC",
        conn
    )

    conn.close()

    if not df.empty:
        df["data"] = pd.to_datetime(df["data"])

    return df


def insert_result(row):
    conn = get_conn()

    conn.execute("""
        INSERT INTO resultados
        (
            data,
            modalidade,
            equipe,
            pelotao,
            abordados,
            carros,
            motos,
            bopm,
            ocorrencias,
            observacao,
            created_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        row["data"].strftime("%Y-%m-%d"),
        row["modalidade"],
        row["equipe"],
        row["pelotao"],
        row["abordados"],
        row["carros"],
        row["motos"],
        row["bopm"],
        row["ocorrencias"],
        row["observacao"],
        datetime.now().isoformat(timespec="seconds"),
    ))

    conn.commit()
    conn.close()


def delete_result(result_id):
    conn = get_conn()

    conn.execute(
        "DELETE FROM resultados WHERE id = ?",
        (int(result_id),)
    )

    conn.commit()
    conn.close()


# ============================================================
# IMPORTAÇÃO DO EXCEL
# ============================================================

def import_excel(uploaded_file):
    raw = pd.read_excel(uploaded_file, header=None)

    # Procura a linha que contém DATA / MODALIDADE / EQUIPE.
    header_idx = None

    for i in range(min(len(raw), 30)):
        vals = [
            str(v).strip().upper()
            for v in raw.iloc[i].tolist()
        ]

        if "DATA" in vals and "MODALIDADE" in vals and "EQUIPE" in vals:
            header_idx = i
            break

    if header_idx is None:
        raise ValueError(
            "Não encontrei a linha de cabeçalho esperada na planilha."
        )

    df = raw.iloc[header_idx + 1:].copy()

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
        "BOPM",
        "OCORRENCIAS",
    ]

    missing = [
        c for c in required
        if c not in df.columns
    ]

    if missing:
        raise ValueError(
            f"Colunas ausentes: {', '.join(missing)}"
        )

    df = df[required].copy()

    df["DATA"] = pd.to_datetime(
        df["DATA"],
        errors="coerce"
    )

    df = df.dropna(
        subset=[
            "DATA",
            "MODALIDADE",
            "EQUIPE",
            "PELOTÃO"
        ]
    )

    for c in [
        "ABORDADOS",
        "CARROS",
        "MOTOS",
        "BOPM",
        "OCORRENCIAS"
    ]:
        df[c] = (
            pd.to_numeric(
                df[c],
                errors="coerce"
            )
            .fillna(0)
            .astype(int)
        )

    df["MODALIDADE"] = (
        df["MODALIDADE"]
        .astype(str)
        .str.strip()
    )

    df["EQUIPE"] = (
        df["EQUIPE"]
        .astype(str)
        .str.strip()
    )

    df["PELOTÃO"] = (
        df["PELOTÃO"]
        .astype(str)
        .str.strip()
    )

    # Ignora linhas vazias.
    df = df[
        (df["MODALIDADE"] != "") &
        (df["EQUIPE"] != "") &
        (df["PELOTÃO"] != "")
    ]

    conn = get_conn()

    for _, r in df.iterrows():

        conn.execute("""
            INSERT INTO resultados
            (
                data,
                modalidade,
                equipe,
                pelotao,
                abordados,
                carros,
                motos,
                bopm,
                ocorrencias,
                observacao,
                created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            r["DATA"].strftime("%Y-%m-%d"),
            r["MODALIDADE"],
            r["EQUIPE"],
            r["PELOTÃO"],
            int(r["ABORDADOS"]),
            int(r["CARROS"]),
            int(r["MOTOS"]),
            int(r["BOPM"]),
            int(r["OCORRENCIAS"]),
            "",
            datetime.now().isoformat(timespec="seconds"),
        ))

    conn.commit()
    conn.close()

    return len(df)


# ============================================================
# MÉTRICAS
# ============================================================

def production_score(df):
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


def filtered_data(
    df,
    start,
    end,
    modalidade,
    pelotao,
    equipe
):
    if df.empty:
        return df.copy()

    out = df[
        (df["data"].dt.date >= start) &
        (df["data"].dt.date <= end)
    ].copy()

    if modalidade != "Todos":
        out = out[
            out["modalidade"] == modalidade
        ]

    if pelotao != "Todos":
        out = out[
            out["pelotao"] == pelotao
        ]

    if equipe != "Todas":
        out = out[
            out["equipe"] == equipe
        ]

    return out


# ============================================================
# ESTILO DOS GRÁFICOS
# ============================================================

def chart_layout(fig, height=390):

    fig.update_layout(
        height=height,
        margin=dict(
            l=10,
            r=20,
            t=20,
            b=10
        ),
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font=dict(size=12),
        hovermode="x unified",
        legend=dict(
            orientation="h",
            yanchor="bottom",
            y=1.02,
            xanchor="right",
            x=1,
        ),
    )

    fig.update_xaxes(
        showgrid=True,
        gridcolor="rgba(128,128,128,0.16)",
        zeroline=False,
        showline=False,
    )

    fig.update_yaxes(
        showgrid=True,
        gridcolor="rgba(128,128,128,0.10)",
        zeroline=False,
        showline=False,
    )

    return fig


# ============================================================
# DASHBOARD
# ============================================================

def show_dashboard(df):

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

    # --------------------------------------------------------
    # FILTROS
    # --------------------------------------------------------

    min_date = df["data"].min().date()
    max_date = df["data"].max().date()

    with st.sidebar:

        st.header("Filtros")

        start = st.date_input(
            "Data inicial",
            min_date,
            min_value=min_date,
            max_value=max_date,
        )

        end = st.date_input(
            "Data final",
            max_date,
            min_value=min_date,
            max_value=max_date,
        )

        modalidades = [
            "Todos"
        ] + sorted(
            df["modalidade"]
            .dropna()
            .unique()
            .tolist()
        )

        modalidade = st.selectbox(
            "Modalidade",
            modalidades
        )

        temp = (
            df
            if modalidade == "Todos"
            else df[
                df["modalidade"] == modalidade
            ]
        )

        pelotoes = [
            "Todos"
        ] + sorted(
            temp["pelotao"]
            .dropna()
            .unique()
            .tolist()
        )

        pelotao = st.selectbox(
            "Pelotão",
            pelotoes
        )

        temp2 = (
            temp
            if pelotao == "Todos"
            else temp[
                temp["pelotao"] == pelotao
            ]
        )

        equipes = [
            "Todas"
        ] + sorted(
            temp2["equipe"]
            .dropna()
            .unique()
            .tolist()
        )

        equipe = st.selectbox(
            "Equipe",
            equipes
        )

    # --------------------------------------------------------
    # VALIDAÇÃO DAS DATAS
    # --------------------------------------------------------

    if start > end:

        st.error(
            "A data inicial não pode ser posterior "
            "à data final."
        )

        return

    # --------------------------------------------------------
    # APLICA FILTROS
    # --------------------------------------------------------

    f = filtered_data(
        df,
        start,
        end,
        modalidade,
        pelotao,
        equipe
    )

    # --------------------------------------------------------
    # KPIs
    # --------------------------------------------------------

    total_abordados = int(
        f["abordados"].sum()
    )

    total_carros = int(
        f["carros"].sum()
    )

    total_motos = int(
        f["motos"].sum()
    )

    total_bopm = int(
        f["bopm"].sum()
    )

    total_ocorrencias = int(
        f["ocorrencias"].sum()
    )

    cols = st.columns(5)

    cols[0].metric(
        "Abordados",
        f"{total_abordados:,}".replace(",", ".")
    )

    cols[1].metric(
        "Carros",
        f"{total_carros:,}".replace(",", ".")
    )

    cols[2].metric(
        "Motos",
        f"{total_motos:,}".replace(",", ".")
    )

    cols[3].metric(
        "BOPM",
        f"{total_bopm:,}".replace(",", ".")
    )

    cols[4].metric(
        "Ocorrências",
        f"{total_ocorrencias:,}".replace(",", ".")
    )

    st.divider()

    if f.empty:

        st.warning(
            "Nenhum registro encontrado "
            "com os filtros selecionados."
        )

        return

    # ========================================================
    # PRIMEIRA LINHA DE GRÁFICOS
    # ========================================================

    left, right = st.columns([1.15, 1])

    # --------------------------------------------------------
    # RANKING DE EQUIPES
    # --------------------------------------------------------

    with left:

        st.subheader("🏆 Ranking de equipes")

        ranking = (
            f.groupby(
                "equipe",
                as_index=False
            )[
                [
                    "abordados",
                    "carros",
                    "motos",
                    "bopm",
                    "ocorrencias",
                ]
            ]
            .sum()
        )

        ranking["indice_producao"] = (
            production_score(ranking)
        )

        ranking = ranking.sort_values(
            "indice_producao",
            ascending=False
        )

        rc = ranking.sort_values(
            "indice_producao"
        )

        fig = px.bar(
            rc,
            x="indice_producao",
            y="equipe",
            orientation="h",
            text="indice_producao",
            labels={
                "indice_producao": "Índice",
                "equipe": "",
            },
        )

        fig.update_traces(
            texttemplate="%{text:,.0f}",
            textposition="outside",
            cliponaxis=False,
            hovertemplate=(
                "<b>%{y}</b><br>"
                "Índice: %{x:,.0f}"
                "<extra></extra>"
            ),
        )

        fig.update_xaxes(title=None)

        fig.update_yaxes(
            title=None,
            automargin=True
        )

        st.plotly_chart(
            chart_layout(fig, 430),
            use_container_width=True
        )

    # --------------------------------------------------------
    # EVOLUÇÃO DIÁRIA
    # --------------------------------------------------------

    with right:

        st.subheader("📈 Evolução diária")

        daily = (
            f.groupby(
                "data",
                as_index=False
            )[
                [
                    "abordados",
                    "carros",
                    "motos",
                    "bopm",
                    "ocorrencias",
                ]
            ]
            .sum()
        )

        daily["indice_producao"] = (
            production_score(daily)
        )

        fig = px.area(
            daily,
            x="data",
            y="indice_producao",
            markers=True,
            labels={
                "indice_producao": "Índice",
                "data": "",
            },
        )

        fig.update_traces(
            line_width=3,
            hovertemplate=(
                "<b>%{x|%d/%m/%Y}</b><br>"
                "Índice: %{y:,.0f}"
                "<extra></extra>"
            ),
        )

        fig.update_xaxes(
            tickformat="%d/%m",
            title=None
        )

        fig.update_yaxes(
            title=None
        )

        st.plotly_chart(
            chart_layout(fig, 430),
            use_container_width=True
        )

    # ========================================================
    # SEGUNDA LINHA DE GRÁFICOS
    # ========================================================

    left, right = st.columns([1.15, 1])

    # --------------------------------------------------------
    # PRODUÇÃO POR PELOTÃO
    # --------------------------------------------------------

    with left:

        st.subheader("🎖️ Produção por pelotão")

        p = (
            f.groupby(
                "pelotao",
                as_index=False
            )[
                [
                    "abordados",
                    "carros",
                    "motos",
                    "bopm",
                    "ocorrencias",
                ]
            ]
            .sum()
        )

        p["indice_producao"] = (
            production_score(p)
        )

        pc = p.sort_values(
            "indice_producao"
        )

        fig = px.bar(
            pc,
            x="indice_producao",
            y="pelotao",
            orientation="h",
            text="indice_producao",
            labels={
                "indice_producao": "Índice",
                "pelotao": "",
            },
        )

        fig.update_traces(
            texttemplate="%{text:,.0f}",
            textposition="outside",
            cliponaxis=False,
            hovertemplate=(
                "<b>%{y}</b><br>"
                "Índice: %{x:,.0f}"
                "<extra></extra>"
            ),
        )

        fig.update_xaxes(title=None)

        fig.update_yaxes(
            title=None,
            automargin=True
        )

        st.plotly_chart(
            chart_layout(fig, 380),
            use_container_width=True
        )

    # --------------------------------------------------------
    # RESULTADOS POR MODALIDADE
    # --------------------------------------------------------

    with right:

        st.subheader("🚔 Resultados por modalidade")

        m = (
            f.groupby(
                "modalidade",
                as_index=False
            )[
                [
                    "abordados",
                    "carros",
                    "motos",
                    "bopm",
                    "ocorrencias",
                ]
            ]
            .sum()
        )

        ml = m.melt(
            id_vars="modalidade",
            value_vars=[
                "abordados",
                "carros",
                "motos",
                "bopm",
                "ocorrencias",
            ],
            var_name="indicador",
            value_name="quantidade",
        )

        ml["indicador"] = ml[
            "indicador"
        ].map({
            "abordados": "Abordados",
            "carros": "Carros",
            "motos": "Motos",
            "bopm": "BOPM",
            "ocorrencias": "Ocorrências",
        })

        fig = px.bar(
            ml,
            x="modalidade",
            y="quantidade",
            color="indicador",
            barmode="group",
            text_auto=True,
            labels={
                "quantidade": "Quantidade",
                "modalidade": "",
            },
        )

        fig.update_traces(
            hovertemplate=(
                "<b>%{x}</b><br>"
                "%{fullData.name}: %{y:,.0f}"
                "<extra></extra>"
            )
        )

        fig.update_xaxes(title=None)

        fig.update_yaxes(title=None)

        st.plotly_chart(
            chart_layout(fig, 380),
            use_container_width=True
        )

    # ========================================================
    # INDICADOR ESPECÍFICO POR EQUIPE
    # ========================================================

    st.subheader("📊 Indicador por equipe")

    indicator = st.selectbox(
        "Escolha o indicador para comparar as equipes",
        [
            "abordados",
            "carros",
            "motos",
            "bopm",
            "ocorrencias",
        ],
        format_func=lambda x: {
            "abordados": "Abordados",
            "carros": "Carros",
            "motos": "Motos",
            "bopm": "BOPM",
            "ocorrencias": "Ocorrências",
        }[x],
    )

    by_team = (
        f.groupby(
            "equipe",
            as_index=False
        )[indicator]
        .sum()
        .sort_values(indicator)
    )

    fig = px.bar(
        by_team,
        x=indicator,
        y="equipe",
        orientation="h",
        text=indicator,
        labels={
            indicator: "Quantidade",
            "equipe": "",
        },
    )

    fig.update_traces(
        texttemplate="%{text:,.0f}",
        textposition="outside",
        cliponaxis=False,
    )

    fig.update_xaxes(title=None)

    fig.update_yaxes(
        title=None,
        automargin=True
    )

    chart_height = max(
        320,
        55 * len(by_team)
    )

    st.plotly_chart(
        chart_layout(
            fig,
            chart_height
        ),
        use_container_width=True
    )

    # ========================================================
    # RANKING DETALHADO
    # ========================================================

    st.subheader("📋 Ranking detalhado")

    ranking_display = ranking.copy()

    ranking_display = ranking_display.rename(
        columns={
            "indice_producao": "Índice"
        }
    )

    ranking_display.insert(
        0,
        "Posição",
        range(
            1,
            len(ranking_display) + 1
        )
    )

    st.dataframe(
        ranking_display,
        use_container_width=True,
        hide_index=True
    )

    # ========================================================
    # RESULTADO POR DIA
    # ========================================================

    st.subheader("📅 Resultado por dia")

    daily_display = (
        f.groupby(
            "data",
            as_index=False
        )[
            [
                "abordados",
                "carros",
                "motos",
                "bopm",
                "ocorrencias",
            ]
        ]
        .sum()
    )

    daily_display["data"] = (
        daily_display["data"]
        .dt.strftime("%d/%m/%Y")
    )

    st.dataframe(
        daily_display.sort_values(
            "data",
            ascending=False
        ),
        use_container_width=True,
        hide_index=True
    )


# ============================================================
# LANÇAMENTO DE RESULTADO
# ============================================================

def show_lancamento():

    st.title("➕ Lançar resultado")

    st.caption(
        "Registre o resultado de um serviço operacional."
    )

    df = load_data()

    pelotoes_existentes = [
        "1° PELOTÃO",
        "2° PELOTÃO",
    ]

    modalidades_existentes = [
        "FT",
        "ROCAM",
    ]

    with st.form(
        "novo_resultado",
        clear_on_submit=True
    ):

        c1, c2, c3 = st.columns(3)

        data_reg = c1.date_input(
            "Data",
            date.today()
        )

        modalidade = c2.selectbox(
            "Modalidade",
            modalidades_existentes
        )

        equipe = c3.text_input(
            "Equipe",
            placeholder="Ex.: TÁTICO COMANDO"
        )

        c1, c2 = st.columns(2)

        pelotao = c1.selectbox(
            "PELOTÃO",
            pelotoes_existentes
        )

        observacao = c2.text_input(
            "Observação (opcional)"
        )

        st.markdown("### Indicadores")

        c = st.columns(5)

        abordados = c[0].number_input(
            "Abordados",
            min_value=0,
            step=1
        )

        carros = c[1].number_input(
            "Carros",
            min_value=0,
            step=1
        )

        motos = c[2].number_input(
            "Motos",
            min_value=0,
            step=1
        )

        bopm = c[3].number_input(
            "BOPM",
            min_value=0,
            step=1
        )

        ocorrencias = c[4].number_input(
            "Ocorrências",
            min_value=0,
            step=1
        )

        submitted = st.form_submit_button(
            "Salvar resultado",
            type="primary"
        )

    if submitted:

        if not equipe.strip():
            st.error(
                "Informe a equipe."
            )
            return

        if not pelotao.strip():
            st.error(
                "Informe o pelotão."
            )
            return

        insert_result({
            "data": datetime.combine(
                data_reg,
                datetime.min.time()
            ),
            "modalidade": modalidade.strip(),
            "equipe": equipe.strip().upper(),
            "pelotao": pelotao.strip().upper(),
            "abordados": int(abordados),
            "carros": int(carros),
            "motos": int(motos),
            "bopm": int(bopm),
            "ocorrencias": int(ocorrencias),
            "observacao": observacao.strip(),
        })

        st.success(
            "Resultado salvo com sucesso."
        )

        st.rerun()


# ============================================================
# REGISTROS
# ============================================================

def show_registros():

    st.title("📋 Registros")

    df = load_data()

    if df.empty:

        st.info(
            "Nenhum registro cadastrado."
        )

        return

    display = df.copy()

    display["data"] = (
        display["data"]
        .dt.strftime("%d/%m/%Y")
    )

    display = display[
        [
            "id",
            "data",
            "modalidade",
            "equipe",
            "pelotao",
            "abordados",
            "carros",
            "motos",
            "bopm",
            "ocorrencias",
            "observacao",
        ]
    ]

    st.dataframe(
        display,
        use_container_width=True,
        hide_index=True
    )

    st.divider()

    st.subheader(
        "Excluir registro"
    )

    ids = df["id"].tolist()

    selected = st.selectbox(
        "Selecione o ID",
        ids
    )

    if st.button(
        "Excluir selecionado"
    ):

        delete_result(selected)

        st.success(
            f"Registro {selected} excluído."
        )

        st.rerun()


# ============================================================
# IMPORTAÇÃO
# ============================================================

def show_importacao():

    st.title("📥 Importar Excel")

    st.caption(
        "Importe a planilha atual para dentro "
        "do banco do aplicativo."
    )

    uploaded = st.file_uploader(
        "Selecione um arquivo .xlsx",
        type=["xlsx"]
    )

    if uploaded:

        try:

            raw = pd.read_excel(
                uploaded,
                header=None
            )

            st.write(
                "Pré-visualização:"
            )

            st.dataframe(
                raw.head(10),
                use_container_width=True,
                hide_index=True
            )

            if st.button(
                "Importar registros",
                type="primary"
            ):

                count = import_excel(
                    uploaded
                )

                st.success(
                    f"{count} registro(s) "
                    "importado(s) com sucesso."
                )

                st.rerun()

        except Exception as e:

            st.error(
                f"Erro ao ler a planilha: {e}"
            )


# ============================================================
# EXPORTAÇÃO
# ============================================================

def show_exportacao():

    st.title("📤 Exportar dados")

    df = load_data()

    if df.empty:

        st.info(
            "Nenhum dado para exportar."
        )

        return

    export = df.copy()

    export["data"] = (
        export["data"]
        .dt.strftime("%d/%m/%Y")
    )

    export = export[
        [
            "data",
            "modalidade",
            "equipe",
            "pelotao",
            "abordados",
            "carros",
            "motos",
            "bopm",
            "ocorrencias",
            "observacao",
        ]
    ]

    export.columns = [
        "DATA",
        "MODALIDADE",
        "EQUIPE",
        "PELOTÃO",
        "ABORDADOS",
        "CARROS",
        "MOTOS",
        "BOPM",
        "OCORRENCIAS",
        "OBSERVACAO",
    ]

    st.dataframe(
        export,
        use_container_width=True,
        hide_index=True
    )

    csv = export.to_csv(
        index=False,
        sep=";",
        encoding="utf-8-sig"
    )

    st.download_button(
        "Baixar CSV",
        data=csv,
        file_name="resultado_operacional.csv",
        mime="text/csv",
    )


# ============================================================
# MAIN
# ============================================================

def main():

    get_conn()

    df = load_data()

    st.sidebar.title(
        "🚔 Resultado Operacional"
    )

    st.sidebar.caption(
        "Controle operacional"
    )

    page = st.sidebar.radio(
        "Navegação",
        [
            "📊 Dashboard",
            "➕ Lançar resultado",
            "📋 Registros",
            "📥 Importar Excel",
            "📤 Exportar dados",
        ]
    )

    if page == "📊 Dashboard":

        show_dashboard(df)

    elif page == "➕ Lançar resultado":

        show_lancamento()

    elif page == "📋 Registros":

        show_registros()

    elif page == "📥 Importar Excel":

        show_importacao()

    elif page == "📤 Exportar dados":

        show_exportacao()


# ============================================================
# EXECUÇÃO
# ============================================================

if __name__ == "__main__":
    main()