# Phase 3 — laboratório e preparação do pacote de produção

**Data:** 25/10/2026. **HEAD de entrada:** `1641a28cb25f82ba7308cccbe546589c554bf82d`,
checkout inicialmente limpo. As alterações desta rodada permanecem sem commit.
**Autoridade:** pedido humano para resolver bloqueios, seguido da escolha
“Concluir primeiro o laboratório local e preparar o pacote de produção”.
**Decisão de produção:** `NO-GO`. Não houve revisão independente, assinatura,
deploy, consumo de provider pago ou decisão humana GO nesta rodada.

## Correções e prova local

O [probe do produto](../../../../scripts/phase11/local_product_probe.py) passou
**17/17 checks** sobre o grafo real de composição externa, com tenant exclusivo
por execução. Ele observou upload/replay preservando o job, bytes e checksum
no S3, publicação pelo worker, linhagem PostgreSQL, projeção Qdrant, recuperação,
isolamento de documentos/chunks/busca e autoridade de evidência. Também observou
rejeição de tenant/coleção indevidos, versão explicitamente obsoleta, chunk
inexistente e evidence ID forjado. O checksum alterado na projeção é substituído
pelo checksum canônico: isso é **canonicalização**, não rejeição na emissão.
O contrato existente de autoridade foi preservado.

O fixture HTTP de embeddings/citação é iniciado e encerrado pelo probe em uma
porta loopback exclusiva. A resposta passou por `publication_validation=verified`.
Isso prova integração e contrato de citação, não qualidade de IA/modelo.
O fixture deixou de escrever o conteúdo dos prompts no log de debug.

Foi encontrada e corrigida uma divergência real de configuração: o bootstrap
Qdrant e os dois workers recebiam `EMBEDDING_DIMENSION`; a API não. A API usava
1536 por padrão contra um índice de 2 dimensões no laboratório. Ambos os
Compose agora propagam a dimensão à API, e o check estático rejeita ausência
ou divergência entre os quatro consumidores. A API dev foi recriada, recebeu
dimensão 2 e ficou `healthy`. Nenhuma topologia de produção foi iniciada.

O check estático do Collector também passou a reconhecer a sonda nativa
`CMD /otelcol-contrib validate`, preservando a rejeição de shell e a exigência
da sonda HTTP real em `collector-ready`.

O probe opcional exportou um trace pelo Collector real e consultou o Jaeger:
**13 spans, 12 vínculos de parentesco**, trace
`4c88d76570c8c729fda3cfbc01ceeaeb`. Operações observadas: fila, worker,
object storage, retrieval, embeddings/chat provider, evidência e decisão.
Esse resultado cobre o grafo local e sua thread de worker; **não** prova a
matriz distribuída HTTP/OIDC → API → worker em processos separados, métricas,
alertas, cardinalidade ou soak de produção.

## Reproduzir e revisar

O [carregador do lab](../../../../scripts/phase11/local_lab_environment.py)
inspeciona somente containers do projeto dev canônico e o fixture explicitamente
selecionado. As credenciais ficam em memória; a reescrita do host preserva
userinfo, portas e parâmetros. O probe recusa perfil de produção, provider
externo e endereços privados sem opt-in. Ele conserva dados sintéticos para
inspeção e fecha apenas recursos de sua própria execução.

```bash
RICK_LOCAL_PROVIDER_CONTAINER=rick-dev-provider make phase3-local-product-probe
make phase3-prepare-production
```

Para consultar também o Collector/Jaeger internos do lab, obter seus endereços
atuais via `docker inspect` e executar:

```bash
PYTHONPATH="$PWD" python3 scripts/phase13/pyexec.py \
  scripts/phase11/local_product_probe.py \
  --from-dev-compose --provider-container rick-dev-provider \
  --managed-provider-fixture --allow-private-containers \
  --trace-collector-url "http://${LAB_COLLECTOR_IP}:4317" \
  --trace-backend-url "http://${LAB_JAEGER_IP}:16686"
```

Saídas locais: `.runtime/phase-3/local-closure/product-probe.json`, arquivo
por run ID, e `production-handoff.json`, com cópia por hash. O
[preparador](../../../../scripts/state_of_art/prepare_phase3_handoff.py) indexa
15 lanes, hashes dos raw artifacts/preflight, vínculos ao candidato e o
manifesto dos arquivos de origem, incluindo novos arquivos não ignorados.
Ele sinaliza ausência, hash incorreto, commit/tree/fingerprint divergentes,
evidência obsoleta, worktree sujo, perfil inseguro e revisão ausente.
Seu estado é sempre `PREPARED_NO_GO`, sem assinatura, review ou GO inventados.
A aceitação semântica continua pertencendo aos verificadores canônicos.

## Frontend/supply-chain: falha preservada

A execução real do gate adicional de frontend/supply-chain retornou `FAIL`.
Os resultados individuais de axe e contraste não registraram violações nas
telas observadas, mas o gate apontou falhas nos proxies de screen reader/zoom
e falta de observação dos estados de upload/documentos/fontes/jobs/offline,
interrupção e indisponibilidade. O probe atual preenche login/autenticação/chat;
ele ainda não exercita todos os estados mandatórios. Imagens imutáveis e SBOM
de container ficaram `NOT_RUN`. Isso não é aprovação de frontend/acessibilidade.

Foi identificado outro defeito no harness: `--output` alternativo não isolava
os artefatos auxiliares. O browser sobrescreveu um control-input canônico.
A execução foi preservada em `local-closure/frontend-artifacts-first-run/`,
com hash e motivo em `frontend-output-isolation.json`, antes de restaurar
o input autenticado com o restaurador original. O gate agora aceita
`--evidence-dir` confinado ao repositório, com regressão de isolamento/escape.
Usar sempre os dois caminhos em uma nova rodada diagnóstica:

```bash
python3 scripts/phase11/frontend_supply_runtime_gate.py \
  --output .runtime/phase-3/local-closure/frontend-supply.json \
  --evidence-dir .runtime/phase-3/local-closure/frontend-artifacts
```

## Verificação e limites de aceite

A regressão focada executada passou em **190 testes** de preparação, Compose,
observabilidade, golden, tenant/evidence e frontend/supply. O teste com dimensão
ausente/divergente rejeita a configuração. Os negativos do preparador cobrem
hash adulterado, path externo, symlink, timestamp antigo/futuro, status/exit
inválido, fonte não versionada alterada e impossibilidade de gerar aprovação.
`make validate` passou com **1.198 links e zero erros**; `make compose-static`
passou nos dois perfis de 16 serviços. A nova execução real de frontend com
`--evidence-dir` preservou os inputs canônicos e continuou `FAIL`, conforme os
limites registrados acima. `git diff --check` passou. Os links deste novo
relatório foram conferidos separadamente, pois `docs-check` exclui evidências.

O [plano desta rodada](../../../../.agent/plans/phase3-local-closure-2026-10-25.md)
registra escopo e recuperação. Foi realizada revisão própria separada; não há
outro revisor nesta sessão. Os gates formais de golden/tenant permanecem abertos:
o probe não substitui os 11 crash points, parse/normalize explícitos, métricas
de suporte, negativos HTTP/OIDC e canais de enumeração/timing.

## Pendências que impedem promoção

1. Completar as composições formais golden e tenant/evidence e seus critérios
   ainda não observados; conservar o novo probe como regressão da integração.
2. Completar o trace distribuído entre processos e as métricas/alertas/SLO.
3. Definir/aprovar workloads, limites, duração e janelas e executar as matrizes
   completas de performance, chaos e soak.
4. Completar os estados do harness de frontend, corrigir falhas reais de UX
   confirmadas, obter revisão visual/AT independente e evidência de imagens.
5. Fornecer perfil TLS/auth revisado, referências de secret/trust stores,
   CI remoto, imagens imutáveis, SBOM/scans/proveniência/assinaturas.
6. Após commit revisado, regenerar o preflight/envelopes no mesmo candidato
   limpo, obter revisão independente e a decisão humana sobre o packet selado.

Essas pendências não foram fechadas por este relatório. O pacote é preparatório
e a decisão continua `NO-GO`; os sete envelopes locais anteriores não recebem
`production_safe=true` por causa do novo probe.
