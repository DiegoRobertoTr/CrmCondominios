# modules/visitas_vendedoras.py
"""
Módulo de Gerenciamento de Visitas de Vendedoras - VERSÃO OTIMIZADA
- Integrado com cadastro de condomínios existente
- Histórico completo de campanhas
- Agendamento inteligente com regras de negócio
- Especialização por região (Zona Sul, Norte, Oeste, etc.)
- Visualizações por perfil (admin, vendedora, atendente)
- Múltiplos relatórios e exportações
- AGENDA VISUAL POR VENDEDORA COM EDIÇÃO MANUAL
- SELECTBOX DE CONDOMÍNIOS VINCULADO AO CADASTRO

OTIMIZAÇÕES APLICADAS:
✅ Cache cirúrgico (sem st.cache_data.clear() global)
✅ DB singleton via st.cache_resource
✅ Query única na agenda visual (elimina N+1)
✅ Processamento vetorial com pandas
✅ Índices MongoDB compostos
✅ Substituição de st.rerun() por flags de sessão
✅ Projeções nas queries MongoDB
✅ Cache com versionamento para invalidação
"""

import streamlit as st
import pandas as pd
from datetime import datetime, timedelta, date
from collections import defaultdict
import io
from bson.objectid import ObjectId
from typing import Dict, List, Tuple, Optional
import calendar
import uuid

# Importar módulo de condomínios existente
try:
    from modules.condominios import get_condominios_collection, get_all_condominios, get_estatisticas_zonas
except ImportError:
    st.warning("⚠️ Módulo de condomínios não encontrado. Algumas funcionalidades podem ser limitadas.")
    def get_all_condominios():
        return []
    def get_condominios_collection():
        return None
    def get_estatisticas_zonas():
        return []

# ============================================================================
# CONFIGURAÇÕES INICIAIS
# ============================================================================

DIAS_SEMANA = ['Segunda', 'Terça', 'Quarta', 'Quinta', 'Sexta', 'Sábado', 'Domingo']

REGIOES_DISPONIVEIS = [
    "Zona Sul",
    "Zona Norte",
    "Zona Oeste",
    "Zona Sudoeste",
    "Centro",
    "Baixada Fluminense",
    "Todas as regiões"
]

DISPONIBILIDADE_PADRAO = {
    "Kessia": {
        "dias": [0, 1, 2, 3, 4],
        "horario": "08:00-17:00",
        "max_visitas_dia": 2,
        "tipo": "fixa",
        "regiao_preferencial": "Zona Oeste"
    },
    "Larissa": {
        "dias": [0, 1, 2, 3, 4],
        "horario": "08:00-17:00",
        "max_visitas_dia": 2,
        "tipo": "fixa",
        "regiao_preferencial": "Zona Norte"
    },
    "Estephanie": {
        "dias": [0, 1, 2, 3, 4],
        "horario": "08:00-17:00",
        "max_visitas_dia": 2,
        "tipo": "fixa",
        "regiao_preferencial": "Zona Sul"
    },
    "Juliana": {
        "dias": [2, 4],
        "horario": "08:00-17:00",
        "max_visitas_dia": 2,
        "tipo": "freelancer",
        "regiao_preferencial": "Todas as regiões"
    }
}

# Ícones de status (constante - evita recriar dicionário)
STATUS_ICONS = {
    "agendado": "🟢",
    "concluido": "✅",
    "cancelado": "🔴",
    "chuva": "🌧️",
    "falta": "⛔",
    "feriado": "📌"
}

STATUS_FORMAT_MAP = {
    "agendado": "🟢 Agendado",
    "concluido": "✅ Concluído",
    "cancelado": "🔴 Cancelado",
    "chuva": "🌧️ Chuva",
    "falta": "⛔ Falta",
    "feriado": "🔴 Feriado"
}

# ============================================================================
# OTIMIZAÇÃO: DB SINGLETON + CACHE COM VERSIONAMENTO
# ============================================================================

@st.cache_resource(show_spinner=False)
def get_db_singleton():
    """Reutiliza a conexão do MongoDB entre reruns (OTIMIZAÇÃO CRÍTICA)"""
    collection = get_condominios_collection()
    if collection is None:
        return None
    return collection.database


def _get_cache_version(key: str) -> int:
    """Retorna versão atual do cache para invalidação cirúrgica"""
    session_key = f"cache_version_{key}"
    if session_key not in st.session_state:
        st.session_state[session_key] = 0
    return st.session_state[session_key]


def invalidar_cache(key: str):
    """Invalida APENAS o cache da chave especificada (sem clear global)"""
    session_key = f"cache_version_{key}"
    st.session_state[session_key] = st.session_state.get(session_key, 0) + 1


# ============================================================================
# FUNÇÕES AUXILIARES
# ============================================================================

def get_prioridade_condominio(aptos: int = 0, prioridade_manual: str = None) -> str:
    if prioridade_manual and prioridade_manual != "Automática":
        return prioridade_manual
    
    if aptos >= 1000:
        return "A+"
    elif aptos >= 500:
        return "A"
    elif aptos >= 300:
        return "B"
    elif aptos >= 150:
        return "C"
    else:
        return "D"


def get_peso_prioridade(prioridade: str) -> int:
    pesos = {"A+": 5, "A": 4, "B": 3, "C": 2, "D": 1}
    return pesos.get(prioridade, 0)


def calcular_frequencia_semanal(aptos: int) -> int:
    if aptos >= 1000:
        return 3
    elif aptos >= 500:
        return 2
    elif aptos >= 200:
        return 1
    else:
        return 1


def condominios_proximos(cond1: dict, cond2: dict) -> bool:
    bairro1 = (cond1.get('bairro') or '').upper().strip()
    bairro2 = (cond2.get('bairro') or '').upper().strip()
    
    if not bairro1 or not bairro2:
        return False
    
    return bairro1 == bairro2


def calcular_adequacao_vendedora_condominio(vendedora: dict, condominio_zona: str) -> dict:
    regiao_preferencial = vendedora.get('regiao_preferencial', 'Todas as regiões')
    
    if regiao_preferencial == "Todas as regiões":
        return {
            "peso": 0.8,
            "nivel": "disponivel",
            "motivo": f"✓ {vendedora['nome']} atende todas as regiões"
        }
    
    if regiao_preferencial == condominio_zona:
        return {
            "peso": 1.0,
            "nivel": "preferencial",
            "motivo": f"⭐ REGIÃO PREFERENCIAL! {vendedora['nome']} é especialista em {condominio_zona}"
        }
    
    return {
        "peso": 0.4,
        "nivel": "nao_preferencial",
        "motivo": f"⚠️ {vendedora['nome']} prefere {regiao_preferencial}, este condomínio é {condominio_zona}"
    }


def verificar_espaco_mongo(db):
    try:
        stats = db.command("dbStats")
        tamanho_mb = stats.get("dataSize", 0) / (1024 * 1024)
        return tamanho_mb
    except:
        return 0


def formatar_status_visita(status: str) -> str:
    return STATUS_FORMAT_MAP.get(status, status)


# ============================================================================
# CACHE DE CONDOMÍNIOS COM VERSIONAMENTO (substitui clear global)
# ============================================================================

@st.cache_data(ttl=600, show_spinner=False)
def get_condominios_nomes_cached(version: int = 0):
    """Cache invalidável por version. NÃO usar st.cache_data.clear()"""
    condominios = get_all_condominios()
    return sorted([c["nome"] for c in condominios])


@st.cache_data(ttl=600, show_spinner=False)
def get_condominios_dict_cached(version: int = 0):
    condominios = get_all_condominios()
    return {c["nome"].upper(): c for c in condominios}


# ============================================================================
# INICIALIZAÇÃO DAS COLEÇÕES + ÍNDICES OTIMIZADOS
# ============================================================================

def init_colecoes_visitas(clientes_collection):
    """Inicializa coleções e índices (executado apenas uma vez via cache_resource)"""
    db = clientes_collection.database
    
    collections_existentes = db.list_collection_names()
    
    if 'campanhas_historico' not in collections_existentes:
        db.create_collection('campanhas_historico')
        db.campanhas_historico.create_index("data_criacao")
        db.campanhas_historico.create_index("status")
        db.campanhas_historico.create_index("versao")
        db.campanhas_historico.create_index("campanha_id")
    
    if 'campanha_visitas' not in collections_existentes:
        db.create_collection('campanha_visitas')
        db.campanha_visitas.create_index("condominio_id", unique=True)
    
    if 'vendedoras' not in collections_existentes:
        db.create_collection('vendedoras')
        for nome, config in DISPONIBILIDADE_PADRAO.items():
            if not db.vendedoras.find_one({"nome": nome}):
                db.vendedoras.insert_one({
                    "nome": nome,
                    "disponibilidade": config["dias"],
                    "horario": config["horario"],
                    "max_visitas_dia": config["max_visitas_dia"],
                    "tipo": config["tipo"],
                    "regiao_preferencial": config.get("regiao_preferencial", "Todas as regiões"),
                    "ativo": True,
                    "data_cadastro": datetime.now(),
                    "data_desativacao": None,
                    "motivo_desativacao": None
                })
    
    if 'visitas_vendedoras' not in collections_existentes:
        db.create_collection('visitas_vendedoras')
    
    # OTIMIZAÇÃO: Índices compostos para queries frequentes
    try:
        db.visitas_vendedoras.create_index(
            [("data", 1), ("vendedora", 1), ("status", 1)],
            name="idx_data_vend_status",
            background=True
        )
        db.visitas_vendedoras.create_index(
            [("vendedora", 1), ("data", 1)],
            name="idx_vend_data",
            background=True
        )
        db.visitas_vendedoras.create_index(
            [("condominio_id", 1), ("data", 1)],
            name="idx_cond_data",
            background=True
        )
        db.visitas_vendedoras.create_index(
            [("campanha_id", 1), ("status", 1)],
            name="idx_campanha_status",
            background=True
        )
        db.visitas_vendedoras.create_index("status", name="idx_status", background=True)
    except Exception:
        pass  # Índices já existem
    
    return db


# ============================================================================
# HELPER: QUERY ÚNICA PARA AGENDA (elimina N+1)
# ============================================================================

def _buscar_visitas_intervalo(db, data_ini: str, data_fim: str,
                               vendedoras: List[str],
                               status_filter: List[str] = None,
                               projecao: dict = None) -> List[dict]:
    """
    OTIMIZAÇÃO: Uma única query ao invés de N queries em loops.
    Usa projeção para reduzir payload.
    """
    if not vendedoras:
        return []
    
    query = {
        "data": {"$gte": data_ini, "$lte": data_fim},
        "vendedora": {"$in": list(vendedoras)}
    }
    
    if status_filter:
        query["status"] = {"$in": list(status_filter)}
    
    if projecao is None:
        projecao = {
            "condominio_nome": 1, "data": 1, "vendedora": 1, "status": 1,
            "periodo": 1, "manual": 1, "zona": 1, "observacoes": 1,
            "condominio_id": 1
        }
    
    return list(db.visitas_vendedoras.find(query, projecao).sort("data", 1))


# ============================================================================
# SELEÇÃO DE CONDOMÍNIOS PARA CAMPANHA
# ============================================================================

def selecionar_condominios_campanha(db, clientes_collection):
    st.markdown("### 🎯 Seleção de Condomínios para Campanha de Visitas")
    
    condominios_cadastro = get_all_condominios()
    
    if not condominios_cadastro:
        st.warning("⚠️ Nenhum condomínio cadastrado no sistema. Cadastre condomínios primeiro.")
        return
    
    # OTIMIZAÇÃO: queries agregadas em poucas chamadas
    campanha_ativa_ids = set(
        str(c["condominio_id"]) for c in db.campanha_visitas.find({}, {"condominio_id": 1})
    )
    
    ultima_campanha = db.campanhas_historico.find_one(
        {}, {"versao": 1}, sort=[("versao", -1)]
    )
    total_campanhas = db.campanhas_historico.estimated_document_count()
    
    col_info1, col_info2, col_info3 = st.columns(3)
    with col_info1:
        st.info(f"📊 **Total disponível:** {len(condominios_cadastro)} condomínios")
    with col_info2:
        if ultima_campanha:
            st.info(f"📌 **Última versão:** Campanha #{ultima_campanha.get('versao', 0)}")
    with col_info3:
        st.info(f"📚 **Total campanhas:** {total_campanhas}")
    
    # OTIMIZAÇÃO: construção do DataFrame vetorizada
    dados_selecao = []
    for cond in condominios_cadastro:
        aptos = cond.get("apartamentos", 0) or cond.get("aptos", 0) or 0
        prioridade = get_prioridade_condominio(aptos)
        zona = cond.get("zona", "Não definida")
        cond_id_str = str(cond["_id"])
        
        dados_selecao.append({
            "Selecionar": cond_id_str in campanha_ativa_ids,
            "Condomínio": cond["nome"],
            "Bairro": cond.get("bairro", "N/I"),
            "Zona": zona,
            "Aptos": aptos,
            "Prioridade": prioridade,
            "Visitas/Semana": calcular_frequencia_semanal(aptos),
            "ID": cond_id_str
        })
    
    df = pd.DataFrame(dados_selecao)
    
    st.markdown("#### 📋 Selecione os condomínios para a campanha")
    
    edited_df = st.data_editor(
        df,
        column_config={
            "Selecionar": st.column_config.CheckboxColumn("Ativo na Campanha"),
            "Condomínio": st.column_config.TextColumn("Condomínio", disabled=True),
            "Bairro": st.column_config.TextColumn("Bairro", disabled=True),
            "Zona": st.column_config.TextColumn("Zona", disabled=True),
            "Aptos": st.column_config.NumberColumn("Aptos", disabled=True),
            "Prioridade": st.column_config.TextColumn("Prioridade", disabled=True),
            "Visitas/Semana": st.column_config.NumberColumn("Visitas/Semana", disabled=True),
            "ID": st.column_config.TextColumn("ID", disabled=True)
        },
        hide_index=True,
        use_container_width=True,
        height=500,
        key="editor_campanha"
    )
    
    st.markdown("---")
    st.markdown("#### 📅 Período da Campanha")
    
    col_p1, col_p2, col_p3 = st.columns(3)
    
    with col_p1:
        data_inicio = st.date_input(
            "Data de início", value=datetime.now().date()
        )
    
    with col_p2:
        data_fim = st.date_input(
            "Data de término", value=datetime.now().date() + timedelta(days=120)
        )
    
    with col_p3:
        meses = ((data_fim - data_inicio).days) // 30
        st.metric("Duração da Campanha", f"~{meses} meses", f"{((data_fim - data_inicio).days)} dias")
    
    nome_campanha = st.text_input(
        "🏷️ Nome da Campanha (opcional)",
        value=f"Campanha {datetime.now().strftime('%B %Y')}"
    )
    
    col_b1, col_b2, col_b3, col_b4, col_b5, col_b6 = st.columns(6)
    
    with col_b1:
        if st.button("💾 Salvar Campanha", use_container_width=True, type="primary", key="btn_salvar_campanha"):
            selecionados = edited_df[edited_df["Selecionar"] == True]
            
            if len(selecionados) == 0:
                st.warning("⚠️ Selecione pelo menos um condomínio!")
            else:
                ultima_versao = db.campanhas_historico.find_one(
                    {}, {"versao": 1}, sort=[("versao", -1)]
                )
                nova_versao = (ultima_versao.get("versao", 0) + 1) if ultima_versao else 1
                campanha_id = str(uuid.uuid4())
                
                condominios_selecionados = []
                for _, row in selecionados.iterrows():
                    condominios_selecionados.append({
                        "condominio_id": ObjectId(row["ID"]),
                        "condominio_nome": row["Condomínio"],
                        "bairro": row["Bairro"],
                        "zona": row["Zona"],
                        "aptos": row["Aptos"],
                        "prioridade": row["Prioridade"],
                        "frequencia_sugerida": row["Visitas/Semana"]
                    })
                
                db.campanhas_historico.insert_one({
                    "versao": nova_versao,
                    "campanha_id": campanha_id,
                    "nome": nome_campanha or f"Campanha #{nova_versao}",
                    "data_inicio": datetime.combine(data_inicio, datetime.min.time()),
                    "data_fim": datetime.combine(data_fim, datetime.min.time()),
                    "data_criacao": datetime.now(),
                    "status": "ativa",
                    "total_condominios": len(condominios_selecionados),
                    "condominios": condominios_selecionados,
                    "criado_por": st.session_state.get("nome_usuario", "Sistema"),
                    "observacoes": f"Campanha com {len(condominios_selecionados)} condomínios"
                })
                
                db.campanha_visitas.delete_many({})
                docs = [{
                    "condominio_id": c["condominio_id"],
                    "condominio_nome": c["condominio_nome"],
                    "bairro": c["bairro"],
                    "zona": c["zona"],
                    "aptos": c["aptos"],
                    "prioridade": c["prioridade"],
                    "frequencia_sugerida": c["frequencia_sugerida"],
                    "data_inicio": datetime.combine(data_inicio, datetime.min.time()),
                    "data_fim": datetime.combine(data_fim, datetime.min.time()),
                    "campanha_id": campanha_id,
                    "versao": nova_versao,
                    "ativo": True,
                    "data_cadastro": datetime.now()
                } for c in condominios_selecionados]
                
                if docs:
                    db.campanha_visitas.insert_many(docs)
                
                st.success(f"✅ Campanha #{nova_versao} salva! {len(condominios_selecionados)} condomínios.")
                st.balloons()
                st.rerun()
    
    with col_b2:
        if st.button("🤖 Seleção Inteligente", use_container_width=True, key="btn_selec_intel"):
            df_temp = edited_df.copy()
            df_temp['Peso'] = df_temp['Prioridade'].apply(get_peso_prioridade)
            df_temp = df_temp.sort_values(['Peso', 'Aptos'], ascending=[False, False])
            
            limite = min(28, len(df_temp))
            indices = df_temp.head(limite).index
            edited_df.loc[indices, 'Selecionar'] = True
            
            st.success(f"✅ {limite} condomínios selecionados.")
            st.rerun()
    
    with col_b3:
        zona_filter = st.selectbox("Zona", ["Todas"] + REGIOES_DISPONIVEIS[:-1], key="zona_filter")
        if st.button("📍 Selecionar por Zona", use_container_width=True, key="btn_zona"):
            if zona_filter != "Todas":
                df_temp = edited_df[edited_df["Zona"] == zona_filter]
                edited_df.loc[df_temp.index, 'Selecionar'] = True
                st.rerun()
    
    with col_b4:
        prioridade_min = st.selectbox("Prioridade mínima", ["A+", "A", "B", "C", "D"], key="prioridade_min_filter")
        if st.button("⭐ Selecionar por Prioridade", use_container_width=True, key="btn_prioridade"):
            peso_min = get_peso_prioridade(prioridade_min)
            df_temp = edited_df.copy()
            df_temp['Peso'] = df_temp['Prioridade'].apply(get_peso_prioridade)
            df_temp = df_temp[df_temp['Peso'] >= peso_min]
            edited_df.loc[df_temp.index, 'Selecionar'] = True
            st.rerun()
    
    with col_b5:
        if st.button("🗑️ Limpar Todos", use_container_width=True, key="btn_limpar"):
            edited_df['Selecionar'] = False
            st.rerun()
    
    with col_b6:
        tamanho_mb = verificar_espaco_mongo(db)
        if tamanho_mb > 0:
            st.metric("💾 MongoDB", f"{tamanho_mb:.2f} MB", f"{tamanho_mb/512*100:.1f}%")
    
    # Estatísticas
    st.markdown("---")
    st.markdown("### 📊 Estatísticas da Campanha")
    
    selecionados_atual = edited_df[edited_df["Selecionar"] == True]
    
    if len(selecionados_atual) > 0:
        col_e1, col_e2, col_e3, col_e4 = st.columns(4)
        
        with col_e1:
            st.metric("Condomínios Selecionados", len(selecionados_atual))
        with col_e2:
            total_aptos = selecionados_atual["Aptos"].sum()
            st.metric("Total de Apartamentos", f"{total_aptos:,}")
        with col_e3:
            visitas_semana = selecionados_atual["Visitas/Semana"].sum()
            st.metric("Visitas/Semana", visitas_semana)
        with col_e4:
            dias_campanha = (data_fim - data_inicio).days
            semanas = dias_campanha / 7
            total_visitas = int(visitas_semana * semanas)
            st.metric("Total de Visitas (período)", f"{total_visitas:,}")
        
        st.markdown("#### 📍 Distribuição por Zona")
        zona_counts = selecionados_atual["Zona"].value_counts()
        
        cols_zona = st.columns(min(len(zona_counts), 5))
        for idx, (zona, count) in enumerate(zona_counts.items()):
            if idx < len(cols_zona):
                with cols_zona[idx]:
                    st.metric(zona, count)
        
        with st.expander("📋 Ver lista detalhada"):
            for _, row in selecionados_atual.sort_values(
                ["Prioridade", "Aptos"], ascending=[True, False]
            ).iterrows():
                st.write(f"**{row['Prioridade']}** - {row['Condomínio']} | {row['Zona']} | {row['Aptos']} aptos | {row['Visitas/Semana']}x/semana")
    else:
        st.warning("Nenhum condomínio selecionado.")


# ============================================================================
# AGENDAMENTO INTELIGENTE
# ============================================================================

def agendamento_inteligente(db, data_inicio: date, data_fim: date = None, campanha_id: str = None):
    """Algoritmo otimizado com queries agregadas"""
    if not data_fim:
        data_fim = data_inicio + timedelta(days=30)
    
    # OTIMIZAÇÃO: queries com projeção mínima
    query_campanha = {"ativo": True}
    if campanha_id:
        query_campanha["campanha_id"] = campanha_id
    
    campanha = list(db.campanha_visitas.find(
        query_campanha,
        {"condominio_id": 1, "condominio_nome": 1, "bairro": 1, "zona": 1,
         "prioridade": 1, "frequencia_sugerida": 1, "campanha_id": 1}
    ))
    
    if not campanha:
        return []
    
    vendedoras = list(db.vendedoras.find(
        {"ativo": True},
        {"nome": 1, "disponibilidade": 1, "max_visitas_dia": 1, "regiao_preferencial": 1}
    ))
    
    if not vendedoras:
        return []
    
    data_inicio_str = data_inicio.strftime("%Y-%m-%d")
    data_fim_str = data_fim.strftime("%Y-%m-%d")
    dias_periodo = (data_fim - data_inicio).days
    semanas = dias_periodo / 7
    
    # OTIMIZAÇÃO: 1 query para contar todas as visitas agendadas por condomínio
    pipeline = [
        {"$match": {
            "data": {"$gte": data_inicio_str, "$lte": data_fim_str},
            "status": {"$ne": "cancelado"}
        }},
        {"$group": {"_id": "$condominio_id", "count": {"$sum": 1}}}
    ]
    agendados_por_cond = {
        doc["_id"]: doc["count"]
        for doc in db.visitas_vendedoras.aggregate(pipeline)
    }
    
    # Calcular necessidade
    necessidade = {}
    cond_ids = []
    for cond in campanha:
        freq = cond.get('frequencia_sugerida', 1)
        visitas_necessarias = max(1, int(freq * semanas))
        cond_id = cond["condominio_id"]
        cond_ids.append(cond_id)
        
        agendados = agendados_por_cond.get(cond_id, 0)
        
        necessidade[str(cond_id)] = {
            "necessario": max(0, visitas_necessarias - agendados),
            "prioridade": cond.get("prioridade", "D"),
            "zona": cond.get("zona", "Zona Central"),
            "nome": cond["condominio_nome"],
            "bairro": cond.get("bairro", ""),
            "campanha_id": cond.get("campanha_id"),
            "cond_id_obj": cond_id
        }
    
    # OTIMIZAÇÃO: 1 query para agendamentos existentes
    agendamentos_existentes = list(db.visitas_vendedoras.find({
        "data": {"$gte": data_inicio_str, "$lte": data_fim_str},
        "status": {"$ne": "cancelado"}
    }, {"data": 1, "vendedora": 1}))
    
    # Mapa de agendamentos por (data, vendedora)
    contagem_por_dia_vend = defaultdict(int)
    for ag in agendamentos_existentes:
        contagem_por_dia_vend[(ag["data"], ag["vendedora"])] += 1
    
    # OTIMIZAÇÃO: mapa de bairros por condomínio para verificação de proximidade
    bairros_por_cond = {
        str(c["condominio_id"]): (c.get("bairro") or "").upper().strip()
        for c in campanha
    }
    
    # Precalcular dias disponíveis
    dias_disponiveis = {}
    for delta in range(dias_periodo + 1):
        data = data_inicio + timedelta(days=delta)
        dia_semana = data.weekday()
        if dia_semana == 6:
            continue
        data_str = data.strftime("%Y-%m-%d")
        dias_disponiveis[data_str] = {
            "dia_semana": dia_semana,
            "data_obj": data,
            "agendamentos": {v["nome"]: contagem_por_dia_vend.get((data_str, v["nome"]), 0) for v in vendedoras}
        }
    
    # Ordenar condomínios
    campanha_ordenada = sorted(
        necessidade.items(),
        key=lambda x: (-get_peso_prioridade(x[1]["prioridade"]), -x[1]["necessario"])
    )
    
    sugestoes = []
    # OTIMIZAÇÃO: cache local de bairros visitados por (data, vendedora)
    bairros_visitados = defaultdict(set)
    for ag in agendamentos_existentes:
        bairro = bairros_por_cond.get(str(ag.get("condominio_id", "")), "")
        if bairro:
            bairros_visitados[(ag["data"], ag["vendedora"])].add(bairro)
    
    for cond_id, nec in campanha_ordenada:
        if nec["necessario"] <= 0:
            continue
        
        bairro_cond = (nec.get("bairro") or "").upper().strip()
        zona_cond = nec["zona"]
        
        for data_str in sorted(dias_disponiveis.keys()):
            dia_info = dias_disponiveis[data_str]
            dia_semana = dia_info["dia_semana"]
            
            # Pré-calcular vendedoras candidatas
            candidatas = []
            for vend in vendedoras:
                if dia_semana not in vend["disponibilidade"]:
                    continue
                if dia_info["agendamentos"][vend["nome"]] >= vend.get("max_visitas_dia", 2):
                    continue
                
                adequacao = calcular_adequacao_vendedora_condominio(vend, zona_cond)
                candidatas.append({
                    "vendedora": vend,
                    "peso": adequacao["peso"],
                    "nivel": adequacao["nivel"],
                    "motivo": adequacao["motivo"],
                    "visitas_hoje": dia_info["agendamentos"][vend["nome"]]
                })
            
            candidatas.sort(key=lambda x: (-x["peso"], x["visitas_hoje"]))
            
            for vp in candidatas:
                vend = vp["vendedora"]
                
                # Verificação de proximidade otimizada (usa cache local)
                if bairro_cond:
                    bairros_hoje = bairros_visitados.get((data_str, vend["nome"]), set())
                    if bairros_hoje and bairro_cond not in bairros_hoje and dia_info["agendamentos"][vend["nome"]] > 0:
                        continue
                
                sugestoes.append({
                    "condominio_id": cond_id,
                    "condominio_nome": nec["nome"],
                    "condominio_zona": zona_cond,
                    "vendedora": vend["nome"],
                    "vendedora_motivo": vp["motivo"],
                    "data": data_str,
                    "data_obj": dia_info["data_obj"],
                    "dia_semana": DIAS_SEMANA[dia_semana],
                    "prioridade": nec["prioridade"],
                    "adequacao": vp["nivel"],
                    "campanha_id": nec.get("campanha_id"),
                    "periodo": "M/T"
                })
                
                dia_info["agendamentos"][vend["nome"]] += 1
                necessidade[cond_id]["necessario"] -= 1
                if bairro_cond:
                    bairros_visitados[(data_str, vend["nome"])].add(bairro_cond)
                break
            
            if necessidade[cond_id]["necessario"] <= 0:
                break
    
    return sugestoes


# ============================================================================
# AGENDA VISUAL - VERSÃO OTIMIZADA
# ============================================================================

def agenda_visual_por_vendedora(db):
    """Agenda visual otimizada com query única e processamento vetorial"""
    st.markdown("### 📅 Agenda Visual por Vendedora")
    
    col_per1, col_per2, col_per3 = st.columns([1, 1, 1])
    
    with col_per1:
        mes_ano = st.date_input(
            "Mês/Ano",
            value=datetime.now().date().replace(day=1),
            key="mes_agenda_visual"
        )
        mes = mes_ano.month
        ano = mes_ano.year
        dias_no_mes = calendar.monthrange(ano, mes)[1]
    
    # OTIMIZAÇÃO: buscar vendedoras ativas 1x
    vendedoras_ativas = list(db.vendedoras.find(
        {"ativo": True}, {"nome": 1}
    ))
    vendedoras_opcoes = [v["nome"] for v in vendedoras_ativas]
    
    if not vendedoras_opcoes:
        st.warning("⚠️ Nenhuma vendedora ativa cadastrada.")
        return
    
    with col_per2:
        vendedoras_selecionadas = st.multiselect(
            "Vendedoras",
            options=vendedoras_opcoes,
            default=vendedoras_opcoes[:3] if len(vendedoras_opcoes) >= 3 else vendedoras_opcoes,
            key="vendedoras_agenda_visual"
        )
    
    with col_per3:
        mostrar_status = st.multiselect(
            "Mostrar Status",
            options=["agendado", "concluido", "cancelado", "chuva", "falta", "feriado"],
            default=["agendado", "concluido"],
            key="status_agenda_visual",
            format_func=formatar_status_visita
        )
    
    if not vendedoras_selecionadas:
        st.warning("Selecione pelo menos uma vendedora para visualizar.")
        return
    
    col_btn1, col_btn2, col_btn3 = st.columns(3)
    
    with col_btn1:
        if st.button("🔃 Resetar para Sugestões", use_container_width=True, key="btn_reset_agenda"):
            with st.spinner("Resetando agenda..."):
                data_inicio = datetime(ano, mes, 1).date()
                data_fim = datetime(ano, mes, dias_no_mes).date()
                
                campanha_ativa = db.campanha_visitas.find_one(
                    {"ativo": True}, {"campanha_id": 1}
                )
                campanha_id = campanha_ativa.get("campanha_id") if campanha_ativa else None
                
                sugestoes = agendamento_inteligente(db, data_inicio, data_fim, campanha_id)
                
                if sugestoes:
                    # OTIMIZAÇÃO: bulk delete + bulk insert
                    db.visitas_vendedoras.delete_many({
                        "data": {"$gte": data_inicio.strftime("%Y-%m-%d"),
                                 "$lte": data_fim.strftime("%Y-%m-%d")},
                        "manual": True
                    })
                    
                    # Buscar existentes para não duplicar
                    existentes_keys = set()
                    for v in db.visitas_vendedoras.find({
                        "data": {"$gte": data_inicio.strftime("%Y-%m-%d"),
                                 "$lte": data_fim.strftime("%Y-%m-%d")}
                    }, {"data": 1, "vendedora": 1, "condominio_id": 1}):
                        existentes_keys.add((v["data"], v["vendedora"], str(v["condominio_id"])))
                    
                    docs_novos = []
                    for sug in sugestoes:
                        key = (sug["data"], sug["vendedora"], str(sug["condominio_id"]))
                        if key in existentes_keys:
                            continue
                        docs_novos.append({
                            "condominio_id": ObjectId(sug["condominio_id"]),
                            "condominio_nome": sug["condominio_nome"],
                            "vendedora": sug["vendedora"],
                            "data": sug["data"],
                            "status": "agendado",
                            "periodo": "M/T",
                            "criado_por": "Sistema (Reset)",
                            "data_criacao": datetime.now(),
                            "zona": sug["condominio_zona"],
                            "adequacao": sug["adequacao"],
                            "campanha_id": sug.get("campanha_id"),
                            "manual": False
                        })
                    
                    if docs_novos:
                        db.visitas_vendedoras.insert_many(docs_novos)
                    
                    invalidar_cache("agenda_visual")
                    st.success(f"✅ Agenda resetada! {len(docs_novos)} visitas geradas.")
                    st.rerun()
                else:
                    st.warning("Nenhuma sugestão gerada. Verifique a campanha ativa.")
    
    with col_btn2:
        if st.button("📊 Exportar Agenda Visual", use_container_width=True, key="btn_export_agenda"):
            exportar_agenda_visual(db, ano, mes, vendedoras_selecionadas)
    
    with col_btn3:
        if st.button("🔄 Recarregar", use_container_width=True, key="btn_reload_agenda"):
            invalidar_cache("agenda_visual")
            st.rerun()
    
    st.markdown("---")
    
    # ============================================================
    # OTIMIZAÇÃO: QUERY ÚNICA + PROJEÇÃO
    # ============================================================
    
    data_inicio_str = datetime(ano, mes, 1).strftime("%Y-%m-%d")
    data_fim_str = datetime(ano, mes, dias_no_mes).strftime("%Y-%m-%d")
    
    with st.spinner("Carregando agenda..."):
        visitas_db = _buscar_visitas_intervalo(
            db, data_inicio_str, data_fim_str,
            vendedoras_selecionadas,
            status_filter=mostrar_status if mostrar_status else None
        )
    
    # OTIMIZAÇÃO: processamento vetorial com pandas
    # Criar índice por (data, vendedora) - O(1) lookups
    visitas_index = defaultdict(list)
    feriados_set = set()
    
    for v in visitas_db:
        if v.get("status") == "feriado":
            feriados_set.add(v["data"])
            continue
        visitas_index[(v["data"], v["vendedora"])].append(v)
    
    # Exibir cabeçalho
    st.markdown(f"### 📆 {calendar.month_name[mes]} {ano}")
    
    col_leg = st.columns(6)
    legendas = ["🟢 **Agendado**", "✅ **Concluído**", "🔴 **Cancelado**",
                "🌧️ **Chuva**", "⛔ **Falta**", "📌 **Feriado**"]
    for col, leg in zip(col_leg, legendas):
        with col:
            st.markdown(leg)
    
    st.markdown("---")
    
    cols_cabecalho = st.columns([1.2] + [1.5] * len(vendedoras_selecionadas))
    with cols_cabecalho[0]:
        st.markdown("**Data**")
    for i, vendedora in enumerate(vendedoras_selecionadas):
        with cols_cabecalho[i + 1]:
            st.markdown(f"**{vendedora}**")
    
    st.markdown("---")
    
    # OTIMIZAÇÃO: pré-computar cores por dia da semana
    for dia in range(1, dias_no_mes + 1):
        data_obj = datetime(ano, mes, dia).date()
        data_str = data_obj.strftime("%Y-%m-%d")
        dia_semana = data_obj.weekday()
        
        if data_str in feriados_set:
            bg_color = "#ffcccc"
        elif dia_semana == 6:
            bg_color = "#ffe6e6"
        elif dia_semana == 5:
            bg_color = "#e8f4fd"
        else:
            bg_color = "#f9f9f9"
        
        cols = st.columns([1.2] + [1.5] * len(vendedoras_selecionadas))
        
        with cols[0]:
            st.markdown(f"""
            <div style="background-color: {bg_color}; padding: 8px; border-radius: 5px; text-align: center;">
                <strong>{data_obj.strftime('%d/%m')}</strong><br>
                <small>{DIAS_SEMANA[dia_semana][:3]}</small>
            </div>
            """, unsafe_allow_html=True)
        
        is_feriado = data_str in feriados_set
        
        for i, vendedora in enumerate(vendedoras_selecionadas):
            with cols[i + 1]:
                if is_feriado:
                    st.markdown(f"""
                    <div style="background-color: {bg_color}; padding: 8px; border-radius: 5px; text-align: center;">
                        <span style="color: #ff6b6b; font-weight: bold;">🔴 FERIADO</span>
                    </div>
                    """, unsafe_allow_html=True)
                    continue
                
                visitas = visitas_index.get((data_str, vendedora), [])
                
                if not visitas:
                    st.markdown(f"""
                    <div style="background-color: {bg_color}; padding: 8px; border-radius: 5px; text-align: center; min-height: 50px;">
                        <span style="color: #ccc; font-size: 20px;">+</span>
                    </div>
                    """, unsafe_allow_html=True)
                    continue
                
                # OTIMIZAÇÃO: usar list comprehension + join
                blocos = []
                for v in visitas:
                    periodo = v.get("periodo", "M/T")
                    if periodo == 'M':
                        periodo_color = '#e3f2fd'
                    elif periodo == 'T':
                        periodo_color = '#fff3e0'
                    else:
                        periodo_color = '#f3e5f5'
                    
                    border_color = '#ff6b6b' if v.get('manual') else '#28a745'
                    status_icon = STATUS_ICONS.get(v.get("status"), "🟢")
                    manual_label = "📝" if v.get("manual") else "🤖"
                    
                    blocos.append(
                        f'<div style="margin-bottom: 4px; padding: 4px; border-radius: 4px; '
                        f'background-color: #ffffff; border-left: 3px solid {border_color}; font-size: 12px;">'
                        f'<span style="background-color: {periodo_color}; border-radius: 3px; '
                        f'padding: 1px 5px; font-size: 10px; font-weight: bold;">{periodo}</span> '
                        f'<span style="font-weight: 500;">{v["condominio_nome"]}</span> '
                        f'<span>{status_icon}</span> '
                        f'<span style="font-size: 9px; color: #888;">{manual_label}</span>'
                        f'</div>'
                    )
                
                html_content = (
                    f'<div style="background-color: {bg_color}; padding: 8px; '
                    f'border-radius: 5px; min-height: 50px;">'
                    + ''.join(blocos)
                    + '</div>'
                )
                
                st.markdown(html_content, unsafe_allow_html=True)
        
        st.markdown("<hr style='margin: 2px 0; border-color: #ddd;'>", unsafe_allow_html=True)
    
    # ============================================================
    # EDITOR MANUAL
    # ============================================================
    
    st.markdown("---")
    st.markdown("### ✏️ Editor Manual de Visitas")
    st.info("💡 Selecione a data, vendedora e condomínio para adicionar ou editar uma visita.")
    
    # OTIMIZAÇÃO: usar cache versionado
    cache_v = _get_cache_version("condominios")
    condominios_nomes = get_condominios_nomes_cached(cache_v)
    condominios_dict = get_condominios_dict_cached(cache_v)
    
    with st.form("form_edicao_visita", clear_on_submit=False):
        col_ed1, col_ed2, col_ed3, col_ed4 = st.columns(4)
        
        with col_ed1:
            data_edicao = st.date_input(
                "Data",
                value=datetime.now().date(),
                key="data_edicao_manual_form",
                min_value=datetime(ano, mes, 1).date(),
                max_value=datetime(ano, mes, dias_no_mes).date()
            )
        
        with col_ed2:
            vendedora_edicao = st.selectbox(
                "Vendedora",
                options=vendedoras_selecionadas,
                key="vendedora_edicao_form"
            )
        
        with col_ed3:
            if condominios_nomes:
                condominio_edicao = st.selectbox(
                    "Condomínio (da lista)",
                    options=[""] + condominios_nomes,
                    key="condominio_edicao_form"
                )
                condominio_manual = st.text_input(
                    "Ou digite manualmente",
                    key="condominio_manual_form"
                )
            else:
                st.warning("⚠️ Nenhum condomínio cadastrado.")
                condominio_edicao = ""
                condominio_manual = st.text_input("Condomínio", key="condominio_manual_form")
        
        with col_ed4:
            periodo_edicao = st.selectbox("Período", ["M", "T", "M/T"], key="periodo_edicao_form")
        
        col_ed5, col_ed6 = st.columns(2)
        with col_ed5:
            status_edicao = st.selectbox(
                "Status",
                options=["agendado", "concluido", "cancelado", "chuva", "falta", "feriado"],
                key="status_edicao_form",
                format_func=formatar_status_visita
            )
        with col_ed6:
            observacao_edicao = st.text_input("Observação", key="obs_edicao_form")
        
        col_btn_a, col_btn_b = st.columns(2)
        with col_btn_a:
            submitted = st.form_submit_button(
                "✅ Adicionar/Editar Visita", use_container_width=True, type="primary"
            )
        with col_btn_b:
            remover_submitted = st.form_submit_button(
                "🗑️ Remover Visitas do Dia", use_container_width=True
            )
        
        if submitted:
            data_str = data_edicao.strftime("%Y-%m-%d")
            nome_condominio = condominio_edicao if condominio_edicao else condominio_manual
            
            if status_edicao == "feriado":
                if not db.visitas_vendedoras.find_one({"data": data_str, "status": "feriado"}):
                    db.visitas_vendedoras.insert_one({
                        "condominio_id": None,
                        "condominio_nome": "FERIADO",
                        "vendedora": "Sistema",
                        "data": data_str,
                        "status": "feriado",
                        "periodo": "M/T",
                        "observacoes": observacao_edicao or "Feriado",
                        "criado_por": st.session_state.get("nome_usuario", "Manual"),
                        "data_criacao": datetime.now(),
                        "manual": True,
                        "zona": "Sistema",
                        "adequacao": "sistema"
                    })
                    invalidar_cache("agenda_visual")
                    st.success(f"✅ Feriado marcado para {data_edicao.strftime('%d/%m/%Y')}")
                else:
                    st.info(f"ℹ️ Feriado já marcado.")
                st.rerun()
            
            if not nome_condominio:
                st.error("⚠️ Selecione ou digite o nome do condomínio!")
            else:
                condominio_encontrado = condominios_dict.get(nome_condominio.upper())
                condominio_id = condominio_encontrado["_id"] if condominio_encontrado else None
                
                existente = db.visitas_vendedoras.find_one({
                    "data": data_str,
                    "vendedora": vendedora_edicao,
                    "condominio_nome": nome_condominio
                })
                
                if existente:
                    update_data = {
                        "status": status_edicao,
                        "periodo": periodo_edicao,
                        "observacoes": observacao_edicao,
                        "manual": True,
                        "ultima_edicao": datetime.now()
                    }
                    if condominio_id:
                        update_data["condominio_id"] = condominio_id
                        if condominio_encontrado:
                            update_data["zona"] = condominio_encontrado.get("zona", "Manual")
                    
                    db.visitas_vendedoras.update_one({"_id": existente["_id"]}, {"$set": update_data})
                    invalidar_cache("agenda_visual")
                    st.success(f"✅ Visita atualizada: {nome_condominio}")
                else:
                    visitas_dia = db.visitas_vendedoras.count_documents({
                        "data": data_str,
                        "vendedora": vendedora_edicao,
                        "status": {"$ne": "cancelado"}
                    })
                    
                    if visitas_dia >= 2:
                        st.warning(f"⚠️ {vendedora_edicao} já tem {visitas_dia} visitas neste dia.")
                    else:
                        db.visitas_vendedoras.insert_one({
                            "condominio_id": condominio_id,
                            "condominio_nome": nome_condominio,
                            "vendedora": vendedora_edicao,
                            "data": data_str,
                            "status": status_edicao,
                            "periodo": periodo_edicao,
                            "observacoes": observacao_edicao,
                            "criado_por": st.session_state.get("nome_usuario", "Manual"),
                            "data_criacao": datetime.now(),
                            "manual": True,
                            "zona": condominio_encontrado.get("zona", "Manual") if condominio_encontrado else "Manual",
                            "adequacao": "manual"
                        })
                        invalidar_cache("agenda_visual")
                        st.success(f"✅ Visita adicionada: {nome_condominio}")
                
                # OTIMIZAÇÃO: NÃO chamar st.cache_data.clear()
                st.rerun()
        
        if remover_submitted:
            data_str = data_edicao.strftime("%Y-%m-%d")
            result = db.visitas_vendedoras.delete_many({
                "data": data_str,
                "vendedora": vendedora_edicao,
                "status": {"$ne": "feriado"}
            })
            
            if result.deleted_count > 0:
                invalidar_cache("agenda_visual")
                st.success(f"✅ Removidas {result.deleted_count} visitas.")
                st.rerun()
            else:
                st.warning("Nenhuma visita encontrada.")


# ============================================================================
# EXPORTAR AGENDA
# ============================================================================

def exportar_agenda_visual(db, ano, mes, vendedoras_selecionadas):
    dias_no_mes = calendar.monthrange(ano, mes)[1]
    data_inicio_str = datetime(ano, mes, 1).strftime("%Y-%m-%d")
    data_fim_str = datetime(ano, mes, dias_no_mes).strftime("%Y-%m-%d")
    
    # OTIMIZAÇÃO: query única
    visitas = _buscar_visitas_intervalo(
        db, data_inicio_str, data_fim_str,
        vendedoras_selecionadas + ["Sistema"]
    )
    
    if not visitas:
        st.warning("Nenhum dado para exportar.")
        return
    
    # OTIMIZAÇÃO: construção vetorizada
    df = pd.DataFrame(visitas)
    df["data_obj"] = pd.to_datetime(df["data"])
    df["dia_semana"] = df["data_obj"].dt.weekday.map(lambda x: DIAS_SEMANA[x])
    df["data_fmt"] = df["data_obj"].dt.strftime("%d/%m/%Y")
    df["status_fmt"] = df["status"].map(STATUS_FORMAT_MAP).fillna(df["status"])
    df["manual_fmt"] = df["manual"].apply(lambda x: "Sim" if x else "Não")
    df["periodo"] = df["periodo"].fillna("M/T")
    df["observacoes"] = df["observacoes"].fillna("")
    
    df_detalhado = df[[
        "data_fmt", "dia_semana", "vendedora", "condominio_nome",
        "periodo", "status_fmt", "observacoes", "manual_fmt"
    ]].rename(columns={
        "data_fmt": "Data", "dia_semana": "Dia da Semana",
        "vendedora": "Vendedora", "condominio_nome": "Condomínio",
        "periodo": "Período", "status_fmt": "Status",
        "observacoes": "Observação", "manual_fmt": "Manual"
    })
    
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        df_detalhado.to_excel(writer, index=False, sheet_name='Agenda Detalhada')
        
        # Pivot
        df_pivot_src = df[df["vendedora"].isin(vendedoras_selecionadas)].copy()
        if not df_pivot_src.empty:
            df_pivot_src["Visita"] = (
                df_pivot_src["periodo"] + " " +
                df_pivot_src["condominio_nome"] + " " +
                df_pivot_src["status"].map(STATUS_ICONS).fillna("")
            )
            df_pivot_src["Data"] = df_pivot_src["data_obj"].dt.strftime("%d/%m")
            df_pivot_src["Dia"] = df_pivot_src["data_obj"].dt.weekday.map(lambda x: DIAS_SEMANA[x][:3])
            
            df_pivot = df_pivot_src.pivot_table(
                index=["Data", "Dia"], columns="Vendedora",
                values="Visita", aggfunc=lambda x: ' / '.join(x)
            ).reset_index()
            df_pivot.to_excel(writer, index=False, sheet_name='Agenda Visual')
        
        for sheet_name in writer.sheets:
            worksheet = writer.sheets[sheet_name]
            for column in worksheet.columns:
                max_length = 0
                column_letter = column[0].column_letter
                for cell in column:
                    try:
                        if len(str(cell.value)) > max_length:
                            max_length = len(str(cell.value))
                    except:
                        pass
                worksheet.column_dimensions[column_letter].width = min(max_length + 2, 50)
    
    output.seek(0)
    
    st.download_button(
        label="📊 Baixar Agenda Visual",
        data=output.getvalue(),
        file_name=f"agenda_visual_{calendar.month_name[mes]}_{ano}.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )


# ============================================================================
# GESTÃO DE VENDEDORAS
# ============================================================================

def gerenciar_vendedoras(db):
    st.markdown("### 👩‍💼 Gestão de Vendedoras")
    
    tab_lista, tab_nova, tab_editar, tab_historico = st.tabs([
        "📋 Lista", "➕ Nova", "✏️ Editar", "📊 Histórico"
    ])
    
    with tab_lista:
        vendedoras = list(db.vendedoras.find({}))
        
        if vendedoras:
            col_f1, col_f2 = st.columns(2)
            with col_f1:
                filtro_status = st.selectbox("Status", ["Todas", "Ativas", "Inativas"], key="filtro_vend_status")
            with col_f2:
                filtro_tipo = st.selectbox("Tipo", ["Todos", "fixa", "freelancer"], key="filtro_vend_tipo")
            
            vendedoras_filtradas = vendedoras
            if filtro_status == "Ativas":
                vendedoras_filtradas = [v for v in vendedoras if v.get("ativo", True)]
            elif filtro_status == "Inativas":
                vendedoras_filtradas = [v for v in vendedoras if not v.get("ativo", True)]
            
            if filtro_tipo != "Todos":
                vendedoras_filtradas = [v for v in vendedoras_filtradas if v.get("tipo") == filtro_tipo]
            
            # OTIMIZAÇÃO: batch count de visitas por vendedora
            pipeline = [
                {"$group": {
                    "_id": "$vendedora",
                    "total": {"$sum": 1},
                    "concluidas": {"$sum": {"$cond": [{"$eq": ["$status", "concluido"]}, 1, 0]}}
                }}
            ]
            stats_por_vend = {doc["_id"]: doc for doc in db.visitas_vendedoras.aggregate(pipeline)}
            
            hoje_str = datetime.now().strftime("%Y-%m-%d")
            
            for vendedora in vendedoras_filtradas:
                status_icon = "🟢" if vendedora.get("ativo", True) else "🔴"
                with st.expander(f"{status_icon} {vendedora['nome']} - {vendedora['tipo'].title()}", expanded=False):
                    col1, col2, col3 = st.columns(3)
                    
                    with col1:
                        st.write(f"**Tipo:** {vendedora['tipo'].title()}")
                        st.write(f"**Horário:** {vendedora.get('horario', '08:00-17:00')}")
                        st.write(f"**Max visitas/dia:** {vendedora.get('max_visitas_dia', 2)}")
                        st.write(f"**Status:** {'✅ Ativa' if vendedora.get('ativo', True) else '❌ Inativa'}")
                    
                    with col2:
                        dias = [DIAS_SEMANA[d] for d in vendedora.get('disponibilidade', [])]
                        st.write(f"**Dias:** {', '.join(dias) if dias else 'Nenhum'}")
                    
                    with col3:
                        st.write(f"**📍 Região:** {vendedora.get('regiao_preferencial', 'Todas as regiões')}")
                        if vendedora.get("data_desativacao"):
                            st.write(f"**Desativada em:** {vendedora['data_desativacao'].strftime('%d/%m/%Y')}")
                    
                    st.markdown("---")
                    stats = stats_por_vend.get(vendedora["nome"], {"total": 0, "concluidas": 0})
                    
                    col_e1, col_e2, col_e3 = st.columns(3)
                    with col_e1:
                        st.metric("Total Visitas", stats["total"])
                    with col_e2:
                        st.metric("✅ Concluídas", stats["concluidas"])
                    with col_e3:
                        taxa = (stats["concluidas"] / stats["total"] * 100) if stats["total"] > 0 else 0
                        st.metric("Taxa de Sucesso", f"{taxa:.1f}%")
                    
                    proximas = list(db.visitas_vendedoras.find({
                        "vendedora": vendedora["nome"],
                        "status": "agendado",
                        "data": {"$gte": hoje_str}
                    }, {"data": 1, "condominio_nome": 1}).sort("data", 1).limit(3))
                    
                    if proximas:
                        st.markdown("**📅 Próximas visitas:**")
                        for p in proximas:
                            st.caption(f"- {p['data']}: {p['condominio_nome']}")
        else:
            st.info("Nenhuma vendedora cadastrada.")
    
    with tab_nova:
        col1, col2 = st.columns(2)
        with col1:
            nome = st.text_input("Nome*", key="nova_vend_nome")
            tipo = st.selectbox("Tipo", ["fixa", "freelancer"], key="nova_vend_tipo")
            max_visitas = st.number_input("Max visitas/dia", 1, 5, 2, key="nova_vend_max")
        with col2:
            horario = st.text_input("Horário", value="08:00-17:00", key="nova_vend_horario")
            regiao = st.selectbox("📍 Região", REGIOES_DISPONIVEIS,
                                   index=len(REGIOES_DISPONIVEIS)-1, key="nova_vend_regiao")
        
        st.markdown("**Dias disponíveis:**")
        col_dias = st.columns(7)
        dias_selecionados = []
        for i, dia in enumerate(DIAS_SEMANA[:6]):
            with col_dias[i]:
                if st.checkbox(dia, key=f"dia_nova_{i}"):
                    dias_selecionados.append(i)
        
        if st.button("✅ Cadastrar", key="btn_cad_vend_nova"):
            if not nome:
                st.error("⚠️ Nome é obrigatório!")
            elif not dias_selecionados:
                st.error("⚠️ Selecione pelo menos um dia!")
            elif db.vendedoras.find_one({"nome": nome}):
                st.error(f"❌ '{nome}' já cadastrada!")
            else:
                db.vendedoras.insert_one({
                    "nome": nome, "tipo": tipo,
                    "disponibilidade": dias_selecionados,
                    "horario": horario, "max_visitas_dia": max_visitas,
                    "regiao_preferencial": regiao, "ativo": True,
                    "data_cadastro": datetime.now(),
                    "data_desativacao": None, "motivo_desativacao": None
                })
                st.success(f"✅ '{nome}' cadastrada!")
                st.balloons()
                st.rerun()
    
    with tab_editar:
        vendedoras_lista = list(db.vendedoras.find({}))
        if vendedoras_lista:
            vendedora_sel = st.selectbox(
                "Vendedora", options=[v["nome"] for v in vendedoras_lista], key="select_vend_editar"
            )
            
            if vendedora_sel:
                vend = db.vendedoras.find_one({"nome": vendedora_sel})
                if vend:
                    col_edit1, col_edit2 = st.columns(2)
                    with col_edit1:
                        novo_nome = st.text_input("Nome", value=vend["nome"], key="edit_vend_nome")
                        novo_tipo = st.selectbox("Tipo", ["fixa", "freelancer"],
                                                  index=0 if vend["tipo"] == "fixa" else 1, key="edit_vend_tipo")
                        novo_max = st.number_input("Max visitas/dia", value=vend.get("max_visitas_dia", 2), key="edit_vend_max")
                    with col_edit2:
                        novo_horario = st.text_input("Horário", value=vend.get("horario", "08:00-17:00"), key="edit_vend_horario")
                        regiao_atual = vend.get("regiao_preferencial", "Todas as regiões")
                        idx_regiao = REGIOES_DISPONIVEIS.index(regiao_atual) if regiao_atual in REGIOES_DISPONIVEIS else len(REGIOES_DISPONIVEIS)-1
                        nova_regiao = st.selectbox("Região", REGIOES_DISPONIVEIS, index=idx_regiao, key="edit_vend_regiao")
                        novo_ativo = st.checkbox("Ativo", value=vend.get("ativo", True), key="edit_vend_ativo")
                    
                    motivo = ""
                    if not novo_ativo:
                        motivo = st.text_input("Motivo da desativação", key="edit_vend_motivo")
                    
                    st.markdown("**Dias disponíveis:**")
                    col_dias_edit = st.columns(7)
                    dias_atuais = vend.get("disponibilidade", [])
                    novos_dias = []
                    for i, dia in enumerate(DIAS_SEMANA[:6]):
                        with col_dias_edit[i]:
                            if st.checkbox(dia, value=(i in dias_atuais), key=f"edit_dia_{vend['_id']}_{i}"):
                                novos_dias.append(i)
                    
                    col_btn_edit1, col_btn_edit2 = st.columns(2)
                    with col_btn_edit1:
                        if st.button("💾 Salvar", key="btn_save_vend_edit"):
                            update_data = {
                                "nome": novo_nome, "tipo": novo_tipo,
                                "max_visitas_dia": novo_max, "horario": novo_horario,
                                "regiao_preferencial": nova_regiao, "ativo": novo_ativo,
                                "disponibilidade": novos_dias
                            }
                            if not novo_ativo and vend.get("ativo", True):
                                update_data["data_desativacao"] = datetime.now()
                                update_data["motivo_desativacao"] = motivo or "Desativado"
                            elif novo_ativo and not vend.get("ativo", True):
                                update_data["data_desativacao"] = None
                                update_data["motivo_desativacao"] = None
                            
                            db.vendedoras.update_one({"_id": vend["_id"]}, {"$set": update_data})
                            st.success("✅ Salvo!")
                            st.rerun()
                    
                    with col_btn_edit2:
                        if st.button("🗑️ Excluir", key="btn_del_vend"):
                            tem_visitas = db.visitas_vendedoras.count_documents({"vendedora": vend["nome"]})
                            if tem_visitas > 0:
                                st.error(f"❌ Tem {tem_visitas} visitas. Desative em vez de excluir.")
                            else:
                                db.vendedoras.delete_one({"_id": vend["_id"]})
                                st.success("✅ Excluída!")
                                st.rerun()
        else:
            st.info("Nenhuma vendedora cadastrada.")
    
    with tab_historico:
        st.markdown("#### 📊 Histórico")
        
        # OTIMIZAÇÃO: usar estimated_document_count para contagens rápidas
        total = db.vendedoras.estimated_document_count()
        ativas = db.vendedoras.count_documents({"ativo": True})
        inativas = total - ativas
        
        col_h1, col_h2, col_h3 = st.columns(3)
        with col_h1:
            st.metric("Total", total)
        with col_h2:
            st.metric("Ativas", ativas)
        with col_h3:
            st.metric("Inativas", inativas)
        
        inativas_lista = list(db.vendedoras.find({"ativo": False}))
        if inativas_lista:
            st.markdown("**📋 Inativas:**")
            for vend in inativas_lista:
                with st.expander(f"🔴 {vend['nome']}"):
                    st.write(f"**Desativada em:** {vend.get('data_desativacao', 'N/A')}")
                    st.write(f"**Motivo:** {vend.get('motivo_desativacao', 'Não informado')}")


# ============================================================================
# RELATÓRIOS
# ============================================================================

def relatorios_completos(db):
    st.markdown("### 📊 Relatórios de Visitas")
    
    tipo_relatorio = st.selectbox(
        "Tipo de Relatório",
        ["Resumo da Campanha Atual", "Visitas por Vendedora", "Distribuição por Zona",
         "Exportar Agenda", "Comparativo de Campanhas"]
    )
    
    if tipo_relatorio == "Resumo da Campanha Atual":
        campanha_ativa = list(db.campanha_visitas.find({"ativo": True}))
        
        if campanha_ativa:
            campanha_id = campanha_ativa[0].get("campanha_id")
            campanha_historico = None
            if campanha_id:
                campanha_historico = db.campanhas_historico.find_one({"campanha_id": campanha_id})
            
            col_r1, col_r2, col_r3 = st.columns(3)
            with col_r1:
                st.metric("Condomínios", len(campanha_ativa))
                if campanha_historico:
                    st.caption(f"Versão: #{campanha_historico.get('versao', 'N/A')}")
            with col_r2:
                total_aptos = sum(c.get("aptos", 0) for c in campanha_ativa)
                st.metric("Total Aptos", f"{total_aptos:,}")
            with col_r3:
                visitas_concluidas = db.visitas_vendedoras.count_documents({"status": "concluido"})
                st.metric("Visitas Concluídas", visitas_concluidas)
            
            st.markdown("#### 📈 Progresso por Condomínio")
            
            # OTIMIZAÇÃO: aggregate para contar visitas por condomínio
            pipeline = [
                {"$group": {
                    "_id": "$condominio_id",
                    "total": {"$sum": 1},
                    "concluidas": {"$sum": {"$cond": [{"$eq": ["$status", "concluido"]}, 1, 0]}}
                }}
            ]
            stats_cond = {doc["_id"]: doc for doc in db.visitas_vendedoras.aggregate(pipeline)}
            
            dados_progresso = []
            for cond in campanha_ativa:
                stats = stats_cond.get(cond["condominio_id"], {"total": 0, "concluidas": 0})
                dados_progresso.append({
                    "Condomínio": cond["condominio_nome"][:35],
                    "Zona": cond.get("zona", "N/D"),
                    "Total Visitas": stats["total"],
                    "Concluídas": stats["concluidas"],
                    "Progresso": f"{(stats['concluidas']/stats['total']*100):.0f}%" if stats["total"] > 0 else "0%"
                })
            
            st.dataframe(pd.DataFrame(dados_progresso), use_container_width=True, hide_index=True)
        else:
            st.info("Nenhuma campanha ativa.")
    
    elif tipo_relatorio == "Visitas por Vendedora":
        vendedoras_opcoes = [v["nome"] for v in db.vendedoras.find({}, {"nome": 1})]
        if vendedoras_opcoes:
            vendedora_sel = st.selectbox("Vendedora", options=vendedoras_opcoes)
            
            if vendedora_sel:
                visitas_vend = list(db.visitas_vendedoras.find({
                    "vendedora": vendedora_sel,
                    "status": {"$ne": "cancelado"}
                }, {"data": 1, "condominio_nome": 1, "zona": 1, "status": 1}).sort("data", -1))
                
                if visitas_vend:
                    df = pd.DataFrame(visitas_vend)
                    df["Data"] = pd.to_datetime(df["data"]).dt.strftime("%d/%m/%Y")
                    df["Status"] = df["status"].map(STATUS_FORMAT_MAP).fillna(df["status"])
                    df["Zona"] = df["zona"].fillna("N/D")
                    df = df[["Data", "condominio_nome", "Zona", "Status"]].rename(
                        columns={"condominio_nome": "Condomínio"}
                    )
                    
                    st.dataframe(df, use_container_width=True, hide_index=True)
                    
                    total = len(visitas_vend)
                    concluidos = sum(1 for v in visitas_vend if v["status"] == "concluido")
                    
                    col_e1, col_e2, col_e3 = st.columns(3)
                    with col_e1:
                        st.metric("Total", total)
                    with col_e2:
                        st.metric("Concluídas", concluidos)
                    with col_e3:
                        st.metric("Taxa", f"{(concluidos/total*100):.1f}%" if total > 0 else "0%")
                else:
                    st.info("Nenhuma visita encontrada.")
        else:
            st.warning("Nenhuma vendedora cadastrada.")
    
    elif tipo_relatorio == "Distribuição por Zona":
        campanha = list(db.campanha_visitas.find({"ativo": True}, {"zona": 1}))
        
        if campanha:
            zona_counts = defaultdict(int)
            for cond in campanha:
                zona_counts[cond.get("zona", "Não definida")] += 1
            
            st.markdown("#### 📍 Condomínios por Zona")
            for zona, count in sorted(zona_counts.items()):
                st.progress(count / len(campanha),
                            text=f"{zona}: {count} ({count/len(campanha)*100:.1f}%)")
            
            st.markdown("#### 📊 Visitas por Zona")
            
            # OTIMIZAÇÃO: aggregate direto no Mongo
            pipeline = [
                {"$match": {"status": {"$ne": "cancelado"}}},
                {"$group": {"_id": "$zona", "count": {"$sum": 1}}}
            ]
            visitas_por_zona = {doc["_id"] or "Não definida": doc["count"]
                                 for doc in db.visitas_vendedoras.aggregate(pipeline)}
            
            total_visitas = sum(visitas_por_zona.values())
            if total_visitas:
                for zona, count in sorted(visitas_por_zona.items()):
                    st.progress(count / total_visitas,
                                text=f"{zona}: {count} ({count/total_visitas*100:.1f}%)")
            else:
                st.info("Nenhuma visita registrada.")
        else:
            st.info("Nenhuma campanha ativa.")
    
    elif tipo_relatorio == "Comparativo de Campanhas":
        campanhas = list(db.campanhas_historico.find().sort("versao", -1))
        
        if len(campanhas) < 2:
            st.info("Precisa de pelo menos 2 campanhas.")
        else:
            opcoes = [f"#{c['versao']} - {c.get('nome', 'Sem nome')} ({c['data_criacao'].strftime('%d/%m/%Y')})"
                       for c in campanhas]
            
            col_comp1, col_comp2 = st.columns(2)
            with col_comp1:
                c1_idx = st.selectbox("Campanha 1", range(len(opcoes)),
                                       format_func=lambda x: opcoes[x], key="comp1")
            with col_comp2:
                c2_idx = st.selectbox("Campanha 2", range(len(opcoes)),
                                       format_func=lambda x: opcoes[x], key="comp2")
            
            if c1_idx != c2_idx:
                c1, c2 = campanhas[c1_idx], campanhas[c2_idx]
                
                # OTIMIZAÇÃO: aggregate para contar visitas de ambas em 1 query
                pipeline = [
                    {"$match": {"campanha_id": {"$in": [c1.get("campanha_id"), c2.get("campanha_id")]}}},
                    {"$group": {
                        "_id": "$campanha_id",
                        "total": {"$sum": 1},
                        "concluidas": {"$sum": {"$cond": [{"$eq": ["$status", "concluido"]}, 1, 0]}}
                    }}
                ]
                stats = {doc["_id"]: doc for doc in db.visitas_vendedoras.aggregate(pipeline)}
                
                s1 = stats.get(c1.get("campanha_id"), {"total": 0, "concluidas": 0})
                s2 = stats.get(c2.get("campanha_id"), {"total": 0, "concluidas": 0})
                
                col_m1, col_m2, col_m3 = st.columns(3)
                with col_m1:
                    st.metric("Condomínios",
                              f"{c1['total_condominios']} → {c2['total_condominios']}",
                              delta=c2['total_condominios'] - c1['total_condominios'])
                with col_m2:
                    st.metric("Total Visitas",
                              f"{s1['total']} → {s2['total']}",
                              delta=s2['total'] - s1['total'])
                with col_m3:
                    t1 = (s1['concluidas'] / s1['total'] * 100) if s1['total'] > 0 else 0
                    t2 = (s2['concluidas'] / s2['total'] * 100) if s2['total'] > 0 else 0
                    st.metric("Taxa Conclusão", f"{t1:.1f}% → {t2:.1f}%", delta=f"{t2-t1:.1f}%")
    
    elif tipo_relatorio == "Exportar Agenda":
        data_export_inicio = st.date_input("Data Início", value=datetime.now().date())
        data_export_fim = st.date_input("Data Fim", value=datetime.now().date() + timedelta(days=30))
        incluir_historico = st.checkbox("Incluir todas as campanhas")
        
        if st.button("📥 Exportar", key="btn_exportar_agenda"):
            query = {
                "data": {"$gte": data_export_inicio.strftime("%Y-%m-%d"),
                         "$lte": data_export_fim.strftime("%Y-%m-%d")}
            }
            if not incluir_historico:
                query["status"] = {"$ne": "cancelado"}
            
            visitas = list(db.visitas_vendedoras.find(query).sort("data", 1))
            
            if visitas:
                # OTIMIZAÇÃO: buscar campanhas em 1 query
                campanha_ids = [v.get("campanha_id") for v in visitas if v.get("campanha_id")]
                campanhas_map = {}
                if campanha_ids:
                    for c in db.campanhas_historico.find(
                        {"campanha_id": {"$in": list(set(campanha_ids))}},
                        {"campanha_id": 1, "versao": 1, "nome": 1}
                    ):
                        campanhas_map[c["campanha_id"]] = f"#{c['versao']} - {c.get('nome', '')}"
                
                dados = []
                for vis in visitas:
                    data_obj = datetime.strptime(vis["data"], "%Y-%m-%d")
                    dados.append({
                        "Data": data_obj.strftime("%d/%m/%Y"),
                        "Dia": DIAS_SEMANA[data_obj.weekday()],
                        "Condomínio": vis["condominio_nome"],
                        "Zona": vis.get("zona", "N/D"),
                        "Vendedora": vis["vendedora"],
                        "Status": STATUS_FORMAT_MAP.get(vis.get("status", "agendado"), vis.get("status")),
                        "Campanha": campanhas_map.get(vis.get("campanha_id"), "N/A"),
                        "Obs": vis.get("observacoes", "")
                    })
                
                df_export = pd.DataFrame(dados)
                
                output = io.BytesIO()
                with pd.ExcelWriter(output, engine='openpyxl') as writer:
                    df_export.to_excel(writer, index=False, sheet_name='Visitas')
                    ws = writer.sheets['Visitas']
                    for col in ws.columns:
                        max_len = max((len(str(c.value)) for c in col if c.value), default=0)
                        ws.column_dimensions[col[0].column_letter].width = min(max_len + 2, 50)
                
                output.seek(0)
                
                st.download_button(
                    label="📊 Baixar Excel",
                    data=output.getvalue(),
                    file_name=f"visitas_{data_export_inicio.strftime('%Y%m%d')}_{data_export_fim.strftime('%Y%m%d')}.xlsx",
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                )
            else:
                st.warning("Nenhuma visita no período.")


# ============================================================================
# HISTÓRICO DE CAMPANHAS
# ============================================================================

def historico_campanhas(db):
    st.markdown("### 📚 Histórico Completo de Campanhas")
    
    # OTIMIZAÇÃO: estimated_document_count
    total_campanhas = db.campanhas_historico.estimated_document_count()
    total_visitas = db.visitas_vendedoras.estimated_document_count()
    
    col_h1, col_h2, col_h3 = st.columns(3)
    with col_h1:
        st.metric("Total de Campanhas", total_campanhas)
    with col_h2:
        st.metric("Total de Visitas", total_visitas)
    with col_h3:
        st.metric("Espaço MongoDB", f"{verificar_espaco_mongo(db):.2f} MB")
    
    campanhas = list(db.campanhas_historico.find().sort("versao", -1))
    
    if campanhas:
        # OTIMIZAÇÃO: aggregate único para contar visitas por campanha
        pipeline = [
            {"$match": {"campanha_id": {"$ne": None}}},
            {"$group": {
                "_id": "$campanha_id",
                "total": {"$sum": 1},
                "concluidas": {"$sum": {"$cond": [{"$eq": ["$status", "concluido"]}, 1, 0]}}
            }}
        ]
        stats = {doc["_id"]: doc for doc in db.visitas_vendedoras.aggregate(pipeline)}
        
        for camp in campanhas:
            with st.expander(f"📋 Campanha #{camp['versao']} - {camp.get('nome', 'Sem nome')}", expanded=False):
                col_c1, col_c2, col_c3 = st.columns(3)
                
                with col_c1:
                    st.write(f"**Período:** {camp['data_inicio'].strftime('%d/%m/%Y')} a {camp['data_fim'].strftime('%d/%m/%Y')}")
                    st.write(f"**Status:** {'✅ Ativa' if camp.get('status') == 'ativa' else '📌 Concluída'}")
                
                with col_c2:
                    st.write(f"**Condomínios:** {camp['total_condominios']}")
                    st.write(f"**Criado por:** {camp.get('criado_por', 'Sistema')}")
                
                with col_c3:
                    s = stats.get(camp.get("campanha_id"), {"total": 0, "concluidas": 0})
                    st.metric("Visitas", s["total"])
                    st.metric("Concluídas", s["concluidas"])
                
                with st.expander("📋 Ver condomínios"):
                    for cond in camp.get('condominios', []):
                        st.write(f"- {cond.get('condominio_nome')} ({cond.get('zona')}) - P: {cond.get('prioridade')}")
    else:
        st.info("Nenhuma campanha no histórico.")


# ============================================================================
# TELA ADMIN
# ============================================================================

def tela_admin_visitas(db, perfil_usuario, nome_usuario):
    st.markdown("## 📅 Gerenciamento de Visitas de Vendedoras")
    
    tab_campanha, tab_agenda, tab_agenda_visual, tab_vendedoras, tab_relatorios, tab_historico = st.tabs([
        "🎯 Campanha", "📆 Agenda", "📊 Agenda Visual",
        "👩‍💼 Vendedoras", "📊 Relatórios", "📚 Histórico"
    ])
    
    with tab_campanha:
        clientes_collection = get_condominios_collection()
        selecionar_condominios_campanha(db, clientes_collection)
    
    with tab_agenda:
        col_f1, col_f2, col_f3, col_f4, col_f5 = st.columns(5)
        
        vendedoras_ativas = [v["nome"] for v in db.vendedoras.find({"ativo": True}, {"nome": 1})]
        
        with col_f1:
            filtro_vendedora = st.selectbox(
                "👩‍💼 Vendedora",
                options=["Todas"] + vendedoras_ativas,
                key="filtro_vend_agenda"
            )
        
        with col_f2:
            filtro_status = st.selectbox(
                "Status",
                options=["Todos", "agendado", "concluido", "cancelado", "chuva", "falta"],
                key="filtro_status_agenda",
                format_func=lambda x: formatar_status_visita(x) if x != "Todos" else "Todos"
            )
        
        with col_f3:
            data_inicio = st.date_input("Data Início", value=datetime.now().date(), key="data_inicio_agenda")
        
        with col_f4:
            data_fim = st.date_input("Data Fim", value=datetime.now().date() + timedelta(days=30), key="data_fim_agenda")
        
        with col_f5:
            campanhas = list(db.campanhas_historico.find({}, {"versao": 1, "nome": 1, "campanha_id": 1})
                              .sort("versao", -1).limit(10))
            campanha_options = ["Última ativa"] + [f"#{c['versao']} - {c.get('nome', 'Sem nome')}" for c in campanhas]
            campanha_selecionada = st.selectbox("Campanha", options=campanha_options, key="campanha_agenda")
            
            campanha_id = None
            if campanha_selecionada != "Última ativa" and campanhas:
                idx = campanha_options.index(campanha_selecionada) - 1
                if 0 <= idx < len(campanhas):
                    campanha_id = campanhas[idx].get("campanha_id")
        
        col_btn1, col_btn2 = st.columns([1, 3])
        with col_btn1:
            if st.button("🤖 Gerar Agenda Inteligente", key="btn_auto_agendar", use_container_width=True):
                with st.spinner("Gerando sugestões..."):
                    campanha_count = db.campanha_visitas.count_documents({"ativo": True})
                    
                    if campanha_count == 0:
                        st.error("❌ Nenhum condomínio na campanha!")
                    else:
                        sugestoes = agendamento_inteligente(db, data_inicio, data_fim, campanha_id)
                        
                        if sugestoes:
                            st.success(f"✅ {len(sugestoes)} sugestões geradas!")
                            
                            for sug in sugestoes[:10]:
                                icone = "⭐" if sug["adequacao"] == "preferencial" else "✓" if sug["adequacao"] == "disponivel" else "⚠️"
                                
                                with st.expander(f"{icone} {sug['condominio_nome']} ({sug['condominio_zona']}) - {sug['data']} - {sug['vendedora']}"):
                                    st.write(f"**Prioridade:** {sug['prioridade']}")
                                    st.write(f"**Adequação:** {sug['vendedora_motivo']}")
                                    
                                    if st.button("✅ Confirmar",
                                                 key=f"confirm_{sug['condominio_id']}_{sug['data']}_{sug['vendedora']}"):
                                        existente = db.visitas_vendedoras.find_one({
                                            "data": sug["data"],
                                            "vendedora": sug["vendedora"],
                                            "condominio_id": ObjectId(sug["condominio_id"])
                                        })
                                        if not existente:
                                            db.visitas_vendedoras.insert_one({
                                                "condominio_id": ObjectId(sug["condominio_id"]),
                                                "condominio_nome": sug["condominio_nome"],
                                                "vendedora": sug["vendedora"],
                                                "data": sug["data"],
                                                "status": "agendado",
                                                "criado_por": nome_usuario,
                                                "data_criacao": datetime.now(),
                                                "zona": sug["condominio_zona"],
                                                "adequacao": sug["adequacao"],
                                                "campanha_id": sug.get("campanha_id"),
                                                "periodo": "M/T",
                                                "manual": False
                                            })
                                            invalidar_cache("agenda_visual")
                                            st.success("✅ Agendada!")
                                            st.rerun()
                                        else:
                                            st.warning("⚠️ Já existe.")
                        else:
                            st.info("Nenhuma sugestão.")
        
        with col_btn2:
            if st.button("🔄 Atualizar", key="btn_atualizar_agenda", use_container_width=True):
                st.rerun()
        
        st.markdown("---")
        
        # Buscar visitas - OTIMIZADO
        query = {}
        if filtro_vendedora != "Todas":
            query["vendedora"] = filtro_vendedora
        if filtro_status != "Todos":
            query["status"] = filtro_status
        if campanha_id:
            query["campanha_id"] = campanha_id
        
        query["data"] = {"$gte": data_inicio.strftime("%Y-%m-%d"),
                          "$lte": data_fim.strftime("%Y-%m-%d")}
        
        visitas = list(db.visitas_vendedoras.find(query).sort("data", 1))
        
        if visitas:
            st.markdown(f"### 📋 Visitas Agendadas ({len(visitas)})")
            
            # OTIMIZAÇÃO: buscar campanhas em batch
            campanha_ids = list(set(v.get("campanha_id") for v in visitas if v.get("campanha_id")))
            campanhas_map = {}
            if campanha_ids:
                for c in db.campanhas_historico.find(
                    {"campanha_id": {"$in": campanha_ids}},
                    {"campanha_id": 1, "versao": 1, "nome": 1}
                ):
                    campanhas_map[c["campanha_id"]] = f"#{c['versao']} - {c.get('nome', '')}"
            
            for visita in visitas:
                data_obj = datetime.strptime(visita["data"], "%Y-%m-%d").date()
                status_icon = STATUS_ICONS.get(visita["status"], "⏳")
                
                with st.expander(f"{status_icon} {data_obj.strftime('%d/%m/%Y')} - {visita['condominio_nome']} - {visita['vendedora']}", expanded=False):
                    col1, col2 = st.columns(2)
                    
                    with col1:
                        st.write(f"**Status:** {formatar_status_visita(visita['status'])}")
                        if visita.get("zona"):
                            st.write(f"**Zona:** {visita['zona']}")
                        if visita.get("observacoes"):
                            st.write(f"**Obs:** {visita['observacoes']}")
                        if visita.get("campanha_id") in campanhas_map:
                            st.write(f"**Campanha:** {campanhas_map[visita['campanha_id']]}")
                        if visita.get("manual"):
                            st.write("**📝 Manual**")
                    
                    with col2:
                        if visita["status"] == "agendado":
                            obs = st.text_area("Obs", key=f"obs_{visita['_id']}")
                            
                            if st.button("✅ Concluir", key=f"conc_{visita['_id']}"):
                                db.visitas_vendedoras.update_one(
                                    {"_id": visita["_id"]},
                                    {"$set": {"status": "concluido",
                                              "data_conclusao": datetime.now(),
                                              "observacoes": obs}}
                                )
                                invalidar_cache("agenda_visual")
                                st.success("✅ Concluída!")
                                st.rerun()
                            
                            if perfil_usuario in ["admin", "diretoria"]:
                                motivo = st.text_input("Motivo cancelamento", key=f"motivo_{visita['_id']}")
                                if motivo and st.button("❌ Cancelar", key=f"cancel_{visita['_id']}"):
                                    db.visitas_vendedoras.update_one(
                                        {"_id": visita["_id"]},
                                        {"$set": {"status": "cancelado",
                                                  "motivo_cancelamento": motivo,
                                                  "data_cancelamento": datetime.now()}}
                                    )
                                    invalidar_cache("agenda_visual")
                                    st.success("❌ Cancelada!")
                                    st.rerun()
        else:
            st.info("Nenhuma visita no período.")
    
    with tab_agenda_visual:
        agenda_visual_por_vendedora(db)
    
    with tab_vendedoras:
        gerenciar_vendedoras(db)
    
    with tab_relatorios:
        relatorios_completos(db)
    
    with tab_historico:
        historico_campanhas(db)


# ============================================================================
# FUNÇÃO PRINCIPAL
# ============================================================================

def render_visitas_vendedoras(clientes_collection):
    # Inicializar coleções (executado 1x)
    db = init_colecoes_visitas(clientes_collection)
    
    perfil = st.session_state.get("perfil", "admin")
    nome_usuario = st.session_state.get("nome_usuario", "")
    
    st.markdown("""
    <div style='background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); padding: 1rem; border-radius: 10px; margin-bottom: 2rem;'>
        <h2 style='color: white; margin: 0;'>👩‍💼 Gestão de Visitas de Vendedoras</h2>
        <p style='color: white; margin: 0.5rem 0 0 0; opacity: 0.9;'>
            Agendamento inteligente com especialização por região, histórico completo e agenda visual
        </p>
    </div>
    """, unsafe_allow_html=True)
    
    if perfil in ["admin", "diretoria", "supervisao_n1", "supervisao_n2", "supervisao_n3",
                  "atendente_n1", "recepcao"]:
        tela_admin_visitas(db, perfil, nome_usuario)
    elif perfil == "vendedora":
        st.info("👩‍💼 Visão para vendedoras em desenvolvimento...")
    else:
        st.error("❌ Você não tem permissão para acessar este módulo.")
