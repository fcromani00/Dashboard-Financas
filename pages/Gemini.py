"""Consultor Financeiro IA (Finanças V2 — Fase 4).

Unifica os assistentes antigos em um único consultor rápido que:
- Lê diretamente das abas V2 (`transacoes`, `orcamento`, `metas`, `ativos`, `operacoes`) sem depender da Home;
- Monta e faz cache do contexto financeiro completo (Gastos + Orçamento + Carteira de Investimentos);
- Não reconstrói embeddings a cada mensagem enviada.
"""

from __future__ import annotations

import pandas as pd
import streamlit as st
from langchain_google_genai import ChatGoogleGenerativeAI

from core.portfolio import calcular_posicoes
from core.recurring import analisar_parcelas, detectar_recorrencias
from core.state import ler_aba, obter_gemini_key

st.title("🤖 Consultor Financeiro Pessoal (V2)")
st.caption("Enxerga seus gastos, orçamento, reserva de emergência e carteira de investimentos.")


def montar_contexto_v2() -> str:
    df_tx = ler_aba("transacoes")
    df_orc = ler_aba("orcamento")
    df_metas = ler_aba("metas")
    df_ativos = ler_aba("ativos")
    df_ops = ler_aba("operacoes")

    op = df_tx[(df_tx["transferencia"] != "S") & (df_tx["categoria"] != "Transferência Interna")].copy()
    op["ano_mes"] = op["data"].apply(lambda d: d.strftime("%Y-%m") if pd.notna(d) else "")

    rec_m = op[op["valor"] > 0].groupby("ano_mes")["valor"].sum()
    desp_m = op[op["valor"] < 0].groupby("ano_mes")["valor"].sum().abs()
    cat_desp = op[op["valor"] < 0].groupby("categoria")["valor"].sum().abs().sort_values(ascending=False)

    linhas = ["# Contexto Financeiro Completo do Usuário (V2)\n"]
    linhas.append("## 1. Evolução Mensal (Receitas vs. Despesas)")
    for m in sorted(set(rec_m.index) | set(desp_m.index))[-12:]:
        r = float(rec_m.get(m, 0.0))
        d = float(desp_m.get(m, 0.0))
        linhas.append(f"- **{m}**: Receitas R$ {r:,.2f} | Despesas R$ {d:,.2f} | Saldo R$ {r - d:,.2f}")

    linhas.append("\n## 2. Principais Categorias de Despesa (Histórico)")
    for cat, val in cat_desp.head(15).items():
        linhas.append(f"- **{cat}**: R$ {float(val):,.2f}")

    if not df_orc.empty:
        linhas.append("\n## 3. Orçamento Mensal Planejado")
        for _, r in df_orc.iterrows():
            linhas.append(f"- **{r['categoria']}** ({r['grupo']}): R$ {float(r['valor'] or 0):,.2f}")

    if not df_metas.empty:
        linhas.append("\n## 4. Metas e Reserva de Emergência")
        for _, m in df_metas.iterrows():
            linhas.append(
                f"- **{m['nome']}**: Atual R$ {float(m['valor_atual'] or 0):,.2f} / Alvo R$ {float(m['valor_alvo'] or 0):,.2f}"
            )

    pos = calcular_posicoes(df_ativos, df_ops)
    if not pos.empty:
        abertas = pos[(pos["quantidade"] > 1e-7) | (pos["valor_rf_base"] > 0.01)]
        linhas.append(f"\n## 5. Carteira de Investimentos ({len(abertas)} posições abertas)")
        for _, p in abertas.head(30).iterrows():
            if p["classe"] == "renda_fixa":
                linhas.append(f"- **{p['nome']}** ({p['conta']}): Saldo R$ {p['valor_rf_base']:,.2f}")
            else:
                linhas.append(
                    f"- **{p['ticker']}** ({p['classe']}, {p['moeda']}): Qtd {p['quantidade']:.4f} | PM {p['preco_medio']:.2f} | Custo {p['custo_total']:,.2f}"
                )

    rec = detectar_recorrencias(op)
    parc = analisar_parcelas(op)
    linhas.append(
        f"\n## 6. Custos Fixos, Assinaturas e Parcelas\n"
        f"- **Custos fixos/assinaturas ativas**: R$ {rec['total_fixos_ativos_mes']:,.2f}/mês ({rec['qtd_fixos_ativos']} itens)\n"
        f"- **Saldo total de parcelas futuras a vencer**: R$ {parc['total_futuro']:,.2f}"
    )

    return "\n".join(linhas)


api_key = obter_gemini_key()
if not api_key:
    st.error("Chave do Gemini não encontrada em `.streamlit/secrets.toml` ou `.env`.")
    st.stop()

if "v2_contexto_ia" not in st.session_state or st.button("🔄 Atualizar contexto financeiro"):
    with st.spinner("Consolidando dados das abas V2..."):
        st.session_state["v2_contexto_ia"] = montar_contexto_v2()

if "v2_chat_messages" not in st.session_state:
    st.session_state["v2_chat_messages"] = []

with st.expander("📄 Ver resumo financeiro enviado ao Consultor", expanded=False):
    st.markdown(st.session_state["v2_contexto_ia"])

for msg in st.session_state["v2_chat_messages"]:
    with st.chat_message(msg["role"]):
        st.markdown(msg["content"])

pergunta = st.chat_input("Pergunte sobre seus gastos, orçamento ou investimentos...")
if pergunta:
    st.session_state["v2_chat_messages"].append({"role": "user", "content": pergunta})
    with st.chat_message("user"):
        st.markdown(pergunta)

    with st.chat_message("assistant"):
        with st.spinner("Analisando..."):
            llm = ChatGoogleGenerativeAI(model="gemini-2.5-flash", google_api_key=api_key, temperature=0.2)
            historico_txt = "\n".join(
                f"{m['role']}: {m['content']}" for m in st.session_state["v2_chat_messages"][-6:]
            )
            prompt_completo = (
                "Você é o consultor financeiro pessoal do Felipe. Responda em português de forma direta, "
                "prática e baseada nos números reais abaixo.\n\n"
                f"{st.session_state['v2_contexto_ia']}\n\n"
                f"Histórico recente:\n{historico_txt}\n\n"
                f"Pergunta atual: {pergunta}"
            )
            resposta = llm.invoke(prompt_completo).content
            st.markdown(resposta)
            st.session_state["v2_chat_messages"].append({"role": "assistant", "content": resposta})
