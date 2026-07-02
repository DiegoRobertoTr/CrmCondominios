# modules/permissoes.py
"""
Configuração central de permissões por perfil
✅ Inclui módulo de Pendências e Marketing Condomínios para perfis internos
✅ Inclui módulo de Visitas Vendedoras
✅ Inclui módulo de Informações Condomínios
✅ Inclui módulo de Vendas por Vendedor - Condomínios
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
        "Condomínios",  # Cadastro base e importação IXC
        "Informações Condomínios",  # Dashboard, importação e edição de informações detalhadas
        "Relatórios Condomínios", "Prospecção Condomínios",
        "Marketing Condomínios",
        "Leads & Eventos",
        "Visitas Vendedoras",
        "Vendas por Vendedor - Condomínios"  # <-- NOVO
    ],
    
    "recepcao": [
        "Cadastro", "Follow-up", "Agendamentos", "Pendências",
        "Roteiro de Vendas",
        "HotSpots WiFi", "Satisfação", "Endereços Bloqueados",
        "Leads & Eventos",
        "Visitas Vendedoras"
    ],
    
    "atendente_n1": [
        "Cadastro", "Follow-up", "Agendamentos", "Pendências",
        "Roteiro de Vendas",
        "HotSpots WiFi", "Satisfação", "Endereços Bloqueados",
        "Leads & Eventos",
        "Visitas Vendedoras"
    ],
    
    "supervisao_n1": [
        "Cadastro", "Follow-up", "Agendamentos", "Pendências",
        "Roteiro de Vendas",
        "Marketing Condomínios",
        "Leads & Eventos",
        "Visitas Vendedoras"
    ],
    
    "supervisao_n2": [
        "Cadastro", "Follow-up", "Agendamentos", "Pendências",
        "Roteiro de Vendas",
        "Admin Embaixadores", "Admin PaP", "Admin Revendas",
        "Marketing Condomínios",
        "Leads & Eventos",
        "Visitas Vendedoras"
    ],
    
    "supervisao_n3": [
        "Cadastro", "Follow-up", "Agendamentos", "Pendências",
        "Roteiro de Vendas",
        "Admin Embaixadores", "Admin PaP", "Admin Revendas",
        "Relatórios", "Relatórios Condomínios", "Prospecção Condomínios",
        "Marketing Condomínios",
        "Leads & Eventos",
        "Visitas Vendedoras"
    ],
    
    # --- DIRETORIA ---
    "diretoria": [
        "Relatórios Condomínios", 
        "Prospecção Condomínios",
        "Visitas Vendedoras",
        "Vendas por Vendedor - Condomínios"  # <-- NOVO
    ],
    
    # --- Parceiros Externos ---
    "embaixador": ["Painel Embaixador"],
    "tecnico": ["Painel Técnico"],
    "pap": ["Cadastro Porta a Porta"],
    "revenda": ["Painel Revenda"],
    
    # --- NOVO PERFIL: Vendedora ---
    "vendedora": ["Visitas Vendedoras"]
}

def get_modulos_permitidos(perfil):
    """
    Retorna lista de módulos que o perfil pode acessar
    
    Args:
        perfil (str): Nome do perfil do usuário
        
    Returns:
        list: Lista de módulos permitidos para o perfil
    """
    return PERMISSOES_POR_PERFIL.get(perfil, [])

def pode_acessar_modulo(perfil, modulo):
    """
    Verifica se perfil tem acesso ao módulo específico
    
    Args:
        perfil (str): Nome do perfil do usuário
        modulo (str): Nome do módulo a ser verificado
        
    Returns:
        bool: True se o perfil pode acessar o módulo, False caso contrário
    """
    return modulo in get_modulos_permitidos(perfil)

def get_perfis_internos():
    """
    Retorna perfis que são funcionários internos (para cadastro)
    
    Returns:
        list: Lista de perfis internos
    """
    return [
        "admin", "recepcao", "atendente_n1",
        "supervisao_n1", "supervisao_n2", "supervisao_n3",
        "diretoria"
    ]

def get_perfis_pendencias():
    """
    Retorna perfis que podem criar/receber pendências
    (Todos os internos, exceto diretoria)
    
    Returns:
        list: Lista de perfis que podem gerenciar pendências
    """
    return [
        "admin", "recepcao", "atendente_n1",
        "supervisao_n1", "supervisao_n2", "supervisao_n3"
    ]

def get_perfis_marketing():
    """
    Retorna perfis que podem editar marketing dos condomínios
    
    Returns:
        list: Lista de perfis com acesso ao marketing de condomínios
    """
    return [
        "admin", "supervisao_n1", "supervisao_n2", "supervisao_n3"
    ]

def get_perfis_informacoes_condominios():
    """
    Retorna perfis que podem gerenciar informações detalhadas dos condomínios
    
    Returns:
        list: Lista de perfis com acesso ao módulo
    """
    return ["admin"]  # Por enquanto, apenas admin

def get_perfis_vendas_vendedor_condominios():
    """
    Retorna perfis que podem acessar o módulo de Vendas por Vendedor - Condomínios
    
    Returns:
        list: Lista de perfis com acesso ao módulo
    """
    return ["admin", "diretoria"]

def get_perfis_visitas_vendedoras():
    """
    Retorna perfis que podem gerenciar visitas de vendedoras
    
    Returns:
        list: Lista de perfis com acesso ao módulo de visitas de vendedoras
    """
    return [
        "admin", "diretoria", "supervisao_n1", "supervisao_n2", "supervisao_n3",
        "recepcao", "atendente_n1", "vendedora"
    ]

def get_perfis_vendedoras():
    """
    Retorna perfis que são vendedoras (acesso restrito à sua própria agenda)
    
    Returns:
        list: Lista de perfis de vendedoras
    """
    return ["vendedora"]

def get_perfis_gestao_visitas():
    """
    Retorna perfis que podem gerenciar todas as visitas (admin/diretoria/supervisão)
    
    Returns:
        list: Lista de perfis com gestão completa do módulo
    """
    return [
        "admin", "diretoria", "supervisao_n1", "supervisao_n2", "supervisao_n3"
    ]

def get_perfis_visualizacao_visitas():
    """
    Retorna perfis que podem visualizar visitas mas sem poder editar agendamentos
    
    Returns:
        list: Lista de perfis com acesso apenas visual
    """
    return ["recepcao", "atendente_n1"]

# --- Função auxiliar para validar permissões ---
def validar_permissao_visitas_vendedoras(perfil_usuario, nome_usuario=None, vendedora_visita=None):
    """
    Valida permissão específica para o módulo de visitas de vendedoras
    
    Args:
        perfil_usuario (str): Perfil do usuário logado
        nome_usuario (str, optional): Nome do usuário logado
        vendedora_visita (str, optional): Nome da vendedora da visita
        
    Returns:
        tuple: (pode_visualizar, pode_editar, pode_gerenciar)
            - pode_visualizar: pode ver as informações
            - pode_editar: pode editar/criar/cancelar visitas
            - pode_gerenciar: pode gerenciar vendedoras e condomínios
    """
    if perfil_usuario == "admin":
        return True, True, True
    elif perfil_usuario in get_perfis_gestao_visitas():
        return True, True, True
    elif perfil_usuario in get_perfis_visualizacao_visitas():
        return True, False, False
    elif perfil_usuario == "vendedora":
        # Vendedora só vê e edita suas próprias visitas
        pode_editar = (nome_usuario == vendedora_visita)
        return True, pode_editar, False
    else:
        return False, False, False
