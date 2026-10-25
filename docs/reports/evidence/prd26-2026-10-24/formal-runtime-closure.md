# Phase 3 — composições formais locais e pacote revisável

Data: 25/10/2026. HEAD de entrada: `5d66225a60e914c7398716c08be4c7f2dd47cfc0`.
As alterações desta rodada estão no worktree, sem commit/push. Autoridade:
concluir primeiro o laboratório local e preparar o pacote de produção.
Estado global: **PARTIAL / NO-GO**. Não houve aprovação, assinatura ou deploy.
Este relatório complementa o [fechamento anterior](phase3-local-closure.md),
preservando seu conteúdo histórico.

## Resultados observados

| Fronteira | Resultado local | Limite |
| --- | --- | --- |
| Tenant/evidence formal | 16/16 PASS na repetição isolada; 15/16 sob contenção, cleanup PASS | Timing falhou no ensaio concorrente; não há aprovação robusta sob carga |
| Golden formal | 45/47 checks PASS; 11/11 falhas injetadas PASS; cleanup PASS | Professor BLOCKED_EXTERNAL; trace de etapas FAIL por ausência de decisão/response após o bloqueio |
| Trace entre processos | PASS, 49 spans, nove categorias, mesmo trace | API e worker distintos, worker descendente de enqueue; não substitui o gate completo de observabilidade |
| Métricas da API | 13 amostras observadas; estado SLO `healthy` naquela janela | Não ratifica SLO, alertas, cardinalidade ou capacidade |
| Frontend/supply | FAIL preservado | Proxy de nomes acessíveis passou nas três larguras; zoom e dez estados obrigatórios continuam sem aprovação; imagens/SBOM NOT_RUN |

As composições usam PostgreSQL, Redis, S3/MinIO, Qdrant, fila e worker reais do
projeto dev canônico, com tenants novos e conteúdo sintético por execução.
HTTP utiliza o FastAPI real e sessões/identidade persistidas no PostgreSQL.
API e worker do trace rodam em processos próprios; Collector e Jaeger são os
serviços reais já ativos. O provider de embeddings/resposta é um fixture HTTP
local explicitamente selecionado, sem uso de provider pago.

O tenant gate exercita positivos A/B antes dos negativos e usa o **mesmo
processo de API** para as duas sessões, inclusive o buffer de telemetria.
A execução concorrente de golden/trace/tenant excedeu o limite local de timing:
p50 estrangeiro 126,80 ms versus inexistente 157,28 ms, delta 30,48 ms para
limite de 5 ms. O relatório FAIL e os p50 medidos com 32 amostras por grupo foram preservados em
`tenant-contention.json` e nas observações brutas. O harness agora conserva também os arrays de amostras
em novas execuções. Uma única repetição isolada passou em 16/16: p50 de
47,40 ms versus 47,00 ms, com os arrays das amostras conservados. Esse PASS não
apaga esse resultado; timing sob carga permanece não comprovado.
Os casos incluem versões/checksums/chunks/evidence IDs alterados, coleção/tenant
indevidos, upload hostil, contagem, objetos/jobs/coleções, resposta de erro,
identificadores de telemetria e medição de timing. O caso de prompt injection
mede o efeito da instrução no fixture; não certifica resistência de um modelo
real ou qualidade clínica.

## Defeitos corrigidos

- `/api/v1/admin/metrics` expunha eventos globais com identificadores de outros
  tenants a quem possuía somente `observability.read`. A resposta agora conserva
  agregados e restringe os eventos a quem possui `tenants.read`. Regressão
  verifica o bloqueio e o acesso administrativo, preservando o buffer interno.
- A fila persistia o contexto anterior ao span produtor. Agora o worker herda
  `queue.enqueue` quando ele pertence ao mesmo trace, preservando contexto
  explícito de outro trace e excluindo baggage.
- Chunks não persistiam a versão do índice preparado. A linhagem agora registra
  `dense-v1` ou `dense-sparse-logtf-v1` junto da projeção correspondente.
- Uma publicação pendente nunca terminava sua recuperação: o manifesto guardava
  o vetor original, enquanto uma coleção Cosine do Qdrant devolvia o vetor
  normalizado. O adaptador agora envia vetores unitários binary32 estáveis antes
  de calcular o manifesto, mantendo comparação exata de IDs, payload e vetores.
  O comportamento de normalização do servidor consta na
  [documentação oficial do Qdrant](https://qdrant.tech/documentation/manage-data/collections/).
  Não há tolerância arbitrária nem reescrita de manifestos antigos. Jobs
  pendentes de versões anteriores precisam de diagnóstico/reingestão próprios.
- O gate golden rejeitava um emissor de evidência por ele também expor o
  validador obrigatório e podia passar o mesmo argumento duas vezes ao port.
  Ambas as chamadas foram corrigidas sem capturar/reexecutar TypeError interno.
- Os gates agora tentam cleanup também em erro de preflight/caso, no mesmo loop
  dos clientes assíncronos. Processos e grupos próprios são encerrados; os
  containers e volumes compartilhados permanecem ativos. O servidor fecha os
  recursos injetados durante seu lifespan ASGI.
- O proxy de screen reader agora consulta nomes na árvore de acessibilidade do
  browser, reconhecendo texto nativo e labels associados. Isso não substitui
  teste com tecnologia assistiva ou revisão independente.

## Semântica da matriz de falhas

As 11 falhas são realmente injetadas, cada uma em um tenant/grafo independente,
com publicação equivalente de baseline antes da substituição. Não há PASS
padrão para casos ausentes. Replay consulta o mesmo job persistido.

O gate distinguia incorretamente toda falha como rollback, inclusive uma falha
**depois** do commit de publicação. Foi corrigido para respeitar o contrato já
existente do recibo imutável: esse caso exige recibo committed vinculado ao job,
uma única tentativa SUCCEEDED, nova versão/checksum, projeção consistente com
contagem de chunks/pontos, replay idempotente e aposentadoria da versão anterior.
A recuperação de `before_publish` exige ainda prova de que a baseline permaneceu
publicada enquanto o recibo estava pending. Negativos de regressão rejeitam
recibo ausente, sucesso duplicado, contagem booleana, projeção inconsistente e
aposentadoria ausente. As demais falhas conservam o invariante anterior.

Essa correção de semântica requer revisão independente antes de release. Não
altera a quality bar congelada nem cria autoridade de produção.

Há uma reconciliação **explícita do harness** para atualizar no Qdrant o timestamp
de publicação já confirmado pelo PostgreSQL, sob guards de coleção/documento,
preservando os vetores e verificando a escrita. Não é uma correção simulada no
resultado de busca e não demonstra que todo caminho de produção já faça essa
reconciliação automaticamente. A revisão deve avaliar essa responsabilidade.

## Reprodução e pacote

Com o projeto dev e `rick-dev-provider` ativos:

```bash
make phase3-local-tenant-evidence
make phase3-local-distributed
make phase3-local-golden
make phase3-prepare-production
```

Os comandos são diagnósticos locais explícitos. Golden retorna código não zero
até todos os checks passarem. Nenhuma saída muda `production_safe=false` ou
substitui os control-inputs/envelopes canônicos.

Artefatos em `.runtime/phase-3/formal-local/`: `tenant-current.json`,
`golden-current.json`, `distributed.json`, `frontend-supply.json`, observações
brutas por run ID e logs de regressão. O trace bruto validado é conservado em
`<run_id>/distributed-trace.json`, com caminho/hash no relatório; não depende
apenas da retenção volátil do Jaeger. O
[preparador](../../../../scripts/state_of_art/prepare_phase3_handoff.py) indexa
os relatórios, observações brutas e logs de verificação disponíveis por hash,
os 15 envelopes
anteriores, preflight, estado do checkout e manifesto de fontes, incluindo
arquivos novos. Seu resultado é `PREPARED_NO_GO`, sem assinatura e com revisão
independente/decisão humana PENDING. Saída em
`.runtime/phase-3/local-closure/production-handoff.json`, com cópia por hash.

## Verificação e trabalho restante

Regressão principal: **478 passed**, cobrindo gates, API, ingestão, recuperação e
adaptador Qdrant. Regressão adicional de preparação/híbrido: **62 passed,
5 skipped** (testes live opcionais não configurados). Há um aviso de depreciação
da integração Starlette/httpx; nenhum erro nessa regressão. A execução real
acima é evidência distinta dos testes herméticos. A verificação adicional de
fronteiras passou em 100 testes; a de lifecycle/preparação passou em 62 testes
após incluir fechamento de stores mesmo quando outro recurso falha. Essas
suítes se sobrepõem e suas contagens não devem ser somadas.

`make validate` PASS (1.198 links, zero erros), `make compose-static` PASS
(16 serviços em dev e staging), `make typecheck` PASS e `git diff --check` PASS.
A quality bar conserva SHA-256
`fe0f58eb84bea4d16a138391b1afd85a9312d81fdb2ac7a383c2dbaf767f9633`.

Permanecem necessários:

1. Avaliador/corpus aprovado para suporte de claims/faithfulness e observação
   completa de professor/decisão/response. O fixture não fornece essa aprovação.
2. Estabilidade/medição de timing sob carga e fechamento do gate canônico de observabilidade: métricas, cardinalidade,
   alertas e SLO, além do trace já observado.
3. Harnesses e execução das matrizes completas de performance (cinco workloads,
   concorrência 1/10/50/100), chaos (13 falhas) e soak curto/estendido. Precisam
   de limites/janelas/durações definidos para o ambiente isolado; não foram
   executados nem aprovados nesta rodada.
4. Implementação/exercício dos dez estados restantes do harness de frontend,
   correção de zoom/reflow e evidência de imagens imutáveis, SBOM, scans,
   proveniência e assinaturas. O browser atual observa login/autenticação/chat.
5. Perfil TLS/auth revisado, secret/trust stores, CI remoto no SHA final e
   revisão independente. Após candidato limpo, regenerar preflight/envelopes,
   verificar o packet selado e obter a decisão humana GO/NO-GO.

Revisão própria do diff foi feita separadamente; não é revisão independente.
As pendências técnicas locais acima permanecem abertas e não se tornam
BLOCKED_EXTERNAL apenas por falta de implementação. Produção continua NO-GO.
