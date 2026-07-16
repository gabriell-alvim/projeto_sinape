# Datasin — Painel de Licitações

Painel colaborativo para análise de processos licitatórios (públicos e privados). A equipe preenche análise crítica, exigências do edital e checklist; os dados sincronizam em tempo real via API.

**Stack:** Flask + MongoDB + front em HTML/JS (single page).

## Funcionalidades

- Portfólio de processos **públicos** (Lei 14.133/2021) e **privados** (concessionárias)
- Análise crítica estruturada (quantitativos, custos, prazos, habilitação, riscos)
- Aba **Exigências** extraídas do edital (com avaliação e tratativas)
- **Checklist** operacional da equipe
- Importação de processos via **JSON gerado por IA** (Claude, etc.)
- Índice de seções em PDF (negrito + CAPS) para otimizar envio à IA
- Anexos por processo (edital, TR, planilhas)
- Sincronização entre usuários (polling + merge em conflito)
- Login básico no site (`SITE_USER` / `SITE_PASSWORD`)

## Estrutura do repositório

```
datasin/
├── app.py              # API Flask + servir painel e login
├── index.html          # Painel (front + lógica)
├── login.html          # Tela de login
├── pdf_sections.py     # Índice de seções em PDF
├── lambda_function.py  # Backend legado AWS (referência)
├── docker-compose.yml  # App + MongoDB local
├── Dockerfile
├── requirements.txt
├── .env.example
├── README.md
└── docs/
    ├── guia-docker.md      # Deploy local/servidor com Docker
    ├── guia-render.md      # Deploy no Render + MongoDB Atlas
    ├── guia-aws.md         # Deploy legado AWS (Lambda + DynamoDB)
    ├── prompt-ia.md        # Prompt completo para gerar JSON
    └── exemplos/
        └── processo-ia.json
```

## Início rápido (Docker local)

```bash
cp .env.example .env
# Edite .env: TOKEN, SITE_USER, SITE_PASSWORD, SECRET_KEY, MONGO_PASSWORD

# Confira API_TOKEN no index.html (mesmo valor de TOKEN)

docker compose up -d --build
```

Acesse: http://localhost:8080

Detalhes: [docs/guia-docker.md](docs/guia-docker.md)

## Deploy na nuvem (Render)

1. MongoDB Atlas (M0 grátis) → `MONGO_URL`
2. Render Web Service (Docker) → variáveis de ambiente
3. `CONFIG.API_URL: '/api'` e `API_TOKEN` no `index.html`

Detalhes: [docs/guia-render.md](docs/guia-render.md)

## Variáveis de ambiente

| Variável | Obrigatória | Descrição |
|---|---|---|
| `MONGO_URL` | Sim (produção) | Connection string MongoDB |
| `TOKEN` | Sim | Senha da API (`x-sinape-token` / `CONFIG.API_TOKEN`) |
| `SITE_USER` | Recomendada | Usuário do login do site |
| `SITE_PASSWORD` | Recomendada | Senha do login do site |
| `SECRET_KEY` | Recomendada | Chave para assinar cookies de sessão |
| `MONGO_PASSWORD` | Só Docker local | Senha do Mongo no docker-compose |
| `UPLOAD_DIR` | Não | Pasta de anexos (padrão `/app/uploads`) |
| `MAX_UPLOAD_MB` | Não | Tamanho máximo de upload (padrão `25`) |

Sem `SITE_USER` e `SITE_PASSWORD`, o login do site fica desabilitado (útil para dev local).

## Fluxo com IA

1. Na **home**, anexe PDFs (o painel monta o índice de seções) e/ou clique em **Copiar prompt p/ IA** (ou use [docs/prompt-ia.md](docs/prompt-ia.md)).
2. Envie o prompt + edital/TR para o Claude.
3. Cole o JSON em **Importar da IA (JSON)**.
4. Revise no painel — campos vindos da IA aparecem destacados.

Exemplo de saída: [docs/exemplos/processo-ia.json](docs/exemplos/processo-ia.json)

## API (resumo)

Autenticação: sessão de login + header `x-sinape-token: TOKEN`.

| Método | Rota | Descrição |
|---|---|---|
| GET | `/api/health` | Health check |
| GET | `/api/processos` | Lista resumida |
| POST | `/api/processos` | Cria processo |
| GET | `/api/processos/:id` | Documento completo |
| PUT | `/api/processos/:id` | Substitui processo |
| PATCH | `/api/processos/:id` | Mescla alterações |
| DELETE | `/api/processos/:id` | Remove processo |
| POST | `/api/pdf/secoes` | Índice de seções do PDF |
| GET/POST | `/api/processos/:id/anexos` | Lista / envia anexos |

## Documentação

| Guia | Quando usar |
|---|---|
| [guia-docker.md](docs/guia-docker.md) | Máquina local ou VM com Docker |
| [guia-render.md](docs/guia-render.md) | Render + MongoDB Atlas (atual) |
| [guia-aws.md](docs/guia-aws.md) | Arquitetura legada AWS |
| [prompt-ia.md](docs/prompt-ia.md) | Gerar processos a partir de editais |

## Licença

Uso interno SINAPE / Pasley Hill.
