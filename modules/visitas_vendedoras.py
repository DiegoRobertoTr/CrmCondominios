# modules/visitas_vendedoras.py
"""
Módulo de Gerenciamento de Visitas de Vendedoras
- Integrado com cadastro de condomínios existente
- Seleção de condomínios para campanha (28 condomínios por 3-4 meses)
- Agendamento inteligente com regras de negócio
"""

import streamlit as st
import pandas as pd
from datetime import datetime, timedelta, date
from collections import defaultdict
import io
from bson.objectid import ObjectId
from typing import Dict, List, Tuple, Optional
import calendar

# Importar módulo de condomínios existente
try:
    from modules.condominios import get_condominios_collection, get_all_condominios
except ImportError:
    st.warning("Módulo de condomínios não encontrado. Algumas funcionalidades podem ser limitadas.")
    def get_all_condominios():
        return []
    def get_condominios_collection():
        return None

# ============================================================================
# CONFIGURAÇÕES INICIAIS
# ============================================================================

DIAS_SEMANA = ['Segunda', 'Terça', 'Quarta', 'Quinta', 'Sexta', 'Sábado', 'Domingo']

# Configuração padrão de disponibilidade das vendedoras
DISPONIBILIDADE_PADRAO = {
    "Kessia": {
        "dias": [0, 1, 2, 3, 4],
        "horario": "08:00-17:00",
        "max_visitas_dia": 2,
        "tipo": "fixa"
    },
    "Larissa": {
        "dias": [0, 1, 2, 3, 4],
        "horario": "08:00-17:00",
        "max_visitas_dia": 2,
        "tipo": "fixa"
    },
    "Estephanie": {
        "dias": [0, 1, 2, 3, 4],
        "horario": "08:00-17:00",
        "max_visitas_dia": 2,
        "tipo": "fixa"
    },
    "Juliana": {
        "dias": [2, 4],  # Quarta e Sexta apenas
        "horario": "08:00-17:00",
        "max_visitas_dia": 2,
        "tipo": "freelancer"
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
    
    # Mesmo bairro
    if bairro1 == bairro2:
        return True
    
    # Bairros próximos (expansível)
    proximidades = {
        "BARRA": ["BARRA DA TIJUCA", "JARDIM OCEÂNICO", "RECREIO"],
        "JACAREPAGUA": ["CURICICA", "TAQUARA", "FREGUEZIA"],
        "CENTRO": ["CIDADE NOVA", "SAÚDE", "GAMBOA"],
        "TIJUCA": ["ANDARAÍ", "GRAJAÚ", "VILA ISABEL"]
    }
    
    for principal, proximos in proximidades.items():
        if bairro1 == principal and bairro2 in proximos:
            return True
        if bairro2 == principal and bairro1 in proximos:
            return True
    
    return False

# ============================================================================
# INICIALIZAÇÃO
# ============================================================================

def init_colecoes_visitas(clientes_collection):
    """Inicializa as coleções necessárias para o módulo"""
    db = clientes_collection.database
    
    # Coleção para dados específicos de visitas (não substitui a original)
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
                    "ativo": True,
                    "data_cadastro": datetime.now()
                })
    
    # Coleção de visitas agendadas
    if 'visitas_vendedoras' not in db.list_collection_names():
        db.create_collection('visitas_vendedoras')
        db.visitas_vendedoras.create_index([("data", 1), ("vendedora", 1)])
        db.visitas_vendedoras.create_index([("condominio_id", 1), ("data", 1)])
        db.visitas_vendedoras.create_index("status")
    
    return db

# ============================================================================
# SELEÇÃO DE CONDOMÍNIOS PARA CAMPANHA
# ============================================================================

def selecionar_condominios_campanha(db, clientes_collection):
    """
    Interface para selecionar quais condomínios participarão da campanha de visitas
    Permite selecionar um subconjunto (ex: 28 condomínios) por período definido
    """
    st.markdown("### 🎯 Seleção de Condomínios para Campanha de Visitas")
    
    # Buscar condomínios do cadastro principal
    condominios_cadastro = get_all_condominios()
    
    if not condominios_cadastro:
        st.warning("⚠️ Nenhum condomínio cadastrado no sistema. Cadastre condomínios primeiro.")
        return
    
    # Buscar condomínios já selecionados para campanha
    campanha_ativa = list(db.campanha_visitas.find({}))
    cond_selecionados_ids = {str(c["condominio_id"]) for c in campanha_ativa}
    
    # Informações da campanha atual
    st.info(f"📊 **Total de condomínios disponíveis:** {len(condominios_cadastro)}")
    
    if campanha_ativa:
        data_inicio_campanha = min(c.get("data_inicio", datetime.now()) for c in campanha_ativa)
        data_fim_campanha = max(c.get("data_fim", datetime.now()) for c in campanha_ativa)
        st.info(f"📅 **Campanha atual:** de {data_inicio_campanha.strftime('%d/%m/%Y')} até {data_fim_campanha.strftime('%d/%m/%Y')}")
    
    # Preparar dados para seleção
    dados_selecao = []
    for cond in condominios_cadastro:
        # Calcular prioridade baseada em aptos (se tiver)
        aptos = cond.get("apartamentos", 0) or cond.get("aptos", 0) or 0
        prioridade = get_prioridade_condominio(aptos)
        
        # Verificar se já está na campanha
        campanha = db.campanha_visitas.find_one({"condominio_id": cond["_id"]})
        
        dados_selecao.append({
            "Selecionar": campanha is not None,
            "Condomínio": cond["nome"],
            "Bairro": cond.get("bairro", "N/I"),
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
    
    # Botões de ação
    col_b1, col_b2, col_b3, col_b4 = st.columns(4)
    
    with col_b1:
        if st.button("💾 Salvar Seleção", use_container_width=True, type="primary"):
            selecionados = edited_df[edited_df["Selecionar"] == True]
            
            if len(selecionados) == 0:
                st.warning("⚠️ Selecione pelo menos um condomínio!")
            else:
                # Limpar campanha atual
                db.campanha_visitas.delete_many({})
                
                # Inserir novos selecionados
                for _, row in selecionados.iterrows():
                    cond_id = ObjectId(row["ID"])
                    
                    # Buscar dados completos do condomínio
                    cond_original = None
                    for c in condominios_cadastro:
                        if str(c["_id"]) == row["ID"]:
                            cond_original = c
                            break
                    
                    if cond_original:
                        aptos = cond_original.get("apartamentos", 0) or cond_original.get("aptos", 0) or 0
                        
                        db.campanha_visitas.insert_one({
                            "condominio_id": cond_id,
                            "condominio_nome": row["Condomínio"],
                            "bairro": row["Bairro"],
                            "aptos": aptos,
                            "prioridade": row["Prioridade"],
                            "frequencia_sugerida": row["Visitas/Semana"],
                            "data_inicio": datetime.combine(data_inicio, datetime.min.time()),
                            "data_fim": datetime.combine(data_fim, datetime.min.time()),
                            "ativo": True,
                            "data_cadastro": datetime.now()
                        })
                
                st.success(f"✅ Campanha salva! {len(selecionados)} condomínios selecionados.")
                st.balloons()
                st.rerun()
    
    with col_b2:
        # Seleção inteligente: sugerir os 28 melhores
        if st.button("🤖 Seleção Inteligente", use_container_width=True):
            # Ordenar por prioridade e aptos, pegar top 28
            df_temp = edited_df.copy()
            df_temp['Peso'] = df_temp['Prioridade'].apply(lambda x: get_peso_prioridade(x))
            df_temp = df_temp.sort_values(['Peso', 'Aptos'], ascending=[False, False])
            
            # Selecionar top 28
            indices_selecionados = df_temp.head(28).index
            edited_df.loc[indices_selecionados, 'Selecionar'] = True
            
            st.success("✅ Seleção inteligente concluída! Revise e salve.")
            st.rerun()
    
    with col_b3:
        # Selecionar por prioridade mínima
        prioridade_min = st.selectbox(
            "Prioridade mínima",
            ["A+", "A", "B", "C", "D"],
            key="prioridade_min_filter"
        )
        
        if st.button("⭐ Selecionar por Prioridade", use_container_width=True):
            pesos = {"A+": 5, "A": 4, "B": 3, "C": 2, "D": 1}
            peso_min = pesos.get(prioridade_min, 0)
            
            df_temp = edited_df.copy()
            df_temp['Peso'] = df_temp['Prioridade'].apply(lambda x: get_peso_prioridade(x))
            df_temp = df_temp[df_temp['Peso'] >= peso_min]
            
            edited_df.loc[df_temp.index, 'Selecionar'] = True
            st.rerun()
    
    with col_b4:
        if st.button("🗑️ Limpar Seleção", use_container_width=True):
            edited_df['Selecionar'] = False
            st.rerun()
    
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
            # Orçamento de visitas para o período
            dias_campanha = (data_fim - data_inicio).days
            semanas = dias_campanha / 7
            total_visitas = int(visitas_semana * semanas)
            st.metric("Total de Visitas (período)", f"{total_visitas:,}")
        
        # Detalhamento por prioridade
        st.markdown("#### 📈 Distribuição por Prioridade")
        
        prioridade_counts = selecionados_atual["Prioridade"].value_counts().sort_index()
        prioridade_df = pd.DataFrame({
            "Prioridade": prioridade_counts.index,
            "Quantidade": prioridade_counts.values,
            "Porcentagem": (prioridade_counts.values / len(selecionados_atual) * 100).round(1)
        })
        
        st.dataframe(prioridade_df, use_container_width=True, hide_index=True)
        
        # Lista detalhada
        with st.expander("📋 Ver lista detalhada dos condomínios selecionados"):
            for _, row in selecionados_atual.sort_values(["Prioridade", "Aptos"], ascending=[True, False]).iterrows():
                st.write(f"**{row['Prioridade']}** - {row['Condomínio']} | {row['Bairro']} | {row['Aptos']} aptos | {row['Visitas/Semana']}x/semana")
    else:
        st.warning("Nenhum condomínio selecionado. Selecione os condomínios para a campanha.")

# ============================================================================
# AGENDAMENTO INTELIGENTE
# ============================================================================

def agendamento_inteligente(db, data_inicio: date, data_fim: date = None):
    """
    Algoritmo inteligente para sugerir agendamentos baseado nos condomínios da campanha
    """
    if not data_fim:
        data_fim = data_inicio + timedelta(days=30)
    
    # Buscar condomínios ativos na campanha
    campanha = list(db.campanha_visitas.find({"ativo": True}))
    
    if not campanha:
        return []
    
    # Calcular necessidade de visitas
    necessidade = {}
    for cond_campanha in campanha:
        freq = cond_campanha.get('frequencia_sugerida', 1)
        dias_periodo = (data_fim - data_inicio).days
        semanas = dias_periodo / 7
        visitas_necessarias = max(1, int(freq * semanas))
        
        # Verificar agendamentos existentes
        agendados = db.visitas_vendedoras.count_documents({
            "condominio_id": cond_campanha["condominio_id"],
            "data": {"$gte": data_inicio.strftime("%Y-%m-%d"), "$lte": data_fim.strftime("%Y-%m-%d")},
            "status": {"$ne": "cancelado"}
        })
        
        necessidade[str(cond_campanha["condominio_id"])] = max(0, visitas_necessarias - agendados)
    
    # Buscar vendedoras ativas
    vendedoras = list(db.vendedoras.find({"ativo": True}))
    
    # Criar mapa de disponibilidade
    dias_disponiveis = {}
    for delta in range((data_fim - data_inicio).days + 1):
        data = data_inicio + timedelta(days=delta)
        dia_semana = data.weekday()
        
        if dia_semana == 6:
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
    
    # Ordenar condomínios por prioridade
    campanha_ordenada = sorted(
        campanha,
        key=lambda c: -get_peso_prioridade(c["prioridade"])
    )
    
    sugestoes = []
    
    for cond_campanha in campanha_ordenada:
        if necessidade.get(str(cond_campanha["condominio_id"]), 0) <= 0:
            continue
        
        # Criar objeto condomínio para verificação de proximidade
        cond_obj = {
            "bairro": cond_campanha.get("bairro", "")
        }
        
        # Ordenar dias
        dias_ordenados = sorted(dias_disponiveis.items())
        
        for data_str, dia_info in dias_ordenados:
            dia_semana = dia_info["dia_semana"]
            
            for vend in vendedoras:
                if dia_semana not in vend["disponibilidade"]:
                    continue
                
                if dia_info["agendamentos"][vend["nome"]] >= vend.get("max_visitas_dia", 2):
                    continue
                
                # Verificar proximidade
                visitas_do_dia = db.visitas_vendedoras.find({
                    "data": data_str,
                    "vendedora": vend["nome"],
                    "status": {"$ne": "cancelado"}
                })
                
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
                
                sugestoes.append({
                    "condominio_id": cond_campanha["condominio_id"],
                    "condominio_nome": cond_campanha["condominio_nome"],
                    "vendedora": vend["nome"],
                    "data": data_str,
                    "data_obj": dia_info["data_obj"],
                    "dia_semana": DIAS_SEMANA[dia_semana],
                    "prioridade": cond_campanha["prioridade"],
                    "aptos": cond_campanha["aptos"]
                })
                
                dias_disponiveis[data_str]["agendamentos"][vend["nome"]] += 1
                necessidade[str(cond_campanha["condominio_id"])] -= 1
                break
            
            if necessidade.get(str(cond_campanha["condominio_id"]), 0) <= 0:
                break
    
    return sugestoes

# ============================================================================
# VISÃO DO ADMIN
# ============================================================================

def tela_admin_visitas(db, perfil_usuario, nome_usuario):
    """Interface completa para admin/diretoria/supervisores"""
    
    st.markdown("## 📅 Gerenciamento de Visitas de Vendedoras")
    
    # Abas principais
    tab_campanha, tab_agenda, tab_vendedoras, tab_relatorios = st.tabs([
        "🎯 Campanha", "📆 Agenda", "👩‍💼 Vendedoras", "📊 Relatórios"
    ])
    
    with tab_campanha:
        # Importar clientes_collection para acessar condomínios originais
        from modules.condominios import get_condominios_collection
        clientes_collection = get_condominios_collection()
        selecionar_condominios_campanha(db, clientes_collection)
    
    with tab_agenda:
        col_f1, col_f2, col_f3, col_f4 = st.columns(4)
        
        with col_f1:
            filtro_vendedora = st.selectbox(
                "👩‍💼 Vendedora",
                options=["Todas"] + [v["nome"] for v in db.vendedoras.find({"ativo": True})],
                key="filtro_vend_agenda"
            )
        
        with col_f2:
            filtro_status = st.selectbox(
                "Status",
                options=["Todos", "agendado", "concluido", "cancelado"],
                key="filtro_status_agenda"
            )
        
        with col_f3:
            data_inicio = st.date_input("Data Início", value=datetime.now().date(), key="data_inicio_agenda")
        
        with col_f4:
            data_fim = st.date_input("Data Fim", value=datetime.now().date() + timedelta(days=30), key="data_fim_agenda")
        
        # Botão para gerar agenda
        col_btn1, col_btn2 = st.columns([1, 3])
        with col_btn1:
            if st.button("🤖 Gerar Agenda Inteligente", key="btn_auto_agendar", use_container_width=True):
                with st.spinner("Gerando sugestões..."):
                    # Verificar se há condomínios na campanha
                    campanha_count = db.campanha_visitas.count_documents({"ativo": True})
                    
                    if campanha_count == 0:
                        st.error("❌ Nenhum condomínio selecionado na campanha! Configure a campanha primeiro.")
                    else:
                        sugestoes = agendamento_inteligente(db, data_inicio, data_fim)
                        
                        if sugestoes:
                            st.success(f"✅ Geradas {len(sugestoes)} sugestões!")
                            
                            for sug in sugestoes[:10]:
                                with st.expander(f"📌 {sug['condominio_nome']} - {sug['data']} - {sug['vendedora']} (Prioridade: {sug['prioridade']})"):
                                    st.write(f"**Apartamentos:** {sug['aptos']}")
                                    st.write(f"**Dia:** {sug['dia_semana']}")
                                    
                                    if st.button(f"✅ Confirmar", key=f"confirm_{sug['condominio_id']}_{sug['data']}_{sug['vendedora']}"):
                                        nova_visita = {
                                            "condominio_id": sug["condominio_id"],
                                            "condominio_nome": sug["condominio_nome"],
                                            "vendedora": sug["vendedora"],
                                            "data": sug["data"],
                                            "status": "agendado",
                                            "criado_por": nome_usuario,
                                            "data_criacao": datetime.now()
                                        }
                                        db.visitas_vendedoras.insert_one(nova_visita)
                                        st.success("✅ Visita agendada!")
                                        st.rerun()
                        else:
                            st.info("Nenhuma sugestão gerada para o período.")
        
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
        
        query["data"] = {"$gte": data_inicio.strftime("%Y-%m-%d"), "$lte": data_fim.strftime("%Y-%m-%d")}
        
        visitas = list(db.visitas_vendedoras.find(query).sort("data", 1))
        
        if visitas:
            st.markdown(f"### 📋 Visitas Agendadas ({len(visitas)})")
            
            for visita in visitas:
                data_obj = datetime.strptime(visita["data"], "%Y-%m-%d").date()
                status_icon = "✅" if visita["status"] == "concluido" else "⏳" if visita["status"] == "agendado" else "❌"
                
                with st.expander(f"{status_icon} {data_obj.strftime('%d/%m/%Y')} - {visita['condominio_nome']} - {visita['vendedora']}", expanded=False):
                    col1, col2 = st.columns(2)
                    
                    with col1:
                        st.write(f"**Status:** {visita['status']}")
                        if visita.get("observacoes"):
                            st.write(f"**Observações:** {visita['observacoes']}")
                    
                    with col2:
                        if visita["status"] == "agendado":
                            if st.button("✅ Concluir", key=f"conc_{visita['_id']}"):
                                obs = st.text_input("Observações", key=f"obs_{visita['_id']}")
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
                                if st.button("❌ Cancelar", key=f"cancel_{visita['_id']}"):
                                    db.visitas_vendedoras.update_one(
                                        {"_id": visita["_id"]},
                                        {"$set": {
                                            "status": "cancelado",
                                            "data_cancelamento": datetime.now()
                                        }}
                                    )
                                    st.success("❌ Visita cancelada!")
                                    st.rerun()
        else:
            st.info("Nenhuma visita agendada no período.")
    
    with tab_vendedoras:
        gerenciar_vendedoras(db)
    
    with tab_relatorios:
        st.markdown("### 📊 Relatórios de Visitas")
        
        # Relatório resumo da campanha
        campanha_ativa = list(db.campanha_visitas.find({"ativo": True}))
        
        if campanha_ativa:
            st.markdown("#### 📈 Resumo da Campanha Atual")
            
            col_r1, col_r2, col_r3 = st.columns(3)
            
            with col_r1:
                st.metric("Condomínios na Campanha", len(campanha_ativa))
            
            with col_r2:
                total_aptos = sum(c.get("aptos", 0) for c in campanha_ativa)
                st.metric("Total de Apartamentos", f"{total_aptos:,}")
            
            with col_r3:
                visitas_concluidas = db.visitas_vendedoras.count_documents({"status": "concluido"})
                st.metric("Visitas Concluídas (Total)", visitas_concluidas)
            
            # Gráfico de progresso
            st.markdown("#### 🎯 Progresso por Condomínio")
            
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
                    "Condomínio": cond["condominio_nome"][:30],
                    "Total Visitas": total_visitas,
                    "Concluídas": visitas_concluidas_cond,
                    "Progresso": f"{(visitas_concluidas_cond/total_visitas*100):.0f}%" if total_visitas > 0 else "0%"
                })
            
            df_progresso = pd.DataFrame(dados_progresso)
            st.dataframe(df_progresso, use_container_width=True, hide_index=True)

def gerenciar_vendedoras(db):
    """Interface para gerenciar vendedoras"""
    st.markdown("### 👩‍💼 Gestão de Vendedoras")
    
    tab_lista, tab_nova = st.tabs(["📋 Lista de Vendedoras", "➕ Nova Vendedora"])
    
    with tab_lista:
        vendedoras = list(db.vendedoras.find({}))
        
        if vendedoras:
            for vendedora in vendedoras:
                with st.expander(f"👤 {vendedora['nome']} - {vendedora['tipo'].title()}", expanded=False):
                    col1, col2 = st.columns(2)
                    
                    with col1:
                        st.write(f"**Tipo:** {vendedora['tipo'].title()}")
                        st.write(f"**Horário:** {vendedora.get('horario', '08:00-17:00')}")
                        st.write(f"**Max visitas/dia:** {vendedora.get('max_visitas_dia', 2)}")
                    
                    with col2:
                        dias_disponiveis = [DIAS_SEMANA[d] for d in vendedora.get('disponibilidade', [])]
                        st.write(f"**Dias disponíveis:** {', '.join(dias_disponiveis)}")
                        
                        ativo = st.checkbox("Ativo", value=vendedora.get("ativo", True), key=f"ativo_{vendedora['nome']}")
                        if ativo != vendedora.get("ativo", True):
                            db.vendedoras.update_one(
                                {"_id": vendedora["_id"]},
                                {"$set": {"ativo": ativo}}
                            )
                            st.rerun()
                    
                    # Estatísticas
                    total_visitas = db.visitas_vendedoras.count_documents({"vendedora": vendedora["nome"]})
                    visitas_concluidas = db.visitas_vendedoras.count_documents({
                        "vendedora": vendedora["nome"],
                        "status": "concluido"
                    })
                    
                    col_est1, col_est2 = st.columns(2)
                    with col_est1:
                        st.metric("Total Visitas", total_visitas)
                    with col_est2:
                        st.metric("Concluídas", visitas_concluidas)
        else:
            st.info("Nenhuma vendedora cadastrada.")
    
    with tab_nova:
        col1, col2 = st.columns(2)
        
        with col1:
            nome = st.text_input("Nome da Vendedora*", key="nova_vend_nome")
            tipo = st.selectbox("Tipo", ["fixa", "freelancer"], key="nova_vend_tipo")
            
        with col2:
            max_visitas = st.number_input("Máximo de visitas por dia", min_value=1, max_value=5, value=2, key="nova_vend_max")
            horario = st.text_input("Horário de trabalho", value="08:00-17:00", key="nova_vend_horario")
        
        st.markdown("**Dias disponíveis:**")
        col_dias = st.columns(7)
        dias_selecionados = []
        
        for i, dia in enumerate(DIAS_SEMANA[:6]):
            with col_dias[i]:
                if st.checkbox(dia, key=f"dia_{nome}_{i}"):
                    dias_selecionados.append(i)
        
        if tipo == "freelancer":
            st.info("💡 Freelancers têm disponibilidade limitada.")
        
        if st.button("✅ Cadastrar Vendedora", key="btn_cad_vend"):
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
                        "ativo": True,
                        "data_cadastro": datetime.now()
                    }
                    db.vendedoras.insert_one(nova_vend)
                    st.success(f"✅ Vendedora '{nome}' cadastrada!")
                    st.rerun()

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
            Agendamento inteligente de visitas em condomínios
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
