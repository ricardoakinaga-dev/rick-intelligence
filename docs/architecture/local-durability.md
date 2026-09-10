# Local durability adapter

Status: `PARTIAL / LOCAL REWORK UNDER VERIFICATION` em 2026-09-06.

`SQLiteKnowledgeStore` é o primeiro adapter transacional do protocolo
`KnowledgeStore`. Ele persiste collections, documents, tombstones e chunks em
um arquivo com schema versionado (`PRAGMA user_version=2`), WAL e transações
`BEGIN IMMEDIATE`. O teste de contrato fecha uma instância, abre outra e
confirma dados, ACL por tenant/collection, paginação e tombstone. A identidade
de uma collection é `(tenant_id, workspace_id, collection_id)`; assim, dois
tenants podem reutilizar os mesmos nomes sem sobrescrever o catálogo do outro.
Databases locais no schema 1 migram essa chave de forma transacional ao reabrir.

Para o factory root local, configurar:

```text
RICK_KNOWLEDGE_SQLITE_PATH=/var/lib/rick/knowledge.sqlite3
```

Sem essa variável, o fixture continua `InMemoryKnowledgeStore`. Em
`RICK_ENV=production`, o path SQLite é rejeitado: produção exige um store
externo injetado pelo deployment.

O factory root também pode ativar um `JobJournal` local:

```text
RICK_INGESTION_JOURNAL_PATH=/var/lib/rick/jobs.sqlite3
RICK_INGESTION_STAGING_PATH=/var/lib/rick/staging
RICK_INGESTION_JOURNAL_MAX_ROWS=256
```

O journal persiste uma whitelist bounded de estado do job, escopo ACL e
referências de staging privada. Fontes publicadas são restauradas para
reindex; jobs não terminais com fonte existente são retomados pelo executor
local bounded; uma fonte ausente vira falha explícita `recovery_required`. As
respostas marcam esse caminho como `durability=local-sqlite` e
`restart_recovery=true`.

ACL, metadata e snapshots persistidos são tratados como JSON não confiável:
o limite de 32 KiB, números finitos, estrutura allowlisted e chaves de objeto
únicas são exigidos antes de uma linha virar estado de recuperação. Uma linha
ambígua ou corrompida é omitida; o journal nunca escolhe silenciosamente o
último valor de uma chave duplicada. Essa é contenção local e bounded, não
prova de fila distribuída ou durabilidade PostgreSQL.

## Rework após revisão I1

O slice local foi reaberto depois de uma revisão independente encontrar quatro
falhas de fronteira. A implementação atual:

- exige `tenant_id` em toda enumeração de collections; omissão não vira
  wildcard nem retorna dados de outro tenant;
- exige tenant explícito também na fachada de conhecimento e no lifecycle:
  DTOs internos preservam o tenant validado para uma segunda checagem, a
  resposta pública continua em allowlist e registros tenantless não são
  promovidos ao tenant `default`;
- valida o postcondition do adapter de reindex depois da chamada: o job precisa
  conservar o escopo solicitado e o novo `document_id`, quando houver, precisa
  apontar para um documento canônico do mesmo escopo;
- aplica o hardening de permissões do journal antes do `commit`, de modo que
  uma falha de filesystem não seja reportada como erro depois de uma gravação já
  confirmada; e
- trata referências de staging como leases internos: se o unlink falha, a
  referência permanece no job/journal ou em um job de quarentena com escopo
  explícito e é repetida no restart. Isso inclui falhas de upload, reindex,
  eviction, cancelamento e delete.

Se a escrita do journal e o unlink falharem na mesma janela, uma lease privada
atômica é gravada em `.cleanup-leases/` com modo `0700/0600`; no próximo
processo, a lease é validada contra o staging privado, removida com sucesso e
só então o marcador é apagado. O marcador não é uma fila distribuída nem uma
autorização para reprocessar a fonte.

O rework é uma garantia bounded para o adapter local. Não implica atomicidade
distribuída, ausência de orphan files diante de falha catastrófica do host, ou
durabilidade de produção.

Esses adapters não resolvem o spine de produção. Os vetores do runtime local
ainda ficam em memória, não há object storage privado nem fila Postgres
multi-instância, e `RICK_ENV=production` rejeita os paths locais de knowledge,
auditoria e jobs. O próximo gate é uma implementação externa coordenada de
repository/object/queue com migrations, idempotência, leases multi-instância,
backup/restore e drill de restart na topologia alvo.
