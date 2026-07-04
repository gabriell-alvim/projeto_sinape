# Guia de Implantação na AWS — Painel de Processos SINAPE

Este guia coloca o painel no ar em ~30 minutos usando só o console da AWS, sem instalar nada.

**Arquitetura:**

```
Navegador (equipe)  ⇄  index.html (S3 site estático)
        ⇄  Lambda Function URL (API)  ⇄  DynamoDB (tabela SinapeProcessos)
```

**Custo estimado:** praticamente zero. DynamoDB on-demand + Lambda + S3 nesse volume de uso (equipe pequena, polling a cada 20 s) ficam dentro do nível gratuito ou em centavos por mês.

---

## Passo 1 — Tabela DynamoDB

1. Console AWS → **DynamoDB** → **Criar tabela**.
2. Nome da tabela: `SinapeProcessos`
3. Chave de partição: `id` — tipo **String**. Sem chave de classificação.
4. Configurações da tabela: **Personalizar** → Modo de capacidade: **Sob demanda (on-demand)**.
5. Criar tabela. Pronto.

## Passo 2 — Função Lambda

1. Console AWS → **Lambda** → **Criar função** → "Criar do zero".
2. Nome: `sinape-painel-api` · Runtime: **Python 3.12** · Arquitetura: x86_64.
3. Criar função.
4. Na aba **Código**, apague o conteúdo de `lambda_function.py` e cole o conteúdo do arquivo `lambda_function.py` deste pacote. Clique **Deploy**.
5. Aba **Configuração → Variáveis de ambiente** → Editar → adicionar:
   - `TABLE_NAME` = `SinapeProcessos`
   - `TOKEN` = uma senha longa inventada por você (ex.: `sinape-2026-Xk93jf82hs`). **Anote — vai no CONFIG do painel.**
6. Aba **Configuração → Configuração geral** → Editar → Tempo limite: **10 s** (o padrão de 3 s serve, mas 10 dá folga).

### Permissão para a Lambda acessar o DynamoDB

1. Aba **Configuração → Permissões** → clique no nome da **função de execução** (abre o IAM).
2. **Adicionar permissões → Criar política em linha** → aba JSON → cole (troque `SUA_CONTA` pelo ID da conta, ou use o ARN mostrado na tabela DynamoDB):

```json
{
  "Version": "2012-10-17",
  "Statement": [{
    "Effect": "Allow",
    "Action": [
      "dynamodb:GetItem", "dynamodb:PutItem",
      "dynamodb:DeleteItem", "dynamodb:Scan"
    ],
    "Resource": "arn:aws:dynamodb:*:SUA_CONTA:table/SinapeProcessos"
  }]
}
```

3. Nome da política: `sinape-dynamo` → Criar.

## Passo 3 — Function URL (o endereço da API)

1. Na função Lambda → **Configuração → URL da função** → **Criar URL de função**.
2. Tipo de autenticação: **NONE** (a proteção é o token `x-sinape-token` verificado dentro do código).
3. Marque **Configurar CORS (compartilhamento de recursos entre origens)**:
   - Origens permitidas: `*` (depois de publicado, troque pela URL do site — ver Segurança abaixo)
   - Métodos permitidos: `GET, POST, PUT, PATCH, DELETE`  (ou `*`)
   - Cabeçalhos permitidos: `content-type, x-sinape-token`
4. Salvar. Copie a URL gerada, algo como:
   `https://abc123xyz.lambda-url.sa-east-1.on.aws/`

### Teste rápido (opcional, no terminal)

```bash
curl -H "x-sinape-token: SEU_TOKEN" https://abc123xyz.lambda-url.sa-east-1.on.aws/processos
# esperado: {"processos": []}
```

## Passo 4 — Configurar o painel

Abra o `index.html` num editor de texto e localize o bloco `CONFIG` no topo do primeiro `<script>`:

```js
const CONFIG = {
  API_URL: 'https://abc123xyz.lambda-url.sa-east-1.on.aws',  // URL do Passo 3, SEM barra no final
  API_TOKEN: 'sinape-2026-Xk93jf82hs',                       // mesmo TOKEN do Passo 2
  POLL_SEGUNDOS: 20,                                          // intervalo de sincronização
  USUARIO: ''                                                 // deixe vazio: o painel pergunta o nome 1x por navegador
};
```

> Com `API_URL` vazio o painel funciona em **modo local** (salva só no navegador) — bom para testar antes de implantar.

## Passo 5 — Hospedar o painel no S3

1. Console AWS → **S3** → **Criar bucket**. Nome: `sinape-painel` (nomes são globais; se ocupado, varie). Região: a mesma da Lambda (ex.: `sa-east-1`).
2. **Desmarque** "Bloquear todo o acesso público" e confirme o aviso.
3. Criar bucket → entre nele → **Carregar** → envie o `index.html` configurado.
4. Aba **Propriedades** → lá embaixo, **Hospedagem de site estático** → Editar → Ativar → Documento de índice: `index.html` → Salvar.
5. Aba **Permissões → Política do bucket** → Editar → cole (troque `sinape-painel` pelo nome real):

```json
{
  "Version": "2012-10-17",
  "Statement": [{
    "Sid": "LeituraPublica",
    "Effect": "Allow",
    "Principal": "*",
    "Action": "s3:GetObject",
    "Resource": "arn:aws:s3:::sinape-painel/*"
  }]
}
```

6. Volte em **Propriedades → Hospedagem de site estático**: ali está a URL do site, ex.:
   `http://sinape-painel.s3-website-sa-east-1.amazonaws.com`

Compartilhe essa URL com a equipe. Ao abrir pela primeira vez em cada navegador, o painel pergunta o nome da pessoa (aparece no "atualizado por").

## Passo 6 — Primeira carga

Com o servidor vazio, o painel mostra um aviso com o botão **"Enviar os 4 processos pré-cadastrados"** (Motiva + 3 EPR). Clique uma única vez, em um único navegador. A partir daí tudo que qualquer pessoa editar sincroniza para todos (polling + ao focar a janela).

---

## Como criar processo novo com IA (o fluxo do dia a dia)

1. No painel → **"Copiar prompt p/ IA"** (copia o prompt com o contrato JSON).
2. Numa conversa com o Claude (ou outra IA), cole o prompt e **anexe o edital/TR/anexos**.
3. A IA devolve um JSON com os campos preenchidos e, quando o edital exigir, **seções extras próprias** (garantia, vistoria, amostras…) e **checklist customizado com referência a cada item/cláusula**.
4. No painel → **"Importar da IA (JSON)"** → cole → o painel valida, mostra um resumo e cria o processo.

Alternativa sem colar no painel — a IA (ou um script) pode criar direto via API:

```bash
curl -X POST "https://abc123xyz.lambda-url.sa-east-1.on.aws/processos" \
  -H "content-type: application/json" \
  -H "x-sinape-token: SEU_TOKEN" \
  -d @processo.json
```

---

## Segurança — recomendações

- **Token**: use uma senha longa e troque se vazar (basta editar a variável `TOKEN` na Lambda e o `CONFIG.API_TOKEN` no HTML).
- **CORS**: depois que o site estiver no ar, volte na Function URL e troque "Origens permitidas" de `*` para a URL exata do site S3. Isso impede outros sites de chamarem sua API pelo navegador.
- O token fica visível no HTML — qualquer pessoa com o link do painel consegue editar. Para esse uso interno de equipe é o equilíbrio certo entre simplicidade e proteção; se um dia precisar de login por pessoa, o caminho é Amazon Cognito na frente da Function URL.
- **Backup**: DynamoDB → tabela → aba Backups → ative **PITR (recuperação point-in-time)**. Custo irrisório e desfaz qualquer acidente.

## Problemas comuns

| Sintoma | Causa provável | Correção |
|---|---|---|
| Pílula "sem conexão" no topo | `API_URL` errada ou com barra final | Confira o CONFIG (sem `/` no fim) |
| Erro de token no painel | `API_TOKEN` ≠ variável `TOKEN` da Lambda | Igualar os dois |
| Erro de CORS no console do navegador | CORS da Function URL sem o header `x-sinape-token` | Passo 3, item 3 |
| Lista vazia após importar | Escreveu numa tabela/região diferente | Confira `TABLE_NAME` e a região da Lambda |
| `AccessDeniedException` nos logs | Política IAM não aplicada | Passo 2, seção de permissões |

Logs da API: Lambda → aba **Monitorar → Visualizar logs do CloudWatch**.
