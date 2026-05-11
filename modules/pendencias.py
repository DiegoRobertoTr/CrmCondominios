# modules/pendencias.py
# ✅ Adaptado para Condomínios Tracecom - Sistema de Perfis Hierárquicos
import streamlit as st
from datetime import datetime, timedelta, timezone
from bson import ObjectId
import calendar
from collections import defaultdict

# ============================================================================
# 🕐 CONFIGURAÇÃO DE FUSO HORÁRIO
# ============================================================================
FUSO_BRASILIA = timezone(timedelta(hours=-3))

def agora_brasilia():
    """Retorna datetime.now() no fuso horário de Brasília"""
    return datetime.now(FUSO_BRASILIA)

def formatar_data_hora(dt):
    """Formata datetime para exibição no horário de Brasília"""
    if dt is None:
        return "N/A"
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc).astimezone(FUSO_BRASILIA)
    else:
        dt = dt.astimezone(FUSO_BRASILIA)
    return dt.strftime('%d/%m/%Y %H:%M')

def formatar_data(dt):
    """Formata apenas a data no horário de Brasília"""
    if dt is None:
        return "N/A"
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc).astimezone(FUSO_BRASILIA)
    else:
        dt = dt.astimezone(FUSO_BRASILIA)
    return dt.strftime('%d/%m/%Y')

# ============================================================================
# 📋 CONEXÃO COM A COLEÇÃO DE PENDÊNCIAS
# ============================================================================
def get_pendencias_collection(clientes_collection):
    """Retorna a coleção de pendências (mesmo banco do CRM)"""
    return clientes_collection.database.pendencias

# ============================================================================
# 👥 USUÁRIOS DISPONÍVEIS PARA PENDÊNCIAS
# ============================================================================
def obter_usuarios_disponiveis(clientes_collection=None):
    """
    ✅ Retorna APENAS perfis internos que podem receber pendências.
    
    Perfis incluídos:
    - admin (secrets)
    - recepcao (secrets)
    - atendente_n1 (MongoDB)
    - supervisao_n1 (MongoDB)
    - supervisao_n2 (MongoDB)
    - supervisao_n3 (MongoDB)
    
    Perfis excluídos:
    - diretoria (apenas visualiza relatórios)
    - embaixador, tecnico, pap, revenda (externos)
    """
    usuarios = []
    
    # ✅ PASSO 1: Adicionar usuários FIXOS do secrets
    try:
        if "usuarios" in st.secrets:
            secrets_usuarios = st.secrets["usuarios"]
            
            # Admin
            if "admin_login" in secrets_usuarios:
                usuarios.append({
                    "login": secrets_usuarios["admin_login"],
                    "nome": "Administrador",
                    "perfil": "admin",
                    "perfil_nome": "Administrador",
                    "origem": "Fixo (secrets)"
                })
            
            # Recepção
            if "recepcao_login" in secrets_usuarios:
                usuarios.append({
                    "login": secrets_usuarios["recepcao_login"],
                    "nome": "Recepção",
                    "perfil": "recepcao",
                    "perfil_nome": "Recepção",
                    "origem": "Fixo (secrets)"
                })
    except Exception:
        # Fallback
        usuarios.append({
            "login": "admin", "nome": "Administrador", 
            "perfil": "admin", "perfil_nome": "Administrador"
        })
        usuarios.append({
            "login": "recepcao", "nome": "Recepção",
            "perfil": "recepcao", "perfil_nome": "Recepção"
        })
    
    # ✅ PASSO 2: Adicionar usuários DINÂMICOS do MongoDB (apenas internos)
    try:
        usuarios_coll = st.session_state.get("usuarios_collection")
        
        if usuarios_coll is None:
            from modules.auth import get_usuarios_collection
            try:
                usuarios_coll = get_usuarios_collection()
                st.session_state["usuarios_collection"] = usuarios_coll
            except Exception:
                usuarios_coll = None
        
        if usuarios_coll is not None:
            # Define perfis internos que podem receber pendências
            perfis_internos_pendencias = [
                "admin", "recepcao", "atendente_n1",
                "supervisao_n1", "supervisao_n2", "supervisao_n3"
            ]
            
            todos_usuarios = list(usuarios_coll.find({
                "perfil": {"$in": perfis_internos_pendencias},
                "ativo": {"$ne": False}  # Apenas usuários ativos
            }))
            
            # Tradução de perfis para nomes amigáveis
            perfil_nomes = {
                "admin": "Administrador",
                "recepcao": "Recepção",
                "atendente_n1": "Atendente N1",
                "supervisao_n1": "Supervisão N1",
                "supervisao_n2": "Supervisão N2",
                "supervisao_n3": "Supervisão N3",
            }
            
            for u in todos_usuarios:
                login = u.get("login", "")
                nome = u.get("nome_exibicao", login or "Usuário sem nome")
                perfil = u.get("perfil", "desconhecido")
                
                # Pular se já foi adicionado pelos secrets (evitar duplicatas)
                if any(user["login"] == login for user in usuarios):
                    continue
                
                usuarios.append({
                    "login": login if login else perfil,
                    "nome": nome,
                    "perfil": perfil,
                    "perfil_nome": perfil_nomes.get(perfil, perfil.replace("_", " ").title()),
                    "origem": "MongoDB"
                })
    except Exception:
        pass  # Pelo menos admin e recepção já estão na lista
    
    # ✅ Ordenação hierárquica
    ordem_perfil = {
        "admin": 0,
        "recepcao": 1,
        "supervisao_n3": 2,
        "supervisao_n2": 3,
        "supervisao_n1": 4,
        "atendente_n1": 5,
    }
    usuarios.sort(key=lambda x: (ordem_perfil.get(x["perfil"], 99), x["nome"]))
    
    return usuarios

# ============================================================================
# 🎯 RENDER PRINCIPAL
# ============================================================================
def render_pendencias(clientes_collection):
    """Renderiza o módulo de pendências"""
    st.markdown("## 📋 Pendências")
    
    pendencias_coll = get_pendencias_collection(clientes_collection)
    
    # Garantir índices
    pendencias_coll.create_index("responsavel")
    pendencias_coll.create_index("solicitante")
    pendencias_coll.create_index("status")
    pendencias_coll.create_index("data_limite")
    
    # Abas do módulo
    tab_criar, tab_minhas, tab_todas, tab_calendario = st.tabs([
        "➕ Nova Pendência",
        "👤 Minhas Pendências",
        "📋 Todas as Pendências",
        "📅 Calendário"
    ])
    
    with tab_criar:
        criar_pendencia(pendencias_coll, clientes_collection)
    
    with tab_minhas:
        mostrar_minhas_pendencias(pendencias_coll, clientes_collection)
    
    with tab_todas:
        mostrar_todas_pendencias(pendencias_coll, clientes_collection)
    
    with tab_calendario:
        mostrar_calendario_pendencias(pendencias_coll)

# ============================================================================
# ➕ CRIAR PENDÊNCIA
# ============================================================================
def criar_pendencia(pendencias_coll, clientes_collection):
    """Formulário para criar nova pendência"""
    st.subheader("➕ Criar Nova Pendência")
    
    perfil = st.session_state.get("perfil", "")
    nome_usuario = st.session_state.get("nome_usuario", perfil)
    
    # Mostrar hora atual de Brasília
    agora = agora_brasilia()
    st.caption(f"👤 Logado como: **{nome_usuario}** ({perfil}) | 🕐 {agora.strftime('%d/%m/%Y %H:%M')}")
    
    with st.form("nova_pendencia", clear_on_submit=True):
        col1, col2 = st.columns(2)
        
        with col1:
            titulo = st.text_input(
                "📌 Título da Pendência *", 
                placeholder="Ex: Vistoriar condomínio, Reagendar visita técnica, etc."
            )
            
            prioridade = st.selectbox(
                "🔴 Prioridade", 
                ["baixa", "média", "alta", "urgente"],
                index=1
            )
        
        with col2:
            data_limite = st.date_input(
                "📅 Data Limite *", 
                min_value=agora.date(),
                value=agora.date() + timedelta(days=1)
            )
        
        st.divider()
        
        # Direcionamento
        st.markdown("### 📤 Direcionamento")
        
        direcionamento = st.radio(
            "Para quem é esta pendência?",
            ["👥 Para um atendente específico", "👤 Para mim mesmo"],
            horizontal=True,
            help="Escolha se a pendência é para você ou para outra pessoa"
        )
        
        responsavel = None
        
        if direcionamento == "👥 Para um atendente específico":
            usuarios = obter_usuarios_disponiveis(clientes_collection)
            
            if not usuarios:
                st.error("❌ Nenhum usuário interno encontrado no sistema!")
            else:
                # Mostrar contagem
                total_fixos = sum(1 for u in usuarios if u.get("origem") == "Fixo (secrets)")
                total_dinamicos = sum(1 for u in usuarios if u.get("origem") == "MongoDB")
                st.caption(f"📊 {len(usuarios)} colaboradores disponíveis ({total_fixos} fixos + {total_dinamicos} cadastrados)")
                
                # Criar dicionário de opções
                opcoes_usuarios = {}
                for u in usuarios:
                    label = f"{u['nome']} ({u['perfil_nome']})"
                    if u.get("origem") == "MongoDB" and u['login'] and u['login'] != u['perfil']:
                        label += f" - @{u['login']}"
                    opcoes_usuarios[label] = u['login'] if u['login'] else u['perfil']
                
                # Dropdown de seleção
                responsavel_opcao = st.selectbox(
                    "👤 Selecione o Responsável *",
                    options=list(opcoes_usuarios.keys()),
                    help="Escolha quem será responsável por executar esta pendência"
                )
                responsavel = opcoes_usuarios[responsavel_opcao]
                st.success(f"✅ Pendência será direcionada para: **{responsavel_opcao}**")
        else:
            # Para mim mesmo
            responsavel = perfil
            
            # Para admin e recepção, usar o login específico do secrets
            if perfil == "admin":
                try:
                    responsavel = st.secrets["usuarios"]["admin_login"]
                except:
                    responsavel = "admin"
            elif perfil == "recepcao":
                try:
                    responsavel = st.secrets["usuarios"]["recepcao_login"]
                except:
                    responsavel = "recepcao"
            
            st.info(f"✅ Esta pendência será atribuída a você: **{nome_usuario}**")
        
        st.divider()
        
        # Cliente/Condomínio relacionado (opcional)
        st.markdown("### 🏢 Condomínio Relacionado (opcional)")
        
        vincular_condominio = st.checkbox(
            "🔗 Vincular a um condomínio específico?",
            value=False,
            help="Marque para associar esta pendência a um condomínio"
        )
        
        condominio_id = None
        condominio_nome = None
        cliente_id = None
        cliente_nome = None
        
        if vincular_condominio:
            busca = st.text_input(
                "🔍 Digite o nome do condomínio:",
                placeholder="Ex: Residencial Parque das Flores",
                key="busca_condominio_pendencia"
            )
            
            if busca:
                # Busca na coleção de condomínios (se existir) ou clientes
                try:
                    condominios_coll = clientes_collection.database.condominios
                    encontrados = list(condominios_coll.find({
                        "nome": {"$regex": busca, "$options": "i"}
                    }).limit(10))
                    
                    if encontrados:
                        opcoes = {
                            f"🏢 {c['nome']}": c['_id']
                            for c in encontrados
                        }
                        
                        escolhido = st.selectbox(
                            "Selecione o condomínio:",
                            options=list(opcoes.keys()),
                            key="condominio_select_pendencia"
                        )
                        
                        if escolhido:
                            condominio_id = opcoes[escolhido]
                            condominio_nome = escolhido.replace("🏢 ", "")
                            st.success(f"✅ Condomínio vinculado: {condominio_nome}")
                    else:
                        st.warning("🔍 Nenhum condomínio encontrado.")
                except Exception:
                    # Fallback: busca na coleção de clientes
                    encontrados = list(clientes_collection.find({
                        "nome_completo": {"$regex": busca, "$options": "i"}
                    }).limit(10))
                    
                    if encontrados:
                        opcoes = {
                            f"📞 {c['nome_completo']} - {c.get('celular', 'Sem tel')}": c['_id']
                            for c in encontrados
                        }
                        
                        escolhido = st.selectbox(
                            "Selecione:",
                            options=list(opcoes.keys()),
                            key="cliente_select_pendencia"
                        )
                        
                        if escolhido:
                            cliente_id = opcoes[escolhido]
                            cliente_nome = escolhido.split(" - ")[0].replace("📞 ", "")
                            st.success(f"✅ Cliente vinculado: {cliente_nome}")
                    else:
                        st.warning("🔍 Nenhum resultado encontrado.")
        
        st.divider()
        
        # Descrição
        st.markdown("### 📝 Detalhes")
        descricao = st.text_area(
            "Descrição Detalhada *",
            placeholder="Descreva o que precisa ser feito, observações importantes, materiais necessários, etc.",
            height=120
        )
        
        # Botão submit
        st.divider()
        submitted = st.form_submit_button("✅ Criar Pendência", use_container_width=True, type="primary")
        
        if submitted:
            erros = []
            if not titulo or not titulo.strip():
                erros.append("⚠️ O título é obrigatório!")
            if not descricao or not descricao.strip():
                erros.append("⚠️ A descrição é obrigatória!")
            if not responsavel:
                erros.append("⚠️ Selecione um responsável!")
            
            if erros:
                for erro in erros:
                    st.error(erro)
            else:
                pendencia = {
                    "titulo": titulo.strip(),
                    "descricao": descricao.strip(),
                    "solicitante": perfil,
                    "solicitante_nome": nome_usuario,
                    "responsavel": responsavel,
                    "data_criacao": agora_brasilia(),
                    "data_limite": datetime.combine(data_limite, datetime.min.time()),
                    "fuso_horario": "America/Sao_Paulo",
                    "status": "pendente",
                    "prioridade": prioridade,
                    "condominio_relacionado_id": condominio_id,
                    "condominio_relacionado_nome": condominio_nome,
                    "cliente_relacionado_id": cliente_id,
                    "cliente_relacionado_nome": cliente_nome,
                    "historico": [{
                        "acao": "Pendência criada",
                        "data": agora_brasilia(),
                        "usuario": nome_usuario,
                        "detalhes": f"Solicitante: {nome_usuario} → Responsável: {responsavel}"
                    }]
                }
                
                try:
                    pendencias_coll.insert_one(pendencia)
                    st.success(f"✅ Pendência '{titulo}' criada com sucesso para {responsavel}!")
                    st.toast(f"🎉 Pendência registrada às {agora_brasilia().strftime('%H:%M')}!", icon="✅")
                    st.balloons()
                except Exception as e:
                    st.error(f"❌ Erro ao criar pendência: {e}")

# ============================================================================
# 👤 MINHAS PENDÊNCIAS
# ============================================================================
def mostrar_minhas_pendencias(pendencias_coll, clientes_collection):
    """Mostra APENAS pendências do usuário logado"""
    st.subheader("👤 Minhas Pendências")
    
    perfil = st.session_state.get("perfil", "")
    nome_usuario = st.session_state.get("nome_usuario", "")
    
    st.caption(f"🕐 Horário atual: {agora_brasilia().strftime('%d/%m/%Y %H:%M')}")
    
    # Query base: pendências onde sou responsável
    query = {"responsavel": perfil}
    
    # Para perfis do secrets, buscar também pelo login real
    if perfil == "admin":
        try:
            admin_login = st.secrets["usuarios"]["admin_login"]
            if admin_login != "admin":
                query = {"$or": [{"responsavel": "admin"}, {"responsavel": admin_login}]}
        except:
            pass
    elif perfil == "recepcao":
        try:
            recepcao_login = st.secrets["usuarios"]["recepcao_login"]
            if recepcao_login != "recepcao":
                query = {"$or": [{"responsavel": "recepcao"}, {"responsavel": recepcao_login}]}
        except:
            pass
    
    # Filtros
    col1, col2, col3 = st.columns(3)
    with col1:
        status_filter = st.multiselect(
            "Filtrar por Status:",
            ["pendente", "em_andamento", "concluida"],
            default=["pendente", "em_andamento"],
            key="minhas_status"
        )
    with col2:
        prioridade_filter = st.multiselect(
            "Filtrar por Prioridade:",
            ["baixa", "média", "alta", "urgente"],
            key="minhas_prioridade"
        )
    with col3:
        hoje = agora_brasilia().date()
        periodo_filter = st.selectbox(
            "Período:",
            ["Todas", "Hoje", "Esta Semana", "Vencidas"],
            key="minhas_periodo"
        )
    
    # Aplicar filtros
    if status_filter:
        if "$or" in query:
            query = {"$and": [{"$or": query["$or"]}, {"status": {"$in": status_filter}}]}
        else:
            query["status"] = {"$in": status_filter}
    
    if prioridade_filter:
        query["prioridade"] = {"$in": prioridade_filter}
    
    if periodo_filter == "Hoje":
        query["data_limite"] = {
            "$gte": datetime(hoje.year, hoje.month, hoje.day),
            "$lt": datetime(hoje.year, hoje.month, hoje.day) + timedelta(days=1)
        }
    elif periodo_filter == "Esta Semana":
        inicio_semana = hoje - timedelta(days=hoje.weekday())
        fim_semana = inicio_semana + timedelta(days=7)
        query["data_limite"] = {
            "$gte": datetime(inicio_semana.year, inicio_semana.month, inicio_semana.day),
            "$lt": datetime(fim_semana.year, fim_semana.month, fim_semana.day)
        }
    elif periodo_filter == "Vencidas":
        query["data_limite"] = {"$lt": datetime.now()}
        if "status" not in query:
            query["status"] = {"$in": ["pendente", "em_andamento"]}
    
    pendencias = list(pendencias_coll.find(query).sort("data_limite", 1))
    
    if not pendencias:
        st.info("✅ Nenhuma pendência encontrada para você!")
        return
    
    # Resumo
    pendentes = sum(1 for p in pendencias if p['status'] == 'pendente')
    em_andamento = sum(1 for p in pendencias if p['status'] == 'em_andamento')
    concluidas = sum(1 for p in pendencias if p['status'] == 'concluida')
    vencidas = sum(1 for p in pendencias if p['data_limite'] < datetime.now() and p['status'] in ['pendente', 'em_andamento'])
    
    col1, col2, col3, col4 = st.columns(4)
    col1.metric("⏳ Pendentes", pendentes)
    col2.metric("🔄 Em Andamento", em_andamento)
    col3.metric("✅ Concluídas", concluidas)
    col4.metric("⚠️ Vencidas", vencidas)
    
    st.divider()
    
    # Cards de pendências
    for pendencia in pendencias:
        vencida = pendencia['data_limite'] < datetime.now() and pendencia['status'] in ['pendente', 'em_andamento']
        
        prioridade_icon = "🔴" if pendencia['prioridade'] == 'urgente' else "🟡" if pendencia['prioridade'] == 'alta' else "🟢"
        status_icon = "⏳" if pendencia['status'] == 'pendente' else "🔄" if pendencia['status'] == 'em_andamento' else "✅"
        
        titulo_expander = f"{prioridade_icon} {status_icon} {pendencia['titulo']}"
        if vencida:
            titulo_expander = f"⚠️ VENCIDA - {titulo_expander}"
        
        with st.expander(titulo_expander, expanded=vencida):
            col1, col2 = st.columns([3, 1])
            
            with col1:
                st.markdown(f"**📝 Descrição:** {pendencia['descricao']}")
                
                # Data limite
                data_limite_str = pendencia['data_limite'].strftime('%d/%m/%Y')
                if vencida:
                    dias_atraso = (datetime.now() - pendencia['data_limite']).days
                    st.error(f"⚠️ **VENCIDA HÁ {dias_atraso} DIAS!** | Data limite: {data_limite_str}")
                else:
                    st.info(f"📅 **Data Limite:** {data_limite_str}")
                
                # Solicitante
                st.write(f"👤 **Solicitante:** {pendencia.get('solicitante_nome', pendencia['solicitante'])}")
                
                # Condomínio relacionado
                if pendencia.get("condominio_relacionado_nome"):
                    st.write(f"🏢 **Condomínio:** {pendencia['condominio_relacionado_nome']}")
                elif pendencia.get("cliente_relacionado_nome"):
                    st.write(f"👤 **Cliente:** {pendencia['cliente_relacionado_nome']}")
                
                # Data de criação
                st.caption(f"🕐 Criada em: {formatar_data_hora(pendencia['data_criacao'])}")
                
                # Histórico
                if pendencia.get("historico"):
                    with st.expander("📋 Ver Histórico"):
                        for h in pendencia["historico"]:
                            st.write(f"• {formatar_data_hora(h['data'])} - {h['acao']} por {h['usuario']}")
            
            with col2:
                st.markdown("**Ações:**")
                
                if pendencia["status"] == "pendente":
                    if st.button("▶️ Iniciar", key=f"start_{pendencia['_id']}", use_container_width=True):
                        pendencias_coll.update_one(
                            {"_id": pendencia["_id"]},
                            {
                                "$set": {
                                    "status": "em_andamento",
                                    "data_inicio": agora_brasilia()
                                },
                                "$push": {
                                    "historico": {
                                        "acao": "Pendência iniciada",
                                        "data": agora_brasilia(),
                                        "usuario": nome_usuario,
                                        "detalhes": "Trabalho iniciado"
                                    }
                                }
                            }
                        )
                        st.success("✅ Pendência iniciada!")
                        st.rerun()
                
                elif pendencia["status"] == "em_andamento":
                    observacao = st.text_area(
                        "Observação de conclusão:",
                        key=f"obs_{pendencia['_id']}",
                        height=60,
                        placeholder="Descreva o que foi feito..."
                    )
                    if st.button("✅ Concluir", key=f"done_{pendencia['_id']}", use_container_width=True, type="primary"):
                        pendencias_coll.update_one(
                            {"_id": pendencia["_id"]},
                            {
                                "$set": {
                                    "status": "concluida",
                                    "data_conclusao": agora_brasilia(),
                                    "concluido_por": nome_usuario,
                                    "observacao_conclusao": observacao
                                },
                                "$push": {
                                    "historico": {
                                        "acao": "Pendência concluída",
                                        "data": agora_brasilia(),
                                        "usuario": nome_usuario,
                                        "detalhes": observacao if observacao else "Concluída sem observações"
                                    }
                                }
                            }
                        )
                        st.success("✅ Pendência concluída!")
                        st.balloons()
                        st.rerun()

# ============================================================================
# 📋 TODAS AS PENDÊNCIAS (VISÃO GERENCIAL)
# ============================================================================
def mostrar_todas_pendencias(pendencias_coll, clientes_collection):
    """Visão geral de TODAS as pendências - perfis com permissão"""
    st.subheader("📋 Todas as Pendências")
    
    perfil = st.session_state.get("perfil", "")
    
    # Filtros
    col1, col2, col3 = st.columns(3)
    
    with col1:
        status_filter = st.multiselect(
            "Status:",
            ["pendente", "em_andamento", "concluida"],
            default=["pendente", "em_andamento"],
            key="todas_status"
        )
    
    with col2:
        usuarios = obter_usuarios_disponiveis(clientes_collection)
        responsaveis_opcoes = [f"{u['nome']} ({u['perfil_nome']})" for u in usuarios]
        responsavel_filter = st.multiselect(
            "Responsável:",
            responsaveis_opcoes,
            key="todas_resp"
        )
    
    with col3:
        prioridade_filter = st.multiselect(
            "Prioridade:",
            ["baixa", "média", "alta", "urgente"],
            key="todas_prioridade"
        )
    
    # Construir query
    query = {}
    if status_filter:
        query["status"] = {"$in": status_filter}
    if prioridade_filter:
        query["prioridade"] = {"$in": prioridade_filter}
    if responsavel_filter:
        logins = []
        for u in usuarios:
            label = f"{u['nome']} ({u['perfil_nome']})"
            if label in responsavel_filter:
                logins.append(u['login'] if u['login'] else u['perfil'])
        if logins:
            query["responsavel"] = {"$in": logins}
    
    pendencias = list(pendencias_coll.find(query).sort("data_limite", 1))
    
    if not pendencias:
        st.info("📭 Nenhuma pendência encontrada!")
        return
    
    # Dashboard
    total = len(pendencias)
    pendentes = sum(1 for p in pendencias if p['status'] == 'pendente')
    em_andamento = sum(1 for p in pendencias if p['status'] == 'em_andamento')
    concluidas = sum(1 for p in pendencias if p['status'] == 'concluida')
    vencidas = sum(1 for p in pendencias if p['data_limite'] < datetime.now() and p['status'] in ['pendente', 'em_andamento'])
    
    col1, col2, col3, col4, col5 = st.columns(5)
    col1.metric("📊 Total", total)
    col2.metric("⏳ Pendentes", pendentes)
    col3.metric("🔄 Em Andamento", em_andamento)
    col4.metric("✅ Concluídas", concluidas)
    col5.metric("⚠️ Vencidas", vencidas)
    
    st.divider()
    
    # Lista
    for pendencia in pendencias:
        vencida = pendencia['data_limite'] < datetime.now() and pendencia['status'] in ['pendente', 'em_andamento']
        
        prioridade_icon = "🔴" if pendencia['prioridade'] == 'urgente' else "🟡" if pendencia['prioridade'] == 'alta' else "🟢"
        status_icon = "⏳" if pendencia['status'] == 'pendente' else "🔄" if pendencia['status'] == 'em_andamento' else "✅"
        
        titulo = f"{prioridade_icon} {status_icon} {pendencia['titulo']} - {pendencia['responsavel']}"
        if vencida:
            titulo = f"⚠️ VENCIDA - {titulo}"
        
        with st.expander(titulo, expanded=False):
            col1, col2 = st.columns([3, 1])
            
            with col1:
                st.write(f"**Descrição:** {pendencia['descricao']}")
                st.write(f"**Responsável:** {pendencia['responsavel']}")
                st.write(f"**Solicitante:** {pendencia.get('solicitante_nome', pendencia['solicitante'])}")
                st.write(f"**Data Limite:** {pendencia['data_limite'].strftime('%d/%m/%Y')}")
                
                if pendencia.get("condominio_relacionado_nome"):
                    st.write(f"🏢 **Condomínio:** {pendencia['condominio_relacionado_nome']}")
                elif pendencia.get("cliente_relacionado_nome"):
                    st.write(f"👤 **Cliente:** {pendencia['cliente_relacionado_nome']}")
                
                st.caption(f"🕐 Criada em: {formatar_data_hora(pendencia['data_criacao'])}")
                
                if pendencia.get("data_conclusao"):
                    st.write(f"✅ **Concluída em:** {formatar_data_hora(pendencia['data_conclusao'])}")
                    st.write(f"👤 **Concluída por:** {pendencia.get('concluido_por', 'N/A')}")
                
                if pendencia.get("observacao_conclusao"):
                    st.write(f"📝 **Obs conclusão:** {pendencia['observacao_conclusao']}")
                
                if vencida:
                    dias_atraso = (datetime.now() - pendencia['data_limite']).days
                    st.error(f"⚠️ Vencida há {dias_atraso} dias!")
            
            with col2:
                if pendencia['status'] != 'concluida':
                    if st.button("❌ Cancelar", key=f"cancel_all_{pendencia['_id']}"):
                        pendencias_coll.update_one(
                            {"_id": pendencia["_id"]},
                            {
                                "$set": {
                                    "status": "concluida",
                                    "data_conclusao": agora_brasilia(),
                                    "concluido_por": st.session_state.get("nome_usuario", "admin"),
                                    "observacao_conclusao": "Cancelada pelo gestor"
                                },
                                "$push": {
                                    "historico": {
                                        "acao": "Pendência cancelada",
                                        "data": agora_brasilia(),
                                        "usuario": st.session_state.get("nome_usuario", "admin"),
                                        "detalhes": "Cancelada pela gestão"
                                    }
                                }
                            }
                        )
                        st.success("✅ Pendência cancelada!")
                        st.rerun()

# ============================================================================
# 📅 CALENDÁRIO MENSAL
# ============================================================================
def mostrar_calendario_pendencias(pendencias_coll):
    """Calendário de pendências por data limite"""
    st.subheader("📅 Calendário de Pendências")
    
    if "mes_pendencias" not in st.session_state:
        st.session_state.mes_pendencias = agora_brasilia().date().replace(day=1)
    
    mes_atual = st.session_state.mes_pendencias
    ano = mes_atual.year
    mes = mes_atual.month
    
    # Navegação
    col1, col2, col3 = st.columns([1, 3, 1])
    with col1:
        if st.button("◀️ Mês Anterior", key="prev_mes_pend"):
            st.session_state.mes_pendencias = (mes_atual.replace(day=1) - timedelta(days=1)).replace(day=1)
            st.rerun()
    with col2:
        nome_mes = calendar.month_name[mes]
        st.markdown(f"### {nome_mes.capitalize()} / {ano}")
    with col3:
        if st.button("Mês Seguinte ▶️", key="next_mes_pend"):
            st.session_state.mes_pendencias = (mes_atual.replace(day=28) + timedelta(days=4)).replace(day=1)
            st.rerun()
    
    # Buscar pendências do mês
    inicio_mes = datetime(ano, mes, 1)
    ultimo_dia = calendar.monthrange(ano, mes)[1]
    fim_mes = datetime(ano, mes, ultimo_dia, 23, 59, 59)
    
    pendencias_mes = list(pendencias_coll.find({
        "data_limite": {"$gte": inicio_mes, "$lte": fim_mes},
        "status": {"$ne": "concluida"}
    }).sort("data_limite", 1))
    
    pend_por_dia = defaultdict(list)
    for p in pendencias_mes:
        dia = p['data_limite'].day
        pend_por_dia[dia].append(p)
    
    st.divider()
    
    if not pend_por_dia:
        st.info("✅ Nenhuma pendência ativa para este mês!")
        return
    
    st.write(f"### 📊 {len(pendencias_mes)} pendências ativas em {nome_mes.capitalize()}")
    
    for dia in sorted(pend_por_dia.keys()):
        pendencias_dia = pend_por_dia[dia]
        data = datetime(ano, mes, dia)
        vencido = data.date() < datetime.today().date()
        
        dias_semana = {
            'Monday': 'Segunda-feira', 'Tuesday': 'Terça-feira',
            'Wednesday': 'Quarta-feira', 'Thursday': 'Quinta-feira',
            'Friday': 'Sexta-feira', 'Saturday': 'Sábado', 'Sunday': 'Domingo'
        }
        dia_semana = dias_semana.get(data.strftime('%A'), data.strftime('%A'))
        
        titulo_dia = f"{'⚠️ ' if vencido else ''}📅 {data.strftime('%d/%m/%Y')} ({dia_semana}) - {len(pendencias_dia)} pendências"
        
        with st.expander(titulo_dia, expanded=vencido):
            for p in pendencias_dia:
                icon = "🔴" if p['prioridade'] == 'urgente' else "🟡" if p['prioridade'] == 'alta' else "🟢"
                status_icon = "⏳" if p['status'] == 'pendente' else "🔄"
                
                st.markdown(f"""
                {icon} {status_icon} **{p['titulo']}**  
                👤 Resp: {p['responsavel']} | 🕐 Criada: {formatar_data_hora(p.get('data_criacao'))}  
                📝 {p['descricao'][:80]}...  
                {'⚠️ **VENCIDA!**' if vencido else ''}
                """)
                st.divider()
