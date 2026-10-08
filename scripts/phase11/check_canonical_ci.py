#!/usr/bin/env python3
"""Enforce hash-locked Python installs and required suites in root CI."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
import argparse
import hashlib
import re
import shlex
import sys
from dataclasses import dataclass

import yaml


ROOT = Path(__file__).resolve().parents[2]
WORKFLOWS = (
    ".github/workflows/quality.yml",
    ".github/workflows/state-of-art-quality.yml",
)
EXPECTED_SUITES = (
    "make jobs-test",
    "make storage-test",
    "env -u RICK_MIGRATION_POSTGRES_TESTS python3 -m pytest -q -p no:cacheprovider infrastructure/scripts/tests",
)
EXPECTED_ARGV = {tuple(shlex.split(command)): command for command in EXPECTED_SUITES}
CANONICAL_LOCK_INPUTS = {
    "requirements/test.in",
    "requirements/runtime.in",
}
PIP_INSTALL = re.compile(r"\bpip\s+install\b")
INCLUDE = re.compile(r"^\s*-(?:r|c)\s+(.+?)\s*$", re.IGNORECASE)
PIN = re.compile(r"^\s*([A-Za-z0-9][A-Za-z0-9._-]*)(?:\[[^]]+\])?\s*==\s*([^\s;]+)")
LOCK_ENTRY = re.compile(r"^([A-Za-z0-9][A-Za-z0-9._-]*)==([^\s\\]+)")
HASH = re.compile(r"--hash=sha256:[0-9a-f]{64}(?:\s*\\)?$")


def _canonical_name(value: str) -> str:
    return re.sub(r"[-_.]+", "-", value).lower()


def _enabled(condition: object) -> bool:
    """Only unconditional/on-success execution can establish a required contract."""
    if condition is None or condition is True:
        return True
    if not isinstance(condition, str):
        return False
    value = condition.strip()
    if value.startswith("${{") and value.endswith("}}"):
        value = value[3:-2].strip()
    return value in {"true", "success()", "always()"}


def _run_blocks(source: str, text: str) -> tuple[list[tuple[str, str]], list[str]]:
    try:
        workflow = yaml.safe_load(text)
    except yaml.YAMLError:
        return [], [f"{source}: workflow YAML is malformed"]
    if not isinstance(workflow, dict) or not isinstance(workflow.get("jobs"), dict):
        return [], [f"{source}: workflow jobs must be a mapping"]
    jobs = workflow["jobs"]

    def reachable(job_id: str, visiting: frozenset[str] = frozenset()) -> bool | None:
        # None denotes an invalid graph; always() can override a skipped
        # prerequisite, but cannot make a missing/cyclic dependency valid.
        job = jobs.get(job_id)
        if job_id in visiting or not isinstance(job, dict):
            return None
        needs = job.get("needs", [])
        if isinstance(needs, str):
            needs = [needs]
        if not isinstance(needs, list) or any(not isinstance(name, str) for name in needs):
            return None
        dependencies = [reachable(name, visiting | {job_id}) for name in needs]
        if any(value is None for value in dependencies):
            return None
        condition = job.get("if")
        if not _enabled(condition):
            return False
        value = condition.strip() if isinstance(condition, str) else ""
        if value.startswith("${{") and value.endswith("}}"):
            value = value[3:-2].strip()
        return value == "always()" or all(dependencies)

    blocks = []
    def execution_env(*values: object) -> bool:
        for value in values:
            if not isinstance(value, dict) or any(_execution_override(name) for name in value):
                return False
        return True
    def defaults_for(value: object) -> dict:
        if not isinstance(value, dict) or not isinstance(value.get("run", {}), dict):
            raise ValueError("workflow/job run defaults must be mappings")
        return value.get("run", {})

    try:
        defaults = defaults_for(workflow.get("defaults", {}))
    except ValueError as exc:
        return [], [f"{source}: {exc}"]
    for job_id, job in workflow["jobs"].items():
        if not isinstance(job, dict):
            continue
        if reachable(job_id) is not True or job.get("continue-on-error", False) is not False:
            continue
        try:
            job_defaults = {**defaults, **defaults_for(job.get("defaults", {}))}
        except ValueError as exc:
            return [], [f"{source}:{job_id}: {exc}"]
        steps = job.get("steps", [])
        if not isinstance(steps, list):
            return [], [f"{source}:{job_id}: workflow steps must be a list"]
        for step in steps:
            if not isinstance(step, dict) or not isinstance(step.get("run"), str):
                continue
            if not _enabled(step.get("if")) or step.get("continue-on-error", False) is not False:
                continue
            settings = {**job_defaults, **step}
            if not execution_env(workflow.get("env", {}), job.get("env", {}), step.get("env", {})):
                continue
            if settings.get("shell", "bash") not in ("bash", "sh"):
                continue
            if settings.get("working-directory", ".") not in (".", "./", "${{ github.workspace }}"):
                continue
            blocks.append((str(job_id), step["run"]))
    return blocks, []


@dataclass(frozen=True)
class _Token:
    text: str
    operator: bool = False
    dynamic: bool = False
    assignment: bool = False


def _shell_tokens(run: str) -> list[_Token]:
    """Lex a whole POSIX shell block; quotes and heredoc bodies are never code.

    This deliberately supports a bounded static grammar, not arbitrary Bash.
    Expansions remain marked rather than evaluated. No workflow code is executed.
    """
    tokens: list[_Token] = []
    word: list[str] = []
    active = quoted = dynamic = False
    assignment = False
    bare_name = True
    heredocs: list[tuple[str, bool]] = []
    waiting: str | None = None
    i = 0

    def flush() -> None:
        nonlocal active, quoted, dynamic, waiting, assignment, bare_name
        if active:
            token = _Token("".join(word), dynamic=dynamic, assignment=assignment)
            tokens.append(token)
            if waiting is not None:
                if token.dynamic or not token.text:
                    raise ValueError("unverifiable heredoc delimiter")
                heredocs.append((token.text, waiting == "<<-"))
                waiting = None
            word.clear()
            active = quoted = dynamic = False
            assignment = False
            bare_name = True

    while i < len(run):
        char = run[i]
        if char in " \t\r":
            flush()
            i += 1
        elif char == "#" and not active:
            end = run.find("\n", i)
            i = len(run) if end < 0 else end
        elif char == "\\":
            if i + 1 >= len(run):
                raise ValueError("trailing shell escape")
            if run[i + 1] != "\n":
                active = True
                if not assignment:
                    bare_name = False
                word.append(run[i + 1])
            i += 2
        elif char in {"'", '"'}:
            active = quoted = True
            if not assignment:
                bare_name = False
            quote = char
            i += 1
            while i < len(run) and run[i] != quote:
                char = run[i]
                if quote == '"' and char == "\\" and i + 1 < len(run) and run[i + 1] in '$`"\\\n':
                    if run[i + 1] != "\n":
                        word.append(run[i + 1])
                    i += 2
                    continue
                dynamic |= quote == '"' and char in "$`"
                word.append(char)
                i += 1
            if i >= len(run):
                raise ValueError("unterminated shell quote")
            i += 1
        elif char in ";&|()<>\n":
            # An unquoted adjacent integer is a redirection fd, not an argv item.
            if char in "<>" and active and not quoted and "".join(word).isdigit():
                word.clear()
                active = False
            flush()
            if waiting is not None:
                raise ValueError("heredoc delimiter is missing")
            operator = next((op for op in ("<<-", "&&", "||", ">>", "<<", ";;", "<&", ">&")
                             if run.startswith(op, i)), char)
            tokens.append(_Token(operator, operator=True))
            i += len(operator)
            if operator in {"<<", "<<-"}:
                waiting = operator
            if operator == "\n":
                for delimiter, strip_tabs in heredocs:
                    while True:
                        if i >= len(run):
                            raise ValueError("unterminated heredoc")
                        end = run.find("\n", i)
                        end = len(run) if end < 0 else end
                        line = run[i:end]
                        i = min(end + 1, len(run))
                        if (line.lstrip("\t") if strip_tabs else line) == delimiter:
                            break
                heredocs.clear()
        else:
            active = True
            if char == "=" and bare_name and re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", "".join(word)):
                assignment = True
            dynamic |= char in "$`*?["
            word.append(char)
            i += 1
    flush()
    if waiting is not None or heredocs:
        raise ValueError("unterminated heredoc")
    return tokens


ASSIGNMENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")
WRAPPER = "scripts/state_of_art/ci_lane_evidence.py"
# Reviewed CLI/shlex/Popen contract. Updating the helper requires an explicit
# review of that contract and update of this version binding; never auto-pin
# the file found in a candidate checkout. Same-path no-ops cannot prove suites.
WRAPPER_SHA256 = "2230849f20be446e55f6d09da950ae8a926aed41a60b38065f2d4c520740fca9"


def _declared_wrapper(argv: list[str]) -> bool:
    return (argv[:1] in (["python"], ["python3"]) and len(argv) > 1
            and Path(argv[1]).as_posix() == WRAPPER
            and not Path(argv[1]).is_absolute() and ".." not in Path(argv[1]).parts)
EXECUTION_OVERRIDES = {
    "PATH", "PYTHON", "PYTHONHOME", "ROOT", "SHELL", "MAKEFLAGS", "GNUMAKEFLAGS", "MFLAGS", "MAKEOVERRIDES",
    "PYTEST_ADDOPTS", "PYTEST_PLUGINS", "BASH_ENV", "ENV", "SHELLOPTS", "BASHOPTS",
}


def _execution_override(name: str) -> bool:
    # Bash imports these environment entries as functions before running the
    # step; they can replace any executable, including the pinned wrapper's
    # interpreter, without changing PATH or the workflow command text.
    return not isinstance(name, str) or name in EXECUTION_OVERRIDES or name.startswith("BASH_FUNC_")


def _argv(tokens: list[str], shell_assignments: set[int] | None = None) -> list[str]:
    """Remove literal assignments and supported env prefixes without losing -u."""
    i = 0
    while (i < len(tokens) and ASSIGNMENT.match(tokens[i])
           and (shell_assignments is None or i in shell_assignments)):
        if _execution_override(tokens[i].partition("=")[0]):
            raise ValueError("unverifiable execution environment override")
        i += 1
    tokens = tokens[i:]
    if not tokens or tokens[0] != "env":
        return tokens
    i = 1
    removals = []
    while i < len(tokens) and tokens[i].startswith("-"):
        if tokens[i] == "--":
            i += 1
            break
        if tokens[i] in {"-u", "--unset"} and i + 1 < len(tokens):
            removals.append(tokens[i + 1])
            i += 2
        elif tokens[i].startswith("--unset="):
            removals.append(tokens[i].partition("=")[2])
            i += 1
        elif tokens[i].startswith("-u") and len(tokens[i]) > 2:
            removals.append(tokens[i][2:])
            i += 1
        else:
            raise ValueError("unsupported env option")
    while i < len(tokens) and ASSIGNMENT.match(tokens[i]):
        if _execution_override(tokens[i].partition("=")[0]):
            raise ValueError("unverifiable execution environment override")
        if tokens[i].partition("=")[0] == "RICK_MIGRATION_POSTGRES_TESTS":
            raise ValueError("migration test opt-in is reintroduced after env unset")
        i += 1
    command = tokens[i:]
    if any(not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name) for name in removals):
        raise ValueError("unverifiable env unset name")
    if command and command[0].startswith("-"):
        raise ValueError("env options cannot follow assignments")
    # This unset is a required part of the migration suite's safety boundary.
    if "RICK_MIGRATION_POSTGRES_TESTS" in removals and command[:3] == ["python3", "-m", "pytest"]:
        command = ["env", "-u", "RICK_MIGRATION_POSTGRES_TESTS", *command]
    return command


def _check_redirection(operator: str, destination: str, root: Path) -> None:
    if operator in {"<<", "<<-"}:
        return  # The lexer already consumed the complete heredoc as data.
    if destination == "/dev/null":
        return
    path = Path(destination)
    if not destination or path.is_absolute() or ".." in path.parts:
        raise ValueError("redirection must use a verifiable workspace path or /dev/null")
    target = root / path
    if any(part.is_symlink() for part in (target, *target.parents)):
        raise ValueError("redirection through a symlink cannot establish execution")
    if not target.parent.is_dir() or target.is_dir():
        raise ValueError("redirection destination cannot be opened")
    if operator == "<" and not target.is_file():
        raise ValueError("redirection input is missing")


def _parse_shell_commands(run: str, root: Path = ROOT) -> list[list[str]]:
    commands: list[list[str]] = []
    current: list[_Token] = []
    redirection = ""
    after_and = False
    previous: list[str] = []
    forbidden = {"if", "then", "else", "elif", "fi", "for", "while", "until", "do", "done",
                 "case", "esac", "function", "{", "}", "!", "eval", "source", ".", "alias",
                 "unalias", "exit", "return", "exec", "break", "continue", "cd", "false",
                 "builtin", "trap", "enable", "export", "unset", "readonly", "local",
                 "declare", "typeset", "shopt", "hash"}

    def finish() -> None:
        nonlocal current, previous, after_and
        if redirection:
            raise ValueError("redirection target is missing")
        if not current:
            return
        argv = _argv([token.text for token in current],
                     {index for index, token in enumerate(current) if token.assignment})
        current = []
        # command only suppresses function lookup; it does not make false/exit
        # or a query (-v/-V) execute the following suites.
        if argv[:1] == ["command"]:
            argv = argv[1:]
            if argv[:1] == ["--"]:
                argv = argv[1:]
            if not argv or argv[0].startswith("-") or argv[0] == "command":
                raise ValueError("unsupported command wrapper")
        if argv[:1] == ["set"]:
            # Only options which strengthen error handling are supported. This
            # excludes noexec, positional rebinding, +e and option abbreviations.
            options = argv[1:]
            while options:
                option = options.pop(0)
                if re.fullmatch(r"-[eu]+", option):
                    continue
                if option == "-o" and options[:1] == ["pipefail"]:
                    options.pop(0)
                    continue
                if re.fullmatch(r"-[eu]*o", option) and options[:1] == ["pipefail"]:
                    options.pop(0)
                    continue
                raise ValueError("unsupported shell execution option")
        if argv and argv[0] in forbidden:
            raise ValueError("unverifiable shell control flow or executable rebinding")
        if argv[:1] in (["bash"], ["sh"]) and argv[1:2] != ["-n"]:
            raise ValueError("nested shell execution cannot establish suite execution")
        if argv[:1] in (["python"], ["python3"]) and argv[1:2] == ["-c"]:
            raise ValueError("inline interpreter control flow cannot be verified")
        if argv[:1] in (["python"], ["python3"]):
            module = argv[1:2] == ["-m"] and argv[2:3] in (["pip"], ["pytest"], ["py_compile"])
            script = len(argv) > 1 and not argv[1].startswith("-") and argv[1].endswith(".py")
            if not (module or script):
                raise ValueError("undeclared interpreter mode cannot establish execution")
        if argv and argv[0] not in {"make", "python", "python3", "pip", "pip3", "bash", "sh",
                                    "true", ":", "printf", "echo", "cat", "set"} and tuple(argv) not in EXPECTED_ARGV:
            raise ValueError("undeclared executable cannot establish command reachability")
        if argv[:1] == ["make"] and (len(argv) != 2 or not re.fullmatch(r"[A-Za-z0-9_.-]+", argv[1])):
            raise ValueError("Make options/overrides cannot establish target execution")
        if argv[:1] == ["printf"] and argv[1:2] == ["-v"]:
            raise ValueError("printf variable rebinding cannot establish execution")
        if (argv[:1] in (["python"], ["python3"]) and len(argv) > 1
                and Path(argv[1]).name == Path(WRAPPER).name):
            if not _declared_wrapper(argv):
                raise ValueError("wrapper invocation is outside the declared repository path")
            _trusted_wrapper(root)
            _wrapper_commands(argv[2:], root)
        if argv[:1] in (["python"], ["python3"]):
            inputs = argv[3:] if argv[1:3] == ["-m", "py_compile"] else (
                argv[1:2] if len(argv) > 1 and argv[1].endswith(".py") else None)
            if inputs is not None:
                if not inputs:
                    raise ValueError("Python compilation requires source inputs")
                for filename in inputs:
                    path = Path(filename)
                    path = path if path.is_absolute() else root / path
                    if ".." in path.parts or not path.resolve().is_relative_to(root.resolve()):
                        raise ValueError("Python source input must stay inside the checkout")
                    try:
                        # Validate the executable input without importing it or
                        # writing the bytecode that py_compile would produce.
                        compile(path.read_bytes(), filename, "exec")
                    except (OSError, SyntaxError, ValueError) as exc:
                        raise ValueError(f"Python source input cannot execute: {filename}") from exc
        if after_and:
            setup = (previous[:3] in (["python", "-m", "pip"], ["python3", "-m", "pip"])
                     and previous[3:4] in (["install"], ["check"]))
            setup |= previous[:2] in (["pip", "install"], ["pip3", "install"])
            setup |= bool(_pytest_paths(previous, root))
            setup |= _declared_wrapper(previous)
            if not (tuple(previous) in EXPECTED_ARGV or setup or previous[:1] in (["true"], [":"], ["set"])):
                raise ValueError("unverifiable conditional command prefix")
        previous = argv
        after_and = False
        if argv:
            commands.append(argv)

    for token in _shell_tokens(run):
        if token.dynamic:
            raise ValueError("shell expansion is not statically verifiable")
        if not token.operator:
            if redirection:
                _check_redirection(redirection, token.text, root)
                redirection = ""
            else:
                current.append(token)
        elif token.text in {"<", ">", ">>", "<<", "<<-"}:
            if redirection:
                raise ValueError("invalid redirection")
            redirection = token.text
        elif token.text in {";", "\n", "&&"}:
            if token.text in {";", "&&"} and not current:
                raise ValueError("command separator has no preceding command")
            finish()
            if token.text == "&&":
                if after_and or not previous:
                    raise ValueError("invalid conditional command")
                after_and = True
            elif token.text == ";" and after_and:
                raise ValueError("conditional command is missing")
        else:
            raise ValueError("unsupported shell operator/branch")
    finish()
    if after_and:
        raise ValueError("conditional command is missing")
    return commands


def _shell_commands(run: str):
    try:
        yield from _parse_shell_commands(run)
    except ValueError:
        return


def _job_commands(source: str, text: str, root: Path, job: str) -> tuple[set[tuple[str, ...]], list[str]]:
    blocks, errors = _run_blocks(source, text)
    commands = set()
    for job_id, run in blocks:
        if job_id != job:
            continue
        try:
            parsed = _parse_shell_commands(run, root)
        except ValueError as exc:
            errors.append(f"{source}:{job_id}: unverifiable shell execution: {exc}")
            continue
        for tokens in parsed:
            executable = tokens[0]
            if _declared_wrapper(tokens):
                try:
                    _trusted_wrapper(root)
                    values = _wrapper_commands(tokens[2:], root)
                except (OSError, ValueError) as exc:
                    errors.append(f"{source}:{job_id}: unverifiable wrapper arguments: {exc}")
                    continue
                for value in values:
                    try:
                        # The declared wrapper uses shlex argv and subprocess without a shell.
                        argv = shlex.split(value)
                    except ValueError:
                        continue
                    # A quoted executable containing spaces is one argv item,
                    # not the several executable/argument items its text resembles.
                    if argv and not ASSIGNMENT.match(argv[0]):
                        try:
                            argv = _argv(argv)
                        except ValueError:
                            continue
                        commands.add(tuple(argv))
            else:
                commands.add(tuple(tokens))
    return commands, errors


def _trusted_wrapper(root: Path) -> None:
    path = root / WRAPPER
    if not path.is_file() or any(part.is_symlink() for part in (path, *path.parents)):
        raise ValueError("declared wrapper must be a regular file without symlink traversal")
    if hashlib.sha256(path.read_bytes()).hexdigest() != WRAPPER_SHA256:
        raise ValueError("declared wrapper implementation SHA-256 does not match the reviewed contract")


def _unit_suite_commands(source: str, text: str, root: Path = ROOT) -> tuple[set[str], list[str]]:
    commands, errors = _job_commands(source, text, root, "unit")
    return {EXPECTED_ARGV[argv] for argv in commands if argv in EXPECTED_ARGV}, errors


def _wrapper_commands(arguments: list[str], root: Path = ROOT) -> list[str]:
    """Validate every invocation, including prefixes which launch no suite.

    Mirror only the pinned helper's argparse contract (never import/execute a
    candidate helper). --help is a successful early exit; invalid argv raises
    instead of being silently ignored ahead of later required commands.
    """
    class HelpExit(Exception):
        pass

    class ContractParser(argparse.ArgumentParser):
        def error(self, message: str) -> None:
            raise ValueError("invalid declared wrapper argv: " + message)

        def exit(self, status: int = 0, message: str | None = None) -> None:
            if status == 0:
                raise HelpExit
            raise ValueError("invalid declared wrapper argv")

        def _print_message(self, message, file=None) -> None:
            pass

    parser = ContractParser()
    parser.add_argument("--lane", required=True)
    parser.add_argument("--gate", action="append", dest="gate_ids", required=True)
    parser.add_argument("--command", action="append", dest="command_texts", required=True)
    parser.add_argument("--output", default=".runtime/ci/lane-evidence.json")
    parser.add_argument("--log-output")
    parser.add_argument("--timeout-seconds", type=int, default=900)
    parser.add_argument("--root", type=Path, default=root)
    try:
        args = parser.parse_args(arguments)
    except HelpExit:
        return []
    if (args.root != root or any(item.partition("=")[0].startswith("--")
                                and "--root".startswith(item.partition("=")[0]) for item in arguments)):
        raise ValueError("wrapper root override is outside the declared checkout contract")
    gates = [value.strip() for value in args.gate_ids if value.strip()]
    if not args.lane.strip() or not gates or len(set(gates)) != len(gates):
        raise ValueError("wrapper lane/gates must be non-empty and gates unique")
    if not 1 <= args.timeout_seconds <= 86_400:
        raise ValueError("wrapper timeout is outside the declared bound")
    output = args.output
    log = args.log_output or str(Path(output).with_suffix(".log"))
    for value in (output, log):
        path = Path(value)
        if not value.strip() or path.is_absolute() or ".." in path.parts or not (root / path).resolve().is_relative_to(root):
            raise ValueError("wrapper evidence path must remain inside the checkout")
    if (root / output).resolve() == (root / log).resolve():
        raise ValueError("wrapper output and raw log must differ")
    # The helper parses *all* command strings before launching any process.
    for value in args.command_texts:
        try:
            argv = shlex.split(value)
        except ValueError as exc:
            raise ValueError("invalid shell-free wrapper command: " + str(exc)) from exc
        if not argv or any(not item for item in argv):
            raise ValueError("wrapper command must contain non-empty argv")
    return args.command_texts


def _read_input(root: Path, relative: str, source_texts: Mapping[str, str]) -> str:
    if relative in source_texts:
        return source_texts[relative]
    return (root / relative).read_text(encoding="utf-8")


MAKE_SUITES = {
    "jobs-test": {
        "apps/worker/tests/test_runtime.py", "apps/worker/tests/test_canonical_queue.py",
        "apps/worker/tests/test_postgres_jobs.py", "packages/jobs/tests",
    },
    "storage-test": {"packages/storage/tests"},
    "ops-static": {"scripts/phase11/test_check_canonical_ci.py"},
}
MAKE_CHECKERS = {
    "validate": "scripts/phase15/check_boundaries.py",
    "ops-static": "scripts/phase11/check_canonical_ci.py",
}


def _make_commands(text: str, root: Path, target: str) -> list[list[str]]:
    """Read literal, phony Make targets without executing Make expansion.

    Includes, conditionals, eval, target-specific variables, custom shell flags,
    ignored errors and unsupported expansion fail closed. Recipes are individual
    shells unless joined by a literal backslash, just as in ordinary GNU Make.
    This proves declared invocation, not the outcome of the invoked test suite.
    """
    rules: dict[str, tuple[list[str], list[str]]] = {}
    variables: dict[str, list[str]] = {}
    phony: set[str] = set()
    active: list[str] = []
    pending = ""
    for raw in text.splitlines():
        if pending:
            raw = pending + raw.lstrip("\t")
            pending = ""
        if raw.endswith("\\"):
            pending = raw[:-1] + " "
            continue
        if raw.startswith("\t"):
            if not active:
                raise ValueError("recipe has no literal target")
            for name in active:
                rules[name][1].append(raw[1:])
            continue
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        active = []
        assignment = re.fullmatch(r"([A-Za-z_.][A-Za-z0-9_.]*)\s*(:=|\?=|=)\s*(.*)", line)
        if assignment:
            name, _operator, value = assignment.groups()
            if name in {"MAKEFLAGS", "MFLAGS", "MAKEOVERRIDES", ".SHELLFLAGS", ".RECIPEPREFIX"}:
                raise ValueError("unsupported Make execution settings")
            if "$" in re.sub(r"\$\([A-Za-z_][A-Za-z0-9_]*\)|\$\{[A-Za-z_][A-Za-z0-9_]*\}", "", value):
                raise ValueError("unsupported Make assignment expansion")
            variables.setdefault(name, []).append(value)
            continue
        header = re.fullmatch(r"([A-Za-z0-9_. -]+):([^:]*)", line)
        if not header:
            raise ValueError("unsupported Make directive or target")
        names = header[1].split()
        dependencies, separator, inline = header[2].partition(";")
        dependencies = dependencies.partition("#")[0].split()
        if names == [".PHONY"]:
            phony.update(dependencies)
            continue
        if any(name.startswith(".") for name in names):
            raise ValueError("unsupported Make special target")
        if any(not re.fullmatch(r"[A-Za-z0-9_.-]+", name) for name in dependencies):
            raise ValueError("unsupported Make prerequisite")
        for name in names:
            if name in rules:
                raise ValueError("duplicate Make target declaration")
            rules[name] = (list(dependencies), [inline] if separator else [])
        active = names
    if pending:
        raise ValueError("unterminated Make continuation")
    expected = {"ROOT": "$(CURDIR)", "PYTHON": "python3", "SHELL": "/usr/bin/env bash"}
    for name, value in expected.items():
        if variables.get(name) != [value]:
            raise ValueError(f"unsupported or rebound Make {name}")

    def collect(name: str, visiting: set[str]) -> list[list[str]]:
        if name in visiting or name not in rules or name not in phony:
            raise ValueError(f"missing, cyclic or non-phony Make target: {name}")
        dependencies, recipes = rules[name]
        commands = []
        for dependency in dependencies:
            commands.extend(collect(dependency, visiting | {name}))
        for recipe in recipes:
            recipe = recipe.lstrip()
            if recipe.startswith("@"):
                recipe = recipe[1:]
            if recipe.startswith(("-", "+", "@")):
                raise ValueError("unsupported Make recipe execution prefix")
            for variable, value in {"ROOT": str(root), "CURDIR": str(root), "PYTHON": "python3"}.items():
                recipe = recipe.replace(f"$({variable})", value).replace("${" + variable + "}", value)
            if "$" in recipe:
                raise ValueError("unsupported Make recipe expansion")
            commands.extend(_parse_shell_commands(recipe, root))
        return commands

    return collect(target, set())


def _pytest_paths(argv: list[str], root: Path) -> set[str]:
    if argv[:3] not in (["python", "-m", "pytest"], ["python3", "-m", "pytest"]):
        return set()
    paths: set[str] = set()
    options = iter(argv[3:])
    for argument in options:
        if argument in {"-q", "--quiet", "-v", "--verbose"}:
            continue
        if argument == "-p" and next(options, "") == "no:cacheprovider":
            continue
        if argument.startswith("-"):
            # Filters, collection-only, plugins and config overrides cannot
            # demonstrate execution of the entire required suite.
            return set()
        path = Path(argument)
        if not path.is_absolute():
            path = root / path
        if ".." in path.parts or not path.is_relative_to(root):
            return set()
        paths.add(path.relative_to(root).as_posix())
    return paths


def _check_make_contract(root: Path, sources: Mapping[str, str]) -> list[str]:
    errors = []
    text = _read_input(root, "Makefile", sources)
    for target in sorted(MAKE_SUITES.keys() | MAKE_CHECKERS.keys()):
        try:
            commands = _make_commands(text, root, target)
        except ValueError as exc:
            errors.append(f"Makefile:{target}: unverifiable recipe execution: {exc}")
            continue
        paths = set().union(*(_pytest_paths(argv, root) for argv in commands))
        for path in sorted(MAKE_SUITES.get(target, set()) - paths):
            errors.append(f"Makefile:{target}: missing executable pytest suite: {path}")
        checker = MAKE_CHECKERS.get(target)
        if checker and not any(argv[:1] in (["python"], ["python3"])
                               and len(argv) == 2 and argv[1] in {checker, str(root / checker)}
                               for argv in commands):
            errors.append(f"Makefile:{target}: missing executable checker: {checker}")
    return errors


def _pins(text: str) -> dict[str, str]:
    pins: dict[str, str] = {}
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or INCLUDE.match(line):
            continue
        match = PIN.match(line)
        if match is not None:
            pins[_canonical_name(match.group(1))] = match.group(2)
    return pins


def _lock_versions_and_hash_errors(lock_text: str, source: str) -> tuple[dict[str, str], list[str]]:
    versions: dict[str, str] = {}
    errors: list[str] = []
    current: str | None = None
    current_has_hash = False

    def finish() -> None:
        if current is not None and not current_has_hash:
            errors.append(f"{source}: {current} has no SHA-256 hash")

    for line in lock_text.splitlines():
        entry = LOCK_ENTRY.match(line)
        if entry is not None:
            finish()
            current = _canonical_name(entry.group(1))
            current_has_hash = False
            versions[current] = entry.group(2)
        elif current is not None and HASH.match(line.strip()) is not None:
            current_has_hash = True
    finish()
    if not versions:
        errors.append(f"{source}: no pinned package entries found")
    return versions, errors


def _generated_inputs(root: Path, lock_relative: str) -> tuple[list[str], list[str], str]:
    lock_path = root / lock_relative
    if not lock_path.is_file():
        return [], [f"{lock_relative}: referenced requirements lock does not exist"], ""
    lock_text = lock_path.read_text(encoding="utf-8")
    lines = lock_text.splitlines()
    provenance = next(
        (line.removeprefix("#    ") for line in lines[:8] if line.startswith("#    uv pip compile ")),
        None,
    )
    if provenance is None:
        return [], [f"{lock_relative}: missing generated uv compile provenance"], lock_text
    try:
        command = shlex.split(provenance)
    except ValueError as exc:
        return [], [f"{lock_relative}: invalid compile provenance: {exc}"], lock_text
    errors: list[str] = []
    if "--generate-hashes" not in command:
        errors.append(f"{lock_relative}: compile provenance does not enable --generate-hashes")
    output_index = next(
        (index for index, argument in enumerate(command) if argument == "--output-file" or argument.startswith("--output-file=")),
        None,
    )
    if output_index is None:
        return [], errors + [f"{lock_relative}: compile provenance is missing --output-file"], lock_text
    if command[output_index] == "--output-file":
        if output_index + 1 >= len(command):
            return [], errors + [f"{lock_relative}: compile provenance has no output path"], lock_text
        output_path = command[output_index + 1]
        source_start = output_index + 2
    else:
        output_path = command[output_index].partition("=")[2]
        source_start = output_index + 1
    if Path(output_path).as_posix() != Path(lock_relative).as_posix():
        errors.append(f"{lock_relative}: compile provenance names a different output file")
    source_paths = [argument for argument in command[source_start:] if not argument.startswith("-")]
    if not source_paths:
        errors.append(f"{lock_relative}: generated lock has no .in source input")
    normalized_sources: list[str] = []
    for source_path in source_paths:
        path = Path(source_path)
        if path.is_absolute() or ".." in path.parts:
            errors.append(f"{lock_relative}: source input must remain inside the repository: {source_path}")
        else:
            normalized_sources.append(path.as_posix())
    _versions, hash_errors = _lock_versions_and_hash_errors(lock_text, lock_relative)
    errors.extend(hash_errors)
    return normalized_sources, errors, lock_text


def _collect_lock_inputs(
    root: Path,
    lock_relative: str,
    *,
    seen_locks: set[str],
    source_inputs: set[str],
    source_texts: Mapping[str, str],
) -> list[str]:
    if lock_relative in seen_locks:
        return []
    seen_locks.add(lock_relative)
    sources, errors, lock_text = _generated_inputs(root, lock_relative)
    lock_versions, _hash_errors = _lock_versions_and_hash_errors(lock_text, lock_relative)
    for source_relative in sources:
        source_inputs.add(source_relative)
        try:
            source_text = _read_input(root, source_relative, source_texts)
        except OSError:
            errors.append(f"{source_relative}: generated lock input does not exist")
            continue
        for package, version in _pins(source_text).items():
            if lock_versions.get(package) != version:
                errors.append(
                    f"{lock_relative}: pin {package}=={version} from {source_relative} is absent or mismatched"
                )
        for line in source_text.splitlines():
            if not line.strip() or line.lstrip().startswith("#"):
                continue
            include = INCLUDE.match(line)
            if include is None:
                continue
            included = (Path(source_relative).parent / include.group(1)).as_posix()
            if included.endswith(".lock"):
                errors.extend(
                    _collect_lock_inputs(
                        root,
                        included,
                        seen_locks=seen_locks,
                        source_inputs=source_inputs,
                        source_texts=source_texts,
                    )
                )
    return errors


def _check_declared_quality_pins(
    root: Path,
    source_texts: Mapping[str, str],
    lock_texts: Mapping[str, str],
) -> list[str]:
    errors: list[str] = []
    test_input_path = "requirements/test.in"
    try:
        test_pins = _pins(_read_input(root, test_input_path, source_texts))
        state_pins = _pins((root / "scripts/state_of_art/requirements.txt").read_text(encoding="utf-8"))
    except OSError as exc:
        return [f"required quality dependency input is unavailable: {exc}"]
    expected_pins = {**state_pins, "pip-audit": "2.9.0"}
    for package, version in sorted(expected_pins.items()):
        if test_pins.get(package) != version:
            errors.append(f"{test_input_path}: required pin {package}=={version} is missing or mismatched")
    test_lock = lock_texts.get("requirements/test.lock", "")
    lock_versions, lock_errors = _lock_versions_and_hash_errors(test_lock, "requirements/test.lock")
    errors.extend(lock_errors)
    for package, version in sorted(expected_pins.items()):
        if lock_versions.get(package) != version:
            errors.append(f"requirements/test.lock: required pin {package}=={version} is missing or mismatched")
    return errors


def _workflow_installs(source: str, text: str, root: Path = ROOT) -> tuple[list[str], set[str]]:
    blocks, errors = _run_blocks(source, text)
    locks: set[str] = set()
    for job_id, run in blocks:
        try:
            parsed = _parse_shell_commands(run, root)
        except ValueError as exc:
            if PIP_INSTALL.search(run):
                errors.append(f"{source}:{job_id}: unverifiable pip install execution: {exc}")
            continue
        for tokens in parsed:
            executable = tokens[0]
            pip_install = ((executable in {"python", "python3"} and tokens[1:4] == ["-m", "pip", "install"])
                           or (executable in {"pip", "pip3"} and tokens[1:2] == ["install"]))
            if not pip_install:
                continue
            for option in ("--require-hashes", "--only-binary=:all:"):
                if option not in tokens:
                    errors.append(f"{source}:{job_id}: pip install must include {option}")
            requirements = []
            for index, token in enumerate(tokens):
                if token in {"-r", "--requirement"} and index + 1 < len(tokens):
                    requirements.append(tokens[index + 1])
                elif token.startswith("--requirement="):
                    requirements.append(token.partition("=")[2])
                elif token.startswith("-r") and token != "-r":
                    requirements.append(token[2:])
            if not requirements:
                errors.append(f"{source}:{job_id}: pip install must reference a generated requirements lock")
                continue
            for requirement in requirements:
                lock_path = Path(requirement)
                if (lock_path.is_absolute() or ".." in lock_path.parts or lock_path.suffix != ".lock"
                        or not lock_path.as_posix().startswith("requirements/")):
                    errors.append(f"{source}:{job_id}: lock path must be a root requirements lock")
                    continue
                locks.add(lock_path.as_posix())
    return errors, locks


def check_canonical_ci(
    root: Path = ROOT,
    workflow_texts: Mapping[str, str] | None = None,
    source_texts: Mapping[str, str] | None = None,
) -> list[str]:
    """Check root workflow installs, generated lock inputs, pins, and suite wiring."""
    root = root.resolve()
    sources = {} if source_texts is None else dict(source_texts)
    texts = (
        {relative: (root / relative).read_text(encoding="utf-8") for relative in WORKFLOWS}
        if workflow_texts is None
        else dict(workflow_texts)
    )
    errors: list[str] = []
    referenced_locks: set[str] = set()
    for workflow in WORKFLOWS:
        text = texts.get(workflow)
        if text is None:
            errors.append(f"{workflow}: canonical workflow fixture is missing")
            continue
        install_errors, locks = _workflow_installs(workflow, text, root)
        errors.extend(install_errors)
        referenced_locks.update(locks)

    quality = texts.get(WORKFLOWS[0], "")
    suite_commands, suite_errors = _unit_suite_commands(WORKFLOWS[0], quality, root)
    errors.extend(suite_errors)
    for suite in EXPECTED_SUITES:
        if suite not in suite_commands:
            errors.append(f"{WORKFLOWS[0]}: missing required suite command: {suite}")
    fast_commands, fast_errors = _job_commands(WORKFLOWS[0], quality, root, "fast")
    errors.extend(fast_errors)
    for target in ("validate", "ops-static"):
        if ("make", target) not in fast_commands:
            errors.append(f"{WORKFLOWS[0]}: missing executable fast checker target: make {target}")
    errors.extend(_check_make_contract(root, sources))

    all_sources: set[str] = set()
    lock_texts: dict[str, str] = {}
    for lock in sorted(referenced_locks):
        errors.extend(
            _collect_lock_inputs(
                root,
                lock,
                seen_locks=set(),
                source_inputs=all_sources,
                source_texts=sources,
            )
        )
        lock_path = root / lock
        if lock_path.is_file():
            lock_texts[lock] = lock_path.read_text(encoding="utf-8")
    for expected in sorted(CANONICAL_LOCK_INPUTS - all_sources):
        errors.append(f"{expected}: canonical lock input is not referenced by an installed lock")
    errors.extend(_check_declared_quality_pins(root, sources, lock_texts))
    return errors


def main() -> int:
    try:
        errors = check_canonical_ci()
    except OSError as exc:
        print(f"FAIL: unable to inspect canonical CI inputs: {exc}", file=sys.stderr)
        return 1
    for error in errors:
        print(f"FAIL: {error}")
    if errors:
        return 1
    print("PASS: canonical Python installs are hash-locked and required suites are present")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
