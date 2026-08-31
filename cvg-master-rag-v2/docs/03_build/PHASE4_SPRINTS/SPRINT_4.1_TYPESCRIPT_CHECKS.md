# PHASE 4 — SPRINT 4.1: TypeScript Checks

## Objetivo
Garantir que todos os checks TypeScript passem (tsc --noEmit).

## Escopo
- TypeScript configuration
- Type annotations
- Error resolution
- CI/CD integration

## Tasks

### Task 4.1.1: TypeScript Configuration
**O QUE:** Configurar tsconfig.json corretamente
**ONDE:** tsconfig.json
**COMO:** Configurar strict mode, paths, includes
**DEPENDÊNCIA:** Sprint 0.4 (Telemetry)
**CRITÉRIO DE PRONTO:** tsc --noEmit executa sem erro de config

### Task 4.1.2: Type Annotations
**O QUE:** Adicionar anotações de tipo onde faltam
**ONDE:** src/*/*.py (se Python) ou src/*/*.ts (se TypeScript)
**COMO:** Adicionar tipos explícitos a funções e variáveis
**DEPENDÊNCIA:** Task 4.1.1
**CRITÉRIO DE PRONTO:** Código sem types any implícitos

### Task 4.1.3: Type Error Resolution
**O QUE:** Resolver erros de tipo identificados
**ONDE:** src/
**COMO:** Corrigir tipos inconsistentes
**DEPENDÊNCIA:** Task 4.1.2
**CRITÉRIO DE PRONTO:** tsc --noEmit passa 100%

### Task 4.1.4: CI Integration
**O QUE:** Integrar tsc --noEmit no CI pipeline
**ONDE:** .github/workflows/ci.yaml
**COMO:** Step de type check no workflow
**DEPENDÊNCIA:** Task 4.1.3
**CRITÉRIO DE PRONTO:** CI falha se TypeScript check falhar

## Riscos
- Nenhum identificad

## Critérios de Validação
- [ ] tsconfig.json configurado
- [ ] Anotações de tipo completas
- [ ] tsc --noEmit passa
- [ ] CI integration working

## Status
⚪ PENDENTE