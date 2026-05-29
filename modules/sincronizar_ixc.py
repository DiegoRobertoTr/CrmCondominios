# modules/sincronizar_ixc.py
import streamlit as st
from datetime import datetime
from modules.integracao_ixc import enviar_cliente_para_ixc

def render_sincronizacao_ixc(clientes_collection):
    """Painel para sincronizar clientes pendentes com o IXC"""
    
    st.subheader("🔄 Sincronização com IXCsoft")
    
    # Buscar clientes não integrados
    pendentes = list(clientes_collection.find({
        "$or": [
            {"integrado_ixc": {"$ne": True}},
            {"id_ixc": {"$exists": False}}
        ],
        "tentativas_integracao": {"$lt": 5}  # máximo 5 tentativas
    }))
    
    if not pendentes:
        st.success("✅ Todos os clientes estão integrados com o IXC!")
        return
    
    st.warning(f"📋 {len(pendentes)} cliente(s) aguardando integração")
    
    for cliente in pendentes:
        with st.expander(f"🔄 {cliente['nome_completo']} - {cliente.get('celular', '')}"):
            st.write(f"**CPF:** {cliente.get('cpf', 'N/A')}")
            st.write(f"**Tentativas:** {cliente.get('tentativas_integracao', 0)}")
            if cliente.get("erro_integracao_ixc"):
                st.write(f"**Último erro:** {cliente['erro_integracao_ixc'][:100]}")
            
            if st.button(f"🔄 Tentar sincronizar agora", key=f"sinc_{cliente['_id']}"):
                with st.spinner("Enviando para IXC..."):
                    sucesso, id_ixc, erro = enviar_cliente_para_ixc(cliente)
                    
                    if sucesso:
                        update_data = {
                            "integrado_ixc": True,
                            "data_integracao_ixc": datetime.now()
                        }
                        if id_ixc and id_ixc not in ["ok", "existente"]:
                            update_data["id_ixc"] = id_ixc
                        
                        clientes_collection.update_one(
                            {"_id": cliente["_id"]},
                            {"$set": update_data, "$unset": {"dados_pendentes_integracao": ""}}
                        )
                        st.success("✅ Sincronizado com sucesso!")
                        st.rerun()
                    else:
                        nova_tentativa = cliente.get("tentativas_integracao", 0) + 1
                        clientes_collection.update_one(
                            {"_id": cliente["_id"]},
                            {"$set": {
                                "tentativas_integracao": nova_tentativa,
                                "ultima_tentativa_integracao": datetime.now(),
                                "erro_integracao_ixc": erro
                            }}
                        )
                        st.error(f"❌ Falha na sincronização: {erro[:150]}")
    
    # Botão para tentar todos
    if st.button("🔄 Tentar sincronizar todos os pendentes"):
        for cliente in pendentes:
            sucesso, id_ixc, erro = enviar_cliente_para_ixc(cliente)
            if sucesso:
                clientes_collection.update_one(
                    {"_id": cliente["_id"]},
                    {"$set": {"integrado_ixc": True, "data_integracao_ixc": datetime.now()}}
                )
        st.success("Sincronização concluída!")
        st.rerun()
