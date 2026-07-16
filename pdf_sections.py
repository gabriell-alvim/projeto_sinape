# -*- coding: utf-8 -*-
"""
Identifica seções em PDFs de edital/TR a partir de títulos em negrito e CAPS LOCK.

Usa pdfplumber para ler caracteres com nome da fonte (negrito) e montar títulos
por linha. Cada seção recebe o intervalo de páginas até o início da próxima —
útil para enviar só os trechos relevantes à IA e economizar tokens.
"""

from __future__ import annotations

import logging
import re
from io import BytesIO
from pathlib import Path
from typing import BinaryIO, Union

import pdfplumber

log = logging.getLogger("datasin.pdf_sections")

PdfSource = Union[str, Path, bytes, BinaryIO]

MIN_TITULO_LEN = 4
MIN_CAPS_RATIO = 0.8
_TOLERANCIA_LINHA = 3


def configurar_log(debug: bool = False) -> None:
    """Ativa logs no stderr. Com debug=True, mostra candidatos rejeitados e fontes."""
    nivel = logging.DEBUG if debug else logging.INFO
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter(
        "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    ))
    log.handlers.clear()
    log.addHandler(handler)
    log.setLevel(nivel)
    log.propagate = False


def _abrir_pdf(fonte: PdfSource):
    if isinstance(fonte, (str, Path)):
        caminho = Path(fonte)
        log.debug("Abrindo PDF: %s (%s bytes)", caminho, caminho.stat().st_size)
        return pdfplumber.open(fonte)
    if isinstance(fonte, bytes):
        log.debug("Abrindo PDF de bytes (%s bytes)", len(fonte))
        return pdfplumber.open(BytesIO(fonte))
    if hasattr(fonte, "read"):
        dados = fonte.read()
        if hasattr(fonte, "seek"):
            fonte.seek(0)
        log.debug("Abrindo PDF de stream (%s bytes)", len(dados))
        return pdfplumber.open(BytesIO(dados))
    raise TypeError("fonte deve ser caminho, bytes ou arquivo binário")


def _char_negrito(char: dict) -> bool:
    fonte = (char.get("fontname") or "").lower()
    return any(m in fonte for m in ("bold", "black", ",bd", "-bd", "semibold", "demi"))


def _texto_caps(texto: str) -> bool:
    letras = [c for c in texto if c.isalpha()]
    if len(letras) < 3:
        return False
    maiusculas = sum(1 for c in letras if c.isupper())
    return (maiusculas / len(letras)) >= MIN_CAPS_RATIO


def _ratio_caps(texto: str) -> float:
    letras = [c for c in texto if c.isalpha()]
    if not letras:
        return 0.0
    return sum(1 for c in letras if c.isupper()) / len(letras)


def _normalizar_titulo(texto: str) -> str:
    return re.sub(r"\s+", " ", (texto or "").strip())


def _motivo_rejeicao(texto: str) -> str:
    if not texto:
        return "vazio"
    if len(texto) < MIN_TITULO_LEN:
        return f"curto ({len(texto)} < {MIN_TITULO_LEN})"
    if re.fullmatch(r"[\d.\s\-–—]+", texto):
        return "só números/pontuação"
    if not _texto_caps(texto):
        return f"sem CAPS ({_ratio_caps(texto):.0%} < {MIN_CAPS_RATIO:.0%})"
    return "ok"


def _titulo_valido(texto: str) -> bool:
    return _motivo_rejeicao(texto) == "ok"


def _texto_da_linha(chars: list[dict]) -> str:
    return _normalizar_titulo("".join(c.get("text") or "" for c in chars))


def _fontes_da_linha(chars: list[dict]) -> set[str]:
    return {c.get("fontname") or "?" for c in chars}


def _agrupar_chars_em_linhas(chars: list[dict]) -> list[list[dict]]:
    if not chars:
        return []
    ordenados = sorted(chars, key=lambda c: (round(c["top"], 1), c.get("x0", 0)))
    linhas: list[list[dict]] = []
    linha_atual: list[dict] = []
    y_ref = None
    for char in ordenados:
        y = round(char["top"] / _TOLERANCIA_LINHA) * _TOLERANCIA_LINHA
        if y_ref is None or abs(y - y_ref) <= _TOLERANCIA_LINHA:
            linha_atual.append(char)
            y_ref = y if y_ref is None else y_ref
        else:
            if linha_atual:
                linhas.append(sorted(linha_atual, key=lambda c: c.get("x0", 0)))
            linha_atual = [char]
            y_ref = y
    if linha_atual:
        linhas.append(sorted(linha_atual, key=lambda c: c.get("x0", 0)))
    return linhas


def _negrito_da_linha(chars: list[dict]) -> str:
    partes = []
    buffer = []
    for char in chars:
        if _char_negrito(char):
            buffer.append(char.get("text") or "")
        elif buffer:
            parte = _normalizar_titulo("".join(buffer))
            if parte:
                partes.append(parte)
            buffer = []
    if buffer:
        parte = _normalizar_titulo("".join(buffer))
        if parte:
            partes.append(parte)
    return _normalizar_titulo(" ".join(partes))


def _detectar_titulos_por_pagina(pdf) -> list[dict]:
    achados = []
    for idx, pagina in enumerate(pdf.pages):
        pagina_num = idx + 1
        chars = pagina.chars or []
        linhas = _agrupar_chars_em_linhas(chars)
        log.debug(
            "Página %s: %s chars, %s linhas",
            pagina_num, len(chars), len(linhas),
        )

        fontes_pagina = sorted({c.get("fontname") or "?" for c in chars})
        if fontes_pagina:
            log.debug("Página %s fontes: %s", pagina_num, ", ".join(fontes_pagina[:12]))
            if len(fontes_pagina) > 12:
                log.debug("  … e mais %s fonte(s)", len(fontes_pagina) - 12)

        for linha in linhas:
            titulo = _negrito_da_linha(linha)
            if not titulo:
                continue
            linha_txt = _texto_da_linha(linha)
            fontes = _fontes_da_linha(linha)
            if _titulo_valido(titulo):
                log.info("SEÇÃO p.%s: %r", pagina_num, titulo)
                log.debug("  linha completa: %r | fontes: %s", linha_txt, fontes)
                achados.append({"titulo": titulo, "pagina": pagina_num})
            else:
                motivo = _motivo_rejeicao(titulo)
                log.debug(
                    "p.%s negrito rejeitado (%s): %r | linha: %r | fontes: %s",
                    pagina_num, motivo, titulo, linha_txt, fontes,
                )
    return achados


def _deduplicar_titulos_consecutivos(achados: list[dict]) -> list[dict]:
    if not achados:
        return []
    resultado = [achados[0]]
    for item in achados[1:]:
        ultimo = resultado[-1]
        if item["titulo"] == ultimo["titulo"] and item["pagina"] == ultimo["pagina"]:
            log.debug("Duplicata ignorada: %r p.%s", item["titulo"], item["pagina"])
            continue
        resultado.append(item)
    removidos = len(achados) - len(resultado)
    if removidos:
        log.debug("Deduplicação: %s → %s título(s)", len(achados), len(resultado))
    return resultado


def _montar_intervalos(achados: list[dict], total_paginas: int) -> list[dict]:
    """
    Cada seção vai da página do título (negrito + CAPS) até a página do
    próximo título — inclusive. A última seção vai até o fim do documento.
    """
    if not achados:
        return []

    secoes = []
    for i, item in enumerate(achados):
        pagina_inicio = item["pagina"]
        if i + 1 < len(achados):
            pagina_fim = achados[i + 1]["pagina"]
        else:
            pagina_fim = total_paginas
        paginas = list(range(pagina_inicio, pagina_fim + 1))
        secoes.append({
            "titulo": item["titulo"],
            "pagina_inicio": pagina_inicio,
            "pagina_fim": pagina_fim,
            "paginas": paginas,
        })
        log.info(
            "Intervalo %r: páginas %s–%s (%s pág.) → próximo título em p.%s",
            item["titulo"],
            pagina_inicio,
            pagina_fim,
            len(paginas),
            achados[i + 1]["pagina"] if i + 1 < len(achados) else "—",
        )
    return secoes


def _indice_por_titulo(secoes: list[dict]) -> dict:
    indice = {}
    for sec in secoes:
        chave = sec["titulo"]
        if chave in indice:
            chave = f'{chave} (p. {sec["pagina_inicio"]})'
            log.debug("Título duplicado no índice, chave: %r", chave)
        indice[chave] = {
            "pagina_inicio": sec["pagina_inicio"],
            "pagina_fim": sec["pagina_fim"],
            "paginas": sec["paginas"],
        }
    return indice


def analisar_pdf_secoes(fonte: PdfSource, nome_arquivo: str = "", debug: bool = False) -> dict:
    """
    Analisa um PDF e devolve seções detectadas por títulos negrito + CAPS.

    Retorno:
        {
          "arquivo": "...",
          "total_paginas": N,
          "secoes": [{titulo, pagina_inicio, pagina_fim, paginas}, ...],
          "indice": {titulo: {pagina_inicio, pagina_fim, paginas}, ...}
        }
    """
    if debug and not log.handlers:
        configurar_log(debug=True)
    elif debug:
        log.setLevel(logging.DEBUG)

    log.info("Iniciando análise: %s", nome_arquivo or "(sem nome)")
    with _abrir_pdf(fonte) as pdf:
        total = len(pdf.pages)
        log.info("Total de páginas: %s", total)
        brutos = _detectar_titulos_por_pagina(pdf)
        log.info("Títulos brutos detectados: %s", len(brutos))
        achados = _deduplicar_titulos_consecutivos(brutos)
        secoes = _montar_intervalos(achados, total)
        log.info("Seções finais: %s", len(secoes))
        resultado = {
            "arquivo": nome_arquivo or "",
            "total_paginas": total,
            "secoes": secoes,
            "indice": _indice_por_titulo(secoes),
        }
        return resultado


def extrair_texto_paginas(fonte: PdfSource, paginas: list[int]) -> str:
    """Extrai texto plano das páginas indicadas (1-based). Para uso futuro com IA."""
    if not paginas:
        return ""
    with _abrir_pdf(fonte) as pdf:
        partes = []
        for num in sorted(set(paginas)):
            if num < 1 or num > len(pdf.pages):
                continue
            texto = (pdf.pages[num - 1].extract_text() or "").strip()
            if texto:
                partes.append(f"--- Página {num} ---\n{texto}")
        return "\n\n".join(partes)
