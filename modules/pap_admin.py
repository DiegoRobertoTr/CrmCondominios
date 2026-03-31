# modules/pap_admin.py
import streamlit as st
import hashlib
from datetime import datetime

def hash_senha(senha):
    return hashlib.sha256(senha.encode()).hexdigest()

def render_pap_admin(usuarios_collection, clientes_collection):
    st.header("🚪 Gerenciar Usuários PaP (Porta a Porta)")
    st.markdown("Cadastre e gerencie usuários com acesso limitado ao cadastro completo.")

    # --- Cadastro de novo usuário PaP ---
    with st.expander("➕ Cadastrar Novo Usuário PaP", expanded=False):
        col1, col2 = st.columns(2)
        with col1:
            nome_exibicao = st.text_input("Nome de Exibição", placeholder="Ex: João Silva", key="pap_nome")
            login = st.text_input("Login (usuário)", placeholder="Ex: joao_pap", key="pap_login")
            telefone = st.text_input("Telefone", placeholder="(00) 90000-0000", key="pap_telefone")
            email = st.text_input("Email", placeholder="exemplo@dominio.com", key="pap_email")
        with col2:
            senha = st.text_input("Senha", type="password", key="pap_senha")
            senha_confirma = st.text_input("Confirmar Senha", type="password", key="pap_senha_confirma")
            lideranca = st.selectbox(
                "Liderança",
                options=["Selecione...", "Diego Roberto", "Sabrina"],
                index=0,
                key="pap_lideranca"
            )
            tipo_chave_pix = st.selectbox(
                "Tipo de Chave Pix",
                ["Selecione...", "CPF", "E-mail", "Celular", "Chave Aleatória"],
                index=0,
                key="pap_tipo_chave_pix"
            )
            chave_pix = st.text_input("Chave Pix", placeholder="Ex: 123.456.789-00", key="pap_chave_pix")

        if st.button("✅ Cadastrar Usuário PaP"):
            campos_obrigatorios = [
                nome_exibicao.strip(),
                login.strip(),
                senha.strip(),
                telefone.strip(),
                email.strip(),
                lideranca,
                tipo_chave_pix,
                chave_pix.strip()
            ]
            if not all(campo for campo in campos_obrigatorios):
                st.error("⚠️ Todos os campos são obrigatórios.")
            elif lideranca == "Selecione...":
                st.error("⚠️ Selecione uma liderança válida.")
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
                    usuario_data = {
                        "login": login.strip(),
                        "senha_hash": hash_senha(senha),
                        "perfil": "pap",
                        "nome_exibicao": nome_exibicao.strip(),
                        "data_cadastro": datetime.now(),
                        "telefone": telefone.strip(),
                        "email": email.strip(),
                        "lideranca": lideranca.strip(),
                        "tipo_chave_pix": tipo_chave_pix.strip(),
                        "chave_pix": chave_pix.strip()
                    }
                    try:
                        usuarios_collection.insert_one(usuario_data)
                        st.success(f"✅ Usuário **{nome_exibicao}** cadastrado com sucesso!")
                        st.rerun()
                    except Exception as e:
                        st.error(f"❌ Erro ao salvar: {e}")

    # --- Listagem de usuários PaP ---
    st.divider()
    st.subheader("📋 Lista de Usuários PaP Cadastrados")
    usuarios_pap = list(usuarios_collection.find({"perfil": "pap"}).sort("data_cadastro", -1))

    if usuarios_pap:
        for user in usuarios_pap:
            with st.container(border=True):
                col1, col2 = st.columns([2, 1])
                with col1:
                    st.write(f"**{user.get('nome_exibicao', '—')}**")
                    st.caption(f"Login: `{user['login']}`")
                    st.caption(f"Telefone: {user.get('telefone', 'N/A')}")
                    st.caption(f"Email: {user.get('email', 'N/A')}")
                    st.caption(f"Liderança: {user.get('lideranca', '—')}")
                    st.caption(f"Chave Pix ({user.get('tipo_chave_pix', 'N/A')}): {user.get('chave_pix', 'N/A')}")
                with col2:
                    if st.button("✏️ Editar", key=f"edit_pap_{user['_id']}"):
                        st.session_state["editando_pap"] = user
                        st.rerun()
                    if st.button("🗑️ Excluir", key=f"delete_pap_{user['_id']}"):
                        st.session_state[f"confirm_delete_pap_{user['_id']}"] = True

                # Confirmação de exclusão
                if st.session_state.get(f"confirm_delete_pap_{user['_id']}", False):
                    st.warning("⚠️ Confirmar exclusão deste usuário PaP?")
                    if st.checkbox("Sim, tenho certeza", key=f"check_del_pap_{user['_id']}"):
                        if st.button("✅ Confirmar", key=f"btn_del_pap_{user['_id']}"):
                            try:
                                usuarios_collection.delete_one({"_id": user["_id"]})
                                st.success(f"✅ Usuário {user['nome_exibicao']} excluído!")
                                del st.session_state[f"confirm_delete_pap_{user['_id']}"]
                                st.rerun()
                            except Exception as e:
                                st.error(f"❌ Erro: {e}")

    else:
        st.info("Nenhum usuário PaP cadastrado ainda.")

    # --- Edição de usuário PaP ---
    if "editando_pap" in st.session_state:
        user_edit = st.session_state["editando_pap"]
        st.divider()
        st.subheader(f"✏️ Editar Usuário: {user_edit['nome_exibicao']}")

        col1, col2 = st.columns(2)
        with col1:
            nome_edit = st.text_input("Nome de Exibição", value=user_edit.get("nome_exibicao", ""), key="pap_edit_nome")
            login_edit = st.text_input("Login", value=user_edit.get("login", ""), key="pap_edit_login")
            telefone_edit = st.text_input("Telefone", value=user_edit.get("telefone", ""), key="pap_edit_tel")
            email_edit = st.text_input("Email", value=user_edit.get("email", ""), key="pap_edit_email")
        with col2:
            senha_edit = st.text_input("Nova Senha (deixe em branco para manter)", type="password", key="pap_edit_senha")
            senha_conf_edit = st.text_input("Confirmar Nova Senha", type="password", key="pap_edit_senha_conf")
            lideranca_edit = st.selectbox(
                "Liderança",
                options=["Selecione...", "Diego Roberto", "Sabrina"],
                index=["Selecione...", "Diego Roberto", "Sabrina"].index(
                    user_edit.get("lideranca", "Selecione...")
                ),
                key="pap_edit_lideranca"
            )
            tipo_chave_pix_edit = st.selectbox(
                "Tipo de Chave Pix",
                ["Selecione...", "CPF", "E-mail", "Celular", "Chave Aleatória"],
                index=["Selecione...", "CPF", "E-mail", "Celular", "Chave Aleatória"].index(
                    user_edit.get("tipo_chave_pix", "Selecione...")
                ),
                key="pap_edit_tipo_chave_pix"
            )
            chave_pix_edit = st.text_input("Chave Pix", value=user_edit.get("chave_pix", ""), key="pap_edit_chave_pix")

        if st.button("💾 Salvar Alterações", key="salvar_pap_edit"):
            if not all([
                nome_edit.strip(), login_edit.strip(), telefone_edit.strip(),
                email_edit.strip(), lideranca_edit, tipo_chave_pix_edit, chave_pix_edit.strip()
            ]):
                st.error("⚠️ Todos os campos, exceto senha, são obrigatórios.")
            elif lideranca_edit == "Selecione...":
                st.error("⚠️ Selecione uma liderança válida.")
            elif tipo_chave_pix_edit == "Selecione...":
                st.error("⚠️ Selecione um tipo de chave Pix válido.")
            else:
                update_data = {
                    "nome_exibicao": nome_edit.strip(),
                    "login": login_edit.strip(),
                    "telefone": telefone_edit.strip(),
                    "email": email_edit.strip(),
                    "lideranca": lideranca_edit.strip(),
                    "tipo_chave_pix": tipo_chave_pix_edit.strip(),
                    "chave_pix": chave_pix_edit.strip()
                }
                if senha_edit:
                    if senha_edit != senha_conf_edit:
                        st.error("❌ Senhas não coincidem.")
                    elif len(senha_edit) < 6:
                        st.error("⚠️ Senha deve ter ≥6 caracteres.")
                    else:
                        update_data["senha_hash"] = hash_senha(senha_edit)

                try:
                    usuarios_collection.update_one({"_id": user_edit["_id"]}, {"$set": update_data})
                    st.success("✅ Usuário atualizado!")
                    del st.session_state["editando_pap"]
                    st.rerun()
                except Exception as e:
                    st.error(f"❌ Erro: {e}")

        if st.button("❌ Cancelar", key="cancelar_pap_edit"):
            del st.session_state["editando_pap"]
            st.rerun()
