# HANDOFF — para o próximo modelo/sessão continuar

Data: 17/07/2026 (atualizado após implementação).

## O que foi feito NESTA tarefa
- `ARQUITETURA.md` escrito e, em seguida, **ia-service IMPLEMENTADO** em
  `Desktop/ia-sinape/`: `servidor.py` (Flask, porta 5006), `ia.py` (SDK
  anthropic 0.117, opus-4-8, adaptive thinking, streaming, structured
  outputs), `esquemas.py` (Pydantic), `painel.py`, `config.py`, `prompts/`
  (3 system prompts), `README.md`.
- Testado: schemas geram additionalProperties:false; servidor sobe sem
  config; /health; 401 de token; 422 de não-PDF; 400 de exigências
  ausentes; handler de AuthenticationError→502 (chamada real com chave
  fake chegou na API da Anthropic). **Falta apenas teste ponta a ponta com
  chave real — Gabriel ainda não criou a ANTHROPIC_API_KEY.**
- Regra do usuário: **não subir nada disso para o git por enquanto.**
- Atenção Windows: `pkill` não mata o Flask e o Windows deixa DOIS processos
  escutarem a mesma porta — matar via `taskkill //PID <pid> //F` (PID pelo
  `netstat -ano | grep :5006`).

## Contexto do sistema (onde encontrar cada peça)
- **Painel Sinape** (Fase 1): repo `gabriell-alvim/projeto_sinape` (público).
  API Flask+Mongo em `app.py`; contrato da IA em `PROMPT_PARA_IA.md` e
  `exemplo_processo_ia.json`. PRs abertos: #1 (campo `geral_pasta_sharepoint`
  + botão "📦 Montar Dossiê" por processo) e #2 (consolida montador +
  examinador em subpastas no monorepo). Branch local do usuário
  `migrar-mongodb` tem trabalho não commitado — não mexer.
- **Montador de Dossiê** (Fase 3): `Desktop/Dossiê de Montagem de Documentação/`
  (server.py Flask porta 5005 + montador_dossie.py com GraphClient pronto).
  Bloqueado por: cadastro do app no Azure AD (Gabriel ainda não fez) —
  sem isso não baixa binário do SharePoint.
- **Examinador do SharePoint** (Fase 2): `Desktop/examinador-do-sharepoint/`
  (SKILL.md de tarefa agendada 08:15 + cruzamento com Painel via config.json).
  Repo privado separado existe mas o usuário pediu para APAGAR (falta escopo
  delete_repo no gh — ele vai apagar manualmente ou rodar
  `gh auth refresh -h github.com -s delete_repo`).
- **Fase 4** (análise de atestados da concorrência): é a capacidade C3 do
  ia-service — só existe no ARQUITETURA.md por enquanto.

## Próximos passos (na ordem do ARQUITETURA.md §6)
1. Validar a arquitetura com o Gabriel (ele ainda não leu/aprovou).
2. Esqueleto do ia-service (Python, SDK `anthropic`, modelo `claude-opus-4-8`,
   adaptive thinking, structured outputs via `messages.parse()`).
3. Ele precisa criar a chave em platform.claude.com (não criar por ele).

## Pendências herdadas de antes desta tarefa
- Azure AD (Graph API) — passo a passo já foi dado no chat; aguardando Gabriel.
- `biblioteca.json` do Montador tem categorias `a_confirmar` (Garantias,
  Proposta comercial, Doc. complementar) — validar com dossiê real.
- Repo `projeto_sinape` é público com dados reais de licitação; Gabriel
  recusou torná-lo privado uma vez — não insistir sem ele pedir.
- LibreOffice foi instalado nesta máquina (QA visual de .pptx funciona;
  usar PyMuPDF para gerar imagens, pdftoppm não existe aqui).
