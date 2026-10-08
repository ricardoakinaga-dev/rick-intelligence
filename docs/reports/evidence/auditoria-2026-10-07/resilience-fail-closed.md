# Evidência de correção — `production_safe` fail-closed (AUD07-14)

**Data:** 2026-10-07. **Candidato:** worktree de `/home/ricardo/rick-intelligence`,
`HEAD = b52f32c141916a2ea3af1a6b913bd91f380606e0` (*Record alternate Docker endpoint probe*).
**Ambiente:** Python 3.12.3 (`.runtime/venvs/cvg`), Node v24.20.0 / npm 11.19.0 no host.
**Achado de origem:** A16 (*`production_safe` defaulta a `True` sem probe*). **Continuação:**
[`fix-gates-1.md`](fix-gates-1.md) (M0), [`fix-gates-2.md`](fix-gates-2.md) (AUD07-10…12) e
[`route-policy.md`](route-policy.md) (AUD07-13). Encerra **M1**.

## 1. Problema

Dois fail-opens no mesmo wrapper
(`packages/providers/src/rick_providers/resilience.py`):

1. `self.production_safe = getattr(provider, "production_safe",
   self.is_test_provider is not True)` — a **ausência** de declaração valia `True`.
   Um port customizado sem probe, sem teste e sem qualquer decisão explícita era
   classificado como seguro para produção.
2. `health_check()` retornava `self.readiness_check()` quando o portado não expunha
   `health_check` — circuito fechado passava a ser lido como *reachability*. Um
   provider injetável que nunca respondeu à rede era reportado saudável.

A composição oficial já resiste a (2) no nível do cliente
(`OpenAICompatibleClient.health_check` → `GET {base}/models` autenticado, e
`AnthropicMessagesClient` herda o mesmo caminho), mas nada impedia (1) nem o
fallback em ports fora da composição revisada.

## 2. O que mudou

### `packages/providers/src/rick_providers/resilience.py`

| Símbolo | Papel |
|---|---|
| `ResilientProvider._production_safe(provider)` | regra de admissão: `is_test_provider is True` ⇒ `False`; declaração explícita `True`/`False` vence; sem declaração ⇒ `True` **somente** se houver `health_check` chamável |
| `self.production_safe = self._production_safe(provider)` | substitui o `getattr(..., default=True)` |
| `health_check()` | sem probe ⇒ `False` (era `readiness_check()`); com probe ⇒ delega, preservando cancelamento e `result is True` |
| `readiness_check()` | **inalterado** — continua sendo o sinal barato local, para quem explicitamente o quer |

Contrato documentado em `docs/architecture/provider-resilience.md` (seção de admissão).

### Testes

| Arquivo | Mudança |
|---|---|
| `packages/providers/tests/test_resilience.py` | `test_resilient_provider_falls_back_to_local_readiness_without_live_hook` ⇒ `test_resilient_provider_fails_closed_without_a_live_probe` (`health_check` **False**, `readiness_check` **True**); novo `test_production_safe_requires_a_probe_or_an_explicit_declaration` (sem probe/sem declaração ⇒ False, só probe ⇒ True, declaração explícita nos dois sentidos, port de teste ⇒ False); novo `test_the_official_client_is_admitted_through_its_own_probe` |
| `apps/api/tests/test_external_composition.py` | dois testes de **admissão da composição**, não só do wrapper: `test_composition_admits_the_official_provider_through_its_live_probe` (`production_safe` True + `health_checks["provider"]()` True com `/models` respondendo o modelo configurado) e `test_composition_refuses_a_provider_port_without_a_probe` (factory injetado devolve `SyntheticPort` sem probe ⇒ `production_safe` False **e** o check de prontidão registrado pela composição False) |

## 3. Discriminação (a nova checagem falha sem a correção)

Script: `/tmp/opencode/discriminate_a16.sh` — regrava as duas linhas originais em
`resilience.py`, roda `test_resilience.py` + `test_external_composition.py`,
restaura e verifica o sha256.

| Experimento | Mudança | exit | Resultado |
|---|---|---|---|
| [`exp-a16.txt`](discrimination/exp-a16.txt) | `production_safe` volta a defaultar `True` sem probe e `health_check` volta a cair para `readiness_check()` | 1 | **3 falharam**, 20 passaram — os dois testes novos do wrapper e o de admissão da composição |
| [`control-a16.txt`](discrimination/control-a16.txt) | restauração verificada por hash | 0 | **23 passaram**, 0 falharam |

## 4. Gates

| Gate | exit | Resultado |
|---|---|---|
| `make test` | 0 | 7 linhas `<==` — pacotes/API/diferencial, worker **734**, validadores/runner **472** |
| `make api-test` | 0 | **1704 passed, 18 skipped** (+2) |
| `make ci` | 0 | 17 linhas `<==` |
| `make validate` | 0 | — |
| `make test-fast` | 0 | 14 + 26 passed |
| `make api-security` | 0 | **181 passed** |
| `make ops-static` | 0 | **298 passed** |
| `make api-contract` | 0 | OpenAPI 55 paths |
| `make compose-static` | 0 | 16 serviços × 2 arquivos |
| `make lint` / `make typecheck` | 0 | ESLint, `tsc --noEmit`, `compileall` |

Nenhuma suíte reduzida; nenhum teste ignorado.

## 5. Limites

- Uma declaração explícita `production_safe = True` **sem** probe é aceita por
  decisão de política (é a "marca explícita de produção" do aceite), não por
  herança silenciosa: quem a escreve é o dono do port. A prova de que um provider
  está de fato vivo em produção continua sendo o Phase 11 *provider runtime gate*
  (TLS, chave e `/models` ao vivo), que calcula `production_safe` de forma
  independente deste wrapper.
- O fallback de `health_check()` afeta qualquer port sem probe já registrado na
  composição; os dois providers oficiais têm probe e o port de teste
  (`DeterministicProvider`) já declarava `production_safe = False`. Compositions
  de teste que dependiam do fallback agora reportam `provider` não-saudável — o
  comportamento correto, e nenhum gate da lista acima passou a falhar por isso.
- Fora de escopo: adicionar `health_check` ao `DeterministicProvider` e o
  inventário de skips (A17).
