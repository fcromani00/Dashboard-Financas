def importar_faturas():
    import os
    import pandas as pd
    pasta_csv = "Faturas/"
    
    lista_dfs = []
    
    for arquivo in os.listdir(pasta_csv):
        if arquivo.endswith(".csv"):
            caminho_arquivo = os.path.join(pasta_csv, arquivo)
    
            ano_mes = arquivo.split("_")[1][:7]
    
            df = pd.read_csv(caminho_arquivo)
    
            df['Ano/Mês'] = ano_mes
            df['Tipo'] = 'Crédito'
    
            lista_dfs.append(df)
    
    df_faturas = pd.concat(lista_dfs, ignore_index=True).sort_values(by='date', ascending=True)
    df_faturas = df_faturas.rename(columns={'date': 'Data', 'amount': 'Valor', 'title': 'Descrição'})
    df_faturas = df_faturas[(df_faturas['Descrição'] != 'Pagamento recebido') & (df_faturas['Descrição'] != 'Saldo restante da fatura anterior')]
    df_faturas['Valor'] = df_faturas['Valor'] * -1
    return df_faturas
#--------------------------------------------------------------------------------------------------
def importar_extratos():
    import pandas as pd
    import os
    pasta_csv = "Extratos/"
    
    lista_dfs = []
    
    for arquivo in os.listdir(pasta_csv):
        if arquivo.endswith(".csv"):
            caminho_arquivo = os.path.join(pasta_csv, arquivo)
    
            ano_mes = arquivo.split("_")[-1][2:9]
    
            df = pd.read_csv(caminho_arquivo)
    
            df['Ano/Mês'] = ano_mes
            df['Tipo'] = 'Extrato'
    
            lista_dfs.append(df)
    
    df_extratos = pd.concat(lista_dfs, ignore_index=True)
    df_extratos = df_extratos[df_extratos['Descrição'] != 'Pagamento fatura']
    df_extratos['Data'] = df_extratos['Data'].str.replace('/', '-')
    df_extratos['Data'] = pd.to_datetime(df_extratos['Data'], format='%d-%m-%Y').dt.date
    df_extratos = df_extratos.sort_values(by='Data', ascending=True)
    return df_extratos
#--------------------------------------------------------------------------------------------------
def tratar_extrato_nubank(arquivo_df):
    import pandas as pd
    df_extrato = arquivo_df[arquivo_df['Descrição'] != 'Pagamento de fatura']
    df_extrato['Data'] = df_extrato['Data'].str.replace('/', '-')
    del df_extrato['Identificador']
    df_extrato['Data'] = pd.to_datetime(df_extrato['Data'], format='%d-%m-%Y')
    df_extrato = df_extrato.sort_values(by='Data', ascending=True)
    df_extrato['Dia da Semana'] = df_extrato['Data'].dt.day_name().replace({
        'Monday': 'Segunda', 'Tuesday': 'Terça', 'Wednesday': 'Quarta',
        'Thursday': 'Quinta', 'Friday': 'Sexta', 'Saturday': 'Sábado', 'Sunday': 'Domingo'
        })
    df_extrato['Data'] = df_extrato['Data'].astype(str)
    df_extrato['Fonte'] = 'Extrato' 
    df_extrato['Conta'] = "Nubank"
    return df_extrato
#--------------------------------------------------------------------------------------------------
def tratar_fatura_nubank(arquivo_df):
    import pandas as pd
    df_fatura = arquivo_df.rename(columns={'date': 'Data', 'amount': 'Valor', 'title': 'Descrição'})
    df_fatura = df_fatura[(df_fatura['Descrição'] != 'Pagamento recebido') & (df_fatura['Descrição'] != 'Saldo restante da fatura anterior')]
    df_fatura['Valor'] = df_fatura['Valor'] * -1
    df_fatura['Fonte'] = 'Crédito'
    df_fatura['Conta'] = "Nubank"
    return df_fatura
#--------------------------------------------------------------------------------------------------
def tratar_fatura_nubank_pdf(arquivo_df,nome_arquivo):
    import pandas as pd
    import re
    df_fatura = arquivo_df.drop(arquivo_df.columns[1], axis=1)
    primeira_linha = pd.DataFrame([df_fatura.columns], columns=["Data", "Descrição", "Valor"])
    df_fatura.columns = ["Data", "Descrição", "Valor"]
    df_fatura = pd.concat([primeira_linha, df_fatura], ignore_index=True)
    df_fatura['Valor'] = df_fatura['Valor'].str.replace(',','.').astype(float)
    df_fatura['Valor'] = df_fatura['Valor'] * -1
    # df_fatura['Valor'] = df_fatura['Valor'].astype(float)
    ano = re.search(r'(\d{4})', nome_arquivo).group(1)
    meses = {"JAN":"01","FEV":"02","MAR":"03","ABR":"04","MAI":"05","JUN":"06",
             "JUL":"07","AGO":"08","SET":"09","OUT":"10","NOV":"11","DEZ":"12"}
    def converter_data(data):
        mes_abrev = data[-3:]
        if mes_abrev in meses:
            return f"{ano}-{meses[mes_abrev]}-{data[:-4].zfill(2)}"
        return data
    df_fatura["Data"] = df_fatura["Data"].apply(converter_data)
    df_fatura['Fonte'] = "Crédito"
    padrao = re.compile(r"Pagamento em \d{2} (" + "|".join(meses.keys()) + r")")
    df_fatura = df_fatura[~df_fatura["Descrição"].str.match(padrao)]
    df_fatura['Data'] = pd.to_datetime(df_fatura['Data'])
    df_fatura['Dia da Semana'] = df_fatura['Data'].dt.day_name().replace({
    'Monday': 'Segunda', 'Tuesday': 'Terça', 'Wednesday': 'Quarta',
    'Thursday': 'Quinta', 'Friday': 'Sexta', 'Saturday': 'Sábado', 'Sunday': 'Domingo'
})
    df_fatura['Data'] = df_fatura['Data'].dt.date
    df_fatura['Conta'] = "Nubank"
    return df_fatura
#--------------------------------------------------------------------------------------------------
def importar_dados():
    import streamlit as st
    from streamlit_gsheets import GSheetsConnection

    conn = st.connection("gsheets", type=GSheetsConnection)
    df = conn.read(worksheet="df")
    return df
#--------------------------------------------------------------------------------------------------
def tratar_fatura_inter(arquivo_df):
    import pandas as pd
    df_fatura = arquivo_df.rename(columns={'Lançamento':"Descrição", "Tipo":"Tipo Transação"})
    df_fatura = df_fatura[df_fatura['Descrição'] != 'Pagamento On Line']
    df_fatura['Valor'] = df_fatura['Valor'].str.replace("R$","").str.replace(",",".")
    df_fatura['Valor'] = df_fatura['Valor'].astype(float)
    df_fatura['Valor'] = df_fatura['Valor'] * -1
    df_fatura['Fonte'] = 'Crédito'
    df_fatura['Data'] = df_fatura['Data'].str.replace('/', '-')
    df_fatura['Data'] = pd.to_datetime(df_fatura['Data'], format='%d-%m-%Y')
    df_fatura['Dia da Semana'] = df_fatura['Data'].dt.day_name().replace({
        'Monday': 'Segunda', 'Tuesday': 'Terça', 'Wednesday': 'Quarta',
        'Thursday': 'Quinta', 'Friday': 'Sexta', 'Saturday': 'Sábado', 'Sunday': 'Domingo'
        })
    df_fatura['Categoria'] = df_fatura['Categoria'].str.title()
    df_fatura['Data'] = pd.to_datetime(df_fatura['Data'], format='%d-%m-%Y').dt.date
    df_fatura['Conta'] = "Inter"
    return df_fatura
#--------------------------------------------------------------------------------------------------
def tratar_extrato_inter(arquivo_df):
    import pandas as pd
    df_extrato = arquivo_df[arquivo_df['Descrição'] != 'Pagamento efetuado: "Pagamento fatura cartao Inter"']
    df_extrato['Data'] = df_extrato['Data Lançamento'].str.replace('/', '-')
    del df_extrato['Saldo'], df_extrato['Data Lançamento']
    df_extrato['Data'] = pd.to_datetime(df_extrato['Data'], format='%d-%m-%Y')
    df_extrato['Dia da Semana'] = df_extrato['Data'].dt.day_name().replace({
        'Monday': 'Segunda', 'Tuesday': 'Terça', 'Wednesday': 'Quarta',
        'Thursday': 'Quinta', 'Friday': 'Sexta', 'Saturday': 'Sábado', 'Sunday': 'Domingo'
        })
    df_extrato['Valor'] = df_extrato['Valor'].str.replace('.','').str.replace(',','.')
    df_extrato['Valor'] = df_extrato['Valor'].astype(float)
    df_extrato['Fonte'] = 'Extrato'
    df_extrato['Data'] = pd.to_datetime(df_extrato['Data'], format='%d-%m-%Y').dt.date
    df_extrato = df_extrato[['Data', 'Descrição', 'Valor', 'Fonte', 'Dia da Semana']]
    df_extrato['Conta'] = "Inter"
    return df_extrato
#--------------------------------------------------------------------------------------------------
def classificar_transacao(model, descricao, valor, data, dia_da_semana, fonte):
    """Classifica uma única transação usando a IA do GROQ."""
    try:
        resposta = model.invoke({"descricao": descricao, "valor": valor, "data":data, "dia_da_semana":dia_da_semana, "fonte":fonte}).content
        return resposta.strip()
    except Exception as e:
        print(f"Erro ao classificar: {descricao} - {e}")
        return "Erro"
#--------------------------------------------------------------------------------------------------
def classificar_dataframe(model,df):
    """Adiciona uma nova coluna 'Categoria' ao DataFrame."""
    df = df.copy()
    df["Categoria"] = df.apply(
        lambda row: classificar_transacao(
            model, row["Descrição"], row["Valor"], row["Data"], row["Dia da Semana"], row["Fonte"]
        ), axis=1
    )
    return df
#--------------------------------------------------------------------------------------------------
# def gerar_relatorio_rag(df):
#     """
#     Gera um relatório financeiro detalhado para ser usado como contexto em um sistema RAG.
#     Retorna uma string formatada com análises financeiras detalhadas.
#     """
#     import pandas as pd
#     import datetime
    
#     # Cópia para não alterar o original
#     df_analise = df.copy()
    
#     # Dados básicos
#     hoje = datetime.date.today()
#     ultimo_registro = df['Data'].max()
#     dias_desde_ultima_atualizacao = (hoje - ultimo_registro).days if isinstance(ultimo_registro, datetime.date) else "desconhecido"
    
#     # Resumo financeiro geral
#     saldo_atual = round(df["Valor"].sum(), 2)
#     salario = round(df[df['Categoria'] == 'Salário']['Valor'].median(), 2)
#     receita_total = round(df[df["Valor"] > 0]["Valor"].sum(), 2)
#     gasto_total = round(abs(df[df["Valor"] < 0]["Valor"].sum()), 2)
#     gasto_medio_transacao = round(abs(df[df["Valor"] < 0]["Valor"].mean()), 2)
    
#     # Análises por categoria
#     categorias_despesas = df[df['Valor'] < 0].groupby('Categoria')['Valor'].sum().abs().sort_values(ascending=False)
#     categorias_receitas = df[df['Valor'] > 0].groupby('Categoria')['Valor'].sum().sort_values(ascending=False)
    
#     # Análise temporal
#     gastos_por_mes = df[df['Valor'] < 0].groupby('Ano/Mês')['Valor'].sum().abs()
#     receitas_por_mes = df[df['Valor'] > 0].groupby('Ano/Mês')['Valor'].sum()
    
#     # Indicadores financeiros
#     gasto_medio_mensal = gastos_por_mes.mean()
#     receita_media_mensal = receitas_por_mes.mean() if len(receitas_por_mes) > 0 else 0
#     taxa_poupanca = round(((receita_media_mensal - gasto_medio_mensal) / receita_media_mensal) * 100, 2) if receita_media_mensal > 0 else 0
    
#     # Análise por conta (se aplicável)
#     contas_saldo = df.groupby('Conta')['Valor'].sum().sort_values()
    
#     # Análise por fonte (se aplicável)
#     fontes_receita = df[df['Valor'] > 0].groupby('Fonte')['Valor'].sum().sort_values(ascending=False)
    
#     # Análise de dias da semana (se aplicável)
#     gastos_por_dia = df[df['Valor'] < 0].groupby('Dia da Semana')['Valor'].sum().abs()
    
#     # Análise de tipos de transação (se aplicável)
#     tipos_transacao = df.groupby('Tipo Transação')['Valor'].sum()
    
#     # Identificar transações recorrentes
#     transacoes_frequentes = df.groupby('Descrição').agg({
#         'Valor': ['count', 'mean'],
#         'Categoria': 'first'
#     })
#     transacoes_frequentes.columns = ['Frequência', 'Valor Médio', 'Categoria']
#     transacoes_frequentes = transacoes_frequentes[transacoes_frequentes['Frequência'] > 2].sort_values('Frequência', ascending=False)
    
#     # Tendências recentes
#     # Pegar os últimos 3 meses se disponíveis
#     meses_disponiveis = sorted(df['Ano/Mês'].unique())
#     ultimos_meses = meses_disponiveis[-3:] if len(meses_disponiveis) >= 3 else meses_disponiveis
    
#     df_recente = df[df['Ano/Mês'].isin(ultimos_meses)]
#     tendencia_gastos = df_recente[df_recente['Valor'] < 0].groupby('Ano/Mês')['Valor'].sum().abs()
#     tendencia_receitas = df_recente[df_recente['Valor'] > 0].groupby('Ano/Mês')['Valor'].sum()
    
#     # Preparar o relatório
#     relatorio = f"""# Perfil Financeiro Detalhado do Usuário

# ## 1. Resumo Geral da Situação Financeira
# - **Saldo atual**: R$ {saldo_atual:.2f}
# - **Último registro financeiro**: {ultimo_registro}
# - **Dias desde última atualização**: {dias_desde_ultima_atualizacao}
# - **Receita total registrada**: R$ {receita_total:.2f}
# - **Despesa total registrada**: R$ {gasto_total:.2f}
# - **Salário médio (estimado)**: R$ {salario:.2f}

# ## 2. Análise de Receitas
# ### Principais fontes de renda:
# """

#     # Adicionar informações de categorias de receita
#     for categoria, valor in categorias_receitas.items():
#         percentual = (valor / receita_total) * 100
#         relatorio += f"- **{categoria}**: R$ {valor:.2f} ({percentual:.1f}% da receita total)\n"
    
#     # Adicionar informações de fontes de receita
#     if not fontes_receita.empty:
#         relatorio += "\n### Receitas por fonte:\n"
#         for fonte, valor in fontes_receita.items():
#             percentual = (valor / receita_total) * 100
#             relatorio += f"- **{fonte}**: R$ {valor:.2f} ({percentual:.1f}% da receita total)\n"
    
#     relatorio += f"""
# ## 3. Análise de Despesas
# ### Principais categorias de despesas:
# """

#     # Adicionar informações de categorias de despesa
#     for categoria, valor in categorias_despesas.items():
#         percentual = (valor / gasto_total) * 100
#         relatorio += f"- **{categoria}**: R$ {valor:.2f} ({percentual:.1f}% das despesas totais)\n"
    
#     # Análise de dias da semana
#     if not gastos_por_dia.empty:
#         relatorio += "\n### Padrão de gastos por dia da semana:\n"
#         for dia, valor in gastos_por_dia.sort_values(ascending=False).items():
#             percentual = (valor / gasto_total) * 100
#             relatorio += f"- **{dia}**: R$ {valor:.2f} ({percentual:.1f}% das despesas totais)\n"
    
#     relatorio += f"""
# ## 4. Análise Temporal
# ### Evolução mensal:
# """

#     # Adicionar informações de evolução mensal
#     meses_todos = sorted(set(gastos_por_mes.index) | set(receitas_por_mes.index))
#     for mes in meses_todos:
#         receita = receitas_por_mes.get(mes, 0)
#         gasto = gastos_por_mes.get(mes, 0)
#         saldo_mes = receita - gasto
#         relatorio += f"- **{mes}**: Receitas R$ {receita:.2f}, Despesas R$ {gasto:.2f}, Saldo R$ {saldo_mes:.2f}\n"
    
#     # Adicionar tendências recentes
#     if len(ultimos_meses) > 1:
#         relatorio += "\n### Tendência dos últimos meses:\n"
        
#         # Verificar se os gastos estão aumentando ou diminuindo
#         if len(tendencia_gastos) > 1:
#             primeiro_gasto = tendencia_gastos.iloc[0]
#             ultimo_gasto = tendencia_gastos.iloc[-1]
#             variacao_gastos = ((ultimo_gasto - primeiro_gasto) / primeiro_gasto) * 100
            
#             if variacao_gastos > 10:
#                 relatorio += f"- **ALERTA**: Gastos aumentaram {variacao_gastos:.1f}% nos últimos meses\n"
#             elif variacao_gastos < -10:
#                 relatorio += f"- **POSITIVO**: Gastos diminuíram {abs(variacao_gastos):.1f}% nos últimos meses\n"
#             else:
#                 relatorio += f"- Gastos mantiveram-se estáveis nos últimos meses (variação de {variacao_gastos:.1f}%)\n"
        
#         # Verificar se as receitas estão aumentando ou diminuindo
#         if len(tendencia_receitas) > 1:
#             primeira_receita = tendencia_receitas.iloc[0]
#             ultima_receita = tendencia_receitas.iloc[-1]
#             variacao_receitas = ((ultima_receita - primeira_receita) / primeira_receita) * 100
            
#             if variacao_receitas > 10:
#                 relatorio += f"- **POSITIVO**: Receitas aumentaram {variacao_receitas:.1f}% nos últimos meses\n"
#             elif variacao_receitas < -10:
#                 relatorio += f"- **ALERTA**: Receitas diminuíram {abs(variacao_receitas):.1f}% nos últimos meses\n"
#             else:
#                 relatorio += f"- Receitas mantiveram-se estáveis nos últimos meses (variação de {variacao_receitas:.1f}%)\n"
    
#     relatorio += f"""
# ## 5. Indicadores Financeiros
# - **Receita média mensal**: R$ {receita_media_mensal:.2f}
# - **Despesa média mensal**: R$ {gasto_medio_mensal:.2f}
# - **Gasto médio por transação**: R$ {gasto_medio_transacao:.2f}
# - **Taxa de poupança mensal**: {taxa_poupanca:.1f}%
# """

#     # Análise por conta
#     if len(contas_saldo) > 1:
#         relatorio += "\n## 6. Distribuição por Contas\n"
#         for conta, saldo in contas_saldo.items():
#             relatorio += f"- **{conta}**: Saldo de R$ {saldo:.2f}\n"
    
#     # Análise por tipo de transação
#     if not tipos_transacao.empty:
#         relatorio += "\n## 7. Tipos de Transação\n"
#         for tipo, valor in tipos_transacao.items():
#             relatorio += f"- **{tipo}**: R$ {valor:.2f}\n"
    
#     # Transações recorrentes
#     if not transacoes_frequentes.empty:
#         relatorio += "\n## 8. Transações Recorrentes\n"
#         for desc, row in transacoes_frequentes.iterrows():
#             relatorio += f"- **{desc}** ({row['Categoria']}): {row['Frequência']} ocorrências, valor médio R$ {abs(row['Valor Médio']):.2f}\n"
    
#     # Análise de saúde financeira
#     relatorio += "\n## 9. Análise de Saúde Financeira\n"
    
#     # Relação despesa/receita
#     if receita_media_mensal > 0:
#         proporcao_gasto = (gasto_medio_mensal / receita_media_mensal) * 100
#         relatorio += f"- O usuário gasta em média {proporcao_gasto:.1f}% da sua renda mensal.\n"
        
#         if proporcao_gasto > 90:
#             relatorio += "- **ALERTA CRÍTICO**: As despesas estão próximas ou excedem as receitas, situação financeira em risco.\n"
#         elif proporcao_gasto > 80:
#             relatorio += "- **ALERTA**: A taxa de gastos está elevada, deixando pouca margem para poupança e emergências.\n"
#         elif proporcao_gasto < 60:
#             relatorio += "- **POSITIVO**: O usuário mantém um bom nível de poupança mensal.\n"
    
#     # Identificar maiores despesas
#     if not categorias_despesas.empty and len(categorias_despesas) > 0:
#         maior_categoria = categorias_despesas.index[0]
#         percentual_maior = (categorias_despesas.iloc[0] / gasto_total) * 100
#         relatorio += f"- A categoria '{maior_categoria}' representa {percentual_maior:.1f}% das despesas totais.\n"
        
#         if percentual_maior > 40:
#             relatorio += f"- **OBSERVAÇÃO**: A categoria '{maior_categoria}' concentra uma proporção significativa dos gastos.\n"
    
#     # Análise de emergência financeira
#     meses_seguranca = saldo_atual / gasto_medio_mensal if gasto_medio_mensal > 0 else 0
#     relatorio += f"- **Reserva de emergência**: O saldo atual cobriria aproximadamente {meses_seguranca:.1f} meses de despesas.\n"
    
#     if meses_seguranca < 3:
#         relatorio += "- **ALERTA**: Reserva de emergência abaixo do recomendado (mínimo de 3-6 meses de despesas).\n"
#     elif meses_seguranca > 6:
#         relatorio += "- **POSITIVO**: Boa reserva de emergência, superior a 6 meses de despesas.\n"
    
#     # Recomendações personalizadas
#     relatorio += "\n## 10. Recomendações Automáticas\n"
    
#     # Baseadas na taxa de poupança
#     if taxa_poupanca < 10:
#         relatorio += "- **Aumentar taxa de poupança**: A taxa atual está abaixo do recomendado (20% da renda). Considere revisar despesas não essenciais.\n"
    
#     # Baseadas nas categorias de maior gasto
#     if not categorias_despesas.empty and len(categorias_despesas) > 0:
#         maior_categoria = categorias_despesas.index[0]
#         percentual_maior = (categorias_despesas.iloc[0] / gasto_total) * 100
        
#         if percentual_maior > 40:
#             relatorio += f"- **Revisar gastos em '{maior_categoria}'**: Esta categoria representa {percentual_maior:.1f}% das despesas totais, o que pode indicar oportunidade de otimização.\n"
    
#     # Baseadas na tendência de gastos
#     if len(tendencia_gastos) > 1:
#         primeiro_gasto = tendencia_gastos.iloc[0]
#         ultimo_gasto = tendencia_gastos.iloc[-1]
#         variacao_gastos = ((ultimo_gasto - primeiro_gasto) / primeiro_gasto) * 100
        
#         if variacao_gastos > 15:
#             relatorio += f"- **Controlar aumento de gastos**: Houve um aumento de {variacao_gastos:.1f}% nos gastos recentemente, analise as causas.\n"
    
#     # Conclusão
#     relatorio += "\n## 11. Conclusão\n"
#     if taxa_poupanca > 20 and proporcao_gasto < 70 and meses_seguranca > 6:
#         relatorio += "- O usuário apresenta uma **saúde financeira sólida**, com boa taxa de poupança e reserva de emergência adequada.\n"
#     elif taxa_poupanca < 10 or proporcao_gasto > 90 or meses_seguranca < 2:
#         relatorio += "- O usuário apresenta **vulnerabilidade financeira**, necessitando ajustes significativos para melhorar sua resiliência econômica.\n"
#     else:
#         relatorio += "- O usuário apresenta uma **saúde financeira moderada**, com oportunidades de melhoria em sua gestão financeira.\n"
    
#     # Retornar apenas a string, não usar st.write()
#     return relatorio

#--------------------------------------------------------------------------------------------------
def gerar_relatorio_rag(df):
    """
    Gera um relatório financeiro detalhado para ser usado como contexto em um sistema RAG.
    Retorna uma string formatada com análises financeiras detalhadas.
    """
    import pandas as pd
    import datetime
    import re
    from collections import Counter
    
    # Cópia para não alterar o original
    df_analise = df.copy()
    
    # Dados básicos
    hoje = datetime.date.today()
    ultimo_registro = df['Data'].max()
    dias_desde_ultima_atualizacao = (pd.to_datetime(hoje) - pd.to_datetime(ultimo_registro)).days if isinstance(ultimo_registro, datetime.date) else "desconhecido"
    
    # Resumo financeiro geral
    saldo_atual = round(df["Valor"].sum(), 2)
    salario = round(df[df['Categoria'] == 'Salário']['Valor'].median(), 2)
    receita_total = round(df[df["Valor"] > 0]["Valor"].sum(), 2)
    gasto_total = round(abs(df[df["Valor"] < 0]["Valor"].sum()), 2)
    gasto_medio_transacao = round(abs(df[df["Valor"] < 0]["Valor"].mean()), 2)
    
    # Análises por categoria
    categorias_despesas = df[df['Valor'] < 0].groupby('Categoria')['Valor'].sum().abs().sort_values(ascending=False)
    categorias_receitas = df[df['Valor'] > 0].groupby('Categoria')['Valor'].sum().sort_values(ascending=False)
    
    # Análise temporal
    gastos_por_mes = df[df['Valor'] < 0].groupby('Ano/Mês')['Valor'].sum().abs()
    receitas_por_mes = df[df['Valor'] > 0].groupby('Ano/Mês')['Valor'].sum()
    
    # Indicadores financeiros
    gasto_medio_mensal = gastos_por_mes.mean()
    receita_media_mensal = receitas_por_mes.mean() if len(receitas_por_mes) > 0 else 0
    taxa_poupanca = round(((receita_media_mensal - gasto_medio_mensal) / receita_media_mensal) * 100, 2) if receita_media_mensal > 0 else 0
    
    # Análise por conta (se aplicável)
    contas_saldo = df.groupby('Conta')['Valor'].sum().sort_values()
    
    # Análise por fonte (se aplicável)
    fontes_receita = df[df['Valor'] > 0].groupby('Fonte')['Valor'].sum().sort_values(ascending=False)
    
    # Análise de dias da semana (se aplicável)
    gastos_por_dia = df[df['Valor'] < 0].groupby('Dia da Semana')['Valor'].sum().abs()
    
    # Análise de tipos de transação (se aplicável)
    tipos_transacao = df.groupby('Tipo Transação')['Valor'].sum()
    
    # Identificar transações recorrentes
    transacoes_frequentes = df.groupby('Descrição').agg({
        'Valor': ['count', 'mean'],
        'Categoria': 'first'
    })
    transacoes_frequentes.columns = ['Frequência', 'Valor Médio', 'Categoria']
    transacoes_frequentes = transacoes_frequentes[transacoes_frequentes['Frequência'] > 2].sort_values('Frequência', ascending=False)
    
    # Tendências recentes
    # Pegar os últimos 3 meses se disponíveis
    meses_disponiveis = sorted(df['Ano/Mês'].unique())
    ultimos_meses = meses_disponiveis[-3:] if len(meses_disponiveis) >= 3 else meses_disponiveis
    
    df_recente = df[df['Ano/Mês'].isin(ultimos_meses)]
    tendencia_gastos = df_recente[df_recente['Valor'] < 0].groupby('Ano/Mês')['Valor'].sum().abs()
    tendencia_receitas = df_recente[df_recente['Valor'] > 0].groupby('Ano/Mês')['Valor'].sum()
    
    # Gerar nuvem de palavras textual a partir da coluna Descrição
    # Primeiro para todas as transações
    todas_descricoes = ' '.join(df['Descrição'].astype(str).tolist())
    # Depois separadamente para receitas e despesas
    descricoes_receitas = ' '.join(df[df['Valor'] > 0]['Descrição'].astype(str).tolist())
    descricoes_despesas = ' '.join(df[df['Valor'] < 0]['Descrição'].astype(str).tolist())
    
    # Função para processar texto e extrair palavras significativas
    def extrair_palavras_chave(texto, min_len=3, max_palavras=25):
        # Converter para minúsculas
        texto = texto.lower()
        # Remover caracteres especiais
        texto = re.sub(r'[^\w\s]', ' ', texto)
        # Dividir em palavras
        palavras = texto.split()
        # Filtrar palavras muito curtas e palavras comuns (stopwords)
        stopwords = ['de', 'da', 'do', 'das', 'dos', 'para', 'com', 'por', 'em', 'no', 'na', 'nos', 'nas', 
                     'um', 'uma', 'uns', 'umas', 'o', 'a', 'os', 'as', 'e', 'ou', 'que', 'pra', 'pro']
        palavras_filtradas = [p for p in palavras if len(p) >= min_len and p not in stopwords]
        # Contar frequência
        contagem = Counter(palavras_filtradas)
        # Retornar as mais frequentes
        return contagem.most_common(max_palavras)
    
    # Processar as descrições
    palavras_chave_todas = extrair_palavras_chave(todas_descricoes)
    palavras_chave_receitas = extrair_palavras_chave(descricoes_receitas)
    palavras_chave_despesas = extrair_palavras_chave(descricoes_despesas)
    
    # Preparar o relatório
    relatorio = f"""# Perfil Financeiro Detalhado do Usuário

## 1. Resumo Geral da Situação Financeira
- **Saldo atual**: R$ {saldo_atual:.2f}
- **Último registro financeiro**: {ultimo_registro}
- **Dias desde última atualização**: {dias_desde_ultima_atualizacao}
- **Receita total registrada**: R$ {receita_total:.2f}
- **Despesa total registrada**: R$ {gasto_total:.2f}
- **Salário médio (estimado)**: R$ {salario:.2f}

## 2. Análise de Receitas
### Principais fontes de renda:
"""

    # Adicionar informações de categorias de receita
    for categoria, valor in categorias_receitas.items():
        percentual = (valor / receita_total) * 100
        relatorio += f"- **{categoria}**: R$ {valor:.2f} ({percentual:.1f}% da receita total)\n"
    
    # Adicionar informações de fontes de receita
    if not fontes_receita.empty:
        relatorio += "\n### Receitas por fonte:\n"
        for fonte, valor in fontes_receita.items():
            percentual = (valor / receita_total) * 100
            relatorio += f"- **{fonte}**: R$ {valor:.2f} ({percentual:.1f}% da receita total)\n"
    
    relatorio += f"""
## 3. Análise de Despesas
### Principais categorias de despesas:
"""

    # Adicionar informações de categorias de despesa
    for categoria, valor in categorias_despesas.items():
        percentual = (valor / gasto_total) * 100
        relatorio += f"- **{categoria}**: R$ {valor:.2f} ({percentual:.1f}% das despesas totais)\n"
    
    # Análise de dias da semana
    if not gastos_por_dia.empty:
        relatorio += "\n### Padrão de gastos por dia da semana:\n"
        for dia, valor in gastos_por_dia.sort_values(ascending=False).items():
            percentual = (valor / gasto_total) * 100
            relatorio += f"- **{dia}**: R$ {valor:.2f} ({percentual:.1f}% das despesas totais)\n"
    
    relatorio += f"""
## 4. Análise Temporal
### Evolução mensal:
"""

    # Adicionar informações de evolução mensal
    meses_todos = sorted(set(gastos_por_mes.index) | set(receitas_por_mes.index))
    for mes in meses_todos:
        receita = receitas_por_mes.get(mes, 0)
        gasto = gastos_por_mes.get(mes, 0)
        saldo_mes = receita - gasto
        relatorio += f"- **{mes}**: Receitas R$ {receita:.2f}, Despesas R$ {gasto:.2f}, Saldo R$ {saldo_mes:.2f}\n"
    
    # Adicionar tendências recentes
    if len(ultimos_meses) > 1:
        relatorio += "\n### Tendência dos últimos meses:\n"
        
        # Verificar se os gastos estão aumentando ou diminuindo
        if len(tendencia_gastos) > 1:
            primeiro_gasto = tendencia_gastos.iloc[0]
            ultimo_gasto = tendencia_gastos.iloc[-1]
            variacao_gastos = ((ultimo_gasto - primeiro_gasto) / primeiro_gasto) * 100
            
            if variacao_gastos > 10:
                relatorio += f"- **ALERTA**: Gastos aumentaram {variacao_gastos:.1f}% nos últimos meses\n"
            elif variacao_gastos < -10:
                relatorio += f"- **POSITIVO**: Gastos diminuíram {abs(variacao_gastos):.1f}% nos últimos meses\n"
            else:
                relatorio += f"- Gastos mantiveram-se estáveis nos últimos meses (variação de {variacao_gastos:.1f}%)\n"
        
        # Verificar se as receitas estão aumentando ou diminuindo
        if len(tendencia_receitas) > 1:
            primeira_receita = tendencia_receitas.iloc[0]
            ultima_receita = tendencia_receitas.iloc[-1]
            variacao_receitas = ((ultima_receita - primeira_receita) / primeira_receita) * 100
            
            if variacao_receitas > 10:
                relatorio += f"- **POSITIVO**: Receitas aumentaram {variacao_receitas:.1f}% nos últimos meses\n"
            elif variacao_receitas < -10:
                relatorio += f"- **ALERTA**: Receitas diminuíram {abs(variacao_receitas):.1f}% nos últimos meses\n"
            else:
                relatorio += f"- Receitas mantiveram-se estáveis nos últimos meses (variação de {variacao_receitas:.1f}%)\n"
    
    relatorio += f"""
## 5. Indicadores Financeiros
- **Receita média mensal**: R$ {receita_media_mensal:.2f}
- **Despesa média mensal**: R$ {gasto_medio_mensal:.2f}
- **Gasto médio por transação**: R$ {gasto_medio_transacao:.2f}
- **Taxa de poupança mensal**: {taxa_poupanca:.1f}%
"""

    # Análise por conta
    if len(contas_saldo) > 1:
        relatorio += "\n## 6. Distribuição por Contas\n"
        for conta, saldo in contas_saldo.items():
            relatorio += f"- **{conta}**: Saldo de R$ {saldo:.2f}\n"
    
    # Análise por tipo de transação
    if not tipos_transacao.empty:
        relatorio += "\n## 7. Tipos de Transação\n"
        for tipo, valor in tipos_transacao.items():
            relatorio += f"- **{tipo}**: R$ {valor:.2f}\n"
    
    # Transações recorrentes
    if not transacoes_frequentes.empty:
        relatorio += "\n## 8. Transações Recorrentes\n"
        for desc, row in transacoes_frequentes.iterrows():
            relatorio += f"- **{desc}** ({row['Categoria']}): {row['Frequência']} ocorrências, valor médio R$ {abs(row['Valor Médio']):.2f}\n"
    
    # Adicionar seção de nuvem de palavras (análise textual)
    relatorio += "\n## 9. Análise Textual de Transações\n"
    
    # Adicionar nuvem de palavras geral
    relatorio += "### Palavras mais frequentes em todas as transações:\n"
    for palavra, contagem in palavras_chave_todas:
        relatorio += f"- {palavra}: {contagem} ocorrências\n"
    
    # Adicionar nuvem de palavras para despesas
    relatorio += "\n### Palavras mais frequentes em transações de despesa:\n"
    for palavra, contagem in palavras_chave_despesas:
        relatorio += f"- {palavra}: {contagem} ocorrências\n"
    
    # Adicionar nuvem de palavras para receitas
    relatorio += "\n### Palavras mais frequentes em transações de receita:\n"
    for palavra, contagem in palavras_chave_receitas:
        relatorio += f"- {palavra}: {contagem} ocorrências\n"
    
    # Análise de saúde financeira (movido para seção 10)
    relatorio += "\n## 10. Análise de Saúde Financeira\n"
    
    # Relação despesa/receita
    if receita_media_mensal > 0:
        proporcao_gasto = (gasto_medio_mensal / receita_media_mensal) * 100
        relatorio += f"- O usuário gasta em média {proporcao_gasto:.1f}% da sua renda mensal.\n"
        
        if proporcao_gasto > 90:
            relatorio += "- **ALERTA CRÍTICO**: As despesas estão próximas ou excedem as receitas, situação financeira em risco.\n"
        elif proporcao_gasto > 80:
            relatorio += "- **ALERTA**: A taxa de gastos está elevada, deixando pouca margem para poupança e emergências.\n"
        elif proporcao_gasto < 60:
            relatorio += "- **POSITIVO**: O usuário mantém um bom nível de poupança mensal.\n"
    
    # Identificar maiores despesas
    if not categorias_despesas.empty and len(categorias_despesas) > 0:
        maior_categoria = categorias_despesas.index[0]
        percentual_maior = (categorias_despesas.iloc[0] / gasto_total) * 100
        relatorio += f"- A categoria '{maior_categoria}' representa {percentual_maior:.1f}% das despesas totais.\n"
        
        if percentual_maior > 40:
            relatorio += f"- **OBSERVAÇÃO**: A categoria '{maior_categoria}' concentra uma proporção significativa dos gastos.\n"
    
    # Análise de emergência financeira
    meses_seguranca = saldo_atual / gasto_medio_mensal if gasto_medio_mensal > 0 else 0
    relatorio += f"- **Reserva de emergência**: O saldo atual cobriria aproximadamente {meses_seguranca:.1f} meses de despesas.\n"
    
    if meses_seguranca < 3:
        relatorio += "- **ALERTA**: Reserva de emergência abaixo do recomendado (mínimo de 3-6 meses de despesas).\n"
    elif meses_seguranca > 6:
        relatorio += "- **POSITIVO**: Boa reserva de emergência, superior a 6 meses de despesas.\n"
    
    # Recomendações personalizadas
    relatorio += "\n## 11. Recomendações Automáticas\n"
    
    # Baseadas na taxa de poupança
    if taxa_poupanca < 10:
        relatorio += "- **Aumentar taxa de poupança**: A taxa atual está abaixo do recomendado (20% da renda). Considere revisar despesas não essenciais.\n"
    
    # Baseadas nas categorias de maior gasto
    if not categorias_despesas.empty and len(categorias_despesas) > 0:
        maior_categoria = categorias_despesas.index[0]
        percentual_maior = (categorias_despesas.iloc[0] / gasto_total) * 100
        
        if percentual_maior > 40:
            relatorio += f"- **Revisar gastos em '{maior_categoria}'**: Esta categoria representa {percentual_maior:.1f}% das despesas totais, o que pode indicar oportunidade de otimização.\n"
    
    # Baseadas na tendência de gastos
    if len(tendencia_gastos) > 1:
        primeiro_gasto = tendencia_gastos.iloc[0]
        ultimo_gasto = tendencia_gastos.iloc[-1]
        variacao_gastos = ((ultimo_gasto - primeiro_gasto) / primeiro_gasto) * 100
        
        if variacao_gastos > 15:
            relatorio += f"- **Controlar aumento de gastos**: Houve um aumento de {variacao_gastos:.1f}% nos gastos recentemente, analise as causas.\n"
    
    # Análise baseada nas palavras mais frequentes (nova)
    if palavras_chave_despesas:
        relatorio += "- **Atenção aos padrões de gastos**: "
        palavras_topo = [p[0] for p in palavras_chave_despesas[:5]]
        relatorio += f"As palavras mais frequentes em suas despesas são: {', '.join(palavras_topo)}. "
        relatorio += "Isso pode indicar áreas de gastos recorrentes que merecem atenção.\n"
    
    # Conclusão
    relatorio += "\n## 12. Conclusão\n"
    if taxa_poupanca > 20 and proporcao_gasto < 70 and meses_seguranca > 6:
        relatorio += "- O usuário apresenta uma **saúde financeira sólida**, com boa taxa de poupança e reserva de emergência adequada.\n"
    elif taxa_poupanca < 10 or proporcao_gasto > 90 or meses_seguranca < 2:
        relatorio += "- O usuário apresenta **vulnerabilidade financeira**, necessitando ajustes significativos para melhorar sua resiliência econômica.\n"
    else:
        relatorio += "- O usuário apresenta uma **saúde financeira moderada**, com oportunidades de melhoria em sua gestão financeira.\n"
    
    # Resumo baseado na análise textual (novo)
    relatorio += "\n- **Padrões de consumo**: A análise textual das transações indica "
    
    # Encontrar algumas insights das palavras frequentes
    palavras_destaque = [p[0] for p in palavras_chave_despesas[:3]]
    if palavras_destaque:
        relatorio += f"frequência de gastos relacionados a {', '.join(palavras_destaque)}. "
        relatorio += "Estes podem representar oportunidades de otimização de despesas ou refletir as prioridades atuais do usuário.\n"
    
    # Retornar apenas a string, não usar st.write()
    return relatorio