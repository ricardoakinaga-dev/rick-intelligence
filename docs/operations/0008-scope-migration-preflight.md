# Preflight da migration 0008

## Escopo

Execute `docs/operations/0008-scope-preflight.sql` somente em uma cópia autorizada da base, com conexão de leitura. O arquivo retorna quatro contagens agregadas; todas devem ser zero antes de aplicar `0008_composite_scope_constraints.sql`. O inventário não repara nem exclui linhas.

## Comando somente de leitura

O comando `infrastructure/scripts/scope_preflight.py` executa esse mesmo SQL
em transação PostgreSQL `REPEATABLE READ, READ ONLY`. Disponibilize a conexão
autorizada em `RICK_PREFLIGHT_DATABASE_DSN` e informe um identificador não
sensível do snapshot. A ferramenta usa exclusivamente essa variável; ela não
herda automaticamente `RICK_EXTERNAL_DATABASE_DSN`. O driver `psycopg` deve
estar instalado no ambiente de execução.

```bash
python3 infrastructure/scripts/scope_preflight.py --snapshot-id snapshot-autorizado-20261004
```

Alternativa pelo Make, com a mesma conexão já configurada no ambiente:

```bash
RICK_PREFLIGHT_SNAPSHOT_ID=snapshot-autorizado-20261004 make ops-scope-preflight
```

O stdout contém um objeto JSON com os quatro totais, identificador informado,
horário UTC, configuração da transação e SHA-256 do SQL executado e da migration
local 0008. Não contém DSN, identificadores de registros ou conteúdo das linhas.
Guarde a saída somente quando o processo terminar com o resultado esperado.
O identificador de snapshot é uma declaração do operador; a ferramenta não
atesta a origem, a autorização ou a correspondência dessa conexão ao snapshot.

| Exit code | Resultado | Interpretação |
|---|---|---|
| 0 | `NO_CONFLICTS` | Os quatro totais são zero |
| 1 | `BLOCKED` | Há pelo menos uma referência incompatível |
| 2 | Sem JSON de sucesso | Configuração, consulta ou resultado inválido; não foi possível concluir |

A conexão usa timeout de 5 segundos, cada consulta tem limite de 15 segundos
e espera por lock de 5 segundos. Erros do driver expõem apenas SQLSTATE,
sem seus diagnósticos ou valores de linhas. A conta deve ter permissão de
leitura nas tabelas consultadas; a transação impõe READ ONLY também quando a
conexão usa uma conta com permissão de escrita.

`NO_CONFLICTS` se limita aos totais dessas quatro relações. O comando não
valida checksums da história instalada, definições de constraints, permissões,
backup ou compatibilidade de versões; esses pré-requisitos continuam na
sequência abaixo. Não aplica migration, repair, backfill ou reconciliação.

| Relação | Leitura e escrita afetadas | Pré-condição |
|---|---|---|
| chunk → documento | `packages/knowledge/src/rick_knowledge/postgres_store.py` | tenant, workspace e collection iguais aos do documento |
| job → documento | `apps/worker/postgres_jobs.py`, `apps/worker/postgres_queue.py` | documento nulo ou mesmo tenant, workspace e collection; a FK de 0004 já deve estar validada |
| conversa → collection | `apps/api/src/services/postgres_chat_history.py` | collection nula ou presente no mesmo tenant e workspace |
| mensagem → conversa | `apps/api/src/services/postgres_chat_history.py` | tenant, workspace e user iguais aos da conversa |

## Sequência de execução

1. Identifique o candidato por commit e fingerprint da árvore; registre checksums dos arquivos de migration. Obtenha inventário da história instalada conforme [procedimento de upgrade](migration-upgrade-2026-09-24.md).
2. Em snapshot descartável aprovado, execute o comando acima ou o SQL em transação `READ ONLY` e salve os quatro totais, identificador do snapshot e metadados da execução. Uma contagem positiva bloqueia a aplicação; investigue as linhas na própria base sob autorização de dados.
3. Reconcilie cada linha incompatível na origem com decisão de titularidade e trilha de auditoria. Faça novo snapshot e repita o preflight. A migration não faz backfill implícito.
4. Faça backup verificável antes da aplicação. Execute `migrate.py --check` e depois `--apply` somente no ambiente autorizado. Em transação separada, tente as quatro associações cruzadas e confirme rejeição, preservando inserções e leituras válidas.
5. Em falha antes do commit, confirme que o registro de 0008 não foi gravado; repita após corrigir a causa. Depois do commit, recupere a cópia a partir do backup testado se for preciso reverter dados ou esquema. Não edite checksums históricos nem remova constraints manualmente.

O preflight executável não demonstra, por si só, compatibilidade de uma base instalada. Testes em PostgreSQL descartável com dados sintéticos cobrem aplicação, rejeição de referências cruzadas e rollback transacional; o inventário e a recuperação de uma base instalada exigem snapshot identificado e autorização própria.
