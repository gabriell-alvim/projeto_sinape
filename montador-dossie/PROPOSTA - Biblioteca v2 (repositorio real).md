# Proposta — Biblioteca v2 do Montador (baseada no repositório real da SINAPE)

> **Por que esta proposta existe.** A `biblioteca.json` atual foi construída a
> partir de **uma única pasta de teste** — a `VERGIL - DOSSIÊ TESTE COMPLETO`
> da USP RP. Ao varrer todo o SharePoint, essa estrutura (`02 - Documentacao/
> 02.01 - Habilitação Jurídica…`) aparece **em um só lugar**: aquele teste.
> Nenhum processo real é organizado assim. Por isso o Montador dá `404` em
> qualquer processo real (Águas da Prata, SIE SC etc.).
>
> A documentação de habilitação da SINAPE **não é copiada processo a
> processo**. Ela é a mesma para toda licitação e vive **centralizada e
> atualizada** em `2 - LICITACAO/05.03 - Documentos Atualizados/` (+ atestados
> em `1 - COMERCIAL/02.07 - Atestados`). Esta proposta reaponta o Montador
> para esses locais reais.

---

## 1. Como a equipe realmente organiza (convenções descobertas)

Três convenções aparecem de forma consistente em todo o repositório:

1. **Vigente na raiz, vencido em subpasta.**
   O documento atual fica na **raiz** da pasta-folha; as versões vencidas/
   substituídas são movidas para subpastas como `Obsoleto`, `Anteriores`,
   `Antigas`, `antigos`, `descartar`, `OLD`. Às vezes o atual fica numa
   subpasta explícita `Vigente` / `Vigentes`.

2. **Data de validade no nome do arquivo.** Dois padrões:
   - **Intervalo** `NOME DD.MM - DD.MM.pdf` → `emissão - validade`
     (a **2ª data é o vencimento**). Às vezes com ano: `18.11.25 - 17.01.26`.
   - **Data única** `NOME DD.MM.AAAA.pdf` (ex.: `Sicaf 05.06.2026.pdf`).
   Documentos que não vencem (contratos, RG, diplomas, balanços) geralmente
   **não têm data** no nome.

3. **Recorte por contexto.**
   - **Regularidade fiscal é por estado** (`BA, DF, GO, MG, MS, PR, RJ, RS,
     SP…` → `Estadual / Federal / Municipal`). A licitação usa o estado do
     órgão contratante (a UF que já está na análise do Painel).
   - **Empresa**: normalmente **Sinape**; há também BCW, Águia dos Mares
     (holding/sócios) e consórcios.

> **Consequência prática:** a seleção do documento certo é **majoritariamente
> baseada em pasta** (ignorar `Obsoleto` e afins), com a **data no nome** só
> como critério de desempate/frescor quando há vários vigentes do mesmo tipo.

---

## 2. De onde vem cada categoria (mapa de fontes real)

Raiz central: `2 - LICITACAO/05.03 - Documentos Atualizados`

| Letra | Categoria (Painel)              | Fonte real                                                                 | Observações |
|------|----------------------------------|----------------------------------------------------------------------------|-------------|
| A | Habilitação jurídica              | `05.03/01 - Habilitação Jurídica`                                          | Contrato social **Sinape/Vigente**; Certidão Simplificada (JUCESP) mais recente; docs dos sócios |
| B | Habilitação fiscal e trabalhista  | `05.03/02 - Regularidade Fiscal/<UF>` + `05.03/03 - Regularidade Trabalhista` + SICAF/FGTS | **Depende da UF** do processo. Federal (CNPJ/FGTS/CND Federal) é nacional |
| C | Habilitação econômico-financeira  | `05.03/04 - Qualificação Econômica`                                        | Balanço do **ano vigente** (`SP/Contábil/<ano>`) + índices + certidões de falência/cartórios + CRC do contador |
| D | Habilitação técnica               | `05.03/05 - Qualificação Técnica` (CREA/RT) **+** `1 - COMERCIAL/02.07 - Atestados` | Atestados **dependem do objeto** do edital — seleção com curadoria |
| E | Participação (declarações)        | Pasta do **processo** (declarações específicas com o nº do PE)             | Geradas por processo; não são centrais |
| F | Proposta comercial                | Pasta do **processo** (`Orçamento…`, proposta)                            | Específica do processo |
| — | Certificações cadastrais (SICAF)  | `05.03/06 - Certificações Cadastrais/Federal` (`Sicaf …AAAA.pdf` mais recente) | SICAF é o documento-chave; hoje mora aqui, não em “fiscal” |

**Duas fontes, não uma.** O Montador v2 precisa combinar:
- **Documentos da empresa** (A, B, C, D-credenciais, SICAF) → **repositório central** (iguais para toda licitação, sempre os vigentes).
- **Documentos do processo** (E, F) → **pasta do processo** no SharePoint.

---

## 3. Lógica de seleção proposta (3 camadas)

Para cada item da biblioteca, o Montador aplica, nesta ordem:

**Camada 1 — Fonte (onde procurar).**
Caminho central fixo (ex.: `…/02 - Regularidade Fiscal/{UF}/Federal`) ou
pasta do processo. `{UF}` e `{empresa}` são preenchidos pelo contexto do
processo (a UF já existe na análise do Painel).

**Camada 2 — Vigência (qual versão).**
1. Listar arquivos, **excluindo** qualquer um cujo caminho contenha uma pasta
   “de arquivo morto”: `obsoleto`, `anterior(es)`, `antiga(s)`, `antigos`,
   `descartar`, `old`, `baixados`, `obsoletos`.
2. Se existir subpasta `Vigente`/`Vigentes`, **priorizar** o conteúdo dela.
3. Se sobrar **mais de um** arquivo do mesmo tipo, escolher o de **validade
   mais recente** lendo a data no nome (2ª data do intervalo, ou a data única).
   Sem data → manter todos e sinalizar no checklist.

**Camada 3 — Alerta de vencimento.**
Se a data de validade do escolhido já passou (< hoje), **não** descartar, mas
marcar no `CHECKLIST.txt` como `[VENCIDO? CONFERIR] nome (validade dd/mm)`.
Isso protege contra certidão vencida esquecida na raiz.

**Itens com curadoria (não 100% automáticos):**
- **Atestados técnicos (D):** quais atestados entram depende do **objeto** do
  edital. Proposta: o Montador **copia a lista de atestados disponíveis** para
  uma pasta `D - Habilitação técnica/_ATESTADOS DISPONÍVEIS/` e o checklist
  pede seleção humana — ou, futuramente, a IA do Painel sugere os atestados
  compatíveis com o objeto.
- **Município (fiscal municipal):** varia por cidade; sinalizar no checklist
  quando o edital exigir certidão municipal específica.

---

## 4. Novo schema da `biblioteca.json` (v2)

Ver arquivo `biblioteca_v2_proposta.json` (rascunho ao lado deste). Cada
categoria passa a ter uma lista de **fontes**, cada uma com origem, caminho
(com variáveis `{uf}`/`{empresa}`), e regra de vigência:

```json
{
  "categoria_painel": "Habilitação fiscal e trabalhista",
  "letra_zip": "B",
  "fontes": [
    { "descricao": "Regularidade Federal (CNPJ, FGTS, CND Federal)",
      "origem": "central",
      "caminho": "2 - LICITACAO/05.03 - Documentos Atualizados/02 - Regularidade Fiscal/SP/Federal",
      "vigencia": "atual_mais_recente" },
    { "descricao": "Regularidade Estadual da UF do processo",
      "origem": "central",
      "caminho": "2 - LICITACAO/05.03 - Documentos Atualizados/02 - Regularidade Fiscal/{uf}/Estadual",
      "vigencia": "atual_mais_recente" },
    { "descricao": "Regularidade Trabalhista (CNDT, MTE, TRT)",
      "origem": "central",
      "caminho": "2 - LICITACAO/05.03 - Documentos Atualizados/03 - Regularidade Trabalhista",
      "vigencia": "atual_mais_recente" }
  ]
}
```

Valores de `vigencia`:
- `todos` — copia tudo da pasta (para pastas já curadas, ex.: `…/Vigente`).
- `atual_mais_recente` — aplica a Camada 2 completa (ignora arquivo morto +
  escolhe o mais recente por data no nome).
- `manual` — não baixa; lista no checklist para seleção humana (atestados).

---

## 5. Pontos a confirmar com a equipe (Thiago/responsável)

1. **Empresa licitante padrão** é sempre a **Sinape**? (há BCW, Águia,
   consórcios). Precisamos saber quando é consórcio.
2. **Federal por estado**: as certidões federais (CNPJ, FGTS, CND Tributos
   Federais) são idênticas em qualquer `<UF>/Federal`? Podemos fixar `SP/Federal`
   como fonte canônica do federal?
3. **SICAF**: confirmar que o SICAF (`06 - Certificações Cadastrais/Federal`,
   `Sicaf AAAA.pdf` mais recente) entra sempre e substitui boa parte da
   habilitação quando o edital aceita SICAF.
4. **Atestados técnicos**: como decidir quais entram? Existe um critério
   (tipo de obra/serviço) que dê para automatizar, ou é sempre curadoria?
5. **Balanço econômico**: usar sempre o balanço do **último exercício**
   (`04/SP/Contábil/<ano mais recente>`)? Confirmar quais peças (balanço, DRE,
   notas, índices) formam o pacote.
6. **Município**: quando o edital exige certidão municipal, ela existe no
   repositório central (`…/Municipal/<cidade>`) ou é emitida na hora?

---

## 6. Resumo executivo

- ✅ O Graph API está **funcionando** (acesso liberado, download real testado).
- ✅ A empresa **já mantém** um repositório central bem organizado e atualizado.
- 🔧 O Montador precisa ser **reapontado** para esse repositório, com a lógica
  de vigência/estado/empresa acima — não é um bug, é um **redesenho de fonte**.
- 🧭 Alguns itens (atestados técnicos, município) exigem curadoria ou apoio da
  IA do Painel; o resto pode ser 100% automático.
