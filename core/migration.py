"""Transformações puras da V1 (abas `df`, `Investimentos`, `Orçamento Financeiro Mensal`) para o esquema V2.

Nada aqui acessa a rede: recebe DataFrames e devolve DataFrames, para ser testável.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from datetime import date
from typing import Any

import pandas as pd

from core import schema
from core.utils import agora_iso, hash_dedup, id_deterministico, normalizar_texto, parse_data, parse_numero, vazio

# ----------------------------------------------------------------------------- catálogos padrão

CATEGORIAS_PADRAO: list[tuple[str, str, str]] = [
    # (nome, tipo, grupo)
    ("Alimentação", "despesa", "Essencial"),
    ("Moradia", "despesa", "Essencial"),
    ("Transporte", "despesa", "Essencial"),
    ("Saúde", "despesa", "Essencial"),
    ("Educação", "despesa", "Essencial"),
    ("Serviços", "despesa", "Essencial"),
    ("Imposto, Juros e Multa", "despesa", "Essencial"),
    ("Restaurante", "despesa", "Estilo de vida"),
    ("Bares", "despesa", "Estilo de vida"),
    ("Academia", "despesa", "Estilo de vida"),
    ("Barbearia", "despesa", "Estilo de vida"),
    ("Compras", "despesa", "Estilo de vida"),
    ("Lazer", "despesa", "Estilo de vida"),
    ("Presente", "despesa", "Estilo de vida"),
    ("Doação", "despesa", "Estilo de vida"),
    ("Vestuário", "despesa", "Estilo de vida"),
    ("Viagem", "despesa", "Estilo de vida"),
    ("Assinaturas", "despesa", "Estilo de vida"),
    ("Outras Saídas", "despesa", "Estilo de vida"),
    ("Investimentos", "despesa", "Investimento"),
    ("Transferência Interna", "transferencia", "Transferência"),
    ("Salário", "receita", "Receita"),
    ("Renda", "receita", "Receita"),
    ("Rendimento", "receita", "Receita"),
    ("Cashback", "receita", "Receita"),
    ("Estorno", "receita", "Receita"),
    ("Bônus", "receita", "Receita"),
    ("Outras Entradas", "receita", "Receita"),
]

MAPA_SINONIMOS_CATEGORIA: dict[str, str] = {
    "alimentacao": "Alimentação",
    "comida": "Alimentação",
    "mercado": "Alimentação",
    "supermercado": "Alimentação",
    "moradia": "Moradia",
    "imovel moradia": "Moradia",
    "transporte": "Transporte",
    "saude": "Saúde",
    "drogaria": "Saúde",
    "educacao": "Educação",
    "ensino": "Educação",
    "servicos": "Serviços",
    "servico": "Serviços",
    "imposto juros e multa": "Imposto, Juros e Multa",
    "imposto": "Imposto, Juros e Multa",
    "taxas": "Imposto, Juros e Multa",
    "taxa": "Imposto, Juros e Multa",
    "restaurante": "Restaurante",
    "restaurantes": "Restaurante",
    "bares": "Bares",
    "bar": "Bares",
    "academia": "Academia",
    "barbearia": "Barbearia",
    "compras": "Compras",
    "lazer": "Lazer",
    "presente": "Presente",
    "doacao": "Doação",
    "vestuario": "Vestuário",
    "vestiario": "Vestuário",
    "viagem": "Viagem",
    "assinaturas": "Assinaturas",
    "outras saidas": "Outras Saídas",
    "saidas": "Outras Saídas",
    "outros": "Outras Saídas",
    "investimentos": "Investimentos",
    "investimento": "Investimentos",
    "reserva": "Investimentos",
    "transferencia interna": "Transferência Interna",
    "transferencia": "Transferência Interna",
    "salario": "Salário",
    "renda": "Renda",
    "rendimento": "Rendimento",
    "rendimentos": "Rendimento",
    "cashback": "Cashback",
    "estorno": "Estorno",
    "bonus": "Bônus",
    "outras entradas": "Outras Entradas",
    "entradas": "Outras Entradas",
    "recebida": "Outras Entradas",
    "recebimento": "Outras Entradas",
    "pix": "Outras Entradas",
    "dinheiro": "Outras Entradas",
    "r": "Outras Entradas",
}

CONTAS_EXTRAS: list[tuple[str, str, str, str]] = [
    # (nome, tipo, instituicao, moeda)
    ("Nubank", "banco", "Nubank", "BRL"),
    ("Inter", "banco", "Inter", "BRL"),
    ("Mercado Pago", "banco", "Mercado Pago", "BRL"),
    ("Dinheiro", "dinheiro", "-", "BRL"),
    ("Inter US", "corretora", "Inter", "USD"),
    ("Inter Porquinho", "renda_fixa", "Inter", "BRL"),
    ("Mercado Pago CDB", "renda_fixa", "Mercado Pago", "BRL"),
    ("Binance", "cripto", "Binance", "BRL"),
]

MEIO_MAP = {
    "credito": "credito",
    "cartao": "credito",
    "extrato": "conta",
    "debito": "debito",
    "pix": "pix",
    "apple pay": "apple_pay",
    "dinheiro": "dinheiro",
}

CATEGORIAS_PENDENTES = {"", "a revisar", "erro", "nan"}


@dataclass
class ResultadoMigracao:
    tabelas: dict[str, pd.DataFrame] = field(default_factory=dict)
    avisos: list[str] = field(default_factory=list)
    relatorio: dict[str, Any] = field(default_factory=dict)


def _col(df: pd.DataFrame, *candidatas: str) -> str | None:
    norm = {normalizar_texto(c): c for c in df.columns}
    for c in candidatas:
        if normalizar_texto(c) in norm:
            return norm[normalizar_texto(c)]
    return None


# ----------------------------------------------------------------------------- transações

def _origem(tipo_transacao: str, fonte: str) -> str:
    combinado = normalizar_texto(f"{tipo_transacao} {fonte}")
    if any(t in combinado for t in ("iphone", "apple pay", "atalho")):
        return "iphone"
    if "manual" in combinado:
        return "manual"
    return "migracao"


def _meio(fonte: str) -> str:
    f = normalizar_texto(fonte)
    if not f:
        return ""
    for chave, meio in MEIO_MAP.items():
        if chave in f:
            return meio
    return f.replace(" ", "_")


def limpar_categoria_v1(cat_bruta: str, valor: float) -> str:
    """Normaliza categorias da V1, incluindo textos longos gerados por LLM antigo e variações."""
    cat_str = str(cat_bruta or "").strip()
    if not cat_str:
        return ""
    norm = normalizar_texto(cat_str)
    if norm in CATEGORIAS_PENDENTES:
        return ""

    # 1. Match direto no dicionário de sinônimos
    if norm in MAPA_SINONIMOS_CATEGORIA:
        canon = MAPA_SINONIMOS_CATEGORIA[norm]
        if canon == "Outras Entradas" and valor < 0:
            return "Outras Saídas"
        if canon == "Outras Saídas" and valor > 0:
            return "Outras Entradas"
        return canon

    # 2. Se for resposta longa de LLM (ex: "Categoria: Alimentação" ou "... seria Compras"),
    # procura qual categoria canônica ou sinônimo aparece por último no texto
    if len(cat_str) > 25 or "\n" in cat_str or ":" in cat_str:
        melhor_pos = -1
        melhor_cat = ""
        for chave, canon in MAPA_SINONIMOS_CATEGORIA.items():
            if len(chave) < 4:
                continue
            pos = norm.rfind(chave)
            if pos > melhor_pos:
                melhor_pos = pos
                melhor_cat = canon
        if melhor_cat:
            if melhor_cat == "Outras Entradas" and valor < 0:
                return "Outras Saídas"
            if melhor_cat == "Outras Saídas" and valor > 0:
                return "Outras Entradas"
            return melhor_cat

    return cat_str


def migrar_transacoes(
    df_v1: pd.DataFrame,
    padroes_transferencia: list[str] | None = None,
) -> tuple[pd.DataFrame, list[str]]:
    """Converte a aba `df` da V1 para a aba `transacoes`."""
    avisos: list[str] = []
    if df_v1 is None or df_v1.empty:
        return pd.DataFrame(columns=schema.TRANSACOES.columns), ["Aba 'df' vazia."]

    c_data = _col(df_v1, "Data")
    c_valor = _col(df_v1, "Valor")
    c_desc = _col(df_v1, "Descrição", "Descricao")
    c_cat = _col(df_v1, "Categoria")
    c_fonte = _col(df_v1, "Fonte")
    c_conta = _col(df_v1, "Conta")
    c_tipo = _col(df_v1, "Tipo Transação", "Tipo Transacao", "Tipo")
    if not (c_data and c_valor and c_desc):
        raise ValueError(f"Aba 'df' sem colunas mínimas Data/Valor/Descrição. Colunas: {list(df_v1.columns)}")

    padroes = [normalizar_texto(p) for p in (padroes_transferencia or []) if p]
    ocorrencias: Counter = Counter()
    criado = agora_iso()
    linhas = []
    descartadas = 0
    categorias_higienizadas = 0

    for i, row in df_v1.iterrows():
        d = parse_data(row[c_data])
        v = parse_numero(row[c_valor])
        if d is None or v is None:
            descartadas += 1
            avisos.append(f"Linha {i + 2} da aba 'df' ignorada (data/valor inválidos): {row[c_data]!r} / {row[c_valor]!r}")
            continue

        desc = "" if vazio(row[c_desc]) else str(row[c_desc]).strip()
        cat_raw = "" if not c_cat or vazio(row[c_cat]) else str(row[c_cat]).strip()
        cat = limpar_categoria_v1(cat_raw, v)
        if cat != cat_raw and cat_raw:
            categorias_higienizadas += 1

        fonte = "" if not c_fonte or vazio(row[c_fonte]) else str(row[c_fonte]).strip()
        conta = "" if not c_conta or vazio(row[c_conta]) else str(row[c_conta]).strip()
        tipo_tx = "" if not c_tipo or vazio(row[c_tipo]) else str(row[c_tipo]).strip()

        h = hash_dedup(d, v, desc, conta)
        ocorrencias[h] += 1

        desc_norm = normalizar_texto(desc)
        tem_titular = bool(padroes) and any(p in desc_norm for p in padroes)
        tem_verbo_transf = any(t in desc_norm for t in ("transfer", "pix", "ted", "doc", "qr pix"))
        eh_transf = (cat == "Transferência Interna") or (tem_titular and tem_verbo_transf)

        if eh_transf:
            cat = "Transferência Interna"

        origem = _origem(tipo_tx, fonte)
        obs = tipo_tx if tipo_tx and origem == "migracao" else ""

        linhas.append(
            {
                "id": id_deterministico("v1", h, ocorrencias[h]),
                "data": d,
                "valor": round(v, 2),
                "descricao": desc,
                "categoria": cat,
                "conta": conta,
                "meio": _meio(fonte),
                "origem": origem,
                "status": "revisar" if normalizar_texto(cat) in CATEGORIAS_PENDENTES else "confirmada",
                "importacao_id": "",
                "conciliada_com": "",
                "hash_dedup": h,
                "transferencia": "S" if eh_transf else "N",
                "observacao": obs,
                "criado_em": criado,
                "atualizado_em": "",
            }
        )

    df_out = pd.DataFrame(linhas, columns=schema.TRANSACOES.columns)
    df_out = df_out.sort_values(["data", "descricao"], ascending=[False, True]).reset_index(drop=True)

    if categorias_higienizadas:
        avisos.append(f"{categorias_higienizadas} categorias antigas/textos longos de IA foram padronizadas automaticamente.")

    repetidas = sum(n - 1 for n in ocorrencias.values() if n > 1)
    if repetidas:
        avisos.append(
            f"{repetidas} transações idênticas (mesma data, valor, descrição e conta) foram mantidas. "
            "Podem ser compras repetidas reais ou duplicatas antigas; dá para revisar depois."
        )
    if descartadas:
        avisos.append(f"{descartadas} linhas ignoradas por data/valor inválidos.")
    return df_out, avisos


def catalogo_contas(transacoes: pd.DataFrame) -> pd.DataFrame:
    nomes_existentes = [c for c in transacoes.get("conta", pd.Series(dtype=str)).unique() if not vazio(c)]
    linhas = []
    vistos = set()
    for nome in nomes_existentes:
        linhas.append({"nome": nome, "tipo": "banco", "instituicao": nome, "moeda": "BRL", "ativa": "S"})
        vistos.add(normalizar_texto(nome))
    for nome, tipo, inst, moeda in CONTAS_EXTRAS:
        if normalizar_texto(nome) not in vistos:
            linhas.append({"nome": nome, "tipo": tipo, "instituicao": inst, "moeda": moeda, "ativa": "S"})
    df = pd.DataFrame(linhas)
    df.insert(0, "id", [id_deterministico("conta", n) for n in df["nome"]])
    return df[schema.CONTAS.columns]


def catalogo_categorias(transacoes: pd.DataFrame) -> pd.DataFrame:
    linhas = [{"nome": n, "tipo": t, "grupo": g, "ativa": "S"} for n, t, g in CATEGORIAS_PADRAO]
    conhecidas = {normalizar_texto(n) for n, _, _ in CATEGORIAS_PADRAO}

    if not transacoes.empty:
        for cat, grupo_df in transacoes.groupby("categoria"):
            if normalizar_texto(cat) in conhecidas | CATEGORIAS_PENDENTES:
                continue
            positivas = (grupo_df["valor"] > 0).sum()
            tipo = "receita" if positivas > len(grupo_df) / 2 else "despesa"
            linhas.append(
                {"nome": cat, "tipo": tipo, "grupo": "Receita" if tipo == "receita" else "A definir", "ativa": "S"}
            )
            conhecidas.add(normalizar_texto(cat))

    df = pd.DataFrame(linhas)
    df.insert(0, "id", [id_deterministico("cat", n) for n in df["nome"]])
    return df[schema.CATEGORIAS.columns]


# ----------------------------------------------------------------------------- investimentos

def migrar_investimentos(df_inv: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, list[str]]:
    """Converte a aba `Investimentos` (Inter US) em `ativos` + `operacoes`."""
    avisos: list[str] = []
    ativos: dict[str, dict[str, Any]] = {}
    operacoes = []
    criado = agora_iso()

    if df_inv is not None and not df_inv.empty:
        c_data = _col(df_inv, "Trade Date")
        c_sym = _col(df_inv, "Symbol")
        c_sec = _col(df_inv, "Security")
        c_act = _col(df_inv, "Action")
        c_price = _col(df_inv, "Price")
        c_qty = _col(df_inv, "Quantity")
        c_port = _col(df_inv, "Portfolio")
        if not (c_data and c_sym and c_price and c_qty):
            raise ValueError(f"Aba 'Investimentos' sem colunas esperadas. Colunas: {list(df_inv.columns)}")

        ocorr: Counter = Counter()
        for i, row in df_inv.iterrows():
            sym = "" if vazio(row[c_sym]) else str(row[c_sym]).strip().upper()
            d = parse_data(row[c_data])
            preco = parse_numero(row[c_price])
            qtd = parse_numero(row[c_qty])
            if not sym or d is None or preco is None or qtd is None:
                avisos.append(f"Linha {i + 2} de 'Investimentos' ignorada: {sym!r} {row[c_data]!r} {row[c_price]!r} {row[c_qty]!r}")
                continue

            acao = normalizar_texto(row[c_act]) if c_act else ""
            tipo = "venda" if ("sell" in acao or "vend" in acao or qtd < 0) else "compra"
            ativo_id = id_deterministico("ativo", sym)
            if sym not in ativos:
                nome = "" if not c_sec or vazio(row[c_sec]) else str(row[c_sec]).strip()
                ativos[sym] = {
                    "id": ativo_id,
                    "ticker": sym,
                    "nome": nome,
                    "classe": "etf_us" if "etf" in normalizar_texto(nome) else "acao_us",
                    "moeda": "USD",
                    "conta": "Inter US",
                    "fonte_cotacao": "yfinance",
                    "codigo_cotacao": sym.replace(".", "-"),
                    "ativo": "S",
                }

            qtd_abs = abs(qtd)
            chave = (d.isoformat(), sym, tipo, round(qtd_abs, 8), round(preco, 6))
            ocorr[chave] += 1
            obs = "" if not c_port or vazio(row[c_port]) else f"Portfolio: {row[c_port]}"
            operacoes.append(
                {
                    "id": id_deterministico("op", *chave, ocorr[chave]),
                    "data": d,
                    "ativo_id": ativo_id,
                    "conta": "Inter US",
                    "tipo": tipo,
                    "quantidade": round(qtd_abs, 8),
                    "preco": round(preco, 6),
                    "taxas": 0.0,
                    "valor_total": round(qtd_abs * preco, 2),
                    "moeda": "USD",
                    "importacao_id": "",
                    "observacao": obs,
                    "criado_em": criado,
                }
            )

    # Ativos que você já possui fora da Inter US
    for ticker, nome, classe, moeda, conta, fonte, codigo in [
        ("BTC", "Bitcoin", "cripto", "BRL", "Binance", "yfinance", "BTC-BRL"),
        ("PORQUINHO-INTER", "Meu Porquinho Inter", "renda_fixa", "BRL", "Inter Porquinho", "cdi", "CDI"),
        ("CDB-MP", "CDB Mercado Pago", "renda_fixa", "BRL", "Mercado Pago CDB", "cdi", "CDI"),
    ]:
        if ticker not in ativos:
            ativos[ticker] = {
                "id": id_deterministico("ativo", ticker),
                "ticker": ticker,
                "nome": nome,
                "classe": classe,
                "moeda": moeda,
                "conta": conta,
                "fonte_cotacao": fonte,
                "codigo_cotacao": codigo,
                "ativo": "S",
            }

    df_ativos = pd.DataFrame(list(ativos.values()), columns=schema.ATIVOS.columns)
    df_ops = pd.DataFrame(operacoes, columns=schema.OPERACOES.columns)
    if not df_ops.empty:
        df_ops = df_ops.sort_values(["data", "ativo_id"]).reset_index(drop=True)
    return df_ativos, df_ops, avisos


def renda_fixa_inicial() -> pd.DataFrame:
    linhas = [
        {
            "id": id_deterministico("rf", "PORQUINHO-INTER"),
            "ativo_id": id_deterministico("ativo", "PORQUINHO-INTER"),
            "instituicao": "Inter",
            "produto": "Meu Porquinho",
            "indexador": "CDI",
            "taxa_pct": 100.0,
            "data_aplicacao": "",
            "vencimento": "",
            "liquidez": "diaria",
        },
        {
            "id": id_deterministico("rf", "CDB-MP"),
            "ativo_id": id_deterministico("ativo", "CDB-MP"),
            "instituicao": "Mercado Pago",
            "produto": "CDB",
            "indexador": "CDI",
            "taxa_pct": 100.0,
            "data_aplicacao": "",
            "vencimento": "",
            "liquidez": "diaria",
        },
    ]
    return pd.DataFrame(linhas, columns=schema.RENDA_FIXA.columns)


# ----------------------------------------------------------------------------- orçamento / metas / config

def fatiar_orcamento_v1(df_orc: pd.DataFrame) -> dict[str, pd.DataFrame]:
    """Reproduz o fatiamento posicional de `ler_orcamento_mensal()` da V1."""
    receitas = df_orc.iloc[4:13, :2].reset_index(drop=True)
    receitas.columns = ["DESCRIÇÃO", "VALOR"]
    despesas = df_orc.iloc[4:33, 3:6].reset_index(drop=True)
    despesas.columns = ["ESSENCIAL/NÃO ESSENCIAL", "DESCRIÇÃO", "VALOR"]
    reserva = df_orc.iloc[16:22, :2].reset_index(drop=True)
    reserva.columns = ["INFORMAÇÃO", "VALOR"]
    info = df_orc.iloc[24:28, :2].reset_index(drop=True)
    info.columns = ["DESCRIÇÃO", "INFORMAÇÃO"]
    return {"receitas": receitas, "despesas": despesas, "reserva": reserva, "info": info}


def migrar_orcamento(blocos: dict[str, pd.DataFrame]) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    orc, metas, config = [], [], []

    for _, r in blocos.get("despesas", pd.DataFrame()).iterrows():
        desc, val = r.get("DESCRIÇÃO"), parse_numero(r.get("VALOR"))
        if vazio(desc) or val is None:
            continue
        essencial = normalizar_texto(r.get("ESSENCIAL/NÃO ESSENCIAL"))
        grupo = "Estilo de vida" if "nao" in essencial else ("Essencial" if essencial else "")
        orc.append({"id": id_deterministico("orc", "despesa", desc), "mes": "padrao", "categoria": str(desc).strip(), "grupo": grupo, "valor": abs(val)})

    for _, r in blocos.get("receitas", pd.DataFrame()).iterrows():
        desc, val = r.get("DESCRIÇÃO"), parse_numero(r.get("VALOR"))
        if vazio(desc) or val is None:
            continue
        orc.append({"id": id_deterministico("orc", "receita", desc), "mes": "padrao", "categoria": str(desc).strip(), "grupo": "Receita", "valor": abs(val)})

    alvo = atual = None
    for _, r in blocos.get("reserva", pd.DataFrame()).iterrows():
        info, val = normalizar_texto(r.get("INFORMAÇÃO")), parse_numero(r.get("VALOR"))
        if val is None:
            continue
        if "ideal" in info:
            alvo = val
        elif "atual" in info:
            atual = val
    if alvo is not None or atual is not None:
        metas.append({"id": id_deterministico("meta", "reserva"), "nome": "Reserva de emergência", "valor_alvo": alvo or 0.0, "valor_atual": atual or 0.0, "prazo": "", "observacao": "Migrado da aba Orçamento Financeiro Mensal"})

    for _, r in blocos.get("info", pd.DataFrame()).iterrows():
        if not vazio(r.get("DESCRIÇÃO")) and not vazio(r.get("INFORMAÇÃO")):
            config.append({"chave": f"perfil.{normalizar_texto(r['DESCRIÇÃO']).replace(' ', '_')}", "valor": str(r["INFORMAÇÃO"]).strip()})

    config += [
        {"chave": "moeda_base", "valor": "BRL"},
        {"chave": "versao_esquema", "valor": "2"},
        {"chave": "migrado_em", "valor": agora_iso()},
    ]
    return (
        pd.DataFrame(orc, columns=schema.ORCAMENTO.columns),
        pd.DataFrame(metas, columns=schema.METAS.columns),
        pd.DataFrame(config, columns=schema.CONFIG.columns),
    )


# ----------------------------------------------------------------------------- conferência

def conferir_totais(df_v1: pd.DataFrame, transacoes: pd.DataFrame) -> pd.DataFrame:
    """Compara quantidade e soma por mês entre a aba `df` (V1) e `transacoes` (V2)."""
    c_data, c_valor = _col(df_v1, "Data"), _col(df_v1, "Valor")
    v1 = pd.DataFrame(
        {
            "mes": df_v1[c_data].apply(lambda x: (parse_data(x) or date(1900, 1, 1)).strftime("%Y-%m")),
            "valor": df_v1[c_valor].apply(parse_numero),
        }
    ).dropna()
    v1 = v1[v1["mes"] != "1900-01"]
    v2 = pd.DataFrame({"mes": transacoes["data"].apply(lambda d: d.strftime("%Y-%m")), "valor": transacoes["valor"]})

    a = v1.groupby("mes")["valor"].agg(qtd_v1="count", soma_v1="sum")
    b = v2.groupby("mes")["valor"].agg(qtd_v2="count", soma_v2="sum")
    comp = a.join(b, how="outer").fillna(0).sort_index()
    comp["diferenca"] = (comp["soma_v2"] - comp["soma_v1"]).round(2)
    comp["ok"] = (comp["qtd_v1"] == comp["qtd_v2"]) & (comp["diferenca"].abs() < 0.01)
    return comp.reset_index()


def migrar_tudo(
    df_v1: pd.DataFrame,
    df_inv: pd.DataFrame | None,
    blocos_orc: dict[str, pd.DataFrame] | None,
    padroes_transferencia: list[str] | None = None,
) -> ResultadoMigracao:
    res = ResultadoMigracao()

    transacoes, av = migrar_transacoes(df_v1, padroes_transferencia)
    res.avisos += av
    res.tabelas["transacoes"] = transacoes
    res.tabelas["contas"] = catalogo_contas(transacoes)
    res.tabelas["categorias"] = catalogo_categorias(transacoes)
    res.tabelas["regras"] = pd.DataFrame(columns=schema.REGRAS.columns)
    res.tabelas["importacoes"] = pd.DataFrame(columns=schema.IMPORTACOES.columns)

    ativos, ops, av = migrar_investimentos(df_inv if df_inv is not None else pd.DataFrame())
    res.avisos += av
    res.tabelas["ativos"] = ativos
    res.tabelas["operacoes"] = ops
    res.tabelas["renda_fixa"] = renda_fixa_inicial()
    res.tabelas["cotacoes"] = pd.DataFrame(columns=schema.COTACOES.columns)

    if blocos_orc:
        orc, metas, config = migrar_orcamento(blocos_orc)
    else:
        orc, metas, config = migrar_orcamento({})
        res.avisos.append("Orçamento V1 não migrado (aba ausente ou layout inesperado).")
    res.tabelas["orcamento"] = orc
    res.tabelas["metas"] = metas
    res.tabelas["config"] = config

    comp = conferir_totais(df_v1, transacoes)
    res.relatorio = {
        "conferencia_mensal": comp,
        "meses_divergentes": int((~comp["ok"]).sum()),
        "qtd_v1": int(len(df_v1)),
        "qtd_v2": int(len(transacoes)),
        "pendentes_revisao": int((transacoes["status"] == "revisar").sum()),
        "posicoes_v2": (
            ops.assign(q=ops.apply(lambda r: r["quantidade"] if r["tipo"] == "compra" else -r["quantidade"], axis=1))
            .groupby("ativo_id")["q"].sum().round(6)
            if not ops.empty
            else pd.Series(dtype=float)
        ),
    }
    return res
