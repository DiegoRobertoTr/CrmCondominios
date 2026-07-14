# modules/vendas_vendedor_condominios.py
"""
Módulo de Vendas por Vendedor - CRM Condomínios RJ
VERSÃO COMPLETA E OTIMIZADA COM:
- Upload com limpeza automática do MongoDB
- Vendas por vendedor
- Evolução semanal (com semana do MÊS)
- Evolução mensal com seleção múltipla de vendedores e PROJEÇÃO baseada no período selecionado
- VISUALIZAÇÃO EVOLUTIVA MÊS A MÊS (COM VENDAS REAIS E PROJEÇÃO COMO REFERÊNCIA)
- Metas configuráveis por vendedor
- Ranking com posição, vendas, projeção, meta e % de alcance
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

# ==================== METAS DOS VENDEDORES ====================
# Metas padrão - podem ser ajustadas pelo usuário
METAS_PADRAO = {
    'Larissa Oliveira dos Santos': 200,
    'Leandro Monteiro': 120,
    'Kessia Priscila da Conceição Silva': 80,
    'Laryssa Medeiros': 25,
    'Estephani Marcolino': 15,
    'Erick Eduardo Lombardi': 30,
    'RETORNO FINANCEIRO': 10,
    'Vendedor padrão': 20
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

# ==================== FUNÇÃO: EVOLUÇÃO MENSAL COM PROJEÇÃO E METAS ====================

@st.cache_data(ttl=CONFIG['cache_ttl'], show_spinner=False)
def calcular_vendas_mensais_cached(df_hash, data_inicio_str, data_fim_str, vendedores_selecionados):
    """
    Calcula vendas mensais para vendedores selecionados
    COM PROJEÇÃO BASEADA NO PERÍODO SELECIONADO
    CORRIGIDO: Projeção considera apenas o período analisado para meses parciais
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
    df_filtrado['dia'] = df_filtrado['data_ativacao'].dt.day
    df_filtrado['dia_semana'] = df_filtrado['data_ativacao'].dt.dayofweek  # 0=Segunda, 6=Domingo
    
    # ========== DADOS REAIS POR MÊS ==========
    vendas_mensais = df_filtrado.groupby(['vendedor', 'mes_ano', 'mes_str', 'ano_mes_num']).agg(
        total_vendas=('cliente', 'count'),
        dias_com_vendas=('dia', 'nunique')
    ).reset_index().sort_values(['vendedor', 'ano_mes_num'])
    
    # ========== CALCULAR DIAS ÚTEIS (SEGUNDA A SÁBADO) ==========
    def get_dias_uteis_seg_sab(ano, mes, data_inicio, data_fim):
        """Calcula quantos dias úteis (Segunda a Sábado) no período"""
        import calendar
        dias_uteis = 0
        
        # Primeiro dia do mês
        primeiro_dia_mes = datetime(ano, mes, 1)
        ultimo_dia_mes = calendar.monthrange(ano, mes)[1]
        ultimo_dia_mes_dt = datetime(ano, mes, ultimo_dia_mes)
        
        # Ajustar para o período
        inicio_periodo = max(primeiro_dia_mes, data_inicio)
        fim_periodo = min(ultimo_dia_mes_dt, data_fim)
        
        if inicio_periodo > fim_periodo:
            return 0
        
        # Contar dias de Segunda a Sábado (0=Segunda, 5=Sábado, 6=Domingo)
        data_atual = inicio_periodo
        while data_atual <= fim_periodo:
            if data_atual.weekday() < 6:  # Segunda a Sábado
                dias_uteis += 1
            data_atual += timedelta(days=1)
        
        return dias_uteis
    
    # Adicionar dias úteis do período por mês
    vendas_mensais['dias_uteis_periodo'] = vendas_mensais.apply(
        lambda row: get_dias_uteis_seg_sab(
            row['mes_ano'].year, 
            row['mes_ano'].month,
            data_inicio,
            data_fim
        ),
        axis=1
    )
    
    # Calcular total de dias úteis no mês (Segunda a Sábado)
    def get_total_dias_uteis_seg_sab(ano, mes):
        """Calcula total de dias úteis (Segunda a Sábado) no mês"""
        import calendar
        dias_uteis = 0
        ultimo_dia = calendar.monthrange(ano, mes)[1]
        
        for dia in range(1, ultimo_dia + 1):
            data = datetime(ano, mes, dia)
            if data.weekday() < 6:  # Segunda a Sábado
                dias_uteis += 1
        return dias_uteis
    
    vendas_mensais['dias_uteis_mes'] = vendas_mensais.apply(
        lambda row: get_total_dias_uteis_seg_sab(row['mes_ano'].year, row['mes_ano'].month),
        axis=1
    )
    
    # ========== IDENTIFICAR ÚLTIMO MÊS DO PERÍODO ==========
    ultimo_mes_periodo = data_fim.month
    ultimo_ano_periodo = data_fim.year
    
    # Verificar se o último mês é parcial (data_fim não é o último dia do mês)
    ultimo_dia_mes = calendar.monthrange(data_fim.year, data_fim.month)[1]
    is_mes_parcial = data_fim.day < ultimo_dia_mes
    
    vendas_mensais['is_ultimo_mes'] = (vendas_mensais['mes_ano'].dt.year == ultimo_ano_periodo) & (vendas_mensais['mes_ano'].dt.month == ultimo_mes_periodo)
    
    # Verificar se o mês é parcial
    vendas_mensais['is_mes_parcial'] = vendas_mensais.apply(
        lambda row: is_mes_parcial if row['is_ultimo_mes'] else False,
        axis=1
    )
    
    # ========== CALCULAR PROJEÇÃO CORRIGIDA ==========
    # CORREÇÃO: A média diária deve considerar APENAS os dias úteis do período analisado
    vendas_mensais['media_diaria'] = vendas_mensais.apply(
        lambda row: row['total_vendas'] / row['dias_uteis_periodo'] if row['dias_uteis_periodo'] > 0 else 0,
        axis=1
    )
    
    # Calcular média por dia com vendas (mais conservadora)
    vendas_mensais['media_por_dia_com_vendas'] = vendas_mensais.apply(
        lambda row: row['total_vendas'] / row['dias_com_vendas'] if row['dias_com_vendas'] > 0 else 0,
        axis=1
    )
    
    # Usar a média mais conservadora (menor entre as duas)
    vendas_mensais['media_diaria_final'] = vendas_mensais.apply(
        lambda row: min(row['media_diaria'], row['media_por_dia_com_vendas']) 
        if row['media_diaria'] > 0 and row['media_por_dia_com_vendas'] > 0 
        else row['media_diaria'],
        axis=1
    )
    
    # CORREÇÃO: Projeção = média diária final × total de dias úteis do MÊS COMPLETO
    # Mas apenas para o mês parcial (último mês)
    vendas_mensais['projecao_mes'] = vendas_mensais.apply(
        lambda row: row['media_diaria_final'] * row['dias_uteis_mes'] 
        if row['media_diaria_final'] > 0 and row['is_mes_parcial'] 
        else row['total_vendas'],
        axis=1
    )
    
    # ========== USAR PROJEÇÃO PARA MÊS PARCIAL ==========
    vendas_mensais['vendas_ajustadas'] = vendas_mensais.apply(
        lambda row: row['projecao_mes'] if row['is_mes_parcial'] else row['total_vendas'],
        axis=1
    )
    
    # ========== CALCULAR MÉDIA DIÁRIA PROJETADA ==========
    vendas_mensais['media_diaria_projetada'] = vendas_mensais.apply(
        lambda row: row['vendas_ajustadas'] / row['dias_uteis_mes'] if row['dias_uteis_mes'] > 0 else 0,
        axis=1
    )
    
    # ========== CALCULAR VARIAÇÃO MENSAL ==========
    vendas_mensais['variacao_mensal'] = 0.0
    
    for vendedor in vendas_mensais['vendedor'].unique():
        mask = vendas_mensais['vendedor'] == vendedor
        dados_vendedor = vendas_mensais.loc[mask].sort_values('ano_mes_num')
        
        vendas_ajustadas = dados_vendedor['vendas_ajustadas'].values
        
        for i in range(1, len(vendas_ajustadas)):
            if vendas_ajustadas[i-1] > 0:
                variacao_ajustada = ((vendas_ajustadas[i] - vendas_ajustadas[i-1]) / vendas_ajustadas[i-1]) * 100
            else:
                variacao_ajustada = 100 if vendas_ajustadas[i] > 0 else 0
            vendas_mensais.loc[mask & (vendas_mensais['ano_mes_num'] == dados_vendedor['ano_mes_num'].iloc[i]), 'variacao_mensal'] = variacao_ajustada
    
    return vendas_mensais

# ==================== FUNÇÃO: VISUALIZAÇÃO EVOLUTIVA MÊS A MÊS ====================

def render_evolucao_mensal_evolutiva(vendas_mensais, metas, data_inicio, data_fim):
    """
    Renderiza a visualização evolutiva mês a mês para os vendedores selecionados
    Exibe gráfico de BARRAS com VENDAS REAIS e linha de PROJEÇÃO para o mês parcial
    """
    if vendas_mensais.empty:
        st.info("ℹ️ Nenhum dado mensal disponível para a visualização evolutiva.")
        return
    
    st.markdown("### 📈 Evolução Mensal - Mês a Mês")
    st.markdown(f"""
    <div style="background-color:#f0f8ff; padding:12px; border-radius:8px; margin-bottom:15px; font-size:13px;">
    <strong>📅 Período:</strong> {data_inicio.strftime('%d/%m/%Y')} a {data_fim.strftime('%d/%m/%Y')}
    </div>
    """, unsafe_allow_html=True)
    
    # ========== ORDENAR DADOS CRONOLOGICAMENTE ==========
    # Criar uma coluna de data para ordenação
    vendas_mensais['data_ordem'] = pd.to_datetime(vendas_mensais['mes_str'], format='%b/%Y')
    vendas_mensais = vendas_mensais.sort_values(['vendedor', 'data_ordem'])
    
    # ========== PREPARAR DADOS PARA O GRÁFICO ==========
    # Pivot para o gráfico com VENDAS REAIS (total_vendas)
    df_pivot_real = vendas_mensais.pivot_table(
        index='mes_str',
        columns='vendedor',
        values='total_vendas',
        fill_value=0
    )
    
    # Pivot para a projeção (apenas meses parciais)
    df_pivot_projecao = vendas_mensais.pivot_table(
        index='mes_str',
        columns='vendedor',
        values='projecao_mes',
        fill_value=0
    )
    
    # Ordenar por data (cronologicamente)
    ordem_meses = vendas_mensais.groupby('mes_str')['data_ordem'].first().sort_values().index.tolist()
    df_pivot_real = df_pivot_real.reindex(ordem_meses, axis=0)
    df_pivot_projecao = df_pivot_projecao.reindex(ordem_meses, axis=0)
    
    # Identificar meses parciais
    meses_parciais = vendas_mensais[vendas_mensais['is_mes_parcial']]['mes_str'].unique().tolist()
    
    # ========== GRÁFICO DE BARRAS AGRUPADAS ==========
    st.markdown("### 📊 Evolução Mensal de Vendas Reais")
    
    fig_barras = go.Figure()
    
    # Adicionar barras para cada vendedor (VENDAS REAIS)
    for vendedor in df_pivot_real.columns:
        fig_barras.add_trace(go.Bar(
            x=df_pivot_real.index,
            y=df_pivot_real[vendedor],
            name=vendedor,
            text=df_pivot_real[vendedor].apply(lambda x: f'{int(x)}' if x > 0 else ''),
            textposition='outside',
            hovertemplate=f'<b>{vendedor}</b><br>Mês: %{{x}}<br>Vendas Reais: %{{y:.0f}}<extra></extra>'
        ))
    
    # Adicionar linha de projeção para meses parciais (tracejada)
    for vendedor in df_pivot_projecao.columns:
        # Filtrar apenas meses parciais com projeção > 0
        meses_com_projecao = []
        valores_projecao = []
        
        for mes in meses_parciais:
            if mes in df_pivot_projecao.index:
                valor = df_pivot_projecao.loc[mes, vendedor]
                if valor > 0:
                    meses_com_projecao.append(mes)
                    valores_projecao.append(valor)
        
        if meses_com_projecao:
            fig_barras.add_trace(go.Scatter(
                x=meses_com_projecao,
                y=valores_projecao,
                mode='markers+lines',
                name=f'{vendedor} (Projeção)',
                line=dict(dash='dash', width=2, color='orange'),
                marker=dict(symbol='diamond', size=10, color='orange'),
                hovertemplate=f'<b>{vendedor}</b><br>Mês: %{{x}}<br>Projeção: %{{y:.1f}}<extra></extra>'
            ))
    
    # Adicionar linha de meta média
    if metas and len(metas) > 0:
        meta_media = sum(metas.values()) / len(metas)
        if meta_media > 0:
            fig_barras.add_hline(
                y=meta_media,
                line_dash="dot",
                line_color="green",
                opacity=0.7,
                annotation_text=f"🎯 Meta Média: {meta_media:.0f}",
                annotation_position="bottom right"
            )
    
    # Adicionar marcações para meses parciais
    for mes in meses_parciais:
        if mes in df_pivot_real.index:
            fig_barras.add_annotation(
                x=mes,
                y=0.95,
                yref="paper",
                text="📊 Projetado",
                showarrow=False,
                font=dict(color="orange", size=10),
                bgcolor="rgba(255,255,255,0.9)",
                bordercolor="orange",
                borderwidth=1,
                borderpad=4
            )
    
    fig_barras.update_layout(
        title='📊 Evolução Mensal de Vendas Reais por Vendedor',
        xaxis_title='Mês',
        yaxis_title='Vendas Reais',
        height=450,
        barmode='group',
        legend=dict(
            orientation='h',
            yanchor='bottom',
            y=1.02,
            xanchor='right',
            x=1
        )
    )
    
    st.plotly_chart(fig_barras, use_container_width=True, config={'displayModeBar': False})
    
    # ========== TABELA DETALHADA EM ORDEM CRONOLÓGICA ==========
    st.markdown("### 📋 Detalhamento Mensal por Vendedor")
    
    # Preparar tabela com valores em ordem cronológica
    tabela_evolutiva = vendas_mensais[['vendedor', 'mes_str', 'total_vendas', 'projecao_mes', 'variacao_mensal', 'is_mes_parcial', 'data_ordem']].copy()
    
    # Ordenar por vendedor e data
    tabela_evolutiva = tabela_evolutiva.sort_values(['vendedor', 'data_ordem'])
    
    # Adicionar variação mensal formatada
    tabela_evolutiva['variacao_formatada'] = tabela_evolutiva['variacao_mensal'].apply(
        lambda x: f"{x:+.1f}%" if x != 0 else "0%"
    )
    
    # Marcar meses parciais e mostrar projeção
    tabela_evolutiva['status'] = tabela_evolutiva['is_mes_parcial'].apply(
        lambda x: "⭐ Projetado" if x else "✅ Realizado"
    )
    
    # Criar coluna com projeção apenas para meses parciais
    tabela_evolutiva['projecao_display'] = tabela_evolutiva.apply(
        lambda row: f"{row['projecao_mes']:.1f}" if row['is_mes_parcial'] and row['projecao_mes'] > 0 else "-",
        axis=1
    )
    
    # Ordenar e exibir
    tabela_display = tabela_evolutiva[['vendedor', 'mes_str', 'total_vendas', 'projecao_display', 'variacao_formatada', 'status']]
    tabela_display = tabela_display.rename(columns={
        'vendedor': 'Vendedor',
        'mes_str': 'Mês',
        'total_vendas': 'Vendas Reais',
        'projecao_display': 'Projeção',
        'variacao_formatada': 'Variação Mensal',
        'status': 'Status'
    })
    
    st.dataframe(
        tabela_display,
        use_container_width=True,
        height=300,
        column_config={
            'Vendedor': st.column_config.TextColumn('Vendedor', width='medium'),
            'Mês': st.column_config.TextColumn('Mês', width='small'),
            'Vendas Reais': st.column_config.NumberColumn('Vendas Reais', format='%d'),
            'Projeção': st.column_config.TextColumn('Projeção', width='small'),
            'Variação Mensal': st.column_config.TextColumn('Variação %', width='small'),
            'Status': st.column_config.TextColumn('Status', width='small')
        }
    )
    
    # ========== RESUMO POR VENDEDOR ==========
    st.markdown("### 📊 Resumo por Vendedor")
    
    resumo_vendedor = vendas_mensais.groupby('vendedor').agg(
        total_vendas_periodo=('total_vendas', 'sum'),
        media_mensal_real=('total_vendas', 'mean'),
        max_mensal=('total_vendas', 'max'),
        min_mensal=('total_vendas', 'min'),
        meses_ativos=('mes_str', 'nunique')
    ).reset_index()
    
    # Adicionar meta
    resumo_vendedor['meta'] = resumo_vendedor['vendedor'].apply(
        lambda x: metas.get(x, METAS_PADRAO.get(x, 20))
    )
    
    # Calcular % da meta (média mensal vs meta)
    resumo_vendedor['percentual_meta'] = (resumo_vendedor['media_mensal_real'] / resumo_vendedor['meta'] * 100).fillna(0)
    
    resumo_display = resumo_vendedor[['vendedor', 'total_vendas_periodo', 'media_mensal_real', 'meta', 'percentual_meta', 'meses_ativos']]
    resumo_display = resumo_display.rename(columns={
        'vendedor': 'Vendedor',
        'total_vendas_periodo': 'Total Período',
        'media_mensal_real': 'Média Mensal',
        'meta': 'Meta Mensal',
        'percentual_meta': '% da Meta',
        'meses_ativos': 'Meses Ativos'
    })
    
    st.dataframe(
        resumo_display,
        use_container_width=True,
        column_config={
            'Vendedor': st.column_config.TextColumn('Vendedor', width='medium'),
            'Total Período': st.column_config.NumberColumn('Total Período', format='%d'),
            'Média Mensal': st.column_config.NumberColumn('Média Mensal', format='%.1f'),
            'Meta Mensal': st.column_config.NumberColumn('Meta Mensal', format='%d'),
            '% da Meta': st.column_config.NumberColumn('% da Meta', format='%.1f%%'),
            'Meses Ativos': st.column_config.NumberColumn('Meses Ativos', format='%d')
        }
    )

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
    
    # ========== ABA: EVOLUÇÃO MENSAL ==========
    with tab3:
        st.subheader("📈 Evolução Mensal")
        
        # ========== SELETOR DE VENDEDORES ==========
        vendedores_disponiveis = sorted(df_filtrado['vendedor'].unique().tolist())
        
        st.markdown("### 👥 Selecione os Vendedores")
        
        col1, col2 = st.columns([3, 1])
        
        with col1:
            opcoes_vendedores = ["👥 Todos"] + vendedores_disponiveis
            
            default_value = ["👥 Todos"] if "👥 Todos" in opcoes_vendedores else [opcoes_vendedores[0]]
            
            vendedores_selecionados = st.multiselect(
                "Selecione um ou mais vendedores:",
                options=opcoes_vendedores,
                default=default_value,
                key="vendedores_mensais",
                help="Selecione 'Todos' ou escolha vendedores específicos"
            )
        
        with col2:
            if st.button("🗑️ Limpar", key="limpar_vendedores"):
                st.session_state.vendedores_mensais = ["👥 Todos"]
                st.rerun()
        
        # Processar seleção
        if not vendedores_selecionados:
            st.warning("⚠️ Selecione pelo menos um vendedor.")
            return
        
        if "👥 Todos" in vendedores_selecionados:
            vendedores_selecionados = vendedores_disponiveis
            label_selecao = "Todos os Vendedores"
        else:
            label_selecao = f"{len(vendedores_selecionados)} vendedores selecionados"
        
        st.caption(f"📌 {label_selecao}")
        
        # ========== CONFIGURAR METAS ==========
        st.markdown("---")
        st.markdown("### 🎯 Configurar Metas")
        
        with st.expander("📝 Definir Metas Mensais por Vendedor"):
            st.info("💡 Defina a meta mensal de vendas para cada vendedor.")
            
            metas = {}
            cols_meta = st.columns(2)
            
            for i, vendedor in enumerate(vendedores_selecionados):
                col = cols_meta[i % 2]
                valor_padrao = METAS_PADRAO.get(vendedor, 20)
                metas[vendedor] = col.number_input(
                    f"Meta {vendedor}",
                    min_value=1,
                    max_value=1000,
                    value=valor_padrao,
                    step=5,
                    key=f"meta_{vendedor}_{i}"
                )
            
            if st.button("📊 Aplicar Metas", key="aplicar_metas"):
                st.success("✅ Metas aplicadas com sucesso!")
        
        # ========== CALCULAR DADOS MENSAIS ==========
        with st.spinner("🔄 Calculando evolução mensal..."):
            vendas_mensais = calcular_vendas_mensais_cached(df_hash, data_inicio_str, data_fim_str, vendedores_selecionados)
        
        if vendas_mensais.empty:
            st.warning("⚠️ Nenhum dado mensal disponível para os vendedores selecionados.")
            return
        
        # ========== VISUALIZAÇÃO EVOLUTIVA MÊS A MÊS ==========
        render_evolucao_mensal_evolutiva(vendas_mensais, metas, data_inicio, data_fim)
        
        st.markdown("---")
        st.markdown("### 🏆 Ranking de Desempenho")
        
        # ========== CRIAR RANKING ==========
        ranking_data = []
        
        for vendedor in vendedores_selecionados:
            dados_vendedor = vendas_mensais[vendas_mensais['vendedor'] == vendedor]
            
            if dados_vendedor.empty:
                continue
            
            dados_vendedor = dados_vendedor.sort_values('ano_mes_num')
            ultimo_mes = dados_vendedor.iloc[-1]
            
            vendas_reais = ultimo_mes['total_vendas']
            
            if ultimo_mes['is_mes_parcial']:
                projecao = ultimo_mes['projecao_mes']
                media_diaria = ultimo_mes['media_diaria_final']
                dias_uteis_mes = ultimo_mes['dias_uteis_mes']
            else:
                projecao = vendas_reais
                media_diaria = ultimo_mes['total_vendas'] / ultimo_mes['dias_uteis_mes'] if ultimo_mes['dias_uteis_mes'] > 0 else 0
                dias_uteis_mes = ultimo_mes['dias_uteis_mes']
            
            meta = metas.get(vendedor, METAS_PADRAO.get(vendedor, 20))
            percentual_meta = (projecao / meta * 100) if meta > 0 else 0
            dias_uteis_periodo = ultimo_mes['dias_uteis_periodo']
            
            ranking_data.append({
                'Vendedor': vendedor,
                'Vendas Realizadas': int(vendas_reais),
                'Projeção': int(projecao),
                'Meta': int(meta),
                '% da Meta': min(percentual_meta, 200),
                'Média Diária': media_diaria,
                'Dias Úteis Período': int(dias_uteis_periodo),
                'Dias Úteis Mês': int(dias_uteis_mes),
                'Status': '📊 Projetado' if ultimo_mes['is_mes_parcial'] else '✅ Realizado'
            })
        
        if ranking_data:
            df_ranking = pd.DataFrame(ranking_data)
            df_ranking = df_ranking.sort_values('Projeção', ascending=False).reset_index(drop=True)
            df_ranking.index = df_ranking.index + 1
            
            def get_posicao_emoji(pos):
                if pos == 1:
                    return "🥇"
                elif pos == 2:
                    return "🥈"
                elif pos == 3:
                    return "🥉"
                else:
                    return f"{pos}º"
            
            df_ranking['Posição'] = df_ranking.index
            df_ranking['Posição'] = df_ranking['Posição'].apply(get_posicao_emoji)
            
            # Identificar mês parcial
            mes_parcial_nome = vendas_mensais[vendas_mensais['is_mes_parcial']]['mes_str'].iloc[0] if not vendas_mensais[vendas_mensais['is_mes_parcial']].empty else None
            
            st.markdown(f"""
            <div style="background-color:#f0f8ff; padding:12px; border-radius:8px; margin-bottom:15px; font-size:14px;">
            <strong>📌 Mês analisado:</strong> {mes_parcial_nome if mes_parcial_nome else 'Último mês do período'}
            {f' (parcial - com projeção)' if mes_parcial_nome else ''}
            </div>
            """, unsafe_allow_html=True)
            
            st.dataframe(
                df_ranking,
                use_container_width=True,
                height=400,
                column_config={
                    'Posição': st.column_config.TextColumn('🏆', width='small'),
                    'Vendedor': st.column_config.TextColumn('Vendedor', width='medium'),
                    'Vendas Realizadas': st.column_config.NumberColumn('Vendido', format='%d'),
                    'Projeção': st.column_config.NumberColumn('Projeção', format='%d'),
                    'Meta': st.column_config.NumberColumn('Meta', format='%d'),
                    '% da Meta': st.column_config.NumberColumn('% Meta', format='%.1f%%'),
                    'Média Diária': st.column_config.NumberColumn('Média/dia', format='%.2f'),
                    'Dias Úteis Período': st.column_config.NumberColumn('Dias Úteis', format='%d'),
                    'Status': st.column_config.TextColumn('Status', width='small')
                }
            )
            
            # ========== GRÁFICO DE BARRAS COMPARATIVO ==========
            st.markdown("---")
            st.markdown("### 📊 Comparativo de Vendas")
            
            fig_compare = go.Figure()
            
            fig_compare.add_trace(go.Bar(
                x=df_ranking['Vendedor'],
                y=df_ranking['Vendas Realizadas'],
                name='Vendas Realizadas',
                marker_color='#3498db',
                text=df_ranking['Vendas Realizadas'],
                textposition='outside'
            ))
            
            fig_compare.add_trace(go.Bar(
                x=df_ranking['Vendedor'],
                y=df_ranking['Projeção'],
                name='Projeção',
                marker_color='#e67e22',
                text=df_ranking['Projeção'],
                textposition='outside'
            ))
            
            fig_compare.add_trace(go.Bar(
                x=df_ranking['Vendedor'],
                y=df_ranking['Meta'],
                name='Meta',
                marker_color='#2ecc71',
                text=df_ranking['Meta'],
                textposition='outside',
                opacity=0.7
            ))
            
            fig_compare.update_layout(
                title='📊 Comparativo: Realizado vs Projeção vs Meta',
                xaxis_title='Vendedor',
                yaxis_title='Vendas',
                height=400,
                barmode='group',
                legend=dict(
                    orientation='h',
                    yanchor='bottom',
                    y=1.02,
                    xanchor='right',
                    x=1
                )
            )
            st.plotly_chart(fig_compare, use_container_width=True, config={'displayModeBar': False})
            
            # ========== GRÁFICO DE BARRAS: % DA META ==========
            st.markdown("### 🎯 Percentual de Alcance da Meta")
            
            df_percentual = df_ranking.sort_values('% da Meta', ascending=True)
            
            colors = ['#FF6B6B' if x < 50 else '#FFA500' if x < 80 else '#FFD700' if x < 100 else '#90EE90' for x in df_percentual['% da Meta']]
            
            fig_percent = go.Figure()
            
            fig_percent.add_trace(go.Bar(
                x=df_percentual['% da Meta'],
                y=df_percentual['Vendedor'],
                orientation='h',
                marker_color=colors,
                text=[f"{x:.1f}%" for x in df_percentual['% da Meta']],
                textposition='outside'
            ))
            
            fig_percent.add_vline(
                x=100, 
                line_dash="dash", 
                line_color="green",
                annotation_text="Meta 100%",
                annotation_position="top"
            )
            
            fig_percent.update_layout(
                title='🎯 Percentual da Meta Alcançado',
                xaxis_title='% da Meta',
                yaxis_title='Vendedor',
                height=350,
                xaxis=dict(range=[0, max(df_percentual['% da Meta'].max() + 20, 120)])
            )
            st.plotly_chart(fig_percent, use_container_width=True, config={'displayModeBar': False})
            
            # ========== TABELA DE DETALHES ==========
            st.markdown("---")
            st.markdown("### 📋 Detalhamento Mensal")
            
            pivot_detalhe = vendas_mensais.pivot_table(
                index='vendedor',
                columns='mes_str',
                values='vendas_ajustadas',
                fill_value=0
            )
            
            ordem_colunas = vendas_mensais.groupby('mes_str')['ano_mes_num'].first().sort_values().index.tolist()
            pivot_detalhe = pivot_detalhe.reindex(ordem_colunas, axis=1)
            
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
            
            if mes_parcial_nome:
                st.caption(f"⭐ **{mes_parcial_nome}** é o mês parcial com valores **projetados** para o mês completo")
        
        with st.expander("📋 Ver Dados Completos"):
            colunas_display = ['vendedor', 'mes_str', 'total_vendas', 'dias_uteis_periodo', 'dias_uteis_mes', 'media_diaria', 'media_diaria_final', 'projecao_mes', 'vendas_ajustadas', 'variacao_mensal', 'is_mes_parcial']
            colunas_existentes = [c for c in colunas_display if c in vendas_mensais.columns]
            
            df_display = vendas_mensais[colunas_existentes].copy()
            df_display = df_display.rename(columns={
                'vendedor': 'Vendedor',
                'mes_str': 'Mês',
                'total_vendas': 'Vendas Reais',
                'dias_uteis_periodo': 'Dias Úteis Período',
                'dias_uteis_mes': 'Dias Úteis Mês',
                'media_diaria': 'Média Diária (Período)',
                'media_diaria_final': 'Média Diária (Conservadora)',
                'projecao_mes': 'Projeção Mês',
                'vendas_ajustadas': 'Vendas Ajustadas',
                'variacao_mensal': 'Variação %',
                'is_mes_parcial': 'Mês Parcial'
            })
            
            df_display['Mês Parcial'] = df_display['Mês Parcial'].apply(lambda x: '⭐ Sim' if x else '')
            
            st.dataframe(
                df_display,
                use_container_width=True,
                column_config={
                    'Vendedor': 'Vendedor',
                    'Mês': 'Mês',
                    'Vendas Reais': st.column_config.NumberColumn('Vendas Reais', format='%d'),
                    'Dias Úteis Período': st.column_config.NumberColumn('Dias Úteis Período', format='%d'),
                    'Dias Úteis Mês': st.column_config.NumberColumn('Dias Úteis Mês', format='%d'),
                    'Média Diária (Período)': st.column_config.NumberColumn('Média Diária (Período)', format='%.2f'),
                    'Média Diária (Conservadora)': st.column_config.NumberColumn('Média Diária (Conservadora)', format='%.2f'),
                    'Projeção Mês': st.column_config.NumberColumn('Projeção Mês', format='%.1f'),
                    'Vendas Ajustadas': st.column_config.NumberColumn('Vendas Ajustadas', format='%.1f'),
                    'Variação %': st.column_config.NumberColumn('Variação %', format='%.1f%%'),
                    'Mês Parcial': 'Mês Parcial'
                }
            )
    
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
                        df_filtrado.to_excel(writer, sheet_name='Dados Filtrados', index=False)
                        
                        if exportar_vendas_vendedor:
                            vendas_vendedor = calcular_vendas_vendedor_cached(df_hash, data_inicio_str, data_fim_str)
                            if not vendas_vendedor.empty:
                                vendas_vendedor.to_excel(writer, sheet_name='Vendas por Vendedor', index=False)
                        
                        if exportar_evolucao:
                            vendas_semanais, _ = calcular_vendas_semanais_cached(df_hash, data_inicio_str, data_fim_str)
                            if not vendas_semanais.empty:
                                evolucao_df = calcular_indicador_evolucao(vendas_semanais)
                                if not evolucao_df.empty:
                                    evolucao_df.reset_index().to_excel(writer, sheet_name='Evolução Vendedores', index=False)
                        
                        if exportar_semanal:
                            vendas_semanais, vendas_diarias = calcular_vendas_semanais_cached(df_hash, data_inicio_str, data_fim_str)
                            if not vendas_semanais.empty:
                                vendas_semanais.to_excel(writer, sheet_name='Vendas Semanais', index=False)
                            if not vendas_diarias.empty:
                                vendas_diarias.to_excel(writer, sheet_name='Vendas Diárias', index=False)
                        
                        if exportar_mensal:
                            todos_vendedores = df['vendedor'].unique().tolist()
                            vendas_mensais = calcular_vendas_mensais_cached(df_hash, data_inicio_str, data_fim_str, todos_vendedores)
                            if not vendas_mensais.empty:
                                vendas_mensais.to_excel(writer, sheet_name='Evolução Mensal', index=False)
                        
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
