# modules/integracao_ixc.py - VERSÃO COMPLETA ATUALIZADA
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
        print(f"❌ Erro detalhado: {e}")
        return None

def _sanitizar_host(host: str) -> str:
    """Remove protocolo, caminhos e barras."""
    host = host.replace("https://", "").replace("http://", "")
    return host.split("/")[0].strip().rstrip("/")

# ============================================================================
# VALIDAÇÃO DE CPF
# ============================================================================
def validar_cpf(cpf: str) -> bool:
    """Valida CPF algorítmico (apenas dígitos)."""
    cpf = "".join(filter(str.isdigit, cpf))
    if len(cpf) != 11 or cpf == cpf[0] * 11:
        return False
    
    soma1 = sum(int(cpf[i]) * (10 - i) for i in range(9))
    digito1 = 0 if (soma1 * 10) % 11 >= 10 else (soma1 * 10) % 11
    if int(cpf[9]) != digito1:
        return False
        
    soma2 = sum(int(cpf[i]) * (11 - i) for i in range(10))
    digito2 = 0 if (soma2 * 10) % 11 >= 10 else (soma2 * 10) % 11
    return int(cpf[10]) == digito2

# ============================================================================
# FUNÇÃO PARA TESTAR CONEXÃO
# ============================================================================
def testar_conexao_ixc() -> Dict:
    """Testa a conexão com a API do IXC."""
    config = get_ixc_config()
    if not config:
        return {"sucesso": False, "erro": "Configuração não encontrada"}
    
    resultados = {"sucesso": False, "testes": [], "erro": None}
    host_limpo = _sanitizar_host(config["host"])
    
    try:
        url = f"https://{host_limpo}/webservice/v1/cliente"
        auth_string = base64.b64encode(config["token"].encode('utf-8')).decode('utf-8')
        payload = {"qtype": "cliente.id", "query": "1", "oper": ">", "page": "1", "rp": "1"}
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Basic {auth_string}",
            "ixcsoft": "listar"
        }
        
        response = requests.post(url, json=payload, headers=headers, timeout=10, verify=False)
        
        if response.status_code in [200, 201]:
            resultados["sucesso"] = True
            resultados["testes"].append({"nome": "Conexão", "sucesso": True, "detalhe": "API respondeu com sucesso"})
        else:
            resultados["erro"] = f"HTTP {response.status_code}"
            resultados["testes"].append({"nome": "Conexão", "sucesso": False, "detalhe": response.text[:200]})
            
    except Exception as e:
        resultados["erro"] = str(e)
        resultados["testes"].append({"nome": "Conexão", "sucesso": False, "detalhe": str(e)[:200]})

    return resultados

# ============================================================================
# FUNÇÃO PARA BUSCAR CONDÔMINIO NO IXC (OPCIONAL)
# ============================================================================
def buscar_condominio_ixc_por_nome(nome_condominio: str, config: Dict) -> Optional[str]:
    """Busca um condomínio no IXC pelo nome e retorna o ID."""
    if not nome_condominio:
        return None
        
    host_limpo = _sanitizar_host(config["host"])
    url = f"https://{host_limpo}/webservice/v1/condominio"
    auth_string = base64.b64encode(config["token"].encode('utf-8')).decode('utf-8')

    payload = {"qtype": "condominio.nome", "query": nome_condominio, "oper": "=", "page": "1", "rp": "5"}
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Basic {auth_string}",
        "ixcsoft": "listar"
    }

    try:
        response = requests.post(url, json=payload, headers=headers, timeout=15, verify=False)
        if response.status_code == 200:
            dados = response.json()
            registros = dados.get("registros", []) or dados.get("data", [])
            if registros:
                return str(registros[0].get("id"))
        return None
    except Exception as e:
        print(f"⚠️ Erro ao buscar condomínio no IXC: {e}")
        return None

# ============================================================================
# CONSTRUÇÃO DO PAYLOAD (VERSÃO CORRIGIDA)
# ============================================================================
def construir_payload_ixc(cliente_data: Dict, config: Dict) -> Tuple[Dict, Optional[str]]:
    """Constrói payload seguro para IXC - SEM campos de endereço quando tem condomínio."""
    
    def safe(val: any) -> str:
        return str(val).strip() if val is not None else ""

    # 1. Sanitização dos campos
    cpf_raw = safe(cliente_data.get("cpf"))
    cpf = "".join(filter(str.isdigit, cpf_raw))
    
    rg = safe(cliente_data.get("rg"))
    
    celular_raw = safe(cliente_data.get("celular"))
    celular = "".join(filter(str.isdigit, celular_raw))
    
    telefone_com_raw = safe(cliente_data.get("telefone_comercial"))
    telefone_com = "".join(filter(str.isdigit, telefone_com_raw))
    fone = celular or telefone_com

    # 2. Validação do CPF
    if not validar_cpf(cpf):
        return {}, f"CPF inválido: '{cpf_raw}'. Use um CPF válido (apenas números)."

    # 3. Dados básicos do cliente
    nome_completo = safe(cliente_data.get("nome_completo"))
    email = safe(cliente_data.get("email"))
    bloco = safe(cliente_data.get("bloco"))
    apartamento = safe(cliente_data.get("apartamento"))
    obs = safe(cliente_data.get("observacoes"))[:500]
    
    # Validação de nome e email
    if not nome_completo:
        return {}, "Nome completo é obrigatório"
    if not email:
        return {}, "Email é obrigatório"

    # 4. Data de nascimento
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

    # 5. ⭐ OBTENÇÃO DO ID DO CONDÔMINIO (parte mais importante)
    id_condominio_ixc = None
    
    # Tenta obter de diferentes formas:
    # Forma 1: Direto pelo campo 'id_condominio_ixc' (se já tiver o ID)
    if cliente_data.get("id_condominio_ixc"):
        id_condominio_ixc = str(cliente_data["id_condominio_ixc"])
        print(f"✅ Usando ID do condomínio diretamente: {id_condominio_ixc}")
    
    # Forma 2: Pelo campo 'condominio_id' (buscando no seu banco local)
    elif cliente_data.get("condominio_id"):
        try:
            # Função que você precisa ter implementada para buscar o condomínio no seu banco
            # Exemplo de como deve ser:
            from .condominios import get_condominio_by_id
            cond_data = get_condominio_by_id(cliente_data["condominio_id"])
            if cond_data and cond_data.get("id_ixc"):
                id_condominio_ixc = str(cond_data["id_ixc"])
                print(f"✅ Condomínio encontrado no banco local: ID IXC={id_condominio_ixc}")
            else:
                print(f"⚠️ Condomínio ID {cliente_data['condominio_id']} não possui id_ixc cadastrado")
        except Exception as e:
            print(f"⚠️ Erro ao buscar condomínio no banco local: {e}")
    
    # Forma 3: Pelo nome do condomínio (busca automática no IXC)
    elif cliente_data.get("condominio_nome"):
        nome_cond = safe(cliente_data["condominio_nome"])
        id_condominio_ixc = buscar_condominio_ixc_por_nome(nome_cond, config)
        if id_condominio_ixc:
            print(f"✅ Condomínio encontrado pelo nome no IXC: {nome_cond} -> ID={id_condominio_ixc}")
        else:
            print(f"⚠️ Condomínio não encontrado no IXC: {nome_cond}")

    # 6. ⭐⭐ PAYLOAD CONDICIONAL (CRÍTICO: não enviar endereço se tem condomínio)
    
    # Dados comuns a ambos os casos
    payload_base = {
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
        "acesso_automatico_central": "P",
        "alterar_senha_primeiro_acesso": "S",
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
        "bloco": bloco,
        "apartamento": apartamento,
        "obs": obs
    }
    
    # ⭐ DECISÃO CRÍTICA: COM ou SEM condomínio?
    if id_condominio_ixc:
        # ✅ CASO 1: Tem condomínio - NÃO envia campos de endereço
        payload_base["id_condominio"] = id_condominio_ixc
        print(f"📦 Payload com condomínio (ID={id_condominio_ixc}) - campos de endereço NÃO serão enviados")
    else:
        # ✅ CASO 2: Sem condomínio - Precisa enviar todos os campos de endereço
        cep = "".join(filter(str.isdigit, safe(cliente_data.get("cep"))))
        endereco = safe(cliente_data.get("endereco"))
        numero = safe(cliente_data.get("numero"))
        bairro = safe(cliente_data.get("bairro"))
        cidade = safe(cliente_data.get("cidade")) or "Rio de Janeiro"
        uf = (safe(cliente_data.get("uf")) or "RJ").upper()
        
        # Validações de endereço (só são obrigatórias quando NÃO tem condomínio)
        if not endereco:
            return {}, "Endereço é obrigatório quando não há condomínio vinculado"
        if not numero:
            return {}, "Número é obrigatório quando não há condomínio vinculado"
        if not bairro:
            return {}, "Bairro é obrigatório quando não há condomínio vinculado"
        if cep and len(cep) != 8:
            return {}, f"CEP inválido: deve conter 8 dígitos"
        
        # Adiciona campos de endereço ao payload
        payload_base.update({
            "endereco": endereco,
            "numero": numero,
            "bairro": bairro,
            "cidade": cidade,
            "uf": uf,
            "cep": cep,
            "tipo_localidade": "U"
        })
        print(f"📦 Payload sem condomínio - enviando endereço completo")

    # Remove campos vazios e retorna
    payload_final = {k: v for k, v in payload_base.items() if v not in (None, "", " ", [], {})}
    
    # Log para depuração
    print(f"📋 Campos no payload final: {list(payload_final.keys())}")
    
    return payload_final, None

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
        response = requests.post(url, json=payload, headers=headers, timeout=15, verify=False)
        if response.status_code == 200:
            dados = response.json()
            registros = dados.get("registros", []) or dados.get("data", [])
            if registros:
                return str(registros[0].get("id"))
        return None
    except Exception as e:
        print(f"⚠️ Erro ao buscar cliente: {e}")
        return None

# ============================================================================
# FUNÇÃO PRINCIPAL: ENVIAR CLIENTE AO IXC
# ============================================================================
def enviar_cliente_para_ixc(cliente_data: Dict) -> Tuple[bool, Optional[str], Optional[str]]:
    """Envia os dados do cliente para a API do IXC."""
    print("\n" + "=" * 70)
    print("🚀 INICIANDO INTEGRAÇÃO COM IXC")
    print("=" * 70)
    
    config = get_ixc_config()
    if not config:
        return False, None, "Configuração do IXC não encontrada."

    cpf = "".join(filter(str.isdigit, str(cliente_data.get("cpf", ""))))
    nome = cliente_data.get("nome_completo", "")
    print(f"📋 Cliente: {nome} | CPF: {cpf}")

    # Verificar se cliente já existe
    if cpf and len(cpf) >= 11:
        print(f"🔍 Verificando se CPF já existe no IXC...")
        id_existente = buscar_cliente_ixc_por_cpf(cpf, config)
        if id_existente:
            print(f"✅ Cliente já existe com ID: {id_existente}")
            return True, id_existente, None

    # Construir payload
    payload, erro_validacao = construir_payload_ixc(cliente_data, config)
    if erro_validacao:
        print(f"❌ Erro de validação: {erro_validacao}")
        return False, None, erro_validacao

    # Preparar requisição
    host_limpo = _sanitizar_host(config["host"])
    url = f"https://{host_limpo}/webservice/v1/cliente"
    auth_string = base64.b64encode(config["token"].encode('utf-8')).decode('utf-8')

    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Basic {auth_string}",
        "ixcsoft": "inserir"
    }

    print(f"\n🌐 URL: {url}")
    print(f"📦 Payload enviado: {json.dumps(payload, indent=2, ensure_ascii=False)}")
    
    try:
        response = requests.post(url, json=payload, headers=headers, timeout=30, verify=False)
        
        print(f"\n📥 RESPOSTA: Status={response.status_code}")
        print(f"   Texto: {response.text[:500]}")
        
        if response.status_code in [200, 201]:
            try:
                resposta_json = response.json()
                
                # Verifica se a API retornou erro
                if resposta_json.get("type") == "error" or resposta_json.get("success") is False:
                    erro_msg = resposta_json.get("message") or resposta_json.get("error") or "Erro desconhecido"
                    print(f"❌ API retornou erro: {erro_msg}")
                    return False, None, f"Erro na API: {erro_msg}"
                
                # Sucesso!
                id_ixc = resposta_json.get("id") or resposta_json.get("cliente_id") or resposta_json.get("registro_id")
                print(f"✅ Cliente integrado com sucesso! ID: {id_ixc or 'ok'}")
                return True, str(id_ixc) if id_ixc else "ok", None
                
            except ValueError:
                if "sucesso" in response.text.lower() or "success" in response.text.lower():
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
# FUNÇÃO PARA TESTE NO PAINEL ADMIN
# ============================================================================
def render_teste_conexao():
    """Renderiza painel de teste de conexão."""
    st.subheader("🔌 Teste de Conexão com IXCsoft")
    if st.button("🧪 Testar Conexão"):
        with st.spinner("Testando..."):
            resultado = testar_conexao_ixc()
            
            if resultado["sucesso"]:
                st.success("✅ Conexão com IXC funcionando!")
            else:
                st.error(f"❌ Falha: {resultado['erro']}")
                st.info("""
                **Verifique:**
                1. Host do IXC está acessível?
                2. Token está válido?
                3. Firewall liberado?
                """)
