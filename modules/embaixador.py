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
        for cli in minhas_indicacoes:
            nome = cli["nome_completo"]
            tel = cli["celular"]
            data = cli.get("data_indicacao", "")[:16] if cli.get("data_indicacao") else "—"
            status_legivel = determinar_status_embaixador(cli)

            col1, col2 = st.columns([4, 1])
            with col1:
                # ✨ Destaque visual se for uma ativação nova
                if cli.get("status_agendamento") == "ativado" and not cli.get("notificacao_embaixador_lida", False):
                    st.markdown("🎉 **NOVO CLIENTE ATIVADO!**")
                
                st.write(f"**{nome}** | 📞 {tel} | 🕒 {data} | 📌 Status: `{status_legivel}`")
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
        st.info("Nenhuma indicação registrada ainda.")
