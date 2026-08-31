# Relatório Técnico: Módulo cvg_agent_professor

Este relatório apresenta uma análise crítica do módulo `cvg-agent-professor` desenvolvido para substituir o workflow n8n "Professor RAG + Lock + Fallback".

## 1. Visão Geral
O módulo é um microsserviço Standalone construído em **Node.js (v22)** com **Fastify**, **TypeScript** e **Docker**. Ele replica a lógica de orquestração de Agentes, RAG (Retrieval-Augmented Generation) e controle de fluxo (Gates/Locks) que existia no n8n.

## 2. Qualidades (Pontos Fortes)

### 2.1. Arquitetura Robusta e Moderna
- **Stack Tecnológico**: O uso de Fastify e TypeScript garante alta performance (baixo overhead) e segurança de tipos, prevenindo erros comuns em tempo de desenvolvimento.
- **Separação de Responsabilidades**: O código está bem organizado em:
  - `src/core`: Lógica de negócio pura (Agentes, Gates, Fluxo).
  - `src/lib`: Integrações externas (OpenAI, Qdrant, Redis, Telegram).
  - `src/routes`: Entrada de dados (Webhooks).
  - Isso facilita muito a manutenção e testes futuros comparado ao "spaghetti visual" de fluxos complexos no n8n.

### 2.2. Replicação Fiel da Lógica de Negócio
- **Pipeline RAG Completo**: O módulo implementa fielmente os passos críticos:
  1. **Locking**: Previne condições de corrida usando Redis.
  2. **Preprocessing**: Normaliza a pergunta e detecta intenção.
  3. **Evidence Gating**: Avalia matematicamente a relevância do contexto (Qdrant) antes de acionar o agente clínico.
  4. **Planner & Clinical Agent**: Separação clara entre quem "planeja" a resposta e quem a "escreve", garantindo fidelidade técnica.
  5. **Fallback**: Mecanismo de segurança para perguntas fora do contexto.

### 2.3. Independência e Portabilidade
- **Docker First**: O `Dockerfile` multistage garante que a imagem final seja leve (Alpine Linux) e pronta para produção sem depender de ferramentas de CI/CD externas complexas.
- **Configuração via Variáveis**: Todo o comportamento (URLs, Chaves, Portas) é controlado por variáveis de ambiente (`src/config.ts`), seguindo as práticas do 12-Factor App.

### 2.4. Prompts Centralizados
- Todos os "System Prompts" complexos do JSON original foram extraídos e centralizados em `src/core/prompts.ts`. Isso permite ajustar a "personalidade" ou regras dos agentes sem mexer na lógica do código.

## 3. Defeitos e Pontos de Atenção (Pontos Fracos)

### 3.1. Ausência de Memória Conversacional (Critical)
- **O Problema**: No n8n, havia um nó `Redis Chat Memory` (LangChain) que injetava automaticamente o histórico da conversa no contexto do LLM.
- **Na Versão Atual**: O código atual é **stateless** (sem estado). Ele processa apenas a pergunta atual (`originalQuestion`). Se o usuário disser "explique melhor o item 2", o bot não saberá o que foi o "item 2".
- **Impacto**: Perda da capacidade de manter um diálogo contínuo.

### 3.2. Modelos de IA Hardcoded
- **O Problema**: O código utiliza strings literais como `'gpt-4.1-mini'` e `'gpt-5-mini'` (copiados do JSON).
- **Risco**: Esses modelos muito provavelmente não existem na API pública da OpenAI (são aliases internos ou placeholders). Isso causará erro 400/404 na chamada da API se não forem substituídos por modelos reais (`gpt-4o`, `gpt-4o-mini`).

### 3.3. Simplificação de Tratamento de Texto
- **O Problema**: O fluxo original do n8n possuía lógicas complexas de Regex e splitting para o Telegram (Node 17).
- **Na Versão Atual**: A lógica foi simplificada. Embora funcional para a maioria dos casos, pode falhar em formatações muito específicas (Markdown malformado) que o n8n tratava com mais robustez via nós dedicados.

### 3.4. Observabilidade Limitada ("Fire and Forget")
- **O Problema**: O webhook responde `200 OK` imediatamente e processa em background. Se ocorrer um erro crítico (ex: Redis fora do ar), o erro é logado no console (`console.error`), mas não há um mecanismo nativo de alerta ou retentativa (Retry) automática como o n8n oferece.

## 4. Recomendações
1. **Implementar Memória**: Adicionar uma etapa no `processor.ts` para ler/gravar as últimas 10 mensagens no Redis e incluí-las no prompt do Agente Clínico.
2. **Revisar Modelos**: Alterar os nomes dos modelos em `processor.ts` ou mapeá-los via variáveis de ambiente para garantir que funcionem com a API da OpenAI.
3. **Melhorar Logs**: Integrar uma ferramenta de monitoramento ou estruturar melhor os logs para facilitar o debug em produção.

---
**Conclusão**: O módulo é uma base sólida e profissional, muito superior ao n8n em termos de manutenibilidade e performance, mas requer a implementação da gestão de memória conversacional para atingir paridade total de funcionalidades.
