# Backlog executável — RICK Intelligence (auditoria 27/09/2026)

**Data-base:** 27/09/2026. **Versão:** BL27-v1. **Origem:** [relatório de auditoria geral](reports/relatorio-auditoria-geral-2026-09-27.md) e [roadmap](roadmap-auditoria-2026-09-27.md).

**Referências:** catálogos Q17/Q24 ([backlog Q24](backlog-qualidade-2026-09-24.md)) continuam donos do estado histórico. Estas tarefas **R27** identificam o trabalho remanescente da fotografia de 27/09; não duplicam nem encerram Q17/Q24 — reutilizam os itens canônicos equivalentes sempre que representarem o mesmo resultado.

## 1. Convenções

- **Prioridade:** P0 = segurança/isolamento/uso básico; P1 = completar produto/validação; P2 = endurecimento/qualidade. Prioridade não afirma incidente.
- **Porte:** P = ajuste localizado; M = mudança de fronteira/fluxo; G = integração/campanha com checkpoints.
- **Dependências D01–D07:** ver [plano executivo](plano-executivo-qualidade-2026-09-24.md); condicionam apenas o efeito dependente.
- **Aceite:** só fecha no controle canônico com ID, candidato (commit/tree), arquivos/hashes, ambiente, comando/procedimento, exit code, resultado, artefatos sanitizados, revisão e recuperação.
- **Nunca:** editar evidência histórica, transformar erro em sucesso, descartar resultado negativo, apagar alterações alheias ou falsificar checksum.

## 2. Fila priorizada

| ID | Marco | Prioridade | Porte | Dependências | Decisão externa |
|---|---|---|---|---|---|
| R27-01 | M1 | P1 | P | nenhuma | — |
| R27-02 | M1 | P1 | P | nenhuma | D02 (imagem final) |
| R27-03 | M1 | P2 | P | nenhuma | — |
| R27-04 | M1 | P2 | P | nenhuma | — |
| R27-05 | M1 | P2 | P | nenhuma | — |
| R27-06 | M1 | P2 | P | nenhuma | — |
| R27-07 | M2 | P1 | M | R27-06 | D07 |
| R27-08 | M3 | P0 | G | R27-02 | D01, D02, D03 |
| R27-09 | M3 | P1 | G | R27-08 | D01, D02 |
| R27-10 | M4 | P1 | G | R27-09 | D01, D02, D05 |
| R27-11 | M4 | P1 | G | R27-08 | D03, D05 |
| R27-12 | M4 | P1 | G | R27-10, R27-11 | D01, D02, D05 |
| R27-13 | M5 | P0 | M | R27-08 | D04 |
| R27-14 | M5 | P1 | G | R27-13 | D07 |
| R27-15 | M5 | P1 | M | R27-14 | D02, D07 |

## 3. Tarefas M1 — Hardening e higiene

### R27-01 — CSRF com nonce por sessão
**Origem:** seção 4 da auditoria; `apps/api/src/core/csrf.py:96`. **Entregar:** token CSRF por sessão com nonce (não estático/vazio) em produção; manter comportamento local/test. **Aceite:** produção não aceita token CSRF vazio; regressão de sessão/cookie passa. **Prova:** testes de CSRF com relógio/rolação de nonce, `make api16-root`.

### R27-02 — Credencial scoped no bootstrap do MinIO
**Origem:** `docker-compose.dev.yml:126-127` (init usa credencial de root também usada pelos serviços). **Entregar:** credencial de bootstrap separada e scoped APENAS para criação de bucket; remover root do init. **Aceite:** init não detém credencial de root; serviços usam keys scoped (`150-151`). **Prova:** `make compose-static` + inspeção de manifests/CI.

### R27-03 — Eliminar duplicação de diálogos frontend
**Origem:** `ui.tsx` vs `admin-management.tsx` (`ConfirmDialog`/`AdminConfirmDialog`); helper `errorMessage` 4×. **Entregar:** consolidar em um único `ConfirmDialog` e um único `errorMessage`. **Aceite:** sem divergência de comportamento entre telas; build/typecheck verdes. **Prova:** `make web-lint`, `make web-typecheck`, `make web-build`.

### R27-04 — Pin de ações GitHub nas workflows legadas
**Origem:** `phase-1.x.yml`/`phase-0.6.yml` usam `actions/checkout@v4` sem versão. **Entregar:** pin exato (`@v4.2.2`, etc.) alinhado ao `quality.yml`; `--require-hashes` onde instala. **Aceite:** consistência de pin em todas as workflows. **Prova:** validação estática + `make validate`.

### R27-05 — Reconciliar `toolchain.json`
**Origem:** Qdrant 1.7.4/Redis 7.0.15 no toolchain vs 1.12.5/7.4 no compose. **Entregar:** versões canônicas únicas (documentar a decisão de qual é autoritativa). **Aceite:** sem drift; referência única. **Prova:** `make compose-static` + checagem de referências.

### R27-06 — Explicitar `retrieval_mode` na composição
**Origem:** `apps/api/src/services/external_composition.py:424` depende do default `auto`. **Entregar:** fixar `retrieval_mode` explicitamente (ou documentar por que `auto` é desejado). **Aceite:** modo efetivo não depende de default implícito. **Prova:** testes de composição + `make api16-root`.

## 4. Tarefas M2 — Autoridade (A24-09)

### R27-07 — Conectar/explicitar executores dos gates finais
**Origem:** `triple_aaa_verify.py:513,541,544` — `lab-readiness`, `independent-reviews`, `production-runtime` sem comando. **Entregar:** para cada lane, ou (a) comando/produtor real com fonte de aceite, ou (b) especificação documentada do processo humano e da evidência aceita. **Aceite:** nenhuma lane obrigatória permanece ambígua; cada uma tem dono e evidência vinculada ao candidato. **Prova:** `make triple-aaa-verify` reflete as lanes corretamente; sem PASS sintético. **Decisão:** D07 (autoridade de revisão/final).

## 5. Tarefas M3 — Prova operacional (A24-10 + resíduo A24-06)

### R27-08 — Fluxo golden ponta-a-ponta em ambiente descartável
**Origem:** A24-10; áreas 8, 11–13, 15–16, 18–22. **Entregar:** upload → objeto → job → worker → parse → chunk → embed → Qdrant → publish → retrieval → evidence → Professor → decision → resposta citada → histórico, com serviços reais e lineage registrado. **Aceite:** fonte/coleção corretas, job processado, pontos indexados, resposta fundamentada com citação verificável, histórico consistente; caminho negativo (fonte insuficiente/acesso negado) também exercitado. **Prova:** harness real + observação de navegador; nada de interceptação substituindo a operação principal. **Decisão:** D01, D02, D03.

### R27-09 — Reconciliação do outbox administrativo ponta-a-ponta
**Origem:** A24-06 (parcialmente endereçado pelo consumidor). **Entregar:** exercitar falha de sink, restart, consumidores concorrentes e dead-letter no fluxo real composto. **Aceite:** pendências são reconciliadas sem duplicação nem perda silenciosa; status de API reflete o resultado real. **Prova:** integração PostgreSQL/worker real com falha injetada. **Decisão:** D01, D02.

## 6. Tarefas M4 — Medição operacional

### R27-10 — Restore e RPO/RTO medidos
**Origem:** área 24. **Entregar:** seed → backup → destroy → restore → verify com contagens/digests/consultas; medir perda e tempo reais. **Aceite:** documentos, fontes, histórico, permissões e pendências coerentes; backup incompleto/corrompido detectado. **Prova:** `make phase3-restore-runtime` com harness concreto. **Decisão:** D01, D02, D05.

### R27-11 — Capacidade, latência e custo medidos
**Origem:** área 24; Q17-24.B. **Entregar:** p50/p95/p99, primeiro token, throughput, fila, memória em 1/10/50/100 concorrência. **Aceite:** cargas previstas atendem budgets aprovados; gargalo e limite de admissão conhecidos. **Prova:** `make phase3-performance` com séries suficientes. **Decisão:** D03, D05.

### R27-12 — Caos e estabilidade prolongada
**Origem:** área 24; Q17-24.C. **Entregar:** faults de dependência/rede/processo, reinícios, saturação + janela de estabilidade. **Aceite:** ausência de corrupção/efeitos duplicados; memória/filas limitadas; recuperação observada. **Prova:** `make phase3-chaos`, `make phase3-soak`. **Decisão:** D01, D02, D05.

## 7. Tarefas M5 — Domínio e promoção

### R27-13 — Política de domínio clínico (D04)
**Origem:** A24-02 residual; `request_policy.py` é allowlist técnico não-clínico. **Entregar:** política de domínio revisada substituindo o allowlist, sem liberar resposta indevida; persistir versão/motivo. **Aceite:** consultas permitidas alcançam ANSWER fundamentado; risco/ambiguidade continuam conservadores; implementador não auto-atribui aceite clínico. **Prova:** testes determinísticos positivos/negativos + revisão de domínio. **Decisão:** D04.

### R27-14 — Revisão independente e reauditoria
**Origem:** A24-09; Q17-26.D. **Entregar:** revisão com contexto fresco por revisor distinto; reproduzir achados; recalcular as 26 áreas. **Aceite:** zero achado crítico/alto impeditivo; relatório diferencia observado/parcial/desconhecido. **Prova:** CI do candidato + pareceres + matriz. **Decisão:** D07.

### R27-15 — Decisão de promoção
**Origem:** A24-09/A24-10. **Entregar:** consumir evidências reais do candidato revisado; obter assinatura/decisão válida quando requerida. **Aceite:** `make triple-aaa-verify` aprova o conjunto correto; missing/stale/tampered/autoaprovação reprovados. **Prova:** pacote íntegro + resultado dos gates + decisão registrada. **Decisão:** D02, D07.

## 8. Rastreabilidade

| Achado auditoria 27/09 | Tarefas |
|---|---|
| A24-09 (gates sem executor) | R27-07, R27-14, R27-15 |
| A24-10 (operação distribuída) | R27-08, R27-10, R27-11, R27-12 |
| A24-06 (resíduo: ponta-a-ponta) | R27-09 |
| CSRF token vazio | R27-01 |
| Root credential MinIO | R27-02 |
| Duplicação de diálogos | R27-03 |
| Actions não-pinadas | R27-04 |
| Drift toolchain | R27-05 |
| `retrieval_mode` implícito | R27-06 |
| Política clínica (D04) | R27-13 |

## 9. Catálogo de validação

| Camada | Comandos | Limite da prova |
|---|---|---|
| Estática/higiene | `make validate`, `make compose-static`, `make lint`, `make typecheck`, `make web-lint/typecheck/build` | não executam produto distribuído |
| Domínio/API | `make api16-root`, `make api16-domain`, `make api16-worker`, `make api15-*` | conferir mocks/stores |
| Runtime (externo) | `make phase3-postgres-runtime`, `phase3-redis-runtime`, `phase3-object-qdrant-runtime`, `phase3-golden-runtime` | requer endpoints/credenciais reais |
| Operação | `make phase3-restore-runtime`, `phase3-performance`, `phase3-chaos`, `phase3-soak` | não executar sem escopo/limites/autoridade |
| Promoção | `make triple-aaa-verify`, `make triple-aaa-capability-matrix` | selo/autoridade humanos externos |

## 10. Retomada e limite

Ao retomar após interrupção, observar o efeito já ocorrido antes de repetir upload, migração, mutação administrativa ou publicação. Uma tarefa bloqueada deve indicar exatamente o recurso/decisão ausente; não impede trabalho independente, mas não pode receber DONE.

**Limite deste backlog:** define escopo, dependências e aceite propostos. O estado real permanece no controle canônico (`.agent/`, `.gauntlet/`); a inclusão de progresso aqui não encerra tarefa nem autoriza promoção.
