# modules/roteiro_vendas.py
# ✅ OTIMIZADO - Com carregamento sob demanda e cache
import streamlit as st
from datetime import datetime
from modules.condominios import get_condominios_collection

def render_roteiro_vendas(clientes_collection):
    """Módulo de roteiro de vendas com checklist interativo e textos prontos"""
    
    st.title("🧭 Roteiro de Vendas - WhatsApp")
    st.caption("Guia passo a passo para atendimento eficaz")

    # Criar as 6 abas
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
        total_items = 10
        progresso = total_checks / total_items
        
        st.progress(progresso, text=f"Progresso: {int(progresso * 100)}%")
        
        if progresso == 1.0:
            st.success("🎉 Checklist completo! Venda bem conduzida!")
            st.balloons()

        st.divider()
        st.info("""
        **📌 ESTRUTURA PARA MEMORIZAR:**  
        VALIDA → DIAGNOSTICA → RECOMENDA → DIRECIONA
        """)

    # ==================== ABA 2: PLANOS (OTIMIZADO COM CACHE) ====================
    with tab_planos:
        st.header("💰 Planos e Promoções por Condomínio")
        st.caption("Busque um condomínio para ver promoções e planos exclusivos")
        
        # Função com cache para carregar condomínios
        @st.cache_data(ttl=300, show_spinner=False)  # Cache por 5 minutos
        def carregar_condominios():
            """Carrega condomínios do banco com campos essenciais apenas"""
            try:
                condominios_coll = get_condominios_collection()
                # Buscar apenas campos necessários para performance
                condominios = list(condominios_coll.find(
                    {}, 
                    {
                        "nome": 1, 
                        "bairro": 1, 
                        "endereco": 1, 
                        "numero": 1, 
                        "cidade": 1,
                        "marketing": 1
                    }
                ).sort("nome", 1))
                return condominios
            except Exception as e:
                st.error(f"Erro ao carregar condomínios: {e}")
                return []
        
        # Carregar condomínios com spinner
        with st.spinner("📡 Carregando condomínios..."):
            todos_condominios = carregar_condominios()
        
        if not todos_condominios:
            st.warning("⚠️ Nenhum condomínio cadastrado no sistema ainda.")
            st.info("Solicite ao administrador o cadastro dos condomínios.")
            return
        
        # Campo de busca
        busca = st.text_input(
            "🔍 Digite o nome do condomínio:",
            placeholder="Ex: Residencial Parque das Flores",
            key="busca_condominio_planos"
        )
        
        if not busca:
            st.info("👆 Digite o nome de um condomínio para buscar promoções e planos exclusivos.")
            return
        
        # Filtrar condomínios (busca case-insensitive)
        busca_lower = busca.lower()
        condominios_filtrados = [
            c for c in todos_condominios 
            if busca_lower in c.get("nome", "").lower()
        ]
        
        if not condominios_filtrados:
            st.warning(f"🔍 Nenhum condomínio encontrado com: '{busca}'")
            st.info("Tente buscar por parte do nome (ex: 'Parque' em vez de 'Residencial Parque das Flores')")
            return
        
        # Limitar a 20 resultados para não sobrecarregar
        if len(condominios_filtrados) > 20:
            st.info(f"📋 Encontrados {len(condominios_filtrados)} condomínios. Mostrando os 20 primeiros.")
            condominios_filtrados = condominios_filtrados[:20]
        
        # Selecionar condomínio
        opcoes = {}
        for i, c in enumerate(condominios_filtrados):
            label = f"🏢 {c['nome']} - {c.get('bairro', 'N/A')}"
            opcoes[label] = c
        
        selecionado_label = st.selectbox(
            "Selecione o condomínio:",
            options=list(opcoes.keys()),
            key="select_condominio_planos"
        )
        
        if not selecionado_label:
            return
        
        condominio = opcoes[selecionado_label]
        marketing = condominio.get("marketing", {})
        
        st.divider()
        
        # ========== PAINEL DO CONDOMÍNIO ==========
        endereco_completo = f"{condominio.get('endereco', '')}, {condominio.get('numero', '')}"
        bairro = condominio.get('bairro', '')
        cidade = condominio.get('cidade', 'Rio de Janeiro')
        
        st.markdown(f"""
        <div style="
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            border-radius: 15px;
            padding: 20px;
            color: white;
            margin: 10px 0;
        ">
            <h2 style="color: white; margin: 0;">🏢 {condominio['nome']}</h2>
            <p style="margin: 5px 0; opacity: 0.9;">
                📍 {endereco_completo} - {bairro} - {cidade}
            </p>
        </div>
        """, unsafe_allow_html=True)
        
        # ========== FOLDER DO CONDOMÍNIO ==========
        folder_url = marketing.get("folder_url", "")
        
        if folder_url:
            st.subheader("📋 Folder Promocional")
            
            try:
                if folder_url.startswith("http"):
                    st.image(folder_url, use_container_width=True)
                    # Botão para abrir em nova aba
                    st.link_button("🔗 Abrir Folder", folder_url)
                else:
                    try:
                        st.image(folder_url, use_container_width=True)
                    except:
                        st.warning(f"⚠️ Imagem não encontrada no caminho: {folder_url}")
                        st.info("💡 O supervisor precisa atualizar o caminho da imagem do folder.")
            except Exception as e:
                st.warning(f"⚠️ Não foi possível carregar a imagem. Erro: {e}")
        else:
            st.info("📷 Nenhum folder cadastrado para este condomínio ainda.")
            st.caption("Solicite ao supervisor para cadastrar o folder promocional.")
        
        st.divider()
        
        # ========== PROMOÇÕES ATIVAS ==========
        promocoes = marketing.get("promocoes", [])
        promocoes_ativas = [p for p in promocoes if p.get("ativa", True)]
        
        # Filtrar promoções não vencidas
        promocoes_validas = []
        for promo in promocoes_ativas:
            validade = promo.get("validade", "")
            if validade:
                try:
                    data_validade = datetime.strptime(validade, "%Y-%m-%d")
                    if data_validade < datetime.now():
                        continue  # Vencida, pular
                except:
                    pass  # Data inválida, mostrar mesmo assim
            promocoes_validas.append(promo)
        
        if promocoes_validas:
            st.subheader("🎯 Promoções Ativas")
            
            for idx, promo in enumerate(promocoes_validas):
                with st.container(border=True):
                    col1, col2 = st.columns([4, 1])
                    with col1:
                        st.markdown(f"### 🔥 {promo['descricao']}")
                    with col2:
                        validade = promo.get("validade", "")
                        if validade:
                            try:
                                data_val = datetime.strptime(validade, "%Y-%m-%d")
                                st.caption(f"⏰ Até {data_val.strftime('%d/%m/%Y')}")
                            except:
                                pass
                    
                    # Botão para copiar com chave única
                    promo_id = promo.get('id', f'promo_{idx}')
                    if st.button("📋 Copiar Promoção", key=f"copiar_promo_{promo_id}", use_container_width=True):
                        st.code(promo['descricao'], language=None)
                        st.toast("✅ Promoção copiada!", icon="📋")
        else:
            st.info("📢 Nenhuma promoção ativa no momento para este condomínio.")
        
        st.divider()
        
        # ========== PLANOS ESPECIAIS DO CONDOMÍNIO ==========
        planos_especiais = marketing.get("planos_especiais", [])
        planos_ativos = [p for p in planos_especiais if p.get("ativo", True)]
        
        if planos_ativos:
            st.subheader("💎 Planos Especiais para este Condomínio")
            
            for idx, plano in enumerate(planos_ativos):
                with st.container(border=True):
                    col1, col2, col3 = st.columns([3, 2, 1])
                    
                    with col1:
                        st.markdown(f"**{plano.get('nome', 'Plano Especial')}**")
                        if plano.get("destaque"):
                            st.caption(f"✨ {plano['destaque']}")
                    
                    with col2:
                        preco = plano.get("preco", "Sob consulta")
                        preco_normal = plano.get("preco_normal", "")
                        
                        if preco_normal:
                            st.markdown(f"<span style='text-decoration: line-through; color: #999;'>{preco_normal}</span>", unsafe_allow_html=True)
                        st.markdown(f"### {preco}")
                    
                    with col3:
                        texto_plano = f"{plano.get('nome', '')} - {preco}"
                        if plano.get("destaque"):
                            texto_plano += f" ({plano['destaque']})"
                        
                        plano_id = plano.get('id', f'plano_{idx}')
                        if st.button("📋 Copiar", key=f"copiar_plano_{plano_id}", use_container_width=True):
                            st.code(texto_plano, language=None)
                            st.toast("✅ Plano copiado!", icon="📋")
        else:
            st.info("💎 Nenhum plano especial cadastrado para este condomínio.")
            st.caption("Os supervisores podem cadastrar planos especiais no módulo 'Marketing Condomínios'.")
        
        # Rodapé informativo
        st.divider()
        with st.expander("ℹ️ Informações de Contato", expanded=False):
            st.markdown("""
            📞 **Suporte Tracecom:** (21) 3500-0188  
            📱 **WhatsApp:** (21) 3500-0188  
            🌐 **Site:** www.tracecom.net
            """)

    # ==================== ABA 3: CONFIRMAÇÃO DE VENDA ====================
    with tab_confirmacao:
        st.header("📝 Confirmação de Venda")
        st.caption("Texto para solicitar dados do cliente")
        
        nome_cliente = st.text_input("Nome do cliente (opcional):", placeholder="Deixe em branco para mensagem genérica", key="nome_conf")
        
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

        with st.container(border=True):
            st.markdown(mensagem)
            
            if st.button("📋 Copiar Mensagem Completa", type="primary", key="copiar_confirm", use_container_width=True):
                st.code(mensagem, language=None)
                st.toast("✅ Mensagem de confirmação copiada!", icon="📋")

    # ==================== ABA 4: ANTI-FRAUDE ====================
    with tab_antifraude:
        st.header("🛡️ Validação Anti-Fraude")
        st.caption("Mensagem para validação presencial obrigatória")
        
        nome_cliente_af = st.text_input("Nome do cliente (opcional):", placeholder="Deixe em branco para mensagem genérica", key="nome_af")
        
        if nome_cliente_af:
            saudacao_af = f"Olá {nome_cliente_af}!\n\n"
        else:
            saudacao_af = "Olá!\n\n"
            
        mensagem_antifraude = f"""{saudacao_af}Para darmos continuidade à sua solicitação, será necessária a validação presencial mediante comparecimento à nossa loja com documento original com foto para assinatura do contrato."""

        with st.container(border=True):
            st.markdown(mensagem_antifraude)
            
            if st.button("📋 Copiar Mensagem Anti-Fraude", type="primary", key="copiar_af", use_container_width=True):
                st.code(mensagem_antifraude, language=None)
                st.toast("✅ Mensagem anti-fraude copiada!", icon="🛡️")

    # ==================== ABA 5: ORIENTAÇÕES INICIAIS ====================
    with tab_orientacoes:
        st.header("📋 Orientações Iniciais")
        st.caption("Mensagem para clientes com instalação agendada")
        
        nome_cliente_ori = st.text_input("Nome do cliente (opcional):", placeholder="Deixe em branco para mensagem genérica", key="nome_ori")
        
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
        
        with st.container(border=True):
            st.markdown(mensagem_orientacoes)
            
            if st.button("📋 Copiar Orientações", type="primary", key="copiar_orientacoes", use_container_width=True):
                st.code(mensagem_orientacoes, language=None)
                st.toast("✅ Orientações copiadas!", icon="📋")

    # ==================== ABA 6: RECUSA ====================
    with tab_recusa:
        st.header("❌ Recusa por Restrição")
        
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
            st.markdown(f"""
            <div style="
                background-color: #fee2e2;
                border: 2px solid #ef4444;
                border-radius: 10px;
                padding: 20px;
                margin: 10px 0;
            ">{mensagem_recusa.replace(chr(10), '<br>')}</div>
            """, unsafe_allow_html=True)
            
            if st.button("📋 Copiar Mensagem de Recusa", key="copiar_rec", use_container_width=True):
                st.code(mensagem_recusa, language=None)
                st.toast("✅ Mensagem de recusa copiada!", icon="📋")
        
        st.divider()
        if st.button("🔄 Resetar Checklist", type="secondary"):
            keys_to_clear = [
                "checklist_abertura", "checklist_diagnostico", "checklist_recomendacao",
                "checklist_valor", "checklist_fechamento", "checklist_objecao", "checklist_regra_ouro"
            ]
            for key in keys_to_clear:
                if key in st.session_state:
                    del st.session_state[key]
            st.rerun()
