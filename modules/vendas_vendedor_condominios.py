# modules/vendas_vendedor_condominios.py
"""
Módulo de Vendas por Vendedor - CRM Condomínios RJ
Versão adaptada com:
- Upload de planilha com colunas específicas
- Limpeza automática do MongoDB antes de cada importação
- Análise mensal e semanal
- Indicador de evolução/piora semana a semana
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
from pymongo import MongoClient
import urllib.parse

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
    }
}

# ==================== CONEXÃO MONGODB ====================
@st.cache_resource
def init_mongo():
    """Inicializa conexão MongoDB"""
    try:
        # Tenta pegar do st.secrets no formato do CRM
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
        
        client = MongoClient(uri, serverSelectionTimeoutMS=5000)
        client.admin.command('ping')
        
        database_name = st.secrets.get("mongo", {}).get("MONGO_DATABASE", "crm_db")
        db = client[database_name]
        
        # Criar índice
        db[CONFIG['colecao_mongo']].create_index([("import_batch", -1)])
        
        return db
    except Exception as e:
        st.error(f"❌ Falha ao conectar ao MongoDB: {str(e)}")
        return None

# ==================== FUNÇÕES DE BANCO ====================
def limpar_dados_antigos(db):
    """Remove todos os dados antigos da coleção antes de nova importação"""
    try:
        colecao = db[CONFIG['colecao_mongo']]
        resultado = colecao.delete_many({})
        st.info(f"🧹 {resultado.deleted_count} registros antigos removidos do MongoDB")
        return True
    except Exception as e:
        st.error(f"❌ Erro ao limpar dados antigos: {str(e)}")
        return False

def salvar_dados_mongo(db, df):
    """Salva os dados no MongoDB"""
    try:
        colecao = db[CONFIG['colecao_mongo']]
        
        # Limpa dados antigos primeiro
        limpar_dados_antigos(db)
        
        # Converte NaN para None
        df_clean = df.replace({np.nan: None})
        
        # Adiciona metadados
        batch_id = f"import_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        records = df_clean.to_dict('records')
        for record in records:
            record['import_batch'] = batch_id
            record['imported_at'] = datetime.now()
        
        # Insere em lotes para evitar problemas
        batch_size = 5000
        for i in range(0, len(records), batch_size):
            colecao.insert_many(records[i:i+batch_size], ordered=False)
        
        st.success(f"💾 {len(records)} registros salvos no MongoDB (batch: {batch_id})")
        return batch_id
    except Exception as e:
        st.error(f"❌ Erro ao salvar dados: {str(e)}")
        return None

def carregar_dados_mongo(db):
    """Carrega os dados mais recentes do MongoDB"""
    try:
        colecao = db[CONFIG['colecao_mongo']]
        
        # Busca o batch mais recente
        latest = colecao.find_one(sort=[("import_batch", -1)])
        if not latest:
            return None
        
        batch_id = latest.get('import_batch')
        
        # Carrega todos os registros do batch
        cursor = colecao.find({"import_batch": batch_id})
        df = pd.DataFrame(list(cursor))
        
        if df.empty:
            return None
        
        # Remove colunas de metadados
        for col in ['_id', 'import_batch', 'imported_at']:
            if col in df.columns:
                df = df.drop(columns=[col])
        
        return df, batch_id
    except Exception as e:
        st.error(f"❌ Erro ao carregar dados: {str(e)}")
        return None

# ==================== FUNÇÕES DE PROCESSAMENTO ====================
def processar_planilha(uploaded_file):
    """Processa a planilha importada"""
    try:
        df = pd.read_excel(uploaded_file, engine='openpyxl')
        
        # Verifica colunas obrigatórias
        colunas_faltantes = [col for col in CONFIG['colunas_obrigatorias'] if col not in df.columns]
        if colunas_faltantes:
            st.error(f"❌ Colunas obrigatórias não encontradas: {colunas_faltantes}")
            st.warning(f"🔍 Colunas disponíveis: {list(df.columns)}")
            return None
        
        # Converte data de ativação
        df['DATA ATIVAAAO'] = pd.to_datetime(df['DATA ATIVAAAO'], format='%d/%m/%Y', errors='coerce')
        df = df.dropna(subset=['DATA ATIVAAAO'])
        
        # Renomeia colunas para facilitar
        df = df.rename(columns={
            'RAZAO SOCIAL/NOME': 'cliente',
            'ID': 'id_cliente',
            'DATA ATIVAAAO': 'data_ativacao',
            'STATUS CONTRATO': 'status',
            'VENDEDOR': 'vendedor',
            'CONDOMANIO': 'condominio_id',
            'DATA DE CADASTRO NO SISTEMA': 'data_cadastro'
        })
        
        # Remove espaços extras
        df['vendedor'] = df['vendedor'].astype(str).str.strip()
        df['status'] = df['status'].astype(str).str.strip()
        
        # Filtra apenas contratos ativos ou inativos (relevantes)
        # df = df[df['status'].isin(['Ativo', 'Inativo'])]
        
        return df
    except Exception as e:
        st.error(f"❌ Erro ao processar planilha: {str(e)}")
        return None

def calcular_vendas_por_vendedor(df, data_inicio, data_fim):
    """Calcula vendas por vendedor no período"""
    df_filtrado = df[(df['data_ativacao'] >= data_inicio) & (df['data_ativacao'] <= data_fim)]
    
    if df_filtrado.empty:
        return pd.DataFrame()
    
    # Vendas por vendedor
    vendas_vendedor = df_filtrado.groupby('vendedor').agg(
        total_vendas=('cliente', 'count'),
        clientes=('cliente', lambda x: list(x))
    ).reset_index().sort_values('total_vendas', ascending=False)
    
    return vendas_vendedor

def calcular_vendas_semanais(df, data_inicio, data_fim):
    """Calcula vendas semanais por vendedor"""
    df_filtrado = df[(df['data_ativacao'] >= data_inicio) & (df['data_ativacao'] <= data_fim)]
    
    if df_filtrado.empty:
        return pd.DataFrame()
    
    # Adiciona coluna de semana
    df_filtrado['semana'] = df_filtrado['data_ativacao'].dt.isocalendar().week
    df_filtrado['semana_str'] = df_filtrado['data_ativacao'].dt.strftime('Semana %W')
    
    # Agrupa por vendedor e semana
    vendas_semanais = df_filtrado.groupby(['vendedor', 'semana_str', 'semana']).agg(
        total_vendas=('cliente', 'count')
    ).reset_index().sort_values(['vendedor', 'semana'])
    
    # Adiciona dia da semana para análise diária
    df_filtrado['dia_semana'] = df_filtrado['data_ativacao'].dt.day_name()
    df_filtrado['data_str'] = df_filtrado['data_ativacao'].dt.strftime('%d/%m')
    
    vendas_diarias = df_filtrado.groupby(['vendedor', 'semana_str', 'data_str', 'dia_semana']).agg(
        total_vendas=('cliente', 'count')
    ).reset_index().sort_values(['vendedor', 'semana_str', 'data_str'])
    
    return vendas_semanais, vendas_diarias

def calcular_indicador_evolucao(vendas_semanais):
    """Calcula indicador de evolução/piora semana a semana"""
    if vendas_semanais.empty:
        return pd.DataFrame()
    
    # Pivot para ter semanas como colunas
    pivot = vendas_semanais.pivot_table(
        index='vendedor',
        columns='semana_str',
        values='total_vendas',
        fill_value=0
    )
    
    # Calcula evolução semana a semana
    evolucao = pivot.copy()
    for i in range(1, len(pivot.columns)):
        col_anterior = pivot.columns[i-1]
        col_atual = pivot.columns[i]
        evolucao[f'{col_atual}_vs_{col_anterior}'] = (
            (pivot[col_atual] - pivot[col_anterior]) / pivot[col_anterior] * 100
        ).replace([np.inf, -np.inf], 0).fillna(0)
    
    # Média de evolução
    cols_evolucao = [col for col in evolucao.columns if '_vs_' in col]
    if cols_evolucao:
        evolucao['media_evolucao'] = evolucao[cols_evolucao].mean(axis=1)
    else:
        evolucao['media_evolucao'] = 0
    
    # Classifica tendência
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

# ==================== FUNÇÕES DE UI ====================
def gerar_opcoes_periodo(df):
    """Gera opções de período baseado nos dados disponíveis"""
    if df is None or df.empty:
        return {}
    
    min_date = df['data_ativacao'].min().date()
    max_date = df['data_ativacao'].max().date()
    
    periodo_opcoes = {}
    
    # Meses disponíveis
    anos_meses = df.groupby(df['data_ativacao'].dt.to_period('M')).size().index
    for periodo in anos_meses:
        nome_mes = CONFIG['meses_pt'][periodo.month]
        data_inicio = datetime(periodo.year, periodo.month, 1).date()
        ultimo_dia = calendar.monthrange(periodo.year, periodo.month)[1]
        data_fim = datetime(periodo.year, periodo.month, ultimo_dia).date()
        periodo_opcoes[f"📅 {nome_mes} de {periodo.year}"] = (data_inicio, data_fim)
    
    periodo_opcoes.update({
        "📅 Últimos 3 Meses": 90,
        "📅 Últimos 6 Meses": 180,
        "📅 Último Ano": 365,
        "📆 Todo o período": None,
        "🎯 Personalizado": "personalizado"
    })
    
    return periodo_opcoes

def get_periodo(periodo_selecionado, periodo_opcoes, min_date, max_date):
    """Retorna data_inicio e data_fim baseado na seleção"""
    if periodo_selecionado == "🎯 Personalizado":
        return "personalizado", None, None
    elif "📅 " in periodo_selecionado and " de " in periodo_selecionado:
        return periodo_opcoes[periodo_selecionado]
    else:
        dias = periodo_opcoes[periodo_selecionado]
        if dias is None:
            return min_date, max_date
        else:
            data_fim = max_date
            data_inicio = max((datetime.combine(data_fim, datetime.min.time()) - timedelta(days=dias)).date(), min_date)
            return data_inicio, data_fim

def formatar_moeda_br(valor):
    """Formata valor para moeda brasileira"""
    try:
        return f"R$ {valor:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    except:
        return f"R$ {valor}"

# ==================== DASHBOARD ====================
def render_dashboard():
    """Renderiza o dashboard completo"""
    st.title("📊 Vendas por Vendedor - Condomínios RJ")
    
    db = init_mongo()
    if db is None:
        st.stop()
    
    # ========== UPLOAD / CARREGAMENTO ==========
    st.markdown("---")
    st.subheader("📤 Importar Dados")
    
    col1, col2 = st.columns([2, 1])
    
    with col1:
        uploaded_file = st.file_uploader(
            "📁 Carregue a planilha de vendas (Excel)",
            type=["xlsx", "xls"],
            key="vendas_uploader"
        )
    
    with col2:
        if uploaded_file is not None:
            if st.button("🚀 Importar e Processar", type="primary", use_container_width=True):
                with st.spinner("🔄 Processando planilha..."):
                    df = processar_planilha(uploaded_file)
                    if df is not None:
                        batch_id = salvar_dados_mongo(db, df)
                        if batch_id:
                            st.session_state.vendas_df = df
                            st.session_state.vendas_batch = batch_id
                            st.success("✅ Dados importados com sucesso!")
                            st.rerun()
    
    # ========== CARREGAR DADOS EXISTENTES ==========
    if 'vendas_df' not in st.session_state:
        with st.spinner("🔄 Carregando dados existentes..."):
            resultado = carregar_dados_mongo(db)
            if resultado:
                df, batch_id = resultado
                st.session_state.vendas_df = df
                st.session_state.vendas_batch = batch_id
                st.info(f"📋 Dados carregados (batch: {batch_id})")
            else:
                st.info("ℹ️ Nenhum dado encontrado. Faça o upload de uma planilha.")
    
    df = st.session_state.get('vendas_df')
    
    if df is None or df.empty:
        st.warning("⚠️ Nenhum dado carregado. Faça o upload de uma planilha.")
        return
    
    # ========== CONFIGURAÇÃO DE PERÍODO ==========
    st.markdown("---")
    st.subheader("📅 Selecione o Período de Análise")
    
    min_date = df['data_ativacao'].min().date()
    max_date = df['data_ativacao'].max().date()
    periodo_opcoes = gerar_opcoes_periodo(df)
    
    col1, col2 = st.columns([2, 1])
    
    with col1:
        periodo_selecionado = st.selectbox(
            "Período:",
            list(periodo_opcoes.keys()),
            key="periodo_select"
        )
    
    # Define período
    if periodo_selecionado == "🎯 Personalizado":
        col_data1, col_data2 = st.columns(2)
        with col_data1:
            data_inicio = st.date_input("Data Início", value=min_date, min_value=min_date, max_value=max_date)
        with col_data2:
            data_fim = st.date_input("Data Fim", value=max_date, min_value=min_date, max_value=max_date)
    else:
        resultado_periodo = get_periodo(periodo_selecionado, periodo_opcoes, min_date, max_date)
        if resultado_periodo == "personalizado":
            data_inicio, data_fim = min_date, max_date
        else:
            data_inicio, data_fim = resultado_periodo
    
    if data_inicio > data_fim:
        st.error("⚠️ Data de início não pode ser maior que data de fim.")
        return
    
    # Filtra dados pelo período
    df_filtrado = df[
        (df['data_ativacao'] >= pd.Timestamp(data_inicio)) & 
        (df['data_ativacao'] <= pd.Timestamp(data_fim))
    ].copy()
    
    if df_filtrado.empty:
        st.warning("⚠️ Nenhum dado encontrado para o período selecionado.")
        return
    
    # ========== FILTRO POR VENDEDOR ==========
    vendedores = ["Todos"] + sorted(df_filtrado['vendedor'].unique().tolist())
    vendedor_selecionado = st.sidebar.selectbox(
        "👤 Vendedor",
        vendedores,
        key="vendedor_filter"
    )
    
    if vendedor_selecionado != "Todos":
        df_filtrado = df_filtrado[df_filtrado['vendedor'] == vendedor_selecionado]
    
    # ========== MÉTRICAS PRINCIPAIS ==========
    total_vendas = len(df_filtrado)
    total_vendedores = df_filtrado['vendedor'].nunique()
    media_vendas = total_vendas / total_vendedores if total_vendedores > 0 else 0
    
    st.markdown("---")
    
    col1, col2, col3, col4 = st.columns(4)
    col1.metric("📊 Total de Vendas", f"{total_vendas:,}")
    col2.metric("👤 Vendedores Ativos", f"{total_vendedores}")
    col3.metric("📈 Média por Vendedor", f"{media_vendas:.1f}")
    col4.metric("📅 Período", f"{data_inicio.strftime('%d/%m/%Y')} a {data_fim.strftime('%d/%m/%Y')}")
    
    st.markdown("---")
    
    # ========== ANÁLISE POR VENDEDOR ==========
    vendas_vendedor = calcular_vendas_por_vendedor(df, data_inicio, data_fim)
    
    tab1, tab2, tab3 = st.tabs(["📊 Vendas por Vendedor", "📈 Evolução Semanal", "📤 Exportar"])
    
    with tab1:
        st.subheader("👥 Vendas por Vendedor")
        
        # Gráfico de barras
        if not vendas_vendedor.empty:
            fig = px.bar(
                vendas_vendedor,
                x='vendedor',
                y='total_vendas',
                title='📊 Total de Vendas por Vendedor',
                color='total_vendas',
                color_continuous_scale='Viridis',
                text='total_vendas'
            )
            fig.update_traces(textposition='outside')
            fig.update_layout(xaxis_title="Vendedor", yaxis_title="Qtd Vendas", height=400)
            st.plotly_chart(fig, use_container_width=True, config={'displayModeBar': False})
            
            # Tabela
            st.dataframe(
                vendas_vendedor,
                use_container_width=True,
                column_config={
                    'vendedor': 'Vendedor',
                    'total_vendas': st.column_config.NumberColumn('Total Vendas', format='%d'),
                    'clientes': 'Clientes'
                }
            )
        else:
            st.info("ℹ️ Nenhum dado disponível para exibir.")
    
    with tab2:
        st.subheader("📈 Evolução Semanal de Vendas")
        
        vendas_semanais, vendas_diarias = calcular_vendas_semanais(df, data_inicio, data_fim)
        
        if not vendas_semanais.empty:
            # ========== INDICADOR DE EVOLUÇÃO ==========
            st.markdown("### 🎯 Indicador de Evolução por Vendedor")
            
            evolucao_df = calcular_indicador_evolucao(vendas_semanais)
            
            if not evolucao_df.empty:
                # Exibe resumo da tendência
                col1, col2, col3, col4 = st.columns(4)
                
                total_vendedores_evol = len(evolucao_df)
                cresc_forte = len(evolucao_df[evolucao_df['tendencia'] == '🚀 Crescimento Forte'])
                cresc_mod = len(evolucao_df[evolucao_df['tendencia'] == '📈 Crescimento Moderado'])
                estavel = len(evolucao_df[evolucao_df['tendencia'] == '➡️ Estável'])
                declinio = len(evolucao_df[evolucao_df['tendencia'].str.contains('Declínio')])
                
                col1.metric("📈 Crescendo", f"{cresc_forte + cresc_mod} vendedores")
                col2.metric("➡️ Estável", f"{estavel} vendedores")
                col3.metric("📉 Declinando", f"{declinio} vendedores")
                col4.metric("📊 Média Evolução", f"{evolucao_df['media_evolucao'].mean():.1f}%")
                
                st.markdown("---")
                
                # Gráfico de evolução
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
                
                # Tabela de evolução
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
            
            # Gráfico de linhas - evolução semanal
            pivot_semanal = vendas_semanais.pivot_table(
                index='semana_str',
                columns='vendedor',
                values='total_vendas',
                fill_value=0
            )
            
            if not pivot_semanal.empty:
                fig_linhas = px.line(
                    pivot_semanal,
                    title='📈 Evolução Semanal de Vendas por Vendedor',
                    labels={'value': 'Vendas', 'semana_str': 'Semana', 'variable': 'Vendedor'},
                    markers=True
                )
                fig_linhas.update_layout(height=450, hovermode='x unified')
                st.plotly_chart(fig_linhas, use_container_width=True, config={'displayModeBar': False})
            
            # ========== ANÁLISE DIÁRIA POR SEMANA ==========
            st.markdown("---")
            st.markdown("### 📅 Vendas Diárias por Semana")
            
            # Seleciona semana para detalhamento
            semanas_disponiveis = sorted(vendas_diarias['semana_str'].unique())
            if semanas_disponiveis:
                semana_selecionada = st.selectbox(
                    "Selecione a semana para detalhamento:",
                    semanas_disponiveis,
                    key="semana_detalhe"
                )
                
                df_semana = vendas_diarias[vendas_diarias['semana_str'] == semana_selecionada]
                
                # Gráfico de barras diário
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
                
                # Tabela diária
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
            
            # ========== TABELA SEMANAL ==========
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
    
    with tab3:
        st.subheader("📤 Exportar Dados")
        
        # Opções de exportação
        exportar_vendas_vendedor = st.checkbox("📊 Dados de Vendas por Vendedor", value=True)
        exportar_evolucao = st.checkbox("📈 Indicador de Evolução", value=True)
        exportar_semanal = st.checkbox("📅 Dados Semanais", value=True)
        
        if st.button("📥 Gerar Excel para Download", type="primary"):
            try:
                output = BytesIO()
                with pd.ExcelWriter(output, engine='openpyxl') as writer:
                    # Vendas por vendedor
                    if exportar_vendas_vendedor and not vendas_vendedor.empty:
                        vendas_vendedor.to_excel(writer, sheet_name='Vendas por Vendedor', index=False)
                    
                    # Indicador de evolução
                    if exportar_evolucao and 'evolucao_df' in locals() and not evolucao_df.empty:
                        evolucao_df.reset_index().to_excel(writer, sheet_name='Evolução Vendedores', index=False)
                    
                    # Dados semanais
                    if exportar_semanal and not vendas_semanais.empty:
                        vendas_semanais.to_excel(writer, sheet_name='Vendas Semanais', index=False)
                        if not vendas_diarias.empty:
                            vendas_diarias.to_excel(writer, sheet_name='Vendas Diárias', index=False)
                    
                    # Dados filtrados
                    df_filtrado.to_excel(writer, sheet_name='Dados Filtrados', index=False)
                
                output.seek(0)
                
                st.download_button(
                    label="⬇️ Baixar Excel",
                    data=output,
                    file_name=f"vendas_vendedor_{data_inicio.strftime('%Y%m%d')}_a_{data_fim.strftime('%Y%m%d')}.xlsx",
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    use_container_width=True
                )
                st.success("✅ Arquivo gerado com sucesso!")
            except Exception as e:
                st.error(f"❌ Erro ao gerar arquivo: {str(e)}")

# ==================== FUNÇÃO PRINCIPAL ====================
def render_vendas_vendedor_condominios():
    """Função principal do módulo"""
    # Verifica permissão
    perfil = st.session_state.get('perfil', '')
    if perfil not in ['admin', 'diretoria']:
        st.error("🚫 Acesso negado. Este módulo é restrito a admin e diretoria.")
        return
    
    render_dashboard()

if __name__ == "__main__":
    render_vendas_vendedor_condominios()
