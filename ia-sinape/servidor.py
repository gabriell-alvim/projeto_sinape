# -*- coding: utf-8 -*-
"""ia-service — servidor HTTP das capacidades de IA do sistema SINAPE.

Porta 5006. Roda local por enquanto; sobe para a AWS junto com o resto depois.

Endpoints (ver ARQUITETURA.md §3):
  GET  /health
  POST /analisar-edital     multipart: arquivos=PDF(s); form: criar_no_painel=1 (opcional)
  POST /analisar-atestados  multipart: arquivos=PDF(s) de UMA empresa concorrente;
                            form: processo_id (busca exigências no Painel) OU
                                  exigencias (JSON em texto), empresa (opcional),
                                  salvar_no_painel=1 (opcional, exige processo_id)
  POST /conferir-dossie     JSON: {processo_id, checklist_texto}

Autenticação entre serviços: se IA_SERVICE_TOKEN estiver no config.json,
toda rota (exceto /health) exige o header x-ia-token com o mesmo valor.

Uso:
    pip install -r requirements.txt
    python servidor.py
"""

import json
import logging

import anthropic
import requests as _requests
from flask import Flask, jsonify, request

import ia
import painel
from config import carregar_config, exigir

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s",
                    datefmt="%H:%M:%S")
log = logging.getLogger("ia-service")

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 25 * 1024 * 1024  # PDFs somados ≤ ~20MB úteis

CFG = carregar_config()  # recarregar = reiniciar o servidor


def _erro(msg: str, status: int = 400):
    return jsonify({"erro": msg}), status


@app.before_request
def _auth():
    if request.path == "/health":
        return None
    token = CFG.get("IA_SERVICE_TOKEN")
    if token and request.headers.get("x-ia-token") != token:
        return _erro("Token ausente ou inválido (header x-ia-token).", 401)
    return None


@app.errorhandler(ia.ErroIA)
def _erro_ia(e):
    return _erro(str(e), 422)


@app.errorhandler(painel.ErroPainel)
def _erro_painel(e):
    return _erro(str(e), 400)


@app.errorhandler(anthropic.AuthenticationError)
def _erro_auth_claude(_e):
    return _erro("Chave da Anthropic inválida ou revogada — confira ANTHROPIC_API_KEY.", 502)


@app.errorhandler(anthropic.RateLimitError)
def _erro_rate(_e):
    return _erro("Limite de requisições da API da Anthropic atingido — aguarde e tente de novo.", 429)


@app.errorhandler(anthropic.APIStatusError)
def _erro_api(e):
    log.error("Erro da API Anthropic: %s %s", e.status_code, e.message)
    return _erro(f"Erro da API da Anthropic ({e.status_code}). Tente novamente.", 502)


@app.errorhandler(anthropic.APIConnectionError)
def _erro_conexao(_e):
    return _erro("Sem conexão com a API da Anthropic — verifique a internet.", 502)


@app.errorhandler(_requests.RequestException)
def _erro_painel_http(e):
    log.error("Erro ao falar com o Painel: %s", e)
    return _erro("Não consegui falar com o Painel Sinape — confira PAINEL_BASE_URL/PAINEL_TOKEN.", 502)


def _pdfs_do_request() -> list[tuple[str, bytes]]:
    arquivos = request.files.getlist("arquivos")
    if not arquivos:
        raise ia.ErroIA("Envie ao menos um PDF no campo multipart 'arquivos'.")
    return [(a.filename or "documento.pdf", a.read()) for a in arquivos]


def _flag(nome: str) -> bool:
    return (request.form.get(nome) or "").lower() in ("1", "true", "sim")


@app.route("/health")
def health():
    faltando_ia = exigir(CFG, "ANTHROPIC_API_KEY")
    faltando_painel = exigir(CFG, "PAINEL_BASE_URL", "PAINEL_TOKEN")
    return jsonify({
        "ok": True,
        "modelo": CFG.get("CLAUDE_MODEL"),
        "claude_configurado": not faltando_ia,
        "painel_configurado": not faltando_painel,
    })


@app.route("/analisar-edital", methods=["POST"])
def rota_analisar_edital():
    faltando = exigir(CFG, "ANTHROPIC_API_KEY")
    if faltando:
        return _erro(f"Configuração incompleta: {', '.join(faltando)}. Preencha config.json.")

    arquivos = _pdfs_do_request()
    log.info("Analisando edital: %d arquivo(s)", len(arquivos))
    processo, usage = ia.analisar_edital(CFG, arquivos)

    resultado = {"processo": processo, "uso": usage}
    if _flag("criar_no_painel"):
        faltando = exigir(CFG, "PAINEL_BASE_URL", "PAINEL_TOKEN")
        if faltando:
            return _erro(f"criar_no_painel exige: {', '.join(faltando)} no config.json.")
        criado = painel.criar_processo(CFG, processo)
        resultado["painel"] = {"id": criado.get("id"), "criado": True}
        log.info("Processo criado no Painel: %s", criado.get("id"))
    return jsonify(resultado)


@app.route("/analisar-atestados", methods=["POST"])
def rota_analisar_atestados():
    faltando = exigir(CFG, "ANTHROPIC_API_KEY")
    if faltando:
        return _erro(f"Configuração incompleta: {', '.join(faltando)}. Preencha config.json.")

    arquivos = _pdfs_do_request()
    processo_id = (request.form.get("processo_id") or "").strip()
    salvar = _flag("salvar_no_painel")

    if salvar and not processo_id:
        return _erro("salvar_no_painel exige processo_id.")

    if processo_id:
        faltando = exigir(CFG, "PAINEL_BASE_URL", "PAINEL_TOKEN")
        if faltando:
            return _erro(f"processo_id exige: {', '.join(faltando)} no config.json.")
        processo = painel.obter_processo(CFG, processo_id)
        exigencias = painel.exigencias_tecnicas(processo)
    else:
        try:
            exigencias = json.loads(request.form.get("exigencias") or "[]")
        except json.JSONDecodeError:
            return _erro("Campo 'exigencias' não é JSON válido.")
        if not exigencias:
            return _erro("Informe processo_id OU o campo 'exigencias' (JSON) com as "
                         "exigências técnicas do edital.")

    log.info("Analisando atestados: %d arquivo(s), %d exigência(s)", len(arquivos), len(exigencias))
    analise, usage = ia.analisar_atestados(CFG, arquivos, exigencias,
                                           empresa_dica=request.form.get("empresa", ""))

    resultado = {"analise": analise, "uso": usage}
    if salvar:
        painel.salvar_analise_concorrente(CFG, processo_id, analise)
        resultado["painel"] = {"id": processo_id, "salvo_em": "analise.concorrencia"}
        log.info("Análise de '%s' salva no processo %s", analise.get("empresa"), processo_id)
    return jsonify(resultado)


@app.route("/conferir-dossie", methods=["POST"])
def rota_conferir_dossie():
    faltando = exigir(CFG, "ANTHROPIC_API_KEY", "PAINEL_BASE_URL", "PAINEL_TOKEN")
    if faltando:
        return _erro(f"Configuração incompleta: {', '.join(faltando)}. Preencha config.json.")

    corpo = request.get_json(silent=True) or {}
    processo_id = (corpo.get("processo_id") or "").strip()
    checklist_texto = (corpo.get("checklist_texto") or "").strip()
    if not processo_id or not checklist_texto:
        return _erro("Corpo JSON deve ter 'processo_id' e 'checklist_texto'.")

    processo = painel.obter_processo(CFG, processo_id)
    exigencias = processo.get("exigencias") or []
    if not exigencias:
        return _erro(f"Processo '{processo_id}' não tem exigências cadastradas no Painel.")

    log.info("Conferindo dossiê do processo %s (%d exigências)", processo_id, len(exigencias))
    parecer, usage = ia.conferir_dossie(CFG, exigencias, checklist_texto)
    return jsonify({"parecer": parecer, "uso": usage})


if __name__ == "__main__":
    log.info("ia-service subindo na porta 5006 (modelo: %s)", CFG.get("CLAUDE_MODEL"))
    app.run(host="127.0.0.1", port=5006, debug=False)
