# -*- coding: utf-8 -*-
"""
API do Painel de Processos SINAPE — servidor Flask (Docker) + MongoDB
=========================================================================

Substitui o backend AWS (Lambda + DynamoDB + S3) por um único container:
Flask serve o index.html e a API; os dados ficam no MongoDB; os anexos
enviados pela equipe ficam em disco, dentro da pasta UPLOAD_DIR.

Rotas:
  GET     /login                             → página de login (se SITE_USER/SITE_PASSWORD configurados)
  POST    /login                             → autentica e cria sessão
  GET     /logout                            → encerra sessão
  GET     /                                  → index.html
  GET     /chart.umd.min.js                  → Chart.js hospedado localmente (indicadores do módulo Comercial)
  GET     /api/processos                     → lista resumida {"processos":[...]}
  POST    /api/processos                     → cria processo (corpo = documento completo); cria também a Oportunidade
                                                ligada no Painel Gerencial (_sync_oportunidade_do_processo) — só pra
                                                processo novo, processo já existente antes disso não é tocado
  GET     /api/processos/<id>                → documento completo
  PUT     /api/processos/<id>                → substitui documento completo; se já houver Oportunidade ligada, atualiza
  PATCH   /api/processos/<id>                → mescla {metaPatch, analisePatch, checklistPatch, exigencias, seVersao};
                                                se já houver Oportunidade ligada, sincroniza cliente/objeto/valor/status
  DELETE  /api/processos/<id>                → manda pra lixeira (não apaga anexos nem arquivo nenhum — ver /excluidos)
  GET     /api/processos/excluidos           → lixeira: processos excluídos, disponíveis pra restaurar
  POST    /api/processos/excluidos/<id>/restaurar → desfaz a exclusão, com anexos e tudo intacto
  DELETE  /api/processos/excluidos/<id>       → expurgo definitivo: apaga o registro E os arquivos (anexos, pasta de concorrente) — sem volta
  GET     /api/processos/<id>/anexos         → lista anexos do processo
  POST    /api/processos/<id>/anexos         → envia um anexo (multipart, campo "arquivo")
  GET     /api/processos/<id>/anexos/<aid>   → baixa o arquivo
  DELETE  /api/processos/<id>/anexos/<aid>   → remove o anexo (registro + arquivo em disco)
  GET     /api/processos/<id>/pasta/arquivos → lista os arquivos da pasta DESTE processo no SharePoint (qualquer tipo), pra anexar sem caçar no computador
  POST    /api/processos/<id>/anexos/do-sharepoint → anexa {caminho_relativo, secao?} vindo direto da pasta do processo
  GET     /api/processos/<id>/dossie         → monta o dossiê de habilitação (Montador) e devolve o .zip
  GET     /api/relatorios/mais-recente        → devolve a atualização do dia mais recente publicada (inclui "novos": [{tipo,nome,status,caminho_pasta}])
  POST    /api/relatorios                     → publica uma nova atualização do dia (uso por processo automatizado)
  POST    /api/relatorios/executar-varredura  → varre o SharePoint agora, compara com a varredura anterior e publica o relatório do dia
  POST    /api/processos/analisar-ia          → recebe PDFs (multipart, campo "arquivos"); responde 202 {job_id} e analisa em segundo plano
  GET     /api/pastas/arquivos                → lista os PDFs de uma pasta do SharePoint com páginas e custo estimado, pra escolher o que entra na análise
  POST    /api/processos/analisar-novo        → a partir de {caminho_pasta, tipo, model?, effort?, arquivos?} de um item novo da varredura, baixa os PDFs e responde 202 {job_id}; a análise e a criação do processo correm em segundo plano
  GET     /api/jobs/<id>                      → andamento de uma análise: rodando | concluido (com processo_id ou documento) | erro
  GET     /api/pendentes                      → fila de processos novos aguardando decisão (analisar ou dispensar)
  POST    /api/pendentes                      → põe uma pasta do SharePoint na fila à mão {caminho_pasta, tipo?, nome?}
  POST    /api/pendentes/dispensar            → tira da fila sem analisar {caminho_pasta, autor?, motivo?}
  GET     /api/pendentes/dispensados          → lista quem foi dispensado (pra oferecer "Restaurar" na tela)
  POST    /api/pendentes/restaurar            → desfaz a dispensa {caminho_pasta}
  DELETE  /api/pendentes/dispensados          → apaga de vez um item dispensado {caminho_pasta} — some da fila, sem volta
  GET     /api/gastos                         → contador de gastos de IA (total de tokens e custo em US$/R$) + detalhamento por processo
  GET     /api/correcoes                      → pares (resposta da IA / correção da equipe) — matéria-prima pra treinar um modelo especialista no futuro
  GET     /api/prazos                         → todos os prazos de todos os processos ativos, numa lista só, ordenados do mais urgente pro mais distante
  GET     /api/gerencial                      → dados crus do acompanhamento por fases de todos os processos (a tela é quem calcula % e semáforo)
  POST    /api/emails/varredura               → varre o Inbox do Outlook do usuário logado (Mail.Read), classifica e cruza com processos
  GET     /api/emails/ultima-varredura        → devolve a última varredura de e-mail já feita, sem rodar de novo
  POST    /api/emails/responder               → responde um e-mail da varredura na própria thread (Mail.Send) {graph_id, texto}
  GET     /api/eu                             → identidade de quem está logado (inclui "autor", que assina o que a pessoa fizer)
  GET     /api/usuarios                       → quem já entrou com conta própria — a lista de gente endereçável (notificar, atribuir)
  POST    /api/notificacoes                   → avisa a equipe (tipo "equipe") ou pede conferência de alguém (tipo "dirigida") sobre o que mudou numa sessão de edição
  GET     /api/notificacoes                   → caixa de entrada de quem está logado: gerais, pessoais e o agrupamento por remetente
  POST    /api/notificacoes/<id>/lida         → marca lida ao ABRIR o item (não ao abrir a aba)
  POST    /api/notificacoes/<id>/responder    → OK (sem texto) ou comentário; gera o retorno pra quem avisou
  POST    /api/sinki/conversar                → uma rodada de conversa com o Sinki (multipart: mensagem + arquivos + conversa_id)
  GET     /api/sinki/conversas                → lista as conversas com o Sinki (mais recentes primeiro)
  GET     /api/sinki/conversas/<cid>          → histórico completo de uma conversa
  DELETE  /api/sinki/conversas/<cid>          → apaga a conversa e seus anexos
  GET     /api/sinki/prompt                   → prompt do Sinki em texto (fonte única, usada pelo botão de copiar)
  GET     /api/processos/<id>/concorrentes         → lista as verificações de documentação de concorrente já feitas neste processo
  POST    /api/processos/<id>/concorrentes         → confere a documentação de uma empresa concorrente (multipart: empresa, arquivos) contra as exigências já extraídas do edital
  DELETE  /api/processos/<id>/concorrentes/<cid>   → apaga uma verificação de concorrente e seus arquivos
  GET     /api/comercial/oportunidades        → lista as oportunidades comerciais (área Comercial, separada dos processos)
  POST    /api/comercial/oportunidades        → cria uma oportunidade
  PUT     /api/comercial/oportunidades/<id>   → substitui a oportunidade (inclusive editar margem)
  DELETE  /api/comercial/oportunidades/<id>   → remove a oportunidade
  GET     /api/comercial/equipe               → lista a equipe comercial (custo mensal, alimenta os indicadores)
  POST    /api/comercial/equipe               → cria pessoa na equipe
  PUT     /api/comercial/equipe/<id>          → substitui
  DELETE  /api/comercial/equipe/<id>          → remove
  GET     /api/comercial/meta                 → meta anual de carteira (singleton)
  PUT     /api/comercial/meta                 → substitui a meta
  GET     /api/comercial/timesheet            → horas dedicadas por mês
  PUT     /api/comercial/timesheet/<mes>      → upsert do total do mês (AAAA-MM)
  DELETE  /api/comercial/timesheet/<mes>      → remove o mês
  GET     /api/comercial/atas                 → lista as atas de reunião da área (mais recente primeiro)
  POST    /api/comercial/atas                 → cria uma ata {data, participantes, assuntos:[...]}
  PUT     /api/comercial/atas/<id>            → substitui a ata (inclusive editar/adicionar assuntos)
  DELETE  /api/comercial/atas/<id>            → remove a ata
  POST    /api/comercial/importar             → substitui TODO o módulo pelo backup {oportunidades,equipe,meta,timesheet} — rota de recuperação, não só migração;
                                                guarda uma foto do estado atual antes de sobrescrever (botão de segurança abaixo)
  GET     /api/comercial/snapshot-anterior     → {existe, criadoEm} — se há uma foto de "antes do último import" pra restaurar
  POST    /api/comercial/restaurar-anterior    → botão de segurança: volta pro estado de antes do último import (é um swap —
                                                apertar de novo desfaz a restauração)

Montador de Dossiê (integrado):
  Usa o módulo em montador-dossie/ (mesmo repo) para buscar a documentação de
  habilitação atualizada da SINAPE no SharePoint via Microsoft Graph API e
  organizar num .zip. Configuração via variáveis de ambiente:
    MONTADOR_TENANT_ID, MONTADOR_CLIENT_ID, MONTADOR_CLIENT_SECRET  → app do Azure AD
    MONTADOR_MODO_LOCAL + MONTADOR_ONEDRIVE_RAIZ                    → alternativa via OneDrive sincronizado
  Sem essas variáveis, o endpoint responde 503 (funcionalidade desabilitada,
  resto do Painel funciona normalmente).

Autenticação:
  - Acesso ao site: sessão Flask após login (env SITE_USER + SITE_PASSWORD + SECRET_KEY).
  - API: header x-sinape-token comparado com a variável de ambiente TOKEN.
Armazenamento de dados: MongoDB (env MONGO_URL), coleção "processos" com o
documento inteiro (evita migração de esquema a cada campo novo) e coleção
"anexos" com os metadados dos arquivos.
Armazenamento de anexos: disco, em UPLOAD_DIR/<processo_id>/<uuid>__<nome original>.

Controle de concorrência: PATCH aceita "seVersao"; se a versão gravada for
diferente, responde 409 com o documento atual no corpo — o painel então
mescla e reenvia (last-write-wins campo a campo, sem travar ninguém). A
gravação usa update condicional pela versão lida, para não perder alterações
concorrentes entre a leitura e a escrita.
"""

import base64
import copy
import io
import json
import mimetypes
import os
import re
import shutil
import sys
import tempfile
import threading
import time
import traceback
import uuid
from datetime import date, datetime, timedelta
from pathlib import Path
from urllib.parse import quote

import anthropic
import msal
import requests
from pypdf import PdfReader, PdfWriter
from pymongo import MongoClient, ASCENDING, DESCENDING
from pymongo.errors import DuplicateKeyError
from flask import Flask, request, jsonify, send_from_directory, send_file, session, redirect, Response
from werkzeug.utils import secure_filename

BASE_DIR = Path(__file__).resolve().parent
UPLOAD_DIR = Path(os.environ.get("UPLOAD_DIR", "/app/uploads"))
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

sys.path.insert(0, str(BASE_DIR / "montador-dossie"))
from montador_dossie import (  # noqa: E402
    montar_dossie_por_processo, escanear_biblioteca, localizar_pasta_processo,
    baixar_pdfs_da_pasta, listar_arquivos_do_processo, baixar_arquivo_do_processo,
    parse_pasta_sharepoint, SITE_HOSTNAME, SITE_PATH,
)

MONTADOR_MODO_LOCAL = os.environ.get("MONTADOR_MODO_LOCAL", "").lower() in ("1", "true", "sim")
MONTADOR_TENANT_ID = os.environ.get("MONTADOR_TENANT_ID", "")
MONTADOR_CLIENT_ID = os.environ.get("MONTADOR_CLIENT_ID", "")
MONTADOR_CLIENT_SECRET = os.environ.get("MONTADOR_CLIENT_SECRET", "")
MONTADOR_ONEDRIVE_RAIZ = os.environ.get("MONTADOR_ONEDRIVE_RAIZ", "")
with open(BASE_DIR / "montador-dossie" / "biblioteca_v2_proposta.json", "r", encoding="utf-8") as _f:
    MONTADOR_BIBLIOTECA = json.load(_f)

TOKEN = os.environ.get("TOKEN", "")
SITE_USER = os.environ.get("SITE_USER", "")
SITE_PASSWORD = os.environ.get("SITE_PASSWORD", "")
SECRET_KEY = os.environ.get("SECRET_KEY", "troque-em-producao")

# Login com a conta Microsoft da empresa — reaproveita o mesmo app do Azure AD
# já usado para o SharePoint (mesmo tenant, mesmo client). Diferente de checar
# se o e-mail *parece* corporativo, aqui é a própria Microsoft que confirma que
# a conta existe, tem senha certa (e MFA, se a empresa exigir) e pertence ao
# tenant da SINAPE — desligou no Entra, perde o acesso aqui também.
AUTH_TENANT_ID = os.environ.get("AUTH_TENANT_ID", "") or MONTADOR_TENANT_ID
AUTH_CLIENT_ID = os.environ.get("AUTH_CLIENT_ID", "") or MONTADOR_CLIENT_ID
AUTH_CLIENT_SECRET = os.environ.get("AUTH_CLIENT_SECRET", "") or MONTADOR_CLIENT_SECRET
AUTH_REDIRECT_URI = os.environ.get("AUTH_REDIRECT_URI", "") or "https://projeto-sinape.onrender.com/auth/callback"
MONGO_URL = os.environ.get("MONGO_URL", "")
MAX_UPLOAD_MB = int(os.environ.get("MAX_UPLOAD_MB", "25"))

ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
ANTHROPIC_MODEL = os.environ.get("ANTHROPIC_MODEL", "claude-opus-5")
# Esse teto era pensado pra uma chamada só (32 MB em base64 é o limite real da
# API) — agora que a análise reparte em lotes quando passa disso, ele só
# precisa segurar um exagero de verdade (pasta inteira anexada por engano),
# não mais o tamanho normal de um edital grande com tudo junto.
MAX_PDF_TOTAL_MB = int(os.environ.get("MAX_PDF_TOTAL_MB", "80"))
# Prompt único do Sinki (a IA do DATA SIN): vale tanto pra conversa quanto pra
# análise estruturada de edital — antes eram dois textos que saíam de sincronia.
PROMPT_SINKI = (BASE_DIR / "prompt_sinki.txt").read_text(encoding="utf-8")
# Biblioteca de jurisprudência do TCU (manual "Licitações e Contratos", 5ª ed.).
# São 209 seções, ~3 milhões de caracteres — não cabe no prompt e não faria
# sentido: o Sinki consulta sob demanda, e o índice marca quais seções são do
# nosso escopo (habilitação, impugnação, recurso...) e quais ignorar
# (governança interna do órgão, dispensas específicas).
BIBLIOTECA_TCU_DIR = BASE_DIR / "biblioteca-tcu"
try:
    BIBLIOTECA_TCU = json.loads((BIBLIOTECA_TCU_DIR / "indice.json").read_text(encoding="utf-8"))
except Exception:
    BIBLIOTECA_TCU = {"secoes": []}
# Pedido que liga o "modo análise" descrito no prompt do Sinki. Vai como última
# coisa do turno do usuário (posição de maior peso), logo após os documentos.
PEDIDO_ANALISE = (
    "Produza agora a análise estruturada deste processo para importar no Painel, "
    "seguindo exatamente o contrato da seção \"ANÁLISE ESTRUTURADA DE EDITAL\". "
    "Responda apenas com o JSON, sem nenhum texto antes ou depois."
)
PEDIDO_VERIFICAR_CONCORRENTE = (
    "Os documentos anexados a seguir pertencem a uma empresa CONCORRENTE da SINAPE "
    "neste certame — não são documentos da SINAPE. Confira-os contra o gabarito de "
    "exigências do edital (abaixo, em JSON), seguindo exatamente o contrato da seção "
    "\"VERIFICAÇÃO DE DOCUMENTAÇÃO DE CONCORRENTE\". Responda apenas com o JSON, sem "
    "nenhum texto antes ou depois.\n\nGABARITO DE EXIGÊNCIAS DO EDITAL:\n{gabarito}"
)
anthropic_client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY) if ANTHROPIC_API_KEY else None

app = Flask(__name__, static_folder=None)
app.secret_key = SECRET_KEY
app.config["PERMANENT_SESSION_LIFETIME"] = timedelta(days=7)
app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
app.config["SESSION_COOKIE_SECURE"] = os.environ.get("RENDER") == "true"
app.config["MAX_CONTENT_LENGTH"] = MAX_UPLOAD_MB * 1024 * 1024

CORS_HEADERS = {
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Methods": "GET,POST,PUT,PATCH,DELETE,OPTIONS",
    "Access-Control-Allow-Headers": "content-type,x-sinape-token",
    "Access-Control-Max-Age": "86400",
}


# ──────────────────────────────────────────────────────────────────
# banco de dados
# ──────────────────────────────────────────────────────────────────
mongo_client = MongoClient(MONGO_URL)
db = mongo_client.get_database("sinape")
col_processos = db["processos"]
col_anexos = db["anexos"]
col_relatorios = db["relatorios"]
col_snapshots = db["sharepoint_snapshots"]
col_gastos = db["gastos_ia"]
col_sinki = db["sinki_conversas"]
col_correcoes = db["correcoes_ia"]
col_jobs = db["jobs_analise"]
col_pendentes = db["pendentes_analise"]
col_usuarios = db["usuarios"]
col_notificacoes = db["notificacoes"]
col_comercial_oportunidades = db["comercial_oportunidades"]
col_comercial_equipe = db["comercial_equipe"]
col_comercial_meta = db["comercial_meta"]
col_comercial_timesheet = db["comercial_timesheet"]
col_comercial_atas = db["comercial_atas"]
col_comercial_snapshot_anterior = db["comercial_snapshot_anterior"]
col_processos_excluidos = db["processos_excluidos"]
col_varreduras_email = db["varreduras_email"]


def _init_db():
    col_processos.create_index([("atualizadoEm", DESCENDING)])
    col_varreduras_email.create_index([("criadoEm", DESCENDING)])
    col_anexos.create_index([("processo_id", ASCENDING), ("enviado_em", DESCENDING)])
    col_relatorios.create_index([("criadoEm", DESCENDING)])
    col_snapshots.create_index([("criadoEm", DESCENDING)])
    col_gastos.create_index([("criadoEm", DESCENDING)])
    col_sinki.create_index([("atualizadoEm", DESCENDING)])
    col_correcoes.create_index([("processo_id", ASCENDING)])
    col_correcoes.create_index([("atualizadoEm", DESCENDING)])
    col_pendentes.create_index([("situacao", ASCENDING), ("detectadoEm", ASCENDING)])
    # a caixa de entrada de cada pessoa é filtrada por destinatário e ordenada
    # por data; e as gerais são lidas por todo mundo
    col_notificacoes.create_index([("destinatarios", ASCENDING), ("criadoEm", DESCENDING)])
    col_notificacoes.create_index([("tipo", ASCENDING), ("criadoEm", DESCENDING)])
    col_comercial_oportunidades.create_index([("data", ASCENDING)])
    col_comercial_atas.create_index([("data", DESCENDING)])


# ──────────────────────────────────────────────────────────────────
# util
# ──────────────────────────────────────────────────────────────────
def _agora_ms():
    return int(time.time() * 1000)


def _slug(texto):
    s = (texto or "").lower()
    s = re.sub(r"[àáâãä]", "a", s); s = re.sub(r"[èéêë]", "e", s)
    s = re.sub(r"[ìíîï]", "i", s);  s = re.sub(r"[òóôõö]", "o", s)
    s = re.sub(r"[ùúûü]", "u", s);  s = re.sub(r"[ç]", "c", s)
    s = re.sub(r"[^a-z0-9]+", "-", s).strip("-")
    return s[:60] or ("proc-" + uuid.uuid4().hex[:8])


def _resumo_do_doc(doc):
    return {
        "id": doc["_id"],
        "nome": doc.get("nome") or "(sem nome)",
        "type": doc.get("type") or "publico",
        "status": doc.get("status") or "em_analise",
        # 1 Prospecção / 2 Validação (Fabrício) / 3 Documentação / 4 (indefinido
        # ainda) -- processo antigo, gravado antes deste campo existir, entra
        # como 1 (mesma regra de fallback usada nos outros campos aqui).
        "fase": int(doc.get("fase") or 1),
        "progress": int(doc.get("progress") or 0),
        "origem": doc.get("origem") or "manual",
        "fontes": doc.get("fontes") or "",
        "atualizadoEm": doc.get("atualizadoEm") or 0,
        "atualizadoPor": doc.get("atualizadoPor") or "",
        "versao": doc.get("versao") or 1,
    }


def _sem_id_mongo(doc):
    doc = dict(doc)
    doc["id"] = doc.pop("_id")
    return doc


@app.after_request
def _add_cors(resp):
    for k, v in CORS_HEADERS.items():
        resp.headers[k] = v
    return resp


# ──────────────────────────────────────────────────────────────────
# contas por pessoa
# ──────────────────────────────────────────────────────────────────
# Antes havia um único usuário e senha para a empresa inteira, e o nome de quem
# fez cada coisa era digitado à mão no navegador — ou seja, "atualizadoPor" não
# provava nada. Login por e-mail+senha próprio existiu por um commit e foi
# abandonado: checar se o e-mail só TERMINA em @sinape.com.br não prova que a
# conta é real. Quem cria e confirma a identidade agora é o login Microsoft
# (auth_callback, abaixo) — a senha compartilhada (sinape_admin) segue valendo
# em paralelo enquanto a equipe migra.
DOMINIO_PERMITIDO = os.environ.get("DOMINIO_EMAIL", "@sinape.com.br").lower()
MAX_TENTATIVAS = 8            # por e-mail/usuário
JANELA_TENTATIVAS_S = 15 * 60


def _site_auth_enabled():
    return bool(SITE_USER and SITE_PASSWORD)


def _logged_in():
    return session.get("site_auth") is True


def _email_valido(email: str) -> bool:
    """Aceita só e-mail do domínio da empresa. A comparação é no fim da string
    de propósito: 'x@sinape.com.br.invasor.com' não pode passar. Usada como
    segunda camada depois do login Microsoft — a primeira é o próprio tenant."""
    email = (email or "").strip().lower()
    if not email.endswith(DOMINIO_PERMITIDO):
        return False
    local = email[: -len(DOMINIO_PERMITIDO)]
    return bool(re.fullmatch(r"[a-z0-9][a-z0-9._%+-]*", local))


# tentativas por identificador, em memória: some quando o processo reinicia, o
# que é aceitável para travar força bruta sem depender de mais infraestrutura
_tentativas: dict[str, list] = {}


def _bloqueado(chave: str) -> int:
    """Segundos que faltam para liberar, ou 0 se pode tentar."""
    agora = time.time()
    marcas = [t for t in _tentativas.get(chave, []) if agora - t < JANELA_TENTATIVAS_S]
    _tentativas[chave] = marcas
    if len(marcas) < MAX_TENTATIVAS:
        return 0
    return int(JANELA_TENTATIVAS_S - (agora - marcas[0]))


def _registrar_tentativa(chave: str):
    _tentativas.setdefault(chave, []).append(time.time())


def _abrir_sessao(email: str, nome: str, admin: bool = False):
    session.permanent = True
    session["site_auth"] = True
    session["usuario_email"] = email
    session["usuario_nome"] = nome
    session["usuario_admin"] = admin
    _tentativas.pop(email, None)


def _auth_ms_habilitado() -> bool:
    return bool(AUTH_TENANT_ID and AUTH_CLIENT_ID and AUTH_CLIENT_SECRET and AUTH_REDIRECT_URI)


def _auth_ms_app(token_cache=None):
    return msal.ConfidentialClientApplication(
        AUTH_CLIENT_ID,
        authority=f"https://login.microsoftonline.com/{AUTH_TENANT_ID}",
        client_credential=AUTH_CLIENT_SECRET,
        token_cache=token_cache,
    )


# Escopos extras (além do User.Read, que só confirma identidade) usados só
# pelo Painel de E-mails — pedidos no mesmo login, com consentimento próprio
# do usuário (delegado, não exige admin do Azure, ao contrário de permissão
# app-only). Ficam junto do User.Read porque o MSAL guarda tudo no mesmo
# token cache por conta. Mail.Send entrou depois do Mail.Read -- quem já
# tinha logado antes vê a tela de consentimento de novo uma vez, porque o
# conjunto de permissões pedido mudou.
ESCOPOS_LOGIN_MS = ["User.Read", "Mail.Read", "Mail.Send"]


def _token_graph_mail(email, escopos):
    """Devolve um access token com os escopos pedidos pra ESTE usuário, renovando
    sozinho via refresh token quando o access token já expirou (acquire_token_silent).
    None quando o usuário nunca concedeu esses escopos ainda (login antigo, antes
    deles existirem, ou entrou pela conta compartilhada) -- nesse caso precisa
    logar de novo uma vez pra ver a tela de consentimento."""
    if not email:
        return None
    u = col_usuarios.find_one({"_id": email}) or {}
    cache_serializado = u.get("msTokenCache")
    if not cache_serializado:
        return None
    cache = msal.SerializableTokenCache()
    cache.deserialize(cache_serializado)
    app_ms = _auth_ms_app(token_cache=cache)
    contas = app_ms.get_accounts()
    if not contas:
        return None
    resultado = app_ms.acquire_token_silent(escopos, account=contas[0])
    if cache.has_state_changed:
        col_usuarios.update_one({"_id": email}, {"$set": {"msTokenCache": cache.serialize()}})
    if not resultado or "access_token" not in resultado:
        return None
    return resultado["access_token"]


@app.route("/auth/entrar")
def auth_entrar():
    """Ponto de partida do login Microsoft — manda a pessoa pro login.microsoftonline.com
    da própria empresa. Ela nunca digita a senha da Microsoft aqui dentro."""
    if not _auth_ms_habilitado():
        return jsonify({"erro": "Login com Microsoft não configurado neste servidor."}), 503
    # 'state' vai e volta pra provar que a resposta é da mesma pessoa que saiu
    # daqui — sem isso, alguém poderia colar um "code" roubado no /auth/callback
    estado = uuid.uuid4().hex
    session["auth_state"] = estado
    session["auth_next"] = _safe_next_url(request.args.get("next"))
    try:
        url = _auth_ms_app().get_authorization_request_url(
            scopes=ESCOPOS_LOGIN_MS, state=estado, redirect_uri=AUTH_REDIRECT_URI,
        )
    except Exception as e:
        # tenant mal configurado ou a Microsoft fora do ar: quem clicou no
        # botão não pode ver um erro 500 cru — volta pro login com explicação
        print(f"[auth] falha ao montar a URL de login Microsoft: {e!r}", flush=True)
        return redirect("/login?erro=" + quote(
            "Não consegui contactar o login Microsoft agora. Tente de novo em instantes "
            "ou entre pelo usuário compartilhado."))
    return redirect(url)


@app.route("/auth/callback")
def auth_callback():
    """A Microsoft manda a pessoa de volta pra cá depois do login dela. O que
    prova que a conta é real e do tenant certo é o token que a Microsoft
    devolve — não é nada que a gente pediu pra pessoa digitar."""
    def falhou(msg):
        return redirect("/login?erro=" + quote(msg))

    if not _auth_ms_habilitado():
        return redirect("/login")

    erro_ms = request.args.get("error_description") or request.args.get("error")
    if erro_ms:
        return falhou("A Microsoft não autorizou o login: " + erro_ms[:200])

    if not request.args.get("state") or request.args.get("state") != session.pop("auth_state", None):
        return falhou("A sessão de login expirou ou é inválida. Tente entrar de novo.")

    codigo = request.args.get("code")
    if not codigo:
        return redirect("/login")

    # cache próprio pra esta troca -- é ele que vai carregar o refresh token
    # que o Painel de E-mails usa depois, silenciosamente, sem pedir login de novo
    cache = msal.SerializableTokenCache()
    try:
        resultado = _auth_ms_app(token_cache=cache).acquire_token_by_authorization_code(
            codigo, scopes=ESCOPOS_LOGIN_MS, redirect_uri=AUTH_REDIRECT_URI,
        )
    except Exception as e:
        print(f"[auth] falha ao trocar o código pelo token: {e!r}", flush=True)
        return falhou("Não consegui confirmar seu login com a Microsoft agora. Tente de novo.")
    if "id_token_claims" not in resultado:
        return falhou("Não foi possível confirmar sua conta Microsoft. Tente de novo.")

    claims = resultado["id_token_claims"]
    email = (claims.get("preferred_username") or claims.get("email") or "").strip().lower()
    nome = claims.get("name") or email

    # o tenant do app já restringe quem consegue chegar até aqui, mas confere
    # o domínio mesmo assim — segunda camada, barata, contra um tenant mal
    # configurado ou um convidado externo dentro da organização
    if not _email_valido(email):
        return falhou(f"Sua conta Microsoft não é do domínio {DOMINIO_PERMITIDO}.")

    existente = col_usuarios.find_one({"_id": email})
    if existente and not existente.get("ativo", True):
        return falhou("Sua conta foi desativada. Fale com o administrador do Painel.")

    # o Mail.Read pode não ter sido concedido (ex.: usuário recusou naquela
    # tela específica de consentimento, mesmo aceitando o login) -- nesse caso
    # não sobrescreve um cache anterior válido com um sem o escopo
    campos_set = {"nome": nome, "ultimoAcesso": _agora_ms(), "via": "microsoft"}
    if "access_token" in resultado:
        campos_set["msTokenCache"] = cache.serialize()
    col_usuarios.update_one(
        {"_id": email},
        {
            "$set": campos_set,
            "$setOnInsert": {"criadoEm": _agora_ms(), "ativo": True, "admin": False},
        },
        upsert=True,
    )
    u = col_usuarios.find_one({"_id": email})
    _abrir_sessao(email, nome, admin=bool(u.get("admin")))
    return redirect(session.pop("auth_next", None) or "/")


def _safe_next_url(val):
    if val and val.startswith("/") and not val.startswith("//"):
        return val
    return "/"


# /api/processos/<pid>/anexos/<aid> — e só isso. Os ids não podem conter barra,
# senão a expressão deixaria passar caminho de sub-rota que não é download.
_PADRAO_BAIXAR_ANEXO = re.compile(r"^/api/processos/[^/]+/anexos/[^/]+$")


@app.before_request
def _auth():
    if request.method == "OPTIONS":
        return ("", 204)

    if request.path == "/api/health":
        return None

    # as rotas /auth/* ficam fora da barreira porque quem está entrando ainda
    # não tem sessão — a proteção delas é a própria Microsoft confirmando a conta
    if request.path in ("/login", "/logout", "/auth/entrar", "/auth/callback"):
        return None

    if _site_auth_enabled() and not _logged_in():
        if request.path.startswith("/api/"):
            return jsonify({"erro": "Não autenticado — faça login"}), 401
        next_path = request.path
        if request.query_string:
            next_path += "?" + request.query_string.decode("utf-8")
        return redirect("/login?next=" + quote(next_path, safe="/?=&"))

    if request.path.startswith("/api/"):
        # Baixar anexo é a única coisa que o navegador abre por navegação (um
        # link, ou "abrir em nova aba"), e navegação não manda header nenhum —
        # o token só existe no fetch. Sem esta exceção, clicar no anexo dava
        # {"erro":"Token ausente ou inválido"} como página crua, que foi o que
        # o Bruno viu ao mexer numa planilha. A sessão continua obrigatória
        # (checada logo acima), e vale só pro GET: excluir anexo segue exigindo
        # token como todo o resto.
        if not (request.method == "GET" and _PADRAO_BAIXAR_ANEXO.match(request.path)):
            if not TOKEN or request.headers.get("x-sinape-token") != TOKEN:
                return jsonify({"erro": "Token ausente ou inválido"}), 401

    return None


# ──────────────────────────────────────────────────────────────────
# login do site
# ──────────────────────────────────────────────────────────────────
@app.route("/login", methods=["GET", "POST"])
def login():
    if not _site_auth_enabled():
        return redirect("/")
    if _logged_in():
        return redirect(_safe_next_url(request.args.get("next")))
    if request.method == "POST":
        usuario = (request.form.get("usuario", "") or "").strip()
        senha = request.form.get("senha", "")
        destino = _safe_next_url(request.form.get("next"))

        def falhou(msg="1"):
            return redirect(f"/login?erro={quote(msg)}&next=" + quote(destino))

        chave = usuario.lower()
        faltam = _bloqueado(chave)
        if faltam:
            return falhou(f"Muitas tentativas. Tente de novo em {faltam // 60 + 1} minuto(s).")

        # login compartilhado — a única porta por senha que resta. Contas por
        # pessoa entram por /auth/entrar (Microsoft), nunca por aqui.
        if usuario == SITE_USER and senha == SITE_PASSWORD:
            _abrir_sessao("", SITE_USER, admin=True)
            return redirect(destino)

        _registrar_tentativa(chave)
        return falhou()
    return send_from_directory(BASE_DIR, "login.html")


NOME_CONTA_COMPARTILHADA = "Conta compartilhada"


def _autor_da_sessao():
    """Mesma regra de /api/eu: quem assina uma ação é decidido no servidor,
    não digitado na tela — conta compartilhada nunca assina como pessoa."""
    return session.get("usuario_nome") or NOME_CONTA_COMPARTILHADA


@app.route("/api/eu", methods=["GET"])
def quem_sou_eu():
    """Identidade de quem está logado — a tela usa isto em vez de perguntar o
    nome, que antes era digitado e não provava nada.

    'autor' é o que vai assinar o que a pessoa fizer, e sai daqui em vez de
    ser decidido na tela: quem entrou pela conta compartilhada assina como
    conta compartilhada, não como uma pessoa. Deixar essa sessão escolher um
    nome faria qualquer um assinar como qualquer um — e aí 'atualizado por
    Fabrício' não provaria que foi o Fabrício."""
    email = session.get("usuario_email") or ""
    nome = session.get("usuario_nome") or ""
    return jsonify({
        "email": email,
        "nome": nome,
        "admin": bool(session.get("usuario_admin")),
        "compartilhado": not email,
        "autor": nome if email else NOME_CONTA_COMPARTILHADA,
    })


@app.route("/api/usuarios", methods=["GET"])
def listar_usuarios():
    """Quem já entrou no Painel com conta própria — é a lista de gente que dá
    pra endereçar (notificar, atribuir).

    A lista se preenche sozinha no primeiro login de cada pessoa pela
    Microsoft; não há cadastro pra ninguém manter. Quem nunca entrou não
    aparece, e é correto que não apareça: mandar recado pra uma caixa que
    ninguém nunca abriu é o mesmo que não mandar.

    A conta compartilhada fica de fora de propósito — ela não é uma pessoa."""
    cursor = col_usuarios.find({"ativo": {"$ne": False}}, {"nome": 1, "ultimoAcesso": 1})
    usuarios = [
        {"email": u["_id"], "nome": u.get("nome") or u["_id"],
         "ultimoAcesso": u.get("ultimoAcesso") or 0}
        for u in cursor if u.get("_id")
    ]
    usuarios.sort(key=lambda u: u["nome"].lower())
    return jsonify({"usuarios": usuarios})


# ──────────────────────────────────────────────────────────────────
# notificações entre a equipe
# ──────────────────────────────────────────────────────────────────
# siglas que aparecem no campo Órgão mas não identificam ninguém
_SIGLAS_INUTEIS = {"CNPJ", "CPF", "LTDA", "EPP", "ME", "SA", "EIRELI", "S.A"}
_PALAVRAS_VAZIAS = {"de", "da", "do", "das", "dos", "e"}


def _rotulo_curto(doc):
    """Identificação curta do processo pra caber numa notificação: algo como
    "DNIT · PR · 17/08" ou "EPR · PR · 12/09".

    O campo Órgão é longo demais pra usar inteiro — os valores reais são do
    tipo "EPR Litoral Pioneiro S.A. (Concessionária de Rodovias — Lote 2 do
    Paraná) — CNPJ 51.137.031/0001-20". A sigla é o que a equipe usa pra
    falar do processo, então ela vem primeiro quando existe; sem sigla,
    valem as duas primeiras palavras; sem órgão nenhum, o nome do processo."""
    a = doc.get("analise") or {}
    orgao = (a.get("geral_orgao") or "").strip()

    nome = ""
    if orgao:
        siglas = [s for s in re.findall(r"\b[A-ZÀ-Ú]{2,}\b", orgao)
                  if s.upper() not in _SIGLAS_INUTEIS]
        if siglas:
            nome = siglas[0]
        else:
            # sem sigla: corta no primeiro parêntese/travessão, porque dali pra
            # frente vem razão social e CNPJ, que não ajudam a reconhecer nada
            base = re.split(r"[(—–]|\s-\s", orgao)[0]
            palavras = [p for p in base.split()
                        if p.lower() not in _PALAVRAS_VAZIAS
                        and p.strip(".").upper() not in _SIGLAS_INUTEIS]
            nome = " ".join(palavras[:2])
    if not nome:
        nome = (doc.get("nome") or "Processo").strip()[:40]

    partes = [nome]
    uf = (a.get("geral_uf") or "").strip()
    if uf:
        partes.append(uf)
    data = (a.get("prazo_abertura") or a.get("geral_abertura") or "").strip()
    m = re.match(r"^(\d{4})-(\d{2})-(\d{2})$", data)
    if m:
        partes.append(f"{m.group(3)}/{m.group(2)}")
    return " · ".join(partes)


def _sessao_pessoa():
    """(email, nome) de quem está logado. E-mail vazio = conta compartilhada,
    que não é ninguém em particular."""
    return (session.get("usuario_email") or "").strip().lower(), (session.get("usuario_nome") or "")


def _emails_ativos():
    return {u["_id"] for u in col_usuarios.find({"ativo": {"$ne": False}}, {"_id": 1}) if u.get("_id")}


@app.route("/api/notificacoes", methods=["POST"])
def criar_notificacao():
    """Avisa a equipe (ou alguém específico) do que mudou num processo.

    Um envio cobre a SESSÃO de edição inteira, não um campo. Perguntar
    "avisar quem?" a cada campo salvo cansaria em uma semana — e aí ou
    ninguém usa, ou manda tudo pra todo mundo e a caixa geral vira ruído.

    O tipo é escolhido por intenção, não pelo tamanho da lista: "equipe" é
    informativo, "dirigida" pede conferência. Deduzir isso de quantas pessoas
    foram marcadas seria frágil — com 5 na equipe, mandar pra 4 e pra 5 cairia
    em caixas diferentes sem ninguém perceber, e a entrada do 6º usuário mudaria
    a classificação de envios idênticos."""
    email, nome = _sessao_pessoa()
    if not email:
        return jsonify({"erro": "Entre com sua conta Microsoft para enviar notificação — "
                                "a conta compartilhada não identifica quem está avisando."}), 403

    corpo = request.get_json(silent=True) or {}
    pid = (corpo.get("processo_id") or "").strip()
    processo = col_processos.find_one({"_id": pid}) if pid else None
    if not processo:
        return jsonify({"erro": "Processo não encontrado"}), 404

    mudancas = corpo.get("mudancas")
    if not isinstance(mudancas, list) or not mudancas:
        return jsonify({"erro": "Informe as mudanças que motivaram o aviso."}), 400

    tipo = corpo.get("tipo")
    if tipo not in ("equipe", "dirigida"):
        return jsonify({"erro": "tipo deve ser 'equipe' ou 'dirigida'."}), 400

    ativos = _emails_ativos()
    if tipo == "dirigida":
        pedidos = [str(d).strip().lower() for d in (corpo.get("destinatarios") or [])]
        # quem enviou não precisa ser avisado do que ele mesmo fez
        destinatarios = sorted({d for d in pedidos if d in ativos and d != email})
        if not destinatarios:
            return jsonify({"erro": "Escolha ao menos uma pessoa (fora você) para conferir."}), 400
    else:
        destinatarios = sorted(ativos - {email})

    doc = {
        "_id": uuid.uuid4().hex,
        "tipo": tipo,
        "processo_id": pid,
        "processo_nome": processo.get("nome") or "",
        "processo_rotulo": _rotulo_curto(processo),
        "autor_email": email,
        "autor_nome": nome or email,
        "destinatarios": destinatarios,
        # antes e depois de cada item, não só "mudou": sem isso, abrir a
        # notificação não mostra nada útil — e se alguém editar o mesmo campo
        # por cima, o que estava lá some pra sempre
        "mudancas": [
            {"rotulo": str(m.get("rotulo") or "")[:200],
             "antes": str(m.get("antes") or "")[:800],
             "depois": str(m.get("depois") or "")[:800]}
            for m in mudancas[:40]
        ],
        "criadoEm": _agora_ms(),
        "leituras": {},
        "respostas": [],
    }
    col_notificacoes.insert_one(doc)
    return jsonify(_sem_id_mongo(doc)), 201


@app.route("/api/notificacoes/<nid>/responder", methods=["POST"])
def responder_notificacao(nid):
    """OK ou comentário numa notificação dirigida, e o retorno pra quem avisou.

    O retorno só existe nas dirigidas de propósito: num aviso pra equipe
    inteira, esperar confirmação de todo mundo daria cinco confirmações por
    mudança — ninguém faria, e em duas semanas o "CONFIRA" não significaria
    mais nada."""
    email, nome = _sessao_pessoa()
    if not email:
        return jsonify({"erro": "Entre com sua conta Microsoft para responder."}), 403

    n = col_notificacoes.find_one({"_id": nid})
    if not n:
        return jsonify({"erro": "Notificação não encontrada"}), 404
    if email not in (n.get("destinatarios") or []):
        return jsonify({"erro": "Esta notificação não foi endereçada a você."}), 403
    if n.get("tipo") != "dirigida":
        return jsonify({"erro": "Só notificação dirigida pede conferência."}), 400

    corpo = request.get_json(silent=True) or {}
    texto = (corpo.get("texto") or "").strip()
    resposta = "comentario" if texto else "ok"

    col_notificacoes.update_one(
        {"_id": nid},
        {"$set": {f"leituras.{_chave_leitura(email)}": _agora_ms()},
         "$push": {"respostas": {"email": email, "nome": nome or email,
                                 "resposta": resposta, "texto": texto[:2000],
                                 "em": _agora_ms()}}},
    )

    # o retorno vira uma notificação de verdade pra quem avisou, pra caber na
    # mesma caixa de entrada em vez de virar um segundo lugar pra olhar
    col_notificacoes.insert_one({
        "_id": uuid.uuid4().hex,
        "tipo": "retorno",
        "origem_id": nid,
        "processo_id": n.get("processo_id"),
        "processo_nome": n.get("processo_nome"),
        "processo_rotulo": n.get("processo_rotulo"),
        "autor_email": email,
        "autor_nome": nome or email,
        "destinatarios": [n["autor_email"]],
        "resposta": resposta,
        "mudancas": ([{"rotulo": "Comentário", "antes": "", "depois": texto[:2000]}]
                     if texto else []),
        "criadoEm": _agora_ms(),
        "leituras": {},
        "respostas": [],
    })
    return jsonify({"ok": True, "resposta": resposta})


def _chave_leitura(email):
    # ponto é separador de caminho no Mongo; e-mail tem ponto
    return email.replace(".", "__")


def _notificacao_para_tela(n, email):
    lida = _chave_leitura(email) in (n.get("leituras") or {})
    return {
        "id": n["_id"],
        "tipo": n.get("tipo"),
        "processo_id": n.get("processo_id"),
        "processo_rotulo": n.get("processo_rotulo") or n.get("processo_nome") or "",
        "autor_nome": n.get("autor_nome") or "",
        "autor_email": n.get("autor_email") or "",
        "mudancas": n.get("mudancas") or [],
        "resposta": n.get("resposta") or "",
        "respostas": n.get("respostas") or [],
        "criadoEm": n.get("criadoEm") or 0,
        "lida": lida,
        "respondida": any(r.get("email") == email for r in (n.get("respostas") or [])),
    }


@app.route("/api/notificacoes", methods=["GET"])
def listar_notificacoes():
    """Caixa de entrada de quem está logado, nas duas prateleiras.

    Geral = avisos pra equipe. Pessoal = o que foi endereçado a você
    (conferências pedidas e retornos das suas), agrupado por quem mandou."""
    email, _nome = _sessao_pessoa()
    if not email:
        # a conta compartilhada não é ninguém: não tem caixa de entrada
        return jsonify({"gerais": [], "pessoais": [], "porRemetente": [],
                        "naoLidasGerais": 0, "naoLidasPessoais": 0, "compartilhado": True})

    gerais = [_notificacao_para_tela(n, email) for n in col_notificacoes.find(
        {"tipo": "equipe", "destinatarios": email}).sort("criadoEm", DESCENDING).limit(100)]
    pessoais = [_notificacao_para_tela(n, email) for n in col_notificacoes.find(
        {"tipo": {"$in": ["dirigida", "retorno"]}, "destinatarios": email}
    ).sort("criadoEm", DESCENDING).limit(200)]

    # agrupado por quem mandou, com quantas faltam ler de cada um — o número
    # cai conforme a pessoa abre cada item, não ao abrir a aba
    porRemetente = {}
    for p in pessoais:
        g = porRemetente.setdefault(p["autor_email"], {
            "email": p["autor_email"], "nome": p["autor_nome"], "total": 0, "naoLidas": 0})
        g["total"] += 1
        if not p["lida"]:
            g["naoLidas"] += 1
    remetentes = sorted(porRemetente.values(), key=lambda g: (-g["naoLidas"], g["nome"].lower()))

    return jsonify({
        "gerais": gerais,
        "pessoais": pessoais,
        "porRemetente": remetentes,
        "naoLidasGerais": sum(1 for g in gerais if not g["lida"]),
        "naoLidasPessoais": sum(1 for p in pessoais if not p["lida"]),
        "compartilhado": False,
    })


@app.route("/api/notificacoes/<nid>/lida", methods=["POST"])
def marcar_notificacao_lida(nid):
    """Marca como lida ao ABRIR o item — não ao abrir a aba. Zerar tudo só
    porque a pessoa espiou a caixa faria o contador mentir."""
    email, _nome = _sessao_pessoa()
    if not email:
        return jsonify({"erro": "Sessão sem identificação."}), 403
    r = col_notificacoes.update_one(
        {"_id": nid, "destinatarios": email},
        {"$set": {f"leituras.{_chave_leitura(email)}": _agora_ms()}})
    if not r.matched_count:
        return jsonify({"erro": "Notificação não encontrada"}), 404
    return jsonify({"ok": True})


@app.route("/logout", methods=["GET", "POST"])
def logout():
    session.clear()
    if _site_auth_enabled():
        return redirect("/login")
    return redirect("/")


# ──────────────────────────────────────────────────────────────────
# páginas estáticas
# ──────────────────────────────────────────────────────────────────
@app.route("/")
def index():
    return send_from_directory(BASE_DIR, "index.html")


@app.route("/chart.umd.min.js")
def chart_js():
    """Chart.js hospedado dentro do projeto (v4.4.0, mesma do painel comercial
    original) — carregado só quando a área Comercial abre uma página de
    indicador, não no carregamento normal do Painel. Hospedado localmente,
    e não via CDN, porque o app inteiro hoje não depende de nada externo;
    um CDN fora do ar não pode tirar os gráficos do ar."""
    return send_from_directory(BASE_DIR, "chart.umd.min.js", mimetype="application/javascript")


@app.route("/api/health")
def health():
    return jsonify({"ok": True})


# ──────────────────────────────────────────────────────────────────
# processos
# ──────────────────────────────────────────────────────────────────
@app.route("/api/processos", methods=["GET"])
def listar():
    docs = col_processos.find().sort("atualizadoEm", DESCENDING)
    processos = [_resumo_do_doc(d) for d in docs]
    return jsonify({"processos": processos})


@app.route("/api/processos", methods=["POST"])
def criar():
    doc = request.get_json(force=True, silent=False)
    if not isinstance(doc, dict):
        return jsonify({"erro": "Corpo deve ser um objeto JSON"}), 400
    try:
        doc = _preparar_e_inserir_processo(doc)
    except DuplicateKeyError:
        return jsonify({"erro": "Já existe processo com esse id", "id": doc.get("_id")}), 409
    return jsonify(_sem_id_mongo(doc)), 201


@app.route("/api/processos/<pid>", methods=["GET"])
def obter(pid):
    doc = col_processos.find_one({"_id": pid})
    if not doc:
        return jsonify({"erro": "Processo não encontrado"}), 404
    return jsonify(_sem_id_mongo(doc))


@app.route("/api/processos/<pid>", methods=["PUT"])
def substituir(pid):
    doc = request.get_json(force=True, silent=False)
    if not isinstance(doc, dict):
        return jsonify({"erro": "Corpo deve ser um objeto JSON"}), 400
    doc["id"] = pid
    doc["atualizadoEm"] = _agora_ms()
    doc["versao"] = int(doc.get("versao") or 1)

    doc["_id"] = pid
    del doc["id"]
    col_processos.replace_one({"_id": pid}, doc, upsert=True)
    _sync_oportunidade_do_processo(doc)
    return jsonify(_sem_id_mongo(doc))


def _capturar_correcoes(doc_antes: dict, campos_tocados: dict):
    """Registra o par (resposta original da IA / valor que a equipe deixou) pra
    cada campo da análise que a equipe editou nesta requisição — vira material
    de treino no futuro. Só se aplica a processo que nasceu de IA (tem
    '_analiseOriginalIA' guardado); processo manual não tem o que comparar.
    Se a equipe editar e depois voltar pro valor original, some o registro —
    não é mais uma correção."""
    baseline = doc_antes.get("_analiseOriginalIA")
    if baseline is None or not campos_tocados:
        return
    processo_id = doc_antes["_id"]
    processo_nome = doc_antes.get("nome") or ""
    modelo_ia = doc_antes.get("_iaModel") or ""
    esforco_ia = doc_antes.get("_iaEsforco") or ""
    fontes = doc_antes.get("analise", {}).get("_sourceFiles") or doc_antes.get("fontes") or ""
    for campo, valor_novo in campos_tocados.items():
        chave_registro = f"{processo_id}::{campo}"
        valor_ia = baseline.get(campo, "")
        if valor_novo == valor_ia:
            col_correcoes.delete_one({"_id": chave_registro})
            continue
        col_correcoes.replace_one({"_id": chave_registro}, {
            "_id": chave_registro, "processo_id": processo_id, "processo_nome": processo_nome,
            "campo": campo, "modelo_ia": modelo_ia, "esforco_ia": esforco_ia, "fontes": fontes,
            "valor_ia": valor_ia, "valor_atual": valor_novo,
            "criadoEm": _agora_ms(), "atualizadoEm": _agora_ms(),
        }, upsert=True)


@app.route("/api/processos/<pid>", methods=["PATCH"])
def patch(pid):
    corpo = request.get_json(force=True, silent=False)
    if not isinstance(corpo, dict):
        return jsonify({"erro": "Corpo deve ser um objeto JSON"}), 400
    se_versao = corpo.get("seVersao")

    doc = col_processos.find_one({"_id": pid})
    if not doc:
        return jsonify({"erro": "Processo não encontrado"}), 404
    versao_atual = doc.get("versao") or 1

    if se_versao is not None and int(se_versao) != versao_atual:
        return jsonify(_sem_id_mongo(doc)), 409  # painel mescla e tenta de novo

    for chave, valor in (corpo.get("metaPatch") or {}).items():
        if chave in ("id", "_id", "versao", "doc"):
            continue
        doc[chave] = valor
    if corpo.get("analisePatch"):
        doc.setdefault("analise", {}).update(corpo["analisePatch"])
        _capturar_correcoes(doc, corpo["analisePatch"])
    if corpo.get("checklistPatch"):
        doc.setdefault("checklist", {}).update(corpo["checklistPatch"])
    if corpo.get("schemaCustom") is not None:
        doc["schemaCustom"] = corpo["schemaCustom"]

    nova_versao = versao_atual + 1
    agora = _agora_ms()
    doc["versao"] = nova_versao
    doc["atualizadoEm"] = agora

    resultado = col_processos.replace_one({"_id": pid, "versao": versao_atual}, doc)
    if resultado.matched_count == 0:
        atual = col_processos.find_one({"_id": pid})
        return jsonify(_sem_id_mongo(atual)), 409  # alterado por outra requisição nesse meio-tempo

    _sync_oportunidade_do_processo(doc)
    return jsonify({"versao": nova_versao, "atualizadoEm": agora})


@app.route("/api/processos/<pid>", methods=["DELETE"])
def excluir(pid):
    """Exclusão vai pra lixeira (col_processos_excluidos), não some de vez —
    só assim dá pra oferecer 'Restaurar' na tela sem perder nada. Por isso,
    diferente de antes, NÃO apaga anexos nem a pasta de documentos de
    concorrente aqui: ficam esperando no disco, prontos pra voltar junto se
    o processo for restaurado. Só um expurgo de verdade (que não existe
    ainda — ninguém pediu) apagaria esses arquivos."""
    doc = col_processos.find_one({"_id": pid})
    if not doc:
        return jsonify({"erro": "Processo não encontrado"}), 404
    doc["excluidoEm"] = _agora_ms()
    doc["excluidoPor"] = _autor_da_sessao()
    col_processos_excluidos.replace_one({"_id": pid}, doc, upsert=True)
    col_processos.delete_one({"_id": pid})
    return jsonify({"ok": True})


@app.route("/api/processos/excluidos", methods=["GET"])
def listar_processos_excluidos():
    """Lixeira: processos excluídos, disponíveis pra restaurar."""
    docs = col_processos_excluidos.find().sort("excluidoEm", DESCENDING)
    itens = [{"id": d["_id"], "nome": d.get("nome"), "type": d.get("type"),
              "excluidoEm": d.get("excluidoEm"), "excluidoPor": d.get("excluidoPor") or ""}
             for d in docs]
    return jsonify({"processos": itens})


@app.route("/api/processos/excluidos/<pid>/restaurar", methods=["POST"])
def restaurar_processo(pid):
    """Desfaz a exclusão. Anexos e verificações de concorrente voltam juntos
    intactos, porque excluir() nunca chegou a tocar neles."""
    doc = col_processos_excluidos.find_one({"_id": pid})
    if not doc:
        return jsonify({"erro": "Processo não está na lixeira."}), 404
    doc.pop("excluidoEm", None)
    doc.pop("excluidoPor", None)
    doc["versao"] = int(doc.get("versao") or 1) + 1
    doc["atualizadoEm"] = _agora_ms()
    col_processos.replace_one({"_id": pid}, doc, upsert=True)
    col_processos_excluidos.delete_one({"_id": pid})
    return jsonify(_sem_id_mongo(doc))


@app.route("/api/processos/excluidos/<pid>", methods=["DELETE"])
def expurgar_processo(pid):
    """Apaga de vez um processo que já estava na lixeira — esse, sim, sem
    volta: some o registro e todo arquivo associado (anexos e pasta de
    verificação de concorrente). Só se aplica a quem já passou pela lixeira;
    excluir() nunca apaga direto, sempre passa por aqui antes."""
    doc = col_processos_excluidos.find_one({"_id": pid})
    if not doc:
        return jsonify({"erro": "Processo não está na lixeira."}), 404
    for anexo in col_anexos.find({"processo_id": pid}):
        (UPLOAD_DIR / pid / anexo["nome_arquivo"]).unlink(missing_ok=True)
    col_anexos.delete_many({"processo_id": pid})
    shutil.rmtree(UPLOAD_DIR / pid, ignore_errors=True)
    shutil.rmtree(CONCORRENTES_DIR / pid, ignore_errors=True)
    col_processos_excluidos.delete_one({"_id": pid})
    return jsonify({"ok": True})


@app.route("/api/processos/<pid>/dossie", methods=["GET"])
def montar_dossie(pid):
    """Monta o dossie de habilitacao do processo (Montador de Dossie,
    integrado ao Painel) e devolve o .zip pronto. Usa a documentacao
    atualizada da SINAPE no SharePoint - nao precisa que a equipe tenha
    copiado nada para dentro da pasta do processo (ver biblioteca v2)."""
    doc = col_processos.find_one({"_id": pid})
    if not doc:
        return jsonify({"erro": "Processo não encontrado"}), 404
    processo = _sem_id_mongo(doc)

    if not (MONTADOR_MODO_LOCAL or (MONTADOR_TENANT_ID and MONTADOR_CLIENT_ID and MONTADOR_CLIENT_SECRET)):
        return jsonify({
            "erro": "Montador não configurado neste servidor. Defina MONTADOR_TENANT_ID, "
                    "MONTADOR_CLIENT_ID e MONTADOR_CLIENT_SECRET (ou MONTADOR_MODO_LOCAL=true "
                    "+ MONTADOR_ONEDRIVE_RAIZ)."
        }), 503

    cfg = {
        "MODO_LOCAL": MONTADOR_MODO_LOCAL,
        "TENANT_ID": MONTADOR_TENANT_ID,
        "CLIENT_ID": MONTADOR_CLIENT_ID,
        "CLIENT_SECRET": MONTADOR_CLIENT_SECRET,
        "ONEDRIVE_RAIZ_SHAREPOINT": MONTADOR_ONEDRIVE_RAIZ,
    }

    analise = processo.setdefault("analise", {})
    if not analise.get("geral_pasta_sharepoint") and not MONTADOR_MODO_LOCAL:
        try:
            achado = localizar_pasta_processo(
                cfg,
                orgao=analise.get("geral_orgao", ""),
                numero=analise.get("geral_numero", ""),
                objeto=analise.get("geral_objeto", ""),
                nome=processo.get("nome", ""),
            )
        except Exception as e:
            return jsonify({"erro": f"Falha ao localizar a pasta do processo no SharePoint: {e}"}), 502

        if not achado["encontrado"]:
            proximos = [c["nome"] for c in achado["candidatos"][:5]]
            return jsonify({
                "erro": "Não consegui identificar sozinho a pasta deste processo no SharePoint. "
                        "Confira se 'Órgão' e 'Nº do Edital/Processo' estão preenchidos e batem com o "
                        "nome da pasta real, ou preencha manualmente o campo da pasta.",
                "candidatos_proximos": proximos,
            }), 404

        url_pasta = f"https://{SITE_HOSTNAME}{SITE_PATH}/Documentos/{achado['caminho']}"
        analise["geral_pasta_sharepoint"] = url_pasta
        col_processos.update_one({"_id": pid}, {"$set": {"analise.geral_pasta_sharepoint": url_pasta}})

    pasta_temp = Path(tempfile.mkdtemp(prefix="dossie-"))
    try:
        zip_destino = montar_dossie_por_processo(
            cfg, MONTADOR_BIBLIOTECA, pid, pasta_temp / pid, processo_preload=processo)
        # le o zip para memoria e limpa a pasta temp AGORA - no Windows, o
        # arquivo fica travado enquanto send_file esta streaming a resposta,
        # entao apagar depois (ex.: via after_this_request) falha silenciosamente
        conteudo_zip = zip_destino.read_bytes()
        nome_zip = zip_destino.name
    except SystemExit as e:
        return jsonify({"erro": str(e)}), 400
    except Exception as e:
        return jsonify({"erro": f"Falha ao montar o dossiê: {e}"}), 502
    finally:
        shutil.rmtree(pasta_temp, ignore_errors=True)

    return Response(
        conteudo_zip,
        mimetype="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{nome_zip}"'},
    )


# ──────────────────────────────────────────────────────────────────
# relatórios ("Atualizações do dia")
# ──────────────────────────────────────────────────────────────────
# ──────────────────────────────────────────────────────────────────
# fila de processos novos esperando análise
# ──────────────────────────────────────────────────────────────────
# Antes a lista de "novos" existia só dentro do último relatório, e a tela só
# mostrava o mais recente. Rodar a varredura duas vezes fazia a segunda virar a
# linha de base e os itens da primeira sumirem sem ninguém decidir nada — foi o
# que engoliu as propostas 048 e 049 da Arteris em 31/07/2026. Agora cada item
# detectado entra numa fila que só sai quando a equipe resolve o que fazer com
# ele: analisar ou dispensar. Varrer de novo não apaga o que está pendente.

def _registrar_pendentes(novos: list):
    """Põe na fila os itens detectados na varredura. Item já conhecido não é
    tocado — nem para reviver o que a equipe já dispensou, nem para perder a
    data em que apareceu pela primeira vez."""
    for item in novos:
        caminho = item.get("caminho_pasta") or ""
        if not caminho:
            continue
        col_pendentes.update_one(
            {"_id": caminho},
            {"$setOnInsert": {
                "_id": caminho,
                "tipo": item.get("tipo") or "",
                "nome": item.get("nome") or "",
                "status": item.get("status"),
                "caminho_pasta": caminho,
                "detectadoEm": _agora_ms(),
                "situacao": "pendente",
            }},
            upsert=True,
        )


def _pendentes_abertos() -> list:
    return [_sem_id_mongo(d) for d in
            col_pendentes.find({"situacao": "pendente"}).sort("detectadoEm", ASCENDING)]


@app.route("/api/pendentes", methods=["GET"])
def listar_pendentes():
    """Fila de processos novos aguardando decisão da equipe."""
    return jsonify({"itens": _pendentes_abertos()})


@app.route("/api/pendentes", methods=["POST"])
def adicionar_pendente():
    """Põe uma pasta do SharePoint na fila de análise à mão. Serve para o que a
    varredura não pega: pasta renomeada, proposta antiga que a equipe decidiu
    analisar agora, ou item perdido por alguma falha — foi o caso das propostas
    048 e 049 da Arteris, que entraram na linha de base antes da fila existir.
    A pasta é conferida no SharePoint antes de entrar: fila com caminho errado
    só produz erro na hora de analisar."""
    corpo = request.get_json(silent=True) or {}
    caminho = (corpo.get("caminho_pasta") or "").strip().strip("/")
    if not caminho:
        return jsonify({"erro": "Informe o caminho_pasta."}), 400

    ja = col_pendentes.find_one({"_id": caminho})
    if ja and ja.get("situacao") == "pendente":
        return jsonify({"erro": "Essa pasta já está na fila."}), 409

    if not (MONTADOR_TENANT_ID and MONTADOR_CLIENT_ID and MONTADOR_CLIENT_SECRET):
        return jsonify({"erro": "SharePoint não configurado neste servidor."}), 503
    cfg = {"MODO_LOCAL": False, "TENANT_ID": MONTADOR_TENANT_ID,
           "CLIENT_ID": MONTADOR_CLIENT_ID, "CLIENT_SECRET": MONTADOR_CLIENT_SECRET}
    try:
        pdfs = baixar_pdfs_da_pasta(cfg, caminho, limite_mb=MAX_PDF_TOTAL_MB)
    except requests.HTTPError as e:
        if e.response is not None and e.response.status_code == 404:
            return jsonify({"erro": "Essa pasta não existe no SharePoint. Confira o caminho."}), 404
        return jsonify({"erro": f"Falha ao conferir a pasta no SharePoint: {e}"}), 502
    except ValueError as e:
        # pasta passa do limite de MB (a mensagem já vem pronta pra tela)
        return jsonify({"erro": str(e)}), 400
    except Exception as e:
        return jsonify({"erro": f"Falha ao conferir a pasta no SharePoint: {e}"}), 502
    if not pdfs:
        return jsonify({"erro": "A pasta existe mas não tem nenhum PDF para analisar."}), 400

    # o tipo sai do próprio caminho: as duas árvores do SharePoint já separam
    # contratação privada de licitação pública
    tipo = corpo.get("tipo") or ("publico" if caminho.startswith("2 - LICITACAO") else "privado")
    item = {
        "tipo": tipo,
        "nome": corpo.get("nome") or caminho.rsplit("/", 1)[-1],
        "status": corpo.get("status"),
        "caminho_pasta": caminho,
    }
    # se já existia como dispensado/analisado, volta para a fila: pedir de novo
    # à mão é uma decisão explícita da equipe
    col_pendentes.delete_one({"_id": caminho})
    _registrar_pendentes([item])
    return jsonify({"ok": True, "item": item, "arquivos": len(pdfs),
                    "restantes": len(_pendentes_abertos())}), 201


@app.route("/api/pendentes/dispensar", methods=["POST"])
def dispensar_pendente():
    """Tira um processo da fila sem analisar — quando a equipe julga que não
    vale a pena. Fica registrado quem dispensou e quando, então dá para
    reverter e o item não volta sozinho na próxima varredura."""
    corpo = request.get_json(silent=True) or {}
    caminho = corpo.get("caminho_pasta") or ""
    if not caminho:
        return jsonify({"erro": "Informe o caminho_pasta do item a dispensar."}), 400
    r = col_pendentes.update_one(
        {"_id": caminho, "situacao": "pendente"},
        {"$set": {"situacao": "dispensado", "dispensadoEm": _agora_ms(),
                  "dispensadoPor": corpo.get("autor") or "",
                  "motivo": (corpo.get("motivo") or "").strip()}},
    )
    if not r.matched_count:
        return jsonify({"erro": "Item não está na fila de pendentes."}), 404
    return jsonify({"ok": True, "restantes": len(_pendentes_abertos())})


@app.route("/api/pendentes/dispensados", methods=["GET"])
def listar_dispensados():
    """Itens que a equipe tirou da fila sem analisar — a tela usa isto pra
    oferecer 'Restaurar' de quem foi dispensado por engano. Sem esta rota,
    o único jeito de saber o que estava dispensado era olhar direto no banco:
    /api/pendentes só devolve a fila aberta (situacao=pendente)."""
    itens = [
        {"caminho_pasta": d["_id"], "tipo": d.get("tipo"), "nome": d.get("nome") or d["_id"].rsplit("/", 1)[-1],
         "dispensadoEm": d.get("dispensadoEm"), "dispensadoPor": d.get("dispensadoPor") or "",
         "motivo": d.get("motivo") or ""}
        for d in col_pendentes.find({"situacao": "dispensado"}).sort("dispensadoEm", DESCENDING)
    ]
    return jsonify({"itens": itens})


@app.route("/api/pendentes/restaurar", methods=["POST"])
def restaurar_pendente():
    """Desfaz uma dispensa — dispensar por engano não pode ser irreversível."""
    corpo = request.get_json(silent=True) or {}
    caminho = corpo.get("caminho_pasta") or ""
    r = col_pendentes.update_one(
        {"_id": caminho, "situacao": "dispensado"},
        {"$set": {"situacao": "pendente"},
         "$unset": {"dispensadoEm": "", "dispensadoPor": "", "motivo": ""}},
    )
    if not r.matched_count:
        return jsonify({"erro": "Item não está dispensado."}), 404
    return jsonify({"ok": True, "restantes": len(_pendentes_abertos())})


@app.route("/api/pendentes/dispensados", methods=["DELETE"])
def apagar_dispensado():
    """Apaga de vez um item dispensado — até aqui só dava pra restaurar; isso
    aqui esquece o item de verdade (some do banco, não fica nem como
    'dispensado' nem como 'pendente'). Não mexe em processo nenhum, é só a
    entrada na fila de análise."""
    corpo = request.get_json(silent=True) or {}
    caminho = corpo.get("caminho_pasta") or ""
    if not caminho:
        return jsonify({"erro": "Informe o caminho_pasta."}), 400
    r = col_pendentes.delete_one({"_id": caminho, "situacao": "dispensado"})
    if not r.deleted_count:
        return jsonify({"erro": "Item não está dispensado."}), 404
    return jsonify({"ok": True})


def _concluir_pendente(caminho: str, processo_id: str):
    """Chamado quando a análise vira processo: o item sai da fila sozinho."""
    col_pendentes.update_one(
        {"_id": caminho},
        {"$set": {"situacao": "analisado", "analisadoEm": _agora_ms(),
                  "processo_id": processo_id}},
    )


@app.route("/api/relatorios/mais-recente", methods=["GET"])
def relatorio_mais_recente():
    doc = col_relatorios.find_one(sort=[("criadoEm", DESCENDING)])
    if not doc:
        return jsonify({"erro": "Nenhum relatório publicado ainda"}), 404
    doc = _sem_id_mongo(doc)
    # "novos" passa a vir da fila, não do texto deste relatório: o que ficou
    # pendente de varreduras anteriores continua aparecendo até ser resolvido
    doc["novos"] = _pendentes_abertos()
    return jsonify(doc)


@app.route("/api/relatorios", methods=["POST"])
def criar_relatorio():
    """Publica uma nova atualização do dia. Pensado para ser chamado por um
    processo automatizado (ex.: Examinador do SharePoint) - o Painel sempre
    mostra a mais recente pelo campo criadoEm."""
    corpo = request.get_json(force=True, silent=False)
    if not isinstance(corpo, dict) or not corpo.get("conteudo"):
        return jsonify({"erro": "Informe ao menos o campo 'conteudo'"}), 400
    rid = uuid.uuid4().hex
    doc = {
        "_id": rid,
        "titulo": corpo.get("titulo") or "Atualizações do dia",
        "conteudo": corpo["conteudo"],
        "autor": corpo.get("autor") or "",
        "criadoEm": _agora_ms(),
    }
    col_relatorios.insert_one(doc)
    return jsonify(_sem_id_mongo(doc)), 201


def _fmt_data_ms(ms):
    from datetime import datetime
    return datetime.fromtimestamp(ms / 1000).strftime("%d/%m/%Y")


def _gerar_relatorio_diario(atual: dict, anterior: dict | None, data_anterior: str | None) -> tuple[str, str, list]:
    """Compara a varredura atual com a anterior e monta o texto do relatório
    do dia, no mesmo espírito do que a varredura manual da equipe já produz:
    propostas novas, editais novos e movimentações de status. Também devolve
    uma lista estruturada dos itens novos (com o caminho da pasta no
    SharePoint já resolvido), usada pelo botão "Rodar análise e preencher
    informações" — não precisa localizar a pasta de novo, já veio da varredura."""
    ano = atual.get("ano")
    props_atual = atual.get("propostas_privadas", [])
    lic_atual = atual.get("licitacoes", {})
    novos_estruturados = []

    partes = []

    partes.append("PROPOSTAS PRIVADAS NOVAS")
    if anterior is None:
        partes.append(
            f"Primeira varredura registrada — {len(props_atual)} proposta(s) encontrada(s) na pasta "
            f"PROPOSTAS ANO {ano}, servindo de base para as próximas comparações."
        )
    else:
        props_anterior = set(anterior.get("propostas_privadas", []))
        novas = [p for p in props_atual if p not in props_anterior]
        if novas:
            partes.append(f"{len(novas)} nova(s) proposta(s) cadastrada(s) desde a verificação anterior ({data_anterior}):")
            for p in novas:
                partes.append(f"  • {p}")
                novos_estruturados.append({
                    "tipo": "privado",
                    "nome": p,
                    "status": None,
                    "caminho_pasta": f"1 - COMERCIAL/02.02 - Propostas/PROPOSTAS ANO {ano}/{p}",
                })
        else:
            extremos = f", da {props_atual[0]} até a {props_atual[-1]}" if props_atual else ""
            partes.append(
                f"Não houve novas propostas privadas cadastradas na pasta PROPOSTAS ANO {ano} desde a "
                f"verificação anterior ({data_anterior}). A pasta segue com as mesmas {len(props_atual)} "
                f"proposta(s) já registrada(s){extremos}."
            )
    partes.append("")

    mapa_atual = {nome: status for status, lst in lic_atual.items() for nome in lst}
    mapa_anterior = {}
    if anterior:
        for status, lst in anterior.get("licitacoes", {}).items():
            for nome in lst:
                mapa_anterior[nome] = status

    partes.append("LICITAÇÕES/EDITAIS NOVOS")
    if anterior is None:
        partes.append(
            f"Primeira varredura registrada — {len(mapa_atual)} processo(s) de licitação encontrados, "
            f"distribuídos em {len(lic_atual)} categoria(s) de status."
        )
    else:
        novos = [n for n in mapa_atual if n not in mapa_anterior]
        if novos:
            partes.append(f"{len(novos)} novo(s) edital(is) adicionado(s) desde a verificação anterior ({data_anterior}):")
            for n in novos:
                partes.append(f"  • {n} (em \"{mapa_atual[n]}\")")
                status_n = mapa_atual[n]
                novos_estruturados.append({
                    "tipo": "publico",
                    "nome": n,
                    "status": status_n,
                    "caminho_pasta": f"2 - LICITACAO/05.02 - Editais para Licitação/{ano}/{status_n}/{n}",
                })
        else:
            partes.append(
                "Não houve novos editais adicionados às pastas de status de licitação desde a última "
                "verificação. Todas as subpastas de status mantiveram os mesmos processos já conhecidos."
            )
    partes.append("")

    partes.append("STATUS DE PROCESSOS EM ANDAMENTO")
    if anterior is not None:
        movidos = [(n, mapa_anterior[n], mapa_atual[n]) for n in mapa_atual
                   if n in mapa_anterior and mapa_anterior[n] != mapa_atual[n]]
        if movidos:
            for nome, de, para in movidos:
                partes.append(f"O processo \"{nome}\", que constava em \"{de}\", foi movido para \"{para}\".")
        else:
            partes.append("Nenhuma movimentação de status identificada nesta verificação.")
        partes.append("")

    partes.append("Situação atual, por categoria:")
    for status in sorted(lic_atual.keys()):
        itens = lic_atual[status]
        if itens:
            partes.append(f"  \"{status}\" ({len(itens)}): " + "; ".join(itens))
        else:
            partes.append(f"  \"{status}\": nenhum processo.")

    conteudo = "\n".join(partes)
    titulo = "Varredura do SharePoint"
    return titulo, conteudo, novos_estruturados


@app.route("/api/relatorios/executar-varredura", methods=["POST"])
def executar_varredura_sharepoint():
    """Varre o SharePoint agora (propostas privadas + licitações por status),
    compara com a varredura anterior salva e publica o relatório do dia -
    o equivalente automatizado à varredura manual que a equipe já fazia."""
    if not (MONTADOR_TENANT_ID and MONTADOR_CLIENT_ID and MONTADOR_CLIENT_SECRET):
        return jsonify({
            "erro": "SharePoint não configurado neste servidor. Defina MONTADOR_TENANT_ID, "
                    "MONTADOR_CLIENT_ID e MONTADOR_CLIENT_SECRET."
        }), 503

    corpo = request.get_json(silent=True) or {}
    cfg = {
        "MODO_LOCAL": False,
        "TENANT_ID": MONTADOR_TENANT_ID,
        "CLIENT_ID": MONTADOR_CLIENT_ID,
        "CLIENT_SECRET": MONTADOR_CLIENT_SECRET,
    }
    try:
        atual = escanear_biblioteca(cfg)
    except Exception as e:
        return jsonify({"erro": f"Falha ao varrer o SharePoint: {e}"}), 502

    anterior_doc = col_snapshots.find_one(sort=[("criadoEm", DESCENDING)])
    anterior = anterior_doc["dados"] if anterior_doc else None
    data_anterior = _fmt_data_ms(anterior_doc["criadoEm"]) if anterior_doc else None

    titulo, conteudo, novos = _gerar_relatorio_diario(atual, anterior, data_anterior)

    col_snapshots.insert_one({"_id": uuid.uuid4().hex, "dados": atual, "criadoEm": _agora_ms()})
    _registrar_pendentes(novos)

    rid = uuid.uuid4().hex
    doc_rel = {
        "_id": rid,
        "titulo": titulo,
        "conteudo": conteudo,
        "novos": novos,
        "autor": corpo.get("autor") or "",
        "criadoEm": _agora_ms(),
    }
    col_relatorios.insert_one(doc_rel)
    resposta = _sem_id_mongo(doc_rel)
    # a tela trabalha com a fila inteira, não só com o que esta varredura achou
    resposta["novos"] = _pendentes_abertos()
    return jsonify(resposta), 201


# ──────────────────────────────────────────────────────────────────
# Painel de E-mails — triagem de volume alto no Outlook
# ──────────────────────────────────────────────────────────────────
# Domínios (ou o pai deles -- "boletim.conlicitacao.com.br" bate em
# "conlicitacao.com.br") de portal de licitação: aviso automático de
# publicação/esclarecimento/impugnação/republicação de edital. Sozinhos não
# interessa ler um por um; só sobem de prioridade quando batem com um
# processo que a Sinape já acompanha (ver _casar_email_com_processo).
DOMINIOS_PORTAL_LICITACAO = {
    "procergs.rs.gov.br", "boletimconlicitacao.com.br", "saeb.ba.gov.br",
    "comprasnet.ba.gov.br", "comprasnet.gov.br", "compras.gov.br",
    "licitacoes-e.com.br", "bll.org.br", "portaldecompraspublicas.com.br",
    "bnc.org.br", "pncp.gov.br", "tce.rs.gov.br",
}
_PADRAO_PORTAL_PALAVRA = re.compile(r"compras|licitac|licitaç|edital|pncp", re.I)

# Ruído puro: marketing/newsletter, nunca precisa entrar no resumo, só contar.
DOMINIOS_RUIDO_CONHECIDOS = {"pinterest.com", "laiob.com"}
_PADRAO_RUIDO_REMETENTE = re.compile(
    r"^(no-?reply|newsletter|notifica|recommendations|marketing|comunicacao)", re.I
)

_PADRAO_EDITAL_NUM = re.compile(r"Edital:\s*([0-9./-]+)", re.I)
_PADRAO_ORGAO = re.compile(r"Central de compras:\s*([^\n\r]+)", re.I)

# Proposta recebida: pedido de orçamento/cotação vindo direto de um cliente em
# potencial (não é aviso de portal nem newsletter) -- é o caso que o Gabriel
# citou (ex.: "SOLICITAÇÃO DE ORÇAMENTO" da Unicamp). É uma marcação (booleana)
# em cima da categoria, não uma categoria nova -- um e-mail de proposta É
# correspondência, só que com esse destaque a mais pra filtrar rápido.
_PADRAO_PROPOSTA = re.compile(
    r"solicita\w*\s+de\s+or[çc]amento|pedido de cota[çc][ãa]o|solicita[çc][ãa]o de cota[çc][ãa]o|"
    r"solicita[çc][ãa]o de proposta|termo de refer[êe]ncia|pedido de or[çc]amento|\bRFP\b|"
    r"cota[çc][ãa]o de pre[çc]os?",
    re.I,
)


def _eh_proposta_recebida(assunto, corpo_preview):
    return bool(_PADRAO_PROPOSTA.search((assunto or "") + " " + (corpo_preview or "")))


def _dominio_email(endereco):
    return (endereco or "").strip().lower().rsplit("@", 1)[-1]


def _dominio_ou_pai_em(dominio, conjunto):
    """'sub.boletimconlicitacao.com.br' bate em {'boletimconlicitacao.com.br'}
    -- confere o domínio inteiro e cada sufixo dele, não só a igualdade exata."""
    partes = dominio.split(".")
    return any(".".join(partes[i:]) in conjunto for i in range(len(partes)))


def _classificar_email(remetente, corpo_preview):
    """Bucket determinístico, sem IA -- rápido e barato, roda pra cada e-mail da
    varredura. 'correspondencia' é o padrão: só sai dali quem bate com um padrão
    CONHECIDO de automação (portal ou ruído) -- e-mail desconhecido é tratado
    como possivelmente importante, nunca como ruído por omissão."""
    dominio = _dominio_email(remetente)
    local = (remetente or "").split("@")[0]
    if _dominio_ou_pai_em(dominio, DOMINIOS_PORTAL_LICITACAO) or _PADRAO_PORTAL_PALAVRA.search(dominio):
        return "portal"
    if _dominio_ou_pai_em(dominio, DOMINIOS_RUIDO_CONHECIDOS) or _PADRAO_RUIDO_REMETENTE.search(local):
        return "ruido"
    return "correspondencia"


def _casar_email_com_processo(corpo_preview):
    """Tenta casar um aviso de portal com um processo já cadastrado, pelo número
    do edital ou pelo nome do órgão citados no corpo do aviso -- é um cruzamento
    de melhor esforço (o texto do aviso não segue o mesmo formato do cadastro),
    não precisa ser perfeito pra já ajudar a priorizar o resumo."""
    m_num = _PADRAO_EDITAL_NUM.search(corpo_preview or "")
    m_org = _PADRAO_ORGAO.search(corpo_preview or "")
    ou = []
    if m_num:
        ou.append({"analise.geral_numero": {"$regex": re.escape(m_num.group(1).strip()), "$options": "i"}})
    if m_org:
        ou.append({"analise.geral_orgao": {"$regex": re.escape(m_org.group(1).strip()[:40]), "$options": "i"}})
    if not ou:
        return None
    doc = col_processos.find_one({"$or": ou}, {"nome": 1})
    if not doc:
        return None
    return {"processo_id": doc["_id"], "processo_nome": doc.get("nome") or "(sem nome)"}


GRAPH_BASE = "https://graph.microsoft.com/v1.0"


@app.route("/api/emails/varredura", methods=["POST"])
def executar_varredura_email():
    """Varre a caixa de entrada do usuário logado via Microsoft Graph (Mail.Read
    delegado -- token do próprio usuário, nunca a caixa de outra pessoa),
    classifica cada mensagem e cruza aviso de portal com processo já cadastrado.
    Só roda sob demanda (clique em "Executar varredura") -- sem varredura
    automática de manhã por enquanto, decisão do Gabriel pra não mexer em
    permissão de app-only/admin do Azure agora (ver _token_graph_mail)."""
    email = session.get("usuario_email") or ""
    token = _token_graph_mail(email, ["Mail.Read"])
    if not token:
        return jsonify({
            "erro": "Leitura de e-mail ainda não autorizada para esta conta. Saia e "
                    "entre de novo pela Microsoft para conceder a permissão (aparece "
                    "uma tela de consentimento do Outlook uma única vez)."
        }), 400

    ultima = col_varreduras_email.find_one(sort=[("criadoEm", DESCENDING)])
    if ultima and ultima.get("criadoEm"):
        # 2h de folga sobre a última varredura -- evita buraco quando um e-mail
        # chega atrasado na indexação do Graph
        desde = datetime.utcfromtimestamp(ultima["criadoEm"] / 1000 - 2 * 60 * 60)
    else:
        desde = datetime.utcnow() - timedelta(hours=24)
    desde_iso = desde.strftime("%Y-%m-%dT%H:%M:%SZ")

    headers = {"Authorization": f"Bearer {token}"}
    params = {
        "$top": "50",
        "$orderby": "receivedDateTime desc",
        "$select": "id,subject,from,receivedDateTime,isRead,webLink,bodyPreview",
        "$filter": f"receivedDateTime ge {desde_iso}",
    }
    url = f"{GRAPH_BASE}/me/mailFolders/Inbox/messages"
    brutos = []
    try:
        paginas = 0
        while url and paginas < 6:  # teto de ~300 mensagens por varredura
            r = requests.get(url, headers=headers, params=(params if paginas == 0 else None), timeout=20)
            if r.status_code != 200:
                return jsonify({"erro": f"Microsoft Graph respondeu {r.status_code}: {r.text[:300]}"}), 502
            corpo = r.json()
            brutos.extend(corpo.get("value") or [])
            url = corpo.get("@odata.nextLink")
            paginas += 1
    except requests.RequestException as e:
        return jsonify({"erro": f"Falha ao contactar o Microsoft Graph: {e}"}), 502

    itens = []
    contagens = {"portal": 0, "correspondencia": 0, "ruido": 0, "propostas": 0}
    for m in brutos:
        remetente = ((m.get("from") or {}).get("emailAddress") or {}).get("address") or ""
        preview = m.get("bodyPreview") or ""
        categoria = _classificar_email(remetente, preview)
        contagens[categoria] += 1
        assunto = m.get("subject") or "(sem assunto)"
        eh_proposta = _eh_proposta_recebida(assunto, preview)
        if eh_proposta:
            contagens["propostas"] += 1
        item = {
            "graph_id": m.get("id"),  # precisa do id de verdade da mensagem pra responder (ver /api/emails/responder)
            "assunto": assunto,
            "remetente": remetente,
            "recebidoEm": m.get("receivedDateTime"),
            "lido": bool(m.get("isRead")),
            "webLink": m.get("webLink"),
            "categoria": categoria,
            "proposta": eh_proposta,
            "respondido": False,
        }
        if categoria == "portal":
            casado = _casar_email_com_processo(preview)
            if casado:
                item.update(casado)
        itens.append(item)

    doc = {
        "_id": uuid.uuid4().hex,
        "criadoEm": _agora_ms(),
        "autor": _autor_da_sessao(),
        "desde": desde_iso,
        "total_verificado": len(itens),
        "contagens": contagens,
        "itens": itens,
    }
    col_varreduras_email.insert_one(doc)
    return jsonify(_sem_id_mongo(doc)), 201


@app.route("/api/emails/ultima-varredura", methods=["GET"])
def ultima_varredura_email():
    doc = col_varreduras_email.find_one(sort=[("criadoEm", DESCENDING)])
    if not doc:
        return jsonify({}), 200
    return jsonify(_sem_id_mongo(doc)), 200


@app.route("/api/emails/responder", methods=["POST"])
def responder_email():
    """Responde um e-mail direto na thread original (mesmo destinatário e
    assunto "RE: ..." que o Outlook já monta sozinho -- Graph cuida disso,
    não precisamos remontar cabeçalho nem citação). O texto sempre vem
    pronto da tela, escrito ou revisado pela pessoa -- esta rota nunca decide
    sozinha o que mandar, só dispara o que já chegou pronto."""
    email = session.get("usuario_email") or ""
    token = _token_graph_mail(email, ["Mail.Send"])
    if not token:
        return jsonify({
            "erro": "Envio de e-mail ainda não autorizado para esta conta. Saia e "
                    "entre de novo pela Microsoft para conceder a permissão (aparece "
                    "uma tela de consentimento do Outlook uma única vez)."
        }), 400

    corpo = request.get_json(silent=True) or {}
    graph_id = (corpo.get("graph_id") or "").strip()
    texto = (corpo.get("texto") or "").strip()
    if not graph_id or not texto:
        return jsonify({"erro": "Informe graph_id e texto."}), 400

    try:
        r = requests.post(
            f"{GRAPH_BASE}/me/messages/{graph_id}/reply",
            headers={"Authorization": f"Bearer {token}"},
            json={"comment": texto},
            timeout=20,
        )
    except requests.RequestException as e:
        return jsonify({"erro": f"Falha ao contactar o Microsoft Graph: {e}"}), 502
    if r.status_code not in (200, 202):
        return jsonify({"erro": f"Microsoft Graph respondeu {r.status_code}: {r.text[:300]}"}), 502

    col_varreduras_email.update_one(
        {"itens.graph_id": graph_id},
        {"$set": {
            "itens.$.respondido": True,
            "itens.$.respondidoEm": _agora_ms(),
            "itens.$.respondidoPor": _autor_da_sessao(),
        }},
    )
    return jsonify({"ok": True}), 200


MODELOS_IA_PERMITIDOS = {"claude-opus-5", "claude-sonnet-5"}
ESFORCOS_IA_PERMITIDOS = {"low", "medium", "high", "xhigh", "max"}

# Esforço efetivo quando a tela não manda nenhum. Ficam explícitos aqui porque o
# esforço agora vai gravado em cada registro de gasto, e um custo só serve pra
# comparar se dá pra saber com que esforço ele foi gasto — "em branco" no
# relatório seria um buraco justamente nas chamadas que ninguém configurou.
# A análise de edital usa o padrão da própria API (high); as telas interativas
# (Sinki e concorrentes) já vinham caindo em medium.
ESFORCO_PADRAO_ANALISE = "high"
ESFORCO_PADRAO_INTERATIVO = "medium"

# preço por 1 milhão de tokens (entrada / saída), em dólares — referência oficial.
# Já deixo GPT aqui pra quando/se integrarmos a OpenAI (ainda não está ligada).
PRECOS_MODELOS = {
    "claude-opus-5":   {"entrada": 5.0,  "saida": 25.0},
    "claude-opus-4-8": {"entrada": 5.0,  "saida": 25.0},   # mantido só p/ registros antigos de gastos
    "claude-sonnet-5": {"entrada": 2.0,  "saida": 10.0},   # preço promocional até 31/08/2026; depois 3/15
    "gpt-5.6-sol":     {"entrada": 5.0,  "saida": 30.0},
    "gpt-5.6-terra":   {"entrada": 2.5,  "saida": 15.0},
    "gpt-5.6-luna":    {"entrada": 1.0,  "saida": 6.0},
}
USD_PARA_BRL = 5.40  # referência aproximada, só para exibição


def _custo_usd(model: str, tokens_entrada: int, tokens_saida: int) -> float:
    p = PRECOS_MODELOS.get(model, {"entrada": 0.0, "saida": 0.0})
    return (tokens_entrada * p["entrada"] + tokens_saida * p["saida"]) / 1_000_000


def _registrar_gasto(model: str, uso: dict, processo_id=None, processo_nome: str = "",
                     origem: str = "", esforco: str = ""):
    """Registra uma chamada de IA no contador de gastos: tokens e custo em
    dólar. Usado toda vez que uma análise por IA roda, pra alimentar o Painel
    de Gastos (total geral + por processo).

    O esforço vai junto porque ele é quem manda no volume de tokens de saída —
    e saída custa 5x a entrada. Sem esse campo dá pra comparar Opus contra
    Sonnet, mas não dá pra responder se compensa baixar o esforço, que costuma
    ser a economia maior."""
    ent = int(uso.get("entrada", 0))
    sai = int(uso.get("saida", 0))
    custo = _custo_usd(model, ent, sai)
    col_gastos.insert_one({
        "_id": uuid.uuid4().hex,
        "processo_id": processo_id,
        "processo_nome": processo_nome,
        "model": model,
        "origem": origem,
        "esforco": esforco or uso.get("esforco") or "",
        "tokens_entrada": ent,
        "tokens_saida": sai,
        "custo_usd": round(custo, 6),
        "criadoEm": _agora_ms(),
    })


# ──────────────────────────────────────────────────────────────────
# jobs de análise — a análise não roda mais dentro da requisição HTTP
# ──────────────────────────────────────────────────────────────────
# Segurar a conexão aberta enquanto o Claude lê um edital de 200 páginas não
# funciona: o gunicorn mata o worker no --timeout (foi o que derrubou a
# proposta 47/2026 da Conasa, duas vezes), e mesmo aumentando o teto qualquer
# oscilação de rede ou aba fechada perde o trabalho — possivelmente já cobrado.
# Agora a requisição só cria um job e responde na hora; a análise roda numa
# thread e grava o resultado no banco. A tela pergunta o andamento de tempos
# em tempos. Se o navegador cair, o job continua e o processo aparece do mesmo
# jeito — e o gasto fica registrado, que era o pior de se perder.
JOB_ABANDONADO_S = 30 * 60   # sem sinal de vida por tanto tempo = worker morreu


def _job_novo(tipo: str, descricao: str) -> str:
    jid = uuid.uuid4().hex
    col_jobs.insert_one({
        "_id": jid, "tipo": tipo, "descricao": descricao, "status": "rodando",
        "criadoEm": _agora_ms(), "sinalDeVida": _agora_ms(),
        "processo_id": None, "erro": None,
    })
    return jid


def _job_encerrar(jid: str, **campos):
    campos["sinalDeVida"] = _agora_ms()
    col_jobs.update_one({"_id": jid}, {"$set": campos})


def _job_progresso(jid: str, etapa: str, atual: int = 0, total: int = 0):
    """Anota em que pé está a análise, pra tela mostrar em vez de só um relógio
    correndo. 'atual/total' só vem preenchido quando existe contagem de verdade
    (os lotes de um edital grande) — no resto o progresso é indeterminado de
    propósito, porque inventar uma porcentagem que não corresponde a nada seria
    pior que não mostrar nenhuma."""
    col_jobs.update_one({"_id": jid}, {"$set": {
        "etapa": etapa, "passo_atual": atual, "passos_total": total,
        "sinalDeVida": _agora_ms(),
    }})


def _job_rodar_em_thread(jid: str, alvo, *args, **kwargs):
    """Executa `alvo` fora da requisição. Nada de contexto do Flask aqui
    dentro: quem chama já extraiu tudo que precisa antes."""
    def _tarefa():
        t0 = time.time()
        try:
            processo_id = alvo(*args, **kwargs)
            _job_encerrar(jid, status="concluido", processo_id=processo_id,
                          duracao_s=round(time.time() - t0, 1))
            print(f"[job {jid[:8]}] concluido em {time.time() - t0:.0f}s", flush=True)
        except Exception as e:
            # a mensagem vai pra tela, então tem que ser legível — e o traceback
            # vai pro log do Render pra quem for investigar
            _job_encerrar(jid, status="erro", erro=str(e) or e.__class__.__name__,
                          duracao_s=round(time.time() - t0, 1))
            print(f"[job {jid[:8]}] ERRO em {time.time() - t0:.0f}s: {e!r}", flush=True)
            traceback.print_exc()

    threading.Thread(target=_tarefa, name=f"job-{jid[:8]}", daemon=True).start()


@app.route("/api/jobs/<jid>", methods=["GET"])
def ver_job(jid):
    job = col_jobs.find_one({"_id": jid})
    if not job:
        return jsonify({"erro": "Job não encontrado."}), 404
    # Se o processo do servidor reiniciou no meio, a thread morreu junto e o job
    # ficaria "rodando" pra sempre. Sem sinal de vida há muito tempo, assume-se
    # perdido — melhor dizer isso do que deixar a tela girando sem fim.
    if job["status"] == "rodando":
        parado_ha = (_agora_ms() - job.get("sinalDeVida", job["criadoEm"])) / 1000
        if parado_ha > JOB_ABANDONADO_S:
            job["status"] = "erro"
            job["erro"] = ("O servidor reiniciou durante a análise e ela se perdeu. "
                           "Se aparecer uma chamada nova no Painel de gastos, ela foi "
                           "cobrada mesmo sem gerar processo.")
            col_jobs.update_one({"_id": jid}, {"$set": {"status": "erro", "erro": job["erro"]}})
    resposta = {
        "id": jid, "status": job["status"], "descricao": job.get("descricao", ""),
        "processo_id": job.get("processo_id"), "erro": job.get("erro"),
        "segundos": round((_agora_ms() - job["criadoEm"]) / 1000),
        "duracao_s": job.get("duracao_s"),
        "etapa": job.get("etapa") or "",
        "passo_atual": job.get("passo_atual") or 0,
        "passos_total": job.get("passos_total") or 0,
    }
    # o upload manual não cria processo: devolve o JSON pra tela conferir
    if job.get("documento"):
        resposta["documento"] = job["documento"]
    return jsonify(resposta)


# A API aceita no máximo 100 páginas por PDF e 600 páginas na requisição
# inteira. Um anexo passar de 100 páginas não é anomalia: o PER — Programa de
# Exploração da Rodovia da proposta 47/2026 (Via Brasil MT-246) tem 197 e é
# Anexo III do próprio TR, citado no item 7.1. Recusar esse tipo de arquivo
# seria recusar o edital; o certo é fatiar e mandar em partes.
PAGINAS_POR_PDF = 100
PAGINAS_POR_REQUISICAO = 600
# Acima de 600 páginas ao todo (caso real: um edital de 847 páginas com tudo
# junto), uma chamada não basta mais. Em vez de recusar, o processo é dividido
# em lotes de até 600 páginas cada, cada lote analisado à parte, e uma última
# chamada (só texto, sem PDF — barata) funde os resultados num JSON só,
# cruzando valores e prazos entre os lotes do mesmo jeito que já se cruza
# entre documentos numa análise normal. É diferente de simplesmente "chamar
# de novo pro resto": chamar de novo sem fundir perderia justamente esse
# cruzamento entre o que caiu no lote 1 e o que caiu no lote 2.
PAGINAS_MAXIMO_TOTAL = 3000  # acima disso, provavelmente pasta com lixo demais junto — barra e avisa
MB_MAXIMO_POR_LOTE = 20      # margem de sobra pro teto de 32 MB em base64 (20 MB × 4/3 ≈ 27 MB)

# Página não mede densidade. Um edital de texto corrido gasta ~2 mil tokens por
# página; um "Orçamento Referencial" (planilha virada PDF, tabela em cada linha)
# gasta muito mais — e foi assim que a análise do PE 456/2026 do DNIT DF estourou
# a janela de contexto mesmo com o lote dentro das 600 páginas. Por isso o limite
# que vale de verdade é medido, não estimado: antes de mandar, conta os tokens do
# lote pela própria API e reparte se passar. A janela é de 1M; o teto abaixo
# deixa folga pro system prompt e pros 64k de saída (raciocínio + resposta).
LIMITE_TOKENS_LOTE = 700_000
# Contar tokens custa uma ida à API, então só vale a pena quando o lote é grande
# o bastante pra ter chance real de estourar — abaixo disso, manda direto.
PAGINAS_PARA_CONTAR_TOKENS = 120


def _erro_api_legivel(e) -> str:
    """Traduz os erros da Anthropic que a equipe realmente encontra. Sem isto a
    tela mostra o JSON cru em inglês — foi o que apareceu quando o saldo da API
    acabou no meio da análise da proposta 048 da Arteris, e a mensagem não
    dizia o que fazer nem que o problema era de conta, não do documento."""
    try:
        corpo = getattr(e, "body", None) or {}
        detalhe = (corpo.get("error") or {}).get("message", "") or getattr(e, "message", "")
    except Exception:
        detalhe = getattr(e, "message", "") or str(e)
    d = (detalhe or "").lower()
    codigo = getattr(e, "status_code", None)

    if "credit balance is too low" in d or "insufficient" in d and "credit" in d:
        return ("O saldo da API da Anthropic acabou. Nenhuma análise roda até adicionar "
                "créditos em Plans & Billing no console da Anthropic. A tentativa não foi "
                "cobrada e o processo continua na fila — é só rodar de novo depois de "
                "recarregar.")
    if codigo == 401 or "authentication" in d or "invalid x-api-key" in d:
        return ("A chave da API da Anthropic foi recusada. Ela pode ter sido revogada ou "
                "trocada — confira a variável ANTHROPIC_API_KEY no servidor.")
    if codigo == 403 or "permission" in d:
        return "A chave da API não tem permissão para esta operação."
    if codigo == 429:
        return ("Limite de uso da API atingido, mesmo depois de algumas tentativas. "
                "Espere alguns minutos e rode de novo.")
    if codigo == 503 or "overloaded" in d:
        return ("A API da Anthropic está sobrecarregada e não respondeu depois de várias "
                "tentativas. É temporário — rode de novo daqui a pouco.")
    if "could not process pdf" in d:
        return ("A IA não conseguiu abrir um dos PDFs. Ele pode estar corrompido ou "
                "protegido por senha — abra os arquivos da pasta e confira qual não abre.")
    if "prompt is too long" in d or "too many tokens" in d:
        return ("Os documentos somados passam do que a IA consegue ler de uma vez. Rode a "
                "análise com menos arquivos, deixando de fora os anexos que não afetam a "
                "decisão.")
    return f"Erro na API da IA: {detalhe or e}"


def _fatiar_pdfs_grandes(pdfs: list) -> list:
    """Divide PDFs acima do limite de páginas em partes menores, preservando a
    ordem. Cada parte carrega no nome o intervalo de páginas para que as
    referências da análise ("página 5 do PER") continuem fazendo sentido.
    Não recusa mais o total: quem decide se cabe numa chamada só ou precisa
    de vários lotes é _agrupar_em_lotes, chamado depois disso."""
    saida = []
    total_paginas = 0
    for nome, dados in pdfs:
        try:
            leitor = PdfReader(io.BytesIO(dados))
            paginas = len(leitor.pages)
        except Exception:
            # PDF que o pypdf não abre pode muito bem ser legível pela API —
            # manda inteiro e deixa que ela reporte, em vez de barrar aqui
            saida.append((nome, dados))
            continue

        total_paginas += paginas
        if paginas <= PAGINAS_POR_PDF:
            saida.append((nome, dados))
            continue

        base, _, ext = nome.rpartition(".")
        for inicio in range(0, paginas, PAGINAS_POR_PDF):
            fim = min(inicio + PAGINAS_POR_PDF, paginas)
            escritor = PdfWriter()
            for p in range(inicio, fim):
                escritor.add_page(leitor.pages[p])
            buf = io.BytesIO()
            escritor.write(buf)
            rotulo = f"{base or nome} (páginas {inicio + 1}-{fim} de {paginas})"
            saida.append((f"{rotulo}.{ext}" if ext else rotulo, buf.getvalue()))
        print(f"[analise] '{nome}' tem {paginas} páginas — dividido em "
              f"{-(-paginas // PAGINAS_POR_PDF)} partes", flush=True)

    if total_paginas > PAGINAS_MAXIMO_TOTAL:
        raise ValueError(
            f"Os documentos somam {total_paginas} páginas — acima do teto de "
            f"{PAGINAS_MAXIMO_TOTAL} que o Painel aceita numa análise. Confira se não "
            f"entrou algum arquivo que não devia (versão antiga, pasta errada) antes "
            f"de tentar de novo."
        )
    return saida


def _agrupar_em_lotes(partes: list) -> list:
    """Agrupa as partes (já fatiadas em blocos de até 100 páginas) em lotes
    que cabem numa chamada — até 600 páginas e até MB_MAXIMO_POR_LOTE de peso
    cada — respeitando a ordem em que os documentos aparecem. Um documento só
    é dividido entre lotes quando ele sozinho já passa do teto de um lote
    (como o edital de 847 páginas junto que estourou os 600 de uma vez)."""
    lotes = []
    lote_atual, paginas_atual, bytes_atual = [], 0, 0
    limite_bytes = MB_MAXIMO_POR_LOTE * 1024 * 1024
    for nome, dados in partes:
        try:
            paginas = len(PdfReader(io.BytesIO(dados)).pages)
        except Exception:
            paginas = 1  # ilegível pro pypdf: conta como 1 pra não travar o agrupamento
        estoura = lote_atual and (
            paginas_atual + paginas > PAGINAS_POR_REQUISICAO
            or bytes_atual + len(dados) > limite_bytes
        )
        if estoura:
            lotes.append(lote_atual)
            lote_atual, paginas_atual, bytes_atual = [], 0, 0
        lote_atual.append((nome, dados))
        paginas_atual += paginas
        bytes_atual += len(dados)
    if lote_atual:
        lotes.append(lote_atual)
    return lotes


def _chamar_claude(content: list, modelo_usado: str, esforco_usado: str):
    """Uma chamada ao Claude com o prompt padrão do Sinki, com retentativa em
    erro transitório (503/429). Devolve (texto_bruto, uso) — usado tanto pra
    analisar um lote de PDFs quanto pra fundir os resultados de vários lotes
    (aí sem PDF nenhum no content, só texto)."""
    kwargs = {"output_config": {"effort": esforco_usado}}
    t0 = time.time()
    # A API da Anthropic devolve 503 overloaded_error de vez em quando —
    # sobrecarga momentânea do lado deles, que passa em segundos. Antes isso
    # virava erro na hora e o usuário tinha que clicar de novo manualmente;
    # agora que a análise roda numa thread (sem mais o relógio do gunicorn
    # correndo), dá pra esperar um pouco e tentar de novo sozinho. Só
    # overloaded/rate-limit se repete — erro de PDF ilegível ou de conteúdo
    # não se resolve tentando de novo, então sobe na hora.
    TENTATIVAS = 4
    for tentativa in range(1, TENTATIVAS + 1):
        try:
            with anthropic_client.messages.stream(
                model=modelo_usado,
                # quem é o Sinki e o contrato da análise ficam no system prompt: é o
                # mesmo texto usado na conversa, e o cache de prompt cobra barato por ele
                system=[{"type": "text", "text": PROMPT_SINKI, "cache_control": {"type": "ephemeral"}}],
                # 64k porque o "esforço" alto/máximo gasta parte do orçamento pensando:
                # max_tokens limita raciocínio + resposta juntos, e com 32k o JSON da
                # análise chegava a ser cortado no meio nos esforços mais altos.
                max_tokens=64000,
                # Sem isto o Opus 4.8 roda SEM raciocinar (no Sonnet 5 o padrão já é
                # raciocinar) - ou seja, o modelo vendido como "mais cuidadoso" saía
                # menos cuidadoso que o barato, e o seletor de esforço quase não
                # surtia efeito nele. Com o raciocínio desligado o Opus também tende a
                # escrever explicações junto do JSON, o que quebrava a leitura.
                thinking={"type": "adaptive"},
                messages=[{"role": "user", "content": content}],
                **kwargs,
            ) as stream:
                resposta = stream.get_final_message()
            break
        except anthropic.APIStatusError as e:
            transitorio = e.status_code == 503 or e.status_code == 429
            if not transitorio or tentativa == TENTATIVAS:
                # quem lê isso é a equipe na tela, não quem escreveu o código:
                # sobe a versão em português, dizendo o que fazer
                raise ValueError(_erro_api_legivel(e)) from e
            espera = 5 * tentativa
            print(f"[analise] tentativa {tentativa} falhou ({e.status_code} "
                  f"{getattr(e, 'body', None) or e.message}) — tentando de novo em {espera}s",
                  flush=True)
            time.sleep(espera)

    u = resposta.usage
    print(f"[analise] fim · {time.time() - t0:.0f}s · "
          f"{getattr(u, 'output_tokens', 0) or 0} tokens de saida", flush=True)
    uso = {
        "entrada": (getattr(u, "input_tokens", 0) or 0)
                   + (getattr(u, "cache_creation_input_tokens", 0) or 0)
                   + (getattr(u, "cache_read_input_tokens", 0) or 0),
        "saida": getattr(u, "output_tokens", 0) or 0,
    }
    texto = "".join(b.text for b in resposta.content if b.type == "text").strip()
    texto = re.sub(r"^```(?:json)?\s*|\s*```$", "", texto.strip())
    return texto, uso


def _texto_para_json(texto: str) -> dict:
    try:
        return json.loads(texto)
    except json.JSONDecodeError:
        # de vez em quando a IA escreve uma frase antes ou depois do JSON;
        # antes de desistir, recorta o objeto do meio do texto. Se nem assim
        # der, o erro sobe pro chamador (que responde "JSON inválido").
        inicio, fim = texto.find("{"), texto.rfind("}")
        if inicio == -1 or fim <= inicio:
            raise
        return json.loads(texto[inicio:fim + 1])


def _content_do_lote(pdfs_lote: list) -> list:
    """Monta o content de uma chamada de análise. Isolado porque a contagem de
    tokens precisa medir exatamente o mesmo que vai ser enviado."""
    content = [
        {"type": "document", "source": {"type": "base64", "media_type": "application/pdf",
         "data": base64.standard_b64encode(dados).decode("ascii")}}
        for _, dados in pdfs_lote
    ]
    content.append({"type": "text", "text": PEDIDO_ANALISE})
    return content


def _contar_tokens(content: list, modelo_usado: str):
    """Pergunta à própria API quantos tokens o lote ocupa. Devolve None se a
    contagem falhar — nesse caso o envio segue e, se estourar, a mensagem de
    erro traduzida explica; melhor isso do que travar a análise por causa da
    medição."""
    try:
        r = anthropic_client.messages.count_tokens(
            model=modelo_usado,
            system=[{"type": "text", "text": PROMPT_SINKI}],
            messages=[{"role": "user", "content": content}],
        )
        return getattr(r, "input_tokens", None)
    except Exception as e:
        print(f"[analise] não consegui contar tokens ({e!r}) — seguindo assim mesmo", flush=True)
        return None


def _repartir_por_tokens(lotes: list, modelo_usado: str) -> list:
    """Reparte os lotes que, medidos, não cabem na janela de contexto. Divide
    ao meio e mede de novo, até caber — é o que resolve documento denso
    (planilha virada PDF) que passa no limite de páginas mas estoura em
    tokens."""
    saida, fila = [], list(lotes)
    while fila:
        lote = fila.pop(0)
        paginas = 0
        for _, dados in lote:
            try:
                paginas += len(PdfReader(io.BytesIO(dados)).pages)
            except Exception:
                paginas += 1
        # lote pequeno não tem chance de estourar: evita uma ida à API à toa
        if paginas < PAGINAS_PARA_CONTAR_TOKENS or len(lote) == 1:
            saida.append(lote)
            continue
        tokens = _contar_tokens(_content_do_lote(lote), modelo_usado)
        if tokens is None or tokens <= LIMITE_TOKENS_LOTE:
            if tokens:
                print(f"[analise] lote de {paginas} páginas = {tokens} tokens, cabe", flush=True)
            saida.append(lote)
            continue
        meio = len(lote) // 2
        print(f"[analise] lote de {paginas} páginas = {tokens} tokens, acima do teto de "
              f"{LIMITE_TOKENS_LOTE} — repartindo em dois", flush=True)
        fila.insert(0, lote[meio:])
        fila.insert(0, lote[:meio])
    return saida


def _analisar_um_lote(pdfs_lote: list, modelo_usado: str, esforco_usado: str) -> tuple:
    """Manda um lote de PDFs (já dentro do teto de páginas/MB de uma
    requisição) pro Claude e devolve (doc, uso) desse lote."""
    nomes = [nome for nome, _ in pdfs_lote]
    content = _content_do_lote(pdfs_lote)

    # Sem isto, uma análise que estoura o timeout do gunicorn não deixa rastro
    # nenhum: o worker morre esperando a resposta, o registro de gasto nunca
    # roda e ninguém sabe quanto tempo aquilo levou nem se a API foi chamada.
    mb = sum(len(d) for _, d in pdfs_lote) / 1024 / 1024
    print(f"[analise] inicio · modelo={modelo_usado} esforco={esforco_usado} "
          f"{len(pdfs_lote)} arquivo(s) {mb:.1f} MB", flush=True)
    texto, uso = _chamar_claude(content, modelo_usado, esforco_usado)
    doc = _texto_para_json(texto)
    doc.setdefault("fontes", "; ".join(nomes))
    doc.setdefault("analise", {}).setdefault("_sourceFiles", "; ".join(nomes))
    return doc, uso


PEDIDO_MERGE_ANALISE = (
    "Os blocos abaixo são análises parciais do MESMO processo — não são processos diferentes, são "
    "pedaços do mesmo, porque os documentos juntos passavam do que a IA processa numa única chamada e "
    "tiveram que ser analisados em grupos separados.\n\n"
    "Funda tudo em UM único JSON, seguindo exatamente o mesmo contrato da \"ANÁLISE ESTRUTURADA DE "
    "EDITAL\" que você já conhece:\n"
    "- Não duplique exigência, risco ou item de checklist que apareça (com o mesmo sentido, mesmo com "
    "texto diferente) em mais de um bloco.\n"
    "- Cruze valores, prazos e quantitativos que aparecem em blocos diferentes: se divergirem entre si, "
    "registre como risco citando as duas fontes, com a mesma ordem de prevalência de sempre (edital > "
    "TR > demais anexos).\n"
    "- Campo do modelo padrão preenchido em só um bloco: use esse valor. Preenchido em mais de um bloco "
    "com o MESMO valor (ou equivalente): use uma vez. Preenchido em blocos diferentes com valores "
    "DIFERENTES: aplique a mesma prevalência e registre a divergência como risco, não escolha em silêncio.\n"
    "- Junte as seções extras e o checklist dos blocos sem repetir id/key/grupo.\n"
    "- \"_autoFilledKeys\" e \"_sourceFiles\" do resultado final = união dos blocos.\n"
    "Responda apenas com o JSON final, sem texto antes ou depois.\n\n"
    "BLOCOS PARCIAIS:\n"
)


def _fundir_analises(parciais: list, modelo_usado: str, esforco_usado: str) -> tuple:
    """Junta as análises de vários lotes num JSON só, cruzando entre si do
    mesmo jeito que já se cruza entre documentos numa análise normal. Chamada
    só de texto — sem PDF, sem custo de imagem — por isso sai barata mesmo
    depois de várias chamadas grandes."""
    blocos = "\n\n".join(f"--- BLOCO {i + 1} ---\n{json.dumps(p, ensure_ascii=False)}"
                         for i, p in enumerate(parciais))
    content = [{"type": "text", "text": PEDIDO_MERGE_ANALISE + blocos}]
    print(f"[analise] fundindo {len(parciais)} lotes num resultado só", flush=True)
    texto, uso = _chamar_claude(content, modelo_usado, esforco_usado)
    return _texto_para_json(texto), uso


def _rodar_analise_ia(pdfs: list, model: str | None = None, effort: str | None = None,
                      ao_progresso=None):
    """Manda uma lista de PDFs (nome, bytes) pro Claude com o prompt padrão do
    Painel e devolve (doc, meta) — o JSON de análise pronto pra virar processo
    e os metadados de uso (modelo + tokens de entrada/saída, somados de todas
    as chamadas feitas) pro contador de gastos. Reaproveitado tanto pelo
    upload manual (analisar_ia) quanto pela análise automática de processos
    novos detectados na varredura.

    Documentos que juntos passam de 600 páginas (o teto de uma chamada) são
    divididos em lotes, cada um analisado à parte, e fundidos numa chamada
    final — só assim editais grandes de verdade (800+ páginas juntando tudo)
    saem sem faltar nada nem perder o cruzamento entre os documentos.

    `ao_progresso(etapa, atual, total)` é chamado a cada marco, pra tela poder
    mostrar em que pé está em vez de só um relógio correndo."""
    if not anthropic_client:
        raise RuntimeError("ANTHROPIC_API_KEY não configurada no servidor")

    avisar = ao_progresso or (lambda *a, **k: None)

    total_bytes = sum(len(dados) for _, dados in pdfs)
    if total_bytes > MAX_PDF_TOTAL_MB * 1024 * 1024:
        raise ValueError(f"Total dos PDFs excede {MAX_PDF_TOTAL_MB} MB")

    # antes o esforço só ia quando a tela mandava um válido, e sem ele a chamada
    # caía no padrão da API. Agora vai sempre explícito: o valor é o mesmo, mas
    # o registro de gasto passa a saber com que esforço aquele custo foi gasto
    # em vez de gravar em branco.
    esforco_usado = effort if effort in ESFORCOS_IA_PERMITIDOS else ESFORCO_PADRAO_ANALISE
    modelo_usado = model if model in MODELOS_IA_PERMITIDOS else ANTHROPIC_MODEL
    nomes_originais = [nome for nome, _ in pdfs]

    avisar("Preparando os documentos", 0, 0)
    partes = _fatiar_pdfs_grandes(pdfs)
    lotes = _agrupar_em_lotes(partes)
    # o agrupamento acima só sabe contar página e MB; esta etapa mede os tokens
    # de verdade e reparte de novo o que não couber na janela de contexto
    lotes = _repartir_por_tokens(lotes, modelo_usado)

    if len(lotes) == 1:
        # Uma chamada só: não há marco intermediário nenhum pra medir — a IA
        # lê tudo de uma vez. Manda total=0 pra tela mostrar barra
        # indeterminada em vez de uma porcentagem que não quer dizer nada.
        avisar("Lendo os documentos com a IA", 0, 0)
        doc, uso = _analisar_um_lote(lotes[0], modelo_usado, esforco_usado)
    else:
        total_paginas = sum(len(PdfReader(io.BytesIO(d)).pages) for _, d in partes)
        print(f"[analise] {total_paginas} páginas ao todo, acima do teto de "
              f"{PAGINAS_POR_REQUISICAO} por chamada — dividido em {len(lotes)} lotes, "
              f"mais uma chamada final pra fundir os resultados", flush=True)
        parciais = []
        uso = {"entrada": 0, "saida": 0}
        # os passos contados são os lotes + a fusão: é o que existe de marco
        # real, então a porcentagem mostrada corresponde a trabalho concluído
        passos = len(lotes) + 1
        for i, lote in enumerate(lotes, 1):
            avisar(f"Lendo parte {i} de {len(lotes)} ({total_paginas} páginas ao todo)",
                   i - 1, passos)
            doc_i, uso_i = _analisar_um_lote(lote, modelo_usado, esforco_usado)
            parciais.append(doc_i)
            uso["entrada"] += uso_i["entrada"]
            uso["saida"] += uso_i["saida"]
            print(f"[analise] lote {i}/{len(lotes)} concluído", flush=True)
        avisar("Juntando e cruzando as partes", len(lotes), passos)
        doc, uso_fusao = _fundir_analises(parciais, modelo_usado, esforco_usado)
        uso["entrada"] += uso_fusao["entrada"]
        uso["saida"] += uso_fusao["saida"]
        # "fontes" de cada bloco cita só os arquivos daquele lote; o resultado
        # final tem que citar o conjunto inteiro, não só o do último lote
        doc["fontes"] = "; ".join(nomes_originais)
        doc.setdefault("analise", {})["_sourceFiles"] = "; ".join(nomes_originais)

    uso["model"] = modelo_usado
    uso["esforco"] = esforco_usado
    doc["_iaModel"] = modelo_usado
    doc["_iaEsforco"] = esforco_usado
    return doc, uso


def _preparar_e_inserir_processo(doc: dict, criar_oportunidade: bool = True) -> dict:
    """Mesma preparação (id, timestamps, versão, defaults) que POST
    /api/processos faz — reaproveitada pela criação manual e pela criação
    automática a partir da análise de um processo novo do SharePoint.
    criar_oportunidade=False é usado por "promover" (Painel Gerencial → DATA
    SIN): a Oportunidade de origem já existe, então não faz sentido criar uma
    segunda — quem chama liga o processo novo a ELA na sequência."""
    pid = doc.get("id") or (_slug(doc.get("nome", "")) + "-" + uuid.uuid4().hex[:6])
    agora = _agora_ms()
    doc["id"] = pid
    doc.setdefault("criadoEm", agora)
    doc["atualizadoEm"] = agora
    doc["versao"] = int(doc.get("versao") or 1)
    doc.setdefault("analise", {})
    doc.setdefault("checklist", {})

    # guarda o que a IA respondeu originalmente, pra depois comparar com o que
    # a equipe deixou de fato — é o par (resposta da IA / correção humana) que
    # vira material de treino no futuro. Só faz sentido pra processo que
    # nasceu de IA; um processo criado manualmente não tem "resposta da IA"
    # pra comparar.
    if doc.get("origem") in ("ia", "sinki") and "_analiseOriginalIA" not in doc:
        doc["_analiseOriginalIA"] = copy.deepcopy(doc.get("analise") or {})

    doc["_id"] = pid
    del doc["id"]
    col_processos.insert_one(doc)
    _sync_oportunidade_do_processo(doc, criar_se_faltar=criar_oportunidade)
    return doc


# ──────────────────────────────────────────────────────────────────
# Ligação Processos → Painel Gerencial (Comercial)
# ──────────────────────────────────────────────────────────────────
# Decisão explícita do Gabriel: só processo criado a partir de agora ganha
# Oportunidade ligada automaticamente — processo já cadastrado antes disso
# não é tocado nem retroativamente migrado, mesmo que seja editado depois.
# Por isso _sync_oportunidade_do_processo só CRIA quando criar_se_faltar=True
# (chamado apenas no momento da criação do processo); toda atualização
# posterior (PATCH/PUT) só mexe numa Oportunidade que já existir ligada.
_MAPA_STATUS_PROCESSO_OPORTUNIDADE = {
    # status do processo -> (statusGanho, statusEnviadas, motivo)
    "pendente":       ("Pendente", "Não enviada", None),
    "em_analise":     ("Pendente", "Não enviada", None),
    "participar":     ("Pendente", "Enviada", None),
    "nao_participar": ("Perca", "Não enviada", "Decisão de não participar"),
    "em_disputa":     ("Pendente", "Enviada", None),
    "vencido":        ("Ganho", "Enviada", None),
    "perdido":        ("Perca", "Enviada", None),
}


def _parse_valor_processo(txt):
    """Extrai um número de um campo de texto livre tipo 'R$ 1.234.567,89' ou
    'até R$ 500 mil, a confirmar' — se não achar nada que pareça número,
    devolve None (não sobrescreve o que a Oportunidade já tinha)."""
    if not txt:
        return None
    m = re.search(r"[\d.,]+", str(txt))
    if not m:
        return None
    raw = m.group(0).strip(".,")
    if not raw:
        return None
    if "," in raw:
        raw = raw.replace(".", "").replace(",", ".")
    else:
        raw = raw.replace(".", "")
    try:
        valor = float(raw)
    except ValueError:
        return None
    return valor or None


def _sync_oportunidade_do_processo(doc: dict, criar_se_faltar: bool = False):
    """Mantém a Oportunidade ligada a este processo (col_comercial_oportunidades,
    campo processoId) em dia com nome/órgão/valor/status do processo. Chamada
    depois de toda escrita em col_processos (criação, PATCH, PUT) — sozinha,
    sem exigir nada da equipe nos dois cadastros."""
    oport = col_comercial_oportunidades.find_one({"processoId": doc["_id"]})
    if not oport and not criar_se_faltar:
        return

    status_ganho, status_enviadas, motivo = _MAPA_STATUS_PROCESSO_OPORTUNIDADE.get(
        doc.get("status") or "pendente", ("Pendente", "Não enviada", None))
    a = doc.get("analise") or {}
    hoje = date.today().isoformat()

    campos = {
        "cliente": a.get("geral_orgao") or (oport or {}).get("cliente") or "",
        "objeto": a.get("geral_objeto") or (oport or {}).get("objeto") or "",
        "numProposta": a.get("geral_numero") or (oport or {}).get("numProposta") or "",
        "segmento": "Público" if doc.get("type") == "publico" else "Privado",
        "statusEnviadas": status_enviadas,
        "statusGanho": status_ganho,
        "motivo": motivo or "",
    }
    valor = _parse_valor_processo(a.get("geral_valor") or a.get("custo_preco_max") or "")
    if valor:
        campos["valorLicitado"] = valor
    if status_ganho == "Ganho":
        campos["valorGanho"] = valor or (oport or {}).get("valorLicitado") or 0
        campos["dataConclusao"] = hoje
    elif status_ganho == "Perca":
        campos["dataConclusao"] = hoje

    if oport:
        oport.update(campos)
        col_comercial_oportunidades.replace_one({"_id": oport["_id"]}, oport)
    else:
        novo = dict(campos)
        novo.update({
            "_id": uuid.uuid4().hex, "processoId": doc["_id"],
            "empresa": "Sinape", "data": hoje, "percChanceReal": 0.5,
            "habilitacao": "SIM", "continuidadeOuNovo": "Novo",
            "novosClientes": "Não", "statusProcesso": "Em andamento", "consorcio": "Não",
        })
        col_comercial_oportunidades.insert_one(novo)


@app.route("/api/processos/analisar-ia", methods=["POST"])
def analisar_ia():
    arquivos = request.files.getlist("arquivos")
    if not arquivos:
        return jsonify({"erro": "Envie ao menos um arquivo no campo 'arquivos'"}), 400

    pdfs = []
    total_bytes = 0
    for arquivo in arquivos:
        if arquivo.mimetype != "application/pdf":
            return jsonify({"erro": f"Arquivo '{arquivo.filename}' não é PDF"}), 400
        dados = arquivo.read()
        total_bytes += len(dados)
        if total_bytes > MAX_PDF_TOTAL_MB * 1024 * 1024:
            return jsonify({"erro": f"Total dos PDFs excede {MAX_PDF_TOTAL_MB} MB"}), 400
        pdfs.append((arquivo.filename, dados))

    # Mesmo motivo do fluxo do SharePoint: PDF grande passa do timeout do
    # worker. Vai pra job. A diferença é que aqui a análise não cria processo —
    # ela devolve o JSON pra tela conferir e importar — então o resultado fica
    # guardado no próprio job.
    jid = _job_novo("analise_upload", ", ".join(n for n, _ in pdfs)[:80])
    _job_rodar_em_thread(jid, _analisar_upload_manual, jid=jid,
                         pdfs=pdfs, model=request.form.get("model"),
                         effort=request.form.get("effort"))
    return jsonify({"job_id": jid, "status": "rodando"}), 202


def _analisar_upload_manual(jid, pdfs, model, effort):
    """Analisa PDFs enviados pela tela e guarda o JSON no job — este fluxo não
    cria processo sozinho, quem importa é a equipe depois de conferir."""
    doc, uso = _rodar_analise_ia(pdfs, model=model, effort=effort)
    _registrar_gasto(uso["model"], uso, processo_nome=doc.get("nome", ""), origem="upload manual")
    col_jobs.update_one({"_id": jid}, {"$set": {"documento": doc}})
    return None


# Média medida nos documentos reais desta operação (editais, TRs e planilhas
# orçamentárias do DNIT/concessionárias): cada página custa ~1.600 tokens de
# imagem, que a API cobra sempre porque todo PDF também entra como imagem, mais
# ~700 de texto. Serve pra estimativa de tela, não pra decidir corte — quem
# decide isso é a contagem real da API em _repartir_por_tokens.
TOKENS_POR_PAGINA_ESTIMADO = 2300


def _medir_pdf(dados: bytes) -> tuple:
    """(páginas, tokens estimados) de um PDF, pela contagem de páginas.

    Cheguei a estimar lendo o texto de cada arquivo, o que é mais preciso, mas
    inviável aqui: extrair texto dos três orçamentos desta licitação levava 45
    segundos (18 mesmo amostrando 2 páginas por arquivo), porque abrir um PDF
    de tabela densa já é caro. A tela ficaria travada quase meio minuto só pra
    listar arquivos. Com a média por página a lista sai instantânea, e a
    decisão que ela apoia — "este anexo de 234 páginas vale a pena?" — se
    responde pelo número de páginas de qualquer jeito."""
    try:
        paginas = len(PdfReader(io.BytesIO(dados)).pages)
        return paginas, paginas * TOKENS_POR_PAGINA_ESTIMADO
    except Exception:
        return 0, 0


@app.route("/api/pastas/arquivos", methods=["GET"])
def listar_arquivos_da_pasta():
    """Lista os PDFs de uma pasta do SharePoint com tamanho, páginas e custo
    estimado — pra tela deixar a equipe escolher o que entra na análise antes
    de gastar. Sem isso, a única forma de tirar um anexo caro da análise era
    renomear o arquivo no SharePoint."""
    caminho = (request.args.get("caminho_pasta") or "").strip().strip("/")
    if not caminho:
        return jsonify({"erro": "Informe o caminho_pasta."}), 400
    if not (MONTADOR_TENANT_ID and MONTADOR_CLIENT_ID and MONTADOR_CLIENT_SECRET):
        return jsonify({"erro": "SharePoint não configurado neste servidor."}), 503

    modelo = request.args.get("model")
    modelo = modelo if modelo in MODELOS_IA_PERMITIDOS else ANTHROPIC_MODEL
    cfg = {"MODO_LOCAL": False, "TENANT_ID": MONTADOR_TENANT_ID,
           "CLIENT_ID": MONTADOR_CLIENT_ID, "CLIENT_SECRET": MONTADOR_CLIENT_SECRET}
    try:
        # apenas=[] não serve aqui: a listagem precisa ver TUDO que existe na
        # pasta, inclusive o que a marca 'DATA SIN' esconderia
        pdfs = baixar_pdfs_da_pasta(cfg, caminho, limite_mb=MAX_PDF_TOTAL_MB, apenas=None)
    except requests.HTTPError as e:
        if e.response is not None and e.response.status_code == 404:
            return jsonify({"erro": "Essa pasta não foi encontrada no SharePoint."}), 404
        return jsonify({"erro": f"Falha ao ler a pasta no SharePoint: {e}"}), 502
    except ValueError as e:
        return jsonify({"erro": str(e)}), 400
    except Exception as e:
        return jsonify({"erro": f"Falha ao ler a pasta no SharePoint: {e}"}), 502

    preco_entrada = PRECOS_MODELOS.get(modelo, {}).get("entrada", 0.0)
    arquivos = []
    for p in pdfs:
        paginas, tokens = _medir_pdf(p["bytes"])
        arquivos.append({
            "nome": p["nome"],
            "paginas": paginas,
            "mb": round(len(p["bytes"]) / 1024 / 1024, 2),
            "tokens_estimados": tokens,
            "custo_estimado_usd": round(tokens * preco_entrada / 1_000_000, 2),
        })
    return jsonify({
        "caminho_pasta": caminho,
        "model": modelo,
        "arquivos": arquivos,
        "total_paginas": sum(a["paginas"] for a in arquivos),
        "total_custo_usd": round(sum(a["custo_estimado_usd"] for a in arquivos), 2),
    })


@app.route("/api/processos/analisar-novo", methods=["POST"])
def analisar_processo_novo():
    """A partir de um item novo já identificado na varredura do SharePoint
    (pasta conhecida, sem precisar de localização fuzzy), baixa os PDFs,
    roda a análise por IA e já cria o processo no Painel — o botão "Rodar
    análise e preencher informações" dentro do relatório do dia."""
    if not (MONTADOR_TENANT_ID and MONTADOR_CLIENT_ID and MONTADOR_CLIENT_SECRET):
        return jsonify({
            "erro": "SharePoint não configurado neste servidor. Defina MONTADOR_TENANT_ID, "
                    "MONTADOR_CLIENT_ID e MONTADOR_CLIENT_SECRET."
        }), 503

    corpo = request.get_json(silent=True) or {}
    caminho_pasta = corpo.get("caminho_pasta")
    tipo = corpo.get("tipo")
    if not caminho_pasta or tipo not in ("publico", "privado"):
        return jsonify({"erro": "Informe 'caminho_pasta' e 'tipo' ('publico' ou 'privado')."}), 400

    # arquivos escolhidos na tela; ausente = comportamento de sempre (tudo, ou
    # só o que estiver marcado com 'DATA SIN' no nome)
    apenas = corpo.get("arquivos")
    if apenas is not None:
        if not isinstance(apenas, list):
            return jsonify({"erro": "'arquivos' precisa ser uma lista de nomes."}), 400
        if not apenas:
            return jsonify({"erro": "Escolha pelo menos um arquivo para analisar."}), 400

    cfg = {
        "MODO_LOCAL": False,
        "TENANT_ID": MONTADOR_TENANT_ID,
        "CLIENT_ID": MONTADOR_CLIENT_ID,
        "CLIENT_SECRET": MONTADOR_CLIENT_SECRET,
    }
    try:
        pdfs_pasta = baixar_pdfs_da_pasta(cfg, caminho_pasta, limite_mb=MAX_PDF_TOTAL_MB,
                                          apenas=apenas)
    except requests.HTTPError as e:
        if e.response is not None and e.response.status_code == 404:
            return jsonify({
                "erro": "Essa pasta não foi encontrada no SharePoint agora. Ela pode ter sido "
                        "renomeada, movida ou removida desde a última varredura. Clique em "
                        "\"Executar análise agora\" para atualizar a lista e tente de novo."
            }), 404
        return jsonify({"erro": f"Falha ao baixar documentos do SharePoint (erro {e.response.status_code if e.response is not None else '?'})."}), 502
    except ValueError as e:
        # pasta passa do limite de MB (a mensagem já vem pronta pra tela)
        return jsonify({"erro": str(e)}), 400
    except Exception as e:
        return jsonify({"erro": f"Falha ao baixar documentos do SharePoint: {e}"}), 502
    if not pdfs_pasta:
        if apenas:
            return jsonify({
                "erro": "Nenhum dos arquivos escolhidos foi encontrado na pasta. Ela pode ter "
                        "mudado desde que a lista foi carregada — feche e abra de novo."
            }), 404
        return jsonify({"erro": "Nenhum PDF encontrado nessa pasta do SharePoint."}), 404

    # Daqui pra baixo é a parte demorada — vai pra uma thread. O download do
    # SharePoint ficou acima de propósito: é rápido e os erros dele (pasta
    # sumiu, sem PDF) valem mais respondidos na hora, com o status HTTP certo,
    # do que escondidos dentro de um job.
    pdfs = [(p["nome"], p["bytes"]) for p in pdfs_pasta]
    jid = _job_novo("analise_sharepoint", caminho_pasta.rsplit("/", 1)[-1] or caminho_pasta)
    _job_rodar_em_thread(
        jid, _analisar_e_criar_processo,
        pdfs=pdfs, tipo=tipo, caminho_pasta=caminho_pasta,
        model=corpo.get("model"), effort=corpo.get("effort"), job_id=jid,
    )
    return jsonify({"job_id": jid, "status": "rodando"}), 202


def _analisar_e_criar_processo(pdfs, tipo, caminho_pasta, model, effort, job_id=None) -> str:
    """Roda a análise e cria o processo. Só é chamada de dentro de uma thread
    de job — devolve o id do processo criado, e qualquer erro sobe pro job.

    `job_id` (e não `jid`) porque _job_rodar_em_thread já recebe `jid` como
    primeiro parâmetro: repetir o nome fazia os dois colidirem em tempo de
    execução."""
    # o progresso vai pro job pra tela poder mostrar a barra em vez de só um
    # relógio correndo; sem job_id (chamada fora de job) simplesmente não reporta
    jid = job_id
    avisar = (lambda e, a, t: _job_progresso(jid, e, a, t)) if jid else None
    doc, uso = _rodar_analise_ia(pdfs, model=model, effort=effort, ao_progresso=avisar)
    if jid:
        _job_progresso(jid, "Criando o processo no Painel", 0, 0)

    doc["type"] = tipo
    doc.setdefault("origem", "ia")
    # o baseline pra comparar correções depois é só o que a IA respondeu de
    # fato — captura antes de colar o link da pasta (isso não veio da IA)
    doc["_analiseOriginalIA"] = copy.deepcopy(doc.get("analise") or {})
    url_pasta = f"https://{SITE_HOSTNAME}{SITE_PATH}/Documentos/{caminho_pasta}"
    doc.setdefault("analise", {})["geral_pasta_sharepoint"] = url_pasta

    try:
        doc = _preparar_e_inserir_processo(doc)
    except DuplicateKeyError:
        raise ValueError("Já existe processo com esse id no Painel.")
    # o gasto é registrado mesmo se ninguém estiver com a tela aberta — era
    # justamente isso que se perdia quando o worker morria no timeout
    _registrar_gasto(uso["model"], uso, processo_id=doc.get("_id"),
                     processo_nome=doc.get("nome", ""), origem="varredura automática")
    _concluir_pendente(caminho_pasta, doc["_id"])
    return doc["_id"]


# ──────────────────────────────────────────────────────────────────
# Painel de prazos — junta os prazos de todos os processos numa lista só
# ──────────────────────────────────────────────────────────────────
# Só os campos que a IA/a equipe preenchem como DATA de verdade (AAAA-MM-DD);
# prazo_execucao/prazo_vigencia/prazo_contrato ficam de fora de propósito -
# são duração em texto ("12 meses", "30 dias após assinatura"), não uma data
# marcável no calendário.
CAMPOS_PRAZO_DATA = [
    ("prazo_publicacao", "Publicação / envio da carta-convite"),
    ("prazo_esclarecimento", "Prazo para esclarecimentos"),
    ("prazo_impugnacao", "Prazo para impugnação"),
    ("prazo_abertura", "Abertura / entrega da proposta"),
    ("prazo_habilitacao", "Prazo para envio de habilitação"),
]
# processo com esse status já foi decidido - prazo dele não interessa mais
# no painel do dia a dia (evita virar ruído). "Vencido" aqui é o sentido de
# licitação: a SINAPE VENCEU o certame - não confundir com prazo vencido.
STATUS_PRAZO_ENCERRADO = {"Vencido", "Perdido", "Decidido não participar"}
PRAZO_JANELA_PASSADO_DIAS = 60   # atrasado além disso não aparece mais (ruído velho)
PRAZO_JANELA_FUTURO_DIAS = 180   # prazo longe demais também não ajuda o dia a dia


def _parse_data_prazo(valor):
    """Aceita AAAA-MM-DD (o formato que a IA usa) e, com tolerância,
    DD/MM/AAAA (caso alguém digite manualmente na Análise Crítica)."""
    valor = (valor or "").strip()
    if not valor:
        return None
    try:
        return date.fromisoformat(valor)
    except ValueError:
        pass
    m = re.match(r"^(\d{1,2})/(\d{1,2})/(\d{4})$", valor)
    if m:
        d, mo, y = (int(x) for x in m.groups())
        try:
            return date(y, mo, d)
        except ValueError:
            return None
    return None


def _prazos_do_processo(doc):
    """Devolve a lista de prazos com data reconhecível deste processo, cada
    um já com quantos dias faltam (negativo = atrasado)."""
    analise = doc.get("analise") or {}
    if analise.get("geral_status") in STATUS_PRAZO_ENCERRADO:
        return []
    hoje = date.today()
    nome = doc.get("nome") or "(sem nome)"
    achados = []

    for campo, rotulo in CAMPOS_PRAZO_DATA:
        data_prazo = _parse_data_prazo(analise.get(campo))
        if campo == "prazo_abertura" and data_prazo is None:
            data_prazo = _parse_data_prazo(analise.get("geral_abertura"))  # sinônimo antigo
        if data_prazo:
            achados.append((rotulo, data_prazo))

    for linha in analise.get("tbl_prazo") or []:
        if not isinstance(linha, list) or len(linha) < 3:
            continue
        marco, data_prazo = (linha[0] or "").strip(), _parse_data_prazo(linha[2])
        if data_prazo and marco:
            achados.append((f"Cronograma: {marco}", data_prazo))

    resultado = []
    for rotulo, data_prazo in achados:
        dias = (data_prazo - hoje).days
        if -PRAZO_JANELA_PASSADO_DIAS <= dias <= PRAZO_JANELA_FUTURO_DIAS:
            resultado.append({
                "processo_id": doc["_id"], "processo_nome": nome,
                "tipo": doc.get("type"), "campo": rotulo,
                "data": data_prazo.isoformat(), "dias": dias,
                "categoria": ("atrasado" if dias < 0 else "hoje" if dias == 0
                              else "semana" if dias <= 7 else "mes" if dias <= 30 else "depois"),
            })
    return resultado


# campos da análise que o painel gerencial lê — mandar o documento inteiro de
# cada processo só pra calcular isso seria desperdício de banda e de memória
_CAMPOS_GERENCIAIS = (
    "geral_orgao", "geral_numero", "geral_uf", "geral_valor", "geral_abertura",
    "custo_preco_max", "prazo_abertura",
    "hab_jur_consorcio", "hab_jur_lider", "hab_jur_sub",
    "hab_ef_lc_ok", "hab_ef_cap_ok",
    "hab_tec_atestado", "hab_tec_quant_min",
    "risco_decisao", "risco_resp_decisao", "risks",
)


@app.route("/api/gerencial", methods=["GET"])
def painel_gerencial():
    """Dados crus do acompanhamento por fases de TODOS os processos, pro painel
    gerencial mostrar a carteira inteira numa tela.

    Quem calcula porcentagem e semáforo é a tela, não este endpoint: a mesma
    conta roda dentro do processo aberto, e ter duas implementações da regra
    (uma aqui, outra lá) é garantia de divergirem com o tempo. Daqui sai só o
    que a conta lê — das exigências, nem o texto vai junto, só categoria,
    obrigatoriedade e avaliação."""
    saida = []
    for doc in col_processos.find().sort("atualizadoEm", DESCENDING):
        analise = doc.get("analise") or {}
        exigencias = doc.get("exigencias")
        saida.append({
            "id": doc["_id"],
            "nome": doc.get("nome") or "(sem nome)",
            "type": doc.get("type") or "publico",
            "status": doc.get("status") or "em_analise",
            "progress": int(doc.get("progress") or 0),
            "atualizadoEm": doc.get("atualizadoEm") or 0,
            "atualizadoPor": doc.get("atualizadoPor") or "",
            "analise": {k: analise[k] for k in _CAMPOS_GERENCIAIS if k in analise},
            "exigencias": [
                {"categoria": e.get("categoria") or "",
                 "obrigatorio": e.get("obrigatorio") is not False,
                 "checks": e.get("checks") or {}}
                for e in (exigencias if isinstance(exigencias, list) else [])
            ],
        })
    return jsonify({"processos": saida})


@app.route("/api/prazos", methods=["GET"])
def painel_prazos():
    """Junta os prazos de TODOS os processos ativos numa lista só, ordenada
    do mais urgente pro mais distante - hoje cada prazo só aparece dentro do
    processo dele, um de cada vez; aqui dá pra ver o que vence essa semana em
    qualquer processo, sem abrir um por um."""
    prazos = []
    for doc in col_processos.find():
        prazos.extend(_prazos_do_processo(doc))
    prazos.sort(key=lambda p: p["dias"])
    return jsonify({
        "total": len(prazos),
        "atrasados": sum(1 for p in prazos if p["categoria"] == "atrasado"),
        "esta_semana": sum(1 for p in prazos if p["categoria"] in ("hoje", "semana")),
        "prazos": prazos,
    })


@app.route("/api/correcoes", methods=["GET"])
def listar_correcoes():
    """Cada correção é um par (o que a IA respondeu / o que a equipe deixou
    de fato) num campo de um processo — a matéria-prima pra treinar um modelo
    especialista no futuro. Se junta sozinha: toda vez que alguém edita um
    campo de um processo criado por IA/Sinki, o par entra aqui. Editar de
    volta pro valor original apaga o registro correspondente."""
    registros = list(col_correcoes.find().sort("atualizadoEm", DESCENDING))
    return jsonify({"total": len(registros), "correcoes": [_sem_id_mongo(r) for r in registros]})


# ──────────────────────────────────────────────────────────────────
# Sinki — conversa com a IA do Painel
# ──────────────────────────────────────────────────────────────────
SINKI_DIR = UPLOAD_DIR / "sinki"
SINKI_MAX_RODADAS = 12  # teto de idas e vindas com as ferramentas numa única resposta
TIPOS_IMAGEM = {"image/jpeg", "image/png", "image/gif", "image/webp"}
EXTENSOES_TEXTO = {".txt", ".md", ".csv", ".json", ".xml", ".log", ".yaml", ".yml"}


def _bloco_de_arquivo(nome: str, dados: bytes, content_type: str):
    """Converte um anexo no bloco de conteúdo que a API entende. PDF e imagem
    vão nativos; arquivo de texto entra transcrito. Formato não suportado
    (ex.: .xlsx, .docx) devolve None e o chamador avisa a equipe."""
    nome_lower = (nome or "").lower()
    if nome_lower.endswith(".pdf") or content_type == "application/pdf":
        return {"type": "document", "source": {
            "type": "base64", "media_type": "application/pdf",
            "data": base64.standard_b64encode(dados).decode("ascii")}}
    if content_type in TIPOS_IMAGEM:
        return {"type": "image", "source": {
            "type": "base64", "media_type": content_type,
            "data": base64.standard_b64encode(dados).decode("ascii")}}
    if any(nome_lower.endswith(e) for e in EXTENSOES_TEXTO):
        texto = dados.decode("utf-8", errors="replace")
        return {"type": "text", "text": f"--- conteúdo de {nome} ---\n{texto}"}
    return None


# ── ferramentas do Sinki: é o que dá "mãos" a ele dentro do Painel ──
# De propósito NÃO existe ferramenta que apague processo, anexo ou conversa:
# tudo aqui é leitura, preenchimento ou criação, então nenhum pedido mal
# interpretado consegue destruir trabalho da equipe.
SINKI_FERRAMENTAS = [
    {
        "name": "listar_processos",
        "description": "Lista os processos cadastrados no Painel, com nome, tipo, status e progresso. "
                       "Use para responder o que existe, o que está em cada etapa, ou para achar o id "
                       "de um processo antes de abrir ou alterar.",
        "input_schema": {
            "type": "object",
            "properties": {
                "tipo": {"type": "string", "enum": ["publico", "privado"],
                         "description": "Filtra por licitação pública ou contratação privada."},
                "busca": {"type": "string", "description": "Trecho do nome do processo."},
            },
        },
    },
    {
        "name": "ver_processo",
        "description": "Abre um processo inteiro: análise crítica preenchida, exigências do edital, "
                       "checklist e o que já foi marcado. Use antes de responder qualquer pergunta "
                       "específica sobre um processo.",
        "input_schema": {
            "type": "object",
            "properties": {
                "processo": {"type": "string", "description": "Id do processo ou parte do nome."},
            },
            "required": ["processo"],
        },
    },
    {
        "name": "ver_concorrentes",
        "description": "Consulta as verificações já feitas de documentação de empresas concorrentes "
                       "— o que cada uma atende ou não atende num edital, e por quê. Use pra responder "
                       "se uma empresa concorrente cumpre as exigências (ex.: 'a empresa X atende as "
                       "exigências técnicas daquele edital?'). Omita 'processo' pra buscar em todos os "
                       "processos — útil pra saber se essa empresa já apareceu antes, em outro certame.",
        "input_schema": {
            "type": "object",
            "properties": {
                "processo": {"type": "string", "description": "Id do processo ou parte do nome. "
                                                               "Omita pra buscar em todos os processos."},
                "empresa": {"type": "string", "description": "Nome (ou parte do nome) da empresa "
                                                              "concorrente. Omita pra ver todas as "
                                                              "verificações daquele processo."},
            },
        },
    },
    {
        "name": "ver_gastos",
        "description": "Quanto já foi gasto com IA: total de tokens, custo em dólar e real, e o "
                       "detalhamento por análise.",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "ver_atualizacoes_do_dia",
        "description": "Último relatório de varredura do SharePoint: propostas e editais novos, "
                       "movimentações de status e os processos novos ainda não analisados.",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "atualizar_processo",
        "description": "Preenche ou corrige campos de um processo já cadastrado. Use as chaves do "
                       "modelo padrão (ex.: geral_orgao, prazo_abertura, hab_tec_rt_nome). Só mexa "
                       "no que o usuário pediu.",
        "input_schema": {
            "type": "object",
            "properties": {
                "processo": {"type": "string", "description": "Id do processo ou parte do nome."},
                "campos": {"type": "object",
                           "description": "Pares chave/valor da análise crítica a gravar."},
                "status": {"type": "string",
                           "description": "Opcional: novo status do processo (ex.: em_analise)."},
            },
            "required": ["processo", "campos"],
        },
    },
    {
        "name": "marcar_checklist",
        "description": "Marca ou desmarca itens do checklist de um processo. Identifique os itens "
                       "pelo texto; confira antes com ver_processo.",
        "input_schema": {
            "type": "object",
            "properties": {
                "processo": {"type": "string", "description": "Id do processo ou parte do nome."},
                "itens": {"type": "array", "items": {"type": "string"},
                          "description": "Trechos do texto dos itens a marcar."},
                "marcar": {"type": "boolean",
                           "description": "true marca como feito, false desmarca. Padrão true."},
            },
            "required": ["processo", "itens"],
        },
    },
    {
        "name": "criar_processo",
        "description": "Cria um processo novo no Painel a partir da análise estruturada que você "
                       "mesmo produziu (mesmo formato da seção ANÁLISE ESTRUTURADA DE EDITAL). "
                       "Use quando anexarem um edital e pedirem para cadastrar.",
        "input_schema": {
            "type": "object",
            "properties": {
                "documento": {"type": "object",
                              "description": "O JSON completo do processo, no contrato da análise."},
            },
            "required": ["documento"],
        },
    },
    {
        "name": "executar_varredura_sharepoint",
        "description": "Varre o SharePoint agora, compara com a varredura anterior e publica o "
                       "relatório do dia. Demora cerca de meio minuto. Use quando pedirem para "
                       "conferir se entrou processo novo.",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "consultar_jurisprudencia",
        "description": "Consulta a biblioteca de jurisprudência do TCU (manual oficial "
                       "\"Licitações e Contratos\", 5ª edição) pra fundamentar impugnação, "
                       "pedido de esclarecimento ou recurso — e pra checar se uma exigência do "
                       "edital extrapola o que o TCU admite. Busque por tema ('atestado de "
                       "capacidade técnica', 'capital social mínimo', 'prazo de impugnação'), "
                       "por número de acórdão ('1604/2025'), por súmula ('Súmula 263') ou pelo "
                       "número da seção ('5.5.2'). Use SEMPRE que for citar entendimento do TCU "
                       "— nunca cite acórdão de memória, porque errar o número desmoraliza a "
                       "peça inteira. Vale só pra processo PÚBLICO (Lei 14.133/2021); em "
                       "processo privado não se cita TCU.",
        "input_schema": {
            "type": "object",
            "properties": {
                "busca": {"type": "string",
                          "description": "Tema, número de acórdão, súmula ou número da seção."},
                "modo": {"type": "string", "enum": ["resumo", "completo"],
                         "description": "'resumo' (padrão) traz só os enunciados de acórdão e "
                                        "súmula da seção — compacto e suficiente pra citar. "
                                        "'completo' traz o texto inteiro, use quando precisar "
                                        "do raciocínio e do contexto normativo."},
            },
            "required": ["busca"],
        },
    },
]


def _sinki_achar_processo(referencia: str):
    """Aceita id exato ou pedaço do nome — a equipe fala pelo nome, não pelo id."""
    doc = col_processos.find_one({"_id": referencia})
    if doc:
        return doc
    ref = _norm(referencia)
    candidatos = [d for d in col_processos.find() if ref in _norm(d.get("nome", ""))]
    return candidatos[0] if len(candidatos) == 1 else (candidatos or None)


def _norm(texto):
    s = (texto or "").lower()
    for de, para in (("àáâãä", "a"), ("èéêë", "e"), ("ìíîï", "i"),
                     ("òóôõö", "o"), ("ùúûü", "u"), ("ç", "c")):
        for c in de:
            s = s.replace(c, para)
    return s


# ── biblioteca de jurisprudência do TCU ───────────────────────────────────
RE_SECAO = re.compile(r"^\s*(\d+(?:\.\d+){0,4})\.?\s*$")
RE_ACORDAO_BUSCA = re.compile(r"(\d{1,5})\s*/\s*(\d{4})")
RE_SUMULA_BUSCA = re.compile(r"s[uú]mula[\s\-–—]*(?:tcu)?[\s\-–—]*(\d{1,3})", re.I)
# no texto convertido, cada entendimento vira uma linha "Acórdão X/Y-TCU-Órgão | ..."
RE_ENUNCIADO = re.compile(r"^\s*(Ac[óo]rd[ãa]o\s+\d{1,5}/\d{4}[^|]*|S[úu]mula[^|]{0,30})\|\s*(.+)$")


def _tcu_texto_da_secao(entrada):
    caminho = BIBLIOTECA_TCU_DIR / "secoes" / entrada["arquivo"]
    try:
        return caminho.read_text(encoding="utf-8")
    except Exception:
        return ""


def _tcu_enunciados(texto, limite=60):
    """Extrai só as linhas de acórdão/súmula — é o que serve pra citar numa peça,
    e cabe numa fração dos tokens do texto completo da seção."""
    achados = []
    for linha in texto.splitlines():
        m = RE_ENUNCIADO.match(linha)
        if m:
            corpo = m.group(2).strip()
            if corpo.lower().startswith("[enunciado]"):
                corpo = corpo[len("[enunciado]"):].strip()
            achados.append({"referencia": m.group(1).strip(), "entendimento": corpo[:700]})
        if len(achados) >= limite:
            break
    return achados


def _tcu_buscar(busca):
    """Devolve as seções que batem com a busca, mais relevante primeiro.
    Aceita número de seção ('5.5.2'), acórdão ('1604/2025'), súmula ou tema."""
    secoes = BIBLIOTECA_TCU.get("secoes") or []
    if not secoes:
        return []
    termo = (busca or "").strip()

    m = RE_SECAO.match(termo)
    if m:  # pediu uma seção específica: entrega ela, mesmo se estiver fora do escopo
        return [s for s in secoes if s["numero"] == m.group(1)]

    m = RE_SUMULA_BUSCA.search(termo)
    if m:
        n = int(m.group(1))
        return [s for s in secoes if n in (s.get("sumulas") or []) and s["escopo"] != "fora"]

    m = RE_ACORDAO_BUSCA.search(termo)
    if m:
        alvo = f"{int(m.group(1))}/{m.group(2)}"
        achados = [s for s in secoes if alvo in (s.get("acordaos") or [])]
        return sorted(achados, key=lambda s: s["escopo"] != "nucleo")

    # Busca por tema. A pontuação é por PALAVRA, não por substring da frase
    # inteira: quem pergunta escreve "nosso preço foi considerado inexequível",
    # e a palavra-chave cadastrada é "preço inexequível" — casar a frase toda
    # falha justamente nos casos reais, porque as palavras não vêm coladas.
    alvo = _norm(termo)
    palavras = [p for p in re.split(r"\W+", alvo) if len(p) > 3]
    pontuados = []
    for s in secoes:
        if s["escopo"] == "fora":
            continue
        pontos = 0
        chaves = [_norm(c) for c in s.get("palavras_chave") or []]
        palavras_das_chaves = set()
        for ch in chaves:
            palavras_das_chaves.update(w for w in re.split(r"\W+", ch) if len(w) > 3)
            if ch and (ch in alvo or alvo in ch):
                pontos += 10          # a expressão inteira bateu
        pontos += sum(5 for p in palavras if p in palavras_das_chaves)

        titulo = _norm(s["titulo"])
        if alvo in titulo:
            pontos += 8
        pontos += sum(3 for p in palavras if p in titulo)

        # rede de segurança: só ~1/3 das seções tem palavra-chave escrita à mão;
        # as demais dependeriam de a frase casar com o título. Os termos
        # extraídos do próprio texto (já sem os genéricos) cobrem esse buraco,
        # mas pesam menos que uma palavra-chave curada.
        termos = set(s.get("termos") or [])
        pontos += sum(2 for p in palavras if p in termos)
        if s["escopo"] == "nucleo":
            pontos = int(pontos * 1.3)
        if pontos:
            pontuados.append((pontos, s))
    pontuados.sort(key=lambda t: -t[0])
    return [s for _, s in pontuados[:5]]


def _sinki_rodar_ferramenta(nome: str, entrada: dict, modelo_usado: str = ""):
    """Executa uma ferramenta e devolve (resultado_pro_modelo, acao_pro_usuario).
    'acao' só é preenchida quando algo mudou de fato no Painel, pra que a tela
    possa mostrar à equipe exatamente o que o Sinki fez."""
    if nome == "listar_processos":
        consulta = {}
        if entrada.get("tipo"):
            consulta["type"] = entrada["tipo"]
        docs = list(col_processos.find(consulta).sort("atualizadoEm", DESCENDING))
        if entrada.get("busca"):
            b = _norm(entrada["busca"])
            docs = [d for d in docs if b in _norm(d.get("nome", ""))]
        return {"total": len(docs), "processos": [{
            "id": d["_id"], "nome": d.get("nome"), "tipo": d.get("type"),
            "status": d.get("status"), "progresso": d.get("progress", 0),
        } for d in docs[:60]]}, None

    if nome == "ver_processo":
        doc = _sinki_achar_processo(entrada.get("processo", ""))
        if not doc:
            return {"erro": "Nenhum processo com esse id ou nome."}, None
        if isinstance(doc, list):
            return {"erro": "Mais de um processo bate com esse nome — seja mais específico.",
                    "candidatos": [{"id": d["_id"], "nome": d.get("nome")} for d in doc[:10]]}, None
        analise = {k: v for k, v in (doc.get("analise") or {}).items() if v not in ("", None, [])}
        checklist_marcado = doc.get("checklist") or {}
        concorrentes = doc.get("concorrentes") or []
        return {
            "id": doc["_id"], "nome": doc.get("nome"), "tipo": doc.get("type"),
            "status": doc.get("status"), "progresso": doc.get("progress", 0),
            "analise": analise,
            "exigencias": doc.get("exigencias") or [],
            "checklist_do_edital": (doc.get("schemaCustom") or {}).get("checklist") or [],
            "itens_ja_marcados": checklist_marcado,
            "concorrentes_verificados": [c.get("empresa") for c in concorrentes] if concorrentes else [],
        }, None

    if nome == "ver_concorrentes":
        processo_ref = entrada.get("processo")
        empresa_ref = _norm(entrada.get("empresa") or "")
        if processo_ref:
            doc = _sinki_achar_processo(processo_ref)
            if not doc:
                return {"erro": "Nenhum processo com esse id ou nome."}, None
            if isinstance(doc, list):
                return {"erro": "Mais de um processo bate com esse nome — seja mais específico.",
                        "candidatos": [{"id": d["_id"], "nome": d.get("nome")} for d in doc[:10]]}, None
            docs = [doc]
        else:
            docs = list(col_processos.find())

        verificacoes = []
        for d in docs:
            for c in d.get("concorrentes") or []:
                if empresa_ref and empresa_ref not in _norm(c.get("empresa", "")):
                    continue
                verificacoes.append({
                    "processo_id": d["_id"], "processo_nome": d.get("nome"),
                    "empresa": c.get("empresa"), "resumo": c.get("resumo"),
                    "itens": [{"ref": i.get("ref"), "categoria": i.get("categoria"),
                               "descricao_exigencia": i.get("descricao_exigencia"),
                               "atende": i.get("atende"), "observacao": i.get("observacao"),
                               "fundamento_recurso": i.get("fundamento_recurso")}
                              for i in c.get("itens") or []],
                })
        if not verificacoes:
            return {"erro": "Nenhuma verificação de concorrente encontrada com esses filtros."}, None
        return {"total": len(verificacoes), "verificacoes": verificacoes}, None

    if nome == "consultar_jurisprudencia":
        busca = (entrada.get("busca") or "").strip()
        if not busca:
            return {"erro": "Diga o que procurar: um tema, um número de acórdão ou uma seção."}, None
        achados = _tcu_buscar(busca)
        if not achados:
            return {"erro": f"Nada encontrado para '{busca}' na biblioteca do TCU.",
                    "dica": "Tente o tema por extenso (ex.: 'atestado de capacidade técnica'), "
                            "o número do acórdão (ex.: '1604/2025') ou o número da seção "
                            "(ex.: '5.5.2'). Assuntos de governança interna do órgão e de "
                            "dispensa/inexigibilidade ficam fora da biblioteca de propósito."}, None

        completo = entrada.get("modo") == "completo"
        principal = achados[0]
        texto = _tcu_texto_da_secao(principal)
        resultado = {
            "secao": principal["numero"],
            "titulo": principal["titulo"],
            "escopo": principal["escopo"],
            "url": principal["url"],
            "fonte": BIBLIOTECA_TCU.get("fonte"),
            "aviso": BIBLIOTECA_TCU.get("observacao"),
        }
        if completo:
            resultado["texto"] = texto[:45000]
            resultado["truncado"] = len(texto) > 45000
        else:
            resultado["entendimentos"] = _tcu_enunciados(texto)
            resultado["nota"] = ("Estes são os enunciados da seção. Peça modo 'completo' se "
                                 "precisar do raciocínio e das referências normativas.")
        if len(achados) > 1:
            resultado["outras_secoes"] = [
                {"secao": s["numero"], "titulo": s["titulo"]} for s in achados[1:]
            ]
        return resultado, None

    if nome == "ver_gastos":
        registros = list(col_gastos.find(sort=[("criadoEm", DESCENDING)]))
        ent = sum(r.get("tokens_entrada", 0) for r in registros)
        sai = sum(r.get("tokens_saida", 0) for r in registros)
        usd = round(sum(r.get("custo_usd", 0.0) for r in registros), 4)
        return {"total_analises": len(registros), "tokens_entrada": ent, "tokens_saida": sai,
                "custo_usd": usd, "custo_brl_aprox": round(usd * USD_PARA_BRL, 2),
                "itens": [{"processo": r.get("processo_nome"), "modelo": r.get("model"),
                           "origem": r.get("origem"), "custo_usd": r.get("custo_usd")}
                          for r in registros[:40]]}, None

    if nome == "ver_atualizacoes_do_dia":
        doc = col_relatorios.find_one(sort=[("criadoEm", DESCENDING)])
        if not doc:
            return {"erro": "Nenhuma varredura publicada ainda."}, None
        return {"titulo": doc.get("titulo"), "conteudo": doc.get("conteudo"),
                "processos_novos": doc.get("novos") or []}, None

    if nome == "atualizar_processo":
        doc = _sinki_achar_processo(entrada.get("processo", ""))
        if not doc or isinstance(doc, list):
            return {"erro": "Processo não encontrado ou ambíguo — confira com listar_processos."}, None
        campos = entrada.get("campos") or {}
        if not campos and not entrada.get("status"):
            return {"erro": "Nada para atualizar."}, None
        mudanca = {"atualizadoEm": _agora_ms(), "versao": (doc.get("versao") or 1) + 1,
                   "atualizadoPor": "Sinki"}
        for k, v in campos.items():
            mudanca["analise." + k] = v
        if entrada.get("status"):
            mudanca["status"] = entrada["status"]
        col_processos.update_one({"_id": doc["_id"]}, {"$set": mudanca})
        # a Oportunidade ligada (se houver) também precisa saber -- é a mesma
        # sincronia que o PATCH da tela já dispara sozinho a cada escrita em
        # col_processos; esta ferramenta escrevia direto no Mongo por fora
        # dela, então o Sinki mudando status/campos aqui deixava a Oportunidade
        # do Painel Gerencial desatualizada (nome/valor/status defasados) sem
        # nenhum aviso.
        doc.setdefault("analise", {}).update(campos)
        if entrada.get("status"):
            doc["status"] = entrada["status"]
        _sync_oportunidade_do_processo(doc)
        quais = ", ".join(list(campos)[:6]) + ("…" if len(campos) > 6 else "")
        return ({"ok": True, "campos_gravados": list(campos)},
                f"Preencheu {len(campos)} campo(s) em “{doc.get('nome')}”: {quais}")

    if nome == "marcar_checklist":
        doc = _sinki_achar_processo(entrada.get("processo", ""))
        if not doc or isinstance(doc, list):
            return {"erro": "Processo não encontrado ou ambíguo."}, None
        marcar = entrada.get("marcar", True)
        grupos = (doc.get("schemaCustom") or {}).get("checklist") or []
        checklist = dict(doc.get("checklist") or {})
        casados = []
        for gi, grupo in enumerate(grupos):
            for ii, item in enumerate(grupo.get("items", [])):
                texto = _norm(item.get("texto", ""))
                for procurado in entrada.get("itens", []):
                    if _norm(procurado) in texto:
                        chave = f"{gi}-{ii}"
                        checklist[chave] = {"feito": marcar}
                        casados.append(item.get("texto", ""))
                        break
        if not casados:
            return {"erro": "Nenhum item do checklist bate com esses textos."}, None
        col_processos.update_one({"_id": doc["_id"]}, {"$set": {
            "checklist": checklist, "atualizadoEm": _agora_ms(),
            "versao": (doc.get("versao") or 1) + 1, "atualizadoPor": "Sinki"}})
        verbo = "Marcou" if marcar else "Desmarcou"
        return ({"ok": True, "itens": casados},
                f"{verbo} {len(casados)} item(ns) do checklist de “{doc.get('nome')}”")

    if nome == "criar_processo":
        documento = entrada.get("documento") or {}
        if not isinstance(documento, dict) or not documento.get("nome"):
            return {"erro": "O documento precisa ser um objeto com pelo menos 'nome'."}, None
        documento.setdefault("origem", "sinki")
        if modelo_usado:
            documento["_iaModel"] = modelo_usado
        try:
            criado = _preparar_e_inserir_processo(dict(documento))
        except DuplicateKeyError:
            return {"erro": "Já existe processo com esse id."}, None
        return ({"ok": True, "id": criado["_id"], "nome": criado.get("nome")},
                f"Cadastrou o processo “{criado.get('nome')}” no Painel")

    if nome == "executar_varredura_sharepoint":
        if not (MONTADOR_TENANT_ID and MONTADOR_CLIENT_ID and MONTADOR_CLIENT_SECRET):
            return {"erro": "SharePoint não configurado neste servidor."}, None
        try:
            atual = escanear_biblioteca({"MODO_LOCAL": False, "TENANT_ID": MONTADOR_TENANT_ID,
                                         "CLIENT_ID": MONTADOR_CLIENT_ID,
                                         "CLIENT_SECRET": MONTADOR_CLIENT_SECRET})
        except Exception as e:
            return {"erro": f"Falha ao varrer o SharePoint: {e}"}, None
        anterior_doc = col_snapshots.find_one(sort=[("criadoEm", DESCENDING)])
        anterior = anterior_doc["dados"] if anterior_doc else None
        data_anterior = _fmt_data_ms(anterior_doc["criadoEm"]) if anterior_doc else None
        titulo, conteudo, novos = _gerar_relatorio_diario(atual, anterior, data_anterior)
        col_snapshots.insert_one({"_id": uuid.uuid4().hex, "dados": atual, "criadoEm": _agora_ms()})
        # o Sinki também varre, e antes isso podia engolir os pendentes de uma
        # varredura anterior feita pela tela — a fila é a mesma para os dois
        _registrar_pendentes(novos)
        col_relatorios.insert_one({"_id": uuid.uuid4().hex, "titulo": titulo, "conteudo": conteudo,
                                   "novos": novos, "autor": "Sinki", "criadoEm": _agora_ms()})
        pendentes = _pendentes_abertos()
        return ({"ok": True, "relatorio": conteudo, "processos_novos": pendentes},
                f"Varreu o SharePoint ({len(novos)} novo(s) nesta varredura, "
                f"{len(pendentes)} aguardando análise no total)")

    return {"erro": f"Ferramenta desconhecida: {nome}"}, None


def _mensagens_da_conversa(conversa: dict) -> list:
    """Remonta o histórico no formato da API, relendo do disco os arquivos que
    foram anexados em cada turno (a API não guarda estado entre chamadas)."""
    pasta = SINKI_DIR / conversa["_id"]
    mensagens = []
    for m in conversa.get("mensagens", []):
        if m.get("papel") == "assistant":
            mensagens.append({"role": "assistant", "content": m.get("texto") or ""})
            continue
        content = []
        for a in m.get("arquivos", []):
            caminho = pasta / a["arquivo"]
            if not caminho.is_file():
                continue
            bloco = _bloco_de_arquivo(a["nome"], caminho.read_bytes(), a.get("content_type", ""))
            if bloco:
                content.append(bloco)
        content.append({"type": "text", "text": m.get("texto") or "(sem texto)"})
        mensagens.append({"role": "user", "content": content})
    return mensagens


@app.route("/api/sinki/prompt", methods=["GET"])
def sinki_prompt():
    """Prompt do Sinki em texto puro — usado pelo botão 'copiar prompt' do
    Painel, pra existir uma única fonte de verdade (antes o texto vivia
    duplicado no index.html e saía de sincronia com o arquivo)."""
    return jsonify({"prompt": PROMPT_SINKI})


@app.route("/api/sinki/conversas", methods=["GET"])
def sinki_listar_conversas():
    docs = col_sinki.find({}, {"titulo": 1, "criadoEm": 1, "atualizadoEm": 1}).sort("atualizadoEm", DESCENDING)
    return jsonify({"conversas": [_sem_id_mongo(d) for d in docs]})


@app.route("/api/sinki/conversas/<cid>", methods=["GET"])
def sinki_obter_conversa(cid):
    doc = col_sinki.find_one({"_id": cid})
    if not doc:
        return jsonify({"erro": "Conversa não encontrada"}), 404
    return jsonify(_sem_id_mongo(doc))


@app.route("/api/sinki/conversas/<cid>", methods=["DELETE"])
def sinki_excluir_conversa(cid):
    col_sinki.delete_one({"_id": cid})
    shutil.rmtree(SINKI_DIR / cid, ignore_errors=True)
    return jsonify({"ok": True})


@app.route("/api/sinki/conversar", methods=["POST"])
def sinki_conversar():
    """Uma rodada de conversa com o Sinki. Recebe (multipart) a mensagem nova e
    os arquivos anexados agora; o histórico fica guardado no servidor, então o
    Painel só precisa mandar o id da conversa. Devolve a resposta pronta — sem
    streaming de propósito: o texto sendo remontado aos pedaços atrapalha quem
    usa leitor de tela, que prefere ouvir a resposta inteira de uma vez."""
    if not anthropic_client:
        return jsonify({"erro": "ANTHROPIC_API_KEY não configurada no servidor"}), 503

    mensagem = (request.form.get("mensagem") or "").strip()
    arquivos = request.files.getlist("arquivos")
    if not mensagem and not arquivos:
        return jsonify({"erro": "Escreva uma mensagem ou anexe um arquivo."}), 400

    cid = request.form.get("conversa_id") or ""
    conversa = col_sinki.find_one({"_id": cid}) if cid else None
    if not conversa:
        cid = uuid.uuid4().hex
        conversa = {"_id": cid, "titulo": "", "mensagens": [],
                    "criadoEm": _agora_ms(), "atualizadoEm": _agora_ms()}

    # salva os anexos desta rodada; eles são relidos a cada turno seguinte
    anexados, nao_suportados = [], []
    if arquivos:
        pasta = SINKI_DIR / cid
        pasta.mkdir(parents=True, exist_ok=True)
        for arquivo in arquivos:
            if not arquivo.filename:
                continue
            dados = arquivo.read()
            if _bloco_de_arquivo(arquivo.filename, dados, arquivo.content_type or "") is None:
                nao_suportados.append(arquivo.filename)
                continue
            nome_disco = uuid.uuid4().hex + "__" + secure_filename(arquivo.filename)
            (pasta / nome_disco).write_bytes(dados)
            anexados.append({"nome": arquivo.filename, "arquivo": nome_disco,
                             "content_type": arquivo.content_type or "", "tamanho": len(dados)})

    if nao_suportados and not anexados and not mensagem:
        return jsonify({"erro": "Nenhum dos arquivos pode ser lido pela IA: "
                                + ", ".join(nao_suportados)
                                + ". Envie PDF, imagem ou texto."}), 400

    conversa.setdefault("mensagens", []).append({
        "papel": "user", "texto": mensagem, "arquivos": anexados, "em": _agora_ms()})

    total_anexos = sum(a.get("tamanho", 0)
                       for m in conversa["mensagens"] for a in m.get("arquivos", []))
    if total_anexos > MAX_PDF_TOTAL_MB * 1024 * 1024:
        return jsonify({"erro": f"Os anexos desta conversa somam mais de {MAX_PDF_TOTAL_MB} MB. "
                                f"Comece uma conversa nova para continuar."}), 400

    modelo = request.form.get("model")
    modelo_usado = modelo if modelo in MODELOS_IA_PERMITIDOS else ANTHROPIC_MODEL
    esforco = request.form.get("effort")
    esforco_usado = esforco if esforco in ESFORCOS_IA_PERMITIDOS else ESFORCO_PADRAO_INTERATIVO
    kwargs = {"output_config": {"effort": esforco_usado}}

    # laço de ferramentas: o Sinki pode consultar e mexer no Painel várias vezes
    # antes de responder. O teto de rodadas evita que um pedido mal formulado
    # vire um vaivém sem fim segurando a requisição.
    mensagens = _mensagens_da_conversa(conversa)
    acoes, entrada_total, saida_total = [], 0, 0
    resposta = None
    try:
        for _ in range(SINKI_MAX_RODADAS):
            with anthropic_client.messages.stream(
                model=modelo_usado,
                max_tokens=32000,
                system=[{"type": "text", "text": PROMPT_SINKI, "cache_control": {"type": "ephemeral"}}],
                thinking={"type": "adaptive"},
                tools=SINKI_FERRAMENTAS,
                messages=mensagens,
                **kwargs,
            ) as stream:
                resposta = stream.get_final_message()

            u = resposta.usage
            entrada_total += ((getattr(u, "input_tokens", 0) or 0)
                              + (getattr(u, "cache_creation_input_tokens", 0) or 0)
                              + (getattr(u, "cache_read_input_tokens", 0) or 0))
            saida_total += getattr(u, "output_tokens", 0) or 0

            if resposta.stop_reason != "tool_use":
                break

            # o turno do assistente volta inteiro (inclui raciocínio e as chamadas)
            mensagens.append({"role": "assistant", "content": resposta.content})
            resultados = []
            for bloco in resposta.content:
                if bloco.type != "tool_use":
                    continue
                try:
                    saida, acao = _sinki_rodar_ferramenta(bloco.name, bloco.input or {}, modelo_usado)
                    erro = False
                except Exception as e:
                    saida, acao, erro = {"erro": str(e)}, None, True
                if acao:
                    acoes.append(acao)
                resultados.append({"type": "tool_result", "tool_use_id": bloco.id,
                                   "content": json.dumps(saida, ensure_ascii=False, default=str),
                                   "is_error": erro})
            mensagens.append({"role": "user", "content": resultados})
    except anthropic.APIStatusError as e:
        return jsonify({"erro": _erro_api_legivel(e)}), 502

    texto = "".join(b.text for b in (resposta.content if resposta else []) if b.type == "text").strip()
    if not texto:
        texto = "(o Sinki não devolveu texto desta vez — tente reformular a pergunta)"
    if nao_suportados:
        texto += ("\n\nObservação: não consegui ler " + ", ".join(nao_suportados)
                  + ". Envie em PDF, imagem ou texto.")

    conversa["mensagens"].append({"papel": "assistant", "texto": texto,
                                  "acoes": acoes, "em": _agora_ms()})
    if not conversa.get("titulo"):
        base = mensagem or (anexados[0]["nome"] if anexados else "Conversa")
        conversa["titulo"] = base[:60] + ("…" if len(base) > 60 else "")
    conversa["atualizadoEm"] = _agora_ms()
    col_sinki.replace_one({"_id": cid}, conversa, upsert=True)

    uso = {"model": modelo_usado, "entrada": entrada_total, "saida": saida_total}
    _registrar_gasto(modelo_usado, uso, processo_nome="Sinki: " + conversa["titulo"],
                     origem="conversa com o Sinki", esforco=esforco_usado)

    return jsonify({"conversa_id": cid, "titulo": conversa["titulo"], "resposta": texto,
                    "acoes": acoes, "anexados": [a["nome"] for a in anexados]})


# ──────────────────────────────────────────────────────────────────
# Verificação de documentação de empresa CONCORRENTE (por processo)
# ──────────────────────────────────────────────────────────────────
# Guardado numa pasta própria e num campo próprio do processo (doc["concorrentes"],
# nunca dentro de "analise"/"exigencias") de propósito: são documentos de uma
# OUTRA empresa, não podem se misturar com os dados/documentos da SINAPE.
CONCORRENTES_DIR = UPLOAD_DIR / "concorrentes"


@app.route("/api/processos/<pid>/concorrentes", methods=["GET"])
def listar_concorrentes(pid):
    doc = col_processos.find_one({"_id": pid}, {"concorrentes": 1})
    if not doc:
        return jsonify({"erro": "Processo não encontrado"}), 404
    return jsonify({"concorrentes": doc.get("concorrentes") or []})


@app.route("/api/processos/<pid>/concorrentes", methods=["POST"])
def verificar_concorrente(pid):
    """Confere a documentação de uma empresa concorrente contra as exigências
    JÁ extraídas deste processo (o 'gabarito' vindo da análise do edital) -
    não relê o edital do zero pra cada concorrente, só compara contra o que
    já está cadastrado. Resultado fica em doc['concorrentes'], separado de
    'analise'/'exigencias' (que são da SINAPE)."""
    if not anthropic_client:
        return jsonify({"erro": "ANTHROPIC_API_KEY não configurada no servidor"}), 503

    doc = col_processos.find_one({"_id": pid})
    if not doc:
        return jsonify({"erro": "Processo não encontrado"}), 404

    exigencias = doc.get("exigencias") or []
    if not exigencias:
        return jsonify({"erro": "Este processo ainda não tem exigências extraídas do edital "
                                "(aba Exigências vazia) — não há gabarito pra comparar o "
                                "concorrente. Rode a análise do edital primeiro."}), 400

    empresa_informada = (request.form.get("empresa") or "").strip()
    arquivos = request.files.getlist("arquivos")
    if not arquivos:
        return jsonify({"erro": "Envie ao menos um arquivo da documentação do concorrente."}), 400

    pdfs, nao_suportados = [], []
    total_bytes = 0
    for arquivo in arquivos:
        if not arquivo.filename:
            continue
        dados = arquivo.read()
        total_bytes += len(dados)
        if total_bytes > MAX_PDF_TOTAL_MB * 1024 * 1024:
            return jsonify({"erro": f"Total dos arquivos excede {MAX_PDF_TOTAL_MB} MB"}), 400
        if _bloco_de_arquivo(arquivo.filename, dados, arquivo.content_type or "") is None:
            nao_suportados.append(arquivo.filename)
            continue
        pdfs.append((arquivo.filename, dados, arquivo.content_type or ""))

    if not pdfs:
        return jsonify({"erro": "Nenhum dos arquivos pode ser lido pela IA: "
                                + ", ".join(nao_suportados) + ". Envie PDF, imagem ou texto."}), 400

    gabarito = [{"ref": e.get("ref", ""), "categoria": e.get("categoria", ""),
                 "descricao": e.get("descricao", ""), "obrigatorio": e.get("obrigatorio", True)}
                for e in exigencias]

    content = [_bloco_de_arquivo(nome, dados, ct) for nome, dados, ct in pdfs]
    content.append({"type": "text", "text": PEDIDO_VERIFICAR_CONCORRENTE.format(
        gabarito=json.dumps(gabarito, ensure_ascii=False, indent=2))})

    modelo = request.form.get("model")
    modelo_usado = modelo if modelo in MODELOS_IA_PERMITIDOS else ANTHROPIC_MODEL
    esforco = request.form.get("effort")
    esforco_usado = esforco if esforco in ESFORCOS_IA_PERMITIDOS else ESFORCO_PADRAO_INTERATIVO
    kwargs = {"output_config": {"effort": esforco_usado}}

    try:
        with anthropic_client.messages.stream(
            model=modelo_usado,
            max_tokens=32000,
            system=[{"type": "text", "text": PROMPT_SINKI, "cache_control": {"type": "ephemeral"}}],
            thinking={"type": "adaptive"},
            messages=[{"role": "user", "content": content}],
            **kwargs,
        ) as stream:
            resposta = stream.get_final_message()
    except anthropic.APIStatusError as e:
        return jsonify({"erro": _erro_api_legivel(e)}), 502

    texto = "".join(b.text for b in resposta.content if b.type == "text").strip()
    texto = re.sub(r"^```(?:json)?\s*|\s*```$", "", texto.strip())
    try:
        resultado = json.loads(texto)
    except json.JSONDecodeError:
        inicio, fim = texto.find("{"), texto.rfind("}")
        if inicio == -1 or fim <= inicio:
            return jsonify({"erro": "A IA não devolveu um JSON válido para esta verificação."}), 502
        try:
            resultado = json.loads(texto[inicio:fim + 1])
        except json.JSONDecodeError:
            return jsonify({"erro": "A IA não devolveu um JSON válido para esta verificação."}), 502

    cid = uuid.uuid4().hex
    pasta = CONCORRENTES_DIR / pid / cid
    pasta.mkdir(parents=True, exist_ok=True)
    arquivos_salvos = []
    for nome, dados, ct in pdfs:
        nome_disco = uuid.uuid4().hex + "__" + secure_filename(nome)
        (pasta / nome_disco).write_bytes(dados)
        arquivos_salvos.append({"nome": nome, "arquivo": nome_disco})

    registro = {
        "_id": cid,
        "empresa": empresa_informada or resultado.get("empresa_concorrente") or "(empresa não identificada)",
        "resumo": resultado.get("resumo", ""),
        "itens": resultado.get("itens", []),
        "arquivos": arquivos_salvos,
        "modelo": modelo_usado,
        "criadoEm": _agora_ms(),
    }
    col_processos.update_one({"_id": pid}, {"$push": {"concorrentes": registro}})

    u = resposta.usage
    uso = {"model": modelo_usado,
           "entrada": (getattr(u, "input_tokens", 0) or 0)
                      + (getattr(u, "cache_creation_input_tokens", 0) or 0)
                      + (getattr(u, "cache_read_input_tokens", 0) or 0),
           "saida": getattr(u, "output_tokens", 0) or 0}
    _registrar_gasto(modelo_usado, uso, processo_id=pid, processo_nome=doc.get("nome", ""),
                     origem="verificação de concorrente", esforco=esforco_usado)

    return jsonify(registro), 201


@app.route("/api/processos/<pid>/concorrentes/<cid>", methods=["DELETE"])
def excluir_concorrente(pid, cid):
    doc = col_processos.find_one({"_id": pid}, {"concorrentes": 1})
    if not doc:
        return jsonify({"erro": "Processo não encontrado"}), 404
    col_processos.update_one({"_id": pid}, {"$pull": {"concorrentes": {"_id": cid}}})
    shutil.rmtree(CONCORRENTES_DIR / pid / cid, ignore_errors=True)
    return jsonify({"ok": True})


# ──────────────────────────────────────────────────────────────────
# comercial — painel de oportunidades, equipe, meta e indicadores
# ──────────────────────────────────────────────────────────────────
# Documento inteiro, sem schema rígido — mesma filosofia de col_processos
# (comentário lá em cima): cada oportunidade tem ~40 campos e evita migração
# a cada campo novo que a área comercial decidir acompanhar. Quem calcula
# os indicadores (ROI, pipeline, eficácia...) é o front, em cima da lista
# crua; aqui só se guarda e devolve.
_META_ID = "atual"


@app.route("/api/comercial/oportunidades", methods=["GET"])
def listar_oportunidades():
    docs = col_comercial_oportunidades.find().sort("data", DESCENDING)
    return jsonify({"oportunidades": [_sem_id_mongo(d) for d in docs]})


@app.route("/api/comercial/oportunidades", methods=["POST"])
def criar_oportunidade():
    corpo = request.get_json(silent=True)
    if not isinstance(corpo, dict):
        return jsonify({"erro": "Corpo deve ser um objeto JSON"}), 400
    doc = dict(corpo)
    doc["_id"] = uuid.uuid4().hex
    col_comercial_oportunidades.insert_one(doc)
    return jsonify(_sem_id_mongo(doc)), 201


@app.route("/api/comercial/oportunidades/<oid>", methods=["PUT"])
def salvar_oportunidade(oid):
    corpo = request.get_json(silent=True)
    if not isinstance(corpo, dict):
        return jsonify({"erro": "Corpo deve ser um objeto JSON"}), 400
    doc = dict(corpo)
    doc.pop("id", None)
    doc["_id"] = oid
    # substitui o documento inteiro — sem controle de versão de propósito: é
    # tabela editada campo a campo (ex.: margem no ROI), não um formulário
    # longo em edição simultânea, então o risco de conflito não paga a
    # complexidade de seVersao que col_processos usa
    r = col_comercial_oportunidades.replace_one({"_id": oid}, doc, upsert=False)
    if not r.matched_count:
        return jsonify({"erro": "Oportunidade não encontrada"}), 404
    return jsonify(_sem_id_mongo(doc))


@app.route("/api/comercial/oportunidades/<oid>", methods=["DELETE"])
def excluir_oportunidade(oid):
    r = col_comercial_oportunidades.delete_one({"_id": oid})
    if not r.deleted_count:
        return jsonify({"erro": "Oportunidade não encontrada"}), 404
    return jsonify({"ok": True})


@app.route("/api/comercial/oportunidades/<oid>/promover", methods=["POST"])
def promover_oportunidade(oid):
    """Caminho inverso de _sync_oportunidade_do_processo: cria um processo na
    Fase 1 do DATA SIN a partir de uma Oportunidade que nasceu direto no
    Painel Gerencial (sem processo por trás) e liga os dois pelo processoId —
    dali em diante, editar o processo atualiza esta MESMA Oportunidade
    sozinho, como já acontece com quem nasce do lado do processo."""
    oport = col_comercial_oportunidades.find_one({"_id": oid})
    if not oport:
        return jsonify({"erro": "Oportunidade não encontrada"}), 404
    if oport.get("processoId") and col_processos.find_one({"_id": oport["processoId"]}):
        # 400, não 409: o front trata status 409 genericamente como conflito de
        # versão otimista (usado no PATCH de processos) e jogaria fora esta
        # mensagem específica, mostrando só "conflito" pro usuário
        return jsonify({"erro": "Esta oportunidade já está ligada a um processo"}), 400

    doc = {
        "nome": oport.get("objeto") or oport.get("cliente") or "Processo sem nome",
        "type": "privado" if oport.get("segmento") == "Privado" else "publico",
        "status": "em_analise",
        "origem": "comercial",
        "analise": {
            "geral_orgao": oport.get("cliente") or "",
            "geral_objeto": oport.get("objeto") or "",
            "geral_numero": oport.get("numProposta") or "",
            "geral_valor": (f"R$ {oport['valorLicitado']:.2f}".replace(".", ",")
                            if oport.get("valorLicitado") else ""),
        },
    }
    # criar_oportunidade=False: a Oportunidade de origem já existe (é esta
    # aqui) — sem isto, _preparar_e_inserir_processo criaria uma segunda,
    # deixando a original órfã e duplicando a linha no Painel Gerencial
    doc = _preparar_e_inserir_processo(doc, criar_oportunidade=False)

    oport["processoId"] = doc["_id"]
    col_comercial_oportunidades.replace_one({"_id": oid}, oport)

    return jsonify(_sem_id_mongo(doc)), 201


@app.route("/api/comercial/equipe", methods=["GET"])
def listar_equipe_comercial():
    docs = col_comercial_equipe.find().sort("nome", ASCENDING)
    return jsonify({"equipe": [_sem_id_mongo(d) for d in docs]})


@app.route("/api/comercial/equipe", methods=["POST"])
def criar_pessoa_equipe():
    corpo = request.get_json(silent=True)
    if not isinstance(corpo, dict):
        return jsonify({"erro": "Corpo deve ser um objeto JSON"}), 400
    doc = dict(corpo)
    doc["_id"] = uuid.uuid4().hex
    col_comercial_equipe.insert_one(doc)
    return jsonify(_sem_id_mongo(doc)), 201


@app.route("/api/comercial/equipe/<pid>", methods=["PUT"])
def salvar_pessoa_equipe(pid):
    corpo = request.get_json(silent=True)
    if not isinstance(corpo, dict):
        return jsonify({"erro": "Corpo deve ser um objeto JSON"}), 400
    doc = dict(corpo)
    doc.pop("id", None)
    doc["_id"] = pid
    r = col_comercial_equipe.replace_one({"_id": pid}, doc, upsert=False)
    if not r.matched_count:
        return jsonify({"erro": "Pessoa não encontrada"}), 404
    return jsonify(_sem_id_mongo(doc))


@app.route("/api/comercial/equipe/<pid>", methods=["DELETE"])
def excluir_pessoa_equipe(pid):
    r = col_comercial_equipe.delete_one({"_id": pid})
    if not r.deleted_count:
        return jsonify({"erro": "Pessoa não encontrada"}), 404
    return jsonify({"ok": True})


@app.route("/api/comercial/meta", methods=["GET"])
def obter_meta_comercial():
    doc = col_comercial_meta.find_one({"_id": _META_ID})
    if not doc:
        return jsonify({"ano": date.today().year, "metaAnual": 0, "valorCarteiraInicial": 0})
    return jsonify(_sem_id_mongo(doc))


@app.route("/api/comercial/meta", methods=["PUT"])
def salvar_meta_comercial():
    corpo = request.get_json(silent=True)
    if not isinstance(corpo, dict):
        return jsonify({"erro": "Corpo deve ser um objeto JSON"}), 400
    doc = {
        "_id": _META_ID,
        "ano": int(corpo.get("ano") or date.today().year),
        "metaAnual": float(corpo.get("metaAnual") or 0),
        "valorCarteiraInicial": float(corpo.get("valorCarteiraInicial") or 0),
    }
    col_comercial_meta.replace_one({"_id": _META_ID}, doc, upsert=True)
    return jsonify(_sem_id_mongo(doc))


@app.route("/api/comercial/timesheet", methods=["GET"])
def listar_timesheet():
    docs = col_comercial_timesheet.find().sort("_id", ASCENDING)
    return jsonify({"timesheet": [{"mes": d["_id"], "total": d.get("total") or 0} for d in docs]})


@app.route("/api/comercial/timesheet/<mes>", methods=["PUT"])
def salvar_timesheet_mes(mes):
    if not re.match(r"^\d{4}-\d{2}$", mes):
        return jsonify({"erro": "Mês deve estar no formato AAAA-MM"}), 400
    corpo = request.get_json(silent=True) or {}
    total = float(corpo.get("total") or 0)
    col_comercial_timesheet.replace_one({"_id": mes}, {"_id": mes, "total": total}, upsert=True)
    return jsonify({"mes": mes, "total": total})


@app.route("/api/comercial/timesheet/<mes>", methods=["DELETE"])
def excluir_timesheet_mes(mes):
    r = col_comercial_timesheet.delete_one({"_id": mes})
    if not r.deleted_count:
        return jsonify({"erro": "Mês não encontrado"}), 404
    return jsonify({"ok": True})


@app.route("/api/comercial/atas", methods=["GET"])
def listar_atas_comercial():
    docs = col_comercial_atas.find().sort("data", DESCENDING)
    return jsonify({"atas": [_sem_id_mongo(d) for d in docs]})


@app.route("/api/comercial/atas", methods=["POST"])
def criar_ata_comercial():
    corpo = request.get_json(silent=True)
    if not isinstance(corpo, dict):
        return jsonify({"erro": "Corpo deve ser um objeto JSON"}), 400
    doc = dict(corpo)
    if not isinstance(doc.get("assuntos"), list):
        doc["assuntos"] = []
    doc["_id"] = uuid.uuid4().hex
    col_comercial_atas.insert_one(doc)
    return jsonify(_sem_id_mongo(doc)), 201


@app.route("/api/comercial/atas/<aid>", methods=["PUT"])
def salvar_ata_comercial(aid):
    corpo = request.get_json(silent=True)
    if not isinstance(corpo, dict):
        return jsonify({"erro": "Corpo deve ser um objeto JSON"}), 400
    doc = dict(corpo)
    doc.pop("id", None)
    if not isinstance(doc.get("assuntos"), list):
        doc["assuntos"] = []
    doc["_id"] = aid
    r = col_comercial_atas.replace_one({"_id": aid}, doc, upsert=False)
    if not r.matched_count:
        return jsonify({"erro": "Ata não encontrada"}), 404
    return jsonify(_sem_id_mongo(doc))


@app.route("/api/comercial/atas/<aid>", methods=["DELETE"])
def excluir_ata_comercial(aid):
    r = col_comercial_atas.delete_one({"_id": aid})
    if not r.deleted_count:
        return jsonify({"erro": "Ata não encontrada"}), 404
    return jsonify({"ok": True})


def _capturar_estado_comercial_atual() -> dict:
    """Tira uma 'foto' de tudo que está no módulo Comercial agora, no mesmo
    formato que /api/comercial/importar aceita de volta — usada pra guardar
    o botão de segurança 'Restaurar para o backup anterior' antes de aplicar
    um backup novo por cima."""
    return {
        "oportunidades": [_sem_id_mongo(d) for d in col_comercial_oportunidades.find()],
        "equipe": [_sem_id_mongo(d) for d in col_comercial_equipe.find()],
        "meta": _sem_id_mongo(col_comercial_meta.find_one({"_id": _META_ID})
                               or {"_id": _META_ID, "ano": date.today().year,
                                   "metaAnual": 0, "valorCarteiraInicial": 0}),
        "timesheet": [{"mes": d["_id"], "total": d.get("total") or 0} for d in col_comercial_timesheet.find()],
        "atas": [_sem_id_mongo(d) for d in col_comercial_atas.find()],
    }


def _aplicar_backup_comercial(corpo: dict) -> dict:
    """Substitui TODO o módulo Comercial (oportunidades/equipe/meta/timesheet/
    atas) pelo conteúdo de 'corpo' — mesma lógica usada tanto por
    /api/comercial/importar (arquivo escolhido pela pessoa) quanto por
    /api/comercial/restaurar-anterior (a foto guardada automaticamente antes
    do último import)."""
    oportunidades = corpo.get("oportunidades") or []
    equipe = corpo.get("equipe") or []
    meta = corpo.get("meta") or {}
    timesheet = corpo.get("timesheet") or []

    col_comercial_oportunidades.delete_many({})
    if oportunidades:
        docs = []
        for o in oportunidades:
            d = dict(o)
            # preserva o id original quando existe (mantém rastreabilidade
            # de quem editou o quê antes da importação); gera um novo só se
            # faltar ou vier duplicado
            oid = str(d.pop("id", None) or d.pop("_id", None) or uuid.uuid4().hex)
            d["_id"] = oid
            docs.append(d)
        vistos = set()
        for d in docs:
            if d["_id"] in vistos:
                d["_id"] = uuid.uuid4().hex
            vistos.add(d["_id"])
        col_comercial_oportunidades.insert_many(docs)

    col_comercial_equipe.delete_many({})
    if equipe:
        docs = []
        for p in equipe:
            d = dict(p)
            d["_id"] = str(d.pop("id", None) or d.pop("_id", None) or uuid.uuid4().hex)
            docs.append(d)
        vistos = set()
        for d in docs:
            if d["_id"] in vistos:
                d["_id"] = uuid.uuid4().hex
            vistos.add(d["_id"])
        col_comercial_equipe.insert_many(docs)

    meta_doc = {
        "_id": _META_ID,
        "ano": int(meta.get("ano") or date.today().year),
        "metaAnual": float(meta.get("metaAnual") or 0),
        "valorCarteiraInicial": float(meta.get("valorCarteiraInicial") or 0),
    }
    col_comercial_meta.replace_one({"_id": _META_ID}, meta_doc, upsert=True)

    col_comercial_timesheet.delete_many({})
    if timesheet:
        docs = [{"_id": t.get("mes"), "total": float(t.get("total") or 0)}
                for t in timesheet if t.get("mes")]
        if docs:
            col_comercial_timesheet.insert_many(docs)

    # atas é opcional (backups antigos não tinham) — só mexe na coleção
    # quando o campo vem no arquivo, pra não apagar atas já cadastradas
    # ao importar um backup gerado antes dessa área existir
    atas = corpo.get("atas")
    n_atas = 0
    if isinstance(atas, list):
        col_comercial_atas.delete_many({})
        if atas:
            docs = []
            for a in atas:
                d = dict(a)
                d["_id"] = str(d.pop("id", None) or d.pop("_id", None) or uuid.uuid4().hex)
                if not isinstance(d.get("assuntos"), list):
                    d["assuntos"] = []
                docs.append(d)
            vistos = set()
            for d in docs:
                if d["_id"] in vistos:
                    d["_id"] = uuid.uuid4().hex
                vistos.add(d["_id"])
            col_comercial_atas.insert_many(docs)
        n_atas = len(atas)

    return {
        "ok": True,
        "oportunidades": len(oportunidades),
        "equipe": len(equipe),
        "timesheet": len(timesheet),
        "atas": n_atas,
    }


@app.route("/api/comercial/importar", methods=["POST"])
def importar_backup_comercial():
    """Substitui TODO o módulo Comercial pelo conteúdo de um backup — o mesmo
    formato que o painel original já exportava (oportunidades/equipe/meta/
    timesheet). Fica como rota permanente de recuperação, não só migração
    inicial: a equipe já usa esse fluxo de exportar/importar como rede de
    segurança, então mantê-lo dá continuidade a um hábito que já existe."""
    corpo = request.get_json(silent=True)
    if not isinstance(corpo, dict) or not isinstance(corpo.get("oportunidades"), list):
        return jsonify({"erro": "Arquivo não parece ser um backup válido — falta a lista de oportunidades."}), 400

    equipe = corpo.get("equipe") or []
    meta = corpo.get("meta") or {}
    timesheet = corpo.get("timesheet") or []
    if not isinstance(equipe, list) or not isinstance(timesheet, list) or not isinstance(meta, dict):
        return jsonify({"erro": "Arquivo não parece ser um backup válido — equipe/meta/timesheet em formato inesperado."}), 400

    # tira a foto do que está no ar AGORA, antes de sobrescrever — é o que o
    # botão "Restaurar para o backup anterior" devolve se este import novo
    # se revelar errado
    col_comercial_snapshot_anterior.replace_one(
        {"_id": "anterior"},
        dict(_capturar_estado_comercial_atual(), _id="anterior", criadoEm=_agora_ms()),
        upsert=True,
    )
    return jsonify(_aplicar_backup_comercial(corpo))


@app.route("/api/comercial/snapshot-anterior", methods=["GET"])
def obter_snapshot_anterior():
    """Diz se existe uma foto de 'antes do último import' pra restaurar, e de
    quando é — o front usa isso pra mostrar (ou não) o botão de segurança."""
    doc = col_comercial_snapshot_anterior.find_one({"_id": "anterior"})
    if not doc:
        return jsonify({"existe": False})
    return jsonify({"existe": True, "criadoEm": doc.get("criadoEm")})


@app.route("/api/comercial/restaurar-anterior", methods=["POST"])
def restaurar_backup_anterior():
    """Botão de segurança: devolve o módulo Comercial pro estado de
    imediatamente antes do último import. A troca é uma TESTE (swap), não uma
    via de mão única — o estado atual (o import que a pessoa achou que
    estava errado) vira a nova foto guardada, então apertar o botão de novo
    desfaz a restauração e volta pro que tinha antes de restaurar."""
    snapshot = col_comercial_snapshot_anterior.find_one({"_id": "anterior"})
    if not snapshot:
        return jsonify({"erro": "Não há nenhum backup anterior guardado pra restaurar."}), 404

    estado_atual = _capturar_estado_comercial_atual()
    resultado = _aplicar_backup_comercial(snapshot)
    col_comercial_snapshot_anterior.replace_one(
        {"_id": "anterior"},
        dict(estado_atual, _id="anterior", criadoEm=_agora_ms()),
        upsert=True,
    )
    return jsonify(resultado)


@app.route("/api/gastos", methods=["GET"])
def painel_gastos():
    """Contador de gastos de IA: total geral (tokens + custo) e o detalhamento
    por processo/análise, do mais recente para o mais antigo. Alimenta o
    Painel de Gastos do front-end."""
    registros = list(col_gastos.find(sort=[("criadoEm", DESCENDING)]))
    total_ent = sum(r.get("tokens_entrada", 0) for r in registros)
    total_sai = sum(r.get("tokens_saida", 0) for r in registros)
    total_usd = round(sum(r.get("custo_usd", 0.0) for r in registros), 4)
    itens = [{
        "processo_nome": r.get("processo_nome") or "(sem nome)",
        "model": r.get("model", ""),
        "esforco": r.get("esforco", ""),
        "origem": r.get("origem", ""),
        "tokens_entrada": r.get("tokens_entrada", 0),
        "tokens_saida": r.get("tokens_saida", 0),
        "custo_usd": round(r.get("custo_usd", 0.0), 4),
        "criadoEm": r.get("criadoEm"),
    } for r in registros]

    # Comparativo por modelo + esforço: é o que responde "compensa baixar o
    # esforço?" e "Opus no médio sai mais barato que Sonnet no máximo?".
    # A média por chamada importa mais que o total, porque uma combinação usada
    # 2 vezes e outra usada 50 não se comparam pelo total gasto.
    # Agrupa por TIPO DE TRABALHO antes de modelo+esforço. Sem isso a conta
    # engana: ler um edital de 200 páginas custa dez vezes uma pergunta ao
    # Sinki, então um modelo usado só em edital pareceria caríssimo ao lado de
    # outro usado só em conversa — sem que nenhum dos dois seja pior.
    combos = {}
    for r in registros:
        chave = (r.get("origem", "") or "(sem origem)", r.get("model", ""), r.get("esforco", ""))
        c = combos.setdefault(chave, {"chamadas": 0, "entrada": 0, "saida": 0, "usd": 0.0})
        c["chamadas"] += 1
        c["entrada"] += r.get("tokens_entrada", 0)
        c["saida"] += r.get("tokens_saida", 0)
        c["usd"] += r.get("custo_usd", 0.0)

    # ── qualidade: quanto a equipe teve que corrigir do que a IA preencheu ──
    # Não dá pra julgar a qualidade sozinho, mas dá pra usar algo melhor que
    # opinião: o trabalho da própria equipe. Todo processo nascido de IA guarda
    # o que ela respondeu (_analiseOriginalIA), e cada campo que a equipe mudou
    # depois vira um registro de correção. A proporção entre os dois é o sinal
    # mais honesto que temos de "esse modelo/esforço acertou mais".
    correcoes_por_processo = {}
    for corr in col_correcoes.find({}, {"processo_id": 1}):
        pid_c = corr.get("processo_id")
        correcoes_por_processo[pid_c] = correcoes_por_processo.get(pid_c, 0) + 1

    qualidade = {}
    for d in col_processos.find({"_iaModel": {"$exists": True}},
                                {"_iaModel": 1, "_iaEsforco": 1, "_analiseOriginalIA": 1}):
        base = d.get("_analiseOriginalIA") or {}
        preenchidos = base.get("_autoFilledKeys")
        if not isinstance(preenchidos, list) or not preenchidos:
            # sem a lista que a IA declara, conta os campos que ela deixou com valor
            preenchidos = [k for k, v in base.items()
                           if not k.startswith("_") and v not in ("", None, [], {})]
        if not preenchidos:
            continue
        chave = (d.get("_iaModel", ""), d.get("_iaEsforco", ""))
        q = qualidade.setdefault(chave, {"processos": 0, "campos": 0, "corrigidos": 0})
        q["processos"] += 1
        q["campos"] += len(preenchidos)
        q["corrigidos"] += correcoes_por_processo.get(d["_id"], 0)

    def _qualidade_de(modelo, esf):
        q = qualidade.get((modelo, esf))
        if not q or not q["campos"]:
            return None
        return {
            "processos_avaliados": q["processos"],
            "campos_preenchidos": q["campos"],
            "campos_corrigidos": q["corrigidos"],
            "taxa_correcao_pct": round(q["corrigidos"] / q["campos"] * 100, 1),
        }

    comparativo = sorted(
        ({
            "origem": origem,
            "model": modelo,
            "esforco": esf or "(não registrado)",
            "chamadas": c["chamadas"],
            "tokens_entrada_media": round(c["entrada"] / c["chamadas"]),
            "tokens_saida_media": round(c["saida"] / c["chamadas"]),
            "custo_usd_medio": round(c["usd"] / c["chamadas"], 4),
            "custo_usd_total": round(c["usd"], 4),
            "qualidade": _qualidade_de(modelo, esf),
        } for (origem, modelo, esf), c in combos.items()),
        key=lambda x: (x["origem"], x["custo_usd_medio"]),
    )

    return jsonify({
        "total_analises": len(registros),
        "total_tokens_entrada": total_ent,
        "total_tokens_saida": total_sai,
        "total_tokens": total_ent + total_sai,
        "total_usd": total_usd,
        "total_brl_aprox": round(total_usd * USD_PARA_BRL, 2),
        "cotacao_usd_brl": USD_PARA_BRL,
        "comparativo_modelo_esforco": comparativo,
        "itens": itens,
    })


# ──────────────────────────────────────────────────────────────────
# anexos
# ──────────────────────────────────────────────────────────────────
@app.route("/api/processos/<pid>/anexos", methods=["GET"])
def listar_anexos(pid):
    cursor = col_anexos.find(
        {"processo_id": pid},
        {"nome_original": 1, "tamanho": 1, "content_type": 1, "enviado_em": 1, "enviado_por": 1, "secao": 1},
    ).sort("enviado_em", DESCENDING)
    anexos = [_sem_id_mongo(a) for a in cursor]
    return jsonify({"anexos": anexos})


def _guardar_anexo(pid, nome_original, escrever, content_type, enviado_por, secao):
    """Grava o arquivo em disco e o registro no banco. `escrever` recebe o
    caminho de destino — é o que difere o upload do navegador (arquivo.save)
    do arquivo trazido do SharePoint (write_bytes)."""
    anexo_id = uuid.uuid4().hex
    nome_arquivo = anexo_id + "__" + secure_filename(nome_original)
    pasta = UPLOAD_DIR / pid
    pasta.mkdir(parents=True, exist_ok=True)
    destino = pasta / nome_arquivo
    escrever(destino)

    agora = _agora_ms()
    tamanho = destino.stat().st_size
    # só uma planilha por seção: a nova substitui a anterior, inclusive em disco
    if secao:
        antigo = col_anexos.find_one_and_delete({"processo_id": pid, "secao": secao})
        if antigo:
            try:
                (UPLOAD_DIR / pid / antigo["nome_arquivo"]).unlink(missing_ok=True)
            except OSError as e:
                # o registro da planilha antiga já saiu do banco; se o arquivo
                # em si resistir (no Windows, alguém baixando ainda o segura),
                # não vale derrubar o anexo novo por causa de um órfão em disco
                print(f"[anexo] não removi o arquivo da planilha anterior "
                      f"({antigo['nome_arquivo']}): {e!r}", flush=True)
    col_anexos.insert_one({
        "_id": anexo_id,
        "processo_id": pid,
        "nome_original": nome_original,
        "nome_arquivo": nome_arquivo,
        "tamanho": tamanho,
        "content_type": content_type,
        "enviado_em": agora,
        "enviado_por": enviado_por,
        "secao": secao,
    })
    return {
        "id": anexo_id, "nome_original": nome_original, "tamanho": tamanho,
        "content_type": content_type, "enviado_em": agora, "enviado_por": enviado_por,
        "secao": secao,
    }


@app.route("/api/processos/<pid>/anexos", methods=["POST"])
def enviar_anexo(pid):
    if not col_processos.find_one({"_id": pid}, {"_id": 1}):
        return jsonify({"erro": "Processo não encontrado"}), 404

    arquivo = request.files.get("arquivo")
    if not arquivo or not arquivo.filename:
        return jsonify({"erro": "Envie o arquivo no campo 'arquivo'"}), 400

    # "secao" marca o anexo como a planilha real de uma seção específica da
    # Análise Crítica (ex.: "quantitativos", "custos") — só uma por seção;
    # anexos comuns (sem seção) continuam só na aba de Anexos.
    dados = _guardar_anexo(
        pid, arquivo.filename, arquivo.save, arquivo.content_type,
        request.form.get("enviadoPor", ""), request.form.get("secao") or None)
    return jsonify(dados), 201


def _pasta_sharepoint_do_processo(pid, processo):
    """Caminho da pasta do processo relativo à biblioteca 'Documentos'.

    Sai do link já gravado em geral_pasta_sharepoint; se ele não existir,
    procura a pasta pelos dados do processo e grava o que achou, pra próxima
    vez sair direto. Devolve (caminho, erro_json, status) — caminho é None
    quando não deu."""
    if not (MONTADOR_TENANT_ID and MONTADOR_CLIENT_ID and MONTADOR_CLIENT_SECRET):
        return None, {"erro": "SharePoint não configurado neste servidor."}, 503

    analise = processo.get("analise") or {}
    url_pasta = (analise.get("geral_pasta_sharepoint") or "").strip()
    cfg = {"MODO_LOCAL": False, "TENANT_ID": MONTADOR_TENANT_ID,
           "CLIENT_ID": MONTADOR_CLIENT_ID, "CLIENT_SECRET": MONTADOR_CLIENT_SECRET}

    if not url_pasta:
        try:
            achado = localizar_pasta_processo(
                cfg, orgao=analise.get("geral_orgao", ""),
                numero=analise.get("geral_numero", ""),
                objeto=analise.get("geral_objeto", ""),
                nome=processo.get("nome", ""))
        except Exception as e:
            return None, {"erro": f"Falha ao procurar a pasta no SharePoint: {e}"}, 502
        if not achado["encontrado"]:
            proximos = [c["nome"] for c in achado["candidatos"][:5]]
            return None, {
                "erro": "Não consegui identificar sozinho a pasta deste processo no SharePoint. "
                        "Preencha o campo 'Pasta do processo no SharePoint', em Dados Gerais, "
                        "e tente de novo.",
                "candidatos_proximos": proximos,
            }, 404
        url_pasta = f"https://{SITE_HOSTNAME}{SITE_PATH}/Documentos/{achado['caminho']}"
        col_processos.update_one({"_id": pid},
                                 {"$set": {"analise.geral_pasta_sharepoint": url_pasta}})

    try:
        # parse_pasta_sharepoint levanta SystemExit em link torto — que não é
        # exceção comum e derrubaria o worker se subisse
        _host, _site, caminho = parse_pasta_sharepoint(url_pasta)
    except SystemExit as e:
        return None, {"erro": f"O link da pasta deste processo está em formato inesperado: {e}"}, 400
    return caminho, None, 200


@app.route("/api/processos/<pid>/pasta/arquivos", methods=["GET"])
def listar_arquivos_da_pasta_do_processo(pid):
    """Arquivos que existem na pasta DESTE processo no SharePoint.

    Serve pra tela de anexar: quem está no processo da Conasa precisa ver os
    documentos da Conasa, não sair caçando no computador entre as planilhas de
    todos os processos."""
    processo = col_processos.find_one({"_id": pid})
    if not processo:
        return jsonify({"erro": "Processo não encontrado"}), 404

    caminho, erro, status = _pasta_sharepoint_do_processo(pid, processo)
    if erro:
        return jsonify(erro), status
    cfg = {"MODO_LOCAL": False, "TENANT_ID": MONTADOR_TENANT_ID,
           "CLIENT_ID": MONTADOR_CLIENT_ID, "CLIENT_SECRET": MONTADOR_CLIENT_SECRET}
    try:
        arquivos = listar_arquivos_do_processo(cfg, caminho)
    except requests.HTTPError as e:
        if e.response is not None and e.response.status_code == 404:
            return jsonify({"erro": "A pasta deste processo não foi encontrada no SharePoint."}), 404
        return jsonify({"erro": f"Falha ao ler a pasta no SharePoint: {e}"}), 502
    except Exception as e:
        return jsonify({"erro": f"Falha ao ler a pasta no SharePoint: {e}"}), 502
    return jsonify({"caminho_pasta": caminho, "arquivos": arquivos})


@app.route("/api/processos/<pid>/anexos/do-sharepoint", methods=["POST"])
def anexar_da_pasta_do_processo(pid):
    """Anexa ao processo um arquivo que já está na pasta dele no SharePoint,
    sem passar pelo computador de ninguém. Não chama IA: é cópia de arquivo."""
    processo = col_processos.find_one({"_id": pid})
    if not processo:
        return jsonify({"erro": "Processo não encontrado"}), 404

    corpo = request.get_json(silent=True) or {}
    relativo = (corpo.get("caminho_relativo") or "").strip()
    if not relativo:
        return jsonify({"erro": "Informe o caminho_relativo do arquivo."}), 400

    caminho, erro, status = _pasta_sharepoint_do_processo(pid, processo)
    if erro:
        return jsonify(erro), status
    cfg = {"MODO_LOCAL": False, "TENANT_ID": MONTADOR_TENANT_ID,
           "CLIENT_ID": MONTADOR_CLIENT_ID, "CLIENT_SECRET": MONTADOR_CLIENT_SECRET}
    try:
        dados = baixar_arquivo_do_processo(cfg, caminho, relativo)
    except ValueError as e:
        return jsonify({"erro": str(e)}), 400
    except requests.HTTPError as e:
        if e.response is not None and e.response.status_code == 404:
            return jsonify({"erro": "Esse arquivo não está mais na pasta do processo."}), 404
        return jsonify({"erro": f"Falha ao baixar o arquivo do SharePoint: {e}"}), 502
    except Exception as e:
        return jsonify({"erro": f"Falha ao baixar o arquivo do SharePoint: {e}"}), 502

    nome = relativo.replace("\\", "/").rstrip("/").split("/")[-1]
    tipo = mimetypes.guess_type(nome)[0] or "application/octet-stream"
    guardado = _guardar_anexo(pid, nome, lambda destino: destino.write_bytes(dados),
                              tipo, corpo.get("enviadoPor", ""), corpo.get("secao") or None)
    return jsonify(guardado), 201


@app.route("/api/processos/<pid>/anexos/<aid>", methods=["GET"])
def baixar_anexo(pid, aid):
    anexo = col_anexos.find_one({"_id": aid, "processo_id": pid})
    if not anexo:
        return jsonify({"erro": "Anexo não encontrado"}), 404
    caminho = UPLOAD_DIR / pid / anexo["nome_arquivo"]
    if not caminho.is_file():
        return jsonify({"erro": "Arquivo não encontrado em disco"}), 404
    return send_file(caminho, mimetype=anexo["content_type"], as_attachment=True,
                      download_name=anexo["nome_original"])


@app.route("/api/processos/<pid>/anexos/<aid>", methods=["DELETE"])
def excluir_anexo(pid, aid):
    anexo = col_anexos.find_one_and_delete({"_id": aid, "processo_id": pid})
    if not anexo:
        return jsonify({"erro": "Anexo não encontrado"}), 404
    (UPLOAD_DIR / pid / anexo["nome_arquivo"]).unlink(missing_ok=True)
    return jsonify({"ok": True})


@app.errorhandler(json.JSONDecodeError)
def _erro_json(_e):
    return jsonify({"erro": "JSON inválido no corpo da requisição"}), 400


_init_db()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "8080")), debug=False)
