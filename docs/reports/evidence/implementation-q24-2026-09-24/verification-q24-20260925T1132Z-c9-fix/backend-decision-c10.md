# Decisão de arquitetura C10 — escopo e ordenação de identidade

## Problema e invariantes

C9 encontrou autorização administrativa apenas por tenant no adaptador volátil e uma corrida entre a validação de membership na recuperação de senha e sua desativação. Uma mutação precisa permanecer no tenant e workspace do ator; desativar membership não pode desativar outras memberships nem invalidar sessões fora desse escopo. Recuperação só pode trocar credenciais se a membership exata estiver ativa no ponto de serialização. A proteção de último administrador deve cobrir o mesmo workspace.

## Alternativas consideradas

- Manter o fallback permissivo: rejeitado porque atravessa workspaces.
- Modelar memberships múltiplas no adaptador em memória: rejeitado para esta correção; seu armazenamento atual mantém um único tenant/workspace por usuário e não oferece semântica durável.
- Reutilizar apenas um lock global de conta na recuperação: insuficiente porque a desativação bloqueia a linha de membership, sem adquirir a linha global da conta.

## Decisão

No adaptador volátil, cada mutação administrativa exige igualdade exata de tenant e workspace. A criação usa o workspace do ator; transferência de workspace falha fechada. Desativação altera apenas `membership_status`, mantém a conta global ativa e revoga sessões que correspondem ao tenant/workspace exatos. Demissão e desativação de administrador contam apenas administradores ativos nesse escopo. Um `RLock` local serializa o teste e a escrita de mutações administrativas no processo.

Na recuperação PostgreSQL, a transação primeiro bloqueia a linha global de `rick_users` e depois lê/bloqueia a linha exata de `rick_memberships` com `FOR UPDATE OF m`. A atualização de credenciais e a revogação de sessões permanecem na mesma transação. A desativação atualiza a linha de membership; o bloqueio dessa mesma linha estabelece a ordem serial: se recuperação bloquear primeiro, desativação aguarda o commit; se desativação confirmar primeiro, recuperação lê a membership inativa e faz rollback, inclusive da reivindicação do token. A resposta administrativa expõe `membership_status` e a interface apresenta essa condição de acesso separadamente do status global da conta.

## Consequências e verificação

O fallback em memória continua limitado a uma membership por usuário; operações fora dela são recusadas. O lock em memória coordena apenas threads do mesmo processo e não é evidência para uso distribuído. PostgreSQL continua sendo o caminho durável. Regressões incluem rotas administrativas cross-workspace, criação no workspace do ator, último administrador sob concorrência, mudança de workspace recusada, invalidação de sessão com workspace divergente, projeção/renderização da membership desativada, SQL do lock, concorrência real recuperação/desativação, rejeição de membership inativa e replay do token.
