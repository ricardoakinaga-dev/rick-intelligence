# State of Art Program — living execution plan

## Goal and authorization

Construir e promover o RICK Intelligence como plataforma State of the Art / AAA:
API root segura, runtime durável, ingestão e retrieval grounded, web canônica,
operação observável e gates de qualidade atuais, preservando os três sistemas
filhos. A instrução explícita do usuário autoriza execução local contínua; não
autoriza criação de credenciais, deploy externo, alteração dos children ou
fabricação de evidência.

## Recovery result

- Docs root: 91 arquivos lidos integralmente durante discovery.
- Worktree: dirty, com mudanças aditivas de Phase 1.5/1.6; nenhuma mudança
  existente foi descartada.
- `.agent/state.json`, `.orchestrate/state.json` e `.gauntlet/state.json` estavam
  atrasados ou apontando para runs anteriores. Runs históricos permanecem
  intactos; este plano e `.gauntlet-state-of-art/` são o controle atual.
- `make validate`: PASS.
- Baseline `make api16-full`: inicialmente FAIL em parity de identidade;
  causa corrigida em `packages/knowledge/src/rick_knowledge/identity.py`.
- Teste direcionado após a correção: `10 passed`.
- Docker não está disponível no ambiente atual; Google Chrome está disponível.
- Current foundation matrix after the fix: `make api14-full`, `make api15-full`,
  `make api16-full`, `make api-security`, `make api-contract`, `storage-test`,
  `api16-worker`, retrieval evaluation and `ops-static` all pass; preserved
  child focused checks remain clean.
- Current implementation wave: SQLite knowledge/vector/audit/job-journal
  restart adapters, private local object storage, bounded durable queue,
  hermetic Qdrant/Redis adapters, provider budgets/circuit breaker, redacted
  observability primitives, offline retrieval fixture, CSRF/origin checks,
  configured chat rate limiting, offline release-integrity gate, and root
  `apps/web` lifecycle/search/admin/document-filter slice with 16 Playwright
  passes and 2 intentionally skipped duplicates.

## Frozen Quality Bar v1

O bar executável está em `.gauntlet-state-of-art/bar.json`. Nenhum item crítico
ou alto pode permanecer sem evidência atual no gate final. A web exige render
real em 375/768/1440px, acessibilidade WCAG AA e score visual >=95 por critic
independente; código ou screenshot antigo não substitui render atual.

## Current round — R1/R2 bounded implementation

### Ownership

- Lead: `.agent/**`, `docs/plans/**`, `.gauntlet-state-of-art/**`, contratos
  compartilhados e integração final.
- Domain builder: `packages/knowledge/**`, `packages/ingestion/**`,
  `packages/retrieval/**`, com handoff explícito de contratos.
- API/worker builder: `apps/api/**`, `apps/worker/**`, scripts da fase, sem
  editar UI.
- Web builder: exclusivamente `apps/web/**`, sem editar children ou packages.
- Ops/security builder: `infrastructure/**`, `.github/workflows/**`, scripts
  próprios e docs operacionais, sem tocar contrato durante uma wave ativa.
- Critic: leitura apenas, sem descendentes, sem `.gauntlet*` writes.

### Immediate tasks

1. Executar critics frescos e read-only contra o artefato local integrado,
   usando o bar congelado e sentinel de mutação.
2. Quando houver ambiente autorizado, fechar o spine externo: Postgres, object
   storage/broker, Qdrant/Redis/provider live e recovery multi-instância.
3. Fechar qualidade operacional: corpus aprovado, freshness/thresholds,
   collectors, backup/restore, RTO/RPO, performance e rollback.
4. Reexecutar o bar completo com fingerprint de checkout limpo após cada wave;
   o critic anterior foi invalidado por mutação e não é aprovação.

### Stop rules

Parar uma rodada quando não houver gap material com hipótese testável, quando a
mudança exigir autoridade externa, ou quando o ambiente impedir evidência. Não
converter falta de Docker/serviço/credencial em PASS; registrar `NOT_RUN` ou
`BLOCKED` e continuar nos caminhos herméticos seguros.

## Verification matrix

| Camada | Comando/evidência | Frequência |
| --- | --- | --- |
| Boundaries | `make validate`, `git diff --check` | a cada wave |
| Root phases | `make api14-full`, `make api15-full`, `make api16-full` | após mudanças de packages/API |
| Contract/security | `make api-contract`, `make api-security`, phase verify | após routes/contracts |
| Web | `npm run lint`, `npm run build`, Playwright root, screenshots | cada slice visual |
| Runtime | compose/integration/live adapters, quando disponíveis | antes de promoção |
| Independent judgment | fresh critic + mutation sentinel | após integração e final |
