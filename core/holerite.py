"""Leitor de Holerites PDF (Mercado Pago / Mercado Livre) e consolidador de Renda, Impostos, FGTS e PGBL."""

from __future__ import annotations

import io
import re
from typing import Any

import pandas as pd

from core.utils import agora_iso, id_deterministico, parse_numero

_MESES_PT = {
    "janeiro": "01",
    "fevereiro": "02",
    "março": "03",
    "marco": "03",
    "abril": "04",
    "maio": "05",
    "junho": "06",
    "julho": "07",
    "agosto": "08",
    "setembro": "09",
    "outubro": "10",
    "novembro": "11",
    "dezembro": "12",
}


def _num_br(txt: str | None) -> float:
    if not txt:
        return 0.0
    v = parse_numero(txt)
    return float(v) if v is not None else 0.0


def parse_holerite_texto(texto: str) -> dict[str, Any]:
    """Extrai rubricas estruturadas a partir do texto OCR/PDF de um holerite do Mercado Pago."""
    linhas = [re.sub(r"\s+", " ", ln).strip() for ln in texto.splitlines() if ln.strip()]
    t_full = "\n".join(linhas)

    empresa = "MERCADOPAGO.COM REP. LTDA"
    for ln in linhas[:6]:
        if "LTDA" in ln.upper() or "S.A" in ln.upper() or "MERCADO" in ln.upper():
            empresa = re.sub(r"\s*CNPJ:.*$", "", ln, flags=re.IGNORECASE).strip()
            break

    # Competência (MES: Outubro ANO: 2026)
    competencia = ""
    m_comp = re.search(r"MES:\s*([A-Za-zçÇ]+)\s+ANO:\s*(\d{4})", t_full, re.IGNORECASE)
    if m_comp:
        mes_num = _MESES_PT.get(m_comp.group(1).strip().lower(), "01")
        competencia = f"{m_comp.group(2)}-{mes_num}"

    # Cargo / Função
    cargo = ""
    m_func = re.search(
        r"SALARIO\s+FUN[ÇC][ÃA]O\s+SETOR\s+[\d.,]+\s+(.+?)\s+(?:Asset|Tech|Finance|People|Data|Product|Legal|Ops)",
        " ".join(linhas),
        re.IGNORECASE,
    )
    if m_func:
        cargo = m_func.group(1).strip()

    # Salário base (linha logo após SALARIO ou após o número de registro)
    salario_base = 0.0
    for idx, ln in enumerate(linhas):
        if ln.upper() == "SALARIO" and idx + 1 < len(linhas):
            m_sal = re.search(r"([\d.]+,\d{2})", linhas[idx + 1])
            if m_sal:
                salario_base = _num_br(m_sal.group(1))
                break
        m_sal_inline = re.search(r"SALARIO\s+([\d.]+,\d{2})", ln, re.IGNORECASE)
        if m_sal_inline:
            salario_base = _num_br(m_sal_inline.group(1))
            break
    if salario_base == 0.0:
        m_fb = re.search(r"\b\d{8}\b\s+([\d.]+,\d{2})", " ".join(linhas))
        if m_fb:
            salario_base = _num_br(m_fb.group(1))

    # Bases e FGTS
    def _extrair_campo(padrao: str) -> float:
        m = re.search(padrao, t_full, re.IGNORECASE)
        return _num_br(m.group(1)) if m else 0.0

    base_irrf = _extrair_campo(r"Base IRRF:\s*([\d.,]+)")
    base_inss = _extrair_campo(r"Base INSS:\s*([\d.,]+)")
    base_fgts = _extrair_campo(r"Base FGTS:\s*([\d.,]+)")
    fgts = _extrair_campo(r"(?<!Base )FGTS:\s*([\d.,]+)")

    # Totais (suporta valor na mesma linha ou na linha seguinte)
    def _extrair_bloco_total(label_regex: str) -> float:
        for idx, ln in enumerate(linhas):
            if re.search(label_regex, ln, re.IGNORECASE):
                m_same = re.search(r"([\d.]+,\d{2})\s*$", ln)
                if m_same:
                    return _num_br(m_same.group(1))
                if idx + 1 < len(linhas):
                    m_next = re.search(r"([\d.]+,\d{2})", linhas[idx + 1])
                    if m_next:
                        return _num_br(m_next.group(1))
        return 0.0

    total_proventos = _extrair_bloco_total(r"TOTAL DE\s*PROVENTOS|^PROVENTOS$")
    if total_proventos == 0.0:
        m_tp = re.search(r"TOTAL DE\s+PROVENTOS\s+([\d.]+,\d{2})", " ".join(linhas), re.IGNORECASE)
        if m_tp:
            total_proventos = _num_br(m_tp.group(1))

    total_descontos = _extrair_bloco_total(r"TOTAL DE\s*DESCONTOS|^DESCONTOS$")
    if total_descontos == 0.0:
        m_td = re.search(r"TOTAL DE\s+DESCONTOS\s+([\d.]+,\d{2})", " ".join(linhas), re.IGNORECASE)
        if m_td:
            total_descontos = _num_br(m_td.group(1))

    total_liquido = _extrair_bloco_total(r"TOTAL L[ÍI]QUIDO")
    if total_liquido == 0.0 and total_proventos > 0:
        total_liquido = round(total_proventos - total_descontos, 2)

    # Rubricas específicas
    inss = 0.0
    irrf = 0.0
    pgbl = 0.0
    beneficios_desc = 0.0
    ajuda_custo = 0.0
    adiantamento = 0.0

    for ln in linhas:
        m_val = re.search(r"([\d.]+,\d{2})\s*$", ln)
        if not m_val:
            continue
        val = _num_br(m_val.group(1))
        up = ln.upper()
        if "/314" in up or ("CONTR. INSS" in up and "PROVIS" not in up):
            inss += val
        elif "/401" in up or "TRIBUTO IRRF" in up:
            irrf += val
        elif "9FPH" in up or "PGBL" in up:
            pgbl += val
        elif "0830" in up or "AJUDA DE CUSTO" in up:
            ajuda_custo += val
        elif "/B02" in up or "ADIANTAMENTO PAGO" in up:
            adiantamento += val
        elif any(k in up for k in ("VALE-REFEI", "VALE ALIMENTA", "ASSISTÊNCIA MÉDICA", "ASSISTENCIA MEDICA", "ODONTOL")):
            beneficios_desc += val

    return {
        "id": id_deterministico("holerite", competencia or "sem_data", empresa),
        "competencia": competencia,
        "empresa": empresa,
        "cargo": cargo,
        "salario_base": round(salario_base, 2),
        "total_proventos": round(total_proventos, 2),
        "total_descontos": round(total_descontos, 2),
        "total_liquido": round(total_liquido, 2),
        "inss": round(inss, 2),
        "irrf": round(irrf, 2),
        "fgts": round(fgts, 2),
        "pgbl": round(pgbl, 2),
        "beneficios_desconto": round(beneficios_desc, 2),
        "ajuda_custo": round(ajuda_custo, 2),
        "adiantamento": round(adiantamento, 2),
        "base_inss": round(base_inss, 2),
        "base_irrf": round(base_irrf, 2),
        "base_fgts": round(base_fgts, 2),
        "observacao": "",
        "criado_em": agora_iso(),
    }


def tratar_holerite_pdf(file_obj: Any) -> dict[str, Any]:
    """Lê um arquivo PDF de holerite (path, bytes ou UploadedFile) com PyPDF2 e extrai os campos."""
    import PyPDF2

    if isinstance(file_obj, (bytes, bytearray)):
        stream = io.BytesIO(file_obj)
    else:
        stream = file_obj
        if hasattr(stream, "seek"):
            stream.seek(0)

    reader = PyPDF2.PdfReader(stream)
    texto = "\n".join((page.extract_text() or "") for page in reader.pages)
    return parse_holerite_texto(texto)


def resumir_holerites(df_hol: pd.DataFrame) -> dict[str, float]:
    """Calcula totais acumulados de renda, impostos, FGTS, PGBL e margem até 12% para dedução de IRPF."""
    if df_hol is None or df_hol.empty:
        return {
            "meses": 0,
            "ultimo_salario_base": 0.0,
            "total_proventos": 0.0,
            "total_liquido_folha": 0.0,
            "total_inss": 0.0,
            "total_irrf": 0.0,
            "aliquota_efetiva_pct": 0.0,
            "total_fgts": 0.0,
            "total_pgbl": 0.0,
            "limite_pgbl_12_pct": 0.0,
            "margem_pgbl_restante": 0.0,
        }

    df = df_hol.sort_values("competencia")
    prov = float(df["total_proventos"].sum())
    inss = float(df["inss"].sum())
    irrf = float(df["irrf"].sum())
    pgbl = float(df["pgbl"].sum())
    fgts = float(df["fgts"].sum())
    liq = float(df["total_liquido"].sum()) + float(df["adiantamento"].sum())
    ult_sal = float(df["salario_base"].iloc[-1])

    limite_12 = round(prov * 0.12, 2)
    margem_pgbl = round(max(0.0, limite_12 - pgbl), 2)
    aliq_efetiva = round(((inss + irrf) / prov * 100.0) if prov > 0 else 0.0, 2)

    return {
        "meses": int(len(df)),
        "ultimo_salario_base": round(ult_sal, 2),
        "total_proventos": round(prov, 2),
        "total_liquido_folha": round(liq, 2),
        "total_inss": round(inss, 2),
        "total_irrf": round(irrf, 2),
        "aliquota_efetiva_pct": aliq_efetiva,
        "total_fgts": round(fgts, 2),
        "total_pgbl": round(pgbl, 2),
        "limite_pgbl_12_pct": limite_12,
        "margem_pgbl_restante": margem_pgbl,
    }
