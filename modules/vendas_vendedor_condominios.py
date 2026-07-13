# modules/vendas_vendedor_condominios.py
"""
Módulo de Vendas por Vendedor - CRM Condomínios RJ
VERSÃO COMPLETA E OTIMIZADA COM:
- Upload com limpeza automática do MongoDB
- Vendas por vendedor
- Evolução semanal (com semana do MÊS)
- Evolução mensal com seleção múltipla de vendedores
- Indicador de evolução/piora semana a semana
- Desempenho por condomínio (integrado com módulo condominios.py)
- Filtro de período aplicado em TODAS as análises
- Seletor de período: Personalizado primeiro, depois pré-selecionados, depois meses (do mais recente para o mais antigo)
- Exportação em Excel
- Permissões: admin e diretoria
"""
import streamlit as st
import pandas as pd
import numpy as np
import plotly.express as px
import plotly.graph_objects as go
from datetime import datetime, timedelta
from io import BytesIO
import warnings
import logging
import calendar
import urllib.parse
import time
from pymongo import MongoClient

warnings.filterwarnings('ignore')
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ==================== CONFIGURAÇÃO ====================
CONFIG = {
    'colunas_obrigatorias': [
        'RAZAO SOCIAL/NOME',
        'ID',
        'DATA ATIVAAAO',
        'STATUS CONTRATO',
        'VENDEDOR',
        'CONDOMANIO',
        'DATA DE CADASTRO NO SISTEMA'
    ],
    'colecao_mongo': 'vendas_vendedor_condominios',
    'meses_pt': {
        1: "Janeiro", 2: "Fevereiro", 3: "Março", 4: "Abril",
        5: "Maio", 6: "Junho", 7: "Julho", 8: "Agosto",
        9: "Setembro", 10: "Outubro", 11: "Novembro", 12: "Dezembro"
    },
    'cache_ttl': 300,  # 5 minutos de cache
    'limite_grafico': 50,  # Máximo de barras em gráficos
    'limite_tabela': 500  # Máximo de linhas em tabelas
}

# ==================== CONEXÃO MONGODB ====================
@st.cache_resource(ttl=CONFIG['cache_ttl'])
def init_mongo():
    """Inicializa conexão MongoDB com cache"""
    try:
        if "MONGO_URI" in st.secrets:
            uri = st.secrets["MONGO_URI"]
        else:
            mongo_cfg = st.secrets.get("mongo", {})
            username = mongo_cfg.get("MONGO_USERNAME")
            password = mongo_cfg.get("MONGO_PASSWORD")
            cluster = mongo_cfg.get("MONGO_CLUSTER_URL")
            database = mongo_cfg.get("MONGO_DATABASE", "crm_db")
            
            if not all([username, password, cluster]):
                st.error("🚨 Credenciais MongoDB incompletas nos Secrets.")
                st.stop()
            
            uri = f"mongodb+srv://{username}:{urllib.parse.quote_plus(password)}@{cluster}/{database}?retryWrites=true&w=majority"
        
        client = MongoClient(uri, serverSelectionTimeoutMS=5000, connectTimeoutMS=5000)
        client.admin.command('ping')
        
        database_name = st.secrets.get("mongo", {}).get("MONGO_DATABASE", "crm_db")
        db = client[database_name]
        
        # Índices para performance
        db[CONFIG['colecao_mongo']].create_index([("import_batch", -1)])
        db[CONFIG['colecao_mongo']].create_index([("data_ativacao", -1)])
        db[CONFIG['colecao_mongo']].create_index([("vendedor", 1)])
        db[CONFIG['colecao_mongo']].create_index([("condominio_id", 1)])
        
        return db
    except Exception as e:
        st.error(f"❌ Falha ao conectar ao MongoDB: {str(e)}")
        return None

@st.cache_data(ttl=CONFIG['cache_ttl'], show_spinner=False)
def get_condominios_crm_cached():
    """Retorna condomínios do CRM com CACHE"""
    try:
        username = st.secrets["mongo"]["MONGO_USERNAME"]
        password = st.secrets["mongo"]["MONGO_PASSWORD"]
        cluster_url = st.secrets["mongo"]["MONGO_CLUSTER_URL"]
    except KeyError:
        username = st.secrets.get("MONGO_USERNAME", "")
        password = st.secrets.get("MONGO_PASSWORD", "")
        cluster_url = st.secrets.get("MONGO_CLUSTER_URL", "")
    
    u = urllib.parse.quote_plus(username)
    p = urllib.parse.quote_plus(password)
    uri = f"mongodb+srv://{u}:{p}@{cluster_url}/?retryWrites=true&w=majority"
    
    client = MongoClient(uri, serverSelectionTimeoutMS=3000, connectTimeoutMS=3000)
    collection = client.crm_db.condominios
    
    # Buscar apenas campos necessários + limitar para performance
    condominios = list(collection.find(
        {},
        {"_id": 1, "nome": 1, "id_ixc": 1, "cidade": 1, "zona": 1, "bairro": 1}
    ).limit(5000))
    
    client.close()
    
    df_cond = pd.DataFrame(condominios)
    if not df_cond.empty:
        df_cond['id_ixc'] = pd.to_numeric(df_cond['id_ixc'], errors='coerce').fillna(0).astype(int)
        df_cond['_id'] = df_cond['_id'].astype(str)
    
    return df_cond

# ==================== FUNÇÕES DE BANCO ====================
def limpar_dados_antigos(db):
    """Remove dados antigos - OTIMIZADO com índice"""
    try:
        colecao = db[CONFIG['colecao_mongo']]
        resultado = colecao.delete_many({})
        if resultado.deleted_count > 0:
            st.info(f"🧹 {resultado.deleted_count:,} registros removidos")
        return True
    except Exception as e:
        st.error(f"❌ Erro ao limpar dados: {str(e)}")
        return False

def salvar_dados_mongo(db, df):
    """Salva dados em BATCH para performance"""
    try:
        colecao = db[CONFIG['colecao_mongo']]
        
        limpar_dados_antigos(db)
        
        df_clean = df.replace({np.nan: None})
        
        batch_id = f"import_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        records = df_clean.to_dict('records')
        for record in records:
            record['import_batch'] = batch_id
            record['imported_at'] = datetime.now()
        
        # Inserção em lotes de 5000
        batch_size = 5000
        total = len(records)
        for i in range(0, total, batch_size):
            colecao.insert_many(records[i:i+batch_size], ordered=False)
        
        st.success(f"💾 {total:,} registros salvos")
        return batch_id
    except Exception as e:
        st.error(f"❌ Erro ao salvar: {str(e)}")
        return None

def carregar_dados_mongo(db):
    """Carrega dados - OTIMIZADO com projeção"""
    try:
        colecao = db[CONFIG['colecao_mongo']]
        
        # Busca apenas o batch mais recente
        latest = colecao.find_one(sort=[("import_batch", -1)])
        if not latest:
            return None
        
        batch_id = latest.get('import_batch')
        
        # Projeção para não carregar campos desnecessários
        projection = {'_id': 0, 'import_batch': 0, 'imported_at': 0}
        cursor = colecao.find({"import_batch": batch_id}, projection)
        
        df = pd.DataFrame(list(cursor))
        
        if df.empty:
            return None
        
        return df, batch_id
    except Exception as e:
        st.error(f"❌ Erro ao carregar: {str(e)}")
        return None

# ==================== FUNÇÕES DE PROCESSAMENTO ====================
@st.cache_data(ttl=CONFIG['cache_ttl'], show_spinner=False)
def processar_planilha_cached(uploaded_file_bytes, filename):
    """Processa planilha com CACHE"""
    try:
        import io
        df = pd.read_excel(io.BytesIO(uploaded_file_bytes), engine='openpyxl')
        
        colunas_faltantes = [col for col in CONFIG['colunas_obrigatorias'] if col not in df.columns]
        if colunas_faltantes:
            return {"erro": f"Colunas faltantes: {colunas_faltantes}"}
        
        df['DATA ATIVAAAO'] = pd.to_datetime(df['DATA ATIVAAAO'], format='%d/%m/%Y', errors='coerce')
        df = df.dropna(subset=['DATA ATIVAAAO'])
        
        df = df.rename(columns={
            'RAZAO SOCIAL/NOME': 'cliente',
            'ID': 'id_cliente',
            'DATA ATIVAAAO': 'data_ativacao',
            'STATUS CONTRATO': 'status',
            'VENDEDOR': 'vendedor',
            'CONDOMANIO': 'condominio_id',
            'DATA DE CADASTRO NO SISTEMA': 'data_cadastro'
        })
        
        df['vendedor'] = df['vendedor'].astype(str).str.strip()
        df['status'] = df['status'].astype(str).str.strip()
        df['condominio_id'] = pd.to_numeric(df['condominio_id'], errors='coerce').fillna(0).astype(int)
        
        return {"df": df, "total": len(df)}
    except Exception as e:
        return {"erro": str(e)}

@st.cache_data(ttl=CONFIG['cache_ttl'], show_spinner=False)
def calcular_vendas_vendedor_cached(df_hash, data_inicio_str, data_fim_str):
    """Calcula vendas por vendedor com CACHE"""
    data_inicio = datetime.fromisoformat(data_inicio_str)
    data_fim = datetime.fromisoformat(data_fim_str)
    
    df_filtrado = df_hash[
        (df_hash['data_ativacao'] >= pd.Timestamp(data_inicio)) & 
        (df_hash['data_ativacao'] <= pd.Timestamp(data_fim))
    ]
    
    if df_filtrado.empty:
        return pd.DataFrame()
    
    return df_filtrado.groupby('vendedor').agg(
        total_vendas=('cliente', 'count')
    ).reset_index().sort_values('total_vendas', ascending=False)

@st.cache_data(ttl=CONFIG['cache_ttl'], show_spinner=False)
def calcular_vendas_semanais_cached(df_hash, data_inicio_str, data_fim_str):
    """
    Calcula vendas semanais com SEMANA DO MÊS
    Ex: Semana 1 = dias 01-07, Semana 2 = dias 08-14, etc
    """
    data_inicio = datetime.fromisoformat(data_inicio_str)
    data_fim = datetime.fromisoformat(data_fim_str)
    
    df_filtrado = df_hash[
        (df_hash['data_ativacao'] >= pd.Timestamp(data_inicio)) & 
        (df_hash['data_ativacao'] <= pd.Timestamp(data_fim))
    ].copy()
    
    if df_filtrado.empty:
        return pd.DataFrame(), pd.DataFrame()
    
    # ========== CALCULAR SEMANA DO MÊS ==========
    def get_semana_mes(data):
        """Retorna a semana do mês (1-5) baseado no dia"""
        dia = data.day
        if dia <= 7:
            return 1
        elif dia <= 14:
            return 2
        elif dia <= 21:
            return 3
        elif dia <= 28:
            return 4
        else:
            return 5
    
    df_filtrado['semana_mes'] = df_filtrado['data_ativacao'].apply(get_semana_mes)
    df_filtrado['semana_str'] = df_filtrado['semana_mes'].apply(lambda x: f'Semana {x}')
    
    # Agrupa por vendedor e semana do mês
    vendas_semanais = df_filtrado.groupby(['vendedor', 'semana_str', 'semana_mes']).agg(
        total_vendas=('cliente', 'count')
    ).reset_index().sort_values(['vendedor', 'semana_mes'])
    
    # Vendas diárias com semana do mês
    df_filtrado['dia_semana'] = df_filtrado['data_ativacao'].dt.day_name()
    df_filtrado['data_str'] = df_filtrado['data_ativacao'].dt.strftime('%d/%m')
    
    vendas_diarias = df_filtrado.groupby(['vendedor', 'semana_str', 'data_str', 'dia_semana', 'semana_mes']).agg(
        total_vendas=('cliente', 'count')
    ).reset_index().sort_values(['vendedor', 'semana_mes', 'data_str'])
    
    return vendas_semanais, vendas_diarias

def calcular_indicador_evolucao(vendas_semanais):
    """Calcula indicador de evolução/piora semana a semana"""
    if vendas_semanais.empty:
        return pd.DataFrame()
    
    # Pivot com semanas do mês
    pivot = vendas_semanais.pivot_table(
        index='vendedor',
        columns='semana_str',
        values='total_vendas',
        fill_value=0
    )
    
    # Ordenar colunas por semana (1, 2, 3, 4, 5)
    pivot = pivot.reindex(sorted(pivot.columns), axis=1)
    
    evolucao = pivot.copy()
    for i in range(1, len(pivot.columns)):
        col_anterior = pivot.columns[i-1]
        col_atual = pivot.columns[i]
        evolucao[f'{col_atual}_vs_{col_anterior}'] = (
            (pivot[col_atual] - pivot[col_anterior]) / pivot[col_anterior] * 100
        ).replace([np.inf, -np.inf], 0).fillna(0)
    
    cols_evolucao = [col for col in evolucao.columns if '_vs_' in col]
    if cols_evolucao:
        evolucao['media_evolucao'] = evolucao[cols_evolucao].mean(axis=1)
    else:
        evolucao['media_evolucao'] = 0
    
    def classificar_tendencia(valor):
        if valor > 20:
            return '🚀 Crescimento Forte'
        elif valor > 5:
            return '📈 Crescimento Moderado'
        elif valor > -5:
            return '➡️ Estável'
        elif valor > -20:
            return '📉 Declínio Moderado'
        else:
            return '🔻 Declínio Forte'
    
    evolucao['tendencia'] = evolucao['media_evolucao'].apply(classificar_tendencia)
    
    return evolucao

# ==================== NOVA FUNÇÃO: EVOLUÇÃO MENSAL ====================

@st.cache_data(ttl=CONFIG['cache_ttl'], show_spinner=False)
def calcular_vendas_mensais_cached(df_hash, data_inicio_str, data_fim_str, vendedores_selecionados):
    """
    Calcula vendas mensais para vendedores selecionados
    Retorna DataFrame com vendas por mês e vendedor
    """
    data_inicio = datetime.fromisoformat(data_inicio_str)
    data_fim = datetime.fromisoformat(data_fim_str)
    
    df_filtrado = df_hash[
        (df_hash['data_ativacao'] >= pd.Timestamp(data_inicio)) & 
        (df_hash['data_ativacao'] <= pd.Timestamp(data_fim))
    ].copy()
    
    if df_filtrado.empty:
        return pd.DataFrame()
    
    # Filtrar vendedores selecionados
    if vendedores_selecionados and "Todos" not in vendedores_selecionados:
        df_filtrado = df_filtrado[df_filtrado['vendedor'].isin(vendedores_selecionados)]
    
    if df_filtrado.empty:
        return pd.DataFrame()
    
    # Criar coluna de mês/ano
    df_filtrado['mes_ano'] = df_filtrado['data_ativacao'].dt.to_period('M')
    df_filtrado['mes_str'] = df_filtrado['data_ativacao'].dt.strftime('%b/%Y')
    df_filtrado['ano_mes_num'] = df_filtrado['data_ativacao'].dt.year * 100 + df_filtrado['data_ativacao'].dt.month
    
    # Agrupar por vendedor e mês
    vendas_mensais = df_filtrado.groupby(['vendedor', 'mes_ano', 'mes_str', 'ano_mes_num']).agg(
        total_vendas=('cliente', 'count')
    ).reset_index().sort_values(['vendedor', 'ano_mes_num'])
    
    # Calcular variação mensal (%)
    vendas_mensais['variacao_mensal'] = 0.0
    
    for vendedor in vendas_mensais['vendedor'].unique():
        mask = vendas_mensais['vendedor'] == vendedor
        vendas = vendas_mensais.loc[mask, 'total_vendas'].values
        
        for i in range(1, len(vendas)):
            if vendas[i-1] > 0:
                variacao = ((vendas[i] - vendas[i-1]) / vendas[i-1]) * 100
            else:
                variacao = 100 if vendas[i] > 0 else 0
            vendas_mensais.loc[mask & (vendas_mensais['ano_mes_num'] == vendas_mensais.loc[mask, 'ano_mes_num'].iloc[i]), 'variacao_mensal'] = variacao
    
    return vendas_mensais

def calcular_tendencia_linear(df_vendas_mensais, vendedor):
    """
    Calcula a tendência linear para um vendedor específico
    Retorna: inclinação (crescimento por mês) e R²
    """
    dados_vendedor = df_vendas_mensais[df_vendas_mensais['vendedor'] == vendedor].sort_values('ano_mes_num')
    
    if len(dados_vendedor) < 2:
        return 0, 0
    
    x = np.arange(len(dados_vendedor))
    y = dados_vendedor['total_vendas'].values
    
    if len(x) < 2 or y.sum() == 0:
        return 0, 0
    
    # Regressão linear simples
    n = len(x)
    x_mean = np.mean(x)
    y_mean = np.mean(y)
    
    # Inclinação (slope)
    slope = np.sum((x - x_mean) * (y - y_mean)) / np.sum((x - x_mean) ** 2)
    
    # R²
    y_pred = slope * (x - x_mean) + y_mean
    ss_res = np.sum((y - y_pred) ** 2)
    ss_tot = np.sum((y - y_mean) ** 2)
    r2 = 1 - (ss_res / ss_tot) if ss_tot > 0 else 0
    
    return slope, r2

def render_evolucao_mensal(df, data_inicio, data_fim):
    """Renderiza a aba de evolução mensal com seleção múltipla de vendedores"""
    st.subheader("📈 Evolução Mensal por Vendedor")
    
    st.markdown(f"""
    <div style="background-color:#e8f4f8; padding:12px; border-radius:8px; margin-bottom:15px; font-size:14px;">
    <strong>📅 Período analisado:</strong> {data_inicio.strftime('%d/%m/%Y')} a {data_fim.strftime('%d/%m/%Y')}
    </div>
    """, unsafe_allow_html=True)
    
    df_filtrado = df[
        (df['data_ativacao'] >= pd.Timestamp(data_inicio)) & 
        (df['data_ativacao'] <= pd.Timestamp(data_fim))
    ].copy()
    
    if df_filtrado.empty:
        st.warning("⚠️ Nenhum dado no período selecionado.")
        return
    
    # ========== SELETOR DE VENDEDORES ==========
    vendedores_disponiveis = sorted(df_filtrado['vendedor'].unique().tolist())
    
    st.markdown("### 👥 Selecione os Vendedores")
    
    col1, col2 = st.columns([3, 1])
    
    with col1:
        # Opção "Todos" + lista de vendedores
        opcoes_vendedores = ["👥 Todos"] + vendedores_disponiveis
        
        vendedores_selecionados = st.multiselect(
            "Selecione um ou mais vendedores:",
            options=opcoes_vendedores,
            default=["👥 Todos"],
            key="vendedores_mensais",
            help="Selecione 'Todos' ou escolha vendedores específicos"
        )
    
    with col2:
        # Botão para limpar seleção
        if st.button("🗑️ Limpar", key="limpar_vendedores"):
            st.session_state.vendedores_mensais = ["👥 Todos"]
            st.rerun()
    
    # Processar seleção
    if not vendedores_selecionados:
        st.warning("⚠️ Selecione pelo menos um vendedor.")
        return
    
    if "👥 Todos" in vendedores_selecionados:
        # Se "Todos" está selecionado, usa todos os vendedores disponíveis
        vendedores_selecionados = vendedores_disponiveis
        label_selecao = "Todos os Vendedores"
    else:
        label_selecao = f"{len(vendedores_selecionados)} vendedores selecionados"
    
    st.caption(f"📌 {label_selecao}")
    
    # ========== CALCULAR DADOS MENSAIS ==========
    data_inicio_str = datetime.combine(data_inicio, datetime.min.time()).isoformat()
    data_fim_str = datetime.combine(data_fim, datetime.min.time()).isoformat()
    
    with st.spinner("🔄 Calculando evolução mensal..."):
        # Hash para cache
        df_hash = df.copy()
        vendas_mensais = calcular_vendas_mensais_cached(df_hash, data_inicio_str, data_fim_str, vendedores_selecionados)
    
    if vendas_mensais.empty:
        st.warning("⚠️ Nenhum dado mensal disponível para os vendedores selecionados.")
        return
    
    # ========== MÉTRICAS ==========
    total_vendas_periodo = vendas_mensais['total_vendas'].sum()
    qtd_vendedores = vendas_mensais['vendedor'].nunique()
    qtd_meses = vendas_mensais['mes_ano'].nunique()
    
    col1, col2, col3, col4 = st.columns(4)
    col1.metric("📊 Total de Vendas", f"{total_vendas_periodo:,}")
    col2.metric("👤 Vendedores Analisados", qtd_vendedores)
    col3.metric("📅 Meses Analisados", qtd_meses)
    col4.metric("📈 Média por Mês", f"{total_vendas_periodo/qtd_meses:.1f}" if qtd_meses > 0 else "0")
    
    st.markdown("---")
    
    # ========== GRÁFICO DE EVOLUÇÃO MENSAL ==========
    st.markdown("### 📊 Evolução Mensal de Vendas")
    
    # Pivot para gráfico
    pivot_mensal = vendas_mensais.pivot_table(
        index='mes_str',
        columns='vendedor',
        values='total_vendas',
        fill_value=0
    )
    
    # Ordenar por data
    ordem_meses = vendas_mensais.groupby('mes_str')['ano_mes_num'].first().sort_values().index.tolist()
    pivot_mensal = pivot_mensal.reindex(ordem_meses)
    
    if not pivot_mensal.empty:
        # Gráfico de linhas
        fig_linhas = px.line(
            pivot_mensal,
            title='📈 Evolução Mensal de Vendas por Vendedor',
            labels={'value': 'Vendas', 'mes_str': 'Mês', 'variable': 'Vendedor'},
            markers=True,
            line_shape='linear'
        )
        fig_linhas.update_layout(
            height=450,
            hovermode='x unified',
            legend=dict(
                orientation='h',
                yanchor='bottom',
                y=1.02,
                xanchor='right',
                x=1
            )
        )
        st.plotly_chart(fig_linhas, use_container_width=True, config={'displayModeBar': False})
        
        # Gráfico de barras empilhadas
        fig_barras = px.bar(
            pivot_mensal,
            title='📊 Distribuição Mensal de Vendas por Vendedor',
            labels={'value': 'Vendas', 'mes_str': 'Mês', 'variable': 'Vendedor'},
            barmode='stack'
        )
        fig_barras.update_layout(
            height=400,
            legend=dict(
                orientation='h',
                yanchor='bottom',
                y=1.02,
                xanchor='right',
                x=1
            )
        )
        st.plotly_chart(fig_barras, use_container_width=True, config={'displayModeBar': False})
    
    st.markdown("---")
    
    # ========== ANÁLISE DE TENDÊNCIA ==========
    st.markdown("### 📈 Análise de Tendência por Vendedor")
    
    # Calcular tendência para cada vendedor
    tendencias = []
    for vendedor in vendas_mensais['vendedor'].unique():
        slope, r2 = calcular_tendencia_linear(vendas_mensais, vendedor)
        
        # Classificar tendência
        if slope > 2:
            tendencia = "🚀 Crescimento Forte"
            cor = "#2ecc71"
        elif slope > 0.5:
            tendencia = "📈 Crescimento Moderado"
            cor = "#27ae60"
        elif slope > -0.5:
            tendencia = "➡️ Estável"
            cor = "#f39c12"
        elif slope > -2:
            tendencia = "📉 Declínio Moderado"
            cor = "#e67e22"
        else:
            tendencia = "🔻 Declínio Forte"
            cor = "#e74c3c"
        
        # Vendas totais e média do vendedor no período
        dados_vendedor = vendas_mensais[vendas_mensais['vendedor'] == vendedor]
        total_vendas = dados_vendedor['total_vendas'].sum()
        media_mensal = dados_vendedor['total_vendas'].mean()
        meses_analisados = len(dados_vendedor)
        
        tendencias.append({
            'vendedor': vendedor,
            'total_vendas': total_vendas,
            'media_mensal': media_mensal,
            'meses_analisados': meses_analisados,
            'inclinacao': slope,
            'r2': r2,
            'tendencia': tendencia,
            'cor': cor
        })
    
    df_tendencias = pd.DataFrame(tendencias)
    df_tendencias = df_tendencias.sort_values('inclinacao', ascending=False)
    
    # Cards de tendência
    col_t1, col_t2, col_t3, col_t4 = st.columns(4)
    
    cresc_forte = len(df_tendencias[df_tendencias['tendencia'] == '🚀 Crescimento Forte'])
    cresc_mod = len(df_tendencias[df_tendencias['tendencia'] == '📈 Crescimento Moderado'])
    estavel = len(df_tendencias[df_tendencias['tendencia'] == '➡️ Estável'])
    declinio = len(df_tendencias[df_tendencias['tendencia'].str.contains('Declínio')])
    
    col_t1.metric("🚀 Crescimento Forte", cresc_forte)
    col_t2.metric("📈 Crescimento Moderado", cresc_mod)
    col_t3.metric("➡️ Estável", estavel)
    col_t4.metric("📉 Em Declínio", declinio)
    
    st.markdown("---")
    
    # Gráfico de tendência
    fig_tend = px.bar(
        df_tendencias,
        x='vendedor',
        y='inclinacao',
        color='tendencia',
        title='📊 Tendência de Crescimento por Vendedor (Inclinação Mensal)',
        text='inclinacao',
        color_discrete_map={
            '🚀 Crescimento Forte': '#2ecc71',
            '📈 Crescimento Moderado': '#27ae60',
            '➡️ Estável': '#f39c12',
            '📉 Declínio Moderado': '#e67e22',
            '🔻 Declínio Forte': '#e74c3c'
        }
    )
    fig_tend.update_traces(texttemplate='%{text:.2f}', textposition='outside')
    fig_tend.update_layout(
        height=400,
        xaxis_title="Vendedor",
        yaxis_title="Inclinação (vendas por mês)",
        legend=dict(
            orientation='h',
            yanchor='bottom',
            y=1.02,
            xanchor='right',
            x=1
        )
    )
    st.plotly_chart(fig_tend, use_container_width=True, config={'displayModeBar': False})
    
    # ========== TABELA DE DETALHES ==========
    st.markdown("### 📋 Detalhamento Mensal")
    
    # Tabela pivô
    pivot_detalhe = vendas_mensais.pivot_table(
        index='vendedor',
        columns='mes_str',
        values='total_vendas',
        fill_value=0
    )
    
    # Reordenar colunas
    ordem_colunas = vendas_mensais.groupby('mes_str')['ano_mes_num'].first().sort_values().index.tolist()
    pivot_detalhe = pivot_detalhe.reindex(ordem_colunas, axis=1)
    
    # Adicionar coluna de total
    pivot_detalhe['Total'] = pivot_detalhe.sum(axis=1)
    pivot_detalhe['Média'] = pivot_detalhe.iloc[:, :-1].mean(axis=1)
    
    st.dataframe(
        pivot_detalhe,
        use_container_width=True,
        height=300,
        column_config={
            'Total': st.column_config.NumberColumn('Total', format='%d'),
            'Média': st.column_config.NumberColumn('Média', format='%.1f')
        }
    )
    
    st.caption(f"📌 Mostrando {len(pivot_detalhe)} vendedores e {len(ordem_colunas)} meses")
    
    # ========== EXPANDER COM DADOS COMPLETOS ==========
    with st.expander("📋 Ver Dados Completos"):
        st.dataframe(
            vendas_mensais,
            use_container_width=True,
            column_config={
                'vendedor': 'Vendedor',
                'mes_str': 'Mês',
                'total_vendas': st.column_config.NumberColumn('Vendas', format='%d'),
                'variacao_mensal': st.column_config.NumberColumn('Variação %', format='%.1f%%')
            }
        )
    
    # ========== EXPORTAR ==========
    st.markdown("---")
    st.markdown("### 📤 Exportar Dados Mensais")
    
    if st.button("📥 Baixar Dados Mensais", key="exportar_mensal"):
        try:
            output = BytesIO()
            with pd.ExcelWriter(output, engine='openpyxl') as writer:
                vendas_mensais.to_excel(writer, sheet_name='Vendas Mensais', index=False)
                df_tendencias.to_excel(writer, sheet_name='Tendências', index=False)
                pivot_detalhe.to_excel(writer, sheet_name='Resumo Mensal', index=True)
            
            output.seek(0)
            st.download_button(
                label="⬇️ Baixar Excel",
                data=output,
                file_name=f"evolucao_mensal_{data_inicio.strftime('%Y%m%d')}_{data_fim.strftime('%Y%m%d')}.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                use_container_width=True
            )
            st.success("✅ Arquivo gerado!")
        except Exception as e:
            st.error(f"❌ Erro: {str(e)}")

# ==================== FUNÇÃO: DESEMPENHO POR CONDOMÍNIO ====================

def render_desempenho_por_condominio(df, data_inicio, data_fim):
    """Renderiza análise de desempenho por condomínio - COM FILTRO DE PERÍODO"""
    st.subheader("🏢 Desempenho por Condomínio")
    
    st.markdown(f"""
    <div style="background-color:#e8f4f8; padding:12px; border-radius:8px; margin-bottom:15px; font-size:14px;">
    <strong>📅 Período analisado:</strong> {data_inicio.strftime('%d/%m/%Y')} a {data_fim.strftime('%d/%m/%Y')}
    </div>
    """, unsafe_allow_html=True)
    
    # Carregar condomínios com cache
    with st.spinner("🔄 Carregando condomínios..."):
        df_cond_crm = get_condominios_crm_cached()
    
    if df_cond_crm.empty:
        st.warning("⚠️ Nenhum condomínio cadastrado. Acesse o módulo 'Condomínios'.")
        return
    
    df_vendas = df.copy()
    
    if 'condominio_id' not in df_vendas.columns:
        st.error("❌ Coluna 'condominio_id' não encontrada.")
        return
    
    df_vendas['condominio_id'] = pd.to_numeric(df_vendas['condominio_id'], errors='coerce').fillna(0).astype(int)
    
    # ========== APLICAR FILTRO DE PERÍODO ==========
    df_vendas_periodo = df_vendas[
        (df_vendas['data_ativacao'] >= pd.Timestamp(data_inicio)) & 
        (df_vendas['data_ativacao'] <= pd.Timestamp(data_fim))
    ].copy()
    
    if df_vendas_periodo.empty:
        st.warning(f"⚠️ Nenhuma venda no período {data_inicio.strftime('%d/%m/%Y')} a {data_fim.strftime('%d/%m/%Y')}.")
        return
    
    # Agrupar e merge
    df_planilha_cond = df_vendas_periodo.groupby('condominio_id', as_index=False).agg(
        total_vendas=('cliente', 'count'),
        vendedores=('vendedor', lambda x: list(set(x))[:10])
    )
    
    df_merged = df_planilha_cond.merge(
        df_cond_crm[['id_ixc', 'nome', 'zona', 'cidade', 'bairro']],
        left_on='condominio_id',
        right_on='id_ixc',
        how='left'
    )
    
    df_merged['nome_condominio'] = df_merged['nome'].fillna(f"ID {df_merged['condominio_id']} (não cadastrado)")
    df_merged['status_cadastro'] = df_merged['nome'].apply(lambda x: '✅ Cadastrado' if pd.notna(x) else '⚠️ Não Cadastrado')
    
    # ========== MÉTRICAS DO PERÍODO ==========
    total_vendas_cond = df_merged['total_vendas'].sum()
    cond_com_vendas = len(df_merged[df_merged['total_vendas'] > 0])
    
    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.metric("📊 Vendas no Período", f"{total_vendas_cond:,}")
    with col2:
        st.metric("🏢 Condomínios com Vendas", cond_com_vendas)
    with col3:
        st.metric("📈 Média por Condomínio", f"{total_vendas_cond/cond_com_vendas:.1f}" if cond_com_vendas > 0 else "0")
    with col4:
        st.metric("📅 Período", f"{data_inicio.strftime('%d/%m')} a {data_fim.strftime('%d/%m/%y')}")
    
    st.markdown("---")
    
    # Filtros
    col_f1, col_f2 = st.columns(2)
    with col_f1:
        zonas = ["Todas"] + sorted(df_merged['zona'].dropna().unique().tolist())
        zona_sel = st.selectbox("📍 Zona:", zonas, key="cond_zona_periodo")
    
    with col_f2:
        status_opts = ["Todos", "✅ Cadastrados", "⚠️ Não Cadastrados"]
        status_sel = st.selectbox("📋 Status:", status_opts, key="cond_status_periodo")
    
    df_filtrado = df_merged.copy()
    if zona_sel != "Todas":
        df_filtrado = df_filtrado[df_filtrado['zona'] == zona_sel]
    if status_sel == "✅ Cadastrados":
        df_filtrado = df_filtrado[df_filtrado['nome'].notna()]
    elif status_sel == "⚠️ Não Cadastrados":
        df_filtrado = df_filtrado[df_filtrado['nome'].isna()]
    
    if df_filtrado.empty:
        st.warning("⚠️ Nenhum condomínio com os filtros.")
        return
    
    # Ranking
    df_ranking = df_filtrado.sort_values('total_vendas', ascending=False).reset_index(drop=True)
    df_ranking_display = df_ranking.head(CONFIG['limite_tabela'])
    
    # ========== TOP 10 COM VALORES REAIS DO PERÍODO ==========
    st.markdown(f"### 🏆 Top 10 Condomínios no Período")
    
    top_10 = df_ranking.head(10)
    
    if not top_10.empty:
        # Gráfico
        fig_rank = px.bar(
            top_10,
            x='total_vendas',
            y='nome_condominio',
            color='total_vendas',
            color_continuous_scale='Viridis',
            title=f'Top 10 Condomínios - {data_inicio.strftime("%b/%Y")} a {data_fim.strftime("%b/%Y")}',
            orientation='h',
            text='total_vendas'
        )
        fig_rank.update_traces(textposition='outside')
        fig_rank.update_layout(height=400, xaxis_title="Vendas no Período", yaxis_title="")
        st.plotly_chart(fig_rank, use_container_width=True, config={'displayModeBar': False})
        
        # Pódio
        st.markdown("### 🏅 Pódio do Período")
        col_p1, col_p2, col_p3 = st.columns(3)
        
        if len(top_10) >= 1:
            with col_p1:
                st.success(f"🥇 **{top_10.iloc[0]['nome_condominio']}**\n\n{top_10.iloc[0]['total_vendas']} vendas")
        
        if len(top_10) >= 2:
            with col_p2:
                st.info(f"🥈 **{top_10.iloc[1]['nome_condominio']}**\n\n{top_10.iloc[1]['total_vendas']} vendas")
        
        if len(top_10) >= 3:
            with col_p3:
                st.warning(f"🥉 **{top_10.iloc[2]['nome_condominio']}**\n\n{top_10.iloc[2]['total_vendas']} vendas")
    
    st.markdown("---")
    
    # Tabela completa
    st.markdown("### 📋 Lista Completa do Período")
    
    colunas = ['nome_condominio', 'total_vendas', 'zona', 'cidade', 'status_cadastro']
    colunas_existentes = [c for c in colunas if c in df_ranking_display.columns]
    
    st.dataframe(
        df_ranking_display[colunas_existentes],
        use_container_width=True,
        height=350,
        column_config={
            'nome_condominio': 'Condomínio',
            'total_vendas': st.column_config.NumberColumn('Vendas no Período', format='%d'),
            'zona': 'Zona',
            'cidade': 'Cidade',
            'status_cadastro': 'Status'
        }
    )
    
    st.caption(f"📌 Mostrando {len(df_ranking_display)} de {len(df_ranking)} condomínios com vendas no período {data_inicio.strftime('%d/%m/%Y')} a {data_fim.strftime('%d/%m/%Y')}")

# ==================== FUNÇÕES DE UI ====================
def gerar_opcoes_periodo(df):
    """
    Gera opções de período para o seletor.
    Ordem:
    1. Personalizado (primeiro)
    2. Períodos pré-selecionados (3 meses, 6 meses, etc)
    3. Meses disponíveis (do mais recente para o mais antigo)
    """
    if df is None or df.empty:
        return {}
    
    periodo_opcoes = {}
    
    # ========== 1. PERSONALIZADO (primeiro) ==========
    periodo_opcoes["🎯 Personalizado"] = "personalizado"
    
    # ========== 2. PERÍODOS PRÉ-SELECIONADOS ==========
    periodo_opcoes["📅 Últimos 3 Meses"] = 90
    periodo_opcoes["📅 Últimos 6 Meses"] = 180
    periodo_opcoes["📅 Último Ano"] = 365
    periodo_opcoes["📆 Todo o período"] = None
    
    # ========== 3. MESES DISPONÍVEIS (do mais recente para o mais antigo) ==========
    anos_meses = df.groupby(df['data_ativacao'].dt.to_period('M')).size().index
    anos_meses_ordenados = sorted(anos_meses, reverse=True)
    
    for periodo in anos_meses_ordenados:
        nome_mes = CONFIG['meses_pt'][periodo.month]
        data_inicio = datetime(periodo.year, periodo.month, 1).date()
        ultimo_dia = calendar.monthrange(periodo.year, periodo.month)[1]
        data_fim = datetime(periodo.year, periodo.month, ultimo_dia).date()
        periodo_opcoes[f"📅 {nome_mes} {periodo.year}"] = (data_inicio, data_fim)
    
    return periodo_opcoes

# ==================== DASHBOARD ====================
def render_dashboard():
    """Renderiza o dashboard completo"""
    st.title("📊 Vendas por Vendedor - Condomínios RJ")
    
    db = init_mongo()
    if db is None:
        st.stop()
    
    # ========== UPLOAD ==========
    st.markdown("---")
    st.subheader("📤 Importar Dados")
    
    uploaded_file = st.file_uploader(
        "📁 Planilha de vendas (Excel)",
        type=["xlsx", "xls"],
        key="vendas_uploader"
    )
    
    if uploaded_file is not None:
        col1, col2 = st.columns([1, 3])
        with col1:
            if st.button("🚀 Importar", type="primary", use_container_width=True):
                with st.spinner("🔄 Processando..."):
                    start_time = time.time()
                    
                    file_bytes = uploaded_file.getvalue()
                    resultado = processar_planilha_cached(file_bytes, uploaded_file.name)
                    
                    if "erro" in resultado:
                        st.error(f"❌ {resultado['erro']}")
                    else:
                        df = resultado["df"]
                        batch_id = salvar_dados_mongo(db, df)
                        if batch_id:
                            st.session_state.vendas_df = df
                            st.session_state.vendas_batch = batch_id
                            st.success(f"✅ {resultado['total']:,} registros em {time.time() - start_time:.1f}s")
                            st.rerun()
    
    # ========== CARREGAR DADOS ==========
    if 'vendas_df' not in st.session_state:
        with st.spinner("🔄 Carregando dados..."):
            resultado = carregar_dados_mongo(db)
            if resultado:
                df, batch_id = resultado
                st.session_state.vendas_df = df
                st.session_state.vendas_batch = batch_id
                st.info(f"📋 {len(df):,} registros carregados")
            else:
                st.info("ℹ️ Nenhum dado. Faça upload.")
    
    df = st.session_state.get('vendas_df')
    
    if df is None or df.empty:
        st.warning("⚠️ Nenhum dado carregado.")
        return
    
    # ========== PERÍODO ==========
    st.markdown("---")
    st.subheader("📅 Período de Análise")
    
    min_date = df['data_ativacao'].min().date()
    max_date = df['data_ativacao'].max().date()
    periodo_opcoes = gerar_opcoes_periodo(df)
    
    col1, col2 = st.columns([2, 1])
    
    with col1:
        periodo_selecionado = st.selectbox(
            "Período:",
            list(periodo_opcoes.keys()),
            key="periodo"
        )
    
    with col2:
        if st.button("🔄 Atualizar", use_container_width=True):
            st.rerun()
    
    # Calcular período
    if periodo_selecionado == "🎯 Personalizado":
        col_d1, col_d2 = st.columns(2)
        with col_d1:
            data_inicio = st.date_input("Início", min_date, min_value=min_date, max_value=max_date)
        with col_d2:
            data_fim = st.date_input("Fim", max_date, min_value=min_date, max_value=max_date)
    else:
        dias = periodo_opcoes[periodo_selecionado]
        if dias is None:
            data_inicio, data_fim = min_date, max_date
        elif isinstance(dias, tuple):
            data_inicio, data_fim = dias
        else:
            data_fim = max_date
            data_inicio = max((datetime.combine(data_fim, datetime.min.time()) - timedelta(days=dias)).date(), min_date)
    
    if data_inicio > data_fim:
        st.error("⚠️ Data inválida")
        return
    
    # Hash para cache
    df_hash = df.copy()
    data_inicio_str = datetime.combine(data_inicio, datetime.min.time()).isoformat()
    data_fim_str = datetime.combine(data_fim, datetime.min.time()).isoformat()
    
    # ========== FILTRO VENDEDOR ==========
    vendedores = ["Todos"] + sorted(df['vendedor'].unique().tolist())
    vendedor_sel = st.sidebar.selectbox("👤 Vendedor", vendedores, key="vendedor_filtro")
    
    # ========== DADOS FILTRADOS ==========
    df_filtrado = df[(df['data_ativacao'] >= pd.Timestamp(data_inicio)) & (df['data_ativacao'] <= pd.Timestamp(data_fim))].copy()
    
    if vendedor_sel != "Todos":
        df_filtrado = df_filtrado[df_filtrado['vendedor'] == vendedor_sel]
    
    if df_filtrado.empty:
        st.warning("⚠️ Nenhum dado no período.")
        return
    
    # ========== MÉTRICAS ==========
    total_vendas = len(df_filtrado)
    total_vendedores = df_filtrado['vendedor'].nunique()
    
    col1, col2, col3, col4 = st.columns(4)
    col1.metric("📊 Vendas", f"{total_vendas:,}")
    col2.metric("👤 Vendedores", f"{total_vendedores}")
    col3.metric("📈 Média", f"{total_vendas/total_vendedores:.1f}" if total_vendedores > 0 else "0")
    col4.metric("📅 Período", f"{data_inicio.strftime('%d/%m')} a {data_fim.strftime('%d/%m/%y')}")
    
    st.markdown("---")
    
    # ========== ABAS ==========
    tab1, tab2, tab3, tab4, tab5 = st.tabs([
        "📊 Vendas por Vendedor",
        "📈 Evolução Semanal",
        "📈 Evolução Mensal",
        "🏢 Desempenho por Condomínio",
        "📤 Exportar"
    ])
    
    with tab1:
        st.subheader("👥 Vendas por Vendedor")
        
        with st.spinner("🔄 Calculando..."):
            vendas_vendedor = calcular_vendas_vendedor_cached(df_hash, data_inicio_str, data_fim_str)
        
        if not vendas_vendedor.empty:
            top_vendedores = vendas_vendedor.head(CONFIG['limite_grafico'])
            
            fig = px.bar(
                top_vendedores,
                x='vendedor',
                y='total_vendas',
                title=f'📊 Vendas por Vendedor ({len(vendas_vendedor)} vendedores)',
                color='total_vendas',
                color_continuous_scale='Viridis',
                text='total_vendas'
            )
            fig.update_traces(textposition='outside')
            fig.update_layout(height=350, xaxis_title="", yaxis_title="Vendas")
            st.plotly_chart(fig, use_container_width=True, config={'displayModeBar': False})
            
            st.dataframe(
                vendas_vendedor,
                use_container_width=True,
                height=250,
                column_config={
                    'vendedor': 'Vendedor',
                    'total_vendas': st.column_config.NumberColumn('Vendas', format='%d')
                }
            )
    
    with tab2:
        st.subheader("📈 Evolução Semanal de Vendas")
        
        with st.spinner("🔄 Calculando evolução..."):
            vendas_semanais, vendas_diarias = calcular_vendas_semanais_cached(df_hash, data_inicio_str, data_fim_str)
        
        if not vendas_semanais.empty:
            # ========== INDICADOR DE EVOLUÇÃO ==========
            st.markdown("### 🎯 Indicador de Evolução por Vendedor")
            
            evolucao_df = calcular_indicador_evolucao(vendas_semanais)
            
            if not evolucao_df.empty:
                col1, col2, col3, col4 = st.columns(4)
                
                cresc_forte = len(evolucao_df[evolucao_df['tendencia'] == '🚀 Crescimento Forte'])
                cresc_mod = len(evolucao_df[evolucao_df['tendencia'] == '📈 Crescimento Moderado'])
                estavel = len(evolucao_df[evolucao_df['tendencia'] == '➡️ Estável'])
                declinio = len(evolucao_df[evolucao_df['tendencia'].str.contains('Declínio')])
                
                col1.metric("📈 Crescendo", f"{cresc_forte + cresc_mod} vendedores")
                col2.metric("➡️ Estável", f"{estavel} vendedores")
                col3.metric("📉 Declinando", f"{declinio} vendedores")
                col4.metric("📊 Média Evolução", f"{evolucao_df['media_evolucao'].mean():.1f}%")
                
                st.markdown("---")
                
                evolucao_display = evolucao_df.reset_index()
                evolucao_display = evolucao_display[['vendedor', 'media_evolucao', 'tendencia']]
                evolucao_display = evolucao_display.sort_values('media_evolucao', ascending=False)
                
                fig_evol = px.bar(
                    evolucao_display,
                    x='vendedor',
                    y='media_evolucao',
                    color='tendencia',
                    title='📊 Evolução Média Semanal por Vendedor (%)',
                    text='media_evolucao',
                    color_discrete_map={
                        '🚀 Crescimento Forte': '#2ecc71',
                        '📈 Crescimento Moderado': '#27ae60',
                        '➡️ Estável': '#f39c12',
                        '📉 Declínio Moderado': '#e67e22',
                        '🔻 Declínio Forte': '#e74c3c'
                    }
                )
                fig_evol.update_traces(texttemplate='%{text:.1f}%', textposition='outside')
                fig_evol.update_layout(height=400, xaxis_title="Vendedor", yaxis_title="Evolução (%)")
                st.plotly_chart(fig_evol, use_container_width=True, config={'displayModeBar': False})
                
                st.dataframe(
                    evolucao_display,
                    use_container_width=True,
                    column_config={
                        'vendedor': 'Vendedor',
                        'media_evolucao': st.column_config.NumberColumn('Evolução Média', format='%.1f%%'),
                        'tendencia': 'Tendência'
                    }
                )
            
            # ========== GRÁFICO SEMANAL ==========
            st.markdown("---")
            st.markdown("### 📊 Vendas Semanais por Vendedor")
            
            pivot_semanal = vendas_semanais.pivot_table(
                index='semana_str',
                columns='vendedor',
                values='total_vendas',
                fill_value=0
            )
            
            # Ordenar semanas (1, 2, 3, 4, 5)
            pivot_semanal = pivot_semanal.reindex(sorted(pivot_semanal.index), axis=0)
            
            if not pivot_semanal.empty:
                fig_linhas = px.line(
                    pivot_semanal,
                    title='📈 Evolução Semanal de Vendas por Vendedor',
                    labels={'value': 'Vendas', 'semana_str': 'Semana do Mês', 'variable': 'Vendedor'},
                    markers=True
                )
                fig_linhas.update_layout(height=400, hovermode='x unified')
                st.plotly_chart(fig_linhas, use_container_width=True, config={'displayModeBar': False})
            
            # ========== VENDAS DIÁRIAS ==========
            st.markdown("---")
            st.markdown("### 📅 Vendas Diárias por Semana")
            
            semanas_disponiveis = sorted(vendas_diarias['semana_str'].unique())
            if semanas_disponiveis:
                semana_selecionada = st.selectbox(
                    "Selecione a semana para detalhamento:",
                    semanas_disponiveis,
                    key="semana_detalhe"
                )
                
                df_semana = vendas_diarias[vendas_diarias['semana_str'] == semana_selecionada]
                
                fig_diario = px.bar(
                    df_semana,
                    x='data_str',
                    y='total_vendas',
                    color='vendedor',
                    title=f'📊 Vendas Diárias - {semana_selecionada}',
                    labels={'data_str': 'Dia', 'total_vendas': 'Vendas', 'vendedor': 'Vendedor'},
                    barmode='group'
                )
                fig_diario.update_layout(height=400)
                st.plotly_chart(fig_diario, use_container_width=True, config={'displayModeBar': False})
                
                st.dataframe(
                    df_semana,
                    use_container_width=True,
                    column_config={
                        'vendedor': 'Vendedor',
                        'semana_str': 'Semana',
                        'data_str': 'Data',
                        'dia_semana': 'Dia da Semana',
                        'total_vendas': st.column_config.NumberColumn('Vendas', format='%d')
                    }
                )
            
            with st.expander("📋 Ver Tabela Completa de Vendas Semanais"):
                st.dataframe(
                    vendas_semanais,
                    use_container_width=True,
                    column_config={
                        'vendedor': 'Vendedor',
                        'semana_str': 'Semana',
                        'total_vendas': st.column_config.NumberColumn('Vendas', format='%d')
                    }
                )
        else:
            st.info("ℹ️ Nenhum dado semanal disponível para o período selecionado.")
    
    # ========== NOVA ABA: EVOLUÇÃO MENSAL ==========
    with tab3:
        render_evolucao_mensal(df, data_inicio, data_fim)
    
    with tab4:
        render_desempenho_por_condominio(df, data_inicio, data_fim)
    
    with tab5:
        st.subheader("📤 Exportar Dados")
        
        exportar_vendas_vendedor = st.checkbox("📊 Vendas por Vendedor", value=True)
        exportar_evolucao = st.checkbox("📈 Indicador de Evolução Semanal", value=True)
        exportar_semanal = st.checkbox("📅 Dados Semanais", value=True)
        exportar_mensal = st.checkbox("📈 Evolução Mensal", value=True)
        exportar_condominios = st.checkbox("🏢 Desempenho por Condomínio", value=True)
        
        if st.button("📥 Gerar Excel", type="primary"):
            with st.spinner("🔄 Gerando arquivo..."):
                try:
                    output = BytesIO()
                    with pd.ExcelWriter(output, engine='openpyxl') as writer:
                        # Dados filtrados
                        df_filtrado.to_excel(writer, sheet_name='Dados Filtrados', index=False)
                        
                        # Vendas por vendedor
                        if exportar_vendas_vendedor:
                            vendas_vendedor = calcular_vendas_vendedor_cached(df_hash, data_inicio_str, data_fim_str)
                            if not vendas_vendedor.empty:
                                vendas_vendedor.to_excel(writer, sheet_name='Vendas por Vendedor', index=False)
                        
                        # Evolução semanal
                        if exportar_evolucao:
                            vendas_semanais, _ = calcular_vendas_semanais_cached(df_hash, data_inicio_str, data_fim_str)
                            if not vendas_semanais.empty:
                                evolucao_df = calcular_indicador_evolucao(vendas_semanais)
                                if not evolucao_df.empty:
                                    evolucao_df.reset_index().to_excel(writer, sheet_name='Evolução Vendedores', index=False)
                        
                        # Dados semanais
                        if exportar_semanal:
                            vendas_semanais, vendas_diarias = calcular_vendas_semanais_cached(df_hash, data_inicio_str, data_fim_str)
                            if not vendas_semanais.empty:
                                vendas_semanais.to_excel(writer, sheet_name='Vendas Semanais', index=False)
                            if not vendas_diarias.empty:
                                vendas_diarias.to_excel(writer, sheet_name='Vendas Diárias', index=False)
                        
                        # Evolução mensal
                        if exportar_mensal:
                            todos_vendedores = df['vendedor'].unique().tolist()
                            vendas_mensais = calcular_vendas_mensais_cached(df_hash, data_inicio_str, data_fim_str, todos_vendedores)
                            if not vendas_mensais.empty:
                                vendas_mensais.to_excel(writer, sheet_name='Evolução Mensal', index=False)
                        
                        # Condomínios
                        if exportar_condominios:
                            df_cond = get_condominios_crm_cached()
                            if not df_cond.empty:
                                df_cond.to_excel(writer, sheet_name='Condomínios CRM', index=False)
                    
                    output.seek(0)
                    
                    st.download_button(
                        label="⬇️ Baixar Excel",
                        data=output,
                        file_name=f"vendas_{data_inicio.strftime('%Y%m%d')}_{data_fim.strftime('%Y%m%d')}.xlsx",
                        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                        use_container_width=True
                    )
                    st.success("✅ Arquivo gerado!")
                except Exception as e:
                    st.error(f"❌ Erro: {str(e)}")

# ==================== FUNÇÃO PRINCIPAL ====================
def render_vendas_vendedor_condominios():
    """Função principal do módulo"""
    perfil = st.session_state.get('perfil', '')
    if perfil not in ['admin', 'diretoria']:
        st.error("🚫 Acesso restrito a admin e diretoria.")
        return
    
    render_dashboard()

if __name__ == "__main__":
    render_vendas_vendedor_condominios()
