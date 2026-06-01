# modules/integracao_ixc.py - VERSÃO FINAL BLINDADA
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
def get_ixc_config() -> Optional[Dict]:
    """Retorna configuração da API IXC a partir de st.secrets."""
    try:
        config = {
            "host": st.secrets["ixc"]["host"],
            "token": st.secrets["ixc"]["token"],
            "filial_id": st.secrets["ixc"].get("filial_id", "1"),
            "id_tipo_cliente": st.secrets["ixc"].get("id_tipo_cliente", "03"),
            "tipo_cliente_scm": st.secrets["ixc"].get("tipo_cliente_scm", "01"),
            "id_vendedor_padrao": st.secrets["ixc"].get("id_vendedor_padrao", "1")
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
    
    resultados["testes"].append({"nome": "Formato do Host", "sucesso": True, "detalhe": f"Host sanitizado: {host_limpo}"})
    
    try:
        url = f"https://{host_limpo}/webservice/v1/cliente"
        auth_string = base64.b64encode(config["token"].encode('utf-8')).decode('utf-8')
        payload = {"qtype": "cliente.id", "query": "1", "oper": ">", "page": "1", "rp": "1"}
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Basic {auth_string}",
            "ixcsoft": "listar"
        }
        
        print(f"🔍 Testando conexão com: {url}")
        response = requests.post(url, json=payload, headers=headers, timeout=10, verify=False)
        
        resultados["testes"].append({"nome": "Conexão HTTP", "sucesso": response.status_code in [200, 201], "detalhe": f"Status: {response.status_code}"})
        
        if response.status_code in [200, 201]:
            resultados["sucesso"] = True
            try:
                dados = response.json()
                resultados["testes"].append({"nome": "Resposta JSON", "sucesso": True, "detalhe": "API respondeu com JSON válido"})
            except Exception:
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
# CONSTRUÇÃO DO PAYLOAD PARA IXC (BLINDADA CONTRA None + ISS OBRIGATÓRIO)
# ============================================================================
def construir_payload_ixc(cliente_data: Dict, config: Dict) -> Tuple[Dict, Optional[str]]:
    """Constrói payload seguro para IXC e valida campos obrigatórios."""
    
    # ✅ Função auxiliar que evita 'NoneType has no attribute strip'
    def safe(val: any) -> str:
        return str(val).strip() if val is not None else ""

    # Sanitização e extração segura
    nome_completo = safe(cliente_data.get("nome_completo"))
    cpf = "".join(filter(str.isdigit, safe(cliente_data.get("cpf"))))
    rg = safe(cliente_data.get("rg"))
    email = safe(cliente_data.get("email"))
    celular = "".join(filter(str.isdigit, safe(cliente_data.get("celular"))))
    telefone_com = "".join(filter(str.isdigit, safe(cliente_data.get("telefone_comercial"))))
    fone = celular or telefone_com
    cep = "".join(filter(str.isdigit, safe(cliente_data.get("cep"))))

    endereco = safe(cliente_data.get("endereco"))
    numero = safe(cliente_data.get("numero"))
    complemento = safe(cliente_data.get("complemento"))
    bairro = safe(cliente_data.get("bairro"))
    cidade = safe(cliente_data.get("cidade")) or "Rio de Janeiro"
    uf = (safe(cliente_data.get("uf")) or "RJ").upper()
    bloco = safe(cliente_data.get("bloco"))
    apartamento = safe(cliente_data.get("apartamento"))
    obs = safe(cliente_data.get("observacoes"))[:500]

    # Validação rápida de obrigatórios
    obrigatorios = {
        "razao": nome_completo, "cnpj_cpf": cpf, "cidade": cidade, 
        "uf": uf, "endereco": endereco, "numero": numero, "bairro": bairro, "cep": cep, "fone": fone, "email": email
    }
    faltando = [k for k, v in obrigatorios.items() if not v]
    if faltando:
        return {}, f"Campos obrigatórios ausentes ou vazios: {', '.join(faltando)}"

    # Data de nascimento
    data_nasc_formatada = ""
    raw_nasc = cliente_data.get("data_nascimento")
    if raw_nasc:
        for fmt in ["%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y"]:
            try:
                dt = datetime.strptime(str(raw_nasc).strip(), fmt)
                data_nasc_formatada = dt.strftime("%Y-%m-%d")
                break
            except ValueError:
                continue

    # Buscar ID Condomínio
    id_condominio_ixc = None
    if cliente_data.get("condominio_id"):
        try:
            from .condominios import get_condominio_by_id
            cond_data = get_condominio_by_id(cliente_data["condominio_id"])
            if cond_data and cond_data.get("id_ixc"):
                id_condominio_ixc = str(cond_data["id_ixc"])
        except Exception as e:
            print(f"⚠️ Erro ao buscar condomínio: {e}")

    payload = {
        "ativo": "S",
        "id_tipo_cliente": config.get("id_tipo_cliente", "03"),
        "tipo_cliente_scm": config.get("tipo_cliente_scm", "01"),
        "filial_id": config.get("filial_id", "1"),
        "filtra_filial": "S",
        "tipo_pessoa": "F",
        "razao": nome_completo,
        "nome_social": nome_completo,
        "fantasia": nome_completo,
        "cnpj_cpf": cpf,
        "ie_identidade": rg,
        "data_nascimento": data_nasc_formatada,
        "email": email,
        "telefone_celular": celular,
        "whatsapp": celular,
        "fone": fone,
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
        "acesso_automatico_central": "P",
        "alterar_senha_primeiro_acesso": "S",
        "hotsite_acesso": "2",
        "senha_hotsite_md5": "N",
        # ✅ CAMPO OBRIGATÓRIO QUE ESTAVA FALTANDO:
        "iss_classificacao_padrao": "99",  # "99" = Outros Serviços (valor padrão seguro)
        # ✅ Configurações de vendedor
        "responsavel": config.get("id_vendedor_padrao", "1"),
        "id_vendedor": config.get("id_vendedor_padrao", "1"),
        # ✅ Configurações de cobrança
        "participa_cobranca": "S",
        "participa_pre_cobranca": "S",
        "cob_envia_email": "S",
        "cob_envia_sms": "S",
        # ✅ Outros campos obrigatórios
        "contribuinte_icms": "N",
        "nacionalidade": "Brasileiro",
        "status_prospeccao": "C",
        "tipo_assinante": "3",
        "obs": obs
    }

    if id_condominio_ixc:
        payload["id_condominio"] = id_condominio_ixc
    elif cliente_data.get("condominio_nome"):
        payload["referencia"] = f"Condomínio: {safe(cliente_data['condominio_nome'])}"
        
    # IXC rejeita campos vazios explícitos - remove apenas None, "" ou " "
    return {k: v for k, v in payload.items() if v not in (None, "", " ", [], {})}, None

# ============================================================================
# FUNÇÃO PARA BUSCAR CLIENTE NO IXC POR CPF
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
        response = requests.post(url, json=payload, headers=headers, timeout=15, verify=False)
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
    if cpf and len("".join(filter(str.isdigit, str(cpf)))) >= 11:
        print(f"🔍 Verificando se CPF {cpf} já existe no IXC...")
        id_existente = buscar_cliente_ixc_por_cpf(cpf, config)
        if id_existente:
            print(f"✅ Cliente já existe no IXC com ID: {id_existente}")
            return True, id_existente, None

    # Construir payload
    payload, erro_validacao = construir_payload_ixc(cliente_data, config)
    if erro_validacao:
        return False, None, erro_validacao

    # Preparar requisição
    host_limpo = _sanitizar_host(config["host"])
    url = f"https://{host_limpo}/webservice/v1/cliente"
    auth_string = base64.b64encode(config["token"].encode('utf-8')).decode('utf-8')

    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Basic {auth_string}",
        "ixcsoft": "inserir"  # ✅ Padrão oficial para criação via POST
    }

    print(f"\n🌐 URL da requisição: {url}")
    print(f"📤 Payload size: {len(json.dumps(payload))} bytes")
    
    try:
        # ✅ Usa json=payload (requests cuida do dumps + content-type automaticamente)
        response = requests.post(url, json=payload, headers=headers, timeout=30, verify=False)
        
        print(f"\n📥 RESPOSTA RECEBIDA: Status={response.status_code}")
        print(f"   Resposta bruta: {response.text[:400]}")
        
        if response.status_code in [200, 201]:
            try:
                resposta_json = response.json()
                
                # ✅ VERIFICAÇÃO CRÍTICA: IXC retorna 200 mesmo com erro!
                if resposta_json.get("type") == "error" or resposta_json.get("success") is False:
                    erro = resposta_json.get("message") or resposta_json.get("error") or "Erro desconhecido na API"
                    print(f"❌ API retornou erro interno: {erro}")
                    return False, None, f"Erro na API: {erro}"
                
                id_ixc = resposta_json.get("id") or resposta_json.get("cliente_id") or resposta_json.get("registro_id")
                print(f"✅ Cliente integrado com sucesso! ID: {id_ixc or 'não retornado'}")
                return True, str(id_ixc) if id_ixc else "ok", None
                
            except ValueError:
                if any(x in response.text.lower() for x in ["sucesso", "success", "created"]):
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
