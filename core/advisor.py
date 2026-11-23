"""Motor do Consultor Financeiro IA V3:
- Tool Calling sob demanda (sem carregar RAG pesado a cada mensagem)
- Ferramentas em tempo real do Yahoo Finance (cotações, fundamentos, histórico, comparação e notícias)
- Memória persistente do usuário salva na aba `config` do Google Sheets (`ia.memoria_perfil`)
"""

from __future__ import annotations

import json
from datetime import date
from typing import Any, Callable

import pandas as pd
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.tools import tool

from core.portfolio import buscar_selic_atual, calcular_ir_iof_renda_fixa, consolidar_carteira
from core.recurring import analisar_parcelas, detectar_recorrencias
from core.utils import parse_data, parse_numero

CHAVE_MEMORIA_PERFIL = "ia.memoria_perfil"
CHAVE_ULTIMO_RESUMO = "ia.ultimo_resumo"


def carregar_memoria_lista(cfg: dict[str, str]) -> list[str]:
    """Lê a lista de fatos persistidos sobre o usuário em `config`."""
    raw = str(cfg.get(CHAVE_MEMORIA_PERFIL, "") or "").strip()
    if not raw:
        return []
    try:
        dados = json.loads(raw)
        if isinstance(dados, list):
            return [str(x).strip() for x in dados if str(x).strip()]
    except Exception:
        pass
    return [linha.strip("- ").strip() for linha in raw.splitlines() if linha.strip()]


def formatar_system_prompt(cfg: dict[str, str]) -> str:
    """Monta o prompt de sistema enxuto com a memória persistida do usuário."""
    fatos = carregar_memoria_lista(cfg)
    ultimo_resumo = str(cfg.get(CHAVE_ULTIMO_RESUMO, "") or "").strip()

    bloco_mem = (
        "\n".join(f"- {f}" for f in fatos)
        if fatos
        else "- (Nenhum fato salvo ainda. Use `salvar_memoria_usuario` quando o Felipe compartilhar objetivos, preferências ou decisões.)"
    )
    bloco_resumo = f"\nResumo da conversa anterior:\n{ultimo_resumo}\n" if ultimo_resumo else ""

    return (
        f"Você é o Consultor Financeiro Pessoal do Felipe (hoje é {date.today().strftime('%d/%m/%Y')}).\n"
        "Responda em português, de forma direta, analítica e prática.\n\n"
        "REGRAS IMPORTANTES:\n"
        "1. NÃO invente números. Sempre chame as ferramentas de dados (`consultar_carteira_investimentos`, "
        "`consultar_resumo_financeiro`, `consultar_metas_e_reserva`) ou do Yahoo Finance (`yf_*`) antes de responder.\n"
        "2. Sempre que o Felipe revelar uma preferência, meta, estratégia, horizonte ou decisão importante, "
        "chame `salvar_memoria_usuario` para lembrar nas próximas sessões.\n"
        "3. Para ativos brasileiros ou cripto no Yahoo Finance, use `.SA` (B3) ou `-USD`/`-BRL`.\n\n"
        f"MEMÓRIA PERSISTENTE SOBRE O FELIPE:\n{bloco_mem}\n"
        f"{bloco_resumo}"
    )


def criar_ferramentas_consultor(
    leitor_aba: Callable[[str], pd.DataFrame],
    leitor_config: Callable[[], dict[str, str]],
    gravador_config: Callable[[dict[str, str]], None],
) -> list[Any]:
    """Constrói a suíte de ferramentas (Sheets V2 + Yahoo Finance + Memória Persistente)."""

    @tool
    def consultar_carteira_investimentos(classe_filtro: str = "todas") -> str:
        """Consulta a carteira atual consolidada (ações/ETFs EUA, Renda Fixa com IOF/IR, Cripto e B3).
        `classe_filtro`: 'todas', 'acao_us', 'etf_us', 'renda_fixa', 'cripto' ou 'acao_br'.
        """
        df_a = leitor_aba("ativos")
        df_o = leitor_aba("operacoes")
        df_rf = leitor_aba("renda_fixa")
        df_cart, resumo = consolidar_carteira(df_a, df_o)
        if df_cart.empty:
            return "Nenhuma posição aberta encontrada."

        if classe_filtro and classe_filtro != "todas":
            df_cart = df_cart[df_cart["classe"] == classe_filtro]

        mapa_rf = {}
        if df_rf is not None and not df_rf.empty:
            for _, r in df_rf.iterrows():
                mapa_rf[str(r["ativo_id"])] = r

        selic_aa, cdi_aa, _ = buscar_selic_atual()
        linhas = [
            f"Resumo Geral: Patrimônio R$ {resumo['patrimonio_brl']:,.2f} | Custo R$ {resumo['custo_brl']:,.2f} | "
            f"P&L Aberto R$ {resumo['pl_aberto_brl']:,.2f} ({resumo['pl_aberto_pct']:.2f}%) | "
            f"Realizado+Proventos US$/R$ {resumo['pl_realizado_total'] + resumo['proventos_total']:,.2f} | "
            f"USD/BRL {resumo['usd_brl']:.4f} | Selic {selic_aa:.2f}% a.a. (CDI {cdi_aa:.2f}%)"
        ]
        for _, r in df_cart.iterrows():
            if r["classe"] == "renda_fixa":
                info_rf = mapa_rf.get(str(r["ativo_id"]))
                extra = ""
                if info_rf is not None:
                    dt_ap = parse_data(info_rf.get("data_aplicacao"))
                    trib = calcular_ir_iof_renda_fixa(dt_ap, rendimento_bruto=max(0.0, float(r["pl_aberto"])))
                    extra = f" | {parse_numero(info_rf.get('taxa_pct')) or 100:.0f}% CDI | IOF {trib['aliquota_iof_pct']:.0f}% | IR {trib['aliquota_ir_pct']:.1f}%"
                    if trib["aliquota_iof_pct"] > 0 and trib["data_isencao_iof"]:
                        extra += f" (isento IOF em {trib['data_isencao_iof'].strftime('%d/%m/%Y')})"
                linhas.append(
                    f"- {r['ticker']} ({r['nome']}, {r['conta']}): Saldo R$ {r['valor_brl']:,.2f} | Custo R$ {r['custo_brl']:,.2f}{extra}"
                )
            else:
                linhas.append(
                    f"- {r['ticker']} ({r['classe']}, {r['moeda']}): Qtd {r['quantidade']:.6f} | "
                    f"PM {r['preco_medio']:.2f} | Atual {r['preco_atual']:.2f} ({r['variacao_dia_pct']:+.2f}% dia) | "
                    f"Valor R$ {r['valor_brl']:,.2f} ({r['alocacao_pct']:.1f}%) | P&L {r['pl_aberto_pct']:+.2f}%"
                )
        return "\n".join(linhas)

    @tool
    def consultar_resumo_financeiro(mes: str = "") -> str:
        """Consulta receitas, despesas, saldo, top categorias, orçamento, fixos e parcelas.
        Passe `mes` no formato 'YYYY-MM' ou deixe vazio para o mês mais recente + histórico de 6 meses.
        """
        df_tx = leitor_aba("transacoes")
        df_orc = leitor_aba("orcamento")
        if df_tx.empty:
            return "Nenhuma transação registrada."

        op = df_tx[(df_tx["transferencia"] != "S") & (df_tx["categoria"] != "Transferência Interna")].copy()
        op["ano_mes"] = op["data"].apply(lambda d: d.strftime("%Y-%m") if pd.notna(d) else "")
        meses = sorted([m for m in op["ano_mes"].unique() if m])
        mes_alvo = mes.strip() if mes.strip() in meses else (meses[-1] if meses else "")

        linhas = ["Evolução últimos 6 meses:"]
        rec_m = op[op["valor"] > 0].groupby("ano_mes")["valor"].sum()
        desp_m = op[op["valor"] < 0].groupby("ano_mes")["valor"].sum().abs()
        for m in meses[-6:]:
            r = float(rec_m.get(m, 0.0))
            d = float(desp_m.get(m, 0.0))
            linhas.append(f"- {m}: Receitas R$ {r:,.2f} | Despesas R$ {d:,.2f} | Saldo R$ {r - d:,.2f}")

        if mes_alvo:
            df_m = op[op["ano_mes"] == mes_alvo]
            cats = df_m[df_m["valor"] < 0].groupby("categoria")["valor"].sum().abs().sort_values(ascending=False)
            linhas.append(f"\nTop categorias de despesa em {mes_alvo}:")
            for c, v in cats.head(10).items():
                linhas.append(f"- {c}: R$ {float(v):,.2f}")

        if not df_orc.empty:
            orc_desp = df_orc[df_orc["grupo"] != "Receita"]
            linhas.append(f"\nOrçamento mensal planejado (despesas): R$ {float(orc_desp['valor'].sum()):,.2f}")

        rec = detectar_recorrencias(op)
        parc = analisar_parcelas(op)
        linhas.append(
            f"Fixos/assinaturas ativos: R$ {rec['total_fixos_ativos_mes']:,.2f}/mês ({rec['qtd_fixos_ativos']} itens) | "
            f"Parcelas futuras a vencer: R$ {parc['total_futuro']:,.2f}"
        )
        return "\n".join(linhas)

    @tool
    def consultar_metas_e_reserva() -> str:
        """Consulta as metas financeiras e reserva de emergência cadastradas."""
        df_metas = leitor_aba("metas")
        if df_metas.empty:
            return "Nenhuma meta cadastrada."
        return "\n".join(
            f"- {m['nome']}: Atual R$ {float(m['valor_atual'] or 0):,.2f} / Alvo R$ {float(m['valor_alvo'] or 0):,.2f}"
            for _, m in df_metas.iterrows()
        )

    @tool
    def yf_cotacao_e_fundamentos(ticker: str) -> str:
        """Busca no Yahoo Finance preço atual, máxima/mínima 52s, P/L, Dividend Yield, setor,
        recomendação de analistas e preço-alvo para um ticker (ex: VOO, QQQM, NVDA, PETR4.SA, BTC-USD).
        """
        import yfinance as yf

        sym = ticker.strip().upper().replace(".", "-") if "." in ticker and not ticker.upper().endswith(".SA") else ticker.strip().upper()
        try:
            info = yf.Ticker(sym).info or {}
            if not info or ("regularMarketPrice" not in info and "currentPrice" not in info and "previousClose" not in info):
                return f"Ticker '{sym}' não encontrado no Yahoo Finance."
            preco = info.get("currentPrice") or info.get("regularMarketPrice") or info.get("previousClose")
            dados = {
                "ticker": sym,
                "nome": info.get("shortName") or info.get("longName"),
                "moeda": info.get("currency"),
                "preco_atual": preco,
                "var_dia_pct": round(float(info.get("regularMarketChangePercent") or 0.0), 2),
                "min_52s": info.get("fiftyTwoWeekLow"),
                "max_52s": info.get("fiftyTwoWeekHigh"),
                "pl_trailing": info.get("trailingPE"),
                "pl_forward": info.get("forwardPE"),
                "dividend_yield_pct": round(float(info.get("dividendYield") or 0.0) * 100, 2) if info.get("dividendYield") and info.get("dividendYield") < 1 else info.get("dividendYield"),
                "market_cap": info.get("marketCap"),
                "setor": info.get("sector") or info.get("category"),
                "preco_alvo_analistas": info.get("targetMeanPrice"),
                "recomendacao": info.get("recommendationKey"),
            }
            return json.dumps(dados, ensure_ascii=False)
        except Exception as exc:
            return f"Erro ao consultar Yahoo Finance para {sym}: {exc}"

    @tool
    def yf_historico_performance(ticker: str, periodo: str = "6mo") -> str:
        """Calcula retorno acumulado, máxima, mínima e drawdown no Yahoo Finance para um ticker.
        `periodo` válidos: '1mo', '3mo', '6mo', '1y', 'ytd', '2y', '5y'.
        """
        import yfinance as yf

        sym = ticker.strip().upper()
        try:
            hist = yf.Ticker(sym).history(period=periodo, auto_adjust=True)
            if hist.empty or "Close" not in hist.columns:
                return f"Sem histórico para {sym} no período {periodo}."
            close = hist["Close"].dropna()
            ini = float(close.iloc[0])
            fim = float(close.iloc[-1])
            pico = float(close.max())
            fundo = float(close.min())
            ret_pct = ((fim / ini) - 1.0) * 100.0 if ini > 0 else 0.0
            dd_pico_pct = ((fim / pico) - 1.0) * 100.0 if pico > 0 else 0.0
            return json.dumps(
                {
                    "ticker": sym,
                    "periodo": periodo,
                    "preco_inicial": round(ini, 2),
                    "preco_atual": round(fim, 2),
                    "retorno_pct": round(ret_pct, 2),
                    "maxima_periodo": round(pico, 2),
                    "minima_periodo": round(fundo, 2),
                    "queda_desde_pico_pct": round(dd_pico_pct, 2),
                },
                ensure_ascii=False,
            )
        except Exception as exc:
            return f"Erro ao buscar histórico de {sym}: {exc}"

    @tool
    def yf_comparar_ativos(tickers: list[str], periodo: str = "6mo") -> str:
        """Compara o retorno (%) no Yahoo Finance de uma lista de tickers (ex: ['QQQM', 'SOXX', 'VOO']) no mesmo período."""
        import yfinance as yf

        syms = [t.strip().upper() for t in tickers if t.strip()][:8]
        if not syms:
            return "Informe ao menos 1 ticker."
        try:
            df = yf.download(syms, period=periodo, progress=False, auto_adjust=True)["Close"]
            if isinstance(df, pd.Series):
                df = df.to_frame(name=syms[0])
            resultados = []
            for s in syms:
                if s not in df.columns:
                    continue
                col = df[s].dropna()
                if len(col) < 2:
                    continue
                ret = ((float(col.iloc[-1]) / float(col.iloc[0])) - 1.0) * 100.0
                pico = float(col.max())
                dd = ((float(col.iloc[-1]) / pico) - 1.0) * 100.0 if pico > 0 else 0.0
                resultados.append({"ticker": s, "retorno_pct": round(ret, 2), "drawdown_pico_pct": round(dd, 2)})
            resultados.sort(key=lambda x: x["retorno_pct"], reverse=True)
            return json.dumps({"periodo": periodo, "ranking": resultados}, ensure_ascii=False)
        except Exception as exc:
            return f"Erro ao comparar ativos: {exc}"

    @tool
    def yf_noticias_ativo(ticker: str) -> str:
        """Busca as últimas 5 notícias de um ticker no Yahoo Finance."""
        import yfinance as yf

        sym = ticker.strip().upper()
        try:
            news = yf.Ticker(sym).news or []
            itens = []
            for n in news[:5]:
                content = n.get("content") if isinstance(n.get("content"), dict) else n
                titulo = content.get("title") or n.get("title")
                pub = (content.get("provider") or {}).get("displayName") or n.get("publisher")
                if titulo:
                    itens.append(f"- {titulo} ({pub or 'Yahoo Finance'})")
            return "\n".join(itens) if itens else f"Nenhuma notícia recente encontrada para {sym}."
        except Exception as exc:
            return f"Erro ao buscar notícias de {sym}: {exc}"

    @tool
    def salvar_memoria_usuario(fato: str) -> str:
        """Salva permanentemente um fato, meta, preferência ou decisão do usuário na planilha (aba `config`)."""
        fato_limpo = str(fato or "").strip()
        if not fato_limpo:
            return "Fato vazio ignorado."
        cfg = leitor_config()
        fatos = carregar_memoria_lista(cfg)
        if not any(f.lower() == fato_limpo.lower() for f in fatos):
            fatos.append(fato_limpo)
            gravador_config({CHAVE_MEMORIA_PERFIL: json.dumps(fatos, ensure_ascii=False)})
        return f"Memória salva: '{fato_limpo}' (total: {len(fatos)} fatos)."

    @tool
    def esquecer_memoria_usuario(termo: str) -> str:
        """Remove da memória persistente os fatos que contenham `termo` (case-insensitive)."""
        t = str(termo or "").strip().lower()
        if not t:
            return "Informe um termo para remover."
        cfg = leitor_config()
        fatos = carregar_memoria_lista(cfg)
        novos = [f for f in fatos if t not in f.lower()]
        gravador_config({CHAVE_MEMORIA_PERFIL: json.dumps(novos, ensure_ascii=False)})
        return f"Removido(s) {len(fatos) - len(novos)} fato(s). Restam {len(novos)}."

    return [
        consultar_carteira_investimentos,
        consultar_resumo_financeiro,
        consultar_metas_e_reserva,
        yf_cotacao_e_fundamentos,
        yf_historico_performance,
        yf_comparar_ativos,
        yf_noticias_ativo,
        salvar_memoria_usuario,
        esquecer_memoria_usuario,
    ]


def executar_turno_consultor(
    llm: Any,
    tools: list[Any],
    cfg: dict[str, str],
    historico_mensagens: list[dict[str, str]],
    pergunta: str,
    max_passos: int = 6,
) -> tuple[str, list[str]]:
    """Executa 1 turno completo de conversa com Tool Calling (sem RAG completo).
    Retorna `(texto_resposta, lista_nomes_ferramentas_usadas)`.
    """
    mapa_tools = {t.name: t for t in tools}
    llm_com_tools = llm.bind_tools(tools)

    mensagens: list[Any] = [SystemMessage(content=formatar_system_prompt(cfg))]
    for m in historico_mensagens[-8:]:
        role = m.get("role", "user")
        content = str(m.get("content", ""))
        if role == "assistant":
            mensagens.append(AIMessage(content=content))
        else:
            mensagens.append(HumanMessage(content=content))
    mensagens.append(HumanMessage(content=pergunta))

    ferramentas_usadas: list[str] = []
    for _ in range(max_passos):
        resp = llm_com_tools.invoke(mensagens)
        mensagens.append(resp)
        tool_calls = getattr(resp, "tool_calls", None) or []
        if not tool_calls:
            conteudo = resp.content
            if isinstance(conteudo, list):
                conteudo = "\n".join(
                    str(bloco.get("text", bloco)) if isinstance(bloco, dict) else str(bloco)
                    for bloco in conteudo
                )
            return str(conteudo), ferramentas_usadas

        for tc in tool_calls:
            nome = tc.get("name", "")
            args = tc.get("args", {}) or {}
            tc_id = tc.get("id", nome)
            ferramentas_usadas.append(nome)
            fn = mapa_tools.get(nome)
            if fn is None:
                saida = f"Ferramenta '{nome}' não encontrada."
            else:
                try:
                    saida = str(fn.invoke(args))
                except Exception as exc:
                    saida = f"Erro ao executar '{nome}': {exc}"
            mensagens.append(ToolMessage(content=saida, tool_call_id=tc_id))

    return "Não consegui concluir a análise dentro do limite de chamadas de ferramentas.", ferramentas_usadas
