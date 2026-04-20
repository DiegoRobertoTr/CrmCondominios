import streamlit as st
from datetime import datetime, timedelta, timezone
import urllib.parse
import re
from collections import defaultdict
import calendar
import pandas as pd
from io import BytesIO, StringIO

# ============================================================================
# ✅ FUNÇÃO AUXILIAR: Obter lista de condomínios com cache e contagem
# ============================================================================
def get_condominios_com_contagem(clientes_collection, forcar_atualizacao=False):
    """
    Retorna lista de condomínios com contagem de clientes, usando cache.
    """
    cache_key = "condominios_cache_followup"
    cache_timestamp_key = "condominios_cache_timestamp_followup"
    CACHE_EXPIRY_SECONDS = 300  # 5 minutos de validade do cache
    
    agora = datetime.now(timezone.utc)
    
    # Verifica se precisa atualizar o cache
    precisa_atualizar = forcar_atualizacao
    
    if not precisa_atualizar:
        if cache_key not in st.session_state or cache_timestamp_key not in st.session_state:
            precisa_atualizar = True
        else:
            cache_timestamp = st.session_state.get(cache_timestamp_key, datetime.min.replace(tzinfo=timezone.utc))
            if (agora - cache_timestamp).total_seconds() > CACHE_EXPIRY_SECONDS:
                precisa_atualizar = True
    
    # Atualiza cache se necessário
    if precisa_atualizar:
        try:
            # Busca todos os condomínios únicos com contagem
            pipeline = [
                {
                    "$match": {
                        "seguiu_ativacao": {"$ne": "Sim"},
                        "restritivo": {"$ne": "Sim"},
                        "status_followup": {"$ne": "removido"},
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
            
            # Formata: "Nome do Condomínio (X clientes)"
            condominios_formatados = {}
            for r in resultados:
                nome = r["_id"]
                count = r["count"]
                condominios_formatados[f"{nome} ({count})"] = nome
            
            # Ordena por nome
            condominios_formatados = dict(sorted(condominios_formatados.items()))
            
            # Adiciona opção "Todos"
            opcoes_finais = {"Todos": "Todos"}
            opcoes_finais.update(condominios_formatados)
            
            # Salva no cache
            st.session_state[cache_key] = opcoes_finais
            st.session_state[cache_timestamp_key] = agora
            
            return opcoes_finais
            
        except Exception as e:
            st.error(f"❌ Erro ao buscar condomínios: {e}")
            return {"Todos": "Todos"}
    
    # Retorna do cache
    return st.session_state.get(cache_key, {"Todos": "Todos"})


# ============================================================================
# ✅ FUNÇÃO AUXILIAR: exibir cliente com touch tracking (ATUALIZADA)
# ============================================================================
def exibir_cliente_detalhe(cliente, clientes_collection, key_suffix=""):
    nome = cliente["nome_completo"]
    _id = str(cliente["_id"])
    key_base = f"{key_suffix}{_id}"
    
    # ✅ Obter contagem de touches (padrão: 0)
    touch_count = cliente.get("touch_count", 0)

    # ✅ Definir badge + cor com base no touch_count
    if touch_count == 0:
        badge = "🆕 "
        color_hex = "#d4edda"
    elif touch_count <= 3:
        badge = f"🟢 {touch_count} "
        color_hex = "#d4edda"
    elif touch_count <= 6:
        badge = f"🟡 {touch_count} "
        color_hex = "#fff3cd"
    elif touch_count <= 10:
        badge = f"🟠 {touch_count} "
        color_hex = "#ffeacc"
    else:
        badge = f"🔴 {touch_count} "
        color_hex = "#f8d7da"

    expander_title = f"👤 {nome} — {cliente.get('celular', 'N/A')} {badge} "

    with st.expander(expander_title, expanded=False):
        col1, col2 = st.columns([3, 1])
        with col1:
            st.write(f"**Origem:** {cliente.get('origem', 'N/A')} ")
            st.write(f"**Plano:** {cliente.get('plano_escolhido', 'N/A')} ")
            data_banco = cliente.get('retorno_agendado', '')
            try:
                data_exibicao = datetime.strptime(data_banco, "%Y-%m-%d").strftime("%d/%m/%Y") if data_banco else "Não definida "
            except:
                data_exibicao = data_banco or "Inválida "
            st.write(f"**Data Follow-up:** {data_exibicao} ")
            st.write(f"**Última atualização:** {cliente.get('data_cadastro', 'N/A')} ")
            st.write(f"**Cadastrado por:** {cliente.get('cadastrado_por', 'N/A')} ")
            
            # 🏢 NOVO: Exibir informações de condomínio
            if cliente.get("condominio_nome"):
                st.write(f"**Condomínio:** {cliente.get('condominio_nome', 'N/A')} ")
            if cliente.get("bloco") or cliente.get("apartamento"):
                bloco = cliente.get("bloco", " ")
                apto = cliente.get("apartamento", " ")
                unidade_texto = []
                if bloco:
                    unidade_texto.append(f"Bloco {bloco} ")
                if apto:
                    unidade_texto.append(f"Apto {apto} ")
                st.write(f"**Unidade:** {' - '.join(unidade_texto)} ")
            
            st.caption(f"🎯 Toques registrados: **{touch_count}** ")
        with col2:
            if st.button("✏️ Editar Follow-up ", key=f"edit_{key_base} "):
                st.session_state["editando_followup"] = _id
                st.session_state["data_banco_original"] = cliente.get("retorno_agendado", " ")

        # ✅ Botão de Registrar Touch
        if st.button("✅ Registrar Touch ", key=f"touch_{key_base} ", type="secondary"):
            novo_count = touch_count + 1
            nome_usuario = st.session_state.get("nome_usuario", "Anônimo ")
            timestamp = datetime.now(timezone.utc).isoformat()
            clientes_collection.update_one(
                {"_id": cliente["_id"]},
                {
                    "$set": {"touch_count": novo_count},
                    "$push": {
                        "touch_history": {
                            "timestamp": timestamp,
                            "by": nome_usuario,
                            "notes": "Touch registrado via Follow-up "
                        }
                    }
                }
            )
            st.success(f"✔️ Touch #{novo_count} registrado por {nome_usuario}! ")
            st.rerun()

        # Formulário de edição
        if st.session_state.get("editando_followup") == _id:
            with st.form(f"form_edit_{key_base} "):
                data_banco_orig = st.session_state.get("data_banco_original", " ")
                data_para_exibicao = " "
                if data_banco_orig:
                    try:
                        data_para_exibicao = datetime.strptime(data_banco_orig, "%Y-%m-%d").strftime("%d/%m/%Y")
                    except:
                        data_para_exibicao = data_banco_orig

                nova_data_exibicao = st.text_input(
                    "Nova data de follow-up (DD/MM/AAAA): ",
                    value=data_para_exibicao,
                    key=f"input_{key_base} "
                )
                col_a, col_b = st.columns(2)
                with col_a:
                    if st.form_submit_button("💾 Salvar "):
                        nova_data_banco = " "
                        if nova_data_exibicao.strip():
                            if re.match(r'\d{2}/\d{2}/\d{4}', nova_data_exibicao):
                                try:
                                    data_obj = datetime.strptime(nova_data_exibicao, "%d/%m/%Y")
                                    nova_data_banco = data_obj.strftime("%Y-%m-%d")
                                except ValueError:
                                    st.error("❌ Data inválida. ")
                                    return
                            else:
                                st.error("❌ Formato inválido. Use DD/MM/AAAA. ")
                                return

                        clientes_collection.update_one(
                            {"_id": cliente["_id"]},
                            {"$set": {"retorno_agendado": nova_data_banco}}
                        )
                        st.success("✅ Data atualizada! ")
                        st.session_state.pop("editando_followup", None)
                        st.session_state.pop("data_banco_original", None)
                        st.rerun()
                with col_b:
                    if st.form_submit_button("❌ Cancelar "):
                        st.session_state.pop("editando_followup", None)
                        st.session_state.pop("data_banco_original", None)
                        st.rerun()

        # Observações
        st.markdown("### 📝 Observações de Follow-up ")
        col_obs, col_btns = st.columns([3, 1])
        with col_obs:
            obs_atual = cliente.get("observacoes_followup", " ")
            nova_observacao = st.text_area(
                " ",
                value=obs_atual,
                placeholder="Ex: Cliente quer mais 3 pontos na semana que vem. ",
                key=f"obs_{key_base} "
            )
        with col_btns:
            if st.button("💾 Salvar ", key=f"salvar_obs_{key_base} "):
                clientes_collection.update_one(
                    {"_id": cliente["_id"]},
                    {"$set": {"observacoes_followup": nova_observacao}}
                )
                st.success("✅ Observações salvas! ")
                st.rerun()
            if st.button("🚫 Remover da Lista ", key=f"remover_{key_base} "):
                clientes_collection.update_one(
                    {"_id": cliente["_id"]},
                    {"$set": {"status_followup": "removido"}}
                )
                st.success(f"✅ {nome} removido da lista de follow-up. ")
                st.rerun()

        # WhatsApp
        if st.button("📞 Contatar Agora ", key=f"contato_{key_base} "):
            celular = cliente.get("celular", " ").replace(" ", "").replace("-", "").replace("(", "").replace(")", " ")
            if celular:
                mensagem = f"Olá {nome}, tudo bem? Aqui é da Tracecom. Estamos entrando em contato para acompanhar seu cadastro. Podemos conversar? "
                whatsapp_url = f"https://wa.me/55{celular}?text={urllib.parse.quote(mensagem)} "
                st.markdown(f"[📲 Enviar mensagem via WhatsApp]({whatsapp_url}) ", unsafe_allow_html=True)
            else:
                st.warning("Celular não encontrado. ")


# ============================================================================
# ✅ FUNÇÃO AUXILIAR: Formatar último touch
# ============================================================================
def formatar_ultimo_touch(cliente):
    """Retorna string formatada com data do último touch ou mensagem padrão"""
    touch_history = cliente.get("touch_history", [])
    if not touch_history:
        return "🆕 Nunca contactado "
    
    try:
        ultimo_ts = max([t.get("timestamp", " ") for t in touch_history])
        if not ultimo_ts:
            return "🆕 Nunca contactado "
        
        data_ultimo = datetime.fromisoformat(ultimo_ts.replace("Z ", "+00:00 "))
        agora = datetime.now(timezone.utc)
        
        diff = agora - data_ultimo
        dias = diff.days
        horas = diff.seconds // 3600
        minutos = (diff.seconds % 3600) // 60
        
        if dias == 0:
            if horas == 0:
                if minutos == 0:
                    tempo_str = "agora mesmo "
                else:
                    tempo_str = f"há {minutos} min "
            else:
                tempo_str = f"há {horas}h "
        elif dias == 1:
            tempo_str = "ontem "
        elif dias < 7:
            tempo_str = f"há {dias} dias "
        elif dias < 30:
            semanas = dias // 7
            tempo_str = f"há {semanas} semana{'s' if semanas > 1 else ''} "
        else:
            tempo_str = data_ultimo.strftime("%d/%m/%Y")
        
        if dias == 0:
            icone = "🟢 "
        elif dias <= 3:
            icone = "🟡 "
        elif dias <= 7:
            icone = "🟠 "
        else:
            icone = "🔴 "
        
        return f"{icone} Último touch: {tempo_str} "

    except Exception:
        return "❓ Data inválida "


# ============================================================================
# ✅ FUNÇÃO AUXILIAR: Formatar data de cadastro
# ============================================================================
def formatar_data_cadastro(data_cad):
    """Converte data de cadastro para string formatada de forma segura"""
    if data_cad is None:
        return "N/A"
    if isinstance(data_cad, str):
        return data_cad[:10] if len(data_cad) > 10 else data_cad
    if isinstance(data_cad, datetime):
        return data_cad.strftime("%Y-%m-%d")
    return str(data_cad)[:10]


# ============================================================================
# ✅ FUNÇÃO: Painel de Ligações (ATUALIZADA COM CONDOMÍNIO + CACHE + CONTADOR)
# ============================================================================
def render_painel_ligacoes(clientes_collection, is_admin, usuario_atual):
    """Renderiza o painel de ligações telefônicas com visualização e exportação"""
    st.subheader("📞 Painel de Ligações - Modo Call Center ")
    
    # 🔄 CARREGAR CONFIGURAÇÃO DO BANCO
    config_banco = clientes_collection.database["configuracoes"].find_one({"tipo": "modo_delegacao "})

    if "modo_delegacao_carregado_do_banco " not in st.session_state:
        if config_banco and config_banco.get("ativo "):
            st.session_state.modo_delegacao_ativo_sessao = config_banco.get("ativo ", False)
            st.session_state.atendente_delegado_sessao = config_banco.get("atendente ", "Todos os atendentes ")
            st.session_state.persistir_delegacao = True
        else:
            st.session_state.modo_delegacao_ativo_sessao = False
            st.session_state.atendente_delegado_sessao = "Todos os atendentes "
            st.session_state.persistir_delegacao = False
        st.session_state.modo_delegacao_carregado_do_banco = True

    modo_delegacao_ativo = st.session_state.get("modo_delegacao_ativo_sessao ", False)
    atendente_delegado = st.session_state.get("atendente_delegado_sessao ", "Todos os atendentes ")

    if config_banco:
        banco_ativo = config_banco.get("ativo ", False)
        banco_atendente = config_banco.get("atendente ", "Todos os atendentes ")
        
        if banco_ativo != modo_delegacao_ativo or banco_atendente != atendente_delegado:
            modo_delegacao_ativo = banco_ativo
            atendente_delegado = banco_atendente  
            st.session_state.modo_delegacao_ativo_sessao = modo_delegacao_ativo
            st.session_state.atendente_delegado_sessao = atendente_delegado

    # === CONTROLE DE DELEGAÇÃO (Só para Admin) ===
    if is_admin:
        if modo_delegacao_ativo:
            if atendente_delegado == "Todos os atendentes ":
                st.error("🚨 **MODO DELEGAÇÃO ATIVO (PERSISTENTE)** - Todos os atendentes estão vendo TODOS os clientes! ")
            else:
                st.warning(f"🚨 **MODO DELEGAÇÃO ATIVO (PERSISTENTE)** - Apenas **{atendente_delegado}** está vendo TODOS os clientes! ")
        
        todos_atendentes = clientes_collection.distinct("cadastrado_por ", {
            "seguiu_ativacao": {"$ne": "Sim "},
            "restritivo": {"$ne": "Sim "},
            "status_followup": {"$ne": "removido "}
        })
        todos_atendentes = [a for a in todos_atendentes if a]
        opcoes_delegacao = ["Todos os atendentes "] + sorted(todos_atendentes)
        
        with st.expander("⚙️ Configurar Modo Delegação ", expanded=not modo_delegacao_ativo):
            col_del1, col_del2, col_del3 = st.columns([1, 2, 2])
            
            with col_del1:
                modo_delegacao = st.toggle(
                    "🔄 Ativar ",
                    value=modo_delegacao_ativo,
                    help="Ative para permitir que um atendente específico (ou todos) vejam todos os clientes do follow-up. ",
                    key="toggle_delegacao "
                )
                st.session_state.modo_delegacao_ativo_sessao = modo_delegacao
                modo_delegacao_ativo = modo_delegacao
            
            with col_del2:
                if modo_delegacao:
                    atendente_delegado = st.selectbox(
                        "👤 Quem recebe todos os clientes: ",
                        options=opcoes_delegacao,
                        index=opcoes_delegacao.index(atendente_delegado) if atendente_delegado in opcoes_delegacao else 0,
                        key="select_atendente_delegado "
                    )
                    st.session_state.atendente_delegado_sessao = atendente_delegado
            
            with col_del3:
                persistir = st.checkbox(
                    "💾 Salvar configuração (persistente) ",
                    value=st.session_state.get("persistir_delegacao ", bool(config_banco)),
                    help="Se marcado, a configuração permanece ativa mesmo após reiniciar o sistema. ",
                    key="check_persistir "
                )
                st.session_state.persistir_delegacao = persistir
                
                if modo_delegacao:
                    if atendente_delegado == "Todos os atendentes ":
                        st.info("💡 Todos os atendentes logados terão acesso à carteira completa. ")
                    else:
                        st.info(f"💡 Apenas **{atendente_delegado}** terá acesso à carteira completa. ")
            
            col_btn1, col_btn2 = st.columns(2)
            with col_btn1:
                if st.button("💾 Aplicar Configuração ", use_container_width=True, type="primary "):
                    if persistir:
                        clientes_collection.database["configuracoes"].update_one(
                            {"tipo": "modo_delegacao "},
                            {"$set": {
                                "tipo": "modo_delegacao ",
                                "ativo": modo_delegacao,
                                "atendente": atendente_delegado,
                                "ativado_por": usuario_atual,
                                "data_ativacao": datetime.now(timezone.utc).isoformat()
                            }},
                            upsert=True
                        )
                        st.success("✅ Configuração salva no banco de dados! ")
                    else:
                        clientes_collection.database["configuracoes"].delete_one({"tipo": "modo_delegacao "})
                        st.info("ℹ️ Configuração aplicada apenas para esta sessão. ")
                    st.rerun()
            
            with col_btn2:
                if st.button("🗑️ Limpar Configuração do Banco ", use_container_width=True, type="secondary "):
                    clientes_collection.database["configuracoes"].delete_one({"tipo": "modo_delegacao "})
                    st.session_state.modo_delegacao_ativo_sessao = False
                    st.session_state.atendente_delegado_sessao = "Todos os atendentes "
                    st.success("🗑️ Configuração removida do banco! ")
                    st.rerun()
        
        st.divider()

    st.info("Visualize os clientes para ligação telefônica. Use os filtros para otimizar suas ligações. ")

    # === FILTROS AVANÇADOS ===
    st.markdown("### 🔍 Filtros Avançados de Ligação ")

    col_f1, col_f2, col_f3, col_f4 = st.columns([2, 2, 2, 2])

    with col_f1:
        filtro_touch_tipo = st.selectbox(
            "Quantidade de ligações: ",
            options=["Todos ", "Nunca ligado (0) ", "1-3 ligações ", "4-6 ligações ", "7-10 ligações ", "Mais de 10 ", "Personalizado "],
            index=0,
            key="filtro_touch_tipo "
        )

    with col_f2:
        if filtro_touch_tipo == "Personalizado ":
            touch_min = st.number_input("Mínimo: ", min_value=0, value=0, key="touch_min ")
            touch_max = st.number_input("Máximo: ", min_value=0, value=999, key="touch_max ")
        else:
            st.caption("Selecione 'Personalizado' para definir range ")
            touch_min, touch_max = 0, 999

    with col_f3:
        filtro_periodo = st.selectbox(
            "Último contato: ",
            options=["Qualquer período ", "Hoje ", "Ontem ", "Últimos 3 dias ", "Última semana ", "Últimos 15 dias ", "Último mês ", "Mais de 1 mês ", "Nunca contactado "],
            index=0,
            key="filtro_periodo "
        )

    with col_f4:
        filtro_nao_perturbar = st.checkbox(
            "☑️ Incluir 'Não Perturbar' ",
            value=False,
            help="Se marcado, mostra também clientes em período de não perturbar ",
            key="filtro_nao_perturbar "
        )

    # Botão de ações rápidas em lote
    st.markdown("#### ⚡ Ações em Lote Selecionados ")
    col_acoes1, col_acoes2, col_acoes3, col_acoes4 = st.columns([1, 1, 1, 2])

    with col_acoes1:
        st.caption("Após selecionar clientes: ")
    with col_acoes2:
        if st.button("📅 Tentar em 3 dias ", key="acao_3dias ", use_container_width=True):
            st.session_state.acao_lote = "tentar_3_dias "
    with col_acoes3:
        if st.button("🚫 Não perturbar 6m ", key="acao_6meses ", use_container_width=True):
            st.session_state.acao_lote = "nao_perturbar_6m "
    with col_acoes4:
        if st.button("❌ Remover da lista ", key="acao_remover ", use_container_width=True, type="secondary "):
            st.session_state.acao_lote = "remover "

    st.divider()

    # Filtros específicos do painel
    col1, col2, col3, col4 = st.columns([2, 2, 2, 1])

    usuario_pode_ver_todos = is_admin or (
        modo_delegacao_ativo and (
            atendente_delegado == "Todos os atendentes " or 
            atendente_delegado == usuario_atual
        )
    )

    with col1:
        if usuario_pode_ver_todos:
            atendentes = clientes_collection.distinct("cadastrado_por ", {
                "seguiu_ativacao": {"$ne": "Sim "},
                "restritivo": {"$ne": "Sim "},
                "status_followup": {"$ne": "removido "}
            })
            atendentes = [a for a in atendentes if a]
            atendentes.insert(0, "Todos ")
            
            filtro_atendente = st.selectbox(
                "Filtrar por atendente: ",
                options=atendentes,
                index=0,
                key="painel_atendente "
            )
        else:
            filtro_atendente = usuario_atual
            st.write(f"**Atendente:** {usuario_atual} ")

    with col2:
        ordenacao = st.selectbox(
            "Ordenar por: ",
            options=["Data de cadastro (mais recente) ", "Data de cadastro (mais antiga) ", "Nome (A-Z) ", "Touch count (mais touches primeiro) ", "Touch count (menos touches primeiro) ", "Último touch (mais recente) ", "Último touch (mais antigo) "],
            index=0,
            key="painel_ordenacao "
        )

    with col3:
        limite = st.number_input(
            "Quantidade por página: ",
            min_value=10,
            max_value=200,
            value=50,
            step=10,
            key="painel_limite "
        )

    # 🏢 NOVO: Filtro de Condomínio com Cache e Contador
    with col4:
        # Botão para atualizar cache
        if st.button("🔄 Atualizar ", key="btn_atualizar_cond_painel ", help="Atualiza a lista de condomínios "):
            if "condominios_cache_followup " in st.session_state:
                del st.session_state["condominios_cache_followup "]
            if "condominios_cache_timestamp_followup " in st.session_state:
                del st.session_state["condominios_cache_timestamp_followup "]
            st.rerun()
        
        condominios_opcoes = get_condominios_com_contagem(clientes_collection)
        
        # Extrai apenas os nomes para o multiselect
        opcoes_display = list(condominios_opcoes.keys())
        
        filtro_condominio_painel = st.multiselect(
            "Condomínio: ",
            options=opcoes_display,
            default=["Todos "] if "Todos " in opcoes_display else [],
            key="painel_filtro_condominio "
        )

    # Montagem da query
    query = {
        "seguiu_ativacao": {"$ne": "Sim "},
        "restritivo": {"$ne": "Sim "},
        "status_followup": {"$ne": "removido "}
    }

    # Lógica de filtro por atendente
    if not usuario_pode_ver_todos:
        query["cadastrado_por"] = usuario_atual
    elif filtro_atendente != "Todos ":
        query["cadastrado_por"] = filtro_atendente

    # 🏢 APLICAR FILTRO DE CONDOMÍNIO
    if filtro_condominio_painel and "Todos " not in filtro_condominio_painel:
        # Extrai os nomes reais (sem o contador)
        condominios_selecionados = []
        for opcao in filtro_condominio_painel:
            nome_real = condominios_opcoes.get(opcao, opcao)
            if nome_real != "Todos ":
                condominios_selecionados.append(nome_real)
        
        if condominios_selecionados:
            query["condominio_nome"] = {"$in": condominios_selecionados}

    # === FILTROS DE TOUCH ===
    if filtro_touch_tipo == "Nunca ligado (0) ":
        query["touch_count"] = {"$eq": 0}
    elif filtro_touch_tipo == "1-3 ligações ":
        query["touch_count"] = {"$gte": 1, "$lte": 3}
    elif filtro_touch_tipo == "4-6 ligações ":
        query["touch_count"] = {"$gte": 4, "$lte": 6}
    elif filtro_touch_tipo == "7-10 ligações ":
        query["touch_count"] = {"$gte": 7, "$lte": 10}
    elif filtro_touch_tipo == "Mais de 10 ":
        query["touch_count"] = {"$gt": 10}
    elif filtro_touch_tipo == "Personalizado ":
        query["touch_count"] = {"$gte": touch_min, "$lte": touch_max}

    # === FILTRO DE NÃO PERTURBAR ===
    hoje = datetime.now(timezone.utc)
    hoje_str = hoje.strftime("%Y-%m-%d ")

    if not filtro_nao_perturbar:
        query["$or"] = [
            {"retorno_agendado": {"$exists": False}},
            {"retorno_agendado": " "},
            {"retorno_agendado": {"$lte": hoje_str}}
        ]

    # === FILTRO DE PERÍODO DO ÚLTIMO CONTATO ===
    if filtro_periodo != "Qualquer período " and filtro_periodo != "Nunca contactado ":
        if filtro_periodo == "Hoje ":
            data_limite = hoje.replace(hour=0, minute=0, second=0)
        elif filtro_periodo == "Ontem ":
            data_limite = hoje - timedelta(days=1)
            data_limite = data_limite.replace(hour=0, minute=0, second=0)
        elif filtro_periodo == "Últimos 3 dias ":
            data_limite = hoje - timedelta(days=3)
        elif filtro_periodo == "Última semana ":
            data_limite = hoje - timedelta(days=7)
        elif filtro_periodo == "Últimos 15 dias ":
            data_limite = hoje - timedelta(days=15)
        elif filtro_periodo == "Último mês ":
            data_limite = hoje - timedelta(days=30)
        elif filtro_periodo == "Mais de 1 mês ":
            data_limite = hoje - timedelta(days=30)
            pass
        
        if filtro_periodo != "Mais de 1 mês ":
            query["touch_history.timestamp"] = {"$gte": data_limite.isoformat()}

    elif filtro_periodo == "Nunca contactado ":
        query["$or"] = [
            {"touch_history": {"$exists": False}},
            {"touch_history": {"$size": 0}}
        ]

    # Ordenação
    sort_field = "data_cadastro "
    sort_direction = -1

    if ordenacao == "Data de cadastro (mais antiga) ":
        sort_direction = 1
    elif ordenacao == "Nome (A-Z) ":
        sort_field = "nome_completo "
        sort_direction = 1
    elif ordenacao == "Touch count (mais touches primeiro) ":
        sort_field = "touch_count "
        sort_direction = -1
    elif ordenacao == "Touch count (menos touches primeiro) ":
        sort_field = "touch_count "
        sort_direction = 1
    elif ordenacao == "Último touch (mais recente) ":
        sort_field = "touch_history.timestamp "
        sort_direction = -1
    elif ordenacao == "Último touch (mais antigo) ":
        sort_field = "touch_history.timestamp "
        sort_direction = 1

    # Busca os clientes
    clientes = list(clientes_collection.find(query).sort(sort_field, sort_direction).limit(limite))

    # Pós-processamento para filtro "Mais de 1 mês "
    if filtro_periodo == "Mais de 1 mês ":
        data_limite = hoje - timedelta(days=30)
        clientes_filtrados = []
        for c in clientes:
            touch_history = c.get("touch_history ", [])
            if touch_history:
                ultimo_touch = max([t.get("timestamp ", " ") for t in touch_history])
                if ultimo_touch:
                    try:
                        data_ultimo = datetime.fromisoformat(ultimo_touch.replace("Z ", "+00:00 "))
                        if data_ultimo < data_limite:
                            clientes_filtrados.append(c)
                    except:
                        pass
            else:
                clientes_filtrados.append(c)
        clientes = clientes_filtrados[:limite]

    if not clientes:
        st.warning("📭 Nenhum cliente encontrado para ligação com os filtros selecionados. ")
        return

    # Mensagem informativa
    if modo_delegacao_ativo and not is_admin:
        if atendente_delegado == usuario_atual:
            st.success(f"🔄 **Modo Delegação Ativo** - Você está vendo {len(clientes)} cliente(s) de TODOS os atendentes. ")
        else:
            st.info(f"✅ {len(clientes)} cliente(s) encontrado(s) para ligação. ")
    else:
        st.success(f"✅ {len(clientes)} cliente(s) encontrado(s) para ligação! ")

    # === EXPORTAÇÃO (ATUALIZADA COM CONDOMÍNIO) ===
    st.markdown("---")
    col_exp1, col_exp2 = st.columns([1, 3])

    with col_exp1:
        st.markdown("### 📥 Exportar para Impressão ")

    with col_exp2:
        dados_export = []
        for c in clientes:
            touch_history = c.get("touch_history ", [])
            ultimo_contato = "Nunca "
            if touch_history:
                ultimo_ts = max([t.get("timestamp ", " ") for t in touch_history])
                try:
                    ultimo_dt = datetime.fromisoformat(ultimo_ts.replace("Z ", "+00:00 "))
                    ultimo_contato = ultimo_dt.strftime("%d/%m/%Y %H:%M ")
                except:
                    ultimo_contato = ultimo_ts
            
            # 🏢 Informações de condomínio
            condominio_info = " "
            if c.get("condominio_nome "):
                condominio_info = c.get("condominio_nome ", " ")
            if c.get("bloco ") or c.get("apartamento "):
                bloco = c.get("bloco ", " ")
                apto = c.get("apartamento ", " ")
                if bloco:
                    condominio_info += f" - Bloco {bloco} " if condominio_info else f"Bloco {bloco} "
                if apto:
                    condominio_info += f" - Apto {apto} "
            
            dados_export.append({
                "Data Cadastro": c.get("data_cadastro ", "N/A "),
                "Cadastrado Por": c.get("cadastrado_por ", "N/A "),
                "Nome Completo": c.get("nome_completo ", "N/A "),
                "Telefone": c.get("celular ", "N/A "),
                "Condomínio/Unidade": condominio_info if condominio_info else "N/A ",
                "Observações": c.get("observacoes_followup ", " ").replace("\n ", " "),
                "Toques": c.get("touch_count ", 0),
                "Último Contato": ultimo_contato,
                "Retorno Agendado": c.get("retorno_agendado ", "Imediato "),
                "Origem": c.get("origem ", "N/A "),
                "Plano": c.get("plano_escolhido ", "N/A ")
            })
        
        df = pd.DataFrame(dados_export)
        
        csv_buffer = StringIO()
        df.to_csv(csv_buffer, index=False, encoding='utf-8-sig')
        csv_data = csv_buffer.getvalue().encode('utf-8-sig')
        
        col_csv, col_txt = st.columns(2)
        
        with col_csv:
            st.download_button(
                label="📊 Excel/CSV (.csv) ",
                data=csv_data,
                file_name=f"ligacoes_followup_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M')}.csv ",
                mime="text/csv ",
                use_container_width=True,
                help="Abre diretamente no Excel. Formato CSV com suporte a acentos. "
            )
        
        with col_txt:
            texto_impressao = "📞 LISTA DE LIGAÇÕES - FOLLOW UP\n "
            texto_impressao += f"Gerado em: {datetime.now(timezone.utc).strftime('%d/%m/%Y %H:%M')}\n "
            texto_impressao += f"Filtros: {filtro_touch_tipo} | {filtro_periodo}\n "
            texto_impressao += f"Atendente: {filtro_atendente if usuario_pode_ver_todos else usuario_atual}\n "
            if modo_delegacao_ativo:
                texto_impressao += f"⚠️ MODO DELEGAÇÃO: {atendente_delegado}\n "
            texto_impressao += "=" * 80 + "\n\n "
            
            for i, c in enumerate(dados_export, 1):
                texto_impressao += f"{i}. {c['Nome Completo']} (Toques: {c['Toques']})\n "
                texto_impressao += f"   📱 {c['Telefone']}\n "
                if c['Condomínio/Unidade'] != "N/A ":
                    texto_impressao += f"   🏢 {c['Condomínio/Unidade']}\n "
                texto_impressao += f"   📅 Cadastro: {c['Data Cadastro']} | Último contato: {c['Último Contato']}\n "
                texto_impressao += f"   🔄 Retorno agendado: {c['Retorno Agendado']}\n "
                texto_impressao += f"   📝 Obs: {c['Observações'][:80]}{'...' if len(c['Observações']) > 80 else ''}\n "
                texto_impressao += "-" * 80 + "\n "
            
            st.download_button(
                label="📝 Texto (.txt) ",
                data=texto_impressao,
                file_name=f"ligacoes_followup_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M')}.txt ",
                mime="text/plain ",
                use_container_width=True,
                help="Formato texto para impressão rápida. "
            )

    st.markdown("---")

    # === PAINEL DE LIGAÇÕES COM AÇÕES AVANÇADAS ===
    st.markdown("### 🎯 Painel de Ligações ")
    st.caption("Use os botões para registrar touch, adicionar observações ou agendar retorno. ")

    st.markdown("""
    <style>
    .painel-card {
        background-color: #f8f9fa;
        border-radius: 10px;
        padding: 15px;
        margin-bottom: 10px;
        border-left: 5px solid #007bff;
    }
    .painel-card:hover {
        background-color: #e9ecef;
    }
    .telefone-destaque {
        font-size: 1.3em;
        font-weight: bold;
        color: #28a745;
    }
    .nao-perturbar {
        border-left: 5px solid #dc3545 !important;  
        background-color: #f8d7da !important;
    }
    .data-cadastro {
        font-size: 0.85em;
        color: #6c757d;
    }
    .ultimo-touch {
        font-size: 0.8em;
        font-weight: 500;
        margin-top: 2px;
    }
    .condominio-info {
        font-size: 0.85em;
        color: #17a2b8;
        font-weight: 500;
    }
    </style>
    """, unsafe_allow_html=True)

    selecionados = []

    for idx, cliente in enumerate(clientes, 1):
        nome = cliente.get("nome_completo ", "N/A ")
        telefone = cliente.get("celular ", "N/A ")
        data_cad = cliente.get("data_cadastro ", "N/A ")
        cadastrado_por = cliente.get("cadastrado_por ", "N/A ")
        obs = cliente.get("observacoes_followup ", " ")
        touch_count = cliente.get("touch_count ", 0)
        origem = cliente.get("origem ", "N/A ")
        retorno_agendado = cliente.get("retorno_agendado ", " ")
        _id = str(cliente["_id"])
        
        info_ultimo_touch = formatar_ultimo_touch(cliente)
        data_cad_str = formatar_data_cadastro(data_cad)
        
        # 🏢 Informações de condomínio
        condominio_nome = cliente.get("condominio_nome ", " ")
        bloco = cliente.get("bloco ", " ")
        apartamento = cliente.get("apartamento ", " ")
        condominio_display = " "
        if condominio_nome:
            condominio_display = f"🏢 {condominio_nome} "
            if bloco or apartamento:
                unidade_parts = []
                if bloco:
                    unidade_parts.append(f"Bloco {bloco} ")
                if apartamento:
                    unidade_parts.append(f"Apto {apartamento} ")
                condominio_display += f" - {' / '.join(unidade_parts)} "
        
        em_nao_perturbar = retorno_agendado and retorno_agendado > hoje_str
        
        if touch_count == 0:
            badge_touch = "🆕 "
        elif touch_count <= 3:
            badge_touch = f"🟢 {touch_count} "
        elif touch_count <= 6:
            badge_touch = f"🟡 {touch_count} "
        elif touch_count <= 10:
            badge_touch = f"🟠 {touch_count} "
        else:
            badge_touch = f"🔴 {touch_count} "
        
        css_class = "painel-card " if not em_nao_perturbar else "painel-card nao-perturbar "
        
        with st.container():
            col_check, cols_dados = st.columns([0.3, 9.7])
            
            with col_check:
                selecionado = st.checkbox(" ", key=f"sel_{_id} ", label_visibility="collapsed ")
                if selecionado:
                    selecionados.append(_id)
            
            with cols_dados:
                cols = st.columns([0.5, 2, 1.5, 1.5, 2, 1.5])
                
                with cols[0]:
                    st.markdown(f"**#{idx}** ")
                
                with cols[1]:
                    st.markdown(f"**{nome}** ")
                    st.caption(f"Origem: {origem} ")
                    if condominio_display:
                        st.caption(f"<span class='condominio-info'>{condominio_display}</span> ", unsafe_allow_html=True)
                    if em_nao_perturbar:
                        st.caption(f"🔕 Retorno: {datetime.strptime(retorno_agendado, '%Y-%m-%d').strftime('%d/%m/%Y')} ")
                
                with cols[2]:
                    st.markdown(f"<span class='telefone-destaque'>{telefone}</span> ", unsafe_allow_html=True)
                    st.caption(f"Toques: {badge_touch} ")
                
                with cols[3]:
                    st.markdown(f"<span class='data-cadastro'>📅 Cad: {data_cad_str}</span> ", unsafe_allow_html=True)
                    st.markdown(f"<span class='ultimo-touch'>{info_ultimo_touch}</span> ", unsafe_allow_html=True)
                    st.caption(f"👤 {cadastrado_por} ")
                
                with cols[4]:
                    if obs:
                        st.caption(f"📝 {obs[:40]}{'...' if len(obs) > 40 else ''} ")
                    else:
                        st.caption("_Sem observações_ ")
                
                with cols[5]:
                    if st.button("✋ Touch ", key=f"painel_touch_{_id} ", use_container_width=True):
                        novo_count = touch_count + 1
                        nome_usuario = st.session_state.get("nome_usuario ", "Anônimo ")
                        timestamp = datetime.now(timezone.utc).isoformat()
                        clientes_collection.update_one(
                            {"_id": cliente["_id"]},
                            {
                                "$set": {"touch_count": novo_count},
                                "$push": {
                                    "touch_history": {
                                        "timestamp": timestamp,
                                        "by": nome_usuario,
                                        "notes": "Touch registrado via Painel de Ligações "
                                    }
                                }
                            }
                        )
                        st.success("✔️ Touch registrado! ", icon="✅ ")
                        st.rerun()
                    
                    if st.button("⚙️ Ações ", key=f"painel_acoes_{_id} ", use_container_width=True):
                        st.session_state[f"mostrar_acoes_{_id} "] = True
    
    if st.session_state.get(f"mostrar_acoes_{_id} ", False):
        with st.form(key=f"form_acoes_painel_{_id} "):
            st.markdown("**Ações Rápidas:** ")
            
            col_ac1, col_ac2, col_ac3, col_ac4 = st.columns(4)
            
            with col_ac1:
                acao_obs = st.text_area(
                    "Observação: ",
                    value=obs,
                    height=80,
                    key=f"obs_acao_{_id} "
                )
            
            with col_ac2:
                st.markdown("  &nbsp; ")
                if st.form_submit_button("💾 Salvar Obs ", use_container_width=True):
                    clientes_collection.update_one(
                        {"_id": cliente["_id"]},
                        {"$set": {"observacoes_followup": acao_obs}}
                    )
                    st.success("✅ Observação salva! ")
                    st.session_state[f"mostrar_acoes_{_id} "] = False
                    st.rerun()
            
            with col_ac3:
                st.markdown("**Agendar Retorno:** ")
                dias_retorno = st.selectbox(
                    "Daqui a: ",
                    options=[3, 7, 15, 30, 180],
                    format_func=lambda x: f"{x} dias " if x < 30 else f"{x//30} meses " if x == 180 else f"{x} dias ",
                    key=f"dias_retorno_{_id} "
                )
                if st.form_submit_button("📅 Agendar ", use_container_width=True, type="primary "):
                    data_retorno = (hoje + timedelta(days=dias_retorno)).strftime("%Y-%m-%d ")
                    clientes_collection.update_one(
                        {"_id": cliente["_id"]},
                        {"$set": {"retorno_agendado": data_retorno}}
                    )
                    st.success(f"✅ Retorno agendado para {data_retorno}! ")
                    st.session_state[f"mostrar_acoes_{_id} "] = False
                    st.rerun()
            
            with col_ac4:
                st.markdown("**Outras Ações:** ")
                if st.form_submit_button("🚫 Não Perturbar 6m ", use_container_width=True):
                    data_retorno = (hoje + timedelta(days=180)).strftime("%Y-%m-%d ")
                    clientes_collection.update_one(
                        {"_id": cliente["_id"]},
                        {
                            "$set": {
                                "retorno_agendado": data_retorno,
                                "observacoes_followup": f"{obs}\n[NÃO PERTURBAR até {data_retorno}] "
                            }
                        }
                    )
                    st.success("✅ Não perturbar por 6 meses! ")
                    st.session_state[f"mostrar_acoes_{_id} "] = False
                    st.rerun()
                
                if st.form_submit_button("❌ Remover ", use_container_width=True, type="secondary "):
                    clientes_collection.update_one(
                        {"_id": cliente["_id"]},
                        {"$set": {"status_followup": "removido"}}
                    )
                    st.success("✅ Cliente removido da lista! ")
                    st.session_state[f"mostrar_acoes_{_id} "] = False
                    st.rerun()
    
    st.divider()

    if selecionados:
        st.markdown("---")
        st.warning(f"🎯 **{len(selecionados)} cliente(s) selecionado(s)** ")
        
        col_lote1, col_lote2, col_lote3, col_lote4 = st.columns([2, 2, 2, 4])
        
        with col_lote1:
            if st.button("📅 Agendar retorno em 3 dias (Lote) ", use_container_width=True):
                data_retorno = (hoje + timedelta(days=3)).strftime("%Y-%m-%d ")
                for cid in selecionados:
                    clientes_collection.update_one(
                        {"_id": cid},
                        {"$set": {"retorno_agendado": data_retorno}}
                    )
                st.success(f"✅ {len(selecionados)} clientes agendados para daqui 3 dias! ")
                st.rerun()
        
        with col_lote2:
            if st.button("🚫 Não Perturbar 6 meses (Lote) ", use_container_width=True):
                data_retorno = (hoje + timedelta(days=180)).strftime("%Y-%m-%d ")
                for cid in selecionados:
                    obs_atual = clientes_collection.find_one({"_id": cid}).get("observacoes_followup ", " ")
                    clientes_collection.update_one(
                        {"_id": cid},
                        {
                            "$set": {
                                "retorno_agendado": data_retorno,
                                "observacoes_followup": f"{obs_atual}\n[NÃO PERTURBAR até {data_retorno}] "
                            }
                        }
                    )
                st.success(f"✅ {len(selecionados)} clientes marcados como Não Perturbar! ")
                st.rerun()
        
        with col_lote3:
            if st.button("❌ Remover da lista (Lote) ", use_container_width=True, type="secondary "):
                for cid in selecionados:
                    clientes_collection.update_one(
                        {"_id": cid},
                        {"$set": {"status_followup": "removido"}}
                    )
                st.success(f"✅ {len(selecionados)} clientes removidos da lista! ")
                st.rerun()


# ============================================================================
# ✅ FUNÇÃO PRINCIPAL: render_followup
# ============================================================================
def render_followup(clientes_collection):
    """Renderiza o módulo de Follow-up com tracking de touches"""
    st.title("📅 Follow-up de Clientes")
    st.info("Aqui você gerencia o acompanhamento dos clientes que ainda não seguiram para ativação e não são restritivos.")
    
    tab1, tab2, tab3 = st.tabs(["📋 Lista de Follow-up ", "🗓️ Calendário Mensal ", "📞 Painel de Ligações "])

    usuario_atual = st.session_state.get("nome_usuario ", " ")
    is_admin = (usuario_atual == "Diego Roberto ")

    # =============== TAB 1: LISTA TRADICIONAL ===============
    with tab1:
        col_busca, col_tipo = st.columns([3, 1])
        with col_tipo:
            tipo_busca = st.selectbox(
                "Buscar por: ",
                options=["Telefone ", "Nome "],
                index=0,
                key="followup_tipo_busca "
            )
        with col_busca:
            placeholder = "Ex: 11999999999 " if tipo_busca == "Telefone " else "Ex: João Silva "
            busca_texto = st.text_input(
                f"🔍 Digite para buscar por {tipo_busca.lower()}: ",
                placeholder=placeholder,
                key="followup_busca "
            ).strip()

        # 🏢 NOVO: Filtros com Condomínio (3 colunas)
        col1, col2, col3 = st.columns([2, 2, 1])
        
        with col1:
            filtro_data = st.selectbox(
                "Filtrar por data de follow-up: ",
                ["Todos ", "Com data definida ", "Sem data definida ", "Vencidas ", "Hoje ", "Próximos 7 dias "],
                index=0
            )
        
        with col2:
            filtro_origem = st.multiselect(
                "Filtrar por origem: ",
                ["Opa Suite ", "Whatsapp ", "Indicação ", "Loja "],
                default=["Opa Suite ", "Whatsapp ", "Indicação ", "Loja "]
            )
        
        # 🏢 NOVO: Filtro de Condomínio com Cache e Contador
        with col3:
            # Botão para atualizar cache
            if st.button("🔄 Atualizar ", key="btn_atualizar_cond_tab1 ", help="Atualiza a lista de condomínios "):
                if "condominios_cache_followup " in st.session_state:
                    del st.session_state["condominios_cache_followup "]
                if "condominios_cache_timestamp_followup " in st.session_state:
                    del st.session_state["condominios_cache_timestamp_followup "]
                st.rerun()
            
            condominios_opcoes = get_condominios_com_contagem(clientes_collection)
            opcoes_display = list(condominios_opcoes.keys())
            
            filtro_condominio = st.multiselect(
                "Condomínio: ",
                options=opcoes_display,
                default=["Todos "] if "Todos " in opcoes_display else [],
                key="followup_filtro_condominio "
            )

        # ✅ Montagem da query base
        query = {
            "seguiu_ativacao": {"$ne": "Sim "},
            "restritivo": {"$ne": "Sim "},
            "status_followup": {"$ne": "removido "}
        }

        # ✅ Aplicar filtro de busca
        if busca_texto:
            if tipo_busca == "Nome ":
                query["nome_completo"] = {"$regex": re.escape(busca_texto), "$options": "i "}
            else:
                celular_limpo = re.sub(r"[^\d]", "", busca_texto)
                if len(celular_limpo) > 10 and celular_limpo.startswith("55 "):
                    celular_limpo = celular_limpo[2:]
                if celular_limpo:
                    query["celular"] = {"$regex": celular_limpo, "$options": "i "}

        # Filtro por usuário
        if not is_admin and usuario_atual:
            query["cadastrado_por"] = usuario_atual

        # Aplica filtros de data
        hoje = datetime.now(timezone.utc)
        hoje_str = hoje.strftime("%Y-%m-%d ")
        if filtro_data == "Com data definida ":
            query["retorno_agendado"] = {"$ne": " ", "$exists": True}
        elif filtro_data == "Sem data definida ":
            query["retorno_agendado"] = " "
        elif filtro_data == "Vencidas ":
            query["retorno_agendado"] = {"$lt": hoje_str, "$ne": " "}
        elif filtro_data == "Hoje ":
            query["retorno_agendado"] = hoje_str
        elif filtro_data == "Próximos 7 dias ":
            proximos_7 = [(hoje + timedelta(days=i)).strftime("%Y-%m-%d ") for i in range(1, 8)]
            query["retorno_agendado"] = {"$in": proximos_7}

        if filtro_origem:
            query["origem"] = {"$in": filtro_origem}

        # 🏢 APLICAR FILTRO DE CONDOMÍNIO
        if filtro_condominio and "Todos " not in filtro_condominio:
            condominios_selecionados = []
            for opcao in filtro_condominio:
                nome_real = condominios_opcoes.get(opcao, opcao)
                if nome_real != "Todos ":
                    condominios_selecionados.append(nome_real)
            
            if condominios_selecionados:
                query["condominio_nome"] = {"$in": condominios_selecionados}

        clientes_followup = list(clientes_collection.find(query).sort("retorno_agendado ", 1))

        if not clientes_followup:
            st.warning("📭 Nenhum cliente encontrado com os filtros selecionados. ")
        else:
            st.success(f"✅ {len(clientes_followup)} cliente(s) para follow-up! ")
            for cliente in clientes_followup:
                exibir_cliente_detalhe(cliente, clientes_collection, key_suffix="tab1 ")

    # =============== TAB 2: CALENDÁRIO MENSAL ===============
    with tab2:
        st.subheader("🗓️ Calendário Mensal de Follow-up ")

        query_agenda = {
            "seguiu_ativacao": {"$ne": "Sim "},
            "restritivo": {"$ne": "Sim "},
            "status_followup": {"$ne": "removido "},
            "retorno_agendado": {"$ne": " ", "$exists": True}
        }

        if not is_admin and usuario_atual:
            query_agenda["cadastrado_por"] = usuario_atual

        clientes_agenda = list(clientes_collection.find(query_agenda))
        agenda_por_dia = defaultdict(list)
        for cliente in clientes_agenda:
            agenda_por_dia[cliente["retorno_agendado"]].append(cliente)

        if "mes_visualizado_followup " not in st.session_state:
            st.session_state.mes_visualizado_followup = datetime.now(timezone.utc).replace(day=1).date()

        mes_atual = st.session_state.mes_visualizado_followup
        ano = mes_atual.year
        mes = mes_atual.month

        col_prev, col_title, col_next = st.columns([1, 3, 1])
        with col_prev:
            if st.button("<< Mês Anterior "):
                novo_mes = mes_atual.replace(day=1) - timedelta(days=1)
                st.session_state.mes_visualizado_followup = novo_mes.replace(day=1)
                st.rerun()
        with col_title:
            st.markdown(f"### {calendar.month_name[mes].capitalize()} {ano} ")
        with col_next:
            if st.button("Mês Próximo >> "):
                proximo = mes_atual.replace(day=28) + timedelta(days=4)
                st.session_state.mes_visualizado_followup = proximo.replace(day=1)
                st.rerun()

        st.caption(
            "🎨 Legendas: "
            "⚪ Sem follow-up | "
            "🟢 ≤2 | "
            "🟡 3–5 | "
            "🟠 6–10 | "
            "🔴 ≥11 | "
            "❗ Dias vencidos com follow-up pendente "
        )

        cal = calendar.monthcalendar(ano, mes)
        dias_da_semana = ["Seg ", "Ter ", "Qua ", "Qui ", "Sex ", "Sáb ", "Dom "]

        cols_header = st.columns(7)
        for i, dia in enumerate(dias_da_semana):
            cols_header[i].markdown(f"**{dia}** ")

        hoje_date = datetime.now(timezone.utc).date()
        for semana in cal:
            cols = st.columns(7)
            for i, dia_num in enumerate(semana):
                if dia_num == 0:
                    cols[i].write(" ")
                else:
                    data = datetime(ano, mes, dia_num).date()
                    data_str = data.strftime("%Y-%m-%d ")
                    qtd = len(agenda_por_dia.get(data_str, []))

                    if qtd > 0:
                        touches_totais = sum(cli.get("touch_count ", 0) for cli in agenda_por_dia[data_str])
                        media_touches = touches_totais / qtd
                    else:
                        media_touches = 0

                    if qtd == 0:
                        cor = "#f8f9fa "
                        texto = str(dia_num)
                    elif media_touches <= 2:
                        cor = "#d4edda "
                        texto = f"{dia_num}<br/>({qtd})<br/><small>avg: {media_touches:.1f}</small> "
                    elif media_touches <= 5:
                        cor = "#fff3cd "
                        texto = f"{dia_num}<br/>({qtd})<br/><small>avg: {media_touches:.1f}</small> "
                    elif media_touches <= 10:
                        cor = "#ffeacc "
                        texto = f"{dia_num}<br/>({qtd})<br/><small>avg: {media_touches:.1f}</small> "
                    else:
                        cor = "#f8d7da "
                        texto = f"{dia_num}<br/>({qtd})<br/><small>avg: {media_touches:.1f}</small> "

                    borda = " "
                    icone = " "
                    if data < hoje_date and qtd > 0:
                        borda = "border: 2px solid #e74c3c; "
                        icone = "❗ "

                    estilo = (
                        f"background-color:{cor}; "
                        f"padding:10px; "
                        f"border-radius:6px; "
                        f"text-align:center; "
                        f"font-weight:bold; "
                        f"font-size:0.9em; "
                        f"{borda} "
                    )
                    html = f"<div style='{estilo}'>{icone}{texto}</div> "
                    cols[i].markdown(html, unsafe_allow_html=True)

                    if qtd > 0:
                        if cols[i].button("👁️ ", key=f"ver_dia_{data_str} ", use_container_width=True):
                            st.session_state[f"expandir_dia_{data_str} "] = True

        st.markdown("---")

        data_selecionada = st.date_input(
            "Selecione um dia para ver os follow-ups: ",
            value=datetime.now(timezone.utc),
            min_value=datetime(2020, 1, 1),
            key="followup_seleciona_dia "
        )
        data_str = data_selecionada.strftime("%Y-%m-%d ")
        clientes_do_dia = agenda_por_dia.get(data_str, [])

        if clientes_do_dia:
            st.markdown(f"### 👥 Follow-ups em {data_selecionada.strftime('%d/%m/%Y')} ")

            texto_export = " "
            for cliente in clientes_do_dia:
                nome = cliente.get("nome_completo ", "N/A ")
                tel = cliente.get("celular ", "N/A ")
                plano = cliente.get("plano_escolhido ", "N/A ")
                origem = cliente.get("origem ", "N/A ")
                cad_por = cliente.get("cadastrado_por ", "N/A ")
                obs = cliente.get("observacoes_followup ", " ").strip() or "Sem observação "
                touch_ct = cliente.get("touch_count ", 0)
                # 🏢 Incluir condomínio na exportação
                condominio = cliente.get("condominio_nome ", " ")
                bloco = cliente.get("bloco ", " ")
                apto = cliente.get("apartamento ", " ")
                condominio_info = " "
                if condominio:
                    condominio_info = f" | 🏢 {condominio} "
                    if bloco or apto:
                        unidade = []
                        if bloco:
                            unidade.append(f"Bloco {bloco} ")
                        if apto:
                            unidade.append(f"Apto {apto} ")
                        condominio_info += f" ({' / '.join(unidade)}) "
                
                texto_export += (
                    f"📞 {nome} (toques: {touch_ct}){condominio_info}\n "
                    f"📱 {tel}\n "
                    f"🎯 Origem: {origem}\n "
                    f"📋 Plano: {plano}\n "
                    f"👤 Cadastrado por: {cad_por}\n "
                    f"📝 Obs: {obs}\n "
                    f"---\n "
                )

            st.download_button(
                label="📋 Copiar todos os follow-ups do dia ",
                data=texto_export,
                file_name=f"followups_{data_selecionada.strftime('%Y-%m-%d')}.txt ",
                mime="text/plain "
            )

            for cliente in clientes_do_dia:
                exibir_cliente_detalhe(cliente, clientes_collection, key_suffix="calendario ")

        else:
            st.info("📭 Nenhum follow-up agendado para este dia. ")

    # =============== TAB 3: PAINEL DE LIGAÇÕES ===============
    with tab3:
        render_painel_ligacoes(clientes_collection, is_admin, usuario_atual)
