# Roadmap de remediação — Reauditoria local 01/10/2026

**Origem:** [`relatorio-auditoria-geral-2026-10-01.md`](reports/relatorio-auditoria-geral-2026-10-01.md). **Estado:** proposta de execução local; não modifica `.agent/` nem estados Q17. **Classificação observada:** `STATE_OF_ART_CANDIDATE / NO-GO`.

## Objetivo

Fechar os gaps locais confirmados na reauditoria, manter um conjunto de testes que proteja migrations/storage/jobs no CI, e só então buscar as autorizações necessárias para evidência integrada. Nota de auditoria não substitui gates nem autoriza uso de credenciais, dados ou serviços externos.

## Princípios

1. Preservar o worktree compartilhado e os três repositórios legados.
2. Tratar migrations por transaction/roll-forward; não editar checksums aplicados.
3. `NOT_RUN`, `BLOCKED_EXTERNAL`, falha ou evidência stale nunca são PASS.
4. Separar implementação local, PostgreSQL descartável e inventário de instalações reais.
5. Não alterar `.agent/`, `.gauntlet/` ou o plano ativo por meio deste roadmap/backlog.

## Marcos

| Marco | Foco | Saída | Dependência |
|---|---|---|---|
| **M0 — Reconciliação documental** | Um caminho claro entre baseline, reauditoria, roadmap e backlog | índice, aliases atuais e README apontam pins atuais/históricos corretamente; score antigo permanece histórico | Nenhuma |
| **M1 — Fronteiras de identidade/schema/CI** | Resolver membership ambígua no login; verificar constraints duplicadas de 0008; integrar suites ausentes à CI com installs reprodutíveis | regressões known-bad pass/fail; CI static/unit cobre jobs, storage e migrations | Revisão técnica local; sem runtime externo |
| **M2 — Regressão local final** | Reexecutar suites isoladas e concorrentes; full web matrix após último CSS | comandos/exit codes/artefatos frescos num snapshot identificado | M1 |
| **M3 — Runtime integrado** | Golden path, stores e identidade no lab descartável | evidência por etapa e por negativo, A/B tenancy e teardown | D01–D04, D02 e ambiente autorizado |
| **M4 — Operação e recuperação** | Collector, alertas, restore/RPO/RTO, performance, chaos, soak | medidas comparáveis com budgets decididos antes da execução | D05 e M3 |
| **M5 — Reauditoria e promoção** | Same-SHA CI, critic independente, packet, riscos e Go/No-Go | classificação derivada e decisão humana para o artefato exato | D07, todas as lanes obrigatórias |

## Saídas por marco

### M0 — Reconciliação documental

- **Concluído neste pacote:** `docs/INDEX.md` aponta para a reauditoria; os aliases antigos estão sinalizados como históricos e preservados; README distingue serviços atuais das imagens históricas Phase 0.6.
- **Verificação pendente:** rerodar `scripts/phase11/check_toolchain.py`, `make validate`, links e `git diff --check` depois de fechar os documentos desta execução.
- Não declarar o arquivo de auditoria como aceite canônico de tarefas do `.agent/`.

### M1 — Identidade, schema e CI

- Definir como o login escolhe workspace quando um usuário tem mais de uma membership no mesmo tenant; rejeitar estado ambíguo ou aceitar seleção explícita limitada a memberships autorizadas.
- Fortalecer migration 0008 para verificar definição/validação exata das constraints quando encontrar nome já existente; testar colisão com constraint incompatível.
- Integrar testes de `packages/jobs`, `packages/storage` e `infrastructure/scripts/tests` a uma lane CI apropriada; usar lock com hashes para as dependências do evaluator.

### M2 — Regressão local

- Reproduzir o evento intermitente de ingestão/telemetria isolado, repetido e em paralelo sem sleeps ou thresholds relaxados.
- Reexecutar a matriz web completa no build final; guardar hashes de screenshots/logs e diferenciar API simulada de API real.
- Rerodar API/domain/worker/coverage após as mudanças M1 e inspecionar todos os artefatos gerados no diff.

### M3–M5 — Gates que dependem de autoridade externa

1. Conferir as decisões D01–D04 e o alcance de D02 antes de executar qualquer service gate.
2. Executar migrations somente no PostgreSQL descartável autorizado, depois preflight e backup; inventário de bases instaladas continua read-only e separado.
3. Observar golden path, réplicas, ACL, provider/corpus, OTel e recovery com evidência vinculada ao mesmo candidato.
4. Definir D05 antes de carga/restore/chaos/soak e D07 antes de assinar ou promover.

## Condições de saída

- Nenhuma falha conhecida de identidade ou integridade cross-scope fica sem reprodução/disposição.
- `make validate`, suites de migration/jobs/storage, suites API/domain/worker e a matriz web atual têm resultados explícitos.
- Runtime, restore, capacity, observability e authority são atuais para o candidato; local fixtures não os substituem.
- Reauditoria atualiza as 26 notas e preserva a distinção entre score técnico e promoção.
