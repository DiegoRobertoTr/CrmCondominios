# modules/integracao_ixc.py
import requests
import base64
import json
import streamlit as st
from datetime import datetime
from typing import Dict, Optional, Tuple

# ============================================================================
# CONFIGURAÇÕES (ler dos segredos do Streamlit)
# ============================================================================
def get_ixc_config():
    """Retorna configuração da API IXC a partir de st.secrets"""
    try:
        return {
            "host": st.secrets["ixc"]["host"],
            "token": st.secrets["ixc"]["token"],
            "filial_id": st.secrets["ixc"].get("filial_id", "1"),
            "id_tipo_cliente": st.secrets["ixc"].get("id_tipo_cliente", "03"),
            "tipo_cliente_scm": st.secrets["ixc"].get("tipo_cliente_scm", "01"),
        }
    except Exception as e:
        st.error(f"❌ Erro ao carregar configuração do IXC: {e}")
        return None

# ============================================================================
# CONSTRUÇÃO DO PAYLOAD PARA IXC
# ============================================================================
def construir_payload_ixc(cliente_data: Dict, config: Dict) -> Dict:
    """
    Converte os dados do cliente (MongoDB) para o formato esperado pela API do IXC.
    """
    # Dados básicos
    nome_completo = cliente_data.get("nome_completo", "")
    cpf = cliente_data.get("cpf", "")
    rg = cliente_data.get("rg", "")
    data_nascimento = cliente_data.get("data_nascimento", "")
    email = cliente_data.get("email", "")
    celular = cliente_data.get("celular", "")
    
    # Limpa o celular (remove formatação)
    celular_limpo = celular.replace(" ", "").replace("-", "").replace("(", "").replace(")", "") if celular else ""
    
    # Endereço
    endereco = cliente_data.get("endereco", "")
    numero = cliente_data.get("numero", "")
    complemento = cliente_data.get("complemento", "")
    bairro = cliente_data.get("bairro", "")
    cidade = cliente_data.get("cidade", "Rio de Janeiro")
    uf = cliente_data.get("uf", "RJ")  # Padrão RJ
    cep = cliente_data.get("cep", "")
    
    # Bloco e Apartamento
    bloco = cliente_data.get("bloco", "")
    apartamento = cliente_data.get("apartamento", "")
    
    # Data no formato DD-MM-AAAA -> converte para YYYY-MM-DD
    data_nasc_formatada = ""
    if data_nascimento:
        try:
            if isinstance(data_nascimento, str):
                # Tenta diferentes formatos
                for fmt in ["%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y"]:
                    try:
                        dt = datetime.strptime(data_nascimento, fmt)
                        break
                    except:
                        continue
                else:
                    dt = None
            else:
                dt = data_nascimento
                
            if dt:
                data_nasc_formatada = dt.strftime("%Y-%m-%d")
        except:
            data_nasc_formatada = ""
    
    # Senha padrão para hotsite
    senha_padrao = "123456"
    
    # ID do vendedor padrão (pode ser ajustado depois)
    id_vendedor_padrao = "33"  # Recepção como padrão
    
    payload = {
        # Dados obrigatórios
        "ativo": "S",
        "id_tipo_cliente": config["id_tipo_cliente"],
        "tipo_cliente_scm": config["tipo_cliente_scm"],
        "tipo_pessoa": "F",                     # Física
        "filial_id": config["filial_id"],
        "filtra_filial": "S",
        
        # Identificação
        "razao": nome_completo,
        "nome_social": nome_completo,
        "fantasia": nome_completo,
        "cnpj_cpf": cpf,
        "ie_identidade": rg,
        "data_nascimento": data_nasc_formatada,
        
        # Contato
        "email": email,
        "telefone_celular": celular_limpo,
        "whatsapp": celular_limpo,
        "fone": cliente_data.get("telefone_comercial", "") or celular_limpo,
        
        # Endereço
        "endereco": endereco,
        "numero": numero,
        "complemento": complemento,
        "bairro": bairro,
        "cidade": cidade,
        "uf": uf,
        "cep": cep,
        "tipo_localidade": "U",
        
        # Bloco e Apartamento
        "bloco": bloco,
        "apartamento": apartamento,
        
        # Hotsite (portal do assinante)
        "hotsite_email": email,
        "senha": senha_padrao,
        "senha_hotsite_md5": "N",
        "hotsite_acesso": "2",      # 2 = liberado
        "acesso_automatico_central": "P",
        "alterar_senha_primeiro_acesso": "S",
        
        # Vendedor / Responsável (padrão)
        "id_vendedor": id_vendedor_padrao,
        "responsavel": id_vendedor_padrao,
        
        # Outros padrões
        "participa_cobranca": "S",
        "participa_pre_cobranca": "S",
        "cob_envia_email": "S",
        "cob_envia_sms": "S",
        "contribuinte_icms": "N",
        "nacionalidade": "Brasileiro",
        "status_prospeccao": "C",   # C = Cliente
        "tipo_assinante": "3",      # 3 = Residencial
        
        # Observações
        "obs": (cliente_data.get("observacoes", "")[:500] if cliente_data.get("observacoes") else ""),
    }
    
    # Adiciona condomínio se existir
    if cliente_data.get("condominio_nome"):
        payload["referencia"] = f"Condomínio: {cliente_data['condominio_nome']}"
    
    # Remove campos vazios para não dar erro na API
    payload = {k: v for k, v in payload.items() if v not in (None, "", [])}
    
    return payload

# ============================================================================
# FUNÇÃO PARA BUSCAR CLIENTE NO IXC POR CPF (evitar duplicatas)
# ============================================================================
def buscar_cliente_ixc_por_cpf(cpf: str, config: Dict) -> Optional[str]:
    """
    Busca um cliente no IXC pelo CPF.
    Retorna o ID se encontrar, None caso contrário.
    """
    if not cpf or len(cpf) < 11:
        return None
    
    host = config["host"]
    url = f"https://{host}/webservice/v1/cliente"
    token = config["token"]
    
    auth_string = base64.b64encode(token.encode('utf-8')).decode('utf-8')
    
    # Query para buscar por CPF
    payload = {
        "qtype": "cliente.cnpj_cpf",
        "query": cpf,
        "oper": "=",
        "page": "1",
        "rp": "1"
    }
    
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Basic {auth_string}",
        "ixcsoft": "listar"
    }
    
    try:
        response = requests.post(
            url,
            data=json.dumps(payload),
            headers=headers,
            timeout=15
        )
        
        if response.status_code == 200:
            dados = response.json()
            # Tenta diferentes estruturas de resposta
            if "registros" in dados and dados["registros"]:
                return str(dados["registros"][0].get("id"))
            elif "data" in dados and dados["data"]:
                return str(dados["data"][0].get("id"))
            elif isinstance(dados, list) and dados:
                return str(dados[0].get("id"))
        return None
    except Exception as e:
        print(f"Erro ao buscar cliente no IXC: {e}")
        return None

# ============================================================================
# FUNÇÃO PRINCIPAL: ENVIAR CLIENTE AO IXC
# ============================================================================
def enviar_cliente_para_ixc(cliente_data: Dict) -> Tuple[bool, Optional[str], Optional[str]]:
    """
    Envia os dados do cliente para a API do IXC.
    
    Retorna:
        (sucesso, id_ixc, mensagem_erro)
    """
    config = get_ixc_config()
    if not config:
        return False, None, "Configuração do IXC não encontrada. Verifique os segredos."
    
    # Verificar se tem CPF (obrigatório para buscar/evitar duplicatas)
    cpf = cliente_data.get("cpf", "")
    if not cpf or len(cpf) < 11:
        # Se não tem CPF, ainda tenta criar, mas avisa
        print("⚠️ Cliente sem CPF - integração com IXC pode falhar")
    
    # 1. Verificar se cliente já existe no IXC (evitar duplicatas)
    if cpf and len(cpf) >= 11:
        id_existente = buscar_cliente_ixc_por_cpf(cpf, config)
        if id_existente:
            print(f"✅ Cliente já existe no IXC com ID: {id_existente}")
            return True, id_existente, None
    
    # 2. Construir payload
    payload = construir_payload_ixc(cliente_data, config)
    
    # 3. Preparar requisição
    host = config["host"]
    url = f"https://{host}/webservice/v1/cliente"
    token = config["token"]
    
    auth_string = base64.b64encode(token.encode('utf-8')).decode('utf-8')
    
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Basic {auth_string}"
    }
    
    # 4. Enviar (com retry)
    max_tentativas = 2
    for tentativa in range(max_tentativas):
        try:
            response = requests.post(
                url,
                data=json.dumps(payload),
                headers=headers,
                timeout=30
            )
            
            if response.status_code in [200, 201]:
                # Tenta extrair o ID do cliente criado
                id_ixc = None
                try:
                    resposta_json = response.json()
                    # Tenta diferentes formatos de resposta
                    if isinstance(resposta_json, dict):
                        id_ixc = resposta_json.get("id") or resposta_json.get("ID") or \
                                 resposta_json.get("cliente_id") or resposta_json.get("registro_id")
                    elif isinstance(resposta_json, list) and resposta_json:
                        id_ixc = resposta_json[0].get("id")
                    
                    if not id_ixc and response.text:
                        # Se conseguiu criar mas não retornou ID, tenta buscar por CPF novamente
                        if cpf and len(cpf) >= 11:
                            id_ixc = buscar_cliente_ixc_por_cpf(cpf, config)
                    
                    return True, str(id_ixc) if id_ixc else "ok", None
                except:
                    return True, "ok", None
                    
            elif response.status_code == 409:
                # Conflito - provavelmente já existe
                return True, "existente", None
            else:
                erro_msg = f"HTTP {response.status_code}: {response.text[:200]}"
                if tentativa == max_tentativas - 1:
                    return False, None, erro_msg
                continue
                
        except requests.exceptions.Timeout:
            if tentativa == max_tentativas - 1:
                return False, None, "Timeout na conexão com o IXC"
            continue
        except requests.exceptions.ConnectionError:
            if tentativa == max_tentativas - 1:
                return False, None, "Erro de conexão com o IXC"
            continue
        except Exception as e:
            if tentativa == max_tentativas - 1:
                return False, None, str(e)
            continue
    
    return False, None, "Falha após múltiplas tentativas"

# ============================================================================
# FUNÇÃO PARA REGISTRAR PENDÊNCIA DE INTEGRAÇÃO (para tentar depois)
# ============================================================================
def registrar_pendencia_integracao(cliente_id, cliente_data, erro_msg):
    """
    Registra que este cliente precisa ser sincronizado posteriormente.
    """
    try:
        from pymongo import MongoClient
        # Usa a conexão existente
        clientes_collection = st.session_state.get("clientes_collection")
        if clientes_collection:
            clientes_collection.update_one(
                {"_id": cliente_id},
                {"$set": {
                    "integrado_ixc": False,
                    "erro_integracao_ixc": erro_msg,
                    "tentativas_integracao": 1,
                    "ultima_tentativa_integracao": datetime.now(),
                    "dados_pendentes_integracao": cliente_data  # salva para tentar depois
                }}
            )
    except Exception as e:
        print(f"Erro ao registrar pendência: {e}")
