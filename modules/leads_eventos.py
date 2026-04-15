import streamlit as st
from datetime import datetime
from pymongo import MongoClient
import urllib.parse

# --- Funções de Conexão (Mantendo o padrão do seu arquivo original) ---
def get_db_client():
    """Retorna o cliente MongoDB configurado"""
    try:
        username = st.secrets["mongo"]["MONGO_USERNAME"]
        password = st.secrets["mongo"]["MONGO_PASSWORD"]
        cluster_url = st.secrets["mongo"]["MONGO_CLUSTER_URL"]
    except KeyError:
        username = st.secrets.get("MONGO_USERNAME", " ")
        password = st.secrets.get("MONGO_PASSWORD", " ")
        cluster_url = st.secrets.get("MONGO_CLUSTER_URL", " ")
    
    u = urllib.parse.quote_plus(username)
    p = urllib.parse.quote_plus(password)
    uri = f"mongodb+srv://{u}:{p}@{cluster_url}/?retryWrites=true&w=majority"
    return MongoClient(uri)

def get_leads_collection():
    """Retorna coleção de Leads/Eventos"""
    client = get_db_client()
    return client.crm_db.leads

def get_condominios_collection():
    """Retorna coleção de condomínios (Importado do seu módulo original)"""
    client = get_db_client()
    return client.crm_db.condominios

# --- Módulo de Registro de Leads ---
def render_registro_lead():
    """Renderiza formulário de captura de leads em eventos"""
    st.title("🤝 Captura de Leads & Eventos")
    st.markdown("Registro de contatos realizados em feiras, eventos e visitas.")
    
    # Lista de Produtos conforme solicitado
    PRODUTOS = [
        "Conecta e Protege (Câmeras + Internet + Bônus)",
        "Câmeras de Segurança",
        "Recarga de Carros Elétricos",
        "Conectividade (Internet)",
        "Automação Residencial",
        "Automação Predial"
    ]
    
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
            st.subheader("📍 Dados do Evento")
            nome_evento = st.text_input("Nome do Evento / Origem *", value="Feira de Condomínios", max_chars=100)
            data_evento = st.date_input("Data do Contato", value=datetime.now())
            nivel_interesse = st.selectbox("Nível de Interesse", ["🔥 Quente (Pronto para fechar)", "⚡ Morno (Interessado, vai analisar)", "❄️ Frio (Apenas coletou info)"])
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
                    "nivel_interesse": nivel_interesse,
                    "status": status_lead,
                    "produtos_interesse": produtos_interesse,
                    "observacoes": observacoes.strip(),
                    "data_cadastro": datetime.now(),
                    "ativo": True
                }
                
                try:
                    collection = get_leads_collection()
                    result = collection.insert_one(lead_data)
                    st.success(f"✅ Lead '{nome_contato}' registrado com sucesso! ID: {result.inserted_id}")
                    st.balloons()
                    # Limpar formulário via rerun ou mensagem
                except Exception as e:
                    st.error(f"❌ Erro ao salvar: {e}")

# --- Visualização Simples de Leads (Opcional, para conferência) ---
def render_lista_leads():
    """Exibe os últimos leads cadastrados"""
    st.subheader("📋 Últimos Leads Registrados")
    collection = get_leads_collection()
    leads = list(collection.find().sort("data_cadastro", -1).limit(10))
    
    if not leads:
        st.info("Nenhum lead registrado ainda.")
    else:
        for lead in leads:
            with st.expander(f"{lead['nome_contato']} - {lead['evento']} ({lead['nivel_interesse']})"):
                st.write(f"**Telefone:** {lead['telefone']}")
                st.write(f"**Produtos:** {', '.join(lead.get('produtos_interesse', []))}")
                st.write(f"**Obs:** {lead.get('observacoes', 'Sem observações')}")
                st.write(f"**Data:** {lead['data_evento'].strftime('%d/%m/%Y')}")

# --- Execução Principal (Para teste standalone) ---
if __name__ == "__main__":
    render_registro_lead()
    st.divider()
    render_lista_leads()
