# modules/revenda.py
import streamlit as st
from datetime import datetime
import re
import base64
from .utils import normalize_phone, limpar_cpf as limpar_cpf_util
from .pdf_generator import gerar_pdf_contrato, gerar_pdf_comodato, MODELOS_ROTEADORES, PLANOS
from urllib.parse import quote

WHATSAPP_LOJA = "5524992035540"

def gerar_codigo_indicacao_revenda():
    """Gera código no formato: REV + 6 números + 3 letras maiúsculas."""
    import random, string
    numeros = ''.join(random.choices(string.digits, k=6))
    letras = ''.join(random.choices(string.ascii_uppercase, k=3))
    return f"REV{numeros}{letras}"

def montar_endereco_completo(endereco, numero, complemento=""):
    partes = [p.strip() for p in [endereco, numero] if p]
    res = " - ".join(partes)
    if complemento.strip():
        res += f" ({complemento.strip()})"
    return res

def safe_strip_codigo_indicador(texto):
    return texto.strip() if isinstance(texto, str) and texto.strip() else None

def gerar_link_whatsapp_solicitacao(nome, celular, cpf=None):
    """Gera link WhatsApp para análise de cadastro."""
    cpf_texto = f"\nCPF: {cpf}" if cpf else ""
    mensagem = f"Temos um cadastro novo (Revenda):\nNome: {nome}\nTelefone: {celular}{cpf_texto}"
    mensagem_codificada = quote(mensagem)
    return f"https://wa.me/{WHATSAPP_LOJA}?text={mensagem_codificada}"

def determinar_status_revenda(cliente):
    """Determina status visual da indicação para revenda (igual embaixador)."""
    status_agendamento = cliente.get("status_agendamento")
    
    if status_agendamento == "ativado":
        return "Ativado"
    elif status_agendamento == "cancelado":
        return "Cancelado"
    elif status_agendamento == "agendado":
        return "Agendado"
    elif cliente.get("reagendado_para") and status_agendamento not in ["ativado", "cancelado"]:
        return "Reagendado"
    elif cliente.get("em_tratamento") is True:
        return "Em tratamento"
    elif cliente.get("seguiu_ativacao") == "Sim":
        return "Seguiu para ativação"
    else:
        return "Indicado"

def render_revenda(usuarios_collection, clientes_collection):
    # Busca dados da revenda logada
    codigo_revenda = st.session_state.get("codigo_revenda")
    nome_revenda = st.session_state.get("nome_usuario", "Revenda")
    nome_loja = "—"

    if codigo_revenda:
        rev_data = usuarios_collection.find_one(
            {"codigo_revenda": codigo_revenda, "perfil": "revenda"}
        )
        if rev_data:
            nome_revenda = rev_data.get("nome_exibicao", nome_revenda)
            nome_loja = rev_data.get("nome_loja", "—")

    # Boas-vindas
    st.markdown(
        f"""
        <div style="
            background-color: #f0fff4;
            border-left: 4px solid #48bb78;
            padding: 12px 16px;
            border-radius: 0 6px 6px 0;
            margin-bottom: 20px;
        ">
            <h3 style="margin: 0; color: #2c3e50;">👋 Bem-vindo, <strong>Revenda {nome_revenda}</strong>{f' da Loja <em>"{nome_loja}"</em>' if nome_loja != '—' else ''}!</h3>
        </div>
        """,
        unsafe_allow_html=True
    )

    st.caption(f"Código da sua revenda: **{codigo_revenda or 'REV??????'}**")

    # Abas: Cadastro | Minhas Indicações
    tab_cadastro, tab_indicacoes = st.tabs(["➕ Novo Cadastro", "📋 Minhas Indicações"])

    # ==================== ABA 1: CADASTRO COMPLETO ====================
    with tab_cadastro:
        st.subheader("📝 Cadastro Completo de Cliente")
        st.info("⚠️ Você pode realizar cadastros completos. Após salvar, acompanhe o status na aba 'Minhas Indicações'.")

        # Inicialização de estados (igual pap.py)
        if "form_key_rev" not in st.session_state:
            st.session_state["form_key_rev"] = 0
        if "gerando_contrato_rev" not in st.session_state:
            st.session_state["gerando_contrato_rev"] = False
        if "contrato_pronto_rev" not in st.session_state:
            st.session_state["contrato_pronto_rev"] = False
        if "gerando_comodato_rev" not in st.session_state:
            st.session_state["gerando_comodato_rev"] = False
        if "comodato_pronto_rev" not in st.session_state:
            st.session_state["comodato_pronto_rev"] = False

        # Botão WhatsApp se houver cadastro recente
        if "ultimo_cadastro_rev" in st.session_state:
            dados = st.session_state["ultimo_cadastro_rev"]
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

            if st.button("➕ Novo Cadastro", type="secondary", key="novo_cadastro_rev"):
                keys_to_clear = [
                    "ultimo_cadastro_rev", "dados_temp_rev", "gerando_contrato_rev",
                    "contrato_pronto_rev", "gerando_comodato_rev", "comodato_pronto_rev"
                ]
                for k in keys_to_clear:
                    st.session_state.pop(k, None)
                st.session_state["form_key_rev"] += 1
                st.rerun()
            return

        # Formulário de cadastro completo (igual pap.py)
        def get_valor_inicial(chave, default=""):
            return st.session_state.get("dados_temp_rev", {}).get(chave, default)

        nome_completo = st.text_input(
            "Nome completo *",
            value=get_valor_inicial("nome_completo", ""),
            key=f"nome_rev_{st.session_state['form_key_rev']}"
        )

        col_tel1, col_tel2, col_tel3 = st.columns(3)
        with col_tel1:
            celular_principal = st.text_input(
                "Celular Principal *",
                max_chars=15,
                placeholder="(00) 90000-0000",
                value=get_valor_inicial("celular_principal", ""),
                key=f"cel_rev_{st.session_state['form_key_rev']}"
            )
        with col_tel2:
            celular_contato_1 = st.text_input(
                "Contato 1",
                max_chars=15,
                placeholder="(00) 90000-0000",
                value=get_valor_inicial("celular_contato_1", ""),
                key=f"cont1_rev_{st.session_state['form_key_rev']}"
            )
            descricao_contato_1 = st.text_input(
                "Quem é esse contato?",
                max_chars=30,
                placeholder="Ex: Esposa",
                value=get_valor_inicial("descricao_contato_1", ""),
                key=f"desc1_rev_{st.session_state['form_key_rev']}"
            )
        with col_tel3:
            celular_contato_2 = st.text_input(
                "Contato 2",
                max_chars=15,
                placeholder="(00) 90000-0000",
                value=get_valor_inicial("celular_contato_2", ""),
                key=f"cont2_rev_{st.session_state['form_key_rev']}"
            )
            descricao_contato_2 = st.text_input(
                "Quem é esse contato?",
                max_chars=30,
                placeholder="Ex: Mãe",
                value=get_valor_inicial("descricao_contato_2", ""),
                key=f"desc2_rev_{st.session_state['form_key_rev']}"
            )

        cpf_raw = st.text_input(
            "CPF *",
            max_chars=14,
            placeholder="000.000.000-00",
            value=get_valor_inicial("cpf", ""),
            key=f"cpf_rev_{st.session_state['form_key_rev']}"
        )
        cpf_limpo = re.sub(r'\D', '', cpf_raw)
        if len(cpf_limpo) == 11:
            dup = clientes_collection.find_one({"cpf": cpf_limpo})
            if dup:
                st.warning(f"⚠️ CPF já cadastrado: **{dup.get('nome_completo', '—')}**")

        with st.container(border=True):
            st.markdown("### 📌 Informações de Origem")
            origem_opcoes = ["Selecione...", "Radio Show FM", "Opa Suite", "Whatsapp", "Instagram", "Indicação", "Loja", "Panfleto", "PaP", "Ex Cliente", "Prospecção Ativa (Zap, Email, Telegram)", "Facebook", "Site", "Revenda"]
            origem = st.selectbox(
                "De onde veio?",
                origem_opcoes,
                index=origem_opcoes.index("Revenda"),
                key=f"origem_rev_{st.session_state['form_key_rev']}"
            )

            restritivo = st.selectbox(
                "Restritivo?",
                ["Selecione...", "Sim", "Não"],
                index=["Selecione...", "Sim", "Não"].index(get_valor_inicial("restritivo", "Selecione...")),
                key=f"restr_rev_{st.session_state['form_key_rev']}"
            )

            if restritivo == "Sim":
                st.markdown("### ⚠️ Informações sobre Restrição")
                col1, col2, col3 = st.columns(3)
                with col1:
                    qtd_registros = st.selectbox("Quantos registros?", list(range(1, 31)), index=0, key=f"qtd_rev_{st.session_state['form_key_rev']}")
                with col2:
                    ano_atual = datetime.now().year
                    ano_recente = st.selectbox("Qual ano mais recente?", list(range(2020, ano_atual + 1)), index=ano_atual - 2020, key=f"ano_rev_{st.session_state['form_key_rev']}")
                with col3:
                    servico_internet = st.selectbox("Serviço de internet?", ["Sim", "Não"], index=0, key=f"serv_rev_{st.session_state['form_key_rev']}")
            else:
                qtd_registros = ano_recente = servico_internet = None

            seguiu_ativacao = st.selectbox(
                "Seguiu para Ativação?",
                ["Selecione...", "Sim", "Não"],
                index=["Selecione...", "Sim", "Não"].index(get_valor_inicial("seguiu_ativacao", "Selecione...")),
                key=f"ativ_rev_{st.session_state['form_key_rev']}"
            )

            OPCOES_INTERNET = ["Selecione...", "Giga+", "Internet10", "TR Telecom", "Claro", "Não possui"]
            ja_possui_internet = st.selectbox(
                "Já Possui Internet?",
                OPCOES_INTERNET,
                index=OPCOES_INTERNET.index(get_valor_inicial("ja_possui_internet", "Selecione...")) if get_valor_inicial("ja_possui_internet") in OPCOES_INTERNET else 0,
                key=f"int_rev_{st.session_state['form_key_rev']}"
            )

            observacoes = st.text_area(
                "Observações Gerais",
                placeholder="Ex: Cliente interessado em plano familiar.",
                value=get_valor_inicial("observacoes", ""),
                key=f"obs_rev_{st.session_state['form_key_rev']}"
            )

        col1, col2 = st.columns(2)
        with col1:
            rg = st.text_input("RG *", max_chars=15, placeholder="12.345.678-9", value=get_valor_inicial("rg", ""), key=f"rg_rev_{st.session_state['form_key_rev']}")
        with col2:
            data_nascimento = st.date_input("Data de nascimento *", format="DD/MM/YYYY", min_value=datetime(1900,1,1), key=f"nasc_rev_{st.session_state['form_key_rev']}")

        email = st.text_input("Email *", value=get_valor_inicial("email", ""), key=f"email_rev_{st.session_state['form_key_rev']}")

        col1, col2 = st.columns([3, 1])
        with col1:
            endereco = st.text_input("Endereço *", value=get_valor_inicial("endereco", ""), key=f"end_rev_{st.session_state['form_key_rev']}")
        with col2:
            numero = st.text_input("Número *", max_chars=6, value=get_valor_inicial("numero", ""), key=f"num_rev_{st.session_state['form_key_rev']}")

        col1, col2 = st.columns(2)
        with col1:
            complemento = st.text_input("Complemento", value=get_valor_inicial("complemento", ""), key=f"comp_rev_{st.session_state['form_key_rev']}")
        with col2:
            cidade = st.text_input("Cidade *", value=get_valor_inicial("cidade", "Paraiba do Sul"), key=f"cid_rev_{st.session_state['form_key_rev']}")

        col1, col2 = st.columns(2)
        with col1:
            bairro = st.text_input("Bairro *", value=get_valor_inicial("bairro", ""), key=f"bairro_rev_{st.session_state['form_key_rev']}")
        with col2:
            ponto_referencia = st.text_input("Ponto de referência", value=get_valor_inicial("ponto_ref", ""), key=f"ref_rev_{st.session_state['form_key_rev']}")

        plano_atual = get_valor_inicial("plano_escolhido", "")
        index_plano = (PLANOS.index(plano_atual) + 1) if plano_atual in PLANOS else 0
        plano_escolhido = st.selectbox(
            "Plano escolhido *",
            ["Selecione..."] + PLANOS,
            index=index_plano,
            key=f"plano_rev_{st.session_state['form_key_rev']}"
        )

        profissao = st.text_input("Profissão *", value=get_valor_inicial("profissao", ""), key=f"prof_rev_{st.session_state['form_key_rev']}")
        data_vencimento = st.selectbox("Melhor data de vencimento *", list(range(1, 32)), index=0, key=f"venc_rev_{st.session_state['form_key_rev']}")

        st.subheader("📸 Foto segurando documento (opcional)")
        foto_documento = st.file_uploader("Envie a foto (JPG ou PNG)", type=["jpg", "png", "jpeg"], key=f"foto_rev_{st.session_state['form_key_rev']}")

        # SEÇÃO DE EQUIPAMENTO E BOTÕES DE CONTRATO/COMODATO REMOVIDA PARA REVENDA
        # A revenda não deve ter acesso à geração de contratos
        
        # Salvar cadastro
        if st.button("💾 Salvar Cadastro Completo", type="primary"):
            if not nome_completo or not celular_principal or plano_escolhido == "Selecione...":
                st.error("⚠️ Nome, celular e plano são obrigatórios.")
            else:
                cpf_valido = limpar_cpf_util(cpf_raw)
                foto_base64 = ""
                if foto_documento:
                    foto_bytes = foto_documento.read()
                    foto_base64 = base64.b64encode(foto_bytes).decode('utf-8')

                codigo_indicacao = None
                if seguiu_ativacao == "Sim":
                    codigo_indicacao = gerar_codigo_indicacao_revenda()

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
                    "cadastrado_por": st.session_state.get("nome_usuario", "Revenda"),
                    "origem": "Revenda",
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
                    "indicado_por": {
                        "tipo": "revenda",
                        "codigo": codigo_revenda,
                        "nome_revenda": nome_revenda
                    },
                    "endereco_bloqueado": False,
                    "observacoes_bloqueio_endereco": None,
                    "bonus_enviado": False,
                    "bonus_confirmado": False
                }

                try:
                    clientes_collection.insert_one(cliente_data)
                    st.success("✅ Cadastro salvo com sucesso!")
                    st.balloons()

                    st.session_state["ultimo_cadastro_rev"] = {
                        "nome": nome_completo,
                        "celular": normalize_phone(celular_principal),
                        "cpf": cpf_valido
                    }

                    keys_to_clear = ["dados_temp_rev", "gerando_contrato_rev", "contrato_pronto_rev",
                                   "gerando_comodato_rev", "comodato_pronto_rev"]
                    for k in keys_to_clear:
                        st.session_state.pop(k, None)
                    st.session_state["form_key_rev"] += 1
                    st.rerun()
                except Exception as e:
                    st.error(f"❌ Erro ao salvar: {e}")

        # Lógica de geração assíncrona REMOVIDA (não necessária sem os botões)
        # if st.session_state.get("gerando_contrato_rev") and "dados_contrato_rev" in st.session_state:
        #     ...
        # if st.session_state.get("gerando_comodato_rev") and "dados_comodato_rev" in st.session_state:
        #     ...

    # ==================== ABA 2: MINHAS INDICAÇÕES ====================
    with tab_indicacoes:
        st.subheader("📋 Minhas Indicações")
        st.info("Acompanhe o status de todos os clientes que você indicou.")

        minhas_indicacoes = list(
            clientes_collection.find(
                {"indicado_por.codigo": codigo_revenda}
            ).sort("data_cadastro", -1)
        )

        if not minhas_indicacoes:
            st.info("Nenhuma indicação registrada ainda.")
        else:
            # Dashboard resumido
            total = len(minhas_indicacoes)
            ativados = sum(1 for c in minhas_indicacoes if c.get("status_agendamento") == "ativado")
            pendentes = total - ativados
            
            col1, col2, col3 = st.columns(3)
            col1.metric("Total Indicações", total)
            col2.metric("Ativados", ativados, f"{ativados/total*100:.0f}%" if total > 0 else "0%")
            col3.metric("Pendentes", pendentes)

            st.divider()

            for cli in minhas_indicacoes:
                nome = cli["nome_completo"]
                tel = cli["celular"]
                data = cli.get("data_cadastro", "")
                if isinstance(data, datetime):
                    data_str = data.strftime("%d/%m/%Y %H:%M")
                elif isinstance(data, str):
                    data_str = data[:16]
                else:
                    data_str = "—"
                
                status = determinar_status_revenda(cli)
                
                # Cores por status
                cor_status = {
                    "Ativado": "🟢",
                    "Cancelado": "🔴",
                    "Agendado": "🔵",
                    "Reagendado": "🟡",
                    "Em tratamento": "🟠",
                    "Seguiu para ativação": "⚪",
                    "Indicado": "⚫"
                }.get(status, "⚫")

                with st.expander(f"{cor_status} {nome} — {tel} ({status})", expanded=False):
                    col1, col2 = st.columns([3, 1])
                    
                    with col1:
                        st.write(f"**Telefone:** {tel}")
                        st.write(f"**Data da indicação:** {data_str}")
                        st.write(f"**Plano:** {cli.get('plano_escolhido', 'N/A')}")
                        st.write(f"**Status atual:** `{status}`")
                        
                        if cli.get("retorno_agendado") and cli.get("retorno_agendado") != " ":
                            st.write(f"**Agendado para:** {cli['retorno_agendado']}")
                        
                        if cli.get("reagendado_para"):
                            st.write(f"**Reagendado para:** {cli['reagendado_para']}")
                    
                    with col2:
                        # Notificação de ativação
                        if status == "Ativado" and not cli.get("notificacao_revenda_lida", False):
                            st.markdown("🎉 **ATIVADO!**")
                            if st.button("✅ Entendi", key=f"lido_rev_{cli['_id']}"):
                                clientes_collection.update_one(
                                    {"_id": cli["_id"]},
                                    {"$set": {"notificacao_revenda_lida": True}}
                                )
                                st.rerun()
                        
                        # Confirmação de bônus
                        elif cli.get("bonus_enviado") and not cli.get("bonus_confirmado"):
                            st.markdown("💰 **Bônus Enviado!**")
                            if st.button("✅ Confirmar Recebimento", key=f"conf_rev_{cli['_id']}"):
                                clientes_collection.update_one(
                                    {"_id": cli["_id"]},
                                    {"$set": {
                                        "bonus_confirmado": True,
                                        "data_bonus_confirmado": datetime.now()
                                    }}
                                )
                                st.success("🎉 Bônus confirmado!")
                                st.rerun()
                        
                        elif cli.get("bonus_confirmado"):
                            st.success("✅ Bônus Confirmado")
