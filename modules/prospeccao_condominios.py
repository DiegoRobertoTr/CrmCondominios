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
import re

# ==================== FUNÇÕES UTILITÁRIAS ====================

def limpar_valor_data(valor):
    """Limpa e converte valores de data"""
    if pd.isna(valor) or valor is None:
        return None
    if isinstance(valor, str):
        valor_limpo = valor.strip()
        if valor_limpo in ["00/00/0000", "0", "", "nan", "NaT", "null", "NULL", "-"]:
            return None
        # Tentar extrair data de strings como "15/07/25: Entregue há dois meses"
        match = re.search(r'\d{2}/\d{2}/\d{2,4}', valor_limpo)
        if match:
            valor_limpo = match.group()
        try:
            valor = pd.to_datetime(valor_limpo, errors='coerce', dayfirst=True)
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
    """Converte todas as colunas de data em um DataFrame"""
    df = df.copy()
    for col in df.columns:
        col_lower = col.lower()
        eh_coluna_data = any(palavra in col_lower for palavra in ['data', 'date', 'cadastro', 'entrega', 'previsao', 'atualizacao'])
        if eh_coluna_data or pd.api.types.is_datetime64_any_dtype(df[col]):
            df[col] = pd.to_datetime(df[col], errors='coerce')
            df[col] = df[col].apply(lambda x: limpar_valor_data(x))
    return df

def formatar_numero_br(valor, decimais=0):
    """Formata número no padrão brasileiro"""
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

def safe_strftime(value, fmt="%d/%m/%Y"):
    """Formata datetime com tratamento seguro"""
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

# ==================== CONFIGURAÇÃO INICIAL ====================

st.set_page_config(page_title="🏗️ Prospecção de Condomínios", layout="wide")

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

def save_prospeccao_data(db, df_prospeccao, metadata):
    """Salva dados de prospecção no MongoDB"""
    collection = db["prospeccao_condominios"]
    df_limpo = converter_dataframe_dates(df_prospeccao)
    
    docs = []
    for _, row in df_limpo.iterrows():
        doc = row.to_dict()
        for key, value in list(doc.items()):
            if isinstance(value, (pd.Timestamp, datetime)):
                doc[key] = limpar_valor_data(value)
            elif pd.isna(value):
                doc[key] = None
        doc["_import_timestamp"] = datetime.now().replace(tzinfo=None)
        doc["_import_batch"] = metadata["batch_id"]
        docs.append(doc)
    
    if docs:
        collection.insert_many(docs)
    
    db["prospeccao_meta"].insert_one({
        "batch_id": metadata["batch_id"],
        "timestamp": datetime.now().replace(tzinfo=None),
        "total_projetos": len(df_prospeccao),
        "fases": metadata.get("fases", {}),
        "construtoras": metadata.get("construtoras", [])
    })
    return True

def load_latest_prospeccao(db):
    """Carrega últimos dados de prospecção"""
    meta = db["prospeccao_meta"].find_one(sort=[("timestamp", -1)])
    if not meta:
        return None, None
    collection = db["prospeccao_condominios"]
    df_prospeccao = pd.DataFrame(list(collection.find({"_import_batch": meta["batch_id"]})))
    if "_id" in df_prospeccao.columns:
        df_prospeccao = df_prospeccao.drop(columns=["_id"])
    df_prospeccao = converter_dataframe_dates(df_prospeccao)
    return df_prospeccao, meta

def clear_prospeccao_data(db, batch_id=None):
    """Limpa dados de prospecção"""
    collection = db["prospeccao_condominios"]
    if batch_id:
        result = collection.delete_many({"_import_batch": batch_id})
        db["prospeccao_meta"].delete_many({"batch_id": batch_id})
    else:
        result = collection.delete_many({})
        db["prospeccao_meta"].delete_many({})
    return result.deleted_count

# ==================== FUNÇÕES DE ANÁLISE ====================

def classificar_fase(fase_str):
    """Classifica a fase do projeto em categorias padronizadas"""
    if pd.isna(fase_str):
        return "Não Informado"
    fase_lower = str(fase_str).lower().strip()
    
    if any(x in fase_lower for x in ["pronto", "entregue", "finalizado"]):
        return "✅ Pronto"
    elif any(x in fase_lower for x in ["final de obra", "fase final", "acabamento"]):
        return "🏁 Final de Obra"
    elif any(x in fase_lower for x in ["intermediário", "intermediario", "50%", "60%", "70%"]):
        return "🔨 Intermediário"
    elif any(x in fase_lower for x in ["início de obra", "inicio de obra", "fundação", "estrutura"]):
        return "🚧 Início de Obra"
    elif any(x in fase_lower for x in ["lançamento", "lancamento", "vendas"]):
        return "📢 Lançamento"
    elif any(x in fase_lower for x in ["futuro", "planejado", "terreno"]):
        return "📅 Futuro Lançamento"
    elif any(x in fase_lower for x in ["não entramos", "perdido", "embargado", "sem viabilidade"]):
        return "❌ Não Entramos"
    else:
        return "📋 Em Tratativa"

def extrair_previsao_entrega(viabilidade_str):
    """Extrai data de previsão de entrega da coluna de viabilidade/obs"""
    if pd.isna(viabilidade_str):
        return None
    viab_lower = str(viabilidade_str).lower()
    
    # Padrões de data
    padroes_data = [
        r'(\d{2}/\d{2}/\d{2,4})',
        r'(\d{2}/\d{4})',
        r'(jan|fev|mar|abr|mai|jun|jul|ago|set|out|nov|dez)[\s/-]+(\d{4})',
        r'(set|dez|nov|out)[\s/-]+(\d{2})'
    ]
    
    for padrao in padroes_data:
        match = re.search(padrao, viabilidade_str, re.IGNORECASE)
        if match:
            try:
                data_str = match.group()
                # Normalizar para formato completo
                if len(data_str) == 5:  # 12/24
                    data_str = f"01/{data_str}"
                data = pd.to_datetime(data_str, errors='coerce', dayfirst=True)
                if pd.notna(data):
                    return data
            except:
                pass
    return None

def calcular_dias_para_entrega(previsao_entrega):
    """Calcula dias restantes para entrega"""
    if pd.isna(previsao_entrega):
        return None
    hoje = datetime.now().replace(tzinfo=None)
    if isinstance(previsao_entrega, pd.Timestamp):
        previsao_entrega = previsao_entrega.to_pydatetime().replace(tzinfo=None)
    delta = previsao_entrega - hoje
    return delta.days

def analisar_por_construtora(df_prospeccao):
    """Análise consolidada por construtora"""
    if df_prospeccao.empty or "CONSTRUTORA" not in df_prospeccao.columns:
        return pd.DataFrame()
    
    construtora_stats = df_prospeccao.groupby("CONSTRUTORA").agg(
        total_projetos=("NOME", "count"),
        total_apartamentos=("APTO", lambda x: pd.to_numeric(x, errors='coerce').sum()),
        projetos_pronto=("FASE_CLASSIFICADA", lambda x: (x == "✅ Pronto").sum()),
        projetos_final_obra=("FASE_CLASSIFICADA", lambda x: (x == "🏁 Final de Obra").sum()),
        projetos_intermediario=("FASE_CLASSIFICADA", lambda x: (x == "🔨 Intermediário").sum()),
        projetos_inicio_obra=("FASE_CLASSIFICADA", lambda x: (x == "🚧 Início de Obra").sum()),
        projetos_lancamento=("FASE_CLASSIFICADA", lambda x: (x == "📢 Lançamento").sum()),
        projetos_futuro=("FASE_CLASSIFICADA", lambda x: (x == "📅 Futuro Lançamento").sum()),
        projetos_nao_entramos=("FASE_CLASSIFICADA", lambda x: (x == "❌ Não Entramos").sum())
    ).reset_index()
    
    # Calcular percentuais
    construtora_stats["percentual_pronto"] = (construtora_stats["projetos_pronto"] / construtora_stats["total_projetos"] * 100).round(1)
    construtora_stats["percentual_em_obra"] = ((construtora_stats["projetos_final_obra"] + construtora_stats["projetos_intermediario"] + construtora_stats["projetos_inicio_obra"]) / construtora_stats["total_projetos"] * 100).round(1)
    construtora_stats["percentual_lancamento"] = ((construtora_stats["projetos_lancamento"] + construtora_stats["projetos_futuro"]) / construtora_stats["total_projetos"] * 100).round(1)
    
    return construtora_stats.sort_values("total_projetos", ascending=False).reset_index(drop=True)

def analisar_por_zona(df_prospeccao):
    """Análise consolidada por Zona"""
    if df_prospeccao.empty or "ZONA" not in df_prospeccao.columns:
        return pd.DataFrame()
    
    zona_stats = df_prospeccao.groupby("ZONA").agg(
        total_projetos=("NOME", "count"),
        total_apartamentos=("APTO", lambda x: pd.to_numeric(x, errors='coerce').sum()),
        projetos_em_obra=("FASE_CLASSIFICADA", lambda x: x.isin(["🏁 Final de Obra", "🔨 Intermediário", "🚧 Início de Obra"]).sum()),
        projetos_pronto=("FASE_CLASSIFICADA", lambda x: (x == "✅ Pronto").sum()),
        oportunidades=("FASE_CLASSIFICADA", lambda x: x.isin(["📢 Lançamento", "📅 Futuro Lançamento", "🔨 Intermediário", "🚧 Início de Obra"]).sum())
    ).reset_index()
    
    zona_stats["percentual_em_obra"] = (zona_stats["projetos_em_obra"] / zona_stats["total_projetos"] * 100).round(1)
    zona_stats["percentual_oportunidades"] = (zona_stats["oportunidades"] / zona_stats["total_projetos"] * 100).round(1)
    
    return zona_stats.sort_values("total_projetos", ascending=False).reset_index(drop=True)

def timeline_entregas(df_prospeccao):
    """Prepara dados para timeline de entregas"""
    df_timeline = df_prospeccao.copy()
    df_timeline["PREVISAO_ENTREGA"] = df_timeline["VIABILIDADE"].apply(extrair_previsao_entrega)
    df_timeline = df_timeline[df_timeline["PREVISAO_ENTREGA"].notna()]
    df_timeline["DIAS_RESTANTES"] = df_timeline["PREVISAO_ENTREGA"].apply(calcular_dias_para_entrega)
    df_timeline["ANO_ENTREGA"] = df_timeline["PREVISAO_ENTREGA"].dt.year
    df_timeline["MES_ENTREGA"] = df_timeline["PREVISAO_ENTREGA"].dt.to_period('M')
    return df_timeline.sort_values("PREVISAO_ENTREGA")

def calcular_prioridade(row):
    """Calcula prioridade de ação baseado em fase e tempo"""
    fase = row.get("FASE_CLASSIFICADA", "")
    dias = row.get("DIAS_RESTANTES", None)
    
    # Prioridade máxima: pronto ou final de obra com entrega próxima
    if fase in ["✅ Pronto", "🏁 Final de Obra"]:
        if dias is not None and dias <= 90:
            return "🔴 Urgente"
        elif dias is not None and dias <= 180:
            return "🟠 Alta"
        else:
            return "🟡 Média"
    # Prioridade alta: em obra com entrega em 2025
    elif fase in ["🔨 Intermediário", "🚧 Início de Obra"]:
        if dias is not None and dias <= 365:
            return "🟠 Alta"
        else:
            return "🟡 Média"
    # Prioridade média: lançamentos
    elif fase in ["📢 Lançamento", "📅 Futuro Lançamento"]:
        return "🟢 Planejamento"
    else:
        return "⚪ Baixa"

def exportar_prospeccao_excel(df_prospeccao, df_construtoras, df_zonas):
    """Exporta dados de prospecção para Excel"""
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        df_prospeccao.to_excel(writer, sheet_name='Projetos', index=False)
        df_construtoras.to_excel(writer, sheet_name='Por Construtora', index=False)
        df_zonas.to_excel(writer, sheet_name='Por Zona', index=False)
    output.seek(0)
    return output

# ==================== INTERFACE STREAMLIT ====================

def render_prospeccao_condominios():
    st.title("🏗️ Prospecção de Condomínios")
    st.markdown("Acompanhamento de fases de construção por construtora e oportunidades de mercado")
    
    db = init_mongo()
    st.markdown("---")
    
    # ==================== GERENCIAMENTO DE DADOS ====================
    st.subheader("⚙️ Gerenciamento de Dados")
    col1, col2 = st.columns([3, 1])
    
    with col1:
        uploaded_file = st.file_uploader(
            "📤 Importar Planilha de Prospecção", 
            type=["xlsx", "xls"], 
            help="Planilha com múltiplas abas por fase (Pronto, Final de obra, Intermediário, etc.)"
        )
    with col2:
        if st.button("🔄 Recarregar Últimos", type="primary", use_container_width=True):
            st.session_state["reload_prospeccao"] = True
        if st.button("🗑️ Limpar Dados", type="secondary", use_container_width=True):
            if st.session_state.get("confirm_delete_prospeccao"):
                deleted = clear_prospeccao_data(db)
                st.success(f"✅ {deleted} registros removidos!")
                st.session_state["confirm_delete_prospeccao"] = False
                st.rerun()
            else:
                st.warning("⚠️ Clique novamente para confirmar")
                st.session_state["confirm_delete_prospeccao"] = True
    
    # Carregar metadados
    meta = db["prospeccao_meta"].find_one(sort=[("timestamp", -1)])
    if meta:
        ts = meta.get('timestamp')
        ts_str = safe_strftime(ts, "%d/%m/%Y %H:%M") if ts else "Data não disponível"
        st.info(f"""
        **Última Importação:**
        - 📅 {ts_str}
        - 🏗️ {meta['total_projetos']} projetos
        - 🏢 {len(meta.get('construtoras', []))} construtoras
        """)
    else:
        st.warning("⚠️ Nenhum dado importado ainda")
    
    st.markdown("---")
    df_prospeccao, meta = None, None
    
    # ==================== IMPORTAÇÃO DA PLANILHA ====================
    if uploaded_file:
        try:
            # Ler todas as abas da planilha
            xls = pd.ExcelFile(uploaded_file)
            abas = xls.sheet_names
            
            dfs_fases = []
            fases_count = {}
            
            for aba in abas:
                try:
                    df_temp = pd.read_excel(xls, sheet_name=aba)
                    if len(df_temp) > 0:
                        # Adicionar coluna de fase baseada no nome da aba
                        df_temp["FASE_ORIGINAL"] = aba
                        df_temp["FASE_CLASSIFICADA"] = df_temp["ESTÁGIO"].apply(classificar_fase) if "ESTÁGIO" in df_temp.columns else classificar_fase(aba)
                        dfs_fases.append(df_temp)
                        fases_count[aba] = len(df_temp)
                except Exception as e:
                    st.warning(f"⚠️ Erro ao ler aba '{aba}': {str(e)}")
            
            if dfs_fases:
                df_prospeccao = pd.concat(dfs_fases, ignore_index=True)
                
                # Padronizar colunas
                col_mapping = {
                    'ZONA': 'ZONA',
                    'BAIRRO': 'BAIRRO',
                    'ENDEREÇO': 'ENDEREÇO',
                    'ENDERECO': 'ENDEREÇO',
                    'NOME': 'NOME',
                    'CONDOMÍNIO': 'NOME',
                    'CONDOMINIO': 'NOME',
                    'BLOCO': 'BLOCO',
                    'APTO': 'APTO',
                    'APARTAMENTOS': 'APTO',
                    'CONSTRUTORA': 'CONSTRUTORA',
                    'ESTÁGIO': 'ESTÁGIO',
                    'ESTAGIO': 'ESTÁGIO',
                    'VIABILIDADE': 'VIABILIDADE',
                    'OBS': 'VIABILIDADE',
                    'OBSERVAÇÕES': 'VIABILIDADE',
                    'DATA': 'DATA_ATUALIZACAO',
                    'DATA DA ATUALIZAÇÃO': 'DATA_ATUALIZACAO'
                }
                
                df_prospeccao = df_prospeccao.rename(columns={k: v for k, v in col_mapping.items() if k in df_prospeccao.columns})
                
                # Extrair previsão de entrega
                df_prospeccao["PREVISAO_ENTREGA"] = df_prospeccao["VIABILIDADE"].apply(extrair_previsao_entrega) if "VIABILIDADE" in df_prospeccao.columns else None
                df_prospeccao["DIAS_RESTANTES"] = df_prospeccao["PREVISAO_ENTREGA"].apply(calcular_dias_para_entrega)
                df_prospeccao["PRIORIDADE"] = df_prospeccao.apply(calcular_prioridade, axis=1)
                
                # Converter datas
                df_prospeccao = converter_dataframe_dates(df_prospeccao)
                
                metadata = {
                    "timestamp": datetime.now().replace(tzinfo=None),
                    "batch_id": f"prospeccao_{datetime.now().strftime('%Y%m%d_%H%M%S')}",
                    "filename": uploaded_file.name,
                    "fases": fases_count,
                    "construtoras": df_prospeccao["CONSTRUTORA"].dropna().unique().tolist() if "CONSTRUTORA" in df_prospeccao.columns else []
                }
                
                if save_prospeccao_data(db, df_prospeccao, metadata):
                    st.success(f"✅ Dados importados! {len(df_prospeccao)} projetos de {len(metadata['construtoras'])} construtoras")
                    st.rerun()
            else:
                st.error("❌ Nenhuma aba com dados válida encontrada na planilha")
                
        except Exception as e:
            st.error(f"❌ Erro ao processar planilha: {str(e)}")
            import traceback
            st.expander("Detalhes técnicos do erro").code(traceback.format_exc())
    
    elif st.session_state.get("reload_prospeccao") or "df_prospeccao_cached" not in st.session_state:
        result = load_latest_prospeccao(db)
        if result[0] is not None:
            df_prospeccao, meta = result
            # Recalcular campos derivados
            if "FASE_CLASSIFICADA" not in df_prospeccao.columns and "ESTÁGIO" in df_prospeccao.columns:
                df_prospeccao["FASE_CLASSIFICADA"] = df_prospeccao["ESTÁGIO"].apply(classificar_fase)
            if "PREVISAO_ENTREGA" not in df_prospeccao.columns and "VIABILIDADE" in df_prospeccao.columns:
                df_prospeccao["PREVISAO_ENTREGA"] = df_prospeccao["VIABILIDADE"].apply(extrair_previsao_entrega)
                df_prospeccao["DIAS_RESTANTES"] = df_prospeccao["PREVISAO_ENTREGA"].apply(calcular_dias_para_entrega)
            if "PRIORIDADE" not in df_prospeccao.columns:
                df_prospeccao["PRIORIDADE"] = df_prospeccao.apply(calcular_prioridade, axis=1)
            
            st.session_state["df_prospeccao_cached"] = df_prospeccao
            st.session_state["meta_cached"] = meta
            st.success("📦 Dados pré-carregados da última importação")
        else:
            st.info("👆 Faça upload da planilha para começar")
            return
    else:
        df_prospeccao = st.session_state["df_prospeccao_cached"]
        meta = st.session_state["meta_cached"]
    
    if "reload_prospeccao" in st.session_state:
        del st.session_state["reload_prospeccao"]
    
    # ==================== DASHBOARD PRINCIPAL ====================
    st.subheader("📊 Dashboard Geral de Prospecção")
    st.markdown("---")
    
    if not df_prospeccao.empty:
        # KPIs Principais
        col1, col2, col3, col4, col5 = st.columns(5)
        
        total_projetos = len(df_prospeccao)
        total_apartamentos = pd.to_numeric(df_prospeccao["APTO"], errors='coerce').sum() if "APTO" in df_prospeccao.columns else 0
        projetos_em_obra = len(df_prospeccao[df_prospeccao["FASE_CLASSIFICADA"].isin(["🏁 Final de Obra", "🔨 Intermediário", "🚧 Início de Obra"])]) if "FASE_CLASSIFICADA" in df_prospeccao.columns else 0
        entregas_2025 = len(df_prospeccao[(df_prospeccao["PREVISAO_ENTREGA"].dt.year == 2025) if "PREVISAO_ENTREGA" in df_prospeccao.columns else False]) if "PREVISAO_ENTREGA" in df_prospeccao.columns else 0
        oportunidades_imediatas = len(df_prospeccao[df_prospeccao["PRIORIDADE"] == "🔴 Urgente"]) if "PRIORIDADE" in df_prospeccao.columns else 0
        
        col1.metric("🏗️ Total de Projetos", formatar_numero_br(total_projetos))
        col2.metric("🏠 Total de Apartamentos", formatar_numero_br(int(total_apartamentos)))
        col3.metric("🔨 Em Obra", formatar_numero_br(projetos_em_obra))
        col4.metric("📅 Entregas 2025", formatar_numero_br(entregas_2025))
        col5.metric("🔴 Oportunidades Imediatas", formatar_numero_br(oportunidades_imediatas))
        
        st.markdown("---")
        
        # ==================== ABAS DE ANÁLISE ====================
        tab1, tab2, tab3, tab4, tab5 = st.tabs([
            "📊 Por Construtora",
            "🗺️ Por Zona/Bairro",
            "⏱️ Timeline de Entregas",
            "🎯 Priorização",
            "📋 Lista Completa"
        ])
        
        # TAB 1: POR CONSTRUTORA
        with tab1:
            st.header("🏢 Análise por Construtora")
            
            df_construtoras = analisar_por_construtora(df_prospeccao)
            
            if not df_construtoras.empty:
                # Filtro de construtoras
                construtoras_disp = df_construtoras["CONSTRUTORA"].dropna().unique().tolist()
                construtoras_sel = st.multiselect(
                    "Filtrar Construtoras",
                    options=construtoras_disp,
                    default=construtoras_disp[:5],
                    key="construtoras_filter"
                )
                
                if construtoras_sel:
                    df_construtoras_filt = df_construtoras[df_construtoras["CONSTRUTORA"].isin(construtoras_sel)]
                    
                    # Gráfico: Top construtoras por volume
                    col_chart1, col_chart2 = st.columns(2)
                    
                    with col_chart1:
                        fig1 = px.bar(
                            df_construtoras_filt.head(10),
                            x="total_projetos",
                            y="CONSTRUTORA",
                            orientation="h",
                            title="Top 10 Construtoras por Nº de Projetos",
                            color="total_projetos",
                            color_continuous_scale="Blues"
                        )
                        fig1.update_layout(height=400, yaxis={"categoryorder": "total ascending"})
                        st.plotly_chart(fig1, use_container_width=True)
                    
                    with col_chart2:
                        fig2 = px.bar(
                            df_construtoras_filt.head(10),
                            x="total_apartamentos",
                            y="CONSTRUTORA",
                            orientation="h",
                            title="Top 10 Construtoras por Total de APTs",
                            color="total_apartamentos",
                            color_continuous_scale="Greens"
                        )
                        fig2.update_layout(height=400, yaxis={"categoryorder": "total ascending"})
                        st.plotly_chart(fig2, use_container_width=True)
                    
                    # Gráfico de composição por fase
                    st.markdown("### 📊 Composição de Fases por Construtora")
                    fases_cols = ["projetos_pronto", "projetos_final_obra", "projetos_intermediario", "projetos_inicio_obra", "projetos_lancamento", "projetos_futuro"]
                    fases_labels = ["✅ Pronto", "🏁 Final", "🔨 Intermed.", "🚧 Início", "📢 Lançam.", "📅 Futuro"]
                    
                    df_fases_plot = df_construtoras_filt.head(8).copy()
                    df_fases_plot = df_fases_plot.set_index("CONSTRUTORA")[fases_cols]
                    df_fases_plot.columns = fases_labels
                    
                    fig3 = px.bar(
                        df_fases_plot,
                        barmode="stack",
                        title="Distribuição de Fases por Construtora (Top 8)",
                        color_discrete_sequence=px.colors.qualitative.Set3
                    )
                    fig3.update_layout(height=500, xaxis_title="Construtora", yaxis_title="Nº de Projetos")
                    st.plotly_chart(fig3, use_container_width=True)
                    
                    # Tabela detalhada
                    st.markdown("### 📋 Tabela Detalhada por Construtora")
                    df_display = df_construtoras_filt[[
                        "CONSTRUTORA", "total_projetos", "total_apartamentos",
                        "percentual_pronto", "percentual_em_obra", "percentual_lancamento"
                    ]].copy()
                    
                    df_display["total_apartamentos"] = df_display["total_apartamentos"].apply(lambda x: formatar_numero_br(int(x)))
                    df_display["percentual_pronto"] = df_display["percentual_pronto"].apply(lambda x: f"{x:.1f}%")
                    df_display["percentual_em_obra"] = df_display["percentual_em_obra"].apply(lambda x: f"{x:.1f}%")
                    df_display["percentual_lancamento"] = df_display["percentual_lancamento"].apply(lambda x: f"{x:.1f}%")
                    
                    df_display.columns = [
                        "Construtora", "Projetos", "Total APTs",
                        "% Pronto", "% Em Obra", "% Lançamento/Futuro"
                    ]
                    
                    st.dataframe(df_display, use_container_width=True)
                    
                    # Insights
                    st.markdown("### 💡 Insights por Construtora")
                    if not df_construtoras_filt.empty:
                        top_construtora = df_construtoras_filt.loc[df_construtoras_filt["total_projetos"].idxmax()]
                        st.success(f"**🏆 Maior Volume:** {top_construtora['CONSTRUTORA']} com {int(top_construtora['total_projetos'])} projetos")
                        
                        if "percentual_em_obra" in df_construtoras_filt.columns:
                            mais_obras = df_construtoras_filt.loc[df_construtoras_filt["percentual_em_obra"].idxmax()]
                            st.info(f"**🔨 Mais Obras Ativas:** {mais_obras['CONSTRUTORA']} com {mais_obras['percentual_em_obra']:.1f}% em obra")
            else:
                st.warning("⚠️ Dados insuficientes para análise por construtora")
        
        # TAB 2: POR ZONA/BAIRRO
        with tab2:
            st.header("🗺️ Análise por Zona/Bairro")
            
            df_zonas = analisar_por_zona(df_prospeccao)
            
            if not df_zonas.empty:
                # Mapa de calor por zona
                col_map1, col_map2 = st.columns(2)
                
                with col_map1:
                    fig_zona = px.bar(
                        df_zonas,
                        x="ZONA",
                        y="total_projetos",
                        color="total_projetos",
                        color_continuous_scale="Reds",
                        title="Projetos por Zona",
                        text="total_projetos"
                    )
                    fig_zona.update_traces(texttemplate='%{text}', textposition='outside')
                    fig_zona.update_layout(height=400)
                    st.plotly_chart(fig_zona, use_container_width=True)
                
                with col_map2:
                    fig_oportunidades = px.bar(
                        df_zonas,
                        x="ZONA",
                        y="oportunidades",
                        color="percentual_oportunidades",
                        color_continuous_scale="Greens",
                        title="Oportunidades por Zona",
                        text="oportunidades"
                    )
                    fig_oportunidades.update_traces(texttemplate='%{text}', textposition='outside')
                    fig_oportunidades.update_layout(height=400)
                    st.plotly_chart(fig_oportunidades, use_container_width=True)
                
                # Análise por bairro
                if "BAIRRO" in df_prospeccao.columns:
                    st.markdown("### 📍 Top 15 Bairros com Mais Projetos")
                    bairros_stats = df_prospeccao.groupby("BAIRRO").agg(
                        total_projetos=("NOME", "count"),
                        total_apartamentos=("APTO", lambda x: pd.to_numeric(x, errors='coerce').sum())
                    ).reset_index().sort_values("total_projetos", ascending=False).head(15)
                    
                    fig_bairro = px.bar(
                        bairros_stats,
                        x="total_projetos",
                        y="BAIRRO",
                        orientation="h",
                        title="Top 15 Bairros",
                        color="total_projetos",
                        color_continuous_scale="Blues"
                    )
                    fig_bairro.update_layout(height=500, yaxis={"categoryorder": "total ascending"})
                    st.plotly_chart(fig_bairro, use_container_width=True)
                
                # Tabela de zonas
                st.markdown("### 📋 Tabela de Zonas")
                df_zonas_display = df_zonas.copy()
                df_zonas_display["total_apartamentos"] = df_zonas_display["total_apartamentos"].apply(lambda x: formatar_numero_br(int(x)))
                df_zonas_display["percentual_em_obra"] = df_zonas_display["percentual_em_obra"].apply(lambda x: f"{x:.1f}%")
                df_zonas_display["percentual_oportunidades"] = df_zonas_display["percentual_oportunidades"].apply(lambda x: f"{x:.1f}%")
                
                df_zonas_display.columns = [
                    "Zona", "Projetos", "Total APTs", "Em Obra", "% Em Obra",
                    "Pronto", "Oportunidades", "% Oportunidades"
                ]
                
                st.dataframe(df_zonas_display, use_container_width=True)
            else:
                st.warning("⚠️ Dados insuficientes para análise por zona")
        
        # TAB 3: TIMELINE DE ENTREGAS
        with tab3:
            st.header("⏱️ Timeline de Entregas")
            
            df_timeline = timeline_entregas(df_prospeccao)
            
            if not df_timeline.empty and "PREVISAO_ENTREGA" in df_timeline.columns:
                # Filtro por ano
                anos_disp = sorted(df_timeline["ANO_ENTREGA"].dropna().unique())
                ano_sel = st.selectbox("Filtrar por Ano de Entrega", options=anos_disp, index=len(anos_disp)-1 if len(anos_disp) > 0 else 0)
                
                df_timeline_filt = df_timeline[df_timeline["ANO_ENTREGA"] == ano_sel]
                
                # Timeline horizontal
                st.markdown(f"### 📅 Entregas Previstas para {int(ano_sel)}")
                
                if len(df_timeline_filt) > 0:
                    # Agrupar por mês
                    entregas_por_mes = df_timeline_filt.groupby("MES_ENTREGA").agg(
                        total_projetos=("NOME", "count"),
                        total_apartamentos=("APTO", lambda x: pd.to_numeric(x, errors='coerce').sum())
                    ).reset_index()
                    entregas_por_mes["MES_ENTREGA"] = entregas_por_mes["MES_ENTREGA"].astype(str)
                    
                    fig_timeline = px.bar(
                        entregas_por_mes,
                        x="MES_ENTREGA",
                        y="total_projetos",
                        color="total_apartamentos",
                        title=f"Distribuição de Entregas por Mês ({int(ano_sel)})",
                        labels={"MES_ENTREGA": "Mês", "total_projetos": "Nº de Projetos", "total_apartamentos": "Total de APTs"}
                    )
                    fig_timeline.update_layout(height=400)
                    st.plotly_chart(fig_timeline, use_container_width=True)
                    
                    # Lista de entregas próximas
                    st.markdown("### 🚨 Entregas Próximas (Próximos 90 dias)")
                    entregas_proximas = df_timeline[df_timeline["DIAS_RESTANTES"] <= 90].sort_values("DIAS_RESTANTES")
                    
                    if len(entregas_proximas) > 0:
                        for _, row in entregas_proximas.head(10).iterrows():
                            dias = int(row["DIAS_RESTANTES"]) if pd.notna(row["DIAS_RESTANTES"]) else 0
                            cor = "🔴" if dias <= 30 else "🟠" if dias <= 60 else "🟡"
                            st.markdown(f"{cor} **{row['NOME']}** ({row['CONSTRUTORA']}) - {row['BAIRRO']} - Entrega em {dias} dias ({safe_strftime(row['PREVISAO_ENTREGA'])})")
                    else:
                        st.info("ℹ️ Nenhuma entrega prevista para os próximos 90 dias")
                    
                    # Tabela completa de entregas
                    with st.expander("📋 Ver Todas as Entregas de " + str(int(ano_sel))):
                        df_timeline_display = df_timeline_filt[[
                            "NOME", "CONSTRUTORA", "BAIRRO", "APTO", "PREVISAO_ENTREGA", "DIAS_RESTANTES"
                        ]].copy()
                        df_timeline_display["APTO"] = df_timeline_display["APTO"].apply(lambda x: formatar_numero_br(int(x)) if pd.notna(x) else "N/A")
                        df_timeline_display["PREVISAO_ENTREGA"] = df_timeline_display["PREVISAO_ENTREGA"].apply(lambda x: safe_strftime(x))
                        df_timeline_display["DIAS_RESTANTES"] = df_timeline_display["DIAS_RESTANTES"].apply(lambda x: f"{int(x)} dias" if pd.notna(x) else "N/A")
                        df_timeline_display.columns = ["Condomínio", "Construtora", "Bairro", "APTs", "Previsão", "Dias Restantes"]
                        st.dataframe(df_timeline_display, use_container_width=True)
                else:
                    st.info(f"ℹ️ Nenhuma entrega prevista para {int(ano_sel)}")
            else:
                st.warning("⚠️ Dados de previsão de entrega não disponíveis")
        
        # TAB 4: PRIORIZAÇÃO
        with tab4:
            st.header("🎯 Priorização de Ações")
            
            if "PRIORIDADE" in df_prospeccao.columns:
                # Distribuição de prioridades
                col_pri1, col_pri2 = st.columns(2)
                
                with col_pri1:
                    prioridade_counts = df_prospeccao["PRIORIDADE"].value_counts()
                    fig_pri = px.pie(
                        values=prioridade_counts.values,
                        names=prioridade_counts.index,
                        title="Distribuição de Prioridades",
                        color=prioridade_counts.index,
                        color_discrete_map={
                            "🔴 Urgente": "#e74c3c",
                            "🟠 Alta": "#e67e22",
                            "🟡 Média": "#f1c40f",
                            "🟢 Planejamento": "#2ecc71",
                            "⚪ Baixa": "#95a5a6"
                        }
                    )
                    st.plotly_chart(fig_pri, use_container_width=True)
                
                with col_pri2:
                    # Filtro por prioridade
                    prioridades_disp = df_prospeccao["PRIORIDADE"].unique().tolist()
                    prioridade_sel = st.multiselect(
                        "Filtrar por Prioridade",
                        options=prioridades_disp,
                        default=["🔴 Urgente", "🟠 Alta"],
                        key="prioridade_filter"
                    )
                    
                    if prioridade_sel:
                        df_prioridade = df_prospeccao[df_prospeccao["PRIORIDADE"].isin(prioridade_sel)]
                        
                        st.metric(
                            "Projetos Prioritários",
                            formatar_numero_br(len(df_prioridade)),
                            help="Projetos que requerem ação imediata"
                        )
                
                # Lista de projetos prioritários
                st.markdown("### 📋 Projetos Prioritários para Ação")
                
                if prioridade_sel:
                    df_prioridade_display = df_prioridade[[
                        "NOME", "CONSTRUTORA", "BAIRRO", "ZONA", "FASE_CLASSIFICADA",
                        "APTO", "PRIORIDADE", "DIAS_RESTANTES", "VIABILIDADE"
                    ]].copy()
                    
                    df_prioridade_display["APTO"] = df_prioridade_display["APTO"].apply(lambda x: formatar_numero_br(int(x)) if pd.notna(x) else "N/A")
                    df_prioridade_display["DIAS_RESTANTES"] = df_prioridade_display["DIAS_RESTANTES"].apply(lambda x: f"{int(x)} dias" if pd.notna(x) else "N/A")
                    
                    df_prioridade_display.columns = [
                        "Condomínio", "Construtora", "Bairro", "Zona", "Fase",
                        "APTs", "Prioridade", "Tempo Restante", "Observações"
                    ]
                    
                    st.dataframe(df_prioridade_display, use_container_width=True)
                    
                    # Exportar lista prioritária
                    excel_buffer = io.BytesIO()
                    with pd.ExcelWriter(excel_buffer, engine='openpyxl') as writer:
                        df_prioridade_display.to_excel(writer, sheet_name='Prioritários', index=False)
                    excel_buffer.seek(0)
                    
                    st.download_button(
                        label="📥 Exportar Lista Prioritária (Excel)",
                        data=excel_buffer,
                        file_name=f"prospeccao_prioritarios_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx",
                        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                        use_container_width=True
                    )
            else:
                st.warning("⚠️ Dados de prioridade não disponíveis")
        
        # TAB 5: LISTA COMPLETA
        with tab5:
            st.header("📋 Lista Completa de Projetos")
            
            # Filtros
            col_f1, col_f2, col_f3, col_f4 = st.columns(4)
            
            with col_f1:
                zonas_disp = df_prospeccao["ZONA"].dropna().unique().tolist() if "ZONA" in df_prospeccao.columns else []
                zona_sel = st.multiselect("Zona", options=zonas_disp, key="lista_zona")
            
            with col_f2:
                construtoras_disp = df_prospeccao["CONSTRUTORA"].dropna().unique().tolist() if "CONSTRUTORA" in df_prospeccao.columns else []
                construtora_sel = st.multiselect("Construtora", options=construtoras_disp, key="lista_construtora")
            
            with col_f3:
                fases_disp = df_prospeccao["FASE_CLASSIFICADA"].dropna().unique().tolist() if "FASE_CLASSIFICADA" in df_prospeccao.columns else []
                fase_sel = st.multiselect("Fase", options=fases_disp, key="lista_fase")
            
            with col_f4:
                prioridades_disp = df_prospeccao["PRIORIDADE"].dropna().unique().tolist() if "PRIORIDADE" in df_prospeccao.columns else []
                prioridade_sel = st.multiselect("Prioridade", options=prioridades_disp, key="lista_prioridade")
            
            # Aplicar filtros
            df_filt = df_prospeccao.copy()
            if zona_sel:
                df_filt = df_filt[df_filt["ZONA"].isin(zona_sel)]
            if construtora_sel:
                df_filt = df_filt[df_filt["CONSTRUTORA"].isin(construtora_sel)]
            if fase_sel:
                df_filt = df_filt[df_filt["FASE_CLASSIFICADA"].isin(fase_sel)]
            if prioridade_sel:
                df_filt = df_filt[df_filt["PRIORIDADE"].isin(prioridade_sel)]
            
            st.markdown(f"### 📊 {len(df_filt)} projetos encontrados")
            
            # Colunas para exibição
            colunas_display = ["NOME", "CONSTRUTORA", "BAIRRO", "ZONA", "FASE_CLASSIFICADA", "APTO", "PRIORIDADE"]
            colunas_existentes = [c for c in colunas_display if c in df_filt.columns]
            
            df_lista = df_filt[colunas_existentes].copy()
            
            # Formatar
            if "APTO" in df_lista.columns:
                df_lista["APTO"] = df_lista["APTO"].apply(lambda x: formatar_numero_br(int(x)) if pd.notna(x) else "N/A")
            
            # Nomes das colunas em português
            col_names = {
                "NOME": "Condomínio",
                "CONSTRUTORA": "Construtora",
                "BAIRRO": "Bairro",
                "ZONA": "Zona",
                "FASE_CLASSIFICADA": "Fase",
                "APTO": "APTs",
                "PRIORIDADE": "Prioridade"
            }
            df_lista = df_lista.rename(columns={k: v for k, v in col_names.items() if k in df_lista.columns})
            
            st.dataframe(df_lista, use_container_width=True)
            
            # Exportar lista completa
            excel_buffer = exportar_prospeccao_excel(df_filt, analisar_por_construtora(df_filt), analisar_por_zona(df_filt))
            st.download_button(
                label="📥 Exportar Lista Completa (Excel)",
                data=excel_buffer,
                file_name=f"prospeccao_completa_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                use_container_width=True
            )
        
        st.markdown("---")
        
        # ==================== RODAPÉ ====================
        st.markdown("""
        ### 💡 Como usar este módulo:
        
        | Aba | Finalidade | Ação Recomendada |
        |-----|-----------|-----------------|
        | 📊 Por Construtora | Entender volume e fases por parceiro | Focar em construtoras com mais entregas em 2025 |
        | 🗺️ Por Zona/Bairro | Identificar regiões com mais oportunidades | Priorizar zonas com maior % de oportunidades |
        | ⏱️ Timeline | Planejar ações baseadas em datas de entrega | Agendar visitas 60-90 dias antes da entrega |
        | 🎯 Priorização | Focar nos projetos mais críticos | Ação imediata em projetos 🔴 Urgente |
        | 📋 Lista Completa | Visão geral e exportação | Filtrar e exportar para equipe de campo |
        """)
    else:
        st.info("👆 Faça upload da planilha para visualizar os dados")

if __name__ == "__main__":
    render_prospeccao_condominios()
