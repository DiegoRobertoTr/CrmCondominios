# modules/roteiro_vendas.py
import streamlit as st
from datetime import datetime

def render_roteiro_vendas(clientes_collection):
    """Módulo de roteiro de vendas com checklist interativo e textos prontos"""
    
    st.title("🧭 Roteiro de Vendas - WhatsApp")
    st.caption("Guia passo a passo para atendimento eficaz")

    # Criar as 6 abas (adicionada Anti-Fraude)
    tab_checklist, tab_planos, tab_confirmacao, tab_antifraude, tab_orientacoes, tab_recusa = st.tabs([
        "✅ Checklist de Abordagem", 
        "💰 Planos", 
        "📝 Confirmação de Venda",
        "🛡️ Anti-Fraude",
        "📋 Orientações Iniciais",
        "❌ Recusa"
    ])

    # ==================== ABA 1: CHECKLIST DE ABORDAGEM ====================
    with tab_checklist:
        st.header("CHECKLIST – ABORDAGEM DE VENDAS WHATSAPP")
        
        # Inicializar estados dos checkboxes se não existirem
        if "checklist_abertura" not in st.session_state:
            st.session_state.checklist_abertura = {"cumprimento": False, "intencao": False, "nome": False}
        if "checklist_diagnostico" not in st.session_state:
            st.session_state.checklist_diagnostico = {"pessoas": False, "trabalho": False}
        if "checklist_recomendacao" not in st.session_state:
            st.session_state.checklist_recomendacao = {"plano_unico": False}
        if "checklist_valor" not in st.session_state:
            st.session_state.checklist_valor = {"valor_diferencial": False}
        if "checklist_fechamento" not in st.session_state:
            st.session_state.checklist_fechamento = {"pergunta_direcionada": False}
        if "checklist_objecao" not in st.session_state:
            st.session_state.checklist_objecao = {"preparado": False}
        if "checklist_regra_ouro" not in st.session_state:
            st.session_state.checklist_regra_ouro = {"pergunta_ou_passo": False}

        # 1) ABERTURA
        with st.container(border=True):
            st.subheader("1️⃣ ABERTURA")
            col1, col2 = st.columns([3, 1])
            with col1:
                st.markdown("""
                • Cumprimente de forma humana: *"Olá, bom dia! Tudo bem?"*  
                • Valide a intenção: *"Você deseja contratar internet para sua residência?"*  
                • Confirme o nome (se necessário): *"Como posso te chamar?"*
                """)
            with col2:
                st.session_state.checklist_abertura["cumprimento"] = st.checkbox("Cumprimento", value=st.session_state.checklist_abertura["cumprimento"], key="abert_cump")
                st.session_state.checklist_abertura["intencao"] = st.checkbox("Validou intenção", value=st.session_state.checklist_abertura["intencao"], key="abert_int")
                st.session_state.checklist_abertura["nome"] = st.checkbox("Confirmou nome", value=st.session_state.checklist_abertura["nome"], key="abert_nome")

        # 2) MICRO-DIAGNÓSTICO
        with st.container(border=True):
            st.subheader("2️⃣ MICRO-DIAGNÓSTICO (máx. 2 perguntas)")
            col1, col2 = st.columns([3, 1])
            with col1:
                st.markdown("""
                • *"Quantas pessoas usam a internet aí na casa?"*  
                • *"Alguém trabalha ou estuda online?"*
                """)
            with col2:
                st.session_state.checklist_diagnostico["pessoas"] = st.checkbox("Qtd pessoas", value=st.session_state.checklist_diagnostico["pessoas"], key="diag_pess")
                st.session_state.checklist_diagnostico["trabalho"] = st.checkbox("Trabalho/estudo", value=st.session_state.checklist_diagnostico["trabalho"], key="diag_trab")

        # 3) RECOMENDAÇÃO
        with st.container(border=True):
            st.subheader("3️⃣ RECOMENDAÇÃO (NUNCA LISTA)")
            col1, col2 = st.columns([3, 1])
            with col1:
                st.markdown("""
                Indique apenas **UM** plano.  
                *Ex: "Pelo seu perfil, o plano de 600MB atende perfeitamente, inclusive para streaming e redes sociais."*
                """)
            with col2:
                st.session_state.checklist_recomendacao["plano_unico"] = st.checkbox("Indicou 1 plano", value=st.session_state.checklist_recomendacao["plano_unico"], key="rec_plano")

        # 4) VALOR + BENEFÍCIO
        with st.container(border=True):
            st.subheader("4️⃣ VALOR + BENEFÍCIO")
            col1, col2 = st.columns([3, 1])
            with col1:
                st.markdown("""
                Informe o valor + 1 diferencial.  
                *Ex: "Está R$109,99 e o suporte é aqui da cidade mesmo, com atendimento rápido."*
                """)
            with col2:
                st.session_state.checklist_valor["valor_diferencial"] = st.checkbox("Valor + Diferencial", value=st.session_state.checklist_valor["valor_diferencial"], key="val_dif")

        # 5) FECHAMENTO SUAVE
        with st.container(border=True):
            st.subheader("5️⃣ FECHAMENTO SUAVE")
            col1, col2 = st.columns([3, 1])
            with col1:
                st.markdown("""
                ❌ Não perguntar: *"Quer contratar?"*  
                ✅ Perguntar direcionando: *"Prefere instalar amanhã ou sexta?"*
                """)
            with col2:
                st.session_state.checklist_fechamento["pergunta_direcionada"] = st.checkbox("Pergunta direcionada", value=st.session_state.checklist_fechamento["pergunta_direcionada"], key="fech_dir")

        # 6) TRATAMENTO DE OBJEÇÃO
        with st.container(border=True):
            st.subheader("6️⃣ TRATAMENTO DE OBJEÇÃO")
            col1, col2 = st.columns([3, 1])
            with col1:
                st.markdown("""
                • *"Vou pensar"* → *"Ficou alguma dúvida que posso te ajudar agora?"*  
                • *"Vou ver com minha esposa"* → *"Posso te chamar mais tarde para saber o que decidiram?"*
                """)
            with col2:
                st.session_state.checklist_objecao["preparado"] = st.checkbox("Preparado para objeções", value=st.session_state.checklist_objecao["preparado"], key="obj_prep")

        # 7) REGRA DE OURO
        with st.container(border=True):
            st.subheader("7️⃣ REGRA DE OURO")
            col1, col2 = st.columns([3, 1])
            with col1:
                st.markdown("""
                Toda mensagem deve terminar com:  
                • Uma pergunta direcionadora **OU**  
                • Um próximo passo claro.
                """)
            with col2:
                st.session_state.checklist_regra_ouro["pergunta_ou_passo"] = st.checkbox("Final direcionado", value=st.session_state.checklist_regra_ouro["pergunta_ou_passo"], key="regra_fim")

        # Barra de progresso visual
        st.divider()
        total_checks = (
            sum(st.session_state.checklist_abertura.values()) +
            sum(st.session_state.checklist_diagnostico.values()) +
            sum(st.session_state.checklist_recomendacao.values()) +
            sum(st.session_state.checklist_valor.values()) +
            sum(st.session_state.checklist_fechamento.values()) +
            sum(st.session_state.checklist_objecao.values()) +
            sum(st.session_state.checklist_regra_ouro.values())
        )
        total_items = 10  # 3 + 2 + 1 + 1 + 1 + 1 + 1
        progresso = total_checks / total_items
        
        st.progress(progresso, text=f"Progresso: {int(progresso * 100)}%")
        
        if progresso == 1.0:
            st.success("🎉 Checklist completo! Venda bem conduzida!")
            st.balloons()

        # Estrutura para memorizar
        st.divider()
        st.info("""
        **📌 ESTRUTURA PARA MEMORIZAR:**  
        VALIDA → DIAGNOSTICA → RECOMENDA → DIRECIONA
        """)

    # ==================== ABA 2: PLANOS ====================
    with tab_planos:
        st.header("💰 Planos Tracecom")
        st.caption("Clique no botão ao lado para copiar")
        
        # Planos principais (destaque) - LAYOUT EXPANDIDO
        st.subheader("🎯 Planos Principais")
        
        planos_principais = [
            ("600 Mbps Residencial PS + Trace Canais — R$109,99", "🎯 600 Mbps Residencial PS + Trace Canais — R$109,99"),
            ("600 Mbps Residencial PS + Trace Canais + GloboPlay — R$119,99", "🎯 600 Mbps Residencial PS + Trace Canais + GloboPlay — R$119,99"),
            ("800 Mbps Residencial PS + Trace Canais — R$129,99", "🎯 800 Mbps Residencial PS + Trace Canais — R$129,99"),
        ]
        
        # Botão para copiar os 3 planos principais de uma vez
        texto_tres_planos = "\n\n".join([texto for _, texto in planos_principais])
        
        if st.button("📋 Copiar os 3 Planos Principais", key="copiar_tres_principais", type="primary", use_container_width=True):
            st.code(texto_tres_planos, language=None)
            st.toast("✅ 3 planos principais copiados!", icon="📋")
        
        st.divider()
        
        # Lista individual dos 3 planos principais - LAYOUT HORIZONTAL EXPANDIDO
        for idx, (titulo, texto) in enumerate(planos_principais):
            with st.container(border=True):
                # Usar proporção 5:1 para dar mais espaço ao texto
                col1, col2 = st.columns([5, 1])
                with col1:
                    st.markdown(f"**{texto}**")
                with col2:
                    # Botão de copiar diretamente visível
                    if st.button("📋 Copiar", key=f"copiar_principal_{idx}", use_container_width=True):
                        st.code(texto, language=None)
                        st.toast(f"✅ Plano copiado!", icon="📋")

        # Todos os planos
        st.divider()
        st.subheader("📋 Todos os Planos")
        
        todos_planos = [
            "🎯 600 Mbps Residencial PS + Trace Canais — R$109,99",
            "🎯 800 Mbps Residencial PS + Trace Canais — R$129,99",
            "🎯 600 Mbps Residencial PS + Trace Canais + Telemedicina + Teleconsulta + GloboPlay ou Max ou Disney — R$139,99",
            "🎯 600 Mbps Residencial PS + Trace Canais + Telemedicina + GloboPlay ou Max ou Disney — R$119,99",
            "🎯 800 Mbps Residencial PS + Trace Canais + Telemedicina + GloboPlay ou Max ou Disney — R$139,99",
            "🎯 600 Mbps Residencial PS + Trace Canais + Telemedicina + Teleconsulta + GloboPlay + Max — R$159,99",
            "🎯 800 Mbps Residencial PS + Trace Canais + Telemedicina + Teleconsulta + GloboPlay ou Max ou Disney — R$159,99",
            "🎯 800 Mbps Residencial PS + Trace Canais + Telemedicina + Teleconsulta + GloboPlay + Max — R$179,99",
        ]
        
        texto_todos = "\n\n".join(todos_planos)
        
        with st.expander("📄 Ver todos os planos", expanded=False):
            for plano in todos_planos:
                st.markdown(plano)
        
        if st.button("📋 Copiar Todos os Planos", key="copiar_todos", use_container_width=True):
            st.code(texto_todos, language=None)
            st.toast("✅ Todos os planos copiados!", icon="📋")
        
        # Telefonia fixa
        st.divider()
        st.subheader("☎️ Adicional")
        telefonia_texto = "Telefonia Fixa Ilimitada: R$19,99"
        col_tel1, col_tel2 = st.columns([5, 1])
        with col_tel1:
            st.markdown(f"**{telefonia_texto}**")
        with col_tel2:
            if st.button("📋 Copiar", key="copiar_tel", use_container_width=True):
                st.code(telefonia_texto, language=None)
                st.toast("✅ Telefonia copiada!", icon="📋")

    # ==================== ABA 3: CONFIRMAÇÃO DE VENDA ====================
    with tab_confirmacao:
        st.header("📝 Confirmação de Venda")
        st.caption("Texto para solicitar dados do cliente")
        
        # Campo para personalizar nome (opcional)
        nome_cliente = st.text_input("Nome do cliente (opcional):", placeholder="Deixe em branco para mensagem genérica", key="nome_conf")
        
        # Montar mensagem
        if nome_cliente:
            saudacao = f"Olá {nome_cliente}!\n\n"
        else:
            saudacao = "Olá!\n\n"
            
        mensagem = f"""{saudacao}Vamos enviar os dados para o cadastro e análise, ok?

📌 Por favor, envie:

1️⃣ Uma foto segurando um documento com foto.

2️⃣ Os dados abaixo preenchidos de uma só vez, para facilitar o seu cadastro:

Nome completo:
Celular:
Celular de contato (Grau de Parentesco):
Celular de contato (Grau de Parentesco):
Email:
Data de nascimento:
CPF:
RG:
Endereço:
Número:
Bairro:
Ponto de referência:
Tipo de Moradia:
Tempo de Moradia:
Plano escolhido:
Profissão:

Aguardamos sua resposta para prosseguirmos. Qualquer dúvida, estou à disposição!"""

        # Container com borda para a mensagem
        with st.container(border=True):
            st.markdown(mensagem)
            
            # Botão de copiar DENTRO do container, logo abaixo da mensagem
            if st.button("📋 Copiar Mensagem Completa", type="primary", key="copiar_confirm", use_container_width=True):
                st.code(mensagem, language=None)
                st.toast("✅ Mensagem de confirmação copiada!", icon="📋")

    # ==================== ABA 4: ANTI-FRAUDE (NOVA) ====================
    with tab_antifraude:
        st.header("🛡️ Validação Anti-Fraude")
        st.caption("Mensagem para validação presencial obrigatória")
        
        # Campo para personalizar nome (opcional)
        nome_cliente_af = st.text_input("Nome do cliente (opcional):", placeholder="Deixe em branco para mensagem genérica", key="nome_af")
        
        # Montar mensagem
        if nome_cliente_af:
            saudacao_af = f"Olá {nome_cliente_af}!\n\n"
        else:
            saudacao_af = "Olá!\n\n"
            
        mensagem_antifraude = f"""{saudacao_af}Para darmos continuidade à sua solicitação, será necessária a validação presencial mediante comparecimento à nossa loja com documento original com foto para assinatura do contrato."""

        # Container com borda para a mensagem
        with st.container(border=True):
            st.markdown(mensagem_antifraude)
            
            # Botão de copiar DENTRO do container
            if st.button("📋 Copiar Mensagem Anti-Fraude", type="primary", key="copiar_af", use_container_width=True):
                st.code(mensagem_antifraude, language=None)
                st.toast("✅ Mensagem anti-fraude copiada!", icon="🛡️")

    # ==================== ABA 5: ORIENTAÇÕES INICIAIS ====================
    with tab_orientacoes:
        st.header("📋 Orientações Iniciais")
        st.caption("Mensagem para clientes com instalação agendada")
        
        # Campo para personalizar nome (opcional)
        nome_cliente_ori = st.text_input("Nome do cliente (opcional):", placeholder="Deixe em branco para mensagem genérica", key="nome_ori")
        
        # Montar mensagem de orientações
        if nome_cliente_ori:
            saudacao_ori = f"Olá {nome_cliente_ori}!\n\n"
        else:
            saudacao_ori = "Olá!\n\n"
            
        mensagem_orientacoes = f"""{saudacao_ori}Sua instalação está agendada.

📌 Informações Importantes:

📡 Suporte e Acesso:

Após a instalação, você poderá solicitar seu login do Tracecanais pelo WhatsApp 21 3500-0188 (opção 5).

Em caso de travamento por queda de energia, retire o equipamento da tomada por 15 segundos e reconecte.

Se o serviço não normalizar, nosso suporte técnico está disponível pelo WhatsApp 21 3500-0188 (opção 5).

💳 Faturamento:

Sua primeira fatura vencerá 30 dias após a instalação e ativação do contrato.

A fatura poderá ser enviada para o e-mail cadastrado, retirada impressa em nossa loja ou solicitada pelo WhatsApp 21 3500-0188 (opção 1 – Segunda Via).

📱 Aplicativo:

Nosso aplicativo já está disponível. Acesse pelo link abaixo e acompanhe suas faturas, consumo e outras informações da sua conexão:

https://play.google.com/store/apps/details?id=br.net.tracecom.ixc&utm_source=latam_Med

Ficamos muito felizes em ter você com a gente!
Seja bem-vinda à Tracecom 🚀
        """
        
        # Container com borda para a mensagem
        with st.container(border=True):
            st.markdown(mensagem_orientacoes)
            
            # Botão de copiar DENTRO do container
            if st.button("📋 Copiar Orientações", type="primary", key="copiar_orientacoes", use_container_width=True):
                st.code(mensagem_orientacoes, language=None)
                st.toast("✅ Orientações copiadas!", icon="📋")

    # ==================== ABA 6: RECUSA ====================
    with tab_recusa:
        # Container vermelho para destacar
        st.markdown("""
        <style>
        .recusa-box {
            background-color: #fee2e2;
            border: 2px solid #ef4444;
            border-radius: 10px;
            padding: 20px;
            margin: 10px 0;
        }
        </style>
        """, unsafe_allow_html=True)
        
        st.header("❌ Recusa por Restrição")
        
        # Campo para personalizar nome (opcional)
        nome_recusa = st.text_input("Nome do cliente (opcional):", placeholder="Deixe em branco para mensagem genérica", key="nome_rec")
        
        if nome_recusa:
            saudacao_rec = f"Olá {nome_recusa},\n\n"
        else:
            saudacao_rec = "Olá,\n\n"
            
        mensagem_recusa = f"""{saudacao_rec}Agradecemos pelo seu interesse em nossos serviços de internet!

Informamos que, neste momento, não foi possível dar continuidade à contratação.
Mas não se preocupe! Você poderá realizar uma nova solicitação após 30 dias.
Esperamos poder atendê-lo em breve!

Atenciosamente,
Tracecom"""

        with st.container(border=True):
            # Aplicar estilo vermelho
            st.markdown(f'<div class="recusa-box">{mensagem_recusa.replace(chr(10), "<br>")}</div>', unsafe_allow_html=True)
            
            # Botão de copiar abaixo da mensagem
            if st.button("📋 Copiar Mensagem de Recusa", key="copiar_rec", use_container_width=True):
                st.code(mensagem_recusa, language=None)
                st.toast("✅ Mensagem de recusa copiada!", icon="📋")
        
        st.divider()
        if st.button("🔄 Resetar Checklist", type="secondary"):
            # Limpar todos os estados do checklist
            keys_to_clear = [
                "checklist_abertura", "checklist_diagnostico", "checklist_recomendacao",
                "checklist_valor", "checklist_fechamento", "checklist_objecao", "checklist_regra_ouro"
            ]
            for key in keys_to_clear:
                if key in st.session_state:
                    del st.session_state[key]
            st.rerun()
