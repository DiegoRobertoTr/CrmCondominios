"""
Módulo de Relatórios de Condomínios para a DR Tracecom Suite Analítica.
VERSÃO OTIMIZADA COM ANÁLISE TEMPORAL POR CONDOMÍNIO
- Processamento de 300k+ registros em < 3 segundos
- Análise temporal individual por condomínio selecionado
- Dashboard de impacto de campanhas por condomínio específico
- INTEGRAÇÃO COM MEUS ACOMPANHAMENTOS do módulo de prospecção
- ANÁLISE DE CRESCIMENTO INDIVIDUAL POR CONDOMÍNIO
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

def carregar_meus_condominios_prospeccao(db):
    """
    Carrega a lista de condomínios da aba 'Meus Acompanhamentos' do módulo de prospecção.
    """
    try:
        meta = db["prospeccao_meta"].find_one(sort=[("timestamp", -1)])
        if not meta:
            return None, None
        
        batch_id = meta.get("batch_id")
        cursor = db["prospeccao_condominios"].find(
            {"_import_batch": batch_id},
            {"_id": 0, "NOME": 1, "ACOMPANHAMENTO": 1, "CONSTRUTORA": 1, "BAIRRO": 1, "Região": 1, "FASE_CLASSIFICADA": 1}
        )
        
        df_prospeccao = pd.DataFrame(list(cursor))
        
        if df_prospeccao.empty:
            return None, None
        
        df_com_responsavel = df_prospeccao[df_prospeccao["ACOMPANHAMENTO"].notna() & 
                                           (df_prospeccao["ACOMPANHAMENTO"] != "")].copy()
        
        if df_com_responsavel.empty:
            return None, None
        
        meu_nome = st.session_state.get("meu_nome_prospeccao", "Diego Roberto")
        
        df_meus = df_com_responsavel[df_com_responsavel["ACOMPANHAMENTO"] == meu_nome].copy()
        
        if df_meus.empty:
            return None, None
        
        meus_nomes = set()
        for _, row in df_meus.iterrows():
            nome = row.get("NOME", "")
            if nome:
                meus_nomes.add(nome.strip())
        
        return meus_nomes, df_meus
        
    except Exception as e:
        print(f"Erro ao carregar meus condomínios: {e}")
        return None, None

def filtrar_condominios_meus(df_condominios, meus_nomes):
    """
    Filtra o DataFrame de condomínios para incluir apenas os que estão na lista de acompanhamento.
    """
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
    """
    Renderiza seletor de usuário para integração com Meus Acompanhamentos.
    """
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

# ==================== NOVA FUNÇÃO: ANÁLISE DE CRESCIMENTO POR CONDOMÍNIO ====================

def render_analise_crescimento_condominios(df_clientes, df_condominios, df_meus_prospeccao, data_inicio_padrao=None):
    """
    Análise de crescimento individual por condomínio
    Comparativo: Clientes em período inicial vs período final
    """
    st.subheader("📈 Crescimento Individual por Condomínio")
    
    st.markdown("""
    <div style="background-color:#e8f4f8; padding:15px; border-radius:10px; margin-bottom:20px;">
    <strong>🎯 Como funciona:</strong><br>
    Esta análise mostra o crescimento de <strong>cada condomínio</strong> individualmente,
    comparando o número de clientes no início e no fim do período selecionado.
    <br><br>
    <strong>📊 O que é calculado:</strong>
    <ul>
        <li><strong>Clientes Início:</strong> Total de clientes na data inicial</li>
        <li><strong>Clientes Fim:</strong> Total de clientes na data final</li>
        <li><strong>Variação Absoluta:</strong> Quantos clientes a mais (ou a menos)</li>
        <li><strong>Crescimento %:</strong> Percentual de crescimento no período</li>
        <li><strong>Taxa Mensal:</strong> Crescimento médio por mês</li>
    </ul>
    </div>
    """, unsafe_allow_html=True)
    
    if df_clientes is None or df_clientes.empty or df_condominios is None or df_condominios.empty:
        st.warning("⚠️ Nenhum dado carregado para análise.")
        return
    
    if df_meus_prospeccao is None or df_meus_prospeccao.empty:
        st.warning("⚠️ Nenhum condomínio encontrado em 'Meus Acompanhamentos'.")
        return
    
    # Preparar dados
    df_clientes_temp = df_clientes.copy()
    df_condominios_temp = df_condominios.copy()
    
    # Normalizar IDs
    if 'CONDOMANIO' in df_clientes_temp.columns:
        df_clientes_temp['CONDOMANIO'] = pd.to_numeric(df_clientes_temp['CONDOMANIO'], errors='coerce').fillna(0).astype(int)
    if 'ID' in df_condominios_temp.columns:
        df_condominios_temp['ID'] = pd.to_numeric(df_condominios_temp['ID'], errors='coerce').fillna(0).astype(int)
    
    # Identificar coluna de data de cadastro
    data_col = identificar_coluna_data(df_clientes_temp)
    
    if data_col is None:
        st.error("❌ Coluna de data de cadastro não encontrada. Análise indisponível.")
        st.info("Verifique se a planilha possui uma coluna com data de cadastro (ex: 'Data cadastro', 'data_cadastro')")
        return
    
    # Converter data para datetime
    df_clientes_temp[data_col] = pd.to_datetime(df_clientes_temp[data_col], errors='coerce')
    df_clientes_temp = df_clientes_temp.dropna(subset=[data_col])
    
    if df_clientes_temp.empty:
        st.warning("⚠️ Nenhuma data de cadastro válida encontrada.")
        return
    
    # Classificar status ativo
    df_clientes_temp['status_classificacao'] = classificar_status_serie(df_clientes_temp.get('STATUS ACESSO', pd.Series()))
    df_clientes_temp['is_active'] = df_clientes_temp['status_classificacao'] == 'Ativo'
    
    # Lista de condomínios da prospecção
    meus_nomes = set(df_meus_prospeccao['NOME'].str.strip().str.upper().unique())
    
    # Filtrar condomínios que estão na lista de acompanhamento
    df_condominios_temp['nome_normalizado'] = df_condominios_temp['Condomínio'].str.strip().str.upper()
    df_condominios_filtrados = df_condominios_temp[df_condominios_temp['nome_normalizado'].isin(meus_nomes)].copy()
    
    if df_condominios_filtrados.empty:
        st.warning("⚠️ Nenhum dos condomínios de acompanhamento foi encontrado na base de clientes.")
        return
    
    # ========== SELEÇÃO DO PERÍODO ==========
    st.markdown("### 📅 Período de Análise")
    
    if data_inicio_padrao is None:
        data_inicio_padrao = datetime(2026, 6, 1)
    
    col1, col2, col3 = st.columns([2, 2, 1])
    
    with col1:
        periodo_preset = st.selectbox(
            "Período pré-definido:",
            options=[
                "Personalizado",
                "Desde que assumi (Jun/2026)",
                "Últimos 3 meses",
                "Últimos 6 meses",
                "Último ano",
                "Últimos 2 anos",
                "Todos os dados"
            ],
            index=1,
            key="crescimento_periodo_preset"
        )
    
    with col2:
        if periodo_preset == "Personalizado":
            col_data1, col_data2 = st.columns(2)
            with col_data1:
                data_inicio_date = st.date_input(
                    "Data inicial:",
                    value=data_inicio_padrao.date(),
                    key="crescimento_data_inicio"
                )
            with col_data2:
                data_fim_date = st.date_input(
                    "Data final:",
                    value=datetime.now().date(),
                    key="crescimento_data_fim"
                )
            data_inicio = datetime.combine(data_inicio_date, datetime.min.time())
            data_fim = datetime.combine(data_fim_date, datetime.min.time())
        elif periodo_preset == "Desde que assumi (Jun/2026)":
            data_inicio = data_inicio_padrao
            data_fim = datetime.now().replace(tzinfo=None)
            st.info(f"📅 Período: {data_inicio.strftime('%d/%m/%Y')} até {data_fim.strftime('%d/%m/%Y')}")
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
    
    with col3:
        if st.button("🔄 Atualizar Análise", key="btn_atualizar_crescimento", use_container_width=True):
            st.rerun()
    
    # ========== PROCESSAMENTO ==========
    with st.spinner("🔄 Calculando crescimento por condomínio..."):
        resultados = []
        
        for _, cond_row in df_condominios_filtrados.iterrows():
            cond_id = cond_row['ID']
            cond_nome = cond_row['Condomínio']
            regiao = cond_row.get('Região', 'N/A')
            total_aptos = cond_row.get('Apartamentos', 0)
            
            clientes_cond = df_clientes_temp[df_clientes_temp['CONDOMANIO'] == cond_id].copy()
            
            if clientes_cond.empty:
                continue
            
            clientes_ativos = clientes_cond[clientes_cond['is_active']].copy()
            
            if clientes_ativos.empty:
                continue
            
            clientes_inicio = clientes_ativos[clientes_ativos[data_col] <= data_inicio].copy()
            total_inicio = len(clientes_inicio)
            
            clientes_fim = clientes_ativos[clientes_ativos[data_col] <= data_fim].copy()
            total_fim = len(clientes_fim)
            
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
            info_prospec = df_meus_prospeccao[df_meus_prospeccao['NOME'].str.strip().str.upper() == cond_nome.upper()]
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
        st.warning("⚠️ Nenhum dado de crescimento encontrado para os condomínios selecionados.")
        return
    
    df_resultados = pd.DataFrame(resultados)
    
    # ========== DASHBOARD ==========
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
        st.metric("📊 Crescimento Total", f"{total_crescimento:+.0f} clientes", 
                  delta=f"{total_crescimento:+.0f}", delta_color="normal" if total_crescimento > 0 else "inverse")
    
    st.markdown("---")
    
    # ========== TABELA COMPLETA ==========
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
        height=400,
        column_config={
            'Crescimento %': st.column_config.ProgressColumn(
                'Crescimento %',
                format='%.1f%%',
                min_value=-100,
                max_value=200
            ),
            'Penetração %': st.column_config.ProgressColumn(
                'Penetração %',
                format='%.1f%%',
                min_value=0,
                max_value=100
            ),
            'Total Apartamentos': st.column_config.NumberColumn(format='%d'),
            'Clientes Início': st.column_config.NumberColumn(format='%d'),
            'Clientes Fim': st.column_config.NumberColumn(format='%d'),
            'Status': st.column_config.TextColumn(),
        }
    )
    
    st.markdown("---")
    
    # ========== GRÁFICOS ==========
    col_g1, col_g2 = st.columns(2)
    
    with col_g1:
        fig_top = px.bar(
            df_sorted.head(10),
            x='Crescimento %',
            y='Condomínio',
            color='Crescimento %',
            color_continuous_scale='RdYlGn',
            title='🏆 Top 10 - Maior Crescimento (%)',
            labels={'Crescimento %': 'Crescimento (%)', 'Condomínio': ''},
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
            labels={'Crescimento %': 'Crescimento (%)', 'Condomínio': ''},
            orientation='h',
            text='Crescimento %'
        )
        fig_bottom.update_traces(texttemplate='%{text:.1f}%', textposition='outside')
        fig_bottom.update_layout(height=400, coloraxis_showscale=False)
        st.plotly_chart(fig_bottom, use_container_width=True, config={'displayModeBar': False})
    
    # ========== MATRIZ DE CRESCIMENTO VS PENETRAÇÃO ==========
    st.markdown("---")
    st.subheader("🎯 Matriz de Crescimento vs Penetração")
    
    fig_bubble = px.scatter(
        df_sorted,
        x='Penetração %',
        y='Crescimento %',
        size='Total Apartamentos',
        color='Status',
        hover_name='Condomínio',
        text='Condomínio',
        title='📊 Crescimento vs Penetração - Matriz Estratégica',
        labels={
            'Penetração %': 'Penetração (%)',
            'Crescimento %': 'Crescimento (%)'
        },
        color_discrete_map={
            '📈 Crescendo': '#2ecc71',
            '➡️ Estável': '#f39c12',
            '📉 Declinando': '#e74c3c'
        }
    )
    fig_bubble.update_traces(textposition='top center')
    fig_bubble.update_layout(height=500)
    
    fig_bubble.add_hline(y=0, line_dash="dash", line_color="gray", opacity=0.5)
    fig_bubble.add_vline(x=50, line_dash="dash", line_color="gray", opacity=0.5)
    
    fig_bubble.add_annotation(x=75, y=50, text="🟢 Líderes", showarrow=False, font=dict(size=14, color="#2ecc71"))
    fig_bubble.add_annotation(x=25, y=50, text="🟡 Potencial", showarrow=False, font=dict(size=14, color="#f39c12"))
    fig_bubble.add_annotation(x=75, y=-30, text="🟠 Alta Penetração, Baixo Cresc.", showarrow=False, font=dict(size=12, color="#e67e22"))
    fig_bubble.add_annotation(x=25, y=-30, text="🔴 Atenção", showarrow=False, font=dict(size=14, color="#e74c3c"))
    
    st.plotly_chart(fig_bubble, use_container_width=True, config={'displayModeBar': False})
    
    # ========== ANÁLISE DETALHADA POR CONDOMÍNIO ==========
    st.markdown("---")
    st.subheader("📊 Análise Detalhada por Condomínio")
    
    if len(df_sorted) > 0:
        cond_select = st.selectbox(
            "Selecione um condomínio para análise detalhada:",
            options=df_sorted['Condomínio'].tolist(),
            key="crescimento_cond_select"
        )
        
        if cond_select:
            cond_data = df_sorted[df_sorted['Condomínio'] == cond_select].iloc[0]
            
            col_d1, col_d2, col_d3, col_d4 = st.columns(4)
            with col_d1:
                st.metric("📈 Crescimento", f"{cond_data['Crescimento %']:.1f}%", 
                          delta=f"{cond_data['Variação']:+.0f} clientes")
            with col_d2:
                st.metric("📅 Taxa Mensal", f"{cond_data['Taxa Mensal %']:.1f}%")
            with col_d3:
                st.metric("📊 Penetração", f"{cond_data['Penetração %']:.1f}%")
            with col_d4:
                st.metric("📌 Fase", cond_data['Fase Prospecção'])
            
            cond_id = df_condominios_filtrados[df_condominios_filtrados['Condomínio'] == cond_select]['ID'].iloc[0]
            
            clientes_cond = df_clientes_temp[df_clientes_temp['CONDOMANIO'] == cond_id].copy()
            clientes_ativos = clientes_cond[clientes_cond['is_active']].copy()
            
            if not clientes_ativos.empty:
                clientes_ativos['mes'] = clientes_ativos[data_col].dt.to_period('M')
                evolucao = clientes_ativos.groupby('mes').size().reset_index(name='novos')
                evolucao['acumulado'] = evolucao['novos'].cumsum()
                evolucao['mes_str'] = evolucao['mes'].astype(str)
                
                evolucao = evolucao[evolucao['mes'].dt.start_time >= data_inicio]
                
                if not evolucao.empty:
                    fig_evol = px.line(
                        evolucao,
                        x='mes_str',
                        y='acumulado',
                        title=f'📈 Evolução Mensal - {cond_select}',
                        labels={'mes_str': 'Mês/Ano', 'acumulado': 'Total de Clientes Ativos'},
                        markers=True
                    )
                    fig_evol.update_traces(line=dict(color='#3498db', width=3), marker=dict(size=8))
                    fig_evol.update_layout(height=350)
                    st.plotly_chart(fig_evol, use_container_width=True, config={'displayModeBar': False})
    
    # ========== EXPORTAÇÃO ==========
    st.markdown("---")
    st.subheader("📎 Exportar Dados de Crescimento")
    
    col_exp1, col_exp2 = st.columns(2)
    
    with col_exp1:
        output = io.BytesIO()
        with pd.ExcelWriter(output, engine='openpyxl') as writer:
            df_sorted.to_excel(writer, sheet_name='Crescimento_Condominios', index=False)
            
            for cond in df_sorted['Condomínio'].head(10):
                cond_id = df_condominios_filtrados[df_condominios_filtrados['Condomínio'] == cond]['ID'].iloc[0]
                clientes_cond = df_clientes_temp[df_clientes_temp['CONDOMANIO'] == cond_id].copy()
                clientes_ativos = clientes_cond[clientes_cond['is_active']].copy()
                
                if not clientes_ativos.empty:
                    clientes_ativos['mes'] = clientes_ativos[data_col].dt.to_period('M')
                    evolucao = clientes_ativos.groupby('mes').size().reset_index(name='novos')
                    evolucao['acumulado'] = evolucao['novos'].cumsum()
                    evolucao['mes_str'] = evolucao['mes'].astype(str)
                    evolucao.to_excel(writer, sheet_name=cond[:31], index=False)
        
        output.seek(0)
        
        st.download_button(
            "📥 Exportar Análise de Crescimento",
            output,
            f"crescimento_condominios_{datetime.now().strftime('%Y%m%d_%H%M')}.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            use_container_width=True
        )
    
    with col_exp2:
        st.info("""
        **📋 O que será exportado:**
        - Aba principal com todos os condomínios
        - Abas individuais para os 10 primeiros condomínios
        - Evolução mensal detalhada de cada um
        """)

# ==================== FUNÇÕES OTIMIZADAS PARA CONSULTA DE CRÉDITO ====================

@st.cache_data(ttl=300, show_spinner=False)
def analisar_inadimplencia_periodo_otimizado(_df_parcelas_hash, _df_clientes_hash, _df_condominios_hash,
                                              dias_atraso, data_referencia_str, parcelas_shape, clientes_shape):
    """
    VERSÃO OTIMIZADA - Processamento vetorizado sem loops
    Para 300k linhas deve rodar em < 2 segundos
    """
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
    
    df_parcelas_subset.loc[:, 'DATA DO VENCIMENTO'] = pd.to_datetime(
        df_parcelas_subset['DATA DO VENCIMENTO'], errors='coerce'
    )
    df_parcelas_subset.loc[:, 'STATUS_NORMALIZADO'] = (
        df_parcelas_subset['STATUS'].str.upper().str.strip()
    )
    
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
    
    parcelas_vencidas.loc[:, 'DIAS_ATRASO'] = (
        data_referencia - parcelas_vencidas['DATA DO VENCIMENTO']
    ).dt.days
    
    parcelas_vencidas.loc[:, 'FAIXA_ATRASO'] = pd.cut(
        parcelas_vencidas['DIAS_ATRASO'],
        bins=[0, 30, 60, 90, float('inf')],
        labels=['1-30 dias', '31-60 dias', '61-90 dias', '90+ dias']
    )
    
    cliente_atraso = parcelas_vencidas.groupby('ID', as_index=False).agg({
        'VALOR': ['count', 'sum'],
        'DIAS_ATRASO': ['max', 'mean']
    })
    
    cliente_atraso.columns = ['ID', 'total_parcelas_vencidas', 'valor_total_atraso', 
                              'max_dias_atraso', 'media_dias_atraso']
    
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
    
    total_clientes_cond = (
        df_clientes_subset.groupby('CONDOMANIO')
        .size()
        .reset_index(name='total_clientes')
    )
    
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
    """
    VERSÃO OTIMIZADA - Filtros em lote sem loops
    """
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
            min_value=1,
            max_value=90,
            value=30,
            step=5,
            key="consulta_dias_atraso",
            help="Cliente é considerado inadimplente se tiver parcelas vencidas há mais de X dias"
        )
        
        data_referencia = st.date_input(
            "📆 Data de referência",
            value=datetime.now().date(),
            key="consulta_data_ref",
            help="Data base para verificar vencimentos"
        )
    
    with col2:
        taxa_minima = st.slider(
            "📊 Taxa mínima de inadimplência (%)",
            min_value=0,
            max_value=100,
            value=30,
            step=5,
            key="consulta_taxa_minima",
            help="Condomínios com inadimplência acima deste percentual"
        )
        
        min_inadimplentes = st.number_input(
            "👥 Número mínimo de clientes inadimplentes",
            min_value=0,
            max_value=1000,
            value=5,
            step=1,
            key="consulta_min_inadimplentes",
            help="Condomínios com pelo menos este número de clientes inadimplentes (0 = ignora)"
        )
    
    st.markdown("---")
    st.markdown("### 💰 Filtro de Valor")
    
    ativar_filtro_valor = st.checkbox(
        "✅ Ativar filtro de valor mínimo em atraso",
        value=True,
        key="ativar_filtro_valor",
        help="Desmarque para ignorar o valor mínimo em atraso"
    )
    
    valor_minimo_atraso = 0
    if ativar_filtro_valor:
        valor_minimo_atraso = st.number_input(
            "💰 Valor mínimo em atraso (R$)",
            min_value=0,
            max_value=100000,
            value=500,
            step=100,
            key="consulta_valor_minimo",
            help="Condomínios com valor em atraso acima deste limite"
        )
    
    st.markdown("---")
    
    aplicar_filtros = st.button(
        "🔍 Aplicar Filtros e Gerar Ranking",
        type="primary",
        use_container_width=True,
        key="botao_aplicar_filtros_consulta"
    )
    
    with st.expander("📋 Resumo dos Filtros Ativos"):
        st.markdown(f"""
        - **Dias de atraso:** {dias_atraso} dias
        - **Data de referência:** {data_referencia.strftime('%d/%m/%Y')}
        - **Taxa mínima de inadimplência:** {taxa_minima}%
        - **Mínimo de inadimplentes:** {min_inadimplentes if min_inadimplentes > 0 else 'Ignorado'}
        - **Valor mínimo em atraso:** {f'R$ {valor_minimo_atraso:,.2f}' if ativar_filtro_valor and valor_minimo_atraso > 0 else 'Ignorado'}
        """)
    
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
        st.info("ℹ️ Nenhum condomínio atende aos critérios definidos. Ajuste os filtros acima.")
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
            "total_clientes": st.column_config.NumberColumn("Total Clientes", format="%d"),
            "total_clientes_inadimplentes": st.column_config.NumberColumn("Inadimplentes", format="%d"),
            "max_dias_atraso": st.column_config.NumberColumn("Máx Dias Atraso", format="%d"),
        }
    )
    
    fig_top = px.bar(
        df_top_oportunidades,
        x="Condomínio",
        y="taxa_inadimplencia",
        color="valor_total_atraso",
        text="taxa_inadimplencia",
        title="📊 Top 10 Condomínios por Taxa de Inadimplência",
        color_continuous_scale="Reds",
        labels={"taxa_inadimplencia": "Inadimplência (%)", "valor_total_atraso": "Valor em Atraso (R$)"}
    )
    fig_top.update_traces(texttemplate='%{text:.1f}%', textposition='outside')
    fig_top.update_layout(height=450)
    st.plotly_chart(fig_top, use_container_width=True, config={'displayModeBar': False})
    
    with st.expander("📋 Ver Todos os Condomínios Aptos"):
        df_exibir = df_aptos if len(df_aptos) <= 500 else df_aptos.head(500)
        if len(df_aptos) > 500:
            st.caption(f"⚠️ Exibindo apenas 500 de {len(df_aptos)} condomínios. Use exportação para ver todos.")
        
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
        "📥 Exportar Lista de Condomínios Aptos para Consulta",
        output_aptos,
        f"condominios_aptos_consulta_{datetime.now().strftime('%Y%m%d_%H%M')}.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        use_container_width=True
    )

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
    """
    Converte DataFrame para lista de dicts seguros para o MongoDB.
    VERSÃO OTIMIZADA — conversão vetorizada, sem loop Python por célula.
    """
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
    """Versão melhorada do save_condominio_data com referência ao source_file_id e parcelas"""
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
    """Carrega automaticamente os dados mais recentes do MongoDB — versão otimizada com projeção"""
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
        
        cursor_clientes = db["condominios_relatorios"].find(
            {"_import_batch": batch_id, "module": "condominios"},
            projection
        )
        
        _CHUNK = 10000
        chunks = []
        buf = []
        for doc in cursor_clientes:
            buf.append(doc)
            if len(buf) >= _CHUNK:
                chunks.append(pd.DataFrame(buf))
                buf.clear()
        if buf:
            chunks.append(pd.DataFrame(buf))
        
        if not chunks:
            return False
        
        df_all = pd.concat(chunks, ignore_index=True)
        del chunks, buf
        
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
        
        return True
        
    except Exception as e:
        print(f"❌ Erro ao carregar dados automáticos: {str(e)}")
        return False

def clear_condominio_data(db, batch_id=None, module="condominios"):
    """Limpa dados do banco com filtro por módulo"""
    collection_clientes = db["condominios_relatorios"]
    collection_meta = db["condominios_meta"]
    
    if batch_id:
        result_clientes = collection_clientes.delete_many({
            "_import_batch": batch_id,
            "module": module
        })
        result_meta = collection_meta.delete_many({
            "batch_id": batch_id,
            "module": module
        })
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
                st.warning("⚠️ Aba 'Base Parcelas' não encontrada. A análise de inadimplência real será limitada.")
            
            df_clientes = df_clientes.replace({pd.NaT: None, np.nan: None})
            df_condominios = df_condominios.replace({pd.NaT: None, np.nan: None})
            if not df_parcelas.empty:
                df_parcelas = df_parcelas.replace({pd.NaT: None, np.nan: None})
            
            colunas_faltantes_clientes = [
                col for col in CONDOMINIOS_CONFIG['colunas_obrigatorias_clientes'] 
                if col not in df_clientes.columns
            ]
            colunas_faltantes_condominios = [
                col for col in CONDOMINIOS_CONFIG['colunas_obrigatorias_condominios'] 
                if col not in df_condominios.columns
            ]
            
            if colunas_faltantes_clientes:
                st.warning(f"⚠️ Colunas faltantes em Dados: {colunas_faltantes_clientes}")
            if colunas_faltantes_condominios:
                st.warning(f"⚠️ Colunas faltantes em Condominios: {colunas_faltantes_condominios}")
            
            if "CONDOMANIO" in df_clientes.columns:
                df_clientes["CONDOMANIO"] = pd.to_numeric(
                    df_clientes["CONDOMANIO"], errors="coerce"
                ).fillna(0).astype(int)
            
            if "ID" in df_condominios.columns:
                df_condominios["ID"] = pd.to_numeric(
                    df_condominios["ID"], errors="coerce"
                ).fillna(0).astype(int)
            
            if "Apartamentos" in df_condominios.columns:
                df_condominios["Apartamentos"] = pd.to_numeric(
                    df_condominios["Apartamentos"], errors="coerce"
                ).fillna(0).astype(int)
            
            if not df_parcelas.empty and "ID" in df_parcelas.columns:
                df_parcelas["ID"] = pd.to_numeric(
                    df_parcelas["ID"], errors="coerce"
                ).fillna(0).astype(int)
            
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
    """
    Versão vetorizada de classificação de status para uso em DataFrames.
    ~50x mais rápido que .apply() em 300k linhas.
    """
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
    """
    Identifica a coluna de data de cadastro no DataFrame de clientes
    """
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
    """Classifica o status do cliente — mantido para compatibilidade pontual"""
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
    """Analisa inadimplência baseada na coluna FINANCEIRO EM ATRASO (modo legado)"""
    df_clientes = df_clientes.copy()
    df_condominios = df_condominios.copy()
    
    df_clientes["CONDOMANIO"] = pd.to_numeric(df_clientes["CONDOMANIO"], errors="coerce").fillna(0).astype(int)
    df_condominios["ID"] = pd.to_numeric(df_condominios["ID"], errors="coerce").fillna(0).astype(int)
    
    if not incluir_desativados:
        df_clientes = df_clientes[
            ~df_clientes["STATUS ACESSO"].str.lower().str.contains("desativado|cancelado", na=False)
        ].copy()
    
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
    """Analisa inadimplência REAL baseada na aba 'Base Parcelas' (otimizada)"""
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
    
    parcelas_detalhe = parcelas_vencidas.merge(
        df_condominios[["ID", "Condomínio", "Região"]], 
        left_on="ID", right_on="ID", how="left"
    )
    
    if not parcelas_detalhe.empty:
        parcelas_detalhe = parcelas_detalhe[[
            "ID", "RAZAO SOCIAL/NOME", "Condomínio", "Região",
            "DATA DO VENCIMENTO", "NAMERO DA PARCELA RECORRENTE",
            "PLANO DE VENDA", "VALOR", "STATUS"
        ]].copy()
        parcelas_detalhe.columns = [
            "ID Cliente", "Cliente", "Condomínio", "Região",
            "Data Vencimento", "Nº Parcela", "Plano", "Valor", "Status"
        ]
    
    return result.sort_values("taxa_inadimplencia", ascending=False).reset_index(drop=True), parcelas_detalhe

def analisar_churn(df_clientes, df_condominios):
    """Análise de churn (taxa de cancelamento) otimizada"""
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
    
    cols_merge = ["ID", "Condomínio", "Região", "Principal Concorrente"]
    cols_existentes = [c for c in cols_merge if c in df_condominios.columns]
    
    result = status_count.reset_index().merge(
        df_condominios[cols_existentes], 
        left_on="CONDOMANIO", right_on="ID", how="right"
    )
    result["churn_rate"] = result["churn_rate"].fillna(0)
    result["Ativo"] = result.get("Ativo", 0).fillna(0).astype(int)
    result["Desativado"] = result.get("Desativado", 0).fillna(0).astype(int)
    
    return result.sort_values("churn_rate", ascending=False)

def calcular_receita_potencial(df_penetracao, ticket_medio=89.99):
    """Calcula receita potencial por condomínio"""
    df = df_penetracao.copy()
    df["clientes_ativos"] = df["clientes_ativos"].fillna(0)
    df["Apartamentos"] = pd.to_numeric(df["Apartamentos"], errors="coerce").fillna(0)
    df["receita_atual"] = df["clientes_ativos"] * ticket_medio
    df["potencial_clientes"] = (df["Apartamentos"] - df["clientes_ativos"]).clip(lower=0)
    df["receita_potencial"] = df["potencial_clientes"] * ticket_medio
    df["receita_maxima"] = df["Apartamentos"] * ticket_medio
    df["gap_receita"] = (df["receita_potencial"] / df["receita_atual"].replace(0, np.nan)).replace(
        [np.inf, -np.inf], 0) * 100
    return df.sort_values("receita_potencial", ascending=False)

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
        conc_stats["penetracao_ponderada"] = (conc_stats["clientes_ativos_sum"] / 
            conc_stats["Apartamentos_sum"].replace(0, np.nan) * 100).round(2)
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
        media_atraso=("% Atraso", "mean"),
        media_capacidade_exploracao=("% Capacidade de Exploração", "mean")
    ).reset_index()
    
    zona_stats["percentual_ativos"] = (zona_stats["total_ativos"] / 
        zona_stats["total_apartamentos"] * 100).round(2)
    zona_stats["percentual_ocupacao"] = (zona_stats["total_ocupados"] / 
        zona_stats["total_apartamentos"] * 100).round(2)
    zona_stats["percentual_atraso"] = (zona_stats["total_em_atraso"] / 
        zona_stats["total_apartamentos"] * 100).round(2)
    zona_stats["percentual_desativados"] = (zona_stats["total_desativados"] / 
        zona_stats["total_apartamentos"] * 100).round(2)
    
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
            if ativos >= 50:
                return "🟢 Maduro Grande (Sem Aptos)"
            elif ativos >= 20:
                return "🟡 Maduro Médio (Sem Aptos)"
            elif ativos > 0:
                return " Maduro Pequeno (Sem Aptos)"
            else:
                return " Maduro Inativo (Sem Aptos)"
    elif meses >= 12:
        if tem_aptos:
            if ativos_pct >= 30:
                return "🔵 Intermediário Saudável"
            elif ativos_pct >= 10:
                return "🟡 Intermediário Fraco"
            else:
                return "Intermediário Crítico"
        else:
            if ativos >= 30:
                return " Intermediário Grande (Sem Aptos)"
            elif ativos >= 10:
                return "Intermediário Médio (Sem Aptos)"
            else:
                return "Intermediário Fraco (Sem Aptos)"
    elif meses >= 6:
        if tem_aptos:
            if ativos_pct >= 20:
                return " Jovem em Crescimento"
            else:
                return "Jovem Fraco"
        else:
            if ativos >= 20:
                return " Jovem Grande (Sem Aptos)"
            else:
                return "🟡 Jovem Pequeno (Sem Aptos)"
    else:
        if ativos > 10:
            return "⚪ Novo Promissor"
        else:
            return "⚪ Novo Iniciante"

def preparar_dados_maturidade(df_clientes, df_condominios):
    """Prepara dados para análise de maturidade"""
    df_clientes = df_clientes.copy()
    df_condominios = df_condominios.copy()
    
    df_clientes["CONDOMANIO"] = pd.to_numeric(df_clientes["CONDOMANIO"], errors="coerce").fillna(0).astype(int)
    df_condominios["ID"] = pd.to_numeric(df_condominios["ID"], errors="coerce").fillna(0).astype(int)
    
    data_ref = datetime.now().replace(tzinfo=None)
    df_condominios = df_condominios.copy()
    df_condominios["Apartamentos"] = pd.to_numeric(df_condominios["Apartamentos"], 
        errors="coerce").fillna(0).astype(int)
    df_condominios["Data cadastro"] = df_condominios["Data cadastro"].apply(limpar_valor_data)
    
    df_clientes["status_classificacao"] = classificar_status_serie(df_clientes["STATUS ACESSO"])
    
    clientes_agg = df_clientes.groupby("CONDOMANIO").agg(
        total_clientes=("CONDOMANIO", "count"),
        ativos=("status_classificacao", lambda x: (x == "Ativo").sum()),
        em_atraso=("status_classificacao", lambda x: (x == "Em Atraso").sum()),
        bloqueio_automatico=("status_classificacao", lambda x: (x == "Bloqueio Automático").sum()),
        desativados=("status_classificacao", lambda x: (x == "Desativado").sum()),
    ).reset_index()
    
    df_maturidade = df_condominios[["ID", "Condomínio", "Apartamentos", "Região", 
                                    "Data cadastro", "Principal Concorrente"]].copy()
    df_maturidade = df_maturidade.merge(clientes_agg, left_on="ID", right_on="CONDOMANIO", how="left")
    
    for col in ["ativos", "em_atraso", "bloqueio_automatico", "desativados", "total_clientes"]:
        df_maturidade[col] = df_maturidade[col].fillna(0).astype(int)
    
    apt_safe = df_maturidade["Apartamentos"].replace(0, np.nan)
    df_maturidade["total_ocupados"] = df_maturidade["ativos"] + df_maturidade["em_atraso"] + df_maturidade["bloqueio_automatico"]
    df_maturidade["percentual_ativos"] = (df_maturidade["ativos"] / apt_safe * 100).round(2).fillna(0)
    df_maturidade["percentual_penetracao"] = (df_maturidade["total_ocupados"] / apt_safe * 100).round(2).fillna(0)
    df_maturidade["meses_cadastro"] = df_maturidade["Data cadastro"].apply(
        lambda x: calcular_meses_cadastro(x, data_ref))
    
    return df_maturidade

# ==================== DASHBOARD MEUS ACOMPANHAMENTOS ====================

def render_dashboard_meus_acompanhamentos(df_clientes, df_condominios, df_parcelas, meus_nomes, df_meus_prospeccao):
    """
    Renderiza dashboard completo com foco nos condomínios de acompanhamento.
    """
    st.subheader("⭐ Meus Condomínios - Acompanhamento Estratégico")
    
    if not meus_nomes or df_meus_prospeccao is None or df_meus_prospeccao.empty:
        st.warning("⚠️ Nenhum condomínio encontrado em 'Meus Acompanhamentos'.")
        st.info("💡 Certifique-se de que: 1) A planilha de prospecção foi importada, 2) Você preencheu seu nome na coluna 'Acompanhamento', 3) Seu nome está correto no campo acima.")
        return
    
    df_condominios_filtrados = filtrar_condominios_meus(df_condominios, meus_nomes)
    
    if df_condominios_filtrados.empty:
        st.warning("⚠️ Nenhum dos condomínios de 'Meus Acompanhamentos' foi encontrado na base de dados de relatórios.")
        st.info("📌 Verifique se os nomes dos condomínios estão escritos exatamente iguais em ambas as planilhas.")
        
        with st.expander("📋 Ver lista de condomínios esperados"):
            st.dataframe(df_meus_prospeccao[["NOME", "CONSTRUTORA", "BAIRRO", "Região", "FASE_CLASSIFICADA"]], use_container_width=True)
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
            total_ativos = dashboard_meus["Qtd Ativos"].sum()
            st.metric("👥 Total Ativos", formatar_numero_br(total_ativos))
        with col_m2:
            total_atrasos = dashboard_meus["Total Atrasos"].sum()
            st.metric("⚠️ Em Atraso", formatar_numero_br(total_atrasos))
        with col_m3:
            total_aptos = dashboard_meus["Total Apartamentos"].sum()
            st.metric("🏢 Apartamentos", formatar_numero_br(total_aptos))
        with col_m4:
            media_penetracao = dashboard_meus["% Ativos (Penetração)"].mean()
            st.metric("📈 Penetração Média", f"{media_penetracao:.1f}%")
        with col_m5:
            capacidade = dashboard_meus["% Capacidade de Exploração"].mean()
            st.metric("🎯 Potencial Médio", f"{capacidade:.1f}%")
        
        st.markdown("---")
        
        st.subheader("📋 Detalhamento dos Meus Condomínios")
        
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
                "Qtd Ativos": st.column_config.NumberColumn(format="%d"),
                "Total Apartamentos": st.column_config.NumberColumn(format="%d"),
                "Total Ocupados": st.column_config.NumberColumn(format="%d"),
                "Ativos Puros": st.column_config.NumberColumn(format="%d"),
                "Em Atraso": st.column_config.NumberColumn(format="%d"),
                "Bloqueio Automático": st.column_config.NumberColumn(format="%d"),
                "Desativados": st.column_config.NumberColumn(format="%d"),
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
        
        if df_condominios_filtrados is not None and not df_condominios_filtrados.empty:
            st.subheader("📈 Evolução Temporal - Meus Condomínios")
            
            df_clientes_temp = df_clientes.copy()
            df_clientes_temp['CONDOMANIO'] = pd.to_numeric(df_clientes_temp['CONDOMANIO'], errors='coerce').fillna(0).astype(int)
            df_condominios_filtrados['ID'] = pd.to_numeric(df_condominios_filtrados['ID'], errors='coerce').fillna(0).astype(int)
            
            meus_ids = set(df_condominios_filtrados['ID'].unique())
            
            clientes_meus = df_clientes_temp[df_clientes_temp['CONDOMANIO'].isin(meus_ids)].copy()
            
            if not clientes_meus.empty:
                data_col = identificar_coluna_data(clientes_meus)
                
                if data_col:
                    clientes_meus[data_col] = pd.to_datetime(clientes_meus[data_col], errors='coerce')
                    clientes_meus = clientes_meus.dropna(subset=[data_col])
                    
                    if not clientes_meus.empty:
                        clientes_meus['data_normalizada'] = clientes_meus[data_col].dt.date
                        novos_por_dia = clientes_meus.groupby('data_normalizada').size().reset_index(name='novos_clientes')
                        novos_por_dia = novos_por_dia.sort_values('data_normalizada')
                        novos_por_dia['acumulado'] = novos_por_dia['novos_clientes'].cumsum()
                        
                        clientes_meus['ano_mes'] = clientes_meus[data_col].dt.to_period('M')
                        novos_por_mes = clientes_meus.groupby('ano_mes').size().reset_index(name='novos_clientes')
                        novos_por_mes['acumulado'] = novos_por_mes['novos_clientes'].cumsum()
                        novos_por_mes['ano_mes_str'] = novos_por_mes['ano_mes'].astype(str)
                        
                        fig_meus_acum = px.line(
                            novos_por_mes,
                            x='ano_mes_str',
                            y='acumulado',
                            title=f'📈 Evolução de Clientes - Meus Condomínios (Total: {len(meus_ids)} condomínios)',
                            labels={'ano_mes_str': 'Mês/Ano', 'acumulado': 'Total de Clientes'},
                            markers=True
                        )
                        fig_meus_acum.update_traces(line=dict(color='#2ecc71', width=3))
                        fig_meus_acum.update_layout(height=400)
                        st.plotly_chart(fig_meus_acum, use_container_width=True, config={'displayModeBar': False})
                        
                        fig_meus_novos = px.bar(
                            novos_por_mes,
                            x='ano_mes_str',
                            y='novos_clientes',
                            title='📊 Novos Clientes por Mês - Meus Condomínios',
                            labels={'ano_mes_str': 'Mês/Ano', 'novos_clientes': 'Novos Clientes'},
                            color='novos_clientes',
                            color_continuous_scale='Viridis'
                        )
                        fig_meus_novos.update_layout(height=350)
                        st.plotly_chart(fig_meus_novos, use_container_width=True, config={'displayModeBar': False})
        
        st.markdown("---")
        
        st.subheader("📎 Exportar Dados dos Meus Condomínios")
        
        col_exp1, col_exp2 = st.columns(2)
        
        with col_exp1:
            output_meus = io.BytesIO()
            with pd.ExcelWriter(output_meus, engine='openpyxl') as writer:
                dashboard_meus.to_excel(writer, sheet_name='Meus_Condominios', index=False)
                if df_meus_prospeccao is not None and not df_meus_prospeccao.empty:
                    df_meus_prospeccao.to_excel(writer, sheet_name='Prospeccao_Referencia', index=False)
            output_meus.seek(0)
            
            st.download_button(
                "📥 Exportar Meus Condomínios",
                output_meus,
                f"meus_condominios_{datetime.now().strftime('%Y%m%d_%H%M')}.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                use_container_width=True
            )
        
        with col_exp2:
            st.info("💡 **Dica:** Esta exportação inclui todos os dados dos seus condomínios, incluindo as informações de prospecção.")
        
        with st.expander("📋 Ver dados de referência da prospecção"):
            st.dataframe(
                df_meus_prospeccao[["NOME", "CONSTRUTORA", "BAIRRO", "Região", "ACOMPANHAMENTO", "FASE_CLASSIFICADA"]],
                use_container_width=True
            )
    
    else:
        st.warning("⚠️ Não foi possível gerar o dashboard para os condomínios selecionados.")

# ==================== INTERFACE DE UPLOAD ====================
def upload_mode(db):
    """Modo de upload com interface melhorada"""
    subtitulo("📤 Upload de Nova Planilha de Condomínios")
    
    st.markdown("""
    <div style="background-color:#f8f9fa; padding:15px; border-radius:10px; margin-bottom:20px;">
    <strong>📋 Instruções:</strong>
    <ul>
        <li>A planilha deve conter <strong>3 abas</strong>: <code>Dados</code> (clientes), <code>Condominios</code> e <code>Base Parcelas</code></li>
        <li>Colunas obrigatórias em <code>Dados</code>: <code>CONDOMANIO</code>, <code>STATUS ACESSO</code>, <code>ID</code></li>
        <li>Colunas obrigatórias em <code>Condominios</code>: <code>ID</code>, <code>Condomínio</code>, <code>Apartamentos</code>, <code>Região</code></li>
        <li>Colunas obrigatórias em <code>Base Parcelas</code>: <code>ID</code>, <code>DATA DO VENCIMENTO</code>, <code>STATUS</code>, <code>VALOR</code></li>
    </ul>
    <strong>📌 Importante:</strong> A aba <code>Base Parcelas</code> é fundamental para a análise de inadimplência REAL.
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
                
                st.markdown("**Aba Dados (primeiras 5 linhas):**")
                st.dataframe(df_preview_dados, use_container_width=True)
                st.markdown("**Aba Condominios (primeiras 5 linhas):**")
                st.dataframe(df_preview_cond, use_container_width=True)
                
                try:
                    df_preview_parcelas = pd.read_excel(uploaded_file, sheet_name="Base Parcelas", nrows=5)
                    st.markdown("**Aba Base Parcelas (primeiras 5 linhas):**")
                    st.dataframe(df_preview_parcelas, use_container_width=True)
                except:
                    st.warning("⚠️ Aba 'Base Parcelas' não encontrada. A análise de inadimplência real será limitada.")
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
        arquivos_cursor = db["condominios_meta"].find(
            {'module': 'condominios'}
        ).sort('timestamp', -1).limit(50)
        
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
                        cursor = db["condominios_relatorios"].find({
                            "_import_batch": arq['batch_id'],
                            "module": "condominios"
                        })
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
                    
                    st.success(f"✅ Dados carregados: {len(df_clientes):,} clientes{', ' + f'{len(df_parcelas):,} parcelas' if not df_parcelas.empty else ''}")
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
        <strong>⚠️ Atenção!</strong> Você está prestes a excluir permanentemente estes dados.<br>
        Esta ação <strong>não pode ser desfeita</strong>.
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
                            
                            st.session_state.exclusao_confirmada = False
                            st.rerun()
                        else:
                            st.warning("⚠️ Nenhum registro foi removido.")
                    except Exception as e:
                        st.error(f"❌ Erro ao excluir: {str(e)}")
                else:
                    st.error("❌ Senha incorreta")

# ==================== BOTÃO RECARREGAR ====================
def gerenciamento_dados_mode(db):
    """Modo de gerenciamento de dados com botão recarregar"""
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
        st.warning("⚠️ Nenhum dado carregado. Faça upload ou selecione dados existentes.")
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
    
    with st.expander("📖 Entenda como os 'Ativos' são calculados"):
        st.markdown("""
        ### Como são calculados os indicadores:
        
        | Métrica | Fórmula |
        |---------|---------|
        | **Qtd Ativos** | Depende do modo selecionado abaixo |
        | **% Ativos (Penetração)** | Ativos / Total Apartamentos × 100 |
        | **% Atraso** | (Em Atraso + Bloqueio Automático) / Total Ocupados × 100 |
        | **% Capacidade de Exploração** | (Apartamentos - Total Ocupados) / Apartamentos × 100 |
        
        **Classificações de status:**
        - **Ativo Puro**: Status "Ativo" sem atraso ou bloqueio
        - **Em Atraso**: Financeiro em atraso
        - **Bloqueio Automático**: Bloqueado por inadimplência
        - **Desativado**: Cancelado ou desativado
        """)
    
    st.markdown("---")
    
    st.markdown("""
    <div style="background-color:#e8f4f8; padding:10px; border-radius:5px; margin-bottom:15px;">
    <strong>📋 Como os "Ativos" são calculados:</strong><br>
    Por padrão, "Ativos" = apenas clientes com status "Ativo" (sem atraso, sem bloqueio).<br>
    Use o toggle abaixo para alterar o modo de cálculo.
    </div>
    """, unsafe_allow_html=True)
    
    col_modo1, col_modo2 = st.columns([1, 3])
    with col_modo1:
        modo_ativos_toggle = st.toggle(
            "Considerar 'Financeiro em Atraso' e 'Bloqueio Automático' como Ativos",
            value=False,
            key="modo_ativos_toggle",
            help="Quando ligado: Ativos incluem também clientes em atraso e bloqueados"
        )
    
    modo_param = "todos_ativos" if modo_ativos_toggle else "somente_ativos"
    
    with col_modo2:
        if modo_ativos_toggle:
            st.success("✅ Modo atual: **Todos os Ocupados** = Ativos + Em Atraso + Bloqueio Automático")
        else:
            st.warning("⚠️ Modo atual: **Somente Ativos Limpos** = Apenas status 'Ativo' puro")
    
    st.markdown("---")
    
    dashboard_df = gerar_dashboard_principal(df_clientes, df_condominios, modo_param)
    
    if not dashboard_df.empty:
        col1, col2, col3, col4 = st.columns(4)
        total_ativos = dashboard_df["Qtd Ativos"].sum()
        total_atrasos = dashboard_df["Total Atrasos"].sum()
        total_apartamentos = dashboard_df["Total Apartamentos"].sum()
        total_ocupados = dashboard_df["Total Ocupados"].sum()
        media_penetracao = dashboard_df["% Ativos (Penetração)"].mean()
        
        col1.metric("👥 Total de Ativos", formatar_numero_br(total_ativos))
        col2.metric("⚠️ Total em Atraso", formatar_numero_br(total_atrasos))
        col3.metric("🏢 Total de Apartamentos", formatar_numero_br(total_apartamentos))
        col4.metric("📈 Penetração Média", f"{media_penetracao:.1f}%")
        
        condos_sem_clientes = len(dashboard_df[dashboard_df["Qtd Ativos"] == 0])
        if condos_sem_clientes > 0:
            st.info(f"📌 **{condos_sem_clientes} condomínios** sem clientes ativos (oportunidades de expansão)")
        
        df_exibir = dashboard_df if len(dashboard_df) <= 500 else dashboard_df.head(500)
        if len(dashboard_df) > 500:
            st.caption(f"⚠️ Exibindo apenas 500 de {len(dashboard_df)} condomínios. Use exportação para ver todos.")
        
        st.dataframe(
            df_exibir, 
            use_container_width=True,
            height=500,
            column_config={
                "Data de Implantação": st.column_config.DateColumn(format="DD/MM/YYYY"),
                "% Ativos (Penetração)": st.column_config.ProgressColumn(format="%.1f%%", min_value=0, max_value=100),
                "% Capacidade de Exploração": st.column_config.ProgressColumn(format="%.1f%%", min_value=0, max_value=100),
                "% Atraso": st.column_config.ProgressColumn(format="%.1f%%", min_value=0, max_value=100),
                "Total Apartamentos": st.column_config.NumberColumn(format="%d"),
                "Qtd Ativos": st.column_config.NumberColumn(format="%d"),
                "Total Atrasos": st.column_config.NumberColumn(format="%d"),
                "Desativados": st.column_config.NumberColumn(format="%d"),
                "Total Ocupados": st.column_config.NumberColumn(format="%d"),
                "Ativos Puros": st.column_config.NumberColumn(format="%d"),
                "Em Atraso": st.column_config.NumberColumn(format="%d"),
                "Bloqueio Automático": st.column_config.NumberColumn(format="%d"),
            }
        )
        
        output = io.BytesIO()
        with pd.ExcelWriter(output, engine='openpyxl') as writer:
            dashboard_df.to_excel(writer, sheet_name='Dashboard Principal', index=False)
            df_clientes.to_excel(writer, sheet_name='Dados Clientes', index=False)
            df_condominios.to_excel(writer, sheet_name='Condomínios', index=False)
            if df_parcelas is not None and not df_parcelas.empty:
                df_parcelas.to_excel(writer, sheet_name='Base Parcelas', index=False)
        output.seek(0)
        
        st.download_button(
            "📥 Exportar Dashboard Completo",
            output,
            f"dashboard_condominios_{datetime.now().strftime('%Y%m%d')}.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            use_container_width=True
        )
    
    # ==================== ABAS DE ANÁLISE ====================
    st.markdown("---")
    
    # AGORA SÃO 11 ABAS (NOVA: CRESCIMENTO POR CONDOMÍNIO)
    tab1, tab2, tab3, tab4, tab5, tab6, tab7, tab8, tab9, tab10, tab11 = st.tabs([
        "🎯 Penetração", "💰 Receita Potencial", "⚠️ Inadimplência", 
        "📉 Churn", "⚔️ Concorrência", "📍 Análise por Zona", 
        "⏳ Maturidade", "🎯 Consulta de Crédito", "📈 Análise Temporal",
        "⭐ MEUS ACOMPANHAMENTOS",
        "📈 CRESCIMENTO POR CONDOMÍNIO"
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
        
        df_receita = calcular_receita_potencial(df_penetracao_base, ticket_medio=ticket)
        
        if not df_receita.empty:
            fig = go.Figure(go.Waterfall(
                name="Receita", 
                orientation="v", 
                measure=["relative"] * len(df_receita.head(15)),
                x=df_receita.head(15)["Condomínio"], 
                y=df_receita.head(15)["receita_potencial"],
                textposition="outside", 
                text=[formatar_moeda_br(v) for v in df_receita.head(15)["receita_potencial"]]
            ))
            fig.update_layout(
                title="💰 Receita Potencial Não Explorada (Top 15)", 
                showlegend=False, 
                height=500
            )
            st.plotly_chart(fig, use_container_width=True, config={'displayModeBar': False})
            
            st.dataframe(
                df_receita.sort_values("receita_potencial", ascending=False).head(20)[
                    ["Condomínio", "Região", "clientes_ativos", "potencial_clientes", 
                     "receita_atual", "receita_potencial", "gap_receita"]
                ],
                use_container_width=True,
                height=400,
                column_config={
                    "receita_atual": st.column_config.NumberColumn(format="R$ %.2f"),
                    "receita_potencial": st.column_config.NumberColumn(format="R$ %.2f"),
                    "gap_receita": st.column_config.ProgressColumn(format="%.1f%%", min_value=0, max_value=1000),
                }
            )
    
    # TAB 3: INADIMPLÊNCIA
    with tab3:
        st.subheader("⚠️ Análise de Inadimplência por Condomínio")
        
        has_parcelas = df_parcelas is not None and not df_parcelas.empty
        
        if has_parcelas:
            st.markdown("""
            <div style="background-color:#e8f4f8; padding:15px; border-radius:10px; margin-bottom:20px;">
            <strong>📋 Como a inadimplência é calculada:</strong><br>
            A análise de inadimplência utiliza <strong>TRÊS visões diferentes</strong> para melhor compreensão:
            <ol>
                <li><strong>🔴 Visão Completa (Status Acesso)</strong> - Baseada na coluna "STATUS ACESSO" do arquivo de dados</li>
                <li><strong>🟡 Visão Financeiro Histórico</strong> - Baseada na coluna "FINANCEIRO EM ATRASO" (último atraso registrado)</li>
                <li><strong>🟢 Visão Real (Parcelas Vencidas)</strong> - Baseada na aba "Base Parcelas" com data de vencimento + status "A receber"</li>
            </ol>
            A <strong>Visão Real</strong> é a mais precisa para situação atual de inadimplência!
            </div>
            """, unsafe_allow_html=True)
        else:
            st.markdown("""
            <div style="background-color:#e8f4f8; padding:15px; border-radius:10px; margin-bottom:20px;">
            <strong>📋 Como a inadimplência é calculada:</strong><br>
            A análise de inadimplência é baseada na coluna <strong>"STATUS ACESSO"</strong> do arquivo de dados.
            Clientes com status "Financeiro em atraso" ou "Bloqueio Automático" são considerados inadimplentes.
            </div>
            """, unsafe_allow_html=True)
        
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
                key="visao_inadimplencia",
                help="Visão Real é a mais precisa, baseada em parcelas vencidas e não pagas"
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
            
            st.info("🔴 **Visão por Status Acesso:** Considera inadimplentes clientes com status 'Financeiro em atraso' ou 'Bloqueio Automático'")
            
        elif visao_selecionada == "🟡 Visão Financeiro Histórico":
            df_inadimplencia = analisar_inadimplencia_por_status(df_clientes, df_condominios, incluir_desativados=True)
            st.info("🟡 **Visão Financeiro Histórico:** Baseada na coluna 'FINANCEIRO EM ATRASO' (último atraso registrado)")
        else:
            df_inadimplencia, parcelas_detalhe = analisar_inadimplencia_por_parcelas(df_clientes, df_condominios, df_parcelas)
            st.success("🟢 **Visão Real (Parcelas Vencidas):** Baseada em parcelas com data de vencimento passada e status 'A receber'")
        
        if not df_inadimplencia.empty:
            total_condominios = len(df_inadimplencia)
            total_inadimplentes = df_inadimplencia["total_inadimplentes"].sum() if "total_inadimplentes" in df_inadimplencia.columns else 0
            total_clientes_analisados = df_inadimplencia["total_clientes"].sum() if "total_clientes" in df_inadimplencia.columns else 0
            media_inadimplencia = df_inadimplencia["taxa_inadimplencia"].mean()
            
            col1, col2, col3, col4 = st.columns(4)
            col1.metric("🏢 Condomínios Analisados", formatar_numero_br(total_condominios))
            col2.metric("⚠️ Total Inadimplentes", formatar_numero_br(total_inadimplentes))
            col3.metric("👥 Total Clientes", formatar_numero_br(total_clientes_analisados))
            col4.metric("📊 Média Inadimplência", f"{media_inadimplencia:.1f}%")
            
            if visao_selecionada == "🟢 Visão Real (Parcelas Vencidas)" and "valor_total_atraso" in df_inadimplencia.columns:
                valor_total_atraso = df_inadimplencia["valor_total_atraso"].sum()
                st.metric("💰 Valor Total em Atraso", formatar_moeda_br(valor_total_atraso))
            
            st.markdown("---")
            
            st.markdown("#### 📊 Top 15 Condomínios com Maior Taxa de Inadimplência")
            
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
            fig1.update_layout(yaxis_title="Taxa de Inadimplência (%)", xaxis_title="")
            st.plotly_chart(fig1, use_container_width=True, config={'displayModeBar': False})
            
            if visao_selecionada == "🟢 Visão Real (Parcelas Vencidas)" and "valor_total_atraso" in df_inadimplencia.columns:
                st.markdown("#### 💰 Top 15 Condomínios com Maior Valor em Atraso")
                
                fig_valor = px.bar(
                    df_inadimplencia.head(15),
                    x="Condomínio",
                    y="valor_total_atraso",
                    color="valor_total_atraso",
                    color_continuous_scale="Oranges",
                    text="valor_total_atraso",
                    title="Top 15 - Valor Total em Atraso por Condomínio"
                )
                fig_valor.update_traces(texttemplate='%{text:.2f}', textposition='outside')
                fig_valor.update_layout(yaxis_title="Valor em Atraso (R$)", xaxis_title="")
                st.plotly_chart(fig_valor, use_container_width=True, config={'displayModeBar': False})
            
            with st.expander("📋 Ver Tabela Completa de Inadimplência"):
                df_exibir = df_inadimplencia if len(df_inadimplencia) <= 500 else df_inadimplencia.head(500)
                if len(df_inadimplencia) > 500:
                    st.caption(f"⚠️ Exibindo apenas 500 de {len(df_inadimplencia)} condomínios.")
                
                if visao_selecionada == "🟢 Visão Real (Parcelas Vencidas)":
                    colunas_exibir = ["Condomínio", "Região", "Apartamentos", "total_clientes", 
                                     "total_inadimplentes", "taxa_inadimplencia", "valor_total_atraso", "total_parcelas_vencidas"]
                    colunas_existentes = [c for c in colunas_exibir if c in df_inadimplencia.columns]
                    
                    st.dataframe(
                        df_exibir[colunas_existentes], 
                        use_container_width=True,
                        height=400,
                        column_config={
                            "taxa_inadimplencia": st.column_config.ProgressColumn("Taxa Inadimplência", format="%.1f%%", min_value=0, max_value=100),
                            "valor_total_atraso": st.column_config.NumberColumn("Valor em Atraso", format="R$ %.2f"),
                            "Apartamentos": st.column_config.NumberColumn("Apartamentos", format="%d"),
                            "total_clientes": st.column_config.NumberColumn("Total Clientes", format="%d"),
                            "total_inadimplentes": st.column_config.NumberColumn("Total Inadimplentes", format="%d"),
                            "total_parcelas_vencidas": st.column_config.NumberColumn("Parcelas Vencidas", format="%d"),
                        }
                    )
                else:
                    st.dataframe(
                        df_exibir[[
                            "Condomínio", "Região", "Apartamentos", 
                            "total_clientes", "Em Dia", "Em Atraso", "total_inadimplentes", "taxa_inadimplencia"
                        ]], 
                        use_container_width=True,
                        height=400,
                        column_config={
                            "taxa_inadimplencia": st.column_config.ProgressColumn("Taxa Inadimplência", format="%.1f%%", min_value=0, max_value=100),
                            "Apartamentos": st.column_config.NumberColumn("Apartamentos", format="%d"),
                            "total_clientes": st.column_config.NumberColumn("Total Clientes", format="%d"),
                            "Em Dia": st.column_config.NumberColumn("Em Dia", format="%d"),
                            "Em Atraso": st.column_config.NumberColumn("Em Atraso", format="%d"),
                            "total_inadimplentes": st.column_config.NumberColumn("Total Inadimplentes", format="%d"),
                        }
                    )
            
            if visao_selecionada == "🟢 Visão Real (Parcelas Vencidas)" and 'parcelas_detalhe' in locals() and not parcelas_detalhe.empty:
                with st.expander("📋 Ver Detalhamento de Parcelas Vencidas"):
                    st.dataframe(
                        parcelas_detalhe,
                        use_container_width=True,
                        height=400,
                        column_config={
                            "Data Vencimento": st.column_config.DateColumn(format="DD/MM/YYYY"),
                            "Valor": st.column_config.NumberColumn(format="R$ %.2f"),
                        }
                    )
            
            output_inad = io.BytesIO()
            with pd.ExcelWriter(output_inad, engine='openpyxl') as writer:
                df_inadimplencia.to_excel(writer, sheet_name='Inadimplencia', index=False)
                if visao_selecionada == "🟢 Visão Real (Parcelas Vencidas)" and 'parcelas_detalhe' in locals() and not parcelas_detalhe.empty:
                    parcelas_detalhe.to_excel(writer, sheet_name='Parcelas_Vencidas', index=False)
            output_inad.seek(0)
            
            st.download_button(
                f"📥 Exportar Análise de Inadimplência - {visao_selecionada}",
                output_inad,
                f"inadimplencia_condominios_{datetime.now().strftime('%Y%m%d')}.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                use_container_width=True
            )
    
    # TAB 4: CHURN
    with tab4:
        st.subheader("📉 Análise de Churn (Cancelamentos) por Condomínio")
        df_churn = analisar_churn(df_clientes, df_condominios)
        
        if not df_churn.empty:
            fig = px.bar(
                df_churn.head(15),
                x="Condomínio",
                y="churn_rate",
                color="churn_rate",
                color_continuous_scale="Reds",
                title="Top 15 Condomínios com Maior Taxa de Cancelamento"
            )
            st.plotly_chart(fig, use_container_width=True, config={'displayModeBar': False})
            
            with st.expander("📋 Tabela Completa de Churn"):
                st.dataframe(
                    df_churn[["Condomínio", "Região", "Ativo", "Desativado", "churn_rate"]], 
                    use_container_width=True,
                    height=400
                )
    
    # TAB 5: CONCORRÊNCIA
    with tab5:
        st.subheader("⚔️ Análise Competitiva por Concorrente")
        df_penetracao_base = calcular_penetracao(df_clientes, df_condominios)
        df_concorrencia = correlacao_concorrencia(df_penetracao_base, df_condominios)
        
        if not df_concorrencia.empty:
            fig = px.bar(
                df_concorrencia, 
                x="Principal Concorrente", 
                y="penetracao_ponderada", 
                color="penetracao_ponderada", 
                color_continuous_scale="RdYlGn",
                title="Penetração Média por Concorrente Principal"
            )
            st.plotly_chart(fig, use_container_width=True, config={'displayModeBar': False})
            
            st.dataframe(df_concorrencia, use_container_width=True)
        else:
            st.info("⚠️ Dados de concorrentes não disponíveis na planilha.")
    
    # TAB 6: ANÁLISE POR ZONA
    with tab6:
        st.subheader("📍 Análise Consolidada por Zona/Região")
        
        dashboard_para_zona = gerar_dashboard_principal(df_clientes, df_condominios, "somente_ativos")
        
        if not dashboard_para_zona.empty and "Região" in dashboard_para_zona.columns:
            zona_stats = analisar_por_zona(dashboard_para_zona)
            
            if not zona_stats.empty:
                st.dataframe(zona_stats, use_container_width=True)
                
                col1, col2 = st.columns(2)
                with col1:
                    fig_ativos = px.bar(
                        zona_stats, 
                        x="Região", 
                        y="total_ativos", 
                        color="percentual_ativos",
                        title="Total de Ativos por Região",
                        color_continuous_scale="Viridis"
                    )
                    st.plotly_chart(fig_ativos, use_container_width=True, config={'displayModeBar': False})
                
                with col2:
                    fig_penetracao = px.bar(
                        zona_stats, 
                        x="Região", 
                        y="media_penetracao", 
                        color="media_penetracao",
                        title="Penetração Média por Região (%)",
                        color_continuous_scale="Blues"
                    )
                    st.plotly_chart(fig_penetracao, use_container_width=True, config={'displayModeBar': False})
        else:
            st.warning("⚠️ Dados insuficientes para análise por região.")
    
    # TAB 7: MATURIDADE
    with tab7:
        st.subheader("⏳ Análise de Maturidade dos Condomínios")
        
        df_maturidade = preparar_dados_maturidade(df_clientes, df_condominios)
        df_maturidade["classificacao_maturidade"] = df_maturidade.apply(
            lambda row: classificar_maturidade(row, CONDOMINIOS_CONFIG['meses_maturidade_limite']), axis=1)
        
        st.markdown("#### 📊 Distribuição por Maturidade")
        maturidade_counts = df_maturidade["classificacao_maturidade"].value_counts().reset_index()
        maturidade_counts.columns = ["Classificação", "Quantidade"]
        
        fig_maturidade = px.pie(
            maturidade_counts, 
            values="Quantidade", 
            names="Classificação",
            title="Distribuição dos Condomínios por Maturidade",
            hole=0.4
        )
        st.plotly_chart(fig_maturidade, use_container_width=True, config={'displayModeBar': False})
        
        with st.expander("📋 Ver Tabela Completa de Maturidade"):
            df_exibir = df_maturidade if len(df_maturidade) <= 500 else df_maturidade.head(500)
            if len(df_maturidade) > 500:
                st.caption(f"⚠️ Exibindo apenas 500 de {len(df_maturidade)} condomínios.")
            
            st.dataframe(
                df_exibir[[
                    "Condomínio", "Data cadastro", "meses_cadastro", "Região", 
                    "Apartamentos", "ativos", "percentual_ativos", "total_ocupados",
                    "classificacao_maturidade"
                ]], 
                use_container_width=True,
                height=400,
                column_config={
                    "Data cadastro": st.column_config.DateColumn(format="DD/MM/YYYY"),
                    "percentual_ativos": st.column_config.ProgressColumn(format="%.1f%%", min_value=0, max_value=100),
                }
            )
        
        output_maturidade = io.BytesIO()
        with pd.ExcelWriter(output_maturidade, engine='openpyxl') as writer:
            df_maturidade.to_excel(writer, sheet_name='Maturidade', index=False)
        output_maturidade.seek(0)
        
        st.download_button(
            "📥 Exportar Análise de Maturidade",
            output_maturidade,
            f"maturidade_condominios_{datetime.now().strftime('%Y%m%d')}.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            use_container_width=True
        )
    
    # TAB 8: CONSULTA DE CRÉDITO
    with tab8:
        st.subheader("🎯 Análise de Condomínios para Consulta de Crédito")
        
        st.markdown("""
        <div style="background-color:#e8f4f8; padding:15px; border-radius:10px; margin-bottom:20px;">
        <strong>📋 Como funciona a Consulta de Crédito:</strong><br>
        Esta análise identifica condomínios com <strong>ALTA INCIDÊNCIA DE INADIMPLÊNCIA</strong>, 
        que são os principais candidatos para ações de recuperação de crédito e consulta de crédito.
        <br><br>
        <strong>📌 Instruções:</strong>
        <ol>
            <li>Configure os parâmetros abaixo conforme sua estratégia</li>
            <li>Você pode <strong>desativar o filtro de valor mínimo</strong> se desejar</li>
            <li>Clique em <strong>"Aplicar Filtros e Gerar Ranking"</strong></li>
            <li>Analise os resultados e exporte a lista</li>
        </ol>
        </div>
        """, unsafe_allow_html=True)
        
        if df_parcelas is None or df_parcelas.empty:
            st.warning("⚠️ Aba 'Base Parcelas' não encontrada. A análise de consulta de crédito requer dados de parcelas.")
            st.info("Por favor, faça upload de uma planilha que contenha a aba 'Base Parcelas'.")
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
                    st.warning("⚠️ Nenhuma inadimplência encontrada com os critérios atuais.")
                    st.info("Tente ajustar os filtros para um período maior ou taxas menores.")
                else:
                    col1, col2, col3, col4 = st.columns(4)
                    with col1:
                        st.metric("📅 Dias de Atraso", f"{filtros['dias_atraso']} dias")
                    with col2:
                        st.metric("📆 Data Referência", filtros['data_referencia'].strftime("%d/%m/%Y"))
                    with col3:
                        total_inadimplentes = df_inad_periodo["total_clientes_inadimplentes"].sum()
                        st.metric("👥 Total Inadimplentes", formatar_numero_br(total_inadimplentes))
                    with col4:
                        media_dias = df_inad_periodo["media_dias_atraso"].mean()
                        st.metric("⏱️ Média Dias Atraso", f"{media_dias:.0f} dias")
                    
                    st.markdown("---")
                    
                    df_aptos, df_top_oportunidades = identificar_condominios_aptos_consulta_flexivel_otimizado(
                        _df_fingerprint(df_inad_periodo),
                        filtros['taxa_minima'],
                        filtros['min_inadimplentes'] if filtros['min_inadimplentes'] > 0 else 0,
                        filtros['valor_minimo_atraso'],
                        filtros['ativar_filtro_valor'],
                        df_inad_periodo.shape
                    )
                    
                    render_painel_condominios_aptos(df_aptos, df_top_oportunidades)
                    
                    if not df_aptos.empty:
                        st.markdown("---")
                        st.subheader("📄 Detalhamento Adicional")
                        
                        col_detalhe1, col_detalhe2 = st.columns([1, 2])
                        with col_detalhe1:
                            mostrar_detalhe = st.checkbox("Mostrar detalhamento de parcelas vencidas", key="mostrar_detalhe_parcelas")
                        
                        if mostrar_detalhe and not df_aptos.empty:
                            condominios_lista = df_aptos["Condomínio"].tolist()
                            if condominios_lista:
                                cond_selecionado = st.selectbox(
                                    "Selecione um condomínio para ver detalhes:",
                                    condominios_lista,
                                    key="select_cond_detalhe"
                                )
                                
                                if cond_selecionado:
                                    cond_id = df_aptos[df_aptos["Condomínio"] == cond_selecionado]["ID"].iloc[0]
                                    parcelas_top = df_parcelas_vencidas[df_parcelas_vencidas["ID"] == cond_id]
                                    
                                    if not parcelas_top.empty:
                                        st.markdown(f"**📄 Parcelas Vencidas - {cond_selecionado}**")
                                        st.dataframe(
                                            parcelas_top[["RAZAO SOCIAL/NOME", "DATA DO VENCIMENTO", "DIAS_ATRASO", "FAIXA_ATRASO", "VALOR"]],
                                            use_container_width=True,
                                            height=400,
                                            column_config={
                                                "DATA DO VENCIMENTO": st.column_config.DateColumn(format="DD/MM/YYYY"),
                                                "VALOR": st.column_config.NumberColumn("Valor", format="R$ %.2f"),
                                                "DIAS_ATRASO": st.column_config.NumberColumn("Dias", format="%d"),
                                            }
                                        )
            else:
                st.info("🔧 Configure os parâmetros acima e clique em 'Aplicar Filtros e Gerar Ranking' para iniciar a análise.")
                
                st.markdown("""
                <div style="background-color:#f0f2f6; padding:20px; border-radius:10px; margin-top:20px;">
                <h4>🎯 Exemplo de uso:</h4>
                <ul>
                    <li><strong>Para identificar inadimplência grave:</strong> 30+ dias, taxa > 40%</li>
                    <li><strong>Para identificar inadimplência leve:</strong> 15+ dias, taxa > 20%</li>
                    <li><strong>Para ignorar valor mínimo:</strong> Desmarque a opção "Ativar filtro de valor mínimo"</li>
                    <li><strong>Para incluir condomínios pequenos:</strong> Defina mínimo de inadimplentes como 0</li>
                </ul>
                </div>
                """, unsafe_allow_html=True)
    
    # TAB 9: ANÁLISE TEMPORAL
    with tab9:
        st.subheader("📈 Análise Temporal de Clientes por Condomínio")
        
        st.markdown("""
        <div style="background-color:#e8f4f8; padding:15px; border-radius:10px; margin-bottom:20px;">
        <strong>🎯 Como funciona:</strong><br>
        Selecione um condomínio e um período para visualizar a evolução do número de clientes ativos ao longo do tempo.
        Ideal para acompanhar o impacto de campanhas e ações comerciais em condomínios específicos.
        </div>
        """, unsafe_allow_html=True)
        
        if df_clientes is None or df_clientes.empty or df_condominios is None or df_condominios.empty:
            st.warning("⚠️ Nenhum dado carregado para análise.")
        else:
            df_clientes_temp = df_clientes.copy()
            df_condominios_temp = df_condominios.copy()
            
            if 'CONDOMANIO' in df_clientes_temp.columns:
                df_clientes_temp['CONDOMANIO'] = pd.to_numeric(df_clientes_temp['CONDOMANIO'], errors='coerce').fillna(0).astype(int)
            if 'ID' in df_condominios_temp.columns:
                df_condominios_temp['ID'] = pd.to_numeric(df_condominios_temp['ID'], errors='coerce').fillna(0).astype(int)
            
            data_col = identificar_coluna_data(df_clientes_temp)
            
            if data_col is None:
                st.error("❌ Coluna de data de cadastro não encontrada. Análise temporal indisponível.")
                st.info("Verifique se a planilha possui uma coluna com data de cadastro (ex: 'Data cadastro', 'data_cadastro')")
            else:
                df_clientes_temp[data_col] = pd.to_datetime(df_clientes_temp[data_col], errors='coerce')
                df_clientes_temp = df_clientes_temp.dropna(subset=[data_col])
                
                if df_clientes_temp.empty:
                    st.warning("⚠️ Nenhuma data de cadastro válida encontrada.")
                else:
                    df_clientes_temp['status_classificacao'] = classificar_status_serie(df_clientes_temp.get('STATUS ACESSO', pd.Series()))
                    df_clientes_temp['is_active'] = df_clientes_temp['status_classificacao'] == 'Ativo'
                    
                    st.markdown("### 🏢 Selecione o Condomínio")
                    
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
                        
                        st.markdown("### 📅 Período de Análise")
                        
                        col1, col2, col3 = st.columns([2, 2, 1])
                        
                        with col1:
                            periodo_preset = st.selectbox(
                                "Período pré-definido:",
                                options=["Personalizado", "Últimos 3 meses", "Últimos 6 meses", "Último ano", "Últimos 2 anos", "Todos os dados"],
                                key="temporal_periodo_preset"
                            )
                        
                        with col2:
                            data_inicio = None
                            data_fim = datetime.now().replace(tzinfo=None)
                            
                            if periodo_preset == "Personalizado":
                                col_data1, col_data2 = st.columns(2)
                                with col_data1:
                                    data_inicio_date = st.date_input("Data inicial:", value=datetime.now().date() - timedelta(days=180), key="temporal_data_inicio")
                                with col_data2:
                                    data_fim_date = st.date_input("Data final:", value=datetime.now().date(), key="temporal_data_fim")
                                data_inicio = datetime.combine(data_inicio_date, datetime.min.time())
                                data_fim = datetime.combine(data_fim_date, datetime.min.time())
                            elif periodo_preset == "Últimos 3 meses":
                                data_inicio = datetime.now().replace(tzinfo=None) - timedelta(days=90)
                            elif periodo_preset == "Últimos 6 meses":
                                data_inicio = datetime.now().replace(tzinfo=None) - timedelta(days=180)
                            elif periodo_preset == "Último ano":
                                data_inicio = datetime.now().replace(tzinfo=None) - timedelta(days=365)
                            elif periodo_preset == "Últimos 2 anos":
                                data_inicio = datetime.now().replace(tzinfo=None) - timedelta(days=730)
                            elif periodo_preset == "Todos os dados":
                                data_inicio = df_clientes_temp[data_col].min()
                        
                        with st.spinner(f"🔄 Analisando evolução do condomínio '{condominio_nome}'..."):
                            clientes_condominio = df_clientes_temp[df_clientes_temp['CONDOMANIO'] == condominio_id].copy()
                            
                            if clientes_condominio.empty:
                                st.warning(f"⚠️ Nenhum cliente encontrado para o condomínio '{condominio_nome}'.")
                            else:
                                clientes_condominio = clientes_condominio[
                                    (clientes_condominio[data_col] >= data_inicio) & 
                                    (clientes_condominio[data_col] <= data_fim)
                                ].copy()
                                
                                if clientes_condominio.empty:
                                    st.warning(f"⚠️ Nenhum cliente encontrado para o condomínio '{condominio_nome}' no período selecionado.")
                                else:
                                    clientes_condominio = clientes_condominio.sort_values(data_col)
                                    clientes_condominio['data_normalizada'] = clientes_condominio[data_col].dt.date
                                    
                                    novos_por_dia = clientes_condominio.groupby('data_normalizada').size().reset_index(name='novos_clientes')
                                    novos_por_dia = novos_por_dia.sort_values('data_normalizada')
                                    novos_por_dia['acumulado_ativos'] = novos_por_dia['novos_clientes'].cumsum()
                                    
                                    clientes_condominio['ano_mes'] = clientes_condominio[data_col].dt.to_period('M')
                                    novos_por_mes = clientes_condominio.groupby('ano_mes').size().reset_index(name='novos_clientes')
                                    novos_por_mes['acumulado_ativos'] = novos_por_mes['novos_clientes'].cumsum()
                                    novos_por_mes['ano_mes_str'] = novos_por_mes['ano_mes'].astype(str)
                                    
                                    info_condominio = df_condominios_temp[df_condominios_temp['ID'] == condominio_id].iloc[0]
                                    total_apartamentos = info_condominio.get('Apartamentos', 0)
                                    regiao = info_condominio.get('Região', 'N/A')
                                    
                                    total_clientes_periodo = len(clientes_condominio)
                                    primeiro_cadastro = clientes_condominio[data_col].min()
                                    ultimo_cadastro = clientes_condominio[data_col].max()
                                    penetracao = (total_clientes_periodo / total_apartamentos * 100) if total_apartamentos > 0 else 0
                                    
                                    st.markdown("---")
                                    st.subheader(f"📊 Evolução - {condominio_nome}")
                                    
                                    col1, col2, col3, col4, col5 = st.columns(5)
                                    with col1:
                                        st.metric("🏢 Total de Clientes", f"{total_clientes_periodo}")
                                    with col2:
                                        primeiro_str = primeiro_cadastro.strftime('%d/%m/%Y') if pd.notna(primeiro_cadastro) else "N/A"
                                        st.metric("📅 Primeiro Cadastro", primeiro_str)
                                    with col3:
                                        ultimo_str = ultimo_cadastro.strftime('%d/%m/%Y') if pd.notna(ultimo_cadastro) else "N/A"
                                        st.metric("📅 Último Cadastro", ultimo_str)
                                    with col4:
                                        st.metric("📈 Penetração", f"{penetracao:.1f}%")
                                    with col5:
                                        st.metric("📍 Região", regiao)
                                    
                                    st.markdown("---")
                                    st.subheader("📈 Evolução Acumulada de Clientes")
                                    
                                    granularidade = st.radio(
                                        "Granularidade do gráfico:",
                                        options=["Diário", "Mensal"],
                                        horizontal=True,
                                        key="temporal_granularidade"
                                    )
                                    
                                    if granularidade == "Diário":
                                        fig = px.line(
                                            novos_por_dia,
                                            x='data_normalizada',
                                            y='acumulado_ativos',
                                            title=f'📈 Evolução de Clientes - {condominio_nome}',
                                            labels={'data_normalizada': 'Data', 'acumulado_ativos': 'Total de Clientes Ativos'},
                                            markers=True
                                        )
                                        fig.update_traces(line=dict(color='#2ecc71', width=3), marker=dict(size=6))
                                    else:
                                        fig = px.line(
                                            novos_por_mes,
                                            x='ano_mes_str',
                                            y='acumulado_ativos',
                                            title=f'📈 Evolução Mensal de Clientes - {condominio_nome}',
                                            labels={'ano_mes_str': 'Mês/Ano', 'acumulado_ativos': 'Total de Clientes Ativos'},
                                            markers=True
                                        )
                                        fig.update_traces(line=dict(color='#2ecc71', width=3), marker=dict(size=8))
                                    
                                    fig.update_layout(height=450, xaxis_title="", yaxis_title="Total de Clientes Ativos", hovermode='x unified')
                                    st.plotly_chart(fig, use_container_width=True, config={'displayModeBar': False})
                                    
                                    st.subheader("📊 Novos Clientes por Período")
                                    
                                    if granularidade == "Diário":
                                        ultimos_30_dias = novos_por_dia.tail(30)
                                        fig_novos = px.bar(
                                            ultimos_30_dias,
                                            x='data_normalizada',
                                            y='novos_clientes',
                                            title=f'📊 Novos Clientes (últimos 30 dias) - {condominio_nome}',
                                            labels={'data_normalizada': 'Data', 'novos_clientes': 'Novos Clientes'},
                                            color='novos_clientes',
                                            color_continuous_scale='Viridis'
                                        )
                                    else:
                                        fig_novos = px.bar(
                                            novos_por_mes,
                                            x='ano_mes_str',
                                            y='novos_clientes',
                                            title=f'📊 Novos Clientes por Mês - {condominio_nome}',
                                            labels={'ano_mes_str': 'Mês/Ano', 'novos_clientes': 'Novos Clientes'},
                                            color='novos_clientes',
                                            color_continuous_scale='Viridis'
                                        )
                                    
                                    fig_novos.update_layout(height=400)
                                    st.plotly_chart(fig_novos, use_container_width=True, config={'displayModeBar': False})
                                    
                                    output = io.BytesIO()
                                    with pd.ExcelWriter(output, engine='openpyxl') as writer:
                                        novos_por_dia.to_excel(writer, sheet_name='Evolucao_Diaria', index=False)
                                        novos_por_mes[['ano_mes_str', 'novos_clientes', 'acumulado_ativos']].to_excel(writer, sheet_name='Evolucao_Mensal', index=False)
                                        
                                        cols_exportar = [data_col, 'CONDOMANIO', 'STATUS ACESSO', 'status_classificacao']
                                        cols_existentes = [c for c in cols_exportar if c in clientes_condominio.columns]
                                        clientes_condominio[cols_existentes].to_excel(writer, sheet_name='Clientes_Periodo', index=False)
                                        
                                        info_df = pd.DataFrame([{
                                            'Condomínio': condominio_nome,
                                            'Região': regiao,
                                            'Total Apartamentos': total_apartamentos,
                                            'Período Início': data_inicio.strftime('%d/%m/%Y') if hasattr(data_inicio, 'strftime') else str(data_inicio),
                                            'Período Fim': data_fim.strftime('%d/%m/%Y') if hasattr(data_fim, 'strftime') else str(data_fim),
                                            'Total Clientes no Período': total_clientes_periodo,
                                            'Penetração': f"{penetracao:.1f}%"
                                        }])
                                        info_df.to_excel(writer, sheet_name='Resumo', index=False)
                                    
                                    output.seek(0)
                                    
                                    st.download_button(
                                        "📥 Exportar Análise Temporal Completa",
                                        output,
                                        f"analise_temporal_{condominio_nome.replace(' ', '_')}_{datetime.now().strftime('%Y%m%d_%H%M')}.xlsx",
                                        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                                        use_container_width=True
                                    )
                                    
                                    st.markdown("---")
                                    st.subheader("💡 Insights")
                                    
                                    insights = []
                                    
                                    if not novos_por_mes.empty:
                                        melhor_mes = novos_por_mes.loc[novos_por_mes['novos_clientes'].idxmax()]
                                        insights.append(f"📈 **Melhor mês:** {melhor_mes['ano_mes_str']} com {melhor_mes['novos_clientes']} novos clientes")
                                    
                                    if len(novos_por_mes) >= 2:
                                        primeiro_valor = novos_por_mes.iloc[0]['acumulado_ativos']
                                        ultimo_valor = novos_por_mes.iloc[-1]['acumulado_ativos']
                                        if primeiro_valor > 0:
                                            crescimento_total = ((ultimo_valor - primeiro_valor) / primeiro_valor * 100)
                                            insights.append(f"📊 **Crescimento total no período:** {crescimento_total:.1f}%")
                                        else:
                                            insights.append(f"📊 **Crescimento total no período:** +{ultimo_valor} clientes")
                                    
                                    if total_apartamentos > 0:
                                        if penetracao >= 50:
                                            insights.append(f"🏆 **Alta penetração:** {penetracao:.1f}% dos apartamentos são clientes")
                                        elif penetracao >= 25:
                                            insights.append(f"📈 **Boa penetração:** {penetracao:.1f}% dos apartamentos são clientes")
                                        else:
                                            insights.append(f"🎯 **Potencial de crescimento:** Apenas {penetracao:.1f}% de penetração")
                                    
                                    if not novos_por_mes.empty:
                                        media_mensal = novos_por_mes['novos_clientes'].mean()
                                        insights.append(f"📅 **Média mensal:** {media_mensal:.1f} novos clientes por mês")
                                    
                                    for insight in insights:
                                        st.info(insight)
    
    # TAB 10: MEUS ACOMPANHAMENTOS
    with tab10:
        if db is not None:
            st.markdown("""
            <div style="background-color:#e8f4f8; padding:15px; border-radius:10px; margin-bottom:20px;">
            <strong>⭐ Meus Acompanhamentos - Integração com Prospecção</strong><br>
            Esta aba exibe os condomínios que você está acompanhando no módulo de prospecção,
            com todas as métricas e análises disponíveis nos relatórios.
            <br><br>
            <strong>📌 Como funciona:</strong>
            <ol>
                <li>Informe seu nome exatamente como aparece na coluna "Acompanhamento" da prospecção</li>
                <li>O sistema busca automaticamente os condomínios sob sua responsabilidade</li>
                <li>Exibe um dashboard completo com todas as métricas dos relatórios</li>
                <li>Permite exportar dados específicos dos seus condomínios</li>
            </ol>
            </div>
            """, unsafe_allow_html=True)
            
            nome_usuario = render_seletor_usuario()
            
            with st.spinner("🔄 Carregando seus condomínios da prospecção..."):
                meus_nomes, df_meus_prospeccao = carregar_meus_condominios_prospeccao(db)
                
                if meus_nomes and df_meus_prospeccao is not None:
                    st.session_state.meus_condominios_ids = meus_nomes
                    st.session_state.meus_condominios_nomes = df_meus_prospeccao
                    
                    render_dashboard_meus_acompanhamentos(
                        df_clientes, 
                        df_condominios, 
                        df_parcelas,
                        meus_nomes, 
                        df_meus_prospeccao
                    )
                else:
                    st.warning("⚠️ Nenhum condomínio encontrado em 'Meus Acompanhamentos'.")
                    st.info("""
                    💡 **Para configurar:**
                    1. Certifique-se de que a planilha de prospecção foi importada no módulo **prospeccao_condominios.py**
                    2. A planilha deve ter uma coluna **'Acompanhamento'** com seu nome
                    3. Seu nome no campo acima deve ser **exatamente igual** ao da planilha
                    4. Clique em **"Atualizar Lista de Meus Condomínios"** após corrigir
                    """)
                    
                    if st.button("🔄 Tentar recarregar novamente", use_container_width=True):
                        st.session_state.meus_condominios_ids = None
                        st.session_state.meus_condominios_nomes = None
                        st.rerun()
        else:
            st.warning("⚠️ Conexão com banco de dados não disponível para carregar Meus Acompanhamentos.")
    
    # TAB 11: CRESCIMENTO POR CONDOMÍNIO (NOVA)
    with tab11:
        if db is not None:
            # Buscar dados de meus condomínios para análise de crescimento
            meus_nomes, df_meus_prospeccao = carregar_meus_condominios_prospeccao(db)
            
            if meus_nomes and df_meus_prospeccao is not None:
                render_analise_crescimento_condominios(
                    df_clientes, 
                    df_condominios, 
                    df_meus_prospeccao,
                    data_inicio_padrao=datetime(2026, 6, 1)
                )
            else:
                st.warning("⚠️ Nenhum condomínio encontrado em 'Meus Acompanhamentos'.")
                st.info("""
                💡 **Para usar esta análise:**
                1. Certifique-se de que a planilha de prospecção foi importada no módulo **prospeccao_condominios.py**
                2. A planilha deve ter uma coluna **'Acompanhamento'** com seu nome
                3. A planilha de relatórios deve ter dados de clientes com data de cadastro
                4. Os nomes dos condomínios devem ser **exatamente iguais** em ambas as planilhas
                """)
                
                if st.button("🔄 Tentar recarregar dados de prospecção", use_container_width=True):
                    st.session_state.meus_condominios_ids = None
                    st.session_state.meus_condominios_nomes = None
                    st.rerun()
        else:
            st.warning("⚠️ Conexão com banco de dados não disponível para análise de crescimento.")

# ==================== FUNÇÃO PRINCIPAL ====================
def render_relatorios_condominios():
    """Função principal refatorada com todas as funcionalidades"""
    
    initialize_session_state()
    
    titulo_principal("🏢 Relatórios Estratégicos - Condomínios")
    st.markdown("Análise de penetração, receita potencial, inadimplência (3 visões), churn, concorrência, maturidade, análise temporal por condomínio, integração com Meus Acompanhamentos e análise de crescimento individual")
    
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
            st.warning("⚠️ Nenhum dado carregado. Faça upload ou selecione dados existentes.")
            if st.button("🔄 Tentar carregar novamente"):
                if carregar_dados_mais_recentes(db):
                    st.success("✅ Dados carregados!")
                    st.rerun()
    
    if st.session_state.exclusao_confirmada:
        if st.session_state.batch_id_a_excluir:
            confirmar_exclusao(db, st.session_state.batch_id_a_excluir)

if __name__ == "__main__":
    render_relatorios_condominios()
