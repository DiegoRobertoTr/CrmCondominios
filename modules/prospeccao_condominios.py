import streamlit as st
import pandas as pd
import numpy as np
import plotly.express as px
import plotly.graph_objects as go
from datetime import datetime, timezone, date
from pymongo import MongoClient, UpdateOne
from pymongo.errors import ServerSelectionTimeoutError, ConnectionFailure
from urllib.parse import quote_plus
import io
import re
import calendar
from bson.objectid import ObjectId
import time
import smtplib
import ssl
from email.mime.multipart import MIMEMultipart
from email.mime.base import MIMEBase
from email.mime.text import MIMEText
from email import encoders

# ==================== CONFIGURAÇÕES DE EMAIL E SENHA ====================
SENHA_ADM = "3540170"
EMAIL_CONFIG = {
    "smtp_user": "comercial1@tracecom.net.br",
    "smtp_password": "Tracecom@mudar",
    "smtp_server": "smtps.uhserver.com",
    "smtp_port": 465,
    "use_tls": False,
}
DESTINATARIOS_BACKUP = [
    "comercial1@tracecom.net.br",
    "pmarques@tracecom.net.br",
    "myjobtracecom@gmail.com",
]
HORARIO_BACKUP_HORA = 18
HORARIO_BACKUP_MIN = 0

# ==================== FUNÇÕES UTILITÁRIAS VETORIZADAS ====================
@st.cache_data
def classificar_fase_vetorizado(fases_series):
    if fases_series is None or len(fases_series) == 0:
        return pd.Series([], dtype='object')
    fases_lower = fases_series.fillna('').astype(str).str.lower().str.strip()

    conditions = {
        '✅ Entramos':        fases_lower.str.contains('entramos|entrada confirmada|projeto aceito|ganhamos|contratado', na=False),
        '💼 Em Negociação':   fases_lower.str.contains('em negociação|negociando|tratativa|proposta|estudo|análise|avaliação', na=False),
        '📢 Lançamento':      fases_lower.str.contains('lançamento|lancamento|vendas|grupo em formação|pré-venda', na=False),
        '🚧 Início de Obra':  fases_lower.str.contains('início de obra|inicio de obra|inicial|fundação|estrutura|começando', na=False),
        '🔨 Obra em Andamento': fases_lower.str.contains('obra em andamento|andamento|intermediário|intermediario|em construção|50%|60%|70%|80%', na=False),
        '🏁 Final de Obra':   fases_lower.str.contains('final de obra|fase final|acabamento|estágio final|estagio final|terminando', na=False),
        '🎉 Entregue':        fases_lower.str.contains('entregue|entregues|finalizado|concluído|concluido', na=False),
        '🏡 Pronto Para Morar': fases_lower.str.contains('pronto para morar|pronto pra morar|habite-se|disponível', na=False),
        '📅 Futuro Lançamento': fases_lower.str.contains('futuro|planejado|terreno|futuro lançamento|previsão|previsto', na=False),
        '❌ Não Entramos':    fases_lower.str.contains('não entramos|nao entramos|perdido|embargado|sem viabilidade|não autorizado|descartado', na=False),
    }

    resultado = pd.Series('💼 Em Negociação', index=fases_series.index, dtype='object')
    for fase, cond in conditions.items():
        resultado[cond] = fase
    return resultado

@st.cache_data
def extrair_previsao_entrega_vetorizado(viabilidade_series):
    if viabilidade_series is None or len(viabilidade_series) == 0:
        return pd.Series([], dtype='datetime64[ns]')
    viabilidade_str = viabilidade_series.fillna('').astype(str)
    resultado = pd.Series(pd.NaT, index=viabilidade_str.index, dtype='datetime64[ns]')

    try:
        data_encontrada = viabilidade_str.str.extract(r'(\d{2}/\d{2}/\d{4})', expand=False)
        mask = data_encontrada.notna()
        if mask.any():
            resultado[mask] = pd.to_datetime(data_encontrada[mask], format='%d/%m/%Y', errors='coerce')

        mask_restante = resultado.isna()
        if mask_restante.any():
            data2 = viabilidade_str[mask_restante].str.extract(r'(\d{2}/\d{2}/\d{2})', expand=False)
            mask2 = data2.notna()
            if mask2.any():
                idx = resultado[mask_restante].index[mask2]
                resultado.loc[idx] = pd.to_datetime(data2[mask2], format='%d/%m/%y', errors='coerce')

        mask_restante = resultado.isna()
        if mask_restante.any():
            data3 = viabilidade_str[mask_restante].str.extract(r'(\d{4}-\d{2}-\d{2})', expand=False)
            mask3 = data3.notna()
            if mask3.any():
                idx = resultado[mask_restante].index[mask3]
                resultado.loc[idx] = pd.to_datetime(data3[mask3], format='%Y-%m-%d', errors='coerce')

        mask_restante = resultado.isna()
        if mask_restante.any():
            data4 = viabilidade_str[mask_restante].str.extract(r'(\d{2}/\d{4})', expand=False)
            mask4 = data4.notna()
            if mask4.any():
                idx = resultado[mask_restante].index[mask4]
                resultado.loc[idx] = pd.to_datetime('01/' + data4[mask4], format='%d/%m/%Y', errors='coerce')

    except Exception as e:
        st.warning(f"Aviso ao processar datas: {e}.")
    return resultado

@st.cache_data
def calcular_prioridade_vetorizado(df):
    if df.empty:
        return pd.Series([], dtype='object')
    fase = df['FASE_CLASSIFICADA'].fillna('')
    prioridade = pd.Series('⚪ Baixa', index=df.index)

    prioridade[fase == '✅ Entramos']  = '🟢 Ação Imediata'
    prioridade[fase == '💼 Em Negociação'] = '🟠 Alta Prioridade'
    prioridade[fase.isin(['🎉 Entregue', '🏡 Pronto Para Morar'])] = '🟡 Acompanhamento'

    if 'DIAS_RESTANTES' in df.columns:
        dias_num = pd.to_numeric(df['DIAS_RESTANTES'], errors='coerce')
        mask_final = fase == '🏁 Final de Obra'
        if mask_final.any():
            prioridade[mask_final & (dias_num <= 90)]  = '🔴 Urgente'
            prioridade[mask_final & (dias_num > 90) & (dias_num <= 180)] = '🟠 Alta'
            prioridade[mask_final & (dias_num > 180)] = '🟡 Média'

        mask_obra = fase.isin(['🔨 Obra em Andamento', '🚧 Início de Obra'])
        if mask_obra.any():
            prioridade[mask_obra & (dias_num <= 365)] = '🟠 Alta'
            prioridade[mask_obra & (dias_num > 365)]  = '🟡 Média'

    prioridade[fase.isin(['📢 Lançamento', '📅 Futuro Lançamento'])] = '🔵 Planejamento'
    prioridade[fase == '❌ Não Entramos'] = '⚪ Arquivado'
    return prioridade

@st.cache_data
def calcular_dias_para_entrega_vetorizado(previsao_series):
    if previsao_series is None or len(previsao_series) == 0:
        return pd.Series([], dtype='float64')
    hoje = datetime.now().replace(tzinfo=None)
    previsao_dt = pd.to_datetime(previsao_series, errors='coerce')
    return (previsao_dt - pd.Timestamp(hoje)).dt.days

# ==================== CONFIGURAÇÃO MONGODB ====================
@st.cache_resource
def init_mongo():
    try:
        uri = st.secrets.get("MONGO_URI")
        if not uri:
            mongo_cfg = st.secrets.get("mongo", {})
            username = mongo_cfg.get("MONGO_USERNAME")
            password = mongo_cfg.get("MONGO_PASSWORD")
            cluster = mongo_cfg.get("MONGO_CLUSTER_URL")
            database = mongo_cfg.get("MONGO_DATABASE", "tracecom_crm")
            if not all([username, password, cluster]):
                st.error("❌ Credenciais MongoDB incompletas nos Secrets.")
                st.stop()
            uri = f"mongodb+srv://{username}:{quote_plus(password)}@{cluster}/{database}?retryWrites=true&w=majority"
        
        client = MongoClient(uri, serverSelectionTimeoutMS=5000, connectTimeoutMS=5000)
        client.admin.command('ping')
        database_name = st.secrets.get("mongo", {}).get("MONGO_DATABASE", "tracecom_crm")
        return client[database_name]
    except (ServerSelectionTimeoutError, ConnectionFailure) as e:
        st.error(f"❌ Falha ao conectar ao MongoDB:\n`{type(e).__name__}: {e}`")
        st.stop()
    except Exception as e:
        st.error(f"❌ Erro inesperado ao conectar: {type(e).__name__}: {e}")
        st.stop()

# ==================== FUNÇÕES DE BACKUP E EMAIL ====================
def gerar_excel_tratado(df_prospeccao):
    df_construtoras = analisar_por_construtora(df_prospeccao)
    df_zonas = analisar_por_zona(df_prospeccao)
    return exportar_prospeccao_excel(df_prospeccao, df_construtoras, df_zonas)

def gerar_excel_reimportavel(df_prospeccao):
    COLUNAS_ORIGINAIS = [
        'Data da Atualização', 'Região', 'BAIRRO', 'ENDEREÇO',
        'NOME', 'BLOCO', 'APTO', 'CONSTRUTORA',
        'ESTÁGIO', 'VIABILIDADE', 'OBS', 'Previsão de Entrega',
    ]
    df_export = df_prospeccao.copy()
    if 'FASE_ORIGINAL' in df_export.columns:
        df_export['ESTÁGIO'] = df_export['FASE_ORIGINAL']

    for col_data in ['Data da Atualização', 'Previsão de Entrega', 'PREVISAO_ENTREGA']:
        if col_data in df_export.columns:
            df_export[col_data] = pd.to_datetime(df_export[col_data], errors='coerce')
            mask = df_export[col_data].notna()
            df_export.loc[mask, col_data] = df_export.loc[mask, col_data].dt.strftime('%d/%m/%Y')
            df_export.loc[~mask, col_data] = ''

    for col in COLUNAS_ORIGINAIS:
        if col not in df_export.columns:
            df_export[col] = ''

    df_reimport = df_export[COLUNAS_ORIGINAIS].copy().fillna('')
    for col in df_reimport.select_dtypes(include='object').columns:
        df_reimport[col] = df_reimport[col].replace(['nan', 'NaT', 'None', 'nat', 'NaN'], '')

    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        df_reimport.to_excel(writer, sheet_name='Prospecção', index=False)
    output.seek(0)
    return output

def enviar_email_backup(arquivo_tratado: bytes, arquivo_reimportavel: bytes,
                        total_projetos: int, nome_arquivo_original: str,
                        motivo: str = "importação de planilha") -> tuple[bool, str]:
    timestamp_str = datetime.now().strftime('%d/%m/%Y às %H:%M')
    data_str = datetime.now().strftime('%Y%m%d_%H%M%S')
    assunto = f"[Tracecom] Backup Prospecção Condomínios — {datetime.now().strftime('%d/%m/%Y %H:%M')}"

    corpo_html = f"""
    <html><body style="font-family: Arial, sans-serif; color: #333;">
      <h2 style="color: #1a5276;">🏢 Backup — Prospecção de Condomínios</h2>
      <p>Olá,</p>
      <p>Este backup foi gerado automaticamente em <strong>{timestamp_str}</strong>
        por <strong>{motivo}</strong>.</p>
      <p>Seguem em anexo os dois arquivos de backup:</p>
      <table style="border-collapse:collapse; width:100%; margin:16px 0;">
        <tr style="background:#1a5276; color:#fff;">
          <th style="padding:8px 12px; text-align:left;">Arquivo</th>
          <th style="padding:8px 12px; text-align:left;">Descrição</th>
        </tr>
        <tr style="background:#eaf4fb;">
          <td style="padding:8px 12px;"><strong>backup_tratado_{data_str}.xlsx</strong></td>
          <td style="padding:8px 12px;">Dados tratados com abas por fase, análises e resumo executivo</td>
        </tr>
        <tr>
          <td style="padding:8px 12px;"><strong>backup_reimportavel_{data_str}.xlsx</strong></td>
          <td style="padding:8px 12px;">Formato original — pode ser reimportado diretamente pelo sistema</td>
        </tr>
      </table>
      <p><strong>Referência:</strong> {nome_arquivo_original} <br>
         <strong>Total de projetos:</strong> {total_projetos:,}</p>
      <hr style="border:none; border-top:1px solid #ddd; margin:24px 0;">
      <p style="font-size:12px; color:#888;">Mensagem automática — Sistema de Prospecção Tracecom</p>
    </body></html>
    """

    try:
        msg = MIMEMultipart('mixed')
        msg['Subject'] = assunto
        msg['From'] = EMAIL_CONFIG["smtp_user"]
        msg['To'] = ", ".join(DESTINATARIOS_BACKUP)
        msg.attach(MIMEText(corpo_html, 'html', 'utf-8'))

        part1 = MIMEBase('application', 'vnd.openxmlformats-officedocument.spreadsheetml.sheet')
        part1.set_payload(arquivo_tratado)
        encoders.encode_base64(part1)
        part1.add_header('Content-Disposition', 'attachment', filename=f"backup_tratado_{data_str}.xlsx")
        msg.attach(part1)

        part2 = MIMEBase('application', 'vnd.openxmlformats-officedocument.spreadsheetml.sheet')
        part2.set_payload(arquivo_reimportavel)
        encoders.encode_base64(part2)
        part2.add_header('Content-Disposition', 'attachment', filename=f"backup_reimportavel_{data_str}.xlsx")
        msg.attach(part2)

        context = ssl.create_default_context()
        with smtplib.SMTP_SSL(EMAIL_CONFIG["smtp_server"], EMAIL_CONFIG["smtp_port"], context=context) as servidor:
            servidor.login(EMAIL_CONFIG["smtp_user"], EMAIL_CONFIG["smtp_password"])
            servidor.sendmail(EMAIL_CONFIG["smtp_user"], DESTINATARIOS_BACKUP, msg.as_bytes())

        return True, f"✅ Backup enviado com sucesso para {len(DESTINATARIOS_BACKUP)} destinatário(s)."
    except smtplib.SMTPAuthenticationError:
        return False, "❌ Falha de autenticação SMTP. Verifique usuário/senha."
    except smtplib.SMTPConnectError as e:
        return False, f"❌ Erro de conexão SMTP: {e}"
    except Exception as e:
        return False, f"❌ Erro ao enviar email: {type(e).__name__}: {e}"

# ==================== FUNÇÕES DE CONTROLE DE BACKUP DIÁRIO ====================
def marcar_backup_pendente(db, motivo: str = "edição de registros"):
    col = db["prospeccao_backup_flags"]
    now = datetime.now().replace(tzinfo=None)
    col.update_one(
        {"_id": "backup_flag"},
        {"$set": {"pending": True, "ultimo_motivo": motivo, "ultima_edicao_em": now},
         "$setOnInsert": {"primeira_edicao_em": now}},
        upsert=True,
    )

def obter_flag_backup(db) -> dict:
    col = db["prospeccao_backup_flags"]
    doc = col.find_one({"_id": "backup_flag"})
    return doc or {}

def registrar_backup_enviado(db):
    col = db["prospeccao_backup_flags"]
    col.update_one(
        {"_id": "backup_flag"},
        {"$set": {"pending": False, "ultimo_backup_em": datetime.now().replace(tzinfo=None)}},
        upsert=True,
    )

def verificar_e_disparar_backup_diario(db, df_prospeccao) -> tuple[bool, str]:
    flag = obter_flag_backup(db)
    if not flag.get("pending", False):
        return False, ""

    agora = datetime.now()
    hora_limite = agora.replace(hour=HORARIO_BACKUP_HORA, minute=HORARIO_BACKUP_MIN, second=0, microsecond=0)

    ultimo_backup = flag.get("ultimo_backup_em")
    ja_enviou_hoje = (ultimo_backup is not None and ultimo_backup.date() == agora.date()) if ultimo_backup else False

    if agora < hora_limite or ja_enviou_hoje:
        return False, ""

    motivo = flag.get("ultimo_motivo", "backup diário automático")
    try:
        excel_tratado = gerar_excel_tratado(df_prospeccao)
        excel_reimportavel = gerar_excel_reimportavel(df_prospeccao)

        sucesso, msg = enviar_email_backup(
            arquivo_tratado=excel_tratado.getvalue(),
            arquivo_reimportavel=excel_reimportavel.getvalue(),
            total_projetos=len(df_prospeccao),
            nome_arquivo_original="backup_diario",
            motivo=motivo,
        )

        if sucesso:
            registrar_backup_enviado(db)
            return True, f"📧 Backup diário enviado automaticamente ({motivo})."
        else:
            return False, msg
    except Exception as e:
        return False, f"❌ Erro no backup diário: {e}"

def executar_backup_manual(db, df_prospeccao, motivo: str = "envio manual pelo administrador") -> tuple[bool, str]:
    try:
        excel_tratado = gerar_excel_tratado(df_prospeccao)
        excel_reimportavel = gerar_excel_reimportavel(df_prospeccao)
        sucesso, msg = enviar_email_backup(
            arquivo_tratado=excel_tratado.getvalue(),
            arquivo_reimportavel=excel_reimportavel.getvalue(),
            total_projetos=len(df_prospeccao),
            nome_arquivo_original="backup_manual",
            motivo=motivo,
        )
        if sucesso:
            registrar_backup_enviado(db)
        return sucesso, msg
    except Exception as e:
        return False, f"❌ Erro no backup manual: {e}"

# ==================== FUNÇÕES DE BANCO DE DADOS ====================
def save_prospeccao_data(db, df_prospeccao, metadata):
    collection = db["prospeccao_condominios"]
    meta_collection = db["prospeccao_meta"]
    batch_id = metadata["batch_id"]
    ultimo_meta = meta_collection.find_one(sort=[("timestamp", -1)])
    if ultimo_meta:
        batch_anterior = ultimo_meta.get("batch_id")
        if batch_anterior and batch_anterior != batch_id:
            removidos = collection.delete_many({"_import_batch": batch_anterior})
            if removidos.deleted_count > 0:
                st.info(f"🗑️ Removidos {removidos.deleted_count} registros do batch anterior automaticamente.")

    df_para_salvar = df_prospeccao.copy()
    for col in ['Prazo Medio', 'Prazo_Medio', 'prazo_medio', 'Prazo médio']:
        if col in df_para_salvar.columns:
            df_para_salvar = df_para_salvar.drop(columns=[col])

    for col_data in ['Data da Atualização', 'Previsão de Entrega', 'PREVISAO_ENTREGA']:
        if col_data in df_para_salvar.columns:
            df_para_salvar[col_data] = pd.to_datetime(df_para_salvar[col_data], errors='coerce')

    for col in ['VIABILIDADE', 'OBS', 'ESTÁGIO', 'FASE_ORIGINAL', 'FASE_CLASSIFICADA',
                'PRIORIDADE', 'CONSTRUTORA', 'NOME', 'BAIRRO', 'Região', 'ENDEREÇO', 'BLOCO']:
        if col in df_para_salvar.columns:
            df_para_salvar[col] = df_para_salvar[col].astype(str).fillna('')
            df_para_salvar[col] = df_para_salvar[col].replace(['nan', 'NaT', 'None', 'nat', 'NaN', ''], '')

    if 'APTO' in df_para_salvar.columns:
        df_para_salvar['APTO'] = pd.to_numeric(df_para_salvar['APTO'], errors='coerce').fillna(0).astype(int)
    if 'DIAS_RESTANTES' in df_para_salvar.columns:
        df_para_salvar['DIAS_RESTANTES'] = pd.to_numeric(df_para_salvar['DIAS_RESTANTES'], errors='coerce')
    if 'BLOCO' in df_para_salvar.columns:
        df_para_salvar['BLOCO'] = pd.to_numeric(df_para_salvar['BLOCO'], errors='coerce').fillna(0).astype(int)

    df_para_salvar["_import_timestamp"] = datetime.now().replace(tzinfo=None)
    df_para_salvar["_import_batch"] = batch_id
    df_para_salvar = df_para_salvar.replace({pd.NaT: None, np.nan: None, float('inf'): None, float('-inf'): None})

    docs = df_para_salvar.to_dict('records')
    if docs:
        for i in range(0, len(docs), 500):
            collection.insert_many(docs[i:i+500])

    meta_collection.delete_one({"batch_id": batch_id})
    meta_collection.insert_one({
        "batch_id": batch_id,
        "timestamp": datetime.now().replace(tzinfo=None),
        "total_projetos": len(df_prospeccao),
        "fases": metadata.get("fases", {}),
        "construtoras": metadata.get("construtoras", []),
    })
    return True

def clear_prospeccao_data(db, batch_id=None):
    collection = db["prospeccao_condominios"]
    meta_collection = db["prospeccao_meta"]
    if batch_id:
        result = collection.delete_many({"_import_batch": batch_id})
        meta_collection.delete_many({"batch_id": batch_id})
        return result.deleted_count
    else:
        result = collection.delete_many({})
        meta_collection.delete_many({})
        return result.deleted_count

def limpar_todas_duplicatas(db):
    collection = db["prospeccao_condominios"]
    meta_collection = db["prospeccao_meta"]
    total_antes = collection.count_documents({})
    if total_antes > 0:
        collection.delete_many({})
        meta_collection.delete_many({})
        return total_antes
    return 0

def verificar_duplicatas(db):
    collection = db["prospeccao_condominios"]
    pipeline = [
        {"$group": {"_id": "$_import_batch", "count": {"$sum": 1}, "timestamp": {"$max": "$_import_timestamp"}}},
        {"$sort": {"timestamp": -1}},
    ]
    batches = list(collection.aggregate(pipeline))
    total = collection.count_documents({})
    return total, len(batches)

def update_records_batch_vectorized(db, df_original, df_editado, colunas_para_comparar):
    """Atualiza registros com segurança contra NaN do data_editor e persiste colunas calculadas"""
    try:
        mascaras_alteracao = {}
        for col in colunas_para_comparar:
            if col in df_original.columns and col in df_editado.columns:
                mascaras_alteracao[col] = df_original[col].fillna('') != df_editado[col].fillna('')
        if not mascaras_alteracao:
            return 0

        linhas_com_alteracao = pd.DataFrame(mascaras_alteracao).any(axis=1)
        if not linhas_com_alteracao.any():
            return 0

        df_orig_alt = df_original[linhas_com_alteracao].copy()
        df_edit_alt = df_editado[linhas_com_alteracao].copy()
        ids_alterados = df_orig_alt['_id'].values

        # 🔑 RESTAURAR valores originais onde o editor retornou NaN (células não editadas)
        for col in df_edit_alt.columns:
            mask = df_edit_alt[col].isna() & df_orig_alt[col].notna()
            df_edit_alt.loc[mask, col] = df_orig_alt.loc[mask, col]

        # 🔧 FORÇAR recálculo das colunas derivadas para garantir consistência
        if 'ESTÁGIO' in df_edit_alt.columns:
            df_edit_alt['FASE_CLASSIFICADA'] = classificar_fase_vetorizado(df_edit_alt['ESTÁGIO'])
        if 'VIABILIDADE' in df_edit_alt.columns:
            df_edit_alt['PREVISAO_ENTREGA'] = extrair_previsao_entrega_vetorizado(df_edit_alt['VIABILIDADE'])
        if 'PREVISAO_ENTREGA' in df_edit_alt.columns:
            df_edit_alt['DIAS_RESTANTES'] = calcular_dias_para_entrega_vetorizado(df_edit_alt['PREVISAO_ENTREGA'])

        df_temp = df_edit_alt.copy()
        if 'FASE_CLASSIFICADA' not in df_temp.columns and 'ESTÁGIO' in df_temp.columns:
            df_temp['FASE_CLASSIFICADA'] = classificar_fase_vetorizado(df_temp['ESTÁGIO'])
        if 'DIAS_RESTANTES' not in df_temp.columns and 'PREVISAO_ENTREGA' in df_temp.columns:
            df_temp['DIAS_RESTANTES'] = calcular_dias_para_entrega_vetorizado(df_temp['PREVISAO_ENTREGA'])
        df_temp['PRIORIDADE'] = calcular_prioridade_vetorizado(df_temp)
        df_edit_alt['PRIORIDADE'] = df_temp['PRIORIDADE']

        bulk_operations = []
        collection = db["prospeccao_condominios"]

        for idx, record_id in enumerate(ids_alterados):
            updates = {}
            
            # 1. Colunas editáveis pelo usuário
            for col in colunas_para_comparar:
                if col in df_edit_alt.columns:
                    v_edit = df_edit_alt[col].iloc[idx]
                    v_orig = df_orig_alt[col].iloc[idx] if col in df_orig_alt.columns else None
                    if pd.isna(v_edit): continue
                    if str(v_orig) != str(v_edit):
                        updates[col] = None if (v_edit == '') else v_edit

            # 2. Colunas calculadas (usar sempre o valor recalculado)
            for col in ['FASE_CLASSIFICADA', 'PREVISAO_ENTREGA', 'DIAS_RESTANTES', 'PRIORIDADE']:
                if col in df_edit_alt.columns:
                    val_new = df_edit_alt[col].iloc[idx]
                    val_old = df_orig_alt[col].iloc[idx] if col in df_orig_alt.columns else None
                    if pd.isna(val_new): continue
                    if str(val_new) != str(val_old):
                        updates[col] = None if (val_new == '') else val_new

            if updates:
                oid = ObjectId(record_id) if isinstance(record_id, str) else record_id
                bulk_operations.append(UpdateOne({"_id": oid}, {"$set": updates}))

        if bulk_operations:
            return collection.bulk_write(bulk_operations).modified_count
        return 0

    except Exception as e:
        st.error(f"Erro na atualização em lote: {e}")
        import traceback
        st.code(traceback.format_exc())
        return 0

@st.cache_data
def load_latest_prospeccao(_db):
    meta = _db["prospeccao_meta"].find_one(sort=[("timestamp", -1)])
    if not meta:
        return None, None
    cursor = _db["prospeccao_condominios"].find({"_import_batch": meta["batch_id"]})
    df = pd.DataFrame(list(cursor))
    if "_id" in df.columns:
        df["_id"] = df["_id"].astype(str)
    else:
        df["_id"] = [str(i) for i in range(len(df))]
    return df, meta

def insert_new_record(db, new_data):
    try:
        collection = db["prospeccao_condominios"]
        doc = new_data.copy()
        if "ESTÁGIO" in doc:
            doc["FASE_CLASSIFICADA"] = classificar_fase_vetorizado(pd.Series([doc["ESTÁGIO"]])).iloc[0]
        if "VIABILIDADE" in doc:
            doc["PREVISAO_ENTREGA"] = extrair_previsao_entrega_vetorizado(pd.Series([doc["VIABILIDADE"]])).iloc[0]
        if doc.get("PREVISAO_ENTREGA"):
            doc["DIAS_RESTANTES"] = calcular_dias_para_entrega_vetorizado(pd.Series([doc["PREVISAO_ENTREGA"]])).iloc[0]

        temp_df = pd.DataFrame([doc])
        doc["PRIORIDADE"] = calcular_prioridade_vetorizado(temp_df).iloc[0]
        doc["_import_timestamp"] = datetime.now().replace(tzinfo=None)
        doc["_import_batch"] = "manual_entry"

        for key, value in list(doc.items()):
            if isinstance(value, (pd.Timestamp, datetime)):
                doc[key] = None if pd.isna(value) else value
            elif isinstance(value, float) and pd.isna(value):
                doc[key] = None

        collection.insert_one(doc)
        return True
    except Exception as e:
        st.error(f"Erro ao inserir: {e}")
        return False

# ==================== FUNÇÕES DE ANÁLISE ====================
@st.cache_data
def analisar_por_construtora(df_prospeccao):
    if df_prospeccao.empty or "CONSTRUTORA" not in df_prospeccao.columns:
        return pd.DataFrame()
    df_copy = df_prospeccao.copy()
    if "APTO" in df_copy.columns:
        df_copy["APTO"] = pd.to_numeric(df_copy["APTO"], errors='coerce')
    stats = df_copy.groupby("CONSTRUTORA").agg(
        total_projetos=("NOME", "count"),
        total_apartamentos=("APTO", "sum"),
        projetos_entramos=("FASE_CLASSIFICADA", lambda x: (x == "✅ Entramos").sum()),
        projetos_negociacao=("FASE_CLASSIFICADA", lambda x: (x == "💼 Em Negociação").sum()),
        projetos_lancamento=("FASE_CLASSIFICADA", lambda x: (x == "📢 Lançamento").sum()),
        projetos_inicio_obra=("FASE_CLASSIFICADA", lambda x: (x == "🚧 Início de Obra").sum()),
        projetos_andamento=("FASE_CLASSIFICADA", lambda x: (x == "🔨 Obra em Andamento").sum()),
        projetos_final_obra=("FASE_CLASSIFICADA", lambda x: (x == "🏁 Final de Obra").sum()),
        projetos_entregue=("FASE_CLASSIFICADA", lambda x: (x == "🎉 Entregue").sum()),
        projetos_pronto_morar=("FASE_CLASSIFICADA", lambda x: (x == "🏡 Pronto Para Morar").sum()),
        projetos_futuro=("FASE_CLASSIFICADA", lambda x: (x == "📅 Futuro Lançamento").sum()),
        projetos_nao_entramos=("FASE_CLASSIFICADA", lambda x: (x == "❌ Não Entramos").sum()),
    ).reset_index()

    stats["percentual_entregue"] = (stats["projetos_entregue"] / stats["total_projetos"] * 100).round(1)
    stats["percentual_em_obra"] = ((stats["projetos_inicio_obra"] + stats["projetos_andamento"] + stats["projetos_final_obra"]) / stats["total_projetos"] * 100).round(1)
    stats["percentual_oportunidades"] = ((stats["projetos_lancamento"] + stats["projetos_futuro"] + stats["projetos_negociacao"]) / stats["total_projetos"] * 100).round(1)
    return stats.sort_values("total_projetos", ascending=False).reset_index(drop=True)

@st.cache_data
def analisar_por_zona(df_prospeccao):
    if df_prospeccao.empty:
        return pd.DataFrame()
    col_zona = "Região" if "Região" in df_prospeccao.columns else "ZONA" if "ZONA" in df_prospeccao.columns else None
    if not col_zona:
        return pd.DataFrame()
    df_copy = df_prospeccao.copy()
    if "APTO" in df_copy.columns:
        df_copy["APTO"] = pd.to_numeric(df_copy["APTO"], errors='coerce')

    stats = df_copy.groupby(col_zona).agg(
        total_projetos=("NOME", "count"),
        total_apartamentos=("APTO", "sum"),
        projetos_em_obra=("FASE_CLASSIFICADA", lambda x: x.isin(["🚧 Início de Obra", "🔨 Obra em Andamento", "🏁 Final de Obra"]).sum()),
        projetos_entregue=("FASE_CLASSIFICADA", lambda x: x.isin(["🎉 Entregue", "🏡 Pronto Para Morar"]).sum()),
        oportunidades=("FASE_CLASSIFICADA", lambda x: x.isin(["📢 Lançamento", "📅 Futuro Lançamento", "💼 Em Negociação", "✅ Entramos"]).sum()),
    ).reset_index()

    stats["percentual_em_obra"] = (stats["projetos_em_obra"] / stats["total_projetos"] * 100).round(1)
    stats["percentual_entregue"] = (stats["projetos_entregue"] / stats["total_projetos"] * 100).round(1)
    stats["percentual_oportunidades"] = (stats["oportunidades"] / stats["total_projetos"] * 100).round(1)
    return stats.sort_values("total_projetos", ascending=False).reset_index(drop=True)

@st.cache_data
def timeline_entregas(df_prospeccao):
    if "PREVISAO_ENTREGA" not in df_prospeccao.columns:
        return pd.DataFrame()
    df_t = df_prospeccao.copy()
    df_t["PREVISAO_ENTREGA"] = pd.to_datetime(df_t["PREVISAO_ENTREGA"], errors='coerce')
    df_t = df_t[df_t["PREVISAO_ENTREGA"].notna()].copy()
    if df_t.empty:
        return df_t
    df_t["DIAS_RESTANTES"] = calcular_dias_para_entrega_vetorizado(df_t["PREVISAO_ENTREGA"])
    df_t["ANO_ENTREGA"] = df_t["PREVISAO_ENTREGA"].dt.year
    df_t["MES_ENTREGA"] = df_t["PREVISAO_ENTREGA"].dt.to_period('M')
    return df_t.sort_values("PREVISAO_ENTREGA")

# ==================== EXPORTAÇÃO EXCEL (SISTEMA) ====================
def exportar_prospeccao_excel(df_prospeccao, df_construtoras, df_zonas):
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        resumo = {
            'Métrica': [
                'Total de Projetos', 'Total de Apartamentos', 'Projetos em Obra',
                'Projetos Entregues', 'Projetos "Entramos"', 'Projetos "Em Negociação"',
                'Oportunidades (Lançamento/Futuro)', 'Construtoras Ativas', 'Regiões Atendidas',
            ],
            'Valor': [
                len(df_prospeccao),
                df_prospeccao['APTO'].fillna(0).sum() if 'APTO' in df_prospeccao.columns else 0,
                len(df_prospeccao[df_prospeccao['FASE_CLASSIFICADA'].isin(['🚧 Início de Obra', '🔨 Obra em Andamento', '🏁 Final de Obra'])]) if 'FASE_CLASSIFICADA' in df_prospeccao.columns else 0,
                len(df_prospeccao[df_prospeccao['FASE_CLASSIFICADA'].isin(['🎉 Entregue', '🏡 Pronto Para Morar'])]) if 'FASE_CLASSIFICADA' in df_prospeccao.columns else 0,
                len(df_prospeccao[df_prospeccao['FASE_CLASSIFICADA'] == '✅ Entramos']) if 'FASE_CLASSIFICADA' in df_prospeccao.columns else 0,
                len(df_prospeccao[df_prospeccao['FASE_CLASSIFICADA'] == '💼 Em Negociação']) if 'FASE_CLASSIFICADA' in df_prospeccao.columns else 0,
                len(df_prospeccao[df_prospeccao['FASE_CLASSIFICADA'].isin(['📢 Lançamento', '📅 Futuro Lançamento'])]) if 'FASE_CLASSIFICADA' in df_prospeccao.columns else 0,
                df_prospeccao['CONSTRUTORA'].nunique() if 'CONSTRUTORA' in df_prospeccao.columns else 0,
                df_prospeccao['Região'].nunique() if 'Região' in df_prospeccao.columns else (df_prospeccao['ZONA'].nunique() if 'ZONA' in df_prospeccao.columns else 0),
            ],
        }
        pd.DataFrame(resumo).to_excel(writer, sheet_name='📊 Resumo Executivo', index=False)
        df_prospeccao.to_excel(writer, sheet_name='📋 Completo', index=False)

        fases_map = {
            '✅ Entramos': '00_Entramos_Destaque', '💼 Em Negociação': '01_Em_Negociacao',
            '📢 Lançamento': '02_Lancamento', '🚧 Início de Obra': '03_Inicio_Obra',
            '🔨 Obra em Andamento': '04_Andamento', '🏁 Final de Obra': '05_Final_Obra',
            '🎉 Entregue': '06_Entregue', '🏡 Pronto Para Morar': '07_Pronto_Morar',
            '📅 Futuro Lançamento': '08_Futuro_Lancamento', '❌ Não Entramos': '09_Nao_Entramos',
        }
        cols_base = ['NOME', 'CONSTRUTORA', 'BAIRRO',
                     'Região' if 'Região' in df_prospeccao.columns else 'ZONA',
                     'ENDEREÇO', 'BLOCO', 'APTO', 'FASE_CLASSIFICADA', 'PRIORIDADE']

        for fase, nome_aba in fases_map.items():
            df_fase = df_prospeccao[df_prospeccao['FASE_CLASSIFICADA'] == fase].copy()
            if not df_fase.empty:
                extras = ['VIABILIDADE', 'OBS', 'PREVISAO_ENTREGA', 'DIAS_RESTANTES', 'FASE_ORIGINAL']
                cols_final = [c for c in cols_base if c in df_fase.columns] + [c for c in extras if c in df_fase.columns]
                df_exp = df_fase[cols_final].copy()
                if 'PREVISAO_ENTREGA' in df_exp.columns:
                    mask = df_exp['PREVISAO_ENTREGA'].notna()
                    df_exp.loc[mask, 'PREVISAO_ENTREGA'] = pd.to_datetime(df_exp.loc[mask, 'PREVISAO_ENTREGA']).dt.strftime('%d/%m/%Y')
                    df_exp.loc[~mask, 'PREVISAO_ENTREGA'] = ''
                df_exp.to_excel(writer, sheet_name=nome_aba[:31], index=False)

        if not df_construtoras.empty:
            df_construtoras.to_excel(writer, sheet_name='10_Por_Construtora', index=False)
        if not df_zonas.empty:
            df_zonas.to_excel(writer, sheet_name='11_Por_Regiao', index=False)

    output.seek(0)
    return output

# ==================== INTERFACE STREAMLIT ====================
def render_prospeccao_condominios():
    st.title("🏢 Prospecção de Condomínios")
    st.markdown("Acompanhamento de fases de construção por construtora e oportunidades de mercado")
    db = init_mongo()
    st.markdown("---")

    # ==================== FERRAMENTAS ADMINISTRATIVAS COM SENHA ====================
    with st.expander("🔐 FERRAMENTAS DE MANUTENÇÃO (Administrador)", expanded=False):
        if not st.session_state.get("adm_autenticado", False):
            st.warning("🔒 Área restrita. Informe a senha de administrador para continuar.")
            col_pw, col_btn = st.columns([3, 1])
            with col_pw:
                senha_input = st.text_input("Senha", type="password", key="input_senha_adm", placeholder="Digite a senha de acesso")
            with col_btn:
                st.markdown("<div style='margin-top:28px'></div>", unsafe_allow_html=True)
                if st.button("🔓 Entrar", key="btn_entrar_adm", use_container_width=True):
                    if senha_input == SENHA_ADM:
                        st.session_state["adm_autenticado"] = True
                        st.rerun()
                    else:
                        st.error("❌ Senha incorreta.")
            return_early = not st.session_state.get("adm_autenticado", False)
        else:
            return_early = False

        if not return_early:
            col_logout, _ = st.columns([1, 4])
            with col_logout:
                if st.button("🔒 Sair (bloquear)", key="btn_logout_adm"):
                    st.session_state["adm_autenticado"] = False
                    st.rerun()

            st.warning("⚠️ Use estas ferramentas com cuidado! Elas removem dados permanentemente.")
            col_limpeza1, col_limpeza2, col_limpeza3 = st.columns(3)

            with col_limpeza1:
                if st.button("🔍 Verificar Duplicatas", key="btn_verificar"):
                    total, num_batches = verificar_duplicatas(db)
                    st.metric("Total de registros no banco", f"{total:,}")
                    st.metric("Número de batches", num_batches)
                    if num_batches > 1:
                        st.error(f"⚠️ {num_batches} batches encontrados. Isso indica duplicação!")

            with col_limpeza2:
                if st.button("🗑️ LIMPAR TODOS OS DADOS", key="btn_limpar_tudo"):
                    st.session_state['confirmar_limpeza_total'] = True

            with col_limpeza3:
                if st.button("🧹 Manter Apenas Último Lote", key="btn_manter_ultimo"):
                    st.session_state['confirmar_manter_ultimo'] = True

            if st.session_state.get('confirmar_limpeza_total', False):
                st.error("🔴 CONFIRMAÇÃO NECESSÁRIA!")
                total_atual, _ = verificar_duplicatas(db)
                st.warning(f"Isso irá remover TODOS os {total_atual:,} registros. Esta ação NÃO pode ser desfeita!")
                col_c1, col_c2 = st.columns(2)
                with col_c1:
                    if st.button("✅ SIM, REMOVER TUDO", key="confirmar_sim"):
                        removidos = limpar_todas_duplicatas(db)
                        st.success(f"✅ {removidos:,} registros removidos com sucesso!")
                        st.session_state['confirmar_limpeza_total'] = False
                        st.cache_data.clear()
                        st.session_state.pop("df_prospeccao_cached", None)
                        st.rerun()
                with col_c2:
                    if st.button("❌ Cancelar", key="confirmar_nao"):
                        st.session_state['confirmar_limpeza_total'] = False
                        st.rerun()

            if st.session_state.get('confirmar_manter_ultimo', False):
                st.info("ℹ️ Isso irá manter apenas o batch mais recente e remover os antigos.")
                col_c3, col_c4 = st.columns(2)
                with col_c3:
                    if st.button("✅ Sim, manter apenas último", key="manter_sim"):
                        meta_col = db["prospeccao_meta"]
                        ultimo = meta_col.find_one(sort=[("timestamp", -1)])
                        if ultimo:
                            ultimo_batch = ultimo.get("batch_id")
                            res = db["prospeccao_condominios"].delete_many({"_import_batch": {"$ne": ultimo_batch}})
                            meta_col.delete_many({"batch_id": {"$ne": ultimo_batch}})
                            st.success(f"✅ Removidos {res.deleted_count:,} registros antigos.")
                        else:
                            st.warning("Nenhum batch encontrado.")
                        st.session_state['confirmar_manter_ultimo'] = False
                        st.cache_data.clear()
                        st.session_state.pop("df_prospeccao_cached", None)
                        st.rerun()
                with col_c4:
                    if st.button("❌ Cancelar", key="manter_nao"):
                        st.session_state['confirmar_manter_ultimo'] = False
                        st.rerun()

            st.markdown("---")
            st.markdown("#### 📧 Backup Manual por E-mail")
            flag_info = obter_flag_backup(db)
            col_st1, col_st2, col_st3 = st.columns(3)
            with col_st1:
                pending = flag_info.get("pending", False)
                st.metric("Status", "⏳ Pendente" if pending else "✅ Em dia")
            with col_st2:
                ult_edicao = flag_info.get("ultima_edicao_em")
                st.metric("Última edição", ult_edicao.strftime("%d/%m %H:%M") if ult_edicao else "—")
            with col_st3:
                ult_backup = flag_info.get("ultimo_backup_em")
                st.metric("Último backup enviado", ult_backup.strftime("%d/%m %H:%M") if ult_backup else "—")

            if flag_info.get("ultimo_motivo"):
                st.caption(f"📝 Motivo pendente: *{flag_info['ultimo_motivo']}*")

            st.info(f"ℹ️ O backup diário automático é disparado todos os dias a partir das **{HORARIO_BACKUP_HORA:02d}h{HORARIO_BACKUP_MIN:02d}** quando há edições pendentes.")

            df_adm = st.session_state.get("df_prospeccao_cached")
            if df_adm is not None and not df_adm.empty:
                if st.button("📤 Enviar Backup Agora (manual)", key="btn_backup_manual", use_container_width=True, type="primary"):
                    with st.spinner("📦 Gerando e enviando backup..."):
                        ok, msg_bkp = executar_backup_manual(db, df_adm, motivo="envio manual pelo administrador")
                    if ok:
                        st.success(msg_bkp if msg_bkp else "✅ Backup enviado com sucesso!")
                    else:
                        st.error(msg_bkp)

                    try:
                        excel_trat = gerar_excel_tratado(df_adm)
                        excel_reim = gerar_excel_reimportavel(df_adm)
                        data_str = datetime.now().strftime('%Y%m%d_%H%M%S')
                        col_dl1, col_dl2 = st.columns(2)
                        with col_dl1:
                            st.download_button("📊 Download — Tratado", data=excel_trat, file_name=f"backup_tratado_{data_str}.xlsx", mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", use_container_width=True)
                        with col_dl2:
                            st.download_button("📋 Download — Reimportável", data=excel_reim, file_name=f"backup_reimportavel_{data_str}.xlsx", mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", use_container_width=True)
                    except Exception:
                        pass
            else:
                st.warning("⚠️ Carregue os dados primeiro para habilitar o backup manual.")

    st.markdown("---")
    # ==================== GERENCIAMENTO DE DADOS ====================
    st.subheader("📂 Gerenciamento de Dados")
    col1, col2 = st.columns([3, 1])

    with col1:
        uploaded_file = st.file_uploader("📥 Importar Planilha de Prospecção", type=["xlsx", "xls"],
                                         help="Planilha com colunas: Região, BAIRRO, ENDEREÇO, NOME, BLOCO, APTO, CONSTRUTORA, ESTÁGIO, VIABILIDADE, OBS")

    with col2:
        if st.button("🔄 Recarregar Últimos", type="primary", use_container_width=True):
            st.cache_data.clear()
            st.session_state["reload_prospeccao"] = True
            st.rerun()

        if st.button("🗑️ Limpar Dados", type="secondary", use_container_width=True):
            if st.session_state.get("confirm_delete_prospeccao"):
                deleted = clear_prospeccao_data(db)
                st.success(f"✅ {deleted} registros removidos!")
                st.session_state["confirm_delete_prospeccao"] = False
                st.cache_data.clear()
                st.session_state.pop("df_prospeccao_cached", None)
                st.session_state.pop("last_imported_file", None)
                st.rerun()
            else:
                st.warning("⚠️ Clique novamente para confirmar")
                st.session_state["confirm_delete_prospeccao"] = True

    # ==================== IMPORTAÇÃO DA PLANILHA ====================
    if uploaded_file is not None:
        file_key = f"{uploaded_file.name}_{uploaded_file.size}"

        if st.session_state.get("last_imported_file") == file_key:
            if "df_prospeccao_cached" not in st.session_state:
                st.session_state["reload_prospeccao"] = True
        else:
            start_time = time.time()
            progress_bar = st.progress(0)

            try:
                progress_bar.progress(10)
                df_prospeccao = pd.read_excel(uploaded_file, sheet_name=0)

                progress_bar.progress(30)
                if len(df_prospeccao) > 0:
                    primeira_linha = df_prospeccao.iloc[0].astype(str).str.lower()
                    if all(val in [str(c).lower().strip() for c in df_prospeccao.columns] or val == 'nan' for val in primeira_linha):
                        df_prospeccao = df_prospeccao.iloc[1:].reset_index(drop=True)

                progress_bar.progress(50)
                if len(df_prospeccao) == 0:
                    st.error("❌ A planilha está vazia após a limpeza inicial.")
                    progress_bar.empty()
                    st.stop()

                col_mapping = {
                    'região': 'Região', 'zona': 'Região', 'bairro': 'BAIRRO',
                    'endereço': 'ENDEREÇO', 'endereco': 'ENDEREÇO', 'nome': 'NOME',
                    'condomínio': 'NOME', 'condominio': 'NOME', 'bloco': 'BLOCO',
                    'apto': 'APTO', 'apartamentos': 'APTO', 'construtora': 'CONSTRUTORA',
                    'estágio': 'ESTÁGIO', 'estagio': 'ESTÁGIO', 'viabilidade': 'VIABILIDADE',
                    'obs': 'OBS', 'observações': 'OBS',
                    'data da atualização': 'Data da Atualização',
                    'previsão de entrega': 'Previsão de Entrega',
                }
                df_prospeccao.columns = [str(col).strip() for col in df_prospeccao.columns]
                cols_lower_map = {c.lower(): c for c in df_prospeccao.columns}
                rename_map = {cols_lower_map[k]: v for k, v in col_mapping.items() if k in cols_lower_map and cols_lower_map[k] != v}
                df_prospeccao = df_prospeccao.rename(columns=rename_map)

                progress_bar.progress(70)
                if "ESTÁGIO" not in df_prospeccao.columns:
                    st.error("❌ Coluna 'ESTÁGIO' não encontrada na planilha!")
                    progress_bar.empty()
                    st.stop()

                for col in ['Prazo Medio', 'Prazo_Medio', 'prazo_medio', 'Prazo médio']:
                    if col in df_prospeccao.columns:
                        df_prospeccao = df_prospeccao.drop(columns=[col])

                df_prospeccao["FASE_CLASSIFICADA"] = classificar_fase_vetorizado(df_prospeccao["ESTÁGIO"])
                df_prospeccao["FASE_ORIGINAL"] = df_prospeccao["ESTÁGIO"]

                progress_bar.progress(80)
                if "VIABILIDADE" in df_prospeccao.columns:
                    df_prospeccao["PREVISAO_ENTREGA"] = extrair_previsao_entrega_vetorizado(df_prospeccao["VIABILIDADE"])
                if "Previsão de Entrega" in df_prospeccao.columns:
                    prev2 = extrair_previsao_entrega_vetorizado(df_prospeccao["Previsão de Entrega"])
                    if "PREVISAO_ENTREGA" in df_prospeccao.columns:
                        df_prospeccao["PREVISAO_ENTREGA"] = df_prospeccao["PREVISAO_ENTREGA"].where(df_prospeccao["PREVISAO_ENTREGA"].notna(), prev2)
                    else:
                        df_prospeccao["PREVISAO_ENTREGA"] = prev2

                progress_bar.progress(90)
                df_prospeccao["DIAS_RESTANTES"] = calcular_dias_para_entrega_vetorizado(df_prospeccao.get("PREVISAO_ENTREGA"))
                df_prospeccao["PRIORIDADE"] = calcular_prioridade_vetorizado(df_prospeccao)

                for col in ['VIABILIDADE', 'OBS', 'ESTÁGIO', 'FASE_ORIGINAL']:
                    if col in df_prospeccao.columns:
                        df_prospeccao[col] = df_prospeccao[col].astype(str).fillna('')
                        df_prospeccao[col] = df_prospeccao[col].replace(['nan', 'NaT', 'None', 'nat', 'NaN', 'Na N'], '')

                progress_bar.progress(95)
                fases_count = df_prospeccao["FASE_CLASSIFICADA"].value_counts().to_dict()
                metadata = {
                    "timestamp": datetime.now().replace(tzinfo=None),
                    "batch_id": f"prospeccao_{datetime.now().strftime('%Y%m%d_%H%M%S')}",
                    "filename": uploaded_file.name,
                    "fases": fases_count,
                    "construtoras": df_prospeccao["CONSTRUTORA"].dropna().unique().tolist() if "CONSTRUTORA" in df_prospeccao.columns else [],
                }

                progress_bar.progress(100)

                if save_prospeccao_data(db, df_prospeccao, metadata):
                    elapsed = time.time() - start_time
                    st.success(f"✅ Dados importados! {len(df_prospeccao)} projetos de {len(metadata['construtoras'])} construtoras (Tempo: {elapsed:.2f}s)")

                    with st.spinner("📦 Gerando backups e enviando por e-mail..."):
                        try:
                            excel_tratado = gerar_excel_tratado(df_prospeccao)
                            excel_reimportavel = gerar_excel_reimportavel(df_prospeccao)
                            sucesso, msg_email = enviar_email_backup(
                                arquivo_tratado=excel_tratado.getvalue(),
                                arquivo_reimportavel=excel_reimportavel.getvalue(),
                                total_projetos=len(df_prospeccao),
                                nome_arquivo_original=uploaded_file.name,
                            )
                            if sucesso:
                                st.success(msg_email)
                            else:
                                st.warning(f"⚠️ Backup gerado, mas falha no envio de e-mail: {msg_email}")

                            st.markdown("##### 📥 Download manual dos backups (caso preciso):")
                            col_dl1, col_dl2 = st.columns(2)
                            data_str = datetime.now().strftime('%Y%m%d_%H%M%S')
                            with col_dl1:
                                excel_tratado.seek(0)
                                st.download_button("📊 Backup Tratado (sistema)", data=excel_tratado, file_name=f"backup_tratado_{data_str}.xlsx", mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", use_container_width=True)
                            with col_dl2:
                                excel_reimportavel.seek(0)
                                st.download_button("📋 Backup Reimportável (original)", data=excel_reimportavel, file_name=f"backup_reimportavel_{data_str}.xlsx", mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", use_container_width=True)
                        except Exception as e_backup:
                            st.warning(f"⚠️ Erro ao gerar backup: {e_backup}")

                    st.session_state["last_imported_file"] = file_key
                    st.cache_data.clear()
                    st.session_state.pop("df_prospeccao_cached", None)
                    st.session_state["reload_prospeccao"] = True
                    st.rerun()

            except Exception as e:
                st.error(f"❌ Erro ao processar planilha: {str(e)}")
                import traceback
                with st.expander("Detalhes técnicos do erro"):
                    st.code(traceback.format_exc())
            finally:
                progress_bar.empty()

    # ==================== CARREGAMENTO COM CACHE ====================
    if st.session_state.get("reload_prospeccao") or "df_prospeccao_cached" not in st.session_state:
        with st.spinner('🔄 Carregando dados do banco...'):
            start_time = time.time()
            result = load_latest_prospeccao(db)
            if result[0] is not None:
                df_prospeccao, meta = result

                if "FASE_CLASSIFICADA" not in df_prospeccao.columns and "ESTÁGIO" in df_prospeccao.columns:
                    df_prospeccao["FASE_CLASSIFICADA"] = classificar_fase_vetorizado(df_prospeccao["ESTÁGIO"])
                if "PREVISAO_ENTREGA" not in df_prospeccao.columns and "VIABILIDADE" in df_prospeccao.columns:
                    df_prospeccao["PREVISAO_ENTREGA"] = extrair_previsao_entrega_vetorizado(df_prospeccao["VIABILIDADE"])
                if "DIAS_RESTANTES" not in df_prospeccao.columns and "PREVISAO_ENTREGA" in df_prospeccao.columns:
                    df_prospeccao["DIAS_RESTANTES"] = calcular_dias_para_entrega_vetorizado(df_prospeccao["PREVISAO_ENTREGA"])
                if "PRIORIDADE" not in df_prospeccao.columns:
                    df_prospeccao["PRIORIDADE"] = calcular_prioridade_vetorizado(df_prospeccao)

                st.session_state["df_prospeccao_cached"] = df_prospeccao
                st.session_state["meta_cached"] = meta
                elapsed = time.time() - start_time
                st.success(f"📦 Dados carregados! (Tempo: {elapsed:.2f}s)")
            else:
                if uploaded_file is None:
                    st.info("📂 Faça upload da planilha para começar")
                    return

    if "reload_prospeccao" in st.session_state:
        del st.session_state["reload_prospeccao"]

    df_prospeccao = st.session_state.get("df_prospeccao_cached")
    meta = st.session_state.get("meta_cached")

    if df_prospeccao is None or df_prospeccao.empty:
        st.info("📂 Faça upload da planilha para visualizar os dados")
        return

    # ==================== VERIFICAÇÃO DE BACKUP DIÁRIO AUTOMÁTICO ====================
    _backup_enviou, _backup_msg = verificar_e_disparar_backup_diario(db, df_prospeccao)
    if _backup_enviou:
        st.toast(_backup_msg, icon="📧")
    elif _backup_msg:
        st.toast(f"⚠️ {_backup_msg}", icon="⚠️")

    # ==================== ABAS PRINCIPAIS ====================
    tab_update, tab_new, tab_dash1, tab_dash2, tab_dash3, tab_dash4, tab_dash5 = st.tabs([
        "✏️ Atualizar Empreendimentos", "➕ Novo Cadastro", "📊 Por Construtora",
        "🗺️ Por Região", "⏱️ Timeline", "🎯 Priorização", "📋 Lista Completa",
    ])

    # --- ABA: ATUALIZAR EMPREENDIMENTOS ---
    with tab_update:
        st.header("✏️ Atualização de Cadastros")
        st.markdown("Filtre os empreendimentos e edite diretamente na tabela abaixo.")

        c1, c2, c3, c4 = st.columns(4)
        construtoras_opts = sorted(df_prospeccao["CONSTRUTORA"].dropna().unique().tolist()) if "CONSTRUTORA" in df_prospeccao.columns else []
        regioes_opts = sorted(df_prospeccao["Região"].dropna().unique().tolist()) if "Região" in df_prospeccao.columns else (sorted(df_prospeccao["ZONA"].dropna().unique().tolist()) if "ZONA" in df_prospeccao.columns else [])
        fases_opts = sorted(df_prospeccao["FASE_CLASSIFICADA"].dropna().unique().tolist()) if "FASE_CLASSIFICADA" in df_prospeccao.columns else []

        with c1: filter_construtora = st.multiselect("Construtora", options=construtoras_opts, placeholder="Todas", key="f_construtora_upd")
        with c2: filter_regiao = st.multiselect("Região/Zona", options=regioes_opts, placeholder="Todas", key="f_regiao_upd")
        with c3: filter_fase = st.multiselect("Estágio/Fase", options=fases_opts, placeholder="Todos", key="f_fase_upd")
        with c4: search_nome = st.text_input("Buscar por Nome", placeholder="Ex: MRV...", key="f_nome_upd")

        df_filtered = df_prospeccao.copy()
        if filter_construtora: df_filtered = df_filtered[df_filtered["CONSTRUTORA"].isin(filter_construtora)]
        if filter_regiao:
            col_reg = "Região" if "Região" in df_filtered.columns else "ZONA"
            df_filtered = df_filtered[df_filtered[col_reg].isin(filter_regiao)]
        if filter_fase: df_filtered = df_filtered[df_filtered["FASE_CLASSIFICADA"].isin(filter_fase)]
        if search_nome: df_filtered = df_filtered[df_filtered["NOME"].str.contains(search_nome, case=False, na=False)]

        st.markdown(f"**{len(df_filtered)} registros encontrados para edição.**")

        if not df_filtered.empty:
            cols_editaveis = ["NOME", "CONSTRUTORA", "BAIRRO",
                              "Região" if "Região" in df_filtered.columns else "ZONA",
                              "ESTÁGIO", "VIABILIDADE", "APTO", "OBS", "PREVISAO_ENTREGA"]
            cols_existing = [c for c in cols_editaveis if c in df_filtered.columns]
            
            # Adiciona FASE_CLASSIFICADA para exibição (somente leitura)
            if "FASE_CLASSIFICADA" in df_filtered.columns:
                cols_to_display = cols_existing + ["FASE_CLASSIFICADA"]
            else:
                cols_to_display = cols_existing

            df_original_edit = df_filtered[cols_existing + ["_id"]].copy()
            df_edit_display = df_filtered[cols_to_display].copy()

            column_config = {
                "ESTÁGIO": st.column_config.SelectboxColumn(
                    "Estágio da Obra",
                    options=["✅ Entramos", "💼 Em Negociação", "📢 Lançamento",
                             "🚧 Início de Obra", "🔨 Obra em Andamento", "🏁 Final de Obra",
                             "🎉 Entregue", "🏡 Pronto Para Morar", "📅 Futuro Lançamento", "❌ Não Entramos"],
                    required=True,
                ),
                "FASE_CLASSIFICADA": st.column_config.TextColumn(
                    "Fase Atual (Calculada)",
                    help="Esta coluna é calculada automaticamente com base no Estágio.",
                    disabled=True
                )
            }

            edited_df = st.data_editor(df_edit_display, key="editor_prospeccao_vectorized", 
                                       use_container_width=True, num_rows="fixed", column_config=column_config)

            st.warning("⚠️ Ao editar 'ESTÁGIO', a 'Fase Classificada' será recalculada automaticamente ao salvar.")

            if st.button("💾 Salvar Alterações", type="primary", key="btn_save_updates"):
                if isinstance(edited_df, dict):
                    edited_df = pd.DataFrame(edited_df)
                with st.spinner('🔄 Processando...'):
                    modified = update_records_batch_vectorized(db, df_original_edit, edited_df, cols_existing)
                    if modified > 0:
                        st.success(f"✅ {modified} registros atualizados!")
                        marcar_backup_pendente(db, motivo=f"edição de {modified} registro(s) na aba Atualizar Empreendimentos")
                        st.cache_data.clear()
                        st.session_state.pop("df_prospeccao_cached", None)
                        st.rerun()
                    else:
                        st.info("ℹ️ Nenhuma alteração detectada.")
        else:
            st.info("Nenhum registro encontrado com esses filtros.")

    # --- ABA: NOVO CADASTRO ---
    with tab_new:
        st.header("➕ Novo Cadastro Manual")
        with st.form("form_novo_empreendimento", clear_on_submit=True):
            c1, c2 = st.columns(2)
            with c1:
                nome = st.text_input("Nome do Empreendimento *", placeholder="Ex: Residencial Jardins")
                construtora = st.text_input("Construtora *", placeholder="Ex: MRV")
                bairro = st.text_input("Bairro", placeholder="Ex: Centro")
                regiao = st.text_input("Região/Zona", placeholder="Ex: Zona Norte")
                endereco = st.text_input("Endereço", placeholder="Rua das Flores, 123")
                bloco = st.text_input("Bloco/Torre", placeholder="Bloco A")
            with c2:
                apto = st.number_input("Total de Apartamentos", min_value=0, step=1)
                estagio = st.selectbox("Estágio da Obra", [
                    "✅ Entramos", "💼 Em Negociação", "📢 Lançamento",
                    "🚧 Início de Obra", "🔨 Obra em Andamento", "🏁 Final de Obra",
                    "🎉 Entregue", "🏡 Pronto Para Morar", "📅 Futuro Lançamento", "❌ Não Entramos",
                ])
                viabilidade = st.text_area("Viabilidade / Observações", placeholder="Ex: Previsão entrega 12/2025.")
                obs_geral = st.text_area("Observações Gerais")

            if st.form_submit_button("Cadastrar Empreendimento"):
                if not nome or not construtora:
                    st.error("❌ Nome e Construtora são obrigatórios.")
                else:
                    new_data = {"NOME": nome, "CONSTRUTORA": construtora, "BAIRRO": bairro,
                                "Região": regiao, "ENDEREÇO": endereco, "BLOCO": bloco,
                                "APTO": apto, "ESTÁGIO": estagio, "VIABILIDADE": viabilidade, "OBS": obs_geral}
                    if insert_new_record(db, new_data):
                        st.success("✅ Empreendimento cadastrado!")
                        st.cache_data.clear()
                        st.session_state.pop("df_prospeccao_cached", None)
                        st.rerun()
                    else:
                        st.error("❌ Erro ao cadastrar.")

    # --- ABA: POR CONSTRUTORA ---
    with tab_dash1:
        st.header("📊 Análise por Construtora")
        df_construtoras = analisar_por_construtora(df_prospeccao)
        if not df_construtoras.empty:
            construtoras_disp = df_construtoras["CONSTRUTORA"].dropna().unique().tolist()
            default_c = construtoras_disp[:5] if len(construtoras_disp) >= 5 else construtoras_disp
            construtoras_sel = st.multiselect("Filtrar Construtoras", options=construtoras_disp, default=default_c, key="construtoras_filter")
            if construtoras_sel:
                df_cf = df_construtoras[df_construtoras["CONSTRUTORA"].isin(construtoras_sel)]
                col_c1, col_c2 = st.columns(2)
                with col_c1:
                    fig1 = px.bar(df_cf.head(10), x="total_projetos", y="CONSTRUTORA", orientation="h", title="Top 10 por Projetos", color="total_projetos", color_continuous_scale="Blues")
                    fig1.update_layout(height=400, yaxis={"categoryorder": "total ascending"})
                    st.plotly_chart(fig1, use_container_width=True)
                with col_c2:
                    fig2 = px.bar(df_cf.head(10), x="total_apartamentos", y="CONSTRUTORA", orientation="h", title="Top 10 por APTs", color="total_apartamentos", color_continuous_scale="Greens")
                    fig2.update_layout(height=400, yaxis={"categoryorder": "total ascending"})
                    st.plotly_chart(fig2, use_container_width=True)

                st.markdown("### Composição de Fases por Construtora")
                fases_cols = ["projetos_entramos", "projetos_negociacao", "projetos_lancamento",
                              "projetos_inicio_obra", "projetos_andamento", "projetos_final_obra",
                              "projetos_entregue", "projetos_pronto_morar", "projetos_futuro"]
                fases_labels = ["✅ Entramos", "💼 Negociação", "📢 Lançam.", "🚧 Início",
                                "🔨 Andamento", "🏁 Final", "🎉 Entregue", "🏡 P/Morar", "📅 Futuro"]
                df_fp = df_cf.head(8).copy().set_index("CONSTRUTORA")[fases_cols]
                df_fp.columns = fases_labels
                fig3 = px.bar(df_fp, barmode="stack", title="Distribuição de Fases (Top 8)", color_discrete_sequence=px.colors.qualitative.Set3)
                fig3.update_layout(height=500)
                st.plotly_chart(fig3, use_container_width=True)

                st.markdown("### Tabela Detalhada")
                df_disp = df_cf[["CONSTRUTORA", "total_projetos", "total_apartamentos",
                                  "percentual_entregue", "percentual_em_obra", "percentual_oportunidades"]].copy()
                df_disp["total_apartamentos"] = df_disp["total_apartamentos"].apply(lambda x: f"{int(x):,}".replace(",", ".") if pd.notna(x) else "0")
                df_disp["percentual_entregue"] = df_disp["percentual_entregue"].apply(lambda x: f"{x:.1f}%")
                df_disp["percentual_em_obra"] = df_disp["percentual_em_obra"].apply(lambda x: f"{x:.1f}%")
                df_disp["percentual_oportunidades"] = df_disp["percentual_oportunidades"].apply(lambda x: f"{x:.1f}%")
                df_disp.columns = ["Construtora", "Projetos", "Total APTs", "% Entregue", "% Em Obra", "% Oportunidades"]
                st.dataframe(df_disp, use_container_width=True)
        else:
            st.warning("⚠️ Dados insuficientes para análise por construtora")

    # --- ABA: POR REGIÃO ---
    with tab_dash2:
        st.header("🗺️ Análise por Região")
        df_zonas = analisar_por_zona(df_prospeccao)
        if not df_zonas.empty:
            col_zona = df_zonas.columns[0]
            col_m1, col_m2 = st.columns(2)
            with col_m1:
                fig_z = px.bar(df_zonas, x=col_zona, y="total_projetos", color="total_projetos", color_continuous_scale="Reds", title="Projetos por Região", text="total_projetos")
                fig_z.update_traces(texttemplate='%{text}', textposition='outside')
                st.plotly_chart(fig_z, use_container_width=True)
            with col_m2:
                fig_o = px.bar(df_zonas, x=col_zona, y="oportunidades", color="percentual_oportunidades", color_continuous_scale="Greens", title="Oportunidades por Região", text="oportunidades")
                fig_o.update_traces(texttemplate='%{text}', textposition='outside')
                st.plotly_chart(fig_o, use_container_width=True)
            if "BAIRRO" in df_prospeccao.columns:
                st.markdown("### Top 15 Bairros")
                bairros_stats = (df_prospeccao.groupby("BAIRRO").agg(total_projetos=("NOME", "count")).reset_index().sort_values("total_projetos", ascending=False).head(15))
                fig_b = px.bar(bairros_stats, x="total_projetos", y="BAIRRO", orientation="h", title="Top 15 Bairros", color="total_projetos", color_continuous_scale="Blues")
                st.plotly_chart(fig_b, use_container_width=True)
            st.dataframe(df_zonas, use_container_width=True)
        else:
            st.warning("⚠️ Dados insuficientes para análise por região")

    # --- ABA: TIMELINE ---
    with tab_dash3:
        st.header("⏱️ Timeline de Entregas")
        df_timeline = timeline_entregas(df_prospeccao)
        if not df_timeline.empty and "PREVISAO_ENTREGA" in df_timeline.columns:
            anos_disp = sorted(df_timeline["ANO_ENTREGA"].dropna().unique().astype(int))
            if anos_disp:
                ano_sel = st.selectbox("Filtrar por Ano de Entrega", options=anos_disp, index=len(anos_disp) - 1)
                df_tl_filt = df_timeline[df_timeline["ANO_ENTREGA"] == ano_sel]
                st.markdown(f"### 📅 Entregas Previstas para {int(ano_sel)}")
                if not df_tl_filt.empty:
                    ent_mes = (df_tl_filt.groupby("MES_ENTREGA").agg(total_projetos=("NOME", "count"), total_apartamentos=("APTO", lambda x: pd.to_numeric(x, errors='coerce').sum())).reset_index())
                    ent_mes["MES_ENTREGA"] = ent_mes["MES_ENTREGA"].astype(str)
                    fig_tl = px.bar(ent_mes, x="MES_ENTREGA", y="total_projetos", color="total_apartamentos", title=f"Distribuição Mensal ({int(ano_sel)})")
                    st.plotly_chart(fig_tl, use_container_width=True)

                    st.markdown("### 🚨 Próximos 90 dias")
                    prox = df_timeline[df_timeline["DIAS_RESTANTES"] <= 90].sort_values("DIAS_RESTANTES")
                    if not prox.empty:
                        for _, row in prox.head(10).iterrows():
                            dias = int(row["DIAS_RESTANTES"]) if pd.notna(row["DIAS_RESTANTES"]) else 0
                            cor = "🔴" if dias <= 30 else "🟠" if dias <= 60 else "🟡"
                            st.markdown(f"{cor} **{row['NOME']}** ({row.get('CONSTRUTORA','N/A')}) — {row.get('BAIRRO','')} — {dias} dias")
                    else:
                        st.info("ℹ️ Nenhuma entrega nos próximos 90 dias")

                    with st.expander(f"Ver Todas as Entregas de {int(ano_sel)}"):
                        cols_d = [c for c in ["NOME", "CONSTRUTORA", "BAIRRO", "APTO", "PREVISAO_ENTREGA", "DIAS_RESTANTES"] if c in df_tl_filt.columns]
                        df_show = df_tl_filt[cols_d].copy()
                        if "PREVISAO_ENTREGA" in df_show.columns:
                            mask = df_show['PREVISAO_ENTREGA'].notna()
                            df_show.loc[mask, 'PREVISAO_ENTREGA'] = pd.to_datetime(df_show.loc[mask, 'PREVISAO_ENTREGA']).dt.strftime('%d/%m/%Y')
                            df_show.loc[~mask, 'PREVISAO_ENTREGA'] = ''
                        st.dataframe(df_show, use_container_width=True)
        else:
            st.warning("⚠️ Sem dados de previsão de entrega.")

    # --- ABA: PRIORIZAÇÃO ---
    with tab_dash4:
        st.header("🎯 Priorização de Ações")
        if "PRIORIDADE" in df_prospeccao.columns:
            col_p1, col_p2 = st.columns(2)
            with col_p1:
                fig_pri = px.pie(values=df_prospeccao["PRIORIDADE"].value_counts().values, names=df_prospeccao["PRIORIDADE"].value_counts().index, title="Distribuição de Prioridades",
                                 color_discrete_map={"🟢 Ação Imediata": "#2ecc71", "🟠 Alta Prioridade": "#d35400", "🔴 Urgente": "#e74c3c", "🟠 Alta": "#e67e22", "🟡 Média": "#f1c40f",
                                                     "🟡 Acompanhamento": "#9b59b6", "🔵 Planejamento": "#3498db", "⚪ Arquivado": "#95a5a6", "⚪ Baixa": "#bdc3c7"})
                st.plotly_chart(fig_pri, use_container_width=True)
            with col_p2:
                prioridades_disp = df_prospeccao["PRIORIDADE"].unique().tolist()
                valid_defaults = [p for p in ["🟢 Ação Imediata", "🟠 Alta Prioridade", "🔴 Urgente"] if p in prioridades_disp]
                if not valid_defaults and prioridades_disp:
                    valid_defaults = [prioridades_disp[0]]
                prioridade_sel = st.multiselect("Filtrar por Prioridade", options=prioridades_disp, default=valid_defaults, key="prioridade_filter")
                if prioridade_sel:
                    df_prio = df_prospeccao[df_prospeccao["PRIORIDADE"].isin(prioridade_sel)]
                    st.metric("Projetos Prioritários", f"{len(df_prio):,}".replace(",", "."))
                    st.markdown("### 📋 Lista de Ação")
                    cols_d = [c for c in ["NOME", "CONSTRUTORA", "BAIRRO", "FASE_CLASSIFICADA", "PRIORIDADE", "DIAS_RESTANTES"] if c in df_prio.columns]
                    df_show = df_prio[cols_d].copy()
                    if "DIAS_RESTANTES" in df_show.columns:
                        df_show["DIAS_RESTANTES"] = df_show["DIAS_RESTANTES"].apply(lambda x: f"{int(x)} dias" if pd.notna(x) else "-")
                    st.dataframe(df_show, use_container_width=True)
                    excel_buf = io.BytesIO()
                    with pd.ExcelWriter(excel_buf, engine='openpyxl') as writer:
                        df_show.to_excel(writer, index=False, sheet_name='Prioritários')
                    excel_buf.seek(0)
                    st.download_button("📥 Exportar Lista Prioritária", excel_buf, f"prioritarios_{datetime.now().strftime('%Y%m%d')}.xlsx", mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
        else:
            st.warning("⚠️ Dados de prioridade indisponíveis")

    # --- ABA: LISTA COMPLETA ---
    with tab_dash5:
        st.header("📋 Lista Completa de Projetos")
        col_f1, col_f2, col_f3, col_f4 = st.columns(4)
        col_regiao = "Região" if "Região" in df_prospeccao.columns else "ZONA" if "ZONA" in df_prospeccao.columns else None
        
        with col_f1:
            zonas_disp = df_prospeccao[col_regiao].dropna().unique().tolist() if col_regiao else []
            zona_sel = st.multiselect("Região", options=zonas_disp, key="lista_zona")
        with col_f2:
            constr_disp = df_prospeccao["CONSTRUTORA"].dropna().unique().tolist() if "CONSTRUTORA" in df_prospeccao.columns else []
            construtora_sel = st.multiselect("Construtora", options=constr_disp, key="lista_construtora")
        with col_f3:
            fases_disp = df_prospeccao["FASE_CLASSIFICADA"].dropna().unique().tolist() if "FASE_CLASSIFICADA" in df_prospeccao.columns else []
            fase_sel = st.multiselect("Fase", options=fases_disp, key="lista_fase")
        with col_f4:
            # 🔍 NOVO: Busca por nome
            search_nome_lista = st.text_input("Buscar por Nome", placeholder="Ex: Brito...", key="lista_busca_nome")

        df_filt = df_prospeccao.copy()
        if zona_sel and col_regiao:
            df_filt = df_filt[df_filt[col_regiao].isin(zona_sel)]
        if construtora_sel:
            df_filt = df_filt[df_filt["CONSTRUTORA"].isin(construtora_sel)]
        if fase_sel:
            df_filt = df_filt[df_filt["FASE_CLASSIFICADA"].isin(fase_sel)]
        if search_nome_lista:
            df_filt = df_filt[df_filt["NOME"].str.contains(search_nome_lista, case=False, na=False)]

        st.markdown(f"### 📊 {len(df_filt)} projetos encontrados")
        cols_disp = [c for c in ["NOME", "CONSTRUTORA", "BAIRRO", "Região", "FASE_CLASSIFICADA", "APTO", "PRIORIDADE"] if c in df_filt.columns]
        df_lista = df_filt[cols_disp].copy()
        if "APTO" in df_lista.columns:
            df_lista["APTO"] = df_lista["APTO"].apply(lambda x: f"{int(x):,}".replace(",", ".") if pd.notna(x) else "N/A")
        df_lista = df_lista.rename(columns={"NOME": "Condomínio", "CONSTRUTORA": "Construtora", "BAIRRO": "Bairro", 
                                             "Região": "Região", "FASE_CLASSIFICADA": "Fase", "APTO": "APTs", "PRIORIDADE": "Prioridade"})
        st.dataframe(df_lista, use_container_width=True)

        st.markdown("---")
        st.subheader("📎 Exportar Dados")
        df_constr_res = analisar_por_construtora(df_filt)
        df_zonas_res = analisar_por_zona(df_filt)
        excel_buf = exportar_prospeccao_excel(df_filt, df_constr_res, df_zonas_res)
        col_e1, col_e2 = st.columns([3, 1])
        with col_e1:
            st.download_button(
                label="📥 Exportar Lista Completa (Excel com Abas por Fase)",
                data=excel_buf,
                file_name=f"prospeccao_completa_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                use_container_width=True,
            )
        with col_e2:
            st.info("""
            **Estrutura do Excel:**
            - 📊 Resumo Executivo
            - 📋 Completo
            - 00: ✅ Entramos
            - 01–09: Outras Fases
            - 10: Por Construtora
            - 11: Por Região
            """)

    st.markdown("---")
    st.markdown("""
    ### 💡 Dicas Rápidas:
    - Use **✏️ Atualizar Empreendimentos** para corrigir fases ou adicionar observações.
    - A fase **✅ Entramos** tem alta prioridade (🟢 Ação Imediata).
    - A fase **🎉 Entregue** identifica projetos concluídos.
    - A exportação gera um Excel com **abas separadas por fase**.
    """)

if __name__ == "__main__":
    render_prospeccao_condominios()
