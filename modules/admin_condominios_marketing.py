# modules/admin_condominios_marketing.py
import streamlit as st
from datetime import datetime
from bson import ObjectId
import uuid
from modules.condominios import get_condominios_collection

def render_admin_marketing():
    """Painel de administração de marketing dos condomínios"""
    st.title("🏢 Marketing - Condomínios")
    st.caption("Gerencie folders, promoções e planos especiais por condomínio")
    
    condominios_coll = get_condominios_collection()
    
    # Abas
    tab_editar, tab_listar = st.tabs(["✏️ Editar Condomínio", "📋 Listar Todos"])
    
    with tab_editar:
        # Buscar condomínio
        todos = list(condominios_coll.find({}).sort("nome", 1))
        
        if not todos:
            st.warning("⚠️ Nenhum condomínio cadastrado!")
            return
        
        opcoes = {f"🏢 {c['nome']} - {c.get('bairro', 'N/A')}": c for c in todos}
        selecionado_label = st.selectbox(
            "Selecione o condomínio para editar:",
            options=list(opcoes.keys()),
            key="admin_select_condominio"
        )
        
        if selecionado_label:
            condominio = opcoes[selecionado_label]
            marketing = condominio.get("marketing", {})
            
            st.divider()
            st.subheader(f"✏️ Editando: {condominio['nome']}")
            
            # ========== FOLDER ==========
            st.markdown("### 📷 Folder Promocional")
            
            folder_atual = marketing.get("folder_url", "")
            if folder_atual:
                st.caption(f"📁 URL atual: {folder_atual}")
                if folder_atual.startswith("http"):
                    try:
                        st.image(folder_atual, width=300)
                    except:
                        st.warning("⚠️ Não foi possível carregar a imagem atual")
            
            folder_url = st.text_input(
                "URL da imagem do folder:",
                value=folder_atual,
                placeholder="https://drive.google.com/... ou assets/folders/nome.jpg",
                help="Cole o link da imagem hospedada (Google Drive, Imgur, etc.) ou caminho local"
            )
            
            st.divider()
            
            # ========== PROMOÇÕES ==========
            st.markdown("### 🎯 Promoções Ativas")
            
            promocoes = marketing.get("promocoes", [])
            
            # Mostrar promoções existentes
            promocoes_para_remover = []
            
            for i, promo in enumerate(promocoes):
                with st.container(border=True):
                    col1, col2 = st.columns([5, 1])
                    with col1:
                        st.markdown(f"**Promoção {i+1}:** {promo.get('descricao', 'Sem descrição')}")
                        if promo.get("validade"):
                            st.caption(f"⏰ Válido até: {promo['validade']}")
                        st.caption(f"{'✅ Ativa' if promo.get('ativa', True) else '❌ Inativa'}")
                    with col2:
                        if st.button("🗑️ Remover", key=f"remover_promo_{i}"):
                            promocoes_para_remover.append(i)
            
            # Remover promoções marcadas
            if promocoes_para_remover:
                for i in sorted(promocoes_para_remover, reverse=True):
                    promocoes.pop(i)
                st.rerun()
            
            # Adicionar nova promoção
            st.markdown("#### ➕ Nova Promoção")
            
            nova_promo_desc = st.text_input(
                "Descrição da promoção:",
                placeholder="Ex: Instalação grátis até 31/05/2026",
                key="nova_promo_desc"
            )
            
            col1, col2 = st.columns(2)
            with col1:
                nova_promo_validade = st.date_input(
                    "Validade:",
                    min_value=datetime.now().date(),
                    key="nova_promo_validade"
                )
            with col2:
                nova_promo_ativa = st.checkbox("Ativa", value=True, key="nova_promo_ativa")
            
            if st.button("✅ Adicionar Promoção", key="add_promo"):
                if nova_promo_desc.strip():
                    promocoes.append({
                        "id": str(uuid.uuid4())[:8],
                        "descricao": nova_promo_desc.strip(),
                        "validade": nova_promo_validade.strftime("%Y-%m-%d"),
                        "ativa": nova_promo_ativa,
                        "adicionada_em": datetime.now()
                    })
                    st.success("✅ Promoção adicionada!")
                    st.rerun()
                else:
                    st.error("⚠️ Descreva a promoção!")
            
            st.divider()
            
            # ========== PLANOS ESPECIAIS ==========
            st.markdown("### 💎 Planos Especiais")
            
            planos_especiais = marketing.get("planos_especiais", [])
            
            planos_para_remover = []
            
            for i, plano in enumerate(planos_especiais):
                with st.container(border=True):
                    col1, col2 = st.columns([5, 1])
                    with col1:
                        st.markdown(f"**{plano.get('nome', 'Plano sem nome')}**")
                        preco = plano.get("preco", "N/A")
                        preco_normal = plano.get("preco_normal", "")
                        if preco_normal:
                            st.markdown(f"~~{preco_normal}~~ → **{preco}**")
                        else:
                            st.markdown(f"**{preco}**")
                        if plano.get("destaque"):
                            st.caption(f"✨ {plano['destaque']}")
                        st.caption(f"{'✅ Ativo' if plano.get('ativo', True) else '❌ Inativo'}")
                    with col2:
                        if st.button("🗑️ Remover", key=f"remover_plano_{i}"):
                            planos_para_remover.append(i)
            
            if planos_para_remover:
                for i in sorted(planos_para_remover, reverse=True):
                    planos_especiais.pop(i)
                st.rerun()
            
            # Adicionar novo plano
            st.markdown("#### ➕ Novo Plano Especial")
            
            col1, col2 = st.columns(2)
            with col1:
                novo_plano_nome = st.text_input(
                    "Nome do plano:",
                    placeholder="Ex: 600 Mbps Residencial",
                    key="novo_plano_nome"
                )
                novo_plano_preco = st.text_input(
                    "Preço especial:",
                    placeholder="Ex: R$89,99",
                    key="novo_plano_preco"
                )
            with col2:
                novo_plano_preco_normal = st.text_input(
                    "Preço normal (opcional):",
                    placeholder="Ex: R$109,99",
                    key="novo_plano_preco_normal"
                )
                novo_plano_destaque = st.text_input(
                    "Destaque (opcional):",
                    placeholder="Ex: 🔥 Exclusivo moradores",
                    key="novo_plano_destaque"
                )
            
            novo_plano_ativo = st.checkbox("Ativo", value=True, key="novo_plano_ativo")
            
            if st.button("✅ Adicionar Plano", key="add_plano"):
                if novo_plano_nome.strip() and novo_plano_preco.strip():
                    planos_especiais.append({
                        "id": str(uuid.uuid4())[:8],
                        "nome": novo_plano_nome.strip(),
                        "preco": novo_plano_preco.strip(),
                        "preco_normal": novo_plano_preco_normal.strip() if novo_plano_preco_normal else None,
                        "destaque": novo_plano_destaque.strip() if novo_plano_destaque else None,
                        "ativo": novo_plano_ativo,
                        "adicionado_em": datetime.now()
                    })
                    st.success("✅ Plano adicionado!")
                    st.rerun()
                else:
                    st.error("⚠️ Preencha nome e preço do plano!")
            
            st.divider()
            
            # ========== SALVAR TUDO ==========
            if st.button("💾 Salvar Todas as Alterações", type="primary", use_container_width=True):
                try:
                    condominios_coll.update_one(
                        {"_id": condominio["_id"]},
                        {"$set": {
                            "marketing": {
                                "folder_url": folder_url.strip() if folder_url else None,
                                "promocoes": promocoes,
                                "planos_especiais": planos_especiais,
                                "atualizado_por": st.session_state.get("nome_usuario", "admin"),
                                "ultima_atualizacao": datetime.now()
                            }
                        }}
                    )
                    st.success("✅ Marketing do condomínio atualizado com sucesso!")
                    st.balloons()
                except Exception as e:
                    st.error(f"❌ Erro ao salvar: {e}")
    
    with tab_listar:
        st.subheader("📋 Condomínios com Marketing")
        
        # Buscar condomínios que têm marketing
        com_marketing = list(condominios_coll.find(
            {"marketing": {"$exists": True}}
        ).sort("nome", 1))
        
        if com_marketing:
            for c in com_marketing:
                mkt = c.get("marketing", {})
                with st.expander(f"🏢 {c['nome']} - {c.get('bairro', 'N/A')}", expanded=False):
                    st.write(f"**Folder:** {'✅ Cadastrado' if mkt.get('folder_url') else '❌ Não cadastrado'}")
                    st.write(f"**Promoções:** {len(mkt.get('promocoes', []))}")
                    st.write(f"**Planos Especiais:** {len(mkt.get('planos_especiais', []))}")
                    if mkt.get("ultima_atualizacao"):
                        st.caption(f"Última atualização: {mkt['ultima_atualizacao'].strftime('%d/%m/%Y %H:%M')}")
        else:
            st.info("📭 Nenhum condomínio com marketing cadastrado ainda.")
