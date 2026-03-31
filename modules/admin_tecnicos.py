import streamlit as st
import hashlib
from datetime import datetime

def hash_senha(senha):
    return hashlib.sha256(senha.encode()).hexdigest()

def render_admin_tecnicos(usuarios_collection):
    st.header("🔧 Gerenciar Técnicos")
    st.markdown("Cadastre e gerencie técnicos que atuam em campo.")

    # --- Cadastro de novo técnico ---
    with st.expander("➕ Cadastrar Novo Técnico", expanded=False):
        col1, col2 = st.columns(2)
        with col1:
            nome_exibicao = st.text_input("Nome do Técnico", placeholder="Ex: Jair Silva", key="tec_nome")
            login = st.text_input("Login (usuário)", placeholder="ex: jair_tec", key="tec_login")
        with col2:
            senha = st.text_input("Senha", type="password", key="tec_senha")
            senha_confirma = st.text_input("Confirmar Senha", type="password", key="tec_senha_confirma")
        
        st.divider()
        st.subheader("📞 Contato e Veículo")
        telefone_tecnico = st.text_input("Telefone do Técnico", placeholder="(00) 90000-0000", key="tec_telefone")
        veiculo = st.text_input("Veículo (opcional)", placeholder="Ex: Gol 2020 - ABC1D23", key="tec_veiculo")

        if st.button("✅ Cadastrar Técnico"):
            if not all([nome_exibicao, login, senha, telefone_tecnico]):
                st.error("⚠️ Nome, Login, Senha e Telefone são obrigatórios.")
            elif senha != senha_confirma:
                st.error("❌ As senhas não coincidem.")
            elif len(senha) < 6:
                st.error("⚠️ A senha deve ter pelo menos 6 caracteres.")
            else:
                if usuarios_collection.find_one({"login": login}):
                    st.error("❌ Este login já está em uso.")
                else:
                    usuario_data = {
                        "login": login,
                        "senha_hash": hash_senha(senha),
                        "perfil": "tecnico",
                        "nome_exibicao": nome_exibicao.strip(),
                        "telefone_tecnico": telefone_tecnico.strip(),
                        "veiculo": veiculo.strip() if veiculo else None,
                        "data_cadastro": datetime.now()
                    }
                    try:
                        usuarios_collection.insert_one(usuario_data)
                        st.success(f"✅ Técnico **{nome_exibicao}** cadastrado com sucesso!")
                        st.rerun()
                    except Exception as e:
                        st.error(f"❌ Erro ao salvar: {e}")

    # --- Listagem de técnicos ---
    st.divider()
    st.subheader("📋 Lista de Técnicos Cadastrados")
    tecnicos = list(usuarios_collection.find({"perfil": "tecnico"}).sort("data_cadastro", -1))

    if tecnicos:
        for tec in tecnicos:
            with st.container(border=True):
                col1, col2 = st.columns([3, 1])
                with col1:
                    st.write(f"**{tec.get('nome_exibicao', '—')}**")
                    st.caption(f"Login: `{tec['login']}`")
                    st.caption(f"Telefone: {tec.get('telefone_tecnico', 'N/A')}")
                    st.caption(f"Veículo: {tec.get('veiculo', 'N/A')}")
                with col2:
                    # Botões de ação
                    if st.button("✏️ Editar", key=f"edit_tec_{tec['_id']}"):
                        st.session_state["editando_tecnico"] = tec
                        st.rerun()
                    if st.button("🗑️ Excluir", key=f"delete_tec_{tec['_id']}"):
                        # Armazena o ID do técnico a ser excluído
                        st.session_state["tec_a_excluir"] = str(tec["_id"])
                        st.session_state["nome_tec_a_excluir"] = tec["nome_exibicao"]
                        st.rerun()

            # Mostra mensagem de confirmação logo abaixo do técnico, se aplicável
            if st.session_state.get("tec_a_excluir") == str(tec["_id"]):
                with st.container():
                    st.warning(
                        f"⚠️ Confirmar exclusão de **{tec['nome_exibicao']}**?\n\n"
                        "Essa ação não pode ser desfeita.",
                        icon="🗑️"
                    )
                    col_confirma, col_cancela = st.columns([1, 1])
                    with col_confirma:
                        if st.button("✅ Sim, excluir", key=f"confirm_delete_{tec['_id']}"):
                            try:
                                from bson import ObjectId
                                usuarios_collection.delete_one({"_id": ObjectId(tec["_id"])})
                                st.success(f"✅ Técnico **{tec['nome_exibicao']}** excluído com sucesso!")
                                # Limpa o estado
                                del st.session_state["tec_a_excluir"]
                                del st.session_state["nome_tec_a_excluir"]
                                st.rerun()
                            except Exception as e:
                                st.error(f"❌ Erro ao excluir: {e}")
                    with col_cancela:
                        if st.button("❌ Cancelar", key=f"cancel_delete_{tec['_id']}"):
                            del st.session_state["tec_a_excluir"]
                            del st.session_state["nome_tec_a_excluir"]
                            st.rerun()
                st.divider()  # Separa visualmente

    else:
        st.info("Nenhum técnico cadastrado ainda.")

    # --- Edição de técnico (simples) ---
    if "editando_tecnico" in st.session_state:
        tec_edit = st.session_state["editando_tecnico"]
        st.divider()
        st.subheader(f"✏️ Editar Técnico: {tec_edit['nome_exibicao']}")
        nome_edit = st.text_input("Nome", value=tec_edit.get("nome_exibicao", ""), key="edit_nome_tec")
        telefone_edit = st.text_input("Telefone", value=tec_edit.get("telefone_tecnico", ""), key="edit_tel_tec")
        veiculo_edit = st.text_input("Veículo", value=tec_edit.get("veiculo", ""), key="edit_veic_tec")
        
        col_salvar, col_cancelar = st.columns([1, 1])
        with col_salvar:
            if st.button("💾 Salvar", key="salvar_edicao_tec"):
                try:
                    usuarios_collection.update_one(
                        {"_id": tec_edit["_id"]},
                        {"$set": {
                            "nome_exibicao": nome_edit,
                            "telefone_tecnico": telefone_edit,
                            "veiculo": veiculo_edit if veiculo_edit else None
                        }}
                    )
                    st.success("✅ Técnico atualizado!")
                    del st.session_state["editando_tecnico"]
                    st.rerun()
                except Exception as e:
                    st.error(f"❌ Erro ao salvar: {e}")
        with col_cancelar:
            if st.button("❌ Cancelar edição", key="cancelar_edicao_tec"):
                del st.session_state["editando_tecnico"]
                st.rerun()
