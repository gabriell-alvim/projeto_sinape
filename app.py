# -*- coding: utf-8 -*-
"""
API do Painel de Processos SINAPE — servidor Flask (Docker) + PostgreSQL
=========================================================================

Substitui o backend AWS (Lambda + DynamoDB + S3) por um único container:
Flask serve o index.html e a API; os dados ficam no Postgres; os anexos
enviados pela equipe ficam em disco, dentro da pasta UPLOAD_DIR.

Rotas:
  GET     /                                  → index.html
  GET     /api/processos                     → lista resumida {"processos":[...]}
  POST    /api/processos                     → cria processo (corpo = documento completo)
  GET     /api/processos/<id>                → documento completo
  PUT     /api/processos/<id>                → substitui documento completo
  PATCH   /api/processos/<id>                → mescla {metaPatch, analisePatch, checklistPatch, seVersao}
  DELETE  /api/processos/<id>                → remove (e seus anexos)
  GET     /api/processos/<id>/anexos         → lista anexos do processo
  POST    /api/processos/<id>/anexos         → envia um anexo (multipart, campo "arquivo")
  GET     /api/processos/<id>/anexos/<aid>   → baixa o arquivo
  DELETE  /api/processos/<id>/anexos/<aid>   → remove o anexo (registro + arquivo em disco)

Autenticação: header x-sinape-token comparado com a variável de ambiente TOKEN.
Armazenamento de dados: Postgres (env DATABASE_URL), tabela "processos" com o
documento inteiro em uma coluna JSONB (evita migração de esquema a cada campo novo).
Armazenamento de anexos: disco, em UPLOAD_DIR/<processo_id>/<uuid>__<nome original>.

Controle de concorrência: PATCH aceita "seVersao"; se a versão gravada for
diferente, responde 409 com o documento atual no corpo — o painel então
mescla e reenvia (last-write-wins campo a campo, sem travar ninguém).
"""

import json
import os
import re
import time
import uuid
from pathlib import Path

import psycopg2
import psycopg2.extras
from flask import Flask, request, jsonify, send_from_directory, send_file, g
from werkzeug.utils import secure_filename

BASE_DIR = Path(__file__).resolve().parent
UPLOAD_DIR = Path(os.environ.get("UPLOAD_DIR", "/app/uploads"))
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

TOKEN = os.environ.get("TOKEN", "")
DATABASE_URL = os.environ.get("DATABASE_URL", "")
MAX_UPLOAD_MB = int(os.environ.get("MAX_UPLOAD_MB", "25"))

app = Flask(__name__, static_folder=None)
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
def _conn():
    if "db" not in g:
        g.db = psycopg2.connect(DATABASE_URL)
    return g.db


@app.teardown_appcontext
def _fecha_conn(_exc):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def _init_db():
    conn = psycopg2.connect(DATABASE_URL)
    try:
        with conn, conn.cursor() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS processos (
                    id TEXT PRIMARY KEY,
                    versao INTEGER NOT NULL DEFAULT 1,
                    atualizado_em BIGINT NOT NULL,
                    doc JSONB NOT NULL
                );
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS anexos (
                    id TEXT PRIMARY KEY,
                    processo_id TEXT NOT NULL REFERENCES processos(id) ON DELETE CASCADE,
                    nome_original TEXT NOT NULL,
                    nome_arquivo TEXT NOT NULL,
                    tamanho BIGINT,
                    content_type TEXT,
                    enviado_em BIGINT NOT NULL,
                    enviado_por TEXT
                );
            """)
    finally:
        conn.close()


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


def _resumo_da_linha(row):
    doc = row["doc"]
    return {
        "id": row["id"],
        "nome": doc.get("nome") or "(sem nome)",
        "type": doc.get("type") or "publico",
        "status": doc.get("status") or "em_analise",
        "progress": int(doc.get("progress") or 0),
        "origem": doc.get("origem") or "manual",
        "fontes": doc.get("fontes") or "",
        "atualizadoEm": row["atualizado_em"],
        "atualizadoPor": doc.get("atualizadoPor") or "",
        "versao": row["versao"],
    }


@app.after_request
def _add_cors(resp):
    for k, v in CORS_HEADERS.items():
        resp.headers[k] = v
    return resp


@app.before_request
def _auth():
    if request.method == "OPTIONS":
        return ("", 204)
    if request.path == "/" or request.path.startswith("/api/health"):
        return None
    if not request.path.startswith("/api/"):
        return None
    if not TOKEN or request.headers.get("x-sinape-token") != TOKEN:
        return jsonify({"erro": "Token ausente ou inválido"}), 401


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
    conn = _conn()
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute("SELECT id, versao, atualizado_em, doc FROM processos ORDER BY atualizado_em DESC;")
        processos = [_resumo_da_linha(r) for r in cur.fetchall()]
    return jsonify({"processos": processos})


@app.route("/api/processos", methods=["POST"])
def criar():
    doc = request.get_json(force=True, silent=False)
    if not isinstance(doc, dict):
        return jsonify({"erro": "Corpo deve ser um objeto JSON"}), 400
    if not doc.get("id"):
        doc["id"] = _slug(doc.get("nome", "")) + "-" + uuid.uuid4().hex[:6]
    agora = _agora_ms()
    doc.setdefault("criadoEm", agora)
    doc["atualizadoEm"] = agora
    doc["versao"] = int(doc.get("versao") or 1)
    doc.setdefault("analise", {})
    doc.setdefault("checklist", {})

    conn = _conn()
    try:
        with conn, conn.cursor() as cur:
            cur.execute(
                "INSERT INTO processos (id, versao, atualizado_em, doc) VALUES (%s,%s,%s,%s);",
                (doc["id"], doc["versao"], doc["atualizadoEm"], psycopg2.extras.Json(doc)),
            )
    except psycopg2.errors.UniqueViolation:
        conn.rollback()
        return jsonify({"erro": "Já existe processo com esse id", "id": doc["id"]}), 409
    return jsonify(doc), 201


@app.route("/api/processos/<pid>", methods=["GET"])
def obter(pid):
    conn = _conn()
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute("SELECT doc FROM processos WHERE id=%s;", (pid,))
        row = cur.fetchone()
    if not row:
        return jsonify({"erro": "Processo não encontrado"}), 404
    return jsonify(row["doc"])


@app.route("/api/processos/<pid>", methods=["PUT"])
def substituir(pid):
    doc = request.get_json(force=True, silent=False)
    if not isinstance(doc, dict):
        return jsonify({"erro": "Corpo deve ser um objeto JSON"}), 400
    doc["id"] = pid
    doc["atualizadoEm"] = _agora_ms()
    doc["versao"] = int(doc.get("versao") or 1)

    conn = _conn()
    with conn, conn.cursor() as cur:
        cur.execute(
            """INSERT INTO processos (id, versao, atualizado_em, doc) VALUES (%s,%s,%s,%s)
               ON CONFLICT (id) DO UPDATE SET versao=EXCLUDED.versao,
                   atualizado_em=EXCLUDED.atualizado_em, doc=EXCLUDED.doc;""",
            (pid, doc["versao"], doc["atualizadoEm"], psycopg2.extras.Json(doc)),
        )
    return jsonify(doc)


@app.route("/api/processos/<pid>", methods=["PATCH"])
def patch(pid):
    corpo = request.get_json(force=True, silent=False)
    if not isinstance(corpo, dict):
        return jsonify({"erro": "Corpo deve ser um objeto JSON"}), 400
    se_versao = corpo.get("seVersao")

    conn = _conn()
    with conn, conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute("SELECT versao, doc FROM processos WHERE id=%s FOR UPDATE;", (pid,))
        row = cur.fetchone()
        if not row:
            return jsonify({"erro": "Processo não encontrado"}), 404
        doc = row["doc"]
        versao_atual = row["versao"]

        if se_versao is not None and int(se_versao) != versao_atual:
            return jsonify(doc), 409  # painel mescla e tenta de novo

        for chave, valor in (corpo.get("metaPatch") or {}).items():
            if chave in ("id", "versao", "doc"):
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

        cur.execute(
            "UPDATE processos SET versao=%s, atualizado_em=%s, doc=%s WHERE id=%s;",
            (nova_versao, agora, psycopg2.extras.Json(doc), pid),
        )
    return jsonify({"versao": nova_versao, "atualizadoEm": agora})


@app.route("/api/processos/<pid>", methods=["DELETE"])
def excluir(pid):
    conn = _conn()
    with conn, conn.cursor() as cur:
        cur.execute("SELECT nome_arquivo FROM anexos WHERE processo_id=%s;", (pid,))
        arquivos = [r[0] for r in cur.fetchall()]
        cur.execute("DELETE FROM processos WHERE id=%s;", (pid,))
    for nome_arquivo in arquivos:
        (UPLOAD_DIR / pid / nome_arquivo).unlink(missing_ok=True)
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
    conn = _conn()
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(
            """SELECT id, nome_original, tamanho, content_type, enviado_em, enviado_por
               FROM anexos WHERE processo_id=%s ORDER BY enviado_em DESC;""",
            (pid,),
        )
        anexos = cur.fetchall()
    return jsonify({"anexos": anexos})


@app.route("/api/processos/<pid>/anexos", methods=["POST"])
def enviar_anexo(pid):
    conn = _conn()
    with conn.cursor() as cur:
        cur.execute("SELECT 1 FROM processos WHERE id=%s;", (pid,))
        if not cur.fetchone():
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
    with conn, conn.cursor() as cur:
        cur.execute(
            """INSERT INTO anexos (id, processo_id, nome_original, nome_arquivo, tamanho,
                   content_type, enviado_em, enviado_por)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s);""",
            (anexo_id, pid, nome_original, nome_arquivo, destino.stat().st_size,
             arquivo.content_type, agora, enviado_por),
        )
    return jsonify({
        "id": anexo_id, "nome_original": nome_original, "tamanho": destino.stat().st_size,
        "content_type": arquivo.content_type, "enviado_em": agora, "enviado_por": enviado_por,
    }), 201


@app.route("/api/processos/<pid>/anexos/<aid>", methods=["GET"])
def baixar_anexo(pid, aid):
    conn = _conn()
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(
            "SELECT nome_original, nome_arquivo, content_type FROM anexos WHERE id=%s AND processo_id=%s;",
            (aid, pid),
        )
        row = cur.fetchone()
    if not row:
        return jsonify({"erro": "Anexo não encontrado"}), 404
    caminho = UPLOAD_DIR / pid / row["nome_arquivo"]
    if not caminho.is_file():
        return jsonify({"erro": "Arquivo não encontrado em disco"}), 404
    return send_file(caminho, mimetype=row["content_type"], as_attachment=True,
                      download_name=row["nome_original"])


@app.route("/api/processos/<pid>/anexos/<aid>", methods=["DELETE"])
def excluir_anexo(pid, aid):
    conn = _conn()
    with conn, conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(
            "DELETE FROM anexos WHERE id=%s AND processo_id=%s RETURNING nome_arquivo;",
            (aid, pid),
        )
        row = cur.fetchone()
    if not row:
        return jsonify({"erro": "Anexo não encontrado"}), 404
    (UPLOAD_DIR / pid / row["nome_arquivo"]).unlink(missing_ok=True)
    return jsonify({"ok": True})


@app.errorhandler(json.JSONDecodeError)
def _erro_json(_e):
    return jsonify({"erro": "JSON inválido no corpo da requisição"}), 400


_init_db()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "8080")), debug=False)
