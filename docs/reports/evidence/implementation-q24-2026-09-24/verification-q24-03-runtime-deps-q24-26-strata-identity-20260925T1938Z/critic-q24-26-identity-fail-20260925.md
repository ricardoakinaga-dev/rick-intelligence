# Revisão independente — identidade dos estratos antes do v4

**Veredito:** `FAIL` válido para o snapshot revisado.  
**Revisor:** Jason; revisão independente I1, sem contexto herdado (`fork_context=false`), escopo selado e somente leitura.  
**Artefato:** Q24-03 dependências/runtime e Q24-26 avaliador de campanha, snapshot anterior à correção v4.

## Integridade da revisão

O fingerprint do candidato permaneceu `a74f9cf061eee070e1907a4eb5d1212ab7d224348ee22fadfff80e2a24b05ce6` antes e depois da revisão. O sentinel de mutação permaneceu `10c10a483b824f9f3bd553dece5f06d11c48f1bed21d9fc6181c76551e9d6522`. O agente declarou que não fez nova inspeção, executou comandos/testes ou escreveu arquivos após concluir o parecer. Nenhuma mutação foi detectada.

## Achados

1. **Falha — identidade textual não preservava igualdade exata.** `_text()` removia espaços nas pontas; IDs não vazios como `ranker` e ` ranker ` podiam ser agrupados como se fossem a mesma identidade.
2. **Falha — sufixo de rótulos não era injetivo.** `stratum_id` usava somente os primeiros 16 caracteres hexadecimais do SHA-256 do JSON de dimensões. A saída não permitia recuperar os rótulos e não garantia unicidade para todas as entradas.

O revisor confirmou que os cinco pins de dependência estavam presentes, incluindo `httpx`; a campanha sintética seguia `NOT_RUN`/`BLOCKED` e a abstenção observada seguia `NOT_MEASURED`. Esses pontos não alteram o `FAIL` de identidade.

## Tratamento

Os dois achados foram corrigidos no resultado v4: identidades e rótulos preservam espaços significativos, componentes de identidade são escapados, e dimensões JSON canônicas usam codificação URL-safe reversível sem hash truncado. Regressões cobrem os dois problemas e os IDs compartilhados entre estratos, qualidade e intervalos. A evidência local pós-correção está no manifesto desta verificação; nova revisão independente permanece pendente.
