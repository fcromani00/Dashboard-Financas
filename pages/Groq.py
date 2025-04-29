import streamlit as st
from langchain_core.prompts import PromptTemplate
from langchain_openai import ChatOpenAI  # ChatOpenAI suporta GROQ!
from dotenv import load_dotenv
import os

# Carregar variáveis de ambiente
load_dotenv()

# Configuração da API GROQ
groq_api_key = os.getenv("GROQ_API_KEY")  # Defina isso no seu .env
llm = ChatOpenAI(
    model="llama-3.3-70b-versatile",  # Modelo da GROQ (outros: llama3-8b, gemma-7b)
    openai_api_key=groq_api_key,  # Usa a chave da API GROQ
    base_url="https://api.groq.com/openai/v1",  # URL da API GROQ
)

# Template de Prompt melhorado
prompt_template = """Você é um assistente especializado em classificar transações financeiras em categorias predefinidas.
Categorias disponíveis:
- Alimentação, Animais de Estimação, Bares, Câmbio, Cashback, Compras, Construção, Contas, Cultura, Delivery Inter, Doações e Caridade, Drogaria, Educação, Ensino, Entretenimento, Esportes, Estacionamento, Gift Card, Hospedagem, Imposto/Juros/Multa, Inter, Inter Shop, Investimento, Lazer, Livrarias, Mercado, Moradia, Outras Saídas, Outros, Pagamentos, Pet Shop, Presente, Recarga, Restaurantes, Saúde, Seguros, Serviços, Supermercado, Transporte, Vestuário, Viagem, Bônus, Estorno, Outras Entradas, Renda, Rendimento, Vendas.

A transação recebida é: "{input}"
Retorne apenas a categoria mais apropriada e uma breve justificativa.
Se for questionado qual modelo de LLM está sendo usado, também responda.
"""

prompt = PromptTemplate.from_template(prompt_template)
model = prompt | llm  # Conecta o template ao LLM

# Interface do Streamlit
st.title("Classificador de Transações Financeiras 💰")

# Histórico de mensagens
if "messages" not in st.session_state:
    st.session_state.messages = []

for msg in st.session_state.messages:
    with st.chat_message(msg["role"]):
        st.write(msg["content"])

entrada = st.chat_input("Digite a descrição da transação...")

if entrada:
    # Adiciona entrada do usuário ao histórico
    st.session_state.messages.append({"role": "user", "content": entrada})
    with st.chat_message("user"):
        st.write(entrada)

    # Obtém resposta do modelo
    resposta = model.invoke({'input': entrada}).content

    # Adiciona resposta do assistente ao histórico
    st.session_state.messages.append({"role": "assistant", "content": resposta})
    with st.chat_message("assistant"):
        st.write(resposta)
