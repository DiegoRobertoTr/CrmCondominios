# modules/revenda.py
import streamlit as st
from datetime import datetime
import re
import base64
from .utils import normalize_phone, limpar_cpf as limpar_cpf_util
# Se a revenda for gerar contratos, descomente as linhas abaixo:
# from .pdf_generator import gerar_pdf_contrato, gerar_pdf_comodato, MODELOS_ROTEADORES, PLANOS
from urllib.parse import quote

#  CONDOMÍNIO - Importação
try:
    from .condominios import get_condominio_options, get_condominio_by_id
except ImportError:
    def get_condominio_options():
        return {}
    def get_condominio_by_id(cond_id):
        return None

WHATSAPP_LOJA = "5524992035540"

def gerar_codigo_indicacao_revenda():
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
    """Determina status visual da indicação para revenda."""
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

def atualizar_endereco_por_condominio_rev(condominio_nome, condominio_options):
    """Atualiza o session_state com dados do condomínio selecionado (para Revenda)."""
    cond_id = condominio_options.get(condominio_nome)
    if cond_id:
        cond_data = get_condominio_by_id(cond_id)
        if cond_data:
            st.session_state["endereco_rev"] = cond_data.get("endereco", "")
            st.session_state["numero_rev"] = cond_data.get("numero", "")
            st.session_state["cidade_rev"] = cond_data.get("cidade", "")
            st.session_state["condominio_id_rev"] = cond_id
            st.session_state["condominio_nome_rev"] = condominio_nome
            st.rerun()

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
        <div style="background-color: #f0fff4; border-left: 4px solid #48bb78; padding: 12px 16px; border-radius: 0 6px 6px 0; margin-bottom: 20px;">
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
        st.subheader(" Cadastro Completo de Cliente")
        st.info("️ Você pode realizar cadastros completos. Após salvar, acompanhe o status na aba 'Minhas Indicações'.")

        # Inicialização de estados
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
        
        # Exibe botão WhatsApp e resumo se houver cadastro recente
        if "ultimo_cadastro_rev" in st.session_state:
            dados = st.session_state["ultimo_cadastro_rev"]
            st.success(f"✅ Cadastro realizado com sucesso para: **{dados['nome']}**")
            
            # Exibir informações do condomínio
            if dados.get("condominio_nome"):
                st.info(f"🏢 **Condomínio:** {dados['condominio_nome']}")
                if dados.get("bloco") or dados.get("apartamento"):
                    unidade_parts = []
                    if dados.get("bloco"): unidade_parts.append(f"Bloco {dados['bloco']}")
                    if dados.get("apartamento"): unidade_parts.append(f"Apto {dados['apartamento']}")
                    if unidade_parts:
                        st.info(f"📍 **Unidade:** {' / '.join(unidade_parts)}")

            link_whatsapp = gerar_link_whatsapp_solicitacao(dados["nome"], dados["celular"], dados.get("cpf"))
            st.markdown(
                f'<a href="{link_whatsapp}" target="_blank" style="display: inline-block; padding: 0.5em 1em; background-color: #25D366; color: white; text-decoration: none; border-radius: 5px; font-weight: bold; margin-bottom: 1em;">📲 Solicitar Análise</a>',
                unsafe_allow_html=True
            )

            if st.button("➕ Novo Cadastro", type="secondary", key="novo_cadastro_rev"):
                keys_to_clear = [
                    "ultimo_cadastro_rev", "dados_temp_rev", 
                    "gerando_contrato_rev", "contrato_pronto_rev",
                    "gerando_comodato_rev", "comodato_pronto_rev",
                    "condominio_id_rev", "condominio_nome_rev",
                    "endereco_rev", "numero_rev", "cidade_rev"
                ]
                for k in keys_to_clear:
                    st.session_state.pop(k, None)
                st.session_state["form_key_rev"] += 1
                st.rerun()
            return # Para o fluxo aqui se já salvou

        def get_valor_inicial(chave, default=""):
            return st.session_state.get("dados_temp_rev", {}).get(chave, default)

        nome_completo = st.text_input("Nome completo *", value=get_valor_inicial("nome_completo", ""), key=f"nome_rev_{st.session_state['form_key_rev']}")

        col_tel1, col_tel2, col_tel3 = st.columns(3)
        with col_tel1:
            celular_principal = st.text_input("Celular Principal *", max_chars=15, placeholder="(00) 90000-0000", value=get_valor_inicial("celular_principal", ""), key=f"cel_rev_{st.session_state['form_key_rev']}")
        with col_tel2:
            celular_contato_1 = st.text_input("Contato 1", max_chars=15, placeholder="(00) 90000-0000", value=get_valor_inicial("celular_contato_1", ""), key=f"cont1_rev_{st.session_state['form_key_rev']}")
            descricao_contato_1 = st.text_input("Quem é esse contato?", max_chars=30, placeholder="Ex: Esposa", value=get_valor_inicial("descricao_contato_1", ""), key=f"desc1_rev_{st.session_state['form_key_rev']}")
        with col_tel3:
            celular_contato_2 = st.text_input("Contato 2", max_chars=15, placeholder="(00) 90000-0000", value=get_valor_inicial("celular_contato_2", ""), key=f"cont2_rev_{st.session_state['form_key_rev']}")
            descricao_contato_2 = st.text_input("Quem é esse contato?", max_chars=30, placeholder="Ex: Mãe", value=get_valor_inicial("descricao_contato_2", ""), key=f"desc2_rev_{st.session_state['form_key_rev']}")

        cpf_raw = st.text_input("CPF *", max_chars=14, placeholder="000.000.000-00", value=get_valor_inicial("cpf", ""), key=f"cpf_rev_{st.session_state['form_key_rev']}")

        with st.container(border=True):
            st.markdown("### 📌 Informações de Origem")
            origem_opcoes = ["Selecione...", "Radio Show FM", "Opa Suite", "Whatsapp", "Instagram", "Indicação", "Loja", "Panfleto", "PaP", "Ex Cliente", "Prospecção Ativa (Zap, Email, Telegram)", "Facebook", "Site", "Revenda"]
            origem = st.selectbox("De onde veio?", origem_opcoes, index=origem_opcoes.index("Revenda"), key=f"origem_rev_{st.session_state['form_key_rev']}")

            restritivo = st.selectbox("Restritivo?", ["Selecione...", "Sim", "Não"], index=["Selecione...", "Sim", "Não"].index(get_valor_inicial("restritivo", "Selecione...")), key=f"rest_rev_{st.session_state['form_key_rev']}")
            
            qtd_registros = ano_recente = servico_internet = None
            if restritivo == "Sim":
                col1, col2, col3 = st.columns(3)
                with col1: qtd_registros = st.selectbox("Qtd registros?", list(range(1, 31)), index=0, key=f"qtd_rev_{st.session_state['form_key_rev']}")
                with col2: ano_recente = st.selectbox("Ano mais recente?", list(range(2020, datetime.now().year + 1)), index=datetime.now().year - 2020, key=f"ano_rev_{st.session_state['form_key_rev']}")
                with col3: servico_internet = st.selectbox("Serviço de internet?", ["Sim", "Não"], index=0, key=f"serv_rev_{st.session_state['form_key_rev']}")

            seguiu_ativacao = st.selectbox("Seguiu para Ativação?", ["Selecione...", "Sim", "Não"], index=["Selecione...", "Sim", "Não"].index(get_valor_inicial("seguiu_ativacao", "Selecione...")), key=f"ativacao_rev_{st.session_state['form_key_rev']}")
            
            OPCOES_INTERNET = ["Selecione...", "Giga+", "Internet10", "TR Telecom", "Claro", "Não possui"]
            ja_possui_internet = st.selectbox("Já Possui Internet?", OPCOES_INTERNET, index=OPCOES_INTERNET.index(get_valor_inicial("ja_possui_internet", "Selecione...")) if get_valor_inicial("ja_possui_internet") in OPCOES_INTERNET else 0, key=f"int_rev_{st.session_state['form_key_rev']}")

            observacoes = st.text_area("Observações Gerais", placeholder="Ex: Cliente interessado em plano familiar.", value=get_valor_inicial("observacoes", ""), key=f"obs_rev_{st.session_state['form_key_rev']}")

        col1, col2 = st.columns(2)
        with col1: rg = st.text_input("RG *", max_chars=15, placeholder="12.345.678-9", value=get_valor_inicial("rg", ""), key=f"rg_rev_{st.session_state['form_key_rev']}")
        with col2: data_nascimento = st.date_input("Data de nascimento *", format="DD/MM/YYYY", min_value=datetime(1900,1,1), key=f"nasc_rev_{st.session_state['form_key_rev']}")

        email = st.text_input("Email *", value=get_valor_inicial("email", ""), key=f"email_rev_{st.session_state['form_key_rev']}")

        #  CONDOMÍNIO - Seção de Localização com Condomínio
        st.markdown("###  Localização")
        condominio_options = {"Nenhum / Não se aplica": None}
        condominio_options.update(get_condominio_options())
        
        cond_nome_salvo = st.session_state.get("condominio_nome_rev", "")
        index_cond = 0
        if cond_nome_salvo and cond_nome_salvo in condominio_options:
            index_cond = list(condominio_options.keys()).index(cond_nome_salvo)

        condominio_select = st.selectbox(
            "Condomínio (Opcional)",
            options=list(condominio_options.keys()),
            index=index_cond,
            key=f"cond_rev_{st.session_state['form_key_rev']}"
        )

        if condominio_select and condominio_select != "Nenhum / Não se aplica":
            if condominio_select != cond_nome_salvo:
                atualizar_endereco_por_condominio_rev(condominio_select, condominio_options)
            else:
                if "condominio_id_rev" not in st.session_state:
                    pass

        col1, col2 = st.columns([3, 1])
        with col1:
            endereco = st.text_input("Endereço *", value=st.session_state.get("endereco_rev", get_valor_inicial("endereco", "")), key=f"end_rev_{st.session_state['form_key_rev']}")
        with col2:
            numero = st.text_input("Número *", max_chars=6, value=st.session_state.get("numero_rev", get_valor_inicial("numero", "")), key=f"num_rev_{st.session_state['form_key_rev']}")

        col1, col2 = st.columns(2)
        with col1: complemento = st.text_input("Complemento", value=get_valor_inicial("complemento", ""), key=f"comp_rev_{st.session_state['form_key_rev']}")
        with col2: cidade = st.text_input("Cidade *", value=st.session_state.get("cidade_rev", get_valor_inicial("cidade", "Paraiba do Sul")), key=f"cid_rev_{st.session_state['form_key_rev']}")

        col1, col2 = st.columns(2)
        with col1: bairro = st.text_input("Bairro *", value=get_valor_inicial("bairro", ""), key=f"bairro_rev_{st.session_state['form_key_rev']}")
        with col2: ponto_referencia = st.text_input("Ponto de referência", value=get_valor_inicial("ponto_ref", ""), key=f"ref_rev_{st.session_state['form_key_rev']}")

        # 🏢 CONDOMÍNIO - Campos Bloco e Apartamento (SEMPRE VISÍVEIS)
        col_bloco, col_apto = st.columns(2)
        with col_bloco:
            bloco = st.text_input("Bloco", value="", key=f"bloco_rev_{st.session_state['form_key_rev']}")
        with col_apto:
            apartamento = st.text_input("Apartamento", value="", key=f"apartamento_rev_{st.session_state['form_key_rev']}")

        plano_atual = get_valor_inicial("plano_escolhido", "")
        # Assumindo que PLANOS foi importado ou definido. Se não, use uma lista fixa.
        try:
            from .pdf_generator import PLANOS
            index_plano = (PLANOS.index(plano_atual) + 1) if plano_atual in PLANOS else 0
            plano_escolhido = st.selectbox("Plano escolhido *", ["Selecione..."] + PLANOS, index=index_plano, key=f"plano_rev_{st.session_state['form_key_rev']}")
        except ImportError:
            plano_escolhido = st.selectbox("Plano escolhido *", ["Selecione...", "100 MEGA", "300 MEGA", "500 MEGA", "1 GIGA"], key=f"plano_rev_{st.session_state['form_key_rev']}")

        profissao = st.text_input("Profissão *", value=get_valor_inicial("profissao", ""), key=f"prof_rev_{st.session_state['form_key_rev']}")
        data_vencimento = st.selectbox("Melhor data de vencimento *", list(range(1, 32)), index=0, key=f"venc_rev_{st.session_state['form_key_rev']}")

        st.subheader("📸 Foto segurando documento (opcional)")
        foto_documento = st.file_uploader("Envie a foto (JPG ou PNG)", type=["jpg", "png", "jpeg"], key=f"foto_rev_{st.session_state['form_key_rev']}")

        # SEÇÃO DE EQUIPAMENTO E BOTÕES DE CONTRATO/COMODATO REMOVIDA PARA REVENDA (conforme seu código original)
        # A revenda geralmente só cadastra, a equipe interna gera o contrato.
        
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
                    "restritivo": restritivo if restritivo != "Selecione..." else "",
                    "restritivo_qtd_registros": qtd_registros if restritivo == "Sim" else None,
                    "restritivo_ano_recente": ano_recente if restritivo == "Sim" else None,
                    "restritivo_servico_internet": servico_internet if restritivo == "Sim" else None,
                    "seguiu_ativacao": seguiu_ativacao if seguiu_ativacao != "Selecione..." else "",
                    "ja_possui_internet": ja_possui_internet if ja_possui_internet != "Selecione..." else "",
                    "retorno_agendado": "",
                    "observacoes": observacoes if observacoes else "",
                    "observacoes_followup": "",
                    "codigo_indicacao": codigo_indicacao,
                    "codigo_indicador": safe_strip_codigo_indicador(codigo_indicador),
                    "indicado_por": {
                        "tipo": "revenda",
                        "codigo": codigo_revenda,
                        "nome_revenda": nome_revenda
                    },
                    "endereco_bloqueado": False,
                    "observacoes_bloqueio_endereco": None,
                    "bonus_enviado": False,
                    "bonus_confirmado": False,
                    # 🏢 CONDOMÍNIO - Novos campos
                    "condominio_id": st.session_state.get("condominio_id_rev"),
                    "condominio_nome": st.session_state.get("condominio_nome_rev"),
                    "bloco": bloco if bloco else None,
                    "apartamento": apartamento if apartamento else None,
                }

                try:
                    clientes_collection.insert_one(cliente_data)
                    st.success("✅ Cadastro salvo com sucesso!")
                    st.balloons()
                    
                    # Armazena dados para exibir WhatsApp após rerun
                    st.session_state["ultimo_cadastro_rev"] = {
                        "nome": nome_completo,
                        "celular": normalize_phone(celular_principal),
                        "cpf": cpf_valido,
                        "condominio_nome": st.session_state.get("condominio_nome_rev"),
                        "bloco": bloco if bloco else None,
                        "apartamento": apartamento if apartamento else None,
                    }
                    
                    # Limpa form
                    keys_to_clear = ["dados_temp_rev", "gerando_contrato_rev", "contrato_pronto_rev", "gerando_comodato_rev", "comodato_pronto_rev"]
                    for k in keys_to_clear:
                        st.session_state.pop(k, None)
                    st.session_state["form_key_rev"] += 1
                    st.rerun()
                except Exception as e:
                    st.error(f"❌ Erro ao salvar: {e}")

    # ==================== ABA 2: MINHAS INDICAÇÕES ====================
    with tab_indicacoes:
        st.subheader("📋 Minhas Indicações")
        st.info("Acompanhe o status de todos os clientes que você indicou.")
        
        minhas_indicacoes = list(
            clientes_collection.find(
                {"indicado_por.codigo": codigo_revenda}
            ).sort("data_cadastro", -1)
        )

        if minhas_indicacoes:
            total = len(minhas_indicacoes)
            ativados = sum(1 for c in minhas_indicacoes if c.get("status_agendamento") == "ativado")
            em_andamento = sum(1 for c in minhas_indicacoes if c.get("status_agendamento") in ["agendado", "em_tratamento"])
            indicados = sum(1 for c in minhas_indicacoes if determinar_status_revenda(c) == "Indicado")

            col_res1, col_res2, col_res3, col_res4 = st.columns(4)
            with col_res1: st.metric("Total", total)
            with col_res2: st.metric("✅ Ativados", ativados)
            with col_res3: st.metric("🔄 Em Andamento", em_andamento)
            with col_res4: st.metric("⏳ Aguardando", indicados)
            
            st.divider()

            for cli in minhas_indicacoes:
                nome = cli["nome_completo"]
                tel = cli["celular"]
                data = cli.get("data_cadastro", "").strftime("%d/%m/%Y %H:%M") if isinstance(cli.get("data_cadastro"), datetime) else str(cli.get("data_cadastro", ""))[:16]
                status = determinar_status_revenda(cli)
                
                cor_status = "🟢" if status == "Ativado" else "" if status == "Agendado" else "⏳"
                
                # 🏢 Informações de Condomínio
                condominio_nome = cli.get("condominio_nome")
                bloco = cli.get("bloco")
                apartamento = cli.get("apartamento")
                
                condominio_info = ""
                if condominio_nome:
                    condominio_info = f"🏢 **{condominio_nome}**"
                    if bloco or apartamento:
                        partes = []
                        if bloco: partes.append(f"Blq {bloco}")
                        if apartamento: partes.append(f"Apto {apartamento}")
                        condominio_info += f" ({' / '.join(partes)})"

                with st.expander(f"{cor_status} {nome} — {tel} ({status}){f' | {condominio_info}' if condominio_info else ''}", expanded=False):
                    col1, col2 = st.columns([3, 1])
                    with col1:
                        if status == "Ativado" and not cli.get("notificacao_revenda_lida", False):
                            st.markdown("🎉 **ATIVADO!**")
                        
                        st.write(f"**Status:** `{status}`")
                        
                        # Exibir info do condomínio no card
                        if condominio_info:
                            st.info(condominio_info)
                        
                        if cli.get("endereco"):
                            end_full = f"{cli['endereco']}, {cli.get('numero', '')}"
                            if cli.get('complemento'): end_full += f" ({cli['complemento']})"
                            st.caption(f"📍 {end_full} - {cli.get('cidade', '')}")

                    with col2:
                        if status == "Ativado" and not cli.get("notificacao_revenda_lida", False):
                            if st.button("✅ Entendi", key=f"lido_rev_{cli['_id']}"):
                                clientes_collection.update_one({"_id": cli["_id"]}, {"$set": {"notificacao_revenda_lida": True}})
                                st.rerun()
                        
                        if status == "Ativado" and not cli.get("bonus_confirmado", False):
                            if st.button("💰 Confirmar Bônus", key=f"bonus_rev_{cli['_id']}"):
                                clientes_collection.update_one({"_id": cli["_id"]}, {"$set": {"bonus_confirmado": True, "data_bonus": datetime.now()}})
                                st.success("Bônus confirmado!")
                                st.rerun()
        else:
            st.info("Nenhuma indicação registrada ainda.")
