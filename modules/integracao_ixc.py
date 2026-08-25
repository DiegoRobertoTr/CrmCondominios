"""
modules/integracao_ixc.py - VERSÃO FINAL COM MÉTODO R6 E BUSCA DE CONDOMÍNIO NO CRM
==================================================================================
Correções aplicadas:
- Busca flexível de condomínio (LIKE + normalização de acentos)
- Fallback que lista todos os condomínios do IXC
- Logs detalhados em cada etapa para debug
- IMPLEMENTAÇÃO DO MÉTODO R6 (que funcionou nos testes)
- BUSCA DE ID DO CONDOMÍNIO DIRETAMENTE NO CRM
- FALLBACK direto R6 caso a construção normal falhe
- NOVA FUNÇÃO: enviar_cliente_para_ixc_com_verificacao() para integração sob demanda
"""
import requests
import re
import base64
import json
import unicodedata
import streamlit as st
from datetime import datetime
from typing import Dict, Optional, Tuple, List
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# ============================================================================
# FORMATADORES EXATOS DO TESTE R6P01 (QUE FUNCIONOU)
# ============================================================================
def fmt_cep(cep: str) -> str:
    """Formata CEP no padrão XXXXX-XXX (ex: 20521130 -> 20521-130)"""
    d = re.sub(r'\D', '', str(cep)).zfill(8)
    return f"{d[:5]}-{d[5:]}" if len(d) == 8 else d


def fmt_fone(fone: str) -> str:
    """Formata telefone no padrão (DDD)NÚMERO (ex: 21999900008 -> (21)999900008)"""
    d = re.sub(r'\D', '', str(fone))
    if len(d) >= 10:
        return f"({d[:2]}){d[2:]}"
    return d


def fmt_cpf(cpf: str) -> str:
    """Formata CPF no padrão XXX.XXX.XXX-XX"""
    d = re.sub(r'\D', '', str(cpf)).zfill(11)
    return f"{d[:3]}.{d[3:6]}.{d[6:9]}-{d[9:]}" if len(d) == 11 else d


# ============================================================================
# IDs FIXOS (confirmados no teste R6P01)
# ============================================================================
ID_CIDADE_RJ = "3241"
ID_UF_RJ = "24"


# ============================================================================
# CONFIGURAÇÃO
# ============================================================================
def get_ixc_config() -> Optional[Dict]:
    """Retorna configuração da API IXC a partir de st.secrets."""
    try:
        return {
            "host": st.secrets["ixc"]["host"],
            "token": st.secrets["ixc"]["token"],
            "filial_id": st.secrets["ixc"].get("filial_id", "1"),
            "id_tipo_cliente": st.secrets["ixc"].get("id_tipo_cliente", "03"),
            "tipo_cliente_scm": st.secrets["ixc"].get("tipo_cliente_scm", "01")
        }
    except Exception as e:
        print(f"❌ Erro ao carregar configuração do IXC: {e}")
        return None


def _sanitizar_host(host: str) -> str:
    """Remove protocolo e barras do host."""
    host = host.replace("https://", "").replace("http://", "")
    return host.split("/")[0].strip().rstrip("/")


# ============================================================================
# VALIDAÇÃO DE CPF
# ============================================================================
def validar_cpf(cpf: str) -> bool:
    """Valida CPF algorítmico."""
    cpf = "".join(filter(str.isdigit, str(cpf)))
    if len(cpf) != 11 or cpf == cpf[0] * 11:
        return False
    # Primeiro dígito
    soma1 = sum(int(cpf[i]) * (10 - i) for i in range(9))
    digito1 = 0 if (soma1 * 10) % 11 >= 10 else (soma1 * 10) % 11
    if int(cpf[9]) != digito1:
        return False
    # Segundo dígito
    soma2 = sum(int(cpf[i]) * (11 - i) for i in range(10))
    digito2 = 0 if (soma2 * 10) % 11 >= 10 else (soma2 * 10) % 11
    return int(cpf[10]) == digito2


# ============================================================================
# NORMALIZAÇÃO DE TEXTO (resolve acentos, maiúsculas, espaços)
# ============================================================================
def _normalizar_texto(texto: str) -> str:
    """Remove acentos, espaços extras e converte para minúsculas."""
    if not texto:
        return ""
    # Remove acentos
    texto = unicodedata.normalize('NFD', str(texto))
    texto = ''.join(c for c in texto if unicodedata.category(c) != 'Mn')
    # Remove espaços extras e converte para minúsculas
    return ' '.join(texto.lower().split())


# ============================================================================
# BUSCAR ID DA CIDADE/UF NO IXC
# ============================================================================
def _buscar_id_cidade(host_limpo: str, auth_string: str, cidade_nome: str, uf_sigla: str) -> tuple:
    """Busca os IDs numericos de cidade e UF no IXC. Fallback para RJ."""
    id_cidade = ID_CIDADE_RJ
    id_uf = ID_UF_RJ
    try:
        h = {
            "Authorization": f"Basic {auth_string}",
            "ixcsoft": "listar",
            "Content-Type": "application/json"
        }
        r = requests.post(
            f"https://{host_limpo}/webservice/v1/cidade",
            json={
                "qtype": "cidade.nome",
                "query": cidade_nome,
                "oper": "=",
                "page": "1",
                "rp": "10"
            },
            headers=h,
            timeout=10,
            verify=False
        )
        if r.status_code == 200:
            rj = r.json()
            regs = rj.get("registros") or rj.get("data") or []
            if regs:
                match = next((x for x in regs if str(x.get("uf", "")).upper() == uf_sigla.upper()), regs[0])
                id_cidade = str(match.get("id", id_cidade))
                id_uf = str(match.get("uf", id_uf))
    except Exception as e:
        print(f"⚠️ Não foi possível buscar ID da cidade '{cidade_nome}': {e} — usando fallback RJ")
    return id_cidade, id_uf


# ============================================================================
# BUSCAR CONDOMÍNIO NO IXC — VERSÃO MELHORADA (LIKE + FALLBACK)
# ============================================================================
def buscar_condominio_completo_ixc(host_limpo: str, auth_string: str, nome_condominio: str) -> Optional[Dict]:
    """
    Busca dados completos de um condomínio no IXC pelo nome.
    VERSÃO MELHORADA: usa busca flexível (LIKE) + normalização de texto.
    """
    if not nome_condominio:
        return None

    nome_busca_norm = _normalizar_texto(nome_condominio)
    print(f"🔍 Buscando condomínio no IXC: '{nome_condominio}' (normalizado: '{nome_busca_norm}')")

    try:
        headers = {
            "Authorization": f"Basic {auth_string}",
            "ixcsoft": "listar",
            "Content-Type": "application/json"
        }

        # Usar "LIKE" em vez de "=" para busca flexível
        payload = {
            "qtype": "condominio.nome",
            "query": nome_condominio,
            "oper": "LIKE",
            "page": "1",
            "rp": "20"
        }

        response = requests.post(
            f"https://{host_limpo}/webservice/v1/condominio",
            json=payload,
            headers=headers,
            timeout=15,
            verify=False
        )

        print(f"📡 Resposta IXC (status {response.status_code})")

        if response.status_code != 200:
            print(f"❌ Erro HTTP {response.status_code}: {response.text[:200]}")
            return None

        dados = response.json()
        registros = dados.get("registros") or dados.get("data") or []

        print(f"📋 {len(registros)} condomínio(s) encontrado(s) no IXC")

        if not registros:
            # Fallback: listar TODOS os condomínios do IXC e buscar manualmente
            print(f"⚠️ Busca por nome falhou. Tentando listar todos os condomínios...")
            return _buscar_condominio_fallback(host_limpo, auth_string, nome_busca_norm)

        # 1ª tentativa: match EXATO (normalizado)
        for reg in registros:
            nome_reg_norm = _normalizar_texto(reg.get("nome", ""))
            if nome_reg_norm == nome_busca_norm:
                print(f"✅ Match exato encontrado: ID {reg.get('id')} - '{reg.get('nome')}'")
                return _montar_dados_condominio(reg)

        # 2ª tentativa: match por CONTÉM
        for reg in registros:
            nome_reg_norm = _normalizar_texto(reg.get("nome", ""))
            if nome_busca_norm in nome_reg_norm or nome_reg_norm in nome_busca_norm:
                print(f"✅ Match parcial encontrado: ID {reg.get('id')} - '{reg.get('nome')}'")
                return _montar_dados_condominio(reg)

        # 3ª tentativa: match por palavras-chave comuns
        palavras_busca = set(nome_busca_norm.split())
        melhor_match = None
        melhor_score = 0
        for reg in registros:
            nome_reg_norm = _normalizar_texto(reg.get("nome", ""))
            palavras_reg = set(nome_reg_norm.split())
            intersecao = palavras_busca & palavras_reg
            score = len(intersecao)
            if score > melhor_score:
                melhor_score = score
                melhor_match = reg

        if melhor_match and melhor_score >= 2:
            print(f"✅ Match por palavras-chave (score={melhor_score}): ID {melhor_match.get('id')} - '{melhor_match.get('nome')}'")
            return _montar_dados_condominio(melhor_match)

        print(f"❌ Nenhum match encontrado para '{nome_condominio}'")
        return None

    except Exception as e:
        print(f"⚠️ Erro ao buscar condomínio '{nome_condominio}': {e}")
        return None


def _montar_dados_condominio(reg: Dict) -> Dict:
    """Monta dicionário padronizado com dados do condomínio."""
    return {
        "id_ixc": str(reg.get("id")),
        "nome": reg.get("nome"),
        "endereco": reg.get("endereco"),
        "numero": reg.get("numero"),
        "bairro": reg.get("bairro"),
        "cidade": reg.get("cidade"),
        "uf": reg.get("uf"),
        "cep": reg.get("cep"),
        "bloco_padrao": reg.get("bloco_padrao"),
        "apartamento_padrao": reg.get("apartamento_padrao"),
        "ativo": reg.get("ativo", "S"),
        "dados_completos": reg
    }


def _buscar_condominio_fallback(host_limpo: str, auth_string: str, nome_busca_norm: str) -> Optional[Dict]:
    """Fallback: lista TODOS os condomínios do IXC e busca pelo nome."""
    try:
        headers = {
            "Authorization": f"Basic {auth_string}",
            "ixcsoft": "listar",
            "Content-Type": "application/json"
        }
        payload = {
            "qtype": "condominio.id",
            "query": "0",
            "oper": ">",
            "page": "1",
            "rp": "500"
        }
        response = requests.post(
            f"https://{host_limpo}/webservice/v1/condominio",
            json=payload,
            headers=headers,
            timeout=20,
            verify=False
        )

        if response.status_code == 200:
            dados = response.json()
            registros = dados.get("registros") or dados.get("data") or []
            print(f"📋 Fallback: {len(registros)} condomínios listados no IXC")

            for reg in registros:
                nome_reg_norm = _normalizar_texto(reg.get("nome", ""))
                if nome_busca_norm in nome_reg_norm or nome_reg_norm in nome_busca_norm:
                    print(f"✅ Fallback encontrou: ID {reg.get('id')} - '{reg.get('nome')}'")
                    return _montar_dados_condominio(reg)
        return None
    except Exception as e:
        print(f"⚠️ Erro no fallback: {e}")
        return None


# ============================================================================
# LISTAR TODOS OS CONDOMÍNIOS DO IXC (para painel admin)
# ============================================================================
def listar_condominios_ixc(config: Dict) -> List[Dict]:
    """Lista todos os condomínios do IXC (para o admin mapear manualmente)."""
    if not config:
        return []
    try:
        host_limpo = _sanitizar_host(config["host"])
        auth_string = base64.b64encode(config["token"].encode('utf-8')).decode('utf-8')
        headers = {
            "Authorization": f"Basic {auth_string}",
            "ixcsoft": "listar",
            "Content-Type": "application/json"
        }
        payload = {
            "qtype": "condominio.id",
            "query": "0",
            "oper": ">",
            "page": "1",
            "rp": "500"
        }
        response = requests.post(
            f"https://{host_limpo}/webservice/v1/condominio",
            json=payload,
            headers=headers,
            timeout=20,
            verify=False
        )
        if response.status_code == 200:
            dados = response.json()
            return dados.get("registros") or dados.get("data") or []
        return []
    except Exception as e:
        print(f"❌ Erro ao listar condomínios IXC: {e}")
        return []


# ============================================================================
# BUSCAR CONDOMÍNIO POR ID IXC
# ============================================================================
def buscar_condominio_por_id_ixc(host_limpo: str, auth_string: str, id_ixc: str) -> Optional[Dict]:
    """Busca dados completos de um condomínio no IXC pelo ID."""
    if not id_ixc:
        return None
    try:
        headers = {
            "Authorization": f"Basic {auth_string}",
            "ixcsoft": "listar",
            "Content-Type": "application/json"
        }
        payload = {
            "qtype": "condominio.id",
            "query": id_ixc,
            "oper": "=",
            "page": "1",
            "rp": "1"
        }
        response = requests.post(
            f"https://{host_limpo}/webservice/v1/condominio",
            json=payload,
            headers=headers,
            timeout=10,
            verify=False
        )
        if response.status_code == 200:
            dados = response.json()
            registros = dados.get("registros") or dados.get("data") or []
            if registros:
                reg = registros[0]
                return _montar_dados_condominio(reg)
        return None
    except Exception as e:
        print(f"⚠️ Erro ao buscar condomínio por ID IXC '{id_ixc}': {e}")
        return None


# ============================================================================
# BUSCAR ID DO CONDOMÍNIO NO CRM
# ============================================================================
def buscar_id_condominio_no_crm(cliente_data: Dict) -> Tuple[Optional[str], Optional[str], Optional[str]]:
    """
    Busca o ID do condomínio no CRM a partir dos dados do cliente.
    
    Retorna: (id_ixc, bloco, apartamento)
    """
    id_ixc = None
    bloco = None
    apto = None
    
    print("\n" + "=" * 70)
    print("🔍 BUSCANDO ID DO CONDOMÍNIO NO CRM")
    print("=" * 70)
    
    # PRIORIDADE 1: Buscar pelo ID do CRM (mais confiável)
    condominio_id_crm = cliente_data.get("condominio_id")
    if condominio_id_crm:
        print(f"📌 PRIORIDADE 1: Buscando por condominio_id = {condominio_id_crm}")
        try:
            from .condominios import get_condominio_by_id
            cond_data = get_condominio_by_id(condominio_id_crm)
            if cond_data:
                id_ixc = cond_data.get("id_ixc")
                if id_ixc:
                    print(f"✅ ID IXC encontrado no CRM: {id_ixc} - '{cond_data.get('nome')}'")
                else:
                    print(f"⚠️ Condomínio ID {condominio_id_crm} não tem id_ixc configurado")
                    print(f"   Nome do condomínio no CRM: '{cond_data.get('nome')}'")
            else:
                print(f"❌ Condomínio ID {condominio_id_crm} não encontrado no CRM")
        except Exception as e:
            print(f"❌ Erro ao buscar condomínio por ID: {e}")
    
    # PRIORIDADE 2: Se não encontrou, buscar pelo nome do condomínio
    if not id_ixc:
        cond_nome = cliente_data.get("condominio_nome")
        if cond_nome:
            print(f"📌 PRIORIDADE 2: Buscando por nome = '{cond_nome}'")
            try:
                from .condominios import get_all_condominios
                condominios = get_all_condominios()
                cond_nome_norm = _normalizar_texto(cond_nome)
                
                for c in condominios:
                    nome_crm_norm = _normalizar_texto(c.get("nome", ""))
                    if nome_crm_norm == cond_nome_norm or cond_nome_norm in nome_crm_norm or nome_crm_norm in cond_nome_norm:
                        id_ixc = c.get("id_ixc")
                        if id_ixc:
                            print(f"✅ ID IXC encontrado no CRM (via nome): {id_ixc} - '{c.get('nome')}'")
                            break
                        else:
                            print(f"⚠️ Condomínio '{c.get('nome')}' encontrado mas não tem id_ixc configurado")
                
                if not id_ixc:
                    print(f"❌ Nenhum condomínio encontrado no CRM com o nome '{cond_nome}'")
            except Exception as e:
                print(f"❌ Erro ao buscar condomínio por nome: {e}")
    
    # PRIORIDADE 3: Se não encontrou, buscar pelo ID_IXC diretamente (se foi passado)
    if not id_ixc:
        cond_id_ixc_direto = cliente_data.get("condominio_id_ixc")
        if cond_id_ixc_direto:
            print(f"📌 PRIORIDADE 3: Buscando por id_ixc direto = {cond_id_ixc_direto}")
            try:
                from .condominios import get_all_condominios
                condominios = get_all_condominios()
                for c in condominios:
                    if str(c.get("id_ixc", "")) == str(cond_id_ixc_direto):
                        id_ixc = str(cond_id_ixc_direto)
                        print(f"✅ ID IXC confirmado no CRM: {id_ixc} - '{c.get('nome')}'")
                        break
                
                if not id_ixc:
                    print(f"⚠️ ID IXC {cond_id_ixc_direto} não encontrado no CRM")
            except Exception as e:
                print(f"❌ Erro ao buscar condomínio por ID IXC: {e}")
    
    # Buscar bloco e apartamento
    bloco = cliente_data.get("bloco")
    apto = cliente_data.get("apartamento")
    
    if bloco:
        print(f"📌 Bloco do cliente: {bloco}")
    if apto:
        print(f"📌 Apartamento do cliente: {apto}")
    
    # Resumo
    if id_ixc:
        print(f"\n✅ CONDOMÍNIO ENCONTRADO: ID IXC = {id_ixc}")
        print(f"   Bloco: {bloco or 'N/A'}")
        print(f"   Apartamento: {apto or 'N/A'}")
    else:
        print("\n❌ CONDOMÍNIO NÃO ENCONTRADO NO CRM")
        print("   O campo id_condominio NÃO será enviado para o IXC")
    
    print("=" * 70 + "\n")
    
    return id_ixc, bloco, apto


# ============================================================================
# OBTER ID IXC DO CONDOMÍNIO (FUNÇÃO OTIMIZADA)
# ============================================================================
def obter_id_ixc_condominio(condominio_id: str, config: Dict) -> Optional[str]:
    """Obtém o ID do IXC para um condomínio de forma otimizada."""
    if not condominio_id or not config:
        return None
    try:
        from .condominios import get_condominio_by_id, update_condominio
        cond_data = get_condominio_by_id(condominio_id)
        if not cond_data:
            print(f"⚠️ Condomínio ID {condominio_id} não encontrado no CRM")
            return None

        # Se já tem ID do IXC, retorna
        if cond_data.get("id_ixc"):
            print(f"✅ ID IXC do condomínio encontrado no CRM: {cond_data['id_ixc']}")
            return cond_data["id_ixc"]

        # Se não tem ID, busca pelo nome no IXC
        nome_cond = cond_data.get("nome")
        if not nome_cond:
            print(f"⚠️ Condomínio ID {condominio_id} não tem nome")
            return None

        print(f"🔍 Buscando condomínio '{nome_cond}' no IXC...")
        host_limpo = _sanitizar_host(config["host"])
        auth_string = base64.b64encode(config["token"].encode('utf-8')).decode('utf-8')
        dados_ixc = buscar_condominio_completo_ixc(host_limpo, auth_string, nome_cond)
        if dados_ixc and dados_ixc.get("id_ixc"):
            id_ixc = dados_ixc["id_ixc"]
            print(f"✅ Condomínio encontrado no IXC! ID: {id_ixc}")
            try:
                update_condominio(condominio_id, {"id_ixc": id_ixc})
                print(f"💾 ID IXC salvo no CRM para o condomínio {condominio_id}")
            except Exception as e:
                print(f"⚠️ Não foi possível salvar ID IXC no CRM: {e}")
            return id_ixc
        else:
            print(f"⚠️ Condomínio '{nome_cond}' NÃO encontrado no IXC")
            return None
    except Exception as e:
        print(f"⚠️ Erro ao obter ID IXC do condomínio: {e}")
        return None


# ============================================================================
# SINCRONIZAR CONDOMÍNIO DO CRM COM IXC
# ============================================================================
def sincronizar_condominio_crm_com_ixc(condominio_id: str, config: Dict) -> Dict:
    """Sincroniza um condomínio específico do CRM com o IXC."""
    resultado = {
        "sucesso": False,
        "condominio_id": condominio_id,
        "id_ixc": None,
        "dados_ixc": None,
        "alteracoes": [],
        "erro": None
    }
    try:
        from .condominios import get_condominio_by_id, update_condominio
        cond_crm = get_condominio_by_id(condominio_id)
        if not cond_crm:
            resultado["erro"] = "Condomínio não encontrado no CRM"
            return resultado

        host_limpo = _sanitizar_host(config["host"])
        auth_string = base64.b64encode(config["token"].encode('utf-8')).decode('utf-8')

        dados_ixc = None
        if cond_crm.get("id_ixc"):
            dados_ixc = buscar_condominio_por_id_ixc(host_limpo, auth_string, cond_crm["id_ixc"])
            if dados_ixc:
                resultado["id_ixc"] = dados_ixc["id_ixc"]
                print(f"✅ Condomínio encontrado pelo ID IXC: {dados_ixc['id_ixc']}")

        if not dados_ixc and cond_crm.get("nome"):
            dados_ixc = buscar_condominio_completo_ixc(host_limpo, auth_string, cond_crm["nome"])
            if dados_ixc:
                resultado["id_ixc"] = dados_ixc["id_ixc"]
                print(f"✅ Condomínio encontrado pelo nome: '{cond_crm['nome']}' -> ID IXC: {dados_ixc['id_ixc']}")

        if dados_ixc:
            resultado["dados_ixc"] = dados_ixc
            resultado["sucesso"] = True
            updates = {
                "id_ixc": dados_ixc["id_ixc"],
                "ultima_sincronizacao_ixc": datetime.now()
            }
            if dados_ixc.get("endereco") and dados_ixc["endereco"] != cond_crm.get("endereco"):
                updates["endereco"] = dados_ixc["endereco"]
                resultado["alteracoes"].append(f"endereco: '{cond_crm.get('endereco')}' -> '{dados_ixc['endereco']}'")
            if dados_ixc.get("numero") and str(dados_ixc["numero"]) != str(cond_crm.get("numero")):
                updates["numero"] = dados_ixc["numero"]
                resultado["alteracoes"].append(f"numero: '{cond_crm.get('numero')}' -> '{dados_ixc['numero']}'")
            if dados_ixc.get("bairro") and dados_ixc["bairro"] != cond_crm.get("bairro"):
                updates["bairro"] = dados_ixc["bairro"]
                resultado["alteracoes"].append(f"bairro: '{cond_crm.get('bairro')}' -> '{dados_ixc['bairro']}'")
            if dados_ixc.get("cidade") and dados_ixc["cidade"] != cond_crm.get("cidade"):
                updates["cidade"] = dados_ixc["cidade"]
                resultado["alteracoes"].append(f"cidade: '{cond_crm.get('cidade')}' -> '{dados_ixc['cidade']}'")
            if dados_ixc.get("uf") and dados_ixc["uf"] != cond_crm.get("uf"):
                updates["uf"] = dados_ixc["uf"]
                resultado["alteracoes"].append(f"uf: '{cond_crm.get('uf')}' -> '{dados_ixc['uf']}'")
            if dados_ixc.get("cep") and dados_ixc["cep"] != cond_crm.get("cep"):
                updates["cep"] = dados_ixc["cep"]
                resultado["alteracoes"].append(f"cep: '{cond_crm.get('cep')}' -> '{dados_ixc['cep']}'")
            if dados_ixc.get("bloco_padrao") and dados_ixc["bloco_padrao"] != cond_crm.get("bloco_padrao"):
                updates["bloco_padrao"] = dados_ixc["bloco_padrao"]
                resultado["alteracoes"].append(f"bloco_padrao: '{cond_crm.get('bloco_padrao')}' -> '{dados_ixc['bloco_padrao']}'")
            if dados_ixc.get("apartamento_padrao") and dados_ixc["apartamento_padrao"] != cond_crm.get("apartamento_padrao"):
                updates["apartamento_padrao"] = dados_ixc["apartamento_padrao"]
                resultado["alteracoes"].append(f"apartamento_padrao: '{cond_crm.get('apartamento_padrao')}' -> '{dados_ixc['apartamento_padrao']}'")

            if updates:
                update_condominio(condominio_id, updates)
                resultado["alteracoes"].append(f"id_ixc: '{cond_crm.get('id_ixc')}' -> '{dados_ixc['id_ixc']}'")
                print(f"✅ Condomínio '{cond_crm['nome']}' atualizado no CRM com dados do IXC")
            else:
                print(f"ℹ️ Condomínio '{cond_crm['nome']}' já está sincronizado com o IXC")
        else:
            resultado["sucesso"] = False
            resultado["erro"] = f"Condomínio '{cond_crm.get('nome')}' não encontrado no IXC"
            print(f"⚠️ Condomínio '{cond_crm.get('nome')}' NÃO encontrado no IXC")
        return resultado
    except Exception as e:
        resultado["erro"] = str(e)
        print(f"❌ Erro ao sincronizar condomínio {condominio_id}: {e}")
        return resultado


def sincronizar_todos_condominios_com_ixc(config: Dict) -> Dict:
    """Sincroniza todos os condomínios do CRM com o IXC."""
    from .condominios import get_all_condominios
    resultados = {
        "total": 0,
        "sincronizados": 0,
        "nao_encontrados": 0,
        "erros": 0,
        "detalhes": []
    }
    try:
        condominios = get_all_condominios()
        resultados["total"] = len(condominios)
        for cond in condominios:
            cond_id = cond.get("_id")
            if not cond_id:
                continue
            resultado = sincronizar_condominio_crm_com_ixc(str(cond_id), config)
            if resultado["sucesso"]:
                resultados["sincronizados"] += 1
                resultados["detalhes"].append({
                    "nome": cond.get("nome"),
                    "id_ixc": resultado.get("id_ixc"),
                    "alteracoes": resultado.get("alteracoes", []),
                    "status": "sincronizado"
                })
            elif resultado.get("erro") and "não encontrado" in resultado["erro"]:
                resultados["nao_encontrados"] += 1
                resultados["detalhes"].append({
                    "nome": cond.get("nome"),
                    "erro": resultado["erro"],
                    "status": "nao_encontrado"
                })
            else:
                resultados["erros"] += 1
                resultados["detalhes"].append({
                    "nome": cond.get("nome"),
                    "erro": resultado.get("erro", "Erro desconhecido"),
                    "status": "erro"
                })
        return resultados
    except Exception as e:
        return {"erro": str(e)}


# ============================================================================
# BUSCAR CLIENTE POR CPF NO IXC
# ============================================================================
def buscar_cliente_ixc_por_cpf(cpf: str, config: Dict) -> Optional[str]:
    """Busca cliente no IXC pelo CPF."""
    cpf_digits = "".join(filter(str.isdigit, str(cpf)))
    if not cpf_digits or len(cpf_digits) < 11:
        return None
    cpf_fmt = fmt_cpf(cpf_digits)
    host_limpo = _sanitizar_host(config["host"])
    url = f"https://{host_limpo}/webservice/v1/cliente"
    auth_string = base64.b64encode(config["token"].encode('utf-8')).decode('utf-8')
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Basic {auth_string}",
        "ixcsoft": "listar"
    }
    try:
        for cpf_query in [cpf_fmt, cpf_digits]:
            payload = {
                "qtype": "cliente.cnpj_cpf",
                "query": cpf_query,
                "oper": "=",
                "page": "1",
                "rp": "1"
            }
            response = requests.post(url, json=payload, headers=headers, timeout=15, verify=False)
            if response.status_code == 200:
                dados = response.json()
                regs = dados.get("registros") or dados.get("data") or []
                if regs:
                    return str(regs[0].get("id"))
        return None
    except Exception as e:
        print(f"⚠️ Erro ao buscar cliente: {e}")
        return None


def buscar_dados_cliente_ixc(id_ixc: str, config: Dict) -> Optional[Dict]:
    """Busca os dados atuais de um cliente no IXC."""
    if not id_ixc:
        return None
    host_limpo = _sanitizar_host(config["host"])
    url = f"https://{host_limpo}/webservice/v1/cliente"
    auth_string = base64.b64encode(config["token"].encode('utf-8')).decode('utf-8')
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Basic {auth_string}",
        "ixcsoft": "listar"
    }
    payload = {
        "qtype": "cliente.id",
        "query": id_ixc,
        "oper": "=",
        "page": "1",
        "rp": "1"
    }
    try:
        response = requests.post(url, json=payload, headers=headers, timeout=15, verify=False)
        if response.status_code == 200:
            dados = response.json()
            regs = dados.get("registros") or dados.get("data") or []
            if regs:
                return regs[0]
        return None
    except Exception as e:
        print(f"⚠️ Erro ao buscar dados do cliente IXC: {e}")
        return None


def verificar_cliente_existente_ixc(cpf: str, config: Dict) -> Dict:
    """Verifica se um cliente com este CPF já existe no IXC."""
    resultado = {
        "existe": False,
        "id_ixc": None,
        "dados": None,
        "erro": None
    }
    if not cpf or not config:
        return resultado
    try:
        id_ixc = buscar_cliente_ixc_por_cpf(cpf, config)
        if id_ixc:
            resultado["existe"] = True
            resultado["id_ixc"] = id_ixc
            try:
                dados = buscar_dados_cliente_ixc(id_ixc, config)
                if dados:
                    resultado["dados"] = {
                        "id": dados.get("id"),
                        "razao": dados.get("razao"),
                        "nome_social": dados.get("nome_social"),
                        "cnpj_cpf": dados.get("cnpj_cpf"),
                        "email": dados.get("email"),
                        "fone": dados.get("fone"),
                        "endereco": dados.get("endereco"),
                        "numero": dados.get("numero"),
                        "bairro": dados.get("bairro"),
                        "cidade": dados.get("cidade"),
                        "uf": dados.get("uf"),
                        "cep": dados.get("cep"),
                        "ativo": dados.get("ativo"),
                        "id_condominio": dados.get("id_condominio"),
                        "bloco": dados.get("bloco"),
                        "apartamento": dados.get("apartamento"),
                    }
            except Exception as e:
                print(f"⚠️ Erro ao buscar dados detalhados: {e}")
    except Exception as e:
        resultado["erro"] = str(e)
        print(f"⚠️ Erro ao verificar cliente no IXC: {e}")
    return resultado


# ============================================================================
# 🔑 FUNÇÃO DE ENVIO BASEADA NO TESTE R6 (QUE FUNCIONOU)
# ============================================================================
def enviar_cliente_ixc_r6(payload: Dict, config: Dict) -> Tuple[bool, Optional[str], Optional[str]]:
    """
    Envia cliente para o IXC usando a lógica exata do Teste R6.
    Esta função substitui o método de envio anterior que estava falhando.
    
    Retorna: (sucesso, id_ixc, mensagem_erro)
    """
    try:
        host_limpo = _sanitizar_host(config["host"])
        url = f"https://{host_limpo}/webservice/v1/cliente"
        auth_string = base64.b64encode(config["token"].encode('utf-8')).decode('utf-8')
        
        headers = {
            'Authorization': f'Basic {auth_string}',
            'ixcsoft': 'inserir',
            'Content-Type': 'application/json'
        }
        
        print("\n" + "=" * 70)
        print("🚀 ENVIANDO CLIENTE (MÉTODO R6)")
        print("=" * 70)
        
        # Log dos dados enviados (sem CPF completo)
        dados_log = payload.copy()
        if 'cnpj_cpf' in dados_log:
            dados_log['cnpj_cpf'] = '***' + dados_log['cnpj_cpf'][-4:]
        print(f"📤 Enviando dados: {json.dumps(dados_log, indent=2, ensure_ascii=False)}")
        
        response = requests.post(
            url,
            json=payload,
            headers=headers,
            timeout=30,
            verify=False
        )
        
        print(f"\n📥 Status Code: {response.status_code}")
        print(f"📥 Resposta raw: {response.text[:500]}")
        
        # Tentar parsear a resposta
        try:
            resposta = response.json()
        except:
            return False, None, f"Resposta não é JSON: {response.text[:200]}"
        
        # Verificar se houve erro
        if response.status_code not in [200, 201]:
            if 'message' in resposta:
                return False, None, f"Erro HTTP {response.status_code}: {resposta['message']}"
            return False, None, f"Erro HTTP {response.status_code}: {response.text[:200]}"
        
        # Verificar se a resposta indica sucesso
        if 'type' in resposta and resposta['type'] == 'error':
            return False, None, f"API retornou erro: {resposta.get('message', 'Erro desconhecido')}"
        
        if 'success' in resposta and resposta['success'] == False:
            return False, None, f"API retornou erro: {resposta.get('message', 'Erro desconhecido')}"
        
        # Verificar se temos o ID do cliente
        cliente_id = resposta.get('id') or resposta.get('cliente_id')
        if cliente_id:
            print(f"✅ Cliente criado com sucesso! ID: {cliente_id}")
            return True, str(cliente_id), None
        else:
            # Mesmo sem ID, se não houve erro, consideramos sucesso
            print(f"✅ Cliente criado, mas sem ID na resposta. Resposta: {resposta}")
            return True, "ok", None
            
    except requests.exceptions.Timeout:
        return False, None, "Timeout na requisição"
    except requests.exceptions.ConnectionError:
        return False, None, "Erro de conexão com o servidor IXC"
    except Exception as e:
        return False, None, f"Erro inesperado: {str(e)}"


# ============================================================================
# 🔧 CONSTRUIR PAYLOAD ESTILO TESTE R6 (COM BUSCA NO CRM)
# ============================================================================
def construir_payload_estilo_r6(cliente_data: Dict, config: Dict) -> Tuple[Dict, bool]:
    """
    Constrói payload EXATAMENTE como no Teste 5 do R6.
    O id_condominio é BUSCADO na base de dados do CRM.
    
    Retorna: (payload, condominio_vinculado)
    """
    from datetime import datetime
    
    # Extrair dados do cliente
    nome = str(cliente_data.get("nome_completo", "TESTE R6"))
    cpf_raw = "".join(filter(str.isdigit, str(cliente_data.get("cpf", ""))))
    celular = str(cliente_data.get("celular", "21999999999"))
    email = str(cliente_data.get("email", f"r6_{datetime.now().strftime('%H%M%S')}@tracecom.com.br"))
    
    # Formatar como no Teste 5
    cpf_formatado = fmt_cpf(cpf_raw)
    telefone_formatado = fmt_fone(celular)
    cep_formatado = fmt_cep(cliente_data.get("cep", "20521130"))
    
    # Data/hora para nome único
    ts = datetime.now().strftime("%H%M%S")
    nome_teste = f"{nome} {ts}"
    
    # ========== BUSCAR ID DO CONDOMÍNIO NO CRM ==========
    id_ixc_condominio, bloco, apto = buscar_id_condominio_no_crm(cliente_data)
    
    # ========== PAYLOAD IGUAL AO TESTE 5 ==========
    payload = {
        # Dados básicos obrigatórios
        "ativo": "S",
        "tipo_pessoa": "F",
        "tipo_cliente_scm": "01",
        "filial_id": config.get("filial_id", "1"),
        "filtra_filial": "S",
        
        # Dados pessoais
        "razao": nome_teste,
        "nome_social": nome_teste,
        "fantasia": nome_teste,
        "cnpj_cpf": cpf_formatado,
        "ie_identidade": "1234567",
        "data_nascimento": "1990-06-01",
        "nacionalidade": "Brasileiro",
        "contribuinte_icms": "N",
        
        # Contato
        "fone": telefone_formatado,
        "telefone_celular": telefone_formatado,
        "whatsapp": telefone_formatado,
        "email": email,
        "hotsite_email": email,
        
        # Endereço
        "cep": cep_formatado,
        "endereco": str(cliente_data.get("endereco", "Rua Conde de Bonfim")),
        "numero": str(cliente_data.get("numero", "255")),
        "bairro": str(cliente_data.get("bairro", "Tijuca")),
        "cidade": ID_CIDADE_RJ,
        "uf": ID_UF_RJ,
        "tipo_localidade": "U",
        
        # Configurações de acesso
        "senha": "123456",
        "acesso_automatico_central": "S",
        "alterar_senha_primeiro_acesso": "P",
        "senha_hotsite_md5": "N",
        "hotsite_acesso": "2",
        
        # Configurações de cobrança
        "tipo_assinante": "3",
        "participa_cobranca": "S",
        "participa_pre_cobranca": "S",
        "cob_envia_email": "S",
        "cob_envia_sms": "S",
        "status_prospeccao": "C",
        
        # Configurações fiscais
        "iss_classificacao_padrao": "99",
        
        # Observação
        "obs": f"Integração CRM - {datetime.now().strftime('%d/%m/%Y %H:%M')}",
    }
    
    # ========== ADICIONAR CONDOMÍNIO (SÓ SE TIVER ID IXC) ==========
    condominio_vinculado = False
    if id_ixc_condominio:
        payload["id_condominio"] = str(id_ixc_condominio)
        condominio_vinculado = True
        print(f"✅ Condomínio ID IXC adicionado ao payload: {id_ixc_condominio}")
        
        if bloco:
            payload["bloco"] = str(bloco)
            print(f"✅ Bloco adicionado ao payload: {bloco}")
        
        if apto:
            payload["apartamento"] = str(apto)
            print(f"✅ Apartamento adicionado ao payload: {apto}")
    else:
        print("⚠️ CONDOMÍNIO NÃO VINCULADO - id_condominio NÃO será enviado ao IXC")
    
    return payload, condominio_vinculado


# ============================================================================
# 🔧 FUNÇÃO DE FALLBACK - TESTE R6 DIRETO (CASO A CONSTRUÇÃO FALHE)
# ============================================================================
def enviar_cliente_ixc_direto_r6(cliente_data: Dict, config: Dict) -> Tuple[bool, Optional[str], Optional[str]]:
    """
    Envia cliente diretamente usando a estrutura exata do Teste R6.
    Esta é uma função de FALLBACK caso a construção normal falhe.
    """
    try:
        # Extrair dados
        cpf_digits = "".join(re.sub(r'\D', '', str(cliente_data.get("cpf", ""))))
        nome = str(cliente_data.get("nome_completo", "TESTE R6 FALLBACK"))
        celular = str(cliente_data.get("celular", "21999999999"))
        email = str(cliente_data.get("email", f"fallback_{datetime.now().strftime('%H%M%S')}@tracecom.com.br"))
        
        # ========== BUSCAR ID DO CONDOMÍNIO NO CRM ==========
        id_ixc_condominio, bloco, apto = buscar_id_condominio_no_crm(cliente_data)
        
        # Construir payload exatamente como no Teste R6
        payload = {
            # Dados básicos obrigatórios
            "ativo": "S",
            "tipo_pessoa": "F",
            "tipo_cliente_scm": "01",
            "filial_id": config.get("filial_id", "1"),
            "filtra_filial": "S",
            
            # Dados pessoais
            "razao": nome,
            "nome_social": nome,
            "fantasia": nome,
            "cnpj_cpf": fmt_cpf(cpf_digits),
            "ie_identidade": "1234567",
            "data_nascimento": "1990-06-01",
            "nacionalidade": "Brasileiro",
            "contribuinte_icms": "N",
            
            # Contato
            "fone": fmt_fone(celular),
            "telefone_celular": fmt_fone(celular),
            "whatsapp": fmt_fone(celular),
            "email": email,
            "hotsite_email": email,
            
            # Endereço
            "cep": fmt_cep(cliente_data.get("cep", "20521130")),
            "endereco": str(cliente_data.get("endereco", "Rua Conde de Bonfim")),
            "numero": str(cliente_data.get("numero", "255")),
            "bairro": str(cliente_data.get("bairro", "Tijuca")),
            "cidade": ID_CIDADE_RJ,
            "uf": ID_UF_RJ,
            "tipo_localidade": "U",
            
            # Configurações de acesso
            "senha": "123456",
            "acesso_automatico_central": "S",
            "alterar_senha_primeiro_acesso": "P",
            "senha_hotsite_md5": "N",
            "hotsite_acesso": "2",
            
            # Configurações de cobrança
            "tipo_assinante": "3",
            "participa_cobranca": "S",
            "participa_pre_cobranca": "S",
            "cob_envia_email": "S",
            "cob_envia_sms": "S",
            "status_prospeccao": "C",
            
            # Configurações fiscais
            "iss_classificacao_padrao": "99",
            
            # Observação
            "obs": f"Fallback R6 - {datetime.now().strftime('%d/%m/%Y %H:%M')}",
        }
        
        # ========== ADICIONAR CONDOMÍNIO SE TIVER ==========
        if id_ixc_condominio:
            payload["id_condominio"] = str(id_ixc_condominio)
            print(f"✅ Condomínio ID IXC adicionado (fallback): {id_ixc_condominio}")
        
        if bloco:
            payload["bloco"] = str(bloco)
            print(f"✅ Bloco adicionado (fallback): {bloco}")
        
        if apto:
            payload["apartamento"] = str(apto)
            print(f"✅ Apartamento adicionado (fallback): {apto}")
        
        # ========== ENVIAR ==========
        return enviar_cliente_ixc_r6(payload, config)
        
    except Exception as e:
        return False, None, f"Erro no fallback R6: {str(e)}"


# ============================================================================
# CONSTRUÇÃO DO PAYLOAD — VERSÃO ORIGINAL (MANTIDA PARA COMPATIBILIDADE)
# ============================================================================
def construir_payload_ixc(cliente_data: Dict, config: Dict) -> Tuple[Dict, Optional[str], bool]:
    """
    Constrói payload para o IXC (versão original).
    Mantida para compatibilidade com código existente.
    Retorna: (payload, mensagem_erro, condominio_vinculado)
    """
    def safe(val) -> str:
        return str(val).strip() if val is not None else ""

    # ========== 1. SANITIZAÇÃO DOS CAMPOS ==========
    cpf_raw = safe(cliente_data.get("cpf"))
    cpf_digits = "".join(filter(str.isdigit, cpf_raw))
    cpf = fmt_cpf(cpf_digits)
    if not validar_cpf(cpf_digits):
        return {}, f"CPF inválido: '{cpf_raw}'. Verifique os dígitos.", False

    nome = safe(cliente_data.get("nome_completo"))
    if not nome:
        return {}, "Nome completo é obrigatório", False

    celular_raw = safe(cliente_data.get("celular"))
    celular = fmt_fone(celular_raw)
    if not celular or len(celular) < 10:
        return {}, f"Telefone inválido: '{celular_raw}'. Use formato (DDD)NÚMERO", False

    email = safe(cliente_data.get("email"))
    if not email:
        return {}, "Email é obrigatório", False

    # ========== 2. ENDEREÇO ==========
    cep_raw = safe(cliente_data.get("cep"))
    if cep_raw:
        cep = fmt_cep(cep_raw)
    else:
        cep = "20521-130"
    endereco = safe(cliente_data.get("endereco"))
    numero = safe(cliente_data.get("numero"))
    bairro = safe(cliente_data.get("bairro"))
    complemento = safe(cliente_data.get("complemento"))
    cidade_nome = safe(cliente_data.get("cidade", "Rio de Janeiro"))
    uf_sigla = safe(cliente_data.get("uf", "RJ")).upper()

    host_limpo = _sanitizar_host(config["host"])
    auth_string = base64.b64encode(config["token"].encode('utf-8')).decode('utf-8')
    cidade_id, uf_id = _buscar_id_cidade(host_limpo, auth_string, cidade_nome, uf_sigla)

    # ========== 3. DATA DE NASCIMENTO ==========
    data_nasc = ""
    raw_nasc = cliente_data.get("data_nascimento")
    if raw_nasc:
        for fmt in ["%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y"]:
            try:
                dt = datetime.strptime(str(raw_nasc).strip(), fmt)
                data_nasc = dt.strftime("%Y-%m-%d")
                break
            except ValueError:
                continue

    # ========== 4. PAYLOAD FINAL ==========
    payload = {
        "ativo": "S",
        "tipo_pessoa": "F",
        "tipo_cliente_scm": "01",
        "filial_id": config.get("filial_id", "1"),
        "filtra_filial": "S",
        "razao": nome,
        "nome_social": nome,
        "fantasia": nome,
        "cnpj_cpf": cpf,
        "ie_identidade": safe(cliente_data.get("rg", "1234567")),
        "data_nascimento": data_nasc if data_nasc else "1990-06-01",
        "nacionalidade": "Brasileiro",
        "contribuinte_icms": "N",
        "fone": celular,
        "telefone_celular": celular,
        "whatsapp": celular,
        "email": email,
        "hotsite_email": email,
        "cep": cep,
        "endereco": endereco if endereco else "Rua Conde de Bonfim",
        "numero": numero if numero else "255",
        "bairro": bairro if bairro else "Tijuca",
        "cidade": cidade_id,
        "uf": uf_id,
        "tipo_localidade": "U",
        "senha": "123456",
        "acesso_automatico_central": "S",
        "alterar_senha_primeiro_acesso": "P",
        "senha_hotsite_md5": "N",
        "hotsite_acesso": "2",
        "tipo_assinante": "3",
        "participa_cobranca": "S",
        "participa_pre_cobranca": "S",
        "cob_envia_email": "S",
        "cob_envia_sms": "S",
        "status_prospeccao": "C",
        "iss_classificacao_padrao": "99",
        "obs": safe(cliente_data.get("observacoes", f"Cadastro CRM - {datetime.now().strftime('%d/%m/%Y')}"))
    }
    if complemento:
        payload["complemento"] = complemento

    # ========== 5. CONDOMÍNIO ==========
    # Usar a nova função de busca no CRM
    id_ixc_condominio, bloco, apto = buscar_id_condominio_no_crm(cliente_data)
    
    condominio_vinculado = False
    if id_ixc_condominio:
        payload["id_condominio"] = str(id_ixc_condominio)
        condominio_vinculado = True
        if bloco:
            payload["bloco"] = str(bloco)
        if apto:
            payload["apartamento"] = str(apto)

    # ========== 6. REMOVER CAMPOS VAZIOS ==========
    payload = {k: v for k, v in payload.items() if v not in (None, "", " ", [], {})}

    return payload, None, condominio_vinculado


# ============================================================================
# FUNÇÃO PRINCIPAL - ENVIAR CLIENTE PARA IXC (COM FALLBACK R6)
# ============================================================================
def enviar_cliente_para_ixc(cliente_data: Dict) -> Tuple[bool, Optional[str], Optional[str], Optional[bool]]:
    """
    Envia cliente para o IXC.
    
    Estratégia:
    1. Tenta construir payload normalmente
    2. Envia usando método R6
    3. Se falhar, usa fallback direto R6
    """
    print("\n" + "=" * 70)
    print("🚀 INICIANDO INTEGRAÇÃO COM IXC")
    print("=" * 70)

    config = get_ixc_config()
    if not config:
        return False, None, "Configuração do IXC não encontrada", None

    # ========== VERIFICAR SE CLIENTE JÁ EXISTE ==========
    cpf = cliente_data.get("cpf", "")
    if cpf and len("".join(filter(str.isdigit, str(cpf)))) >= 11:
        print(f"🔍 Verificando se CPF {cpf} já existe no IXC...")
        id_existente = buscar_cliente_ixc_por_cpf(cpf, config)
        if id_existente:
            print(f"✅ Cliente já existe no IXC com ID: {id_existente}")
            return True, id_existente, None, None

    # ========== TENTATIVA 1: Payload estilo R6 + Método R6 ==========
    print("\n📌 TENTATIVA 1: Payload estilo R6 + Envio R6")
    payload, condominio_vinculado = construir_payload_estilo_r6(cliente_data, config)
    
    # Log do payload (sem dados sensíveis)
    payload_log = payload.copy()
    if "cnpj_cpf" in payload_log:
        payload_log["cnpj_cpf"] = "***" + payload_log["cnpj_cpf"][-4:]
    
    print(f"\n📤 PAYLOAD FINAL (estilo Teste 5):")
    print(f"   id_condominio: {payload.get('id_condominio', '❌ NÃO ENVIADO')}")
    print(f"   bloco: {payload.get('bloco', '❌ NÃO ENVIADO')}")
    print(f"   apartamento: {payload.get('apartamento', '❌ NÃO ENVIADO')}")
    print(f"   cidade: {payload.get('cidade')}")
    print(f"   uf: {payload.get('uf')}")
    print(f"   cnpj_cpf: {payload.get('cnpj_cpf')}")
    
    sucesso, id_ixc, erro_msg = enviar_cliente_ixc_r6(payload, config)
    
    if sucesso:
        print(f"✅ Cliente integrado com sucesso via método R6! ID: {id_ixc}")
        return sucesso, id_ixc, erro_msg, condominio_vinculado
    else:
        print(f"⚠️ Falha no envio R6: {erro_msg}")
    
    # ========== TENTATIVA 2: Fallback direto R6 ==========
    print("\n📌 TENTATIVA 2: Fallback direto R6 (ignorando construção normal)")
    sucesso, id_ixc, erro_msg = enviar_cliente_ixc_direto_r6(cliente_data, config)
    
    if sucesso:
        print(f"✅ Cliente integrado com sucesso via FALLBACK R6! ID: {id_ixc}")
    else:
        print(f"❌ Falha no fallback R6: {erro_msg}")
    
    return sucesso, id_ixc, erro_msg, condominio_vinculado


# ============================================================================
# 🔄 NOVA FUNÇÃO: INTEGRAÇÃO SOB DEMANDA (PARA EDITAR/COMPLETAR)
# ============================================================================
def enviar_cliente_para_ixc_com_verificacao(cliente_data: Dict, cliente_id, clientes_collection) -> Dict:
    """
    Verifica se o cliente existe no IXC e:
    - Se existir: vincula o ID ao CRM
    - Se não existir: cria no IXC
    
    Esta função é usada quando editamos um cadastro simples ou completamos
    um cadastro que ainda não foi integrado.
    
    Retorna: {
        "sucesso": bool,
        "mensagem": str,
        "id_ixc": Optional[str],
        "acao": "vinculado" | "criado" | "ja_integrado" | "erro"
    }
    """
    resultado = {
        "sucesso": False,
        "mensagem": "",
        "id_ixc": None,
        "acao": "erro"
    }
    
    config = get_ixc_config()
    if not config:
        resultado["mensagem"] = "Configuração do IXC não encontrada"
        return resultado
    
    # Verificar se cliente já está integrado
    if cliente_data.get("integrado_ixc") and cliente_data.get("id_ixc"):
        resultado["sucesso"] = True
        resultado["mensagem"] = f"Cliente já está integrado ao IXC (ID: {cliente_data['id_ixc']})"
        resultado["id_ixc"] = cliente_data["id_ixc"]
        resultado["acao"] = "ja_integrado"
        return resultado
    
    # Buscar CPF
    cpf = cliente_data.get("cpf")
    if not cpf:
        resultado["mensagem"] = "CPF não informado"
        return resultado
    
    cpf_digits = "".join(filter(str.isdigit, str(cpf)))
    if len(cpf_digits) < 11:
        resultado["mensagem"] = f"CPF inválido: '{cpf}'"
        return resultado
    
    # Verificar se já existe no IXC
    print(f"🔍 Verificando CPF {cpf_digits} no IXC...")
    id_existente = buscar_cliente_ixc_por_cpf(cpf_digits, config)
    
    if id_existente:
        # Cliente já existe - apenas vincular
        print(f"✅ Cliente já existe no IXC com ID: {id_existente}")
        try:
            clientes_collection.update_one(
                {"_id": cliente_id},
                {"$set": {
                    "integrado_ixc": True,
                    "id_ixc": id_existente,
                    "data_integracao_ixc": datetime.now()
                }}
            )
            resultado["sucesso"] = True
            resultado["mensagem"] = f"Cliente vinculado ao IXC com sucesso! ID: {id_existente}"
            resultado["id_ixc"] = id_existente
            resultado["acao"] = "vinculado"
            return resultado
        except Exception as e:
            resultado["mensagem"] = f"Erro ao vincular cliente: {str(e)}"
            return resultado
    
    # Cliente não existe - tentar criar
    print(f"🔄 Cliente não encontrado no IXC. Tentando criar...")
    sucesso, id_ixc, erro_msg, condominio_vinculado = enviar_cliente_para_ixc(cliente_data)
    
    if sucesso:
        try:
            update_fields = {
                "integrado_ixc": True,
                "data_integracao_ixc": datetime.now()
            }
            if id_ixc and id_ixc not in ["ok", "existente"]:
                update_fields["id_ixc"] = id_ixc
            
            # Registrar se o condomínio não foi vinculado
            if condominio_vinculado is False:
                update_fields["condominio_vinculado_ixc"] = False
            
            clientes_collection.update_one(
                {"_id": cliente_id},
                {"$set": update_fields}
            )
            
            resultado["sucesso"] = True
            resultado["mensagem"] = f"Cliente integrado ao IXC com sucesso! ID: {id_ixc or 'ok'}"
            resultado["id_ixc"] = id_ixc
            resultado["acao"] = "criado"
            
            if condominio_vinculado is False:
                resultado["mensagem"] += " ⚠️ Condomínio não vinculado - verifique manualmente."
            
            return resultado
        except Exception as e:
            resultado["mensagem"] = f"Cliente criado no IXC mas erro ao atualizar CRM: {str(e)}"
            resultado["id_ixc"] = id_ixc
            return resultado
    else:
        # Falha na criação
        resultado["mensagem"] = f"Falha ao criar cliente no IXC: {erro_msg or 'Erro desconhecido'}"
        # Registrar tentativa
        try:
            clientes_collection.update_one(
                {"_id": cliente_id},
                {"$set": {
                    "integrado_ixc": False,
                    "erro_integracao_ixc": erro_msg,
                    "ultima_tentativa_integracao": datetime.now()
                }}
            )
        except:
            pass
        return resultado


# ============================================================================
# REGISTRAR PENDÊNCIA DE INTEGRAÇÃO
# ============================================================================
def registrar_pendencia_integracao(cliente_id, cliente_data, erro_msg):
    """Registra cliente para sincronização posterior."""
    try:
        clientes_collection = st.session_state.get("clientes_collection")
        if clientes_collection:
            clientes_collection.update_one(
                {"_id": cliente_id},
                {"$set": {
                    "integrado_ixc": False,
                    "erro_integracao_ixc": erro_msg,
                    "tentativas_integracao": 1,
                    "ultima_tentativa_integracao": datetime.now()
                }}
            )
            print(f"📝 Pendência registrada para cliente {cliente_id}")
    except Exception as e:
        print(f"❌ Erro ao registrar pendência: {e}")


# ============================================================================
# TESTE DE CONEXÃO
# ============================================================================
def testar_conexao_ixc() -> Dict:
    """Testa conexão com o IXC."""
    config = get_ixc_config()
    if not config:
        return {"sucesso": False, "erro": "Configuração não encontrada"}
    host_limpo = _sanitizar_host(config["host"])
    url = f"https://{host_limpo}/webservice/v1/cliente"
    auth_string = base64.b64encode(config["token"].encode('utf-8')).decode('utf-8')
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Basic {auth_string}",
        "ixcsoft": "listar"
    }
    try:
        response = requests.post(
            url,
            json={"qtype": "cliente.id", "query": "1", "oper": ">", "page": "1", "rp": "1"},
            headers=headers,
            timeout=10,
            verify=False
        )
        if response.status_code in [200, 201]:
            return {"sucesso": True, "detalhe": f"Status: {response.status_code}"}
        else:
            return {"sucesso": False, "erro": f"HTTP {response.status_code}"}
    except Exception as e:
        return {"sucesso": False, "erro": str(e)}


def render_teste_conexao():
    """Renderiza um painel de teste de conexão com o IXC."""
    st.subheader("🔌 Teste de Conexão com IXCsoft")
    if st.button("🧪 Testar Conexão", key="testar_ixc"):
        with st.spinner("Testando conexão..."):
            resultado = testar_conexao_ixc()
            if resultado["sucesso"]:
                st.success("🎉 Conexão com IXC funcionando corretamente!")
                st.json(resultado)
            else:
                st.error(f"❌ Falha na conexão: {resultado.get('erro', 'Erro desconhecido')}")
                st.info("""
                **Possíveis causas:**
                1. O host do IXC não está acessível publicamente
                2. O token está inválido ou expirado
                3. Firewall bloqueando a conexão
                4. O Streamlit Cloud não consegue acessar sua rede interna
                **Soluções:**
                - Verifique se o IXC está exposto na internet
                - Considere usar um Proxy ou VPN
                - Entre em contato com o suporte do IXC
                """)


# ============================================================================
# PAINEL DE SINCRONIZAÇÃO DE CONDOMÍNIOS (ATUALIZADO)
# ============================================================================
def render_painel_sincronizacao_condominios():
    """Renderiza painel para sincronizar condomínios com o IXC."""
    st.subheader("🏢 Sincronização de Condomínios com IXC")
    st.info("""
    **Como funciona:**
    1. O sistema verifica cada condomínio no IXC pelo nome (busca flexível)
    2. Se encontrado, atualiza o CRM com os dados do IXC (endereço, CEP, etc.)
    3. Se não encontrado, mantém os dados do CRM
    4. O ID do IXC é salvo no CRM para futuras referências
    """)

    col1, col2 = st.columns(2)
    with col1:
        if st.button("🔄 Sincronizar Todos os Condomínios", type="primary"):
            with st.spinner("Sincronizando condomínios com o IXC..."):
                config = get_ixc_config()
                if not config:
                    st.error("❌ Configuração do IXC não encontrada")
                else:
                    resultados = sincronizar_todos_condominios_com_ixc(config)
                    if "erro" in resultados:
                        st.error(f"❌ Erro na sincronização: {resultados['erro']}")
                    else:
                        st.success(f"""
                        ✅ Sincronização concluída!
                        - Total: {resultados['total']}
                        - Sincronizados: {resultados['sincronizados']}
                        - Não encontrados: {resultados['nao_encontrados']}
                        - Erros: {resultados['erros']}
                        """)
                        if resultados.get("detalhes"):
                            with st.expander("📋 Detalhes da Sincronização"):
                                for item in resultados["detalhes"]:
                                    if item["status"] == "sincronizado":
                                        st.success(f"✅ {item['nome']} - ID IXC: {item.get('id_ixc')}")
                                        if item.get("alteracoes"):
                                            for alt in item["alteracoes"]:
                                                st.write(f"   🔄 {alt}")
                                    elif item["status"] == "nao_encontrado":
                                        st.warning(f"⚠️ {item['nome']} - Não encontrado no IXC")
                                    else:
                                        st.error(f"❌ {item['nome']} - {item.get('erro', 'Erro desconhecido')}")

    with col2:
        st.subheader("🔍 Sincronizar Condomínio Específico")
        try:
            from .condominios import get_condominio_options
            cond_options = get_condominio_options()
            cond_nomes = list(cond_options.keys())
            if cond_nomes:
                cond_selecionado = st.selectbox("Selecione o condomínio:", cond_nomes)
                if cond_selecionado:
                    cond_id = cond_options[cond_selecionado]
                    if st.button("🔄 Sincronizar Este Condomínio"):
                        with st.spinner(f"Sincronizando '{cond_selecionado}'..."):
                            config = get_ixc_config()
                            if config:
                                resultado = sincronizar_condominio_crm_com_ixc(str(cond_id), config)
                                if resultado["sucesso"]:
                                    st.success(f"✅ Condomínio sincronizado com sucesso!")
                                    st.json({
                                        "id_ixc": resultado.get("id_ixc"),
                                        "alteracoes": resultado.get("alteracoes", []),
                                        "dados_ixc": resultado.get("dados_ixc")
                                    })
                                else:
                                    st.error(f"❌ {resultado.get('erro', 'Erro desconhecido')}")
            else:
                st.info("ℹ️ Nenhum condomínio cadastrado no CRM")
        except Exception as e:
            st.error(f"❌ Erro ao carregar condomínios: {e}")

    # Listar condomínios do IXC para mapeamento manual
    st.markdown("---")
    st.subheader("📋 Listar Condomínios do IXC (para mapeamento manual)")
    st.info("Use esta lista para encontrar o ID correto de um condomínio no IXC caso a busca automática falhe.")
    if st.button("🔍 Listar Condomínios do IXC", key="listar_cond_ixc"):
        with st.spinner("Buscando condomínios no IXC..."):
            config = get_ixc_config()
            if config:
                condominios_ixc = listar_condominios_ixc(config)
                if condominios_ixc:
                    st.success(f"✅ {len(condominios_ixc)} condomínio(s) encontrado(s) no IXC")
                    # Criar tabela
                    tabela = []
                    for c in condominios_ixc:
                        tabela.append({
                            "ID IXC": c.get("id"),
                            "Nome": c.get("nome"),
                            "Endereço": f"{c.get('endereco', '')} {c.get('numero', '')}".strip(),
                            "Bairro": c.get("bairro"),
                            "Cidade/UF": f"{c.get('cidade', '')}/{c.get('uf', '')}"
                        })
                    st.dataframe(tabela, use_container_width=True)

                    # Botão para copiar como CSV
                    csv_lines = ["ID, Nome, Endereço, Bairro, Cidade/UF"]
                    for c in condominios_ixc:
                        csv_lines.append(f"{c.get('id')}, {c.get('nome')}, {c.get('endereco', '')} {c.get('numero', '')}, {c.get('bairro')}, {c.get('cidade')}/{c.get('uf')}")
                    csv_text = "\n".join(csv_lines)
                    st.download_button(
                        "📥 Baixar lista como CSV",
                        data=csv_text,
                        file_name="condominios_ixc.csv",
                        mime="text/csv"
                    )
                else:
                    st.warning("⚠️ Nenhum condomínio encontrado no IXC")
            else:
                st.error("❌ Configuração do IXC não encontrada")
