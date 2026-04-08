import streamlit as st
from modules import auth, cadastro, followup, agendamentos
from pymongo import MongoClient
import urllib.parse
from datetime import datetime
import streamlit.components.v1 as components
from streamlit_js_eval import streamlit_js_eval
from urllib.parse import urlencode
import base64

# ============================================================================
# CONFIGURACAO DE IMAGEM DE FUNDO COM OVERLAY
# ============================================================================
def get_base64_image(image_path):
    """Converte imagem local para base64 para usar como background."""
    try:
        with open(image_path, "rb") as img_file:
            return base64.b64encode(img_file.read()).decode()
    except Exception as e:
        st.warning(f"Nao foi possivel carregar a imagem de fundo: {e}")
        return None

# Carrega a imagem de fundo (ajuste o caminho conforme necessário)
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
    /* Overlay branco semi-transparente para melhorar legibilidade */
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
    /* Sidebar com leve transparência */
    [data-testid="stSidebar"] {{
        background: rgba(255, 255, 255, 0.95);
        backdrop-filter: blur(10px);
    }}
    /* Melhorar contraste dos elementos principais */
    .stTextInput, .stSelectbox, .stNumberInput, .stTextArea {{
        background-color: rgba(255, 255, 255, 0.95);
        border-radius: 8px;
    }}
    /* Cards e containers com fundo mais sólido */
    .stExpander, .stContainer {{
        background-color: rgba(255, 255, 255, 0.9);
        border-radius: 10px;
    }}
    /* Títulos com mais destaque */
    h1, h2, h3 {{
        text-shadow: 1px 1px 2px rgba(0, 0, 0, 0.1);
    }}
    </style>
    """, unsafe_allow_html=True)
else:
    # Fallback sem imagem
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
# Configuracao da pagina
# ============================================================================
st.set_page_config(
    page_title="Condominios Tracecom",
    page_icon="",
    layout="wide",
    initial_sidebar_state="expanded"
)

# ============================================================================
# ROTAS PUBLICAS — DEVEM VIR PRIMEIRO, ANTES DE TUDO
# ============================================================================
query_params = st.query_params.to_dict()

# Rota para pesquisa de satisfacao
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
    Redirecionando para pesquisa de satisfacao...
    ''', unsafe_allow_html=True)
    st.stop()

# HotSpots WiFi — ROTA PUBLICA (portal captive)
if query_params.get("page") == ["hotspots/captive"]:
    try:
        from modules.hotspots.captive_portal import render_captive_portal
        render_captive_portal()
    except Exception as e:
        st.error(f"Erro ao carregar portal: {e}")
        st.exception(e)
    st.stop()

# HotSpots — Confirmacao de acesso (publica)
if query_params.get("page") == ["hotspots/confirmar"]:
    try:
        from modules.hotspots.confirmar_acesso import confirmar_acesso
        confirmar_acesso()
    except Exception as e:
        st.error(f"Erro na confirmacao: {e}")
    st.stop()

# ============================================================================
# DAQUI PARA BAIXO: Codigo privado (requer login)
# ============================================================================

# Funcao auxiliar: colecao de usuarios
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

# Conexao com clientes
if "clientes_collection" not in st.session_state:
    st.session_state["clientes_collection"] = auth.get_db_connection()
clientes_collection = st.session_state["clientes_collection"]

# Garante indices
try:
    clientes_collection.create_index("celular", unique=True)
    clientes_collection.create_index("nome_completo")
except Exception:
    pass  # Indices ja podem existir

# ============================================================================
# Verificacao automatica de login (DEPOIS DAS ROTAS PUBLICAS)
# ============================================================================
if "logado" not in st.session_state:
    st.session_state["logado"] = False

if not st.session_state["logado"]:
    token = None
    try:
        token = streamlit_js_eval(
            js_expressions="localStorage.getItem('crm_auth_token')",
            key="auto_login_token_check"
        )
    except Exception:
        pass

    if token:
        try:
            usuarios_coll = get_usuarios_collection()
            usuario = usuarios_coll.find_one({
                "token_autologin": token,
                "token_expira_em": {"$gt": datetime.utcnow()}
            })
            
            if usuario:
                perfil = usuario["perfil"]
                st.session_state.update({
                    "logado": True,
                    "perfil": perfil,
                    "nome_usuario": usuario["nome_exibicao"]
                })
                
                if perfil == "embaixador":
                    st.session_state["codigo_embaixador"] = usuario["codigo_embaixador"]
                elif perfil == "tecnico":
                    st.session_state["login_tecnico"] = usuario["login"]
                elif perfil == "revenda":
                    st.session_state["codigo_revenda"] = usuario["codigo_revenda"]
                    
                st.toast("Sessao restaurada automaticamente.", icon="")
                st.rerun()
            else:
                auth.remove_local_storage_token()
                st.warning("Sessao expirada. Faca login novamente.")
        except Exception as e:
            st.warning("Erro ao validar sessao. Faca login novamente.")
            auth.remove_local_storage_token()

# ============================================================================
# Redireciona para login se nao autenticado
# ============================================================================
if not st.session_state["logado"]:
    st.title("Condominios Tracecom - Login")
    auth.login()
    st.stop()

# ============================================================================
# Interface principal
# ============================================================================
st.sidebar.success(f"Logado como: {st.session_state['perfil'].title()}")

if st.sidebar.button("Reiniciar Sistema", key="reiniciar_sistema_sidebar"):
    chaves_para_deletar = [k for k in st.session_state.keys() if not k.startswith("__")]
    for k in chaves_para_deletar:
        if k not in ["_components_callbacks"]:
            del st.session_state[k]
    st.success("Sistema reiniciado!")
    st.rerun()

st.sidebar.divider()
st.sidebar.header("Modulos")

# ============================================================================
# SISTEMA DE PERMISSOES DINAMICAS
# ============================================================================
perfil = st.session_state["perfil"]

# Importa permissoes centralizadas
try:
    from modules.permissoes import get_modulos_permitidos
    opcoes_modulos = get_modulos_permitidos(perfil)
except ImportError:
    # Fallback se modulo nao existir ainda
    modulo_map = {
        "embaixador": ["Painel Embaixador"],
        "tecnico": ["Painel Tecnico"],
        "pap": ["Cadastro Porta a Porta"],
        "revenda": ["Painel Revenda"],
        "admin": [
            "Cadastro", "Follow-up", "Agendamentos",
            "Admin Embaixadores", "Admin Tecnicos", "Admin PaP", "Admin Revendas",
            "Admin Funcionarios", "Condominios", "Relatorios Condominios", "Prospeccao Condominios",
            "Acompanhamento Tecnicos", "Relatorios",
            "Roteiro de Vendas", "HotSpots WiFi", "Satisfacao",
            "Monitoramento de E-mails", "Teste de Integracao",
            "Enderecos Bloqueados"
        ],
        "recepcao": [
            "Cadastro", "Follow-up", "Agendamentos",
            "Roteiro de Vendas", "HotSpots WiFi", "Satisfacao",
            "Enderecos Bloqueados"
        ],
        "atendente_n1": [
            "Cadastro", "Follow-up", "Agendamentos",
            "Roteiro de Vendas", "HotSpots WiFi", "Satisfacao",
            "Enderecos Bloqueados"
        ],
        "supervisao_n1": [
            "Cadastro", "Follow-up", "Agendamentos", "Roteiro de Vendas"
        ],
        "supervisao_n2": [
            "Cadastro", "Follow-up", "Agendamentos", "Roteiro de Vendas",
            "Admin Embaixadores", "Admin PaP", "Admin Revendas"
        ],
        "supervisao_n3": [
            "Cadastro", "Follow-up", "Agendamentos", "Roteiro de Vendas",
            "Admin Embaixadores", "Admin PaP", "Admin Revendas",
            "Relatorios", "Relatorios Condominios", "Prospeccao Condominios"
        ],
        # NOVO PERFIL: DIRETORIA
        "diretoria": [
            "Relatorios Condominios",
            "Prospeccao Condominios"
        ]
    }
    opcoes_modulos = modulo_map.get(perfil, [])

modulo = st.sidebar.radio("Selecione o modulo:", opcoes_modulos, index=0, key="modulo_selecionado")

# ============================================================================
# Logout
# ============================================================================
if st.sidebar.button("Logout"):
    auth.remove_local_storage_token()
    for k in list(st.session_state.keys()):
        if k not in ["_components_callbacks"]:
            del st.session_state[k]
    st.session_state["logado"] = False
    st.rerun()

# ============================================================================
# Cabecalho
# ============================================================================
col1, col2 = st.columns([1, 5])
with col1:
    st.image("logo.png", width=80)
with col2:
    st.title("Condominios Tracecom")

# ============================================================================
# Carregamento de modulos
# ============================================================================
try:
    if modulo == "Cadastro":
        cadastro.render_cadastro(clientes_collection)
        
    elif modulo == "Follow-up":
        followup.render_followup(clientes_collection)
        
    elif modulo == "Agendamentos":
        agendamentos.render_agendamentos(clientes_collection)
        
    elif modulo == "Relatorios" and perfil in ["admin", "supervisao_n3"]:
        from modules import relatorios
        relatorios.render_relatorios(clientes_collection)
        
    elif modulo == "Condominios" and perfil == "admin":
        from modules import condominios
        condominios.render_cadastro_condominio()
        
    # MODULO: RELATORIOS CONDOMINIOS (Atualizado para incluir 'diretoria')
    elif modulo == "Relatorios Condominios" and perfil in ["admin", "supervisao_n3", "diretoria"]:
        from modules.relatorios_condominios import render_relatorios_condominios
        render_relatorios_condominios()
        
    # MODULO: PROSPECCAO CONDOMINIOS (Atualizado para incluir 'diretoria')
    elif modulo == "Prospeccao Condominios" and perfil in ["admin", "supervisao_n3", "diretoria"]:
        from modules.prospeccao_condominios import render_prospeccao_condominios
        render_prospeccao_condominios()

    elif modulo == "Painel Embaixador" and perfil == "embaixador":
        from modules import embaixador
        embaixador.render_embaixador(get_usuarios_collection(), clientes_collection)
        
    elif modulo == "Painel Revenda" and perfil == "revenda":
        from modules import revenda
        revenda.render_revenda(get_usuarios_collection(), clientes_collection)
        
    elif modulo == "Painel Tecnico" and perfil == "tecnico":
        from modules import tecnico
        login_tecnico = st.session_state.get("login_tecnico", "")
        tecnico.render_tecnico(clientes_collection, login_tecnico)
        
    elif modulo == "Admin Embaixadores" and perfil in ["admin", "supervisao_n2", "supervisao_n3"]:
        from modules import admin_embaixadores
        admin_embaixadores.render_admin_embaixadores(get_usuarios_collection(), clientes_collection)
        
    elif modulo == "Admin Revendas" and perfil in ["admin", "supervisao_n2", "supervisao_n3"]:
        from modules import admin_revenda
        admin_revenda.render_admin_revenda(get_usuarios_collection(), clientes_collection)
        
    elif modulo == "Admin Tecnicos" and perfil == "admin":
        from modules import admin_tecnicos
        admin_tecnicos.render_admin_tecnicos(get_usuarios_collection())
        
    elif modulo == "Admin PaP" and perfil in ["admin", "supervisao_n2", "supervisao_n3"]:
        from modules import pap_admin
        pap_admin.render_pap_admin(get_usuarios_collection(), clientes_collection)
        
    elif modulo == "Admin Funcionarios" and perfil == "admin":
        from modules import admin_funcionarios
        admin_funcionarios.render_admin_funcionarios(get_usuarios_collection())
        
    elif modulo == "Cadastro Porta a Porta" and perfil == "pap":
        from modules import pap
        pap.render_pap(clientes_collection)
        
    elif modulo == "Acompanhamento Tecnicos" and perfil == "admin":
        from modules import acompanhamento_tecnicos
        acompanhamento_tecnicos.render_acompanhamento_tecnicos(clientes_collection, get_usuarios_collection())
        
    elif modulo == "Roteiro de Vendas" and perfil in ["admin", "recepcao", "atendente_n1", "supervisao_n1", "supervisao_n2", "supervisao_n3"]:
        from modules import roteiro_vendas
        roteiro_vendas.render_roteiro_vendas(clientes_collection)
        
    elif modulo == "HotSpots WiFi" and perfil in ["admin", "recepcao", "atendente_n1"]:
        from modules.hotspots.hotspots import render_hotspots
        render_hotspots(clientes_collection)
        
    elif modulo == "Satisfacao" and perfil in ["admin", "recepcao", "atendente_n1"]:
        import pandas as pd
        st.title("Dashboard de Satisfacao — LGPD Compliant")
        db = clientes_collection.database
        respostas = list(db.satisfacao_respostas.find())
        if not respostas:
            st.info("Nenhuma resposta registrada ainda.")
        else:
            df = pd.DataFrame(respostas)
            col1, col2, col3 = st.columns(3)
            col1.metric("Total de Respostas", len(df))
            col2.metric("NPS Medio", f"{df['nps'].mean():.1f}")
            st.subheader("NPS ao longo do tempo")
            df_sorted = df.sort_values("data_resposta")
            st.line_chart(df_sorted.set_index("data_resposta")["nps"])
            criticos = df[df["nps"] <= 6][["nome_completo", "nps", "feedback"]]
            if not criticos.empty:
                st.subheader("Feedbacks Criticos (NPS <=6)")
                st.dataframe(criticos)
                
    elif modulo == "Monitoramento de E-mails" and perfil == "admin":
        from modules import monitoramento_emails
        monitoramento_emails.render_monitoramento()
        
    elif modulo == "Teste de Integracao" and perfil == "admin":
        from modules import teste_integracao
        teste_integracao.render_teste_integracao()
        
    elif modulo == "Enderecos Bloqueados" and perfil in ["admin", "recepcao", "atendente_n1"]:
        from modules import enderecos_bloqueados
        enderecos_bloqueados.render_enderecos_bloqueados(clientes_collection)
        
    else:
        st.info("Selecione um modulo no menu lateral.")

except ImportError as e:
    st.error(f"Modulo nao encontrado ou importacao falhou: `{e}`")
    st.info("Verifique se o arquivo esta na pasta correta (`modules/`) e se o nome da funcao `render` esta correto.")
except Exception as e:
    st.error("Erro ao carregar o modulo.")
    st.exception(e)
