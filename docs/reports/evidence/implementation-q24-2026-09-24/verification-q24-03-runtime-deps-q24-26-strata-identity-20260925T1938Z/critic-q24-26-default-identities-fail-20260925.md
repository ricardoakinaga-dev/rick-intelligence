# Revisão independente — defaults de identidade e projeções v4

**Veredito:** `FAIL` válido para o snapshot v4 revisado.  
**Revisor:** Halley; revisão independente I1, contexto não herdado (`fork_context=false`), leitura somente, escopo reduzido e selado.

## Integridade da revisão

O fingerprint do candidato foi `09b915e4b508258fcf9f6f4db010d562706fbe5fcc451056bb0b4dcf38b1aa4a` antes e depois. O sentinel permaneceu `a5674ea84d6db1fa53961692fe5da1a16c720caf2b1857c2ee1c1bc62cdf85f6`. O revisor declarou que não executou testes e não escreveu arquivos. Nenhuma mutação foi detectada.

## Achados

1. **Médio — defaults do manifesto do pack não chegavam às estratificações da campanha.** `evaluate_pack` resolve `model_id`/`corpus_id` ausentes pelos defaults de `pack_manifest.metadata`, enquanto `_collect_strata` e `_quality_by_strata` exigiam os campos nos metadados de cada caso. Um pack válido que declare os IDs somente no manifesto falhava antes de produzir estratos, linhas de qualidade e incerteza por estrato. Os testes anteriores cobriam somente IDs explícitos por caso.
2. **Baixo — strings não vazias formadas só por espaços eram rejeitadas.** Os validadores usavam `value.strip()` para decidir se o ID ou rótulo estava vazio, embora preservassem os espaços em outros casos.
3. **Baixo — a documentação não dizia que `uncertainty.overall` é agregado.** A frase “Hit@1 intervals use the same grouping” podia incluir a visão `overall`, que agrega todos os casos positivos.

O revisor não encontrou colisão nos IDs para strings explícitas aceitas: os componentes são escapados separadamente e a dimensão canônica é codificada sem perda. Também confirmou que o JSON sintético limita corretamente suas alegações e mantém campanha `NOT_RUN` / elegibilidade `BLOCKED`.

## Tratamento

O campaign evaluator agora herda IDs ausentes dos defaults do manifesto e preserva qualquer string não vazia, inclusive identidade/rótulo composto somente por espaços. Uma regressão de integração cobre default do pack, ID e rótulo `" "` nas estratificações e projeções de incerteza. A documentação distingue `uncertainty.overall` agrupado de `by_model_corpus` e `by_quality_stratum`. Evidência pós-correção aguarda uma nova revisão independente.
