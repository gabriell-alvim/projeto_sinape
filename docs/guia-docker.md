# Guia de Implantação com Docker — Painel de Processos SINAPE

Este guia substitui a implantação na AWS (ver [guia-aws.md](guia-aws.md), mantido só como referência) por um único container Docker que serve o painel (`index.html`) e a API, mais um container MongoDB para os dados. Os anexos enviados pela equipe ficam salvos em disco, em um volume Docker.

Para deploy na nuvem sem servidor próprio, veja também [guia-render.md](guia-render.md).

**Arquitetura:**

```
Navegador (equipe)  ⇄  container "app" (Flask: serve index.html + API em /api)
                            ⇄  container "db" (MongoDB — dados dos processos)
                            ⇄  volume "uploads" (arquivos anexados aos processos)
```

## Pré-requisitos

- Docker e Docker Compose instalados na máquina/servidor.

## Passo 1 — Configurar variáveis de ambiente

1. Copie `.env.example` para `.env`:
   ```bash
   cp .env.example .env
   ```
2. Edite `.env` e defina:
   - `TOKEN` — senha longa que a API vai exigir no header `x-sinape-token`. **Anote — vai no CONFIG do painel.**
   - `SITE_USER` e `SITE_PASSWORD` — login de acesso ao painel (quem não souber não entra no site).
   - `SECRET_KEY` — chave secreta para a sessão de login (string longa aleatória).
   - `MONGO_PASSWORD` — senha do usuário root do MongoDB (uso interno do container `db`, não precisa ser a mesma do `TOKEN`).

## Passo 2 — Configurar o painel

Abra `index.html` e confira o bloco `CONFIG` no topo do primeiro `<script>`:

```js
const CONFIG = {
  API_URL: '/api',        // já correto — backend no mesmo container
  API_TOKEN: 'MESMO_TOKEN_DO_.env',
  POLL_SEGUNDOS: 20,
  USUARIO: ''
};
```

Preencha `API_TOKEN` com o mesmo valor de `TOKEN` do `.env`.

## Passo 3 — Subir os containers

```bash
docker compose up -d --build
```

Isso builda a imagem do `app` (Python 3.12 + Flask + gunicorn), sobe o MongoDB, cria os índices automaticamente na primeira execução e publica o painel em `http://localhost:8080`.

Verifique:
```bash
curl http://localhost:8080/api/health
# esperado: {"ok": true}
```

## Passo 4 — Primeira carga

Acesse `http://localhost:8080`. Com o servidor vazio, o painel mostra o botão **"Enviar os 4 processos pré-cadastrados"**. Clique uma única vez. A partir daí tudo sincroniza entre quem acessar o mesmo endereço (polling + ao focar a janela).

## Anexos

Dentro de um processo aberto, a caixa **📎 Anexos** permite enviar arquivos (edital, TR, planilhas, etc.) e baixá-los depois. Os arquivos ficam em `UPLOAD_DIR` (padrão `/app/uploads` dentro do container `app`), que é montado como volume Docker nomeado (`uploads`) — sobrevive a rebuilds e restarts do container.

Tamanho máximo por arquivo: `MAX_UPLOAD_MB` no `.env` (padrão 25 MB).

## Persistência e backup

- **Dados dos processos**: volume `mongodata` (MongoDB). Para backup:
  ```bash
  docker compose exec db mongodump -u sinape -p "$MONGO_PASSWORD" --authenticationDatabase admin --db sinape --archive=/tmp/backup.archive
  docker compose cp db:/tmp/backup.archive backup_$(date +%Y%m%d).archive
  ```
- **Anexos**: volume `uploads`. Para copiar para fora do Docker:
  ```bash
  docker run --rm -v projeto_sinape_uploads:/from -v "$PWD/backup_uploads:/to" alpine sh -c "cp -a /from/. /to/"
  ```
  (ajuste o nome do volume conforme `docker volume ls`)

## Expor para a equipe (fora da máquina local)

- Coloque um reverse proxy com HTTPS na frente (nginx, Caddy, Traefik) apontando para a porta `8080` do container `app`. Não exponha a porta 8080 direto na internet sem TLS — o token viaja em texto claro sem HTTPS.
- Se o servidor tiver domínio, o Caddy resolve certificado automaticamente com poucas linhas de config.

## Comandos úteis

| Ação | Comando |
|---|---|
| Ver logs da API | `docker compose logs -f app` |
| Ver logs do banco | `docker compose logs -f db` |
| Reiniciar só a API (após editar `index.html`/`app.py`) | `docker compose up -d --build app` |
| Parar tudo | `docker compose down` |
| Parar e apagar dados (⚠️ irreversível) | `docker compose down -v` |

## Problemas comuns

| Sintoma | Causa provável | Correção |
|---|---|---|
| Pílula "sem conexão" no topo | `CONFIG.API_URL` diferente de `/api` ou container fora do ar | Confira `docker compose ps` e o CONFIG |
| Erro de token no painel | `API_TOKEN` do `index.html` ≠ `TOKEN` do `.env` | Igualar os dois e reiniciar `app` |
| `app` não sobe / erro de conexão com banco | `db` ainda inicializando | `docker compose logs db` — o `app` só sobe após o healthcheck do banco passar |
| Anexo não aparece após enviar | Upload maior que `MAX_UPLOAD_MB` | Aumentar no `.env` e `docker compose up -d --build app` |
| Erro 401 em todas as chamadas | `TOKEN` vazio no `.env` | A API recusa qualquer requisição sem `TOKEN` configurado |
