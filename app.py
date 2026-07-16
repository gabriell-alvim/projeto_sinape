# -*- coding: utf-8 -*-
"""
API do Painel de Processos SINAPE — servidor Flask (Docker) + MongoDB
=========================================================================

Substitui o backend AWS (Lambda + DynamoDB + S3) por um único container:
Flask serve o index.html, login.html e a API; os dados ficam no MongoDB; os anexos
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
  POST    /api/pdf/secoes                    → analisa PDF e mapeia seções (negrito + CAPS) → páginas

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

import json
import os
import re
import time
import uuid
from datetime import timedelta
from pathlib import Path
from urllib.parse import quote

from pymongo import MongoClient, ASCENDING, DESCENDING
from pymongo.errors import DuplicateKeyError
from flask import Flask, request, jsonify, send_from_directory, send_file, session, redirect
from werkzeug.utils import secure_filename

from pdf_sections import analisar_pdf_secoes, configurar_log

BASE_DIR = Path(__file__).resolve().parent
UPLOAD_DIR = Path(os.environ.get("UPLOAD_DIR", "/app/uploads"))
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

TOKEN = os.environ.get("TOKEN", "")
SITE_USER = os.environ.get("SITE_USER", "")
SITE_PASSWORD = os.environ.get("SITE_PASSWORD", "")
SECRET_KEY = os.environ.get("SECRET_KEY", "troque-em-producao")
MONGO_URL = os.environ.get("MONGO_URL", "")
MAX_UPLOAD_MB = int(os.environ.get("MAX_UPLOAD_MB", "25"))
PDF_DEBUG = os.environ.get("PDF_DEBUG", "").lower() in ("1", "true", "yes")

if PDF_DEBUG:
    configurar_log(debug=True)

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


def _init_db():
    col_processos.create_index([("atualizadoEm", DESCENDING)])
    col_anexos.create_index([("processo_id", ASCENDING), ("enviado_em", DESCENDING)])


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
# análise de PDF (seções para otimização de tokens na IA)
# ──────────────────────────────────────────────────────────────────
def _eh_pdf_upload(arquivo):
    if not arquivo or not arquivo.filename:
        return False
    nome = arquivo.filename.lower()
    return nome.endswith(".pdf") or arquivo.mimetype == "application/pdf"


@app.route("/api/pdf/secoes", methods=["POST"])
def analisar_pdf():
    arquivos = request.files.getlist("arquivos") or request.files.getlist("arquivo")
    if not arquivos:
        unico = request.files.get("arquivo")
        arquivos = [unico] if unico else []

    pdfs = [a for a in arquivos if _eh_pdf_upload(a)]
    if not pdfs:
        return jsonify({"erro": "Envie ao menos um PDF no campo 'arquivo' ou 'arquivos'"}), 400

    resultado = []
    for arquivo in pdfs:
        try:
            dados = arquivo.read()
            if len(dados) > MAX_UPLOAD_MB * 1024 * 1024:
                return jsonify({
                    "erro": f'"{arquivo.filename}" excede {MAX_UPLOAD_MB} MB',
                }), 400
            analise = analisar_pdf_secoes(
                dados, nome_arquivo=arquivo.filename, debug=PDF_DEBUG,
            )
            resultado.append(analise)
        except Exception as exc:
            return jsonify({
                "erro": f'Falha ao analisar "{arquivo.filename}"',
                "detalhe": str(exc),
            }), 400

    if len(resultado) == 1:
        return jsonify(resultado[0])
    return jsonify({"arquivos": resultado})


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
    pid = doc.get("id") or (_slug(doc.get("nome", "")) + "-" + uuid.uuid4().hex[:6])
    agora = _agora_ms()
    doc["id"] = pid
    doc.setdefault("criadoEm", agora)
    doc["atualizadoEm"] = agora
    doc["versao"] = int(doc.get("versao") or 1)
    doc.setdefault("analise", {})
    doc.setdefault("checklist", {})

    doc["_id"] = pid
    del doc["id"]
    try:
        col_processos.insert_one(doc)
    except DuplicateKeyError:
        return jsonify({"erro": "Já existe processo com esse id", "id": pid}), 409
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


# ──────────────────────────────────────────────────────────────────
# anexos
# ──────────────────────────────────────────────────────────────────
@app.route("/api/processos/<pid>/anexos", methods=["GET"])
def listar_anexos(pid):
    cursor = col_anexos.find(
        {"processo_id": pid},
        {"nome_original": 1, "tamanho": 1, "content_type": 1, "enviado_em": 1, "enviado_por": 1},
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
    agora = _agora_ms()
    tamanho = destino.stat().st_size
    col_anexos.insert_one({
        "_id": anexo_id,
        "processo_id": pid,
        "nome_original": nome_original,
        "nome_arquivo": nome_arquivo,
        "tamanho": tamanho,
        "content_type": arquivo.content_type,
        "enviado_em": agora,
        "enviado_por": enviado_por,
    })
    return jsonify({
        "id": anexo_id, "nome_original": nome_original, "tamanho": tamanho,
        "content_type": arquivo.content_type, "enviado_em": agora, "enviado_por": enviado_por,
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
