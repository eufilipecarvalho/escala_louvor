"""
Escala de Louvor — Interface Streamlit
========================================
Execute com:  streamlit run app_escala_louvor.py

Dependências:
  pip install streamlit pandas openpyxl

Este arquivo é autocontido: inclui os modelos de dados,
o gerador de escala e a interface visual.
"""

import uuid
import pandas as pd
import streamlit as st
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Optional
import io
from sheets_integration import get_sheets_client
from cadastro_disponibilidade import render_cadastro_disponibilidade

client = get_sheets_client()

# ═══════════════════════════════════════════════════════════════════
# MODELOS DE DADOS
# ═══════════════════════════════════════════════════════════════════

@dataclass
class Instrumento:
    id: str
    nome: str

@dataclass
class MembroInstrumento:
    membro_id: str
    instrumento_id: str
    nivel_tecnico: int

@dataclass
class Disponibilidade:
    id: str
    membro_id: str
    data: date
    periodo: str
    observacao: str = ""

@dataclass
class Membro:
    id: str
    nome: str
    email: str = ""
    telefone: str = ""
    ativo: bool = True

@dataclass
class EscalaMembro:
    escala_id: str
    membro_id: str
    instrumento_id: str
    funcao: str

@dataclass
class Escala:
    id: str
    data: date
    tipo: str
    titulo: str
    status: str = "rascunho"
    membros: list = field(default_factory=list)
    avisos: list = field(default_factory=list)

@dataclass
class BancoDados:
    membros: dict = field(default_factory=dict)
    instrumentos: dict = field(default_factory=dict)
    membro_instrumentos: list = field(default_factory=list)
    disponibilidades: list = field(default_factory=list)
    escalas: list = field(default_factory=list)


# ═══════════════════════════════════════════════════════════════════
# GERADOR DE ESCALA
# ═══════════════════════════════════════════════════════════════════

class GeradorEscala:
    INSTRUMENTOS_OBRIGATORIOS = {
        "Voz": 5,
        "Violão": 1,
        "Bateria": 1,
        "Guitarra": 1,
        "Baixo": 1,
        "Teclado": 1,
    }

    def __init__(self, db: BancoDados):
        self.db = db

    def gerar_escala_semanal(self, datas, tipo="culto", periodo="manha"):
        escalas = []
        escala_anterior = None
        for data in sorted(datas):
            escala = self._gerar_para_data(data, tipo, periodo, escala_anterior)
            escalas.append(escala)
            escala_anterior = escala
        return escalas

    def _gerar_para_data(self, data, tipo, periodo, escala_anterior):
        escala = Escala(
            id=str(uuid.uuid4()),
            data=data,
            tipo=tipo,
            titulo=f"{tipo.capitalize()} – {data.strftime('%d/%m/%Y')}",
        )
        ids_anterior = {em.membro_id for em in escala_anterior.membros} if escala_anterior else set()
        candidatos_por_instrumento = self._candidatos_disponiveis(data, periodo)

        for nome_inst, vagas in self.INSTRUMENTOS_OBRIGATORIOS.items():
            candidatos = candidatos_por_instrumento.get(nome_inst, [])
            instrumento = self._buscar_instrumento(nome_inst)

            if not candidatos:
                escala.avisos.append(f"Sem músico disponível para **{nome_inst}**.")
                continue
            if instrumento is None:
                continue

            lideres = [c for c in candidatos if c["nivel_tecnico"] >= 4]
            if not lideres:
                escala.avisos.append(
                    f"Sem líder (nível ≥ 4) para **{nome_inst}**. "
                    f"Melhor disponível: nível {candidatos[0]['nivel_tecnico']}."
                )

            ordenados = self._ordenar(candidatos, ids_anterior)
            selecionados = self._selecionar(ordenados, vagas,
                                            {c["membro_id"] for c in lideres},
                                            escala, instrumento)
            if len(selecionados) < vagas:
                escala.avisos.append(
                    f"**{nome_inst}**: precisava de {vagas}, encontrou {len(selecionados)}."
                )
        return escala

    def _candidatos_disponiveis(self, data, periodo):
        ids_disp = {
            d.membro_id for d in self.db.disponibilidades
            if d.data == data and d.periodo in (periodo, "dia_todo")
        }
        total_disp = {}
        for d in self.db.disponibilidades:
            total_disp[d.membro_id] = total_disp.get(d.membro_id, 0) + 1

        resultado = {}
        for mi in self.db.membro_instrumentos:
            if mi.membro_id not in ids_disp:
                continue
            membro = self.db.membros.get(mi.membro_id)
            instrumento = self.db.instrumentos.get(mi.instrumento_id)
            if not membro or not membro.ativo or not instrumento:
                continue
            entrada = {
                "membro_id": membro.id,
                "membro_nome": membro.nome,
                "instrumento_id": instrumento.id,
                "instrumento_nome": instrumento.nome,
                "nivel_tecnico": mi.nivel_tecnico,
                "total_disponibilidades": total_disp.get(membro.id, 0),
            }
            resultado.setdefault(instrumento.nome, []).append(entrada)
        return resultado

    def _ordenar(self, candidatos, ids_evitar):
        return sorted(candidatos, key=lambda c: (
            c["membro_id"] in ids_evitar,
            -c["total_disponibilidades"],
            -c["nivel_tecnico"],
        ))

    def _selecionar(self, candidatos, vagas, lideres_ids, escala, instrumento):
        selecionados = []
        ids_ja = {em.membro_id for em in escala.membros}
        lider_ok = False

        for c in candidatos:
            if len(selecionados) >= vagas:
                break
            if c["membro_id"] in ids_ja:
                continue
            if not lider_ok and c["membro_id"] in lideres_ids:
                selecionados.append(c)
                ids_ja.add(c["membro_id"])
                lider_ok = True

        for c in candidatos:
            if len(selecionados) >= vagas:
                break
            if c["membro_id"] in ids_ja:
                continue
            selecionados.append(c)
            ids_ja.add(c["membro_id"])

        for c in selecionados:
            escala.membros.append(EscalaMembro(
                escala_id=escala.id,
                membro_id=c["membro_id"],
                instrumento_id=instrumento.id,
                funcao="lider" if c["nivel_tecnico"] >= 4 else "musico",
            ))
        return selecionados

    def _buscar_instrumento(self, nome):
        return next((i for i in self.db.instrumentos.values() if i.nome == nome), None)


# ═══════════════════════════════════════════════════════════════════
# HELPERS: CSV → BancoDados
# ═══════════════════════════════════════════════════════════════════

INSTRUMENTOS_FIXOS = ["Voz", "Violão", "Bateria", "Guitarra", "Baixo", "Teclado"]

def criar_banco_de_csv(df: pd.DataFrame) -> BancoDados:
    """
    Espera um DataFrame com colunas:
      nome, instrumento, nivel_tecnico, datas_disponiveis (separadas por ';'), ativo
    """
    db = BancoDados()

    for nome in INSTRUMENTOS_FIXOS:
        iid = str(uuid.uuid4())
        db.instrumentos[iid] = Instrumento(id=iid, nome=nome)

    def inst_id(nome):
        return next((i.id for i in db.instrumentos.values() if i.nome == nome), None)

    for _, row in df.iterrows():
        nome = str(row["nome"]).strip()
        instrumento = str(row["instrumento"]).strip()
        nivel = int(row["nivel_tecnico"])
        datas_str = str(row.get("datas_disponiveis", "")).strip()
        ativo = str(row.get("ativo", "sim")).strip().lower() in ("sim", "true", "1", "yes")

        # Reutiliza membro se já existe (mesmo nome)
        membro_existente = next((m for m in db.membros.values() if m.nome == nome), None)
        if membro_existente:
            mid = membro_existente.id
        else:
            mid = str(uuid.uuid4())
            db.membros[mid] = Membro(
                id=mid, nome=nome,
                email=str(row.get("email", "")),
                telefone=str(row.get("telefone", "")),
                ativo=ativo,
            )

        iid = inst_id(instrumento)
        if iid:
            db.membro_instrumentos.append(
                MembroInstrumento(membro_id=mid, instrumento_id=iid, nivel_tecnico=nivel)
            )

        # Disponibilidades
        if datas_str:
            for ds in datas_str.split(";"):
                ds = ds.strip()
                if not ds:
                    continue
                try:
                    dt = date.fromisoformat(ds)
                    db.disponibilidades.append(Disponibilidade(
                        id=str(uuid.uuid4()),
                        membro_id=mid,
                        data=dt,
                        periodo="manha",
                    ))
                except ValueError:
                    pass

    return db


def escalas_para_dataframe(escalas: list[Escala], db: BancoDados) -> pd.DataFrame:
    """Transforma lista de Escala em DataFrame tabular."""
    linhas = []
    for escala in escalas:
        for em in escala.membros:
            membro = db.membros.get(em.membro_id)
            instrumento = db.instrumentos.get(em.instrumento_id)
            if membro and instrumento:
                linhas.append({
                    "Data": escala.data.strftime("%d/%m/%Y"),
                    "Culto": escala.titulo.split("–")[0].strip(),
                    "Instrumento": instrumento.nome,
                    "Integrante": membro.nome,
                    "Função": em.funcao.capitalize(),
                    "Nível": next(
                        (mi.nivel_tecnico for mi in db.membro_instrumentos
                         if mi.membro_id == em.membro_id
                         and mi.instrumento_id == em.instrumento_id),
                        "–"
                    ),
                })
    if not linhas:
        return pd.DataFrame()
    df = pd.DataFrame(linhas)
    ordem = list(GeradorEscala.INSTRUMENTOS_OBRIGATORIOS.keys())
    df["Instrumento"] = pd.Categorical(df["Instrumento"], categories=ordem, ordered=True)
    return df.sort_values(["Data", "Instrumento"]).reset_index(drop=True)


def csv_exemplo() -> str:
    return """nome,instrumento,nivel_tecnico,datas_disponiveis,ativo,email
Ana Lima,Voz,5,2025-05-04;2025-05-11;2025-05-18;2025-05-25,sim,ana@igreja.com
Carla Mendes,Voz,4,2025-05-04;2025-05-11;2025-05-18;2025-05-25,sim,carla@igreja.com
Elaine Souza,Voz,3,2025-05-04;2025-05-18,sim,elaine@igreja.com
Gabi Ferreira,Voz,3,2025-05-11;2025-05-25,sim,gabi@igreja.com
Bruno Costa,Violão,5,2025-05-04;2025-05-11,sim,bruno@igreja.com
Diego Ramos,Violão,3,2025-05-04;2025-05-11;2025-05-18;2025-05-25,sim,diego@igreja.com
Bruno Costa,Guitarra,4,2025-05-04;2025-05-11,sim,bruno@igreja.com
Diego Ramos,Guitarra,3,2025-05-18;2025-05-25,sim,diego@igreja.com
Fábio Nunes,Bateria,4,2025-05-04;2025-05-11;2025-05-18;2025-05-25,sim,fabio@igreja.com
Hugo Alves,Bateria,2,2025-05-18;2025-05-25,sim,hugo@igreja.com
Fábio Nunes,Baixo,4,2025-05-04;2025-05-11;2025-05-18;2025-05-25,sim,fabio@igreja.com
Hugo Alves,Baixo,3,2025-05-04;2025-05-18,sim,hugo@igreja.com
Ana Lima,Teclado,4,2025-05-04;2025-05-11,sim,ana@igreja.com
Carla Mendes,Teclado,3,2025-05-18;2025-05-25,sim,carla@igreja.com
"""


# ═══════════════════════════════════════════════════════════════════
# INTERFACE STREAMLIT
# ═══════════════════════════════════════════════════════════════════

st.set_page_config(
    page_title="Escala de Louvor",
    page_icon="🎵",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── CSS personalizado ──────────────────────────────────────────────
st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=DM+Serif+Display&family=DM+Sans:wght@300;400;500;600&display=swap');

html, body, [class*="css"] {
    font-family: 'DM Sans', sans-serif;
}

h1, h2, h3 {
    font-family: 'DM Serif Display', serif !important;
    letter-spacing: -0.02em;
}

/* Header principal */
.hero {
    background: linear-gradient(135deg, #1a1a2e 0%, #16213e 60%, #0f3460 100%);
    border-radius: 16px;
    padding: 2.5rem 2rem 2rem;
    margin-bottom: 1.5rem;
    position: relative;
    overflow: hidden;
}
.hero::before {
    content: "♪";
    position: absolute;
    right: 2rem;
    top: 1rem;
    font-size: 6rem;
    opacity: 0.07;
    line-height: 1;
}
.hero h1 {
    color: #f8f4ee !important;
    font-size: 2rem !important;
    margin: 0 0 .25rem !important;
}
.hero p {
    color: #a8b8d8;
    margin: 0;
    font-size: .95rem;
    font-weight: 300;
}

/* Cards de stat */
.stat-card {
    background: #f8f4ee;
    border: 1px solid #e8e0d4;
    border-radius: 12px;
    padding: 1rem 1.25rem;
    text-align: center;
}
.stat-number {
    font-family: 'DM Serif Display', serif;
    font-size: 2rem;
    color: #1a1a2e;
    line-height: 1;
}
.stat-label {
    font-size: .8rem;
    color: #888;
    text-transform: uppercase;
    letter-spacing: .08em;
    margin-top: .25rem;
}

/* Badges de função */
.badge-lider {
    background: #0f3460;
    color: #e8d5a3;
    padding: 2px 10px;
    border-radius: 20px;
    font-size: .78rem;
    font-weight: 500;
}
.badge-musico {
    background: #e8e0d4;
    color: #555;
    padding: 2px 10px;
    border-radius: 20px;
    font-size: .78rem;
}

/* Aviso */
.aviso-box {
    background: #fff8e6;
    border-left: 4px solid #f0a500;
    border-radius: 0 8px 8px 0;
    padding: .75rem 1rem;
    margin: .4rem 0;
    font-size: .9rem;
    color: #7a5800;
}

/* Tabela de escala */
.escala-table { width: 100%; border-collapse: collapse; margin-top: .5rem; }
.escala-table th {
    background: #1a1a2e;
    color: #f8f4ee;
    padding: .6rem 1rem;
    text-align: left;
    font-weight: 500;
    font-size: .85rem;
    letter-spacing: .04em;
}
.escala-table td {
    padding: .55rem 1rem;
    border-bottom: 1px solid #f0ebe3;
    font-size: .9rem;
    color: #2a2a2a;
}
.escala-table tr:last-child td { border-bottom: none; }
.escala-table tr:hover td { background: #faf7f2; }

.date-tag {
    background: #0f3460;
    color: #fff;
    padding: 3px 10px;
    border-radius: 6px;
    font-size: .82rem;
    white-space: nowrap;
    font-weight: 500;
}
.nivel-dot {
    display: inline-block;
    width: 10px; height: 10px;
    border-radius: 50%;
    margin-right: 4px;
}

/* Sidebar */
section[data-testid="stSidebar"] {
    background: #faf7f2;
}

/* Botão principal */
div.stButton > button[kind="primary"] {
    background: #0f3460 !important;
    color: #f8f4ee !important;
    border: none !important;
    border-radius: 10px !important;
    padding: .65rem 2rem !important;
    font-family: 'DM Sans', sans-serif !important;
    font-weight: 600 !important;
    font-size: 1rem !important;
    letter-spacing: .02em;
    width: 100%;
    transition: background .2s;
}
div.stButton > button[kind="primary"]:hover {
    background: #1a4a80 !important;
}
</style>
""", unsafe_allow_html=True)


# ── Hero header ───────────────────────────────────────────────────
st.markdown("""
<div class="hero">
  <h1>🎵 Escala de Louvor</h1>
  <p>Geração automática de escalas com base em disponibilidade, nível técnico e rodízio de integrantes.</p>
</div>
""", unsafe_allow_html=True)


# ── Sidebar: configurações ────────────────────────────────────────
with st.sidebar:
    st.markdown("### 🎵 Menu")
    pagina = st.radio(
        label="Navegação",
        options=["📊 Escala", "📅 Disponibilidade"],
        label_visibility="collapsed",
    )

    st.markdown("---")

    # Configurações só aparecem na página de Escala
    if pagina == "📊 Escala":
        st.markdown("### ⚙️ Configurações")

        tipo_culto = st.selectbox(
            "Tipo de culto",
            ["culto", "ensaio", "evento"],
            format_func=lambda x: x.capitalize(),
        )
        periodo = st.selectbox(
            "Período",
            ["manha", "tarde", "noite", "dia_todo"],
            format_func=lambda x: {
                "manha": "Manhã", "tarde": "Tarde",
                "noite": "Noite", "dia_todo": "Dia todo",
            }[x],
        )

        st.markdown("---")
        st.markdown("### 📅 Datas")
        data_inicio = st.date_input("Data inicial", value=date(2025, 5, 4))
        num_semanas = st.slider("Nº de domingos", 1, 8, 4)
        datas = [data_inicio + timedelta(weeks=i) for i in range(num_semanas)]

        st.markdown("**Datas selecionadas:**")
        for d in datas:
            st.markdown(f"- {d.strftime('%d/%m/%Y')}")

        st.markdown("---")
        st.markdown("### 📥 CSV de exemplo")
        st.download_button(
            label="Baixar modelo CSV",
            data=csv_exemplo(),          # função já existente no seu app
            file_name="modelo_integrantes.csv",
            mime="text/csv",
        )

st.markdown("""
<div class="hero">
  <h1>🎵 Escala de Louvor</h1>
  <p>Geração automática de escalas com base em disponibilidade,
     nível técnico e rodízio de integrantes.</p>
</div>
""", unsafe_allow_html=True)

# ── Roteamento ────────────────────────────────────────────────────
if pagina == "📊 Escala":

    # ── Carrega integrantes do Sheets (ou CSV de exemplo) ──────────
    df_integrantes = client.ler_integrantes()

    # Mantém o fallback para dados de exemplo se a planilha estiver vazia
    usar_exemplo = st.checkbox("Usar dados de exemplo", value=df_integrantes.empty)
    if usar_exemplo or df_integrantes.empty:
        import io
        df_input = pd.read_csv(io.StringIO(csv_exemplo()))
        st.caption("ℹ️ Usando dados de exemplo.")
    else:
        df_input = df_integrantes
        st.caption(f"✅ {len(df_input)} registros carregados do Google Sheets.")

    # ── Botão Gerar Escala (igual ao original) ────────────────────
    gerar = st.button("🎵 Gerar Escala", type="primary")

    if gerar:
        with st.spinner("Calculando a melhor escala..."):
            db = criar_banco_de_csv(df_input)           # função já existente
            gerador = GeradorEscala(db)                 # classe já existente
            escalas = gerador.gerar_escala_semanal(
                datas, tipo=tipo_culto, periodo=periodo
            )
            df_resultado = escalas_para_dataframe(escalas, db)  # função já existente

        # … (todo o bloco de exibição de resultados que você já tem) …

        # ── Botão de persistência no Sheets ───────────────────────
        if st.button("💾 Salvar escala no Google Sheets"):
            avisos_flat = [
                {"data_culto": e.data.strftime("%d/%m/%Y"), "aviso": a}
                for e in escalas for a in e.avisos
            ]
            client.salvar_escala(df_resultado, avisos_flat, substituir=True)
            st.success("Escala salva na planilha!")

elif pagina == "📅 Disponibilidade":
    # Delega todo o rendering para o módulo dedicado
    render_cadastro_disponibilidade(client)
