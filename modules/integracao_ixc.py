# modules/integracao_ixc.py - CORREÇÃO PARA BUSCA DE DADOS COM SINCRONIZAÇÃO DE CONDOMÍNIOS
import requests
import re
import base64
import json
import streamlit as st
from datetime import datetime
from typing import Dict, Optional, Tuple
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
# BUSCAR CONDOMÍNIO NO IXC (APENAS LEITURA)
# ============================================================================
def buscar_condominio_completo_ixc(host_limpo: str, auth_string: str, nome_condominio: str) -> Optional[Dict]:
    """
    Busca dados completos de um condomínio no IXC pelo nome.
    Retorna todos os dados disponíveis do condomínio no IXC.
    """
    if not nome_condominio:
        return None
    
    try:
        headers = {
            "Authorization": f"Basic {auth_string}",
            "ixcsoft": "listar",
            "Content-Type": "application/json"
        }
        
        # Buscar condomínio pelo nome
        payload = {
            "qtype": "condominio.nome",
            "query": nome_condominio,
            "oper": "=",
            "page": "1",
            "rp": "5"
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
            
            # Procurar correspondência exata (case insensitive)
            nome_busca = nome_condominio.lower().strip()
            for reg in registros:
                nome_reg = str(reg.get("nome", "")).lower().strip()
                if nome_reg == nome_busca:
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
            
            # Se não encontrar exato, tenta contém (como fallback)
            for reg in registros:
                nome_reg = str(reg.get("nome", "")).lower().strip()
                if nome_busca in nome_reg or nome_reg in nome_busca:
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
        
        return None
    except Exception as e:
        print(f"⚠️ Erro ao buscar condomínio completo '{nome_condominio}': {e}")
        return None


def buscar_condominio_por_id_ixc(host_limpo: str, auth_string: str, id_ixc: str) -> Optional[Dict]:
    """
    Busca dados completos de um condomínio no IXC pelo ID.
    """
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
        
        return None
    except Exception as e:
        print(f"⚠️ Erro ao buscar condomínio por ID IXC '{id_ixc}': {e}")
        return None


def _buscar_condominio_por_endereco(host_limpo: str, auth_string: str, endereco: str, numero: str, bairro: str) -> Optional[str]:
    """
    Busca um condomínio no IXC pelo endereço.
    APENAS LEITURA - Não altera nada no CRM.
    Útil para casos onde o nome pode ser diferente.
    """
    if not endereco:
        return None
    
    try:
        headers = {
            "Authorization": f"Basic {auth_string}",
            "ixcsoft": "listar",
            "Content-Type": "application/json"
        }
        
        # Buscar condomínios pelo endereço (se disponível)
        payload = {
            "qtype": "condominio.endereco",
            "query": endereco,
            "oper": "=",
            "page": "1",
            "rp": "5"
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
            
            # Tentar encontrar pelo número e bairro também
            for reg in registros:
                num_reg = str(reg.get("numero", "")).strip()
                bairro_reg = str(reg.get("bairro", "")).lower().strip()
                
                # Verifica se o número e bairro correspondem (se disponíveis)
                if numero and num_reg == numero.strip():
                    if bairro and bairro_reg == bairro.lower().strip():
                        return str(reg.get("id"))
                    # Se não tem bairro, considera encontrado pelo número
                    return str(reg.get("id"))
            
            # Se não encontrar pelo número, retorna o primeiro
            if registros:
                return str(registros[0].get("id"))
        
        return None
    except Exception as e:
        print(f"⚠️ Erro ao buscar condomínio por endereço: {e}")
        return None


# ============================================================================
# SINCRONIZAR CONDOMÍNIO DO CRM COM IXC
# ============================================================================
def sincronizar_condominio_crm_com_ixc(condominio_id: str, config: Dict) -> Dict:
    """
    Sincroniza um condomínio específico do CRM com o IXC.
    ATUALIZA o CRM com dados do IXC se encontrado.
    """
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
        
        # Buscar condomínio no CRM
        cond_crm = get_condominio_by_id(condominio_id)
        if not cond_crm:
            resultado["erro"] = "Condomínio não encontrado no CRM"
            return resultado
        
        host_limpo = _sanitizar_host(config["host"])
        auth_string = base64.b64encode(config["token"].encode('utf-8')).decode('utf-8')
        
        # Tentar encontrar no IXC
        dados_ixc = None
        
        # 1. Se já tem id_ixc, buscar por ele
        if cond_crm.get("id_ixc"):
            dados_ixc = buscar_condominio_por_id_ixc(host_limpo, auth_string, cond_crm["id_ixc"])
            if dados_ixc:
                resultado["id_ixc"] = dados_ixc["id_ixc"]
                print(f"✅ Condomínio encontrado pelo ID IXC: {dados_ixc['id_ixc']}")
        
        # 2. Se não encontrou ou não tem id_ixc, buscar pelo nome
        if not dados_ixc and cond_crm.get("nome"):
            dados_ixc = buscar_condominio_completo_ixc(host_limpo, auth_string, cond_crm["nome"])
            if dados_ixc:
                resultado["id_ixc"] = dados_ixc["id_ixc"]
                print(f"✅ Condomínio encontrado pelo nome: '{cond_crm['nome']}' -> ID IXC: {dados_ixc['id_ixc']}")
        
        # 3. Se encontrou, atualizar o CRM
        if dados_ixc:
            resultado["dados_ixc"] = dados_ixc
            resultado["sucesso"] = True
            
            # Preparar atualizações
            updates = {
                "id_ixc": dados_ixc["id_ixc"],
                "ultima_sincronizacao_ixc": datetime.now()
            }
            
            # Atualizar dados do IXC no CRM (se diferentes)
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
            
            # Bloco e apartamento padrão
            if dados_ixc.get("bloco_padrao") and dados_ixc["bloco_padrao"] != cond_crm.get("bloco_padrao"):
                updates["bloco_padrao"] = dados_ixc["bloco_padrao"]
                resultado["alteracoes"].append(f"bloco_padrao: '{cond_crm.get('bloco_padrao')}' -> '{dados_ixc['bloco_padrao']}'")
            
            if dados_ixc.get("apartamento_padrao") and dados_ixc["apartamento_padrao"] != cond_crm.get("apartamento_padrao"):
                updates["apartamento_padrao"] = dados_ixc["apartamento_padrao"]
                resultado["alteracoes"].append(f"apartamento_padrao: '{cond_crm.get('apartamento_padrao')}' -> '{dados_ixc['apartamento_padrao']}'")
            
            # Atualizar no MongoDB
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


# ============================================================================
# SINCRONIZAR TODOS OS CONDOMÍNIOS COM IXC
# ============================================================================
def sincronizar_todos_condominios_com_ixc(config: Dict) -> Dict:
    """
    Sincroniza todos os condomínios do CRM com o IXC.
    ATUALIZA o CRM com dados do IXC para cada condomínio encontrado.
    """
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
            
            # Sincronizar este condomínio
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

# ============================================================================
# BUSCAR DADOS DO CLIENTE NO IXC
# ============================================================================
def buscar_dados_cliente_ixc(id_ixc: str, config: Dict) -> Optional[Dict]:
    """
    Busca os dados atuais de um cliente no IXC.
    """
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
    
    # Usa POST com filtro pelo ID
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

# ============================================================================
# VERIFICAR SE CLIENTE EXISTE NO IXC
# ============================================================================
def verificar_cliente_existente_ixc(cpf: str, config: Dict) -> Dict:
    """
    Verifica se um cliente com este CPF já existe no IXC.
    Retorna apenas ID e dados básicos (rápido).
    """
    resultado = {
        "existe": False,
        "id_ixc": None,
        "dados": None,
        "erro": None
    }
    
    if not cpf or not config:
        return resultado
    
    try:
        # Buscar ID no IXC
        id_ixc = buscar_cliente_ixc_por_cpf(cpf, config)
        if id_ixc:
            resultado["existe"] = True
            resultado["id_ixc"] = id_ixc
            
            # Buscar dados básicos
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
# CONSTRUÇÃO DO PAYLOAD - COM SINCRONIZAÇÃO DE CONDOMÍNIO
# ============================================================================
def construir_payload_ixc(cliente_data: Dict, config: Dict) -> Tuple[Dict, Optional[str]]:
    """
    Constrói payload para o IXC seguindo o formato que funcionou no teste R6P01.
    Com sincronização de condomínios.
    """
    def safe(val) -> str:
        return str(val).strip() if val is not None else ""

    # ========== 1. SANITIZAÇÃO DOS CAMPOS ==========
    # CPF
    cpf_raw = safe(cliente_data.get("cpf"))
    cpf_digits = "".join(filter(str.isdigit, cpf_raw))
    cpf = fmt_cpf(cpf_digits)
    
    if not validar_cpf(cpf_digits):
        return {}, f"CPF inválido: '{cpf_raw}'. Verifique os dígitos."

    # Nome
    nome = safe(cliente_data.get("nome_completo"))
    if not nome:
        return {}, "Nome completo é obrigatório"

    # Telefone
    celular_raw = safe(cliente_data.get("celular"))
    celular = fmt_fone(celular_raw)
    
    if not celular or len(celular) < 10:
        return {}, f"Telefone inválido: '{celular_raw}'. Use formato (DDD)NÚMERO"

    # Email
    email = safe(cliente_data.get("email"))
    if not email:
        return {}, "Email é obrigatório"

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
    
    # Cidade e UF - sempre usar IDs numéricos
    cidade_nome = safe(cliente_data.get("cidade", "Rio de Janeiro"))
    uf_sigla = safe(cliente_data.get("uf", "RJ")).upper()
    
    host_limpo = _sanitizar_host(config["host"])
    auth_string = base64.b64encode(config["token"].encode('utf-8')).decode('utf-8')
    cidade_id, uf_id = _buscar_id_cidade(host_limpo, auth_string, cidade_nome, uf_sigla)

    # ========== 3. CONDOMÍNIO - COM SINCRONIZAÇÃO ==========
    id_condominio_ixc = None
    cond_bloco = safe(cliente_data.get("bloco"))
    cond_apto = safe(cliente_data.get("apartamento"))
    cond_nome = safe(cliente_data.get("condominio_nome"))
    cond_id_crm = cliente_data.get("condominio_id")
    
    # Flag para saber se o condomínio foi encontrado
    condominio_encontrado = False
    
    # 3a. Se tem ID do CRM, tentar sincronizar
    if cond_id_crm:
        # Tenta sincronizar o condomínio com o IXC
        resultado_sinc = sincronizar_condominio_crm_com_ixc(cond_id_crm, config)
        
        if resultado_sinc["sucesso"]:
            id_condominio_ixc = resultado_sinc.get("id_ixc")
            condominio_encontrado = True
            
            # Se houve alterações, mostrar no log
            if resultado_sinc.get("alteracoes"):
                print(f"🔄 Condomínio sincronizado com IXC. Alterações: {resultado_sinc['alteracoes']}")
            
            # Atualizar os dados do condomínio no cliente_data com os dados do IXC
            if resultado_sinc.get("dados_ixc"):
                dados_ixc = resultado_sinc["dados_ixc"]
                # Atualizar endereço se veio do IXC
                if dados_ixc.get("endereco"):
                    cliente_data["endereco"] = dados_ixc["endereco"]
                if dados_ixc.get("numero"):
                    cliente_data["numero"] = dados_ixc["numero"]
                if dados_ixc.get("bairro"):
                    cliente_data["bairro"] = dados_ixc["bairro"]
                if dados_ixc.get("cidade"):
                    cliente_data["cidade"] = dados_ixc["cidade"]
                if dados_ixc.get("uf"):
                    cliente_data["uf"] = dados_ixc["uf"]
                if dados_ixc.get("cep"):
                    cliente_data["cep"] = dados_ixc["cep"]
                
                print(f"🏢 Dados do condomínio atualizados a partir do IXC")
    
    # 3b. Se não tem ID CRM mas tem nome, tentar buscar
    if not id_condominio_ixc and cond_nome:
        dados_ixc = buscar_condominio_completo_ixc(host_limpo, auth_string, cond_nome)
        if dados_ixc:
            id_condominio_ixc = dados_ixc["id_ixc"]
            condominio_encontrado = True
            print(f"🏢 Condomínio encontrado pelo nome: '{cond_nome}' -> IXC ID: {id_condominio_ixc}")
            
            # Atualizar dados do cliente com dados do IXC
            if dados_ixc.get("endereco"):
                cliente_data["endereco"] = dados_ixc["endereco"]
            if dados_ixc.get("numero"):
                cliente_data["numero"] = dados_ixc["numero"]
            if dados_ixc.get("bairro"):
                cliente_data["bairro"] = dados_ixc["bairro"]
            if dados_ixc.get("cidade"):
                cliente_data["cidade"] = dados_ixc["cidade"]
            if dados_ixc.get("uf"):
                cliente_data["uf"] = dados_ixc["uf"]
            if dados_ixc.get("cep"):
                cliente_data["cep"] = dados_ixc["cep"]

    # ========== 4. DATA DE NASCIMENTO ==========
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

    # ========== 5. PAYLOAD FINAL ==========
    payload = {
        # Dados obrigatórios
        "ativo": "S",
        "tipo_pessoa": "F",
        "tipo_cliente_scm": "01",
        "filial_id": config.get("filial_id", "1"),
        "filtra_filial": "S",
        
        # Dados pessoais
        "razao": nome,
        "nome_social": nome,
        "fantasia": nome,
        "cnpj_cpf": cpf,
        "ie_identidade": safe(cliente_data.get("rg", "1234567")),
        "data_nascimento": data_nasc if data_nasc else "1990-06-01",
        "nacionalidade": "Brasileiro",
        "contribuinte_icms": "N",
        
        # Contato
        "fone": celular,
        "telefone_celular": celular,
        "whatsapp": celular,
        "email": email,
        "hotsite_email": email,
        
        # Endereço
        "cep": cep,
        "endereco": endereco if endereco else "Rua Conde de Bonfim",
        "numero": numero if numero else "255",
        "bairro": bairro if bairro else "Tijuca",
        "cidade": cidade_id,
        "uf": uf_id,
        "tipo_localidade": "U",
        
        # Acesso
        "senha": "123456",
        "acesso_automatico_central": "S",
        "alterar_senha_primeiro_acesso": "P",
        "senha_hotsite_md5": "N",
        "hotsite_acesso": "2",
        
        # Cobrança
        "tipo_assinante": "3",
        "participa_cobranca": "S",
        "participa_pre_cobranca": "S",
        "cob_envia_email": "S",
        "cob_envia_sms": "S",
        "status_prospeccao": "C",
        
        # Fiscal
        "iss_classificacao_padrao": "99",
        
        # Observação
        "obs": safe(cliente_data.get("observacoes", f"Cadastro CRM - {datetime.now().strftime('%d/%m/%Y')}"))
    }

    # Adicionar complemento se existir
    if complemento:
        payload["complemento"] = complemento

    # ========== 6. ADICIONAR CONDOMÍNIO SE ENCONTRADO ==========
    if id_condominio_ixc and condominio_encontrado:
        payload["id_condominio"] = id_condominio_ixc
        if cond_bloco:
            payload["bloco"] = cond_bloco
        if cond_apto:
            payload["apartamento"] = cond_apto
        
        # Usar dados atualizados do IXC no payload
        if cliente_data.get("endereco"):
            payload["endereco"] = cliente_data["endereco"]
        if cliente_data.get("numero"):
            payload["numero"] = cliente_data["numero"]
        if cliente_data.get("bairro"):
            payload["bairro"] = cliente_data["bairro"]
        if cliente_data.get("cidade"):
            # Buscar ID da cidade atualizada
            cidade_id_atualizada, uf_id_atualizada = _buscar_id_cidade(
                host_limpo, auth_string, cliente_data["cidade"], cliente_data.get("uf", "RJ")
            )
            payload["cidade"] = cidade_id_atualizada
            payload["uf"] = uf_id_atualizada
        if cliente_data.get("cep"):
            payload["cep"] = fmt_cep(cliente_data["cep"])
        
        print(f"🏢 Adicionando ao payload: id_condominio={id_condominio_ixc}, bloco='{cond_bloco}', apto='{cond_apto}'")
    else:
        # Log informativo sem ser erro
        if cond_nome or cond_id_crm:
            print(f"ℹ️ Condomínio não encontrado no IXC: '{cond_nome or cond_id_crm}'. Dados de bloco/apto não serão enviados.")
        elif cond_bloco or cond_apto:
            print(f"ℹ️ Bloco/Apto informados sem condomínio. Não serão enviados para o IXC.")

    # ========== 7. REMOVER CAMPOS VAZIOS ==========
    payload = {k: v for k, v in payload.items() if v not in (None, "", " ", [], {})}

    return payload, None

# ============================================================================
# FUNÇÃO PRINCIPAL - ENVIAR CLIENTE PARA IXC
# ============================================================================
def enviar_cliente_para_ixc(cliente_data: Dict) -> Tuple[bool, Optional[str], Optional[str]]:
    """
    Envia cliente para o IXC usando o formato que funcionou no teste R6P01.
    
    Retorna: (sucesso, id_ixc, mensagem_erro)
    """
    print("\n" + "=" * 70)
    print("🚀 ENVIANDO CLIENTE PARA IXC (formato R6P01)")
    print("=" * 70)

    config = get_ixc_config()
    if not config:
        return False, None, "Configuração do IXC não encontrada"

    # ========== VERIFICAR SE CLIENTE JÁ EXISTE ==========
    cpf = cliente_data.get("cpf", "")
    if cpf and len("".join(filter(str.isdigit, str(cpf)))) >= 11:
        print(f"🔍 Verificando se CPF {cpf} já existe no IXC...")
        id_existente = buscar_cliente_ixc_por_cpf(cpf, config)
        if id_existente:
            print(f"✅ Cliente já existe no IXC com ID: {id_existente}")
            # Retorna sucesso com o ID existente, NÃO atualiza o IXC
            return True, id_existente, None

    # ========== CONSTRUIR PAYLOAD ==========
    payload, erro = construir_payload_ixc(cliente_data, config)
    if erro:
        return False, None, erro

    # Log do payload (sem dados sensíveis)
    payload_log = payload.copy()
    if "cnpj_cpf" in payload_log:
        payload_log["cnpj_cpf"] = "***" + payload_log["cnpj_cpf"][-4:]
    print(f"📤 Payload: {json.dumps(payload_log, indent=2, ensure_ascii=False)}")

    # ========== ENVIAR PARA O IXC ==========
    host_limpo = _sanitizar_host(config["host"])
    url = f"https://{host_limpo}/webservice/v1/cliente"
    auth_string = base64.b64encode(config["token"].encode('utf-8')).decode('utf-8')

    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Basic {auth_string}",
        "ixcsoft": "inserir"
    }

    try:
        response = requests.post(url, json=payload, headers=headers, timeout=30, verify=False)
        
        print(f"📥 Status: {response.status_code}")
        print(f"📥 Resposta: {response.text[:300]}")

        if response.status_code in [200, 201]:
            try:
                resposta = response.json()
                
                # Verifica se a API retornou erro (mesmo com HTTP 200)
                if resposta.get("type") == "error" or resposta.get("success") is False:
                    erro_msg = resposta.get("message") or resposta.get("error") or "Erro desconhecido"
                    return False, None, f"Erro na API: {erro_msg}"
                
                id_ixc = resposta.get("id") or resposta.get("cliente_id")
                if id_ixc:
                    print(f"✅ Cliente criado com sucesso! ID: {id_ixc}")
                    return True, str(id_ixc), None
                else:
                    return True, "ok", None
                    
            except ValueError:
                if "sucesso" in response.text.lower() or "created" in response.text.lower():
                    return True, "ok", None
                return False, None, f"Resposta inválida: {response.text[:200]}"
        else:
            return False, None, f"HTTP {response.status_code}: {response.text[:250]}"

    except requests.exceptions.Timeout:
        return False, None, "Timeout na conexão com o IXC"
    except requests.exceptions.ConnectionError:
        return False, None, "Erro de conexão: IXC inacessível. Verifique IP liberado e Webservice ativo."
    except Exception as e:
        return False, None, str(e)

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

# ============================================================================
# PAINEL DE ADMIN - TESTE DE CONEXÃO
# ============================================================================
def render_teste_conexao():
    """Renderiza um painel de teste de conexão com o IXC (para usar no admin)."""
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
# PAINEL DE SINCRONIZAÇÃO DE CONDOMÍNIOS
# ============================================================================
def render_painel_sincronizacao_condominios():
    """
    Renderiza um painel para sincronizar condomínios com o IXC.
    """
    st.subheader("🏢 Sincronização de Condomínios com IXC")
    
    st.info("""
    **Como funciona:**
    1. O sistema verifica cada condomínio no IXC pelo nome
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
                        
                        # Mostrar detalhes
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
        # Sincronizar um condomínio específico
        st.subheader("🔍 Sincronizar Condomínio Específico")
        
        try:
            from .condominios import get_condominio_options
            cond_options = get_condominio_options()
            cond_nomes = list(cond_options.keys())
            
            if cond_nomes:
                cond_selecionado = st.selectbox(
                    "Selecione o condomínio:",
                    cond_nomes
                )
                
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
