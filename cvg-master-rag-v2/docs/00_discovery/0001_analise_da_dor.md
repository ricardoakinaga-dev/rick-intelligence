# 0001 — Análise da Dor

## Objetivo

Transformar a percepção do programa em dores concretas e mensuráveis.

---

## Dor 1: Ausência de Dataset de Avalidação Real

### Quem sofre
- Equipe de QA
- Time de produto
- Responsáveis por gates de fase

### Quando ocorre
- Toda vez que um gate de fase precisa ser validado
- Toda vez que uma decisão de qualidade precisa ser tomada
- Sempre que alguém pergunta "o sistema está funcionando bem?"

### Frequência
- Contínua — impede todas as decisões de gate
- Sem dataset, não há como verificar se o sistema melhorou ou piorou

### Impacto
- **Tempo:** Equipe gasta tempo validando manualmente em vez de usar métricas objetivas
- **Dinheiro:** Decisões de investimento podem ser tomadas com base em percepção, não em dados
- **Erro:** Gates podem ser aprovados com critérios subjetivos
- **Experiência:** Incerteza sobre a qualidade real do sistema

### Consequência de não resolver
- Continue Usingates sem validação objetiva
- Riscos de produção com problemas não detectados
- Dificuldade de justificar melhorias ou investimentos
- Impossibilidade de comparar versões do sistema

### Evidências observadas
- Documentação do programa indica dataset como "blocker número 1" (0037-roadmap-executivo-e-matriz-de-importacao.md)
- Auditoria 2026-04-17 classifica nota geral em 87/100 com dataset sendo gap crítico
- PRD do programa não pode verificar gates sem dataset válido

---

## Dor 2: Auth Enterprise Incompleto

### Quem sofre
- Operadores de sistema
- Administradores
- Usuários finais

### Quando ocorre
- Quando sessão expira inesperadamente
- Quando múltiplos workspaces precisam ser gerenciados
- Quando permissões precisam ser aplicadas

### Frequência
- Alta — afeta operação diária
- Sistema atual depende de headers do cliente (X-Enterprise-*), não de autenticação real

### Impacto
- **Tempo:** Operadores perdem tempo com sessões não persistidas
- **Erro:** Permissões podem ser burladas via headersmanipulados
- **Experiência:** Navegação por perfil não funciona de forma confiável
- **Segurança:** Risco de acesso não autorizado

### Consequência de não resolver
- Sistema não pode ser considerado enterprise ready
- Não há isolamento real entre tenants
- Compliance e governança ficam comprometidos

### Evidências observadas
- TKT-001 no backlog: "Substituir autenticacao baseada em cabecalho por sessao resolvida no servidor"
- Sprint G1 da Fase 3 parcialmente implementado com autenticação via sessão

---

## Dor 3: Features Premium Pendentes

### Quem sofre
- Time de desenvolvimento
- Produto
- Usuários que esperam funcionalidades prometidas

### Quando ocorre
- Quando hyDE precisa ser avaliado para implementação
- Quando semantic chunking precisa ser decidido
- Quando reranking precisa ser confirmado ou removido

### Frequência
- Episódica — cada vez que uma decisão de roadmap precisa ser tomada
- Feature foi prometida na documentação mas não implementada

### Impacto
- **Tempo:** Desenvolvimento precisa reavaliar decisões já tomadas
- **Dinheiro:** Custo de implementação sem evidência de benefício
- **Erro:** Implementar features sem validar se realmente agregam valor

### Consequência de não resolver
- Roadmap inflado com promessas não cumpridas
- Dificuldade de estimar esforço real
- Desconfiança na documentação

### Evidências observadas
- TKT-025, TKT-026, TKT-027 no backlog: reranking, HyDE, semantic chunking pendentes
- Roadmap executivo (0037) marca estas como P2 para pós-H6

---

## Dor 4: Observabilidade Insuficiente

### Quem sofre
- Operações (SRE/DevOps)
- Time de produto
- Suporte

### Quando ocorre
- Quando um problema ocorre e logs não são suficientes para debug
- Quando métricas de SLA precisam ser reportadas
- Quando alertas precisam ser configurados

### Frequência
- Contínua em ambiente de produção
- Fase 0 tem telemetria básica, mas Fase 3 (enterprise) precisa de mais

### Impacto
- **Tempo:** Debugging leva mais tempo sem tracing adequado
- **Erro:** Problemas podem passar despercebidos
- **Experiência:** Inabilidade de responder a incidentes rapidamente

### Consequência de não resolver
- Sistema não pode ser considerado enterprise ready
- Incapacidade de garantir SLA
- Riscos em ambiente de produção

### Evidências observadas
- TKT-014, TKT-015, TKT-016 no backlog: request_id, métricas por tenant, SLI/SLO
- Score F3 está em 60/100 com observabilidade como gap principal

---

## Dor 5: Gap entre Frontend e Backend Documentado

### Quem sofre
- Usuários operadores
- Time de frontend
- Time de backend

### Quando ocorre
- Quando frontend mostra informações que backend não suporta
- Quando documentação promete recursos que código não entrega
- Quando testes e runtime divergem

### Frequência
- Contínua — documentaćão extensa mas não auditada contra código

### Impacto
- **Erro:** Decisões baseadas em documentação desatualizada
- **Experiência:** Usuários encontram funcionalidades quebradas ou diferentes do esperado
- **Confiança:** Desconfiança na documentação do sistema

### Consequência de não resolver
- Dificuldade de onboarding para novos membros
- Riscos em atualizações e manutenções
- Inconsistência entre ambientes

### Evidências observadas
- 0026-mapa-de-aderencia-ao-guia.md reconhece necessidade de validação entre docs e código
- Suíte de testes principal (`pytest -q`) validada, mas documentação pode estar desatualizada

---

## Perguntas Obrigatórias — Respondidas

### "Isso acontece sempre ou pontualmente?"
- Dataset: Sempre (bloqueia todos os gates)
- Auth: Sempre (operação diária prejudicada)
- Features pendentes: Pontual (quando decisões precisam ser tomadas)
- Observabilidade: Sempre em produção
- Gap documentação: Sempre (documentação não reflete estado real)

### "Isso impacta operação ou só percepção?"
- Dataset: Impacta operação real (impossibilita gates)
- Auth: Impacta operação real (segurança e isolamento)
- Features pendentes: Percepção de roadmap inflado
- Observabilidade: Impacta operação em produção
- Gap documentação: Impacta operação e percepção

### "Isso gera prejuízo real?"
- Dataset: Sim — impede decisões de investimento
- Auth: Sim — risco de segurança e isolamento comprometido
- Features pendentes: Sim — planejamento incorreto
- Observabilidade: Sim — incapacidade de garantir SLA
- Gap documentação: Sim — retrabalho e desconfiança

---

## Próximo Passo

Avançar para Contexto Operacional (0002_contexto_operacional.md)