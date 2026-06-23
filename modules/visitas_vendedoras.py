# modules/visitas_vendedoras.py
"""
Módulo de Gerenciamento de Visitas de Vendedoras
- Integrado com cadastro de condomínios existente
- Histórico completo de campanhas
- Agendamento inteligente com regras de negócio
- Especialização por região (Zona Sul, Norte, Oeste, etc.)
- Visualizações por perfil (admin, vendedora, atendente)
- Múltiplos relatórios e exportações
- AGENDA VISUAL POR VENDEDORA COM EDIÇÃO MANUAL
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

# Lista de regiões disponíveis
REGIOES_DISPONIVEIS = [
    "Zona Sul",
    "Zona Norte",
    "Zona Oeste",
    "Zona Sudoeste",
    "Centro",
    "Baixada Fluminense",
    "Todas as regiões"
]

# Configuração padrão de disponibilidade das vendedoras
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

# ============================================================================
# FUNÇÕES AUXILIARES
# ============================================================================

def get_prioridade_condominio(aptos: int = 0, prioridade_manual: str = None) -> str:
    """Define prioridade baseada no número de apartamentos"""
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
    """Retorna peso numérico para ordenação"""
    pesos = {"A+": 5, "A": 4, "B": 3, "C": 2, "D": 1}
    return pesos.get(prioridade, 0)

def calcular_frequencia_semanal(aptos: int) -> int:
    """Calcula quantas visitas por semana com base no tamanho"""
    if aptos >= 1000:
        return 3
    elif aptos >= 500:
        return 2
    elif aptos >= 200:
        return 1
    else:
        return 1

def condominios_proximos(cond1: dict, cond2: dict) -> bool:
    """Verifica se dois condomínios são próximos baseado no bairro"""
    bairro1 = cond1.get('bairro', '').upper().strip()
    bairro2 = cond2.get('bairro', '').upper().strip()
    
    if not bairro1 or not bairro2:
        return False
    
    if bairro1 == bairro2:
        return True
    
    return False

def calcular_adequacao_vendedora_condominio(vendedora: dict, condominio_zona: str) -> dict:
    """
    Calcula o nível de adequação de uma vendedora para um condomínio
    Baseado na região preferencial da vendedora
    """
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
    """Verifica o espaço usado no MongoDB"""
    try:
        stats = db.command("dbStats")
        tamanho_mb = stats.get("dataSize", 0) / (1024 * 1024)
        return tamanho_mb
    except:
        return 0

def formatar_status_visita(status: str) -> str:
    """Formata o status da visita para exibição"""
    status_map = {
        "agendado": "🟢 Agendado",
        "concluido": "✅ Concluído",
        "cancelado": "🔴 Cancelado",
        "chuva": "🌧️ Chuva",
        "falta": "⛔ Falta",
        "feriado": "🔴 Feriado"
    }
    return status_map.get(status, status)

# ============================================================================
# INICIALIZAÇÃO DAS COLEÇÕES
# ============================================================================

def init_colecoes_visitas(clientes_collection):
    """Inicializa as coleções necessárias para o módulo"""
    db = clientes_collection.database
    
    # Coleção para histórico de campanhas
    if 'campanhas_historico' not in db.list_collection_names():
        db.create_collection('campanhas_historico')
        db.campanhas_historico.create_index("data_criacao")
        db.campanhas_historico.create_index("status")
        db.campanhas_historico.create_index("versao")
    
    # Coleção para campanha atual (mantida para compatibilidade)
    if 'campanha_visitas' not in db.list_collection_names():
        db.create_collection('campanha_visitas')
        db.campanha_visitas.create_index("condominio_id", unique=True)
    
    # Coleção de vendedoras
    if 'vendedoras' not in db.list_collection_names():
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
    
    # Coleção de visitas agendadas
    if 'visitas_vendedoras' not in db.list_collection_names():
        db.create_collection('visitas_vendedoras')
        db.visitas_vendedoras.create_index([("data", 1), ("vendedora", 1)])
        db.visitas_vendedoras.create_index([("condominio_id", 1), ("data", 1)])
        db.visitas_vendedoras.create_index("status")
        db.visitas_vendedoras.create_index("campanha_id")
    
    return db

# ============================================================================
# SELEÇÃO DE CONDOMÍNIOS PARA CAMPANHA COM HISTÓRICO
# ============================================================================

def selecionar_condominios_campanha(db, clientes_collection):
    """
    Interface para selecionar quais condomínios participarão da campanha de visitas
    COM HISTÓRICO COMPLETO
    """
    st.markdown("### 🎯 Seleção de Condomínios para Campanha de Visitas")
    
    # Buscar condomínios do cadastro principal
    condominios_cadastro = get_all_condominios()
    
    if not condominios_cadastro:
        st.warning("⚠️ Nenhum condomínio cadastrado no sistema. Cadastre condomínios primeiro.")
        return
    
    # Buscar campanha ativa atual
    campanha_ativa = list(db.campanha_visitas.find({}))
    
    # Informações da última campanha
    ultima_campanha = db.campanhas_historico.find_one(
        {}, 
        sort=[("versao", -1)]
    )
    
    col_info1, col_info2, col_info3 = st.columns(3)
    with col_info1:
        st.info(f"📊 **Total disponível:** {len(condominios_cadastro)} condomínios")
    with col_info2:
        if ultima_campanha:
            st.info(f"📌 **Última versão:** Campanha #{ultima_campanha.get('versao', 0)}")
    with col_info3:
        total_campanhas = db.campanhas_historico.count_documents({})
        st.info(f"📚 **Total campanhas:** {total_campanhas}")
    
    # Preparar dados para seleção
    dados_selecao = []
    for cond in condominios_cadastro:
        aptos = cond.get("apartamentos", 0) or cond.get("aptos", 0) or 0
        prioridade = get_prioridade_condominio(aptos)
        zona = cond.get("zona", "Não definida")
        
        # Verificar se já está na campanha atual
        campanha = db.campanha_visitas.find_one({"condominio_id": cond["_id"]})
        
        dados_selecao.append({
            "Selecionar": campanha is not None,
            "Condomínio": cond["nome"],
            "Bairro": cond.get("bairro", "N/I"),
            "Zona": zona,
            "Aptos": aptos,
            "Prioridade": prioridade,
            "Visitas/Semana": calcular_frequencia_semanal(aptos),
            "ID": str(cond["_id"])
        })
    
    df = pd.DataFrame(dados_selecao)
    
    # Editor de seleção
    st.markdown("#### 📋 Selecione os condomínios para a campanha")
    
    edited_df = st.data_editor(
        df,
        column_config={
            "Selecionar": st.column_config.CheckboxColumn(
                "Ativo na Campanha",
                help="Marque para incluir este condomínio nas visitas"
            ),
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
        height=500
    )
    
    # Configuração do período da campanha
    st.markdown("---")
    st.markdown("#### 📅 Período da Campanha")
    
    col_p1, col_p2, col_p3 = st.columns(3)
    
    with col_p1:
        data_inicio = st.date_input(
            "Data de início",
            value=datetime.now().date(),
            help="Quando a campanha começa"
        )
    
    with col_p2:
        data_fim = st.date_input(
            "Data de término",
            value=datetime.now().date() + timedelta(days=120),
            help="Duração sugerida: 3-4 meses (120 dias)"
        )
    
    with col_p3:
        meses = ((data_fim - data_inicio).days) // 30
        st.metric("Duração da Campanha", f"~{meses} meses", f"{((data_fim - data_inicio).days)} dias")
    
    # Nome da campanha
    nome_campanha = st.text_input(
        "🏷️ Nome da Campanha (opcional)",
        value=f"Campanha {datetime.now().strftime('%B %Y')}",
        help="Dê um nome para identificar esta campanha nos relatórios históricos"
    )
    
    # Botões de ação
    col_b1, col_b2, col_b3, col_b4, col_b5, col_b6 = st.columns(6)
    
    with col_b1:
        if st.button("💾 Salvar Campanha", use_container_width=True, type="primary"):
            selecionados = edited_df[edited_df["Selecionar"] == True]
            
            if len(selecionados) == 0:
                st.warning("⚠️ Selecione pelo menos um condomínio!")
            else:
                # Buscar próxima versão
                ultima_versao = db.campanhas_historico.find_one(
                    {}, 
                    sort=[("versao", -1)]
                )
                nova_versao = (ultima_versao.get("versao", 0) + 1) if ultima_versao else 1
                
                # Gerar ID único da campanha
                campanha_id = str(uuid.uuid4())
                
                # Lista de condomínios selecionados
                condominios_selecionados = []
                for _, row in selecionados.iterrows():
                    cond_id = ObjectId(row["ID"])
                    condominios_selecionados.append({
                        "condominio_id": cond_id,
                        "condominio_nome": row["Condomínio"],
                        "bairro": row["Bairro"],
                        "zona": row["Zona"],
                        "aptos": row["Aptos"],
                        "prioridade": row["Prioridade"],
                        "frequencia_sugerida": row["Visitas/Semana"]
                    })
                
                # 1. SALVAR NO HISTÓRICO (NOVO)
                historico_campanha = {
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
                }
                db.campanhas_historico.insert_one(historico_campanha)
                
                # 2. ATUALIZAR CAMPANHA ATUAL (mantido para compatibilidade)
                db.campanha_visitas.delete_many({})
                for cond in condominios_selecionados:
                    db.campanha_visitas.insert_one({
                        "condominio_id": cond["condominio_id"],
                        "condominio_nome": cond["condominio_nome"],
                        "bairro": cond["bairro"],
                        "zona": cond["zona"],
                        "aptos": cond["aptos"],
                        "prioridade": cond["prioridade"],
                        "frequencia_sugerida": cond["frequencia_sugerida"],
                        "data_inicio": datetime.combine(data_inicio, datetime.min.time()),
                        "data_fim": datetime.combine(data_fim, datetime.min.time()),
                        "campanha_id": campanha_id,
                        "versao": nova_versao,
                        "ativo": True,
                        "data_cadastro": datetime.now()
                    })
                
                st.success(f"✅ Campanha #{nova_versao} salva com sucesso! {len(condominios_selecionados)} condomínios selecionados.")
                st.balloons()
                st.rerun()
    
    with col_b2:
        if st.button("🤖 Seleção Inteligente", use_container_width=True):
            df_temp = edited_df.copy()
            df_temp['Peso'] = df_temp['Prioridade'].apply(lambda x: get_peso_prioridade(x))
            df_temp = df_temp.sort_values(['Peso', 'Aptos'], ascending=[False, False])
            
            limite = min(28, len(df_temp))
            indices_selecionados = df_temp.head(limite).index
            edited_df.loc[indices_selecionados, 'Selecionar'] = True
            
            st.success(f"✅ Seleção inteligente concluída! {limite} condomínios selecionados.")
            st.rerun()
    
    with col_b3:
        zona_filter = st.selectbox("Zona", ["Todas"] + REGIOES_DISPONIVEIS[:-1], key="zona_filter")
        if st.button("📍 Selecionar por Zona", use_container_width=True):
            if zona_filter != "Todas":
                df_temp = edited_df[edited_df["Zona"] == zona_filter]
                edited_df.loc[df_temp.index, 'Selecionar'] = True
                st.rerun()
    
    with col_b4:
        prioridade_min = st.selectbox("Prioridade mínima", ["A+", "A", "B", "C", "D"], key="prioridade_min_filter")
        if st.button("⭐ Selecionar por Prioridade", use_container_width=True):
            pesos = {"A+": 5, "A": 4, "B": 3, "C": 2, "D": 1}
            peso_min = pesos.get(prioridade_min, 0)
            
            df_temp = edited_df.copy()
            df_temp['Peso'] = df_temp['Prioridade'].apply(lambda x: get_peso_prioridade(x))
            df_temp = df_temp[df_temp['Peso'] >= peso_min]
            
            edited_df.loc[df_temp.index, 'Selecionar'] = True
            st.rerun()
    
    with col_b5:
        if st.button("🗑️ Limpar Todos", use_container_width=True):
            edited_df['Selecionar'] = False
            st.rerun()
    
    with col_b6:
        # Monitoramento de espaço
        tamanho_mb = verificar_espaco_mongo(db)
        if tamanho_mb > 0:
            st.metric(
                "💾 Espaço MongoDB",
                f"{tamanho_mb:.2f} MB",
                f"{tamanho_mb/512*100:.1f}% do Free Tier"
            )
    
    # Estatísticas da seleção atual
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
        
        # Distribuição por zona
        st.markdown("#### 📍 Distribuição por Zona")
        zona_counts = selecionados_atual["Zona"].value_counts()
        
        cols_zona = st.columns(min(len(zona_counts), 5))
        for idx, (zona, count) in enumerate(zona_counts.items()):
            if idx < len(cols_zona):
                with cols_zona[idx]:
                    st.metric(zona, count)
        
        # Lista detalhada
        with st.expander("📋 Ver lista detalhada dos condomínios selecionados"):
            for _, row in selecionados_atual.sort_values(["Prioridade", "Aptos"], ascending=[True, False]).iterrows():
                st.write(f"**{row['Prioridade']}** - {row['Condomínio']} | {row['Zona']} | {row['Aptos']} aptos | {row['Visitas/Semana']}x/semana")
    else:
        st.warning("Nenhum condomínio selecionado.")

# ============================================================================
# AGENDAMENTO INTELIGENTE COM ESPECIALIZAÇÃO
# ============================================================================

def agendamento_inteligente(db, data_inicio: date, data_fim: date = None, campanha_id: str = None):
    """
    Algoritmo inteligente para sugerir agendamentos baseado nos condomínios da campanha
    e especialização das vendedoras por região
    """
    if not data_fim:
        data_fim = data_inicio + timedelta(days=30)
    
    # Buscar condomínios ativos na campanha
    if campanha_id:
        campanha = list(db.campanha_visitas.find({"campanha_id": campanha_id, "ativo": True}))
    else:
        campanha = list(db.campanha_visitas.find({"ativo": True}))
    
    if not campanha:
        return []
    
    # Buscar vendedoras ativas
    vendedoras = list(db.vendedoras.find({"ativo": True}))
    
    if not vendedoras:
        return []
    
    # Calcular necessidade de visitas
    necessidade = {}
    for cond_campanha in campanha:
        freq = cond_campanha.get('frequencia_sugerida', 1)
        dias_periodo = (data_fim - data_inicio).days
        semanas = dias_periodo / 7
        visitas_necessarias = max(1, int(freq * semanas))
        
        agendados = db.visitas_vendedoras.count_documents({
            "condominio_id": cond_campanha["condominio_id"],
            "data": {"$gte": data_inicio.strftime("%Y-%m-%d"), "$lte": data_fim.strftime("%Y-%m-%d")},
            "status": {"$ne": "cancelado"}
        })
        
        necessidade[str(cond_campanha["condominio_id"])] = {
            "necessario": max(0, visitas_necessarias - agendados),
            "prioridade": cond_campanha.get("prioridade", "D"),
            "zona": cond_campanha.get("zona", "Zona Central"),
            "nome": cond_campanha["condominio_nome"],
            "bairro": cond_campanha.get("bairro", ""),
            "campanha_id": cond_campanha.get("campanha_id")
        }
    
    # Criar mapa de disponibilidade
    dias_disponiveis = {}
    for delta in range((data_fim - data_inicio).days + 1):
        data = data_inicio + timedelta(days=delta)
        dia_semana = data.weekday()
        
        if dia_semana == 6:  # Domingo
            continue
        
        dias_disponiveis[data.strftime("%Y-%m-%d")] = {
            "dia_semana": dia_semana,
            "data_obj": data,
            "eh_sabado": dia_semana == 5,
            "agendamentos": {vend["nome"]: 0 for vend in vendedoras}
        }
    
    # Contar agendamentos existentes
    agendamentos_existentes = list(db.visitas_vendedoras.find({
        "data": {"$gte": data_inicio.strftime("%Y-%m-%d"), "$lte": data_fim.strftime("%Y-%m-%d")},
        "status": {"$ne": "cancelado"}
    }))
    
    for ag in agendamentos_existentes:
        data_str = ag["data"]
        if data_str in dias_disponiveis and ag["vendedora"] in dias_disponiveis[data_str]["agendamentos"]:
            dias_disponiveis[data_str]["agendamentos"][ag["vendedora"]] += 1
    
    # Ordenar condomínios: prioridade > necessidade
    campanha_ordenada = sorted(
        necessidade.items(),
        key=lambda x: (-get_peso_prioridade(x[1]["prioridade"]), -x[1]["necessario"])
    )
    
    sugestoes = []
    estatisticas_especializacao = {
        "preferencial": 0,
        "disponivel": 0,
        "nao_preferencial": 0
    }
    
    for cond_id, nec in campanha_ordenada:
        if nec["necessario"] <= 0:
            continue
        
        # Ordenar dias disponíveis
        dias_ordenados = sorted(dias_disponiveis.items())
        
        for data_str, dia_info in dias_ordenados:
            dia_semana = dia_info["dia_semana"]
            
            # Ordenar vendedoras por especialização
            vendedoras_com_peso = []
            for vend in vendedoras:
                # Verificar disponibilidade no dia
                if dia_semana not in vend["disponibilidade"]:
                    continue
                
                # Verificar limite de visitas
                if dia_info["agendamentos"][vend["nome"]] >= vend.get("max_visitas_dia", 2):
                    continue
                
                # Calcular adequação para este condomínio
                adequacao = calcular_adequacao_vendedora_condominio(vend, nec["zona"])
                
                vendedoras_com_peso.append({
                    "vendedora": vend,
                    "peso": adequacao["peso"],
                    "nivel": adequacao["nivel"],
                    "motivo": adequacao["motivo"],
                    "visitas_hoje": dia_info["agendamentos"][vend["nome"]]
                })
            
            # Ordenar por peso (maior = mais adequada)
            vendedoras_com_peso.sort(key=lambda x: (-x["peso"], x["visitas_hoje"]))
            
            for vp in vendedoras_com_peso:
                vend = vp["vendedora"]
                
                # Verificar proximidade com outras visitas do mesmo dia
                visitas_do_dia = db.visitas_vendedoras.find({
                    "data": data_str,
                    "vendedora": vend["nome"],
                    "status": {"$ne": "cancelado"}
                })
                
                cond_obj = {"bairro": nec.get("bairro", "")}
                
                ja_tem_proxima = False
                for visita in visitas_do_dia:
                    cond_visitado = db.campanha_visitas.find_one({"condominio_id": visita["condominio_id"]})
                    if cond_visitado:
                        cond_visitado_obj = {"bairro": cond_visitado.get("bairro", "")}
                        if condominios_proximos(cond_obj, cond_visitado_obj):
                            ja_tem_proxima = True
                            break
                
                if ja_tem_proxima and dia_info["agendamentos"][vend["nome"]] > 0:
                    continue
                
                # Registrar estatística
                estatisticas_especializacao[vp["nivel"]] += 1
                
                # Criar sugestão
                sugestoes.append({
                    "condominio_id": cond_id,
                    "condominio_nome": nec["nome"],
                    "condominio_zona": nec["zona"],
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
                
                # Atualizar contadores
                dias_disponiveis[data_str]["agendamentos"][vend["nome"]] += 1
                necessidade[cond_id]["necessario"] -= 1
                break
            
            if necessidade[cond_id]["necessario"] <= 0:
                break
    
    return sugestoes

# ============================================================================
# AGENDA VISUAL POR VENDEDORA - CORRIGIDA
# ============================================================================

def agenda_visual_por_vendedora(db):
    """
    Exibe agenda em formato visual (tabela) com edição manual
    """
    st.markdown("### 📅 Agenda Visual por Vendedora")
    
    # Seleção do período
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
    
    with col_per2:
        vendedoras_ativas = list(db.vendedoras.find({"ativo": True}))
        vendedoras_opcoes = [v["nome"] for v in vendedoras_ativas]
        
        if not vendedoras_opcoes:
            st.warning("⚠️ Nenhuma vendedora ativa cadastrada.")
            return
        
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
    
    # Botões de ação
    col_btn1, col_btn2, col_btn3, col_btn4 = st.columns(4)
    
    with col_btn1:
        if st.button("📥 Carregar Agenda", use_container_width=True):
            st.rerun()
    
    with col_btn2:
        if st.button("🔃 Resetar para Sugestões", use_container_width=True):
            st.warning("⚠️ Isso irá substituir a agenda manual pelas sugestões automáticas.")
            if st.button("✅ Confirmar Reset", key="confirm_reset"):
                data_inicio = datetime(ano, mes, 1).date()
                data_fim = datetime(ano, mes, dias_no_mes).date()
                
                campanha_ativa = db.campanha_visitas.find_one({"ativo": True})
                campanha_id = campanha_ativa.get("campanha_id") if campanha_ativa else None
                
                sugestoes = agendamento_inteligente(db, data_inicio, data_fim, campanha_id)
                
                if sugestoes:
                    db.visitas_vendedoras.delete_many({
                        "data": {"$gte": data_inicio.strftime("%Y-%m-%d"), "$lte": data_fim.strftime("%Y-%m-%d")},
                        "manual": True
                    })
                    
                    for sug in sugestoes:
                        existente = db.visitas_vendedoras.find_one({
                            "data": sug["data"],
                            "vendedora": sug["vendedora"],
                            "condominio_id": ObjectId(sug["condominio_id"])
                        })
                        
                        if not existente:
                            nova_visita = {
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
                            }
                            db.visitas_vendedoras.insert_one(nova_visita)
                    
                    st.success(f"✅ Agenda resetada com sucesso! {len(sugestoes)} visitas geradas.")
                    st.rerun()
                else:
                    st.warning("Nenhuma sugestão gerada. Verifique a campanha ativa.")
    
    with col_btn3:
        if st.button("📊 Exportar Agenda Visual", use_container_width=True):
            exportar_agenda_visual(db, ano, mes, vendedoras_selecionadas)
    
    with col_btn4:
        if st.button("💾 Salvar Alterações", use_container_width=True, type="primary"):
            st.success("✅ Alterações salvas com sucesso!")
            st.rerun()
    
    st.markdown("---")
    
    # ============================================================
    # BUSCAR DADOS
    # ============================================================
    
    data_inicio_str = datetime(ano, mes, 1).strftime("%Y-%m-%d")
    data_fim_str = datetime(ano, mes, dias_no_mes).strftime("%Y-%m-%d")
    
    visitas_db = list(db.visitas_vendedoras.find({
        "data": {"$gte": data_inicio_str, "$lte": data_fim_str}
    }))
    
    # Criar estrutura de dados
    agenda_data = {}
    for dia in range(1, dias_no_mes + 1):
        data_obj = datetime(ano, mes, dia).date()
        data_str = data_obj.strftime("%Y-%m-%d")
        dia_semana = data_obj.weekday()
        
        agenda_data[data_str] = {
            "data": data_obj,
            "dia_semana": DIAS_SEMANA[dia_semana],
            "vendedoras": {v: [] for v in vendedoras_selecionadas},
            "feriado": False,
            "obs": ""
        }
    
    # Preencher com dados do banco
    for visita in visitas_db:
        data_str = visita["data"]
        vendedora = visita["vendedora"]
        
        if data_str in agenda_data and vendedora in agenda_data[data_str]["vendedoras"]:
            if visita.get("status") == "feriado":
                agenda_data[data_str]["feriado"] = True
                continue
            
            if mostrar_status and visita.get("status") not in mostrar_status:
                continue
            
            agenda_data[data_str]["vendedoras"][vendedora].append({
                "id": str(visita["_id"]),
                "condominio": visita["condominio_nome"],
                "status": visita.get("status", "agendado"),
                "periodo": visita.get("periodo", "M/T"),
                "observacao": visita.get("observacoes", ""),
                "manual": visita.get("manual", False)
            })
    
    # ============================================================
    # EXIBIR TABELA COM STREAMLIT (SEM JAVASCRIPT)
    # ============================================================
    
    st.markdown(f"### 📆 {calendar.month_name[mes]} {ano}")
    
    # Legenda
    col_leg1, col_leg2, col_leg3, col_leg4, col_leg5, col_leg6 = st.columns(6)
    with col_leg1:
        st.markdown("🟢 **Agendado**")
    with col_leg2:
        st.markdown("✅ **Concluído**")
    with col_leg3:
        st.markdown("🔴 **Cancelado**")
    with col_leg4:
        st.markdown("🌧️ **Chuva**")
    with col_leg5:
        st.markdown("⛔ **Falta**")
    with col_leg6:
        st.markdown("📌 **Feriado**")
    
    st.markdown("---")
    
    # CSS para a tabela
    st.markdown("""
    <style>
        .agenda-table {
            width: 100%;
            border-collapse: collapse;
            font-size: 13px;
        }
        .agenda-table th {
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
            padding: 10px;
            text-align: center;
            border: 1px solid #ddd;
            position: sticky;
            top: 0;
            z-index: 10;
        }
        .agenda-table td {
            padding: 6px;
            border: 1px solid #ddd;
            text-align: center;
            vertical-align: top;
            min-height: 50px;
        }
        .agenda-table .dia-util {
            background-color: #f9f9f9;
        }
        .agenda-table .sabado {
            background-color: #e8f4fd;
        }
        .agenda-table .domingo {
            background-color: #ffe6e6;
        }
        .agenda-table .feriado {
            background-color: #ffcccc;
        }
        .status-agendado { color: #28a745; font-weight: bold; }
        .status-concluido { color: #17a2b8; font-weight: bold; }
        .status-cancelado { color: #dc3545; font-weight: bold; }
        .status-chuva { color: #6c757d; font-style: italic; }
        .status-falta { color: #dc3545; font-style: italic; }
        .status-feriado { color: #ff6b6b; font-weight: bold; }
        .visita-manual { border-left: 3px solid #ff6b6b; padding-left: 5px; }
        .visita-auto { border-left: 3px solid #28a745; padding-left: 5px; }
        .periodo-m { background-color: #e3f2fd; border-radius: 3px; padding: 1px 5px; font-size: 11px; }
        .periodo-t { background-color: #fff3e0; border-radius: 3px; padding: 1px 5px; font-size: 11px; }
        .periodo-mt { background-color: #f3e5f5; border-radius: 3px; padding: 1px 5px; font-size: 11px; }
        .visita-item {
            margin-bottom: 4px;
            padding: 3px;
            border-radius: 4px;
            background-color: #f5f5f5;
        }
        .visita-item:hover {
            background-color: #e8e8e8;
        }
        .data-cell {
            font-weight: bold;
            font-size: 14px;
        }
        .data-cell small {
            font-weight: normal;
            font-size: 11px;
            color: #666;
        }
        .vazio {
            color: #999;
            font-size: 12px;
            padding: 5px;
        }
        .add-btn {
            background: #667eea;
            color: white;
            border: none;
            border-radius: 50%;
            width: 24px;
            height: 24px;
            font-size: 16px;
            cursor: pointer;
            display: inline-flex;
            align-items: center;
            justify-content: center;
        }
        .add-btn:hover {
            background: #764ba2;
        }
    </style>
    """, unsafe_allow_html=True)
    
    # Construir tabela
    html_table = '<table class="agenda-table">'
    
    # Cabeçalho
    html_table += '<tr><th style="min-width: 80px;">Data</th>'
    for vendedora in vendedoras_selecionadas:
        html_table += f'<th>{vendedora}</th>'
    html_table += '</tr>'
    
    # Linhas
    for data_str in sorted(agenda_data.keys()):
        data_info = agenda_data[data_str]
        data_obj = data_info["data"]
        dia_semana = data_obj.weekday()
        
        if dia_semana == 6:
            row_class = "domingo"
        elif dia_semana == 5:
            row_class = "sabado"
        else:
            row_class = "dia-util"
        
        if data_info.get("feriado"):
            row_class = "feriado"
        
        html_table += f'<tr class="{row_class}">'
        
        # Coluna da data
        data_formatada = data_obj.strftime("%d/%m")
        html_table += f'<td class="data-cell">{data_formatada}<br><small>{data_info["dia_semana"][:3]}</small></td>'
        
        # Colunas das vendedoras
        for vendedora in vendedoras_selecionadas:
            visitas = data_info["vendedoras"].get(vendedora, [])
            
            if data_info.get("feriado"):
                html_table += '<td class="status-feriado">🔴 FERIADO</td>'
                continue
            
            if not visitas:
                # Célula vazia com indicador visual
                html_table += f'''
                <td>
                    <div class="vazio">
                        <span style="font-size: 16px;">➕</span>
                        <br><small style="font-size: 9px;">Use o formulário abaixo</small>
                    </div>
                </td>
                '''
                continue
            
            # Construir conteúdo da célula com visitas
            cell_content = ""
            for visita in visitas:
                status_icons = {
                    "agendado": "🟢",
                    "concluido": "✅",
                    "cancelado": "🔴",
                    "chuva": "🌧️",
                    "falta": "⛔",
                    "feriado": "📌"
                }
                status_icon = status_icons.get(visita["status"], "🟢")
                status_class = f"status-{visita['status']}"
                
                periodo = visita.get("periodo", "M/T")
                periodo_class = "periodo-mt"
                if periodo == "M":
                    periodo_class = "periodo-m"
                elif periodo == "T":
                    periodo_class = "periodo-t"
                elif periodo == "M/T":
                    periodo_class = "periodo-mt"
                
                manual_class = "visita-manual" if visita.get("manual") else "visita-auto"
                
                cell_content += f'''
                <div class="visita-item {manual_class}">
                    <span class="{periodo_class}">{periodo}</span>
                    <strong>{visita['condominio']}</strong>
                    <span class="{status_class}">{status_icon}</span>
                    <br>
                    <span style="font-size: 10px; color: #666;">
                        {'' if visita.get('manual') else '🤖 '}
                    </span>
                </div>
                '''
            
            html_table += f'<td>{cell_content}</td>'
        
        html_table += '</tr>'
    
    html_table += '</table>'
    
    st.markdown(html_table, unsafe_allow_html=True)
    
    # ============================================================
    # EDITOR MANUAL DE VISITAS (FORMS STREAMLIT)
    # ============================================================
    
    st.markdown("---")
    st.markdown("### ✏️ Editor Manual de Visitas")
    st.info("💡 Selecione a data, vendedora e condomínio para adicionar ou editar uma visita.")
    
    with st.form("form_edicao_visita"):
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
                options=vendedoras_selecionadas if vendedoras_selecionadas else ["Selecione uma vendedora"],
                key="vendedora_edicao_form"
            )
        
        with col_ed3:
            condominio_edicao = st.text_input(
                "Condomínio",
                placeholder="Digite o nome do condomínio",
                key="condominio_edicao_form"
            )
        
        with col_ed4:
            periodo_edicao = st.selectbox(
                "Período",
                options=["M", "T", "M/T"],
                key="periodo_edicao_form"
            )
        
        col_ed5, col_ed6, col_ed7, col_ed8 = st.columns(4)
        
        with col_ed5:
            status_edicao = st.selectbox(
                "Status",
                options=["agendado", "concluido", "cancelado", "chuva", "falta", "feriado"],
                key="status_edicao_form",
                format_func=formatar_status_visita
            )
        
        with col_ed6:
            observacao_edicao = st.text_input(
                "Observação",
                placeholder="Ex: Chuva, falta, etc.",
                key="obs_edicao_form"
            )
        
        with col_ed7:
            submitted = st.form_submit_button("✅ Adicionar/Editar Visita", use_container_width=True, type="primary")
        
        with col_ed8:
            remover_submitted = st.form_submit_button("🗑️ Remover Visitas do Dia", use_container_width=True)
        
        if submitted:
            data_str = data_edicao.strftime("%Y-%m-%d")
            
            if status_edicao == "feriado":
                feriado_existente = db.visitas_vendedoras.find_one({
                    "data": data_str,
                    "status": "feriado"
                })
                
                if not feriado_existente:
                    nova_visita = {
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
                    }
                    db.visitas_vendedoras.insert_one(nova_visita)
                    st.success(f"✅ Feriado marcado para {data_edicao.strftime('%d/%m/%Y')}")
                else:
                    st.info(f"ℹ️ Feriado já marcado para {data_edicao.strftime('%d/%m/%Y')}")
                
                st.rerun()
                return
            
            if not condominio_edicao:
                st.error("⚠️ Digite o nome do condomínio!")
            else:
                existente = db.visitas_vendedoras.find_one({
                    "data": data_str,
                    "vendedora": vendedora_edicao,
                    "condominio_nome": condominio_edicao
                })
                
                if existente:
                    db.visitas_vendedoras.update_one(
                        {"_id": existente["_id"]},
                        {"$set": {
                            "status": status_edicao,
                            "periodo": periodo_edicao,
                            "observacoes": observacao_edicao,
                            "manual": True,
                            "ultima_edicao": datetime.now()
                        }}
                    )
                    st.success(f"✅ Visita atualizada: {condominio_edicao}")
                else:
                    visitas_dia = db.visitas_vendedoras.count_documents({
                        "data": data_str,
                        "vendedora": vendedora_edicao,
                        "status": {"$ne": "cancelado"}
                    })
                    
                    if visitas_dia >= 2:
                        st.warning(f"⚠️ {vendedora_edicao} já tem {visitas_dia} visitas neste dia. Limite é 2.")
                    else:
                        nova_visita = {
                            "condominio_id": None,
                            "condominio_nome": condominio_edicao,
                            "vendedora": vendedora_edicao,
                            "data": data_str,
                            "status": status_edicao,
                            "periodo": periodo_edicao,
                            "observacoes": observacao_edicao,
                            "criado_por": st.session_state.get("nome_usuario", "Manual"),
                            "data_criacao": datetime.now(),
                            "manual": True,
                            "zona": "Manual",
                            "adequacao": "manual"
                        }
                        db.visitas_vendedoras.insert_one(nova_visita)
                        st.success(f"✅ Visita adicionada: {condominio_edicao}")
                
                st.rerun()
        
        if remover_submitted:
            data_str = data_edicao.strftime("%Y-%m-%d")
            
            visitas_remover = list(db.visitas_vendedoras.find({
                "data": data_str,
                "vendedora": vendedora_edicao,
                "status": {"$ne": "feriado"}
            }))
            
            if visitas_remover:
                for vis in visitas_remover:
                    db.visitas_vendedoras.delete_one({"_id": vis["_id"]})
                st.success(f"✅ Removidas {len(visitas_remover)} visitas de {vendedora_edicao} em {data_edicao.strftime('%d/%m/%Y')}")
                st.rerun()
            else:
                st.warning("Nenhuma visita encontrada para este dia/vendedora.")

# ============================================================================
# FUNÇÃO PARA EXPORTAR AGENDA VISUAL
# ============================================================================

def exportar_agenda_visual(db, ano, mes, vendedoras_selecionadas):
    """
    Exporta a agenda visual para Excel
    """
    dias_no_mes = calendar.monthrange(ano, mes)[1]
    
    data_inicio_str = datetime(ano, mes, 1).strftime("%Y-%m-%d")
    data_fim_str = datetime(ano, mes, dias_no_mes).strftime("%Y-%m-%d")
    
    visitas = list(db.visitas_vendedoras.find({
        "data": {"$gte": data_inicio_str, "$lte": data_fim_str}
    }).sort("data", 1))
    
    # Criar DataFrame detalhado
    dados = []
    for visita in visitas:
        if visita["vendedora"] in vendedoras_selecionadas or visita["vendedora"] == "Sistema":
            data_obj = datetime.strptime(visita["data"], "%Y-%m-%d").date()
            dados.append({
                "Data": data_obj.strftime("%d/%m/%Y"),
                "Dia da Semana": DIAS_SEMANA[data_obj.weekday()],
                "Vendedora": visita["vendedora"],
                "Condomínio": visita["condominio_nome"],
                "Período": visita.get("periodo", "M/T"),
                "Status": formatar_status_visita(visita.get("status", "agendado")),
                "Observação": visita.get("observacoes", ""),
                "Manual": "Sim" if visita.get("manual") else "Não"
            })
    
    if dados:
        df_detalhado = pd.DataFrame(dados)
        
        # Pivot para formato visual
        pivot_data = []
        for visita in visitas:
            if visita["vendedora"] in vendedoras_selecionadas:
                data_obj = datetime.strptime(visita["data"], "%Y-%m-%d").date()
                periodo = visita.get("periodo", "M/T")
                status = visita.get("status", "agendado")
                status_emoji = {
                    "agendado": "🟢",
                    "concluido": "✅",
                    "cancelado": "🔴",
                    "chuva": "🌧️",
                    "falta": "⛔"
                }.get(status, "")
                
                texto = f"{periodo} {visita['condominio_nome']} {status_emoji}"
                pivot_data.append({
                    "Data": data_obj.strftime("%d/%m"),
                    "Dia": DIAS_SEMANA[data_obj.weekday()][:3],
                    "Vendedora": visita["vendedora"],
                    "Visita": texto
                })
        
        output = io.BytesIO()
        with pd.ExcelWriter(output, engine='openpyxl') as writer:
            df_detalhado.to_excel(writer, index=False, sheet_name='Agenda Detalhada')
            
            if pivot_data:
                df_pivot = pd.DataFrame(pivot_data)
                df_pivot = df_pivot.pivot_table(
                    index=["Data", "Dia"],
                    columns="Vendedora",
                    values="Visita",
                    aggfunc=lambda x: ' / '.join(x)
                ).reset_index()
                df_pivot.to_excel(writer, index=False, sheet_name='Agenda Visual')
            
            # Ajustar largura das colunas
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
                    adjusted_width = min(max_length + 2, 50)
                    worksheet.column_dimensions[column_letter].width = adjusted_width
        
        output.seek(0)
        
        st.download_button(
            label="📊 Baixar Agenda Visual",
            data=output.getvalue(),
            file_name=f"agenda_visual_{calendar.month_name[mes]}_{ano}.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )
    else:
        st.warning("Nenhum dado para exportar.")

# ============================================================================
# GESTÃO DE VENDEDORAS
# ============================================================================

def gerenciar_vendedoras(db):
    """Interface completa para gerenciar vendedoras com região preferencial"""
    st.markdown("### 👩‍💼 Gestão de Vendedoras")
    
    tab_lista, tab_nova, tab_editar, tab_historico = st.tabs([
        "📋 Lista de Vendedoras", 
        "➕ Nova Vendedora", 
        "✏️ Editar Vendedora",
        "📊 Histórico"
    ])
    
    with tab_lista:
        vendedoras = list(db.vendedoras.find({}))
        
        if vendedoras:
            # Filtros
            col_f1, col_f2 = st.columns(2)
            with col_f1:
                filtro_status = st.selectbox(
                    "Status",
                    ["Todas", "Ativas", "Inativas"],
                    key="filtro_vend_status"
                )
            with col_f2:
                filtro_tipo = st.selectbox(
                    "Tipo",
                    ["Todos", "fixa", "freelancer"],
                    key="filtro_vend_tipo"
                )
            
            # Aplicar filtros
            vendedoras_filtradas = vendedoras
            if filtro_status == "Ativas":
                vendedoras_filtradas = [v for v in vendedoras if v.get("ativo", True)]
            elif filtro_status == "Inativas":
                vendedoras_filtradas = [v for v in vendedoras if not v.get("ativo", True)]
            
            if filtro_tipo != "Todos":
                vendedoras_filtradas = [v for v in vendedoras_filtradas if v.get("tipo") == filtro_tipo]
            
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
                        dias_disponiveis = [DIAS_SEMANA[d] for d in vendedora.get('disponibilidade', [])]
                        st.write(f"**Dias disponíveis:** {', '.join(dias_disponiveis) if dias_disponiveis else 'Nenhum'}")
                    
                    with col3:
                        regiao_pref = vendedora.get('regiao_preferencial', 'Todas as regiões')
                        st.write(f"**📍 Região preferencial:** {regiao_pref}")
                        
                        if vendedora.get("data_desativacao"):
                            st.write(f"**Desativada em:** {vendedora['data_desativacao'].strftime('%d/%m/%Y')}")
                        if vendedora.get("motivo_desativacao"):
                            st.write(f"**Motivo:** {vendedora['motivo_desativacao']}")
                    
                    st.markdown("---")
                    st.markdown("**📊 Estatísticas de Performance:**")
                    
                    total_visitas = db.visitas_vendedoras.count_documents({"vendedora": vendedora["nome"]})
                    visitas_concluidas = db.visitas_vendedoras.count_documents({
                        "vendedora": vendedora["nome"],
                        "status": "concluido"
                    })
                    
                    col_e1, col_e2, col_e3 = st.columns(3)
                    with col_e1:
                        st.metric("Total Visitas", total_visitas)
                    with col_e2:
                        st.metric("✅ Concluídas", visitas_concluidas)
                    with col_e3:
                        taxa = (visitas_concluidas / total_visitas * 100) if total_visitas > 0 else 0
                        st.metric("Taxa de Sucesso", f"{taxa:.1f}%")
                    
                    # Próximas visitas
                    proximas = list(db.visitas_vendedoras.find({
                        "vendedora": vendedora["nome"],
                        "status": "agendado",
                        "data": {"$gte": datetime.now().strftime("%Y-%m-%d")}
                    }).sort("data", 1).limit(3))
                    
                    if proximas:
                        st.markdown("**📅 Próximas visitas:**")
                        for p in proximas:
                            st.caption(f"- {p['data']}: {p['condominio_nome']}")
        else:
            st.info("Nenhuma vendedora cadastrada.")
    
    with tab_nova:
        col1, col2 = st.columns(2)
        
        with col1:
            nome = st.text_input("Nome da Vendedora*", key="nova_vend_nome")
            tipo = st.selectbox("Tipo", ["fixa", "freelancer"], key="nova_vend_tipo")
            max_visitas = st.number_input("Máximo de visitas por dia", min_value=1, max_value=5, value=2, key="nova_vend_max")
        
        with col2:
            horario = st.text_input("Horário de trabalho", value="08:00-17:00", key="nova_vend_horario")
            regiao_preferencial = st.selectbox(
                "📍 Região Preferencial",
                options=REGIOES_DISPONIVEIS,
                index=len(REGIOES_DISPONIVEIS)-1,
                key="nova_vend_regiao",
                help="Selecione a região onde a vendedora tem mais facilidade de atuação"
            )
        
        st.markdown("**Dias disponíveis:**")
        col_dias = st.columns(7)
        dias_selecionados = []
        
        for i, dia in enumerate(DIAS_SEMANA[:6]):
            with col_dias[i]:
                if st.checkbox(dia, key=f"dia_nova_{nome}_{i}"):
                    dias_selecionados.append(i)
        
        if tipo == "freelancer":
            st.info("💡 Freelancers têm disponibilidade limitada. Selecione apenas os dias que podem trabalhar.")
        
        if st.button("✅ Cadastrar Vendedora", key="btn_cad_vend_nova"):
            if not nome:
                st.error("⚠️ Nome é obrigatório!")
            elif not dias_selecionados:
                st.error("⚠️ Selecione pelo menos um dia de trabalho!")
            else:
                if db.vendedoras.find_one({"nome": nome}):
                    st.error(f"❌ Vendedora '{nome}' já cadastrada!")
                else:
                    nova_vend = {
                        "nome": nome,
                        "tipo": tipo,
                        "disponibilidade": dias_selecionados,
                        "horario": horario,
                        "max_visitas_dia": max_visitas,
                        "regiao_preferencial": regiao_preferencial,
                        "ativo": True,
                        "data_cadastro": datetime.now(),
                        "data_desativacao": None,
                        "motivo_desativacao": None
                    }
                    db.vendedoras.insert_one(nova_vend)
                    st.success(f"✅ Vendedora '{nome}' cadastrada com sucesso!")
                    st.balloons()
                    st.rerun()
    
    with tab_editar:
        vendedoras_lista = list(db.vendedoras.find({}))
        if vendedoras_lista:
            vendedora_selecionada = st.selectbox(
                "Selecione a vendedora para editar",
                options=[v["nome"] for v in vendedoras_lista],
                key="select_vend_editar"
            )
            
            if vendedora_selecionada:
                vend = db.vendedoras.find_one({"nome": vendedora_selecionada})
                if vend:
                    col_edit1, col_edit2 = st.columns(2)
                    
                    with col_edit1:
                        novo_nome = st.text_input("Nome", value=vend["nome"], key="edit_vend_nome")
                        novo_tipo = st.selectbox("Tipo", ["fixa", "freelancer"], index=0 if vend["tipo"] == "fixa" else 1, key="edit_vend_tipo")
                        novo_max = st.number_input("Max visitas/dia", value=vend.get("max_visitas_dia", 2), key="edit_vend_max")
                    
                    with col_edit2:
                        novo_horario = st.text_input("Horário", value=vend.get("horario", "08:00-17:00"), key="edit_vend_horario")
                        nova_regiao = st.selectbox(
                            "Região Preferencial",
                            options=REGIOES_DISPONIVEIS,
                            index=REGIOES_DISPONIVEIS.index(vend.get("regiao_preferencial", "Todas as regiões")) if vend.get("regiao_preferencial", "Todas as regiões") in REGIOES_DISPONIVEIS else len(REGIOES_DISPONIVEIS)-1,
                            key="edit_vend_regiao"
                        )
                        novo_ativo = st.checkbox("Ativo", value=vend.get("ativo", True), key="edit_vend_ativo")
                    
                    # Campo para motivo de desativação
                    if not novo_ativo:
                        motivo = st.text_input(
                            "Motivo da desativação",
                            key="edit_vend_motivo",
                            placeholder="Ex: Saída da empresa, licença, etc."
                        )
                    
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
                        if st.button("💾 Salvar Alterações", key="btn_save_vend_edit"):
                            update_data = {
                                "nome": novo_nome,
                                "tipo": novo_tipo,
                                "max_visitas_dia": novo_max,
                                "horario": novo_horario,
                                "regiao_preferencial": nova_regiao,
                                "ativo": novo_ativo,
                                "disponibilidade": novos_dias
                            }
                            
                            # Se desativou, registrar data e motivo
                            if not novo_ativo and vend.get("ativo", True):
                                update_data["data_desativacao"] = datetime.now()
                                update_data["motivo_desativacao"] = motivo or "Desativado pelo admin"
                            elif novo_ativo and not vend.get("ativo", True):
                                update_data["data_desativacao"] = None
                                update_data["motivo_desativacao"] = None
                            
                            db.vendedoras.update_one(
                                {"_id": vend["_id"]},
                                {"$set": update_data}
                            )
                            st.success("✅ Alterações salvas!")
                            st.rerun()
                    
                    with col_btn_edit2:
                        if st.button("🗑️ Excluir Vendedora", key="btn_del_vend"):
                            tem_visitas = db.visitas_vendedoras.count_documents({"vendedora": vend["nome"]})
                            if tem_visitas > 0:
                                st.error(f"❌ Não é possível excluir. Vendedora tem {tem_visitas} visitas associadas.")
                                st.info("💡 Sugestão: Desative a vendedora em vez de excluir.")
                            else:
                                db.vendedoras.delete_one({"_id": vend["_id"]})
                                st.success("✅ Vendedora excluída!")
                                st.rerun()
        else:
            st.info("Nenhuma vendedora cadastrada para editar.")
    
    with tab_historico:
        st.markdown("#### 📊 Histórico de Vendedoras")
        
        # Estatísticas gerais
        total_vendedoras = db.vendedoras.count_documents({})
        ativas = db.vendedoras.count_documents({"ativo": True})
        inativas = db.vendedoras.count_documents({"ativo": False})
        
        col_h1, col_h2, col_h3 = st.columns(3)
        with col_h1:
            st.metric("Total de Vendedoras", total_vendedoras)
        with col_h2:
            st.metric("Ativas", ativas)
        with col_h3:
            st.metric("Inativas", inativas)
        
        # Lista de vendedoras inativas
        inativas_lista = list(db.vendedoras.find({"ativo": False}))
        if inativas_lista:
            st.markdown("**📋 Vendedoras Inativas:**")
            for vend in inativas_lista:
                with st.expander(f"🔴 {vend['nome']}"):
                    st.write(f"**Desativada em:** {vend.get('data_desativacao', 'N/A')}")
                    st.write(f"**Motivo:** {vend.get('motivo_desativacao', 'Não informado')}")
                    st.write(f"**Total de visitas:** {db.visitas_vendedoras.count_documents({'vendedora': vend['nome']})}")

# ============================================================================
# RELATÓRIOS COMPLETOS
# ============================================================================

def relatorios_completos(db):
    """Interface completa de relatórios"""
    st.markdown("### 📊 Relatórios de Visitas")
    
    tipo_relatorio = st.selectbox(
        "Tipo de Relatório",
        ["Resumo da Campanha Atual", "Visitas por Vendedora", "Visitas por Condomínio", 
         "Distribuição por Zona", "Exportar Agenda", "Comparativo de Campanhas"]
    )
    
    if tipo_relatorio == "Resumo da Campanha Atual":
        campanha_ativa = list(db.campanha_visitas.find({"ativo": True}))
        
        if campanha_ativa:
            # Buscar informações da campanha no histórico
            campanha_id = campanha_ativa[0].get("campanha_id") if campanha_ativa else None
            campanha_historico = None
            if campanha_id:
                campanha_historico = db.campanhas_historico.find_one({"campanha_id": campanha_id})
            
            col_r1, col_r2, col_r3 = st.columns(3)
            
            with col_r1:
                st.metric("Condomínios na Campanha", len(campanha_ativa))
                if campanha_historico:
                    st.caption(f"Versão: #{campanha_historico.get('versao', 'N/A')}")
            
            with col_r2:
                total_aptos = sum(c.get("aptos", 0) for c in campanha_ativa)
                st.metric("Total de Apartamentos", f"{total_aptos:,}")
            
            with col_r3:
                visitas_concluidas = db.visitas_vendedoras.count_documents({"status": "concluido"})
                st.metric("Visitas Concluídas (Total)", visitas_concluidas)
            
            # Progresso por condomínio
            st.markdown("#### 📈 Progresso por Condomínio")
            
            dados_progresso = []
            for cond in campanha_ativa:
                total_visitas = db.visitas_vendedoras.count_documents({
                    "condominio_id": cond["condominio_id"]
                })
                visitas_concluidas_cond = db.visitas_vendedoras.count_documents({
                    "condominio_id": cond["condominio_id"],
                    "status": "concluido"
                })
                
                dados_progresso.append({
                    "Condomínio": cond["condominio_nome"][:35],
                    "Zona": cond.get("zona", "N/D"),
                    "Total Visitas": total_visitas,
                    "Concluídas": visitas_concluidas_cond,
                    "Progresso": f"{(visitas_concluidas_cond/total_visitas*100):.0f}%" if total_visitas > 0 else "0%"
                })
            
            df_progresso = pd.DataFrame(dados_progresso)
            st.dataframe(df_progresso, use_container_width=True, hide_index=True)
        else:
            st.info("Nenhuma campanha ativa.")
    
    elif tipo_relatorio == "Visitas por Vendedora":
        # Incluir vendedoras inativas nos relatórios
        vendedoras_opcoes = [v["nome"] for v in db.vendedoras.find({})]
        if vendedoras_opcoes:
            vendedora_sel = st.selectbox("Vendedora", options=vendedoras_opcoes)
            
            if vendedora_sel:
                visitas_vend = list(db.visitas_vendedoras.find({
                    "vendedora": vendedora_sel,
                    "status": {"$ne": "cancelado"}
                }).sort("data", -1))
                
                if visitas_vend:
                    dados = []
                    for vis in visitas_vend:
                        dados.append({
                            "Data": datetime.strptime(vis["data"], "%Y-%m-%d").strftime("%d/%m/%Y"),
                            "Condomínio": vis["condominio_nome"],
                            "Zona": vis.get("zona", "N/D"),
                            "Status": formatar_status_visita(vis["status"])
                        })
                    
                    df = pd.DataFrame(dados)
                    st.dataframe(df, use_container_width=True, hide_index=True)
                    
                    total = len(visitas_vend)
                    concluidos = len([v for v in visitas_vend if v["status"] == "concluido"])
                    
                    col_e1, col_e2, col_e3 = st.columns(3)
                    with col_e1:
                        st.metric("Total de Visitas", total)
                    with col_e2:
                        st.metric("Concluídas", concluidos)
                    with col_e3:
                        st.metric("Taxa de Conclusão", f"{(concluidos/total*100):.1f}%" if total > 0 else "0%")
                else:
                    st.info("Nenhuma visita encontrada.")
        else:
            st.warning("Nenhuma vendedora cadastrada.")
    
    elif tipo_relatorio == "Distribuição por Zona":
        campanha = list(db.campanha_visitas.find({"ativo": True}))
        
        if campanha:
            # Distribuição dos condomínios por zona
            zona_counts = defaultdict(int)
            for cond in campanha:
                zona = cond.get("zona", "Não definida")
                zona_counts[zona] += 1
            
            st.markdown("#### 📍 Distribuição dos Condomínios por Zona")
            
            for zona, count in sorted(zona_counts.items()):
                st.progress(count / len(campanha), text=f"{zona}: {count} condomínios ({count/len(campanha)*100:.1f}%)")
            
            # Distribuição das visitas por zona
            st.markdown("#### 📊 Distribuição das Visitas por Zona")
            
            visitas = list(db.visitas_vendedoras.find({"status": {"$ne": "cancelado"}}))
            visitas_por_zona = defaultdict(int)
            
            for visita in visitas:
                zona = visita.get("zona", "Não definida")
                visitas_por_zona[zona] += 1
            
            if visitas:
                for zona, count in sorted(visitas_por_zona.items()):
                    st.progress(count / len(visitas), text=f"{zona}: {count} visitas ({count/len(visitas)*100:.1f}%)")
            else:
                st.info("Nenhuma visita registrada ainda.")
        else:
            st.info("Nenhuma campanha ativa.")
    
    elif tipo_relatorio == "Comparativo de Campanhas":
        st.markdown("#### 📊 Comparativo entre Campanhas")
        
        # Buscar todas as campanhas
        campanhas = list(db.campanhas_historico.find().sort("versao", -1))
        
        if len(campanhas) < 2:
            st.info("Precisa de pelo menos 2 campanhas para comparar.")
        else:
            # Selecionar campanhas para comparar
            opcoes = [f"#{c['versao']} - {c.get('nome', 'Sem nome')} ({c['data_criacao'].strftime('%d/%m/%Y')})" for c in campanhas]
            
            col_comp1, col_comp2 = st.columns(2)
            with col_comp1:
                camp1_idx = st.selectbox("Campanha 1", options=range(len(opcoes)), format_func=lambda x: opcoes[x], key="comp1")
            with col_comp2:
                camp2_idx = st.selectbox("Campanha 2", options=range(len(opcoes)), format_func=lambda x: opcoes[x], key="comp2")
            
            if camp1_idx != camp2_idx:
                camp1 = campanhas[camp1_idx]
                camp2 = campanhas[camp2_idx]
                
                # Métricas comparativas
                col_m1, col_m2, col_m3, col_m4 = st.columns(4)
                
                with col_m1:
                    st.metric(
                        "Condomínios",
                        f"{camp1['total_condominios']} → {camp2['total_condominios']}",
                        delta=camp2['total_condominios'] - camp1['total_condominios']
                    )
                
                with col_m2:
                    # Contar visitas de cada campanha
                    vis1 = db.visitas_vendedoras.count_documents({"campanha_id": camp1.get("campanha_id")})
                    vis2 = db.visitas_vendedoras.count_documents({"campanha_id": camp2.get("campanha_id")})
                    st.metric(
                        "Total Visitas",
                        f"{vis1} → {vis2}",
                        delta=vis2 - vis1
                    )
                
                with col_m3:
                    # Visitas concluídas
                    conc1 = db.visitas_vendedoras.count_documents({
                        "campanha_id": camp1.get("campanha_id"),
                        "status": "concluido"
                    })
                    conc2 = db.visitas_vendedoras.count_documents({
                        "campanha_id": camp2.get("campanha_id"),
                        "status": "concluido"
                    })
                    taxa1 = (conc1 / vis1 * 100) if vis1 > 0 else 0
                    taxa2 = (conc2 / vis2 * 100) if vis2 > 0 else 0
                    st.metric(
                        "Taxa de Conclusão",
                        f"{taxa1:.1f}% → {taxa2:.1f}%",
                        delta=f"{taxa2 - taxa1:.1f}%"
                    )
                
                with col_m4:
                    # Dias de campanha
                    dias1 = (camp1['data_fim'] - camp1['data_inicio']).days
                    dias2 = (camp2['data_fim'] - camp2['data_inicio']).days
                    st.metric(
                        "Duração",
                        f"{dias1} → {dias2} dias",
                        delta=dias2 - dias1
                    )
                
                # Detalhes das campanhas
                st.markdown("---")
                col_det1, col_det2 = st.columns(2)
                
                with col_det1:
                    st.markdown(f"**📋 Campanha #{camp1['versao']}**")
                    st.write(f"Nome: {camp1.get('nome', 'Sem nome')}")
                    st.write(f"Período: {camp1['data_inicio'].strftime('%d/%m/%Y')} a {camp1['data_fim'].strftime('%d/%m/%Y')}")
                    st.write(f"Condomínios: {camp1['total_condominios']}")
                    st.write(f"Visitas: {vis1} agendadas, {conc1} concluídas")
                
                with col_det2:
                    st.markdown(f"**📋 Campanha #{camp2['versao']}**")
                    st.write(f"Nome: {camp2.get('nome', 'Sem nome')}")
                    st.write(f"Período: {camp2['data_inicio'].strftime('%d/%m/%Y')} a {camp2['data_fim'].strftime('%d/%m/%Y')}")
                    st.write(f"Condomínios: {camp2['total_condominios']}")
                    st.write(f"Visitas: {vis2} agendadas, {conc2} concluídas")
    
    elif tipo_relatorio == "Exportar Agenda":
        data_export_inicio = st.date_input("Data Início", value=datetime.now().date())
        data_export_fim = st.date_input("Data Fim", value=datetime.now().date() + timedelta(days=30))
        
        # Opção de incluir histórico
        incluir_historico = st.checkbox("Incluir todas as campanhas (histórico)")
        
        if st.button("📥 Exportar para Excel", key="btn_exportar"):
            query = {
                "data": {"$gte": data_export_inicio.strftime("%Y-%m-%d"), "$lte": data_export_fim.strftime("%Y-%m-%d")}
            }
            
            if not incluir_historico:
                query["status"] = {"$ne": "cancelado"}
            
            visitas_export = list(db.visitas_vendedoras.find(query).sort("data", 1))
            
            if visitas_export:
                dados_export = []
                for vis in visitas_export:
                    data_obj = datetime.strptime(vis["data"], "%Y-%m-%d")
                    
                    # Buscar campanha
                    campanha_nome = "N/A"
                    if vis.get("campanha_id"):
                        campanha = db.campanhas_historico.find_one({"campanha_id": vis["campanha_id"]})
                        if campanha:
                            campanha_nome = f"#{campanha['versao']} - {campanha.get('nome', '')}"
                    
                    dados_export.append({
                        "Data": data_obj.strftime("%d/%m/%Y"),
                        "Dia da Semana": DIAS_SEMANA[data_obj.weekday()],
                        "Condomínio": vis["condominio_nome"],
                        "Zona": vis.get("zona", "N/D"),
                        "Vendedora": vis["vendedora"],
                        "Status": formatar_status_visita(vis.get("status", "agendado")),
                        "Campanha": campanha_nome,
                        "Observações": vis.get("observacoes", "")
                    })
                
                df_export = pd.DataFrame(dados_export)
                
                output = io.BytesIO()
                with pd.ExcelWriter(output, engine='openpyxl') as writer:
                    df_export.to_excel(writer, index=False, sheet_name='Agenda Visitas')
                    
                    worksheet = writer.sheets['Agenda Visitas']
                    for column in worksheet.columns:
                        max_length = 0
                        column_letter = column[0].column_letter
                        for cell in column:
                            try:
                                if len(str(cell.value)) > max_length:
                                    max_length = len(str(cell.value))
                            except:
                                pass
                        adjusted_width = min(max_length + 2, 50)
                        worksheet.column_dimensions[column_letter].width = adjusted_width
                
                output.seek(0)
                
                st.download_button(
                    label="📊 Baixar Excel",
                    data=output.getvalue(),
                    file_name=f"visitas_vendedoras_{data_export_inicio.strftime('%Y%m%d')}_{data_export_fim.strftime('%Y%m%d')}.xlsx",
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                )
            else:
                st.warning("Nenhuma visita no período selecionado.")

# ============================================================================
# HISTÓRICO DE CAMPANHAS
# ============================================================================

def historico_campanhas(db):
    """Exibe o histórico completo de campanhas"""
    st.markdown("### 📚 Histórico Completo de Campanhas")
    
    # Estatísticas gerais
    total_campanhas = db.campanhas_historico.count_documents({})
    total_visitas = db.visitas_vendedoras.count_documents({})
    
    col_h1, col_h2, col_h3 = st.columns(3)
    with col_h1:
        st.metric("Total de Campanhas", total_campanhas)
    with col_h2:
        st.metric("Total de Visitas", total_visitas)
    with col_h3:
        tamanho_mb = verificar_espaco_mongo(db)
        st.metric("Espaço MongoDB", f"{tamanho_mb:.2f} MB")
    
    # Lista de campanhas
    campanhas = list(db.campanhas_historico.find().sort("versao", -1))
    
    if campanhas:
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
                    # Contar visitas desta campanha
                    visitas_camp = db.visitas_vendedoras.count_documents({
                        "campanha_id": camp.get("campanha_id")
                    })
                    concluidas_camp = db.visitas_vendedoras.count_documents({
                        "campanha_id": camp.get("campanha_id"),
                        "status": "concluido"
                    })
                    st.metric("Visitas", visitas_camp)
                    st.metric("Concluídas", concluidas_camp)
                
                # Lista de condomínios
                with st.expander("📋 Ver condomínios desta campanha"):
                    for cond in camp.get('condominios', []):
                        st.write(f"- {cond.get('condominio_nome')} ({cond.get('zona')}) - Prioridade: {cond.get('prioridade')}")
    else:
        st.info("Nenhuma campanha no histórico. Crie sua primeira campanha!")

# ============================================================================
# VISÃO DO ADMIN (ATUALIZADA COM HISTÓRICO E AGENDA VISUAL)
# ============================================================================

def tela_admin_visitas(db, perfil_usuario, nome_usuario):
    """Interface completa para admin/diretoria/supervisores com histórico e agenda visual"""
    
    st.markdown("## 📅 Gerenciamento de Visitas de Vendedoras")
    
    # Abas principais
    tab_campanha, tab_agenda, tab_agenda_visual, tab_vendedoras, tab_relatorios, tab_historico = st.tabs([
        "🎯 Campanha", 
        "📆 Agenda", 
        "📊 Agenda Visual",
        "👩‍💼 Vendedoras", 
        "📊 Relatórios",
        "📚 Histórico"
    ])
    
    with tab_campanha:
        from modules.condominios import get_condominios_collection
        clientes_collection = get_condominios_collection()
        selecionar_condominios_campanha(db, clientes_collection)
    
    with tab_agenda:
        col_f1, col_f2, col_f3, col_f4, col_f5 = st.columns(5)
        
        with col_f1:
            filtro_vendedora = st.selectbox(
                "👩‍💼 Vendedora",
                options=["Todas"] + [v["nome"] for v in db.vendedoras.find({"ativo": True})],
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
            # Selecionar campanha específica
            campanhas = list(db.campanhas_historico.find().sort("versao", -1).limit(10))
            campanha_options = ["Última ativa"] + [f"#{c['versao']} - {c.get('nome', 'Sem nome')}" for c in campanhas]
            campanha_selecionada = st.selectbox(
                "Campanha",
                options=campanha_options,
                key="campanha_agenda"
            )
            
            campanha_id = None
            if campanha_selecionada != "Última ativa" and campanhas:
                idx = campanha_options.index(campanha_selecionada) - 1
                if idx < len(campanhas):
                    campanha_id = campanhas[idx].get("campanha_id")
        
        # Botão para gerar agenda
        col_btn1, col_btn2 = st.columns([1, 3])
        with col_btn1:
            if st.button("🤖 Gerar Agenda Inteligente", key="btn_auto_agendar", use_container_width=True):
                with st.spinner("Gerando sugestões com especialização geográfica..."):
                    campanha_count = db.campanha_visitas.count_documents({"ativo": True})
                    
                    if campanha_count == 0:
                        st.error("❌ Nenhum condomínio selecionado na campanha!")
                    else:
                        sugestoes = agendamento_inteligente(db, data_inicio, data_fim, campanha_id)
                        
                        if sugestoes:
                            st.success(f"✅ Geradas {len(sugestoes)} sugestões!")
                            
                            for sug in sugestoes[:10]:
                                icone = "⭐" if sug["adequacao"] == "preferencial" else "✓" if sug["adequacao"] == "disponivel" else "⚠️"
                                
                                with st.expander(f"{icone} {sug['condominio_nome']} ({sug['condominio_zona']}) - {sug['data']} - {sug['vendedora']}"):
                                    st.write(f"**Prioridade:** {sug['prioridade']}")
                                    st.write(f"**Zona:** {sug['condominio_zona']}")
                                    st.write(f"**Adequação:** {sug['vendedora_motivo']}")
                                    
                                    if st.button(f"✅ Confirmar", key=f"confirm_{sug['condominio_id']}_{sug['data']}_{sug['vendedora']}"):
                                        # Verificar se já existe
                                        existente = db.visitas_vendedoras.find_one({
                                            "data": sug["data"],
                                            "vendedora": sug["vendedora"],
                                            "condominio_id": ObjectId(sug["condominio_id"])
                                        })
                                        
                                        if not existente:
                                            nova_visita = {
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
                                            }
                                            db.visitas_vendedoras.insert_one(nova_visita)
                                            st.success("✅ Visita agendada!")
                                            st.rerun()
                                        else:
                                            st.warning("⚠️ Visita já existe para este dia/vendedora/condomínio.")
                        else:
                            st.info("Nenhuma sugestão gerada.")
        
        with col_btn2:
            if st.button("🔄 Atualizar", key="btn_atualizar_agenda", use_container_width=True):
                st.rerun()
        
        st.markdown("---")
        
        # Buscar visitas
        query = {}
        if filtro_vendedora != "Todas":
            query["vendedora"] = filtro_vendedora
        if filtro_status != "Todos":
            query["status"] = filtro_status
        if campanha_id:
            query["campanha_id"] = campanha_id
        
        query["data"] = {"$gte": data_inicio.strftime("%Y-%m-%d"), "$lte": data_fim.strftime("%Y-%m-%d")}
        
        visitas = list(db.visitas_vendedoras.find(query).sort("data", 1))
        
        if visitas:
            st.markdown(f"### 📋 Visitas Agendadas ({len(visitas)})")
            
            for visita in visitas:
                data_obj = datetime.strptime(visita["data"], "%Y-%m-%d").date()
                status_icon = {
                    "agendado": "🟢",
                    "concluido": "✅",
                    "cancelado": "🔴",
                    "chuva": "🌧️",
                    "falta": "⛔",
                    "feriado": "📌"
                }.get(visita["status"], "⏳")
                
                with st.expander(f"{status_icon} {data_obj.strftime('%d/%m/%Y')} - {visita['condominio_nome']} - {visita['vendedora']}", expanded=False):
                    col1, col2 = st.columns(2)
                    
                    with col1:
                        st.write(f"**Status:** {formatar_status_visita(visita['status'])}")
                        if visita.get("zona"):
                            st.write(f"**Zona:** {visita['zona']}")
                        if visita.get("observacoes"):
                            st.write(f"**Observações:** {visita['observacoes']}")
                        if visita.get("campanha_id"):
                            campanha = db.campanhas_historico.find_one({"campanha_id": visita["campanha_id"]})
                            if campanha:
                                st.write(f"**Campanha:** #{campanha['versao']} - {campanha.get('nome', '')}")
                        if visita.get("manual"):
                            st.write("**📝 Edição manual**")
                    
                    with col2:
                        if visita["status"] == "agendado":
                            obs = st.text_area("Observações da visita", key=f"obs_{visita['_id']}")
                            
                            if st.button("✅ Concluir", key=f"conc_{visita['_id']}"):
                                db.visitas_vendedoras.update_one(
                                    {"_id": visita["_id"]},
                                    {"$set": {
                                        "status": "concluido",
                                        "data_conclusao": datetime.now(),
                                        "observacoes": obs
                                    }}
                                )
                                st.success("✅ Visita concluída!")
                                st.rerun()
                            
                            if perfil_usuario in ["admin", "diretoria"]:
                                motivo = st.text_input("Motivo do cancelamento", key=f"motivo_{visita['_id']}")
                                if motivo and st.button("❌ Cancelar", key=f"cancel_{visita['_id']}"):
                                    db.visitas_vendedoras.update_one(
                                        {"_id": visita["_id"]},
                                        {"$set": {
                                            "status": "cancelado",
                                            "motivo_cancelamento": motivo,
                                            "data_cancelamento": datetime.now()
                                        }}
                                    )
                                    st.success("❌ Visita cancelada!")
                                    st.rerun()
        else:
            st.info("Nenhuma visita agendada no período.")
    
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
    """
    Função principal que integra o módulo ao sistema
    """
    # Inicializar coleções
    db = init_colecoes_visitas(clientes_collection)
    
    # Verificar perfil do usuário
    perfil = st.session_state.get("perfil", "admin")
    nome_usuario = st.session_state.get("nome_usuario", "")
    
    # Título
    st.markdown("""
    <div style='background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); padding: 1rem; border-radius: 10px; margin-bottom: 2rem;'>
        <h2 style='color: white; margin: 0;'>👩‍💼 Gestão de Visitas de Vendedoras</h2>
        <p style='color: white; margin: 0.5rem 0 0 0; opacity: 0.9;'>
            Agendamento inteligente com especialização por região, histórico completo e agenda visual
        </p>
    </div>
    """, unsafe_allow_html=True)
    
    # Verificar permissões
    if perfil in ["admin", "diretoria", "supervisao_n1", "supervisao_n2", "supervisao_n3", "atendente_n1", "recepcao"]:
        tela_admin_visitas(db, perfil, nome_usuario)
    elif perfil == "vendedora":
        # Visão simplificada para vendedoras
        st.info("👩‍💼 Visão para vendedoras em desenvolvimento...")
    else:
        st.error("❌ Você não tem permissão para acessar este módulo.")
