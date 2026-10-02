import streamlit as st
from datetime import datetime
from pymongo import MongoClient
import urllib.parse
from bson.objectid import ObjectId

# ✅ CORREÇÃO: st.set_page_config() DEVE ser a primeira chamada Streamlit
st.set_page_config(page_title="CRM Eventos", layout="wide")

# --- Funções de Conexão (Padrão MongoDB) ---
def get_db_client():
    """Retorna o cliente MongoDB configurado"""
    try:
        # Tentativa de buscar estrutura aninhada (comum no Streamlit Cloud)
        username = st.secrets["mongo"]["MONGO_USERNAME"]
        password = st.secrets["mongo"]["MONGO_PASSWORD"]
        cluster_url = st.secrets["mongo"]["MONGO_CLUSTER_URL"]
    except KeyError:
        # Fallback para variáveis planas
        username = st.secrets.get("MONGO_USERNAME", "")
        password = st.secrets.get("MONGO_PASSWORD", "")
        cluster_url = st.secrets.get("MONGO_CLUSTER_URL", "")
    
    u = urllib.parse.quote_plus(username)
    p = urllib.parse.quote_plus(password)
    uri = f"mongodb+srv://{u}:{p}@{cluster_url}/?retryWrites=true&w=majority"
    return MongoClient(uri)

def get_leads_collection():
    """Retorna coleção de Leads/Eventos"""
    client = get_db_client()
    return client.crm_db.leads

def update_lead_status(lead_id, novo_status, convertido=False):
    """Atualiza o status ou marca como convertido no MongoDB"""
    try:
        collection = get_leads_collection()
        update_data = {"status": novo_status}
        if convertido:
            update_data["convertido"] = True
            update_data["status"] = "✅ Convertido"
        
        result = collection.update_one(
            {"_id": ObjectId(lead_id)}, 
            {"$set": update_data}
        )
        return result.modified_count > 0
    except Exception as e:
        st.error(f"Erro ao atualizar: {e}")
        return False

def delete_lead(lead_id):
    """Exclui um lead do banco de dados"""
    try:
        collection = get_leads_collection()
        result = collection.delete_one({"_id": ObjectId(lead_id)})
        return result.deleted_count > 0
    except Exception as e:
        st.error(f"Erro ao excluir: {e}")
        return False

def update_lead_observacoes(lead_id, novas_observacoes):
    """Atualiza apenas as observações de um lead"""
    try:
        collection = get_leads_collection()
        result = collection.update_one(
            {"_id": ObjectId(lead_id)},
            {"$set": {"observacoes": novas_observacoes}}
        )
        return result.modified_count > 0
    except Exception as e:
        st.error(f"Erro ao atualizar observações: {e}")
        return False

def update_lead_data_proximo_contato(lead_id, nova_data):
    """Atualiza apenas a data de próximo contato"""
    try:
        collection = get_leads_collection()
        if nova_data is None:
            # Remover data de próximo contato
            result = collection.update_one(
                {"_id": ObjectId(lead_id)},
                {"$unset": {"data_proximo_contato": ""}}
            )
        else:
            result = collection.update_one(
                {"_id": ObjectId(lead_id)},
                {"$set": {"data_proximo_contato": datetime.combine(nova_data, datetime.min.time())}}
            )
        return result.modified_count > 0
    except Exception as e:
        st.error(f"Erro ao atualizar data: {e}")
        return False

def update_lead_potencial(lead_id, potencial_condominio, qtd_apartamentos, potencial_servicos, obs_potencial):
    """Atualiza os dados de potencial do condomínio"""
    try:
        collection = get_leads_collection()
        update_data = {
            "potencial_condominio": potencial_condominio if potencial_condominio != "Não avaliado" else None,
            "qtd_apartamentos": qtd_apartamentos if qtd_apartamentos and qtd_apartamentos > 0 else None,
            "potencial_servicos": potencial_servicos if potencial_servicos != "Não avaliado" else None,
            "obs_potencial": obs_potencial.strip() if obs_potencial else None
        }
        result = collection.update_one(
            {"_id": ObjectId(lead_id)},
            {"$set": update_data}
        )
        return result.modified_count > 0
    except Exception as e:
        st.error(f"Erro ao atualizar potencial: {e}")
        return False

def get_eventos_existentes():
    """Busca todos os nomes de eventos já cadastrados no banco"""
    try:
        collection = get_leads_collection()
        # Aggregation para obter nomes únicos de eventos
        pipeline = [
            {"$group": {"_id": "$evento"}},
            {"$sort": {"_id": 1}},
            {"$limit": 100}  # Limita a 100 eventos mais recentes
        ]
        resultados = list(collection.aggregate(pipeline))
        eventos = [r["_id"] for r in resultados if r["_id"]]
        return sorted(eventos)
    except Exception as e:
        st.warning(f"⚠️ Não foi possível carregar eventos anteriores: {e}")
        return []

# --- Módulo de Registro de Leads ---
def render_registro_lead():
    """Renderiza formulário de captura de leads em eventos"""
    st.title("🤝 Captura de Leads & Eventos")
    st.markdown("Registro de contatos realizados em feiras, eventos e visitas.")
    
    PRODUTOS = [
        "Conecta e Protege (Câmeras + Internet + Bônus)",
        "Câmeras de Segurança",
        "Recarga de Carros Elétricos",
        "Conectividade (Internet)",
        "Automação Residencial",
        "Automação Predial"
    ]

    # Busca eventos existentes para autocomplete
    eventos_existentes = get_eventos_existentes()

    with st.form("form_lead_evento", clear_on_submit=True):
        col1, col2 = st.columns(2)
        
        with col1:
            st.subheader("📋 Dados do Contato")
            tipo_contato = st.selectbox("Tipo de Contato *", ["Síndico / Cliente", "Parceiro Comercial", "Outros"])
            nome_contato = st.text_input("Nome do Contato *", max_chars=100)
            
            # ✅ Campo específico para Condomínio
            nome_condominio = st.text_input("🏢 Nome do Condomínio (Se houver)", max_chars=100, 
                                          help="Preencha apenas se for um condomínio residencial")
            
            # ✅ Campo específico para Empresa
            nome_empresa = st.text_input("🏭 Nome da Empresa (Se houver)", max_chars=100,
                                       help="Preencha apenas se for uma empresa parceira/comercial")
            
            telefone = st.text_input("Telefone / WhatsApp *", max_chars=20, placeholder="(00) 00000-0000")
            email = st.text_input("E-mail", max_chars=100)
            
        with col2:
            st.subheader("📅 Dados do Evento & Agenda")
            
            # ✅ Campo de evento com autocomplete/sugestão
            st.markdown("**Nome do Evento / Origem ***")
            st.caption("💡 Comece a digitar para ver sugestões de eventos já cadastrados")
            
            if eventos_existentes:
                # Opção 1: Selectbox com filtro manual (mais simples)
                opcoes_evento = ["✨ Novo Evento..."] + eventos_existentes
                nome_evento_selecionado = st.selectbox(
                    "Selecione ou digite o evento:",
                    opcoes_evento,
                    index=0,
                    key="selectbox_evento"
                )
                
                if nome_evento_selecionado == "✨ Novo Evento...":
                    nome_evento = st.text_input(
                        "Digite o nome do novo evento:",
                        max_chars=100,
                        placeholder="Ex: Conferência de Síndicos RJ",
                        key="novo_evento_input"
                    )
                else:
                    nome_evento = nome_evento_selecionado
            else:
                # Fallback se não houver eventos anteriores
                nome_evento = st.text_input(
                    "Nome do Evento / Origem *",
                    value="Feira de Condomínios",
                    max_chars=100,
                    key="fallback_evento"
                )
            
            data_evento = st.date_input("Data do Contato", value=datetime.now())
            
            # ✅ Data para Próximo Contato agora é OPCIONAL
            st.markdown("**📅 Data para Próximo Contato (Touch)**")
            st.caption("💡 Deixe em branco se não houver necessidade de contato imediato (ex: parceiros)")
            
            usar_data_proximo = st.checkbox("Definir data para próximo contato", value=True)
            
            if usar_data_proximo:
                data_proximo_contato = st.date_input(
                    "Selecione a data:", 
                    value=datetime.now(),
                    key="data_proximo_input"
                )
            else:
                data_proximo_contato = None
            
            nivel_interesse = st.selectbox("Nível de Interesse", ["🔥 Quente", "Morno", "❄️ Frio"])
            status_lead = st.selectbox("Status Inicial", ["Novo", "Em Negociação", "Aguardando Retorno", "Parceria"])
        
        # ✅ NOVO: Bloco de Potencial do Condomínio (só aparece para Síndico/Cliente)
        potencial_condominio = None
        qtd_apartamentos = None
        potencial_servicos = None
        obs_potencial = None
        
        if tipo_contato == "Síndico / Cliente":
            st.subheader("🏢 Potencial do Condomínio")
            st.caption("Avalie a capacidade de exploração comercial deste condomínio.")
            
            col_pot1, col_pot2, col_pot3 = st.columns(3)
            
            with col_pot1:
                potencial_condominio = st.selectbox(
                    "Potencial do Condomínio",
                    ["Alto", "Médio", "Baixo", "Não avaliado"],
                    index=3,
                    help="Avaliação geral do potencial comercial do condomínio"
                )
            
            with col_pot2:
                qtd_apartamentos = st.number_input(
                    "Qtd. média de apartamentos",
                    min_value=0,
                    max_value=10000,
                    value=0,
                    step=10,
                    help="Quantidade estimada de unidades. Deixe 0 se não souber."
                )
            
            with col_pot3:
                potencial_servicos = st.selectbox(
                    "Potencial de Serviços",
                    ["Alto", "Médio", "Baixo", "Não avaliado"],
                    index=3,
                    help="Capacidade de exploração: automação, internet, carregador, etc."
                )
            
            obs_potencial = st.text_input(
                "Observação sobre o potencial (opcional)",
                max_chars=200,
                placeholder="Ex: Condomínio novo, síndico aberto a propostas, 3 torres..."
            )
        
        st.subheader("🛒 Interesse em Produtos")
        produtos_interesse = st.multiselect(
            "Quais produtos despertaram interesse?", 
            PRODUTOS,
            help="Selecione um ou mais produtos discutidos"
        )
        
        st.subheader("📝 Observações da Conversa")
        observacoes = st.text_area(
            "Detalhes da evolução da conversa", 
            height=100, 
            placeholder="Ex: Síndico reclamou da internet atual. Quer orçamento para 10 câmeras. Decisão até dia 30..."
        )
        
        col_submit, col_novo = st.columns([1, 1])
        
        with col_submit:
            submitted = st.form_submit_button("💾 Salvar Lead", type="primary", use_container_width=True)
        
        with col_novo:
            novo_cadastro = st.form_submit_button("🔄 Novo Cadastro", use_container_width=True)
        
        if submitted:
            # Validação simples
            if not all([nome_contato, telefone, nome_evento]):
                st.error("⚠️ Preencha os campos obrigatórios (Nome, Telefone e Evento)!")
            else:
                lead_data = {
                    "tipo_contato": tipo_contato,
                    "nome_contato": nome_contato.strip().upper(),
                    "nome_condominio": nome_condominio.strip().upper() if nome_condominio else None,
                    "nome_empresa": nome_empresa.strip().upper() if nome_empresa else None,
                    "telefone": telefone.strip(),
                    "email": email.strip() if email else None,
                    "evento": nome_evento.strip(),
                    "data_evento": datetime.combine(data_evento, datetime.min.time()),
                    "data_proximo_contato": datetime.combine(data_proximo_contato, datetime.min.time()) if data_proximo_contato else None,
                    "nivel_interesse": nivel_interesse,
                    "status": status_lead,
                    # ✅ NOVOS CAMPOS DE POTENCIAL
                    "potencial_condominio": potencial_condominio if potencial_condominio != "Não avaliado" else None,
                    "qtd_apartamentos": qtd_apartamentos if qtd_apartamentos and qtd_apartamentos > 0 else None,
                    "potencial_servicos": potencial_servicos if potencial_servicos != "Não avaliado" else None,
                    "obs_potencial": obs_potencial.strip() if obs_potencial else None,
                    "produtos_interesse": produtos_interesse,
                    "observacoes": observacoes.strip(),
                    "data_cadastro": datetime.now(),
                    "ativo": True,
                    "convertido": False
                }
                
                try:
                    collection = get_leads_collection()
                    result = collection.insert_one(lead_data)
                    st.success(f"✅ Lead '{nome_contato}' registrado com sucesso! ID: {result.inserted_id}")
                    st.balloons()
                except Exception as e:
                    st.error(f"❌ Erro ao salvar: {e}")
        
        if novo_cadastro:
            st.info("🔄 Formulário limpo para novo cadastro!")
            st.rerun()

# --- Visualização e Gestão de Leads (Agenda) ---
def render_agenda_leads():
    """Exibe lista de leads com barra de pesquisa e permite atualização"""
    st.title("📋 Agenda & Acompanhamento de Leads")
    st.markdown("Pesquise e gerencie seus contatos. Use os filtros abaixo para encontrar leads específicos.")

    try:
        collection = get_leads_collection()
    except Exception as e:
        st.error(f"❌ Erro ao conectar ao MongoDB: {e}")
        return

    # --- Barra de Pesquisa ---
    with st.expander("🔍 Opções de Busca Avançada", expanded=True):
        col_search1, col_search2 = st.columns(2)
        
        with col_search1:
            search_nome = st.text_input("👤 Nome do Contato", placeholder="Digite parte do nome...")
            search_condo_emp = st.text_input("🏢 Condomínio ou Empresa", placeholder="Ex: Residencial Sol, Tech Solutions...")
        
        with col_search2:
            search_telefone = st.text_input("📞 Telefone", placeholder="Ex: 99999-0000")
            search_evento = st.text_input("📅 Evento/Origem", placeholder="Ex: Feira de Síndicos...")
        
        # ✅ NOVO: Filtro por Potencial do Condomínio
        col_filtro1, col_filtro2 = st.columns(2)
        
        with col_filtro1:
            filtro_potencial = st.multiselect(
                "🏢 Filtrar por Potencial do Condomínio:",
                options=["Alto", "Médio", "Baixo"],
                default=[]
            )
        
        with col_filtro2:
            filtro_potencial_servicos = st.multiselect(
                "🛠️ Filtrar por Potencial de Serviços:",
                options=["Alto", "Médio", "Baixo"],
                default=[]
            )

    # Filtro de Status (Mantido)
    filtro_status = st.multiselect(
        "Filtrar por Status:", 
        options=["Novo", "Em Negociação", "Aguardando Retorno", "Parceria", "✅ Convertido"],
        default=["Novo", "Em Negociação", "Aguardando Retorno"]
    )

    # --- Construção da Query Dinâmica ---
    query = {}
    
    # 1. Filtro de Status
    if filtro_status:
        query["status"] = {"$in": filtro_status}

    # 2. Filtros de Texto (Regex case-insensitive)
    if search_nome:
        query["nome_contato"] = {"$regex": search_nome, "$options": "i"}
    
    if search_telefone:
        query["telefone"] = {"$regex": search_telefone, "$options": "i"}
        
    if search_evento:
        query["evento"] = {"$regex": search_evento, "$options": "i"}
        
    if search_condo_emp:
        # Busca tanto no campo condomínio quanto no campo empresa
        or_condition = [
            {"nome_condominio": {"$regex": search_condo_emp, "$options": "i"}},
            {"nome_empresa": {"$regex": search_condo_emp, "$options": "i"}}
        ]
        
        # Se já existia outro filtro (como status), precisamos usar $and
        if query:
            query = {"$and": [query, {"$or": or_condition}]}
        else:
            query["$or"] = or_condition
    
    # ✅ NOVO: Filtro por Potencial do Condomínio
    if filtro_potencial:
        if "$and" in query:
            query["$and"].append({"potencial_condominio": {"$in": filtro_potencial}})
        else:
            and_list = [query] if query else []
            and_list.append({"potencial_condominio": {"$in": filtro_potencial}})
            query = {"$and": and_list}
    
    # ✅ NOVO: Filtro por Potencial de Serviços
    if filtro_potencial_servicos:
        if "$and" in query:
            query["$and"].append({"potencial_servicos": {"$in": filtro_potencial_servicos}})
        else:
            and_list = [query] if query else []
            and_list.append({"potencial_servicos": {"$in": filtro_potencial_servicos}})
            query = {"$and": and_list}

    try:
        # Ordenação: Data primeiro (ascendente), depois Nome
        leads_cursor = collection.find(query).sort([
            ("data_proximo_contato", 1), 
            ("nome_contato", 1)
        ]).limit(100)
        
        leads = list(leads_cursor)
        
    except Exception as e:
        st.error(f"❌ Erro ao buscar leads: {e}")
        st.write(f"Detalhe do erro (possível conflito de query): {e}")
        return

    if not leads:
        st.warning("⚠️ Nenhum lead encontrado com os critérios selecionados.")
    else:
        st.info(f"🔎 Encontrados {len(leads)} registro(s).")
        
        # Separar leads com e sem data para visualização
        leads_com_data = []
        leads_sem_data = []
        
        for lead in leads:
            if lead.get("data_proximo_contato"):
                leads_com_data.append(lead)
            else:
                leads_sem_data.append(lead)
        
        # Exibir leads com data primeiro
        if leads_com_data:
            st.subheader("📅 Agenda - Próximos Contatos")
            for lead in leads_com_data:
                display_lead_card(lead, collection)
        
        # Exibir pool de leads sem data
        if leads_sem_data:
            st.subheader("🗄️ Pool - Leads Sem Data Agendada")
            st.caption("Contatos que não possuem follow-up agendado.")
            for lead in leads_sem_data:
                display_lead_card(lead, collection, is_pool=True)

def display_lead_card(lead, collection, is_pool=False):
    """Função auxiliar para exibir card de lead"""
    # Formatação de datas com segurança
    data_contato = lead.get("data_proximo_contato")
    if data_contato:
        data_str = data_contato.strftime("%d/%m/%Y")
        hoje = datetime.now().date()
        icono_data = "📅" if data_contato.date() >= hoje else "⏰"
        urgency_badge = " ⚠️ URGENTE" if data_contato.date() < hoje else ""
    else:
        data_str = "Sem data agendada"
        icono_data = "⚪"
        urgency_badge = ""
    
    # ✅ CORREÇÃO CRÍTICA: data_evento pode ser None!
    data_evento = lead.get("data_evento")
    if data_evento:
        data_evento_str = data_evento.strftime("%d/%m/%Y")
    else:
        data_evento_str = "N/A"

    label_expander = f"{icono_data} {lead['nome_contato']} - {data_str} ({lead.get('nivel_interesse', '')}) {urgency_badge}"

    with st.expander(label_expander):
        col_info, col_actions = st.columns([2, 1])
        
        with col_info:
            st.write(f"**📞 Telefone:** {lead.get('telefone')}")
            
            # ✅ Exibir Condomínio ou Empresa conforme o caso
            if lead.get('nome_condominio'):
                st.write(f"**🏢 Condomínio:** {lead.get('nome_condominio')}")
            if lead.get('nome_empresa'):
                st.write(f"**🏭 Empresa:** {lead.get('nome_empresa')}")
            if not lead.get('nome_condominio') and not lead.get('nome_empresa'):
                st.write(f"**🏢 Organização:** N/A")
            
            st.write(f"**🛒 Produtos:** {', '.join(lead.get('produtos_interesse', []))}")
            
            # ✅ NOVO: Exibir Potencial do Condomínio
            if lead.get('potencial_condominio') or lead.get('qtd_apartamentos') or lead.get('potencial_servicos'):
                st.markdown("**🏢 Potencial do Condomínio:**")
                
                col_p1, col_p2, col_p3 = st.columns(3)
                
                with col_p1:
                    pot = lead.get('potencial_condominio', 'N/A')
                    emoji_pot = {"Alto": "🟢", "Médio": "🟡", "Baixo": "🔴"}.get(pot, "⚪")
                    st.metric("Potencial", f"{emoji_pot} {pot}")
                
                with col_p2:
                    qtd = lead.get('qtd_apartamentos')
                    st.metric("Apartamentos", qtd if qtd else "N/A")
                
                with col_p3:
                    pot_serv = lead.get('potencial_servicos', 'N/A')
                    emoji_serv = {"Alto": "🟢", "Médio": "🟡", "Baixo": "🔴"}.get(pot_serv, "⚪")
                    st.metric("Potencial Serviços", f"{emoji_serv} {pot_serv}")
                
                if lead.get('obs_potencial'):
                    st.caption(f"💬 {lead.get('obs_potencial')}")
                
                st.divider()
            
            # ✅ Campo de observações editável
            st.write("**📝 Observações:**")
            observacoes_atuais = lead.get('observacoes', 'Sem observações')
            
            with st.form(key=f"form_obs_{lead['_id']}"):
                novas_observacoes = st.text_area(
                    "Editar observações:",
                    value=observacoes_atuais,
                    height=80,
                    key=f"obs_textarea_{lead['_id']}"
                )
                
                col_upd, col_del = st.columns([1, 1])
                
                with col_upd:
                    submit_obs = st.form_submit_button("🔄 Atualizar Obs", use_container_width=True)
                    
                    if submit_obs:
                        if update_lead_observacoes(lead['_id'], novas_observacoes.strip()):
                            st.success("✅ Observações atualizadas!")
                            st.rerun()
                        else:
                            st.error("❌ Falha ao atualizar observações.")
                
                with col_del:
                    pass  # Botão de exclusão será adicionado abaixo
            
            st.write(f"**📅 Evento:** {lead.get('evento')} em {data_evento_str}")
            st.write(f"**🔄 Status Atual:** {lead.get('status')}")
            if lead.get('convertido'):
                st.success("**🏆 CLIENTE CONVERTIDO**")

        with col_actions:
            st.markdown("### Ações")
            
            # ✅ Botão para definir/editar/remover data de próximo contato
            if not lead.get('data_proximo_contato'):
                if st.button("📅 Definir Data de Contato", key=f"set_date_{lead['_id']}", use_container_width=True):
                    if "editing_date_lead" not in st.session_state:
                        st.session_state.editing_date_lead = str(lead['_id'])
                    st.rerun()
            else:
                col_edit, col_remove = st.columns([1, 1])
                with col_edit:
                    if st.button("✏️ Editar", key=f"edit_date_{lead['_id']}", use_container_width=True):
                        if "editing_date_lead" not in st.session_state:
                            st.session_state.editing_date_lead = str(lead['_id'])
                        st.rerun()
                
                with col_remove:
                    if st.button("🚫 Remover Data", key=f"remove_date_{lead['_id']}", use_container_width=True, type="secondary"):
                        if update_lead_data_proximo_contato(lead['_id'], None):
                            st.success("✅ Data removida! Lead movido para o Pool.")
                            st.rerun()
                        else:
                            st.error("❌ Falha ao remover data.")
            
            # Mostrar editor de data se ativado
            if "editing_date_lead" in st.session_state and st.session_state.editing_date_lead == str(lead['_id']):
                with st.form(key=f"form_date_{lead['_id']}"):
                    nova_data = st.date_input(
                        "Nova data para contato:",
                        value=lead.get('data_proximo_contato', datetime.now()).date() if lead.get('data_proximo_contato') else datetime.now(),
                        key=f"date_input_{lead['_id']}"
                    )
                    
                    col_save, col_cancel = st.columns([1, 1])
                    with col_save:
                        if st.form_submit_button("💾 Salvar Data", use_container_width=True):
                            if update_lead_data_proximo_contato(lead['_id'], nova_data):
                                st.success("✅ Data atualizada!")
                                del st.session_state.editing_date_lead
                                st.rerun()
                            else:
                                st.error("❌ Falha ao atualizar data.")
                    
                    with col_cancel:
                        if st.form_submit_button("❌ Cancelar", use_container_width=True):
                            del st.session_state.editing_date_lead
                            st.rerun()
            
            # ✅ NOVO: Botão para editar Potencial do Condomínio
            if st.button("🏢 Editar Potencial", key=f"edit_pot_{lead['_id']}", use_container_width=True):
                if "editing_potencial_lead" not in st.session_state:
                    st.session_state.editing_potencial_lead = str(lead['_id'])
                st.rerun()
            
            # Editor de Potencial
            if "editing_potencial_lead" in st.session_state and st.session_state.editing_potencial_lead == str(lead['_id']):
                with st.form(key=f"form_pot_{lead['_id']}"):
                    st.markdown("**🏢 Editar Potencial do Condomínio**")
                    
                    pot_atual = lead.get('potencial_condominio') or "Não avaliado"
                    pot_serv_atual = lead.get('potencial_servicos') or "Não avaliado"
                    
                    opcoes_pot = ["Alto", "Médio", "Baixo", "Não avaliado"]
                    
                    novo_pot = st.selectbox(
                        "Potencial do Condomínio",
                        opcoes_pot,
                        index=opcoes_pot.index(pot_atual) if pot_atual in opcoes_pot else 3,
                        key=f"pot_input_{lead['_id']}"
                    )
                    
                    nova_qtd = st.number_input(
                        "Qtd. média de apartamentos",
                        min_value=0,
                        max_value=10000,
                        value=lead.get('qtd_apartamentos') or 0,
                        step=10,
                        key=f"qtd_input_{lead['_id']}"
                    )
                    
                    novo_pot_serv = st.selectbox(
                        "Potencial de Serviços",
                        opcoes_pot,
                        index=opcoes_pot.index(pot_serv_atual) if pot_serv_atual in opcoes_pot else 3,
                        key=f"pot_serv_input_{lead['_id']}"
                    )
                    
                    nova_obs_pot = st.text_input(
                        "Observação sobre o potencial",
                        value=lead.get('obs_potencial') or "",
                        max_chars=200,
                        key=f"obs_pot_input_{lead['_id']}"
                    )
                    
                    col_save_pot, col_cancel_pot = st.columns([1, 1])
                    with col_save_pot:
                        if st.form_submit_button("💾 Salvar Potencial", use_container_width=True):
                            if update_lead_potencial(lead['_id'], novo_pot, nova_qtd, novo_pot_serv, nova_obs_pot):
                                st.success("✅ Potencial atualizado!")
                                del st.session_state.editing_potencial_lead
                                st.rerun()
                            else:
                                st.error("❌ Falha ao atualizar potencial.")
                    
                    with col_cancel_pot:
                        if st.form_submit_button("❌ Cancelar", use_container_width=True):
                            del st.session_state.editing_potencial_lead
                            st.rerun()
            
            # ✅ Botão de exclusão
            if st.button("🗑️ Excluir Lead", key=f"delete_{lead['_id']}", use_container_width=True, type="secondary"):
                if delete_lead(lead['_id']):
                    st.success("✅ Lead excluído com sucesso!")
                    st.rerun()
                else:
                    st.error("❌ Falha ao excluir lead.")
            
            st.divider()
            
            with st.form(key=f"form_update_{lead['_id']}"):
                is_convertido = st.checkbox("✅ Cliente Convertido", value=lead.get('convertido', False))
                
                status_options = ["Novo", "Em Negociação", "Aguardando Retorno", "Parceria", "✅ Convertido"]
                current_status = lead.get('status', 'Novo')
                
                # ✅ Segurança no index
                try:
                    status_index = status_options.index(current_status)
                except ValueError:
                    status_index = 0
                
                novo_status = st.selectbox(
                    "Alterar Status",
                    status_options,
                    index=status_index
                )
                
                submit_update = st.form_submit_button("Atualizar Status", use_container_width=True)
                
                if submit_update:
                    status_final = novo_status
                    flag_convertido = is_convertido
                    if is_convertido:
                        status_final = "✅ Convertido"
                    
                    if update_lead_status(lead['_id'], status_final, flag_convertido):
                        st.success("✅ Status atualizado!")
                        st.rerun()
                    else:
                        st.error("❌ Falha ao atualizar status.")

# --- Execução Principal ---
if __name__ == "__main__":
    # Criação de Abas
    tab1, tab2 = st.tabs(["📝 Cadastro de Leads", "📋 Agenda & Lista"])
    
    with tab1:
        render_registro_lead()
        
    with tab2:
        render_agenda_leads()
