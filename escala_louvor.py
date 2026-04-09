"""
Gerador de Escala Semanal de Louvor
====================================
Baseado na estrutura de dados definida (membro, instrumento,
membro_instrumento, disponibilidade, escala, escala_membro).

Regras de negócio implementadas:
  1. Prioriza quem tem maior disponibilidade no período.
  2. Garante ao menos um integrante de nível técnico 4 ou 5 (líder).
  3. Evita repetir a mesma pessoa em dois domingos consecutivos.
  4. Emite avisos quando não há pessoas suficientes para uma data.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import date
from typing import Optional


# ---------------------------------------------------------------------------
# Modelos de dados
# ---------------------------------------------------------------------------

@dataclass
class Instrumento:
    id: str
    nome: str


@dataclass
class MembroInstrumento:
    membro_id: str
    instrumento_id: str
    nivel_tecnico: int          # 1 a 5


@dataclass
class Disponibilidade:
    id: str
    membro_id: str
    data: date
    periodo: str                # "manha" | "tarde" | "noite" | "dia_todo"
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
    funcao: str                 # "lider" | "ministro" | "musico"


@dataclass
class Escala:
    id: str
    data: date
    tipo: str                   # "culto" | "ensaio" | "evento"
    titulo: str
    status: str = "rascunho"    # "rascunho" | "confirmada" | "concluida"
    membros: list[EscalaMembro] = field(default_factory=list)
    avisos: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Banco de dados in-memory (dicionários simulando tabelas)
# ---------------------------------------------------------------------------

@dataclass
class BancoDados:
    membros: dict[str, Membro] = field(default_factory=dict)
    instrumentos: dict[str, Instrumento] = field(default_factory=dict)
    membro_instrumentos: list[MembroInstrumento] = field(default_factory=list)
    disponibilidades: list[Disponibilidade] = field(default_factory=list)
    escalas: list[Escala] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Gerador de escala
# ---------------------------------------------------------------------------

class GeradorEscala:
    """
    Gera escalas semanais respeitando as quatro regras de negócio.
    """

    # Quais instrumentos são obrigatórios e quantos de cada um.
    # Ajuste conforme a realidade da sua equipe.
    INSTRUMENTOS_OBRIGATORIOS: dict[str, int] = {
        "Voz": 2,
        "Violão": 1,
        "Bateria": 1,
        "Guitarra": 1,
        "Baixo": 1,
        "Teclado": 1,
    }

    def __init__(self, db: BancoDados):
        self.db = db

    # ------------------------------------------------------------------
    # API pública
    # ------------------------------------------------------------------

    def gerar_escala_semanal(
        self,
        datas: list[date],
        tipo: str = "culto",
        periodo: str = "manha",
    ) -> list[Escala]:
        """
        Gera uma escala para cada data fornecida.

        Parameters
        ----------
        datas   : lista de datas (ex.: todos os domingos do mês)
        tipo    : "culto" | "ensaio" | "evento"
        periodo : "manha" | "tarde" | "noite" | "dia_todo"

        Returns
        -------
        Lista de Escala, uma por data, com .avisos populados se necessário.
        """
        escalas: list[Escala] = []
        escala_anterior: Optional[Escala] = None

        for data in sorted(datas):
            escala = self._gerar_escala_para_data(
                data=data,
                tipo=tipo,
                periodo=periodo,
                escala_anterior=escala_anterior,
            )
            escalas.append(escala)
            escala_anterior = escala

        return escalas

    # ------------------------------------------------------------------
    # Lógica interna
    # ------------------------------------------------------------------

    def _gerar_escala_para_data(
        self,
        data: date,
        tipo: str,
        periodo: str,
        escala_anterior: Optional[Escala],
    ) -> Escala:

        escala = Escala(
            id=str(uuid.uuid4()),
            data=data,
            tipo=tipo,
            titulo=f"{tipo.capitalize()} – {data.strftime('%d/%m/%Y')}",
        )

        # IDs dos membros que tocaram no domingo anterior (regra 3)
        ids_domingo_anterior: set[str] = set()
        if escala_anterior:
            ids_domingo_anterior = {em.membro_id for em in escala_anterior.membros}

        # Índice rápido: instrumento_nome → lista de (membro, nivel_tecnico)
        candidatos_por_instrumento = self._candidatos_disponiveis(data, periodo)

        for nome_instrumento, vagas in self.INSTRUMENTOS_OBRIGATORIOS.items():
            candidatos = candidatos_por_instrumento.get(nome_instrumento, [])

            if not candidatos:
                escala.avisos.append(
                    f"⚠️  {data} | Nenhum músico disponível para '{nome_instrumento}'."
                )
                continue

            # Encontra o instrumento no banco
            instrumento = self._buscar_instrumento_por_nome(nome_instrumento)
            if instrumento is None:
                escala.avisos.append(
                    f"⚠️  Instrumento '{nome_instrumento}' não cadastrado no banco."
                )
                continue

            # ----------------------------------------------------------
            # Regra 2: precisa de ao menos 1 líder (nível 4 ou 5)
            # ----------------------------------------------------------
            lideres = [c for c in candidatos if c["nivel_tecnico"] >= 4]
            if not lideres:
                escala.avisos.append(
                    f"⚠️  {data} | Sem líder (nível ≥ 4) para '{nome_instrumento}'. "
                    f"Melhor disponível: nível {candidatos[0]['nivel_tecnico']}."
                )

            # ----------------------------------------------------------
            # Regra 1 + 3: ordena por disponibilidade e evita repetição
            # ----------------------------------------------------------
            candidatos_ordenados = self._ordenar_candidatos(
                candidatos=candidatos,
                ids_evitar=ids_domingo_anterior,
                data_atual=data,
            )

            selecionados = self._selecionar_vagas(
                candidatos_ordenados=candidatos_ordenados,
                vagas=vagas,
                lideres_ids={c["membro_id"] for c in lideres},
                escala=escala,
                instrumento=instrumento,
            )

            # Avisa se não conseguiu preencher todas as vagas
            if len(selecionados) < vagas:
                escala.avisos.append(
                    f"⚠️  {data} | Vagas para '{nome_instrumento}': "
                    f"precisava de {vagas}, encontrou {len(selecionados)}."
                )

        return escala

    def _candidatos_disponiveis(
        self, data: date, periodo: str
    ) -> dict[str, list[dict]]:
        """
        Retorna um dicionário {nome_instrumento: [candidatos]}
        com quem está disponível naquela data/período.

        Candidato = {membro_id, membro_nome, instrumento_id,
                     instrumento_nome, nivel_tecnico, total_disponibilidades}
        """
        # IDs de membros disponíveis nesta data/período
        ids_disponiveis: set[str] = {
            d.membro_id
            for d in self.db.disponibilidades
            if d.data == data and d.periodo in (periodo, "dia_todo")
        }

        # Contagem total de disponibilidades por membro (regra 1)
        total_disp: dict[str, int] = {}
        for d in self.db.disponibilidades:
            total_disp[d.membro_id] = total_disp.get(d.membro_id, 0) + 1

        resultado: dict[str, list[dict]] = {}

        for mi in self.db.membro_instrumentos:
            if mi.membro_id not in ids_disponiveis:
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

    def _ordenar_candidatos(
        self,
        candidatos: list[dict],
        ids_evitar: set[str],
        data_atual: date,
    ) -> list[dict]:
        """
        Ordena candidatos seguindo as regras de prioridade:
          1. Membros que NÃO tocaram no domingo anterior ficam na frente.
          2. Dentre eles, prioriza quem tem MAIS disponibilidades totais.
          3. Nível técnico como critério de desempate.
        """
        def chave(c: dict) -> tuple:
            tocou_ultimo_domingo = c["membro_id"] in ids_evitar
            return (
                tocou_ultimo_domingo,          # False (0) vem antes de True (1)
                -c["total_disponibilidades"],  # maior disponibilidade primeiro
                -c["nivel_tecnico"],           # maior nível como desempate
            )

        return sorted(candidatos, key=chave)

    def _selecionar_vagas(
        self,
        candidatos_ordenados: list[dict],
        vagas: int,
        lideres_ids: set[str],
        escala: Escala,
        instrumento: Instrumento,
    ) -> list[dict]:
        """
        Seleciona até `vagas` candidatos garantindo que a primeira
        vaga seja ocupada por um líder (nível ≥ 4), se possível.
        """
        selecionados: list[dict] = []
        ids_ja_escalados = {em.membro_id for em in escala.membros}
        lider_escalado = False

        # Primeiro passe: garante um líder
        for c in candidatos_ordenados:
            if len(selecionados) >= vagas:
                break
            if c["membro_id"] in ids_ja_escalados:
                continue
            if not lider_escalado and c["membro_id"] in lideres_ids:
                selecionados.append(c)
                ids_ja_escalados.add(c["membro_id"])
                lider_escalado = True

        # Segundo passe: preenche vagas restantes
        for c in candidatos_ordenados:
            if len(selecionados) >= vagas:
                break
            if c["membro_id"] in ids_ja_escalados:
                continue
            selecionados.append(c)
            ids_ja_escalados.add(c["membro_id"])

        # Registra na escala
        for c in selecionados:
            funcao = "lider" if c["nivel_tecnico"] >= 4 else "musico"
            escala.membros.append(
                EscalaMembro(
                    escala_id=escala.id,
                    membro_id=c["membro_id"],
                    instrumento_id=instrumento.id,
                    funcao=funcao,
                )
            )

        return selecionados

    def _buscar_instrumento_por_nome(self, nome: str) -> Optional[Instrumento]:
        return next(
            (i for i in self.db.instrumentos.values() if i.nome == nome),
            None,
        )


# ---------------------------------------------------------------------------
# Formatação de saída
# ---------------------------------------------------------------------------

def imprimir_escala(escala: Escala, db: BancoDados) -> None:
    print("=" * 56)
    print(f"  {escala.titulo}")
    print(f"  Status: {escala.status}")
    print("=" * 56)

    # Agrupa por instrumento para exibição
    por_instrumento: dict[str, list[str]] = {}
    for em in escala.membros:
        instrumento = db.instrumentos.get(em.instrumento_id)
        membro = db.membros.get(em.membro_id)
        if instrumento and membro:
            rotulo = f"{membro.nome} [{em.funcao}]"
            por_instrumento.setdefault(instrumento.nome, []).append(rotulo)

    for inst, membros in por_instrumento.items():
        print(f"  {inst:<12} {', '.join(membros)}")

    if escala.avisos:
        print()
        for aviso in escala.avisos:
            print(f"  {aviso}")
    print()


# ---------------------------------------------------------------------------
# Exemplo de uso
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    from datetime import date

    db = BancoDados()

    # --- Instrumentos ---
    instrumentos_raw = ["Voz", "Violão", "Bateria", "Guitarra", "Baixo", "Teclado"]
    for nome in instrumentos_raw:
        iid = str(uuid.uuid4())
        db.instrumentos[iid] = Instrumento(id=iid, nome=nome)

    def inst_id(nome: str) -> str:
        return next(i.id for i in db.instrumentos.values() if i.nome == nome)

    # --- Membros ---
    membros_raw = [
        ("Ana Lima",     True),
        ("Bruno Costa",  True),
        ("Carla Mendes", True),
        ("Diego Ramos",  True),
        ("Elaine Souza", True),
        ("Fábio Nunes",  True),
        ("Gabi Ferreira", True),
        ("Hugo Alves",   True),
    ]
    for nome, ativo in membros_raw:
        mid = str(uuid.uuid4())
        db.membros[mid] = Membro(id=mid, nome=nome, ativo=ativo)

    def mid(nome: str) -> str:
        return next(m.id for m in db.membros.values() if m.nome == nome)

    # --- Habilidades (membro × instrumento × nível) ---
    habilidades = [
        # (membro,          instrumento,  nível)
        ("Ana Lima",        "Voz",        5),
        ("Carla Mendes",    "Voz",        4),
        ("Elaine Souza",    "Voz",        3),
        ("Gabi Ferreira",   "Voz",        3),
        ("Bruno Costa",     "Violão",     5),
        ("Diego Ramos",     "Violão",     3),
        ("Fábio Nunes",     "Bateria",    4),
        ("Hugo Alves",      "Bateria",    2),
        ("Bruno Costa",     "Guitarra",   4),
        ("Diego Ramos",     "Guitarra",   3),
        ("Fábio Nunes",     "Baixo",      4),
        ("Hugo Alves",      "Baixo",      3),
        ("Ana Lima",        "Teclado",    4),
        ("Carla Mendes",    "Teclado",    3),
    ]
    for nome_m, nome_i, nivel in habilidades:
        db.membro_instrumentos.append(
            MembroInstrumento(
                membro_id=mid(nome_m),
                instrumento_id=inst_id(nome_i),
                nivel_tecnico=nivel,
            )
        )

    # --- Disponibilidades (4 domingos de abril/maio 2025) ---
    datas_culto = [
        date(2025, 4, 6),
        date(2025, 4, 13),
        date(2025, 4, 20),
        date(2025, 4, 27),
    ]

    # Todos disponíveis nos dois primeiros domingos
    disponiveis_geral = [
        "Ana Lima", "Bruno Costa", "Carla Mendes",
        "Diego Ramos", "Elaine Souza", "Fábio Nunes",
        "Gabi Ferreira", "Hugo Alves",
    ]
    for nome_m in disponiveis_geral:
        for dt in datas_culto[:2]:
            db.disponibilidades.append(
                Disponibilidade(
                    id=str(uuid.uuid4()),
                    membro_id=mid(nome_m),
                    data=dt,
                    periodo="manha",
                )
            )

    # Nos dois últimos domingos, Ana e Bruno estão fora (teste regra 3 e 4)
    disponiveis_restante = [
        "Carla Mendes", "Diego Ramos", "Elaine Souza",
        "Fábio Nunes", "Gabi Ferreira", "Hugo Alves",
    ]
    for nome_m in disponiveis_restante:
        for dt in datas_culto[2:]:
            db.disponibilidades.append(
                Disponibilidade(
                    id=str(uuid.uuid4()),
                    membro_id=mid(nome_m),
                    data=dt,
                    periodo="manha",
                )
            )

    # --- Gera e exibe escalas ---
    gerador = GeradorEscala(db)
    escalas = gerador.gerar_escala_semanal(
        datas=datas_culto,
        tipo="culto",
        periodo="manha",
    )

    print("\n🎵 ESCALA DE LOUVOR — ABRIL 2025\n")
    for escala in escalas:
        imprimir_escala(escala, db)
