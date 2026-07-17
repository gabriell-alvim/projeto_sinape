# -*- coding: utf-8 -*-
"""Núcleo de chamadas ao Claude (SDK oficial anthropic).

Decisões (ver ARQUITETURA.md):
- Modelo padrão claude-opus-4-8, thinking adaptativo, effort "high".
- Sempre streaming + get_final_message(): evita timeout HTTP em análises
  longas de PDF sem precisar tratar evento a evento.
- PDFs entram como bloco "document" base64 (o Claude lê o PDF real,
  inclusive escaneado). Antes do bloco de texto, como manda a doc.
- Saída estruturada via output_config.format (JSON Schema gerado dos modelos
  Pydantic em esquemas.py) e validada de volta com Pydantic. Para o edital a
  saída é o contrato livre do Painel (chaves dinâmicas), então lá é JSON em
  texto + json.loads, igual ao fluxo manual que já roda em produção.
- System prompt fixo por capacidade com cache_control (prompt caching).
"""

import base64
import json
import re
from pathlib import Path

import anthropic

from config import BASE_DIR
from esquemas import AnaliseConcorrente, ParecerDossie, schema_json

# Limite prático de payload: a API aceita 32 MB por request e o base64
# infla ~33%, então limitamos a soma dos PDFs originais.
MAX_TOTAL_PDF_MB = 20
MAX_TOKENS_SAIDA = 64000


class ErroIA(Exception):
    """Erro de negócio da IA com mensagem própria para o usuário."""


def _prompt(nome: str) -> str:
    return (BASE_DIR / "prompts" / f"{nome}.md").read_text(encoding="utf-8")


def _blocos_pdf(arquivos: list[tuple[str, bytes]]) -> list[dict]:
    """arquivos: lista de (nome, conteudo). Valida tamanho e monta blocos."""
    total = sum(len(c) for _, c in arquivos)
    if total > MAX_TOTAL_PDF_MB * 1024 * 1024:
        raise ErroIA(
            f"PDFs somam {total / 1024 / 1024:.0f} MB — acima do limite de "
            f"{MAX_TOTAL_PDF_MB} MB por análise. Divida em chamadas menores."
        )
    blocos = []
    for nome, conteudo in arquivos:
        if not conteudo[:5].startswith(b"%PDF-"):
            raise ErroIA(f"'{nome}' não parece ser um PDF válido.")
        blocos.append({
            "type": "document",
            "source": {
                "type": "base64",
                "media_type": "application/pdf",
                "data": base64.standard_b64encode(conteudo).decode("ascii"),
            },
            "title": nome,
        })
    return blocos


def _chamar(cfg: dict, system: str, blocos_usuario: list[dict], schema: dict | None = None):
    """Uma chamada ao Claude. Devolve (texto, usage_dict)."""
    client = anthropic.Anthropic(api_key=cfg["ANTHROPIC_API_KEY"])

    output_config: dict = {"effort": cfg.get("CLAUDE_EFFORT", "high")}
    if schema is not None:
        output_config["format"] = {"type": "json_schema", "schema": schema}

    with client.messages.stream(
        model=cfg.get("CLAUDE_MODEL", "claude-opus-4-8"),
        max_tokens=MAX_TOKENS_SAIDA,
        thinking={"type": "adaptive"},
        output_config=output_config,
        system=[{
            "type": "text",
            "text": system,
            "cache_control": {"type": "ephemeral"},
        }],
        messages=[{"role": "user", "content": blocos_usuario}],
    ) as stream:
        msg = stream.get_final_message()

    if msg.stop_reason == "refusal":
        raise ErroIA("O modelo recusou a análise (política de segurança). "
                     "Confira se os PDFs são mesmo documentos de licitação.")
    if msg.stop_reason == "max_tokens":
        raise ErroIA("A resposta estourou o limite de tokens — divida os "
                     "documentos em chamadas menores.")

    texto = next((b.text for b in msg.content if b.type == "text"), "")
    usage = {
        "tokens_entrada": msg.usage.input_tokens,
        "tokens_saida": msg.usage.output_tokens,
        "cache_lido": msg.usage.cache_read_input_tokens,
        "cache_criado": msg.usage.cache_creation_input_tokens,
        "modelo": msg.model,
    }
    return texto, usage


def _json_do_texto(texto: str) -> dict:
    """json.loads tolerante a cercas de código (defesa, igual ao importador
    do Painel)."""
    limpo = texto.strip()
    limpo = re.sub(r"^```(?:json)?\s*", "", limpo)
    limpo = re.sub(r"\s*```$", "", limpo)
    try:
        return json.loads(limpo)
    except json.JSONDecodeError as e:
        raise ErroIA(f"A IA não devolveu JSON válido ({e}). Tente novamente.") from e


# ---------------------------------------------------------------------------
# C1 — Leitura de edital
# ---------------------------------------------------------------------------

def analisar_edital(cfg: dict, arquivos: list[tuple[str, bytes]]) -> tuple[dict, dict]:
    """Devolve (processo_json, usage). processo_json segue o contrato do
    Painel (PROMPT_PARA_IA.md V2) e está pronto para POST /api/processos."""
    blocos = _blocos_pdf(arquivos)
    blocos.append({"type": "text", "text": "Analise os documentos anexados e devolva o JSON."})
    texto, usage = _chamar(cfg, _prompt("analisar_edital"), blocos)
    processo = _json_do_texto(texto)

    faltando = [k for k in ("nome", "exigencias", "analise") if k not in processo]
    if faltando:
        raise ErroIA(f"JSON da IA veio sem campos essenciais: {', '.join(faltando)}.")
    processo.setdefault("origem", "ia")
    processo.setdefault("status", "em_analise")
    return processo, usage


# ---------------------------------------------------------------------------
# C3 — Análise de atestados da concorrência (Fase 4)
# ---------------------------------------------------------------------------

def analisar_atestados(cfg: dict, arquivos: list[tuple[str, bytes]],
                       exigencias: list[dict], empresa_dica: str = "") -> tuple[dict, dict]:
    """Analisa os atestados de UMA empresa concorrente contra as exigências
    técnicas do edital. Devolve (analise_validada, usage)."""
    blocos = _blocos_pdf(arquivos)
    contexto = {
        "exigencias_tecnicas_do_edital": exigencias,
        "empresa_analisada": empresa_dica or "identifique pelos documentos",
    }
    blocos.append({
        "type": "text",
        "text": "Exigências do edital e contexto:\n" + json.dumps(contexto, ensure_ascii=False, indent=2),
    })
    texto, usage = _chamar(cfg, _prompt("analisar_atestados"), blocos,
                           schema=schema_json(AnaliseConcorrente))
    analise = AnaliseConcorrente.model_validate_json(texto)
    return analise.model_dump(), usage


# ---------------------------------------------------------------------------
# C2 — Conferência de dossiê (Fase 3)
# ---------------------------------------------------------------------------

def conferir_dossie(cfg: dict, exigencias: list[dict], checklist_texto: str) -> tuple[dict, dict]:
    """Cruza exigências do Painel com o CHECKLIST.txt do Montador."""
    corpo = (
        "EXIGÊNCIAS DO EDITAL (JSON do Painel):\n"
        + json.dumps(exigencias, ensure_ascii=False, indent=2)
        + "\n\nCHECKLIST.txt DO MONTADOR:\n"
        + checklist_texto
    )
    texto, usage = _chamar(cfg, _prompt("conferir_dossie"),
                           [{"type": "text", "text": corpo}],
                           schema=schema_json(ParecerDossie))
    parecer = ParecerDossie.model_validate_json(texto)
    return parecer.model_dump(), usage
