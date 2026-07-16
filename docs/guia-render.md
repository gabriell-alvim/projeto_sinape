# Guia de implantação no Render

Deploy recomendado para testes e uso pela equipe sem servidor próprio. O Render roda o container Docker (`Dockerfile`); o banco fica no **MongoDB Atlas** (plano M0 gratuito).

## Arquitetura

```
Navegador  ⇄  Render (Flask + index.html + API /api)
                    ⇄  MongoDB Atlas (M0)
                    ⇄  disco efêmero (anexos — podem sumir após restart no free tier)
```

## Passo 1 — MongoDB Atlas

1. Crie conta em [mongodb.com/atlas](https://www.mongodb.com/cloud/atlas).
2. Cluster **M0 Free**.
3. **Database Access**: usuário e senha.
4. **Network Access**: `0.0.0.0/0` (necessário para o Render).
5. Copie a connection string, por exemplo:

```
mongodb+srv://usuario:senha@cluster0.xxxxx.mongodb.net/sinape?retryWrites=true&w=majority
```

Substitua `<password>` e use encode na URL se a senha tiver `@`, `#`, etc.

## Passo 2 — Serviço no Render

1. [render.com](https://render.com) → **New → Web Service**.
2. Conecte o repositório GitHub.
3. **Environment**: Docker.
4. Porta: `8080`.

### Variáveis de ambiente

| Variável | Descrição |
|---|---|
| `MONGO_URL` | Connection string completa do Atlas |
| `TOKEN` | Senha da API (`CONFIG.API_TOKEN` no `index.html`) |
| `SITE_USER` | Usuário do login do site |
| `SITE_PASSWORD` | Senha do login do site |
| `SECRET_KEY` | Chave longa aleatória (sessão Flask) |
| `UPLOAD_DIR` | `/app/uploads` |
| `MAX_UPLOAD_MB` | `25` (opcional) |

O Render define `RENDER=true`; o cookie de sessão usa HTTPS automaticamente.

## Passo 3 — Configurar o painel

No `index.html`, bloco `CONFIG`:

```js
const CONFIG = {
  API_URL: '/api',
  API_TOKEN: 'MESMO_VALOR_DO_TOKEN_NO_RENDER',
  POLL_SEGUNDOS: 20,
  USUARIO: ''
};
```

Commit e push — o Render redeploya sozinho.

## Passo 4 — Testar

```bash
curl https://SEU-SERVICO.onrender.com/api/health
# {"ok": true}
```

Acesse a URL no navegador → tela de login → painel.

## Limitações do plano free

- Serviço **dorme** após ~15 min sem uso (primeiro acesso pode demorar).
- **Anexos** em disco efêmero — podem desaparecer após restart.
- Para produção estável: plano pago ou VM + Docker (ver [guia-docker.md](guia-docker.md)).

## Problemas comuns

| Sintoma | Correção |
|---|---|
| `Empty host` em `MONGO_URL` | URL vazia ou mal formatada; não use `@db:27017` do docker-compose |
| `bad auth` no Atlas | Senha errada ou não encoded na URL; resete no Atlas |
| Erro de token no painel | `TOKEN` no Render ≠ `API_TOKEN` no `index.html` |
| Redireciona para `/login` | Normal — configure `SITE_USER` e `SITE_PASSWORD` |
| 401 na API após login | Falta `TOKEN` ou cookie de sessão (use mesmo domínio) |
