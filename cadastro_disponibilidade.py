"""
cadastro_disponibilidade.py
────────────────────────────
Módulo de Cadastro de Disponibilidade para o app de Escala de Louvor.

Exporta uma única função pública:
    render_cadastro_disponibilidade(client)

Basta chamar essa função dentro da aba/página correspondente
no app_escala_louvor.py.
"""

from datetime import date, timedelta

import pandas as pd
import streamlit as st


# ── Helpers ───────────────────────────────────────────────────────

def _proximos_domingos(n: int = 8, a_partir: date | None = None) -> list[date]:
    """Retorna os próximos `n` domingos a partir de `a_partir` (padrão: hoje)."""
    hoje = a_partir or date.today()
    dias_ate_domingo = (6 - hoje.weekday()) % 7  # weekday: seg=0 … dom=6
    primeiro = hoje + timedelta(days=dias_ate_domingo if dias_ate_domingo else 7)
    return [primeiro + timedelta(weeks=i) for i in range(n)]


def _nomes_unicos(df_integrantes: pd.DataFrame) -> list[str]:
    """Extrai lista ordenada de nomes únicos do DataFrame de integrantes."""
    if df_integrantes.empty or "nome" not in df_integrantes.columns:
        return []
    return sorted(df_integrantes["nome"].dropna().unique().tolist())


def _disponibilidade_do_membro(
    df_disp: pd.DataFrame, nome: str
) -> set[date]:
    """Retorna o conjunto de datas já registradas para um membro."""
    if df_disp.empty:
        return set()
    filtro = df_disp[df_disp["nome"] == nome]
    datas = pd.to_datetime(filtro["data"], errors="coerce").dt.date
    return set(datas.dropna().tolist())


# ── Render principal ──────────────────────────────────────────────

def render_cadastro_disponibilidade(client) -> None:
    """
    Renderiza o módulo completo de Cadastro de Disponibilidade.

    Parameters
    ----------
    client : SheetsClient
        Instância retornada por get_sheets_client().
    """

    st.markdown("### 📅 Cadastro de Disponibilidade")
    st.caption(
        "Selecione o integrante e marque os domingos em que estará disponível. "
        "Registros existentes serão atualizados automaticamente."
    )

    # ── Carrega dados ──────────────────────────────────────────────
    with st.spinner("Carregando integrantes..."):
        df_integrantes = client.ler_integrantes()

    nomes = _nomes_unicos(df_integrantes)

    if not nomes:
        st.warning(
            "Nenhum integrante cadastrado ainda. "
            "Adicione músicos na aba **Integrantes** antes de registrar disponibilidade."
        )
        return

    # ── Identificação ──────────────────────────────────────────────
    st.markdown("#### 1. Quem é você?")

    col_nome, col_periodo = st.columns([2, 1])

    with col_nome:
        nome_selecionado = st.selectbox(
            "Integrante",
            options=nomes,
            index=0,
            help="Selecione seu nome na lista.",
        )

    with col_periodo:
        periodo = st.selectbox(
            "Período disponível",
            options=["manha", "tarde", "noite", "dia_todo"],
            format_func=lambda x: {
                "manha": "☀️ Manhã",
                "tarde": "🌤️ Tarde",
                "noite": "🌙 Noite",
                "dia_todo": "🌞 Dia todo",
            }[x],
        )

    # ── Carrega disponibilidade já registrada ──────────────────────
    with st.spinner("Verificando registros anteriores..."):
        df_disp = client.ler_disponibilidade()

    datas_ja_salvas = _disponibilidade_do_membro(df_disp, nome_selecionado)

    # ── Seleção de datas ───────────────────────────────────────────
    st.markdown("#### 2. Em quais domingos você estará disponível?")

    num_semanas = st.slider(
        "Quantas semanas exibir",
        min_value=4, max_value=16, value=8, step=4,
    )
    domingos = _proximos_domingos(n=num_semanas)

    # Exibe os domingos como checkboxes agrupados por mês
    datas_selecionadas: list[date] = []
    mes_atual = None

    for domingo in domingos:
        # Cabeçalho de mês
        nome_mes = domingo.strftime("%B de %Y").capitalize()
        if nome_mes != mes_atual:
            st.markdown(f"**{nome_mes}**")
            mes_atual = nome_mes

        ja_marcado = domingo in datas_ja_salvas
        label = domingo.strftime("%d/%m/%Y — %A").replace(
            "Sunday", "Domingo"
        )  # fallback; strftime já retorna em português em locales configurados

        # Pré-marca datas já salvas
        marcado = st.checkbox(
            label=f"{'🔄 ' if ja_marcado else ''}{domingo.strftime('%d/%m/%Y')} "
                  f"{'(já registrado)' if ja_marcado else ''}",
            value=ja_marcado,
            key=f"disp_{nome_selecionado}_{domingo.isoformat()}",
        )
        if marcado:
            datas_selecionadas.append(domingo)

    # ── Resumo antes de salvar ─────────────────────────────────────
    st.markdown("---")

    if not datas_selecionadas:
        st.info("Nenhuma data selecionada. Marque ao menos um domingo para salvar.")
        return

    novas = [d for d in datas_selecionadas if d not in datas_ja_salvas]
    atualizacoes = [d for d in datas_selecionadas if d in datas_ja_salvas]

    col_r1, col_r2, col_r3 = st.columns(3)
    with col_r1:
        st.metric("Total selecionado", len(datas_selecionadas))
    with col_r2:
        st.metric("Novos registros", len(novas))
    with col_r3:
        st.metric("Atualizações", len(atualizacoes))

    # ── Botão salvar ───────────────────────────────────────────────
    if st.button("💾 Salvar Disponibilidade", type="primary", use_container_width=True):
        with st.spinner("Salvando no Google Sheets..."):
            resultado = client.salvar_disponibilidade(
                nome=nome_selecionado,
                datas=datas_selecionadas,
                periodo=periodo,
            )

        st.success(
            f"✅ Disponibilidade de **{nome_selecionado}** salva! "
            f"{resultado['inseridos']} novo(s) registro(s), "
            f"{resultado['atualizados']} atualização(ões)."
        )

        # Exibe confirmação detalhada
        with st.expander("Ver datas salvas"):
            for d in sorted(datas_selecionadas):
                status = "🔄 Atualizado" if d in datas_ja_salvas else "✅ Novo"
                st.markdown(f"- {d.strftime('%d/%m/%Y')} — {status}")

    # ── Histórico do membro ────────────────────────────────────────
    with st.expander(f"📋 Histórico completo de {nome_selecionado}"):
        if df_disp.empty:
            st.info("Nenhum registro encontrado.")
        else:
            historico = df_disp[df_disp["nome"] == nome_selecionado].copy()
            if historico.empty:
                st.info("Este integrante ainda não tem registros de disponibilidade.")
            else:
                historico = historico.sort_values("data", ascending=True)
                historico["data"] = pd.to_datetime(
                    historico["data"], errors="coerce"
                ).dt.strftime("%d/%m/%Y")
                historico.columns = ["Nome", "Data", "Período", "Atualizado em"]
                st.dataframe(
                    historico.drop(columns=["Nome"]),
                    use_container_width=True,
                    hide_index=True,
                )
