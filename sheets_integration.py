"""
sheets_integration.py
──────────────────────
Módulo de integração entre o app de Escala de Louvor e o Google Sheets.

Estrutura esperada na planilha (cada aba é uma "tabela"):
  - Aba "integrantes"  : nome, instrumento, nivel_tecnico,
                         datas_disponiveis, ativo, email, telefone
  - Aba "escalas"      : gerada automaticamente pelo app ao salvar

Uso:
  from sheets_integration import SheetsClient
  client = SheetsClient(credentials_path="credentials.json",
                        spreadsheet_name="Escala de Louvor")
  df = client.ler_integrantes()
  client.salvar_escala(df_resultado, avisos)
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


class SheetsClient:
    """
    Encapsula todas as operações de leitura e escrita no Google Sheets.
    Cria abas automaticamente se não existirem.
    """

    def __init__(
        self,
        credentials_path: str | None = None,
        credentials_dict: dict | None = None,
        spreadsheet_name: str = "Escala de Louvor",
    ):
        """
        Aceita credenciais como caminho de arquivo (desenvolvimento local)
        ou como dicionário (secrets do Streamlit Cloud).

        Parameters
        ----------
        credentials_path  : caminho para o arquivo credentials.json local
        credentials_dict  : dicionário com o conteúdo do JSON (para deploy)
        spreadsheet_name  : nome exato da planilha no Google Drive
        """
        if credentials_dict:
            creds = Credentials.from_service_account_info(
                credentials_dict, scopes=SCOPES
            )
        elif credentials_path:
            creds = Credentials.from_service_account_file(
                credentials_path, scopes=SCOPES
            )
        else:
            raise ValueError(
                "Forneça credentials_path (local) ou credentials_dict (deploy)."
            )

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


# ════════════════════════════════════════════════════════════════════
# COMO CONECTAR NO APP STREAMLIT (cole no app_escala_louvor.py)
# ════════════════════════════════════════════════════════════════════
#
# ── Opção A: desenvolvimento local ──────────────────────────────────
#
#   @st.cache_resource
#   def get_sheets_client():
#       return SheetsClient(
#           credentials_path="credentials.json",
#           spreadsheet_name="Escala de Louvor",
#       )
#
#   client = get_sheets_client()
#   df_input = client.ler_integrantes()
#
#
# ── Opção B: Streamlit Cloud (usando st.secrets) ─────────────────────
#
#   No Streamlit Cloud, vá em Settings → Secrets e cole:
#
#   [gcp_service_account]
#   type = "service_account"
#   project_id = "seu-projeto"
#   private_key_id = "..."
#   private_key = "-----BEGIN RSA PRIVATE KEY-----\n..."
#   client_email = "escala-bot@seu-projeto.iam.gserviceaccount.com"
#   client_id = "..."
#   auth_uri = "https://accounts.google.com/o/oauth2/auth"
#   token_uri = "https://oauth2.googleapis.com/token"
#
#   Depois no código:
#
#   @st.cache_resource
#   def get_sheets_client():
#       creds_dict = dict(st.secrets["gcp_service_account"])
#       return SheetsClient(
#           credentials_dict=creds_dict,
#           spreadsheet_name="Escala de Louvor",
#       )
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
