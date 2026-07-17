# -*- coding: utf-8 -*-
"""Cliente da API do Painel Sinape (app.py Flask+Mongo ou Lambda)."""

import requests


class ErroPainel(Exception):
    pass


def _base(cfg: dict) -> tuple[str, dict]:
    url = cfg["PAINEL_BASE_URL"].rstrip("/")
    headers = {"x-sinape-token": cfg["PAINEL_TOKEN"]}
    return url, headers


def obter_processo(cfg: dict, processo_id: str) -> dict:
    url, headers = _base(cfg)
    resp = requests.get(f"{url}/api/processos/{processo_id}", headers=headers, timeout=15)
    if resp.status_code == 404:
        raise ErroPainel(f"Processo '{processo_id}' não encontrado no Painel.")
    resp.raise_for_status()
    return resp.json()


def criar_processo(cfg: dict, doc: dict) -> dict:
    url, headers = _base(cfg)
    resp = requests.post(f"{url}/api/processos", headers=headers, json=doc, timeout=15)
    if resp.status_code == 409:
        raise ErroPainel(f"Já existe processo com esse id no Painel: {resp.json().get('id')}")
    resp.raise_for_status()
    return resp.json()


def salvar_analise_concorrente(cfg: dict, processo_id: str, analise: dict) -> dict:
    """Anexa a análise de um concorrente à lista analise.concorrencia do
    processo. Read-modify-write com seVersao; uma retentativa em conflito."""
    url, headers = _base(cfg)
    for _ in range(2):
        doc = obter_processo(cfg, processo_id)
        lista = list((doc.get("analise") or {}).get("concorrencia") or [])
        # substitui análise anterior da mesma empresa, se houver
        lista = [c for c in lista if c.get("empresa") != analise.get("empresa")]
        lista.append(analise)
        resp = requests.patch(
            f"{url}/api/processos/{processo_id}",
            headers=headers,
            json={"seVersao": doc.get("versao"), "analisePatch": {"concorrencia": lista}},
            timeout=15,
        )
        if resp.status_code == 409:
            continue  # outra pessoa salvou nesse meio-tempo; relê e tenta de novo
        resp.raise_for_status()
        return resp.json()
    raise ErroPainel("Conflito de versão persistente ao salvar no Painel — tente novamente.")


def exigencias_tecnicas(processo: dict) -> list[dict]:
    """Exigências de habilitação técnica do processo (para a análise de
    atestados). Se não houver nenhuma, devolve todas as exigências."""
    todas = processo.get("exigencias") or []
    tecnicas = [e for e in todas if e.get("categoria") == "Habilitação técnica"]
    return tecnicas or todas
