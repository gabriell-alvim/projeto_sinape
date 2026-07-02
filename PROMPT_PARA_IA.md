# Prompt para IA — Gerar processo para o Painel SINAPE (V2)

Use este prompt em qualquer conversa com o Claude (ou outra IA) **anexando o edital, termo de referência e demais anexos**. A IA devolve um JSON pronto para o botão **"📥 Importar da IA (JSON)"** do painel — ou para POST direto na API.

> É o mesmo texto do botão **"🤖 Copiar prompt p/ IA"** do painel. Diferença do V1: método de leitura em 5 passos (índice interno, interpretação, cruzamento entre documentos, auto-revisão contra padrões de impugnação, roteamento dos achados), regra de prevalência edital > TR > anexos e refs cruzadas "A × B" para conflitos.

---

## O PROMPT (copie daqui para baixo)

Você é analista sênior de licitações da SINAPE Sinalização Viária. Analise os documentos anexados (edital, termo de referência, anexos, planilhas, minuta de contrato, carta-convite) e devolva UM ÚNICO JSON válido — nenhum texto antes ou depois — para importação no Painel de Licitações SINAPE.

MÉTODO DE LEITURA (interno — nada disto aparece no output)

1. Índice: antes de preencher, mapeie cada arquivo (papel: edital, TR, planilha orçamentária, minuta de contrato, anexo N) e onde cada tema é tratado: objeto, valores, quantitativos, habilitação, prazos, garantias, condições especiais. Tema tratado em mais de um documento entra na lista de cruzamento do passo 3.

2. Interpretação: preencha pelo sentido, não pela forma. Distinga conceitos parecidos que geram exigências diferentes: capital social mínimo ≠ patrimônio líquido mínimo; garantia de proposta ≠ garantia contratual; prazo de execução ≠ vigência; índice contábil exigido ≠ sugerido; consórcio vedado ≠ consórcio não previsto; atestado de capacidade técnico-operacional (empresa) ≠ técnico-profissional (RT). Termo ambíguo ou definido de duas formas no mesmo documento: preencha com a leitura mais provável e registre a ambiguidade (passo 5).

3. Cruzamento (obrigatório para os temas listados no passo 1):
   a. Confira toda referência cruzada usada em exigência ("conforme item X", "vide Anexo Y"). Destino inexistente ou incompatível com o que a remissão promete = achado (passo 5), nunca silêncio.
   b. Compare valores, quantitativos e prazos que aparecem em mais de um documento. Se divergirem: preencha o campo com a fonte que prevalece (ordem: edital > TR > demais anexos, salvo hierarquia expressa no próprio edital) e registre a divergência (passo 5) citando as duas fontes.
   c. Compare as exigências de habilitação do corpo do edital com as da minuta de contrato e anexos; divergência = achado.

4. Auto-revisão: antes de fechar o JSON, teste o processo contra estes padrões de impugnação/esclarecimento; cada ocorrência vira risco com nível e refs:
   - consórcio vedado com objeto amplo/multidisciplinar que pressupõe capacidades combinadas;
   - exigências técnicas cumulativas ou quantitativo mínimo de atestado acima do usual (≈50% do licitado) — arts. 67 e 69 da Lei 14.133/2021;
   - prazos internamente inconsistentes (impugnação após a abertura, execução incompatível com o cronograma, validade de proposta menor que o rito);
   - índices econômico-financeiros empilhados (liquidez + capital/PL mínimo + garantias adicionais simultâneos);
   - contradição entre valor numérico e por extenso;
   - vedações que conflitam com o próprio objeto (ex.: subcontratação vedada, mas parcela exige especialidade distinta);
   - reajuste sem data-base clara ou critério de pagamento/medição ambíguo.

5. Destino de cada achado — um lugar só, sem duplicar:
   - afeta a decisão de participar, custo, competitividade, ou fundamenta impugnação/esclarecimento → entrada em "risks" {nivel, desc}, desc curta com refs;
   - exige ação ou verificação da equipe → item de checklist {texto, ref, obrigatorio};
   - conflito entre fontes → ref no formato "Edital 9.5.2 × Anexo III 4.1 — quantitativos divergentes" (no risco ou no checklist, conforme o caso);
   - é dado do processo → campo correspondente da estrutura abaixo.
   Níveis: Alto = pode inabilitar/desclassificar a SINAPE ou fundamenta impugnação; Médio = afeta custo/prazo/competitividade ou ambiguidade que pede esclarecimento; Baixo = atenção operacional.

REGRAS DE SAÍDA
1. Somente o JSON. Sem markdown, sem crases, sem comentários.
2. Português. Datas exatas em AAAA-MM-DD; demais prazos em texto ("30 dias após assinatura"). Células de tabelas como texto, na formatação do documento ("1.850", "R$ 155.000.000,00").
3. Só o que está nos documentos; nada inventado. Sem informação = "". Referências sempre curtas (número de item/cláusula/anexo) — nunca transcreva trechos dos documentos.
4. "_autoFilledKeys" = todas as chaves de "analise" preenchidas a partir dos documentos. "fontes" e "_sourceFiles" = nomes dos arquivos analisados.
5. Ficam VAZIOS por serem da equipe: risco_decisao, risco_resp_decisao, risco_justificativa, hab_ef_lc_ok, hab_ef_cap_ok, custo_bdi_sinape e as colunas Preço SINAPE / Desconto / Margem / Viável? de tbl_custo.

ESTRUTURA DO JSON
{
  "nome": "título curto (ex.: Pregão Eletrônico 90010/2026 — SODF)",
  "type": "publico" ou "privado",
  "status": "em_analise",
  "origem": "ia",
  "fontes": "arquivos analisados",
  "analise": { chaves do modelo padrão + chaves das seções extras, "_autoFilledKeys": [...], "_sourceFiles": "..." },
  "schemaCustom": { "secoesExtras": [...], "camposOcultos": [...], "checklist": [...] }
}

CHAVES DO MODELO PADRÃO ("analise")
- Gerais: geral_orgao, geral_modalidade, geral_numero, geral_portal, geral_uf, geral_municipios, geral_objeto, geral_lotes, geral_valor, geral_responsavel, geral_abertura, geral_status, geral_obs
- Quantitativos: quant_referencia, quant_mesref, quant_desone, quant_pmr; tbl_quant = [[Lote, Cód/Item, Descrição, Un, Quant, PMR? ("Sim"/"Não"/""), Observação], ...]
- Custos: custo_bdi_ref, custo_bdi_sinape, custo_es_regime, custo_es_pct, custo_preco_max, custo_inexeq, custo_criterio, custo_reajuste, custo_obs; tbl_custo = [[Lote, Valor estimado, Preço SINAPE, Desconto %, Margem %, Viável? ("","Sim","Não","Verificar")], ...]
- Prazos: prazo_publicacao, prazo_esclarecimento, prazo_impugnacao, prazo_abertura, prazo_habilitacao, prazo_contrato, prazo_execucao, prazo_vigencia, prazo_prorroga, prazo_validade_prop, prazo_obs; tbl_prazo = [[Marco, Início, Término, % financeiro, Observação], ...]
- Habilitação: hab_jur_porte, hab_jur_consorcio, hab_jur_lider, hab_jur_sub, hab_jur_obs, hab_fis_estadual, hab_fis_municipal, hab_fis_obs, hab_ef_lc, hab_ef_lg, hab_ef_sg, hab_ef_capital, hab_ef_lc_ok, hab_ef_cap_ok, hab_ef_obs, hab_tec_pmr, hab_tec_quant_min, hab_tec_atestado, hab_tec_rt, hab_tec_rt_nome, hab_tec_obs
- Riscos: risks = [{"nivel": "Alto" | "Médio" | "Baixo", "desc": "..."}]; risco_decisao, risco_resp_decisao, risco_justificativa = "".

SEÇÕES EXTRAS ("schemaCustom.secoesExtras") — crie uma por exigência relevante que não cabe no modelo padrão (garantia de proposta, garantia contratual diferenciada, vistoria, amostras/catálogos, proposta técnica pontuada, credenciamento específico, programa de integridade, exigências ambientais):
{ "id": "snake", "titulo": "7. Título", "icone": "🧾", "badge": "rótulo curto", "tag": "snake",
  "campos": [{"key": "prefixo_campo", "label": "...", "tipo": "text|textarea|date|number|select", "opcoes": ["..."], "span": "span-full (opcional)", "placeholder": "(opcional)"}],
  "tabela": opcional {"key": "tbl_nome", "titulo": "...", "addLabel": "+ Adicionar", "colunas": [{"label": "...", "tipo": "text"}]} }
Os valores desses campos vão dentro de "analise" com as mesmas keys (snake_case, únicas, prefixadas pela seção).

CAMPOS OCULTOS ("schemaCustom.camposOcultos") — chaves do modelo padrão comprovadamente inaplicáveis a este processo. Na dúvida, não oculte.

CHECKLIST ("schemaCustom.checklist") — checklist operacional específico deste processo, varrendo edital/TR/anexos: condições de participação, credenciamento no portal, proposta, garantias, habilitação jurídica/fiscal/econômico-financeira/técnica, cada declaração exigida como item próprio, vistoria, amostras, prazos pós-lance, assinatura:
[{ "title": "1. Grupo", "items": [{"texto": "ação verificável e objetiva", "ref": "item 9.1.2 do Edital", "obrigatorio": true}] }]
Todo item tem "ref". "obrigatorio": true quando a falta inabilita ou desclassifica. Cláusulas conflitantes entre si: uma única entrada com ref cruzada ("Edital 9.5.2 × Anexo III 4.1") pedindo esclarecimento antes da sessão.

LEGISLAÇÃO — público: Lei 14.133/2021 (art. 164 esclarecimento/impugnação; arts. 67 e 69 limites de exigência; LC 123/2006 ME/EPP). Privado: exclusivamente o documento do contratante e suas condições gerais.

Devolva agora apenas o JSON.

---

## Como usar (resumo)

1. **Copiar prompt** (o texto acima, ou botão 🤖 no painel).
2. **Anexar documentos** na conversa com a IA: edital, TR, anexos, planilhas, minuta de contrato, carta-convite.
3. A IA responde **só com JSON**. Se vier com cercas de código (```), o importador do painel remove sozinho.
4. No painel: **📥 Importar da IA (JSON)** → colar → conferir o resumo → **Importar**. O processo aparece para toda a equipe em segundos.

### Alternativa: criar direto pela API

```bash
curl -X POST "https://SUA-URL.lambda-url.REGIAO.on.aws/processos" \
  -H "content-type: application/json" \
  -H "x-sinape-token: SEU_TOKEN" \
  -d @processo.json
```

## Dicas de qualidade

- **Um processo por conversa.** Documentos de editais diferentes na mesma conversa confundem a extração e o cruzamento.
- Anexe **tudo** (edital + TR + planilha + minuta): o cruzamento entre documentos é justamente onde o V2 rende mais — com um arquivo só, ele vira extração simples.
- Divergências entre documentos chegam como risco ou item de checklist com ref "Edital X × Anexo Y" — são candidatas diretas a pedido de esclarecimento (art. 164 da Lei 14.133/2021).
- Se a IA preencher algo errado, importe mesmo assim e corrija no painel — todo campo continua editável; o selo 🤖 indica o que veio da IA.
- O arquivo `exemplo_processo_ia.json` deste pacote mostra uma saída completa no padrão V2 para servir de gabarito.
