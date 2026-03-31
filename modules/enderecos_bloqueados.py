# modules/enderecos_bloqueados.py
import streamlit as st
import pandas as pd
from datetime import datetime
import base64

def mascara_cpf(cpf):
    if not cpf or len(cpf) != 11:
        return "—"
    return f"{cpf[:3]}***{cpf[-2:]}"

def montar_endereco_completo(doc):
    """Gera string de endereço completo: Rua - Número (Complemento)"""
    endereco = (doc.get("endereco") or "").strip()
    numero = (doc.get("numero") or "").strip()
    complemento = (doc.get("complemento") or "").strip()
    
    partes = [endereco, numero]
    endereco_base = " - ".join(p for p in partes if p)
    
    if complemento:
        endereco_base += f" ({complemento})"
        
    return endereco_base or "Endereço não informado"

def render_enderecos_bloqueados(clientes_collection):
    st.title("📍 Endereços Bloqueados")
    st.markdown("🔍 Pesquise, gerencie e audite endereços bloqueados no sistema.")
    
    perfil = st.session_state.get("perfil", "")
    is_admin = perfil == "admin"

    # --- Barra de pesquisa ---
    col1, col2 = st.columns([3, 1])
    with col1:
        termo_busca = st.text_input(
            "Pesquisar por endereço (parcial ou completo)",
            placeholder="Ex: Rua das Palmeiras, 123 ou Palmeiras",
            key="busca_endereco_bloqueado"
        ).strip().lower()
    with col2:
        st.markdown("<br>", unsafe_allow_html=True)
        if st.button("↻ Atualizar", key="btn_atualizar_bloqueios"):
            st.rerun()

    # ✅ Busca por endereços bloqueados (com número)
    query = {"endereco_bloqueado": True}
    if termo_busca:
        # Busca por qualquer parte do endereço completo (fallback para compatibilidade)
        query["$or"] = [
            {"endereco": {"$regex": termo_busca, "$options": "i"}},
            {"numero": {"$regex": termo_busca, "$options": "i"}},
            {"complemento": {"$regex": termo_busca, "$options": "i"}},
            {"endereco_completo_bloqueado": {"$regex": termo_busca, "$options": "i"}}
        ]

    registros_bloqueados = list(clientes_collection.find(query).sort("data_cadastro", -1))

    if not registros_bloqueados:
        st.info("📭 Nenhum endereço bloqueado encontrado." if termo_busca else "✅ Nenhum endereço bloqueado no sistema.")
        return

    # ✅ Agrupar por chave única: (endereco, numero, complemento)
    from collections import defaultdict
    agrupados = defaultdict(list)
    for doc in registros_bloqueados:
        chave = (
            (doc.get("endereco") or "").strip().lower(),
            (doc.get("numero") or "").strip(),
            (doc.get("complemento") or "").strip()
        )
        agrupados[chave].append(doc)

    # Ordenar por data do primeiro cadastro (mais recente primeiro)
    lista_enderecos = sorted(
        agrupados.items(),
        key=lambda x: min(
            c.get("data_cadastro", datetime.min) 
            for c in x[1] 
            if isinstance(c.get("data_cadastro"), datetime)
        ),
        reverse=True
    )

    st.metric("📌 Endereços bloqueados", len(lista_enderecos))

    # --- Exportação (só admin) ---
    if is_admin and st.button("📥 Exportar Relatório (CSV)", key="exportar_csv_bloqueios"):
        dados_export = []
        for chave, cadastros in lista_enderecos:
            primeiro = cadastros[0]
            endereco_completo = montar_endereco_completo(primeiro)
            motivo = next(
                (c.get("observacoes_bloqueio_endereco", "—") for c in cadastros if c.get("observacoes_bloqueio_endereco")),
                "—"
            )
            bloqueado_por = primeiro.get("bloqueado_por", "—")
            data_bloqueio = primeiro.get("data_bloqueio")
            if isinstance(data_bloqueio, datetime):
                data_bloqueio = data_bloqueio.strftime("%d/%m/%Y %H:%M")
            else:
                data_bloqueio = "—"

            for c in cadastros:
                dados_export.append({
                    "Endereço Completo": endereco_completo,
                    "Motivo do Bloqueio": motivo,
                    "Bloqueado Por": bloqueado_por,
                    "Data do Bloqueio": data_bloqueio,
                    "Nome": c.get("nome_completo", "—"),
                    "CPF": mascara_cpf(c.get("cpf", "")),
                    "Celular": c.get("celular", "—"),
                    "Tipo": c.get("tipo_cadastro", "—").title(),
                    "Status": c.get("status", "—").title(),
                    "Data Cadastro": c.get("data_cadastro", "").strftime("%d/%m/%Y %H:%M") 
                        if isinstance(c.get("data_cadastro"), datetime) else "—",
                    "Cadastrado Por": c.get("cadastrado_por", "—")
                })
        df = pd.DataFrame(dados_export)
        csv = df.to_csv(index=False).encode("utf-8")
        b64 = base64.b64encode(csv).decode()
        href = f'<a href="file/csv;base64,{b64}" download="enderecos_bloqueados_{datetime.now().strftime("%Y%m%d_%H%M")}.csv" style="display:inline-block;padding:0.4em 1em;background:#0068c9;color:white;border-radius:5px;text-decoration:none;">📥 Baixar CSV</a>'
        st.markdown(href, unsafe_allow_html=True)

    # --- Lista interativa ---
    for i, (chave, cadastros) in enumerate(lista_enderecos):
        endereco_exibicao = montar_endereco_completo(cadastros[0])
        
        # ✅ Expander com endereço completo (ex: "Rua Vicente de Moraes - 86")
        with st.expander(f"📍 {endereco_exibicao}", expanded=False):
            # Motivo do bloqueio
            motivo = next(
                (c.get("observacoes_bloqueio_endereco", "").strip() for c in cadastros if c.get("observacoes_bloqueio_endereco")),
                ""
            )
            if motivo:
                st.markdown(
                    f"<p style='background:#f0f0f0;padding:8px;border-radius:5px;'><strong>📝 Motivo:</strong> {motivo}</p>",
                    unsafe_allow_html=True
                )
            else:
                st.warning("⚠️ Motivo não informado.")

            # Informações de auditoria (só admin)
            if is_admin:
                primeiro = cadastros[0]
                bloqueado_por = primeiro.get("bloqueado_por", "—")
                data_bloqueio = primeiro.get("data_bloqueio")
                if isinstance(data_bloqueio, datetime):
                    data_bloqueio = data_bloqueio.strftime("%d/%m/%Y %H:%M")
                else:
                    data_bloqueio = "—"
                st.caption(f"🔒 Bloqueado por: {bloqueado_por} • {data_bloqueio}")

            # Lista de cadastros associados a esse endereço EXATO
            st.markdown(f"👥 **{len(cadastros)} cadastro(s)** neste endereço:")
            for c in cadastros:
                col_a, col_b, col_c = st.columns([2, 1, 2])
                with col_a:
                    st.markdown(f"**{c.get('nome_completo', '—')}**")
                    st.caption(f"CPF: {mascara_cpf(c.get('cpf',''))} • {c.get('celular','—')}")
                with col_b:
                    badge_tipo = "🔵 Simples" if c.get("tipo_cadastro") == "simples" else "🟢 Completo"
                    badge_status = {
                        "novo": "🟡 Novo",
                        "analise": "🟠 Em análise",
                        "convertido": "🟢 Convertido"
                    }.get(c.get("status"), c.get("status", "—"))
                    st.markdown(f"<small>{badge_tipo}<br>{badge_status}</small>", unsafe_allow_html=True)
                with col_c:
                    data_str = c.get("data_cadastro")
                    if isinstance(data_str, datetime):
                        data_str = data_str.strftime("%d/%m/%Y %H:%M")
                    st.caption(f"{data_str} • {c.get('cadastrado_por', '—')}")

            # Ações (só admin)
            if is_admin:
                st.divider()
                col_d, col_e = st.columns(2)
                with col_d:
                    if st.button("🔓 Desbloquear Endereço", key=f"desbloquear_{i}", type="secondary"):
                        try:
                            # ✅ Desbloqueia só o endereço EXATO (não a rua toda)
                            update_query = {
                                "endereco": chave[0],
                                "numero": chave[1]
                            }
                            if chave[2]:  # complemento
                                update_query["complemento"] = chave[2]
                            update_query["endereco_bloqueado"] = True  # só os bloqueados!
                            result = clientes_collection.update_many(
                                update_query,
                                {"$set": {
                                    "endereco_bloqueado": False,
                                    "observacoes_bloqueio_endereco": None,
                                    "endereco_completo_bloqueado": None
                                }}
                            )
                            st.success(f"✅ Endereço desbloqueado ({result.modified_count} cadastro(s) atualizados).")
                            st.rerun()
                        except Exception as e:
                            st.error(f"❌ Erro ao desbloquear: {e}")
                with col_e:
                    if st.button("✏️ Editar Motivo", key=f"editar_motivo_{i}"):
                        st.session_state[f"editando_motivo_{i}"] = True

                # Formulário de edição de motivo
                if st.session_state.get(f"editando_motivo_{i}", False):
                    novo_motivo = st.text_area(
                        "Novo motivo do bloqueio:",
                        value=motivo,
                        key=f"input_motivo_{i}",
                        help="Deixe em branco para remover o motivo (não recomendado)."
                    )
                    col_s, col_x = st.columns(2)
                    with col_s:
                        if st.button("💾 Salvar", key=f"salvar_motivo_{i}"):
                            try:
                                # ✅ Query precisa: endereco + numero + complemento + bloqueado
                                update_query = {
                                    "endereco": chave[0],
                                    "numero": chave[1]
                                }
                                if chave[2]:  # complemento
                                    update_query["complemento"] = chave[2]
                                update_query["endereco_bloqueado"] = True

                                result = clientes_collection.update_many(
                                    update_query,
                                    {"$set": {"observacoes_bloqueio_endereco": novo_motivo.strip() or None}}
                                )
                                if result.matched_count == 0:
                                    st.warning("⚠️ Nenhum cadastro encontrado para atualização.")
                                else:
                                    st.success(f"✅ Motivo atualizado! ({result.modified_count} cadastro(s) afetados.)")
                                st.session_state[f"editando_motivo_{i}"] = False
                                st.rerun()
                            except Exception as e:
                                st.error(f"❌ Erro ao salvar: {e}")
                    with col_x:
                        if st.button("❌ Cancelar", key=f"cancelar_motivo_{i}"):
                            st.session_state[f"editando_motivo_{i}"] = False
                            st.rerun()
