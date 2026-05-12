import streamlit as st
import hashlib
import time
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
    
    # ✅ Botão para corrigir documentos com chaves erradas
    col_corrigir, col_vazio = st.columns([1, 3])
    with col_corrigir:
        if st.button("🔧 Corrigir Cadastros Antigos", 
                      help="Corrige funcionários cadastrados com erro de espaços nas chaves",
                      type="secondary",
                      key="btn_corrigir_docs",
                      use_container_width=True):
            with st.spinner("🔍 Verificando e corrigindo documentos..."):
                qtd_corrigidos = corrigir_documentos_com_espacos(usuarios_collection)
                if qtd_corrigidos > 0:
                    st.success(f"✅ {qtd_corrigidos} documento(s) corrigido(s) com sucesso!")
                    st.toast(f"🔧 {qtd_corrigidos} cadastros corrigidos!", icon="✅")
                    st.balloons()
                    time.sleep(1.5)
                    st.rerun()
                else:
                    st.info("✅ Nenhum documento precisou ser corrigido.")
    
    st.divider()
    
    # Abas do módulo
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
            
            enviado = st.form_submit_button("💾 Cadastrar Funcionário", use_container_width=True, type="primary")
            
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
                            st.toast(f"🎉 {nome_exibicao} cadastrado(a)!", icon="✅")
                            st.balloons()
                            time.sleep(1.5)
                            st.rerun()
                        except Exception as e:
                            st.error(f"❌ Erro ao cadastrar: {e}")

    # ========================================================================
    # ABA 1: LISTA DE FUNCIONÁRIOS
    # ========================================================================
    with menu[1]:
        st.subheader("Funcionários Internos")
        
        # Filtro por perfil
        col_filtro, col_info = st.columns([1, 2])
        with col_filtro:
            perfis_filtro = ["Todos"] + get_perfis_internos()
            filtro_perfil = st.selectbox("Filtrar por perfil:", perfis_filtro)
        
        query = {"tipo_usuario": "interno"}
        if filtro_perfil != "Todos":
            query["perfil"] = filtro_perfil
        
        funcionarios = list(usuarios_collection.find(query))
        
        with col_info:
            if funcionarios:
                ativos = sum(1 for f in funcionarios if f.get('ativo', True))
                inativos = len(funcionarios) - ativos
                st.info(f"📊 **{len(funcionarios)}** funcionários encontrados | ✅ {ativos} ativos | ❌ {inativos} inativos")
        
        if funcionarios:
            for func in funcionarios:
                nome = func.get('nome_exibicao', 'N/A')
                login_func = func.get('login', 'N/A')
                perfil_func = func.get('perfil', 'N/A')
                email_func = func.get('email', 'N/A')
                ativo = func.get('ativo', True)
                data_cadastro = func.get('data_cadastro', None)
                
                # Emoji de status
                status_emoji = "🟢" if ativo else "🔴"
                
                with st.expander(f"{status_emoji} {nome} ({login_func})"):
                    col1, col2, col3 = st.columns(3)
                    with col1:
                        st.write(f"**Perfil:** {perfil_func.title()}")
                        st.write(f"**Login:** {login_func}")
                    with col2:
                        st.write(f"**E-mail:** {email_func if email_func else 'N/A'}")
                        if data_cadastro:
                            st.write(f"**Cadastro:** {data_cadastro.strftime('%d/%m/%Y')}")
                    with col3:
                        st.write(f"**Status:** {'✅ Ativo' if ativo else '❌ Inativo'}")
                    
                    # Permissões
                    permissoes_func = PERMISSOES_POR_PERFIL.get(perfil_func, [])
                    if permissoes_func:
                        st.write("**Permissões:**")
                        # Mostrar em badges
                        cols_perm = st.columns(min(len(permissoes_func), 4))
                        for i, perm in enumerate(permissoes_func):
                            col_idx = i % 4
                            cols_perm[col_idx].markdown(f"`{perm}`")
                    else:
                        st.warning("⚠️ Nenhuma permissão definida para este perfil.")
                    
                    st.divider()
                    
                    # Ações
                    col_ac1, col_ac2, col_ac3 = st.columns(3)
                    with col_ac1:
                        btn_text = "🔒 Desativar" if ativo else "✅ Ativar"
                        btn_type = "secondary" if ativo else "primary"
                        if st.button(btn_text, key=f"toggle_{func['_id']}", use_container_width=True, type=btn_type):
                            usuarios_collection.update_one(
                                {"_id": func["_id"]},
                                {"$set": {"ativo": not ativo}}
                            )
                            acao = "desativado" if ativo else "ativado"
                            st.success(f"✅ Funcionário {nome} {acao} com sucesso!")
                            st.toast(f"{'🔒' if ativo else '✅'} {nome} {acao}(a)!", icon="✅")
                            time.sleep(1)
                            st.rerun()
                    with col_ac2:
                        if st.button("🔑 Resetar Senha", key=f"reset_{func['_id']}", use_container_width=True):
                            # Senha padrão: 123456
                            nova_senha_padrao = "123456"
                            usuarios_collection.update_one(
                                {"_id": func["_id"]},
                                {"$set": {"senha_hash": hashlib.sha256(nova_senha_padrao.encode()).hexdigest()}}
                            )
                            st.success(f"✅ Senha de {nome} resetada para a senha padrão!")
                            st.toast(f"🔑 Senha de {nome} resetada!", icon="🔐")
                            time.sleep(1)
                            st.rerun()
                    with col_ac3:
                        if st.button("🗑️ Excluir", key=f"delete_{func['_id']}", use_container_width=True, type="secondary"):
                            # Confirmação
                            with st.spinner(f"Excluindo {nome}..."):
                                usuarios_collection.delete_one({"_id": func["_id"]})
                                st.success(f"✅ Funcionário {nome} excluído com sucesso!")
                                st.toast(f"🗑️ {nome} removido(a)!", icon="🗑️")
                                time.sleep(1)
                                st.rerun()
        else:
            st.info("ℹ️ Nenhum funcionário interno encontrado.")
    
    # ========================================================================
    # ABA 2: ALTERAR SENHA
    # ========================================================================
    with menu[2]:
        st.subheader("Alterar Senha de Funcionário")
        
        st.markdown("Altere a senha de qualquer funcionário interno informando o login e a nova senha.")
        
        col1, col2 = st.columns(2)
        with col1:
            login_alterar = st.text_input("Login do funcionário", placeholder="Digite o login...")
        with col2:
            st.write("")  # Espaçamento
            st.write("")
        
        col3, col4 = st.columns(2)
        with col3:
            nova_senha = st.text_input("Nova Senha", type="password", placeholder="Mínimo 6 caracteres")
        with col4:
            confirmar_nova_senha = st.text_input("Confirmar Nova Senha", type="password", placeholder="Repita a senha")
        
        if st.button("🔄 Alterar Senha", use_container_width=True, type="primary"):
            if not all([login_alterar, nova_senha, confirmar_nova_senha]):
                st.error("❌ Preencha todos os campos!")
            elif len(nova_senha) < 6:
                st.error("❌ A senha deve ter no mínimo 6 caracteres!")
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
                    nome_usuario = usuario.get('nome_exibicao', login_alterar)
                    st.success(f"✅ Senha de **{nome_usuario}** alterada com sucesso!")
                    st.toast(f"🔑 Senha de {nome_usuario} atualizada!", icon="🔐")
                    st.balloons()
                    time.sleep(1.5)
                    st.rerun()

    # ========================================================================
    # ABA 3: NÍVEIS E PERMISSÕES
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
                perfil_nome = perfil.replace("_", " ").title()
                emoji = "👑" if perfil == "admin" else "🎯" if "supervisao" in perfil else "📋"
                
                with st.expander(f"{emoji} **{perfil_nome}**"):
                    permissoes = PERMISSOES_POR_PERFIL.get(perfil, [])
                    if permissoes:
                        st.write(f"**{len(permissoes)} permissões:**")
                        for mod in permissoes:
                            st.write(f"• {mod}")
                    else:
                        st.warning("Nenhuma permissão definida.")

        # --- Parceiros Externos ---
        with col_externa:
            st.markdown("### 🤝 Parceiros Externos")
            st.info("Acesso restrito a painéis específicos.")
            
            perfis_externos = [
                ("embaixador", "🤝"),
                ("tecnico", "🔧"),
                ("pap", "🚪"),
                ("revenda", "🏪")
            ]
            
            for perfil, emoji in perfis_externos:
                perfil_nome = perfil.title()
                
                with st.expander(f"{emoji} **{perfil_nome}**"):
                    permissoes = PERMISSOES_POR_PERFIL.get(perfil, [])
                    if permissoes:
                        st.write(f"**{len(permissoes)} permissão(ões):**")
                        for mod in permissoes:
                            st.write(f"• {mod}")
                    else:
                        st.warning("Nenhuma permissão definida.")
        
        st.divider()
        
        # Tabela resumo
        st.markdown("### 📋 Resumo Rápido")
        
        todos_perfis = get_perfis_internos() + ["embaixador", "tecnico", "pap", "revenda"]
        
        dados_tabela = []
        for perfil in todos_perfis:
            permissoes = PERMISSOES_POR_PERFIL.get(perfil, [])
            dados_tabela.append({
                "Perfil": perfil.replace("_", " ").title(),
                "Qtd. Módulos": len(permissoes),
                "Módulos": ", ".join(permissoes) if permissoes else "Nenhum"
            })
        
        st.dataframe(
            dados_tabela,
            use_container_width=True,
            hide_index=True,
            column_config={
                "Perfil": st.column_config.TextColumn("Perfil", width="medium"),
                "Qtd. Módulos": st.column_config.NumberColumn("Qtd. Módulos", width="small"),
                "Módulos": st.column_config.TextColumn("Módulos Acessados", width="large")
            }
        )
        
        st.divider()
        st.caption("ℹ️ Para corrigir funcionários já cadastrados com erro, use o botão 'Corrigir Cadastros Antigos' no topo da página.")
