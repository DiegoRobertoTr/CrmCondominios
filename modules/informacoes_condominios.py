# modules/informacoes_condominios.py
"""
Módulo de Informações Detalhadas dos Condomínios - VERSÃO OTIMIZADA + PARSER INF.XLSX
Gerencia: Pontos de Internet, Placas/Fotos, Doações, Contatos, etc.

OTIMIZAÇÕES APLICADAS:
✅ Índice pré-carregado de condomínios (elimina N+1 no matching)
✅ Cache cirúrgico com versionamento (sem st.cache_data.clear() global)
✅ Projeções em todas as queries
✅ Bulk write na importação
✅ Memoização de normalização de nomes
✅ rapidfuzz (fallback para fuzzywuzzy)
✅ Índices MongoDB (nome, zona, id_ixc)
✅ Removidos form_submit_button("🗑️") de dentro de forms (bug fix)

PARSER ESPECIALIZADO Inf.xlsx:
✅ Mapeamento de siglas de zona (ZN → Zona Norte, etc.)
✅ Limpeza de nomes de condomínios (remove "(EM ANDAMENTO)", "- PREV. NOV.")
✅ Detecção das 3 colunas "CONTATO 1" duplicadas (Síndico/Preposto/Subsíndico)
✅ Parser de placas com múltiplos eventos históricos (data, tipo, responsável, status)
✅ Parser de doações com múltiplos formatos (1.234,56 / 3K / "Split + Notebook")
✅ Parser de parceiros com nome + função + isenção
✅ Flag "precisa_revisao" + motivos salvos no MongoDB
✅ Preview + relatório de qualidade exportável
"""

import streamlit as st
import pandas as pd
from datetime import datetime
import re
import io
from functools import lru_cache

# OTIMIZAÇÃO: usar rapidfuzz se disponível
try:
    from rapidfuzz import fuzz, process
    _HAS_RAPIDFUZZ = True
except ImportError:
    from fuzzywuzzy import fuzz, process
    _HAS_RAPIDFUZZ = False

try:
    from unidecode import unidecode
except ImportError:
    def unidecode(s):
        return s

try:
    from pymongo import UpdateOne, InsertOne
except ImportError:
    UpdateOne = None
    InsertOne = None

from modules.condominios import get_condominios_collection, OPCOES_ZONA


# ============================================================================
# CONSTANTES
# ============================================================================

TIPOS_PLACA = [
    "Cavalete", "Placa de Metal", "Windbanner", "Porta Panfleto",
    "Adesivo", "Banner", "Painel LED", "Outro"
]

LOCAIS_PONTOS = [
    "Portaria", "ADM", "Salão de Festas", "Salão de Jogos", "Academia",
    "Churrasqueira", "Coworking", "Lavanderia", "Espaço Gourmet", "Rooftop",
    "Área de Lazer", "Carregador Veicular", "Espaço Baby", "Espaço Teen",
    "Espaço Zen", "Outros"
]

FORMAS_PAGAMENTO = ["Pix", "Cartão", "Boleto", "Transferência", "Dinheiro", "Outro"]
FUNCOES_CONTATO = ["Síndico", "Subsíndico", "Administrador", "Preposto",
                   "Porteiro", "Zelador", "Outro"]

# ---------------------------------------------------------------------------
# MAPEAMENTO DE ZONAS (sigla → nome completo) - para a planilha Inf.xlsx
# ---------------------------------------------------------------------------
MAPA_ZONAS_SIGLA = {
    "ZN": "Zona Norte",
    "ZS": "Zona Sul",
    "ZO": "Zona Oeste",
    "SO": "Zona Sudoeste",
    "C":  "Centro",
    "BXD": "Baixada Fluminense",
    "N":  "Niterói",
}

# Palavras a remover na normalização de nomes
_PALAVRAS_REMOVER = [
    "CONDOMINIO", "CONDOMÍNIO", "RESIDENCIAL", "RESIDENCE",
    "CLUBE", "PARK", "LIVING", "VIVAZ", "VIVA", "VIVER",
    "ALTO", "NOVO", "NOVA", "RECANTO", "PARQUE", "JARDIM",
    "VILLAGIO", "SPAZIO", "URBAN", "PORTO", "ORLA"
]


# ============================================================================
# CACHE VERSIONADO
# ============================================================================

def _get_cache_version(key: str) -> int:
    session_key = f"info_cache_v_{key}"
    if session_key not in st.session_state:
        st.session_state[session_key] = 0
    return st.session_state[session_key]


def invalidar_cache(key: str):
    session_key = f"info_cache_v_{key}"
    st.session_state[session_key] = st.session_state.get(session_key, 0) + 1


# ============================================================================
# ÍNDICES MONGODB (executa 1x)
# ============================================================================

@st.cache_resource(show_spinner=False)
def _init_indices():
    collection = get_condominios_collection()
    try:
        collection.create_index("nome", name="idx_nome", background=True)
        collection.create_index("zona", name="idx_zona", background=True)
        collection.create_index("id_ixc", name="idx_id_ixc", background=True, sparse=True)
    except Exception:
        pass
    return True


# ============================================================================
# CACHE DE LEITURA
# ============================================================================

@st.cache_data(ttl=300, show_spinner=False)
def get_all_condominios_com_info(version: int = 0):
    _init_indices()
    collection = get_condominios_collection()
    return list(collection.find(
        {},
        {"nome": 1, "zona": 1, "id_ixc": 1, "informacoes_detalhadas": 1,
         "ultima_atualizacao_informacoes": 1}
    ).sort("nome", 1))


@st.cache_data(ttl=300, show_spinner=False)
def get_condominios_filtrados(zona=None, status=None, version: int = 0):
    collection = get_condominios_collection()
    query = {}
    if zona and zona != "Todas":
        query["zona"] = zona
    if status == "Com Informações":
        query["informacoes_detalhadas"] = {"$exists": True}
    elif status == "Sem Informações":
        query["informacoes_detalhadas"] = {"$exists": False}
    return list(collection.find(
        query,
        {"nome": 1, "zona": 1, "id_ixc": 1, "informacoes_detalhadas": 1,
         "ultima_atualizacao_informacoes": 1}
    ).sort("nome", 1))


@st.cache_data(ttl=300, show_spinner=False)
def get_dashboard_stats(version: int = 0):
    collection = get_condominios_collection()
    total = collection.estimated_document_count()
    com_info = collection.count_documents({"informacoes_detalhadas": {"$exists": True}})
    zonas = list(collection.aggregate([
        {"$group": {"_id": "$zona", "count": {"$sum": 1}}},
        {"$sort": {"count": -1}}
    ]))
    return {"total": total, "com_info": com_info,
            "sem_info": total - com_info, "zonas": zonas}


@st.cache_data(ttl=600, show_spinner=False)
def _get_indice_condominios(version: int = 0):
    """Índice pré-carregado para matching O(1)"""
    _init_indices()
    collection = get_condominios_collection()
    docs = list(collection.find({}, {"nome": 1, "zona": 1, "id_ixc": 1}))
    
    por_id_ixc = {}
    por_nome_normalizado = {}
    nomes_normalizados = []
    conds_por_nome_norm = {}
    
    for c in docs:
        if c.get("id_ixc"):
            por_id_ixc[str(c["id_ixc"])] = c
        norm = _normalizar_nome_cached(c.get("nome", ""))
        if norm:
            if norm not in por_nome_normalizado:
                por_nome_normalizado[norm] = c
            nomes_normalizados.append(norm)
            conds_por_nome_norm[norm] = c
    
    return {
        "por_id_ixc": por_id_ixc,
        "por_nome_normalizado": por_nome_normalizado,
        "nomes_normalizados": nomes_normalizados,
        "conds_por_nome_norm": conds_por_nome_norm,
        "todos": docs
    }


# ============================================================================
# NORMALIZAÇÃO MEMOIZADA
# ============================================================================

@lru_cache(maxsize=2048)
def _normalizar_nome_cached(nome: str) -> str:
    if not nome:
        return ""
    nome = unidecode(str(nome).upper().strip())
    for palavra in _PALAVRAS_REMOVER:
        nome = nome.replace(palavra, "").strip()
    nome = re.sub(r'\s+', ' ', nome)
    return nome.strip()


def normalizar_nome_condominio(nome):
    return _normalizar_nome_cached(nome)


# ============================================================================
# MATCHING OTIMIZADO
# ============================================================================

def encontrar_match_condominio_otimizado(nome_planilha, zona, indice):
    if not nome_planilha:
        return None
    
    # Estratégia 1: ID IXC
    id_match = re.search(r'ID:(\d+)', str(nome_planilha))
    if id_match:
        cond = indice["por_id_ixc"].get(id_match.group(1))
        if cond:
            return {**cond, "_score": 100}
    
    nome_normalizado = normalizar_nome_condominio(nome_planilha)
    if not nome_normalizado:
        return None
    
    # Estratégia 2: match exato
    cond = indice["por_nome_normalizado"].get(nome_normalizado)
    if cond:
        return {**cond, "_score": 100}
    
    # Estratégia 3: substring
    melhor_substring = None
    melhor_score_sub = 0
    for nome_crm_norm, cond in indice["conds_por_nome_norm"].items():
        if nome_normalizado in nome_crm_norm or nome_crm_norm in nome_normalizado:
            score = 85 if (zona and cond.get('zona') == zona) else 70
            if score > melhor_score_sub:
                melhor_score_sub = score
                melhor_substring = cond
    if melhor_substring and melhor_score_sub >= 85:
        return {**melhor_substring, "_score": melhor_score_sub}
    
    # Estratégia 4: fuzzy
    if indice["nomes_normalizados"]:
        matches = process.extract(
            nome_normalizado, indice["nomes_normalizados"],
            scorer=fuzz.token_sort_ratio, limit=5
        )
        for match_nome, match_score, _ in matches:
            if match_score >= 70:
                cond = indice["conds_por_nome_norm"].get(match_nome)
                if cond:
                    score_final = match_score + 10 if (zona and cond.get('zona') == zona) else match_score
                    return {**cond, "_score": score_final}
    
    # Estratégia 5: 2 primeiras palavras
    palavras = nome_normalizado.split()
    if len(palavras) > 1:
        chave = " ".join(palavras[:2])
        for nome_crm_norm, cond in indice["conds_por_nome_norm"].items():
            if chave in nome_crm_norm:
                return {**cond, "_score": 60}
    
    if melhor_substring:
        return {**melhor_substring, "_score": melhor_score_sub}
    
    return None


def encontrar_match_condominio(nome_planilha, zona, collection):
    """Wrapper de compatibilidade"""
    version = _get_cache_version("indice")
    indice = _get_indice_condominios(version)
    return encontrar_match_condominio_otimizado(nome_planilha, zona, indice)


# ============================================================================
# ▓▓▓ PARSERS ESPECIALIZADOS INF.XLSX ▓▓▓
# ============================================================================

# ---------------------------------------------------------------------------
# ZONAS
# ---------------------------------------------------------------------------
def normalizar_zona(zona_bruta: str) -> str:
    if not zona_bruta:
        return ""
    z = str(zona_bruta).strip().upper()
    return MAPA_ZONAS_SIGLA.get(z, z)


# ---------------------------------------------------------------------------
# LIMPEZA DE NOME DO CONDOMÍNIO
# ---------------------------------------------------------------------------
_PADROES_LIMPEZA_NOME = [
    r'\(EM ANDAMENTO\)',
    r'\(CABEADO\)',
    r'\(AGUARDANDO INÍCIO\)',
    r'\(AGUARDANDO INICIO\)',
    r'\s*-\s*PREV\.?\s*[A-Z]+\.?\s*\d*\s*$',
]


def limpar_nome_condominio(nome_bruto: str):
    """Retorna (nome_limpo, anotacoes_extraidas)"""
    if not nome_bruto:
        return "", ""
    nome = str(nome_bruto).strip()
    anotacoes = []
    for padrao in _PADROES_LIMPEZA_NOME:
        matches = re.findall(padrao, nome, flags=re.IGNORECASE)
        for m in matches:
            anotacoes.append(m.strip())
        nome = re.sub(padrao, '', nome, flags=re.IGNORECASE).strip()
    nome = re.sub(r'\s*-\s*$', '', nome)
    nome = re.sub(r'\s+', ' ', nome).strip()
    return nome, " | ".join(anotacoes)


# ---------------------------------------------------------------------------
# PONTOS DE INTERNET
# ---------------------------------------------------------------------------
_LOCAIS_NORMALIZADOS = {
    'adm': 'ADM', 'administracao': 'ADM', 'administração': 'ADM',
    'portaria': 'Portaria',
    'salão': 'Salão de Festas', 'salao': 'Salão de Festas',
    'salão de festas': 'Salão de Festas', 'salao de festas': 'Salão de Festas',
    'salão de jogos': 'Salão de Jogos', 'salao de jogos': 'Salão de Jogos',
    'academia': 'Academia',
    'churrasqueira': 'Churrasqueira',
    'coworking': 'Coworking',
    'lavanderia': 'Lavanderia',
    'rooftop': 'Rooftop',
    'carregador': 'Carregador Veicular',
    'carregador veicular': 'Carregador Veicular',
    'espaço gourmet': 'Espaço Gourmet', 'espaco gourmet': 'Espaço Gourmet',
    'espaço teen': 'Espaço Teen',
    'espaço baby': 'Espaço Baby',
    'espaço zen': 'Espaço Zen',
    'brinquedoteca': 'Brinquedoteca',
    'sala de estudos': 'Sala de Estudos',
    'sala de telecom': 'Sala de Telecom',
    'rack central': 'Rack Central',
    'cftv': 'CFTV',
    'lixeira': 'Lixeira',
    'armário inteligente': 'Armário Inteligente',
    'medidor': 'Medidor',
    'casa de bomba': 'Casa de Bomba',
    'cofre': 'Cofre',
    'área gourmet': 'Espaço Gourmet',
    'sl samba': 'Salão Samba',
    'sala home': 'Sala Home',
    'área de lazer': 'Área de Lazer',
}


def _normalizar_local(local_bruto: str) -> str:
    if not local_bruto:
        return ""
    key = local_bruto.strip().lower()
    return _LOCAIS_NORMALIZADOS.get(key, local_bruto.strip().title())


def parse_pontos_internet_avancado(texto) -> dict:
    """Parser robusto para PONTOS INTERNET"""
    if pd.isna(texto) or not texto:
        return {"quantidade": 0, "locais": [], "observacao": "",
                "tem_pontos": False}
    
    texto_original = str(texto).strip()
    texto_lower = texto_original.lower()
    
    # Negativos
    negativos = ["sem ponto", "sem pontos", "não tem", "nao tem",
                 "não possui", "nao possui", "sem internet",
                 "não há", "nao ha"]
    if any(n in texto_lower for n in negativos):
        return {"quantidade": 0, "locais": [], "tem_pontos": False,
                "observacao": texto_original}
    
    locais = []
    quantidade_total = 0
    
    # Padrão 1: "NN (locais)"
    matches = re.findall(r'(\d+)\s*\(([^)]+)\)', texto_original)
    if matches:
        for qtd_str, locais_str in matches:
            try:
                qtd = int(qtd_str)
            except ValueError:
                qtd = 0
            quantidade_total += qtd
            for lb in re.split(r'\s*[,;]\s*|\s+e\s+', locais_str, flags=re.IGNORECASE):
                lb = lb.strip()
                if lb:
                    locais.append(_normalizar_local(lb))
    
    # Padrão 2: "NN-Local" ou "NN Local" (sem parênteses)
    if not matches:
        padrao_simples = r'(\d+)\s*[-–]?\s*([a-zA-ZÀ-ÿ][a-zA-ZÀ-ÿ\s,/]+?)(?=\s+\d|\s*$|\s*\+)'
        matches2 = re.findall(padrao_simples, texto_original)
        if matches2:
            for qtd_str, local_str in matches2:
                try:
                    qtd = int(qtd_str)
                except ValueError:
                    continue
                quantidade_total += qtd
                for lb in re.split(r'\s*[,;]\s*|\s+e\s+', local_str, flags=re.IGNORECASE):
                    lb = lb.strip()
                    if lb and len(lb) > 2:
                        locais.append(_normalizar_local(lb))
    
    # Padrão 3: só locais, sem número
    if not matches and quantidade_total == 0:
        for chave, valor in _LOCAIS_NORMALIZADOS.items():
            if chave in texto_lower and valor not in locais:
                locais.append(valor)
        if locais:
            quantidade_total = len(locais)
    
    locais = list(dict.fromkeys(locais))
    
    return {
        "quantidade": quantidade_total,
        "locais": locais,
        "tem_pontos": quantidade_total > 0,
        "observacao": texto_original
    }


# ---------------------------------------------------------------------------
# PLACAS (FOTOS) - múltiplos eventos
# ---------------------------------------------------------------------------
_KEYWORDS_PLACAS = {
    'cavalete': 'Cavalete',
    'windbanner': 'Windbanner',
    'wind banner': 'Windbanner',
    'plaquinha': 'Placa de Metal',
    'plaquinhas': 'Placa de Metal',
    'placa': 'Placa de Metal',
    'placas': 'Placa de Metal',
    'banner': 'Banner',
    'adesivo': 'Adesivo',
    'acrílico': 'Adesivo',
    'acrilico': 'Adesivo',
    'painel': 'Painel LED',
    'porta panfleto': 'Porta Panfleto',
    'folheto': 'Porta Panfleto',
}

_KEYWORDS_STATUS = {
    'retirado': 'RETIRADO',
    'removido': 'RETIRADO',
    'substituído': 'SUBSTITUÍDO',
    'substituido': 'SUBSTITUÍDO',
    'ok': 'OK',
    'colocado': 'COLOCADO',
    'sem autorização': 'SEM AUTORIZAÇÃO',
    'sem autorizacao': 'SEM AUTORIZAÇÃO',
    'não foi autorizado': 'SEM AUTORIZAÇÃO',
    'nao foi autorizado': 'SEM AUTORIZAÇÃO',
    'impedidos': 'IMPEDIDO',
    'sem placas': 'SEM PLACAS',
    'sem foto': 'SEM FOTO',
    'faltou foto': 'SEM FOTO',
    'trocar': 'TROCAR',
    'confirmar': 'CONFIRMAR',
    'instalar': 'INSTALAR',
    'pendência': 'PENDÊNCIA',
    'pendencia': 'PENDÊNCIA',
    'colocar': 'COLOCAR',
}


def _extrair_responsavel(texto: str) -> str:
    m = re.search(r'_([A-ZÀ-Ý][a-zA-ZÀ-ÿ]+)', texto)
    return m.group(1) if m else ""


def _extrair_status(texto: str):
    status = []
    t = texto.lower()
    for k, v in _KEYWORDS_STATUS.items():
        if k in t and v not in status:
            status.append(v)
    return status


def parse_placas_avancado(texto) -> dict:
    """Parser de PLACAS (FOTOS) com múltiplos eventos"""
    if pd.isna(texto) or not texto:
        return {"itens": [], "observacao": "", "eventos": [], "pendencias": ""}
    
    texto_original = str(texto).strip()
    texto_lower = texto_original.lower()
    
    # "Sem placas" / "Sem autorização" puro
    if any(k in texto_lower for k in ['sem placas', 'sem divulgação', 'sem divulgacao']):
        if not any(k in texto_lower for k in ['cavalete', 'placa', 'windbanner']):
            return {"itens": [], "eventos": [], "pendencias": "",
                    "observacao": texto_original}
    
    itens = []
    eventos = []
    pendencias = []
    
    # Dividir por datas
    partes = re.split(r'(\d{1,2}/\d{1,2}/\d{2,4})', texto_original)
    blocos = []
    if len(partes) > 1:
        if partes[0].strip():
            blocos.append((None, partes[0].strip()))
        for i in range(1, len(partes), 2):
            data = partes[i]
            corpo = partes[i + 1] if i + 1 < len(partes) else ""
            blocos.append((data, corpo.strip()))
    else:
        blocos.append((None, texto_original))
    
    for data, corpo in blocos:
        if not corpo:
            continue
        corpo_lower = corpo.lower()
        responsavel = _extrair_responsavel(corpo)
        status = _extrair_status(corpo)
        local_match = re.search(r'\(([^)]+)\)', corpo)
        local_extraido = local_match.group(1) if local_match else ""
        
        encontrou_tipo = False
        for chave, tipo in _KEYWORDS_PLACAS.items():
            if chave in corpo_lower:
                padrao = rf'(\d+)\s*{re.escape(chave)}'
                m = re.search(padrao, corpo_lower)
                qtd = int(m.group(1)) if m else 1
                itens.append({
                    "tipo": tipo, "quantidade": qtd, "local": local_extraido,
                    "data": data or "", "responsavel": responsavel,
                    "status": ", ".join(status) if status else "",
                    "observacao": ""
                })
                encontrou_tipo = True
        
        if encontrou_tipo:
            eventos.append({
                "data": data or "",
                "descricao": corpo[:200],
                "responsavel": responsavel,
                "status": ", ".join(status) if status else ""
            })
        
        if any(k in corpo_lower for k in ['trocar', 'instalar', 'confirmar',
                                            'colocar', 'pendência', 'pendencia',
                                            'faltou', 'faltando']):
            pendencias.append(corpo[:200])
    
    if not itens and texto_original.strip():
        if not any(k in texto_lower for k in ['sem placas', 'sem divulgação', 'sem divulgacao']):
            itens.append({
                "tipo": "Outro", "quantidade": 1, "local": "",
                "data": "", "responsavel": "", "status": "",
                "observacao": texto_original[:200]
            })
    
    return {
        "itens": itens,
        "eventos": eventos,
        "pendencias": " | ".join(pendencias),
        "observacao": texto_original
    }


# ---------------------------------------------------------------------------
# DOAÇÕES
# ---------------------------------------------------------------------------
_VALOR_REGEX = r'(\d{1,3}(?:\.\d{3})*(?:,\d{2})?|\d+(?:,\d{2})?)'


def _parse_valor_br(valor_str: str) -> float:
    if not valor_str:
        return 0.0
    limpo = str(valor_str).strip().replace('R$', '').strip()
    if ',' in limpo:
        limpo = limpo.replace('.', '').replace(',', '.')
    try:
        return float(limpo)
    except ValueError:
        return 0.0


def parse_doacoes_avancado(texto) -> dict:
    """Parser robusto de DOAÇÃO"""
    if pd.isna(texto) or not texto:
        return {"itens": [], "observacao": "", "total_doacoes": 0,
                "teve_doacao": False}
    
    texto_original = str(texto).strip()
    texto_lower = texto_original.lower()
    
    negativos = ['sem doações', 'sem doacoes', 'não houve', 'nao houve',
                 'não tem', 'nao tem', 'sem doação', 'sem doacao']
    if any(n in texto_lower for n in negativos) and not re.search(r'\d', texto_original):
        return {"itens": [], "observacao": texto_original,
                "total_doacoes": 0, "teve_doacao": False}
    
    itens = []
    
    # Padrão 1: "NN Item: VALOR (Forma)"
    padrao1 = rf'(\d+)\s*([^:]+?):\s*{_VALOR_REGEX}\s*(?:\(([^)]+)\))?'
    for qtd_str, item, valor_str, forma in re.findall(padrao1, texto_original, flags=re.IGNORECASE):
        valor = _parse_valor_br(valor_str)
        if valor > 0:
            itens.append({
                "item": item.strip(), "quantidade": int(qtd_str), "valor": valor,
                "forma_pagamento": (forma or "Não especificado").strip(),
                "observacao": ""
            })
    
    # Padrão 2: "Item: VALOR (Forma)"
    if not itens:
        padrao2 = rf'([A-Za-zÀ-ÿ][^:\d]{{2,60}}?):\s*{_VALOR_REGEX}\s*(?:\(([^)]+)\))?'
        for item, valor_str, forma in re.findall(padrao2, texto_original, flags=re.IGNORECASE):
            valor = _parse_valor_br(valor_str)
            if valor > 0:
                itens.append({
                    "item": item.strip(), "quantidade": 1, "valor": valor,
                    "forma_pagamento": (forma or "Não especificado").strip(),
                    "observacao": ""
                })
    
    # Padrão 3: "Doação de VALOR" / "Doação: VALOR"
    if not itens:
        padrao3 = rf'doa[çc][aã]o\s*(?:de|:)?\s*{_VALOR_REGEX}'
        for valor_str in re.findall(padrao3, texto_original, flags=re.IGNORECASE):
            valor = _parse_valor_br(valor_str)
            if valor > 0:
                itens.append({
                    "item": "Doação", "quantidade": 1, "valor": valor,
                    "forma_pagamento": "Não especificado", "observacao": ""
                })
    
    # Padrão 4: "3K" / "5K"
    if not itens:
        for num in re.findall(r'(\d+)\s*[Kk]\b', texto_original):
            itens.append({
                "item": "Doação", "quantidade": 1, "valor": int(num) * 1000,
                "forma_pagamento": "Não especificado",
                "observacao": f"Interpretado como {num}K"
            })
    
    # Padrão 5: valores soltos
    if not itens:
        for v in re.findall(_VALOR_REGEX, texto_original):
            valor = _parse_valor_br(v)
            if valor > 100:
                itens.append({
                    "item": "Doação", "quantidade": 1, "valor": valor,
                    "forma_pagamento": "Não especificado", "observacao": ""
                })
    
    # Itens sem valor (ex: "1 Split/ 1 Notebook")
    if not itens and re.search(r'\d+\s*[A-Za-z]', texto_original):
        for m in re.finditer(r'(\d+)\s+([A-Za-zÀ-ÿ][a-zA-ZÀ-ÿ\s]+?)(?=/|$|\+)', texto_original):
            itens.append({
                "item": m.group(2).strip(), "quantidade": int(m.group(1)),
                "valor": 0.0, "forma_pagamento": "A definir",
                "observacao": "Valor não informado"
            })
    
    total = sum(i.get("valor", 0) * i.get("quantidade", 1) for i in itens)
    
    return {
        "itens": itens,
        "observacao": texto_original,
        "total_doacoes": total,
        "teve_doacao": len(itens) > 0
    }


# ---------------------------------------------------------------------------
# PARCEIROS
# ---------------------------------------------------------------------------
def parse_parceiros_avancado(texto) -> list:
    if pd.isna(texto) or not texto:
        return []
    texto_original = str(texto).strip()
    t_lower = texto_original.lower().strip()
    
    if t_lower in ['não tem', 'nao tem', 'não', 'nao', 'nenhum',
                   'não há', 'nao ha', 'nenhum parceiro']:
        return []
    
    parceiros = []
    for parte in re.split(r'\s*\+\s*', texto_original):
        parte = parte.strip()
        if not parte or parte.lower() in ['não tem', 'nao tem']:
            continue
        m = re.match(r'^([^(]+?)(?:\s*\(([^)]+)\))?$', parte)
        if m:
            nome = m.group(1).strip()
            obs = m.group(2).strip() if m.group(2) else ""
            funcao = ""
            obs_lower = obs.lower()
            for f in ['síndico', 'sindico', 'subsíndico', 'subsindico',
                      'gestor', 'gestora', 'conselheir', 'administrador',
                      'zelador', 'porteiro', 'morador']:
                if f in obs_lower:
                    funcao = f.title()
                    break
            parceiros.append({"nome": nome, "funcao": funcao, "observacao": obs})
    return parceiros


# ---------------------------------------------------------------------------
# DETECÇÃO DE COLUNAS (com tratamento de duplicatas)
# ---------------------------------------------------------------------------
def detectar_colunas_informacoes_v2(df: pd.DataFrame) -> dict:
    """
    Detecta colunas considerando os nomes duplicados pelo pandas.
    Ex.: colunas 'CONTATO 1', 'CONTATO 1.1', 'CONTATO 1.2' na planilha Inf.xlsx
    são associadas a Síndico, Preposto, Subsíndico (nessa ordem).
    """
    mapa = {}
    colunas = list(df.columns)
    colunas_upper = {c.upper().strip(): c for c in colunas}
    
    mapa_direto = {
        'ZONA': 'zona',
        'CONDOMINIO': 'condominio', 'CONDOMÍNIO': 'condominio', 'NOME': 'condominio',
        'PONTOS INTERNET': 'pontos_internet', 'PONTOS_INTERNET': 'pontos_internet',
        'PLACAS (FOTOS)': 'placas_fotos', 'PLACAS FOTOS': 'placas_fotos',
        'PLACAS': 'placas_fotos',
        'DOACAO': 'doacao', 'DOAÇÃO': 'doacao',
        'PARCEIRO': 'parceiro',
        'SINDICO': 'sindico', 'SÍNDICO': 'sindico',
        'PREPOSTO': 'preposto',
        'SUBSINDICO': 'subsindico', 'SUBSÍNDICO': 'subsindico',
        'OBSERVACOES': 'observacoes', 'OBSERVAÇÕES': 'observacoes',
    }
    
    for col_upper, col_original in colunas_upper.items():
        if col_upper in mapa_direto:
            mapa[mapa_direto[col_upper]] = col_original
    
    # Colunas de contato duplicadas (por posição)
    contatos_cols = []
    for i, col in enumerate(colunas):
        cu = col.upper().strip()
        if cu.startswith('CONTATO'):
            contatos_cols.append((i, col))
    
    contatos_cols.sort(key=lambda x: x[0])
    funcoes_ordem = ['Síndico', 'Preposto', 'Subsíndico']
    for idx, (pos, col) in enumerate(contatos_cols):
        funcao = funcoes_ordem[idx] if idx < len(funcoes_ordem) else f"Contato {idx+1}"
        mapa[f'contato_telefone_{funcao.lower()}'] = col
    
    return mapa


# ---------------------------------------------------------------------------
# PROCESSAR UMA LINHA
# ---------------------------------------------------------------------------
def processar_linha_planilha(row: pd.Series, mapa: dict) -> dict:
    """Processa uma linha e retorna dict pronto para o MongoDB"""
    def _get(chave):
        col = mapa.get(chave)
        if not col:
            return ""
        val = row.get(col, '')
        return "" if pd.isna(val) else str(val).strip()
    
    nome_bruto = _get('condominio')
    nome_limpo, anotacoes_nome = limpar_nome_condominio(nome_bruto)
    zona = normalizar_zona(_get('zona'))
    
    pontos = parse_pontos_internet_avancado(_get('pontos_internet'))
    placas = parse_placas_avancado(_get('placas_fotos'))
    doacoes = parse_doacoes_avancado(_get('doacao'))
    parceiros_detalhados = parse_parceiros_avancado(_get('parceiro'))
    parceiros_nomes = [p['nome'] for p in parceiros_detalhados]
    
    sindico = _get('sindico')
    subsindico = _get('subsindico')
    preposto = _get('preposto')
    
    tel_sind = _get('contato_telefone_síndico')
    tel_prep = _get('contato_telefone_preposto')
    tel_subs = _get('contato_telefone_subsíndico')
    
    contatos = []
    if sindico or tel_sind:
        contatos.append({"nome": sindico, "funcao": "Síndico",
                         "telefone": tel_sind, "observacao": ""})
    if preposto or tel_prep:
        contatos.append({"nome": preposto, "funcao": "Preposto",
                         "telefone": tel_prep, "observacao": ""})
    if subsindico or tel_subs:
        contatos.append({"nome": subsindico, "funcao": "Subsíndico",
                         "telefone": tel_subs, "observacao": ""})
    
    observacoes = _get('observacoes')
    
    # Motivos de revisão
    motivos_revisao = []
    if not pontos['tem_pontos']:
        bruto_pontos = _get('pontos_internet').lower()
        if bruto_pontos and not any(x in bruto_pontos for x in
                                     ['sem', 'não', 'nao', 'n/a']):
            motivos_revisao.append("Pontos de internet não interpretados")
    if placas.get('pendencias'):
        motivos_revisao.append(f"Pendência placas: {placas['pendencias'][:80]}")
    if not nome_limpo:
        motivos_revisao.append("Nome vazio após limpeza")
    if not zona:
        motivos_revisao.append("Zona não identificada")
    
    return {
        "nome": nome_limpo.upper(),
        "nome_original": nome_bruto,
        "zona": zona,
        "anotacoes_nome": anotacoes_nome,
        "informacoes_detalhadas": {
            "pontos_internet": pontos,
            "placas_fotos": {
                "itens": placas['itens'],
                "eventos": placas['eventos'],
                "pendencias": placas['pendencias'],
                "observacao": placas['observacao']
            },
            "doacoes": doacoes,
            "parceiros": parceiros_nomes,
            "parceiros_detalhados": parceiros_detalhados,
            "sindico": sindico,
            "subsindico": subsindico,
            "preposto": preposto,
            "contatos": contatos,
            "observacoes": observacoes,
            "precisa_revisao": len(motivos_revisao) > 0,
            "motivos_revisao": motivos_revisao,
            "data_importacao": datetime.now()
        }
    }


def gerar_relatorio_qualidade(linhas: list) -> pd.DataFrame:
    dados = []
    for linha in linhas:
        info = linha['informacoes_detalhadas']
        dados.append({
            "Nome Original": linha['nome_original'],
            "Nome Limpo": linha['nome'],
            "Zona": linha['zona'],
            "Pontos": info['pontos_internet']['quantidade'],
            "Locais Pontos": ", ".join(info['pontos_internet']['locais'][:3]),
            "Itens Placas": len(info['placas_fotos']['itens']),
            "Total Doações": f"R$ {info['doacoes']['total_doacoes']:,.2f}",
            "Parceiros": len(info['parceiros']),
            "Contatos": len(info['contatos']),
            "Revisão?": "⚠️ SIM" if info.get('precisa_revisao') else "✅ OK",
            "Motivos": " | ".join(info.get('motivos_revisao', []))
        })
    return pd.DataFrame(dados)


# ============================================================================
# IMPORTAÇÃO COM BULK WRITE
# ============================================================================

def importar_informacoes_completas(df, collection, usar_parser_v2: bool = True):
    """
    Importação otimizada. Se usar_parser_v2=True, usa o parser Inf.xlsx.
    """
    resultado = {
        "total": 0, "matches": 0, "atualizados": 0,
        "criados": 0, "sem_match": 0, "precisa_revisao": 0,
        "detalhes": [], "linhas_processadas": []
    }
    
    # Escolher mapa
    if usar_parser_v2:
        mapa = detectar_colunas_informacoes_v2(df)
    else:
        mapa = detectar_colunas_informacoes(df)  # (fallback antigo)
    
    if 'condominio' not in mapa:
        return {**resultado, "erro": "Coluna CONDOMÍNIO não encontrada"}
    
    version = _get_cache_version("indice")
    indice = _get_indice_condominios(version)
    
    operacoes = []
    agora = datetime.now()
    
    for idx, row in df.iterrows():
        resultado["total"] += 1
        try:
            if usar_parser_v2:
                dados = processar_linha_planilha(row, mapa)
            else:
                # Fallback antigo (não recomendado)
                dados = None
            
            if not dados:
                continue
            
            resultado["linhas_processadas"].append(dados)
            
            if dados["informacoes_detalhadas"].get("precisa_revisao"):
                resultado["precisa_revisao"] += 1
            
            nome_match = dados["nome_original"] or dados["nome"]
            match = encontrar_match_condominio_otimizado(
                nome_match, dados["zona"], indice
            )
            
            if match:
                resultado["matches"] += 1
                operacoes.append(UpdateOne(
                    {"_id": match["_id"]},
                    {"$set": {
                        "informacoes_detalhadas": dados["informacoes_detalhadas"],
                        "ultima_atualizacao_informacoes": agora
                    }}
                ))
                resultado["atualizados"] += 1
                resultado["detalhes"].append({
                    "nome_planilha": nome_match,
                    "nome_crm": match.get("nome", ""),
                    "status": "match",
                    "score": match.get("_score", 0),
                    "detalhes": "Atualizado"
                })
            else:
                # Cria novo se a opção estiver ativa
                if dados["nome"]:
                    operacoes.append(InsertOne({
                        "nome": dados["nome"],
                        "zona": dados["zona"],
                        "informacoes_detalhadas": dados["informacoes_detalhadas"],
                        "data_cadastro": agora,
                        "ultima_atualizacao_informacoes": agora
                    }))
                    resultado["criados"] += 1
                    resultado["detalhes"].append({
                        "nome_planilha": nome_match,
                        "nome_crm": dados["nome"],
                        "status": "criado",
                        "score": 0,
                        "detalhes": "Novo condomínio criado"
                    })
                else:
                    resultado["sem_match"] += 1
                    resultado["detalhes"].append({
                        "nome_planilha": nome_match,
                        "nome_crm": "",
                        "status": "sem_match",
                        "score": 0,
                        "detalhes": "Sem nome válido"
                    })
        
        except Exception as e:
            resultado["detalhes"].append({
                "nome_planilha": str(row.get(mapa.get('condominio', ''), f'Linha {idx}')),
                "nome_crm": "", "status": "erro", "score": 0,
                "detalhes": f"Erro: {str(e)}"
            })
    
    if operacoes and UpdateOne is not None:
        try:
            collection.bulk_write(operacoes, ordered=False)
        except Exception as e:
            resultado["detalhes"].append({
                "nome_planilha": "BULK", "nome_crm": "",
                "status": "erro", "score": 0,
                "detalhes": f"Erro no bulk_write: {str(e)}"
            })
    elif operacoes:
        # Fallback sem pymongo.bulk
        for op in operacoes:
            try:
                collection.insert_one(op._doc) if isinstance(op, InsertOne) else None
            except Exception:
                pass
    
    invalidar_cache("lista")
    invalidar_cache("stats")
    invalidar_cache("indice")
    
    return resultado


# ============================================================================
# FUNÇÕES AUXILIARES ANTIGAS (compatibilidade)
# ============================================================================

def detectar_colunas_informacoes(df):
    """Fallback antigo (mantido para compatibilidade)"""
    return detectar_colunas_informacoes_v2(df)


# ============================================================================
# RENDER: DASHBOARD
# ============================================================================

def render_dashboard():
    collection = get_condominios_collection()
    
    v_stats = _get_cache_version("stats")
    stats = get_dashboard_stats(v_stats)
    
    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.metric("📊 Total de Condomínios", stats['total'])
    with col2:
        st.metric("✅ Com Informações", stats['com_info'])
    with col3:
        st.metric("⚠️ Sem Informações", stats['sem_info'],
                  delta="⚠️ Pendente" if stats['sem_info'] > 0 else None)
    with col4:
        principal = stats['zonas'][0]['_id'] if stats['zonas'] and stats['zonas'][0]['_id'] else "N/A"
        st.metric("🏙️ Principal Zona", principal)
    
    st.subheader("🔍 Filtros")
    col1, col2 = st.columns(2)
    with col1:
        zona_filter = st.selectbox("Zona", ["Todas"] + OPCOES_ZONA[1:])
    with col2:
        status_filter = st.selectbox("Status", ["Todos", "Com Informações", "Sem Informações"])
    
    query = {}
    if zona_filter != "Todas":
        query["zona"] = zona_filter
    if status_filter == "Com Informações":
        query["informacoes_detalhadas"] = {"$exists": True}
    elif status_filter == "Sem Informações":
        query["informacoes_detalhadas"] = {"$exists": False}
    
    condominios = list(collection.find(
        query,
        {"nome": 1, "zona": 1, "id_ixc": 1, "informacoes_detalhadas": 1,
         "ultima_atualizacao_informacoes": 1}
    ).sort("nome", 1))
    
    st.subheader(f"📋 {len(condominios)} Condomínios")
    
    cols = st.columns(3)
    for idx, cond in enumerate(condominios):
        with cols[idx % 3]:
            with st.container(border=True):
                st.markdown(f"### 🏢 {cond.get('nome', 'N/A')[:35]}")
                st.caption(f"📍 {cond.get('zona', 'N/A')} | IXC: {cond.get('id_ixc', 'N/A')}")
                
                info = cond.get("informacoes_detalhadas", {})
                if info:
                    if info.get("precisa_revisao"):
                        st.warning("⚠️ Precisa revisão")
                    
                    pontos = info.get("pontos_internet", {})
                    if pontos.get("quantidade", 0) > 0:
                        locais = pontos.get("locais", [])
                        st.write(f"📶 **{pontos['quantidade']}** pontos" +
                                 (f" ({', '.join(locais[:3])})" if locais else ""))
                    
                    itens_placas = info.get("placas_fotos", {}).get("itens", [])
                    if itens_placas:
                        st.write(f"🪧 **{len(itens_placas)}** itens de placa")
                    
                    total_doacoes = info.get("doacoes", {}).get("total_doacoes", 0)
                    if total_doacoes > 0:
                        st.write(f"🎁 **R$ {total_doacoes:,.2f}** em doações")
                    
                    data_atualizacao = cond.get("ultima_atualizacao_informacoes")
                    if data_atualizacao:
                        st.caption(f"🔄 {data_atualizacao.strftime('%d/%m/%Y')}")
                else:
                    st.warning("⚠️ Sem informações detalhadas")
                
                st.caption("💡 Edite na aba 'Editar Informações'")


# ============================================================================
# RENDER: IMPORTAÇÃO
# ============================================================================

def render_importacao_informacoes():
    st.subheader("📥 Importar Informações Detalhadas")
    
    st.info("""
    **🔍 Como funciona o matching inteligente (parser Inf.xlsx):**
    
    1. **Prioridade 1**: Match pelo ID do IXC (se disponível no nome)
    2. **Prioridade 2**: Match pelo nome normalizado (remove acentos, palavras comuns)
    3. **Prioridade 3**: Match por similaridade (rapidfuzz)
    4. **Prioridade 4**: Match por zona + palavras-chave
    
    **✨ O parser especializado trata automaticamente:**
    - Siglas de zona (ZN → Zona Norte)
    - Colunas "CONTATO 1" duplicadas (Síndico / Preposto / Subsíndico)
    - Placas com múltiplos eventos históricos (data, tipo, responsável, status)
    - Doações em vários formatos (1.234,56 / 3K / "Split + Notebook")
    - Nomes com anotações ("(EM ANDAMENTO)", "- PREV. NOV.")
    """)
    
    arquivo = st.file_uploader(
        "📂 Selecione a planilha",
        type=["csv", "xlsx", "xls"],
        help="Recomendado: formato Inf.xlsx (ZN/ZO/ZS/SO/C/BXD + CONTATO 1 duplicado)"
    )
    
    if not arquivo:
        return
    
    try:
        if arquivo.name.lower().endswith('.csv'):
            df = pd.read_csv(arquivo)
        else:
            df = pd.read_excel(arquivo)
        
        st.success(f"✅ Arquivo lido! {len(df)} registros")
        df.columns = df.columns.str.strip()
        
        with st.expander("📋 Prévia dos dados brutos", expanded=False):
            st.dataframe(df.head(10), use_container_width=True)
        
        mapa = detectar_colunas_informacoes_v2(df)
        
        with st.expander("🔍 Mapeamento de colunas detectado", expanded=True):
            for campo, coluna in mapa.items():
                st.write(f"- **{campo}** → `{coluna}`")
        
        if 'condominio' not in mapa:
            st.error("❌ Coluna 'CONDOMÍNIO' não encontrada!")
            st.write("Colunas disponíveis:", list(df.columns))
            return
        
        # ============================================
        # PREVIEW COM QUALIDADE
        # ============================================
        st.divider()
        st.subheader("🔎 Preview com análise de qualidade")
        st.caption("Mostrando as primeiras 15 linhas processadas pelo parser")
        
        linhas_preview = []
        erros_preview = []
        for idx, row in df.head(15).iterrows():
            try:
                dados = processar_linha_planilha(row, mapa)
                linhas_preview.append(dados)
            except Exception as e:
                erros_preview.append(f"Linha {idx}: {e}")
        
        if linhas_preview:
            df_qualidade = gerar_relatorio_qualidade(linhas_preview)
            st.dataframe(df_qualidade, use_container_width=True, hide_index=True)
        
        if erros_preview:
            with st.expander(f"⚠️ {len(erros_preview)} erros no preview"):
                for e in erros_preview:
                    st.write(e)
        
        # Detalhamento de UMA linha (drill-down)
        if linhas_preview:
            with st.expander("🔬 Detalhamento de uma linha (drill-down)"):
                opcoes = [f"{i+1}. {l['nome_original']}" for i, l in enumerate(linhas_preview)]
                escolha = st.selectbox("Ver detalhes de:", opcoes)
                idx_escolhido = opcoes.index(escolha)
                detalhe = linhas_preview[idx_escolhido]["informacoes_detalhadas"]
                
                col_d1, col_d2 = st.columns(2)
                with col_d1:
                    st.markdown("**📶 Pontos Internet**")
                    st.json(detalhe["pontos_internet"])
                    
                    st.markdown("**🎁 Doações**")
                    st.json(detalhe["doacoes"])
                
                with col_d2:
                    st.markdown("**🪧 Placas (itens)**")
                    st.json(detalhe["placas_fotos"]["itens"])
                    
                    st.markdown("**👥 Contatos**")
                    st.json(detalhe["contatos"])
        
        # Estatísticas
        revisao_count = sum(1 for l in linhas_preview
                             if l['informacoes_detalhadas'].get('precisa_revisao'))
        
        col1, col2, col3 = st.columns(3)
        with col1:
            st.metric("Total de linhas", len(df))
        with col2:
            st.metric("✅ OK automático", len(linhas_preview) - revisao_count)
        with col3:
            st.metric("⚠️ Precisam revisar", revisao_count)
        
        # ============================================
        # BOTÃO IMPORTAR
        # ============================================
        st.divider()
        st.warning("⚠️ Ao importar, informações existentes serão **ATUALIZADAS**. "
                   "Condomínios sem match serão **CRIADOS** com o nome limpo.")
        
        col_imp1, col_imp2 = st.columns([1, 3])
        with col_imp1:
            importar_btn = st.button("🚀 Importar Tudo", type="primary",
                                      use_container_width=True)
        
        if importar_btn:
            with st.spinner("🔄 Processando com bulk_write..."):
                collection = get_condominios_collection()
                resultado = importar_informacoes_completas(df, collection, usar_parser_v2=True)
                
                if resultado.get("erro"):
                    st.error(f"❌ {resultado['erro']}")
                    return
                
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
                    st.metric("⚠️ Revisar", resultado['precisa_revisao'])
                
                # Detalhes
                with st.expander("📋 Detalhes da Importação", expanded=False):
                    for item in resultado['detalhes'][:50]:
                        if item['status'] == 'match':
                            st.success(f"✅ **{item['nome_planilha']}** → "
                                       f"**{item['nome_crm']}** (Score: {item['score']}%)")
                        elif item['status'] == 'criado':
                            st.info(f"🆕 **{item['nome_planilha']}** - novo condomínio")
                        elif item['status'] == 'sem_match':
                            st.warning(f"⚠️ **{item['nome_planilha']}** - sem match")
                        else:
                            st.error(f"❌ **{item['nome_planilha']}** - {item.get('detalhes', 'Erro')}")
                    
                    if len(resultado['detalhes']) > 50:
                        st.info(f"... e mais {len(resultado['detalhes']) - 50} registros")
                
                # Relatório de qualidade para download
                if resultado['linhas_processadas']:
                    df_rel = gerar_relatorio_qualidade(resultado['linhas_processadas'])
                    
                    output = io.BytesIO()
                    with pd.ExcelWriter(output, engine='openpyxl') as writer:
                        df_rel.to_excel(writer, index=False, sheet_name='Qualidade')
                        # Ajustar larguras
                        ws = writer.sheets['Qualidade']
                        for col in ws.columns:
                            max_len = max((len(str(c.value)) for c in col if c.value), default=10)
                            ws.column_dimensions[col[0].column_letter].width = min(max_len + 2, 50)
                    output.seek(0)
                    
                    st.download_button(
                        "📥 Baixar relatório de qualidade (Excel)",
                        data=output.getvalue(),
                        file_name=f"relatorio_importacao_{datetime.now():%Y%m%d_%H%M}.xlsx",
                        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                        use_container_width=True
                    )
                
                st.balloons()
    
    except Exception as e:
        st.error(f"❌ Erro ao processar arquivo: {e}")
        import traceback
        st.code(traceback.format_exc())


# ============================================================================
# RENDER: EDIÇÃO
# ============================================================================

def render_lista_edicao_condominios():
    st.subheader("✏️ Editar Informações dos Condomínios")
    st.info("💡 Clique no nome do condomínio para expandir e editar.")
    
    collection = get_condominios_collection()
    
    col1, col2, col3 = st.columns([2, 2, 1])
    with col1:
        zona_filter = st.selectbox("Zona", ["Todas"] + OPCOES_ZONA[1:], key="filtro_zona_edicao")
    with col2:
        status_filter = st.selectbox(
            "Status", ["Todos", "Com Informações", "Sem Informações", "⚠️ Precisa Revisão"],
            key="filtro_status_edicao"
        )
    with col3:
        if st.button("🔄 Recarregar", use_container_width=True):
            invalidar_cache("lista")
            invalidar_cache("stats")
            st.rerun()
    
    v_lista = _get_cache_version("lista")
    if zona_filter == "Todas" and status_filter == "Todos":
        condominios = get_all_condominios_com_info(v_lista)
    else:
        # Filtro especial para "precisa revisão"
        if status_filter == "⚠️ Precisa Revisão":
            base = get_all_condominios_com_info(v_lista)
            condominios = [c for c in base
                           if c.get("informacoes_detalhadas", {}).get("precisa_revisao")
                           and (zona_filter == "Todas" or c.get("zona") == zona_filter)]
        else:
            condominios = get_condominios_filtrados(
                zona_filter,
                status_filter if status_filter != "⚠️ Precisa Revisão" else None,
                v_lista
            )
    
    if not condominios:
        st.info("Nenhum condomínio encontrado.")
        return
    
    ITENS_POR_PAGINA = 10
    total = len(condominios)
    total_paginas = (total + ITENS_POR_PAGINA - 1) // ITENS_POR_PAGINA
    
    col1, col2, col3 = st.columns([2, 3, 2])
    with col1:
        st.caption(f"📌 {total} condomínios")
    with col2:
        if total_paginas > 1:
            pagina_atual = st.selectbox("Página", range(1, total_paginas + 1), key="pagina_edicao")
        else:
            pagina_atual = 1
            st.caption("Página 1 de 1")
    with col3:
        st.caption(f"Mostrando {ITENS_POR_PAGINA} por página")
    
    inicio = (pagina_atual - 1) * ITENS_POR_PAGINA
    fim = min(inicio + ITENS_POR_PAGINA, total)
    condominios_pagina = condominios[inicio:fim]
    
    cond_selecionado_id = st.session_state.get('cond_info_edit', None)
    
    for cond in condominios_pagina:
        info = cond.get("informacoes_detalhadas", {})
        has_info = bool(info)
        precisa_revisao = info.get("precisa_revisao", False) if has_info else False
        
        if not has_info:
            status_icon = "⚠️"
            status_text = "Sem informações"
        elif precisa_revisao:
            status_icon = "🔶"
            status_text = "Precisa revisão"
        else:
            status_icon = "✅"
            status_text = "Com informações"
        
        expander_label = (f"{status_icon} {cond.get('nome', 'N/A')} - "
                          f"{cond.get('zona', 'N/A')} - {status_text}")
        is_expanded = (str(cond['_id']) == cond_selecionado_id)
        
        with st.expander(expander_label, expanded=is_expanded):
            col1, col2, col3 = st.columns([3, 1, 1])
            with col1:
                st.markdown(f"### 🏢 {cond.get('nome', 'N/A')}")
                st.caption(f"📍 Zona: {cond.get('zona', 'N/A')} | "
                           f"ID IXC: {cond.get('id_ixc', 'N/A')}")
            with col2:
                if has_info:
                    if st.button("🗑️ Limpar", key=f"clear_{cond['_id']}"):
                        collection.update_one(
                            {"_id": cond['_id']},
                            {"$unset": {"informacoes_detalhadas": ""}}
                        )
                        for key in [f'itens_placas_{cond["_id"]}',
                                     f'itens_doacoes_{cond["_id"]}',
                                     f'contatos_{cond["_id"]}']:
                            st.session_state.pop(key, None)
                        invalidar_cache("lista")
                        invalidar_cache("stats")
                        st.success("Informações removidas!")
                        st.rerun()
            with col3:
                if has_info:
                    if st.button("📋 Resumo", key=f"resumo_{cond['_id']}"):
                        k = f'resumo_{cond["_id"]}'
                        st.session_state[k] = not st.session_state.get(k, False)
            
            # Alerta de revisão
            if precisa_revisao:
                motivos = info.get("motivos_revisao", [])
                if motivos:
                    st.warning("⚠️ **Motivos de revisão:**\n- " + "\n- ".join(motivos))
            
            # Resumo
            if has_info and st.session_state.get(f'resumo_{cond["_id"]}', False):
                with st.container(border=True):
                    pontos = info.get("pontos_internet", {})
                    if pontos.get("quantidade", 0) > 0:
                        st.write(f"📶 **{pontos['quantidade']}** pontos")
                        if pontos.get("locais"):
                            st.write(f"   Locais: {', '.join(pontos['locais'])}")
                    
                    placas_info = info.get("placas_fotos", {})
                    itens_placas = placas_info.get("itens", [])
                    if itens_placas:
                        st.write(f"🪧 **{len(itens_placas)}** itens de placa")
                        for item in itens_placas[:5]:
                            data = item.get("data", "")
                            data_str = f" ({data})" if data else ""
                            st.write(f"   - {item.get('tipo')}: {item.get('quantidade')}x"
                                     f"{data_str} [{item.get('status', '')}]")
                    
                    if placas_info.get("pendencias"):
                        st.warning(f"⏳ Pendência: {placas_info['pendencias'][:150]}")
                    
                    doacoes_info = info.get("doacoes", {})
                    total_doacoes = doacoes_info.get("total_doacoes", 0)
                    if total_doacoes > 0:
                        st.write(f"🎁 **R$ {total_doacoes:,.2f}** em doações")
                        for item in doacoes_info.get("itens", [])[:5]:
                            st.write(f"   - {item.get('item')}: R$ {item.get('valor', 0):,.2f}")
                    
                    parceiros_det = info.get("parceiros_detalhados", [])
                    if parceiros_det:
                        st.write(f"🤝 **{len(parceiros_det)}** parceiros")
                        for p in parceiros_det[:5]:
                            obs = f" ({p.get('observacao', '')})" if p.get('observacao') else ""
                            st.write(f"   - {p.get('nome')}{obs}")
                    
                    contatos = info.get("contatos", [])
                    if contatos:
                        st.write(f"👥 **{len(contatos)}** contatos")
                        for c in contatos:
                            st.write(f"   - {c.get('nome') or '(sem nome)'} "
                                     f"({c.get('funcao')}) - {c.get('telefone', '')}")
                    
                    data_atualizacao = cond.get("ultima_atualizacao_informacoes")
                    if data_atualizacao:
                        st.caption(f"🔄 {data_atualizacao.strftime('%d/%m/%Y %H:%M')}")
            
            # ========== FORMULÁRIO DE EDIÇÃO ==========
            st.markdown("---")
            st.markdown("### ✏️ Editar Informações")
            
            if f'itens_placas_{cond["_id"]}' not in st.session_state:
                st.session_state[f'itens_placas_{cond["_id"]}'] = info.get("placas_fotos", {}).get("itens", [])
            if f'itens_doacoes_{cond["_id"]}' not in st.session_state:
                st.session_state[f'itens_doacoes_{cond["_id"]}'] = info.get("doacoes", {}).get("itens", [])
            if f'contatos_{cond["_id"]}' not in st.session_state:
                st.session_state[f'contatos_{cond["_id"]}'] = info.get("contatos", [])
            
            # Botões de adicionar (fora do form)
            col1, col2, col3 = st.columns(3)
            with col1:
                if st.button("➕ Adicionar Placa", key=f"add_placa_{cond['_id']}"):
                    st.session_state[f'itens_placas_{cond["_id"]}'].append({
                        "tipo": "Cavalete", "quantidade": 1, "local": "",
                        "data": "", "responsavel": "", "status": "", "observacao": ""
                    })
                    st.rerun()
            with col2:
                if st.button("➕ Adicionar Doação", key=f"add_doacao_{cond['_id']}"):
                    st.session_state[f'itens_doacoes_{cond["_id"]}'].append({
                        "item": "", "quantidade": 1, "valor": 0.00,
                        "forma_pagamento": "Pix", "observacao": ""
                    })
                    st.rerun()
            with col3:
                if st.button("➕ Adicionar Contato", key=f"add_contato_{cond['_id']}"):
                    st.session_state[f'contatos_{cond["_id"]}'].append({
                        "nome": "", "telefone": "", "funcao": "Outro", "observacao": ""
                    })
                    st.rerun()
            
            st.markdown("---")
            
            with st.form(f"form_info_{cond['_id']}"):
                # PONTOS
                st.subheader("📶 Pontos de Internet")
                pontos_info = info.get("pontos_internet", {})
                qtd_pontos = st.number_input(
                    "Quantidade de pontos", min_value=0, max_value=20,
                    value=int(pontos_info.get("quantidade", 0)),
                    key=f"qtd_pontos_{cond['_id']}"
                )
                
                st.markdown("**Locais:**")
                col1, col2, col3 = st.columns(3)
                locais_existentes = pontos_info.get("locais", [])
                locais_selecionados = []
                for i, local in enumerate(LOCAIS_PONTOS):
                    target_col = col1 if i % 3 == 0 else col2 if i % 3 == 1 else col3
                    with target_col:
                        if st.checkbox(local, value=local in locais_existentes,
                                       key=f"ponto_{cond['_id']}_{i}"):
                            locais_selecionados.append(local)
                
                obs_pontos = st.text_area(
                    "Observações", value=pontos_info.get("observacao", ""),
                    key=f"obs_pontos_{cond['_id']}"
                )
                
                st.divider()
                
                # PLACAS
                st.subheader("🪧 Placas e Fotos")
                itens_atuais = st.session_state.get(f'itens_placas_{cond["_id"]}', [])
                st.caption(f"📌 {len(itens_atuais)} itens")
                
                for idx_item, item in enumerate(itens_atuais):
                    with st.container(border=True):
                        col1, col2, col3, col4 = st.columns([2, 1, 1, 1])
                        with col1:
                            tipo_atual = item.get("tipo", "Cavalete")
                            item["tipo"] = st.selectbox(
                                f"Tipo {idx_item+1}", options=TIPOS_PLACA,
                                index=TIPOS_PLACA.index(tipo_atual) if tipo_atual in TIPOS_PLACA else 0,
                                key=f"tipo_placa_{cond['_id']}_{idx_item}"
                            )
                        with col2:
                            item["quantidade"] = st.number_input(
                                "Qtd", min_value=0, max_value=50,
                                value=int(item.get("quantidade", 1)),
                                key=f"qtd_placa_{cond['_id']}_{idx_item}"
                            )
                        with col3:
                            item["local"] = st.text_input(
                                "Local", value=item.get("local", ""),
                                key=f"local_placa_{cond['_id']}_{idx_item}"
                            )
                        with col4:
                            item["data"] = st.text_input(
                                "Data", value=item.get("data", ""),
                                key=f"data_placa_{cond['_id']}_{idx_item}"
                            )
                
                obs_placas = st.text_area(
                    "Observações placas",
                    value=info.get("placas_fotos", {}).get("observacao", ""),
                    key=f"obs_placas_{cond['_id']}"
                )
                
                st.divider()
                
                # DOAÇÕES
                st.subheader("🎁 Doações")
                itens_doacoes_atuais = st.session_state.get(f'itens_doacoes_{cond["_id"]}', [])
                st.caption(f"📌 {len(itens_doacoes_atuais)} doações")
                
                for idx_item, doacao in enumerate(itens_doacoes_atuais):
                    with st.container(border=True):
                        col1, col2, col3 = st.columns([3, 1, 1])
                        with col1:
                            doacao["item"] = st.text_input(
                                f"Item {idx_item+1}", value=doacao.get("item", ""),
                                key=f"item_doacao_{cond['_id']}_{idx_item}"
                            )
                        with col2:
                            doacao["quantidade"] = st.number_input(
                                "Qtd", min_value=1,
                                value=int(doacao.get("quantidade", 1)),
                                key=f"qtd_doacao_{cond['_id']}_{idx_item}"
                            )
                        with col3:
                            doacao["valor"] = st.number_input(
                                "Valor (R$)", min_value=0.00,
                                value=float(doacao.get("valor", 0.00)),
                                step=0.01,
                                key=f"valor_doacao_{cond['_id']}_{idx_item}"
                            )
                        
                        col4, col5 = st.columns([1, 2])
                        with col4:
                            formas = FORMAS_PAGAMENTO + ["Não especificado", "A definir"]
                            fp = doacao.get("forma_pagamento", "Pix")
                            doacao["forma_pagamento"] = st.selectbox(
                                "Forma",
                                options=formas,
                                index=formas.index(fp) if fp in formas else 0,
                                key=f"forma_doacao_{cond['_id']}_{idx_item}"
                            )
                        with col5:
                            doacao["observacao"] = st.text_input(
                                "Obs", value=doacao.get("observacao", ""),
                                key=f"obs_doacao_{cond['_id']}_{idx_item}"
                            )
                
                obs_doacoes = st.text_area(
                    "Observações doações",
                    value=info.get("doacoes", {}).get("observacao", ""),
                    key=f"obs_doacoes_{cond['_id']}"
                )
                
                st.divider()
                
                # CONTATOS
                st.subheader("👥 Contatos")
                contatos_atuais = st.session_state.get(f'contatos_{cond["_id"]}', [])
                st.caption(f"📌 {len(contatos_atuais)} contatos")
                
                for idx_item, contato in enumerate(contatos_atuais):
                    with st.container(border=True):
                        col1, col2, col3 = st.columns([2, 1, 1])
                        with col1:
                            contato["nome"] = st.text_input(
                                f"Nome {idx_item+1}", value=contato.get("nome", ""),
                                key=f"nome_contato_{cond['_id']}_{idx_item}"
                            )
                        with col2:
                            contato["telefone"] = st.text_input(
                                "Telefone", value=contato.get("telefone", ""),
                                key=f"tel_contato_{cond['_id']}_{idx_item}"
                            )
                        with col3:
                            funcao_atual = contato.get("funcao", "Outro")
                            contato["funcao"] = st.selectbox(
                                "Função", options=FUNCOES_CONTATO,
                                index=FUNCOES_CONTATO.index(funcao_atual)
                                if funcao_atual in FUNCOES_CONTATO else 0,
                                key=f"funcao_contato_{cond['_id']}_{idx_item}"
                            )
                
                # OBSERVAÇÕES GERAIS
                st.subheader("📝 Observações Gerais")
                observacoes_gerais = st.text_area(
                    "Observações", value=info.get("observacoes", ""),
                    key=f"obs_gerais_{cond['_id']}", height=100
                )
                
                # PARCEIROS
                st.subheader("🤝 Parceiros")
                parceiros_det = info.get("parceiros_detalhados", [])
                if not parceiros_det:
                    parceiros_det = [{"nome": n, "funcao": "", "observacao": ""}
                                      for n in info.get("parceiros", [])]
                parceiros_text = st.text_input(
                    "Parceiros (nomes separados por vírgula)",
                    value=", ".join(p.get("nome", "") for p in parceiros_det if p.get("nome")),
                    key=f"parceiros_{cond['_id']}"
                )
                
                st.divider()
                
                # Marcar revisão como resolvida
                marcar_ok = st.checkbox(
                    "✅ Marcar revisão como resolvida",
                    value=False,
                    key=f"marcar_ok_{cond['_id']}",
                    help="Se marcado, remove o alerta de revisão deste condomínio"
                )
                
                if st.form_submit_button("💾 Salvar Informações", type="primary"):
                    nova_info = {
                        "pontos_internet": {
                            "quantidade": qtd_pontos,
                            "locais": locais_selecionados,
                            "observacao": obs_pontos,
                            "tem_pontos": qtd_pontos > 0
                        },
                        "placas_fotos": {
                            "itens": itens_atuais,
                            "eventos": info.get("placas_fotos", {}).get("eventos", []),
                            "pendencias": info.get("placas_fotos", {}).get("pendencias", ""),
                            "observacao": obs_placas
                        },
                        "doacoes": {
                            "itens": itens_doacoes_atuais,
                            "observacao": obs_doacoes,
                            "total_doacoes": sum(
                                item.get("valor", 0) * item.get("quantidade", 1)
                                for item in itens_doacoes_atuais
                            ),
                            "teve_doacao": len(itens_doacoes_atuais) > 0
                        },
                        "contatos": contatos_atuais,
                        "observacoes": observacoes_gerais,
                        "parceiros": [p.strip() for p in parceiros_text.split(",") if p.strip()] if parceiros_text else [],
                        "parceiros_detalhados": info.get("parceiros_detalhados", []),
                        "sindico": info.get("sindico", ""),
                        "subsindico": info.get("subsindico", ""),
                        "preposto": info.get("preposto", ""),
                        "precisa_revisao": False if marcar_ok else info.get("precisa_revisao", False),
                        "motivos_revisao": [] if marcar_ok else info.get("motivos_revisao", []),
                        "data_ultima_edicao": datetime.now()
                    }
                    
                    collection.update_one(
                        {"_id": cond['_id']},
                        {"$set": {
                            "informacoes_detalhadas": nova_info,
                            "ultima_atualizacao_informacoes": datetime.now()
                        }}
                    )
                    
                    for key in [f'itens_placas_{cond["_id"]}',
                                 f'itens_doacoes_{cond["_id"]}',
                                 f'contatos_{cond["_id"]}']:
                        st.session_state.pop(key, None)
                    st.session_state.pop('cond_info_edit', None)
                    
                    invalidar_cache("lista")
                    invalidar_cache("stats")
                    
                    st.success(f"✅ '{cond['nome']}' atualizado!")
                    st.balloons()
                    st.rerun()


# ============================================================================
# RENDER PRINCIPAL
# ============================================================================

def render_informacoes_condominios():
    st.title("📊 Informações Detalhadas dos Condomínios")
    
    _init_indices()
    
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
