# Continuação Phase 3 — CI público e correções de produção

25/10/2026. Baseline `a8a83ca5ce1781302ffb2a72fac9fe8de398de10`.
Esta unidade fecha defeitos técnicos demonstrados; produção continua **NO-GO**.

## Publicação autorizada e observação remota

O usuário autorizou explicitamente “Autorizar branch público e CI”. Os 44 commits
locais foram publicados no branch `phase3/a8a83ca-candidate`, sem promover main.
O [quality remoto de a8a83ca](https://github.com/ricardoakinaga-dev/rick-intelligence/actions/runs/40212544954)
terminou **FAIL**. UNIT, FRONTEND e RAG-EVAL passaram; os outros resultados não
são convertidos em PASS por este relatório. Artefatos baixados estão em
`.runtime/phase-3/unblock-a8a83ca/remote-*`; esses caminhos são locais e ignorados.

## Correções demonstradas

- Links: no export de Git com os control-inputs canônicos restaurados, o checker
  original encontrou **63 links quebrados / 1.198 links**. Após converter referências
  de artefatos ignorados em caminhos textuais e acrescentar referências aos originais,
  o mesmo checker encontrou **0 erros / 1.136 links**, sem mudar o checker ou criar
  evidência fictícia. Foram convertidas 64 referências locais (uma já resolvia).
  Os [originais](../aud15-portability-20261025/README.md) são byte a byte iguais à
  baseline, com [SHA-256 registrados](../aud15-portability-20261025/originals.json).
  As notas, falhas e decisões históricas nos relatórios ativos foram preservadas.
- Permissões: a filtragem de eventos de métricas foi separada da exigência de
  acesso à rota, preservando `observability.read` e a ocultação dos eventos globais
  sem `tenants.read`. O teste estático de permissões não foi relaxado. A suíte de
  segurança passou **182 testes**; as requisições reais em `test_health.py` cobrem
  a ocultação e a visibilidade administrativa.
- Redis: gate e fault harness encaminham CA/cert/key. A biblioteca agora fornece
  `ssl_cert_reqs="required"` ao driver asyncio 5.2.1, que não inicializava seu
  contexto com `ssl.VerifyMode`. Teste com a classe real do vendor garante
  CERT_REQUIRED e hostname checking; verificação não pode ser desativada por env
  no gate. Suite focada: **75 passed**.
- TLS real: instância própria descartável, TLS 1.3, mTLS e senha; rejeitou CA e
  hostname errados, cliente sem certificado, senha errada e plaintext. Leases,
  heartbeat, tenant namespace, limite atômico/replay, reconexão e recuperação
  após pausa passaram; cleanup passou. Observação inicial PASS: run
  `7289c1224ae7448a`, antes da adição de proveniência no probe. O rerun com proveniência `fac0aebf030a428a` também passou (source DIRTY,
  antes do commit); resultados em `.runtime/phase-3/production-inputs/tls-current.json` com HEAD,
  worktree e hashes de fontes. `production_safe=false` permanece explícito.
- Dependências: locks regenerados com hashes. OpenTelemetry API/SDK/exporter
  1.45.1; certifi 2026.10.19, Pillow 13.0.0, filelock 4.2.1 e setuptools 84.1.0;
  Next 15.5.28, Vite 7.3.7, Vitest/coverage 4.1.12. Sem exclusões de advisory.
  `pip-audit --strict` do runtime e do lock de testes: zero vulnerabilidades;
  `npm audit`: zero em todas as severidades. Isso não atesta imagens antigas.
  Fontes primárias: [OTel advisory](https://github.com/advisories/GHSA-xcq7-p3pf-p88h),
  [Next security](https://nextjs.org/blog/nextjs-security-update-october-14-2026),
  [Pillow 13](https://pillow.readthedocs.io/en/stable/releasenotes/13.0.0.html),
  [Vitest](https://github.com/vitest-dev/vitest/releases/tag/v4.1.12) e
  [Vite](https://github.com/vitejs/vite/releases/tag/v7.3.7).
- `make compose-static` e `make typecheck` passaram. O build frontend e o trace real API/worker com OpenTelemetry novo passaram.
  Testes frontend com coverage (266 passed)
  passaram: statements 87,56%, branches 80,55%, lines 91,96%.

## Como repetir a prova TLS

Com o Compose dev canônico ativo e OpenSSL disponível, executar
`make phase3-local-tls`. O alvo autoriza apenas o laboratório local. Cada run cria
CA de dois dias, credenciais sintéticas e referências em diretórios privados
0700, arquivos 0600, sob `.runtime/phase-3/production-inputs/<run>/`.
Não publica segredos nem os incorpora aos relatórios. Só pausa/remove o container
com o label de propriedade e run ID exatos. A pilha dev compartilhada não é pausada.
O teste de recusa de ownership impede fault injection em containers alheios.
As referências de CA/cert/key para os gates nativos são `RICK_REDIS_TLS_CA_FILE`,
`RICK_REDIS_TLS_CERT_FILE`, `RICK_REDIS_TLS_KEY_FILE`; os valores são caminhos,
nunca material secreto no chat ou no Git.

## Fronteiras que continuam externas

A CA local não é trust store de produção aprovado e o teste Redis não cobre TLS
PostgreSQL/S3/Qdrant/edge nem políticas de identidade implantadas. Nenhum reviewer
independente foi inventado. Corpus/avaliador representativo e critérios aprovados,
`citation_support`, perfil/stores/políticas de produção, budgets operacionais,
imagens novas imutáveis/scans/proveniência/assinaturas, revisão independente e GO
humano continuam exigidos. As lanes remotas operacionais precisam de seus inputs
reais; suas falhas não devem ser ocultadas por condicionais de workflow.
O publish-images existente não foi disparado: as políticas revisadas e um quality
aprovado no SHA exato ainda são pré-condições. CI a8a83ca não prova código novo;
a correção precisa de novo commit e de novo run remoto.

## Segundo achado de clone e restauração fiel

No [CI bde6c44](https://github.com/ricardoakinaga-dev/rick-intelligence/actions/runs/40213501168),
SECURITY, CONTRACT, UNIT, FRONTEND, RAG-EVAL e SUPPLY-CHAIN passaram. FAST
encontrou 51 arquivos históricos ausentes referenciados por ledgers/gates ativos.
O bundle complementar em [control-artifacts](../../../ci/control-artifacts/README.md)
conserva os 3.608.649 bytes originais, hashes e falhas; nenhuma referência ou
aprovação dos ledgers foi reescrita. O restorer valida destinos limitados,
inventário, tamanhos, hashes e ausência de conflitos antes de qualquer escrita.
Sete casos de regressão cobrem payload íntegro, hash falso, traversal, path
absoluto, duplicata, symlink e membro extra; todos passaram.

A suíte ampliada da API terminou em **1.882 passed, 18 skipped**, cobertura
**75,65%**. TLS também passou no candidato bde6c44 CLEAN (run
`0be802285db84ff0`, cleanup PASS). O trace real teve 46 spans/nove categorias,
API e worker distintos; a amostra de SLO registrou **breach** sob essa carga
local. Isso foi preservado e não constitui aprovação de SLO/capacidade.
O novo reparo de restauração exige outro commit/CI no mesmo branch; os resultados
de bde6c44 não são apresentados como aprovação desse novo commit.

O clone separado com histórico Git íntegro, dependências npm instaladas e
nenhum artefato `.runtime` emprestado passou em **make validate**, incluindo
restauração dos 51 originais e política de evidências sem a bolsa local. Foram
verificados **1.138 links, zero erros**. A suíte canônica de CI passou em
**305 testes**. Logs/recibo desse ensaio ficam em
`.runtime/phase-3/unblock-a8a83ca/fresh-full-validate.log` e
`fresh-full-result.json`. Não foram alterados o checker de links, o controlador,
a política de retenção ou a quality bar congelada.

## Progresso do loop e medição de latência

No [quality 4d0db8b](https://github.com/ricardoakinaga-dev/rick-intelligence/actions/runs/40214481141),
FAST passou, confirmando a restauração autêntica no GitHub. CONTRACT preservou
um FAIL em `test_slow_identity_lookup_does_not_occupy_asgi_loop[login]`: 113,57 ms
para um assert de 100 ms que incluía admissão do runner antes da entrada no
worker. O contrato B07/T009 exige não bloquear o loop, sem fixar esse orçamento
de latência. O teste agora mantém o worker bloqueado por um evento, exige saúde
concorrente antes de liberá-lo e verifica que a identidade roda fora da thread
ASGI. Timeouts de cinco segundos apenas limitam fixture quebrado; não são novo
SLO. A medição de 113,57 ms e o breach de SLO local continuam preservados.

Os 43 testes de identidade passaram. Mutação isolada que executa a identidade
sincronamente na thread ASGI foi rejeitada pelo teste (um FAIL esperado),
confirmando que a prova causal detecta a regressão. Código de produção, limites
de admissão/deadline e critérios da quality bar não foram alterados por isso.
Essa alteração requer novo SHA/CI, sem reclassificar a falha de 4d0db8b.
