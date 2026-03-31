import streamlit as st
from datetime import datetime, date
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import urllib.parse


def enviar_email_tecnico_a_caminho(cliente, tecnico_nome="Técnico Tracecom"):
    try:
        # Carrega configurações do secrets
        smtp_user = st.secrets["smtp"]["smtp_user"]
        smtp_password = st.secrets["smtp"]["smtp_password"]
        smtp_server = st.secrets["smtp"]["smtp_server"]
        smtp_port = int(st.secrets["smtp"]["smtp_port"])
        smtp_use_tls = st.secrets["smtp"].get("smtp_use_tls", False)

        # Validação de e-mail do cliente
        email_cliente = cliente.get("email", "").strip()
        if not email_cliente or "@" not in email_cliente or "." not in email_cliente.split("@")[-1]:
            st.warning("📧 Cliente sem e-mail válido cadastrado — e-mail não enviado.")
            return False

        # Prepara mensagem
        msg = MIMEMultipart("alternative")
        msg["Subject"] = "✅ Técnico Tracecom a caminho!"
        msg["From"] = "Tracecom Internet <comercial1@tracecom.net.br>"
        msg["To"] = email_cliente
        msg["Cc"] = "comercial1@tracecom.net.br"

        corpo_html = f"""
        <div style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto; padding: 20px; border: 1px solid #e0e0e0; border-radius: 8px;">
            <h2 style="color: #1e88e5;">Olá, {cliente.get('nome_completo', 'cliente')}!</h2>
            <p style="font-size: 16px; line-height: 1.6;">
                <strong>{tecnico_nome}</strong> está a caminho para realizar sua instalação.
            </p>
            <div style="background: #f5f9ff; padding: 16px; border-left: 4px solid #1e88e5; margin: 20px 0;">
                <p style="margin: 0;"><strong>📍 Endereço:</strong> {cliente.get('endereco', '—')}, {cliente.get('numero', '')}</p>
                {f"<p style='margin: 4px 0;'>{cliente.get('complemento', '')}</p>" if cliente.get('complemento') else ""}
                <p style="margin: 0;">{cliente.get('bairro', '—')} – {cliente.get('cidade', '—')}</p>
            </div>
            <p>Em caso de dúvidas, entre em contato conosco.</p>
            <hr style="border: 0; border-top: 1px solid #eee; margin: 24px 0;" />
            <p style="font-size: 14px; color: #666;">
                <strong>Equipe Tracecom</strong><br>
                Whatsapp (21) 3500-0188 | Opção 5
            </p>
        </div>
        """
        msg.attach(MIMEText(corpo_html, "html"))

        # Destinatários
        destinatarios = [email_cliente, "comercial1@tracecom.net.br"]

        # Conexão SMTP
        if smtp_port == 465:
            with smtplib.SMTP_SSL(smtp_server, smtp_port) as server:
                server.login(smtp_user, smtp_password)
                server.sendmail(smtp_user, destinatarios, msg.as_string())
        else:
            with smtplib.SMTP(smtp_server, smtp_port) as server:
                if smtp_use_tls:
                    server.starttls()
                server.login(smtp_user, smtp_password)
                server.sendmail(smtp_user, destinatarios, msg.as_string())

        return True

    except smtplib.SMTPAuthenticationError:
        st.error("❌ Erro de autenticação no SMTP. Verifique usuário/senha.")
        return False
    except smtplib.SMTPRecipientsRefused:
        st.error("❌ Destinatário recusado. Verifique o e-mail do cliente.")
        return False
    except Exception as e:
        st.error(f"⚠️ Erro ao enviar e-mail: {type(e).__name__}: {str(e)}")
        return False


def enviar_email_os_finalizada(cliente, tecnico_nome="Técnico Tracecom"):
    try:
        # Carrega configurações do secrets
        smtp_user = st.secrets["smtp"]["smtp_user"]
        smtp_password = st.secrets["smtp"]["smtp_password"]
        smtp_server = st.secrets["smtp"]["smtp_server"]
        smtp_port = int(st.secrets["smtp"]["smtp_port"])
        smtp_use_tls = st.secrets["smtp"].get("smtp_use_tls", False)

        # Validação de e-mail do cliente
        email_cliente = cliente.get("email", "").strip()
        if not email_cliente or "@" not in email_cliente or "." not in email_cliente.split("@")[-1]:
            st.warning("📧 Cliente sem e-mail válido cadastrado — e-mail de encerramento não enviado.")
            return False

        # E-mail atualizado conforme sua solicitação
        msg = MIMEMultipart("alternative")
        msg["Subject"] = "🎉 Sua instalação foi concluída com sucesso!"
        msg["From"] = "Tracecom Internet <comercial1@tracecom.net.br>"
        msg["To"] = email_cliente
        msg["Cc"] = "comercial1@tracecom.net.br"

        corpo_html = f"""
        <div style="font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; 
                    max-width: 600px; margin: 0 auto; padding: 20px; 
                    border: 1px solid #e3f2fd; border-radius: 10px; 
                    background-color: #fafcff;">
            <h2 style="color: #1565c0; margin-top: 0; font-weight: 600;">
                Olá, {cliente.get('nome_completo', 'cliente')}!
            </h2>
            <p style="font-size: 16px; line-height: 1.6; color: #333;">
                Agradecemos por escolher a <strong>Tracecom</strong>! 🎉<br>
                Sua instalação foi concluída com sucesso pelo nosso técnico <strong>{tecnico_nome}</strong>.
            </p>

            <div style="background: #f8fdff; padding: 16px; 
                        border-left: 4px solid #2196f3; 
                        margin: 20px 0; border-radius: 0 6px 6px 0;">
                <p style="margin: 0; font-weight: 600; color: #0d47a1;">▸ Local:</p>
                <p style="margin: 4px 0 0 16px;">{cliente.get('endereco', '—')}, {cliente.get('numero', '')}</p>
                {f"<p style='margin: 2px 0 0 16px;'>{cliente.get('complemento', '')}</p>" if cliente.get('complemento') else ""}
                <p style="margin: 4px 0 8px 16px;">{cliente.get('bairro', '—')} – {cliente.get('cidade', '—')}</p>
                
                <p style="margin: 12px 0 0 0; font-weight: 600; color: #0d47a1;">▸ Plano contratado:</p>
                <p style="margin: 4px 0 0 16px;">{cliente.get('plano_escolhido', '—')}</p>
            </div>

            <p style="font-size: 15px; line-height: 1.6; background-color: #fff8e1; 
                      padding: 14px; border-radius: 8px; border-left: 3px solid #ff9800;">
                <strong>💡 Em caso de necessidade de suporte, registre este número:</strong><br>
                <span style="font-size: 18px; font-weight: bold; color: #e65100;">(21) 3500-0188, opção 6</span><br><br>
                Lembre-se! Toda a tratativa de suporte é realizada por este canal, 
                especializado e com acessos diferenciados para qualquer tratativa necessária 
                em caso de intermitência de sinal.
            </p>

            <hr style="border: 0; border-top: 1px solid #e0e0e0; margin: 28px 0;" />
            
            <p style="font-size: 14px; color: #555; text-align: center; margin-bottom: 0;">
                <strong>Equipe Tracecom</strong><br>
                Whatsapp (21) 3500-0188 | Opção 6
            </p>
        </div>
        """
        msg.attach(MIMEText(corpo_html, "html"))

        # Destinatários
        destinatarios = [email_cliente, "comercial1@tracecom.net.br"]

        # Conexão SMTP
        if smtp_port == 465:
            with smtplib.SMTP_SSL(smtp_server, smtp_port) as server:
                server.login(smtp_user, smtp_password)
                server.sendmail(smtp_user, destinatarios, msg.as_string())
        else:
            with smtplib.SMTP(smtp_server, smtp_port) as server:
                if smtp_use_tls:
                    server.starttls()
                server.login(smtp_user, smtp_password)
                server.sendmail(smtp_user, destinatarios, msg.as_string())

        return True

    except smtplib.SMTPAuthenticationError:
        st.error("❌ Erro de autenticação no SMTP ao enviar e-mail de encerramento.")
        return False
    except smtplib.SMTPRecipientsRefused:
        st.error("❌ Destinatário recusado no e-mail de encerramento.")
        return False
    except Exception as e:
        st.error(f"⚠️ Erro ao enviar e-mail de encerramento: {type(e).__name__}: {str(e)}")
        return False


def render_tecnico(clientes_collection, login_tecnico):
    st.header("🔧 Painel do Técnico")
    st.caption(f"Técnico logado: **{login_tecnico}**")

    hoje = date.today().isoformat()
    
    # Busca agendamentos do dia (seguiu_ativacao == "Sim" + retorno_agendado == hoje)
    agendamentos_do_dia = list(
        clientes_collection.find({
            "seguiu_ativacao": "Sim",
            "retorno_agendado": hoje
        }).sort("ordem_execucao", 1)
    )

    if not agendamentos_do_dia:
        st.info("✅ Nenhum agendamento para hoje.")
        return

    st.subheader(f"📅 Agendamentos de Hoje ({hoje})")
    
    # Separa meus agendamentos e os disponíveis
    meus_agendamentos = [a for a in agendamentos_do_dia if a.get("atribuido_a") == login_tecnico]
    outros_agendamentos = [a for a in agendamentos_do_dia if a.get("atribuido_a") != login_tecnico or a.get("atribuido_a") is None]

    # === Meus agendamentos (com controle de status) ===
    if meus_agendamentos:
        st.markdown("### 👷 Meus Atendimentos (em ordem)")
        for cliente in meus_agendamentos:
            nome = cliente["nome_completo"]
            tel = cliente["celular"]
            status_os = cliente.get("status_os", "pendente")
            ordem = cliente.get("ordem_execucao", "—")
            
            # Determinar texto e cor do status
            status_config = {
                "em_rota": ("🟡 Em rota", "amarelo"),
                "iniciado": ("🔵 Iniciado", "azul"),
                "finalizado": ("🟢 Finalizado", "verde"),
                "pendente": ("⚪ Pendente", "cinza")
            }
            status_texto, _ = status_config.get(status_os, ("⚠️ Desconhecido", "vermelho"))

            with st.expander(f"[{ordem}] {nome} - {tel} | {status_texto}", expanded=False):
                st.write(f"**Endereço:** {cliente.get('endereco', '—')}, {cliente.get('numero', '')}")
                st.write(f"**Plano:** {cliente.get('plano_escolhido', '—')}")
                st.write(f"**Período:** {cliente.get('periodo', '—')}")
                
                # Botões sequenciais com e-mail automático no "Em rota" e "Finalizar"
                if status_os == "pendente":
                    if st.button("🚗 Em Rota", key=f"rota_{cliente['_id']}"):
                        clientes_collection.update_one(
                            {"_id": cliente["_id"]},
                            {"$set": {"status_os": "em_rota", "data_status_os": datetime.now()}}
                        )
                        email_cliente = cliente.get("email")
                        if email_cliente and "@" in email_cliente:
                            sucesso = enviar_email_tecnico_a_caminho(
                                cliente,
                                st.session_state.get("nome_usuario", "Técnico Tracecom")
                            )
                            if sucesso:
                                st.toast("📬 E-mail 'Técnico a caminho' enviado ao cliente!", icon="✅")
                        else:
                            st.warning("📧 Cliente sem e-mail — notificação não enviada.")
                        st.rerun()
                elif status_os == "em_rota":
                    if st.button("▶️ Iniciar OS", key=f"iniciar_{cliente['_id']}"):
                        clientes_collection.update_one(
                            {"_id": cliente["_id"]},
                            {"$set": {"status_os": "iniciado", "data_status_os": datetime.now()}}
                        )
                        st.rerun()
                elif status_os == "iniciado":
                    if st.button("✅ Finalizar OS", key=f"finalizar_{cliente['_id']}"):
                        clientes_collection.update_one(
                            {"_id": cliente["_id"]},
                            {"$set": {"status_os": "finalizado", "data_status_os": datetime.now()}}
                        )
                        email_cliente = cliente.get("email")
                        if email_cliente and "@" in email_cliente:
                            sucesso = enviar_email_os_finalizada(
                                cliente,
                                st.session_state.get("nome_usuario", "Técnico Tracecom")
                            )
                            if sucesso:
                                st.toast("📬 E-mail de encerramento enviado ao cliente!", icon="🎉")
                                
                                # ✅ HOOK DE SATISFAÇÃO — 100% COMPATÍVEL COM SEU app.py
                                try:
                                    from modules.satisfacao import agendar_pesquisas_satisfacao
                                    from pymongo import MongoClient
                                    
                                    # 🔁 Replica EXATAMENTE a lógica de app.py
                                    try:
                                        username = st.secrets["mongo"]["MONGO_USERNAME"]
                                        password = st.secrets["mongo"]["MONGO_PASSWORD"]
                                        cluster_url = st.secrets["mongo"]["MONGO_CLUSTER_URL"]
                                    except KeyError:
                                        username = st.secrets["MONGO_USERNAME"]
                                        password = st.secrets["MONGO_PASSWORD"]
                                        cluster_url = st.secrets["MONGO_CLUSTER_URL"]
                                    
                                    u = urllib.parse.quote_plus(username)
                                    p = urllib.parse.quote_plus(password)
                                    uri = f"mongodb+srv://{u}:{p}@{cluster_url}/?retryWrites=true&w=majority"
                                    
                                    client = MongoClient(uri)
                                    db = client.crm_db
                                    
                                    sucesso_satisfacao = agendar_pesquisas_satisfacao(
                                        db=db,
                                        cliente_id=cliente["_id"],
                                        cliente_data=cliente,
                                        tecnico_nome=st.session_state.get("nome_usuario", "Técnico Tracecom"),
                                        link_pesquisa_base="https://forms.gle/DNburCnrLyLgYcweA?usp=pp_url"
                                    )
                                    if sucesso_satisfacao:
                                        st.toast("📨 Pesquisas de satisfação agendadas (7,15,30,60d).", icon="✅")
                                    else:
                                        st.warning("⚠️ Falha ao agendar pesquisas — verifique os logs.")
                                except Exception as e:
                                    st.error(f"⚠️ Erro ao agendar satisfação: {e}")
                        else:
                            st.toast("⚠️ Cliente sem e-mail — e-mail de encerramento não enviado.", icon="📧")
                        st.rerun()
                elif status_os == "finalizado":
                    st.success("✅ Ordem de serviço finalizada!")
                    if st.button("➡️ Seguir para o próximo", key=f"proximo_{cliente['_id']}"):
                        st.info("Próximo agendamento já está visível na lista.")

    # === Agendamentos disponíveis para atribuição (CORRIGIDO) ===
    if outros_agendamentos:
        st.divider()
        st.markdown("### ➕ Agendamentos Disponíveis")
        for cliente in outros_agendamentos:
            nome = cliente["nome_completo"]
            tel = cliente["celular"]
            atribuido_a = cliente.get("atribuido_a")

            # ✅ Lógica de disponibilidade: só permite atribuição se NÃO estiver atribuído a outro técnico
            disponivel_para_atribuir = (atribuido_a is None) or (atribuido_a == login_tecnico)

            status_rotulo = "🟢 Disponível" if disponivel_para_atribuir else f"🔒 Atribuído a: {atribuido_a}"
            
            with st.expander(f"📞 {nome} - {tel} | {status_rotulo}", expanded=False):
                st.write(f"**Endereço:** {cliente.get('endereco', '—')}, {cliente.get('numero', '')}")
                st.write(f"**Plano:** {cliente.get('plano_escolhido', '—')}")
                
                if disponivel_para_atribuir:
                    if st.button("🙋 Atribuir a Mim", key=f"atribuir_{cliente['_id']}"):
                        clientes_collection.update_one(
                            {"_id": cliente["_id"]},
                            {"$set": {
                                "atribuido_a": login_tecnico,
                                "status_os": "pendente",
                                "ordem_execucao": len(meus_agendamentos) + 1
                            }}
                        )
                        st.success(f"✅ {nome} atribuído a você!")
                        st.rerun()
                else:
                    st.info(f"🔒 Este agendamento já está atribuído a **{atribuido_a}** e não pode ser reassumido por outro técnico.")

    # === Reordenar meus agendamentos ===
    if meus_agendamentos:
        st.divider()
        st.markdown("### 🔄 Reordenar Meus Atendimentos")
        for idx, cliente in enumerate(meus_agendamentos, start=1):
            nova_ordem = st.number_input(
                f"Ordem de execução para {cliente['nome_completo']}",
                min_value=1,
                max_value=len(meus_agendamentos),
                value=cliente.get("ordem_execucao", idx),
                key=f"ordem_{cliente['_id']}"
            )
            if nova_ordem != cliente.get("ordem_execucao", idx):
                if st.button("💾 Salvar Ordem", key=f"salvar_ordem_{cliente['_id']}"):
                    clientes_collection.update_one(
                        {"_id": cliente["_id"]},
                        {"$set": {"ordem_execucao": nova_ordem}}
                    )
                    st.rerun()
        st.info("💡 A lista será reordenada após atualização.")
