"""Consultor Financeiro IA (Finanças V2/V3):
- Tool Calling sob demanda (sem carregar RAG pesado a cada mensagem)
- Acesso ao vivo ao Yahoo Finance (cotações, fundamentos, histórico, comparação e notícias)
- Memória persistente salva na aba `config` do Google Sheets (`ia.memoria_perfil` / `ia.ultimo_resumo`)
"""

from __future__ import annotations

import json

import streamlit as st
from langchain_google_genai import ChatGoogleGenerativeAI

from core.advisor import (
    CHAVE_MEMORIA_PERFIL,
    CHAVE_ULTIMO_RESUMO,
    carregar_memoria_lista,
    criar_ferramentas_consultor,
    executar_turno_consultor,
)
from core.state import invalidar_abas, ler_aba, mapa_config, obter_gemini_key, salvar_config

col_h1, col_h2, col_h3 = st.columns([4.2, 1.4, 1.2])
with col_h1:
    st.title("Consultor Financeiro IA")
    st.caption("Consulta seus dados sob demanda, analisa ativos no Yahoo Finance e lembra das suas preferências.")
with col_h2:
    if st.button("Salvar resumo", icon=":material/bookmark_add:", use_container_width=True, help="Resume a conversa atual e salva na memória"):
        msgs = st.session_state.get("v2_chat_messages", [])
        api_k = obter_gemini_key()
        if msgs and api_k:
            with st.spinner("Salvando resumo na planilha..."):
                llm_res = ChatGoogleGenerativeAI(model="gemini-2.5-flash", google_api_key=api_k, temperature=0.1)
                txt_conv = "\n".join(f"{m['role']}: {m['content']}" for m in msgs[-10:])
                resumo = llm_res.invoke(
                    "Resuma em no máximo 4 frases objetivas as decisões, dúvidas e próximos passos desta conversa "
                    f"financeira para lembrar na próxima sessão:\n\n{txt_conv}"
                ).content
                salvar_config({CHAVE_ULTIMO_RESUMO: str(resumo).strip()})
                invalidar_abas("config")
                st.toast("✅ Resumo salvo na memória!")
with col_h3:
    if st.button("Nova conversa", icon=":material/add_comment:", use_container_width=True):
        st.session_state["v2_chat_messages"] = []
        st.rerun()

api_key = obter_gemini_key()
if not api_key:
    st.error("Chave do Gemini não encontrada em `.streamlit/secrets.toml` ou `.env`.")
    st.stop()

cfg = mapa_config()
fatos_salvos = carregar_memoria_lista(cfg)
ultimo_resumo = str(cfg.get(CHAVE_ULTIMO_RESUMO, "") or "").strip()

with st.expander(f"Memória do Consultor ({len(fatos_salvos)} fato(s) salvo(s))", expanded=False):
    if fatos_salvos:
        for f in fatos_salvos:
            st.markdown(f"- {f}")
    else:
        st.caption("Nenhum fato salvo ainda. Conforme você conversa, o Consultor aprende e salva suas preferências aqui.")

    if ultimo_resumo:
        st.info(f"**Última conversa:** {ultimo_resumo}")

    novo_fato = st.text_input("Adicionar preferência/objetivo manualmente", placeholder="Ex: Quero manter 60% em EUA, 30% RF e 10% BTC")
    cm1, cm2 = st.columns(2)
    with cm1:
        if st.button("Adicionar à memória", use_container_width=True) and novo_fato.strip():
            atualizados = fatos_salvos + [novo_fato.strip()]
            salvar_config({CHAVE_MEMORIA_PERFIL: json.dumps(atualizados, ensure_ascii=False)})
            invalidar_abas("config")
            st.toast("✅ Salvo na memória!")
            st.rerun()
    with cm2:
        if st.button("Limpar memória", use_container_width=True):
            salvar_config({CHAVE_MEMORIA_PERFIL: "[]", CHAVE_ULTIMO_RESUMO: ""})
            invalidar_abas("config")
            st.toast("🗑️ Memória limpa.")
            st.rerun()

if "v2_chat_messages" not in st.session_state:
    st.session_state["v2_chat_messages"] = []

# Sugestões rápidas quando a conversa ainda está vazia
prompt_sugerido = None
if not st.session_state["v2_chat_messages"]:
    s1, s2, s3 = st.columns(3)
    if s1.button("Comparar minhas posições vs VOO (6m)", use_container_width=True):
        prompt_sugerido = "Consulte minha carteira de ações/ETFs EUA e compare as maiores posições com o VOO nos últimos 6 meses no Yahoo Finance."
    if s2.button("Como está meu orçamento do mês?", use_container_width=True):
        prompt_sugerido = "Consulte meu resumo financeiro do mês atual, orçamento e custos fixos/parcelas, e diga onde preciso segurar."
    if s3.button("Checar IOF/IR da Renda Fixa", use_container_width=True):
        prompt_sugerido = "Consulte minha Renda Fixa e me diga quais títulos têm IOF ou prazo de IR para ficar atento."

for msg in st.session_state["v2_chat_messages"]:
    with st.chat_message(msg["role"]):
        st.markdown(msg["content"])

pergunta = st.chat_input("Pergunte sobre seus gastos, carteira ou qualquer ticker no Yahoo Finance...") or prompt_sugerido
if pergunta:
    st.session_state["v2_chat_messages"].append({"role": "user", "content": pergunta})
    with st.chat_message("user"):
        st.markdown(pergunta)

    with st.chat_message("assistant"):
        with st.status("Consultando dados e Yahoo Finance...", expanded=False) as status_box:
            llm = ChatGoogleGenerativeAI(model="gemini-2.5-flash", google_api_key=api_key, temperature=0.2)
            tools = criar_ferramentas_consultor(
                leitor_aba=ler_aba,
                leitor_config=mapa_config,
                gravador_config=lambda d: (salvar_config(d), invalidar_abas("config")),
            )
            resposta, usadas = executar_turno_consultor(
                llm=llm,
                tools=tools,
                cfg=mapa_config(),
                historico_mensagens=st.session_state["v2_chat_messages"][:-1],
                pergunta=pergunta,
            )
            if usadas:
                status_box.update(
                    label=f"Consultado: {', '.join(dict.fromkeys(usadas))}",
                    state="complete",
                )
            else:
                status_box.update(label="Respondido com memória atual", state="complete")

        st.markdown(resposta)
        st.session_state["v2_chat_messages"].append({"role": "assistant", "content": resposta})
