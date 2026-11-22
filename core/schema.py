"""Esquema das abas da planilha V2.

Regras:
- Uma aba por entidade, cabeçalho fixo na linha 1.
- Toda aba de entidade tem a coluna `id`.
- Nenhuma fórmula nas abas de dados (visualizações ficam em abas separadas).
- Datas gravadas como texto ISO (AAAA-MM-DD); números como números.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Tab:
    name: str
    columns: list[str]
    numeric: list[str] = field(default_factory=list)
    dates: list[str] = field(default_factory=list)
    key: str | None = "id"


TRANSACOES = Tab(
    name="transacoes",
    columns=[
        "id",
        "data",
        "valor",
        "descricao",
        "categoria",
        "conta",
        "meio",          # credito | debito | pix | apple_pay | conta | dinheiro
        "origem",        # import | iphone | manual | migracao
        "status",        # confirmada | provisoria | revisar
        "importacao_id",
        "conciliada_com",
        "hash_dedup",
        "transferencia",  # S | N
        "observacao",
        "criado_em",
        "atualizado_em",
    ],
    numeric=["valor"],
    dates=["data"],
)

CONTAS = Tab(
    name="contas",
    columns=["id", "nome", "tipo", "instituicao", "moeda", "ativa"],
)

CATEGORIAS = Tab(
    name="categorias",
    columns=["id", "nome", "tipo", "grupo", "ativa"],
)

REGRAS = Tab(
    name="regras",
    columns=["id", "padrao", "categoria", "prioridade", "ativa"],
    numeric=["prioridade"],
)

IMPORTACOES = Tab(
    name="importacoes",
    columns=["id", "arquivo", "hash_arquivo", "formato", "qtd_linhas", "importado_em", "desfeita"],
    numeric=["qtd_linhas"],
)

ORCAMENTO = Tab(
    name="orcamento",
    columns=["id", "mes", "categoria", "grupo", "valor"],
    numeric=["valor"],
)

METAS = Tab(
    name="metas",
    columns=["id", "nome", "valor_alvo", "valor_atual", "prazo", "observacao"],
    numeric=["valor_alvo", "valor_atual"],
    dates=["prazo"],
)

ATIVOS = Tab(
    name="ativos",
    columns=["id", "ticker", "nome", "classe", "moeda", "conta", "fonte_cotacao", "codigo_cotacao", "ativo"],
)

OPERACOES = Tab(
    name="operacoes",
    columns=[
        "id",
        "data",
        "ativo_id",
        "conta",
        "tipo",  # compra | venda | dividendo | juros | taxa | aporte | resgate | ajuste_saldo
        "quantidade",
        "preco",
        "taxas",
        "valor_total",
        "moeda",
        "importacao_id",
        "observacao",
        "criado_em",
    ],
    numeric=["quantidade", "preco", "taxas", "valor_total"],
    dates=["data"],
)

RENDA_FIXA = Tab(
    name="renda_fixa",
    columns=[
        "id",
        "ativo_id",
        "instituicao",
        "produto",
        "indexador",  # CDI | IPCA | PRE
        "taxa_pct",   # ex.: 100 (=100% do CDI), 6.5 (IPCA+6.5), 12 (pré 12% a.a.)
        "data_aplicacao",
        "vencimento",
        "liquidez",   # diaria | vencimento
    ],
    numeric=["taxa_pct"],
    dates=["data_aplicacao", "vencimento"],
)

COTACOES = Tab(
    name="cotacoes",
    columns=["data", "codigo", "valor", "moeda"],
    numeric=["valor"],
    dates=["data"],
    key=None,
)

CONFIG = Tab(
    name="config",
    columns=["chave", "valor"],
    key="chave",
)

ALL_TABS: dict[str, Tab] = {
    t.name: t
    for t in [
        TRANSACOES,
        CONTAS,
        CATEGORIAS,
        REGRAS,
        IMPORTACOES,
        ORCAMENTO,
        METAS,
        ATIVOS,
        OPERACOES,
        RENDA_FIXA,
        COTACOES,
        CONFIG,
    ]
}

# Abas da V1 (somente leitura durante a migração)
V1_TRANSACOES = "df"
V1_INVESTIMENTOS = "Investimentos"
V1_ORCAMENTO = "Orçamento Financeiro Mensal"
