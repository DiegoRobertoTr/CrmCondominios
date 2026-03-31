# modules/pap.py
import streamlit as st
from datetime import datetime
import base64
import re
from urllib.parse import quote
from .utils import normalize_phone, limpar_cpf as limpar_cpf_util
from .pdf_generator import gerar_pdf_contrato, gerar_pdf_comodato, MODELOS_ROTEADORES, PLANOS

WHATSAPP_LOJA = "5524992035540"

def gerar_codigo_indicacao():
    import random, string
    numeros = ''.join(random.choices(string.digits, k=6))
    letras = ''.join(random.choices(string.ascii_uppercase, k=3))
    return f"Trace{numeros}{letras}"

def montar_endereco_completo(endereco, numero, complemento=""):
    partes = [p.strip() for p in [endereco, numero] if p]
    res = " - ".join(partes)
    if complemento.strip():
        res += f" ({complemento.strip()})"
    return res

def safe_strip_codigo_indicador(texto):
    return texto.strip() if isinstance(texto, str) and texto.strip() else None

def gerar_link_whatsapp_solicitacao(nome, celular, cpf=None):
    """Gera um link do WhatsApp com mensagem pré-formatada para análise de cadastro."""
    cpf_texto = f"\nCPF: {cpf}" if cpf else ""
    mensagem = f"Temos um cadastro novo:\nNome: {nome}\nTelefone: {celular}{cpf_texto}"
    mensagem_codificada = quote(mensagem)
    return f"https://wa.me/{WHATSAPP_LOJA}?text={mensagem_codificada}"

def render_pap(clientes_collection):
    st.session_state["clientes_collection"] = clientes_collection

    # Inicializa estados
    if "form_key_pap" not in st.session_state:
        st.session_state["form_key_pap"] = 0
    if "gerando_contrato_pap" not in st.session_state:
        st.session_state["gerando_contrato_pap"] = False
    if "contrato_pronto_pap" not in st.session_state:
        st.session_state["contrato_pronto_pap"] = False
    if "gerando_comodato_pap" not in st.session_state:
        st.session_state["gerando_comodato_pap"] = False
    if "comodato_pronto_pap" not in st.session_state:
        st.session_state["comodato_pronto_pap"] = False
    if "ignorar_bloqueio_pap" not in st.session_state:
        st.session_state["ignorar_bloqueio_pap"] = False
    if "endereco_bloqueado_confirmado_pap" not in st.session_state:
        st.session_state["endereco_bloqueado_confirmado_pap"] = {}

    st.title("📝 Cadastro Porta a Porta (PaP)")
    st.info("⚠️ Você só pode realizar **novos cadastros completos**. Não é possível buscar, editar ou visualizar outros clientes.")

    # ➕ EXIBE BOTÃO DE WHATSAPP SE HOUVER CADASTRO RECENTE
    if "ultimo_cadastro_pap" in st.session_state:
        dados = st.session_state["ultimo_cadastro_pap"]
        link_whatsapp = gerar_link_whatsapp_solicitacao(
            dados["nome"],
            dados["celular"],
            dados.get("cpf")
        )
        st.markdown(
            f'<a href="{link_whatsapp}" target="_blank" '
            f'style="display: inline-block; padding: 0.5em 1em; background-color: #25D366; '
            f'color: white; text-decoration: none; border-radius: 5px; font-weight: bold; margin-bottom: 1em;">'
            f'📲 Solicitar Análise</a>',
            unsafe_allow_html=True
        )

        # Botão "Novo Cadastro" — igual ao cadastro.py
        if st.button("➕ Novo Cadastro", type="secondary", key="novo_cadastro_pap"):
            # Limpa tudo relacionado ao último cadastro e ao formulário
            if "ultimo_cadastro_pap" in st.session_state:
                del st.session_state["ultimo_cadastro_pap"]
            keys_to_clear = [
                "dados_temp_pap",
                "ignorar_bloqueio_pap",
                "endereco_bloqueado_confirmado_pap",
                "gerando_contrato_pap",
                "contrato_pronto_pap",
                "gerando_comodato_pap",
                "comodato_pronto_pap"
            ]
            for k in keys_to_clear:
                st.session_state.pop(k, None)
            st.session_state["form_key_pap"] += 1
            st.rerun()

        # Não mostra o formulário se já salvou (até clicar em "Novo Cadastro")
        return

    # --- Formulário de cadastro único ---
    st.subheader("📝 Cadastro CRM (Completo)")

    def get_valor_inicial(chave, default=""):
        return st.session_state.get("dados_temp_pap", {}).get(chave, default)

    nome_completo = st.text_input(
        "Nome completo *",
        value=get_valor_inicial("nome_completo", ""),
        key=f"nome_completo_pap_{st.session_state['form_key_pap']}"
    )

    col_tel1, col_tel2, col_tel3 = st.columns(3)
    with col_tel1:
        celular_principal = st.text_input(
            "Celular Principal *",
            max_chars=15,
            placeholder="(00) 90000-0000",
            value=get_valor_inicial("celular_principal", ""),
            key=f"celular_pap_{st.session_state['form_key_pap']}"
        )
    with col_tel2:
        celular_contato_1 = st.text_input(
            "Contato 1",
            max_chars=15,
            placeholder="(00) 90000-0000",
            value=get_valor_inicial("celular_contato_1", ""),
            key=f"contato1_pap_{st.session_state['form_key_pap']}"
        )
        descricao_contato_1 = st.text_input(
            "Quem é esse contato?",
            max_chars=30,
            placeholder="Ex: Esposa",
            value=get_valor_inicial("descricao_contato_1", ""),
            key=f"desc1_pap_{st.session_state['form_key_pap']}"
        )
    with col_tel3:
        celular_contato_2 = st.text_input(
            "Contato 2",
            max_chars=15,
            placeholder="(00) 90000-0000",
            value=get_valor_inicial("celular_contato_2", ""),
            key=f"contato2_pap_{st.session_state['form_key_pap']}"
        )
        descricao_contato_2 = st.text_input(
            "Quem é esse contato?",
            max_chars=30,
            placeholder="Ex: Mãe",
            value=get_valor_inicial("descricao_contato_2", ""),
            key=f"desc2_pap_{st.session_state['form_key_pap']}"
        )

    cpf_raw = st.text_input(
        "CPF *",
        max_chars=14,
        placeholder="000.000.000-00",
        value=get_valor_inicial("cpf", ""),
        key=f"cpf_pap_{st.session_state['form_key_pap']}"
    )
    cpf_limpo = re.sub(r'\D', '', cpf_raw)
    if len(cpf_limpo) == 11:
        dup = clientes_collection.find_one({"cpf": cpf_limpo})
        if dup:
            st.warning(f"⚠️ CPF já cadastrado: **{dup.get('nome_completo', '—')}**")

    with st.container(border=True):
        st.markdown("### 📌 Informações de Origem")
        origem_opcoes = ["Selecione...", "Radio Show FM", "Opa Suite", "Whatsapp", "Instagram", "Indicação", "Loja", "Panfleto", "PaP", "Ex Cliente", "Prospecção Ativa (Zap, Email, Telegram)", "Facebook", "Site"]
        origem = st.selectbox(
            "De onde veio?",
            origem_opcoes,
            index=origem_opcoes.index(get_valor_inicial("origem", "PaP")) if get_valor_inicial("origem") in origem_opcoes else origem_opcoes.index("PaP"),
            key=f"origem_pap_{st.session_state['form_key_pap']}"
        )

        restritivo = st.selectbox(
            "Restritivo?",
            ["Selecione...", "Sim", "Não"],
            index=["Selecione...", "Sim", "Não"].index(get_valor_inicial("restritivo", "Selecione...")),
            key=f"restritivo_pap_{st.session_state['form_key_pap']}"
        )

        if restritivo == "Sim":
            st.markdown("### ⚠️ Informações sobre Restrição")
            col1, col2, col3 = st.columns(3)
            with col1:
                qtd_registros = st.selectbox("Quantos registros?", list(range(1, 31)), index=0, key=f"qtd_pap_{st.session_state['form_key_pap']}")
            with col2:
                ano_atual = datetime.now().year
                ano_recente = st.selectbox("Qual ano mais recente?", list(range(2020, ano_atual + 1)), index=ano_atual - 2020, key=f"ano_pap_{st.session_state['form_key_pap']}")
            with col3:
                servico_internet = st.selectbox("Serviço de internet?", ["Sim", "Não"], index=0, key=f"serv_pap_{st.session_state['form_key_pap']}")
        else:
            qtd_registros = ano_recente = servico_internet = None

        seguiu_ativacao = st.selectbox(
            "Seguiu para Ativação?",
            ["Selecione...", "Sim", "Não"],
            index=["Selecione...", "Sim", "Não"].index(get_valor_inicial("seguiu_ativacao", "Selecione...")),
            key=f"ativacao_pap_{st.session_state['form_key_pap']}"
        )

        OPCOES_INTERNET = ["Selecione...", "Giga+", "Internet10", "TR Telecom", "Claro", "Não possui"]
        ja_possui_internet = st.selectbox(
            "Já Possui Internet?",
            OPCOES_INTERNET,
            index=OPCOES_INTERNET.index(get_valor_inicial("ja_possui_internet", "Selecione...")) if get_valor_inicial("ja_possui_internet") in OPCOES_INTERNET else 0,
            key=f"internet_pap_{st.session_state['form_key_pap']}"
        )

        codigo_indicador = st.text_input(
            "Código de Quem Indicou",
            max_chars=15,
            value=get_valor_inicial("codigo_indicador", ""),
            key=f"cod_ind_pap_{st.session_state['form_key_pap']}"
        )

        observacoes = st.text_area(
            "Observações Gerais",
            placeholder="Ex: Cliente interessado em plano familiar.",
            value=get_valor_inicial("observacoes", ""),
            key=f"obs_pap_{st.session_state['form_key_pap']}"
        )

    col1, col2 = st.columns(2)
    with col1:
        rg = st.text_input("RG *", max_chars=15, placeholder="12.345.678-9", value=get_valor_inicial("rg", ""), key=f"rg_pap_{st.session_state['form_key_pap']}")
    with col2:
        data_nascimento = st.date_input("Data de nascimento *", format="DD/MM/YYYY", min_value=datetime(1900,1,1), key=f"nasc_pap_{st.session_state['form_key_pap']}")

    email = st.text_input("Email *", value=get_valor_inicial("email", ""), key=f"email_pap_{st.session_state['form_key_pap']}")

    col1, col2 = st.columns([3, 1])
    with col1:
        endereco = st.text_input("Endereço *", value=get_valor_inicial("endereco", ""), key=f"end_pap_{st.session_state['form_key_pap']}")
    with col2:
        numero = st.text_input("Número *", max_chars=6, value=get_valor_inicial("numero", ""), key=f"num_pap_{st.session_state['form_key_pap']}")

    col1, col2 = st.columns(2)
    with col1:
        complemento = st.text_input("Complemento", value=get_valor_inicial("complemento", ""), key=f"comp_pap_{st.session_state['form_key_pap']}")
    with col2:
        cidade = st.text_input("Cidade *", value=get_valor_inicial("cidade", "Paraiba do Sul"), key=f"cid_pap_{st.session_state['form_key_pap']}")

    col1, col2 = st.columns(2)
    with col1:
        bairro = st.text_input("Bairro *", value=get_valor_inicial("bairro", ""), key=f"bairro_pap_{st.session_state['form_key_pap']}")
    with col2:
        ponto_referencia = st.text_input("Ponto de referência", value=get_valor_inicial("ponto_ref", ""), key=f"ref_pap_{st.session_state['form_key_pap']}")

    plano_atual = get_valor_inicial("plano_escolhido", "")
    index_plano = (PLANOS.index(plano_atual) + 1) if plano_atual in PLANOS else 0
    plano_escolhido = st.selectbox(
        "Plano escolhido *",
        ["Selecione..."] + PLANOS,
        index=index_plano,
        key=f"plano_pap_{st.session_state['form_key_pap']}"
    )

    profissao = st.text_input("Profissão *", value=get_valor_inicial("profissao", ""), key=f"prof_pap_{st.session_state['form_key_pap']}")
    data_vencimento = st.selectbox("Melhor data de vencimento *", list(range(1, 32)), index=0, key=f"venc_pap_{st.session_state['form_key_pap']}")

    st.subheader("1️⃣ Foto segurando documento com foto (RG, CNH, etc) - Opcional")
    foto_documento = st.file_uploader("Envie a foto aqui (JPG ou PNG)", type=["jpg", "png", "jpeg"], key=f"foto_pap_{st.session_state['form_key_pap']}")

    st.subheader("📦 Equipamento em Comodato (opcional)")
    equip_desc = st.text_input("Descrição do Equipamento", value="Roteador Wi-Fi", key=f"equip_desc_pap_{st.session_state['form_key_pap']}")
    modelo_atual = get_valor_inicial("equip_modelo", "")
    index_modelo = MODELOS_ROTEADORES.index(modelo_atual) if modelo_atual in MODELOS_ROTEADORES else 0
    equip_modelo = st.selectbox("Marca/Modelo*", MODELOS_ROTEADORES, index=index_modelo, key=f"equip_mod_pap_{st.session_state['form_key_pap']}")
    equip_codigo = st.text_input("Informação Adicional*", placeholder="Ex: Número de série", value="", key=f"equip_cod_pap_{st.session_state['form_key_pap']}")
    equip_acessorios = st.text_input("Acessórios", value="Fonte de alimentação, cabo Ethernet", key=f"equip_acc_pap_{st.session_state['form_key_pap']}")

    # Botões de contrato/comodato
    col1, col2 = st.columns(2)
    with col1:
        if st.session_state["gerando_contrato_pap"]:
            st.button("⏳ Gerando contrato...", disabled=True)
        elif st.session_state["contrato_pronto_pap"]:
            st.download_button("📥 Baixar Contrato", data=st.session_state["contrato_bytes_pap"], file_name=st.session_state["contrato_nome_pap"], mime="application/pdf")
        else:
            if st.button("✍️ Gerar Contrato"):
                cpf_valido = limpar_cpf_util(cpf_raw)
                if not cpf_valido:
                    st.error("❌ CPF inválido!")
                elif not all([nome_completo, cpf_valido, endereco, celular_principal, plano_escolhido != "Selecione..."]):
                    st.error("❌ Preencha todos os campos obrigatórios!")
                else:
                    dados = {
                        "nome_contratante": nome_completo,
                        "cpf_cnpj_contratante": cpf_valido,
                        "endereco_contratante": endereco,
                        "numero_contratante": numero,
                        "complemento": complemento,
                        "cidade": cidade,
                        "bairro": bairro,
                        "telefone_contratante": celular_principal,
                        "plano_contratado": plano_escolhido,
                        "modalidade": "Pós Pago"
                    }
                    st.session_state["dados_contrato_pap"] = dados
                    st.session_state["gerando_contrato_pap"] = True
                    st.session_state["contrato_nome_pap"] = f"Contrato_{nome_completo.replace(' ', '_')}.pdf"
                    st.rerun()

    with col2:
        if st.session_state["gerando_comodato_pap"]:
            st.button("⏳ Gerando termo...", disabled=True)
        elif st.session_state["comodato_pronto_pap"]:
            st.download_button("📥 Baixar Termo", data=st.session_state["comodato_bytes_pap"], file_name=st.session_state["comodato_nome_pap"], mime="application/pdf")
        else:
            if st.button("📄 Gerar Termo de Comodato"):
                cpf_valido = limpar_cpf_util(cpf_raw)
                if not cpf_valido:
                    st.error("❌ CPF inválido!")
                elif not all([nome_completo, cpf_valido, endereco, celular_principal, equip_modelo, equip_codigo]):
                    st.error("❌ Preencha campos obrigatórios do comodato!")
                else:
                    dados = {
                        "nome_contratante": nome_completo,
                        "cpf_cnpj_contratante": cpf_valido,
                        "endereco_contratante": endereco,
                        "numero_contratante": numero,
                        "complemento": complemento,
                        "cidade": cidade,
                        "bairro": bairro,
                        "telefone_contratante": celular_principal,
                        "equipamento_descricao": equip_desc,
                        "equipamento_modelo": equip_modelo,
                        "equipamento_codigo": equip_codigo,
                        "equipamento_acessorios": equip_acessorios
                    }
                    st.session_state["dados_comodato_pap"] = dados
                    st.session_state["gerando_comodato_pap"] = True
                    st.session_state["comodato_nome_pap"] = f"Termo_Comodato_{nome_completo.replace(' ', '_')}.pdf"
                    st.rerun()

    # Salvar cadastro
    if st.button("💾 Salvar Cadastro Completo", type="primary"):
        if not nome_completo or not celular_principal or plano_escolhido == "Selecione...":
            st.error("⚠️ Nome, celular e plano são obrigatórios.")
        else:
            endereco_salvo = endereco.strip()
            numero_salvo = numero.strip()
            if endereco_salvo and numero_salvo:
                cliente_bloqueado = clientes_collection.find_one({
                    "endereco": endereco_salvo,
                    "numero": numero_salvo,
                    "endereco_bloqueado": True
                })
                conf = st.session_state.get("endereco_bloqueado_confirmado_pap", {})
                confirmado = conf.get("endereco") == endereco_salvo and conf.get("numero") == numero_salvo
                if cliente_bloqueado and not st.session_state.get("ignorar_bloqueio_pap", False) and not confirmado:
                    st.error("❌ Endereço bloqueado! Use o botão 'Continuar mesmo assim' se necessário.")
                    return

            cpf_valido = limpar_cpf_util(cpf_raw)
            foto_base64 = ""
            if foto_documento:
                foto_bytes = foto_documento.read()
                foto_base64 = base64.b64encode(foto_bytes).decode('utf-8')

            codigo_indicacao = None
            if seguiu_ativacao == "Sim":
                codigo_indicacao = gerar_codigo_indicacao()

            cliente_data = {
                "nome_completo": nome_completo,
                "celular": normalize_phone(celular_principal),
                "celular_contato_1": normalize_phone(celular_contato_1) if celular_contato_1.strip() else None,
                "celular_contato_2": normalize_phone(celular_contato_2) if celular_contato_2.strip() else None,
                "descricao_contato_1": descricao_contato_1.strip() if descricao_contato_1.strip() else None,
                "descricao_contato_2": descricao_contato_2.strip() if descricao_contato_2.strip() else None,
                "email": email if email else None,
                "data_nascimento": data_nascimento.isoformat(),
                "cpf": cpf_valido,
                "rg": rg if rg else None,
                "endereco": endereco if endereco else None,
                "numero": numero if numero else None,
                "complemento": complemento if complemento else None,
                "cidade": cidade if cidade else None,
                "bairro": bairro if bairro else None,
                "ponto_referencia": ponto_referencia if ponto_referencia else None,
                "plano_escolhido": plano_escolhido,
                "profissao": profissao if profissao else None,
                "data_vencimento": data_vencimento,
                "foto_documento_base64": foto_base64,
                "data_cadastro": datetime.now(),
                "tipo_cadastro": "completo",
                "status": "novo",
                "cadastrado_por": st.session_state.get("nome_usuario", "PaP"),
                "origem": origem if origem != "Selecione..." else "PaP",
                "restritivo": restritivo if restritivo != "Selecione..." else " ",
                "restritivo_qtd_registros": qtd_registros if restritivo == "Sim" else None,
                "restritivo_ano_recente": ano_recente if restritivo == "Sim" else None,
                "restritivo_servico_internet": servico_internet if restritivo == "Sim" else None,
                "seguiu_ativacao": seguiu_ativacao if seguiu_ativacao != "Selecione..." else " ",
                "ja_possui_internet": ja_possui_internet if ja_possui_internet != "Selecione..." else " ",
                "retorno_agendado": " ",
                "observacoes": observacoes if observacoes else " ",
                "observacoes_followup": "",
                "codigo_indicacao": codigo_indicacao,
                "codigo_indicador": safe_strip_codigo_indicador(codigo_indicador),
                "endereco_bloqueado": False,
                "observacoes_bloqueio_endereco": None,
            }

            try:
                clientes_collection.insert_one(cliente_data)
                st.success("✅ Cadastro salvo com sucesso!")
                st.balloons()

                # ✅ Armazena dados para exibir WhatsApp após rerun
                st.session_state["ultimo_cadastro_pap"] = {
                    "nome": nome_completo,
                    "celular": normalize_phone(celular_principal),
                    "cpf": cpf_valido
                }

                # Limpa apenas o formulário (não apaga o último cadastro!)
                keys_to_clear = [
                    "dados_temp_pap",
                    "ignorar_bloqueio_pap",
                    "endereco_bloqueado_confirmado_pap",
                    "gerando_contrato_pap",
                    "contrato_pronto_pap",
                    "gerando_comodato_pap",
                    "comodato_pronto_pap"
                ]
                for k in keys_to_clear:
                    st.session_state.pop(k, None)
                st.session_state["form_key_pap"] += 1
                st.rerun()
            except Exception as e:
                st.error(f"❌ Erro ao salvar: {e}")

    # Lógica de geração assíncrona
    if st.session_state.get("gerando_contrato_pap") and "dados_contrato_pap" in st.session_state:
        with st.spinner("📝 Gerando contrato..."):
            pdf_bytes = gerar_pdf_contrato(st.session_state["dados_contrato_pap"])
            if pdf_bytes:
                st.session_state["contrato_bytes_pap"] = pdf_bytes
                st.session_state["contrato_pronto_pap"] = True
                del st.session_state["gerando_contrato_pap"]
                del st.session_state["dados_contrato_pap"]
                st.rerun()

    if st.session_state.get("gerando_comodato_pap") and "dados_comodato_pap" in st.session_state:
        with st.spinner("📄 Gerando termo de comodato..."):
            pdf_bytes = gerar_pdf_comodato(st.session_state["dados_comodato_pap"])
            if pdf_bytes:
                st.session_state["comodato_bytes_pap"] = pdf_bytes
                st.session_state["comodato_pronto_pap"] = True
                del st.session_state["gerando_comodato_pap"]
                del st.session_state["dados_comodato_pap"]
                st.rerun()
