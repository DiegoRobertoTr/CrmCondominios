# modules/permissoes.py
"""
Configuração central de permissões por perfil
✅ Inclui módulo de Pendências e Marketing Condomínios para perfis internos
"""

PERMISSOES_POR_PERFIL = {
    # --- Equipe Interna ---
    "admin": [
        "Cadastro", "Follow-up", "Agendamentos", "Pendências",
        "Roteiro de Vendas",
        "Admin Embaixadores", "Admin Técnicos", "Admin PaP", "Admin Revendas",
        "Admin Funcionários", "Acompanhamento Técnicos", "Relatórios",
        "HotSpots WiFi", "Satisfação", "Monitoramento de E-mails",
        "Teste de Integração", "Endereços Bloqueados",
        "Condomínios", "Relatórios Condomínios", "Prospecção Condomínios",
        "Marketing Condomínios",
        "Leads & Eventos"
    ],
    "recepcao": [
        "Cadastro", "Follow-up", "Agendamentos", "Pendências",
        "Roteiro de Vendas",
        "HotSpots WiFi", "Satisfação", "Endereços Bloqueados",
        "Leads & Eventos"
    ],
    "atendente_n1": [
        "Cadastro", "Follow-up", "Agendamentos", "Pendências",
        "Roteiro de Vendas",
        "HotSpots WiFi", "Satisfação", "Endereços Bloqueados",
        "Leads & Eventos"
    ],
    "supervisao_n1": [
        "Cadastro", "Follow-up", "Agendamentos", "Pendências",
        "Roteiro de Vendas",
        "Marketing Condomínios",
        "Leads & Eventos"
    ],
    "supervisao_n2": [
        "Cadastro", "Follow-up", "Agendamentos", "Pendências",
        "Roteiro de Vendas",
        "Admin Embaixadores", "Admin PaP", "Admin Revendas",
        "Marketing Condomínios",
        "Leads & Eventos"
    ],
    "supervisao_n3": [
        "Cadastro", "Follow-up", "Agendamentos", "Pendências",
        "Roteiro de Vendas",
        "Admin Embaixadores", "Admin PaP", "Admin Revendas",
        "Relatórios", "Relatórios Condomínios", "Prospecção Condomínios",
        "Marketing Condomínios",
        "Leads & Eventos"
    ],
    # --- DIRETORIA ---
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

def get_perfis_pendencias():
    """
    ✅ Retorna perfis que podem criar/receber pendências
    (Todos os internos, exceto diretoria)
    """
    return [
        "admin", "recepcao", "atendente_n1",
        "supervisao_n1", "supervisao_n2", "supervisao_n3"
    ]

def get_perfis_marketing():
    """
    ✅ Retorna perfis que podem editar marketing dos condomínios
    """
    return [
        "admin", "supervisao_n1", "supervisao_n2", "supervisao_n3"
    ]
