# modules/auth.py - Versão atualizada e corrigida
import streamlit as st
from pymongo import MongoClient
import urllib.parse
import hashlib
import uuid
from datetime import datetime, timedelta
import streamlit.components.v1 as components
from streamlit_js_eval import streamlit_js_eval

# ============================================================================
# 🔐 FUNÇÕES DE LOCALSTORAGE
# ============================================================================

def remove_local_storage_token():
    """Remove o token de autenticação do localStorage do navegador"""
    components.html(
        """
        <script>
        console.log("🧹 localStorage: removendo crm_auth_token");
        localStorage.removeItem('crm_auth_token');
        </script>
        """,
        height=0,
        width=0,
    )

def get_local_storage_token():
    """Obtém o token do localStorage usando streamlit_js_eval"""
    try:
        token = streamlit_js_eval(
            js_expressions="localStorage.getItem('crm_auth_token')",
            key="get_token_js_" + str(datetime.now().timestamp())
        )
        return token
    except Exception as e:
        st.warning(f"⚠️ Erro ao ler token: {e}")
        return None

def set_local_storage_token(token):
    """Salva token no localStorage com verificação"""
    # Salva via components.html
    components.html(
        f"""
        <script>
            try {{
                console.log("💾 Salvando token no localStorage:", "{token[:20]}...");
                localStorage.setItem('crm_auth_token', '{token}');
                console.log("✅ Token salvo com sucesso!");
            }} catch (e) {{
                console.error("❌ Erro ao salvar token:", e);
            }}
        </script>
        """,
        height=0,
        width=0,
    )
    
    # Pequena pausa para o JavaScript ser executado
    import time
    time.sleep(0.3)
    
    # Verifica se o token foi realmente salvo
    token_verificado = get_local_storage_token()
    if token_verificado == token:
        return True
    else:
        return False

# ============================================================================
# 🧩 CONEXÕES COM MONGODB ATLAS
# ============================================================================

def get_mongo_client():
    """Retorna cliente MongoDB configurado com secrets do Streamlit."""
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

# ============================================================================
# 🔧 FUNÇÃO PARA LIMPAR TOKENS EXPIRADOS
# ============================================================================

def limpar_tokens_expirados():
    """Remove tokens expirados do banco para manter a coleção limpa"""
    try:
        usuarios_coll = get_usuarios_collection()
        result = usuarios_coll.update_many(
            {"token_expira_em": {"$lt": datetime.utcnow()}},
            {"$unset": {"token_autologin": "", "token_expira_em": ""}}
        )
        if result.modified_count > 0:
            print(f"🧹 {result.modified_count} tokens expirados removidos.")
        return result.modified_count
    except Exception as e:
        print(f"⚠️ Erro ao limpar tokens expirados: {e}")
        return 0

# ============================================================================
# 🔍 FUNÇÃO PARA VALIDAR TOKEN
# ============================================================================

def validar_token(token):
    """
    Valida um token de autologin.
    Retorna o usuário se válido, None caso contrário.
    """
    if not token:
        return None
    
    try:
        usuarios_coll = get_usuarios_collection()
        
        # Limpa tokens expirados antes de validar
        limpar_tokens_expirados()
        
        # Busca usuário com token válido e ativo
        usuario = usuarios_coll.find_one({
            "token_autologin": token,
            "token_expira_em": {"$gt": datetime.utcnow()},
            "ativo": True
        })
        
        return usuario
    except Exception as e:
        print(f"⚠️ Erro ao validar token: {e}")
        return None

# ============================================================================
# 🔑 INTERFACE DE LOGIN
# ============================================================================

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
        st.sidebar.caption("👤 Usuário fixo: sessão não persiste após fechar o navegador.")
    
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
            
            # Verifica se usuário está ativo
            if not usuario.get("ativo", True):
                st.sidebar.error("❌ Usuário desativado. Contate o administrador.")
                return
            
            # Valida senha com SHA-256
            senha_hash = hashlib.sha256(senha_input.encode()).hexdigest()
            if usuario.get("senha_hash") != senha_hash:
                st.sidebar.error("❌ Usuário ou senha inválidos")
                return
            
            perfil = usuario.get("perfil")
            
            # Perfis válidos
            perfis_validos = [
                "embaixador", "tecnico", "pap", "revenda",
                "admin", "recepcao", "atendente_n1",
                "supervisao_n1", "supervisao_n2", "supervisao_n3",
                "diretoria"
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
            
            # Persistência SÓ para dinâmicos
            if manter_conectado:
                sucesso = _handle_persistent_login(login_input)
                if not sucesso:
                    st.sidebar.warning("⚠️ Não foi possível ativar 'Manter conectado'. Faça login novamente.")
                    return
            
            st.rerun()

# ============================================================================
# 🧩 AUXILIARES DE SESSÃO
# ============================================================================

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
    Retorna True se tudo funcionar, False em caso de erro.
    """
    try:
        usuarios_coll = get_usuarios_collection()
        
        # 1. Limpa tokens antigos do usuário (evita múltiplos tokens)
        usuarios_coll.update_one(
            {"login": login},
            {"$unset": {"token_autologin": "", "token_expira_em": ""}}
        )
        
        # 2. Gera novo token
        token = str(uuid.uuid4())
        expira_em = datetime.utcnow() + timedelta(days=30)
        
        # 3. Salva no MongoDB
        result = usuarios_coll.update_one(
            {"login": login},
            {"$set": {
                "token_autologin": token,
                "token_expira_em": expira_em,
                "ultimo_login_em": datetime.utcnow()
            }},
            upsert=False
        )
        
        if result.matched_count == 0:
            st.error("⚠️ Erro: usuário não encontrado no MongoDB.")
            return False
        
        # 4. Salva no localStorage (com verificação)
        sucesso = set_local_storage_token(token)
        
        if sucesso:
            # 5. Registra sessão ativa
            if "active_sessions" not in st.session_state:
                st.session_state["active_sessions"] = {}
            st.session_state["active_sessions"][token] = {
                "login": login,
                "expira_em": expira_em
            }
            
            st.toast(
                "✅ Sessão persistente ativada! Você permanecerá conectado por 30 dias.",
                icon="🔒"
            )
            return True
        else:
            # Remove token do MongoDB se não salvou no localStorage
            usuarios_coll.update_one(
                {"login": login},
                {"$unset": {"token_autologin": "", "token_expira_em": ""}}
            )
            st.warning("⚠️ Não foi possível salvar o token no navegador. 'Manter conectado' desativado.")
            return False
            
    except Exception as e:
        st.error(f"❌ Erro ao configurar persistência: {e}")
        return False
