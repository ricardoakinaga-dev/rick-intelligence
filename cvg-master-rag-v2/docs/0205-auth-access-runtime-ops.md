# 0205 — Auth Access Runtime Ops

## Como Criar o Primeiro Admin
- Estratégia desta rodada:
  - manter o bootstrap local compatível
  - criar utilitário operacional via backend/admin state para promover o primeiro usuário a `super_admin`
- Regra:
  - só `super_admin` pode criar outro `super_admin`
  - em ambiente vazio, bootstrap controlado é permitido uma única vez

## Como Resetar Senha de Forma Segura

### Fluxo de usuário
1. Solicitar reset.
2. Receber token temporário por canal controlado.
3. Confirmar reset com nova senha.
4. Todas as sessões anteriores são revogadas.

### Fluxo administrativo
1. `super_admin` executa reset administrativo.
2. Sistema força `must_change_password`.
3. Evento auditado como `user.password_reset_admin`.

## Como Revogar Sessão
- `super_admin` pode:
  - revogar sessão específica
  - revogar todas as sessões de um usuário
- Uso recomendado:
  - credencial comprometida
  - mudança de papel
  - desligamento/desativação

## Como Desativar Usuário
1. Marcar usuário como `disabled`.
2. Revogar sessões ativas.
3. Registrar motivo operacional.
4. Auditar ação.

## Como Operar Permissões
- Nesta rodada, permissões são derivadas de papéis canônicos.
- Não haverá editor arbitrário de permission override na UI, exceto suporte estrutural no backend.
- Mudança de papel é a operação primária de governança.

## Como Auditar Acessos
- Consultar:
  - `admin_events.jsonl` via endpoints admin
  - query logs e observability logs já existentes
- Filtrar por:
  - usuário
  - ação
  - tenant/workspace
  - resultado

## Resposta a Incidente Simples de Credencial Comprometida
1. Revogar sessões do usuário.
2. Forçar reset de senha.
3. Revisar eventos recentes:
  - login
  - login_failed
  - access_denied
  - ações destrutivas
4. Reativar acesso apenas após troca de senha.
