"""Fluxo V2 de transações: regras -> histórico -> IA em lote,
reconciliação com lançamentos provisórios do iPhone e desfazer importação.
"""

from __future__ import annotations

from collections import Counter
from datetime import date
from typing import Any

import pandas as pd

from core import schema
from core.migration import CATEGORIAS_PADRAO, limpar_categoria_v1
from core.utils import (
    agora_iso,
    hash_arquivo,
    hash_dedup,
    normalizar_texto,
    novo_id,
    parse_data,
    parse_numero,
    vazio,
)
from expense_flow import (
    _chamar_groq_em_lote,
    chave_estabelecimento,
    identificar_e_tratar_arquivo,
)

CATEGORIAS_DESPESA = [n for n, t, _ in CATEGORIAS_PADRAO if t == "despesa"] + ["Transferência Interna", "A Revisar"]
CATEGORIAS_RECEITA = [n for n, t, _ in CATEGORIAS_PADRAO if t == "receita"] + ["Transferência Interna", "A Revisar"]
TODAS_CATEGORIAS_V2 = list(dict.fromkeys([n for n, _, _ in CATEGORIAS_PADRAO] + ["A Revisar"]))

MEIOS_PADRAO = ["credito", "pix", "debito", "apple_pay", "conta", "dinheiro"]
CONTAS_PADRAO_V2 = ["Nubank", "Inter", "Mercado Pago", "Dinheiro"]


def mapa_historico_v2(df_transacoes: pd.DataFrame) -> dict[str, str]:
    """Constrói mapa estabelecimento -> categoria mais frequente a partir da aba `transacoes`."""
    if df_transacoes is None or df_transacoes.empty:
        return {}
    contagens: dict[str, Counter] = {}
    for _, r in df_transacoes.iterrows():
        cat = str(r.get("categoria", "") or "").strip()
        if not cat or cat in ("A Revisar", "Erro"):
            continue
        chave = chave_estabelecimento(r.get("descricao", ""))
        if chave:
            contagens.setdefault(chave, Counter())[cat] += 1
    return {k: c.most_common(1)[0][0] for k, c in contagens.items()}


def aplicar_regras(descricao: str, df_regras: pd.DataFrame | None) -> str | None:
    if df_regras is None or df_regras.empty:
        return None
    alvo = normalizar_texto(descricao)
    if not alvo:
        return None
    regras = df_regras.copy()
    if "prioridade" in regras.columns:
        regras["prioridade"] = regras["prioridade"].apply(lambda x: parse_numero(x) or 0)
        regras = regras.sort_values("prioridade", ascending=False)
    for _, r in regras.iterrows():
        if str(r.get("ativa", "S")).upper() == "N":
            continue
        padrao = normalizar_texto(r.get("padrao", ""))
        cat = str(r.get("categoria", "") or "").strip()
        if padrao and cat and padrao in alvo:
            return cat
    return None


def sugerir_categoria_v2(
    descricao: str,
    valor: float,
    df_regras: pd.DataFrame | None,
    mapa_hist: dict[str, str],
) -> tuple[str | None, str]:
    """Retorna (categoria, fonte_sugestao) usando 1º regras, 2º histórico."""
    cat_regra = aplicar_regras(descricao, df_regras)
    if cat_regra:
        return limpar_categoria_v1(cat_regra, valor) or cat_regra, "Regra"

    chave = chave_estabelecimento(descricao)
    if chave:
        if chave in mapa_hist:
            return mapa_hist[chave], "Histórico"
        if len(chave) >= 5:
            for k, cat in mapa_hist.items():
                if len(k) >= 5 and (chave in k or k in chave):
                    return cat, "Histórico"
    return None, ""


def normalizar_meio_v2(fonte: Any) -> str:
    f = normalizar_texto(fonte)
    if "apple" in f:
        return "apple_pay"
    if "pix" in f:
        return "pix"
    if "cred" in f or "cart" in f:
        return "credito"
    if "deb" in f:
        return "debito"
    if "dinh" in f:
        return "dinheiro"
    return "conta"


def converter_arquivo_para_v2(uploaded_file) -> tuple[pd.DataFrame | None, str | None, str | None, str]:
    """Lê um arquivo de extrato/fatura e devolve (df_v2, tipo_arquivo, erro, file_hash)."""
    uploaded_file.seek(0)
    conteudo = uploaded_file.read()
    f_hash = hash_arquivo(conteudo)
    uploaded_file.seek(0)

    df_bruto, tipo_arq, erro = identificar_e_tratar_arquivo(uploaded_file)
    if erro or df_bruto is None:
        return None, tipo_arq, erro, f_hash

    linhas = []
    for _, r in df_bruto.iterrows():
        d = parse_data(r.get("Data"))
        v = parse_numero(r.get("Valor"))
        if d is None or v is None:
            continue
        desc = str(r.get("Descrição", "") or "").strip()
        conta = str(r.get("Conta", "Nubank") or "Nubank").strip()
        meio = normalizar_meio_v2(r.get("Fonte", "Extrato"))
        cat_inicial = limpar_categoria_v1(str(r.get("Categoria", "") or ""), v)
        linhas.append(
            {
                "data": d,
                "valor": round(v, 2),
                "descricao": desc,
                "categoria": cat_inicial,
                "conta": conta,
                "meio": meio,
                "observacao": str(r.get("Tipo Transação", "") or "").strip(),
                "arquivo": uploaded_file.name,
            }
        )
    return pd.DataFrame(linhas), tipo_arq, None, f_hash


def classificar_e_reconciliar_v2(
    df_lote: pd.DataFrame,
    df_transacoes: pd.DataFrame,
    df_regras: pd.DataFrame | None = None,
    groq_api_key: str | None = None,
    janela_dias_iphone: int = 2,
    nomes_titular: list[str] | None = None,
) -> tuple[pd.DataFrame, dict[str, int]]:
    """Classifica (Regras -> Histórico -> Groq em lote) e reconcilia com a aba `transacoes`."""
    df_out = df_lote.copy().reset_index(drop=True)
    mapa_hist = mapa_historico_v2(df_transacoes)
    padroes_titular = [normalizar_texto(n) for n in (nomes_titular or ["Felipe Romani", "Felipe Christofaro Romani"])]

    stats = {"regras": 0, "historico": 0, "ia": 0, "pendente": 0}
    pendentes_ia: list[int] = []

    for i, r in df_out.iterrows():
        desc = str(r["descricao"])
        val = float(r["valor"])
        desc_norm = normalizar_texto(desc)

        # Detecta transferência entre contas próprias ou movimentação interna de Cofrinho/Porquinho/CDB
        eh_mov_interna_reserva = any(
            termo in desc_norm
            for termo in (
                "dinheiro retirado cofrinho",
                "dinheiro reservado cofrinho",
                "aplicacao cdb porq",
                "resgate cdb porq",
                "investimento cdb a prazo",
                "liberacao cdb a prazo",
                "pagamento cartao de credito",
                "pagamento de fatura cartao de credito",
            )
        )
        if eh_mov_interna_reserva or (
            any(p in desc_norm for p in padroes_titular)
            and any(t in desc_norm for t in ("transfer", "pix", "ted", "doc"))
        ):
            df_out.at[i, "categoria"] = "Transferência Interna"
            stats["regras"] += 1
            continue

        cat_sug, fonte_sug = sugerir_categoria_v2(desc, val, df_regras, mapa_hist)
        if cat_sug:
            df_out.at[i, "categoria"] = cat_sug
            stats["regras" if fonte_sug == "Regra" else "historico"] += 1
        elif r.get("categoria") and r["categoria"] in TODAS_CATEGORIAS_V2 and r["categoria"] != "A Revisar":
            stats["historico"] += 1
        else:
            pendentes_ia.append(i)

    if pendentes_ia:
        if groq_api_key:
            for ini in range(0, len(pendentes_ia), 25):
                fatia = pendentes_ia[ini : ini + 25]
                itens = [
                    {
                        "id": int(idx),
                        "descricao": str(df_out.at[idx, "descricao"]),
                        "valor": float(df_out.at[idx, "valor"]),
                        "dia": "",
                        "fonte": str(df_out.at[idx, "meio"]),
                    }
                    for idx in fatia
                ]
                try:
                    resp_ia = _chamar_groq_em_lote(itens, groq_api_key)
                except Exception:
                    resp_ia = {}
                for idx in fatia:
                    if idx in resp_ia:
                        df_out.at[idx, "categoria"] = limpar_categoria_v1(
                            resp_ia[idx], float(df_out.at[idx, "valor"])
                        ) or "Outras Saídas"
                        stats["ia"] += 1
                    else:
                        df_out.at[idx, "categoria"] = "A Revisar"
                        stats["pendente"] += 1
        else:
            for idx in pendentes_ia:
                df_out.at[idx, "categoria"] = "A Revisar"
                stats["pendente"] += 1

    # Reconciliação contra base V2
    df_out["Incluir"] = True
    df_out["Status"] = "🆕 Nova"
    df_out["Match Existente"] = ""
    df_out["conciliada_com"] = ""

    existentes: list[dict[str, Any]] = []
    if df_transacoes is not None and not df_transacoes.empty:
        for _, r in df_transacoes.iterrows():
            d_ex = parse_data(r.get("data"))
            v_ex = parse_numero(r.get("valor"))
            if d_ex is None or v_ex is None:
                continue
            origem_ex = str(r.get("origem", "") or "").lower()
            status_ex = str(r.get("status", "") or "").lower()
            existentes.append(
                {
                    "id": str(r.get("id", "")),
                    "data": d_ex,
                    "valor": round(v_ex, 2),
                    "desc_raw": str(r.get("descricao", "") or ""),
                    "desc_norm": normalizar_texto(r.get("descricao", "")),
                    "categoria": str(r.get("categoria", "") or ""),
                    "hash": str(r.get("hash_dedup", "") or ""),
                    "is_iphone": origem_ex in ("iphone", "manual") or status_ex == "provisoria",
                    "ja_conciliada": not vazio(r.get("conciliada_com")),
                }
            )

    usados_iphone: set[str] = set()
    vistos_lote: set[str] = set()

    for i, r in df_out.iterrows():
        d_n: date = r["data"]
        v_n = round(float(r["valor"]), 2)
        h_n = hash_dedup(d_n, v_n, r["descricao"], r["conta"])
        df_out.at[i, "hash_dedup"] = h_n

        if h_n in vistos_lote:
            df_out.at[i, "Incluir"] = False
            df_out.at[i, "Status"] = "🔁 Duplicata no lote"
            df_out.at[i, "Match Existente"] = "Repetida neste envio"
            continue
        vistos_lote.add(h_n)

        # 1. Duplicata exata
        exato = next(
            (
                ex
                for ex in existentes
                if ex["hash"] == h_n
                or (
                    ex["data"] == d_n
                    and abs(ex["valor"] - v_n) < 0.01
                    and ex["desc_norm"] == normalizar_texto(r["descricao"])
                )
            ),
            None,
        )
        if exato is not None:
            df_out.at[i, "Incluir"] = False
            df_out.at[i, "Status"] = "🔁 Duplicata exata"
            df_out.at[i, "Match Existente"] = f"{exato['data']} | {exato['desc_raw']} ({exato['id']})"
            continue

        # 2. Conciliação com lançamento provisório do iPhone/Manual (mesmo valor, ±2 dias)
        candidatos = [
            ex
            for ex in existentes
            if ex["id"] not in usados_iphone
            and not ex["ja_conciliada"]
            and abs(ex["valor"] - v_n) < 0.01
            and abs((ex["data"] - d_n).days) <= janela_dias_iphone
        ]
        if candidatos:
            candidatos.sort(key=lambda ex: (0 if ex["is_iphone"] else 1, abs((ex["data"] - d_n).days)))
            melhor = candidatos[0]
            usados_iphone.add(melhor["id"])
            if melhor["is_iphone"]:
                # Por padrão marcamos Incluir=True para confirmar o provisório via update_by_key sem duplicar!
                df_out.at[i, "Incluir"] = True
                df_out.at[i, "Status"] = "📱 Conciliar c/ iPhone"
                df_out.at[i, "conciliada_com"] = melhor["id"]
                df_out.at[i, "Match Existente"] = (
                    f"[iPhone #{melhor['id']}] {melhor['data']} | {melhor['desc_raw']} ({melhor['categoria']})"
                )
                # Preserva a categoria que o usuário escolheu no menu de 1 toque do iPhone
                if melhor["categoria"] and melhor["categoria"] not in ("A Revisar", ""):
                    df_out.at[i, "categoria"] = melhor["categoria"]
            else:
                df_out.at[i, "Incluir"] = False
                df_out.at[i, "Status"] = "⚠️ Possível duplicata"
                df_out.at[i, "Match Existente"] = f"{melhor['data']} | {melhor['desc_raw']} ({melhor['id']})"

    return df_out, stats


def criar_registro_transacao(
    data_tx: date,
    valor: float,
    descricao: str,
    categoria: str,
    conta: str,
    meio: str,
    origem: str = "manual",
    status: str = "confirmada",
    importacao_id: str = "",
    conciliada_com: str = "",
    observacao: str = "",
) -> dict[str, Any]:
    eh_transf = "S" if categoria == "Transferência Interna" else "N"
    return {
        "id": novo_id(),
        "data": data_tx,
        "valor": round(float(valor), 2),
        "descricao": descricao.strip(),
        "categoria": categoria,
        "conta": conta,
        "meio": meio,
        "origem": origem,
        "status": "revisar" if categoria in ("", "A Revisar") else status,
        "importacao_id": importacao_id,
        "conciliada_com": conciliada_com,
        "hash_dedup": hash_dedup(data_tx, valor, descricao, conta),
        "transferencia": eh_transf,
        "observacao": observacao,
        "criado_em": agora_iso(),
        "atualizado_em": "",
    }


def gravar_lote_importado(
    repo,
    df_selecionadas: pd.DataFrame,
    nome_arquivo: str,
    hash_arq: str,
    formato: str,
) -> tuple[str, int, int]:
    """Grava novas transações por `append` e confirma provisórios do iPhone por `update_by_key`.
    Retorna (importacao_id, qtd_inseridas, qtd_conciliadas_iphone).
    """
    imp_id = novo_id()
    agora = agora_iso()
    novas_linhas: list[dict[str, Any]] = []
    qtd_conciliadas = 0

    for _, r in df_selecionadas.iterrows():
        id_iphone = str(r.get("conciliada_com", "") or "").strip()
        cat = str(r.get("categoria", "Outras Saídas") or "Outras Saídas")
        eh_transf = "S" if cat == "Transferência Interna" else "N"

        if id_iphone and str(r.get("Status", "")).startswith("📱"):
            # Atualiza o lançamento provisório do iPhone in-place (zero duplicação!)
            ok = repo.update_by_key(
                "transacoes",
                id_iphone,
                {
                    "data": r["data"],
                    "descricao": str(r["descricao"]).strip(),
                    "categoria": cat,
                    "conta": str(r["conta"]),
                    "meio": str(r["meio"]),
                    "status": "confirmada",
                    "importacao_id": imp_id,
                    "conciliada_com": "iphone_confirmado",
                    "transferencia": eh_transf,
                    "atualizado_em": agora,
                },
            )
            if ok:
                qtd_conciliadas += 1
                continue

        novas_linhas.append(
            criar_registro_transacao(
                data_tx=r["data"],
                valor=float(r["valor"]),
                descricao=str(r["descricao"]),
                categoria=cat,
                conta=str(r["conta"]),
                meio=str(r["meio"]),
                origem="import",
                status="confirmada",
                importacao_id=imp_id,
                observacao=str(r.get("observacao", "") or ""),
            )
        )

    qtd_inseridas = repo.append("transacoes", novas_linhas) if novas_linhas else 0
    repo.append(
        "importacoes",
        [
            {
                "id": imp_id,
                "arquivo": nome_arquivo,
                "hash_arquivo": hash_arq,
                "formato": formato,
                "qtd_linhas": qtd_inseridas + qtd_conciliadas,
                "importado_em": agora,
                "desfeita": "N",
            }
        ],
    )
    return imp_id, qtd_inseridas, qtd_conciliadas
