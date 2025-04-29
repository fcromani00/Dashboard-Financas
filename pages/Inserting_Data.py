import streamlit as st
import pandas as pd
import os
import tabula
from tqdm import tqdm
from streamlit_gsheets import GSheetsConnection
from functions import tratar_fatura_nubank, tratar_extrato_nubank, tratar_fatura_nubank_pdf, tratar_fatura_inter, tratar_extrato_inter, classificar_transacao, classificar_dataframe
from langchain_openai import ChatOpenAI
from langchain_core.prompts import PromptTemplate
from dotenv import load_dotenv

# Carregar variáveis de ambiente
load_dotenv()

# Configuração do LLM do GROQ
groq_api_key = os.getenv("GROQ_API_KEY")
llm = ChatOpenAI(
    model="llama-3.1-8b-instant",
    openai_api_key=groq_api_key,
    base_url="https://api.groq.com/openai/v1",
)

# Template do prompt
prompt_template = """Você é um assistente especializado em classificar transações financeiras em categorias predefinidas.

Quando o valor for positivo, as categorias possíveis para a transação são:
- Salário
- Renda
- Rendimento
- Cashback
- Estorno
- Bônus
- Outras Entradas

Quando o valor for negativo, as categorias possíveis para a transação são:

- Alimentação
- Restaurante
- Bares
- Academia
- Barbearia
- Compras
- Lazer
- Educação
- Investimentos
- Imposto, Juros e Multa
- Presente
- Doação
- Moradia
- Transporte
- Vestuário
- Viagem
- Outras Saídas

A transação recebida é: "{descricao}" no valor de R$ {valor}, realizada em {data} sendo uma {dia_da_semana}, e aparece no {fonte}.
Retorne apenas a palavra da categoria mais apropriada dentre as apresentadas anteriormente, sem explicações adicionais.
"""

prompt = PromptTemplate.from_template(prompt_template)
model = prompt | llm

###########################################################
st.title('Inserir Extrato/Fatura')
st.write('Essa página é usada para inserir extratos e faturas')
st.write('---')

tipo_arquivo = None
uploaded_file = st.file_uploader("Escolha um arquivo")

if uploaded_file is not None:
    file_key = uploaded_file.name

    if file_key not in st.session_state:
        if uploaded_file.name.endswith('.csv'):
            try:
                arquivo_df = pd.read_csv(uploaded_file)
            except pd.errors.ParserError:
                uploaded_file.seek(0)
                arquivo_df = pd.read_csv(uploaded_file, header=4, sep=";")
            except Exception as e:
                st.error(f"Erro ao ler o arquivo: {e}")
                st.stop()

            colunas = list(arquivo_df.columns)

            if colunas == ['date', 'title', 'amount']:
                st.warning("Arquivo identificado como **Fatura Nubank**")
                tipo_arquivo = 'Fatura Nubank'
            elif colunas == ['Data', 'Valor', 'Identificador', 'Descrição']:
                st.warning("Arquivo identificado como **Extrato Nubank**")
                tipo_arquivo = 'Extrato Nubank'
            elif colunas == ['Data', 'Lançamento', 'Categoria', 'Tipo', 'Valor']:
                st.warning("Arquivo identificado como **Fatura Inter**")
                tipo_arquivo = "Fatura Inter"
            elif colunas == ["Data Lançamento", "Descrição", 'Valor', "Saldo"]:
                st.warning("Arquivo identificado como **Extrato Inter**")
                tipo_arquivo = "Extrato Inter"
        elif uploaded_file.name.endswith(".pdf"):
            st.warning("Arquivo identificado como **Fatura Nubank PDF**")
            tipo_arquivo = 'Fatura Nubank PDF'
            lista_tabelas = tabula.read_pdf(uploaded_file, pages='all')
        else:
            st.warning("Formato de arquivo não reconhecido. Verifique as colunas.")

        # Processamento
        if tipo_arquivo == 'Fatura Nubank':
            arquivo_df = tratar_fatura_nubank(arquivo_df)
        elif tipo_arquivo == 'Extrato Nubank':
            arquivo_df = tratar_extrato_nubank(arquivo_df)
        elif tipo_arquivo == 'Fatura Nubank PDF':
            arquivo_df = tratar_fatura_nubank_pdf(lista_tabelas[-1], uploaded_file.name)
        elif tipo_arquivo == "Fatura Inter":
            arquivo_df = tratar_fatura_inter(arquivo_df)
        elif tipo_arquivo == "Extrato Inter":
            arquivo_df = tratar_extrato_inter(arquivo_df)

        # Adicionar classificação automática apenas se não existir
        with st.spinner("Inteligência Artificial está classificando as suas transações... 🤖🔍✨"):
            arquivo_df['Dia da Semana'] = pd.to_datetime(arquivo_df['Data']).dt.day_name().replace({
    'Monday': 'Segunda', 'Tuesday': 'Terça', 'Wednesday': 'Quarta',
    'Thursday': 'Quinta', 'Friday': 'Sexta', 'Saturday': 'Sábado', 'Sunday': 'Domingo'
})
            arquivo_df = classificar_dataframe(model, arquivo_df)

        # Armazenar no session_state
        st.session_state[file_key] = arquivo_df
    else:
        # Se o arquivo já foi carregado antes, recuperamos do session_state
        arquivo_df = st.session_state[file_key]

    arquivo_df = st.data_editor(arquivo_df, disabled=arquivo_df.columns.difference(["Categoria", "Descrição"]).tolist(), hide_index=True)


    if st.button("Inserir dados"):
        conn = st.connection("gsheets", type=GSheetsConnection)
        df = conn.read(worksheet="df")

        df = pd.concat([df, arquivo_df], ignore_index=True).sort_values(by=['Data', 'Descrição'], ascending=True)
        df['Ano/Mês'] = df['Data'].astype(str).str[:7]
        df['Data'] = pd.to_datetime(df['Data']).dt.date
        
        conn.update(worksheet="df", data=df)
        st.success(f'{tipo_arquivo} {uploaded_file.name} inserido com sucesso!')
        st.toast(f'✅🧾{tipo_arquivo} inserido com sucesso! \n​{uploaded_file.name}')
        st.cache_data.clear()