# modules/visitas_vendedoras.py
"""
Módulo de Gerenciamento de Visitas de Vendedoras
- Gestão de vendedoras e condomínios
- Agendamento inteligente com regras de negócio
- Visualizações por perfil
- Exportação de relatórios
"""

import streamlit as st
import pandas as pd
from datetime import datetime, timedelta, date
from collections import defaultdict
import io
from bson.objectid import ObjectId
from typing import Dict, List, Tuple, Optional
import calendar

# ============================================================================
# CONFIGURAÇÕES INICIAIS
# ============================================================================

# Dias da semana (0=segunda, 1=terça, 2=quarta, 3=quinta, 4=sexta, 5=sábado, 6=domingo)
DIAS_SEMANA = ['Segunda', 'Terça', 'Quarta', 'Quinta', 'Sexta', 'Sábado', 'Domingo']

# Configuração padrão de disponibilidade das vendedoras
DISPONIBILIDADE_PADRAO = {
    "Kessia": {
        "dias": [0, 1, 2, 3, 4],  # Seg a Sex
        "horario": "08:00-17:00",
        "max_visitas_dia": 2,
        "tipo": "fixa"
    },
    "Larissa": {
        "dias": [0, 1, 2, 3, 4],  # Seg a Sex
        "horario": "08:00-17:00",
        "max_visitas_dia": 2,
        "tipo": "fixa"
    },
    "Estephanie": {
        "dias": [0, 1, 2, 3, 4],  # Seg a Sex
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

def get_prioridade_condominio(aptos: int) -> str:
    """Define prioridade baseada no número de apartamentos"""
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
    """
    Calcula quantas visitas por semana com base no tamanho do condomínio
    Condomínios maiores precisam de mais visitas
    """
    if aptos >= 1000:
        return 3  # 3x por semana
    elif aptos >= 500:
        return 2  # 2x por semana
    elif aptos >= 200:
        return 1  # 1x por semana
    else:
        return 1  # 1x por semana padrão

def condominios_proximos(cond1: dict, cond2: dict) -> bool:
    """
    Verifica se dois condomínios são próximos
    Baseado no bairro/nome do condomínio
    """
    # Mapeamento de bairros/regiões
    regioes = {
        "Jacarepagua": ["JACAREPAGUA", "MY JACAREPAGUA", "STYLE"],
        "Barra": ["BARRA", "ORLA RECREIO", "PRAIA DO PONTAL", "PRAINHA", "RIO MAR"],
        "Centro": ["PORTO CARIOCA", "CACHAMBI", "BONSUCESSO", "PORTO VALENCIA"],
        "Tijuca": ["GRAN ROYAL", "PARQUE IRIS", "SIDE PARK", "MATO ALTO"],
        "Irajá": ["NOVA IRAJA", "JERIVA"],
        "Vila Isabel": ["TRENDY CACHAMBI"],
        "Recreio": ["RESERVA CARIOCA", "ORLA RECREIO RESERVA", "VITALE ON"],
        "Jacarepagua/Santos Dumont": ["IPA STUDIOS", "DUET BARRA"],
        "Rio Comprido": ["RIO ENERGY"],
        "Bonsucesso": ["CONNECT BONSUCESSO"],
        "Méier": ["LIVING PARQUE", "JARDIM ORQUIDEA", "JARDIM JASMIM"],
        "Cascadura": ["PORTAL SOLAR DOS CANARIOS"],
        "Penha": ["ETHE RESIDENCIAL"],
        "Pilares": ["PRIMOR CARIOCA"],
        "Vicente de Carvalho": ["NOVA NORTE SAMBA"],
        "Madureira": ["STILLO BARRA"],
        "Campinho": ["RESIDENCIAL JERIVA"]
    }
    
    nome1 = cond1.get('nome', '').upper()
    nome2 = cond2.get('nome', '').upper()
    
    # Encontrar região do primeiro condomínio
    regiao1 = "OUTROS"
    for regiao, palavras in regioes.items():
        if any(palavra.upper() in nome1 for palavra in palavras):
            regiao1 = regiao
            break
    
    # Encontrar região do segundo condomínio
    regiao2 = "OUTROS"
    for regiao, palavras in regioes.items():
        if any(palavra.upper() in nome2 for palavra in palavras):
            regiao2 = regiao
            break
    
    return regiao1 == regiao2 and regiao1 != "OUTROS"

# ============================================================================
# INICIALIZAÇÃO DAS COLEÇÕES
# ============================================================================

def init_colecoes_visitas(clientes_collection):
    """Inicializa as coleções necessárias para o módulo"""
    db = clientes_collection.database
    
    # Coleção de condomínios para visitas
    if 'condominios_visitas' not in db.list_collection_names():
        db.create_collection('condominios_visitas')
        db.condominios_visitas.create_index("nome", unique=True)
    
    # Coleção de vendedoras
    if 'vendedoras' not in db.list_collection_names():
        db.create_collection('vendedoras')
        # Inserir vendedoras padrão
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
# CADASTRO DE CONDOMÍNIOS
# ============================================================================

def cadastrar_condominio_visita(db):
    """Formulário para cadastrar/editar condomínio para visitas"""
    st.markdown("### 🏢 Cadastro de Condomínios para Visitas")
    
    col1, col2 = st.columns(2)
    
    with col1:
        nome = st.text_input("Nome do Condomínio*", key="cad_cond_nome")
        endereco = st.text_input("Endereço", key="cad_cond_endereco")
        bairro = st.text_input("Bairro", key="cad_cond_bairro")
        responsavel = st.text_input("Responsável/Portaria", key="cad_cond_responsavel")
        
    with col2:
        aptos = st.number_input("Número de Apartamentos*", min_value=1, step=1, key="cad_cond_aptos")
        prioridade_manual = st.selectbox(
            "Prioridade",
            ["Automática", "A+ (Prioridade Máxima)", "A (Alta)", "B (Média)", "C (Baixa)", "D (Mínima)"],
            key="cad_cond_prioridade"
        )
        prefere_sabado = st.checkbox("Prefere visitas aos sábados", key="cad_cond_sabado")
        ativo = st.checkbox("Ativo para visitas", value=True, key="cad_cond_ativo")
    
    observacoes = st.text_area("Observações", placeholder="Ex: Apenas sábados tem movimento, Portaria restritiva, etc.", key="cad_cond_obs")
    
    # Calcular prioridade
    prioridade_auto = get_prioridade_condominio(aptos)
    
    if prioridade_manual == "Automática":
        prioridade_final = prioridade_auto
        prioridade_desc = prioridade_auto
    else:
        prioridade_final = prioridade_manual.split(" ")[0]
        prioridade_desc = prioridade_manual
    
    freq_sugerida = calcular_frequencia_semanal(aptos)
    
    st.info(f"""
    📊 **Informações de priorização:**
    - Prioridade automática: **{prioridade_auto}**
    - Prioridade definida: **{prioridade_desc}**
    - Visitas sugeridas: **{freq_sugerida} vez(es) por semana**
    """)
    
    col_btn1, col_btn2 = st.columns(2)
    
    with col_btn1:
        if st.button("✅ Cadastrar Condomínio", key="btn_cad_cond", use_container_width=True):
            if not nome or not aptos:
                st.error("⚠️ Nome e número de aptos são obrigatórios!")
            else:
                existente = db.condominios_visitas.find_one({"nome": nome})
                if existente:
                    st.error(f"❌ Condomínio '{nome}' já cadastrado!")
                else:
                    novo_cond = {
                        "nome": nome,
                        "endereco": endereco,
                        "bairro": bairro,
                        "responsavel": responsavel,
                        "aptos": aptos,
                        "prioridade": prioridade_final,
                        "prioridade_auto": prioridade_auto,
                        "frequencia_sugerida": freq_sugerida,
                        "prefere_sabado": prefere_sabado,
                        "ativo": ativo,
                        "observacoes": observacoes,
                        "data_cadastro": datetime.now()
                    }
                    db.condominios_visitas.insert_one(novo_cond)
                    st.success(f"✅ Condomínio '{nome}' cadastrado com sucesso!")
                    st.rerun()
    
    with col_btn2:
        if st.button("📋 Listar Condomínios", key="btn_list_cond", use_container_width=True):
            st.session_state.show_cond_list_visitas = not st.session_state.get("show_cond_list_visitas", False)
    
    if st.session_state.get("show_cond_list_visitas", False):
        st.markdown("---")
        st.markdown("### 📋 Condomínios Cadastrados")
        
        condominios = list(db.condominios_visitas.find({}).sort("prioridade", -1))
        
        if condominios:
            dados = []
            for cond in condominios:
                dados.append({
                    "Nome": cond["nome"],
                    "Aptos": cond["aptos"],
                    "Prioridade": cond["prioridade"],
                    "Frequência": f"{cond.get('frequencia_sugerida', 1)}x/semana",
                    "Prefere Sábado": "✅" if cond.get("prefere_sabado", False) else "❌",
                    "Ativo": "✅" if cond.get("ativo", True) else "❌"
                })
            
            df = pd.DataFrame(dados)
            st.dataframe(df, use_container_width=True, hide_index=True)
            
            # Opção de editar
            cond_selecionado = st.selectbox(
                "Selecione um condomínio para editar",
                options=[c["nome"] for c in condominios],
                key="select_cond_editar_visitas"
            )
            
            if cond_selecionado:
                if st.button("✏️ Editar Selecionado", key="btn_editar_cond_visitas"):
                    st.session_state.cond_editando_visitas = cond_selecionado
                    st.rerun()
            
            if st.session_state.get("cond_editando_visitas"):
                cond = db.condominios_visitas.find_one({"nome": st.session_state.cond_editando_visitas})
                if cond:
                    st.markdown("#### ✏️ Editando Condomínio")
                    
                    col_edit1, col_edit2 = st.columns(2)
                    with col_edit1:
                        novo_nome = st.text_input("Nome", value=cond["nome"], key="edit_nome_visitas")
                        novos_aptos = st.number_input("Aptos", value=cond["aptos"], key="edit_aptos_visitas")
                    with col_edit2:
                        novo_ativo = st.checkbox("Ativo", value=cond.get("ativo", True), key="edit_ativo_visitas")
                        novo_sabado = st.checkbox("Prefere Sábado", value=cond.get("prefere_sabado", False), key="edit_sabado_visitas")
                    
                    if st.button("💾 Salvar Alterações", key="btn_save_cond_visitas"):
                        db.condominios_visitas.update_one(
                            {"_id": cond["_id"]},
                            {"$set": {
                                "nome": novo_nome,
                                "aptos": novos_aptos,
                                "prioridade": get_prioridade_condominio(novos_aptos),
                                "prioridade_auto": get_prioridade_condominio(novos_aptos),
                                "frequencia_sugerida": calcular_frequencia_semanal(novos_aptos),
                                "ativo": novo_ativo,
                                "prefere_sabado": novo_sabado
                            }}
                        )
                        st.success("✅ Alterações salvas!")
                        del st.session_state.cond_editando_visitas
                        st.rerun()
                    
                    if st.button("❌ Cancelar Edição"):
                        del st.session_state.cond_editando_visitas
                        st.rerun()
        else:
            st.info("Nenhum condomínio cadastrado ainda.")

# ============================================================================
# GESTÃO DE VENDEDORAS
# ============================================================================

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
                        st.write(f"**Máximo visitas/dia:** {vendedora.get('max_visitas_dia', 2)}")
                    
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
                    st.markdown("**📊 Estatísticas recentes:**")
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
            st.info("💡 Freelancers têm disponibilidade limitada. Selecione apenas os dias que podem trabalhar.")
        
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
                    st.success(f"✅ Vendedora '{nome}' cadastrada com sucesso!")
                    st.rerun()

# ============================================================================
# AGENDAMENTO INTELIGENTE
# ============================================================================

def agendamento_inteligente(db, data_inicio: date, data_fim: date = None):
    """
    Algoritmo inteligente para sugerir agendamentos de visitas
    """
    if not data_fim:
        data_fim = data_inicio + timedelta(days=30)
    
    # Buscar condomínios ativos
    condominios = list(db.condominios_visitas.find({"ativo": True}))
    
    # Calcular necessidade de visitas
    necessidade = {}
    for cond in condominios:
        freq = cond.get('frequencia_sugerida', 1)
        dias_periodo = (data_fim - data_inicio).days
        semanas = dias_periodo / 7
        visitas_necessarias = max(1, int(freq * semanas))
        
        # Verificar agendamentos existentes
        agendados = db.visitas_vendedoras.count_documents({
            "condominio_id": cond["_id"],
            "data": {"$gte": data_inicio.strftime("%Y-%m-%d"), "$lte": data_fim.strftime("%Y-%m-%d")},
            "status": {"$ne": "cancelado"}
        })
        
        necessidade[cond["_id"]] = max(0, visitas_necessarias - agendados)
    
    # Buscar vendedoras ativas
    vendedoras = list(db.vendedoras.find({"ativo": True}))
    
    # Criar mapa de disponibilidade por dia
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
    
    # Ordenar condomínios: prioridade > necessidade > aptos
    condominios_ordenados = sorted(
        condominios,
        key=lambda c: (
            -get_peso_prioridade(c["prioridade"]),
            -necessidade.get(c["_id"], 0),
            -c["aptos"]
        )
    )
    
    sugestoes = []
    
    # Para cada condomínio, tentar agendar
    for cond in condominios_ordenados:
        if necessidade.get(cond["_id"], 0) <= 0:
            continue
        
        # Ordenar dias: preferir sábado se condomínio preferir
        dias_ordenados = sorted(dias_disponiveis.items())
        if cond.get("prefere_sabado", False):
            dias_ordenados.sort(key=lambda x: (0 if x[1]["eh_sabado"] else 1, x[0]))
        
        for data_str, dia_info in dias_ordenados:
            dia_semana = dia_info["dia_semana"]
            
            # Ordenar vendedoras por disponibilidade
            vendedoras_ordenadas = sorted(vendedoras, key=lambda v: (
                0 if dia_semana in v["disponibilidade"] else 1,
                dia_info["agendamentos"][v["nome"]]
            ))
            
            for vend in vendedoras_ordenadas:
                # Verificar se vendedora trabalha neste dia
                if dia_semana not in vend["disponibilidade"]:
                    continue
                
                # Verificar limite de visitas por dia
                if dia_info["agendamentos"][vend["nome"]] >= vend.get("max_visitas_dia", 2):
                    continue
                
                # Verificar proximidade com outras visitas do mesmo dia
                visitas_do_dia = db.visitas_vendedoras.find({
                    "data": data_str,
                    "vendedora": vend["nome"],
                    "status": {"$ne": "cancelado"}
                })
                
                ja_tem_proxima = False
                for visita in visitas_do_dia:
                    cond_visitado = db.condominios_visitas.find_one({"_id": visita["condominio_id"]})
                    if cond_visitado and condominios_proximos(cond, cond_visitado):
                        ja_tem_proxima = True
                        break
                
                # Se já tem uma visita próxima e não é a primeira do dia, pular
                if ja_tem_proxima and dia_info["agendamentos"][vend["nome"]] > 0:
                    continue
                
                # Sugerir agendamento
                sugestoes.append({
                    "condominio": cond,
                    "vendedora": vend["nome"],
                    "data": data_str,
                    "data_obj": dia_info["data_obj"],
                    "dia_semana": DIAS_SEMANA[dia_semana],
                    "prioridade": cond["prioridade"],
                    "aptos": cond["aptos"],
                    "eh_sabado": dia_info["eh_sabado"]
                })
                
                # Atualizar contador
                dias_disponiveis[data_str]["agendamentos"][vend["nome"]] += 1
                necessidade[cond["_id"]] -= 1
                break
        
        if necessidade.get(cond["_id"], 0) > 0:
            # Se não conseguiu agendar todas, tentar dias sem restrição de proximidade
            for data_str, dia_info in dias_ordenados:
                dia_semana = dia_info["dia_semana"]
                
                for vend in vendedoras_ordenadas:
                    if dia_semana in vend["disponibilidade"]:
                        if dia_info["agendamentos"][vend["nome"]] < vend.get("max_visitas_dia", 2):
                            sugestoes.append({
                                "condominio": cond,
                                "vendedora": vend["nome"],
                                "data": data_str,
                                "data_obj": dia_info["data_obj"],
                                "dia_semana": DIAS_SEMANA[dia_semana],
                                "prioridade": cond["prioridade"],
                                "aptos": cond["aptos"],
                                "eh_sabado": dia_info["eh_sabado"]
                            })
                            dias_disponiveis[data_str]["agendamentos"][vend["nome"]] += 1
                            necessidade[cond["_id"]] -= 1
                            break
                
                if necessidade.get(cond["_id"], 0) <= 0:
                    break
    
    return sugestoes

# ============================================================================
# VISÃO DO ADMIN
# ============================================================================

def tela_admin_visitas(db, perfil_usuario, nome_usuario):
    """Interface completa para admin/diretoria/supervisores"""
    
    st.markdown("## 📅 Gerenciamento de Visitas de Vendedoras")
    
    # Abas principais
    tab_agenda, tab_condominios, tab_vendedoras, tab_relatorios = st.tabs([
        "📆 Agenda de Visitas", "🏢 Condomínios", "👩‍💼 Vendedoras", "📊 Relatórios"
    ])
    
    with tab_agenda:
        # Filtros
        col_f1, col_f2, col_f3, col_f4 = st.columns(4)
        
        with col_f1:
            filtro_vendedora = st.selectbox(
                "👩‍💼 Vendedora",
                options=["Todas"] + [v["nome"] for v in db.vendedoras.find({"ativo": True})],
                key="filtro_vend_agenda_admin"
            )
        
        with col_f2:
            filtro_status = st.selectbox(
                "Status",
                options=["Todos", "agendado", "concluido", "cancelado"],
                key="filtro_status_agenda_admin"
            )
        
        with col_f3:
            data_inicio = st.date_input("Data Início", value=datetime.now().date(), key="data_inicio_agenda_admin")
        
        with col_f4:
            data_fim = st.date_input("Data Fim", value=datetime.now().date() + timedelta(days=30), key="data_fim_agenda_admin")
        
        # Botão para gerar agendamento inteligente
        col_btn1, col_btn2 = st.columns([1, 3])
        with col_btn1:
            if st.button("🤖 Gerar Agenda Inteligente", key="btn_auto_agendar", use_container_width=True):
                with st.spinner("Gerando sugestões de agendamento..."):
                    sugestoes = agendamento_inteligente(db, data_inicio, data_fim)
                    
                    if sugestoes:
                        st.success(f"✅ Geradas {len(sugestoes)} sugestões!")
                        
                        # Mostrar sugestões
                        for sug in sugestoes:
                            with st.expander(f"📌 {sug['condominio']['nome']} - {sug['data']} - {sug['vendedora']} (Prioridade: {sug['prioridade']})"):
                                st.write(f"**Apartamentos:** {sug['aptos']}")
                                st.write(f"**Dia da semana:** {sug['dia_semana']}")
                                
                                col_sug1, col_sug2 = st.columns(2)
                                with col_sug1:
                                    if st.button(f"✅ Confirmar", key=f"confirm_{sug['condominio']['_id']}_{sug['data']}_{sug['vendedora']}"):
                                        nova_visita = {
                                            "condominio_id": sug["condominio"]["_id"],
                                            "condominio_nome": sug["condominio"]["nome"],
                                            "vendedora": sug["vendedora"],
                                            "data": sug["data"],
                                            "status": "agendado",
                                            "criado_por": nome_usuario,
                                            "data_criacao": datetime.now()
                                        }
                                        db.visitas_vendedoras.insert_one(nova_visita)
                                        st.success("✅ Visita agendada!")
                                        st.rerun()
                                with col_sug2:
                                    if st.button(f"❌ Descartar", key=f"discard_{sug['condominio']['_id']}_{sug['data']}_{sug['vendedora']}"):
                                        st.info("Sugestão descartada.")
                    else:
                        st.info("Nenhuma sugestão gerada para o período.")
        
        with col_btn2:
            if st.button("🔄 Atualizar", key="btn_atualizar_agenda", use_container_width=True):
                st.rerun()
        
        st.markdown("---")
        
        # Buscar visitas agendadas
        query = {}
        if filtro_vendedora != "Todas":
            query["vendedora"] = filtro_vendedora
        if filtro_status != "Todos":
            query["status"] = filtro_status
        
        query["data"] = {"$gte": data_inicio.strftime("%Y-%m-%d"), "$lte": data_fim.strftime("%Y-%m-%d")}
        
        visitas = list(db.visitas_vendedoras.find(query).sort("data", 1))
        
        if visitas:
            st.markdown(f"### 📋 Visitas Agendadas ({len(visitas)})")
            
            # Agrupar por data
            visitas_por_data = defaultdict(list)
            for visita in visitas:
                visitas_por_data[visita["data"]].append(visita)
            
            for data_str in sorted(visitas_por_data.keys()):
                visits = visitas_por_data[data_str]
                data_obj = datetime.strptime(data_str, "%Y-%m-%d").date()
                dia_semana = DIAS_SEMANA[data_obj.weekday()]
                
                st.markdown(f"#### 📅 {data_obj.strftime('%d/%m/%Y')} - {dia_semana}")
                
                for visita in visits:
                    with st.container():
                        col1, col2, col3, col4, col5 = st.columns([3, 2, 1.5, 1, 1])
                        
                        with col1:
                            st.write(f"**🏢 {visita['condominio_nome']}**")
                        
                        with col2:
                            st.write(f"👩‍💼 {visita['vendedora']}")
                        
                        with col3:
                            status_map = {
                                "agendado": "⏳ Agendado",
                                "concluido": "✅ Concluído",
                                "cancelado": "❌ Cancelado"
                            }
                            st.write(status_map.get(visita["status"], visita["status"]))
                        
                        with col4:
                            if visita["status"] == "agendado":
                                if st.button("✅ Concluir", key=f"conc_{visita['_id']}"):
                                    observacao = st.text_input("Observações da visita", key=f"obs_{visita['_id']}")
                                    db.visitas_vendedoras.update_one(
                                        {"_id": visita["_id"]},
                                        {"$set": {
                                            "status": "concluido",
                                            "data_conclusao": datetime.now(),
                                            "concluido_por": nome_usuario,
                                            "observacoes": observacao
                                        }}
                                    )
                                    st.success("✅ Visita concluída!")
                                    st.rerun()
                        
                        with col5:
                            if visita["status"] == "agendado":
                                if st.button("✏️", key=f"edit_{visita['_id']}"):
                                    st.session_state.editando_visita = str(visita["_id"])
                            
                            if perfil_usuario in ["admin", "diretoria"] and visita["status"] == "agendado":
                                if st.button("❌", key=f"del_{visita['_id']}"):
                                    db.visitas_vendedoras.update_one(
                                        {"_id": visita["_id"]},
                                        {"$set": {
                                            "status": "cancelado",
                                            "motivo_cancelamento": "Cancelado pelo administrador",
                                            "data_cancelamento": datetime.now()
                                        }}
                                    )
                                    st.success("❌ Visita cancelada!")
                                    st.rerun()
                        
                        # Edição inline
                        if st.session_state.get("editando_visita") == str(visita["_id"]):
                            with st.expander("✏️ Editando visita", expanded=True):
                                nova_data = st.date_input("Nova data", value=data_obj, key=f"edit_data_{visita['_id']}")
                                nova_vendedora = st.selectbox(
                                    "Nova vendedora",
                                    options=[v["nome"] for v in db.vendedoras.find({"ativo": True})],
                                    index=[v["nome"] for v in db.vendedoras.find({"ativo": True})].index(visita["vendedora"]) if visita["vendedora"] in [v["nome"] for v in db.vendedoras.find({"ativo": True})] else 0,
                                    key=f"edit_vend_{visita['_id']}"
                                )
                                
                                if st.button("💾 Salvar", key=f"save_edit_{visita['_id']}"):
                                    db.visitas_vendedoras.update_one(
                                        {"_id": visita["_id"]},
                                        {"$set": {
                                            "data": nova_data.strftime("%Y-%m-%d"),
                                            "vendedora": nova_vendedora
                                        }}
                                    )
                                    del st.session_state.editando_visita
                                    st.success("✅ Visita atualizada!")
                                    st.rerun()
                        
                        st.divider()
        else:
            st.info("Nenhuma visita agendada no período selecionado.")
    
    with tab_condominios:
        cadastrar_condominio_visita(db)
    
    with tab_vendedoras:
        gerenciar_vendedoras(db)
    
    with tab_relatorios:
        st.markdown("### 📊 Relatórios de Visitas")
        
        tipo_relatorio = st.selectbox(
            "Tipo de Relatório",
            ["Visitas por Vendedora", "Visitas por Condomínio", "Resumo Semanal", "Exportar Agenda Completa",
             "Matriz de Visitas (Semanal)", "Performance por Vendedora"]
        )
        
        if tipo_relatorio == "Visitas por Vendedora":
            vendedora_sel = st.selectbox("Vendedora", options=[v["nome"] for v in db.vendedoras.find({"ativo": True})])
            
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
                            "Status": "✅ Concluído" if vis["status"] == "concluido" else "⏳ Agendado",
                            "Observações": vis.get("observacoes", "")
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
        
        elif tipo_relatorio == "Matriz de Visitas (Semanal)":
            semana_inicio = st.date_input("Início da semana", value=datetime.now().date() - timedelta(days=datetime.now().weekday()))
            
            if semana_inicio:
                semana_fim = semana_inicio + timedelta(days=6)
                
                visitas_semana = list(db.visitas_vendedoras.find({
                    "data": {"$gte": semana_inicio.strftime("%Y-%m-%d"), "$lte": semana_fim.strftime("%Y-%m-%d")},
                    "status": {"$ne": "cancelado"}
                }))
                
                # Criar matriz
                vendedoras_lista = [v["nome"] for v in db.vendedoras.find({"ativo": True})]
                matriz = defaultdict(lambda: {dia: "" for dia in DIAS_SEMANA[:6]})
                
                for visita in visitas_semana:
                    data_obj = datetime.strptime(visita["data"], "%Y-%m-%d")
                    dia_nome = DIAS_SEMANA[data_obj.weekday()]
                    if matriz[visita["vendedora"]][dia_nome]:
                        matriz[visita["vendedora"]][dia_nome] += f", {visita['condominio_nome']}"
                    else:
                        matriz[visita["vendedora"]][dia_nome] = visita['condominio_nome']
                
                # DataFrame para exibição
                dados_matriz = []
                for vendedora in vendedoras_lista:
                    row = {"Vendedora": vendedora}
                    for dia in DIAS_SEMANA[:6]:
                        row[dia] = matriz[vendedora][dia] or "-"
                    dados_matriz.append(row)
                
                df_matriz = pd.DataFrame(dados_matriz)
                st.dataframe(df_matriz, use_container_width=True, hide_index=True)
                
                # Exportar matriz
                output = io.BytesIO()
                with pd.ExcelWriter(output, engine='openpyxl') as writer:
                    df_matriz.to_excel(writer, index=False, sheet_name='Matriz Semanal')
                output.seek(0)
                
                st.download_button(
                    label="📥 Exportar Matriz para Excel",
                    data=output.getvalue(),
                    file_name=f"matriz_visitas_{semana_inicio.strftime('%Y%m%d')}.xlsx",
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                )
        
        elif tipo_relatorio == "Exportar Agenda Completa":
            data_export_inicio = st.date_input("Data Início Exportação", value=datetime.now().date())
            data_export_fim = st.date_input("Data Fim Exportação", value=datetime.now().date() + timedelta(days=30))
            
            if st.button("📥 Exportar para Excel", key="btn_exportar_visitas"):
                visitas_export = list(db.visitas_vendedoras.find({
                    "data": {"$gte": data_export_inicio.strftime("%Y-%m-%d"), "$lte": data_export_fim.strftime("%Y-%m-%d")}
                }).sort("data", 1))
                
                if visitas_export:
                    dados_export = []
                    for vis in visitas_export:
                        data_obj = datetime.strptime(vis["data"], "%Y-%m-%d")
                        dados_export.append({
                            "Condomínio": vis["condominio_nome"],
                            "Data": data_obj.strftime("%d/%m/%Y"),
                            "Dia da Semana": DIAS_SEMANA[data_obj.weekday()],
                            "Vendedora": vis["vendedora"],
                            "Status": vis["status"],
                            "Data Conclusão": vis.get("data_conclusao", ""),
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
# VISÃO DA VENDEDORA
# ============================================================================

def tela_vendedora_visitas(db, nome_usuario):
    """Interface para vendedora ver seus próprios agendamentos"""
    
    st.markdown(f"## 📅 Minha Agenda de Visitas - {nome_usuario}")
    
    # Verificar se é uma vendedora cadastrada
    vendedora = db.vendedoras.find_one({"nome": nome_usuario})
    if not vendedora:
        st.error("❌ Seu perfil não está configurado como vendedora no sistema.")
        return
    
    # Filtros
    col_f1, col_f2 = st.columns(2)
    with col_f1:
        filtro_status = st.selectbox(
            "Status",
            options=["Todos", "agendado", "concluido"],
            key="filtro_status_vendedora"
        )
    with col_f2:
        periodo = st.selectbox(
            "Período",
            options=["Próximos 30 dias", "Próximos 7 dias", "Todos os futuros", "Histórico"],
            key="periodo_vendedora"
        )
    
    # Montar query
    query = {"vendedora": nome_usuario}
    if filtro_status != "Todos":
        query["status"] = filtro_status
    
    hoje = datetime.now().date()
    if periodo == "Próximos 7 dias":
        data_fim = hoje + timedelta(days=7)
        query["data"] = {"$gte": hoje.strftime("%Y-%m-%d"), "$lte": data_fim.strftime("%Y-%m-%d")}
    elif periodo == "Próximos 30 dias":
        data_fim = hoje + timedelta(days=30)
        query["data"] = {"$gte": hoje.strftime("%Y-%m-%d"), "$lte": data_fim.strftime("%Y-%m-%d")}
    elif periodo == "Todos os futuros":
        query["data"] = {"$gte": hoje.strftime("%Y-%m-%d")}
    elif periodo == "Histórico":
        query["data"] = {"$lt": hoje.strftime("%Y-%m-%d")}
    
    visitas = list(db.visitas_vendedoras.find(query).sort("data", 1))
    
    if visitas:
        # Resumo
        total = len(visitas)
        agendadas = len([v for v in visitas if v["status"] == "agendado"])
        concluidas = len([v for v in visitas if v["status"] == "concluido"])
        
        col_r1, col_r2, col_r3 = st.columns(3)
        with col_r1:
            st.metric("📋 Total de Visitas", total)
        with col_r2:
            st.metric("⏳ Pendentes", agendadas)
        with col_r3:
            st.metric("✅ Concluídas", concluidas)
        
        st.markdown("---")
        
        # Listar visitas
        for visita in visitas:
            data_obj = datetime.strptime(visita["data"], "%Y-%m-%d").date()
            status_icon = "✅" if visita["status"] == "concluido" else "⏳"
            
            with st.expander(f"{status_icon} {data_obj.strftime('%d/%m/%Y')} - {visita['condominio_nome']}", expanded=visita["status"] == "agendado"):
                st.write(f"**Dia da semana:** {DIAS_SEMANA[data_obj.weekday()]}")
                
                if visita.get("observacoes"):
                    st.info(f"📝 Observações: {visita['observacoes']}")
                
                if visita["status"] == "agendado":
                    st.warning("⚠️ Esta visita ainda não foi concluída.")
                    
                    observacao = st.text_area("Registrar observações da visita", key=f"obs_vend_{visita['_id']}")
                    
                    col_btn_v1, col_btn_v2 = st.columns(2)
                    with col_btn_v1:
                        if st.button("✅ Marcar como Concluída", key=f"conc_vend_{visita['_id']}"):
                            db.visitas_vendedoras.update_one(
                                {"_id": visita["_id"]},
                                {"$set": {
                                    "status": "concluido",
                                    "data_conclusao": datetime.now(),
                                    "observacoes": observacao
                                }}
                            )
                            st.success("✅ Visita registrada com sucesso!")
                            st.rerun()
                    
                    with col_btn_v2:
                        motivo = st.text_input("Motivo do cancelamento", key=f"motivo_vend_{visita['_id']}")
                        if motivo and st.button("❌ Cancelar Visita", key=f"cancel_vend_{visita['_id']}"):
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
                    st.success("✅ Visita já realizada e registrada.")
                    
                    if visita.get("data_conclusao"):
                        data_conc = datetime.fromisoformat(str(visita["data_conclusao"])) if isinstance(visita["data_conclusao"], str) else visita["data_conclusao"]
                        st.caption(f"Registrada em: {data_conc.strftime('%d/%m/%Y %H:%M')}")
    else:
        st.info("📭 Nenhuma visita encontrada para os filtros selecionados.")

# ============================================================================
# FUNÇÃO PRINCIPAL DE RENDERIZAÇÃO
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
    
    # Permissões
    perfis_admin = ["admin", "diretoria", "supervisao_n1", "supervisao_n2", "supervisao_n3"]
    perfis_atendimento = ["atendente_n1", "recepcao"]
    
    # Título e descrição
    st.markdown("""
    <div style='background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); padding: 1rem; border-radius: 10px; margin-bottom: 2rem;'>
        <h2 style='color: white; margin: 0;'>👩‍💼 Gestão de Visitas de Vendedoras</h2>
        <p style='color: white; margin: 0.5rem 0 0 0; opacity: 0.9;'>
            Agendamento inteligente de visitas em condomínios
        </p>
    </div>
    """, unsafe_allow_html=True)
    
    # Redirecionar baseado no perfil
    if perfil in perfis_admin or perfil in perfis_atendimento:
        tela_admin_visitas(db, perfil, nome_usuario)
    elif perfil == "vendedora":
        tela_vendedora_visitas(db, nome_usuario)
    else:
        st.error("❌ Você não tem permissão para acessar este módulo.")
        return
