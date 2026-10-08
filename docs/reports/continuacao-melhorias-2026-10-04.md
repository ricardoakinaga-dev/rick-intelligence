# Continuação das melhorias — 04/10/2026

Foi concluída a preparação local do preflight de escopo da migration 0008,
relacionada a AUD03-27. O novo comando
`infrastructure/scripts/scope_preflight.py` executa o SQL agregado existente em
transação PostgreSQL `REPEATABLE READ, READ ONLY`, com limites para conexão,
consulta e espera por locks. O alvo `make ops-scope-preflight` expõe o mesmo
comportamento. As oito migrations e o sidecar de repair foram preservados.

O JSON inclui os quatro totais, snapshot informado, horário e hashes das fontes;
não exporta DSN ou conteúdo de registros. Quatro zeros retornam 0 e
`NO_CONFLICTS`; conflitos retornam 1 e `BLOCKED`; configuração, consulta ou
resultado inválido retorna 2, sem JSON de sucesso. O
[runbook](../operations/0008-scope-migration-preflight.md) documenta ambiente,
comandos e limites. A ferramenta exige `RICK_PREFLIGHT_DATABASE_DSN` e não usa
implicitamente a configuração externa do produto.

## Evidência executada

- [20 testes unitários](evidence/implementation-aud03-2026-10-03/lead/continuation-20261004-scope-preflight-unit.command.json)
  passaram: resultados completos, duplicados, ausentes e inválidos, identificador,
  exit codes, configuração explícita e redação de erros.
- [154 testes de regressão de migrations e preflight](evidence/implementation-aud03-2026-10-03/lead/continuation-20261004-scope-preflight-regression.command.json)
  passaram com o PostgreSQL opt-in habilitado, sem skips. Houve um aviso existente
  de depreciação do transporte httpx de Starlette no teste administrativo.
- [Make ops-static](evidence/implementation-aud03-2026-10-03/lead/continuation-20261004-scope-preflight-static.command.json)
  passou, incluindo checksums das oito migrations/repair, shell, compilação,
  checker canônico e 297 testes de CI.
- [27 verificações finais](evidence/implementation-aud03-2026-10-03/lead/continuation-20261004-scope-preflight-final.command.json)
  passaram no candidato final: 20 unitárias, seis probes PostgreSQL do preflight
  e uma regressão da CLI de migrations. O manifesto inclui 17 fontes estáveis,
  incluindo o runner de migrations e seu sidecar.

As contagens se sobrepõem. A única alteração após a regressão de 154 casos foi
nos testes, para arquivar os JSONs sintéticos observados; as 27 verificações
finais cobrem essa alteração. Os resultados anteriores permanecem preservados.

O laboratório usou Python 3.12.3 do ambiente instalado dos locks e PostgreSQL
16.15 em containers próprios, loopback, CPU/RAM limitadas e databases sintéticas.
Os probes observaram quatro conflitos simultâneos, rejeição de UPDATE com uma
conexão privilegiada, erro em schema ausente, timeout real de lock e execução
pelo Make. Comparações antes/depois incluíram dados, constraints, triggers e
histórico; nenhuma alteração foi causada pelo preflight. Os
[artefatos finais e autorrevisão](evidence/implementation-aud03-2026-10-04/scope-preflight/completion.json)
vinculam critérios P1–P5, hashes, saídas JSON e identificação/teardown dos containers.

## Limites e continuidade

A revisão desta unidade foi autorrevisão separada, sem aprovação independente.
O identificador do snapshot é declarado pelo operador. Totais zero não validam
checksums da história instalada, definições de constraints, backup, compatibilidade
ou autorização de aplicação. A ferramenta não aplica migration, repair ou backfill.

O inventário D02 de uma base instalada continua não executado. AUD03-27 não foi
encerrada e a promoção permanece **NO-GO**. O worktree compartilhado continua
com alterações de rodadas anteriores; esta unidade não valida conjuntamente
todas elas, os locks de dependências ou o Compose. Os controles históricos e o
checkpoint v2 permanecem preservados.

Próxima ação para o aceite externo de AUD03-27: identificar a cópia autorizada,
obter a história instalada e constraints conforme o procedimento de upgrade e
executar o preflight no mesmo snapshot. Esta rodada conclui apenas a ferramenta
e sua validação local.
