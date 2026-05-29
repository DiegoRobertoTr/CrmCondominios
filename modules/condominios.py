# modules/condominios.py - COMPLETO ATUALIZADO
import streamlit as st
from datetime import datetime
from pymongo import MongoClient
import urllib.parse

# Lista de opções de Zona
OPCOES_ZONA = [
    "Selecione...",
    "Zona Sul",
    "Zona Norte", 
    "Zona Oeste",
    "Zona Sudoeste",
    "Centro",
    "Baixada Fluminense",
    "Outros"
]

def get_condominios_collection():
    """Retorna coleção de condomínios"""
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
    
    return MongoClient(uri).crm_db.condominios

def render_cadastro_condominio():
    """Renderiza formulário de cadastro de condomínio"""
    st.title("🏢 Cadastro de Condomínios")
    
    # Abas para Cadastro e Lista/Edição
    tab1, tab2 = st.tabs(["📝 Novo Condomínio", "📋 Lista / Editar IDs IXC"])
    
    with tab1:
        with st.form("form_condominio"):
            col1, col2 = st.columns(2)
            
            with col1:
                nome = st.text_input("Nome do Condomínio *", max_chars=100)
                cnpj = st.text_input("CNPJ", max_chars=18, placeholder="00.000.000/0000-00")
                bairro = st.text_input("Bairro *", max_chars=50)
                zona = st.selectbox("Zona *", options=OPCOES_ZONA, index=0)
                estado = st.text_input("Estado", value="RJ", max_chars=2, disabled=True)
            
            with col2:
                endereco = st.text_input("Endereço *", max_chars=100)
                numero = st.text_input("Número *", max_chars=10)
                cidade = st.text_input("Cidade *", value="Rio de Janeiro", max_chars=50)
                cep = st.text_input("CEP", max_chars=10, placeholder="00000-000")
                id_ixc = st.text_input(
                    "ID no IXCsoft", 
                    max_chars=10, 
                    placeholder="Ex: 123",
                    help="ID numérico do condomínio no sistema IXCsoft (opcional, pode preencher depois)"
                )
            
            st.subheader("👤 Dados do Síndico")
            col3, col4 = st.columns(2)
            
            with col3:
                sindico = st.text_input("Nome do Síndico", max_chars=100)
                cel_sindico = st.text_input("Celular Síndico", max_chars=15, placeholder="(00) 00000-0000")
            
            with col4:
                contato = st.text_input("Nome do Contato", max_chars=100)
                cel_contato = st.text_input("Celular Contato", max_chars=15, placeholder="(00) 00000-0000")
            
            submitted = st.form_submit_button("💾 Salvar Condomínio", type="primary")
            
            if submitted:
                if not all([nome, endereco, numero, cidade, bairro]):
                    st.error("⚠️ Preencha os campos obrigatórios!")
                elif zona == "Selecione...":
                    st.error("⚠️ Selecione a Zona do condomínio!")
                else:
                    condominio_data = {
                        "nome": nome.upper().strip(),
                        "cnpj": cnpj.strip() if cnpj else None,
                        "cidade": cidade.strip(),
                        "estado": "RJ",
                        "bairro": bairro.strip(),
                        "zona": zona,
                        "endereco": endereco.strip(),
                        "numero": numero.strip(),
                        "cep": cep.strip() if cep else None,
                        "id_ixc": id_ixc.strip() if id_ixc else None,  # ✅ ID do IXC
                        "sindico": sindico.strip() if sindico else None,
                        "cel_sindico": cel_sindico.strip() if cel_sindico else None,
                        "contato": contato.strip() if contato else None,
                        "cel_contato": cel_contato.strip() if cel_contato else None,
                        "data_cadastro": datetime.now()
                    }
                    
                    try:
                        collection = get_condominios_collection()
                        result = collection.insert_one(condominio_data)
                        st.success(f"✅ Condomínio '{nome}' cadastrado com sucesso!")
                        if id_ixc:
                            st.info(f"📌 ID no IXC: {id_ixc}")
                        else:
                            st.info("🔧 Lembre-se de configurar o ID do IXC na aba 'Lista / Editar IDs IXC'")
                        st.balloons()
                    except Exception as e:
                        st.error(f"❌ Erro ao salvar: {e}")
    
    with tab2:
        render_lista_condominios()

def render_lista_condominios():
    """Exibe lista de condomínios e permite editar IDs do IXC"""
    collection = get_condominios_collection()
    condominios = list(collection.find().sort("nome", 1))
    
    if not condominios:
        st.info("Nenhum condomínio cadastrado ainda.")
        return
    
    st.subheader("📋 Condomínios Cadastrados")
    
    # Estatísticas rápidas
    total = len(condominios)
    com_id_ixc = sum(1 for c in condominios if c.get("id_ixc"))
    sem_id_ixc = total - com_id_ixc
    
    col1, col2, col3 = st.columns(3)
    with col1:
        st.metric("Total de Condomínios", total)
    with col2:
        st.metric("Com ID IXC configurado", com_id_ixc)
    with col3:
        st.metric("Sem ID IXC", sem_id_ixc, delta="⚠️ Pendente" if sem_id_ixc > 0 else None)
    
    if sem_id_ixc > 0:
        st.warning(f"⚠️ {sem_id_ixc} condomínio(s) sem ID do IXC configurado. A integração não enviará o campo 'id_condominio' para esses condomínios.")
    
    # Tabela de condomínios
    dados = []
    for c in condominios:
        dados.append({
            "ID IXC": c.get("id_ixc", "❌ Não configurado"),
            "Nome do Condomínio": c.get("nome", ""),
            "Cidade": c.get("cidade", ""),
            "Endereço": f"{c.get('endereco', '')}, {c.get('numero', '')}",
            "Zona": c.get("zona", ""),
            "_id": str(c["_id"])  # Guarda o ID para edição
        })
    
    st.dataframe(dados, use_container_width=True, height=400)
    
    # Editor de ID IXC
    st.divider()
    st.subheader("✏️ Configurar/Editar ID do IXC")
    
    # Selectbox para escolher o condomínio
    cond_options = [f"{c['nome']} - {c['cidade']}" for c in condominios]
    cond_selecionado_nome = st.selectbox(
        "Selecione o condomínio:",
        options=cond_options,
        key="editar_id_ixc_select"
    )
    
    if cond_selecionado_nome:
        # Encontrar o condomínio selecionado
        cond_atual = next(
            (c for c in condominios if f"{c['nome']} - {c['cidade']}" == cond_selecionado_nome),
            None
        )
        
        if cond_atual:
            col1, col2 = st.columns([2, 1])
            with col1:
                novo_id_ixc = st.text_input(
                    "ID no IXCsoft:",
                    value=cond_atual.get("id_ixc", ""),
                    placeholder="Digite o ID numérico (ex: 123)",
                    help="Este é o ID que você vê no sistema IXCsoft para este condomínio",
                    key="novo_id_ixc_input"
                )
            with col2:
                st.markdown("### ")
                if st.button("💾 Salvar ID IXC", type="primary", key="salvar_id_ixc"):
                    collection.update_one(
                        {"_id": cond_atual["_id"]},
                        {"$set": {"id_ixc": novo_id_ixc.strip() if novo_id_ixc else None}}
                    )
                    if novo_id_ixc:
                        st.success(f"✅ ID do IXC '{novo_id_ixc}' configurado para '{cond_atual['nome']}'!")
                    else:
                        st.warning(f"⚠️ ID do IXC removido para '{cond_atual['nome']}'. A integração não enviará este campo.")
                    st.rerun()

def get_condominio_by_id(condominio_id):
    """Busca condomínio por ID"""
    collection = get_condominios_collection()
    return collection.find_one({"_id": condominio_id})

def get_all_condominios():
    """Retorna todos os condomínios ordenados por nome"""
    collection = get_condominios_collection()
    return list(collection.find().sort("nome", 1))

def get_condominio_options():
    """Retorna lista de opções para selectbox (ID, nome)"""
    condominios = get_all_condominios()
    return {f"{c['nome']} - {c['cidade']}": c["_id"] for c in condominios}

def get_condominios_por_zona(zona=None):
    """Retorna condomínios filtrados por zona"""
    collection = get_condominios_collection()
    if zona:
        return list(collection.find({"zona": zona}).sort("nome", 1))
    return get_all_condominios()

def get_estatisticas_zonas():
    """Retorna contagem de condomínios por zona"""
    collection = get_condominios_collection()
    pipeline = [
        {"$group": {"_id": "$zona", "count": {"$sum": 1}}},
        {"$sort": {"count": -1}}
    ]
    return list(collection.aggregate(pipeline))
