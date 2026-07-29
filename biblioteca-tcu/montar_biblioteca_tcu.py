# -*- coding: utf-8 -*-
"""Converte o manual "Licitações e Contratos" do TCU (baixado da API REST do
site oficial) em arquivos de texto por seção + um índice curado.

O índice marca cada seção como nucleo / complementar / fora, para o Sinki
carregar só o que interessa a uma empresa LICITANTE de sinalização viária —
o manual inteiro tem ~2,5 milhões de caracteres e mandar isso pra IA a cada
pergunta seria caro e inútil."""
import html
import json
import os
import re
import sys

BASE = os.path.dirname(os.path.abspath(__file__))
RAW = os.path.join(BASE, "tcu_raw")
DESTINO = sys.argv[1] if len(sys.argv) > 1 else os.path.join(BASE, "biblioteca_tcu")

# ── classificação de escopo ────────────────────────────────────────────────
# nucleo       = usado no dia a dia; bate direto com campos do Painel
# complementar = fundamenta impugnação/recurso, mesmo sendo "lado do órgão"
# fora         = governança interna do órgão, dispensas específicas etc.
NUCLEO = [
    "5.1.1",                                   # impugnação e esclarecimento
    "5.2", "5.2.1",                            # propostas, garantia de proposta
    "5.3",                                     # lances
    "5.4", "5.4.1", "5.4.1.1", "5.4.1.2",      # julgamento, inexequibilidade, POC
    "5.4.2", "5.4.3", "5.4.4",
    "5.5", "5.5.1", "5.5.2", "5.5.3", "5.5.4", # habilitação (o coração)
    "5.6",                                     # recurso
    "5.7",                                     # encerramento
    "5.8",                                     # sanções ao licitante
    "5.9.4",                                   # registro de preços (SRP)
    "5.11.2",                                  # garantia contratual
    "5.11.6",                                  # convocação para contratar
    "4.5.2", "4.5.2.1", "4.5.2.2", "4.5.2.4", "4.5.2.5",  # consórcio, ME/EPP...
    "6.1.1",                                   # subcontratação
]
COMPLEMENTAR = [
    "3.2", "3.4", "3.4.1", "3.4.2", "3.4.4", "3.5", "3.6", "3.6.1", "3.6.2",
    "4.1.4", "4.1.8",
    "4.3", "4.3.1", "4.3.4", "4.3.5", "4.3.7", "4.3.8",
    "4.3.9", "4.3.9.1", "4.3.9.2", "4.3.9.3",
    "4.4", "4.4.1", "4.4.1.1", "4.4.1.2", "4.4.1.3", "4.4.1.4",
    "4.4.3", "4.4.3.6", "4.4.4",
    "4.5", "4.5.1", "4.5.3", "4.5.4", "4.5.5", "4.5.6",
    "5.1", "5.9", "5.9.2", "5.10.2.2",
    "5.11", "5.11.1", "5.11.3", "5.11.5",
    "6.1", "6.1.7", "6.1.8", "6.1.9",
    "6.2", "6.2.1", "6.2.2", "6.2.2.1", "6.2.2.1.1", "6.2.2.1.2", "6.2.2.1.3",
    "6.3",
]

# termos que ajudam o Sinki a achar a seção certa a partir da pergunta
PALAVRAS = {
    "5.5.2": ["atestado", "capacidade técnica", "CAT", "CREA", "CAU", "acervo",
              "parcela de maior relevância", "PMR", "quantitativo mínimo",
              "responsável técnico", "vínculo empregatício", "vistoria",
              "visita técnica", "somatório de atestados", "qualificação técnica"],
    "5.5.4": ["índice", "liquidez corrente", "liquidez geral", "solvência geral",
              "capital social", "patrimônio líquido", "balanço patrimonial",
              "capital circulante líquido", "CCL", "recuperação judicial",
              "falência", "qualificação econômico-financeira"],
    "5.5.3": ["regularidade fiscal", "certidão", "CND", "FGTS", "INSS",
              "trabalhista", "CNDT", "seguridade social"],
    "5.5.1": ["contrato social", "estatuto", "objeto social", "habilitação jurídica",
              "registro comercial", "CNPJ"],
    "5.5":   ["habilitação", "inabilitação", "documentos de habilitação", "diligência"],
    "5.1.1": ["impugnação", "esclarecimento", "republicação do edital",
              "reabertura de prazo", "prazo para impugnar"],
    "5.6":   ["recurso", "intenção de recurso", "contrarrazões", "reconsideração",
              "efeito suspensivo", "preclusão"],
    "5.2.1": ["garantia de proposta", "pré-habilitação", "1%", "caução",
              "seguro-garantia", "fiança bancária"],
    "5.11.2": ["garantia contratual", "seguro-garantia", "5%", "10%",
               "retenção", "performance bond"],
    "5.4.1": ["inexequibilidade", "preço inexequível", "desclassificação",
              "aceitabilidade", "preço máximo", "sobrepreço", "diligência"],
    "5.4.1.2": ["amostra", "prova de conceito", "POC", "exame de conformidade",
                "demonstração"],
    "5.4.2": ["desempate", "critério de desempate", "sorteio"],
    "5.4.3": ["negociação", "contraproposta"],
    "5.4.4": ["garantia adicional", "proposta inexequível"],
    "4.5.2.2": ["consórcio", "vedação a consórcio", "empresa líder", "consorciada"],
    "4.5.2.4": ["ME", "EPP", "microempresa", "empresa de pequeno porte",
                "LC 123", "tratamento favorecido", "empate ficto"],
    "4.5.2.1": ["impedimento", "vedação de participar", "conflito de interesses",
                "inidoneidade", "sanção"],
    "4.5.2.5": ["margem de preferência", "produto nacional"],
    "5.8":   ["sanção", "penalidade", "multa", "impedimento de licitar",
              "declaração de inidoneidade", "advertência"],
    "5.9.4": ["registro de preços", "SRP", "ata de registro de preços", "carona",
              "adesão", "órgão participante", "intenção de registro de preços"],
    "6.1.1": ["subcontratação", "subcontratada", "cessão"],
    "4.4.1": ["regime de execução", "empreitada por preço unitário", "EPU",
              "empreitada por preço global", "EPG", "contratação integrada"],
    "4.3.7": ["medição", "critério de pagamento", "cronograma físico-financeiro"],
    "4.3.9.3": ["orçamento", "BDI", "custo", "encargos sociais", "SINAPI", "SICRO",
                "preço estimado", "composição de custos"],
    "4.5.6": ["orçamento sigiloso", "valor estimado sigiloso"],
    "6.2.2.1.2": ["reajuste", "data-base", "índice de reajuste", "IPCA", "INCC"],
    "6.2.2.1.1": ["reequilíbrio", "recomposição", "revisão", "álea extraordinária"],
    "5.7":   ["adjudicação", "homologação", "encerramento"],
    "5.11.6": ["convocação para contratar", "recusa em assinar", "prazo para assinar"],
}


def escopo_de(numero):
    if numero in NUCLEO:
        return "nucleo"
    if numero in COMPLEMENTAR:
        return "complementar"
    return "fora"


# ── conversão HTML → texto ─────────────────────────────────────────────────
def limpar(txt):
    txt = html.unescape(txt)
    txt = txt.replace(" ", " ").replace("​", "")
    txt = re.sub(r"[ \t]+", " ", txt)
    return txt.strip()


def tabela_para_texto(bloco):
    linhas = []
    for tr in re.findall(r"<tr[^>]*>(.*?)</tr>", bloco, re.S | re.I):
        celulas = [limpar(re.sub(r"<[^>]+>", " ", td))
                   for td in re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", tr, re.S | re.I)]
        celulas = [c for c in celulas if c]
        if celulas:
            linhas.append(" | ".join(celulas))
    return "\n".join(linhas)


def html_para_texto(bruto):
    # tabelas viram blocos de texto legíveis (a jurisprudência mora nelas)
    def _tab(m):
        return "\n\n" + tabela_para_texto(m.group(0)) + "\n\n"
    txt = re.sub(r"<table[^>]*>.*?</table>", _tab, bruto, flags=re.S | re.I)
    txt = re.sub(r"<button[^>]*>.*?</button>", "", txt, flags=re.S | re.I)
    txt = re.sub(r"<(script|style)[^>]*>.*?</\1>", "", txt, flags=re.S | re.I)
    txt = re.sub(r"</(p|div|li|h[1-6]|figure|tr)>", "\n\n", txt, flags=re.I)
    txt = re.sub(r"<br\s*/?>", "\n", txt, flags=re.I)
    txt = re.sub(r"<li[^>]*>", "- ", txt, flags=re.I)
    txt = re.sub(r"<[^>]+>", "", txt)
    txt = limpar(txt)
    txt = re.sub(r"\n{3,}", "\n\n", txt)
    return txt


# ── extração de acórdãos e súmulas ────────────────────────────────────────
RE_ACORDAO = re.compile(
    r"Ac[óo]rd[ãa]o\s+(\d{1,5})/(\d{4})[-–\s]*TCU?[-–\s]*"
    r"(Plen[áa]rio|Primeira C[âa]mara|Segunda C[âa]mara)?", re.I)
RE_ACORDAO2 = re.compile(r"Ac[óo]rd[ãa]o\s+(\d{1,5})/(\d{4})", re.I)
# o manual cita de várias formas: "Súmula 263", "Súmula TCU 263",
# "Súmula – TCU 263" (travessão) e "Súmula-TCU 263"
RE_SUMULA = re.compile(r"S[úu]mula[\s–—-]*(?:TCU)?[\s–—-]*(\d{1,3})", re.I)


def extrair_referencias(texto):
    acs = set()
    for m in RE_ACORDAO2.finditer(texto):
        acs.add(f"{int(m.group(1))}/{m.group(2)}")
    sums = {int(m.group(1)) for m in RE_SUMULA.finditer(texto)}
    return sorted(acs, key=lambda a: (int(a.split("/")[1]), int(a.split("/")[0]))), sorted(sums)


def numero_de(titulo, slug):
    m = re.match(r"^\s*(\d+(?:\.\d+)*)\.?\s", titulo)
    if m:
        return m.group(1)
    m = re.match(r"^((?:\d+-)+)", slug)
    if m:
        return ".".join(m.group(1).strip("-").split("-"))
    return None


def main():
    posts = []
    for p in (1, 2, 3):
        caminho = os.path.join(RAW, f"posts_{p}.json")
        with open(caminho, encoding="utf-8") as f:
            posts += json.load(f)

    os.makedirs(os.path.join(DESTINO, "secoes"), exist_ok=True)

    entradas = []
    for p in posts:
        titulo = limpar(re.sub(r"<[^>]+>", "", p["title"]["rendered"]))
        corpo = html_para_texto(p["content"]["rendered"])
        numero = numero_de(titulo, p["slug"])

        # alguns posts têm título vazio no WP; tenta achar o número no corpo
        if not titulo or not numero:
            m = re.match(r"^\s*(\d+(?:\.\d+)*)\.\s*(.+)", corpo)
            if m:
                numero = numero or m.group(1)
                titulo = titulo or f"{m.group(1)}. {m.group(2)[:80]}"

        if not numero or len(corpo) < 200:
            continue  # páginas de apoio/vazias do WordPress

        titulo_limpo = re.sub(r"^\s*\d+(?:\.\d+)*\.?\s*", "", titulo).strip()
        acordaos, sumulas = extrair_referencias(corpo)
        escopo = escopo_de(numero)
        arquivo = f"{numero}-{re.sub(r'[^a-z0-9]+', '-', titulo_limpo.lower())[:60].strip('-')}.txt"

        cabecalho = (
            f"{numero}. {titulo_limpo}\n"
            f"Fonte: TCU — Licitações e Contratos: Orientações e Jurisprudência (5ª ed.)\n"
            f"URL: https://licitacoesecontratos.tcu.gov.br/{p['slug']}/\n"
            f"{'=' * 70}\n\n"
        )
        with open(os.path.join(DESTINO, "secoes", arquivo), "w", encoding="utf-8") as f:
            f.write(cabecalho + corpo + "\n")

        entradas.append({
            "numero": numero,
            "titulo": titulo_limpo,
            "arquivo": arquivo,
            "escopo": escopo,
            "caracteres": len(corpo),
            "acordaos": acordaos,
            "sumulas": sumulas,
            "palavras_chave": PALAVRAS.get(numero, []),
            "url": f"https://licitacoesecontratos.tcu.gov.br/{p['slug']}/",
        })

    entradas.sort(key=lambda e: [int(x) for x in e["numero"].split(".")])

    indice = {
        "fonte": "TCU — Licitações e Contratos: Orientações e Jurisprudência do TCU (5ª edição)",
        "url_base": "https://licitacoesecontratos.tcu.gov.br/",
        "atualizado_em_origem": "2025-08-29",
        "observacao": (
            "Vale só para contratações PÚBLICAS (Lei 14.133/2021). Em processo "
            "privado (concessionária, RFQ, carta-convite) não se cita TCU — vale "
            "o documento do contratante."
        ),
        "escopos": {
            "nucleo": "uso diário; bate direto com os campos do Painel",
            "complementar": "fundamenta impugnação/recurso, consultar quando o tema aparecer",
            "fora": "governança interna do órgão, dispensas específicas — não consultar",
        },
        "secoes": entradas,
    }
    with open(os.path.join(DESTINO, "indice.json"), "w", encoding="utf-8") as f:
        json.dump(indice, f, ensure_ascii=False, indent=1)

    # relatório
    por_escopo = {}
    for e in entradas:
        por_escopo.setdefault(e["escopo"], []).append(e)
    print(f"{len(entradas)} seções convertidas em {DESTINO}")
    for esc in ("nucleo", "complementar", "fora"):
        lst = por_escopo.get(esc, [])
        chars = sum(x["caracteres"] for x in lst)
        print(f"  {esc:13} {len(lst):3} seções  {chars:9,} caracteres")
    todos_ac = {a for e in entradas for a in e["acordaos"]}
    ac_uteis = {a for e in entradas if e["escopo"] != "fora" for a in e["acordaos"]}
    sum_uteis = {s for e in entradas if e["escopo"] != "fora" for s in e["sumulas"]}
    print(f"\nacórdãos distintos: {len(todos_ac)} no total, {len(ac_uteis)} dentro do escopo")
    print(f"súmulas dentro do escopo: {len(sum_uteis)} -> {sorted(sum_uteis)}")


if __name__ == "__main__":
    main()
