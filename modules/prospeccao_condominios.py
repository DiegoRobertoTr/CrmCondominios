import streamlit as st
import pandas as pd
import numpy as np
import plotly.express as px
import plotly.graph_objects as go
from datetime import datetime, timezone, date
from pymongo import MongoClient
from pymongo.errors import ServerSelectionTimeoutError, ConnectionFailure
from urllib.parse import quote_plus
import io
import re
import calendar

# ==================== FUNÇÕES UTILITÁRIAS OTIMIZADAS ====================

def limpar_valor_data(valor):
    """Limpa e converte valores de data com tratamento robusto"""
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
            valor_dt = pd.to_datetime(valor_limpo, errors='coerce', dayfirst=True)
            if pd.isna(valor_dt):
                return None
            return valor_dt.to_pydatetime().replace(tzinfo=None)
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

def converter_dataframe_dates(df, colunas_alvo=None):
    """Converte apenas colunas específicas ou detectadas como data"""
    df = df.copy()
    
    # Se não houver lista específica, tenta detectar pelo nome (mas de forma mais segura)
    if colunas_alvo is None:
        colunas_alvo = []
        palavras_chave = ['data', 'date', 'cadastro', 'entrega', 'previsao', 'atualizacao']
        for col in df.columns:
            col_lower = col.lower()
            if any(palavra in col_lower for palavra in palavras_chave):
                colunas_alvo.append(col)
            elif pd.api.types.is_datetime64_any_dtype(df[col]):
                colunas_alvo.append(col)

    for col in colunas_alvo:
        if col in df.columns:
            try:
                # Conversão direta vetorializada é mais rápida que apply linha a linha
                df[col] = pd.to_datetime(df[col], errors='coerce', dayfirst=True)
                # Aplica limpeza apenas nos valores válidos para garantir tzinfo None
                df[col] = df[col].apply(lambda x: limpar_valor_data(x) if pd.notna(x) else None)
            except Exception:
                pass # Ignora falhas silenciosamente para não travar o upload
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
st.set_page_config(page_title="️ Prospecção de Condomínios", layout="wide")

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

# ✅ CORREÇÃO CRÍTICA 1: Limpeza preventiva antes do insert para evitar duplicatas
def save_prospeccao_data(db, df_prospeccao, metadata):
    """Salva dados de prospecção no MongoDB garantindo integridade do batch"""
    collection = db["prospeccao_condominios"]
    meta_collection = db["prospeccao_meta"]
    
    batch_id = metadata["batch_id"]
    
    # 1. LIMPEZA PREVENTIVA: Remove dados de imports anteriores com o mesmo batch_id
    # Isso garante que reenviar a mesma planilha substitua os dados, não duplique
    delete_result = collection.delete_many({"_import_batch": batch_id})
    meta_collection.delete_many({"batch_id": batch_id})
    
    if delete_result.deleted_count > 0:
        st.info(f"⚠️ {delete_result.deleted_count} registros antigos do mesmo lote removidos.")

    # Preparação dos dados
    # Definimos explicitamente quais colunas são datas para otimizar a conversão
    cols_data = ["PREVISAO_ENTREGA", "Data da Atualização", "Previsão de Entrega"] 
    # Adiciona colunas que possam existir no DF original
    cols_data.extend([c for c in df_prospeccao.columns if 'data' in c.lower() or 'date' in c.lower()])
    
    df_limpo = converter_dataframe_dates(df_prospeccao, colunas_alvo=list(set(cols_data)))
    
    docs = []
    for _, row in df_limpo.iterrows():
        doc = row.to_dict()
        # Sanitização para MongoDB
        for key, value in list(doc.items()):
            if isinstance(value, (pd.Timestamp, datetime)):
                doc[key] = limpar_valor_data(value)
            elif pd.isna(value):
                doc[key] = None
            elif isinstance(value, (pd.Series, pd.DataFrame)):
                doc[key] = str(value)
        
        doc["_import_timestamp"] = datetime.now().replace(tzinfo=None)
        doc["_import_batch"] = batch_id
        docs.append(doc)

    if docs:
        collection.insert_many(docs)

    # Salva metadados
    meta_collection.insert_one({
        "batch_id": batch_id,
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
    # Busca apenas pelo batch_id mais recente
    cursor = collection.find({"_import_batch": meta["batch_id"]})
    df_prospeccao = pd.DataFrame(list(cursor))
    
    if "_id" in df_prospeccao.columns:
        df_prospeccao = df_prospeccao.drop(columns=["_id"])
    
    # Converte datas básicas, mas NÃO recalcula colunas derivadas aqui (fazemos isso na UI com cache)
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

# ==================== FUNÇÕES DE ANÁLISE (Lógica de Negócio) ====================

def classificar_fase(fase_str):
    """Classifica a fase do projeto em categorias padronizadas"""
    if pd.isna(fase_str):
        return "Não Informado"
    fase_lower = str(fase_str).lower().strip()
    
    if any(x in fase_lower for x in ["pronto", "entregue", "finalizado", "pronto para morar"]):
        return "✅ Pronto"
    elif any(x in fase_lower for x in ["final de obra", "fase final", "acabamento", "estágio final", "estagio final"]):
        return "🏁 Final de Obra"
    elif any(x in fase_lower for x in ["intermediário", "intermediario", "intermed.", "avançado", "avancado", "50%", "60%", "70%"]):
        return "🔨 Intermediário"
    elif any(x in fase_lower for x in ["início de obra", "inicio de obra", "inicial", "fundação", "estrutura", "obra em andamento"]):
        return "🚧 Início de Obra"
    elif any(x in fase_lower for x in ["lançamento", "lancamento", "vendas", "grupo em formação"]):
        return "📢 Lançamento"
    elif any(x in fase_lower for x in ["futuro", "planejado", "terreno", "futuro lançamento"]):
        return "📅 Futuro Lançamento"
    elif any(x in fase_lower for x in ["não entramos", "perdido", "embargado", "sem viabilidade", "não autorizado"]):
        return "❌ Não Entramos"
    else:
        return "📋 Em Tratativa"

def extrair_previsao_entrega(viabilidade_str):
    """Extrai data de previsão de entrega da coluna de viabilidade/obs"""
    if isinstance(viabilidade_str, (pd.Series, pd.DataFrame)):
        return None
    if pd.isna(viabilidade_str):
        return None

    viabilidade_str = str(viabilidade_str)
    
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
                if len(data_str) == 5:  # 12/24 -> 01/12/24
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

    construtora_stats["percentual_pronto"] = (construtora_stats["projetos_pronto"] / construtora_stats["total_projetos"] * 100).round(1)
    construtora_stats["percentual_em_obra"] = ((construtora_stats["projetos_final_obra"] + construtora_stats["projetos_intermediario"] + construtora_stats["projetos_inicio_obra"]) / construtora_stats["total_projetos"] * 100).round(1)
    construtora_stats["percentual_lancamento"] = ((construtora_stats["projetos_lancamento"] + construtora_stats["projetos_futuro"]) / construtora_stats["total_projetos"] * 100).round(1)

    return construtora_stats.sort_values("total_projetos", ascending=False).reset_index(drop=True)

def analisar_por_zona(df_prospeccao):
    """Análise consolidada por Zona/Região"""
    if df_prospeccao.empty:
        return pd.DataFrame()
    
    col_zona = "Região" if "Região" in df_prospeccao.columns else "ZONA" if "ZONA" in df_prospeccao.columns else None
    if not col_zona:
        return pd.DataFrame()

    zona_stats = df_prospeccao.groupby(col_zona).agg(
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
    
    # Garante que a coluna de previsão exista e seja datetime
    if "PREVISAO_ENTREGA" not in df_timeline.columns:
        df_timeline["PREVISAO_ENTREGA"] = None
    else:
        df_timeline["PREVISAO_ENTREGA"] = pd.to_datetime(df_timeline["PREVISAO_ENTREGA"], errors='coerce')

    df_timeline = df_timeline[df_timeline["PREVISAO_ENTREGA"].notna()]
    if df_timeline.empty:
        return df_timeline

    df_timeline["DIAS_RESTANTES"] = df_timeline["PREVISAO_ENTREGA"].apply(calcular_dias_para_entrega)
    df_timeline["ANO_ENTREGA"] = df_timeline["PREVISAO_ENTREGA"].dt.year
    df_timeline["MES_ENTREGA"] = df_timeline["PREVISAO_ENTREGA"].dt.to_period('M')
    return df_timeline.sort_values("PREVISAO_ENTREGA")

def calcular_prioridade(row):
    """Calcula prioridade de ação baseado em fase e tempo"""
    fase = row.get("FASE_CLASSIFICADA", "")
    dias = row.get("DIAS_RESTANTES", None)
    
    if fase in ["✅ Pronto", "🏁 Final de Obra"]:
        if dias is not None and dias <= 90:
            return " Urgente"
        elif dias is not None and dias <= 180:
            return "🟠 Alta"
        else:
            return "🟡 Média"
    elif fase in ["🔨 Intermediário", "🚧 Início de Obra"]:
        if dias is not None and dias <= 365:
            return "🟠 Alta"
        else:
            return " Média"
    elif fase in ["📢 Lançamento", " Futuro Lançamento"]:
        return "🟢 Planejamento"
    else:
        return "⚪ Baixa"

def exportar_prospeccao_excel(df_prospeccao, df_construtoras, df_zonas):
    """Exporta dados de prospecção para Excel com abas por fase"""
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        df_prospeccao.to_excel(writer, sheet_name='Completo', index=False)
        
        fases_map = {
            '✅ Pronto': 'Pronto', ' Final de Obra': 'Final de Obra',
            ' Intermediário': 'Intermediario', '🚧 Início de Obra': 'Inicio de Obra',
            '📢 Lançamento': 'Lancamento', ' Futuro Lançamento': 'Futuro Lancamento',
            '❌ Não Entramos': 'Nao Entramos', ' Em Tratativa': 'Em Tratativa'
        }

        for fase_padrao, nome_aba in fases_map.items():
            df_fase = df_prospeccao[df_prospeccao["FASE_CLASSIFICADA"] == fase_padrao]
            if not df_fase.empty:
                nome_aba = nome_aba[:31]
                df_fase.to_excel(writer, sheet_name=nome_aba, index=False)

        if not df_construtoras.empty:
            df_construtoras.to_excel(writer, sheet_name='Por Construtora', index=False)
        if not df_zonas.empty:
            df_zonas.to_excel(writer, sheet_name='Por Regiao', index=False)

    output.seek(0)
    return output

# ==================== INTERFACE STREAMLIT ====================

def render_prospeccao_condominios():
    st.title("🏗️ Prospecção de Condomínios")
    st.markdown("Acompanhamento de fases de construção por construtora e oportunidades de mercado")
    db = init_mongo()
    st.markdown("---")

    # ==================== GERENCIAMENTO DE DADOS ====================
    st.subheader("️ Gerenciamento de Dados")
    col1, col2 = st.columns([3, 1])

    with col1:
        uploaded_file = st.file_uploader(
            " Importar Planilha de Prospecção", 
            type=["xlsx", "xls"], 
            help="Planilha com colunas: Região, BAIRRO, ENDEREÇO, NOME, BLOCO, APTO, CONSTRUTORA, ESTÁGIO, VIABILIDADE, OBS"
        )
    with col2:
        if st.button("🔄 Recarregar Últimos", type="primary", use_container_width=True):
            st.session_state["reload_prospeccao"] = True
            st.rerun()
            
        if st.button("🗑️ Limpar Dados", type="secondary", use_container_width=True):
            if st.session_state.get("confirm_delete_prospeccao"):
                deleted = clear_prospeccao_data(db)
                st.success(f"✅ {deleted} registros removidos!")
                st.session_state["confirm_delete_prospeccao"] = False
                if "df_prospeccao_cached" in st.session_state:
                    del st.session_state["df_prospeccao_cached"]
                st.rerun()
            else:
                st.warning("⚠️ Clique novamente para confirmar")
                st.session_state["confirm_delete_prospeccao"] = True

    # Carregar metadados rápidos
    meta = db["prospeccao_meta"].find_one(sort=[("timestamp", -1)])
    if meta:
        ts = meta.get('timestamp')
        ts_str = safe_strftime(ts, "%d/%m/%Y %H:%M") if ts else "Data não disponível"
        st.info(f"""
        **Última Importação:**
        -  {ts_str}
        - ️ {meta['total_projetos']} projetos
        - 🏢 {len(meta.get('construtoras', []))} construtoras
        """)
    else:
        st.warning("⚠️ Nenhum dado importado ainda")

    st.markdown("---")
    df_prospeccao, meta = None, None

    # ==================== IMPORTAÇÃO DA PLANILHA ====================
    if uploaded_file:
        try:
            df_prospeccao = pd.read_excel(uploaded_file, sheet_name=0)

            # Verificar cabeçalho duplicado
            if len(df_prospeccao) > 0:
                primeira_linha = df_prospeccao.iloc[0].astype(str).str.lower()
                colunas_lower = [c.lower() for c in df_prospeccao.columns]
                if all(val in colunas_lower or val == 'nan' for val in primeira_linha):
                    df_prospeccao = df_prospeccao.iloc[1:].reset_index(drop=True)

            if len(df_prospeccao) > 0:
                col_mapping = {
                    'região': 'Região', 'zona': 'Região', 'bairro': 'BAIRRO',
                    'endereço': 'ENDEREÇO', 'endereco': 'ENDEREÇO', 'nome': 'NOME',
                    'condomínio': 'NOME', 'condominio': 'NOME', 'bloco': 'BLOCO',
                    'apto': 'APTO', 'apartamentos': 'APTO', 'construtora': 'CONSTRUTORA',
                    'estágio': 'ESTÁGIO', 'estagio': 'ESTÁGIO', 'viabilidade': 'VIABILIDADE',
                    'obs': 'OBS', 'observações': 'OBS', 'data da atualização': 'Data da Atualização',
                    'previsão de entrega': 'Previsão de Entrega'
                }

                df_prospeccao.columns = [str(col).strip() for col in df_prospeccao.columns]
                df_prospeccao = df_prospeccao.rename(columns={k: v for k, v in col_mapping.items() if k in [c.lower() for c in df_prospeccao.columns]})

                if "ESTÁGIO" not in df_prospeccao.columns:
                    st.error("❌ Coluna 'ESTÁGIO' não encontrada na planilha!")
                    st.stop()

                # Processamento inicial (apenas o necessário para salvar)
                df_prospeccao["FASE_CLASSIFICADA"] = df_prospeccao["ESTÁGIO"].apply(classificar_fase)
                df_prospeccao["FASE_ORIGINAL"] = df_prospeccao["ESTÁGIO"]
                
                # Extrair datas
                if "VIABILIDADE" in df_prospeccao.columns:
                    df_prospeccao["PREVISAO_ENTREGA"] = df_prospeccao["VIABILIDADE"].apply(extrair_previsao_entrega)
                if "Previsão de Entrega" in df_prospeccao.columns:
                    df_prospeccao["PREVISAO_ENTREGA_2"] = df_prospeccao["Previsão de Entrega"].apply(extrair_previsao_entrega)
                    df_prospeccao["PREVISAO_ENTREGA"] = df_prospeccao.apply(
                        lambda row: row["PREVISAO_ENTREGA"] if pd.notna(row["PREVISAO_ENTREGA"]) else row.get("PREVISAO_ENTREGA_2"), 
                        axis=1
                    )
                
                df_prospeccao["DIAS_RESTANTES"] = df_prospeccao["PREVISAO_ENTREGA"].apply(calcular_dias_para_entrega)
                df_prospeccao["PRIORIDADE"] = df_prospeccao.apply(calcular_prioridade, axis=1)

                fases_count = df_prospeccao["FASE_CLASSIFICADA"].value_counts().to_dict()
                metadata = {
                    "timestamp": datetime.now().replace(tzinfo=None),
                    "batch_id": f"prospeccao_{datetime.now().strftime('%Y%m%d_%H%M%S')}",
                    "filename": uploaded_file.name,
                    "fases": fases_count,
                    "construtoras": df_prospeccao["CONSTRUTORA"].dropna().unique().tolist() if "CONSTRUTORA" in df_prospeccao.columns else []
                }

                if save_prospeccao_data(db, df_prospeccao, metadata):
                    st.success(f"✅ Dados importados! {len(df_prospeccao)} projetos de {len(metadata['construtoras'])} construtoras")
                    # Limpa cache para forçar recarga limpa
                    if "df_prospeccao_cached" in st.session_state:
                        del st.session_state["df_prospeccao_cached"]
                    st.rerun()
        except Exception as e:
            st.error(f"❌ Erro ao processar planilha: {str(e)}")
            import traceback
            st.expander("Detalhes técnicos do erro").code(traceback.format_exc())

    # ==================== CARREGAMENTO OTIMIZADO (CACHE) ====================
    elif st.session_state.get("reload_prospeccao") or "df_prospeccao_cached" not in st.session_state:
        with st.spinner('🔄 Carregando dados do banco...'):
            result = load_latest_prospeccao(db)
            if result[0] is not None:
                df_prospeccao, meta = result
                
                # ✅ PERFORMANCE BOOST: Só recalcula se as colunas não existirem
                # Se vieram do banco já calculadas, pula essa etapa pesada
                if "FASE_CLASSIFICADA" not in df_prospeccao.columns and "ESTÁGIO" in df_prospeccao.columns:
                    df_prospeccao["FASE_CLASSIFICADA"] = df_prospeccao["ESTÁGIO"].apply(classificar_fase)
                
                if "PREVISAO_ENTREGA" not in df_prospeccao.columns:
                     if "VIABILIDADE" in df_prospeccao.columns:
                        df_prospeccao["PREVISAO_ENTREGA"] = df_prospeccao["VIABILIDADE"].apply(extrair_previsao_entrega)
                
                if "DIAS_RESTANTES" not in df_prospeccao.columns and "PREVISAO_ENTREGA" in df_prospeccao.columns:
                    df_prospeccao["DIAS_RESTANTES"] = df_prospeccao["PREVISAO_ENTREGA"].apply(calcular_dias_para_entrega)
                    
                if "PRIORIDADE" not in df_prospeccao.columns:
                    df_prospeccao["PRIORIDADE"] = df_prospeccao.apply(calcular_prioridade, axis=1)

                st.session_state["df_prospeccao_cached"] = df_prospeccao
                st.session_state["meta_cached"] = meta
                st.success("📦 Dados carregados e otimizados!")
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
        
        # Cálculos seguros para KPIs
        fases_em_obra = ["🏁 Final de Obra", "🔨 Intermediário", "🚧 Início de Obra"]
        projetos_em_obra = len(df_prospeccao[df_prospeccao["FASE_CLASSIFICADA"].isin(fases_em_obra)]) if "FASE_CLASSIFICADA" in df_prospeccao.columns else 0
        
        entregas_2025 = 0
        if "PREVISAO_ENTREGA" in df_prospeccao.columns:
             df_2025 = df_prospeccao[pd.to_datetime(df_prospeccao["PREVISAO_ENTREGA"], errors='coerce').dt.year == 2025]
             entregas_2025 = len(df_2025)
             
        oportunidades_imediatas = len(df_prospeccao[df_prospeccao["PRIORIDADE"] == "🔴 Urgente"]) if "PRIORIDADE" in df_prospeccao.columns else 0

        col1.metric("🏗️ Total de Projetos", formatar_numero_br(total_projetos))
        col2.metric("🏠 Total de Apartamentos", formatar_numero_br(int(total_apartamentos)))
        col3.metric("🔨 Em Obra", formatar_numero_br(projetos_em_obra))
        col4.metric("📅 Entregas 2025", formatar_numero_br(entregas_2025))
        col5.metric("🔴 Oportunidades Imediatas", formatar_numero_br(oportunidades_imediatas))

        st.markdown("---")

        # ==================== ABAS DE ANÁLISE ====================
        tab1, tab2, tab3, tab4, tab5 = st.tabs([
            "📊 Por Construtora", "🗺️ Por Região", "⏱️ Timeline de Entregas", 
            "🎯 Priorização", "📋 Lista Completa"
        ])

        # TAB 1: POR CONSTRUTORA
        with tab1:
            st.header("🏢 Análise por Construtora")
            df_construtoras = analisar_por_construtora(df_prospeccao)

            if not df_construtoras.empty:
                construtoras_disp = df_construtoras["CONSTRUTORA"].dropna().unique().tolist()
                default_construtoras = construtoras_disp[:5] if len(construtoras_disp) >= 5 else construtoras_disp
                
                construtoras_sel = st.multiselect(
                    "Filtrar Construtoras", options=construtoras_disp, default=default_construtoras, key="construtoras_filter"
                )

                if construtoras_sel:
                    df_construtoras_filt = df_construtoras[df_construtoras["CONSTRUTORA"].isin(construtoras_sel)]
                    
                    col_chart1, col_chart2 = st.columns(2)
                    with col_chart1:
                        fig1 = px.bar(df_construtoras_filt.head(10), x="total_projetos", y="CONSTRUTORA", orientation="h", title="Top 10 por Projetos", color="total_projetos", color_continuous_scale="Blues")
                        fig1.update_layout(height=400, yaxis={"categoryorder": "total ascending"})
                        st.plotly_chart(fig1, use_container_width=True)

                    with col_chart2:
                        fig2 = px.bar(df_construtoras_filt.head(10), x="total_apartamentos", y="CONSTRUTORA", orientation="h", title="Top 10 por APTs", color="total_apartamentos", color_continuous_scale="Greens")
                        fig2.update_layout(height=400, yaxis={"categoryorder": "total ascending"})
                        st.plotly_chart(fig2, use_container_width=True)

                    st.markdown("###  Composição de Fases por Construtora")
                    fases_cols = ["projetos_pronto", "projetos_final_obra", "projetos_intermediario", "projetos_inicio_obra", "projetos_lancamento", "projetos_futuro"]
                    fases_labels = ["✅ Pronto", "🏁 Final", " Intermed.", "🚧 Início", "📢 Lançam.", " Futuro"]

                    df_fases_plot = df_construtoras_filt.head(8).copy().set_index("CONSTRUTORA")[fases_cols]
                    df_fases_plot.columns = fases_labels

                    fig3 = px.bar(df_fases_plot, barmode="stack", title="Distribuição de Fases (Top 8)", color_discrete_sequence=px.colors.qualitative.Set3)
                    fig3.update_layout(height=500)
                    st.plotly_chart(fig3, use_container_width=True)

                    st.markdown("###  Tabela Detalhada")
                    df_display = df_construtoras_filt[["CONSTRUTORA", "total_projetos", "total_apartamentos", "percentual_pronto", "percentual_em_obra", "percentual_lancamento"]].copy()
                    df_display["total_apartamentos"] = df_display["total_apartamentos"].apply(lambda x: formatar_numero_br(int(x) if pd.notna(x) else 0))
                    df_display["percentual_pronto"] = df_display["percentual_pronto"].apply(lambda x: f"{x:.1f}%")
                    df_display["percentual_em_obra"] = df_display["percentual_em_obra"].apply(lambda x: f"{x:.1f}%")
                    df_display["percentual_lancamento"] = df_display["percentual_lancamento"].apply(lambda x: f"{x:.1f}%")
                    df_display.columns = ["Construtora", "Projetos", "Total APTs", "% Pronto", "% Em Obra", "% Lançamento/Futuro"]
                    st.dataframe(df_display, use_container_width=True)
            else:
                st.warning("️ Dados insuficientes para análise por construtora")

        # TAB 2: POR REGIÃO/ZONA
        with tab2:
            st.header("️ Análise por Região")
            df_zonas = analisar_por_zona(df_prospeccao)
            if not df_zonas.empty:
                col_zona = df_zonas.columns[0]
                col_map1, col_map2 = st.columns(2)
                with col_map1:
                    fig_zona = px.bar(df_zonas, x=col_zona, y="total_projetos", color="total_projetos", color_continuous_scale="Reds", title="Projetos por Região", text="total_projetos")
                    fig_zona.update_traces(texttemplate='%{text}', textposition='outside')
                    st.plotly_chart(fig_zona, use_container_width=True)
                with col_map2:
                    fig_oport = px.bar(df_zonas, x=col_zona, y="oportunidades", color="percentual_oportunidades", color_continuous_scale="Greens", title="Oportunidades por Região", text="oportunidades")
                    fig_oport.update_traces(texttemplate='%{text}', textposition='outside')
                    st.plotly_chart(fig_oport, use_container_width=True)
                
                if "BAIRRO" in df_prospeccao.columns:
                    st.markdown("### 📍 Top 15 Bairros")
                    bairros_stats = df_prospeccao.groupby("BAIRRO").agg(total_projetos=("NOME", "count")).reset_index().sort_values("total_projetos", ascending=False).head(15)
                    fig_bairro = px.bar(bairros_stats, x="total_projetos", y="BAIRRO", orientation="h", title="Top 15 Bairros", color="total_projetos", color_continuous_scale="Blues")
                    st.plotly_chart(fig_bairro, use_container_width=True)
                
                st.dataframe(df_zonas, use_container_width=True)
            else:
                st.warning("⚠️ Dados insuficientes para análise por região")

        # TAB 3: TIMELINE
        with tab3:
            st.header("️ Timeline de Entregas")
            df_timeline = timeline_entregas(df_prospeccao)
            if not df_timeline.empty and "PREVISAO_ENTREGA" in df_timeline.columns:
                anos_disp = sorted(df_timeline["ANO_ENTREGA"].dropna().unique().astype(int))
                if anos_disp:
                    ano_sel = st.selectbox("Filtrar por Ano de Entrega", options=anos_disp, index=len(anos_disp)-1)
                    df_timeline_filt = df_timeline[df_timeline["ANO_ENTREGA"] == ano_sel]
                    
                    st.markdown(f"### 📅 Entregas Previstas para {int(ano_sel)}")
                    if not df_timeline_filt.empty:
                        entregas_por_mes = df_timeline_filt.groupby("MES_ENTREGA").agg(total_projetos=("NOME", "count"), total_apartamentos=("APTO", lambda x: pd.to_numeric(x, errors='coerce').sum())).reset_index()
                        entregas_por_mes["MES_ENTREGA"] = entregas_por_mes["MES_ENTREGA"].astype(str)
                        
                        fig_timeline = px.bar(entregas_por_mes, x="MES_ENTREGA", y="total_projetos", color="total_apartamentos", title=f"Distribuição Mensal ({int(ano_sel)})")
                        st.plotly_chart(fig_timeline, use_container_width=True)
                        
                        st.markdown("### 🚨 Próximos 90 dias")
                        entregas_proximas = df_timeline[df_timeline["DIAS_RESTANTES"] <= 90].sort_values("DIAS_RESTANTES")
                        if not entregas_proximas.empty:
                            for _, row in entregas_proximas.head(10).iterrows():
                                dias = int(row["DIAS_RESTANTES"]) if pd.notna(row["DIAS_RESTANTES"]) else 0
                                cor = "🔴" if dias <= 30 else "" if dias <= 60 else "🟡"
                                st.markdown(f"{cor} **{row['NOME']}** ({row.get('CONSTRUTORA', 'N/A')}) - {row.get('BAIRRO', '')} - {dias} dias")
                        else:
                            st.info("ℹ️ Nenhuma entrega nos próximos 90 dias")
                        
                        with st.expander("📋 Ver Todas as Entregas de " + str(int(ano_sel))):
                            cols_disp = ["NOME", "CONSTRUTORA", "BAIRRO", "APTO", "PREVISAO_ENTREGA", "DIAS_RESTANTES"]
                            cols_existentes = [c for c in cols_disp if c in df_timeline_filt.columns]
                            df_show = df_timeline_filt[cols_existentes].copy()
                            if "PREVISAO_ENTREGA" in df_show.columns: df_show["PREVISAO_ENTREGA"] = df_show["PREVISAO_ENTREGA"].apply(safe_strftime)
                            st.dataframe(df_show, use_container_width=True)
            else:
                st.warning("⚠️ Sem dados de previsão de entrega.")

        # TAB 4: PRIORIZAÇÃO
        with tab4:
            st.header("🎯 Priorização de Ações")
            if "PRIORIDADE" in df_prospeccao.columns:
                col_pri1, col_pri2 = st.columns(2)
                with col_pri1:
                    fig_pri = px.pie(values=df_prospeccao["PRIORIDADE"].value_counts().values, names=df_prospeccao["PRIORIDADE"].value_counts().index, title="Distribuição de Prioridades", color_discrete_map={"🔴 Urgente": "#e74c3c", " Alta": "#e67e22", " Média": "#f1c40f", "🟢 Planejamento": "#2ecc71", " Baixa": "#95a5a6"})
                    st.plotly_chart(fig_pri, use_container_width=True)
                
                with col_pri2:
                    prioridades_disp = df_prospeccao["PRIORIDADE"].unique().tolist()
                    valid_defaults = [p for p in ["🔴 Urgente", " Alta"] if p in prioridades_disp]
                    if not valid_defaults and prioridades_disp: valid_defaults = [prioridades_disp[0]]
                    
                    prioridade_sel = st.multiselect("Filtrar por Prioridade", options=prioridades_disp, default=valid_defaults, key="prioridade_filter")
                    if prioridade_sel:
                        df_prioridade = df_prospeccao[df_prospeccao["PRIORIDADE"].isin(prioridade_sel)]
                        st.metric("Projetos Prioritários", formatar_numero_br(len(df_prioridade)))
                        
                        st.markdown("### 📋 Lista de Ação")
                        cols_disp = ["NOME", "CONSTRUTORA", "BAIRRO", "FASE_CLASSIFICADA", "PRIORIDADE", "DIAS_RESTANTES"]
                        cols_existentes = [c for c in cols_disp if c in df_prioridade.columns]
                        df_show = df_prioridade[cols_existentes].copy()
                        if "DIAS_RESTANTES" in df_show.columns: df_show["DIAS_RESTANTES"] = df_show["DIAS_RESTANTES"].apply(lambda x: f"{int(x)} dias" if pd.notna(x) else "")
                        st.dataframe(df_show, use_container_width=True)
                        
                        # Exportação rápida
                        excel_buffer = io.BytesIO()
                        with pd.ExcelWriter(excel_buffer, engine='openpyxl') as writer:
                            df_show.to_excel(writer, index=False, sheet_name='Prioritários')
                        excel_buffer.seek(0)
                        st.download_button("📥 Exportar Lista Prioritária", excel_buffer, f"prioritarios_{datetime.now().strftime('%Y%m%d')}.xlsx", mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
            else:
                st.warning("⚠️ Dados de prioridade indisponíveis")

        # TAB 5: LISTA COMPLETA
        with tab5:
            st.header("📋 Lista Completa de Projetos")
            col_f1, col_f2, col_f3 = st.columns(3)
            
            col_regiao = "Região" if "Região" in df_prospeccao.columns else "ZONA" if "ZONA" in df_prospeccao.columns else None
            
            with col_f1:
                zonas_disp = df_prospeccao[col_regiao].dropna().unique().tolist() if col_regiao else []
                zona_sel = st.multiselect("Região", options=zonas_disp, key="lista_zona")
            with col_f2:
                construtoras_disp = df_prospeccao["CONSTRUTORA"].dropna().unique().tolist() if "CONSTRUTORA" in df_prospeccao.columns else []
                construtora_sel = st.multiselect("Construtora", options=construtoras_disp, key="lista_construtora")
            with col_f3:
                fases_disp = df_prospeccao["FASE_CLASSIFICADA"].dropna().unique().tolist() if "FASE_CLASSIFICADA" in df_prospeccao.columns else []
                fase_sel = st.multiselect("Fase", options=fases_disp, key="lista_fase")

            df_filt = df_prospeccao.copy()
            if zona_sel and col_regiao: df_filt = df_filt[df_filt[col_regiao].isin(zona_sel)]
            if construtora_sel: df_filt = df_filt[df_filt["CONSTRUTORA"].isin(construtora_sel)]
            if fase_sel: df_filt = df_filt[df_filt["FASE_CLASSIFICADA"].isin(fase_sel)]

            st.markdown(f"### 📊 {len(df_filt)} projetos encontrados")
            
            colunas_display = ["NOME", "CONSTRUTORA", "BAIRRO", "Região", "FASE_CLASSIFICADA", "APTO", "PRIORIDADE"]
            colunas_existentes = [c for c in colunas_display if c in df_filt.columns]
            df_lista = df_filt[colunas_existentes].copy()
            
            if "APTO" in df_lista.columns: df_lista["APTO"] = df_lista["APTO"].apply(lambda x: formatar_numero_br(int(x)) if pd.notna(x) else "N/A")
            
            col_names = {"NOME": "Condomínio", "CONSTRUTORA": "Construtora", "BAIRRO": "Bairro", "Região": "Região", "FASE_CLASSIFICADA": "Fase", "APTO": "APTs", "PRIORIDADE": "Prioridade"}
            df_lista = df_lista.rename(columns={k: v for k, v in col_names.items() if k in df_lista.columns})
            
            st.dataframe(df_lista, use_container_width=True)
            
            df_construtoras_resumo = analisar_por_construtora(df_filt)
            df_zonas_resumo = analisar_por_zona(df_filt)
            excel_buffer = exportar_prospeccao_excel(df_filt, df_construtoras_resumo, df_zonas_resumo)
            
            st.download_button("📥 Exportar Lista Completa (Excel)", excel_buffer, f"prospeccao_completa_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx", mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", use_container_width=True)

        st.markdown("---")
        st.markdown("""
        ### 💡 Dicas Rápidas:
        - Use a aba **Timeline** para planejar visitas 60-90 dias antes da entrega.
        - Foque nos projetos **🔴 Urgente** para ações imediatas.
        - A exportação gera um Excel com abas separadas por fase para facilitar o trabalho de campo.
        """)
    else:
        st.info("👆 Faça upload da planilha para visualizar os dados")

if __name__ == "__main__":
    render_prospeccao_condominios()
