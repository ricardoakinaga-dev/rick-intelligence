SHELL := /usr/bin/env bash

ROOT := $(CURDIR)
PYTHON ?= python3
PHASE11_RUNNER := $(ROOT)/scripts/phase11/runner.py
PHASE11_CHECK := $(ROOT)/scripts/phase11/check_skeleton.py

.DEFAULT_GOAL := help

.PHONY: help bootstrap validate dev test test-fast test-integration lint typecheck build up down logs ci eval

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
