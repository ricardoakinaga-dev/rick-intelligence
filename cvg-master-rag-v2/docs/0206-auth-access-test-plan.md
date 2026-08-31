# 0206 — Auth Access Test Plan

## Testes Unitários
- hashing e verificação de senha
- compatibilidade com hashes legados
- política mínima de senha
- normalização de roles legadas
- resolução de permissões por role
- expiração/consumo de reset token
- revogação de sessão

## Testes de Integração
- login válido
- login inválido
- usuário inativo
- logout
- auth/me
- switch tenant permitido
- switch tenant negado
- change-password
- request-password-reset
- confirm-password-reset com token válido
- confirm-password-reset com token expirado

## Testes E2E
- login pelo frontend
- acesso a rota negada com redirect para `/forbidden`
- troca de senha com feedback consistente
- recuperação/reset com feedback consistente
- admin de usuários com role gating

## Testes de Regressão
- chat continua funcionando para perfil permitido
- busca continua funcionando para perfil permitido
- listagem de documentos continua funcionando
- upload continua funcionando apenas para perfil autorizado
- avaliação/observability continuam preservadas para perfis autorizados

## Testes de Permissão por Rota
- `super_admin` acessa governança de usuários
- `admin_rag` não acessa governança de usuários
- `admin_rag` pode operações operacionais do RAG
- `auditor` lê auditoria mas não muta corpus
- `operator` pode upload/ingestão permitidos
- `viewer` não faz upload nem avaliação operacional

## Testes de Sessão
- sessão expira
- sessão revogada falha
- sessão anterior à troca de senha falha
- sessão anterior à desativação falha
- sessão anterior a mudança de role falha

## Testes de Reset/Troca de Senha
- troca válida
- troca com senha atual errada
- reset com token válido
- reset com token expirado
- reset com token reutilizado
- reset request com usuário inexistente retorna mensagem neutra

## Testes de Auditoria
- login gera evento
- falha de login gera evento
- logout gera evento
- access denied gera evento
- alteração de papel gera evento
- reset de senha gera evento
- ação crítica operacional gera evento

## Cenários de Acesso Negado
- viewer em upload
- viewer em admin
- operator em governança de usuários
- auditor em deleção/reparo destrutivo
- admin_rag em role management

## Matriz Perfil x Ação

| Ação | super_admin | admin_rag | auditor | operator | viewer |
|---|---|---|---|---|---|
| login | ✅ | ✅ | ✅ | ✅ | ✅ |
| search/query | ✅ | ✅ | ✅ | ✅ | ✅ |
| documents.read | ✅ | ✅ | ✅ | ✅ | ✅ |
| documents.upload | ✅ | ✅ | ❌ | ✅ | ❌ |
| evaluation/observability | ✅ | ✅ | ✅ leitura | ✅ | ❌ |
| corpus repair/destructive ops | ✅ | ✅ conforme política | ❌ | ❌ | ❌ |
| users.manage | ✅ | ❌ | ❌ | ❌ | ❌ |
| roles.manage | ✅ | ❌ | ❌ | ❌ | ❌ |
| sessions.revoke | ✅ | ❌ | ❌ | ❌ | ❌ |
| audit.export | ✅ | ❌ | ❌ | ❌ | ❌ |
