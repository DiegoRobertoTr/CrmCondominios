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
        st.warning(f"️ Não foi possível carregar eventos anteriores: {e}")
        return []

# --- Módulo de Registro de Leads ---
def render_registro_lead():
    """Renderiza formulário de captura de leads em eventos"""
    st.title(" Captura de Leads & Eventos")
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
    
    with st.form("form_lead_evento"):
        col1, col2 = st.columns(2)
        
        with col1:
            st.subheader("📋 Dados do Contato")
            tipo_contato = st.selectbox("Tipo de Contato *", ["Síndico / Cliente", "Parceiro Comercial", "Outros"])
            nome_contato = st.text_input("Nome do Contato *", max_chars=100)
            nome_condominio = st.text_input("Nome do Condomínio (Se houver)", max_chars=100)
            telefone = st.text_input("Telefone / WhatsApp *", max_chars=20, placeholder="(00) 00000-0000")
            email = st.text_input("E-mail", max_chars=100)
            
        with col2:
            st.subheader("📍 Dados do Evento & Agenda")
            
            # ✅ NOVO: Campo de evento com autocomplete/sugestão
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
            
            # NOVO: Data para Próximo Contato (Touch)
            data_proximo_contato = st.date_input(
                "📅 Data para Próximo Contato (Touch)", 
                value=datetime.now(),
                help="Defina quando você deve entrar em contato novamente."
            )
            
            nivel_interesse = st.selectbox("Nível de Interesse", ["🔥 Quente", " Morno", "❄️ Frio"])
            status_lead = st.selectbox("Status Inicial", ["Novo", "Em Negociação", "Aguardando Retorno", "Parceria"])
        
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
        
        submitted = st.form_submit_button("💾 Salvar Lead", type="primary")
        
        if submitted:
            # Validação simples
            if not all([nome_contato, telefone, nome_evento]):
                st.error("⚠️ Preencha os campos obrigatórios (Nome, Telefone e Evento)!")
            else:
                lead_data = {
                    "tipo_contato": tipo_contato,
                    "nome_contato": nome_contato.strip().upper(),
                    "nome_condominio": nome_condominio.strip().upper() if nome_condominio else None,
                    "telefone": telefone.strip(),
                    "email": email.strip() if email else None,
                    "evento": nome_evento.strip(),
                    "data_evento": datetime.combine(data_evento, datetime.min.time()),
                    "data_proximo_contato": datetime.combine(data_proximo_contato, datetime.min.time()),
                    "nivel_interesse": nivel_interesse,
                    "status": status_lead,
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

# --- Visualização e Gestão de Leads (Agenda) ---
def render_agenda_leads():
    """Exibe lista de leads ordenada por prioridade de contato e permite atualização"""
    st.title("📋 Agenda & Acompanhamento de Leads")
    st.markdown("Lista organizada por data do próximo contato (mais urgentes no topo).")
    
    try:
        collection = get_leads_collection()
    except Exception as e:
        st.error(f"❌ Erro ao conectar ao MongoDB: {e}")
        return

    # Filtro opcional de status
    filtro_status = st.multiselect(
        "Filtrar por Status:", 
        options=["Novo", "Em Negociação", "Aguardando Retorno", "Parceria", "✅ Convertido"],
        default=["Novo", "Em Negociação", "Aguardando Retorno"]
    )

    query = {}
    if filtro_status:
        query["status"] = {"$in": filtro_status}

    try:
        leads = list(collection.find(query).sort("data_proximo_contato", 1).limit(50))
    except Exception as e:
        st.error(f"❌ Erro ao buscar leads: {e}")
        return

    if not leads:
        st.info("Nenhum lead encontrado com os filtros selecionados.")
    else:
        for lead in leads:
            # Formatação de datas com segurança
            data_contato = lead.get("data_proximo_contato")
            if data_contato:
                data_str = data_contato.strftime("%d/%m/%Y")
            else:
                data_str = "Não agendado"
            
            # ✅ CORREÇÃO CRÍTICA: data_evento pode ser None!
            data_evento = lead.get("data_evento")
            if data_evento:
                data_evento_str = data_evento.strftime("%d/%m/%Y")
            else:
                data_evento_str = "N/A"
            
            hoje = datetime.now().date()
            icono_data = "🔴" if data_contato and data_contato.date() < hoje else "🟢"
            
            label_expander = f"{icono_data} {lead['nome_contato']} - {data_str} ({lead.get('nivel_interesse', '')})"
            
            with st.expander(label_expander):
                col_info, col_action = st.columns([2, 1])
                
                with col_info:
                    st.write(f"**📞 Telefone:** {lead.get('telefone')}")
                    st.write(f"**🏢 Condomínio:** {lead.get('nome_condominio', 'N/A')}")
                    st.write(f"**🛒 Produtos:** {', '.join(lead.get('produtos_interesse', []))}")
                    st.write(f"**📝 Obs:** {lead.get('observacoes', 'Sem observações')}")
                    st.write(f"** Evento:** {lead.get('evento')} em {data_evento_str}")
                    st.write(f"**🔄 Status Atual:** {lead.get('status')}")
                    if lead.get('convertido'):
                        st.success("**🎉 CLIENTE CONVERTIDO**")

                with col_action:
                    st.markdown("### Ações")
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
                        
                        submit_update = st.form_submit_button("Atualizar", use_container_width=True)
                        
                        if submit_update:
                            status_final = novo_status
                            flag_convertido = is_convertido
                            if is_convertido:
                                status_final = "✅ Convertido"
                            
                            if update_lead_status(lead['_id'], status_final, flag_convertido):
                                st.success("Atualizado!")
                                st.rerun()
                            else:
                                st.error("Falha ao atualizar.")

# --- Execução Principal ---
if __name__ == "__main__":
    # ✅ CORREÇÃO: Removido st.set_page_config daqui - já está no topo!
    # Criação de Abas
    tab1, tab2 = st.tabs(["📝 Cadastro de Leads", "📅 Agenda & Lista"])

    with tab1:
        render_registro_lead()
        
    with tab2:
        render_agenda_leads()
