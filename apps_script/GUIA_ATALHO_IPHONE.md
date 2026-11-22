# 📱 Guia: Registrar Gastos pelo iPhone (Atalhos + Apple Pay)

Este guia conecta o seu iPhone diretamente à aba `df` da sua planilha do **Google Sheets** usando o webhook em [Code.gs](Code.gs). Funciona **24/7, de graça e mesmo com o computador desligado**.

---

## Parte 1 — Publicar o Webhook na sua Planilha (2 minutos)

1. Abra a sua planilha no Google Sheets.
2. No menu superior, clique em **Extensões → Apps Script**.
3. Apague o código inicial e cole todo o conteúdo de [Code.gs](Code.gs).
4. Na linha 17, troque o `TOKEN_SECRETO` por uma senha forte sua (ex: `meu-token-financas-2026`).
5. Salve (`Ctrl + S`).
6. Clique em **Implantar → Nova implantação**:
   - Clique na engrenagem e selecione **App da Web**.
   - **Executar como:** `Eu`
   - **Quem pode acessar:** `Qualquer pessoa` *(não se preocupe: o script bloqueia qualquer requisição sem o seu `TOKEN_SECRETO`)*.
7. Clique em **Implantar**, autorize o acesso à sua planilha e **copie a URL do App da Web** (termina com `/exec`).
8. **Teste rápido:** cole essa URL no navegador. Se aparecer `{"status":"ok", ...}`, está funcionando!

> 💡 **Dica:** Sempre que alterar o `Code.gs` no futuro, vá em **Implantar → Gerenciar implantações → Editar (lápis) → Nova versão** para atualizar sem mudar a URL.

---

## Parte 2 — Atalho Manual Rápido (Menu 1 toque para Pix, dinheiro e online)

Abra o app **Atalhos (Shortcuts)** no iPhone, toque em **+** e monte estes blocos em sequência:

1. **Solicitar Entrada**
   - Tipo: `Número`
   - Mensagem: `Qual o valor do gasto?`
2. **Solicitar Entrada**
   - Tipo: `Texto`
   - Mensagem: `Onde / o que foi?`
3. **Lista** *(coloque suas categorias mais usadas no topo para escolher com 1 toque)*:
   - `Alimentação`
   - `Restaurante`
   - `Transporte`
   - `Lazer`
   - `Compras`
   - `Bares`
   - `Moradia`
   - `Academia`
   - `Barbearia`
   - `Educação`
   - `Investimentos`
   - `Presente`
   - `Vestuário`
   - `Viagem`
   - `Outras Saídas`
4. **Escolher na Lista**
   - Entrada: a `Lista` acima
   - Mensagem: `Categoria`
5. **Lista** *(suas contas)*:
   - `Nubank`
   - `Inter`
   - `Mercado Pago`
   - `Dinheiro`
6. **Escolher na Lista**
   - Entrada: a `Lista` de contas
   - Mensagem: `Conta`
7. **Obter Conteúdo da URL**
   - URL: *(cole a URL `/exec` do seu Apps Script)*
   - Método: `POST`
   - Corpo da Solicitação: `JSON`
   - Adicione os campos:
     - `token` (Texto): `SEU_TOKEN_SECRETO`
     - `valor` (Texto): `Entrada Solicitada` *(do passo 1)*
     - `descricao` (Texto): `Entrada Solicitada` *(do passo 2)*
     - `categoria` (Texto): `Item Escolhido` *(do passo 4)*
     - `conta` (Texto): `Item Escolhido` *(do passo 6)*
     - `fonte` (Texto): `Pix` *(ou crie mais uma lista rápida com `Crédito` / `Pix` / `Débito`)*
     - `tipo` (Texto): `despesa`
     - `origem` (Texto): `iPhone (Atalho)`
8. **Obter Valor do Dicionário**
   - Chave: `mensagem`
   - Dicionário: `Conteúdo da URL`
9. **Mostrar Notificação**
   - Texto: `Valor do Dicionário`

### ⚡ Como acionar em 1 segundo no dia a dia:
- **Botão de Ação (iPhone 15 Pro+):** Ajustes → Botão de Ação → Atalho → *Registrar Gasto*.
- **Toque Atrás (qualquer iPhone):** Ajustes → Acessibilidade → Toque → Tocar Atrás → Toque Duplo → *Registrar Gasto*.
- **Tela Bloqueada / Tela Inicial:** adicione o widget do app Atalhos com *Registrar Gasto*.

---

## Parte 3 — Automação Automática no Apple Pay (iOS 17+)

Sempre que você encostar o iPhone ou Apple Watch na maquininha, o gasto é capturado automaticamente:

1. No app **Atalhos**, toque na aba **Automação** → **+**.
2. Escolha o gatilho **Transação** (Carteira / Apple Pay).
3. Selecione os cartões que você usa (ex: Nubank, Inter) e marque **Executar Imediatamente**.
4. Crie uma **Nova Automação em Branco** com:
   - **Lista** com suas categorias + **Escolher na Lista** *(1 toque para escolher a categoria na hora! Se quiser 100% silencioso sem perguntar nada, pule a lista e envie `"categoria": ""` — o Apps Script tenta descobrir pelo seu histórico ou marca como `"A Revisar"`).*
   - **Obter Conteúdo da URL** (`POST` JSON para a mesma URL `/exec`):
     - `token`: `SEU_TOKEN_SECRETO`
     - `valor`: `Valor` *(variável mágica de Entrada do Atalho → Transação)*
     - `descricao`: `Comerciante` *(variável mágica de Entrada do Atalho → Transação)*
     - `categoria`: `Item Escolhido` *(ou vazio `""` no modo silencioso)*
     - `conta`: `Cartão ou Passe` *(variável mágica de Entrada do Atalho → Transação)*
     - `fonte`: `Apple Pay`
     - `tipo`: `despesa`
     - `origem`: `iPhone (Apple Pay)`
   - **Obter Valor do Dicionário** (`mensagem`) → **Mostrar Notificação**.

---

## 🔄 E quando eu importar a fatura no fim do mês?

Não se preocupe em duplicar! Na tela **Lançar / Importar Gastos** do Dashboard Streamlit:
- O importador compara automaticamente cada linha da fatura/extrato com o que você lançou pelo iPhone (mesmo valor com diferença de até ±2 dias).
- Linhas que já foram lançadas pelo iPhone aparecem destacadas como **`📱 Match iPhone/Manual`** e já vêm desmarcadas (ou você pode escolher substituir o lançamento provisório pela linha oficial da fatura).
