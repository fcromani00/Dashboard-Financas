import streamlit as st
from langchain.chains import ConversationChain
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain.memory import ConversationBufferMemory
from langchain.text_splitter import RecursiveCharacterTextSplitter
from langchain_community.vectorstores import FAISS
from langchain_google_genai import GoogleGenerativeAIEmbeddings
import pandas as pd
import datetime
import re
from collections import Counter
from functions import gerar_relatorio_rag

# Sua função gerar_relatorio_rag() aqui (mantenha exatamente como estava)

# Configuração da Página
st.set_page_config(page_title="Consultor Financeiro", page_icon="💸", layout="wide")
st.title("💸 Consultor Financeiro Pessoal")

# Inicialização dos estados
if "vectorstore" not in st.session_state:
    st.session_state.vectorstore = None
if "memory" not in st.session_state:
    st.session_state.memory = ConversationBufferMemory()
if "conversation" not in st.session_state:
    llm = ChatGoogleGenerativeAI(model="gemini-2.5-pro-exp-03-25", google_api_key=st.secrets["GEMINI"]["api_key"])
    st.session_state.conversation = ConversationChain(llm=llm, memory=st.session_state.memory)
if "messages" not in st.session_state:
    st.session_state.messages = []

# Verifica se existe df_transacoes no session_state
if "df" not in st.session_state:
    st.error("Dados financeiros não encontrados. Por favor, carregue os dados na página principal.")
    st.stop()

# Processa os dados automaticamente
df = st.session_state.df.copy()

# Garante as colunas necessárias
if 'Data' in df.columns:
    df['Data'] = pd.to_datetime(df['Data'])
    df['Ano/Mês'] = df['Data'].dt.strftime('%Y-%m')
    df['Dia da Semana'] = df['Data'].dt.day_name()

# Gera o relatório
with st.spinner("Analisando seus dados financeiros..."):
    relatorio = gerar_relatorio_rag(df)
    
    # Cria o vetorstore com o relatório
    text_splitter = RecursiveCharacterTextSplitter(
        chunk_size=1000,
        chunk_overlap=200
    )
    chunks = text_splitter.split_text(relatorio)
    st.session_state.vectorstore = FAISS.from_texts(chunks, GoogleGenerativeAIEmbeddings(
        model="models/embedding-001", 
        google_api_key=st.secrets["GEMINI"]["api_key"]
    ))

# Layout principal
# col1, col2 = st.columns([1, 2])

# with col1:
#     st.subheader("📊 Resumo Financeiro")
#     st.write(f"**Período:** {df['Data'].min().date()} a {df['Data'].max().date()}")
#     st.write(f"**Total de transações:** {len(df):,}")
#     st.write(f"**Saldo atual:** R$ {df['Valor'].sum():.2f}")
    
#     st.download_button(
#         label="Baixar Relatório Completo",
#         data=relatorio,
#         file_name="relatorio_financeiro.md",
#         mime="text/markdown"
#     )

# with col2:
st.subheader("💬 Consultor Financeiro")

# Área de mensagens com limite de altura e scroll
with st.container():
    messages_container = st.container()
    with messages_container:
        for message in st.session_state.messages:
            with st.chat_message(message["role"]):
                st.markdown(message["content"])

# Input do usuário (sempre no fim)
prompt = st.chat_input("Pergunte sobre suas finanças...")

if prompt:
    # Adiciona a mensagem do usuário
    st.session_state.messages.append({"role": "user", "content": prompt})

    # Exibe mensagem do usuário
    with messages_container:
        with st.chat_message("user"):
            st.markdown(prompt)

    # Resposta do Assistente
    with messages_container:
        with st.chat_message("assistant"):
            with st.spinner("Pensando..."):
                docs = st.session_state.vectorstore.similarity_search(prompt, k=3)
                context = "\n\n".join([doc.page_content for doc in docs])
                response = st.session_state.conversation.run(
                    f"""Você é um consultor financeiro especializado. Use estes dados:
                    {context}
                    
                    Responda de forma clara e prática: {prompt}"""
                )
                st.markdown(response)
                st.session_state.messages.append({"role": "assistant", "content": response})
