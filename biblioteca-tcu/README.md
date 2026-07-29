# Biblioteca de jurisprudência do TCU

Material de referência que o Sinki consulta na hora de responder, em vez de
citar acórdão de memória — que é como se erra número de acórdão e se perde a
peça inteira no indeferimento.

## De onde veio

Manual oficial **"Licitações e Contratos: Orientações e Jurisprudência do
TCU"**, 5ª edição, atualizado na origem em 29/08/2025, já sob a Lei
14.133/2021.

- Site: <https://licitacoesecontratos.tcu.gov.br/>
- Baixado em 29/07/2026 pela API REST pública do próprio site
  (`/wp-json/wp/v2/posts`), 209 seções.

## O que tem aqui

```
indice.json   índice curado: seção, título, escopo, acórdãos e súmulas citados
secoes/       uma seção por arquivo, em texto puro
```

O manual inteiro tem ~3,1 milhões de caracteres. Mandar isso pra IA a cada
pergunta seria caro e inútil, então o `indice.json` classifica cada seção:

| escopo | seções | o que é |
|---|---|---|
| `nucleo` | 28 | uso diário; bate direto com os campos do Painel (habilitação, impugnação, recurso, POC, consórcio, garantias, SRP) |
| `complementar` | 56 | fundamenta impugnação/recurso quando o tema aparece (regimes de execução, medição, BDI, reajuste, orçamento sigiloso) |
| `fora` | 125 | governança interna do órgão, ETP, as 27 hipóteses de dispensa/inexigibilidade — não interessa a quem disputa |

Busca por tema nunca retorna seção `fora`. Busca por número de seção retorna
qualquer uma, inclusive as de fora — se alguém pedir explicitamente, entrega.

## Limite importante

Vale só para contratação **pública** (Lei 14.133/2021). Em processo privado
— concessionária, RFQ, carta-convite — não se cita TCU: vale o documento do
contratante. O prompt do Sinki já diz isso, e a própria resposta da
ferramenta carrega o aviso.

## Como o Sinki usa

Ferramenta `consultar_jurisprudencia`, com dois modos:

- `resumo` (padrão) — só os enunciados de acórdão e súmula da seção, prontos
  para citar. Compacto.
- `completo` — o texto inteiro da seção, para quando o raciocínio e as
  referências normativas importam.

Aceita tema (`atestado de capacidade técnica`), número de acórdão
(`1604/2025`), súmula (`Súmula 275`) ou seção (`5.5.2`).

## Como atualizar quando sair uma nova edição

`montar_biblioteca_tcu.py` refaz tudo a partir do JSON bruto da API. Rebaixe
os posts e rode o script — ele reconverte as seções e regera o índice. A
classificação de escopo e as palavras-chave de busca ficam no topo do
próprio script (`NUCLEO`, `COMPLEMENTAR`, `PALAVRAS`); é ali que se ajusta
se um tema novo passar a importar.
