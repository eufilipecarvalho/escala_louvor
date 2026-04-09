"""
sheets_integration.py
──────────────────────
Módulo de integração entre o app de Escala de Louvor e o Google Sheets.

Estrutura esperada na planilha (cada aba é uma "tabela"):
  - Aba "integrantes"  : nome, instrumento, nivel_tecnico,
                         datas_disponiveis, ativo, email, telefone
  - Aba "escalas"      : gerada automaticamente pelo app ao salvar

Uso:
  from sheets_integration import get_sheets_client
  client = get_sheets_client()
  df = client.ler_integrantes()
  client.salvar_escala(df_resultado, avisos)

Credenciais (em ordem de prioridade):
  1. st.secrets["gcp_service_account"]  →  Streamlit Cloud ou .streamlit/secrets.toml local
  2. arquivo credentials.json na raiz   →  fallback para desenvolvimento sem secrets
"""

import json
from datetime import datetime
from pathlib import Path

import gspread
import pandas as pd
import streamlit as st
from google.oauth2.service_account import Credentials


# ── Escopos necessários ────────────────────────────────────────────
SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]

# ── Cabeçalhos esperados em cada aba ──────────────────────────────
CABECALHO_INTEGRANTES = [
    "nome", "instrumento", "nivel_tecnico",
    "datas_disponiveis", "ativo", "email", "telefone",
]
CABECALHO_ESCALAS = [
    "gerado_em", "data_culto", "culto", "instrumento",
    "integrante", "funcao", "nivel",
]
CABECALHO_AVISOS = ["gerado_em", "data_culto", "aviso"]
CABECALHO_DISPONIBILIDADE = ["nome", "data", "periodo", "atualizado_em"]


def _carregar_credenciais() -> Credentials:
    """
    Carrega credenciais em ordem de prioridade:
      1. st.secrets["gcp_service_account"] (Streamlit Cloud ou secrets.toml local)
      2. arquivo credentials.json na raiz do projeto (fallback de desenvolvimento)

    Levanta RuntimeError com mensagem clara se nenhuma fonte for encontrada.
    """
    # — Prioridade 1: st.secrets ————————————————————————————————————
    try:
        creds_dict = dict(st.secrets["gcp_service_account"])
        return Credentials.from_service_account_info(creds_dict, scopes=SCOPES)
    except (KeyError, FileNotFoundError):
        pass  # secrets não configurado, tenta o fallback

    # — Prioridade 2: credentials.json local ————————————————————————
    local_path = Path("credentials.json")
    if local_path.exists():
        return Credentials.from_service_account_file(str(local_path), scopes=SCOPES)

    # — Nenhuma fonte encontrada ————————————————————————————————————
    raise RuntimeError(
        "Credenciais do Google não encontradas.\n\n"
        "Para rodar localmente: crie .streamlit/secrets.toml com a seção "
        "[gcp_service_account], ou coloque credentials.json na raiz do projeto.\n"
        "Para Streamlit Cloud: configure os secrets em Settings → Secrets."
    )


@st.cache_resource(show_spinner="Conectando ao Google Sheets...")
def get_sheets_client(spreadsheet_name: str = "Escala de Louvor") -> "SheetsClient":
    """
    Retorna uma instância cacheada de SheetsClient.
    O cache é mantido enquanto o app estiver rodando;
    chame st.cache_resource.clear() para forçar reconexão.

    Uso no app:
        client = get_sheets_client()
    """
    return SheetsClient(spreadsheet_name=spreadsheet_name)


class SheetsClient:
    """
    Encapsula todas as operações de leitura e escrita no Google Sheets.
    Cria abas automaticamente se não existirem.
    Obtém credenciais via _carregar_credenciais() — nunca recebe
    caminhos ou dicionários diretamente.
    """

    def __init__(self, spreadsheet_name: str = "Escala de Louvor"):
        creds = _carregar_credenciais()
        self._gc = gspread.authorize(creds)
        self._sh = self._gc.open(spreadsheet_name)

    # ── Helpers internos ──────────────────────────────────────────

    def _aba(self, nome: str, cabecalho: list[str]) -> gspread.Worksheet:
        """Retorna a aba pelo nome, criando-a com cabeçalho se não existir."""
        try:
            return self._sh.worksheet(nome)
        except gspread.WorksheetNotFound:
            ws = self._sh.add_worksheet(title=nome, rows=500, cols=len(cabecalho))
            ws.append_row(cabecalho, value_input_option="USER_ENTERED")
            return ws

    @staticmethod
    def _ws_para_df(ws: gspread.Worksheet) -> pd.DataFrame:
        """Converte worksheet em DataFrame, tratando planilha vazia."""
        dados = ws.get_all_records(expected_headers=None)
        if not dados:
            return pd.DataFrame()
        return pd.DataFrame(dados)

    # ── Leitura ───────────────────────────────────────────────────

    def ler_integrantes(self) -> pd.DataFrame:
        """
        Lê a aba 'integrantes' e retorna um DataFrame.
        Cria a aba com cabeçalho se não existir.
        """
        ws = self._aba("integrantes", CABECALHO_INTEGRANTES)
        df = self._ws_para_df(ws)
        if df.empty:
            return pd.DataFrame(columns=CABECALHO_INTEGRANTES)
        # Garante tipos corretos
        df["nivel_tecnico"] = pd.to_numeric(df["nivel_tecnico"], errors="coerce").fillna(1).astype(int)
        df["ativo"] = df["ativo"].astype(str).str.lower().isin(("sim", "true", "1", "yes"))
        return df

    def ler_escalas_anteriores(self) -> pd.DataFrame:
        """Lê escalas já salvas (útil para histórico/auditoria)."""
        ws = self._aba("escalas", CABECALHO_ESCALAS)
        return self._ws_para_df(ws)

    # ── Escrita ───────────────────────────────────────────────────

    def salvar_integrante(self, dados: dict) -> None:
        """
        Adiciona uma nova linha na aba 'integrantes'.

        dados = {
            "nome": "...", "instrumento": "...", "nivel_tecnico": 3,
            "datas_disponiveis": "2025-05-04;2025-05-11",
            "ativo": "sim", "email": "...", "telefone": "..."
        }
        """
        ws = self._aba("integrantes", CABECALHO_INTEGRANTES)
        linha = [str(dados.get(col, "")) for col in CABECALHO_INTEGRANTES]
        ws.append_row(linha, value_input_option="USER_ENTERED")

    def atualizar_integrante(self, nome: str, instrumento: str, novos_dados: dict) -> bool:
        """
        Atualiza a linha de um integrante específico (identificado por nome + instrumento).
        Retorna True se encontrou e atualizou, False caso contrário.
        """
        ws = self._aba("integrantes", CABECALHO_INTEGRANTES)
        registros = ws.get_all_records()
        for i, reg in enumerate(registros, start=2):  # linha 1 = cabeçalho
            if reg.get("nome") == nome and reg.get("instrumento") == instrumento:
                reg.update(novos_dados)
                linha = [str(reg.get(col, "")) for col in CABECALHO_INTEGRANTES]
                ws.update(f"A{i}", [linha], value_input_option="USER_ENTERED")
                return True
        return False

    def salvar_escala(
        self,
        df_escala: pd.DataFrame,
        avisos: list[dict] | None = None,
        substituir: bool = False,
    ) -> None:
        """
        Salva o resultado de uma escala gerada nas abas 'escalas' e 'avisos'.

        Parameters
        ----------
        df_escala   : DataFrame retornado por escalas_para_dataframe()
        avisos      : lista de {"data_culto": "...", "aviso": "..."}
        substituir  : se True, limpa a aba antes de salvar (útil para re-gerar)
        """
        timestamp = datetime.now().strftime("%d/%m/%Y %H:%M")

        # ── Aba escalas ──
        ws_esc = self._aba("escalas", CABECALHO_ESCALAS)
        if substituir:
            ws_esc.clear()
            ws_esc.append_row(CABECALHO_ESCALAS, value_input_option="USER_ENTERED")

        if not df_escala.empty:
            linhas = []
            for _, row in df_escala.iterrows():
                linhas.append([
                    timestamp,
                    row.get("Data", ""),
                    row.get("Culto", ""),
                    row.get("Instrumento", ""),
                    row.get("Integrante", ""),
                    row.get("Função", ""),
                    str(row.get("Nível", "")),
                ])
            ws_esc.append_rows(linhas, value_input_option="USER_ENTERED")

        # ── Aba avisos ──
        if avisos:
            ws_av = self._aba("avisos", CABECALHO_AVISOS)
            if substituir:
                ws_av.clear()
                ws_av.append_row(CABECALHO_AVISOS, value_input_option="USER_ENTERED")
            linhas_av = [
                [timestamp, av.get("data_culto", ""), av.get("aviso", "")]
                for av in avisos
            ]
            ws_av.append_rows(linhas_av, value_input_option="USER_ENTERED")

    def limpar_escala(self) -> None:
        """Remove todos os dados das abas 'escalas' e 'avisos' (mantém cabeçalho)."""
        for nome, cab in [("escalas", CABECALHO_ESCALAS), ("avisos", CABECALHO_AVISOS)]:
            ws = self._aba(nome, cab)
            ws.clear()
            ws.append_row(cab, value_input_option="USER_ENTERED")

    # ── Disponibilidade ───────────────────────────────────────────

    def ler_disponibilidade(self) -> pd.DataFrame:
        """
        Lê a aba 'disponibilidade' e retorna um DataFrame.
        Colunas: nome, data, periodo, atualizado_em
        """
        ws = self._aba("disponibilidade", CABECALHO_DISPONIBILIDADE)
        df = self._ws_para_df(ws)
        if df.empty:
            return pd.DataFrame(columns=CABECALHO_DISPONIBILIDADE)
        df["data"] = pd.to_datetime(df["data"], errors="coerce").dt.date
        return df

    def salvar_disponibilidade(
        self,
        nome: str,
        datas: list,
        periodo: str = "manha",
    ) -> dict:
        """
        Salva ou atualiza a disponibilidade de um integrante.

        Para cada (nome, data):
          - Se já existir uma linha → atualiza periodo e atualizado_em.
          - Se não existir          → insere linha nova.

        Retorna {"inseridos": int, "atualizados": int}.
        """
        ws = self._aba("disponibilidade", CABECALHO_DISPONIBILIDADE)
        registros = ws.get_all_records()   # lista de dicts, linha 1 = cabeçalho
        timestamp = datetime.now().strftime("%d/%m/%Y %H:%M")

        # Índice {(nome, data_str): numero_linha_na_planilha}
        # get_all_records retorna a partir da linha 2 (linha 1 = cabeçalho)
        indice: dict[tuple, int] = {}
        for i, reg in enumerate(registros, start=2):
            chave = (str(reg.get("nome", "")), str(reg.get("data", "")))
            indice[chave] = i

        inseridos = 0
        atualizados = 0
        novas_linhas = []

        for dt in datas:
            data_str = dt.isoformat() if hasattr(dt, "isoformat") else str(dt)
            chave = (nome, data_str)

            if chave in indice:
                # Atualiza a linha existente (apenas periodo e timestamp)
                num_linha = indice[chave]
                # Colunas: A=nome B=data C=periodo D=atualizado_em
                ws.update(
                    f"C{num_linha}:D{num_linha}",
                    [[periodo, timestamp]],
                    value_input_option="USER_ENTERED",
                )
                atualizados += 1
            else:
                novas_linhas.append([nome, data_str, periodo, timestamp])
                inseridos += 1

        if novas_linhas:
            ws.append_rows(novas_linhas, value_input_option="USER_ENTERED")

        return {"inseridos": inseridos, "atualizados": atualizados}


# ════════════════════════════════════════════════════════════════════
# COMO USAR NO app_escala_louvor.py
# ════════════════════════════════════════════════════════════════════
#
# ── Importar e conectar (uma linha) ─────────────────────────────────
#
#   from sheets_integration import get_sheets_client
#   client = get_sheets_client()          # cache automático, sem parâmetros
#   df_input = client.ler_integrantes()
#
#
# ── Configurar credenciais ───────────────────────────────────────────
#
#   LOCAL → crie .streamlit/secrets.toml:
#
#     [gcp_service_account]
#     type = "service_account"
#     project_id = "seu-projeto"
#     private_key_id = "..."
#     private_key = "-----BEGIN PRIVATE KEY-----\n...\n-----END PRIVATE KEY-----\n"
#     client_email = "escala-bot@seu-projeto.iam.gserviceaccount.com"
#     client_id = "..."
#     auth_uri = "https://accounts.google.com/o/oauth2/auth"
#     token_uri = "https://oauth2.googleapis.com/token"
#
#   STREAMLIT CLOUD → cole o mesmo conteúdo em Settings → Secrets.
#
#   FALLBACK → coloque credentials.json na raiz do projeto
#              (útil para testes rápidos, nunca suba para o GitHub).
#
#
# ── Salvar escala após gerar ─────────────────────────────────────────
#
#   if st.button("💾 Salvar no Google Sheets"):
#       avisos_flat = [
#           {"data_culto": e.data.strftime("%d/%m/%Y"), "aviso": a}
#           for e in escalas for a in e.avisos
#       ]
#       client.salvar_escala(df_resultado, avisos_flat, substituir=True)
#       st.success("Escala salva na planilha!")
#
#
# ── Adicionar integrante via formulário ──────────────────────────────
#
#   with st.form("novo_integrante"):
#       nome = st.text_input("Nome")
#       instrumento = st.selectbox("Instrumento", INSTRUMENTOS_FIXOS)
#       nivel = st.slider("Nível técnico", 1, 5, 3)
#       datas = st.text_input("Datas disponíveis (AAAA-MM-DD separadas por ;)")
#       submitted = st.form_submit_button("Adicionar")
#       if submitted:
#           client.salvar_integrante({
#               "nome": nome, "instrumento": instrumento,
#               "nivel_tecnico": nivel, "datas_disponiveis": datas,
#               "ativo": "sim",
#           })
#           st.success(f"{nome} adicionado!")
#           st.cache_resource.clear()  # força releitura na próxima ação
