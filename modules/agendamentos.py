import streamlit as st
from datetime import datetime, timedelta
import calendar
import re
from collections import defaultdict
from .utils import normalize_phone
import io  # ← NOVO: Para exportação Excel
import pandas as pd  # ← NOVO: Para exportação Excel

============================================================================
✅ FUNÇÃO AUXILIAR: Cache de Condomínios (igual ao followup)
============================================================================
def get_condominios_com_contagem_agendamentos(clientes_collection, forcar_atualizacao=False):
    """
    Retorna lista de condomínios com contagem de clientes agendados, usando cache.
    Cache válido por 5 minutos para evitar queries excessivas no banco.
    """
    cache_key = "condominios_cache_agendamentos"
    cache_timestamp_key = "condominios_cache_timestamp_agendamentos"
    CACHE_EXPIRY_SECONDS = 300  # 5 minutos
    agora = datetime.now()

    precisa_atualizar = forcar_atualizacao

    if not precisa_atualizar:
        if cache_key not in st.session_state or cache_timestamp_key not in st.session_state:
            precisa_atualizar = True
        else:
            cache_timestamp = st.session_state.get(cache_timestamp_key, datetime.min)
            if (agora - cache_timestamp).total_seconds() > CACHE_EXPIRY_SECONDS:
                precisa_atualizar = True

    if precisa_atualizar:
        try:
            pipeline = [
                {
                    "$match": {
                        "seguiu_ativacao": "Sim",
                        "retorno_agendado": {"$exists": True, "$ne": None, "$ne": ""},
                        "condominio_nome": {"$ne": None, "$ne": ""}
                    }
                },
                {
                    "$group": {
                        "_id": "$condominio_nome",
                        "count": {"$sum": 1}
                    }
                },
                {"$sort": {"_id": 1}}
            ]
            
            resultados = list(clientes_collection.aggregate(pipeline))
            
            condominios_formatados = {}
            for r in resultados:
                nome = r["_id"]
                count = r["count"]
                condominios_formatados[f"{nome} ({count})"] = nome
            
            condominios_formatados = dict(sorted(condominios_formatados.items()))
            
            opcoes_finais = {"Todos": "Todos"}
            opcoes_finais.update(condominios_formatados)
            
            st.session_state[cache_key] = opcoes_finais
            st.session_state[cache_timestamp_key] = agora
            
            return opcoes_finais
            
        except Exception as e:
            st.error(f"❌ Erro ao buscar condomínios: {e}")
            return {"Todos": "Todos"}

    return st.session_state.get(cache_key, {"Todos": "Todos"})

============================================================================
✅ FUNÇÃO PRINCIPAL: render_agendamentos
============================================================================
def render_agendamentos(clientes_collection):
    st.markdown("## 📅 Agendamentos")
    # Abas — incluindo nova aba para indicações de embaixadores e revendas
    tab_pool, tab_indicacoes_emb, tab_indicacoes_rev, tab_agendados, tab_calendario = st.tabs([
        "🏊‍️ Pool (Sem Agendamento)",
        "🌟 Pool de Indicações (Embaixadores)",
        "🏪 Pool de Indicações (Revendas)",
        "✅ Agendados",
        "📅 Calendário Mensal"
    ])

    with tab_pool:
        mostrar_pool(clientes_collection)

    with tab_indicacoes_emb:
        mostrar_pool_embaixadores(clientes_collection)

    with tab_indicacoes_rev:
        mostrar_pool_revendas(clientes_collection)

    with tab_agendados:
        mostrar_agendados(clientes_collection)

    with tab_calendario:
        mostrar_calendario(clientes_collection)

============================================================================
✅ FUNÇÃO: mostrar_pool (Clientes sem agendamento)
============================================================================
def mostrar_pool(clientes_collection):
    st.subheader("📋 Clientes que seguiram para ativação (sem agendamento)")
    query = {
        "seguiu_ativacao": "Sim",
        "$or": [
            {"retorno_agendado": {"$exists": False}},
            {"retorno_agendado": {"$in": [None, ""]}},
            {"retorno_agendado": {"$not": {"$regex": r"^\d{4}-\d{2}-\d{2}$"}}}
        ]
    }
    clientes = list(clientes_collection.find(query))
    pool_valido = []
    for c in clientes:
        data = c.get("retorno_agendado")
        if not data or not isinstance(data, str) or len(data) != 10 or data[4] != '-' or data[7] != '-':
            pool_valido.append(c)

    if not pool_valido:
        st.info("✅ Todos os clientes já estão agendados!")
        return

    for cliente in pool_valido:
        with st.expander(f"📞 {cliente['nome_completo']} - {cliente['celular']}", expanded=False):
            col1, col2 = st.columns([2, 1])
            with col1:
                st.write(f"**Origem:** {cliente.get('origem', 'N/A')}")
                st.write(f"**Plano:** {cliente.get('plano_escolhido', 'N/A')}")
                st.write(f"**Cadastrado por:** {cliente.get('cadastrado_por', 'N/A')}")
                
                # 🏢 Exibir informações de condomínio
                if cliente.get("condominio_nome"):
                    st.write(f"**Condomínio:** {cliente.get('condominio_nome', 'N/A')}")
                if cliente.get("bloco") or cliente.get("apartamento"):
                    bloco = cliente.get("bloco", "")
                    apto = cliente.get("apartamento", "")
                    unidade_parts = []
                    if bloco:
                        unidade_parts.append(f"Bloco {bloco}")
                    if apto:
                        unidade_parts.append(f"Apto {apto}")
                    if unidade_parts:
                        st.write(f"**Unidade:** {' / '.join(unidade_parts)}")
                
                if cliente.get("observacoes"):
                    st.write(f"**Observações:** {cliente['observacoes']}")
            
            with col2:
                data_agendamento = st.date_input(
                    "Agendar para:  ",
                    min_value=datetime.today().date(),
                    key=f"data_{cliente['_id']}"
                )
                periodo = st.selectbox(
                    "Período:  ",
                    ["Selecione...", "Horário Comercial", "Manhã", "Tarde"],
                    index=0,
                    key=f"periodo_{cliente['_id']}"
                )
                
                observacao_agendamento = st.text_input(
                    "📝 Observações específicas:  ",
                    placeholder="Ex: Após 14 horas, Cliente em casa até 15h, etc.  ",
                    key=f"obs_{cliente['_id']}"
                )
                
                contrato_titular = st.checkbox(
                    "✅ Contrato deverá ser assinado obrigatoriamente pelo Titular  ",
                    key=f"contrato_{cliente['_id']}"
                )
                
                if st.button("✅ Agendar", key=f"agendar_{cliente['_id']}"):
                    if periodo == "Selecione...":
                        st.error("⚠️ Selecione um período!")
                        continue
                    
                    try:
                        clientes_collection.update_one(
                            {"_id": cliente["_id"]},
                            {"$set": {
                                "retorno_agendado": data_agendamento.isoformat(),
                                "periodo": periodo,
                                "observacoes_agendamento": observacao_agendamento.strip() if observacao_agendamento else None,
                                "contrato_titular": contrato_titular,
                                "ativo": False,
                                "reagendado_para": None
                            }}
                        )
                        st.success(f"✅ {cliente['nome_completo']} agendado para {data_agendamento.strftime('%d/%m/%Y')} ({periodo})!")
                        st.rerun()
                    except Exception as e:
                        st.error(f"❌ Erro ao agendar: {e}")

============================================================================
✅ FUNÇÃO: mostrar_agendados (COM FILTRO DE CONDOMÍNIO + ORDENAÇÃO)
============================================================================
def mostrar_agendados(clientes_collection):
    st.subheader("📅 Clientes Agendados")
    # 🏢 NOVO: Filtros de Condomínio e Ordenação
    col_filtro1, col_filtro2, col_filtro3 = st.columns([2, 2, 1])

    with col_filtro1:
        filtro_data_inicio = st.date_input(
            "📅 Data início:  ",
            value=datetime.today().date(),
            key="agend_filtro_data_inicio"
        )

    with col_filtro2:
        filtro_data_fim = st.date_input(
            "📅 Data fim:  ",
            value=datetime.today().date() + timedelta(days=7),
            key="agend_filtro_data_fim"
        )

    with col_filtro3:
        # Botão atualizar cache
        if st.button("🔄", key="btn_atualizar_cond_agend", help="Atualizar lista de condomínios"):
            if "condominios_cache_agendamentos" in st.session_state:
                del st.session_state["condominios_cache_agendamentos"]
            if "condominios_cache_timestamp_agendamentos" in st.session_state:
                del st.session_state["condominios_cache_timestamp_agendamentos"]
            st.rerun()
        
        condominios_opcoes = get_condominios_com_contagem_agendamentos(clientes_collection)
        opcoes_display = list(condominios_opcoes.keys())
        
        filtro_condominio = st.multiselect(
            "🏢 Condomínio:  ",
            options=opcoes_display,
            default=["Todos"] if "Todos" in opcoes_display else [],
            key="agend_filtro_condominio"
        )

    # 🔀 Ordenação
    ordenacao = st.selectbox(
        "Ordenar por:  ",
        options=["Data de agendamento", "Condomínio + Data", "Nome do cliente", "Cadastrado por"],
        index=0,
        key="agend_ordenacao"
    )

    # Query base
    query = {
        "seguiu_ativacao": "Sim",
        "retorno_agendado": {"$exists": True, "$ne": None, "$ne": ""}
    }

    # Filtro de data
    query["retorno_agendado"] = {
        "$gte": filtro_data_inicio.strftime("%Y-%m-%d"),
        "$lte": filtro_data_fim.strftime("%Y-%m-%d")
    }

    # 🏢 Filtro de condomínio
    if filtro_condominio and "Todos" not in filtro_condominio:
        condominios_selecionados = []
        for opcao in filtro_condominio:
            nome_real = condominios_opcoes.get(opcao, opcao)
            if nome_real != "Todos":
                condominios_selecionados.append(nome_real)
        
        if condominios_selecionados:
            query["condominio_nome"] = {"$in": condominios_selecionados}

    clientes = list(clientes_collection.find(query))

    # Validação de data
    clientes_validos = []
    for c in clientes:
        data = c.get("retorno_agendado")
        if isinstance(data, str) and len(data) == 10 and data[4] == '-' and data[7] == '-':
            try:
                datetime.fromisoformat(data)
                clientes_validos.append(c)
            except ValueError:
                continue

    if not clientes_validos:
        st.info("🚫 Nenhum cliente agendado com data válida no período selecionado.")
        return

    # 🔀 Ordenação
    if ordenacao == "Data de agendamento":
        clientes_validos.sort(key=lambda x: x.get("retorno_agendado", ""))
    elif ordenacao == "Condomínio + Data":
        clientes_validos.sort(key=lambda x: (
            x.get("condominio_nome", "") or "ZZZ",
            x.get("retorno_agendado", "")
        ))
    elif ordenacao == "Nome do cliente":
        clientes_validos.sort(key=lambda x: x.get("nome_completo", ""))
    elif ordenacao == "Cadastrado por":
        clientes_validos.sort(key=lambda x: x.get("cadastrado_por", ""))

    # 🏢 Agrupamento por condomínio (se ordenado por condomínio)
    if ordenacao == "Condomínio + Data":
        from itertools import groupby
        
        st.markdown("### 📍 Agrupado por Condomínio")
        
        for condominio, group in groupby(clientes_validos, key=lambda x: x.get("condominio_nome", "Sem Condomínio")):
            group_list = list(group)
            
            if condominio:
                st.markdown(f"#### 🏢 **{condominio}** ({len(group_list)} agendamento(s))")
            else:
                st.markdown(f"#### 📍 **Sem Condomínio** ({len(group_list)} agendamento(s))")
            
            for cliente in group_list:
                _render_cliente_agendado(cliente, clientes_collection)
            
            st.divider()
    else:
        for cliente in clientes_validos:
            _render_cliente_agendado(cliente, clientes_collection)

============================================================================
✅ FUNÇÃO AUXILIAR: Renderizar cliente agendado
============================================================================
def _render_cliente_agendado(cliente, clientes_collection):
    """Renderiza um único cliente agendado (código extraído para reuso)"""
    data_agendada = cliente["retorno_agendado"]
    try:
        data_formatada = datetime.fromisoformat(data_agendada).strftime("%d/%m/%Y")
    except Exception:
        return
    
    status_agendamento = cliente.get("status_agendamento", "agendado")
    status_exibicao = {
        "ativado": "✅ Ativado",
        "cancelado": "❌ Cancelado",
        "agendado": "⏳ Agendado"
    }.get(status_agendamento, "⚠️ Desconhecido")

    with st.expander(f"📅 {data_formatada} - {cliente['nome_completo']} ({status_exibicao})", expanded=False):
        col1, col2 = st.columns([2, 1])
        with col1:
            st.write(f"**Celular:** {cliente['celular']}")
            st.write(f"**Origem:** {cliente.get('origem', 'N/A')}")
            st.write(f"**Plano:** {cliente.get('plano_escolhido', 'N/A')}")
            st.write(f"**Cadastrado por:** {cliente.get('cadastrado_por', 'N/A')}")
            
            # 🏢 Informações de condomínio (DESTAQUE)
            if cliente.get("condominio_nome"):
                st.info(f"🏢 **Condomínio:** {cliente.get('condominio_nome', 'N/A')}")
            
            if cliente.get("bloco") or cliente.get("apartamento"):
                bloco = cliente.get("bloco", "")
                apto = cliente.get("apartamento", "")
                unidade_parts = []
                if bloco:
                    unidade_parts.append(f"Bloco {bloco}")
                if apto:
                    unidade_parts.append(f"Apto {apto}")
                if unidade_parts:
                    st.info(f"📍 **Unidade:** {' / '.join(unidade_parts)}")
            
            if cliente.get("observacoes"):
                st.write(f"**Observações:** {cliente['observacoes']}")
            
            periodo = cliente.get("periodo", "Não definido")
            st.write(f"**Período:** {periodo}")
            
            if cliente.get("observacoes_agendamento"):
                st.info(f"📝 **Obs. Agendamento:** {cliente['observacoes_agendamento']}")
            
            if cliente.get("contrato_titular"):
                st.warning("⚠️ **Contrato deve ser assinado pelo TITULAR**")
            
            reagendado_para = cliente.get("reagendado_para")
            if reagendado_para:
                st.write(f"**Reagendado para:** {reagendado_para}")
            
            if status_agendamento == "cancelado":
                motivo = cliente.get("motivo_cancelamento", "Não informado")
                st.write(f"**Motivo do Cancelamento:** {motivo}")
        
        with col2:
            # Botão Ativar
            if status_agendamento == "agendado":
                if st.button("✅ Ativar", key=f"ativar_{cliente['_id']}"):
                    try:
                        clientes_collection.update_one(
                            {"_id": cliente["_id"]},
                            {"$set": {
                                "status_agendamento": "ativado",
                                "ativo": True,
                                "data_ativacao": datetime.now()
                            }}
                        )
                        st.success(f"✅ {cliente['nome_completo']} ativado!")
                        st.rerun()
                    except Exception as e:
                        st.error(f"❌ Erro ao ativar: {e}")

            # Botão Cancelar
            if status_agendamento != "cancelado":
                motivo_atual = cliente.get("motivo_cancelamento", "")
                motivo_cancelamento = st.text_input(
                    "Motivo do cancelamento:  ",
                    value=motivo_atual,
                    key=f"motivo_{cliente['_id']}",
                    placeholder="Ex: Não atendeu o horário"
                )
                if st.button("🚫 Cancelar", key=f"cancelar_{cliente['_id']}"):
                    if not motivo_cancelamento.strip():
                        st.error("⚠️ Informe o motivo do cancelamento.")
                    else:
                        try:
                            clientes_collection.update_one(
                                {"_id": cliente["_id"]},
                                {"$set": {
                                    "status_agendamento": "cancelado",
                                    "motivo_cancelamento": motivo_cancelamento.strip(),
                                    "data_cancelamento": datetime.now(),
                                    "ativo": False
                                }}
                            )
                            st.success(f"✅ Agendamento de {cliente['nome_completo']} cancelado.")
                            st.rerun()
                        except Exception as e:
                            st.error(f"❌ Erro ao cancelar: {e}")

============================================================================
✅ FUNÇÃO: mostrar_calendario (COM FILTRO DE CONDOMÍNIO + EXPORTAÇÃO EXCEL)
============================================================================
def mostrar_calendario(clientes_collection):
    st.subheader("🗓️ Calendário Mensal de Agendamentos")
    # Estado para controlar o mês visualizado (persistente)
    if "mes_visualizado_agendamento" not in st.session_state:
        st.session_state.mes_visualizado_agendamento = datetime.now().replace(day=1).date()

    mes_atual = st.session_state.mes_visualizado_agendamento
    ano = mes_atual.year
    mes = mes_atual.month

    # Navegação de mês
    col_prev, col_title, col_next = st.columns([1, 3, 1])
    with col_prev:
        if st.button("<< Mês Anterior", key="prev_mes_agend"):
            novo_mes = mes_atual.replace(day=1) - timedelta(days=1)
            st.session_state.mes_visualizado_agendamento = novo_mes.replace(day=1)
            st.rerun()

    with col_title:
        st.markdown(f"### {calendar.month_name[mes].capitalize()} {ano}")

    with col_next:
        if st.button("Mês Próximo >>", key="prox_mes_agend"):
            proximo = mes_atual.replace(day=28) + timedelta(days=4)
            st.session_state.mes_visualizado_agendamento = proximo.replace(day=1)
            st.rerun()

    # Legenda visual
    st.caption(
        "🎨 Legendas:  "
        "⚪ Sem agendamento |  "
        "🟢 ≤2 |  "
        "🟡 3–5 |  "
        "🟠 6–10 |  "
        "🔴 ≥11 |  "
        "❗ Dias vencidos com agendamento pendente"
    )

    # 🏢 NOVO: Filtro de Condomínio no calendário
    col_cal1, col_cal2 = st.columns([3, 1])

    with col_cal1:
        # Seletor de data existente
        pass

    with col_cal2:
        # Botão atualizar cache
        if st.button("🔄 Atualizar", key="btn_atualizar_cond_cal", help="Atualizar lista de condomínios"):
            if "condominios_cache_agendamentos" in st.session_state:
                del st.session_state["condominios_cache_agendamentos"]
            if "condominios_cache_timestamp_agendamentos" in st.session_state:
                del st.session_state["condominios_cache_timestamp_agendamentos"]
            st.rerun()
        
        condominios_opcoes = get_condominios_com_contagem_agendamentos(clientes_collection)
        opcoes_display = list(condominios_opcoes.keys())
        
        filtro_condominio_cal = st.multiselect(
            "🏢 Filtrar por condomínio:  ",
            options=opcoes_display,
            default=["Todos"] if "Todos" in opcoes_display else [],
            key="calendario_filtro_condominio"
        )

    # Buscar agendamentos do mês
    inicio_mes = datetime(ano, mes, 1)
    fim_mes = datetime(ano, mes, calendar.monthrange(ano, mes)[1])
    query_agendamentos = {
        "seguiu_ativacao": "Sim",
        "retorno_agendado": {
            "$gte": inicio_mes.strftime("%Y-%m-%d"),
            "$lte": fim_mes.strftime("%Y-%m-%d")
        }
    }

    # 🏢 Aplicar filtro de condomínio na query do calendário
    if filtro_condominio_cal and "Todos" not in filtro_condominio_cal:
        condominios_selecionados = []
        for opcao in filtro_condominio_cal:
            nome_real = condominios_opcoes.get(opcao, opcao)
            if nome_real != "Todos":
                condominios_selecionados.append(nome_real)
        
        if condominios_selecionados:
            query_agendamentos["condominio_nome"] = {"$in": condominios_selecionados}

    todos_agendados = list(clientes_collection.find(query_agendamentos))

    agenda_por_dia = defaultdict(list)
    for cliente in todos_agendados:
        data = cliente.get("retorno_agendado")
        if isinstance(data, str) and data:
            agenda_por_dia[data].append(cliente)

    # Gerar calendário
    cal = calendar.monthcalendar(ano, mes)
    dias_da_semana = ["Seg", "Ter", "Qua", "Qui", "Sex", "Sáb", "Dom"]

    # Cabeçalho
    cols_header = st.columns(7)
    for i, dia in enumerate(dias_da_semana):
        cols_header[i].markdown(
            f"<div style='font-weight: bold; text-align: center; padding: 8px;'>{dia}</div>",
            unsafe_allow_html=True
        )

    hoje_date = datetime.now().date()

    # Corpo do calendário
    for semana in cal:
        cols = st.columns(7)
        for i, dia_num in enumerate(semana):
            if dia_num == 0:
                cols[i].markdown("<div style='height: 70px;'></div>", unsafe_allow_html=True)
                continue

            data = datetime(ano, mes, dia_num).date()
            data_str = data.strftime("%Y-%m-%d")
            qtd = len(agenda_por_dia.get(data_str, []))

            # Cores por faixa
            if qtd == 0:
                cor = "#f8f9fa"
                texto = str(dia_num)
            elif qtd <= 2:
                cor = "#d4edda"
                texto = f"{dia_num}<br/>({qtd})"
            elif qtd <= 5:
                cor = "#fff3cd"
                texto = f"{dia_num}<br/>({qtd})"
            elif qtd <= 10:
                cor = "#ffeacc"
                texto = f"{dia_num}<br/>({qtd})"
            else:
                cor = "#f8d7da"
                texto = f"{dia_num}<br/>({qtd})"

            # Destaque para dias vencidos com agendamento
            borda = ""
            icone = ""
            if data < hoje_date and qtd > 0:
                borda = "border: 2px solid #e74c3c;"
                icone = "❗ "

            estilo = (
                f"background-color: {cor};  "
                f"padding: 12px 6px;  "
                f"border-radius: 8px;  "
                f"text-align: center;  "
                f"font-weight: bold;  "
                f"font-size: 15px;  "
                f"box-shadow: 0 2px 4px rgba(0,0,0,0.06);  "
                f"{borda}"
            )
            html_celula = f"<div style='{estilo}'>{icone}{texto}</div>"
            cols[i].markdown(html_celula, unsafe_allow_html=True)

            # Botão "👁️"
            if qtd > 0:
                if cols[i].button("👁️", key=f"olho_agend_{data_str}", use_container_width=True):
                    st.session_state["data_selecionada_agendamento"] = data
                    st.rerun()

    st.markdown("---")

    # Seleção de data
    data_selecionada = st.date_input(
        "Selecione um dia para ver os agendamentos:  ",
        value=st.session_state.get("data_selecionada_agendamento", datetime.now().date()),
        min_value=datetime(2020, 1, 1),
        key="data_selecionada_agendamento"
    )
    data_str = data_selecionada.strftime("%Y-%m-%d")
    clientes_do_dia = agenda_por_dia.get(data_str, [])

    if clientes_do_dia:
        st.markdown(f"### 👥 Agendamentos em {data_selecionada.strftime('%d/%m/%Y')}")

        # ==================== EXPORTAÇÃO TEXTO (EXISTENTE) ====================
        texto_exportacao = ""
        for cliente in clientes_do_dia:
            nome = cliente.get("nome_completo", "Nome não disponível")
            endereco = cliente.get("endereco", "Endereço não informado")
            numero = cliente.get("numero", "")
            complemento = cliente.get("complemento", "")
            bairro = cliente.get("bairro", "")
            cidade = cliente.get("cidade", "")
            ponto_referencia = cliente.get("ponto_referencia", "")
            plano_completo = cliente.get("plano_escolhido", "Plano não informado")
            celular = cliente.get("celular", "Telefone não informado")
            periodo = cliente.get("periodo", "Período não definido")
            ativo = cliente.get("ativo", False)
            reagendado_para = cliente.get("reagendado_para", "")
            status_agendamento = cliente.get("status_agendamento", "agendado")

            plano_limpo = re.sub(r'\s*R\$.*', '', plano_completo).strip()
            endereco_completo = f"{endereco}, {numero}"
            if complemento:
                endereco_completo += f" - {complemento}"
            if bairro:
                endereco_completo += f" - {bairro}"
            if cidade:
                endereco_completo += f" - {cidade}"

            # 🏢 Incluir informações de condomínio no endereço
            if cliente.get("condominio_nome"):
                endereco_completo += f" - {cliente.get('condominio_nome')}"
            if cliente.get("bloco") or cliente.get("apartamento"):
                bloco = cliente.get("bloco", "")
                apto = cliente.get("apartamento", "")
                if bloco:
                    endereco_completo += f" - Bloco {bloco}"
                if apto:
                    endereco_completo += f" - Apto {apto}"

            status_exib = {
                "ativado": "✅ Ativado",
                "cancelado": "❌ Cancelado",
                "agendado": "⏳ Agendado"
            }.get(status_agendamento, "⚠️ Desconhecido")

            texto_exportacao += (
                f"📞 {nome} | {status_exib}\n"
                f"📱 {celular}\n"
                f"🏠 {endereco_completo}\n"
                f"📍 Ref: {ponto_referencia}\n"
                f"📋 Plano: {plano_limpo}\n"
                f"⏰ Período: {periodo}\n"
            )
            
            if cliente.get("observacoes_agendamento"):
                texto_exportacao += f"📝 Obs: {cliente['observacoes_agendamento']}\n"
            
            if cliente.get("contrato_titular"):
                texto_exportacao += "⚠️ CONTRATO DEVE SER ASSINADO PELO TITULAR\n"
            
            texto_exportacao += (
                f"{'🔄 Reagendado para: ' + reagendado_para if reagendado_para else ''}\n"
                f"---\n"
            )

        # ==================== EXPORTAÇÃO EXCEL (NOVO) ====================
        # Preparar dados para Excel
        dados_excel = []
        
        for cliente in clientes_do_dia:
            # Extrair período e observações
            periodo = cliente.get("periodo", "Não definido")
            obs_agendamento = cliente.get("observacoes_agendamento", "")
            horario_obs = f"{periodo}"
            if obs_agendamento:
                horario_obs += f" - {obs_agendamento}"
            
            # Extrair informações de condomínio/unidade
            condominio = cliente.get("condominio_nome", "")
            bloco = cliente.get("bloco", "")
            apartamento = cliente.get("apartamento", "")
            
            # Limpar plano (remover valor R$)
            plano_completo = cliente.get("plano_escolhido", "Plano não informado")
            plano_limpo = re.sub(r'\s*R\$.*', '', plano_completo).strip()
            
            dados_excel.append({
                "Condomínio": condominio,
                "Bloco": bloco,
                "Apartamento": apartamento,
                "Horário e Obs": horario_obs,
                "Plano": plano_limpo,
                "Telefone": cliente.get("celular", "Telefone não informado"),
                "Nome do Cliente": cliente.get("nome_completo", "Nome não disponível")
            })
        
        # Criar DataFrame e converter para Excel
        df = pd.DataFrame(dados_excel)
        
        # Reordenar colunas conforme solicitado
        df = df[["Condomínio", "Bloco", "Apartamento", "Horário e Obs", "Plano", "Telefone", "Nome do Cliente"]]
        
        # Criar buffer em memória para o arquivo Excel
        output = io.BytesIO()
        
        with pd.ExcelWriter(output, engine='openpyxl') as writer:
            df.to_excel(writer, index=False, sheet_name='Agendamentos')
            
            # Ajustar largura das colunas
            worksheet = writer.sheets['Agendamentos']
            column_widths = [15, 8, 8, 25, 20, 15, 30]
            for i, width in enumerate(column_widths):
                col_letter = chr(65 + i)  # A, B, C, D, E, F, G
                worksheet.column_dimensions[col_letter].width = width
        
        output.seek(0)

        # ==================== BOTÕES DE EXPORTAÇÃO (LADO A LADO) ====================
        col_txt, col_xlsx = st.columns(2)

        with col_txt:
            st.download_button(
                label="📋 Exportar TXT",
                data=texto_exportacao,
                file_name=f"agendamentos_{data_selecionada.strftime('%Y-%m-%d')}.txt",
                mime="text/plain",
                key=f"copiar_agendamentos_{data_str}"
            )

        with col_xlsx:
            st.download_button(
                label="📊 Exportar Excel (.xlsx)",
                data=output.getvalue(),
                file_name=f"agendamentos_{data_selecionada.strftime('%Y-%m-%d')}.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                key=f"exportar_excel_{data_str}"
            )

        # Exibir clientes
        for cliente in clientes_do_dia:
            status_agendamento = cliente.get("status_agendamento", "agendado")
            status_exibicao = {
                "ativado": "✅ Ativado",
                "cancelado": "❌ Cancelado",
                "agendado": "⏳ Agendado"
            }.get(status_agendamento, "⚠️ Desconhecido")

            with st.expander(f"📞 {cliente['nome_completo']} - {cliente['celular']} ({status_exibicao})", expanded=False):
                nome = cliente.get("nome_completo", "Nome não disponível")
                endereco = cliente.get("endereco", "Endereço não informado")
                numero = cliente.get("numero", "")
                complemento = cliente.get("complemento", "")
                bairro = cliente.get("bairro", "")
                cidade = cliente.get("cidade", "")
                ponto_referencia = cliente.get("ponto_referencia", "")
                plano_completo = cliente.get("plano_escolhido", "Plano não informado")
                celular = cliente.get("celular", "Telefone não informado")
                periodo = cliente.get("periodo", "Período não definido")
                ativo = cliente.get("ativo", False)
                reagendado_para = cliente.get("reagendado_para", "")

                plano_limpo = re.sub(r'\s*R\$.*', '', plano_completo).strip()
                endereco_completo = f"{endereco}, {numero}"
                if complemento:
                    endereco_completo += f" - {complemento}"
                if bairro:
                    endereco_completo += f" - {bairro}"
                if cidade:
                    endereco_completo += f" - {cidade}"
                
                # 🏢 Incluir informações de condomínio
                if cliente.get("condominio_nome"):
                    endereco_completo += f" - {cliente.get('condominio_nome')}"
                if cliente.get("bloco") or cliente.get("apartamento"):
                    bloco = cliente.get("bloco", "")
                    apto = cliente.get("apartamento", "")
                    if bloco:
                        endereco_completo += f" - Bloco {bloco}"
                    if apto:
                        endereco_completo += f" - Apto {apto}"

                st.markdown(f"""
                **Cliente:** {nome}  
                **Endereço:** {endereco_completo}  
                **Referência:** {ponto_referencia}  
                **Plano:** {plano_limpo}  
                **Telefone:** {celular}  
                **Período:** {periodo}  
                **Status Ativado:** {'✅ Sim' if ativo else '❌ Não'}  
                """)

                # 🏢 Exibir condomínio separadamente se existir
                if cliente.get("condominio_nome"):
                    st.info(f"🏢 **Condomínio:** {cliente.get('condominio_nome')}")
                    if cliente.get("bloco") or cliente.get("apartamento"):
                        bloco = cliente.get("bloco", "")
                        apto = cliente.get("apartamento", "")
                        unidade_parts = []
                        if bloco:
                            unidade_parts.append(f"Bloco {bloco}")
                        if apto:
                            unidade_parts.append(f"Apto {apto}")
                        if unidade_parts:
                            st.info(f"📍 **Unidade:** {' / '.join(unidade_parts)}")

                if cliente.get("observacoes_agendamento"):
                    st.info(f"📝 **Observações:** {cliente['observacoes_agendamento']}")
                
                if cliente.get("contrato_titular"):
                    st.warning("⚠️ **Contrato deve ser assinado pelo TITULAR**")

                # Checkbox "Ativado"
                novo_status_ativo = st.checkbox(
                    "✅ Marcar como Ativado",
                    value=ativo,
                    key=f"ativo_{cliente['_id']}"
                )
                if novo_status_ativo != ativo:
                    try:
                        update_fields = {"ativo": novo_status_ativo}
                        if novo_status_ativo:
                            update_fields["status_agendamento"] = "ativado"
                            update_fields["data_ativacao"] = datetime.now()
                        else:
                            update_fields["status_agendamento"] = "agendado"
                            update_fields.pop("data_ativacao", None)

                        clientes_collection.update_one(
                            {"_id": cliente["_id"]},
                            {"$set": update_fields}
                        )
                        st.success(f"✅ Status de '{nome}' atualizado.")
                        st.rerun()
                    except Exception as e:
                        st.error(f"❌ Erro ao atualizar: {e}")

                # Reagendar
                col_reag_data, col_reag_periodo, col_reag_obs, col_btn = st.columns([2, 2, 2, 1])
                
                with col_reag_data:
                    nova_data = st.date_input(
                        "Reagendar para:  ",
                        min_value=datetime.today().date(),
                        key=f"reag_{cliente['_id']}"
                    )
                
                with col_reag_periodo:
                    periodo_atual = cliente.get("periodo", "Selecione...")
                    opcoes = ["Selecione...", "Horário Comercial", "Manhã", "Tarde"]
                    index_inicial = opcoes.index(periodo_atual) if periodo_atual in opcoes else 0
                    novo_periodo = st.selectbox(
                        "Período:  ",
                        opcoes,
                        index=index_inicial,
                        key=f"periodo_reag_{cliente['_id']}"
                    )
                
                with col_reag_obs:
                    obs_atual = cliente.get("observacoes_agendamento", "")
                    nova_observacao = st.text_input(
                        "📝 Observações:  ",
                        value=obs_atual,
                        placeholder="Ex: Após 14h",
                        key=f"reag_obs_{cliente['_id']}"
                    )
                    contrato_atual = cliente.get("contrato_titular", False)
                    novo_contrato_titular = st.checkbox(
                        "✅ Contrato Titular",
                        value=contrato_atual,
                        key=f"reag_contrato_{cliente['_id']}"
                    )
                
                with col_btn:
                    if st.button("🔄 Reagendar", key=f"reagendar_{cliente['_id']}"):
                        if novo_periodo == "Selecione...":
                            st.error("⚠️ Selecione um período!")
                        else:
                            try:
                                clientes_collection.update_one(
                                    {"_id": cliente["_id"]},
                                    {"$set": {
                                        "reagendado_para": nova_data.isoformat(),
                                        "retorno_agendado": nova_data.isoformat(),
                                        "periodo": novo_periodo,
                                        "observacoes_agendamento": nova_observacao.strip() if nova_observacao else None,
                                        "contrato_titular": novo_contrato_titular
                                    }}
                                )
                                st.success(f"✅ {nome} reagendado para {nova_data.strftime('%d/%m/%Y')} ({novo_periodo})!")
                                st.rerun()
                            except Exception as e:
                                st.error(f"❌ Erro: {e}")

                # Cancelar
                if status_agendamento != "cancelado":
                    motivo_atual = cliente.get("motivo_cancelamento", "")
                    motivo_cancelamento = st.text_input(
                        "Motivo do cancelamento:  ",
                        value=motivo_atual,
                        key=f"motivo_cal_{cliente['_id']}",
                        placeholder="Ex: Cliente desistiu"
                    )
                    if st.button("🚫 Cancelar", key=f"cancelar_cal_{cliente['_id']}"):
                        if not motivo_cancelamento.strip():
                            st.error("⚠️ Informe o motivo.")
                        else:
                            try:
                                clientes_collection.update_one(
                                    {"_id": cliente["_id"]},
                                    {"$set": {
                                        "status_agendamento": "cancelado",
                                        "motivo_cancelamento": motivo_cancelamento.strip(),
                                        "data_cancelamento": datetime.now(),
                                        "ativo": False
                                    }}
                                )
                                st.success(f"✅ Agendamento de {nome} cancelado.")
                                st.rerun()
                            except Exception as e:
                                st.error(f"❌ Erro: {e}")

    else:
        st.info("📭 Nenhum agendamento para este dia.")

============================================================================
✅ FUNÇÃO: mostrar_pool_embaixadores (mantida original)
============================================================================
def mostrar_pool_embaixadores(clientes_collection):
    st.subheader("🌟 Indicações de Embaixadores")
    def determinar_status_embaixador(cliente):
        status_agendamento = cliente.get("status_agendamento")

        if status_agendamento == "ativado":
            return "Ativado"
        elif status_agendamento == "cancelado":
            return "Cancelado"
        elif status_agendamento == "agendado":
            return "Agendado"
        elif cliente.get("reagendado_para") and status_agendamento not in ["ativado", "cancelado"]:
            return "Reagendado"
        elif cliente.get("em_tratamento") is True:
            return "Em tratamento"
        elif cliente.get("seguiu_ativacao") == "Sim":
            return "Seguiu para ativação"
        else:
            return "Indicado"

    col_btn, col_space = st.columns([2, 8])
    with col_btn:
        if st.button("🔄 Atualizar", help="Recarrega os dados do banco para refletir alterações recentes"):
            st.rerun()

    todos_indicados = list(clientes_collection.find({"indicado_por.tipo": "embaixador"}))

    # Correção proativa de status
    updated_count = 0
    for c in todos_indicados:
        status_ag = c.get("status_agendamento")
        em_trat = c.get("em_tratamento", False)
        _id = c["_id"]

        if status_ag in ["ativado", "cancelado"] and em_trat is True:
            try:
                clientes_collection.update_one(
                    {"_id": _id},
                    {"$set": {"em_tratamento": False}}
                )
                c["em_tratamento"] = False
                updated_count += 1
            except Exception as e:
                st.warning(f"⚠️ Não foi possível corrigir inconsistência para {c.get('nome_completo', '?')}: {e}")

    if updated_count > 0:
        st.info(f"✅ Corrigidas {updated_count} inconsistências de status.")

    if not todos_indicados:
        st.info("✅ Nenhuma indicação de embaixador registrada ainda.")
        return

    hoje = datetime.now()

    status_groups = defaultdict(list)
    atrasadas_ids = set()

    for c in todos_indicados:
        status = determinar_status_embaixador(c)
        status_groups[status].append(c)

        if status == "Indicado":
            data_ind = c.get("data_indicacao")
            if data_ind:
                try:
                    if isinstance(data_ind, str):
                        data_ind_dt = datetime.fromisoformat(data_ind)
                    elif isinstance(data_ind, datetime):
                        data_ind_dt = data_ind
                    else:
                        continue
                    if (hoje - data_ind_dt) > timedelta(days=7):
                        atrasadas_ids.add(str(c["_id"]))
                except Exception:
                    pass

    aguardando = ["Indicado"]
    em_fluxo = ["Em tratamento", "Seguiu para ativação", "Agendado", "Reagendado"]
    concluidos = ["Ativado", "Cancelado"]

    total = len(todos_indicados)
    total_concluidos = sum(len(status_groups[s]) for s in concluidos)
    total_fluxo = sum(len(status_groups[s]) for s in em_fluxo)
    total_indicado = len(status_groups["Indicado"])
    atrasadas_count = len(atrasadas_ids)

    st.markdown(f"""
    📊 **Resumo Geral**  
    Total: {total} | 
    ⚪ Aguardando início (indicado): {total_indicado - atrasadas_count} | 
    🟡 Em fluxo (em tratamento/agendado/etc.): {total_fluxo} | 
    ✅ Concluídos (ativado/cancelado): {total_concluidos} | 
    ⚠️ Atrasadas (>7d sem tratamento): {atrasadas_count}
    """)

    # --- ⚪ SEÇÃO 1: AGUARDANDO INÍCIO DO TRATAMENTO ---
    st.markdown("### ⚪ Aguardando Início do Tratamento")
    st.markdown("<div style='border: 2px solid #ddd; border-radius: 8px; padding: 16px; background-color: #fafafa;'>", unsafe_allow_html=True)

    aguardando_normal = []
    atrasadas = []
    for cliente in status_groups.get("Indicado", []):
        if str(cliente["_id"]) in atrasadas_ids:
            atrasadas.append(cliente)
        else:
            aguardando_normal.append(cliente)

    if atrasadas:
        st.markdown("#### ⚠️ Atrasadas (+7 dias sem tratamento)")
        for cliente in sorted(atrasadas, key=lambda x: x.get("data_indicacao", ""), reverse=False):
            nome = cliente["nome_completo"]
            tel = cliente["celular"]
            emb = cliente["indicado_por"].get("nome_embaixador", "—")
            data_ind = cliente.get("data_indicacao", "")
            dias_atraso = "—"
            if data_ind:
                try:
                    dt = datetime.fromisoformat(data_ind) if isinstance(data_ind, str) else data_ind
                    dias_atraso = (hoje - dt).days
                except:
                    pass

            st.markdown(f"""
            <div style="
                border: 1px solid #e0e0e0;
                border-radius: 8px;
                padding: 12px;
                margin-bottom: 12px;
                background-color: #fff;
                box-shadow: 0 2px 4px rgba(0,0,0,0.05);
            ">
                <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px;">
                    <strong>{nome}</strong>
                    <span style="color: #666;">{dias_atraso} dias</span>
                </div>
                <div style="font-size: 0.9em; color: #555; margin-bottom: 8px;">
                  📞 {tel} | 🕒 Indicação: {data_ind[:16] if data_ind else '—'}
                </div>
                <div style="font-size: 0.85em; color: #777; margin-bottom: 8px;">
                  👤 Embaixador: {emb}
                </div>
                <div style="background-color: #fff3cd; padding: 8px; border-radius: 6px; font-size: 0.9em;">
                  ⚠️ Esta indicação está há <strong>{dias_atraso} dias</strong> sem tratamento.
                </div>
            </div>
            """, unsafe_allow_html=True)

            clicked = st.button("✅ Iniciar Tratamento", key=f"start_atrasado_{cliente['_id']}", use_container_width=True)
            if clicked:
                try:
                    update_data = {
                        "em_tratamento": True,
                        "data_inicio_tratamento": datetime.now(),
                        "etapa_atual": "tratamento"
                    }
                    clientes_collection.update_one({"_id": cliente["_id"]}, {"$set": update_data})
                    st.success(f"✅ Tratamento iniciado para {nome}!")
                    st.rerun()
                except Exception as e:
                    st.error(f"❌ Erro: {e}")

    if aguardando_normal:
        st.markdown("#### 🟡 Novas indicações (últimos 7 dias)")
        for cliente in sorted(aguardando_normal, key=lambda x: x.get("data_indicacao", ""), reverse=True):
            nome = cliente["nome_completo"]
            tel = cliente["celular"]
            emb = cliente["indicado_por"].get("nome_embaixador", "—")
            data_ind = cliente.get("data_indicacao", "—")[:16]

            st.markdown(f"""
            <div style="
                border: 1px solid #e0e0e0;
                border-radius: 8px;
                padding: 12px;
                margin-bottom: 12px;
                background-color: #fff;
                box-shadow: 0 2px 4px rgba(0,0,0,0.05);
            ">
                <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px;">
                    <strong>{nome}</strong>
                    <span style="color: #666;">{data_ind.split(' ')[0]}</span>
                </div>
                <div style="font-size: 0.9em; color: #555; margin-bottom: 8px;">
                  📞 {tel} | 🕒 Indicação: {data_ind}
                </div>
                <div style="font-size: 0.85em; color: #777; margin-bottom: 8px;">
                  👤 Embaixador: {emb}
                </div>
            </div>
            """, unsafe_allow_html=True)

            clicked = st.button("✅ Iniciar Tratamento", key=f"start_normal_{cliente['_id']}", use_container_width=True)
            if clicked:
                try:
                    update_data = {
                        "em_tratamento": True,
                        "data_inicio_tratamento": datetime.now(),
                        "etapa_atual": "tratamento"
                    }
                    clientes_collection.update_one({"_id": cliente["_id"]}, {"$set": update_data})
                    st.success(f"✅ Tratamento iniciado para {nome}!")
                    st.rerun()
                except Exception as e:
                    st.error(f"❌ Erro: {e}")

    if not aguardando_normal and not atrasadas:
        st.info("✅ Todos os indicados já entraram em tratamento ou foram concluídos.")

    st.markdown("</div>", unsafe_allow_html=True)

    # --- 🟡 SEÇÃO 2: EM FLUXO ---
    st.markdown("### 🟡 Em Fluxo (Pendentes de conclusão)")
    st.markdown("<div style='border: 2px solid #ddd; border-radius: 8px; padding: 16px; background-color: #fafafa; margin-top: 20px;'>", unsafe_allow_html=True)

    has_fluxo = False
    for status in em_fluxo:
        clientes = status_groups.get(status, [])
        if clientes:
            has_fluxo = True
            with st.expander(f"{status} ({len(clientes)})", expanded=False):
                for cliente in sorted(clientes, key=lambda x: x.get("data_indicacao", ""), reverse=True):
                    nome = cliente["nome_completo"]
                    tel = cliente["celular"]
                    emb = cliente["indicado_por"].get("nome_embaixador", "—")
                    data_ind = cliente.get("data_indicacao", "—")[:16]
                    status_cliente = determinar_status_embaixador(cliente)

                    info_extra = ""
                    if status_cliente == "Em tratamento":
                        data_inicio = cliente.get("data_inicio_tratamento")
                        if isinstance(data_inicio, datetime):
                            data_inicio_str = data_inicio.strftime("%d/%m/%Y %H:%M")
                        elif isinstance(data_inicio, str):
                            try:
                                data_inicio_str = datetime.fromisoformat(data_inicio).strftime("%d/%m/%Y %H:%M")
                            except:
                                data_inicio_str = "—"
                        info_extra = f"<div style='background-color: #e3f2fd; padding: 6px; border-radius: 4px; margin-top: 6px;'>🕒 Tratamento iniciado em: {data_inicio_str}</div>"
                    elif status_cliente in ["Agendado", "Reagendado"]:
                        data_ag = cliente.get("retorno_agendado", "—")
                        periodo = cliente.get("periodo", "—")
                        info_extra = f"<div style='background-color: #e3f2fd; padding: 6px; border-radius: 4px; margin-top: 6px;'>📅 Agendado para {data_ag} ({periodo})</div>"
                        if cliente.get("reagendado_para"):
                            info_extra += f"<div style='background-color: #fff3cd; padding: 6px; border-radius: 4px; margin-top: 4px;'>🔄 Reagendado para: {cliente['reagendado_para']}</div>"
                    elif status_cliente == "Seguiu para ativação":
                        info_extra = "<div style='background-color: #fff3cd; padding: 6px; border-radius: 4px; margin-top: 6px;'>➡️ Aguardando agendamento ou início de tratamento</div>"

                    st.markdown(f"""
                    <div style="
                        border: 1px solid #e0e0e0;
                        border-radius: 8px;
                        padding: 12px;
                        margin-bottom: 12px;
                        background-color: #fff;
                        box-shadow: 0 2px 4px rgba(0,0,0,0.05);
                    ">
                        <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px;">
                            <strong>{nome}</strong>
                            <span style="color: #666;">{data_ind.split(' ')[0]}</span>
                        </div>
                        <div style="font-size: 0.9em; color: #555; margin-bottom: 8px;">
                          📞 {tel} | 🕒 Indicação: {data_ind}
                        </div>
                        <div style="font-size: 0.85em; color: #777; margin-bottom: 8px;">
                          👤 Embaixador: {emb}
                        </div>
                        {info_extra}
                    </div>
                    """, unsafe_allow_html=True)

                    if status_cliente == "Seguiu para ativação" and not cliente.get("em_tratamento", False):
                        clicked = st.button("✅ Iniciar Tratamento", key=f"start_{cliente['_id']}", use_container_width=True)
                        if clicked:
                            try:
                                update_data = {
                                    "em_tratamento": True,
                                    "data_inicio_tratamento": datetime.now(),
                                    "etapa_atual": "tratamento"
                                }
                                clientes_collection.update_one({"_id": cliente["_id"]}, {"$set": update_data})
                                st.success(f"✅ Tratamento iniciado para {nome}!")
                                st.rerun()
                            except Exception as e:
                                st.error(f"❌ Erro: {e}")
                    else:
                        st.button("🔄 Em andamento", key=f"ongoing_{cliente['_id']}", disabled=True, use_container_width=True)

    if not has_fluxo:
        st.info("✅ Nenhuma indicação em fluxo no momento.")

    st.markdown("</div>", unsafe_allow_html=True)

    # --- ✅ SEÇÃO 3: CONCLUÍDOS ---
    st.markdown("### ✅ Concluídos (Tratamento finalizado)")
    st.markdown("<div style='border: 2px solid #ddd; border-radius: 8px; padding: 16px; background-color: #fafafa; margin-top: 20px;'>", unsafe_allow_html=True)

    has_concluidos = False
    for status in concluidos:
        clientes = status_groups.get(status, [])
        if clientes:
            has_concluidos = True
            with st.expander(f"{status} ({len(clientes)})", expanded=False):
                for cliente in sorted(clientes, key=lambda x: x.get("data_indicacao", ""), reverse=True):
                    nome = cliente["nome_completo"]
                    tel = cliente["celular"]
                    emb = cliente["indicado_por"].get("nome_embaixador", "—")
                    data_ind = cliente.get("data_indicacao", "—")[:16]
                    data_fim = cliente.get("data_ativacao") or cliente.get("data_cancelamento") or "—"

                    if isinstance(data_fim, datetime):
                        data_fim_str = data_fim.strftime("%d/%m/%Y %H:%M")
                    elif isinstance(data_fim, str) and len(data_fim) > 10:
                        try:
                            data_fim_str = datetime.fromisoformat(data_fim).strftime("%d/%m/%Y %H:%M")
                        except:
                            data_fim_str = "—"
                    else:
                        data_fim_str = "—"

                    status_text = "✅ Ativado" if status == "Ativado" else "❌ Cancelado"
                    status_color = "#d4edda" if status == "Ativado" else "#f8d7da"
                    motivo = cliente.get("motivo_cancelamento", "Não informado") if status == "Cancelado" else ""

                    st.markdown(f"""
                    <div style="
                        border: 1px solid #e0e0e0;
                        border-radius: 8px;
                        padding: 12px;
                        margin-bottom: 12px;
                        background-color: #fff;
                        box-shadow: 0 2px 4px rgba(0,0,0,0.05);
                    ">
                        <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px;">
                            <strong>{nome}</strong>
                            <span style="color: #666;">{data_ind.split(' ')[0]}</span>
                        </div>
                        <div style="font-size: 0.9em; color: #555; margin-bottom: 8px;">
                          📞 {tel} | 🕒 Indicação: {data_ind}
                        </div>
                        <div style="font-size: 0.85em; color: #777; margin-bottom: 8px;">
                          👤 Embaixador: {emb}
                        </div>
                        <div style="background-color: {status_color}; padding: 6px; border-radius: 4px; margin-top: 6px;">
                          {status_text} em {data_fim_str}
                          {f' | Motivo: {motivo}' if status == 'Cancelado' else ''}
                        </div>
                    </div>
                    """, unsafe_allow_html=True)

                    st.button("✔️ Concluído", key=f"done_{cliente['_id']}", disabled=True, use_container_width=True)

    if not has_concluidos:
        st.info("🟡 Nenhuma indicação concluída ainda.")

    st.markdown("</div>", unsafe_allow_html=True)

============================================================================
✅ FUNÇÃO: mostrar_pool_revendas (mantida original)
============================================================================
def mostrar_pool_revendas(clientes_collection):
    st.subheader("🏪 Indicações de Revendas")
    def determinar_status_revenda(cliente):
        status_agendamento = cliente.get("status_agendamento")

        if status_agendamento == "ativado":
            return "Ativado"
        elif status_agendamento == "cancelado":
            return "Cancelado"
        elif status_agendamento == "agendado":
            return "Agendado"
        elif cliente.get("reagendado_para") and status_agendamento not in ["ativado", "cancelado"]:
            return "Reagendado"
        elif cliente.get("em_tratamento") is True:
            return "Em tratamento"
        elif cliente.get("seguiu_ativacao") == "Sim":
            return "Seguiu para ativação"
        else:
            return "Indicado"

    col_btn, col_space = st.columns([2, 8])
    with col_btn:
        if st.button("🔄 Atualizar Revendas", help="Recarrega os dados do banco", key="atualizar_revendas"):
            st.rerun()

    todos_indicados = list(clientes_collection.find({"indicado_por.tipo": "revenda"}))

    updated_count = 0
    for c in todos_indicados:
        status_ag = c.get("status_agendamento")
        em_trat = c.get("em_tratamento", False)
        _id = c["_id"]

        if status_ag in ["ativado", "cancelado"] and em_trat is True:
            try:
                clientes_collection.update_one(
                    {"_id": _id},
                    {"$set": {"em_tratamento": False}}
                )
                c["em_tratamento"] = False
                updated_count += 1
            except Exception as e:
                st.warning(f"⚠️ Não foi possível corrigir inconsistência para {c.get('nome_completo', '?')}: {e}")

    if updated_count > 0:
        st.info(f"✅ Corrigidas {updated_count} inconsistências de status.")

    if not todos_indicados:
        st.info("✅ Nenhuma indicação de revenda registrada ainda.")
        return

    hoje = datetime.now()

    status_groups = defaultdict(list)
    atrasadas_ids = set()

    for c in todos_indicados:
        status = determinar_status_revenda(c)
        status_groups[status].append(c)

        if status == "Indicado":
            data_ind = c.get("data_cadastro")
            if data_ind:
                try:
                    if isinstance(data_ind, str):
                        data_ind_dt = datetime.fromisoformat(data_ind)
                    elif isinstance(data_ind, datetime):
                        data_ind_dt = data_ind
                    else:
                        continue
                    if (hoje - data_ind_dt) > timedelta(days=7):
                        atrasadas_ids.add(str(c["_id"]))
                except Exception:
                    pass

    aguardando = ["Indicado"]
    em_fluxo = ["Em tratamento", "Seguiu para ativação", "Agendado", "Reagendado"]
    concluidos = ["Ativado", "Cancelado"]

    total = len(todos_indicados)
    total_concluidos = sum(len(status_groups[s]) for s in concluidos)
    total_fluxo = sum(len(status_groups[s]) for s in em_fluxo)
    total_indicado = len(status_groups["Indicado"])
    atrasadas_count = len(atrasadas_ids)

    st.markdown(f"""
    📊 **Resumo Geral**  
    Total: {total} | 
    ⚪ Aguardando início (indicado): {total_indicado - atrasadas_count} | 
    🟡 Em fluxo (em tratamento/agendado/etc.): {total_fluxo} | 
    ✅ Concluídos (ativado/cancelado): {total_concluidos} | 
    ⚠️ Atrasadas (>7d sem tratamento): {atrasadas_count}
    """)

    # --- ⚪ SEÇÃO 1: AGUARDANDO INÍCIO DO TRATAMENTO ---
    st.markdown("### ⚪ Aguardando Início do Tratamento")
    st.markdown("<div style='border: 2px solid #ddd; border-radius: 8px; padding: 16px; background-color: #fafafa;'>", unsafe_allow_html=True)

    aguardando_normal = []
    atrasadas = []
    for cliente in status_groups.get("Indicado", []):
        if str(cliente["_id"]) in atrasadas_ids:
            atrasadas.append(cliente)
        else:
            aguardando_normal.append(cliente)

    if atrasadas:
        st.markdown("#### ⚠️ Atrasadas (+7 dias sem tratamento)")
        for cliente in sorted(atrasadas, key=lambda x: x.get("data_cadastro", ""), reverse=False):
            nome = cliente["nome_completo"]
            tel = cliente["celular"]
            rev = cliente["indicado_por"].get("nome_revenda", "—")
            data_ind = cliente.get("data_cadastro", "")
            dias_atraso = "—"
            if data_ind:
                try:
                    if isinstance(data_ind, str):
                        dt = datetime.fromisoformat(data_ind)
                    elif isinstance(data_ind, datetime):
                        dt = data_ind
                    dias_atraso = (hoje - dt).days
                except:
                    pass

            st.markdown(f"""
            <div style="
                border: 1px solid #e0e0e0;
                border-radius: 8px;
                padding: 12px;
                margin-bottom: 12px;
                background-color: #fff;
                box-shadow: 0 2px 4px rgba(0,0,0,0.05);
            ">
                <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px;">
                    <strong>{nome}</strong>
                    <span style="color: #666;">{dias_atraso} dias</span>
                </div>
                <div style="font-size: 0.9em; color: #555; margin-bottom: 8px;">
                  📞 {tel} | 🕒 Cadastro: {str(data_ind)[:16] if data_ind else '—'}
                </div>
                <div style="font-size: 0.85em; color: #777; margin-bottom: 8px;">
                  🏪 Revenda: {rev}
                </div>
                <div style="background-color: #fff3cd; padding: 8px; border-radius: 6px; font-size: 0.9em;">
                  ⚠️ Esta indicação está há <strong>{dias_atraso} dias</strong> sem tratamento.
                </div>
            </div>
            """, unsafe_allow_html=True)

            clicked = st.button("✅ Iniciar Tratamento", key=f"start_rev_atrasado_{cliente['_id']}", use_container_width=True)
            if clicked:
                try:
                    update_data = {
                        "em_tratamento": True,
                        "data_inicio_tratamento": datetime.now(),
                        "etapa_atual": "tratamento"
                    }
                    clientes_collection.update_one({"_id": cliente["_id"]}, {"$set": update_data})
                    st.success(f"✅ Tratamento iniciado para {nome}!")
                    st.rerun()
                except Exception as e:
                    st.error(f"❌ Erro: {e}")

    if aguardando_normal:
        st.markdown("#### 🟡 Novas indicações (últimos 7 dias)")
        for cliente in sorted(aguardando_normal, key=lambda x: x.get("data_cadastro", ""), reverse=True):
            nome = cliente["nome_completo"]
            tel = cliente["celular"]
            rev = cliente["indicado_por"].get("nome_revenda", "—")
            data_ind = str(cliente.get("data_cadastro", "—"))[:16]

            st.markdown(f"""
            <div style="
                border: 1px solid #e0e0e0;
                border-radius: 8px;
                padding: 12px;
                margin-bottom: 12px;
                background-color: #fff;
                box-shadow: 0 2px 4px rgba(0,0,0,0.05);
            ">
                <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px;">
                    <strong>{nome}</strong>
                    <span style="color: #666;">{data_ind.split(' ')[0]}</span>
                </div>
                <div style="font-size: 0.9em; color: #555; margin-bottom: 8px;">
                  📞 {tel} | 🕒 Cadastro: {data_ind}
                </div>
                <div style="font-size: 0.85em; color: #777; margin-bottom: 8px;">
                  🏪 Revenda: {rev}
                </div>
            </div>
            """, unsafe_allow_html=True)

            clicked = st.button("✅ Iniciar Tratamento", key=f"start_rev_normal_{cliente['_id']}", use_container_width=True)
            if clicked:
                try:
                    update_data = {
                        "em_tratamento": True,
                        "data_inicio_tratamento": datetime.now(),
                        "etapa_atual": "tratamento"
                    }
                    clientes_collection.update_one({"_id": cliente["_id"]}, {"$set": update_data})
                    st.success(f"✅ Tratamento iniciado para {nome}!")
                    st.rerun()
                except Exception as e:
                    st.error(f"❌ Erro: {e}")

    if not aguardando_normal and not atrasadas:
        st.info("✅ Todos os indicados já entraram em tratamento ou foram concluídos.")

    st.markdown("</div>", unsafe_allow_html=True)

    # --- 🟡 SEÇÃO 2: EM FLUXO ---
    st.markdown("### 🟡 Em Fluxo (Pendentes de conclusão)")
    st.markdown("<div style='border: 2px solid #ddd; border-radius: 8px; padding: 16px; background-color: #fafafa; margin-top: 20px;'>", unsafe_allow_html=True)

    has_fluxo = False
    for status in em_fluxo:
        clientes = status_groups.get(status, [])
        if clientes:
            has_fluxo = True
            with st.expander(f"{status} ({len(clientes)})", expanded=False):
                for cliente in sorted(clientes, key=lambda x: x.get("data_cadastro", ""), reverse=True):
                    nome = cliente["nome_completo"]
                    tel = cliente["celular"]
                    rev = cliente["indicado_por"].get("nome_revenda", "—")
                    data_ind = str(cliente.get("data_cadastro", "—"))[:16]
                    status_cliente = determinar_status_revenda(cliente)

                    info_extra = ""
                    if status_cliente == "Em tratamento":
                        data_inicio = cliente.get("data_inicio_tratamento")
                        if isinstance(data_inicio, datetime):
                            data_inicio_str = data_inicio.strftime("%d/%m/%Y %H:%M")
                        elif isinstance(data_inicio, str):
                            try:
                                data_inicio_str = datetime.fromisoformat(data_inicio).strftime("%d/%m/%Y %H:%M")
                            except:
                                data_inicio_str = "—"
                        info_extra = f"<div style='background-color: #e3f2fd; padding: 6px; border-radius: 4px; margin-top: 6px;'>🕒 Tratamento iniciado em: {data_inicio_str}</div>"
                    elif status_cliente in ["Agendado", "Reagendado"]:
                        data_ag = cliente.get("retorno_agendado", "—")
                        periodo = cliente.get("periodo", "—")
                        info_extra = f"<div style='background-color: #e3f2fd; padding: 6px; border-radius: 4px; margin-top: 6px;'>📅 Agendado para {data_ag} ({periodo})</div>"
                        if cliente.get("reagendado_para"):
                            info_extra += f"<div style='background-color: #fff3cd; padding: 6px; border-radius: 4px; margin-top: 4px;'>🔄 Reagendado para: {cliente['reagendado_para']}</div>"
                    elif status_cliente == "Seguiu para ativação":
                        info_extra = "<div style='background-color: #fff3cd; padding: 6px; border-radius: 4px; margin-top: 6px;'>➡️ Aguardando agendamento ou início de tratamento</div>"

                    st.markdown(f"""
                    <div style="
                        border: 1px solid #e0e0e0;
                        border-radius: 8px;
                        padding: 12px;
                        margin-bottom: 12px;
                        background-color: #fff;
                        box-shadow: 0 2px 4px rgba(0,0,0,0.05);
                    ">
                        <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px;">
                            <strong>{nome}</strong>
                            <span style="color: #666;">{data_ind.split(' ')[0]}</span>
                        </div>
                        <div style="font-size: 0.9em; color: #555; margin-bottom: 8px;">
                          📞 {tel} | 🕒 Cadastro: {data_ind}
                        </div>
                        <div style="font-size: 0.85em; color: #777; margin-bottom: 8px;">
                          🏪 Revenda: {rev}
                        </div>
                        {info_extra}
                    </div>
                    """, unsafe_allow_html=True)

                    if status_cliente == "Seguiu para ativação" and not cliente.get("em_tratamento", False):
                        clicked = st.button("✅ Iniciar Tratamento", key=f"start_rev_{cliente['_id']}", use_container_width=True)
                        if clicked:
                            try:
                                update_data = {
                                    "em_tratamento": True,
                                    "data_inicio_tratamento": datetime.now(),
                                    "etapa_atual": "tratamento"
                                }
                                clientes_collection.update_one({"_id": cliente["_id"]}, {"$set": update_data})
                                st.success(f"✅ Tratamento iniciado para {nome}!")
                                st.rerun()
                            except Exception as e:
                                st.error(f"❌ Erro: {e}")
                    else:
                        st.button("🔄 Em andamento", key=f"ongoing_rev_{cliente['_id']}", disabled=True, use_container_width=True)

    if not has_fluxo:
        st.info("✅ Nenhuma indicação em fluxo no momento.")

    st.markdown("</div>", unsafe_allow_html=True)

    # --- ✅ SEÇÃO 3: CONCLUÍDOS ---
    st.markdown("### ✅ Concluídos (Tratamento finalizado)")
    st.markdown("<div style='border: 2px solid #ddd; border-radius: 8px; padding: 16px; background-color: #fafafa; margin-top: 20px;'>", unsafe_allow_html=True)

    has_concluidos = False
    for status in concluidos:
        clientes = status_groups.get(status, [])
        if clientes:
            has_concluidos = True
            with st.expander(f"{status} ({len(clientes)})", expanded=False):
                for cliente in sorted(clientes, key=lambda x: x.get("data_cadastro", ""), reverse=True):
                    nome = cliente["nome_completo"]
                    tel = cliente["celular"]
                    rev = cliente["indicado_por"].get("nome_revenda", "—")
                    data_ind = str(cliente.get("data_cadastro", "—"))[:16]
                    data_fim = cliente.get("data_ativacao") or cliente.get("data_cancelamento") or "—"

                    if isinstance(data_fim, datetime):
                        data_fim_str = data_fim.strftime("%d/%m/%Y %H:%M")
                    elif isinstance(data_fim, str) and len(data_fim) > 10:
                        try:
                            data_fim_str = datetime.fromisoformat(data_fim).strftime("%d/%m/%Y %H:%M")
                        except:
                            data_fim_str = "—"
                    else:
                        data_fim_str = "—"

                    status_text = "✅ Ativado" if status == "Ativado" else "❌ Cancelado"
                    status_color = "#d4edda" if status == "Ativado" else "#f8d7da"
                    motivo = cliente.get("motivo_cancelamento", "Não informado") if status == "Cancelado" else ""

                    st.markdown(f"""
                    <div style="
                        border: 1px solid #e0e0e0;
                        border-radius: 8px;
                        padding: 12px;
                        margin-bottom: 12px;
                        background-color: #fff;
                        box-shadow: 0 2px 4px rgba(0,0,0,0.05);
                    ">
                        <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px;">
                            <strong>{nome}</strong>
                            <span style="color: #666;">{data_ind.split(' ')[0]}</span>
                        </div>
                        <div style="font-size: 0.9em; color: #555; margin-bottom: 8px;">
                          📞 {tel} | 🕒 Cadastro: {data_ind}
                        </div>
                        <div style="font-size: 0.85em; color: #777; margin-bottom: 8px;">
                          🏪 Revenda: {rev}
                        </div>
                        <div style="background-color: {status_color}; padding: 6px; border-radius: 4px; margin-top: 6px;">
                          {status_text} em {data_fim_str}
                          {f' | Motivo: {motivo}' if status == 'Cancelado' else ''}
                        </div>
                    </div>
                    """, unsafe_allow_html=True)

                    st.button("✔️ Concluído", key=f"done_rev_{cliente['_id']}", disabled=True, use_container_width=True)

    if not has_concluidos:
        st.info("🟡 Nenhuma indicação concluída ainda.")

    st.markdown("</div>", unsafe_allow_html=True)
