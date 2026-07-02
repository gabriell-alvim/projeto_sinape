# -*- coding: utf-8 -*-
"""
API do Painel de Processos SINAPE — AWS Lambda (Python 3.12) + DynamoDB + Function URL
======================================================================================

Rotas atendidas (Function URL, payload v2):
  OPTIONS *                      → CORS preflight (sem token)
  GET     /processos             → lista resumida  {"processos":[...]}
  POST    /processos             → cria processo (corpo = documento completo)
  GET     /processos/{id}        → documento completo
  PUT     /processos/{id}        → substitui documento completo
  PATCH   /processos/{id}        → mescla {metaPatch, analisePatch, checklistPatch, seVersao}
  DELETE  /processos/{id}        → remove

Autenticação: header  x-sinape-token  comparado com a variável de ambiente TOKEN.
Armazenamento: tabela DynamoDB (env TABLE_NAME, PK "id" tipo String).
  O documento inteiro é guardado como string JSON no atributo "doc" (evita
  problemas com Decimal/float do DynamoDB). Campos de listagem ficam também
  no nível de cima do item para o Scan com projeção ser barato:
  id, nome, type, status, progress, origem, fontes, atualizadoEm,
  atualizadoPor, versao.

Controle de concorrência: PATCH aceita "seVersao"; se a versão gravada for
diferente, responde 409 com o documento atual no corpo — o painel então
mescla e reenvia (last-write-wins campo a campo, sem travar ninguém).
"""

import base64
import json
import os
import re
import time
import uuid

import boto3
from botocore.exceptions import ClientError

TABLE_NAME = os.environ.get("TABLE_NAME", "SinapeProcessos")
TOKEN = os.environ.get("TOKEN", "")

_dynamo = boto3.resource("dynamodb")
_table = _dynamo.Table(TABLE_NAME)

CORS_HEADERS = {
    "Access-Control-Allow-Origin": "*",           # depois de publicar, restrinja ao seu domínio
    "Access-Control-Allow-Methods": "GET,POST,PUT,PATCH,DELETE,OPTIONS",
    "Access-Control-Allow-Headers": "content-type,x-sinape-token",
    "Access-Control-Max-Age": "86400",
}

# Campos duplicados no topo do item para a listagem (Scan com projeção)
CAMPOS_RESUMO = [
    "id", "nome", "type", "status", "progress", "origem",
    "fontes", "atualizadoEm", "atualizadoPor", "versao",
]


# ──────────────────────────────────────────────────────────────────
# util
# ──────────────────────────────────────────────────────────────────
def _resp(status, corpo=None):
    headers = dict(CORS_HEADERS)
    headers["Content-Type"] = "application/json; charset=utf-8"
    return {
        "statusCode": status,
        "headers": headers,
        "body": "" if corpo is None else json.dumps(corpo, ensure_ascii=False),
    }


def _agora_ms():
    return int(time.time() * 1000)


def _slug(texto):
    s = (texto or "").lower()
    s = re.sub(r"[àáâãä]", "a", s); s = re.sub(r"[èéêë]", "e", s)
    s = re.sub(r"[ìíîï]", "i", s);  s = re.sub(r"[òóôõö]", "o", s)
    s = re.sub(r"[ùúûü]", "u", s);  s = re.sub(r"[ç]", "c", s)
    s = re.sub(r"[^a-z0-9]+", "-", s).strip("-")
    return s[:60] or ("proc-" + uuid.uuid4().hex[:8])


def _corpo_json(event):
    body = event.get("body")
    if body is None:
        return None
    if event.get("isBase64Encoded"):
        body = base64.b64decode(body).decode("utf-8")
    body = body.strip()
    if not body:
        return None
    return json.loads(body)


def _resumo_do_doc(doc):
    """Extrai os campos de listagem de um documento completo."""
    return {
        "id": doc.get("id"),
        "nome": doc.get("nome") or "(sem nome)",
        "type": doc.get("type") or "publico",
        "status": doc.get("status") or "em_analise",
        "progress": int(doc.get("progress") or 0),
        "origem": doc.get("origem") or "manual",
        "fontes": doc.get("fontes") or "",
        "atualizadoEm": int(doc.get("atualizadoEm") or 0),
        "atualizadoPor": doc.get("atualizadoPor") or "",
        "versao": int(doc.get("versao") or 1),
    }


def _item_do_doc(doc):
    """Monta o item DynamoDB: resumo no topo + doc inteiro como string JSON."""
    item = _resumo_do_doc(doc)
    item["doc"] = json.dumps(doc, ensure_ascii=False)
    return item


def _doc_do_item(item):
    try:
        return json.loads(item.get("doc") or "{}")
    except (TypeError, ValueError):
        return {}


# ──────────────────────────────────────────────────────────────────
# operações
# ──────────────────────────────────────────────────────────────────
def _listar():
    processos, start_key = [], None
    while True:
        kwargs = {
            "ProjectionExpression": "#i,#n,#t,#s,progress,origem,fontes,atualizadoEm,atualizadoPor,versao",
            "ExpressionAttributeNames": {"#i": "id", "#n": "nome", "#t": "type", "#s": "status"},
        }
        if start_key:
            kwargs["ExclusiveStartKey"] = start_key
        pagina = _table.scan(**kwargs)
        for it in pagina.get("Items", []):
            processos.append({
                "id": it.get("id"),
                "nome": it.get("nome") or "",
                "type": it.get("type") or "publico",
                "status": it.get("status") or "em_analise",
                "progress": int(it.get("progress") or 0),
                "origem": it.get("origem") or "manual",
                "fontes": it.get("fontes") or "",
                "atualizadoEm": int(it.get("atualizadoEm") or 0),
                "atualizadoPor": it.get("atualizadoPor") or "",
                "versao": int(it.get("versao") or 1),
            })
        start_key = pagina.get("LastEvaluatedKey")
        if not start_key:
            break
    processos.sort(key=lambda p: p["atualizadoEm"], reverse=True)
    return _resp(200, {"processos": processos})


def _obter(pid):
    r = _table.get_item(Key={"id": pid})
    if "Item" not in r:
        return _resp(404, {"erro": "Processo não encontrado"})
    return _resp(200, _doc_do_item(r["Item"]))


def _criar(doc):
    if not isinstance(doc, dict):
        return _resp(400, {"erro": "Corpo deve ser um objeto JSON"})
    if not doc.get("id"):
        doc["id"] = _slug(doc.get("nome", "")) + "-" + uuid.uuid4().hex[:6]
    agora = _agora_ms()
    doc.setdefault("criadoEm", agora)
    doc["atualizadoEm"] = agora
    doc["versao"] = int(doc.get("versao") or 1)
    doc.setdefault("analise", {})
    doc.setdefault("checklist", {})
    try:
        _table.put_item(
            Item=_item_do_doc(doc),
            ConditionExpression="attribute_not_exists(id)",
        )
    except ClientError as e:
        if e.response["Error"]["Code"] == "ConditionalCheckFailedException":
            return _resp(409, {"erro": "Já existe processo com esse id", "id": doc["id"]})
        raise
    return _resp(201, doc)


def _substituir(pid, doc):
    if not isinstance(doc, dict):
        return _resp(400, {"erro": "Corpo deve ser um objeto JSON"})
    doc["id"] = pid
    doc["atualizadoEm"] = _agora_ms()
    doc["versao"] = int(doc.get("versao") or 1)
    _table.put_item(Item=_item_do_doc(doc))
    return _resp(200, doc)


def _patch(pid, corpo):
    if not isinstance(corpo, dict):
        return _resp(400, {"erro": "Corpo deve ser um objeto JSON"})
    se_versao = corpo.get("seVersao")

    # até 3 tentativas contra corridas de escrita simultânea
    for _ in range(3):
        r = _table.get_item(Key={"id": pid})
        if "Item" not in r:
            return _resp(404, {"erro": "Processo não encontrado"})
        doc = _doc_do_item(r["Item"])
        versao_atual = int(doc.get("versao") or 1)

        if se_versao is not None and int(se_versao) != versao_atual:
            return _resp(409, doc)  # painel mescla e tenta de novo

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

        doc["versao"] = versao_atual + 1
        doc["atualizadoEm"] = _agora_ms()

        try:
            _table.put_item(
                Item=_item_do_doc(doc),
                ConditionExpression="attribute_not_exists(id) OR versao = :v",
                ExpressionAttributeValues={":v": versao_atual},
            )
            return _resp(200, {"versao": doc["versao"], "atualizadoEm": doc["atualizadoEm"]})
        except ClientError as e:
            if e.response["Error"]["Code"] == "ConditionalCheckFailedException":
                if se_versao is not None:
                    r2 = _table.get_item(Key={"id": pid})
                    return _resp(409, _doc_do_item(r2.get("Item", {})))
                continue  # sem seVersao: recarrega e tenta de novo
            raise
    return _resp(503, {"erro": "Muitas escritas simultâneas, tente novamente"})


def _excluir(pid):
    _table.delete_item(Key={"id": pid})
    return _resp(200, {"ok": True})


# ──────────────────────────────────────────────────────────────────
# handler
# ──────────────────────────────────────────────────────────────────
def lambda_handler(event, context):
    http = (event.get("requestContext") or {}).get("http") or {}
    metodo = (http.get("method") or "GET").upper()
    caminho = event.get("rawPath") or "/"

    if metodo == "OPTIONS":
        return {"statusCode": 204, "headers": dict(CORS_HEADERS), "body": ""}

    # autenticação
    headers = {k.lower(): v for k, v in (event.get("headers") or {}).items()}
    if not TOKEN or headers.get("x-sinape-token") != TOKEN:
        return _resp(401, {"erro": "Token ausente ou inválido"})

    # roteamento:  /processos  |  /processos/{id}
    partes = [p for p in caminho.split("/") if p]
    try:
        if partes[:1] == ["processos"]:
            if len(partes) == 1:
                if metodo == "GET":
                    return _listar()
                if metodo == "POST":
                    return _criar(_corpo_json(event))
            elif len(partes) == 2:
                pid = partes[1]
                if metodo == "GET":
                    return _obter(pid)
                if metodo == "PUT":
                    return _substituir(pid, _corpo_json(event))
                if metodo == "PATCH":
                    return _patch(pid, _corpo_json(event))
                if metodo == "DELETE":
                    return _excluir(pid)
        return _resp(404, {"erro": "Rota não encontrada", "rota": metodo + " " + caminho})
    except json.JSONDecodeError:
        return _resp(400, {"erro": "JSON inválido no corpo da requisição"})
    except ClientError as e:
        return _resp(500, {"erro": "Erro DynamoDB: " + e.response["Error"]["Code"]})
