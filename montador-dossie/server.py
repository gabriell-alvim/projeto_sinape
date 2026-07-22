#!/usr/bin/env python3
"""Servidor local para a pagina 'Dossie de Montagem de Documentacao'.

Roda 100% na sua maquina. A pagina HTML nunca ve o CLIENT_SECRET nem o
PAINEL_TOKEN - eles ficam so aqui no servidor (config.json), lidos do disco.

Uso:
    pip install -r requirements.txt
    python server.py
    -> abra http://localhost:5005 no navegador
"""

import json
import traceback
from pathlib import Path

from flask import Flask, request, send_from_directory, send_file, Response

from montador_dossie import carregar_config, montar_dossie_por_processo

BASE_DIR = Path(__file__).resolve().parent
app = Flask(__name__, static_folder=None)


def carregar_biblioteca():
    with open(BASE_DIR / "biblioteca.json", "r", encoding="utf-8") as f:
        return json.load(f)


@app.route("/")
def index():
    return send_from_directory(BASE_DIR, "index.html")


@app.route("/montar")
def montar():
    processo_id = request.args.get("processo_id", "").strip()
    if not processo_id:
        return Response("Informe o id do processo.", status=400)

    try:
        cfg = carregar_config(str(BASE_DIR / "config.json"))
        biblioteca = carregar_biblioteca()
        saida_dir = BASE_DIR / "dossies" / processo_id
        zip_destino = montar_dossie_por_processo(cfg, biblioteca, processo_id, saida_dir)
        return send_file(zip_destino, as_attachment=True, download_name=zip_destino.name)
    except SystemExit as e:
        return Response(f"<h3>Nao foi possivel montar o dossie</h3><p>{e}</p>", status=400, mimetype="text/html")
    except Exception as e:
        traceback.print_exc()
        return Response(f"<h3>Erro inesperado</h3><pre>{e}</pre>", status=500, mimetype="text/html")


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5005, debug=False)
