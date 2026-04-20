# modules/embaixador.py
import streamlit as st
from datetime import datetime
from .utils import normalize_phone

# 🏢 CONDOMÍNIO - Importação
try:
    from .condominios import get_condominio_options, get_condominio_by_id
except ImportError:
    def get_condominio_options():
        return {}
    def get_condominio_by_id(cond_id):
        return None

def determinar_status_embaixador(cliente):
    """Converte campos do cliente em status legível para o painel do embaixador."""
    # Primeiro verifica o status principal do agendamento
    status_agendamento = cliente.get("status_agendamento")
    
    if status_agendamento == "ativado":
        return "Ativado"
    elif status_agendamento == "cancelado":
        return "Cancelado"
    elif status_agendamento == "agendado":
        return "Agendado"
    
    # Só verifica reagendado se NÃO estiver ativado/cancelado
    if cliente.get("reagendado_para") and status_agendamento not in ["ativado", "cancelado"]:
        return "Reagendado"
    elif cliente.get("em_tratamento") is True:
        return "Em tratamento"
    elif cliente.get("seguiu_ativacao") == "Sim":
        return "Seguiu para ativação"
    else:
        return "Indicado"

def atualizar_endereco_por_condominio_emb(condominio_nome, condominio_options):
    """Atualiza o session_state com dados do condomínio selecionado (para Embaixador)."""
    cond_id = condominio_options.get(condominio_nome)
    if cond_id:
        cond_data = get_condominio_by_id(cond_id)
        if cond_data:  # ✅ CORREÇÃO AQUI: Verificação completa
            st.session_state["endereco_emb"] = cond_data.get("endereco", "")
            st.session_state["numero_emb"] = cond_data.get("numero", "")
            st.session_state["cidade_emb"] = cond_data.get("cidade", "")
            st.session_state["condominio_id_emb"] = cond_id
            st.session_state["condominio_nome_emb"] = condominio_nome
            st.rerun()

def render_embaixador(usuarios_collection, clientes_collection):
    # 🔍 Busca dados completos do embaixador logado (para obter nome da loja)
    codigo_embaixador = st.session_state.get("codigo_embaixador")
    nome_embaixador = st.session_state.get("nome_usuario", "Embaixador")
    loja_parceira = "—"

    if codigo_embaixador:
        emb_data = usuarios_collection.find_one(
            {"codigo_embaixador": codigo_embaixador, "perfil": "embaixador"}
        )
        if emb_data:  # ✅ CORREÇÃO AQUI: Verificação completa
            nome_embaixador = emb_data.get("nome_exibicao", nome_embaixador)
            loja_parceira = emb_data.get("loja_parceira", "—")

    #  Mensagem de boas-vindas personalizada
    st.markdown(
        f"""
        <div style="background-color: #f0f9ff; border-left: 4px solid #4a90e2; padding: 12px 16px; border-radius: 0 6px 6px 0; margin-bottom: 20px; font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;">
        <h3 style="margin: 0; color: #2c3e50;">👋 Bem-vindo, <strong>Embaixador {nome_embaixador}</strong> da Loja <em>"{loja_parceira}"</em>!</h3>
        </div>
        """,
        unsafe_allow_html=True
    )
    st.caption(f"Código do seu embaixador: **{codigo_embaixador or 'EMB??????'}**")

    # --- Formulário de Indicação ---
    with st.expander("➕ Indicar Novo Cliente", expanded=False):
        st.info("ℹ️ Este formulário é para registro inicial de indicação. Os dados técnicos serão completados pela equipe.")
        
        nome = st.text_input("Nome completo do cliente *", key="ind_nome_emb")
        celular = st.text_input("Telefone (com DDD, ex: 24999999999) *", key="ind_cel_emb")
        cpf = st.text_input("CPF (opcional)", key="ind_cpf_emb")

        #  CONDOMÍNIO - Novos campos no formulário do Embaixador
        st.markdown("### 🏢 Localização (Opcional)")
        condominio_options = {"Nenhum / Não se aplica": None}
        condominio_options.update(get_condominio_options())
        
        cond_nome_salvo = st.session_state.get("condominio_nome_emb", "")
        index_cond = 0
        if cond_nome_salvo and cond_nome_salvo in condominio_options:
            index_cond = list(condominio_options.keys()).index(cond_nome_salvo)

        condominio_select = st.selectbox(
            "Condomínio",
            options=list(condominio_options.keys()),
            index=index_cond,
            key=f"cond_emb_{st.session_state.get('form_key_emb', 0)}"
        )

        if condominio_select and condominio_select != "Nenhum / Não se aplica":
            if condominio_select != cond_nome_salvo:
                atualizar_endereco_por_condominio_emb(condominio_select, condominio_options)
            else:
                # Garante persistência se já estava selecionado
                if "condominio_id_emb" not in st.session_state:
                    # Tenta recuperar do banco se houver edição futura, aqui apenas mantém
                    pass

        col_bloco, col_apto = st.columns(2)
        with col_bloco:
            bloco = st.text_input("Bloco (Opcional)", key=f"bloco_emb_{st.session_state.get('form_key_emb', 0)}")
        with col_apto:
            apartamento = st.text_input("Apartamento (Opcional)", key=f"apto_emb_{st.session_state.get('form_key_emb', 0)}")

        if st.button("✅ Registrar Indicação", type="primary"):
            if not nome.strip() or not celular.strip():
                st.error("️ Nome e telefone são obrigatórios.")
            else:
                celular_norm = normalize_phone(celular)
                if len(celular_norm) < 10 or len(celular_norm) > 11:
                    st.error("⚠️ Telefone inválido. Use 10 ou 11 dígitos (com DDD).")
                else:
                    # Verifica duplicidade simples
                    existe = clientes_collection.find_one({"celular": celular_norm})
                    if existe:
                        st.warning(f"⚠️ Este telefone já está cadastrado como: **{existe.get('nome_completo')}**.")
                        if not st.button("Mesmo assim registrar nova indicação?"):
                            st.stop()
                    
                    cliente = {
                        "nome_completo": nome.strip().title(),
                        "celular": celular_norm,
                        "cpf": normalize_phone(cpf) if cpf.strip() else None,
                        "indicado_por": {
                            "tipo": "embaixador",
                            "codigo": codigo_embaixador,
                            "nome_embaixador": nome_embaixador # usa o nome atualizado
                        },
                        "data_indicacao": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                        "status": "indicado",
                        "cadastrado_por": codigo_embaixador,
                        "etapa_atual": "indicacao",
                        "bonus_enviado": False,
                        "bonus_confirmado": False,
                        "status_agendamento": "aguardando", # Status inicial
                        # 🏢 CONDOMÍNIO - Salvando dados
                        "condominio_id": st.session_state.get("condominio_id_emb"),
                        "condominio_nome": st.session_state.get("condominio_nome_emb"),
                        "bloco": bloco.strip() if bloco.strip() else None,
                        "apartamento": apartamento.strip() if apartamento.strip() else None,
                        # Endereço básico se preenchido automaticamente
                        "endereco": st.session_state.get("endereco_emb"),
                        "numero": st.session_state.get("numero_emb"),
                        "cidade": st.session_state.get("cidade_emb"),
                    }

                    try:
                        clientes_collection.insert_one(cliente)
                        st.success("✅ Indicação registrada com sucesso!")
                        st.balloons()
                        
                        # Limpa form
                        keys_to_clear = [
                            "ind_nome_emb", "ind_cel_emb", "ind_cpf_emb",
                            "condominio_id_emb", "condominio_nome_emb",
                            "endereco_emb", "numero_emb", "cidade_emb",
                            "bloco_emb", "apto_emb"
                        ]
                        for k in keys_to_clear:
                            st.session_state.pop(k, None)
                        st.session_state["form_key_emb"] = st.session_state.get("form_key_emb", 0) + 1
                        st.rerun()
                    except Exception as e:
                        st.error(f"❌ Erro ao salvar: {e}")

    # --- Lista de Indicações ---
    st.divider()
    st.subheader(" Minhas Indicações")
    
    minhas_indicacoes = list(
        clientes_collection.find(
            {"indicado_por.codigo": codigo_embaixador}
        ).sort("data_indicacao", -1)
    )

    if minhas_indicacoes:
        # 📊 Resumo das indicações
        total = len(minhas_indicacoes)
        ativados = sum(1 for c in minhas_indicacoes if c.get("status_agendamento") == "ativado")
        em_andamento = sum(1 for c in minhas_indicacoes if c.get("status_agendamento") in ["agendado", "em_tratamento"])
        indicados = sum(1 for c in minhas_indicacoes if determinar_status_embaixador(c) == "Indicado")

        col_res1, col_res2, col_res3, col_res4 = st.columns(4)
        with col_res1:
            st.metric("Total", total)
        with col_res2:
            st.metric("✅ Ativados", ativados)
        with col_res3:
            st.metric("🔄 Em Andamento", em_andamento)
        with col_res4:
            st.metric("⏳ Aguardando", indicados)
        
        st.divider()

        for cli in minhas_indicacoes:
            nome = cli["nome_completo"]
            tel = cli["celular"]
            data = cli.get("data_indicacao", "")[:16] if cli.get("data_indicacao") else "—"
            status_legivel = determinar_status_embaixador(cli)
            
            #  NOVO: Informações de condomínio (se existir)
            condominio_nome = cli.get("condominio_nome")
            bloco = cli.get("bloco")
            apartamento = cli.get("apartamento")
            
            condominio_info = ""
            if condominio_nome:
                condominio_info = f" **{condominio_nome}**"
                if bloco or apartamento:
                    partes = []
                    if bloco: partes.append(f"Blq {bloco}")
                    if apartamento: partes.append(f"Apto {apartamento}")
                    condominio_info += f" ({' / '.join(partes)})"

            with st.expander(f"**{nome}** |  {tel} | 🕒 {data}", expanded=False):
                col1, col2 = st.columns([4, 1])
                with col1:
                    # Destaque visual
                    if cli.get("status_agendamento") == "ativado" and not cli.get("notificacao_embaixador_lida", False):
                        st.markdown("**NOVO CLIENTE ATIVADO!**")
                    
                    # Linha principal
                    st.write(f"**Status:** `{status_legivel}`")
                    
                    #  Exibir condomínio se existir
                    if condominio_info:
                        st.info(condominio_info)
                    
                    if cli.get("endereco"):
                        end_full = f"{cli['endereco']}, {cli.get('numero', '')}"
                        if cli.get('complemento'): end_full += f" ({cli['complemento']})"
                        st.caption(f"📍 {end_full} - {cli.get('cidade', '')}")

                with col2:
                    # Ações
                    if cli.get("status_agendamento") == "ativado" and not cli.get("notificacao_embaixador_lida", False):
                        if st.button("✅ Entendi", key=f"lido_{cli['_id']}"):
                            clientes_collection.update_one(
                                {"_id": cli["_id"]},
                                {"$set": {"notificacao_embaixador_lida": True}}
                            )
                            st.rerun()
                    
                    # Confirmação de bônus (exemplo simples)
                    if cli.get("status_agendamento") == "ativado" and not cli.get("bonus_confirmado", False):
                        if st.button("💰 Confirmar Bônus", key=f"bonus_{cli['_id']}"):
                            clientes_collection.update_one(
                                {"_id": cli["_id"]},
                                {"$set": {"bonus_confirmado": True, "data_bonus": datetime.now()}}
                            )
                            st.success("🎉 Bônus confirmado!")
                            st.rerun()

    else:
        st.info("Nenhuma indicação registrada ainda.")

    # --- Estatísticas ---
    st.divider()
    st.subheader("📊 Suas Estatísticas")
    if minhas_indicacoes:
        taxa_conversao = (ativados / total * 100) if total > 0 else 0
        col_est1, col_est2 = st.columns(2)
        with col_est1:
            st.metric("Taxa de Conversão", f"{taxa_conversao:.1f}%")
        with col_est2:
            st.metric("Bônus Confirmados", sum(1 for c in minhas_indicacoes if c.get("bonus_confirmado")))
