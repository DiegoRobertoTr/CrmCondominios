import streamlit as st
import pandas as pd
import numpy as np
import plotly.express as px
import plotly.graph_objects as go
from datetime import datetime
from pymongo import MongoClient
from pymongo.errors import ServerSelectionTimeoutError, ConnectionFailure
from urllib.parse import quote_plus
import io
import re
import time
from bson.objectid import ObjectId

# ==================== FUNÇÕES VETORIZADAS PURAS (SEM LOOPS) ====================

def processar_dataframe_prospeccao(df_raw):
    """Processa o DataFrame completo em operações VETORIZADAS - SEM LOOPS"""
    
    df = df_raw.copy()
    
    # 1. Limpar nomes das colunas
    df.columns = [str(col).strip() for col in df.columns]
    
    # 2. Renomear colunas (vetorizado)
    col_mapping = {
        'região': 'Região', 'zona': 'Região', 'bairro': 'BAIRRO',
        'endereço': 'ENDEREÇO', 'endereco': 'ENDEREÇO', 'nome': 'NOME',
        'condomínio': 'NOME', 'condominio': 'NOME', 'bloco': 'BLOCO',
        'apto': 'APTO', 'apartamentos': 'APTO', 'construtora': 'CONSTRUTORA',
        'estágio': 'ESTÁGIO', 'estagio': 'ESTÁGIO', 'viabilidade': 'VIABILIDADE',
        'obs': 'OBS', 'observações': 'OBS', 'data da atualização': 'Data da Atualização',
        'previsão de entrega': 'Previsão de Entrega'
    }
    
    cols_to_rename = {k: v for k, v in col_mapping.items() 
                     if k in [c.lower() for c in df.columns]}
    df = df.rename(columns=cols_to_rename)
    
    # 3. Classificar fases (usando numpy.select - MUITO RÁPIDO)
    if 'ESTÁGIO' in df.columns:
        fases_lower = df['ESTÁGIO'].fillna('').astype(str).str.lower().str.strip()
        
        conditions = [
            fases_lower.str.contains('entramos|entrada confirmada|projeto aceito|ganhamos|contratado', na=False, regex=True),
            fases_lower.str.contains('em negociação|negociando|tratativa|proposta|estudo|análise|avaliação', na=False, regex=True),
            fases_lower.str.contains('lançamento|lancamento|vendas|grupo em formação|pré-venda', na=False, regex=True),
            fases_lower.str.contains('início de obra|inicio de obra|inicial|fundação|estrutura|começando', na=False, regex=True),
            fases_lower.str.contains('obra em andamento|andamento|intermediário|intermediario|em construção|50%|60%|70%|80%', na=False, regex=True),
            fases_lower.str.contains('final de obra|fase final|acabamento|estágio final|estagio final|terminando', na=False, regex=True),
            fases_lower.str.contains('entregue|entregues|finalizado|concluído|concluido', na=False, regex=True),
            fases_lower.str.contains('pronto para morar|pronto pra morar|habite-se|disponível', na=False, regex=True),
            fases_lower.str.contains('futuro|planejado|terreno|futuro lançamento|previsão|previsto', na=False, regex=True),
            fases_lower.str.contains('não entramos|nao entramos|perdido|embargado|sem viabilidade|não autorizado|descartado', na=False, regex=True)
        ]
        
        choices = [
            '✅ Entramos', '💼 Em Negociação', '📢 Lançamento', '🚧 Início de Obra',
            '🔨 Obra em Andamento', '🏁 Final de Obra', '🎉 Entregue', '🏡 Pronto Para Morar',
            '📅 Futuro Lançamento', '❌ Não Entramos'
        ]
        
        df['FASE_CLASSIFICADA'] = np.select(conditions, choices, default='💼 Em Negociação')
        df['FASE_ORIGINAL'] = df['ESTÁGIO']
    
    # 4. Extrair previsão de entrega (vetorizado com regex - CORRIGIDO)
    if 'VIABILIDADE' in df.columns:
        viab_str = df['VIABILIDADE'].fillna('').astype(str)
        
        # Tentar extrair data completa
        datas = viab_str.str.extract(r'(\d{2}/\d{2}/\d{2,4})', expand=False)
        
        # Se não encontrou, tentar mês/ano
        mask_no_data = datas.isna()
        if mask_no_data.any():
            mes_ano = viab_str[mask_no_data].str.extract(r'(\d{2}/\d{4})', expand=False)
            datas_copy = datas.copy()
            datas_copy[mask_no_data] = mes_ano
            datas = datas_copy
            # Adicionar dia 01 para conversão
            mask_mes_ano = datas.notna() & (datas.str.len() == 7)
            if mask_mes_ano.any():
                datas_updated = datas.copy()
                datas_updated[mask_mes_ano] = '01/' + datas[mask_mes_ano]
                datas = datas_updated
        
        # Converter para datetime com tratamento de erro
        df['PREVISAO_ENTREGA'] = pd.to_datetime(datas, errors='coerce', dayfirst=True)
    
    # 5. Se houver coluna específica de previsão, usar ela como優先
    if 'Previsão de Entrega' in df.columns:
        previsao_direta = pd.to_datetime(df['Previsão de Entrega'], errors='coerce', dayfirst=True)
        if 'PREVISAO_ENTREGA' in df.columns:
            df['PREVISAO_ENTREGA'] = df['PREVISAO_ENTREGA'].fillna(previsao_direta)
        else:
            df['PREVISAO_ENTREGA'] = previsao_direta
    
    # 6. Calcular dias restantes (vetorizado - CORRIGIDO)
    if 'PREVISAO_ENTREGA' in df.columns:
        hoje = datetime.now().replace(tzinfo=None, hour=0, minute=0, second=0, microsecond=0)
        # Converter para datetime sem timezone
        previsao_clean = pd.to_datetime(df['PREVISAO_ENTREGA'], errors='coerce')
        # Remover timezone se existir
        if previsao_clean.dt.tz is not None:
            previsao_clean = previsao_clean.dt.tz_localize(None)
        # Calcular diferença
        df['DIAS_RESTANTES'] = (previsao_clean - pd.Timestamp(hoje)).dt.days
    
    # 7. Calcular prioridade (vetorizado com numpy.select)
    if 'FASE_CLASSIFICADA' in df.columns:
        fase = df['FASE_CLASSIFICADA']
        dias = df.get('DIAS_RESTANTES', pd.Series([np.nan] * len(df)))
        
        # Tratar valores nulos
        dias = dias.fillna(9999)
        
        priority_conditions = [
            fase == '✅ Entramos',
            fase == '💼 Em Negociação',
            fase.isin(['🎉 Entregue', '🏡 Pronto Para Morar']),
            (fase == '🏁 Final de Obra') & (dias <= 90),
            (fase == '🏁 Final de Obra') & (dias > 90) & (dias <= 180),
            (fase == '🏁 Final de Obra') & (dias > 180),
            fase.isin(['🔨 Obra em Andamento', '🚧 Início de Obra']) & (dias <= 365),
            fase.isin(['🔨 Obra em Andamento', '🚧 Início de Obra']) & (dias > 365),
            fase.isin(['📢 Lançamento', '📅 Futuro Lançamento']),
            fase == '❌ Não Entramos'
        ]
        
        priority_choices = [
            '🟢 Ação Imediata', '🟠 Alta Prioridade', '🟡 Acompanhamento',
            '🔴 Urgente', '🟠 Alta', '🟡 Média', '🟠 Alta', '🟡 Média',
            '🔵 Planejamento', '⚪ Arquivado'
        ]
        
        df['PRIORIDADE'] = np.select(priority_conditions, priority_choices, default='⚪ Baixa')
    
    # 8. Converter colunas numéricas
    if 'APTO' in df.columns:
        df['APTO'] = pd.to_numeric(df['APTO'], errors='coerce')
    
    return df


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
                st.error("❌ Credenciais MongoDB incompletas nos Secrets.")
                st.stop()
            
            uri = f"mongodb+srv://{username}:{quote_plus(password)}@{cluster}/{database}?retryWrites=true&w=majority"
        
        client = MongoClient(uri, serverSelectionTimeoutMS=5000, connectTimeoutMS=5000)
        client.admin.command('ping')
        database_name = st.secrets.get("mongo", {}).get("MONGO_DATABASE", "tracecom_crm")
        return client[database_name]
    except (ServerSelectionTimeoutError, ConnectionFailure) as e:
        st.error(f"❌ Falha ao conectar ao MongoDB: {e}")
        st.stop()
    except Exception as e:
        st.error(f"❌ Erro inesperado: {e}")
        st.stop()


# ==================== FUNÇÕES DE BANCO DE DADOS OTIMIZADAS ====================
def save_prospeccao_data_super_rapido(db, df_prospeccao, metadata):
    """Salva dados - SEM NENHUM LOOP, usando inserção em lote puro"""
    collection = db["prospeccao_condominios"]
    meta_collection = db["prospeccao_meta"]
    batch_id = metadata["batch_id"]
    
    # Limpeza rápida em lote
    collection.delete_many({"_import_batch": batch_id})
    meta_collection.delete_many({"batch_id": batch_id})
    
    # PREPARAÇÃO SUPER RÁPIDA - TUDO VETORIZADO
    df = df_prospeccao.copy()
    
    # Converter todas as datas de uma vez (sem timezone)
    date_cols = df.select_dtypes(include=['datetime64']).columns.tolist()
    for col in date_cols:
        # Remover timezone se existir
        if df[col].dt.tz is not None:
            df[col] = df[col].dt.tz_localize(None)
        df[col] = df[col].where(df[col].notna(), None)
    
    # Adicionar metadados (vetorizado)
    df['_import_timestamp'] = datetime.now().replace(tzinfo=None)
    df['_import_batch'] = batch_id
    
    # Substituir NaN/NaT por None em TODO o DataFrame de uma vez
    df = df.where(pd.notna(df), None)
    
    # CONVERSÃO ÚNICA PARA DICT - A OPERAÇÃO MAIS RÁPIDA POSSÍVEL
    docs = df.to_dict('records')
    
    # Inserção em lote (ordered=False é mais rápido)
    if docs:
        collection.insert_many(docs, ordered=False)
    
    # Salvar metadados
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

    if "_id" in df_prospeccao.columns:
        df_prospeccao["_id"] = df_prospeccao["_id"].astype(str)
    else:
        df_prospeccao["_id"] = [str(i) for i in range(len(df_prospeccao))]

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
        
        clean_updates = {k: (None if (isinstance(v, str) and v.strip() == "") or pd.isna(v) else v) 
                        for k, v in updates.items() if k != "_id"}
        
        result = collection.update_one({"_id": obj_id}, {"$set": clean_updates})
        return result.modified_count > 0
    except Exception as e:
        st.error(f"Erro ao atualizar: {e}")
        return False


def insert_new_record(db, new_data):
    """Insere um novo registro manualmente"""
    try:
        collection = db["prospeccao_condominios"]
        
        # Criar DataFrame temporário para processamento vetorizado
        temp_df = pd.DataFrame([new_data])
        temp_df = processar_dataframe_prospeccao(temp_df)
        
        # Extrair o documento processado
        doc = temp_df.iloc[0].to_dict()
        
        doc["_import_timestamp"] = datetime.now().replace(tzinfo=None)
        doc["_import_batch"] = "manual_entry"
        
        # Converter NaN para None
        doc = {k: (None if pd.isna(v) else v) for k, v in doc.items()}
        
        collection.insert_one(doc)
        return True
    except Exception as e:
        st.error(f"Erro ao inserir: {e}")
        return False


# ==================== FUNÇÕES DE ANÁLISE OTIMIZADAS ====================
@st.cache_data
def analisar_por_construtora(df_prospeccao):
    """Análise consolidada por construtora - VETORIZADA"""
    if df_prospeccao.empty or "CONSTRUTORA" not in df_prospeccao.columns:
        return pd.DataFrame()
    
    df_copy = df_prospeccao.copy()
    if "APTO" in df_copy.columns:
        df_copy["APTO"] = pd.to_numeric(df_copy["APTO"], errors='coerce')
    
    construtora_stats = df_copy.groupby("CONSTRUTORA").agg(
        total_projetos=("NOME", "count"),
        total_apartamentos=("APTO", "sum"),
        projetos_entramos=("FASE_CLASSIFICADA", lambda x: (x == "✅ Entramos").sum()),
        projetos_negociacao=("FASE_CLASSIFICADA", lambda x: (x == "💼 Em Negociação").sum()),
        projetos_lancamento=("FASE_CLASSIFICADA", lambda x: (x == "📢 Lançamento").sum()),
        projetos_inicio_obra=("FASE_CLASSIFICADA", lambda x: (x == "🚧 Início de Obra").sum()),
        projetos_andamento=("FASE_CLASSIFICADA", lambda x: (x == "🔨 Obra em Andamento").sum()),
        projetos_final_obra=("FASE_CLASSIFICADA", lambda x: (x == "🏁 Final de Obra").sum()),
        projetos_entregue=("FASE_CLASSIFICADA", lambda x: (x == "🎉 Entregue").sum()),
        projetos_pronto_morar=("FASE_CLASSIFICADA", lambda x: (x == "🏡 Pronto Para Morar").sum()),
        projetos_futuro=("FASE_CLASSIFICADA", lambda x: (x == "📅 Futuro Lançamento").sum()),
        projetos_nao_entramos=("FASE_CLASSIFICADA", lambda x: (x == "❌ Não Entramos").sum())
    ).reset_index()

    construtora_stats["percentual_entregue"] = (construtora_stats["projetos_entregue"] / construtora_stats["total_projetos"] * 100).round(1)
    construtora_stats["percentual_em_obra"] = ((construtora_stats["projetos_inicio_obra"] + construtora_stats["projetos_andamento"] + construtora_stats["projetos_final_obra"]) / construtora_stats["total_projetos"] * 100).round(1)
    construtora_stats["percentual_oportunidades"] = ((construtora_stats["projetos_lancamento"] + construtora_stats["projetos_futuro"] + construtora_stats["projetos_negociacao"]) / construtora_stats["total_projetos"] * 100).round(1)

    return construtora_stats.sort_values("total_projetos", ascending=False).reset_index(drop=True)


@st.cache_data
def analisar_por_zona(df_prospeccao):
    """Análise consolidada por Zona/Região - OTIMIZADA"""
    if df_prospeccao.empty:
        return pd.DataFrame()
    
    col_zona = "Região" if "Região" in df_prospeccao.columns else "ZONA" if "ZONA" in df_prospeccao.columns else None
    if not col_zona:
        return pd.DataFrame()
    
    df_copy = df_prospeccao.copy()
    if "APTO" in df_copy.columns:
        df_copy["APTO"] = pd.to_numeric(df_copy["APTO"], errors='coerce')
    
    zona_stats = df_copy.groupby(col_zona).agg(
        total_projetos=("NOME", "count"),
        total_apartamentos=("APTO", "sum"),
        projetos_em_obra=("FASE_CLASSIFICADA", lambda x: x.isin(["🚧 Início de Obra", "🔨 Obra em Andamento", "🏁 Final de Obra"]).sum()),
        projetos_entregue=("FASE_CLASSIFICADA", lambda x: x.isin(["🎉 Entregue", "🏡 Pronto Para Morar"]).sum()),
        oportunidades=("FASE_CLASSIFICADA", lambda x: x.isin(["📢 Lançamento", "📅 Futuro Lançamento", "💼 Em Negociação", "✅ Entramos"]).sum())
    ).reset_index()

    zona_stats["percentual_em_obra"] = (zona_stats["projetos_em_obra"] / zona_stats["total_projetos"] * 100).round(1)
    zona_stats["percentual_entregue"] = (zona_stats["projetos_entregue"] / zona_stats["total_projetos"] * 100).round(1)
    zona_stats["percentual_oportunidades"] = (zona_stats["oportunidades"] / zona_stats["total_projetos"] * 100).round(1)

    return zona_stats.sort_values("total_projetos", ascending=False).reset_index(drop=True)


@st.cache_data
def timeline_entregas(df_prospeccao):
    """Prepara dados para timeline de entregas"""
    if "PREVISAO_ENTREGA" not in df_prospeccao.columns:
        return pd.DataFrame()
    
    df_timeline = df_prospeccao.copy()
    df_timeline["PREVISAO_ENTREGA"] = pd.to_datetime(df_timeline["PREVISAO_ENTREGA"], errors='coerce')
    df_timeline = df_timeline[df_timeline["PREVISAO_ENTREGA"].notna()].copy()
    
    if df_timeline.empty:
        return df_timeline

    hoje = datetime.now().replace(tzinfo=None, hour=0, minute=0, second=0, microsecond=0)
    df_timeline["DIAS_RESTANTES"] = (df_timeline["PREVISAO_ENTREGA"] - pd.Timestamp(hoje)).dt.days
    df_timeline["ANO_ENTREGA"] = df_timeline["PREVISAO_ENTREGA"].dt.year
    df_timeline["MES_ENTREGA"] = df_timeline["PREVISAO_ENTREGA"].dt.to_period('M')
    
    return df_timeline.sort_values("PREVISAO_ENTREGA")


# ==================== FUNÇÃO DE EXPORTAÇÃO OTIMIZADA ====================
def exportar_prospeccao_excel(df_prospeccao, df_construtoras, df_zonas):
    """Exporta dados de prospecção para Excel - SEM LOOPS DESNECESSÁRIOS"""
    output = io.BytesIO()
    
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        # ABA 1: RESUMO EXECUTIVO
        resumo_data = {
            'Métrica': [
                'Total de Projetos',
                'Total de Apartamentos',
                'Projetos em Obra',
                'Projetos Entregues',
                'Projetos "Entramos"',
                'Projetos "Em Negociação"',
                'Oportunidades (Lançamento/Futuro)',
                'Construtoras Ativas',
                'Regiões Atendidas'
            ],
            'Valor': [
                len(df_prospeccao),
                df_prospeccao['APTO'].fillna(0).sum() if 'APTO' in df_prospeccao.columns else 0,
                len(df_prospeccao[df_prospeccao['FASE_CLASSIFICADA'].isin(['🚧 Início de Obra', '🔨 Obra em Andamento', '🏁 Final de Obra'])]) if 'FASE_CLASSIFICADA' in df_prospeccao.columns else 0,
                len(df_prospeccao[df_prospeccao['FASE_CLASSIFICADA'].isin(['🎉 Entregue', '🏡 Pronto Para Morar'])]) if 'FASE_CLASSIFICADA' in df_prospeccao.columns else 0,
                len(df_prospeccao[df_prospeccao['FASE_CLASSIFICADA'] == '✅ Entramos']) if 'FASE_CLASSIFICADA' in df_prospeccao.columns else 0,
                len(df_prospeccao[df_prospeccao['FASE_CLASSIFICADA'] == '💼 Em Negociação']) if 'FASE_CLASSIFICADA' in df_prospeccao.columns else 0,
                len(df_prospeccao[df_prospeccao['FASE_CLASSIFICADA'].isin(['📢 Lançamento', '📅 Futuro Lançamento'])]) if 'FASE_CLASSIFICADA' in df_prospeccao.columns else 0,
                df_prospeccao['CONSTRUTORA'].nunique() if 'CONSTRUTORA' in df_prospeccao.columns else 0,
                df_prospeccao['Região'].nunique() if 'Região' in df_prospeccao.columns else (df_prospeccao['ZONA'].nunique() if 'ZONA' in df_prospeccao.columns else 0)
            ]
        }
        df_resumo = pd.DataFrame(resumo_data)
        df_resumo.to_excel(writer, sheet_name='📊 Resumo Executivo', index=False)
        
        # ABA 2: DADOS COMPLETOS
        df_prospeccao.to_excel(writer, sheet_name='📋 Completo', index=False)
        
        # ABAS POR FASE
        fases_map = {
            '✅ Entramos': '00_Entramos_Destaque',
            '💼 Em Negociação': '01_Em_Negociacao',
            '📢 Lançamento': '02_Lancamento',
            '🚧 Início de Obra': '03_Inicio_Obra',
            '🔨 Obra em Andamento': '04_Andamento',
            '🏁 Final de Obra': '05_Final_Obra',
            '🎉 Entregue': '06_Entregue',
            '🏡 Pronto Para Morar': '07_Pronto_Morar',
            '📅 Futuro Lançamento': '08_Futuro_Lancamento',
            '❌ Não Entramos': '09_Nao_Entramos'
        }
        
        cols_base = ['NOME', 'CONSTRUTORA', 'BAIRRO', 
                    'Região' if 'Região' in df_prospeccao.columns else 'ZONA', 
                    'ENDEREÇO', 'BLOCO', 'APTO', 'FASE_CLASSIFICADA', 'PRIORIDADE']
        
        for fase_padrao, nome_aba in fases_map.items():
            df_fase = df_prospeccao[df_prospeccao['FASE_CLASSIFICADA'] == fase_padrao].copy()
             
            if not df_fase.empty:
                cols_adicionais = ['VIABILIDADE', 'OBS', 'PREVISAO_ENTREGA', 'DIAS_RESTANTES', 'FASE_ORIGINAL']
                cols_existentes = [c for c in cols_adicionais if c in df_fase.columns]
                cols_final = [c for c in cols_base if c in df_fase.columns] + cols_existentes
                
                df_export = df_fase[cols_final].copy()
                 
                if 'PREVISAO_ENTREGA' in df_export.columns:
                    mask_notna = df_export['PREVISAO_ENTREGA'].notna()
                    df_export.loc[mask_notna, 'PREVISAO_ENTREGA'] = pd.to_datetime(df_export.loc[mask_notna, 'PREVISAO_ENTREGA']).dt.strftime('%d/%m/%Y')
                    df_export.loc[~mask_notna, 'PREVISAO_ENTREGA'] = ''
                
                nome_aba = nome_aba[:31]
                df_export.to_excel(writer, sheet_name=nome_aba, index=False)
        
        if not df_construtoras.empty:
            df_construtoras.to_excel(writer, sheet_name='10_Por_Construtora', index=False)
        
        if not df_zonas.empty:
            df_zonas.to_excel(writer, sheet_name='11_Por_Regiao', index=False)

    output.seek(0)
    return output


# ==================== INTERFACE STREAMLIT PRINCIPAL ====================
def render_prospeccao_condominios():
    st.title("🏗️ Prospecção de Condomínios")
    st.markdown("Acompanhamento de fases de construção por construtora e oportunidades de mercado")
    
    db = init_mongo()
    
    st.markdown("---")

    # GERENCIAMENTO DE DADOS
    st.subheader("📂 Gerenciamento de Dados")
    col1, col2 = st.columns([3, 1])

    with col1:
        uploaded_file = st.file_uploader(
            "📤 Importar Planilha de Prospecção", 
            type=["xlsx", "xls"], 
            help="Planilha com colunas: Região, BAIRRO, ENDEREÇO, NOME, BLOCO, APTO, CONSTRUTORA, ESTÁGIO, VIABILIDADE, OBS"
        )

    with col2:
        if st.button("🔄 Recarregar Últimos", type="primary", use_container_width=True):
            st.cache_data.clear()
            st.session_state["reload_prospeccao"] = True
            st.rerun()
        
        if st.button("🗑️ Limpar Dados", type="secondary", use_container_width=True):
            if st.session_state.get("confirm_delete_prospeccao"):
                deleted = clear_prospeccao_data(db)
                st.success(f"✅ {deleted} registros removidos!")
                st.session_state["confirm_delete_prospeccao"] = False
                st.cache_data.clear()
                if "df_prospeccao_cached" in st.session_state:
                    del st.session_state["df_prospeccao_cached"]
                st.rerun()
            else:
                st.warning("⚠️ Clique novamente para confirmar")
                st.session_state["confirm_delete_prospeccao"] = True

    # Mostrar metadados da última importação
    meta = db["prospeccao_meta"].find_one(sort=[("timestamp", -1)])
    if meta:
        ts = meta.get('timestamp')
        ts_str = ts.strftime("%d/%m/%Y %H:%M") if ts else "Data não disponível"
        st.info(f"""
        **Última Importação:**
        - 📅 {ts_str}
        - 🏗️ {meta['total_projetos']} projetos
        - 🏢 {len(meta.get('construtoras', []))} construtoras
        """)
    else:
        st.warning("⚠️ Nenhum dado importado ainda")

    st.markdown("---")

    # IMPORTAÇÃO DA PLANILHA (VERSÃO ULTRA RÁPIDA)
    if uploaded_file:
        with st.spinner('🚀 Processando planilha com engine otimizado...'):
            try:
                start_time = time.time()
                
                # Ler Excel de uma vez
                df_raw = pd.read_excel(uploaded_file, sheet_name=0)
                
                # Remover linha de cabeçalho duplicado se existir
                if len(df_raw) > 0:
                    primeira_linha = df_raw.iloc[0].astype(str).str.lower()
                    colunas_lower = [c.lower() for c in df_raw.columns]
                    if all(val in colunas_lower or val == 'nan' for val in primeira_linha):
                        df_raw = df_raw.iloc[1:].reset_index(drop=True)
                
                # Processar tudo de uma vez
                df_prospeccao = processar_dataframe_prospeccao(df_raw)
                
                # Calcular estatísticas
                construtoras_list = df_prospeccao['CONSTRUTORA'].dropna().unique().tolist() if 'CONSTRUTORA' in df_prospeccao.columns else []
                fases_count = df_prospeccao['FASE_CLASSIFICADA'].value_counts().to_dict()
                
                metadata = {
                    "timestamp": datetime.now().replace(tzinfo=None),
                    "batch_id": f"prospeccao_{datetime.now().strftime('%Y%m%d_%H%M%S')}",
                    "filename": uploaded_file.name,
                    "fases": fases_count,
                    "construtoras": construtoras_list
                }
                
                # Salvar no MongoDB
                if save_prospeccao_data_super_rapido(db, df_prospeccao, metadata):
                    elapsed_time = time.time() - start_time
                    st.success(f"✅ Dados importados! {len(df_prospeccao)} projetos de {len(construtoras_list)} construtoras (Tempo: {elapsed_time:.2f}s)")
                    st.balloons()
                    st.cache_data.clear()
                    if "df_prospeccao_cached" in st.session_state:
                        del st.session_state["df_prospeccao_cached"]
                    st.rerun()
                    
            except Exception as e:
                st.error(f"❌ Erro ao processar planilha: {str(e)}")
                import traceback
                with st.expander("Detalhes técnicos do erro"):
                    st.code(traceback.format_exc())

    # CARREGAMENTO DOS DADOS
    elif st.session_state.get("reload_prospeccao") or "df_prospeccao_cached" not in st.session_state:
        with st.spinner('🔄 Carregando dados do banco...'):
            start_time = time.time()
            result = load_latest_prospeccao(db)
            if result[0] is not None:
                df_prospeccao, meta = result
                
                # Verificar e processar colunas faltantes
                if "FASE_CLASSIFICADA" not in df_prospeccao.columns and "ESTÁGIO" in df_prospeccao.columns:
                    df_prospeccao = processar_dataframe_prospeccao(df_prospeccao)
                
                st.session_state["df_prospeccao_cached"] = df_prospeccao
                st.session_state["meta_cached"] = meta
                
                elapsed_time = time.time() - start_time
                st.success(f"📦 Dados carregados! (Tempo: {elapsed_time:.2f}s)")
            else:
                st.info("👆 Faça upload da planilha para começar")
                return
    else:
        df_prospeccao = st.session_state["df_prospeccao_cached"]
        meta = st.session_state["meta_cached"]

    if "reload_prospeccao" in st.session_state:
        del st.session_state["reload_prospeccao"]

    # VERIFICAR SE HÁ DADOS
    if df_prospeccao is None or df_prospeccao.empty:
        st.info("👆 Faça upload da planilha para visualizar os dados")
        return

    # ==================== ABAS PRINCIPAIS ====================
    tab_update, tab_new, tab_dash1, tab_dash2, tab_dash3, tab_dash4, tab_dash5 = st.tabs([
        "✏️ Atualizar Empreendimentos", 
        "➕ Novo Cadastro",
        "📊 Por Construtora", 
        "🗺️ Por Região", 
        "⏱️ Timeline", 
        "🎯 Priorização", 
        "📋 Lista Completa"
    ])

    # ABA: ATUALIZAR EMPREENDIMENTOS
    with tab_update:
        st.header("✏️ Atualização de Cadastros")
        st.markdown("Filtre os empreendimentos e edite diretamente na tabela abaixo.")
        
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
        
        if not df_filtered.empty and "_id" in df_filtered.columns:
            cols_to_edit = ["NOME", "CONSTRUTORA", "BAIRRO", "Região" if "Região" in df_filtered.columns else "ZONA", 
                            "ESTÁGIO", "VIABILIDADE", "APTO", "OBS", "PREVISAO_ENTREGA"]
            
            cols_existing = [c for c in cols_to_edit if c in df_filtered.columns]
            df_edit = df_filtered[cols_existing + ["_id"]].copy()
            
            column_config = {
                "ESTÁGIO": st.column_config.SelectboxColumn(
                    "Estágio da Obra",
                    options=[
                        "✅ Entramos", "💼 Em Negociação", "📢 Lançamento",
                        "🚧 Início de Obra", "🔨 Obra em Andamento", "🏁 Final de Obra",
                        "🎉 Entregue", "🏡 Pronto Para Morar", "📅 Futuro Lançamento", "❌ Não Entramos"
                    ],
                    required=True
                )
            }
            
            edited_df = st.data_editor(
                df_edit.drop(columns=["_id"]),
                key="editor_prospeccao",
                use_container_width=True,
                num_rows="fixed",
                column_config=column_config
            )
            
            if st.button("💾 Salvar Alterações", type="primary"):
                if isinstance(edited_df, dict):
                    edited_df = pd.DataFrame(edited_df)
                
                df_filtered_reset = df_filtered.reset_index(drop=True)
                edited_df_reset = edited_df.reset_index(drop=True)
                 
                success_count = 0
                progress_bar = st.progress(0)
                
                for i, row in edited_df_reset.iterrows():
                    if i >= len(df_filtered_reset):
                        break
                    
                    original_id = df_filtered_reset.iloc[i]["_id"]
                    updates = row.to_dict()
                    
                    # Recriar DataFrame temporário para processamento
                    temp_df = pd.DataFrame([updates])
                    temp_df = processar_dataframe_prospeccao(temp_df)
                    updates_processados = temp_df.iloc[0].to_dict()
                    
                    if update_single_record(db, original_id, updates_processados):
                        success_count += 1
                    
                    progress_bar.progress((i + 1) / len(edited_df_reset))
                
                progress_bar.empty()
                if success_count > 0:
                    st.success(f"✅ {success_count} registros atualizados!")
                    st.cache_data.clear()
                    if "df_prospeccao_cached" in st.session_state:
                        del st.session_state["df_prospeccao_cached"]
                    st.rerun()
        elif not df_filtered.empty:
            st.error("Erro: ID não encontrado nos dados.")
        else:
            st.info("Nenhum registro encontrado com esses filtros.")

    # ABA: NOVO CADASTRO
    with tab_new:
        st.header("➕ Novo Cadastro Manual")
        
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
                    "✅ Entramos", "💼 Em Negociação", "📢 Lançamento",
                    "🚧 Início de Obra", "🔨 Obra em Andamento", "🏁 Final de Obra",
                    "🎉 Entregue", "🏡 Pronto Para Morar", "📅 Futuro Lançamento", "❌ Não Entramos"
                ])
                viabilidade = st.text_area("Viabilidade / Observações", placeholder="Ex: Sim, contato feito. Previsão entrega 12/2025.")
                obs_geral = st.text_area("Observações Gerais")
            
            submitted = st.form_submit_button("Cadastrar Empreendimento")
            
            if submitted:
                if not nome or not construtora:
                    st.error("❌ Nome e Construtora são obrigatórios.")
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
                        st.success("✅ Empreendimento cadastrado!")
                        st.cache_data.clear()
                        if "df_prospeccao_cached" in st.session_state:
                            del st.session_state["df_prospeccao_cached"]
                        st.rerun()
                    else:
                        st.error("❌ Erro ao cadastrar.")

    # DASHBOARDS (apenas se houver dados)
    if df_prospeccao is not None and not df_prospeccao.empty:
        
        with tab_dash1:
            st.header("📊 Análise por Construtora")
            df_construtoras = analisar_por_construtora(df_prospeccao)
            if not df_construtoras.empty:
                construtoras_disp = df_construtoras["CONSTRUTORA"].dropna().unique().tolist()
                default_construtoras = construtoras_disp[:5] if len(construtoras_disp) >= 5 else construtoras_disp
                
                construtoras_sel = st.multiselect(
                    "Filtrar Construtoras", options=construtoras_disp, default=default_construtoras, key="construtoras_filter"
                )
                
                if construtoras_sel:
                    df_construtoras_filt = df_construtoras[df_construtoras["CONSTRUTORA"].isin(construtoras_sel)]
                    
                    col1, col2 = st.columns(2)
                    with col1:
                        fig1 = px.bar(df_construtoras_filt.head(10), x="total_projetos", y="CONSTRUTORA", orientation="h", 
                                     title="Top 10 por Projetos", color="total_projetos", color_continuous_scale="Blues")
                        fig1.update_layout(height=400)
                        st.plotly_chart(fig1, use_container_width=True)
                    
                    with col2:
                        fig2 = px.bar(df_construtoras_filt.head(10), x="total_apartamentos", y="CONSTRUTORA", orientation="h", 
                                     title="Top 10 por APTs", color="total_apartamentos", color_continuous_scale="Greens")
                        fig2.update_layout(height=400)
                        st.plotly_chart(fig2, use_container_width=True)
                    
                    st.dataframe(df_construtoras_filt[["CONSTRUTORA", "total_projetos", "total_apartamentos", 
                                                       "percentual_entregue", "percentual_em_obra", "percentual_oportunidades"]], 
                                use_container_width=True)
            else:
                st.warning("Dados insuficientes para análise por construtora")
        
        with tab_dash2:
            st.header("🗺️ Análise por Região")
            df_zonas = analisar_por_zona(df_prospeccao)
            if not df_zonas.empty:
                col_zona = df_zonas.columns[0]
                fig_zona = px.bar(df_zonas, x=col_zona, y="total_projetos", title="Projetos por Região", 
                                 color="total_projetos", color_continuous_scale="Reds", text="total_projetos")
                fig_zona.update_traces(texttemplate='%{text}', textposition='outside')
                st.plotly_chart(fig_zona, use_container_width=True)
                st.dataframe(df_zonas, use_container_width=True)
            else:
                st.warning("Dados insuficientes para análise por região")
        
        with tab_dash3:
            st.header("⏱️ Timeline de Entregas")
            df_timeline = timeline_entregas(df_prospeccao)
            if not df_timeline.empty:
                anos_disp = sorted(df_timeline["ANO_ENTREGA"].dropna().unique().astype(int))
                if anos_disp:
                    ano_sel = st.selectbox("Filtrar por Ano", options=anos_disp, index=len(anos_disp)-1)
                    df_timeline_filt = df_timeline[df_timeline["ANO_ENTREGA"] == ano_sel]
                    
                    if not df_timeline_filt.empty:
                        st.markdown(f"### Entregas Previstas para {ano_sel}")
                        entregas_por_mes = df_timeline_filt.groupby("MES_ENTREGA").size().reset_index(name="total")
                        entregas_por_mes["MES_ENTREGA"] = entregas_por_mes["MES_ENTREGA"].astype(str)
                        fig = px.bar(entregas_por_mes, x="MES_ENTREGA", y="total", title=f"Distribuição Mensal ({ano_sel})")
                        st.plotly_chart(fig, use_container_width=True)
            else:
                st.warning("Sem dados de previsão de entrega")
        
        with tab_dash4:
            st.header("🎯 Priorização de Ações")
            if "PRIORIDADE" in df_prospeccao.columns:
                fig_pri = px.pie(values=df_prospeccao["PRIORIDADE"].value_counts().values, 
                                names=df_prospeccao["PRIORIDADE"].value_counts().index, 
                                title="Distribuição de Prioridades")
                st.plotly_chart(fig_pri, use_container_width=True)
                
                prioridades_disp = df_prospeccao["PRIORIDADE"].unique().tolist()
                # CORREÇÃO: Verificar quais prioridades existem antes de definir defaults
                default_prioridades = [p for p in ["🟢 Ação Imediata", "🟠 Alta Prioridade", "🔴 Urgente"] if p in prioridades_disp]
                if not default_prioridades and prioridades_disp:
                    default_prioridades = [prioridades_disp[0]]
                
                prioridade_sel = st.multiselect("Filtrar por Prioridade", options=prioridades_disp, 
                                               default=default_prioridades)
                if prioridade_sel:
                    df_prioridade = df_prospeccao[df_prospeccao["PRIORIDADE"].isin(prioridade_sel)]
                    st.dataframe(df_prioridade[["NOME", "CONSTRUTORA", "BAIRRO", "FASE_CLASSIFICADA", "PRIORIDADE"]], 
                                use_container_width=True)
            else:
                st.warning("Dados de prioridade indisponíveis")
        
        with tab_dash5:
            st.header("📋 Lista Completa de Projetos")
            
            # Filtros
            col1, col2, col3 = st.columns(3)
            with col1:
                if "Região" in df_prospeccao.columns:
                    regioes = st.multiselect("Região", options=df_prospeccao["Região"].dropna().unique())
                else:
                    regioes = []
            with col2:
                if "CONSTRUTORA" in df_prospeccao.columns:
                    construtoras = st.multiselect("Construtora", options=df_prospeccao["CONSTRUTORA"].dropna().unique())
                else:
                    construtoras = []
            with col3:
                if "FASE_CLASSIFICADA" in df_prospeccao.columns:
                    fases = st.multiselect("Fase", options=df_prospeccao["FASE_CLASSIFICADA"].dropna().unique())
                else:
                    fases = []
            
            df_filt = df_prospeccao.copy()
            if regioes:
                df_filt = df_filt[df_filt["Região"].isin(regioes)]
            if construtoras:
                df_filt = df_filt[df_filt["CONSTRUTORA"].isin(construtoras)]
            if fases:
                df_filt = df_filt[df_filt["FASE_CLASSIFICADA"].isin(fases)]
            
            st.markdown(f"**{len(df_filt)} projetos encontrados**")
            
            colunas_display = ["NOME", "CONSTRUTORA", "BAIRRO", "Região", "FASE_CLASSIFICADA", "APTO", "PRIORIDADE"]
            colunas_existentes = [c for c in colunas_display if c in df_filt.columns]
            st.dataframe(df_filt[colunas_existentes], use_container_width=True)
            
            # Exportação
            st.markdown("---")
            col_exp1, col_exp2 = st.columns([3, 1])
            with col_exp1:
                df_construtoras_resumo = analisar_por_construtora(df_filt)
                df_zonas_resumo = analisar_por_zona(df_filt)
                excel_buffer = exportar_prospeccao_excel(df_filt, df_construtoras_resumo, df_zonas_resumo)
                
                st.download_button(
                    label="📥 Exportar para Excel",
                    data=excel_buffer,
                    file_name=f"prospeccao_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx",
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    use_container_width=True
                )
            with col_exp2:
                st.info("Exporta com abas separadas por fase!")


# ==================== PONTO DE ENTRADA ====================
if __name__ == "__main__":
    render_prospeccao_condominios()
