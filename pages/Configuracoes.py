"""Página de Configurações (Finanças V2) — inspirada no `NutriV3/pages/8_Configuracoes.py`.

Permite gerenciar:
- Perfil Financeiro (aba `config`)
- Orçamento Mensal, Contas e Categorias (abas `orcamento`, `contas`, `categorias`)
- Conta e Segurança: E-mail, Senha e PIN Rápido para iPhone (aba `config`)
- Sistema e Cache
"""

from __future__ import annotations

import streamlit as st

from core import schema
from core.auth import gerar_hash_senha, verificar_hash_senha
from core.state import invalidar_abas, ler_aba, mapa_config, obter_repo, salvar_config
from core.utils import id_deterministico, novo_id

st.title("⚙️ Configurações")
st.caption("Gerencie seu perfil, orçamento mensal, contas, categorias e segurança de login.")

cfg = mapa_config()

tab_perfil, tab_orc_cad, tab_seguranca, tab_sistema = st.tabs(
    [
        "👤 Perfil Financeiro",
        "📏 Orçamento, Contas & Categorias",
        "🔑 Conta e Segurança",
        "📱 Sistema & Cache",
    ]
)

# ==============================================================================
# ABA 1: PERFIL FINANCEIRO
# ==============================================================================
with tab_perfil:
    st.subheader("Seus Dados & Preferências")
    with st.form("form_perfil_financas"):
        c1, c2 = st.columns(2)
        with c1:
            nome = st.text_input("Nome Completo*", value=cfg.get("perfil.nome", "Felipe Romani"))
            profissao = st.text_input("Profissão", value=cfg.get("perfil.profissao", ""))
        with c2:
            perfis = ["Conservador", "Moderado", "Arrojado", "Agressivo"]
            atual_p = cfg.get("perfil.perfil_de_investidor", "Arrojado")
            idx_p = perfis.index(atual_p) if atual_p in perfis else 2
            perfil_inv = st.selectbox("Perfil de Investidor", options=perfis, index=idx_p)
            moeda_base = st.selectbox(
                "Moeda Base do Patrimônio",
                options=["BRL", "USD"],
                index=0 if cfg.get("moeda_base", "BRL") == "BRL" else 1,
            )

        if st.form_submit_button("💾 Salvar Perfil", type="primary", use_container_width=True):
            salvar_config(
                {
                    "perfil.nome": nome.strip(),
                    "perfil.profissao": profissao.strip(),
                    "perfil.perfil_de_investidor": perfil_inv,
                    "moeda_base": moeda_base,
                }
            )
            st.session_state["usuario_nome"] = nome.strip()
            st.session_state["usuario_perfil_inv"] = perfil_inv
            st.success("✅ Perfil atualizado com sucesso!")

# ==============================================================================
# ABA 2: ORÇAMENTO, CONTAS & CATEGORIAS
# ==============================================================================
with tab_orc_cad:
    sub_orc, sub_contas, sub_cats = st.tabs(["📏 Orçamento Mensal", "🏦 Contas", "🏷️ Categorias"])

    with sub_orc:
        df_orc = ler_aba("orcamento")
        with st.form("form_add_orcamento", clear_on_submit=True):
            st.markdown("**Adicionar item ao Orçamento Mensal**")
            o1, o2, o3, o4 = st.columns([2, 1.4, 1.2, 1])
            with o1:
                cat_orc = st.text_input("Descrição / Categoria", placeholder="Ex: Aluguel, Supermercado, Lazer...")
            with o2:
                grupo_orc = st.selectbox("Grupo", options=["Essencial", "Estilo de vida", "Receita"])
            with o3:
                val_orc = st.number_input("Valor Mensal (R$)", min_value=0.0, step=50.0, format="%.2f")
            with o4:
                st.write("")
                add_orc = st.form_submit_button("➕ Adicionar", type="primary", use_container_width=True)

            if add_orc and cat_orc.strip() and val_orc > 0:
                obter_repo().append(
                    "orcamento",
                    [
                        {
                            "id": novo_id(),
                            "mes": "padrao",
                            "categoria": cat_orc.strip(),
                            "grupo": grupo_orc,
                            "valor": round(val_orc, 2),
                        }
                    ],
                )
                invalidar_abas("orcamento")
                st.success("✅ Item adicionado ao orçamento!")
                st.rerun()

        if not df_orc.empty:
            df_orc_ed = st.data_editor(
                df_orc[["id", "categoria", "grupo", "valor", "mes"]],
                hide_index=True,
                use_container_width=True,
                disabled=["id"],
                column_config={
                    "id": st.column_config.TextColumn("ID", width="small"),
                    "categoria": "Item / Categoria",
                    "grupo": st.column_config.SelectboxColumn("Grupo", options=["Essencial", "Estilo de vida", "Receita"]),
                    "valor": st.column_config.NumberColumn("Valor (R$)", format="R$ %.2f"),
                    "mes": "Mês ('padrao' ou YYYY-MM)",
                },
                key="ed_orc_config",
            )
            if st.button("💾 Salvar alterações no Orçamento", type="primary"):
                repo = obter_repo()
                orig = df_orc.set_index("id")
                n_alt = 0
                for _, r in df_orc_ed.iterrows():
                    oid = str(r["id"])
                    o = orig.loc[oid]
                    if (
                        str(r["categoria"]) != str(o["categoria"])
                        or str(r["grupo"]) != str(o["grupo"])
                        or float(r["valor"] or 0) != float(o["valor"] or 0)
                    ):
                        repo.update_by_key(
                            "orcamento",
                            oid,
                            {
                                "categoria": str(r["categoria"]),
                                "grupo": str(r["grupo"]),
                                "valor": round(float(r["valor"] or 0), 2),
                            },
                        )
                        n_alt += 1
                invalidar_abas("orcamento")
                st.success(f"✅ {n_alt} item(ns) do orçamento atualizado(s)!")
                st.rerun()

    with sub_contas:
        df_contas = ler_aba("contas")
        with st.form("form_add_conta", clear_on_submit=True):
            c_a, c_b, c_c, c_d = st.columns([2, 1.5, 1, 1])
            with c_a:
                nome_c = st.text_input("Nome da Conta", placeholder="Ex: Itaú, XP, Carteira...")
            with c_b:
                tipo_c = st.selectbox("Tipo", options=["banco", "corretora", "renda_fixa", "cripto", "dinheiro"])
            with c_c:
                moeda_c = st.selectbox("Moeda", options=["BRL", "USD"])
            with c_d:
                st.write("")
                if st.form_submit_button("➕ Nova Conta", type="primary", use_container_width=True) and nome_c.strip():
                    obter_repo().append(
                        "contas",
                        [
                            {
                                "id": id_deterministico("conta", nome_c.strip()),
                                "nome": nome_c.strip(),
                                "tipo": tipo_c,
                                "instituicao": nome_c.strip(),
                                "moeda": moeda_c,
                                "ativa": "S",
                            }
                        ],
                    )
                    invalidar_abas("contas")
                    st.rerun()
        st.dataframe(df_contas, hide_index=True, use_container_width=True)

    with sub_cats:
        df_cats = ler_aba("categorias")
        with st.form("form_add_cat", clear_on_submit=True):
            k_a, k_b, k_c, k_d = st.columns([2, 1.4, 1.4, 1])
            with k_a:
                nome_cat = st.text_input("Nova Categoria", placeholder="Ex: Pet Shop, Streaming...")
            with k_b:
                tipo_cat = st.selectbox("Tipo", options=["despesa", "receita", "transferencia"])
            with k_c:
                grupo_cat = st.selectbox("Grupo", options=["Essencial", "Estilo de vida", "Investimento", "Receita"])
            with k_d:
                st.write("")
                if st.form_submit_button("➕ Categoria", type="primary", use_container_width=True) and nome_cat.strip():
                    obter_repo().append(
                        "categorias",
                        [
                            {
                                "id": id_deterministico("cat", nome_cat.strip()),
                                "nome": nome_cat.strip(),
                                "tipo": tipo_cat,
                                "grupo": grupo_cat,
                                "ativa": "S",
                            }
                        ],
                    )
                    invalidar_abas("categorias")
                    st.rerun()
        st.dataframe(df_cats, hide_index=True, use_container_width=True)

# ==============================================================================
# ABA 3: CONTA E SEGURANÇA (PADRÃO NUTRIV3)
# ==============================================================================
with tab_seguranca:
    st.subheader("Segurança e Acesso")

    with st.expander("📧 Alterar E-mail de Login", expanded=False):
        with st.form("form_trocar_email"):
            st.info(f"E-mail atual: **{cfg.get('auth.email', 'não definido')}**")
            novo_email = st.text_input("Novo E-mail*")
            conf_email = st.text_input("Confirmar Novo E-mail*")
            senha_conf = st.text_input("Sua Senha Atual*", type="password")
            if st.form_submit_button("Salvar Novo E-mail", type="primary"):
                if not novo_email.strip() or novo_email.strip() != conf_email.strip():
                    st.error("Os e-mails informados não coincidem.")
                elif not verificar_hash_senha(senha_conf, cfg.get("auth.senha_hash", "")):
                    st.error("Senha atual incorreta.")
                else:
                    salvar_config({"auth.email": novo_email.strip().lower()})
                    st.session_state["usuario_email"] = novo_email.strip().lower()
                    st.success("✅ E-mail de login atualizado!")

    with st.expander("🔑 Alterar Senha de Login", expanded=False):
        with st.form("form_trocar_senha"):
            s_atual = st.text_input("Senha Atual*", type="password")
            s_nova = st.text_input("Nova Senha* (mín. 6 caracteres)", type="password")
            s_conf = st.text_input("Confirmar Nova Senha*", type="password")
            if st.form_submit_button("Alterar Senha", type="primary"):
                if len(s_nova) < 6 or s_nova != s_conf:
                    st.error("A nova senha deve ter no mínimo 6 caracteres e coincidir com a confirmação.")
                elif not verificar_hash_senha(s_atual, cfg.get("auth.senha_hash", "")):
                    st.error("Senha atual incorreta.")
                else:
                    salvar_config({"auth.senha_hash": gerar_hash_senha(s_nova)})
                    st.success("✅ Senha alterada com sucesso!")

    with st.expander("📱 Configurar PIN Rápido para iPhone", expanded=True):
        st.caption("O PIN permite abrir o app na Tela Inicial do iPhone sem precisar digitar e-mail e senha completa.")
        with st.form("form_trocar_pin"):
            pin_novo = st.text_input("Novo PIN (4 a 8 dígitos)", type="password")
            s_para_pin = st.text_input("Sua Senha Atual (para autorizar)*", type="password")
            c_p1, c_p2 = st.columns(2)
            with c_p1:
                salvar_pin_btn = st.form_submit_button("💾 Salvar PIN", type="primary", use_container_width=True)
            with c_p2:
                remover_pin_btn = st.form_submit_button("🗑️ Desativar PIN", use_container_width=True)

            if salvar_pin_btn:
                if len(pin_novo.strip()) < 4:
                    st.error("O PIN deve ter pelo menos 4 caracteres.")
                elif not verificar_hash_senha(s_para_pin, cfg.get("auth.senha_hash", "")):
                    st.error("Senha atual incorreta.")
                else:
                    salvar_config({"auth.pin_hash": gerar_hash_senha(pin_novo.strip())})
                    st.success("✅ PIN Rápido ativado!")
            elif remover_pin_btn:
                if not verificar_hash_senha(s_para_pin, cfg.get("auth.senha_hash", "")):
                    st.error("Senha atual incorreta.")
                else:
                    salvar_config({"auth.pin_hash": ""})
                    st.success("✅ PIN Rápido desativado!")

# ==============================================================================
# ABA 4: SISTEMA & CACHE
# ==============================================================================
with tab_sistema:
    st.subheader("🔄 Cache & Diagnóstico da Planilha V2")

    if st.button("🧹 Limpar Cache do Aplicativo", type="primary", use_container_width=True):
        invalidar_abas()
        st.cache_data.clear()
        st.success("✅ Cache limpo! Todos os dados serão recarregados da planilha.")
        st.rerun()

    st.markdown("---")
    st.markdown("#### 📊 Status das Abas V2 no Google Sheets")
    resumo_abas = []
    for nome_aba in schema.ALL_TABS:
        try:
            df_a = ler_aba(nome_aba)
            resumo_abas.append({"Aba": nome_aba, "Registros": len(df_a), "Colunas": ", ".join(df_a.columns)})
        except Exception as exc:
            resumo_abas.append({"Aba": nome_aba, "Registros": -1, "Colunas": f"Erro: {exc}"})
    st.dataframe(resumo_abas, hide_index=True, use_container_width=True)
