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
# FUNCAO PARA EXTRAIR VALOR DO PLANO (CORRIGIDA)
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
    
    # Busca padrao: numero com virgula apos ":" ou "R$"
    match = re.search(r'(?:R?\$?\s*|:\s*)([0-9]+,[0-9]{2})', plano_nome)
    if match:
        return match.group(1)
    
    # Fallback: busca qualquer numero com virgula no texto
    match = re.search(r'([0-9]+,[0-9]{2})', plano_nome)
    if match:
        return match.group(1)
    
    return "0,00"

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

# Fallback: se o arquivo nao existir, usa o template embutido com caracteres simples
if not TERMO_ADESAO_TEMPLATE:
    TERMO_ADESAO_TEMPLATE = """TERMO DE ADESAO - CONTRATO DE PRESTACAO DE SERVICOS DE COMUNICACAO MULTIMIDIA - SCM E SERVICOS DE VALOR ADICIONADO - SVA

As partes abaixo mencionadas, especialmente o CONTRATANTE, tiveram total acesso ao CONTRATO DE PRESTACAO DE SCM - SERVICOS DE COMUNICACAO MULTIMIDIA e ao CONTRATO DE PRESTACAO DE SERVICOS DE VALOR ADICIONADO - SVA, que estao disponibilizados no site da CONTRATADA ({{ site_empresa }}), CONCORDANDO ambas as partes com todos os termos desses contratos, suas clausulas e condicoes.

================================================================================
                              1. QUALIFICACAO DAS PARTES
================================================================================

CONTRATADA:
Razao Social: {{ razao_social }}
CNPJ: {{ cnpj_empresa }}
Endereco: {{ endereco_empresa }}, {{ numero_empresa }} - {{ bairro_empresa }}
Cidade: {{ cidade_empresa }} - {{ estado_empresa }} | CEP: {{ cep_empresa }}
Telefone: {{ telefone_empresa }} | E-mail: {{ email_empresa }}
Site: {{ site_empresa }}
Autorizacao ANATEL: {{ anatel_autorizacao }}

CONTRATANTE:
Nome: {{ nome_completo }}
CPF: {{ cpf }}
RG: {{ rg or 'Nao informado' }}
Data de Nascimento: {{ data_nascimento or 'Nao informado' }}
Telefone: {{ celular }}
E-mail: {{ email or 'Nao informado' }}

ENDERECO DE INSTALACAO:
{{ endereco }}, {{ numero }}
{% if complemento %}Complemento: {{ complemento }}{% endif %}
{% if condominio_nome %}Condominio: {{ condominio_nome }}{% endif %}
{% if bloco %}Bloco: {{ bloco }}{% endif %}
{% if apartamento %}Apartamento: {{ apartamento }}{% endif %}
Bairro: {{ bairro }} | Cidade: {{ cidade }}
CEP: {{ cep or 'Nao informado' }}
Ponto de Referencia: {{ ponto_referencia or 'Nao informado' }}

================================================================================
                              2. DO OBJETO E PLANO CONTRATADO
================================================================================

O presente contrato tem como objeto a prestacao, pela CONTRATADA, do Servico de Comunicacao Multimidia (SCM) - Internet, conforme plano detalhado abaixo:

PLANO CONTRATADO:
{{ plano_escolhido }}

CARACTERISTICAS TECNICAS:
- Tecnologia: {{ tecnologia or 'Fibra Optica' }}
- Prazo para Instalacao: {{ prazo_instalacao or '10' }} dias uteis
- Vigencia Contratual: {{ vigencia_contratual or '12' }} meses

================================================================================
                              3. VALORES E CONDICOES DE PAGAMENTO
================================================================================

-----------------------------------------------------------+------------------
DESCRICAO                                                  | VALOR (R$)
-----------------------------------------------------------+------------------
Mensalidade                                                | {{ valor_mensal }}
Taxa de Instalacao                                         | {{ valor_instalacao or '0,00' }}
Vencimento                                                 | Dia {{ data_vencimento }} de cada mes
Forma de Pagamento                                         | {{ forma_pagamento or 'Boleto Bancario' }}
-----------------------------------------------------------+------------------
JUROS E MULTAS:                                            |
Juros Moratorios                                           | 1% ao mes
Multa por Atraso                                           | 2%
Reajuste Anual                                             | {{ indice_correcao or 'IPCA' }}
-----------------------------------------------------------+------------------

================================================================================
                              4. SERVICOS DE VALOR ADICIONADO (SVA)
================================================================================

O CONTRATANTE declara ciencia de que Servicos de Valor Adicionado (SVA) podem estar inclusos no plano contratado, conforme descrito na nomenclatura do plano escolhido.

Todos os detalhes, regras e condicoes dos SVA estao disponiveis no CONTRATO DE PRESTACAO DE SERVICOS DE VALOR ADICIONADO - SVA, disponivel no site da CONTRATADA, que o CONTRATANTE declara ter tido acesso.

================================================================================
                              5. EQUIPAMENTOS EM COMODATO
================================================================================

A CONTRATADA disponibiliza ao CONTRATANTE, em regime de comodato, o(s) seguinte(s) equipamento(s):

Equipamento(s): {{ equipamento_descricao or 'Roteador Wi-Fi' }}
Modelo: {{ equipamento_modelo }}
Acessorios: {{ equipamento_acessorios or 'Fonte de alimentacao, cabo Ethernet' }}

O CONTRATANTE declara que recebeu o(s) equipamento(s) acima e se compromete a devolve-lo(s) no final do contrato nas condicoes em que lhe foram entregues, salvo desgaste natural.

================================================================================
                              6. CONTRATO DE PERMANENCIA / FIDELIDADE
================================================================================

O CONTRATANTE declara que teve conhecimento do CONTRATO DE PERMANENCIA / TERMO DE FIDELIDADE e:

{% if optou_fidelidade %}
( X ) OPTOU PELA FIDELIDADE / CONTRATO DE PERMANENCIA (12 meses)
(   ) NAO OPTOU PELA FIDELIDADE / CONTRATO DE PERMANENCIA

CONDICOES DA FIDELIDADE:
- Prazo minimo: 12 meses
- Multa por rescissao antecipada: ate 30% sobre o valor das parcelas vincendas
- Beneficios aplicaveis: descontos e condicoes especiais conforme plano contratado
{% else %}
(   ) OPTOU PELA FIDELIDADE / CONTRATO DE PERMANENCIA (12 meses)
( X ) NAO OPTOU PELA FIDELIDADE / CONTRATO DE PERMANENCIA

CONDICOES SEM FIDELIDADE:
- Contrato por prazo indeterminado
- Cancelamento a qualquer momento, sem multa
- Valor integral do plano aplicado
{% endif %}

================================================================================
                              7. DISPOSICOES GERAIS E OBSERVACOES
================================================================================

- A Contratada tera o prazo de {{ prazo_viabilidade or '10' }} dias para concluir a analise de viabilidade tecnica. Caso constatada a inviabilidade tecnica, o contrato sera cancelado automaticamente sem qualquer onus para ambas as partes.

- O Contratante declara ter conhecimento que a medicao da banda contratada atraves de aparelhos WI-FI pode variar, e que o correto e medir por meio de equipamentos via cabo.

- O Contratante esta ciente dos motivos que podem culminar na degradacao dos servicos, conforme previsto nos contratos disponiveis no site.

- Este Termo de Adesao, juntamente com os CONTRATOS DE PRESTACAO DE SCM E SVA disponiveis no site da CONTRATADA, constituem o acordo integral entre as partes.

================================================================================
                              8. DECLARACAO DE CONCORDANCIA
================================================================================

Declaro, para os devidos fins, que sao corretos os dados cadastrais e informacoes por mim prestadas neste instrumento.

Declaro estar ciente que a assinatura deste instrumento representa expressa concordancia aos termos e condicoes dos CONTRATOS DE PRESTACAO DE SCM E SVA, disponiveis no site da Contratada.

Declaro que tive previo acesso a todas as informacoes relativas aos contratos mencionados, bem como ao plano de servico por mim ora contratado.

Declaro que o presente documento, juntamente com os contratos mencionados, formam um unico instrumento contratual.

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
                        10. FORO DE ELEICAO
================================================================================

As partes elegem o foro da comarca de {{ cidade_empresa }}/{{ estado_empresa }} para dirimir quaisquer duvidas ou controversias oriundas do presente contrato, com expressa renuncia a qualquer outro, por mais privilegiado que seja.
"""

# ============================================================================
# FUNCAO AUXILIAR PARA CONVERTER TEXTO PARA LATIN-1
# ============================================================================
def safe_latin1_encode(texto):
    """
    Converte texto para latin-1 substituindo caracteres não suportados.
    """
    try:
        return texto.encode('latin-1').decode('latin-1')
    except UnicodeEncodeError:
        # Substitui caracteres problemáticos
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
        # Tenta novamente
        return texto.encode('latin-1', errors='replace').decode('latin-1')

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
    Gera o PDF do Termo de Adesao Unificado (SCM + referencia SVA)
    Usa dados do cliente + dados da empresa
    """
    if not TERMO_ADESAO_TEMPLATE:
        return None
    
    try:
        # Dados base da empresa
        dados = DADOS_EMPRESA.copy()
        
        # Mesclar com os dados do cliente (cliente tem prioridade)
        dados.update(dados_cliente)
        
        # Garantir campos obrigatorios
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
            # Converter para latin-1 com seguranca
            linha_segura = safe_latin1_encode(linha)
            pdf.multi_cell(0, 6, linha_segura)
        
        return pdf.output(dest='S').encode('latin1')
    
    except Exception as e:
        st.error(f"Erro ao gerar termo de adesao: {e}")
        return None
