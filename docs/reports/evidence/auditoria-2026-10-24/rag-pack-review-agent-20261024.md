# AUD24-044 — revisão do pack por agente (não humana)

**Data:** 24/10/2026. **Revisor:** agente de IA autorizado pelo usuário. **Veredito:** **REJEITADO** como pack representativo e como aprovação de AUD24-044.
**Escopo:** revisão técnica/estrutural de schema, consistência e harness. **Não** é revisão clínica, de domínio, de release ou de produção.

## Veredito

O avaliador retorna `PASS`, mas isso só prova consistência interna do fixture. O pack **não** demonstra qualidade de retrieval, citação, abstenção ou ACL e não atende à composição/labels/thresholds do D04. No máximo, é um **smoke test estrutural**, fora do escopo de AUD24-044.

## Bloqueadores encontrados

1. **Casos positivos clonados e métricas tautológicas.** Os 9 positivos têm a mesma estrutura: 2 resultados, 2 relevantes, 0 distratores, 2 claims e latência fixa. `results == relevant_ids` e `citations == relevant_ids`, então hit@1/recall@2/precision/recall são verdadeiros por construção.
2. **Corpus sem texto.** `corpus` contém apenas metadados; não há `text`/`content`. Os arquivos `source` citados (`aud24-01.txt` etc.) não existem. Não é possível auditar relevância, entailment ou faithfulness.
3. **Abstenção não medida.** Os 3 negativos são placeholders sem `context`, `corpus`, `claims` ou latência; não há campo de resposta/abstenção. O `unsupported_claim_rate` só olha claims dos positivos; uma resposta inventada sem citação passaria.
4. **ACL não exercitada.** O chunk estrangeiro só aparece em `corpus`, nunca em `results`/pré-filtro; `leakage=0` é ausência de evidência, não prova de filtragem. Faltam os 2 casos cross-tenant do D04.
5. **Manifest não implementa os thresholds do D04.** Usa hit@1/recall@2 e p95≤100 ms; o D04 propõe hit@3≥0,90, precision≥0,95, recall≥0,90, unsupported≤0,05 e latência descritiva. Também há threshold de faithfulness não previsto.
6. **Proveniência frágil.** Checksums `sha256:...` não são digests válidos; fontes ausentes; latência fixa apresentada como observada.
7. **Aprovação por agente não registrada no D04/backlog.** O contrato ainda exige autoridade de domínio/humana; uma revisão de agente precisa de emenda formal e não pode preencher a assinatura humana.

## O que o pack pode ser

- **Smoke test estrutural** de schema e do harness, explicitamente sem validade clínica.
- Não pode ser chamado de representativo, aprovado, nem usado para fechar AUD24-044.

## Mudanças mínimas antes de nova revisão

- materializar corpus textual sintético com fonte, licença e checksum real;
- redesenhar 12 casos em estratos (single-hop, multi-hop, distrator, top-1 erra/top-3 recupera, abstenção real, ACL pré-filtro, claim não suportado, limite);
- medir abstenção/resposta e claim não suportado de verdade;
- alinhar manifest aos thresholds do D04;
- registrar a revisão por agente como exceção formal, sem alegar aprovação humana.

**Conclusão:** AUD24-044 permanece **BLOCKED_EXTERNAL**. O pack candidato fica como smoke, não como aprovação.
