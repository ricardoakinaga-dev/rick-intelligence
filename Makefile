SHELL := /usr/bin/env bash

ROOT := $(CURDIR)
PYTHON ?= python3
PHASE11_RUNNER := $(ROOT)/scripts/phase11/runner.py
PHASE11_CHECK := $(ROOT)/scripts/phase11/check_skeleton.py
PHASE13_RUNNER := $(ROOT)/scripts/phase13/phase13.py
PHASE131_RUNNER := $(ROOT)/scripts/phase13/phase131.py
PHASE14_RUNNER := $(ROOT)/scripts/phase13/phase14.py

.DEFAULT_GOAL := help

.PHONY: help bootstrap validate dev test test-fast test-integration lint typecheck build up down logs ci eval api-dev api-test api-contract api-security api-benchmark api131-canonical api131-differential api131-full api131-benchmark api14-units api14-differential api14-acl api14-full api14-benchmark

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
	@printf '%s\n' '  make api-dev          run canonical apps/api kernel (hermetic by default)'
	@printf '%s\n' '  make api-test         Phase 1.3 API matrix (routing/auth/errors/health/compat/streaming)'
	@printf '%s\n' '  make api-contract     OpenAPI generation + required-path check'
	@printf '%s\n' '  make api-security     route-policy + negatives + import-boundary checks'
	@printf '%s\n' '  make api-benchmark    kernel-overhead p50/p95 observation (stub backend)'

bootstrap:
	$(PYTHON) "$(PHASE11_RUNNER)" bootstrap

validate:
	$(PYTHON) "$(PHASE11_CHECK)"

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
