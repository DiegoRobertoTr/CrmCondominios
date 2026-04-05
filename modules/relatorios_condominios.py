import streamlit as st
import pandas as pd
import numpy as np
import plotly.express as px
import plotly.graph_objects as go
from datetime import datetime
from pymongo import MongoClient
from pymongo.errors import ServerSelectionTimeoutError, ConnectionFailure
from urllib.parse import quote_plus

# ==================== CONFIGURAÇÃO INICIAL ====================
# ⚠️ st.set_page_config DEVE ser o primeiro comando do Streamlit
st.set_page_config(page_title="🏢 Relatórios Condomínios", layout="wide")

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
                st.error("🚨 Credenciais MongoDB incompletas nos Secrets.")
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

def save_condominio_data(db, df_clientes, df_condominios, metadata):
    """Salva dados com timestamp para versionamento"""
    collection = db["condominios_relatorios"]
    docs = []
    
    for _, row in df_clientes.iterrows():
        doc = row.to_dict()
        
        # ✅ CORREÇÃO: Tratamento seguro de datas e NaT
        for key, value in doc.items():
            if isinstance(value, pd.Timestamp):
                if pd.isna(value):
                    doc[key] = None
                else:
                    doc[key] = value.to_pydatetime()
            elif pd.isna(value):
                doc[key] = None
        
        doc["_import_timestamp"] = metadata["timestamp"]
        doc["_import_batch"] = metadata["batch_id"]
        docs.append(doc)

    if docs:
        collection.insert_many(docs)

    db["condominios_meta"].insert_one({
        "batch_id": metadata["batch_id"],
        "timestamp": metadata["timestamp"],
        "total_clientes": len(df_clientes),
        "total_condominios": len(df_condominios),
        "condominios": df_condominios.to_dict(orient="records")
    })
    return True

def load_latest_data(db):
    """Carrega últimos dados importados"""
    meta = db["condominios_meta"].find_one(sort=[("timestamp", -1)])
    if not meta:
        return None, None, None
        
    collection = db["condominios_relatorios"]
    df_clientes = pd.DataFrame(list(collection.find({"_import_batch": meta["batch_id"]})))

    if "_id" in df_clientes.columns:
        df_clientes = df_clientes.drop(columns=["_id"])

    for col in df_clientes.select_dtypes(include=['object']).columns:
        if 'data' in col.lower() or 'date' in col.lower():
            df_clientes[col] = pd.to_datetime(df_clientes[col], errors='coerce')
        
    df_condominios = pd.DataFrame(meta.get("condominios", []))
    return df_clientes, df_condominios, meta

def clear_condominio_data(db, batch_id=None):
    """Limpa dados"""
    collection = db["condominios_relatorios"]
    if batch_id:
        result = collection.delete_many({"_import_batch": batch_id})
        db["condominios_meta"].delete_many({"batch_id": batch_id})
    else:
        result = collection.delete_many({})
        db["condominios_meta"].delete_many({})
    return result.deleted_count

# ==================== FUNÇÕES DE ANÁLISE ====================
def calcular_penetracao(df_clientes, df_condominios):
    """Calcula taxa de penetração por condomínio"""
    # Filtra apenas ativos
    ativos = df_clientes[df_clientes["STATUS ACESSO"].str.lower().str.contains("ativo", na=False)]
    
    # ✅ CORREÇÃO: Agrupar pela coluna CONDOMANIO (da tabela de clientes)
    clientes_por_cond = ativos.groupby("CONDOMANIO").size().reset_index(name="clientes_ativos")
    
    # ✅ CORREÇÃO: Cruzar CONDOMANIO (esquerda) com ID (direita - tabela condominios)
    df_merged = clientes_por_cond.merge(
        df_condominios[["ID", "Condomínio", "Apartamentos", "Região", "Principal Concorrente"]],
        left_on="CONDOMANIO",
        right_on="ID",
        how="left"
    )

    df_merged["taxa_penetracao"] = (
        df_merged["clientes_ativos"] / df_merged["Apartamentos"] * 100
    ).round(2)

    def classificar_penetracao(taxa):
        if pd.isna(taxa): return "🔴 Baixa Presença"
        if taxa >= 50: return "🟢 Dominado"
        elif taxa >= 25: return "🟡 Em Crescimento"
        else: return "🔴 Baixa Presença"
        
    df_merged["classificacao"] = df_merged["taxa_penetracao"].apply(classificar_penetracao)
    return df_merged.sort_values("taxa_penetracao", ascending=False)

def analisar_inadimplencia(df_clientes, df_condominios):
    """Análise de inadimplência por condomínio"""
    df_clientes["atraso_bin"] = df_clientes["FINANCEIRO EM ATRASO"].apply(
        lambda x: "Em Atraso" if pd.notna(x) and str(x).strip().lower() not in ["00/00/0000", "", "0", "nan", "nat"] else "Em Dia"
    )
    
    # ✅ CORREÇÃO: Agrupar por CONDOMANIO
    inadimplencia = df_clientes.groupby(["CONDOMANIO", "atraso_bin"]).size().unstack(fill_value=0)
    
    if "Em Atraso" in inadimplencia.columns and "Em Dia" in inadimplencia.columns:
        inadimplencia["taxa_inadimplencia"] = (
            inadimplencia["Em Atraso"] / (inadimplencia["Em Atraso"] + inadimplencia["Em Dia"]) * 100
        ).round(2)
        
    # ✅ CORREÇÃO: Reset index para transformar CONDOMANIO em coluna e fazer o merge
    result = inadimplencia.reset_index().merge(
        df_condominios[["ID", "Condomínio", "Região"]],
        left_on="CONDOMANIO",
        right_on="ID",
        how="left"
    )
    return result.sort_values("taxa_inadimplencia", ascending=False)

def analisar_churn(df_clientes, df_condominios):
    """Análise de churn/cancelamentos por condomínio"""
    # ✅ CORREÇÃO: Agrupar por CONDOMANIO
    status_count = df_clientes.groupby(["CONDOMANIO", "STATUS ACESSO"]).size().unstack(fill_value=0)
    
    if "Ativo" in status_count.columns and "Desativado" in status_count.columns:
        total = status_count["Ativo"] + status_count["Desativado"]
        status_count["churn_rate"] = (status_count["Desativado"] / total * 100).round(2)
        
    # ✅ CORREÇÃO: Merge ajustado
    result = status_count.reset_index().merge(
        df_condominios[["ID", "Condomínio", "Região", "Principal Concorrente"]],
        left_on="CONDOMANIO",
        right_on="ID",
        how="left"
    )
    return result.sort_values("churn_rate", ascending=False)

def correlacao_concorrencia(df_penetracao, df_condominios):
    """Correlaciona penetração com concorrentes principais"""
    if "Principal Concorrente" in df_penetracao.columns:
        conc_stats = df_penetracao.groupby("Principal Concorrente").agg({
            "taxa_penetracao": ["mean", "median", "count"],
            "clientes_ativos": "sum",
            "Apartamentos": "sum"
        }).round(2)
        conc_stats.columns = ["_".join(col).strip() for col in conc_stats.columns.values]
        conc_stats = conc_stats.reset_index()
        conc_stats["penetracao_ponderada"] = (
            conc_stats["clientes_ativos_sum"] / conc_stats["Apartamentos_sum"] * 100
        ).round(2)
        return conc_stats.sort_values("penetracao_ponderada", ascending=False)
    return pd.DataFrame()

def calcular_receita_potencial(df_penetracao, ticket_medio=89.99):
    """Calcula receita atual vs. potencial por condomínio"""
    df = df_penetracao.copy()
    df["receita_atual"] = df["clientes_ativos"] * ticket_medio
    df["potencial_clientes"] = df["Apartamentos"] - df["clientes_ativos"]
    df["receita_potencial"] = df["potencial_clientes"] * ticket_medio
    df["receita_maxima"] = df["Apartamentos"] * ticket_medio
    df["gap_receita"] = (df["receita_potencial"] / df["receita_atual"]).replace([np.inf, -np.inf], 0) * 100
    return df.sort_values("receita_potencial", ascending=False)

def safe_strftime(value, fmt="%d/%m/%Y %H:%M"):
    """Formata datetime com tratamento seguro para NaT/None"""
    if pd.isna(value) or value is None:
        return ""
    if isinstance(value, (pd.Timestamp, datetime)):
        return value.strftime(fmt)
    return str(value)

# ==================== INTERFACE STREAMLIT ====================
def render_relatorios_condominios():
    st.title("🏢 Relatórios Estratégicos - Condomínios")
    st.markdown("Análise de penetração, churn, inadimplência e oportunidades de mercado")
    
    db = init_mongo()

    st.markdown("---")
    st.subheader("⚙️ Gerenciamento de Dados")

    col1, col2 = st.columns([3, 1])

    with col1:
        uploaded_file = st.file_uploader(
            "📤 Importar Planilha",
            type=["xlsx", "xls"],
            help="Planilha com 2 abas: 'Dados' (clientes) e 'Condominios'"
        )

    with col2:
        if st.button("🔄 Recarregar Últimos", type="primary", use_container_width=True):
            st.session_state["reload_data"] = True
        
        if st.button("🗑️ Limpar Dados", type="secondary", use_container_width=True):
            if st.session_state.get("confirm_delete"):
                deleted = clear_condominio_data(db)
                st.success(f"✅ {deleted} registros removidos!")
                st.session_state["confirm_delete"] = False
                st.rerun()
            else:
                st.warning("⚠️ Clique novamente para confirmar")
                st.session_state["confirm_delete"] = True

    meta = db["condominios_meta"].find_one(sort=[("timestamp", -1)])
    if meta:
        ts = meta.get('timestamp')
        ts_str = safe_strftime(ts, "%d/%m/%Y %H:%M") if ts else "Data não disponível"
        st.info(f"""
        **Última Importação:**
        - 📅 {ts_str}
        - 👥 {meta['total_clientes']} clientes
        - 🏢 {meta['total_condominios']} condomínios
        """)
    else:
        st.warning("⚠️ Nenhum dado importado ainda")

    st.markdown("---")

    df_clientes, df_condominios, meta = None, None, None

    if uploaded_file:
        try:
            df_clientes = pd.read_excel(uploaded_file, sheet_name="Dados")
            df_condominios = pd.read_excel(uploaded_file, sheet_name="Condominios")
            
            for col in df_clientes.select_dtypes(include=['object']).columns:
                if 'data' in col.lower() or 'date' in col.lower():
                    df_clientes[col] = pd.to_datetime(df_clientes[col], errors='coerce')
            
            metadata = {
                "timestamp": datetime.now(),
                "batch_id": f"batch_{datetime.now().strftime('%Y%m%d_%H%M%S')}",
                "filename": uploaded_file.name
            }
            
            if save_condominio_data(db, df_clientes, df_condominios, metadata):
                st.success(f"✅ Dados importados! {len(df_clientes)} clientes, {len(df_condominios)} condomínios")
                st.rerun()
        except Exception as e:
            st.error(f"❌ Erro ao processar planilha: {str(e)}")
            st.code("Verifique se as abas 'Dados' e 'Condominios' existem e têm os cabeçalhos corretos.")
    elif st.session_state.get("reload_data") or "df_clientes_cached" not in st.session_state:
        result = load_latest_data(db)
        if result[0] is not None:
            df_clientes, df_condominios, meta = result
            st.session_state["df_clientes_cached"] = df_clientes
            st.session_state["df_condominios_cached"] = df_condominios
            st.session_state["meta_cached"] = meta
            st.success("📦 Dados pré-carregados da última importação")
        else:
            st.info("👆 Faça upload da planilha para começar")
            return
    else:
        df_clientes = st.session_state["df_clientes_cached"]
        df_condominios = st.session_state["df_condominios_cached"]
        meta = st.session_state["meta_cached"]

    if "reload_data" in st.session_state:
        del st.session_state["reload_data"]

    # KPIs
    st.subheader("📊 Visão Geral do Mercado")
    ativos = df_clientes[df_clientes["STATUS ACESSO"].str.lower().str.contains("ativo", na=False)]
    total_clientes = len(df_clientes["ID"].unique())
    total_ativos = len(ativos["ID"].unique())
    total_apartamentos = df_condominios["Apartamentos"].sum()
    penetracao_geral = (total_ativos / total_apartamentos * 100) if total_apartamentos > 0 else 0

    col1, col2, col3, col4 = st.columns(4)
    col1.metric("🏢 Condomínios", len(df_condominios))
    col2.metric("👥 Clientes Ativos", f"{total_ativos:,}")
    col3.metric("🏠 Total de Apartamentos", f"{total_apartamentos:,}")
    col4.metric("📈 Penetração Geral", f"{penetracao_geral:.1f}%")

    # Tabs
    tab1, tab2, tab3, tab4, tab5 = st.tabs(["🎯 Penetração", "💰 Receita Potencial", "⚠️ Inadimplência", "📉 Churn", "⚔️ Concorrência"])

    with tab1:
        st.header("🎯 Taxa de Penetração por Condomínio")
        df_penetracao = calcular_penetracao(df_clientes, df_condominios)
        
        col1, col2, col3 = st.columns(3)
        with col1:
            regioes = df_condominios["Região"].dropna().unique()
            regiao_filter = st.multiselect("Região", list(regioes) if len(regioes) > 0 else [])
        with col2:
            classific_filter = st.multiselect("Classificação", ["🟢 Dominado", "🟡 Em Crescimento", "🔴 Baixa Presença"])
        with col3:
            min_penetracao = st.slider("Penetração Mínima (%)", 0, 100, 0)
            
        df_filtered = df_penetracao.copy()
        if regiao_filter:
            df_filtered = df_filtered[df_filtered["Região"].isin(regiao_filter)]
        if classific_filter:
            df_filtered = df_filtered[df_filtered["classificacao"].isin(classific_filter)]
        df_filtered = df_filtered[df_filtered["taxa_penetracao"] >= min_penetracao]
        
        fig = px.bar(
            df_filtered.head(20),
            x="taxa_penetracao",
            y="Condomínio",
            color="classificacao",
            orientation="h",
            title="Top 20 Condomínios por Penetração",
            color_discrete_map={
                "🟢 Dominado": "#2ecc71",
                "🟡 Em Crescimento": "#f39c12", 
                "🔴 Baixa Presença": "#e74c3c"
            }
        )
        fig.update_layout(height=600, yaxis={"categoryorder": "total ascending"})
        st.plotly_chart(fig, use_container_width=True)
        
        with st.expander("📋 Ver Tabela Completa"):
            st.dataframe(df_filtered[["Condomínio", "Região", "Apartamentos", "clientes_ativos", "taxa_penetracao", "classificacao"]], use_container_width=True)
            csv = df_filtered.to_csv(index=False, sep=";").encode("utf-8-sig")
            st.download_button("📥 Exportar CSV", data=csv, file_name=f"penetracao_{datetime.now().strftime('%Y%m%d')}.csv", mime="text/csv")
            
        st.markdown("### 💡 Insights Automáticos")
        baixas = df_penetracao[df_penetracao["taxa_penetracao"] < 20]
        altas = df_penetracao[df_penetracao["taxa_penetracao"] > 60]
        
        c1, c2 = st.columns(2)
        with c1:
            if not baixas.empty:
                top3 = baixas.nlargest(3, 'Apartamentos')['Condomínio'].tolist()
                st.warning(f"**🔴 Oportunidades de Expansão:**\n- {len(baixas)} condomínios com <20% de penetração\n- Top 3: {', '.join(top3) if top3 else 'N/A'}\n- **Ação sugerida:** Campanhas direcionadas + abordagem com síndicos")
        with c2:
            if not altas.empty:
                st.success(f"**🟢 Condomínios Saturados:**\n- {len(altas)} condomínios com >60% de penetração\n- **Ação sugerida:** Foco em retenção, upsell e indicações")

    with tab2:
        st.header("💰 Receita Potencial por Condomínio")
        ticket = st.number_input("🎯 Ticket Médio Estimado (R$)", value=89.99, min_value=10.0, max_value=500.0, step=5.0)
        df_receita = calcular_receita_potencial(df_penetracao, ticket_medio=ticket)
        
        fig = go.Figure(go.Waterfall(
            name="Receita", orientation="v", measure=["relative"] * len(df_receita.head(15)),
            x=df_receita.head(15)["Condomínio"], y=df_receita.head(15)["receita_potencial"],
            textposition="outside", text=[f"R$ {v:,.2f}" for v in df_receita.head(15)["receita_potencial"]],
            connector={"line": {"color": "rgb(63, 63, 63)"}}
        ))
        fig.update_layout(title="💰 Receita Potencial Não Explorada (Top 15)", showlegend=False, height=500)
        st.plotly_chart(fig, use_container_width=True)
        
        st.markdown("### 🎯 Priorização Comercial")
        df_prioridade = df_receita[["Condomínio", "Apartamentos", "clientes_ativos", "potencial_clientes", "receita_potencial"]].copy()
        df_prioridade["prioridade"] = df_prioridade["receita_potencial"].rank(ascending=False)
        st.dataframe(df_prioridade.sort_values("receita_potencial", ascending=False).head(20), use_container_width=True, column_config={"receita_potencial": st.column_config.NumberColumn("Potencial (R$)", format="R$ %.2f")})

    with tab3:
        st.header("⚠️ Análise de Inadimplência por Condomínio")
        df_inadimplencia = analisar_inadimplencia(df_clientes, df_condominios)
        # Note: Merge aqui precisa ajustar os nomes das colunas se necessário, mas o foco é mostrar o gráfico
        df_merge = df_penetracao.merge(df_inadimplencia[["CONDOMANIO", "taxa_inadimplencia"]], left_on="CONDOMANIO", right_on="CONDOMANIO", how="left")
        
        fig = px.scatter(df_merge, x="taxa_penetracao", y="taxa_inadimplencia", size="Apartamentos", color="Região", hover_name="Condomínio", title="Penetração vs Inadimplência")
        fig.update_layout(height=500)
        st.plotly_chart(fig, use_container_width=True)
        
        st.markdown("### 🚨 Alertas de Inadimplência")
        altos = df_inadimplencia[df_inadimplencia["taxa_inadimplencia"] > 30]
        if not altos.empty:
            for _, row in altos.head(5).iterrows():
                em_atraso = row.get('Em Atraso', 0)
                em_dia = row.get('Em Dia', 0)
                st.warning(f"**{row['Condomínio']}**: {row['taxa_inadimplencia']}% inadimplência ({em_atraso} de {em_atraso+em_dia} clientes)")

    with tab4:
        st.header("📉 Análise de Churn por Condomínio")
        df_churn = analisar_churn(df_clientes, df_condominios)
        fig = px.bar(df_churn.head(15), x="Condomínio", y="churn_rate", color="churn_rate", color_continuous_scale="Reds", title="Top 15 Condomínios com Maior Taxa de Cancelamento")
        fig.update_layout(height=400)
        st.plotly_chart(fig, use_container_width=True)
        
        if "MOTIVO" in df_clientes.columns:
            st.markdown("### 🔍 Principais Motivos de Cancelamento")
            motivos = df_clientes[df_clientes["STATUS ACESSO"].str.contains("Desativado", na=False)]["MOTIVO"].value_counts().head(10)
            fig_motivos = px.bar(x=motivos.values, y=motivos.index, orientation="h", title="Top 10 Motivos de Cancelamento")
            st.plotly_chart(fig_motivos, use_container_width=True)

    with tab5:
        st.header("⚔️ Análise Competitiva")
        df_concorrencia = correlacao_concorrencia(df_penetracao, df_condominios)
        
        if not df_concorrencia.empty:
            fig = px.bar(df_concorrencia, x="Principal Concorrente", y="penetracao_ponderada", color="penetracao_ponderada", color_continuous_scale="RdYlGn", title="Penetração Média por Concorrente Principal")
            fig.update_layout(height=400)
            st.plotly_chart(fig, use_container_width=True)
            
            st.markdown("### 💡 Insights Competitivos")
            if "penetracao_ponderada" in df_concorrencia.columns and not df_concorrencia["penetracao_ponderada"].empty:
                melhor = df_concorrencia.loc[df_concorrencia["penetracao_ponderada"].idxmax()]
                pior = df_concorrencia.loc[df_concorrencia["penetracao_ponderada"].idxmin()]
                c1, c2 = st.columns(2)
                with c1:
                    st.success(f"**✅ Melhor desempenho:** vs {melhor['Principal Concorrente']}\n- Penetração média: {melhor['penetracao_ponderada']:.1f}%")
                with c2:
                    st.error(f"**⚠️ Desafio:** vs {pior['Principal Concorrente']}\n- Penetração média: {pior['penetracao_ponderada']:.1f}%")
        else:
            st.info("ℹ️ Dados de concorrentes não disponíveis na planilha importada")

    st.markdown("---")
    st.subheader("🗺️ Mapa Estratégico de Condomínios")
    fig_mapa = px.scatter(df_penetracao, x="Apartamentos", y="taxa_penetracao", size="clientes_ativos", color="classificacao", hover_name="Condomínio", hover_data=["Região", "Principal Concorrente"], title="Matriz: Tamanho do Condomínio vs Penetração")
    fig_mapa.add_hline(y=25, line_dash="dash", line_color="orange", annotation_text="Limite Crescimento")
    fig_mapa.add_hline(y=50, line_dash="dash", line_color="green", annotation_text="Limite Dominado")
    fig_mapa.add_vline(x=df_penetracao["Apartamentos"].median(), line_dash="dot", annotation_text="Tamanho Médio")
    fig_mapa.update_layout(height=500, hovermode="closest")
    st.plotly_chart(fig_mapa, use_container_width=True)

    st.markdown("""
    #### 🎯 Como usar esta matriz:
    | Quadrante | Perfil | Ação Recomendada |
    |-----------|--------|-----------------|
    | 🔴 Grande + Baixa Penetração | **Prioridade Máxima** | Campanha agressiva, negociação com síndico |
    | 🟡 Médio + Crescimento | **Consolidar** | Fidelização, indicações, upsell |
    | 🟢 Pequeno + Alta Penetração | **Manter** | Atendimento premium, monitorar churn |
    | ⚪ Qualquer + Saturado | **Otimizar** | Foco em margem, não volume |
    """)

if __name__ == "__main__":
    render_relatorios_condominios()
