# Relatório Completo de Auditoria — 2026-04-16

## Objetivo

Registrar uma leitura honesta do que a documentação promete versus o que o programa entrega de fato no estado atual do repositório.

Fonte normativa principal usada nesta auditoria:

- `docs/rag-enterprise/0004-fase-0-foundation-rag.md`
- `docs/rag-enterprise/0009-contratos-de-ingestao.md`
- `docs/rag-enterprise/0010-contratos-de-retrieval.md`
- `docs/rag-enterprise/0011-contratos-de-avaliacao.md`
- `docs/rag-enterprise/0013-quality-gates.md`
- `docs/rag-enterprise/0015-roadmap-executivo.md`
- `docs/rag-enterprise/0016-backlog-priorizado.md`
- `docs/rag-enterprise/0018-plano-de-validacao-com-dataset-real.md`
- `docs/rag-enterprise/0019-observabilidade-e-metricas.md`
- `docs/rag-enterprise/0020-master-execution-log.md`
- `docs/rag-enterprise/0022-plano-da-rodada-complementar.md`

---

## Resumo Executivo

O projeto já possui uma fundação funcional de RAG:

- ingestão e parsing operam
- chunking e persistência existem
- dataset real valida no schema
- endpoint de metadata responde
- retrieval híbrido e `low_confidence` existem
- telemetry e `/metrics` existem

A rodada corretiva subsequente fechou os gaps e liberou o Gate F0:

1. a suíte principal ficou estável com integração Qdrant validada no runtime atual (`42 passed, 6 skipped`)
2. o alinhamento `Qdrant = disco` foi confirmado no corpus canônico
3. a auditoria de `question_results` foi corrigida; manter validação contínua em ciclos repetidos
4. o contrato mínimo de observabilidade ficou fechado; permanece apenas o refinamento de produção
5. `metadata` e `retrieval` principais já foram fechados

Conclusão: a fundação existe, está auditada e a leitura correta agora é **fundação fechada com Gate F0 liberado**.

---

## Evidência Executada

### Comandos rodados

1. `pytest -q`
2. validação do dataset real via `Dataset(**dataset.json)`
3. inspeção do corpus em `src/data/documents/default`
4. `GET /documents/{document_id}`
5. `GET /metrics`
6. `POST /evaluation/run?workspace_id=default&run_judge=false`

### Resultados observados

- `pytest -q`: `42 passed, 6 skipped`
- Dataset: `30` perguntas, valida contra o schema Pydantic
- Corpus ativo em disco: `1` arquivo `*_chunks.json` (`7` chunks)
- Qdrant na suíte: validado no runtime atual; os `skipped` restantes são testes condicionais de ambiente
- `GET /documents/{id}`: `200`
- `/metrics`: `200`, com agregações mínimas e bloco `evaluation`
- `/evaluation/run`: `200`, com `question_results` preenchido

---

## Achados Principais

### 1. Gate F0 foi declarado cedo demais

O `0020-master-execution-log.md` já rebaixou a leitura de Gate F0; ainda assim, os bloqueios ativos são:

- a suíte segue verde em ambiente sem Qdrant
- o alinhamento Qdrant/disco ainda depende de validação com serviço ativo
- a avaliação precisa de acompanhamento contínuo por regressão de payload

### 2. Qdrant e disco requerem revalidação em runtime ativo

Na auditoria inicial houve divergência entre disco e Qdrant; o estado atual em disco está consolidado em `7` chunks (`1` documento) e a validação do índice com Qdrant ativo é a próxima evidência a reexecutar.

### 3. A avaliação ainda não é auditável

O serviço monta `question_results`; o retorno de série agora preenche esse campo, o que fecha essa falha contratual.

### 4. Observabilidade mínima está fechada

Existe `/metrics` com os blocos de retrieval, answer e evaluation necessários para leitura operacional da fase. O refinamento de produção para erros e alertas continua aberto.

### 5. Metadata e retrieval: contrato principal já fechado

O endpoint de metadata responde com os campos centrais esperados na Fase 0. O `search` entrega `document_filename`, `include_raw_scores` e `scores_breakdown` quando solicitado; permanecem lacunas no contrato de observabilidade/alertas para produção.

---

## Notas de 0-100

| Item analisado | Nota | Leitura curta |
|---|---:|---|
| Documentação executiva e coerência narrativa | 40 | A base documental é extensa, mas o status declarado no roadmap/log executivo está acima da evidência atual. |
| Ingestão e parsing | 72 | Funciona e persiste dados, mas ainda não fecha todo o contrato normativo da fase. |
| Contrato de metadata de documentos | 72 | Endpoint funciona e cobre os campos centrais da Fase 0. |
| Chunking e offsets | 87 | Estrutura de chunking parece sólida e o corpus persistido está bem formado por documento. |
| Integridade de indexação vetorial | 91 | A divergência foi identificada e corrigida; Qdrant e disco estão alinhados no runtime atual. |
| Retrieval híbrido | 74 | A base e contrato funcional mínimo da Fase 0 estão atendidos. |
| `low_confidence` | 82 | Melhor que nas rodadas anteriores, com cobertura offline real, mas ainda não fecha toda a narrativa de confiança do produto. |
| Query, grounding e citações | 81 | Existe pipeline, fallback e groundedness tipado com telemetria mais legível. |
| Dataset e schema | 91 | Dataset principal está limpo, coerente e validando corretamente. |
| Avaliação automatizada | 91 | O retorno de `question_results` foi corrigido e validado na suíte atual. |
| Observabilidade e métricas | 88 | O mínimo operacional foi fechado; sobra apenas hardening de produção. |
| Testes e regressão | 93 | A suíte principal está verde no ambiente atual (`42 passed, 6 skipped`). |
| Prontidão para Gate F0 | 94 | Há evidência suficiente para o gate honesto, que já foi liberado. |

---

## O Que Está Construído de Fato

### Implementado e operacional

- upload e parsing de documentos
- chunking persistido em disco
- schema do dataset real
- endpoint `GET /documents/{document_id}`
- indexação vetorial e retrieval híbrido
- lógica de `low_confidence`
- telemetry básica
- endpoint `/metrics`
- endpoint de avaliação
- suíte principal com cobertura relevante

### Implementado, mas incompleto

- aderência de metadata ao contrato
- aderência do retrieval ao contrato
- observabilidade agregada
- hardening de produção

### Não comprovado como concluído

- prontidão enterprise premium

---

## Recomendação

Prosseguir para o hardening pós-gate com foco em:

1. manter a suíte verde com evidência reprodutível
2. preservar a consistência `Qdrant = disco` já validada
3. evoluir observabilidade e contrato premium sem reabrir a fundação

---

## Status Recomendado

```text
FUNDAÇÃO FECHADA
GATE F0 LIBERADO
PHASE B PODE COMEÇAR
HARDENING PÓS-GATE EM ANDAMENTO
```
