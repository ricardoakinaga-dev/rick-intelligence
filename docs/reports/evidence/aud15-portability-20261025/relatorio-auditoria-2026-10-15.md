# Nova auditoria de código — RICK Intelligence

**Observação:** 14/10/2026 no horário local, 15/10/2026 UTC. **Nota geral: 74,6/100 — 75/100 arredondada. Produção: NO-GO.**

A implementação local é forte em arquitetura, testes, contratos e controles de autoridade. Correções recentes foram revalidadas, mas ainda há defeitos comprovados em logout OIDC, resistência a abuso e preservação de rascunhos. A suíte ampliada não passou; testes locais e build não substituem execução distribuída e evidência de produção.

## 1. Escopo e método

- Candidato: HEAD `48e383c25ca4af32aa7ffe7e2367360ca9742c58`, branch `archive/local-runtime-20261011`, **worktree com 51 entradas pendentes antes da auditoria**. O objeto avaliado inclui essas alterações e testes novos, não apenas o commit.
- Escopo: API FastAPI, identidade/autorização, worker, packages de ingestão/retrieval/providers/evidence/observabilidade, web Next.js, testes, CI, documentação e controles de operação. Inspeção estruturada por amostragem conectada, não leitura exaustiva de todo arquivo.
- Critérios: negar acesso indevido; preservar escopo, estado e dados; falhar com honestidade nas dependências; recuperar erros/concorrência; respeitar contratos; oferecer testes e gates reproduzíveis; separar prova hermética de operação real.
- Método: inspeção de fontes/testes atuais, dois auditores independentes com acesso read-only, verificações locais e probes determinísticos. Os principais probes foram repetidos pelo coordenador.
- Ambiente observado: Python 3.12.3, pytest 9.0.3, Node 24.20.0, npm 11.19.0, sandbox bwrap. Node/npm diferem do [contrato declarado](<../../toolchain.json#L3-L7>): 22.19.0/10.9.3.
- Sem deploy, migrations em banco, serviços externos, chamadas a modelos pagos ou leitura de `.env`. Nenhuma correção da implementação foi realizada. O build isolado reescreveu temporariamente [tsconfig](<../../apps/web/tsconfig.json>) e [next-env](<../../apps/web/next-env.d.ts>); ambos foram restaurados exatamente e conferidos com `git diff --exit-code`.
- Artefatos desta rodada: este relatório e logs/probes locais sob `.runtime/audit-20261015`. Esses logs são ignorados pelo Git; os links abaixo funcionam neste checkout e não são um pacote selado de promoção.

### Escala e cálculo

| Nota | Interpretação |
|---|---|
| 90–100 | Evidência local muito forte para o recorte, com poucas lacunas |
| 75–89 | Boa implementação, ainda com limitações relevantes |
| 60–74 | Base útil, com fragilidades materiais |
| 40–59 | Parcial; faltam provas ou capacidades importantes |
| 0–39 | Insuficiente para o objetivo, ou bloqueios graves |

**Média simples das 26 dimensões: 1.939 / 26 = 74,5769.** As notas são julgamento técnico fundamentado, não porcentagem de funcionalidades, cobertura global, probabilidade de segurança ou autorização de produção. A média não compensa falha obrigatória. Não comparar diretamente com médias antigas: os recortes e ambientes não são idênticos.

## 2. Notas de 0–100 por item analisado

| # | Item | Nota | Fundamentação / maior limite |
|---:|---|---:|---|
| 1 | Arquitetura e fronteiras | **88** | Separação apps → packages; gate de fronteiras aprovado. Composição e módulos grandes ainda aumentam custo de revisão. |
| 2 | Contratos API e schemas | **86** | Schemas, envelopes e negativos bem exercitados. Sem revalidação OpenAPI isolada nesta rodada; logout OIDC viola a semântica de sucesso. |
| 3 | Autenticação e ciclo de sessão | **72** | Revogação nativa melhorou e regressões passaram; OIDC ainda confirma logout sem invalidar o token. |
| 4 | Autorização e isolamento tenant | **85** | Snapshots restritivos, grants atuais, tenant/workspace explícitos e negativos locais. Não comprovados contra IdP/PG distribuídos reais. |
| 5 | Segurança de entrada e resistência a abuso | **66** | Limites de corpo, CSRF, proxies e buckets independentes; confirmação pública de reset executa hash sem quota. Scans atuais não executados. |
| 6 | Auditoria e honestidade dos resultados | **76** | Auditoria obrigatória da revogação nativa; OIDC gera `completed` sem efeito e indisponibilidade pode virar falsa ausência. |
| 7 | Persistência e integridade de dados | **80** | Stores, escopo, lineage e transações têm regressões locais substanciais; PostgreSQL/S3/Qdrant reais não exercitados. |
| 8 | Ingestão e segurança de documentos | **85** | Allowlist, checksums, limites de bytes/texto/arquivos e isolamento de parser; corpus hostil externo não executado. |
| 9 | Worker, concorrência e shutdown | **88** | Novas regressões de claims em voo, admission, drain e fechamento passaram; sem SIGTERM real ou fencing multiprocesso externo. |
| 10 | Providers, streaming e resiliência | **86** | Budgets, circuit breaker, cancelamento e cleanup; prova local, sem provider real nem carga representativa. |
| 11 | Retrieval e proveniência de evidência | **84** | Escopo antes/depois de fusão, autoridade e provenance; validação semântica da resposta não demonstrada com corpus real. |
| 12 | Qualidade efetiva de IA/RAG | **45** | Pack offline aprovado, mas apenas 2 positivos/3 negativos sintéticos; não mede desempenho de modelo real nem qualidade clínica. |
| 13 | Frontend e recuperação de UX | **68** | Bons estados e regressões novas; perdas comprovadas de pergunta offline e de novo rascunho de caso. |
| 14 | Integração frontend ↔ API | **72** | SSE/parser e paginação de chat bons; casos sem paginação completa, transporte aceita 2xx malformado e jobs sem retomada. |
| 15 | Acessibilidade | **78** | Labels, skip link, foco, log/alert/status e confirmação com trap. Drawer sem modalidade explícita; browser/AT atual não executado. |
| 16 | Testes e força de regressão | **84** | 7.658 passes na suíte ampliada; 215 regressões focadas e 115 web verdes. Ainda escapam defeitos reproduzidos; suíte total FAIL. |
| 17 | Cobertura e validade dos denominadores | **72** | Web 92,57% linhas / 82,54% branches, mas só 539 linhas selecionadas. Sem cobertura Python global fresca. |
| 18 | Tipagem e análise estática | **68** | TypeScript e mypy aprovados; mypy cobre somente 13 arquivos de contratos/autorização, não API/worker/stores. |
| 19 | Lint e higiene local de código | **90** | ESLint e whitespace aprovados; não equivale a lint semântico completo de todo Python. |
| 20 | Build frontend | **88** | Next compilou e gerou 12 páginas estáticas; sem navegador atual, imagens Docker ou build no Node contratado. |
| 21 | CI e supply chain | **76** | Actions fixadas por SHA e gates estruturais aprovados; inventário Node falha por segundo manifesto versionado. Sem CI remoto/scans atuais. |
| 22 | Documentação e rastreabilidade | **80** | 836 links locais válidos e NO-GO explícito; documentos de CSRF/histórico divergem do código; evidências históricas exigem cuidado. |
| 23 | Reprodutibilidade do ambiente e das suites | **60** | Venv canônico funciona, mas Node/npm divergem e 277 testes VPS falham neste sandbox por barreiras de filesystem/harness. |
| 24 | Observabilidade e operação local | **72** | Redação, sinks bounded, tracing e health têm controles; utilitário OTel altera exceção do corpo, e telemetria distribuída não comprovada. |
| 25 | Backup, restore e recuperação | **55** | Ferramentas de checksum/restore e runbooks existem; restore integrado, RPO/RTO e recuperação real não executados. |
| 26 | Prontidão de produção | **35** | Gates fail-closed são positivos; há defeitos altos, suite ampliada FAIL e obrigações externas atuais sem prova. |

### Evidência orientadora da matriz

- Arquitetura/CI/docs: [README](<../../README.md#L63-L84>), [workflow canônico](<../../.github/workflows/quality.yml#L23-L61>) e [validação atual](<../../.runtime/audit-20261015/validate.log>).
- Segurança e sessão: [autoridade de sessão](<../architecture/security/session-authority.md#L3-L24>), [OIDC](<../../packages/identity/src/rick_identity/oidc.py#L238-L295>), [regressões de revogação](<../../apps/api/tests/test_logout_revocation_failure.py#L22-L64>) e [regressões de abuso](<../../apps/api/tests/test_public_abuse_regressions.py#L18-L65>).
- Dados/IA: [envelope de ingestão](<../../packages/ingestion/src/rick_ingestion/admission.py#L94-L127>), [limites do parser](<../../packages/ingestion/src/rick_ingestion/parsers.py#L39-L68>), [retrieval](<../../packages/retrieval/src/rick_retrieval/pipeline.py#L172-L225>), [autoridade de evidência](<../../packages/evidence/src/rick_evidence/validator.py#L75-L88>) e [pack sintético](<../evaluation/packs/rec22-local-v2/manifest.json#L1-L13>).
- Worker/providers: [shutdown](<../../apps/worker/runtime.py#L1853-L1909>), [composição](<../../apps/worker/deployment_composition.py#L308-L392>), [regressões de corridas](<../../apps/worker/tests/test_shutdown_races.py#L25-L99>) e [resiliência](<../../packages/providers/src/rick_providers/resilience.py#L50-L151>).
- Tipos/cobertura: [mypy](<../../mypy.ini#L6-L14>), [allowlist Vitest](<../../apps/web/vitest.config.ts#L8-L14>) e [resumo de cobertura](<../../.runtime/qa/web/coverage-summary.json>).
- Operação: [instrumentação](<../../apps/api/src/core/otel.py>), [sinks bounded](<../../packages/observability/src/rick_observability/events.py#L113-L127>), [backup file-level](<../../infrastructure/scripts/backup_restore.py#L1-L8>) e [runbook](<../operations/release-readiness.md#L11-L35>).

## 3. Verificações executadas

| Procedimento | Exit | Resultado atual |
|---|---:|---|
| `make validate` | 0 | PASS: controle estrutural, fronteiras, toolchain declarada, Actions, quality bar; 836 links/0 erros. Não certifica versões efetivas Node/npm nem promoção. |
| pytest ampliado, sem configurações externas herdadas | **1** | **FAIL: 7.658 passed, 278 failed, 221 skipped, 99 subtests passed**, 403,66 s. |
| Regressões focadas de patches recentes | 0 | **215 passed, 11 subtests passed**, 2,26 s; revogação/read/corrupção/abuso/shutdown/recuperação de controle. |
| Inventário Node, rerun isolado | **1** | FAIL confirmado: segundo manifesto versionado sob snapshot de runtime. |
| `npm run lint` | 0 | PASS. |
| `npm run typecheck` | 0 | PASS. |
| `npm run test:coverage` | 0 | **115 passed**; 92,57% linhas, 82,54% branches somente na allowlist. |
| `npm run build`, dist isolado | 0 | PASS; Next 15.5.25 instalado, 12 páginas estáticas, sem iniciar servidor. |
| `python -m mypy --config-file mypy.ini` | 0 | PASS em 13 arquivos, escopo restrito. |
| `python -m pip check` | 0 | PASS: dependências consistentes; não é scan de CVEs. |
| `make eval-retrieval-pack` | 0 | PASS offline/sintético; latência e métricas registradas não são observação de provider real. |
| `make ops-migration-check` | 0 | PASS: checksums de 10 migrations; aplicação NOT_RUN. |
| `git diff --check` | 0 | PASS. |
| Probes OIDC/reset/eventloop/OTel e React/jsdom | 0 | Reproduziram falhas descritas abaixo. Exit 0 indica que o probe confirmou o defeito, não que o produto passou. |

Logs: [Python ampliado](<../../.runtime/audit-20261015/pytest.log>), [regressões focadas](<../../.runtime/audit-20261015/regressions.log>), [web](<../../.runtime/audit-20261015/web.log>), [build](<../../.runtime/audit-20261015/build.log>), [checks com exits individuais](<../../.runtime/audit-20261015/checks-explicit.log>) e [inventário isolado](<../../.runtime/audit-20261015/inventory.log>).

Comando principal de testes:

```bash
env -i PATH="$PATH" HOME="$HOME" LANG=C.UTF-8 PYTHONDONTWRITEBYTECODE=1 \
  .runtime/venvs/cvg/bin/python -m pytest -q -p no:cacheprovider \
  apps/api/tests packages apps/worker/tests scripts infrastructure docs/ci
```

### Interpretação das 278 falhas

**277 estão em testes VPS; 1 está no inventário Node. Nenhuma falha foi listada em apps ou packages.** Não converter esse recorte em PASS da suíte total.

A principal barreira VPS é ambiental e foi diagnosticada: UID efetivo 1000; `/tmp` tem UID 1000 e modo 1777, enquanto `/usr`, `/proc` e outros ancestrais aparecem com UID 65534. O [contrato de captura](<../../infrastructure/vps/contracts.py#L75-L92>) só admite pai gravável com sticky bit quando pertence a root (UID 0), então a captura de um arquivo sintético privado falha com `unprotected input parent`. Parte das assertions seguintes falha em cascata antes de atingir o comportamento alvo; duas falhas mostram `chown` com EINVAL. [Diagnóstico de filesystem](<../../.runtime/audit-20261015/filesystem-probe.log>).

Isso **não comprova 277 bugs de produto**, nem comprova que todos esses testes passariam em outro host. A lane VPS permanece não validada neste ambiente; repetir em Linux com ownership/permissões representativos, sem enfraquecer a política. Diferentemente dela, o inventário Node falha também isoladamente e possui causa demonstrada no checkout.

## 4. Achados priorizados e critérios de fechamento

IDs `AUD15-xx` pertencem exclusivamente a esta rodada. **Alta**: impacto de segurança/integridade ou uso central; **média**: disponibilidade/recuperação/contrato material; **baixa**: risco limitado no encadeamento observado. **P1**: antes de candidatura a produção; **P2**: próxima rodada de robustez. Todos permanecem abertos; nenhuma aceitação de risco foi concedida.

### AUD15-01 — Alta / P1 — logout OIDC confirma saída sem revogar

**Prova:** API real in-process + verificador JWT real, token sintético: `me 200 → logout 200 signed_out → mesmo bearer me 200`; auditoria registra `requested/completed`. O [provider OIDC](<../../packages/identity/src/rick_identity/oidc.py#L294-L295>) não executa logout, mas a [rota](<../../apps/api/src/routes/auth.py#L258-L266>) presume o efeito. A [composição](<../../apps/api/src/services/external_composition.py#L453-L466>) aceita identity marcada production-safe sem exigir capacidade de broker/logout.

**Impacto:** falsa confirmação de término e trilha de auditoria incorreta no uso direto desse adapter. Não foi demonstrada exploração em implantação real, nem falha da revogação nativa corrigida. **Confiança alta.**

**Fechamento:** explicitar contrato de logout federado, integrar broker/revogação ou rejeitar confirmação não suportada; provar que saída confirmada invalida a autoridade relevante e que erros não geram `completed`. [Probe reproduzível](<../../.runtime/audit-20261015/oidc-probe.py>) / [saída](<../../.runtime/audit-20261015/oidc-probe.log>).

### AUD15-02 — Alta / P1 — reset público executa trabalho caro sem quota

A [confirmação de reset](<../../apps/api/src/routes/auth.py#L306-L317>) não chama limiter. A [facade PostgreSQL](<../../apps/api/src/services/postgres_identity.py#L885-L895>) calcula [PBKDF2 de 100 mil iterações](<../../packages/identity/src/rick_identity/passwords.py#L14-L20>) antes de consultar o token.

**Prova:** três tokens inexistentes, facade real com transaction/consume controlados: `400/400/400`, **hash=3, consume=3, limiter=0**, inclusive com limiter que nega. **Impacto:** CPU e acesso a persistência acessíveis anonimamente sem possuir token válido; não foi medido DoS ou throughput real. **Confiança alta.**

**Fechamento:** quota antes de KDF/DB; reduzir trabalho para tokens inválidos preservando atomicidade e não enumeração; teste negativo garante zero KDF/consume quando barrado. [Probe](<../../.runtime/audit-20261015/reset-probe.py>) / [saída](<../../.runtime/audit-20261015/reset-probe.log>).

### AUD15-03 — Alta / P1 — chat perde pergunta ao ficar offline durante envio

O [envio](<../../apps/web/components/chat/chat-workspace.tsx#L694-L724>) limpa o draft; a [transição offline](<../../apps/web/components/chat/chat-workspace.tsx#L589-L601>) aborta, invalida callbacks, zera request e remove mensagem `sending` sem restaurar a pergunta. O catch tardio não recupera a operação invalidada.

**Prova React/jsdom:** pergunta existia antes do offline; após reconnect, draft vazio, pergunta ausente e nenhum retry. Callback tardio foi corretamente descartado. **Impacto:** perda do texto e do estado/chave de retry, não perda demonstrada no backend. **Confiança alta.**

**Fechamento:** preservar pergunta/identidade do retry durante desconexão e descartar respostas tardias; teste deferred send → offline → online. [Probe de componentes reais](<../../.runtime/audit-20261015/web-probe.cjs>) / [saída](<../../.runtime/audit-20261015/web-probe.log>).

### AUD15-04 — Alta / P1 — criação de caso apaga edições posteriores ao submit

O [create](<../../apps/web/components/cases/case-workspace.tsx#L167-L179>) envia A e, ao resolver, limpa o formulário inteiro. Os [campos](<../../apps/web/components/cases/case-workspace.tsx#L263>) continuam editáveis enquanto a requisição aguarda.

**Prova React/jsdom:** payload continha A; novo draft B estava visível e habilitado; resposta A apagou título/resumo B. **Impacto:** alterações humanas não enviadas desaparecem silenciosamente. **Confiança alta.**

**Fechamento:** congelar os campos durante envio ou versionar draft para limpar somente a revisão enviada; cobrir edição pós-submit e admissão duplicada. Mesma [saída de probe](<../../.runtime/audit-20261015/web-probe.log>).

### AUD15-05 — Alta / P1 — sessão visual não sincroniza entre abas

O [provider de sessão](<../../apps/web/components/session-provider.tsx#L30-L60>) revalida no mount/refresh explícito; não há revalidação em focus/visibility nem evento entre abas. O [transporte](<../../apps/web/lib/api.ts#L95-L124>) usa cookies compartilhados e não comunica 401 ao contexto.

**Sequência estática:** duas abas como A; numa, logout/login B; outra conserva contexto/conteúdo A, mas uma ação nova leva cookies B. Não alego bypass ACL do servidor; é divergência de identidade visual e de admissão de ação. **Confiança média-alta; browser multiaba não executado.**

**Fechamento:** sincronizar troca/logout e revalidar ao retomar antes de privado/mutações; teste real multi-page A→B/revogação/callback tardio.

### AUD15-06 — Média / P1 — indisponibilidade OIDC é tratada como ausência confirmada

O [catch amplo](<../../packages/identity/src/rick_identity/oidc.py#L291-L292>) transforma falha de membership em anonymous; a [rota de logout](<../../apps/api/src/routes/auth.py#L240-L252>) interpreta isso como cleanup seguro.

**Prova:** resolver indisponível → logout `200 signed_out`, me `401`; resolver restaurado → mesmo token me `200`. **Acesso falha fechado**, mas indisponibilidade vira falsa confirmação em vez de 503. **Confiança alta.**

**Fechamento:** distinguir token inválido/membership negada de autoridade indisponível; último caso retorna erro seguro sem afirmar logout. [Saída OIDC](<../../.runtime/audit-20261015/oidc-probe.log>).

### AUD15-07 — Média / P1 — identidade síncrona ocupa event loop ASGI

A [dependência async](<../../apps/api/src/dependencies/identity.py#L32-L56>) executa `validate_token` síncrono diretamente; o [login async](<../../apps/api/src/routes/auth.py#L174-L203>) faz o mesmo com login/KDF.

**Prova:** chamadas reais com PBKDF2 registraram loop ativo em login e nas duas validações. Inspeção dos adapters PG conecta essa fronteira a DB-API síncrono. **Impacto inferido:** latência de KDF/DB bloqueia outras requisições no mesmo loop; não foi medido throughput real. **Confiança alta sobre scheduling.**

**Fechamento:** offload bounded ou adapter async com deadline; prova concorrente mostra requisição independente progredindo durante dependência lenta. [Probe](<../../.runtime/audit-20261015/eventloop-probe.py>) / [saída](<../../.runtime/audit-20261015/eventloop-probe.log>).

### AUD15-08 — Média / P1 — inventário Node inconsistente com Git

O [teste de inventário](<../../scripts/state_of_art/tests/test_frontend_supply_runtime.py#L208-L214>) espera só o web canônico. Git inclui também um [manifesto de snapshot](<../../.runtime/production-local-20261004/source/apps/web/package.json>). Falhou global e isoladamente.

**Impacto:** gate de supply/inventário vermelho; não prova vulnerabilidade na dependência. **Confiança alta.**

**Fechamento:** definir política explícita de snapshot/inventário e versionamento; o teste deve voltar a aprovar sem ignorar componentes executáveis legítimos. [Falha isolada](<../../.runtime/audit-20261015/inventory.log>).

### AUD15-09 — Média / P2 — casos mostram apenas primeira página

A [listagem](<../../apps/web/components/cases/case-workspace.tsx#L111-L114>) descarta total/next_offset; a [tela](<../../apps/web/components/cases/case-workspace.tsx#L262-L264>) usa items.length e não oferece paginação. A [API](<../../apps/api/src/routes/cases.py#L184-L199>) tem default 50 e offset.

**Impacto:** 51º caso fica inacessível pela listagem e parcialidade não é anunciada; não significa registro perdido. **Prova estática, confiança alta.** Fechamento: 51 casos acessíveis, total verdadeiro e erro da página seguinte sem apagar a primeira.

### AUD15-10 — Média / P2 — retry do chat após 403 não funciona e E2E diverge

`denied` desabilita queryAvailable, mas continua sendo oferecido retry que retorna antes de consultar API. [Gate de envio](<../../apps/web/components/chat/chat-workspace.tsx#L679-L686>), [tratamento 403](<../../apps/web/components/chat/chat-workspace.tsx#L817-L825>) e [spec browser antigo](<../../apps/web/tests/chat-workspace.spec.ts#L142-L167>).

Limpar/bloquear após 403 pode ser política legítima. O defeito é oferecer recuperação inoperante. Os specs também pressupõem draft editável offline, contrário à UI atual. **Inspeção estática, não execução E2E; confiança alta.** Fechamento: ação explícita de revalidação mantendo fail-closed e alinhar expectativas sem enfraquecer segurança.

### AUD15-11 — Média / P2 — acompanhamento de job não retoma

O [polling](<../../apps/web/app/app/documents/page.tsx#L160-L184>) encerra após 80 intervalos de 120ms (~9,6s mais rede), ou erro transitório; Atualizar consulta catálogo, não o job existente.

**Impacto:** card pode continuar queued após publicação posterior, sem recuperação do acompanhamento. **Prova estática, confiança alta.** Fechamento: retomar/consultar o mesmo job, backoff controlado e testes timeout→published/503→published sem novo upload.

### AUD15-12 — Média / P2 — 2xx malformado pode parecer catálogo vazio

O [transporte](<../../apps/web/lib/api.ts#L103-L124>) faz JSON inválido virar null e devolve cast T sem validação; a [página de documentos](<../../apps/web/app/app/documents/page.tsx#L96-L111>) aceita esse retorno e renderiza vazio.

**Impacto:** HTML de proxy ou envelope incompleto pode ser confundido com ausência legítima de dados. **Prova estática, confiança alta.** Fechamento: validar contrato de resposta, retornar invalid_response e cobrir 200HTML/JSON inválido/campos ausentes com retry.

### AUD15-13 — Baixa / P2 — utilitário de propagação OTel substitui erro do corpo

O [contextmanager](<../../apps/api/src/core/otel.py#L109-L128>) envolve o yield em catch amplo e tenta produzir um segundo yield após erro do corpo.

**Prova:** carrier válido + ValueError sintético → RuntimeError `generator didn't stop after throw()`, original não preservado. **Limite importante:** o [caller atual do worker](<../../apps/worker/runtime.py#L1357-L1401>) captura erros do handler dentro do contexto e preserva o resultado; não foi demonstrada perda de job nem alteração de resposta API por esse defeito. Por isso, prioridade/severidade reduzidas. **Confiança alta no utilitário.**

**Fechamento:** separar falha de entrada/cleanup da exceção do corpo; teste exige mesma exceção original em sucesso de attach e falha de detach. [Probe](<../../.runtime/audit-20261015/otel-probe.py>) / [saída](<../../.runtime/audit-20261015/otel-probe.log>).

## 5. Evolução desde a referência anterior

A [baseline de 12/10](<baseline-producao-2026-10-12.md>) foi usada como contexto histórico, não como prova atual.

- **Melhoria comprovada:** `make validate` agora passa; a divergência de raiz não aparece neste check atual. Isso não equivale a evidência de release fresca/selada.
- **Melhoria comprovada localmente:** 215 regressões selecionadas aprovam patches de revogação nativa, leitura/corrupção de sessão, proteção da busca/spray/memória e corridas de shutdown. Não extrapolar para OIDC ou PostgreSQL real.
- **Melhoria comprovada:** web passou de 76 testes registrados naquela baseline para **115 nesta rodada**; paginação do chat, restrição do selo de autorização e refresh após publicação têm testes novos.
- **Pendente:** inventário Node permanece vermelho; cobertura restrita e tipagem gradual continuam com denominadores limitados.
- **Pendente:** documentação de [CSRF](<../architecture/api-security.md#L44-L46>) ainda diz tokens adiados, mas [login](<../../apps/api/src/routes/auth.py#L194-L201>) já gera nonce; a [tabela web](<../architecture/canonical-web.md#L51>) ainda apresenta histórico/streaming como próximo limite, apesar da implementação atual.
- **Novas provas:** logout OIDC sem revogação, reset sem quota e perdas de draft reproduzidos; segurança da sessão nativa não deve ser usada para encerrar esses gaps de outras superfícies.

## 6. Limitações e parecer final

**NOT_RUN nesta rodada:** PostgreSQL/Redis/Qdrant/S3/IdP/providers reais, browser E2E/axe/tecnologia assistiva, scans atuais de CVEs/imagens, imagem/SBOM/assinatura, restore integrado, SIGTERM real, carga, chaos/soak e corpus hostil externo. Não foi iniciado servidor substituto, nem presumido estado da GUI/browser. Os 221 skips não são aprovação de runtime.

O gate estático emite aviso de 741 citações relativas de evidência sem arquivo na árvore, aceitas pela política do repositório. Esse PASS estrutural não torna cada citação uma prova atual. A árvore permanece dirty; este relatório não representa release limpa/imutável. Auditoria read-only brownfield/T2, sem adoção de tarefas ou mudança de gate de promoção.

Após a consolidação, `make docs-check` aprovou **916 links locais/0 erros** e `git diff --check` passou. O auditor independente de API revisou as seções de OIDC/reset/scheduling e não encontrou erro material; essa aprovação é limitada ao relato, não ao produto. As demais contagens foram verificadas pelo coordenador nos logs. O status Git final preservou as 51 entradas iniciais, acrescentando somente este relatório entre os arquivos não ignorados.

**Parecer:** qualidade local boa, mas ainda não pronta para produção. Primeiro corrigir **AUD15-01/02/03/04/05**; depois revalidar os mesmos probes como regressões que rejeitem a versão defeituosa, reconciliar inventário/toolchain/harness VPS e executar as fronteiras externas num ambiente aprovado. Não foi observado incidente real nem concedido aceite de risco. **Próxima ação única recomendada:** abrir uma rodada de correção dos cinco achados altos, começando pelo contrato de logout OIDC.
