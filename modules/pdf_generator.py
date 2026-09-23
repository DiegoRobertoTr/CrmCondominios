# modules/pdf_generator.py
import os
import re
import unicodedata
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
# LISTAS ESTÁTICAS
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
    "800Mb por 139,99 e 600Mb por 119,99",
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
# FUNÇÃO PARA EXTRAIR VALOR DO PLANO
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
# ✅ FUNÇÃO ROBUSTA DE SANITIZAÇÃO PARA LATIN-1
# ============================================================================
def safe_latin1_encode(texto):
    """
    Converte texto para latin-1 de forma ROBUSTA:
    1. Normaliza caracteres Unicode (NFKD separa acentos dos caracteres base)
    2. Remove caracteres de controle (exceto \n, \r, \t)
    3. Substitui acentos latinos por equivalentes ASCII
    4. Remove emojis e símbolos que não existem em latin-1
    
    Retorna SEMPRE uma string válida em latin-1.
    """
    if texto is None:
        return ""
    
    if not isinstance(texto, str):
        texto = str(texto)
    
    # Passo 1: Normalizar (NFKD separa "é" em "e" + acento)
    try:
        texto = unicodedata.normalize('NFKD', texto)
    except Exception:
        pass
    
    # Passo 2: Remover caracteres de controle (exceto \n, \r, \t)
    texto = ''.join(
        c for c in texto
        if unicodedata.category(c)[0] != 'C' or c in '\n\r\t'
    )
    
    # Passo 3: Substituições explícitas de caracteres latinos com acento
    substituicoes = {
        'á': 'a', 'à': 'a', 'ã': 'a', 'â': 'a', 'ä': 'a', 'å': 'a',
        'é': 'e', 'è': 'e', 'ê': 'e', 'ë': 'e',
        'í': 'i', 'ì': 'i', 'î': 'i', 'ï': 'i',
        'ó': 'o', 'ò': 'o', 'õ': 'o', 'ô': 'o', 'ö': 'o',
        'ú': 'u', 'ù': 'u', 'û': 'u', 'ü': 'u',
        'ç': 'c', 'ñ': 'n', 'ý': 'y',
        'Á': 'A', 'À': 'A', 'Ã': 'A', 'Â': 'A', 'Ä': 'A', 'Å': 'A',
        'É': 'E', 'È': 'E', 'Ê': 'E', 'Ë': 'E',
        'Í': 'I', 'Ì': 'I', 'Î': 'I', 'Ï': 'I',
        'Ó': 'O', 'Ò': 'O', 'Õ': 'O', 'Ô': 'O', 'Ö': 'O',
        'Ú': 'U', 'Ù': 'U', 'Û': 'U', 'Ü': 'U',
        'Ç': 'C', 'Ñ': 'N', 'Ý': 'Y',
        # Símbolos tipográficos comuns
        '—': '-', '–': '-', '…': '...',
        '"': '"', '"': '"', ''': "'", ''': "'",
        '•': '-', '·': '-', '€': 'EUR', '£': 'GBP',
        '\u00a0': ' ',  # non-breaking space
    }
    for orig, dest in substituicoes.items():
        texto = texto.replace(orig, dest)
    
    # Passo 4: Remover qualquer caractere que ainda não seja latin-1
    texto_limpo = []
    for c in texto:
        try:
            c.encode('latin-1')
            texto_limpo.append(c)
        except UnicodeEncodeError:
            # Remove emojis e símbolos não suportados
            pass
    
    return ''.join(texto_limpo)


# ============================================================================
# FUNÇÕES PARA CARREGAR TEMPLATES
# ============================================================================
def load_template(filename):
    """Carrega um template de arquivo externo com encoding UTF-8."""
    path = os.path.join("templates", filename)
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                conteudo = f.read()
            # Remove BOM se presente
            if conteudo.startswith('\ufeff'):
                conteudo = conteudo[1:]
            return conteudo
        except UnicodeDecodeError:
            # Fallback: tenta latin-1
            with open(path, "r", encoding="latin-1") as f:
                return f.read()
    else:
        st.error(f"Template '{filename}' nao encontrado em /templates/")
        return ""

# Carrega templates
CONTRATO_TEMPLATE = load_template("contrato.txt")
TERMO_COMODATO_TEMPLATE = load_template("comodato.txt")
TERMO_ADESAO_TEMPLATE = load_template("termo_adesao.txt")


# ============================================================================
# CÁLCULO DE MULTAS DECRESCENTES (ROBUSTO)
# ============================================================================
def calcular_multas_decrescentes(beneficio_total_str):
    """Calcula os valores decrescentes de multa baseado no benefício total."""
    try:
        # Limpa formatação: "R$ 600,00" -> "600.00"
        valor_limpo = str(beneficio_total_str)
        valor_limpo = re.sub(r'[R$\s]', '', valor_limpo)
        valor_limpo = valor_limpo.replace(".", "").replace(",", ".")
        base = float(valor_limpo)
        if base <= 0:
            base = 600.00
    except (ValueError, TypeError, AttributeError):
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
# FUNÇÕES DE GERAÇÃO DE PDF
# ============================================================================
def _gerar_pdf_generico(texto_renderizado, tamanho_fonte=10, altura_linha=8):
    """
    Função auxiliar que gera PDF a partir de texto renderizado.
    Aplica sanitização robusta e trata erros por linha.
    """
    pdf = FPDF()
    pdf.add_page()
    
    if os.path.exists("logo.png"):
        try:
            pdf.image("logo.png", x=10, y=8, w=40)
            pdf.ln(30)
        except Exception:
            pass  # Se falhar ao carregar logo, continua sem ele
    
    pdf.set_font("Arial", size=tamanho_fonte)
    
    for i, linha in enumerate(texto_renderizado.split("\n")):
        linha_segura = safe_latin1_encode(linha)
        try:
            pdf.multi_cell(0, altura_linha, linha_segura)
        except Exception as e:
            # Em caso de erro numa linha específica, tenta uma versão ainda mais limpa
            linha_ultra_segura = ''.join(
                c if ord(c) < 256 else '?' for c in linha
            )
            try:
                pdf.multi_cell(0, altura_linha, linha_ultra_segura)
            except Exception:
                # Se ainda falhar, pula a linha
                print(f"[AVISO] Linha {i} ignorada: {e}")
    
    return pdf.output(dest='S').encode('latin-1', errors='replace')


def gerar_pdf_contrato(dados):
    """Gera PDF do contrato e retorna bytes."""
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
        
        return _gerar_pdf_generico(contrato_preenchido, tamanho_fonte=10, altura_linha=8)
    except Exception as e:
        st.error(f"Erro ao gerar contrato: {e}")
        import traceback
        traceback.print_exc()
        return None


def gerar_pdf_comodato(dados):
    """Gera PDF do termo de comodato e retorna bytes."""
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
        
        return _gerar_pdf_generico(termo_preenchido, tamanho_fonte=10, altura_linha=8)
    except Exception as e:
        st.error(f"Erro ao gerar termo de comodato: {e}")
        import traceback
        traceback.print_exc()
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
        
        # ====================================================================
        # ✅ GARANTIR QUE TODOS OS CAMPOS TENHAM VALORES VÁLIDOS
        # ====================================================================
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
        dados.setdefault(
            "beneficio_descricao",
            "Isencao integral da taxa de instalacao, no valor de R$ 600,00 (seiscentos reais)."
        )
        dados.setdefault("modalidade", "Contratacao")
        dados.setdefault("equipamento_adicional_modelo", "")
        dados.setdefault("prazo_instalacao", "10")
        dados.setdefault("vigencia_contratual", "12")
        dados.setdefault("prazo_viabilidade", "10")
        
        # ✅ Garantir que sva_selecionados seja sempre uma lista válida
        if not isinstance(dados.get("sva_selecionados"), list):
            dados["sva_selecionados"] = []
        
        # ✅ Corrigir valores None que possam ter vindo
        for campo in ["valor_promocional", "valor_sem_fidelidade", "valor_com_fidelidade",
                      "beneficio_total", "beneficio_descricao", "modalidade",
                      "equipamento_adicional_modelo", "valor_mensal"]:
            if dados.get(campo) is None:
                if campo == "beneficio_total":
                    dados[campo] = "600,00"
                elif campo == "beneficio_descricao":
                    dados[campo] = "Isencao integral da taxa de instalacao, no valor de R$ 600,00 (seiscentos reais)."
                elif campo == "modalidade":
                    dados[campo] = "Contratacao"
                elif campo == "valor_mensal":
                    dados[campo] = extrair_valor_do_plano(dados.get("plano_escolhido", ""))
                else:
                    dados[campo] = "0,00"
        
        # Calcula as multas decrescentes
        dados.update(calcular_multas_decrescentes(dados["beneficio_total"]))
        
        # Renderiza
        template = Template(TERMO_ADESAO_TEMPLATE)
        texto = template.render(dados)
        
        # ====================================================================
        # ✅ DIAGNÓSTICO (opcional - remova em produção)
        # ====================================================================
        # import sys
        # print(f"[DEBUG] Template: {len(TERMO_ADESAO_TEMPLATE)} chars", file=sys.stderr)
        # print(f"[DEBUG] Renderizado: {len(texto)} chars", file=sys.stderr)
        # problematicos = set(c for c in texto if ord(c) > 255)
        # if problematicos:
        #     print(f"[DEBUG] Chars não-latin1: {problematicos}", file=sys.stderr)
        
        # Gera PDF
        return _gerar_pdf_generico(texto, tamanho_fonte=9, altura_linha=6)
    
    except Exception as e:
        st.error(f"Erro ao gerar termo de adesao: {e}")
        import traceback
        traceback.print_exc()
        return None
