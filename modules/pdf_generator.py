# modules/pdf_generator.py
import os
import streamlit as st
from jinja2 import Template
from fpdf import FPDF

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

# Listas estáticas (podem ser movidas para arquivos também, se desejar)
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
    "PS 100MB+CV+TrC R$79,99",
    "PS 600Mb+TrC: 109,99",
    "PS 800Mb+TrC: 129,99",
    "PS 600Mb + Trc Premium: 149,98",
    "PS 600Mb+TrC+TM+Globo: 119,99",
    "PS 800Mb+TrC+TM+Globo ou Max ou Disney: 139,99",
    "PS 600Mb+TrC: 99,99"
]

def gerar_pdf_contrato(dados):
    """Gera PDF do contrato e retorna bytes"""
    if not CONTRATO_TEMPLATE:
        return None
        
    try:
        # Garante que todos os campos de endereço estejam presentes (mesmo que vazios)
        dados.setdefault("endereco_contratante", "")
        dados.setdefault("numero_contratante", "")
        dados.setdefault("bairro", "")
        dados.setdefault("cidade", "")

        template = Template(CONTRATO_TEMPLATE)
        contrato_preenchido = template.render(dados)
        pdf = FPDF()
        pdf.add_page()
        
        # Adiciona logo se existir
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
        # Garante que todos os campos de endereço estejam presentes (mesmo que vazios)
        dados.setdefault("endereco_contratante", "")
        dados.setdefault("numero_contratante", "")
        dados.setdefault("bairro", "")
        dados.setdefault("cidade", "")

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
