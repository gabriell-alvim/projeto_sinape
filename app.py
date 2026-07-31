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
  GET     /api/processos                     → lista resumida {"processos":[...]}
  POST    /api/processos                     → cria processo (corpo = documento completo)
  GET     /api/processos/<id>                → documento completo
  PUT     /api/processos/<id>                → substitui documento completo
  PATCH   /api/processos/<id>                → mescla {metaPatch, analisePatch, checklistPatch, exigencias, seVersao}
  DELETE  /api/processos/<id>                → remove (e seus anexos)
  GET     /api/processos/<id>/anexos         → lista anexos do processo
  POST    /api/processos/<id>/anexos         → envia um anexo (multipart, campo "arquivo")
  GET     /api/processos/<id>/anexos/<aid>   → baixa o arquivo
  DELETE  /api/processos/<id>/anexos/<aid>   → remove o anexo (registro + arquivo em disco)
  GET     /api/processos/<id>/dossie         → monta o dossiê de habilitação (Montador) e devolve o .zip
  GET     /api/relatorios/mais-recente        → devolve a atualização do dia mais recente publicada (inclui "novos": [{tipo,nome,status,caminho_pasta}])
  POST    /api/relatorios                     → publica uma nova atualização do dia (uso por processo automatizado)
  POST    /api/relatorios/executar-varredura  → varre o SharePoint agora, compara com a varredura anterior e publica o relatório do dia
  POST    /api/processos/analisar-ia          → recebe PDFs (multipart, campo "arquivos"); responde 202 {job_id} e analisa em segundo plano
  POST    /api/processos/analisar-novo        → a partir de {caminho_pasta, tipo, model?, effort?} de um item novo da varredura, baixa os PDFs e responde 202 {job_id}; a análise e a criação do processo correm em segundo plano
  GET     /api/jobs/<id>                      → andamento de uma análise: rodando | concluido (com processo_id ou documento) | erro
  GET     /api/pendentes                      → fila de processos novos aguardando decisão (analisar ou dispensar)
  POST    /api/pendentes                      → põe uma pasta do SharePoint na fila à mão {caminho_pasta, tipo?, nome?}
  POST    /api/pendentes/dispensar            → tira da fila sem analisar {caminho_pasta, autor?, motivo?}
  POST    /api/pendentes/restaurar            → desfaz a dispensa {caminho_pasta}
  GET     /api/gastos                         → contador de gastos de IA (total de tokens e custo em US$/R$) + detalhamento por processo
  GET     /api/correcoes                      → pares (resposta da IA / correção da equipe) — matéria-prima pra treinar um modelo especialista no futuro
  GET     /api/prazos                         → todos os prazos de todos os processos ativos, numa lista só, ordenados do mais urgente pro mais distante
  POST    /api/sinki/conversar                → uma rodada de conversa com o Sinki (multipart: mensagem + arquivos + conversa_id)
  GET     /api/sinki/conversas                → lista as conversas com o Sinki (mais recentes primeiro)
  GET     /api/sinki/conversas/<cid>          → histórico completo de uma conversa
  DELETE  /api/sinki/conversas/<cid>          → apaga a conversa e seus anexos
  GET     /api/sinki/prompt                   → prompt do Sinki em texto (fonte única, usada pelo botão de copiar)
  GET     /api/processos/<id>/concorrentes         → lista as verificações de documentação de concorrente já feitas neste processo
  POST    /api/processos/<id>/concorrentes         → confere a documentação de uma empresa concorrente (multipart: empresa, arquivos) contra as exigências já extraídas do edital
  DELETE  /api/processos/<id>/concorrentes/<cid>   → apaga uma verificação de concorrente e seus arquivos

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
import os
import re
import shutil
import sys
import tempfile
import threading
import time
import traceback
import uuid
from datetime import date, timedelta
from pathlib import Path
from urllib.parse import quote

import anthropic
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
    baixar_pdfs_da_pasta, SITE_HOSTNAME, SITE_PATH,
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
MONGO_URL = os.environ.get("MONGO_URL", "")
MAX_UPLOAD_MB = int(os.environ.get("MAX_UPLOAD_MB", "25"))

ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
ANTHROPIC_MODEL = os.environ.get("ANTHROPIC_MODEL", "claude-opus-5")
MAX_PDF_TOTAL_MB = int(os.environ.get("MAX_PDF_TOTAL_MB", "24"))  # margem p/ limite de 32MB em base64
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


def _init_db():
    col_processos.create_index([("atualizadoEm", DESCENDING)])
    col_anexos.create_index([("processo_id", ASCENDING), ("enviado_em", DESCENDING)])
    col_relatorios.create_index([("criadoEm", DESCENDING)])
    col_snapshots.create_index([("criadoEm", DESCENDING)])
    col_gastos.create_index([("criadoEm", DESCENDING)])
    col_sinki.create_index([("atualizadoEm", DESCENDING)])
    col_correcoes.create_index([("processo_id", ASCENDING)])
    col_correcoes.create_index([("atualizadoEm", DESCENDING)])
    col_pendentes.create_index([("situacao", ASCENDING), ("detectadoEm", ASCENDING)])


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


def _site_auth_enabled():
    return bool(SITE_USER and SITE_PASSWORD)


def _logged_in():
    return session.get("site_auth") is True


def _safe_next_url(val):
    if val and val.startswith("/") and not val.startswith("//"):
        return val
    return "/"


@app.before_request
def _auth():
    if request.method == "OPTIONS":
        return ("", 204)

    if request.path == "/api/health":
        return None

    if request.path in ("/login", "/logout"):
        return None

    if _site_auth_enabled() and not _logged_in():
        if request.path.startswith("/api/"):
            return jsonify({"erro": "Não autenticado — faça login"}), 401
        next_path = request.path
        if request.query_string:
            next_path += "?" + request.query_string.decode("utf-8")
        return redirect("/login?next=" + quote(next_path, safe="/?=&"))

    if request.path.startswith("/api/"):
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
        usuario = request.form.get("usuario", "")
        senha = request.form.get("senha", "")
        if usuario == SITE_USER and senha == SITE_PASSWORD:
            session.permanent = True
            session["site_auth"] = True
            return redirect(_safe_next_url(request.form.get("next")))
        return redirect("/login?erro=1&next=" + quote(request.form.get("next") or "/"))
    return send_from_directory(BASE_DIR, "login.html")


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

    return jsonify({"versao": nova_versao, "atualizadoEm": agora})


@app.route("/api/processos/<pid>", methods=["DELETE"])
def excluir(pid):
    for anexo in col_anexos.find({"processo_id": pid}):
        (UPLOAD_DIR / pid / anexo["nome_arquivo"]).unlink(missing_ok=True)
    col_anexos.delete_many({"processo_id": pid})
    col_processos.delete_one({"_id": pid})
    try:
        (UPLOAD_DIR / pid).rmdir()
    except OSError:
        pass
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
        pdfs = baixar_pdfs_da_pasta(cfg, caminho)
    except requests.HTTPError as e:
        if e.response is not None and e.response.status_code == 404:
            return jsonify({"erro": "Essa pasta não existe no SharePoint. Confira o caminho."}), 404
        return jsonify({"erro": f"Falha ao conferir a pasta no SharePoint: {e}"}), 502
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
    referências da análise ("página 5 do PER") continuem fazendo sentido."""
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

    if total_paginas > PAGINAS_POR_REQUISICAO:
        raise ValueError(
            f"Os documentos somam {total_paginas} páginas e a IA analisa no máximo "
            f"{PAGINAS_POR_REQUISICAO} por vez. Rode a análise com menos arquivos de "
            f"cada vez, deixando de fora os anexos que não afetam a decisão."
        )
    return saida


def _rodar_analise_ia(pdfs: list, model: str | None = None, effort: str | None = None):
    """Manda uma lista de PDFs (nome, bytes) pro Claude com o prompt padrão do
    Painel e devolve (doc, meta) — o JSON de análise pronto pra virar processo
    e os metadados de uso (modelo + tokens de entrada/saída) pro contador de
    gastos. Reaproveitado tanto pelo upload manual (analisar_ia) quanto pela
    análise automática de processos novos detectados na varredura."""
    if not anthropic_client:
        raise RuntimeError("ANTHROPIC_API_KEY não configurada no servidor")

    total_bytes = sum(len(dados) for _, dados in pdfs)
    if total_bytes > MAX_PDF_TOTAL_MB * 1024 * 1024:
        raise ValueError(f"Total dos PDFs excede {MAX_PDF_TOTAL_MB} MB")

    pdfs = _fatiar_pdfs_grandes(pdfs)

    nomes = []
    content = []
    for nome, dados in pdfs:
        nomes.append(nome)
        content.append({
            "type": "document",
            "source": {
                "type": "base64",
                "media_type": "application/pdf",
                "data": base64.standard_b64encode(dados).decode("ascii"),
            },
        })
    content.append({"type": "text", "text": PEDIDO_ANALISE})

    # antes o esforço só ia quando a tela mandava um válido, e sem ele a chamada
    # caía no padrão da API. Agora vai sempre explícito: o valor é o mesmo, mas
    # o registro de gasto passa a saber com que esforço aquele custo foi gasto
    # em vez de gravar em branco.
    esforco_usado = effort if effort in ESFORCOS_IA_PERMITIDOS else ESFORCO_PADRAO_ANALISE
    kwargs = {"output_config": {"effort": esforco_usado}}

    modelo_usado = model if model in MODELOS_IA_PERMITIDOS else ANTHROPIC_MODEL
    # Sem isto, uma análise que estoura o timeout do gunicorn não deixa rastro
    # nenhum: o worker morre esperando a resposta, o registro de gasto nunca
    # roda e ninguém sabe quanto tempo aquilo levou nem se a API foi chamada.
    # Estes dois prints vão pro log do Render e respondem as duas coisas.
    mb = sum(len(d) for _, d in pdfs) / 1024 / 1024
    print(f"[analise] inicio · modelo={modelo_usado} esforco={esforco_usado} "
          f"{len(pdfs)} arquivo(s) {mb:.1f} MB", flush=True)
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
        "model": modelo_usado,
        "esforco": esforco_usado,
        "entrada": (getattr(u, "input_tokens", 0) or 0)
                   + (getattr(u, "cache_creation_input_tokens", 0) or 0)
                   + (getattr(u, "cache_read_input_tokens", 0) or 0),
        "saida": getattr(u, "output_tokens", 0) or 0,
    }

    texto = "".join(b.text for b in resposta.content if b.type == "text").strip()
    texto = re.sub(r"^```(?:json)?\s*|\s*```$", "", texto.strip())
    try:
        doc = json.loads(texto)
    except json.JSONDecodeError:
        # de vez em quando a IA escreve uma frase antes ou depois do JSON;
        # antes de desistir, recorta o objeto do meio do texto. Se nem assim
        # der, o erro sobe pro chamador (que responde "JSON inválido").
        inicio, fim = texto.find("{"), texto.rfind("}")
        if inicio == -1 or fim <= inicio:
            raise
        doc = json.loads(texto[inicio:fim + 1])

    doc.setdefault("fontes", "; ".join(nomes))
    doc.setdefault("analise", {}).setdefault("_sourceFiles", "; ".join(nomes))
    doc["_iaModel"] = modelo_usado
    doc["_iaEsforco"] = esforco_usado
    return doc, uso


def _preparar_e_inserir_processo(doc: dict) -> dict:
    """Mesma preparação (id, timestamps, versão, defaults) que POST
    /api/processos faz — reaproveitada pela criação manual e pela criação
    automática a partir da análise de um processo novo do SharePoint."""
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
    return doc


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

    cfg = {
        "MODO_LOCAL": False,
        "TENANT_ID": MONTADOR_TENANT_ID,
        "CLIENT_ID": MONTADOR_CLIENT_ID,
        "CLIENT_SECRET": MONTADOR_CLIENT_SECRET,
    }
    try:
        pdfs_pasta = baixar_pdfs_da_pasta(cfg, caminho_pasta)
    except requests.HTTPError as e:
        if e.response is not None and e.response.status_code == 404:
            return jsonify({
                "erro": "Essa pasta não foi encontrada no SharePoint agora. Ela pode ter sido "
                        "renomeada, movida ou removida desde a última varredura. Clique em "
                        "\"Executar análise agora\" para atualizar a lista e tente de novo."
            }), 404
        return jsonify({"erro": f"Falha ao baixar documentos do SharePoint (erro {e.response.status_code if e.response is not None else '?'})."}), 502
    except Exception as e:
        return jsonify({"erro": f"Falha ao baixar documentos do SharePoint: {e}"}), 502
    if not pdfs_pasta:
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
        model=corpo.get("model"), effort=corpo.get("effort"),
    )
    return jsonify({"job_id": jid, "status": "rodando"}), 202


def _analisar_e_criar_processo(pdfs, tipo, caminho_pasta, model, effort) -> str:
    """Roda a análise e cria o processo. Só é chamada de dentro de uma thread
    de job — devolve o id do processo criado, e qualquer erro sobe pro job."""
    doc, uso = _rodar_analise_ia(pdfs, model=model, effort=effort)

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


@app.route("/api/processos/<pid>/anexos", methods=["POST"])
def enviar_anexo(pid):
    if not col_processos.find_one({"_id": pid}, {"_id": 1}):
        return jsonify({"erro": "Processo não encontrado"}), 404

    arquivo = request.files.get("arquivo")
    if not arquivo or not arquivo.filename:
        return jsonify({"erro": "Envie o arquivo no campo 'arquivo'"}), 400

    nome_original = arquivo.filename
    anexo_id = uuid.uuid4().hex
    nome_arquivo = anexo_id + "__" + secure_filename(nome_original)
    pasta = UPLOAD_DIR / pid
    pasta.mkdir(parents=True, exist_ok=True)
    destino = pasta / nome_arquivo
    arquivo.save(destino)

    enviado_por = request.form.get("enviadoPor", "")
    # "secao" marca o anexo como a planilha real de uma seção específica da
    # Análise Crítica (ex.: "quantitativos", "custos") — só uma por seção;
    # anexos comuns (sem seção) continuam só na aba de Anexos.
    secao = request.form.get("secao") or None
    agora = _agora_ms()
    tamanho = destino.stat().st_size
    if secao:
        antigo = col_anexos.find_one_and_delete({"processo_id": pid, "secao": secao})
        if antigo:
            (UPLOAD_DIR / pid / antigo["nome_arquivo"]).unlink(missing_ok=True)
    col_anexos.insert_one({
        "_id": anexo_id,
        "processo_id": pid,
        "nome_original": nome_original,
        "nome_arquivo": nome_arquivo,
        "tamanho": tamanho,
        "content_type": arquivo.content_type,
        "enviado_em": agora,
        "enviado_por": enviado_por,
        "secao": secao,
    })
    return jsonify({
        "id": anexo_id, "nome_original": nome_original, "tamanho": tamanho,
        "content_type": arquivo.content_type, "enviado_em": agora, "enviado_por": enviado_por,
        "secao": secao,
    }), 201


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
