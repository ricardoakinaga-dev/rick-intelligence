SHELL := /usr/bin/env bash

ROOT := $(CURDIR)
PYTHON ?= python3
PHASE11_RUNNER := $(ROOT)/scripts/phase11/runner.py
PHASE11_CHECK := $(ROOT)/scripts/phase11/check_skeleton.py
PHASE13_RUNNER := $(ROOT)/scripts/phase13/phase13.py
PHASE131_RUNNER := $(ROOT)/scripts/phase13/phase131.py
PHASE14_RUNNER := $(ROOT)/scripts/phase13/phase14.py
WEB_DIR := $(ROOT)/apps/web
WEB_CURRENT_EVIDENCE_DIR := $(ROOT)/.gauntlet-state-of-art/evidence/visual-cycle5-current

.DEFAULT_GOAL := help

.PHONY: help bootstrap validate quality-bar-static dev test test-fast test-integration lint typecheck build up down logs ci eval eval-retrieval eval-retrieval-pack security-adversarial storage-test ops-migration-check ops-static compose-static postgres-runtime phase3-postgres-runtime multi-worker-runtime phase3-multi-worker-runtime redis-multi-replica-runtime phase3-redis-multi-replica-runtime phase3-redis-runtime phase3-object-qdrant-runtime redis-runtime object-qdrant-runtime provider-runtime phase3-provider-runtime golden-runtime phase3-golden-runtime provider-rag-runtime tenant-evidence-runtime phase3-tenant-evidence-runtime observability-runtime phase3-observability-runtime frontend-supply-runtime phase3-frontend-supply-runtime restore-runtime phase3-restore-runtime file-security-runtime phase3-file-security-runtime triple-aaa-verify ops-backup-test jobs-test release-evidence phase3-evidence phase3-evidence-verify phase3-performance phase3-chaos phase3-soak web-install web-lint web-typecheck web-build web-e2e web-validate api-dev api-test api-contract api-security api-benchmark api131-canonical api131-differential api131-full api131-benchmark api14-units api14-differential api14-acl api14-full api14-benchmark api15-contracts api15-provider api15-lock api15-professor api15-root api15-benchmark api15-verify api15-full api15-boundaries api16-domain api16-worker api16-root api16-benchmark api16-full api16-verify

help:
	@printf '%s\n' 'RICK Intelligence root commands:'
	@printf '%s\n' '  make bootstrap        prepare preserved runtimes and lockfile installs'
	@printf '%s\n' '  make validate         verify skeleton, contracts, boundaries, and history'
	@printf '%s\n' '  make dev              guarded canonical development compose lifecycle'
	@printf '%s\n' '  make test-fast        focused preserved-component regression checks'
	@printf '%s\n' '  make test             all available component tests and frontend smoke'
	@printf '%s\n' '  make test-integration disposable loopback integration probes'
	@printf '%s\n' '  make lint             root/static/frontend lint checks'
	@printf '%s\n' '  make typecheck        TypeScript compiler and Python compilation checks'
	@printf '%s\n' '  make build            preserved Professor/frontend/Python build checks'
	@printf '%s\n' '  make up|down|logs     guarded dev compose lifecycle; up writes the shared Phase 3 preflight'
	@printf '%s\n' '  make ci               validate + fast tests + lint + typecheck + build'
	@printf '%s\n' '  make eval             deterministic non-live Phase 0.5 plumbing evaluation'
	@printf '%s\n' '  make eval-retrieval   offline retrieval/ACL/provenance evaluation fixture'
	@printf '%s\n' '  make eval-retrieval-pack  versioned local thresholds and negative-case pack'
	@printf '%s\n' '  make security-adversarial validate the bounded synthetic RAG attack corpus'
	@printf '%s\n' '  make storage-test     local object-store security and restart tests'
	@printf '%s\n' '  make ops-static       migration/env/runbook static checks (no services)'
	@printf '%s\n' '  make compose-static   render both canonical Compose topologies without starting services'
	@printf '%s\n' '  make postgres-runtime run the real PostgreSQL migration/queue gate from RICK_TEST_DATABASE_DSN'
	@printf '%s\n' '  make phase3-postgres-runtime emit commit-bound PostgreSQL runtime evidence'
	@printf '%s\n' '  make multi-worker-runtime run the real two-process worker fencing gate'
	@printf '%s\n' '  make phase3-multi-worker-runtime emit commit-bound worker evidence'
	@printf '%s\n' '  make redis-runtime run the real Redis lease/rate-limit gate from RICK_TEST_REDIS_URL'
	@printf '%s\n' '  make redis-multi-replica-runtime run the real two-process Redis bucket gate'
	@printf '%s\n' '  make phase3-redis-multi-replica-runtime emit commit-bound multi-replica Redis evidence'
	@printf '%s\n' '  make phase3-redis-runtime emit commit-bound Redis runtime evidence'
	@printf '%s\n' '  make object-qdrant-runtime run the real object/vector gate from explicit test URLs'
	@printf '%s\n' '  make phase3-object-qdrant-runtime emit commit-bound object/vector runtime evidence'
	@printf '%s\n' '  make provider-runtime run the real OpenAI-compatible chat/embedding gate from RICK_TEST_PROVIDER_URL'
	@printf '%s\n' '  make phase3-provider-runtime emit commit-bound provider runtime evidence'
	@printf '%s\n' '  make golden-runtime run the real RICK_GOLDEN_RUNTIME_PATH ingestion/RAG gate'
	@printf '%s\n' '  make phase3-golden-runtime emit commit-bound golden ingestion evidence'
	@printf '%s\n' '  make provider-rag-runtime require both the live provider and golden RAG runtime gates'
	@printf '%s\n' '  make tenant-evidence-runtime run the live multi-tenant/evidence negative matrix'
	@printf '%s\n' '  make phase3-tenant-evidence-runtime emit commit-bound tenant/evidence evidence'
	@printf '%s\n' '  make observability-runtime run the bounded OTel/metrics/SLO gate'
	@printf '%s\n' '  make phase3-observability-runtime emit commit-bound observability evidence'
	@printf '%s\n' '  make frontend-supply-runtime run frontend/accessibility/supply-chain checks'
	@printf '%s\n' '  make phase3-frontend-supply-runtime emit commit-bound frontend/supply evidence'
	@printf '%s\n' '  make restore-runtime run the authorized disposable backup/restore sequence'
	@printf '%s\n' '  make phase3-restore-runtime emit commit-bound restore evidence'
	@printf '%s\n' '  make file-security-runtime run the hostile file corpus in an isolated worker'
	@printf '%s\n' '  make phase3-file-security-runtime emit commit-bound file-security evidence'
	@printf '%s\n' '  make triple-aaa-verify run the fail-closed integrated verification packet'
	@printf '%s\n' '  make release-evidence generate the ignored commit-bound release manifest'
	@printf '%s\n' '  make phase3-evidence generate the ignored Phase 3 capability matrix'
	@printf '%s\n' '  make phase3-evidence-verify require a fully promotable Phase 3 matrix'
	@printf '%s\n' '  make phase3-performance|chaos|soak run explicit fail-closed operational lanes'
	@printf '%s\n' '  make api-dev          run canonical apps/api kernel (hermetic by default)'
	@printf '%s\n' '  make api-test         Phase 1.3 API matrix (routing/auth/errors/health/compat/streaming)'
	@printf '%s\n' '  make api-contract     OpenAPI generation + required-path check'
	@printf '%s\n' '  make api-security     route-policy + negatives + import-boundary checks'
	@printf '%s\n' '  make api-benchmark    kernel-overhead p50/p95 observation (stub backend)'
	@printf '%s\n' '  make api15-full        Phase 1.5 contracts/provider/locking/Professor/root checks'
	@printf '%s\n' '  make api15-verify      Phase 1.5 sanitized full evidence matrix'
	@printf '%s\n' '  make api16-full        Phase 1.6 ingestion/jobs/readiness/root checks'
	@printf '%s\n' '  make api16-verify      Phase 1.6 sanitized regression/evidence matrix'
	@printf '%s\n' '  make web-validate      canonical web lint + typecheck + production build + browser matrix'
	@printf '%s\n' '  make web-e2e           browser smoke at 375/768/1440 with root API loopback'

bootstrap:
	$(PYTHON) "$(PHASE11_RUNNER)" bootstrap

validate:
	$(PYTHON) "$(ROOT)/scripts/phase15/check_boundaries.py"
	PYTHONDONTWRITEBYTECODE=1 $(PYTHON) "$(ROOT)/docs/ci/check_control_plane.py"
	PYTHONDONTWRITEBYTECODE=1 $(PYTHON) "$(ROOT)/scripts/state_of_art/validate_quality_bar.py"

quality-bar-static:
	PYTHONDONTWRITEBYTECODE=1 $(PYTHON) "$(ROOT)/scripts/state_of_art/validate_quality_bar.py"

dev:
	$(PYTHON) "$(PHASE11_RUNNER)" dev

test:
	$(PYTHON) "$(PHASE11_RUNNER)" test

test-fast:
	$(PYTHON) "$(PHASE11_RUNNER)" test-fast

test-integration:
	$(PYTHON) "$(PHASE11_RUNNER)" test-integration

lint:
	$(PYTHON) "$(PHASE11_RUNNER)" lint

typecheck:
	$(PYTHON) "$(PHASE11_RUNNER)" typecheck

build:
	$(PYTHON) "$(PHASE11_RUNNER)" build

up:
	$(PYTHON) "$(PHASE11_RUNNER)" up

down:
	$(PYTHON) "$(PHASE11_RUNNER)" down

logs:
	$(PYTHON) "$(PHASE11_RUNNER)" logs

ci:
	$(PYTHON) "$(PHASE11_RUNNER)" ci

eval:
	$(PYTHON) "$(PHASE11_RUNNER)" eval

eval-retrieval:
	PYTHONDONTWRITEBYTECODE=1 PYTHONPATH="$(ROOT)" $(PYTHON) "$(ROOT)/scripts/state_of_art/evaluate_retrieval.py" --fixture "$(ROOT)/scripts/state_of_art/tests/fixtures/retrieval_fixture.json" --pretty

eval-retrieval-pack:
	PYTHONDONTWRITEBYTECODE=1 PYTHONPATH="$(ROOT):$(ROOT)/scripts/state_of_art" $(PYTHON) "$(ROOT)/scripts/state_of_art/evaluate_pack.py" --pack "$(ROOT)/docs/evaluation/packs/rec22-local-v1" --pretty

security-adversarial:
	PYTHONDONTWRITEBYTECODE=1 $(PYTHON) "$(ROOT)/scripts/phase11/check_adversarial_corpus.py"

storage-test:
	PYTHONDONTWRITEBYTECODE=1 PYTHONPATH="$(ROOT)/packages/storage/src" $(PYTHON) -m pytest -q -p no:cacheprovider "$(ROOT)/packages/storage/tests"

ops-migration-check:
	PYTHONDONTWRITEBYTECODE=1 $(PYTHON) "$(ROOT)/infrastructure/scripts/migrate.py" "$(ROOT)/infrastructure/migrations" --check

ops-static: ops-migration-check
	bash -n "$(ROOT)/infrastructure/scripts/validate-env.sh"
	PYTHONDONTWRITEBYTECODE=1 $(PYTHON) -m py_compile "$(ROOT)/infrastructure/scripts/backup-restore-check.py" "$(ROOT)/infrastructure/scripts/backup_restore.py"

compose-static:
	PYTHONDONTWRITEBYTECODE=1 $(PYTHON) "$(ROOT)/scripts/phase11/check_compose.py"

postgres-runtime:
	PYTHONDONTWRITEBYTECODE=1 PYTHONPATH="$(ROOT)" $(PYTHON) "$(ROOT)/scripts/phase11/postgres_runtime_gate.py"

phase3-postgres-runtime:
	PYTHONDONTWRITEBYTECODE=1 PYTHONPATH="$(ROOT)" $(PYTHON) "$(ROOT)/scripts/state_of_art/run_phase3_postgres.py"

multi-worker-runtime:
	PYTHONDONTWRITEBYTECODE=1 PYTHONPATH="$(ROOT)" $(PYTHON) "$(ROOT)/scripts/phase11/multi_worker_runtime_gate.py"

phase3-multi-worker-runtime:
	PYTHONDONTWRITEBYTECODE=1 PYTHONPATH="$(ROOT)" $(PYTHON) "$(ROOT)/scripts/state_of_art/run_phase3_multi_worker.py"

redis-multi-replica-runtime:
	PYTHONDONTWRITEBYTECODE=1 PYTHONPATH="$(ROOT)/packages/contracts/src:$(ROOT)/packages/locking/src" $(PYTHON) "$(ROOT)/scripts/phase11/redis_multi_replica_runtime_gate.py"

phase3-redis-multi-replica-runtime:
	PYTHONDONTWRITEBYTECODE=1 PYTHONPATH="$(ROOT)" $(PYTHON) "$(ROOT)/scripts/state_of_art/run_phase3_redis_multi_replica.py"

phase3-redis-runtime:
	PYTHONDONTWRITEBYTECODE=1 PYTHONPATH="$(ROOT):$(ROOT)/packages/contracts/src:$(ROOT)/packages/locking/src" $(PYTHON) "$(ROOT)/scripts/state_of_art/run_phase3_redis.py"

phase3-object-qdrant-runtime:
	PYTHONDONTWRITEBYTECODE=1 PYTHONPATH="$(ROOT):$(ROOT)/packages/knowledge/src:$(ROOT)/packages/retrieval/src:$(ROOT)/packages/storage/src" $(PYTHON) "$(ROOT)/scripts/state_of_art/run_phase3_object_qdrant.py"

redis-runtime:
	PYTHONDONTWRITEBYTECODE=1 PYTHONPATH="$(ROOT)/packages/contracts/src:$(ROOT)/packages/locking/src" $(PYTHON) "$(ROOT)/scripts/phase11/redis_runtime_gate.py"

object-qdrant-runtime:
	PYTHONDONTWRITEBYTECODE=1 PYTHONPATH="$(ROOT)/packages/knowledge/src:$(ROOT)/packages/retrieval/src:$(ROOT)/packages/storage/src" $(PYTHON) "$(ROOT)/scripts/phase11/object_qdrant_runtime_gate.py"

provider-runtime:
	PYTHONDONTWRITEBYTECODE=1 PYTHONPATH="$(ROOT)/packages/contracts/src:$(ROOT)/packages/providers/src" $(PYTHON) "$(ROOT)/scripts/phase11/provider_runtime_gate.py"

phase3-provider-runtime:
	PYTHONDONTWRITEBYTECODE=1 PYTHONPATH="$(ROOT)" $(PYTHON) "$(ROOT)/scripts/state_of_art/run_phase3_provider.py"

golden-runtime:
	PYTHONDONTWRITEBYTECODE=1 PYTHONPATH="$(ROOT)" $(PYTHON) "$(ROOT)/scripts/phase11/golden_runtime_gate.py"

phase3-golden-runtime:
	PYTHONDONTWRITEBYTECODE=1 PYTHONPATH="$(ROOT)" $(PYTHON) "$(ROOT)/scripts/state_of_art/run_phase3_golden_runtime.py"

provider-rag-runtime: provider-runtime golden-runtime

tenant-evidence-runtime:
	PYTHONDONTWRITEBYTECODE=1 PYTHONPATH="$(ROOT)" $(PYTHON) "$(ROOT)/scripts/phase11/tenant_evidence_runtime_gate.py"

phase3-tenant-evidence-runtime:
	PYTHONDONTWRITEBYTECODE=1 PYTHONPATH="$(ROOT)" $(PYTHON) "$(ROOT)/scripts/state_of_art/run_phase3_tenant_evidence.py"

observability-runtime:
	PYTHONDONTWRITEBYTECODE=1 PYTHONPATH="$(ROOT)" $(PYTHON) "$(ROOT)/scripts/phase11/observability_runtime_gate.py"

phase3-observability-runtime:
	PYTHONDONTWRITEBYTECODE=1 PYTHONPATH="$(ROOT)" $(PYTHON) "$(ROOT)/scripts/state_of_art/run_phase3_observability.py"

frontend-supply-runtime:
	PYTHONDONTWRITEBYTECODE=1 PYTHONPATH="$(ROOT)" $(PYTHON) "$(ROOT)/scripts/phase11/frontend_supply_runtime_gate.py"

phase3-frontend-supply-runtime:
	PYTHONDONTWRITEBYTECODE=1 PYTHONPATH="$(ROOT)" $(PYTHON) "$(ROOT)/scripts/state_of_art/run_phase3_frontend_supply.py"

restore-runtime:
	PYTHONDONTWRITEBYTECODE=1 PYTHONPATH="$(ROOT)" $(PYTHON) "$(ROOT)/scripts/phase11/restore_runtime_gate.py"

phase3-restore-runtime:
	PYTHONDONTWRITEBYTECODE=1 PYTHONPATH="$(ROOT)" $(PYTHON) "$(ROOT)/scripts/state_of_art/run_phase3_restore.py"

file-security-runtime:
	PYTHONDONTWRITEBYTECODE=1 PYTHONPATH="$(ROOT)" $(PYTHON) "$(ROOT)/scripts/phase11/file_security_runtime_gate.py"

phase3-file-security-runtime:
	PYTHONDONTWRITEBYTECODE=1 PYTHONPATH="$(ROOT)" $(PYTHON) "$(ROOT)/scripts/state_of_art/run_phase3_file_security.py"

triple-aaa-verify:
	PYTHONDONTWRITEBYTECODE=1 $(PYTHON) "$(ROOT)/scripts/state_of_art/triple_aaa_verify.py"

release-evidence:
	PYTHONDONTWRITEBYTECODE=1 $(PYTHON) "$(ROOT)/scripts/state_of_art/generate_release_evidence.py" --environment local-hermetic

phase3-evidence:
	PYTHONDONTWRITEBYTECODE=1 PYTHONPATH="$(ROOT)" $(PYTHON) "$(ROOT)/scripts/state_of_art/generate_phase3_evidence.py"

phase3-evidence-verify:
	PYTHONDONTWRITEBYTECODE=1 PYTHONPATH="$(ROOT)" $(PYTHON) "$(ROOT)/scripts/state_of_art/generate_phase3_evidence.py" --verify --require-promotable

phase3-performance:
	PYTHONDONTWRITEBYTECODE=1 PYTHONPATH="$(ROOT)" $(PYTHON) "$(ROOT)/scripts/state_of_art/run_phase3_operational.py" --lane performance

phase3-chaos:
	PYTHONDONTWRITEBYTECODE=1 PYTHONPATH="$(ROOT)" $(PYTHON) "$(ROOT)/scripts/state_of_art/run_phase3_operational.py" --lane chaos

phase3-soak:
	PYTHONDONTWRITEBYTECODE=1 PYTHONPATH="$(ROOT)" $(PYTHON) "$(ROOT)/scripts/state_of_art/run_phase3_operational.py" --lane soak

ops-backup-test:
	PYTHONDONTWRITEBYTECODE=1 $(PYTHON) -m pytest -q -p no:cacheprovider "$(ROOT)/infrastructure/scripts/tests/test_backup_restore.py"

jobs-test:
	PYTHONDONTWRITEBYTECODE=1 PYTHONPATH="$(ROOT)/apps/worker:$(ROOT)/packages/jobs/src:$(ROOT)/packages/observability/src" $(PYTHON) -m pytest -q -p no:cacheprovider "$(ROOT)/apps/worker/tests/test_runtime.py" "$(ROOT)/apps/worker/tests/test_canonical_queue.py" "$(ROOT)/apps/worker/tests/test_postgres_jobs.py" "$(ROOT)/packages/jobs/tests"

api-dev:
	$(PYTHON) "$(PHASE13_RUNNER)" dev

api-test:
	$(PYTHON) "$(PHASE13_RUNNER)" test

api-contract:
	$(PYTHON) "$(PHASE13_RUNNER)" contract

api-security:
	$(PYTHON) "$(PHASE13_RUNNER)" security

api-benchmark:
	$(PYTHON) "$(PHASE13_RUNNER)" benchmark

api131-canonical:
	$(PYTHON) "$(PHASE131_RUNNER)" canonical

api131-differential:
	$(PYTHON) "$(PHASE131_RUNNER)" differential

api131-full:
	$(PYTHON) "$(PHASE131_RUNNER)" full

api131-benchmark:
	$(PYTHON) "$(PHASE131_RUNNER)" benchmark

api14-units:
	$(PYTHON) "$(PHASE14_RUNNER)" units

api14-differential:
	$(PYTHON) "$(PHASE14_RUNNER)" differential

api14-acl:
	$(PYTHON) "$(PHASE14_RUNNER)" acl

api14-full:
	$(PYTHON) "$(PHASE14_RUNNER)" full

api14-benchmark:
	$(PYTHON) "$(PHASE14_RUNNER)" benchmark

api15-boundaries:
	$(PYTHON) "$(ROOT)/scripts/phase15/check_boundaries.py"

api15-contracts:
	PYTHONDONTWRITEBYTECODE=1 PYTHONPATH="$(ROOT)/packages/contracts/src" $(PYTHON) -m pytest -q -p no:cacheprovider "$(ROOT)/packages/contracts/tests"

api15-provider:
	PYTHONDONTWRITEBYTECODE=1 PYTHONPATH="$(ROOT)/packages/contracts/src:$(ROOT)/packages/providers/src" $(PYTHON) -m pytest -q -p no:cacheprovider "$(ROOT)/packages/providers/tests"

api15-lock:
	PYTHONDONTWRITEBYTECODE=1 PYTHONPATH="$(ROOT)/packages/contracts/src:$(ROOT)/packages/locking/src" $(PYTHON) -m pytest -q -p no:cacheprovider "$(ROOT)/packages/locking/tests"

api15-professor:
	PYTHONDONTWRITEBYTECODE=1 PYTHONPATH="$(ROOT)/packages/contracts/src:$(ROOT)/packages/professor/src" $(PYTHON) -m pytest -q -p no:cacheprovider "$(ROOT)/packages/professor/tests"

api15-root:
	PYTHONDONTWRITEBYTECODE=1 PYTHONPATH="$(ROOT)/apps/api/src:$(ROOT)/apps/worker:$(ROOT)/packages/jobs/src:$(ROOT)/packages/contracts/src:$(ROOT)/packages/authorization/src:$(ROOT)/packages/identity/src:$(ROOT)/packages/observability/src:$(ROOT)/packages/knowledge/src:$(ROOT)/packages/ingestion/src:$(ROOT)/packages/retrieval/src:$(ROOT)/packages/providers/src:$(ROOT)/packages/locking/src:$(ROOT)/packages/professor/src:$(ROOT)/packages/evidence/src:$(ROOT)/packages/decision/src" $(PYTHON) -m pytest -q -p no:cacheprovider "$(ROOT)/apps/api/tests"

api15-benchmark:
	PYTHONDONTWRITEBYTECODE=1 PYTHONPATH="$(ROOT)/apps/api/src:$(ROOT)/packages/contracts/src:$(ROOT)/packages/authorization/src:$(ROOT)/packages/identity/src:$(ROOT)/packages/observability/src:$(ROOT)/packages/knowledge/src:$(ROOT)/packages/ingestion/src:$(ROOT)/packages/retrieval/src:$(ROOT)/packages/providers/src:$(ROOT)/packages/locking/src:$(ROOT)/packages/professor/src:$(ROOT)/packages/evidence/src:$(ROOT)/packages/decision/src" $(PYTHON) "$(ROOT)/scripts/phase15/benchmark.py"

api15-verify:
	$(PYTHON) "$(ROOT)/scripts/phase15/verify.py"

api15-full: api15-boundaries api15-contracts api15-provider api15-lock api15-professor api15-root api15-benchmark

api16-domain:
	PYTHONDONTWRITEBYTECODE=1 PYTHONPATH="$(ROOT)/packages/knowledge/src:$(ROOT)/packages/ingestion/src:$(ROOT)/packages/retrieval/src" $(PYTHON) -m pytest -q -p no:cacheprovider "$(ROOT)/packages/knowledge/tests" "$(ROOT)/packages/ingestion/tests" "$(ROOT)/packages/retrieval/tests"

api16-worker:
	PYTHONDONTWRITEBYTECODE=1 PYTHONPATH="$(ROOT)/apps/worker:$(ROOT)/apps/api/src:$(ROOT)/packages/jobs/src:$(ROOT)/packages/contracts/src:$(ROOT)/packages/authorization/src:$(ROOT)/packages/identity/src:$(ROOT)/packages/observability/src:$(ROOT)/packages/knowledge/src:$(ROOT)/packages/ingestion/src:$(ROOT)/packages/retrieval/src:$(ROOT)/packages/providers/src:$(ROOT)/packages/locking/src:$(ROOT)/packages/professor/src:$(ROOT)/packages/evidence/src:$(ROOT)/packages/decision/src" $(PYTHON) -m pytest -q -p no:cacheprovider "$(ROOT)/apps/worker/tests" "$(ROOT)/apps/api/tests/test_phase16_health.py"

api16-root:
	PYTHONDONTWRITEBYTECODE=1 PYTHONPATH="$(ROOT)/apps/api/src:$(ROOT)/apps/worker:$(ROOT)/packages/jobs/src:$(ROOT)/packages/contracts/src:$(ROOT)/packages/authorization/src:$(ROOT)/packages/identity/src:$(ROOT)/packages/observability/src:$(ROOT)/packages/knowledge/src:$(ROOT)/packages/ingestion/src:$(ROOT)/packages/retrieval/src:$(ROOT)/packages/providers/src:$(ROOT)/packages/locking/src:$(ROOT)/packages/professor/src:$(ROOT)/packages/evidence/src:$(ROOT)/packages/decision/src" $(PYTHON) -m pytest -q -p no:cacheprovider "$(ROOT)/apps/api/tests"

api16-benchmark:
	PYTHONDONTWRITEBYTECODE=1 PYTHONPATH="$(ROOT)/apps/api/src:$(ROOT)/packages/contracts/src:$(ROOT)/packages/knowledge/src:$(ROOT)/packages/ingestion/src:$(ROOT)/packages/retrieval/src" $(PYTHON) "$(ROOT)/scripts/phase16/benchmark.py"

api16-full: validate api16-domain api16-worker api16-root api16-benchmark

api16-verify:
	$(PYTHON) "$(ROOT)/scripts/phase16/verify.py"

web-install:
	cd "$(WEB_DIR)" && npm ci --no-audit --no-fund

web-lint:
	cd "$(WEB_DIR)" && npm run lint

web-typecheck:
	cd "$(WEB_DIR)" && npm run typecheck

web-build:
	cd "$(WEB_DIR)" && RICK_API_INTERNAL_URL="http://127.0.0.1:$${RICK_API_TEST_PORT:-8001}" npm run build

web-e2e:
	cd "$(WEB_DIR)" && RICK_WEB_E2E_PRODUCTION=1 RICK_VISUAL_EVIDENCE_DIR="$(WEB_CURRENT_EVIDENCE_DIR)/production-test-results" RICK_PERFORMANCE_EVIDENCE_DIR="$(WEB_CURRENT_EVIDENCE_DIR)/performance" npm run test:e2e
	@printf '%s\n' 'viewport matrix: 375/768/1440; no planned or executable skips'
	PYTHONDONTWRITEBYTECODE=1 $(PYTHON) "$(ROOT)/scripts/state_of_art/summarize_web_performance.py" --input "$(WEB_CURRENT_EVIDENCE_DIR)/performance" --output "$(WEB_CURRENT_EVIDENCE_DIR)/performance-summary.json"

web-validate: web-lint web-typecheck web-build web-e2e
