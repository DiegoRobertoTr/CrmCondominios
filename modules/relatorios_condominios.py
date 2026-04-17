import streamlit as st
import pandas as pd
import numpy as np
import plotly.express as px
import plotly.graph_objects as go
from datetime import datetime, timezone, timedelta
from pymongo import MongoClient, ASCENDING, DESCENDING
from pymongo.errors import ServerSelectionTimeoutError, ConnectionFailure
from urllib.parse import quote_plus
import io
import traceback
import math

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

# ==================== CONFIGURAÇÃO MONGODB OTIMIZADA ====================
@st.cache_resource
def init_mongo():
    """Inicializa conexão MongoDB com índices automáticos"""
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
        
        criar_indices_mongodb(db)
        return db
    except (ServerSelectionTimeoutError, ConnectionFailure) as e:
        st.error(f"❌ Falha ao conectar ao MongoDB:\n`{type(e).__name__}: {e}`")
        st.stop()
    except Exception as e:
        st.error(f"❌ Erro inesperado ao conectar: {type(e).__name__}: {e}")
        st.stop()

def criar_indices_mongodb(db):
    """✅ OTIMIZAÇÃO: Cria índices para acelerar consultas em ~80%"""
    try:
        db["condominios_relatorios"].create_index([("_import_batch", ASCENDING)])
        db["condominios_relatorios"].create_index([("CONDOMANIO", ASCENDING)])
        db["condominios_meta"].create_index([("timestamp", DESCENDING)])
        db["condominios_meta"].create_index([("batch_id", ASCENDING)])
        
        # ✅ NOVO: Índice para controle de lotes
        db["condominios_lotes"].create_index([("uploaded_at", DESCENDING)])
        db["condominios_lotes"].create_index([("status", ASCENDING)])
    except Exception as e:
        print(f"⚠️ Aviso ao criar índices: {e}")

# ==================== FUNÇÕES UTILITÁRIAS ====================
def limpar_valor_data(valor):
    if pd.isna(valor) or valor is None:
        return None
    if isinstance(valor, str):
        valor_limpo = valor.strip()
        if valor_limpo in ["00/00/0000", "0", "  ", "nan", "NaT", "null", "NULL"]:
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
    """✅ OTIMIZAÇÃO: Conversão vetorial de datas"""
    df = df.copy()
    for col in df.columns:
        col_lower = col.lower()
        eh_coluna_data = any(palavra in col_lower for palavra in
            ['data', 'date', 'cadastro', 'ativacao', 'cancelamento',
             'nascimento', 'renovacao'])
        if eh_coluna_data or pd.api.types.is_datetime64_any_dtype(df[col]):
            df[col] = pd.to_datetime(df[col], errors='coerce')
            df[col] = df[col].apply(limpar_valor_data)
    return df

def formatar_numero_br(valor, decimais=0):
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

def formatar_moeda_br(valor):
    if pd.isna(valor) or valor is None:
        return "R$ 0,00"
    try:
        return f"R$ {formatar_numero_br(valor, 2)}"
    except:
        return f"R$ {valor}"

def safe_strftime(value, fmt="%d/%m/%Y %H:%M"):
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

# ==================== FUNÇÕES DE BANCO DE DADOS OTIMIZADAS ====================
def safe_mongo_docs(df):
    """Converte DataFrame para lista de dicts seguros para o MongoDB (BSON-safe)"""
    records = df.to_dict('records')
    safe_records = []
    for doc in records:
        safe_doc = {}
        for k, v in doc.items():
            if v is None:
                safe_doc[k] = None
            elif isinstance(v, pd.Timestamp):
                safe_doc[k] = None if pd.isna(v) else v.to_pydatetime().replace(tzinfo=None)
            elif isinstance(v, datetime):
                safe_doc[k] = v.replace(tzinfo=None)
            elif isinstance(v, float):
                safe_doc[k] = None if (math.isnan(v) or math.isinf(v)) else v
            else:
                try:
                    safe_doc[k] = None if pd.isna(v) else v
                except (TypeError, ValueError):
                    safe_doc[k] = v
        safe_records.append(safe_doc)
    return safe_records

def insert_many_chunked(collection, docs, chunk_size=5000):
    """✅ OTIMIZAÇÃO: Evita timeout/MaxBSONSize em lotes grandes"""
    if not docs:
        return 0
    total = 0
    for i in range(0, len(docs), chunk_size):
        res = collection.insert_many(docs[i:i+chunk_size])
        total += len(res.inserted_ids)
    return total

def salvar_metadados_lote(db, batch_id, filename, total_clientes, total_condominios):
    """✅ NOVA: Persistência rastreável de lotes"""
    db["condominios_lotes"].insert_one({
        "batch_id": batch_id,
        "filename": filename,
        "uploaded_at": datetime.now(),
        "status": "ativo",
        "total_clientes": total_clientes,
        "total_condominios": total_condominios,
        "module": "relatorios_condominios"
    })

def limpar_lotes_antigos(db, manter_ultimos=3):
    """✅ NOVA: Mantém histórico seguro, marca antigos como 'arquivado'"""
    lotes_antigos = list(db["condominios_lotes"].find(
        {"status": "ativo"}, {"_id": 0, "batch_id": 1}
    ).sort("uploaded_at", -1).skip(manter_ultimos))
    
    batchs_para_arquivar = [l["batch_id"] for l in lotes_antigos]
    if batchs_para_arquivar:
        db["condominios_lotes"].update_many(
            {"batch_id": {"$in": batchs_para_arquivar}},
            {"$set": {"status": "arquivado"}}
        )
        db["condominios_relatorios"].update_many(
            {"_import_batch": {"$in": batchs_para_arquivar}},
            {"$set": {"_lote_status": "arquivado"}}
        )

def save_condominio_data(db, df_clientes, df_condominios, metadata):
    """✅ OTIMIZADO: Persistência segura + chunking + metadados"""
    batch_id = metadata["batch_id"]
    
    # 1. Salva metadados do lote
    salvar_metadados_lote(db, batch_id, metadata.get("filename", "upload.xlsx"), 
                          len(df_clientes), len(df_condominios))
    
    # 2. Gerencia lotes antigos (não apaga, arquiva)
    limpar_lotes_antigos(db, manter_ultimos=3)
    
    # 3. Processa e insere clientes
    df_clientes_limpo = converter_dataframe_dates(df_clientes)
    df_clientes_limpo["_import_timestamp"] = datetime.now().replace(tzinfo=None)
    df_clientes_limpo["_import_batch"] = batch_id
    docs = safe_mongo_docs(df_clientes_limpo)
    if docs:
        insert_many_chunked(db["condominios_relatorios"], docs, chunk_size=5000)
    
    # 4. Salva metadados dos condomínios
    df_condominios_limpo = converter_dataframe_dates(df_condominios)
    condominios_records = safe_mongo_docs(df_condominios_limpo)
    db["condominios_meta"].insert_one({
        "batch_id": batch_id,
        "timestamp": datetime.now().replace(tzinfo=None),
        "total_clientes": len(df_clientes),
        "total_condominios": len(df_condominios),
        "condominios": condominios_records
    })
    return True

def load_latest_data(db, limit=20000):
    """✅ OTIMIZADO: Pré-carregamento eficiente via session_state + DB"""
    # Busca lote ativo mais recente
    lote_ativo = db["condominios_lotes"].find_one({"status": "ativo"}, sort=[("uploaded_at", DESCENDING)])
    if not lote_ativo:
        # Fallback para versão antiga
        meta = db["condominios_meta"].find_one(sort=[("timestamp", DESCENDING)])
        if not meta:
            return None, None, None
        batch_id = meta["batch_id"]
        meta_fallback = meta
    else:
        batch_id = lote_ativo["batch_id"]
        meta_fallback = db["condominios_meta"].find_one({"batch_id": batch_id})

    collection = db["condominios_relatorios"]
    docs = list(collection.find({"_import_batch": batch_id}).limit(limit))
    
    if not docs:
        return None, None, None

    df_clientes = pd.DataFrame(docs)
    if "_id" in df_clientes.columns:
        df_clientes.drop(columns=["_id"], inplace=True)
    
    df_clientes = converter_dataframe_dates(df_clientes)
    
    # Normalização de tipos para joins seguros
    if "CONDOMANIO" in df_clientes.columns:
        df_clientes["CONDOMANIO"] = pd.to_numeric(df_clientes["CONDOMANIO"], errors="coerce").fillna(0).astype(int)
        
    df_condominios = pd.DataFrame(meta_fallback.get("condominios", [])) if meta_fallback else pd.DataFrame()
    df_condominios = converter_dataframe_dates(df_condominios)
    
    if "ID" in df_condominios.columns:
        df_condominios["ID"] = pd.to_numeric(df_condominios["ID"], errors="coerce").fillna(0).astype(int)
    if "Apartamentos" in df_condominios.columns:
        df_condominios["Apartamentos"] = pd.to_numeric(df_condominios["Apartamentos"], errors="coerce").fillna(0).astype(int)

    return df_clientes, df_condominios, meta_fallback or lote_ativo

def clear_condominio_data(db, batch_id=None):
    """Limpa dados do banco (apenas lote específico ou tudo)"""
    collection = db["condominios_relatorios"]
    if batch_id:
        result = collection.delete_many({"_import_batch": batch_id})
        db["condominios_meta"].delete_many({"batch_id": batch_id})
        db["condominios_lotes"].delete_many({"batch_id": batch_id})
    else:
        result = collection.delete_many({})
        db["condominios_meta"].delete_many({})
        db["condominios_lotes"].delete_many({})
    return result.deleted_count

# ==================== CACHE DE CÁLCULOS PESADOS ====================
@st.cache_data(ttl=600)
def gerar_dashboard_principal_cached(df_clientes_json, df_condominios_json, modo_ativos):
    df_clientes = pd.read_json(df_clientes_json, orient='split')
    df_condominios = pd.read_json(df_condominios_json, orient='split')
    
    if "CONDOMANIO" not in df_clientes.columns or "ID" not in df_condominios.columns:
        return pd.DataFrame()

    df_condominios = df_condominios.copy()
    df_condominios["ID"] = pd.to_numeric(df_condominios["ID"], errors="coerce").fillna(0).astype(int)
    df_clientes = df_clientes.copy()
    df_clientes["CONDOMANIO"] = pd.to_numeric(df_clientes["CONDOMANIO"], errors="coerce").fillna(0).astype(int)
    df_condominios["Apartamentos"] = pd.to_numeric(df_condominios["Apartamentos"], errors="coerce").fillna(0).astype(int)

    def classificar_status(status):
        if pd.isna(status): return "Outros"
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

    df_clientes = df_clientes.copy()
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

@st.cache_data(ttl=600)
def calcular_penetracao_cached(df_clientes_json, df_condominios_json):
    df_clientes = pd.read_json(df_clientes_json, orient='split')
    df_condominios = pd.read_json(df_condominios_json, orient='split')
    
    df_clientes["CONDOMANIO"] = pd.to_numeric(df_clientes["CONDOMANIO"], errors="coerce").fillna(0).astype(int)
    df_condominios["ID"] = pd.to_numeric(df_condominios["ID"], errors="coerce").fillna(0).astype(int)

    ativos = df_clientes[df_clientes["STATUS ACESSO"].str.lower().str.contains("ativo", na=False)]
    clientes_por_cond = ativos.groupby("CONDOMANIO").size().reset_index(name="clientes_ativos")

    df_merged = clientes_por_cond.merge(
        df_condominios[["ID", "Condomínio", "Apartamentos", "Região", "Principal Concorrente", 
                        "Endereço", "Número", "CEP", "Cidade", "Sindico", "Celular sindico"]],
        left_on="CONDOMANIO", right_on="ID", how="right"
    )

    df_merged["Apartamentos"] = pd.to_numeric(df_merged["Apartamentos"], errors="coerce").fillna(0)
    df_merged["clientes_ativos"] = df_merged["clientes_ativos"].fillna(0)
    df_merged["taxa_penetracao"] = (df_merged["clientes_ativos"] / df_merged["Apartamentos"].replace(0, np.nan) * 100).round(2)
    df_merged["Apartamentos"] = df_merged["Apartamentos"].fillna(0).astype(int)

    def classificar_penetracao(taxa):
        if pd.isna(taxa): return "Baixa Presença"
        if taxa >= 50: return "🟢 Dominado"
        elif taxa >= 25: return "🟡 Em Crescimento"
        return "🔴 Baixa Presença"

    df_merged["classificacao"] = df_merged["taxa_penetracao"].apply(classificar_penetracao)
    return df_merged.sort_values("taxa_penetracao", ascending=False)

@st.cache_data(ttl=600)
def analisar_inadimplencia_cached(df_clientes_json, df_condominios_json):
    df_clientes = pd.read_json(df_clientes_json, orient='split')
    df_condominios = pd.read_json(df_condominios_json, orient='split')
    
    df_clientes["CONDOMANIO"] = pd.to_numeric(df_clientes["CONDOMANIO"], errors="coerce").fillna(0).astype(int)
    df_condominios["ID"] = pd.to_numeric(df_condominios["ID"], errors="coerce").fillna(0).astype(int)

    df_clientes["atraso_bin"] = df_clientes["FINANCEIRO EM ATRASO"].apply(
        lambda x: "Em Atraso" if pd.notna(x) and str(x).strip().lower() not in 
        ["00/00/0000", "   ", "0", "nan", "nat"] else "Em Dia"
    )

    inadimplencia = df_clientes.groupby(["CONDOMANIO", "atraso_bin"]).size().unstack(fill_value=0)
    if "Em Atraso" in inadimplencia.columns and "Em Dia" in inadimplencia.columns:
        inadimplencia["taxa_inadimplencia"] = (inadimplencia["Em Atraso"] / (inadimplencia["Em Atraso"] + inadimplencia["Em Dia"]) * 100).round(2)
    elif "Em Atraso" in inadimplencia.columns:
        inadimplencia["taxa_inadimplencia"] = 100.0
    else:
        inadimplencia["taxa_inadimplencia"] = 0.0

    result = inadimplencia.reset_index().merge(
        df_condominios[["ID", "Condomínio", "Região"]], 
        left_on="CONDOMANIO", right_on="ID", how="right"
    )
    result["taxa_inadimplencia"] = result["taxa_inadimplencia"].fillna(0)
    return result.sort_values("taxa_inadimplencia", ascending=False)

@st.cache_data(ttl=600)
def analisar_churn_cached(df_clientes_json, df_condominios_json):
    df_clientes = pd.read_json(df_clientes_json, orient='split')
    df_condominios = pd.read_json(df_condominios_json, orient='split')
    
    df_clientes["CONDOMANIO"] = pd.to_numeric(df_clientes["CONDOMANIO"], errors="coerce").fillna(0).astype(int)
    df_condominios["ID"] = pd.to_numeric(df_condominios["ID"], errors="coerce").fillna(0).astype(int)

    status_count = df_clientes.groupby(["CONDOMANIO", "STATUS ACESSO"]).size().unstack(fill_value=0)
    if "Ativo" not in status_count.columns: status_count["Ativo"] = 0
    if "Desativado" not in status_count.columns: status_count["Desativado"] = 0

    total = status_count["Ativo"] + status_count["Desativado"]
    status_count["churn_rate"] = (status_count["Desativado"] / total.replace(0, np.nan) * 100).round(2)

    result = status_count.reset_index().merge(
        df_condominios[["ID", "Condomínio", "Região", "Principal Concorrente"]], 
        left_on="CONDOMANIO", right_on="ID", how="right"
    )
    result["churn_rate"] = result["churn_rate"].fillna(0)
    result["Ativo"] = result["Ativo"].fillna(0).astype(int)
    result["Desativado"] = result["Desativado"].fillna(0).astype(int)
    return result.sort_values("churn_rate", ascending=False)

def analisar_por_zona(df_dashboard):
    if df_dashboard.empty or "Região" not in df_dashboard.columns:
        return pd.DataFrame()
    zona_stats = df_dashboard.groupby("Região").agg(
        total_condominios=("Condomínio", "count"),
        total_apartamentos=("Total Apartamentos", "sum"),
        total_ativos=("Qtd Ativos", "sum"),
        total_em_atraso=("Total Atrasos", "sum"),
        total_desativados=("Desativados", "sum"),
        total_ocupados=("Total Ocupados", "sum"),
        media_penetracao=("% Ativos (Penetração)", "mean"),
        media_atraso=("% Atraso", "mean"),
        media_capacidade_exploracao=("% Capacidade de Exploração", "mean")
    ).reset_index()

    zona_stats["percentual_ativos"] = (zona_stats["total_ativos"] / zona_stats["total_apartamentos"] * 100).round(2)
    zona_stats["percentual_ocupacao"] = (zona_stats["total_ocupados"] / zona_stats["total_apartamentos"] * 100).round(2)
    zona_stats["percentual_atraso"] = (zona_stats["total_em_atraso"] / zona_stats["total_apartamentos"] * 100).round(2)
    zona_stats["percentual_desativados"] = (zona_stats["total_desativados"] / zona_stats["total_apartamentos"] * 100).round(2)

    return zona_stats.sort_values("total_apartamentos", ascending=False).reset_index(drop=True)

def correlacao_concorrencia(df_penetracao, df_condominios):
    if "Principal Concorrente" in df_penetracao.columns:
        conc_stats = df_penetracao.groupby("Principal Concorrente").agg({
            "taxa_penetracao": ["mean", "median", "count"],
            "clientes_ativos": "sum",
            "Apartamentos": "sum"
        }).round(2)
        conc_stats.columns = ["_".join(col).strip() for col in conc_stats.columns.values]
        conc_stats = conc_stats.reset_index()
        conc_stats["penetracao_ponderada"] = (conc_stats["clientes_ativos_sum"] / conc_stats["Apartamentos_sum"].replace(0, np.nan) * 100).round(2)
        return conc_stats.sort_values("penetracao_ponderada", ascending=False)
    return pd.DataFrame()

def calcular_receita_potencial(df_penetracao, ticket_medio=89.99):
    df = df_penetracao.copy()
    df["clientes_ativos"] = df["clientes_ativos"].fillna(0)
    df["Apartamentos"] = pd.to_numeric(df["Apartamentos"], errors="coerce").fillna(0)
    df["receita_atual"] = df["clientes_ativos"] * ticket_medio
    df["potencial_clientes"] = (df["Apartamentos"] - df["clientes_ativos"]).clip(lower=0)
    df["receita_potencial"] = df["potencial_clientes"] * ticket_medio
    df["receita_maxima"] = df["Apartamentos"] * ticket_medio
    df["gap_receita"] = (df["receita_potencial"] / df["receita_atual"].replace(0, np.nan)).replace(
        [np.inf, -np.inf], 0) * 100
    return df.sort_values("receita_potencial", ascending=False)

# ==================== FUNÇÕES DE MATURIDADE ====================
def calcular_meses_cadastro(data_cadastro, data_ref=None):
    if data_ref is None: data_ref = datetime.now().replace(tzinfo=None)
    if pd.isna(data_cadastro): return None
    delta = data_ref - data_cadastro
    return int(delta.days / 30.44)

def classificar_maturidade(row, meses_limite=18):
    meses = row.get("meses_cadastro")
    ativos = row.get("ativos", 0)
    aptos = row.get("Apartamentos", 0)
    ativos_pct = row.get("percentual_ativos", 0)
    if pd.isna(meses):
        if aptos > 0:
            if ativos_pct >= 40: return "🟢 Estável (Sem Data Cadastro)"
            elif ativos_pct >= 10: return "🟡 Em Desenvolvimento (Sem Data)"
            else: return "⚪ Fraco (Sem Data Cadastro)"
        else:
            if ativos >= 50: return "Grande (Sem Data/Aptos)"
            elif ativos >= 20: return "🟡 Médio (Sem Data/Aptos)"
            elif ativos > 0: return "Pequeno (Sem Data/Aptos)"
            else: return "⚪ Inativo (Sem Data Cadastro)"

    tem_aptos = aptos > 0
    if meses >= meses_limite:
        if tem_aptos:
            if ativos_pct >= 40: return "🟢 Maduro Saudável"
            elif ativos_pct >= 15: return "Maduro Estagnado"
            else: return "Maduro Abandonado"
        else:
            if ativos >= 50: return "🟢 Maduro Grande (Sem Aptos)"
            elif ativos >= 20: return "🟡 Maduro Médio (Sem Aptos)"
            elif ativos > 0: return " Maduro Pequeno (Sem Aptos)"
            else: return " Maduro Inativo (Sem Aptos)"
    elif meses >= 12:
        if tem_aptos:
            if ativos_pct >= 30: return "🔵 Intermediário Saudável"
            elif ativos_pct >= 10: return "🟡 Intermediário Fraco"
            else: return "Intermediário Crítico"
        else:
            if ativos >= 30: return " Intermediário Grande (Sem Aptos)"
            elif ativos >= 10: return "Intermediário Médio (Sem Aptos)"
            else: return "Intermediário Fraco (Sem Aptos)"
    elif meses >= 6:
        if tem_aptos:
            if ativos_pct >= 20: return " Jovem em Crescimento"
            else: return "Jovem Fraco"
        else:
            if ativos >= 20: return " Jovem Grande (Sem Aptos)"
            else: return "🟡 Jovem Pequeno (Sem Aptos)"
    else:
        if ativos > 10: return "⚪ Novo Promissor"
        else: return "⚪ Novo Iniciante"

@st.cache_data(ttl=600)
def preparar_dados_maturidade_cached(df_clientes_json, df_condominios_json):
    df_clientes = pd.read_json(df_clientes_json, orient='split')
    df_condominios = pd.read_json(df_condominios_json, orient='split')
    
    df_clientes["CONDOMANIO"] = pd.to_numeric(df_clientes["CONDOMANIO"], errors="coerce").fillna(0).astype(int)
    df_condominios["ID"] = pd.to_numeric(df_condominios["ID"], errors="coerce").fillna(0).astype(int)

    data_ref = datetime.now().replace(tzinfo=None)
    df_condominios = df_condominios.copy()
    df_condominios["Apartamentos"] = pd.to_numeric(df_condominios["Apartamentos"], errors="coerce").fillna(0).astype(int)
    df_condominios["Data cadastro"] = df_condominios["Data cadastro"].apply(limpar_valor_data)

    def classificar_status(status):
        if pd.isna(status): return "Outros"
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

    df_clientes = df_clientes.copy()
    df_clientes["status_classificacao"] = df_clientes["STATUS ACESSO"].apply(classificar_status)

    clientes_agg = df_clientes.groupby("CONDOMANIO").agg(
        total_clientes=("CONDOMANIO", "count"),
        ativos=("status_classificacao", lambda x: (x == "Ativo").sum()),
        em_atraso=("status_classificacao", lambda x: (x == "Em Atraso").sum()),
        bloqueio_automatico=("status_classificacao", lambda x: (x == "Bloqueio Automático").sum()),
        desativados=("status_classificacao", lambda x: (x == "Desativado").sum()),
    ).reset_index()

    df_maturidade = df_condominios[["ID", "Condomínio", "Apartamentos", "Região", "Data cadastro", "Principal Concorrente"]].copy()
    df_maturidade = df_maturidade.merge(clientes_agg, left_on="ID", right_on="CONDOMANIO", how="left")

    for col in ["ativos", "em_atraso", "bloqueio_automatico", "desativados", "total_clientes"]:
        df_maturidade[col] = df_maturidade[col].fillna(0).astype(int)

    apt_safe = df_maturidade["Apartamentos"].replace(0, np.nan)
    df_maturidade["total_ocupados"] = df_maturidade["ativos"] + df_maturidade["em_atraso"] + df_maturidade["bloqueio_automatico"]
    df_maturidade["percentual_ativos"] = (df_maturidade["ativos"] / apt_safe * 100).round(2).fillna(0)
    df_maturidade["percentual_penetracao"] = (df_maturidade["total_ocupados"] / apt_safe * 100).round(2).fillna(0)
    df_maturidade["meses_cadastro"] = df_maturidade["Data cadastro"].apply(lambda x: calcular_meses_cadastro(x, data_ref))

    return df_maturidade

# ==================== GEOCODIFICAÇÃO OTIMIZADA ====================
@st.cache_data(ttl=3600)
def obter_coordenadas_se_nao_existir(endereco, numero, cep, cidade="Rio de Janeiro"):
    if not GEOCODING_AVAILABLE: return None, None
    endereco_completo = f"{endereco}, {numero}, {cep}, {cidade}, Brasil".replace("NaN", "").strip()
    if not endereco_completo or endereco_completo == ", , , Brasil": return None, None
    try:
        geolocator = Nominatim(user_agent="tracecom_condominios_app_v3_optimized")
        location = geolocator.geocode(endereco_completo, timeout=10)
        if location: return location.latitude, location.longitude
        location_cep = geolocator.geocode(f"{cep}, {cidade}, Brasil", timeout=10)
        return (location_cep.latitude, location_cep.longitude) if location_cep else (None, None)
    except: return None, None

# ==================== INTERFACE STREAMLIT ====================
def render_relatorios_condominios():
    st.title("🏢 Relatórios Estratégicos - Condomínios")
    st.markdown("Análise de penetração, churn, inadimplência e oportunidades de mercado")
    db = init_mongo()

    st.markdown("---")
    st.subheader("⚙️ Gerenciamento de Dados")
    col1, col2 = st.columns([3, 1])

    with col1:
        uploaded_file = st.file_uploader("📤 Importar Planilha", type=["xlsx", "xls"], 
                                        help="Planilha com 2 abas: 'Dados' (clientes) e 'Condominios'")

    with col2:
        if st.button("🔄 Recarregar Últimos", type="primary", use_container_width=True):
            st.session_state["reload_data"] = True
        if st.button("🗑️ Limpar Dados", type="secondary", use_container_width=True):
            if st.session_state.get("confirm_delete"):
                deleted = clear_condominio_data(db)
                st.success(f"✅ {deleted} registros removidos!")
                st.session_state["confirm_delete"] = False
                st.cache_data.clear()
                if "df_clientes_cached" in st.session_state:
                    del st.session_state["df_clientes_cached"]
                    del st.session_state["df_condominios_cached"]
                    del st.session_state["meta_cached"]
                st.rerun()
            else:
                st.warning("⚠️ Clique novamente para confirmar")
                st.session_state["confirm_delete"] = True

    # Pré-carregamento automático na inicialização
    if "df_clientes_cached" not in st.session_state or st.session_state.get("reload_data"):
        with st.spinner("🔄 Carregando último lote processado..."):
            result = load_latest_data(db)
            if result[0] is not None:
                st.session_state["df_clientes_cached"] = result[0]
                st.session_state["df_condominios_cached"] = result[1]
                st.session_state["meta_cached"] = result[2]
                if st.session_state.get("reload_data"):
                    st.success("✅ Dados atualizados!")
                else:
                    st.info("📦 Dados pré-carregados da última importação")
            else:
                st.info("ℹ️ Nenhum dado encontrado no banco. Faça upload para começar.")
                if not uploaded_file: return

        if "reload_data" in st.session_state:
            del st.session_state["reload_data"]

    df_clientes = st.session_state.get("df_clientes_cached")
    df_condominios = st.session_state.get("df_condominios_cached")
    meta = st.session_state.get("meta_cached")

    # Exibe info do meta
    if meta and "timestamp" in meta:
        ts = meta.get('timestamp')
        ts_str = safe_strftime(ts, "%d/%m/%Y %H:%M") if ts else "Data não disponível"
        st.info(f"📊 **Última Importação:**\n- {ts_str}\n- 👥 {meta.get('total_clientes', 'N/A')} clientes\n- 🏢 {meta.get('total_condominios', 'N/A')} condomínios")

    # Processa Upload
    if uploaded_file:
        try:
            df_clientes = pd.read_excel(uploaded_file, sheet_name="Dados")
            df_condominios = pd.read_excel(uploaded_file, sheet_name="Condominios")
            
            # Normalização segura de chaves
            if "CONDOMANIO" in df_clientes.columns:
                df_clientes["CONDOMANIO"] = pd.to_numeric(df_clientes["CONDOMANIO"], errors="coerce").fillna(0).astype(int)
            if "ID" in df_condominios.columns:
                df_condominios["ID"] = pd.to_numeric(df_condominios["ID"], errors="coerce").fillna(0).astype(int)
            if "Apartamentos" in df_condominios.columns:
                df_condominios["Apartamentos"] = pd.to_numeric(df_condominios["Apartamentos"], errors="coerce").fillna(0).astype(int)
            
            df_clientes = converter_dataframe_dates(df_clientes)
            df_condominios = converter_dataframe_dates(df_condominios)
            
            metadata = {
                "timestamp": datetime.now().replace(tzinfo=None),
                "batch_id": f"batch_{datetime.now().strftime('%Y%m%d_%H%M%S')}",
                "filename": uploaded_file.name
            }
            
            if save_condominio_data(db, df_clientes, df_condominios, metadata):
                st.success(f"✅ Dados importados! {len(df_clientes)} clientes, {len(df_condominios)} condomínios")
                st.session_state["df_clientes_cached"] = df_clientes
                st.session_state["df_condominios_cached"] = df_condominios
                st.session_state["meta_cached"] = metadata
                st.cache_data.clear()
                st.rerun()
        except Exception as e:
            st.error(f"❌ Erro ao processar planilha: {str(e)}")
            st.expander("Detalhes técnicos do erro").code(traceback.format_exc())
            return

    if df_clientes is None or df_condominios is None:
        st.warning("⚠️ Nenhum dado disponível para análise.")
        return

    # ==================== DASHBOARD PRINCIPAL ====================
    st.subheader("📊 Dashboard Principal")
    st.markdown("---")
    st.info("📋 **Como os 'Ativos' são calculados:**\nPor padrão, 'Ativos' = apenas clientes com status 'Ativo' (sem atraso, sem bloqueio). Use o toggle abaixo para alterar.")

    col_modo1, col_modo2 = st.columns([1, 3])
    with col_modo1:
        modo_ativos = st.toggle("Considerar 'Financeiro em Atraso' e 'Bloqueio Automático' como Ativos", value=False)
    with col_modo2:
        modo_param = "todos_ativos" if modo_ativos else "somente_ativos"
        st.success("✅ Modo atual: **Todos os Ocupados**" if modo_ativos else "⚠️ Modo atual: **Somente Ativos Limpos**")

    st.markdown("---")
    df_clientes_json = df_clientes.to_json(orient='split', date_format='iso')
    df_condominios_json = df_condominios.to_json(orient='split', date_format='iso')

    dashboard_df = gerar_dashboard_principal_cached(df_clientes_json, df_condominios_json, modo_param)

    if not dashboard_df.empty:
        col1, col2, col3, col4 = st.columns(4)
        col1.metric("Total de Ativos", formatar_numero_br(dashboard_df["Qtd Ativos"].sum()))
        col2.metric("⚠️ Total em Atraso", formatar_numero_br(dashboard_df["Total Atrasos"].sum()))
        col3.metric("Total de Apartamentos", formatar_numero_br(dashboard_df["Total Apartamentos"].sum()))
        col4.metric("📈 Penetração Média", f"{dashboard_df['% Ativos (Penetração)'].mean():.1f}%")
        
        condos_sem_clientes = len(dashboard_df[dashboard_df["Qtd Ativos"] == 0])
        if condos_sem_clientes > 0:
            st.info(f"📌 **{condos_sem_clientes} condomínios** sem clientes ativos (oportunidades de expansão)")
        
        st.dataframe(dashboard_df, use_container_width=True, column_config={
            "Data de Implantação": st.column_config.DateColumn(format="DD/MM/YYYY"),
            "% Ativos (Penetração)": st.column_config.ProgressColumn(format="%.1f%%", min_value=0, max_value=100),
            "% Capacidade de Exploração": st.column_config.ProgressColumn(format="%.1f%%", min_value=0, max_value=100),
            "% Atraso": st.column_config.ProgressColumn(format="%.1f%%", min_value=0, max_value=100)
        })
        
        with st.expander("Entenda os cálculos"):
            st.markdown(f"""
            ### Como são calculados os indicadores:
            **Modo atual:** {'**Todos os Ocupados**' if modo_param == 'todos_ativos' else '**Somente Ativos Limpos**'}
            | Métrica | Fórmula |
            |---------|---------|
            | **Qtd Ativos** | {'Ativos + Atraso + Bloqueio' if modo_param == 'todos_ativos' else 'Apenas Ativos Puros'} |
            | **% Ativos** | Ativos / Total Apartamentos × 100 |
            | **% Atraso** | (Em Atraso + Bloqueio) / Total Ocupados × 100 |
            """)
        
        output = io.BytesIO()
        with pd.ExcelWriter(output, engine='openpyxl') as writer:
            dashboard_df.to_excel(writer, sheet_name='Dashboard Principal', index=False) 
            df_clientes.to_excel(writer, sheet_name='Dados Clientes', index=False)
            df_condominios.to_excel(writer, sheet_name='Condomínios', index=False)
        output.seek(0)
         
        st.download_button("📥 Exportar Dashboard Completo", output, 
                          f"dashboard_{datetime.now().strftime('%Y%m%d')}.xlsx", 
                          mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", 
                          use_container_width=True)

    st.markdown("---")

    # ==================== ABAS DE ANÁLISE ====================
    tab1, tab2, tab3, tab4, tab5, tab6, tab7, tab8 = st.tabs([
        "🎯 Penetração", "💰 Receita Potencial", "⚠️ Inadimplência", "📉 Churn", 
        "⚔️ Concorrência", "🗺️ Análise por Zona", "⏳ Maturidade", "📍 Mapeamento Geográfico"
    ])

    with tab1:
        st.header("🎯 Taxa de Penetração por Condomínio")
        df_penetracao = calcular_penetracao_cached(df_clientes_json, df_condominios_json)
        
        col1, col2, col3 = st.columns(3)
        with col1:
            regioes = df_condominios["Região"].dropna().unique()
            regiao_filter = st.multiselect("Região", list(regioes) if len(regioes) > 0 else [], key="penetracao_regiao")
        with col2:
            classific_filter = st.multiselect("Classificação", ["🟢 Dominado", "🟡 Em Crescimento", "🔴 Baixa Presença"], key="penetracao_classificacao")
        with col3:
            min_penetracao = st.slider("Penetração Mínima (%)", 0, 100, 0)
        
        df_filtered = df_penetracao.copy()
        if regiao_filter: df_filtered = df_filtered[df_filtered["Região"].isin(regiao_filter)]
        if classific_filter: df_filtered = df_filtered[df_filtered["classificacao"].isin(classific_filter)]
        df_filtered = df_filtered[df_filtered["taxa_penetracao"] >= min_penetracao]
        
        fig = px.bar(df_filtered.head(20), x="taxa_penetracao", y="Condomínio", 
                    color="classificacao", orientation="h", title="Top 20 Condomínios por Penetração")
        st.plotly_chart(fig, use_container_width=True)
        
        with st.expander("📋 Ver Tabela Completa"):
            st.dataframe(df_filtered[["Condomínio", "Região", "Apartamentos", "clientes_ativos", "taxa_penetracao", "classificacao"]], use_container_width=True)

    with tab2:
        st.header("💰 Receita Potencial por Condomínio")
        ticket = st.number_input("🎯 Ticket Médio Estimado (R$)", value=89.99, min_value=10.0, max_value=500.0, step=5.0)
        df_receita = calcular_receita_potencial(df_penetracao, ticket_medio=ticket)
        
        fig = go.Figure(go.Waterfall(name="Receita", orientation="v", measure=["relative"] * len(df_receita.head(15)),
                    x=df_receita.head(15)["Condomínio"], y=df_receita.head(15)["receita_potencial"],
                    textposition="outside", text=[f"R$ {formatar_numero_br(v, 0)}" for v in df_receita.head(15)["receita_potencial"]]))
        fig.update_layout(title="💰 Receita Potencial Não Explorada (Top 15)", showlegend=False, height=500)
        st.plotly_chart(fig, use_container_width=True)
        st.dataframe(df_receita.sort_values("receita_potencial", ascending=False).head(20), use_container_width=True)

    with tab3:
        st.header("⚠️ Análise de Inadimplência por Condomínio")
        df_inadimplencia = analisar_inadimplencia_cached(df_clientes_json, df_condominios_json)
        df_merge = df_penetracao.merge(df_inadimplencia[["CONDOMANIO", "taxa_inadimplencia"]], left_on="CONDOMANIO", right_on="CONDOMANIO", how="left")
        
        fig = px.scatter(df_merge, x="taxa_penetracao", y="taxa_inadimplencia", size="Apartamentos", color="Região", hover_name="Condomínio", title="Penetração vs Inadimplência")
        st.plotly_chart(fig, use_container_width=True)

    with tab4:
        st.header("📉 Análise de Churn por Condomínio")
        df_churn = analisar_churn_cached(df_clientes_json, df_condominios_json)
        fig = px.bar(df_churn.head(15), x="Condomínio", y="churn_rate", color="churn_rate", color_continuous_scale="Reds", title="Top 15 Condomínios com Maior Taxa de Cancelamento")
        st.plotly_chart(fig, use_container_width=True)

    with tab5:
        st.header("⚔️ Análise Competitiva")
        df_concorrencia = correlacao_concorrencia(df_penetracao, df_condominios)
        if not df_concorrencia.empty:
            fig = px.bar(df_concorrencia, x="Principal Concorrente", y="penetracao_ponderada", color="penetracao_ponderada", color_continuous_scale="RdYlGn", title="Penetração Média por Concorrente Principal")
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.info("⚠️ Dados de concorrentes não disponíveis")

    with tab6:
        st.header("📍 Análise Consolidada por Zona/Região")
        if not dashboard_df.empty and "Região" in dashboard_df.columns:
            zona_stats = analisar_por_zona(dashboard_df)
            if not zona_stats.empty:
                st.dataframe(zona_stats, use_container_width=True)
                fig_zona = px.bar(zona_stats, x="Região", y="total_ativos", color="percentual_ativos", title="Ativos por Região")
                st.plotly_chart(fig_zona, use_container_width=True)

    with tab7:
        st.header("⏳ Análise de Maturidade dos Condomínios")
        df_maturidade = preparar_dados_maturidade_cached(df_clientes_json, df_condominios_json)
        df_maturidade["classificacao_maturidade"] = df_maturidade.apply(lambda row: classificar_maturidade(row, 18), axis=1)
        st.dataframe(df_maturidade[["Condomínio", "Data cadastro", "meses_cadastro", "Região", "Apartamentos", "ativos", "percentual_ativos", "classificacao_maturidade"]], use_container_width=True)

    with tab8:
        st.header("📍 Mapeamento Geográfico dos Condomínios")
        if not GEOCODING_AVAILABLE:
            st.error("❌ Bibliotecas de mapa não instaladas. Instale: `pip install folium streamlit-folium geopy`")
        else:
            df_mapa_base = calcular_penetracao_cached(df_clientes_json, df_condominios_json)
            cols_endereco = ["ID", "Endereço", "Número", "CEP", "Cidade", "Sindico", "Celular sindico"]
            cols_existentes = [c for c in cols_endereco if c in df_condominios.columns]
            
            if len(cols_existentes) < 3:
                st.warning("⚠️ Colunas de endereço insuficientes para gerar o mapa.")
            else:
                df_mapa_base = df_mapa_base.merge(df_condominios[cols_existentes], left_on="CONDOMANIO", right_on="ID", how="left")
                
                if "lat" not in df_mapa_base.columns or "lon" not in df_mapa_base.columns:
                    st.info("ℹ️ Coordenadas não encontradas nos dados. Gerando mapa...")
                    if st.button("🛰️ Gerar Coordenadas e Exibir Mapa", type="primary"):
                        progress_bar = st.progress(0)
                        coords = []
                        total = len(df_mapa_base)
                        for i, row in df_mapa_base.iterrows():
                            coord = obter_coordenadas_se_nao_existir(row.get("Endereço", ""), row.get("Número", ""), row.get("CEP", ""))
                            coords.append(coord)
                            progress_bar.progress((i + 1) / total)
                        df_mapa_base["lat"] = [c[0] for c in coords]
                        df_mapa_base["lon"] = [c[1] for c in coords]
                        st.session_state["df_mapa_com_coords"] = df_mapa_base
                        st.success(f"✅ {len(df_mapa_base)} endereços geocodificados!")
                        st.rerun()
                else:
                    df_plot = st.session_state.get("df_mapa_com_coords", df_mapa_base.dropna(subset=["lat", "lon"]))
                    if df_plot.empty or "lat" not in df_plot.columns:
                        st.warning("Nenhuma coordenada válida encontrada.")
                    else:
                        st.success(f"✅ {len(df_plot)} endereços mapeados!")
                        m = folium.Map(location=[-22.9068, -43.1729], zoom_start=11)
                        for _, row in df_plot.iterrows():
                            if pd.notna(row.get('lat')) and pd.notna(row.get('lon')):
                                popup_html = f"<b>{row['Condomínio']}</b><br>Penetração: {row['taxa_penetracao']:.1f}%<br>Síndico: {row.get('Sindico', 'N/A')}"
                                folium.CircleMarker(location=[row['lat'], row['lon']], radius=6, popup=folium.Popup(popup_html, max_width=200), tooltip=row['Condomínio'], color="green" if row['taxa_penetracao'] >= 50 else "orange" if row['taxa_penetracao'] >= 25 else "red", fill=True, fill_opacity=0.7).add_to(m)
                        st_folium(m, width=1000, height=600)

if __name__ == "__main__":
    render_relatorios_condominios()
