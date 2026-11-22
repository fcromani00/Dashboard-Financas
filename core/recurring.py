"""Inteligência de Gastos Recorrentes, Assinaturas e Projeção de Parcelas (Finanças V2 — Frente 3).

Funcionalidades:
- Detecta compras parceladas tanto pela coluna `observacao` (padrão Banco Inter: 'Parcela 2/5')
  quanto pela `descricao` (padrão Nubank: 'Parcela 2/5', '2/5'), sem confundir com datas (DD/MM/YYYY).
- Projeta o comprometimento de faturas nos próximos meses com as parcelas restantes.
- Identifica Assinaturas / Custos Fixos mensais e Hábitos Recorrentes (ex: Uber, Buser, Padaria),
  indicando quais estão Ativos e quais pararam de cobrar (Inativos/Cancelados).
"""

from __future__ import annotations

import re
from datetime import date
from typing import Any

import pandas as pd

from core.utils import parse_data, parse_numero, vazio
from expense_flow import chave_estabelecimento

RE_PARCELA_EXPLICITA = re.compile(
    r"(?:parcela|parc\.?)\s*(\d{1,2})\s*(?:/|de)\s*(\d{1,2})\b",
    re.IGNORECASE,
)
# Captura "1/5" ou "02/10" isolado (sem "/2025" logo depois para não confundir com data DD/MM/YYYY)
RE_PARCELA_CURTA = re.compile(
    r"(?:^|[\s\-–(])(\d{1,2})/(\d{1,2})(?![/\d])(?:[\s\-–)]|$)"
)

CATEGORIAS_TIPICAS_FIXAS = {
    "Assinaturas",
    "Moradia",
    "Academia",
    "Educação",
    "Serviços",
}


def extrair_info_parcela(descricao: Any, observacao: Any = "") -> tuple[int, int] | None:
    """Retorna (parcela_atual, total_parcelas) se a transação for parcelada, ou None."""
    for texto in (str(observacao or ""), str(descricao or "")):
        if not texto:
            continue
        m = RE_PARCELA_EXPLICITA.search(texto)
        if m:
            atual, total = int(m.group(1)), int(m.group(2))
            if 1 <= atual <= total <= 48 and total >= 2:
                return atual, total

    # Na descrição, aceita formato curto "2/6" desde que não seja data
    desc_str = str(descricao or "")
    # Remove datas DD/MM/YYYY ou DD/MM/YY antes de procurar X/Y
    desc_sem_data = re.sub(r"\b\d{1,2}/\d{1,2}/\d{2,4}\b", " ", desc_str)
    m2 = RE_PARCELA_CURTA.search(desc_sem_data)
    if m2:
        atual, total = int(m2.group(1)), int(m2.group(2))
        if 1 <= atual <= total <= 36 and total >= 2:
            return atual, total

    return None


def _somar_meses(ano_mes: str, delta: int) -> str:
    ano, mes = [int(x) for x in ano_mes.split("-")]
    total = (ano * 12 + (mes - 1)) + delta
    novo_ano = total // 12
    novo_mes = (total % 12) + 1
    return f"{novo_ano:04d}-{novo_mes:02d}"


def analisar_parcelas(
    df_transacoes: pd.DataFrame,
    mes_referencia: str | None = None,
) -> dict[str, Any]:
    """Analisa compras parceladas no mês de referência e projeta parcelas futuras."""
    vazio_res = {
        "parcelas_mes": pd.DataFrame(),
        "parcelas_ativas": pd.DataFrame(),
        "projecao_futura": pd.DataFrame(),
        "total_mes": 0.0,
        "total_futuro": 0.0,
    }
    if df_transacoes is None or df_transacoes.empty:
        return vazio_res

    df = df_transacoes.copy()
    df["data_dt"] = df["data"].apply(parse_data)
    df["valor_num"] = df["valor"].apply(parse_numero)
    df = df.dropna(subset=["data_dt", "valor_num"])
    df = df[(df["valor_num"] < 0) & (df["transferencia"] != "S")].copy()
    if df.empty:
        return vazio_res

    df["ano_mes"] = df["data_dt"].apply(lambda d: d.strftime("%Y-%m"))
    if not mes_referencia:
        mes_referencia = str(df["ano_mes"].max())

    registros_parc = []
    for _, r in df.iterrows():
        info = extrair_info_parcela(r.get("descricao", ""), r.get("observacao", ""))
        if not info:
            continue
        atual, total = info
        val_abs = round(abs(float(r["valor_num"])), 2)
        chave = f"{chave_estabelecimento(r.get('descricao', ''))}|{total}|{val_abs:.2f}|{r.get('conta', '')}"
        registros_parc.append(
            {
                "id": r.get("id", ""),
                "data": r["data_dt"],
                "ano_mes": r["ano_mes"],
                "descricao": str(r.get("descricao", "")).strip(),
                "categoria": str(r.get("categoria", "")).strip(),
                "conta": str(r.get("conta", "")).strip(),
                "valor_parcela": val_abs,
                "parcela_atual": atual,
                "total_parcelas": total,
                "parcela_fmt": f"{atual}/{total}",
                "chave_compra": chave,
            }
        )

    if not registros_parc:
        return vazio_res

    df_p = pd.DataFrame(registros_parc)
    parcelas_mes = (
        df_p[df_p["ano_mes"] == mes_referencia]
        .sort_values(["valor_parcela", "descricao"], ascending=[False, True])
        .reset_index(drop=True)
    )

    # Considera compras até o mês de referência para projetar o que falta pagar dali em diante
    df_ate_ref = df_p[df_p["ano_mes"] <= mes_referencia].sort_values(
        ["ano_mes", "parcela_atual"], ascending=[True, True]
    )
    ultimas_por_compra = df_ate_ref.groupby("chave_compra", as_index=False).last()

    ativas_rows = []
    projecao_rows = []

    for _, r in ultimas_por_compra.iterrows():
        restantes = int(r["total_parcelas"]) - int(r["parcela_atual"])
        if restantes <= 0:
            continue
        # Se a última parcela registrada foi há mais de 3 meses do mês de referência, a compra já deve ter encerrado
        ym_ult = str(r["ano_mes"])
        a_u, m_u = [int(x) for x in ym_ult.split("-")]
        a_r, m_r = [int(x) for x in mes_referencia.split("-")]
        gap_meses = (a_r - a_u) * 12 + (m_r - m_u)
        if gap_meses > restantes:
            continue

        val_p = float(r["valor_parcela"])
        total_restante = round(restantes * val_p, 2)
        ultimo_mes_prev = _somar_meses(ym_ult, restantes)

        ativas_rows.append(
            {
                "descricao": r["descricao"],
                "categoria": r["categoria"],
                "conta": r["conta"],
                "progresso": f"{int(r['parcela_atual'])}/{int(r['total_parcelas'])}",
                "valor_parcela": val_p,
                "parcelas_restantes": restantes,
                "saldo_restante": total_restante,
                "termino_previsto": ultimo_mes_prev,
            }
        )

        for k in range(1, restantes + 1):
            mes_fut = _somar_meses(ym_ult, k)
            if mes_fut > mes_referencia:
                projecao_rows.append(
                    {
                        "ano_mes": mes_fut,
                        "descricao": r["descricao"],
                        "parcela": f"{int(r['parcela_atual']) + k}/{int(r['total_parcelas'])}",
                        "valor": val_p,
                    }
                )

    df_ativas = (
        pd.DataFrame(ativas_rows).sort_values("saldo_restante", ascending=False).reset_index(drop=True)
        if ativas_rows
        else pd.DataFrame()
    )
    if projecao_rows:
        df_proj_raw = pd.DataFrame(projecao_rows)
        df_proj = (
            df_proj_raw.groupby("ano_mes", as_index=False)
            .agg(valor_comprometido=("valor", "sum"), qtd_parcelas=("valor", "count"))
            .sort_values("ano_mes")
            .reset_index(drop=True)
        )
        df_proj["valor_comprometido"] = df_proj["valor_comprometido"].round(2)
    else:
        df_proj = pd.DataFrame(columns=["ano_mes", "valor_comprometido", "qtd_parcelas"])

    return {
        "parcelas_mes": parcelas_mes,
        "parcelas_ativas": df_ativas,
        "projecao_futura": df_proj,
        "total_mes": round(float(parcelas_mes["valor_parcela"].sum()), 2) if not parcelas_mes.empty else 0.0,
        "total_futuro": round(float(df_proj["valor_comprometido"].sum()), 2) if not df_proj.empty else 0.0,
    }


def detectar_recorrencias(
    df_transacoes: pd.DataFrame,
    min_meses: int = 3,
    janela_ativo_dias: int = 65,
) -> dict[str, Any]:
    """Detecta Assinaturas/Custos Fixos e Hábitos Recorrentes no histórico de transações."""
    vazio_res = {
        "fixos": pd.DataFrame(),
        "habitos": pd.DataFrame(),
        "total_fixos_ativos_mes": 0.0,
        "qtd_fixos_ativos": 0,
    }
    if df_transacoes is None or df_transacoes.empty:
        return vazio_res

    df = df_transacoes.copy()
    df["data_dt"] = df["data"].apply(parse_data)
    df["valor_num"] = df["valor"].apply(parse_numero)
    df = df.dropna(subset=["data_dt", "valor_num"])
    df = df[
        (df["valor_num"] < 0)
        & (df["transferencia"] != "S")
        & (~df["categoria"].isin(["Transferência Interna", "Investimentos"]))
    ].copy()
    if df.empty:
        return vazio_res

    # Ignora compras parceladas para não confundi-las com assinaturas
    mask_parc = df.apply(
        lambda r: extrair_info_parcela(r.get("descricao", ""), r.get("observacao", "")) is not None,
        axis=1,
    )
    df = df[~mask_parc].copy()
    if df.empty:
        return vazio_res

    df["ano_mes"] = df["data_dt"].apply(lambda d: d.strftime("%Y-%m"))
    df["gasto_abs"] = df["valor_num"].abs()
    df["chave"] = df["descricao"].apply(chave_estabelecimento)
    df = df[df["chave"].str.len() >= 3].copy()

    data_max_base: date = df["data_dt"].max()

    fixos_rows = []
    habitos_rows = []

    for chave, grp in df.groupby("chave"):
        meses_unicos = grp["ano_mes"].nunique()
        cat_moda = grp["categoria"].mode().iloc[0] if not grp["categoria"].mode().empty else ""
        min_m_exigido = 2 if cat_moda in CATEGORIAS_TIPICAS_FIXAS else min_meses
        if meses_unicos < min_m_exigido:
            continue

        qtd_total = len(grp)
        freq_por_mes = qtd_total / meses_unicos
        gasto_por_mes = grp.groupby("ano_mes")["gasto_abs"].sum()
        media_mensal = float(gasto_por_mes.mean())
        desvio_rel = (float(gasto_por_mes.std()) / media_mensal) if (len(gasto_por_mes) > 1 and media_mensal > 0) else 0.0

        ult_data: date = grp["data_dt"].max()
        ativo = (data_max_base - ult_data).days <= janela_ativo_dias
        status_str = "🟢 Ativo" if ativo else "⚪ Inativo"

        nome_exibicao = (
            grp.sort_values("data_dt", ascending=False)["descricao"].iloc[0].strip()
        )
        conta_moda = grp["conta"].mode().iloc[0] if not grp["conta"].mode().empty else ""

        item = {
            "estabelecimento": nome_exibicao,
            "categoria": cat_moda,
            "conta": conta_moda,
            "meses_cobrado": int(meses_unicos),
            "ocorrencias": int(qtd_total),
            "media_mensal": round(media_mensal, 2),
            "ultima_cobranca": ult_data,
            "total_historico": round(float(grp["gasto_abs"].sum()), 2),
            "status": status_str,
            "_ativo": ativo,
        }

        # Critério para Custo Fixo / Assinatura vs. Hábito Recorrente Variável
        eh_fixo = (freq_por_mes <= 1.35 and desvio_rel <= 0.25) or (
            cat_moda in CATEGORIAS_TIPICAS_FIXAS and freq_por_mes <= 1.6
        )
        if eh_fixo:
            fixos_rows.append(item)
        else:
            habitos_rows.append(item)

    df_fixos = (
        pd.DataFrame(fixos_rows)
        .sort_values(["_ativo", "media_mensal"], ascending=[False, False])
        .reset_index(drop=True)
        if fixos_rows
        else pd.DataFrame()
    )
    df_habitos = (
        pd.DataFrame(habitos_rows)
        .sort_values(["_ativo", "media_mensal"], ascending=[False, False])
        .reset_index(drop=True)
        if habitos_rows
        else pd.DataFrame()
    )

    total_fixos_ativos = (
        round(float(df_fixos[df_fixos["_ativo"]]["media_mensal"].sum()), 2)
        if not df_fixos.empty
        else 0.0
    )
    qtd_fixos_ativos = int(df_fixos["_ativo"].sum()) if not df_fixos.empty else 0

    for d_out in (df_fixos, df_habitos):
        if "_ativo" in d_out.columns:
            d_out.drop(columns=["_ativo"], inplace=True)

    return {
        "fixos": df_fixos,
        "habitos": df_habitos,
        "total_fixos_ativos_mes": total_fixos_ativos,
        "qtd_fixos_ativos": qtd_fixos_ativos,
    }
