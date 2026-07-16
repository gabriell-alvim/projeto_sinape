#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Teste local de detecção de seções em PDF — com logs de debug no terminal.

Uso:
  python3 test_pdf_secoes.py caminho/para/edital.pdf
  python3 test_pdf_secoes.py edital.pdf -o resultado.json
  PDF_DEBUG=1 python3 test_pdf_secoes.py edital.pdf   # via env (mesmo efeito)
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from pdf_sections import analisar_pdf_secoes, configurar_log


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Analisa seções (negrito + CAPS) em um PDF e imprime logs de debug.",
    )
    parser.add_argument(
        "pdf",
        type=Path,
        help="Caminho do arquivo PDF de entrada",
    )
    parser.add_argument(
        "-o", "--output",
        type=Path,
        help="Salva o JSON do resultado neste arquivo",
    )
    parser.add_argument(
        "-q", "--quiet",
        action="store_true",
        help="Só imprime o JSON final (sem logs)",
    )
    args = parser.parse_args()

    if not args.pdf.is_file():
        print(f"Arquivo não encontrado: {args.pdf}", file=sys.stderr)
        return 1
    if args.pdf.suffix.lower() != ".pdf":
        print(f"Aviso: extensão não é .pdf ({args.pdf.suffix})", file=sys.stderr)

    debug = not args.quiet
    if debug:
        configurar_log(debug=True)

    resultado = analisar_pdf_secoes(args.pdf, nome_arquivo=args.pdf.name, debug=debug)

    texto_json = json.dumps(resultado, ensure_ascii=False, indent=2)
    if args.output:
        args.output.write_text(texto_json, encoding="utf-8")
        if debug:
            print(f"\nJSON salvo em: {args.output.resolve()}", file=sys.stderr)
    else:
        print("\n─── RESULTADO JSON ───")
        print(texto_json)

    return 0


if __name__ == "__main__":
    env_debug = os.environ.get("PDF_DEBUG", "").lower() in ("1", "true", "yes")
    if env_debug and len(sys.argv) == 1:
        print("Uso: python3 test_pdf_secoes.py <arquivo.pdf>", file=sys.stderr)
        sys.exit(1)
    sys.exit(main())
