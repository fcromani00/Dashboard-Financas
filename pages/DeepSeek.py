import streamlit as st
from streamlit_gsheets import GSheetsConnection
import requests
import json
from dotenv import load_dotenv
import os

conn = st.connection("gsheets", type=GSheetsConnection)
df = conn.read(worksheet="df")

load_dotenv()
API_KEY = os.getenv("OPENROUTER_API_KEY")

# Verificar se a chave da API foi carregada
if not API_KEY:
    st.error("API Key do OpenRouter não encontrada. Defina no .env como OPENROUTER_API_KEY.")
    st.stop()


# Função para consultar a API do OpenRouter usando o DeepSeek
def get_llm_response(transaction_description, df):
    url = "https://openrouter.ai/api/v1/chat/completions"

    headers = {
        "Authorization": f"Bearer {API_KEY}",
        "Content-Type": "application/json",
    }

    # Extraindo métricas do DataFrame
    saldo_atual = round(df["Valor"].sum(), 2)
    receita_mensal = round(df[df["Valor"] > 0]["Valor"].sum(), 2)
    gastos_mensal = round(df[df["Valor"] < 0]["Valor"].sum(), 2)
    
    categorias_mais_gastas = df.groupby("Categoria")["Valor"].sum().sort_values(ascending=True)
    categorias_top3 = ", ".join([f"{cat} (R$ {abs(valor)})" for cat, valor in categorias_mais_gastas.items()])

    # Criando o prompt com dados financeiros
    prompt = f"""
    Você é um assistente financeiro que ajuda a pessoa a tomar melhores decisões financeiras.

    Aqui estão as finanças do usuário:
    - **Saldo atual:** R$ {saldo_atual}
    - **Receitas do mês:** R$ {receita_mensal}
    - **Gastos do mês:** R$ {gastos_mensal}
    - **Principais categorias de gastos:** {categorias_top3}

    Agora, classifique a transação: "{transaction_description}".
    Também dê recomendações sobre como melhorar a situação financeira com base nesses dados.
    """
    if "messages" not in st.session_state:
        st.session_state.messages = [
            {"role": "system", "content": prompt}
        ]

    data = {
        "model": "deepseek/deepseek-chat",
        "messages": [{"role": "system", "content": prompt}]
    }

    response = requests.post(url, headers=headers, data=json.dumps(data))

    if response.status_code == 200:
        result = response.json()
        return result["choices"][0]["message"]["content"]
    else:
        return f"Erro na API: {response.status_code} - {response.text}"


# Interface do Streamlit
st.title("Classificador de Transações Financeiras 💰")

# Histórico de mensagens
if "messages" not in st.session_state:
    st.session_state.messages = []

# Exibir histórico
for msg in st.session_state.messages:
    with st.chat_message(msg["role"]):
        st.write(msg["content"])

entrada = st.chat_input("Pergunte alguma coisa ao seu consultor financeiro")

if entrada:
    # Adiciona entrada do usuário ao histórico
    st.session_state.messages.append({"role": "user", "content": entrada})
    with st.chat_message("user"):
        st.write(entrada)

    # Obter resposta do DeepSeek via OpenRouter
    resposta = get_llm_response(entrada, df)

    # Adiciona resposta ao histórico
    st.session_state.messages.append({"role": "assistant", "content": resposta})
    with st.chat_message("assistant"):
        st.write(resposta)
