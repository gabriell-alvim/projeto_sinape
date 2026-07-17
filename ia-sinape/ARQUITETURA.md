# IA do Sistema SINAPE — Arquitetura

> Documento de arquitetura inicial. Nada aqui foi implementado ainda; nada sobe
> para o git por enquanto. Ver `HANDOFF.md` para o estado exato e próximos passos.

## 1. O que é "a IA" neste sistema

Hoje a inteligência do sistema é **manual**: a equipe copia o prompt do Painel
("🤖 Copiar prompt p/ IA"), cola numa conversa com o Claude junto com o edital,
e importa o JSON de volta. A proposta é transformar isso num **serviço próprio
(ia-service)** que os três sistemas chamam via API, sem ninguém colar prompt na mão.

A IA terá três capacidades, uma por fase do sistema:

| # | Capacidade | Fase | Estado |
|---|---|---|---|
| C1 | **Leitura de edital** → devolve o JSON do processo (mesmo contrato do `PROMPT_PARA_IA.md` / `exemplo_processo_ia.json`) | Fase 1 (Painel) | Contrato já existe e é usado manualmente — automatizar |
| C2 | **Conferência de dossiê** → antes de zipar, cruza o CHECKLIST do Montador com as `exigencias` do Painel e aponta lacunas em linguagem natural | Fase 3 (Montador) | Novo |
| C3 | **Análise de atestados da concorrência** → lê PDFs de atestados de capacidade técnica dos concorrentes e devolve resumo estruturado por empresa | Fase 4 | Novo (prioridade do usuário) |

## 2. Arquitetura geral

```
                         ┌──────────────────────────────┐
  Painel Sinape (Flask)──┤                              │
  Montador (server.py) ──┤   ia-service (FastAPI/Flask) │──► Claude API (Anthropic SDK python)
  Examinador (agente) ───┤   porta local 5006           │      modelo padrão: claude-opus-4-8
                         └──────────┬───────────────────┘
                                    │
                              SharePoint (Graph API)
                              [reusa GraphClient do montador_dossie.py
                               para baixar os PDFs binários]
```

Decisões:

- **Um único serviço Python** (`ia-service`), separado do Painel, com um endpoint
  por capacidade. Mesmo padrão do Montador: roda local agora, sobe para a AWS
  depois junto com o resto.
- **SDK oficial `anthropic` (Python)** — nunca chamar a API do navegador
  (a chave ficaria exposta, mesmo problema do client secret do Graph).
- **Modelo padrão: `claude-opus-4-8`** com `thinking={"type": "adaptive"}`.
  Análise de atestado e leitura de edital são tarefas longas de raciocínio
  sobre documentos — não economizar em modelo aqui. `output_config.effort`:
  `"high"` como padrão.
- **PDFs entram como documento nativo** (`{"type": "document", "source":
  {"type": "base64", "media_type": "application/pdf", ...}}`) — o Claude lê o
  PDF real (inclusive escaneado), sem OCR próprio. Limites: 32 MB por request,
  100–600 páginas. Para lotes de atestados reutilizados, usar **Files API**
  (upload 1x, referencia por `file_id`).
- **Saída sempre estruturada** via `client.messages.parse()` com schema
  Pydantic (structured outputs) — elimina o passo frágil de "colar JSON e
  torcer para validar" que existe hoje no fluxo manual.
- **Batches API** para cargas em lote (ex: analisar atestados de todos os
  concorrentes de um pregão de uma vez) — 50% mais barato, sem pressa.
- **Prompt caching**: system prompt fixo por capacidade com
  `cache_control: {"type": "ephemeral"}` — os prompts são grandes (o contrato
  do Painel tem ~11 KB) e repetem a cada chamada.

## 3. Endpoints planejados do ia-service

| Endpoint | Entrada | Saída | Consumidor |
|---|---|---|---|
| `POST /analisar-edital` | PDFs do edital/anexos (upload ou link SharePoint) | JSON do processo (contrato do `PROMPT_PARA_IA.md`) — já pronto para `POST /api/processos` do Painel | Painel ("Importar da IA" vira 1 clique) |
| `POST /conferir-dossie` | `processo_id` | Parecer: exigência a exigência, o que o dossiê cobre/não cobre | Montador (antes de zipar) |
| `POST /analisar-atestados` | `processo_id` + lista de PDFs de atestados (ou pasta SharePoint) | Por empresa: obras executadas, quantitativos, órgãos emissores, CAT/ART, pontos fortes/fracos vs. exigência do edital | Painel (nova aba "Concorrência") |
| `GET /health` | — | ok | monitoramento |

Autenticação entre serviços: mesmo padrão do Painel (header com token compartilhado).

## 4. Fase 4 em detalhe (análise de atestados)

Pipeline por pregão:

1. Recebe `processo_id` → busca no Painel as `exigencias` de habilitação técnica
   (ex: "≥ 210 controladores", "12 meses de operação de central").
2. Baixa os PDFs dos atestados dos concorrentes (upload manual no início;
   depois, pasta padronizada no SharePoint via GraphClient).
3. Para cada empresa: 1 chamada com os PDFs dela + as exigências → schema
   Pydantic `AnaliseConcorrente` (empresa, CNPJ, atestados[], quantitativos
   comprovados, emissor, indícios de não-atendimento, score de aderência à
   exigência).
4. Consolida num comparativo (nós vs. cada concorrente, exigência a exigência)
   e grava no documento do processo no Painel via `PATCH` (`analisePatch` ou
   campo novo `concorrencia`), aparecendo para toda a equipe.
5. `citations: {enabled: true}` nos documentos → cada afirmação aponta a página
   do atestado de origem (importante se virar base para impugnação).

## 5. Configuração e segredos

`config.json` local (fora do git, mesmo padrão dos outros módulos):
`ANTHROPIC_API_KEY`, `PAINEL_BASE_URL`, `PAINEL_TOKEN`, e as credenciais Graph
(`TENANT_ID`/`CLIENT_ID`/`CLIENT_SECRET`) compartilhadas com o Montador.
A chave Anthropic o Gabriel cria em `platform.claude.com` (Console) — mesma
regra do Azure: eu não crio conta/chave por ele.

## 6. Ordem de implementação sugerida

1. Esqueleto do `ia-service` + `/health` + config (30 min de trabalho).
2. `/analisar-edital` — o contrato já existe e é validado em produção manual;
   é a vitória mais rápida e elimina o copiar/colar do dia a dia.
3. `/analisar-atestados` — Fase 4, com upload manual de PDFs primeiro;
   integração SharePoint depois.
4. `/conferir-dossie` — depende do Montador estar rodando com Graph API.
5. Botões no Painel chamando o serviço + campo `concorrencia` no processo.
