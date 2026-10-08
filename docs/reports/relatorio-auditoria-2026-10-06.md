# Auditoria do RICK Intelligence — 06/10/2026

## 1. Parecer executivo

**Nota geral do recorte auditado: 70,4/100 (70/100 arredondada). Produção: NO-GO.**

O projeto tem arquitetura modular consistente, controles de autorização relevantes e uma quantidade substancial de testes locais. Ingestão, worker, identity e providers possuem implementação bem mais madura do que um protótipo. Entretanto, o checkout atual não passa sua própria validação geral; a remoção dos legados não foi refletida integralmente em testes/CI/documentação. Foram reproduzidos defeitos de frescor da busca, integridade da idempotência, cache local e readiness de extensões. A ligação entre aprovação final e instalação VPS também precisa ser demonstrada.

A nota é uma avaliação técnica qualitativa, não um percentual de funcionalidades concluídas, uma probabilidade de segurança ou autorização para produção. Um gate obrigatório falho não é compensado pela média.

## 2. Escopo, versão e método

- Observação: **06/10/2026, aproximadamente 12:15–12:24 UTC**, seguida da consolidação deste relatório.
- Checkout: `/home/ricardo/rick-intelligence`; HEAD `b52f32c141916a2ea3af1a6b913bd91f380606e0`.
- **Árvore extensamente modificada**, incluindo fontes novas e exclusões dos três componentes legados. O objeto auditado é esse worktree, não somente o HEAD nem a candidata18 descrita em relatórios anteriores.
- Modo: auditoria brownfield, revisão e verificação local; sem remediação da implementação. Nenhum deploy, push, migração real, leitura de secrets/.env ou chamada a modelos pagos.
- Métodos: leitura de documentação e código conectado; inspeção de configuração; validações estáticas; testes herméticos; quatro reproduções discriminantes; consultas públicas de vulnerabilidades npm/Python.
- Duas revisões delegadas: backend/segurança e infraestrutura/worker/entrega. A restrição de leitura foi instrucional, não isolamento técnico de escrita. A [checagem final de fontes](</home/ricardo/rick-intelligence/.runtime/audit-20261006/source-check.json>) confirmou **702 arquivos sem diferenças em relação ao snapshot registrado durante a auditoria**; isso não equivale a revisão linha a linha dos 702 arquivos nem a um snapshot anterior a toda a sessão.
- O build Next alterou automaticamente dois arquivos de configuração/declaração. Somente essas alterações automáticas foram restauradas; a comparação Git confirmou restauração. Foram produzidos ambiente isolado, build separado, logs e este relatório; mudanças anteriores do usuário foram preservadas.

### Documentos de referência lidos

[README](</home/ricardo/rick-intelligence/README.md>), [índice documental](</home/ricardo/rick-intelligence/docs/INDEX.md>), [contribuição](</home/ricardo/rick-intelligence/CONTRIBUTING.md>), [arquitetura](</home/ricardo/rick-intelligence/docs/architecture/system-architecture.md>), [runtime](</home/ricardo/rick-intelligence/docs/architecture/production-runtime.md>), [autorização](</home/ricardo/rick-intelligence/docs/architecture/authorization.md>), [política de decisão](</home/ricardo/rick-intelligence/docs/architecture/domain-decision-policy-2026-09-24.md>), [avaliação RAG](</home/ricardo/rick-intelligence/docs/evaluation/retrieval-evaluation.md>), [CI](</home/ricardo/rick-intelligence/docs/ci/README.md>), [integridade de release](</home/ricardo/rick-intelligence/docs/architecture/release-integrity.md>), [runbook de release](</home/ricardo/rick-intelligence/docs/operations/release-readiness.md>), READMEs dos componentes auditados e o [estado de produção](</home/ricardo/rick-intelligence/docs/reports/producao-2026-10-04.md#L1-L100>).

Os números históricos da candidata18 foram tratados como contexto, **não como testes executados nesta rodada**.

### Critérios e escala

Critérios definidos antes do parecer: aderência documentação/código, limites arquiteturais, autorização fail-closed, isolamento e integridade, contratos/lifecycle, qualidade da IA, comportamento e acessibilidade da interface, testes reproduzíveis, dependências, CI, operação e promoção.

| Faixa | Interpretação |
|---|---|
| 0–39 | Evidência insuficiente ou lacunas estruturais graves |
| 40–59 | Parcial; bloqueios relevantes |
| 60–74 | Base útil, com fragilidades materiais |
| 75–89 | Implementação local forte, ainda com limites relevantes |
| 90–100 | Evidência muito forte e abrangente para o escopo; 100 exigiria ausência de lacunas materiais conhecidas |

Notas integram adequação do desenho, implementação observada, defeitos e força/frescor da prova. Não são métricas instrumentadas. A nota geral é a **média simples das 26 áreas**, soma 1.831, divisão por 26; não é comparável diretamente com scorecards anteriores de outros escopos.

## 3. Notas por item analisado

| # | Item | Nota /100 | Fundamentação e principal limite |
|---|---|---:|---|
| 1 | Documentação e aderência ao checkout | **62** | Boa organização e honestidade sobre NO-GO; [README](</home/ricardo/rick-intelligence/README.md#L3-L28>) e autoridades antigas ainda descrevem legados preservados ausentes. |
| 2 | Arquitetura e limites de dependência | **85** | Separação apps/packages/contratos consistente; o [validador](</home/ricardo/rick-intelligence/scripts/phase15/check_boundaries.py#L147-L151>) encontrou ausência dos legados, não erros de importação nesta execução. |
| 3 | Manutenibilidade e concentração de responsabilidades | **66** | Testabilidade e interfaces ajudam; [serviço de ingestão](</home/ricardo/rick-intelligence/apps/api/src/services/ingestion_service.py>) tem 3.077 linhas; [jobs PostgreSQL](</home/ricardo/rick-intelligence/apps/worker/postgres_jobs.py>) 2.023; mudanças exigem grande superfície de compreensão. Tamanho não prova bug, mas eleva custo. |
| 4 | Contratos API e idempotência | **78** | DTOs e validação de envelopes presentes; replay sem vínculo ao payload/conversa viola a intenção do [contrato](</home/ricardo/rick-intelligence/packages/contracts/src/rick_contracts/chat.py#L14-L25>). |
| 5 | Autenticação, identity e sessões | **86** | Snapshots, revogação, membership/OIDC e escopo explícito; 201 testes identity passaram, 16 externos não executados. [Identity](</home/ricardo/rick-intelligence/packages/identity/src/rick_identity/provider.py#L138-L217>). |
| 6 | Autorização e governança de acesso | **72** | Interseção de grants e isolamento sólidos, 34 testes authorization passaram; lifecycle de coleção arquivada não é imposto uniformemente na [busca pública](</home/ricardo/rick-intelligence/apps/api/src/routes/search.py#L140-L182>). |
| 7 | Retrieval, cache e frescor da busca | **60** | Filtros de escopo antes/depois da busca, mas archive continua pesquisável e reidratação local usa um [índice global](</home/ricardo/rick-intelligence/apps/api/src/services/retrieval_service.py#L80-L173>) preso ao primeiro escopo. |
| 8 | Ingestão e validação de documentos | **85** | Embeddings validados antes dos writes, transições e cancelamento explícitos; 374 testes passaram. [Pipeline](</home/ricardo/rick-intelligence/packages/ingestion/src/rick_ingestion/pipeline.py#L171-L250>). Corpus hostil e isolamento completo externo não repetidos. |
| 9 | Persistência, lineage e armazenamento | **82** | Chaves compostas, tombstones e fences; storage 28 PASS, knowledge 83 PASS. **98 skips** em knowledge limitam prova PostgreSQL atual. [Store](</home/ricardo/rick-intelligence/packages/knowledge/src/rick_knowledge/store.py#L195-L333>). |
| 10 | Worker, filas, recovery e fencing | **85** | 734 testes worker passaram; acknowledgement e receipts não confundem execução com publicação confirmada. [Worker](</home/ricardo/rick-intelligence/apps/worker/runtime.py#L1082-L1116>). Partições/multi-worker real não repetidos. |
| 11 | Providers, streaming e tratamento de falhas | **82** | 2.143 testes providers passaram; cancelamento/término/envelopes fortes. O [wrapper de resiliência](</home/ricardo/rick-intelligence/packages/providers/src/rick_providers/resilience.py#L83-L122>) aceita extensão sem probe como saudável; modelos reais não avaliados. |
| 12 | Evidências, citações e decisão | **84** | 9 testes evidence, 42 decision e 93 professor passaram; revalidação antes da publicação e deltas provisórios. [Política](</home/ricardo/rick-intelligence/docs/architecture/domain-decision-policy-2026-09-24.md#L48-L71>). Validade estrutural não prova verdade semântica. |
| 13 | Qualidade real de IA/RAG | **52** | Harness offline explícito e aprovado sobre fixtures; pack tem apenas **2 positivos e 3 negativos sintéticos**. [Contrato de avaliação](</home/ricardo/rick-intelligence/docs/evaluation/retrieval-evaluation.md#L3-L21>). Não comprova qualidade/custo de modelos reais. |
| 14 | Segurança e aceite do domínio clínico | **62** | Intake clínico marca risco e exige revisão/escalonamento; [política](</home/ricardo/rick-intelligence/docs/architecture/domain-decision-policy-2026-09-24.md#L23-L45>) declara que não é aprovação clínica. Falta homologação representativa do produto no domínio. |
| 15 | Frontend: comportamento e integração | **84** | Lint, TypeScript, build e 76 testes verdes; sessão serializada e descarte de estado privado. [Session provider](</home/ricardo/rick-intelligence/apps/web/components/session-provider.tsx#L19-L135>). Browser/API real não repetidos. |
| 16 | Acessibilidade e estados da interface | **78** | Skip link, foco, inert, navegação de teclado e estados de erro; [app shell](</home/ricardo/rick-intelligence/apps/web/components/app-shell.tsx#L112-L167>). Sem auditoria visual ou leitor de tela atual nesta rodada. |
| 17 | Testes automatizados locais | **80** | Ampla matriz local; 92,14% de linhas no denominador web declarado. Defeitos reproduzidos ainda escapam às suites verdes. [Configuração de cobertura](</home/ricardo/rick-intelligence/apps/web/vitest.config.ts#L8-L14>). |
| 18 | Integração e regressão reproduzíveis | **55** | API e retrieval originais interrompem coleta por legados ausentes; diagnósticos com exclusões passam, mas não recuperam parity. [API: erro de coleta](</home/ricardo/rick-intelligence/.runtime/audit-20261006/api.log#L3-L24>). |
| 19 | Dependências e vulnerabilidades conhecidas | **56** | Python runtime sem alertas conhecidos nesta consulta; npm tem **8 entradas HIGH, 3 sem dev**. [Audit runtime web](</home/ricardo/rick-intelligence/.runtime/audit-20261006/npm-audit-runtime.json>). Não são oito CVEs independentes. |
| 20 | CI e reprodução do checkout | **48** | Actions por SHA e installs hash-locked são positivos; CI ainda chama caminhos excluídos e RELEASE tem ordem/bootstrap inconsistentes. [CI](</home/ricardo/rick-intelligence/.github/workflows/quality.yml#L334-L342>). |
| 21 | Migrações e integridade do histórico | **86** | Dez SQLs e sidecar passam checksums; runner valida histórico/prefixo e usa lock/transação. [Runner](</home/ricardo/rick-intelligence/infrastructure/scripts/migrate.py#L350-L445>). Nenhuma migração real executada. |
| 22 | Observabilidade e alertas no alvo VPS | **59** | Staging tem estrutura e testes; inventário VPS não inclui a pilha e descarta OTEL. [Inventário](</home/ricardo/rick-intelligence/infrastructure/vps/assets.py#L106-L113>), [env de runtime](</home/ricardo/rick-intelligence/infrastructure/vps/deploy.py#L191-L200>). |
| 23 | Backup, restore e rollback operacional | **63** | Políticas e inventários revisáveis existem; rollback protege compatibilidade. [Runbook](</home/ricardo/rick-intelligence/docs/operations/release-readiness.md#L21-L35>). Restore conjunto e budgets do alvo não comprovados nesta rodada. |
| 24 | Release, promoção e prontidão de produção | **45** | Packet assinado e bindings estritos são bons; workflow verifica antes de gerar manifest e VPS não exige vínculo executável ao GO final. [Ordem de release](</home/ricardo/rick-intelligence/.github/workflows/quality.yml#L498-L510>). |
| 25 | Performance, capacidade e resiliência prolongada | **52** | Há harnesses e evidência local histórica; nenhum load/soak/chaos ou benchmark atual representativo foi executado aqui. [Pendências operacionais](</home/ricardo/rick-intelligence/docs/reports/producao-2026-10-04.md#L82-L96>). |
| 26 | Construção e rastreabilidade de imagens | **84** | Inputs por digest, construção/scan/SBOM/provenance/assinatura previstos e política independente. [Publisher](</home/ricardo/rick-intelligence/.github/workflows/publish-images.yml#L72-L115>). Registro/scans/assinaturas reais não repetidos; construção não é promoção. |

## 4. Achados priorizados e critérios de fechamento

Prioridades: **P1** = corrigir antes de promover; **P2** = próxima rodada de robustez/manutenção. Severidade mede impacto; prioridade mede ordem. Confiança é alta nos achados reproduzidos e nos encadeamentos estáticos abaixo, salvo ressalvas específicas.

### A01 — Alta / P1 — remoção dos legados quebra validação, coleta e CI

**Esperado:** comandos canônicos reproduzíveis e remoção só após equivalência/ajuste dos consumidores, conforme [regra de migração](</home/ricardo/rick-intelligence/README.md#L145-L156>).

**Observado:** `make validate` termina em exit 2, apontando os três componentes ausentes. A suite API original dá erro de coleta em autorização legada; retrieval dá dois erros em chunker/vector legados. A [lane supply-chain](</home/ricardo/rick-intelligence/.github/workflows/quality.yml#L334-L342>) ainda os exige.

**Impacto:** não se pode executar a cadeia canônica nem provar a equivalência declarada. Não foi revertida a exclusão, porque é trabalho anterior do usuário.

**Fechamento:** decidir preservação ou retirada autorizada, ajustar documentação/consumidores com regressões equivalentes e demonstrar validação + suites originais + CI em checkout limpo, sem exclusões ad hoc.

### A02 — Alta / P1 — busca continua expondo conteúdo de coleção arquivada

**Esperado:** lifecycle/revogação uniforme; Professor já [exige coleção ativa](</home/ricardo/rick-intelligence/apps/api/src/services/professor_backend.py#L125-L135>).

**Observado e reproduzido:** login 200 → busca 200/1 item → archive 200/`archived` → nova busca 200/1 item. A [busca](</home/ricardo/rick-intelligence/apps/api/src/routes/search.py#L152-L176>) revalida escopo, não a autoridade de lifecycle. [Log de reprodução](</home/ricardo/rick-intelligence/.runtime/audit-20261006/archive-reproduction.log>).

**Impacto:** conteúdo retirado do catálogo continua consultável. Reprodução in-process local; não foi executada exposição em Qdrant remoto nem demonstrado vazamento entre tenants.

**Fechamento:** revalidar coleção/documento/fontes atuais na admission e na resposta; regressão pública archive→search, com cache quente/frio, SQLite e backend remoto autorizado.

### A03 — Média / P1 — idempotência devolve resposta de outro pedido/conversa

**Esperado:** chave de retry ligada ao usuário e turno da conversa, conforme [ChatRequest](</home/ricardo/rick-intelligence/packages/contracts/src/rick_contracts/chat.py#L17-L22>).

**Observado:** conversa A/pergunta A/key K retorna 200; conversa B/pergunta diferente/key K retorna 200 com conversa A e resposta A. O [replay](</home/ricardo/rick-intelligence/apps/api/src/services/chat_service.py#L301-L307>) ocorre antes da preparação da conversa, sem comparar fingerprint do pedido. [Log](</home/ricardo/rick-intelligence/.runtime/audit-20261006/edge-reproductions.log#L3>).

**Impacto:** quebra de integridade request/response e potencial confusão de contexto. Não foi demonstrado vazamento entre usuários.

**Fechamento:** persistir fingerprint canônico/escopo do turno, repetir o mesmo pedido de forma estável e recusar reutilização incompatível com 409; cobrir JSON, SSE e stores in-memory/SQLite/PostgreSQL.

### A04 — Média / P2 — cache reidratado é global, mas sua leitura é scoped

A [primeira leitura](</home/ricardo/rick-intelligence/apps/api/src/services/retrieval_service.py#L80-L102>) filtra tenant/workspace/grants; depois [_indexed](</home/ricardo/rick-intelligence/apps/api/src/services/retrieval_service.py#L162-L173>) bloqueia nova reidratação para outro escopo. Reprodução: t1=1, t2=0, t1=1, leitor consultado apenas para t1. [Log](</home/ricardo/rick-intelligence/.runtime/audit-20261006/edge-reproductions.log#L4>).

**Impacto:** falsos vazios e disponibilidade/frescor local após reidratação; não é prova de leakage. Backend Qdrant remoto pesquisa independentemente desse índice; não generalizar o defeito para ele.

**Fechamento:** cache por escopo ou estratégia autorizada de reidratação/invalidação; testes alternando tenants, workspaces e grants, incluindo restart persistido.

### A05 — Média / P1 — extensão sem probe pode ser classificada como saudável

[ResilientProvider](</home/ricardo/rick-intelligence/packages/providers/src/rick_providers/resilience.py#L83-L122>) presume `production_safe=True` quando o port não se declara test e retorna circuito fechado quando falta health probe. Port sintético sem probe resultou `production_safe=True`, `health=True`, sem operação externa. [Log](</home/ricardo/rick-intelligence/.runtime/audit-20261006/edge-reproductions.log#L5>).

**Impacto condicionado ao integrador:** readiness de ports customizados pode exagerar saúde. A composição oficial registra probes próprios; não foi comprovado falso verde na produção canônica.

**Fechamento:** exigir marca explícita/probe nas extensões produtivas e falhar fechado se ausentes; testar a admission pela composição, não só pelo wrapper.

### A06 — Alta / P1 — npm audit atual aponta cadeia HIGH também sem dev

[Audit completo](</home/ricardo/rick-intelligence/.runtime/audit-20261006/npm-audit.json>) retorna 8 entradas HIGH; [audit sem dev](</home/ricardo/rick-intelligence/.runtime/audit-20261006/npm-audit-runtime.json>) retorna 3. O advisory raiz observado é [GHSA-68fv-2mgg-jv7q](https://github.com/advisories/GHSA-68fv-2mgg-jv7q), DoS por indexed source-map offsets em `source-map-js`; a propagação inclui `postcss`/`next` e ferramentas de desenvolvimento. O relatório npm não anuncia correção automática disponível.

**Qualificação:** entradas transitivas não equivalem a oito vulnerabilidades independentes; presença na árvore runtime não demonstra explorabilidade na aplicação instalada. Nenhuma exploração foi tentada. Alertas anteriores de outra cadeia não substituem esta consulta.

**Fechamento:** analisar a versão corrigida e alcançabilidade, atualizar/resolver a cadeia com revisão de compatibilidade e repetir install limpo, build, testes e audits; eventual aceite de risco exige autoridade humana.

### A07 — Alta / P1 — ordem de RELEASE rejeita até packet válido em runner limpo

[Workflow](</home/ricardo/rick-intelligence/.github/workflows/quality.yml#L498-L508>) chama o verificador selado antes de gerar release evidence. O [verificador](</home/ricardo/rick-intelligence/scripts/state_of_art/verify_sealed_promotion.py#L49-L56>) lê o manifest atual e devolve hash nulo se ausente; o [motor](</home/ricardo/rick-intelligence/scripts/state_of_art/promotion_engine.py#L764-L783>) exige igualdade do artifact hash.

**Evidência:** encadeamento estático; nenhuma execução GitHub atual foi consultada. O manifest necessário não é criado pelos passos anteriores mostrados.

**Fechamento:** gerar o manifest correto antes da verificação, sem relaxar bindings, e testar o job em ambiente limpo com packet válido/ausente/adulterado.

### A08 — Média / P2 — bootstrap do job RELEASE depende do runner

Após [setup-python](</home/ricardo/rick-intelligence/.github/workflows/quality.yml#L383-L386>), o job não instala explicitamente a dependência criptográfica do verificador. Jobs distintos não compartilham instalações.

**Impacto:** ambiente não reproduzível; presença ou ausência de cryptography no hosted runner não foi observada. Confiança alta na lacuna de declaração, não na ocorrência remota de ImportError.

**Fechamento:** instalar conjunto mínimo hash-locked e executar a verificação em ambiente sem pacotes pré-instalados.

### A09 — Alta / P1 — observabilidade staging não acompanha o instalador VPS

O [inventário VPS](</home/ricardo/rick-intelligence/infrastructure/vps/assets.py#L109-L113>) é fechado, sem collector/Prometheus/Alertmanager/backend de traces. A [allowlist do runtime.env](</home/ricardo/rick-intelligence/infrastructure/vps/deploy.py#L197-L199>) exclui `OTEL_`.

**Impacto:** provas de monitoramento do laboratório/staging não certificam alertas/traces no alvo. Collector externo é uma alternativa possível, mas seu transporte/configuração ainda precisa ser provado; não se exige necessariamente stack embutida.

**Fechamento:** composição/integrador operacional revisado, transporte explícito de configuração e ensaio no alvo autorizado de scrape, perda/no-data, trace, entrega e recuperação de alerta.

### A10 — Alta / P1 — falta vínculo executável de promoção final na admissão VPS

[Attestations de construção](</home/ricardo/rick-intelligence/infrastructure/vps/deploy.py#L137-L147>) aceitas têm `promotion_authorized:false`. A [política de admissão](</home/ricardo/rick-intelligence/infrastructure/vps/admission.py#L69-L91>) liga source/construction/tool/quality, não o packet runtime/GO. [Install/upgrade](</home/ricardo/rick-intelligence/infrastructure/vps/deploy.py#L380-L391>) usa checagem REC33; o [teste estático](</home/ricardo/rick-intelligence/infrastructure/docker/tests/test_release_static.py#L38-L79>) aceita referências declaradas de canary/rollback sem abrir esses arquivos.

**Qualificação importante:** há hashes externos obrigatórios e revisão humana de políticas. Não é exploit nem bypass humano demonstrado; é uma lacuna do vínculo verificável entre decisão de promoção e os digests efetivamente instalados.

**Fechamento:** alvo production exigir packet/GO válido dos mesmos digests e rejeitar construction-only; permitir laboratório apenas por modo explícito separado.

### A11 — Média / P2 — porcentagem de cobertura web tem denominador parcial

92,14% descrevem os dez arquivos explicitados na [configuração](</home/ricardo/rick-intelligence/apps/web/vitest.config.ts#L8-L14>), não a aplicação inteira. Rotas, wrappers de request e outros workspaces estão excluídos e isso é honestamente [documentado](</home/ricardo/rick-intelligence/apps/web/README.md#L33-L42>). App shell sozinho tem 61,45% de linhas e 46,42% de branches nessa execução.

**Fechamento:** ampliar cobertura por risco sobre documentos/search/admin/wrappers e fluxos de erro/revogação; reportar denominador e cobertura por componente, complementados pelo browser. Não simplesmente elevar a meta agregada.

### A12 — Média / P2 — autoridades documentais divergentes

[README](</home/ricardo/rick-intelligence/README.md#L3-L17>) descreve legados byte-identical; [toolchain](</home/ricardo/rick-intelligence/toolchain.json#L30-L36>) aponta instalações ausentes; [índice](</home/ricardo/rick-intelligence/docs/INDEX.md#L3-L4>) ancora baseline de 02–03/10; [estado posterior](</home/ricardo/rick-intelligence/docs/reports/producao-2026-10-04.md#L1-L14>) descreve candidata isolada diferente. A [matriz de autorização documental](</home/ricardo/rick-intelligence/docs/architecture/authorization.md#L16-L20>) também não acompanha permissões de casos atuais.

**Fechamento:** autoridade atual única com SHA/worktree e datas; marcar históricos, reconciliar comandos, instalação, remoção de legados, papéis e fronteiras local/alvo real. Não apagar história útil.

### A13 — Média / P2 — healthcheck worker não prova progresso do daemon

O [entrypoint](</home/ricardo/rick-intelligence/infrastructure/docker/worker-entrypoint.py#L157-L177>) cria outra composição, avalia startup/readiness e a encerra. Isso mede composição/dependências, não diretamente heartbeat, capacidade ou falha fatal do processo worker original.

**Fechamento:** sinal de liveness/progresso do daemon com timestamp/limite de staleness e teste de loop travado/morto; manter readiness das dependências separada. Não foi demonstrada perda de dados.

### A14 — Lacuna de evidência / P1 antes de produção — qualidade e operação reais

Modelo/corpus representativos, licença/proveniência, aceite clínico, latência/custo, partições de stores, restore conjunto, budgets aprovados, carga/soak e canary do alvo permanecem fora da prova desta rodada. O [relatório operacional anterior](</home/ricardo/rick-intelligence/docs/reports/producao-2026-10-04.md#L82-L96>) também os distingue de sucesso local.

**Fechamento:** executar matriz autorizada, com limites de custo/dados/falhas, e evidência fresca ligada ao mesmo candidato/digests. Falta de execução é NOT_RUN nesta auditoria, não prova de que uma feature inexiste.

## 5. Verificações executadas nesta rodada

### Ambiente e controles

| Procedimento | Exit | Resultado/limite |
|---|---:|---|
| Estado Git, pwd, HEAD | 0 | Checkout e dirty worktree identificados |
| Criação venv uv inicial | 1 | uv escolheu Python 3.10; incompatível com lock >=3.12. Falha preservada no registro da sessão |
| venv explícito `/usr/bin/python3` + install `--require-hashes -r requirements/test.lock` | 0 | Python 3.12.3, **91 pacotes** instalados em ambiente próprio |
| `make validate` | **2** | Restauração/check de controles passou; fronteira falhou pelos três legados ausentes. [Log](</home/ricardo/rick-intelligence/.runtime/audit-20261006/validate.log>) |
| `make ops-migration-check quality-bar-static security-adversarial eval-retrieval-pack` | 0 | Dez migrations + sidecar conferidos; quality bar PASS; oito registros adversariais estruturais; cinco casos offline RAG PASS. **Nenhum ataque real ou SQL real executado** |
| `check_toolchain.py`, `check_workflow_actions.py`, `check_canonical_ci.py`, `git diff --check` | 0 cada | Tags/SHAs/regras sintáticas e whitespace passaram; não provam execução de CI |
| `pip-audit --disable-pip --no-deps -r requirements/runtime.lock --format json` | 0 | Nenhuma vulnerabilidade conhecida reportada para o inventário de runtime travado. [JSON](</home/ricardo/rick-intelligence/.runtime/audit-20261006/python-audit.json>) |
| `npm audit --json`; `npm audit --omit=dev --json` | **1 / 1** | 8 HIGH totais / 3 HIGH sem dev; zero CRITICAL reportados |

Python global instalado tinha versões antigas de FastAPI/Pydantic. Ele **não foi usado como prova das suites amplas**: estas usaram o venv312 do lock. Node/npm locais eram **24.20.0 / 11.19.0**, distintos do [contrato declarado](</home/ricardo/rick-intelligence/toolchain.json#L3-L6>) 22.19.0 / 10.9.3. Os resultados web são válidos para o ambiente observado, não substituem repetição no toolchain canônico.

### Suites Python

Comando-base: `.runtime/audit-20261006/venv312/bin/python -m pytest -q -p no:cacheprovider <suite>`, com paths dos packages/apps no PYTHONPATH, `PYTHONDONTWRITEBYTECODE=1`, ambiente test e remoção de marcadores de serviços externos. Cada suite foi executada em processo separado.

| Suite | Resultado atual | Exit | Evidência |
|---|---|---:|---|
| API original | Erro de coleta, referência legada ausente | **2** | [API](</home/ricardo/rick-intelligence/.runtime/audit-20261006/api.log>) |
| API diagnóstico, **excluindo somente módulo diferencial de auth legado** | **1.561 PASS, 18 skips**, 1 warning | 0 | [API diagnóstico](</home/ricardo/rick-intelligence/.runtime/audit-20261006/api-without-legacy-auth.log>) |
| Worker | **734 PASS** | 0 | [Worker](</home/ricardo/rick-intelligence/.runtime/audit-20261006/worker.log>) |
| Authorization | 34 PASS | 0 | [Authorization](</home/ricardo/rick-intelligence/.runtime/audit-20261006/authorization.log>) |
| Contracts | 12 PASS | 0 | [Contracts](</home/ricardo/rick-intelligence/.runtime/audit-20261006/contracts.log>) |
| Decision | 42 PASS | 0 | [Decision](</home/ricardo/rick-intelligence/.runtime/audit-20261006/decision.log>) |
| Evidence | 9 PASS | 0 | [Evidence](</home/ricardo/rick-intelligence/.runtime/audit-20261006/evidence.log>) |
| Identity | 201 PASS, **16 skips** | 0 | [Identity](</home/ricardo/rick-intelligence/.runtime/audit-20261006/identity.log>) |
| Ingestion | **374 PASS** | 0 | [Ingestion](</home/ricardo/rick-intelligence/.runtime/audit-20261006/ingestion.log>) |
| Jobs | 14 PASS | 0 | [Jobs](</home/ricardo/rick-intelligence/.runtime/audit-20261006/jobs.log>) |
| Knowledge | 83 PASS, **98 skips** | 0 | [Knowledge](</home/ricardo/rick-intelligence/.runtime/audit-20261006/knowledge.log>) |
| Locking | 54 PASS | 0 | [Locking](</home/ricardo/rick-intelligence/.runtime/audit-20261006/locking.log>) |
| Observability | 49 PASS | 0 | [Observability](</home/ricardo/rick-intelligence/.runtime/audit-20261006/observability.log>) |
| Professor | 93 PASS | 0 | [Professor](</home/ricardo/rick-intelligence/.runtime/audit-20261006/professor.log>) |
| Providers | **2.143 PASS** | 0 | [Providers](</home/ricardo/rick-intelligence/.runtime/audit-20261006/providers.log>) |
| Retrieval original | Dois erros de coleta em referências legadas | **2** | [Retrieval](</home/ricardo/rick-intelligence/.runtime/audit-20261006/retrieval.log>) |
| Retrieval diagnóstico, **excluindo diferencial/shadow legacy** | **140 PASS, 5 skips** | 0 | [Retrieval diagnóstico](</home/ricardo/rick-intelligence/.runtime/audit-20261006/retrieval-without-legacy.log>) |
| Storage | 28 PASS | 0 | [Storage](</home/ricardo/rick-intelligence/.runtime/audit-20261006/storage.log>) |

O [registro dos processos originais](</home/ricardo/rick-intelligence/.runtime/audit-20261006/python-results.json>) conserva comandos, durações e exit codes. A batch original terminou **exit 1**, por API/retrieval. Diagnósticos com exclusões **não transformam suites originais em PASS**. Skips externos foram mantidos visíveis; não representam aceite PostgreSQL.

Revisões adicionais delegadas reportaram 266 testes focados no lock e 105 herméticos de worker/configuração/assinatura. Há sobreposição com as matrizes acima; **não foram somados como testes únicos**. A primeira tentativa operacional usou executável `.venv` ausente (exit 127), corrigida para Python disponível; a revisão backend também registrou execução inicial no Python global e ausência de jsonschema, antes da repetição locked. Esses ensaios preliminares não substituem a matriz do Lead.

### Frontend

- `npm run lint`: exit **0**.
- `npm run typecheck`: exit **0**.
- `RICK_WEB_COVERAGE_DIR=... npm run test:coverage`: exit **0**, **76 PASS**, seis arquivos de testes; linhas **92,14%**, branches **81,55%**, no denominador de dez fontes. [Cobertura](</home/ricardo/rick-intelligence/.runtime/audit-20261006/web-coverage/coverage-summary.json>).
- `NEXT_DIST_DIR=.next-audit-20261006 RICK_API_INTERNAL_URL=http://127.0.0.1:8001 npm run build`: exit **0**, Next **15.5.25**, geração de 12 páginas e compilação concluídas. Nenhum servidor foi iniciado por esse build.
- Playwright, inspeção visual, leitor de tela e medição LCP/CLS atuais: **NOT_RUN**. Contagens históricas de browser não foram reutilizadas como PASS fresco.

### Reproduções de defeitos

Executáveis de auditoria, sem alteração da implementação:

```bash
PYTHONDONTWRITEBYTECODE=1 python3 .runtime/audit-20261006/reproduce_archive.py
PYTHONDONTWRITEBYTECODE=1 python3 .runtime/audit-20261006/reproduce_edges.py
```

[Reprodutor archive](</home/ricardo/rick-intelligence/.runtime/audit-20261006/reproduce_archive.py>) e [reprodutor de bordas](</home/ricardo/rick-intelligence/.runtime/audit-20261006/reproduce_edges.py>) constroem ambiente test isolado e usam TestClient/stores sintéticos. Ambos tiveram exit **0**, significando **defeitos confirmados**, não aprovação do produto. [Resultados archive](</home/ricardo/rick-intelligence/.runtime/audit-20261006/archive-reproduction.log>) e [resultados de bordas](</home/ricardo/rick-intelligence/.runtime/audit-20261006/edge-reproductions.log>).

## 6. Ordem recomendada de correção

1. **Recuperar a cadeia canônica do checkout:** resolver A01 e reconciliar documentação sem descartar trabalho existente.
2. **Proteger integridade/frescor no limite público:** A02 e A03 primeiro; regressões que falham antes e passam depois. Em seguida A04/A05.
3. **Fechar dependências e entrega:** A06; corrigir ordem/bootstrap A07/A08 e comprovar vínculo de promoção A10, sem dispensar checks ou hashes.
4. **Homologar a operação real:** observabilidade VPS A09, health do daemon A13, restore/rollback/carga/corpus/providers e aceite humano A14.
5. **Aprimorar cobertura e manutenção:** A11/A12 e decomposição incremental dos maiores módulos, preservando invariantes.

**Próxima ação única:** preparar um patch de recuperação de A01, com decisão explícita sobre os legados e prova de `make validate` + suites originais em checkout limpo. Esta auditoria não aplica esse patch nem autoriza promoção.

## 7. Limitações e veredito final

Revisão por amostragem, não pentest nem certificação. Não foram exercitados infraestrutura VPS, GitHub remoto atual, PostgreSQL/Redis/Qdrant/object store reais, IdP ou modelos reais, migrações reais, rede distribuída, corpus clínico aprovado, performance/soak/chaos atuais ou cadeia completa registry/signatures. Sem garantia de ausência de segredos no histórico Git: scanner completo não foi executado nesta rodada.

As notas de armazenamento, migração, worker e providers descrevem força local + inspeção; não atestam comportamento sob todas as falhas produtivas. Consultas de vulnerabilidade são pontuais e não comprovam ausência futura de falhas. O worktree auditado não é release publicada, e a média não é um gate.

**Veredito: implementação local tecnicamente sólida em várias áreas, mas com falhas funcionais e de reprodução/entrega que impedem recomendar promoção para produção.**
