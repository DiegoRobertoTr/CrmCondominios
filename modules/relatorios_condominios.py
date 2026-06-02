"""
Módulo de Relatórios de Condomínios para a DR Tracecom Suite Analítica.
Pode ser chamado via relatorios_condominios.render_relatorios_condominios()

Melhorias implementadas:
- GridFS para armazenamento de arquivos originais
- Pré-carregamento automático dos últimos dados
- Session state estruturado
- Exclusão com confirmação de senha
- Processamento otimizado com referência ao arquivo original
- Todas as abas do original: Penetração, Receita, Inadimplência (2 visões), Churn, Concorrência, Zona, Maturidade
- NOVO: Análise de inadimplência real baseada na aba "Base Parcelas"
- NOVO: Filtros na própria aba "Consulta de Crédito"
- NOVO: Opção de desativar filtro de valor mínimo
- NOVO: Identificação de condomínios aptos para consulta de crédito
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
    'meses_maturidade_limite': 18
}

# ==================== INICIALIZAÇÃO DO SESSION STATE ====================
def initialize_session_state():
    """Inicializa estado da sessão de forma estruturada"""
    defaults = {
        'condominios_dados_clientes': None,
        'condominios_dados_condominios': None,
        'condominios_dados_parcelas': None,
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
        'recarregar_dados': False
    }
    
    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value

# ==================== FUNÇÕES DE UI ====================
def titulo_principal(texto):
    st.markdown(f"<h1 style='font-size: 28px; font-weight: bold; color: #2c3e50;'>{texto}</h1>", unsafe_allow_html=True)

def subtitulo(texto):
    st.markdown(f"<h3 style='color: #34495e;'>{texto}</h3>", unsafe_allow_html=True)

# ==================== FUNÇÕES PARA CONSULTA DE CRÉDITO ====================

def render_filtros_consulta_credito():
    """Renderiza filtros dentro da aba Consulta de Crédito"""
    
    st.markdown("### ⚙️ Configuração da Análise")
    
    col1, col2 = st.columns(2)
    
    with col1:
        # Dias de atraso
        dias_atraso = st.slider(
            "📅 Dias de atraso para considerar inadimplente",
            min_value=1,
            max_value=90,
            value=30,
            step=5,
            key="consulta_dias_atraso",
            help="Cliente é considerado inadimplente se tiver parcelas vencidas há mais de X dias"
        )
        
        # Data de referência
        data_referencia = st.date_input(
            "📆 Data de referência",
            value=datetime.now().date(),
            key="consulta_data_ref",
            help="Data base para verificar vencimentos"
        )
    
    with col2:
        # Taxa mínima de inadimplência
        taxa_minima = st.slider(
            "📊 Taxa mínima de inadimplência (%)",
            min_value=0,
            max_value=100,
            value=30,
            step=5,
            key="consulta_taxa_minima",
            help="Condomínios com inadimplência acima deste percentual"
        )
        
        # Número mínimo de clientes inadimplentes
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
    
    # Checkbox para ativar/desativar filtro de valor mínimo
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
    
    # Botão para aplicar filtros
    aplicar_filtros = st.button(
        "🔍 Aplicar Filtros e Gerar Ranking",
        type="primary",
        use_container_width=True,
        key="botao_aplicar_filtros_consulta"
    )
    
    # Resumo dos filtros ativos
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

def analisar_inadimplencia_periodo(df_parcelas, df_clientes, df_condominios, 
                                   dias_atraso=30, data_referencia=None):
    """
    Analisa inadimplência considerando período específico de atraso
    
    Retorna:
    - DataFrame com análise detalhada por condomínio
    - DataFrame com clientes inadimplentes
    - DataFrame com parcelas vencidas no período
    """
    if df_parcelas is None or df_parcelas.empty:
        return pd.DataFrame(), pd.DataFrame(), pd.DataFrame()
    
    if data_referencia is None:
        data_referencia = datetime.now().replace(tzinfo=None)
    
    df_parcelas = df_parcelas.copy()
    df_clientes = df_clientes.copy()
    df_condominios = df_condominios.copy()
    
    # Normalizar IDs
    df_clientes["ID"] = pd.to_numeric(df_clientes["ID"], errors="coerce").fillna(0).astype(int)
    df_parcelas["ID"] = pd.to_numeric(df_parcelas["ID"], errors="coerce").fillna(0).astype(int)
    df_condominios["ID"] = pd.to_numeric(df_condominios["ID"], errors="coerce").fillna(0).astype(int)
    
    # Converter data de vencimento
    df_parcelas["DATA DO VENCIMENTO"] = pd.to_datetime(df_parcelas["DATA DO VENCIMENTO"], errors='coerce')
    
    # Calcular data limite (data_referencia - dias_atraso)
    data_limite = data_referencia - timedelta(days=dias_atraso)
    
    # Normalizar status
    df_parcelas["STATUS_NORMALIZADO"] = df_parcelas["STATUS"].str.upper().str.strip()
    
    # Identificar parcelas vencidas (considerando período)
    parcelas_vencidas = df_parcelas[
        (df_parcelas["DATA DO VENCIMENTO"] <= data_limite) &
        (df_parcelas["STATUS_NORMALIZADO"] == "A RECEBER")
    ].copy()
    
    if parcelas_vencidas.empty:
        return pd.DataFrame(), pd.DataFrame(), pd.DataFrame()
    
    # Calcular dias em atraso
    parcelas_vencidas["DIAS_ATRASO"] = (data_referencia - parcelas_vencidas["DATA DO VENCIMENTO"]).dt.days
    
    # Classificar faixa de atraso
    def classificar_faixa_atraso(dias):
        if dias <= 30:
            return "1-30 dias"
        elif dias <= 60:
            return "31-60 dias"
        elif dias <= 90:
            return "61-90 dias"
        else:
            return "90+ dias"
    
    parcelas_vencidas["FAIXA_ATRASO"] = parcelas_vencidas["DIAS_ATRASO"].apply(classificar_faixa_atraso)
    
    # Clientes inadimplentes
    clientes_inadimplentes = parcelas_vencidas["ID"].unique()
    
    # Detalhamento por cliente
    cliente_atraso = parcelas_vencidas.groupby("ID").agg(
        total_parcelas_vencidas=("ID", "count"),
        valor_total_atraso=("VALOR", "sum"),
        max_dias_atraso=("DIAS_ATRASO", "max"),
        media_dias_atraso=("DIAS_ATRASO", "mean")
    ).reset_index()
    
    # Mapear CONDOMANIO
    df_cliente_cond = df_clientes[["ID", "CONDOMANIO"]].drop_duplicates()
    cliente_atraso = cliente_atraso.merge(df_cliente_cond, on="ID", how="left")
    
    # Agregar por condomínio
    cond_agg = cliente_atraso.groupby("CONDOMANIO").agg(
        total_clientes_inadimplentes=("ID", "count"),
        total_parcelas_vencidas=("total_parcelas_vencidas", "sum"),
        valor_total_atraso=("valor_total_atraso", "sum"),
        media_dias_atraso=("media_dias_atraso", "mean"),
        max_dias_atraso=("max_dias_atraso", "max")
    ).reset_index()
    
    # Total de clientes por condomínio
    total_clientes_cond = df_clientes.groupby("CONDOMANIO").size().reset_index(name="total_clientes")
    cond_agg = cond_agg.merge(total_clientes_cond, on="CONDOMANIO", how="right")
    
    # Calcular taxa de inadimplência
    cond_agg["taxa_inadimplencia"] = (
        cond_agg["total_clientes_inadimplentes"] / cond_agg["total_clientes"].replace(0, np.nan) * 100
    ).round(2).fillna(0)
    
    # Adicionar informações do condomínio
    cols_merge = ["ID", "Condomínio", "Região", "Apartamentos"]
    cols_existentes = [c for c in cols_merge if c in df_condominios.columns]
    
    result = cond_agg.merge(
        df_condominios[cols_existentes],
        left_on="CONDOMANIO", right_on="ID", how="right"
    )
    
    # Preencher NAs
    result["total_clientes"] = result["total_clientes"].fillna(0).astype(int)
    result["total_clientes_inadimplentes"] = result["total_clientes_inadimplentes"].fillna(0).astype(int)
    result["total_parcelas_vencidas"] = result["total_parcelas_vencidas"].fillna(0).astype(int)
    result["valor_total_atraso"] = result["valor_total_atraso"].fillna(0)
    result["taxa_inadimplencia"] = result["taxa_inadimplencia"].fillna(0)
    result["media_dias_atraso"] = result["media_dias_atraso"].fillna(0)
    result["max_dias_atraso"] = result["max_dias_atraso"].fillna(0)
    
    return result.sort_values("taxa_inadimplencia", ascending=False).reset_index(drop=True), cliente_atraso, parcelas_vencidas

def identificar_condominios_aptos_consulta_flexivel(df_inadimplencia, taxa_minima=30, 
                                                     min_inadimplentes=5, valor_minimo_atraso=500,
                                                     ativar_filtro_valor=True):
    """
    Identifica condomínios aptos para consulta de crédito com opção de ignorar valor mínimo
    
    Retorna:
    - DataFrame com condomínios aptos
    - DataFrame com condomínios prioritários (melhores oportunidades)
    """
    if df_inadimplencia.empty:
        return pd.DataFrame(), pd.DataFrame()
    
    # Aplicar filtros básicos
    df_filtrado = df_inadimplencia[
        (df_inadimplencia["taxa_inadimplencia"] >= taxa_minima) &
        (df_inadimplencia["total_clientes_inadimplentes"] >= min_inadimplentes)
    ].copy()
    
    # Aplicar filtro de valor se ativado
    if ativar_filtro_valor and valor_minimo_atraso > 0:
        df_filtrado = df_filtrado[df_filtrado["valor_total_atraso"] >= valor_minimo_atraso]
    
    if df_filtrado.empty:
        return pd.DataFrame(), pd.DataFrame()
    
    # Calcular score de prioridade
    df_filtrado["score_prioridade"] = (
        df_filtrado["taxa_inadimplencia"] * 2 +
        df_filtrado["total_clientes_inadimplentes"] * 5 +
        df_filtrado["valor_total_atraso"] / 100
    ).round(2)
    
    # Classificar prioridade
    def classificar_prioridade(score):
        if score >= 200:
            return "🔥 PRIORIDADE MÁXIMA"
        elif score >= 100:
            return "🟠 Alta Prioridade"
        elif score >= 50:
            return "🟡 Média Prioridade"
        else:
            return "🟢 Baixa Prioridade"
    
    df_filtrado["prioridade"] = df_filtrado["score_prioridade"].apply(classificar_prioridade)
    
    # Ordenar por prioridade
    df_filtrado = df_filtrado.sort_values("score_prioridade", ascending=False).reset_index(drop=True)
    
    # Identificar top 10 oportunidades
    df_top_oportunidades = df_filtrado.head(10).copy()
    
    return df_filtrado, df_top_oportunidades

def render_painel_condominios_aptos(df_aptos, df_top_oportunidades):
    """Renderiza painel com condomínios aptos para consulta"""
    
    st.markdown("## 🎯 Condomínios Aptos para Consulta de Crédito")
    
    if df_aptos.empty:
        st.info("ℹ️ Nenhum condomínio atende aos critérios definidos. Ajuste os filtros acima.")
        return
    
    # Métricas resumidas
    col1, col2, col3, col4 = st.columns(4)
    col1.metric("🏢 Condomínios Aptos", len(df_aptos))
    col2.metric("👥 Total Inadimplentes", df_aptos["total_clientes_inadimplentes"].sum())
    col3.metric("💰 Valor Total em Atraso", formatar_moeda_br(df_aptos["valor_total_atraso"].sum()))
    col4.metric("📈 Média Inadimplência", f"{df_aptos['taxa_inadimplencia'].mean():.1f}%")
    
    st.markdown("---")
    
    # Top 10 oportunidades
    st.subheader("🏆 Top 10 Condomínios - Maior Potencial para Consulta")
    
    # Configurar colunas para exibição
    colunas_exibir = [
        "Condomínio", "Região", "total_clientes", "total_clientes_inadimplentes",
        "taxa_inadimplencia", "valor_total_atraso", "max_dias_atraso", "prioridade", "score_prioridade"
    ]
    
    colunas_existentes = [c for c in colunas_exibir if c in df_top_oportunidades.columns]
    
    st.dataframe(
        df_top_oportunidades[colunas_existentes],
        use_container_width=True,
        column_config={
            "taxa_inadimplencia": st.column_config.ProgressColumn("Taxa Inadimplência", format="%.1f%%", min_value=0, max_value=100),
            "valor_total_atraso": st.column_config.NumberColumn("Valor em Atraso", format="R$ %.2f"),
            "score_prioridade": st.column_config.NumberColumn("Score", format="%.0f"),
            "total_clientes": st.column_config.NumberColumn("Total Clientes", format="%d"),
            "total_clientes_inadimplentes": st.column_config.NumberColumn("Inadimplentes", format="%d"),
            "max_dias_atraso": st.column_config.NumberColumn("Máx Dias Atraso", format="%d"),
        }
    )
    
    # Gráfico de barras dos top 10
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
    fig_top.update_layout(height=500)
    st.plotly_chart(fig_top, use_container_width=True)
    
    # Gráfico de dispersão (taxa vs valor em atraso)
    st.subheader("📈 Análise de Concentração de Inadimplência")
    
    fig_scatter = px.scatter(
        df_aptos,
        x="taxa_inadimplencia",
        y="valor_total_atraso",
        size="total_clientes_inadimplentes",
        color="prioridade",
        hover_name="Condomínio",
        text="Condomínio",
        title="Concentração: Taxa vs Valor em Atraso",
        labels={
            "taxa_inadimplencia": "Taxa de Inadimplência (%)",
            "valor_total_atraso": "Valor Total em Atraso (R$)",
            "total_clientes_inadimplentes": "Nº Inadimplentes"
        }
    )
    fig_scatter.update_traces(textposition="top center", textfont_size=10)
    fig_scatter.update_layout(height=500)
    st.plotly_chart(fig_scatter, use_container_width=True)
    
    # Tabela completa dos aptos (expansível)
    with st.expander("📋 Ver Todos os Condomínios Aptos"):
        st.dataframe(
            df_aptos[colunas_existentes],
            use_container_width=True,
            column_config={
                "taxa_inadimplencia": st.column_config.ProgressColumn("Taxa Inadimplência", format="%.1f%%", min_value=0, max_value=100),
                "valor_total_atraso": st.column_config.NumberColumn("Valor em Atraso", format="R$ %.2f"),
            }
        )
    
    # Botão de exportação
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
        
        # Criar índices para acelerar consultas
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
        print("✅ Índices MongoDB criados/atualizados")
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
            valor = pd.to_datetime(valor_limpo, errors='coerce', format='mixed')
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
    
    for col in df.columns:
        col_lower = col.lower()
        eh_coluna_data = any(palavra in col_lower for palavra in 
                           ['data', 'date', 'cadastro', 'ativacao', 'cancelamento', 
                            'nascimento', 'renovacao', 'vencimento', 'credito'])
        
        if eh_coluna_data or pd.api.types.is_datetime64_any_dtype(df[col]):
            df[col] = pd.to_datetime(df[col], errors='coerce', format='mixed')
            df[col] = df[col].apply(lambda x: None if pd.isna(x) else x)
    
    return df

def safe_mongo_docs(df):
    """Converte DataFrame para lista de dicts seguros para o MongoDB"""
    import math
    import numpy as np
    
    df = df.copy()
    
    for col in df.columns:
        if pd.api.types.is_datetime64_any_dtype(df[col]):
            df[col] = df[col].apply(lambda x: None if pd.isna(x) else x)
    
    df = df.replace([np.nan, np.inf, -np.inf], None)
    
    records = df.to_dict('records')
    safe_records = []
    
    for doc in records:
        safe_doc = {}
        for k, v in doc.items():
            if v is None:
                safe_doc[k] = None
            elif pd.isna(v):
                safe_doc[k] = None
            elif isinstance(v, pd.Timestamp):
                try:
                    safe_doc[k] = v.to_pydatetime().replace(tzinfo=None)
                except (AttributeError, ValueError, TypeError):
                    safe_doc[k] = None
            elif isinstance(v, datetime):
                try:
                    if v.tzinfo is not None:
                        safe_doc[k] = v.replace(tzinfo=None)
                    else:
                        safe_doc[k] = v
                except (AttributeError, ValueError):
                    safe_doc[k] = None
            elif isinstance(v, float):
                if math.isnan(v) or math.isinf(v):
                    safe_doc[k] = None
                else:
                    safe_doc[k] = v
            elif hasattr(v, 'dtype'):
                try:
                    if np.issubdtype(v.dtype, np.datetime64):
                        if np.isnat(v):
                            safe_doc[k] = None
                        else:
                            ts = pd.Timestamp(v)
                            safe_doc[k] = ts.to_pydatetime().replace(tzinfo=None)
                        continue
                except (TypeError, AttributeError):
                    pass
                safe_doc[k] = v
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
    
    # Limpar apenas dados antigos deste módulo
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
    
    # Preparar dados de clientes
    df_clientes_limpo = converter_dataframe_dates(df_clientes)
    df_clientes_limpo["_import_timestamp"] = datetime.now().replace(tzinfo=None)
    df_clientes_limpo["_import_batch"] = batch_id
    df_clientes_limpo["source_file_id"] = metadata["source_file_id"]
    df_clientes_limpo["module"] = module
    
    docs = safe_mongo_docs(df_clientes_limpo)
    
    if docs:
        collection_clientes.insert_many(docs)
    
    # Preparar parcelas para o MongoDB
    if df_parcelas is not None and not df_parcelas.empty:
        df_parcelas_limpo = converter_dataframe_dates(df_parcelas)
        df_parcelas_limpo["_import_timestamp"] = datetime.now().replace(tzinfo=None)
        df_parcelas_limpo["_import_batch"] = batch_id
        df_parcelas_limpo["source_file_id"] = metadata["source_file_id"]
        df_parcelas_limpo["module"] = module
        
        parcelas_docs = safe_mongo_docs(df_parcelas_limpo)
        if parcelas_docs:
            collection_clientes.insert_many(parcelas_docs)
    
    # Preparar condomínios para metadados
    condominios_records = safe_mongo_docs(df_condominios)
    metadata["condominios"] = condominios_records
    
    # Salvar parcelas no metadado também
    if df_parcelas is not None and not df_parcelas.empty:
        metadata["has_parcelas"] = True
        metadata["total_parcelas"] = len(df_parcelas)
    else:
        metadata["has_parcelas"] = False
    
    metadata["module"] = module
    
    collection_meta.insert_one(metadata)
    
    return True

def carregar_dados_mais_recentes(db):
    """Carrega automaticamente os dados mais recentes do MongoDB"""
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
        
        cursor_clientes = db["condominios_relatorios"].find({
            "_import_batch": batch_id,
            "module": "condominios"
        })
        df_all = pd.DataFrame(list(cursor_clientes))
        
        if df_all.empty:
            return False
        
        # Separar clientes (que têm CONDOMANIO) de parcelas (que têm DATA DO VENCIMENTO)
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
            # Ler as 3 abas
            df_clientes = pd.read_excel(uploaded_file, sheet_name="Dados")
            df_condominios = pd.read_excel(uploaded_file, sheet_name="Condominios")
            
            # Tentar ler a aba Base Parcelas (opcional)
            try:
                df_parcelas = pd.read_excel(uploaded_file, sheet_name="Base Parcelas")
                st.info(f"📋 Aba 'Base Parcelas' encontrada com {len(df_parcelas)} registros")
            except Exception:
                df_parcelas = pd.DataFrame()
                st.warning("⚠️ Aba 'Base Parcelas' não encontrada. A análise de inadimplência real será limitada.")
            
            df_clientes = df_clientes.replace({pd.NaT: None, np.nan: None})
            df_condominios = df_condominios.replace({pd.NaT: None, np.nan: None})
            if not df_parcelas.empty:
                df_parcelas = df_parcelas.replace({pd.NaT: None, np.nan: None})
            
            # Validar colunas obrigatórias
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
            
            # Normalizar chaves
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
            
            # Normalizar ID nas parcelas
            if not df_parcelas.empty and "ID" in df_parcelas.columns:
                df_parcelas["ID"] = pd.to_numeric(
                    df_parcelas["ID"], errors="coerce"
                ).fillna(0).astype(int)
            
            df_clientes = converter_dataframe_dates(df_clientes)
            df_condominios = converter_dataframe_dates(df_condominios)
            if not df_parcelas.empty:
                df_parcelas = converter_dataframe_dates(df_parcelas)
            
            for col in df_clientes.columns:
                if pd.api.types.is_datetime64_any_dtype(df_clientes[col]):
                    df_clientes[col] = df_clientes[col].apply(lambda x: None if pd.isna(x) else x)
            
            for col in df_condominios.columns:
                if pd.api.types.is_datetime64_any_dtype(df_condominios[col]):
                    df_condominios[col] = df_condominios[col].apply(lambda x: None if pd.isna(x) else x)
            
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
                
                st.success(f"✅ {len(df_clientes)} clientes, {len(df_condominios)} condomínios e {len(df_parcelas)} parcelas processados!")
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
    """Gera dashboard principal"""
    if df_clientes is None or df_condominios is None:
        return pd.DataFrame()
    
    if "CONDOMANIO" not in df_clientes.columns or "ID" not in df_condominios.columns:
        return pd.DataFrame()
    
    df_clientes = df_clientes.copy()
    df_condominios = df_condominios.copy()
    
    df_condominios["ID"] = pd.to_numeric(df_condominios["ID"], errors="coerce").fillna(0).astype(int)
    df_clientes["CONDOMANIO"] = pd.to_numeric(df_clientes["CONDOMANIO"], errors="coerce").fillna(0).astype(int)
    df_condominios["Apartamentos"] = pd.to_numeric(df_condominios["Apartamentos"], errors="coerce").fillna(0).astype(int)
    
    df_clientes["status_classificacao"] = df_clientes["STATUS ACESSO"].apply(classificar_status)
    
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
    """Calcula taxa de penetração"""
    df_clientes = df_clientes.copy()
    df_condominios = df_condominios.copy()
    
    df_clientes["CONDOMANIO"] = pd.to_numeric(df_clientes["CONDOMANIO"], errors="coerce").fillna(0).astype(int)
    df_condominios["ID"] = pd.to_numeric(df_condominios["ID"], errors="coerce").fillna(0).astype(int)
    
    ativos = df_clientes[df_clientes["STATUS ACESSO"].str.lower().str.contains("ativo", na=False)]
    clientes_por_cond = ativos.groupby("CONDOMANIO").size().reset_index(name="clientes_ativos")
    
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
    
    def classificar_penetracao(taxa):
        if pd.isna(taxa):
            return "Baixa Presença"
        if taxa >= 50:
            return "🟢 Dominado"
        elif taxa >= 25:
            return "🟡 Em Crescimento"
        return "🔴 Baixa Presença"
    
    df_merged["classificacao"] = df_merged["taxa_penetracao"].apply(classificar_penetracao)
    return df_merged.sort_values("taxa_penetracao", ascending=False)

def analisar_inadimplencia_por_status(df_clientes, df_condominios, incluir_desativados=True):
    """
    Analisa inadimplência baseada na coluna FINANCEIRO EM ATRASO (modo legado)
    
    Parâmetros:
    - incluir_desativados=True: análise com TODOS os clientes
    - incluir_desativados=False: análise apenas com NÃO DESATIVADOS (recuperáveis)
    """
    df_clientes = df_clientes.copy()
    df_condominios = df_condominios.copy()
    
    # Normalizar chaves
    df_clientes["CONDOMANIO"] = pd.to_numeric(df_clientes["CONDOMANIO"], errors="coerce").fillna(0).astype(int)
    df_condominios["ID"] = pd.to_numeric(df_condominios["ID"], errors="coerce").fillna(0).astype(int)
    
    # Filtrar por status (se necessário)
    if not incluir_desativados:
        # Manter apenas clientes NÃO desativados
        df_clientes = df_clientes[
            ~df_clientes["STATUS ACESSO"].str.lower().str.contains("desativado|cancelado", na=False)
        ].copy()
    
    # Classificar inadimplência baseada apenas em FINANCEIRO EM ATRASO
    def classificar_inadimplencia(valor):
        if pd.isna(valor):
            return "Em Dia"
        valor_str = str(valor).strip().lower()
        if valor_str in ["", "00/00/0000", "0", "nan", "nat", "none", "null"]:
            return "Em Dia"
        return "Em Atraso"
    
    df_clientes["situacao_inadimplencia"] = df_clientes["FINANCEIRO EM ATRASO"].apply(classificar_inadimplencia)
    
    # Agrupar por condomínio
    inadimplencia = df_clientes.groupby(["CONDOMANIO", "situacao_inadimplencia"]).size().unstack(fill_value=0)
    
    # Garantir colunas existentes
    if "Em Atraso" not in inadimplencia.columns:
        inadimplencia["Em Atraso"] = 0
    if "Em Dia" not in inadimplencia.columns:
        inadimplencia["Em Dia"] = 0
    
    total_clientes = inadimplencia["Em Atraso"] + inadimplencia["Em Dia"]
    inadimplencia["taxa_inadimplencia"] = (inadimplencia["Em Atraso"] / total_clientes.replace(0, np.nan) * 100).round(2).fillna(0)
    inadimplencia["total_clientes"] = total_clientes
    inadimplencia["total_inadimplentes"] = inadimplencia["Em Atraso"]
    
    # Adicionar informações do condomínio
    cols_merge = ["ID", "Condomínio", "Região", "Apartamentos"]
    cols_existentes = [c for c in cols_merge if c in df_condominios.columns]
    
    result = inadimplencia.reset_index().merge(
        df_condominios[cols_existentes], 
        left_on="CONDOMANIO", right_on="ID", how="right"
    )
    
    # Preencher NAs
    result["taxa_inadimplencia"] = result["taxa_inadimplencia"].fillna(0)
    result["total_clientes"] = result["total_clientes"].fillna(0).astype(int)
    result["total_inadimplentes"] = result["total_inadimplentes"].fillna(0).astype(int)
    result["Em Atraso"] = result["Em Atraso"].fillna(0).astype(int)
    result["Em Dia"] = result["Em Dia"].fillna(0).astype(int)
    
    # Ordenar por maior inadimplência
    return result.sort_values("taxa_inadimplencia", ascending=False).reset_index(drop=True)

def analisar_inadimplencia_por_parcelas(df_clientes, df_condominios, df_parcelas, data_referencia=None):
    """
    Analisa inadimplência REAL baseada na aba 'Base Parcelas'
    - Cliente inadimplente se tiver parcela com vencimento passado e status 'A receber'
    
    Retorna:
    - DataFrame com análise por condomínio
    - DataFrame com detalhamento de parcelas vencidas
    """
    if df_parcelas is None or df_parcelas.empty:
        return pd.DataFrame(), pd.DataFrame()
    
    if data_referencia is None:
        data_referencia = datetime.now().replace(tzinfo=None)
    
    df_parcelas = df_parcelas.copy()
    df_clientes = df_clientes.copy()
    df_condominios = df_condominios.copy()
    
    # Normalizar IDs
    df_clientes["ID"] = pd.to_numeric(df_clientes["ID"], errors="coerce").fillna(0).astype(int)
    df_parcelas["ID"] = pd.to_numeric(df_parcelas["ID"], errors="coerce").fillna(0).astype(int)
    df_condominios["ID"] = pd.to_numeric(df_condominios["ID"], errors="coerce").fillna(0).astype(int)
    
    # Converter data de vencimento
    df_parcelas["DATA DO VENCIMENTO"] = pd.to_datetime(df_parcelas["DATA DO VENCIMENTO"], errors='coerce')
    
    # Normalizar status
    df_parcelas["STATUS_NORMALIZADO"] = df_parcelas["STATUS"].str.upper().str.strip()
    
    # Identificar parcelas vencidas e não pagas
    parcelas_vencidas = df_parcelas[
        (df_parcelas["DATA DO VENCIMENTO"] < data_referencia) &
        (df_parcelas["STATUS_NORMALIZADO"] == "A RECEBER")
    ].copy()
    
    # Clientes inadimplentes (que têm pelo menos uma parcela vencida)
    clientes_inadimplentes = set(parcelas_vencidas["ID"].unique())
    
    # Adicionar flag de inadimplência aos clientes
    df_clientes["inadimplente_por_parcelas"] = df_clientes["ID"].apply(
        lambda x: x in clientes_inadimplentes
    )
    
    # Calcular total em atraso por cliente (soma das parcelas vencidas)
    soma_atraso = parcelas_vencidas.groupby("ID")["VALOR"].sum().to_dict()
    df_clientes["total_em_atraso"] = df_clientes["ID"].map(soma_atraso).fillna(0)
    
    # Contar número de parcelas vencidas por cliente
    count_parcelas = parcelas_vencidas.groupby("ID").size().to_dict()
    df_clientes["parcelas_vencidas"] = df_clientes["ID"].map(count_parcelas).fillna(0).astype(int)
    
    # Mapear CONDOMANIO a partir do ID do cliente
    df_cliente_cond = df_clientes[["ID", "CONDOMANIO"]].drop_duplicates()
    
    # Agregar por condomínio
    inad_cond = df_cliente_cond.merge(
        df_clientes[["ID", "inadimplente_por_parcelas", "total_em_atraso", "parcelas_vencidas"]],
        on="ID", how="left"
    )
    
    # Agrupar por CONDOMANIO
    cond_agg = inad_cond.groupby("CONDOMANIO").agg(
        total_clientes=("ID", "count"),
        total_inadimplentes=("inadimplente_por_parcelas", "sum"),
        valor_total_atraso=("total_em_atraso", "sum"),
        total_parcelas_vencidas=("parcelas_vencidas", "sum")
    ).reset_index()
    
    cond_agg["taxa_inadimplencia"] = (
        cond_agg["total_inadimplentes"] / cond_agg["total_clientes"].replace(0, np.nan) * 100
    ).round(2).fillna(0)
    
    # Adicionar informações do condomínio
    cols_merge = ["ID", "Condomínio", "Região", "Apartamentos"]
    cols_existentes = [c for c in cols_merge if c in df_condominios.columns]
    
    result = cond_agg.merge(
        df_condominios[cols_existentes],
        left_on="CONDOMANIO", right_on="ID", how="right"
    )
    
    # Preencher NAs
    result["total_clientes"] = result["total_clientes"].fillna(0).astype(int)
    result["total_inadimplentes"] = result["total_inadimplentes"].fillna(0).astype(int)
    result["valor_total_atraso"] = result["valor_total_atraso"].fillna(0)
    result["total_parcelas_vencidas"] = result["total_parcelas_vencidas"].fillna(0).astype(int)
    result["taxa_inadimplencia"] = result["taxa_inadimplencia"].fillna(0)
    
    # Detalhamento das parcelas vencidas
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
    """Análise de churn (taxa de cancelamento)"""
    df_clientes = df_clientes.copy()
    df_condominios = df_condominios.copy()
    
    df_clientes["CONDOMANIO"] = pd.to_numeric(df_clientes["CONDOMANIO"], errors="coerce").fillna(0).astype(int)
    df_condominios["ID"] = pd.to_numeric(df_condominios["ID"], errors="coerce").fillna(0).astype(int)
    
    df_clientes["status_classificacao"] = df_clientes["STATUS ACESSO"].apply(classificar_status)
    
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
    
    df_clientes["status_classificacao"] = df_clientes["STATUS ACESSO"].apply(classificar_status)
    
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
            
            parcelas_info = f", {total_parcelas} parcelas" if total_parcelas > 0 else ""
            display = f"📄 {nome} - {data_str} ({total_clientes} clientes, {total_cond} condomínios{parcelas_info})"
            
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
                        
                        # Separar clientes e parcelas
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
                    
                    st.success(f"✅ Dados carregados: {len(df_clientes)} clientes{', ' + str(len(df_parcelas)) + ' parcelas' if not df_parcelas.empty else ''}")
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
def exibir_dashboard_principal():
    """Exibe o dashboard principal com todas as abas"""
    subtitulo("📊 Dashboard de Condomínios")
    
    df_clientes = st.session_state.condominios_dados_clientes
    df_condominios = st.session_state.condominios_dados_condominios
    df_parcelas = st.session_state.condominios_dados_parcelas
    meta = st.session_state.condominios_meta
    
    if df_clientes is None or df_condominios is None:
        st.warning("⚠️ Nenhum dado carregado. Faça upload ou selecione dados existentes.")
        return
    
    # Exibir informações da importação
    if meta:
        ts = meta.get('timestamp')
        ts_str = safe_strftime(ts, "%d/%m/%Y %H:%M") if ts else "Data não disponível"
        parcelas_info = f" - 📋 {meta.get('total_parcelas', 0)} parcelas" if meta.get('total_parcelas', 0) > 0 else ""
        st.info(f"""
        **📋 Última Importação:**
        - 📅 {ts_str}
        - 📄 {meta.get('filename', 'Arquivo desconhecido')}
        - 👥 {meta.get('total_clientes', 0)} clientes
        - 🏢 {meta.get('total_condominios', 0)} condomínios{parcelas_info}
        """)
    
    st.markdown("---")
    
    # Explicação do cálculo de ativos
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
    
    # Configuração do modo de ativos
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
    
    # Gerar dashboard
    dashboard_df = gerar_dashboard_principal(df_clientes, df_condominios, modo_param)
    
    if not dashboard_df.empty:
        # Métricas principais
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
        
        # Tabela principal
        st.dataframe(
            dashboard_df, 
            use_container_width=True,
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
        
        # Botão de exportação
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
    
    tab1, tab2, tab3, tab4, tab5, tab6, tab7, tab8 = st.tabs([
        "🎯 Penetração", "💰 Receita Potencial", "⚠️ Inadimplência", 
        "📉 Churn", "⚔️ Concorrência", "📍 Análise por Zona", 
        "⏳ Maturidade", "🎯 Consulta de Crédito"
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
            st.plotly_chart(fig, use_container_width=True)
            
            with st.expander("📋 Ver Tabela Completa"):
                st.dataframe(
                    df_filtered[["Condomínio", "Região", "Apartamentos", "clientes_ativos", "taxa_penetracao", "classificacao"]],
                    use_container_width=True
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
            st.plotly_chart(fig, use_container_width=True)
            
            st.dataframe(
                df_receita.sort_values("receita_potencial", ascending=False).head(20)[
                    ["Condomínio", "Região", "clientes_ativos", "potencial_clientes", 
                     "receita_atual", "receita_potencial", "gap_receita"]
                ],
                use_container_width=True,
                column_config={
                    "receita_atual": st.column_config.NumberColumn(format="R$ %.2f"),
                    "receita_potencial": st.column_config.NumberColumn(format="R$ %.2f"),
                    "gap_receita": st.column_config.ProgressColumn(format="%.1f%%", min_value=0, max_value=1000),
                }
            )
    
    # TAB 3: INADIMPLÊNCIA (COM TRÊS VISÕES)
    with tab3:
        st.subheader("⚠️ Análise de Inadimplência por Condomínio")
        
        # Verificar se há dados de parcelas
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
        
        # Radio para escolher a visão de inadimplência
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
        
        # Calcular inadimplência conforme visão selecionada
        if visao_selecionada == "🔴 Visão por Status Acesso":
            # Usar classificação por STATUS ACESSO
            df_clientes_temp = df_clientes.copy()
            df_clientes_temp["CONDOMANIO"] = pd.to_numeric(df_clientes_temp["CONDOMANIO"], errors="coerce").fillna(0).astype(int)
            df_condominios_temp = df_condominios.copy()
            df_condominios_temp["ID"] = pd.to_numeric(df_condominios_temp["ID"], errors="coerce").fillna(0).astype(int)
            
            # Classificar inadimplência por STATUS ACESSO
            def status_para_inadimplencia(status):
                if pd.isna(status):
                    return "Em Dia"
                status_lower = str(status).lower().strip()
                if "financeiro em atraso" in status_lower or "bloqueio" in status_lower:
                    return "Em Atraso"
                return "Em Dia"
            
            df_clientes_temp["situacao_inadimplencia"] = df_clientes_temp["STATUS ACESSO"].apply(status_para_inadimplencia)
            
            # Agrupar por condomínio
            inad_agg = df_clientes_temp.groupby(["CONDOMANIO", "situacao_inadimplencia"]).size().unstack(fill_value=0)
            
            if "Em Atraso" not in inad_agg.columns:
                inad_agg["Em Atraso"] = 0
            if "Em Dia" not in inad_agg.columns:
                inad_agg["Em Dia"] = 0
            
            total_clientes = inad_agg["Em Atraso"] + inad_agg["Em Dia"]
            inad_agg["taxa_inadimplencia"] = (inad_agg["Em Atraso"] / total_clientes.replace(0, np.nan) * 100).round(2).fillna(0)
            inad_agg["total_clientes"] = total_clientes
            inad_agg["total_inadimplentes"] = inad_agg["Em Atraso"]
            
            # Adicionar informações do condomínio
            cols_merge = ["ID", "Condomínio", "Região", "Apartamentos"]
            cols_existentes = [c for c in cols_merge if c in df_condominios.columns]
            
            df_inadimplencia = inad_agg.reset_index().merge(
                df_condominios[cols_existentes], 
                left_on="CONDOMANIO", right_on="ID", how="right"
            )
            
            # Preencher NAs
            df_inadimplencia["taxa_inadimplencia"] = df_inadimplencia["taxa_inadimplencia"].fillna(0)
            df_inadimplencia["total_clientes"] = df_inadimplencia["total_clientes"].fillna(0).astype(int)
            df_inadimplencia["total_inadimplentes"] = df_inadimplencia["total_inadimplentes"].fillna(0).astype(int)
            
            st.info("🔴 **Visão por Status Acesso:** Considera inadimplentes clientes com status 'Financeiro em atraso' ou 'Bloqueio Automático'")
            
        elif visao_selecionada == "🟡 Visão Financeiro Histórico":
            # Usar a função legada
            df_inadimplencia = analisar_inadimplencia_por_status(df_clientes, df_condominios, incluir_desativados=True)
            st.info("🟡 **Visão Financeiro Histórico:** Baseada na coluna 'FINANCEIRO EM ATRASO' (último atraso registrado)")
        else:
            # Visão Real por parcelas
            df_inadimplencia, parcelas_detalhe = analisar_inadimplencia_por_parcelas(df_clientes, df_condominios, df_parcelas)
            st.success("🟢 **Visão Real (Parcelas Vencidas):** Baseada em parcelas com data de vencimento passada e status 'A receber'")
        
        if not df_inadimplencia.empty:
            # Métricas resumidas
            total_condominios = len(df_inadimplencia)
            total_inadimplentes = df_inadimplencia["total_inadimplentes"].sum() if "total_inadimplentes" in df_inadimplencia.columns else 0
            total_clientes_analisados = df_inadimplencia["total_clientes"].sum() if "total_clientes" in df_inadimplencia.columns else 0
            media_inadimplencia = df_inadimplencia["taxa_inadimplencia"].mean()
            
            col1, col2, col3, col4 = st.columns(4)
            col1.metric("🏢 Condomínios Analisados", formatar_numero_br(total_condominios))
            col2.metric("⚠️ Total Inadimplentes", formatar_numero_br(total_inadimplentes))
            col3.metric("👥 Total Clientes", formatar_numero_br(total_clientes_analisados))
            col4.metric("📊 Média Inadimplência", f"{media_inadimplencia:.1f}%")
            
            # Se for visão real, mostrar valor total em atraso
            if visao_selecionada == "🟢 Visão Real (Parcelas Vencidas)" and "valor_total_atraso" in df_inadimplencia.columns:
                valor_total_atraso = df_inadimplencia["valor_total_atraso"].sum()
                st.metric("💰 Valor Total em Atraso", formatar_moeda_br(valor_total_atraso))
            
            st.markdown("---")
            
            # Gráfico: Top 15 condomínios com maior inadimplência
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
            st.plotly_chart(fig1, use_container_width=True)
            
            # Se for visão real, mostrar gráfico de valor em atraso
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
                st.plotly_chart(fig_valor, use_container_width=True)
            
            # Tabela completa
            with st.expander("📋 Ver Tabela Completa de Inadimplência"):
                if visao_selecionada == "🟢 Visão Real (Parcelas Vencidas)":
                    colunas_exibir = ["Condomínio", "Região", "Apartamentos", "total_clientes", 
                                     "total_inadimplentes", "taxa_inadimplencia", "valor_total_atraso", "total_parcelas_vencidas"]
                    colunas_existentes = [c for c in colunas_exibir if c in df_inadimplencia.columns]
                    
                    st.dataframe(
                        df_inadimplencia[colunas_existentes], 
                        use_container_width=True,
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
                        df_inadimplencia[[
                            "Condomínio", "Região", "Apartamentos", 
                            "total_clientes", "Em Dia", "Em Atraso", "total_inadimplentes", "taxa_inadimplencia"
                        ]], 
                        use_container_width=True,
                        column_config={
                            "taxa_inadimplencia": st.column_config.ProgressColumn("Taxa Inadimplência", format="%.1f%%", min_value=0, max_value=100),
                            "Apartamentos": st.column_config.NumberColumn("Apartamentos", format="%d"),
                            "total_clientes": st.column_config.NumberColumn("Total Clientes", format="%d"),
                            "Em Dia": st.column_config.NumberColumn("Em Dia", format="%d"),
                            "Em Atraso": st.column_config.NumberColumn("Em Atraso", format="%d"),
                            "total_inadimplentes": st.column_config.NumberColumn("Total Inadimplentes", format="%d"),
                        }
                    )
            
            # Se for visão real e houver detalhamento de parcelas, mostrar
            if visao_selecionada == "🟢 Visão Real (Parcelas Vencidas)" and 'parcelas_detalhe' in locals() and not parcelas_detalhe.empty:
                with st.expander("📋 Ver Detalhamento de Parcelas Vencidas"):
                    st.dataframe(
                        parcelas_detalhe,
                        use_container_width=True,
                        column_config={
                            "Data Vencimento": st.column_config.DateColumn(format="DD/MM/YYYY"),
                            "Valor": st.column_config.NumberColumn(format="R$ %.2f"),
                        }
                    )
            
            # Botão de exportação específico
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
            st.plotly_chart(fig, use_container_width=True)
            
            with st.expander("📋 Tabela Completa de Churn"):
                st.dataframe(
                    df_churn[["Condomínio", "Região", "Ativo", "Desativado", "churn_rate"]], 
                    use_container_width=True
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
            st.plotly_chart(fig, use_container_width=True)
            
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
                    st.plotly_chart(fig_ativos, use_container_width=True)
                
                with col2:
                    fig_penetracao = px.bar(
                        zona_stats, 
                        x="Região", 
                        y="media_penetracao", 
                        color="media_penetracao",
                        title="Penetração Média por Região (%)",
                        color_continuous_scale="Blues"
                    )
                    st.plotly_chart(fig_penetracao, use_container_width=True)
        else:
            st.warning("⚠️ Dados insuficientes para análise por região.")
    
    # TAB 7: MATURIDADE
    with tab7:
        st.subheader("⏳ Análise de Maturidade dos Condomínios")
        
        df_maturidade = preparar_dados_maturidade(df_clientes, df_condominios)
        df_maturidade["classificacao_maturidade"] = df_maturidade.apply(
            lambda row: classificar_maturidade(row, CONDOMINIOS_CONFIG['meses_maturidade_limite']), axis=1)
        
        # Estatísticas de maturidade
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
        st.plotly_chart(fig_maturidade, use_container_width=True)
        
        # Tabela completa
        with st.expander("📋 Ver Tabela Completa de Maturidade"):
            st.dataframe(
                df_maturidade[[
                    "Condomínio", "Data cadastro", "meses_cadastro", "Região", 
                    "Apartamentos", "ativos", "percentual_ativos", "total_ocupados",
                    "classificacao_maturidade"
                ]], 
                use_container_width=True,
                column_config={
                    "Data cadastro": st.column_config.DateColumn(format="DD/MM/YYYY"),
                    "percentual_ativos": st.column_config.ProgressColumn(format="%.1f%%", min_value=0, max_value=100),
                }
            )
        
        # Exportar maturidade
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
    
    # TAB 8: CONSULTA DE CRÉDITO (VERSÃO ATUALIZADA COM FILTROS NA PRÓPRIA ABA)
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
        
        # Verificar se há dados de parcelas
        if df_parcelas is None or df_parcelas.empty:
            st.warning("⚠️ Aba 'Base Parcelas' não encontrada. A análise de consulta de crédito requer dados de parcelas.")
            st.info("Por favor, faça upload de uma planilha que contenha a aba 'Base Parcelas'.")
        else:
            # Renderizar filtros dentro da aba
            filtros = render_filtros_consulta_credito()
            
            # Verificar se o botão foi clicado
            if filtros['aplicar_filtros']:
                with st.spinner("🔄 Analisando inadimplência com os filtros selecionados..."):
                    df_inad_periodo, df_clientes_inad, df_parcelas_vencidas = analisar_inadimplencia_periodo(
                        df_parcelas, df_clientes, df_condominios,
                        dias_atraso=filtros['dias_atraso'],
                        data_referencia=filtros['data_referencia']
                    )
                
                if df_inad_periodo.empty:
                    st.warning("⚠️ Nenhuma inadimplência encontrada com os critérios atuais.")
                    st.info("Tente ajustar os filtros para um período maior ou taxas menores.")
                else:
                    # Exibir resumo do período
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
                    
                    # Identificar condomínios aptos com filtros flexíveis
                    df_aptos, df_top_oportunidades = identificar_condominios_aptos_consulta_flexivel(
                        df_inad_periodo,
                        taxa_minima=filtros['taxa_minima'],
                        min_inadimplentes=filtros['min_inadimplentes'] if filtros['min_inadimplentes'] > 0 else 0,
                        valor_minimo_atraso=filtros['valor_minimo_atraso'],
                        ativar_filtro_valor=filtros['ativar_filtro_valor']
                    )
                    
                    # Renderizar painel de aptos
                    render_painel_condominios_aptos(df_aptos, df_top_oportunidades)
                    
                    # Mostrar detalhamento de parcelas vencidas do top 1 (opcional)
                    if not df_aptos.empty:
                        st.markdown("---")
                        st.subheader("📄 Detalhamento Adicional")
                        
                        col_detalhe1, col_detalhe2 = st.columns([1, 2])
                        with col_detalhe1:
                            mostrar_detalhe = st.checkbox("Mostrar detalhamento de parcelas vencidas", key="mostrar_detalhe_parcelas")
                        
                        if mostrar_detalhe and not df_aptos.empty:
                            # Selecionar condomínio para detalhamento
                            condominios_lista = df_aptos["Condomínio"].tolist()
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
                                        column_config={
                                            "DATA DO VENCIMENTO": st.column_config.DateColumn(format="DD/MM/YYYY"),
                                            "VALOR": st.column_config.NumberColumn("Valor", format="R$ %.2f"),
                                            "DIAS_ATRASO": st.column_config.NumberColumn("Dias", format="%d"),
                                        }
                                    )
            else:
                st.info("🔧 Configure os parâmetros acima e clique em 'Aplicar Filtros e Gerar Ranking' para iniciar a análise.")
                
                # Mostrar exemplo visual dos filtros
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

# ==================== FUNÇÃO PRINCIPAL ====================
def render_relatorios_condominios():
    """Função principal refatorada com todas as funcionalidades"""
    
    # Inicializar session_state
    initialize_session_state()
    
    # Título
    titulo_principal("🏢 Relatórios Estratégicos - Condomínios")
    st.markdown("Análise de penetração, receita potencial, inadimplência (3 visões), churn, concorrência e maturidade")
    
    # Conectar ao banco
    db = init_mongo()
    
    if db is None:
        st.error("❌ Não foi possível conectar ao banco de dados")
        return
    else:
        st.success("✅ Database conectado", icon="🔗")
    
    # 🚀 Pré-carregamento automático
    if st.session_state.condominios_dados_clientes is None:
        with st.spinner("🔄 Carregando dados mais recentes..."):
            if carregar_dados_mais_recentes(db):
                st.success("✅ Dados mais recentes carregados automaticamente!")
            else:
                st.info("ℹ️ Nenhum dado encontrado — faça upload de uma planilha.")
    
    # Gerenciamento de dados
    gerenciamento_dados_mode(db)
    st.markdown("---")
    
    # Tabs principais
    tab1, tab2, tab3 = st.tabs(["📤 Upload", "📁 Dados Existentes", "📊 Dashboard"])
    
    with tab1:
        upload_mode(db)
    
    with tab2:
        dados_existentes_mode(db)
    
    with tab3:
        if st.session_state.condominios_processado:
            exibir_dashboard_principal()
        else:
            st.warning("⚠️ Nenhum dado carregado. Faça upload ou selecione dados existentes.")
            if st.button("🔄 Tentar carregar novamente"):
                if carregar_dados_mais_recentes(db):
                    st.success("✅ Dados carregados!")
                    st.rerun()
    
    # Verificar pop-up de exclusão
    if st.session_state.exclusao_confirmada:
        if st.session_state.batch_id_a_excluir:
            confirmar_exclusao(db, st.session_state.batch_id_a_excluir)

# ==================== ENTRY POINT ====================
if __name__ == "__main__":
    render_relatorios_condominios()
