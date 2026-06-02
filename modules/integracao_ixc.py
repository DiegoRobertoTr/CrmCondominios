# modules/integracao_ixc.py - VERSÃO CORRIGIDA E OTIMIZADA (COM CAMPO OBRIGATÓRIO)
import requests
import base64
import json
import streamlit as st
from datetime import datetime
from typing import Dict, Optional, Tuple, Any
import urllib3
import re

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
            "tipo_cliente_scm": st.secrets["ixc"].get("tipo_cliente_scm", "01"),
            "iss_classificacao_padrao": st.secrets["ixc"].get("iss_classificacao_padrao", "99")
        }
        return config
    except Exception as e:
        st.error(f"❌ Erro ao carregar configuração do IXC: {e}")
        return None

def _sanitizar_host(host: str) -> str:
    """Remove protocolo, caminhos e barras para evitar URL duplicada."""
    host = re.sub(r'^https?://', '', host)
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
# FUNÇÃO PARA BUSCAR CLIENTE NO IXC POR CPF
# ============================================================================
def buscar_cliente_ixc_por_cpf(cpf: str, config: Dict) -> Optional[Dict]:
    """Busca um cliente no IXC pelo CPF e retorna os dados completos."""
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
            registros = None
            
            if "registros" in dados and dados["registros"]:
                registros = dados["registros"]
            elif "data" in dados and dados["data"]:
                registros = dados["data"]
            elif isinstance(dados, list) and dados:
                registros = dados
            
            if registros and len(registros) > 0:
                cliente = registros[0]
                return {
                    "id": str(cliente.get("id")),
                    "nome": cliente.get("razao"),
                    "cpf": cliente.get("cnpj_cpf"),
                    "email": cliente.get("email")
                }
        return None
    except Exception as e:
        print(f"Erro ao buscar cliente no IXC: {e}")
        return None

# ============================================================================
# CONSTRUÇÃO DO PAYLOAD PARA IXC (COM TODOS OS CAMPOS OBRIGATÓRIOS)
# ============================================================================
def construir_payload_ixc(cliente_data: Dict, config: Dict) -> Tuple[Dict, Optional[str]]:
    """Constrói payload seguro para IXC, validando apenas campos essenciais."""
    
    def safe(val: Any) -> str:
        return str(val).strip() if val is not None else ""

    # Limpeza de campos numéricos
    cpf = "".join(filter(str.isdigit, safe(cliente_data.get("cpf"))))
    celular = "".join(filter(str.isdigit, safe(cliente_data.get("celular"))))
    telefone_com = "".join(filter(str.isdigit, safe(cliente_data.get("telefone_comercial"))))
    cep = "".join(filter(str.isdigit, safe(cliente_data.get("cep"))))
    rg = safe(cliente_data.get("rg"))
    
    # Validação do CPF
    if not validar_cpf(cpf):
        return {}, f"CPF inválido: '{cliente_data.get('cpf')}'. Use um CPF válido (ex: 07099562017)."

    # Validação do CEP (opcional, mas se informado deve ter 8 dígitos)
    if cep and len(cep) != 8:
        return {}, f"CEP inválido: '{cliente_data.get('cep')}'. O CEP deve conter 8 dígitos."

    # Campos obrigatórios
    nome = safe(cliente_data.get("nome_completo"))
    email = safe(cliente_data.get("email"))
    endereco = safe(cliente_data.get("endereco"))
    numero = safe(cliente_data.get("numero"))
    bairro = safe(cliente_data.get("bairro"))
    cidade = safe(cliente_data.get("cidade")) or "Rio de Janeiro"
    uf = safe(cliente_data.get("uf")).upper() or "RJ"
    
    if not all([nome, email, endereco, numero, bairro]):
        return {}, f"Campos obrigatórios faltando: nome, email, endereço, número e bairro são necessários."

    # Telefone (prioriza celular)
    fone = celular or telefone_com
    if not fone:
        return {}, "Telefone ou celular é obrigatório."

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

    # Payload completo com todos os campos obrigatórios
    payload = {
        "ativo": "S",
        "id_tipo_cliente": config.get("id_tipo_cliente", "03"),
        "tipo_cliente_scm": config.get("tipo_cliente_scm", "01"),
        "filial_id": config.get("filial_id", "1"),
        "filtra_filial": "S",
        "tipo_pessoa": "F",
        "razao": nome[:100],
        "nome_social": nome[:100],
        "fantasia": nome[:100],
        "cnpj_cpf": cpf,
        "email": email[:100],
        "fone": fone[:15],
        "telefone_celular": celular[:15] if celular else "",
        "whatsapp": celular[:15] if celular else "",
        "endereco": endereco[:100],
        "numero": numero[:10],
        "bairro": bairro[:50],
        "cidade": cidade[:50],
        "uf": uf[:2],
        "cep": cep[:8],
        "participa_cobranca": "S",
        "participa_pre_cobranca": "S",
        "cob_envia_email": "S",
        "cob_envia_sms": "S",
        "status_prospeccao": "C",
        "tipo_assinante": "3",
        "hotsite_acesso": "2",
        "hotsite_email": email[:100],
        "senha": "123456",
        "senha_hotsite_md5": "N",
        "acesso_automatico_central": "P",
        "alterar_senha_primeiro_acesso": "S",
        "iss_classificacao_padrao": config.get("iss_classificacao_padrao", "99"),  # ✅ Campo obrigatório
        "nacionalidade": "Brasileiro",
        "contribuinte_icms": "N",
        "tipo_localidade": "U"
    }
    
    # Adiciona campos opcionais apenas se tiverem valor
    if data_nasc_formatada:
        payload["data_nascimento"] = data_nasc_formatada
    
    if complemento := safe(cliente_data.get("complemento")):
        payload["complemento"] = complemento[:50]
    
    if rg:
        payload["ie_identidade"] = rg[:20]
    
    if bloco := safe(cliente_data.get("bloco")):
        payload["bloco"] = bloco[:10]
    
    if apartamento := safe(cliente_data.get("apartamento")):
        payload["apartamento"] = apartamento[:10]
    
    if obs := safe(cliente_data.get("observacoes")):
        payload["obs"] = obs[:500]
    
    # Tratamento de condomínio (se houver)
    if cliente_data.get("condominio_id"):
        try:
            from .condominios import get_condominio_by_id
            cond_data = get_condominio_by_id(cliente_data["condominio_id"])
            if cond_data and cond_data.get("id_ixc"):
                payload["id_condominio"] = str(cond_data["id_ixc"])
        except Exception as e:
            print(f"⚠️ Erro ao buscar condomínio: {e}")
    elif cliente_data.get("condominio_nome"):
        payload["referencia"] = f"Condomínio: {safe(cliente_data['condominio_nome'])}"
    
    # Remove campos vazios (mas mantém os que têm valor padrão)
    payload = {k: v for k, v in payload.items() if v not in (None, "", " ", [], {})}
    
    return payload, None

# ============================================================================
# FUNÇÃO PRINCIPAL: ENVIAR CLIENTE AO IXC
# ============================================================================
def enviar_cliente_para_ixc(cliente_data: Dict, mongo_collection=None) -> Tuple[bool, Optional[str], Optional[str]]:
    """
    Envia os dados do cliente para a API do IXC.
    
    Args:
        cliente_data: Dicionário com dados do cliente
        mongo_collection: Coleção do MongoDB para salvar o ID (opcional)
    
    Returns:
        (sucesso, id_ixc, mensagem_erro)
    """
    print("\n" + "=" * 70)
    print("🚀 INICIANDO INTEGRAÇÃO COM IXC")
    print("=" * 70)
    
    config = get_ixc_config()
    if not config:
        return False, None, "Configuração do IXC não encontrada."

    cpf = "".join(filter(str.isdigit, str(cliente_data.get("cpf", ""))))
    nome = cliente_data.get("nome_completo", "")
    print(f"📋 Cliente: {nome} | CPF: {cpf}")

    # Verificar se cliente já existe no IXC
    if cpf and len(cpf) >= 11:
        print(f"🔍 Verificando CPF {cpf} no IXC...")
        cliente_existente = buscar_cliente_ixc_por_cpf(cpf, config)
        if cliente_existente:
            id_ixc = cliente_existente["id"]
            print(f"✅ Cliente já existe no IXC! ID: {id_ixc}")
            
            # Salva o ID no MongoDB se fornecido
            if mongo_collection and cliente_data.get("_id"):
                mongo_collection.update_one(
                    {"_id": cliente_data["_id"]},
                    {"$set": {
                        "id_ixc": id_ixc,
                        "integrado_ixc": True,
                        "data_integracao_ixc": datetime.now()
                    }}
                )
            return True, id_ixc, None

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
        "ixcsoft": "inserir"
    }

    print(f"\n🌐 Enviando para: {url}")
    print(f"📦 Payload size: {len(json.dumps(payload))} bytes")
    
    try:
        response = requests.post(url, json=payload, headers=headers, timeout=30, verify=False)
        
        print(f"📥 Status: {response.status_code}")
        print(f"📄 Resposta: {response.text[:500]}")
        
        if response.status_code in [200, 201]:
            try:
                resposta_json = response.json()
                
                # Verifica erro na resposta (IXC pode retornar 200 com erro interno)
                if resposta_json.get("type") == "error" or resposta_json.get("success") is False:
                    erro = resposta_json.get("message") or resposta_json.get("error") or "Erro desconhecido"
                    print(f"❌ API retornou erro: {erro}")
                    return False, None, f"API retornou erro: {erro}"
                
                # Extrai ID da resposta
                id_ixc = None
                for campo in ["id", "cliente_id", "registro_id", "ID"]:
                    if campo in resposta_json:
                        id_ixc = str(resposta_json[campo])
                        break
                
                if not id_ixc and isinstance(resposta_json, dict):
                    # Tenta encontrar qualquer campo que pareça um ID
                    for k, v in resposta_json.items():
                        if "id" in k.lower() and v:
                            id_ixc = str(v)
                            break
                
                print(f"✅ Cliente integrado com sucesso! ID: {id_ixc or 'não retornado'}")
                
                # Salva o ID no MongoDB se fornecido
                if mongo_collection and cliente_data.get("_id") and id_ixc:
                    mongo_collection.update_one(
                        {"_id": cliente_data["_id"]},
                        {"$set": {
                            "id_ixc": id_ixc,
                            "integrado_ixc": True,
                            "data_integracao_ixc": datetime.now(),
                            "dados_enviados_ixc": payload
                        }}
                    )
                    print(f"💾 ID {id_ixc} salvo no MongoDB")
                
                return True, id_ixc if id_ixc else "ok", None
                
            except json.JSONDecodeError:
                # Se a resposta não for JSON mas indicar sucesso
                if "sucesso" in response.text.lower() or "success" in response.text.lower():
                    return True, "ok", None
                return False, None, f"Resposta inválida (não é JSON): {response.text[:200]}"
        else:
            return False, None, f"HTTP {response.status_code}: {response.text[:250]}"

    except requests.exceptions.Timeout:
        return False, None, "Timeout: IXC não respondeu em 30 segundos"
    except requests.exceptions.ConnectionError as e:
        return False, None, f"Erro de conexão: Verifique se o host {host_limpo} está acessível. Detalhe: {str(e)[:100]}"
    except Exception as e:
        return False, None, str(e)

# ============================================================================
# FUNÇÃO PARA REGISTRAR PENDÊNCIA
# ============================================================================
def registrar_pendencia_integracao(cliente_id, cliente_data, erro_msg, mongo_collection=None):
    """Registra pendência de integração para sincronização posterior."""
    try:
        if mongo_collection is None:
            # Tenta obter do session_state apenas se disponível
            if hasattr(st, 'session_state') and 'clientes_collection' in st.session_state:
                mongo_collection = st.session_state.clientes_collection
            else:
                print("⚠️ Sem acesso ao MongoDB, pendência não registrada")
                return
        
        mongo_collection.update_one(
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
    """Renderiza um painel de teste de conexão com o IXC."""
    st.subheader("🔌 Teste de Conexão com IXCsoft")
    
    if st.button("🧪 Testar Conexão"):
        with st.spinner("Testando conexão..."):
            config = get_ixc_config()
            if not config:
                st.error("❌ Configuração não encontrada. Verifique os secrets.")
                return
            
            host_limpo = _sanitizar_host(config["host"])
            url = f"https://{host_limpo}/webservice/v1/cliente"
            
            try:
                auth_string = base64.b64encode(config["token"].encode('utf-8')).decode('utf-8')
                payload = {"qtype": "cliente.id", "query": "1", "oper": ">", "page": "1", "rp": "1"}
                headers = {
                    "Content-Type": "application/json",
                    "Authorization": f"Basic {auth_string}",
                    "ixcsoft": "listar"
                }
                
                response = requests.post(url, json=payload, headers=headers, timeout=10, verify=False)
                
                st.write("### Resultado do Teste:")
                
                if response.status_code in [200, 201]:
                    st.success(f"✅ Conexão com IXC funcionando corretamente! (Status: {response.status_code})")
                    
                    try:
                        dados = response.json()
                        st.json({
                            "status": response.status_code,
                            "host": host_limpo,
                            "total_registros": len(dados.get("registros", [])) if "registros" in dados else "N/A"
                        })
                    except:
                        st.json({
                            "status": response.status_code,
                            "host": host_limpo,
                            "resposta_bruta": response.text[:300]
                        })
                else:
                    st.error(f"❌ Falha na conexão: HTTP {response.status_code}")
                    st.code(response.text[:500])
                    
                    st.info("""
                    **Possíveis causas:**
                    1. Host incorreto ou inacessível
                    2. Token inválido ou expirado
                    3. Firewall bloqueando a conexão
                    4. WebService do IXC não está ativo
                    5. Certificado SSL não confiável (usando verify=False)
                    
                    **Soluções:**
                    - Verifique se o host é acessível publicamente
                    - Confirme o token no painel do IXC (Módulo API)
                    - Teste a URL manualmente no navegador
                    - Verifique se o IP do Streamlit Cloud está liberado no IXC
                    """)
            except requests.exceptions.Timeout:
                st.error("❌ Timeout: O IXC não respondeu em 10 segundos")
                st.info("Verifique se o host está correto e se o serviço está ativo.")
            except requests.exceptions.ConnectionError as e:
                st.error(f"❌ Erro de conexão: {str(e)[:150]}")
                st.info(f"Host testado: {host_limpo}\n\nVerifique se este host está acessível pela internet.")
            except Exception as e:
                st.error(f"❌ Erro inesperado: {str(e)}")

# ============================================================================
# FUNÇÃO PARA REPROCESSAR PENDÊNCIAS
# ============================================================================
def reprocessar_pendencias_integracao(mongo_collection, limit=50):
    """Reprocessa clientes com pendência de integração."""
    try:
        pendencias = list(mongo_collection.find({
            "integrado_ixc": False,
            "erro_integracao_ixc": {"$exists": True}
        }).limit(limit))
        
        if not pendencias:
            return {"sucesso": True, "processados": 0, "mensagem": "Nenhuma pendência encontrada"}
        
        resultados = {
            "total": len(pendencias),
            "sucessos": 0,
            "falhas": 0,
            "detalhes": []
        }
        
        for cliente in pendencias:
            dados_pendentes = cliente.get("dados_pendentes_integracao", {})
            if not dados_pendentes:
                dados_pendentes = {k: v for k, v in cliente.items() if k not in ["_id", "integrado_ixc", "erro_integracao_ixc"]}
            
            sucesso, id_ixc, erro = enviar_cliente_para_ixc(dados_pendentes, mongo_collection)
            
            if sucesso:
                resultados["sucessos"] += 1
                resultados["detalhes"].append({
                    "cliente_id": str(cliente["_id"]),
                    "nome": cliente.get("nome_completo", "N/A"),
                    "status": "sucesso",
                    "id_ixc": id_ixc
                })
            else:
                resultados["falhas"] += 1
                resultados["detalhes"].append({
                    "cliente_id": str(cliente["_id"]),
                    "nome": cliente.get("nome_completo", "N/A"),
                    "status": "falha",
                    "erro": erro
                })
                
                # Atualiza contagem de tentativas
                mongo_collection.update_one(
                    {"_id": cliente["_id"]},
                    {"$inc": {"tentativas_integracao": 1}}
                )
        
        return resultados
        
    except Exception as e:
        return {"sucesso": False, "erro": str(e)}
