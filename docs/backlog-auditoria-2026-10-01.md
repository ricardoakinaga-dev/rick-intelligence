# Backlog proposto — Reauditoria local 01/10/2026

**Origem:** [`relatorio-auditoria-geral-2026-10-01.md`](reports/relatorio-auditoria-geral-2026-10-01.md) e [`roadmap-auditoria-2026-10-01.md`](roadmap-auditoria-2026-10-01.md). **Estado:** proposta; não é backlog canônico e não atualiza status em `.agent/`.

## Convenções de aceite

- **P0:** necessário antes de declarar promoção; pode depender de autoridade/ambiente.
- **P1:** correção ou validação necessária para entrega integrada confiável.
- **P2:** manutenção documental e operacional.
- Cada conclusão precisa registrar baseline/candidato, comando, exit code, teste discriminante, resultado, limitações e diff revisado.
- Não combinar PASS local com runtime `NOT_RUN`; preservar falhas e tentativas intermediárias.

## Fila priorizada

| ID | Marco | Prioridade | Entrega | Dependências |
|---|---|---:|---|---|
| AUD26-01 | M1 | P1 | Resolver escolha de workspace no login por memberships | Identidade e UX/API contract |
| AUD26-02 | M1 | P1 | Tornar idempotente e fail-closed a detecção de constraint existente em 0008 | Migration tests/DB disposable |
| AUD26-03 | M1 | P1 | Adicionar migration/jobs/storage tests à CI | Lock test/runtime deps |
| AUD26-04 | M1 | P1 | Trocar instalações RAG-EVAL/supply-chain por dependências hash-pinned | requirements/test.lock |
| AUD26-05 | M2 | P1 | Reproduzir e encerrar intermitência `worker.ingestion.published` | Harness determinístico; executar serial/paralelo |
| AUD26-06 | M2 | P1 | Reexecutar matriz Playwright completa no CSS final | Build/frontend runtime autorizado |
| AUD26-07 | M0 | P2 | Reconciliar índice, aliases “atual”, README e notas documentais | Novo relatório/roadmap/backlog |
| AUD26-08 | M3 | P0 | Executar inventário read-only de migrations já aplicadas, como definido pelo plano ativo | D02 e Q17-01.A; sem mutação |
| AUD26-09 | M3 | P0 | Executar golden path multi-tenant com PostgreSQL/Redis/Qdrant/S3/API/worker/provider | D01–D04 e D02 |
| AUD26-10 | M4 | P1 | Medir collector/SLO, restore/RPO/RTO, performance, chaos e soak | D05 e lab aprovado |
| AUD26-11 | M5 | P0 | Rodar CI same-SHA, revisão independente, packet selado e Go/No-Go | D07 e todos os gates obrigatórios |

## Critérios por item

### AUD26-01 — Workspace na autenticação

**Problema:** login seleciona membership por tenant sem campo de workspace; o adapter pode devolver uma linha arbitrária quando há mais de uma membership no mesmo tenant.

**Aceite:** escolha de workspace é explícita e só aceita membership ativa do usuário, ou login rejeita ambiguidade. Testes cobrem duas memberships no mesmo tenant com papéis/grants distintos e provam sessão com scope exato. Refresh de autorização exige a membership exata do contexto. Recovery com `tenant_id` usa apenas uma membership ativa única dentro daquele tenant; recovery sem tenant requer unicidade global. As rotas públicas mantêm resposta neutra quando lookup/token-store ou delivery falham, sem logar email/token ou texto da exceção; erro interno permanece observável por request ID e tipo. Revisar compatibilidade com clientes existentes.

### AUD26-02 — Constraint duplicada na migration 0008

**Problema:** handlers `duplicate_object` seguem sem conferir sempre `pg_get_constraintdef`, tabela/colunas/referência, tipo e `convalidated` da constraint de destino.

**Aceite:** instalação limpa e repetida passam; constraint homônima incorreta ou não validada falha sem inserir o ledger de 0008; associações cross-scope continuam rejeitadas; registros válidos são preservados. Rodar PostgreSQL descartável só sob escopo autorizado.

### AUD26-03 — CI para migrations, jobs e storage

**Problema:** as suites de `infrastructure/scripts/tests`, `packages/jobs/tests` e `packages/storage/tests` não aparecem como passos explícitos no workflow canônico lido.

**Aceite:** mutação known-bad na migration, contrato de job e store falha a lane correspondente; execução fica bounded; live PostgreSQL não é simulada e permanece lane distinta.

### AUD26-04 — Instalação hash-pinned em CI

**Problema:** a lane RAG-EVAL instala packages com pins de versão sem hashes; auditar o scanner e demais installs conforme a política reprodutível.

**Aceite:** workflows instalam do lock requerido com hashes ou justificam e verificam artefatos pinados; teste estático falha quando o lock ou hash é removido.

### AUD26-05 — Corrida de evento de ingestão

**Reprodução:** callback `worker.ingestion.enqueued` retido além do deadline limitado permite o worker continuar; o callback terminal pode chegar antes do callback antigo. Uma captura controlada mostrou `started,published` visíveis enquanto `enqueued` continuava bloqueado. Isso segue o contrato best-effort do sink (`emit_safely` retorna no timeout) e invalida o snapshot imediatamente após o callback terminal como prova de completude.

**Aceite refinado:** com sink saudável e isolado, aguardar a drenagem real da lane e provar uma ocorrência de `enqueued → started → published`, sem timeout/drop. No caso de callback lento, provar com barreira que upload continua até `published`, o limite permanece finito, eventos entregues continuam sanitizados e não exigir ordenação após timeout. Repetir os dois cenários em execução serial e sob carga de testes controlada, sem sleeps arbitrários. Preservar o teste/assertion failure-first quando uma corrida for observada.

### AUD26-06 — Web matrix do artefato final

**Aceite:** executar build final + todas as rotas/estados exigidos em 375/768/1440; inspecionar screenshots, console/network, foco/teclado e axe; marcar explicitamente rotas com API simulada e obter review independente com fingerprint.

### AUD26-07 — Toolchain no README

**Concluído em documentação local:** `docs/INDEX.md` aponta para a auditoria de 01/10, roadmap/backlog anteriores estão sinalizados como históricos e o README agora distingue pins atuais e históricos; os relatórios 72/80 permanecem preservados.

**Verificação pendente:** rerodar `scripts/phase11/check_toolchain.py`, `make validate`, links e `git diff --check` após concluir a atualização dos documentos de resultado.

### AUD26-08 a AUD26-11 — Ambiente, operação e decisão

Não executar sem decisão aplicável: D02 inventário read-only somente; D01–D04 para dados/provider/corpus/runtime; D05 para operação/cargas; D07 para autoridade de revisão/assinatura/promoção. O aceite exige evidência crua atual, limites de recurso, escopo descartável, teardown e binding ao mesmo candidato.

## Rastreabilidade

| Achado | Item |
|---|---|
| Membership workspace ambígua | AUD26-01 |
| Constraint 0008 preexistente de definição divergente | AUD26-02 |
| CI sem suites completas de infraestrutura | AUD26-03 |
| Installs CI sem hash lock | AUD26-04 |
| Corrida de evento | AUD26-05 |
| Matriz web não repetida no snapshot final | AUD26-06 |
| Drift do índice/roadmap/README | AUD26-07 |
| História de migrations instalada e runtime completo | AUD26-08/AUD26-09 |
| Telemetria/DR/capacidade | AUD26-10 |
| Review/selo/Go-No-Go | AUD26-11 |
