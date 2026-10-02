import streamlit as st
from datetime import datetime, timedelta
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
# ✅ NOVO: FUNÇÃO AUXILIAR - Retorna leads agrupados por data de próximo contato
# ============================================================================
def get_leads_para_calendario(collection, ano, mes, filtros=None):
    """
    Retorna dict { 'YYYY-MM-DD': [leads] } para o mês/ano especificado.
    Considera 'data_proximo_contato' (datetime) OU 'data_evento' como fallback.
    """
    filtros = filtros or {}
    
    # Intervalo do mês
    inicio_mes = datetime(ano, mes, 1)
    fim_mes = datetime(ano, mes, calendar.monthrange(ano, mes)[1], 23, 59, 59)
    
    # Query base: pega leads com data_proximo_contato OU data_evento no mês
    query_base = {
        "$or": [
            {"data_proximo_contato": {"$gte": inicio_mes, "$lte": fim_mes}},
            {"data_evento": {"$gte": inicio_mes, "$lte": fim_mes}}
        ]
    }
    
    # Aplicar filtros extras (status, potencial, evento)
    if filtros:
        query_base = {"$and": [query_base, filtros]}
    
    try:
        leads = list(collection.find(query_base))
    except Exception as e:
        st.error(f"❌ Erro ao buscar leads para calendário: {e}")
        return {}
    
    agenda = defaultdict(list)
    
    for lead in leads:
        # Priorizar data_proximo_contato; se não tiver, usa data_evento
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
        
        # ✅ Bloco de Potencial do Condomínio (só aparece para Síndico/Cliente)
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

    label_expander = f"{icono_data} {lead['nome_contato']} - {data_str} ({lead.get('nivel_interesse', '')}) {urgency_badge}"

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
                
                with col_del:
                    pass
            
            st.write(f"**📅 Evento:** {lead.get('evento')} em {data_evento_str}")
            st.write(f"**🔄 Status Atual:** {lead.get('status')}")
            if lead.get('convertido'):
                st.success("**🏆 CLIENTE CONVERTIDO**")

        with col_actions:
            st.markdown("### Ações")
            
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
# ✅ NOVA FUNÇÃO: render_calendario_leads - Calendário Mensal de Leads
# ============================================================================
def render_calendario_leads():
    """Exibe calendário mensal dos leads baseado em data_proximo_contato / data_evento"""
    st.title("📅 Calendário Mensal de Leads")
    st.markdown("Visualize seus leads distribuídos ao longo do mês. Clique em 👁️ para ver os detalhes de um dia.")
    
    try:
        collection = get_leads_collection()
    except Exception as e:
        st.error(f"❌ Erro ao conectar ao MongoDB: {e}")
        return
    
    # --- Estado do mês visualizado ---
    if "mes_visualizado_leads" not in st.session_state:
        st.session_state.mes_visualizado_leads = datetime.now().replace(day=1).date()
    
    mes_atual = st.session_state.mes_visualizado_leads
    ano = mes_atual.year
    mes = mes_atual.month
    
    # --- Navegação entre meses ---
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
        "🟢 1–2 | "
        "🟡 3–5 | "
        "🟠 6–10 | "
        "🔴 ≥11 | "
        "❗ Dias vencidos com leads pendentes | "
        "🔥 Quente | ⚪ Morno | ❄️ Frio"
    )
    
    # --- Filtros ---
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
    
    # --- Montar filtros para a query ---
    filtros_query = {}
    
    if filtro_status_cal:
        filtros_query["status"] = {"$in": filtro_status_cal}
    
    if filtro_interesse_cal:
        filtros_query["nivel_interesse"] = {"$in": filtro_interesse_cal}
    
    if filtro_potencial_cal:
        filtros_query["potencial_condominio"] = {"$in": filtro_potencial_cal}
    
    if search_evento_cal:
        filtros_query["evento"] = {"$regex": search_evento_cal, "$options": "i"}
    
    # --- Buscar leads do mês ---
    with st.spinner("Carregando leads do mês..."):
        agenda_por_dia = get_leads_para_calendario(collection, ano, mes, filtros_query)
    
    # --- Estatísticas do mês ---
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
    
    # --- Renderizar calendário ---
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
            
            # Definir cor pela quantidade
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
    
    # --- Seleção de data + detalhes ---
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
        
        # --- Exportação ---
        col_exp1, col_exp2 = st.columns(2)
        
        # Preparar dados para exportação
        dados_excel = []
        texto_txt = ""
        
        for lead in leads_do_dia:
            # Dados para Excel
            dados_excel.append({
                "Nome": lead.get("nome_contato", ""),
                "Telefone": lead.get("telefone", ""),
                "Condomínio": lead.get("nome_condominio", "") or "",
                "Empresa": lead.get("nome_empresa", "") or "",
                "Evento": lead.get("evento", ""),
                "Nível Interesse": lead.get("nivel_interesse", ""),
                "Status": lead.get("status", ""),
                "Potencial": lead.get("potencial_condominio", "") or "",
                "Qtd. Aptos": lead.get("qtd_apartamentos", "") or "",
                "Potencial Serviços": lead.get("potencial_servicos", "") or "",
                "Produtos": ", ".join(lead.get("produtos_interesse", [])),
                "Observações": lead.get("observacoes", "")
            })
            
            # Dados para TXT
            texto_txt += f"📞 {lead.get('nome_contato', 'N/A')} | {lead.get('nivel_interesse', '')}\n"
            texto_txt += f"📱 {lead.get('telefone', 'N/A')}\n"
            if lead.get('nome_condominio'):
                texto_txt += f"🏢 Condomínio: {lead.get('nome_condominio')}\n"
            if lead.get('nome_empresa'):
                texto_txt += f"🏭 Empresa: {lead.get('nome_empresa')}\n"
            texto_txt += f"📅 Evento: {lead.get('evento', 'N/A')}\n"
            texto_txt += f"🔄 Status: {lead.get('status', 'N/A')}\n"
            if lead.get('potencial_condominio'):
                texto_txt += f"🟢 Potencial: {lead.get('potencial_condominio')}\n"
            if lead.get('qtd_apartamentos'):
                texto_txt += f"🏠 Qtd. Apartamentos: {lead.get('qtd_apartamentos')}\n"
            if lead.get('produtos_interesse'):
                texto_txt += f"🛒 Produtos: {', '.join(lead.get('produtos_interesse', []))}\n"
            if lead.get('observacoes'):
                texto_txt += f"📝 Obs: {lead.get('observacoes')}\n"
            texto_txt += "---\n"
        
        df = pd.DataFrame(dados_excel)
        output = io.BytesIO()
        with pd.ExcelWriter(output, engine='openpyxl') as writer:
            df.to_excel(writer, index=False, sheet_name='Leads do Dia')
            worksheet = writer.sheets['Leads do Dia']
            column_widths = [25, 15, 25, 20, 20, 15, 15, 12, 10, 15, 30, 40]
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
        
        # --- Exibir leads do dia ---
        for lead in leads_do_dia:
            nivel = lead.get("nivel_interesse", "")
            emoji_nivel = {"🔥 Quente": "🔥", "Morno": "⚪", "❄️ Frio": "❄️"}.get(nivel, "⚪")
            
            pot = lead.get("potencial_condominio", "")
            emoji_pot = {"Alto": "🟢", "Médio": "🟡", "Baixo": "🔴"}.get(pot, "")
            
            titulo = f"{emoji_nivel} {lead.get('nome_contato', 'N/A')} - {lead.get('telefone', '')}"
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
                    
                    if lead.get('potencial_condominio'):
                        st.write(f"**🏢 Potencial:** {emoji_pot} {lead.get('potencial_condominio')}")
                    if lead.get('qtd_apartamentos'):
                        st.write(f"**🏠 Qtd. Apartamentos:** {lead.get('qtd_apartamentos')}")
                    if lead.get('potencial_servicos'):
                        pot_serv = lead.get('potencial_servicos')
                        emoji_serv = {"Alto": "🟢", "Médio": "🟡", "Baixo": "🔴"}.get(pot_serv, "")
                        st.write(f"**🛠️ Potencial Serviços:** {emoji_serv} {pot_serv}")
                    
                    if lead.get('produtos_interesse'):
                        st.write(f"**🛒 Produtos:** {', '.join(lead.get('produtos_interesse', []))}")
                    
                    if lead.get('observacoes'):
                        st.write(f"**📝 Observações:** {lead.get('observacoes')}")
                    
                    if lead.get('convertido'):
                        st.success("**🏆 CLIENTE CONVERTIDO**")
                
                with col_actions:
                    st.markdown("### Ações Rápidas")
                    
                    # Botão de atualizar data de próximo contato
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

# --- Execução Principal ---
if __name__ == "__main__":
    # Criação de Abas
    tab1, tab2, tab3 = st.tabs([
        "📝 Cadastro de Leads",
        "📋 Agenda & Lista",
        "📅 Calendário Mensal"
    ])
    
    with tab1:
        render_registro_lead()
        
    with tab2:
        render_agenda_leads()
    
    with tab3:
        render_calendario_leads()
