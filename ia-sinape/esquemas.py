# -*- coding: utf-8 -*-
"""Esquemas Pydantic das saídas estruturadas da IA.

Todos os modelos usam extra="forbid" (vira additionalProperties: false no
JSON Schema) e só campos obrigatórios — requisitos dos structured outputs
da API da Anthropic. Campos que podem não existir no documento usam string
vazia ou "indeterminado" em vez de null, seguindo a convenção do Painel.

Nota (desvio registrado da ARQUITETURA.md §4): citations nativas da API são
incompatíveis com structured outputs, então a rastreabilidade de página vem
como campo do próprio schema ("paginas"), preenchido pelo modelo.
"""

from typing import Literal

from pydantic import BaseModel, ConfigDict


class _Base(BaseModel):
    model_config = ConfigDict(extra="forbid")


# ---------------------------------------------------------------------------
# C3 — Análise de atestados da concorrência (Fase 4)
# ---------------------------------------------------------------------------

class Atestado(_Base):
    objeto: str                 # o que a obra/serviço atestado envolve
    contratante_emissor: str    # órgão/empresa que emitiu o atestado
    periodo: str                # período de execução, como está no documento
    quantitativos: list[str]    # ex: "412 controladores semafóricos instalados"
    possui_cat: Literal["sim", "nao", "nao_identificado"]
    paginas: str                # páginas do PDF de onde a informação veio
    observacoes: str


class AderenciaExigencia(_Base):
    exigencia: str              # texto da exigência técnica do edital
    situacao: Literal["atende", "atende_parcialmente", "nao_atende", "indeterminado"]
    evidencia: str              # o que no atestado sustenta a conclusão
    paginas: str


class AnaliseConcorrente(_Base):
    empresa: str
    cnpj: str                   # "" se não aparecer nos documentos
    resumo: str                 # 2-4 frases: porte, experiência, perfil de obra
    atestados: list[Atestado]
    aderencia_exigencias: list[AderenciaExigencia]
    pontos_fortes: list[str]
    pontos_fracos: list[str]
    indicios_para_impugnacao: list[str]   # possíveis falhas formais nos atestados
    conferir_manualmente: list[str]       # trechos ilegíveis/ambíguos que pedem olho humano


# ---------------------------------------------------------------------------
# C2 — Conferência de dossiê (Fase 3)
# ---------------------------------------------------------------------------

class ItemConferencia(_Base):
    exigencia: str
    categoria: str              # categoria da exigência no Painel
    situacao: Literal["coberta", "parcial", "ausente", "indeterminado"]
    justificativa: str          # qual item do checklist cobre (ou por que não)


class ParecerDossie(_Base):
    resumo: str
    apto_para_envio: Literal["sim", "com_ressalvas", "nao"]
    itens: list[ItemConferencia]
    pendencias: list[str]       # ações objetivas antes de enviar a habilitação


def schema_json(modelo: type[BaseModel]) -> dict:
    """JSON Schema no formato aceito por output_config.format."""
    return modelo.model_json_schema()
