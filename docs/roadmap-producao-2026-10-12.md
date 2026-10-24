# Roadmap — da auditoria à produção controlada

**Data:** 12/10/2026. **Estado:** PROPOSTO PARA EXECUÇÃO; produto NO-GO. **Base:** `48e383c25ca4af32aa7ffe7e2367360ca9742c58`, checkout limpo antes da elaboração. Este pedido autoriza preparar documentos, não implementar correções nem implantar.

**Resultado esperado:** um release reproduzível, seguro, durável, multi-tenant, observável e recuperável, com funcionalidades aprovadas e qualidade de evidência demonstrada, seguido de entrada controlada em produção e acompanhamento real. Não se promete diagnóstico/prescrição autônomos, HA de single VPS ou AAA por documentação.

O [backlog PROD12](<backlog-producao-2026-10-12.md>) define **56 tarefas**, responsáveis sugeridos, dependências, aceites e rastreabilidade dos 13 achados/26 dimensões. Ele é a especificação da fila proposta; após adoção aprovada, o [controlador](<../.agent/backlog.json>) será o único owner de status/evidência. Este roadmap possui sequência, gates e decisões, não replica status de cada item.

## 1. Ponto de partida e preservação

A [baseline de 12/10](<reports/baseline-producao-2026-10-12.md>) registra 7.713 testes Python aprovados, **6 falhas e 221 skips**, checks web aprovados e cinco probes herméticos que expuseram defeitos. Cinco falhas da suíte têm causas ambientais; a sexta é inventário de manifesto duplicado. O plano exige novos resultados, não apagar as falhas. Serviços/browser/carga/restore reais não foram exercitados nessa auditoria.

A [retomada de 09/10](<reports/retomada-2026-10-09.md>) e o [backlog AUD07](<backlog-auditoria-2026-10-07.md>) preservam implementações anteriores. **Não repetir automaticamente AUD07-01–26/44–46.** AUD07-27/43 e provas externas 28–42 são relacionadas aos novos itens, sem transição automática dos seus aceites. Achados `AUD12-Axx` têm namespace distinto dos antigos Axx.

Não há migração/rewrite de arquitetura por moda. Reusar FastAPI/Python worker/Next, pacotes, adapters, assets Docker/VPS/CI e contratos existentes; corrigir lacunas observadas e comprovar as fronteiras reais.

## 2. Marcos e gates de saída

| Marco | Entrega demonstrável | Itens do backlog | Gate de saída |
|---|---|---|---|
| **M0 — Base, perfil e autoridade** | Baseline preservada, controle recuperado, executor compatível, escolhas/owners/budgets e recursos autorizados | 001–006 | **G0:** fontes/IDs/owner de status únicos; decisões e pré-condições documentadas, nenhum pressuposto externo apresentado como PASS |
| **M1 — Integridade e segurança** | Logout honesto, shutdown/claims/teardown corretos, search protegido, anti-spray/cardinalidade e contrato CSRF verificados | 007–014 | **G1:** regressões rejeitam código anterior e passam no corrigido; nenhum P0 dessa superfície aberto, revisão independente |
| **M2 — Produto local reproduzível** | Inventário/toolchain/gates corretos, tipos/cobertura ampliados por risco, docs e web corrigidos, candidato integrado | 015–026 | **G2:** mesmos SHA/toolchain/FS, gates locais e browser local obrigatórios aprovados, seis falhas reconciliadas, skips classificados; 019 é advisory |
| **M3 — Imagens, staging e stores** | Imagens imutáveis/scans, topologia segura, lab production-shaped atestado, migrations/Redis/S3/Qdrant reais | 027–032 | **G3:** ownership/autorizações/probes/fencing/ACL básicas e preflight válidos; artefatos são os que serão testados/promovidos |
| **M4 — Integração e qualidade do produto** | Golden path, identidade/tenant/worker A/B, provider/corpus hostil/RAG/evidência/clínico, browser real e segurança externa | 033–042 | **G4:** provas ponta a ponta/negativas reais, corpus e escopo aprovados, funcionamento e segurança verificáveis no candidato exato |
| **M5 — Operação e recuperação** | Telemetria/audit/alertas, restore/rollback, capacidade/custo/chaos/soak e operação humana demonstrados | 043–049 | **G5:** budgets pré-aprovados atendidos e runbooks executados por operador distinto; nenhum gap material de recuperação/observabilidade |
| **M6 — Release e autorização** | 050 fecha gates técnicos pré-autoridade; 051 obtém reviews; 052 prepara packet/trust; 053 reúne D07 e signer independente para decisão, selo, validação total e ratificação | 050–053 | **G6:** somente no fim de 053 todos gates mandatórios atuais PASS, zero Critical/High, evidências íntegras/frescas, scorecard requerido e GO explícito sobre bytes/digests exatos |
| **M7 — Produção controlada** | Canary com dados/tenants limitados, expansão autorizada, handoff e observação de produção | 054–056 | **G7a:** canary atende policy para expandir; **G7b:** operação transferida e primeiro ciclo real revisado, SLIs sem alegações antecipadas |

Marcos são aceites, não barreiras artificiais ao trabalho: correções M1 podem começar após 001 enquanto M0 resolve owners/recursos; preparação de corpus/lab/runbook pode começar cedo. **Execução externa** requer autorização de 006 e respectivos gates. Aceite M6 exige todos obrigatórios pre-release; M7 é uma obrigação pós-Go, não um pré-requisito circular para autorizar canary.

### Caminho de dependências

```text
001 baseline
  ├─ 002/003/004 → 005 → 006 (controle, executor, perfil, budgets e autoridade)
  ├─ 007 logout + 008 → 009 → 010 worker + 011 → 012 → 013 limites + 014 CSRF
  └─ 015/016 + 021–025 (inventário/toolchain/produto)
       → 017/018/020 → 026 candidato local integrado [G2]
       → 027 → 028 → 029 → 030/031/032 staging/stores [G3]
       → 033/034 → 035/036/037/038/039/040/041/042 [G4]
       → 043/044/045/046/047/048/049 [G5]
       → 050 → 051 → 052 → 053 [G6]
       → 054 canary → 055 expansão/handoff → 056 ciclo real [G7]
```

Esse desenho é resumido: **as dependências AND da tabela do backlog prevalecem**. M4/M5 permitem frentes simultâneas depois de pré-condições, não obrigam serializar todos os ensaios; candidate/config/fixture namespaces e ownership não podem colidir.

## 3. O que significa estar pronto para produção

Não basta uma média alta, um teste unitário, Dockerfile ou assinatura. A [barra congelada](<../.gauntlet/bar.json>), o [motor de promoção](<../scripts/state_of_art/promotion_engine.py>), a [integridade de release](<architecture/release-integrity.md>) e a [autoridade de promoção](<architecture/promotion-authority.md>) continuam governando os gates.

Para G6, demonstrar:

1. SHA/tree/fingerprint limpos e únicos; CI, runtimes, configurações e digests das imagens correspondem ao mesmo candidato. Não construir imagem nova no final e reutilizar provas de outra.
2. Todos os P0/P1/gates mandatórios satisfeitos no escopo ativo; nada `FAIL`, `NOT_RUN`, `BLOCKED_EXTERNAL`, `STALE`, `INVALID` ou `no_data` apresentado como PASS.
3. Serviços reais e runtime production-shaped **com autoridade externa**, golden path, tenant/revogação/evidência negativos e workers A/B/crash/sinais comprovados. Lab local sozinho não satisfaz a autoridade production-runtime.
4. Restore integrado e capacidade/chaos/soak com workload/budgets definidos antes; audit/observabilidade/alertas e on-call funcionam. Dados pessoais/clinicamente sensíveis apenas com autorização e proteção próprias.
5. Imagens/digests/SBOM/scans/provenance/assinaturas confiáveis, **zero HIGH/CRITICAL inclusive unfixed**, conforme política vigente. Sem exceções de scanner para esconder chaves reais.
6. **12 escopos independentes frescos** com tentativa de rejeição, **checklist de 18 riscos** e **scorecard tipado de 26 dimensões**, overall derivado **≥96/100**, zero Critical/High e Medium com owner/mitigação/aceite/review/expiração. Essa é a exigência do pacote atual, não o score opinativo da auditoria e não as contagens de planos predecessores.
7. Packet Ed25519/trust store íntegros e retidos, refs/hash/candidato válidos e decisão humana independente D07 ligada aos bytes/digests exatos. Não criar executores que fabriquem PASS nas lanes de autoridade `command=None`.
8. Plano de instalação, canary, reversão compatível/roll-forward, owners, limites de usuários/custos e autorizações explícitos. Uma publicação candidata no registry não é promoção.

**Frescor:** o contrato de release contém janela de 24 horas, além de validade própria do preflight/run. Testes longos e reviews podem exigir reexecução de provas vencidas antes do selo. Registrar observação real; nunca rejuvenecer timestamp/checksum por edição. Se código/config/topologia muda por correção, retornar ao gate afetado e repetir as provas pertinentes.

### Canary e SLO não são a mesma coisa

A [política REC-33](<../infrastructure/docker/rollout-policy.json>) exige **≥900 s**, **≥100 requests**, **5xx ≤1%**, **p95 ≤1500 ms**, **crescimento DLQ = 0**, readiness verdadeira e rollback **≤300 s**, com preservação de dados e compatibilidade/roll-forward. Esses targets já existem e não são inventados por este roadmap.

Os [SLOs](<operations/slo.md>) são pontos iniciais de política para ratificação: API ≥99,9%/30 dias; chat ≥99%/30 dias; retrieval autorizado p95 ≤1,5 s/30 dias; jobs publicados ou explicitamente DLQ ≥99%/24 h; durabilidade 100% por drill; citation support ≥99% no conjunto aprovado; provider errors ≤5%/10 min. RPO/RTO, teto de gasto e duração/carga de soak precisam decisão específica em 005.

Antes do primeiro Go não há 30 dias de serviço novo observados. Aprovar canary com os gates pre-release **não** permite afirmar SLO de produção atendido: começar com `no_data`, coletar a janela real em 056 e agir sobre breaches. Staging e observação local mantêm classes separadas.

## 4. Decisões, recursos e responsáveis

| Assunto | Já registrado / o que confirmar | Owner sugerido | Itens |
|---|---|---|---|
| Identidade | [VPS: postgres-local-v1](<operations/vps-github-images.md#L337-L342>); store/verifier/roles/recuperação atuais e prova live. IdP/OIDC exige escolha e composição reais, não URLs | Segurança/identidade/produto | 004,007,030,035 |
| Providers | Chat OpenAI ou Anthropic; embeddings OpenAI independentes; modelo/dimensão/capabilities/dados/budget definidos | Produto/RAG/provider | 004,005,033,038 |
| Clínica/casos | [D04 intake amplo e revisão humana](<architecture/domain-decision-policy-2026-09-24.md>); sem aprovação de safety/release. Persistência/permissões/PII e feature flags de lançamento | Domínio/privacidade/segurança | 004,021,038–041 |
| Topologia | Reusar [deploy VPS](<operations/vps-github-images.md>) ou runtime aprovado; capacidade/HA/volumes/endpoints reais, não só arquivos presentes | SRE/DBA | 004,006,027–032 |
| SLIs, RPO/RTO e custos | Ratificar policy e workloads antes dos testes; pessoas/contatos e poder de aborto | SRE/produto/domínio | 005,043–049 |
| Corpus e dados | Direitos, consentimento/classificação, retenção, estratos e adjudicação, transferência ao provider | Dados/domínio/privacidade | 004–006,037–040,049 |
| Release/registry/review | Permissão publication/signer/trust store; 12 scopes e D07 independentes; escopo do Go/canary | Release authority | 006,028,050–055 |

A preparação pode ser feita sem expor credenciais: registrar nomes e referências ao secret manager, nunca valores. Não afirmar recurso indisponível apenas porque faltou prova na auditoria; conferir disponibilidade e permissão em 006.

**Lançamento limitado recomendado:** tenants/corpus/capacidade/custos bounded, workflow clínico de intake/revisão mantido e expansão por resultados. É proposta para ratificação, **não redução dos gates**. Desativar feature opcional só com perfil formal, provar que está fechada e não marcar sua capacidade inexistente como implementada. Segurança, isolamento, recuperação, policy clínica e autoridade de release não são opcionais.

## 5. Organização da execução e paralelismo

| Frente | Responsabilidade / ownership | Coordenação |
|---|---|---|
| Identidade/abuso | Auth/PG identity/rate limit/search; 007,011–014,035 | Auth e limiter compartilhados: mesmo owner ou serialização; contrato de quotas primeiro |
| Worker/dados | Runtime/composição/queue/migrations; 008–010,030,036,044,045 | 008/009/010 sequenciais; locks/schema/lease acordados; DB/namespace único por ensaio |
| Web/produto | Casos/chat/documentos/foco; 021–025,040,041 | Chat 022/023 e wrapper/cobertura 018 coordenados; casos e documentos podem ser disjuntos |
| Plataforma/CI/evidência | Controle/artifacts/locks/workflows/images/lab; 002,003,015,016,027–032,050–054 | Um integrador de Make/locks/workflows; registrador único de evidência/ledgers |
| RAG/domínio | Provider/embeddings/corpus/claims/abstenção; 033,038–040 | Dataset/modelo/policy/version/authority estáveis; não transmitir dados sem consentimento |
| Operação/review | OTel/audit/DR/load/chaos/soak/on-call/release | Ensaios destrutivos e load compartilham recursos: namespaces disjuntos ou janelas sequenciais; reviewers distintos dos builders |

**WIP proposto:** uma tarefa de escrita por owner/recurso compartilhado; o Lead integra contratos e diffs. Read-only scouts podem ser paralelos; writers nunca disputam código, schema, ports, recursos ou ledgers. No fim de cada unidade: teste focado → regressão integrada → review independente quando exigido → evidência → status no owner único.

### Primeira onda prática

- Preservar/adotar: **001 → 002**, e **003/004** em paralelo.
- Corrigir primeiro: **007**, **008 → 009 → 010** e **011**, com owners separados; 012/013 após os contratos comuns.
- Recuperar gates: **015 → 016**; começar casos **021**, chat **022 → 023** e retry **024** após baseline/perfil aplicáveis.
- Fechar tipos/cobertura/docs/acessibilidade: **017/018/020/025**; então **026** demonstra candidato local. Sem avançar para deploy porque o local ficou verde.
- Confirmar **005/006** enquanto a implementação local avança; corpus/recursos/autoridade costumam determinar o caminho crítico externo.

## 6. Estimativa, horizonte e controle de mudanças

Não há data de produção prometida: disponibilidade da equipe, do corpus, de infraestrutura/custos e de reviewers não foi informada. P/M/G do backlog são estimativas relativas de risco/superfície, não horas ou dias. Depois de M0, decompor itens G, estimar capacidade por owner e montar calendário com buffers de rerun/review/frescor.

- **Horizonte detalhado:** M0–M2, bugs concretos e gates locais.
- **Horizonte condicionado:** M3–M5, contratos conhecidos, mas implantação/datasets/volumes/providers exigem discovery e recursos autorizados.
- **Horizonte de release:** M6–M7, datas derivadas de provas e autoridade, não de porcentagem de backlog concluído.
- **Advisory/pós-primeiro Go:** 019, refatoração adicional por risco/benefício. Escala, HA, novos providers e recursos avançados entram em release próprio se o perfil os exigir; não dispensam obrigações atuais.

Alterar scope, policy, budgets ou requisitos após novos fatos requer motivo/evidência/owner/impacto/autoridade e nova baseline. Não baixar targets porque uma execução falhou. Cada mudança material conserva história e revalida o artefato afetado.

## 7. Validação a executar durante a implementação

Comandos abaixo são contratos existentes a inspecionar e executar **nas tarefas correspondentes**, não procedimentos realizados para escrever este plano. Confirmar inputs, ambiente, efeitos, autorizações, candidate binding e evidência antes de cada execução. Fonte: [Makefile](<../Makefile>).

```text
# Candidato local; preservar falhas e ambiente, instalar só dos locks
make control-inputs-check validate
make ci
make api-test api-contract api-security api14-acl api16-full
make compose-static ops-static eval-retrieval-pack security-adversarial storage-test
make web-validate
PYTHONDONTWRITEBYTECODE=1 .runtime/venvs/cvg/bin/python -m pytest \
  -q -p no:cacheprovider apps/api/tests packages apps/worker/tests scripts infrastructure

# Runtime autorizado com preflight/inputs e namespace descartáveis
make phase3-postgres-runtime
make phase3-redis-runtime phase3-redis-multi-replica-runtime
make phase3-object-qdrant-runtime phase3-multi-worker-runtime
make phase3-provider-runtime phase3-golden-runtime phase3-provider-rag-runtime
make phase3-tenant-evidence-runtime phase3-file-security-runtime
make phase3-observability-runtime phase3-restore-runtime
make phase3-performance phase3-chaos phase3-soak
make phase3-frontend-supply-runtime

# Observar/verificar envelopes e promoção: comandos NÃO assinam nem dão Go
make triple-aaa-capability-matrix phase3-evidence
make phase3-evidence-verify triple-aaa-verify
```

Inputs de packet selado/trust store/authority são obrigatórios conforme [contrato de integridade](<architecture/release-integrity.md#L134-L181>); não presumir que `make` sem eles aprova. Mudança de código/config durante gates exige novo candidato/reexecução. A política de estado do [runbook de operação](<operations/release-readiness.md>) e os targets dos validators prevalecem.

## 8. Recuperação e Definition of Done

Antes de retomar uma tarefa: ler fontes/contrato, conferir SHA/status/processos/recursos e status do controlador, validar se inputs/artefatos estão atuais. Se uma operação externa interrompeu, inventariar efeitos/leases/migrations/jobs/objetos antes de retry; não reexecutar DDL/deploy/delete por adivinhação. Só limpar recursos com ownership provado. Falha relevante retorna à investigação/correção com resultado preservado.

**Pronto para canary:** G0–G6 obrigatórios comprovados, decisão/artefatos/escopo/rollback autorizados. **Entrada controlada concluída:** 054/055 aprovados e operação assumida. **Primeiro ciclo operacional concluído:** 056 com dados reais da janela e ações/owners. **Evolução contínua:** SLIs, incidentes, patches de dependências, restore drills e novos riscos geram nova execução, não encerramento permanente de segurança.

**Próximo passo:** designar responsáveis e aprovar a adoção da primeira onda (001–004 e bugs P0 007–011), incluindo contrato de ownership. Autorizações de ambiente, custos, dados e produção permanecem decisões separadas. Produto continua **NO-GO** enquanto os gates obrigatórios não forem comprovados.

## 9. Verificação desta entrega de planejamento

Em 12/10/2026 foram executados o checker documental e a validação estrutural do backlog: **836 links locais, zero erros; 56 IDs únicos e 56 contratos de entrega/aceite; dependências acíclicas; 13 achados AUD12 e 17 obrigações AUD07-27–43 mapeados; 55 itens obrigatórios e um advisory**. Checker, validação do plano e `git diff --check` retornaram exit 0. O diff versionado foi limitado ao README/índice; os novos arquivos são documentação, sem alteração de implementação/configuração/ledgers.

Dois scouts reconciliaram backlog/decisões/gates, e um terceiro contexto independente revisou o plano. A primeira revisão rejeitou uma circularidade semântica em 050 (exigir reviews/selo/Go ainda futuros); o texto foi corrigido para gates técnicos em 050, preparação em 052 e transação D07/signer em 053. Após releitura, o revisor retornou **APPROVE do plano**, não do produto nem da implementação.

Não foram reexecutadas suítes de produto, gates runtime, scans, deploys ou autorizações para escrever este planejamento. Resultados da baseline continuam históricos; código e prontidão de produção não foram melhorados apenas pela criação destes documentos.
