"""Canonical CI must use generated, hash-checked locks and retain key suites."""

from pathlib import Path

import pytest
import yaml

from scripts.phase11.check_canonical_ci import ROOT, WORKFLOWS, check_canonical_ci
from scripts.phase11.check_canonical_ci import EXPECTED_SUITES, WRAPPER


def _current_workflows() -> dict[str, str]:
    return {
        relative: (ROOT / relative).read_text(encoding="utf-8")
        for relative in WORKFLOWS
    }


def test_current_canonical_workflows_are_a_known_good_fixture() -> None:
    assert check_canonical_ci(ROOT, _current_workflows()) == []


def test_unhashed_canonical_install_is_rejected() -> None:
    workflows = _current_workflows()
    quality = workflows[WORKFLOWS[0]]
    workflows[WORKFLOWS[0]] = quality.replace("--require-hashes ", "", 1)

    errors = check_canonical_ci(ROOT, workflows)

    assert any("pip install must include --require-hashes" in error for error in errors)


def test_removing_a_dependency_from_the_lock_fails_the_lock_contract(tmp_path: Path) -> None:
    """AUD07-08: a lock that drops a declared pin must fail the supply-chain lane.

    The declaration lives in ``requirements/*.in``; the lane installs the
    generated lock with ``--require-hashes``. Deleting a pin from the lock
    therefore has to surface as an explicit named error here, not as a later
    import failure in an unrelated suite.
    """
    import shutil

    from scripts.phase11.check_canonical_ci import _collect_lock_inputs

    shutil.copytree(ROOT / "requirements", tmp_path / "requirements")
    lock = tmp_path / "requirements" / "runtime.lock"
    kept: list[str] = []
    dropping = False
    for line in lock.read_text(encoding="utf-8").splitlines():
        if line.startswith("jsonschema=="):
            dropping = True
            continue
        if dropping:
            if line.startswith("    ") or line.startswith("\t"):
                continue
            dropping = False
        kept.append(line)
    lock.write_text("\n".join(kept) + "\n", encoding="utf-8")

    errors = _collect_lock_inputs(
        tmp_path,
        "requirements/runtime.lock",
        seen_locks=set(),
        source_inputs=set(),
        source_texts={},
    )

    assert errors == [
        "requirements/runtime.lock: pin jsonschema==4.26.0 "
        "from requirements/runtime.in is absent or mismatched"
    ]


def test_missing_jobs_suite_command_is_rejected() -> None:
    workflows = _current_workflows()
    quality = workflows[WORKFLOWS[0]]
    workflows[WORKFLOWS[0]] = quality.replace('            --command "make jobs-test" \\\n', "", 1)

    errors = check_canonical_ci(ROOT, workflows)

    assert any("missing required suite command: make jobs-test" in error for error in errors)


def test_commented_jobs_suite_does_not_count_as_executed() -> None:
    workflows = _current_workflows()
    workflows[WORKFLOWS[0]] = workflows[WORKFLOWS[0]].replace(
        '            --command "make jobs-test" \\\n',
        '            # --command "make jobs-test" \\\n', 1,
    )
    assert any("missing required suite command: make jobs-test" in error
               for error in check_canonical_ci(ROOT, workflows))


def test_suite_only_in_a_step_name_does_not_count() -> None:
    workflows = _current_workflows()
    workflows[WORKFLOWS[0]] = workflows[WORKFLOWS[0]].replace(
        '            --command "make jobs-test" \\\n', "", 1,
    ).replace("name: Execute and record unit CI gate", "name: make jobs-test")
    assert any("missing required suite command: make jobs-test" in error
               for error in check_canonical_ci(ROOT, workflows))


def test_suite_echo_does_not_count_as_executed() -> None:
    workflows = _current_workflows()
    workflows[WORKFLOWS[0]] = workflows[WORKFLOWS[0]].replace(
        '            --command "make jobs-test" \\\n', "", 1,
    ).replace("python -m pip check", 'python -m pip check\n          echo "make jobs-test"', 1)
    assert any("missing required suite command: make jobs-test" in error
               for error in check_canonical_ci(ROOT, workflows))


def test_unreferenced_runtime_input_is_rejected() -> None:
    test_input = (ROOT / "requirements/test.in").read_text(encoding="utf-8")
    test_input = test_input.replace("-r runtime.lock\n", "", 1)

    errors = check_canonical_ci(
        ROOT,
        _current_workflows(),
        {"requirements/test.in": test_input},
    )

    assert any(
        "requirements/runtime.in: canonical lock input is not referenced" in error
        for error in errors
    )


@pytest.mark.parametrize("header,body,footer", [
    ("cat <<EOF", "make jobs-test", "EOF"),
    ("cat <<'EOF'", "make jobs-test", "EOF"),
    ('cat <<"EOF"', "make jobs-test", "EOF"),
    ("cat <<\\EOF", "make jobs-test", "EOF"),
    ("cat <<-EOF", "\tmake jobs-test", "\tEOF"),
    ("cat <<FIRST <<SECOND", "make jobs-test\nFIRST\nmake jobs-test", "SECOND"),
])
def test_suite_in_heredoc_is_data_not_execution(header: str, body: str, footer: str) -> None:
    from scripts.phase11.check_canonical_ci import EXPECTED_SUITES
    workflows = _current_workflows()
    workflow = yaml.safe_load(workflows[WORKFLOWS[0]])
    steps = workflow["jobs"]["unit"]["steps"]
    gate = next(step for step in steps if step.get("name") == "Execute and record unit CI gate")
    gate["run"] = "\n".join([header, body, footer, *EXPECTED_SUITES[1:]])
    workflows[WORKFLOWS[0]] = yaml.safe_dump(workflow)
    errors = check_canonical_ci(ROOT, workflows)
    assert any("missing required suite command: make jobs-test" in error for error in errors)
    assert not any("missing required suite command: make storage-test" in error for error in errors)


def test_actual_suite_after_heredoc_still_executes() -> None:
    from scripts.phase11.check_canonical_ci import EXPECTED_SUITES
    workflows = _current_workflows()
    workflow = yaml.safe_load(workflows[WORKFLOWS[0]])
    gate = next(step for step in workflow["jobs"]["unit"]["steps"]
                if step.get("name") == "Execute and record unit CI gate")
    gate["run"] = "\n".join(["cat <<'EOF'", "make jobs-test", "EOF", *EXPECTED_SUITES])
    workflows[WORKFLOWS[0]] = yaml.safe_dump(workflow)
    assert check_canonical_ci(ROOT, workflows) == []


def _unit_run(run: str, *, change=None) -> dict[str, str]:
    workflows = _current_workflows()
    workflow = yaml.safe_load(workflows[WORKFLOWS[0]])
    job = workflow['jobs']['unit']
    gate = next(step for step in job['steps'] if step.get('name') == 'Execute and record unit CI gate')
    gate['run'] = run
    if change:
        change(workflow, job, gate)
    workflows[WORKFLOWS[0]] = yaml.safe_dump(workflow)
    return workflows


@pytest.mark.parametrize('data', [
    "printf '%s\\n' 'heading\nmake jobs-test\nfooter'",
    ': "heading\nmake jobs-test\nfooter"',
    "printf '%s\\n' 'make jobs-test'",
    'echo "make jobs-test"',
    '"make jobs-test"',
    '"CI=true" make jobs-test',
    "'CI=true' make jobs-test",
    "C'I'=true make jobs-test",
    "CI\\=true make jobs-test",
    "env -u '' make jobs-test",
    'make "jobs-test storage-test"',
    "cat <<EOF\nmake jobs-test\nEOF",
    "cat <<'EOF'\n: 'make jobs-test'\nEOF",
    "# make jobs-test",
    "if false; then\nmake jobs-test\nfi",
    "if [ -n \"$UNKNOWN\" ]; then make jobs-test; fi",
    "false && make jobs-test",
    "true || make jobs-test",
    "python3 -c 'raise SystemExit(1)' && make jobs-test",
    "make jobs-test &",
    "make jobs-test | cat",
    "exit 0\nmake jobs-test",
    "false\nmake jobs-test",
    "make() { :; }; make jobs-test",
    "alias make=:; make jobs-test",
    "eval 'make jobs-test'",
    "bash -c 'make jobs-test'",
    "${COMMAND:-make} jobs-test",
    "make jobs-test &&;",
    "make jobs-test; ; true",
    "; make jobs-test",
    "printf '%s' '\nmake jobs-test",  # Unclosed quote cannot expose its inner line.
    "cat <<EOF\nmake jobs-test",  # Unclosed heredoc cannot prove anything.
])
def test_public_gate_rejects_data_unreachable_or_unverifiable_jobs(data):
    errors = check_canonical_ci(ROOT, _unit_run('\n'.join([data, *EXPECTED_SUITES[1:]])))
    assert any('missing required suite command: make jobs-test' in error for error in errors)


@pytest.mark.parametrize('run', [
    '\n'.join(EXPECTED_SUITES),
    '; '.join(EXPECTED_SUITES),
    ' && '.join(EXPECTED_SUITES),
    ' &&\n'.join(EXPECTED_SUITES),
    '\n'.join(["CI=true make jobs-test", *EXPECTED_SUITES[1:]]),
    '\n'.join(["CI='a b' env TRACE=1 make jobs-test", *EXPECTED_SUITES[1:]]),
    '\n'.join(["env -- TRACE=1 make jobs-test", *EXPECTED_SUITES[1:]]),
    '\n'.join(["env -u RICK_MIGRATION_POSTGRES_TESTS make jobs-test", *EXPECTED_SUITES[1:]]),
    '\n'.join(["# explanatory comment \\", *EXPECTED_SUITES]),
    '\n'.join(["printf '%s\\n' 'make jobs-test\n&& not a command'", *EXPECTED_SUITES]),
    '\n'.join(["cat <<FIRST <<'SECOND'\nmake jobs-test\nFIRST\nif false; then\nSECOND", *EXPECTED_SUITES]),
    '\n'.join(["cat <<-EOF\n\tmake jobs-test\n\tEOF", *EXPECTED_SUITES]),
    '\n'.join(["make jobs-test > result.txt", *EXPECTED_SUITES[1:]]),
    '\n'.join(["make jobs-test 2> result.txt", *EXPECTED_SUITES[1:]]),
    '\n'.join(["make jobs-test <<'EOF'\nquoted data\nEOF", *EXPECTED_SUITES[1:]]),
    '\n'.join(["ma\\\nke jobs-test", *EXPECTED_SUITES[1:]]),
])
def test_public_gate_accepts_supported_actual_commands(run):
    assert check_canonical_ci(ROOT, _unit_run(run)) == []


@pytest.mark.parametrize('where,condition', [
    ('step', False), ('step', 'false'), ('step', '${{ false }}'),
    ('job', False), ('job', 'false'), ('job', '${{ false }}'),
    ('step', "github.event_name == 'unknown'"),
    ('job', "github.event_name == 'unknown'"),
])
def test_disabled_or_unverifiable_yaml_conditions_do_not_prove_suites(where, condition):
    def change(_workflow, job, step):
        (step if where == 'step' else job)['if'] = condition
    errors = check_canonical_ci(ROOT, _unit_run('\n'.join(EXPECTED_SUITES), change=change))
    assert any('missing required suite command: make jobs-test' in error for error in errors)


@pytest.mark.parametrize('condition', [True, 'true', '${{ true }}', 'success()', '${{ success() }}', 'always()'])
def test_supported_execution_conditions_are_accepted(condition):
    def change(_workflow, job, step):
        job['if'] = step['if'] = condition
    assert check_canonical_ci(ROOT, _unit_run('\n'.join(EXPECTED_SUITES), change=change)) == []


@pytest.mark.parametrize('property,value', [
    ('shell', 'pwsh'), ('working-directory', 'apps/web'), ('continue-on-error', True),
])
def test_wrong_execution_context_is_not_suite_evidence(property, value):
    def change(_workflow, _job, step):
        step[property] = value
    errors = check_canonical_ci(ROOT, _unit_run('\n'.join(EXPECTED_SUITES), change=change))
    assert any('missing required suite command: make jobs-test' in error for error in errors)


def _wrapper(path=WRAPPER, extra='', command='make jobs-test'):
    import shlex
    return (f'python3 {path} --lane unit --gate unit {extra} '
            f'--command {shlex.quote(command)}')


@pytest.mark.parametrize('path', [
    'docs/ci_lane_evidence.py', 'docs/ci/ci_lane_evidence.py',
    '/absent/ci_lane_evidence.py', 'ci_lane_evidence.py',
    'scripts/state_of_art/../state_of_art/ci_lane_evidence.py',
])
def test_wrong_or_absent_wrapper_path_does_not_prove_execution(path):
    errors = check_canonical_ci(ROOT, _unit_run('\n'.join([_wrapper(path), *EXPECTED_SUITES[1:]])))
    assert any('missing required suite command: make jobs-test' in error for error in errors)


@pytest.mark.parametrize('extra,command', [
    ('--help', 'make jobs-test'), ('--root /other', 'make jobs-test'),
    ('--invalid option', 'make jobs-test'), ('', "'make jobs-test'"),
    ('', 'CI=true make jobs-test'), ('', 'echo make jobs-test'),
    ('', 'make jobs-test && make storage-test'),
])
def test_wrapper_must_actually_launch_exact_suite_argv(extra, command):
    errors = check_canonical_ci(ROOT, _unit_run('\n'.join([_wrapper(extra=extra, command=command), *EXPECTED_SUITES[1:]])))
    assert any('missing required suite command: make jobs-test' in error for error in errors)


@pytest.mark.parametrize('command', ['make jobs-test', 'env CI=true make jobs-test'])
def test_declared_wrapper_with_real_argv_is_accepted(command):
    assert check_canonical_ci(ROOT, _unit_run('\n'.join([_wrapper(command=command), *EXPECTED_SUITES[1:]]))) == []


def test_wrapper_equals_options_and_env_prefix_are_accepted():
    run = 'CI=true env TRACE=1 python3 ./scripts/state_of_art/ci_lane_evidence.py --lane=unit --gate=unit '
    run += ' '.join('--command=' + __import__('shlex').quote(command) for command in EXPECTED_SUITES)
    assert check_canonical_ci(ROOT, _unit_run(run)) == []


def test_migration_env_unset_cannot_be_cancelled_by_assignment():
    run = '\n'.join([*EXPECTED_SUITES[:2], EXPECTED_SUITES[2].replace(
        'python3', 'RICK_MIGRATION_POSTGRES_TESTS=1 python3', 1)])
    errors = check_canonical_ci(ROOT, _unit_run(run))
    assert any('missing required suite command: env -u' in error for error in errors)


def test_incomplete_and_list_is_rejected():
    errors = check_canonical_ci(ROOT, _unit_run('make jobs-test &&'))
    assert any('missing required suite command: make jobs-test' in error for error in errors)


def test_env_options_after_assignments_do_not_prove_execution():
    run = '\n'.join(['env CI=true -u IGNORED make jobs-test', *EXPECTED_SUITES[1:]])
    errors = check_canonical_ci(ROOT, _unit_run(run))
    assert any('missing required suite command: make jobs-test' in error for error in errors)


@pytest.mark.parametrize('extra', [
    '--timeout-seconds 0', '--timeout-seconds never', '--timeout-seconds 86401',
    '--gate unit', '--output /absent/evidence.json', '--output .',
    '--output .runtime/../elsewhere.json',
    '--output .runtime/same.json --log-output .runtime/same.json',
    '--command "\'unterminated"', '--command "\'\'"',
])
def test_invalid_helper_envelope_options_prevent_all_suite_execution(extra):
    errors = check_canonical_ci(ROOT, _unit_run('\n'.join([_wrapper(extra=extra), *EXPECTED_SUITES[1:]])))
    assert any('missing required suite command: make jobs-test' in error for error in errors)


@pytest.mark.parametrize('run,executes', [
    ("printf '%s\\n' 'heading\nmake jobs-test\nfooter'", False),
    (": 'heading\nmake jobs-test\nfooter'", False),
    ("cat <<'EOF'\nmake jobs-test\nEOF", False),
    ("if false; then make jobs-test; fi", False),
    ("python3 -c 'raise SystemExit(1)' && make jobs-test", False),
    ("CI=true make jobs-test", True),
    ("make jobs-test && make storage-test", True),
    ("# a comment \\\nmake jobs-test", True),
])
def test_public_command_faithfulness_matches_bash_execution(run, executes):
    import subprocess
    # Stub definitions are the observation harness, not part of the checked workflow.
    harness = 'make() { printf "EXECUTED_MAKE:%s\\n" "$*"; }; env() { :; };\n'
    candidate = '\n'.join([run, *EXPECTED_SUITES[1:]])
    result = subprocess.run(['bash', '--noprofile', '--norc', '-e', '-c', harness + candidate],
                            capture_output=True, text=True, check=False, timeout=5)
    assert result.returncode == 0
    assert ('EXECUTED_MAKE:jobs-test' in result.stdout) is executes
    errors = check_canonical_ci(ROOT, _unit_run(candidate))
    checker_executes = not any('missing required suite command: make jobs-test' in error for error in errors)
    assert checker_executes is executes


def test_install_requirement_is_an_argv_path_not_joined_data():
    workflows = _current_workflows()
    workflows[WORKFLOWS[0]] = workflows[WORKFLOWS[0]].replace(
        '-r requirements/test.lock', '-r "requirements/test.lock trailing-data"', 1)
    assert any('lock path must be a root requirements lock' in error
               for error in check_canonical_ci(ROOT, workflows))


def test_compound_env_prefixed_lock_install_is_accepted():
    workflows = _current_workflows()
    workflows[WORKFLOWS[0]] = workflows[WORKFLOWS[0]].replace(
        'python -m pip install', 'CI=true env TRACE=1 python -m pip install', 1)
    workflows[WORKFLOWS[0]] = workflows[WORKFLOWS[0]].replace(
        '-r requirements/test.lock\n          python -m pip check',
        '--requirement=requirements/test.lock && python -m pip check', 1)
    assert check_canonical_ci(ROOT, workflows) == []


@pytest.mark.parametrize('prefix', [
    'set -n', 'set -en', 'set -o noexec', 'set +e', 'set -- ignored',
    'command false', 'command -- false', 'env TRACE=1 command false',
    'command exit 0', 'command exec true', 'builtin exit 0',
    'exec true', 'exit 0', 'return 0', 'trap "exit 0" DEBUG',
    'bash -n', "python3 -c 'raise SystemExit(0)'", 'command -v make',
    'export PYTEST_ADDOPTS=--collect-only',
    'nonexistent-aud03-command', 'make -n jobs-test',
    'make jobs-test PYTHON=true', "printf -v PATH '%s' /absent",
    "python3 -I -c 'raise SystemExit(1)'", 'python3 -m nonexistent_aud03_module',
])
def test_execution_suppression_and_unsupported_flow_fail_closed(prefix):
    # A standalone bash -n waits for stdin rather than running following code.
    if prefix == 'bash -n':
        prefix = "bash -n <<'EOF'\nmake jobs-test\nEOF"
        candidate = '\n'.join([prefix, *EXPECTED_SUITES[1:]])
    else:
        candidate = '\n'.join([prefix, *EXPECTED_SUITES])
    assert check_canonical_ci(ROOT, _unit_run(candidate))


@pytest.mark.parametrize('prefix', ['set -e', 'set -eu', 'set -euo pipefail', 'set -o pipefail'])
def test_safe_shell_options_preserve_real_suite_execution(prefix):
    assert check_canonical_ci(ROOT, _unit_run(prefix + '\n' + '\n'.join(EXPECTED_SUITES))) == []


@pytest.mark.parametrize('command', [
    'make jobs-test > /nonexistent-aud03-independent/child/log',
    'make jobs-test < missing-aud03-input.txt', 'make jobs-test > .',
    'make jobs-test > nonexistent-aud03-parent/log',
    'PYTHON=true make jobs-test', 'env MAKEFLAGS=-n make jobs-test',
    'env PYTEST_ADDOPTS=--collect-only make jobs-test', 'PATH=/absent make jobs-test',
])
def test_suite_redirections_and_execution_overrides_are_not_discarded(command):
    assert check_canonical_ci(ROOT, _unit_run('\n'.join([command, *EXPECTED_SUITES[1:]])))


@pytest.mark.parametrize('command', ['command make jobs-test', 'command -- make jobs-test', 'make jobs-test > /dev/null'])
def test_literal_command_wrapper_and_null_redirection_are_supported(command):
    assert check_canonical_ci(ROOT, _unit_run('\n'.join([command, *EXPECTED_SUITES[1:]]))) == []


def _replace_recipe(target, recipe):
    text = (ROOT / 'Makefile').read_text()
    lines = text.splitlines(keepends=True)
    start = next(i for i, line in enumerate(lines) if line.startswith(target + ':')) + 1
    end = start
    while end < len(lines) and (lines[end].startswith('\t') or not lines[end].strip()):
        end += 1
    return ''.join(lines[:start]) + recipe + '\n' + ''.join(lines[end:])


@pytest.mark.parametrize('target', ['jobs-test', 'storage-test', 'validate', 'ops-static'])
@pytest.mark.parametrize('recipe', ['', '\t@true\n', '\t@echo "python3 -m pytest packages/jobs/tests"\n'])
def test_real_make_recipes_are_required_not_phony_or_printed_targets(target, recipe):
    assert check_canonical_ci(ROOT, source_texts={'Makefile': _replace_recipe(target, recipe)})


@pytest.mark.parametrize('recipe', [
    '\tset -n; python3 -m pytest apps/worker/tests/test_runtime.py apps/worker/tests/test_canonical_queue.py apps/worker/tests/test_postgres_jobs.py packages/jobs/tests\n',
    '\t-python3 -m pytest packages/jobs/tests\n',
    '\tpython3 -m pytest --collect-only apps/worker/tests/test_runtime.py apps/worker/tests/test_canonical_queue.py apps/worker/tests/test_postgres_jobs.py packages/jobs/tests\n',
    '\tPYTEST_ADDOPTS=--collect-only python3 -m pytest packages/jobs/tests\n',
])
def test_make_suite_options_must_execute_the_required_suite(recipe):
    assert check_canonical_ci(ROOT, source_texts={'Makefile': _replace_recipe('jobs-test', recipe)})


@pytest.mark.parametrize('mutation', [
    lambda text: text.replace('PYTHON ?= python3', 'PYTHON ?= true'),
    lambda text: text + '\nPYTHON := true\n',
    lambda text: text + '\n.SHELLFLAGS := -n\n',
    lambda text: text + '\n.IGNORE: jobs-test\n',
    lambda text: text + '\nMAKEFLAGS := -n\n',
    lambda text: text + '\ninclude unverified.mk\n',
    lambda text: text + '\nX := $(shell printf unsafe)\n',
])
def test_unverifiable_make_execution_settings_fail_closed(mutation):
    assert check_canonical_ci(ROOT, source_texts={'Makefile': mutation((ROOT / 'Makefile').read_text())})


def test_make_suite_can_be_a_real_phony_prerequisite_with_literal_env_and_compound_recipe():
    text = _replace_recipe('jobs-test', '')
    text = text.replace('jobs-test:\n', 'jobs-test: actual-jobs-suite\n')
    original = (ROOT / 'Makefile').read_text().split('jobs-test:\n', 1)[1].split('\napi-dev:', 1)[0].strip()
    text += '\n.PHONY: actual-jobs-suite\nactual-jobs-suite:\n\t@' + original.replace('$(PYTHON)', 'env TRACE=1 $(PYTHON)') + ' && true\n'
    assert check_canonical_ci(ROOT, source_texts={'Makefile': text}) == []


@pytest.mark.parametrize('change', [
    lambda job, gate: job.update({'if': False}),
    lambda job, gate: gate.update({'if': '${{ false }}'}),
    lambda job, gate: gate.update({'continue-on-error': True}),
    lambda job, gate: gate.update({'run': 'echo "make validate; make ops-static"'}),
    lambda job, gate: gate.update({'run': 'set -n\nmake validate\nmake ops-static'}),
])
def test_checker_wiring_must_execute_in_the_fast_job(change):
    texts = _current_workflows()
    workflow = yaml.safe_load(texts[WORKFLOWS[0]])
    job = workflow['jobs']['fast']
    gate = next(step for step in job['steps'] if step.get('name') == 'Execute and record architecture CI gate')
    change(job, gate)
    texts[WORKFLOWS[0]] = yaml.safe_dump(workflow)
    assert check_canonical_ci(ROOT, texts)


@pytest.mark.parametrize('where', ['workflow', 'job', 'step'])
@pytest.mark.parametrize('binding', [{'MAKEFLAGS': '-n'}, {'PYTHON': 'true'}, {'PYTEST_ADDOPTS': '--collect-only'}, {'BASH_ENV': 'unverified.sh'}])
def test_yaml_execution_environment_cannot_suppress_or_rebind_suites(where, binding):
    def change(workflow, job, step):
        selected = {'workflow': workflow, 'job': job, 'step': step}[where]
        selected['env'] = {**selected.get('env', {}), **binding}
    assert check_canonical_ci(ROOT, _unit_run('\n'.join(EXPECTED_SUITES), change=change))


@pytest.mark.parametrize('extra', [
    '--invalid nope', '--timeout-seconds 0', '--timeout-seconds 86401',
    '--timeout-seconds never', '--gate unit', '--lane " "',
    '--output /absent/evidence.json', '--output .runtime/../outside.json',
    '--output .runtime/same.json --log-output .runtime/same.json',
    '--command "\'unterminated"', '--command "\'\'"', '--root .', '--roo .',
])
@pytest.mark.parametrize('separator', ['\n', '; ', ' && '])
def test_every_invalid_wrapper_prefix_invalidates_following_suite_evidence(extra, separator):
    prefix = _wrapper(command='true', extra=extra)
    candidate = separator.join([prefix, *EXPECTED_SUITES])
    errors = check_canonical_ci(ROOT, _unit_run(candidate))
    assert errors
    assert any('unverifiable shell execution' in error for error in errors)


@pytest.mark.parametrize('prefix', [
    f'python3 {WRAPPER} --help', f'python3 {WRAPPER} -h',
    _wrapper(command='true', extra='--help'),
    _wrapper(command='true', extra='--invalid ignored --help'),
])
@pytest.mark.parametrize('separator', ['\n', '; ', ' && '])
def test_real_helper_help_is_a_harmless_prefix_not_suite_evidence(prefix, separator):
    assert check_canonical_ci(ROOT, _unit_run(separator.join([prefix, *EXPECTED_SUITES]))) == []


def _canonical_control_fixture(root):
    import shutil
    for relative in [*WORKFLOWS, 'Makefile', WRAPPER, 'scripts/state_of_art/requirements.txt']:
        target = root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / relative, target)
    for source in (ROOT / 'requirements').glob('*'):
        if source.is_file():
            target = root / 'requirements' / source.name
            target.parent.mkdir(exist_ok=True)
            shutil.copyfile(source, target)
    # These recipes execute real Python sources before their checkers/suites.
    for relative in [
        'docs/ci/restore_control_inputs.py', 'docs/ci/check_control_plane.py',
        'scripts/phase15/check_boundaries.py', 'scripts/phase11/check_toolchain.py',
        'scripts/phase11/check_workflow_actions.py', 'scripts/phase11/check_canonical_ci.py',
        'scripts/phase11/evidence_store.py',
        'scripts/state_of_art/validate_quality_bar.py', 'infrastructure/scripts/migrate.py',
        'infrastructure/scripts/backup-restore-check.py', 'infrastructure/scripts/backup_restore.py',
    ]:
        target = root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / relative, target)


def test_wrapper_implementation_is_bound_to_reviewed_bytes(tmp_path):
    import hashlib
    from scripts.phase11.check_canonical_ci import WRAPPER_SHA256
    _canonical_control_fixture(tmp_path)
    assert hashlib.sha256((tmp_path / WRAPPER).read_bytes()).hexdigest() == WRAPPER_SHA256
    assert check_canonical_ci(tmp_path) == []
    (tmp_path / WRAPPER).write_text('print("NO_SUITE_EXECUTED")\n')
    errors = check_canonical_ci(tmp_path)
    assert any('implementation SHA-256' in error for error in errors)


def test_helper_byte_changes_require_explicit_contract_review(tmp_path):
    _canonical_control_fixture(tmp_path)
    helper = tmp_path / WRAPPER
    helper.write_bytes(helper.read_bytes() + b'\n# changed version\n')
    assert any('implementation SHA-256' in error for error in check_canonical_ci(tmp_path))


@pytest.mark.parametrize('position', [0, 1, 2])
def test_all_wrapper_invocations_are_checked_even_beside_a_genuine_suite_wrapper(position):
    import shlex
    good = f'python3 {WRAPPER} --lane unit --gate unit ' + ' '.join('--command ' + shlex.quote(command) for command in EXPECTED_SUITES)
    commands = [f'python3 {WRAPPER} --help', good]
    commands.insert(position, _wrapper(command='true', extra='--invalid nope'))
    assert check_canonical_ci(ROOT, _unit_run('\n'.join(commands)))


@pytest.mark.parametrize('extra,expected_exit', [
    ('--invalid nope', 2), ('--timeout-seconds 0', 1),
    ('--command "\'unterminated"', 1), ('--help', 0),
])
def test_pinned_helper_prefix_reachability_matches_bash_and_actual_suites(tmp_path, extra, expected_exit):
    import os
    import shlex
    import subprocess
    import sys
    from scripts.phase11.check_canonical_ci import _trusted_wrapper
    _canonical_control_fixture(tmp_path)
    _trusted_wrapper(tmp_path)
    # Execute only the byte-pinned genuine helper. Excluded provenance/redaction
    # imports are explicit observation stubs; no fake CI approval is produced.
    driver = tmp_path / 'observe.py'
    driver.write_text('import runpy,sys,types\n'
                      'a=types.ModuleType("scripts.state_of_art.phase3_runtime_adapter")\n'
                      'a.redact_runtime_value=lambda x:x\n'
                      'b=types.ModuleType("scripts.state_of_art.release_integrity")\n'
                      'b.capture_checkout=lambda root:{"available":False,"status":"OBSERVATION_ONLY"}\n'
                      'sys.modules[a.__name__]=a; sys.modules[b.__name__]=b\n'
                      'path=sys.argv.pop(1); runpy.run_path(path,run_name="__main__")\n')
    paths = ['apps/worker/tests/test_runtime.py', 'apps/worker/tests/test_canonical_queue.py',
             'apps/worker/tests/test_postgres_jobs.py', 'packages/jobs/tests/test_synthetic.py',
             'packages/storage/tests/test_synthetic.py', 'infrastructure/scripts/tests/test_synthetic.py']
    for index, relative in enumerate(paths):
        path = tmp_path / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f'from pathlib import Path\ndef test_marker():\n    Path({str(tmp_path / (str(index) + ".marker"))!r}).write_text("EXECUTED")\n')
    prefix = f'{shlex.quote(sys.executable)} {shlex.quote(str(driver))} {shlex.quote(str(tmp_path / WRAPPER))} --lane unit --gate unit --command true {extra}'
    result = subprocess.run(['bash', '--noprofile', '--norc', '-e', '-c', prefix + '\n' + '\n'.join(EXPECTED_SUITES)],
                            cwd=tmp_path, env={**os.environ, 'PATH': str(__import__('pathlib').Path(sys.executable).parent) + os.pathsep + os.environ['PATH']},
                            text=True, capture_output=True, timeout=30)
    assert result.returncode == expected_exit, result.stdout + result.stderr
    assert len(list(tmp_path.glob('*.marker'))) == (6 if expected_exit == 0 else 0)
    errors = check_canonical_ci(tmp_path, _unit_run(_wrapper(command='true', extra=extra) + '\n' + '\n'.join(EXPECTED_SUITES)))
    assert (not errors) is (expected_exit == 0)


@pytest.mark.parametrize('script,expected_exit,executed', [
    ('set -n\nmake jobs-test', 0, False),
    ('set -o noexec\nmake jobs-test', 0, False),
    ('command false\nmake jobs-test', 1, False),
    ('exec true\nmake jobs-test', 0, False),
    ('exit 0\nmake jobs-test', 0, False),
    ('make jobs-test > /nonexistent-aud03-independent/child/log', 1, False),
    ('set -eu\nmake jobs-test', 0, True),
])
def test_suppression_matches_actual_bash_exit_and_suite_markers(tmp_path, script, expected_exit, executed):
    import os
    import subprocess
    stub = tmp_path / 'make'
    stub.write_text('#!/bin/sh\nprintf "EXECUTED_MAKE:%s\\n" "$*"\n')
    stub.chmod(0o755)
    result = subprocess.run(['bash', '--noprofile', '--norc', '-e', '-c', script],
                            env={**os.environ, 'PATH': str(tmp_path) + os.pathsep + os.environ['PATH']},
                            capture_output=True, text=True, timeout=5)
    assert result.returncode == expected_exit
    assert ('EXECUTED_MAKE:jobs-test' in result.stdout) is executed
    errors = check_canonical_ci(ROOT, _unit_run('\n'.join([script, *EXPECTED_SUITES[1:]])))
    assert (not errors) is executed


@pytest.mark.parametrize('prefix', [
    'python3 missing-aud03-never-exists.py',
    'python3 -m py_compile missing-aud03-never-exists.py',
])
def test_missing_python_input_cannot_prove_a_later_wrapper(prefix):
    import shlex
    wrapper = f'python3 {WRAPPER} --lane unit --gate unit ' + ' '.join(
        '--command ' + shlex.quote(command) for command in EXPECTED_SUITES)
    errors = check_canonical_ci(ROOT, _unit_run(prefix + '\n' + wrapper))
    assert any('missing required suite command: make jobs-test' in error for error in errors)


@pytest.mark.parametrize('condition,expected', [(None, False), ('true', False), ('success()', False), ('always()', True)])
def test_dependency_skip_propagates_through_a_chain(condition, expected):
    def change(workflow, job, _step):
        workflow['jobs']['disabled'] = {'if': False, 'steps': [{'run': 'true'}]}
        workflow['jobs']['middle'] = {'needs': 'disabled', 'steps': [{'run': 'true'}]}
        job['needs'] = ['middle']
        if condition is not None:
            job['if'] = condition
    assert (not check_canonical_ci(ROOT, _unit_run('\n'.join(EXPECTED_SUITES), change=change))) is expected


def test_enabled_dependency_chain_and_common_executable_prefix_remain_valid():
    def change(workflow, job, _step):
        workflow['jobs']['setup'] = {'steps': [{'run': 'true'}]}
        workflow['jobs']['middle'] = {'needs': 'setup', 'steps': [{'run': 'true'}]}
        job['needs'] = ['middle']
    run = 'python3 -m pip check\n' + '\n'.join(EXPECTED_SUITES)
    assert check_canonical_ci(ROOT, _unit_run(run, change=change)) == []


@pytest.mark.parametrize('needs', [['unit'], ['missing-aud03-job'], {'job': 'fast'}])
def test_invalid_dependency_graph_cannot_supply_suite_evidence(needs):
    def change(_workflow, job, _step):
        job['needs'] = needs
    assert check_canonical_ci(ROOT, _unit_run('\n'.join(EXPECTED_SUITES), change=change))


@pytest.mark.parametrize('compile_input', [False, True])
def test_existing_python_setup_input_preserves_real_suite_execution(tmp_path, compile_input):
    import os
    import subprocess
    _canonical_control_fixture(tmp_path)
    (tmp_path / 'setup.py').write_text('print("SETUP_EXECUTED")\n')
    prefix = 'python3 ' + ('-m py_compile ' if compile_input else '') + 'setup.py'
    run = prefix + '\n' + '\n'.join(EXPECTED_SUITES)
    assert check_canonical_ci(tmp_path, _unit_run(run)) == []
    marker = tmp_path / 'make'
    marker.write_text('#!/bin/sh\nprintf "EXECUTED_MAKE:%s\\n" "$*"\n')
    marker.chmod(0o755)
    observed = subprocess.run(['bash', '--noprofile', '--norc', '-e', '-c',
                               prefix + '\nmake jobs-test'], cwd=tmp_path,
                              env={**os.environ, 'PATH': str(tmp_path) + os.pathsep + os.environ['PATH']},
                              capture_output=True, text=True, timeout=5)
    assert observed.returncode == 0, observed.stderr
    assert 'EXECUTED_MAKE:jobs-test' in observed.stdout


@pytest.mark.parametrize('prefix', ['python3 broken.py', 'python3 -m py_compile broken.py', 'python3 -m py_compile'])
def test_invalid_python_input_prevents_later_suites(tmp_path, prefix):
    _canonical_control_fixture(tmp_path)
    (tmp_path / 'broken.py').write_text('def broken(:\n')
    errors = check_canonical_ci(tmp_path, _unit_run(prefix + '\n' + '\n'.join(EXPECTED_SUITES)))
    assert any('missing required suite command: make jobs-test' in error for error in errors)


@pytest.mark.parametrize('where', ['workflow', 'job', 'step'])
def test_imported_bash_function_cannot_replace_the_suite_wrapper(tmp_path, where):
    import os
    import subprocess
    binding = {'BASH_FUNC_python3%%': '() { printf "WRAPPER_DISABLED\\n"; }'}
    workflows = _current_workflows()
    workflow = yaml.safe_load(workflows[WORKFLOWS[0]])
    job = workflow['jobs']['unit']
    step = next(item for item in job['steps'] if item.get('name') == 'Execute and record unit CI gate')
    selected = {'workflow': workflow, 'job': job, 'step': step}[where]
    selected['env'] = {**selected.get('env', {}), **binding}
    workflows[WORKFLOWS[0]] = yaml.safe_dump(workflow)
    observed = subprocess.run(['bash', '--noprofile', '--norc', '-e', '-o', 'pipefail', '-c', step['run']],
                              cwd=tmp_path, env={**os.environ, **binding},
                              capture_output=True, text=True, timeout=5)
    assert observed.returncode == 0, observed.stderr
    assert observed.stdout == 'WRAPPER_DISABLED\n'
    errors = check_canonical_ci(ROOT, workflows)
    assert any('missing required suite command: make jobs-test' in error for error in errors)


@pytest.mark.parametrize('where', ['workflow', 'job', 'step'])
def test_normal_yaml_environment_preserves_required_execution(where):
    def change(workflow, job, step):
        selected = {'workflow': workflow, 'job': job, 'step': step}[where]
        selected['env'] = {**selected.get('env', {}), 'CI': 'true', 'AUD03_LABEL': 'normal'}
    assert check_canonical_ci(ROOT, _unit_run('\n'.join(EXPECTED_SUITES), change=change)) == []


@pytest.mark.parametrize('where', ['workflow', 'job', 'step'])
@pytest.mark.parametrize('binding', [
    {'PYTHONHOME': '/definitely-absent-aud03-pythonhome'},
    {'GNUMAKEFLAGS': '--just-print'},
])
def test_runtime_environment_cannot_disable_canonical_wrapper_suites(where, binding):
    def change(workflow, job, step):
        selected = {'workflow': workflow, 'job': job, 'step': step}[where]
        selected['env'] = {**selected.get('env', {}), **binding}
    workflows = _current_workflows()
    workflow = yaml.safe_load(workflows[WORKFLOWS[0]])
    job = workflow['jobs']['unit']
    step = next(step for step in job['steps'] if step.get('name') == 'Execute and record unit CI gate')
    change(workflow, job, step)
    workflows[WORKFLOWS[0]] = yaml.safe_dump(workflow)
    assert check_canonical_ci(ROOT, workflows)


@pytest.mark.parametrize('prefix', [
    'PYTHONHOME=/definitely-absent-aud03-pythonhome',
    'GNUMAKEFLAGS=--just-print',
    'env PYTHONHOME=/definitely-absent-aud03-pythonhome',
    'env GNUMAKEFLAGS=--just-print',
])
def test_runtime_environment_prefix_cannot_disable_required_suite(prefix):
    run = '\n'.join([prefix + ' ' + EXPECTED_SUITES[0], *EXPECTED_SUITES[1:]])
    assert check_canonical_ci(ROOT, _unit_run(run))
