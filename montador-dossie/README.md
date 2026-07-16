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

Copie `config.exemplo.json` para `config.json` e preencha:

- `TENANT_ID`, `CLIENT_ID`, `CLIENT_SECRET` — do app registrado no Azure AD
  (veja o guia que o Claude te passou no chat para esse cadastro).
- `PAINEL_BASE_URL`, `PAINEL_TOKEN` — os mesmos usados pelo Painel Sinape.

**Nunca** commite `config.json` em um repositório Git.

## 3. Rodar

```
python server.py
```

Abra `http://localhost:5005`, digite o id do processo (o mesmo `id` usado
no Painel Sinape) e clique em "Montar dossiê e baixar .zip".

## 4. Antes de enviar

Leia o `CHECKLIST.txt` dentro da pasta gerada — ele lista o que foi
encontrado, o que está faltando, e quais arquivos ficaram grandes demais
para entrar automaticamente (ficam listados com link direto do SharePoint
para você decidir se anexa manualmente).

## Pendências conhecidas (ver `biblioteca.json`)

Algumas categorias (Garantias, Execução contratual, Documentação
complementar, Proposta comercial) ainda estão marcadas `"a_confirmar"` —
os nomes de subpasta são palpites baseados no único dossiê real
inspecionado até agora. Ajuste conforme a equipe confirmar.
