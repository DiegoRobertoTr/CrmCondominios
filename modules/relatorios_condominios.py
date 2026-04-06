import streamlit as st
import pandas as pd
import numpy as np
import plotly.express as px
import plotly.graph_objects as go
from datetime import datetime, timezone
from pymongo import MongoClient
from pymongo.errors import ServerSelectionTimeoutError, ConnectionFailure
from urllib.parse import quote_plus
import io
import time # Necessário para respeitar limites da API de geocodificação

# --- NOVAS IMPORTAÇÕES PARA O MAPA ---
try:
    import folium
    from streamlit_folium import st_folium
    from geopy.geocoders import Nominatim
    from geopy.exc import GeocoderUnavailable, GeocoderServiceError
    GEOCODING_AVAILABLE = True
except ImportError:
    GEOCODING_AVAILABLE = False

# ==================== FUNÇÕES UTILITÁRIAS PARA DATAS E FORMATAÇÃO ====================
def limpar_valor_data(valor):
    """
    Limpa e converte valores de data, tratando casos especiais como:
    - "00/00/0000" → None
    - NaT → None
    - strings vazias → None
    - pd.Timestamp válido → datetime python
    """
    if pd.isna(valor) or valor is None:
        return None
    # Se for string, verificar valores inválidos
    if isinstance(valor, str):
        valor_limpo = valor.strip()
        if valor_limpo in ["00/00/0000", "0", "", "nan", "NaT", "null", "NULL"]:
            return None
        # Tentar converter string para data
        try:
            valor = pd.to_datetime(valor_limpo, errors='coerce')
            if pd.isna(valor):
                return None
        except:
            return None

    # Se for pd.Timestamp
    if isinstance(valor, pd.Timestamp):
        if pd.isna(valor):
            return None
        # Converter para datetime python sem timezone
        try:
            return valor.to_pydatetime().replace(tzinfo=None)
        except:
            return None

    # Se for datetime python
    if isinstance(valor, datetime):
        # Remover timezone se existir
        if valor.tzinfo is not None:
            try:
                return valor.replace(tzinfo=None)
            except:
                return None
        return valor

    return None

def converter_dataframe_dates(df):
    """Converte todas as colunas de data em um DataFrame, tratando NaT"""
    df = df.copy()
    for col in df.columns:
        # Verificar se coluna parece ser de data pelo nome ou tipo
        col_lower = col.lower()
        eh_coluna_data = any(palavra in col_lower for palavra in ['data', 'date', 'cadastro', 'ativacao', 'cancelamento', 'nascimento', 'renovacao'])
        if eh_coluna_data or pd.api.types.is_datetime64_any_dtype(df[col]):
            # Converter para datetime primeiro
            df[col] = pd.to_datetime(df[col], errors='coerce')
            # Depois limpar NaT e timezones
            df[col] = df[col].apply(lambda x: limpar_valor_data(x))
    return df

# ✅ FUNÇÃO: Formatar números no padrão brasileiro (ponto para milhar, vírgula para decimal)
def formatar_numero_br(valor, decimais=0):
    """
    Formata número no padrão brasileiro:
    - Milhar: ponto (.)
    - Decimal: vírgula (,)
    Ex: 45723 → "45.723"
    Ex: 1234.56 → "1.234,56"
    """
    if pd.isna(valor) or valor is None:
        return "0"
    try:
        numero = float(valor)
        if decimais == 0:
            return f"{int(numero):,}".replace(",", ".")
        else:
            # Formata com vírgula como decimal e ponto como milhar
            formatado = f"{numero:,.{decimais}f}"
            # Troca vírgula por ponto e ponto por vírgula
            formatado = formatado.replace(",", "X").replace(".", ",").replace("X", ".")
            return formatado
    except:
        return str(valor)

# ✅ FUNÇÃO: Formatar moeda brasileira
def formatar_moeda_br(valor):
    """Formata valor como moeda brasileira: R$ 1.234,56"""
    if pd.isna(valor) or valor is None:
        return "R$ 0,00"
    try:
        return f"R$ {formatar_numero_br(valor, 2)}"
    except:
        return f"R$ {valor}"

# ==================== CONFIGURAÇÃO INICIAL ====================
st.set_page_config(page_title="🏢 Relatórios Condomínios", layout="wide")

# ==================== CONFIGURAÇÃO MONGODB ====================
@st.cache_resource
def init_mongo():
    """Conexão segura com MongoDB usando secrets"""
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
        return client[database_name]
    except (ServerSelectionTimeoutError, ConnectionFailure) as e:
        st.error(f"❌ Falha ao conectar ao MongoDB:\n`{type(e).__name__}: {e}`")
        st.stop()
    except Exception as e:
        st.error(f"❌ Erro inesperado ao conectar: {type(e).__name__}: {e}")
        st.stop()

def save_condominio_data(db, df_clientes, df_condominios, metadata):
    """Salva dados com timestamp para versionamento - CORRIGIDO PARA NaT"""
    collection = db["condominios_relatorios"]
    # ✅ CORREÇÃO: Limpar datas antes de converter para dict
    df_clientes_limpo = converter_dataframe_dates(df_clientes)

    docs = []
    for _, row in df_clientes_limpo.iterrows():
        doc = row.to_dict()
        
        # ✅ CORREÇÃO: Garantir que nenhum valor de data cause problemas
        for key, value in list(doc.items()):
            if isinstance(value, (pd.Timestamp, datetime)):
                doc[key] = limpar_valor_data(value)
            elif pd.isna(value):
                doc[key] = None
        
        # ✅ CORREÇÃO: Metadata com datetime seguro
        doc["_import_timestamp"] = datetime.now().replace(tzinfo=None)
        doc["_import_batch"] = metadata["batch_id"]
        docs.append(doc)

    if docs:
        collection.insert_many(docs)

    # ✅ CORREÇÃO: Limpar datas do DataFrame de condomínios também
    df_condominios_limpo = converter_dataframe_dates(df_condominios)

    # Converter condomínios para dict com tratamento de NaT
    condominios_records = []
    for _, row in df_condominios_limpo.iterrows():
        record = row.to_dict()
        for key, value in list(record.items()):
            if isinstance(value, (pd.Timestamp, datetime)):
                record[key] = limpar_valor_data(value)
            elif pd.isna(value):
                 record[key] = None
        condominios_records.append(record)
    
    db["condominios_meta"].insert_one({
         "batch_id": metadata["batch_id"],
         "timestamp": datetime.now().replace(tzinfo=None),  # ✅ Sem timezone
         "total_clientes": len(df_clientes),
         "total_condominios": len(df_condominios),
         "condominios": condominios_records
    })
    return True

def load_latest_data(db):
    """Carrega últimos dados importados - CORRIGIDO PARA NaT"""
    meta = db["condominios_meta"].find_one(sort=[("timestamp", -1)])
    if not meta:
        return None, None, None
    collection = db["condominios_relatorios"]
    df_clientes = pd.DataFrame(list(collection.find({"_import_batch": meta["batch_id"]})))
    if "_id" in df_clientes.columns:
        df_clientes = df_clientes.drop(columns=["_id"])

    # ✅ CORREÇÃO: Converter datas de forma segura
    df_clientes = converter_dataframe_dates(df_clientes)
        
    df_condominios = pd.DataFrame(meta.get("condominios", []))
    df_condominios = converter_dataframe_dates(df_condominios)

    return df_clientes, df_condominios, meta

def clear_condominio_data(db, batch_id=None):
    """Limpa dados"""
    collection = db["condominios_relatorios"]
    if batch_id:
        result = collection.delete_many({"_import_batch": batch_id})
        db["condominios_meta"].delete_many({"batch_id": batch_id})
    else:
        result = collection.delete_many({})
        db["condominios_meta"].delete_many({})
    return result.deleted_count

# ==================== DASHBOARD PRINCIPAL CORRIGIDO ====================
def gerar_dashboard_principal(df_clientes, df_condominios, modo_ativos="somente_ativos"):
    """
    Gera dashboard principal com visão consolidada por condomínio.
    Parâmetros:
    - modo_ativos: "somente_ativos" (padrão) ou "todos_ativos"
        * "somente_ativos": Conta apenas status "Ativo" puro
        * "todos_ativos": Conta Ativo + Em Atraso + Bloqueio Automático como ativos
    """
    if "CONDOMANIO" not in df_clientes.columns:
        st.error("❌ Coluna 'CONDOMANIO' não encontrada na tabela de clientes")
        return pd.DataFrame()
    if "ID" not in df_condominios.columns:
        st.error("❌ Coluna 'ID' não encontrada na tabela de condomínios")
        return pd.DataFrame()

    # ✅ CORREÇÃO CRÍTICA #1: Garantir que Apartamentos é numérico
    df_condominios = df_condominios.copy()
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

    # ✅ Criar resumo de clientes por condomínio PRIMEIRO
    df_clientes = df_clientes.copy()
    df_clientes["status_classificacao"] = df_clientes["STATUS ACESSO"].apply(classificar_status)

    # Agrupa clientes por condomínio
    clientes_agg = df_clientes.groupby("CONDOMANIO").agg(
        total_clientes=("CONDOMANIO", "count"),
        ativos_puros=("status_classificacao", lambda x: (x == "Ativo").sum()),
        em_atraso=("status_classificacao", lambda x: (x == "Em Atraso").sum()),
        bloqueio_automatico=("status_classificacao", lambda x: (x == "Bloqueio Automático").sum()),
        desativados=("status_classificacao", lambda x: (x == "Desativado").sum()),
        outros=("status_classificacao", lambda x: (x == "Outros").sum())
    ).reset_index()

    # ✅ CORREÇÃO: Definir o que conta como "Ativos" baseado no modo
    if modo_ativos == "todos_ativos":
        # Modo "todos ativos": Ativo puro + Em Atraso + Bloqueio Automático
        clientes_agg["ativos"] = clientes_agg["ativos_puros"] + clientes_agg["em_atraso"] + clientes_agg["bloqueio_automatico"]
        clientes_agg["label_ativos"] = "Ativos (inclui atraso/bloqueio)"
    else:
        # Modo padrão: apenas Ativo puro
        clientes_agg["ativos"] = clientes_agg["ativos_puros"]
        clientes_agg["label_ativos"] = "Ativos (somente ativos limpos)"

    # ✅ CORREÇÃO CRÍTICA: Total ocupados = base para cálculo de atraso
    clientes_agg["total_ocupados"] = clientes_agg["ativos_puros"] + clientes_agg["em_atraso"] + clientes_agg["bloqueio_automatico"]

    # ✅ CORREÇÃO CRÍTICA #3: Fazer merge começando pelos condomínios (RIGHT JOIN logic)
    df_merged = df_condominios[["ID", "Condomínio", "Apartamentos", "Região", "Data cadastro"]].merge(
        clientes_agg,
        left_on="ID",
        right_on="CONDOMANIO",
        how="left"  # Mantém todos os condomínios, adiciona clientes onde existir
    )

    # ✅ CORREÇÃO CRÍTICA #4: Preencher NaN com 0 para condomínios sem clientes
    df_merged["ativos"] = df_merged["ativos"].fillna(0).astype(int)
    df_merged["ativos_puros"] = df_merged["ativos_puros"].fillna(0).astype(int)
    df_merged["em_atraso"] = df_merged["em_atraso"].fillna(0).astype(int)
    df_merged["bloqueio_automatico"] = df_merged["bloqueio_automatico"].fillna(0).astype(int)
    df_merged["desativados"] = df_merged["desativados"].fillna(0).astype(int)
    df_merged["outros"] = df_merged["outros"].fillna(0).astype(int)
    df_merged["total_ocupados"] = df_merged["total_ocupados"].fillna(0).astype(int)

    # Cálculos
    apt_safe = df_merged["Apartamentos"].replace(0, np.nan)

    # ✅ Penetração: Ativos / Total Apartamentos
    df_merged["percentual_ativos"] = (df_merged["ativos"] / apt_safe * 100).round(2)

    # ✅ CORREÇÃO CRÍTICA DO CÁLCULO DE ATRASO:
    # Total de atrasos = Em Atraso + Bloqueio Automático
    df_merged["total_atrasos"] = df_merged["em_atraso"] + df_merged["bloqueio_automatico"]

    # ✅ Percentual de Atraso: Atrasos / Total Ocupados (não sobre total apartamentos!)
    # Se não houver ocupados, fica 0%
    ocupados_safe = df_merged["total_ocupados"].replace(0, np.nan)
    df_merged["percentual_atraso"] = (df_merged["total_atrasos"] / ocupados_safe * 100).round(2).fillna(0)

    # Capacidade de exploração: Apartamentos vazios / Total Apartamentos
    df_merged["capacidade_exploracao"] = ((apt_safe - df_merged["total_ocupados"]) / apt_safe * 100).round(2)

    # Seleciona e renomeia colunas
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

# ==================== NOVA FUNÇÃO: ANÁLISE POR ZONA/REGIÃO ====================
def analisar_por_zona(df_dashboard):
    """
    Análise consolidada por Zona/Região
    Retorna métricas agregadas: total apt, ativos, % ativos, etc.
    """
    if df_dashboard.empty or "Região" not in df_dashboard.columns:
        return pd.DataFrame()
    # Agrupar por Região
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

    # Calcular percentuais
    zona_stats["percentual_ativos"] = (zona_stats["total_ativos"] / zona_stats["total_apartamentos"] * 100).round(2)
    zona_stats["percentual_ocupacao"] = (zona_stats["total_ocupados"] / zona_stats["total_apartamentos"] * 100).round(2)
    zona_stats["percentual_atraso"] = (zona_stats["total_em_atraso"] / zona_stats["total_apartamentos"] * 100).round(2)
    zona_stats["percentual_desativados"] = (zona_stats["total_desativados"] / zona_stats["total_apartamentos"] * 100).round(2)

    # Arredondar médias
    zona_stats["media_penetracao"] = zona_stats["media_penetracao"].round(2)
    zona_stats["media_atraso"] = zona_stats["media_atraso"].round(2)
    zona_stats["media_capacidade_exploracao"] = zona_stats["media_capacidade_exploracao"].round(2)

    # Ordenar por total de apartamentos (maior para menor)
    zona_stats = zona_stats.sort_values("total_apartamentos", ascending=False).reset_index(drop=True)

    return zona_stats

def exportar_dashboard_excel(dashboard_df, df_clientes, df_condominios):
    """Exporta dashboard para Excel com múltiplas abas"""
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        dashboard_df.to_excel(writer, sheet_name='Dashboard Principal', index=False)
        df_clientes.to_excel(writer, sheet_name='Dados Clientes', index=False)
        df_condominios.to_excel(writer, sheet_name='Condomínios', index=False)
        workbook = writer.book
        worksheet = writer.sheets['Dashboard Principal']
        column_widths = {'A': 15, 'B': 40, 'C': 20, 'D': 12, 'E': 18, 'F': 14, 'G': 12, 'H': 22, 'I': 18, 'J': 12, 'K': 15}
        for col, width in column_widths.items():
            worksheet.column_dimensions[col].width = width
    output.seek(0)
    return output

# ==================== FUNÇÕES DE ANÁLISE ====================
def calcular_penetracao(df_clientes, df_condominios):
    """Calcula taxa de penetração por condomínio"""
    ativos = df_clientes[df_clientes["STATUS ACESSO"].str.lower().str.contains("ativo", na=False)]
    clientes_por_cond = ativos.groupby("CONDOMANIO").size().reset_index(name="clientes_ativos")
    df_merged = clientes_por_cond.merge(
        df_condominios[["ID", "Condomínio", "Apartamentos", "Região", "Principal Concorrente", "Endereço", "Número", "CEP", "Cidade", "Sindico", "Celular sindico"]],
        left_on="CONDOMANIO", right_on="ID", how="right"  # ✅ CORREÇÃO: right join para incluir todos os condomínios
    )

    df_merged["Apartamentos"] = pd.to_numeric(df_merged["Apartamentos"], errors="coerce").fillna(0)
    df_merged["clientes_ativos"] = df_merged["clientes_ativos"].fillna(0)  # ✅ CORREÇÃO: preencher NaN com 0
    df_merged["taxa_penetracao"] = (df_merged["clientes_ativos"] / df_merged["Apartamentos"].replace(0, np.nan) * 100).round(2)
    df_merged["Apartamentos"] = df_merged["Apartamentos"].fillna(0).astype(int)

    def classificar_penetracao(taxa):
        if pd.isna(taxa): return "🔴 Baixa Presença"
        if taxa >= 50: return " Dominado"
        elif taxa >= 25: return "🟡 Em Crescimento"
        return "🔴 Baixa Presença"
        
    df_merged["classificacao"] = df_merged["taxa_penetracao"].apply(classificar_penetracao)
    return df_merged.sort_values("taxa_penetracao", ascending=False)

def analisar_inadimplencia(df_clientes, df_condominios):
    """Análise de inadimplência por condomínio"""
    df_clientes["atraso_bin"] = df_clientes["FINANCEIRO EM ATRASO"].apply(
        lambda x: "Em Atraso" if pd.notna(x) and str(x).strip().lower() not in ["00/00/0000", " ", "0", "nan", "nat", ""] else "Em Dia"
    )
    inadimplencia = df_clientes.groupby(["CONDOMANIO", "atraso_bin"]).size().unstack(fill_value=0)
    if "Em Atraso" in inadimplencia.columns and "Em Dia" in inadimplencia.columns:
        inadimplencia["taxa_inadimplencia"] = (inadimplencia["Em Atraso"] / (inadimplencia["Em Atraso"] + inadimplencia["Em Dia"]) * 100).round(2)
    elif "Em Atraso" in inadimplencia.columns:
        inadimplencia["taxa_inadimplencia"] = 100.0
    else:
        inadimplencia["taxa_inadimplencia"] = 0.0
        
    result = inadimplencia.reset_index().merge(
        df_condominios[["ID", "Condomínio", "Região"]], left_on="CONDOMANIO", right_on="ID", how="right"  # ✅ CORREÇÃO: right join
    )
    result["taxa_inadimplencia"] = result["taxa_inadimplencia"].fillna(0)  # ✅ CORREÇÃO: preencher NaN
    return result.sort_values("taxa_inadimplencia", ascending=False)

def analisar_churn(df_clientes, df_condominios):
    """Análise de churn/cancelamentos por condomínio"""
    status_count = df_clientes.groupby(["CONDOMANIO", "STATUS ACESSO"]).size().unstack(fill_value=0)
    # ✅ CORREÇÃO: Garantir que as colunas existem
    if "Ativo" not in status_count.columns:
        status_count["Ativo"] = 0
    if "Desativado" not in status_count.columns:
        status_count["Desativado"] = 0
        
    total = status_count["Ativo"] + status_count["Desativado"]
    status_count["churn_rate"] = (status_count["Desativado"] / total.replace(0, np.nan) * 100).round(2)

    result = status_count.reset_index().merge(
        df_condominios[["ID", "Condomínio", "Região", "Principal Concorrente"]], 
        left_on="CONDOMANIO", right_on="ID", how="right"  # ✅ CORREÇÃO: right join
    )
    result["churn_rate"] = result["churn_rate"].fillna(0)  # ✅ CORREÇÃO: preencher NaN
    result["Ativo"] = result["Ativo"].fillna(0).astype(int)
    result["Desativado"] = result["Desativado"].fillna(0).astype(int)
    return result.sort_values("churn_rate", ascending=False)

def correlacao_concorrencia(df_penetracao, df_condominios):
    """Correlaciona penetração com concorrentes principais"""
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
    """Calcula receita atual vs. potencial por condomínio"""
    df = df_penetracao.copy()
    df["clientes_ativos"] = df["clientes_ativos"].fillna(0)
    df["Apartamentos"] = pd.to_numeric(df["Apartamentos"], errors="coerce").fillna(0)
    df["receita_atual"] = df["clientes_ativos"] * ticket_medio
    df["potencial_clientes"] = (df["Apartamentos"] - df["clientes_ativos"]).clip(lower=0)
    df["receita_potencial"] = df["potencial_clientes"] * ticket_medio
    df["receita_maxima"] = df["Apartamentos"] * ticket_medio
    df["gap_receita"] = (df["receita_potencial"] / df["receita_atual"].replace(0, np.nan)).replace([np.inf, -np.inf], 0) * 100
    return df.sort_values("receita_potencial", ascending=False)

def safe_strftime(value, fmt="%d/%m/%Y %H:%M"):
    """Formata datetime com tratamento seguro para NaT/None"""
    if pd.isna(value) or value is None:
        return ""
    if isinstance(value, (pd.Timestamp, datetime)):
        try:
            # ✅ CORREÇÃO: Remover timezone antes de formatar
            if hasattr(value, 'tzinfo') and value.tzinfo is not None:
                value = value.replace(tzinfo=None)
            return value.strftime(fmt)
        except (ValueError, OSError):
            return ""
    return str(value)

# ==================== FUNÇÕES DE MATURIDADE ====================
def calcular_meses_cadastro(data_cadastro, data_ref=None):
    """Calcula meses desde o cadastro até data de referência"""
    if data_ref is None:
        data_ref = datetime.now().replace(tzinfo=None)
    if pd.isna(data_cadastro):
        return None
    delta = data_ref - data_cadastro
    return int(delta.days / 30.44)

def classificar_maturidade(row, meses_limite=18):
    """
    Classifica condomínio por maturidade baseado em tempo e performance.
    """
    meses = row.get("meses_cadastro")
    ativos = row.get("ativos", 0)
    aptos = row.get("Apartamentos", 0)
    ativos_pct = row.get("percentual_ativos", 0)
    # Sem data de cadastro - classificar por performance absoluta
    if pd.isna(meses):
        if aptos > 0:
            if ativos_pct >= 40:
                return "🟢 Estável (Sem Data Cadastro)"
            elif ativos_pct >= 10:
                return "🟡 Em Desenvolvimento (Sem Data)"
            else:
                return "⚪ Fraco (Sem Data Cadastro)"
        else:
            if ativos > 50:
                return "🟢 Grande (Sem Data/Aptos)"
            elif ativos > 20:
                return " Médio (Sem Data/Aptos)"
            elif ativos > 0:
                return "⚪ Pequeno (Sem Data/Aptos)"
            else:
                return " Inativo (Sem Data Cadastro)"

    # Com data de cadastro
    tem_aptos = aptos > 0

    if meses >= meses_limite:  # Maduro (>18 meses)
        if tem_aptos:
            if ativos_pct >= 40:
                return " Maduro Saudável"
            elif ativos_pct >= 15:
                return "🟡 Maduro Estagnado"
            else:
                return "🔴 Maduro Abandonado"
        else:
            if ativos >= 50:
                return "🟢 Maduro Grande (Sem Aptos)"
            elif ativos >= 20:
                return "🟡 Maduro Médio (Sem Aptos)"
            elif ativos > 0:
                return " Maduro Pequeno (Sem Aptos)"
            else:
                return "🔴 Maduro Inativo (Sem Aptos)"

    elif meses >= 12:  # Intermediário (12-18 meses)
        if tem_aptos:
            if ativos_pct >= 30:
                return "🔵 Intermediário Saudável"
            elif ativos_pct >= 10:
                return "🟡 Intermediário Fraco"
            else:
                return " Intermediário Crítico"
        else:
            if ativos >= 30:
                return "🔵 Intermediário Grande (Sem Aptos)"
            elif ativos >= 10:
                return " Intermediário Médio (Sem Aptos)"
            else:
                return "🟠 Intermediário Fraco (Sem Aptos)"

    elif meses >= 6:  # Jovem (6-12 meses)
        if tem_aptos:
            if ativos_pct >= 20:
                return "🔵 Jovem em Crescimento"
            else:
                return "🟡 Jovem Fraco"
        else:
            if ativos >= 20:
                return " Jovem Grande (Sem Aptos)"
            else:
                return "🟡 Jovem Pequeno (Sem Aptos)"

    else:  # Novo (<6 meses)
        if ativos > 10:
            return "⚪ Novo Promissor"
        else:
            return "⚪ Novo Iniciante"

def calcular_receita_perdida_maturidade(row, ticket_medio=89.99):
    """Calcula receita perdida por abandono/má performance"""
    classe = row.get("classificacao_maturidade", "")
    aptos = row.get("Apartamentos", 0)
    ativos = row.get("ativos", 0)
    # Abandono = classes críticas (maduros ou intermediários com baixa performance)
    criticas = ["🔴 Maduro", " Maduro", " Intermediário", "🔴 Intermediário"]
    abandonado = any(x in str(classe) for x in criticas)

    if abandonado:
        if aptos > 0:
            potencial = max(0, aptos - ativos)
        else:
            # Estimar potencial baseado em média de mercado (100 aptos)
            potencial = max(0, 100 - ativos)
        return potencial * ticket_medio
    return 0

def preparar_dados_maturidade(df_clientes, df_condominios, data_ref=None):
    """Prepara DataFrame completo com análise de maturidade"""
    if data_ref is None:
        data_ref = datetime.now().replace(tzinfo=None)
    df_condominios = df_condominios.copy()
    df_condominios["Apartamentos"] = pd.to_numeric(df_condominios["Apartamentos"], errors="coerce").fillna(0).astype(int)
    df_condominios["Data cadastro"] = df_condominios["Data cadastro"].apply(limpar_valor_data)

    # Classificar status dos clientes
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

    df_clientes = df_clientes.copy()
    df_clientes["status_classificacao"] = df_clientes["STATUS ACESSO"].apply(classificar_status)

    # Agregar clientes por condomínio
    clientes_agg = df_clientes.groupby("CONDOMANIO").agg(
        total_clientes=("CONDOMANIO", "count"),
        ativos=("status_classificacao", lambda x: (x == "Ativo").sum()),
        em_atraso=("status_classificacao", lambda x: (x == "Em Atraso").sum()),
        bloqueio_automatico=("status_classificacao", lambda x: (x == "Bloqueio Automático").sum()),
        desativados=("status_classificacao", lambda x: (x == "Desativado").sum()),
    ).reset_index()

    # Merge com condomínios
    df_maturidade = df_condominios[["ID", "Condomínio", "Apartamentos", "Região", "Data cadastro", "Principal Concorrente"]].copy()
    df_maturidade = df_maturidade.merge(clientes_agg, left_on="ID", right_on="CONDOMANIO", how="left")

    for col in ["ativos", "em_atraso", "bloqueio_automatico", "desativados", "total_clientes"]:
        df_maturidade[col] = df_maturidade[col].fillna(0).astype(int)

    # Calcular métricas
    apt_safe = df_maturidade["Apartamentos"].replace(0, np.nan)
    df_maturidade["total_ocupados"] = df_maturidade["ativos"] + df_maturidade["em_atraso"] + df_maturidade["bloqueio_automatico"]
    df_maturidade["percentual_ativos"] = (df_maturidade["ativos"] / apt_safe * 100).round(2).fillna(0)
    df_maturidade["percentual_penetracao"] = (df_maturidade["total_ocupados"] / apt_safe * 100).round(2).fillna(0)
    df_maturidade["meses_cadastro"] = df_maturidade["Data cadastro"].apply(lambda x: calcular_meses_cadastro(x, data_ref))

    return df_maturidade

# ==================== FUNÇÃO DE GEOCODIFICAÇÃO (NOVA) ====================
@st.cache_data(ttl=3600) # Cache por 1 hora para não estourar limite da API gratuita
def obter_coordenadas(endereco, numero, cep, cidade="Rio de Janeiro"):
    """
    Tenta obter lat/lon usando Nominatim (OpenStreetMap).
    Retorna (lat, lon) ou (None, None) se falhar.
    """
    if not GEOCODING_AVAILABLE:
        return None, None
    
    # Constrói o endereço completo
    endereco_completo = f"{endereco}, {numero}, {cep}, {cidade}, Brasil"
    endereco_completo = endereco_completo.replace("NaN", "").strip()
    
    if not endereco_completo or endereco_completo == ", , , Brasil":
        return None, None

    try:
        # Inicializa o geocoder (User-Agent é obrigatório)
        geolocator = Nominatim(user_agent="tracecom_condominios_app_v1")
        # Pequeno delay para ser educado com a API gratuita
        time.sleep(1.0) 
        location = geolocator.geocode(endereco_completo, timeout=10)
        
        if location:
            return location.latitude, location.longitude
        else:
            # Tenta apenas com CEP se o endereço falhar
            location_cep = geolocator.geocode(f"{cep}, {cidade}, Brasil", timeout=10)
            if location_cep:
                return location_cep.latitude, location_cep.longitude
            return None, None
    except (GeocoderUnavailable, GeocoderServiceError, Exception) as e:
        # Silencioso para não poluir o log em loop, mas retorna None
        return None, None

# ==================== INTERFACE STREAMLIT ====================
def render_relatorios_condominios():
    st.title("🏢 Relatórios Estratégicos - Condomínios")
    st.markdown("Análise de penetração, churn, inadimplência e oportunidades de mercado")
    db = init_mongo()
    st.markdown("---")
    st.subheader("️ Gerenciamento de Dados")
    col1, col2 = st.columns([3, 1])

    with col1:
        uploaded_file = st.file_uploader("📤 Importar Planilha", type=["xlsx", "xls"], help="Planilha com 2 abas: 'Dados' (clientes) e 'Condominios'")
    with col2:
        if st.button("🔄 Recarregar Últimos", type="primary", use_container_width=True):
            st.session_state["reload_data"] = True
        if st.button("🗑️ Limpar Dados", type="secondary", use_container_width=True):
            if st.session_state.get("confirm_delete"):
                deleted = clear_condominio_data(db)
                st.success(f"✅ {deleted} registros removidos!")
                st.session_state["confirm_delete"] = False
                st.rerun()
            else:
                st.warning("️ Clique novamente para confirmar")
                st.session_state["confirm_delete"] = True

    meta = db["condominios_meta"].find_one(sort=[("timestamp", -1)])
    if meta:
        ts = meta.get('timestamp')
        ts_str = safe_strftime(ts, "%d/%m/%Y %H:%M") if ts else "Data não disponível"
        st.info(f"""
        **Última Importação:**
        - 📅 {ts_str}
        - 👥 {meta['total_clientes']} clientes
        -  {meta['total_condominios']} condomínios
        """)
    else:
        st.warning("⚠️ Nenhum dado importado ainda")

    st.markdown("---")
    df_clientes, df_condominios, meta = None, None, None

    if uploaded_file:
        try:
            # ✅ CORREÇÃO: Ler planilha com tratamento de datas
            df_clientes = pd.read_excel(uploaded_file, sheet_name="Dados")
            df_condominios = pd.read_excel(uploaded_file, sheet_name="Condominios")
            
            # ✅ CORREÇÃO: Converter Apartamentos para numérico imediatamente
            if "Apartamentos" in df_condominios.columns:
                df_condominios["Apartamentos"] = pd.to_numeric(df_condominios["Apartamentos"], errors="coerce").fillna(0).astype(int)

            # ✅ CORREÇÃO: Limpar datas problematicas (00/00/0000, etc)
            df_clientes = converter_dataframe_dates(df_clientes)
            df_condominios = converter_dataframe_dates(df_condominios)
            
            metadata = {
                 "timestamp": datetime.now().replace(tzinfo=None),  # ✅ Sem timezone
                 "batch_id": f"batch_{datetime.now().strftime('%Y%m%d_%H%M%S')}", 
                 "filename": uploaded_file.name
            }
            if save_condominio_data(db, df_clientes, df_condominios, metadata):
                st.success(f"✅ Dados importados! {len(df_clientes)} clientes, {len(df_condominios)} condomínios")
                st.rerun()
        except Exception as e:
            st.error(f"❌ Erro ao processar planilha: {str(e)}")
            st.code("Verifique se as abas 'Dados' e 'Condominios' existem e têm os cabeçalhos corretos.")
            # ✅ CORREÇÃO: Mostrar traceback para debug
            import traceback
            st.expander("Detalhes técnicos do erro").code(traceback.format_exc())
    elif st.session_state.get("reload_data") or "df_clientes_cached" not in st.session_state:
        result = load_latest_data(db)
        if result[0] is not None:
            df_clientes, df_condominios, meta = result
            # Garantir tipo numérico ao carregar do cache
            if "Apartamentos" in df_condominios.columns:
                df_condominios["Apartamentos"] = pd.to_numeric(df_condominios["Apartamentos"], errors="coerce").fillna(0).astype(int)
                
            st.session_state["df_clientes_cached"] = df_clientes
            st.session_state["df_condominios_cached"] = df_condominios
            st.session_state["meta_cached"] = meta
            st.success(" Dados pré-carregados da última importação")
        else:
            st.info("👆 Faça upload da planilha para começar")
            return
    else:
        df_clientes = st.session_state["df_clientes_cached"]
        df_condominios = st.session_state["df_condominios_cached"]
        meta = st.session_state["meta_cached"]

    if "reload_data" in st.session_state:
        del st.session_state["reload_data"]


    # ==================== DASHBOARD PRINCIPAL ====================
    st.subheader("📊 Dashboard Principal")

    # ✅ AVISO IMPORTANTE E SELEÇÃO DE MODO
    st.markdown("---")

    # Caixa de informação sobre o cálculo de ativos
    st.info("""
    📋 **Como os "Ativos" são calculados:**

    Por padrão, "Ativos" = apenas clientes com status "Ativo" (sem atraso, sem bloqueio).

    Use o toggle abaixo para alterar o modo de cálculo.
    """)

    # Toggle para seleção de modo
    col_modo1, col_modo2 = st.columns([1, 3])
    with col_modo1:
        modo_ativos = st.toggle(
             "Considerar 'Financeiro em Atraso' e 'Bloqueio Automático' como Ativos",
            value=False,  # Desligado por padrão (modo "somente ativos")
            help="Quando ligado: Ativos incluem também clientes em atraso e bloqueados"
        )

    with col_modo2:
        if modo_ativos:
            st.success("✅ Modo atual: **Todos os Ocupados** = Ativos + Em Atraso + Bloqueio Automático")
            modo_param = "todos_ativos"
        else:
            st.warning("⚠️ Modo atual: **Somente Ativos Limpos** = Apenas status 'Ativo' puro (exclui atraso/bloqueio)")
            modo_param = "somente_ativos"

    st.markdown("---")

    # Gerar dashboard com o modo selecionado
    dashboard_df = gerar_dashboard_principal(df_clientes, df_condominios, modo_ativos=modo_param)

    if not dashboard_df.empty:
        col1, col2, col3, col4 = st.columns(4)
        total_ativos = dashboard_df["Qtd Ativos"].sum()
        total_atrasos = dashboard_df["Total Atrasos"].sum()
        total_apartamentos = dashboard_df["Total Apartamentos"].sum()
        total_ocupados = dashboard_df["Total Ocupados"].sum()
        media_penetracao = dashboard_df["% Ativos (Penetração)"].mean()

        # ✅ Alerta se houver discrepância entre modos
        ativos_puros_total = dashboard_df["Ativos Puros"].sum()
        if modo_param == "somente_ativos" and total_ocupados > ativos_puros_total:
            diferenca = total_ocupados - ativos_puros_total
            st.info(f"💡 **Dica:** Existem {formatar_numero_br(diferenca)} clientes em 'Atraso' ou 'Bloqueio' que não estão sendo contados como Ativos. Ative o toggle acima para incluí-los.")

        col1.metric("👥 Total de Ativos", formatar_numero_br(total_ativos))
        col2.metric("⚠️ Total em Atraso", formatar_numero_br(total_atrasos), 
                   help="Financeiro em Atraso + Bloqueio Automático")
        col3.metric("🏠 Total de Apartamentos", formatar_numero_br(total_apartamentos))
        col4.metric("📈 Penetração Média", f"{media_penetracao:.1f}%")

        # ✅ NOVO: Alerta sobre condomínios sem clientes
        condos_sem_clientes = len(dashboard_df[dashboard_df["Qtd Ativos"] == 0])
        if condos_sem_clientes > 0:
            st.info(f"📌 **{condos_sem_clientes} condomínios** sem clientes ativos (oportunidades de expansão)")

        # ✅ CORREÇÃO DE FORMATAÇÃO: Configurar colunas do dataframe para formato brasileiro
        st.dataframe(dashboard_df, use_container_width=True, column_config={
             "Data de Implantação": st.column_config.DateColumn(format="DD/MM/YYYY"),
             "% Ativos (Penetração)": st.column_config.ProgressColumn(format="%.1f%%", min_value=0, max_value=100),
             "% Capacidade de Exploração": st.column_config.ProgressColumn(format="%.1f%%", min_value=0, max_value=100),
            # ✅ CORREÇÃO: % Atraso agora é calculado sobre ocupados, não sobre apartamentos
             "% Atraso": st.column_config.ProgressColumn(
                format="%.1f%%", 
                min_value=0, 
                max_value=100,
                help="% de clientes em atraso/bloqueio sobre o total de ocupados (ativos + atraso + bloqueio)"
            ),
             "Total Apartamentos": st.column_config.NumberColumn(format="%d", help="Total de apartamentos no condomínio"),
             "Qtd Ativos": st.column_config.NumberColumn(format="%d"),
             "Total Atrasos": st.column_config.NumberColumn(format="%d"),
             "Desativados": st.column_config.NumberColumn(format="%d"),
             "Total Ocupados": st.column_config.NumberColumn(format="%d", help="Ativos + Em Atraso + Bloqueio Automático"),
             "Ativos Puros": st.column_config.NumberColumn(format="%d", help="Apenas status 'Ativo' sem restrições"),
             "Em Atraso": st.column_config.NumberColumn(format="%d"),
             "Bloqueio Automático": st.column_config.NumberColumn(format="%d"),
        })

        # Legenda explicativa dos cálculos
        with st.expander("📖 Entenda os cálculos"):
            st.markdown(f"""
            ### Como são calculados os indicadores:

            **Modo atual:** {'**Todos os Ocupados** (Ativos + Atraso + Bloqueio)' if modo_param == 'todos_ativos' else '**Somente Ativos Limpos** (apenas status "Ativo" puro)'}

            | Métrica | Fórmula | Observação |
            |---------|---------|------------|
            | **Qtd Ativos** | { 'Ativos Puros + Em Atraso + Bloqueio' if modo_param == 'todos_ativos' else 'Apenas Ativos Puros (sem restrições)' } | {'Inclui clientes em atraso/bloqueio' if modo_param == 'todos_ativos' else 'EXCLUI clientes em atraso/bloqueio'} |
             | **% Ativos (Penetração)** | Ativos / Total Apartamentos × 100 | Sobre total de unidades do condomínio |
            | **Total Atrasos** | Em Atraso + Bloqueio Automático | Sempre inclui ambos os status |
            | **% Atraso** | Total Atrasos / Total Ocupados × 100 | ✅ **Corrigido:** Sobre base de ocupados, não sobre apartamentos |
            | **Total Ocupados** | Ativos Puros + Em Atraso + Bloqueio | Base para cálculo de % atraso |
            | **% Capacidade de Exploração** | (Apartamentos - Ocupados) / Apartamentos × 100 | Oportunidade de crescimento |

            **💡 Dica:** O % de Atraso agora é calculado corretamente sobre a base de clientes ocupados (que deveriam estar pagando), não sobre o total de apartamentos do condomínio.
            """)

        excel_buffer = exportar_dashboard_excel(dashboard_df, df_clientes, df_condominios)
        st.download_button(
            label="📥 Exportar Dashboard Completo (Excel)", 
            data=excel_buffer,
            file_name=f"dashboard_condominios_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", 
            use_container_width=True
        )
    st.markdown("---")

    # ==================== ABAS DE ANÁLISE ====================
    # ✅ NOVA ABA: Análise por Zona
    tab1, tab2, tab3, tab4, tab5, tab6, tab7, tab8 = st.tabs([
         "🎯 Penetração", 
         "💰 Receita Potencial", 
         "⚠️ Inadimplência", 
         "📉 Churn", 
         "⚔️ Concorrência",
         "🗺️ Análise por Zona",
         "⏳ Maturidade",
         " Mapeamento Geográfico" # NOVA ABA
    ])

    with tab1:
        st.header("🎯 Taxa de Penetração por Condomínio")
        df_penetracao = calcular_penetracao(df_clientes, df_condominios)
        col1, col2, col3 = st.columns(3)
        with col1:
            regioes = df_condominios["Região"].dropna().unique()
            regiao_filter = st.multiselect("Região", list(regioes) if len(regioes) > 0 else [], key="penetracao_regiao")
        with col2:
            classific_filter = st.multiselect("Classificação", [" Dominado", "🟡 Em Crescimento", "🔴 Baixa Presença"], key="penetracao_classificacao")
        with col3:
            min_penetracao = st.slider("Penetração Mínima (%)", 0, 100, 0)
            
        df_filtered = df_penetracao.copy()
        if regiao_filter: 
            df_filtered = df_filtered[df_filtered["Região"].isin(regiao_filter)]
        if classific_filter: 
            df_filtered = df_filtered[df_filtered["classificacao"].isin(classific_filter)]
        df_filtered = df_filtered[df_filtered["taxa_penetracao"] >= min_penetracao]
        
        fig = px.bar(
            df_filtered.head(20), 
            x="taxa_penetracao", 
            y="Condomínio", 
            color="classificacao", 
            orientation="h",
            title="Top 20 Condomínios por Penetração", 
            color_discrete_map={
                 "🟢 Dominado": "#2ecc71", 
                 " Em Crescimento": "#f39c12", 
                 " Baixa Presença": "#e74c3c"
            }
        )
        fig.update_layout(height=600, yaxis={"categoryorder": "total ascending"})
        st.plotly_chart(fig, use_container_width=True)
        
        with st.expander("📋 Ver Tabela Completa"):
            # ✅ CORREÇÃO DE FORMATAÇÃO: Aplicar formatação brasileira na tabela
            df_display = df_filtered[["Condomínio", "Região", "Apartamentos", "clientes_ativos", "taxa_penetracao", "classificacao"]].copy()
            df_display["Apartamentos"] = df_display["Apartamentos"].apply(lambda x: formatar_numero_br(x))
            df_display["clientes_ativos"] = df_display["clientes_ativos"].apply(lambda x: formatar_numero_br(x))
            df_display["taxa_penetracao"] = df_display["taxa_penetracao"].apply(lambda x: f"{x:.1f}%")
            st.dataframe(df_display, use_container_width=True)
            
        st.markdown("### 💡 Insights Automáticos")
        baixas = df_penetracao[df_penetracao["taxa_penetracao"] < 20]
        altas = df_penetracao[df_penetracao["taxa_penetracao"] > 60]
        c1, c2 = st.columns(2)
        with c1:
            if not baixas.empty:
                top3 = baixas.nlargest(3, 'Apartamentos')['Condomínio'].tolist()
                st.warning(
                     f"**🔴 Oportunidades de Expansão:**\n"
                    f"- {len(baixas)} condomínios com <20% de penetração\n"
                    f"- Top 3: {', '.join(top3) if top3 else 'N/A'}\n"
                    f"- **Ação sugerida:** Campanhas direcionadas + abordagem com síndicos"
                )
        with c2:
            if not altas.empty:
                st.success(
                    f"**🟢 Condomínios Saturados:**\n"
                    f"- {len(altas)} condomínios com >60% de penetração\n"
                    f"- **Ação sugerida:** Foco em retenção, upsell e indicações"
                )

    with tab2:
        st.header("💰 Receita Potencial por Condomínio")
        ticket = st.number_input("🎯 Ticket Médio Estimado (R$)", value=89.99, min_value=10.0, max_value=500.0, step=5.0)
        df_receita = calcular_receita_potencial(df_penetracao, ticket_medio=ticket)
        
        # ✅ CORREÇÃO DE FORMATAÇÃO: Formatar valores monetários
        df_receita_display = df_receita.head(15).copy()
        df_receita_display["receita_atual"] = df_receita_display["receita_atual"].apply(lambda x: formatar_moeda_br(x))
        df_receita_display["receita_potencial"] = df_receita_display["receita_potencial"].apply(lambda x: formatar_moeda_br(x))
        df_receita_display["receita_maxima"] = df_receita_display["receita_maxima"].apply(lambda x: formatar_moeda_br(x))
        
        fig = go.Figure(go.Waterfall(
            name="Receita", 
            orientation="v", 
            measure=["relative"] * len(df_receita.head(15)),
            x=df_receita.head(15)["Condomínio"], 
            y=df_receita.head(15)["receita_potencial"],
            textposition="outside", 
            text=[f"R$ {formatar_numero_br(v, 0)}" for v in df_receita.head(15)["receita_potencial"]],
            connector={"line": {"color": "rgb(63, 63, 63)"}}
        ))
        fig.update_layout(title="💰 Receita Potencial Não Explorada (Top 15)", showlegend=False, height=500)
        st.plotly_chart(fig, use_container_width=True)
        
        st.markdown("### 🎯 Priorização Comercial")
        df_prioridade = df_receita[["Condomínio", "Apartamentos", "clientes_ativos", "potencial_clientes", "receita_potencial"]].copy()
        df_prioridade["prioridade"] = df_prioridade["receita_potencial"].rank(ascending=False)
        # ✅ CORREÇÃO DE FORMATAÇÃO
        df_prioridade["Apartamentos"] = df_prioridade["Apartamentos"].apply(lambda x: formatar_numero_br(x))
        df_prioridade["clientes_ativos"] = df_prioridade["clientes_ativos"].apply(lambda x: formatar_numero_br(x))
        df_prioridade["potencial_clientes"] = df_prioridade["potencial_clientes"].apply(lambda x: formatar_numero_br(x))
        df_prioridade["receita_potencial"] = df_prioridade["receita_potencial"].apply(lambda x: formatar_moeda_br(x))
        st.dataframe(df_prioridade.sort_values("receita_potencial", ascending=False).head(20), use_container_width=True)

    with tab3:
        st.header("️ Análise de Inadimplência por Condomínio")
        df_inadimplencia = analisar_inadimplencia(df_clientes, df_condominios)
        df_merge = df_penetracao.merge(
            df_inadimplencia[["CONDOMANIO", "taxa_inadimplencia"]], 
            left_on="CONDOMANIO", 
            right_on="CONDOMANIO", 
            how="left"
        )
        
        fig = px.scatter(
            df_merge, 
            x="taxa_penetracao", 
            y="taxa_inadimplencia", 
            size="Apartamentos", 
            color="Região", 
            hover_name="Condomínio", 
            title="Penetração vs Inadimplência"
        )
        fig.update_layout(height=500)
        st.plotly_chart(fig, use_container_width=True)
        
        st.markdown("### 🚨 Alertas de Inadimplência")
        altos = df_inadimplencia[df_inadimplencia["taxa_inadimplencia"] > 30]
        if not altos.empty:
            for _, row in altos.head(5).iterrows():
                em_atraso = row.get('Em Atraso', 0)
                em_dia = row.get('Em Dia', 0)
                st.warning(
                    f"**{row['Condomínio']}**: {row['taxa_inadimplencia']}% inadimplência"
                    f"({formatar_numero_br(em_atraso)} de {formatar_numero_br(em_atraso+em_dia)} clientes)"
                )

    with tab4:
        st.header("📉 Análise de Churn por Condomínio")
        df_churn = analisar_churn(df_clientes, df_condominios)
        fig = px.bar(
            df_churn.head(15), 
            x="Condomínio", 
            y="churn_rate", 
            color="churn_rate", 
            color_continuous_scale="Reds", 
            title="Top 15 Condomínios com Maior Taxa de Cancelamento"
        )
        fig.update_layout(height=400)
        st.plotly_chart(fig, use_container_width=True)
        
        if "MOTIVO" in df_clientes.columns:
            st.markdown("### 🔍 Principais Motivos de Cancelamento")
            motivos = df_clientes[df_clientes["STATUS ACESSO"].str.contains("Desativado", na=False)]["MOTIVO"].value_counts().head(10)
            fig_motivos = px.bar(
                x=motivos.values, 
                y=motivos.index, 
                orientation="h", 
                title="Top 10 Motivos de Cancelamento"
            )
            st.plotly_chart(fig_motivos, use_container_width=True)

    with tab5:
        st.header("️ Análise Competitiva")
        df_concorrencia = correlacao_concorrencia(df_penetracao, df_condominios)
        
        if not df_concorrencia.empty:
            fig = px.bar(
                df_concorrencia, 
                 x="Principal Concorrente", 
                y="penetracao_ponderada", 
                color="penetracao_ponderada", 
                color_continuous_scale="RdYlGn", 
                title="Penetração Média por Concorrente Principal"
            )
            fig.update_layout(height=400)
            st.plotly_chart(fig, use_container_width=True)
            
            st.markdown("### 💡 Insights Competitivos")
            if "penetracao_ponderada" in df_concorrencia.columns and not df_concorrencia["penetracao_ponderada"].empty:
                melhor = df_concorrencia.loc[df_concorrencia["penetracao_ponderada"].idxmax()]
                pior = df_concorrencia.loc[df_concorrencia["penetracao_ponderada"].idxmin()]
                c1, c2 = st.columns(2)
                with c1: 
                    st.success(
                        f"**✅ Melhor desempenho:** vs {melhor['Principal Concorrente']}\n"
                        f"- Penetração média: {melhor['penetracao_ponderada']:.1f}%"
                    )
                with c2: 
                    st.error(
                        f"**⚠️ Desafio:** vs {pior['Principal Concorrente']}\n"
                        f"- Penetração média: {pior['penetracao_ponderada']:.1f}%"
                    )
        else:
            st.info("ℹ️ Dados de concorrentes não disponíveis na planilha importada")

    # ✅ NOVA ABA: ANÁLISE POR ZONA
    with tab6:
        st.header("️ Análise Consolidada por Zona/Região")
        
        if not dashboard_df.empty and "Região" in dashboard_df.columns:
            # Calcular estatísticas por zona
            zona_stats = analisar_por_zona(dashboard_df)
            
            if not zona_stats.empty:
                # Filtro de regiões
                regioes_disponiveis = zona_stats["Região"].tolist()
                regioes_selecionadas = st.multiselect(
                     "📍 Filtrar Regiões/Zonas",
                    options=regioes_disponiveis,
                    default=regioes_disponiveis,
                    help="Selecione quais regiões deseja visualizar",
                    key="zona_regioes"
                )
                
                if regioes_selecionadas:
                    zona_filtered = zona_stats[zona_stats["Região"].isin(regioes_selecionadas)]
                    
                    # Métricas Cards - ✅ CORREÇÃO DE FORMATAÇÃO
                    st.markdown("###  Métricas Consolidadas por Zona")
                    
                    # Criar cards em grid
                    cols = st.columns(min(len(zona_filtered), 4))
                    for idx, (_, row) in enumerate(zona_filtered.iterrows()):
                        with cols[idx % 4]:
                            # ✅ CORREÇÃO: Usar HTML para controlar formatação do metric
                            st.markdown(f"""
                             <div style="background-color: #f0f2f6; padding: 10px; border-radius: 8px; margin-bottom: 10px;">
                                 <div style="font-size: 14px; color: #555;">🏙️ {row['Região']}</div>
                                 <div style="font-size: 28px; font-weight: bold; color: #000;">{formatar_numero_br(row['total_apartamentos'])} aptos</div>
                                 <div style="font-size: 14px; color: green;">↑ {row['percentual_ativos']:.1f}% ativos</div>
                             </div>
                             """, unsafe_allow_html=True)
                    
                    # Tabela detalhada - ✅ CORREÇÃO DE FORMATAÇÃO
                    st.markdown("### 📋 Tabela Detalhada por Zona")
                    
                    # Preparar dados para exibição com formatação brasileira
                    zona_display = zona_filtered[[
                         "Região",
                         "total_condominios",
                         "total_apartamentos", 
                         "total_ativos",
                         "percentual_ativos",
                         "total_em_atraso",
                         "percentual_atraso",
                         "total_desativados",
                         "percentual_desativados",
                         "total_ocupados",
                         "percentual_ocupacao",
                         "media_capacidade_exploracao"
                    ]].copy()
                    
                    # ✅ CORREÇÃO: Aplicar formatação brasileira nos números
                    zona_display["total_condominios"] = zona_display["total_condominios"].apply(lambda x: formatar_numero_br(x))
                    zona_display["total_apartamentos"] = zona_display["total_apartamentos"].apply(lambda x: formatar_numero_br(x))
                    zona_display["total_ativos"] = zona_display["total_ativos"].apply(lambda x: formatar_numero_br(x))
                    zona_display["total_em_atraso"] = zona_display["total_em_atraso"].apply(lambda x: formatar_numero_br(x))
                    zona_display["total_desativados"] = zona_display["total_desativados"].apply(lambda x: formatar_numero_br(x))
                    zona_display["total_ocupados"] = zona_display["total_ocupados"].apply(lambda x: formatar_numero_br(x))
                    
                    zona_display.columns = [
                         "Região/Zona",
                         "Condomínios",
                         "Total Aptos", 
                         "Ativos",
                         "% Ativos",
                         "Em Atraso",
                         "% Atraso",
                         "Desativados",
                         "% Desativados",
                         "Ocupados",
                         "% Ocupação",
                         "% Cap. Exploração"
                    ]
                    
                    st.dataframe(
                        zona_display,
                        use_container_width=True,
                        column_config={
                             "% Ativos": st.column_config.ProgressColumn(format="%.1f%%", min_value=0, max_value=100),
                             "% Atraso": st.column_config.ProgressColumn(format="%.1f%%", min_value=0, max_value=100),
                             "% Ocupação": st.column_config.ProgressColumn(format="%.1f%%", min_value=0, max_value=100),
                             "% Cap. Exploração": st.column_config.ProgressColumn(format="%.1f%%", min_value=0, max_value=100),
                        }
                    )
                    
                    # Gráficos comparativos
                    st.markdown("### 📈 Visualizações Comparativas")
                    
                    col_chart1, col_chart2 = st.columns(2)
                    
                    with col_chart1:
                        # Gráfico de barras: Apartamentos vs Ativos por Zona
                        fig_comp = go.Figure()
                        
                        fig_comp.add_trace(go.Bar(
                            name='Total Apartamentos',
                             x=zona_filtered["Região"],
                            y=zona_filtered["total_apartamentos"],
                            marker_color='lightblue'
                        ))
                        
                        fig_comp.add_trace(go.Bar(
                            name='Clientes Ativos',
                            x=zona_filtered["Região"],
                            y=zona_filtered["total_ativos"],
                            marker_color='green'
                        ))
                        
                        fig_comp.add_trace(go.Bar(
                            name='Em Atraso',
                            x=zona_filtered["Região"],
                            y=zona_filtered["total_em_atraso"],
                            marker_color='orange'
                        ))
                        
                        fig_comp.update_layout(
                            title="Composição por Zona",
                            barmode='group',
                            height=400,
                            xaxis_title="Região",
                            yaxis_title="Quantidade"
                        )
                        
                        st.plotly_chart(fig_comp, use_container_width=True)
                    
                    with col_chart2:
                         # Gráfico de pizza: Distribuição de apartamentos
                        fig_pie = px.pie(
                            zona_filtered,
                            values="total_apartamentos",
                            names="Região",
                            title="Distribuição de Apartamentos por Zona",
                            hole=0.4
                        )
                        fig_pie.update_layout(height=400)
                        st.plotly_chart(fig_pie, use_container_width=True)
                    
                    # Gráfico de penetração
                    st.markdown("###  Penetração por Zona")
                    fig_pen = px.bar(
                        zona_filtered,
                        x="Região",
                        y="percentual_ativos",
                        color="percentual_ativos",
                        color_continuous_scale="RdYlGn",
                        text="percentual_ativos",
                        title="Percentual de Ativos por Zona (Penetração)"
                    )
                    fig_pen.update_traces(texttemplate='%{text:.1f}%', textposition='outside')
                    fig_pen.update_layout(height=400)
                    st.plotly_chart(fig_pen, use_container_width=True)
                    
                    # Insights automáticos - ✅ CORREÇÃO DE FORMATAÇÃO
                    st.markdown("### 💡 Insights por Zona")
                    
                    # Melhor e pior zona
                    melhor_zona = zona_filtered.loc[zona_filtered["percentual_ativos"].idxmax()]
                    pior_zona = zona_filtered.loc[zona_filtered["percentual_ativos"].idxmin()]
                    maior_potencial = zona_filtered.loc[zona_filtered["media_capacidade_exploracao"].idxmax()]
                    
                    col_ins1, col_ins2, col_ins3 = st.columns(3)
                    
                    with col_ins1:
                        st.success(
                             f"** Melhor Zona: {melhor_zona['Região']}**\n\n"
                            f"• Penetração: **{melhor_zona['percentual_ativos']:.1f}%**\n"
                            f"• {formatar_numero_br(melhor_zona['total_ativos'])} ativos de {formatar_numero_br(melhor_zona['total_apartamentos'])} aptos\n"
                            f"• {formatar_numero_br(melhor_zona['total_condominios'])} condomínios"
                        )
                    
                    with col_ins2:
                        oportunidade = pior_zona['total_apartamentos'] - pior_zona['total_ativos']
                         st.warning(
                            f"**️ Zona com Menor Penetração: {pior_zona['Região']}**\n\n"
                            f"• Penetração: **{pior_zona['percentual_ativos']:.1f}%**\n"
                            f"• {formatar_numero_br(pior_zona['total_ativos'])} ativos de {formatar_numero_br(pior_zona['total_apartamentos'])} aptos\n"
                            f"• Oportunidade: **{formatar_numero_br(oportunidade)} aptos vazios**"
                        )
                    
                    with col_ins3:
                        st.info(
                            f"**🚀 Maior Potencial: {maior_potencial['Região']}**\n\n"
                            f"• Capacidade de Exploração: **{maior_potencial['media_capacidade_exploracao']:.1f}%**\n"
                            f"• {formatar_numero_br(maior_potencial['total_condominios'])} condomínios para expansão\n"
                            f"• Foco estratégico recomendado"
                        )
                    
                    # Exportar análise por zona
                    st.markdown("### 📥 Exportar Análise")
                    
                    # Criar Excel com aba de zonas
                    output_zona = io.BytesIO()
                    with pd.ExcelWriter(output_zona, engine='openpyxl') as writer:
                        zona_display.to_excel(writer, sheet_name='Análise por Zona', index=False)
                        dashboard_df.to_excel(writer, sheet_name='Dashboard Principal', index=False)
                    output_zona.seek(0)
                    
                    st.download_button(
                        label="📊 Exportar Análise por Zona (Excel)",
                        data=output_zona,
                        file_name=f"analise_por_zona_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx",
                        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                        use_container_width=True
                    )
                else:
                    st.info("👆 Selecione pelo menos uma região para visualizar os dados")
            else:
                st.warning("⚠️ Não foi possível gerar análise por zona. Verifique se a coluna 'Região' existe nos dados.")
        else:
            st.warning("⚠️ Dados insuficientes para análise por zona")

    # ==================== ABA MATURIDADE ====================
    with tab7:
        st.header(" Análise de Maturidade dos Condomínios")
        st.markdown("Avaliação do tempo de cadastro vs. performance de ativação")

        # Parâmetros configuráveis
        col_param1, col_param2, col_param3 = st.columns(3)
        with col_param1:
            ticket_medio_maturidade = st.number_input(
                 "💰 Ticket Médio (R$)", 
                value=89.99, 
                min_value=10.0, 
                max_value=500.0, 
                step=5.0,
                key="ticket_maturidade"
            )
        with col_param2:
            meses_limite = st.number_input(
                 "⏱️ Meses para 'Maduro'", 
                value=18, 
                min_value=6, 
                max_value=60, 
                step=3,
                key="meses_limite"
            )
        with col_param3:
            ordenacao = st.radio(
                 " Ordenação", 
                ["Mais antigos primeiro", "Mais recentes primeiro"],
                index=0,
                key="ordenacao_maturidade"
            )

        # Preparar dados de maturidade
        df_maturidade = preparar_dados_maturidade(df_clientes, df_condominios)
        df_maturidade["classificacao_maturidade"] = df_maturidade.apply(
            lambda row: classificar_maturidade(row, meses_limite), axis=1
        )
        df_maturidade["receita_perdida_mensal"] = df_maturidade.apply(
            lambda row: calcular_receita_perdida_maturidade(row, ticket_medio_maturidade), axis=1
        )

        # Cards de resumo
        st.markdown("### 📊 Resumo da Maturidade")

        col_res1, col_res2, col_res3, col_res4 = st.columns(4)

        maduros_saudaveis = len(df_maturidade[df_maturidade["classificacao_maturidade"].str.contains("🟢 Maduro")])
        maduros_abandonados = len(df_maturidade[df_maturidade["classificacao_maturidade"].str.contains("🔴 Maduro")])
        intermediarios = len(df_maturidade[df_maturidade["classificacao_maturidade"].str.contains("🔵 Intermediário")])
        sem_data = len(df_maturidade[df_maturidade["classificacao_maturidade"].str.contains("Sem Data")])
        perda_total = df_maturidade["receita_perdida_mensal"].sum()

        with col_res1:
            st.metric("🟢 Maduros Saudáveis", formatar_numero_br(maduros_saudaveis))
        with col_res2:
            st.metric(" Maduros Abandonados", formatar_numero_br(maduros_abandonados), 
                     delta=f"-R$ {formatar_numero_br(perda_total/1000, 1)}k/mês", delta_color="inverse")
        with col_res3:
            st.metric(" Intermediários", formatar_numero_br(intermediarios))
        with col_res4:
            st.metric(" Sem Data Cadastro", formatar_numero_br(sem_data))

        # Alerta financeiro
        if perda_total > 0:
            st.error(f"💸 **Receita Perdida:** R$ {formatar_numero_br(perda_total, 2)}/mês  "
                    f"(R$ {formatar_numero_br(perda_total*12, 2)}/ano) em condomínios abandonados!")

        # Filtros
        st.markdown("### 🔍 Filtros")
        col_f1, col_f2, col_f3 = st.columns(3)
        with col_f1:
            classes_disp = sorted(df_maturidade["classificacao_maturidade"].unique())
            classes_sel = st.multiselect("Classificação", classes_disp, default=[], key="maturidade_classificacao")
        with col_f2:
            regioes_disp = [r for r in df_maturidade["Região"].dropna().unique() if r and r != "0"]
            regioes_sel = st.multiselect("Região", regioes_disp, default=[], key="maturidade_regiao")
        with col_f3:
            min_ativos_filtro = st.number_input("Mín. Ativos", 0, 1000, 0)

        # Aplicar filtros
        df_filt = df_maturidade.copy()
        if classes_sel:
            df_filt = df_filt[df_filt["classificacao_maturidade"].isin(classes_sel)]
        if regioes_sel:
            df_filt = df_filt[df_filt["Região"].isin(regioes_sel)]
        if min_ativos_filtro > 0:
            df_filt = df_filt[df_filt["ativos"] >= min_ativos_filtro]

        # Ordenação
        if ordenacao == "Mais antigos primeiro":
            df_filt = df_filt.sort_values(["Data cadastro", "Condomínio"], na_position="last")
        else:
            df_filt = df_filt.sort_values(["Data cadastro", "Condomínio"], ascending=False, na_position="last")

        # Tabela
        st.markdown(f"### 📋 Condomínios ({len(df_filt)} registros)")

        df_display = df_filt[[
             "Condomínio", "Data cadastro", "meses_cadastro", "Região",
             "Apartamentos", "ativos", "percentual_ativos", 
             "classificacao_maturidade", "receita_perdida_mensal"
        ]].copy()

        df_display["Data cadastro"] = df_display["Data cadastro"].apply(
            lambda x: x.strftime("%d/%m/%Y") if pd.notna(x) else "Não informada"
        )
        df_display["meses_cadastro"] = df_display["meses_cadastro"].apply(
            lambda x: f"{int(x)} meses" if pd.notna(x) else "-"
        )
        df_display["Apartamentos"] = df_display["Apartamentos"].apply(lambda x: formatar_numero_br(x))
        df_display["ativos"] = df_display["ativos"].apply(lambda x: formatar_numero_br(x))
        df_display["percentual_ativos"] = df_display["percentual_ativos"].apply(lambda x: f"{x:.1f}%")
        df_display["receita_perdida_mensal"] = df_display["receita_perdida_mensal"].apply(
            lambda x: formatar_moeda_br(x) if x > 0 else "-"
        )
        df_display.columns = [
             "Condomínio", "Data Cadastro", "Tempo", "Região",
             "Aptos", "Ativos", "% Ativos", "Classificação", "Receita Perdida"
        ]

        st.dataframe(
            df_display,
            use_container_width=True,
            column_config={
                 "% Ativos": st.column_config.ProgressColumn(format="%.1f%%", min_value=0, max_value=100),
            }
        )

        # Gráfico de curva de maturidade
        st.markdown("### 📈 Curva de Maturidade por Ano")
        df_com_data = df_maturidade[df_maturidade["Data cadastro"].notna()].copy()

        if len(df_com_data) > 0:
            df_com_data["ano_cadastro"] = df_com_data["Data cadastro"].dt.year
            curva = df_com_data.groupby("ano_cadastro").agg(
                total=("Condomínio", "count"),
                media_ativos=("percentual_ativos", "mean"),
                total_ativos_abs=("ativos", "sum"),
                total_apartamentos=("Apartamentos", "sum")
            ).reset_index()
            curva["penetracao_real"] = (curva["total_ativos_abs"] / curva["total_apartamentos"].replace(0, np.nan) * 100).round(1)

            fig_curva = go.Figure()
            fig_curva.add_trace(go.Scatter(
                x=curva["ano_cadastro"], y=curva["media_ativos"],
                mode='lines+markers', name='% Ativos Médio',
                line=dict(color='green', width=3), marker=dict(size=10)
            ))
            fig_curva.add_trace(go.Bar(
                 x=curva["ano_cadastro"], y=curva["total"],
                name='Qtd Condomínios', marker_color='lightblue',
                opacity=0.6, yaxis='y2'
            ))
            fig_curva.update_layout(
                title="Evolução da Maturidade por Ano de Cadastro",
                xaxis_title="Ano", yaxis_title="% Ativos Médio",
                yaxis2=dict(title="Qtd", overlaying='y', side='right'),
                height=450, legend=dict(orientation="h", yanchor="bottom", y=1.02)
            )
            st.plotly_chart(fig_curva, use_container_width=True)

        # Alertas de condomínios críticos
        st.markdown("### 🚨 Condomínios Maduros Abandonados")
        abandonados = df_maturidade[df_maturidade["classificacao_maturidade"].str.contains(" Maduro")].sort_values("Data cadastro")

        if len(abandonados) > 0:
            st.warning(f"**{len(abandonados)} condomínios cadastrados há mais de {meses_limite} meses com baixa performance:**")
            for _, row in abandonados.iterrows():
                tempo = f"{int(row['meses_cadastro'])} meses" if pd.notna(row['meses_cadastro']) else "tempo não calc."
                aptos_str = f"{int(row['Apartamentos'])} aptos" if row['Apartamentos'] > 0 else "sem aptos cad."
                st.markdown(f"• **{row['Condomínio']}** - {tempo} | {aptos_str} | {int(row['ativos'])} ativos ({row['percentual_ativos']:.1f}%) | 💸 {formatar_moeda_br(row['receita_perdida_mensal'])}/mês")
        else:
            st.success("✅ Nenhum condomínio maduro abandonado identificado!")

        # Exportar
        st.markdown("###  Exportar")
        output_mat = io.BytesIO()
        with pd.ExcelWriter(output_mat, engine='openpyxl') as writer:
            df_display.to_excel(writer, sheet_name='Maturidade', index=False)
        output_mat.seek(0)
        st.download_button(
             "📊 Exportar Análise de Maturidade", output_mat,
            f"maturidade_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx",
             "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            use_container_width=True
        )

    # ==================== NOVA ABA: MAPEAMENTO GEOGRÁFICO ====================
    with tab8:
        st.header("📍 Mapeamento Geográfico dos Condomínios")
        st.markdown("Visualize a distribuição espacial e planeje rotas de visita.")
        
        if not GEOCODING_AVAILABLE:
            st.error("❌ Bibliotecas de mapa não instaladas. Instale `streamlit-folium` e `geopy` no requirements.txt.")
        else:
            # Verifica se temos dados de endereço
            enderecos_necessarios = ["Endereço", "Número", "CEP"]
            # Precisamos garantir que df_penetracao tenha esses dados. 
            # Vamos recalcular df_penetracao aqui garantindo as colunas de endereço
            df_mapa_base = calcular_penetracao(df_clientes, df_condominios)
            
            # Merge para pegar endereço completo se não estiver no df_penetracao original
            # Assumindo que df_condominios tem: ID, Endereço, Número, CEP, Cidade, Sindico, Celular sindico
            cols_endereco = ["ID", "Endereço", "Número", "CEP", "Cidade", "Sindico", "Celular sindico"]
            cols_existentes = [c for c in cols_endereco if c in df_condominios.columns]
            
            if len(cols_existentes) < 3: # Precisa pelo menos de Endereço, Num, CEP
                st.warning("⚠️ Colunas de endereço insuficientes na planilha de condomínios para gerar o mapa.")
            else:
                df_mapa_base = df_mapa_base.merge(
                    df_condominios[cols_existentes], 
                    left_on="CONDOMANIO", 
                    right_on="ID", 
                    how="left"
                )

                faltam_colunas = [col for col in ["Endereço", "Número", "CEP"] if col not in df_mapa_base.columns]
                
                if faltam_colunas:
                    st.warning(f"️ Colunas de endereço faltando: {', '.join(faltam_colunas)}. Impossível gerar mapa.")
                else:
                    st.info("ℹ️ O mapeamento requer conversão de endereços em coordenadas. Isso pode levar alguns segundos dependendo da quantidade de condomínios.")
                    
                    if st.button("🛰️ Gerar Coordenadas e Exibir Mapa", type="primary"):
                        with st.spinner("🌍 Geocodificando endereços... Aguarde."):
                            # Aplica geocodificação linha a linha
                            coords = df_mapa_base.apply(
                                lambda row: obter_coordenadas(row["Endereço"], row["Número"], row["CEP"]), 
                                axis=1
                            )
                            df_mapa_base["lat"] = [c[0] for c in coords]
                            df_mapa_base["lon"] = [c[1] for c in coords]
                            
                            # Remove linhas sem coordenadas
                            df_plot = df_mapa_base.dropna(subset=["lat", "lon"])
                            
                            if df_plot.empty:
                                st.error("❌ Não foi possível geocodificar nenhum endereço. Verifique se os dados de Endereço/CEP estão corretos.")
                            else:
                                st.success(f"✅ {len(df_plot)} endereços localizados com sucesso!")
                                
                                # Filtros para o mapa
                                col_map_f1, col_map_f2 = st.columns(2)
                                with col_map_f1:
                                    regioes_map = df_plot["Região"].dropna().unique()
                                    regiao_map_filter = st.multiselect("Filtrar por Região", list(regioes_map), default=list(regioes_map), key="map_regiao")
                                with col_map_f2:
                                    cor_map = st.selectbox("Cor dos Pontos por", ["Classificação", "Região", "Padrão"], key="map_cor")
                                
                                df_final_plot = df_plot[df_plot["Região"].isin(regiao_map_filter)]
                                
                                # Configuração do Mapa Folium
                                m = folium.Map(location=[-22.9068, -43.1729], zoom_start=11) # Centro RJ
                                
                                # Define cores baseadas na classificação
                                def get_color(row):
                                    if cor_map == "Classificação":
                                        if "🟢" in str(row["classificacao"]): return "green"
                                        elif "🟡" in str(row["classificacao"]): return "orange"
                                        else: return "red"
                                    elif cor_map == "Região":
                                        import hashlib
                                        h = hashlib.md5(str(row["Região"]).encode()).hexdigest()
                                        colors = ["blue", "purple", "darkred", "lightred", "beige", "darkblue", "darkgreen", "cadetblue", "darkpurple"]
                                        return colors[int(h[0], 16) % len(colors)]
                                    return "blue"
                                
                                for _, row in df_final_plot.iterrows():
                                    # Conteúdo do Popup (Card)
                                    sindico = row.get('Sindico', 'N/A') if pd.notna(row.get('Sindico')) else 'N/A'
                                    tel = row.get('Celular sindico', 'N/A') if pd.notna(row.get('Celular sindico')) else 'N/A'
                                    
                                    popup_html = f"""
                                    <div style="font-family: Arial; min-width: 220px;">
                                        <h4 style="margin:0; color:#0056b3;">{row['Condomínio']}</h4>
                                        <hr style="margin:5px 0;">
                                        <b>Endereço:</b> {row['Endereço']}, {row['Número']}<br>
                                        <b>Região:</b> {row['Região']}<br>
                                        <b>Apartamentos:</b> {int(row['Apartamentos'])}<br>
                                        <b>Ativos:</b> {int(row['clientes_ativos'])}<br>
                                        <b>Penetração:</b> <span style="color:{'green' if row['taxa_penetracao']>=50 else 'orange' if row['taxa_penetracao']>=25 else 'red'}"><b>{row['taxa_penetracao']:.1f}%</b></span><br>
                                        <b>Síndico:</b> {sindico}<br>
                                        <b>Tel:</b> {tel}<br>
                                        <br>
                                        <small>Concorrente: {row.get('Principal Concorrente', 'N/A')}</small>
                                    </div>
                                    """
                                    
                                    folium.CircleMarker(
                                        location=[row['lat'], row['lon']],
                                        radius=8,
                                        popup=folium.Popup(popup_html, max_width=300),
                                        tooltip=f"{row['Condomínio']} - {row['taxa_penetracao']:.1f}%",
                                        color=get_color(row),
                                        fill=True,
                                        fill_opacity=0.7
                                    ).add_to(m)
                                
                                # Renderiza o mapa no Streamlit
                                st_folium(m, width=1000, height=600)
                                
                                st.caption("💡 Dica: Clique nos pontos para ver detalhes. Use o scroll para navegar. As cores representam a classificação de penetração.")

    st.markdown("---")
    st.subheader("🗺️ Mapa Estratégico de Condomínios (Matriz)")

    # Usar df_penetracao que já foi calculado na tab1
    if 'df_penetracao' in locals() and not df_penetracao.empty:
        fig_mapa = px.scatter(
            df_penetracao, 
            x="Apartamentos", 
            y="taxa_penetracao", 
            size="clientes_ativos", 
            color="classificacao", 
            hover_name="Condomínio", 
            hover_data=["Região", "Principal Concorrente"], 
            title="Matriz: Tamanho do Condomínio vs Penetração"
        )
        fig_mapa.add_hline(y=25, line_dash="dash", line_color="orange", annotation_text="Limite Crescimento")
        fig_mapa.add_hline(y=50, line_dash="dash", line_color="green", annotation_text="Limite Dominado")
        fig_mapa.add_vline(x=df_penetracao["Apartamentos"].median(), line_dash="dot", annotation_text="Tamanho Médio")
        fig_mapa.update_layout(height=500, hovermode="closest")
        st.plotly_chart(fig_mapa, use_container_width=True)

    st.markdown("""
    ####  Como usar esta matriz:
    | Quadrante | Perfil | Ação Recomendada |
    |-----------|--------|-----------------|
    | 🔴 Grande + Baixa Penetração | **Prioridade Máxima** | Campanha agressiva, negociação com síndico |
    |  Médio + Crescimento | **Consolidar** | Fidelização, indicações, upsell |
    | 🟢 Pequeno + Alta Penetração | **Manter** | Atendimento premium, monitorar churn |
    | ⚪ Qualquer + Saturado | **Otimizar** | Foco em margem, não volume |
    """)

if __name__ == "__main__":
    render_relatorios_condominios()
