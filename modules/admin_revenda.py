# modules/admin_revenda.py
import streamlit as st
import hashlib
import random
import string
from datetime import datetime

def gerar_codigo_revenda():
    """Gera código no formato: REV + 6 números + 3 letras maiúsculas."""
    numeros = ''.join(random.choices(string.digits, k=6))
    letras = ''.join(random.choices(string.ascii_uppercase, k=3))
    return f"REV{numeros}{letras}"

def hash_senha(senha):
    return hashlib.sha256(senha.encode()).hexdigest()

def determinar_status_revenda(cliente):
    """Status para painel administrativo."""
    status_agendamento = cliente.get("status_agendamento")
    
    if status_agendamento == "ativado":
        return "Ativado"
    elif status_agendamento == "cancelado":
        return "Cancelado"
    elif status_agendamento == "agendado":
        return "Agendado"
    elif cliente.get("reagendado_para") and status_agendamento not in ["ativado", "cancelado"]:
        return "Reagendado"
    elif cliente.get("em_tratamento") is True:
        return "Em tratamento"
    elif cliente.get("seguiu_ativacao") == "Sim":
        return "Seguiu para ativação"
    else:
        return "Indicado"

def render_admin_revenda(usuarios_collection, clientes_collection):
    st.header("🏪 Gerenciar Revendas")
    st.markdown("Cadastre e gerencie revendas com acesso ao sistema de indicações e acompanhamento.")

    # --- Cadastro de nova revenda ---
    with st.expander("➕ Cadastrar Nova Revenda", expanded=False):
        col1, col2 = st.columns(2)
        with col1:
            nome_exibicao = st.text_input("Nome de Exibição", placeholder="Ex: Revenda Silva", key="rev_nome")
            login = st.text_input("Login (usuário)", placeholder="Ex: revenda_silva", key="rev_login")
            telefone = st.text_input("Telefone", placeholder="(00) 90000-0000", key="rev_telefone")
            email = st.text_input("Email", placeholder="exemplo@dominio.com", key="rev_email")
            nome_loja = st.text_input("Nome da Loja", placeholder="Ex: Loja do João", key="rev_loja")
        with col2:
            senha = st.text_input("Senha", type="password", key="rev_senha")
            senha_confirma = st.text_input("Confirmar Senha", type="password", key="rev_senha_confirma")
            tipo_chave_pix = st.selectbox(
                "Tipo de Chave Pix",
                ["Selecione...", "CPF", "E-mail", "Celular", "Chave Aleatória"],
                index=0,
                key="rev_tipo_chave_pix"
            )
            chave_pix = st.text_input("Chave Pix", placeholder="Ex: 123.456.789-00", key="rev_chave_pix")
            endereco_loja = st.text_area("Endereço da Loja", placeholder="Rua Principal, 123 - Centro", key="rev_endereco")

        responsavel_cadastro = st.selectbox(
            "Responsável pelo Cadastro",
            options=["Selecione...", "Diego Roberto", "Sabrina"],
            index=0,
            key="rev_responsavel"
        )

        if st.button("✅ Cadastrar Revenda"):
            campos_obrigatorios = [
                nome_exibicao.strip(), login.strip(), senha.strip(), telefone.strip(),
                email.strip(), nome_loja.strip(), endereco_loja.strip(),
                tipo_chave_pix, chave_pix.strip(), responsavel_cadastro
            ]
            if not all(campo for campo in campos_obrigatorios):
                st.error("⚠️ Todos os campos são obrigatórios.")
            elif responsavel_cadastro == "Selecione...":
                st.error("⚠️ Selecione um responsável válido.")
            elif tipo_chave_pix == "Selecione...":
                st.error("⚠️ Selecione um tipo de chave Pix válido.")
            elif senha != senha_confirma:
                st.error("❌ As senhas não coincidem.")
            elif len(senha) < 6:
                st.error("⚠️ A senha deve ter pelo menos 6 caracteres.")
            else:
                if usuarios_collection.find_one({"login": login}):
                    st.error("❌ Este login já está em uso.")
                else:
                    codigo = gerar_codigo_revenda()
                    usuario_data = {
                        "login": login.strip(),
                        "senha_hash": hash_senha(senha),
                        "perfil": "revenda",
                        "nome_exibicao": nome_exibicao.strip(),
                        "codigo_revenda": codigo,
                        "data_cadastro": datetime.now(),
                        "telefone": telefone.strip(),
                        "email": email.strip(),
                        "nome_loja": nome_loja.strip(),
                        "endereco_loja": endereco_loja.strip(),
                        "tipo_chave_pix": tipo_chave_pix.strip(),
                        "chave_pix": chave_pix.strip(),
                        "responsavel_cadastro": responsavel_cadastro.strip()
                    }
                    try:
                        usuarios_collection.insert_one(usuario_data)
                        st.success(f"✅ Revenda **{nome_exibicao}** cadastrada com sucesso!")
                        st.code(f"Código da revenda: `{codigo}`", language="text")
                        st.rerun()
                    except Exception as e:
                        st.error(f"❌ Erro ao salvar: {e}")

    # --- Listagem de revendas ---
    st.divider()
    st.subheader("📋 Lista de Revendas Cadastradas")
    revendas = list(usuarios_collection.find({"perfil": "revenda"}).sort("data_cadastro", -1))

    if revendas:
        for rev in revendas:
            with st.container(border=True):
                col1, col2, col3 = st.columns([2, 1.5, 1])
                with col1:
                    st.write(f"**{rev.get('nome_exibicao', '—')}**")
                    st.caption(f"Login: `{rev['login']}`")
                    st.caption(f"Telefone: {rev.get('telefone', 'N/A')}")
                    st.caption(f"Email: {rev.get('email', 'N/A')}")
                    st.caption(f"Loja: {rev.get('nome_loja', 'N/A')}")
                    st.caption(f"Chave Pix ({rev.get('tipo_chave_pix', 'N/A')}): {rev.get('chave_pix', 'N/A')}")
                    st.caption(f"Responsável: {rev.get('responsavel_cadastro', '—')}")
                with col2:
                    codigo = rev.get("codigo_revenda", "REV??????")
                    st.code(codigo, language="text")
                with col3:
                    if st.button("✏️ Editar", key=f"edit_rev_{rev['_id']}"):
                        st.session_state["editando_revenda"] = rev
                        st.rerun()
                    if st.button("🗑️ Excluir", key=f"delete_rev_{rev['_id']}"):
                        st.session_state[f"confirm_delete_rev_{rev['_id']}"] = True

                # Confirmação de exclusão
                if st.session_state.get(f"confirm_delete_rev_{rev['_id']}", False):
                    st.warning("⚠️ Confirmar exclusão desta revenda?")
                    if st.checkbox("Sim, tenho certeza", key=f"check_del_rev_{rev['_id']}"):
                        if st.button("✅ Confirmar", key=f"btn_del_rev_{rev['_id']}"):
                            try:
                                usuarios_collection.delete_one({"_id": rev["_id"]})
                                st.success(f"✅ Revenda {rev['nome_exibicao']} excluída!")
                                del st.session_state[f"confirm_delete_rev_{rev['_id']}"]
                                st.rerun()
                            except Exception as e:
                                st.error(f"❌ Erro: {e}")
    else:
        st.info("Nenhuma revenda cadastrada ainda.")

    # --- Edição de revenda ---
    if "editando_revenda" in st.session_state:
        rev_edit = st.session_state["editando_revenda"]
        st.divider()
        st.subheader(f"✏️ Editar Revenda: {rev_edit['nome_exibicao']}")

        col1, col2 = st.columns(2)
        with col1:
            nome_edit = st.text_input("Nome de Exibição", value=rev_edit.get("nome_exibicao", ""), key="rev_edit_nome")
            login_edit = st.text_input("Login", value=rev_edit.get("login", ""), key="rev_edit_login")
            telefone_edit = st.text_input("Telefone", value=rev_edit.get("telefone", ""), key="rev_edit_tel")
            email_edit = st.text_input("Email", value=rev_edit.get("email", ""), key="rev_edit_email")
            nome_loja_edit = st.text_input("Nome da Loja", value=rev_edit.get("nome_loja", ""), key="rev_edit_loja")
        with col2:
            senha_edit = st.text_input("Nova Senha (deixe em branco para manter)", type="password", key="rev_edit_senha")
            senha_conf_edit = st.text_input("Confirmar Nova Senha", type="password", key="rev_edit_senha_conf")
            tipo_chave_pix_edit = st.selectbox(
                "Tipo de Chave Pix",
                ["Selecione...", "CPF", "E-mail", "Celular", "Chave Aleatória"],
                index=["Selecione...", "CPF", "E-mail", "Celular", "Chave Aleatória"].index(
                    rev_edit.get("tipo_chave_pix", "Selecione...")
                ),
                key="rev_edit_tipo_chave_pix"
            )
            chave_pix_edit = st.text_input("Chave Pix", value=rev_edit.get("chave_pix", ""), key="rev_edit_chave_pix")
            endereco_loja_edit = st.text_area("Endereço da Loja", value=rev_edit.get("endereco_loja", ""), key="rev_edit_endereco")

        responsavel_edit = st.selectbox(
            "Responsável pelo Cadastro",
            options=["Selecione...", "Diego Roberto", "Sabrina"],
            index=["Selecione...", "Diego Roberto", "Sabrina"].index(
                rev_edit.get("responsavel_cadastro", "Selecione...")
            ),
            key="rev_edit_responsavel"
        )

        if st.button("💾 Salvar Alterações", key="salvar_rev_edit"):
            if not all([
                nome_edit.strip(), login_edit.strip(), telefone_edit.strip(),
                email_edit.strip(), nome_loja_edit.strip(), endereco_loja_edit.strip(),
                tipo_chave_pix_edit, chave_pix_edit.strip()
            ]):
                st.error("⚠️ Todos os campos, exceto senha, são obrigatórios.")
            elif responsavel_edit == "Selecione...":
                st.error("⚠️ Selecione um responsável válido.")
            elif tipo_chave_pix_edit == "Selecione...":
                st.error("⚠️ Selecione um tipo de chave Pix válido.")
            else:
                update_data = {
                    "nome_exibicao": nome_edit.strip(),
                    "login": login_edit.strip(),
                    "telefone": telefone_edit.strip(),
                    "email": email_edit.strip(),
                    "nome_loja": nome_loja_edit.strip(),
                    "endereco_loja": endereco_loja_edit.strip(),
                    "tipo_chave_pix": tipo_chave_pix_edit.strip(),
                    "chave_pix": chave_pix_edit.strip(),
                    "responsavel_cadastro": responsavel_edit.strip()
                }
                if senha_edit:
                    if senha_edit != senha_conf_edit:
                        st.error("❌ Senhas não coincidem.")
                    elif len(senha_edit) < 6:
                        st.error("⚠️ Senha deve ter ≥6 caracteres.")
                    else:
                        update_data["senha_hash"] = hash_senha(senha_edit)

                try:
                    usuarios_collection.update_one({"_id": rev_edit["_id"]}, {"$set": update_data})
                    st.success("✅ Revenda atualizada!")
                    del st.session_state["editando_revenda"]
                    st.rerun()
                except Exception as e:
                    st.error(f"❌ Erro: {e}")

        if st.button("❌ Cancelar", key="cancelar_rev_edit"):
            del st.session_state["editando_revenda"]
            st.rerun()

    # --- Controle de Bônus/Comissões ---
    st.divider()
    st.subheader("💰 Controle de Bônus das Revendas")

    pipeline = [
        {"$match": {"indicado_por.tipo": "revenda"}},
        {"$lookup": {
            "from": "usuarios",
            "localField": "indicado_por.codigo",
            "foreignField": "codigo_revenda",
            "as": "revenda"
        }},
        {"$unwind": "$revenda"},
        {"$sort": {"data_cadastro": -1}}
    ]
    todas_indicacoes = list(clientes_collection.aggregate(pipeline))

    if not todas_indicacoes:
        st.info("Nenhuma indicação de revenda encontrada.")
    else:
        # Resumo geral
        total_indicacoes = len(todas_indicacoes)
        total_ativados = sum(1 for i in todas_indicacoes if i.get("status_agendamento") == "ativado")
        total_pagos = sum(1 for i in todas_indicacoes if i.get("bonus_enviado"))
        total_confirmados = sum(1 for i in todas_indicacoes if i.get("bonus_confirmado"))

        col1, col2, col3, col4 = st.columns(4)
        col1.metric("Total Indicações", total_indicacoes)
        col2.metric("Ativados", total_ativados)
        col3.metric("Bônus Pagos", total_pagos)
        col4.metric("Bônus Confirmados", total_confirmados)

        st.divider()

        # Filtros
        col_filtro1, col_filtro2 = st.columns(2)
        with col_filtro1:
            filtro_revenda = st.selectbox(
                "Filtrar por revenda:",
                ["Todas"] + sorted(list(set(i["revenda"]["nome_exibicao"] for i in todas_indicacoes))),
                key="filtro_revenda_bonus"
            )
        with col_filtro2:
            filtro_status = st.selectbox(
                "Filtrar por status:",
                ["Todos", "Indicado", "Em tratamento", "Seguiu para ativação", "Agendado", "Ativado", "Cancelado"],
                key="filtro_status_bonus"
            )

        indicacoes_filtradas = todas_indicacoes
        if filtro_revenda != "Todas":
            indicacoes_filtradas = [i for i in indicacoes_filtradas if i["revenda"]["nome_exibicao"] == filtro_revenda]
        if filtro_status != "Todos":
            indicacoes_filtradas = [i for i in indicacoes_filtradas if determinar_status_revenda(i) == filtro_status]

        for ind in indicacoes_filtradas:
            nome_cliente = ind['nome_completo']
            nome_rev = ind['revenda']['nome_exibicao']
            codigo_rev = ind['revenda']['codigo_revenda']
            status = determinar_status_revenda(ind)
            bonus_enviado = ind.get("bonus_enviado", False)
            bonus_confirmado = ind.get("bonus_confirmado", False)
            
            status_bonus = "✅ Confirmado" if bonus_confirmado else "⏳ Enviado" if bonus_enviado else "❌ Pendente"
            
            with st.expander(f"{nome_cliente} → {nome_rev} ({status} | Bônus: {status_bonus})", expanded=False):
                col1, col2 = st.columns([3, 1])
                
                with col1:
                    st.write(f"**Revenda:** {nome_rev} (`{codigo_rev}`)")
                    st.write(f"**Status do cliente:** `{status}`")
                    st.write(f"**Data da indicação:** {ind.get('data_cadastro', '—')}")
                    st.write(f"**Plano:** {ind.get('plano_escolhido', 'N/A')}")
                    st.write(f"**Telefone cliente:** {ind['celular']}")
                    
                    if ind.get("data_ativacao"):
                        st.write(f"**Data de ativação:** {ind['data_ativacao']}")
                
                with col2:
                    if status == "Ativado":
                        if not bonus_enviado:
                            if st.button("📤 Marcar Bônus como Enviado", key=f"env_bonus_{ind['_id']}"):
                                clientes_collection.update_one(
                                    {"_id": ind["_id"]},
                                    {"$set": {
                                        "bonus_enviado": True,
                                        "data_bonus_enviado": datetime.now()
                                    }}
                                )
                                st.success("✅ Bônus marcado como enviado!")
                                st.rerun()
                        else:
                            st.success("📤 Bônus enviado")
                            if not bonus_confirmado:
                                st.info("⏳ Aguardando confirmação da revenda")
                            else:
                                st.success("✅ Confirmado pela revenda")
                    else:
                        st.info("Bônus disponível apenas após ativação")
