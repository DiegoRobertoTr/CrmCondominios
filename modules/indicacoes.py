# modulos/indicacoes.py
import secrets
from datetime import datetime

def gerar_codigo_indicacao(prefixo="CLI", tamanho=6):
    """Gera um código único de indicação (ex: CLI-AB3X9)."""
    token = secrets.token_urlsafe(tamanho).replace('_', '').replace('-', '').upper()
    return f"{prefixo}-{token[:tamanho]}"

def validar_codigo_indicacao(codigo, clientes_collection):
    """
    Valida se um código de indicação existe em algum cliente convertido.
    Retorna o cliente indicador ou None.
    """
    if not codigo or not isinstance(codigo, str):
        return None
    return clientes_collection.find_one({
        "codigo_indicacao": codigo,
        "seguiu_ativacao": "Sim"
    })

def registrar_indicacao(indicado_id, codigo_indicador, clientes_collection):
    """
    Registra a indicação no cliente indicado (após validação).
    """
    if not codigo_indicador:
        return False
    indicador = validar_codigo_indicacao(codigo_indicador, clientes_collection)
    if indicador:
        clientes_collection.update_one(
            {"_id": indicado_id},
            {"$set": {
                "indicado_por": codigo_indicador,
                "origem": "Indicação"
            }}
        )
        return True
    return False
