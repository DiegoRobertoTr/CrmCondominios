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
import re
import time
from bson import ObjectId

# ==================== FUNÇÕES UTILITÁRIAS OTIMIZADAS ====================

def limpar_valor_data_vetorizado(series):
    """Versão vetorizada e otimizada para limpar datas"""
    if series.empty:
        return series
    
    # Converter para string e limpar valores inválidos
    invalidos = ["00/00/0000", "0", "", "nan", "NaT", "null", "NULL", "-"]
    series = series.astype(str).str.strip()
    series = series.replace(invalidos, pd.NaT)
    
    # Tentar extrair datas com regex vetorizado
    def extrair_data(texto):
        if pd.isna(texto) or texto in invalidos:
            return pd.NaT
        match = re.search(r'\d{2}/\d{2}/\d{2,4}', str(texto))
        if match:
            try:
                return pd.to_datetime(match.group(), errors='coerce', dayfirst=True)
            except:
                return pd.NaT
        return pd.NaT
    
    return series.apply(extrair_data)

def converter_dataframe_dates_otimizado(df):
    """Conversão vetorizada de datas - MUITO mais rápida"""
    df = df.copy()
    colunas_data = []
    
    for col in df.columns:
        col_lower = col.lower()
        if any(palavra in col_lower for palavra in ['data', 'date', 'cadastro', 'entrega', 'previsao', 'atualizacao', 'viabilidade']):
            colunas_data.append(col)
    
    for col in colunas_data:
        if df[col].dtype == object:
            df[col] = limpar_valor_data_vetorizado(df[col])
        else:
            df[col] = pd.to_datetime(df[col], errors='coerce')
    
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

# ==================== FUNÇÕES DE CLASSIFICAÇÃO (Pré-calculadas) ====================

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
    """Extrai data de previsão de entrega"""
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
    elif isinstance(previsao_entrega, datetime) and previsao_entrega.tzinfo:
        previsao_entrega = previsao_entrega.replace(tzinfo=None)
    delta = previsao_entrega - hoje
    return delta.days

def calcular_prioridade(row):
    """Calcula prioridade de ação baseado em fase e tempo"""
    fase = row.get("FASE_CLASSIFICADA", "")
    dias = row.get("DIAS_RESTANTES", None)

    if fase in ["✅ Pronto", "🏁 Final de Obra"]:
        if dias is not None and dias <= 90:
            return "🔴 Urgente"
        elif dias is not None and dias <= 180:
            return "🟠 Alta"
        else:
            return "🟡 Média"
    elif fase in ["🔨 Intermediário", "🚧 Início de Obra"]:
        if dias is not None and dias <= 365:
            return "🟠 Alta"
        else:
            return "🟡 Média"
    elif fase in ["📢 Lançamento", "📅 Futuro Lançamento"]:
        return "🟢 Planejamento"
    else:
        return "⚪ Baixa"

def processar_dados_completos(df):
    """Processa todos os campos derivados de uma vez - OTIMIZADO"""
    df = df.copy()
    
    # Garantir coluna ESTÁGIO existe
    if "ESTÁGIO" not in df.columns and "FASE" in df.columns:
        df["ESTÁGIO"] = df["FASE"]
    
    # Pré-calcular todas as colunas derivadas
    if "ESTÁGIO" in df.columns:
        df["FASE_CLASSIFICADA"] = df["ESTÁGIO"].apply(classificar_fase)
        df["FASE_ORIGINAL"] = df["ESTÁGIO"]
    
    # Previsão de entrega
    if "VIABILIDADE" in df.columns:
        df["PREVISAO_ENTREGA"] = df["VIABILIDADE"].apply(extrair_previsao_entrega)
    
    if "Previsão de Entrega" in df.columns:
        prev2 = df["Previsão de Entrega"].apply(extrair_previsao_entrega)
        if "PREVISAO_ENTREGA" in df.columns:
            df["PREVISAO_ENTREGA"] = df["PREVISAO_ENTREGA"].fillna(prev2)
        else:
            df["PREVISAO_ENTREGA"] = prev2
    
    # Dias restantes e prioridade
    if "PREVISAO_ENTREGA" in df.columns:
        df["DIAS_RESTANTES"] = df["PREVISAO_ENTREGA"].apply(calcular_dias_para_entrega)
    
    if "FASE_CLASSIFICADA" in df.columns:
        df["PRIORIDADE"] = df.apply(calcular_prioridade, axis=1)
    
    # Converter datas
    df = converter_dataframe_dates_otimizado(df)
    
    return df

# ==================== CONFIGURAÇÃO INICIAL ====================

st.set_page_config(page_title="🏗️ Prospecção de Condomínios", layout="wide")

# ==================== CONFIGURAÇÃO MONGODB OTIMIZADA ====================

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
        db = client[database_name]
        
        # Criar índices para performance
        db["prospeccao_condominios"].create_index([("_import_batch", ASCENDING)])
        db["prospeccao_condominios"].create_index([("CONSTRUTORA", ASCENDING)])
        db["prospeccao_condominios"].create_index([("FASE_CLASSIFICADA", ASCENDING)])
        db["prospeccao_condominios"].create_index([("Região", ASCENDING)])
        db["prospeccao_condominios"].create_index([("NOME", ASCENDING)])
        
        return db
    except (ServerSelectionTimeoutError, ConnectionFailure) as e:
        st.error(f"❌ Falha ao conectar ao MongoDB:\n`{type(e).__name__}: {e}`")
        st.stop()
    except Exception as e:
        st.error(f"❌ Erro inesperado ao conectar: {type(e).__name__}: {e}")
        st.stop()

def save_prospeccao_data(db, df_prospeccao, metadata):
    """Salva dados de prospecção no MongoDB com todos os campos pré-calculados"""
    collection = db["prospeccao_condominios"]
    
    # Processar todos os campos derivados antes de salvar
    df_processado = processar_dados_completos(df_prospeccao)

    docs = []
    for _, row in df_processado.iterrows():
        doc = row.to_dict()
        # Limpar valores para MongoDB
        for key, value in doc.items():
            if isinstance(value, (pd.Timestamp, datetime)):
                doc[key] = value.to_pydatetime().replace(tzinfo=None) if value.tzinfo else value
            elif pd.isna(value):
                doc[key] = None
            elif isinstance(value, (pd.Series, pd.DataFrame)):
                doc[key] = str(value)
        doc["_import_timestamp"] = datetime.now().replace(tzinfo=None)
        doc["_import_batch"] = metadata["batch_id"]
        doc["_last_updated"] = datetime.now().replace(tzinfo=None)
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

def load_latest_prospeccao(db, limit=None):
    """Carrega últimos dados de prospecção - já processados"""
    meta = db["prospeccao_meta"].find_one(sort=[("timestamp", -1)])
    if not meta:
        return None, None
    
    collection = db["prospeccao_condominios"]
    query = {"_import_batch": meta["batch_id"]}
    
    if limit:
        cursor = collection.find(query).limit(limit)
    else:
        cursor = collection.find(query)
    
    df_prospeccao = pd.DataFrame(list(cursor))
    
    if "_id" in df_prospeccao.columns:
        df_prospeccao = df_prospeccao.drop(columns=["_id"])
    
    # NÃO precisa recalcular - dados já vêm processados!
    # Apenas garantir tipos de data estão corretos
    df_prospeccao = converter_dataframe_dates_otimizado(df_prospeccao)
    
    return df_prospeccao, meta

# ==================== FUNÇÕES PARA ATUALIZAÇÃO DE EMPREENDIMENTOS ====================

def get_distinct_values(db, campo):
    """Obtém valores distintos de um campo para filtros"""
    collection = db["prospeccao_condominios"]
    valores = collection.distinct(campo)
    return sorted([v for v in valores if v is not None])

def buscar_empreendimentos_paginado(db, filtros=None, pagina=1, itens_por_pagina=50):
    """Busca empreendimentos com filtros e paginação server-side"""
    collection = db["prospeccao_condominios"]
    
    query = {}
    if filtros:
        if filtros.get("construtora"):
            query["CONSTRUTORA"] = filtros["construtora"]
        if filtros.get("fase"):
            query["FASE_CLASSIFICADA"] = filtros["fase"]
        if filtros.get("regiao"):
            campo_regiao = "Região" if "Região" in get_distinct_values(db, "Região")[:1] or [] else "ZONA"
            query[campo_regiao] = filtros["regiao"]
        if filtros.get("busca_nome"):
            query["NOME"] = {"$regex": filtros["busca_nome"], "$options": "i"}
        if filtros.get("viabilidade"):
            # Busca na coluna VIABILIDADE
            query["VIABILIDADE"] = {"$regex": filtros["viabilidade"], "$options": "i"}
    
    # Contar total
    total = collection.count_documents(query)
    
    # Paginação
    skip = (pagina - 1) * itens_por_pagina
    cursor = collection.find(query).skip(skip).limit(itens_por_pagina).sort("NOME", ASCENDING)
    
    df = pd.DataFrame(list(cursor))
    if "_id" in df.columns:
        df = df.drop(columns=["_id"])
    
    return df, total

def atualizar_empreendimento(db, empreendimento_id, dados_atualizados):
    """Atualiza um empreendimento no MongoDB"""
    collection = db["prospeccao_condominios"]
    
    # Recalcular campos derivados se necessário
    if "ESTÁGIO" in dados_atualizados:
        dados_atualizados["FASE_CLASSIFICADA"] = classificar_fase(dados_atualizados["ESTÁGIO"])
        dados_atualizados["FASE_ORIGINAL"] = dados_atualizados["ESTÁGIO"]
    
    if "VIABILIDADE" in dados_atualizados:
        dados_atualizados["PREVISAO_ENTREGA"] = extrair_previsao_entrega(dados_atualizados["VIABILIDADE"])
        if dados_atualizados.get("PREVISAO_ENTREGA"):
            dados_atualizados["DIAS_RESTANTES"] = calcular_dias_para_entrega(dados_atualizados["PREVISAO_ENTREGA"])
    
    # Recalcular prioridade
    if "FASE_CLASSIFICADA" in dados_atualizados or "DIAS_RESTANTES" in dados_atualizados:
        row_temp = {
            "FASE_CLASSIFICADA": dados_atualizados.get("FASE_CLASSIFICADA", ""),
            "DIAS_RESTANTES": dados_atualizados.get("DIAS_RESTANTES")
        }
        dados_atualizados["PRIORIDADE"] = calcular_prioridade(row_temp)
    
    dados_atualizados["_last_updated"] = datetime.now().replace(tzinfo=None)
    
    result = collection.update_one(
        {"_id": ObjectId(empreendimento_id)},
        {"$set": dados_atualizados}
    )
    return result.modified_count > 0

def cadastrar_novo_empreendimento(db, dados):
    """Cadastra novo empreendimento no MongoDB"""
    collection = db["prospeccao_condominios"]
    
    # Processar dados
    df_temp = pd.DataFrame([dados])
    df_processado = processar_dados_completos(df_temp)
    
    doc = df_processado.iloc[0].to_dict()
    for key, value in doc.items():
        if isinstance(value, (pd.Timestamp, datetime)):
            doc[key] = value.to_pydatetime().replace(tzinfo=None) if value.tzinfo else value
        elif pd.isna(value):
            doc[key] = None
    
    doc["_import_timestamp"] = datetime.now().replace(tzinfo=None)
    doc["_import_batch"] = f"manual_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    doc["_last_updated"] = datetime.now().replace(tzinfo=None)
    doc["_is_manual"] = True
    
    result = collection.insert_one(doc)
    return result.inserted_id

# ==================== FUNÇÕES DE ANÁLISE ====================

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
    
    if "PREVISAO_ENTREGA" not in df_timeline.columns:
        return pd.DataFrame()
    
    df_timeline = df_timeline[df_timeline["PREVISAO_ENTREGA"].notna()]
    
    if df_timeline.empty:
        return df_timeline

    df_timeline["DIAS_RESTANTES"] = df_timeline["PREVISAO_ENTREGA"].apply(calcular_dias_para_entrega)
    df_timeline["ANO_ENTREGA"] = df_timeline["PREVISAO_ENTREGA"].dt.year
    df_timeline["MES_ENTREGA"] = df_timeline["PREVISAO_ENTREGA"].dt.to_period('M')
    return df_timeline.sort_values("PREVISAO_ENTREGA")

def exportar_prospeccao_excel(df_prospeccao, df_construtoras, df_zonas):
    """Exporta dados de prospecção para Excel com abas por fase"""
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        df_prospeccao.to_excel(writer, sheet_name='Completo', index=False)

        fases_map = {
            '✅ Pronto': 'Pronto',
            '🏁 Final de Obra': 'Final de Obra',
            '🔨 Intermediário': 'Intermediario',
            '🚧 Início de Obra': 'Inicio de Obra',
            '📢 Lançamento': 'Lancamento',
            '📅 Futuro Lançamento': 'Futuro Lançamento',
            '❌ Não Entramos': 'Não Entramos',
            '📋 Em Tratativa': 'Em Tratativa'
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

# ==================== INTERFACE STREAMLIT - NOVAS ABAS ====================

def render_atualizar_empreendimentos(db):
    """Renderiza a aba de atualização de empreendimentos"""
    st.header("🔄 Atualizar Empreendimentos")
    st.markdown("Busque, filtre e edite empreendimentos cadastrados")
    
    # Sidebar com filtros
    with st.sidebar:
        st.subheader("🔍 Filtros de Busca")
        
        # Busca por nome
        busca_nome = st.text_input("Buscar por nome", placeholder="Digite o nome do empreendimento...")
        
        # Filtro por construtora
        construtoras = get_distinct_values(db, "CONSTRUTORA")
        construtora_sel = st.selectbox("Construtora", ["Todas"] + construtoras)
        
        # Filtro por fase
        fases = get_distinct_values(db, "FASE_CLASSIFICADA")
        fase_sel = st.selectbox("Fase/Estágio", ["Todas"] + fases)
        
        # Filtro por região
        regioes = get_distinct_values(db, "Região") or get_distinct_values(db, "ZONA")
        regiao_sel = st.selectbox("Região", ["Todas"] + regioes)
        
        # Filtro por viabilidade
        viabilidade_filtro = st.text_input("Viabilidade contém", placeholder="Ex: sim, comercial...")
        
        st.markdown("---")
        
        # Configurações de paginação
        itens_por_pagina = st.selectbox("Itens por página", [25, 50, 100], index=1)
    
    # Montar filtros
    filtros = {}
    if construtora_sel != "Todas":
        filtros["construtora"] = construtora_sel
    if fase_sel != "Todas":
        filtros["fase"] = fase_sel
    if regiao_sel != "Todas":
        filtros["regiao"] = regiao_sel
    if busca_nome:
        filtros["busca_nome"] = busca_nome
    if viabilidade_filtro:
        filtros["viabilidade"] = viabilidade_filtro
    
    # Estado da paginação
    if "pagina_atual" not in st.session_state:
        st.session_state.pagina_atual = 1
    
    # Botões de navegação
    col_nav1, col_nav2, col_nav3 = st.columns([1, 2, 1])
    
    with col_nav1:
        if st.button("⬅️ Anterior", disabled=st.session_state.pagina_atual <= 1):
            st.session_state.pagina_atual -= 1
            st.rerun()
    
    with col_nav3:
        if st.button("Próxima ➡️"):
            st.session_state.pagina_atual += 1
            st.rerun()
    
    # Buscar dados
    with st.spinner("Carregando empreendimentos..."):
        df_resultado, total_registros = buscar_empreendimentos_paginado(
            db, filtros, st.session_state.pagina_atual, itens_por_pagina
        )
    
    # Verificar se há próxima página
    total_paginas = (total_registros // itens_por_pagina) + (1 if total_registros % itens_por_pagina > 0 else 0)
    
    with col_nav2:
        st.markdown(f"<center>Página {st.session_state.pagina_atual} de {total_paginas} | Total: {total_registros} registros</center>", unsafe_allow_html=True)
    
    # Resetar página se ultrapassar o total
    if st.session_state.pagina_atual > total_paginas and total_paginas > 0:
        st.session_state.pagina_atual = 1
        st.rerun()
    
    if df_resultado.empty:
        st.info("ℹ️ Nenhum empreendimento encontrado com os filtros selecionados.")
        return
    
    # Selecionar colunas para exibição
    colunas_display = ["NOME", "CONSTRUTORA", "BAIRRO", "Região", "FASE_CLASSIFICADA", "APTO", "PRIORIDADE", "VIABILIDADE"]
    colunas_existentes = [c for c in colunas_display if c in df_resultado.columns]
    
    df_display = df_resultado[colunas_existentes].copy()
    
    # Formatar dados
    if "APTO" in df_display.columns:
        df_display["APTO"] = df_display["APTO"].apply(lambda x: formatar_numero_br(int(x)) if pd.notna(x) else "N/A")
    
    # Renomear colunas
    col_names = {
        "NOME": "Condomínio",
        "CONSTRUTORA": "Construtora",
        "BAIRRO": "Bairro",
        "Região": "Região",
        "FASE_CLASSIFICADA": "Fase",
        "APTO": "APTs",
        "PRIORIDADE": "Prioridade",
        "VIABILIDADE": "Viabilidade"
    }
    df_display = df_display.rename(columns={k: v for k, v in col_names.items() if k in df_display.columns})
    
    # Tabela interativa com seleção
    st.markdown("### 📋 Resultados da Busca")
    
    # Usar data_editor para edição inline (mais performático que cards)
    edited_df = st.data_editor(
        df_display,
        use_container_width=True,
        num_rows="fixed",
        disabled=["Condomínio", "Construtora", "Bairro", "Região", "APTs", "Prioridade"],
        hide_index=True
    )
    
    # Seleção para edição detalhada
    st.markdown("---")
    st.markdown("### ✏️ Edição Detalhada")
    
    # Dropdown para selecionar qual empreendimento editar
    opcoes_edicao = df_resultado.apply(lambda row: f"{row.get('NOME', 'N/A')} - {row.get('CONSTRUTORA', 'N/A')}", axis=1).tolist()
    empreendimento_selecionado = st.selectbox("Selecione o empreendimento para editar:", [""] + opcoes_edicao)
    
    if empreendimento_selecionado:
        idx = opcoes_edicao.index(empreendimento_selecionado)
        row_selecionada = df_resultado.iloc[idx]
        empreendimento_id = row_selecionada.get('_id', None)
        
        if empreendimento_id is None:
            # Tentar buscar pelo nome
            collection = db["prospeccao_condominios"]
            doc = collection.find_one({"NOME": row_selecionada["NOME"], "CONSTRUTORA": row_selecionada["CONSTRUTORA"]})
            if doc:
                empreendimento_id = doc["_id"]
        
        if empreendimento_id:
            with st.form("form_edicao_empreendimento"):
                st.subheader(f"Editando: {row_selecionada.get('NOME', '')}")
                
                col1, col2 = st.columns(2)
                
                with col1:
                    nome = st.text_input("Nome do Condomínio", value=row_selecionada.get('NOME', ''))
                    construtora = st.text_input("Construtora", value=row_selecionada.get('CONSTRUTORA', ''))
                    bairro = st.text_input("Bairro", value=row_selecionada.get('BAIRRO', ''))
                    endereco = st.text_input("Endereço", value=row_selecionada.get('ENDEREÇO', ''))
                    regiao = st.text_input("Região/Zona", value=row_selecionada.get('Região', row_selecionada.get('ZONA', '')))
                
                with col2:
                    estagio = st.selectbox(
                        "Estágio/Fase",
                        options=["Pronto", "Final de Obra", "Intermediário", "Início de Obra", 
                                "Lançamento", "Futuro Lançamento", "Não Entramos", "Em Tratativa"],
                        index=0 if pd.isna(row_selecionada.get('ESTÁGIO')) else 
                              ["Pronto", "Final de Obra", "Intermediário", "Início de Obra", 
                               "Lançamento", "Futuro Lançamento", "Não Entramos", "Em Tratativa"].index(
                                   str(row_selecionada.get('ESTÁGIO', 'Pronto')).replace("✅ ", "").replace("🏁 ", "").replace("🔨 ", "")
                                   .replace("🚧 ", "").replace("📢 ", "").replace("📅 ", "").replace("❌ ", "").replace("📋 ", "")
                               ) if str(row_selecionada.get('ESTÁGIO', '')).replace("✅ ", "").replace("🏁 ", "").replace("🔨 ", "")
                                   .replace("🚧 ", "").replace("📢 ", "").replace("📅 ", "").replace("❌ ", "").replace("📋 ", "") 
                               in ["Pronto", "Final de Obra", "Intermediário", "Início de Obra", 
                                   "Lançamento", "Futuro Lançamento", "Não Entramos", "Em Tratativa"] else 0
                    )
                    apto = st.number_input("Nº de Apartamentos", value=int(row_selecionada.get('APTO', 0)) if pd.notna(row_selecionada.get('APTO')) else 0, min_value=0)
                    bloco = st.text_input("Bloco/Torre", value=str(row_selecionada.get('BLOCO', '')))
                    viabilidade = st.text_area("Viabilidade/Observações", value=str(row_selecionada.get('VIABILIDADE', '')), height=100)
                
                col_btn1, col_btn2 = st.columns(2)
                
                with col_btn1:
                    submitted = st.form_submit_button("💾 Salvar Alterações", use_container_width=True, type="primary")
                
                with col_btn2:
                    deletar = st.form_submit_button("🗑️ Excluir Empreendimento", use_container_width=True, type="secondary")
                
                if submitted:
                    dados_atualizados = {
                        "NOME": nome,
                        "CONSTRUTORA": construtora,
                        "BAIRRO": bairro,
                        "ENDEREÇO": endereco,
                        "Região": regiao,
                        "ESTÁGIO": estagio,
                        "APTO": apto,
                        "BLOCO": bloco,
                        "VIABILIDADE": viabilidade
                    }
                    
                    if atualizar_empreendimento(db, str(empreendimento_id), dados_atualizados):
                        st.success("✅ Empreendimento atualizado com sucesso!")
                        time.sleep(1)
                        st.rerun()
                    else:
                        st.error("❌ Erro ao atualizar empreendimento.")
                
                if deletar:
                    confirmacao = st.checkbox("Confirmar exclusão?")
                    if confirmacao:
                        collection = db["prospeccao_condominios"]
                        collection.delete_one({"_id": ObjectId(empreendimento_id)})
                        st.success("🗑️ Empreendimento excluído!")
                        time.sleep(1)
                        st.rerun()

def render_cadastrar_empreendimento(db):
    """Renderiza a aba de cadastro de novo empreendimento"""
    st.header("➕ Cadastrar Novo Empreendimento")
    st.markdown("Preencha os dados do novo empreendimento")
    
    with st.form("form_cadastro_empreendimento"):
        st.subheader("📋 Dados do Empreendimento")
        
        col1, col2 = st.columns(2)
        
        with col1:
            nome = st.text_input("Nome do Condomínio *", placeholder="Ex: Residencial Parque das Flores")
            construtora = st.text_input("Construtora *", placeholder="Ex: MRV, Tenda, Direcional...")
            bairro = st.text_input("Bairro *", placeholder="Ex: Vila Maria")
            endereco = st.text_input("Endereço Completo", placeholder="Rua, número, complemento")
        
        with col2:
            regiao = st.text_input("Região/Zona *", placeholder="Ex: Zona Norte, Centro...")
            estagio = st.selectbox(
                "Estágio/Fase *",
                options=["Pronto", "Final de Obra", "Intermediário", "Início de Obra", 
                        "Lançamento", "Futuro Lançamento", "Não Entramos", "Em Tratativa"]
            )
            apto = st.number_input("Nº de Apartamentos", min_value=0, value=0)
            bloco = st.text_input("Bloco/Torre", placeholder="Ex: Torre A, Bloco 1")
        
        st.markdown("---")
        st.subheader("📊 Dados Comerciais")
        
        col3, col4 = st.columns(2)
        
        with col3:
            viabilidade = st.text_area(
                "Viabilidade/Observações",
                placeholder="Descreva a viabilidade comercial, data prevista de entrega, etc...",
                height=150
            )
        
        with col4:
            previsao_entrega = st.date_input("Previsão de Entrega (se houver)", value=None)
            obs = st.text_area("Observações Adicionais", placeholder="Outras informações relevantes", height=100)
        
        st.markdown("---")
        
        submitted = st.form_submit_button("💾 Cadastrar Empreendimento", use_container_width=True, type="primary")
        
        if submitted:
            # Validação
            if not nome or not construtora or not bairro or not regiao:
                st.error("❌ Preencha todos os campos obrigatórios (*)")
                return
            
            dados = {
                "NOME": nome,
                "CONSTRUTORA": construtora,
                "BAIRRO": bairro,
                "ENDEREÇO": endereco,
                "Região": regiao,
                "ESTÁGIO": estagio,
                "APTO": apto,
                "BLOCO": bloco,
                "VIABILIDADE": viabilidade,
                "OBS": obs
            }
            
            if previsao_entrega:
                dados["Previsão de Entrega"] = previsao_entrega.strftime("%d/%m/%Y")
            
            try:
                novo_id = cadastrar_novo_empreendimento(db, dados)
                st.success(f"✅ Empreendimento cadastrado com sucesso! ID: {novo_id}")
                st.balloons()
            except Exception as e:
                st.error(f"❌ Erro ao cadastrar: {str(e)}")

# ==================== INTERFACE PRINCIPAL ====================

def render_prospeccao_condominios():
    st.title("🏗️ Prospecção de Condomínios")
    st.markdown("Acompanhamento de fases de construção por construtora e oportunidades de mercado")

    db = init_mongo()
    
    # Tabs principais
    tab_dashboard, tab_atualizar, tab_cadastrar, tab_importar = st.tabs([
        "📊 Dashboard",
        "🔄 Atualizar Empreendimentos", 
        "➕ Cadastrar Novo",
        "📤 Importar Planilha"
    ])
    
    with tab_dashboard:
        render_dashboard(db)
    
    with tab_atualizar:
        render_atualizar_empreendimentos(db)
    
    with tab_cadastrar:
        render_cadastrar_empreendimento(db)
    
    with tab_importar:
        render_importar_planilha(db)

def render_dashboard(db):
    """Renderiza o dashboard original"""
    st.markdown("---")

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
    
    # Carregar dados
    if "df_prospeccao_cached" not in st.session_state or st.button("🔄 Recarregar Dados"):
        with st.spinner("Carregando dados..."):
            result = load_latest_prospeccao(db)
            if result[0] is not None:
                df_prospeccao, meta = result
                st.session_state["df_prospeccao_cached"] = df_prospeccao
                st.session_state["meta_cached"] = meta
            else:
                st.info("👆 Importe dados na aba 'Importar Planilha'")
                return
    
    if "df_prospeccao_cached" in st.session_state:
        df_prospeccao = st.session_state["df_prospeccao_cached"]
        render_analises_dashboard(df_prospeccao)

def render_analises_dashboard(df_prospeccao):
    """Renderiza as análises do dashboard"""
    if df_prospeccao.empty:
        st.info("Sem dados para exibir")
        return
    
    # KPIs
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

    # Abas de análise
    tab1, tab2, tab3, tab4, tab5 = st.tabs([
        "📊 Por Construtora",
        "🗺️ Por Região",
        "⏱️ Timeline de Entregas",
        "🎯 Priorização",
        "📋 Lista Completa"
    ])

    with tab1:
        render_tab_construtora(df_prospeccao)
    with tab2:
        render_tab_regiao(df_prospeccao)
    with tab3:
        render_tab_timeline(df_prospeccao)
    with tab4:
        render_tab_priorizacao(df_prospeccao)
    with tab5:
        render_tab_lista_completa(df_prospeccao)

def render_tab_construtora(df_prospeccao):
    """Aba por construtora"""
    st.header("🏢 Análise por Construtora")
    df_construtoras = analisar_por_construtora(df_prospeccao)
    
    if not df_construtoras.empty:
        construtoras_disp = df_construtoras["CONSTRUTORA"].dropna().unique().tolist()
        default_construtoras = construtoras_disp[:5] if len(construtoras_disp) >= 5 else construtoras_disp
        
        construtoras_sel = st.multiselect("Filtrar Construtoras", options=construtoras_disp, default=default_construtoras)
        
        if construtoras_sel:
            df_construtoras_filt = df_construtoras[df_construtoras["CONSTRUTORA"].isin(construtoras_sel)]
            
            col_chart1, col_chart2 = st.columns(2)
            with col_chart1:
                fig1 = px.bar(df_construtoras_filt.head(10), x="total_projetos", y="CONSTRUTORA", 
                             orientation="h", title="Top 10 por Nº de Projetos", color="total_projetos", color_continuous_scale="Blues")
                st.plotly_chart(fig1, use_container_width=True)
            with col_chart2:
                fig2 = px.bar(df_construtoras_filt.head(10), x="total_apartamentos", y="CONSTRUTORA",
                             orientation="h", title="Top 10 por Total de APTs", color="total_apartamentos", color_continuous_scale="Greens")
                st.plotly_chart(fig2, use_container_width=True)
            
            st.dataframe(df_construtoras_filt)
    else:
        st.warning("Sem dados de construtora")

def render_tab_regiao(df_prospeccao):
    """Aba por região"""
    st.header("🗺️ Análise por Região")
    df_zonas = analisar_por_zona(df_prospeccao)
    
    if not df_zonas.empty:
        col_zona = df_zonas.columns[0]
        col1, col2 = st.columns(2)
        with col1:
            fig = px.bar(df_zonas, x=col_zona, y="total_projetos", color="total_projetos", title="Projetos por Região")
            st.plotly_chart(fig, use_container_width=True)
        with col2:
            fig2 = px.bar(df_zonas, x=col_zona, y="oportunidades", color="percentual_oportunidades", title="Oportunidades por Região")
            st.plotly_chart(fig2, use_container_width=True)
        st.dataframe(df_zonas)
    else:
        st.warning("Sem dados de região")

def render_tab_timeline(df_prospeccao):
    """Aba timeline"""
    st.header("⏱️ Timeline de Entregas")
    df_timeline = timeline_entregas(df_prospeccao)
    
    if not df_timeline.empty:
        anos_disp = sorted(df_timeline["ANO_ENTREGA"].dropna().unique())
        if len(anos_disp) > 0:
            ano_sel = st.selectbox("Ano de Entrega", options=anos_disp, index=len(anos_disp)-1)
            df_timeline_filt = df_timeline[df_timeline["ANO_ENTREGA"] == ano_sel]
            
            entregas_por_mes = df_timeline_filt.groupby("MES_ENTREGA").agg(
                total_projetos=("NOME", "count"),
                total_apartamentos=("APTO", lambda x: pd.to_numeric(x, errors='coerce').sum())
            ).reset_index()
            entregas_por_mes["MES_ENTREGA"] = entregas_por_mes["MES_ENTREGA"].astype(str)
            
            fig = px.bar(entregas_por_mes, x="MES_ENTREGA", y="total_projetos", color="total_apartamentos",
                        title=f"Entregas por Mês ({int(ano_sel)})")
            st.plotly_chart(fig, use_container_width=True)
            
            # Entregas próximas
            st.markdown("### 🚨 Entregas Próximas (90 dias)")
            entregas_proximas = df_timeline[df_timeline["DIAS_RESTANTES"] <= 90].sort_values("DIAS_RESTANTES")
            if len(entregas_proximas) > 0:
                for _, row in entregas_proximas.head(10).iterrows():
                    dias = int(row["DIAS_RESTANTES"]) if pd.notna(row["DIAS_RESTANTES"]) else 0
                    cor = "🔴" if dias <= 30 else "🟠" if dias <= 60 else "🟡"
                    st.markdown(f"{cor} **{row['NOME']}** - {dias} dias ({safe_strftime(row['PREVISAO_ENTREGA'])})")
    else:
        st.info("Sem dados de previsão de entrega")

def render_tab_priorizacao(df_prospeccao):
    """Aba priorização"""
    st.header("🎯 Priorização de Ações")
    
    if "PRIORIDADE" in df_prospeccao.columns:
        prioridade_counts = df_prospeccao["PRIORIDADE"].value_counts()
        fig = px.pie(values=prioridade_counts.values, names=prioridade_counts.index, title="Distribuição de Prioridades")
        st.plotly_chart(fig, use_container_width=True)
        
        prioridades_disp = df_prospeccao["PRIORIDADE"].unique().tolist()
        prioridade_sel = st.multiselect("Filtrar Prioridade", options=prioridades_disp, 
                                       default=["🔴 Urgente", "🟠 Alta"] if "🔴 Urgente" in prioridades_disp else [])
        
        if prioridade_sel:
            df_prioridade = df_prospeccao[df_prospeccao["PRIORIDADE"].isin(prioridade_sel)]
            st.dataframe(df_prioridade[["NOME", "CONSTRUTORA", "FASE_CLASSIFICADA", "PRIORIDADE", "DIAS_RESTANTES"]])

def render_tab_lista_completa(df_prospeccao):
    """Aba lista completa"""
    st.header("📋 Lista Completa")
    
    col_f1, col_f2, col_f3 = st.columns(3)
    col_regiao = "Região" if "Região" in df_prospeccao.columns else "ZONA" if "ZONA" in df_prospeccao.columns else None
    
    with col_f1:
        if col_regiao:
            zona_sel = st.multiselect("Região", options=df_prospeccao[col_regiao].dropna().unique().tolist())
        else:
            zona_sel = []
    with col_f2:
        construtora_sel = st.multiselect("Construtora", options=df_prospeccao["CONSTRUTORA"].dropna().unique().tolist() if "CONSTRUTORA" in df_prospeccao.columns else [])
    with col_f3:
        fase_sel = st.multiselect("Fase", options=df_prospeccao["FASE_CLASSIFICADA"].dropna().unique().tolist() if "FASE_CLASSIFICADA" in df_prospeccao.columns else [])
    
    df_filt = df_prospeccao.copy()
    if zona_sel and col_regiao:
        df_filt = df_filt[df_filt[col_regiao].isin(zona_sel)]
    if construtora_sel:
        df_filt = df_filt[df_filt["CONSTRUTORA"].isin(construtora_sel)]
    if fase_sel:
        df_filt = df_filt[df_filt["FASE_CLASSIFICADA"].isin(fase_sel)]
    
    st.dataframe(df_filt)

def render_importar_planilha(db):
    """Renderiza a aba de importação"""
    st.header("📤 Importar Planilha de Prospecção")
    
    uploaded_file = st.file_uploader("Selecione o arquivo Excel", type=["xlsx", "xls"])
    
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
                # Mapear colunas
                col_mapping = {
                    'região': 'Região', 'zona': 'Região',
                    'bairro': 'BAIRRO',
                    'endereço': 'ENDEREÇO', 'endereco': 'ENDEREÇO',
                    'nome': 'NOME', 'condomínio': 'NOME', 'condominio': 'NOME',
                    'bloco': 'BLOCO',
                    'apto': 'APTO', 'apartamentos': 'APTO',
                    'construtora': 'CONSTRUTORA',
                    'estágio': 'ESTÁGIO', 'estagio': 'ESTÁGIO',
                    'viabilidade': 'VIABILIDADE',
                    'obs': 'OBS',
                    'data da atualização': 'Data da Atualização',
                    'previsão de entrega': 'Previsão de Entrega'
                }
                
                df_prospeccao.columns = [str(col).strip() for col in df_prospeccao.columns]
                df_prospeccao = df_prospeccao.rename(columns={k: v for k, v in col_mapping.items() 
                                                              if k in [c.lower() for c in df_prospeccao.columns]})
                
                if "ESTÁGIO" not in df_prospeccao.columns:
                    st.error("❌ Coluna 'ESTÁGIO' não encontrada!")
                    return
                
                # Processar dados (agora otimizado)
                with st.spinner("Processando dados..."):
                    df_prospeccao = processar_dados_completos(df_prospeccao)
                
                fases_count = df_prospeccao["FASE_CLASSIFICADA"].value_counts().to_dict()
                
                metadata = {
                    "timestamp": datetime.now().replace(tzinfo=None),
                    "batch_id": f"prospeccao_{datetime.now().strftime('%Y%m%d_%H%M%S')}",
                    "filename": uploaded_file.name,
                    "fases": fases_count,
                    "construtoras": df_prospeccao["CONSTRUTORA"].dropna().unique().tolist() if "CONSTRUTORA" in df_prospeccao.columns else []
                }
                
                if st.button("💾 Salvar no Banco de Dados", type="primary"):
                    with st.spinner("Salvando..."):
                        if save_prospeccao_data(db, df_prospeccao, metadata):
                            st.success(f"✅ {len(df_prospeccao)} projetos importados!")
                            st.session_state["df_prospeccao_cached"] = df_prospeccao
                            st.rerun()
            else:
                st.error("❌ Nenhum dado válido encontrado")
        except Exception as e:
            st.error(f"❌ Erro: {str(e)}")

if __name__ == "__main__":
    render_prospeccao_condominios()
