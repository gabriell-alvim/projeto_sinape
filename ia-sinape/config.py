# -*- coding: utf-8 -*-
"""Configuração do ia-service.

Lê config.json (mesmo padrão do Montador) com variáveis de ambiente tendo
prioridade. Nenhuma chave é obrigatória para o servidor SUBIR — cada endpoint
valida o que precisa e devolve erro claro se faltar, para o serviço poder
rodar antes de todas as credenciais existirem.
"""

import json
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent

CHAVES = [
    "ANTHROPIC_API_KEY",   # chave criada pelo Gabriel em platform.claude.com
    "CLAUDE_MODEL",        # padrão: claude-opus-4-8
    "CLAUDE_EFFORT",       # padrão: high
    "PAINEL_BASE_URL",     # ex: http://localhost:8080 ou URL na AWS
    "PAINEL_TOKEN",        # mesmo x-sinape-token do Painel
    "IA_SERVICE_TOKEN",    # se preenchido, exige header x-ia-token nas chamadas
]

PADROES = {
    "CLAUDE_MODEL": "claude-opus-4-8",
    "CLAUDE_EFFORT": "high",
}


def carregar_config() -> dict:
    cfg = dict(PADROES)
    caminho = BASE_DIR / "config.json"
    if caminho.exists():
        with open(caminho, "r", encoding="utf-8") as f:
            cfg.update({k: v for k, v in json.load(f).items() if v})
    for chave in CHAVES:
        if os.environ.get(chave):
            cfg[chave] = os.environ[chave]
    return cfg


def exigir(cfg: dict, *chaves: str) -> list:
    """Devolve a lista de chaves faltantes (vazia = tudo ok)."""
    return [k for k in chaves if not cfg.get(k)]
