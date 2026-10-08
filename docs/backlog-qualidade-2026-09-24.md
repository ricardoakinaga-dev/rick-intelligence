# Backlog de atualizações e melhorias — RICK Intelligence

**Data-base:** 24/09/2026. **Versão:** BL24-v1, com checkpoints locais em 25/09. O catálogo mantém os critérios propostos; os avanços de Q24-03, Q24-05, Q24-06, Q24-08, Q24-19–Q24-21 e Q24-25/Q24-26 seguem parciais e sem encerramento canônico.

Referências: [plano executivo](plano-executivo-qualidade-2026-09-24.md), [roadmap](roadmap-qualidade-2026-09-24.md), [auditoria e achados A24](relatorio-auditoria-2026-09-24.md), [catálogo Q17](plans/backlog-qualidade-2026-09-17.md), [matriz de recuperação Q17](reports/matriz-rastreabilidade-q17-2026-09-17.md) e [backlog canônico](../.agent/backlog.json).

## 1. Como executar este backlog

Q24 identifica resultados propostos para a próxima execução. Q17 continua identificando os trabalhos anteriores. Reutilizar o item canônico equivalente e adicionar o vínculo Q24; criar subtarefa apenas para escopo que ainda não existe. O mapeamento não transfere automaticamente status ou aceita correções com validação pendente. Pendências do catálogo anterior que não forem encerradas continuam existentes.

**Prioridades:** P0 bloqueia segurança, isolamento ou uso básico; P1 é necessário para completar o produto e sua validação. Prioridade não afirma que um incidente ocorreu. **Porte relativo:** P = ajuste localizado; M = alteração de fronteira ou fluxo; G = integração/campanha que exige decomposição e checkpoints. Porte não é estimativa de prazo. Responsáveis são papéis a designar.

As dependências da tabela são resultados técnicos prévios. D01–D07 remetem às decisões do plano executivo e condicionam apenas o efeito dependente: preparação e testes locais podem avançar sem credenciais, orçamento ou implantação. Conferir decisões já existentes antes de pedir qualquer nova autorização. A escrita deste catálogo está concluída; o estado real de implementação pertence a `.agent/`.

### Contrato comum de aceite

Antes de editar, confirmar o achado no candidato atual e registrar a reprodução ou expectativa discriminante. Alterar o menor conjunto conectado, testar o resultado correto e pelo menos o modo de falha relevante. Executar regressões compatíveis com o impacto, revisar o diff e registrar limitações. Item G deve ser dividido em incrementos demonstráveis antes do BUILD, sem perder os critérios finais descritos aqui.

Uma tarefa só pode ser encerrada no controle canônico quando sua prova exigida estiver disponível: ID Q24/Q17, commit/tree ou identificação da árvore local, arquivos e hashes, ambiente, dados/modelo quando aplicável, comando/procedimento, exit code, resultado, artefatos sanitizados, revisão e recuperação. Não somar suítes sobrepostas como testes únicos. Prova unitária não substitui a prova integrada explicitamente pedida.

Não editar evidência histórica, remover teste reprovado, transformar erro em sucesso ou descartar resultados negativos para encerrar uma tarefa. Achado refutado recebe disposição justificada. Não apagar alterações alheias, volumes ou histórico de migrações. A prova parcial permanece parcial.

## 2. Fila priorizada e dependências

As prioridades e dependências abaixo descrevem o escopo proposto. O status de execução pertence a `.agent/`; neste checkpoint, Q24-19/Q24-20 têm implementação e testes locais, permanecendo abertos para revisão e aceitação mais ampla. “Nenhuma adicional” na última coluna não amplia a autorização do pedido: apenas indica ausência de uma decisão externa específica além da autorização de implementação vigente.

| ID | Marco | Prioridade | Porte | Responsável proposto | Dependências técnicas | Decisão para efeito dependente |
|---|---|---|---|---|---|---|
| Q24-01 | M0 | P0 | M | Lead | Nenhuma | Conferir D06 existente |
| Q24-02 | M0 | P1 | M | Lead/QA | Q24-01 | Conferir contratos e decisões existentes |
| Q24-03 | M1 | P0 | M | Backend/segurança | Q24-02 | Nenhuma adicional |
| Q24-04 | M1 | P0 | P | Frontend | Q24-02 | Nenhuma adicional |
| Q24-05 | M1 | P0 | M | Backend/frontend | Q24-03, Q24-04 | D01 para retenção/origem |
| Q24-06 | M1 | P1 | M | RAG/QA | Q24-02 | D04 para contrato de avaliação |
| Q24-07 | M1 | P1 | G | Dados/Lead | Q24-02 | D02 para inventário externo |
| Q24-08 | M1 | P1 | M | Backend/observabilidade | Q24-02 | Nenhuma adicional |
| Q24-09 | M1 | P1 | M | QA/CI | Q24-03, Q24-04, Q24-05, Q24-06, Q24-07, Q24-08 | Permissões da CI quando acionada |
| Q24-10 | M2 | P1 | G | Operações | Q24-03, Q24-07 | D01, D02 |
| Q24-11 | M2 | P1 | G | Dados/QA | Q24-07, Q24-10 | D01, D02 |
| Q24-12 | M2 | P1 | M | Providers/QA | Q24-10 | D03 |
| Q24-13 | M2 | P0 | G | RAG/domínio | Q24-02 | D04 |
| Q24-14 | M2 | P0 | M | RAG/API | Q24-13, Q24-15 | D04 |
| Q24-15 | M2 | P1 | G | Evidence/API | Q24-02, Q24-03 | D04 para semântica de fontes |
| Q24-16 | M2 | P0 | G | Integração/QA | Q24-05, Q24-11, Q24-12, Q24-14, Q24-15 | D01, D02, D03, D04 |
| Q24-17 | M3 | P1 | G | Retrieval/dados | Q24-11, Q24-16 | D02 para alteração de schema de teste |
| Q24-18 | M3 | P1 | G | Retrieval/QA | Q24-17 | D04 para comparação de qualidade |
| Q24-19 | M3 | P1 | G | Backend/dados | Q24-11 | D01, D02 |
| Q24-20 | M3 | P1 | M | Worker/backend | Q24-19 | D01, D02 |
| Q24-21 | M3 | P0 | G | Identidade/segurança | Q24-11, Q24-15, Q24-18, Q24-20, Q24-22 | D01, D02 |
| Q24-22 | M3 | P1 | G | Worker/Redis | Q24-11, Q24-16 | D01, D02 |
| Q24-23 | M3 | P1 | G | Ingestão/knowledge | Q24-17, Q24-22 | D01, D03 |
| Q24-24 | M3 | P1 | M | Observabilidade/operações | Q24-08, Q24-16, Q24-22 | D05 |
| Q24-25 | M3 | P1 | G | Frontend/design/QA | Q24-05, Q24-15, Q24-16, Q24-20, Q24-21 | D01 para cenários de interface |
| Q24-26 | M3 | P1 | G | RAG/domínio/QA | Q24-06, Q24-12, Q24-14, Q24-15, Q24-18, Q24-23 | D03, D04 |
| Q24-27 | M3 | P1 | G | CI/release | Q24-09, Q24-10 | D02; autoridade dos emissores |
| Q24-28 | M4 | P1 | G | Operações/dados | Q24-11, Q24-20, Q24-21, Q24-22, Q24-23, Q24-24 | D01, D02, D05 |
| Q24-29 | M4 | P1 | G | Performance/QA | Q24-18, Q24-24, Q24-25, Q24-26 | D03, D05 |
| Q24-30 | M4 | P1 | G | Operações/QA | Q24-28, Q24-29 | D01, D02, D05 |
| Q24-31 | M5 | P1 | M | Lead/release | Q24-25, Q24-26, Q24-27, Q24-28, Q24-29, Q24-30 | D02 para artefatos operacionais |
| Q24-32 | M5 | P1 | G | Revisão independente/QA | Q24-31 | Autoridade de revisão conforme D07 |
| Q24-33 | M5 | P1 | M | Release/autoridade humana | Q24-27, Q24-32 | D02, D07 |

## 3. Tarefas M0 — Preparação

### Q24-01 — Preservar o candidato e reconciliar Q17/Q24

**Origem:** áreas 1, 2, 25 e 26; Q17-01.A e Q17-02.A. **Superfície:** Git, documentos atuais e controles `.agent/` na futura ativação.

**Entrega:** inventário de alterações, arquivos não rastreados pertinentes e responsabilidades; vínculo de cada Q24 ao item canônico que possui o mesmo resultado. Distinguir trabalho novo, correção local já verificada e ensaio pendente.

**Aceite:** nenhum arquivo existente perdido, nenhum resultado duplicado em execução e primeira tarefa identificada. A fotografia inclui as alterações locais relevantes, não apenas o commit base.

**Prova e recuperação:** comparar status/diff/hashes, validar referências e `make validate` ao alterar controles. Preservar o inventário; nunca usar reset/clean para reconciliar o candidato.

### Q24-02 — Fixar aceitação, cobertura e responsabilidades

**Origem:** áreas 1, 2, 26; Q17-01.B, Q17-02.A e Q17-26.A. **Superfície:** contratos de qualidade existentes, mapa de requisitos e plano ativo.

**Entrega:** ligar dez achados, 26 áreas, critérios obrigatórios e tarefas; identificar responsáveis, decisões válidas e dependências externas. Manter requisitos históricos sem omissões silenciosas.

**Aceite:** cada resultado tem dono funcional, teste/procedimento e fonte do limiar. Ausência de prova não aparece como sucesso; documentos gerenciais não substituem contratos de produto.

**Prova e recuperação:** validar IDs, links e coerência dos critérios. Registrar adendo de decisão quando necessário, preservando barras e snapshots anteriores.

## 4. Tarefas M1 — Fundamentos

### Q24-03 — Atualizar dependências da API de forma compatível

**Origem:** A24-01; áreas 5, 25; extensão de Q17-05.B e Q17-25.C. **Superfície:** `apps/api/pyproject.toml`, Dockerfiles API/worker, manifests e CI que instalem o mesmo conjunto.

**Entrega:** verificar avisos oficiais e dependências resolvidas na data da execução; selecionar versões compatíveis e corrigidas, com instalação reproduzível. Não assumir que a versão mínima citada na auditoria seja a mais recente ou resolva todos os avisos atuais.

**Aceite:** ambiente limpo e imagem usam o conjunto revisado; upload, autenticação, limites multipart e streaming mantêm seus contratos; avisos aplicáveis recebem correção ou disposição fundamentada, sem ocultar bloqueadores altos.

**Prova e recuperação:** regressões HTTP/upload, `make api16-root`, build e inventário da imagem, verificação de dependências. Reverter apenas a atualização própria em ambiente de desenvolvimento; não reexpor versão afetada em produção como solução.

**Checkpoint local 25/09:** FastAPI permanece em 0.141.1; Starlette e Uvicorn foram atualizados para 1.7.0 e 0.54.0 após conferir os releases e a faixa declarada pelo FastAPI. `apps/api/pyproject.toml`/`uv.lock`, `requirements/runtime.in`/`runtime.lock` e os cinco workflows que instalam o conjunto diretamente estão alinhados, incluindo `python-multipart==0.0.32` no phase-1.5. Um ambiente Python 3.12 limpo resolveu os 45 pacotes; `pip check`, `uv lock --check`, os audits PyPI/OSV e `make api16-root` (749 testes) passaram. O TestClient ainda emite um aviso de depreciação do uso de HTTPX; ele não falhou no conjunto e fica disposto como migração de dependência de teste. A compilação e auditoria da imagem continuam pendentes de referência/base aprovadas por D02; Q24-03 permanece parcial. Consulte o [manifesto de verificação](reports/evidence/implementation-q24-2026-09-24/verification-q24-03-runtime-deps-q24-26-strata-identity-20260925T1938Z/manifest.json).

### Q24-04 — Unificar a coleção exibida e enviada no upload

**Origem:** A24-03; área 16; parte restante de Q17-16.A. **Superfície:** `apps/web/app/app/documents/page.tsx`, `apps/web/lib/api.ts` e `apps/web/tests/document-state.spec.ts`.

**Entrega:** uma coleção efetiva compartilhada entre seletor, validação e FormData; comportamento definido para nenhuma coleção disponível, coleção arquivada ou alteração da lista durante o uso.

**Aceite:** primeiro upload sem interação no seletor envia a coleção exibida; seleção alternativa é respeitada; destino vazio ou sem autorização não é enviado como sucesso.

**Prova e recuperação:** reproduzir o teste vermelho existente; conferir campo multipart sem confundir delimitadores com conteúdo; adicionar casos de mudança/ausência de coleção e repetir lint/typecheck web. Reverter somente o patch de interface, preservando testes discriminantes.

### Q24-05 — Preservar fontes binárias no retry

**Origem:** A24-03; áreas 6, 8, 16, 22; Q17-06.A e Q17-16.A. **Superfície:** rota de retry em `apps/api/src/routes/knowledge.py`, serviço de ingestão, storage e cliente/página de documentos.

**Entrega:** especificar e implementar retry por referência durável autorizada ou multipart íntegro; versionar compatibilidade com o contrato JSON textual existente. Remover conversão binária por `file.text()` no caminho PDF/DOCX.

**Aceite:** checksum, tamanho e nome/origem válidos são preservados; retry respeita tenant, coleção, idempotência e retenção; fonte ausente/expirada ou acesso indevido produz erro explícito; reload permite retomada quando a referência existir.

**Prova e recuperação:** PDF, DOCX, texto, conteúdo vazio, alteração de bytes, repetição da mesma intenção e falha da fonte. Validar API e browser. Preservar a versão anterior durante migração de contrato e não apagar fontes até confirmação de retenção/aceite.

### Q24-06 — Corrigir o contrato impossível do pacote de avaliação RAG

**Origem:** A24-04; área 14; continuação de Q17-14.A. **Superfície:** `docs/evaluation/packs/rec22-local-v1`, `scripts/state_of_art/evaluate_pack.py`, seus testes e documentação de avaliação.

**Entrega:** manter a versão antiga e sua falha; produzir versão sucessora com métrica, k e limites coerentes. Uma alternativa a julgar é medir cobertura com Recall@2 no caso de dois relevantes e ordem com métrica própria, sem reduzir o conjunto de referência para fabricar sucesso.

**Aceite:** demonstrar matematicamente a viabilidade de cada meta por grupo, tratar métricas ausentes como desconhecidas e manter exemplos ruins reprovados. Mudança de versão/target padrão deve ser explícita e justificada.

**Prova e recuperação:** valores calculados manualmente, caso perfeito, omissão de fonte, rank inadequado, grupos divergentes e dados inválidos; `make eval-retrieval-pack` após atualização acordada do apontamento. Reverter o apontamento se o novo contrato estiver incorreto, preservando ambos os resultados.

**Checkpoint local 25/09:** o pack sintético v2 passou 22 testes e mantém 2 casos positivos e 3 negativos estruturais. Um wrapper de campanha agora vincula configuração/candidato, estratos, partição e intervalo de incerteza; seu resultado continua explicitamente `campaign_status=NOT_RUN`, sem corpus autorizado nem provider. Evidência em [manifesto Q24-06](reports/evidence/implementation-q24-2026-09-24/verification-q24-06-evaluation-20260925/manifest.json) e [manifesto do harness de campanha](reports/evidence/implementation-q24-2026-09-24/verification-q24-26-campaign-harness-20260925/manifest.json). Q24-06 tem prova local do contrato, não uma avaliação representativa.

### Q24-07 — Definir atualização de banco sem reescrever histórico

**Origem:** A24-07; área 19; Q17-19.A. **Superfície:** `infrastructure/migrations/0005_rewrite_legacy_jobs.sql`, runner, testes e inventário autorizado de instalações.

**Entrega:** distinguir banco vazio, legado anterior à 0005 e banco com a 0005 já registrada; inventariar os checksums realmente existentes. Escolher procedimento compatível por estado, incluindo reparo pré-aplicação quando necessário. Uma migration adicional não resolve sozinha um runner que falha antes de alcançá-la.

**Aceite:** estratégia documentada, validadores locais e testes de decisão do runner cobrem os três estados; nenhum checksum aplicado é falsificado. Prova em PostgreSQL real fica explicitamente em Q24-11, não presumida aqui.

**Prova e recuperação:** fixtures de histórico válido, divergente, incompleto e desconhecido; `make ops-static` apenas como check estático. Prever backup e roll-forward/restore por estado; manter instalações não inventariadas como desconhecidas.

### Q24-08 — Tornar explícitos e limitados os modos de telemetria

**Origem:** A24-08; área 23; parte restante de Q17-23.A. **Superfície:** `packages/observability/src/rick_observability/events.py` e seus chamadores.

**Entrega:** inventariar uso de `timeout=None`; definir contrato que evite bloquear fluxos operacionais com um sink não confiável, por remoção/restrição do modo síncrono ou entrega limitada. Preservar fila finita, pool fixo e contadores existentes.

**Aceite:** sink bloqueado não bloqueia indefinidamente o caminho operacional; saturação e shutdown possuem resultado observável; falha de entrega não é reportada como confirmação.

**Prova e recuperação:** sink lento, falho e permanentemente bloqueado, saturação, esvaziamento e shutdown; medir número de threads/fila e latência do chamador. Usar comportamento anterior apenas onde o contrato revisado permitir; não criar thread por evento.

**Checkpoint local 25/09:** corrigidos os dois caminhos observados: o pacote principal e o fallback standalone agora usam dois workers fixos e fila finita de 1.024 eventos; `timeout=None` permanece limitado a 250 ms; lookup de `emit` ocorre no worker; falha de callback não retorna sucesso. O snapshot JSON e a exportação Prometheus da API incluem fila, workers e contadores de resultados. Passaram 17 testes do pacote, 13 focados da telemetria/fallback da API, a suíte API (748) e worker (116), além de `make lint` e `make typecheck`. Estes números são evidências sobrepostas, não uma soma. O desligamento é um helper process-level explícito ainda não integrado ao lifespan; métricas não provam carga representativa, exporter externo ou composição distribuída. Consulte `docs/architecture/observability-sink-delivery.md` e o manifesto em `reports/evidence/implementation-q24-2026-09-24/verification-q24-08-sink-delivery-20260925/manifest.json`. Q17-23.A continua `VERIFY`.

### Q24-09 — Integrar regressões e tipagem reais ao fluxo local/CI

**Origem:** áreas 6, 25, 26; Q17-06.B e Q17-26.A/B. **Superfície:** Makefile, scripts de validação, testes e workflows em `.github/workflows/`.

**Entrega:** executar suites canônicas de API, domínio, worker e web; avaliar/adotar análise estática Python incremental adequada ao repositório, distinguindo-a de `compileall`. Conferir asserções tautológicas e fixtures que não exercitam o resultado esperado.

**Aceite:** instalação limpa executa os checks definidos; um defeito representativo de contrato/tipo/segurança faz o check correspondente falhar. Não exigir número arbitrário de testes nem esconder erros por exclusões indiscriminadas.

**Prova e recuperação:** checks locais listados na seção 10, regressões e execução de CI quando autorizada. Reverter configuração defeituosa de ferramenta, mantendo os checks existentes; registrar a cobertura incremental e suas exclusões justificadas.

## 5. Tarefas M2 — Primeiro fluxo real

### Q24-10 — Construir laboratório isolado e observar readiness

**Origem:** A24-09/A24-10; áreas 18, 20, 21; Q17-18.A/B, Q17-20.A e Q17-21.A. **Superfície:** Compose dev/staging, Dockerfiles, entrypoints e scripts de inicialização.

**Entrega:** projeto separado, portas/volumes próprios, secrets de teste e serviços reais necessários; verificar configuração API/worker, TLS aplicável, readiness e término ordenado. Aproveitar as correções já existentes.

**Aceite:** migração/bootstrap, API, web, workers, PostgreSQL, Redis, Qdrant, object storage e telemetria são identificados e observados; perda de processo/dependência não permanece falsamente pronta.

**Prova e recuperação:** `make compose-static`, ciclo de inicialização inspecionado e healthchecks do processo real, logs e digests. Teardown alcança somente recursos comprovadamente pertencentes ao laboratório; não usar serviços do usuário como descartáveis.

### Q24-11 — Provar instalação, upgrade e bootstrap persistente

**Origem:** A24-07/A24-10; áreas 7, 19, 22; Q17-07.B, Q17-19.A/B e Q17-22.B. **Superfície:** migrations, runner, stores e inicialização no laboratório.

**Entrega:** executar os caminhos de Q24-07 em PostgreSQL real; testar transações, falha parcial, repetição e bootstrap convergente. Verificar objetos, políticas e identidades criados sem duplicação nem mudança silenciosa de privilégios.

**Aceite:** bancos vazio, legado e já migrado chegam ao estado suportado com dados íntegros; divergência não autorizada interrompe a operação; reinício não deixa migração parcialmente registrada.

**Prova e recuperação:** `make phase3-postgres-runtime`, casos reais adicionais de upgrade e bootstrap, inspeção de históricos e dados. Testar restore/roll-forward de falha no próprio laboratório; nunca atualizar histórico para simular sucesso.

### Q24-12 — Validar provider real e orçamento de chamadas

**Origem:** área 13 e A24-10; Q17-13.A/B. **Superfície:** `packages/providers`, composição externa e gates de provider.

**Entrega:** testar endpoint/modelo autorizado, local ou remoto, com chat, embeddings, dimensões, streaming, ferramentas e JSON quando contratados. Limitar custo, tamanho, timeout, retries e cancelamento.

**Aceite:** capacidades declaradas são observadas; erro 429/500, stream interrompido e dimensão incompatível não viram resposta válida; retry após emissão não duplica saída nem efeitos.

**Prova e recuperação:** `make api15-provider`, `make api15-contracts` e `make phase3-provider-runtime`, com modelo/configuração e consumo registrados. Desativar o endpoint de teste e preservar resultado parcial ao atingir limite; não tentar indefinidamente nem trocar provider sem registro.

### Q24-13 — Especificar e implementar classificação de risco/intenção

**Origem:** A24-02; área 11; Q17-11.A. **Superfície:** `packages/decision`, adaptador Professor e política versionada de domínio.

**Entrega:** separar qualidade da evidência de risco da solicitação e clareza da intenção. Definir regras e exemplos revisáveis para consultas informativas, ambíguas, de risco e fora de escopo; persistir versão/motivo da decisão.

**Aceite:** fontes boas não transformam automaticamente risco desconhecido em baixo; consultas permitidas possuem classificação alcançável; desconhecidos continuam tratados conservadoramente. O implementador não atribui sozinho aceite clínico às regras.

**Prova e recuperação:** testes determinísticos positivos/negativos e revisão de domínio dos casos aplicáveis. Manter fallback conservador quando política/configuração não estiver disponível e registrar suas limitações funcionais.

### Q24-14 — Conectar as ações de decisão ao caminho da API

**Origem:** A24-02; áreas 11, 12, 15; Q17-11.B e Q17-12.B. **Superfície:** `apps/api/src/services/professor_backend.py`, contratos, Professor e exposição na API/UI.

**Entrega:** ligar ANSWER, RETRIEVE_AGAIN, ASK_FOR_CLARIFICATION, ABSTAIN e ESCALATE conforme contrato existente; preservar motivo, tentativa e resultado. Nova recuperação deve ter orçamento e alteração de estratégia definida.

**Aceite:** cada ação tem caso atingível e testado; consulta permitida chega ao provider; consulta bloqueada não o chama indevidamente; nada colapsa em escalação universal ou resposta sem evidência.

**Prova e recuperação:** matriz de decisão/API, testes do gate e `make api15-professor`/`make api16-root`. Reverter adaptador junto com seu contrato quando necessário, preservando negações e identificando claramente modo degradado.

### Q24-15 — Completar fontes, publicação final e equivalência do chat

**Origem:** áreas 6, 10, 12, 15; Q17-06.B, Q17-10.A/B, Q17-12.A/B e Q17-15.A. **Superfície:** pacotes contracts/evidence/professor e serviços Professor/chat.

**Entrega:** preservar rejeição de respostas sem citações; revalidar chunk, checksum, versão e autorização imediatamente antes de publicar. Explicitar tratamento de múltiplas coleções e diferenciar validade estrutural de suporte semântico.

**Aceite:** revogação/exclusão durante geração impede aprovação inadequada; metadados/fontes equivalem entre JSON, SSE, replay e histórico; conteúdo provisório não assume aprovação final. Cancelamento e orçamento não publicam conclusão truncada como completa.

**Prova e recuperação:** testes com alteração concorrente de fonte/escopo, citações inexistentes e stream cancelado; regressões Professor/contratos/API. Versionar respostas com compatibilidade e preservar histórico válido; não retroagir rótulos sem contrato.

### Q24-16 — Demonstrar o fluxo inicial completo

**Origem:** A24-10; áreas 8, 11–13, 15–16, 18–22; Q17-08.C e Q17-18.B. **Superfície:** browser → API → fila → worker → storage/índice → provider → histórico.

**Entrega:** criar e executar cenário rastreável com documento sintético autorizado, usando serviços reais e o caminho canônico. O retrieval dense pode compor esta primeira demonstração, declarado como limite.

**Aceite:** fonte e coleção corretas, job efetivamente processado, pontos indexados, resposta permitida com citação verificável e histórico consistente. Sem evidência ou autorização, o sistema apresenta a ação adequada.

**Prova e recuperação:** `make phase3-golden-runtime`/`make phase3-provider-rag-runtime` com harness concreto e observação do navegador; nada de interceptação substituindo a operação principal. Ao falhar, registrar o primeiro limite quebrado e retomar sem reenviar efeitos não idempotentes.

## 6. Tarefas M3 — Completude

### Q24-17 — Disponibilizar schema e indexação sparse no caminho HTTP

**Origem:** A24-05; áreas 8, 9, 19; Q17-08.B e Q17-09.A. **Superfície:** adapter Qdrant HTTP, payloads, pipeline de ingestão e composição externa.

**Entrega:** especificar representações dense/sparse compatíveis, versionamento de índice e transição de coleções existentes; implementar upserts respeitando limites por quantidade e bytes.

**Aceite:** novas fontes possuem as representações necessárias; índice anterior continua utilizável até transição válida; schema incompatível é detectado antes de publicação; escopo faz parte dos pontos e consultas.

**Prova e recuperação:** inspeção de schema/pontos em Qdrant real, indexação maior que um lote e falha parcial. Usar índice/alias versionado quando adequado e ensaiar retorno ao índice anterior; não apagar a única cópia publicada.

### Q24-18 — Conectar busca híbrida HTTP e fallback explícito

**Origem:** A24-05; área 9; Q17-09.A/B. **Superfície:** `packages/retrieval/src/rick_retrieval/backends.py`, adapter HTTP e serviço de retrieval.

**Entrega:** executar dense e sparse no caminho composto, filtrar escopos antes da fusão, deduplicar e aplicar reranking conforme contrato; definir comportamento quando uma modalidade ou backend falhar.

**Aceite:** ambas as modalidades aparecem em observações reais; nenhuma resposta fora de tenant/workspace/coleção chega à fusão; degradação é sinalizada e não rotulada silenciosamente como busca híbrida completa.

**Prova e recuperação:** consultas sensíveis a termos exatos e semântica, filtros negativos e comparação por ablação de qualidade/latência; `make phase3-object-qdrant-runtime` com casos adicionais. Flag compatível permite voltar ao caminho dense declarado, mantendo o achado aberto até aceite híbrido.

### Q24-19 — Garantir consistência entre mutação e auditoria

**Origem:** A24-06; áreas 17, 19; Q17-17.A. **Superfície:** rotas administrativas, identidade, stores de auditoria e schema necessário.

**Entrega:** definir e implementar transação/outbox ou protocolo durável equivalente. A intenção e o resultado da mutação não podem depender exclusivamente do sink final que já falhou; distinguir falha antes da mutação de resultado aplicado com conclusão pendente.

**Aceite:** create/update/deactivate/reset têm estado reconstruível após crash em cada fronteira; autorização e isolamento são preservados; nem indisponibilidade do sink nem retry provocam perda silenciosa do resultado.

**Prova e recuperação:** testes dos pontos de falha e restart em PostgreSQL, incluindo falha da tentativa de registrar pendência. Evoluir schema de forma compatível; reconciliar registros existentes sem inventar eventos concluídos.

**Checkpoint 25/09:** rotas PostgreSQL usam transação/outbox atômica. O teste de falha do outbox confirma rollback real nas quatro mutações; a rota legado diferencia revisão manual e o runtime `production_safe` rejeita providers sem atomicidade. A mutação segue aberta até crítica independente final e aceitação dos demais fluxos de identidade/tenant.

### Q24-20 — Consumir e reconciliar pendências administrativas

**Origem:** A24-06; áreas 17, 20, 23; complemento de Q17-17.A. **Superfície:** worker, outbox/audit stores, métricas e consultas administrativas.

**Entrega:** consumidor com posse/lease ou mecanismo transacional, retries limitados e conclusão idempotente. Definir tratamento de pendências irrecuperáveis e retenção dos registros não reconciliados.

**Aceite:** dois consumidores não duplicam a conclusão; reinício retoma pendências; falha persistente é visível e não cresce sem política de controle; interface/API informam corretamente resultado pendente.

**Prova e recuperação:** sink offline/recuperado, concorrência, crash entre envio e confirmação e expiração de lease. Pausar consumidor preserva pendências; reprocessamento opera por identificador estável sem repetir a mutação de negócio.

**Checkpoint 25/09:** worker separado implementa `SKIP LOCKED`, projeção idempotente, backoff limitado, dead-letter e retry manual limitado. PostgreSQL real confirma dois consumidores concorrentes e a recuperação depois de interromper o `DeploymentRuntime` e iniciar um processo novo; a crítica independente final e a prova operacional no ambiente completo continuam pendentes.

### Q24-21 — Validar sessões, permissões e isolamento completo

**Origem:** áreas 3–5, 10, 17; Q17-03.A/B, Q17-04.A/B e Q17-05.A/B. **Superfície:** identity/authorization, auth, API, retrieval, caches, histórico, casos e audit.

**Entrega:** alinhar TTL/cookies/revogação; explicitar ausência, lista vazia e wildcard de concessões; avaliar migração de hashes/credenciais apenas quando necessária e compatível. Completar matriz por papéis e escopos nos stores reais.

**Aceite:** sessão expirada/desativada ou papel revogado perde acesso; isolamento inclui IDs, metadados e resultados de erro; endpoint protegido não é considerado seguro apenas por retornar 422. Produção mantém política de CSRF/CORS/proxy/TLS definida.

**Prova e recuperação:** relógio controlado, login antigo compatível, autenticação, negativos com corpos válidos e `make phase3-tenant-evidence-runtime`. Migração de permissões exige estratégia de reversão e invalidação de snapshots; nunca ampliar concessões para corrigir falha de teste.

**Checkpoint local 25/09:** a regressão PostgreSQL para PATCH administrativo esparso versus recuperação de senha passou 4 casos nas duas ordens de lock; API/identity passou 773 testes e lint/typecheck passaram. Essa fatia não fecha sessão expirada/revogação, matriz completa de papéis/tenants, isolamento distribuído nem a tarefa Q24-21. Consulte o [manifesto da regressão](reports/evidence/implementation-q24-2026-09-24/verification-q24-21-tenant-race-20260925/manifest.json).

### Q24-22 — Provar concorrência, fencing e retomada de workers/Redis

**Origem:** A24-10; áreas 19–21; Q17-19.B, Q17-20.A/B e Q17-21.A/B. **Superfície:** runtime de worker efetivamente composto, fila PostgreSQL, Redis/leases e healthchecks.

**Entrega:** testar dois workers e réplicas da API, posse de jobs, cancelamento, heartbeat, rate limit compartilhado, desligamento e retomada. Verificar garantias do runtime usado pela implantação, não apenas de uma classe alternativa.

**Aceite:** proprietário expirado não confirma/publica; duplicatas não duplicam efeito; processo morto não mantém readiness; shutdown e cancelamento têm limites e estados coerentes. Preservar matrizes obrigatórias de crash do projeto.

**Prova e recuperação:** gates de PostgreSQL/multi-worker/Redis/multi-réplica, sinais e falhas controladas com invariantes de publicação. Recuperar por lease/replay definido, sem apagar fila ou forçar ACK de trabalho desconhecido.

### Q24-23 — Completar integridade, reindexação e contratos dos stores

**Origem:** áreas 7, 8, 19, 22; Q17-07.A/B, Q17-08.A/B/C e Q17-22.A/B. **Superfície:** knowledge, ingestion, storage, worker externo e Qdrant.

**Entrega:** verificar checksum de origem antes de parsing, publicação e exclusão terminal entre memória/SQLite/PostgreSQL; reindexar conteúdo igual com novo modelo/versão sem deduplicação indevida. Preservar batching e validar parsing isolado e fontes hostis no laboratório.

**Aceite:** tombstone não ressuscita por adapter alternativo; divergência de origem falha antes do processamento; versão antiga permanece até substituição válida; falha de lote/crash é recuperável sem publicação parcial. Cobrir limites de tamanho e dimensão reais do modelo escolhido.

**Prova e recuperação:** contratos compartilhados de stores, `make api16-domain`, ensaios de storage/Qdrant e `make phase3-file-security-runtime`; matriz de falhas de ingestão existente. Recuperar por versão/objeto e compensações verificadas, sem remover a fonte única.

### Q24-24 — Observar o fluxo e testar alertas operacionais

**Origem:** A24-08/A24-10; área 23; Q17-23.B. **Superfície:** OTel, exportação, Prometheus/regras, métricas API/worker e runbooks.

**Entrega:** correlacionar API, job, worker, retrieval e provider; medir fila, falhas, descartes, retries e pendências administrativas; configurar alertas com destino de teste e limiares acordados.

**Aceite:** falha injetada chega ao coletor e produz alerta verificável; recuperação é observada; credenciais/conteúdo sensível não aparecem nos logs; labels não têm cardinalidade descontrolada por usuário/documento.

**Prova e recuperação:** `make phase3-observability-runtime`, inspeção de traces e alerta recebido, coletor indisponível e retomada. Restaurar configurações anteriores sem alterar resultados históricos e sem tornar o estado de negócio dependente da telemetria.

### Q24-25 — Completar UX de documentos, chat e administração

**Origem:** áreas 15–17, 26; Q17-15.B, Q17-16.B, Q17-17.B/C e Q17-26.C. **Superfície:** páginas/components web, API de casos/jobs/histórico e contratos de paginação/idempotência.

**Entrega:** polling com backoff/retomada, atualização de catálogo após retry, paginação, descarte de respostas obsoletas e preservação de formulário/scroll. Chave de idempotência permanece estável por intenção; payload divergente com mesma chave recebe conflito explícito.

**Aceite:** sucesso/erro/vazio/carregamento/sem permissão/pendência são distinguíveis; reload e timeout não indicam publicação fictícia; teclado, foco, leitor de tela e viewports 375/768/1440 seguem os critérios visuais vigentes.

**Prova e recuperação:** `make web-lint`, `make web-typecheck`, `make web-build`, `make web-e2e`, screenshots e inspeção de console/network com API real nos cenários de aceite. Reverter componentes mantendo contratos compatíveis e dados preservados.

**Checkpoint local 25/09:** a interface de documentos distingue falha/carregamento/ausência de coleções, pausa uploads sem destino, expõe retry também a usuários que só podem enviar e mantém o estado responsivo. A matriz anterior passou 321 testes; após os ajustes P3, build e 27 testes focados passaram. A revisão visual independente final encontrou zero achados P0–P3. API foi simulada nos testes, e chat/admin/API real continuam fora desta fatia; Q24-25 permanece parcial. Consulte o [manifesto de verificação final](reports/evidence/implementation-q24-2026-09-24/verification-q24-25-web-collection-error-review-resolved-20260925/manifest.json) e o [parecer visual](reports/review-q24-25-document-collection-error-2026-09-25.md).

### Q24-26 — Avaliar RAG em corpus representativo e autorizado

**Origem:** A24-04/A24-10; áreas 9–14; Q17-14.B. **Superfície:** packs de avaliação, harness de execução real, provider/retrieval e revisão de domínio.

**Entrega:** corpus com direitos de uso, rótulos e estratos documentados; separar calibração e conjunto reservado de avaliação. Congelar métricas/limiares antes de observar o resultado do candidato, incluindo qualidade de citações e abstenção.

**Aceite:** qualidade, fontes sem suporte, isolamento, ambiguidade e risco são avaliados por grupo; modelo/corpus/configuração identificados; incerteza e tamanho da amostra reportados. Cinco fixtures sintéticos não encerram esta tarefa.

**Prova e recuperação:** avaliação real repetível, referência humana qualificada nos casos exigidos e comparação com baseline/ablação. Preservar conjuntos e resultados; não usar o conjunto reservado para ajustar o sistema e depois anunciar avaliação independente.

**Checkpoint local 25/09:** o harness v4 exige dimensões `risk` e `ambiguity` para prontidão de produto, sem inventar categorias ou limiares D04. As linhas e intervalos separam pares positivos modelo/corpus e tipos de expectativa negativos dentro dos rótulos. Identidades mantêm qualquer string não vazia exatamente, inclusive espaços-only, e casos sem `model_id`/`corpus_id` herdam os defaults do manifesto do pack. Componentes são percent-encoded e o JSON canônico dos rótulos é codificado sem perda em base64 URL-safe. Regressões cobrem pares com `/`, IDs `ranker`/` ranker ` e ` ` distintos, defaults, igualdade dos IDs entre estratos/métricas/intervalos e decodificação integral. Um caso sintético confirma p95 de 11 ms e 15 ms em linhas distintas. Os cinco casos do manifesto continuam sintéticos e sem rótulos; a campanha permanece `NOT_RUN` e a elegibilidade `BLOCKED`. Passaram 20 testes do harness e 15 do pack. Revisões independentes válidas corrigiram colisões, normalização/hash truncado e, depois, fallback de IDs, strings de espaços-only e descrição da incerteza `overall`; a nova revisão do snapshot corrigido permanece pendente. Q24-26 segue parcial até corpus autorizado/representativo, provider, revisão de domínio, limiares D04, split e execução real repetível. Consulte o [manifesto de verificação](reports/evidence/implementation-q24-2026-09-24/verification-q24-03-runtime-deps-q24-26-strata-identity-20260925T1938Z/manifest.json) e os [resultados históricos do harness](reports/evidence/implementation-q24-2026-09-24/verification-q24-26-strata-harness-20260925T1851Z/manifest.json).

### Q24-27 — Conectar evidências reais aos verificadores de release

**Origem:** A24-09; áreas 2, 25, 26; Q17-25.A/B e Q17-26.B. **Superfície:** `scripts/state_of_art/triple_aaa_verify.py`, adapters de evidência e workflows.

**Entrega:** produtores/consumidores para lab-readiness, independent-reviews e production-runtime, com identidades e contratos válidos. Ordenar geração, consumo e verificação sem dependência circular de pacote/selo; mensagens descrevem o bloqueio observado.

**Aceite:** um conjunto tecnicamente completo e autorizado pode avançar; artefato ausente, antigo, alterado, de outro candidato ou autoaprovado é rejeitado. Testes do mecanismo não são observações de runtime/review reais.

**Prova e recuperação:** casos bons/ruins do verificador, CI local e execução remota pertinente. O consumo final das campanhas fica em Q24-33; não atribuir PASS à operação só porque o parser de evidência funciona. Reverter adapter defeituoso mantendo falha conservadora.

## 7. Tarefas M4 — Operação

### Q24-28 — Restaurar o conjunto e medir RPO/RTO

**Origem:** A24-10; área 24; Q17-24.A. **Superfície:** backup/restore, PostgreSQL, objetos, índices, identidades, jobs e auditoria no laboratório.

**Entrega:** testar seed → backup → perda simulada em cópia isolada → restore/rebuild → reconciliação; medir perda efetiva de dados e tempo de recuperação conforme D05.

**Aceite:** documentos, fontes/citações, histórico, permissões e pendências continuam coerentes; objetivos aprovados de RPO/RTO atendidos; backup incompleto/corrompido é detectado. Comando com exit zero não substitui conferência de dados restaurados.

**Prova e recuperação:** `make phase3-restore-runtime` com harness concreto, contagens, digests e consultas após restore. Manter backup verificado separado; perda simulada nunca alcança origem ou recursos não comprovadamente descartáveis.

### Q24-29 — Medir capacidade, latência e custo

**Origem:** A24-10; áreas 13, 23, 24; Q17-24.B. **Superfície:** workloads reais, provider, API, worker, busca, web e métricas.

**Entrega:** medir p50/p95, primeiro token, conclusão, throughput, espera em fila, memória, VRAM quando aplicável e consumo. Definir hardware, concorrências, documentos/contextos e limites antes da campanha.

**Aceite:** cargas exigidas pelos contratos existentes atendem os budgets aprovados; gargalo e limite de admissão conhecidos; saturação tem controle explícito. Não presumir que máquinas de outras finalidades estejam disponíveis nem substituir cenários obrigatórios por uma carga menor sem decisão.

**Prova e recuperação:** `make phase3-performance` com harness implementado, séries e amostras suficientes. Interromper no limite; recuperar o ambiente e revalidar saúde sem reutilizar medições contaminadas por outra campanha.

### Q24-30 — Executar caos e estabilidade prolongada

**Origem:** A24-10; área 24; Q17-24.C. **Superfície:** laboratório instrumentado e matriz de faults/invariantes vigente.

**Entrega:** falhas de dependências/rede/processos, reinícios e saturação seguidos de janela de estabilidade definida em D05. Preservar a abrangência das matrizes históricas exigidas, registrando casos não executados.

**Aceite:** ausência de corrupção e efeitos duplicados, memória/filas limitadas, detecção/recuperação observadas e objetivos de estabilidade atendidos. Um ensaio curto não substitui uma janela maior requerida.

**Prova e recuperação:** `make phase3-chaos` e `make phase3-soak` com comandos/harness reais e resultados por fault/invariante. Definir parada de emergência e restauração pelo procedimento já testado; manter falhas como evidência para reabrir tarefas causais.

## 8. Tarefas M5 — Candidato e encerramento

### Q24-31 — Preparar documentação, inventário e artefatos do candidato

**Origem:** áreas 1, 2, 25; Q17-01.C, Q17-02.B/C e Q17-25.C. **Superfície:** docs correntes, runbooks, manifests/locks, imagens, CI e inventário de release.

**Entrega:** atualizar navegação e estado vigente por adendos; instruções de instalação, operação, falhas e rollback; inventário de componentes, licenças, dependências, secrets e imagens com digests. Preparar candidato revisável que inclua o trabalho aprovado.

**Aceite:** walkthrough operacional é reproduzível; arquivos e imagens correspondem ao candidato; achados de supply chain têm disposição verificável; histórico é preservado e nenhum commit/push é presumido por esta tarefa de preparação.

**Prova e recuperação:** links/IDs, build/inventário e ensaios de runbook no laboratório. Mudança posterior relevante exige reconstrução dos artefatos afetados; preservar candidato anterior e suas evidências.

### Q24-32 — Revisar de forma independente e reauditar as 26 áreas

**Origem:** áreas 1–26; Q17-26.D e Q17-25.D. **Superfície:** candidato completo, código conectado e evidências de todas as campanhas.

**Entrega:** revisão com contexto fresco e responsável distinto do implementador quando exigido; reproduzir achados prioritários, verificar todos os critérios obrigatórios e recalcular as notas com justificativa e limites.

**Aceite:** zero achados críticos/altos impeditivos e nenhum requisito obrigatório omitido; relatório diferencia observado, parcial e desconhecido. Nota real calculada após revisão; indisponibilidade de revisor não é autoaprovação.

**Prova e recuperação:** CI do candidato, regressões relevantes, pareceres e matriz de critérios. Achado novo reabre sua tarefa; após correção, repetir revisão e ensaios impactados antes de avançar.

### Q24-33 — Validar o pacote final e obter decisão de promoção

**Origem:** A24-09/A24-10; área 25; Q17-25.D. **Superfície:** manifesto de release, verificadores, selo e autoridade definida.

**Entrega:** consumir evidências reais do candidato revisado e das campanhas; obter assinatura/decisão válidas quando requeridas; apresentar resultado e riscos. Eventual implantação depende de destino, canário/rollback e autorização operacional específicos.

**Aceite:** `make triple-aaa-verify` e critérios vigentes aprovam o conjunto correto; missing/stale/tampered/wrong-candidate e autoaprovação continuam reprovados. A autoridade é externa ao próprio implementador quando o contrato exigir.

**Prova e recuperação:** pacote íntegro e verificável, resultado dos gates e decisão registrada. Falta de autoridade mantém a promoção pendente, preservando o candidato completo; falha de rollout segue o procedimento ensaiado, sem alteração retroativa dos testes.

## 9. Rastreabilidade e fechamento dos achados

### Dez achados de 24/09

| Achado | Tarefas responsáveis | Evidência que encerra a pendência |
|---|---|---|
| A24-01 — Dependências | Q24-03, Q24-09, Q24-31 | Dependências/imagem verificadas e regressões HTTP aprovadas. |
| A24-02 — Escalação universal | Q24-13, Q24-14, Q24-15, Q24-16, Q24-26 | Decisões positivas/negativas e resposta permitida demonstradas no caminho real. |
| A24-03 — Upload/retry | Q24-04, Q24-05, Q24-16, Q24-25 | Destino efetivo, integridade binária e retomada comprovados pela API/browser. |
| A24-04 — Avaliação inviável | Q24-06, Q24-26 | Contrato viável versionado, testes discriminantes e campanha representativa. |
| A24-05 — Híbrido HTTP ausente | Q24-17, Q24-18, Q24-23, Q24-26 | Schema/indexação/consulta com ambas as modalidades e escopo verificado. |
| A24-06 — Auditoria pendente | Q24-19, Q24-20, Q24-21, Q24-28 | Consistência, restart, consumidor e recuperação sem repetição da mutação. |
| A24-07 — Upgrade/checksum | Q24-07, Q24-11, Q24-28 | Estratégia por estado e upgrade/restore executados sem falsificar histórico. |
| A24-08 — Telemetria síncrona | Q24-08, Q24-24, Q24-30 | Limites em chamadores operacionais, coletor/alerta e falha prolongada verificados. |
| A24-09 — Promoção desconectada | Q24-09, Q24-10, Q24-27, Q24-31, Q24-32, Q24-33 | Produtores/consumidores conectados e pacote final verdadeiro do candidato. |
| A24-10 — Prova operacional ausente | Q24-10–Q24-12, Q24-16, Q24-21–Q24-30, Q24-32, Q24-33 | Integração, segurança, qualidade, restore, carga e estabilidade com evidências atuais. |

### Cobertura das 26 áreas da auditoria

| Área | Nome | Tarefas Q24 | Continuidade Q17 |
|---|---|---|---|
| 1 | Arquitetura e fronteiras | Q24-01, Q24-02, Q24-31, Q24-32 | Q17-01 |
| 2 | Documentação | Q24-01, Q24-02, Q24-27, Q24-31 | Q17-02 |
| 3 | Identidade e sessões | Q24-11, Q24-21 | Q17-03 |
| 4 | Autorização e isolamento | Q24-18, Q24-21 | Q17-04 |
| 5 | Kernel HTTP | Q24-03, Q24-09, Q24-21 | Q17-05 |
| 6 | Contratos e compatibilidade | Q24-05, Q24-09, Q24-12, Q24-15 | Q17-06 |
| 7 | Knowledge e proveniência | Q24-11, Q24-15, Q24-23 | Q17-07 |
| 8 | Ingestão e reindexação | Q24-05, Q24-16, Q24-17, Q24-23 | Q17-08 |
| 9 | Retrieval | Q24-17, Q24-18, Q24-26 | Q17-09 |
| 10 | Evidence e fontes | Q24-15, Q24-21, Q24-26 | Q17-10 |
| 11 | Decision | Q24-13, Q24-14, Q24-16, Q24-26 | Q17-11 |
| 12 | Professor | Q24-14, Q24-15, Q24-16, Q24-26 | Q17-12 |
| 13 | Providers | Q24-12, Q24-26, Q24-29 | Q17-13 |
| 14 | Avaliação RAG | Q24-06, Q24-26 | Q17-14 |
| 15 | Chat e histórico | Q24-14, Q24-15, Q24-16, Q24-25 | Q17-15 |
| 16 | Documentos na interface | Q24-04, Q24-05, Q24-16, Q24-25 | Q17-16 |
| 17 | Administração, auditoria e casos | Q24-19, Q24-20, Q24-21, Q24-25 | Q17-17 |
| 18 | Containers e composição | Q24-10, Q24-16, Q24-31 | Q17-18 |
| 19 | Jobs, PostgreSQL e migrations | Q24-07, Q24-11, Q24-19, Q24-22, Q24-23 | Q17-19 |
| 20 | Worker | Q24-10, Q24-20, Q24-22 | Q17-20 |
| 21 | Redis e coordenação | Q24-10, Q24-22 | Q17-21 |
| 22 | Storage e bootstrap | Q24-05, Q24-11, Q24-23, Q24-28 | Q17-22 |
| 23 | Observabilidade e SLO | Q24-08, Q24-20, Q24-24, Q24-29 | Q17-23 |
| 24 | Recuperação e capacidade | Q24-28, Q24-29, Q24-30 | Q17-24 |
| 25 | CI e release | Q24-03, Q24-09, Q24-27, Q24-31, Q24-32, Q24-33 | Q17-25 |
| 26 | Testes e verificação | Q24-02, Q24-09, Q24-25, Q24-26, Q24-32 | Q17-26 |

## 10. Catálogo de validação e comandos

Os targets abaixo já estão declarados no [Makefile](../Makefile). Conferir a implementação e o ambiente antes de executar. Um target existente pode depender de harness, endpoint ou artefato ainda incompleto; sua presença não implica PASS.

| Camada | Comandos/procedimentos | Limite da prova |
|---|---|---|
| Controle e estática | `make validate`, `make lint`, `make typecheck`, `make compose-static`, `make ops-static` | Não executam, por si, o produto distribuído; compilação Python não é tipagem completa. |
| Domínio/API/worker | `make api16-domain`, `make api16-worker`, `make api16-root` | Conferir mocks, stores e escopo realmente cobertos. |
| Contratos e integrações locais | `make api15-contracts`, `make api15-provider`, `make api15-lock`, `make api15-professor`, `make storage-test`, `make jobs-test`, `make ops-backup-test` | Provas locais não substituem serviços reais e restore do conjunto. |
| RAG | `make eval-retrieval-pack` e campanha versionada Q24-26 | Pack sintético valida contrato; qualidade representativa exige corpus/modelo reais. |
| Web | `make web-lint`, `make web-typecheck`, `make web-build`, `make web-e2e` | Usar API real nas campanhas de aceite e separar fixtures interceptados. |
| Banco/fila/Redis | `make phase3-postgres-runtime`, `make phase3-multi-worker-runtime`, `make phase3-redis-runtime`, `make phase3-redis-multi-replica-runtime` | Requer endpoints e recursos de teste identificados. |
| Objetos/índice/provider | `make phase3-object-qdrant-runtime`, `make phase3-provider-runtime`, `make phase3-golden-runtime`, `make phase3-provider-rag-runtime` | Registrar candidato, modelo, dimensões, dados e chamadas efetivas. |
| Segurança/telemetria/frontend | `make phase3-tenant-evidence-runtime`, `make phase3-file-security-runtime`, `make phase3-observability-runtime`, `make phase3-frontend-supply-runtime` | Artefatos atuais e comportamento do limite externo são obrigatórios. |
| Operação/release | `make phase3-restore-runtime`, `make phase3-performance`, `make phase3-chaos`, `make phase3-soak`, `make triple-aaa-verify` | Não executar destruição/carga/promoção antes de conferir escopo, limites e autoridade aplicáveis. |

Os casos adicionais de cada tarefa exigem testes específicos, ainda que não exista target dedicado. Guardar novos resultados em diretório próprio de tarefa/candidato; manter intocados os [logs da auditoria](reports/evidence/auditoria-2026-09-24/manifest.json). Não registrar tokens, senhas, chaves ou conteúdo pessoal desnecessário.

## 11. Retomada e encerramento do programa

Q24-01 e Q24-02 já foram reconciliadas com os responsáveis Q17. C11 confirmou o lookup exato de sessão, mas rejeitou o snapshot por reset PostgreSQL sem escopo workspace e por hashes fora do inventário. C12 tornou obrigatório o membership tenant/workspace do ator; sua revisão encontrou a corrida de PATCH esparso com recovery. C13 foi aceito nos 11 critérios locais após regressão PostgreSQL; a única nota foi cobertura separada de workspace-only e ordem inversa. Em 25/09, Q24-20 foi revalidado localmente: worker 116/116 e PostgreSQL descartável 1/1 cobriram projeção idempotente, consumidores concorrentes, falha/restart em novo processo, dead-letter/retry e status pending/published da API. Q17-17.A continua VERIFY para a composição externa completa e critérios administrativos restantes; nenhuma aceitação de produção ou operação é inferida. Os detalhes, limites e logs ficam no [checkpoint de implementação](reports/estado-implementacao-q24-2026-09-24.md), [parecer C13](reports/review-q24-19-20-critic-c13-2026-09-25.md) e no diretório de evidência `reports/evidence/implementation-q24-2026-09-24/verification-q24-20260925T1430Z-outbox/`. Próximo passo local: reconciliar os pré-requisitos Q17-01.B, Q17-19.B e Q17-03.B contra seus donos canônicos; os gates externos seguem abertos.

As fatias API/autorização/chat e retrieval/ingestão/migrações já receberam revisões independentes limitadas. C1–C12 rejeitaram seus snapshots exatos; C13 aceitou a correção de identidade local. A revalidação de 25/09 confirma Q24-20 localmente com 116 testes worker e uma integração PostgreSQL real para idempotência, concorrência, crash/restart, retries e estado da API. Q17-17.A ainda não equivale à aceitação do grafo completo: produção externa, identidade distribuída e critérios administrativos remanescentes ficam abertos, além dos pré-requisitos Q17-01.B/Q17-19.B/Q17-03.B em reconciliação. Q24-10/Q24-11/Q24-21 seguem sujeitos às decisões D01/D02 e evidência operacional. Ao retomar após interrupção, observar o efeito já ocorrido antes de repetir upload, migration, mutação administrativa ou publicação.

### Continuidade — prova live da fila PostgreSQL (25/09/2026)

Esclarecimento de estado canônico: Q17-19.A permanece `VERIFY`; a implementação local checksum-safe e os cenários sintéticos estão testados. O que aguarda D02 é o inventário de uma instalação realmente implantada. O dono mais amplo `PH2-P0-02-POSTGRES-ADAPTER` segue `BLOCKED` até essa evidência, os limites operacionais e uma revisão independente atual.

Q17-19.B passou localmente em PostgreSQL 16.15 descartável. A integração da `PostgresJobQueue` confirmou idempotência por escopo, claims concorrentes com `SKIP LOCKED`, recuperação de lease e fencing do worker antigo, retries/tentativas, dead-letter, replay/cancelamento, rollback antes da projeção de auditoria/outbox e retenção de jobs terminais preservando as projeções duráveis. A suíte focal passou 1/1; a suíte PostgreSQL completa passou 110/110; worker 116/116; contratos de jobs 44/44; lint e typecheck passaram. O teste revelou uma regressão de transição de estado por timestamps arredondados pelo PostgreSQL; monotonicidade e precisão de microssegundos foram corrigidas no adapter.

Evidências, imagem PostgreSQL e teardown estão em `reports/evidence/implementation-q24-2026-09-24/verification-q17-19b-live-20260925T1447Z/`; não restaram contêineres do fixture. Isso cobre a execução local do adapter e os estados sintéticos de migração. Q17-19.A permanece em VERIFY até comparar o caminho testado com um inventário autorizado de bancos implantados; o PH2-P0-02 mais amplo continua BLOCKED. Também seguem abertos runtime aprovado, Redis/distribuição, operações, domínio e promoção.

O programa termina quando todas as tarefas obrigatórias e critérios vigentes tiverem a prova correspondente, as revisões exigidas estiverem concluídas e o resultado de promoção refletir a autoridade disponível. Uma tarefa operacional bloqueada deve indicar exatamente o recurso/decisão ausente; não impede trabalho independente, mas não pode receber DONE.

**Limite deste backlog:** ele define escopo, dependências e aceite propostos. O estado real permanece no controle canônico; a inclusão de progresso neste documento não altera status, não encerra tarefa e não autoriza promoção.


Q17-20.A recebeu teste local do processo real worker-entrypoint: SIGTERM alcança o worker, pede parada, retorna exit 0 e executa cleanup no limite de 30 s (8 testes, make lint PASS). A integração de serviços externos, fencing e restart em runtime autorizado continua aberta.
