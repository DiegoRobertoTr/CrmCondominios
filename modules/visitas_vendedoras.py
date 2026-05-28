import streamlit as st
import pandas as pd
from datetime import datetime, timedelta
from collections import defaultdict
import io

# Configuração de capacidade e disponibilidade das vendedoras
CAPACIDADE_VENDEDORAS = {
    "KESSIA":       {"dias_validos": [0,1,2,3,4,5], "max_diario": 3}, # Seg(0)..Sáb(5)
    "LARISSA":      {"dias_validos": [0,1,2,3,4,5], "max_diario": 2},
    "ESTEPHANIE":   {"dias_validos": [0,1,2,3,4,5], "max_diario": 2},
    "JULIANA":      {"dias_validos": [2,4],          "max_diario": 2}, # Apenas Qua e Sex
}

def render_visitas_vendedoras(visitas_collection):
    perfil = st.session_state.get("perfil")
    usuario = st.session_state.get("nome_usuario", "").upper()

    st.markdown("## 👩‍💼 Agendamento de Visitas Externas")

    if perfil in ["admin", "diretoria"]:
        tab_gestao, tab_relatorio = st.tabs(["📅 Gestão & Agenda", "📊 Exportação & Métricas"])
        with tab_gestao: _mostrar_gestao_admin(visitas_collection)
        with tab_relatorio: _mostrar_exportacao(visitas_collection)

    elif perfil == "atendente_n1":
        _mostrar_conclusao_visitas(visitas_collection)

    elif perfil == "vendedora":
        # Filtra apenas pela vendedora logada
        st.info(f"👤 Visualizando agenda de: **{usuario}**")
        _mostrar_minha_agenda(visitas_collection, usuario)

    else:
        st.warning("⚠️ Seu perfil não tem acesso a este módulo.")

# =========================================================================
# GESTÃO (ADMIN/DIRETORIA)
# =========================================================================
def _mostrar_gestao_admin(visitas_collection):
    col1, col2 = st.columns([2, 1])
    with col1:
        data_inicio = st.date_input("📅 Início da Semana:", value=datetime.now().date())
    with col2:
        if st.button("🔄 Recarregar", use_container_width=True): st.rerun()

    data_fim = data_inicio + timedelta(days=6)
    st.caption(f"🗓️ Semana: {data_inicio.strftime('%d/%m')} a {data_fim.strftime('%d/%m')}")

    # Formulário de agendamento
    st.markdown("### ➕ Agendar Nova Visita")
    col_a, col_b, col_c = st.columns(3)
    with col_a:
        condominio = st.text_input("Condomínio:", placeholder="Nome exato ou buscar...")
        num_aptos = st.number_input("Nº Aptos:", min_value=1, value=300)
        prefere_sabado = st.checkbox("Priorizar Sábado (alto fluxo)")
    with col_b:
        vendedora = st.selectbox("Vendedora:", list(CAPACIDADE_VENDEDORAS.keys()))
        data_visita = st.date_input("Data:", min_value=data_inicio, max_value=data_fim, value=data_inicio)
        periodo = st.selectbox("Período:", ["Manhã", "Tarde"])
    with col_c:
        prioridade = st.selectbox("Prioridade:", ["alta", "media", "baixa"])
        obs = st.text_area("Observações:")

    if st.button("✅ Agendar Visita", type="primary", use_container_width=True):
        dia_semana = data_visita.weekday() # 0=Seg, 5=Sáb
        
        # Validações
        if dia_semana not in CAPACIDADE_VENDEDORAS[vendedora]["dias_validos"]:
            st.error(f"❌ {vendedora} não trabalha neste dia da semana.")
        else:
            # Verifica capacidade
            count_dia = visitas_collection.count_documents({
                "data_visita": data_visita.isoformat(),
                "vendedora": vendedora,
                "status": {"$in": ["pendente", "concluido"]}
            })
            if count_dia >= CAPACIDADE_VENDEDORAS[vendedora]["max_diario"]:
                st.warning(f"⚠️ {vendedora} já atingiu o limite de {count_dia}/{CAPACIDADE_VENDEDORAS[vendedora]['max_diario']} visitas no dia.")
                if not st.button("Forçar agendamento mesmo assim?", key="force_agendar"):
                    st.stop()

            visitas_collection.insert_one({
                "condominio_nome": condominio,
                "num_aptos": num_aptos,
                "data_visita": data_visita.isoformat(),
                "vendedora": vendedora,
                "periodo": periodo,
                "status": "pendente",
                "prioridade": prioridade,
                "prefere_sabado": prefere_sabado,
                "observacoes_conclusao": "",
                "criado_em": datetime.now()
            })
            st.success(f"✅ Visita agendada para {data_visita.strftime('%d/%m')}!")
            st.rerun()

    # Tabela da semana
    st.markdown("### 📋 Agenda da Semana")
    filtro = {
        "data_visita": {"$gte": data_inicio.isoformat(), "$lte": data_fim.isoformat()},
        "status": {"$ne": "cancelado"}
    }
    visitas = list(visitas_collection.find(filtro).sort([("data_visita", 1), ("vendedora", 1)]))
    
    if not visitas:
        st.info("📭 Nenhum agendamento nesta semana.")
        return

    df = pd.DataFrame(visitas)
    df["data_visita"] = pd.to_datetime(df["data_visita"]).dt.strftime("%d/%m")
    st.dataframe(df[["condominio_nome", "data_visita", "vendedora", "periodo", "status", "prioridade"]], use_container_width=True)

# =========================================================================
# CONCLUSÃO (ATENDENTE N1)
# =========================================================================
def _mostrar_conclusao_visitas(visitas_collection):
    st.markdown("### ✅ Concluir Visitas do Dia")
    hoje = datetime.now().date()
    
    pendentes = list(visitas_collection.find({
        "data_visita": hoje.isoformat(),
        "status": "pendente"
    }))

    if not pendentes:
        st.info("🎉 Nenhuma visita pendente para hoje.")
        return

    for v in pendentes:
        with st.expander(f"🏢 {v['condominio_nome']} - {v['vendedora']} ({v['periodo']})"):
            st.write(f"📍 Aptos: {v.get('num_aptos', '-')} | Prioridade: {v.get('prioridade', '-')}")
            obs = st.text_input("Observações da visita:", key=f"obs_{v['_id']}")
            col_ok, col_no = st.columns(2)
            with col_ok:
                if st.button("✅ Concluído", key=f"done_{v['_id']}"):
                    visitas_collection.update_one({"_id": v["_id"]}, {
                        "$set": {"status": "concluido", "observacoes_conclusao": obs, "atualizado_em": datetime.now()}
                    })
                    st.success("Marcado como concluído!")
                    st.rerun()
            with col_no:
                if st.button("🚫 Cancelar/Reagendar", key=f"cancel_{v['_id']}"):
                    st.warning("Função de reagendamento disponível apenas para Admin.")

# =========================================================================
# MINHA AGENDA (VENDEDORA)
# =========================================================================
def _mostrar_minha_agenda(visitas_collection, nome_vendedora):
    hoje = datetime.now().date()
    daqui_7 = hoje + timedelta(days=7)
    
    minhas = list(visitas_collection.find({
        "vendedora": nome_vendedora,
        "data_visita": {"$gte": hoje.isoformat(), "$lte": daqui_7.isoformat()}
    }).sort("data_visita", 1))

    if not minhas:
        st.info("📅 Você não tem visitas agendadas nos próximos 7 dias.")
        return

    for m in minhas:
        status_icon = {"pendente": "⏳", "concluido": "✅", "cancelado": "❌"}.get(m["status"], "⚠️")
        st.markdown(f"### {status_icon} `{m['data_visita']}` - **{m['condominio_nome']}**")
        st.write(f"🕒 {m['periodo']} | 📊 {m.get('num_aptos', '-')} aptos")
        if m.get("observacoes_conclusao"):
            st.info(f"📝 Obs: {m['observacoes_conclusao']}")
        st.divider()

# =========================================================================
# EXPORTAÇÃO (RELATÓRIO EXATO DO MODELO SOLICITADO)
# =========================================================================
def _mostrar_exportacao(visitas_collection):
    st.markdown("### 📊 Relatório Semanal & Exportação")
    semana_inicio = st.date_input("Semana de referência:", value=datetime.now().date())
    
    if st.button("📥 Gerar & Exportar", type="primary"):
        # Busca todas as visitas do mês para montar a visão semanal
        mes_inicio = semana_inicio.replace(day=1)
        mes_fim = (mes_inicio + timedelta(days=31)).replace(day=1) - timedelta(days=1)
        
        todas = list(visitas_collection.find({
            "data_visita": {"$gte": mes_inicio.isoformat(), "$lte": mes_fim.isoformat()}
        }))

        # Agrupa por condomínio e conta visitas por dia da semana
        dados = defaultdict(lambda: {"dias": [0]*6, "vendedoras": [], "visitadas": 0})
        for v in todas:
            nome = v["condominio_nome"]
            dia = datetime.fromisoformat(v["data_visita"]).weekday()
            dados[nome]["dias"][dia] += 1
            dados[nome]["vendedoras"].append(v["vendedora"])
            dados[nome]["visitadas"] += 1

        linhas = []
        for cond, info in dados.items():
            vendedores_unicos = list(dict.fromkeys(info["vendedoras"])) # Remove duplicatas mantendo ordem
            linhas.append({
                "Condominio": cond,
                "Aptos": v.get("num_aptos", 0) if (v := next((x for x in todas if x["condominio_nome"]==cond), None)) else 0,
                "Vendedor Principal": vendedores_unicos[0] if vendedores_unicos else "-",
                "Segunda": "Kessia" if info["dias"][0]>0 else "",
                "Terca": "Larissa" if info["dias"][1]>0 else "",
                "Quarta": "Juliana" if info["dias"][2]>0 else "",
                "Quinta": "Estephanie" if info["dias"][3]>0 else "",
                "Sexta": "Kessia" if info["dias"][4]>0 else "",
                "Sabado": "Kessia" if info["dias"][5]>0 else "",
                "Visitas_na_Semana": sum(info["dias"])
            })

        df = pd.DataFrame(linhas)
        st.dataframe(df, use_container_width=True)

        # Export Excel
        output = io.BytesIO()
        with pd.ExcelWriter(output, engine="openpyxl") as writer:
            df.to_excel(writer, index=False, sheet_name="Visitas")
        output.seek(0)
        st.download_button("📥 Baixar Excel (.xlsx)", data=output, file_name=f"visitas_{semana_inicio.strftime('%Y-%m')}.xlsx")
