import streamlit as st
import hashlib
from datetime import datetime

# Tentativa de importação robusta
try:
    from modules.permissoes import get_perfis_internos, PERMISSOES_POR_PERFIL
except ImportError:
    # Fallback caso a importação falhe (evita quebra total do módulo)
    def get_perfis_internos():
        return ["admin", "recepcao", "atendente_n1", "supervisao_n1", "supervisao_n2", "supervisao_n3", "diretoria"]
    
    PERMISSOES_POR_PERFIL = {
        "admin": ["Cadastro", "Follow-up", "Agendamentos", "Roteiro de Vendas", "Admin Embaixadores", "Admin Técnicos", "Admin PaP", "Admin Revendas", "Admin Funcionários", "Acompanhamento Técnicos", "Relatórios", "Endereços Bloqueados", "Condomínios", "Relatórios Condomínios", "Prospecção Condomínios", "Leads & Eventos", "Pendências"],
        "recepcao": ["Cadastro", "Follow-up", "Agendamentos", "Roteiro de Vendas", "Endereços Bloqueados", "Leads & Eventos", "Pendências"],
        "atendente_n1": ["Cadastro", "Follow-up", "Agendamentos", "Roteiro de Vendas", "Endereços Bloqueados", "Leads & Eventos", "Pendências"],
        "supervisao_n1": ["Cadastro", "Follow-up", "Agendamentos", "Roteiro de Vendas", "Leads & Eventos", "Pendências"],
        "supervisao_n2": ["Cadastro", "Follow-up", "Agendamentos", "Roteiro de Vendas", "Admin Embaixadores", "Admin PaP", "Admin Revendas", "Leads & Eventos", "Pendências"],
        "supervisao_n3": ["Cadastro", "Follow-up", "Agendamentos", "Roteiro de Vendas", "Admin Embaixadores", "Admin PaP", "Admin Revendas", "Relatórios", "Relatórios Condomínios", "Prospecção Condomínios", "Leads & Eventos", "Pendências"],
        "diretoria": ["Relatórios Condomínios", "Prospecção Condomínios"],
        "embaixador": ["Painel Embaixador"],
        "tecnico": ["Painel Técnico"],
        "pap": ["Cadastro Porta a Porta"],
        "revenda": ["Painel Revenda"]
    }


def corrigir_documentos_com_espacos(usuarios_collection):
    """
    Corrige documentos existentes que foram salvos com chaves contendo espaços no final.
    Ex: "nome_exibicao " -> "nome_exibicao"
    """
    documentos_corrigidos = 0
    
    # Buscar documentos que tem chaves com espaço (verificando pela chave "login ")
    documentos_problematicos = list(usuarios_collection.find({"login ": {"$exists": True}}))
    
    if not documentos_problematicos:
        # Também tenta buscar por "nome_exibicao " caso "login " não exista
        documentos_problematicos = list(usuarios_collection.find({"nome_exibicao ": {"$exists": True}}))
    
    for doc in documentos_problematicos:
        try:
            novo_doc = {}
            for chave, valor in doc.items():
                nova_chave = chave.strip()  # Remove espaços no início e fim
                novo_doc[nova_chave] = valor
            
            # Substitui o documento antigo pelo corrigido
            usuarios_collection.replace_one({"_id": doc["_id"]}, novo_doc)
            documentos_corrigidos += 1
            
            # Log no terminal
            nome = novo_doc.get('nome_exibicao', novo_doc.get('login', 'N/A'))
            print(f"✅ Documento corrigido: {nome}")
        except Exception as e:
            print(f"❌ Erro ao corrigir documento {doc.get('_id')}: {e}")
    
    return documentos_corrigidos


def render_admin_funcionarios(usuarios_collection):
    st.title("👥 Admin Funcionários Internos")
    
    # ✅ Verificar e corrigir documentos com chaves erradas
    if st.button("🔧 Corrigir Documentos Existentes", 
                  help="Corrige funcionários cadastrados com erro de espaços nas chaves",
                  type="secondary",
                  key="btn_corrigir_docs"):
        with st.spinner("🔍 Verificando e corrigindo documentos..."):
            qtd_corrigidos = corrigir_documentos_com_espacos(usuarios_collection)
            if qtd_corrigidos > 0:
                st.success(f"✅ {qtd_corrigidos} documento(s) corrigido(s) com sucesso!")
                st.rerun()
            else:
                st.info("✅ Nenhum documento precisou ser corrigido.")
    
    st.divider()
    
    # ✅ ADICIONADA 4ª ABA: NÍVEIS E PERMISSÕES
    menu = st.tabs(["➕ Novo Funcionário", "📋 Lista de Funcionários", "🔑 Alterar Senha", "📊 Níveis e Permissões"])

    # ========================================================================
    # ABA 0: NOVO FUNCIONÁRIO
    # ========================================================================
    with menu[0]:
        st.subheader("Cadastrar Novo Funcionário Interno")
        
        with st.form("form_novo_funcionario"):
            col1, col2 = st.columns(2)
            with col1:
                nome_exibicao = st.text_input("Nome Completo *")
                login = st.text_input("Login de Acesso *")
                email = st.text_input("E-mail")
            with col2:
                # ✅ CORRIGIDO: type="password" (sem espaço)
                senha = st.text_input("Senha *", type="password")
                confirmar_senha = st.text_input("Confirmar Senha *", type="password")
                
                # Garante que a lista de perfis venha da função corrigida
                perfis_disponiveis = get_perfis_internos()
                
                perfil = st.selectbox(
                    "Perfil de Acesso *",
                    options=perfis_disponiveis,
                    index=1 if "recepcao" in perfis_disponiveis else 0
                )
            
            # Exibe as permissões do perfil selecionado
            if perfil:
                permissoes_atuais = PERMISSOES_POR_PERFIL.get(perfil, [])
                if permissoes_atuais:
                    st.info(f"📋 **Permissões deste perfil:**\n{', '.join(permissoes_atuais)}")
                else:
                    st.warning("⚠️ Este perfil não tem permissões definidas ainda.")
            
            enviado = st.form_submit_button("💾 Cadastrar Funcionário")
            
            if enviado:
                if not all([nome_exibicao, login, senha, confirmar_senha]):
                    st.error("❌ Preencha todos os campos obrigatórios!")
                elif senha != confirmar_senha:
                    st.error("❌ As senhas não coincidem!")
                elif len(senha) < 6:
                    st.error("❌ A senha deve ter no mínimo 6 caracteres!")
                else:
                    # ✅ CORRIGIDO: removido espaço de "login"
                    if usuarios_collection.find_one({"login": login}):
                        st.error("❌ Este login já está em uso!")
                    else:
                        try:
                            # ✅ CORRIGIDO: removidos TODOS os espaços das chaves
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
                            st.rerun()
                        except Exception as e:
                            st.error(f"❌ Erro ao cadastrar: {e}")

    # ========================================================================
    # ABA 1: LISTA DE FUNCIONÁRIOS
    # ========================================================================
    with menu[1]:
        st.subheader("Funcionários Internos")
        
        perfis_filtro = ["Todos"] + get_perfis_internos()
        filtro_perfil = st.selectbox("Filtrar por perfil:", perfis_filtro)
        
        # ✅ CORRIGIDO: removidos espaços das chaves
        query = {"tipo_usuario": "interno"}
        if filtro_perfil != "Todos":
            query["perfil"] = filtro_perfil
        
        funcionarios = list(usuarios_collection.find(query))
        
        if funcionarios:
            for func in funcionarios:
                # ✅ CORRIGIDO: removidos espaços dos .get()
                nome = func.get('nome_exibicao', 'N/A')
                login_func = func.get('login', 'N/A')
                perfil_func = func.get('perfil', 'N/A')
                email_func = func.get('email', 'N/A')
                ativo = func.get('ativo', True)
                
                with st.expander(f"👤 {nome} ({login_func})"):
                    col1, col2, col3 = st.columns(3)
                    col1.write(f"**Perfil:** {perfil_func.title()}")
                    col2.write(f"**E-mail:** {email_func}")
                    col3.write(f"**Ativo:** {'✅ Sim' if ativo else '❌ Não'}")
                    
                    permissoes_func = PERMISSOES_POR_PERFIL.get(perfil_func, [])
                    st.write(f"**Permissões:** {', '.join(permissoes_func) if permissoes_func else 'Nenhuma'}")
                    
                    col_ac1, col_ac2 = st.columns(2)
                    with col_ac1:
                        btn_text = "🔒 Desativar" if ativo else "✅ Ativar"
                        # ✅ CORRIGIDO: removidos espaços das chaves de update
                        if st.button(btn_text, key=f"toggle_{func['_id']}"):
                            usuarios_collection.update_one(
                                {"_id": func["_id"]},
                                {"$set": {"ativo": not ativo}}
                            )
                            st.rerun()
                    with col_ac2:
                        if st.button("🗑️ Excluir", key=f"delete_{func['_id']}", type="secondary"):
                            # ✅ CORRIGIDO: removido espaço de "_id"
                            usuarios_collection.delete_one({"_id": func["_id"]})
                            st.success(f"✅ Funcionário {nome} excluído com sucesso!")
                            st.rerun()
        else:
            st.info("ℹ️ Nenhum funcionário interno encontrado.")
    
    # ========================================================================
    # ABA 2: ALTERAR SENHA
    # ========================================================================
    with menu[2]:
        st.subheader("Alterar Senha de Funcionário")
        login_alterar = st.text_input("Login do funcionário")
        # ✅ CORRIGIDO: type="password" (sem espaço)
        nova_senha = st.text_input("Nova Senha", type="password")
        confirmar_nova_senha = st.text_input("Confirmar Nova Senha", type="password")
        
        if st.button("🔄 Alterar Senha"):
            if not all([login_alterar, nova_senha, confirmar_nova_senha]):
                st.error("❌ Preencha todos os campos!")
            elif nova_senha != confirmar_nova_senha:
                st.error("❌ As senhas não coincidem!")
            else:
                # ✅ CORRIGIDO: removidos espaços das chaves
                usuario = usuarios_collection.find_one({"login": login_alterar, "tipo_usuario": "interno"})
                if not usuario:
                    st.error("❌ Funcionário não encontrado!")
                else:
                    # ✅ CORRIGIDO: removidos espaços das chaves
                    usuarios_collection.update_one(
                        {"login": login_alterar},
                        {"$set": {"senha_hash": hashlib.sha256(nova_senha.encode()).hexdigest()}}
                    )
                    st.success(f"✅ Senha de {usuario.get('nome_exibicao')} alterada com sucesso!")
                    st.rerun()

    # ========================================================================
    # ✅ ABA 3: NÍVEIS E PERMISSÕES (NOVA ABA)
    # ========================================================================
    with menu[3]:
        st.subheader("📊 Matriz de Permissões por Perfil")
        st.markdown("Consulte abaixo quais módulos cada perfil tem acesso antes de cadastrar um novo funcionário.")
        
        col_interna, col_externa = st.columns(2)
        
        # --- Equipe Interna ---
        with col_interna:
            st.markdown("### 🏢 Equipe Interna")
            st.info("Funcionários com acesso ao sistema administrativo.")
            
            perfis_internos = get_perfis_internos()
            
            for perfil in perfis_internos:
                with st.expander(f"**{perfil.strip().title()}**"):
                    permissoes = PERMISSOES_POR_PERFIL.get(perfil, [])
                    if permissoes:
                        for mod in permissoes:
                            st.write(f"• {mod.strip()}")
                    else:
                        st.warning("Nenhuma permissão definida.")

        # --- Parceiros Externos ---
        with col_externa:
            st.markdown("### 🤝 Parceiros Externos")
            st.info("Acesso restrito a painéis específicos.")
            
            perfis_externos = ["embaixador", "tecnico", "pap", "revenda"]
            
            for perfil in perfis_externos:
                with st.expander(f"**{perfil.strip().title()}**"):
                    permissoes = PERMISSOES_POR_PERFIL.get(perfil, [])
                    if permissoes:
                        for mod in permissoes:
                            st.write(f"• {mod.strip()}")
                    else:
                        st.warning("Nenhuma permissão definida.")
        
        st.divider()
        st.caption("ℹ️ Nota: Para corrigir funcionários já cadastrados com erro, use o botão 'Corrigir Documentos Existentes' no topo da página.")
