# Dossiê de Montagem de Documentação

Pega um processo já pronto no Painel Sinape (exigências + pasta do
SharePoint já preenchidas) e devolve um `.zip` organizado em pastas
letradas, um por categoria de exigência.

## 1. Instalar

```
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
```

## 2. Configurar

Copie `config.exemplo.json` para `config.json` e escolha um dos dois modos:

### Modo Graph API (`MODO_LOCAL: false`, padrão)

- `TENANT_ID`, `CLIENT_ID`, `CLIENT_SECRET` — do app registrado no Azure AD
  (veja o guia que o Claude te passou no chat para esse cadastro).
- `PAINEL_BASE_URL`, `PAINEL_TOKEN` — os mesmos usados pelo Painel Sinape.

### Modo local (`MODO_LOCAL: true`)

Não depende do cadastro no Azure AD. Usa uma pasta do SharePoint já
sincronizada no seu computador via OneDrive, em vez de baixar pelo Graph API.

1. No SharePoint, abra a biblioteca de documentos do site (ex:
   `sinape.comercial` → Documentos) e clique em **"Adicionar atalho ao
   OneDrive"** (ou "Sincronizar"). Isso cria uma pasta local espelhando a
   biblioteca inteira — pode levar alguns minutos para sincronizar tudo na
   primeira vez, dependendo do tamanho.
2. Preencha `ONEDRIVE_RAIZ_SHAREPOINT` com o caminho dessa pasta local (ex:
   `C:\Users\SEU-USUARIO\OneDrive - SINAPE LTDA\Setor Comercial - Documentos`).
3. `PAINEL_BASE_URL`, `PAINEL_TOKEN` continuam sendo necessários do mesmo
   jeito — só a origem dos documentos muda, não a integração com o Painel.

**Nunca** commite `config.json` em um repositório Git.

## 3. Rodar

```
python server.py
```

Abra `http://localhost:5005`, digite o id do processo (o mesmo `id` usado
no Painel Sinape) e clique em "Montar dossiê e baixar .zip".

## 4. Antes de enviar

Leia o `CHECKLIST.txt` dentro da pasta gerada — ele lista o que foi
encontrado, o que está faltando e o que falhou ao baixar (nesse caso,
geralmente é um arquivo que o OneDrive ainda não sincronizou localmente —
tente rodar de novo depois). Não há limite de tamanho: todo arquivo
encontrado é baixado automaticamente, incluindo os grandes.

## Pendências conhecidas (ver `biblioteca.json`)

Algumas categorias (Garantias, Execução contratual, Documentação
complementar, Proposta comercial) ainda estão marcadas `"a_confirmar"` —
os nomes de subpasta são palpites baseados no único dossiê real
inspecionado até agora. Ajuste conforme a equipe confirmar.
