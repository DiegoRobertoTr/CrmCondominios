import streamlit as st
from datetime import datetime
from pymongo import MongoClient
import urllib.parse

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
    
    with st.form("form_condominio"):
        col1, col2 = st.columns(2)
        with col1:
            nome = st.text_input("Nome do Condomínio *", max_chars=100)
            cnpj = st.text_input("CNPJ", max_chars=18, placeholder="00.000.000/0000-00")
            cidade = st.text_input("Cidade *", value="Rio de Janeiro", max_chars=50)
            estado = st.text_input("Estado", value="RJ", max_chars=2, disabled=True)
        
        with col2:
            endereco = st.text_input("Endereço *", max_chars=100)
            numero = st.text_input("Número *", max_chars=10)
            cep = st.text_input("CEP", max_chars=10, placeholder="00000-000")
        
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
            if not all([nome, endereco, numero, cidade]):
                st.error("⚠️ Preencha os campos obrigatórios!")
            else:
                condominio_data = {
                    "nome": nome.upper().strip(),
                    "cnpj": cnpj.strip() if cnpj else None,
                    "cidade": cidade.strip(),
                    "estado": "RJ",
                    "endereco": endereco.strip(),
                    "numero": numero.strip(),
                    "cep": cep.strip() if cep else None,
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
                    st.balloons()
                except Exception as e:
                    st.error(f"❌ Erro ao salvar: {e}")

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
