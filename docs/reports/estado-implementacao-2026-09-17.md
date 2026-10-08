# Estado da implementação — 2026-09-17

Data: 2026-09-17. Versão: EST17-v1. Escopo: retrato aditivo do estado de implementação após a reconciliação Q17-01.A (controle) e a onda de implementação atribuída ao Lead. Estado: **IN_PROGRESS / PARTIAL / NO-GO**.

Candidato: HEAD `b52f32c141916a2ea3af1a6b913bd91f380606e0`, árvore `b205d9cbd1dcb719b4a8c2f5dcd8ac68009f326f`, árvore de trabalho suja (124 entradas). Fontes canônicas: [estado](../../.agent/state.json), [backlog](../../.agent/backlog.json), [ledgers](../../.agent/execution-log.jsonl), [plano ativo](../../.agent/plans/phase-3-runtime-evidence-production-promotion.md), [backlog BL17](../plans/backlog-qualidade-2026-09-17.md). Este documento não altera os quatro documentos Q17 preservados nem cópias de auditoria; é apenas aditivo.

## Estado do plano de controle

- Q17-01.A: status IN_PROGRESS, `active_action_id` `Q17-01.A:RECOVER`, estado revisão 306, `last_event_id` `EVT-Q17-01A-RECON-20260917`, `verification_state` PARTIAL.
- 16 itens da onda de implementação registrados como **VERIFY** com evidência de relatório atribuído (EXTERNAL_RECORD, PARTIAL, freshness UNKNOWN): Q17-08.A, Q17-09.A, Q17-12.A, Q17-13.A, Q17-15.A, Q17-16.A (parcial), Q17-17.A, Q17-18.A, Q17-19.A, Q17-20.A (parcial), Q17-22.A, Q17-23.A, Q17-26.A, Q17-11.A, Q17-14.A (parcial), Q17-06.B (parcial). O pedido citava "12" subtasks, mas enumerava 16 IDs; todos os 16 foram registrados.
- Nenhum item Q17 está DONE além de Q17-01.A permanecer em reconciliação (também não DONE). Nenhum gate foi emitido; `next_gate` segue IMPLEMENTATION_READY e não foi FORJADO.

## Evidência de comandos (executados por este integrador nesta árvore suja)

| Comando | Exit | Contagem / observação |
|---|---|---|
| `make validate` | 0 | boundaries PASS; control-plane PASS (35 itens, 326 eventos, 320 registros de verificação, 27 gates, 30 arquivados + 11 review-history); quality bar PASS |
| `make lint` | 0 | boundary validator, sintaxe Python/Locker JS e lint CVG frontend; sem pytest |
| `make typecheck` | 0 | tsc Professor, tsc CVG frontend, compileall Python; compilação não é tipagem completa |
| `make api16-root` | 0 | 599 passed, 369 warnings |
| `make api16-domain` | 0 | 204 passed |
| `make api16-worker` | 0 | 89 passed, 7 warnings |
| `make api15-professor` | 0 | 60 passed |
| `make api15-provider` | 0 | 76 passed |
| `make jobs-test` | 0 | 44 passed |
| `make compose-static` | 0 | dev e staging renderizam 14 serviços cada; runtime não iniciado |
| `make ops-static` | 0 | checksums de 6 migrações PASS; execução NOT_RUN; 0005 sha256 `58878320223f9f30d42aea840c7e58795eb5c448daf90a0877adedc781cc9774` |
| `make eval-retrieval-pack` | **2** (make; avaliador 1) | **FAIL esperado**: 5 casos (2 positivos, 3 negativos); alpha (`offline-ranker-a`/`synthetic-corpus-a`) Recall@1 **0.5 < 0.75** FAIL; beta 1.0 PASS; agregado 0.75 PASS; 3 negativos PASS. Fixture violada exposta pelo rigor por grupo; thresholds congelados inalterados; reparo é do dono do pack |

Contagens se sobrepõem entre suítes e não devem ser somadas como testes únicos. Nenhum serviço, CI remoto, provider pago, corpus ou reviewer independente foi acionado.

## Áreas tocadas pela onda de implementação

- Ingestão: lotes limitados de embeddings e upserts com contagem/ordem/dimensão/cancelamento; planejador de lotes por bytes serializados e `max_points` configurado (`plan_upsert_batches`), com rejeição pré-I/O de ponto individual oversized; admissão de tamanho de fonte. Testes de contagem usam vetores 2-D; incidência com embeddings reais 1536-D não demonstrada em runtime.
- Retrieval: busca SDK sparse+dense escopada; caminho HTTP canônico segue dense-only (ver defeito 1).
- Professor: rejeição de resposta sem marcador/citação válida.
- Providers: SSE delimitado por bytes, emissão de tool deltas e retry/cancelamento; `finish_reason="tool_calls"` aceito na allowlist e nos contratos (`ChatCompletionResult`/`ChatCompletionChunk`), com regressão ponta a ponta (testes 76 provider; 12 contracts).
- API/contratos: metadata canônica em completion/replay/SSE buffered; parser de chat compartilhado; validação de fronteira.
- Web: parser único no cliente, lib/api.ts, recuperação de UI de documentos.
- Admin/audit: registro durável de pending-completion (ver defeito 2).
- Plataforma: Compose factory/Prometheus, shutdown do worker; migração 0005 (portable JSON count/regex).
- Observabilidade: sink limitado (fila/concorrência/capacidade/discard/shutdown).
- QA: route-policy com corpos válidos, equivalência real em vez de tautologias; decisão conservadora (UNKNOWN) até D04.
- Avaliação: métricas/thresholds por grupo; documentação RAG evaluation.

## Defeitos abertos conhecidos

1. **Retrieval HTTP canônico permanece dense-only** — migração de schema sparse do HTTP-store ausente; prova end-to-end escopada pendente (Q17-09.A).
2. **Registro durável de pending-completion do admin sem reconciliation worker** — ninguém replays os registros (Q17-17.A).
3. **Decision gate escala TODAS as queries para ESCALATE/risk_unknown** até a política de domínio D04 existir; caminho de resposta do produto desabilitado por design (Q17-11.A).
4. **Migração 0005 alterada pós-baseline** — caminho de reparo para instalações que já aplicaram a migração não comprovado; nunca reescrever checksum aplicado (Q17-19.A aberto).
5. **Visual/e2e/live runtime/provider/corpus NOT_RUN/BLOCKED_EXTERNAL** — campanha visual/AA, provider ao vivo e corpus aprovados ausentes.
6. **Observabilidade `timeout=None` mantém entrega síncrona** — a lane limitada com fila finita/descartes não cobre o caminho síncrono; limites não são universais.

## Decisão

**NO-GO.** Nenhuma evidência local, relatório atribuído ou verificação estrutural constitui aceite integrado, revisão independente ou promoção. D01–D05 e D07 permanecem sem decisão; D06 autoriza apenas a reconciliação executada.

## Próximas ações

1. Decisões humanas D01–D05 e D07 (dados/tenants, runtime/secrets/TLS, provider/custo, corpus/política de domínio, SLO/DR, autoridade de promoção).
2. Worker de reconciliação para registros pending-completion do admin (Q17-17.A).
3. Migração de schema sparse do HTTP-store e prova de busca escopada no caminho canônico (Q17-09.A).
4. Dono do pack repara a fixture do eval pack sem enfraquecer thresholds congelados (Q17-14.A).
5. Estratégia e execução de reparo checksum-safe para instalações com 0005 aplicado (Q17-19.A).
6. Campanha visual/AA e evidências de runtime/provider/corpus autorizadas (Q17-16.A, Q17-18.A, Q17-20.A, Q17-24/25/26).

Falha pré-existente do fixture do controlador (6 pass/2 fail em cópia de diretório histórico) permanece registrada, não reproduzida nem "corrigida" aqui.
