import streamlit as st
from datetime import datetime, timedelta, timezone
import calendar
import re
from collections import defaultdict
import io
import pandas as pd
from pymongo import MongoClient
import urllib.parse
from bson.objectid import ObjectId

# ✅ CORREÇÃO: st.set_page_config() DEVE ser a primeira chamada Streamlit
st.set_page_config(page_title="CRM Eventos", layout="wide")

# --- Funções de Conexão (Padrão MongoDB) ---
def get_db_client():
    """Retorna o cliente MongoDB configurado"""
    try:
        username = st.secrets["mongo"]["MONGO_USERNAME"]
        password = st.secrets["mongo"]["MONGO_PASSWORD"]
        cluster_url = st.secrets["mongo"]["MONGO_CLUSTER_URL"]
    except KeyError:
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
    try:
        collection = get_leads_collection()
        result = collection.delete_one({"_id": ObjectId(lead_id)})
        return result.deleted_count > 0
    except Exception as e:
        st.error(f"Erro ao excluir: {e}")
        return False

def update_lead_observacoes(lead_id, novas_observacoes):
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
    try:
        collection = get_leads_collection()
        if nova_data is None:
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

# ============================================================================
# ✅ NOVA FUNÇÃO: Registrar Touch em um Lead
# ============================================================================
def registrar_touch_lead(lead_id, notas="Touch registrado via Painel de Ligações"):
    """Registra um novo touch em um lead e incrementa o contador"""
    try:
        collection = get_leads_collection()
        lead = collection.find_one({"_id": ObjectId(lead_id)})
        if not lead:
            return False
        
        touch_count = lead.get("touch_count", 0) + 1
        nome_usuario = st.session_state.get("nome_usuario", "Anônimo")
        timestamp = datetime.now(timezone.utc).isoformat()
        
        result = collection.update_one(
            {"_id": ObjectId(lead_id)},
            {
                "$set": {"touch_count": touch_count},
                "$push": {
                    "touch_history": {
                        "timestamp": timestamp,
                        "by": nome_usuario,
                        "notes": notas
                    }
                }
            }
        )
        return result.modified_count > 0
    except Exception as e:
        st.error(f"❌ Erro ao registrar touch: {e}")
        return False

# ============================================================================
# ✅ NOVA FUNÇÃO: Formatar último touch (humanizado)
# ============================================================================
def formatar_ultimo_touch(lead):
    """Retorna string formatada com data do último touch ou mensagem padrão"""
    touch_history = lead.get("touch_history", [])
    if not touch_history:
        return "🆕 Nunca contactado"
    
    try:
        ultimo_ts = max([t.get("timestamp", "") for t in touch_history])
        if not ultimo_ts:
            return "🆕 Nunca contactado"
        
        data_ultimo = datetime.fromisoformat(ultimo_ts.replace("Z", "+00:00"))
        agora = datetime.now(timezone.utc)
        
        diff = agora - data_ultimo
        dias = diff.days
        horas = diff.seconds // 3600
        minutos = (diff.seconds % 3600) // 60
        
        if dias == 0:
            if horas == 0:
                tempo_str = "agora mesmo" if minutos == 0 else f"há {minutos} min"
            else:
                tempo_str = f"há {horas}h"
        elif dias == 1:
            tempo_str = "ontem"
        elif dias < 7:
            tempo_str = f"há {dias} dias"
        elif dias < 30:
            semanas = dias // 7
            tempo_str = f"há {semanas} semana{'s' if semanas > 1 else ''}"
        else:
            tempo_str = data_ultimo.strftime("%d/%m/%Y")
        
        if dias == 0:
            icone = "🟢"
        elif dias <= 3:
            icone = "🟡"
        elif dias <= 7:
            icone = "🟠"
        else:
            icone = "🔴"
        
        return f"{icone} Último touch: {tempo_str}"
    except Exception:
        return "❓ Data inválida"

# ============================================================================
# ✅ NOVA FUNÇÃO: Badge visual do touch_count
# ============================================================================
def get_touch_badge(touch_count):
    """Retorna o badge emoji + cor para exibir ao lado do nome"""
    if touch_count == 0:
        return "🆕", "#d4edda"  # Novo
    elif touch_count <= 3:
        return f"🟢 {touch_count}", "#d4edda"
    elif touch_count <= 6:
        return f"🟡 {touch_count}", "#fff3cd"
    elif touch_count <= 10:
        return f"🟠 {touch_count}", "#ffeacc"
    else:
        return f"🔴 {touch_count}", "#f8d7da"

def get_eventos_existentes():
    try:
        collection = get_leads_collection()
        pipeline = [
            {"$group": {"_id": "$evento"}},
            {"$sort": {"_id": 1}},
            {"$limit": 100}
        ]
        resultados = list(collection.aggregate(pipeline))
        eventos = [r["_id"] for r in resultados if r["_id"]]
        return sorted(eventos)
    except Exception as e:
        st.warning(f"⚠️ Não foi possível carregar eventos anteriores: {e}")
        return []

# ============================================================================
# ✅ FUNÇÃO AUXILIAR: Retorna leads agrupados por data de próximo contato
# ============================================================================
def get_leads_para_calendario(collection, ano, mes, filtros=None):
    filtros = filtros or {}
    
    inicio_mes = datetime(ano, mes, 1)
    fim_mes = datetime(ano, mes, calendar.monthrange(ano, mes)[1], 23, 59, 59)
    
    query_base = {
        "$or": [
            {"data_proximo_contato": {"$gte": inicio_mes, "$lte": fim_mes}},
            {"data_evento": {"$gte": inicio_mes, "$lte": fim_mes}}
        ]
    }
    
    if filtros:
        query_base = {"$and": [query_base, filtros]}
    
    try:
        leads = list(collection.find(query_base))
    except Exception as e:
        st.error(f"❌ Erro ao buscar leads para calendário: {e}")
        return {}
    
    agenda = defaultdict(list)
    
    for lead in leads:
        data_ref = lead.get("data_proximo_contato") or lead.get("data_evento")
        
        if not data_ref:
            continue
        
        if isinstance(data_ref, datetime):
            data_key = data_ref.strftime("%Y-%m-%d")
        elif isinstance(data_ref, str) and len(data_ref) >= 10:
            data_key = data_ref[:10]
        else:
            continue
        
        agenda[data_key].append(lead)
    
    return agenda

# --- Módulo de Registro de Leads ---
def render_registro_lead():
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

    eventos_existentes = get_eventos_existentes()

    with st.form("form_lead_evento", clear_on_submit=True):
        col1, col2 = st.columns(2)
        
        with col1:
            st.subheader("📋 Dados do Contato")
            tipo_contato = st.selectbox("Tipo de Contato *", ["Síndico / Cliente", "Parceiro Comercial", "Outros"])
            nome_contato = st.text_input("Nome do Contato *", max_chars=100)
            
            nome_condominio = st.text_input("🏢 Nome do Condomínio (Se houver)", max_chars=100, 
                                          help="Preencha apenas se for um condomínio residencial")
            
            nome_empresa = st.text_input("🏭 Nome da Empresa (Se houver)", max_chars=100,
                                       help="Preencha apenas se for uma empresa parceira/comercial")
            
            telefone = st.text_input("Telefone / WhatsApp *", max_chars=20, placeholder="(00) 00000-0000")
            email = st.text_input("E-mail", max_chars=100)
            
        with col2:
            st.subheader("📅 Dados do Evento & Agenda")
            
            st.markdown("**Nome do Evento / Origem ***")
            st.caption("💡 Comece a digitar para ver sugestões de eventos já cadastrados")
            
            if eventos_existentes:
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
                nome_evento = st.text_input(
                    "Nome do Evento / Origem *",
                    value="Feira de Condomínios",
                    max_chars=100,
                    key="fallback_evento"
                )
            
            data_evento = st.date_input("Data do Contato", value=datetime.now())
            
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
                    index=3
                )
            
            with col_pot2:
                qtd_apartamentos = st.number_input(
                    "Qtd. média de apartamentos",
                    min_value=0,
                    max_value=10000,
                    value=0,
                    step=10
                )
            
            with col_pot3:
                potencial_servicos = st.selectbox(
                    "Potencial de Serviços",
                    ["Alto", "Médio", "Baixo", "Não avaliado"],
                    index=3
                )
            
            obs_potencial = st.text_input(
                "Observação sobre o potencial (opcional)",
                max_chars=200
            )
        
        st.subheader("🛒 Interesse em Produtos")
        produtos_interesse = st.multiselect(
            "Quais produtos despertaram interesse?", 
            PRODUTOS
        )
        
        st.subheader("📝 Observações da Conversa")
        observacoes = st.text_area(
            "Detalhes da evolução da conversa", 
            height=100
        )
        
        col_submit, col_novo = st.columns([1, 1])
        
        with col_submit:
            submitted = st.form_submit_button("💾 Salvar Lead", type="primary", use_container_width=True)
        
        with col_novo:
            novo_cadastro = st.form_submit_button("🔄 Novo Cadastro", use_container_width=True)
        
        if submitted:
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
                    "potencial_condominio": potencial_condominio if potencial_condominio != "Não avaliado" else None,
                    "qtd_apartamentos": qtd_apartamentos if qtd_apartamentos and qtd_apartamentos > 0 else None,
                    "potencial_servicos": potencial_servicos if potencial_servicos != "Não avaliado" else None,
                    "obs_potencial": obs_potencial.strip() if obs_potencial else None,
                    "produtos_interesse": produtos_interesse,
                    "observacoes": observacoes.strip(),
                    "data_cadastro": datetime.now(),
                    "ativo": True,
                    "convertido": False,
                    # ✅ NOVOS CAMPOS DE TOUCH
                    "touch_count": 0,
                    "touch_history": []
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
    st.title("📋 Agenda & Acompanhamento de Leads")
    st.markdown("Pesquise e gerencie seus contatos. Use os filtros abaixo para encontrar leads específicos.")

    try:
        collection = get_leads_collection()
    except Exception as e:
        st.error(f"❌ Erro ao conectar ao MongoDB: {e}")
        return

    with st.expander("🔍 Opções de Busca Avançada", expanded=True):
        col_search1, col_search2 = st.columns(2)
        
        with col_search1:
            search_nome = st.text_input("👤 Nome do Contato", placeholder="Digite parte do nome...")
            search_condo_emp = st.text_input("🏢 Condomínio ou Empresa", placeholder="Ex: Residencial Sol, Tech Solutions...")
        
        with col_search2:
            search_telefone = st.text_input("📞 Telefone", placeholder="Ex: 99999-0000")
            search_evento = st.text_input("📅 Evento/Origem", placeholder="Ex: Feira de Síndicos...")
        
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

    filtro_status = st.multiselect(
        "Filtrar por Status:", 
        options=["Novo", "Em Negociação", "Aguardando Retorno", "Parceria", "✅ Convertido"],
        default=["Novo", "Em Negociação", "Aguardando Retorno"]
    )

    query = {}
    
    if filtro_status:
        query["status"] = {"$in": filtro_status}

    if search_nome:
        query["nome_contato"] = {"$regex": search_nome, "$options": "i"}
    
    if search_telefone:
        query["telefone"] = {"$regex": search_telefone, "$options": "i"}
        
    if search_evento:
        query["evento"] = {"$regex": search_evento, "$options": "i"}
        
    if search_condo_emp:
        or_condition = [
            {"nome_condominio": {"$regex": search_condo_emp, "$options": "i"}},
            {"nome_empresa": {"$regex": search_condo_emp, "$options": "i"}}
        ]
        
        if query:
            query = {"$and": [query, {"$or": or_condition}]}
        else:
            query["$or"] = or_condition
    
    if filtro_potencial:
        if "$and" in query:
            query["$and"].append({"potencial_condominio": {"$in": filtro_potencial}})
        else:
            and_list = [query] if query else []
            and_list.append({"potencial_condominio": {"$in": filtro_potencial}})
            query = {"$and": and_list}
    
    if filtro_potencial_servicos:
        if "$and" in query:
            query["$and"].append({"potencial_servicos": {"$in": filtro_potencial_servicos}})
        else:
            and_list = [query] if query else []
            and_list.append({"potencial_servicos": {"$in": filtro_potencial_servicos}})
            query = {"$and": and_list}

    try:
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
        
        leads_com_data = []
        leads_sem_data = []
        
        for lead in leads:
            if lead.get("data_proximo_contato"):
                leads_com_data.append(lead)
            else:
                leads_sem_data.append(lead)
        
        if leads_com_data:
            st.subheader("📅 Agenda - Próximos Contatos")
            for lead in leads_com_data:
                display_lead_card(lead, collection)
        
        if leads_sem_data:
            st.subheader("🗄️ Pool - Leads Sem Data Agendada")
            st.caption("Contatos que não possuem follow-up agendado.")
            for lead in leads_sem_data:
                display_lead_card(lead, collection, is_pool=True)

def display_lead_card(lead, collection, is_pool=False):
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
    
    data_evento = lead.get("data_evento")
    if data_evento:
        data_evento_str = data_evento.strftime("%d/%m/%Y")
    else:
        data_evento_str = "N/A"

    # ✅ NOVO: Badge de touch_count
    touch_count = lead.get("touch_count", 0)
    badge_touch, _ = get_touch_badge(touch_count)
    info_ultimo_touch = formatar_ultimo_touch(lead)

    label_expander = f"{icono_data} {lead['nome_contato']} - {data_str} ({lead.get('nivel_interesse', '')}) {badge_touch} {urgency_badge}"

    with st.expander(label_expander):
        col_info, col_actions = st.columns([2, 1])
        
        with col_info:
            st.write(f"**📞 Telefone:** {lead.get('telefone')}")
            
            if lead.get('nome_condominio'):
                st.write(f"**🏢 Condomínio:** {lead.get('nome_condominio')}")
            if lead.get('nome_empresa'):
                st.write(f"**🏭 Empresa:** {lead.get('nome_empresa')}")
            if not lead.get('nome_condominio') and not lead.get('nome_empresa'):
                st.write(f"**🏢 Organização:** N/A")
            
            st.write(f"**🛒 Produtos:** {', '.join(lead.get('produtos_interesse', []))}")
            
            # ✅ NOVO: Exibir info de touches
            st.caption(f"🎯 Toques: **{touch_count}** | {info_ultimo_touch}")
            
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
            
            st.write(f"**📅 Evento:** {lead.get('evento')} em {data_evento_str}")
            st.write(f"**🔄 Status Atual:** {lead.get('status')}")
            if lead.get('convertido'):
                st.success("**🏆 CLIENTE CONVERTIDO**")

        with col_actions:
            st.markdown("### Ações")
            
            # ✅ NOVO: Botão de Touch
            if st.button("✋ Registrar Touch", key=f"touch_{lead['_id']}", use_container_width=True, type="primary"):
                if registrar_touch_lead(lead['_id'], "Touch registrado via card de lead"):
                    st.success(f"✔️ Touch #{touch_count + 1} registrado!")
                    st.rerun()
                else:
                    st.error("❌ Falha ao registrar touch.")
            
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
            
            if st.button("🏢 Editar Potencial", key=f"edit_pot_{lead['_id']}", use_container_width=True):
                if "editing_potencial_lead" not in st.session_state:
                    st.session_state.editing_potencial_lead = str(lead['_id'])
                st.rerun()
            
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

# ============================================================================
# ✅ NOVA FUNÇÃO: render_calendario_leads
# ============================================================================
def render_calendario_leads():
    """Exibe calendário mensal dos leads com info de touches"""
    st.title("📅 Calendário Mensal de Leads")
    st.markdown("Visualize seus leads distribuídos ao longo do mês. Clique em 👁️ para ver os detalhes de um dia.")
    
    try:
        collection = get_leads_collection()
    except Exception as e:
        st.error(f"❌ Erro ao conectar ao MongoDB: {e}")
        return
    
    if "mes_visualizado_leads" not in st.session_state:
        st.session_state.mes_visualizado_leads = datetime.now().replace(day=1).date()
    
    mes_atual = st.session_state.mes_visualizado_leads
    ano = mes_atual.year
    mes = mes_atual.month
    
    col_prev, col_title, col_next = st.columns([1, 3, 1])
    with col_prev:
        if st.button("<< Mês Anterior", key="prev_mes_leads"):
            novo_mes = mes_atual.replace(day=1) - timedelta(days=1)
            st.session_state.mes_visualizado_leads = novo_mes.replace(day=1)
            st.rerun()
    
    with col_title:
        st.markdown(f"### {calendar.month_name[mes].capitalize()} {ano}")
    
    with col_next:
        if st.button("Mês Próximo >>", key="prox_mes_leads"):
            proximo = mes_atual.replace(day=28) + timedelta(days=4)
            st.session_state.mes_visualizado_leads = proximo.replace(day=1)
            st.rerun()
    
    st.caption(
        "🎨 Legenda: "
        "⚪ Sem leads | "
        "🟢 ≤2 | "
        "🟡 3–5 | "
        "🟠 6–10 | "
        "🔴 ≥11 | "
        "❗ Dias vencidos com leads pendentes"
    )
    
    with st.expander("🔍 Filtros do Calendário", expanded=False):
        col_f1, col_f2, col_f3 = st.columns(3)
        
        with col_f1:
            filtro_status_cal = st.multiselect(
                "Filtrar por Status:",
                options=["Novo", "Em Negociação", "Aguardando Retorno", "Parceria", "✅ Convertido"],
                default=[],
                key="cal_leads_status"
            )
        
        with col_f2:
            filtro_interesse_cal = st.multiselect(
                "Filtrar por Nível de Interesse:",
                options=["🔥 Quente", "Morno", "❄️ Frio"],
                default=[],
                key="cal_leads_interesse"
            )
        
        with col_f3:
            filtro_potencial_cal = st.multiselect(
                "Filtrar por Potencial:",
                options=["Alto", "Médio", "Baixo"],
                default=[],
                key="cal_leads_potencial"
            )
        
        search_evento_cal = st.text_input(
            "📅 Filtrar por Evento/Origem (opcional):",
            placeholder="Ex: Feira de Síndicos...",
            key="cal_leads_evento"
        )
    
    filtros_query = {}
    
    if filtro_status_cal:
        filtros_query["status"] = {"$in": filtro_status_cal}
    
    if filtro_interesse_cal:
        filtros_query["nivel_interesse"] = {"$in": filtro_interesse_cal}
    
    if filtro_potencial_cal:
        filtros_query["potencial_condominio"] = {"$in": filtro_potencial_cal}
    
    if search_evento_cal:
        filtros_query["evento"] = {"$regex": search_evento_cal, "$options": "i"}
    
    with st.spinner("Carregando leads do mês..."):
        agenda_por_dia = get_leads_para_calendario(collection, ano, mes, filtros_query)
    
    total_leads_mes = sum(len(v) for v in agenda_por_dia.values())
    
    if total_leads_mes > 0:
        col_stat1, col_stat2, col_stat3, col_stat4 = st.columns(4)
        
        with col_stat1:
            st.metric("📊 Total de Leads", total_leads_mes)
        
        with col_stat2:
            quentes = sum(1 for leads in agenda_por_dia.values() for l in leads if l.get("nivel_interesse") == "🔥 Quente")
            st.metric("🔥 Quentes", quentes)
        
        with col_stat3:
            alto_pot = sum(1 for leads in agenda_por_dia.values() for l in leads if l.get("potencial_condominio") == "Alto")
            st.metric("🟢 Alto Potencial", alto_pot)
        
        with col_stat4:
            convertidos = sum(1 for leads in agenda_por_dia.values() for l in leads if l.get("convertido"))
            st.metric("🏆 Convertidos", convertidos)
    
    cal = calendar.monthcalendar(ano, mes)
    dias_da_semana = ["Seg", "Ter", "Qua", "Qui", "Sex", "Sáb", "Dom"]
    
    cols_header = st.columns(7)
    for i, dia in enumerate(dias_da_semana):
        cols_header[i].markdown(
            f"<div style='font-weight: bold; text-align: center; padding: 8px;'>{dia}</div>",
            unsafe_allow_html=True
        )
    
    hoje_date = datetime.now().date()
    
    for semana in cal:
        cols = st.columns(7)
        for i, dia_num in enumerate(semana):
            if dia_num == 0:
                cols[i].markdown("<div style='height: 70px;'></div>", unsafe_allow_html=True)
                continue
            
            data = datetime(ano, mes, dia_num).date()
            data_str = data.strftime("%Y-%m-%d")
            leads_do_dia = agenda_por_dia.get(data_str, [])
            qtd = len(leads_do_dia)
            
            if qtd == 0:
                cor = "#f8f9fa"
                texto = str(dia_num)
            elif qtd <= 2:
                cor = "#d4edda"
                texto = f"{dia_num}<br/>({qtd})"
            elif qtd <= 5:
                cor = "#fff3cd"
                texto = f"{dia_num}<br/>({qtd})"
            elif qtd <= 10:
                cor = "#ffeacc"
                texto = f"{dia_num}<br/>({qtd})"
            else:
                cor = "#f8d7da"
                texto = f"{dia_num}<br/>({qtd})"
            
            borda = ""
            icone = ""
            if data < hoje_date and qtd > 0:
                borda = "border: 2px solid #e74c3c;"
                icone = "❗ "
            
            estilo = (
                f"background-color: {cor};  "
                f"padding: 12px 6px;  "
                f"border-radius: 8px;  "
                f"text-align: center;  "
                f"font-weight: bold;  "
                f"font-size: 15px;  "
                f"box-shadow: 0 2px 4px rgba(0,0,0,0.06);  "
                f"{borda}"
            )
            html_celula = f"<div style='{estilo}'>{icone}{texto}</div>"
            cols[i].markdown(html_celula, unsafe_allow_html=True)
            
            if qtd > 0:
                if cols[i].button("👁️", key=f"olho_lead_{data_str}", use_container_width=True):
                    st.session_state["data_selecionada_lead"] = data
                    st.rerun()
    
    st.markdown("---")
    
    data_selecionada = st.date_input(
        "Selecione um dia para ver os leads:",
        value=st.session_state.get("data_selecionada_lead", datetime.now().date()),
        min_value=datetime(2020, 1, 1),
        key="data_selecionada_lead"
    )
    data_str = data_selecionada.strftime("%Y-%m-%d")
    leads_do_dia = agenda_por_dia.get(data_str, [])
    
    if leads_do_dia:
        st.markdown(f"### 👥 Leads em {data_selecionada.strftime('%d/%m/%Y')}")
        st.info(f"📊 {len(leads_do_dia)} lead(s) agendado(s) para este dia.")
        
        col_exp1, col_exp2 = st.columns(2)
        
        dados_excel = []
        texto_txt = ""
        
        for lead in leads_do_dia:
            touch_count = lead.get("touch_count", 0)
            
            dados_excel.append({
                "Nome": lead.get("nome_contato", ""),
                "Telefone": lead.get("telefone", ""),
                "Condomínio": lead.get("nome_condominio", "") or "",
                "Empresa": lead.get("nome_empresa", "") or "",
                "Evento": lead.get("evento", ""),
                "Nível Interesse": lead.get("nivel_interesse", ""),
                "Status": lead.get("status", ""),
                "Toques": touch_count,
                "Potencial": lead.get("potencial_condominio", "") or "",
                "Qtd. Aptos": lead.get("qtd_apartamentos", "") or "",
                "Produtos": ", ".join(lead.get("produtos_interesse", [])),
                "Observações": lead.get("observacoes", "")
            })
            
            texto_txt += f"📞 {lead.get('nome_contato', 'N/A')} | {lead.get('nivel_interesse', '')} | Toques: {touch_count}\n"
            texto_txt += f"📱 {lead.get('telefone', 'N/A')}\n"
            if lead.get('nome_condominio'):
                texto_txt += f"🏢 Condomínio: {lead.get('nome_condominio')}\n"
            if lead.get('nome_empresa'):
                texto_txt += f"🏭 Empresa: {lead.get('nome_empresa')}\n"
            texto_txt += f"📅 Evento: {lead.get('evento', 'N/A')}\n"
            texto_txt += f"🔄 Status: {lead.get('status', 'N/A')}\n"
            if lead.get('observacoes'):
                texto_txt += f"📝 Obs: {lead.get('observacoes')}\n"
            texto_txt += "---\n"
        
        df = pd.DataFrame(dados_excel)
        output = io.BytesIO()
        with pd.ExcelWriter(output, engine='openpyxl') as writer:
            df.to_excel(writer, index=False, sheet_name='Leads do Dia')
            worksheet = writer.sheets['Leads do Dia']
            column_widths = [25, 15, 25, 20, 20, 15, 15, 10, 12, 10, 30, 40]
            for i, width in enumerate(column_widths):
                if i < 26:
                    col_letter = chr(65 + i)
                    worksheet.column_dimensions[col_letter].width = width
        output.seek(0)
        
        with col_exp1:
            st.download_button(
                label="📋 Exportar TXT",
                data=texto_txt,
                file_name=f"leads_{data_selecionada.strftime('%Y-%m-%d')}.txt",
                mime="text/plain",
                key=f"copiar_leads_{data_str}",
                use_container_width=True
            )
        
        with col_exp2:
            st.download_button(
                label="📊 Exportar Excel (.xlsx)",
                data=output.getvalue(),
                file_name=f"leads_{data_selecionada.strftime('%Y-%m-%d')}.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                key=f"excel_leads_{data_str}",
                use_container_width=True
            )
        
        st.markdown("---")
        
        for lead in leads_do_dia:
            nivel = lead.get("nivel_interesse", "")
            emoji_nivel = {"🔥 Quente": "🔥", "Morno": "⚪", "❄️ Frio": "❄️"}.get(nivel, "⚪")
            
            pot = lead.get("potencial_condominio", "")
            emoji_pot = {"Alto": "🟢", "Médio": "🟡", "Baixo": "🔴"}.get(pot, "")
            
            touch_count = lead.get("touch_count", 0)
            badge_touch, _ = get_touch_badge(touch_count)
            info_ultimo_touch = formatar_ultimo_touch(lead)
            
            titulo = f"{emoji_nivel} {lead.get('nome_contato', 'N/A')} - {lead.get('telefone', '')} {badge_touch}"
            if emoji_pot:
                titulo += f" {emoji_pot} {pot}"
            
            with st.expander(titulo, expanded=False):
                col_info, col_actions = st.columns([2, 1])
                
                with col_info:
                    st.write(f"**📞 Telefone:** {lead.get('telefone', 'N/A')}")
                    
                    if lead.get('nome_condominio'):
                        st.info(f"🏢 **Condomínio:** {lead.get('nome_condominio')}")
                    if lead.get('nome_empresa'):
                        st.info(f"🏭 **Empresa:** {lead.get('nome_empresa')}")
                    
                    st.write(f"**📅 Evento:** {lead.get('evento', 'N/A')}")
                    st.write(f"**🔄 Status:** {lead.get('status', 'N/A')}")
                    st.write(f"**🌡️ Nível de Interesse:** {lead.get('nivel_interesse', 'N/A')}")
                    st.caption(f"🎯 Toques: **{touch_count}** | {info_ultimo_touch}")
                    
                    if lead.get('potencial_condominio'):
                        st.write(f"**🏢 Potencial:** {emoji_pot} {lead.get('potencial_condominio')}")
                    if lead.get('qtd_apartamentos'):
                        st.write(f"**🏠 Qtd. Apartamentos:** {lead.get('qtd_apartamentos')}")
                    
                    if lead.get('observacoes'):
                        st.write(f"**📝 Observações:** {lead.get('observacoes')}")
                    
                    if lead.get('convertido'):
                        st.success("**🏆 CLIENTE CONVERTIDO**")
                
                with col_actions:
                    st.markdown("### Ações Rápidas")
                    
                    # ✅ Botão de Touch
                    if st.button("✋ Touch", key=f"cal_touch_{lead['_id']}", use_container_width=True, type="primary"):
                        if registrar_touch_lead(lead['_id'], "Touch registrado via calendário"):
                            st.success(f"✔️ Touch #{touch_count + 1} registrado!")
                            st.rerun()
                        else:
                            st.error("❌ Falha ao registrar touch.")
                    
                    if st.button("📅 Alterar Data", key=f"cal_edit_date_{lead['_id']}", use_container_width=True):
                        st.session_state[f"cal_editing_date_{lead['_id']}"] = True
                        st.rerun()
                    
                    if st.session_state.get(f"cal_editing_date_{lead['_id']}", False):
                        with st.form(key=f"cal_form_date_{lead['_id']}"):
                            nova_data_cal = st.date_input(
                                "Nova data:",
                                value=lead.get('data_proximo_contato', datetime.now()).date() if lead.get('data_proximo_contato') else datetime.now(),
                                key=f"cal_date_input_{lead['_id']}"
                            )
                            col_s, col_c = st.columns([1, 1])
                            with col_s:
                                if st.form_submit_button("💾 Salvar", use_container_width=True):
                                    if update_lead_data_proximo_contato(lead['_id'], nova_data_cal):
                                        st.success("✅ Data atualizada!")
                                        del st.session_state[f"cal_editing_date_{lead['_id']}"]
                                        st.rerun()
                            with col_c:
                                if st.form_submit_button("❌ Cancelar", use_container_width=True):
                                    del st.session_state[f"cal_editing_date_{lead['_id']}"]
                                    st.rerun()
    
    else:
        st.info(f"📭 Nenhum lead para {data_selecionada.strftime('%d/%m/%Y')}.")

# ============================================================================
# ✅ NOVA FUNÇÃO: render_painel_ligacoes_leads
# Painel de ligações estilo call center para leads de eventos
# ============================================================================
def render_painel_ligacoes_leads():
    """Renderiza o painel de ligações para leads de eventos"""
    st.title("📞 Painel de Ligações - Leads de Eventos")
    st.markdown("Visualize, filtre e registre touches em seus leads de forma rápida e eficiente.")
    
    try:
        collection = get_leads_collection()
    except Exception as e:
        st.error(f"❌ Erro ao conectar ao MongoDB: {e}")
        return
    
    # === FILTROS ===
    st.markdown("### 🔍 Filtros Avançados")
    
    col_f1, col_f2, col_f3, col_f4 = st.columns(4)
    
    with col_f1:
        filtro_touch_tipo = st.selectbox(
            "Quantidade de toques:",
            options=[
                "Todos",
                "Nunca contatado (0)",
                "1-3 toques",
                "4-6 toques",
                "7-10 toques",
                "Mais de 10",
                "Personalizado"
            ],
            index=0,
            key="painel_leads_touch_tipo"
        )
    
    with col_f2:
        if filtro_touch_tipo == "Personalizado":
            touch_min = st.number_input("Mínimo:", min_value=0, value=0, key="painel_leads_touch_min")
            touch_max = st.number_input("Máximo:", min_value=0, value=999, key="painel_leads_touch_max")
        else:
            touch_min, touch_max = 0, 999
            st.caption("Use 'Personalizado' para range")
    
    with col_f3:
        filtro_periodo = st.selectbox(
            "Último contato:",
            options=[
                "Qualquer período",
                "Hoje",
                "Ontem",
                "Últimos 3 dias",
                "Última semana",
                "Últimos 15 dias",
                "Último mês",
                "Mais de 1 mês",
                "Nunca contactado"
            ],
            index=0,
            key="painel_leads_periodo"
        )
    
    with col_f4:
        filtro_status_painel = st.multiselect(
            "Status:",
            options=["Novo", "Em Negociação", "Aguardando Retorno", "Parceria", "✅ Convertido"],
            default=["Novo", "Em Negociação", "Aguardando Retorno", "Parceria"],
            key="painel_leads_status"
        )
    
    # Linha 2 de filtros
    col_f5, col_f6, col_f7, col_f8 = st.columns(4)
    
    with col_f5:
        filtro_interesse = st.multiselect(
            "Nível de Interesse:",
            options=["🔥 Quente", "Morno", "❄️ Frio"],
            default=[],
            key="painel_leads_interesse"
        )
    
    with col_f6:
        filtro_potencial_painel = st.multiselect(
            "Potencial:",
            options=["Alto", "Médio", "Baixo"],
            default=[],
            key="painel_leads_potencial"
        )
    
    with col_f7:
        search_evento_painel = st.text_input(
            "Evento (busca):",
            placeholder="Ex: Feira...",
            key="painel_leads_evento"
        )
    
    with col_f8:
        search_nome_painel = st.text_input(
            "Nome (busca):",
            placeholder="Ex: João...",
            key="painel_leads_nome"
        )
    
    col_ord, col_lim = st.columns([3, 1])
    
    with col_ord:
        ordenacao_painel = st.selectbox(
            "Ordenar por:",
            options=[
                "Data próximo contato (mais próxima)",
                "Data próximo contato (mais distante)",
                "Touch count (mais touches primeiro)",
                "Touch count (menos touches primeiro)",
                "Último touch (mais recente)",
                "Último touch (mais antigo)",
                "Nome (A-Z)",
                "Data cadastro (mais recente)"
            ],
            index=0,
            key="painel_leads_ordenacao"
        )
    
    with col_lim:
        limite = st.number_input(
            "Limite:",
            min_value=10,
            max_value=500,
            value=50,
            step=10,
            key="painel_leads_limite"
        )
    
    st.divider()
    
    # === MONTAGEM DA QUERY ===
    query = {}
    
    if filtro_status_painel:
        query["status"] = {"$in": filtro_status_painel}
    
    if filtro_interesse:
        query["nivel_interesse"] = {"$in": filtro_interesse}
    
    if filtro_potencial_painel:
        query["potencial_condominio"] = {"$in": filtro_potencial_painel}
    
    if search_evento_painel:
        query["evento"] = {"$regex": search_evento_painel, "$options": "i"}
    
    if search_nome_painel:
        query["nome_contato"] = {"$regex": search_nome_painel, "$options": "i"}
    
    # Filtros de touch
    if filtro_touch_tipo == "Nunca contatado (0)":
        query["$or"] = [
            {"touch_count": {"$exists": False}},
            {"touch_count": 0}
        ]
    elif filtro_touch_tipo == "1-3 toques":
        query["touch_count"] = {"$gte": 1, "$lte": 3}
    elif filtro_touch_tipo == "4-6 toques":
        query["touch_count"] = {"$gte": 4, "$lte": 6}
    elif filtro_touch_tipo == "7-10 toques":
        query["touch_count"] = {"$gte": 7, "$lte": 10}
    elif filtro_touch_tipo == "Mais de 10":
        query["touch_count"] = {"$gt": 10}
    elif filtro_touch_tipo == "Personalizado":
        query["touch_count"] = {"$gte": touch_min, "$lte": touch_max}
    
    # Filtro de período
    hoje = datetime.now(timezone.utc)
    
    if filtro_periodo != "Qualquer período" and filtro_periodo != "Nunca contactado":
        if filtro_periodo == "Hoje":
            data_limite = hoje.replace(hour=0, minute=0, second=0)
        elif filtro_periodo == "Ontem":
            data_limite = (hoje - timedelta(days=1)).replace(hour=0, minute=0, second=0)
        elif filtro_periodo == "Últimos 3 dias":
            data_limite = hoje - timedelta(days=3)
        elif filtro_periodo == "Última semana":
            data_limite = hoje - timedelta(days=7)
        elif filtro_periodo == "Últimos 15 dias":
            data_limite = hoje - timedelta(days=15)
        elif filtro_periodo == "Último mês":
            data_limite = hoje - timedelta(days=30)
        elif filtro_periodo == "Mais de 1 mês":
            data_limite = hoje - timedelta(days=30)
        
        if filtro_periodo != "Mais de 1 mês":
            if "$or" in query:
                # Combina com o $or existente
                query["$and"] = [{"$or": query.pop("$or")}, {"touch_history.timestamp": {"$gte": data_limite.isoformat()}}]
            else:
                query["touch_history.timestamp"] = {"$gte": data_limite.isoformat()}
    
    elif filtro_periodo == "Nunca contactado":
        cond_nunca = {
            "$or": [
                {"touch_history": {"$exists": False}},
                {"touch_history": {"$size": 0}}
            ]
        }
        if query:
            query = {"$and": [query, cond_nunca]}
        else:
            query = cond_nunca
    
    # === ORDENAÇÃO ===
    sort_field = "data_proximo_contato"
    sort_direction = 1
    
    if ordenacao_painel == "Data próximo contato (mais distante)":
        sort_direction = -1
    elif ordenacao_painel == "Touch count (mais touches primeiro)":
        sort_field = "touch_count"
        sort_direction = -1
    elif ordenacao_painel == "Touch count (menos touches primeiro)":
        sort_field = "touch_count"
        sort_direction = 1
    elif ordenacao_painel == "Último touch (mais recente)":
        sort_field = "touch_history.timestamp"
        sort_direction = -1
    elif ordenacao_painel == "Último touch (mais antigo)":
        sort_field = "touch_history.timestamp"
        sort_direction = 1
    elif ordenacao_painel == "Nome (A-Z)":
        sort_field = "nome_contato"
        sort_direction = 1
    elif ordenacao_painel == "Data cadastro (mais recente)":
        sort_field = "data_cadastro"
        sort_direction = -1
    
    # === BUSCA ===
    try:
        leads = list(collection.find(query).sort(sort_field, sort_direction).limit(limite))
    except Exception as e:
        st.error(f"❌ Erro ao buscar leads: {e}")
        return
    
    # Pós-processamento para "Mais de 1 mês"
    if filtro_periodo == "Mais de 1 mês":
        data_limite = hoje - timedelta(days=30)
        leads_filtrados = []
        for l in leads:
            touch_history = l.get("touch_history", [])
            if touch_history:
                ultimo_ts = max([t.get("timestamp", "") for t in touch_history])
                if ultimo_ts:
                    try:
                        data_ultimo = datetime.fromisoformat(ultimo_ts.replace("Z", "+00:00"))
                        if data_ultimo < data_limite:
                            leads_filtrados.append(l)
                    except:
                        pass
            else:
                leads_filtrados.append(l)
        leads = leads_filtrados[:limite]
    
    if not leads:
        st.warning("📭 Nenhum lead encontrado com os filtros selecionados.")
        return
    
    st.success(f"✅ {len(leads)} lead(s) encontrado(s) para ligação!")
    
    # === ESTATÍSTICAS RÁPIDAS ===
    total_touches = sum(l.get("touch_count", 0) for l in leads)
    media_touches = total_touches / len(leads) if leads else 0
    nunca_contatados = sum(1 for l in leads if l.get("touch_count", 0) == 0)
    alto_potencial = sum(1 for l in leads if l.get("potencial_condominio") == "Alto")
    
    col_s1, col_s2, col_s3, col_s4 = st.columns(4)
    with col_s1:
        st.metric("📊 Total", len(leads))
    with col_s2:
        st.metric("✋ Média de Toques", f"{media_touches:.1f}")
    with col_s3:
        st.metric("🆕 Nunca contatados", nunca_contatados)
    with col_s4:
        st.metric("🟢 Alto Potencial", alto_potencial)
    
    st.markdown("---")
    
    # === PAINEL DE CARDS ===
    st.markdown("### 🎯 Lista de Ligações")
    st.caption("Clique em 'Touch' para registrar uma ligação. Use 'Ações' para agendar retorno ou editar observações.")
    
    # CSS customizado
    st.markdown("""
        <style>
        .lead-card-painel {
            background-color: #f8f9fa;
            border-radius: 10px;
            padding: 12px;
            margin-bottom: 8px;
            border-left: 5px solid #007bff;
        }
        .lead-card-painel:hover {
            background-color: #e9ecef;
        }
        .telefone-destaque-lead {
            font-size: 1.2em;
            font-weight: bold;
            color: #28a745;
        }
        .quente-badge {
            color: #dc3545;
            font-weight: bold;
        }
        .touch-badge-painel {
            font-size: 0.9em;
            font-weight: bold;
        }
        </style>
    """, unsafe_allow_html=True)
    
    selecionados = []
    
    for idx, lead in enumerate(leads, 1):
        _id = str(lead["_id"])
        nome = lead.get("nome_contato", "N/A")
        telefone = lead.get("telefone", "N/A")
        evento = lead.get("evento", "N/A")
        status = lead.get("status", "N/A")
        nivel = lead.get("nivel_interesse", "")
        potencial = lead.get("potencial_condominio", "")
        touch_count = lead.get("touch_count", 0)
        info_ultimo_touch = formatar_ultimo_touch(lead)
        obs = lead.get("observacoes", "")
        
        # Badge de touch
        badge_touch, cor_touch = get_touch_badge(touch_count)
        
        # Emoji de nível de interesse
        emoji_nivel = {"🔥 Quente": "🔥", "Morno": "⚪", "❄️ Frio": "❄️"}.get(nivel, "⚪")
        
        # Emoji de potencial
        emoji_pot = {"Alto": "🟢", "Médio": "🟡", "Baixo": "🔴"}.get(potencial, "")
        
        # Condomínio/Empresa
        org = ""
        if lead.get("nome_condominio"):
            org = f"🏢 {lead.get('nome_condominio')}"
        elif lead.get("nome_empresa"):
            org = f"🏭 {lead.get('nome_empresa')}"
        
        with st.container():
            col_check, cols_dados = st.columns([0.3, 9.7])
            
            with col_check:
                selecionado = st.checkbox(" ", key=f"painel_lead_sel_{_id}", label_visibility="collapsed")
                if selecionado:
                    selecionados.append(_id)
            
            with cols_dados:
                cols = st.columns([0.4, 2.5, 1.5, 1.8, 1.8, 1])
                
                with cols[0]:
                    st.markdown(f"**#{idx}**")
                
                with cols[1]:
                    st.markdown(f"**{emoji_nivel} {nome}** {badge_touch}")
                    st.caption(f"📅 {evento}")
                    if org:
                        st.caption(org)
                
                with cols[2]:
                    st.markdown(f"<span class='telefone-destaque-lead'>{telefone}</span>", unsafe_allow_html=True)
                    if emoji_pot:
                        st.caption(f"{emoji_pot} Potencial: {potencial}")
                
                with cols[3]:
                    st.caption(f"🔄 Status: {status}")
                    st.caption(f"🎯 Toques: **{touch_count}**")
                
                with cols[4]:
                    st.caption(info_ultimo_touch)
                    if obs:
                        st.caption(f"📝 {obs[:40]}{'...' if len(obs) > 40 else ''}")
                
                with cols[5]:
                    if st.button("✋ Touch", key=f"painel_lead_touch_{_id}", use_container_width=True, type="primary"):
                        if registrar_touch_lead(_id, "Touch registrado via Painel de Ligações"):
                            st.success("✔️ Touch registrado!")
                            st.rerun()
                        else:
                            st.error("❌ Erro ao registrar.")
                    
                    if st.button("⚙️", key=f"painel_lead_acoes_{_id}", use_container_width=True, type="secondary"):
                        st.session_state[f"painel_lead_mostrar_acoes_{_id}"] = True
        
        # Ações expandidas
        if st.session_state.get(f"painel_lead_mostrar_acoes_{_id}", False):
            with st.form(key=f"painel_lead_form_acoes_{_id}"):
                st.markdown("**Ações Rápidas:**")
                
                col_a1, col_a2, col_a3, col_a4 = st.columns(4)
                
                with col_a1:
                    nova_obs = st.text_area(
                        "Observação:",
                        value=obs,
                        height=80,
                        key=f"painel_lead_obs_{_id}"
                    )
                
                with col_a2:
                    st.markdown("&nbsp;")
                    if st.form_submit_button("💾 Salvar Obs", use_container_width=True):
                        if update_lead_observacoes(_id, nova_obs):
                            st.success("✅ Observação salva!")
                            st.session_state[f"painel_lead_mostrar_acoes_{_id}"] = False
                            st.rerun()
                
                with col_a3:
                    st.markdown("**Agendar Retorno:**")
                    dias_retorno = st.selectbox(
                        "Daqui a:",
                        options=[3, 7, 15, 30, 180],
                        format_func=lambda x: f"{x} dias" if x < 180 else "6 meses",
                        key=f"painel_lead_dias_{_id}"
                    )
                    if st.form_submit_button("📅 Agendar", use_container_width=True, type="primary"):
                        nova_data_retorno = (datetime.now() + timedelta(days=dias_retorno)).date()
                        if update_lead_data_proximo_contato(_id, nova_data_retorno):
                            st.success(f"✅ Retorno agendado para {nova_data_retorno.strftime('%d/%m/%Y')}!")
                            st.session_state[f"painel_lead_mostrar_acoes_{_id}"] = False
                            st.rerun()
                
                with col_a4:
                    st.markdown("**Outras Ações:**")
                    if st.form_submit_button("🚫 Não Perturbar 6m", use_container_width=True, type="secondary"):
                        nova_data_retorno = (datetime.now() + timedelta(days=180)).date()
                        if update_lead_data_proximo_contato(_id, nova_data_retorno):
                            st.success("✅ Marcado para não perturbar por 6 meses!")
                            st.session_state[f"painel_lead_mostrar_acoes_{_id}"] = False
                            st.rerun()
                    
                    if st.form_submit_button("❌ Remover", use_container_width=True, type="secondary"):
                        if delete_lead(_id):
                            st.success("✅ Lead removido!")
                            st.session_state[f"painel_lead_mostrar_acoes_{_id}"] = False
                            st.rerun()
    
    # === AÇÕES EM LOTE ===
    if selecionados:
        st.markdown("---")
        st.warning(f"🎯 **{len(selecionados)} lead(s) selecionado(s)**")
        
        col_lote1, col_lote2, col_lote3, col_lote4 = st.columns(4)
        
        with col_lote1:
            if st.button("✋ Touch em Todos", use_container_width=True, type="primary"):
                for lid in selecionados:
                    registrar_touch_lead(lid, "Touch em lote via Painel de Ligações")
                st.success(f"✅ {len(selecionados)} touches registrados!")
                st.rerun()
        
        with col_lote2:
            if st.button("📅 Agendar 3 dias (Lote)", use_container_width=True):
                nova_data_retorno = (datetime.now() + timedelta(days=3)).date()
                for lid in selecionados:
                    update_lead_data_proximo_contato(lid, nova_data_retorno)
                st.success(f"✅ {len(selecionados)} leads agendados para daqui 3 dias!")
                st.rerun()
        
        with col_lote3:
            if st.button("🚫 Não Perturbar 6m (Lote)", use_container_width=True, type="secondary"):
                nova_data_retorno = (datetime.now() + timedelta(days=180)).date()
                for lid in selecionados:
                    update_lead_data_proximo_contato(lid, nova_data_retorno)
                st.success(f"✅ {len(selecionados)} leads marcados como não perturbar!")
                st.rerun()
        
        with col_lote4:
            if st.button("🗑️ Excluir (Lote)", use_container_width=True, type="secondary"):
                for lid in selecionados:
                    delete_lead(lid)
                st.success(f"✅ {len(selecionados)} leads excluídos!")
                st.rerun()

# --- Execução Principal ---
if __name__ == "__main__":
    # Criação de Abas
    tab1, tab2, tab3, tab4 = st.tabs([
        "📝 Cadastro de Leads",
        "📋 Agenda & Lista",
        "📅 Calendário Mensal",
        "📞 Painel de Ligações"
    ])
    
    with tab1:
        render_registro_lead()
        
    with tab2:
        render_agenda_leads()
    
    with tab3:
        render_calendario_leads()
    
    with tab4:
        render_painel_ligacoes_leads()
