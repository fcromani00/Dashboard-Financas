"""Módulo de autenticação e gerenciamento de sessão do Finanças V2.

Inspirado no padrão do NutriV3 (`core/auth.py`), com melhorias para uso pessoal e no iPhone:
- Bloqueio centralizado no `app.py` (nenhuma página ou menu aparece antes do login);
- Senha e PIN armazenados com hash PBKDF2-HMAC-SHA256 na aba `config` da planilha;
- Fluxo de Primeiro Acesso caso nenhuma senha tenha sido cadastrada ainda;
- Opção de login rápido por PIN (ideal para abrir na Tela Inicial do iPhone).
"""

from __future__ import annotations

import hashlib
import hmac
import secrets

import streamlit as st

from core.state import mapa_config, salvar_config

ITERACOES_PBKDF2 = 120_000


def gerar_hash_senha(senha: str) -> str:
    """Gera hash PBKDF2-HMAC-SHA256 com salt aleatório."""
    salt = secrets.token_hex(16)
    dk = hashlib.pbkdf2_hmac("sha256", senha.encode("utf-8"), salt.encode("utf-8"), ITERACOES_PBKDF2)
    return f"pbkdf2_sha256${salt}${dk.hex()}"


def verificar_hash_senha(senha_digitada: str, hash_salvo: str) -> bool:
    """Verifica senha ou PIN contra o hash salvo em tempo constante."""
    if not senha_digitada or not hash_salvo:
        return False
    partes = str(hash_salvo).split("$")
    if len(partes) != 3 or partes[0] != "pbkdf2_sha256":
        return False
    _, salt, hex_esperado = partes
    dk = hashlib.pbkdf2_hmac("sha256", senha_digitada.encode("utf-8"), salt.encode("utf-8"), ITERACOES_PBKDF2)
    return hmac.compare_digest(dk.hex(), hex_esperado)


def check_password() -> bool:
    """Verifica se o usuário está autenticado; exibe tela de primeiro acesso ou login se necessário.
    Suporta login automático no iPhone via parâmetro de URL `?pin=SEU_PIN`.
    """
    if st.session_state.get("autenticado", False):
        return True

    try:
        cfg = mapa_config()
    except Exception as exc:
        st.error(f"Erro ao conectar com a planilha para autenticação: {exc}")
        return False

    senha_hash = cfg.get("auth.senha_hash", "")
    if not senha_hash:
        _primeiro_acesso_form(cfg)
        return False

    # Login rápido automático via URL (?pin=SEU_PIN) para atalho/favorito na Tela Inicial do iPhone
    pin_url = str(st.query_params.get("pin", "") or "").strip()
    if pin_url and cfg.get("auth.pin_hash", ""):
        if verificar_hash_senha(pin_url, cfg.get("auth.pin_hash", "")):
            _iniciar_sessao(
                cfg.get("perfil.nome", "Felipe Romani"),
                cfg.get("auth.email", ""),
                cfg.get("perfil.perfil_de_investidor", ""),
            )
            return True

    _login_form(cfg)
    if st.session_state.get("login_erro", False):
        st.error("❌ Credenciais incorretas!")
    return False


def _primeiro_acesso_form(cfg: dict[str, str]) -> None:
    col1, col2, col3 = st.columns([1, 1.8, 1])
    with col2:
        st.markdown("## 💰 Finanças V2")
        st.info("🔐 **Primeiro Acesso:** defina seu e-mail, senha e um PIN opcional para entrar rápido pelo iPhone.")

        with st.form("form_primeiro_acesso"):
            nome_padrao = cfg.get("perfil.nome", "Felipe Romani")
            email = st.text_input("📧 Seu E-mail de Login*", placeholder="seu@email.com")
            senha = st.text_input("🔒 Nova Senha* (mín. 6 caracteres)", type="password")
            confirmar = st.text_input("🔒 Confirmar Senha*", type="password")
            pin = st.text_input(
                "📱 PIN Rápido para iPhone (opcional, 4 a 8 dígitos)",
                type="password",
                help="Permite entrar no celular digitando apenas o PIN.",
            )
            submit = st.form_submit_button("Salvar e Entrar", type="primary", use_container_width=True)

            if submit:
                if not email.strip() or len(senha) < 6:
                    st.error("Informe um e-mail válido e uma senha com pelo menos 6 caracteres.")
                elif senha != confirmar:
                    st.error("As senhas não coincidem.")
                elif pin and len(pin.strip()) < 4:
                    st.error("Se informar um PIN, use pelo menos 4 caracteres.")
                else:
                    novos_dados = {
                        "auth.email": email.strip().lower(),
                        "auth.senha_hash": gerar_hash_senha(senha),
                    }
                    if pin.strip():
                        novos_dados["auth.pin_hash"] = gerar_hash_senha(pin.strip())
                    salvar_config(novos_dados)
                    _iniciar_sessao(nome_padrao, email.strip().lower(), cfg.get("perfil.perfil_de_investidor", ""))
                    st.rerun()


def _login_form(cfg: dict[str, str]) -> None:
    col1, col2, col3 = st.columns([1, 1.6, 1])
    with col2:
        st.markdown("## 💰 Finanças Felipe")
        st.caption("Acesse seu painel financeiro pessoal")

        tem_pin = bool(cfg.get("auth.pin_hash", ""))
        if tem_pin:
            aba_pin, aba_senha = st.tabs(["📱 PIN Rápido", "🔑 E-mail e Senha"])
        else:
            aba_pin = None
            aba_senha = st.container()

        if aba_pin is not None:
            with aba_pin:
                with st.form("login_pin_form"):
                    pin_in = st.text_input("🔒 Digite seu PIN", type="password", placeholder="••••")
                    sub_pin = st.form_submit_button("Entrar com PIN", type="primary", use_container_width=True)
                    if sub_pin:
                        if verificar_hash_senha(pin_in.strip(), cfg.get("auth.pin_hash", "")):
                            _iniciar_sessao(
                                cfg.get("perfil.nome", "Felipe Romani"),
                                cfg.get("auth.email", ""),
                                cfg.get("perfil.perfil_de_investidor", ""),
                            )
                            st.rerun()
                        else:
                            st.session_state["login_erro"] = True
                            st.rerun()

        with aba_senha:
            with st.form("login_email_form"):
                email_in = st.text_input("📧 E-mail", placeholder="seu@email.com")
                senha_in = st.text_input("🔒 Senha", type="password", placeholder="Sua senha")
                sub_email = st.form_submit_button("Entrar", type="primary", use_container_width=True)
                if sub_email:
                    email_ok = email_in.strip().lower() == cfg.get("auth.email", "").strip().lower()
                    senha_ok = verificar_hash_senha(senha_in, cfg.get("auth.senha_hash", ""))
                    if email_ok and senha_ok:
                        _iniciar_sessao(
                            cfg.get("perfil.nome", "Felipe Romani"),
                            cfg.get("auth.email", ""),
                            cfg.get("perfil.perfil_de_investidor", ""),
                        )
                        st.rerun()
                    else:
                        st.session_state["login_erro"] = True
                        st.rerun()


def _iniciar_sessao(nome: str, email: str, perfil_inv: str) -> None:
    st.session_state["autenticado"] = True
    st.session_state["login_erro"] = False
    st.session_state["usuario_nome"] = nome
    st.session_state["usuario_email"] = email
    st.session_state["usuario_perfil_inv"] = perfil_inv


def logout() -> None:
    """Encerra a sessão autenticada."""
    for chave in ("autenticado", "login_erro", "usuario_nome", "usuario_email", "usuario_perfil_inv"):
        st.session_state.pop(chave, None)
    st.rerun()


def sidebar_usuario() -> None:
    """Exibe informações do usuário logado e botão de Sair na sidebar."""
    with st.sidebar:
        st.markdown("---")
        nome = st.session_state.get("usuario_nome", "Felipe Romani")
        email = st.session_state.get("usuario_email", "")
        perfil = st.session_state.get("usuario_perfil_inv", "")

        st.markdown(f"👤 **{nome}**")
        if email:
            st.caption(f"📧 {email}")
        if perfil:
            st.caption(f"📈 Perfil: {perfil}")

        if st.button("🚪 Sair", use_container_width=True):
            logout()
