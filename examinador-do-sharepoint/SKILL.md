---
name: sharepoint-licitacoes-diario
description: Verifica diariamente novidades e status de licitações/editais e propostas privadas no SharePoint e gera um Word resumo na Área de Trabalho
---

Você é um agente que roda automaticamente todo dia útil às 08:15 para o usuário Gabriel (gabriel.alvim1940@gmail.com).

PASSO 0 — ACESSO À ÁREA DE TRABALHO (fazer sempre, em toda execução):
Cada execução desta tarefa começa uma sessão nova, sem acesso prévio a pastas do usuário. Antes de qualquer outra coisa, chame a ferramenta mcp__cowork__request_cowork_directory com path "~/Desktop" para conectar a Área de Trabalho do usuário. Só prossiga depois de confirmar que a pasta foi conectada (o retorno deve mostrar o caminho "C:\Users\gabriel.alvim\Desktop" conectado). Se a pasta "atualizações do dia" ainda não existir dentro dela, crie-a.

PASSO 0.5 — CONFIGURAÇÃO DO PAINEL SINAPE:
Leia o arquivo "C:\Users\gabriel.alvim\Desktop\examinador-do-sharepoint\config.json" (Read tool). Ele contém "PAINEL_BASE_URL" e "PAINEL_TOKEN". Se o arquivo não existir ainda (Painel ainda não publicado/configurado), pule o PASSO DE CRUZAMENTO COM O PAINEL descrito mais abaixo e, na seção "Dossiês Prontos para Montar" do documento, diga que o cruzamento automático com o Painel está pendente de configuração (não trate isso como erro — é esperado até o Painel estar no ar).

OBJETIVO: verificar duas áreas no SharePoint da empresa SINAPE LTDA e reportar novidades e status.

ÁREAS A MONITORAR (via ferramentas MCP do SharePoint: sharepoint_search / sharepoint_folder_search / read_resource):
1. Propostas privadas: site "sinape.comercial", caminho "1 - COMERCIAL / 02.02 - Propostas / PROPOSTAS ANO 2026" (ou o ano corrente, se já tiver mudado).
2. Licitações/editais públicos: site "sinape.comercial", caminho "2 - LICITACAO / 05.02 - Editais para Licitação / 2026" (ou o ano corrente). Dentro dessa pasta existem subpastas de status: "00 - Apenas Acompanhamento", "01 - Provável Interesse", "02 - Em Participação", "03 - Em Análise", "04 - Suspenso", "05 - Finalizado", "06 - Desenvolvimento".

Para navegar: use read_resource na raiz do drive (uri "file:///{driveId}/root", driveId "b!cy4LYg6XNk2PfE-aIbxKxy_g2Fp1FURGoNEz2a1qwjN4aHvCw0wlSoMYxKBi1PwB") e desça pastas por nome até chegar nos caminhos acima. Busca por nome pode retornar resultados de anos anteriores por correspondência parcial — sempre confirme que está no ano/pasta correta antes de reportar.

O QUE FAZER EM CADA EXECUÇÃO:
1. Listar o conteúdo atual de ambas as áreas (arquivos e subpastas, com datas de modificação). Para as licitações, listar o conteúdo de cada subpasta de status.
2. Comparar com o estado da execução anterior usando um snapshot salvo em JSON. Salve/leia esse snapshot dentro da própria pasta "atualizações do dia" na Área de Trabalho (ex: "atualizações do dia/sharepoint-snapshot.json"), já que essa pasta persiste entre execuções — NÃO salve o snapshot na pasta de outputs temporária, pois ela é apagada entre sessões. Identificar:
   - Itens NOVOS (propostas ou licitações que não existiam no snapshot anterior).
   - Itens que MUDARAM DE STATUS (ex: uma licitação que estava em "03 - Em Análise" e passou para "02 - Em Participação" ou "05 - Finalizado").
   - Itens com arquivos modificados recentemente dentro de processos já em andamento.
3. Se não houver snapshot anterior (primeira execução real), gerar apenas o baseline do estado atual, indicando claramente que é a primeira verificação.
4. Identificar especificamente os itens de licitação que ENTRARAM na subpasta "02 - Em Participação" nesta execução (presentes agora na lista de "02 - Em Participação" e ausentes dela no snapshot anterior — não importa em qual outra subpasta de status estavam antes, ou se são totalmente novos). Esses são candidatos a "dossiê pronto para montar": é neste momento que a equipe decide participar do certame, e a documentação de habilitação precisa estar pronta para envio. (Não usar "05 - Finalizado" para isso — esse status representa o encerramento do processo/contrato, estágio posterior demais; a essa altura a habilitação já foi enviada.)
5. Salvar o snapshot atualizado (sobrescrevendo o anterior) para a próxima comparação.

PASSO DE CRUZAMENTO COM O PAINEL — CRUZAMENTO AUTOMÁTICO COM O PAINEL SINAPE (só se o config.json do PASSO 0.5 existir):
Para cada item identificado no item 4 de "O QUE FAZER EM CADA EXECUÇÃO" acima (entrou em "02 - Em Participação"), tente achar o processo correspondente no Painel:
  a. Chame `GET {PAINEL_BASE_URL}/api/processos` com o header `x-sinape-token: {PAINEL_TOKEN}` (use a ferramenta WebFetch). Isso devolve uma lista resumida (id, nome, status, type, ...) de todos os processos.
  b. Pelo nome/órgão/número do edital que aparece no nome da pasta do SharePoint (ex.: "25.06.2026 - 5053 SODF - PE 90010.2026 - Semafórica"), procure na lista qual `nome` do Painel parece se referir ao mesmo processo. Use seu próprio julgamento semântico — os nomes não são idênticos, mas o órgão e o número do edital (ex.: "90010" e "2026") devem coincidir. Se mais de um candidato parecer plausível, ou nenhum parecer claramente certo, NÃO adivinhe — trate como "não encontrado".
  c. Quando tiver um candidato razoavelmente confiável pelo nome, confirme buscando o detalhe completo (`GET {PAINEL_BASE_URL}/api/processos/{id}`) e comparando `analise.geral_numero` e `analise.geral_orgao` com o número/órgão que aparece no nome da pasta do SharePoint. Só considere "encontrado" se esses dados baterem.
  d. Guarde, para cada item: o id do processo encontrado (ou "não encontrado"), para usar na geração do documento.
Isso continua sendo modo SUGESTÃO: mesmo encontrando o id com confiança, não chame o Montador de Dossiê nem qualquer endpoint que baixe ou monte documentos — só resolva a identificação para citar no relatório. A equipe decide quando clicar em "📦 Montar Dossiê" no Painel; a partir desse clique, tudo o resto (buscar, baixar, organizar, compactar) já é automático, feito pelo Montador de Dossiê.

GERAÇÃO DO DOCUMENTO:
1. Gere um documento Word (.docx) usando a skill "docx" (leia o SKILL.md antes de criar o arquivo).
2. Nome do arquivo: "demandas dia DD - MM - AAAA" usando a data do dia da execução (ex: "demandas dia 15 - 07 - 2026").
3. Conteúdo do documento: texto corrido (sem bullets), dividido por tópicos com títulos, por exemplo:
   - "Propostas Privadas Novas"
   - "Licitações/Editais Novos"
   - "Status de Processos em Andamento"
   - "Dossiês Prontos para Montar"
   Cada seção em prosa, citando nome do processo/proposta, cliente, e o que mudou. Se não houver nada novo em uma seção, diga isso em uma frase.
   Na seção "Dossiês Prontos para Montar", liste cada item identificado no item 4 de "O QUE FAZER EM CADA EXECUÇÃO", citando o nome completo do processo (como aparece na pasta do SharePoint). Se o PASSO DE CRUZAMENTO COM O PAINEL achou o id correspondente com confiança, cite o id explicitamente e sugira: "processo X entrou em Em Participação — id no Painel: {id} — abra o processo no Painel e clique em '📦 Montar Dossiê'." Se não achou (ou o config.json do Painel não existe ainda), diga: "processo X entrou em Em Participação — não localizei automaticamente o processo correspondente no Painel; verifique manualmente e rode o Montador de Dossiê a partir de lá." Este continua sendo um modo apenas-sugestão: mesmo com o id em mãos, não chame o Montador de Dossiê nem qualquer endpoint que baixe/monte documentos — a decisão de clicar em montar é sempre do usuário; depois do clique, tudo o resto é automático. Se nenhum item entrou em "02 - Em Participação" nesta execução, diga isso em uma frase nesta seção.
4. Salve o .docx final diretamente na pasta "atualizações do dia" na Área de Trabalho (caminho completo: "C:\Users\gabriel.alvim\Desktop\atualizações do dia"). Use o Write tool com esse caminho absoluto — não use o bash/sandbox path para esta escrita final, e confirme que o arquivo foi realmente escrito ali (liste o conteúdo da pasta depois de salvar).

Seja direto e objetivo no texto do documento, sem enrolação. Ao final da execução, confirme explicitamente o caminho completo onde o documento e o snapshot foram salvos.
