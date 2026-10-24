# Baseline de planejamento para produção — 12/10/2026

**Estado:** snapshot derivado da auditoria desta sessão; não é nova execução nem aprovação de produção. **Candidato observado:** `48e383c25ca4af32aa7ffe7e2367360ca9742c58`. **Observação final da auditoria:** 2026-10-12T03:45:17Z, checkout limpo. O relatório completo foi entregue ao solicitante nesta sessão; este sumário portátil registra a origem do [roadmap](<../roadmap-producao-2026-10-12.md>) e do [backlog proposto](<../backlog-producao-2026-10-12.md>).

## Evidência observada, não previsão

| Verificação | Resultado observado |
|---|---|
| Suíte Python ampliada | FAIL, exit 1: 7.713 passed, 6 failed, 221 skipped, 75 warnings, 88 subtests passed; 522,02 s |
| Cinco falhas VPS | Hipóteses ambientais confirmadas: `/tmp` 0755 sem sticky bit, owners 65534 em `/usr`/`/proc`, `chown` de GID retornando EINVAL; não convertidas em PASS |
| Sexta falha Python | Inventário canônico Node inclui segundo manifesto versionado; rerun isolado também FAIL, exit 1 |
| `make validate` | FAIL, exit 2: estado de controle vinculado a outro caminho de checkout |
| Web lint / TypeScript | PASS, exit 0 |
| Vitest | PASS, exit 0: 76 testes; 92,14% linhas e 81,55% branches somente na allowlist de 509 linhas |
| Mypy | PASS, exit 0: 13 arquivos de contratos/autorização, não todo Python |
| `pip check` | PASS, exit 0 |
| Fronteiras, links, imagens declaradas e Actions | Checks isolados PASS, exit 0; 751 links sem erro |
| Avaliação retrieval offline | PASS, exit 0: 2 casos positivos/3 negativos registrados; nenhum provider/store real |
| Probes adicionais | Logout, busca, cardinalidade e duas corridas do worker reproduzidos hermeticamente |

Ambiente: Python 3.12.3, pytest 9.0.3, Node 24.20.0 e npm 11.19.0. O [contrato de toolchain](<../../toolchain.json>) declara Node 22.19.0 e npm 10.9.3: repetir a verificação no ambiente declarado. A suíte foi executada sem configurações/chaves externas herdadas e com `PYTHONDONTWRITEBYTECODE=1` e `-p no:cacheprovider`. Skips não são prova de runtime.

Não executados nessa auditoria: build atual, browser/axe/AT, scans atuais de CVEs/imagens, PostgreSQL/Redis/Qdrant/S3/IdP/provider reais, carga, restore integrado, SIGTERM real, chaos/soak e corpus hostil isolado. Docker instalado não é autorização nem prova de disponibilidade desses serviços.

## Achados e namespace

`AUD12-Axx` refere-se a **12/10**, nunca ao achado homônimo de 07/10. IDs AUD07 e seus resultados anteriores não são renumerados.

| Origem | Achado | Tipo de prova | Fonte principal |
|---|---|---|---|
| AUD12-A01 | Logout PostgreSQL silencia falha de revogação e responde sucesso | HTTP hermético: adaptador PG com falha injetada, backing de sessão em memória; não PG real | [postgres_identity](<../../apps/api/src/services/postgres_identity.py#L182-L186>), [rota](<../../apps/api/src/routes/auth.py#L252-L260>) |
| AUD12-A02 | Segundo shutdown declara drain com handler ainda ativo | Probe concorrente com fila fake; fechamento de stores é inferência do código | [runtime](<../../apps/worker/runtime.py#L1663-L1697>), [composição](<../../apps/worker/deployment_composition.py#L285-L309>) |
| AUD12-A03 | Claim em voo admite handler após shutdown concluído | Probe concorrente confirma início, não ACK/publicação | [runtime](<../../apps/worker/runtime.py#L1438-L1514>) |
| AUD12-A04 | Search não consulta rate limiter | Duas buscas HTTP 200 com limiter sempre negativo, zero chamadas ao limiter | [search](<../../apps/api/src/routes/search.py#L140-L160>) |
| AUD12-A05 | Chave composta permite spray; limiter local retém chaves sem limite global | Inspeção das chaves + 1.000 chaves sintéticas retidas; limiter local não é admitido em produção | [auth](<../../apps/api/src/routes/auth.py#L163-L178>), [rate_limit](<../../apps/api/src/core/rate_limit.py#L97-L111>) |
| AUD12-A06 | Validate bloqueado por raiz de controle diferente | Exit 2; portabilidade/recuperação, não prova de CI remoto quebrado | [restore_control_inputs](<../ci/restore_control_inputs.py#L163-L175>) |
| AUD12-A07 | Rascunhos de revisão/feedback atravessam casos | Inspeção estática; reproduzir em browser com módulo habilitado | [cases](<../../apps/web/components/cases/case-workspace.tsx#L120-L199>) |
| AUD12-A08 | Chat ignora paginação além de 50 conversas/100 turnos | Inspeção estática; não é perda de dados no backend | [adapter](<../../apps/web/components/chat/chat-adapter.ts#L24-L27>) |
| AUD12-A09 | Selo verde de autorização aparece mesmo após 403 | Inspeção estática; UX enganosa, não bypass de autorização | [chat](<../../apps/web/components/chat/chat-workspace.tsx#L766>) |
| AUD12-A10 | Retry publicado não atualiza catálogo | Inspeção estática; browser pendente | [documents](<../../apps/web/app/app/documents/page.tsx#L143-L145>) |
| AUD12-A11 | Tipos/cobertura têm denominadores pequenos; módulos grandes | Configurações/resultados/inventário, não prova de defeito por tamanho | [mypy](<../../mypy.ini#L8-L9>), [vitest](<../../apps/web/vitest.config.ts#L10-L13>) |
| AUD12-A12 | Drift documental e toolchain efetiva distinta | Docs CSRF/histórico divergem; Node/npm fora do contrato | [api-security](<../architecture/api-security.md#L44-L46>), [canonical-web](<../architecture/canonical-web.md#L51>) |
| AUD12-A13 | Snapshot versionado quebra inventário Node canônico | Teste global e isolado falham, dois manifestos em Git | [inventário](<../../scripts/state_of_art/tests/test_frontend_supply_runtime.py#L208-L214>), [snapshot](<../../.runtime/production-local-20261004/source/apps/web/package.json>) |

Hipóteses adicionais ainda dependem de prova: CSRF sob injeção de cookie/subdomínio e foco do drawer após resize. A hipótese de mudar filtro de coleção durante upload foi descartada porque esse controle fica desabilitado; não criá-la como bug confirmado.

## Continuidade e limites

O [backlog AUD07](<../backlog-auditoria-2026-10-07.md>) e a [retomada de 09/10](<retomada-2026-10-09.md>) registram trabalho local anterior; ele não deve ser refeito automaticamente. AUD07-27 e 43 seguem com aceite pendente; 28–42 exigem evidência externa. O novo plano adiciona correções/revalidações e vincula as provas faltantes sem conceder aceite aos IDs antigos.

A revisão independente aprovou o **relatório**, não o produto. Notas locais não são o scorecard tipado do pacote de promoção. A [integridade de release](<../architecture/release-integrity.md#L169-L181>) exige evidência atual e critérios próprios; não derivar GO da média da auditoria.

**Decisão preservada:** NO-GO. Este arquivo só registra evidência histórica para planejamento. Código, serviços, ledgers e aprovações não foram alterados na auditoria.
