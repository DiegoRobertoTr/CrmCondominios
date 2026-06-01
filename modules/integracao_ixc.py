# modules/integracao_ixc.py - VERSÃO FINAL CORRIGIDA
import requests
import base64
import json
import streamlit as st
from datetime import datetime
from typing import Dict, Optional, Tuple
import urllib3

# 🔒 Suprime avisos de certificado autoassinado (comum no IXCsoft)
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# ============================================================================
# CONFIGURAÇÕES (ler dos segredos do Streamlit)
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
        print(f"🔍 Configuração IXC carregada: Host={config['host']}, Filial={config['filial_id']}")
        return config
    except Exception as e:
        st.error(f"❌ Erro ao carregar configuração do IXC: {e}")
        print(f"❌ Erro detalhado ao carregar secrets: {e}")
        return None

def _sanitizar_host(host: str) -> str:
    """Remove protocolo, caminhos e barras para evitar URL duplicada."""
    host = host.replace("https://", "").replace("http://", "")
    return host.split("/")[0].strip().rstrip("/")

# ============================================================================
# FUNÇÃO PARA TESTAR CONEXÃO COM O IXC
# ============================================================================
def testar_conexao_ixc() -> Dict:
    """Testa a conexão com a API do IXC e retorna diagnóstico."""
    config = get_ixc_config()
    if not config:
        return {"sucesso": False, "erro": "Configuração não encontrada"}
    
    resultados = {"sucesso": False, "testes": [], "erro": None}
    host_limpo = _sanitizar_host(config["host"])
    token = config["token"]
    
    resultados["testes"].append({
        "nome": "Formato do Host",
        "sucesso": True,
        "detalhe": f"Host sanitizado: {host_limpo}"
    })
    
    try:
        url = f"https://{host_limpo}/webservice/v1/cliente"
        auth_string = base64.b64encode(token.encode('utf-8')).decode('utf-8')
        payload = {"qtype": "cliente.id", "query": "1", "oper": ">", "page": "1", "rp": "1"}
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Basic {auth_string}",
            "ixcsoft": "listar"  # ✅ Obrigatório para consultas
        }
        
        print(f"🔍 Testando conexão com: {url}")
        response = requests.post(url, data=json.dumps(payload), headers=headers, timeout=10, verify=False)
        
        resultados["testes"].append({
            "nome": "Conexão HTTP",
            "sucesso": response.status_code in [200, 201],
            "detalhe": f"Status: {response.status_code}"
        })
        
        if response.status_code in [200, 201]:
            resultados["sucesso"] = True
            try:
                dados = response.json()
                resultados["testes"].append({"nome": "Resposta JSON", "sucesso": True, "detalhe": "API respondeu com JSON válido"})
            except:
                resultados["testes"].append({"nome": "Resposta JSON", "sucesso": False, "detalhe": f"Resposta não é JSON: {response.text[:100]}"})
        else:
            resultados["erro"] = f"HTTP {response.status_code}"
            resultados["testes"].append({"nome": "Resposta", "sucesso": False, "detalhe": response.text[:200]})
            
    except requests.exceptions.Timeout:
        resultados["erro"] = "Timeout - IXC não respondeu"
        resultados["testes"].append({"nome": "Timeout", "sucesso": False, "detalhe": "A conexão expirou após 10 segundos"})
    except requests.exceptions.ConnectionError as e:
        resultados["erro"] = "Erro de conexão"
        resultados["testes"].append({"nome": "Conexão", "sucesso": False, "detalhe": str(e)[:200]})
    except Exception as e:
        resultados["erro"] = str(e)
        resultados["testes"].append({"nome": "Erro", "sucesso": False, "detalhe": str(e)[:200]})
    
    return resultados

# ============================================================================
# CONSTRUÇÃO DO PAYLOAD PARA IXC
# ============================================================================
def construir_payload_ixc(cliente_data: Dict, config: Dict) -> Dict:
    """Converte os dados do cliente para o formato esperado pela API do IXC."""
    nome_completo = cliente_data.get("nome_completo", "")
    cpf = cliente_data.get("cpf", "")
    rg = cliente_data.get("rg", "")
    data_nascimento = cliente_data.get("data_nascimento", "")
    email = cliente_data.get("email", "")
    celular = cliente_data.get("celular", "")
    
    celular_limpo = celular.replace(" ", "").replace("-", "").replace("(", "").replace(")", "") if celular else ""
    
    endereco = cliente_data.get("endereco", "")
    numero = cliente_data.get("numero", "")
    complemento = cliente_data.get("complemento", "")
    bairro = cliente_data.get("bairro", "")
    cidade = cliente_data.get("cidade", "Rio de Janeiro")
    uf = cliente_data.get("uf", "RJ")
    cep = cliente_data.get("cep", "")
    
    bloco = cliente_data.get("bloco", "")
    apartamento = cliente_data.get("apartamento", "")
    
    # Data no formato YYYY-MM-DD
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
    
    senha_padrao = "123456"
    id_vendedor_padrao = "33"
    
    # Buscar ID do condomínio no IXC
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
        "ie_identidade": rg,
        "data_nascimento": data_nasc_formatada,
        "email": email,
        "telefone_celular": celular_limpo,
        "whatsapp": celular_limpo,
        "fone": cliente_data.get("telefone_comercial", "") or celular_limpo,
        "endereco": endereco,
        "numero": numero,
        "complemento": complemento,
        "bairro": bairro,
        "cidade": cidade,
        "uf": uf,
        "cep": cep,
        "tipo_localidade": "U",
        "bloco": bloco,
        "apartamento": apartamento,
        "hotsite_email": email,
        "senha": senha_padrao,
        "senha_hotsite_md5": "N",
        "hotsite_acesso": "2",
        "acesso_automatico_central": "P",
        "alterar_senha_primeiro_acesso": "S",
        "id_vendedor": id_vendedor_padrao,
        "responsavel": id_vendedor_padrao,
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
    
    # Remove campos vazios/nulos que o IXC rejeita
    payload = {k: v for k, v in payload.items() if v not in (None, "", [])}
    return payload

# ============================================================================
# FUNÇÃO PARA BUSCAR CLIENTE NO IXC POR CPF
# ============================================================================
def buscar_cliente_ixc_por_cpf(cpf: str, config: Dict) -> Optional[str]:
    """Busca um cliente no IXC pelo CPF."""
    if not cpf or len(cpf) < 11:
        return None
    
    host_limpo = _sanitizar_host(config["host"])
    url = f"https://{host_limpo}/webservice/v1/cliente"
    token = config["token"]
    auth_string = base64.b64encode(token.encode('utf-8')).decode('utf-8')
    
    payload = {"qtype": "cliente.cnpj_cpf", "query": cpf, "oper": "=", "page": "1", "rp": "1"}
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Basic {auth_string}",
        "ixcsoft": "listar"  # ✅ Obrigatório para consultas
    }
    
    try:
        response = requests.post(url, data=json.dumps(payload), headers=headers, timeout=15, verify=False)
        if response.status_code == 200:
            dados = response.json()
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
    """Envia os dados do cliente para a API do IXC com diagnóstico completo."""
    print("\n" + "=" * 70)
    print("🚀 INICIANDO INTEGRAÇÃO COM IXC")
    print("=" * 70)
    
    config = get_ixc_config()
    if not config:
        return False, None, "Configuração do IXC não encontrada."
    
    cpf = cliente_data.get("cpf", "")
    nome = cliente_data.get("nome_completo", "")
    print(f"📋 Dados do cliente: Nome={nome}, CPF={cpf}")
    
    # Verificar se cliente já existe
    if cpf and len(cpf) >= 11:
        print(f"🔍 Verificando se CPF {cpf} já existe no IXC...")
        id_existente = buscar_cliente_ixc_por_cpf(cpf, config)
        if id_existente:
            print(f"✅ Cliente já existe no IXC com ID: {id_existente}")
            return True, id_existente, None
    
    # Construir payload
    payload = construir_payload_ixc(cliente_data, config)
    
    # Preparar requisição
    host_limpo = _sanitizar_host(config["host"])
    url = f"https://{host_limpo}/webservice/v1/cliente"
    token = config["token"]
    
    print(f"\n🌐 URL da requisição: {url}")
    auth_string = base64.b64encode(token.encode('utf-8')).decode('utf-8')
    
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Basic {auth_string}",
        "ixcsoft": ""  # ✅ Vazio para CRIAÇÃO/EDIÇÃO
    }
    
    print(f"\n📤 Enviando requisição...")
    try:
        response = requests.post(
            url,
            data=json.dumps(payload),
            headers=headers,
            timeout=30,
            verify=False  # 🔥 Obrigatório para certificados autoassinados do IXC
        )
        
        print(f"\n📥 RESPOSTA RECEBIDA: Status={response.status_code}")
        print(f"   Resposta bruta: {response.text[:500]}")
        
        if response.status_code in [200, 201]:
            try:
                resposta_json = response.json()
                id_ixc = None
                if isinstance(resposta_json, dict):
                    id_ixc = resposta_json.get("id") or resposta_json.get("ID") or \
                             resposta_json.get("cliente_id") or resposta_json.get("registro_id")
                    
                    if resposta_json.get("success") is False:
                        erro = resposta_json.get("message") or resposta_json.get("error")
                        print(f"❌ API retornou erro: {erro}")
                        return False, None, f"Erro na API: {erro}"
                
                print(f"✅ Cliente integrado com sucesso! ID: {id_ixc if id_ixc else 'não retornado'}")
                return True, str(id_ixc) if id_ixc else "ok", None
                
            except json.JSONDecodeError as e:
                print(f"⚠️ Resposta não é JSON válido: {e}")
                if "sucesso" in response.text.lower() or "success" in response.text.lower():
                    return True, "ok", None
                return False, None, f"Resposta não JSON: {response.text[:200]}"
        else:
            erro_msg = f"HTTP {response.status_code}: {response.text[:300]}"
            print(f"❌ Falha na requisição: {erro_msg}")
            return False, None, erro_msg
            
    except requests.exceptions.Timeout:
        print("❌ Timeout - API não respondeu em 30 segundos")
        return False, None, "Timeout na conexão com o IXC"
    except requests.exceptions.ConnectionError as e:
        print(f"❌ Erro de conexão: {e}")
        return False, None, "Erro de conexão: O IXC não está acessível publicamente. Verifique firewall, DNS e se o Webservice está ativo."
    except Exception as e:
        print(f"❌ Erro inesperado: {e}")
        return False, None, str(e)

# ============================================================================
# FUNÇÃO PARA REGISTRAR PENDÊNCIA
# ============================================================================
def registrar_pendencia_integracao(cliente_id, cliente_data, erro_msg):
    """Registra que este cliente precisa ser sincronizado posteriormente."""
    try:
        clientes_collection = st.session_state.get("clientes_collection")
        if clientes_collection:
            clientes_collection.update_one(
                {"_id": cliente_id},
                {"$set": {
                    "integrado_ixc": False,
                    "erro_integracao_ixc": erro_msg,
                    "tentativas_integracao": 1,
                    "ultima_tentativa_integracao": datetime.now(),
                    "dados_pendentes_integracao": cliente_data
                }}
            )
            print(f"📝 Pendência registrada para cliente {cliente_id}")
    except Exception as e:
        print(f"❌ Erro ao registrar pendência: {e}")

# ============================================================================
# FUNÇÃO DE TESTE PARA O PAINEL ADMIN
# ============================================================================
def render_teste_conexao():
    """Renderiza um painel de teste de conexão com o IXC (para usar no admin)."""
    st.subheader("🔌 Teste de Conexão com IXCsoft")
    
    if st.button("🧪 Testar Conexão"):
        with st.spinner("Testando conexão..."):
            resultado = testar_conexao_ixc()
            
            st.write("### Resultados dos Testes:")
            for teste in resultado["testes"]:
                if teste["sucesso"]:
                    st.success(f"✅ {teste['nome']}: {teste.get('detalhe', 'OK')}")
                else:
                    st.error(f"❌ {teste['nome']}: {teste.get('detalhe', 'Falha')}")
            
            if resultado["sucesso"]:
                st.success("🎉 Conexão com IXC funcionando corretamente!")
            else:
                st.error(f"⚠️ Falha na conexão: {resultado['erro']}")
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
