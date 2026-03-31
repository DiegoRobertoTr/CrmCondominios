import streamlit as st
import hashlib
import random
import string
from datetime import datetime

# Função de normalização — mantém consistência e evita duplicatas
def normalizar_nome_loja(nome: str) -> str:
    """Remove espaços extras, padroniza caixa (title case), garante string."""
    if not isinstance(nome, str):
        return ""
    return nome.strip().title()

def gerar_codigo_embaixador(eh_tecnico=False):
    """Gera código no formato:
    - EMB + 6 números + 3 letras (padrão)
    - TECEMB + 6 números + 3 letras (se eh_tecnico=True)
    """
    prefixo = "TECEMB" if eh_tecnico else "EMB"
    numeros = ''.join(random.choices(string.digits, k=6))
    letras = ''.join(random.choices(string.ascii_uppercase, k=3))
    return f"{prefixo}{numeros}{letras}"

def hash_senha(senha):
    return hashlib.sha256(senha.encode()).hexdigest()

def determinar_status_embaixador(cliente):
    """Converte campos do cliente em status legível para o painel de bônus."""
    if cliente.get("ativo") is True:
        return "Ativado"
    elif cliente.get("retorno_agendado"):
        return "Agendamento"
    elif cliente.get("seguiu_ativacao") == "Sim":
        return "Seguiu para ativação"
    else:
        return "Indicado"

# 🔁 Componente compatível com Streamlit Cloud: autocomplete-like com sugestões + digitação livre
def st_autocomplete_like(label: str, suggestions: list[str], key: str, placeholder: str = "", value: str = "") -> str:
    """
    Simula autocomplete com sugestões clicáveis + digitação livre.
    Retorna o texto digitado (mesmo que não esteja nas sugestões).
    """
    # Campo de entrada principal
    user_input = st.text_input(label, value=value, placeholder=placeholder, key=f"{key}_input")

    # Filtra sugestões com base no que foi digitado (case-insensitive)
    if user_input.strip():
        filtered = [
            s for s in suggestions
            if user_input.lower() in s.lower()
        ]
    else:
        filtered = suggestions[:5]  # limite visual para evitar poluição

    # Exibe sugestões como botões compactos
    if filtered:
        st.caption("📌 Sugestões:")
        # Exibe até 4 sugestões por linha
        cols = st.columns(min(len(filtered), 4))
        for idx, sug in enumerate(filtered):
            col = cols[idx % 4]
            if col.button(f"« {sug}", key=f"{key}_sug_{idx}", use_container_width=True):
                # Define o valor via session_state e recarrega
                st.session_state[f"{key}_input"] = sug
                st.rerun()

    return user_input.strip()

def render_admin_embaixadores(usuarios_collection, clientes_collection):
    st.header("👑 Gerenciar Embaixadores da Marca")
    st.markdown("Cadastre e gerencie embaixadores com acesso exclusivo ao painel de indicações.")

    # --- Cadastro de novo embaixador ---
    with st.expander("➕ Cadastrar Novo Embaixador", expanded=False):
        col1, col2 = st.columns(2)
        with col1:
            nome_exibicao = st.text_input("Nome de Exibição", placeholder="Ex: Diego R.", key="emb_nome")
            login = st.text_input("Login (usuário)", placeholder="Ex: diego_emb", key="emb_login")
            telefone_embaixador = st.text_input("Telefone do Embaixador", placeholder="(00) 90000-0000", key="emb_telefone")
            email_embaixador = st.text_input("Email do Embaixador", placeholder="exemplo@dominio.com", key="emb_email")
        with col2:
            senha = st.text_input("Senha", type="password", key="emb_senha")
            senha_confirma = st.text_input("Confirmar Senha", type="password", key="emb_senha_confirma")
            tipo_chave_pix = st.selectbox(
                "Tipo de Chave Pix",
                ["Selecione...", "CPF", "E-mail", "Celular", "Chave Aleatória"],
                index=0,
                key="emb_tipo_chave_pix"
            )
            chave_pix = st.text_input("Chave Pix", placeholder="Ex: 123.456.789-00", key="emb_chave_pix")

        # --- Checkbox: técnico ou não ---
        eh_tecnico = st.checkbox("🔧 Esse embaixador é um técnico da empresa?", key="emb_eh_tecnico")

        # --- Dados da Loja Parceira (COM AUTOCOMPLETE COMPATÍVEL) ---
        st.divider()
        st.subheader("🏢 Dados da Loja Parceira")

        # Busca e normaliza lojas já cadastradas (únicas e válidas)
        lojas_db = usuarios_collection.distinct("loja_parceira", {
            "perfil": "embaixador",
            "loja_parceira": {"$type": "string", "$ne": ""}
        })
        lojas_normalizadas = sorted({
            normalizar_nome_loja(loja) for loja in lojas_db if normalizar_nome_loja(loja)
        })

        loja_digitada = st_autocomplete_like(
            label="Nome da Loja",
            suggestions=lojas_normalizadas,
            key="autocomplete_loja",
            placeholder="Ex: PK Barber, Tech Store...",
        )
        loja_parceira = normalizar_nome_loja(loja_digitada)

        # Feedback suave para nova loja
        if loja_parceira and loja_parceira not in lojas_normalizadas:
            st.info(f"🆕 Nova loja: **{loja_parceira}**")

        endereco_loja = st.text_area("Endereço da Loja", placeholder="Ex: Rua Principal, 123 - Centro - Cidade - Estado", key="emb_endereco_loja")

        # --- Responsável Pelo Cadastro da Loja ---
        st.divider()
        st.subheader("👥 Responsável Pelo Cadastro da Loja")
        responsavel_cadastro = st.selectbox(
            "Responsável Pelo Cadastro da Loja",
            options=["Selecione...", "Diego Roberto", "Sabrina"],
            index=0,
            key="emb_responsavel"
        )

        if st.button("✅ Cadastrar Embaixador"):
            campos_obrigatorios = [
                nome_exibicao, login, senha, telefone_embaixador,
                email_embaixador, loja_parceira, endereco_loja,
                tipo_chave_pix, chave_pix, responsavel_cadastro
            ]
            if not all(campo.strip() if isinstance(campo, str) else campo for campo in campos_obrigatorios):
                st.error("⚠️ Todos os campos são obrigatórios.")
            elif responsavel_cadastro == "Selecione...":
                st.error("⚠️ Selecione um responsável válido pelo cadastro da loja.")
            elif senha != senha_confirma:
                st.error("❌ As senhas não coincidem.")
            elif len(senha) < 6:
                st.error("⚠️ A senha deve ter pelo menos 6 caracteres.")
            elif tipo_chave_pix == "Selecione...":
                st.error("⚠️ Selecione um tipo de chave Pix válido.")
            else:
                if usuarios_collection.find_one({"login": login}):
                    st.error("❌ Este login já está em uso.")
                else:
                    eh_tecnico_valor = st.session_state.get("emb_eh_tecnico", False)
                    codigo = gerar_codigo_embaixador(eh_tecnico=eh_tecnico_valor)
                    usuario_data = {
                        "login": login.strip(),
                        "senha_hash": hash_senha(senha),
                        "perfil": "embaixador",
                        "nome_exibicao": nome_exibicao.strip(),
                        "codigo_embaixador": codigo,
                        "eh_tecnico": eh_tecnico_valor,
                        "data_cadastro": datetime.now(),
                        "telefone_embaixador": telefone_embaixador.strip(),
                        "email_embaixador": email_embaixador.strip(),
                        "loja_parceira": loja_parceira,  # já normalizado
                        "endereco_loja": endereco_loja.strip(),
                        "tipo_chave_pix": tipo_chave_pix,
                        "chave_pix": chave_pix.strip(),
                        "responsavel_cadastro": responsavel_cadastro.strip()
                    }
                    try:
                        usuarios_collection.insert_one(usuario_data)
                        st.success(f"✅ Embaixador **{nome_exibicao}** cadastrado com sucesso!")
                        st.code(f"Código de indicação: `{codigo}`", language="text")
                        st.rerun()
                    except Exception as e:
                        st.error(f"❌ Erro ao salvar: {e}")

    # --- Listagem de embaixadores ---
    st.divider()
    st.subheader("📋 Lista de Embaixadores Cadastrados")
    embaixadores = list(usuarios_collection.find({"perfil": "embaixador"}).sort("data_cadastro", -1))

    if embaixadores:
        for emb in embaixadores:
            with st.container(border=True):
                col1, col2, col3 = st.columns([2, 1.5, 1])
                with col1:
                    st.write(f"**{emb.get('nome_exibicao', '—')}**")
                    st.caption(f"Login: `{emb['login']}`")
                    st.caption(f"Telefone: {emb.get('telefone_embaixador', 'N/A')}")
                    st.caption(f"Email: {emb.get('email_embaixador', 'N/A')}")
                    st.caption(f"Loja: {emb.get('loja_parceira', 'N/A')}")
                    st.caption(f"Chave Pix ({emb.get('tipo_chave_pix', 'N/A')}): {emb.get('chave_pix', 'N/A')}")
                    st.caption(f"Responsável: {emb.get('responsavel_cadastro', '—')}")
                    if emb.get("eh_tecnico", False):
                        st.caption("🔧 Técnico da empresa")
                with col2:
                    codigo = emb.get("codigo_embaixador", "EMB??????")
                    st.code(codigo, language="text")
                with col3:
                    if st.button("✏️ Editar", key=f"edit_{emb['_id']}"):
                        st.session_state["editando_embaixador"] = emb
                        st.rerun()
                    if st.button("🗑️ Excluir", key=f"delete_{emb['_id']}"):
                        st.session_state[f"confirm_delete_{emb['_id']}"] = True

                # Confirmação de exclusão
                if st.session_state.get(f"confirm_delete_{emb['_id']}", False):
                    st.warning("⚠️ Confirme a exclusão deste embaixador.")
                    if st.checkbox("Sim, tenho certeza", key=f"confirm_check_{emb['_id']}"):
                        if st.button("✅ Confirmar Exclusão", key=f"confirm_btn_{emb['_id']}"):
                            try:
                                usuarios_collection.delete_one({"_id": emb["_id"]})
                                st.success(f"✅ Embaixador {emb['nome_exibicao']} excluído!")
                                del st.session_state[f"confirm_delete_{emb['_id']}"]
                                st.rerun()
                            except Exception as e:
                                st.error(f"❌ Erro ao excluir: {e}")
    else:
        st.info("Nenhum embaixador cadastrado ainda.")

    # --- Edição de embaixador ---
    if "editando_embaixador" in st.session_state:
        emb_edit = st.session_state["editando_embaixador"]
        st.divider()
        st.subheader(f"✏️ Editar Embaixador: {emb_edit['nome_exibicao']}")

        col1, col2 = st.columns(2)
        with col1:
            nome_exibicao_edit = st.text_input("Nome de Exibição", value=emb_edit.get("nome_exibicao", ""), key="emb_edit_nome")
            login_edit = st.text_input("Login (usuário)", value=emb_edit.get("login", ""), key="emb_edit_login")
            telefone_embaixador_edit = st.text_input("Telefone do Embaixador", value=emb_edit.get("telefone_embaixador", ""), key="emb_edit_telefone")
            email_embaixador_edit = st.text_input("Email do Embaixador", value=emb_edit.get("email_embaixador", ""), key="emb_edit_email")
        with col2:
            senha_edit = st.text_input("Nova Senha (deixe em branco para manter)", type="password", key="emb_edit_senha")
            senha_confirma_edit = st.text_input("Confirmar Nova Senha", type="password", key="emb_edit_senha_confirma")
            tipo_chave_pix_edit = st.selectbox(
                "Tipo de Chave Pix",
                ["Selecione...", "CPF", "E-mail", "Celular", "Chave Aleatória"],
                index=["Selecione...", "CPF", "E-mail", "Celular", "Chave Aleatória"].index(emb_edit.get("tipo_chave_pix", "Selecione...")),
                key="emb_edit_tipo_chave_pix"
            )
            chave_pix_edit = st.text_input("Chave Pix", value=emb_edit.get("chave_pix", ""), key="emb_edit_chave_pix")

        # Checkbox de técnico na edição
        eh_tecnico_edit = st.checkbox(
            "🔧 Esse embaixador é um técnico da empresa?",
            value=emb_edit.get("eh_tecnico", False),
            key="emb_edit_eh_tecnico"
        )

        st.divider()
        st.subheader("🏢 Dados da Loja Parceira")

        # Autocomplete para edição (com valor inicial preenchido)
        lojas_db_edit = usuarios_collection.distinct("loja_parceira", {
            "perfil": "embaixador",
            "loja_parceira": {"$type": "string", "$ne": ""}
        })
        lojas_normalizadas_edit = sorted({
            normalizar_nome_loja(loja) for loja in lojas_db_edit if normalizar_nome_loja(loja)
        })

        loja_digitada_edit = st_autocomplete_like(
            label="Nome da Loja",
            suggestions=lojas_normalizadas_edit,
            key="autocomplete_loja_edit",
            placeholder="Ex: PK Barber",
            value=normalizar_nome_loja(emb_edit.get("loja_parceira", ""))  # valor inicial
        )
        loja_parceira_edit = normalizar_nome_loja(loja_digitada_edit)

        endereco_loja_edit = st.text_area("Endereço da Loja", value=emb_edit.get("endereco_loja", ""), key="emb_edit_endereco_loja")

        st.divider()
        st.subheader("👥 Responsável Pelo Cadastro da Loja")
        responsavel_cadastro_edit = st.selectbox(
            "Responsável Pelo Cadastro da Loja",
            options=["Selecione...", "Diego Roberto", "Sabrina"],
            index=["Selecione...", "Diego Roberto", "Sabrina"].index(
                emb_edit.get("responsavel_cadastro", "Selecione...")
            ),
            key="emb_edit_responsavel"
        )

        if st.button("💾 Salvar Alterações", key="salvar_edicao"):
            if not all([
                nome_exibicao_edit, login_edit, telefone_embaixador_edit, email_embaixador_edit,
                loja_parceira_edit, endereco_loja_edit, tipo_chave_pix_edit, chave_pix_edit
            ]):
                st.error("⚠️ Todos os campos, exceto senha, são obrigatórios.")
            elif responsavel_cadastro_edit == "Selecione...":
                st.error("⚠️ Selecione um responsável válido pelo cadastro da loja.")
            elif tipo_chave_pix_edit == "Selecione...":
                st.error("⚠️ Selecione um tipo de chave Pix válido.")
            else:
                update_data = {
                    "nome_exibicao": nome_exibicao_edit.strip(),
                    "login": login_edit.strip(),
                    "telefone_embaixador": telefone_embaixador_edit.strip(),
                    "email_embaixador": email_embaixador_edit.strip(),
                    "loja_parceira": loja_parceira_edit,  # já normalizado
                    "endereco_loja": endereco_loja_edit.strip(),
                    "tipo_chave_pix": tipo_chave_pix_edit,
                    "chave_pix": chave_pix_edit.strip(),
                    "responsavel_cadastro": responsavel_cadastro_edit.strip(),
                    "eh_tecnico": eh_tecnico_edit,
                }

                # Atualiza senha se fornecida
                if senha_edit:
                    if senha_edit != senha_confirma_edit:
                        st.error("❌ As senhas não coincidem.")
                    elif len(senha_edit) < 6:
                        st.error("⚠️ A senha deve ter pelo menos 6 caracteres.")
                    else:
                        update_data["senha_hash"] = hash_senha(senha_edit)

                try:
                    usuarios_collection.update_one({"_id": emb_edit["_id"]}, {"$set": update_data})
                    st.success("✅ Embaixador atualizado com sucesso!")
                    del st.session_state["editando_embaixador"]
                    st.rerun()
                except Exception as e:
                    st.error(f"❌ Erro ao salvar: {e}")

        if st.button("❌ Cancelar Edição", key="cancelar_edicao"):
            del st.session_state["editando_embaixador"]
            st.rerun()

    # --- Controle de Bônus ---
    st.divider()
    st.subheader("💰 Controle de Bônus")

    pipeline_b = [
        {"$match": {"indicado_por.tipo": "embaixador"}},
        {"$lookup": {
            "from": "usuarios",
            "localField": "indicado_por.codigo",
            "foreignField": "codigo_embaixador",
            "as": "embaixador"
        }},
        {"$unwind": "$embaixador"},
        {"$sort": {"data_indicacao": -1}}
    ]
    todas_indicacoes = list(clientes_collection.aggregate(pipeline_b))

    if not todas_indicacoes:
        st.info("Nenhuma indicação de embaixador encontrada.")
    else:
        for ind in todas_indicacoes:
            nome_cliente = ind['nome_completo']
            nome_emb = ind['embaixador']['nome_exibicao']
            bonus_enviado = ind.get("bonus_enviado", False)
            bonus_confirmado = ind.get("bonus_confirmado", False)
            
            status_bonus = "✅ Confirmado" if bonus_confirmado else "⏳ Enviado" if bonus_enviado else "❌ Pendente"
            status_cliente = determinar_status_embaixador(ind)
            
            with st.expander(f"{nome_cliente} → {nome_emb} ({status_bonus})"):
                st.write(f"**Status do cliente:** `{status_cliente}`")
                st.write(f"**Data da indicação:** {ind.get('data_indicacao', '—')[:16]}")
                
                if not bonus_enviado:
                    if st.button("📤 Marcar Bônus como Enviado", key=f"env_{ind['_id']}"):
                        clientes_collection.update_one(
                            {"_id": ind["_id"]},
                            {"$set": {
                                "bonus_enviado": True,
                                "data_bonus_enviado": datetime.now()
                            }}
                        )
                        st.success("✅ Bônus marcado como enviado!")
                        st.rerun()
                else:
                    st.success("📤 Bônus já enviado.")
                    if not bonus_confirmado:
                        st.info("⏳ Aguardando confirmação do embaixador.")
