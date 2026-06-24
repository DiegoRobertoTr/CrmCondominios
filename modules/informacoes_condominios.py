# modules/informacoes_condominios.py
"""
Módulo de Informações Detalhadas dos Condomínios
Gerencia: Pontos de Internet, Placas/Fotos, Doações, Contatos, etc.
"""

import streamlit as st
import pandas as pd
from datetime import datetime
import re
from unidecode import unidecode
from fuzzywuzzy import fuzz, process
from modules.condominios import get_condominios_collection, OPCOES_ZONA

# ============================================================================
# CONSTANTES
# ============================================================================

# Tipos de placas para seleção
TIPOS_PLACA = [
    "Cavalete",
    "Placa de Metal",
    "Windbanner",
    "Porta Panfleto",
    "Adesivo",
    "Banner",
    "Painel LED",
    "Outro"
]

# Locais comuns para pontos de internet
LOCAIS_PONTOS = [
    "Portaria",
    "ADM",
    "Salão de Festas",
    "Salão de Jogos",
    "Academia",
    "Churrasqueira",
    "Coworking",
    "Lavanderia",
    "Espaço Gourmet",
    "Rooftop",
    "Área de Lazer",
    "Carregador Veicular",
    "Espaço Baby",
    "Espaço Teen",
    "Espaço Zen",
    "Outros"
]

# Formas de pagamento
FORMAS_PAGAMENTO = ["Pix", "Cartão", "Boleto", "Transferência", "Dinheiro", "Outro"]

# Funções de contato
FUNCOES_CONTATO = ["Síndico", "Subsíndico", "Administrador", "Preposto", "Porteiro", "Zelador", "Outro"]

# ============================================================================
# FUNÇÕES DE NORMALIZAÇÃO E MATCHING
# ============================================================================

def normalizar_nome_condominio(nome):
    """
    Normaliza nome do condomínio para matching:
    - Remove acentos
    - Remove palavras comuns
    - Remove caracteres especiais
    """
    if not nome:
        return ""
    
    # Remove acentos
    nome = unidecode(nome.upper().strip())
    
    # Remove palavras comuns
    palavras_remover = [
        "CONDOMINIO", "CONDOMÍNIO", "RESIDENCIAL", "RESIDENCE",
        "CLUBE", "PARK", "LIVING", "VIVAZ", "VIVA", "VIVER",
        "ALTO", "NOVO", "NOVA", "RECANTO", "PARQUE", "JARDIM",
        "VILLAGIO", "SPAZIO", "URBAN", "PORTO", "ORLA"
    ]
    
    for palavra in palavras_remover:
        nome = nome.replace(palavra, "").strip()
    
    # Remove múltiplos espaços
    nome = re.sub(r'\s+', ' ', nome)
    
    return nome.strip()

def encontrar_match_condominio(nome_planilha, zona, collection):
    """
    Encontra o melhor match para um condomínio da planilha no CRM
    Usa múltiplas estratégias:
    1. Match exato normalizado
    2. Fuzzy matching com threshold
    3. Match por zona e nome
    """
    if not nome_planilha:
        return None
    
    nome_normalizado = normalizar_nome_condominio(nome_planilha)
    
    # Estratégia 1: Busca pelo ID do IXC (se disponível)
    id_match = re.search(r'ID:(\d+)', nome_planilha)
    if id_match:
        id_ixc = id_match.group(1)
        resultado = collection.find_one({"id_ixc": id_ixc})
        if resultado:
            resultado['_score'] = 100
            return resultado
    
    # Estratégia 2: Busca pelo nome normalizado (match exato)
    todos_condominios = list(collection.find())
    
    # Primeiro, tentar match exato (ignorando maiúsculas/minúsculas)
    for cond in todos_condominios:
        nome_crm = normalizar_nome_condominio(cond.get('nome', ''))
        if nome_crm == nome_normalizado:
            cond['_score'] = 100
            return cond
        
        # Também tentar match contendo o nome
        if nome_normalizado in nome_crm or nome_crm in nome_normalizado:
            if zona and cond.get('zona') == zona:
                cond['_score'] = 85
                return cond
            cond['_score'] = 70
    
    # Estratégia 3: Fuzzy matching
    nomes_crm = [normalizar_nome_condominio(c.get('nome', '')) for c in todos_condominios]
    if nomes_crm:
        matches = process.extract(
            nome_normalizado,
            nomes_crm,
            scorer=fuzz.token_sort_ratio,
            limit=5
        )
        
        for match in matches:
            if match[1] >= 70:
                idx = nomes_crm.index(match[0])
                cond = todos_condominios[idx]
                
                if zona and cond.get('zona') == zona:
                    cond['_score'] = match[1] + 10
                else:
                    cond['_score'] = match[1]
                
                return cond
    
    # Estratégia 4: Buscar por palavras-chave mais importantes
    palavras_chave = nome_normalizado.split()
    if len(palavras_chave) > 1:
        chave_principal = " ".join(palavras_chave[:2])
        for cond in todos_condominios:
            nome_crm = normalizar_nome_condominio(cond.get('nome', ''))
            if chave_principal in nome_crm:
                cond['_score'] = 60
                return cond
    
    return None

def detectar_colunas_informacoes(df):
    """
    Detecta automaticamente as colunas da planilha de informações
    """
    mapa = {}
    colunas = df.columns.tolist()
    
    for nome in ['ZONA', 'Zona', 'zona', 'Região', 'Regiao']:
        if nome in colunas:
            mapa['zona'] = nome
            break
    
    for nome in ['CONDOMÍNIO', 'Condomínio', 'CONDOMINIO', 'Condominio', 'condominio', 'Nome']:
        if nome in colunas:
            mapa['condominio'] = nome
            break
    
    for nome in ['PONTOS INTERNET', 'Pontos Internet', 'PONTOS_INTERNET', 'pontos_internet']:
        if nome in colunas:
            mapa['pontos_internet'] = nome
            break
    
    for nome in ['PLACAS (FOTOS)', 'PLACAS FOTOS', 'Placas Fotos', 'PLACAS', 'Placas']:
        if nome in colunas:
            mapa['placas_fotos'] = nome
            break
    
    for nome in ['DOAÇÃO', 'Doação', 'DOACAO', 'Doacao', 'doacao']:
        if nome in colunas:
            mapa['doacao'] = nome
            break
    
    for nome in ['PARCEIRO', 'Parceiro', 'parceiro']:
        if nome in colunas:
            mapa['parceiro'] = nome
            break
    
    for nome in ['SÍNDICO', 'Sindico', 'SINDICO', 'sindico']:
        if nome in colunas:
            mapa['sindico'] = nome
            break
    
    contatos_colunas = []
    for nome in colunas:
        if 'CONTATO' in nome.upper() or 'Contato' in nome:
            contatos_colunas.append(nome)
    if contatos_colunas:
        mapa['contatos'] = contatos_colunas
    
    for nome in ['OBSERVAÇÕES', 'Observações', 'OBSERVACOES', 'Observacoes']:
        if nome in colunas:
            mapa['observacoes'] = nome
            break
    
    return mapa

# ============================================================================
# FUNÇÕES DE PARSING
# ============================================================================

def parse_pontos_internet(texto):
    """
    Parseia o texto de pontos de internet
    Exemplo: "02 (Adm e portaria) + 02 (salão de jogos e coworking)"
    Retorna: {"quantidade": 4, "locais": ["ADM", "Portaria", "Salão de Jogos", "Coworking"], "observacao": texto}
    """
    if pd.isna(texto) or not texto:
        return {"quantidade": 0, "locais": [], "observacao": ""}
    
    texto = str(texto).strip()
    locais = []
    quantidade_total = 0
    
    padrao = r'(\d+)\s*\(([^)]+)\)'
    matches = re.findall(padrao, texto)
    
    if matches:
        for qtd, locais_str in matches:
            qtd = int(qtd)
            quantidade_total += qtd
            locais_sep = re.split(r'[e,;]+\s*', locais_str)
            for local in locais_sep:
                local = local.strip()
                if local and local not in locais:
                    locais.append(local)
    
    if not matches:
        numeros = re.findall(r'(\d+)', texto)
        if numeros:
            quantidade_total = sum(int(n) for n in numeros)
        
        locais_palavras = ['adm', 'portaria', 'salão', 'academia', 'churrasqueira', 
                          'coworking', 'lavanderia', 'rooftop', 'carregador']
        for local in locais_palavras:
            if local in texto.lower():
                locais.append(local.title())
    
    return {
        "quantidade": quantidade_total,
        "locais": locais,
        "observacao": texto
    }

def parse_placas_fotos(texto):
    """
    Parseia o texto de placas e fotos
    Exemplo: "01 cavalete + 03 Placas (Portaria, Adm e Salão)"
    Retorna: {"itens": [{"tipo": "cavalete", "quantidade": 1, "local": ""}, ...], "observacao": texto}
    """
    if pd.isna(texto) or not texto:
        return {"itens": [], "observacao": ""}
    
    texto = str(texto).strip()
    itens = []
    
    padrao = r'(\d+)\s*([a-zA-ZÀ-ÿç\s]+)'
    matches = re.findall(padrao, texto)
    
    if matches:
        for qtd, tipo in matches:
            tipo = tipo.strip()
            tipo_normalizado = None
            for tipo_valido in TIPOS_PLACA:
                if tipo_valido.lower() in tipo.lower():
                    tipo_normalizado = tipo_valido
                    break
            
            if tipo_normalizado:
                local = ""
                padrao_local = r'\(([^)]+)\)'
                local_match = re.search(padrao_local, texto)
                if local_match:
                    local = local_match.group(1)
                
                itens.append({
                    "tipo": tipo_normalizado,
                    "quantidade": int(qtd),
                    "local": local,
                    "observacao": ""
                })
    
    if not itens:
        itens.append({
            "tipo": "Outro",
            "quantidade": 1,
            "local": "",
            "observacao": texto
        })
    
    return {
        "itens": itens,
        "observacao": texto
    }

def parse_doacoes(texto):
    """
    Parseia o texto de doações
    Exemplo: "01 Notebook Dell: 2.399,00 (Pix)"
    Retorna: {"itens": [{"item": "Notebook Dell", "valor": 2399.00, "forma_pagamento": "Pix"}], "observacao": texto}
    """
    if pd.isna(texto) or not texto:
        return {"itens": [], "observacao": "", "total_doacoes": 0}
    
    texto = str(texto).strip()
    itens = []
    
    padrao = r'(\d+)\s*([^:]+):\s*([\d.,]+)\s*\(([^)]+)\)'
    matches = re.findall(padrao, texto)
    
    if matches:
        for qtd, item, valor_str, forma in matches:
            valor = float(valor_str.replace('.', '').replace(',', '.'))
            itens.append({
                "item": item.strip(),
                "quantidade": int(qtd),
                "valor": valor,
                "forma_pagamento": forma.strip(),
                "observacao": ""
            })
    
    if not itens:
        padrao_simples = r'([^:]+):\s*([\d.,]+)'
        matches_simples = re.findall(padrao_simples, texto)
        if matches_simples:
            for item, valor_str in matches_simples:
                try:
                    valor = float(valor_str.replace('.', '').replace(',', '.'))
                    itens.append({
                        "item": item.strip(),
                        "quantidade": 1,
                        "valor": valor,
                        "forma_pagamento": "Não especificado",
                        "observacao": ""
                    })
                except:
                    pass
    
    total_doacoes = sum(item.get('valor', 0) for item in itens)
    
    return {
        "itens": itens,
        "observacao": texto,
        "total_doacoes": total_doacoes
    }

# ============================================================================
# FUNÇÕES DE IMPORTAÇÃO
# ============================================================================

def importar_informacoes_completas(df, mapa_colunas, collection):
    """
    Importa informações detalhadas da planilha para o CRM
    Usa matching inteligente para encontrar os condomínios
    """
    resultado = {
        "total": 0,
        "matches": 0,
        "atualizados": 0,
        "criados": 0,
        "sem_match": 0,
        "detalhes": []
    }
    
    for idx, row in df.iterrows():
        resultado["total"] += 1
        
        try:
            nome_planilha = str(row[mapa_colunas.get('condominio', 'CONDOMÍNIO')]).strip()
            zona = str(row[mapa_colunas.get('zona', 'ZONA')]).strip() if mapa_colunas.get('zona') else ""
            
            if not nome_planilha:
                continue
            
            cond_match = encontrar_match_condominio(nome_planilha, zona, collection)
            
            if cond_match:
                resultado["matches"] += 1
                
                pontos_texto = str(row.get(mapa_colunas.get('pontos_internet', ''), '')).strip() if mapa_colunas.get('pontos_internet') else ""
                placas_texto = str(row.get(mapa_colunas.get('placas_fotos', ''), '')).strip() if mapa_colunas.get('placas_fotos') else ""
                doacao_texto = str(row.get(mapa_colunas.get('doacao', ''), '')).strip() if mapa_colunas.get('doacao') else ""
                parceiro_texto = str(row.get(mapa_colunas.get('parceiro', ''), '')).strip() if mapa_colunas.get('parceiro') else ""
                sindico_texto = str(row.get(mapa_colunas.get('sindico', ''), '')).strip() if mapa_colunas.get('sindico') else ""
                observacoes_texto = str(row.get(mapa_colunas.get('observacoes', ''), '')).strip() if mapa_colunas.get('observacoes') else ""
                
                pontos_parse = parse_pontos_internet(pontos_texto) if pontos_texto else {"quantidade": 0, "locais": [], "observacao": ""}
                placas_parse = parse_placas_fotos(placas_texto) if placas_texto else {"itens": [], "observacao": ""}
                doacoes_parse = parse_doacoes(doacao_texto) if doacao_texto else {"itens": [], "observacao": "", "total_doacoes": 0}
                
                contatos = []
                if mapa_colunas.get('contatos'):
                    for col_contato in mapa_colunas['contatos']:
                        if col_contato in row and not pd.isna(row[col_contato]) and row[col_contato]:
                            contatos.append({
                                "nome": str(row[col_contato]).strip(),
                                "telefone": "",
                                "funcao": col_contato.replace("CONTATO ", "").strip(),
                                "observacao": ""
                            })
                
                info_detalhada = {
                    "pontos_internet": pontos_parse,
                    "placas_fotos": placas_parse,
                    "doacoes": doacoes_parse,
                    "parceiros": [p.strip() for p in parceiro_texto.split(',') if p.strip()] if parceiro_texto else [],
                    "sindico": sindico_texto,
                    "contatos": contatos,
                    "observacoes": observacoes_texto,
                    "zona_planilha": zona,
                    "data_importacao": datetime.now()
                }
                
                if cond_match.get('_id'):
                    collection.update_one(
                        {"_id": cond_match['_id']},
                        {"$set": {"informacoes_detalhadas": info_detalhada, "ultima_atualizacao_informacoes": datetime.now()}}
                    )
                    resultado["atualizados"] += 1
                    resultado["detalhes"].append({
                        "nome_planilha": nome_planilha,
                        "nome_crm": cond_match.get('nome', ''),
                        "status": "match",
                        "score": cond_match.get('_score', 0),
                        "detalhes": f"Atualizado com informações da planilha"
                    })
                else:
                    novo_cond = {
                        "nome": nome_planilha.upper(),
                        "zona": zona,
                        "informacoes_detalhadas": info_detalhada,
                        "data_cadastro": datetime.now(),
                        "ultima_atualizacao_informacoes": datetime.now()
                    }
                    collection.insert_one(novo_cond)
                    resultado["criados"] += 1
                    resultado["detalhes"].append({
                        "nome_planilha": nome_planilha,
                        "nome_crm": nome_planilha,
                        "status": "criado",
                        "score": 0,
                        "detalhes": "Novo condomínio criado a partir da planilha"
                    })
            else:
                resultado["sem_match"] += 1
                resultado["detalhes"].append({
                    "nome_planilha": nome_planilha,
                    "nome_crm": "",
                    "status": "sem_match",
                    "score": 0,
                    "detalhes": "Nenhum match encontrado no CRM"
                })
                
        except Exception as e:
            resultado["detalhes"].append({
                "nome_planilha": str(row.get('CONDOMÍNIO', f'Linha {idx}')),
                "nome_crm": "",
                "status": "erro",
                "score": 0,
                "detalhes": f"Erro: {str(e)}"
            })
    
    return resultado

# ============================================================================
# FUNÇÕES DE RENDERIZAÇÃO
# ============================================================================

def render_informacoes_condominios():
    """Renderiza a aba de informações detalhadas dos condomínios"""
    st.title("📊 Informações Detalhadas dos Condomínios")
    
    # Abas internas
    tab1, tab2, tab3 = st.tabs([
        "📋 Dashboard",
        "📥 Importar Planilha",
        "✏️ Editar Informações"
    ])
    
    with tab1:
        render_dashboard()
    
    with tab2:
        render_importacao_informacoes()
    
    with tab3:
        render_lista_edicao_condominios()

def render_dashboard():
    """Dashboard com visão geral das informações"""
    collection = get_condominios_collection()
    
    total_condominios = collection.count_documents({})
    com_informacoes = collection.count_documents({"informacoes_detalhadas": {"$exists": True}})
    sem_informacoes = total_condominios - com_informacoes
    
    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.metric("📊 Total de Condomínios", total_condominios)
    with col2:
        st.metric("✅ Com Informações", com_informacoes)
    with col3:
        st.metric("⚠️ Sem Informações", sem_informacoes, 
                 delta="⚠️ Pendente" if sem_informacoes > 0 else None)
    with col4:
        zonas = list(collection.aggregate([
            {"$group": {"_id": "$zona", "count": {"$sum": 1}}},
            {"$sort": {"count": -1}}
        ]))
        if zonas:
            st.metric("🏙️ Principal Zona", zonas[0]["_id"])
    
    st.subheader("🔍 Filtros")
    col1, col2 = st.columns(2)
    with col1:
        zona_filter = st.selectbox("Zona", ["Todas"] + OPCOES_ZONA[1:])
    with col2:
        status_filter = st.selectbox(
            "Status", 
            ["Todos", "Com Informações", "Sem Informações"]
        )
    
    query = {}
    if zona_filter != "Todas":
        query["zona"] = zona_filter
    
    if status_filter == "Com Informações":
        query["informacoes_detalhadas"] = {"$exists": True}
    elif status_filter == "Sem Informações":
        query["informacoes_detalhadas"] = {"$exists": False}
    
    condominios = list(collection.find(query).sort("nome", 1))
    
    st.subheader(f"📋 {len(condominios)} Condomínios")
    
    # Grid de cards (3 por linha) - APENAS VISUALIZAÇÃO
    cols = st.columns(3)
    for idx, cond in enumerate(condominios):
        with cols[idx % 3]:
            with st.container(border=True):
                st.markdown(f"### 🏢 {cond.get('nome', 'N/A')[:35]}")
                st.caption(f"📍 {cond.get('zona', 'N/A')} | IXC: {cond.get('id_ixc', 'N/A')}")
                
                info = cond.get("informacoes_detalhadas", {})
                if info:
                    pontos = info.get("pontos_internet", {})
                    if pontos and pontos.get("quantidade", 0) > 0:
                        qtd = pontos.get("quantidade", 0)
                        locais = pontos.get("locais", [])
                        st.write(f"📶 **{qtd}** pontos" + (f" ({', '.join(locais[:3])})" if locais else ""))
                    
                    placas = info.get("placas_fotos", {})
                    itens_placas = placas.get("itens", [])
                    if itens_placas:
                        st.write(f"🪧 **{len(itens_placas)}** itens de placa")
                    
                    doacoes = info.get("doacoes", {})
                    total_doacoes = doacoes.get("total_doacoes", 0)
                    if total_doacoes > 0:
                        st.write(f"🎁 **R$ {total_doacoes:,.2f}** em doações")
                    
                    data_atualizacao = cond.get("ultima_atualizacao_informacoes")
                    if data_atualizacao:
                        st.caption(f"🔄 Atualizado: {data_atualizacao.strftime('%d/%m/%Y')}")
                else:
                    st.warning("⚠️ Sem informações detalhadas")
                
                # Link para editar na aba de edição
                if st.button("✏️ Editar", key=f"edit_{cond['_id']}"):
                    st.session_state['cond_info_edit'] = str(cond['_id'])
                    st.rerun()

def render_importacao_informacoes():
    """Importa informações da planilha usando matching inteligente"""
    st.subheader("📥 Importar Informações Detalhadas")
    
    st.info("""
    **🔍 Como funciona o matching inteligente:**
    
    1. **Prioridade 1**: Match pelo ID do IXC (se disponível no nome)
    2. **Prioridade 2**: Match pelo nome normalizado (remove acentos, palavras comuns)
    3. **Prioridade 3**: Match por similaridade de nome (fuzzy matching)
    4. **Prioridade 4**: Match por zona + palavras-chave
    
    Isso garante que mesmo com nomes escritos de forma diferente, consigamos
    encontrar o condomínio correto no CRM.
    """)
    
    arquivo = st.file_uploader(
        "📂 Selecione a planilha com as informações detalhadas",
        type=["csv", "xlsx", "xls"],
        help="A planilha deve ter as colunas: ZONA, CONDOMÍNIO, PONTOS INTERNET, PLACAS (FOTOS), DOAÇÃO, etc."
    )
    
    if arquivo:
        try:
            if arquivo.name.endswith('.csv'):
                df = pd.read_csv(arquivo)
            else:
                df = pd.read_excel(arquivo)
            
            st.success(f"✅ Arquivo lido! {len(df)} registros encontrados")
            df.columns = df.columns.str.strip()
            
            with st.expander("📋 Prévia dos dados", expanded=True):
                st.dataframe(df.head(10), use_container_width=True)
            
            mapa_colunas = detectar_colunas_informacoes(df)
            
            with st.expander("🔍 Mapeamento de colunas detectado"):
                for campo, coluna in mapa_colunas.items():
                    if isinstance(coluna, list):
                        st.write(f"- **{campo}** → {', '.join(coluna)}")
                    else:
                        st.write(f"- **{campo}** → '{coluna}'")
            
            if 'condominio' not in mapa_colunas:
                st.error("❌ Coluna 'CONDOMÍNIO' não encontrada na planilha!")
                st.write("Colunas disponíveis:", list(df.columns))
                return
            
            st.divider()
            st.subheader("🔗 Preview do Matching")
            
            collection = get_condominios_collection()
            matching_preview = []
            
            amostra = df.head(20)
            for idx, row in amostra.iterrows():
                nome_planilha = str(row[mapa_colunas.get('condominio', 'CONDOMÍNIO')]).strip()
                zona = str(row[mapa_colunas.get('zona', 'ZONA')]).strip() if mapa_colunas.get('zona') else ""
                
                match = encontrar_match_condominio(nome_planilha, zona, collection)
                
                if match:
                    score = match.get('_score', 0)
                    status = "✅ Match"
                    if score >= 90:
                        confianca = "🟢 Alta"
                    elif score >= 70:
                        confianca = "🟡 Média"
                    else:
                        confianca = "🟠 Baixa"
                else:
                    score = 0
                    status = "❌ Sem match"
                    confianca = "🔴 Nenhum"
                
                matching_preview.append({
                    "Nome na Planilha": nome_planilha[:35],
                    "Zona": zona,
                    "Match no CRM": match.get('nome', '❌ NÃO ENCONTRADO')[:35] if match else "❌ NÃO ENCONTRADO",
                    "ID IXC": match.get('id_ixc', 'N/A') if match else "N/A",
                    "Confiança": f"{score}%",
                    "Status": status,
                    "Nível": confianca
                })
            
            df_preview = pd.DataFrame(matching_preview)
            st.dataframe(df_preview, use_container_width=True)
            
            total = len(matching_preview)
            encontrados = sum(1 for m in matching_preview if m["Status"] == "✅ Match")
            
            col1, col2, col3 = st.columns(3)
            with col1:
                st.metric("Total na amostra", total)
            with col2:
                st.metric("Match encontrado", encontrados)
            with col3:
                taxa = (encontrados / total * 100) if total > 0 else 0
                st.metric("Taxa de acerto", f"{taxa:.1f}%")
            
            st.divider()
            st.warning("⚠️ Ao importar, as informações existentes serão **ATUALIZADAS** ou **CRIADAS** para cada condomínio.")
            
            if st.button("🚀 Importar Informações", type="primary"):
                with st.spinner("🔄 Processando importação..."):
                    resultado = importar_informacoes_completas(df, mapa_colunas, collection)
                    
                    if resultado.get("erro"):
                        st.error(f"❌ {resultado['erro']}")
                    else:
                        col1, col2, col3, col4, col5 = st.columns(5)
                        with col1:
                            st.metric("📊 Total", resultado['total'])
                        with col2:
                            st.metric("✅ Matches", resultado['matches'])
                        with col3:
                            st.metric("🔄 Atualizados", resultado['atualizados'])
                        with col4:
                            st.metric("🆕 Criados", resultado['criados'])
                        with col5:
                            st.metric("❌ Sem match", resultado['sem_match'])
                        
                        if resultado.get('detalhes'):
                            with st.expander("📋 Detalhes da Importação", expanded=True):
                                for item in resultado['detalhes'][:30]:
                                    if item['status'] == 'match':
                                        st.success(f"✅ **{item['nome_planilha']}** → **{item['nome_crm']}** (Score: {item['score']}%)")
                                        st.write(f"   🔄 {item.get('detalhes', 'Atualizado')}")
                                    elif item['status'] == 'criado':
                                        st.info(f"🆕 **{item['nome_planilha']}** - Novo condomínio criado")
                                    elif item['status'] == 'sem_match':
                                        st.warning(f"⚠️ **{item['nome_planilha']}** - {item.get('detalhes', 'Sem match')}")
                                    else:
                                        st.error(f"❌ **{item['nome_planilha']}** - {item.get('detalhes', 'Erro')}")
                                
                                if len(resultado['detalhes']) > 30:
                                    st.info(f"... e mais {len(resultado['detalhes']) - 30} registros")
                        
                        st.balloons()
        
        except Exception as e:
            st.error(f"❌ Erro ao processar arquivo: {e}")
            import traceback
            st.code(traceback.format_exc())

def render_lista_edicao_condominios():
    """Lista todos os condomínios com expanders para edição"""
    st.subheader("✏️ Editar Informações dos Condomínios")
    
    collection = get_condominios_collection()
    condominios = list(collection.find().sort("nome", 1))
    
    if not condominios:
        st.info("Nenhum condomínio cadastrado.")
        return
    
    # Filtros
    col1, col2 = st.columns(2)
    with col1:
        zona_filter = st.selectbox(
            "Filtrar por Zona",
            ["Todas"] + OPCOES_ZONA[1:],
            key="filtro_zona_edicao"
        )
    with col2:
        status_filter = st.selectbox(
            "Filtrar por Status",
            ["Todos", "Com Informações", "Sem Informações"],
            key="filtro_status_edicao"
        )
    
    # Aplicar filtros
    condominios_filtrados = condominios.copy()
    if zona_filter != "Todas":
        condominios_filtrados = [c for c in condominios_filtrados if c.get("zona") == zona_filter]
    
    if status_filter == "Com Informações":
        condominios_filtrados = [c for c in condominios_filtrados if c.get("informacoes_detalhadas")]
    elif status_filter == "Sem Informações":
        condominios_filtrados = [c for c in condominios_filtrados if not c.get("informacoes_detalhadas")]
    
    # Estatísticas
    st.caption(f"📌 {len(condominios_filtrados)} condomínios encontrados")
    
    # Verificar se veio de um clique em "Editar" no dashboard
    cond_selecionado_id = st.session_state.get('cond_info_edit', None)
    
    # Lista com expanders
    for idx, cond in enumerate(condominios_filtrados):
        # Determinar status
        info = cond.get("informacoes_detalhadas", {})
        has_info = bool(info)
        
        # Ícone de status
        status_icon = "✅" if has_info else "⚠️"
        status_text = "Com informações" if has_info else "Sem informações"
        
        # Nome do expander
        expander_label = f"{status_icon} {cond.get('nome', 'N/A')} - {cond.get('zona', 'N/A')} - {status_text}"
        
        # Verificar se deve estar expandido
        is_expanded = (str(cond['_id']) == cond_selecionado_id)
        
        with st.expander(expander_label, expanded=is_expanded):
            # Cabeçalho do condomínio
            col1, col2, col3 = st.columns([3, 1, 1])
            with col1:
                st.markdown(f"### 🏢 {cond.get('nome', 'N/A')}")
                st.caption(f"📍 Zona: {cond.get('zona', 'N/A')} | ID IXC: {cond.get('id_ixc', 'N/A')}")
            with col2:
                # Botão para limpar informações (FORA do form)
                if has_info:
                    if st.button("🗑️ Limpar", key=f"clear_{cond['_id']}"):
                        collection.update_one(
                            {"_id": cond['_id']},
                            {"$unset": {"informacoes_detalhadas": ""}}
                        )
                        # Limpar session_state
                        for key in [f'itens_placas_{cond["_id"]}', f'itens_doacoes_{cond["_id"]}', f'contatos_{cond["_id"]}']:
                            if key in st.session_state:
                                del st.session_state[key]
                        st.success("Informações removidas!")
                        st.rerun()
            with col3:
                # Botão para ver resumo
                if has_info:
                    if st.button("📋 Resumo", key=f"resumo_{cond['_id']}"):
                        st.session_state[f'resumo_{cond["_id"]}'] = not st.session_state.get(f'resumo_{cond["_id"]}', False)
            
            # Mostrar resumo se solicitado
            if has_info and st.session_state.get(f'resumo_{cond["_id"]}', False):
                with st.container(border=True):
                    # Pontos de internet
                    pontos = info.get("pontos_internet", {})
                    if pontos and pontos.get("quantidade", 0) > 0:
                        st.write(f"📶 **{pontos.get('quantidade')}** pontos de internet")
                        if pontos.get("locais"):
                            st.write(f"   Locais: {', '.join(pontos.get('locais', []))}")
                        if pontos.get("observacao"):
                            st.write(f"   Obs: {pontos.get('observacao')}")
                    
                    # Placas
                    placas = info.get("placas_fotos", {})
                    itens_placas = placas.get("itens", [])
                    if itens_placas:
                        st.write(f"🪧 **{len(itens_placas)}** itens de placa")
                        for item in itens_placas:
                            st.write(f"   - {item.get('tipo')}: {item.get('quantidade')}x ({item.get('local', 'N/A')})")
                    
                    # Doações
                    doacoes = info.get("doacoes", {})
                    total_doacoes = doacoes.get("total_doacoes", 0)
                    if total_doacoes > 0:
                        st.write(f"🎁 **R$ {total_doacoes:,.2f}** em doações")
                        for item in doacoes.get("itens", []):
                            st.write(f"   - {item.get('item')}: R$ {item.get('valor', 0):,.2f}")
                    
                    # Contatos
                    contatos = info.get("contatos", [])
                    if contatos:
                        st.write(f"👥 **{len(contatos)}** contatos")
                        for contato in contatos:
                            st.write(f"   - {contato.get('nome')} ({contato.get('funcao', 'N/A')})")
                    
                    # Data atualização
                    data_atualizacao = cond.get("ultima_atualizacao_informacoes")
                    if data_atualizacao:
                        st.caption(f"🔄 Última atualização: {data_atualizacao.strftime('%d/%m/%Y %H:%M')}")
            
            # ========== FORMULÁRIO DE EDIÇÃO ==========
            st.markdown("---")
            st.markdown("### ✏️ Editar Informações")
            
            # Preparar dados do formulário
            info = cond.get("informacoes_detalhadas", {})
            
            # Inicializar session_state para este condomínio
            if f'itens_placas_{cond["_id"]}' not in st.session_state:
                st.session_state[f'itens_placas_{cond["_id"]}'] = info.get("placas_fotos", {}).get("itens", [])
            
            if f'itens_doacoes_{cond["_id"]}' not in st.session_state:
                st.session_state[f'itens_doacoes_{cond["_id"]}'] = info.get("doacoes", {}).get("itens", [])
            
            if f'contatos_{cond["_id"]}' not in st.session_state:
                st.session_state[f'contatos_{cond["_id"]}'] = info.get("contatos", [])
            
            # Botões de adicionar (FORA do form)
            col1, col2, col3 = st.columns(3)
            with col1:
                if st.button("➕ Adicionar Placa", key=f"add_placa_{cond['_id']}"):
                    st.session_state[f'itens_placas_{cond["_id"]}'].append({
                        "tipo": "Cavalete",
                        "quantidade": 1,
                        "local": "",
                        "observacao": ""
                    })
                    st.rerun()
            
            with col2:
                if st.button("➕ Adicionar Doação", key=f"add_doacao_{cond['_id']}"):
                    st.session_state[f'itens_doacoes_{cond["_id"]}'].append({
                        "item": "",
                        "quantidade": 1,
                        "valor": 0.00,
                        "forma_pagamento": "Pix",
                        "observacao": ""
                    })
                    st.rerun()
            
            with col3:
                if st.button("➕ Adicionar Contato", key=f"add_contato_{cond['_id']}"):
                    st.session_state[f'contatos_{cond["_id"]}'].append({
                        "nome": "",
                        "telefone": "",
                        "funcao": "Outro",
                        "observacao": ""
                    })
                    st.rerun()
            
            st.markdown("---")
            
            # ========== FORMULÁRIO ==========
            with st.form(f"form_info_{cond['_id']}"):
                # PONTOS DE INTERNET
                st.subheader("📶 Pontos de Internet")
                
                pontos_info = info.get("pontos_internet", {})
                quantidade_pontos = pontos_info.get("quantidade", 0)
                locais_existentes = pontos_info.get("locais", [])
                
                qtd_pontos = st.number_input(
                    "Quantidade de pontos",
                    min_value=0,
                    max_value=20,
                    value=quantidade_pontos,
                    key=f"qtd_pontos_{cond['_id']}"
                )
                
                st.markdown("**Locais com pontos de internet:**")
                col1, col2, col3 = st.columns(3)
                locais_selecionados = []
                
                for i, local in enumerate(LOCAIS_PONTOS):
                    with col1 if i % 3 == 0 else col2 if i % 3 == 1 else col3:
                        if st.checkbox(
                            local,
                            value=local in locais_existentes,
                            key=f"ponto_{cond['_id']}_{i}"
                        ):
                            locais_selecionados.append(local)
                
                obs_pontos = st.text_area(
                    "Observações sobre os Pontos de Internet",
                    value=pontos_info.get("observacao", ""),
                    placeholder="Ex: 02 (Adm e portaria) + 02 (salão de jogos e coworking)",
                    key=f"obs_pontos_{cond['_id']}"
                )
                
                st.divider()
                
                # PLACAS E FOTOS
                st.subheader("🪧 Placas e Fotos")
                
                itens_atuais = st.session_state.get(f'itens_placas_{cond["_id"]}', [])
                
                st.caption(f"📌 {len(itens_atuais)} itens de placa cadastrados")
                
                for idx_item, item in enumerate(itens_atuais):
                    with st.container(border=True):
                        col1, col2, col3, col4 = st.columns([2, 1, 2, 1])
                        with col1:
                            tipo_atual = item.get("tipo", "Cavalete")
                            item["tipo"] = st.selectbox(
                                f"Tipo {idx_item+1}",
                                options=TIPOS_PLACA,
                                index=TIPOS_PLACA.index(tipo_atual) if tipo_atual in TIPOS_PLACA else 0,
                                key=f"tipo_placa_{cond['_id']}_{idx_item}"
                            )
                        
                        with col2:
                            item["quantidade"] = st.number_input(
                                "Qtd",
                                min_value=0,
                                max_value=10,
                                value=int(item.get("quantidade", 1)),
                                key=f"qtd_placa_{cond['_id']}_{idx_item}"
                            )
                        
                        with col3:
                            item["local"] = st.text_input(
                                "Local",
                                value=item.get("local", ""),
                                placeholder="Ex: Portaria",
                                key=f"local_placa_{cond['_id']}_{idx_item}"
                            )
                        
                        with col4:
                            if st.button("🗑️", key=f"del_placa_{cond['_id']}_{idx_item}"):
                                itens_atuais.pop(idx_item)
                                st.session_state[f'itens_placas_{cond["_id"]}'] = itens_atuais
                                st.rerun()
                
                obs_placas = st.text_area(
                    "Observações sobre Placas/Fotos",
                    value=info.get("placas_fotos", {}).get("observacao", ""),
                    placeholder="Ex: 01 cavalete + 03 Placas",
                    key=f"obs_placas_{cond['_id']}"
                )
                
                st.divider()
                
                # DOAÇÕES
                st.subheader("🎁 Doações")
                
                itens_doacoes_atuais = st.session_state.get(f'itens_doacoes_{cond["_id"]}', [])
                
                st.caption(f"📌 {len(itens_doacoes_atuais)} doações cadastradas")
                
                for idx_item, doacao in enumerate(itens_doacoes_atuais):
                    with st.container(border=True):
                        col1, col2, col3, col4 = st.columns([2, 1, 1, 1])
                        with col1:
                            doacao["item"] = st.text_input(
                                f"Doação {idx_item+1} - Item",
                                value=doacao.get("item", ""),
                                placeholder="Ex: Notebook Dell",
                                key=f"item_doacao_{cond['_id']}_{idx_item}"
                            )
                        
                        with col2:
                            doacao["quantidade"] = st.number_input(
                                "Qtd",
                                min_value=1,
                                value=int(doacao.get("quantidade", 1)),
                                key=f"qtd_doacao_{cond['_id']}_{idx_item}"
                            )
                        
                        with col3:
                            doacao["valor"] = st.number_input(
                                "Valor (R$)",
                                min_value=0.00,
                                value=float(doacao.get("valor", 0.00)),
                                step=0.01,
                                key=f"valor_doacao_{cond['_id']}_{idx_item}"
                            )
                        
                        with col4:
                            if st.button("🗑️", key=f"del_doacao_{cond['_id']}_{idx_item}"):
                                itens_doacoes_atuais.pop(idx_item)
                                st.session_state[f'itens_doacoes_{cond["_id"]}'] = itens_doacoes_atuais
                                st.rerun()
                        
                        col5, col6 = st.columns([2, 1])
                        with col5:
                            doacao["forma_pagamento"] = st.selectbox(
                                "Forma de Pagamento",
                                options=FORMAS_PAGAMENTO,
                                index=FORMAS_PAGAMENTO.index(doacao.get("forma_pagamento", "Pix")) if doacao.get("forma_pagamento") in FORMAS_PAGAMENTO else 0,
                                key=f"forma_doacao_{cond['_id']}_{idx_item}"
                            )
                        
                        with col6:
                            doacao["observacao"] = st.text_input(
                                "Obs",
                                value=doacao.get("observacao", ""),
                                placeholder="Obs",
                                key=f"obs_doacao_{cond['_id']}_{idx_item}"
                            )
                
                obs_doacoes = st.text_area(
                    "Observações sobre Doações",
                    value=info.get("doacoes", {}).get("observacao", ""),
                    placeholder="Ex: 01 Notebook Dell: 2.399,00 (Pix)",
                    key=f"obs_doacoes_{cond['_id']}"
                )
                
                st.divider()
                
                # CONTATOS
                st.subheader("👥 Contatos")
                
                contatos_atuais = st.session_state.get(f'contatos_{cond["_id"]}', [])
                
                st.caption(f"📌 {len(contatos_atuais)} contatos cadastrados")
                
                for idx_item, contato in enumerate(contatos_atuais):
                    with st.container(border=True):
                        col1, col2, col3, col4 = st.columns([2, 1, 1, 1])
                        with col1:
                            contato["nome"] = st.text_input(
                                f"Contato {idx_item+1} - Nome",
                                value=contato.get("nome", ""),
                                placeholder="Nome completo",
                                key=f"nome_contato_{cond['_id']}_{idx_item}"
                            )
                        
                        with col2:
                            contato["telefone"] = st.text_input(
                                "Telefone",
                                value=contato.get("telefone", ""),
                                placeholder="(00) 00000-0000",
                                key=f"tel_contato_{cond['_id']}_{idx_item}"
                            )
                        
                        with col3:
                            contato["funcao"] = st.selectbox(
                                "Função",
                                options=FUNCOES_CONTATO,
                                index=FUNCOES_CONTATO.index(contato.get("funcao", "Outro")) if contato.get("funcao") in FUNCOES_CONTATO else 0,
                                key=f"funcao_contato_{cond['_id']}_{idx_item}"
                            )
                        
                        with col4:
                            if st.button("🗑️", key=f"del_contato_{cond['_id']}_{idx_item}"):
                                contatos_atuais.pop(idx_item)
                                st.session_state[f'contatos_{cond["_id"]}'] = contatos_atuais
                                st.rerun()
                
                # OBSERVAÇÕES GERAIS
                st.subheader("📝 Observações Gerais")
                
                observacoes_gerais = st.text_area(
                    "Observações",
                    value=info.get("observacoes", ""),
                    placeholder="Informações adicionais sobre o condomínio...",
                    key=f"obs_gerais_{cond['_id']}",
                    height=100
                )
                
                # PARCEIROS
                st.subheader("🤝 Parceiros")
                
                parceiros = info.get("parceiros", [])
                parceiros_text = st.text_input(
                    "Parceiros (separados por vírgula)",
                    value=", ".join(parceiros) if parceiros else "",
                    placeholder="Ex: Morador João Silva, Empresa X",
                    key=f"parceiros_{cond['_id']}"
                )
                
                st.divider()
                
                if st.form_submit_button("💾 Salvar Informações", type="primary"):
                    # Montar dados
                    nova_info = {
                        "pontos_internet": {
                            "quantidade": qtd_pontos,
                            "locais": locais_selecionados,
                            "observacao": obs_pontos
                        },
                        "placas_fotos": {
                            "itens": itens_atuais,
                            "observacao": obs_placas
                        },
                        "doacoes": {
                            "itens": itens_doacoes_atuais,
                            "observacao": obs_doacoes,
                            "total_doacoes": sum(item.get("valor", 0) * item.get("quantidade", 1) for item in itens_doacoes_atuais)
                        },
                        "contatos": contatos_atuais,
                        "observacoes": observacoes_gerais,
                        "parceiros": [p.strip() for p in parceiros_text.split(",") if p.strip()] if parceiros_text else [],
                        "data_ultima_edicao": datetime.now()
                    }
                    
                    # Atualizar no banco
                    collection.update_one(
                        {"_id": cond['_id']},
                        {"$set": {
                            "informacoes_detalhadas": nova_info,
                            "ultima_atualizacao_informacoes": datetime.now()
                        }}
                    )
                    
                    # Limpar session_state
                    for key in [f'itens_placas_{cond["_id"]}', f'itens_doacoes_{cond["_id"]}', f'contatos_{cond["_id"]}']:
                        if key in st.session_state:
                            del st.session_state[key]
                    
                    # Remover flag de edição
                    if 'cond_info_edit' in st.session_state:
                        del st.session_state['cond_info_edit']
                    
                    st.success(f"✅ Informações de '{cond['nome']}' atualizadas com sucesso!")
                    st.balloons()
                    st.rerun()
