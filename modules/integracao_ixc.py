# modules/integracao_ixc.py - VERSÃO CORRIGIDA
import requests
import re
import base64
import json
import streamlit as st
from datetime import datetime
from typing import Dict, Optional, Tuple
import urllib3

# 🔒 Suprime avisos de certificado autoassinado (comum no IXCsoft)
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# ============================================================================
# FORMATADORES — padrao exigido pelo IXC (descoberto nos testes R4)
# ============================================================================
def _fmt_cep(cep: str) -> str:
    """'20521130' -> '20521-130'  (formato obrigatorio no IXC)"""
    d = re.sub(r'\D', '', cep).zfill(8)
    return f"{d[:5]}-{d[5:]}" if len(d) == 8 else d


def _fmt_fone(fone: str) -> str:
    """'21999990001' -> '(21)999990001'  (formato armazenado no IXC)"""
    d = re.sub(r'\D', '', fone)
    if len(d) == 11:   # celular com 9
        return f"({d[:2]}){d[2:]}"
    if len(d) == 10:   # fixo
        return f"({d[:2]}){d[2:]}"
    return d  # formato desconhecido — retorna como veio

def _fmt_cpf(cpf: str) -> str:
    """'01234567890' -> '012.345.678-90'  (formato armazenado no IXC)"""
    d = re.sub(r'\D', '', cpf).zfill(11)
    return f"{d[:3]}.{d[3:6]}.{d[6:9]}-{d[9:]}" if len(d) == 11 else d

# IDs fixos para Rio de Janeiro (confirmados pelo diagnostico P28/P30)
_ID_CIDADE_RJ = "3241"
_ID_UF_RJ     = "24"

def _buscar_id_cidade(host_limpo: str, auth_string: str, cidade_nome: str, uf_sigla: str) -> tuple:
    """Busca os IDs numericos de cidade e UF no IXC. Fallback para RJ."""
    id_cidade = _ID_CIDADE_RJ
    id_uf     = _ID_UF_RJ
    try:
        h = {"Authorization": f"Basic {auth_string}", "ixcsoft": "listar",
             "Content-Type": "application/json"}
        r = requests.post(
            f"https://{host_limpo}/webservice/v1/cidade",
            json={"qtype": "cidade.nome", "query": cidade_nome, "oper": "=",
                  "page": "1", "rp": "10"},
            headers=h, timeout=10, verify=False
        )
        if r.status_code == 200:
            rj = r.json()
            regs = rj.get("registros") or rj.get("data") or []
            if regs:
                match = next((x for x in regs
                               if str(x.get("uf","")).upper() == uf_sigla.upper()), regs[0])
                id_cidade = str(match.get("id", id_cidade))
                id_uf     = str(match.get("uf", id_uf))
    except Exception as e:
        print(f"Nao foi possivel buscar ID da cidade '{cidade_nome}': {e} — usando fallback RJ")
    return id_cidade, id_uf


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
            "tipo_cliente_scm": st.secrets["ixc"].get("tipo_cliente_scm", "01")
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
# VALIDAÇÃO DE CPF (Algorítmica)
# ============================================================================
def validar_cpf(cpf: str) -> bool:
    """Valida CPF algorítmico (apenas dígitos)."""
    cpf = "".join(filter(str.isdigit, cpf))
    if len(cpf) != 11 or cpf == cpf[0] * 11:
        return False
    
    # Validação do primeiro dígito
    soma1 = sum(int(cpf[i]) * (10 - i) for i in range(9))
    digito1 = 0 if (soma1 * 10) % 11 >= 10 else (soma1 * 10) % 11
    if int(cpf[9]) != digito1:
        return False
        
    # Validação do segundo dígito
    soma2 = sum(int(cpf[i]) * (11 - i) for i in range(10))
    digito2 = 0 if (soma2 * 10) % 11 >= 10 else (soma2 * 10) % 11
    return int(cpf[10]) == digito2

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
                resultados["testes"].append({"nome": "Resposta JSON", "sucesso": False, "detalhe": f"Resposta não é JSON: {response.text[:100]"})
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
# CONSTRUÇÃO DO PAYLOAD PARA IXC (COM SANITIZAÇÃO COMPLETA)
# ============================================================================
def construir_payload_ixc(cliente_data: Dict, config: Dict) -> Tuple[Dict, Optional[str]]:
    """Constrói payload seguro para IXC, valida CPF e sanitiza todos os campos."""
    
    def safe(val: any) -> str:
        return str(val).strip() if val is not None else ""

    # 1. Sanitização rigorosa de TODOS os campos numéricos
    cpf_raw = safe(cliente_data.get("cpf"))
    cpf_digits = "".join(filter(str.isdigit, cpf_raw))  # digitos para validacao
    cpf = _fmt_cpf(cpf_digits)                          # formato IXC: XXX.XXX.XXX-XX
    
    rg = safe(cliente_data.get("rg"))
    
    cep_raw = safe(cliente_data.get("cep"))
    cep_digits = "".join(filter(str.isdigit, cep_raw))  # digitos para validacao
    cep = _fmt_cep(cep_digits)                             # formato IXC: XXXXX-XXX
    
    celular_raw = safe(cliente_data.get("celular"))
    celular_digits = "".join(filter(str.isdigit, celular_raw))
    celular = _fmt_fone(celular_digits)  # ✅ Remove espaços, traços, parênteses
    
    telefone_com_raw = safe(cliente_data.get("telefone_comercial"))
    telefone_com_digits = "".join(filter(str.isdigit, telefone_com_raw))
    telefone_com = _fmt_fone(telefone_com_digits)
    
    fone = celular or telefone_com

    # 2. Validação algorítmica do CPF
    if not validar_cpf(cpf_digits):
        return {}, f"CPF inválido: '{cpf_raw}'. Verifique os dígitos ou use um CPF válido para teste (ex: 070.995.620-17)."

    # 3. Validação do CEP (deve ter 8 dígitos)
    if cep_digits and len(cep_digits) != 8:
        return {}, f"CEP inválido: '{cep_raw}'. O CEP deve conter 8 dígitos (ex: 22775020)."

    # 4. Outros campos
    nome_completo = safe(cliente_data.get("nome_completo"))
    email = safe(cliente_data.get("email"))
    
    endereco = safe(cliente_data.get("endereco"))
    numero = safe(cliente_data.get("numero"))
    complemento = safe(cliente_data.get("complemento"))
    bairro = safe(cliente_data.get("bairro"))
    cidade_nome = safe(cliente_data.get("cidade")) or "Rio de Janeiro"
    uf_sigla     = (safe(cliente_data.get("uf")) or "RJ").upper()
    bloco = safe(cliente_data.get("bloco"))
    apartamento = safe(cliente_data.get("apartamento"))
    obs = safe(cliente_data.get("observacoes"))[:500]

    # 5. Data de nascimento
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

    # 5b. Buscar IDs de cidade e UF (IXC usa IDs numericos, nao texto)
    host_limpo_tmp = _sanitizar_host(config["host"])
    auth_tmp = base64.b64encode(config["token"].encode()).decode()
    id_cidade, id_uf = _buscar_id_cidade(host_limpo_tmp, auth_tmp, cidade_nome, uf_sigla)

    # 6. Buscar ID Condomínio e seus dados de endereço
    id_condominio_ixc = None
    cond_cep = ""
    cond_endereco = ""
    cond_numero = ""
    cond_bairro = ""
    cond_cidade = ""
    cond_uf = ""
    cond_complemento = ""

    if cliente_data.get("condominio_id"):
        try:
            from .condominios import get_condominio_by_id
            cond_data = get_condominio_by_id(cliente_data["condominio_id"])
            if cond_data and cond_data.get("id_ixc"):
                id_condominio_ixc = str(cond_data["id_ixc"])
                # Capturar campos de endereço do condomínio para repassar ao IXC
                # (o IXC valida CEP antes de fazer o preenchimento automático)
                raw_cond_cep = safe(cond_data.get("cep") or cond_data.get("CEP", ""))
                cond_cep = "".join(filter(str.isdigit, raw_cond_cep))
                cond_endereco = safe(cond_data.get("endereco") or cond_data.get("logradouro", ""))
                cond_numero = safe(cond_data.get("numero", ""))
                cond_bairro = safe(cond_data.get("bairro", ""))
                cond_cidade = safe(cond_data.get("cidade", ""))
                cond_uf = safe(cond_data.get("uf") or cond_data.get("estado", "")).upper()
                cond_complemento = safe(cond_data.get("complemento", ""))
        except Exception as e:
            print(f"⚠️ Erro ao buscar condomínio: {e}")

    # 7. Validação de campos obrigatórios ✅ CORRIGIDO
    #    Quando há id_condominio, o IXC preenche endereço automaticamente —
    #    logo CEP/endereço/bairro/cidade/UF NÃO são obrigatórios nesse caso.
    usando_condominio = bool(id_condominio_ixc)

    obrigatorios_sempre = {"razao": nome_completo, "cnpj_cpf": cpf, "fone": fone, "email": email}
    # ✅ CORREÇÃO: usar cidade_nome e uf_sigla ao invés de cidade/uf
    obrigatorios_sem_cond = {"cidade": cidade_nome, "uf": uf_sigla, "endereco": endereco,
                             "numero": numero, "bairro": bairro, "cep": cep}

    faltando = [k for k, v in obrigatorios_sempre.items() if not v]
    if not usando_condominio:
        faltando += [k for k, v in obrigatorios_sem_cond.items() if not v]

    if faltando:
        return {}, f"Campos obrigatórios ausentes: {', '.join(faltando)}"

    # 8. Montagem do payload base (sem endereço nem condomínio ainda)
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
        "tipo_localidade": "U",
        "acesso_automatico_central": "P",  # ✅ CORRIGIDO: era "S", agora "P" (padrão IXC)
        "alterar_senha_primeiro_acesso": "P",   # IXC espera "P", não "S"
        "hotsite_acesso": "2",
        "senha_hotsite_md5": "N",
        "hotsite_email": email,
        "senha": "123456",
        "iss_classificacao_padrao": "99",
        "participa_cobranca": "S",
        "participa_pre_cobranca": "S",
        "cob_envia_email": "S",
        "cob_envia_sms": "S",
        "contribuinte_icms": "N",
        "nacionalidade": "Brasileiro",
        "status_prospeccao": "C",
        "tipo_assinante": "3",
        "obs": obs
    }

    if usando_condominio:
        # ✅ Modo condomínio: o IXC valida CEP antes de fazer preenchimento automático.
        #    Enviar o endereço do próprio condomínio resolve a validação sem conflito.
        #    Campos do CLIENTE (bloco/apto) complementam o endereço do condomínio.
        payload["id_condominio"] = id_condominio_ixc
        # Endereço vem do condomínio; fallback para o que o operador digitou
        payload["cep"]      = cond_cep      or cep
        payload["endereco"] = cond_endereco or endereco
        payload["numero"]   = cond_numero   or numero
        payload["bairro"]   = cond_bairro   or bairro
        payload["cidade"]   = id_cidade
        payload["uf"]       = id_uf
        if cond_complemento or complemento:
            payload["complemento"] = cond_complemento or complemento
        if bloco:
            payload["bloco"] = bloco
        if apartamento:
            payload["apartamento"] = apartamento
    else:
        # ✅ Modo endereço avulso: enviar todos os campos de endereço normalmente
        payload["cep"] = cep
        payload["endereco"] = endereco
        payload["numero"] = numero
        payload["complemento"] = complemento
        payload["bairro"] = bairro
        payload["cidade"] = id_cidade
        payload["uf"]     = id_uf
        if cliente_data.get("condominio_nome"):
            payload["referencia"] = f"Condomínio: {safe(cliente_data['condominio_nome'])}"

    # Remove campos vazios que o IXC rejeita
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
                return False, None, f"Resposta inválida: {response.text[:200]}")
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
