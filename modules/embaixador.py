# modules/embaixador.py
import streamlit as st
from datetime import datetime
from .utils import normalize_phone

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
    elif cliente.get("reagendado_para") and status_agendamento not in ["ativado", "cancelado"]:
        return "Reagendado"
    elif cliente.get("retorno_agendado"):
        return "Agendado"
    elif cliente.get("em_tratamento") is True:
        return "Em tratamento"
    elif cliente.get("seguiu_ativacao") == "Sim":
        return "Seguiu para ativação"
    else:
        return "Indicado"

def render_embaixador(usuarios_collection, clientes_collection):
    # 🔍 Busca dados completos do embaixador logado (para obter nome da loja)
    codigo_embaixador = st.session_state.get("codigo_embaixador")
    nome_embaixador = st.session_state.get("nome_usuario", "Embaixador")
    loja_parceira = "—"
    
    if codigo_embaixador:
        emb_data = usuarios_collection.find_one(
            {"codigo_embaixador": codigo_embaixador, "perfil": "embaixador"}
        )
        if emb_data:
            nome_embaixador = emb_data.get("nome_exibicao", nome_embaixador)
            loja_parceira = emb_data.get("loja_parceira", "—")

    # ✨ Mensagem de boas-vindas personalizada
    st.markdown(
        f"""
        <div style="
            background-color: #f0f9ff;
            border-left: 4px solid #4a90e2;
            padding: 12px 16px;
            border-radius: 0 6px 6px 0;
            margin-bottom: 20px;
            font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
        ">
            <h3 style="margin: 0; color: #2c3e50;">👋 Bem-vindo, <strong>Embaixador {nome_embaixador}</strong> da Loja <em>"{loja_parceira}"</em>!</h3>
        </div>
        """,
        unsafe_allow_html=True
    )

    st.caption(f"Código do seu embaixador: **{codigo_embaixador or 'EMB??????'}**")

    # --- Formulário de indicação ---
    with st.expander("➕ Indicar Novo Cliente"):
        st.info("ℹ️ Este formulário é para registro inicial de indicação. Os dados completos serão preenchidos pela equipe durante o atendimento.")
        
        nome = st.text_input("Nome completo do cliente", key="ind_nome")
        celular = st.text_input("Telefone (com DDD, ex: 11999999999)", key="ind_cel")
        cpf = st.text_input("CPF (opcional)", key="ind_cpf")

        if st.button("✅ Registrar Indicação"):
            if not nome.strip() or not celular.strip():
                st.error("⚠️ Nome e telefone são obrigatórios.")
            else:
                celular_norm = normalize_phone(celular)
                if len(celular_norm) < 10 or len(celular_norm) > 11:
                    st.error("⚠️ Telefone inválido. Use 10 ou 11 dígitos (com DDD).")
                else:
                    cliente = {
                        "nome_completo": nome.strip().title(),
                        "celular": celular_norm,
                        "cpf": normalize_phone(cpf) if cpf.strip() else None,
                        "indicado_por": {
                            "tipo": "embaixador",
                            "codigo": codigo_embaixador,
                            "nome_embaixador": nome_embaixador  # usa o nome atualizado
                        },
                        "data_indicacao": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                        "status": "indicado",
                        "cadastrado_por": codigo_embaixador,
                        "etapa_atual": "indicacao",
                        "bonus_enviado": False,
                        "bonus_confirmado": False
                    }
                    try:
                        clientes_collection.insert_one(cliente)
                        st.success("✅ Indicação registrada com sucesso!")
                        st.rerun()
                    except Exception as e:
                        if "duplicate key" in str(e):
                            st.error("⚠️ Este telefone já está cadastrado no sistema.")
                        else:
                            st.error(f"❌ Erro ao salvar: {e}")

    # --- Lista de indicações ---
    st.divider()
    st.subheader("📋 Minhas Indicações")

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

            # 🏢 NOVO: Informações de condomínio (se existir)
            condominio_nome = cli.get("condominio_nome")
            bloco = cli.get("bloco")
            apartamento = cli.get("apartamento")
            
            condominio_info = ""
            if condominio_nome:
                condominio_info = f"🏢 {condominio_nome}"
                if bloco or apartamento:
                    unidade_parts = []
                    if bloco:
                        unidade_parts.append(f"Bloco {bloco}")
                    if apartamento:
                        unidade_parts.append(f"Apto {apartamento}")
                    if unidade_parts:
                        condominio_info += f" ({' / '.join(unidade_parts)})"

            col1, col2 = st.columns([4, 1])
            with col1:
                # ✨ Destaque visual se for uma ativação nova
                if cli.get("status_agendamento") == "ativado" and not cli.get("notificacao_embaixador_lida", False):
                    st.markdown("🎉 **NOVO CLIENTE ATIVADO!**")
                
                # Linha principal com nome e telefone
                st.write(f"**{nome}** | 📞 {tel} | 🕒 {data}")
                
                # 🏢 NOVO: Exibir condomínio se existir
                if condominio_info:
                    st.caption(condominio_info)
                
                # Status com badge colorido
                status_badge = {
                    "Ativado": "✅",
                    "Cancelado": "❌",
                    "Agendado": "📅",
                    "Reagendado": "🔄",
                    "Em tratamento": "🔧",
                    "Seguiu para ativação": "➡️",
                    "Indicado": "⏳"
                }.get(status_legivel, "📍")
                
                st.write(f"📌 Status: `{status_badge} {status_legivel}`")
                
            with col2:
                # ✅ Botão para marcar notificação como lida
                if cli.get("status_agendamento") == "ativado" and not cli.get("notificacao_embaixador_lida", False):
                    if st.button("✅ Entendi", key=f"lido_{cli['_id']}"):
                        clientes_collection.update_one(
                            {"_id": cli["_id"]},
                            {"$set": {"notificacao_embaixador_lida": True}}
                        )
                        st.rerun()
                # ✅ Botão de confirmação de bônus
                elif cli.get("bonus_enviado") and not cli.get("bonus_confirmado"):
                    if st.button("✅ Confirmar", key=f"conf_{cli['_id']}"):
                        clientes_collection.update_one(
                            {"_id": cli["_id"]},
                            {"$set": {
                                "bonus_confirmado": True,
                                "data_bonus_confirmado": datetime.now()
                            }}
                        )
                        st.success("🎉 Bônus confirmado!")
                        st.rerun()
                else:
                    st.caption("Ações disponíveis em breve")
    else:
        st.info("Nenhuma indicação registrada ainda.")

    # --- 📊 Estatísticas do Embaixador ---
    st.divider()
    st.subheader("📊 Suas Estatísticas")
    
    if minhas_indicacoes:
        # Taxa de conversão
        taxa_conversao = (ativados / total * 100) if total > 0 else 0
        
        col_est1, col_est2 = st.columns(2)
        with col_est1:
            st.metric("Taxa de Conversão", f"{taxa_conversao:.1f}%")
        with col_est2:
            st.metric("Bônus Confirmados", sum(1 for c in minhas_indicacoes if c.get("bonus_confirmado")))
        
        # 🏢 NOVO: Estatísticas por condomínio (se houver dados)
        condominios_com_ativacoes = {}
        for cli in minhas_indicacoes:
            if cli.get("status_agendamento") == "ativado" and cli.get("condominio_nome"):
                cond_nome = cli.get("condominio_nome")
                condominios_com_ativacoes[cond_nome] = condominios_com_ativacoes.get(cond_nome, 0) + 1
        
        if condominios_com_ativacoes:
            st.markdown("##### 🏢 Ativações por Condomínio")
            for cond, qtd in sorted(condominios_com_ativacoes.items(), key=lambda x: x[1], reverse=True)[:5]:
                st.caption(f"• {cond}: {qtd} ativação(ões)")
    else:
        st.info("📊 Estatísticas disponíveis após primeiras indicações.")
