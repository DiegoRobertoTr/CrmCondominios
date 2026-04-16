import streamlit as st
import pandas as pd
import numpy as np
import plotly.express as px
import plotly.graph_objects as go
from datetime import datetime, timezone, date
from pymongo import MongoClient, UpdateOne
from pymongo.errors import ServerSelectionTimeoutError, ConnectionFailure
from urllib.parse import quote_plus
import io
import re
import calendar
from bson.objectid import ObjectId
import time

# ==================== FUNÇÕES UTILITÁRIAS VETORIZADAS ====================

@st.cache_data
def classificar_fase_vetorizado(fases_series):
    """Versão vetorizada para classificar fases - OTIMIZADA E SEGURA"""
    if fases_series is None or len(fases_series) == 0:
        return pd.Series([], dtype='object')
        
    fases_lower = fases_series.fillna('').astype(str).str.lower().str.strip()
    
    conditions = {
        '✅ Entramos': fases_lower.str.contains('entramos|entrada confirmada|projeto aceito|ganhamos|contratado', na=False),
        '💼 Em Negociação': fases_lower.str.contains('em negociação|negociando|tratativa|proposta|estudo|análise|avaliação', na=False),
        '📢 Lançamento': fases_lower.str.contains('lançamento|lancamento|vendas|grupo em formação|pré-venda', na=False),
        ' Início de Obra': fases_lower.str.contains('início de obra|inicio de obra|inicial|fundação|estrutura|começando', na=False),
        '🔨 Obra em Andamento': fases_lower.str.contains('obra em andamento|andamento|intermediário|intermediario|em construção|50%|60%|70%|80%', na=False),
        '🏁 Final de Obra': fases_lower.str.contains('final de obra|fase final|acabamento|estágio final|estagio final|terminando', na=False),
        '🎉 Entregue': fases_lower.str.contains('entregue|entregues|finalizado|concluído|concluido', na=False),
        ' Pronto Para Morar': fases_lower.str.contains('pronto para morar|pronto pra morar|habite-se|disponível', na=False),
        '📅 Futuro Lançamento': fases_lower.str.contains('futuro|planejado|terreno|futuro lançamento|previsão|previsto', na=False),
        '❌ Não Entramos': fases_lower.str.contains('não entramos|nao entramos|perdido|embargado|sem viabilidade|não autorizado|descartado', na=False)
    }

    # Default
    resultado = pd.Series('💼 Em Negociação', index=fases_series.index, dtype='object')
    
    for fase, cond in conditions.items():
        resultado[cond] = fase

    return resultado

@st.cache_data
def extrair_previsao_entrega_vetorizado(viabilidade_series):
    """Versão vetorizada para extrair previsão de entrega - ROBUSTA CONTRA ERROS"""
    if viabilidade_series is None or len(viabilidade_series) == 0:
        return pd.Series([], dtype='datetime64[ns]')
        
    viabilidade_str = viabilidade_series.fillna('').astype(str)
    
    # Inicializar resultado com NaT (Not a Time)
    resultado = pd.Series(pd.NaT, index=viabilidade_str.index, dtype='datetime64[ns]')

    try:
        # Primeiro: formato DD/MM/YYYY
        data_encontrada = viabilidade_str.str.extract(r'(\d{2}/\d{2}/\d{4})', expand=False)
        mask_ddmmyyyy = data_encontrada.notna()
        if mask_ddmmyyyy.any():
            resultado[mask_ddmmyyyy] = pd.to_datetime(data_encontrada[mask_ddmmyyyy], format='%d/%m/%Y', errors='coerce')

        # Segundo: formato DD/MM/YY (apenas onde ainda não encontrou)
        mask_restante = resultado.isna()
        if mask_restante.any():
            data_ddmmyy = viabilidade_str[mask_restante].str.extract(r'(\d{2}/\d{2}/\d{2})', expand=False)
            mask_ddmmyy = data_ddmmyy.notna()
            if mask_ddmmyy.any():
                idx = resultado[mask_restante].index[mask_ddmmyy]
                # Cuidado com anos 2 dígitos, pandas assume 19xx ou 20xx dependendo da configuração, coerce ajuda
                resultado.loc[idx] = pd.to_datetime(data_ddmmyy[mask_ddmmyy], format='%d/%m/%y', errors='coerce')

        # Terceiro: formato YYYY-MM-DD (ISO)
        mask_restante = resultado.isna()
        if mask_restante.any():
            data_iso = viabilidade_str[mask_restante].str.extract(r'(\d{4}-\d{2}-\d{2})', expand=False)
            mask_iso = data_iso.notna()
            if mask_iso.any():
                idx = resultado[mask_restante].index[mask_iso]
                resultado.loc[idx] = pd.to_datetime(data_iso[mask_iso], format='%Y-%m-%d', errors='coerce')

        # Quarto: formato MM/YYYY (adiciona dia 01)
        mask_restante = resultado.isna()
        if mask_restante.any():
            data_mes_ano = viabilidade_str[mask_restante].str.extract(r'(\d{2}/\d{4})', expand=False)
            mask_mes_ano = data_mes_ano.notna()
            if mask_mes_ano.any():
                idx = resultado[mask_restante].index[mask_mes_ano]
                data_com_dia = '01/' + data_mes_ano[mask_mes_ano]
                resultado.loc[idx] = pd.to_datetime(data_com_dia, format='%d/%m/%Y', errors='coerce')
                
    except Exception as e:
        st.warning(f"Aviso ao processar datas: {e}. Algumas datas podem não ter sido extraídas.")
        
    return resultado

@st.cache_data
def calcular_prioridade_vetorizado(df):
    """Versão vetorizada para calcular prioridades"""
    if df.empty:
        return pd.Series([], dtype='object')
        
    fase = df['FASE_CLASSIFICADA'].fillna('')
    dias = df.get('DIAS_RESTANTES', pd.Series([None] * len(df)))
    
    # Default
    prioridade = pd.Series('⚪ Baixa', index=df.index)

    # Regras específicas
    prioridade[fase == '✅ Entramos'] = ' Ação Imediata'
    prioridade[fase == '💼 Em Negociação'] = '🟠 Alta Prioridade'
    prioridade[fase.isin(['🎉 Entregue', ' Pronto Para Morar'])] = ' Acompanhamento'

    # Lógica para Final de Obra
    if 'DIAS_RESTANTES' in df.columns:
        mask_final_obra = fase == '🏁 Final de Obra'
        if mask_final_obra.any():
            # Garantir que dias seja numérico para comparação
            dias_num = pd.to_numeric(dias, errors='coerce')
            prioridade[mask_final_obra & (dias_num <= 90)] = '🔴 Urgente'
            prioridade[mask_final_obra & (dias_num > 90) & (dias_num <= 180)] = '🟠 Alta'
            prioridade[mask_final_obra & (dias_num > 180)] = '🟡 Média'

        # Lógica para Obra em Andamento / Início
        mask_obra = fase.isin([' Obra em Andamento', '🚧 Início de Obra'])
        if mask_obra.any():
            prioridade[mask_obra & (dias_num <= 365)] = '🟠 Alta'
            prioridade[mask_obra & (dias_num > 365)] = '🟡 Média'

    prioridade[fase.isin(['📢 Lançamento', '📅 Futuro Lançamento'])] = '🔵 Planejamento'
    prioridade[fase == '❌ Não Entramos'] = '⚪ Arquivado'

    return prioridade

@st.cache_data
def calcular_dias_para_entrega_vetorizado(previsao_series):
    """Versão vetorizada para calcular dias restantes"""
    if previsao_series is None or len(previsao_series) == 0:
        return pd.Series([], dtype='float64')
        
    hoje = datetime.now().replace(tzinfo=None)
    # Garante que é datetime
    previsao_dt = pd.to_datetime(previsao_series, errors='coerce')
    
    # Calcula diferença
    diff = (previsao_dt - pd.Timestamp(hoje))
    return diff.dt.days

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
        st.error(f"❌ Falha ao conectar ao MongoDB:\n`{type(e).__name__}: {e}`")
        st.stop()
    except Exception as e:
        st.error(f"❌ Erro inesperado ao conectar: {type(e).__name__}: {e}")
        st.stop()

# ==================== FUNÇÕES DE BANCO DE DADOS OTIMIZADAS ====================

def save_prospeccao_data(db, df_prospeccao, metadata):
    """Salva dados de prospecção no MongoDB - COM LIMPEZA CORRETA"""
    collection = db["prospeccao_condominios"]
    meta_collection = db["prospeccao_meta"]
    batch_id = metadata["batch_id"]
    
    # ✅ Limpar APENAS dados do batch anterior para evitar duplicidade massiva
    ultimo_meta = meta_collection.find_one(sort=[("timestamp", -1)])
    if ultimo_meta:
        batch_anterior = ultimo_meta.get("batch_id")
        if batch_anterior and batch_anterior != batch_id:
            removidos = collection.delete_many({"_import_batch": batch_anterior})
            if removidos.deleted_count > 0:
                st.info(f"️ Removidos {removidos.deleted_count} registros do batch anterior automaticamente.")

    # Remover metadados antigos (opcional, mantém histórico se quiser, aqui limpa tudo menos o atual)
    # meta_collection.delete_many({}) 

    # Preparar dados
    df_para_salvar = df_prospeccao.copy()

    # ✅ REMOVER COLUNAS QUE CAUSAM PROBLEMAS NO MONGO OU SÃO REDUNDANTES
    colunas_para_remover = ['Prazo Medio', 'Prazo_Medio', 'prazo_medio', 'Prazo médio']
    for col in colunas_para_remover:
        if col in df_para_salvar.columns:
            df_para_salvar = df_para_salvar.drop(columns=[col])

    # ✅ CONVERTER DATAS PARA FORMATO COMPATÍVEL
    if 'Data da Atualização' in df_para_salvar.columns:
        # Tenta converter, se falhar vira NaT
        df_para_salvar['Data da Atualização'] = pd.to_datetime(df_para_salvar['Data da Atualização'], errors='coerce')

    if 'Previsão de Entrega' in df_para_salvar.columns:
        df_para_salvar['Previsão de Entrega'] = pd.to_datetime(df_para_salvar['Previsão de Entrega'], errors='coerce')

    if 'PREVISAO_ENTREGA' in df_para_salvar.columns:
        df_para_salvar['PREVISAO_ENTREGA'] = pd.to_datetime(df_para_salvar['PREVISAO_ENTREGA'], errors='coerce')

    # ✅ GARANTIR QUE COLUNAS DE TEXTO SEJAM STRINGS LIMPAS
    colunas_texto = ['VIABILIDADE', 'OBS', 'ESTÁGIO', 'FASE_ORIGINAL', 'FASE_CLASSIFICADA', 
                     'PRIORIDADE', 'CONSTRUTORA', 'NOME', 'BAIRRO', 'Região', 'ENDEREÇO', 'BLOCO']
    for col in colunas_texto:
        if col in df_para_salvar.columns:
            df_para_salvar[col] = df_para_salvar[col].astype(str).fillna('')
            # Remove strings 'nan', 'None', etc que viraram texto
            df_para_salvar[col] = df_para_salvar[col].replace(['nan', 'NaT', 'None', 'nat', 'NaN', ''], '')

    # ✅ TRATAR VALORES NUMÉRICOS
    if 'APTO' in df_para_salvar.columns:
        df_para_salvar['APTO'] = pd.to_numeric(df_para_salvar['APTO'], errors='coerce').fillna(0).astype(int)

    if 'DIAS_RESTANTES' in df_para_salvar.columns:
        df_para_salvar['DIAS_RESTANTES'] = pd.to_numeric(df_para_salvar['DIAS_RESTANTES'], errors='coerce')

    if 'BLOCO' in df_para_salvar.columns:
        df_para_salvar['BLOCO'] = pd.to_numeric(df_para_salvar['BLOCO'], errors='coerce').fillna(0).astype(int)

    # Adicionar metadados de importação
    df_para_salvar["_import_timestamp"] = datetime.now().replace(tzinfo=None)
    df_para_salvar["_import_batch"] = batch_id

    # Substituir valores problemáticos para o Mongo (NaT -> None, inf -> None)
    df_para_salvar = df_para_salvar.replace({pd.NaT: None, np.nan: None, float('inf'): None, float('-inf'): None})

    # Converter para lista de dicionários
    docs = df_para_salvar.to_dict('records')

    # Inserir novos dados em lotes (Batch Insert)
    if docs:
        batch_size = 500
        total = len(docs)
        for i in range(0, total, batch_size):
            batch = docs[i:i+batch_size]
            collection.insert_many(batch)

    # Salvar/Sobrescrever metadados do batch atual
    # Primeiro remove o meta antigo desse batch se existir (segurança)
    meta_collection.delete_one({"batch_id": batch_id})
    
    meta_collection.insert_one({
        "batch_id": batch_id,
        "timestamp": datetime.now().replace(tzinfo=None),
        "total_projetos": len(df_prospeccao),
        "fases": metadata.get("fases", {}),
        "construtoras": metadata.get("construtoras", [])
    })

    return True

def clear_prospeccao_data(db, batch_id=None):
    """Limpa dados de prospecção"""
    collection = db["prospeccao_condominios"]
    meta_collection = db["prospeccao_meta"]
    if batch_id:
        result = collection.delete_many({"_import_batch": batch_id})
        meta_collection.delete_many({"batch_id": batch_id})
        return result.deleted_count
    else:
        result = collection.delete_many({})
        meta_collection.delete_many({})
        return result.deleted_count

def limpar_todas_duplicatas(db):
    """LIMPEZA TOTAL - Remove TODOS os registros do banco"""
    collection = db["prospeccao_condominios"]
    meta_collection = db["prospeccao_meta"]
    total_antes = collection.count_documents({})

    if total_antes > 0:
        collection.delete_many({})
        meta_collection.delete_many({})
        return total_antes
    return 0

def verificar_duplicatas(db):
    """Verifica se há registros duplicados no banco"""
    collection = db["prospeccao_condominios"]
    pipeline = [
        {"$group": {
            "_id": "$_import_batch",
            "count": {"$sum": 1},
            "timestamp": {"$max": "$_import_timestamp"}
        }},
        {"$sort": {"timestamp": -1}}
    ]

    batches = list(collection.aggregate(pipeline))
    total = collection.count_documents({})
    return total, len(batches)

def update_records_batch_vectorized(db, df_original, df_editado, colunas_para_comparar):
    """Atualiza registros usando processamento 100% VETORIZADO"""
    try:
        mascaras_alteracao = {}
        for col in colunas_para_comparar:
            if col in df_original.columns and col in df_editado.columns:
                # Comparação segura tratando NaN
                orig = df_original[col].fillna('')
                edit = df_editado[col].fillna('')
                mascaras_alteracao[col] = orig != edit
        
        if not mascaras_alteracao:
            return 0
        
        df_mascaras = pd.DataFrame(mascaras_alteracao)
        linhas_com_alteracao = df_mascaras.any(axis=1)
        
        if not linhas_com_alteracao.any():
            return 0
        
        df_original_alterado = df_original[linhas_com_alteracao].copy()
        df_editado_alterado = df_editado[linhas_com_alteracao].copy()
        ids_alterados = df_original_alterado['_id'].values
        
        # Recalcular campos derivados se necessário
        if 'ESTÁGIO' in colunas_para_comparar and 'ESTÁGIO' in df_editado_alterado.columns:
            mask_estagio_alterado = df_editado_alterado['ESTÁGIO'] != df_original_alterado['ESTÁGIO']
            if mask_estagio_alterado.any():
                df_editado_alterado.loc[mask_estagio_alterado, 'FASE_CLASSIFICADA'] = \
                    classificar_fase_vetorizado(df_editado_alterado.loc[mask_estagio_alterado, 'ESTÁGIO'])
        
        if 'VIABILIDADE' in colunas_para_comparar and 'VIABILIDADE' in df_editado_alterado.columns:
            mask_viab_alterado = df_editado_alterado['VIABILIDADE'] != df_original_alterado['VIABILIDADE']
            if mask_viab_alterado.any():
                df_editado_alterado.loc[mask_viab_alterado, 'PREVISAO_ENTREGA'] = \
                    extrair_previsao_entrega_vetorizado(df_editado_alterado.loc[mask_viab_alterado, 'VIABILIDADE']) 
        
        if 'PREVISAO_ENTREGA' in colunas_para_comparar and 'PREVISAO_ENTREGA' in df_editado_alterado.columns:
            mask_previsao_alterado = df_editado_alterado['PREVISAO_ENTREGA'] != df_original_alterado['PREVISAO_ENTREGA']
            if mask_previsao_alterado.any():
                df_editado_alterado.loc[mask_previsao_alterado, 'DIAS_RESTANTES'] = \
                     calcular_dias_para_entrega_vetorizado(df_editado_alterado.loc[mask_previsao_alterado, 'PREVISAO_ENTREGA'])
        
        # Recalcular Prioridade se algo mudou
        colunas_que_afetam_prioridade = ['ESTÁGIO', 'FASE_CLASSIFICADA', 'PREVISAO_ENTREGA', 'DIAS_RESTANTES']
        mask_precisa_prioridade = pd.Series([False] * len(df_editado_alterado))
        for col in colunas_que_afetam_prioridade:
            if col in colunas_para_comparar and col in df_editado_alterado.columns:
                if col in df_original_alterado.columns:
                    orig = df_original_alterado[col].fillna('')
                    edit = df_editado_alterado[col].fillna('')
                    mask_precisa_prioridade |= (orig != edit)
        
        if mask_precisa_prioridade.any():
            df_temp = df_original_alterado.copy()
            for col in df_editado_alterado.columns:
                if col in df_temp.columns and col != '_id':
                    df_temp[col] = df_editado_alterado[col]
            
            df_temp['PRIORIDADE'] = calcular_prioridade_vetorizado(df_temp)
            df_editado_alterado.loc[mask_precisa_prioridade, 'PRIORIDADE'] = df_temp.loc[mask_precisa_prioridade, 'PRIORIDADE']
        
        bulk_operations = []
        collection = db["prospeccao_condominios"]
        
        for idx, record_id in enumerate(ids_alterados):
            updates = {}
            for col in colunas_para_comparar:
                if col in df_editado_alterado.columns and col in df_original_alterado.columns:
                    val_orig = df_original_alterado[col].iloc[idx]
                    val_edit = df_editado_alterado[col].iloc[idx]
                    
                    # Comparação final segura
                    if str(val_orig) != str(val_edit):
                        valor = val_edit
                        if pd.isna(valor) or valor == '':
                            valor = None
                        updates[col] = valor
            
            # Adicionar campos recalculados se existirem nas mudanças
            if 'FASE_CLASSIFICADA' in df_editado_alterado.columns and 'FASE_CLASSIFICADA' in colunas_para_comparar:
                 if str(df_original_alterado['FASE_CLASSIFICADA'].iloc[idx]) != str(df_editado_alterado['FASE_CLASSIFICADA'].iloc[idx]):
                    updates['FASE_CLASSIFICADA'] = df_editado_alterado['FASE_CLASSIFICADA'].iloc[idx]
            
            if 'PREVISAO_ENTREGA' in df_editado_alterado.columns:
                 if str(df_original_alterado['PREVISAO_ENTREGA'].iloc[idx]) != str(df_editado_alterado['PREVISAO_ENTREGA'].iloc[idx]):
                    updates['PREVISAO_ENTREGA'] = df_editado_alterado['PREVISAO_ENTREGA'].iloc[idx]
            
            if 'DIAS_RESTANTES' in df_editado_alterado.columns:
                 if str(df_original_alterado['DIAS_RESTANTES'].iloc[idx]) != str(df_editado_alterado['DIAS_RESTANTES'].iloc[idx]):
                    updates['DIAS_RESTANTES'] = df_editado_alterado['DIAS_RESTANTES'].iloc[idx]
            
            if 'PRIORIDADE' in df_editado_alterado.columns:
                 if str(df_original_alterado['PRIORIDADE'].iloc[idx]) != str(df_editado_alterado['PRIORIDADE'].iloc[idx]):
                    updates['PRIORIDADE'] = df_editado_alterado['PRIORIDADE'].iloc[idx]
            
            if updates:
                # Converter ID para ObjectId se for string
                if isinstance(record_id, str):
                    try:
                        oid = ObjectId(record_id)
                    except:
                        continue # Pula se ID inválido
                else:
                    oid = record_id
                    
                bulk_operations.append(UpdateOne({"_id": oid}, {"$set": updates}))
    
        if bulk_operations:
            result = collection.bulk_write(bulk_operations)
            return result.modified_count
    
        return 0
        
    except Exception as e:
        st.error(f"Erro na atualização em lote vetorizada: {e}")
        import traceback
        st.code(traceback.format_exc())
        return 0

@st.cache_data
def load_latest_prospeccao(_db):
    """Carrega últimos dados de prospecção - COM CACHE"""
    meta = _db["prospeccao_meta"].find_one(sort=[("timestamp", -1)])
    if not meta:
        return None, None
    collection = _db["prospeccao_condominios"]
    cursor = collection.find({"_import_batch": meta["batch_id"]})
    df_prospeccao = pd.DataFrame(list(cursor))

    if "_id" in df_prospeccao.columns:
        df_prospeccao["_id"] = df_prospeccao["_id"].astype(str)
    else:
        df_prospeccao["_id"] = [str(i) for i in range(len(df_prospeccao))]

    return df_prospeccao, meta

def insert_new_record(db, new_data):
    """Insere um novo registro manualmente"""
    try:
        collection = db["prospeccao_condominios"]
        doc = new_data.copy()
        
        if "ESTÁGIO" in doc:
            fase_series = pd.Series([doc["ESTÁGIO"]])
            doc["FASE_CLASSIFICADA"] = classificar_fase_vetorizado(fase_series).iloc[0]
        
        if "VIABILIDADE" in doc:
            viab_series = pd.Series([doc["VIABILIDADE"]])
            doc["PREVISAO_ENTREGA"] = extrair_previsao_entrega_vetorizado(viab_series).iloc[0]
        
        if doc.get("PREVISAO_ENTREGA"):
            previsao_series = pd.Series([doc["PREVISAO_ENTREGA"]])
            doc["DIAS_RESTANTES"] = calcular_dias_para_entrega_vetorizado(previsao_series).iloc[0]
        
        temp_df = pd.DataFrame([doc])
        doc["PRIORIDADE"] = calcular_prioridade_vetorizado(temp_df).iloc[0]
        
        doc["_import_timestamp"] = datetime.now().replace(tzinfo=None)
        doc["_import_batch"] = "manual_entry"
        
        for key, value in list(doc.items()):
            if isinstance(value, (pd.Timestamp, datetime)):
                doc[key] = None if pd.isna(value) else value
            elif pd.isna(value):   
                doc[key] = None
        
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
        projetos_lancamento=("FASE_CLASSIFICADA", lambda x: (x == " Lançamento").sum()),
        projetos_inicio_obra=("FASE_CLASSIFICADA", lambda x: (x == " Início de Obra").sum()),
        projetos_andamento=("FASE_CLASSIFICADA", lambda x: (x == " Obra em Andamento").sum()),
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
        projetos_em_obra=("FASE_CLASSIFICADA", lambda x: x.isin([" Início de Obra", "🔨 Obra em Andamento", "🏁 Final de Obra"]).sum()),
        projetos_entregue=("FASE_CLASSIFICADA", lambda x: x.isin(["🎉 Entregue", "🏡 Pronto Para Morar"]).sum()),
        oportunidades=("FASE_CLASSIFICADA", lambda x: x.isin(["📢 Lançamento", "📅 Futuro Lançamento", "💼 Em Negociação", "✅ Entramos"]).sum())
    ).reset_index()

    zona_stats["percentual_em_obra"] = (zona_stats["projetos_em_obra"] / zona_stats["total_projetos"] * 100).round(1)
    zona_stats["percentual_entregue"] = (zona_stats["projetos_entregue"] / zona_stats["total_projetos"] * 100).round(1)
    zona_stats["percentual_oportunidades"] = (zona_stats["oportunidades"] / zona_stats["total_projetos"] * 100).round(1)

    return zona_stats.sort_values("total_projetos", ascending=False).reset_index(drop=True)

@st.cache_data
def timeline_entregas(df_prospeccao):
    """Prepara dados para timeline de entregas - OTIMIZADA"""
    if "PREVISAO_ENTREGA" not in df_prospeccao.columns:
        return pd.DataFrame()
    df_timeline = df_prospeccao.copy()
    df_timeline["PREVISAO_ENTREGA"] = pd.to_datetime(df_timeline["PREVISAO_ENTREGA"], errors='coerce')
    df_timeline = df_timeline[df_timeline["PREVISAO_ENTREGA"].notna()].copy()

    if df_timeline.empty:
        return df_timeline

    df_timeline["DIAS_RESTANTES"] = calcular_dias_para_entrega_vetorizado(df_timeline["PREVISAO_ENTREGA"])
    df_timeline["ANO_ENTREGA"] = df_timeline["PREVISAO_ENTREGA"].dt.year
    df_timeline["MES_ENTREGA"] = df_timeline["PREVISAO_ENTREGA"].dt.to_period('M')

    return df_timeline.sort_values("PREVISAO_ENTREGA")

# ==================== FUNÇÃO DE EXPORTAÇÃO OTIMIZADA ====================

def exportar_prospeccao_excel(df_prospeccao, df_construtoras, df_zonas):
    """Exporta dados de prospecção para Excel - SEM LOOPS DESNECESSÁRIOS"""
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
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
                len(df_prospeccao[df_prospeccao['FASE_CLASSIFICADA'].isin(['🎉 Entregue', ' Pronto Para Morar'])]) if 'FASE_CLASSIFICADA' in df_prospeccao.columns else 0,
                len(df_prospeccao[df_prospeccao['FASE_CLASSIFICADA'] == '✅ Entramos']) if 'FASE_CLASSIFICADA' in df_prospeccao.columns else 0,
                len(df_prospeccao[df_prospeccao['FASE_CLASSIFICADA'] == '💼 Em Negociação']) if 'FASE_CLASSIFICADA' in df_prospeccao.columns else 0,
                len(df_prospeccao[df_prospeccao['FASE_CLASSIFICADA'].isin(['📢 Lançamento', '📅 Futuro Lançamento'])]) if 'FASE_CLASSIFICADA' in df_prospeccao.columns else 0,
                df_prospeccao['CONSTRUTORA'].nunique() if 'CONSTRUTORA' in df_prospeccao.columns else 0,
                df_prospeccao['Região'].nunique() if 'Região' in df_prospeccao.columns else (df_prospeccao['ZONA'].nunique() if 'ZONA' in df_prospeccao.columns else 0)
            ]
        }
        df_resumo = pd.DataFrame(resumo_data)
        df_resumo.to_excel(writer, sheet_name='📊 Resumo Executivo', index=False)
        df_prospeccao.to_excel(writer, sheet_name='📋 Completo', index=False)
        
        fases_map = {
            '✅ Entramos': '00_Entramos_Destaque',
            '💼 Em Negociação': '01_Em_Negociacao',
            '📢 Lançamento': '02_Lancamento',
            '🚧 Início de Obra': '03_Inicio_Obra',
            '🔨 Obra em Andamento': '04_Andamento',
            '🏁 Final de Obra': '05_Final_Obra',
            '🎉 Entregue': '06_Entregue',
            '🏡 Pronto Para Morar': '07_Pronto_Morar',
            ' Futuro Lançamento': '08_Futuro_Lancamento',
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

# ==================== INTERFACE STREAMLIT OTIMIZADA ====================

def render_prospeccao_condominios():
    st.title("️ Prospecção de Condomínios")
    st.markdown("Acompanhamento de fases de construção por construtora e oportunidades de mercado")
    db = init_mongo()

    st.markdown("---")

    # ==================== BOTÃO DE LIMPEZA TOTAL (Administrador) ====================
    with st.expander("⚠️ FERRAMENTAS DE MANUTENÇÃO (Administrador)", expanded=False):
        st.warning("️ Use estas ferramentas com cuidado! Elas removem dados permanentemente.")
        
        col_limpeza1, col_limpeza2, col_limpeza3 = st.columns(3)
        
        with col_limpeza1:
            if st.button("🔍 Verificar Duplicatas", key="btn_verificar"):
                total, num_batches = verificar_duplicatas(db)
                st.metric("Total de registros no banco", f"{total:,}")
                st.metric("Número de batches", num_batches)
                if num_batches > 1:
                    st.error(f"️ Atenção! {num_batches} batches encontrados. Isso indica duplicação!")
        
        with col_limpeza2:
            if st.button("🗑️ LIMPAR TODOS OS DADOS (URGENTE)", key="btn_limpar_tudo"):
                st.session_state['confirmar_limpeza_total'] = True
        
        with col_limpeza3:
            if st.button("🧹 Manter Apenas Último Lote", key="btn_manter_ultimo"):
                st.session_state['confirmar_manter_ultimo'] = True
        
        # Confirmação de limpeza total
        if st.session_state.get('confirmar_limpeza_total', False):
            st.error("🔴 CONFIRMAÇÃO NECESSÁRIA!")
            total_atual, _ = verificar_duplicatas(db)
            st.warning(f"This will remove ALL {total_atual:,} records. This action CANNOT be undone!")
            
            col_confirm1, col_confirm2 = st.columns(2)
            with col_confirm1:
                if st.button("✅ SIM, REMOVER TUDO", key="confirmar_sim"):
                    removidos = limpar_todas_duplicatas(db)
                    st.success(f"✅ {removidos:,} registros removidos com sucesso!")
                    st.session_state['confirmar_limpeza_total'] = False
                    st.cache_data.clear()
                    if "df_prospeccao_cached" in st.session_state:
                        del st.session_state["df_prospeccao_cached"]
                    st.rerun() # Rerun imediato sem sleep
            with col_confirm2:
                if st.button("❌ Cancelar", key="confirmar_nao"):
                    st.session_state['confirmar_limpeza_total'] = False
                    st.rerun()
        
        # Confirmação de manter apenas último lote
        if st.session_state.get('confirmar_manter_ultimo', False):
            st.info("ℹ️ Isso irá manter apenas o batch mais recente e remover os antigos.")
            
            col_confirm3, col_confirm4 = st.columns(2)
            with col_confirm3:
                if st.button("✅ Sim, manter apenas último", key="manter_sim"):
                    collection = db["prospeccao_condominios"]
                    meta_collection = db["prospeccao_meta"]
                    
                    ultimo_meta = meta_collection.find_one(sort=[("timestamp", -1)])
                    if ultimo_meta:
                        ultimo_batch = ultimo_meta.get("batch_id")
                        resultado = collection.delete_many({"_import_batch": {"$ne": ultimo_batch}})
                        meta_collection.delete_many({"batch_id": {"$ne": ultimo_batch}})
                        st.success(f"✅ Removidos {resultado.deleted_count:,} registros antigos. Mantido apenas o batch mais recente.")
                    else:
                        st.warning("Nenhum batch encontrado para manter.")
                    
                    st.session_state['confirmar_manter_ultimo'] = False
                    st.cache_data.clear()
                    if "df_prospeccao_cached" in st.session_state:
                        del st.session_state["df_prospeccao_cached"]
                    st.rerun()
            with col_confirm4:
                if st.button("❌ Cancelar", key="manter_nao"):
                    st.session_state['confirmar_manter_ultimo'] = False
                    st.rerun()

    st.markdown("---")

    # ==================== GERENCIAMENTO DE DADOS ====================
    st.subheader("📂 Gerenciamento de Dados")
    col1, col2 = st.columns([3, 1])

    with col1:
        uploaded_file = st.file_uploader(
            " Importar Planilha de Prospecção", 
            type=["xlsx", "xls"], 
            help="Planilha com colunas: Região, BAIRRO, ENDEREÇO, NOME, BLOCO, APTO, CONSTRUTORA, ESTÁGIO, VIABILIDADE, OBS"
        )

    with col2:
        if st.button("🔄 Recarregar Últimos", type="primary", use_container_width=True):
            st.cache_data.clear()
            st.session_state["reload_prospeccao"] = True
            st.rerun()
        
        if st.button("️ Limpar Dados", type="secondary", use_container_width=True):
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

    # ==================== IMPORTAÇÃO DA PLANILHA OTIMIZADA ====================
    if uploaded_file:
        start_time = time.time()
        progress_bar = st.progress(0)
        
        try:
            progress_bar.progress(10)
            df_prospeccao = pd.read_excel(uploaded_file, sheet_name=0)
            
            progress_bar.progress(30)
            # Verifica se a primeira linha é cabeçalho duplicado
            if len(df_prospeccao) > 0:
                primeira_linha = df_prospeccao.iloc[0].astype(str).str.lower()
                # Se a maioria dos valores da primeira linha forem iguais aos nomes das colunas (case insensitive), pula
                if all(val in [str(c).lower().strip() for c in df_prospeccao.columns] or val == 'nan' for val in primeira_linha):
                    df_prospeccao = df_prospeccao.iloc[1:].reset_index(drop=True)
            
            progress_bar.progress(50)
            if len(df_prospeccao) == 0:
                st.error("❌ A planilha está vazia após a limpeza inicial.")
                st.stop()

            # Normalização de colunas
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
                st.error("❌ Coluna 'ESTÁGIO' não encontrada na planilha! Verifique o cabeçalho.")
                st.stop()
            
            # Remover coluna problemática 'Prazo Medio' se existir
            if 'Prazo Medio' in df_prospeccao.columns:
                df_prospeccao = df_prospeccao.drop(columns=['Prazo Medio'])
            
            # Processamento Vetorizado
            df_prospeccao["FASE_CLASSIFICADA"] = classificar_fase_vetorizado(df_prospeccao["ESTÁGIO"])
            df_prospeccao["FASE_ORIGINAL"] = df_prospeccao["ESTÁGIO"]
            
            progress_bar.progress(80)
            if "VIABILIDADE" in df_prospeccao.columns:
                df_prospeccao["PREVISAO_ENTREGA"] = extrair_previsao_entrega_vetorizado(df_prospeccao["VIABILIDADE"])
            if "Previsão de Entrega" in df_prospeccao.columns:
                previsao2 = extrair_previsao_entrega_vetorizado(df_prospeccao["Previsão de Entrega"])
                if "PREVISAO_ENTREGA" in df_prospeccao.columns:
                    # Preenche onde estava vazio
                    df_prospeccao["PREVISAO_ENTREGA"] = df_prospeccao["PREVISAO_ENTREGA"].where(
                        df_prospeccao["PREVISAO_ENTREGA"].notna(), previsao2
                    )
                else:
                    df_prospeccao["PREVISAO_ENTREGA"] = previsao2
            
            progress_bar.progress(90)
            df_prospeccao["DIAS_RESTANTES"] = calcular_dias_para_entrega_vetorizado(df_prospeccao.get("PREVISAO_ENTREGA"))
            df_prospeccao["PRIORIDADE"] = calcular_prioridade_vetorizado(df_prospeccao)
            
            # Limpeza final de texto antes de salvar
            colunas_texto_limpeza = ['VIABILIDADE', 'OBS', 'ESTÁGIO', 'FASE_ORIGINAL']
            for col in colunas_texto_limpeza:
                if col in df_prospeccao.columns:
                    df_prospeccao[col] = df_prospeccao[col].astype(str).fillna('')
                    df_prospeccao[col] = df_prospeccao[col].replace(['nan', 'NaT', 'None', 'nat', 'NaN'], '')
            
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
                st.success(f"✅ Dados importados! {len(df_prospeccao)} projetos de {len(metadata['construtoras'])} construtoras (Tempo: {elapsed_time:.2f}s)")
                st.cache_data.clear()
                if "df_prospeccao_cached" in st.session_state:
                    del st.session_state["df_prospeccao_cached"]
                # Força reload na próxima iteração
                st.session_state["reload_prospeccao"] = True
                st.rerun()
                
        except Exception as e:
            st.error(f"❌ Erro ao processar planilha: {str(e)}")
            import traceback
            with st.expander("Detalhes técnicos do erro"):
                st.code(traceback.format_exc())
        finally:
            progress_bar.empty()

    # ==================== CARREGAMENTO COM CACHE ====================
    elif st.session_state.get("reload_prospeccao") or "df_prospeccao_cached" not in st.session_state:
        with st.spinner('🔄 Carregando dados do banco...'):
            start_time = time.time()
            result = load_latest_prospeccao(db)
            if result[0] is not None:
                df_prospeccao, meta = result
                
                # Garante que colunas calculadas existam (caso o schema mude no futuro)
                if "FASE_CLASSIFICADA" not in df_prospeccao.columns and "ESTÁGIO" in df_prospeccao.columns:
                    df_prospeccao["FASE_CLASSIFICADA"] = classificar_fase_vetorizado(df_prospeccao["ESTÁGIO"])
                
                if "PREVISAO_ENTREGA" not in df_prospeccao.columns and "VIABILIDADE" in df_prospeccao.columns:
                    df_prospeccao["PREVISAO_ENTREGA"] = extrair_previsao_entrega_vetorizado(df_prospeccao["VIABILIDADE"])
                
                if "DIAS_RESTANTES" not in df_prospeccao.columns and "PREVISAO_ENTREGA" in df_prospeccao.columns:
                    df_prospeccao["DIAS_RESTANTES"] = calcular_dias_para_entrega_vetorizado(df_prospeccao["PREVISAO_ENTREGA"])
                    
                if "PRIORIDADE" not in df_prospeccao.columns:
                    df_prospeccao["PRIORIDADE"] = calcular_prioridade_vetorizado(df_prospeccao)
                
                st.session_state["df_prospeccao_cached"] = df_prospeccao
                st.session_state["meta_cached"] = meta
                
                elapsed_time = time.time() - start_time
                st.success(f"📦 Dados carregados e otimizados! (Tempo: {elapsed_time:.2f}s)")
            else:
                st.info("👆 Faça upload da planilha para começar")
                return
    else:
        df_prospeccao = st.session_state["df_prospeccao_cached"]
        meta = st.session_state["meta_cached"]

    if "reload_prospeccao" in st.session_state:
        del st.session_state["reload_prospeccao"]

    # ==================== ABAS PRINCIPAIS ====================
    if df_prospeccao is not None and not df_prospeccao.empty:
        tab_update, tab_new, tab_dash1, tab_dash2, tab_dash3, tab_dash4, tab_dash5 = st.tabs([
            "✏️ Atualizar Empreendimentos", 
            "➕ Novo Cadastro",
            "📊 Por Construtora", 
            "🗺️ Por Região", 
            "⏱️ Timeline", 
            "🎯 Priorização", 
            "📋 Lista Completa"
        ])

        # --- LÓGICA DA ABA: ATUALIZAR EMPREENDIMENTOS ---
        with tab_update:
            st.header("✏️ Atualização de Cadastros")
            st.markdown("Filtre os empreendimentos e edite diretamente na tabela abaixo.")
            
            c1, c2, c3, c4 = st.columns(4)
            
            construtoras_opts = sorted(df_prospeccao["CONSTRUTORA"].dropna().unique().tolist()) if "CONSTRUTORA" in df_prospeccao.columns else []
            regioes_opts = sorted(df_prospeccao["Região"].dropna().unique().tolist()) if "Região" in df_prospeccao.columns else (sorted(df_prospeccao["ZONA"].dropna().unique().tolist()) if "ZONA" in df_prospeccao.columns else [])
            fases_opts = sorted(df_prospeccao["FASE_CLASSIFICADA"].dropna().unique().tolist()) if "FASE_CLASSIFICADA" in df_prospeccao.columns else []
            
            with c1:
                filter_construtora = st.multiselect("Construtora", options=construtoras_opts, placeholder="Todas", key="f_construtora_upd")
            with c2:
                filter_regiao = st.multiselect("Região/Zona", options=regioes_opts, placeholder="Todas", key="f_regiao_upd")
            with c3:
                filter_fase = st.multiselect("Estágio/Fase", options=fases_opts, placeholder="Todos", key="f_fase_upd")
            with c4:
                search_nome = st.text_input("Buscar por Nome", placeholder="Ex: MRV...", key="f_nome_upd")
            
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
                
                df_original_edit = df_filtered[cols_existing + ["_id"]].copy()
                df_edit_display = df_original_edit.drop(columns=["_id"]).copy()
                
                column_config = {
                    "ESTÁGIO": st.column_config.SelectboxColumn(
                        "Estágio da Obra",
                        options=[
                            "✅ Entramos", "💼 Em Negociação", "📢 Lançamento",
                            "🚧 Início de Obra", " Obra em Andamento", " Final de Obra",
                            "🎉 Entregue", " Pronto Para Morar", "📅 Futuro Lançamento", "❌ Não Entramos"
                        ],
                        required=True
                    )
                }
                
                edited_df = st.data_editor(
                    df_edit_display,
                    key="editor_prospeccao_vectorized",
                    use_container_width=True,
                    num_rows="fixed",
                    column_config=column_config
                )
                
                st.warning("️ Atenção: Ao editar a coluna 'ESTÁGIO', a 'Fase Classificada' será recalculada automaticamente ao salvar.")
                
                if st.button("💾 Salvar Alterações Selecionadas", type="primary", key="btn_save_updates"):
                    if isinstance(edited_df, dict):
                        edited_df = pd.DataFrame(edited_df)
                    
                    with st.spinner(f'🔄 Processando alterações de forma vetorizada...'):
                        colunas_para_comparar = cols_existing
                        modified_count = update_records_batch_vectorized(
                            db, 
                            df_original_edit, 
                            edited_df, 
                            colunas_para_comparar
                        )
                        
                        if modified_count > 0:
                            st.success(f"✅ {modified_count} registros atualizados com sucesso!")
                            st.cache_data.clear()
                            if "df_prospeccao_cached" in st.session_state:
                                del st.session_state["df_prospeccao_cached"]
                            st.rerun()
                        else:
                            st.info("ℹ️ Nenhuma alteração detectada ou erro ao salvar.")
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
                        "✅ Entramos", "💼 Em Negociação", "📢 Lançamento",
                        "🚧 Início de Obra", "🔨 Obra em Andamento", "🏁 Final de Obra",
                        "🎉 Entregue", " Pronto Para Morar", "📅 Futuro Lançamento", "❌ Não Entramos"
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
                            st.success("✅ Empreendimento cadastrado com sucesso!")
                            st.cache_data.clear()
                            if "df_prospeccao_cached" in st.session_state:
                                del st.session_state["df_prospeccao_cached"]
                            st.rerun()
                        else:
                            st.error("❌ Erro ao cadastrar. Verifique os logs.")

        # ==================== DASHBOARD PRINCIPAL ====================
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
                    fases_cols = ["projetos_entramos", "projetos_negociacao", "projetos_lancamento", "projetos_inicio_obra", "projetos_andamento", "projetos_final_obra", "projetos_entregue", "projetos_pronto_morar", "projetos_futuro"]
                    fases_labels = ["✅ Entramos", "💼 Negociação", " Lançam.", "🚧 Início", "🔨 Andamento", " Final", " Entregue", "🏡 P/Morar", "📅 Futuro"]
                    
                    df_fases_plot = df_construtoras_filt.head(8).copy().set_index("CONSTRUTORA")[fases_cols]
                    df_fases_plot.columns = fases_labels
                    
                    fig3 = px.bar(df_fases_plot, barmode="stack", title="Distribuição de Fases (Top 8)", color_discrete_sequence=px.colors.qualitative.Set3)
                    fig3.update_layout(height=500)
                    st.plotly_chart(fig3, use_container_width=True)
                       
                    st.markdown("### Tabela Detalhada")
                    df_display = df_construtoras_filt[["CONSTRUTORA", "total_projetos", "total_apartamentos", "percentual_entregue", "percentual_em_obra", "percentual_oportunidades"]].copy()
                    df_display["total_apartamentos"] = df_display["total_apartamentos"].apply(lambda x: f"{int(x):,}".replace(",", ".") if pd.notna(x) else "0")
                    df_display["percentual_entregue"] = df_display["percentual_entregue"].apply(lambda x: f"{x:.1f}%")
                    df_display["percentual_em_obra"] = df_display["percentual_em_obra"].apply(lambda x: f"{x:.1f}%")
                    df_display["percentual_oportunidades"] = df_display["percentual_oportunidades"].apply(lambda x: f"{x:.1f}%")
                    df_display.columns = ["Construtora", "Projetos", "Total APTs", "% Entregue", "% Em Obra", "% Oportunidades"]
                    st.dataframe(df_display, use_container_width=True)
            else:
                st.warning("⚠️ Dados insuficientes para análise por construtora")
        
        with tab_dash2:
            st.header("🗺️ Análise por Região")
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
                st.warning("⚠️ Dados insuficientes para análise por região")
        
        with tab_dash3:
            st.header("⏱️ Timeline de Entregas")
            df_timeline = timeline_entregas(df_prospeccao)
            if not df_timeline.empty and "PREVISAO_ENTREGA" in df_timeline.columns:
                anos_disp = sorted(df_timeline["ANO_ENTREGA"].dropna().unique().astype(int))
                if anos_disp:
                    ano_sel = st.selectbox("Filtrar por Ano de Entrega", options=anos_disp, index=len(anos_disp)-1)
                    df_timeline_filt = df_timeline[df_timeline["ANO_ENTREGA"] == ano_sel]
                    
                    st.markdown(f"### 📅 Entregas Previstas para {int(ano_sel)}")
                    if not df_timeline_filt.empty:
                        entregas_por_mes = df_timeline_filt.groupby("MES_ENTREGA").agg(
                            total_projetos=("NOME", "count"), 
                            total_apartamentos=("APTO", lambda x: pd.to_numeric(x, errors='coerce').sum())
                        ).reset_index()
                        entregas_por_mes["MES_ENTREGA"] = entregas_por_mes["MES_ENTREGA"].astype(str)
                        
                        fig_timeline = px.bar(entregas_por_mes, x="MES_ENTREGA", y="total_projetos", color="total_apartamentos", title=f"Distribuição Mensal ({int(ano_sel)})")
                        st.plotly_chart(fig_timeline, use_container_width=True)
                        
                        st.markdown("### 🚨 Próximos 90 dias")
                        entregas_proximas = df_timeline[df_timeline["DIAS_RESTANTES"] <= 90].sort_values("DIAS_RESTANTES")
                        if not entregas_proximas.empty:
                            for _, row in entregas_proximas.head(10).iterrows():
                                dias = int(row["DIAS_RESTANTES"]) if pd.notna(row["DIAS_RESTANTES"]) else 0
                                cor = "" if dias <= 30 else "🟠" if dias <= 60 else "🟡"
                                st.markdown(f"{cor} **{row['NOME']}** ({row.get('CONSTRUTORA', 'N/A')}) - {row.get('BAIRRO', '')} - {dias} dias")
                        else:
                            st.info("ℹ️ Nenhuma entrega nos próximos 90 dias")
                        
                        with st.expander("Ver Todas as Entregas de " + str(int(ano_sel))):
                            cols_disp = ["NOME", "CONSTRUTORA", "BAIRRO", "APTO", "PREVISAO_ENTREGA", "DIAS_RESTANTES"]
                            cols_existentes = [c for c in cols_disp if c in df_timeline_filt.columns]
                            df_show = df_timeline_filt[cols_existentes].copy()
                            if "PREVISAO_ENTREGA" in df_show.columns:
                                mask_notna = df_show['PREVISAO_ENTREGA'].notna()
                                df_show.loc[mask_notna, 'PREVISAO_ENTREGA'] = pd.to_datetime(df_show.loc[mask_notna, 'PREVISAO_ENTREGA']).dt.strftime('%d/%m/%Y')
                                df_show.loc[~mask_notna, 'PREVISAO_ENTREGA'] = ''
                            st.dataframe(df_show, use_container_width=True)
            else:
                st.warning("⚠️ Sem dados de previsão de entrega.")
        
        with tab_dash4:
            st.header(" Priorização de Ações")
            if "PRIORIDADE" in df_prospeccao.columns:
                col_pri1, col_pri2 = st.columns(2)
                
                with col_pri1:
                    fig_pri = px.pie(values=df_prospeccao["PRIORIDADE"].value_counts().values, 
                                    names=df_prospeccao["PRIORIDADE"].value_counts().index, 
                                    title="Distribuição de Prioridades", 
                                    color_discrete_map={
                                        " Ação Imediata": "#2ecc71",
                                        " Alta Prioridade": "#d35400",
                                        " Urgente": "#e74c3c",
                                        "🟠 Alta": "#e67e22",
                                        "🟡 Média": "#f1c40f",
                                        "🟡 Acompanhamento": "#9b59b6",
                                        "🔵 Planejamento": "#3498db",
                                        " Arquivado": "#95a5a6",
                                        "⚪ Baixa": "#bdc3c7"
                                    })
                    st.plotly_chart(fig_pri, use_container_width=True)
                
                with col_pri2:
                    prioridades_disp = df_prospeccao["PRIORIDADE"].unique().tolist()
                    valid_defaults = [p for p in [" Ação Imediata", "🟠 Alta Prioridade", "🔴 Urgente"] if p in prioridades_disp]
                    if not valid_defaults and prioridades_disp:
                        valid_defaults = [prioridades_disp[0]]
                    
                    prioridade_sel = st.multiselect("Filtrar por Prioridade", options=prioridades_disp, default=valid_defaults, key="prioridade_filter")
                    
                    if prioridade_sel:
                        df_prioridade = df_prospeccao[df_prospeccao["PRIORIDADE"].isin(prioridade_sel)]
                        st.metric("Projetos Prioritários", f"{len(df_prioridade):,}".replace(",", "."))
                        
                        st.markdown("###  Lista de Ação")
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
                        st.download_button("📥 Exportar Lista Prioritária", excel_buffer, f"prioritarios_{datetime.now().strftime('%Y%m%d')}.xlsx", 
                                         mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
            else:
                st.warning("⚠️ Dados de prioridade indisponíveis")
        
        # ==================== ABA LISTA COMPLETA ====================
        with tab_dash5:
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
            if zona_sel and col_regiao:
                df_filt = df_filt[df_filt[col_regiao].isin(zona_sel)]
            if construtora_sel:   
                df_filt = df_filt[df_filt["CONSTRUTORA"].isin(construtora_sel)]
            if fase_sel:
                df_filt = df_filt[df_filt["FASE_CLASSIFICADA"].isin(fase_sel)]
            
            st.markdown(f"### 📊 {len(df_filt)} projetos encontrados")
            
            colunas_display = ["NOME", "CONSTRUTORA", "BAIRRO", "Região", "FASE_CLASSIFICADA", "APTO", "PRIORIDADE"]
            colunas_existentes = [c for c in colunas_display if c in df_filt.columns]
            df_lista = df_filt[colunas_existentes].copy()
            
            if "APTO" in df_lista.columns:
                df_lista["APTO"] = df_lista["APTO"].apply(lambda x: f"{int(x):,}".replace(",", ".") if pd.notna(x) else "N/A")
            
            col_names = {"NOME": "Condomínio", "CONSTRUTORA": "Construtora", "BAIRRO": "Bairro", "Região": "Região", "FASE_CLASSIFICADA": "Fase", "APTO": "APTs", "PRIORIDADE": "Prioridade"}
            df_lista = df_lista.rename(columns={k: v for k, v in col_names.items() if k in df_lista.columns})
            
            st.dataframe(df_lista, use_container_width=True)
               
            # === BOTÃO DE EXPORTAÇÃO ===
            st.markdown("---")
            st.subheader("📎 Exportar Dados")
            
            df_construtoras_resumo = analisar_por_construtora(df_filt)
            df_zonas_resumo = analisar_por_zona(df_filt)
            excel_buffer = exportar_prospeccao_excel(df_filt, df_construtoras_resumo, df_zonas_resumo)
            
            col_exp1, col_exp2 = st.columns([3, 1])
            with col_exp1:
                st.download_button(
                    label="📥 Exportar Lista Completa (Excel com Abas por Fase)",
                    data=excel_buffer,
                    file_name=f"prospeccao_completa_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx",
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    use_container_width=True
                )
            with col_exp2:
                st.info("""
                **Estrutura do Excel:**
                - 📊 Resumo Executivo
                - 📋 Completo
                - 00: ✅ Entramos
                - 01: 💼 Em Negociação
                - 02-09: Outras Fases
                - 10: Por Construtora
                - 11: Por Região
                """)
        
        st.markdown("---")
        st.markdown("""
        ### 💡 Dicas Rápidas:
        - Use a aba **✏️ Atualizar Empreendimentos** para corrigir fases ou adicionar observações rapidamente.
        - A fase **✅ Entramos** destaca projetos confirmados com alta prioridade ( Ação Imediata).
        - A fase ** Entregue** identifica projetos já concluídos.
        - A exportação gera um Excel com **abas separadas por fase** para facilitar o trabalho de campo.
        """)
    else:
        st.info("👆 Faça upload da planilha para visualizar os dados")

if __name__ == "__main__":
    render_prospeccao_condominios()
