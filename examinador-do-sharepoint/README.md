# Examinador do SharePoint

Agente/tarefa agendada que roda todo dia útil às 08:15 (e pode ser rodada manualmente a qualquer momento) e verifica duas áreas no SharePoint da SINAPE (propostas privadas e licitações/editais públicos), comparando com o estado do dia anterior e gerando um resumo em Word ("demandas dia DD - MM - AAAA.docx") na Área de Trabalho do usuário.

## Integração com o Painel Sinape e o Montador de Dossiê (modo sugestão)

Quando um processo entra na subpasta "05 - Finalizado" do SharePoint, o relatório
diário passa a ter uma seção "Dossiês Prontos para Montar" sinalizando isso — é
o sinal de que a documentação de habilitação normalmente já está completa e o
Montador de Dossiê pode ser rodado para aquele processo.

Se `config.json` estiver preenchido (veja `config.exemplo.json`), o agente
cruza automaticamente esses itens com a lista de processos do Painel Sinape
(por órgão/número do edital) e já cita o `id` correto no relatório — bastando
abrir aquele processo no Painel e clicar em "📦 Montar Dossiê". Se não
encontrar com confiança (ou o Painel ainda não estiver configurado), o
relatório avisa que a checagem precisa ser manual. Em nenhum dos dois casos o
agente chama o Montador sozinho — a decisão de montar continua sendo sempre
do usuário.

## Conteúdo deste repositório

- `SKILL.md` — instruções completas da tarefa agendada (o que verificar, como comparar com o snapshot anterior, como cruzar com o Painel, como gerar o documento).
- `config.exemplo.json` — modelo de configuração (URL e token do Painel Sinape). Copie para `config.json` e preencha; `config.json` fica fora do git.
- `sharepoint-snapshot.json` — último snapshot salvo do estado das pastas monitoradas, usado para detectar novidades e mudanças de status na execução seguinte.
- `demandas dia 15 - 07 - 2026.docx` — exemplo de relatório gerado pela tarefa.

## Como funciona

1. Conecta na Área de Trabalho do usuário.
2. Lista o conteúdo atual das pastas de propostas privadas e de licitações (por status) no SharePoint.
3. Compara com o snapshot da execução anterior para identificar itens novos e mudanças de status.
4. Gera um `.docx` resumindo as novidades, dividido em: Propostas Privadas Novas, Licitações/Editais Novos e Status de Processos em Andamento.
5. Atualiza o snapshot para a próxima comparação.
