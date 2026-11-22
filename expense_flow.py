"""Módulo de fluxo de gastos: parsing multi-banco, classificação híbrida,
deduplicação e conciliação com lançamentos do iPhone/manuais.
"""

from __future__ import annotations

import json
import re
import unicodedata
from collections import Counter
from datetime import date, datetime
from typing import Any

import pandas as pd

CATEGORIAS_ENTRADA = [
    "Salário",
    "Renda",
    "Rendimento",
    "Cashback",
    "Estorno",
    "Bônus",
    "Transferência Interna",
    "Outras Entradas",
]

CATEGORIAS_SAIDA = [
    "Alimentação",
    "Restaurante",
    "Bares",
    "Academia",
    "Barbearia",
    "Compras",
    "Lazer",
    "Educação",
    "Investimentos",
    "Imposto, Juros e Multa",
    "Presente",
    "Doação",
    "Moradia",
    "Transporte",
    "Vestuário",
    "Viagem",
    "Transferência Interna",
    "Outras Saídas",
]

TODAS_CATEGORIAS = list(dict.fromkeys(CATEGORIAS_SAIDA + CATEGORIAS_ENTRADA + ["A Revisar"]))

CONTAS_PADRAO = ["Nubank", "Inter", "Mercado Pago", "Dinheiro", "Outra"]
FONTES_PADRAO = ["Crédito", "Pix", "Débito", "Extrato", "Apple Pay", "Dinheiro"]

DIAS_SEMANA_MAP = {
    "Monday": "Segunda",
    "Tuesday": "Terça",
    "Wednesday": "Quarta",
    "Thursday": "Quinta",
    "Friday": "Sexta",
    "Saturday": "Sábado",
    "Sunday": "Domingo",
}


def dia_semana_pt(dt_series: pd.Series) -> pd.Series:
    return pd.to_datetime(dt_series, errors="coerce").dt.day_name().replace(DIAS_SEMANA_MAP)


def parse_valor_brl(valor: Any) -> float:
    """Converte strings monetárias BR/US ou números em float."""
    if pd.isna(valor):
        return 0.0
    if isinstance(valor, (int, float)):
        return float(valor)

    texto = str(valor).replace("R$", "").replace("\xa0", "").replace(" ", "").strip()
    if not texto:
        return 0.0

    # Trata casos como "-R$ 10,00" ou "-\xa010,00"
    negativo = texto.startswith("-")
    texto = texto.lstrip("+-")

    if "," in texto and "." in texto:
        if texto.rfind(",") > texto.rfind("."):
            texto = texto.replace(".", "").replace(",", ".")
        else:
            texto = texto.replace(",", "")
    elif "," in texto:
        texto = texto.replace(",", ".")

    num = float(texto)
    return -num if negativo else num


def normalizar_descricao(texto: Any) -> str:
    """Normaliza descrições bancárias para melhorar match de histórico e deduplicação."""
    s = str(texto or "").lower()
    s = unicodedata.normalize("NFKD", s)
    s = "".join(ch for ch in s if not unicodedata.combining(ch))
    # Remove padrões de parcela ex: "parcela 2/6", "parcela 2 de 6", "2/6", "02/10"
    s = re.sub(r"\bparcela\s*\d+\s*(?:/|de)\s*\d+\b", " ", s)
    s = re.sub(r"\b\d{1,2}\s*/\s*\d{1,2}\b", " ", s)
    # Remove símbolos mantendo letras, números e espaços
    s = re.sub(r"[^a-z0-9\s]", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def chave_estabelecimento(texto: Any) -> str:
    """Gera uma chave estável do estabelecimento removendo ruídos numéricos longos (CPF/CNPJ/IDs)."""
    s = normalizar_descricao(texto)
    # Remove sequências numéricas longas (IDs, contas, agências, CNPJ)
    s = re.sub(r"\b\d{4,}\b", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def padronizar_colunas_transacoes(df: pd.DataFrame) -> pd.DataFrame:
    """Garante colunas mínimas padronizadas e tipos consistentes."""
    df = df.copy()
    if "Data" in df.columns:
        dt = pd.to_datetime(df["Data"], errors="coerce")
        df["Data"] = dt.dt.date
        df["Ano/Mês"] = dt.dt.strftime("%Y-%m")
        if "Dia da Semana" not in df.columns or df["Dia da Semana"].isna().any():
            df["Dia da Semana"] = dt.dt.day_name().replace(DIAS_SEMANA_MAP)
    if "Valor" in df.columns:
        df["Valor"] = df["Valor"].apply(parse_valor_brl).round(2)
    if "Descrição" in df.columns:
        df["Descrição"] = df["Descrição"].fillna("").astype(str).str.strip()
    if "Categoria" not in df.columns:
        df["Categoria"] = ""
    else:
        df["Categoria"] = df["Categoria"].fillna("").astype(str).str.strip()
    if "Fonte" not in df.columns:
        df["Fonte"] = "Extrato"
    if "Conta" not in df.columns:
        df["Conta"] = "Nubank"
    if "Tipo Transação" not in df.columns:
        df["Tipo Transação"] = ""
    return df


def identificar_e_tratar_arquivo(uploaded_file) -> tuple[pd.DataFrame | None, str | None, str | None]:
    """Detecta automaticamente o tipo de extrato/fatura e retorna (df, tipo, erro)."""
    from functions import (
        tratar_extrato_inter,
        tratar_extrato_mercado_pago,
        tratar_extrato_nubank,
        tratar_fatura_inter,
        tratar_fatura_nubank,
        tratar_fatura_nubank_pdf,
    )

    nome = uploaded_file.name
    nome_lower = nome.lower()

    if nome_lower.endswith(".csv"):
        uploaded_file.seek(0)
        arquivo_df = None
        try:
            arquivo_df = pd.read_csv(uploaded_file)
        except pd.errors.ParserError:
            uploaded_file.seek(0)
            try:
                arquivo_df = pd.read_csv(uploaded_file, header=4, sep=";")
            except Exception as exc:
                return None, None, f"Erro ao ler CSV '{nome}': {exc}"
        except Exception as exc:
            return None, None, f"Erro ao ler CSV '{nome}': {exc}"

        colunas = [str(c).strip() for c in arquivo_df.columns]

        # Se leu tudo em 1 coluna com ';', tenta identificar Mercado Pago ou Inter ';'
        if colunas == ["INITIAL_BALANCE;CREDITS;DEBITS;FINAL_BALANCE"]:
            uploaded_file.seek(0)
            arquivo_df = pd.read_csv(uploaded_file, header=2, sep=";")
            tipo = "Extrato Mercado Pago"
            df_tratado = tratar_extrato_mercado_pago(arquivo_df)
            return padronizar_colunas_transacoes(df_tratado), tipo, None

        if len(colunas) == 1 and ";" in colunas[0]:
            uploaded_file.seek(0)
            try:
                arquivo_df = pd.read_csv(uploaded_file, sep=";")
                colunas = [str(c).strip() for c in arquivo_df.columns]
            except Exception:
                pass

        if colunas == ["date", "title", "amount"]:
            tipo = "Fatura Nubank"
            df_tratado = tratar_fatura_nubank(arquivo_df)
        elif colunas == ["Data", "Valor", "Identificador", "Descrição"]:
            tipo = "Extrato Nubank"
            df_tratado = tratar_extrato_nubank(arquivo_df)
        elif colunas == ["Data", "Lançamento", "Categoria", "Tipo", "Valor"]:
            tipo = "Fatura Inter"
            df_tratado = tratar_fatura_inter(arquivo_df)
        elif colunas == ["Data Lançamento", "Descrição", "Valor", "Saldo"]:
            tipo = "Extrato Inter"
            df_tratado = tratar_extrato_inter(arquivo_df)
        elif set(["RELEASE_DATE", "TRANSACTION_TYPE", "TRANSACTION_NET_AMOUNT"]).issubset(set(colunas)):
            tipo = "Extrato Mercado Pago"
            df_tratado = tratar_extrato_mercado_pago(arquivo_df)
        elif "SETTLEMENT_DATE" in colunas and "TRANSACTION_DATE" in colunas:
            return (
                None,
                None,
                f"O arquivo '{nome}' é o Relatório de Liquidações (settlement_v2) do Mercado Pago, "
                "que não traz a descrição/destinatário dos Pix. No Mercado Pago, exporte em "
                "'Extratos da Conta' (account_statement) no formato CSV.",
            )
        else:
            return (
                None,
                None,
                f"Formato não reconhecido em '{nome}'. Colunas encontradas: {colunas}",
            )

        return padronizar_colunas_transacoes(df_tratado), tipo, None

    if nome_lower.endswith(".pdf"):
        try:
            import PyPDF2

            uploaded_file.seek(0)
            reader = PyPDF2.PdfReader(uploaded_file)
            texto_total = "\n".join((p.extract_text() or "") for p in reader.pages)

            # 1. Fatura de Cartão de Crédito Mercado Pago PDF
            if "Mercado Pago" in texto_total and (
                "Movimentações na fatura" in texto_total or "Detalhes de consumo" in texto_total
            ):
                df_mp_pdf = _extrair_fatura_mercado_pago_pdf(texto_total, nome)
                if not df_mp_pdf.empty:
                    return padronizar_colunas_transacoes(df_mp_pdf), "Fatura Cartão Mercado Pago PDF", None

            # 2. Fatura Nubank PDF
            df_pdf = _extrair_fatura_nubank_texto_pdf(texto_total, nome)
            if not df_pdf.empty:
                return padronizar_colunas_transacoes(df_pdf), "Fatura Nubank PDF", None

            return None, None, f"Nenhuma transação reconhecida no PDF '{nome}'."
        except Exception as exc:
            return None, None, f"Erro ao processar PDF '{nome}': {exc}"

    return None, None, f"Extensão não suportada em '{nome}'. Envie arquivos .csv ou .pdf."


def _extrair_fatura_mercado_pago_pdf(texto: str, nome_arquivo: str) -> pd.DataFrame:
    """Extrai lançamentos da Fatura de Cartão de Crédito do Mercado Pago em PDF via PyPDF2."""
    import calendar

    # Descobre mês/ano de emissão da fatura pelo texto ("Emitida em: 30/10/2026") ou pelo nome ("2026-10")
    ano_fat = date.today().year
    mes_fat = date.today().month
    m_emit = re.search(r"Emitida em:\s*(\d{2})/(\d{2})/(\d{4})", texto)
    if m_emit:
        mes_fat = int(m_emit.group(2))
        ano_fat = int(m_emit.group(3))
    else:
        m_nome = re.search(r"(20\d{2})[-_](\d{2})", nome_arquivo)
        if m_nome:
            ano_fat = int(m_nome.group(1))
            mes_fat = int(m_nome.group(2))

    # Aceita com ou sem espaço após DD/MM (ex: "30/04OCIMAR HAIR..." ou "11/09 MERCADOLIVRE...")
    padrao_mov = re.compile(r"^(\d{2})/(\d{2})\s*(.+?)\s+(-?\s*R\$\s*[\d\.]*,\d{2})$")
    padrao_parc = re.compile(r"Parcela\s+(\d{1,2})\s+de\s+(\d{1,2})", re.IGNORECASE)

    registros = []
    em_secao_mov = False

    for linha in texto.splitlines():
        s = linha.strip()
        if not s:
            continue
        if "Movimentações na fatura" in s or "Cartão Visa" in s or "Detalhes de consumo" in s:
            em_secao_mov = True
            continue
        if "Parcele a fatura" in s or "Seu cartão de crédito" in s or "Datas importantes" in s:
            em_secao_mov = False
            continue
        if not em_secao_mov:
            continue

        m = padrao_mov.match(s)
        if not m:
            continue
        dia_s, mes_s, desc, val_s = m.groups()
        desc = desc.strip()

        # Ignora pagamentos da fatura anterior
        if desc.lower().startswith("pagamento da fatura"):
            continue

        dia_compra = int(dia_s)
        mes_compra = int(mes_s)
        val_num = abs(parse_valor_brl(val_s))

        eh_credito = (
            val_s.strip().startswith("-")
            or desc.lower().startswith("crédito concedido")
            or desc.lower().startswith("credito concedido")
            or desc.lower().startswith("estorno")
        )
        valor_final = val_num if eh_credito else -val_num

        m_p = padrao_parc.search(desc)
        obs = ""
        if m_p:
            p_atual, p_total = int(m_p.group(1)), int(m_p.group(2))
            obs = f"Parcela {p_atual}/{p_total}"
            # Para parcelas k >= 2 (ou compras de meses anteriores), aloca no mês de competência da fatura
            if p_atual >= 2 or (mes_compra != mes_fat and not (mes_compra == 12 and mes_fat == 1)):
                max_d = calendar.monthrange(ano_fat, mes_fat)[1]
                dt_tx = date(ano_fat, mes_fat, min(dia_compra, max_d))
            else:
                ano_c = ano_fat - 1 if (mes_compra == 12 and mes_fat == 1) else ano_fat
                max_d = calendar.monthrange(ano_c, mes_compra)[1]
                dt_tx = date(ano_c, mes_compra, min(dia_compra, max_d))
        else:
            ano_c = ano_fat - 1 if (mes_compra == 12 and mes_fat == 1) else ano_fat
            max_d = calendar.monthrange(ano_c, mes_compra)[1]
            dt_tx = date(ano_c, mes_compra, min(dia_compra, max_d))

        registros.append(
            {
                "Data": dt_tx,
                "Descrição": desc,
                "Valor": round(valor_final, 2),
                "Fonte": "Crédito",
                "Conta": "Mercado Pago",
                "Tipo Transação": obs or "Compra à vista",
            }
        )

    return pd.DataFrame(registros)


def _extrair_fatura_nubank_texto_pdf(texto: str, nome_arquivo: str) -> pd.DataFrame:
    """Extrai lançamentos de fatura Nubank em PDF usando regex em Python puro (PyPDF2)."""
    meses = {
        "JAN": "01", "FEV": "02", "MAR": "03", "ABR": "04", "MAI": "05", "JUN": "06",
        "JUL": "07", "AGO": "08", "SET": "09", "OUT": "10", "NOV": "11", "DEZ": "12",
    }
    m_ano = re.search(r"(\d{4})", nome_arquivo)
    ano = m_ano.group(1) if m_ano else str(date.today().year)
    padrao_linha = re.compile(
        r"^(\d{2})\s+(JAN|FEV|MAR|ABR|MAI|JUN|JUL|AGO|SET|OUT|NOV|DEZ)\s+(.+?)\s+(-?\s*(?:R\$\s*)?\d[\d\.]*,\d{2})$"
    )
    registros = []
    for linha in texto.splitlines():
        s = linha.strip()
        m = padrao_linha.match(s)
        if not m:
            continue
        dia, mes_abrev, desc, val_str = m.groups()
        if desc.startswith("Pagamento em ") or "Saldo restante" in desc:
            continue
        dt_str = f"{ano}-{meses[mes_abrev]}-{dia}"
        val = parse_valor_brl(val_str)
        registros.append(
            {
                "Data": dt_str,
                "Descrição": desc.strip(),
                "Valor": -abs(val),
                "Fonte": "Crédito",
                "Conta": "Nubank",
            }
        )
    return pd.DataFrame(registros)


# ==================== CLASSIFICAÇÃO HÍBRIDA ====================


def construir_mapa_historico(df_existente: pd.DataFrame) -> dict[str, str]:
    """Aprende a categoria mais frequente por estabelecimento a partir do histórico da planilha."""
    if df_existente is None or df_existente.empty:
        return {}
    if "Descrição" not in df_existente.columns or "Categoria" not in df_existente.columns:
        return {}

    contagens: dict[str, Counter] = {}
    for _, row in df_existente[["Descrição", "Categoria"]].dropna().iterrows():
        cat = str(row["Categoria"]).strip()
        if not cat or cat in ("A Revisar", "Erro", "nan"):
            continue
        chave = chave_estabelecimento(row["Descrição"])
        if not chave:
            continue
        contagens.setdefault(chave, Counter())[cat] += 1

    return {chave: counter.most_common(1)[0][0] for chave, counter in contagens.items()}


def sugerir_categoria_por_historico(descricao: str, mapa_historico: dict[str, str]) -> str | None:
    """Sugere categoria para uma descrição usando match exato ou parcial no mapa histórico."""
    chave = chave_estabelecimento(descricao)
    if not chave:
        return None
    if chave in mapa_historico:
        return mapa_historico[chave]

    # Fallback parcial para chaves suficientemente específicas
    if len(chave) >= 5:
        for hist_chave, cat in mapa_historico.items():
            if len(hist_chave) >= 5 and (chave in hist_chave or hist_chave in chave):
                return cat
    return None


def _validar_categoria(categoria: str, valor: float) -> str:
    cat = str(categoria or "").strip().strip(".")
    permitidas = CATEGORIAS_ENTRADA if valor > 0 else CATEGORIAS_SAIDA
    mapa_lower = {c.lower(): c for c in permitidas}
    if cat.lower() in mapa_lower:
        return mapa_lower[cat.lower()]
    # Tenta match parcial
    for lower_c, original in mapa_lower.items():
        if lower_c in cat.lower() or cat.lower() in lower_c:
            return original
    return "Outras Entradas" if valor > 0 else "Outras Saídas"


def _chamar_groq_em_lote(
    itens: list[dict[str, Any]],
    groq_api_key: str,
    model_name: str = "llama-3.1-8b-instant",
) -> dict[int, str]:
    """Classifica um lote de transações em 1 única chamada à API do Groq."""
    from langchain_openai import ChatOpenAI

    llm = ChatOpenAI(
        model=model_name,
        openai_api_key=groq_api_key,
        base_url="https://api.groq.com/openai/v1",
        temperature=0,
    )

    prompt = (
        "Você é um assistente financeiro brasileiro especialista em categorizar extratos e faturas.\n"
        f"Para valores POSITIVOS (> 0), use EXCLUSIVAMENTE uma destas categorias: {', '.join(CATEGORIAS_ENTRADA)}.\n"
        f"Para valores NEGATIVOS (< 0), use EXCLUSIVAMENTE uma destas categorias: {', '.join(CATEGORIAS_SAIDA)}.\n"
        "Use 'Transferência Interna' se parecer claramente transferência entre contas do próprio titular.\n"
        "Responda SOMENTE com um objeto JSON válido mapeando o 'id' (como string) para a categoria exata, "
        "sem markdown e sem explicações. Exemplo: {\"0\": \"Alimentação\", \"1\": \"Transporte\"}.\n\n"
        f"Transações:\n{json.dumps(itens, ensure_ascii=False)}"
    )

    resposta = llm.invoke(prompt).content.strip()
    # Extrai bloco JSON caso o modelo envolva em ```json ... ```
    match_json = re.search(r"\{[\s\S]*\}", resposta)
    if not match_json:
        return {}

    parsed = json.loads(match_json.group(0))
    resultado: dict[int, str] = {}
    for k, v in parsed.items():
        try:
            resultado[int(k)] = str(v).strip()
        except (ValueError, TypeError):
            continue
    return resultado


def classificar_hibrido(
    df_novo: pd.DataFrame,
    df_existente: pd.DataFrame | None = None,
    groq_api_key: str | None = None,
    batch_size: int = 25,
) -> tuple[pd.DataFrame, dict[str, int]]:
    """Classifica transações usando histórico local primeiro e Groq em lote só para novidades."""
    df_res = df_novo.copy().reset_index(drop=True)
    mapa_historico = construir_mapa_historico(df_existente) if df_existente is not None else {}

    stats = {"historico": 0, "ia": 0, "pendente": 0}
    origem_classificacao = []
    indices_para_ia = []

    for idx, row in df_res.iterrows():
        cat_atual = str(row.get("Categoria", "") or "").strip()
        valor = float(row.get("Valor", 0.0) or 0.0)

        # 1. Histórico local (mais confiável pois reflete o hábito do usuário)
        cat_hist = sugerir_categoria_por_historico(row.get("Descrição", ""), mapa_historico)
        if cat_hist:
            df_res.at[idx, "Categoria"] = _validar_categoria(cat_hist, valor)
            origem_classificacao.append("Histórico")
            stats["historico"] += 1
        elif cat_atual and cat_atual in TODAS_CATEGORIAS and cat_atual != "A Revisar":
            df_res.at[idx, "Categoria"] = _validar_categoria(cat_atual, valor)
            origem_classificacao.append("Extrato")
            stats["historico"] += 1
        else:
            origem_classificacao.append("IA")
            indices_para_ia.append(idx)

    # 2. IA em lote (apenas para novidades)
    if indices_para_ia:
        if groq_api_key:
            for inicio in range(0, len(indices_para_ia), batch_size):
                lote_idxs = indices_para_ia[inicio : inicio + batch_size]
                itens = [
                    {
                        "id": int(i),
                        "descricao": str(df_res.at[i, "Descrição"]),
                        "valor": float(df_res.at[i, "Valor"]),
                        "dia": str(df_res.at[i, "Dia da Semana"]),
                        "fonte": str(df_res.at[i, "Fonte"]),
                    }
                    for i in lote_idxs
                ]
                try:
                    mapa_ia = _chamar_groq_em_lote(itens, groq_api_key)
                except Exception:
                    mapa_ia = {}

                for i in lote_idxs:
                    if i in mapa_ia:
                        df_res.at[i, "Categoria"] = _validar_categoria(
                            mapa_ia[i], float(df_res.at[i, "Valor"])
                        )
                        stats["ia"] += 1
                    else:
                        df_res.at[i, "Categoria"] = "A Revisar"
                        origem_classificacao[i] = "A Revisar"
                        stats["pendente"] += 1
        else:
            for i in indices_para_ia:
                df_res.at[i, "Categoria"] = "A Revisar"
                origem_classificacao[i] = "A Revisar"
                stats["pendente"] += 1

    df_res["_OrigemClassif"] = origem_classificacao
    return df_res, stats


# ==================== DEDUPLICAÇÃO E CONCILIAÇÃO ====================


def eh_lancamento_iphone_ou_manual(row: pd.Series) -> bool:
    """Identifica se um registro da planilha veio do iPhone ou lançamento manual."""
    tipo = str(row.get("Tipo Transação", "") or "").lower()
    fonte = str(row.get("Fonte", "") or "").lower()
    origem = str(row.get("Origem", "") or "").lower()
    combinado = f"{tipo} {fonte} {origem}"
    return any(tok in combinado for tok in ("iphone", "apple pay", "atalho", "manual"))


def detectar_duplicatas_e_conciliacao(
    df_novo: pd.DataFrame,
    df_existente: pd.DataFrame | None,
    janela_dias_match: int = 2,
) -> pd.DataFrame:
    """Analisa transações novas contra a base existente e entre si, marcando:
    - 🆕 Nova (Incluir = True)
    - 🔁 Duplicata exata (Incluir = False)
    - 📱 Match iPhone/Manual (Incluir = False, guarda índice da linha para substituição opcional)
    - ⚠️ Possível duplicata (Incluir = False)
    """
    df_out = df_novo.copy().reset_index(drop=True)
    df_out["Incluir"] = True
    df_out["Status"] = "🆕 Nova"
    df_out["Match Existente"] = ""
    df_out["_match_sig"] = ""

    # Preparar base existente com assinatura estável (imune a deslocamento de índices)
    existentes_norm: list[dict[str, Any]] = []
    if df_existente is not None and not df_existente.empty:
        df_ex = df_existente.copy()
        datas_ex = pd.to_datetime(df_ex["Data"], errors="coerce").dt.date
        valores_ex = df_ex["Valor"].apply(parse_valor_brl).round(2)

        for orig_idx, row in df_ex.iterrows():
            d_ex = datas_ex.loc[orig_idx]
            if pd.isna(d_ex):
                continue
            v_ex = float(valores_ex.loc[orig_idx])
            desc_norm_ex = normalizar_descricao(row.get("Descrição", ""))
            existentes_norm.append(
                {
                    "idx": orig_idx,
                    "data": d_ex,
                    "valor": v_ex,
                    "desc_raw": str(row.get("Descrição", "") or ""),
                    "desc_norm": desc_norm_ex,
                    "sig": f"{d_ex}|{v_ex:.2f}|{desc_norm_ex}",
                    "conta": str(row.get("Conta", "") or ""),
                    "is_manual": eh_lancamento_iphone_ou_manual(row),
                }
            )

    # Índices já usados para match aproximado (evita casar 2 compras iguais com 1 único registro)
    matches_consumidos: set[Any] = set()
    chaves_lote_vistas: set[tuple[str, float, str]] = set()

    for i, row in df_out.iterrows():
        d_novo = pd.to_datetime(row["Data"], errors="coerce")
        if pd.isna(d_novo):
            continue
        d_novo_date: date = d_novo.date()
        v_novo = round(float(row["Valor"]), 2)
        desc_novo_norm = normalizar_descricao(row["Descrição"])
        chave_lote = (str(d_novo_date), v_novo, desc_novo_norm)

        # 1. Duplicata dentro do próprio lote enviado (ex: subiu o mesmo arquivo 2x)
        if chave_lote in chaves_lote_vistas:
            df_out.at[i, "Incluir"] = False
            df_out.at[i, "Status"] = "🔁 Duplicata no lote"
            df_out.at[i, "Match Existente"] = "Repetida em outro arquivo deste envio"
            continue
        chaves_lote_vistas.add(chave_lote)

        # 2. Duplicata exata na planilha existente (mesma data + mesmo valor + mesma descrição)
        match_exato = None
        for ex in existentes_norm:
            if (
                ex["data"] == d_novo_date
                and abs(ex["valor"] - v_novo) < 0.01
                and ex["desc_norm"] == desc_novo_norm
            ):
                match_exato = ex
                break

        if match_exato is not None:
            df_out.at[i, "Incluir"] = False
            df_out.at[i, "Status"] = "🔁 Duplicata exata"
            df_out.at[i, "Match Existente"] = (
                f"{match_exato['data']} | {match_exato['desc_raw']} | R$ {match_exato['valor']:.2f}"
            )
            df_out.at[i, "_match_sig"] = match_exato["sig"]
            continue

        # 3. Match aproximado: mesmo valor em janela de ±2 dias (conciliação com iPhone / fatura)
        melhor_match = None
        menor_diff = janela_dias_match + 1
        for ex in existentes_norm:
            if ex["idx"] in matches_consumidos:
                continue
            if abs(ex["valor"] - v_novo) >= 0.01:
                continue
            diff_dias = abs((ex["data"] - d_novo_date).days)
            if diff_dias <= janela_dias_match:
                # Prioriza match com lançamento do iPhone/manual e menor diferença de dias
                if melhor_match is None or (
                    (ex["is_manual"] and not melhor_match["is_manual"])
                    or (ex["is_manual"] == melhor_match["is_manual"] and diff_dias < menor_diff)
                ):
                    melhor_match = ex
                    menor_diff = diff_dias

        if melhor_match is not None:
            matches_consumidos.add(melhor_match["idx"])
            df_out.at[i, "Incluir"] = False
            tag = "iPhone/Manual" if melhor_match["is_manual"] else "Planilha"
            df_out.at[i, "Status"] = (
                "📱 Match iPhone/Manual" if melhor_match["is_manual"] else "⚠️ Possível duplicata"
            )
            df_out.at[i, "Match Existente"] = (
                f"[{tag}] {melhor_match['data']} | {melhor_match['desc_raw']} | R$ {melhor_match['valor']:.2f}"
            )
            df_out.at[i, "_match_sig"] = melhor_match["sig"]

    return df_out


def montar_assinatura_linha(row: pd.Series) -> str:
    """Gera assinatura estável (data|valor|descricao_norm) para localizar uma linha com segurança."""
    dt = pd.to_datetime(row.get("Data"), errors="coerce")
    d_str = str(dt.date()) if pd.notna(dt) else ""
    v_val = round(parse_valor_brl(row.get("Valor", 0.0)), 2)
    desc_norm = normalizar_descricao(row.get("Descrição", ""))
    return f"{d_str}|{v_val:.2f}|{desc_norm}"


def montar_transacao_manual(
    data_tx: date,
    descricao: str,
    valor_positivo: float,
    eh_receita: bool,
    categoria: str,
    conta: str,
    fonte: str,
) -> pd.DataFrame:
    """Cria DataFrame de 1 linha no schema exato da aba `df`."""
    valor_final = abs(float(valor_positivo)) if eh_receita else -abs(float(valor_positivo))
    dt = pd.to_datetime(data_tx)
    registro = {
        "Data": dt.date(),
        "Descrição": descricao.strip(),
        "Valor": round(valor_final, 2),
        "Categoria": categoria,
        "Fonte": fonte,
        "Conta": conta,
        "Dia da Semana": DIAS_SEMANA_MAP.get(dt.day_name(), ""),
        "Ano/Mês": dt.strftime("%Y-%m"),
        "Tipo Transação": "Manual (App)",
    }
    return pd.DataFrame([registro])


def consolidar_para_salvar(
    df_existente: pd.DataFrame,
    df_novas: pd.DataFrame,
    assinaturas_remover: list[str] | None = None,
) -> pd.DataFrame:
    """Combina base existente + novas transações, removendo matches substituídos por assinatura,
    preservando colunas da planilha e ordenando pela data mais recente.
    """
    colunas_internas = {
        "Incluir",
        "Status",
        "Match Existente",
        "_match_sig",
        "_OrigemClassif",
        "Arquivo",
    }
    df_limpo_novo = df_novas[[c for c in df_novas.columns if c not in colunas_internas]].copy()

    df_base = df_existente.copy() if df_existente is not None else pd.DataFrame()
    if assinaturas_remover and not df_base.empty:
        pendentes_remocao = Counter(s for s in assinaturas_remover if s)
        manter_mask = []
        for _, row in df_base.iterrows():
            sig = montar_assinatura_linha(row)
            if pendentes_remocao.get(sig, 0) > 0:
                pendentes_remocao[sig] -= 1
                manter_mask.append(False)
            else:
                manter_mask.append(True)
        df_base = df_base[manter_mask]

    if df_base.empty:
        df_final = df_limpo_novo
    else:
        df_final = pd.concat([df_base, df_limpo_novo], ignore_index=True)

    dt = pd.to_datetime(df_final["Data"], errors="coerce")
    df_final["Ano/Mês"] = dt.dt.strftime("%Y-%m")
    df_final["Data"] = dt.dt.strftime("%Y-%m-%d")
    df_final["Valor"] = df_final["Valor"].apply(parse_valor_brl).round(2)
    df_final = df_final.sort_values(by=["Data", "Descrição"], ascending=[False, True]).reset_index(drop=True)
    return df_final
