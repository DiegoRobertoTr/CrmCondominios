# modules/pdf_generator.py
import os
import re
import streamlit as st
from jinja2 import Template
from fpdf import FPDF
from datetime import datetime

# ============================================================================
# CONSTANTES DA EMPRESA
# ============================================================================
DADOS_EMPRESA = {
    "razao_social": "Tracecom Solucoes em Ti Infraestrutura e Telecomunicacoes Ltda.",
    "cnpj_empresa": "09.637.271/0001-27",
    "endereco_empresa": "Rua da Empresa",
    "numero_empresa": "100",
    "bairro_empresa": "Centro",
    "cidade_empresa": "Miguel Pereira",
    "estado_empresa": "RJ",
    "cep_empresa": "26900-000",
    "telefone_empresa": "(24) 9XXXX-XXXX",
    "email_empresa": "contato@tracecom.com.br",
    "site_empresa": "www.tracecom.com.br",
    "anatel_autorizacao": "Ato no. 123456/2023",
    "forma_pagamento": "Boleto Bancario",
    "indice_correcao": "IPCA",
    "tecnologia": "Fibra Optica",
    "prazo_instalacao": "10",
    "vigencia_contratual": "12",
    "prazo_viabilidade": "10",
}

# ============================================================================
# CONFIGURAÇÃO DOS TIPOS DE TRATATIVA
# ============================================================================
TIPOS_TRATATIVA = {
    "padrao": {
        "label": "Termo Padrão (Cliente Novo)",
        "secao2_titulo": "2. DO OBJETO E PLANO CONTRATADO",
        "secao2_texto": "O presente contrato tem como objeto a prestação, pela CONTRATADA, do Serviço de Comunicação Multimídia (SCM) - Internet, conforme plano detalhado abaixo:",
        "tem_desconto_promocional": False,
        "tem_troca_roteador": False,
        "tem_wifi_adicional": False,
        "multa_base": "instalacao",
    },
    "novo_com_desconto": {
        "label": "Cliente Novo COM Desconto",
        "secao2_titulo": "2. DO OBJETO E PLANO CONTRATADO",
        "secao2_texto": "O presente contrato tem como objeto a prestação, pela CONTRATADA, do Serviço de Comunicação Multimídia (SCM) - Internet, conforme plano detalhado abaixo:",
        "tem_desconto_promocional": True,
        "tem_troca_roteador": False,
        "tem_wifi_adicional": False,
        "multa_base": "instalacao",
    },
    "upsell_sem_troca": {
        "label": "Upsell SEM Troca de Roteador",
        "secao2_titulo": "2. DO OBJETO E PLANO CONTRATADO",
        "secao2_texto": "O presente Termo formaliza a alteração do plano atualmente contratado pelo CONTRATANTE para o plano de {{ plano_escolhido }}, bem como as condições comerciais e de permanência aplicáveis ao upgrade do serviço.",
        "tem_desconto_promocional": False,
        "tem_troca_roteador": False,
        "tem_wifi_adicional": False,
        "multa_base": "beneficio",
    },
    "upsell_com_troca": {
        "label": "Upsell COM Troca de Roteador",
        "secao2_titulo": "2. DO OBJETO E PLANO CONTRATADO",
        "secao2_texto": "O presente Termo formaliza a alteração do plano atualmente contratado pelo CONTRATANTE para o plano de {{ plano_escolhido }}, bem como as condições comerciais e de permanência aplicáveis ao upgrade do serviço.",
        "tem_desconto_promocional": False,
        "tem_troca_roteador": True,
        "tem_wifi_adicional": False,
        "multa_base": "beneficio",
    },
    "upsell_com_troca_e_desconto": {
        "label": "Upsell COM Troca de Roteador e Desconto",
        "secao2_titulo": "2. DO OBJETO E PLANO CONTRATADO",
        "secao2_texto": "O presente Termo formaliza a alteração do plano atualmente contratado pelo CONTRATANTE para o plano de {{ plano_escolhido }}, bem como as condições comerciais e de permanência aplicáveis ao upgrade do serviço.",
        "tem_desconto_promocional": True,
        "tem_troca_roteador": True,
        "tem_wifi_adicional": False,
        "multa_base": "beneficio",
    },
    "retencao_wifi_adicional": {
        "label": "Retenção Wi-Fi Adicional",
        "secao2_titulo": "2. DO OBJETO E PLANO CONTRATADO (RETENÇÃO/UPGRADE)",
        "secao2_texto": "O presente Termo formaliza a alteração do plano atualmente contratado pelo CONTRATANTE para o plano de {{ plano_escolhido }}, bem como as condições comerciais e de permanência aplicáveis ao upgrade do serviço.",
        "tem_desconto_promocional": False,
        "tem_troca_roteador": False,
        "tem_wifi_adicional": True,
        "multa_base": "beneficio",
    },
    "retencao_upgrade_velocidade": {
        "label": "Retenção / Upgrade de Velocidade",
        "secao2_titulo": "2. DO OBJETO E PLANO CONTRATADO",
        "secao2_texto": "O presente Termo formaliza a alteração do plano atualmente contratado pelo CONTRATANTE para o plano de {{ plano_escolhido }}, bem como as condições comerciais e de permanência aplicáveis ao upgrade do serviço.",
        "tem_desconto_promocional": False,
        "tem_troca_roteador": False,
        "tem_wifi_adicional": False,
        "multa_base": "beneficio",
    },
}

# ============================================================================
# LISTAS ESTATICAS
# ============================================================================
MODELOS_ROTEADORES = [
    "Tp Link Ax3000 Xx530v Wifi 6 Mesh Dual Band Bivolt",
    "Tp-link Ax1800 Wi-fi 6 Dual Band",
    "TP-Link Archer C80",
    "Huawei HG8245H",
    "Huawei EG8145V5",
    "Intelbras Roteador RF 301K",
    "Intelbras WRN 342",
    "Mercusys MW301R",
    "D-Link DIR-842",
    "Asus RT-AX55",
    "MikroTik hAP ac²",
    "Outro modelo (especificar)"
]

PLANOS = [
    "800MB+Canais: 59,99 Exclusivo Vibe Sunset",
    "600MB+Tracecanais+Telecine+Premiere: 159,97",
    "600MB+Canais: 69,99",
    "600MB+Trace Canais Novo: 99,99",
    "800MB+Trace Canais Novo: 99,99",
    "800MB+Canais: 69,99",
    "800MB+TraceCanais Basico + 1 Streaming a escolha: 99,99",
    "600MB+1 APP PREMIUM: 99,99",
    "600MB+Canais+Disney: 109,99",
    "600MB+Canais+Globoplay: 124,99",
    "600MB+Canais+Globoplay+Disney: 129,99",
    "600MB+Canais+Max: 119,99",
    "600MB+Disney: 99,99",
    "600MB+Disney: 109,99",
    "600MB+Disney: 119,99",
    "600MB+Globoplay: 109,99",
    "600MB+Globoplay: 119,99",
    "600MB+Globoplay: 99,99",
    "600MB+Globoplay Premium: 119,99",
    "600MB+HBO Max: 109,99",
    "600MB+HBO Max: 99,99",
    "600MB+Telecine: 119,99",
    "600MB+Trace Canais: 79,99",
    "600MB+Trace Canais: 89,99",
    "600MB+Trace Canais: 99,99",
    "600MB+Trace Canais Novo: 119,99",
    "600MB+Trace Canais Novo: 129,99",
    "600MB+Trace Canais Novo: 139,99",
    "600MB: 79,99",
    "600MB: 109,99",
    "600MB: 129,99",
    "600MB: 69,99",
    "600MB: 89,99",
    "600MB: 99,99",
    "600MB Fidelidade: 99,99",
    "700MB+1 APP STANDARD: 119,99",
    "700MB+1 APP STANDARD+1 PREMIUM: 139,99",
    "700MB+Globoplay: 129,99",
    "700MB+Trace Canais: 89,99",
    "700MB: 129,99",
    "700MB: 89,99",
    "800MB+Disney+Max: 99,99",
    "800MB+Canais+Disney: 122,99",
    "800MB+Canais+Globoplay: 124,99",
    "800MB+Canais+Max: 119,99",
    "800MB+Disney: 129,99",
    "800MB+Globoplay: 119,99",
    "800MB+Globoplay: 124,99",
    "800MB+Globoplay: 129,99",
    "800MB+Globoplay Premium: 144,99",
    "800MB+HBO Max: 129,99",
    "800MB+Max: 122,99",
    "800MB+Telecine: 124,99",
    "800MB+Trace Canais: 109,99",
    "800MB+Trace Canais: 119,99",
    "800MB+Trace Canais Novo: 139,99",
    "800MB+Trace Canais Premium: 139,99",
    "800MB: 110,99",
    "800MB: 109,99",
    "800MB: 119,99",
    "800MB: 129,99",
    "800MB: 89,99",
    "800MB: 99,99"
]

# ============================================================================
# FUNCAO PARA EXTRAIR VALOR DO PLANO
# ============================================================================
def extrair_valor_do_plano(plano_nome):
    """Extrai o valor do nome do plano."""
    if not plano_nome or plano_nome == "Selecione...":
        return "0,00"
    
    match = re.search(r'(?:R?\$?\s*|:\s*)([0-9]+,[0-9]{2})', plano_nome)
    if match:
        return match.group(1)
    
    match = re.search(r'([0-9]+,[0-9]{2})', plano_nome)
    if match:
        return match.group(1)
    
    return "0,00"

# ============================================================================
# FUNCAO AUXILIAR PARA CONVERTER TEXTO PARA LATIN-1
# ============================================================================
def safe_latin1_encode(texto):
    """Converte texto para latin-1 substituindo caracteres não suportados."""
    try:
        return texto.encode('latin-1').decode('latin-1')
    except UnicodeEncodeError:
        texto = texto.replace('á', 'a').replace('à', 'a').replace('ã', 'a').replace('â', 'a')
        texto = texto.replace('é', 'e').replace('è', 'e').replace('ê', 'e')
        texto = texto.replace('í', 'i').replace('ì', 'i').replace('î', 'i')
        texto = texto.replace('ó', 'o').replace('ò', 'o').replace('õ', 'o').replace('ô', 'o')
        texto = texto.replace('ú', 'u').replace('ù', 'u').replace('û', 'u')
        texto = texto.replace('ç', 'c')
        texto = texto.replace('Á', 'A').replace('À', 'A').replace('Ã', 'A').replace('Â', 'A')
        texto = texto.replace('É', 'E').replace('È', 'E').replace('Ê', 'E')
        texto = texto.replace('Í', 'I').replace('Ì', 'I').replace('Î', 'I')
        texto = texto.replace('Ó', 'O').replace('Ò', 'O').replace('Õ', 'O').replace('Ô', 'O')
        texto = texto.replace('Ú', 'U').replace('Ù', 'U').replace('Û', 'U')
        texto = texto.replace('Ç', 'C')
        return texto.encode('latin-1', errors='replace').decode('latin-1')

# ============================================================================
# FUNCOES PARA CARREGAR TEMPLATES
# ============================================================================
def load_template(filename):
    """Carrega um template de arquivo externo"""
    path = os.path.join("templates", filename)
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    else:
        st.error(f"Template '{filename}' nao encontrado em /templates/")
        return ""

# Carrega templates de arquivos externos
CONTRATO_TEMPLATE = load_template("contrato.txt")
TERMO_COMODATO_TEMPLATE = load_template("comodato.txt")
TERMO_ADESAO_TEMPLATE = load_template("termo_adesao.txt")

# ============================================================================
# CÁLCULO DE MULTAS DECRESCENTES
# ============================================================================
def calcular_multas_decrescentes(beneficio_total_str):
    """Calcula os valores decrescentes de multa baseado no benefício total."""
    try:
        base = float(str(beneficio_total_str).replace(".", "").replace(",", "."))
    except:
        base = 600.00
    
    percentuais = {
        11: 92, 10: 83, 9: 75, 8: 67, 7: 58,
        6: 50, 5: 42, 4: 33, 3: 25, 2: 17, 1: 8
    }
    
    resultado = {}
    for meses, pct in percentuais.items():
        valor = base * (pct / 100)
        resultado[f"multa_{meses}"] = f"{valor:.2f}".replace(".", ",")
    
    return resultado

# ============================================================================
# FUNCOES DE GERACAO DE PDF
# ============================================================================
def gerar_pdf_contrato(dados):
    """Gera PDF do contrato e retorna bytes"""
    if not CONTRATO_TEMPLATE:
        return None
    try:
        dados.setdefault("endereco_contratante", "")
        dados.setdefault("numero_contratante", "")
        dados.setdefault("bairro", "")
        dados.setdefault("cidade", "")
        dados.setdefault("condominio_nome", "")
        dados.setdefault("bloco", "")
        dados.setdefault("apartamento", "")

        template = Template(CONTRATO_TEMPLATE)
        contrato_preenchido = template.render(dados)
        pdf = FPDF()
        pdf.add_page()
        
        if os.path.exists("logo.png"):
            pdf.image("logo.png", x=10, y=8, w=40)
            pdf.ln(30)
        
        pdf.set_font("Arial", size=10)
        for linha in contrato_preenchido.split("\n"):
            linha_segura = safe_latin1_encode(linha)
            pdf.multi_cell(0, 8, linha_segura)
        
        return pdf.output(dest='S').encode('latin1')
    except Exception as e:
        st.error(f"Erro ao gerar contrato: {e}")
        return None


def gerar_pdf_comodato(dados):
    """Gera PDF do termo de comodato e retorna bytes"""
    if not TERMO_COMODATO_TEMPLATE:
        return None
    try:
        dados.setdefault("endereco_contratante", "")
        dados.setdefault("numero_contratante", "")
        dados.setdefault("bairro", "")
        dados.setdefault("cidade", "")
        dados.setdefault("condominio_nome", "")
        dados.setdefault("bloco", "")
        dados.setdefault("apartamento", "")

        template = Template(TERMO_COMODATO_TEMPLATE)
        termo_preenchido = template.render(dados)
        pdf = FPDF()
        pdf.add_page()
        
        if os.path.exists("logo.png"):
            pdf.image("logo.png", x=10, y=8, w=40)
            pdf.ln(30)
        
        pdf.set_font("Arial", size=10)
        for linha in termo_preenchido.split("\n"):
            linha_segura = safe_latin1_encode(linha)
            pdf.multi_cell(0, 8, linha_segura)
        
        return pdf.output(dest='S').encode('latin1')
    except Exception as e:
        st.error(f"Erro ao gerar termo de comodato: {e}")
        return None


def gerar_pdf_termo_adesao(dados_cliente):
    """
    Gera o PDF do Termo de Adesão Unificado.
    Adapta o conteúdo conforme o 'tipo_tratativa' selecionado.
    """
    if not TERMO_ADESAO_TEMPLATE:
        return None
    
    try:
        # Dados base da empresa
        dados = DADOS_EMPRESA.copy()
        dados.update(dados_cliente)
        
        # Pega configuração do tipo de tratativa (default = padrão)
        tipo_key = dados.get("tipo_tratativa", "padrao")
        config = TIPOS_TRATATIVA.get(tipo_key, TIPOS_TRATATIVA["padrao"])
        
        # Injeta as configurações no template
        dados["tipo_tratativa_secao2_titulo"] = config["secao2_titulo"]
        dados["tipo_tratativa_secao2_texto"] = Template(config["secao2_texto"]).render(dados)
        dados["tem_desconto_promocional"] = config["tem_desconto_promocional"]
        dados["tem_troca_roteador"] = config["tem_troca_roteador"]
        dados["tem_wifi_adicional"] = config["tem_wifi_adicional"]
        dados["multa_base"] = config["multa_base"]
        
        # Garantir campos obrigatórios com defaults
        dados.setdefault("valor_mensal", extrair_valor_do_plano(dados.get("plano_escolhido", "")))
        dados.setdefault("optou_fidelidade", True)
        dados.setdefault("data_assinatura", datetime.now().strftime("%d/%m/%Y"))
        dados.setdefault("rg", "Nao informado")
        dados.setdefault("data_nascimento", "Nao informado")
        dados.setdefault("email", "Nao informado")
        dados.setdefault("cep", "Nao informado")
        dados.setdefault("ponto_referencia", "Nao informado")
        dados.setdefault("complemento", "")
        dados.setdefault("condominio_nome", "")
        dados.setdefault("bloco", "")
        dados.setdefault("apartamento", "")
        dados.setdefault("equipamento_descricao", "Roteador Wi-Fi")
        dados.setdefault("equipamento_modelo", "Nao informado")
        dados.setdefault("equipamento_acessorios", "Fonte de alimentacao, cabo Ethernet")
        dados.setdefault("valor_instalacao", "0,00")
        dados.setdefault("valor_promocional", "0,00")
        dados.setdefault("valor_sem_fidelidade", "0,00")
        dados.setdefault("valor_com_fidelidade", "0,00")
        dados.setdefault("beneficio_total", "600,00")
        dados.setdefault("beneficio_descricao", "Isencao integral da taxa de instalacao, no valor de R$ 600,00 (seiscentos reais).")
        dados.setdefault("modalidade", "Contratacao")
        dados.setdefault("equipamento_adicional_modelo", "")
        dados.setdefault("sva_selecionados", [])
        dados.setdefault("prazo_instalacao", "10")
        dados.setdefault("vigencia_contratual", "12")
        dados.setdefault("prazo_viabilidade", "10")
        
        # Calcula as multas decrescentes
        dados.update(calcular_multas_decrescentes(dados["beneficio_total"]))
        
        # Renderiza
        template = Template(TERMO_ADESAO_TEMPLATE)
        texto = template.render(dados)
        
        # Gera PDF
        pdf = FPDF()
        pdf.add_page()
        
        if os.path.exists("logo.png"):
            pdf.image("logo.png", x=10, y=8, w=40)
            pdf.ln(30)
        
        pdf.set_font("Arial", size=9)
        for linha in texto.split("\n"):
            linha_segura = safe_latin1_encode(linha)
            pdf.multi_cell(0, 6, linha_segura)
        
        return pdf.output(dest='S').encode('latin1')
    
    except Exception as e:
        st.error(f"Erro ao gerar termo de adesao: {e}")
        return None
