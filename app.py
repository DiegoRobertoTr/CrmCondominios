# app.py - Condomínios Tracecom
# ✅ Atualizado com módulo de Pendências e Marketing Condomínios
# ✅ Atualizado com módulo de Visitas Vendedoras
# ✅ Adicionado módulo Informações Condomínios
# ✅ Adicionado módulo Vendas por Vendedor - Condomínios
import streamlit as st
from modules import auth, cadastro, followup, agendamentos, leads_eventos, pendencias
from modules import vendas_vendedor_condominios
from pymongo import MongoClient
import urllib.parse
from datetime import datetime
import streamlit.components.v1 as components
from streamlit_js_eval import streamlit_js_eval
from urllib.parse import urlencode
import base64

# ============================================================================
# 🏢 CONFIGURAÇÃO DE IMAGEM DE FUNDO COM OVERLAY
# ============================================================================

def get_base64_image(image_path):
    """Converte imagem local para base64 para usar como background."""
    try:
        with open(image_path, "rb") as img_file:
            return base64.b64encode(img_file.read()).decode()
    except Exception as e:
        st.warning(f"⚠️ Não foi possível carregar a imagem de fundo: {e}")
        return None

# Carrega a imagem de fundo
img_base64 = get_base64_image("assets/condominio.jpg")

# CSS personalizado com imagem de fundo e overlay
if img_base64:
    st.markdown(f"""
    <style>
    /* Imagem de fundo com overlay semi-transparente */
    .main {{
        background-image: url("data:image/jpeg;base64,{img_base64}");
        background-size: cover;
        background-position: center;
        background-attachment: fixed;
        position: relative;
    }}
    .main::before {{
        content: "";
        position: fixed;
        top: 0;
        left: 0;
        width: 100%;
        height: 100%;
        background: rgba(255, 255, 255, 0.88);
        z-index: -1;
    }}
    [data-testid="stSidebar"] {{
        background: rgba(255, 255, 255, 0.95);
        backdrop-filter: blur(10px);
    }}
    .stTextInput, .stSelectbox, .stNumberInput, .stTextArea {{
        background-color: rgba(255, 255, 255, 0.95);
        border-radius: 8px;
    }}
    .stExpander, .stContainer {{
        background-color: rgba(255, 255, 255, 0.9);
        border-radius: 10px;
    }}
    h1, h2, h3 {{
        text-shadow: 1px 1px 2px rgba(0, 0, 0, 0.1);
    }}
    </style>
    """, unsafe_allow_html=True)
else:
    st.markdown("""
    <style>
    .main {
        background: linear-gradient(135deg, #f5f7fa 0%, #c3cfe2 100%);
    }
    [data-testid="stSidebar"] {
        background: rgba(255, 255, 255, 0.95);
    }
    </style>
    """, unsafe_allow_html=True)

# ============================================================================
# ⭐ CONFIGURAÇÃO DA PÁGINA
# ============================================================================

st.set_page_config(
    page_title="Condominios Tracecom",
    page_icon="🏢",
    layout="wide",
    initial_sidebar_state="expanded"
)

# ============================================================================
# 🔹 ROTAS PÚBLICAS — DEVEM VIR PRIMEIRO, ANTES DE TUDO
# ============================================================================

query_params = st.query_params.to_dict()

# Rota para pesquisa de satisfação
if query_params.get("page") == ["satisfacao"]:
    id_cliente = query_params.get("id", [""])[0]
    tipo = query_params.get("tipo", [""])[0]
    os_id = query_params.get("os", [""])[0]
    
    link_base = "https://forms.gle/DNburCnrLyLgYcweA"
    params = {}
    if id_cliente: params["id"] = id_cliente
    if tipo: params["tipo"] = tipo
    if os_id: params["os"] = os_id
    
    redirect_url = link_base
    if params:
        redirect_url += "?" + urlencode(params)
        
    st.markdown(f'''
    <meta http-equiv="refresh" content="0;url={redirect_url}" />
    Redirecionando para pesquisa de satisfação...
    ''', unsafe_allow_html=True)
    st.stop()

# HotSpots WiFi — ROTA PÚBLICA (portal captive)
if query_params.get("page") == ["hotspots/captive"]:
    try:
        from modules.hotspots.captive_portal import render_captive_portal
        render_captive_portal()
    except Exception as e:
        st.error(f"Erro ao carregar portal: {e}")
        st.exception(e)
    st.stop()

# HotSpots — Confirmação de acesso (pública)
if query_params.get("page") == ["hotspots/confirmar"]:
    try:
        from modules.hotspots.confirmar_acesso import confirmar_acesso
        confirmar_acesso()
    except Exception as e:
        st.error(f"Erro na confirmação: {e}")
    st.stop()

# ============================================================================
# --- 🧩 DAQUI PARA BAIXO: Código privado (requer login) ---
# ============================================================================

# Função auxiliar: coleção de usuários
def get_usuarios_collection():
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
    return MongoClient(uri).crm_db.usuarios

# --- Conexão com clientes ---
if "clientes_collection" not in st.session_state:
    st.session_state["clientes_collection"] = auth.get_db_connection()
clientes_collection = st.session_state["clientes_collection"]

# --- Conexão com usuários (para o módulo de pendências) ---
if "usuarios_collection" not in st.session_state:
    st.session_state["usuarios_collection"] = get_usuarios_collection()

# Garante índices
try:
    clientes_collection.create_index("celular", unique=True)
    clientes_collection.create_index("nome_completo")
except Exception:
    pass

# ============================================================================
# --- 🔐 VERIFICAÇÃO AUTOMÁTICA DE LOGIN (USANDO auth.validar_token) ---
# ============================================================================

if "logado" not in st.session_state:
    st.session_state["logado"] = False

if not st.session_state["logado"]:
    token = None
    try:
        # Tenta ler o token do localStorage
        token = streamlit_js_eval(
            js_expressions="localStorage.getItem('crm_auth_token')",
            key="auto_login_token_check"
        )
    except Exception:
        pass

    if token:
        # ✅ Usa a nova função de validação do auth.py
        from modules.auth import validar_token
        usuario = validar_token(token)
        
        if usuario:
            perfil = usuario["perfil"]
            st.session_state.update({
                "logado": True,
                "perfil": perfil,
                "nome_usuario": usuario["nome_exibicao"]
            })
            
            if perfil == "embaixador":
                st.session_state["codigo_embaixador"] = usuario.get("codigo_embaixador")
            elif perfil == "tecnico":
                st.session_state["login_tecnico"] = usuario.get("login")
            elif perfil == "revenda":
                st.session_state["codigo_revenda"] = usuario.get("codigo_revenda")
            elif perfil == "vendedora":
                st.session_state["nome_vendedora"] = usuario.get("nome_exibicao")
            
            st.toast("✅ Sessão restaurada automaticamente.", icon="🔓")
            st.rerun()
        else:
            # Token inválido ou expirado
            auth.remove_local_storage_token()
            st.warning("⚠️ Sessão expirada. Faça login novamente.")

# ============================================================================
# --- 🚪 REDIRECIONA PARA LOGIN SE NÃO AUTENTICADO ---
# ============================================================================

if not st.session_state["logado"]:
    st.title("🔐 Condomínios Tracecom - Login")
    auth.login()
    st.stop()

# ============================================================================
# --- ✅ INTERFACE PRINCIPAL ---
# ============================================================================

st.sidebar.success(f"✅ Logado como: {st.session_state['perfil'].title()}")

# --- Badge de pendências no menu lateral ---
perfil = st.session_state["perfil"]
try:
    from modules.permissoes import get_perfis_pendencias
    perfis_pendencias = get_perfis_pendencias()
    
    if perfil in perfis_pendencias:
        pendencias_coll = clientes_collection.database.pendencias
        count_pendencias = pendencias_coll.count_documents({
            "responsavel": perfil,
            "status": {"$in": ["pendente", "em_andamento"]}
        })
        if count_pendencias > 0:
            st.sidebar.warning(f"📋 Você tem {count_pendencias} pendência(s) ativa(s)!")
except Exception:
    pass

if st.sidebar.button("🔄 Reiniciar Sistema", key="reiniciar_sistema_sidebar"):
    chaves_para_deletar = [k for k in st.session_state.keys() if not k.startswith("__")]
    for k in chaves_para_deletar:
        if k not in ["_components_callbacks"]:
            del st.session_state[k]
    st.success("Sistema reiniciado!")
    st.rerun()

st.sidebar.divider()
st.sidebar.header("📋 Módulos")

# ============================================================================
# --- 🎯 SISTEMA DE PERMISSÕES DINÂMICAS ---
# ============================================================================

try:
    from modules.permissoes import get_modulos_permitidos
    opcoes_modulos = get_modulos_permitidos(perfil)
except ImportError:
    # Fallback se módulo não existir ainda
    modulo_map = {
        "embaixador": ["Painel Embaixador"],
        "tecnico": ["Painel Técnico"],
        "pap": ["Cadastro Porta a Porta"],
        "revenda": ["Painel Revenda"],
        "vendedora": ["Visitas Vendedoras"],
        "admin": [
            "Cadastro", "Follow-up", "Agendamentos", "Pendências",
            "Admin Embaixadores", "Admin Técnicos", "Admin PaP", "Admin Revendas",
            "Admin Funcionários", "Condomínios", "Informações Condomínios",
            "Relatórios Condomínios", "Prospecção Condomínios",
            "Acompanhamento Técnicos", "Relatórios",
            "Roteiro de Vendas", "Endereços Bloqueados",
            "Marketing Condomínios", "Leads & Eventos",
            "Visitas Vendedoras",
            "Vendas por Vendedor - Condomínios"
        ],
        "recepcao": [
            "Cadastro", "Follow-up", "Agendamentos", "Pendências",
            "Roteiro de Vendas", "Endereços Bloqueados", "Leads & Eventos",
            "Visitas Vendedoras"
        ],
        "atendente_n1": [
            "Cadastro", "Follow-up", "Agendamentos", "Pendências",
            "Roteiro de Vendas", "Endereços Bloqueados", "Leads & Eventos",
            "Visitas Vendedoras"
        ],
        "supervisao_n1": [
            "Cadastro", "Follow-up", "Agendamentos", "Pendências",
            "Roteiro de Vendas",
            "Marketing Condomínios", "Leads & Eventos",
            "Visitas Vendedoras"
        ],
        "supervisao_n2": [
            "Cadastro", "Follow-up", "Agendamentos", "Pendências",
            "Roteiro de Vendas",
            "Admin Embaixadores", "Admin PaP", "Admin Revendas",
            "Marketing Condomínios", "Leads & Eventos",
            "Visitas Vendedoras"
        ],
        "supervisao_n3": [
            "Cadastro", "Follow-up", "Agendamentos", "Pendências",
            "Roteiro de Vendas",
            "Admin Embaixadores", "Admin PaP", "Admin Revendas",
            "Relatórios", "Relatórios Condomínios", "Prospecção Condomínios",
            "Marketing Condomínios", "Leads & Eventos",
            "Visitas Vendedoras"
        ],
        "diretoria": [
            "Relatórios Condomínios", "Prospecção Condomínios",
            "Visitas Vendedoras",
            "Vendas por Vendedor - Condomínios"
        ],
    }
    opcoes_modulos = modulo_map.get(perfil, [])

# Adiciona módulos extras para admin
if perfil == "admin":
    extras_admin = [
        "Admin Funcionários", "Condomínios", "Informações Condomínios", 
        "Relatórios Condomínios", "Prospecção Condomínios", "Marketing Condomínios",
        "Visitas Vendedoras", "Vendas por Vendedor - Condomínios"
    ]
    for mod in extras_admin:
        if mod not in opcoes_modulos:
            opcoes_modulos.append(mod)

modulo = st.sidebar.radio("Selecione o módulo:", opcoes_modulos, index=0, key="modulo_selecionado")

# ============================================================================
# --- 🔒 LOGOUT ---
# ============================================================================

if st.sidebar.button("🚪 Logout"):
    auth.remove_local_storage_token()
    for k in list(st.session_state.keys()):
        if k not in ["_components_callbacks"]:
            del st.session_state[k]
    st.session_state["logado"] = False
    st.rerun()

# ============================================================================
# --- 🏢 CABEÇALHO ---
# ============================================================================

col1, col2 = st.columns([1, 5])
with col1:
    st.image("logo.png", width=80)
with col2:
    st.title("🏢 Condomínios Tracecom")

# ============================================================================
# --- 📦 CARREGAMENTO DE MÓDULOS ---
# ============================================================================

try:
    if modulo == "Cadastro":
        cadastro.render_cadastro(clientes_collection)
        
    elif modulo == "Follow-up":
        followup.render_followup(clientes_collection)
        
    elif modulo == "Agendamentos":
        agendamentos.render_agendamentos(clientes_collection)
        
    elif modulo == "Pendências":
        pendencias.render_pendencias(clientes_collection)
        
    elif modulo == "Marketing Condomínios" and perfil in ["admin", "supervisao_n1", "supervisao_n2", "supervisao_n3"]:
        from modules import admin_condominios_marketing
        admin_condominios_marketing.render_admin_marketing()
        
    elif modulo == "Visitas Vendedoras":
        from modules.visitas_vendedoras import render_visitas_vendedoras
        render_visitas_vendedoras(clientes_collection)
        
    elif modulo == "Relatórios" and perfil in ["admin", "supervisao_n3"]:
        from modules import relatorios
        relatorios.render_relatorios(clientes_collection)
        
    elif modulo == "Condomínios" and perfil == "admin":
        from modules import condominios
        condominios.render_cadastro_condominio()
    
    elif modulo == "Informações Condomínios" and perfil == "admin":
        from modules.informacoes_condominios import render_informacoes_condominios
        render_informacoes_condominios()
        
    elif modulo == "Relatórios Condomínios" and perfil in ["admin", "supervisao_n3", "diretoria"]:
        from modules.relatorios_condominios import render_relatorios_condominios
        render_relatorios_condominios()
        
    elif modulo == "Prospecção Condomínios" and perfil in ["admin", "supervisao_n3", "diretoria"]:
        from modules.prospeccao_condominios import render_prospeccao_condominios
        render_prospeccao_condominios()
        
    elif modulo == "Vendas por Vendedor - Condomínios" and perfil in ["admin", "diretoria"]:
        from modules.vendas_vendedor_condominios import render_vendas_vendedor_condominios
        render_vendas_vendedor_condominios()
        
    elif modulo == "Painel Embaixador" and perfil == "embaixador":
        from modules import embaixador
        embaixador.render_embaixador(get_usuarios_collection(), clientes_collection)
        
    elif modulo == "Painel Revenda" and perfil == "revenda":
        from modules import revenda
        revenda.render_revenda(get_usuarios_collection(), clientes_collection)
        
    elif modulo == "Painel Técnico" and perfil == "tecnico":
        from modules import tecnico
        login_tecnico = st.session_state.get("login_tecnico", "")
        tecnico.render_tecnico(clientes_collection, login_tecnico)
        
    elif modulo == "Admin Embaixadores" and perfil in ["admin", "supervisao_n2", "supervisao_n3"]:
        from modules import admin_embaixadores
        admin_embaixadores.render_admin_embaixadores(get_usuarios_collection(), clientes_collection)
        
    elif modulo == "Admin Revendas" and perfil in ["admin", "supervisao_n2", "supervisao_n3"]:
        from modules import admin_revenda
        admin_revenda.render_admin_revenda(get_usuarios_collection(), clientes_collection)
        
    elif modulo == "Admin Técnicos" and perfil == "admin":
        from modules import admin_tecnicos
        admin_tecnicos.render_admin_tecnicos(get_usuarios_collection())
        
    elif modulo == "Admin PaP" and perfil in ["admin", "supervisao_n2", "supervisao_n3"]:
        from modules import pap_admin
        pap_admin.render_pap_admin(get_usuarios_collection(), clientes_collection)
        
    elif modulo == "Admin Funcionários" and perfil == "admin":
        from modules import admin_funcionarios
        admin_funcionarios.render_admin_funcionarios(get_usuarios_collection())
        
    elif modulo == "Cadastro Porta a Porta" and perfil == "pap":
        from modules import pap
        pap.render_pap(clientes_collection)
        
    elif modulo == "Acompanhamento Técnicos" and perfil == "admin":
        from modules import acompanhamento_tecnicos
        acompanhamento_tecnicos.render_acompanhamento_tecnicos(clientes_collection, get_usuarios_collection())
        
    elif modulo == "Roteiro de Vendas" and perfil in ["admin", "recepcao", "atendente_n1", "supervisao_n1", "supervisao_n2", "supervisao_n3"]:
        from modules import roteiro_vendas
        roteiro_vendas.render_roteiro_vendas(clientes_collection)
        
    elif modulo == "Leads & Eventos":
        st.title("📋 Gestão de Leads & Eventos")
        
        tab_cadastro, tab_agenda = st.tabs(["📝 Cadastro de Leads", "📅 Agenda & Lista"])
        
        with tab_cadastro:
            leads_eventos.render_registro_lead()
            
        with tab_agenda:
            leads_eventos.render_agenda_leads()
            
    elif modulo == "Endereços Bloqueados" and perfil in ["admin", "recepcao", "atendente_n1"]:
        from modules import enderecos_bloqueados
        enderecos_bloqueados.render_enderecos_bloqueados(clientes_collection)
        
    else:
        st.info("Selecione um módulo no menu lateral.")

except ImportError as e:
    st.error(f"⚠️ Módulo não encontrado ou importação falhou: `{e}`")
    st.info("Verifique se o arquivo está na pasta correta (`modules/`) e se o nome da função `render` está correto.")
except Exception as e:
    st.error("⚠️ Erro ao carregar o módulo.")
    st.exception(e)
