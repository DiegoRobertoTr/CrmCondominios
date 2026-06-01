# modules/integracao_ixc.py - VERSÃO COM VALORES PADRÃO E VALIDAÇÃO TOTAL
import requests
import base64
import json
import streamlit as st
from datetime import datetime
from typing import Dict, Optional, Tuple
import urllib3

# 🔒 Suprime avisos de certificado autoassinado
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# ============================================================================
# CONFIGURAÇÕES
# ============================================================================
def get_ixc_config():
    """Retorna configuração da API IXC a partir de st.secrets"""
    try:
        config = {
            "host": st.secrets["ixc"]["host"],
            "token": st.secrets["ixc"]["token"],
            "filial_id": st.secrets["ixc"].get("filial_id", "1"),
            "id_tipo_cliente": st.secrets["ixc"].get("id_tipo_cliente", "03"),
            "tipo_cliente_scm": st.secrets["ixc"].get("tipo_cliente_scm", "01"),
        }
        print(f"🔍 Configuração IXC carregada: Host={config['host']}")
        return config
    except Exception as e:
        st.error(f"❌ Erro ao carregar configuração do IXC: {e}")
        return None

def _sanitizar_host(host: str) -> str:
    """Remove protocolo e caminhos para evitar URL duplicada."""
    host = host.replace("https://", "").replace("http://", "")
    return host.split("/")[0].strip().rstrip("/")

# ============================================================================
# CONSTRUÇÃO DO PAYLOAD COM VALORES PADRÃO
# ============================================================================
def construir_payload_ixc(cliente_data: Dict, config: Dict) -> Dict:
    """Converte os dados do cliente para o formato esperado pelo IXC.
    Todos os campos obrigatórios recebem valores padrão se estiverem vazios."""
    
    # ========== CAMPOS DO CLIENTE (com fallback) ==========
    nome_completo = cliente_data.get("nome_completo", "").strip()
    cpf = cliente_data.get("cpf", "").strip()
    rg = cliente_data.get("rg", "").strip()
    data_nascimento = cliente_data.get("data_nascimento", "")
    email = cliente_data.get("email", "").strip()
    celular = cliente_data.get("celular", "").strip()
    
    # ========== ENDEREÇO (com fallback) ==========
    endereco = cliente_data.get("endereco", "").strip()
    numero = cliente_data.get("numero", "").strip()
    complemento = cliente_data.get("complemento", "").strip()
    bairro = cliente_data.get("bairro", "").strip()
    cidade = cliente_data.get("cidade", "Rio de Janeiro").strip()
    uf = cliente_data.get("uf", "RJ").strip().upper()
    cep = cliente_data.get("cep", "").strip()
    
    # ========== DADOS DO CONDOMÍNIO ==========
    bloco = cliente_data.get("bloco", "").strip()
    apartamento = cliente_data.get("apartamento", "").strip()
    
    # ========== LIMPEZA DE TELEFONE ==========
    celular_limpo = ""
    if celular:
        celular_limpo = celular.replace(" ", "").replace("-", "").replace("(", "").replace(")", "")
    
    # ========== DATA DE NASCIMENTO ==========
    data_nasc_formatada = ""
    if data_nascimento:
        try:
            if isinstance(data_nascimento, str):
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
    
    # ========== VALORES PADRÃO (CRÍTICO PARA EVITAR ERROS) ==========
    # CPF padrão se não informado (apenas para teste)
    if not cpf or len(cpf) < 11:
        cpf = "00000000000"
        print(f"⚠️ CPF não informado, usando padrão: {cpf}")
    
    # Email padrão se não informado
    if not email:
        email = f"cliente_{datetime.now().strftime('%Y%m%d%H%M%S')}@temp.com"
        print(f"⚠️ Email não informado, usando padrão: {email}")
    
    # Telefone padrão se não informado
    if not celular_limpo:
        celular_limpo = "00000000000"
        print(f"⚠️ Telefone não informado, usando padrão: {celular_limpo}")
    
    # Endereço padrão se não informado
    if not endereco:
        endereco = "Endereço não informado"
        print(f"⚠️ Endereço não informado, usando padrão")
    
    # Número padrão se não informado
    if not numero:
        numero = "0"
        print(f"⚠️ Número não informado, usando padrão: 0")
    
    # Bairro padrão se não informado
    if not bairro:
        bairro = "Centro"
        print(f"⚠️ Bairro não informado, usando padrão: Centro")
    
    # Nome padrão se não informado (último recurso)
    if not nome_completo:
        nome_completo = "Cliente não identificado"
        print(f"⚠️ Nome não informado, usando padrão")
    
    # ========== BUSCAR ID DO CONDOMÍNIO NO IXC ==========
    id_condominio_ixc = None
    if cliente_data.get("condominio_id"):
        try:
            from .condominios import get_condominio_by_id
            cond_data = get_condominio_by_id(cliente_data["condominio_id"])
            if cond_data and cond_data.get("id_ixc"):
                id_condominio_ixc = cond_data["id_ixc"]
                print(f"✅ Condomínio encontrado com ID IXC: {id_condominio_ixc}")
        except Exception as e:
            print(f"⚠️ Erro ao buscar ID do condomínio: {e}")
    
    # ========== CONSTRUIR PAYLOAD ==========
    payload = {
        "ativo": "S",
        "id_tipo_cliente": config["id_tipo_cliente"],
        "tipo_cliente_scm": config["tipo_cliente_scm"],
        "tipo_pessoa": "F",
        "filial_id": config["filial_id"],
        "filtra_filial": "S",
        "razao": nome_completo,
        "nome_social": nome_completo,
        "fantasia": nome_completo,
        "cnpj_cpf": cpf,
        "ie_identidade": rg if rg else "ISENTO",
        "data_nascimento": data_nasc_formatada,
        "email": email,
        "telefone_celular": celular_limpo,
        "whatsapp": celular_limpo,
        "fone": celular_limpo,
        "endereco": endereco,
        "numero": numero,
        "complemento": complemento if complemento else " ",
        "bairro": bairro,
        "cidade": cidade,
        "uf": uf,
        "cep": cep if cep else "00000000",
        "tipo_localidade": "U",
        "bloco": bloco if bloco else " ",
        "apartamento": apartamento if apartamento else " ",
        "hotsite_email": email,
        "senha": "123456",
        "senha_hotsite_md5": "N",
        "hotsite_acesso": "2",
        "acesso_automatico_central": "P",
        "alterar_senha_primeiro_acesso": "S",
        "id_vendedor": "33",
        "responsavel": "33",
        "participa_cobranca": "S",
        "participa_pre_cobranca": "S",
        "cob_envia_email": "S",
        "cob_envia_sms": "S",
        "contribuinte_icms": "N",
        "nacionalidade": "Brasileiro",
        "status_prospeccao": "C",
        "tipo_assinante": "3",
        "obs": (cliente_data.get("observacoes", "")[:500] if cliente_data.get("observacoes") else ""),
    }
    
    if id_condominio_ixc:
        payload["id_condominio"] = id_condominio_ixc
    elif cliente_data.get("condominio_nome"):
        payload["referencia"] = f"Condomínio: {cliente_data['condominio_nome']}"
    
    return payload

# ============================================================================
# FUNÇÃO PARA BUSCAR CLIENTE POR CPF
# ============================================================================
def buscar_cliente_ixc_por_cpf(cpf: str, config: Dict) -> Optional[str]:
    """Busca um cliente no IXC pelo CPF."""
    if not cpf or len(cpf) < 11:
        return None
    
    host_limpo = _sanitizar_host(config["host"])
    url = f"https://{host_limpo}/webservice/v1/cliente"
    auth_string = base64.b64encode(config["token"].encode('utf-8')).decode('utf-8')
    
    payload = {"qtype": "cliente.cnpj_cpf", "query": cpf, "oper": "=", "page": "1", "rp": "1"}
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Basic {auth_string}",
        "ixcsoft": "listar"
    }
    
    try:
        response = requests.post(url, data=json.dumps(payload), headers=headers, timeout=15, verify=False)
        if response.status_code == 200:
            dados = response.json()
            if "registros" in dados and dados["registros"]:
                return str(dados["registros"][0].get("id"))
            elif "data" in dados and dados["data"]:
                return str(dados["data"][0].get("id"))
        return None
    except Exception as e:
        print(f"Erro ao buscar cliente: {e}")
        return None

# ============================================================================
# FUNÇÃO PRINCIPAL: ENVIAR CLIENTE COM VALIDAÇÃO TOTAL
# ============================================================================
def enviar_cliente_para_ixc(cliente_data: Dict) -> Tuple[bool, Optional[str], Optional[str]]:
    """Envia cliente para API do IXC com valores padrão e validação rigorosa."""
    
    print("\n" + "=" * 70)
    print("🚀 INICIANDO INTEGRAÇÃO COM IXC")
    print("=" * 70)
    
    config = get_ixc_config()
    if not config:
        return False, None, "Configuração do IXC não encontrada."
    
    cpf = cliente_data.get("cpf", "")
    nome = cliente_data.get("nome_completo", "")
    print(f"📋 Cliente: {nome} | CPF: {cpf if cpf else 'não informado'}")
    
    # Verificar duplicata
    if cpf and len(cpf) >= 11:
        id_existente = buscar_cliente_ixc_por_cpf(cpf, config)
        if id_existente:
            print(f"✅ Cliente já existe com ID: {id_existente}")
            return True, id_existente, None
    
    # Construir payload (já com valores padrão)
    payload = construir_payload_ixc(cliente_data, config)
    
    # Preparar requisição
    host_limpo = _sanitizar_host(config["host"])
    url = f"https://{host_limpo}/webservice/v1/cliente"
    auth_string = base64.b64encode(config["token"].encode('utf-8')).decode('utf-8')
    
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Basic {auth_string}",
        "ixcsoft": ""
    }
    
    # LOG DO PAYLOAD (útil para debug)
    print(f"\n📤 URL: {url}")
    print(f"📦 Payload enviado (campos principais):")
    for key in ["razao", "cnpj_cpf", "email", "telefone_celular", "endereco", "numero", "bairro"]:
        print(f"   {key}: {payload.get(key, 'N/A')}")
    
    try:
        response = requests.post(
            url,
            data=json.dumps(payload),
            headers=headers,
            timeout=30,
            verify=False
        )
        
        print(f"\n📥 Status: {response.status_code}")
        
        # ========== VALIDAÇÃO RIGOROSA DA RESPOSTA ==========
        
        # 1. Verificar se é JSON
        content_type = response.headers.get('Content-Type', '')
        if 'application/json' not in content_type:
            print(f"❌ Resposta não é JSON. Content-Type: {content_type}")
            print(f"   Resposta: {response.text[:300]}")
            return False, None, f"API retornou HTML/Texto. Verifique se o host está correto."
        
        # 2. Tentar decodificar JSON
        try:
            resposta_json = response.json()
            print(f"📄 Resposta JSON: {json.dumps(resposta_json, indent=2, ensure_ascii=False)[:500]}")
        except json.JSONDecodeError as e:
            print(f"❌ JSON inválido: {e}")
            print(f"   Resposta: {response.text[:300]}")
            return False, None, f"Resposta inválida da API: {response.text[:100]}"
        
        # 3. Verificar se a API retornou erro explícito
        if isinstance(resposta_json, dict):
            # IXC retorna {"tipo": "erro", "mensagem": "..."}
            if resposta_json.get("tipo") == "erro":
                erro = resposta_json.get("mensagem") or resposta_json.get("message", "Erro desconhecido")
                print(f"❌ API retornou erro: {erro}")
                return False, None, f"Erro IXC: {erro}"
            
            # Algumas versões usam "success": false
            if resposta_json.get("success") is False:
                erro = resposta_json.get("message") or resposta_json.get("error", "Erro desconhecido")
                print(f"❌ API retornou success=false: {erro}")
                return False, None, f"Erro IXC: {erro}"
            
            # 4. Buscar ID do cliente criado
            id_ixc = (
                resposta_json.get("id") or 
                resposta_json.get("ID") or 
                resposta_json.get("cliente_id") or 
                resposta_json.get("registro_id")
            )
            
            if id_ixc:
                print(f"✅ Cliente criado com sucesso! ID IXC: {id_ixc}")
                return True, str(id_ixc), None
            else:
                # Resposta de sucesso sem ID (caso raro)
                if resposta_json.get("tipo") == "sucesso" or resposta_json.get("success") is True:
                    print(f"⚠️ API indicou sucesso mas não retornou ID")
                    return True, "ok_sem_id", None
                
                print(f"❌ Resposta não contém ID e não indica erro claro")
                return False, None, f"Resposta inesperada: {json.dumps(resposta_json)[:200]}"
        
        # Resposta não é dicionário
        print(f"❌ Resposta em formato inesperado: {type(resposta_json)}")
        return False, None, f"Formato de resposta inesperado: {type(resposta_json)}"
        
    except requests.exceptions.Timeout:
        return False, None, "Timeout: API não respondeu em 30 segundos"
    except requests.exceptions.ConnectionError as e:
        return False, None, f"Erro de conexão: Verifique se o IXC está acessível. Detalhe: {str(e)[:100]}"
    except Exception as e:
        return False, None, f"Erro inesperado: {str(e)}"

# ============================================================================
# FUNÇÃO DE TESTE PARA O PAINEL ADMIN
# ============================================================================
def render_teste_conexao():
    """Renderiza painel de teste de conexão."""
    st.subheader("🔌 Teste de Conexão com IXCsoft")
    
    if st.button("🧪 Testar Conexão"):
        with st.spinner("Testando..."):
            config = get_ixc_config()
            if not config:
                st.error("Configuração não encontrada")
                return
            
            host_limpo = _sanitizar_host(config["host"])
            url = f"https://{host_limpo}/webservice/v1/cliente"
            
            st.write(f"🌐 Testando: {url}")
            
            try:
                response = requests.get(url, timeout=5, verify=False)
                if response.status_code == 200:
                    st.success(f"✅ Conexão OK! Status: {response.status_code}")
                else:
                    st.warning(f"⚠️ Conexão estabelecida mas retornou status: {response.status_code}")
            except Exception as e:
                st.error(f"❌ Falha na conexão: {e}")
