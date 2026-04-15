"""
Configuração central de permissões por perfil
"""
PERMISSOES_POR_PERFIL = {
    # --- Equipe Interna ---
    "admin": [
        "Cadastro", "Follow-up", "Agendamentos", "Roteiro de Vendas",
        "Admin Embaixadores", "Admin Técnicos", "Admin PaP", "Admin Revendas",
        "Admin Funcionários", "Acompanhamento Técnicos", "Relatórios",
        "Endereços Bloqueados", "Condomínios", "Relatórios Condomínios", "Prospecção Condomínios",
        "Leads & Eventos"  # ✅ NOVO
    ],
    "recepcao": [
        "Cadastro", "Follow-up", "Agendamentos", "Roteiro de Vendas",
        "Endereços Bloqueados", "Leads & Eventos"  # ✅ NOVO
    ],
    "atendente_n1": [
        "Cadastro", "Follow-up", "Agendamentos", "Roteiro de Vendas",
        "Endereços Bloqueados", "Leads & Eventos"  # ✅ NOVO
    ],
    "supervisao_n1": [
        "Cadastro", "Follow-up", "Agendamentos", "Roteiro de Vendas", "Leads & Eventos"  # ✅ NOVO
    ],
    "supervisao_n2": [
        "Cadastro", "Follow-up", "Agendamentos", "Roteiro de Vendas",
        "Admin Embaixadores", "Admin PaP", "Admin Revendas", "Leads & Eventos"  # ✅ NOVO
    ],
    "supervisao_n3": [
        "Cadastro", "Follow-up", "Agendamentos", "Roteiro de Vendas",
        "Admin Embaixadores", "Admin PaP", "Admin Revendas",
        "Relatórios", "Relatórios Condomínios", "Prospecção Condomínios", "Leads & Eventos"  # ✅ NOVO
    ],
    # --- NOVO PERFIL: DIRETORIA ---
    "diretoria": [
        "Relatórios Condomínios",
        "Prospecção Condomínios"
    ],
    # --- Parceiros Externos ---
    "embaixador": ["Painel Embaixador"],
    "tecnico": ["Painel Técnico"],
    "pap": ["Cadastro Porta a Porta"],
    "revenda": ["Painel Revenda"]
}

def get_modulos_permitidos(perfil):
    """Retorna lista de módulos que o perfil pode acessar"""
    return PERMISSOES_POR_PERFIL.get(perfil, [])

def pode_acessar_modulo(perfil, modulo):
    """Verifica se perfil tem acesso ao módulo"""
    return modulo in get_modulos_permitidos(perfil)

def get_perfis_internos():
    """Retorna perfis que são funcionários internos (para cadastro)"""
    return [
        "admin", "recepcao", "atendente_n1",
        "supervisao_n1", "supervisao_n2", "supervisao_n3",
        "diretoria"
    ]
