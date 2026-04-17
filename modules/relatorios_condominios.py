"""
Módulo de Relatórios de Condomínios para a DR Tracecom Suite Analítica.
Pode ser chamado via relatorios_condominios.render_relatorios_condominios()

Melhorias implementadas:
- GridFS para armazenamento de arquivos originais
- Pré-carregamento automático dos últimos dados
- Session state estruturado
- Exclusão com confirmação de senha
- Processamento otimizado com referência ao arquivo original
"""
import streamlit as st
import pandas as pd
import numpy as np
import plotly.express as px
import plotly.graph_objects as go
from datetime import datetime, timedelta
from pymongo import MongoClient, ASCENDING, DESCENDING
from pymongo.errors import ServerSelectionTimeoutError, ConnectionFailure
from gridfs import GridFS
from bson import ObjectId
from urllib.parse import quote_plus
import io
import traceback
import warnings

warnings.filterwarnings('ignore')

# ==================== IMPORTAÇÕES PARA O MAPA ====================
try:
    import folium
    from streamlit_folium import st_folium
    from geopy.geocoders import Nominatim
    from geopy.exc import GeocoderUnavailable, GeocoderServiceError
    GEOCODING_AVAILABLE = True
except ImportError:
    GEOCODING_AVAILABLE = False

# ==================== CONFIGURAÇÃO INICIAL ====================
st.set_page_config(page_title="Relatórios Condomínios", layout="wide", initial_sidebar_state="collapsed")

# ==================== CONFIGURAÇÃO DO MÓDULO ====================
CONDOMINIOS_CONFIG = {
    'colunas_obrigatorias_clientes': [
        'CONDOMANIO', 'STATUS ACESSO', 'FINANCEIRO EM ATRASO'
    ],
    'colunas_obrigatorias_condominios': [
        'ID', 'Condomínio', 'Apartamentos', 'Região'
    ],
    'modo_ativos_opcoes': {
        'somente_ativos': 'Apenas Ativos Puros',
        'todos_ativos': 'Todos os Ocupados (Ativos + Atraso + Bloqueio)'
    },
    'colecoes': {
        'dados_processados': 'condominios_relatorios',
        'metadados': 'condominios_meta',
        'gridfs': 'fs.files'
    }
}

# ==================== INICIALIZAÇÃO DO SESSION STATE ====================
def initialize_session_state():
    """Inicializa estado da sessão de forma estruturada"""
    defaults = {
        'condominios_dados_clientes': None,
        'condominios_dados_condominios': None,
        'condominios_processado': False,
        'condominios_file_id': None,
        'condominios_nome_arquivo': None,
        'condominios_meta': None,
        'condominios_filtros': {
            'regiao': None,
            'modo_ativos': 'somente_ativos'
        },
        'condominios_config': CONDOMINIOS_CONFIG,
        'exclusao_confirmada': False,
        'file_id_a_excluir': None,
        'colecao_a_excluir': 'condominios_relatorios',
        'batch_id_a_excluir': None,
        'condominios_colunas_mapeadas': {}
    }
    
    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value

# ==================== FUNÇÕES DE UI ====================
def titulo_principal(texto):
    st.markdown(f"<h1 style='font-size: 28px; font-weight: bold; color: #2c3e50;'>{texto}</h1>", unsafe_allow_html=True)

def subtitulo(texto):
    st.markdown(f"<h3 style='color: #34495e;'>{texto}</h3>", unsafe_allow_html=True)

# ==================== CONEXÃO MONGODB ====================
@st.cache_resource
def init_mongo():
    """Inicializa conexão MongoDB com índices"""
    try:
        uri = st.secrets.get("MONGO_URI")
        if not uri:
            mongo_cfg = st.secrets.get("mongo", {})
            username = mongo_cfg.get("MONGO_USERNAME")
            password = mongo_cfg.get("MONGO_PASSWORD")
            cluster = mongo_cfg.get("MONGO_CLUSTER_URL")
            database = mongo_cfg.get("MONGO_DATABASE", "tracecom_crm")
            
            if not all([username, password, cluster]):
                st.error("🚨 Credenciais MongoDB incompletas nos Secrets.")
                st.stop()
            
            uri = f"mongodb+srv://{username}:{quote_plus(password)}@{cluster}/{database}?retryWrites=true&w=majority"
        
        client = MongoClient(uri, serverSelectionTimeoutMS=5000, connectTimeoutMS=5000)
        client.admin.command('ping')
        database_name = st.secrets.get("mongo", {}).get("MONGO_DATABASE", "tracecom_crm")
        db = client[database_name]
        
        # Criar índices para acelerar consultas
        criar_indices_mongodb(db)
        
        return db
    except (ServerSelectionTimeoutError, ConnectionFailure) as e:
        st.error(f"❌ Falha ao conectar ao MongoDB:\n`{type(e).__name__}: {e}`")
        st.stop()
    except Exception as e:
        st.error(f"❌ Erro inesperado ao conectar: {type(e).__name__}: {e}")
        st.stop()

def criar_indices_mongodb(db):
    """Cria índices para acelerar consultas"""
    try:
        db["condominios_relatorios"].create_index([("_import_batch", ASCENDING)])
        db["condominios_relatorios"].create_index([("module", ASCENDING)])
        db["condominios_relatorios"].create_index([("CONDOMANIO", ASCENDING)])
        db["condominios_meta"].create_index([("timestamp", DESCENDING)])
        db["condominios_meta"].create_index([("batch_id", ASCENDING)])
        db["condominios_meta"].create_index([("module", ASCENDING)])
        print("✅ Índices MongoDB criados/atualizados")
    except Exception as e:
        print(f"⚠️ Aviso ao criar índices: {e}")

def get_gridfs():
    """Retorna instância do GridFS"""
    db = init_mongo()
    return GridFS(db)

# ==================== FUNÇÕES GRIDFS ====================
def save_excel_to_gridfs(file_obj, module_name="condominios"):
    """
    Salva arquivo Excel no GridFS
    Igual ao analise_financeira
    """
    try:
        fs = get_gridfs()
        file_id = fs.put(
            file_obj.getvalue(),
            filename=file_obj.name,
            module=module_name,
            upload_date=datetime.now().replace(tzinfo=None),
            content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )
        return str(file_id)
    except Exception as e:
        st.error(f"❌ Erro ao salvar no GridFS: {str(e)}")
        return None

def load_excel_from_gridfs(file_id):
    """
    Carrega arquivo Excel do GridFS
    Igual ao analise_financeira
    """
    try:
        fs = get_gridfs()
        file_data = fs.get(ObjectId(file_id))
        return file_data
    except Exception as e:
        st.error(f"❌ Arquivo não encontrado no GridFS: {str(e)}")
        return None

# ==================== FUNÇÕES UTILITÁRIAS ====================
def limpar_valor_data(valor):
    """Limpa e padroniza valores de data"""
    if pd.isna(valor) or valor is None:
        return None
    if isinstance(valor, str):
        valor_limpo = valor.strip()
        if valor_limpo in ["00/00/0000", "0", " ", "nan", "NaT", "null", "NULL"]:
            return None
        try:
            valor = pd.to_datetime(valor_limpo, errors='coerce')
            if pd.isna(valor):
                return None
        except:
            return None
    if isinstance(valor, pd.Timestamp):
        if pd.isna(valor):
            return None
        try:
            return valor.to_pydatetime().replace(tzinfo=None)
        except:
            return None
    if isinstance(valor, datetime):
        if valor.tzinfo is not None:
            try:
                return valor.replace(tzinfo=None)
            except:
                return None
        return valor
    return None

def converter_dataframe_dates(df):
    """Conversão vetorial de datas"""
    df = df.copy()
    for col in df.columns:
        col_lower = col.lower()
        eh_coluna_data = any(palavra in col_lower for palavra in 
                           ['data', 'date', 'cadastro', 'ativacao', 'cancelamento', 
                            'nascimento', 'renovacao'])
        if eh_coluna_data or pd.api.types.is_datetime64_any_dtype(df[col]):
            df[col] = pd.to_datetime(df[col], errors='coerce')
            df[col] = df[col].apply(lambda x: limpar_valor_data(x))
    return df

def safe_mongo_docs(df):
    """
    Converte DataFrame para lista de dicts seguros para o MongoDB.
    - Substitui NaT, NaN, inf por None (BSON-safe)
    - Converte Timestamps pandas para datetime Python sem timezone
    """
    import math
    records = df.to_dict('records')
    safe_records = []
    for doc in records:
        safe_doc = {}
        for k, v in doc.items():
            if v is None:
                safe_doc[k] = None
            elif isinstance(v, pd.Timestamp):
                if pd.isna(v):
                    safe_doc[k] = None
                else:
                    try:
                        safe_doc[k] = v.to_pydatetime().replace(tzinfo=None)
                    except Exception:
                        safe_doc[k] = None
            elif isinstance(v, datetime):
                try:
                    safe_doc[k] = v.replace(tzinfo=None)
                except Exception:
                    safe_doc[k] = None
            elif isinstance(v, float):
                if math.isnan(v) or math.isinf(v):
                    safe_doc[k] = None
                else:
                    safe_doc[k] = v
            else:
                try:
                    if pd.isna(v):
                        safe_doc[k] = None
                    else:
                        safe_doc[k] = v
                except (TypeError, ValueError):
                    safe_doc[k] = v
        safe_records.append(safe_doc)
    return safe_records

def formatar_numero_br(valor, decimais=0):
    """Formata número para padrão brasileiro"""
    if pd.isna(valor) or valor is None:
        return "0"
    try:
        numero = float(valor)
        if decimais == 0:
            return f"{int(numero):,}".replace(",", ".")
        else:
            formatado = f"{numero:,.{decimais}f}"
            formatado = formatado.replace(",", "X").replace(".", ",").replace("X", ".")
            return formatado
    except:
        return str(valor)

def safe_strftime(value, fmt="%d/%m/%Y %H:%M"):
    """Converte data para string com segurança"""
    if pd.isna(value) or value is None:
        return ""
    if isinstance(value, (pd.Timestamp, datetime)):
        try:
            if hasattr(value, 'tzinfo') and value.tzinfo is not None:
                value = value.replace(tzinfo=None)
            return value.strftime(fmt)
        except (ValueError, OSError):
            return ""
    return str(value)

# ==================== FUNÇÕES DE BANCO DE DADOS ====================
def save_condominio_data_enhanced(db, df_clientes, df_condominios, metadata):
    """
    Versão melhorada do save_condominio_data com:
    - Referência ao source_file_id (GridFS)
    - Limpeza apenas de batches do mesmo módulo
    - Uso de safe_mongo_docs para evitar NaT
    """
    collection_clientes = db["condominios_relatorios"]
    collection_meta = db["condominios_meta"]
    
    batch_id = metadata["batch_id"]
    module = metadata.get("module", "condominios")
    
    # Limpar apenas dados antigos deste módulo
    count_clientes_del = collection_clientes.delete_many({
        "_import_batch": {"$ne": batch_id},
        "module": module
    }).deleted_count
    
    count_meta_del = collection_meta.delete_many({
        "batch_id": {"$ne": batch_id},
        "module": module
    }).deleted_count
    
    if count_clientes_del > 0 or count_meta_del > 0:
        print(f"🧹 Limpeza: {count_clientes_del} clientes e {count_meta_del} metadados antigos removidos.")
    
    # Preparar dados de clientes
    df_clientes_limpo = converter_dataframe_dates(df_clientes)
    df_clientes_limpo["_import_timestamp"] = datetime.now().replace(tzinfo=None)
    df_clientes_limpo["_import_batch"] = batch_id
    df_clientes_limpo["source_file_id"] = metadata["source_file_id"]
    df_clientes_limpo["module"] = module
    
    # Converter para docs seguros
    docs = safe_mongo_docs(df_clientes_limpo)
    
    if docs:
        collection_clientes.insert_many(docs)
    
    # Preparar condomínios para metadados
    condominios_records = safe_mongo_docs(df_condominios)
    metadata["condominios"] = condominios_records
    metadata["module"] = module
    
    # Inserir metadata
    collection_meta.insert_one(metadata)
    
    return True

def carregar_dados_mais_recentes(db):
    """
    Carrega automaticamente os dados mais recentes do MongoDB
    Igual ao analise_financeira.carregar_dados_mais_recentes()
    """
    try:
        # Buscar o batch mais recente deste módulo
        latest_meta = db["condominios_meta"].find(
            {"module": "condominios"}
        ).sort("timestamp", -1).limit(1)
        
        meta_list = list(latest_meta)
        
        if not meta_list:
            return False
        
        meta = meta_list[0]
        batch_id = meta.get('batch_id')
        source_file_id = meta.get('source_file_id')
        file_name = meta.get('filename', 'Arquivo carregado')
        
        # Carregar dados de clientes
        cursor_clientes = db["condominios_relatorios"].find({
            "_import_batch": batch_id,
            "module": "condominios"
        })
        df_clientes = pd.DataFrame(list(cursor_clientes))
        
        if df_clientes.empty:
            return False
        
        # Remover colunas do MongoDB
        for col in ['_id', '_import_timestamp', '_import_batch', 'source_file_id', 'module']:
            if col in df_clientes.columns:
                df_clientes = df_clientes.drop(columns=[col])
        
        # Carregar condomínios dos metadados
        df_condominios = pd.DataFrame(meta.get("condominios", []))
        
        # Converter datas
        df_clientes = converter_dataframe_dates(df_clientes)
        df_condominios = converter_dataframe_dates(df_condominios)
        
        # Normalizar tipos
        if "CONDOMANIO" in df_clientes.columns:
            df_clientes["CONDOMANIO"] = pd.to_numeric(df_clientes["CONDOMANIO"], errors="coerce").fillna(0).astype(int)
        if "ID" in df_condominios.columns:
            df_condominios["ID"] = pd.to_numeric(df_condominios["ID"], errors="coerce").fillna(0).astype(int)
        if "Apartamentos" in df_condominios.columns:
            df_condominios["Apartamentos"] = pd.to_numeric(df_condominios["Apartamentos"], errors="coerce").fillna(0).astype(int)
        
        # Atualizar session_state
        st.session_state.condominios_dados_clientes = df_clientes
        st.session_state.condominios_dados_condominios = df_condominios
        st.session_state.condominios_meta = meta
        st.session_state.condominios_file_id = source_file_id
        st.session_state.condominios_nome_arquivo = file_name
        st.session_state.condominios_processado = True
        
        return True
        
    except Exception as e:
        print(f"❌ Erro ao carregar dados automáticos: {str(e)}")
        return False

def clear_condominio_data(db, batch_id=None, module="condominios"):
    """Limpa dados do banco com filtro por módulo"""
    collection_clientes = db["condominios_relatorios"]
    collection_meta = db["condominios_meta"]
    
    if batch_id:
        result_clientes = collection_clientes.delete_many({
            "_import_batch": batch_id,
            "module": module
        })
        result_meta = collection_meta.delete_many({
            "batch_id": batch_id,
            "module": module
        })
    else:
        result_clientes = collection_clientes.delete_many({"module": module})
        result_meta = collection_meta.delete_many({"module": module})
    
    return result_clientes.deleted_count + result_meta.deleted_count

# ==================== PROCESSAMENTO DE UPLOAD ====================
def processar_upload_condominios(db, uploaded_file):
    """
    Processa upload de planilha e salva no GridFS + MongoDB
    Igual ao fluxo do analise_financeira
    """
    with st.spinner('💾 Salvando arquivo no GridFS...'):
        file_id = save_excel_to_gridfs(uploaded_file, "condominios")
        
        if not file_id:
            st.error("❌ Falha ao salvar arquivo no GridFS")
            return False
        
        st.success(f"📁 Arquivo salvo com ID: {file_id[:8]}...")
    
    with st.spinner('🔄 Processando planilha...'):
        try:
            # Ler planilha
            df_clientes = pd.read_excel(uploaded_file, sheet_name="Dados")
            df_condominios = pd.read_excel(uploaded_file, sheet_name="Condominios")
            
            # Validar colunas obrigatórias
            colunas_faltantes_clientes = [
                col for col in CONDOMINIOS_CONFIG['colunas_obrigatorias_clientes'] 
                if col not in df_clientes.columns
            ]
            colunas_faltantes_condominios = [
                col for col in CONDOMINIOS_CONFIG['colunas_obrigatorias_condominios'] 
                if col not in df_condominios.columns
            ]
            
            if colunas_faltantes_clientes:
                st.warning(f"⚠️ Colunas faltantes em Dados: {colunas_faltantes_clientes}")
            if colunas_faltantes_condominios:
                st.warning(f"⚠️ Colunas faltantes em Condominios: {colunas_faltantes_condominios}")
            
            # Normalizar chaves
            if "CONDOMANIO" in df_clientes.columns:
                df_clientes["CONDOMANIO"] = pd.to_numeric(
                    df_clientes["CONDOMANIO"], errors="coerce"
                ).fillna(0).astype(int)
            
            if "ID" in df_condominios.columns:
                df_condominios["ID"] = pd.to_numeric(
                    df_condominios["ID"], errors="coerce"
                ).fillna(0).astype(int)
            
            if "Apartamentos" in df_condominios.columns:
                df_condominios["Apartamentos"] = pd.to_numeric(
                    df_condominios["Apartamentos"], errors="coerce"
                ).fillna(0).astype(int)
            
            # Converter datas
            df_clientes = converter_dataframe_dates(df_clientes)
            df_condominios = converter_dataframe_dates(df_condominios)
            
            # Criar metadados com referência ao arquivo original
            batch_id = f"batch_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
            metadata = {
                "batch_id": batch_id,
                "source_file_id": file_id,
                "filename": uploaded_file.name,
                "timestamp": datetime.now().replace(tzinfo=None),
                "total_clientes": len(df_clientes),
                "total_condominios": len(df_condominios),
                "module": "condominios"
            }
            
            # Salvar no MongoDB
            if save_condominio_data_enhanced(db, df_clientes, df_condominios, metadata):
                # Atualizar session_state
                st.session_state.condominios_dados_clientes = df_clientes
                st.session_state.condominios_dados_condominios = df_condominios
                st.session_state.condominios_meta = metadata
                st.session_state.condominios_file_id = file_id
                st.session_state.condominios_nome_arquivo = uploaded_file.name
                st.session_state.condominios_processado = True
                
                st.success(f"✅ {len(df_clientes)} clientes e {len(df_condominios)} condomínios processados!")
                st.balloons()
                return True
            else:
                st.error("❌ Falha ao salvar dados processados")
                return False
                
        except Exception as e:
            st.error(f"❌ Erro no processamento: {str(e)}")
            with st.expander("🔍 Detalhes técnicos"):
                st.code(traceback.format_exc())
            return False

# ==================== FUNÇÕES DE ANÁLISE ====================
def gerar_dashboard_principal(df_clientes, df_condominios, modo_ativos="somente_ativos"):
    """Gera dashboard principal sem cache excessivo"""
    if df_clientes is None or df_condominios is None:
        return pd.DataFrame()
    
    if "CONDOMANIO" not in df_clientes.columns or "ID" not in df_condominios.columns:
        return pd.DataFrame()
    
    df_clientes = df_clientes.copy()
    df_condominios = df_condominios.copy()
    
    # Garantir tipos corretos
    df_condominios["ID"] = pd.to_numeric(df_condominios["ID"], errors="coerce").fillna(0).astype(int)
    df_clientes["CONDOMANIO"] = pd.to_numeric(df_clientes["CONDOMANIO"], errors="coerce").fillna(0).astype(int)
    df_condominios["Apartamentos"] = pd.to_numeric(df_condominios["Apartamentos"], errors="coerce").fillna(0).astype(int)
    
    def classificar_status(status):
        if pd.isna(status):
            return "Outros"
        status_lower = str(status).lower().strip()
        if "ativo" in status_lower and "atraso" not in status_lower and "bloqueio" not in status_lower:
            return "Ativo"
        elif "atraso" in status_lower or "financeiro" in status_lower:
            return "Em Atraso"
        elif "bloqueio" in status_lower or "automático" in status_lower or "automatico" in status_lower:
            return "Bloqueio Automático"
        elif "desativado" in status_lower or "cancelado" in status_lower:
            return "Desativado"
        return "Outros"
    
    df_clientes["status_classificacao"] = df_clientes["STATUS ACESSO"].apply(classificar_status)
    
    clientes_agg = df_clientes.groupby("CONDOMANIO").agg(
        total_clientes=("CONDOMANIO", "count"),
        ativos_puros=("status_classificacao", lambda x: (x == "Ativo").sum()),
        em_atraso=("status_classificacao", lambda x: (x == "Em Atraso").sum()),
        bloqueio_automatico=("status_classificacao", lambda x: (x == "Bloqueio Automático").sum()),
        desativados=("status_classificacao", lambda x: (x == "Desativado").sum()),
        outros=("status_classificacao", lambda x: (x == "Outros").sum())
    ).reset_index()
    
    if modo_ativos == "todos_ativos":
        clientes_agg["ativos"] = clientes_agg["ativos_puros"] + clientes_agg["em_atraso"] + clientes_agg["bloqueio_automatico"]
    else:
        clientes_agg["ativos"] = clientes_agg["ativos_puros"]
    
    clientes_agg["total_ocupados"] = clientes_agg["ativos_puros"] + clientes_agg["em_atraso"] + clientes_agg["bloqueio_automatico"]
    
    df_merged = df_condominios[["ID", "Condomínio", "Apartamentos", "Região", "Data cadastro"]].merge(
        clientes_agg, left_on="ID", right_on="CONDOMANIO", how="left"
    )
    
    cols_fill = ["ativos", "ativos_puros", "em_atraso", "bloqueio_automatico", "desativados", "outros", "total_ocupados"]
    for col in cols_fill:
        if col in df_merged.columns:
            df_merged[col] = df_merged[col].fillna(0).astype(int)
    
    apt_safe = df_merged["Apartamentos"].replace(0, np.nan)
    df_merged["percentual_ativos"] = (df_merged["ativos"] / apt_safe * 100).round(2)
    df_merged["total_atrasos"] = df_merged["em_atraso"] + df_merged["bloqueio_automatico"]
    ocupados_safe = df_merged["total_ocupados"].replace(0, np.nan)
    df_merged["percentual_atraso"] = (df_merged["total_atrasos"] / ocupados_safe * 100).round(2).fillna(0)
    df_merged["capacidade_exploracao"] = ((apt_safe - df_merged["total_ocupados"]) / apt_safe * 100).round(2)
    
    dashboard_final = df_merged[[
        "Região", "Condomínio", "Data cadastro", "ativos", "percentual_ativos",
        "total_atrasos", "percentual_atraso", "capacidade_exploracao",
        "Apartamentos", "desativados", "total_ocupados", "ativos_puros", "em_atraso", "bloqueio_automatico"
    ]].copy()
    
    dashboard_final.columns = [
        "Região", "Condomínio", "Data de Implantação", "Qtd Ativos",
        "% Ativos (Penetração)", "Total Atrasos", "% Atraso",
        "% Capacidade de Exploração", "Total Apartamentos", "Desativados", "Total Ocupados",
        "Ativos Puros", "Em Atraso", "Bloqueio Automático"
    ]
    
    return dashboard_final.sort_values(["Região", "Condomínio"]).reset_index(drop=True)

def calcular_penetracao(df_clientes, df_condominios):
    """Calcula taxa de penetração"""
    df_clientes = df_clientes.copy()
    df_condominios = df_condominios.copy()
    
    df_clientes["CONDOMANIO"] = pd.to_numeric(df_clientes["CONDOMANIO"], errors="coerce").fillna(0).astype(int)
    df_condominios["ID"] = pd.to_numeric(df_condominios["ID"], errors="coerce").fillna(0).astype(int)
    
    ativos = df_clientes[df_clientes["STATUS ACESSO"].str.lower().str.contains("ativo", na=False)]
    clientes_por_cond = ativos.groupby("CONDOMANIO").size().reset_index(name="clientes_ativos")
    
    cols_merge = ["ID", "Condomínio", "Apartamentos", "Região", "Principal Concorrente"]
    cols_existentes = [c for c in cols_merge if c in df_condominios.columns]
    
    df_merged = clientes_por_cond.merge(
        df_condominios[cols_existentes],
        left_on="CONDOMANIO", right_on="ID", how="right"
    )
    
    df_merged["Apartamentos"] = pd.to_numeric(df_merged["Apartamentos"], errors="coerce").fillna(0)
    df_merged["clientes_ativos"] = df_merged["clientes_ativos"].fillna(0)
    df_merged["taxa_penetracao"] = (df_merged["clientes_ativos"] / df_merged["Apartamentos"].replace(0, np.nan) * 100).round(2)
    df_merged["Apartamentos"] = df_merged["Apartamentos"].fillna(0).astype(int)
    
    def classificar_penetracao(taxa):
        if pd.isna(taxa):
            return "Baixa Presença"
        if taxa >= 50:
            return "🟢 Dominado"
        elif taxa >= 25:
            return "🟡 Em Crescimento"
        return "🔴 Baixa Presença"
    
    df_merged["classificacao"] = df_merged["taxa_penetracao"].apply(classificar_penetracao)
    return df_merged.sort_values("taxa_penetracao", ascending=False)

def analisar_inadimplencia(df_clientes, df_condominios):
    """Análise de inadimplência"""
    df_clientes = df_clientes.copy()
    df_condominios = df_condominios.copy()
    
    df_clientes["CONDOMANIO"] = pd.to_numeric(df_clientes["CONDOMANIO"], errors="coerce").fillna(0).astype(int)
    df_condominios["ID"] = pd.to_numeric(df_condominios["ID"], errors="coerce").fillna(0).astype(int)
    
    df_clientes["atraso_bin"] = df_clientes["FINANCEIRO EM ATRASO"].apply(
        lambda x: "Em Atraso" if pd.notna(x) and str(x).strip().lower() not in 
        ["00/00/0000", "  ", "0", "nan", "nat"] else "Em Dia"
    )
    
    inadimplencia = df_clientes.groupby(["CONDOMANIO", "atraso_bin"]).size().unstack(fill_value=0)
    
    if "Em Atraso" in inadimplencia.columns and "Em Dia" in inadimplencia.columns:
        inadimplencia["taxa_inadimplencia"] = (inadimplencia["Em Atraso"] / 
            (inadimplencia["Em Atraso"] + inadimplencia["Em Dia"]) * 100).round(2)
    elif "Em Atraso" in inadimplencia.columns:
        inadimplencia["taxa_inadimplencia"] = 100.0
    else:
        inadimplencia["taxa_inadimplencia"] = 0.0
    
    cols_merge = ["ID", "Condomínio", "Região"]
    cols_existentes = [c for c in cols_merge if c in df_condominios.columns]
    
    result = inadimplencia.reset_index().merge(
        df_condominios[cols_existentes], 
        left_on="CONDOMANIO", right_on="ID", how="right"
    )
    result["taxa_inadimplencia"] = result["taxa_inadimplencia"].fillna(0)
    return result.sort_values("taxa_inadimplencia", ascending=False)

# ==================== INTERFACE DE UPLOAD ====================
def upload_mode(db):
    """Modo de upload com interface melhorada"""
    subtitulo("📤 Upload de Nova Planilha de Condomínios")
    
    st.markdown("""
    <div style="background-color:#f8f9fa; padding:15px; border-radius:10px; margin-bottom:20px;">
    <strong>📋 Instruções:</strong>
    <ul>
        <li>A planilha deve conter <strong>2 abas</strong>: <code>Dados</code> (clientes) e <code>Condominios</code></li>
        <li>Colunas obrigatórias em <code>Dados</code>: <code>CONDOMANIO</code>, <code>STATUS ACESSO</code>, <code>FINANCEIRO EM ATRASO</code></li>
        <li>Colunas obrigatórias em <code>Condominios</code>: <code>ID</code>, <code>Condomínio</code>, <code>Apartamentos</code>, <code>Região</code></li>
    </ul>
    </div>
    """, unsafe_allow_html=True)
    
    uploaded_file = st.file_uploader(
        "📂 Carregue sua planilha de condomínios (Excel)",
        type=["xlsx", "xls"],
        key="condominios_file_uploader"
    )
    
    if uploaded_file is not None:
        # Preview da planilha
        with st.expander("👁️ Visualizar planilha antes de processar"):
            try:
                df_preview_dados = pd.read_excel(uploaded_file, sheet_name="Dados", nrows=5)
                df_preview_cond = pd.read_excel(uploaded_file, sheet_name="Condominios", nrows=5)
                
                st.markdown("**Aba Dados (primeiras 5 linhas):**")
                st.dataframe(df_preview_dados, use_container_width=True)
                st.markdown("**Aba Condominios (primeiras 5 linhas):**")
                st.dataframe(df_preview_cond, use_container_width=True)
            except Exception as e:
                st.warning(f"Não foi possível visualizar: {e}")
        
        col1, col2 = st.columns([1, 3])
        with col1:
            if st.button("🚀 Processar e Salvar", type="primary", key="processar_upload_condominios"):
                processar_upload_condominios(db, uploaded_file)

# ==================== INTERFACE DE DADOS EXISTENTES ====================
def dados_existentes_mode(db):
    """Exibe lista de arquivos com opção de exclusão"""
    subtitulo("📁 Dados Já Importados")
    
    try:
        # Buscar metadados únicos por batch
        arquivos_cursor = db["condominios_meta"].find(
            {'module': 'condominios'}
        ).sort('timestamp', -1).limit(50)
        
        arquivos = list(arquivos_cursor)
        
        if not arquivos:
            st.info("📭 Nenhum dado encontrado no banco.")
            return
        
        st.markdown("### 📋 Arquivos Disponíveis")
        st.write("Clique em 📂 para carregar ou 🗑️ para excluir.")
        
        for arq in arquivos:
            nome = arq.get('filename', 'Arquivo sem nome')
            data = arq.get('timestamp')
            data_str = data.strftime('%d/%m/%Y %H:%M') if data else 'Data desconhecida'
            total_clientes = arq.get('total_clientes', 0)
            total_cond = arq.get('total_condominios', 0)
            display = f"📄 {nome} - {data_str} ({total_clientes} clientes, {total_cond} condomínios)"
            
            col1, col2, col3 = st.columns([7, 1, 1])
            with col1:
                st.markdown(f"<div style='padding:5px; border-bottom:1px solid #eee;'>{display}</div>", unsafe_allow_html=True)
            with col2:
                if st.button("📂", key=f"carregar_{arq['batch_id']}", help="Carregar estes dados"):
                    with st.spinner("🔄 Carregando dados..."):
                        cursor = db["condominios_relatorios"].find({
                            "_import_batch": arq['batch_id'],
                            "module": "condominios"
                        })
                        df_clientes = pd.DataFrame(list(cursor))
                        
                        for col in ['_id', '_import_timestamp', '_import_batch', 'source_file_id', 'module']:
                            if col in df_clientes.columns:
                                df_clientes = df_clientes.drop(columns=[col])
                        
                        df_condominios = pd.DataFrame(arq.get("condominios", []))
                        
                        df_clientes = converter_dataframe_dates(df_clientes)
                        df_condominios = converter_dataframe_dates(df_condominios)
                        
                        st.session_state.condominios_dados_clientes = df_clientes
                        st.session_state.condominios_dados_condominios = df_condominios
                        st.session_state.condominios_meta = arq
                        st.session_state.condominios_file_id = arq.get('source_file_id')
                        st.session_state.condominios_nome_arquivo = nome
                        st.session_state.condominios_processado = True
                    
                    st.success(f"✅ Dados carregados: {len(df_clientes)} clientes")
                    st.rerun()
            with col3:
                if st.button("🗑️", key=f"excluir_{arq['batch_id']}", help="Excluir este arquivo"):
                    st.session_state.exclusao_confirmada = True
                    st.session_state.batch_id_a_excluir = arq['batch_id']
                    st.session_state.colecao_a_excluir = 'condominios_relatorios'
                    st.rerun()
                    
    except Exception as e:
        st.error(f"❌ Erro ao listar arquivos: {str(e)}")

def confirmar_exclusao(db, batch_id):
    """Confirmação de exclusão com senha"""
    with st.expander("🔐 Confirmação de Exclusão", expanded=True):
        st.markdown("""
        <div style="background-color:#fff3cd; padding:15px; border-radius:10px; margin-bottom:20px;">
        <strong>⚠️ Atenção!</strong> Você está prestes a excluir permanentemente estes dados.<br>
        Esta ação <strong>não pode ser desfeita</strong>.
        </div>
        """, unsafe_allow_html=True)
        
        senha = st.text_input("Digite a senha de administração:", type="password", key="senha_exclusao_condominios")
        
        col1, col2 = st.columns([1, 1])
        with col1:
            if st.button("❌ Cancelar", key="cancelar_exclusao_condominios"):
                st.session_state.exclusao_confirmada = False
                st.rerun()
        with col2:
            if st.button("✅ Confirmar Exclusão", key="confirmar_exclusao_condominios", type="primary"):
                if senha == "3540170":
                    try:
                        total = clear_condominio_data(db, batch_id, "condominios")
                        
                        if total > 0:
                            st.success(f"✅ {total} registros excluídos com sucesso!")
                            # Limpar session_state se os dados excluídos forem os atuais
                            if st.session_state.condominios_meta and st.session_state.condominios_meta.get('batch_id') == batch_id:
                                st.session_state.condominios_dados_clientes = None
                                st.session_state.condominios_dados_condominios = None
                                st.session_state.condominios_processado = False
                            
                            st.session_state.exclusao_confirmada = False
                            st.rerun()
                        else:
                            st.warning("⚠️ Nenhum registro foi removido.")
                    except Exception as e:
                        st.error(f"❌ Erro ao excluir: {str(e)}")
                else:
                    st.error("❌ Senha incorreta")

# ==================== DASHBOARD PRINCIPAL ====================
def exibir_dashboard_principal():
    """Exibe o dashboard principal com os dados carregados"""
    subtitulo("📊 Dashboard de Condomínios")
    
    df_clientes = st.session_state.condominios_dados_clientes
    df_condominios = st.session_state.condominios_dados_condominios
    meta = st.session_state.condominios_meta
    
    if df_clientes is None or df_condominios is None:
        st.warning("⚠️ Nenhum dado carregado. Faça upload ou selecione dados existentes.")
        return
    
    # Exibir informações da importação
    if meta:
        ts = meta.get('timestamp')
        ts_str = safe_strftime(ts, "%d/%m/%Y %H:%M") if ts else "Data não disponível"
        st.info(f"""
        **📋 Última Importação:**
        - 📅 {ts_str}
        - 📄 {meta.get('filename', 'Arquivo desconhecido')}
        - 👥 {meta.get('total_clientes', 0)} clientes
        - 🏢 {meta.get('total_condominios', 0)} condomínios
        """)
    
    st.markdown("---")
    
    # Configuração do modo de ativos
    st.markdown("""
    <div style="background-color:#e8f4f8; padding:10px; border-radius:5px; margin-bottom:15px;">
    <strong>📋 Como os "Ativos" são calculados:</strong><br>
    Por padrão, "Ativos" = apenas clientes com status "Ativo" (sem atraso, sem bloqueio).<br>
    Use o toggle abaixo para alterar o modo de cálculo.
    </div>
    """, unsafe_allow_html=True)
    
    col_modo1, col_modo2 = st.columns([1, 3])
    with col_modo1:
        modo_ativos_toggle = st.toggle(
            "Considerar 'Financeiro em Atraso' e 'Bloqueio Automático' como Ativos",
            value=False,
            key="modo_ativos_toggle",
            help="Quando ligado: Ativos incluem também clientes em atraso e bloqueados"
        )
    
    modo_param = "todos_ativos" if modo_ativos_toggle else "somente_ativos"
    
    with col_modo2:
        if modo_ativos_toggle:
            st.success("✅ Modo atual: **Todos os Ocupados** = Ativos + Em Atraso + Bloqueio Automático")
        else:
            st.warning("⚠️ Modo atual: **Somente Ativos Limpos** = Apenas status 'Ativo' puro")
    
    st.markdown("---")
    
    # Gerar dashboard
    dashboard_df = gerar_dashboard_principal(df_clientes, df_condominios, modo_param)
    
    if not dashboard_df.empty:
        # Métricas principais
        col1, col2, col3, col4 = st.columns(4)
        total_ativos = dashboard_df["Qtd Ativos"].sum()
        total_atrasos = dashboard_df["Total Atrasos"].sum()
        total_apartamentos = dashboard_df["Total Apartamentos"].sum()
        media_penetracao = dashboard_df["% Ativos (Penetração)"].mean()
        
        col1.metric("👥 Total de Ativos", formatar_numero_br(total_ativos))
        col2.metric("⚠️ Total em Atraso", formatar_numero_br(total_atrasos))
        col3.metric("🏢 Total de Apartamentos", formatar_numero_br(total_apartamentos))
        col4.metric("📈 Penetração Média", f"{media_penetracao:.1f}%")
        
        condos_sem_clientes = len(dashboard_df[dashboard_df["Qtd Ativos"] == 0])
        if condos_sem_clientes > 0:
            st.info(f"📌 **{condos_sem_clientes} condomínios** sem clientes ativos (oportunidades de expansão)")
        
        # Tabela principal
        st.dataframe(
            dashboard_df, 
            use_container_width=True,
            column_config={
                "Data de Implantação": st.column_config.DateColumn(format="DD/MM/YYYY"),
                "% Ativos (Penetração)": st.column_config.ProgressColumn(format="%.1f%%", min_value=0, max_value=100),
                "% Capacidade de Exploração": st.column_config.ProgressColumn(format="%.1f%%", min_value=0, max_value=100),
                "% Atraso": st.column_config.ProgressColumn(format="%.1f%%", min_value=0, max_value=100),
                "Total Apartamentos": st.column_config.NumberColumn(format="%d"),
                "Qtd Ativos": st.column_config.NumberColumn(format="%d"),
                "Total Atrasos": st.column_config.NumberColumn(format="%d"),
            }
        )
        
        # Botão de exportação
        output = io.BytesIO()
        with pd.ExcelWriter(output, engine='openpyxl') as writer:
            dashboard_df.to_excel(writer, sheet_name='Dashboard Principal', index=False)
            df_clientes.to_excel(writer, sheet_name='Dados Clientes', index=False)
            df_condominios.to_excel(writer, sheet_name='Condomínios', index=False)
        output.seek(0)
        
        st.download_button(
            "📥 Exportar Dashboard Completo",
            output,
            f"dashboard_condominios_{datetime.now().strftime('%Y%m%d')}.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            use_container_width=True
        )
    
    # Abas de análise
    st.markdown("---")
    tab1, tab2, tab3 = st.tabs(["🎯 Penetração", "⚠️ Inadimplência", "📈 Análise por Região"])
    
    with tab1:
        st.subheader("🎯 Taxa de Penetração por Condomínio")
        df_penetracao = calcular_penetracao(df_clientes, df_condominios)
        
        if not df_penetracao.empty:
            # Filtros
            col1, col2 = st.columns(2)
            with col1:
                regioes = df_penetracao["Região"].dropna().unique()
                regiao_filter = st.multiselect("Região", list(regioes), key="penetracao_regiao")
            with col2:
                classific_filter = st.multiselect(
                    "Classificação", 
                    ["🟢 Dominado", "🟡 Em Crescimento", "🔴 Baixa Presença"],
                    key="penetracao_classificacao"
                )
            
            df_filtered = df_penetracao.copy()
            if regiao_filter:
                df_filtered = df_filtered[df_filtered["Região"].isin(regiao_filter)]
            if classific_filter:
                df_filtered = df_filtered[df_filtered["classificacao"].isin(classific_filter)]
            
            fig = px.bar(
                df_filtered.head(20), 
                x="taxa_penetracao", 
                y="Condomínio",
                color="classificacao",
                orientation="h",
                title="Top 20 Condomínios por Penetração",
                color_discrete_map={
                    "🟢 Dominado": "#2ecc71",
                    "🟡 Em Crescimento": "#f1c40f",
                    "🔴 Baixa Presença": "#e74c3c"
                }
            )
            st.plotly_chart(fig, use_container_width=True)
            
            with st.expander("📋 Ver Tabela Completa"):
                st.dataframe(
                    df_filtered[["Condomínio", "Região", "Apartamentos", "clientes_ativos", "taxa_penetracao", "classificacao"]],
                    use_container_width=True
                )
    
    with tab2:
        st.subheader("⚠️ Análise de Inadimplência por Condomínio")
        df_inadimplencia = analisar_inadimplencia(df_clientes, df_condominios)
        
        if not df_inadimplencia.empty:
            fig = px.bar(
                df_inadimplencia.head(15),
                x="Condomínio",
                y="taxa_inadimplencia",
                color="taxa_inadimplencia",
                color_continuous_scale="Reds",
                title="Top 15 Condomínios com Maior Taxa de Inadimplência"
            )
            st.plotly_chart(fig, use_container_width=True)
    
    with tab3:
        st.subheader("📈 Análise Consolidada por Região")
        if not dashboard_df.empty and "Região" in dashboard_df.columns:
            zona_stats = dashboard_df.groupby("Região").agg(
                total_condominios=("Condomínio", "count"),
                total_apartamentos=("Total Apartamentos", "sum"),
                total_ativos=("Qtd Ativos", "sum"),
                total_atrasos=("Total Atrasos", "sum"),
                media_penetracao=("% Ativos (Penetração)", "mean")
            ).reset_index()
            
            zona_stats["penetracao_global"] = (zona_stats["total_ativos"] / zona_stats["total_apartamentos"] * 100).round(2)
            
            st.dataframe(zona_stats, use_container_width=True)
            
            fig = px.bar(
                zona_stats,
                x="Região",
                y="total_ativos",
                color="penetracao_global",
                title="Total de Ativos por Região",
                color_continuous_scale="Viridis"
            )
            st.plotly_chart(fig, use_container_width=True)

# ==================== FUNÇÃO PRINCIPAL ====================
def render_relatorios_condominios():
    """Função principal refatorada com padrão do analise_financeira"""
    
    # Inicializar session_state
    initialize_session_state()
    
    # Título
    titulo_principal("🏢 Relatórios Estratégicos - Condomínios")
    st.markdown("Análise de penetração, inadimplência e oportunidades de mercado")
    
    # Conectar ao banco
    db = init_mongo()
    
    if db is None:
        st.error("❌ Não foi possível conectar ao banco de dados")
        return
    else:
        st.success("✅ Database conectado", icon="🔗")
    
    # 🚀 Pré-carregamento automático
    if st.session_state.condominios_dados_clientes is None:
        with st.spinner("🔄 Carregando dados mais recentes..."):
            if carregar_dados_mais_recentes(db):
                st.success("✅ Dados mais recentes carregados automaticamente!")
            else:
                st.info("ℹ️ Nenhum dado encontrado — faça upload de uma planilha.")
    
    # Tabs principais
    tab1, tab2, tab3 = st.tabs(["📤 Upload", "📁 Dados Existentes", "📊 Dashboard"])
    
    with tab1:
        upload_mode(db)
    
    with tab2:
        dados_existentes_mode(db)
    
    with tab3:
        if st.session_state.condominios_processado:
            exibir_dashboard_principal()
        else:
            st.warning("⚠️ Nenhum dado carregado. Faça upload ou selecione dados existentes.")
            if st.button("🔄 Tentar carregar novamente"):
                if carregar_dados_mais_recentes(db):
                    st.success("✅ Dados carregados!")
                    st.rerun()
    
    # Verificar pop-up de exclusão
    if st.session_state.exclusao_confirmada:
        if st.session_state.batch_id_a_excluir:
            confirmar_exclusao(db, st.session_state.batch_id_a_excluir)

# ==================== ENTRY POINT ====================
if __name__ == "__main__":
    render_relatorios_condominios()
