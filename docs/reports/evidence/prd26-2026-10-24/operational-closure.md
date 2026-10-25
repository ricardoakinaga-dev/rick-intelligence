# Fechamento operacional local — 2026-10-25

Continuação autorizada após `d655815108e4f93228243f3aa09b9191c7269c47`:
concluir o laboratório e preparar o pacote de produção. O usuário confirmou
que corpus e avaliador aprovados ainda não existem. Este relatório complementa
[o fechamento formal anterior](formal-runtime-closure.md) e o
[plano de execução](../../../../.agent/plans/phase3-local-closure-2026-10-25.md).

## Escopo e autoridade

Os novos harnesses usam API, identidade persistida, fila, parser em processo,
PostgreSQL, Redis, Qdrant e objetos nativos. O provider é uma fixture sintética
explícita, com embeddings de dimensão 2; isso não mede qualidade de modelo.
Os resultados são observações diagnósticas do desenvolvimento, com
`production_safe=false`. Nenhum input canônico, revisão independente, assinatura
ou decisão GO foi fabricado. A árvore contém alterações para revisão; os
envelopes antigos não atestam este candidato modificado.

## Correções verificadas

- O contexto síncrono de histórico passa a ser lido fora do event loop, com
  regressão que mantém `/health/live` disponível enquanto a leitura está presa.
- A consulta paginada do histórico tipa o parâmetro opcional de conversa como
  texto. A reabertura real no PostgreSQL deixa de falhar por inferência de tipo.
- O frontend aceita a referência de documento de quatro campos retornada pelo
  job, conserva os vínculos de tenant/workspace/coleção e continua exigindo
  título no catálogo completo. O acompanhamento deixa de ficar em “verificando”
  depois de uma publicação efetiva.
- Os pontos animados da resposta são decorativos para acessibilidade; a região
  de status adjacente já anuncia a geração. Foi removido o `aria-label` inválido
  em um `span` sem papel acessível.
- Histogramas nativos e fallback exportam p99 medido, mantendo ausência de dado
  como ausência. A métrica semântica de suporte a claims continua não avaliada.
- Uma parada fatal do daemon por indisponibilidade da fila chega ao entrypoint
  como falha, em vez de encerrar indevidamente com código zero.
- O handoff conserva o hash do inventário de fontes; a inspeção dos hashes de
  raw artifacts não sobrescreve mais esse hash com o do último artefato.

## Execuções e rastreabilidade

Os comandos reproduzíveis são `make phase3-local-performance`,
`phase3-local-soak`, `phase3-local-chaos`, `phase3-local-frontend`,
`phase3-local-observability`, `phase3-local-supply` e
`phase3-local-tenant-contention`. As saídas ignoradas ficam em
`.runtime/phase-3/{operational,chaos,frontend,observability,supply}-local/`,
com diretórios por execução, observações brutas e hashes. O pacote em
`.runtime/phase-3/local-closure/production-handoff.json` indexa os resultados,
incluindo falhas, e permanece `PREPARED_NO_GO`.

Resultados locais já verificados nesta rodada:

| Frente | Resultado e escopo |
| --- | --- |
| Golden formal | FAIL preservado: 45/47 checks PASS, `professor` BLOCKED_EXTERNAL e `stage_trace` FAIL. Faltam corpus/avaliador aprovados e a execução própria do gate após esses inputs; o trace distribuído separado não substitui esse aceite. |
| Tenant/evidence sob contenção | PASS 16/16; quatro atores, 327 respostas de carga HTTP 200, sem rejeições/erros de carga. 32 pares de timing: medianas 71,506 e 68,199 ms; diferença 3,308 ms, dentro do limite local preservado de 5 ms e razão 2. Execução `e2191dc4652046dcaf2ff62291070c44`. |
| Chaos | PASS 13/13; recuperação, integridade, publicação única, tentativas limitadas e cleanup. Execução `7f401b6535a44898`. |
| Frontend | PASS na imagem final por digest, nos três viewports; estados funcionais/erro, teclado/foco, axe, contraste, proxies de leitor de tela, movimento reduzido, reflow e zoom nativo. Execução `ad18affc894a4626`; 41 raw artifacts indexados e vínculo à imagem/SBOM/contexto. A execução source/dev `587d8b3ee66f46c4` também passou. |
| Soak local | PASS em 30/120 s solicitados; 27/79 ciclos com geração citada, recarga durável e ingestão real, zero erros/fila acumulada/retry storm/starvation/vazamento de FD. Crescimento de memória de 1,25/1,50 MB; deriva mediana de −55/957 ms, limite local 1.000 ms. Execução `17c6e56d68ac446c`. |
| Performance | PASS 20/20, 1.610 operações lógicas; cinco workloads × 1/10/50/100 atores, oito APIs e quatro workers com concorrência 1, PG próprio de 300 conexões. Zero erros e fila final zero. Chat exige `ANSWER`, citações, publicação verificada e recarga persistida. Execução `c0851422af8b4613`. |
| Observabilidade | PARTIAL: 28 spans, nove categorias e vínculo causal API/fila/worker; 17/18 grupos métricos; entrega e resolução de alertas de SLO e perda de telemetria PASS. Só `citation_support` falta ao gate canônico, que permanece FAIL. Execução `9147f487e2ac4be8`. |
| Imagens/SBOM locais | PASS: API/worker/web por digest, SBOMs CycloneDX com 90/90/59 componentes e arquivos de imagem retidos. Execução `dca0468cf1644202`. |

A primeira matriz isolada `7272056052524e66` também teve 20/20 combinações sem
erros. A repetição final acrescentou a exigência explícita de `ANSWER` com
citações, impedindo que abstinência seja contada como geração. Os resultados
anteriores de falha permanecem nos arquivos por execução; nenhum deles foi
reclassificado como sucesso.

Regressão focada: 294 testes Python e 22 subtests PASS; 36 testes de contrato
frontend PASS. `make validate`, `make compose-static`, `make typecheck` e
`git diff --check` verificados. O relatório e pacote são preparados para revisão;
as alterações não foram commitadas nem publicadas.

## Método e limites

Performance mede cinco workloads nas concorrências configuradas 1/10/50/100,
com duas operações por ator. O perfil local declara explicitamente suas
réplicas, workers, limites e provider. As latências incluem espera real e
publicação durável; HTTP 200 sem validação autoritativa não conta como sucesso.
CPU/RAM/FD/threads/processos/conexões são amostras de `/proc` do driver e seus
processos API/worker; não representam recursos reservados nem incluem os
processos Docker dos stores. O soak tem janelas locais declaradas de 30 e 120
segundos, com limites de crescimento e deriva; não substitui soak de produção.

Foi constatado que os primeiros medidores abriam uma conexão SQL por job em
espera e faziam uma consulta redundante ao catálogo em cada ciclo de worker.
Isso interferia no próprio experimento, esgotava as 100 conexões do banco dev
compartilhado e provocou paradas de workers. As falhas e seus frames foram
preservados, sem promovê-las. O observador agora consolida snapshots de fila;
os novos testes usam banco vazio próprio, migrado pelo runner canônico, com
300 conexões, 2 CPUs e 2 GiB declarados. Remoção exige o label de propriedade.
Os prefixes Redis das fixtures separam execuções sem separar as réplicas do
mesmo tenant nem remover os limitadores e leases reais.

Chaos interrompe somente containers Redis/Qdrant próprios, grupos de processos
worker próprios e proxies PG/S3 da execução. Exige falha observada, recuperação,
bytes/linhagem preservados, exatamente um sucesso durável e tentativas limitadas.
Os testes de provider exercitam o cliente tipado e seu circuit breaker;
recuperação de transporte não constitui avaliação de claims. O reset TCP usa
RST real; há regressão de socket que diferencia RST de um EOF normal.

O trace é um grafo causal conectado: fases legítimas podem ser irmãs, e a
aresta de enqueue para worker continua obrigatória. IDs duplicados, ciclos,
parents de outro trace, componentes desconectados e dados sensíveis falham.
A espera por indexação e lotes independentes é limitada pelo mesmo deadline.
As regras de produção e seus timers não foram alterados; alertas locais usam
regras adicionais de 2 segundos e notificam somente um webhook loopback.

Frontend opera o produto pelo navegador, sem `page.route`/fulfill. Após observar
upload/publicação/catálogo, aposenta apenas os uploads sintéticos da execução
pela API real. Isso mantém uma fonte inequívoca para os cenários de provider:
vetores sintéticos iguais podem corretamente bloquear a geração no Professor
antes de alcançar o provider. Cada cenário e viewport inicia nova conversa.
O zoom usa aceleradores do Chromium em Xvfb próprio, comprovando mudança de
DPR e largura CSS; reflow é medido a 320 px. Ver referências
[WCAG Reflow](https://www.w3.org/WAI/WCAG22/Understanding/reflow.html) e
[Resize Text](https://www.w3.org/WAI/WCAG22/Understanding/resize-text.html).
Essas observações e o axe não equivalem a aprovação independente ou certificação.

O modo `RICK_FRONTEND_WEB_IMAGE` exige que o digest esteja no inventário local
PASS, verifica hashes de imagem/SBOM/contexto e o usuário não-root da imagem.
O destino das rewrites do Next é embutido no build: o teste respeita `api:8000`
em uma rede Docker interna própria, com proxy de API no gateway e um forwarder
web que escuta apenas em loopback. Não depende de trocar a URL por variável no runtime,
não modifica `/etc/hosts` da estação e não recria serviços compartilhados.

Supply constrói os Dockerfiles reais a partir de contexto explícito e sem
segredos, fixa bases e imagens por manifests verificados no registry loopback
e extrai SBOM CycloneDX de arquivos das imagens com Trivy offline. Os arquivos
de imagem e dados do registry permanecem disponíveis para inspeção. Isso não
atesta scan de vulnerabilidades atualizado, proveniência ou assinatura de CI.

## Requisitos externos preservados

Continuam exigidos corpus/avaliador e critérios aprovados, workload/SLO/janelas
operacionais de produção, perfil TLS/auth e referências a secret/trust stores,
CI remoto no SHA exato, proveniência/assinaturas, revisão independente e decisão
humana de release. A avaliação local não concede essas autoridades. Após fechar
o código, é necessário regenerar as evidências no candidato limpo e revisado.
