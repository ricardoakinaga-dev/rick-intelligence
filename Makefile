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

.PHONY: help bootstrap validate dev test test-fast test-integration lint typecheck build up down logs ci eval eval-retrieval storage-test ops-migration-check ops-static web-install web-lint web-typecheck web-build web-e2e web-validate api-dev api-test api-contract api-security api-benchmark api131-canonical api131-differential api131-full api131-benchmark api14-units api14-differential api14-acl api14-full api14-benchmark api15-contracts api15-provider api15-lock api15-professor api15-root api15-benchmark api15-verify api15-full api15-boundaries api16-domain api16-worker api16-root api16-benchmark api16-full api16-verify

help:
	@printf '%s\n' 'RICK Intelligence root commands:'
	@printf '%s\n' '  make bootstrap        prepare preserved runtimes and lockfile installs'
	@printf '%s\n' '  make validate         verify skeleton, contracts, boundaries, and history'
	@printf '%s\n' '  make dev              guarded until canonical root apps exist'
	@printf '%s\n' '  make test-fast        focused preserved-component regression checks'
	@printf '%s\n' '  make test             all available component tests and frontend smoke'
	@printf '%s\n' '  make test-integration disposable loopback integration probes'
	@printf '%s\n' '  make lint             root/static/frontend lint checks'
	@printf '%s\n' '  make typecheck        TypeScript compiler and Python compilation checks'
	@printf '%s\n' '  make build            preserved Professor/frontend/Python build checks'
	@printf '%s\n' '  make up|down|logs     guarded root compose lifecycle commands'
	@printf '%s\n' '  make ci               validate + fast tests + lint + typecheck + build'
	@printf '%s\n' '  make eval             deterministic non-live Phase 0.5 plumbing evaluation'
	@printf '%s\n' '  make eval-retrieval   offline retrieval/ACL/provenance evaluation fixture'
	@printf '%s\n' '  make storage-test     local object-store security and restart tests'
	@printf '%s\n' '  make ops-static       migration/env/runbook static checks (no services)'
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

storage-test:
	PYTHONDONTWRITEBYTECODE=1 PYTHONPATH="$(ROOT)/packages/storage/src" $(PYTHON) -m pytest -q -p no:cacheprovider "$(ROOT)/packages/storage/tests"

ops-migration-check:
	PYTHONDONTWRITEBYTECODE=1 $(PYTHON) "$(ROOT)/infrastructure/scripts/check-migration-order.py" "$(ROOT)/infrastructure/migrations"

ops-static: ops-migration-check
	bash -n "$(ROOT)/infrastructure/scripts/validate-env.sh"
	PYTHONDONTWRITEBYTECODE=1 $(PYTHON) -m py_compile "$(ROOT)/infrastructure/scripts/backup-restore-check.py"

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
	PYTHONDONTWRITEBYTECODE=1 PYTHONPATH="$(ROOT)/apps/api/src:$(ROOT)/packages/contracts/src:$(ROOT)/packages/authorization/src:$(ROOT)/packages/identity/src:$(ROOT)/packages/observability/src:$(ROOT)/packages/knowledge/src:$(ROOT)/packages/ingestion/src:$(ROOT)/packages/retrieval/src:$(ROOT)/packages/providers/src:$(ROOT)/packages/locking/src:$(ROOT)/packages/professor/src" $(PYTHON) -m pytest -q -p no:cacheprovider "$(ROOT)/apps/api/tests"

api15-benchmark:
	PYTHONDONTWRITEBYTECODE=1 PYTHONPATH="$(ROOT)/apps/api/src:$(ROOT)/packages/contracts/src:$(ROOT)/packages/authorization/src:$(ROOT)/packages/identity/src:$(ROOT)/packages/observability/src:$(ROOT)/packages/knowledge/src:$(ROOT)/packages/ingestion/src:$(ROOT)/packages/retrieval/src:$(ROOT)/packages/providers/src:$(ROOT)/packages/locking/src:$(ROOT)/packages/professor/src" $(PYTHON) "$(ROOT)/scripts/phase15/benchmark.py"

api15-verify:
	$(PYTHON) "$(ROOT)/scripts/phase15/verify.py"

api15-full: api15-boundaries api15-contracts api15-provider api15-lock api15-professor api15-root api15-benchmark

api16-domain:
	PYTHONDONTWRITEBYTECODE=1 PYTHONPATH="$(ROOT)/packages/knowledge/src:$(ROOT)/packages/ingestion/src:$(ROOT)/packages/retrieval/src" $(PYTHON) -m pytest -q -p no:cacheprovider "$(ROOT)/packages/knowledge/tests" "$(ROOT)/packages/ingestion/tests" "$(ROOT)/packages/retrieval/tests"

api16-worker:
	PYTHONDONTWRITEBYTECODE=1 PYTHONPATH="$(ROOT)/apps/worker:$(ROOT)/apps/api/src:$(ROOT)/packages/contracts/src:$(ROOT)/packages/authorization/src:$(ROOT)/packages/identity/src:$(ROOT)/packages/observability/src:$(ROOT)/packages/knowledge/src:$(ROOT)/packages/ingestion/src:$(ROOT)/packages/retrieval/src:$(ROOT)/packages/providers/src:$(ROOT)/packages/locking/src:$(ROOT)/packages/professor/src" $(PYTHON) -m pytest -q -p no:cacheprovider "$(ROOT)/apps/worker/tests" "$(ROOT)/apps/api/tests/test_phase16_health.py"

api16-root:
	PYTHONDONTWRITEBYTECODE=1 PYTHONPATH="$(ROOT)/apps/api/src:$(ROOT)/packages/contracts/src:$(ROOT)/packages/authorization/src:$(ROOT)/packages/identity/src:$(ROOT)/packages/observability/src:$(ROOT)/packages/knowledge/src:$(ROOT)/packages/ingestion/src:$(ROOT)/packages/retrieval/src:$(ROOT)/packages/providers/src:$(ROOT)/packages/locking/src:$(ROOT)/packages/professor/src" $(PYTHON) -m pytest -q -p no:cacheprovider "$(ROOT)/apps/api/tests"

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
	cd "$(WEB_DIR)" && RICK_API_INTERNAL_URL="http://127.0.0.1:$${RICK_API_TEST_PORT:-8000}" npm run build

web-e2e:
	cd "$(WEB_DIR)" && RICK_WEB_E2E_PRODUCTION=1 RICK_VISUAL_EVIDENCE_DIR="$(WEB_CURRENT_EVIDENCE_DIR)/production-test-results" RICK_PERFORMANCE_EVIDENCE_DIR="$(WEB_CURRENT_EVIDENCE_DIR)/performance" npm run test:e2e
	@printf '%s\n' 'viewport matrix: 375/768/1440; no planned or executable skips'
	PYTHONDONTWRITEBYTECODE=1 $(PYTHON) "$(ROOT)/scripts/state_of_art/summarize_web_performance.py" --input "$(WEB_CURRENT_EVIDENCE_DIR)/performance" --output "$(WEB_CURRENT_EVIDENCE_DIR)/performance-summary.json"

web-validate: web-lint web-typecheck web-build web-e2e
