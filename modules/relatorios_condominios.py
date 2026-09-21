"""
Módulo de Relatórios de Condomínios para a DR Tracecom Suite Analítica.
VERSÃO OTIMIZADA COM ANÁLISE TEMPORAL POR CONDOMÍNIO
- Processamento de 300k+ registros em < 3 segundos
- Análise temporal individual por condomínio selecionado
- Dashboard de impacto de campanhas por condomínio específico
- INTEGRAÇÃO COM MEUS ACOMPANHAMENTOS do módulo de prospecção
- ANÁLISE DE CRESCIMENTO INDIVIDUAL POR CONDOMÍNIO COM FILTRO POR MÚLTIPLAS FASES
- NOVA ABA: ANÁLISE DE CANCELAMENTOS POR CONDOMÍNIO E MÊS
- NOVA ABA: ANÁLISE AVANÇADA DE CANCELAMENTOS (tendência, sazonalidade, coorte)
- MELHORIAS: Total Geral na pivô, Filtro por Região, Top N configurável, Heatmap
- NOVO: Exportação de Clientes para Win-Back com Filtro de Saúde do Cliente (Health Score)
- CORREÇÃO CRÍTICA: Health Score agora aceita "Recebida", "Paga", "Pago", "Recebido"
- OTIMIZAÇÃO: Cache de Health Score, carregamento em batch, prospecção cacheada
"""
import streamlit as st
import pandas as pd
import numpy as np
import plotly.express as px
import plotly.graph_objects as go
from datetime import datetime, timedelta
from pymongo import MongoClient, ASCENDING, DESCENDING
from pymongo.errors import ServerSelectionTimeoutError, ConnectionFailure
from gridfs import GridFS
from bson import ObjectId
from urllib.parse import quote_plus
import io
import traceback
import warnings
import calendar
import hashlib

warnings.filterwarnings('ignore')

# ==================== CONFIGURAÇÃO INICIAL ====================
st.set_page_config(page_title="Relatórios Condomínios", layout="wide", initial_sidebar_state="collapsed")

# ==================== CONFIGURAÇÃO DO MÓDULO ====================
CONDOMINIOS_CONFIG = {
    'colunas_obrigatorias_clientes': [
        'CONDOMANIO', 'STATUS ACESSO'
    ],
    'colunas_obrigatorias_condominios': [
        'ID', 'Condomínio', 'Apartamentos', 'Região'
    ],
    'colunas_obrigatorias_parcelas': [
        'ID', 'DATA DO VENCIMENTO', 'STATUS', 'VALOR'
    ],
    'modo_ativos_opcoes': {
        'somente_ativos': 'Apenas Ativos Puros',
        'todos_ativos': 'Todos os Ocupados (Ativos + Atraso + Bloqueio)'
    },
    'colecoes': {
        'dados_processados': 'condominios_relatorios',
        'metadados': 'condominios_meta',
        'gridfs': 'fs.files'
    },
    'ticket_medio_padrao': 89.99,
    'meses_maturidade_limite': 18,
    'limite_preview_tabela': 500
}

# ==================== CONSTANTES DE STATUS DE PAGAMENTO ====================
# 🔑 CORREÇÃO CRÍTICA: aceitar múltiplos sinônimos de pagamento
STATUS_PAGO_SET = {
    'pago', 'paga', 'pagos', 'pagas',
    'recebida', 'recebido', 'recebidas', 'recebidos',
    'quitado', 'quitada', 'quitados', 'quitadas',
    'liquidado', 'liquidada', 'liquidados', 'liquidadas',
    'baixado', 'baixada'
}
STATUS_IGNORAR_SET = {
    'cancelado', 'cancelada', 'cancelados', 'canceladas',
    'isento', 'isenta', 'isentos', 'isentas',
    'estornado', 'estornada', 'estornados', 'estornadas'
}

# ==================== INICIALIZAÇÃO DO SESSION STATE ====================
def initialize_session_state():
    """Inicializa estado da sessão de forma estruturada"""
    defaults = {
        'condominios_dados_clientes': None,
        'condominios_dados_condominios': None,
        'condominios_dados_parcelas': None,
        'condominios_parcelas_pre_agregadas': None,
        'condominios_processado': False,
        'condominios_file_id': None,
        'condominios_nome_arquivo': None,
        'condominios_meta': None,
        'condominios_filtros': {
            'regiao': None,
            'modo_ativos': 'somente_ativos'
        },
        'condominios_config': CONDOMINIOS_CONFIG,
        'exclusao_confirmada': False,
        'file_id_a_excluir': None,
        'colecao_a_excluir': 'condominios_relatorios',
        'batch_id_a_excluir': None,
        'condominios_colunas_mapeadas': {},
        'recarregar_dados': False,
        'ultimo_cache_hash': None,
        'ultimo_resultado_inadimplencia': None,
        'ultima_analise_temporal': None,
        'temporal_calculado': False,
        'meus_condominios_ids': None,
        'meus_condominios_nomes': None,
        'meu_nome_prospeccao': 'Diego Roberto',
        '_winback_cache': None,
        '_winback_cache_key': None,
    }
    
    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value

# ==================== FUNÇÕES DE UI ====================
def titulo_principal(texto):
    st.markdown(f"<h1 style='font-size: 28px; font-weight: bold; color: #2c3e50;'>{texto}</h1>", unsafe_allow_html=True)

def subtitulo(texto):
    st.markdown(f"<h3 style='color: #34495e;'>{texto}</h3>", unsafe_allow_html=True)


# ==================== FUNÇÕES DE INTEGRAÇÃO - MEUS ACOMPANHAMENTOS ====================

@st.cache_data(ttl=300, show_spinner=False)
def _carregar_prospeccao_cache(batch_id, _hash_key):
    """Cache do DataFrame de prospecção."""
    db = init_mongo()
    cursor = db["prospeccao_condominios"].find(
        {"_import_batch": batch_id},
        {"_id": 0, "NOME": 1, "ACOMPANHAMENTO": 1, "CONSTRUTORA": 1,
         "BAIRRO": 1, "Região": 1, "FASE_CLASSIFICADA": 1}
    ).batch_size(5000)
    return pd.DataFrame(list(cursor))


def carregar_meus_condominios_prospeccao(db):
    """
    Carrega a lista de condomínios da aba 'Meus Acompanhamentos' do módulo de prospecção.
    OTIMIZADO: usa cache para evitar queries repetidas.
    """
    try:
        meta = db["prospeccao_meta"].find_one(sort=[("timestamp", -1)])
        if not meta:
            return None, None
        
        batch_id = meta.get("batch_id")
        
        df_prospeccao = _carregar_prospeccao_cache(batch_id, batch_id)
        
        if df_prospeccao is None or df_prospeccao.empty:
            return None, None
        
        df_com_responsavel = df_prospeccao[
            df_prospeccao["ACOMPANHAMENTO"].notna() & 
            (df_prospeccao["ACOMPANHAMENTO"] != "")
        ].copy()
        
        if df_com_responsavel.empty:
            return None, None
        
        meu_nome = st.session_state.get("meu_nome_prospeccao", "Diego Roberto")
        df_meus = df_com_responsavel[df_com_responsavel["ACOMPANHAMENTO"] == meu_nome].copy()
        
        if df_meus.empty:
            return None, None
        
        meus_nomes = set()
        for nome in df_meus["NOME"].dropna():
            meus_nomes.add(str(nome).strip())
        
        return meus_nomes, df_meus
        
    except Exception as e:
        print(f"Erro ao carregar meus condomínios: {e}")
        return None, None


def filtrar_condominios_meus(df_condominios, meus_nomes):
    """Filtra o DataFrame de condomínios para incluir apenas os que estão na lista de acompanhamento."""
    if df_condominios is None or df_condominios.empty:
        return pd.DataFrame()
    
    if not meus_nomes:
        return pd.DataFrame()
    
    df_condominios_temp = df_condominios.copy()
    df_condominios_temp['nome_normalizado'] = df_condominios_temp['Condomínio'].str.strip().str.upper()
    meus_nomes_normalizados = {nome.strip().upper() for nome in meus_nomes}
    
    df_filtrado = df_condominios_temp[df_condominios_temp['nome_normalizado'].isin(meus_nomes_normalizados)].copy()
    
    if 'nome_normalizado' in df_filtrado.columns:
        df_filtrado = df_filtrado.drop(columns=['nome_normalizado'])
    
    return df_filtrado


def render_seletor_usuario():
    """Renderiza seletor de usuário para integração com Meus Acompanhamentos."""
    st.markdown("### 👤 Configuração de Usuário")
    
    col1, col2 = st.columns([2, 1])
    
    with col1:
        nome_atual = st.session_state.get("meu_nome_prospeccao", "Diego Roberto")
        nome_usuario = st.text_input(
            "Seu nome (como aparece na coluna 'Acompanhamento' da prospecção):",
            value=nome_atual,
            key="meu_nome_prospeccao_input",
            help="Digite exatamente como está na planilha de prospecção"
        )
        
        if nome_usuario != st.session_state.get("meu_nome_prospeccao"):
            st.session_state.meu_nome_prospeccao = nome_usuario
            st.session_state.meus_condominios_ids = None
            st.session_state.meus_condominios_nomes = None
    
    with col2:
        if st.button("🔄 Atualizar Lista de Meus Condomínios", key="btn_atualizar_meus", use_container_width=True):
            st.session_state.meus_condominios_ids = None
            st.session_state.meus_condominios_nomes = None
            st.rerun()
    
    return nome_usuario


# ==================== FUNÇÃO: ANÁLISE DE CANCELAMENTOS POR CONDOMÍNIO ====================

def analisar_cancelamentos_por_condominio(df_clientes, df_condominios, data_inicio, data_fim, regioes_filtro=None):
    """Analisa cancelamentos por condomínio e mês."""
    if df_clientes is None or df_clientes.empty or df_condominios is None or df_condominios.empty:
        return pd.DataFrame(), pd.DataFrame(), pd.DataFrame(), pd.DataFrame()
    
    df_clientes_temp = df_clientes.copy()
    df_condominios_temp = df_condominios.copy()
    
    if 'CONDOMANIO' in df_clientes_temp.columns:
        df_clientes_temp['CONDOMANIO'] = pd.to_numeric(
            df_clientes_temp['CONDOMANIO'], errors='coerce'
        ).fillna(0).astype(int)
    
    if 'ID' in df_condominios_temp.columns:
        df_condominios_temp['ID'] = pd.to_numeric(
            df_condominios_temp['ID'], errors='coerce'
        ).fillna(0).astype(int)
    
    if regioes_filtro and 'Região' in df_condominios_temp.columns:
        df_condominios_temp = df_condominios_temp[
            df_condominios_temp['Região'].isin(regioes_filtro)
        ].copy()
        
        if df_condominios_temp.empty:
            return pd.DataFrame(), pd.DataFrame(), pd.DataFrame(), pd.DataFrame()
    
    data_cancel_col = None
    possiveis_colunas_cancel = [
        'data cancelamento', 'data_cancelamento', 'dt_cancelamento',
        'cancelamento', 'data desativacao', 'data_desativacao',
        'data cancel', 'dt_cancel', 'data de cancelamento',
        'data cancelado', 'cancelado em'
    ]
    
    for col in df_clientes_temp.columns:
        col_lower = col.lower().strip()
        for possivel in possiveis_colunas_cancel:
            if possivel in col_lower:
                data_cancel_col = col
                break
        if data_cancel_col:
            break
    
    if data_cancel_col is None:
        data_cadastro_col = identificar_coluna_data(df_clientes_temp)
        if data_cadastro_col:
            data_cancel_col = data_cadastro_col
        else:
            return pd.DataFrame(), pd.DataFrame(), pd.DataFrame(), pd.DataFrame()
    
    df_clientes_temp[data_cancel_col] = pd.to_datetime(
        df_clientes_temp[data_cancel_col], errors='coerce'
    )
    
    df_clientes_temp['status_classificacao'] = classificar_status_serie(
        df_clientes_temp.get('STATUS ACESSO', pd.Series())
    )
    
    df_cancelados = df_clientes_temp[
        df_clientes_temp['status_classificacao'] == 'Desativado'
    ].copy()
    
    if df_cancelados.empty:
        s = df_clientes_temp['STATUS ACESSO'].fillna('').astype(str).str.lower()
        mascara_cancel = (
            s.str.contains('cancelado|cancelamento|desativado|inativo|encerrado|churn', na=False)
        )
        df_cancelados = df_clientes_temp[mascara_cancel].copy()
    
    if df_cancelados.empty:
        return pd.DataFrame(), pd.DataFrame(), pd.DataFrame(), pd.DataFrame()
    
    df_cancelados = df_cancelados.dropna(subset=[data_cancel_col])
    
    if df_cancelados.empty:
        return pd.DataFrame(), pd.DataFrame(), pd.DataFrame(), pd.DataFrame()
    
    df_cancelados = df_cancelados[
        (df_cancelados[data_cancel_col] >= data_inicio) &
        (df_cancelados[data_cancel_col] <= data_fim)
    ].copy()
    
    if df_cancelados.empty:
        return pd.DataFrame(), pd.DataFrame(), pd.DataFrame(), pd.DataFrame()
    
    df_cancelados['ano_mes'] = df_cancelados[data_cancel_col].dt.to_period('M')
    df_cancelados['mes_num'] = df_cancelados[data_cancel_col].dt.month
    df_cancelados['ano'] = df_cancelados[data_cancel_col].dt.year
    
    meses_pt = {
        1: 'Janeiro', 2: 'Fevereiro', 3: 'Março', 4: 'Abril',
        5: 'Maio', 6: 'Junho', 7: 'Julho', 8: 'Agosto',
        9: 'Setembro', 10: 'Outubro', 11: 'Novembro', 12: 'Dezembro'
    }
    df_cancelados['mes_nome_pt'] = df_cancelados['mes_num'].map(meses_pt)
    
    df_cancelados = df_cancelados.merge(
        df_condominios_temp[['ID', 'Condomínio', 'Região']].drop_duplicates(),
        left_on='CONDOMANIO',
        right_on='ID',
        how='left',
        suffixes=('', '_cond')
    )
    
    df_cancelados['Condomínio'] = df_cancelados['Condomínio'].fillna(
        df_cancelados['CONDOMANIO'].astype(str)
    )
    
    df_cancelados['mes_label'] = df_cancelados.apply(
        lambda row: f"{row['mes_nome_pt']}/{row['ano']}" if pd.notna(row['mes_nome_pt']) else f"Mês {row['mes_num']}",
        axis=1
    )
    
    pivot = df_cancelados.pivot_table(
        index='Condomínio',
        columns='mes_label',
        values='CONDOMANIO',
        aggfunc='count',
        fill_value=0
    )
    
    colunas_ordenadas = []
    for ano in sorted(df_cancelados['ano'].unique()):
        for mes in range(1, 13):
            label = f"{meses_pt[mes]}/{ano}"
            if label in pivot.columns:
                colunas_ordenadas.append(label)
    
    for col in pivot.columns:
        if col not in colunas_ordenadas:
            colunas_ordenadas.append(col)
    
    pivot = pivot[colunas_ordenadas]
    pivot['Total Período'] = pivot.sum(axis=1)
    pivot = pivot.sort_values('Total Período', ascending=False)
    pivot = pivot.reset_index()
    
    colunas_numericas = [c for c in pivot.columns if c != 'Condomínio']
    linha_total = {'Condomínio': '📊 TOTAL GERAL'}
    for col in colunas_numericas:
        linha_total[col] = int(pivot[col].sum())
    
    pivot_com_total = pd.concat(
        [pivot, pd.DataFrame([linha_total])],
        ignore_index=True
    )
    
    df_resumo = df_cancelados.groupby('Condomínio').agg(
        total_cancelamentos=('CONDOMANIO', 'count'),
        regiao=('Região', 'first'),
        media_mensal=('ano_mes', lambda x: x.value_counts().mean())
    ).reset_index().sort_values('total_cancelamentos', ascending=False)
    
    mes_mais_cancel = df_cancelados.groupby(['Condomínio', 'mes_label']).size().reset_index(name='count')
    if not mes_mais_cancel.empty:
        idx_max = mes_mais_cancel.groupby('Condomínio')['count'].idxmax()
        mes_mais_cancel = mes_mais_cancel.loc[idx_max][['Condomínio', 'mes_label', 'count']]
        mes_mais_cancel.columns = ['Condomínio', 'mes_mais_cancelamentos', 'qtd_mes_mais']
        df_resumo = df_resumo.merge(mes_mais_cancel, on='Condomínio', how='left')
    
    df_regiao = pd.DataFrame()
    if 'Região' in df_cancelados.columns:
        df_regiao = df_cancelados.groupby('Região').agg(
            total_cancelamentos=('CONDOMANIO', 'count'),
            total_condominios=('Condomínio', 'nunique')
        ).reset_index().sort_values('total_cancelamentos', ascending=False)
        
        df_regiao['media_por_condominio'] = (
            df_regiao['total_cancelamentos'] / df_regiao['total_condominios']
        ).round(1)
        
        total_geral = df_regiao['total_cancelamentos'].sum()
        df_regiao['percentual'] = (
            df_regiao['total_cancelamentos'] / total_geral * 100
        ).round(1) if total_geral > 0 else 0
    
    return pivot_com_total, df_cancelados, df_resumo, df_regiao


# ==================== FUNÇÃO: RENDERIZAR ABA DE CANCELAMENTOS ====================

def render_aba_cancelamentos(df_clientes, df_condominios):
    """Renderiza a aba de análise de cancelamentos por condomínio."""
    st.subheader("🚫 Análise de Cancelamentos por Condomínio")
    
    st.markdown("""
    <div style="background-color:#fff3cd; padding:15px; border-radius:10px; margin-bottom:20px;">
    <strong>📋 Como funciona:</strong><br>
    Esta análise mostra os <strong>cancelamentos por condomínio e mês</strong>,
    permitindo identificar padrões e sazonalidades.
    </div>
    """, unsafe_allow_html=True)
    
    if df_clientes is None or df_clientes.empty or df_condominios is None or df_condominios.empty:
        st.warning("⚠️ Nenhum dado carregado para análise de cancelamentos.")
        return
    
    data_cancel_col = None
    possiveis_colunas_cancel = [
        'data cancelamento', 'data_cancelamento', 'dt_cancelamento',
        'cancelamento', 'data desativacao', 'data_desativacao',
        'data cancel', 'dt_cancel', 'data de cancelamento',
        'data cancelado', 'cancelado em'
    ]
    
    for col in df_clientes.columns:
        col_lower = col.lower().strip()
        for possivel in possiveis_colunas_cancel:
            if possivel in col_lower:
                data_cancel_col = col
                break
        if data_cancel_col:
            break
    
    if data_cancel_col is None:
        st.warning("""
        ⚠️ **Coluna de data de cancelamento não encontrada!**
        """)
        data_cancel_col = identificar_coluna_data(df_clientes)
        if data_cancel_col is None:
            st.error("❌ Nenhuma coluna de data encontrada. Análise indisponível.")
            return
        st.info(f"📌 Usando a coluna **'{data_cancel_col}'** como referência (proxy).")
    
    st.markdown("### 🎛️ Filtros de Análise")
    
    col_f1, col_f2, col_f3 = st.columns([2, 2, 1])
    
    with col_f1:
        periodo_preset = st.selectbox(
            "📅 Período:",
            options=[
                "Último trimestre",
                "Último semestre",
                "Último ano",
                "Últimos 2 anos",
                "Ano atual",
                "Personalizado",
                "Todos os dados"
            ],
            index=1,
            key="cancelamentos_periodo_preset"
        )
    
    with col_f2:
        regioes_disponiveis = []
        if 'Região' in df_condominios.columns:
            regioes_disponiveis = sorted(df_condominios['Região'].dropna().unique().tolist())
        
        if regioes_disponiveis:
            regioes_selecionadas = st.multiselect(
                "📍 Filtrar por Região:",
                options=regioes_disponiveis,
                default=[],
                key="cancelamentos_regioes",
                help="Deixe vazio para incluir todas as regiões"
            )
        else:
            regioes_selecionadas = []
            st.caption("📍 Região não disponível")
    
    with col_f3:
        st.markdown("<br>", unsafe_allow_html=True)
        if st.button("🔄 Atualizar", key="btn_atualizar_cancelamentos", use_container_width=True):
            st.rerun()
    
    if periodo_preset == "Personalizado":
        col_data1, col_data2 = st.columns(2)
        with col_data1:
            data_inicio_date = st.date_input(
                "Data inicial:",
                value=datetime.now().date() - timedelta(days=180),
                key="cancelamentos_data_inicio"
            )
        with col_data2:
            data_fim_date = st.date_input(
                "Data final:",
                value=datetime.now().date(),
                key="cancelamentos_data_fim"
            )
        data_inicio = datetime.combine(data_inicio_date, datetime.min.time())
        data_fim = datetime.combine(data_fim_date, datetime.max.time())
    else:
        data_fim = datetime.now().replace(tzinfo=None)
        
        if periodo_preset == "Último trimestre":
            data_inicio = data_fim - timedelta(days=90)
        elif periodo_preset == "Último semestre":
            data_inicio = data_fim - timedelta(days=180)
        elif periodo_preset == "Último ano":
            data_inicio = data_fim - timedelta(days=365)
        elif periodo_preset == "Últimos 2 anos":
            data_inicio = data_fim - timedelta(days=730)
        elif periodo_preset == "Ano atual":
            data_inicio = datetime(data_fim.year, 1, 1)
        else:
            df_temp = df_clientes.copy()
            df_temp[data_cancel_col] = pd.to_datetime(df_temp[data_cancel_col], errors='coerce')
            data_inicio = df_temp[data_cancel_col].min()
            if pd.isna(data_inicio):
                data_inicio = datetime(2020, 1, 1)
    
    if isinstance(data_inicio, datetime) and isinstance(data_fim, datetime):
        st.info(f"📅 Período: **{data_inicio.strftime('%d/%m/%Y')}** até **{data_fim.strftime('%d/%m/%Y')}**")
        if regioes_selecionadas:
            st.info(f"📍 Regiões filtradas: **{', '.join(regioes_selecionadas)}**")
    
    with st.spinner("🔄 Analisando cancelamentos..."):
        df_pivot, df_detalhado, df_resumo, df_regiao = analisar_cancelamentos_por_condominio(
            df_clientes, df_condominios, data_inicio, data_fim,
            regioes_filtro=regioes_selecionadas if regioes_selecionadas else None
        )
    
    if df_pivot.empty:
        st.warning("⚠️ Nenhum cancelamento encontrado no período selecionado.")
        st.info("💡 Tente ajustar o período ou verifique se a planilha possui dados de cancelamento.")
        return
    
    total_cancelamentos = df_resumo['total_cancelamentos'].sum()
    total_condominios = len(df_resumo)
    media_por_condominio = total_cancelamentos / total_condominios if total_condominios > 0 else 0
    media_mensal = df_resumo['media_mensal'].mean() if 'media_mensal' in df_resumo.columns else 0
    
    col_m1, col_m2, col_m3, col_m4 = st.columns(4)
    with col_m1:
        st.metric("🚫 Total Cancelamentos", formatar_numero_br(total_cancelamentos))
    with col_m2:
        st.metric("🏢 Condomínios Afetados", formatar_numero_br(total_condominios))
    with col_m3:
        st.metric("📊 Média por Condomínio", f"{media_por_condominio:.1f}")
    with col_m4:
        st.metric("📅 Média Mensal", f"{media_mensal:.1f}")
    
    st.markdown("---")
    
    if not df_regiao.empty:
        st.subheader("📍 Cancelamentos por Região")
        
        col_reg1, col_reg2 = st.columns([1, 1])
        
        with col_reg1:
            fig_reg = px.bar(
                df_regiao,
                x='Região',
                y='total_cancelamentos',
                color='total_cancelamentos',
                color_continuous_scale='Reds',
                title='📊 Total de Cancelamentos por Região',
                text='total_cancelamentos'
            )
            fig_reg.update_traces(texttemplate='%{text}', textposition='outside')
            fig_reg.update_layout(height=400, coloraxis_showscale=False, xaxis_tickangle=-45)
            st.plotly_chart(fig_reg, use_container_width=True, config={'displayModeBar': False})
        
        with col_reg2:
            fig_pie_reg = px.pie(
                df_regiao,
                values='total_cancelamentos',
                names='Região',
                title='🥧 Distribuição Percentual por Região',
                hole=0.4
            )
            fig_pie_reg.update_traces(textinfo='percent+label')
            fig_pie_reg.update_layout(height=400)
            st.plotly_chart(fig_pie_reg, use_container_width=True, config={'displayModeBar': False})
        
        with st.expander("📋 Ver tabela de cancelamentos por região"):
            st.dataframe(
                df_regiao,
                use_container_width=True,
                column_config={
                    'total_cancelamentos': st.column_config.NumberColumn('Total Cancelamentos', format='%d'),
                    'total_condominios': st.column_config.NumberColumn('Condomínios', format='%d'),
                    'media_por_condominio': st.column_config.NumberColumn('Média/Condomínio', format='%.1f'),
                    'percentual': st.column_config.ProgressColumn('Percentual', format='%.1f%%', min_value=0, max_value=100),
                }
            )
        
        st.markdown("---")
    
    st.subheader("📋 Detalhamento de Cancelamentos")
    
    col_toggle1, col_toggle2 = st.columns([1, 1])
    
    with col_toggle1:
        visualizacao = st.radio(
            "Visualização:",
            options=["📋 Tabela", "🔥 Heatmap"],
            horizontal=True,
            key="cancelamentos_visualizacao"
        )
    
    with col_toggle2:
        top_n = st.slider(
            "🏆 Top N condomínios:",
            min_value=5,
            max_value=50,
            value=15,
            step=5,
            key="cancelamentos_top_n",
            help="Define quantos condomínios exibir na tabela e nos gráficos"
        )
    
    colunas_total = [c for c in df_pivot.columns if 'Total' in str(c)]
    colunas_meses = [c for c in df_pivot.columns if c not in colunas_total and c != 'Condomínio']
    
    df_sem_total = df_pivot[df_pivot['Condomínio'] != '📊 TOTAL GERAL']
    df_total_geral = df_pivot[df_pivot['Condomínio'] == '📊 TOTAL GERAL']
    
    df_top_n = df_sem_total.head(top_n)
    df_pivot_display = pd.concat([df_top_n, df_total_geral], ignore_index=True)
    
    if visualizacao == "📋 Tabela":
        st.markdown(f"**Exibindo Top {top_n} condomínios + linha de Total Geral**")
        
        column_config = {
            'Condomínio': st.column_config.TextColumn('Condomínio', width='medium'),
        }
        for col in colunas_meses:
            column_config[col] = st.column_config.NumberColumn(col, format='%d', width='small')
        for col in colunas_total:
            column_config[col] = st.column_config.NumberColumn(col, format='%d', width='small')
        
        st.dataframe(
            df_pivot_display,
            use_container_width=True,
            height=500,
            column_config=column_config
        )
        
        st.caption(f"📊 Mostrando {len(df_top_n)} de {len(df_sem_total)} condomínios. "
                   f"A linha **📊 TOTAL GERAL** soma todos os {len(df_sem_total)} condomínios.")
    
    else:
        st.markdown(f"**Heatmap - Top {top_n} condomínios**")
        
        df_heatmap = df_sem_total.head(top_n).set_index('Condomínio')[colunas_meses]
        
        fig_heatmap = px.imshow(
            df_heatmap,
            labels=dict(x="Mês", y="Condomínio", color="Cancelamentos"),
            color_continuous_scale='Reds',
            aspect='auto',
            title=f'🔥 Heatmap de Cancelamentos - Top {top_n} Condomínios',
            text_auto=True
        )
        fig_heatmap.update_layout(
            height=max(400, len(df_heatmap) * 25),
            xaxis_tickangle=-45,
            coloraxis_colorbar=dict(title="Cancel.")
        )
        fig_heatmap.update_xaxes(side="bottom")
        st.plotly_chart(fig_heatmap, use_container_width=True, config={'displayModeBar': False})
        
        st.caption(f"🔥 Intensidade das cores = volume de cancelamentos. "
                   f"Exibindo Top {top_n} de {len(df_sem_total)} condomínios.")
    
    st.markdown("---")
    
    col_g1, col_g2 = st.columns(2)
    
    with col_g1:
        if colunas_meses:
            totais_por_mes = df_sem_total[colunas_meses].sum().reset_index()
            totais_por_mes.columns = ['Mês', 'Total Cancelamentos']
            
            totais_por_mes['ordem'] = totais_por_mes['Mês'].apply(
                lambda x: colunas_meses.index(x) if x in colunas_meses else 999
            )
            totais_por_mes = totais_por_mes.sort_values('ordem')
            
            fig_meses = px.bar(
                totais_por_mes,
                x='Mês',
                y='Total Cancelamentos',
                color='Total Cancelamentos',
                color_continuous_scale='Reds',
                title='📊 Total de Cancelamentos por Mês',
                text='Total Cancelamentos'
            )
            fig_meses.update_traces(texttemplate='%{text}', textposition='outside')
            fig_meses.update_layout(height=400, coloraxis_showscale=False, xaxis_tickangle=-45)
            st.plotly_chart(fig_meses, use_container_width=True, config={'displayModeBar': False})
    
    with col_g2:
        df_top_n_resumo = df_resumo.head(top_n).copy()
        
        fig_top_n = px.bar(
            df_top_n_resumo.sort_values('total_cancelamentos', ascending=True),
            x='total_cancelamentos',
            y='Condomínio',
            color='total_cancelamentos',
            color_continuous_scale='Reds',
            title=f'🏆 Top {top_n} - Condomínios com Mais Cancelamentos',
            orientation='h',
            text='total_cancelamentos'
        )
        fig_top_n.update_traces(texttemplate='%{text}', textposition='outside')
        fig_top_n.update_layout(height=max(400, top_n * 25), coloraxis_showscale=False)
        st.plotly_chart(fig_top_n, use_container_width=True, config={'displayModeBar': False})
    
    st.markdown("---")
    st.subheader("📈 Evolução Mensal de Cancelamentos")
    
    if colunas_meses:
        df_evolucao = df_sem_total[['Condomínio'] + colunas_meses].copy()
        df_evolucao = df_evolucao.melt(
            id_vars=['Condomínio'],
            value_vars=colunas_meses,
            var_name='Mês',
            value_name='Cancelamentos'
        )
        
        total_por_mes = df_evolucao.groupby('Mês')['Cancelamentos'].sum().reset_index()
        
        total_por_mes['ordem'] = total_por_mes['Mês'].apply(
            lambda x: colunas_meses.index(x) if x in colunas_meses else 999
        )
        total_por_mes = total_por_mes.sort_values('ordem')
        
        fig_evolucao = px.line(
            total_por_mes,
            x='Mês',
            y='Cancelamentos',
            title='📈 Evolução Mensal do Total de Cancelamentos',
            markers=True
        )
        fig_evolucao.update_traces(
            line=dict(color='#e74c3c', width=3),
            marker=dict(size=10, color='#e74c3c')
        )
        fig_evolucao.update_layout(height=400, xaxis_tickangle=-45)
        st.plotly_chart(fig_evolucao, use_container_width=True, config={'displayModeBar': False})
    
    st.markdown("---")
    st.subheader("🔍 Análise Detalhada por Condomínio")
    
    if not df_resumo.empty:
        cond_select = st.selectbox(
            "Selecione um condomínio para análise detalhada:",
            options=df_resumo['Condomínio'].tolist(),
            key="cancelamentos_cond_select"
        )
        
        if cond_select:
            cond_data = df_resumo[df_resumo['Condomínio'] == cond_select].iloc[0]
            
            col_d1, col_d2, col_d3, col_d4 = st.columns(4)
            with col_d1:
                st.metric("🚫 Total Cancelamentos", formatar_numero_br(cond_data['total_cancelamentos']))
            with col_d2:
                st.metric("📊 Média Mensal", f"{cond_data.get('media_mensal', 0):.1f}")
            with col_d3:
                if 'mes_mais_cancelamentos' in cond_data:
                    st.metric("📅 Mês com Mais Cancel.", cond_data['mes_mais_cancelamentos'])
                else:
                    st.metric("📅 Mês com Mais Cancel.", "N/A")
            with col_d4:
                if 'regiao' in cond_data:
                    st.metric("📍 Região", cond_data['regiao'])
                else:
                    st.metric("📍 Região", "N/A")
            
            df_cond_evolucao = df_detalhado[df_detalhado['Condomínio'] == cond_select].copy()
            
            if not df_cond_evolucao.empty:
                evolucao_cond = df_cond_evolucao.groupby('mes_label').size().reset_index(name='cancelamentos')
                
                evolucao_cond['ordem'] = evolucao_cond['mes_label'].apply(
                    lambda x: colunas_meses.index(x) if x in colunas_meses else 999
                )
                evolucao_cond = evolucao_cond.sort_values('ordem')
                
                fig_cond = px.bar(
                    evolucao_cond,
                    x='mes_label',
                    y='cancelamentos',
                    title=f'📊 Cancelamentos Mensais - {cond_select}',
                    labels={'mes_label': 'Mês', 'cancelamentos': 'Cancelamentos'},
                    color='cancelamentos',
                    color_continuous_scale='Reds',
                    text='cancelamentos'
                )
                fig_cond.update_traces(texttemplate='%{text}', textposition='outside')
                fig_cond.update_layout(height=350, coloraxis_showscale=False, xaxis_tickangle=-45)
                st.plotly_chart(fig_cond, use_container_width=True, config={'displayModeBar': False})
    
    st.markdown("---")
    st.subheader("📎 Exportar Dados de Cancelamentos")
    
    col_exp1, col_exp2 = st.columns(2)
    
    with col_exp1:
        output = io.BytesIO()
        with pd.ExcelWriter(output, engine='openpyxl') as writer:
            df_pivot.to_excel(writer, sheet_name='Cancelamentos_Por_Mes', index=False)
            df_resumo.to_excel(writer, sheet_name='Resumo_Por_Condominio', index=False)
            
            if not df_regiao.empty:
                df_regiao.to_excel(writer, sheet_name='Resumo_Por_Regiao', index=False)
            
            if not df_detalhado.empty:
                cols_export = [c for c in ['Condomínio', 'Região', data_cancel_col, 'mes_label', 
                                           'RAZAO SOCIAL/NOME', 'STATUS ACESSO'] 
                              if c in df_detalhado.columns]
                df_detalhado[cols_export].to_excel(writer, sheet_name='Detalhamento', index=False)
        
        output.seek(0)
        
        st.download_button(
            "📥 Exportar Análise de Cancelamentos",
            output,
            f"cancelamentos_condominios_{datetime.now().strftime('%Y%m%d_%H%M')}.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            use_container_width=True
        )
    
    with col_exp2:
        st.info("""
        **📋 O que será exportado:**
        - **Cancelamentos_Por_Mes**: Tabela pivô com Total Geral
        - **Resumo_Por_Condominio**: Total e média por condomínio
        - **Resumo_Por_Regiao**: Agregação por região
        - **Detalhamento**: Lista completa de clientes cancelados
        """)
    
    st.markdown("---")
    st.subheader("💡 Insights")
    
    insights = []
    
    if colunas_meses:
        total_por_mes = df_sem_total[colunas_meses].sum()
        if not total_por_mes.empty:
            mes_pior = total_por_mes.idxmax()
            qtd_pior = total_por_mes.max()
            insights.append(f"📉 **Mês com mais cancelamentos:** {mes_pior} ({qtd_pior} cancelamentos)")
            
            mes_melhor = total_por_mes.idxmin()
            qtd_melhor = total_por_mes.min()
            insights.append(f"📈 **Mês com menos cancelamentos:** {mes_melhor} ({qtd_melhor} cancelamentos)")
    
    if not df_resumo.empty:
        top_cond = df_resumo.iloc[0]
        insights.append(f"🏆 **Condomínio com mais cancelamentos:** {top_cond['Condomínio']} ({top_cond['total_cancelamentos']} cancelamentos)")
    
    if len(colunas_meses) >= 2:
        primeiro_mes = colunas_meses[0]
        ultimo_mes = colunas_meses[-1]
        total_primeiro = df_sem_total[primeiro_mes].sum()
        total_ultimo = df_sem_total[ultimo_mes].sum()
        
        if total_primeiro > 0:
            variacao = ((total_ultimo - total_primeiro) / total_primeiro * 100)
            if variacao > 10:
                insights.append(f"📈 **Tendência de alta:** Cancelamentos aumentaram {variacao:.1f}% do primeiro para o último mês")
            elif variacao < -10:
                insights.append(f"📉 **Tendência de queda:** Cancelamentos reduziram {abs(variacao):.1f}% do primeiro para o último mês")
            else:
                insights.append(f"➡️ **Tendência estável:** Variação de {variacao:.1f}% no período")
    
    if not df_resumo.empty and total_cancelamentos > 0:
        top5_total = df_resumo.head(5)['total_cancelamentos'].sum()
        concentracao = (top5_total / total_cancelamentos * 100)
        insights.append(f"🎯 **Concentração:** Top 5 condomínios representam {concentracao:.1f}% dos cancelamentos")
    
    if not df_regiao.empty:
        top_regiao = df_regiao.iloc[0]
        insights.append(f"📍 **Região com mais cancelamentos:** {top_regiao['Região']} ({top_regiao['total_cancelamentos']} cancelamentos, {top_regiao['percentual']:.1f}%)")
    
    for insight in insights:
        st.info(insight)


# ==================== NOVA ABA: ANÁLISE AVANÇADA DE CANCELAMENTOS ====================

def render_aba_cancelamentos_avancado(df_clientes, df_condominios):
    """NOVA ABA: Análise Avançada de Cancelamentos"""
    st.subheader("📊 Análise Avançada de Cancelamentos")
    
    if df_clientes is None or df_clientes.empty or df_condominios is None or df_condominios.empty:
        st.warning("⚠️ Nenhum dado carregado para análise.")
        return
    
    data_cancel_col = None
    possiveis_colunas_cancel = [
        'data cancelamento', 'data_cancelamento', 'dt_cancelamento',
        'cancelamento', 'data desativacao', 'data_desativacao',
        'data cancel', 'dt_cancel', 'data de cancelamento',
        'data cancelado', 'cancelado em'
    ]
    
    for col in df_clientes.columns:
        col_lower = col.lower().strip()
        for possivel in possiveis_colunas_cancel:
            if possivel in col_lower:
                data_cancel_col = col
                break
        if data_cancel_col:
            break
    
    if data_cancel_col is None:
        data_cancel_col = identificar_coluna_data(df_clientes)
        if data_cancel_col is None:
            st.error("❌ Coluna de data de cancelamento não encontrada.")
            return
        st.info(f"📌 Usando a coluna **'{data_cancel_col}'** como referência (proxy).")
    
    df_clientes_temp = df_clientes.copy()
    df_condominios_temp = df_condominios.copy()
    
    df_clientes_temp['CONDOMANIO'] = pd.to_numeric(df_clientes_temp['CONDOMANIO'], errors='coerce').fillna(0).astype(int)
    df_condominios_temp['ID'] = pd.to_numeric(df_condominios_temp['ID'], errors='coerce').fillna(0).astype(int)
    df_clientes_temp[data_cancel_col] = pd.to_datetime(df_clientes_temp[data_cancel_col], errors='coerce')
    df_clientes_temp = df_clientes_temp.dropna(subset=[data_cancel_col])
    
    df_clientes_temp['status_classificacao'] = classificar_status_serie(df_clientes_temp.get('STATUS ACESSO', pd.Series()))
    
    df_cancelados = df_clientes_temp[df_clientes_temp['status_classificacao'] == 'Desativado'].copy()
    
    if df_cancelados.empty:
        s = df_clientes_temp['STATUS ACESSO'].fillna('').astype(str).str.lower()
        mascara_cancel = s.str.contains('cancelado|desativado|inativo|encerrado|churn', na=False)
        df_cancelados = df_clientes_temp[mascara_cancel].copy()
    
    if df_cancelados.empty:
        st.warning("⚠️ Nenhum cancelamento encontrado.")
        return
    
    df_cancelados = df_cancelados.merge(
        df_condominios_temp[['ID', 'Condomínio', 'Região']].drop_duplicates(),
        left_on='CONDOMANIO', right_on='ID', how='left'
    )
    df_cancelados['Condomínio'] = df_cancelados['Condomínio'].fillna(df_cancelados['CONDOMANIO'].astype(str))
    
    st.markdown("### 🎛️ Configuração")
    
    col_cfg1, col_cfg2 = st.columns(2)
    
    with col_cfg1:
        granularidade = st.selectbox(
            "📅 Granularidade da análise:",
            options=["Mensal", "Trimestral", "Semestral"],
            index=0,
            key="avancado_granularidade"
        )
    
    with col_cfg2:
        regioes_disp = sorted(df_condominios_temp['Região'].dropna().unique().tolist()) if 'Região' in df_condominios_temp.columns else []
        regioes_filtro = st.multiselect(
            "📍 Filtrar por Região:",
            options=regioes_disp,
            default=[],
            key="avancado_regioes"
        )
    
    if regioes_filtro:
        df_cancelados = df_cancelados[df_cancelados['Região'].isin(regioes_filtro)]
    
    if df_cancelados.empty:
        st.warning("⚠️ Nenhum dado encontrado com os filtros selecionados.")
        return
    
    if granularidade == "Mensal":
        df_cancelados['periodo'] = df_cancelados[data_cancel_col].dt.to_period('M')
        df_cancelados['periodo_label'] = df_cancelados[data_cancel_col].dt.strftime('%b/%Y')
    elif granularidade == "Trimestral":
        df_cancelados['periodo'] = df_cancelados[data_cancel_col].dt.to_period('Q')
        df_cancelados['periodo_label'] = df_cancelados['periodo'].apply(
            lambda x: f"T{x.quarter}/{x.year}" if pd.notna(x) else ""
        )
    else:
        df_cancelados['periodo'] = df_cancelados[data_cancel_col].dt.to_period('6M')
        df_cancelados['periodo_label'] = df_cancelados['periodo'].apply(
            lambda x: f"{'S1' if x.month <= 6 else 'S2'}/{x.year}" if pd.notna(x) else ""
        )
    
    st.markdown("---")
    st.subheader("📊 Comparação com Período Anterior")
    
    periodos = sorted(df_cancelados['periodo'].dropna().unique())
    
    if len(periodos) >= 2:
        periodo_atual = periodos[-1]
        periodo_anterior = periodos[-2]
        
        dados_atual = df_cancelados[df_cancelados['periodo'] == periodo_atual]
        dados_anterior = df_cancelados[df_cancelados['periodo'] == periodo_anterior]
        
        total_atual = len(dados_atual)
        total_anterior = len(dados_anterior)
        
        if total_anterior > 0:
            variacao = ((total_atual - total_anterior) / total_anterior * 100)
        else:
            variacao = 100 if total_atual > 0 else 0
        
        label_atual = dados_atual['periodo_label'].iloc[0] if not dados_atual.empty else str(periodo_atual)
        label_anterior = dados_anterior['periodo_label'].iloc[0] if not dados_anterior.empty else str(periodo_anterior)
        
        col_comp1, col_comp2, col_comp3, col_comp4 = st.columns(4)
        
        with col_comp1:
            st.metric(f"📅 Período Atual ({label_atual})", formatar_numero_br(total_atual))
        with col_comp2:
            st.metric(f"📅 Período Anterior ({label_anterior})", formatar_numero_br(total_anterior))
        with col_comp3:
            st.metric("📊 Variação", f"{variacao:+.1f}%", delta=f"{total_atual - total_anterior:+d}")
        with col_comp4:
            if variacao > 10:
                st.error("📈 **AUMENTO** de cancelamentos")
            elif variacao < -10:
                st.success("📉 **REDUÇÃO** de cancelamentos")
            else:
                st.info("➡️ **ESTÁVEL**")
        
        if 'Região' in df_cancelados.columns:
            st.markdown("#### 📊 Comparação Período Atual vs. Anterior por Região")
            
            comp_regiao = pd.DataFrame({
                'Região': sorted(set(dados_atual['Região'].dropna().unique()) | set(dados_anterior['Região'].dropna().unique())),
            })
            
            comp_regiao['Período Atual'] = comp_regiao['Região'].apply(
                lambda r: len(dados_atual[dados_atual['Região'] == r])
            )
            comp_regiao['Período Anterior'] = comp_regiao['Região'].apply(
                lambda r: len(dados_anterior[dados_anterior['Região'] == r])
            )
            
            fig_comp = px.bar(
                comp_regiao.melt(id_vars=['Região'], value_vars=['Período Anterior', 'Período Atual'],
                                 var_name='Período', value_name='Cancelamentos'),
                x='Região',
                y='Cancelamentos',
                color='Período',
                barmode='group',
                title=f'📊 Cancelamentos por Região - {label_anterior} vs {label_atual}',
                color_discrete_map={'Período Anterior': '#95a5a6', 'Período Atual': '#e74c3c'}
            )
            fig_comp.update_layout(height=400, xaxis_tickangle=-45)
            st.plotly_chart(fig_comp, use_container_width=True, config={'displayModeBar': False})
    else:
        st.info("ℹ️ Dados insuficientes para comparação.")
    
    st.markdown("---")
    st.subheader("📈 Análise de Tendência")
    
    tendencia = df_cancelados.groupby('periodo').size().reset_index(name='cancelamentos')
    tendencia['periodo_str'] = tendencia['periodo'].apply(lambda x: str(x) if pd.notna(x) else '')
    tendencia = tendencia.sort_values('periodo')
    
    if len(tendencia) >= 3:
        tendencia['media_movel_3'] = tendencia['cancelamentos'].rolling(window=3, min_periods=1).mean().round(1)
        
        fig_tend = go.Figure()
        
        fig_tend.add_trace(go.Scatter(
            x=tendencia['periodo_str'],
            y=tendencia['cancelamentos'],
            mode='lines+markers',
            name='Cancelamentos',
            line=dict(color='#e74c3c', width=3),
            marker=dict(size=10)
        ))
        
        fig_tend.add_trace(go.Scatter(
            x=tendencia['periodo_str'],
            y=tendencia['media_movel_3'],
            mode='lines',
            name='Média Móvel (3 períodos)',
            line=dict(color='#3498db', width=2, dash='dash')
        ))
        
        fig_tend.update_layout(
            title='📈 Tendência de Cancelamentos',
            height=400,
            xaxis_title='Período',
            yaxis_title='Cancelamentos',
            hovermode='x unified'
        )
        st.plotly_chart(fig_tend, use_container_width=True, config={'displayModeBar': False})
        
        if len(tendencia) >= 2:
            primeiro = tendencia.iloc[0]['cancelamentos']
            ultimo = tendencia.iloc[-1]['cancelamentos']
            var_total = ((ultimo - primeiro) / primeiro * 100) if primeiro > 0 else 0
            
            if var_total > 20:
                st.error(f"🚨 **Tendência CRESCENTE:** Aumento de {var_total:.1f}% no período")
            elif var_total > 5:
                st.warning(f"📈 **Tendência de alta moderada:** Aumento de {var_total:.1f}%")
            elif var_total < -20:
                st.success(f"✅ **Tendência DECRESCENTE:** Redução de {abs(var_total):.1f}%")
            elif var_total < -5:
                st.info(f"📉 **Tendência de queda moderada:** Redução de {abs(var_total):.1f}%")
            else:
                st.info(f"➡️ **Tendência ESTÁVEL:** Variação de {var_total:.1f}%")
    else:
        st.info("ℹ️ Dados insuficientes para análise de tendência (mínimo 3 períodos).")
    
    st.markdown("---")
    st.subheader("🌊 Análise de Sazonalidade")
    
    if granularidade == "Mensal":
        df_cancelados['mes'] = df_cancelados[data_cancel_col].dt.month
        
        meses_pt = {
            1: 'Jan', 2: 'Fev', 3: 'Mar', 4: 'Abr',
            5: 'Mai', 6: 'Jun', 7: 'Jul', 8: 'Ago',
            9: 'Set', 10: 'Out', 11: 'Nov', 12: 'Dez'
        }
        
        sazonalidade = df_cancelados.groupby('mes').size().reset_index(name='total')
        sazonalidade['mes_nome'] = sazonalidade['mes'].map(meses_pt)
        sazonalidade = sazonalidade.sort_values('mes')
        
        media_geral = sazonalidade['total'].mean()
        sazonalidade['percentual_acima'] = ((sazonalidade['total'] / media_geral - 1) * 100).round(1)
        
        col_saz1, col_saz2 = st.columns([2, 1])
        
        with col_saz1:
            fig_saz = px.bar(
                sazonalidade,
                x='mes_nome',
                y='total',
                color='percentual_acima',
                color_continuous_scale='RdYlGn_r',
                title='🌊 Sazonalidade dos Cancelamentos por Mês',
                text='total'
            )
            fig_saz.update_traces(texttemplate='%{text}', textposition='outside')
            fig_saz.update_layout(height=400, coloraxis_showscale=False)
            st.plotly_chart(fig_saz, use_container_width=True, config={'displayModeBar': False})
        
        with col_saz2:
            st.markdown("##### 🔍 Insights de Sazonalidade")
            
            pior_mes = sazonalidade.loc[sazonalidade['total'].idxmax()]
            melhor_mes = sazonalidade.loc[sazonalidade['total'].idxmin()]
            
            st.metric("📛 Mês com Mais Cancel.", pior_mes['mes_nome'], 
                     delta=f"{pior_mes['percentual_acima']:+.1f}%")
            st.metric("✅ Mês com Menos Cancel.", melhor_mes['mes_nome'],
                     delta=f"{melhor_mes['percentual_acima']:+.1f}%")
    else:
        st.info("💡 Selecione a granularidade **Mensal** para análise de sazonalidade.")
    
    st.markdown("---")
    st.subheader("📦 Análise de Coorte Temporal")
    
    df_cancelados['ano_trim'] = df_cancelados[data_cancel_col].dt.to_period('Q')
    coorte = df_cancelados.groupby('ano_trim').agg(
        total=('CONDOMANIO', 'count'),
        condominios=('Condomínio', 'nunique')
    ).reset_index()
    coorte['label'] = coorte['ano_trim'].apply(lambda x: f"T{x.quarter}/{x.year}" if pd.notna(x) else '')
    coorte = coorte.sort_values('ano_trim')
    
    if len(coorte) >= 2:
        coorte['variacao'] = coorte['total'].pct_change() * 100
        coorte['variacao'] = coorte['variacao'].fillna(0).round(1)
        
        col_coorte1, col_coorte2 = st.columns(2)
        
        with col_coorte1:
            fig_coorte = go.Figure()
            
            fig_coorte.add_trace(go.Bar(
                x=coorte['label'],
                y=coorte['total'],
                name='Cancelamentos',
                marker_color='#e74c3c',
                text=coorte['total'],
                textposition='outside'
            ))
            
            fig_coorte.update_layout(
                title='📦 Coorte Trimestral de Cancelamentos',
                height=400,
                xaxis_title='Trimestre',
                yaxis_title='Cancelamentos'
            )
            st.plotly_chart(fig_coorte, use_container_width=True, config={'displayModeBar': False})
        
        with col_coorte2:
            st.markdown("##### 📊 Variação Trimestre a Trimestre")
            
            for _, row in coorte.iterrows():
                if row['variacao'] > 10:
                    st.error(f"📈 **{row['label']}**: {row['total']} cancel. ({row['variacao']:+.1f}%)")
                elif row['variacao'] < -10:
                    st.success(f"📉 **{row['label']}**: {row['total']} cancel. ({row['variacao']:+.1f}%)")
                else:
                    st.info(f"➡️ **{row['label']}**: {row['total']} cancel. ({row['variacao']:+.1f}%)")
    else:
        st.info("ℹ️ Dados insuficientes para análise de coorte.")
    
    st.markdown("---")
    st.subheader("🏆 Ranking de Regiões por Cancelamento")
    
    if 'Região' in df_cancelados.columns:
        regiao_stats = df_cancelados.groupby('Região').agg(
            total_cancelamentos=('CONDOMANIO', 'count'),
            total_condominios=('Condomínio', 'nunique')
        ).reset_index()
        
        regiao_stats['media_por_condominio'] = (
            regiao_stats['total_cancelamentos'] / regiao_stats['total_condominios']
        ).round(1)
        
        total_geral = regiao_stats['total_cancelamentos'].sum()
        regiao_stats['percentual'] = (
            regiao_stats['total_cancelamentos'] / total_geral * 100
        ).round(1) if total_geral > 0 else 0
        
        regiao_stats = regiao_stats.sort_values('total_cancelamentos', ascending=False)
        
        st.dataframe(
            regiao_stats,
            use_container_width=True,
            column_config={
                'Região': st.column_config.TextColumn('Região'),
                'total_cancelamentos': st.column_config.NumberColumn('Total Cancelamentos', format='%d'),
                'total_condominios': st.column_config.NumberColumn('Condomínios', format='%d'),
                'media_por_condominio': st.column_config.NumberColumn('Média/Condomínio', format='%.1f'),
                'percentual': st.column_config.ProgressColumn('Percentual', format='%.1f%%', min_value=0, max_value=100),
            }
        )
    
    st.markdown("---")
    st.subheader("📎 Exportar Análise Avançada")
    
    output_avancado = io.BytesIO()
    with pd.ExcelWriter(output_avancado, engine='openpyxl') as writer:
        if 'tendencia' in locals() and not tendencia.empty:
            tendencia.to_excel(writer, sheet_name='Tendencia', index=False)
        if 'sazonalidade' in locals() and not sazonalidade.empty:
            sazonalidade.to_excel(writer, sheet_name='Sazonalidade', index=False)
        if 'coorte' in locals() and not coorte.empty:
            coorte.to_excel(writer, sheet_name='Coorte_Trimestral', index=False)
        if 'regiao_stats' in locals() and not regiao_stats.empty:
            regiao_stats.to_excel(writer, sheet_name='Ranking_Regioes', index=False)
    
    output_avancado.seek(0)
    
    st.download_button(
        "📥 Exportar Análise Avançada de Cancelamentos",
        output_avancado,
        f"cancelamentos_avancado_{datetime.now().strftime('%Y%m%d_%H%M')}.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        use_container_width=True
    )


# ==================== FUNÇÃO: ANÁLISE DE CRESCIMENTO POR CONDOMÍNIO ====================

def render_analise_crescimento_condominios(df_clientes, df_condominios, df_meus_prospeccao, data_inicio_padrao=None):
    """Análise de crescimento individual por condomínio"""
    st.subheader("📈 Crescimento Individual por Condomínio")
    
    if df_clientes is None or df_clientes.empty or df_condominios is None or df_condominios.empty:
        st.warning("⚠️ Nenhum dado carregado para análise.")
        return
    
    if df_meus_prospeccao is None or df_meus_prospeccao.empty:
        st.warning("⚠️ Nenhum condomínio encontrado em 'Meus Acompanhamentos'.")
        return
    
    df_clientes_temp = df_clientes.copy()
    df_condominios_temp = df_condominios.copy()
    df_meus_prospeccao_temp = df_meus_prospeccao.copy()
    
    if 'CONDOMANIO' in df_clientes_temp.columns:
        df_clientes_temp['CONDOMANIO'] = pd.to_numeric(df_clientes_temp['CONDOMANIO'], errors='coerce').fillna(0).astype(int)
    if 'ID' in df_condominios_temp.columns:
        df_condominios_temp['ID'] = pd.to_numeric(df_condominios_temp['ID'], errors='coerce').fillna(0).astype(int)
    
    data_col = identificar_coluna_data(df_clientes_temp)
    
    if data_col is None:
        st.error("❌ Coluna de data de cadastro não encontrada. Análise indisponível.")
        return
    
    df_clientes_temp[data_col] = pd.to_datetime(df_clientes_temp[data_col], errors='coerce')
    df_clientes_temp = df_clientes_temp.dropna(subset=[data_col])
    
    if df_clientes_temp.empty:
        st.warning("⚠️ Nenhuma data de cadastro válida encontrada.")
        return
    
    df_clientes_temp['status_classificacao'] = classificar_status_serie(df_clientes_temp.get('STATUS ACESSO', pd.Series()))
    df_clientes_temp['is_active'] = df_clientes_temp['status_classificacao'] == 'Ativo'
    
    st.markdown("### 🎯 Filtro por Fase")
    
    fases_disponiveis = sorted(df_meus_prospeccao_temp['FASE_CLASSIFICADA'].dropna().unique().tolist())
    
    if not fases_disponiveis:
        fases_disponiveis = [
            "✅ Entramos", "💼 Em Negociação", "📢 Lançamento",
            "🚧 Início de Obra", "🔨 Obra em Andamento", "🏁 Final de Obra",
            "🎉 Entregue", "🏡 Pronto Para Morar", "📅 Futuro Lançamento", "❌ Não Entramos"
        ]
    
    opcoes_fases = ["Todas"] + fases_disponiveis
    
    fases_selecionadas = st.multiselect(
        "Selecione as fases que deseja analisar:",
        options=opcoes_fases,
        default=["Todas"],
        key="fases_filter_crescimento"
    )
    
    if "Todas" not in fases_selecionadas and fases_selecionadas:
        df_meus_prospeccao_temp = df_meus_prospeccao_temp[df_meus_prospeccao_temp['FASE_CLASSIFICADA'].isin(fases_selecionadas)]
        if df_meus_prospeccao_temp.empty:
            st.warning(f"⚠️ Nenhum condomínio encontrado nas fases selecionadas.")
            return
        st.info(f"🎯 Filtrando condomínios nas fases: **{', '.join(fases_selecionadas)}**")
    else:
        st.info("🌍 Mostrando **todos** os condomínios (todas as fases)")
    
    meus_nomes = set(df_meus_prospeccao_temp['NOME'].str.strip().str.upper().unique())
    
    df_condominios_temp['nome_normalizado'] = df_condominios_temp['Condomínio'].str.strip().str.upper()
    df_condominios_filtrados = df_condominios_temp[df_condominios_temp['nome_normalizado'].isin(meus_nomes)].copy()
    
    if df_condominios_filtrados.empty:
        st.warning("⚠️ Nenhum dos condomínios de acompanhamento foi encontrado na base de clientes.")
        return
    
    st.markdown("### 📅 Período de Análise")
    
    if data_inicio_padrao is None:
        data_inicio_padrao = datetime(2026, 6, 1)
    
    col1, col2, col3 = st.columns([2, 2, 1])
    
    with col1:
        usar_preset = st.checkbox("Usar período pré-definido", value=True, key="usar_preset_crescimento")
        
        if usar_preset:
            periodo_preset = st.selectbox(
                "Período:",
                options=[
                    "Junho/2026 até hoje",
                    "Últimos 3 meses",
                    "Últimos 6 meses",
                    "Último ano",
                    "Últimos 2 anos",
                    "Todos os dados"
                ],
                index=0,
                key="crescimento_periodo_preset"
            )
            
            if periodo_preset == "Junho/2026 até hoje":
                data_inicio = datetime(2026, 6, 1)
                data_fim = datetime.now().replace(tzinfo=None)
                st.info(f"📅 Período: {data_inicio.strftime('%B/%Y')} até {data_fim.strftime('%d/%m/%Y')}")
            elif periodo_preset == "Últimos 3 meses":
                data_inicio = datetime.now().replace(tzinfo=None) - timedelta(days=90)
                data_fim = datetime.now().replace(tzinfo=None)
            elif periodo_preset == "Últimos 6 meses":
                data_inicio = datetime.now().replace(tzinfo=None) - timedelta(days=180)
                data_fim = datetime.now().replace(tzinfo=None)
            elif periodo_preset == "Último ano":
                data_inicio = datetime.now().replace(tzinfo=None) - timedelta(days=365)
                data_fim = datetime.now().replace(tzinfo=None)
            elif periodo_preset == "Últimos 2 anos":
                data_inicio = datetime.now().replace(tzinfo=None) - timedelta(days=730)
                data_fim = datetime.now().replace(tzinfo=None)
            else:
                data_inicio = df_clientes_temp[data_col].min()
                data_fim = datetime.now().replace(tzinfo=None)
        else:
            st.markdown("#### Data Inicial")
            col_mes1, col_ano1 = st.columns(2)
            with col_mes1:
                mes_inicio = st.selectbox(
                    "Mês", options=list(range(1, 13)),
                    format_func=lambda x: ["Janeiro", "Fevereiro", "Março", "Abril", "Maio", "Junho",
                                           "Julho", "Agosto", "Setembro", "Outubro", "Novembro", "Dezembro"][x-1],
                    index=5, key="mes_inicio_cresc"
                )
            with col_ano1:
                ano_inicio = st.number_input("Ano", min_value=2020, max_value=2030, value=2026, key="ano_inicio_cresc", step=1)
            data_inicio = datetime(ano_inicio, mes_inicio, 1)
            
            st.markdown("#### Data Final")
            col_mes2, col_ano2 = st.columns(2)
            with col_mes2:
                mes_fim = st.selectbox(
                    "Mês", options=list(range(1, 13)),
                    format_func=lambda x: ["Janeiro", "Fevereiro", "Março", "Abril", "Maio", "Junho",
                                           "Julho", "Agosto", "Setembro", "Outubro", "Novembro", "Dezembro"][x-1],
                    index=datetime.now().month - 1, key="mes_fim_cresc"
                )
            with col_ano2:
                ano_fim = st.number_input("Ano", min_value=2020, max_value=2030, value=datetime.now().year, key="ano_fim_cresc", step=1)
            ultimo_dia = calendar.monthrange(ano_fim, mes_fim)[1]
            data_fim = datetime(ano_fim, mes_fim, ultimo_dia)
            
            st.info(f"📅 Período: {data_inicio.strftime('%B/%Y')} até {data_fim.strftime('%B/%Y')}")
    
    with col3:
        if st.button("🔄 Atualizar Análise", key="btn_atualizar_crescimento", use_container_width=True):
            st.rerun()
    
    with st.spinner("🔄 Calculando crescimento por condomínio..."):
        resultados = []
        
        for _, cond_row in df_condominios_filtrados.iterrows():
            cond_id = cond_row['ID']
            cond_nome = cond_row['Condomínio']
            regiao = cond_row.get('Região', 'N/A')
            total_aptos = cond_row.get('Apartamentos', 0)
            
            clientes_cond = df_clientes_temp[df_clientes_temp['CONDOMANIO'] == cond_id]
            
            if clientes_cond.empty:
                continue
            
            clientes_ativos = clientes_cond[clientes_cond['is_active']]
            
            if clientes_ativos.empty:
                continue
            
            total_inicio = (clientes_ativos[data_col] <= data_inicio).sum()
            total_fim = (clientes_ativos[data_col] <= data_fim).sum()
            
            variacao = total_fim - total_inicio
            taxa_crescimento = (variacao / total_inicio * 100) if total_inicio > 0 else (100 if total_fim > 0 else 0)
            
            meses = max(1, (data_fim - data_inicio).days / 30.44)
            taxa_mensal = (taxa_crescimento / meses) if meses > 0 else 0
            
            penetracao = (total_fim / total_aptos * 100) if total_aptos > 0 else 0
            
            if variacao > 0:
                status = "📈 Crescendo"
            elif variacao < 0:
                status = "📉 Declinando"
            else:
                status = "➡️ Estável"
            
            fase_prospec = "N/A"
            info_prospec = df_meus_prospeccao_temp[df_meus_prospeccao_temp['NOME'].str.strip().str.upper() == cond_nome.upper()]
            if not info_prospec.empty:
                fase_prospec = info_prospec.iloc[0].get('FASE_CLASSIFICADA', 'N/A')
            
            resultados.append({
                'Condomínio': cond_nome,
                'Região': regiao,
                'Fase Prospecção': fase_prospec,
                'Total Apartamentos': total_aptos,
                'Clientes Início': total_inicio,
                'Clientes Fim': total_fim,
                'Variação': variacao,
                'Crescimento %': taxa_crescimento,
                'Taxa Mensal %': taxa_mensal,
                'Penetração %': penetracao,
                'Status': status,
                'Data Início': data_inicio,
                'Data Fim': data_fim
            })
    
    if not resultados:
        st.warning("⚠️ Nenhum dado de crescimento encontrado.")
        return
    
    df_resultados = pd.DataFrame(resultados)
    
    st.markdown("---")
    
    total_crescimento = df_resultados['Variação'].sum()
    cond_crescendo = len(df_resultados[df_resultados['Variação'] > 0])
    cond_declinando = len(df_resultados[df_resultados['Variação'] < 0])
    
    col_m1, col_m2, col_m3, col_m4 = st.columns(4)
    with col_m1:
        st.metric("🏢 Total Condomínios", len(df_resultados))
    with col_m2:
        st.metric("📈 Crescendo", cond_crescendo)
    with col_m3:
        st.metric("📉 Declinando", cond_declinando)
    with col_m4:
        st.metric("📊 Crescimento Total", f"{total_crescimento:+.0f} clientes")
    
    if "Todas" not in fases_selecionadas and fases_selecionadas:
        st.info(f"🎯 Filtrando condomínios nas fases: **{', '.join(fases_selecionadas)}**")
    
    st.markdown("---")
    st.subheader("📋 Comparativo por Condomínio")
    
    df_sorted = df_resultados.sort_values('Crescimento %', ascending=False).reset_index(drop=True)
    
    df_display = df_sorted.copy()
    df_display['Crescimento %'] = df_display['Crescimento %'].apply(lambda x: f"{x:.1f}%")
    df_display['Taxa Mensal %'] = df_display['Taxa Mensal %'].apply(lambda x: f"{x:.1f}%")
    df_display['Penetração %'] = df_display['Penetração %'].apply(lambda x: f"{x:.1f}%")
    df_display['Variação'] = df_display['Variação'].apply(lambda x: f"{x:+.0f}")
    
    st.dataframe(
        df_display[[
            'Condomínio', 'Região', 'Fase Prospecção', 'Total Apartamentos',
            'Clientes Início', 'Clientes Fim', 'Variação', 'Crescimento %',
            'Taxa Mensal %', 'Penetração %', 'Status'
        ]],
        use_container_width=True,
        height=400
    )
    
    st.markdown("---")
    
    col_g1, col_g2 = st.columns(2)
    
    with col_g1:
        fig_top = px.bar(
            df_sorted.head(10),
            x='Crescimento %',
            y='Condomínio',
            color='Crescimento %',
            color_continuous_scale='RdYlGn',
            title='🏆 Top 10 - Maior Crescimento (%)',
            orientation='h',
            text='Crescimento %'
        )
        fig_top.update_traces(texttemplate='%{text:.1f}%', textposition='outside')
        fig_top.update_layout(height=400, coloraxis_showscale=False)
        st.plotly_chart(fig_top, use_container_width=True, config={'displayModeBar': False})
    
    with col_g2:
        df_bottom = df_sorted.tail(10).sort_values('Crescimento %', ascending=True)
        fig_bottom = px.bar(
            df_bottom,
            x='Crescimento %',
            y='Condomínio',
            color='Crescimento %',
            color_continuous_scale='RdYlGn_r',
            title='⚠️ Menor Crescimento (%)',
            orientation='h',
            text='Crescimento %'
        )
        fig_bottom.update_traces(texttemplate='%{text:.1f}%', textposition='outside')
        fig_bottom.update_layout(height=400, coloraxis_showscale=False)
        st.plotly_chart(fig_bottom, use_container_width=True, config={'displayModeBar': False})
    
    st.markdown("---")
    st.subheader("📎 Exportar Dados de Crescimento")
    
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        df_sorted.to_excel(writer, sheet_name='Crescimento_Condominios', index=False)
    output.seek(0)
    
    st.download_button(
        "📥 Exportar Análise de Crescimento",
        output,
        f"crescimento_condominios_{datetime.now().strftime('%Y%m%d_%H%M')}.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        use_container_width=True
    )


# ==================== FUNÇÕES OTIMIZADAS PARA CONSULTA DE CRÉDITO ====================

@st.cache_data(ttl=300, show_spinner=False)
def analisar_inadimplencia_periodo_otimizado(_df_parcelas_hash, _df_clientes_hash, _df_condominios_hash,
                                              dias_atraso, data_referencia_str, parcelas_shape, clientes_shape):
    """VERSÃO OTIMIZADA - Processamento vetorizado sem loops"""
    df_parcelas = st.session_state.condominios_dados_parcelas
    df_clientes = st.session_state.condominios_dados_clientes
    df_condominios = st.session_state.condominios_dados_condominios
    
    if df_parcelas is None or df_parcelas.empty:
        return pd.DataFrame(), pd.DataFrame(), pd.DataFrame()
    
    data_referencia = datetime.fromisoformat(data_referencia_str)
    
    parcelas_cols = ['ID', 'DATA DO VENCIMENTO', 'STATUS', 'VALOR']
    parcelas_existentes = [c for c in parcelas_cols if c in df_parcelas.columns]
    
    df_parcelas_subset = df_parcelas[parcelas_existentes].copy()
    df_clientes_subset = df_clientes[['ID', 'CONDOMANIO']].copy() if 'ID' in df_clientes.columns and 'CONDOMANIO' in df_clientes.columns else pd.DataFrame()
    df_cond_subset = df_condominios[['ID', 'Condomínio', 'Região', 'Apartamentos']].copy() if df_condominios is not None else pd.DataFrame()
    
    if df_clientes_subset.empty or df_cond_subset.empty:
        return pd.DataFrame(), pd.DataFrame(), pd.DataFrame()
    
    df_parcelas_subset.loc[:, 'DATA DO VENCIMENTO'] = pd.to_datetime(df_parcelas_subset['DATA DO VENCIMENTO'], errors='coerce')
    df_parcelas_subset.loc[:, 'STATUS_NORMALIZADO'] = df_parcelas_subset['STATUS'].str.upper().str.strip()
    df_parcelas_subset = df_parcelas_subset.dropna(subset=['DATA DO VENCIMENTO'])
    
    if df_parcelas_subset.empty:
        return pd.DataFrame(), pd.DataFrame(), pd.DataFrame()
    
    data_limite = data_referencia - timedelta(days=dias_atraso)
    
    mascara_vencidas = (
        (df_parcelas_subset['DATA DO VENCIMENTO'] <= data_limite) &
        (df_parcelas_subset['STATUS_NORMALIZADO'] == "A RECEBER")
    )
    
    parcelas_vencidas = df_parcelas_subset[mascara_vencidas].copy()
    
    if parcelas_vencidas.empty:
        return pd.DataFrame(), pd.DataFrame(), pd.DataFrame()
    
    parcelas_vencidas.loc[:, 'DIAS_ATRASO'] = (data_referencia - parcelas_vencidas['DATA DO VENCIMENTO']).dt.days
    
    parcelas_vencidas.loc[:, 'FAIXA_ATRASO'] = pd.cut(
        parcelas_vencidas['DIAS_ATRASO'],
        bins=[0, 30, 60, 90, float('inf')],
        labels=['1-30 dias', '31-60 dias', '61-90 dias', '90+ dias']
    )
    
    cliente_atraso = parcelas_vencidas.groupby('ID', as_index=False).agg({
        'VALOR': ['count', 'sum'],
        'DIAS_ATRASO': ['max', 'mean']
    })
    
    cliente_atraso.columns = ['ID', 'total_parcelas_vencidas', 'valor_total_atraso', 'max_dias_atraso', 'media_dias_atraso']
    
    cliente_atraso['ID'] = pd.to_numeric(cliente_atraso['ID'], errors='coerce').fillna(0).astype(int)
    df_clientes_subset['ID'] = pd.to_numeric(df_clientes_subset['ID'], errors='coerce').fillna(0).astype(int)
    df_clientes_subset['CONDOMANIO'] = pd.to_numeric(df_clientes_subset['CONDOMANIO'], errors='coerce').fillna(0).astype(int)
    
    cliente_atraso = cliente_atraso.merge(df_clientes_subset, on='ID', how='left')
    cliente_atraso = cliente_atraso[cliente_atraso['CONDOMANIO'] > 0]
    
    if cliente_atraso.empty:
        return pd.DataFrame(), pd.DataFrame(), pd.DataFrame()
    
    cond_agg = cliente_atraso.groupby('CONDOMANIO', as_index=False).agg({
        'ID': 'count',
        'total_parcelas_vencidas': 'sum',
        'valor_total_atraso': 'sum',
        'media_dias_atraso': 'mean',
        'max_dias_atraso': 'max'
    }).rename(columns={'ID': 'total_clientes_inadimplentes'})
    
    total_clientes_cond = df_clientes_subset.groupby('CONDOMANIO').size().reset_index(name='total_clientes')
    cond_agg = cond_agg.merge(total_clientes_cond, on='CONDOMANIO', how='right')
    
    cond_agg['taxa_inadimplencia'] = np.where(
        cond_agg['total_clientes'] > 0,
        cond_agg['total_clientes_inadimplentes'] / cond_agg['total_clientes'] * 100,
        0
    ).round(2)
    
    df_cond_subset['ID'] = pd.to_numeric(df_cond_subset['ID'], errors='coerce').fillna(0).astype(int)
    result = cond_agg.merge(df_cond_subset, left_on='CONDOMANIO', right_on='ID', how='right')
    
    numeric_cols = ['total_clientes', 'total_clientes_inadimplentes', 'total_parcelas_vencidas',
                    'valor_total_atraso', 'taxa_inadimplencia', 'media_dias_atraso', 'max_dias_atraso']
    
    for col in numeric_cols:
        if col in result.columns:
            result[col] = result[col].fillna(0)
    
    int_cols = ['total_clientes', 'total_clientes_inadimplentes', 'total_parcelas_vencidas']
    for col in int_cols:
        if col in result.columns:
            result[col] = result[col].astype(int)
    
    result = result.sort_values('taxa_inadimplencia', ascending=False).reset_index(drop=True)
    
    return result, cliente_atraso, parcelas_vencidas


@st.cache_data(ttl=300, show_spinner=False)
def identificar_condominios_aptos_consulta_flexivel_otimizado(df_inadimplencia_hash, 
                                                               taxa_minima, 
                                                               min_inadimplentes, 
                                                               valor_minimo_atraso,
                                                               ativar_filtro_valor,
                                                               df_shape):
    """VERSÃO OTIMIZADA - Filtros em lote sem loops"""
    df_inadimplencia = st.session_state.ultimo_resultado_inadimplencia
    
    if df_inadimplencia is None or df_inadimplencia.empty:
        return pd.DataFrame(), pd.DataFrame()
    
    mascara = (df_inadimplencia['taxa_inadimplencia'] >= taxa_minima) & \
              (df_inadimplencia['total_clientes_inadimplentes'] >= min_inadimplentes)
    
    if ativar_filtro_valor and valor_minimo_atraso > 0:
        mascara &= (df_inadimplencia['valor_total_atraso'] >= valor_minimo_atraso)
    
    df_filtrado = df_inadimplencia[mascara].copy()
    
    if df_filtrado.empty:
        return pd.DataFrame(), pd.DataFrame()
    
    df_filtrado['score_prioridade'] = (
        df_filtrado['taxa_inadimplencia'] * 2 +
        df_filtrado['total_clientes_inadimplentes'] * 5 +
        df_filtrado['valor_total_atraso'] / 100
    ).round(2)
    
    conditions = [
        df_filtrado['score_prioridade'] >= 200,
        df_filtrado['score_prioridade'] >= 100,
        df_filtrado['score_prioridade'] >= 50
    ]
    choices = ['🔥 PRIORIDADE MÁXIMA', '🟠 Alta Prioridade', '🟡 Média Prioridade']
    df_filtrado['prioridade'] = np.select(conditions, choices, default='🟢 Baixa Prioridade')
    
    df_filtrado = df_filtrado.sort_values('score_prioridade', ascending=False).reset_index(drop=True)
    df_top_oportunidades = df_filtrado.head(10).copy()
    
    return df_filtrado, df_top_oportunidades


def render_filtros_consulta_credito_otimizado():
    """Renderiza filtros com opção de cache"""
    st.markdown("### ⚙️ Configuração da Análise")
    
    col1, col2 = st.columns(2)
    
    with col1:
        dias_atraso = st.slider(
            "📅 Dias de atraso para considerar inadimplente",
            min_value=1, max_value=90, value=30, step=5,
            key="consulta_dias_atraso"
        )
        
        data_referencia = st.date_input(
            "📆 Data de referência",
            value=datetime.now().date(),
            key="consulta_data_ref"
        )
    
    with col2:
        taxa_minima = st.slider(
            "📊 Taxa mínima de inadimplência (%)",
            min_value=0, max_value=100, value=30, step=5,
            key="consulta_taxa_minima"
        )
        
        min_inadimplentes = st.number_input(
            "👥 Número mínimo de clientes inadimplentes",
            min_value=0, max_value=1000, value=5, step=1,
            key="consulta_min_inadimplentes"
        )
    
    st.markdown("---")
    st.markdown("### 💰 Filtro de Valor")
    
    ativar_filtro_valor = st.checkbox(
        "✅ Ativar filtro de valor mínimo em atraso",
        value=True,
        key="ativar_filtro_valor"
    )
    
    valor_minimo_atraso = 0
    if ativar_filtro_valor:
        valor_minimo_atraso = st.number_input(
            "💰 Valor mínimo em atraso (R$)",
            min_value=0, max_value=100000, value=500, step=100,
            key="consulta_valor_minimo"
        )
    
    st.markdown("---")
    
    aplicar_filtros = st.button(
        "🔍 Aplicar Filtros e Gerar Ranking",
        type="primary",
        use_container_width=True,
        key="botao_aplicar_filtros_consulta"
    )
    
    return {
        'dias_atraso': dias_atraso,
        'data_referencia': datetime.combine(data_referencia, datetime.min.time()),
        'taxa_minima': taxa_minima,
        'min_inadimplentes': min_inadimplentes,
        'valor_minimo_atraso': valor_minimo_atraso if ativar_filtro_valor else 0,
        'ativar_filtro_valor': ativar_filtro_valor,
        'aplicar_filtros': aplicar_filtros
    }


def render_painel_condominios_aptos(df_aptos, df_top_oportunidades):
    """Renderiza painel com condomínios aptos para consulta"""
    st.markdown("## 🎯 Condomínios Aptos para Consulta de Crédito")
    
    if df_aptos.empty:
        st.info("ℹ️ Nenhum condomínio atende aos critérios definidos.")
        return
    
    col1, col2, col3, col4 = st.columns(4)
    col1.metric("🏢 Condomínios Aptos", len(df_aptos))
    col2.metric("👥 Total Inadimplentes", f"{df_aptos['total_clientes_inadimplentes'].sum():,}".replace(",", "."))
    col3.metric("💰 Valor Total em Atraso", formatar_moeda_br(df_aptos['valor_total_atraso'].sum()))
    col4.metric("📈 Média Inadimplência", f"{df_aptos['taxa_inadimplencia'].mean():.1f}%")
    
    st.markdown("---")
    
    st.subheader("🏆 Top 10 Condomínios - Maior Potencial para Consulta")
    
    colunas_exibir = [
        "Condomínio", "Região", "total_clientes", "total_clientes_inadimplentes",
        "taxa_inadimplencia", "valor_total_atraso", "max_dias_atraso", "prioridade"
    ]
    
    colunas_existentes = [c for c in colunas_exibir if c in df_top_oportunidades.columns]
    
    st.dataframe(
        df_top_oportunidades[colunas_existentes],
        use_container_width=True,
        height=400,
        column_config={
            "taxa_inadimplencia": st.column_config.ProgressColumn("Taxa Inadimplência", format="%.1f%%", min_value=0, max_value=100),
            "valor_total_atraso": st.column_config.NumberColumn("Valor em Atraso", format="R$ %.2f"),
        }
    )
    
    with st.expander("📋 Ver Todos os Condomínios Aptos"):
        df_exibir = df_aptos if len(df_aptos) <= 500 else df_aptos.head(500)
        if len(df_aptos) > 500:
            st.caption(f"⚠️ Exibindo apenas 500 de {len(df_aptos)} condomínios.")
        
        st.dataframe(
            df_exibir[colunas_existentes],
            use_container_width=True,
            height=400,
            column_config={
                "taxa_inadimplencia": st.column_config.ProgressColumn("Taxa Inadimplência", format="%.1f%%", min_value=0, max_value=100),
                "valor_total_atraso": st.column_config.NumberColumn("Valor em Atraso", format="R$ %.2f"),
            }
        )
    
    output_aptos = io.BytesIO()
    with pd.ExcelWriter(output_aptos, engine='openpyxl') as writer:
        df_aptos.to_excel(writer, sheet_name='Condominios_Aptos', index=False)
        df_top_oportunidades.to_excel(writer, sheet_name='Top_10_Oportunidades', index=False)
    output_aptos.seek(0)
    
    st.download_button(
        "📥 Exportar Lista de Condomínios Aptos",
        output_aptos,
        f"condominios_aptos_consulta_{datetime.now().strftime('%Y%m%d_%H%M')}.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        use_container_width=True
    )


# ==================== FUNÇÃO: HEALTH SCORE (CORRIGIDA E OTIMIZADA) ====================

def calcular_health_score_clientes(df_cancelados, df_parcelas, df_clientes_original):
    """
    Calcula Health Score (0-100) para cada cliente cancelado.
    
    🔑 CORREÇÃO CRÍTICA: aceita múltiplos status de pagamento:
       - "PAGO", "PAGA", "RECEBIDA", "RECEBIDO", "QUITADO", "LIQUIDADO"
    E ignora status como "CANCELADO", "ISENTO", "ESTORNADO".
    
    ⚡ OTIMIZADO: processamento totalmente vetorizado.
    """
    if df_cancelados.empty:
        return df_cancelados
    
    df = df_cancelados.copy()
    
    # Defaults
    df['total_parcelas'] = 0
    df['parcelas_pagas'] = 0
    df['parcelas_atrasadas'] = 0
    df['percentual_atraso'] = 0.0
    df['health_score'] = 50
    df['perfil_cliente'] = '🟡 Médio (Sem Histórico)'
    df['recomendacao'] = '⚠️ Avaliar individualmente'
    df['meses_como_cliente'] = 0.0
    df['score_pagamento'] = 0.0
    df['score_atraso'] = 20.0
    df['score_tempo'] = 0.0
    df['detalhe_saude'] = 'Sem histórico de parcelas'
    
    if df_parcelas is None or df_parcelas.empty:
        return df
    
    df_parcelas_temp = df_parcelas.copy()
    
    col_id = 'ID' if 'ID' in df_parcelas_temp.columns else None
    col_status = 'STATUS' if 'STATUS' in df_parcelas_temp.columns else None
    col_vencimento = 'DATA DO VENCIMENTO' if 'DATA DO VENCIMENTO' in df_parcelas_temp.columns else None
    
    if not all([col_id, col_status, col_vencimento]):
        return df
    
    # Normalizar IDs
    df_parcelas_temp[col_id] = pd.to_numeric(df_parcelas_temp[col_id], errors='coerce').fillna(0).astype(int)
    df[col_id] = pd.to_numeric(df[col_id], errors='coerce').fillna(0).astype(int)
    
    # 🔑 Normalização robusta de status: minúsculo, sem acento, sem espaços extras
    s = df_parcelas_temp[col_status].fillna('').astype(str).str.lower().str.strip()
    # Remove acentos
    s = s.str.normalize('NFKD').str.encode('ascii', errors='ignore').str.decode('utf-8')
    
    # ✅ Aceita: pago, paga, recebida, recebido, quitado, liquidado
    STATUS_PAGO = {
        'pago', 'paga', 'pagos', 'pagas',
        'recebida', 'recebido', 'recebidas', 'recebidos',
        'quitado', 'quitada', 'quitados', 'quitadas',
        'liquidado', 'liquidada', 'liquidados', 'liquidadas',
        'baixado', 'baixada'
    }
    
    STATUS_IGNORAR = {
        'cancelado', 'cancelada', 'cancelados', 'canceladas',
        'isento', 'isenta', 'isentos', 'isentas',
        'estornado', 'estornada', 'estornados', 'estornadas'
    }
    
    df_parcelas_temp['_is_pago'] = s.isin(STATUS_PAGO)
    df_parcelas_temp['_is_a_receber'] = (
        s.str.contains('a receber', na=False) | 
        s.str.contains('areceber', na=False) |
        s.str.contains('a_receber', na=False) |
        (s == 'a receber')
    )
    df_parcelas_temp['_is_ignorar'] = s.isin(STATUS_IGNORAR)
    
    # Filtrar apenas parcelas relevantes (excluir canceladas/isento/estornadas)
    df_relevante = df_parcelas_temp[~df_parcelas_temp['_is_ignorar']].copy()
    
    # Debug (opcional, útil para diagnosticar)
    # st.write(f"Status únicos encontrados: {sorted(s.unique().tolist())[:20]}")
    # st.write(f"Total relevante: {len(df_relevante)} | Pagos: {df_relevante['_is_pago'].sum()} | A receber: {df_relevante['_is_a_receber'].sum()}")
    
    if df_relevante.empty:
        return df
    
    # ⚡ Agregação vetorizada — uma única passada
    agg = df_relevante.groupby(col_id).agg(
        total_parcelas_agg=(col_status, 'size'),
        parcelas_pagas_agg=('_is_pago', 'sum'),
        parcelas_atrasadas_agg=('_is_a_receber', 'sum')
    ).reset_index()
    
    # Limpar colunas antigas (se existirem) para evitar conflito
    for c in ['total_parcelas_agg', 'parcelas_pagas_agg', 'parcelas_atrasadas_agg']:
        if c in df.columns:
            df = df.drop(columns=[c])
    
    df = df.merge(agg, on=col_id, how='left')
    
    df['total_parcelas_agg'] = df['total_parcelas_agg'].fillna(0).astype(int)
    df['parcelas_pagas_agg'] = df['parcelas_pagas_agg'].fillna(0).astype(int)
    df['parcelas_atrasadas_agg'] = df['parcelas_atrasadas_agg'].fillna(0).astype(int)
    
    df['total_parcelas'] = df['total_parcelas_agg']
    df['parcelas_pagas'] = df['parcelas_pagas_agg']
    df['parcelas_atrasadas'] = df['parcelas_atrasadas_agg']
    
    # % atraso
    denom = df['total_parcelas'].replace(0, np.nan)
    df['percentual_atraso'] = (df['parcelas_atrasadas'] / denom * 100).round(1).fillna(0.0)
    
    # Tempo como cliente — vetorizado
    data_col = None
    for col in df.columns:
        cl = col.lower()
        if 'data' in cl and 'cadastro' in cl:
            data_col = col
            break
    if data_col is None:
        data_col = identificar_coluna_data(df)
    
    data_cancel = None
    for col in df.columns:
        cl = col.lower()
        if 'cancelamento' in cl or 'desativacao' in cl or 'cancelado' in cl:
            data_cancel = col
            break
    
    if data_col and data_cancel:
        d1 = pd.to_datetime(df[data_col], errors='coerce')
        d2 = pd.to_datetime(df[data_cancel], errors='coerce')
        df['meses_como_cliente'] = ((d2 - d1).dt.days / 30.44).round(1).fillna(0).clip(lower=0)
    else:
        df['meses_como_cliente'] = 0.0
    
    # Scores — vetorizado
    df['score_pagamento'] = np.clip(df['parcelas_pagas'] / 6 * 40, 0, 40).round(1)
    df['score_atraso'] = np.clip((100 - df['percentual_atraso']) / 100 * 40, 0, 40).round(1)
    df['score_tempo'] = np.clip(df['meses_como_cliente'] / 12 * 20, 0, 20).round(1)
    
    df['health_score'] = (df['score_pagamento'] + df['score_atraso'] + df['score_tempo']).round(1)
    
    # 🔑 Classificação mais realista
    cond_saudavel = (
        (df['health_score'] >= 60) &
        (df['parcelas_pagas'] >= 3) &
        (df['percentual_atraso'] <= 30)
    )
    
    cond_ruim = (
        (df['health_score'] < 30) |
        (df['parcelas_pagas'] < 1) |  # 🔑 apenas 0 pagas = ruim
        (df['percentual_atraso'] > 50)
    )
    
    df['perfil_cliente'] = '🟡 Médio'
    df.loc[cond_saudavel, 'perfil_cliente'] = '🟢 Saudável'
    df.loc[cond_ruim, 'perfil_cliente'] = '🔴 Ruim'
    
    df['recomendacao'] = '🟡 Prioridade MÉDIA - Testar'
    df.loc[cond_saudavel, 'recomendacao'] = '✅ Prioridade ALTA - Recuperar'
    df.loc[cond_ruim, 'recomendacao'] = '🚫 NÃO recuperar - Alto risco'
    df.loc[~cond_saudavel & ~cond_ruim, 'recomendacao'] = '⚠️ Avaliar individualmente'
    
    df['detalhe_saude'] = (
        df['parcelas_pagas'].astype(str) + ' pagas | ' +
        df['percentual_atraso'].astype(str) + '% atraso | ' +
        df['meses_como_cliente'].astype(str) + ' meses'
    )
    
    for c in ['total_parcelas_agg', 'parcelas_pagas_agg', 'parcelas_atrasadas_agg']:
        if c in df.columns:
            df = df.drop(columns=[c])
    
    return df


def render_exportacao_winback(df_clientes, df_condominios, df_parcelas=None):
    """Renderiza a seção de exportação para campanhas de Win-Back."""
    st.markdown("---")
    st.subheader("🎯 Exportar Clientes para Win-Back (Recuperação)")
    
    st.markdown("""
    <div style="background-color:#fff3cd; padding:15px; border-radius:10px; margin-bottom:20px;">
    <strong>💡 O que é Win-Back com Health Score?</strong><br>
    Esta ferramenta permite exportar clientes que cancelaram há um determinado tempo,
    <strong>filtrando apenas os que foram BONS clientes</strong> enquanto estavam conosco.
    <br><br>
    <strong>📊 Classificação de Perfil:</strong>
    <ul>
        <li><strong>🟢 Saudável:</strong> Pagou em dia, ficou um tempo razoável → <strong>Vale recuperar!</strong></li>
        <li><strong>🟡 Médio:</strong> Alguns atrasos, mas nada grave → Testar com cautela</li>
        <li><strong>🔴 Ruim:</strong> Muitos atrasos ou poucas parcelas pagas → <strong>NÃO vale recuperar</strong></li>
    </ul>
    </div>
    """, unsafe_allow_html=True)
    
    if df_clientes is None or df_clientes.empty:
        st.warning("⚠️ Nenhum dado de cliente carregado.")
        return

    # Identificar coluna de cancelamento
    data_cancel_col = None
    possiveis_colunas_cancel = [
        'data cancelamento', 'data_cancelamento', 'dt_cancelamento',
        'cancelamento', 'data desativacao', 'data_desativacao',
        'data cancel', 'dt_cancel', 'data de cancelamento',
        'data cancelado', 'cancelado em'
    ]
    
    for col in df_clientes.columns:
        col_lower = col.lower().strip()
        for possivel in possiveis_colunas_cancel:
            if possivel in col_lower:
                data_cancel_col = col
                break
        if data_cancel_col:
            break
            
    if data_cancel_col is None:
        st.error("❌ Coluna de data de cancelamento não encontrada na base de dados.")
        return

    # 🔑 CACHE: só recalcula se mudou algo relevante
    n_clientes = len(df_clientes)
    n_parcelas = len(df_parcelas) if df_parcelas is not None else 0
    first_id = df_clientes['ID'].iloc[0] if 'ID' in df_clientes.columns and n_clientes > 0 else 0
    last_id = df_clientes['ID'].iloc[-1] if 'ID' in df_clientes.columns and n_clientes > 0 else 0
    
    cache_key = (n_clientes, n_parcelas, first_id, last_id, data_cancel_col)
    
    if (st.session_state.get('_winback_cache_key') == cache_key and 
        st.session_state.get('_winback_cache') is not None):
        df_winback_base = st.session_state._winback_cache
    else:
        # Processar apenas na primeira vez
        df_winback_base = df_clientes.copy()
        df_winback_base[data_cancel_col] = pd.to_datetime(df_winback_base[data_cancel_col], errors='coerce')
        df_winback_base = df_winback_base.dropna(subset=[data_cancel_col])
        
        df_winback_base['status_classificacao'] = classificar_status_serie(df_winback_base.get('STATUS ACESSO', pd.Series()))
        df_winback_base = df_winback_base[df_winback_base['status_classificacao'] == 'Desativado'].copy()
        
        if df_winback_base.empty:
            st.info("ℹ️ Nenhum cliente desativado encontrado na base.")
            return
        
        data_ref = datetime.now().replace(tzinfo=None)
        df_winback_base['dias_desde_cancelamento'] = (data_ref - df_winback_base[data_cancel_col]).dt.days
        df_winback_base['meses_desde_cancelamento'] = (df_winback_base['dias_desde_cancelamento'] / 30.44).round(1)
        
        with st.spinner("🔄 Calculando Health Score dos clientes (primeira vez pode demorar)..."):
            df_winback_base = calcular_health_score_clientes(df_winback_base, df_parcelas, df_clientes)
            st.session_state._winback_cache = df_winback_base
            st.session_state._winback_cache_key = cache_key
    
    df_winback = df_winback_base.copy()
    
    # ========== INTERFACE DE SELEÇÃO ==========
    st.markdown("### 📅 Selecione a Janela de Tempo para Recuperação")
    
    opcoes_faixa = {
        "6 meses a 1 ano (180 a 365 dias)": (180, 365),
        "10 meses a 1 ano (300 a 365 dias)": (300, 365),
        "1 a 2 anos (365 a 730 dias)": (365, 730),
        "2 a 3 anos (730 a 1095 dias)": (730, 1095),
        "Mais de 3 anos (1095+ dias)": (1095, 99999),
        "Personalizado": None
    }
    
    faixa_selecionada = st.selectbox(
        "Escolha uma faixa de tempo desde o cancelamento:",
        options=list(opcoes_faixa.keys()),
        key="winback_faixa_tempo"
    )
    
    if faixa_selecionada == "Personalizado":
        col1, col2 = st.columns(2)
        with col1:
            min_dias = st.number_input("Mínimo de dias desde o cancelamento:", min_value=0, value=180, step=30)
        with col2:
            max_dias = st.number_input("Máximo de dias desde o cancelamento:", min_value=0, value=365, step=30)
    else:
        min_dias, max_dias = opcoes_faixa[faixa_selecionada]

    df_export = df_winback[
        (df_winback['dias_desde_cancelamento'] >= min_dias) & 
        (df_winback['dias_desde_cancelamento'] <= max_dias)
    ].copy()
    
    if df_export.empty:
        st.warning("⚠️ Nenhum cliente encontrado nesta faixa de tempo.")
        return
    
    # ========== FILTRO POR PERFIL ==========
    st.markdown("### 🎯 Filtro por Perfil de Cliente (Health Score)")
    
    col_perfil1, col_perfil2 = st.columns([2, 1])
    
    with col_perfil1:
        perfis_disponiveis = sorted(df_export['perfil_cliente'].dropna().unique().tolist())
        
        perfis_selecionados = st.multiselect(
            "Selecione os perfis que deseja incluir na campanha:",
            options=perfis_disponiveis,
            default=["🟢 Saudável"] if "🟢 Saudável" in perfis_disponiveis else perfis_disponiveis,
            key="winback_perfis"
        )
    
    with col_perfil2:
        st.markdown("<br>", unsafe_allow_html=True)
        incluir_sem_historico = st.checkbox(
            "Incluir clientes sem histórico",
            value=False,
            key="winback_sem_historico"
        )
    
    if perfis_selecionados:
        df_export = df_export[df_export['perfil_cliente'].isin(perfis_selecionados)].copy()
    
    if not incluir_sem_historico:
        df_export = df_export[df_export['perfil_cliente'] != '🟡 Médio (Sem Histórico)'].copy()
    
    if df_export.empty:
        st.warning("⚠️ Nenhum cliente atende aos filtros de perfil selecionados.")
        return
    
    # ========== RESUMO ==========
    st.markdown("### 📊 Resumo dos Clientes Encontrados")
    
    col_res1, col_res2, col_res3, col_res4 = st.columns(4)
    
    total_encontrado = len(df_export)
    qtd_saudavel = len(df_export[df_export['perfil_cliente'] == '🟢 Saudável'])
    qtd_medio = len(df_export[df_export['perfil_cliente'] == '🟡 Médio'])
    qtd_ruim = len(df_export[df_export['perfil_cliente'] == '🔴 Ruim'])
    
    with col_res1:
        st.metric("👥 Total Encontrado", total_encontrado)
    with col_res2:
        st.metric("🟢 Saudáveis", qtd_saudavel)
    with col_res3:
        st.metric("🟡 Médios", qtd_medio)
    with col_res4:
        st.metric("🔴 Ruins", qtd_ruim)
    
    if total_encontrado > 0:
        col_pie1, col_pie2 = st.columns([1, 1])
        
        with col_pie1:
            df_pizza = pd.DataFrame({
                'Perfil': ['🟢 Saudável', '🟡 Médio', '🔴 Ruim'],
                'Quantidade': [qtd_saudavel, qtd_medio, qtd_ruim]
            })
            df_pizza = df_pizza[df_pizza['Quantidade'] > 0]
            
            if not df_pizza.empty:
                fig_pizza = px.pie(
                    df_pizza,
                    values='Quantidade',
                    names='Perfil',
                    title='🎯 Distribuição por Perfil',
                    hole=0.4,
                    color='Perfil',
                    color_discrete_map={
                        '🟢 Saudável': '#2ecc71',
                        '🟡 Médio': '#f39c12',
                        '🔴 Ruim': '#e74c3c'
                    }
                )
                fig_pizza.update_traces(textinfo='percent+label+value')
                fig_pizza.update_layout(height=350)
                st.plotly_chart(fig_pizza, use_container_width=True, config={'displayModeBar': False})
        
        with col_pie2:
            if 'meses_desde_cancelamento' in df_export.columns:
                df_hist = df_export.copy()
                df_hist['faixa_meses'] = pd.cut(
                    df_hist['meses_desde_cancelamento'],
                    bins=[0, 6, 12, 18, 24, 36, 999],
                    labels=['0-6m', '6-12m', '12-18m', '18-24m', '24-36m', '36m+']
                )
                hist_meses = df_hist.groupby('faixa_meses', observed=True).size().reset_index(name='quantidade')
                
                fig_hist = px.bar(
                    hist_meses,
                    x='faixa_meses',
                    y='quantidade',
                    title='📅 Distribuição por Tempo Cancel.',
                    color='quantidade',
                    color_continuous_scale='Blues',
                    text='quantidade'
                )
                fig_hist.update_traces(texttemplate='%{text}', textposition='outside')
                fig_hist.update_layout(height=350, coloraxis_showscale=False)
                st.plotly_chart(fig_hist, use_container_width=True, config={'displayModeBar': False})
    
    st.markdown("---")
    
    col1, col2, col3 = st.columns(3)
    with col1:
        st.metric("👥 Total de Clientes", len(df_export))
    with col2:
        media_meses = df_export['meses_desde_cancelamento'].mean()
        st.metric("📅 Média de Meses", f"{media_meses:.1f} meses")
    with col3:
        total_cond = df_export['CONDOMANIO'].nunique() if 'CONDOMANIO' in df_export.columns else 0
        st.metric("🏢 Condomínios", total_cond)
    
    # ========== TABELA PREVIEW ==========
    st.markdown("### 📋 Preview dos Clientes para Win-Back")
    
    colunas_exibir = [
        'RAZAO SOCIAL/NOME', 'CONDOMANIO', 
        data_cancel_col, 'meses_desde_cancelamento',
        'parcelas_pagas', 'percentual_atraso', 
        'health_score', 'perfil_cliente', 'recomendacao'
    ]
    colunas_existentes = [c for c in colunas_exibir if c in df_export.columns]
    
    if colunas_existentes:
        st.dataframe(
            df_export[colunas_existentes].sort_values('health_score', ascending=False).head(200),
            use_container_width=True,
            height=400,
            column_config={
                data_cancel_col: st.column_config.DateColumn("Data Cancelamento", format="DD/MM/YYYY"),
                'meses_desde_cancelamento': st.column_config.NumberColumn("Meses", format="%.1f"),
                'parcelas_pagas': st.column_config.NumberColumn("Pagas", format="%d"),
                'percentual_atraso': st.column_config.NumberColumn("% Atraso", format="%.1f%%"),
                'health_score': st.column_config.ProgressColumn("Health", format="%.1f", min_value=0, max_value=100),
            }
        )
    
    # ========== EXPORTAÇÃO ==========
    st.markdown("---")
    st.subheader("📎 Exportar Dados")
    
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        df_export_export = df_export.copy()
        cols_remover = ['status_classificacao', 'score_pagamento', 'score_atraso', 'score_tempo']
        for col in cols_remover:
            if col in df_export_export.columns:
                df_export_export = df_export_export.drop(columns=[col])
        
        df_export_export.to_excel(writer, sheet_name='WinBack_Clientes', index=False)
        
        df_saudaveis = df_export[df_export['perfil_cliente'] == '🟢 Saudável'].copy()
        if not df_saudaveis.empty:
            for col in cols_remover:
                if col in df_saudaveis.columns:
                    df_saudaveis = df_saudaveis.drop(columns=[col])
            df_saudaveis.to_excel(writer, sheet_name='Apenas_Saudaveis', index=False)
        
        if 'CONDOMANIO' in df_export.columns:
            resumo_cond = df_export.groupby(['CONDOMANIO', 'perfil_cliente']).size().unstack(fill_value=0)
            resumo_cond['Total'] = resumo_cond.sum(axis=1)
            resumo_cond = resumo_cond.sort_values('Total', ascending=False).reset_index()
            resumo_cond.to_excel(writer, sheet_name='Resumo_Por_Condominio', index=False)
        
        resumo_perfil = df_export.groupby('perfil_cliente').agg(
            total=('perfil_cliente', 'count'),
            media_health_score=('health_score', 'mean'),
            media_meses=('meses_desde_cancelamento', 'mean')
        ).round(2).reset_index()
        resumo_perfil.to_excel(writer, sheet_name='Resumo_Por_Perfil', index=False)
        
    output.seek(0)
    
    st.download_button(
        "📥 Exportar Lista de Clientes para Win-Back",
        output,
        f"winback_clientes_{min_dias}_{max_dias}_dias_{datetime.now().strftime('%Y%m%d_%H%M')}.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        use_container_width=True,
        type="primary"
    )
    
    # ========== INSIGHTS ==========
    st.markdown("---")
    st.subheader("💡 Insights da Campanha")
    
    insights = []
    
    if total_encontrado > 0:
        percentual_saudavel = qtd_saudavel / total_encontrado * 100
        if percentual_saudavel >= 50:
            insights.append(f"✅ **{percentual_saudavel:.0f}%** dos clientes são saudáveis — Excelente potencial!")
        elif percentual_saudavel >= 25:
            insights.append(f"🟡 Apenas **{percentual_saudavel:.0f}%** são saudáveis — Avalie bem o custo.")
        else:
            insights.append(f"🚨 Apenas **{percentual_saudavel:.0f}%** são saudáveis — Considere ampliar janela.")
    
    if 'health_score' in df_export.columns:
        media_score = df_export['health_score'].mean()
        insights.append(f"📊 **Health Score médio:** {media_score:.1f} pontos (de 100)")
    
    if 'percentual_atraso' in df_export.columns:
        media_atraso = df_export['percentual_atraso'].mean()
        insights.append(f"⚠️ **% Atraso médio:** {media_atraso:.1f}%")
    
    for insight in insights:
        st.info(insight)


# ==================== CONEXÃO MONGODB ====================
@st.cache_resource
def init_mongo():
    """Inicializa conexão MongoDB com índices"""
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
        
        criar_indices_mongodb(db)
        
        return db
    except (ServerSelectionTimeoutError, ConnectionFailure) as e:
        st.error(f"❌ Falha ao conectar ao MongoDB:\n`{type(e).__name__}: {e}`")
        st.stop()
    except Exception as e:
        st.error(f"❌ Erro inesperado ao conectar: {type(e).__name__}: {e}")
        st.stop()


def criar_indices_mongodb(db):
    """Cria índices para acelerar consultas"""
    try:
        db["condominios_relatorios"].create_index([("_import_batch", ASCENDING)])
        db["condominios_relatorios"].create_index([("module", ASCENDING)])
        db["condominios_relatorios"].create_index([("CONDOMANIO", ASCENDING)])
        db["condominios_relatorios"].create_index([("ID", ASCENDING)])
        db["condominios_meta"].create_index([("timestamp", DESCENDING)])
        db["condominios_meta"].create_index([("batch_id", ASCENDING)])
        db["condominios_meta"].create_index([("module", ASCENDING)])
        db["prospeccao_condominios"].create_index([("NOME", ASCENDING)])
        db["prospeccao_condominios"].create_index([("ACOMPANHAMENTO", ASCENDING)])
        db["prospeccao_condominios"].create_index([("_import_batch", ASCENDING)])
        db["prospeccao_meta"].create_index([("timestamp", DESCENDING)])
    except Exception as e:
        print(f"⚠️ Aviso ao criar índices: {e}")


def get_gridfs():
    """Retorna instância do GridFS"""
    db = init_mongo()
    return GridFS(db)


# ==================== FUNÇÕES GRIDFS ====================
def save_excel_to_gridfs(file_obj, module_name="condominios"):
    """Salva arquivo Excel no GridFS"""
    try:
        fs = get_gridfs()
        file_id = fs.put(
            file_obj.getvalue(),
            filename=file_obj.name,
            module=module_name,
            upload_date=datetime.now().replace(tzinfo=None),
            content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )
        return str(file_id)
    except Exception as e:
        st.error(f"❌ Erro ao salvar no GridFS: {str(e)}")
        return None


def load_excel_from_gridfs(file_id):
    """Carrega arquivo Excel do GridFS"""
    try:
        fs = get_gridfs()
        file_data = fs.get(ObjectId(file_id))
        return file_data
    except Exception as e:
        st.error(f"❌ Arquivo não encontrado no GridFS: {str(e)}")
        return None


# ==================== FUNÇÕES UTILITÁRIAS ====================
def limpar_valor_data(valor):
    """Limpa e padroniza valores de data"""
    if pd.isna(valor) or valor is None:
        return None
    
    if isinstance(valor, str):
        valor_limpo = valor.strip()
        if valor_limpo in ["", "00/00/0000", "0", " ", "nan", "NaT", "null", "NULL", "NaTType"]:
            return None
        try:
            valor = pd.to_datetime(valor_limpo, errors='coerce')
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
        try:
            if valor.tzinfo is not None:
                return valor.replace(tzinfo=None)
            return valor
        except:
            return None
    
    return None


def converter_dataframe_dates(df):
    """Conversão vetorial de datas com tratamento seguro de NaT"""
    df = df.copy()
    _PALAVRAS_DATA = {'data', 'date', 'cadastro', 'ativacao', 'cancelamento',
                      'nascimento', 'renovacao', 'vencimento', 'credito'}

    for col in df.columns:
        col_lower = col.lower()
        eh_data = any(p in col_lower for p in _PALAVRAS_DATA)

        if eh_data or pd.api.types.is_datetime64_any_dtype(df[col]):
            s = pd.to_datetime(df[col], errors='coerce')
            if s.dt.tz is not None:
                s = s.dt.tz_localize(None)
            py_dates = s.dt.to_pydatetime()
            mask_nat = s.isna().values
            result = np.empty(len(s), dtype=object)
            result[:] = py_dates
            result[mask_nat] = None
            df[col] = result

    return df


def safe_mongo_docs(df):
    """Converte DataFrame para lista de dicts seguros para o MongoDB."""
    import math

    df = df.copy()
    df = df.replace([np.inf, -np.inf], np.nan)

    for col in df.columns:
        if pd.api.types.is_datetime64_any_dtype(df[col]):
            s = df[col]
            if s.dt.tz is not None:
                s = s.dt.tz_localize(None)
            py_dates = s.dt.to_pydatetime()
            mask_nat = s.isna().values
            result = np.empty(len(s), dtype=object)
            result[:] = py_dates
            result[mask_nat] = None
            df[col] = result

    records = df.to_dict('records')

    _NAT = pd.NaT
    safe_records = []
    for doc in records:
        safe_doc = {}
        for k, v in doc.items():
            if v is None:
                safe_doc[k] = None
            elif v is _NAT:
                safe_doc[k] = None
            elif isinstance(v, float) and (math.isnan(v) or math.isinf(v)):
                safe_doc[k] = None
            elif isinstance(v, pd.Timestamp):
                try:
                    safe_doc[k] = v.to_pydatetime().replace(tzinfo=None)
                except Exception:
                    safe_doc[k] = None
            else:
                safe_doc[k] = v
        safe_records.append(safe_doc)

    return safe_records


def formatar_numero_br(valor, decimais=0):
    """Formata número para padrão brasileiro"""
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


def formatar_moeda_br(valor):
    """Formata moeda para padrão brasileiro"""
    if pd.isna(valor) or valor is None:
        return "R$ 0,00"
    try:
        return f"R$ {formatar_numero_br(valor, 2)}"
    except:
        return f"R$ {valor}"


def safe_strftime(value, fmt="%d/%m/%Y %H:%M"):
    """Converte data para string com segurança"""
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


# ==================== FUNÇÕES DE BANCO DE DADOS ====================
def save_condominio_data_enhanced(db, df_clientes, df_condominios, df_parcelas, metadata):
    """Versão melhorada do save_condominio_data"""
    collection_clientes = db["condominios_relatorios"]
    collection_meta = db["condominios_meta"]
    
    batch_id = metadata["batch_id"]
    module = metadata.get("module", "condominios")
    
    count_clientes_del = collection_clientes.delete_many({
        "_import_batch": {"$ne": batch_id},
        "module": module
    }).deleted_count
    
    count_meta_del = collection_meta.delete_many({
        "batch_id": {"$ne": batch_id},
        "module": module
    }).deleted_count
    
    if count_clientes_del > 0 or count_meta_del > 0:
        print(f"🧹 Limpeza: {count_clientes_del} clientes e {count_meta_del} metadados antigos removidos.")
    
    df_clientes_limpo = converter_dataframe_dates(df_clientes)
    df_clientes_limpo["_import_timestamp"] = datetime.now().replace(tzinfo=None)
    df_clientes_limpo["_import_batch"] = batch_id
    df_clientes_limpo["source_file_id"] = metadata["source_file_id"]
    df_clientes_limpo["module"] = module
    
    docs = safe_mongo_docs(df_clientes_limpo)
    
    if docs:
        _BATCH = 5000
        for i in range(0, len(docs), _BATCH):
            collection_clientes.insert_many(docs[i:i + _BATCH], ordered=False)
    
    if df_parcelas is not None and not df_parcelas.empty:
        df_parcelas_limpo = converter_dataframe_dates(df_parcelas)
        df_parcelas_limpo["_import_timestamp"] = datetime.now().replace(tzinfo=None)
        df_parcelas_limpo["_import_batch"] = batch_id
        df_parcelas_limpo["source_file_id"] = metadata["source_file_id"]
        df_parcelas_limpo["module"] = module
        
        parcelas_docs = safe_mongo_docs(df_parcelas_limpo)
        if parcelas_docs:
            _BATCH = 5000
            for i in range(0, len(parcelas_docs), _BATCH):
                collection_clientes.insert_many(parcelas_docs[i:i + _BATCH], ordered=False)
    
    condominios_records = safe_mongo_docs(df_condominios)
    metadata["condominios"] = condominios_records
    
    if df_parcelas is not None and not df_parcelas.empty:
        metadata["has_parcelas"] = True
        metadata["total_parcelas"] = len(df_parcelas)
    else:
        metadata["has_parcelas"] = False
    
    metadata["module"] = module
    
    collection_meta.insert_one(metadata)
    
    return True


def carregar_dados_mais_recentes(db):
    """
    Carrega automaticamente os dados mais recentes do MongoDB.
    ⚡ OTIMIZADO: usa pd.DataFrame(list(cursor)) direto, com batch_size.
    """
    try:
        latest_meta = db["condominios_meta"].find(
            {"module": "condominios"}
        ).sort("timestamp", -1).limit(1)
        
        meta_list = list(latest_meta)
        
        if not meta_list:
            return False
        
        meta = meta_list[0]
        batch_id = meta.get('batch_id')
        source_file_id = meta.get('source_file_id')
        file_name = meta.get('filename', 'Arquivo carregado')
        
        projection = {'_id': 0, '_import_timestamp': 0, '_import_batch': 0,
                      'source_file_id': 0, 'module': 0}
        
        # ⚡ OTIMIZADO: list(cursor) direto com batch_size
        cursor_clientes = db["condominios_relatorios"].find(
            {"_import_batch": batch_id, "module": "condominios"},
            projection
        ).batch_size(5000)
        
        df_all = pd.DataFrame(list(cursor_clientes))
        
        if df_all.empty:
            return False
        
        if 'CONDOMANIO' in df_all.columns:
            df_clientes = df_all[df_all['CONDOMANIO'].notna()].copy()
        else:
            df_clientes = pd.DataFrame()
        
        if 'DATA DO VENCIMENTO' in df_all.columns:
            df_parcelas = df_all[df_all['DATA DO VENCIMENTO'].notna()].copy()
        else:
            df_parcelas = pd.DataFrame()
        
        del df_all
        
        df_condominios = pd.DataFrame(meta.get("condominios", []))
        
        df_clientes = converter_dataframe_dates(df_clientes)
        df_condominios = converter_dataframe_dates(df_condominios)
        if not df_parcelas.empty:
            df_parcelas = converter_dataframe_dates(df_parcelas)
        
        if "CONDOMANIO" in df_clientes.columns:
            df_clientes["CONDOMANIO"] = pd.to_numeric(df_clientes["CONDOMANIO"], errors="coerce").fillna(0).astype(int)
        if "ID" in df_condominios.columns:
            df_condominios["ID"] = pd.to_numeric(df_condominios["ID"], errors="coerce").fillna(0).astype(int)
        if "Apartamentos" in df_condominios.columns:
            df_condominios["Apartamentos"] = pd.to_numeric(df_condominios["Apartamentos"], errors="coerce").fillna(0).astype(int)
        
        st.session_state.condominios_dados_clientes = df_clientes
        st.session_state.condominios_dados_condominios = df_condominios
        st.session_state.condominios_dados_parcelas = df_parcelas if not df_parcelas.empty else None
        st.session_state.condominios_meta = meta
        st.session_state.condominios_file_id = source_file_id
        st.session_state.condominios_nome_arquivo = file_name
        st.session_state.condominios_processado = True
        
        # 🔑 Limpar cache do winback ao recarregar
        st.session_state._winback_cache = None
        st.session_state._winback_cache_key = None
        
        return True
        
    except Exception as e:
        print(f"❌ Erro ao carregar dados automáticos: {str(e)}")
        return False


def clear_condominio_data(db, batch_id=None, module="condominios"):
    """Limpa dados do banco com filtro por módulo"""
    collection_clientes = db["condominios_relatorios"]
    collection_meta = db["condominios_meta"]
    
    if batch_id:
        result_clientes = collection_clientes.delete_many({"_import_batch": batch_id, "module": module})
        result_meta = collection_meta.delete_many({"batch_id": batch_id, "module": module})
    else:
        result_clientes = collection_clientes.delete_many({"module": module})
        result_meta = collection_meta.delete_many({"module": module})
    
    return result_clientes.deleted_count + result_meta.deleted_count


# ==================== PROCESSAMENTO DE UPLOAD ====================
def processar_upload_condominios(db, uploaded_file):
    """Processa upload de planilha e salva no GridFS + MongoDB"""
    with st.spinner('💾 Salvando arquivo no GridFS...'):
        file_id = save_excel_to_gridfs(uploaded_file, "condominios")
        
        if not file_id:
            st.error("❌ Falha ao salvar arquivo no GridFS")
            return False
        
        st.success(f"📁 Arquivo salvo com ID: {file_id[:8]}...")
    
    with st.spinner('🔄 Processando planilha...'):
        try:
            df_clientes = pd.read_excel(uploaded_file, sheet_name="Dados")
            df_condominios = pd.read_excel(uploaded_file, sheet_name="Condominios")
            
            try:
                df_parcelas = pd.read_excel(uploaded_file, sheet_name="Base Parcelas")
                st.info(f"📋 Aba 'Base Parcelas' encontrada com {len(df_parcelas):,} registros")
            except Exception:
                df_parcelas = pd.DataFrame()
                st.warning("⚠️ Aba 'Base Parcelas' não encontrada.")
            
            df_clientes = df_clientes.replace({pd.NaT: None, np.nan: None})
            df_condominios = df_condominios.replace({pd.NaT: None, np.nan: None})
            if not df_parcelas.empty:
                df_parcelas = df_parcelas.replace({pd.NaT: None, np.nan: None})
            
            if "CONDOMANIO" in df_clientes.columns:
                df_clientes["CONDOMANIO"] = pd.to_numeric(df_clientes["CONDOMANIO"], errors="coerce").fillna(0).astype(int)
            
            if "ID" in df_condominios.columns:
                df_condominios["ID"] = pd.to_numeric(df_condominios["ID"], errors="coerce").fillna(0).astype(int)
            
            if "Apartamentos" in df_condominios.columns:
                df_condominios["Apartamentos"] = pd.to_numeric(df_condominios["Apartamentos"], errors="coerce").fillna(0).astype(int)
            
            if not df_parcelas.empty and "ID" in df_parcelas.columns:
                df_parcelas["ID"] = pd.to_numeric(df_parcelas["ID"], errors="coerce").fillna(0).astype(int)
            
            df_clientes = converter_dataframe_dates(df_clientes)
            df_condominios = converter_dataframe_dates(df_condominios)
            if not df_parcelas.empty:
                df_parcelas = converter_dataframe_dates(df_parcelas)
            
            batch_id = f"batch_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
            metadata = {
                "batch_id": batch_id,
                "source_file_id": file_id,
                "filename": uploaded_file.name,
                "timestamp": datetime.now().replace(tzinfo=None),
                "total_clientes": len(df_clientes),
                "total_condominios": len(df_condominios),
                "total_parcelas": len(df_parcelas) if not df_parcelas.empty else 0,
                "module": "condominios"
            }
            
            if save_condominio_data_enhanced(db, df_clientes, df_condominios, df_parcelas, metadata):
                st.session_state.condominios_dados_clientes = df_clientes
                st.session_state.condominios_dados_condominios = df_condominios
                st.session_state.condominios_dados_parcelas = df_parcelas if not df_parcelas.empty else None
                st.session_state.condominios_meta = metadata
                st.session_state.condominios_file_id = file_id
                st.session_state.condominios_nome_arquivo = uploaded_file.name
                st.session_state.condominios_processado = True
                
                # 🔑 Limpar cache do winback
                st.session_state._winback_cache = None
                st.session_state._winback_cache_key = None
                
                st.success(f"✅ {len(df_clientes):,} clientes, {len(df_condominios):,} condomínios e {len(df_parcelas):,} parcelas processados!")
                st.balloons()
                return True
            else:
                st.error("❌ Falha ao salvar dados processados")
                return False
                
        except Exception as e:
            st.error(f"❌ Erro no processamento: {str(e)}")
            with st.expander("🔍 Detalhes técnicos"):
                st.code(traceback.format_exc())
            return False


# ==================== FUNÇÕES DE ANÁLISE ====================
def classificar_status_serie(serie: pd.Series) -> pd.Series:
    """Versão vetorizada de classificação de status"""
    if serie.empty:
        return pd.Series()
    
    s = serie.fillna("").astype(str).str.lower().str.strip()
    conditions = [
        s.str.contains("ativo") & ~s.str.contains("atraso") & ~s.str.contains("bloqueio") & ~s.str.contains("financeiro"),
        s.str.contains("atraso") | s.str.contains("financeiro"),
        s.str.contains("bloqueio") | s.str.contains("autom"),
        s.str.contains("desativado") | s.str.contains("cancelado"),
    ]
    choices = ["Ativo", "Em Atraso", "Bloqueio Automático", "Desativado"]
    return pd.Series(np.select(conditions, choices, default="Outros"), index=serie.index)


def identificar_coluna_data(df_clientes):
    """Identifica a coluna de data de cadastro no DataFrame de clientes"""
    possiveis_nomes_data = [
        'data cadastro', 'data_cadastro', 'datacadastro', 
        'cadastro', 'data de cadastro', 'data_cadastro_cliente',
        'criacao', 'data_criacao', 'created_at', 'created',
        'data_cadastro_cliente', 'dt_cadastro'
    ]
    
    for col in df_clientes.columns:
        col_lower = col.lower().strip()
        for possivel in possiveis_nomes_data:
            if possivel in col_lower:
                return col
    
    for col in df_clientes.columns:
        col_lower = col.lower()
        if 'data' in col_lower or 'cadastro' in col_lower or 'criacao' in col_lower:
            return col
    
    return None


def classificar_status(status):
    """Classifica o status do cliente"""
    if pd.isna(status):
        return "Outros"
    status_lower = str(status).lower().strip()
    if "ativo" in status_lower and "atraso" not in status_lower and "bloqueio" not in status_lower:
        return "Ativo"
    elif "atraso" in status_lower or "financeiro" in status_lower:
        return "Em Atraso"
    elif "bloqueio" in status_lower or "automático" in status_lower or "automatico" in status_lower:
        return "Bloqueio Automático"
    elif "desativado" in status_lower or "cancelado" in status_lower:
        return "Desativado"
    return "Outros"


def gerar_dashboard_principal(df_clientes, df_condominios, modo_ativos="somente_ativos"):
    """Gera dashboard principal otimizado"""
    if df_clientes is None or df_condominios is None:
        return pd.DataFrame()
    
    if "CONDOMANIO" not in df_clientes.columns or "ID" not in df_condominios.columns:
        return pd.DataFrame()
    
    df_clientes = df_clientes.copy()
    df_condominios = df_condominios.copy()
    
    df_condominios["ID"] = pd.to_numeric(df_condominios["ID"], errors="coerce").fillna(0).astype(int)
    df_clientes["CONDOMANIO"] = pd.to_numeric(df_clientes["CONDOMANIO"], errors="coerce").fillna(0).astype(int)
    df_condominios["Apartamentos"] = pd.to_numeric(df_condominios["Apartamentos"], errors="coerce").fillna(0).astype(int)
    
    df_clientes["status_classificacao"] = classificar_status_serie(df_clientes["STATUS ACESSO"])
    
    clientes_agg = df_clientes.groupby("CONDOMANIO").agg(
        total_clientes=("CONDOMANIO", "count"),
        ativos_puros=("status_classificacao", lambda x: (x == "Ativo").sum()),
        em_atraso=("status_classificacao", lambda x: (x == "Em Atraso").sum()),
        bloqueio_automatico=("status_classificacao", lambda x: (x == "Bloqueio Automático").sum()),
        desativados=("status_classificacao", lambda x: (x == "Desativado").sum()),
        outros=("status_classificacao", lambda x: (x == "Outros").sum())
    ).reset_index()
    
    if modo_ativos == "todos_ativos":
        clientes_agg["ativos"] = clientes_agg["ativos_puros"] + clientes_agg["em_atraso"] + clientes_agg["bloqueio_automatico"]
    else:
        clientes_agg["ativos"] = clientes_agg["ativos_puros"]
    
    clientes_agg["total_ocupados"] = clientes_agg["ativos_puros"] + clientes_agg["em_atraso"] + clientes_agg["bloqueio_automatico"]
    
    df_merged = df_condominios[["ID", "Condomínio", "Apartamentos", "Região", "Data cadastro"]].merge(
        clientes_agg, left_on="ID", right_on="CONDOMANIO", how="left"
    )
    
    cols_fill = ["ativos", "ativos_puros", "em_atraso", "bloqueio_automatico", "desativados", "outros", "total_ocupados"]
    for col in cols_fill:
        if col in df_merged.columns:
            df_merged[col] = df_merged[col].fillna(0).astype(int)
    
    apt_safe = df_merged["Apartamentos"].replace(0, np.nan)
    df_merged["percentual_ativos"] = (df_merged["ativos"] / apt_safe * 100).round(2)
    df_merged["total_atrasos"] = df_merged["em_atraso"] + df_merged["bloqueio_automatico"]
    ocupados_safe = df_merged["total_ocupados"].replace(0, np.nan)
    df_merged["percentual_atraso"] = (df_merged["total_atrasos"] / ocupados_safe * 100).round(2).fillna(0)
    df_merged["capacidade_exploracao"] = ((apt_safe - df_merged["total_ocupados"]) / apt_safe * 100).round(2)
    
    dashboard_final = df_merged[[
        "Região", "Condomínio", "Data cadastro", "ativos", "percentual_ativos",
        "total_atrasos", "percentual_atraso", "capacidade_exploracao",
        "Apartamentos", "desativados", "total_ocupados", "ativos_puros", "em_atraso", "bloqueio_automatico"
    ]].copy()
    
    dashboard_final.columns = [
        "Região", "Condomínio", "Data de Implantação", "Qtd Ativos",
        "% Ativos (Penetração)", "Total Atrasos", "% Atraso",
        "% Capacidade de Exploração", "Total Apartamentos", "Desativados", "Total Ocupados",
        "Ativos Puros", "Em Atraso", "Bloqueio Automático"
    ]
    
    return dashboard_final.sort_values(["Região", "Condomínio"]).reset_index(drop=True)


def calcular_penetracao(df_clientes, df_condominios):
    """Calcula taxa de penetração otimizada"""
    df_clientes = df_clientes.copy()
    df_condominios = df_condominios.copy()
    
    df_clientes["CONDOMANIO"] = pd.to_numeric(df_clientes["CONDOMANIO"], errors="coerce").fillna(0).astype(int)
    df_condominios["ID"] = pd.to_numeric(df_condominios["ID"], errors="coerce").fillna(0).astype(int)
    
    df_clientes["status_classificacao"] = classificar_status_serie(df_clientes["STATUS ACESSO"])
    clientes_ativos = df_clientes[df_clientes["status_classificacao"] == "Ativo"]
    
    clientes_por_cond = clientes_ativos.groupby("CONDOMANIO").size().reset_index(name="clientes_ativos")
    
    cols_merge = ["ID", "Condomínio", "Apartamentos", "Região", "Principal Concorrente"]
    cols_existentes = [c for c in cols_merge if c in df_condominios.columns]
    
    df_merged = clientes_por_cond.merge(
        df_condominios[cols_existentes],
        left_on="CONDOMANIO", right_on="ID", how="right"
    )
    
    df_merged["Apartamentos"] = pd.to_numeric(df_merged["Apartamentos"], errors="coerce").fillna(0)
    df_merged["clientes_ativos"] = df_merged["clientes_ativos"].fillna(0)
    df_merged["taxa_penetracao"] = (df_merged["clientes_ativos"] / df_merged["Apartamentos"].replace(0, np.nan) * 100).round(2)
    df_merged["Apartamentos"] = df_merged["Apartamentos"].fillna(0).astype(int)
    
    taxa = df_merged["taxa_penetracao"]
    df_merged["classificacao"] = np.select(
        [taxa >= 50, taxa >= 25],
        ["🟢 Dominado", "🟡 Em Crescimento"],
        default="🔴 Baixa Presença"
    )
    df_merged["classificacao"] = df_merged["classificacao"].where(taxa.notna(), "Baixa Presença")
    return df_merged.sort_values("taxa_penetracao", ascending=False)


def analisar_inadimplencia_por_status(df_clientes, df_condominios, incluir_desativados=True):
    """Analisa inadimplência baseada na coluna FINANCEIRO EM ATRASO"""
    df_clientes = df_clientes.copy()
    df_condominios = df_condominios.copy()
    
    df_clientes["CONDOMANIO"] = pd.to_numeric(df_clientes["CONDOMANIO"], errors="coerce").fillna(0).astype(int)
    df_condominios["ID"] = pd.to_numeric(df_condominios["ID"], errors="coerce").fillna(0).astype(int)
    
    if not incluir_desativados:
        df_clientes = df_clientes[~df_clientes["STATUS ACESSO"].str.lower().str.contains("desativado|cancelado", na=False)].copy()
    
    s = df_clientes["FINANCEIRO EM ATRASO"].fillna("").astype(str).str.strip().str.lower()
    _em_dia_vals = {"", "00/00/0000", "0", "nan", "nat", "none", "null"}
    df_clientes["situacao_inadimplencia"] = np.where(s.isin(_em_dia_vals), "Em Dia", "Em Atraso")
    
    inadimplencia = df_clientes.groupby(["CONDOMANIO", "situacao_inadimplencia"]).size().unstack(fill_value=0)
    
    if "Em Atraso" not in inadimplencia.columns:
        inadimplencia["Em Atraso"] = 0
    if "Em Dia" not in inadimplencia.columns:
        inadimplencia["Em Dia"] = 0
    
    total_clientes = inadimplencia["Em Atraso"] + inadimplencia["Em Dia"]
    inadimplencia["taxa_inadimplencia"] = (inadimplencia["Em Atraso"] / total_clientes.replace(0, np.nan) * 100).round(2).fillna(0)
    inadimplencia["total_clientes"] = total_clientes
    inadimplencia["total_inadimplentes"] = inadimplencia["Em Atraso"]
    
    cols_merge = ["ID", "Condomínio", "Região", "Apartamentos"]
    cols_existentes = [c for c in cols_merge if c in df_condominios.columns]
    
    result = inadimplencia.reset_index().merge(
        df_condominios[cols_existentes], 
        left_on="CONDOMANIO", right_on="ID", how="right"
    )
    
    result["taxa_inadimplencia"] = result["taxa_inadimplencia"].fillna(0)
    result["total_clientes"] = result["total_clientes"].fillna(0).astype(int)
    result["total_inadimplentes"] = result["total_inadimplentes"].fillna(0).astype(int)
    result["Em Atraso"] = result["Em Atraso"].fillna(0).astype(int)
    result["Em Dia"] = result["Em Dia"].fillna(0).astype(int)
    
    return result.sort_values("taxa_inadimplencia", ascending=False).reset_index(drop=True)


def analisar_inadimplencia_por_parcelas(df_clientes, df_condominios, df_parcelas, data_referencia=None):
    """Analisa inadimplência REAL baseada na aba 'Base Parcelas'"""
    if df_parcelas is None or df_parcelas.empty:
        return pd.DataFrame(), pd.DataFrame()
    
    if data_referencia is None:
        data_referencia = datetime.now().replace(tzinfo=None)
    
    df_parcelas = df_parcelas.copy()
    df_clientes = df_clientes.copy()
    df_condominios = df_condominios.copy()
    
    df_clientes["ID"] = pd.to_numeric(df_clientes["ID"], errors="coerce").fillna(0).astype(int)
    df_parcelas["ID"] = pd.to_numeric(df_parcelas["ID"], errors="coerce").fillna(0).astype(int)
    df_condominios["ID"] = pd.to_numeric(df_condominios["ID"], errors="coerce").fillna(0).astype(int)
    
    df_parcelas["DATA DO VENCIMENTO"] = pd.to_datetime(df_parcelas["DATA DO VENCIMENTO"], errors='coerce')
    df_parcelas["STATUS_NORMALIZADO"] = df_parcelas["STATUS"].str.upper().str.strip()
    
    parcelas_vencidas = df_parcelas[
        (df_parcelas["DATA DO VENCIMENTO"] < data_referencia) &
        (df_parcelas["STATUS_NORMALIZADO"] == "A RECEBER")
    ].copy()
    
    clientes_inadimplentes = set(parcelas_vencidas["ID"].unique())
    df_clientes["inadimplente_por_parcelas"] = df_clientes["ID"].apply(lambda x: x in clientes_inadimplentes)
    
    soma_atraso = parcelas_vencidas.groupby("ID")["VALOR"].sum().to_dict()
    df_clientes["total_em_atraso"] = df_clientes["ID"].map(soma_atraso).fillna(0)
    
    count_parcelas = parcelas_vencidas.groupby("ID").size().to_dict()
    df_clientes["parcelas_vencidas"] = df_clientes["ID"].map(count_parcelas).fillna(0).astype(int)
    
    df_cliente_cond = df_clientes[["ID", "CONDOMANIO"]].drop_duplicates()
    
    inad_cond = df_cliente_cond.merge(
        df_clientes[["ID", "inadimplente_por_parcelas", "total_em_atraso", "parcelas_vencidas"]],
        on="ID", how="left"
    )
    
    cond_agg = inad_cond.groupby("CONDOMANIO").agg(
        total_clientes=("ID", "count"),
        total_inadimplentes=("inadimplente_por_parcelas", "sum"),
        valor_total_atraso=("total_em_atraso", "sum"),
        total_parcelas_vencidas=("parcelas_vencidas", "sum")
    ).reset_index()
    
    cond_agg["taxa_inadimplencia"] = (
        cond_agg["total_inadimplentes"] / cond_agg["total_clientes"].replace(0, np.nan) * 100
    ).round(2).fillna(0)
    
    cols_merge = ["ID", "Condomínio", "Região", "Apartamentos"]
    cols_existentes = [c for c in cols_merge if c in df_condominios.columns]
    
    result = cond_agg.merge(
        df_condominios[cols_existentes],
        left_on="CONDOMANIO", right_on="ID", how="right"
    )
    
    result["total_clientes"] = result["total_clientes"].fillna(0).astype(int)
    result["total_inadimplentes"] = result["total_inadimplentes"].fillna(0).astype(int)
    result["valor_total_atraso"] = result["valor_total_atraso"].fillna(0)
    result["total_parcelas_vencidas"] = result["total_parcelas_vencidas"].fillna(0).astype(int)
    result["taxa_inadimplencia"] = result["taxa_inadimplencia"].fillna(0)
    
    return result.sort_values("taxa_inadimplencia", ascending=False).reset_index(drop=True), pd.DataFrame()


def analisar_churn(df_clientes, df_condominios):
    """Análise de churn"""
    df_clientes = df_clientes.copy()
    df_condominios = df_condominios.copy()
    
    df_clientes["CONDOMANIO"] = pd.to_numeric(df_clientes["CONDOMANIO"], errors="coerce").fillna(0).astype(int)
    df_condominios["ID"] = pd.to_numeric(df_condominios["ID"], errors="coerce").fillna(0).astype(int)
    
    df_clientes["status_classificacao"] = classificar_status_serie(df_clientes["STATUS ACESSO"])
    
    status_count = df_clientes.groupby(["CONDOMANIO", "status_classificacao"]).size().unstack(fill_value=0)
    
    ativos = status_count.get("Ativo", 0)
    desativados = status_count.get("Desativado", 0)
    
    total = ativos + desativados
    status_count["churn_rate"] = (desativados / total.replace(0, np.nan) * 100).round(2)
    
    cols_merge = ["ID", "Condomínio", "Região"]
    cols_existentes = [c for c in cols_merge if c in df_condominios.columns]
    
    result = status_count.reset_index().merge(
        df_condominios[cols_existentes], 
        left_on="CONDOMANIO", right_on="ID", how="right"
    )
    result["churn_rate"] = result["churn_rate"].fillna(0)
    result["Ativo"] = result.get("Ativo", 0).fillna(0).astype(int)
    result["Desativado"] = result.get("Desativado", 0).fillna(0).astype(int)
    
    return result.sort_values("churn_rate", ascending=False)


def correlacao_concorrencia(df_penetracao, df_condominios):
    """Analisa correlação com concorrência"""
    if "Principal Concorrente" in df_penetracao.columns:
        conc_stats = df_penetracao.groupby("Principal Concorrente").agg({
            "taxa_penetracao": ["mean", "median", "count"],
            "clientes_ativos": "sum",
            "Apartamentos": "sum"
        }).round(2)
        conc_stats.columns = ["_".join(col).strip() for col in conc_stats.columns.values]
        conc_stats = conc_stats.reset_index()
        conc_stats["penetracao_ponderada"] = (conc_stats["clientes_ativos_sum"] / conc_stats["Apartamentos_sum"].replace(0, np.nan) * 100).round(2)
        return conc_stats.sort_values("penetracao_ponderada", ascending=False)
    return pd.DataFrame()


def analisar_por_zona(df_dashboard):
    """Analisa dados por zona/região"""
    if df_dashboard.empty or "Região" not in df_dashboard.columns:
        return pd.DataFrame()
    
    zona_stats = df_dashboard.groupby("Região").agg(
        total_condominios=("Condomínio", "count"),
        total_apartamentos=("Total Apartamentos", "sum"),
        total_ativos=("Qtd Ativos", "sum"),
        total_em_atraso=("Total Atrasos", "sum"),
        total_desativados=("Desativados", "sum"),
        total_ocupados=("Total Ocupados", "sum"),
        media_penetracao=("% Ativos (Penetração)", "mean"),
        media_atraso=("% Atraso", "mean")
    ).reset_index()
    
    zona_stats["percentual_ativos"] = (zona_stats["total_ativos"] / zona_stats["total_apartamentos"] * 100).round(2)
    zona_stats["percentual_ocupacao"] = (zona_stats["total_ocupados"] / zona_stats["total_apartamentos"] * 100).round(2)
    
    return zona_stats.sort_values("total_apartamentos", ascending=False).reset_index(drop=True)


def calcular_meses_cadastro(data_cadastro, data_ref=None):
    """Calcula meses desde cadastro"""
    if data_ref is None:
        data_ref = datetime.now().replace(tzinfo=None)
    if pd.isna(data_cadastro):
        return None
    delta = data_ref - data_cadastro
    return int(delta.days / 30.44)


def classificar_maturidade(row, meses_limite=18):
    """Classifica maturidade do condomínio"""
    meses = row.get("meses_cadastro")
    ativos = row.get("ativos", 0)
    aptos = row.get("Apartamentos", 0)
    ativos_pct = row.get("percentual_ativos", 0)
    
    if pd.isna(meses):
        if aptos > 0:
            if ativos_pct >= 40:
                return "🟢 Estável (Sem Data Cadastro)"
            elif ativos_pct >= 10:
                return "🟡 Em Desenvolvimento (Sem Data)"
            else:
                return "⚪ Fraco (Sem Data Cadastro)"
        else:
            if ativos >= 50:
                return "Grande (Sem Data/Aptos)"
            elif ativos >= 20:
                return "🟡 Médio (Sem Data/Aptos)"
            elif ativos > 0:
                return "Pequeno (Sem Data/Aptos)"
            else:
                return "⚪ Inativo (Sem Data Cadastro)"
    
    tem_aptos = aptos > 0
    if meses >= meses_limite:
        if tem_aptos:
            if ativos_pct >= 40:
                return "🟢 Maduro Saudável"
            elif ativos_pct >= 15:
                return "Maduro Estagnado"
            else:
                return "Maduro Abandonado"
        else:
            return "Maduro Grande (Sem Aptos)" if ativos >= 50 else \
                   "🟡 Maduro Médio (Sem Aptos)" if ativos >= 20 else \
                   "Maduro Pequeno (Sem Aptos)" if ativos > 0 else "Maduro Inativo (Sem Aptos)"
    elif meses >= 12:
        if tem_aptos:
            if ativos_pct >= 30:
                return "🔵 Intermediário Saudável"
            elif ativos_pct >= 10:
                return "🟡 Intermediário Fraco"
            else:
                return "Intermediário Crítico"
        else:
            return "Intermediário Grande (Sem Aptos)" if ativos >= 30 else \
                   "Intermediário Médio (Sem Aptos)" if ativos >= 10 else "Intermediário Fraco (Sem Aptos)"
    elif meses >= 6:
        if tem_aptos:
            return "Jovem em Crescimento" if ativos_pct >= 20 else "Jovem Fraco"
        else:
            return "Jovem Grande (Sem Aptos)" if ativos >= 20 else "🟡 Jovem Pequeno (Sem Aptos)"
    else:
        return "⚪ Novo Promissor" if ativos > 10 else "⚪ Novo Iniciante"


def preparar_dados_maturidade(df_clientes, df_condominios):
    """Prepara dados para análise de maturidade"""
    df_clientes = df_clientes.copy()
    df_condominios = df_condominios.copy()
    
    df_clientes["CONDOMANIO"] = pd.to_numeric(df_clientes["CONDOMANIO"], errors="coerce").fillna(0).astype(int)
    df_condominios["ID"] = pd.to_numeric(df_condominios["ID"], errors="coerce").fillna(0).astype(int)
    
    data_ref = datetime.now().replace(tzinfo=None)
    df_condominios = df_condominios.copy()
    df_condominios["Apartamentos"] = pd.to_numeric(df_condominios["Apartamentos"], errors="coerce").fillna(0).astype(int)
    df_condominios["Data cadastro"] = df_condominios["Data cadastro"].apply(limpar_valor_data)
    
    df_clientes["status_classificacao"] = classificar_status_serie(df_clientes["STATUS ACESSO"])
    
    clientes_agg = df_clientes.groupby("CONDOMANIO").agg(
        total_clientes=("CONDOMANIO", "count"),
        ativos=("status_classificacao", lambda x: (x == "Ativo").sum()),
        em_atraso=("status_classificacao", lambda x: (x == "Em Atraso").sum()),
        bloqueio_automatico=("status_classificacao", lambda x: (x == "Bloqueio Automático").sum()),
        desativados=("status_classificacao", lambda x: (x == "Desativado").sum()),
    ).reset_index()
    
    df_maturidade = df_condominios[["ID", "Condomínio", "Apartamentos", "Região", "Data cadastro", "Principal Concorrente"]].copy()
    df_maturidade = df_maturidade.merge(clientes_agg, left_on="ID", right_on="CONDOMANIO", how="left")
    
    for col in ["ativos", "em_atraso", "bloqueio_automatico", "desativados", "total_clientes"]:
        df_maturidade[col] = df_maturidade[col].fillna(0).astype(int)
    
    apt_safe = df_maturidade["Apartamentos"].replace(0, np.nan)
    df_maturidade["total_ocupados"] = df_maturidade["ativos"] + df_maturidade["em_atraso"] + df_maturidade["bloqueio_automatico"]
    df_maturidade["percentual_ativos"] = (df_maturidade["ativos"] / apt_safe * 100).round(2).fillna(0)
    df_maturidade["meses_cadastro"] = df_maturidade["Data cadastro"].apply(lambda x: calcular_meses_cadastro(x, data_ref))
    
    return df_maturidade


# ==================== DASHBOARD MEUS ACOMPANHAMENTOS ====================

def render_dashboard_meus_acompanhamentos(df_clientes, df_condominios, df_parcelas, meus_nomes, df_meus_prospeccao):
    """Renderiza dashboard completo com foco nos condomínios de acompanhamento."""
    st.subheader("⭐ Meus Condomínios - Acompanhamento Estratégico")
    
    if not meus_nomes or df_meus_prospeccao is None or df_meus_prospeccao.empty:
        st.warning("⚠️ Nenhum condomínio encontrado em 'Meus Acompanhamentos'.")
        return
    
    df_condominios_filtrados = filtrar_condominios_meus(df_condominios, meus_nomes)
    
    if df_condominios_filtrados.empty:
        st.warning("⚠️ Nenhum dos condomínios de 'Meus Acompanhamentos' foi encontrado na base.")
        return
    
    col1, col2, col3 = st.columns(3)
    with col1:
        st.metric("🏢 Condomínios sob sua responsabilidade", len(df_meus_prospeccao))
    with col2:
        st.metric("📊 Encontrados no relatório", len(df_condominios_filtrados))
    with col3:
        st.metric("📅 Última atualização", datetime.now().strftime("%d/%m/%Y %H:%M"))
    
    st.markdown("---")
    
    dashboard_meus = gerar_dashboard_principal(df_clientes, df_condominios_filtrados, "somente_ativos")
    
    if not dashboard_meus.empty:
        col_m1, col_m2, col_m3, col_m4, col_m5 = st.columns(5)
        with col_m1:
            st.metric("👥 Total Ativos", formatar_numero_br(dashboard_meus["Qtd Ativos"].sum()))
        with col_m2:
            st.metric("⚠️ Em Atraso", formatar_numero_br(dashboard_meus["Total Atrasos"].sum()))
        with col_m3:
            st.metric("🏢 Apartamentos", formatar_numero_br(dashboard_meus["Total Apartamentos"].sum()))
        with col_m4:
            st.metric("📈 Penetração Média", f"{dashboard_meus['% Ativos (Penetração)'].mean():.1f}%")
        with col_m5:
            st.metric("🎯 Potencial Médio", f"{dashboard_meus['% Capacidade de Exploração'].mean():.1f}%")
        
        st.markdown("---")
        
        df_prospeccao_info = df_meus_prospeccao[["NOME", "CONSTRUTORA", "BAIRRO", "Região", "FASE_CLASSIFICADA"]].copy()
        df_prospeccao_info = df_prospeccao_info.rename(columns={
            "NOME": "Condomínio_Prospec",
            "CONSTRUTORA": "Construtora",
            "BAIRRO": "Bairro",
            "Região": "Região_Prospec",
            "FASE_CLASSIFICADA": "Fase_Prospec"
        })
        
        dashboard_meus = dashboard_meus.merge(
            df_prospeccao_info,
            left_on="Condomínio",
            right_on="Condomínio_Prospec",
            how="left"
        )
        
        colunas_ordem = [
            "Condomínio", "Construtora", "Bairro", "Região", "Fase_Prospec",
            "Qtd Ativos", "% Ativos (Penetração)", 
            "Total Atrasos", "% Atraso",
            "% Capacidade de Exploração", "Total Apartamentos",
            "Total Ocupados", "Ativos Puros", "Em Atraso", "Bloqueio Automático", "Desativados"
        ]
        colunas_existentes = [c for c in colunas_ordem if c in dashboard_meus.columns]
        
        st.dataframe(
            dashboard_meus[colunas_existentes],
            use_container_width=True,
            height=400,
            column_config={
                "% Ativos (Penetração)": st.column_config.ProgressColumn(format="%.1f%%", min_value=0, max_value=100),
                "% Capacidade de Exploração": st.column_config.ProgressColumn(format="%.1f%%", min_value=0, max_value=100),
                "% Atraso": st.column_config.ProgressColumn(format="%.1f%%", min_value=0, max_value=100),
            }
        )
        
        st.markdown("---")
        
        col_g1, col_g2 = st.columns(2)
        
        with col_g1:
            fig_meus = px.bar(
                dashboard_meus.sort_values("% Ativos (Penetração)", ascending=True).tail(10),
                x="% Ativos (Penetração)",
                y="Condomínio",
                color="% Ativos (Penetração)",
                color_continuous_scale="Viridis",
                title="📊 Penetração dos Meus Condomínios",
                orientation="h"
            )
            fig_meus.update_layout(height=400)
            st.plotly_chart(fig_meus, use_container_width=True, config={'displayModeBar': False})
        
        with col_g2:
            fig_cap = px.bar(
                dashboard_meus.sort_values("% Capacidade de Exploração", ascending=True).tail(10),
                x="% Capacidade de Exploração",
                y="Condomínio",
                color="% Capacidade de Exploração",
                color_continuous_scale="Oranges",
                title="🎯 Potencial de Crescimento",
                orientation="h"
            )
            fig_cap.update_layout(height=400)
            st.plotly_chart(fig_cap, use_container_width=True, config={'displayModeBar': False})
        
        st.markdown("---")
        
        output_meus = io.BytesIO()
        with pd.ExcelWriter(output_meus, engine='openpyxl') as writer:
            dashboard_meus.to_excel(writer, sheet_name='Meus_Condominios', index=False)
        output_meus.seek(0)
        
        st.download_button(
            "📥 Exportar Meus Condomínios",
            output_meus,
            f"meus_condominios_{datetime.now().strftime('%Y%m%d_%H%M')}.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            use_container_width=True
        )
    else:
        st.warning("⚠️ Não foi possível gerar o dashboard.")


# ==================== INTERFACE DE UPLOAD ====================
def upload_mode(db):
    """Modo de upload com interface melhorada"""
    subtitulo("📤 Upload de Nova Planilha de Condomínios")
    
    st.markdown("""
    <div style="background-color:#f8f9fa; padding:15px; border-radius:10px; margin-bottom:20px;">
    <strong>📋 Instruções:</strong>
    <ul>
        <li>A planilha deve conter <strong>3 abas</strong>: <code>Dados</code>, <code>Condominios</code> e <code>Base Parcelas</code></li>
        <li>Colunas obrigatórias em <code>Dados</code>: <code>CONDOMANIO</code>, <code>STATUS ACESSO</code>, <code>ID</code></li>
        <li>Colunas obrigatórias em <code>Condominios</code>: <code>ID</code>, <code>Condomínio</code>, <code>Apartamentos</code>, <code>Região</code></li>
        <li>Colunas obrigatórias em <code>Base Parcelas</code>: <code>ID</code>, <code>DATA DO VENCIMENTO</code>, <code>STATUS</code>, <code>VALOR</code></li>
    </ul>
    <strong>📌 Importante:</strong> A coluna <code>STATUS</code> da aba <code>Base Parcelas</code> pode conter:
    "A Receber" (não paga), "Recebida" / "Paga" / "Pago" (paga), "Cancelada", "Isenta", etc.
    </div>
    """, unsafe_allow_html=True)
    
    uploaded_file = st.file_uploader(
        "📂 Carregue sua planilha de condomínios (Excel)",
        type=["xlsx", "xls"],
        key="condominios_file_uploader"
    )
    
    if uploaded_file is not None:
        with st.expander("👁️ Visualizar planilha antes de processar"):
            try:
                df_preview_dados = pd.read_excel(uploaded_file, sheet_name="Dados", nrows=5)
                df_preview_cond = pd.read_excel(uploaded_file, sheet_name="Condominios", nrows=5)
                
                st.markdown("**Aba Dados:**")
                st.dataframe(df_preview_dados, use_container_width=True)
                st.markdown("**Aba Condominios:**")
                st.dataframe(df_preview_cond, use_container_width=True)
                
                try:
                    df_preview_parcelas = pd.read_excel(uploaded_file, sheet_name="Base Parcelas", nrows=5)
                    st.markdown("**Aba Base Parcelas:**")
                    st.dataframe(df_preview_parcelas, use_container_width=True)
                except:
                    st.warning("⚠️ Aba 'Base Parcelas' não encontrada.")
            except Exception as e:
                st.warning(f"Não foi possível visualizar: {e}")
        
        col1, col2 = st.columns([1, 3])
        with col1:
            if st.button("🚀 Processar e Salvar", type="primary", key="processar_upload_condominios"):
                processar_upload_condominios(db, uploaded_file)


# ==================== INTERFACE DE DADOS EXISTENTES ====================
def dados_existentes_mode(db):
    """Exibe lista de arquivos com opção de exclusão"""
    subtitulo("📁 Dados Já Importados")
    
    try:
        arquivos_cursor = db["condominios_meta"].find({'module': 'condominios'}).sort('timestamp', -1).limit(50)
        arquivos = list(arquivos_cursor)
        
        if not arquivos:
            st.info("📭 Nenhum dado encontrado no banco.")
            return
        
        st.markdown("### 📋 Arquivos Disponíveis")
        
        for arq in arquivos:
            nome = arq.get('filename', 'Arquivo sem nome')
            data = arq.get('timestamp')
            data_str = data.strftime('%d/%m/%Y %H:%M') if data else 'Data desconhecida'
            total_clientes = arq.get('total_clientes', 0)
            total_cond = arq.get('total_condominios', 0)
            total_parcelas = arq.get('total_parcelas', 0)
            
            parcelas_info = f", {total_parcelas:,} parcelas" if total_parcelas > 0 else ""
            display = f"📄 {nome} - {data_str} ({total_clientes:,} clientes, {total_cond:,} condomínios{parcelas_info})"
            
            col1, col2, col3 = st.columns([7, 1, 1])
            with col1:
                st.markdown(f"<div style='padding:5px; border-bottom:1px solid #eee;'>{display}</div>", unsafe_allow_html=True)
            with col2:
                if st.button("📂", key=f"carregar_{arq['batch_id']}", help="Carregar estes dados"):
                    with st.spinner("🔄 Carregando dados..."):
                        cursor = db["condominios_relatorios"].find({"_import_batch": arq['batch_id'], "module": "condominios"}).batch_size(5000)
                        df_all = pd.DataFrame(list(cursor))
                        
                        if 'CONDOMANIO' in df_all.columns:
                            df_clientes = df_all[df_all['CONDOMANIO'].notna()].copy()
                        else:
                            df_clientes = pd.DataFrame()
                        
                        if 'DATA DO VENCIMENTO' in df_all.columns:
                            df_parcelas = df_all[df_all['DATA DO VENCIMENTO'].notna()].copy()
                        else:
                            df_parcelas = pd.DataFrame()
                        
                        for col in ['_id', '_import_timestamp', '_import_batch', 'source_file_id', 'module']:
                            if col in df_clientes.columns:
                                df_clientes = df_clientes.drop(columns=[col])
                            if col in df_parcelas.columns:
                                df_parcelas = df_parcelas.drop(columns=[col])
                        
                        df_condominios = pd.DataFrame(arq.get("condominios", []))
                        
                        df_clientes = converter_dataframe_dates(df_clientes)
                        df_condominios = converter_dataframe_dates(df_condominios)
                        if not df_parcelas.empty:
                            df_parcelas = converter_dataframe_dates(df_parcelas)
                        
                        st.session_state.condominios_dados_clientes = df_clientes
                        st.session_state.condominios_dados_condominios = df_condominios
                        st.session_state.condominios_dados_parcelas = df_parcelas if not df_parcelas.empty else None
                        st.session_state.condominios_meta = arq
                        st.session_state.condominios_file_id = arq.get('source_file_id')
                        st.session_state.condominios_nome_arquivo = nome
                        st.session_state.condominios_processado = True
                        
                        # 🔑 Limpar cache do winback
                        st.session_state._winback_cache = None
                        st.session_state._winback_cache_key = None
                    
                    st.success(f"✅ Dados carregados: {len(df_clientes):,} clientes")
                    st.rerun()
            with col3:
                if st.button("🗑️", key=f"excluir_{arq['batch_id']}", help="Excluir este arquivo"):
                    st.session_state.exclusao_confirmada = True
                    st.session_state.batch_id_a_excluir = arq['batch_id']
                    st.session_state.colecao_a_excluir = 'condominios_relatorios'
                    st.rerun()
                    
    except Exception as e:
        st.error(f"❌ Erro ao listar arquivos: {str(e)}")


def confirmar_exclusao(db, batch_id):
    """Confirmação de exclusão com senha"""
    with st.expander("🔐 Confirmação de Exclusão", expanded=True):
        st.markdown("""
        <div style="background-color:#fff3cd; padding:15px; border-radius:10px; margin-bottom:20px;">
        <strong>⚠️ Atenção!</strong> Você está prestes a excluir permanentemente estes dados.
        </div>
        """, unsafe_allow_html=True)
        
        senha = st.text_input("Digite a senha de administração:", type="password", key="senha_exclusao_condominios")
        
        col1, col2 = st.columns([1, 1])
        with col1:
            if st.button("❌ Cancelar", key="cancelar_exclusao_condominios"):
                st.session_state.exclusao_confirmada = False
                st.rerun()
        with col2:
            if st.button("✅ Confirmar Exclusão", key="confirmar_exclusao_condominios", type="primary"):
                if senha == "3540170":
                    try:
                        total = clear_condominio_data(db, batch_id, "condominios")
                        
                        if total > 0:
                            st.success(f"✅ {total} registros excluídos com sucesso!")
                            if st.session_state.condominios_meta and st.session_state.condominios_meta.get('batch_id') == batch_id:
                                st.session_state.condominios_dados_clientes = None
                                st.session_state.condominios_dados_condominios = None
                                st.session_state.condominios_dados_parcelas = None
                                st.session_state.condominios_processado = False
                                st.session_state._winback_cache = None
                                st.session_state._winback_cache_key = None
                            
                            st.session_state.exclusao_confirmada = False
                            st.rerun()
                        else:
                            st.warning("⚠️ Nenhum registro foi removido.")
                    except Exception as e:
                        st.error(f"❌ Erro ao excluir: {str(e)}")
                else:
                    st.error("❌ Senha incorreta")


def gerenciamento_dados_mode(db):
    """Modo de gerenciamento de dados"""
    st.subheader("⚙️ Gerenciamento de Dados")
    
    col1, col2 = st.columns([3, 1])
    
    with col1:
        if st.button("🔄 Recarregar Últimos Dados", type="primary", use_container_width=True):
            with st.spinner("🔄 Recarregando dados..."):
                if carregar_dados_mais_recentes(db):
                    st.success("✅ Dados recarregados com sucesso!")
                    st.rerun()
                else:
                    st.warning("⚠️ Nenhum dado encontrado para recarregar.")
    
    with col2:
        if st.button("🗑️ Limpar Todos os Dados", type="secondary", use_container_width=True):
            if st.session_state.get("confirm_delete_all"):
                total = clear_condominio_data(db, module="condominios")
                st.success(f"✅ {total} registros removidos!")
                st.session_state.condominios_dados_clientes = None
                st.session_state.condominios_dados_condominios = None
                st.session_state.condominios_dados_parcelas = None
                st.session_state.condominios_processado = False
                st.session_state._winback_cache = None
                st.session_state._winback_cache_key = None
                st.session_state.confirm_delete_all = False
                st.rerun()
            else:
                st.warning("⚠️ Clique novamente para confirmar exclusão TOTAL")
                st.session_state.confirm_delete_all = True


# ==================== DASHBOARD PRINCIPAL ====================
def exibir_dashboard_principal(db=None):
    """Exibe o dashboard principal com todas as abas"""
    subtitulo("📊 Dashboard de Condomínios")
    
    df_clientes = st.session_state.condominios_dados_clientes
    df_condominios = st.session_state.condominios_dados_condominios
    df_parcelas = st.session_state.condominios_dados_parcelas
    meta = st.session_state.condominios_meta
    
    if df_clientes is None or df_condominios is None:
        st.warning("⚠️ Nenhum dado carregado.")
        return
    
    if meta:
        ts = meta.get('timestamp')
        ts_str = safe_strftime(ts, "%d/%m/%Y %H:%M") if ts else "Data não disponível"
        parcelas_info = f" - 📋 {meta.get('total_parcelas', 0):,} parcelas" if meta.get('total_parcelas', 0) > 0 else ""
        st.info(f"""
        **📋 Última Importação:**
        - 📅 {ts_str}
        - 📄 {meta.get('filename', 'Arquivo desconhecido')}
        - 👥 {meta.get('total_clientes', 0):,} clientes
        - 🏢 {meta.get('total_condominios', 0):,} condomínios{parcelas_info}
        """)
    
    st.markdown("---")
    
    col_modo1, col_modo2 = st.columns([1, 3])
    with col_modo1:
        modo_ativos_toggle = st.toggle(
            "Considerar 'Financeiro em Atraso' e 'Bloqueio Automático' como Ativos",
            value=False,
            key="modo_ativos_toggle"
        )
    
    modo_param = "todos_ativos" if modo_ativos_toggle else "somente_ativos"
    
    with col_modo2:
        if modo_ativos_toggle:
            st.success("✅ Modo atual: **Todos os Ocupados**")
        else:
            st.warning("⚠️ Modo atual: **Somente Ativos Limpos**")
    
    st.markdown("---")
    
    dashboard_df = gerar_dashboard_principal(df_clientes, df_condominios, modo_param)
    
    if not dashboard_df.empty:
        col1, col2, col3, col4 = st.columns(4)
        col1.metric("👥 Total de Ativos", formatar_numero_br(dashboard_df["Qtd Ativos"].sum()))
        col2.metric("⚠️ Total em Atraso", formatar_numero_br(dashboard_df["Total Atrasos"].sum()))
        col3.metric("🏢 Total de Apartamentos", formatar_numero_br(dashboard_df["Total Apartamentos"].sum()))
        col4.metric("📈 Penetração Média", f"{dashboard_df['% Ativos (Penetração)'].mean():.1f}%")
        
        condos_sem_clientes = len(dashboard_df[dashboard_df["Qtd Ativos"] == 0])
        if condos_sem_clientes > 0:
            st.info(f"📌 **{condos_sem_clientes} condomínios** sem clientes ativos")
        
        df_exibir = dashboard_df if len(dashboard_df) <= 500 else dashboard_df.head(500)
        if len(dashboard_df) > 500:
            st.caption(f"⚠️ Exibindo apenas 500 de {len(dashboard_df)} condomínios.")
        
        st.dataframe(
            df_exibir, 
            use_container_width=True,
            height=500,
            column_config={
                "Data de Implantação": st.column_config.DateColumn(format="DD/MM/YYYY"),
                "% Ativos (Penetração)": st.column_config.ProgressColumn(format="%.1f%%", min_value=0, max_value=100),
                "% Capacidade de Exploração": st.column_config.ProgressColumn(format="%.1f%%", min_value=0, max_value=100),
                "% Atraso": st.column_config.ProgressColumn(format="%.1f%%", min_value=0, max_value=100),
            }
        )
        
        output = io.BytesIO()
        with pd.ExcelWriter(output, engine='openpyxl') as writer:
            dashboard_df.to_excel(writer, sheet_name='Dashboard Principal', index=False)
        output.seek(0)
        
        st.download_button(
            "📥 Exportar Dashboard Completo",
            output,
            f"dashboard_condominios_{datetime.now().strftime('%Y%m%d')}.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            use_container_width=True
        )
        
        # ==================== BOTÃO DE WIN-BACK ====================
        render_exportacao_winback(df_clientes, df_condominios, df_parcelas)
        # ==========================================================
    
    # ==================== ABAS ====================
    st.markdown("---")
    
    tab1, tab2, tab3, tab4, tab5, tab6, tab7, tab8, tab9, tab10, tab11, tab12, tab13 = st.tabs([
        "🎯 Penetração", "💰 Receita Potencial", "⚠️ Inadimplência", 
        "📉 Churn", "⚔️ Concorrência", "📍 Análise por Zona", 
        "⏳ Maturidade", "🎯 Consulta de Crédito", "📈 Análise Temporal",
        "⭐ MEUS ACOMPANHAMENTOS",
        "📈 CRESCIMENTO POR CONDOMÍNIO",
        "🚫 CANCELAMENTOS",
        "📊 CANCELAMENTOS AVANÇADO"
    ])
    
    # TAB 1: PENETRAÇÃO
    with tab1:
        st.subheader("🎯 Taxa de Penetração por Condomínio")
        df_penetracao = calcular_penetracao(df_clientes, df_condominios)
        
        if not df_penetracao.empty:
            col1, col2 = st.columns(2)
            with col1:
                regioes = df_penetracao["Região"].dropna().unique()
                regiao_filter = st.multiselect("Região", list(regioes), key="penetracao_regiao")
            with col2:
                classific_filter = st.multiselect(
                    "Classificação", 
                    ["🟢 Dominado", "🟡 Em Crescimento", "🔴 Baixa Presença"],
                    key="penetracao_classificacao"
                )
            
            df_filtered = df_penetracao.copy()
            if regiao_filter:
                df_filtered = df_filtered[df_filtered["Região"].isin(regiao_filter)]
            if classific_filter:
                df_filtered = df_filtered[df_filtered["classificacao"].isin(classific_filter)]
            
            fig = px.bar(
                df_filtered.head(20), 
                x="taxa_penetracao", 
                y="Condomínio",
                color="classificacao",
                orientation="h",
                title="Top 20 Condomínios por Penetração",
                color_discrete_map={
                    "🟢 Dominado": "#2ecc71",
                    "🟡 Em Crescimento": "#f1c40f",
                    "🔴 Baixa Presença": "#e74c3c"
                }
            )
            st.plotly_chart(fig, use_container_width=True, config={'displayModeBar': False})
            
            with st.expander("📋 Ver Tabela Completa"):
                st.dataframe(
                    df_filtered[["Condomínio", "Região", "Apartamentos", "clientes_ativos", "taxa_penetracao", "classificacao"]],
                    use_container_width=True,
                    height=400
                )
    
    # TAB 2: RECEITA POTENCIAL
    with tab2:
        st.subheader("💰 Receita Potencial por Condomínio")
        
        df_penetracao_base = calcular_penetracao(df_clientes, df_condominios)
        
        ticket = st.number_input(
            "🎯 Ticket Médio Estimado (R$)", 
            value=CONDOMINIOS_CONFIG['ticket_medio_padrao'], 
            min_value=10.0, 
            max_value=500.0, 
            step=5.0,
            key="ticket_medio_receita"
        )
        
        df_receita = calcular_receita_potencial(df_penetracao_base, ticket_medio=ticket) if 'calcular_receita_potencial' in globals() else pd.DataFrame()
        
        if not df_receita.empty:
            st.dataframe(
                df_receita.sort_values("receita_potencial", ascending=False).head(20),
                use_container_width=True,
                height=400,
                column_config={
                    "receita_atual": st.column_config.NumberColumn(format="R$ %.2f"),
                    "receita_potencial": st.column_config.NumberColumn(format="R$ %.2f"),
                }
            )
    
    # TAB 3: INADIMPLÊNCIA
    with tab3:
        st.subheader("⚠️ Análise de Inadimplência por Condomínio")
        
        has_parcelas = df_parcelas is not None and not df_parcelas.empty
        
        if has_parcelas:
            visao_opcoes = [
                "🔴 Visão por Status Acesso",
                "🟡 Visão Financeiro Histórico", 
                "🟢 Visão Real (Parcelas Vencidas)"
            ]
            visao_selecionada = st.radio(
                "📊 Selecione a análise de inadimplência:",
                options=visao_opcoes,
                index=2,
                key="visao_inadimplencia"
            )
        else:
            visao_opcoes = [
                "🔴 Visão por Status Acesso",
                "🟡 Visão Financeiro Histórico"
            ]
            visao_selecionada = st.radio(
                "📊 Selecione a análise de inadimplência:",
                options=visao_opcoes,
                index=0,
                key="visao_inadimplencia"
            )
        
        if visao_selecionada == "🔴 Visão por Status Acesso":
            df_clientes_temp = df_clientes.copy()
            df_clientes_temp["CONDOMANIO"] = pd.to_numeric(df_clientes_temp["CONDOMANIO"], errors="coerce").fillna(0).astype(int)
            df_condominios_temp = df_condominios.copy()
            df_condominios_temp["ID"] = pd.to_numeric(df_condominios_temp["ID"], errors="coerce").fillna(0).astype(int)
            
            def status_para_inadimplencia(status):
                if pd.isna(status):
                    return "Em Dia"
                status_lower = str(status).lower().strip()
                if "financeiro em atraso" in status_lower or "bloqueio" in status_lower:
                    return "Em Atraso"
                return "Em Dia"
            
            df_clientes_temp["situacao_inadimplencia"] = df_clientes_temp["STATUS ACESSO"].apply(status_para_inadimplencia)
            
            inad_agg = df_clientes_temp.groupby(["CONDOMANIO", "situacao_inadimplencia"]).size().unstack(fill_value=0)
            
            if "Em Atraso" not in inad_agg.columns:
                inad_agg["Em Atraso"] = 0
            if "Em Dia" not in inad_agg.columns:
                inad_agg["Em Dia"] = 0
            
            total_clientes = inad_agg["Em Atraso"] + inad_agg["Em Dia"]
            inad_agg["taxa_inadimplencia"] = (inad_agg["Em Atraso"] / total_clientes.replace(0, np.nan) * 100).round(2).fillna(0)
            inad_agg["total_clientes"] = total_clientes
            inad_agg["total_inadimplentes"] = inad_agg["Em Atraso"]
            
            cols_merge = ["ID", "Condomínio", "Região", "Apartamentos"]
            cols_existentes = [c for c in cols_merge if c in df_condominios.columns]
            
            df_inadimplencia = inad_agg.reset_index().merge(
                df_condominios[cols_existentes], 
                left_on="CONDOMANIO", right_on="ID", how="right"
            )
            
            df_inadimplencia["taxa_inadimplencia"] = df_inadimplencia["taxa_inadimplencia"].fillna(0)
            df_inadimplencia["total_clientes"] = df_inadimplencia["total_clientes"].fillna(0).astype(int)
            df_inadimplencia["total_inadimplentes"] = df_inadimplencia["total_inadimplentes"].fillna(0).astype(int)
        
        elif visao_selecionada == "🟡 Visão Financeiro Histórico":
            df_inadimplencia = analisar_inadimplencia_por_status(df_clientes, df_condominios, incluir_desativados=True)
        else:
            df_inadimplencia, _ = analisar_inadimplencia_por_parcelas(df_clientes, df_condominios, df_parcelas)
        
        if not df_inadimplencia.empty:
            total_condominios = len(df_inadimplencia)
            total_inadimplentes = df_inadimplencia["total_inadimplentes"].sum()
            media_inadimplencia = df_inadimplencia["taxa_inadimplencia"].mean()
            
            col1, col2, col3 = st.columns(3)
            col1.metric("🏢 Condomínios", formatar_numero_br(total_condominios))
            col2.metric("⚠️ Total Inadimplentes", formatar_numero_br(total_inadimplentes))
            col3.metric("📊 Média Inadimplência", f"{media_inadimplencia:.1f}%")
            
            fig1 = px.bar(
                df_inadimplencia.head(15),
                x="Condomínio",
                y="taxa_inadimplencia",
                color="taxa_inadimplencia",
                color_continuous_scale="Reds",
                text="taxa_inadimplencia",
                title=f"Top 15 - {visao_selecionada}"
            )
            fig1.update_traces(texttemplate='%{text:.1f}%', textposition='outside')
            st.plotly_chart(fig1, use_container_width=True, config={'displayModeBar': False})
    
    # TAB 4: CHURN
    with tab4:
        st.subheader("📉 Análise de Churn")
        df_churn = analisar_churn(df_clientes, df_condominios)
        
        if not df_churn.empty:
            fig = px.bar(
                df_churn.head(15),
                x="Condomínio",
                y="churn_rate",
                color="churn_rate",
                color_continuous_scale="Reds",
                title="Top 15 Condomínios com Maior Churn"
            )
            st.plotly_chart(fig, use_container_width=True, config={'displayModeBar': False})
    
    # TAB 5: CONCORRÊNCIA
    with tab5:
        st.subheader("⚔️ Análise Competitiva")
        df_penetracao_base = calcular_penetracao(df_clientes, df_condominios)
        df_concorrencia = correlacao_concorrencia(df_penetracao_base, df_condominios)
        
        if not df_concorrencia.empty:
            fig = px.bar(
                df_concorrencia, 
                x="Principal Concorrente", 
                y="penetracao_ponderada", 
                title="Penetração por Concorrente"
            )
            st.plotly_chart(fig, use_container_width=True, config={'displayModeBar': False})
    
    # TAB 6: ANÁLISE POR ZONA
    with tab6:
        st.subheader("📍 Análise por Zona/Região")
        
        dashboard_para_zona = gerar_dashboard_principal(df_clientes, df_condominios, "somente_ativos")
        
        if not dashboard_para_zona.empty and "Região" in dashboard_para_zona.columns:
            zona_stats = analisar_por_zona(dashboard_para_zona)
            if not zona_stats.empty:
                st.dataframe(zona_stats, use_container_width=True)
    
    # TAB 7: MATURIDADE
    with tab7:
        st.subheader("⏳ Análise de Maturidade")
        df_maturidade = preparar_dados_maturidade(df_clientes, df_condominios)
        df_maturidade["classificacao_maturidade"] = df_maturidade.apply(
            lambda row: classificar_maturidade(row, CONDOMINIOS_CONFIG['meses_maturidade_limite']), axis=1)
        
        maturidade_counts = df_maturidade["classificacao_maturidade"].value_counts().reset_index()
        maturidade_counts.columns = ["Classificação", "Quantidade"]
        
        fig_maturidade = px.pie(
            maturidade_counts, 
            values="Quantidade", 
            names="Classificação",
            title="Distribuição por Maturidade",
            hole=0.4
        )
        st.plotly_chart(fig_maturidade, use_container_width=True, config={'displayModeBar': False})
    
    # TAB 8: CONSULTA DE CRÉDITO
    with tab8:
        st.subheader("🎯 Análise de Condomínios para Consulta de Crédito")
        
        if df_parcelas is None or df_parcelas.empty:
            st.warning("⚠️ Aba 'Base Parcelas' não encontrada.")
        else:
            filtros = render_filtros_consulta_credito_otimizado()
            
            if filtros['aplicar_filtros']:
                with st.spinner(f"🔄 Processando {len(df_parcelas):,} parcelas..."):
                    def _df_fingerprint(df_):
                        return f"{df_.shape}_{df_.index[0] if len(df_) else 0}_{df_.index[-1] if len(df_) else 0}"

                    df_inad_periodo, df_clientes_inad, df_parcelas_vencidas = analisar_inadimplencia_periodo_otimizado(
                        _df_fingerprint(df_parcelas),
                        _df_fingerprint(df_clientes),
                        _df_fingerprint(df_condominios),
                        filtros['dias_atraso'],
                        filtros['data_referencia'].isoformat(),
                        df_parcelas.shape,
                        df_clientes.shape
                    )
                    
                    st.session_state.ultimo_resultado_inadimplencia = df_inad_periodo
                
                if df_inad_periodo.empty:
                    st.warning("⚠️ Nenhuma inadimplência encontrada.")
                else:
                    df_aptos, df_top_oportunidades = identificar_condominios_aptos_consulta_flexivel_otimizado(
                        _df_fingerprint(df_inad_periodo),
                        filtros['taxa_minima'],
                        filtros['min_inadimplentes'] if filtros['min_inadimplentes'] > 0 else 0,
                        filtros['valor_minimo_atraso'],
                        filtros['ativar_filtro_valor'],
                        df_inad_periodo.shape
                    )
                    
                    render_painel_condominios_aptos(df_aptos, df_top_oportunidades)
            else:
                st.info("🔧 Configure os parâmetros e clique em 'Aplicar Filtros'.")
    
    # TAB 9: ANÁLISE TEMPORAL
    with tab9:
        st.subheader("📈 Análise Temporal de Clientes por Condomínio")
        
        df_clientes_temp = df_clientes.copy()
        df_condominios_temp = df_condominios.copy()
        
        if 'CONDOMANIO' in df_clientes_temp.columns:
            df_clientes_temp['CONDOMANIO'] = pd.to_numeric(df_clientes_temp['CONDOMANIO'], errors='coerce').fillna(0).astype(int)
        if 'ID' in df_condominios_temp.columns:
            df_condominios_temp['ID'] = pd.to_numeric(df_condominios_temp['ID'], errors='coerce').fillna(0).astype(int)
        
        data_col = identificar_coluna_data(df_clientes_temp)
        
        if data_col is None:
            st.error("❌ Coluna de data de cadastro não encontrada.")
        else:
            df_clientes_temp[data_col] = pd.to_datetime(df_clientes_temp[data_col], errors='coerce')
            df_clientes_temp = df_clientes_temp.dropna(subset=[data_col])
            
            df_clientes_temp['status_classificacao'] = classificar_status_serie(df_clientes_temp.get('STATUS ACESSO', pd.Series()))
            df_clientes_temp['is_active'] = df_clientes_temp['status_classificacao'] == 'Ativo'
            
            condominios_lista = df_condominios_temp[['ID', 'Condomínio', 'Região']].copy()
            condominios_lista = condominios_lista.sort_values('Condomínio')
            
            condominio_options = {f"{row['Condomínio']} - {row['Região']}": row['ID'] for _, row in condominios_lista.iterrows()}
            
            condominio_selecionado = st.selectbox(
                "Condomínio para análise:",
                options=list(condominio_options.keys()),
                key="temporal_cond_select"
            )
            
            if condominio_selecionado:
                condominio_id = condominio_options[condominio_selecionado]
                condominio_nome = condominio_selecionado.split(" - ")[0]
                
                periodo_preset = st.selectbox(
                    "Período:",
                    options=["Últimos 6 meses", "Último ano", "Últimos 2 anos", "Todos os dados"],
                    key="temporal_periodo_preset"
                )
                
                data_fim = datetime.now().replace(tzinfo=None)
                if periodo_preset == "Últimos 6 meses":
                    data_inicio = data_fim - timedelta(days=180)
                elif periodo_preset == "Último ano":
                    data_inicio = data_fim - timedelta(days=365)
                elif periodo_preset == "Últimos 2 anos":
                    data_inicio = data_fim - timedelta(days=730)
                else:
                    data_inicio = df_clientes_temp[data_col].min()
                
                clientes_condominio = df_clientes_temp[df_clientes_temp['CONDOMANIO'] == condominio_id].copy()
                
                if clientes_condominio.empty:
                    st.warning(f"⚠️ Nenhum cliente encontrado.")
                else:
                    clientes_condominio = clientes_condominio[
                        (clientes_condominio[data_col] >= data_inicio) & 
                        (clientes_condominio[data_col] <= data_fim)
                    ].copy()
                    
                    if clientes_condominio.empty:
                        st.warning(f"⚠️ Nenhum cliente no período.")
                    else:
                        clientes_condominio = clientes_condominio.sort_values(data_col)
                        clientes_condominio['ano_mes'] = clientes_condominio[data_col].dt.to_period('M')
                        novos_por_mes = clientes_condominio.groupby('ano_mes').size().reset_index(name='novos_clientes')
                        novos_por_mes['acumulado_ativos'] = novos_por_mes['novos_clientes'].cumsum()
                        novos_por_mes['ano_mes_str'] = novos_por_mes['ano_mes'].astype(str)
                        
                        info_condominio = df_condominios_temp[df_condominios_temp['ID'] == condominio_id].iloc[0]
                        total_apartamentos = info_condominio.get('Apartamentos', 0)
                        total_clientes_periodo = len(clientes_condominio)
                        penetracao = (total_clientes_periodo / total_apartamentos * 100) if total_apartamentos > 0 else 0
                        
                        col1, col2, col3 = st.columns(3)
                        col1.metric("🏢 Total de Clientes", f"{total_clientes_periodo}")
                        col2.metric("📈 Penetração", f"{penetracao:.1f}%")
                        col3.metric("📍 Região", info_condominio.get('Região', 'N/A'))
                        
                        fig = px.line(
                            novos_por_mes,
                            x='ano_mes_str',
                            y='acumulado_ativos',
                            title=f'📈 Evolução - {condominio_nome}',
                            markers=True
                        )
                        fig.update_traces(line=dict(color='#2ecc71', width=3))
                        st.plotly_chart(fig, use_container_width=True, config={'displayModeBar': False})
    
    # TAB 10: MEUS ACOMPANHAMENTOS
    with tab10:
        if db is not None:
            nome_usuario = render_seletor_usuario()
            
            with st.spinner("🔄 Carregando seus condomínios..."):
                meus_nomes, df_meus_prospeccao = carregar_meus_condominios_prospeccao(db)
                
                if meus_nomes and df_meus_prospeccao is not None:
                    render_dashboard_meus_acompanhamentos(
                        df_clientes, df_condominios, df_parcelas,
                        meus_nomes, df_meus_prospeccao
                    )
                else:
                    st.warning("⚠️ Nenhum condomínio encontrado em 'Meus Acompanhamentos'.")
        else:
            st.warning("⚠️ Conexão indisponível.")
    
    # TAB 11: CRESCIMENTO
    with tab11:
        if db is not None:
            meus_nomes, df_meus_prospeccao = carregar_meus_condominios_prospeccao(db)
            
            if meus_nomes and df_meus_prospeccao is not None:
                render_analise_crescimento_condominios(
                    df_clientes, df_condominios, df_meus_prospeccao,
                    data_inicio_padrao=datetime(2026, 6, 1)
                )
            else:
                st.warning("⚠️ Nenhum condomínio encontrado em 'Meus Acompanhamentos'.")
        else:
            st.warning("⚠️ Conexão indisponível.")
    
    # TAB 12: CANCELAMENTOS
    with tab12:
        render_aba_cancelamentos(df_clientes, df_condominios)
    
    # TAB 13: CANCELAMENTOS AVANÇADO
    with tab13:
        render_aba_cancelamentos_avancado(df_clientes, df_condominios)


# ==================== FUNÇÃO PRINCIPAL ====================
def render_relatorios_condominios():
    """Função principal refatorada com todas as funcionalidades"""
    
    initialize_session_state()
    
    titulo_principal("🏢 Relatórios Estratégicos - Condomínios")
    st.markdown("""
    Análise de penetração, receita potencial, inadimplência, churn, concorrência, 
    maturidade, análise temporal, integração com Meus Acompanhamentos, 
    análise de crescimento, cancelamentos e **Win-Back com Health Score**.
    """)
    
    db = init_mongo()
    
    if db is None:
        st.error("❌ Não foi possível conectar ao banco de dados")
        return
    else:
        st.success("✅ Database conectado", icon="🔗")
    
    if st.session_state.condominios_dados_clientes is None:
        with st.spinner("🔄 Carregando dados mais recentes..."):
            if carregar_dados_mais_recentes(db):
                st.success("✅ Dados mais recentes carregados automaticamente!")
            else:
                st.info("ℹ️ Nenhum dado encontrado — faça upload de uma planilha.")
    
    gerenciamento_dados_mode(db)
    st.markdown("---")
    
    tab1, tab2, tab3 = st.tabs(["📤 Upload", "📁 Dados Existentes", "📊 Dashboard"])
    
    with tab1:
        upload_mode(db)
    
    with tab2:
        dados_existentes_mode(db)
    
    with tab3:
        if st.session_state.condominios_processado:
            exibir_dashboard_principal(db)
        else:
            st.warning("⚠️ Nenhum dado carregado.")
            if st.button("🔄 Tentar carregar novamente"):
                if carregar_dados_mais_recentes(db):
                    st.success("✅ Dados carregados!")
                    st.rerun()
    
    if st.session_state.exclusao_confirmada:
        if st.session_state.batch_id_a_excluir:
            confirmar_exclusao(db, st.session_state.batch_id_a_excluir)


if __name__ == "__main__":
    render_relatorios_condominios()
