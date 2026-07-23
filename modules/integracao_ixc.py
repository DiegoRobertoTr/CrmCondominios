# modules/integracao_ixc.py - CORREÇÃO PARA BUSCA DE DADOS COM SINCRONIZAÇÃO DE CONDOMÍNIOS
# ALTERAÇÃO 1: Quando tem condomínio, NÃO envia endereço
# ALTERAÇÃO 4: Endereço só é enviado se NÃO tiver condomínio
# CORREÇÃO: Sempre enviar bairro e tipo_localidade (obrigatórios no IXC)

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
# CONSTRUÇÃO DO PAYLOAD - VERSÃO CORRIGIDA (COM BAIRRO E TIPO_LOCALIDADE)
# ============================================================================
def construir_payload_ixc(cliente_data: Dict, config: Dict) -> Tuple[Dict, Optional[str]]:
    """
    Constrói payload para o IXC seguindo o formato que funcionou no teste R6P01.
    
    🔑 ALTERAÇÃO 1: Quando tem condomínio, NÃO envia campos de endereço
    🔑 ALTERAÇÃO 4: Endereço só é enviado se NÃO tiver condomínio
    🔑 CORREÇÃO: Sempre enviar bairro e tipo_localidade (obrigatórios no IXC)
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

    # ========== 2. HOST E AUTH ==========
    host_limpo = _sanitizar_host(config["host"])
    auth_string = base64.b64encode(config["token"].encode('utf-8')).decode('utf-8')

    # ========== 3. DADOS DO CONDOMÍNIO ==========
    cond_bloco = safe(cliente_data.get("bloco"))
    cond_apto = safe(cliente_data.get("apartamento"))
    cond_nome = safe(cliente_data.get("condominio_nome"))
    cond_id_crm = cliente_data.get("condominio_id")
    cond_id_ixc = cliente_data.get("condominio_id_ixc")
    
    # Flag para saber se adicionamos condomínio
    condominio_adicionado = False
    id_condominio_para_enviar = None
    
    print(f"\n🔍 PROCESSANDO CONDOMÍNIO:")
    print(f"   cond_id_ixc: {cond_id_ixc} (tipo: {type(cond_id_ixc).__name__})")
    print(f"   cond_id_crm: {cond_id_crm} (tipo: {type(cond_id_crm).__name__})")
    print(f"   cond_nome: '{cond_nome}'")
    print(f"   cond_bloco: '{cond_bloco}'")
    print(f"   cond_apto: '{cond_apto}'")
    
    # PRIORIDADE 1: Usar ID do IXC se disponível (já sincronizado)
    if cond_id_ixc and str(cond_id_ixc).strip() and str(cond_id_ixc) != "None":
        id_condominio_para_enviar = str(cond_id_ixc)
        condominio_adicionado = True
        print(f"✅ Usando ID IXC do condomínio: {cond_id_ixc}")
    
    # PRIORIDADE 2: Se tem ID do CRM, buscar/sincronizar
    elif cond_id_crm and str(cond_id_crm).strip() and str(cond_id_crm) != "None":
        print(f"🔄 Tentando sincronizar condomínio pelo ID CRM: {cond_id_crm}")
        try:
            resultado_sinc = sincronizar_condominio_crm_com_ixc(str(cond_id_crm), config)
            
            if resultado_sinc["sucesso"] and resultado_sinc.get("id_ixc"):
                id_condominio_para_enviar = str(resultado_sinc["id_ixc"])
                condominio_adicionado = True
                print(f"✅ Condomínio sincronizado: ID IXC = {resultado_sinc['id_ixc']}")
            else:
                print(f"⚠️ Condomínio não encontrado no IXC (ID CRM: {cond_id_crm})")
                print(f"   Erro: {resultado_sinc.get('erro', 'Erro desconhecido')}")
        except Exception as e:
            print(f"⚠️ Erro ao sincronizar condomínio: {e}")
    
    # PRIORIDADE 3: Se tem nome, buscar pelo nome
    elif cond_nome and cond_nome != "None" and cond_nome.strip():
        print(f"🔍 Tentando buscar condomínio pelo nome: '{cond_nome}'")
        try:
            dados_ixc = buscar_condominio_completo_ixc(host_limpo, auth_string, cond_nome)
            
            if dados_ixc and dados_ixc.get("id_ixc"):
                id_condominio_para_enviar = str(dados_ixc["id_ixc"])
                condominio_adicionado = True
                print(f"✅ Condomínio encontrado pelo nome: '{cond_nome}' -> ID IXC: {dados_ixc['id_ixc']}")
                
                # Salvar ID no CRM para futuras referências
                if cond_id_crm:
                    try:
                        from .condominios import update_condominio
                        update_condominio(cond_id_crm, {"id_ixc": dados_ixc["id_ixc"]})
                        print(f"💾 ID IXC salvo no CRM para o condomínio {cond_id_crm}")
                    except Exception as e:
                        print(f"⚠️ Não foi possível salvar ID IXC no CRM: {e}")
            else:
                print(f"⚠️ Condomínio não encontrado pelo nome: '{cond_nome}'")
        except Exception as e:
            print(f"⚠️ Erro ao buscar condomínio pelo nome: {e}")
    else:
        print(f"⚠️ Nenhuma informação de condomínio disponível para busca")

    # ========== 4. ENDEREÇO - SÓ ENVIA SE NÃO TIVER CONDOMÍNIO ==========
    cep = None
    endereco = None
    numero = None
    bairro = None
    complemento = None
    cidade_id = ID_CIDADE_RJ
    uf_id = ID_UF_RJ

    if condominio_adicionado and id_condominio_para_enviar:
        # 🔴 TEM CONDOMÍNIO - NÃO ENVIA ENDEREÇO (ALTERAÇÃO 1)
        print(f"\n🏢 USANDO CONDOMÍNIO - Endereço NÃO será enviado")
        print(f"   ID Condomínio: {id_condominio_para_enviar}")
        print(f"   Bloco: {cond_bloco if cond_bloco else '(vazio)'}")
        print(f"   Apartamento: {cond_apto if cond_apto else '(vazio)'}")
        
        # Buscar bairro do cliente (se disponível)
        bairro = safe(cliente_data.get("bairro"))
        
        # Se não tiver bairro, tentar buscar do condomínio
        if not bairro and cond_id_ixc:
            try:
                dados_cond = buscar_condominio_por_id_ixc(host_limpo, auth_string, cond_id_ixc)
                if dados_cond and dados_cond.get("bairro"):
                    bairro = dados_cond["bairro"]
                    print(f"📍 Bairro obtido do condomínio: {bairro}")
            except Exception as e:
                print(f"⚠️ Erro ao buscar bairro do condomínio: {e}")
        
    else:
        # ❌ NÃO TEM CONDOMÍNIO - ENVIA ENDEREÇO COMPLETO
        print(f"\n📍 SEM CONDOMÍNIO - Endereço completo será enviado")
        
        # Buscar CEP
        cep_raw = safe(cliente_data.get("cep"))
        if cep_raw:
            cep = fmt_cep(cep_raw)
        else:
            cep = "20521-130"

        endereco = safe(cliente_data.get("endereco"))
        numero = safe(cliente_data.get("numero"))
        bairro = safe(cliente_data.get("bairro"))
        complemento = safe(cliente_data.get("complemento"))
        
        # Cidade e UF - buscar IDs no IXC
        cidade_nome = safe(cliente_data.get("cidade", "Rio de Janeiro"))
        uf_sigla = safe(cliente_data.get("uf", "RJ")).upper()
        cidade_id, uf_id = _buscar_id_cidade(host_limpo, auth_string, cidade_nome, uf_sigla)
        
        print(f"   Endereço: {endereco}, {numero}")
        print(f"   Cidade: {cidade_nome} (ID: {cidade_id})")
        print(f"   CEP: {cep}")

    # ========== 5. DATA DE NASCIMENTO ==========
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

    # ========== 6. PAYLOAD FINAL ==========
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

    # ========== 7. ADICIONAR CONDOMÍNIO (se encontrado) ==========
    if condominio_adicionado and id_condominio_para_enviar:
        payload["id_condominio"] = id_condominio_para_enviar
        
        # Adicionar bloco e apartamento
        if cond_bloco:
            payload["bloco"] = str(cond_bloco)
            print(f"🏢 Adicionando bloco: {cond_bloco}")
        if cond_apto:
            payload["apartamento"] = str(cond_apto)
            print(f"🏢 Adicionando apartamento: {cond_apto}")
        
        # 🔴 NÃO ADICIONAR CAMPOS DE ENDEREÇO (ALTERAÇÃO 1)
        print(f"✅ Payload com CONDOMÍNIO - Endereço NÃO enviado")
        
        # ⚠️ MAS PRECISA ENVIAR BAIRRO E TIPO_LOCALIDADE (obrigatórios no IXC)
        if bairro:
            payload["bairro"] = bairro
            print(f"📍 Adicionando bairro: {bairro}")
        else:
            # Fallback: usar um bairro padrão
            payload["bairro"] = "Centro"
            print(f"⚠️ Bairro não encontrado, usando padrão: Centro")
        
        # Sempre adicionar tipo_localidade
        payload["tipo_localidade"] = "U"
        print(f"📍 Adicionando tipo_localidade: U (Urbano)")
        
        # ⚠️ GARANTIR QUE ENDEREÇO NÃO ESTEJA NO PAYLOAD
        campos_endereco = ['endereco', 'numero', 'cidade', 'cep', 'uf', 'complemento']
        for campo in campos_endereco:
            if campo in payload:
                del payload[campo]
                print(f"   🗑️ Removendo campo '{campo}' do payload (tem condomínio)")
        
    else:
        # ❌ SEM CONDOMÍNIO - Adicionar endereço completo
        if endereco:
            payload["endereco"] = endereco
        if numero:
            payload["numero"] = numero
        if bairro:
            payload["bairro"] = bairro
        else:
            payload["bairro"] = "Centro"
        if complemento:
            payload["complemento"] = complemento
        if cep:
            payload["cep"] = cep
        if cidade_id:
            payload["cidade"] = cidade_id
        if uf_id:
            payload["uf"] = uf_id
        
        # Sempre adicionar tipo_localidade
        payload["tipo_localidade"] = "U"
        print(f"📍 Adicionando tipo_localidade: U (Urbano)")
        
        print(f"✅ Payload com ENDEREÇO - Endereço enviado")
        
        # ⚠️ GARANTIR QUE CONDOMÍNIO NÃO ESTEJA NO PAYLOAD
        if 'id_condominio' in payload:
            del payload['id_condominio']
            print(f"   🗑️ Removendo 'id_condominio' do payload (sem condomínio)")

    # ========== 8. REMOVER CAMPOS VAZIOS ==========
    payload = {k: v for k, v in payload.items() if v not in (None, "", " ", [], {})}
    
    # ========== 9. LOG FINAL ==========
    print(f"\n📤 PAYLOAD FINAL:")
    print(f"   id_condominio: {payload.get('id_condominio', '❌ NÃO ENVIADO')}")
    print(f"   bloco: {payload.get('bloco', '❌ NÃO ENVIADO')}")
    print(f"   apartamento: {payload.get('apartamento', '❌ NÃO ENVIADO')}")
    print(f"   endereco: {payload.get('endereco', '❌ NÃO ENVIADO')}")
    print(f"   numero: {payload.get('numero', '❌ NÃO ENVIADO')}")
    print(f"   bairro: {payload.get('bairro', '❌ NÃO ENVIADO')}")
    print(f"   cidade: {payload.get('cidade', '❌ NÃO ENVIADO')}")
    print(f"   cep: {payload.get('cep', '❌ NÃO ENVIADO')}")
    print(f"   tipo_localidade: {payload.get('tipo_localidade', '❌ NÃO ENVIADO')}")
    print("=" * 70)

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
            return True, id_existente, None

    # ========== CONSTRUIR PAYLOAD ==========
    payload, erro = construir_payload_ixc(cliente_data, config)
    if erro:
        return False, None, erro

    # Log do payload (sem dados sensíveis)
    payload_log = payload.copy()
    if "cnpj_cpf" in payload_log:
        payload_log["cnpj_cpf"] = "***" + payload_log["cnpj_cpf"][-4:]
    print(f"\n📤 Payload enviado: {json.dumps(payload_log, indent=2, ensure_ascii=False)}")

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
        
        print(f"\n📥 Status: {response.status_code}")
        print(f"📥 Resposta: {response.text[:500]}")

        if response.status_code in [200, 201]:
            try:
                resposta = response.json()
                
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
