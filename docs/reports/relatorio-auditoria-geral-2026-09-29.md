# Relatório de Auditoria Geral — RICK Intelligence

**Data:** 29/09/2026 00:19 UTC  
**Escopo:** checkout atual `/home/ricardo/rick-intelligence`, HEAD `b52f32c141916a2ea3af1a6b913bd91f380606e0`, worktree sujo.  
**Método:** inspeção estática, documentação, testes locais reproduzíveis e revisão independente somente leitura. Não houve deploy, push, alteração de código ou chamada a provider real.

## Parecer executivo

**Nota técnica geral: 80/100** (média simples de 26 itens; 2.076/2.600).

**Classificação:** `STATE_OF_ART_CANDIDATE`.  
**Promoção:** `NO-GO`: runtime integrado distribuído, restore/RPO/RTO, chaos/soak, provider/corpus reais, CI same-SHA e aprovação independente/humana continuam sem evidência.

A base local é forte: validação de boundaries, control-plane, qualidade estática, lint/typecheck, Compose estático, migrações offline e grandes suítes de API/packages passam. A nota não é maior por três grupos de risco: (1) lacunas de integridade cross-tenant no schema, confirmadas estaticamente; (2) pipelines e testes de browser/benchmark não totalmente verdes; (3) ausência de prova operacional integrada.

## Evidência executada nesta auditoria

- `make validate`: **PASS**; control-plane PASS, quality bar PASS; worktree DIRTY.
- `make test-fast`: **PASS**; suites CVG/Professor/Locker passaram (40 testes CVG, 37 Professor, 2 Locker, além dos checks).
- `make lint`: **PASS**; `make typecheck`: **PASS**.
- `make api15-full`: contratos 12, providers 76, locking 54, professor 86 e API 751 passaram; o alvo terminou **FAIL** porque `api15-benchmark` não produziu evidência aprovada.
- `make api16-full`: packages/knowledge-ingestion-retrieval **281 passed, 5 skipped**; worker/root **116 passed**; API teve **750 passed, 1 falha** em ingestão/telemetria quando executado em paralelo. Reexecução isolada: **1 passed**; classificado como instabilidade/intermitência não resolvida, não como PASS integral.
- `make web-validate`: lint/typecheck/build passaram; a matriz Playwright de 321 testes foi iniciada, exibiu falhas em `axe.run` e timeout de confirmação/teclado e foi interrompida em 131/321 para não deixar processo longo ativo. Portanto o resultado final é **INCONCLUSIVO/FAIL-EVIDENCE**, não PASS.
- `make compose-static ops-static`: **PASS**; 14 serviços dev e 14 staging renderizados; 7 migrações/checksums verificados; execução live **NOT_RUN**.
- `git diff --check`: **PASS**.

## Notas por item (0–100)

| # | Item analisado | Nota | Evidência e principal desconto |
|---:|---|---:|---|
| 1 | Arquitetura e separação de responsabilidades | **84** | Fronteiras apps/packages/contracts e composição explícita; três legados paralelos e worktree muito sujo. |
| 2 | Documentação e aderência ao estado atual | **72** | Estado e limitações são honestos; há drift de versões no toolchain e documentos históricos ligados a SHAs/worktree diferentes. |
| 3 | Identidade e sessões | **84** | Hash em produção e controles de sessão; modos não produtivos persistem `password_plain` em `identity_service.py:224-227`, risco em dumps/discos de dev. |
| 4 | Autorização e isolamento | **80** | Narrowing/revalidação e testes fortes; isolamento DB não é integralmente garantido por constraints cross-scope. |
| 5 | Kernel HTTP e controles defensivos | **88** | Limites, erros, CSRF/rate-limit e gates fail-closed cobertos; warning/dependências e runtime externo ainda limitam confiança. |
| 6 | Contratos e compatibilidade | **85** | Contratos/providers/compatibilidade passaram; consumidores externos reais não foram exercitados. |
| 7 | Knowledge: documentos, versões e proveniência | **84** | Proveniência/lineage fortes; `rick_chunks` permite FK independente do documento e do escopo (`0002_product_schema.sql:115-133`). |
| 8 | Ingestão e reindexação | **86** | Testes de pipeline e worker passam; falha intermitente no evento `worker.ingestion.published` em execução paralela. |
| 9 | Retrieval e busca híbrida | **88** | Busca híbrida e testes locais fortes; Qdrant/stack integrada não validada em runtime completo. |
| 10 | Evidence: fontes e citações | **86** | Gates e citações cobertos; benchmark de evidência falhou: fixture não produziu evidência aprovada. |
| 11 | Decision: responder, abster e escalar | **78** | Política v1 conservadora e testada; escopo de domínio ainda limitado e thresholds não calibrados. |
| 12 | Professor e geração fundamentada | **87** | Rejeição sem citação, leases e budgets testados; provider/modelo real ausente. |
| 13 | Integração com providers | **82** | Resiliência e contratos locais; sem chamada a provider real nesta auditoria. |
| 14 | Avaliação da qualidade RAG | **75** | Packs sintéticos e testes existem; benchmark executável falha e campanha/corpus representativo seguem NOT_RUN. |
| 15 | Chat, histórico e apresentação de evidências | **80** | Contratos e testes locais fortes; ponta a ponta com serviços reais não comprovada. |
| 16 | Interface: documentos, busca e ingestão | **85** | Lint/typecheck/build passam; E2E visual/acessibilidade apresentou `axe.run arguments are invalid` e timeout de modal/teclado. |
| 17 | Administração, auditoria e casos | **82** | Outbox/reconciliação e testes locais; rota admin depende do provider para validar escopo do alvo e não houve runtime externo. |
| 18 | Containers e composição | **78** | Hardening, readiness e 14 serviços estáticos; credencial root MinIO, Jaeger in-memory e startup real ainda abertos. |
| 19 | Jobs, PostgreSQL e migrações | **82** | Checksums e testes locais passam; jobs têm FK de documento e escopo separadas (`0002:135-153`), permitindo inconsistência salvo garantias adicionais de aplicação. |
| 20 | Worker e ciclo de vida | **86** | Shutdown, fencing e poison-claim cobertos; composição multiworker real não validada. |
| 21 | Redis e coordenação distribuída | **78** | Implementação owner-safe e testes; Redis replicado/distribuído não executado. |
| 22 | Storage e inicialização persistente | **78** | Validação de endpoint/credenciais e testes locais; S3 privado, restore e reidratação operacional não demonstrados. |
| 23 | Observabilidade e SLO | **76** | Sink bounded, métricas e configuração OTLP locais; collector, alertas, traces e SLO reais não validados. |
| 24 | Recuperação, capacidade e tolerância a falhas | **50** | Runbooks e manifests existem, mas RPO/RTO, carga, chaos e soak estão NOT_RUN/BLOCKED_EXTERNAL. |
| 25 | CI e promoção de release | **64** | Envelopes/gates fail-closed; release recusa push/PR sem evento de runtime (`quality.yml:314-349`), cobertura operacional é manual/schedule e ações/pipelines têm inconsistências. |
| 26 | Qualidade global dos testes | **78** | Volume e regressões altos; não há threshold obrigatório de coverage, há 424 warnings de depreciação na API, benchmark falha e E2E não fecha verde. |

## Achados prioritários

1. **ALTO — integridade cross-tenant/cross-workspace:** `rick_chunks` e `rick_ingestion_jobs` usam FKs separadas para documento e escopo; `rick_messages` referencia apenas `conversation_id`, enquanto seus campos de tenant/workspace/user são independentes (`0002_product_schema.sql:115-153,188-201`). Isso é um gap confirmado no schema, não prova de exploração ativa. Adicionar constraints compostas e testes negativos de escrita/leitura.
2. **ALTO — evidência insuficiente para promoção:** API+worker+PostgreSQL+Redis+Qdrant+S3+provider integrados, observabilidade distribuída, restore/RPO/RTO e chaos/soak permanecem sem execução autorizada.
3. **MÉDIO — benchmark:** `scripts/phase15/benchmark.py` falha com `benchmark fixture did not produce approved evidence`; corrigir fixture/threshold ou documentar contrato antes de chamar o gate de qualidade.
4. **MÉDIO — frontend E2E:** falhas atuais de `axe.run` e timeout de confirmação/teclado na matriz visual precisam de reprodução e correção antes de considerar acessibilidade/browser verde.
5. **MÉDIO — segredo de desenvolvimento:** `password_plain` é persistido fora de production (`identity_service.py:224-227`); substituir por hash também em dev/test ou garantir store exclusivamente efêmero e não persistente.
6. **MÉDIO — CI/reprodutibilidade:** `make lint/typecheck/build` não cobre todo o app canônico; dependências Python locais não são lockadas por hash como o runtime CI; não há threshold obrigatório de coverage.

## Próximas ações recomendadas

1. Corrigir constraints compostas e adicionar testes de isolamento cross-scope.
2. Tornar benchmark determinístico e fechar a matriz Playwright/axe; repetir `api16-full` sem paralelismo e depois no alvo completo.
3. Alinhar `make lint/typecheck/build` com `apps/web` e API; eliminar warnings deprecatórios e definir coverage mínima.
4. Executar, com aprovação D02–D07, a composição descartável completa e medir provider/RAG, outbox, RPO/RTO, carga, chaos, soak e telemetria.
5. Reauditar em checkout limpo e gerar evidência commit-bound; só então reavaliar promoção.

**Conclusão:** qualidade local alta, mas o sistema ainda não é candidato de promoção. A recomendação técnica permanece `NO-GO` até fechar os gaps de integridade e produzir evidência operacional distribuída independente.
