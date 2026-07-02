# modules/vendas_vendedor_condominios.py
"""
Módulo de Vendas por Vendedor - CRM Condomínios RJ
Versão completa com:
- Upload de planilha com colunas específicas
- Limpeza automática do MongoDB antes de cada importação
- Análise mensal e semanal
- Indicador de evolução/piora semana a semana
- Desempenho por condomínio (integrado com módulo condominios.py)
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
import re
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
    }
}

# ==================== CONEXÃO MONGODB ====================
@st.cache_resource
def init_mongo():
    """Inicializa conexão MongoDB"""
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
        
        client = MongoClient(uri, serverSelectionTimeoutMS=5000)
        client.admin.command('ping')
        
        database_name = st.secrets.get("mongo", {}).get("MONGO_DATABASE", "crm_db")
        db = client[database_name]
        
        db[CONFIG['colecao_mongo']].create_index([("import_batch", -1)])
        
        return db
    except Exception as e:
        st.error(f"❌ Falha ao conectar ao MongoDB: {str(e)}")
        return None

def get_condominios_collection():
    """Retorna coleção de condomínios do MongoDB (CRM)"""
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
    
    return MongoClient(uri).crm_db.condominios

# ==================== FUNÇÕES DE BANCO ====================
def limpar_dados_antigos(db):
    """Remove todos os dados antigos da coleção antes de nova importação"""
    try:
        colecao = db[CONFIG['colecao_mongo']]
        resultado = colecao.delete_many({})
        if resultado.deleted_count > 0:
            st.info(f"🧹 {resultado.deleted_count} registros antigos removidos do MongoDB")
        return True
    except Exception as e:
        st.error(f"❌ Erro ao limpar dados antigos: {str(e)}")
        return False

def salvar_dados_mongo(db, df):
    """Salva os dados no MongoDB"""
    try:
        colecao = db[CONFIG['colecao_mongo']]
        
        limpar_dados_antigos(db)
        
        df_clean = df.replace({np.nan: None})
        
        batch_id = f"import_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        records = df_clean.to_dict('records')
        for record in records:
            record['import_batch'] = batch_id
            record['imported_at'] = datetime.now()
        
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
        
        latest = colecao.find_one(sort=[("import_batch", -1)])
        if not latest:
            return None
        
        batch_id = latest.get('import_batch')
        
        cursor = colecao.find({"import_batch": batch_id})
        df = pd.DataFrame(list(cursor))
        
        if df.empty:
            return None
        
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
        
        colunas_faltantes = [col for col in CONFIG['colunas_obrigatorias'] if col not in df.columns]
        if colunas_faltantes:
            st.error(f"❌ Colunas obrigatórias não encontradas: {colunas_faltantes}")
            st.warning(f"🔍 Colunas disponíveis: {list(df.columns)}")
            return None
        
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
        
        return df
    except Exception as e:
        st.error(f"❌ Erro ao processar planilha: {str(e)}")
        return None

def calcular_vendas_por_vendedor(df, data_inicio, data_fim):
    """Calcula vendas por vendedor no período"""
    df_filtrado = df[(df['data_ativacao'] >= pd.Timestamp(data_inicio)) & 
                     (df['data_ativacao'] <= pd.Timestamp(data_fim))]
    
    if df_filtrado.empty:
        return pd.DataFrame()
    
    vendas_vendedor = df_filtrado.groupby('vendedor').agg(
        total_vendas=('cliente', 'count'),
        clientes=('cliente', lambda x: list(x))
    ).reset_index().sort_values('total_vendas', ascending=False)
    
    return vendas_vendedor

def calcular_vendas_semanais(df, data_inicio, data_fim):
    """Calcula vendas semanais por vendedor"""
    df_filtrado = df[(df['data_ativacao'] >= pd.Timestamp(data_inicio)) & 
                     (df['data_ativacao'] <= pd.Timestamp(data_fim))]
    
    if df_filtrado.empty:
        return pd.DataFrame(), pd.DataFrame()
    
    df_filtrado['semana'] = df_filtrado['data_ativacao'].dt.isocalendar().week
    df_filtrado['semana_str'] = df_filtrado['data_ativacao'].dt.strftime('Semana %W')
    
    vendas_semanais = df_filtrado.groupby(['vendedor', 'semana_str', 'semana']).agg(
        total_vendas=('cliente', 'count')
    ).reset_index().sort_values(['vendedor', 'semana'])
    
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
    
    pivot = vendas_semanais.pivot_table(
        index='vendedor',
        columns='semana_str',
        values='total_vendas',
        fill_value=0
    )
    
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

# ==================== FUNÇÃO: DESEMPENHO POR CONDOMÍNIO ====================

def carregar_condominios_crm():
    """Carrega todos os condomínios cadastrados no CRM"""
    try:
        collection = get_condominios_collection()
        condominios = list(collection.find({}, {
            "_id": 1, "nome": 1, "id_ixc": 1, "cidade": 1, 
            "zona": 1, "bairro": 1, "endereco": 1
        }))
        
        df_cond = pd.DataFrame(condominios)
        if not df_cond.empty:
            df_cond['id_ixc'] = pd.to_numeric(df_cond['id_ixc'], errors='coerce').fillna(0).astype(int)
            df_cond['_id'] = df_cond['_id'].astype(str)
        return df_cond
    except Exception as e:
        st.error(f"❌ Erro ao carregar condomínios do CRM: {str(e)}")
        return pd.DataFrame()

def render_desempenho_por_condominio(df, data_inicio, data_fim):
    """Renderiza análise de desempenho por condomínio"""
    st.subheader("🏢 Desempenho por Condomínio")
    
    st.markdown("""
    <div style="background-color:#e8f4f8; padding:15px; border-radius:10px; margin-bottom:20px;">
    <strong>🎯 Como funciona:</strong><br>
    Esta análise integra os dados de vendas com os condomínios cadastrados no CRM.
    <ul>
        <li>🔍 <strong>Compara</strong> o ID da coluna <code>CONDOMANIO</code> da planilha com os IDs cadastrados</li>
        <li>🏆 <strong>Ranking</strong> dos melhores vendedores por condomínio</li>
        <li>📊 <strong>Métricas</strong> de penetração e desempenho por região</li>
    </ul>
    </div>
    """, unsafe_allow_html=True)
    
    with st.spinner("🔄 Carregando condomínios cadastrados..."):
        df_cond_crm = carregar_condominios_crm()
    
    if df_cond_crm.empty:
        st.warning("⚠️ Nenhum condomínio cadastrado no CRM. Acesse o módulo 'Condomínios' para cadastrar.")
        st.info("💡 Dica: Use a aba 'Importar do IXC' para importar automaticamente os condomínios.")
        return
    
    st.success(f"✅ {len(df_cond_crm)} condomínios cadastrados no CRM")
    
    df_vendas = df.copy()
    
    if 'condominio_id' not in df_vendas.columns:
        st.error("❌ Coluna 'condominio_id' não encontrada na planilha.")
        return
    
    df_vendas['condominio_id'] = pd.to_numeric(df_vendas['condominio_id'], errors='coerce').fillna(0).astype(int)
    
    df_vendas_periodo = df_vendas[
        (df_vendas['data_ativacao'] >= pd.Timestamp(data_inicio)) & 
        (df_vendas['data_ativacao'] <= pd.Timestamp(data_fim))
    ].copy()
    
    if df_vendas_periodo.empty:
        st.warning("⚠️ Nenhuma venda encontrada no período selecionado.")
        return
    
    df_planilha_cond = df_vendas_periodo.groupby('condominio_id').agg(
        total_vendas=('cliente', 'count'),
        vendedores=('vendedor', lambda x: list(set(x))),
        clientes=('cliente', lambda x: list(x))
    ).reset_index()
    
    df_merged = df_planilha_cond.merge(
        df_cond_crm,
        left_on='condominio_id',
        right_on='id_ixc',
        how='left'
    )
    
    df_merged['nome_condominio'] = df_merged['nome'].fillna(f"ID {df_merged['condominio_id']} (não cadastrado)")
    df_merged['status_cadastro'] = df_merged['nome'].apply(lambda x: '✅ Cadastrado' if pd.notna(x) else '⚠️ Não Cadastrado')
    
    total_cond_com_vendas = len(df_merged[df_merged['total_vendas'] > 0])
    total_cond_sem_vendas = len(df_merged[df_merged['total_vendas'] == 0])
    total_vendas_cond = df_merged['total_vendas'].sum()
    
    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.metric("🏢 Condomínios com Vendas", total_cond_com_vendas)
    with col2:
        st.metric("📊 Total de Vendas", f"{total_vendas_cond:,}")
    with col3:
        st.metric("📌 Condomínios sem Vendas", total_cond_sem_vendas, delta="⚠️ Oportunidade" if total_cond_sem_vendas > 0 else None)
    with col4:
        media_vendas_cond = total_vendas_cond / total_cond_com_vendas if total_cond_com_vendas > 0 else 0
        st.metric("📈 Média por Condomínio", f"{media_vendas_cond:.1f}")
    
    st.markdown("---")
    
    col_f1, col_f2 = st.columns(2)
    with col_f1:
        zonas_disponiveis = ["Todas"] + sorted(df_merged['zona'].dropna().unique().tolist())
        zona_selecionada = st.selectbox("📍 Filtrar por Zona:", zonas_disponiveis, key="cond_zona_filter")
    
    with col_f2:
        status_opcoes = ["Todos", "✅ Cadastrados no CRM", "⚠️ Não Cadastrados"]
        status_selecionado = st.selectbox("📋 Status:", status_opcoes, key="cond_status_filter")
    
    df_filtrado = df_merged.copy()
    
    if zona_selecionada != "Todas":
        df_filtrado = df_filtrado[df_filtrado['zona'] == zona_selecionada]
    
    if status_selecionado == "✅ Cadastrados no CRM":
        df_filtrado = df_filtrado[df_filtrado['nome'].notna()]
    elif status_selecionado == "⚠️ Não Cadastrados":
        df_filtrado = df_filtrado[df_filtrado['nome'].isna()]
    
    if df_filtrado.empty:
        st.warning("⚠️ Nenhum condomínio encontrado com os filtros selecionados.")
        return
    
    tab1, tab2, tab3 = st.tabs(["🏆 Ranking por Condomínio", "👤 Melhores Vendedores", "📊 Análise por Região"])
    
    with tab1:
        st.subheader("🏆 Ranking de Condomínios por Vendas")
        
        df_ranking = df_filtrado.sort_values('total_vendas', ascending=False).reset_index(drop=True)
        
        st.markdown("### 🥇 Top 10 Condomínios")
        
        top_10 = df_ranking.head(10)
        
        col_rank1, col_rank2 = st.columns([3, 2])
        
        with col_rank1:
            fig_rank = px.bar(
                top_10,
                x='total_vendas',
                y='nome_condominio',
                color='total_vendas',
                color_continuous_scale='Viridis',
                title='🏆 Top 10 Condomínios por Vendas',
                labels={'total_vendas': 'Total de Vendas', 'nome_condominio': 'Condomínio'},
                orientation='h',
                text='total_vendas'
            )
            fig_rank.update_traces(textposition='outside')
            fig_rank.update_layout(height=400, xaxis_title="Vendas", yaxis_title="")
            st.plotly_chart(fig_rank, use_container_width=True, config={'displayModeBar': False})
        
        with col_rank2:
            st.markdown("### 🏅 Pódio")
            
            if len(top_10) >= 1:
                st.success(f"🥇 **{top_10.iloc[0]['nome_condominio']}**\n\n{top_10.iloc[0]['total_vendas']} vendas")
            
            if len(top_10) >= 2:
                st.info(f"🥈 **{top_10.iloc[1]['nome_condominio']}**\n\n{top_10.iloc[1]['total_vendas']} vendas")
            
            if len(top_10) >= 3:
                st.warning(f"🥉 **{top_10.iloc[2]['nome_condominio']}**\n\n{top_10.iloc[2]['total_vendas']} vendas")
        
        st.markdown("---")
        
        st.markdown("### 📋 Lista Completa")
        
        colunas_exibir = [
            'nome_condominio', 'total_vendas', 'zona', 'cidade', 'bairro', 
            'id_ixc', 'status_cadastro'
        ]
        colunas_existentes = [c for c in colunas_exibir if c in df_ranking.columns]
        
        if 'total_vendas' in df_ranking.columns and total_vendas_cond > 0:
            df_ranking['percentual'] = (df_ranking['total_vendas'] / total_vendas_cond * 100).round(1)
            df_ranking['percentual_str'] = df_ranking['percentual'].apply(lambda x: f"{x:.1f}%")
            if 'percentual_str' not in colunas_existentes:
                colunas_existentes.append('percentual_str')
        
        st.dataframe(
            df_ranking[colunas_existentes],
            use_container_width=True,
            height=400,
            column_config={
                'nome_condominio': 'Condomínio',
                'total_vendas': st.column_config.NumberColumn('Vendas', format='%d'),
                'zona': 'Zona',
                'cidade': 'Cidade',
                'bairro': 'Bairro',
                'id_ixc': 'ID IXC',
                'status_cadastro': 'Status',
                'percentual_str': 'Percentual'
            }
        )
    
    with tab2:
        st.subheader("👤 Melhores Vendedores por Condomínio")
        
        df_exploded = df_vendas_periodo[['condominio_id', 'vendedor', 'cliente']].copy()
        df_exploded = df_exploded.merge(
            df_cond_crm[['id_ixc', 'nome']],
            left_on='condominio_id',
            right_on='id_ixc',
            how='left'
        )
        df_exploded['nome_condominio'] = df_exploded['nome'].fillna(f"ID {df_exploded['condominio_id']} (não cadastrado)")
        
        df_vendedores_cond = df_exploded.groupby(['nome_condominio', 'vendedor']).agg(
            total_vendas=('cliente', 'count')
        ).reset_index().sort_values(['nome_condominio', 'total_vendas'], ascending=[True, False])
        
        if df_vendedores_cond.empty:
            st.info("ℹ️ Nenhum dado disponível para análise de vendedores por condomínio.")
        else:
            condominios_lista = sorted(df_vendedores_cond['nome_condominio'].unique())
            
            col_sel1, col_sel2 = st.columns([2, 1])
            
            with col_sel1:
                cond_selecionado = st.selectbox(
                    "Selecione um condomínio para ver os vendedores:",
                    condominios_lista,
                    key="cond_vendedor_select"
                )
            
            with col_sel2:
                top_n = st.number_input(
                    "Mostrar top N vendedores:",
                    min_value=1,
                    max_value=20,
                    value=5,
                    step=1,
                    key="top_n_vendedores"
                )
            
            if cond_selecionado:
                df_cond_vendedores = df_vendedores_cond[df_vendedores_cond['nome_condominio'] == cond_selecionado]
                df_cond_vendedores = df_cond_vendedores.head(top_n)
                
                if not df_cond_vendedores.empty:
                    total_vendas_cond_sel = df_cond_vendedores['total_vendas'].sum()
                    
                    st.markdown(f"### 📊 Vendedores - {cond_selecionado}")
                    st.metric("Total de Vendas no Condomínio", f"{total_vendas_cond_sel}")
                    
                    fig_vendedores = px.bar(
                        df_cond_vendedores,
                        x='vendedor',
                        y='total_vendas',
                        color='total_vendas',
                        color_continuous_scale='Blues',
                        title=f'🏆 Top {top_n} Vendedores - {cond_selecionado}',
                        text='total_vendas'
                    )
                    fig_vendedores.update_traces(textposition='outside')
                    fig_vendedores.update_layout(height=350)
                    st.plotly_chart(fig_vendedores, use_container_width=True, config={'displayModeBar': False})
                    
                    st.dataframe(
                        df_cond_vendedores,
                        use_container_width=True,
                        column_config={
                            'nome_condominio': 'Condomínio',
                            'vendedor': 'Vendedor',
                            'total_vendas': st.column_config.NumberColumn('Vendas', format='%d')
                        }
                    )
            
            st.markdown("---")
            st.markdown("### 🏆 Melhor Vendedor por Condomínio")
            
            df_top_vendedor = df_vendedores_cond.groupby('nome_condominio').first().reset_index()
            df_top_vendedor = df_top_vendedor.sort_values('total_vendas', ascending=False)
            
            st.dataframe(
                df_top_vendedor,
                use_container_width=True,
                height=300,
                column_config={
                    'nome_condominio': 'Condomínio',
                    'vendedor': 'Melhor Vendedor',
                    'total_vendas': st.column_config.NumberColumn('Vendas', format='%d')
                }
            )
            
            fig_top_vendedor = px.bar(
                df_top_vendedor.head(15),
                x='total_vendas',
                y='nome_condominio',
                color='vendedor',
                title='🏆 Melhor Vendedor por Condomínio (Top 15)',
                labels={'total_vendas': 'Vendas', 'nome_condominio': 'Condomínio'},
                orientation='h',
                text='total_vendas'
            )
            fig_top_vendedor.update_traces(textposition='outside')
            fig_top_vendedor.update_layout(height=400, showlegend=False)
            st.plotly_chart(fig_top_vendedor, use_container_width=True, config={'displayModeBar': False})
    
    with tab3:
        st.subheader("📊 Análise por Região/Zona")
        
        df_zona = df_filtrado.groupby('zona').agg(
            total_condominios=('nome_condominio', 'count'),
            total_vendas=('total_vendas', 'sum'),
            media_vendas=('total_vendas', 'mean')
        ).reset_index()
        
        df_zona = df_zona[df_zona['zona'].notna()]
        
        if df_zona.empty:
            st.info("ℹ️ Nenhum dado de zona disponível.")
        else:
            col_z1, col_z2 = st.columns(2)
            
            with col_z1:
                fig_zona = px.bar(
                    df_zona,
                    x='zona',
                    y='total_vendas',
                    color='total_vendas',
                    color_continuous_scale='Viridis',
                    title='📊 Vendas por Zona',
                    text='total_vendas'
                )
                fig_zona.update_traces(textposition='outside')
                fig_zona.update_layout(height=350)
                st.plotly_chart(fig_zona, use_container_width=True, config={'displayModeBar': False})
            
            with col_z2:
                fig_media = px.bar(
                    df_zona,
                    x='zona',
                    y='media_vendas',
                    color='media_vendas',
                    color_continuous_scale='Oranges',
                    title='📈 Média de Vendas por Zona',
                    text='media_vendas'
                )
                fig_media.update_traces(texttemplate='%{text:.1f}', textposition='outside')
                fig_media.update_layout(height=350)
                st.plotly_chart(fig_media, use_container_width=True, config={'displayModeBar': False})
            
            st.dataframe(
                df_zona,
                use_container_width=True,
                column_config={
                    'zona': 'Zona',
                    'total_condominios': st.column_config.NumberColumn('Condomínios', format='%d'),
                    'total_vendas': st.column_config.NumberColumn('Total Vendas', format='%d'),
                    'media_vendas': st.column_config.NumberColumn('Média por Condomínio', format='%.1f')
                }
            )
    
    st.markdown("---")
    st.subheader("📤 Exportar Dados de Desempenho por Condomínio")
    
    if st.button("📥 Exportar Desempenho por Condomínio (Excel)", type="primary", key="export_desempenho_cond"):
        try:
            output = BytesIO()
            with pd.ExcelWriter(output, engine='openpyxl') as writer:
                df_ranking.to_excel(writer, sheet_name='Ranking Condomínios', index=False)
                if 'df_vendedores_cond' in locals() and not df_vendedores_cond.empty:
                    df_vendedores_cond.to_excel(writer, sheet_name='Vendedores por Condomínio', index=False)
                if 'df_zona' in locals() and not df_zona.empty:
                    df_zona.to_excel(writer, sheet_name='Análise por Zona', index=False)
                if 'df_top_vendedor' in locals() and not df_top_vendedor.empty:
                    df_top_vendedor.to_excel(writer, sheet_name='Melhores Vendedores', index=False)
            
            output.seek(0)
            
            st.download_button(
                label="⬇️ Baixar Excel",
                data=output,
                file_name=f"desempenho_condominios_{data_inicio.strftime('%Y%m%d')}_a_{data_fim.strftime('%Y%m%d')}.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                use_container_width=True
            )
            st.success("✅ Arquivo gerado com sucesso!")
        except Exception as e:
            st.error(f"❌ Erro ao gerar arquivo: {str(e)}")

# ==================== FUNÇÕES DE UI ====================
def gerar_opcoes_periodo(df):
    """Gera opções de período baseado nos dados disponíveis"""
    if df is None or df.empty:
        return {}
    
    min_date = df['data_ativacao'].min().date()
    max_date = df['data_ativacao'].max().date()
    
    periodo_opcoes = {}
    
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

# ==================== DASHBOARD ====================
def render_dashboard():
    """Renderiza o dashboard completo"""
    st.title("📊 Vendas por Vendedor - Condomínios RJ")
    
    db = init_mongo()
    if db is None:
        st.stop()
    
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
    
    df_filtrado = df[
        (df['data_ativacao'] >= pd.Timestamp(data_inicio)) & 
        (df['data_ativacao'] <= pd.Timestamp(data_fim))
    ].copy()
    
    if df_filtrado.empty:
        st.warning("⚠️ Nenhum dado encontrado para o período selecionado.")
        return
    
    vendedores = ["Todos"] + sorted(df_filtrado['vendedor'].unique().tolist())
    vendedor_selecionado = st.sidebar.selectbox(
        "👤 Vendedor",
        vendedores,
        key="vendedor_filter"
    )
    
    if vendedor_selecionado != "Todos":
        df_filtrado = df_filtrado[df_filtrado['vendedor'] == vendedor_selecionado]
    
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
    
    vendas_vendedor = calcular_vendas_por_vendedor(df, data_inicio, data_fim)
    
    tab1, tab2, tab3, tab4 = st.tabs([
        "📊 Vendas por Vendedor",
        "📈 Evolução Semanal",
        "🏢 Desempenho por Condomínio",
        "📤 Exportar"
    ])
    
    with tab1:
        st.subheader("👥 Vendas por Vendedor")
        
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
            
            st.markdown("---")
            st.markdown("### 📊 Vendas Semanais por Vendedor")
            
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
    
    with tab3:
        render_desempenho_por_condominio(df, data_inicio, data_fim)
    
    with tab4:
        st.subheader("📤 Exportar Dados")
        
        exportar_vendas_vendedor = st.checkbox("📊 Dados de Vendas por Vendedor", value=True)
        exportar_evolucao = st.checkbox("📈 Indicador de Evolução", value=True)
        exportar_semanal = st.checkbox("📅 Dados Semanais", value=True)
        exportar_condominios = st.checkbox("🏢 Desempenho por Condomínio", value=True)
        
        if st.button("📥 Gerar Excel para Download", type="primary"):
            try:
                output = BytesIO()
                with pd.ExcelWriter(output, engine='openpyxl') as writer:
                    if exportar_vendas_vendedor and not vendas_vendedor.empty:
                        vendas_vendedor.to_excel(writer, sheet_name='Vendas por Vendedor', index=False)
                    
                    if exportar_evolucao and 'evolucao_df' in locals() and not evolucao_df.empty:
                        evolucao_df.reset_index().to_excel(writer, sheet_name='Evolução Vendedores', index=False)
                    
                    if exportar_semanal and not vendas_semanais.empty:
                        vendas_semanais.to_excel(writer, sheet_name='Vendas Semanais', index=False)
                        if not vendas_diarias.empty:
                            vendas_diarias.to_excel(writer, sheet_name='Vendas Diárias', index=False)
                    
                    if exportar_condominios:
                        df_cond_crm = carregar_condominios_crm()
                        if not df_cond_crm.empty:
                            df_cond_crm.to_excel(writer, sheet_name='Condomínios CRM', index=False)
                    
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
    perfil = st.session_state.get('perfil', '')
    if perfil not in ['admin', 'diretoria']:
        st.error("🚫 Acesso negado. Este módulo é restrito a admin e diretoria.")
        return
    
    render_dashboard()

if __name__ == "__main__":
    render_vendas_vendedor_condominios()
