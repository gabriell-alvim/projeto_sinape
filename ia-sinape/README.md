# ia-service — IA do Sistema SINAPE

Serviço HTTP local (porta 5006) com as capacidades de IA do sistema.
Ver `ARQUITETURA.md` para o desenho completo e `HANDOFF.md` para o estado.

## 1. Instalar

```
pip install -r requirements.txt
```

## 2. Configurar

Copie `config.exemplo.json` para `config.json` e preencha:

- `ANTHROPIC_API_KEY` — crie em **platform.claude.com** (Console da Anthropic
  → API Keys). **Nunca** versione no git (já está no `.gitignore`).
- `PAINEL_BASE_URL` / `PAINEL_TOKEN` — os mesmos do Painel Sinape. Opcionais:
  sem eles, os endpoints que falam com o Painel avisam o que falta.
- `IA_SERVICE_TOKEN` — opcional; se preenchido, toda chamada (exceto /health)
  exige o header `x-ia-token`.

## 3. Rodar

```
python servidor.py
```

## 4. Endpoints

### GET /health
Estado do serviço e o que está configurado.

### POST /analisar-edital  (C1 — Fase 1)
Substitui o copiar/colar do prompt do Painel. Envia os PDFs, recebe o JSON
do processo no contrato do Painel (mesmo `PROMPT_PARA_IA.md` V2 usado hoje).

```
curl -X POST http://localhost:5006/analisar-edital \
  -F "arquivos=@Edital.pdf" -F "arquivos=@TR.pdf" -F "arquivos=@Planilha.pdf" \
  -F "criar_no_painel=1"        # opcional: já cria o processo no Painel
```

### POST /analisar-atestados  (C3 — Fase 4)
Analisa os atestados de **uma** empresa concorrente por chamada, cruzando com
as exigências técnicas do edital. Saída estruturada e validada (schema).

```
curl -X POST http://localhost:5006/analisar-atestados \
  -F "arquivos=@atestado1.pdf" -F "arquivos=@atestado2.pdf" \
  -F "processo_id=pregao-90010-2026-sodf" \
  -F "empresa=Concorrente Ltda" \
  -F "salvar_no_painel=1"       # grava em analise.concorrencia do processo
```

Sem `processo_id`, passe as exigências direto: `-F 'exigencias=[{...}]'`.

### POST /conferir-dossie  (C2 — Fase 3)
Cruza as exigências do Painel com o CHECKLIST.txt do Montador antes de enviar.

```
curl -X POST http://localhost:5006/conferir-dossie \
  -H "content-type: application/json" \
  -d '{"processo_id": "...", "checklist_texto": "<conteúdo do CHECKLIST.txt>"}'
```

Toda resposta traz `uso` (tokens de entrada/saída e cache) para visibilidade
de custo.

## Decisões técnicas / desvios registrados

- Modelo `claude-opus-4-8`, thinking adaptativo, effort `high` (config).
- Streaming interno em toda chamada (análises longas não estouram timeout).
- PDFs vão como documento nativo (base64) — o Claude lê o PDF real, inclusive
  escaneado. Limite: 20 MB somados por análise.
- **Desvio da ARQUITETURA.md §4:** citations nativas são incompatíveis com
  structured outputs na API; a rastreabilidade de página virou campo do
  próprio schema (`paginas`), preenchido pelo modelo.
- Saída do edital é JSON livre (contrato do Painel tem chaves dinâmicas);
  atestados e conferência usam structured outputs + validação Pydantic.

## Limites conhecidos desta versão

- Upload manual de PDFs (integração SharePoint via GraphClient fica para
  depois do cadastro no Azure AD — mesmo bloqueio do Montador).
- Lotes grandes de concorrentes: uma chamada por empresa. A migração para a
  Batches API (50% mais barato) está prevista na arquitetura, não implementada.
- Recarregar config = reiniciar o servidor.
