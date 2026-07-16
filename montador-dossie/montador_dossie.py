#!/usr/bin/env python3
"""
Montador de Dossie SINAPE - Painel + SharePoint -> ZIP
=========================================================

Fluxo (v2 - pos-leitura do edital):
  1. Busca o processo no Painel Sinape (GET /api/processos/<id>), que ja
     contem as exigencias do edital (exigencias[].categoria) e o link da
     pasta desse processo no SharePoint (analise.geral_pasta_sharepoint).
  2. Para cada categoria de exigencia PRESENTE naquele processo, consulta
     biblioteca.json para saber a subpasta padrao (dentro da pasta do
     processo) onde a equipe ja deposita a documentacao pronta.
  3. Baixa os arquivos binarios reais dessa subpasta via Microsoft Graph
     API (app-only / client credentials). Arquivos acima do limite de
     tamanho NAO sao baixados automaticamente - ficam listados no
     checklist com o link, para decisao manual.
  4. Organiza tudo em pastas letradas (A, B, C...) e gera um CHECKLIST.txt.
  5. Compacta em .zip.

Este script NAO decide o que e exigido - isso ja foi decidido pela leitura
do edital, registrada no Painel. Ele so organiza o que ja esta pronto no
SharePoint.

Configuracao necessaria (config.json ou variaveis de ambiente):
    TENANT_ID, CLIENT_ID, CLIENT_SECRET   - app registrado no Azure AD (Graph API)
    PAINEL_BASE_URL, PAINEL_TOKEN         - API do Painel Sinape
"""

import os
import sys
import json
import argparse
import logging
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse, unquote

import requests
import msal

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s", datefmt="%H:%M:%S")
log = logging.getLogger("montador_dossie")

GRAPH_BASE = "https://graph.microsoft.com/v1.0"
GRAPH_SCOPE = ["https://graph.microsoft.com/.default"]
LIMITE_MB_PADRAO = 20


# ---------------------------------------------------------------------------
# Configuracao
# ---------------------------------------------------------------------------

def carregar_config(caminho_config: Optional[str]) -> dict:
    cfg = {}
    if caminho_config and Path(caminho_config).exists():
        with open(caminho_config, "r", encoding="utf-8") as f:
            cfg = json.load(f)

    chaves = ["TENANT_ID", "CLIENT_ID", "CLIENT_SECRET", "PAINEL_BASE_URL", "PAINEL_TOKEN"]
    for chave in chaves:
        if os.environ.get(chave):
            cfg[chave] = os.environ[chave]

    faltando = [k for k in chaves if not cfg.get(k)]
    if faltando:
        raise SystemExit(
            f"Configuracao incompleta. Faltando: {', '.join(faltando)}. "
            f"Preencha config.json (veja config.exemplo.json) ou defina as variaveis de ambiente."
        )
    cfg.setdefault("TAMANHO_MAX_MB", LIMITE_MB_PADRAO)
    return cfg


# ---------------------------------------------------------------------------
# Painel Sinape - busca do processo
# ---------------------------------------------------------------------------

def buscar_processo(cfg: dict, processo_id: str) -> dict:
    url = f"{cfg['PAINEL_BASE_URL'].rstrip('/')}/api/processos/{processo_id}"
    resp = requests.get(url, headers={"x-sinape-token": cfg["PAINEL_TOKEN"]}, timeout=15)
    if resp.status_code == 404:
        raise SystemExit(f"Processo '{processo_id}' nao encontrado no Painel Sinape.")
    resp.raise_for_status()
    return resp.json()


def categorias_exigidas(processo: dict) -> list:
    cats = {e.get("categoria") for e in processo.get("exigencias", []) if e.get("categoria")}
    return sorted(cats)


def parse_pasta_sharepoint(url_pasta: str):
    """Extrai (hostname, site_path, caminho_relativo_ao_drive) a partir do
    link da pasta do processo (analise.geral_pasta_sharepoint), ex:
    https://tisinape.sharepoint.com/sites/sinape.comercial/Documentos/2 - LICITACAO/.../<pasta do processo>
    """
    if not url_pasta:
        raise SystemExit(
            "Este processo nao tem 'Pasta do dossie no SharePoint' preenchida no Painel "
            "(campo geral_pasta_sharepoint). Preencha no painel antes de rodar o montador."
        )
    partes = urlparse(url_pasta)
    hostname = partes.netloc
    caminho = unquote(partes.path)
    segmentos = caminho.split("/")
    if len(segmentos) < 3 or segmentos[1] != "sites":
        raise SystemExit(f"Link de pasta do SharePoint em formato inesperado: {url_pasta}")
    site_path = "/" + segmentos[1] + "/" + segmentos[2]

    marcador = "/Documentos/"
    idx = caminho.find(marcador)
    if idx == -1:
        raise SystemExit(f"Nao encontrei '/Documentos/' no link da pasta: {url_pasta}")
    caminho_relativo = caminho[idx + len(marcador):]
    return hostname, site_path, caminho_relativo


# ---------------------------------------------------------------------------
# Autenticacao e cliente Graph (igual ao ponto de partida original)
# ---------------------------------------------------------------------------

def obter_token(cfg: dict) -> str:
    authority = f"https://login.microsoftonline.com/{cfg['TENANT_ID']}"
    app = msal.ConfidentialClientApplication(
        client_id=cfg["CLIENT_ID"], client_credential=cfg["CLIENT_SECRET"], authority=authority,
    )
    resultado = app.acquire_token_for_client(scopes=GRAPH_SCOPE)
    if "access_token" not in resultado:
        raise SystemExit(f"Falha ao autenticar no Graph API: {resultado.get('error_description', resultado)}")
    log.info("Autenticado no Microsoft Graph com sucesso.")
    return resultado["access_token"]


class GraphClient:
    def __init__(self, token: str):
        self.session = requests.Session()
        self.session.headers.update({"Authorization": f"Bearer {token}"})

    def get(self, url: str, **kwargs) -> dict:
        for tentativa in range(4):
            resp = self.session.get(url, **kwargs)
            if resp.status_code == 429:
                import time
                time.sleep(int(resp.headers.get("Retry-After", 5)))
                continue
            if resp.status_code >= 500:
                import time
                time.sleep(2 * (tentativa + 1))
                continue
            resp.raise_for_status()
            return resp.json() if resp.content else {}
        raise RuntimeError(f"Falha persistente ao chamar {url}")

    def get_binario(self, url: str) -> bytes:
        resp = self.session.get(url)
        resp.raise_for_status()
        return resp.content


def obter_site_id(gc: GraphClient, hostname: str, site_path: str) -> str:
    dados = gc.get(f"{GRAPH_BASE}/sites/{hostname}:{site_path}")
    return dados["id"]


def obter_drive_id(gc: GraphClient, site_id: str, nome_biblioteca: str = "Documentos") -> str:
    dados = gc.get(f"{GRAPH_BASE}/sites/{site_id}/drives")
    for drive in dados.get("value", []):
        if drive["name"].lower() == nome_biblioteca.lower():
            return drive["id"]
    raise SystemExit(f"Biblioteca '{nome_biblioteca}' nao encontrada no site.")


def listar_itens_pasta(gc: GraphClient, drive_id: str, caminho_pasta: str) -> list:
    caminho_codificado = requests.utils.quote(caminho_pasta)
    url = f"{GRAPH_BASE}/drives/{drive_id}/root:/{caminho_codificado}:/children"
    itens = []
    while url:
        dados = gc.get(url)
        itens.extend(dados.get("value", []))
        url = dados.get("@odata.nextLink")
    return itens


def listar_recursivo(gc: GraphClient, drive_id: str, caminho_pasta: str) -> list:
    resultado = []
    fila = [caminho_pasta]
    while fila:
        pasta_atual = fila.pop()
        itens = listar_itens_pasta(gc, drive_id, pasta_atual)
        for item in itens:
            if "folder" in item:
                fila.append(f"{pasta_atual}/{item['name']}")
            else:
                item["_caminho_pasta"] = pasta_atual
                resultado.append(item)
    return resultado


def baixar_arquivo(gc: GraphClient, drive_id: str, item_id: str, destino: Path) -> None:
    conteudo = gc.get_binario(f"{GRAPH_BASE}/drives/{drive_id}/items/{item_id}/content")
    destino.parent.mkdir(parents=True, exist_ok=True)
    destino.write_bytes(conteudo)
    log.info(f"Baixado: {destino.name} ({len(conteudo)/1024:.0f} KB)")


# ---------------------------------------------------------------------------
# Orquestracao principal
# ---------------------------------------------------------------------------

def montar_dossie_por_processo(cfg: dict, biblioteca: dict, processo_id: str, saida_dir: Path) -> Path:
    processo = buscar_processo(cfg, processo_id)
    nome_processo = processo.get("nome") or processo_id
    pasta_url = (processo.get("analise") or {}).get("geral_pasta_sharepoint")
    hostname, site_path, caminho_base = parse_pasta_sharepoint(pasta_url)

    token = obter_token(cfg)
    gc = GraphClient(token)
    site_id = obter_site_id(gc, hostname, site_path)
    drive_id = obter_drive_id(gc, site_id)

    mapa_categoria = {c["categoria_painel"]: c for c in biblioteca["categorias"]}
    limite_bytes = int(cfg.get("TAMANHO_MAX_MB", LIMITE_MB_PADRAO)) * 1024 * 1024

    saida_dir.mkdir(parents=True, exist_ok=True)
    checklist = [
        f"CHECKLIST DE MONTAGEM - {nome_processo}",
        f"Processo: {processo_id}",
        "=" * 70,
        "",
    ]

    categorias = categorias_exigidas(processo)
    if not categorias:
        checklist.append("Nenhuma exigencia com categoria encontrada neste processo no Painel.")

    for categoria in categorias:
        entry = mapa_categoria.get(categoria)
        if not entry or not entry.get("subpasta_relativa"):
            checklist.append(f"[VERIFICAR MANUALMENTE] {categoria}: sem pasta padrao mapeada em biblioteca.json")
            continue

        letra = entry.get("letra_zip") or "X"
        pasta_local = saida_dir / f"{letra} - {categoria}"
        caminho_sp = f"{caminho_base}/{entry['subpasta_relativa']}"

        try:
            arquivos = listar_recursivo(gc, drive_id, caminho_sp)
        except requests.HTTPError as e:
            checklist.append(f"[ERRO] {categoria}: nao foi possivel acessar '{caminho_sp}' ({e})")
            continue

        if not arquivos:
            checklist.append(f"[FALTANDO] {categoria}: nenhum arquivo encontrado em '{caminho_sp}'")
            continue

        pequenos = [a for a in arquivos if a.get("size", 0) <= limite_bytes]
        grandes = [a for a in arquivos if a.get("size", 0) > limite_bytes]

        for arq in pequenos:
            destino = pasta_local / arq["name"]
            baixar_arquivo(gc, drive_id, arq["id"], destino)

        checklist.append(f"[OK] {categoria}: {len(pequenos)} arquivo(s) baixado(s) de '{caminho_sp}'")
        for arq in grandes:
            tamanho_mb = arq.get("size", 0) / (1024 * 1024)
            link = arq.get("webUrl", "")
            checklist.append(
                f"  [GRANDE DEMAIS - NAO BAIXADO] {arq['name']} ({tamanho_mb:.0f} MB) - anexar manualmente: {link}"
            )

    checklist_path = saida_dir / "CHECKLIST.txt"
    checklist_path.write_text("\n".join(checklist), encoding="utf-8")
    log.info(f"Checklist gerado em {checklist_path}")

    zip_destino = saida_dir.parent / f"{saida_dir.name}.zip"
    compactar_dossie(saida_dir, zip_destino)
    return zip_destino


def compactar_dossie(saida_dir: Path, zip_destino: Path) -> None:
    import zipfile
    if zip_destino.exists():
        zip_destino.unlink()
    with zipfile.ZipFile(zip_destino, "w", zipfile.ZIP_DEFLATED) as zf:
        for arquivo in saida_dir.rglob("*"):
            if arquivo.is_file():
                zf.write(arquivo, arquivo.relative_to(saida_dir.parent))
    log.info(f"Dossie compactado em: {zip_destino}")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Montador de Dossie SINAPE (Painel + SharePoint)")
    parser.add_argument("--processo-id", required=True, help="Id do processo no Painel Sinape")
    parser.add_argument("--config", default="config.json")
    parser.add_argument("--biblioteca", default="biblioteca.json")
    parser.add_argument("--saida", default="./dossies")
    args = parser.parse_args()

    cfg = carregar_config(args.config)
    with open(args.biblioteca, "r", encoding="utf-8") as f:
        biblioteca = json.load(f)

    saida_dir = Path(args.saida) / args.processo_id
    zip_destino = montar_dossie_por_processo(cfg, biblioteca, args.processo_id, saida_dir)

    print(f"\nPronto! Dossie disponivel em: {zip_destino}")
    print(f"Confira o CHECKLIST.txt dentro de {saida_dir} antes de enviar.")


if __name__ == "__main__":
    main()
