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
    "razao_social": "Tracecom Soluções em Ti Infraestrutura e Telecomunicações Ltda.",
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
    "anatel_autorizacao": "Ato nº. 123456/2023",
    "forma_pagamento": "Boleto Bancário",
    "indice_correcao": "IPCA",
    "tecnologia": "Fibra Óptica",
    "prazo_instalacao": "10",
    "vigencia_contratual": "12",
    "prazo_viabilidade": "10",
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
    "600MB+Tracecanais+Telecine+Premiere: 159,97",
    "600MB+Canais: 69,99",
    "600MB+Trace Canais Novo: 99,99",
    "800MB+Trace Canais Novo: 99,99",
    "800MB+Canais: 69,99",
    "800MB+TraceCanais Básico + 1 Streaming à escolha: 99,99",
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
# FUNÇÃO PARA EXTRAIR VALOR DO PLANO (CORRIGIDA)
# ============================================================================
def extrair_valor_do_plano(plano_nome):
    """
    Extrai o valor do nome do plano.
    Ex: '600MB: 79,99' -> '79,99'
    Ex: '800MB+Canais: 59,99 Exclusivo Vibe Sunset' -> '59,99'
    Ex: '800MB+Canais: 69,99' -> '69,99'
    """
    if not plano_nome or plano_nome == "Selecione...":
        return "0,00"
    
    # Busca padrão: número com vírgula após ":" ou "R$"
    match = re.search(r'(?:R?\$?\s*|:\s*)([0-9]+,[0-9]{2})', plano_nome)
    if match:
        return match.group(1)
    
    # Fallback: busca qualquer número com vírgula no texto
    match = re.search(r'([0-9]+,[0-9]{2})', plano_nome)
    if match:
        return match.group(1)
    
    return "0,00"

# ============================================================================
# FUNÇÕES PARA CARREGAR TEMPLATES
# ============================================================================
def load_template(filename):
    """Carrega um template de arquivo externo"""
    path = os.path.join("templates", filename)
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    else:
        st.error(f"❌ Template '{filename}' não encontrado em /templates/")
        return ""

# Carrega templates de arquivos externos
CONTRATO_TEMPLATE = load_template("contrato.txt")
TERMO_COMODATO_TEMPLATE = load_template("comodato.txt")
TERMO_ADESAO_TEMPLATE = load_template("termo_adesao.txt")

# Fallback: se o arquivo não existir, usa o template embutido
if not TERMO_ADESAO_TEMPLATE:
    TERMO_ADESAO_TEMPLATE = """TERMO DE ADESÃO - CONTRATO DE PRESTAÇÃO DE SERVIÇOS DE COMUNICAÇÃO MULTIMÍDIA - SCM E SERVIÇOS DE VALOR ADICIONADO - SVA

As partes abaixo mencionadas, especialmente o CONTRATANTE, tiveram total acesso ao CONTRATO DE PRESTAÇÃO DE SCM - SERVIÇOS DE COMUNICAÇÃO MULTIMÍDIA e ao CONTRATO DE PRESTAÇÃO DE SERVIÇOS DE VALOR ADICIONADO - SVA, que estão disponibilizados no site da CONTRATADA ({{ site_empresa }}), CONCORDANDO ambas as partes com todos os termos desses contratos, suas cláusulas e condições.

================================================================================
                              1. QUALIFICAÇÃO DAS PARTES
================================================================================

CONTRATADA:
Razão Social: {{ razao_social }}
CNPJ: {{ cnpj_empresa }}
Endereço: {{ endereco_empresa }}, {{ numero_empresa }} - {{ bairro_empresa }}
Cidade: {{ cidade_empresa }} - {{ estado_empresa }} | CEP: {{ cep_empresa }}
Telefone: {{ telefone_empresa }} | E-mail: {{ email_empresa }}
Site: {{ site_empresa }}
Autorização ANATEL: {{ anatel_autorizacao }}

CONTRATANTE:
Nome: {{ nome_completo }}
CPF: {{ cpf }}
RG: {{ rg or 'Não informado' }}
Data de Nascimento: {{ data_nascimento or 'Não informado' }}
Telefone: {{ celular }}
E-mail: {{ email or 'Não informado' }}

ENDEREÇO DE INSTALAÇÃO:
{{ endereco }}, {{ numero }}
{% if complemento %}Complemento: {{ complemento }}{% endif %}
{% if condominio_nome %}Condomínio: {{ condominio_nome }}{% endif %}
{% if bloco %}Bloco: {{ bloco }}{% endif %}
{% if apartamento %}Apartamento: {{ apartamento }}{% endif %}
Bairro: {{ bairro }} | Cidade: {{ cidade }}
CEP: {{ cep or 'Não informado' }}
Ponto de Referência: {{ ponto_referencia or 'Não informado' }}

================================================================================
                              2. DO OBJETO E PLANO CONTRATADO
================================================================================

O presente contrato tem como objeto a prestação, pela CONTRATADA, do Serviço de Comunicação Multimídia (SCM) - Internet, conforme plano detalhado abaixo:

PLANO CONTRATADO:
{{ plano_escolhido }}

CARACTERÍSTICAS TÉCNICAS:
- Tecnologia: {{ tecnologia or 'Fibra Óptica' }}
- Prazo para Instalação: {{ prazo_instalacao or '10' }} dias úteis
- Vigência Contratual: {{ vigencia_contratual or '12' }} meses

================================================================================
                              3. VALORES E CONDIÇÕES DE PAGAMENTO
================================================================================

┌─────────────────────────────────────────────────────────────────────────────┐
│ DESCRIÇÃO              │ VALOR (R$)                                        │
├─────────────────────────────────────────────────────────────────────────────┤
│ Mensalidade            │ {{ valor_mensal }}                                │
│ Taxa de Instalação     │ {{ valor_instalacao or '0,00' }}                  │
│ Vencimento             │ Dia {{ data_vencimento }} de cada mês             │
│ Forma de Pagamento     │ {{ forma_pagamento or 'Boleto Bancário' }}        │
├─────────────────────────────────────────────────────────────────────────────┤
│ JUROS E MULTAS:                                                           │
│ Juros Moratórios       │ 1% ao mês                                         │
│ Multa por Atraso       │ 2%                                                │
│ Reajuste Anual         │ {{ indice_correcao or 'IPCA' }}                  │
└─────────────────────────────────────────────────────────────────────────────┘

================================================================================
                              4. SERVIÇOS DE VALOR ADICIONADO (SVA)
================================================================================

O CONTRATANTE declara ciência de que Serviços de Valor Adicionado (SVA) podem estar inclusos no plano contratado, conforme descrito na nomenclatura do plano escolhido.

Todos os detalhes, regras e condições dos SVA estão disponíveis no CONTRATO DE PRESTAÇÃO DE SERVIÇOS DE VALOR ADICIONADO - SVA, disponível no site da CONTRATADA, que o CONTRATANTE declara ter tido acesso.

================================================================================
                              5. EQUIPAMENTOS EM COMODATO
================================================================================

A CONTRATADA disponibiliza ao CONTRATANTE, em regime de comodato, o(s) seguinte(s) equipamento(s):

Equipamento(s): {{ equipamento_descricao or 'Roteador Wi-Fi' }}
Modelo: {{ equipamento_modelo }}
Acessórios: {{ equipamento_acessorios or 'Fonte de alimentação, cabo Ethernet' }}

O CONTRATANTE declara que recebeu o(s) equipamento(s) acima e se compromete a devolvê-lo(s) no final do contrato nas condições em que lhe foram entregues, salvo desgaste natural.

================================================================================
                              6. CONTRATO DE PERMANÊNCIA / FIDELIDADE
================================================================================

O CONTRATANTE declara que teve conhecimento do CONTRATO DE PERMANÊNCIA / TERMO DE FIDELIDADE e:

{% if optou_fidelidade %}
( X ) OPTOU PELA FIDELIDADE / CONTRATO DE PERMANÊNCIA (12 meses)
(   ) NÃO OPTOU PELA FIDELIDADE / CONTRATO DE PERMANÊNCIA

CONDIÇÕES DA FIDELIDADE:
- Prazo mínimo: 12 meses
- Multa por rescisão antecipada: até 30% sobre o valor das parcelas vincendas
- Benefícios aplicáveis: descontos e condições especiais conforme plano contratado
{% else %}
(   ) OPTOU PELA FIDELIDADE / CONTRATO DE PERMANÊNCIA (12 meses)
( X ) NÃO OPTOU PELA FIDELIDADE / CONTRATO DE PERMANÊNCIA

CONDIÇÕES SEM FIDELIDADE:
- Contrato por prazo indeterminado
- Cancelamento a qualquer momento, sem multa
- Valor integral do plano aplicado
{% endif %}

================================================================================
                              7. DISPOSIÇÕES GERAIS E OBSERVAÇÕES
================================================================================

- A Contratada terá o prazo de {{ prazo_viabilidade or '10' }} dias para concluir a análise de viabilidade técnica. Caso constatada a inviabilidade técnica, o contrato será cancelado automaticamente sem qualquer ônus para ambas as partes.

- O Contratante declara ter conhecimento que a medição da banda contratada através de aparelhos WI-FI pode variar, e que o correto é medir por meio de equipamentos via cabo.

- O Contratante está ciente dos motivos que podem culminar na degradação dos serviços, conforme previsto nos contratos disponíveis no site.

- Este Termo de Adesão, juntamente com os CONTRATOS DE PRESTAÇÃO DE SCM E SVA disponíveis no site da CONTRATADA, constituem o acordo integral entre as partes.

================================================================================
                              8. DECLARAÇÃO DE CONCORDÂNCIA
================================================================================

Declaro, para os devidos fins, que são corretos os dados cadastrais e informações por mim prestadas neste instrumento.

Declaro estar ciente que a assinatura deste instrumento representa expressa concordância aos termos e condições dos CONTRATOS DE PRESTAÇÃO DE SCM E SVA, disponíveis no site da Contratada.

Declaro que tive prévio acesso a todas as informações relativas aos contratos mencionados, bem como ao plano de serviço por mim ora contratado.

Declaro que o presente documento, juntamente com os contratos mencionados, formam um único instrumento contratual.

================================================================================
                                    9. ASSINATURA
================================================================================

{{ cidade }}/{{ estado_empresa }}, {{ data_assinatura }}.

__________________________________________________________
Contratada: {{ razao_social }}
Assinatura / Carimbo

__________________________________________________________
Contratante: {{ nome_completo }}
Assinatura

TESTEMUNHAS:

__________________________________________________________
Testemunha 1
Nome: _________________________  CPF: __________________________

__________________________________________________________
Testemunha 2
Nome: _________________________  CPF: __________________________

================================================================================
                        10. FORO DE ELEIÇÃO
================================================================================

As partes elegem o foro da comarca de {{ cidade_empresa }}/{{ estado_empresa }} para dirimir quaisquer dúvidas ou controvérsias oriundas do presente contrato, com expressa renúncia a qualquer outro, por mais privilegiado que seja.
"""

# ============================================================================
# FUNÇÕES DE GERAÇÃO DE PDF
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
            pdf.multi_cell(0, 8, linha)
        
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
            pdf.multi_cell(0, 8, linha)
        
        return pdf.output(dest='S').encode('latin1')
    except Exception as e:
        st.error(f"Erro ao gerar termo de comodato: {e}")
        return None

def gerar_pdf_termo_adesao(dados_cliente):
    """
    Gera o PDF do Termo de Adesão Unificado (SCM + referência SVA)
    Usa dados do cliente + dados da empresa
    """
    if not TERMO_ADESAO_TEMPLATE:
        return None
    
    try:
        # Dados base da empresa
        dados = DADOS_EMPRESA.copy()
        
        # Mesclar com os dados do cliente (cliente tem prioridade)
        dados.update(dados_cliente)
        
        # Garantir campos obrigatórios
        dados.setdefault("valor_mensal", extrair_valor_do_plano(dados.get("plano_escolhido", "")))
        dados.setdefault("optou_fidelidade", True)
        dados.setdefault("data_assinatura", datetime.now().strftime("%d/%m/%Y"))
        dados.setdefault("rg", "Não informado")
        dados.setdefault("data_nascimento", "Não informado")
        dados.setdefault("email", "Não informado")
        dados.setdefault("cep", "Não informado")
        dados.setdefault("ponto_referencia", "Não informado")
        dados.setdefault("complemento", "")
        dados.setdefault("condominio_nome", "")
        dados.setdefault("bloco", "")
        dados.setdefault("apartamento", "")
        dados.setdefault("equipamento_descricao", "Roteador Wi-Fi")
        dados.setdefault("equipamento_modelo", "Não informado")
        dados.setdefault("equipamento_acessorios", "Fonte de alimentação, cabo Ethernet")
        dados.setdefault("valor_instalacao", "0,00")
        
        # Renderizar template
        template = Template(TERMO_ADESAO_TEMPLATE)
        texto = template.render(dados)
        
        # Gerar PDF
        pdf = FPDF()
        pdf.add_page()
        
        # Adiciona logo se existir
        if os.path.exists("logo.png"):
            pdf.image("logo.png", x=10, y=8, w=40)
            pdf.ln(30)
        
        pdf.set_font("Arial", size=9)
        for linha in texto.split("\n"):
            pdf.multi_cell(0, 6, linha)
        
        return pdf.output(dest='S').encode('latin1')
    
    except Exception as e:
        st.error(f"Erro ao gerar termo de adesão: {e}")
        return None
