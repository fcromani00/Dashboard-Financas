"""Tela Lançar, Importar & Revisar Gastos (Finanças V2).

Usa escrita 100% segura na aba `transacoes` (somente `append` e `update_by_key`),
suporta regras automáticas (`regras`) e desfazer importação (`importacoes`).
"""

from __future__ import annotations

from datetime import date

import pandas as pd
import streamlit as st

from core.state import invalidar_abas, ler_aba, obter_groq_key, obter_repo
from core.transactions import (
    CATEGORIAS_DESPESA,
    CATEGORIAS_RECEITA,
    CONTAS_PADRAO_V2,
    MEIOS_PADRAO,
    TODAS_CATEGORIAS_V2,
    classificar_e_reconciliar_v2,
    converter_arquivo_para_v2,
    criar_registro_transacao,
    gravar_lote_importado,
    mapa_historico_v2,
    sugerir_categoria_v2,
)
from core.utils import agora_iso, novo_id, parse_numero

st.title("💸 Lançar, Importar & Revisar")
st.caption("Escrita segura na aba `transacoes` (por ID e append), com conciliação do iPhone e opção de desfazer importação.")

try:
    df_tx = ler_aba("transacoes")
    df_regras = ler_aba("regras")
    df_imp = ler_aba("importacoes")
    df_contas = ler_aba("contas")
except Exception as exc:
    st.error(f"Erro ao acessar a planilha V2: {exc}")
    st.stop()

mapa_hist = mapa_historico_v2(df_tx)
groq_key = obter_groq_key()
opcoes_contas = (
    df_contas[df_contas["ativa"] != "N"]["nome"].tolist()
    if not df_contas.empty
    else CONTAS_PADRAO_V2
)
opcoes_contas = list(dict.fromkeys([c for c in opcoes_contas if c] + CONTAS_PADRAO_V2))

qtd_revisar = int((df_tx["status"] == "revisar").sum()) if not df_tx.empty else 0
qtd_provisorias = int((df_tx["status"] == "provisoria").sum()) if not df_tx.empty else 0
badge_rev = f" ({qtd_revisar + qtd_provisorias})" if (qtd_revisar + qtd_provisorias) > 0 else ""

tab_rapido, tab_importar, tab_revisar, tab_regras, tab_holerite = st.tabs(
    [
        "⚡ Lançamento Rápido",
        "📂 Importar Extratos / Faturas",
        f"📱 Revisar & iPhone{badge_rev}",
        "⚙️ Regras Automáticas",
        "🧾 Holerite (PDF)",
    ]
)

# ==============================================================================
# ABA 1: LANÇAMENTO RÁPIDO (PENSADO PARA CELULAR E DESKTOP + ATALHO IPHONE VIA URL)
# ==============================================================================
with tab_rapido:
    st.subheader("Novo lançamento em 5 segundos")

    # Captura parâmetros vindos da Automação do iPhone / Apple Pay via URL:
    # Ex: https://seu-app.streamlit.app/?pin=1234&acao=lancar&valor=45,90&desc=Padaria&conta=Inter&meio=apple_pay
    qp_valor = parse_numero(st.query_params.get("valor")) or 0.0
    qp_desc = str(st.query_params.get("desc", "") or st.query_params.get("descricao", "") or "").strip()
    qp_conta = str(st.query_params.get("conta", "") or "").strip()
    qp_meio = str(st.query_params.get("meio", "") or "").strip().lower()
    qp_cat = str(st.query_params.get("categoria", "") or "").strip()
    qp_autosave = str(st.query_params.get("salvar", "") or "") == "1"

    if qp_valor > 0 and qp_desc and qp_autosave and not st.session_state.get("qp_salvo"):
        sug_qp, _ = sugerir_categoria_v2(qp_desc, -abs(qp_valor), df_regras, mapa_hist)
        cat_qp_final = qp_cat or sug_qp or "A Revisar"
        reg_qp = criar_registro_transacao(
            data_tx=date.today(),
            valor=-abs(qp_valor),
            descricao=qp_desc,
            categoria=cat_qp_final,
            conta=qp_conta if qp_conta in opcoes_contas else opcoes_contas[0],
            meio=qp_meio if qp_meio in MEIOS_PADRAO else "apple_pay",
            origem="iphone",
            status="provisoria" if cat_qp_final != "A Revisar" else "revisar",
            observacao="iPhone (URL Automação)",
        )
        obter_repo().append("transacoes", [reg_qp])
        invalidar_abas("transacoes")
        st.session_state["qp_salvo"] = True
        st.success(f"📱 **Gasto do iPhone registrado automaticamente:** {qp_desc} · R$ {abs(qp_valor):.2f} em **{cat_qp_final}**!")

    elif qp_valor > 0 or qp_desc:
        st.info("📱 **Dados recebidos da automação do iPhone!** Confirme ou toque na categoria abaixo e clique em Salvar.")

    tipo_lanc = st.segmented_control("Tipo", options=["Despesa", "Receita"], default="Despesa") or "Despesa"
    eh_receita = tipo_lanc == "Receita"
    cats_disp = [c for c in (CATEGORIAS_RECEITA if eh_receita else CATEGORIAS_DESPESA) if c != "A Revisar"]

    with st.form("form_rapido_v2", clear_on_submit=True):
        c1, c2, c3 = st.columns([2.2, 1.2, 1.2])
        with c1:
            desc_in = st.text_input("Descrição", value=qp_desc, placeholder="Ex: Padaria, Uber, Mercado, Pix almoço...")
        with c2:
            val_in = st.number_input("Valor (R$)", min_value=0.0, value=abs(float(qp_valor)), step=1.0, format="%.2f")
        with c3:
            data_in = st.date_input("Data", value=date.today(), format="DD/MM/YYYY")

        st.markdown("**Categoria (1 toque) ou deixe em Automática:**")
        cat_pill = st.pills(
            "Escolha rápida de categoria",
            options=["✨ Automática"] + cats_disp[:12],
            default=qp_cat if qp_cat in cats_disp[:12] else "✨ Automática",
            label_visibility="collapsed",
        )

        c4, c5, c6 = st.columns(3)
        with c4:
            cat_select = st.selectbox("Ou todas as categorias", options=["(Usar seleção acima)"] + cats_disp)
        with c5:
            idx_conta = opcoes_contas.index(qp_conta) if qp_conta in opcoes_contas else 0
            conta_in = st.selectbox("Conta", options=opcoes_contas, index=idx_conta)
        with c6:
            idx_meio = MEIOS_PADRAO.index(qp_meio) if qp_meio in MEIOS_PADRAO else (MEIOS_PADRAO.index("apple_pay") if qp_valor > 0 else 0)
            meio_in = st.selectbox("Meio", options=MEIOS_PADRAO, index=idx_meio)

        criar_regra_check = st.checkbox("Criar regra automática para sempre usar esta categoria nessa descrição")
        salvar_btn = st.form_submit_button("💾 Salvar na planilha", type="primary", use_container_width=True)

    if salvar_btn:
        if not desc_in.strip() or val_in <= 0:
            st.warning("Informe a descrição e um valor maior que zero.")
        else:
            valor_final = abs(val_in) if eh_receita else -abs(val_in)
            escolha_cat = cat_select if cat_select != "(Usar seleção acima)" else (cat_pill or "✨ Automática")

            if escolha_cat == "✨ Automática":
                sug, _ = sugerir_categoria_v2(desc_in, valor_final, df_regras, mapa_hist)
                cat_final = sug or ("Outras Entradas" if eh_receita else "Outras Saídas")
            else:
                cat_final = escolha_cat

            reg = criar_registro_transacao(
                data_tx=data_in,
                valor=valor_final,
                descricao=desc_in,
                categoria=cat_final,
                conta=conta_in,
                meio=meio_in,
                origem="manual",
                status="confirmada",
            )
            repo = obter_repo()
            repo.append("transacoes", [reg])

            if criar_regra_check and cat_final:
                repo.append(
                    "regras",
                    [
                        {
                            "id": novo_id(),
                            "padrao": desc_in.strip().lower(),
                            "categoria": cat_final,
                            "prioridade": 10,
                            "ativa": "S",
                        }
                    ],
                )
                invalidar_abas("regras")

            invalidar_abas("transacoes")
            st.success(f"✅ **{desc_in.strip()}** (R$ {val_in:.2f}) salvo em **{cat_final}**!")
            st.toast(f"✅ {desc_in.strip()} salvo!")
            st.rerun()

    st.markdown("---")
    st.markdown("#### 🕒 Últimos 10 lançamentos")
    if not df_tx.empty:
        ultimos = df_tx.sort_values(["data", "criado_em"], ascending=[False, False]).head(10)
        st.dataframe(
            ultimos[["data", "descricao", "valor", "categoria", "conta", "meio", "origem", "status"]],
            hide_index=True,
            use_container_width=True,
            column_config={
                "data": st.column_config.DateColumn("Data", format="DD/MM/YYYY"),
                "valor": st.column_config.NumberColumn("Valor", format="R$ %.2f"),
            },
        )

# ==============================================================================
# ABA 2: IMPORTAÇÃO EM LOTE + RECONCILIAÇÃO IPHONE + DESFAZER IMPORTAÇÃO
# ==============================================================================
with tab_importar:
    st.subheader("Importar extratos e faturas")
    st.caption(
        "Suporta Nubank (Fatura CSV/PDF e Extrato CSV), Inter (Fatura e Extrato CSV) e Mercado Pago (Extrato CSV). "
        "Concilia automaticamente com os lançamentos provisórios do iPhone."
    )

    arquivos = st.file_uploader(
        "Arraste um ou mais arquivos (.csv ou .pdf)",
        type=["csv", "pdf"],
        accept_multiple_files=True,
    )

    if arquivos:
        lote_key = "|".join(sorted(f"{f.name}:{f.size}" for f in arquivos))
        if st.session_state.get("v2_lote_key") != lote_key:
            dfs_v2 = []
            avisos_arq = []
            meta_arquivos = []
            hashes_ja_importados = (
                set(df_imp[df_imp["desfeita"] != "S"]["hash_arquivo"].astype(str).tolist())
                if not df_imp.empty
                else set()
            )

            for arq in arquivos:
                df_a, tipo_a, err_a, f_hash = converter_arquivo_para_v2(arq)
                if err_a:
                    avisos_arq.append(f"❌ {err_a}")
                    continue
                if f_hash in hashes_ja_importados:
                    avisos_arq.append(
                        f"⚠️ O arquivo **{arq.name}** já foi importado anteriormente (as linhas existentes aparecerão como duplicatas)."
                    )
                if df_a is not None and not df_a.empty:
                    dfs_v2.append(df_a)
                    meta_arquivos.append((arq.name, f_hash, tipo_a or "Extrato", len(df_a)))

            st.session_state["v2_avisos_arq"] = avisos_arq
            st.session_state["v2_meta_arquivos"] = meta_arquivos

            if dfs_v2:
                df_unido = pd.concat(dfs_v2, ignore_index=True)
                with st.spinner("Aplicando regras, histórico, IA em lote e conciliando com o iPhone... 🤖"):
                    df_tx_fresh = ler_aba("transacoes", forcar=True)
                    df_rec, stats = classificar_e_reconciliar_v2(
                        df_unido,
                        df_transacoes=df_tx_fresh,
                        df_regras=df_regras,
                        groq_api_key=groq_key,
                    )
                st.session_state["v2_lote_key"] = lote_key
                st.session_state["v2_import_df"] = df_rec
                st.session_state["v2_import_stats"] = stats
            else:
                st.session_state.pop("v2_import_df", None)

        for av in st.session_state.get("v2_avisos_arq", []):
            st.warning(av)

        if "v2_import_df" in st.session_state:
            df_rev = st.session_state["v2_import_df"].copy()
            stats = st.session_state.get("v2_import_stats", {})

            qtd_novas = int((df_rev["Status"] == "🆕 Nova").sum())
            qtd_conc = int((df_rev["Status"] == "📱 Conciliar c/ iPhone").sum())
            qtd_dup = int(df_rev["Status"].str.startswith("🔁").sum())

            m1, m2, m3, m4, m5 = st.columns(5)
            m1.metric("Total lido", len(df_rev))
            m2.metric("🆕 Novas", qtd_novas)
            m3.metric("📱 Conciliar iPhone", qtd_conc)
            m4.metric("🔁 Duplicatas", qtd_dup)
            m5.metric(
                "⚡ Classificação",
                f"{stats.get('regras', 0) + stats.get('historico', 0)} hist / {stats.get('ia', 0)} IA",
            )

            filtro = st.segmented_control(
                "Filtrar",
                options=["Todas", "Selecionadas p/ Salvar", "Conciliação iPhone", "Duplicatas"],
                default="Todas",
            ) or "Todas"

            if filtro == "Selecionadas p/ Salvar":
                mask = df_rev["Incluir"] == True
            elif filtro == "Conciliação iPhone":
                mask = df_rev["Status"] == "📱 Conciliar c/ iPhone"
            elif filtro == "Duplicatas":
                mask = df_rev["Status"].str.startswith("🔁") | df_rev["Status"].str.startswith("⚠️")
            else:
                mask = pd.Series(True, index=df_rev.index)

            cols_ed = ["Incluir", "Status", "data", "descricao", "valor", "categoria", "conta", "meio", "Match Existente"]
            df_view = st.data_editor(
                df_rev.loc[mask, cols_ed],
                hide_index=True,
                use_container_width=True,
                disabled=["Status", "Match Existente"],
                column_config={
                    "Incluir": st.column_config.CheckboxColumn("Salvar", default=True),
                    "Status": "Status",
                    "data": st.column_config.DateColumn("Data", format="DD/MM/YYYY"),
                    "descricao": st.column_config.TextColumn("Descrição", width="large"),
                    "valor": st.column_config.NumberColumn("Valor", format="R$ %.2f"),
                    "categoria": st.column_config.SelectboxColumn("Categoria", options=TODAS_CATEGORIAS_V2, required=True),
                    "conta": st.column_config.SelectboxColumn("Conta", options=opcoes_contas),
                    "meio": st.column_config.SelectboxColumn("Meio", options=MEIOS_PADRAO),
                    "Match Existente": st.column_config.TextColumn("Conciliação / Duplicata", width="large"),
                },
                key=f"v2_editor_imp_{filtro}",
            )

            for c in cols_ed:
                df_rev.loc[mask, c] = df_view[c].values
            st.session_state["v2_import_df"] = df_rev

            selecionadas = df_rev[df_rev["Incluir"] == True].copy()
            if st.button(
                f"💾 Confirmar importação ({len(selecionadas)} transações)",
                type="primary",
                disabled=selecionadas.empty,
                use_container_width=True,
            ):
                metas = st.session_state.get("v2_meta_arquivos", [])
                nomes = ", ".join(m[0] for m in metas) or "importacao.csv"
                hashes = ",".join(m[1] for m in metas)
                formatos = ", ".join(sorted({m[2] for m in metas}))
                imp_id, n_ins, n_conc = gravar_lote_importado(
                    obter_repo(),
                    selecionadas,
                    nome_arquivo=nomes,
                    hash_arq=hashes,
                    formato=formatos,
                )
                invalidar_abas("transacoes", "importacoes")
                st.session_state.pop("v2_lote_key", None)
                st.session_state.pop("v2_import_df", None)
                st.success(
                    f"✅ Importação #{imp_id} concluída: **{n_ins}** novas inseridas e **{n_conc}** conciliadas com o iPhone!"
                )
                st.rerun()

    st.markdown("---")
    with st.expander("🕓 Histórico de Importações & Desfazer Importação", expanded=False):
        if df_imp.empty:
            st.caption("Nenhuma importação registrada ainda na V2.")
        else:
            ativas = df_imp[df_imp["desfeita"] != "S"].sort_values("importado_em", ascending=False)
            st.dataframe(df_imp.sort_values("importado_em", ascending=False), hide_index=True, use_container_width=True)
            if not ativas.empty:
                imp_sel = st.selectbox(
                    "Selecione uma importação para desfazer",
                    options=ativas["id"].tolist(),
                    format_func=lambda i: f"#{i} — {ativas.set_index('id').loc[i, 'arquivo']} ({ativas.set_index('id').loc[i, 'importado_em']})",
                )
                if st.button("↩️ Desfazer importação selecionada", type="secondary"):
                    repo = obter_repo()
                    removidas = repo.delete_by_column_value("transacoes", "importacao_id", imp_sel)
                    repo.update_by_key("importacoes", imp_sel, {"desfeita": "S"})
                    invalidar_abas("transacoes", "importacoes")
                    st.success(f"✅ Importação #{imp_sel} desfeita ({removidas} linhas removidas).")
                    st.rerun()

# ==============================================================================
# ABA 3: REVISAR PENDENTES & IPHONE
# ==============================================================================
with tab_revisar:
    st.subheader("📱 Fila de Revisão & Lançamentos do iPhone")

    modo = st.segmented_control(
        "Filtro",
        options=["Pendentes ('A Revisar')", "Provisórios do iPhone", "Todos do iPhone / Manuais"],
        default="Pendentes ('A Revisar')" if qtd_revisar > 0 else "Provisórios do iPhone",
    ) or "Pendentes ('A Revisar')"

    if modo == "Pendentes ('A Revisar')":
        df_fila = df_tx[(df_tx["status"] == "revisar") | (df_tx["categoria"].isin(["", "A Revisar"]))].copy()
    elif modo == "Provisórios do iPhone":
        df_fila = df_tx[df_tx["status"] == "provisoria"].copy()
    else:
        df_fila = df_tx[df_tx["origem"].isin(["iphone", "manual"])].head(40).copy()

    if df_fila.empty:
        st.success("🎉 Nenhum lançamento pendente neste filtro!")
    else:
        cols_f = ["id", "data", "descricao", "valor", "categoria", "conta", "meio", "status"]
        df_f_ed = st.data_editor(
            df_fila[cols_f],
            hide_index=True,
            use_container_width=True,
            disabled=["id", "data", "valor"],
            column_config={
                "id": st.column_config.TextColumn("ID", width="small"),
                "data": st.column_config.DateColumn("Data", format="DD/MM/YYYY"),
                "valor": st.column_config.NumberColumn("Valor", format="R$ %.2f"),
                "categoria": st.column_config.SelectboxColumn("Categoria", options=TODAS_CATEGORIAS_V2, required=True),
                "conta": st.column_config.SelectboxColumn("Conta", options=opcoes_contas),
                "meio": st.column_config.SelectboxColumn("Meio", options=MEIOS_PADRAO),
                "status": st.column_config.SelectboxColumn("Status", options=["confirmada", "provisoria", "revisar"]),
            },
            key="v2_editor_fila",
        )
        if st.button("💾 Aprovar / Salvar alterações", type="primary"):
            repo = obter_repo()
            atualizadas = 0
            for _, r in df_f_ed.iterrows():
                novo_status = "confirmada" if r["categoria"] != "A Revisar" and r["status"] == "revisar" else r["status"]
                repo.update_by_key(
                    "transacoes",
                    str(r["id"]),
                    {
                        "descricao": str(r["descricao"]),
                        "categoria": str(r["categoria"]),
                        "conta": str(r["conta"]),
                        "meio": str(r["meio"]),
                        "status": str(novo_status),
                        "atualizado_em": agora_iso(),
                    },
                )
                atualizadas += 1
            invalidar_abas("transacoes")
            st.success(f"✅ {atualizadas} lançamento(s) atualizado(s)!")
            st.rerun()

# ==============================================================================
# ABA 4: REGRAS AUTOMÁTICAS DE CATEGORIZAÇÃO
# ==============================================================================
with tab_regras:
    st.subheader("⚙️ Regras Automáticas de Categorização")
    st.caption(
        "As regras têm prioridade sobre o histórico e a IA — funcionam tanto na importação quanto no webhook do iPhone."
    )

    with st.form("form_nova_regra", clear_on_submit=True):
        r1, r2, r3, r4 = st.columns([2, 1.5, 1, 1])
        with r1:
            padrao_r = st.text_input("Se a descrição contiver:", placeholder="Ex: uber, ifood, spotify, buser...")
        with r2:
            cat_r = st.selectbox("Classificar como:", options=[c for c in TODAS_CATEGORIAS_V2 if c != "A Revisar"])
        with r3:
            prio_r = st.number_input("Prioridade", min_value=1, max_value=100, value=10)
        with r4:
            st.write("")
            add_r = st.form_submit_button("➕ Adicionar Regra", type="primary", use_container_width=True)

    if add_r and padrao_r.strip():
        obter_repo().append(
            "regras",
            [
                {
                    "id": novo_id(),
                    "padrao": padrao_r.strip().lower(),
                    "categoria": cat_r,
                    "prioridade": int(prio_r),
                    "ativa": "S",
                }
            ],
        )
        invalidar_abas("regras")
        st.success(f"✅ Regra '{padrao_r.strip()}' → **{cat_r}** adicionada!")
        st.rerun()

    if not df_regras.empty:
        st.dataframe(df_regras, hide_index=True, use_container_width=True)

# ==============================================================================
# ABA 5: IMPORTAR HOLERITE (PDF MERCADO PAGO — SEM DUPLICAR TRANSAÇÕES)
# ==============================================================================
with tab_holerite:
    from core.holerite import tratar_holerite_pdf

    st.subheader("Importar Holerite (PDF)")
    st.caption(
        "Extrai Salário Base, INSS, IRRF, FGTS, PrevPriv PGBL e benefícios direto para a aba `holerites` "
        "(não duplica o salário líquido que já entra pelo extrato bancário)."
    )
    pdfs_hol = st.file_uploader(
        "Selecione 1 ou mais PDFs de holerite",
        type=["pdf"],
        accept_multiple_files=True,
        key="upload_holerites_pdf",
    )
    if pdfs_hol:
        registros_hol = []
        for arq in pdfs_hol:
            try:
                reg = tratar_holerite_pdf(arq)
                reg["observacao"] = f"Importado de {arq.name}"
                registros_hol.append(reg)
            except Exception as exc:
                st.error(f"Erro ao ler `{arq.name}`: {exc}")

        if registros_hol:
            df_hol_prev = pd.DataFrame(registros_hol)
            st.dataframe(
                df_hol_prev[
                    [
                        "competencia",
                        "salario_base",
                        "total_proventos",
                        "total_descontos",
                        "total_liquido",
                        "inss",
                        "irrf",
                        "fgts",
                        "pgbl",
                        "beneficios_desconto",
                    ]
                ],
                hide_index=True,
                use_container_width=True,
            )
            if st.button("💾 Salvar Holerite(s) na Planilha", type="primary", use_container_width=True):
                repo = obter_repo()
                repo.garantir_aba("holerites")
                existentes = ler_aba("holerites")
                ids_ex = set(existentes["id"].astype(str)) if not existentes.empty else set()
                novos = [r for r in registros_hol if str(r["id"]) not in ids_ex]
                atualizados = [r for r in registros_hol if str(r["id"]) in ids_ex]
                if novos:
                    repo.append("holerites", novos)
                for r in atualizados:
                    repo.update_by_key("holerites", str(r["id"]), r)
                invalidar_abas("holerites")
                st.success(f"✅ {len(novos)} novo(s) e {len(atualizados)} atualizado(s) na aba `holerites`!")
                st.rerun()
