import streamlit as st
from datetime import datetime, timedelta
import base64
import re
import random
import string
import streamlit.components.v1 as components
from urllib.parse import quote
from .utils import normalize_phone, validar_cpf, get_followup_date
from .pdf_generator import gerar_pdf_contrato, gerar_pdf_comodato, MODELOS_ROTEADORES, PLANOS
from pymongo.errors import DuplicateKeyError
import copy

============================================================================
🏢 CONDOMÍNIO - Import Correto
============================================================================
try:
    from .condominios import get_condominio_options, get_condominio_by_id
except ImportError:
    def get_condominio_options():
        return {}
    def get_condominio_by_id(cond_id):
        return None

============================================================================
✅ OTIMIZAÇÃO 1: Cache de Condomínios com @st.cache_resource
============================================================================
@st.cache_resource(ttl=300)  # Cache válido por 5 minutos
def get_condominio_options_cached(collection):
    """
    Retorna opções de condomínio COM CACHE.
    Evita queries repetidas no banco de dados.
    """
    try:
        from .condominios import get_all_condominios
        condominios = get_all_condominios()
        return {f"{c['nome']} - {c['cidade']}": c["_id"] for c in condominios}
    except:
        return {"Nenhum / Não se aplica": None}

============================================================================
✅ OTIMIZAÇÃO 2: Criar Índices no MongoDB (Performance)
============================================================================
def criar_indices_performance(clientes_collection):
    """
    Cria índices no MongoDB para melhorar performance das queries.
    Executar apenas uma vez na inicialização do sistema.
    """
    try:
        clientes_collection.create_index([("celular", 1)], unique=False)
        clientes_collection.create_index([("cpf", 1)], unique=False)
        clientes_collection.create_index([("nome_completo", "text")])
        clientes_collection.create_index([("seguiu_ativacao", 1), ("retorno_agendado", 1)])
        clientes_collection.create_index([("endereco", 1), ("numero", 1), ("endereco_bloqueado", 1)])
        clientes_collection.create_index([("condominio_nome", 1)])
        clientes_collection.create_index([("data_cadastro", -1)])
        return True
    except Exception as e:
        st.warning(f"⚠️ Não foi possível criar índices: {e}")
        return False

============================================================================
✅ OTIMIZAÇÃO 3: Atualizar Endereço SEM st.rerun()
============================================================================
def atualizar_endereco_por_condominio(condominio_nome, suffix, condominio_options):
    """
    Atualiza o session_state com dados do condomínio selecionado.
    ✅ SEM st.rerun() - Streamlit detecta mudanças automaticamente.
    """
    cond_id = condominio_options.get(condominio_nome)
    if cond_id:
        cond_data = get_condominio_by_id(cond_id)
        if cond_data:
            st.session_state[f"endereco_{suffix}"] = cond_data.get("endereco", " ")
            st.session_state[f"numero_{suffix}"] = cond_data.get("numero", " ")
            st.session_state[f"bairro_{suffix}"] = cond_data.get("bairro", " ")
            st.session_state[f"cidade_{suffix}"] = cond_data.get("cidade", " ")
            st.session_state[f"condominio_id_{suffix}"] = cond_id
            st.session_state[f"condominio_nome_{suffix}"] = condominio_nome

============================================================================
CONFIGURAÇÕES GERAIS
============================================================================
WHATSAPP_LOJA = "5524992035540"
MOTIVOS_RECUSA_ATIVACAO = [
    "Selecione...",
    "Restritivos (SPC/Serasa)",
    "Suspeita de fraude cadastral",
    "Divergência de dados cadastrais",
    "Endereço com pendência / bloqueado",
    "Área sem viabilidade técnica",
    "Cliente desistiu durante o processo",
    "Falta de documentação",
    "Dados insuficientes para análise"
]

OPCOES_INTERNET = ["Selecione...", "Giga+", "Internet10", "TR Telecom", "Claro", "Não possui"]

# ✅ NOVO: Lista de produtos para interesse
PRODUTOS_INTERESSE = [
    "Conecta e Protege (Câmeras + Internet + Bônus)",
    "Câmeras de Segurança",
    "Recarga de Carros Elétricos",
    "Conectividade (Internet)",
    "Automação Residencial",
    "Automação Predial"
]

def copiar_para_area_de_transferencia(texto, botao_key):
    """Exibe um botão que copia o texto para a área de transferência usando JavaScript."""
    components.html(
        f"""
        <script>
        function copyToClipboard_{botao_key}() {{
            navigator.clipboard.writeText("{texto}");
        }}
        </script>
        <button onclick="copyToClipboard_{botao_key}()">📋 Copiar</button>
        """,
        height=40,
    )

def gerar_codigo_indicacao():
    """Gera um código no formato: Trace + 6 números aleatórios + 3 letras aleatórias maiúsculas."""
    numeros = ''.join(random.choices(string.digits, k=6))
    letras = ''.join(random.choices(string.ascii_uppercase, k=3))
    return f"Trace{numeros}{letras}"

def gerar_link_whatsapp_solicitacao(nome, celular, cpf=None):
    """Gera um link do WhatsApp com mensagem pré-formatada para análise de cadastro."""
    cpf_texto = f"\nCPF: {cpf}" if cpf else ""
    mensagem = f"Temos um cadastro novo:\nNome: {nome}\nTelefone: {celular}{cpf_texto}"
    mensagem_codificada = quote(mensagem)
    return f"https://wa.me/{WHATSAPP_LOJA}?text={mensagem_codificada}"

def limpar_cpf(cpf):
    if not cpf:
        return None
    cpf_puro = re.sub(r'\D', '', cpf)
    return cpf_puro if len(cpf_puro) == 11 else None

def montar_endereco_completo(endereco, numero, complemento=""):
    """Helper para montar endereço consistente."""
    partes = [p.strip() for p in [endereco, numero] if p]
    res = " - ".join(partes)
    if complemento.strip():
        res += f" ({complemento.strip()})"
    return res

def safe_strip_codigo_indicador(texto):
    return texto.strip() if isinstance(texto, str) and texto.strip() else None

def render_campos_restritivos(key_suffix, valor_restritivo, cliente=None):
    if valor_restritivo == "Sim":
        st.markdown("### ⚠️ Informações sobre Restrição")
        col1, col2, col3 = st.columns(3)
        with col1:
            valor_salvo_qtd = cliente.get("restritivo_qtd_registros") if cliente else None
            qtd_registros = st.selectbox("Quantos registros?", options=list(range(1, 31)),
                                         index=valor_salvo_qtd - 1 if valor_salvo_qtd and 1 <= valor_salvo_qtd <= 30 else 0,
                                         key=f"restritivo_qtd_registros_{key_suffix}")
        with col2:
            ano_atual = datetime.now().year
            valor_salvo_ano = cliente.get("restritivo_ano_recente") if cliente else None
            ano_recente = st.selectbox("Qual ano mais recente?", options=list(range(2020, ano_atual + 1)),
                                       index=(valor_salvo_ano - 2020) if valor_salvo_ano and 2020 <= valor_salvo_ano <= ano_atual else (ano_atual - 2020),
                                       key=f"restritivo_ano_recente_{key_suffix}")
        with col3:
            valor_salvo_servico = cliente.get("restritivo_servico_internet") if cliente else None
            servico_internet = st.selectbox("Serviço de internet?", options=["Sim", "Não"],
                                            index=0 if valor_salvo_servico == "Sim" else 1 if valor_salvo_servico == "Não" else 0,
                                            key=f"restritivo_servico_internet_{key_suffix}")
        return qtd_registros, ano_recente, servico_internet
    else:
        return None, None, None

def render_motivo_recusa_ativacao(key_suffix, seguiu_ativacao, cliente=None):
    """Renderiza o campo de motivo de recusa apenas quando seguiu_ativacao == 'Não'"""
    if seguiu_ativacao == "Não":
        st.markdown("### 📊 Motivo da Recusa de Ativação")
        motivo_atual = None
        if cliente:
            motivo_atual = cliente.get("motivo_recusa_ativacao", "Selecione...")
        index_motivo = MOTIVOS_RECUSA_ATIVACAO.index(motivo_atual) if motivo_atual in MOTIVOS_RECUSA_ATIVACAO else 0
        motivo_recusa = st.selectbox("Selecione o motivo da recusa*", MOTIVOS_RECUSA_ATIVACAO, index=index_motivo,
                                     key=f"motivo_recusa_ativacao_{key_suffix}")
        detalhes_recusa = st.text_area("Detalhes adicionais sobre a recusa (opcional)",
                                       value=cliente.get("detalhes_recusa_ativacao", " ") if cliente else " ",
                                       placeholder="Ex: Cliente possui 3 registros no SPC dos últimos 6 meses...",
                                       key=f"detalhes_recusa_ativacao_{key_suffix}")
        return motivo_recusa, detalhes_recusa
    else:
        return None, None

============================================================================
✅ EXPANDER PARA VISUALIZAR/EDITAR CADASTRO COMPLETO
============================================================================
def expander_visualizar_editar(cliente, clientes_collection):
    if not cliente or not isinstance(cliente, dict):
        st.error("❌ Cliente não encontrado.")
        return

    with st.expander("📋 Visualizar / Editar Cadastro Completo", expanded=True):
        st.success(f"Visualizando cadastro de: {cliente['nome_completo']}")

        col_bt1, col_bt2 = st.columns(2)
        with col_bt1:
            if st.button("❌ Fechar", key="fechar_visualizar"):
                st.session_state["mostrar_visualizar"] = False
                if "mensagem_confirmacao_visualizar" in st.session_state:
                    del st.session_state["mensagem_confirmacao_visualizar"]
                st.rerun()
        with col_bt2:
            if st.button("🔙 Voltar", key="voltar_visualizar"):
                st.session_state["mostrar_visualizar"] = False
                st.session_state["mostrar_completar"] = False
                st.session_state["cliente_selecionado"] = None
                st.session_state["busca_pre_preenchida"] = " "
                st.session_state["acao_selecionada"] = "Novo Cadastro"
                st.session_state["form_key"] += 1
                st.rerun()

        # Verificação de endereço bloqueado
        endereco_atual = (cliente.get("endereco") or " ").strip()
        numero_atual = (cliente.get("numero") or " ").strip()
        if endereco_atual and numero_atual:
            cliente_bloqueado = clientes_collection.find_one({
                "endereco": endereco_atual, "numero": numero_atual, "endereco_bloqueado": True
            })
            if cliente_bloqueado:
                endereco_completo = montar_endereco_completo(endereco_atual, numero_atual, cliente.get("complemento", " "))
                st.markdown(
                    f'<div style="background-color:#ffe6e6; padding:4px 8px; border-radius:5px; display:inline-block; font-size:0.9em; margin-bottom:4px;">'
                    f'❌ <strong>Endereço bloqueado:</strong> {endereco_completo}</div>', unsafe_allow_html=True)
                if cliente_bloqueado.get("observacoes_bloqueio_endereco"):
                    st.markdown(
                        f'<div style="background-color:#f0f0f0; padding:4px 8px; border-radius:5px; margin-top:4px; font-size:0.9em;">'
                        f'📝 <strong>Observações:</strong> {cliente_bloqueado["observacoes_bloqueio_endereco"]}</div>',
                        unsafe_allow_html=True)
            else:
                st.markdown(
                    f'<div style="background-color:#e6ffe6; padding:4px 8px; border-radius:5px; display:inline-block; font-size:0.9em; margin-bottom:4px;">'
                    f'✅ <strong>Endereço: LIVRE</strong></div>', unsafe_allow_html=True)

        if st.button("🔒 Bloquear Este Endereço", key="bloquear_endereco_visualizar"):
            st.session_state["mostrar_form_bloqueio_visualizar"] = True

        if st.session_state.get("mostrar_form_bloqueio_visualizar", False):
            st.markdown("#### 📝 Observações de Bloqueio de Endereço:")
            observacoes_bloqueio = st.text_area("Por favor, descreva o motivo do bloqueio (ex: Fraude detectada, múltiplos CPFs).",
                                                value=cliente.get("observacoes_bloqueio_endereco", " "),
                                                key="observacoes_bloqueio_visualizar")
            col_conf, col_canc = st.columns(2)
            with col_conf:
                if st.button("✅ Confirmar Bloqueio", key="confirmar_bloqueio_visualizar"):
                    try:
                        query = {"endereco": endereco_atual, "numero": numero_atual}
                        complemento_atual = cliente.get("complemento", " ").strip()
                        if complemento_atual: query["complemento"] = complemento_atual
                        endereco_completo_bloq = montar_endereco_completo(endereco_atual, numero_atual, complemento_atual)
                        update_data = {"$set": {
                            "endereco_bloqueado": True,
                            "observacoes_bloqueio_endereco": observacoes_bloqueio.strip() if observacoes_bloqueio.strip() else None,
                            "endereco_completo_bloqueado": endereco_completo_bloq,
                            "bloqueado_por": st.session_state.get("nome_usuario", "Sistema"),
                            "data_bloqueio": datetime.now()
                        }}
                        result = clientes_collection.update_many(query, update_data)
                        st.success(f"✅ Endereço '{endereco_completo_bloq}' bloqueado com sucesso! ({result.modified_count} cadastros afetados.)")
                        cliente["endereco_bloqueado"] = True
                        cliente["observacoes_bloqueio_endereco"] = observacoes_bloqueio.strip() if observacoes_bloqueio.strip() else None
                        st.session_state["mostrar_form_bloqueio_visualizar"] = False
                        st.rerun()
                    except Exception as e:
                        st.error(f"❌ Erro ao bloquear endereço: {e}")
            with col_canc:
                if st.button("❌ Cancelar", key="cancelar_bloqueio_visualizar"):
                    st.session_state["mostrar_form_bloqueio_visualizar"] = False
                    st.rerun()

        key_suffix = "visualizar"

        # 🏢 CONDOMÍNIO - Selectbox de Condomínio (FORA do form)
        st.markdown("### 🏢 Localização")
        condominio_options = {"Nenhum / Não se aplica": None}
        condominio_options.update(get_condominio_options())
        cond_id_salvo = cliente.get("condominio_id")
        cond_nome_salvo = cliente.get("condominio_nome")
        index_cond = 0
        if cond_nome_salvo and cond_nome_salvo in condominio_options:
            index_cond = list(condominio_options.keys()).index(cond_nome_salvo)
        condominio_select = st.selectbox("Condomínio (Opcional)", options=list(condominio_options.keys()),
                                         index=index_cond, key=f"condominio_select_{key_suffix}")
        if condominio_select and condominio_select != "Nenhum / Não se aplica":
            if condominio_select != cond_nome_salvo:
                atualizar_endereco_por_condominio(condominio_select, key_suffix, condominio_options)
            else:
                st.session_state[f"condominio_id_{key_suffix}"] = cond_id_salvo
                st.session_state[f"condominio_nome_{key_suffix}"] = cond_nome_salvo

        # ✅ NOVO: Interesse em Produtos (Visualizar/Editar)
        st.markdown("### 🛒 Interesse em Produtos")
        produtos_interesse = st.multiselect(
            "Quais produtos despertaram interesse?",
            PRODUTOS_INTERESSE,
            default=cliente.get("produtos_interesse", []),
            help="Selecione um ou mais produtos discutidos",
            key=f"produtos_interesse_{key_suffix}"
        )

        with st.container(border=True):
            st.markdown("### 📌 Informações de Origem")
            origem_opcoes = ["Selecione...", "Radio Show FM", "Opa Suite", "Whatsapp", "Instagram", "Indicação", "Loja", "Panfleto", "PaP", "Ex Cliente", "Prospecção Ativa (Zap, Email, Telegram)", "Facebook", "Site"]
            origem_atual = cliente.get("origem", " ")
            index_origem = origem_opcoes.index(origem_atual) if origem_atual in origem_opcoes else 0
            origem = st.selectbox("De onde veio?", origem_opcoes, index=index_origem, key=f"origem_{key_suffix}")

            restritivo_opcoes = ["Selecione...", "Sim", "Não"]
            restritivo_atual = cliente.get("restritivo", " ")
            index_restritivo = restritivo_opcoes.index(restritivo_atual) if restritivo_atual in restritivo_opcoes else 0
            restritivo = st.selectbox("Restritivo?", restritivo_opcoes, index=index_restritivo, key=f"restritivo_{key_suffix}_fora_form")
            qtd_registros, ano_recente, servico_internet = render_campos_restritivos(key_suffix, restritivo, cliente)

            col_seg, col_int = st.columns([1, 1.2])
            with col_seg:
                seguiu_ativacao_opcoes = ["Selecione...", "Sim", "Não"]
                seguiu_ativacao_atual = cliente.get("seguiu_ativacao", " ")
                index_seguiu = seguiu_ativacao_opcoes.index(seguiu_ativacao_atual) if seguiu_ativacao_atual in seguiu_ativacao_opcoes else 0
                seguiu_ativacao = st.selectbox("Seguiu para Ativação?", seguiu_ativacao_opcoes, index=index_seguiu, key=f"seguiu_ativacao_{key_suffix}")
            with col_int:
                ja_possui_internet_atual = cliente.get("ja_possui_internet", " ")
                index_internet = OPCOES_INTERNET.index(ja_possui_internet_atual) if ja_possui_internet_atual in OPCOES_INTERNET else 0
                ja_possui_internet = st.selectbox("Já Possui Internet?", OPCOES_INTERNET, index=index_internet, key=f"ja_possui_internet_{key_suffix}")

            motivo_recusa, detalhes_recusa = render_motivo_recusa_ativacao(key_suffix, seguiu_ativacao, cliente)

            codigo_indicacao_atual = cliente.get("codigo_indicacao", " ")
            if codigo_indicacao_atual:
                st.markdown(f"### 🎁 Código de Indicação: `{codigo_indicacao_atual}`")

            st.markdown("### 📅 Follow-up")
            retorno_agendado_atual = cliente.get("retorno_agendado", " ")
            cliente_ja_tem_agendamento = False
            if retorno_agendado_atual and len(retorno_agendado_atual) == 10:
                try:
                    datetime.strptime(retorno_agendado_atual, "%Y-%m-%d")
                    cliente_ja_tem_agendamento = True
                except: pass

            if cliente_ja_tem_agendamento:
                st.info(f"⚠️ **Cliente já possui agendamento em {retorno_agendado_atual}**. O follow-up não será alterado para não perder a agenda.")
                followup_opcao = "Nenhum"
                retorno_agendado = retorno_agendado_atual
            else:
                followup_opcoes = ["Selecione...", "1 dia", "3 dias", "5 dias", "10 dias", "Personalizado (mês/ano)"]
                if retorno_agendado_atual:
                    if len(retorno_agendado_atual) == 7:
                        index_followup = followup_opcoes.index("Personalizado (mês/ano)")
                        try:
                            ano_salvo, mes_salvo = retorno_agendado_atual.split("-")
                            st.session_state[f"mes_{key_suffix}"] = int(mes_salvo)
                            st.session_state[f"ano_{key_suffix}"] = int(ano_salvo)
                        except: pass
                    elif len(retorno_agendado_atual) == 10:
                        try:
                            data_salva = datetime.strptime(retorno_agendado_atual, "%Y-%m-%d")
                            dias_diff = (data_salva.date() - datetime.now().date()).days
                            index_followup = followup_opcoes.index(f"{dias_diff} dia{'s' if dias_diff != 1 else ''}") if f"{dias_diff} dia{'s' if dias_diff != 1 else ''}" in followup_opcoes else 0
                        except: index_followup = 0
                    else: index_followup = 0
                else: index_followup = 0
                followup_opcao = st.selectbox("Follow-up em:", followup_opcoes, index=index_followup, key=f"followup_opcao_{key_suffix}")
                if followup_opcao == "Personalizado (mês/ano)":
                    dia_default = st.session_state.get(f"dias_{key_suffix}", datetime.now().day)
                    mes_default = st.session_state.get(f"mes_{key_suffix}", datetime.now().month)
                    ano_default = st.session_state.get(f"ano_{key_suffix}", datetime.now().year)
                    col_dia, col_mes, col_ano = st.columns(3)
                    with col_dia: dia = st.selectbox("Dia", list(range(1, 32)), index=min(dia_default - 1, 30), key=f"dias_{key_suffix}")
                    with col_mes: mes = st.selectbox("Mês", list(range(1, 13)), format_func=lambda x: datetime(2000, x, 1).strftime('%B'), index=mes_default - 1, key=f"mes_{key_suffix}")
                    with col_ano: ano = st.selectbox("Ano", list(range(datetime.now().year, datetime.now().year + 3)), index=ano_default - datetime.now().year, key=f"ano_{key_suffix}")
                    retorno_agendado = get_followup_date(followup_opcao, mes, ano, dia)
                elif followup_opcao in ["1 dia", "3 dias", "5 dias", "10 dias"]:
                    retorno_agendado = get_followup_date(followup_opcao)
                else: retorno_agendado = " "

            st.markdown("### 📝 Observações Gerais")
            observacoes_atual = cliente.get("observacoes", " ")
            observacoes = st.text_area("Adicione observações ou resumo sobre o cliente", value=observacoes_atual,
                                       placeholder="Ex: Cliente gostou da conexão e quer mais 3 pontos na semana que vem.",
                                       key=f"observacoes_{key_suffix}")

            st.markdown("### 📝 Observações de Follow-up *(exclusivo para acompanhamento)*")
            obs_followup_atual = cliente.get("observacoes_followup", " ")
            obs_followup = st.text_area(" ", value=obs_followup_atual,
                                        placeholder="Ex: Cliente ligou hoje, está aguardando retorno do financeiro.",
                                        key=f"observacoes_followup_{key_suffix}")

        with st.form("form_editar_cadastro"):
            st.markdown("### ⚙️ Informações do Sistema")
            st.text_input("Cadastrado por:", value=cliente.get("cadastrado_por", "N/A"), disabled=True, key="cadastrado_por_visualizar")
            data_cadastro = cliente.get("data_cadastro")
            if data_cadastro:
                if isinstance(data_cadastro, str):
                    try: data_cadastro = datetime.fromisoformat(data_cadastro)
                    except: data_cadastro = None
                if data_cadastro:
                    st.text_input("Data de cadastro:", value=data_cadastro.strftime("%d/%m/%Y %H:%M:%S"), disabled=True, key="data_cadastro_visualizar")
                else:
                    st.text_input("Data de cadastro:", value="Não disponível", disabled=True, key="data_cadastro_visualizar")
            else:
                st.text_input("Data de cadastro:", value="Não disponível", disabled=True, key="data_cadastro_visualizar")

            st.subheader("📝 Dados do Cliente")
            col_tel1, col_tel2, col_tel3 = st.columns(3)
            with col_tel1: celular = st.text_input("Celular Principal*", max_chars=15, value=cliente["celular"], key="celular_editar")
            with col_tel2:
                celular_contato_1 = st.text_input("Contato 1", max_chars=15, value=cliente.get("celular_contato_1", " "), placeholder="(00) 90000-0000", key="celular_contato_1_editar")
                descricao_contato_1 = st.text_input("Quem é esse contato?", max_chars=30, value=cliente.get("descricao_contato_1", " "), placeholder="Ex: Esposa", key="descricao_contato_1_editar")
            with col_tel3:
                celular_contato_2 = st.text_input("Contato 2", max_chars=15, value=cliente.get("celular_contato_2", " "), placeholder="(00) 90000-0000", key="celular_contato_2_editar")
                descricao_contato_2 = st.text_input("Quem é esse contato?", max_chars=30, value=cliente.get("descricao_contato_2", " "), placeholder="Ex: Mãe", key="descricao_contato_2_editar")

            nome_completo = st.text_input("Nome completo*", max_chars=80, value=cliente["nome_completo"], key="nome_completo_editar")
            col1, col2 = st.columns(2)
            with col1: cpf = st.text_input("CPF*", max_chars=14, placeholder="000.000.000-00", value=cliente.get("cpf", " "), key="cpf_editar")
            with col2: rg = st.text_input("RG*", max_chars=15, placeholder="12.345.678-9", value=cliente.get("rg", " "), key="rg_editar")

            data_nascimento_str = cliente.get("data_nascimento")
            data_nascimento = None
            if data_nascimento_str:
                try: data_nascimento = datetime.strptime(data_nascimento_str, "%Y-%m-%d").date()
                except: pass
            data_nascimento = st.date_input("Data de nascimento*", value=data_nascimento, format="DD/MM/YYYY", key="data_nascimento_editar", min_value=datetime(1900, 1, 1))

            email = st.text_input("Email*", max_chars=50, value=cliente.get("email", " "), key="email_editar")

            col1, col2 = st.columns([3, 1])
            with col1: endereco = st.text_input("Endereço*", max_chars=100, value=st.session_state.get(f"endereco_{key_suffix}", cliente.get("endereco", " ")), key=f"endereco_{key_suffix}")
            with col2: numero = st.text_input("Número*", max_chars=6, value=st.session_state.get(f"numero_{key_suffix}", cliente.get("numero", " ")), key=f"numero_{key_suffix}")

            col_bloco, col_apto = st.columns(2)
            with col_bloco: bloco = st.text_input("Bloco", value=cliente.get("bloco", " "), key=f"bloco_{key_suffix}")
            with col_apto: apartamento = st.text_input("Apartamento", value=cliente.get("apartamento", " "), key=f"apartamento_{key_suffix}")

            col1, col2 = st.columns(2)
            with col1: complemento = st.text_input("Complemento", max_chars=50, value=cliente.get("complemento", " "), key=f"complemento_{key_suffix}")
            with col2: ponto_referencia = st.text_input("Ponto de referência", max_chars=100, value=cliente.get("ponto_referencia", " "), key=f"ponto_referencia_{key_suffix}")

            col1, col2 = st.columns(2)
            with col1: bairro = st.text_input("Bairro*", max_chars=50, value=cliente.get("bairro", " "), key=f"bairro_{key_suffix}")
            with col2: cidade = st.text_input("Cidade*", max_chars=50, value=st.session_state.get(f"cidade_{key_suffix}", cliente.get("cidade", "Rio de Janeiro")), key=f"cidade_{key_suffix}")

            col1, col2 = st.columns(2)
            with col1:
                tipo_moradia_atual = cliente.get("tipo_moradia", " ")
                index_tipo_moradia = ["Selecione...", "Própria", "Alugada", "Cedida"].index(tipo_moradia_atual) if tipo_moradia_atual in ["Própria", "Alugada", "Cedida"] else 0
                tipo_moradia = st.selectbox("Tipo de Moradia*", ["Selecione...", "Própria", "Alugada", "Cedida"], index=index_tipo_moradia, key=f"tipo_moradia_{key_suffix}")
            with col2:
                tempo_moradia_atual = cliente.get("tempo_moradia", {})
                tempo_valor_atual = tempo_moradia_atual.get("valor", 0) if isinstance(tempo_moradia_atual, dict) else 0
                tempo_unidade_atual = tempo_moradia_atual.get("unidade", "Anos") if isinstance(tempo_moradia_atual, dict) else "Anos"
                tempo_moradia_valor = st.selectbox("Tempo de Moradia", list(range(0, 51)), index=min(tempo_valor_atual, 50), key=f"tempo_moradia_valor_{key_suffix}")
                tempo_moradia_unidade = st.selectbox(" ", ["Anos", "Meses"], index=0 if tempo_unidade_atual == "Anos" else 1, key=f"tempo_moradia_unidade_{key_suffix}")

            plano_atual = cliente.get("plano_escolhido")
            index_plano = (PLANOS.index(plano_atual) + 1) if plano_atual in PLANOS else 0
            plano_escolhido = st.selectbox("Plano escolhido*", ["Selecione..."] + PLANOS, index=index_plano, key="plano_escolhido_editar")
            profissao = st.text_input("Profissão*", max_chars=50, value=cliente.get("profissao", " "), key="profissao_editar")
            data_vencimento = st.selectbox("Melhor data de vencimento*", list(range(1, 32)), index=(int(cliente["data_vencimento"]) - 1) if cliente.get("data_vencimento") else 0, key="data_vencimento_editar")

            codigo_indicador_atual = cliente.get("codigo_indicador", " ")
            codigo_indicador = st.text_input("Código de Quem Indicou", max_chars=15, value=codigo_indicador_atual, key="codigo_indicador_editar")

            st.subheader("📷 Foto do Documento")
            foto_documento_base64 = cliente.get("foto_documento_base64")
            if foto_documento_base64:
                try: st.image(base64.b64decode(foto_documento_base64), caption="Foto atual", width=250)
                except: st.warning("⚠️ Não foi possível carregar a foto salva.")
            foto_documento = st.file_uploader("Envie uma nova foto (JPG ou PNG) - Opcional", type=["jpg", "png", "jpeg"], key="foto_documento_editar")

            st.subheader("📦 Equipamento em Comodato")
            modelo_atual = cliente.get("equipamento_modelo")
            index_modelo = MODELOS_ROTEADORES.index(modelo_atual) if modelo_atual in MODELOS_ROTEADORES else 0
            equip_modelo = st.selectbox("Marca/Modelo*", MODELOS_ROTEADORES, index=index_modelo, key="equip_modelo_editar")
            equip_desc = st.text_input("Descrição do Equipamento", max_chars=50, value=cliente.get("equipamento_descricao", "Roteador Wi-Fi"), key="equip_desc_editar")
            equip_codigo = st.text_input("Informação Adicional*", max_chars=50, placeholder="Ex: Número de série", value=cliente.get("equipamento_codigo", " "), key="equip_codigo_editar")
            equip_acessorios = st.text_input("Acessórios", max_chars=100, value=cliente.get("equipamento_acessorios", "Fonte de alimentação, cabo Ethernet"), key="equip_acessorios_editar")

            col1, col2 = st.columns(2)
            with col1:
                if st.session_state.get("gerando_contrato_visualizar"): st.form_submit_button("⏳ Gerando contrato...", disabled=True)
                elif st.session_state.get("contrato_pronto_visualizar"):
                    if st.form_submit_button("📥 Baixar Contrato Gerado", type="secondary"): pass
                else:
                    if st.form_submit_button("✍️ Gerar Contrato", type="secondary"):
                        cpf_valido = limpar_cpf(cpf)
                        if not cpf_valido: st.error("❌ CPF inválido!")
                        elif not all([nome_completo, cpf_valido, endereco, celular, plano_escolhido != "Selecione..."]): st.error("❌ Preencha todos os campos obrigatórios para gerar contrato!")
                        else:
                            st.session_state["dados_temp_contrato_visualizar"] = {"nome_contratante": nome_completo, "cpf_cnpj_contratante": cpf_valido, "endereco_contratante": endereco, "numero_contratante": numero, "complemento": complemento, "cidade": cidade, "bairro": bairro, "telefone_contratante": celular, "plano_contratado": plano_escolhido, "modalidade": "Pós Pago"}
                            st.session_state["gerando_contrato_visualizar"] = True
                            st.session_state["nome_arquivo_contrato_visualizar"] = f"Contrato_{nome_completo.replace(' ', '_')}.pdf"
                            st.rerun()
            with col2:
                if st.session_state.get("gerando_comodato_visualizar"): st.form_submit_button("⏳ Gerando termo...", disabled=True)
                elif st.session_state.get("comodato_pronto_visualizar"):
                    if st.form_submit_button("📥 Baixar Termo de Comodato", type="secondary"): pass
                else:
                    if st.form_submit_button("📄 Gerar Termo de Comodato", type="secondary"):
                        cpf_valido = limpar_cpf(cpf)
                        if not cpf_valido: st.error("❌ CPF inválido!")
                        elif not all([nome_completo, cpf_valido, endereco, celular, equip_modelo, equip_codigo]): st.error("❌ Preencha todos os campos obrigatórios do comodato!")
                        else:
                            st.session_state["dados_temp_comodato_visualizar"] = {"nome_contratante": nome_completo, "cpf_cnpj_contratante": cpf_valido, "endereco_contratante": endereco, "numero_contratante": numero, "complemento": complemento, "cidade": cidade, "bairro": bairro, "telefone_contratante": celular, "equipamento_descricao": equip_desc, "equipamento_modelo": equip_modelo, "equipamento_codigo": equip_codigo, "equipamento_acessorios": equip_acessorios}
                            st.session_state["gerando_comodato_visualizar"] = True
                            st.session_state["nome_arquivo_comodato_visualizar"] = f"Termo_Comodato_{nome_completo.replace(' ', '_')}.pdf"
                            st.rerun()

            if st.form_submit_button("📝 Gerar Mensagem de Confirmação", type="secondary"):
                cpf_limpo = limpar_cpf(cpf) or "Não informado"
                tempo_moradia_texto = f"{tempo_moradia_valor} {tempo_moradia_unidade.lower()}" if tempo_moradia_valor > 0 else "Não informado"
                campos = {"Nome completo": nome_completo, "Celular Principal": celular, "Contato 1": f"{celular_contato_1} ({descricao_contato_1})" if celular_contato_1 and descricao_contato_1 else celular_contato_1 or "—", "Contato 2": f"{celular_contato_2} ({descricao_contato_2})" if celular_contato_2 and descricao_contato_2 else celular_contato_2 or "—", "Email": email, "Data de nascimento": data_nascimento.strftime("%d/%m/%Y") if data_nascimento else "Não informado", "CPF": cpf_limpo, "RG": rg, "Endereço": endereco, "Número": numero, "Complemento": complemento or "Não informado", "Cidade": cidade or "Não informada", "Bairro": bairro, "Ponto de referência": ponto_referencia or "Não informado", "Tipo de Moradia": tipo_moradia, "Tempo de Moradia": tempo_moradia_texto, "Plano escolhido": plano_escolhido, "Profissão": profissao, "Melhor data de vencimento": str(data_vencimento)}
                mensagem = "Os dados abaixo estão corretos?\n"
                for chave, valor in campos.items(): mensagem += f"{chave}: {valor}\n"
                mensagem += "\nAguardamos sua resposta para prosseguirmos. Qualquer dúvida, estou à disposição!"
                st.session_state["mensagem_confirmacao_visualizar"] = mensagem
                st.success("✅ Mensagem gerada!")

            atualizar = st.form_submit_button("🔄 Atualizar Cadastro", type="primary")
            if atualizar:
                if not all([nome_completo, celular, plano_escolhido != "Selecione..."]): st.error("⚠️ Nome, Celular e Plano são obrigatórios!")
                elif seguiu_ativacao == "Não" and (not motivo_recusa or motivo_recusa == "Selecione..."): st.error("⚠️ Quando 'Seguiu para Ativação' for 'Não', é obrigatório selecionar o motivo da recusa.")
                else:
                    if seguiu_ativacao == "Sim" and not cliente_ja_tem_agendamento: retorno_agendado = " "
                    restritivo_valor_salvar = restritivo if restritivo != "Selecione..." else " "
                    codigo_indicacao = cliente.get("codigo_indicacao")
                    if seguiu_ativacao == "Sim" and not codigo_indicacao: codigo_indicacao = gerar_codigo_indicacao()
                    cpf_limpo = limpar_cpf(cpf)

                    update_data = {
                        "nome_completo ": nome_completo, "celular ": normalize_phone(celular),
                        "celular_contato_1 ": normalize_phone(celular_contato_1) if celular_contato_1 and celular_contato_1.strip() else None,
                        "celular_contato_2 ": normalize_phone(celular_contato_2) if celular_contato_2 and celular_contato_2.strip() else None,
                        "descricao_contato_1 ": descricao_contato_1.strip() if descricao_contato_1 and descricao_contato_1.strip() else None,
                        "descricao_contato_2 ": descricao_contato_2.strip() if descricao_contato_2 and descricao_contato_2.strip() else None,
                        "email ": email if email else None, "data_nascimento ": data_nascimento.isoformat() if data_nascimento else None,
                        "cpf ": cpf_limpo, "rg ": rg if rg else None, "endereco ": endereco if endereco else None, "numero ": numero if numero else None,
                        "complemento ": complemento if complemento else None, "cidade ": cidade if cidade else None, "bairro ": bairro if bairro else None,
                        "ponto_referencia ": ponto_referencia if ponto_referencia else None,
                        "tipo_moradia ": tipo_moradia if tipo_moradia != "Selecione..." else None,
                        "tempo_moradia ": {"valor ": tempo_moradia_valor, "unidade ": tempo_moradia_unidade} if tempo_moradia_valor > 0 else None,
                        "plano_escolhido ": plano_escolhido if plano_escolhido != "Selecione..." else None,
                        "profissao ": profissao if profissao else None, "data_vencimento ": data_vencimento,
                        "origem ": origem if origem != "Selecione..." else " ", "restritivo ": restritivo_valor_salvar,
                        "restritivo_qtd_registros ": qtd_registros if restritivo_valor_salvar == "Sim" else None,
                        "restritivo_ano_recente ": ano_recente if restritivo_valor_salvar == "Sim" else None,
                        "restritivo_servico_internet ": servico_internet if restritivo_valor_salvar == "Sim" else None,
                        "seguiu_ativacao ": seguiu_ativacao if seguiu_ativacao != "Selecione..." else " ",
                        "motivo_recusa_ativacao ": motivo_recusa if motivo_recusa and motivo_recusa != "Selecione..." else None,
                        "detalhes_recusa_ativacao ": detalhes_recusa.strip() if detalhes_recusa and detalhes_recusa.strip() else None,
                        "ja_possui_internet ": ja_possui_internet if ja_possui_internet != "Selecione..." else " ",
                        "retorno_agendado ": cliente.get("retorno_agendado ", retorno_agendado),
                        "periodo ": cliente.get("periodo ", None), "observacoes_agendamento ": cliente.get("observacoes_agendamento ", None),
                        "contrato_titular ": cliente.get("contrato_titular ", False), "status_agendamento ": cliente.get("status_agendamento ", "agendado "),
                        "ativo ": cliente.get("ativo ", False), "data_ativacao ": cliente.get("data_ativacao ", None),
                        "reagendado_para ": cliente.get("reagendado_para ", None), "motivo_cancelamento ": cliente.get("motivo_cancelamento ", None),
                        "data_cancelamento ": cliente.get("data_cancelamento ", None),
                        "observacoes ": observacoes if observacoes else " ", "observacoes_followup ": obs_followup.strip(),
                        # ✅ NOVO: Atualizar produtos de interesse
                        "produtos_interesse ": produtos_interesse,
                        "codigo_indicacao ": codigo_indicacao, "codigo_indicador ": safe_strip_codigo_indicador(codigo_indicador),
                        "endereco_bloqueado ": cliente.get("endereco_bloqueado ", False),
                        "observacoes_bloqueio_endereco ": cliente.get("observacoes_bloqueio_endereco ", None),
                        "condominio_id ": st.session_state.get(f"condominio_id_{key_suffix} "), "condominio_nome ": st.session_state.get(f"condominio_nome_{key_suffix} "),
                        "bloco ": bloco if bloco else None, "apartamento ": apartamento if apartamento else None,
                    }
                    if foto_documento:
                        foto_bytes = foto_documento.read()
                        foto_base64 = base64.b64encode(foto_bytes).decode('utf-8')
                        update_data["foto_documento_base64 "] = foto_base64
                    else:
                        update_data["foto_documento_base64 "] = cliente.get("foto_documento_base64 ", " ")
                    if equip_desc and equip_desc != "Roteador Wi-Fi ": update_data["equipamento_descricao "] = equip_desc
                    if equip_modelo and equip_modelo in MODELOS_ROTEADORES: update_data["equipamento_modelo "] = equip_modelo
                    if equip_codigo: update_data["equipamento_codigo "] = equip_codigo
                    if equip_acessorios and equip_acessorios != "Fonte de alimentação, cabo Ethernet ": update_data["equipamento_acessorios "] = equip_acessorios

                    try:
                        clientes_collection.update_one({"_id ": cliente["_id "]}, {"$set ": update_data})
                        st.success("✅ Cadastro atualizado com sucesso!")
                        st.balloons()
                        st.rerun()
                    except Exception as e: st.error(f"❌ Erro ao atualizar: {e}")

    if "mensagem_confirmacao_visualizar " in st.session_state:
        st.subheader("📧 Mensagem de Confirmação Gerada:")
        st.code(st.session_state["mensagem_confirmacao_visualizar "], language="text ")
        if st.button("🗑️ Limpar Mensagem ", key="limpar_msg_visualizar "):
            del st.session_state["mensagem_confirmacao_visualizar "]
            st.rerun()

============================================================================
✅ FUNÇÃO PRINCIPAL: render_cadastro
============================================================================
def render_cadastro(clientes_collection):
    st.session_state["clientes_collection"] = clientes_collection
    if "mostrar_botao_novo " not in st.session_state: st.session_state["mostrar_botao_novo "] = False
    if "acao_selecionada " not in st.session_state: st.session_state["acao_selecionada "] = "Novo Cadastro "
    if "busca_pre_preenchida " not in st.session_state: st.session_state["busca_pre_preenchida "] = " "
    if "form_key " not in st.session_state: st.session_state["form_key "] = 0
    if "mostrar_completar " not in st.session_state: st.session_state["mostrar_completar "] = False
    if "mostrar_visualizar " not in st.session_state: st.session_state["mostrar_visualizar "] = False
    if "cliente_selecionado " not in st.session_state: st.session_state["cliente_selecionado "] = None
    if "gerando_contrato_principal " not in st.session_state: st.session_state["gerando_contrato_principal "] = False
    if "contrato_pronto_principal " not in st.session_state: st.session_state["contrato_pronto_principal "] = False
    if "gerando_comodato_principal " not in st.session_state: st.session_state["gerando_comodato_principal "] = False
    if "comodato_pronto_principal " not in st.session_state: st.session_state["comodato_pronto_principal "] = False
    if "ignorar_bloqueio " not in st.session_state: st.session_state["ignorar_bloqueio "] = False
    if "endereco_bloqueado_confirmado " not in st.session_state: st.session_state["endereco_bloqueado_confirmado "] = {}

    st.markdown("### 🔍 Buscar cliente por nome, CPF ou Celular ")
    busca_global = st.text_input("Digite o nome, CPF ou celular do cliente ", placeholder="Ex: Diego Roberto, 21973570259 ou (11) 98765-4321 ",
                                 key=f"busca_global_{st.session_state['form_key']} ")

    if busca_global.strip():
        busca_normalizada = normalize_phone(busca_global)
        cpf_puro = re.sub(r'\D', '', busca_global)
        query = {"$or ": []}
        query["$or "].append({"nome_completo ": {"$regex ": busca_global, "$options ": "i "}})
        if busca_normalizada:
            query["$or "].append({"celular ": busca_normalizada})
            query["$or "].append({"celular_contato_1 ": busca_normalizada})
            query["$or "].append({"celular_contato_2 ": busca_normalizada})
        if len(cpf_puro) == 11 and cpf_puro[0] != '9': query["$or "].append({"cpf ": cpf_puro})
        query["$or "].append({"descricao_contato_1 ": {"$regex ": busca_global, "$options ": "i "}})
        query["$or "].append({"descricao_contato_2 ": {"$regex ": busca_global, "$options ": "i "}})

        if query["$or "]:
            clientes_encontrados = clientes_collection.find(query)
            clientes_lista = list(clientes_encontrados)
            if len(clientes_lista) > 0:
                st.success(f"✅ {len(clientes_lista)} cliente(s) encontrado(s)!")
                for cliente in clientes_lista:
                    if not cliente or not isinstance(cliente, dict): continue
                    with st.expander(f"📋 {cliente['nome_completo']} ", expanded=False):
                        st.write(f"**Nome:** {cliente.get('nome_completo', 'N/A')} ")
                        st.write(f"**CPF:** {cliente.get('cpf', 'N/A')} ")
                        st.write(f"**Celular (Principal):** {cliente.get('celular', 'N/A')} ")
                        cont1 = cliente.get('celular_contato_1')
                        desc1 = cliente.get('descricao_contato_1')
                        cont2 = cliente.get('celular_contato_2')
                        desc2 = cliente.get('descricao_contato_2')
                        if cont1 or cont2:
                            st.markdown("**Contatos Adicionais:** ")
                            if cont1: st.write(f"• {cont1} ({desc1 or '—'}) ")
                            if cont2: st.write(f"• {cont2} ({desc2 or '—'}) ")
                        st.write(f"**Email:** {cliente.get('email', 'N/A')} ")
                        st.write(f"**Plano:** {cliente.get('plano_escolhido', 'N/A')} ")
                        st.write(f"**Tipo de Cadastro:** {cliente.get('tipo_cadastro', 'N/A').title()} ")
                        st.write(f"**Status:** {cliente.get('status', 'N/A').title()} ")
                        st.write(f"**Origem:** {cliente.get('origem', 'N/A')} ")
                        st.write(f"**Cadastrado por:** {cliente.get('cadastrado_por', 'N/A')} ")
                        if cliente.get("condominio_nome "): st.write(f"**Condomínio:** {cliente.get('condominio_nome', 'N/A')} ")
                        if cliente.get("bloco "): st.write(f"**Bloco:** {cliente.get('bloco', 'N/A')} ")
                        if cliente.get("apartamento "): st.write(f"**Apartamento:** {cliente.get('apartamento', 'N/A')} ")
                        # ✅ NOVO: Exibir produtos de interesse na busca
                        produtos = cliente.get('produtos_interesse', [])
                        if produtos:
                            st.write(f"**Interesse em Produtos:** {', '.join(produtos)} ")

                        endereco_atual = (cliente.get("endereco ") or " ").strip()
                        numero_atual = (cliente.get("numero ") or " ").strip()
                        if endereco_atual and numero_atual:
                            cliente_bloqueado = clientes_collection.find_one({"endereco ": endereco_atual, "numero ": numero_atual, "endereco_bloqueado ": True})
                            if cliente_bloqueado:
                                endereco_completo = montar_endereco_completo(endereco_atual, numero_atual, cliente.get("complemento ", " "))
                                st.markdown(f'<div style="background-color:#ffe6e6; padding:4px 8px; border-radius:5px; display:inline-block; font-size:0.9em; margin-bottom:4px;">❌ <strong>Endereço bloqueado:</strong> {endereco_completo}</div>', unsafe_allow_html=True)
                            else:
                                st.markdown(f'<div style="background-color:#e6ffe6; padding:4px 8px; border-radius:5px; display:inline-block; font-size:0.9em; margin-bottom:4px;">✅ <strong>Endereço: LIVRE</strong></div>', unsafe_allow_html=True)
                        data_cadastro = cliente.get("data_cadastro ")
                        if data_cadastro:
                            if isinstance(data_cadastro, str):
                                try: data_cadastro = datetime.fromisoformat(data_cadastro)
                                except: data_cadastro = None
                            if data_cadastro: st.write(f"**Data de Cadastro:** {data_cadastro.strftime('%d/%m/%Y %H:%M:%S')} ")
                            else: st.write("**Data de Cadastro:** Não disponível ")
                        else: st.write("**Data de Cadastro:** Não disponível ")
                        st.write(f"**Restritivo:** {cliente.get('restritivo', 'N/A')} ")
                        if cliente.get("restritivo ") == "Sim ":
                            st.write(f"**Registros:** {cliente.get('restritivo_qtd_registros', 'N/A')} ")
                            st.write(f"**Ano mais recente:** {cliente.get('restritivo_ano_recente', 'N/A')} ")
                            st.write(f"**Serviço de internet:** {cliente.get('restritivo_servico_internet', 'N/A')} ")
                        st.write(f"**Seguiu para Ativação:** {cliente.get('seguiu_ativacao', 'N/A')} ")
                        if cliente.get("seguiu_ativacao ") == "Não " and cliente.get("motivo_recusa_ativacao "):
                            st.write(f"**Motivo da Recusa:** {cliente.get('motivo_recusa_ativacao', 'N/A')} ")
                            if cliente.get("detalhes_recusa_ativacao "): st.write(f"**Detalhes:** {cliente.get('detalhes_recusa_ativacao', 'N/A')} ")
                        st.write(f"**Já Possui Internet?:** {cliente.get('ja_possui_internet', 'N/A')} ")
                        st.write(f"**Código de Indicação:** {cliente.get('codigo_indicacao', 'N/A')} ")
                        if cliente.get("retorno_agendado "): st.write(f"**Retorno agendado:** {cliente['retorno_agendado']} ")
                        if cliente.get("observacoes "): st.write(f"**Observações Gerais:** {cliente['observacoes']} ")
                        if cliente.get("observacoes_followup "): st.write(f"**Observações de Follow-up:** {cliente['observacoes_followup']} ")

                        col1, col2 = st.columns(2)
                        with col1:
                            if st.button("📝 Ver Detalhes / Editar ", key=f"ver_detalhes_{cliente['_id']} "):
                                st.session_state["mostrar_visualizar "] = False
                                st.session_state["mostrar_completar "] = False
                                st.session_state["cliente_selecionado "] = None
                                st.session_state["cliente_selecionado "] = copy.deepcopy(dict(cliente))
                                st.session_state["mostrar_visualizar "] = True
                                st.rerun()
                        with col2:
                            if cliente.get("tipo_cadastro ") == "simples ":
                                if st.button("✏️ Completar Cadastro ", key=f"completar_{cliente['_id']} "):
                                    st.session_state["mostrar_visualizar "] = False
                                    st.session_state["mostrar_completar "] = False
                                    st.session_state["cliente_selecionado "] = None
                                    st.session_state["cliente_selecionado "] = copy.deepcopy(dict(cliente))
                                    st.session_state["mostrar_completar "] = True
                                    st.rerun()
                            else: st.write("Cadastro já completo ")
            else: st.warning("⚠️ Nenhum cliente encontrado. ")

    if st.button("➕ Iniciar Novo Cadastro ", key="novo_cadastro_via_busca "):
        st.session_state["acao_selecionada "] = "Novo Cadastro "
        st.session_state["busca_pre_preenchida "] = " "
        st.rerun()
    else: st.info("🔍 Digite um nome, CPF (11 dígitos) ou celular para buscar. ")

    if st.session_state["mostrar_completar "] and st.session_state["cliente_selecionado "]:
        try:
            from .cadastro_completo import expander_completar_cadastro
            expander_completar_cadastro(st.session_state["cliente_selecionado "], clientes_collection)
        except: st.info("Função de completar cadastro em desenvolvimento. ")

    if st.session_state["mostrar_visualizar "] and st.session_state["cliente_selecionado "]:
        expander_visualizar_editar(st.session_state["cliente_selecionado "], clientes_collection)

    acao = st.radio("Selecione a ação: ", ["Novo Cadastro ", "Completar Cadastro Existente "],
                    index=0 if st.session_state["acao_selecionada "] == "Novo Cadastro " else 1, horizontal=True,
                    help="Completar: busca um cadastro simples e permite preencher os dados restantes. ")

    if acao == "Novo Cadastro " and not st.session_state.get("mostrar_visualizar ", False) and not st.session_state.get("mostrar_completar ", False):
        tipo_cadastro = st.radio("Tipo de cadastro: ", ["Cadastro Simples ", "Cadastro CRM "], horizontal=True)
        st.subheader(f"📝 {tipo_cadastro} ")

        def get_valor_inicial(chave, default=" "):
            return st.session_state.get("dados_temp_bloqueio ", {}).get(chave, default)

        nome_completo = st.text_input("Nome completo* ", value=get_valor_inicial("nome_completo ", " "), key=f"nome_completo_{st.session_state['form_key']} ")

        col_tel1, col_tel2, col_tel3 = st.columns(3)
        with col_tel1:
            celular_principal = st.text_input("Celular Principal* ", max_chars=15, placeholder="(00) 90000-0000 ", value=get_valor_inicial("celular_principal ", " "), key=f"campo_celular_principal_{st.session_state['form_key']} ")
        with col_tel2:
            celular_contato_1 = st.text_input("Contato 1 ", max_chars=15, placeholder="(00) 90000-0000 ", value=get_valor_inicial("celular_contato_1 ", " "), key=f"campo_celular_contato_1_{st.session_state['form_key']} ")
            descricao_contato_1 = st.text_input("Quem é esse contato? ", max_chars=30, placeholder="Ex: Esposa ", value=get_valor_inicial("descricao_contato_1 ", " "), key=f"descricao_contato_1_{st.session_state['form_key']} ")
        with col_tel3:
            celular_contato_2 = st.text_input("Contato 2 ", max_chars=15, placeholder="(00) 90000-0000 ", value=get_valor_inicial("celular_contato_2 ", " "), key=f"campo_celular_contato_2_{st.session_state['form_key']} ")
            descricao_contato_2 = st.text_input("Quem é esse contato? ", max_chars=30, placeholder="Ex: Mãe ", value=get_valor_inicial("descricao_contato_2 ", " "), key=f"descricao_contato_2_{st.session_state['form_key']} ")

        cpf = st.text_input("CPF* ", max_chars=14, placeholder="000.000.000-00 ", value=get_valor_inicial("cpf ", " "), key=f"campo_cpf_{st.session_state['form_key']} ") if tipo_cadastro == "Cadastro CRM " else " "

        restritivo = " "
        qtd_registros = ano_recente = servico_internet = None
        seguiu_ativacao = " "
        retorno_agendado = " "
        observacoes = " "
        observacoes_followup_simples = " "
        motivo_recusa = None
        detalhes_recusa = None

        if tipo_cadastro == "Cadastro CRM ":
            with st.container(border=True):
                st.markdown("### 📌 Informações de Origem ")
                origem_opcoes = ["Selecione... ", "Radio Show FM ", "Opa Suite ", "Whatsapp ", "Instagram ", "Indicação ", "Loja ", "Panfleto ", "PaP ", "Ex Cliente ", "Prospecção Ativa (Zap, Email, Telegram) ", "Facebook ", "Site "]
                origem = st.selectbox("De onde veio? ", origem_opcoes, index=origem_opcoes.index(get_valor_inicial("origem ", "Selecione... ")) if get_valor_inicial("origem ") in origem_opcoes else 0, key=f"origem_novo_{st.session_state['form_key']} ")
                st.markdown("### 📅 Follow-up ")
                col_auto, col_manual = st.columns([2, 3])
                with col_auto:
                    followup_opcao = st.selectbox("Follow-up automático: ", ["Nenhum ", "1 dia ", "3 dias ", "5 dias ", "10 dias "], index=["Nenhum ", "1 dia ", "3 dias ", "5 dias ", "10 dias "].index(get_valor_inicial("followup_opcao ", "Nenhum ")), key=f"followup_auto_{st.session_state['form_key']} ")
                with col_manual:
                    data_personalizada_str = get_valor_inicial("data_personalizada ")
                    data_personalizada = datetime.strptime(data_personalizada_str, "%Y-%m-%d ").date() if data_personalizada_str else None
                    data_personalizada = st.date_input("Ou escolha uma data específica: ", value=data_personalizada, min_value=datetime.today().date(), format="DD/MM/YYYY ", key=f"data_followup_manual_{st.session_state['form_key']} ")
                    if data_personalizada: retorno_agendado = data_personalizada.strftime("%Y-%m-%d ")
                    elif followup_opcao != "Nenhum ": retorno_agendado = get_followup_date(followup_opcao)
                    else: retorno_agendado = " "
                restritivo = st.selectbox("Restritivo? ", ["Selecione... ", "Sim ", "Não "], index=["Selecione... ", "Sim ", "Não "].index(get_valor_inicial("restritivo ", "Selecione... ")), key=f"restritivo_novo_{st.session_state['form_key']} ")
                qtd_registros, ano_recente, servico_internet = render_campos_restritivos("novo ", restritivo)
                col_seg, col_int = st.columns([1, 1.2])
                with col_seg:
                    seguiu_ativacao = st.selectbox("Seguiu para Ativação? ", ["Selecione... ", "Sim ", "Não "], index=["Selecione... ", "Sim ", "Não "].index(get_valor_inicial("seguiu_ativacao ", "Selecione... ")), key=f"seguiu_ativacao_novo_{st.session_state['form_key']} ")
                with col_int:
                    ja_possui_internet = st.selectbox("Já Possui Internet? ", OPCOES_INTERNET, index=OPCOES_INTERNET.index(get_valor_inicial("ja_possui_internet ", "Selecione... ")) if get_valor_inicial("ja_possui_internet ") in OPCOES_INTERNET else 0, key=f"ja_possui_internet_novo_{st.session_state['form_key']} ")
                motivo_recusa, detalhes_recusa = render_motivo_recusa_ativacao("novo ", seguiu_ativacao)
                codigo_indicador = st.text_input("Código de Quem Indicou ", max_chars=15, value=get_valor_inicial("codigo_indicador ", " "), key=f"codigo_indicador_novo_{st.session_state['form_key']} ")
                st.markdown("### 📝 Observações ")
                observacoes = st.text_area("Adicione observações ou resumo sobre o cliente ", placeholder="Ex: Cliente gostou da conexão e quer mais 3 pontos na semana que vem. ", value=get_valor_inicial("observacoes ", " "), key=f"observacoes_novo_{st.session_state['form_key']} ")
                st.markdown("### 📝 Observações de Follow-up *(exclusivo para acompanhamento)* ")
                observacoes_followup_simples = st.text_area("  ", placeholder="Ex: Cliente ligou hoje, está aguardando retorno do financeiro. ", value=get_valor_inicial("observacoes_followup_simples ", " "), key=f"observacoes_followup_novo_{st.session_state['form_key']} ")
        else:
            with st.container(border=True):
                st.markdown("### 📅 Follow-up (opcional) ")
                col_auto, col_manual = st.columns([2, 3])
                with col_auto:
                    followup_opcao_simples = st.selectbox("Follow-up automático: ", ["Nenhum ", "1 dia ", "3 dias ", "5 dias ", "10 dias "], index=["Nenhum ", "1 dia ", "3 dias ", "5 dias ", "10 dias "].index(get_valor_inicial("followup_opcao_simples ", "Nenhum ")), key=f"followup_auto_simples_{st.session_state['form_key']} ")
                with col_manual:
                    data_personalizada_simples_str = get_valor_inicial("data_personalizada_simples ")
                    data_personalizada_simples = datetime.strptime(data_personalizada_simples_str, "%Y-%m-%d ").date() if data_personalizada_simples_str else None
                    data_personalizada_simples = st.date_input("Ou escolha uma data específica: ", value=data_personalizada_simples, min_value=datetime.today().date(), format="DD/MM/YYYY ", key=f"data_followup_manual_simples_{st.session_state['form_key']} ")
                    if data_personalizada_simples: retorno_agendado = data_personalizada_simples.strftime("%Y-%m-%d ")
                    elif followup_opcao_simples != "Nenhum ": retorno_agendado = get_followup_date(followup_opcao_simples)
                    else: retorno_agendado = " "
                observacoes_followup_simples = st.text_area("Adicione observações iniciais para o follow-up ", placeholder="Ex: Cliente está em dúvida entre dois planos. ", value=get_valor_inicial("observacoes_followup_simples ", " "), key=f"observacoes_followup_simples_{st.session_state['form_key']} ")
            origem = "Selecione... "
            observacoes = " "
            ja_possui_internet = " "

        # 🏢 CONDOMÍNIO - Selectbox de Condomínio (FORA do form)
        st.markdown("### 🏢 Localização ")
        condominio_options = {"Nenhum / Não se aplica ": None}
        condominio_options.update(get_condominio_options())
        condominio_select = st.selectbox("Condomínio (Opcional) ", options=list(condominio_options.keys()), index=0, key=f"condominio_select_novo_{st.session_state['form_key']} ")
        if condominio_select and condominio_select != "Nenhum / Não se aplica ":
            atualizar_endereco_por_condominio(condominio_select, st.session_state['form_key'], condominio_options)

        # ✅ NOVO: Campo de Interesse em Produtos (Simples e CRM)
        st.markdown("### 🛒 Interesse em Produtos")
        produtos_interesse = st.multiselect(
            "Quais produtos despertaram interesse?",
            PRODUTOS_INTERESSE,
            help="Selecione um ou mais produtos discutidos",
            key=f"produtos_interesse_{st.session_state['form_key']}"
        )

        endereco_para_salvar = get_valor_inicial("endereco ", " ").strip() if tipo_cadastro == "Cadastro CRM " else " "
        numero_para_salvar = get_valor_inicial("numero ", " ").strip()
        cliente_bloqueado = None

        if endereco_para_salvar and numero_para_salvar:
            cliente_bloqueado = clientes_collection.find_one({"endereco ": endereco_para_salvar, "numero ": numero_para_salvar, "endereco_bloqueado ": True})

        if cliente_bloqueado and not st.session_state["ignorar_bloqueio "]:
            endereco_completo = montar_endereco_completo(endereco_para_salvar, numero_para_salvar, get_valor_inicial("complemento ", " "))
            st.markdown(f'<div style="background-color:#ffe6e6; padding:8px; border-radius:6px; margin-bottom:12px; font-weight:bold; font-size:1em;">🚨 <strong>Endereço bloqueado:</strong> <br> <small>{endereco_completo}</small></div>', unsafe_allow_html=True)
            motivo = cliente_bloqueado.get("observacoes_bloqueio_endereco ", " ").strip()
            if motivo: st.markdown(f"<p style='background-color:#f0f0f0; padding:8px; border-radius:5px; font-size:0.9em;'> <strong>📌 Motivo:</strong> {motivo}</p> ", unsafe_allow_html=True)
            else: st.markdown("<p style='background-color:#fff3cd; padding:8px; border-radius:5px; font-size:0.9em;'> <strong>⚠️ Motivo não informado.</strong> </p> ", unsafe_allow_html=True)
            clientes_com_mesmo_endereco = list(clientes_collection.find({"endereco ": endereco_para_salvar, "numero ": numero_para_salvar}))
            if clientes_com_mesmo_endereco:
                st.markdown(f"<p style='margin-top:12px;'> <strong>👥 Já há {len(clientes_com_mesmo_endereco)} cadastro(s) neste endereço:</strong> </p> ", unsafe_allow_html=True)
                for c in clientes_com_mesmo_endereco:
                    nome = c.get("nome_completo ", "Nome não informado ")
                    celular = c.get("celular ", "— ")
                    cpf_c = c.get("cpf ", " ")
                    tipo = c.get("tipo_cadastro ", "— ")
                    status = c.get("status ", "— ")
                    data_str = " "
                    data_cad = c.get("data_cadastro ")
                    if data_cad:
                        try:
                            if isinstance(data_cad, str): data_cad = datetime.fromisoformat(data_cad)
                            data_str = f" • {data_cad.strftime('%d/%m/%Y %H:%M')} "
                        except: pass
                    cpf_display = f" • CPF: {cpf_c[:3]}***{cpf_c[-2:]} " if cpf_c and len(cpf_c) == 11 else " "
                    badge_tipo = "Simples " if tipo == "simples " else "🟢 Completo "
                    badge_status = "Novo " if status == "novo " else "Em análise " if status == "analise " else "🟢 Convertido " if status == "convertido " else status
                    st.markdown(f"- **{nome}** • `{celular}`{cpf_display}{data_str} <br> <span style='font-size:0.85em; background-color:#e0e0e0; padding:2px 6px; border-radius:4px;'>{badge_tipo}</span>   <span style='font-size:0.85em; background-color:#d0e0ff; padding:2px 6px; border-radius:4px;'>{badge_status}</span> ", unsafe_allow_html=True)
            st.markdown("<p style='margin-top:12px; font-weight:bold;'>Você deseja continuar com o cadastro mesmo assim?</p> ", unsafe_allow_html=True)
            col_conf, col_canc = st.columns(2)
            with col_conf:
                if st.button("✅ Continuar mesmo assim ", key="continuar_bloqueio_novo_fora_form "):
                    st.session_state["ignorar_bloqueio "] = True
                    st.session_state["endereco_bloqueado_confirmado "] = {"endereco ": endereco_para_salvar, "numero ": numero_para_salvar}
                    st.rerun()
            with col_canc:
                if st.button("❌ Cancelar Cadastro ", key="cancelar_bloqueio_novo_fora_form "):
                    st.info("Cadastro cancelado. ")
                    if "dados_temp_bloqueio " in st.session_state: del st.session_state["dados_temp_bloqueio "]
                    if "ignorar_bloqueio " in st.session_state: del st.session_state["ignorar_bloqueio "]
                    if "endereco_bloqueado_confirmado " in st.session_state: del st.session_state["endereco_bloqueado_confirmado "]
                    return
            return

        with st.form(f"novo_cadastro_{st.session_state['form_key']} "):
            if tipo_cadastro == "Cadastro CRM ":
                col1, col2 = st.columns(2)
                with col1: rg = st.text_input("RG* ", max_chars=15, placeholder="12.345.678-9 ", value=get_valor_inicial("rg ", " "), key=f"rg_{st.session_state['form_key']} ")
                with col2: data_nascimento = st.date_input("Data de nascimento* ", value=get_valor_inicial("data_nascimento ", datetime.today()), format="DD/MM/YYYY ", key=f"data_nascimento_{st.session_state['form_key']} ", min_value=datetime(1900, 1, 1))
                email = st.text_input("Email* ", value=get_valor_inicial("email ", " "), key=f"email_{st.session_state['form_key']} ")
                col1, col2 = st.columns([3, 1])
                with col1: endereco = st.text_input("Endereço* ", value=st.session_state.get(f"endereco_{st.session_state['form_key']} ", get_valor_inicial("endereco ", " ")), key=f"endereco_{st.session_state['form_key']} ")
                with col2: numero = st.text_input("Número* ", max_chars=6, value=st.session_state.get(f"numero_{st.session_state['form_key']} ", get_valor_inicial("numero ", " ")), key=f"numero_{st.session_state['form_key']} ")
                col_bloco, col_apto = st.columns(2)
                with col_bloco: bloco = st.text_input("Bloco ", value=" ", key=f"bloco_{st.session_state['form_key']} ")
                with col_apto: apartamento = st.text_input("Apartamento ", value=" ", key=f"apartamento_{st.session_state['form_key']} ")
                col1, col2 = st.columns(2)
                with col1: complemento = st.text_input("Complemento ", value=get_valor_inicial("complemento ", " "), key=f"complemento_{st.session_state['form_key']} ")
                with col2: ponto_referencia = st.text_input("Ponto de referência ", value=get_valor_inicial("ponto_referencia ", " "), key=f"ponto_referencia_{st.session_state['form_key']} ")
                col1, col2 = st.columns(2)
                with col1: bairro = st.text_input("Bairro* ", value=get_valor_inicial("bairro ", " "), key=f"bairro_{st.session_state['form_key']} ")
                with col2: cidade = st.text_input("Cidade* ", value=st.session_state.get(f"cidade_{st.session_state['form_key']} ", get_valor_inicial("cidade ", "Rio de Janeiro ")), key=f"cidade_{st.session_state['form_key']} ")
                col1, col2 = st.columns(2)
                with col1:
                    tipo_moradia = st.selectbox("Tipo de Moradia* ", ["Selecione... ", "Própria ", "Alugada ", "Cedida "], index=0, key=f"tipo_moradia_{st.session_state['form_key']} ")
                with col2:
                    tempo_moradia_valor = st.selectbox("Tempo de Moradia ", list(range(0, 51)), index=0, key=f"tempo_moradia_valor_{st.session_state['form_key']} ")
                    tempo_moradia_unidade = st.selectbox("  ", ["Anos ", "Meses "], index=0, key=f"tempo_moradia_unidade_{st.session_state['form_key']} ")
                plano_atual = get_valor_inicial("plano_escolhido ", " ")
                index_plano = (PLANOS.index(plano_atual) + 1) if plano_atual in PLANOS else 0
                plano_escolhido = st.selectbox("Plano escolhido* ", ["Selecione... "] + PLANOS, index=index_plano, key=f"plano_escolhido_{st.session_state['form_key']} ")
                profissao = st.text_input("Profissão* ", value=get_valor_inicial("profissao ", " "), key=f"profissao_{st.session_state['form_key']} ")
                data_vencimento = st.selectbox("Melhor data de vencimento* ", list(range(1, 32)), index=int(get_valor_inicial("data_vencimento ", 1)) - 1, key=f"data_vencimento_{st.session_state['form_key']} ")
                st.subheader("📷 Foto segurando documento com foto (RG, CNH, etc) - Opcional ")
                foto_documento = st.file_uploader("Envie a foto aqui (JPG ou PNG) - Opcional ", type=["jpg ", "png ", "jpeg "], key=f"foto_documento_{st.session_state['form_key']} ")
                st.subheader("📦 Equipamento em Comodato (opcional) ")
                equip_desc = st.text_input("Descrição do Equipamento ", value=get_valor_inicial("equip_desc ", "Roteador Wi-Fi "), key=f"equip_desc_{st.session_state['form_key']} ")
                modelo_atual = get_valor_inicial("equip_modelo ", " ")
                index_modelo = MODELOS_ROTEADORES.index(modelo_atual) if modelo_atual in MODELOS_ROTEADORES else 0
                equip_modelo = st.selectbox("Marca/Modelo* ", MODELOS_ROTEADORES, index=index_modelo, key=f"equip_modelo_{st.session_state['form_key']} ")
                equip_codigo = st.text_input("Informação Adicional* ", placeholder="Ex: Número de série ", value=get_valor_inicial("equip_codigo ", " "), key=f"equip_codigo_{st.session_state['form_key']} ")
                equip_acessorios = st.text_input("Acessórios ", value=get_valor_inicial("equip_acessorios ", "Fonte de alimentação, cabo Ethernet "), key=f"equip_acessorios_{st.session_state['form_key']} ")
            else:
                rg = email = endereco = numero = bairro = ponto_referencia = " "
                plano_escolhido = "Não informado "
                profissao = " "
                data_vencimento = 1
                data_nascimento = datetime.today()
                foto_documento = None
                equip_desc = " "
                equip_modelo = MODELOS_ROTEADORES[0]
                equip_codigo = " "
                equip_acessorios = " "
                codigo_indicador = " "
                ja_possui_internet = " "
                tipo_moradia = " "
                tempo_moradia_valor = 0
                tempo_moradia_unidade = "Anos "
                bloco = " "
                apartamento = " "

            col1, col2 = st.columns(2)
            with col1:
                if st.session_state["gerando_contrato_principal "]: st.form_submit_button("⏳ Gerando contrato... ", disabled=True)
                elif st.session_state["contrato_pronto_principal "]:
                    if st.form_submit_button("📥 Baixar Contrato Gerado ", type="secondary "): pass
                else:
                    if st.form_submit_button("✍️ Gerar Contrato ", type="secondary "):
                        cpf_valido = limpar_cpf(cpf)
                        if not cpf_valido: st.error("❌ CPF inválido! ")
                        elif not all([nome_completo, cpf_valido, endereco, celular_principal, plano_escolhido != "Selecione... "]): st.error("❌ Preencha todos os campos obrigatórios para gerar contrato! ")
                        else:
                            st.session_state["dados_temp_contrato_principal "] = {"nome_contratante ": nome_completo, "cpf_cnpj_contratante ": cpf_valido, "endereco_contratante ": endereco, "numero_contratante ": numero, "complemento ": complemento, "cidade ": cidade, "bairro ": bairro, "telefone_contratante ": celular_principal, "plano_contratado ": plano_escolhido, "modalidade ": "Pós Pago ", "condominio_nome ": st.session_state.get(f"condominio_nome_{st.session_state['form_key']} ", " "), "bloco ": bloco if bloco else " ", "apartamento ": apartamento if apartamento else " "}
                            st.session_state["gerando_contrato_principal "] = True
                            st.session_state["nome_arquivo_contrato_principal "] = f"Contrato_{nome_completo.replace(' ', '_')}.pdf "
                            st.rerun()
            with col2:
                if st.session_state["gerando_comodato_principal "]: st.form_submit_button("⏳ Gerando termo... ", disabled=True)
                elif st.session_state["comodato_pronto_principal "]:
                    if st.form_submit_button("📥 Baixar Termo de Comodato ", type="secondary "): pass
                else:
                    if st.form_submit_button("📄 Gerar Termo de Comodato ", type="secondary "):
                        cpf_valido = limpar_cpf(cpf)
                        if not cpf_valido: st.error("❌ CPF inválido! ")
                        elif not all([nome_completo, cpf_valido, endereco, celular_principal, equip_modelo, equip_codigo]): st.error("❌ Preencha todos os campos obrigatórios do comodato! ")
                        else:
                            st.session_state["dados_temp_comodato_principal "] = {"nome_contratante ": nome_completo, "cpf_cnpj_contratante ": cpf_valido, "endereco_contratante ": endereco, "numero_contratante ": numero, "complemento ": complemento, "cidade ": cidade, "bairro ": bairro, "telefone_contratante ": celular_principal, "equipamento_descricao ": equip_desc, "equipamento_modelo ": equip_modelo, "equipamento_codigo ": equip_codigo, "equipamento_acessorios ": equip_acessorios, "condominio_nome ": st.session_state.get(f"condominio_nome_{st.session_state['form_key']} ", " "), "bloco ": bloco if bloco else " ", "apartamento ": apartamento if apartamento else " "}
                            st.session_state["gerando_comodato_principal "] = True
                            st.session_state["nome_arquivo_comodato_principal "] = f"Termo_Comodato_{nome_completo.replace(' ', '_')}.pdf "
                            st.rerun()

            if st.form_submit_button("📝 Gerar Mensagem de Confirmação ", type="secondary "):
                cpf_limpo = limpar_cpf(cpf) or "Não informado "
                tempo_moradia_texto = f"{tempo_moradia_valor} {tempo_moradia_unidade.lower()} " if tempo_moradia_valor > 0 else "Não informado "
                campos = {"Nome completo ": nome_completo, "Celular Principal ": celular_principal, "Contato 1 ": f"{celular_contato_1} ({descricao_contato_1}) " if celular_contato_1 and descricao_contato_1 else celular_contato_1 or "— ", "Contato 2 ": f"{celular_contato_2} ({descricao_contato_2}) " if celular_contato_2 and descricao_contato_2 else celular_contato_2 or "— ", "Email ": email, "Data de nascimento ": data_nascimento.strftime("%d/%m/%Y ") if data_nascimento else "Não informado ", "CPF ": cpf_limpo, "RG ": rg, "Endereço ": endereco, "Número ": numero, "Complemento ": complemento or "Não informado ", "Cidade ": cidade or "Não informada ", "Bairro ": bairro, "Ponto de referência ": ponto_referencia or "Não informado ", "Tipo de Moradia ": tipo_moradia, "Tempo de Moradia ": tempo_moradia_texto, "Plano escolhido ": plano_escolhido, "Profissão ": profissao, "Melhor data de vencimento ": str(data_vencimento)}
                mensagem = "Os dados abaixo estão corretos?\n "
                for chave, valor in campos.items(): mensagem += f"{chave}: {valor}\n "
                mensagem += "\nAguardamos sua resposta para prosseguirmos. Qualquer dúvida, estou à disposição! "
                st.session_state["mensagem_confirmacao_novo "] = mensagem
                st.success("✅ Mensagem gerada! ")

            enviado = st.form_submit_button("💾 Salvar Cadastro ", type="primary ")
            if enviado:
                if not nome_completo or not celular_principal: st.error("⚠️ Nome e Celular Principal são obrigatórios. ")
                elif tipo_cadastro == "Cadastro CRM " and plano_escolhido == "Selecione... ": st.error("⚠️ Selecione um plano válido. ")
                elif tipo_cadastro == "Cadastro CRM " and seguiu_ativacao == "Não " and (not motivo_recusa or motivo_recusa == "Selecione... "): st.error("⚠️ Quando 'Seguiu para Ativação' for 'Não', é obrigatório selecionar o motivo da recusa. ")
                else:
                    endereco_salvo = st.session_state.get(f"endereco_{st.session_state['form_key']} ", " ").strip()
                    numero_salvo = st.session_state.get(f"numero_{st.session_state['form_key']} ", " ").strip()
                    if endereco_salvo and numero_salvo:
                        cliente_bloqueado = clientes_collection.find_one({"endereco ": endereco_salvo, "numero ": numero_salvo, "endereco_bloqueado ": True})
                        conf = st.session_state.get("endereco_bloqueado_confirmado ", {})
                        confirmado = (conf.get("endereco ") == endereco_salvo and conf.get("numero ") == numero_salvo)
                        if cliente_bloqueado and not st.session_state.get("ignorar_bloqueio ", False) and not confirmado:
                            endereco_completo = montar_endereco_completo(endereco_salvo, numero_salvo, st.session_state.get(f"complemento_{st.session_state['form_key']} ", " "))
                            motivo = cliente_bloqueado.get("observacoes_bloqueio_endereco ", "Não informado ")
                            st.error("❌ Este endereço está bloqueado! Por favor, clique em 'Continuar mesmo assim' para prosseguir. ")
                            st.info(f"📌 {endereco_completo}\nMotivo: {motivo} ")
                            return

                    if seguiu_ativacao == "Sim ": retorno_agendado = " "
                    codigo_indicacao = None
                    if seguiu_ativacao == "Sim ": codigo_indicacao = gerar_codigo_indicacao()
                    foto_base64 = " "
                    if foto_documento:
                        foto_bytes = foto_documento.read()
                        foto_base64 = base64.b64encode(foto_bytes).decode('utf-8')
                    tipo = "simples " if tipo_cadastro == "Cadastro Simples " else "completo "
                    celular_normalizado = normalize_phone(celular_principal)
                    nome_atendente = st.session_state.get("nome_usuario ", "Desconhecido ")
                    cadastrado_por = nome_atendente
                    cpf_limpo = limpar_cpf(cpf)

                    cliente_data = {
                        "nome_completo ": nome_completo, "celular ": celular_normalizado,
                        "celular_contato_1 ": normalize_phone(celular_contato_1) if celular_contato_1 and celular_contato_1.strip() else None,
                        "celular_contato_2 ": normalize_phone(celular_contato_2) if celular_contato_2 and celular_contato_2.strip() else None,
                        "descricao_contato_1 ": descricao_contato_1.strip() if descricao_contato_1 and descricao_contato_1.strip() else None,
                        "descricao_contato_2 ": descricao_contato_2.strip() if descricao_contato_2 and descricao_contato_2.strip() else None,
                        "email ": email if tipo_cadastro == "Cadastro CRM " else None,
                        "data_nascimento ": data_nascimento.isoformat() if data_nascimento else None, "cpf ": cpf_limpo,
                        "rg ": rg if tipo_cadastro == "Cadastro CRM " and rg else None,
                        "endereco ": endereco_salvo if endereco_salvo else None, "numero ": numero_salvo if numero_salvo else None,
                        "complemento ": st.session_state.get(f"complemento_{st.session_state['form_key']} ", " ") or None,
                        "cidade ": st.session_state.get(f"cidade_{st.session_state['form_key']} ", " ") or None,
                        "bairro ": st.session_state.get(f"bairro_{st.session_state['form_key']} ", " ") or None,
                        "ponto_referencia ": st.session_state.get(f"ponto_referencia_{st.session_state['form_key']} ", " ") or None,
                        "tipo_moradia ": tipo_moradia if tipo_moradia != "Selecione... " else None,
                        "tempo_moradia ": {"valor ": tempo_moradia_valor, "unidade ": tempo_moradia_unidade} if tempo_moradia_valor > 0 else None,
                        "plano_escolhido ": plano_escolhido if plano_escolhido != "Selecione... " else None,
                        "profissao ": profissao if tipo_cadastro == "Cadastro CRM " else None,
                        "data_vencimento ": data_vencimento if tipo_cadastro == "Cadastro CRM " else 1,
                        "foto_documento_base64 ": foto_base64, "data_cadastro ": datetime.now(), "tipo_cadastro ": tipo, "status ": "novo ",
                        "atendente ": nome_atendente, "cadastrado_por ": cadastrado_por,
                        "origem ": origem if origem != "Selecione... " else " ", "restritivo ": restritivo if restritivo != "Selecione... " else " ",
                        "restritivo_qtd_registros ": qtd_registros if restritivo == "Sim " else None,
                        "restritivo_ano_recente ": ano_recente if restritivo == "Sim " else None,
                        "restritivo_servico_internet ": servico_internet if restritivo == "Sim " else None,
                        "seguiu_ativacao ": seguiu_ativacao if seguiu_ativacao != "Selecione... " else " ",
                        "motivo_recusa_ativacao ": motivo_recusa if motivo_recusa and motivo_recusa != "Selecione... " else None,
                        "detalhes_recusa_ativacao ": detalhes_recusa.strip() if detalhes_recusa and detalhes_recusa.strip() else None,
                        "ja_possui_internet ": ja_possui_internet if ja_possui_internet != "Selecione... " else " ",
                        "retorno_agendado ": retorno_agendado,
                        "observacoes ": observacoes if observacoes else " ",
                        "observacoes_followup ": observacoes_followup_simples.strip(),
                        # ✅ NOVO: Salvar produtos de interesse
                        "produtos_interesse ": produtos_interesse,
                        "codigo_indicacao ": codigo_indicacao, "codigo_indicador ": safe_strip_codigo_indicador(codigo_indicador),
                        "endereco_bloqueado ": False, "observacoes_bloqueio_endereco ": None,
                        "condominio_id ": st.session_state.get(f"condominio_id_{st.session_state['form_key']} "),
                        "condominio_nome ": st.session_state.get(f"condominio_nome_{st.session_state['form_key']} "),
                        "bloco ": bloco if bloco else None, "apartamento ": apartamento if apartamento else None,
                    }

                    try:
                        result = clientes_collection.insert_one(cliente_data)
                        st.success(f"✅ {tipo_cadastro} salvo com sucesso! ")
                        st.balloons()
                        st.session_state["mostrar_botao_novo "] = True
                        if "ignorar_bloqueio " in st.session_state: del st.session_state["ignorar_bloqueio "]
                        if "endereco_bloqueado_confirmado " in st.session_state: del st.session_state["endereco_bloqueado_confirmado "]
                        if "dados_temp_bloqueio " in st.session_state: del st.session_state["dados_temp_bloqueio "]
                        if codigo_indicacao:
                            st.markdown(f"### 🎁 Código de Indicação: `{codigo_indicacao}` ")
                            copiar_para_area_de_transferencia(codigo_indicacao, f"copy_{result.inserted_id} ")
                        if tipo_cadastro == "Cadastro CRM ":
                            link_whatsapp = gerar_link_whatsapp_solicitacao(nome_completo, celular_normalizado, cpf_limpo)
                            st.markdown(f'<a href="{link_whatsapp}" target="_blank" style="display: inline-block; padding: 0.5em 1em; background-color: #25D366;color: white; text-decoration: none; border-radius: 5px; font-weight: bold;">📲 Solicitar Análise</a>', unsafe_allow_html=True)
                        if "mensagem_confirmacao_novo " in st.session_state: del st.session_state["mensagem_confirmacao_novo "]
                    except DuplicateKeyError:
                        st.error("❌ Celular já cadastrado no sistema! ")
                        st.info("💡 Use a busca global para encontrar e atualizar o cadastro existente. ")
                    except Exception as e: st.error(f"❌ Erro inesperado ao salvar: {str(e)} ")

    if "mensagem_confirmacao_novo " in st.session_state:
        st.subheader("📧 Mensagem de Confirmação Gerada: ")
        st.code(st.session_state["mensagem_confirmacao_novo "], language="text ")
        if st.button("🗑️ Limpar Mensagem ", key="limpar_msg_novo "):
            del st.session_state["mensagem_confirmacao_novo "]
            st.rerun()

    elif acao == "Completar Cadastro Existente ":
        st.info("🔍 Busque um cadastro simples para completar os dados. ")
        busca = st.text_input("Digite o nome ou telefone do cliente ", placeholder="Ex: Ana Silva ou (11) 98765-4321 ", value=st.session_state["busca_pre_preenchida "], key=f"busca_completar_{st.session_state['form_key']} ")
        if st.session_state["busca_pre_preenchida "]: st.session_state["busca_pre_preenchida "] = " "
        if busca:
            busca_normalizada = normalize_phone(busca)
            query_conditions = [{"nome_completo ": {"$regex ": busca, "$options ": "i "}}]
            if busca_normalizada:
                query_conditions.append({"celular ": busca_normalizada})
                query_conditions.append({"celular_contato_1 ": busca_normalizada})
                query_conditions.append({"celular_contato_2 ": busca_normalizada})
                query_conditions.append({"descricao_contato_1 ": {"$regex ": busca, "$options ": "i "}})
                query_conditions.append({"descricao_contato_2 ": {"$regex ": busca, "$options ": "i "}})
            cliente = clientes_collection.find_one({"$or ": query_conditions})
            if cliente:
                st.success(f"✅ Encontrado: {cliente['nome_completo']} - {cliente['celular']} ")
                if cliente.get("tipo_cadastro ") == "simples ":
                    if st.button("✏️ Abrir Formulário para Completar ", key="abrir_completar_radio "):
                        st.session_state["cliente_selecionado "] = copy.deepcopy(dict(cliente))
                        st.session_state["mostrar_completar "] = True
                        st.rerun()
                else: st.info("ℹ️ Este cadastro já está completo. ")
            else: st.warning("⚠️ Nenhum cliente encontrado com esse nome ou telefone. ")

# Gerar PDFs
for tipo in ["contrato ", "comodato "]:
    for contexto in ["principal ", "visualizar ", "completar "]:
        estado_gerando = f"gerando_{tipo}_{contexto} "
        dados_temp = f"dados_temp_{tipo}_{contexto} "
        nome_arquivo = f"nome_arquivo_{tipo}_{contexto} "
        if st.session_state.get(estado_gerando) and dados_temp in st.session_state:
            with st.spinner(f"📝 Gerando seu {'contrato' if tipo == 'contrato' else 'termo de comodato'}... "):
                func_gerar = gerar_pdf_contrato if tipo == "contrato " else gerar_pdf_comodato
                pdf_bytes = func_gerar(st.session_state[dados_temp])
                if pdf_bytes:
                    st.session_state[f"{tipo}_pdf_bytes "] = pdf_bytes
                    st.session_state[f"{tipo}_nome "] = st.session_state[nome_arquivo]
                    st.session_state[f"{tipo}_pronto_{contexto} "] = True
                    del st.session_state[estado_gerando]
                    del st.session_state[dados_temp]
                    del st.session_state[nome_arquivo]
                    st.rerun()
                else:
                    st.error(f"❌ Falha ao gerar o {'contrato' if tipo == 'contrato' else 'termo de comodato'}. ")
                    if estado_gerando in st.session_state: del st.session_state[estado_gerando]
                    if dados_temp in st.session_state: del st.session_state[dados_temp]
                    if nome_arquivo in st.session_state: del st.session_state[nome_arquivo]

if "contrato_pdf_bytes " in st.session_state and "contrato_nome " in st.session_state:
    st.download_button(label="📥 Baixar Contrato Gerado ", data=st.session_state["contrato_pdf_bytes "], file_name=st.session_state["contrato_nome "], mime="application/pdf ", key="download_contrato_global_unica_key ")
    if st.button("🗑️ Limpar Contrato ", key="limpar_contrato_global "):
        del st.session_state["contrato_pdf_bytes "]
        del st.session_state["contrato_nome "]
        for key in ["contrato_pronto_principal ", "contrato_pronto_visualizar ", "contrato_pronto_completar "]:
            if key in st.session_state: del st.session_state[key]

if "comodato_pdf_bytes " in st.session_state and "comodato_nome " in st.session_state:
    st.download_button(label="📥 Baixar Termo de Comodato ", data=st.session_state["comodato_pdf_bytes "], file_name=st.session_state["comodato_nome "], mime="application/pdf ", key="download_comodato_global_unica_key ")
    if st.button("🗑️ Limpar Termo ", key="limpar_comodato_global "):
        del st.session_state["comodato_pdf_bytes "]
        del st.session_state["comodato_nome "]
        for key in ["comodato_pronto_principal ", "comodato_pronto_visualizar ", "comodato_pronto_completar "]:
            if key in st.session_state: del st.session_state[key]

if st.session_state.get("mostrar_botao_novo ", False):
    if st.button("🔄 Novo Cadastro ", key="btn_novo_cadastro_global "):
        keys_to_clear = ["campo_cpf ", "campo_celular_principal ", "campo_celular_contato_1 ", "campo_celular_contato_2 ", "descricao_contato_1 ", "descricao_contato_2 ", "nome_completo ", "email ", "data_nascimento ", "rg ", "endereco ", "numero ", "bairro ", "ponto_referencia ", "plano_escolhido ", "profissao ", "data_vencimento ", "foto_documento ", "followup_opcao ", "mes ", "ano ", "retorno_agendado ", "contrato_pdf_bytes ", "contrato_nome ", "comodato_pdf_bytes ", "comodato_nome ", "mostrar_completar ", "mostrar_visualizar ", "cliente_selecionado ", "mensagem_confirmacao_novo ", "mensagem_confirmacao_completar ", "mensagem_confirmacao_visualizar ", "gerando_contrato_principal ", "contrato_pronto_principal ", "gerando_comodato_principal ", "comodato_pronto_principal ", "gerando_contrato_visualizar ", "contrato_pronto_visualizar ", "gerando_comodato_visualizar ", "comodato_pronto_visualizar ", "gerando_contrato_completar ", "contrato_pronto_completar ", "gerando_comodato_completar ", "comodato_pronto_completar ", "dados_temp_contrato_principal ", "nome_arquivo_contrato_principal ", "dados_temp_comodato_principal ", "nome_arquivo_comodato_principal ", "dados_temp_contrato_visualizar ", "nome_arquivo_contrato_visualizar ", "dados_temp_comodato_visualizar ", "nome_arquivo_comodato_visualizar ", "dados_temp_contrato_completar ", "nome_arquivo_contrato_completar ", "dados_temp_comodato_completar ", "nome_arquivo_comodato_completar ", "dados_temp_bloqueio ", "ignorar_bloqueio ", "endereco_bloqueado_confirmado "]
        suffixes = [" ", "_completar ", "_dialog ", "_editar ", "_visualizar ", "_principal "]
        for base_key in keys_to_clear:
            for suffix in suffixes:
                key = f"{base_key}{suffix} "
                if key in st.session_state: del st.session_state[key]
        st.session_state["form_key "] += 1
        st.session_state["mostrar_botao_novo "] = False
        st.session_state["acao_selecionada "] = "Novo Cadastro "
        st.session_state["busca_pre_preenchida "] = " "
        st.rerun()
