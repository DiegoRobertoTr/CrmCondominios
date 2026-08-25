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

def gerar_pdf_contrato(dados):
    """Gera PDF do contrato e retorna bytes"""
    if not CONTRATO_TEMPLATE:
        return None
    try:
        # Garante que todos os campos estejam presentes (mesmo que vazios)
        dados.setdefault("endereco_contratante", "")
        dados.setdefault("numero_contratante", "")
        dados.setdefault("bairro", "")
        dados.setdefault("cidade", "")
        dados.setdefault("condominio_nome", "")  # 🏢 NOVO
        dados.setdefault("bloco", "")  # 🏢 NOVO
        dados.setdefault("apartamento", "")  # 🏢 NOVO

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
        # Garante que todos os campos estejam presentes (mesmo que vazios)
        dados.setdefault("endereco_contratante", "")
        dados.setdefault("numero_contratante", "")
        dados.setdefault("bairro", "")
        dados.setdefault("cidade", "")
        dados.setdefault("condominio_nome", "")  # 🏢 NOVO
        dados.setdefault("bloco", "")  # 🏢 NOVO
        dados.setdefault("apartamento", "")  # 🏢 NOVO

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
