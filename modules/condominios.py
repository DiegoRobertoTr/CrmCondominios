# modules/condominios.py - COMPLETO ATUALIZADO COM BAIRRO NA IMPORTAÇÃO
import streamlit as st
from datetime import datetime
from pymongo import MongoClient
import urllib.parse
import pandas as pd
import re

# Lista de opções de Zona
OPCOES_ZONA = [
    "Selecione...",
    "Zona Sul",
    "Zona Norte", 
    "Zona Oeste",
    "Zona Sudoeste",
    "Centro",
    "Baixada Fluminense",
    "Outros"
]

def get_condominios_collection():
    """Retorna coleção de condomínios"""
    try:
        username = st.secrets["mongo"]["MONGO_USERNAME"]
        password = st.secrets["mongo"]["MONGO_PASSWORD"]
        cluster_url = st.secrets["mongo"]["MONGO_CLUSTER_URL"]
    except KeyError:
        username = st.secrets.get("MONGO_USERNAME", "")
        password = st.secrets.get("MONGO_PASSWORD", "")
        cluster_url = st.secrets.get("MONGO_CLUSTER_URL", "")
    
    u = urllib.parse.quote_plus(username)
    p = urllib.parse.quote_plus(password)
    uri = f"mongodb+srv://{u}:{p}@{cluster_url}/?retryWrites=true&w=majority"
    
    return MongoClient(uri).crm_db.condominios

def render_cadastro_condominio():
    """Renderiza formulário de cadastro de condomínio"""
    st.title("🏢 Cadastro de Condomínios")
    
    # Abas para Cadastro e Lista/Edição
    tab1, tab2, tab3 = st.tabs([
        "📝 Novo Condomínio", 
        "📋 Lista / Editar IDs IXC",
        "📥 Importar do IXC"
    ])
    
    with tab1:
        with st.form("form_condominio"):
            col1, col2 = st.columns(2)
            
            with col1:
                nome = st.text_input("Nome do Condomínio *", max_chars=100)
                cnpj = st.text_input("CNPJ", max_chars=18, placeholder="00.000.000/0000-00")
                bairro = st.text_input("Bairro *", max_chars=50)
                zona = st.selectbox("Zona *", options=OPCOES_ZONA, index=0)
                estado = st.text_input("Estado", value="RJ", max_chars=2, disabled=True)
            
            with col2:
                endereco = st.text_input("Endereço *", max_chars=100)
                numero = st.text_input("Número *", max_chars=10)
                cidade = st.text_input("Cidade *", value="Rio de Janeiro", max_chars=50)
                cep = st.text_input("CEP", max_chars=10, placeholder="00000-000")
                id_ixc = st.text_input(
                    "ID no IXCsoft", 
                    max_chars=10, 
                    placeholder="Ex: 123",
                    help="ID numérico do condomínio no sistema IXCsoft (opcional, pode preencher depois)"
                )
            
            st.subheader("👤 Dados do Síndico")
            col3, col4 = st.columns(2)
            
            with col3:
                sindico = st.text_input("Nome do Síndico", max_chars=100)
                cel_sindico = st.text_input("Celular Síndico", max_chars=15, placeholder="(00) 00000-0000")
            
            with col4:
                contato = st.text_input("Nome do Contato", max_chars=100)
                cel_contato = st.text_input("Celular Contato", max_chars=15, placeholder="(00) 00000-0000")
            
            submitted = st.form_submit_button("💾 Salvar Condomínio", type="primary")
            
            if submitted:
                if not all([nome, endereco, numero, cidade, bairro]):
                    st.error("⚠️ Preencha os campos obrigatórios!")
                elif zona == "Selecione...":
                    st.error("⚠️ Selecione a Zona do condomínio!")
                else:
                    condominio_data = {
                        "nome": nome.upper().strip(),
                        "cnpj": cnpj.strip() if cnpj else None,
                        "cidade": cidade.strip(),
                        "estado": "RJ",
                        "bairro": bairro.strip(),
                        "zona": zona,
                        "endereco": endereco.strip(),
                        "numero": numero.strip(),
                        "cep": cep.strip() if cep else None,
                        "id_ixc": id_ixc.strip() if id_ixc else None,
                        "sindico": sindico.strip() if sindico else None,
                        "cel_sindico": cel_sindico.strip() if cel_sindico else None,
                        "contato": contato.strip() if contato else None,
                        "cel_contato": cel_contato.strip() if cel_contato else None,
                        "data_cadastro": datetime.now()
                    }
                    
                    try:
                        collection = get_condominios_collection()
                        result = collection.insert_one(condominio_data)
                        st.success(f"✅ Condomínio '{nome}' cadastrado com sucesso!")
                        if id_ixc:
                            st.info(f"📌 ID no IXC: {id_ixc}")
                        else:
                            st.info("🔧 Lembre-se de configurar o ID do IXC na aba 'Lista / Editar IDs IXC'")
                        st.balloons()
                    except Exception as e:
                        st.error(f"❌ Erro ao salvar: {e}")
    
    with tab2:
        render_lista_condominios()
    
    with tab3:
        render_importacao_condominios()


def render_lista_condominios():
    """Exibe lista de condomínios e permite editar IDs IXC"""
    collection = get_condominios_collection()
    condominios = list(collection.find().sort("nome", 1))
    
    if not condominios:
        st.info("Nenhum condomínio cadastrado ainda.")
        return
    
    st.subheader("📋 Condomínios Cadastrados")
    
    # Estatísticas rápidas
    total = len(condominios)
    com_id_ixc = sum(1 for c in condominios if c.get("id_ixc"))
    sem_id_ixc = total - com_id_ixc
    
    col1, col2, col3 = st.columns(3)
    with col1:
        st.metric("Total de Condomínios", total)
    with col2:
        st.metric("Com ID IXC configurado", com_id_ixc)
    with col3:
        st.metric("Sem ID IXC", sem_id_ixc, delta="⚠️ Pendente" if sem_id_ixc > 0 else None)
    
    if sem_id_ixc > 0:
        st.warning(f"⚠️ {sem_id_ixc} condomínio(s) sem ID do IXC configurado. A integração não enviará o campo 'id_condominio' para esses condomínios.")
    
    # Tabela de condomínios
    dados = []
    for c in condominios:
        dados.append({
            "ID IXC": c.get("id_ixc", "❌ Não configurado"),
            "Nome do Condomínio": c.get("nome", ""),
            "Bairro": c.get("bairro", ""),  # 👈 ADICIONADO BAIRRO NA TABELA
            "Cidade": c.get("cidade", ""),
            "Endereço": f"{c.get('endereco', '')}, {c.get('numero', '')}",
            "Zona": c.get("zona", ""),
            "_id": str(c["_id"])
        })
    
    st.dataframe(dados, use_container_width=True, height=400)
    
    # Editor de ID IXC e Bairro
    st.divider()
    st.subheader("✏️ Configurar/Editar ID do IXC e Bairro")
    
    # Selectbox para escolher o condomínio
    cond_options = [f"{c['nome']} - {c['cidade']}" for c in condominios]
    cond_selecionado_nome = st.selectbox(
        "Selecione o condomínio:",
        options=cond_options,
        key="editar_id_ixc_select"
    )
    
    if cond_selecionado_nome:
        # Encontrar o condomínio selecionado
        cond_atual = next(
            (c for c in condominios if f"{c['nome']} - {c['cidade']}" == cond_selecionado_nome),
            None
        )
        
        if cond_atual:
            col1, col2 = st.columns([2, 1])
            with col1:
                novo_id_ixc = st.text_input(
                    "ID no IXCsoft:",
                    value=cond_atual.get("id_ixc", ""),
                    placeholder="Digite o ID numérico (ex: 123)",
                    help="Este é o ID que você vê no sistema IXCsoft para este condomínio",
                    key="novo_id_ixc_input"
                )
            with col2:
                st.markdown("### ")
                if st.button("💾 Salvar ID IXC", type="primary", key="salvar_id_ixc"):
                    collection.update_one(
                        {"_id": cond_atual["_id"]},
                        {"$set": {"id_ixc": novo_id_ixc.strip() if novo_id_ixc else None}}
                    )
                    if novo_id_ixc:
                        st.success(f"✅ ID do IXC '{novo_id_ixc}' configurado para '{cond_atual['nome']}'!")
                    else:
                        st.warning(f"⚠️ ID do IXC removido para '{cond_atual['nome']}'. A integração não enviará este campo.")
                    st.rerun()
            
            # 👇 NOVO: Editor de Bairro
            st.divider()
            st.subheader("📌 Editar Bairro")
            
            col1, col2 = st.columns([2, 1])
            with col1:
                novo_bairro = st.text_input(
                    "Bairro do Condomínio:",
                    value=cond_atual.get("bairro", ""),
                    placeholder="Digite o bairro",
                    help="Este é o bairro onde o condomínio está localizado",
                    key="novo_bairro_input"
                )
            with col2:
                st.markdown("### ")
                if st.button("💾 Salvar Bairro", type="primary", key="salvar_bairro"):
                    collection.update_one(
                        {"_id": cond_atual["_id"]},
                        {"$set": {"bairro": novo_bairro.strip() if novo_bairro else None}}
                    )
                    if novo_bairro:
                        st.success(f"✅ Bairro '{novo_bairro}' configurado para '{cond_atual['nome']}'!")
                    else:
                        st.warning(f"⚠️ Bairro removido para '{cond_atual['nome']}'.")
                    st.rerun()


# ============================================================================
# FUNÇÕES PARA IMPORTAÇÃO COMPLETA DE CONDOMÍNIOS
# ============================================================================

def render_importacao_condominios():
    """Renderiza o painel de importação de condomínios com senha"""
    
    st.subheader("📥 Importar/Substituir Condomínios do IXC")
    
    st.warning("""
    ⚠️ **ATENÇÃO - LEIA COM CUIDADO!**
    
    Esta operação irá **SUBSTITUIR COMPLETAMENTE** os dados dos condomínios no CRM
    pelos dados da planilha do IXC.
    
    **O que será substituído:**
    - ✅ Nome do condomínio
    - ✅ Endereço completo
    - ✅ Número
    - ✅ Cidade
    - ✅ Bairro (se disponível na planilha)
    - ✅ CEP
    - ✅ ID do IXC
    
    **O que será PRESERVADO:**
    - ✅ **VÍNCULOS COM CLIENTES** (o `_id` do MongoDB é mantido)
    - ✅ Dados do síndico (se existirem no CRM)
    - ✅ Data de cadastro original
    """)
    
    # ⚠️ CAMPO DE SENHA
    senha = st.text_input(
        "🔐 Digite a senha para importar:",
        type="password",
        placeholder="Digite a senha de autorização",
        key="senha_importacao_condominios"
    )
    
    # Upload do arquivo
    arquivo = st.file_uploader(
        "📂 Selecione o arquivo CSV ou Excel com os dados do IXC:",
        type=["csv", "xlsx", "xls"],
        help="O arquivo deve conter as colunas: ID, Condomínio, Cidade, Endereço, Número, CEP (Bairro é opcional)"
    )
    
    if arquivo and senha:
        # Verificar senha
        SENHA_CORRETA = "3540170"
        
        if senha == SENHA_CORRETA:
            st.success("🔓 Senha confirmada! Processando arquivo...")
            
            # Ler arquivo
            try:
                if arquivo.name.endswith('.csv'):
                    df = pd.read_csv(arquivo)
                else:
                    df = pd.read_excel(arquivo)
                
                # Normalizar nomes das colunas (remover espaços, acentos, etc.)
                df.columns = df.columns.str.strip()
                
                st.success(f"✅ Arquivo lido com sucesso! {len(df)} registros encontrados.")
                
                # Mostrar prévia dos dados
                with st.expander("📋 Prévia dos dados que serão importados"):
                    st.dataframe(df.head(10), use_container_width=True)
                    
                    # Mostrar estatísticas
                    col1, col2, col3 = st.columns(3)
                    with col1:
                        st.metric("Total de registros", len(df))
                    with col2:
                        col_id = next((c for c in df.columns if 'id' in c.lower()), None)
                        st.metric("Com ID", len(df[df[col_id].notna()]) if col_id else 0)
                    with col3:
                        col_end = next((c for c in df.columns if 'endereco' in c.lower() or 'endereço' in c.lower()), None)
                        st.metric("Com endereço", len(df[df[col_end].notna()]) if col_end else 0)
                
                # Mapear colunas de forma flexível
                mapa_colunas = {}
                
                # ID do IXC
                for nome in ['ID', 'Id', 'id', 'ID_IXC', 'id_ixc', 'Código', 'codigo']:
                    if nome in df.columns:
                        mapa_colunas['id_ixc'] = nome
                        break
                
                # Nome do Condomínio
                for nome in ['Condomínio', 'Condominio', 'condominio', 'NOME', 'Nome', 'nome']:
                    if nome in df.columns:
                        mapa_colunas['nome'] = nome
                        break
                
                # Cidade
                for nome in ['Cidade', 'cidade', 'CIDADE', 'Município', 'Municipio']:
                    if nome in df.columns:
                        mapa_colunas['cidade'] = nome
                        break
                
                # 👇 NOVO: Bairro
                for nome in ['Bairro', 'bairro', 'BAIRRO', 'Bairro/Núcleo', 'Bairro (Núcleo)', 'Bairro_Núcleo']:
                    if nome in df.columns:
                        mapa_colunas['bairro'] = nome
                        break
                
                # Endereço
                for nome in ['Endereço', 'Endereco', 'endereco', 'endereço', 'Logradouro']:
                    if nome in df.columns:
                        mapa_colunas['endereco'] = nome
                        break
                
                # Número
                for nome in ['Número', 'Numero', 'numero', 'número']:
                    if nome in df.columns:
                        mapa_colunas['numero'] = nome
                        break
                
                # CEP
                for nome in ['CEP', 'Cep', 'cep']:
                    if nome in df.columns:
                        mapa_colunas['cep'] = nome
                        break
                
                # CNPJ (opcional)
                for nome in ['CNPJ', 'Cnpj', 'cnpj']:
                    if nome in df.columns:
                        mapa_colunas['cnpj'] = nome
                        break
                
                # Verificar colunas obrigatórias
                colunas_obrigatorias = ['id_ixc', 'nome', 'cidade', 'endereco']
                colunas_faltando = [c for c in colunas_obrigatorias if c not in mapa_colunas]
                
                if colunas_faltando:
                    st.error(f"❌ Colunas obrigatórias não encontradas: {colunas_faltando}")
                    st.info("📌 O arquivo deve conter as colunas: ID, Condomínio, Cidade, Endereço")
                    st.write("Colunas disponíveis:", list(df.columns))
                    return
                
                # Mostrar mapeamento das colunas
                with st.expander("🔍 Mapeamento das colunas detectado"):
                    for campo, coluna in mapa_colunas.items():
                        st.write(f"- **{campo}** → '{coluna}'")
                
                # Botão de confirmação final
                st.divider()
                st.markdown("### ⚠️ Confirmação Final")
                
                # Mostrar quais condomínios serão afetados
                st.markdown("**Condomínios que serão atualizados/criados:**")
                
                # Listar os condomínios da planilha
                nomes_planilha = df[mapa_colunas['nome']].tolist()
                st.write(f"📋 {len(nomes_planilha)} condomínios da planilha:")
                
                # Buscar condomínios existentes no CRM
                collection = get_condominios_collection()
                
                # Criar tabela de comparação
                dados_comparacao = []
                for _, row in df.iterrows():
                    id_ixc = str(row[mapa_colunas['id_ixc']]).strip()
                    nome = str(row[mapa_colunas['nome']]).strip()
                    
                    # Buscar no CRM
                    cond_crm = collection.find_one({"id_ixc": id_ixc})
                    if not cond_crm:
                        cond_crm = collection.find_one({"nome": {"$regex": f"^{nome}$", "$options": "i"}})
                    
                    dados_comparacao.append({
                        "ID IXC": id_ixc,
                        "Nome (Planilha)": nome,
                        "Nome (CRM)": cond_crm.get("nome", "❌ Não existe") if cond_crm else "❌ Não existe",
                        "Status": "🔄 Atualizar" if cond_crm else "🆕 Novo"
                    })
                
                st.dataframe(dados_comparacao, use_container_width=True)
                
                confirmar = st.checkbox(
                    "✅ Confirmo que entendi que os dados do CRM serão **SUBSTITUÍDOS** pelos dados da planilha, preservando apenas os vínculos com clientes.",
                    key="confirmar_importacao_completa"
                )
                
                if confirmar and st.button("🚀 Confirmar Importação", type="primary"):
                    with st.spinner("🔄 Importando dados..."):
                        resultado = importar_condominios_completos(df, mapa_colunas)
                        
                        if resultado.get("erro"):
                            st.error(f"❌ {resultado['erro']}")
                        else:
                            # Estatísticas
                            st.success(f"""
                            ✅ **Importação concluída com sucesso!**
                            
                            - 📊 Total processados: **{resultado['total']}**
                            - 🔄 Atualizados: **{resultado['atualizados']}**
                            - 🆕 Novos criados: **{resultado['novos']}**
                            - ❌ Erros: **{resultado['erros']}**
                            """)
                            
                            # Mostrar detalhes
                            if resultado.get('detalhes'):
                                with st.expander("📋 Detalhes da Importação", expanded=True):
                                    for item in resultado['detalhes']:
                                        if item['status'] == 'atualizado':
                                            st.success(f"✅ **{item['nome']}** (ID IXC: {item.get('id_ixc')})")
                                            if item.get('alteracoes'):
                                                for alt in item['alteracoes']:
                                                    st.write(f"   🔄 {alt}")
                                        elif item['status'] == 'novo':
                                            st.info(f"🆕 **{item['nome']}** - Novo condomínio criado (ID IXC: {item.get('id_ixc')})")
                                        else:
                                            st.error(f"❌ {item['nome']} - {item.get('erro', 'Erro desconhecido')}")
                            
                            # Mostrar resumo dos condomínios atualizados
                            with st.expander("📊 Resumo dos Condomínios Atualizados"):
                                condominios = list(collection.find().sort("nome", 1))
                                
                                dados_resumo = []
                                for c in condominios:
                                    dados_resumo.append({
                                        "ID IXC": c.get("id_ixc", "N/A"),
                                        "Nome": c.get("nome", ""),
                                        "Bairro": c.get("bairro", ""),  # 👈 ADICIONADO BAIRRO
                                        "Endereço": f"{c.get('endereco', '')}, {c.get('numero', '')}",
                                        "Cidade": c.get("cidade", ""),
                                        "CEP": c.get("cep", ""),
                                    })
                                
                                st.dataframe(dados_resumo, use_container_width=True)
            
            except Exception as e:
                st.error(f"❌ Erro ao processar arquivo: {e}")
                import traceback
                st.code(traceback.format_exc())
        
        elif senha != SENHA_CORRETA:
            st.error("❌ Senha incorreta! Acesso negado.")
    
    elif arquivo and not senha:
        st.warning("🔐 Digite a senha para prosseguir com a importação.")


def importar_condominios_completos(df, mapa_colunas):
    """
    Importa/SUBSTITUI completamente os dados dos condomínios a partir de dados do IXC.
    PRESERVA os vínculos com clientes (mantendo o _id).
    AGORA INCLUI O CAMPO BAIRRO!
    """
    resultado = {
        "total": 0,
        "atualizados": 0,
        "novos": 0,
        "erros": 0,
        "detalhes": []
    }
    
    try:
        collection = get_condominios_collection()
        
        # Processar cada linha do DataFrame
        for idx, row in df.iterrows():
            resultado["total"] += 1
            
            try:
                # Extrair dados da planilha
                id_ixc = str(row[mapa_colunas['id_ixc']]).strip()
                nome = str(row[mapa_colunas['nome']]).strip().upper()
                cidade = str(row[mapa_colunas['cidade']]).strip()
                endereco = str(row[mapa_colunas['endereco']]).strip()
                numero = str(row.get(mapa_colunas.get('numero', ''), '')).strip() if mapa_colunas.get('numero') else ''
                cep = str(row.get(mapa_colunas.get('cep', ''), '')).strip() if mapa_colunas.get('cep') else ''
                cnpj = str(row.get(mapa_colunas.get('cnpj', ''), '')).strip() if mapa_colunas.get('cnpj') else ''
                
                # 👇 NOVO: Extrair bairro
                bairro = str(row.get(mapa_colunas.get('bairro', ''), '')).strip() if mapa_colunas.get('bairro') else ''
                
                # Limpar ID do IXC (remover caracteres não numéricos se necessário)
                id_ixc = re.sub(r'[^0-9]', '', id_ixc)
                
                if not id_ixc or not nome or not cidade or not endereco:
                    resultado["erros"] += 1
                    resultado["detalhes"].append({
                        "nome": nome or f"Linha {idx}",
                        "status": "erro",
                        "erro": f"Dados incompletos - ID: {id_ixc}, Nome: {nome}, Cidade: {cidade}, Endereco: {endereco}"
                    })
                    print(f"⚠️ Linha {idx}: Dados incompletos - ID: {id_ixc}, Nome: {nome}")
                    continue
                
                # 🔍 PRIORIDADE 1: Buscar pelo ID do IXC
                cond_existente = collection.find_one({"id_ixc": id_ixc})
                
                # 🔍 PRIORIDADE 2: Se não encontrou pelo ID, buscar pelo nome (normalizado)
                if not cond_existente:
                    # Normalizar nome para busca (remover caracteres especiais, espaços extras)
                    nome_busca = re.sub(r'[^\w\s]', '', nome).strip()
                    cond_existente = collection.find_one({
                        "nome": {"$regex": f"^{nome_busca}$", "$options": "i"}
                    })
                    if cond_existente:
                        print(f"🔍 Encontrado pelo nome: '{nome}' (ID CRM: {cond_existente['_id']})")
                
                if cond_existente:
                    # ========== SUBSTITUIR COMPLETAMENTE OS DADOS ==========
                    # Preservar dados importantes do CRM
                    dados_preservados = {
                        "_id": cond_existente["_id"],  # Mantém o ID para preservar vínculos
                        "data_cadastro": cond_existente.get("data_cadastro", datetime.now()),
                        "sindico": cond_existente.get("sindico"),
                        "cel_sindico": cond_existente.get("cel_sindico"),
                        "contato": cond_existente.get("contato"),
                        "cel_contato": cond_existente.get("cel_contato"),
                        "zona": cond_existente.get("zona"),  # Preservar zona se existir
                    }
                    
                    # Preparar os novos dados (SUBSTITUIÇÃO COMPLETA)
                    novos_dados = {
                        "nome": nome,
                        "id_ixc": id_ixc,
                        "cidade": cidade,
                        "estado": "RJ",
                        "endereco": endereco,
                        "numero": numero if numero else "",
                        "bairro": bairro if bairro else "",  # 👈 ADICIONADO BAIRRO
                        "cep": cep if cep else "",
                        "cnpj": cnpj if cnpj else cond_existente.get("cnpj", ""),
                        "ultima_sincronizacao_ixc": datetime.now(),
                        "ultima_atualizacao_completa": datetime.now()
                    }
                    
                    # Combinar dados preservados com novos dados
                    dados_atualizados = {**dados_preservados, **novos_dados}
                    
                    # Remover campos que não devem ser atualizados
                    dados_atualizados.pop("_id", None)
                    
                    # Verificar alterações para log
                    alteracoes = []
                    for campo, valor in dados_atualizados.items():
                        if campo in cond_existente and str(cond_existente[campo]) != str(valor):
                            alteracoes.append(f"{campo}: '{cond_existente[campo]}' -> '{valor}'")
                    
                    # Se não houve alterações, apenas log
                    if not alteracoes:
                        alteracoes.append("Nenhuma alteração necessária - dados já estão corretos")
                    
                    # Atualizar no MongoDB
                    collection.update_one(
                        {"_id": cond_existente["_id"]},
                        {"$set": dados_atualizados}
                    )
                    
                    resultado["atualizados"] += 1
                    resultado["detalhes"].append({
                        "nome": nome,
                        "id_ixc": id_ixc,
                        "status": "atualizado",
                        "alteracoes": alteracoes,
                        "id_crm": str(cond_existente["_id"])
                    })
                    
                    print(f"✅ Condomínio atualizado: {nome} (ID IXC: {id_ixc}) - {len(alteracoes)} alterações")
                    
                else:
                    # ========== CRIAR NOVO CONDOMÍNIO ==========
                    novo_cond = {
                        "nome": nome,
                        "id_ixc": id_ixc,
                        "cidade": cidade,
                        "estado": "RJ",
                        "endereco": endereco,
                        "numero": numero if numero else "",
                        "bairro": bairro if bairro else "",  # 👈 ADICIONADO BAIRRO
                        "cep": cep if cep else "",
                        "cnpj": cnpj if cnpj else "",
                        "data_cadastro": datetime.now(),
                        "ultima_sincronizacao_ixc": datetime.now(),
                        "ultima_atualizacao_completa": datetime.now()
                    }
                    
                    result = collection.insert_one(novo_cond)
                    resultado["novos"] += 1
                    resultado["detalhes"].append({
                        "nome": nome,
                        "id_ixc": id_ixc,
                        "status": "novo",
                        "id_crm": str(result.inserted_id),
                        "alteracoes": ["Condomínio criado a partir do IXC"]
                    })
                    
                    print(f"🆕 Novo condomínio criado: {nome} (ID IXC: {id_ixc})")
            
            except Exception as e:
                resultado["erros"] += 1
                nome_linha = str(row.get(mapa_colunas.get('nome', ''), f"Linha {idx}"))
                resultado["detalhes"].append({
                    "nome": nome_linha,
                    "status": "erro",
                    "erro": str(e)
                })
                print(f"❌ Erro na linha {idx}: {e}")
                import traceback
                traceback.print_exc()
        
        return resultado
    
    except Exception as e:
        return {"erro": str(e)}


# ============================================================================
# FUNÇÕES AUXILIARES
# ============================================================================

def get_condominio_by_id(condominio_id):
    """Busca condomínio por ID"""
    collection = get_condominios_collection()
    return collection.find_one({"_id": condominio_id})

def get_all_condominios():
    """Retorna todos os condomínios ordenados por nome"""
    collection = get_condominios_collection()
    return list(collection.find().sort("nome", 1))

def get_condominio_options():
    """Retorna lista de opções para selectbox (ID, nome)"""
    condominios = get_all_condominios()
    return {f"{c['nome']} - {c['cidade']}": c["_id"] for c in condominios}

def get_condominios_por_zona(zona=None):
    """Retorna condomínios filtrados por zona"""
    collection = get_condominios_collection()
    if zona:
        return list(collection.find({"zona": zona}).sort("nome", 1))
    return get_all_condominios()

def get_estatisticas_zonas():
    """Retorna contagem de condomínios por zona"""
    collection = get_condominios_collection()
    pipeline = [
        {"$group": {"_id": "$zona", "count": {"$sum": 1}}},
        {"$sort": {"count": -1}}
    ]
    return list(collection.aggregate(pipeline))

def update_condominio(condominio_id, updates):
    """Atualiza um condomínio específico"""
    collection = get_condominios_collection()
    return collection.update_one(
        {"_id": condominio_id},
        {"$set": updates}
    )
