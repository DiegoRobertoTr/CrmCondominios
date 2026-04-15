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
from bson.objectid import ObjectId
import time

# ==================== FUNÇÕES UTILITÁRIAS OTIMIZADAS ====================
def limpar_valor_data(valor):
    """Limpa e converte valores de data com tratamento robusto"""
    if pd.isna(valor) or valor is None:
        return None
    
    # Cache simples para evitar processamento repetitivo
    if hasattr(limpar_valor_data, '_cache'):
        if valor in limpar_valor_data._cache:
            return limpar_valor_data._cache[valor]
    else:
        limpar_valor_data._cache = {}
    
    try:
        if isinstance(valor, str):
            valor_limpo = valor.strip()
            if valor_limpo in ["00/00/0000", "0", "", "nan", "NaT", "null", "NULL", "-"]:
                limpar_valor_data._cache[valor] = None
                return None
            
            match = re.search(r'\d{2}/\d{2}/\d{2,4}', valor_limpo)
            if match:
                valor_limpo = match.group()
            
            valor_dt = pd.to_datetime(valor_limpo, errors='coerce', dayfirst=True)
            result = valor_dt.to_pydatetime().replace(tzinfo=None) if pd.notna(valor_dt) else None
            limpar_valor_data._cache[valor] = result
            return result
            
        elif isinstance(valor, (pd.Timestamp, datetime)):
            if pd.isna(valor):
                limpar_valor_data._cache[str(valor)] = None
                return None
            
            if hasattr(valor, 'tzinfo') and valor.tzinfo is not None:
                result = valor.replace(tzinfo=None)
            else:
                result = valor
            
            limpar_valor_data._cache[str(valor)] = result
            return result
            
    except Exception:
        limpar_valor_data._cache[valor] = None
        return None
    
    limpar_valor_data._cache[valor] = None
    return None

def converter_dataframe_dates(df, colunas_alvo=None):
    """Converte apenas colunas específicas ou detectadas como data - VERSÃO OTIMIZADA"""
    if df.empty:
        return df
        
    df = df.copy()
    
    if colunas_alvo is None:
        colunas_alvo = []
        palavras_chave = ['data', 'date', 'cadastro', 'entrega', 'previsao', 'atualizacao']
        
        for col in df.columns:
            col_lower = col.lower()
            if any(palavra in col_lower for palavra in palavras_chave):
                colunas_alvo.append(col)
            elif pd.api.types.is_datetime64_any_dtype(df[col]):
                colunas_alvo.append(col)
    
    # Processar todas as colunas de uma vez para melhor performance
    for col in colunas_alvo:
        if col in df.columns:
            try:
                # Converter toda a coluna de uma vez
                df[col] = pd.to_datetime(df[col], errors='coerce', dayfirst=True)
                # Aplicar limpeza apenas nos valores não nulos
                mask_notna = df[col].notna()
                df.loc[mask_notna, col] = df.loc[mask_notna, col].apply(
                    lambda x: limpar_valor_data(x) if pd.notna(x) else None
                )
            except Exception:
                pass
    
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
                st.error(" Credenciais MongoDB incompletas nos Secrets.")
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

# ==================== FUNÇÕES DE BANCO DE DADOS ====================
def save_prospeccao_data(db, df_prospeccao, metadata):
    """Salva dados de prospecção no MongoDB garantindo integridade do batch"""
    collection = db["prospeccao_condominios"]
    meta_collection = db["prospeccao_meta"]
    batch_id = metadata["batch_id"]
    
    # Limpeza preventiva para evitar duplicatas do mesmo lote
    delete_result = collection.delete_many({"_import_batch": batch_id})
    meta_collection.delete_many({"batch_id": batch_id})

    if delete_result.deleted_count > 0:
        st.info(f"⚠️ {delete_result.deleted_count} registros antigos do mesmo lote removidos.")

    cols_data = ["PREVISAO_ENTREGA", "Data da Atualização", "Previsão de Entrega"] 
    cols_data.extend([c for c in df_prospeccao.columns if 'data' in c.lower() or 'date' in c.lower()])

    df_limpo = converter_dataframe_dates(df_prospeccao, colunas_alvo=list(set(cols_data)))

    docs = []
    for _, row in df_limpo.iterrows():
        doc = row.to_dict()
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
    cursor = collection.find({"_import_batch": meta["batch_id"]})
    df_prospeccao = pd.DataFrame(list(cursor))

    # CORREÇÃO CRÍTICA: Manter o _id e converter para string para o Streamlit editar
    if "_id" in df_prospeccao.columns:
        df_prospeccao["_id"] = df_prospeccao["_id"].astype(str)
    else:
        df_prospeccao["_id"] = [str(i) for i in range(len(df_prospeccao))]

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

def update_single_record(db, record_id, updates):
    """Atualiza um único registro no MongoDB"""
    try:
        collection = db["prospeccao_condominios"]
        try:
            obj_id = ObjectId(record_id)
        except:
            st.error("ID inválido.")
            return False
        
        clean_updates = {}
        for k, v in updates.items():
            if k == "_id":
                continue
            if isinstance(v, str) and v.strip() == "":
                clean_updates[k] = None
            elif pd.isna(v):
                clean_updates[k] = None
            else:
                clean_updates[k] = v
        
        date_cols = [k for k in clean_updates.keys() if 'data' in k.lower() or 'previsao' in k.lower()]
        for col in date_cols:
            if clean_updates[col] is not None:
                clean_updates[col] = limpar_valor_data(clean_updates[col])
        
        result = collection.update_one({"_id": obj_id}, {"$set": clean_updates})
        return result.modified_count > 0
    except Exception as e:
        st.error(f"Erro ao atualizar: {e}")
        return False

def insert_new_record(db, new_data):
    """Insere um novo registro manualmente"""
    try:
        collection = db["prospeccao_condominios"]
        doc = new_data.copy()
        
        if "ESTÁGIO" in doc:
            doc["FASE_CLASSIFICADA"] = classificar_fase(doc["ESTÁGIO"])
        else:
            doc["FASE_CLASSIFICADA"] = " Em Tratativa"
        
        if "VIABILIDADE" in doc:
            doc["PREVISAO_ENTREGA"] = extrair_previsao_entrega(doc["VIABILIDADE"])
        
        doc["DIAS_RESTANTES"] = calcular_dias_para_entrega(doc.get("PREVISAO_ENTREGA"))
        doc["PRIORIDADE"] = calcular_prioridade(doc)
        
        doc["_import_timestamp"] = datetime.now().replace(tzinfo=None)
        doc["_import_batch"] = "manual_entry"
        
        for key, value in list(doc.items()):
            if isinstance(value, (pd.Timestamp, datetime)):
                doc[key] = limpar_valor_data(value)
            elif pd.isna(value):  
                doc[key] = None
        
        collection.insert_one(doc)
        return True
    except Exception as e:
        st.error(f"Erro ao inserir: {e}")
        return False

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
        return " Início de Obra"
    elif any(x in fase_lower for x in ["lançamento", "lancamento", "vendas", "grupo em formação"]):
        return " Lançamento"
    elif any(x in fase_lower for x in ["futuro", "planejado", "terreno", "futuro lançamento"]):
        return " Futuro Lançamento"
    elif any(x in fase_lower for x in ["não entramos", "perdido", "embargado", "sem viabilidade", "não autorizado"]):
        return "❌ Não Entramos"
    else:
        return " Em Tratativa"

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
                if len(data_str) == 5:
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
        projetos_inicio_obra=("FASE_CLASSIFICADA", lambda x: (x == " Início de Obra").sum()),
        projetos_lancamento=("FASE_CLASSIFICADA", lambda x: (x == " Lançamento").sum()),
        projetos_futuro=("FASE_CLASSIFICADA", lambda x: (x == " Futuro Lançamento").sum()),
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
        projetos_em_obra=("FASE_CLASSIFICADA", lambda x: x.isin([" Final de Obra", "🔨 Intermediário", " Início de Obra"]).sum()),
        projetos_pronto=("FASE_CLASSIFICADA", lambda x: (x == "✅ Pronto").sum()),
        oportunidades=("FASE_CLASSIFICADA", lambda x: x.isin([" Lançamento", " Futuro Lançamento", " Intermediário", " Início de Obra"]).sum())
    ).reset_index()

    zona_stats["percentual_em_obra"] = (zona_stats["projetos_em_obra"] / zona_stats["total_projetos"] * 100).round(1)
    zona_stats["percentual_oportunidades"] = (zona_stats["oportunidades"] / zona_stats["total_projetos"] * 100).round(1)

    return zona_stats.sort_values("total_projetos", ascending=False).reset_index(drop=True)

def timeline_entregas(df_prospeccao):
    """Prepara dados para timeline de entregas"""
    df_timeline = df_prospeccao.copy()
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
            return " Alta"
        else:
            return " Média"
    elif fase in ["🔨 Intermediário", " Início de Obra"]:
        if dias is not None and dias <= 365:
            return " Alta"
        else:
            return " Média"
    elif fase in [" Lançamento", " Futuro Lançamento"]:
        return " Planejamento"
    else:
        return " Baixa"

# ==================== ✅ FUNÇÃO DE EXPORTAÇÃO MELHORADA ====================
def exportar_prospeccao_excel(df_prospeccao, df_construtoras, df_zonas):
    """
    ✅ Exporta dados de prospecção para Excel COM ABAS SEPARADAS POR FASE
    Cada fase tem sua própria aba com dados pertinentes
    """
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        # === ABA 1: RESUMO EXECUTIVO ===
        resumo_data = {
            'Métrica': [
                'Total de Projetos',
                'Total de Apartamentos',
                'Projetos em Obra',
                'Projetos Prontos',
                'Oportunidades (Lançamento/Futuro)',
                'Construtoras Ativas',
                'Regiões Atendidas'
            ],
            'Valor': [
                len(df_prospeccao),
                df_prospeccao['APTO'].fillna(0).sum() if 'APTO' in df_prospeccao.columns else 0,
                len(df_prospeccao[df_prospeccao['FASE_CLASSIFICADA'].isin(['🏁 Final de Obra', '🔨 Intermediário', ' Início de Obra'])]) if 'FASE_CLASSIFICADA' in df_prospeccao.columns else 0,
                len(df_prospeccao[df_prospeccao['FASE_CLASSIFICADA'] == '✅ Pronto']) if 'FASE_CLASSIFICADA' in df_prospeccao.columns else 0,
                len(df_prospeccao[df_prospeccao['FASE_CLASSIFICADA'].isin([' Lançamento', ' Futuro Lançamento'])]) if 'FASE_CLASSIFICADA' in df_prospeccao.columns else 0,
                df_prospeccao['CONSTRUTORA'].nunique() if 'CONSTRUTORA' in df_prospeccao.columns else 0,
                df_prospeccao['Região'].nunique() if 'Região' in df_prospeccao.columns else (df_prospeccao['ZONA'].nunique() if 'ZONA' in df_prospeccao.columns else 0)
            ]
        }
        df_resumo = pd.DataFrame(resumo_data)
        df_resumo.to_excel(writer, sheet_name=' Resumo Executivo', index=False)
        
        # === ABA 2: DADOS COMPLETOS ===
        df_prospeccao.to_excel(writer, sheet_name=' Completo', index=False)
        
        # === ABAS 3-10: POR FASE (CADA FASE EM UMA ABA) ===
        fases_map = {
            ' Lançamento': '01_Lancamento',
            ' Início de Obra': '02_Inicio_Obra',
            ' Intermediário': '03_Intermediario',
            ' Final de Obra': '04_Final_Obra',
            '✅ Pronto': '05_Pronto',
            ' Futuro Lançamento': '06_Futuro_Lancamento',
            '❌ Não Entramos': '07_Nao_Entramos',
            ' Em Tratativa': '08_Em_Tratativa'
        }
        
        for fase_padrao, nome_aba in fases_map.items():
            df_fase = df_prospeccao[df_prospeccao['FASE_CLASSIFICADA'] == fase_padrao].copy()
             
            if not df_fase.empty:
                # Selecionar colunas pertinentes para cada fase
                cols_base = ['NOME', 'CONSTRUTORA', 'BAIRRO', 'Região' if 'Região' in df_fase.columns else 'ZONA', 
                            'ENDEREÇO', 'BLOCO', 'APTO', 'FASE_CLASSIFICADA', 'PRIORIDADE']
                
                # Adicionar colunas específicas se existirem 
                cols_adicionais = ['VIABILIDADE', 'OBS', 'PREVISAO_ENTREGA', 'DIAS_RESTANTES', 'FASE_ORIGINAL']
                cols_existentes = [c for c in cols_adicionais if c in df_fase.columns]
                
                cols_final = [c for c in cols_base if c in df_fase.columns] + cols_existentes
                
                df_export = df_fase[cols_final].copy()
                 
                # Formatar datas para string legível
                if 'PREVISAO_ENTREGA' in df_export.columns:
                    df_export['PREVISAO_ENTREGA'] = df_export['PREVISAO_ENTREGA'].apply(
                        lambda x: safe_strftime(x, '%d/%m/%Y') if pd.notna(x) else ''
                    )
                
                # Limitar nome da aba a 31 caracteres (limite do Excel)
                nome_aba = nome_aba[:31]
                df_export.to_excel(writer, sheet_name=nome_aba, index=False)
        
        # === ABA 11: POR CONSTRUTORA ===
        if not df_construtoras.empty:
            df_construtoras.to_excel(writer, sheet_name='11_Por_Construtora', index=False)
        
        # === ABA 12: POR REGIÃO ===
        if not df_zonas.empty:
            df_zonas.to_excel(writer, sheet_name='12_Por_Regiao', index=False)

    output.seek(0)
    return output

# ==================== INTERFACE STREAMLIT ====================
def render_prospeccao_condominios():
    st.title(" Prospecção de Condomínios")
    st.markdown("Acompanhamento de fases de construção por construtora e oportunidades de mercado")
    db = init_mongo()

    st.markdown("---")

    # ==================== GERENCIAMENTO DE DADOS ====================
    st.subheader(" Gerenciamento de Dados")
    col1, col2 = st.columns([3, 1])

    with col1:
        uploaded_file = st.file_uploader(
            " Importar Planilha de Prospecção", 
            type=["xlsx", "xls"], 
            help="Planilha com colunas: Região, BAIRRO, ENDEREÇO, NOME, BLOCO, APTO, CONSTRUTORA, ESTÁGIO, VIABILIDADE, OBS"
        )

    with col2:
        if st.button(" Recarregar Últimos", type="primary", use_container_width=True):
            st.session_state["reload_prospeccao"] = True
            st.rerun()
        
        if st.button(" Limpar Dados", type="secondary", use_container_width=True):
            if st.session_state.get("confirm_delete_prospeccao"):
                deleted = clear_prospeccao_data(db)
                st.success(f" {deleted} registros removidos!")
                st.session_state["confirm_delete_prospeccao"] = False
                if "df_prospeccao_cached" in st.session_state:
                    del st.session_state["df_prospeccao_cached"]
                st.rerun()
            else:
                st.warning(" Clique novamente para confirmar")
                st.session_state["confirm_delete_prospeccao"] = True

    meta = db["prospeccao_meta"].find_one(sort=[("timestamp", -1)])
    if meta:
        ts = meta.get('timestamp')
        ts_str = safe_strftime(ts, "%d/%m/%Y %H:%M") if ts else "Data não disponível"
        st.info(f"""
        **Última Importação:**
        -  {ts_str}
        -  {meta['total_projetos']} projetos
        -  {len(meta.get('construtoras', []))} construtoras
        """)
    else:
        st.warning(" Nenhum dado importado ainda")

    st.markdown("---")
    df_prospeccao, meta = None, None

    # ==================== IMPORTAÇÃO DA PLANILHA ====================
    if uploaded_file:
        start_time = time.time()
        progress_bar = st.progress(0)
        
        try:
            progress_bar.progress(10)
            df_prospeccao = pd.read_excel(uploaded_file, sheet_name=0)
            
            progress_bar.progress(30)
            if len(df_prospeccao) > 0:
                primeira_linha = df_prospeccao.iloc[0].astype(str).str.lower()
                colunas_lower = [c.lower() for c in df_prospeccao.columns]
                if all(val in colunas_lower or val == 'nan' for val in primeira_linha):
                    df_prospeccao = df_prospeccao.iloc[1:].reset_index(drop=True)
            
            progress_bar.progress(50)
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
                
                progress_bar.progress(70)
                if "ESTÁGIO" not in df_prospeccao.columns:
                    st.error(" Coluna 'ESTÁGIO' não encontrada na planilha!")
                    st.stop()
                
                df_prospeccao["FASE_CLASSIFICADA"] = df_prospeccao["ESTÁGIO"].apply(classificar_fase)
                df_prospeccao["FASE_ORIGINAL"] = df_prospeccao["ESTÁGIO"]
                
                progress_bar.progress(80)
                if "VIABILIDADE" in df_prospeccao.columns:
                    df_prospeccao["PREVISAO_ENTREGA"] = df_prospeccao["VIABILIDADE"].apply(extrair_previsao_entrega)
                if "Previsão de Entrega" in df_prospeccao.columns:
                    df_prospeccao["PREVISAO_ENTREGA_2"] = df_prospeccao["Previsão de Entrega"].apply(extrair_previsao_entrega)
                    df_prospeccao["PREVISAO_ENTREGA"] = df_prospeccao.apply(
                        lambda row: row["PREVISAO_ENTREGA"] if pd.notna(row["PREVISAO_ENTREGA"]) else row.get("PREVISAO_ENTREGA_2"), 
                        axis=1
                    )
                
                progress_bar.progress(90)
                df_prospeccao["DIAS_RESTANTES"] = df_prospeccao["PREVISAO_ENTREGA"].apply(calcular_dias_para_entrega)
                df_prospeccao["PRIORIDADE"] = df_prospeccao.apply(calcular_prioridade, axis=1)
                
                progress_bar.progress(95)
                fases_count = df_prospeccao["FASE_CLASSIFICADA"].value_counts().to_dict()
                metadata = {
                    "timestamp": datetime.now().replace(tzinfo=None),
                    "batch_id": f"prospeccao_{datetime.now().strftime('%Y%m%d_%H%M%S')}",
                    "filename": uploaded_file.name,
                    "fases": fases_count,
                    "construtoras": df_prospeccao["CONSTRUTORA"].dropna().unique().tolist() if "CONSTRUTORA" in df_prospeccao.columns else []
                }
                
                progress_bar.progress(100)
                if save_prospeccao_data(db, df_prospeccao, metadata):
                    elapsed_time = time.time() - start_time
                    st.success(f" Dados importados! {len(df_prospeccao)} projetos de {len(metadata['construtoras'])} construtoras (Tempo: {elapsed_time:.2f}s)")
                    if "df_prospeccao_cached" in st.session_state:
                        del st.session_state["df_prospeccao_cached"]
                    st.rerun()
                    
        except Exception as e:
            st.error(f" Erro ao processar planilha: {str(e)}")
            import traceback
            st.expander("Detalhes técnicos do erro").code(traceback.format_exc())
        finally:
            progress_bar.empty()

    # ==================== CARREGAMENTO OTIMIZADO (CACHE) ====================
    elif st.session_state.get("reload_prospeccao") or "df_prospeccao_cached" not in st.session_state:
        with st.spinner(' Carregando dados do banco...'):
            start_time = time.time()
            result = load_latest_prospeccao(db)
            if result[0] is not None:
                df_prospeccao, meta = result
                
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
                
                elapsed_time = time.time() - start_time
                st.success(f" Dados carregados e otimizados! (Tempo: {elapsed_time:.2f}s)")
            else:
                st.info(" Faça upload da planilha para começar")
                return
    else:
        df_prospeccao = st.session_state["df_prospeccao_cached"]
        meta = st.session_state["meta_cached"]

    if "reload_prospeccao" in st.session_state:
        del st.session_state["reload_prospeccao"]

    # ==================== NOVAS ABAS SOLICITADAS ====================
    tab_update, tab_new, tab_dash1, tab_dash2, tab_dash3, tab_dash4, tab_dash5 = st.tabs([
        "✏️ Atualizar Empreendimentos", 
        "➕ Novo Cadastro",
        " Por Construtora", 
        " Por Região", 
        " Timeline", 
        " Priorização", 
        " Lista Completa"
    ])

    # --- LÓGICA DA ABA: ATUALIZAR EMPREENDIMENTOS ---
    with tab_update:
        st.header("✏️ Atualização de Cadastros")
        st.markdown("Filtre os empreendimentos e edite diretamente na tabela abaixo.")
        
        if df_prospeccao is not None and not df_prospeccao.empty:
            c1, c2, c3, c4 = st.columns(4)
            
            construtoras_opts = sorted(df_prospeccao["CONSTRUTORA"].dropna().unique().tolist()) if "CONSTRUTORA" in df_prospeccao.columns else []
            regioes_opts = sorted(df_prospeccao["Região"].dropna().unique().tolist()) if "Região" in df_prospeccao.columns else (sorted(df_prospeccao["ZONA"].dropna().unique().tolist()) if "ZONA" in df_prospeccao.columns else [])
            fases_opts = sorted(df_prospeccao["FASE_CLASSIFICADA"].dropna().unique().tolist()) if "FASE_CLASSIFICADA" in df_prospeccao.columns else []
            
            with c1:
                filter_construtora = st.multiselect("Construtora", options=construtoras_opts, placeholder="Todas")
            with c2:
                filter_regiao = st.multiselect("Região/Zona", options=regioes_opts, placeholder="Todas")
            with c3:
                filter_fase = st.multiselect("Estágio/Fase", options=fases_opts, placeholder="Todos")
            with c4:
                search_nome = st.text_input("Buscar por Nome", placeholder="Ex: MRV...")
            
            df_filtered = df_prospeccao.copy()
            if filter_construtora:
                df_filtered = df_filtered[df_filtered["CONSTRUTORA"].isin(filter_construtora)]
            if filter_regiao:
                col_reg = "Região" if "Região" in df_filtered.columns else "ZONA"
                df_filtered = df_filtered[df_filtered[col_reg].isin(filter_regiao)]
            if filter_fase:
                df_filtered = df_filtered[df_filtered["FASE_CLASSIFICADA"].isin(filter_fase)]
            if search_nome:
                df_filtered = df_filtered[df_filtered["NOME"].str.contains(search_nome, case=False, na=False)]
            
            st.markdown(f"**{len(df_filtered)} registros encontrados para edição.**")
            
            if not df_filtered.empty:
                cols_to_edit = ["NOME", "CONSTRUTORA", "BAIRRO", "Região" if "Região" in df_filtered.columns else "ZONA", 
                                 "ESTÁGIO", "VIABILIDADE", "APTO", "OBS", "PREVISAO_ENTREGA"]
                
                cols_existing = [c for c in cols_to_edit if c in df_filtered.columns]
                
                if "_id" not in df_filtered.columns:
                    st.error("Erro interno: ID não encontrado nos dados filtrados.")
                    st.stop()
                
                df_edit = df_filtered[cols_existing + ["_id"]].copy()
                
                # Configurar column_config para usar selectbox na coluna ESTÁGIO
                column_config = {
                    "ESTÁGIO": st.column_config.SelectboxColumn(
                        "Estágio da Obra",
                        options=[
                            " Lançamento", " Início de Obra", " Intermediário", 
                            " Final de Obra", "✅ Pronto", " Futuro Lançamento", 
                            "❌ Não Entramos", " Em Tratativa"
                        ],
                        required=True
                    )
                }
                
                edited_df = st.data_editor(
                    df_edit.drop(columns=["_id"]),
                    key="editor_prospeccao",
                    use_container_width=True,
                    num_rows="fixed",
                    disabled=["_id"],
                    column_config=column_config
                )
                
                st.warning(" Atenção: Ao editar a coluna 'ESTÁGIO', a 'Fase Classificada' será recalculada automaticamente ao salvar.")
                
                if st.button(" Salvar Alterações Selecionadas", type="primary"):
                    edited_df = st.session_state["editor_prospeccao"]
                    
                    # CORREÇÃO CRÍTICA: Verificar se é DataFrame ou dict
                    if isinstance(edited_df, dict):
                        edited_df = pd.DataFrame(edited_df)
                    
                    df_filtered_reset = df_filtered.reset_index(drop=True)
                    edited_df_reset = edited_df.reset_index(drop=True)
                    
                    success_count = 0
                    error_count = 0
                    
                    progress_bar = st.progress(0)
                    
                    for i, row in edited_df_reset.iterrows():
                        if i >= len(df_filtered_reset):
                            break
                        
                        original_id = df_filtered_reset.iloc[i]["_id"]
                        updates = row.to_dict()
                        
                        if "ESTÁGIO" in updates:
                            updates["FASE_CLASSIFICADA"] = classificar_fase(updates["ESTÁGIO"])
                        
                        if "VIABILIDADE" in updates:
                            updates["PREVISAO_ENTREGA"] = extrair_previsao_entrega(updates["VIABILIDADE"])
                        
                        if "PREVISAO_ENTREGA" in updates:
                            updates["DIAS_RESTANTES"] = calcular_dias_para_entrega(updates["PREVISAO_ENTREGA"])
                        
                        temp_row = pd.Series(updates)
                        updates["PRIORIDADE"] = calcular_prioridade(temp_row)
                        
                        if update_single_record(db, original_id, updates):
                            success_count += 1
                        else:
                            error_count += 1
                        
                        progress_bar.progress((i + 1) / len(edited_df_reset))
                    
                    progress_bar.empty()
                    if success_count > 0:
                        st.success(f" {success_count} registros atualizados com sucesso!")
                        if "df_prospeccao_cached" in st.session_state:
                            del st.session_state["df_prospeccao_cached"]
                        st.rerun()
                    if error_count > 0:
                        st.error(f" {error_count} registros falharam ao atualizar.")
            else:
                st.info("Nenhum registro encontrado com esses filtros.")
        else:
            st.warning("Carregue dados primeiro.")

    # --- LÓGICA DA ABA: NOVO CADASTRO ---
    with tab_new:
        st.header("➕ Novo Cadastro Manual")
        st.markdown("Preencha os dados abaixo para adicionar um novo empreendimento ao banco.")
        
        with st.form("form_novo_empreendimento", clear_on_submit=True):
            c1, c2 = st.columns(2)
            
            with c1:
                nome = st.text_input("Nome do Empreendimento *", placeholder="Ex: Residencial Jardins")
                construtora = st.text_input("Construtora *", placeholder="Ex: MRV")
                bairro = st.text_input("Bairro", placeholder="Ex: Centro")
                regiao = st.text_input("Região/Zona", placeholder="Ex: Zona Norte")
                endereco = st.text_input("Endereço", placeholder="Rua das Flores, 123")
                bloco = st.text_input("Bloco/Torre", placeholder="Bloco A")
            
            with c2:
                apto = st.number_input("Total de Apartamentos", min_value=0, step=1)
                estagio = st.selectbox("Estágio da Obra", [
                    " Lançamento", " Início de Obra", " Intermediário", " Final de Obra", 
                    "✅ Pronto", " Futuro Lançamento", "❌ Não Entramos", " Em Tratativa"
                ])
                viabilidade = st.text_area("Viabilidade / Observações", placeholder="Ex: Sim, contato feito. Previsão entrega 12/2025.")
                obs_geral = st.text_area("Observações Gerais")
            
            submitted = st.form_submit_button("Cadastrar Empreendimento")
            
            if submitted:
                if not nome or not construtora:
                    st.error(" Nome e Construtora são obrigatórios.")
                else:
                    new_data = {
                        "NOME": nome,
                        "CONSTRUTORA": construtora,
                        "BAIRRO": bairro,
                        "Região": regiao,
                        "ENDEREÇO": endereco,
                        "BLOCO": bloco,
                        "APTO": apto,
                        "ESTÁGIO": estagio,
                        "VIABILIDADE": viabilidade,
                        "OBS": obs_geral
                    }
                    
                    if insert_new_record(db, new_data):
                        st.success(" Empreendimento cadastrado com sucesso!")
                        if "df_prospeccao_cached" in st.session_state:
                            del st.session_state["df_prospeccao_cached"]
                        st.rerun()
                    else:
                        st.error(" Erro ao cadastrar. Verifique os logs.")

    # ==================== DASHBOARD PRINCIPAL ====================
    if df_prospeccao is not None and not df_prospeccao.empty:
        
        with tab_dash1:
            st.header(" Análise por Construtora")
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
                    
                    st.markdown("### Composição de Fases por Construtora")
                    fases_cols = ["projetos_pronto", "projetos_final_obra", "projetos_intermediario", "projetos_inicio_obra", "projetos_lancamento", "projetos_futuro"]
                    fases_labels = ["✅ Pronto", " Final", " Intermed.", " Início", " Lançam.", " Futuro"]
                    
                    df_fases_plot = df_construtoras_filt.head(8).copy().set_index("CONSTRUTORA")[fases_cols]
                    df_fases_plot.columns = fases_labels
                    
                    fig3 = px.bar(df_fases_plot, barmode="stack", title="Distribuição de Fases (Top 8)", color_discrete_sequence=px.colors.qualitative.Set3)
                    fig3.update_layout(height=500)
                    st.plotly_chart(fig3, use_container_width=True)
                     
                    st.markdown("### Tabela Detalhada")
                    df_display = df_construtoras_filt[["CONSTRUTORA", "total_projetos", "total_apartamentos", "percentual_pronto", "percentual_em_obra", "percentual_lancamento"]].copy()
                    df_display["total_apartamentos"] = df_display["total_apartamentos"].apply(lambda x: formatar_numero_br(int(x) if pd.notna(x) else 0))
                    df_display["percentual_pronto"] = df_display["percentual_pronto"].apply(lambda x: f"{x:.1f}%")
                    df_display["percentual_em_obra"] = df_display["percentual_em_obra"].apply(lambda x: f"{x:.1f}%")
                    df_display["percentual_lancamento"] = df_display["percentual_lancamento"].apply(lambda x: f"{x:.1f}%")
                    df_display.columns = ["Construtora", "Projetos", "Total APTs", "% Pronto", "% Em Obra", "% Lançamento/Futuro"]
                    st.dataframe(df_display, use_container_width=True)
            else:
                st.warning(" Dados insuficientes para análise por construtora")
        
        with tab_dash2:
            st.header(" Análise por Região")
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
                    st.markdown("### Top 15 Bairros")
                    bairros_stats = df_prospeccao.groupby("BAIRRO").agg(total_projetos=("NOME", "count")).reset_index().sort_values("total_projetos", ascending=False).head(15)
                    fig_bairro = px.bar(bairros_stats, x="total_projetos", y="BAIRRO", orientation="h", title="Top 15 Bairros", color="total_projetos", color_continuous_scale="Blues")
                    st.plotly_chart(fig_bairro, use_container_width=True)
                
                st.dataframe(df_zonas, use_container_width=True)
            else:
                st.warning(" Dados insuficientes para análise por região")
        
        with tab_dash3:
            st.header(" Timeline de Entregas")
            df_timeline = timeline_entregas(df_prospeccao)
            if not df_timeline.empty and "PREVISAO_ENTREGA" in df_timeline.columns:
                anos_disp = sorted(df_timeline["ANO_ENTREGA"].dropna().unique().astype(int))
                if anos_disp:
                    ano_sel = st.selectbox("Filtrar por Ano de Entrega", options=anos_disp, index=len(anos_disp)-1)
                    df_timeline_filt = df_timeline[df_timeline["ANO_ENTREGA"] == ano_sel]
                    
                    st.markdown(f"### Entregas Previstas para {int(ano_sel)}")
                    if not df_timeline_filt.empty:
                        entregas_por_mes = df_timeline_filt.groupby("MES_ENTREGA").agg(total_projetos=("NOME", "count"), total_apartamentos=("APTO", lambda x: pd.to_numeric(x, errors='coerce').sum())).reset_index()
                        entregas_por_mes["MES_ENTREGA"] = entregas_por_mes["MES_ENTREGA"].astype(str)
                        
                        fig_timeline = px.bar(entregas_por_mes, x="MES_ENTREGA", y="total_projetos", color="total_apartamentos", title=f"Distribuição Mensal ({int(ano_sel)})")
                        st.plotly_chart(fig_timeline, use_container_width=True)
                        
                        st.markdown("### Próximos 90 dias")
                        entregas_proximas = df_timeline[df_timeline["DIAS_RESTANTES"] <= 90].sort_values("DIAS_RESTANTES")
                        if not entregas_proximas.empty:
                            for _, row in entregas_proximas.head(10).iterrows():
                                dias = int(row["DIAS_RESTANTES"]) if pd.notna(row["DIAS_RESTANTES"]) else 0
                                cor = "🔴" if dias <= 30 else "🟠" if dias <= 60 else "🟡"
                                st.markdown(f"{cor} **{row['NOME']}** ({row.get('CONSTRUTORA', 'N/A')}) - {row.get('BAIRRO', '')} - {dias} dias")
                        else:
                            st.info(" Nenhuma entrega nos próximos 90 dias")
                        
                        with st.expander(" Ver Todas as Entregas de " + str(int(ano_sel))):
                            cols_disp = ["NOME", "CONSTRUTORA", "BAIRRO", "APTO", "PREVISAO_ENTREGA", "DIAS_RESTANTES"]
                            cols_existentes = [c for c in cols_disp if c in df_timeline_filt.columns]
                            df_show = df_timeline_filt[cols_existentes].copy()
                            if "PREVISAO_ENTREGA" in df_show.columns:
                                df_show["PREVISAO_ENTREGA"] = df_show["PREVISAO_ENTREGA"].apply(safe_strftime)
                            st.dataframe(df_show, use_container_width=True)
            else:
                st.warning(" Sem dados de previsão de entrega.")
        
        with tab_dash4:
            st.header(" Priorização de Ações")
            if "PRIORIDADE" in df_prospeccao.columns:
                col_pri1, col_pri2 = st.columns(2)
                
                with col_pri1:
                    fig_pri = px.pie(values=df_prospeccao["PRIORIDADE"].value_counts().values, names=df_prospeccao["PRIORIDADE"].value_counts().index, title="Distribuição de Prioridades", color_discrete_map={" Urgente": "#e74c3c", " Alta": "#e67e22", " Média": "#f1c40f", " Planejamento": "#2ecc71", " Baixa": "#95a5a6"})
                    st.plotly_chart(fig_pri, use_container_width=True)
                
                with col_pri2:
                    prioridades_disp = df_prospeccao["PRIORIDADE"].unique().tolist()
                    valid_defaults = [p for p in [" Urgente", " Alta"] if p in prioridades_disp]
                    if not valid_defaults and prioridades_disp:
                        valid_defaults = [prioridades_disp[0]]
                    
                    prioridade_sel = st.multiselect("Filtrar por Prioridade", options=prioridades_disp, default=valid_defaults, key="prioridade_filter")
                    
                    if prioridade_sel:
                        df_prioridade = df_prospeccao[df_prospeccao["PRIORIDADE"].isin(prioridade_sel)]
                        st.metric("Projetos Prioritários", formatar_numero_br(len(df_prioridade)))
                        
                        st.markdown("### 📋 Lista de Ação")
                        cols_disp = ["NOME", "CONSTRUTORA", "BAIRRO", "FASE_CLASSIFICADA", "PRIORIDADE", "DIAS_RESTANTES"]
                        cols_existentes = [c for c in cols_disp if c in df_prioridade.columns]
                        df_show = df_prioridade[cols_existentes].copy()
                         
                        if "DIAS_RESTANTES" in df_show.columns:
                            df_show["DIAS_RESTANTES"] = df_show["DIAS_RESTANTES"].apply(lambda x: f"{int(x)} dias" if pd.notna(x) else "-")
                        
                        st.dataframe(df_show, use_container_width=True)
                        
                        excel_buffer = io.BytesIO()
                        with pd.ExcelWriter(excel_buffer, engine='openpyxl') as writer:
                            df_show.to_excel(writer, index=False, sheet_name='Prioritários')
                        excel_buffer.seek(0)
                        st.download_button(" Exportar Lista Prioritária", excel_buffer, f"prioritarios_{datetime.now().strftime('%Y%m%d')}.xlsx", mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
            else:
                st.warning(" Dados de prioridade indisponíveis")
        
        # ==================== ✅ ABA LISTA COMPLETA COM EXPORTAÇÃO MELHORADA ====================
        with tab_dash5:
            st.header(" Lista Completa de Projetos")
            
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
            if zona_sel and col_regiao:
                df_filt = df_filt[df_filt[col_regiao].isin(zona_sel)]
            if construtora_sel: 
                df_filt = df_filt[df_filt["CONSTRUTORA"].isin(construtora_sel)]
            if fase_sel:
                df_filt = df_filt[df_filt["FASE_CLASSIFICADA"].isin(fase_sel)]
            
            st.markdown(f"###  {len(df_filt)} projetos encontrados")
            
            colunas_display = ["NOME", "CONSTRUTORA", "BAIRRO", "Região", "FASE_CLASSIFICADA", "APTO", "PRIORIDADE"]
            colunas_existentes = [c for c in colunas_display if c in df_filt.columns]
            df_lista = df_filt[colunas_existentes].copy()
            
            if "APTO" in df_lista.columns:
                df_lista["APTO"] = df_lista["APTO"].apply(lambda x: formatar_numero_br(int(x)) if pd.notna(x) else "N/A")
            
            col_names = {"NOME": "Condomínio", "CONSTRUTORA": "Construtora", "BAIRRO": "Bairro", "Região": "Região", "FASE_CLASSIFICADA": "Fase", "APTO": "APTs", "PRIORIDADE": "Prioridade"}
            df_lista = df_lista.rename(columns={k: v for k, v in col_names.items() if k in df_lista.columns})
            
            st.dataframe(df_lista, use_container_width=True)
             
            # === ✅ BOTÃO DE EXPORTAÇÃO MELHORADO ===
            st.markdown("---")
            st.subheader(" Exportar Dados")
            
            df_construtoras_resumo = analisar_por_construtora(df_filt)
            df_zonas_resumo = analisar_por_zona(df_filt)
            excel_buffer = exportar_prospeccao_excel(df_filt, df_construtoras_resumo, df_zonas_resumo)
            
            col_exp1, col_exp2 = st.columns([3, 1])
            with col_exp1:
                st.download_button(
                    label=" Exportar Lista Completa (Excel com Abas por Fase)",
                    data=excel_buffer,
                    file_name=f"prospeccao_completa_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx",
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    use_container_width=True
                )
            with col_exp2:
                st.info(f"""
                **Estrutura do Excel:**
                -  Resumo Executivo
                -  Completo
                - 01-08: Por Fase
                - 11: Por Construtora
                - 12: Por Região
                """)
        
        st.markdown("---")
        st.markdown("""
        ### 💡 Dicas Rápidas:
        - Use a aba **✏️ Atualizar Empreendimentos** para corrigir fases ou adicionar observações rapidamente.
        - Use a aba **➕ Novo Cadastro** para incluir leads que chegaram por telefone ou visita.
        - A exportação gera um Excel com **abas separadas por fase** para facilitar o trabalho de campo.
        """)
    else:
        st.info(" Faça upload da planilha para visualizar os dados")

if __name__ == "__main__":
    render_prospeccao_condominios()
