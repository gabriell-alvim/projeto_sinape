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
import json
import os
import re
import shutil
import sys
import tempfile
import time
import uuid
from datetime import timedelta
from pathlib import Path
from urllib.parse import quote

import anthropic
from pymongo import MongoClient, ASCENDING, DESCENDING
from pymongo.errors import DuplicateKeyError
from flask import Flask, request, jsonify, send_from_directory, send_file, session, redirect, Response
from werkzeug.utils import secure_filename

BASE_DIR = Path(__file__).resolve().parent
UPLOAD_DIR = Path(os.environ.get("UPLOAD_DIR", "/app/uploads"))
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

sys.path.insert(0, str(BASE_DIR / "montador-dossie"))
from montador_dossie import montar_dossie_por_processo  # noqa: E402

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
ANTHROPIC_MODEL = os.environ.get("ANTHROPIC_MODEL", "claude-opus-4-8")
MAX_PDF_TOTAL_MB = int(os.environ.get("MAX_PDF_TOTAL_MB", "24"))  # margem p/ limite de 32MB em base64
PROMPT_IA = (BASE_DIR / "prompt_ia.txt").read_text(encoding="utf-8")
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


@app.route("/api/processos/analisar-ia", methods=["POST"])
def analisar_ia():
    if not anthropic_client:
        return jsonify({"erro": "ANTHROPIC_API_KEY não configurada no servidor"}), 503

    arquivos = request.files.getlist("arquivos")
    if not arquivos:
        return jsonify({"erro": "Envie ao menos um arquivo no campo 'arquivos'"}), 400

    total_bytes = 0
    content = []
    nomes = []
    for arquivo in arquivos:
        if arquivo.mimetype != "application/pdf":
            return jsonify({"erro": f"Arquivo '{arquivo.filename}' não é PDF"}), 400
        dados = arquivo.read()
        total_bytes += len(dados)
        if total_bytes > MAX_PDF_TOTAL_MB * 1024 * 1024:
            return jsonify({"erro": f"Total dos PDFs excede {MAX_PDF_TOTAL_MB} MB"}), 400
        nomes.append(arquivo.filename)
        content.append({
            "type": "document",
            "source": {
                "type": "base64",
                "media_type": "application/pdf",
                "data": base64.standard_b64encode(dados).decode("ascii"),
            },
        })
    content.append({"type": "text", "text": PROMPT_IA})

    try:
        with anthropic_client.messages.stream(
            model=ANTHROPIC_MODEL,
            max_tokens=32000,
            messages=[{"role": "user", "content": content}],
        ) as stream:
            resposta = stream.get_final_message()
    except anthropic.APIStatusError as e:
        return jsonify({"erro": f"Erro na API da IA: {e.message}"}), 502

    texto = "".join(b.text for b in resposta.content if b.type == "text").strip()
    texto = re.sub(r"^```(?:json)?\s*|\s*```$", "", texto.strip())

    try:
        doc = json.loads(texto)
    except json.JSONDecodeError:
        return jsonify({"erro": "A IA não devolveu um JSON válido", "bruto": texto[:2000]}), 502

    doc.setdefault("fontes", "; ".join(nomes))
    doc.setdefault("analise", {}).setdefault("_sourceFiles", "; ".join(nomes))
    return jsonify(doc)


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
