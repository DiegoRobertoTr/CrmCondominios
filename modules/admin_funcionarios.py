# modules/admin_funcionarios.py
import streamlit as st
import hashlib
from datetime import datetime
from .permissoes import get_perfis_internos, PERMISSOES_POR_PERFIL

def render_admin_funcionarios(usuarios_collection):
    st.title("👥 Admin Funcionários Internos")
    
    menu = st.tabs(["➕ Novo Funcionário", "📋 Lista de Funcionários", "🔑 Alterar Senha"])
    
    with menu[0]:
        st.subheader("Cadastrar Novo Funcionário Interno")
        
        with st.form("form_novo_funcionario"):
            col1, col2 = st.columns(2)
            with col1:
                nome_exibicao = st.text_input("Nome Completo *")
                login = st.text_input("Login de Acesso *")
                email = st.text_input("E-mail")
            with col2:
                senha = st.text_input("Senha *", type="password")
                confirmar_senha = st.text_input("Confirmar Senha *", type="password")
                perfil = st.selectbox(
                    "Perfil de Acesso *",
                    options=get_perfis_internos(),
                    index=1  # Default recepcao
                )
            
            if perfil:
                st.info(f"📋 **Permissões deste perfil:**\n{', '.join(PERMISSOES_POR_PERFIL.get(perfil, []))}")
            
            enviado = st.form_submit_button("💾 Cadastrar Funcionário")
            
            if enviado:
                if not all([nome_exibicao, login, senha, confirmar_senha]):
                    st.error("❌ Preencha todos os campos obrigatórios!")
                elif senha != confirmar_senha:
                    st.error("❌ As senhas não coincidem!")
                elif len(senha) < 6:
                    st.error("❌ A senha deve ter no mínimo 6 caracteres!")
                else:
                    if usuarios_collection.find_one({"login": login}):
                        st.error("❌ Este login já está em uso!")
                    else:
                        try:
                            usuario_data = {
                                "nome_exibicao": nome_exibicao,
                                "login": login,
                                "email": email,
                                "senha_hash": hashlib.sha256(senha.encode()).hexdigest(),
                                "perfil": perfil,
                                "ativo": True,
                                "data_cadastro": datetime.utcnow(),
                                "cadastrado_por": st.session_state.get("nome_usuario", "Sistema"),
                                "tipo_usuario": "interno"
                            }
                            usuarios_collection.insert_one(usuario_data)
                            st.success(f"✅ Funcionário {nome_exibicao} cadastrado com sucesso!")
                            st.balloons()
                        except Exception as e:
                            st.error(f"❌ Erro ao cadastrar: {e}")
    
    with menu[1]:
        st.subheader("Funcionários Internos")
        filtro_perfil = st.selectbox(
            "Filtrar por perfil:",
            ["Todos"] + get_perfis_internos()
        )
        
        query = {"tipo_usuario": "interno"}
        if filtro_perfil != "Todos":
            query["perfil"] = filtro_perfil
        
        funcionarios = list(usuarios_collection.find(query))
        
        if funcionarios:
            for func in funcionarios:
                with st.expander(f"👤 {func.get('nome_exibicao', 'N/A')} ({func.get('login', 'N/A')})"):
                    col1, col2, col3 = st.columns(3)
                    col1.write(f"**Perfil:** {func.get('perfil', 'N/A').title()}")
                    col2.write(f"**E-mail:** {func.get('email', 'N/A')}")
                    col3.write(f"**Ativo:** {'✅ Sim' if func.get('ativo', True) else '❌ Não'}")
                    
                    st.write(f"**Permissões:** {', '.join(PERMISSOES_POR_PERFIL.get(func.get('perfil'), []))}")
                    
                    col_ac1, col_ac2 = st.columns(2)
                    with col_ac1:
                        if st.button("🔒 Desativar" if func.get('ativo', True) else "✅ Ativar", key=f"toggle_{func['_id']}"):
                            usuarios_collection.update_one(
                                {"_id": func["_id"]},
                                {"$set": {"ativo": not func.get('ativo', True)}}
                            )
                            st.rerun()
                    with col_ac2:
                        if st.button("🗑️ Excluir", key=f"delete_{func['_id']}", type="secondary"):
                            usuarios_collection.delete_one({"_id": func["_id"]})
                            st.rerun()
        else:
            st.info("Nenhum funcionário interno encontrado.")
            
    with menu[2]:
        st.subheader("Alterar Senha de Funcionário")
        login_alterar = st.text_input("Login do funcionário")
        nova_senha = st.text_input("Nova Senha", type="password")
        confirmar_nova_senha = st.text_input("Confirmar Nova Senha", type="password")
        
        if st.button("🔄 Alterar Senha"):
            if not all([login_alterar, nova_senha, confirmar_nova_senha]):
                st.error("❌ Preencha todos os campos!")
            elif nova_senha != confirmar_nova_senha:
                st.error("❌ As senhas não coincidem!")
            else:
                usuario = usuarios_collection.find_one({"login": login_alterar, "tipo_usuario": "interno"})
                if not usuario:
                    st.error("❌ Funcionário não encontrado!")
                else:
                    usuarios_collection.update_one(
                        {"login": login_alterar},
                        {"$set": {"senha_hash": hashlib.sha256(nova_senha.encode()).hexdigest()}}
                    )
                    st.success(f"✅ Senha de {usuario.get('nome_exibicao')} alterada com sucesso!")
