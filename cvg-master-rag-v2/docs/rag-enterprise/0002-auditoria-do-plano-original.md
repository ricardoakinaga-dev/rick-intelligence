# 0002 — Auditoria do Plano Original

## Objetivo

Auditar cada item do plano original (`../plano-rag-premium-enterprise.md`), classificando-o em: **MANTER AGORA**, **ADIAR**, **CORTAR**, ou **REPROJETAR**. Identificar inconsistências, superdimensionamentos e premissas inválidas.

---

## Roteiro de Auditoria

Para cada item do plano original, avaliar:
- ✅ Qual o problema real que resolve?
- ❌ O que foi inflado ou antecipado indevidamente?
- 📋 Qual a classificação correta?
- 💬 Justificativa

---

## 1. INGESTÃO — AUDITORIA

### 1.1 Document Service (upload, conversão JSON, MinIO)

**Original:** "Converte todos para JSON estruturado, salva no MinIO"

**Análise:**
- MinIO como storage S3-compatible éprematura. Blob local ou simples filesystem é suficiente para Fase 0.
- A ideia de salvar JSON intermediário para evitar re-upload é boa, mas complica a arquitetura cedo demais.
- Funcionalidade útil, mas não essencial para validar núcleo.

**Classificação:** REPROJETAR
**Motivo:** Manter a lógica de salvar texto extraído para reutilização em testes, mas usar storage simples (filesystem local ou MinIO apenas em produção). Na Fase 0, JSON em disco é suficiente.

**Decisão:**
- Extrair texto e salvar JSON em disco (não MinIO ainda)
- MinIO entra na Fase 1 quando houver múltiplos serviços acessando

---

### 1.2 Suporte a múltiplos formatos (PDF, DOCX, XLSX, TXT, MD)

**Análise:**
- XLSX e tabelas são signficativamente mais complexos que PDF/DOCX/MD/TXT
- Planilhas exigem parsing tabular específico (cabeçalhos, linhas, células mescladas)
- O plano trata todos os formatos como "a mesma coisa"
- É o erro mais crítico da ingestion quality

**Classificação:** REPROJETAR

**Decisão para Fase 0:**
- Manter: PDF, DOCX, MD, TXT (parsing textual direto)
- Adiar: XLSX, PPT, HTML (rich content)
- Cortar por ora: tabelas complexas com células mescladas, nested structures

**Justificativa:** Validar com documentos textuais primeiro. Planilhas exigem pipeline diferente.

---

### 1.3 Metadados por documento

**Análise:** Essencial, mas o plano original não define schema de metadados com clareza.

**Classificação:** MANTER AGORA

**Decisão:** Definir contrato mínimo de metadados desde a Fase 0 (owner_id, document_id, source_type, page_count, created_at, chunk_count)

---

## 2. CHUNKING — AUDITORIA

### 2.1 Recursive Chunking

**Original:** "chunk_size 1000, overlap 200, olha parágrafos"

**Análise:** A estratégia mais robusta, mais testada, mais previsível. Boa como baseline inicial.

**Classificação:** MANTER AGORA ✅

**Justificativa:** É o chão firme. Funciona bem em Fase 0. Benchmark baseline. Não precisa de LLM.

---

### 2.2 Semantic Chunking (LangGraph)

**Análise:** Usa biblioteca "experimental" do LangGraph. Funcionalidade instável. Dependência extra. Performance aceitável, mas não essencial.

**Classificação:** ADIAR

**Decisão:** Entra na Fase 2, não na Fase 0. Primeiro provamos que recursive é insuficiente com dados reais.

---

### 2.3 Page by Page (PDF Only)

**Análise:** Funciona para contratos e documentos jurídicos, mas PDF-only limita generalização. Requer número de páginas do PDF.

**Classificação:** ADIAR

**Decisão:** Entra na Fase 2 quando tivermos dataset de documentos jurídicos.

---

### 2.4 Agentic Chunking (LLM como chunker)

**Original:** "Ferrari do chunking", usa GPT-4o-mini com prompt profissional, overlap 800, chunks 500-1000 caracteres

**Análise:** 
- É a estratégia mais cara e mais lenta
- Requer prompts complexos e validação de saída
- Funciona muito bem, mas é carroceria para validated dataset
- O plano original tenta usar como padrão de saída, mas deveria ser comparação após baseline

**Classificação:** REPROJETAR

**Decisão:**
- Cortar de Fase 0 e 1 (custo/benefício não justificado)
- Entra na Fase 2 como opção premium, não padrão
- Usar apenas para documentos que recursive NÃO conseguiu cobrir (validação A/B)

---

## 3. RETRIEVAL — AUDITORIA

### 3.1 Busca Híbrida (Dense + Sparse + RRF Fusion)

**Original:** Vetor denso (OpenAI) + Vetor esparso (BM25 via Qdrant) + RRF para fundir rankings

**Análise:** 
- É o diferencial real do sistema
- Funcionalidade central, não decorations
- RRF é matematicamente simples e bem estabelecido
- Decisione: manter, mas implementar simples antes de sofisticar

**Classificação:** MANTER AGORA ✅

**Decisão:** Implementar RRF simples em Fase 0. RRF avançado entra na Fase 2.

---

### 3.2 Reranking (Cohere rerank-3)

**Análise:**
- Cohere é serviço externo (custo variável, dependência de API externa)
- Reranking de 20 → 5 candidatos é recurso real, mas Fase 0 pode viver sem se o threshold for bem calibrado
- O plano original coloca reranking como "obrigatório", mas com top-5 bem configurado e threshold 0.70, o RRF sozinho já entrega bem

**Classificação:** ADIAR (Fase 1)

**Decisão:**
- Fase 0: usar RRF para top-5, sem reranker externo
- Fase 1: adicionar Cohere rerank se hit rate top-5 for < 80%

---

### 3.3 HyDE (Hypothetical Document Embeddings)

**Original:** Gera resposta hipotética via GPT-5.1 para fazer busca melhor. Fallback se score < 0.85.

**Análise:**
- Hide é poderoso, mas caro (2 chamadas de LLM por query)
- O plano original já sugere "só entra se score < 0.85", mas não explica como avaliar isso sem circularidade
- Hide funciona bem para perguntas técnicas com terminologia específica
- Não é necessário para consultas simples

**Classificação:** REPROJETAR

**Decisão:**
- Cortar de Fase 0 (custo alto, benefício não comprovado)
- Adiar para Fase 2 com threshold configurável por empresa
- Critério de entrada: evidência real de ganho em Retrieval Quality nos dados do cliente

---

### 3.4 Web Search

**Análise:** Funcionalidade útil, mas cria dependência de provedor de busca, complica pipeline e adiciona latência. Só faz sentido quando o RAG core estiver funcionando bem.

**Classificação:** ADIAR (Fase 2 ou 3)

**Decisão:** Não entra antes de HyDE estar validado.

---

## 4. EVALUATION — AUDITORIA

### 4.1 Evaluation Service (por documento)

**Original:** Gera perguntas via GPT-5.1, recupera chunks, LLM as Judge julga se resposta está correta, percentuais de acerto.

**Análise:**
- LLM as Judge como ÚNICA fonte de verdade é problema metodológico sério
- Perguntas sintéticas geradas pelo mesmo modelo que julga criam viés circular
- Avaliação por documento é boa ideia, mas precisa de revisão humana ou dataset real

**Classificação:** REPROJETAR

**Decisão:**
- Fase 0: avaliação manual ou semi-automatizada com perguntas reais do dataset
- Fase 1: apoio de LLM Judge para triagem, não como veredicto final
- LLM Judge nunca é "fonte única da verdade"

---

### 4.2 Benchmark Service (12 cenários: 4 chunkings × 3 retrievals)

**Original:** "Roda 12 cenários, define estratégia vencedora, apaga collection temporária"

**Análise:**
- É a sofisticação mais prematura do plano
- Rodar 12 cenários com todos os documentos é Caro (API calls) e Lent (minutos)
- A decisão "estratégia vencedora para todos os documentos" ignora que diferentes tipos de documento podem Performar melhor com estratégias diferentes
- A automatização completa do benchmark como "fonte de verdade" é perigosa

**Classificação:** CORTAR (Fase 0 e 1)

**Decisão:**
- Fase 0: benchmark manual simples (perguntas reais, análise humana)
- Fase 2: benchmark controlado (3-5 perguntas, 4 estratégias, análise de resultado)
- Não automatizar benchmark completo antes de ter dataset real validado

---

### 4.3 LLM as Judge — Avaliação de groundedness

**Análise:**
- LLM Judge é ferramenta útil para triagem, mas tem viés estrutural
- Não pode ser usado como fonte única de verdade
- Quando usado corretamente (revisão humana em cima de sugestões), é valioso
- Quando usado como veredicto automático, gera falsos positivos/negativos

**Classificação:** REPROJETAR

**Decisão:** Usar como apoio (triagem), não como veredicto. Revisão humana obrigatória para validação de gate.

---

## 5. ARQUITETURA — AUDITORIA

### 5.1 Stack tecnológica (Next.js, Supabase, MinIO, Qdrant, LangGraph, FastAPI)

**Análise:**
- Next.js + Supabase para admin e chat é escolha razoável
- MinIO cedo demais (Fase 0 não precisa de S3-compatible storage)
- LangGraph para orquestração é "canhão para matar mosca" em Fase 0
- FastAPI é escolha correta para backend

**Classificação:** REPROJETAR

**Decisão:**
- Fase 0: FastAPI (Python) + Qdrant + filesystem local
- Fase 1: adicionar Supabase se necessário para auth/admin
- Fase 2: MinIO quando houver necessidade real de storage compartilhado
- LangGraph: ADIAR para Fase 2 no mínimo. Em Fase 0, router pode ser código simples.

---

### 5.2 Arquitetura de microserviços

**Análise:**
- O plano original sugere arquitetura de microserviços "desde o início"
- Isso cria complexidade operacional, comunicação inter-processo, problemas de deployment
- Nenhuma necessidade de negócio justifica microserviços em Fase 0
- Modular Monolith é a escolha correta inicial

**Classificação:** CORTAR

**Decisão:**
- Fase 0: Modular Monolith ( FastAPI com módulos separados por responsabilidade)
- Fase 2: separar serviços se e somente se houver necessidade real de scaling independente
- Microserviços reais só na Fase 3 se validado

---

### 5.3 Multitenancy

**Análise:**
- Multitenancy completo no plano original inclui: cadastro de empresas, configurações por empresa, white label, isolamento de dados, permissões
- É feature de produto maduro, não de MVP
- Adiantar multitenancy antes de ter "1 tenant usando bem" é desperdício

**Classificação:** ADIAR

**Decisão:**
- Fase 0: single tenant, dados segregados por workspace_id (preparado para multi)
- Fase 2: configuração multi-empresa básica (sem white label)
- Fase 3: multitenancy real com isolamento e white label

---

## 6. AUDIO E WEB SEARCH

### 6.1 Audio (FasterWhisper)

**Análise:** Funcionalidade complementar, não é core do RAG. Audio entra no pipeline deinput, mas não deve bloquear validação do núcleo retrieval.

**Classificação:** ADIAR (Fase 1 ou 2)

**Decisão:** Não entra antes de retrieval estar funcional e medido.

---

### 6.2 Web Search

**Classificação:** ADIAR (Fase 2 ou 3)

**Decisão:** Só depois do core RAG estar validado com métricas reais.

---

## 7. PAINEL ADMIN E FRONTEND

### 7.1 Painel Admin completo

**Análise:**
- Cadastro de empresas, aprovações, logs, configurações de agente, dashboard
- É feature de operação e uso, não de validação técnica
- Não bloqueia a validação do núcleo (retrieval working)

**Classificação:** ADIAR (Fase 1 para admin básico, Fase 3 para admin completo)

**Decisão:**
- Fase 0: sem admin panel (ou CLI/script simples para upload de docs)
- Fase 1: admin mínimo para upload e acompanhamento de métricas
- Fase 2: dashboard básico de retrieval
- Fase 3: admin completo com logs, config de agente, etc.

---

### 7.2 White Label

**Classificação:** ADIAR (Fase 3)

**Decisão:** Não entra antes de multitenancy estar funcionando.

---

## RESUMO DA AUDITORIA

| Item do Plano Original | Classificação | Justificativa |
|---|---|---|
| Document Service (MinIO) | REPROJETAR | Storage simples é suficiente na Fase 0 |
| PDF/DOCX/MD/TXT parsing | MANTER AGORA | Core essencial |
| XLSX/tabelas complexas | ADIAR | Complexidade diferente, validar texto primeiro |
| Metadados por documento | MANTER AGORA | Essencial para segregação futura |
| Recursive Chunking | MANTER AGORA | Baseline sólido, sem custo adicional |
| Semantic Chunking | ADIAR | Experimental, entra após baseline validado |
| Page by Page | ADIAR | Só para jurídico após dataset validar |
| Agentic Chunking | REPROJETAR → ADIAR FASE 2 | Custo alto, benefício não provado ainda |
| Busca Híbrida (Dense+Sparse+RRF) | MANTER AGORA | Core do diferencial |
| Reranking (Cohere) | ADIAR (FASE 1) | Útil mas não crítico em Fase 0 |
| HyDE | REPROJETAR → ADIAR FASE 2 | Custo 2x LLM, benefício não comprovado |
| Web Search | ADIAR (FASE 2/3) | Só depois do core validar |
| Evaluation por documento | REPROJETAR | Não usar LLM Judge como fonte única |
| Benchmark 12 cenários | CORTAR (FASE 0/1) | Prematura, cara, potentially misleading |
| LLM as Judge | REPROJETAR | Usar como triagem, não como veredicto |
| FastAPI | MANTER AGORA | Escolha correta |
| LangGraph | ADIAR (FASE 2+) | Canhão para matar mosca em Fase 0 |
| Microserviços | CORTAR (FASE 0) | Modular Monolith é suficiente |
| Next.js + Supabase | ADIAR (FASE 1+) | Não bloqueia validação do núcleo |
| MinIO | ADIAR (FASE 2+) | Não necesario em Fase 0 |
| Multitenancy | ADIAR (FASE 3) | Validar 1 tenant primeiro |
| White Label | ADIAR (FASE 3) | Depende de multitenancy |
| Audio (Whisper) | ADIAR (FASE 1/2) | Não é core RAG |
| Admin Panel completo | ADIAR (FASE 1+/3) | Não bloqueia validação técnica |
| Dataset real | MANTER AGORA (CRÍTICO) | Nenhum benchmark é válido sem isso |

---

## Problemas Estruturais Identificados

1. **Circularidade de validação**: LLM gerando perguntas e julgando respostas
2. **Equivalência falsa de formatos**: PDF/DOCX ≠ XLSX em complexidade
3. **Benchmark como oráculo**: 12 cenários automáticos não garante qualidade real
4. **Arquitetura distribuída antecipada**: microserviços sem necessidade operacional
5. **Features para "possível futuro"**: multitenancy, white label, sem validação de uso real
6. **Confusão entre demo técnica e produto**: rodar local != produção escalável

---

## Próximo Passo

Ir para `0003-estrategia-de-fases.md` — onde as fases são definidas com escopo, gates e critérios objetivos.