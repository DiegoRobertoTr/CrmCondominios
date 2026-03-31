# modules/auth.py
import streamlit as st
from pymongo import MongoClient
import urllib.parse
import hashlib
import uuid
from datetime import datetime, timedelta
import streamlit.components.v1 as components

# --- 🔐 Funções de localStorage (via components.html) ---
def remove_local_storage_token():
    """Remove o token de autenticação do localStorage do navegador"""
    components.html(
        """
        <script>
            console.log("🧹 localStorage: removendo crm_auth_token");
            localStorage.removeItem('crm_auth_token');
        </script>
        """,
        height=0, width=0,
    )

# --- 🧩 Conexões com MongoDB Atlas ---
def get_mongo_client():
    """
    Retorna cliente MongoDB configurado com secrets do Streamlit.
    ✅ URI ajustada para Atlas Free Tier com appName=Cluster0
    """
    try:
        username = st.secrets["mongo"]["MONGO_USERNAME"]
        password = st.secrets["mongo"]["MONGO_PASSWORD"]
        cluster_url = st.secrets["mongo"]["MONGO_CLUSTER_URL"]
    except KeyError:
        username = st.secrets.get("MONGO_USERNAME", "")
        password = st.secrets.get("MONGO_PASSWORD", "")
        cluster_url = st.secrets.get("MONGO_CLUSTER_URL", "cluster0.6eywlbl.mongodb.net")
    
    u = urllib.parse.quote_plus(username)
    p = urllib.parse.quote_plus(password)
    
    uri = f"mongodb+srv://{u}:{p}@{cluster_url}/?retryWrites=true&w=majority&appName=Cluster0"
    
    return MongoClient(uri)

def get_db_connection():
    """Retorna coleção 'clientes' do banco crm_db"""
    return get_mongo_client().crm_db.clientes

def get_usuarios_collection():
    """Retorna coleção 'usuarios' do banco crm_db"""
    return get_mongo_client().crm_db.usuarios

# --- 🔑 Interface de Login ---
def login():
    """Renderiza formulário de login com suporte a perfis múltiplos"""
    st.sidebar.title("🔐 Login CRM")
    login_input = st.sidebar.text_input("Usuário", key="login_input")
    senha_input = st.sidebar.text_input("Senha", type="password", key="senha_input")
    
    is_fixed_user = (
        login_input == st.secrets["usuarios"]["recepcao_login"] or
        login_input == st.secrets["usuarios"]["admin_login"]
    )
    
    manter_conectado = False
    if not is_fixed_user:
        manter_conectado = st.sidebar.checkbox("✅ Manter conectado", value=False)
    else:
        st.sidebar.caption("🔒 Usuário fixo: sessão não persiste após fechar o navegador.")

    if st.sidebar.button("Entrar", key="btn_entrar"):
        # === 1. Logins FIXOS (admin / recepção) ===
        if (login_input == st.secrets["usuarios"]["recepcao_login"] and
            senha_input == st.secrets["usuarios"]["recepcao_senha"]):
            _set_session("recepcao", login_input)
            st.rerun()

        elif (login_input == st.secrets["usuarios"]["admin_login"] and
              senha_input == st.secrets["usuarios"]["admin_senha"]):
            _set_session("admin", login_input)
            st.rerun()

        # === 2. Usuários DINÂMICOS (MongoDB) ===
        else:
            usuarios_coll = get_usuarios_collection()
            usuario = usuarios_coll.find_one({"login": login_input})
            
            if not usuario:
                st.sidebar.error("❌ Usuário ou senha inválidos")
                return

            # ✅ Verifica se usuário está ativo
            if not usuario.get("ativo", True):
                st.sidebar.error("❌ Usuário desativado. Contate o administrador.")
                return

            # Valida senha com SHA-256
            senha_hash = hashlib.sha256(senha_input.encode()).hexdigest()
            if usuario.get("senha_hash") != senha_hash:
                st.sidebar.error("❌ Usuário ou senha inválidos")
                return

            perfil = usuario.get("perfil")
            
            # ✅ Atualizado para incluir novos perfis de supervisão
            perfis_validos = [
                "embaixador", "tecnico", "pap", "revenda",  # Externos
                "admin", "recepcao", "atendente_n1",  # Internos básicos
                "supervisao_n1", "supervisao_n2", "supervisao_n3"  # ← NOVOS
            ]
            
            if perfil not in perfis_validos:
                st.sidebar.error("❌ Perfil não reconhecido.")
                return

            # Configura sessão
            _set_session(
                perfil=perfil,
                nome_exibicao=usuario["nome_exibicao"],
                codigo_embaixador=usuario.get("codigo_embaixador"),
                codigo_revenda=usuario.get("codigo_revenda"),
                login_tecnico=usuario.get("login") if perfil == "tecnico" else None
            )
            
            # ✅ Persistência SÓ para dinâmicos
            if manter_conectado:
                _handle_persistent_login(login_input)
            
            st.rerun()

# --- 🧠 Auxiliares de Sessão ---
def _set_session(perfil, nome_exibicao=None, codigo_embaixador=None, codigo_revenda=None, login_tecnico=None):
    """Configura variáveis de sessão do Streamlit"""
    st.session_state["logado"] = True
    st.session_state["perfil"] = perfil
    st.session_state["nome_usuario"] = nome_exibicao or login_tecnico or "Usuário"
    
    if codigo_embaixador:
        st.session_state["codigo_embaixador"] = codigo_embaixador
    if codigo_revenda:
        st.session_state["codigo_revenda"] = codigo_revenda
    if login_tecnico:
        st.session_state["login_tecnico"] = login_tecnico

def _handle_persistent_login(login):
    """
    Gera token de sessão persistente (30 dias) e salva no MongoDB + localStorage.
    ✅ Só chamado para perfis: embaixador, tecnico, pap, revenda
    """
    token = str(uuid.uuid4())
    expira_em = datetime.utcnow() + timedelta(days=30)
    
    usuarios_coll = get_usuarios_collection()
    result = usuarios_coll.update_one(
        {"login": login},
        {"$set": {"token_autologin": token, "token_expira_em": expira_em}},
        upsert=False
    )

    if result.matched_count == 0:
        st.error("⚠️ Erro: usuário não encontrado no MongoDB para persistência.")
        st.toast("❌ Não foi possível salvar a sessão. Verifique o usuário no banco.", icon="🚨")
        return

    components.html(
        f"""
        <script>
            console.log("🔐 Salvando token no localStorage para '{login}': ", "{token}");
            localStorage.setItem('crm_auth_token', '{token}');
        </script>
        """,
        height=0, width=0,
    )

    if "active_sessions" not in st.session_state:
        st.session_state["active_sessions"] = {}
    st.session_state["active_sessions"][token] = {
        "login": login,
        "expira_em": expira_em
    }

    st.toast(
        "✅ Sessão salva com sucesso. Você permanecerá conectado mesmo após fechar/reabrir o navegador.",
        icon="🔒"
    )
