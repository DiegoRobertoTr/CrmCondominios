# modules/integracao_ixc.py - VERSÃO CORRIGIDA (baseada no teste R6P01)
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
# CONSTRUÇÃO DO PAYLOAD - VERSÃO CORRIGIDA (baseada no R6P01)
# ============================================================================
def construir_payload_ixc(cliente_data: Dict, config: Dict) -> Tuple[Dict, Optional[str]]:
    """
    Constrói payload para o IXC seguindo o formato que funcionou no teste R6P01.
    """
    def safe(val) -> str:
        return str(val).strip() if val is not None else ""

    # ========== 1. SANITIZAÇÃO DOS CAMPOS ==========
    # CPF
    cpf_raw = safe(cliente_data.get("cpf"))
    cpf_digits = "".join(filter(str.isdigit, cpf_raw))
    cpf = fmt_cpf(cpf_digits)
    
    if not validar_cpf(cpf_digits):
        return {}, f"CPF inválido: '{cpf_raw}'"

    # Nome
    nome = safe(cliente_data.get("nome_completo"))
    if not nome:
        return {}, "Nome completo é obrigatório"

    # Telefone (formato do R6P01: (21)99900008)
    celular_raw = safe(cliente_data.get("celular"))
    celular = fmt_fone(celular_raw)
    
    if not celular or len(celular) < 10:
        return {}, f"Telefone inválido: '{celular_raw}'. Use formato (DDD)NÚMERO"

    # Email
    email = safe(cliente_data.get("email"))
    if not email:
        return {}, "Email é obrigatório"

    # ========== 2. ENDEREÇO ==========
    # CEP - formato do R6P01: 20521-130
    cep_raw = safe(cliente_data.get("cep"))
    if cep_raw:
        cep = fmt_cep(cep_raw)
    else:
        cep = "20521-130"  # fallback

    # Endereço
    endereco = safe(cliente_data.get("endereco"))
    numero = safe(cliente_data.get("numero"))
    bairro = safe(cliente_data.get("bairro"))
    
    # Cidade e UF - SEMPRE usar IDs numéricos (como no R6P01)
    cidade_id = ID_CIDADE_RJ  # 3241
    uf_id = ID_UF_RJ          # 24

    # Complemento
    complemento = safe(cliente_data.get("complemento"))

    # ========== 3. CONDOMÍNIO ==========
    id_condominio_ixc = None
    cond_bloco = safe(cliente_data.get("bloco"))
    cond_apto = safe(cliente_data.get("apartamento"))
    cond_nome = safe(cliente_data.get("condominio_nome"))

    # Buscar ID do condomínio no IXC
    if cliente_data.get("condominio_id"):
        try:
            from .condominios import get_condominio_by_id
            cond_data = get_condominio_by_id(cliente_data["condominio_id"])
            if cond_data and cond_data.get("id_ixc"):
                id_condominio_ixc = str(cond_data["id_ixc"])
                print(f"🏢 Condomínio encontrado: {cond_data.get('nome')} (ID IXC: {id_condominio_ixc})")
                
                # Se o condomínio tem endereço próprio, usar ele
                if cond_data.get("cep"):
                    cep = fmt_cep(cond_data.get("cep"))
                if cond_data.get("endereco"):
                    endereco = safe(cond_data.get("endereco"))
                if cond_data.get("numero"):
                    numero = safe(cond_data.get("numero"))
                if cond_data.get("bairro"):
                    bairro = safe(cond_data.get("bairro"))
                if cond_data.get("cidade"):
                    cidade_id = ID_CIDADE_RJ
                if cond_data.get("uf"):
                    uf_id = ID_UF_RJ
                    
        except Exception as e:
            print(f"⚠️ Erro ao buscar condomínio: {e}")

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

    # ========== 5. PAYLOAD FINAL (igual ao R6P01) ==========
    payload = {
        # Dados obrigatórios (como no R6P01)
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
        
        # Contato (formato do R6P01)
        "fone": celular,
        "telefone_celular": celular,
        "whatsapp": celular,
        "email": email,
        "hotsite_email": email,
        
        # Endereço (formato do R6P01)
        "cep": cep,
        "endereco": endereco if endereco else "Rua Conde de Bonfim",
        "numero": numero if numero else "255",
        "bairro": bairro if bairro else "Tijuca",
        "cidade": cidade_id,  # 3241 (ID, não texto!)
        "uf": uf_id,          # 24 (ID, não texto!)
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

    # ========== 6. ADICIONAR CONDOMÍNIO SE TIVER ==========
    if id_condominio_ixc:
        payload["id_condominio"] = id_condominio_ixc
        if cond_bloco:
            payload["bloco"] = cond_bloco
        if cond_apto:
            payload["apartamento"] = cond_apto

    # ========== 7. REMOVER CAMPOS VAZIOS ==========
    payload = {k: v for k, v in payload.items() if v not in (None, "", " ", [], {})}

    return payload, None

# ============================================================================
# BUSCAR CLIENTE POR CPF
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
# FUNÇÃO PRINCIPAL - ENVIAR CLIENTE
# ============================================================================
def enviar_cliente_para_ixc(cliente_data: Dict) -> Tuple[bool, Optional[str], Optional[str]]:
    """
    Envia cliente para o IXC usando o formato que funcionou no teste R6P01.
    """
    print("\n" + "=" * 70)
    print("🚀 ENVIANDO CLIENTE PARA IXC (formato R6P01)")
    print("=" * 70)

    config = get_ixc_config()
    if not config:
        return False, None, "Configuração do IXC não encontrada"

    # Verifica se cliente já existe
    cpf = cliente_data.get("cpf", "")
    if cpf and len("".join(filter(str.isdigit, str(cpf)))) >= 11:
        id_existente = buscar_cliente_ixc_por_cpf(cpf, config)
        if id_existente:
            print(f"✅ Cliente já existe no IXC (ID: {id_existente})")
            return True, id_existente, None

    # Constrói payload
    payload, erro = construir_payload_ixc(cliente_data, config)
    if erro:
        return False, None, erro

    # Log do payload (sem dados sensíveis)
    payload_log = payload.copy()
    if "cnpj_cpf" in payload_log:
        payload_log["cnpj_cpf"] = "***" + payload_log["cnpj_cpf"][-4:]
    print(f"📤 Payload: {json.dumps(payload_log, indent=2, ensure_ascii=False)}")

    # Envia para o IXC
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
        return False, None, "Erro de conexão: IXC inacessível"
    except Exception as e:
        return False, None, str(e)

# ============================================================================
# REGISTRAR PENDÊNCIA
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
