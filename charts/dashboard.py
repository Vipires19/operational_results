"""Gráficos do dashboard operacional."""

from __future__ import annotations

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go

BAR_COLOR = "#1e4a6e"
AREA_COLOR = "#2563eb"
MA_COLOR = "#c2410c"


def apply_layout(fig: go.Figure, height: int = 390) -> go.Figure:
    fig.update_layout(
        height=height,
        margin=dict(l=10, r=28, t=16, b=10),
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font=dict(size=12, color="#0f172a"),
        hoverlabel=dict(bgcolor="white", font_size=12),
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
        gridcolor="rgba(148,163,184,0.28)",
        zeroline=False,
        showline=False,
        title=None,
    )
    fig.update_yaxes(
        showgrid=True,
        gridcolor="rgba(148,163,184,0.18)",
        zeroline=False,
        showline=False,
        title=None,
        automargin=True,
    )
    return fig


def horizontal_bar(df: pd.DataFrame, x_col: str, y_col: str) -> go.Figure:
    ordered = df.sort_values(x_col, ascending=True)
    height = max(280, min(52 * max(len(ordered), 1) + 90, 900))

    fig = px.bar(
        ordered,
        x=x_col,
        y=y_col,
        orientation="h",
        text=x_col,
        color_discrete_sequence=[BAR_COLOR],
    )
    fig.update_traces(
        texttemplate="%{text:,.0f}",
        textposition="outside",
        cliponaxis=False,
        hovertemplate="<b>%{y}</b><br>Valor: %{x:,.0f}<extra></extra>",
        marker_line_width=0,
    )
    fig.update_layout(showlegend=False)
    return apply_layout(fig, height)


def area_daily(daily: pd.DataFrame, show_ma: bool = False) -> go.Figure:
    fig = px.area(
        daily,
        x="data",
        y="indice_producao",
        markers=True,
        color_discrete_sequence=[AREA_COLOR],
    )
    fig.update_traces(
        line_width=3,
        customdata=daily[
            ["abordados", "carros", "motos", "bopm", "ocorrencias"]
        ].to_numpy(),
        hovertemplate=(
            "<b>%{x|%d/%m/%Y}</b><br>"
            "Índice: %{y:,.0f}<br>"
            "Abordados: %{customdata[0]:,.0f}<br>"
            "Carros: %{customdata[1]:,.0f}<br>"
            "Motos: %{customdata[2]:,.0f}<br>"
            "BOPM: %{customdata[3]:,.0f}<br>"
            "Ocorrências: %{customdata[4]:,.0f}"
            "<extra></extra>"
        ),
    )
    fig.update_xaxes(tickformat="%d/%m")
    fig.update_layout(hovermode="x unified")

    if show_ma and "mm7" in daily.columns:
        fig.add_scatter(
            x=daily["data"],
            y=daily["mm7"],
            name="Média 7 dias",
            mode="lines",
            line=dict(color=MA_COLOR, width=2, dash="dash"),
            hovertemplate=(
                "<b>%{x|%d/%m/%Y}</b><br>Média 7 dias: %{y:,.1f}<extra></extra>"
            ),
        )

    return apply_layout(fig, 400)
