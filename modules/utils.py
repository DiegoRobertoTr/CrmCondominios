import re
from datetime import datetime, timedelta
import streamlit as st

def normalize_phone(phone):
    """Remove todos os caracteres não numéricos do telefone"""
    return re.sub(r'\D', '', phone) if phone else ""

def validar_cpf(cpf):
    """Valida CPF brasileiro"""
    cpf = re.sub(r'[^0-9]', '', cpf)
    if len(cpf) != 11 or cpf == cpf[0] * 11:
        return False
    soma = sum(int(cpf[i]) * (10 - i) for i in range(9))
    digito1 = (soma * 10) % 11
    digito1 = digito1 if digito1 < 10 else 0
    soma = sum(int(cpf[i]) * (11 - i) for i in range(10))
    digito2 = (soma * 10) % 11
    digito2 = digito2 if digito2 < 10 else 0
    return cpf[-2:] == f"{digito1}{digito2}"

def get_followup_date(opcao, mes=None, ano=None, dia=1):
    """Calcula data de follow-up e retorna no formato YYYY-MM-dd para armazenamento"""
    try:
        if opcao == "Personalizado (mês/ano)" and mes and ano:
            data = datetime(ano, mes, dia)
        elif opcao in ["1 dia", "3 dias", "5 dias", "10 dias"]:
            dias = int(opcao.split()[0])
            data = datetime.now() + timedelta(days=dias)
        else:
            return ""
        return data.strftime("%Y-%m-%d")
    except ValueError:
        return ""


# 🔹 🔹 🔹 EXTENSÃO HOTSPOTS — corrigida e compatível com sua nova splash page 🔹 🔹 🔹

def gerar_token_confirmacao():
    """Gera token seguro para confirmação de e-mail (compatível com secrets)"""
    import secrets
    return secrets.token_urlsafe(12)  # ex: "kX9mQz2pLwR8"

def enviar_email_confirmacao(nome, email, token, nome_local):
    """
    Envia e-mail de confirmação usando seu SMTP configurado no Streamlit Cloud.
    Funciona em 2 modos:
      • token != "": modo antigo com confirmação obrigatória
      • token == "": modo splash leve (só agradecimento)
    Retorna True se sucesso, False caso erro.
    """
    import smtplib
    from email.mime.text import MIMEText
    from email.mime.multipart import MIMEMultipart

    # 🔑 Usa EXATAMENTE o que você já configurou no Streamlit Cloud
    try:
        SMTP_SERVER = st.secrets["smtp_server"]
        SMTP_PORT = int(st.secrets["smtp_port"])
        SMTP_USER = st.secrets["smtp_user"]
        SMTP_PASS = st.secrets["smtp_password"]
        USE_TLS = st.secrets.get("smtp_use_tls", "false").lower() == "true"
    except KeyError as e:
        st.error(f"❌ Erro ao carregar configurações SMTP: {e}")
        return False

    # ✅ Corrigido: URL absoluta para o logo (Streamlit Cloud serve arquivos estáticos na raiz)
    logo_url = "https://crmtracecom.streamlit.app/logo.png"

    # Monta link de confirmação (só se houver token)
    link = f"https://crmtracecom.streamlit.app/?page=hotspots/confirmar&token={token}" if token else "https://tracecom.net.br"

    msg = MIMEMultipart("alternative")
    msg["Subject"] = f"{'✅ Confirme seu acesso' if token else '🙏 Obrigado pelo cadastro'} na {nome_local}"
    msg["From"] = "Tracecom Internet <comercial1@tracecom.net.br>"
    msg["To"] = email

    # ✅ HTML adaptativo: mostra botão/token só se necessário
    corpo_html = f"""
    <div style="font-family: 'Segoe UI', Tahoma, sans-serif; max-width: 600px; margin: 20px auto; color: #333;">
      <img src="{logo_url}" alt="Tracecom" width="120" style="display: block; margin-bottom: 20px;">
      <h2 style="color: #2C6E49;">Olá, {nome}!</h2>
      <p>Você se conectou à rede Wi-Fi da <strong>{nome_local}</strong>.</p>
      
      {f'''
      <p>Para liberar seu acesso, confirme seu e-mail:</p>
      
      <div style="background: #f0f8f0; padding: 15px; border-radius: 8px; text-align: center; margin: 20px 0; 
                  font-size: 18px; font-weight: bold; color: #2C6E49; letter-spacing: 2px;">
        {token}
      </div>
      
      <p>Ou clique no botão abaixo:</p>
      <a href="{link}" 
         style="display: inline-block; background: #2C6E49; color: white; padding: 12px 24px; 
                text-decoration: none; border-radius: 6px; font-weight: bold;">
        ✅ Confirmar Acesso
      </a>
      ''' if token else '''
      <p><strong>Obrigado pelo seu cadastro!</strong> Seu acesso à internet já está liberado. 🎉</p>
      <p>Aproveite a navegação — estamos à disposição para o que precisar!</p>
      '''}
      
      <p style="font-size: 13px; color: #666; margin-top: 25px; line-height: 1.5;">
        {f"Este link é válido por <strong>1 hora</strong>.<br>" if token else ""}
        Se não solicitou este acesso, ignore esta mensagem.<br><br>
        — Equipe Tracecom 🌐
      </p>
    </div>
    """

    msg.attach(MIMEText(corpo_html, "html", "utf-8"))

    try:
        if USE_TLS:
            with smtplib.SMTP(SMTP_SERVER, SMTP_PORT) as server:
                server.starttls()
                server.login(SMTP_USER, SMTP_PASS)
                server.send_message(msg)
        else:
            with smtplib.SMTP_SSL(SMTP_SERVER, SMTP_PORT) as server:
                server.login(SMTP_USER, SMTP_PASS)
                server.send_message(msg)
        return True
    except Exception as e:
        print(f"[HotSpots] Erro ao enviar e-mail para {email}: {e}")
        return False


# ✅ Função adicionada para uso em pap.py e cadastro.py
def limpar_cpf(cpf):
    """Remove todos os caracteres não numéricos do CPF e retorna os 11 dígitos ou None se inválido."""
    if not cpf:
        return None
    cpf_puro = re.sub(r'\D', '', cpf)
    return cpf_puro if len(cpf_puro) == 11 else None
