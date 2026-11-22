# 💰 Finanças V2 — Controle Financeiro & Investimentos

Aplicativo pessoal de gestão financeira e acompanhamento de investimentos construído com **Streamlit + Google Sheets + Automação de iPhone (Atalhos & Apple Pay) + IA (Groq & Gemini)**.

---

## ✨ Funcionalidades Principais

### 📊 Visão Geral & Orçamento (`pages/main.py`)
- Indicador de hábito (*"Último lançamento há X dias"*) e fila de pendências.
- KPIs do mês (Receitas, Despesas vs. Orçamento, Saldo/Taxa de Poupança e **Quanto ainda posso gastar por dia**).
- Gráficos separados de **Despesas por Categoria** e **Evolução Mensal (Receitas vs. Despesas)**.
- Acompanhamento do **Orçamento Mensal** e **Reserva de Emergência** com edição rápida.

### 💸 Lançar, Importar & Revisar (`pages/Inserting_Data.py`)
- **⚡ Lançamento Rápido:** registre gastos em 5 segundos com chips de 1 toque (`st.pills`).
- **📂 Importação em Lote:** arraste múltiplos CSVs/PDFs (Nubank, Inter, Mercado Pago).
- **Classificação Híbrida:** `1º Regras Automáticas → 2º Histórico da Planilha → 3º IA Groq em lote`.
- **📱 Conciliação com iPhone:** gastos lançados pelo Apple Pay/Atalho entram como `provisoria` e são confirmados automaticamente quando a fatura chega, sem duplicar.
- **↩️ Desfazer Importação:** reverta qualquer lote importado com 1 clique.

### 📈 Carteira de Investimentos Consolidada (`pages/Investimentos.py`)
- Patrimônio consolidado em **BRL** e **USD** com cotações em lote via Yahoo Finance (`yfinance`).
- **🇺🇸 Ações & ETFs (Inter US):** preço médio ponderado descontando vendas, P&L aberto, P&L realizado e importador de nota de corretagem PDF em Python puro (`PyPDF2`).
- **🐷 Renda Fixa (Porquinho Inter & CDB Mercado Pago):** aportes, resgates e ajuste rápido com o saldo líquido do app do banco.
- **₿ Bitcoin (Binance):** cotação `BTC-BRL` em tempo real e registro de compras/vendas.

### 🤖 Consultor Financeiro IA (`pages/Gemini.py`)
- Assistente com **Gemini 2.5 Flash** que enxerga seus gastos, orçamento, reserva de emergência e carteira de investimentos de forma integrada e com cache.

### 🔐 Autenticação & Configurações (`core/auth.py` e `pages/Configuracoes.py`)
- Login centralizado com hash **`PBKDF2-HMAC-SHA256`** + opção de **PIN Rápido** para o iPhone.
- Gerenciamento de Perfil, Orçamento, Contas, Categorias, Senha/PIN e Cache direto na interface.

---

## 🚀 Deploy no Streamlit Community Cloud

1. Suba este repositório para o seu GitHub (**recomendado: repositório privado**).
2. Acesse [share.streamlit.io](https://share.streamlit.io/) e clique em **Create app**.
3. Selecione o repositório, branch `main` e arquivo principal `app.py`.
4. Em **Advanced settings → Secrets**, cole o conteúdo do seu `.streamlit/secrets.toml` (contendo `[connections.gsheets]`, `GROQ_API_KEY` e `[GEMINI]`).
5. Clique em **Deploy**.

### 📱 Adicionar na Tela Inicial do iPhone
1. Abra a URL do seu app (`https://seu-app.streamlit.app`) no **Safari** do iPhone.
2. Toque em **Compartilhar** → **Adicionar à Tela de Início**.
3. Use o **PIN Rápido** configurado em `⚙️ Configurações → Conta e Segurança` para entrar em 2 segundos.
4. Para o lançamento automático via **Apple Pay / Botão de Ação**, siga o [GUIA_ATALHO_IPHONE.md](apps_script/GUIA_ATALHO_IPHONE.md).
