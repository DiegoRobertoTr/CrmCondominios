# modules/acompanhamento_tecnicos.py
import streamlit as st
from datetime import datetime, date

def formatar_data_status(valor):
    """
    Formata data_status_os de forma segura.
    Aceita: datetime, str ISO (com ou sem fuso/milissegundos), str curta ou None.
    Retorna: string formatada "dd/mm HH:MM" ou "—".
    """
    if not valor:
        return "—"
    if isinstance(valor, datetime):
        return valor.strftime("%d/%m %H:%M")
    if isinstance(valor, str):
        # Remove possíveis sufixos problemáticos antes de tentar parse
        valor_limpo = valor.split(".")[0].split("+")[0].rstrip("Z")
        try:
            dt = datetime.fromisoformat(valor_limpo)
            return dt.strftime("%d/%m %H:%M")
        except (ValueError, TypeError):
            # Se falhar, retorna os primeiros 16 caracteres (ex: "2025-11-13 10:30")
            return valor[:16]
    return str(valor)[:16]  # fallback genérico

def render_acompanhamento_tecnicos(clientes_collection, usuarios_collection):
    st.header("👨‍🔧 Acompanhamento Técnico em Campo")
    st.caption("Visão em tempo real das ordens de serviço dos técnicos hoje")

    hoje = date.today().isoformat()

    # Busca todos os agendamentos do dia que têm técnico atribuído
    agendamentos_hoje = list(
        clientes_collection.find({
            "seguiu_ativacao": "Sim",
            "retorno_agendado": hoje,
            "atribuido_a": {"$exists": True, "$ne": None}
        }).sort("atribuido_a", 1)
    )

    if not agendamentos_hoje:
        st.info("✅ Nenhum agendamento atribuído a técnicos para hoje.")
        return

    # Agrupar por técnico
    tecnicos_dict = {}
    for ag in agendamentos_hoje:
        tecnico_login = ag["atribuido_a"]
        if tecnico_login not in tecnicos_dict:
            tecnico_doc = usuarios_collection.find_one(
                {"login": tecnico_login, "perfil": "tecnico"}
            )
            nome_tecnico = tecnico_doc["nome_exibicao"] if tecnico_doc else tecnico_login
            tecnicos_dict[tecnico_login] = {
                "nome": nome_tecnico,
                "agendamentos": []
            }
        tecnicos_dict[tecnico_login]["agendamentos"].append(ag)

    # Exibir por técnico
    for login_tecnico, dados in tecnicos_dict.items():
        st.subheader(f"🛠️ {dados['nome']} ({login_tecnico})")
        st.markdown("---")

        # Ordenar por ordem_execucao (1, 2, 3...)
        agendamentos_ordenados = sorted(
            dados["agendamentos"],
            key=lambda x: x.get("ordem_execucao", 999)
        )

        for ag in agendamentos_ordenados:
            nome_cliente = ag["nome_completo"]
            tel = ag["celular"]
            status_os = ag.get("status_os", "pendente")
            ordem = ag.get("ordem_execucao", "—")
            data_fmt = formatar_data_status(ag.get("data_status_os"))

            # Definir cor e emoji por status
            status_config = {
                "em_rota": ("🟡 Em rota", "#fff9c4"),
                "iniciado": ("🔵 Iniciado", "#e3f2fd"),
                "finalizado": ("🟢 Finalizado", "#e8f5e9"),
                "pendente": ("⚪ Pendente", "#f5f5f5")
            }
            status_texto, cor_fundo = status_config.get(status_os, ("⚠️ Desconhecido", "#ffebee"))

            # Exibir bloco com destaque visual
            st.markdown(
                f"""
                <div style="background-color:{cor_fundo}; padding:12px; border-radius:8px; margin-bottom:12px; border-left:4px solid #4CAF50;">
                    <strong>[{ordem}] {nome_cliente}</strong> | 📞 {tel}<br>
                    <strong>Status:</strong> {status_texto}
                    <br><small>Atualizado em: {data_fmt}</small>
                </div>
                """,
                unsafe_allow_html=True
            )

            # Reatribuição (apenas para admins ou supervisores no futuro)
            col1, col2 = st.columns([3, 1])
            with col1:
                tecnicos = ["Manter"] + [
                    t.get("login", t.get("_id", "???"))
                    for t in usuarios_collection.find({"perfil": "tecnico"})
                ]
                novo_tecnico = st.selectbox(
                    "Reatribuir para:",
                    options=tecnicos,
                    key=f"reatribuir_{ag['_id']}"
                )
            with col2:
                if st.button("🔄 Reatribuir", key=f"btn_reatribuir_{ag['_id']}"):
                    if novo_tecnico != "Manter":
                        try:
                            clientes_collection.update_one(
                                {"_id": ag["_id"]},
                                {"$set": {"atribuido_a": novo_tecnico}}
                            )
                            st.success(f"✅ Reatribuído para {novo_tecnico}!")
                            st.rerun()
                        except Exception as e:
                            st.error(f"❌ Erro ao reatribuir: {e}")

        st.markdown("<br>", unsafe_allow_html=True)
