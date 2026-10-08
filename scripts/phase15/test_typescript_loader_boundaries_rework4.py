"""Public boundary regressions for CommonJS and Node loader aliases (AUD03-24)."""

import json
import subprocess

import pytest

from scripts.phase15 import check_boundaries


FORBIDDEN_LOADERS = [
    'const x = module.require("rick-professor");',
    'const x = module["require"]("rick-professor");',
    'const x = module["re" + "quire"]("rick-professor");',
    'const m = module; const x = m.require("rick-professor");',
    'const load = module.require; const x = load("rick-professor");',
    'const {require: load} = module; const x = load("rick-professor");',
    'const load = require; const alias = load; alias("rick-professor");',
    'let load; load = module.require; load("rick-professor");',
    'declare const require: any; require("rick-professor");',
    'declare const module: any; module.require("rick-professor");',
    'import {createRequire} from "node:module"; const load = createRequire(import.meta.url); load("rick-professor");',
    'import {createRequire as factory} from "module"; const load = factory(import.meta.url); load("rick-professor");',
    'import * as mod from "node:module"; mod.createRequire(import.meta.url)("rick-professor");',
    'import mod from "node:module"; const load = mod.createRequire(import.meta.url); load("rick-professor");',
    'import mod = require("node:module"); mod.createRequire(import.meta.url)("rick-professor");',
    'const {createRequire: factory} = require("node:module"); factory(import.meta.url)("rick-professor");',
    'const mod = require("module"); const factory = mod.createRequire; factory(import.meta.url)("rick-professor");',
    'const load = (module.require as Function); load("rick-professor");',
    'require.call(null, "rick-professor");',
    'module.require.apply(module, ["rick-professor"]);',
    'const load = require.bind(null); load("rick-professor");',
    'const key = "require"; module[key]("rick-professor");',
    'const key = "require"; const load = module[key]; load("rick-professor");',
    'const name = "rick-professor"; module.require(name);',
    'import {createRequire} from "node:module"; const load = createRequire(import.meta.url); load(name);',
    'module.require();',
    'require(...["rick-professor"]);',
    'let load; ({require: load} = module); load("rick-professor");',
    'const holder = {load: module.require}; holder.load("rick-professor");',
    'const load = (0, require); load("rick-professor");',
    'function factory() { return require; } factory()("rick-professor");',
    'import {createRequire} from "node:module"; const make = createRequire.bind(null); make(import.meta.url)("rick-professor");',
    'const holder = {require}; holder.require("rick-professor");',
    'const holder = {module}; holder.module.require("rick-professor");',
    'import {createRequire} from "node:module"; const holder = {createRequire}; holder.createRequire(import.meta.url)("rick-professor");',
]


FERMAT_LOADERS = [
    'declare function require(x:string):any; require("rick-professor");',
    'declare function require(x:string):any; const load=require; load("rick-professor");',
    'declare namespace module {function require(x:string):any;} module.require("rick-professor");',
    'declare namespace module {function require(x:string):any;} const load=module.require; load("rick-professor");',
    'namespace module {export interface Shape {x:string}} module.require("rick-professor");',
    'module.constructor.createRequire(__filename)("rick-professor");',
    'import {Module} from "node:module"; Module.createRequire(__filename)("rick-professor");',
    'import {Module as M} from "module"; const load=M.createRequire(__filename); load("rick-professor");',
    'import * as mod from "node:module"; mod.Module.createRequire(__filename)("rick-professor");',
    'import mod from "node:module"; mod.Module.createRequire(import.meta.url)("rick-professor");',
    'import mod from "node:module"; mod.createRequire(import.meta.url)("rick-professor");',
    'import {default as M} from "node:module"; M.createRequire(import.meta.url)("rick-professor");',
    'const {Module:M}=require("node:module"); M.createRequire(__filename)("rick-professor");',
    'const {constructor:C}=module; const {createRequire:f}=C; f(__filename)("rick-professor");',
    'const C=module.constructor; C["create"+"Require"](__filename)("rick-professor");',
    'import * as mod from "node:module"; mod.default.createRequire(import.meta.url)("rick-professor");',
    'const k="createRequire"; module.constructor[k](__filename)("rick-professor");',
    'import {Module} from "node:module"; const name="rick-professor"; Module.createRequire(__filename)(name);',
    'import {Module} from "node:module"; const factory=Module.createRequire.bind(null); factory(__filename)("rick-professor");',
]


@pytest.mark.parametrize('source', FERMAT_LOADERS)
def test_erased_declarations_and_module_constructor_factories_cannot_hide_dependencies(tmp_path, source):
    path = tmp_path / 'apps/web/src/sample.tsx'
    path.parent.mkdir(parents=True)
    path.write_text(source)
    errors = check_boundaries.check_source_boundaries(tmp_path)
    assert errors, source
    assert any('legacy' in error or 'statically' in error for error in errors), errors


@pytest.mark.parametrize('source', [
    'function require(x:string) {return x;} const load=require; load("rick-professor");',
    'function require(x:string):string; function require(x:string){return x;} require("rick-professor");',
    'declare namespace require {interface Shape {x:string}} function require(x:string){return x;} require("rick-professor");',
    'namespace module {export function require(x:string){return x;}} module.require("rick-professor");',
    'declare function require(x:string):any; function f(require:(x:string)=>string){return require("rick-professor");}',
    'const Module={createRequire:(x:string)=>(name:string)=>name}; Module.createRequire("data")("rick-professor");',
    'type Text="Module.createRequire(__filename)(rick-professor)";',
    'declare function require(x:string):any; require("typescript");',
    'declare namespace module {function require(x:string):any;} module.require("typescript");',
    'import {Module} from "node:module"; Module.createRequire(__filename)("rick_professor");',
    'import type {Module} from "node:module"; type M=typeof Module;',
])
def test_real_runtime_shadows_allowed_factories_and_type_data_remain_positive(tmp_path, source):
    path = tmp_path / 'apps/web/src/sample.tsx'
    path.parent.mkdir(parents=True)
    path.write_text(source)
    assert check_boundaries.check_source_boundaries(tmp_path) == []


@pytest.mark.parametrize('source,format,loads', [
    (FERMAT_LOADERS[0], 'cjs', True), (FERMAT_LOADERS[1], 'cjs', True),
    (FERMAT_LOADERS[2], 'cjs', True), (FERMAT_LOADERS[5], 'cjs', True),
    (FERMAT_LOADERS[6], 'cjs', True), (FERMAT_LOADERS[8], 'cjs', True),
    (FERMAT_LOADERS[9], 'mjs', True),
    ('function require(x:string){return x;} require("rick-professor");', 'cjs', False),
])
def test_actual_compiler_erasure_and_node_factory_execution(tmp_path, source, format, loads):
    dependency = tmp_path / 'node_modules/rick-professor/index.js'
    dependency.parent.mkdir(parents=True)
    dependency.write_text('console.log("SYNTHETIC_DEPENDENCY_EXECUTED"); module.exports = {};\n')
    transpiler = tmp_path / 'transpile.cjs'
    compiler = check_boundaries.ROOT / 'apps/web/node_modules/typescript'
    transpiler.write_text('const fs=require("node:fs"), ts=require(' + json.dumps(str(compiler)) + '); '
                          'const input=JSON.parse(fs.readFileSync(0,"utf8")); '
                          'process.stdout.write(ts.transpileModule(input.source,{compilerOptions:{target:ts.ScriptTarget.ES2022,'
                          'module:input.format==="mjs"?ts.ModuleKind.ESNext:ts.ModuleKind.CommonJS}}).outputText);')
    result = subprocess.run(['node', str(transpiler)], input=json.dumps({'source': source, 'format': format}),
                            capture_output=True, text=True, check=True, timeout=15)
    emitted = tmp_path / ('emitted.' + format)
    emitted.write_text(result.stdout)
    executed = subprocess.run(['node', str(emitted)], capture_output=True, text=True, timeout=15)
    assert executed.returncode == 0, executed.stderr
    assert ('SYNTHETIC_DEPENDENCY_EXECUTED' in executed.stdout) is loads


@pytest.mark.parametrize('source', FORBIDDEN_LOADERS)
def test_actual_or_unverifiable_loaders_are_rejected_at_public_boundary(tmp_path, source):
    path = tmp_path / 'apps/web/src/sample.tsx'
    path.parent.mkdir(parents=True)
    path.write_text(source)
    errors = check_boundaries.check_source_boundaries(tmp_path)
    assert errors, source
    assert any('legacy' in error or 'statically' in error for error in errors), errors


@pytest.mark.parametrize('source', [
    '// module.require("rick-professor");\nexport const x = 1;',
    '/* module[key]("rick-professor"); */ export const x = 1;',
    'const text = "module.require(\'rick-professor\')";',
    'const text = `createRequire(import.meta.url)("rick-professor")`;',
    'type Text = "module.require(\'rick-professor\')";',
    'type Loader = typeof require; const text = "rick-professor";',
    'export const Component = () => <div>module.require("rick-professor")</div>;',
    'module.require("typescript");',
    'import {createRequire} from "node:module"; const load = createRequire(import.meta.url); load("rick_professor");',
    'const module = {require: (text: string) => text}; module.require("rick-professor");',
    'const require = (text: string) => text; require("rick-professor");',
    'const load = (text: string) => text; load("rick-professor");',
    'import {createRequire} from "node:module"; function text(createRequire: (x: string) => (y: string) => string) { const load = createRequire("data"); return load("rick-professor"); }',
])
def test_loader_spelling_in_data_and_unrelated_bindings_is_not_a_dependency(tmp_path, source):
    path = tmp_path / 'apps/web/src/sample.tsx'
    path.parent.mkdir(parents=True)
    path.write_text(source)
    assert check_boundaries.check_source_boundaries(tmp_path) == []


@pytest.mark.parametrize('relative', ['apps/api/src/adapters/legacy/sample.ts', 'packages/sample/tests/sample.ts'])
def test_existing_adapter_and_test_exceptions_are_preserved_for_real_loaders(tmp_path, relative):
    path = tmp_path / relative
    path.parent.mkdir(parents=True)
    path.write_text('module.require("rick-professor");')
    assert check_boundaries.check_source_boundaries(tmp_path) == []


def test_parser_reports_real_loader_dependency_separately_from_data():
    parser = check_boundaries.ROOT / 'scripts/phase15/typescript_imports.cjs'
    payload = [{'path': 'actual.ts', 'source': source} for source in FORBIDDEN_LOADERS[:3]]
    payload += [{'path': 'data.ts', 'source': 'type Text = "module.require(\'rick-professor\')";'}]
    result = subprocess.run(['node', str(parser)], input=json.dumps(payload), capture_output=True,
                            text=True, check=True, timeout=20)
    parsed = json.loads(result.stdout)
    assert all('rick-professor' in entry['modules'] and not entry['errors'] for entry in parsed[:3])
    assert parsed[3] == {'path': 'data.ts', 'modules': [], 'errors': []}


def test_actual_node_loader_observation_uses_only_a_synthetic_dependency(tmp_path):
    dependency = tmp_path / 'node_modules/rick-professor/index.js'
    dependency.parent.mkdir(parents=True)
    dependency.write_text('console.log("DEPENDENCY_EXECUTED:rick-professor"); module.exports = {};\n')
    for filename, source in [
        ('module.cjs', FORBIDDEN_LOADERS[0]),
        ('factory.mjs', FORBIDDEN_LOADERS[10]),
    ]:
        path = tmp_path / filename
        path.write_text(source)
        result = subprocess.run(['node', str(path)], capture_output=True, text=True, timeout=10)
        assert result.returncode == 0, result.stderr
        assert 'DEPENDENCY_EXECUTED:rick-professor' in result.stdout


@pytest.mark.parametrize('source', [
    'module.constructor._load("rick-professor", {paths: module.paths});',
    'const Module=require("node:module"); Module._load("rick-professor", {paths: module.paths});',
    'import {Module} from "node:module"; Module._load("rick-professor", {paths: module.paths});',
    'const load=module.constructor._load; load("rick-professor", {paths: module.paths});',
    'module.constructor["_"+"load"]("rick-professor", {paths: module.paths});',
])
def test_node_internal_loader_rejects_direct_legacy_dependency(tmp_path, source):
    path = tmp_path / 'apps/web/src/sample.tsx'
    path.parent.mkdir(parents=True)
    path.write_text(source)
    assert any('legacy import rick-professor' in error
               for error in check_boundaries.check_source_boundaries(tmp_path))


@pytest.mark.parametrize('source', [
    'module.constructor._load("typescript", {paths: module.paths});',
    'const Module={_load:(name:string)=>name}; Module._load("rick-professor");',
    'const text=\'module.constructor._load("rick-professor")\';',
])
def test_node_internal_loader_preserves_allowed_imports_and_local_data(tmp_path, source):
    path = tmp_path / 'apps/web/src/sample.tsx'
    path.parent.mkdir(parents=True)
    path.write_text(source)
    assert check_boundaries.check_source_boundaries(tmp_path) == []


def test_node_internal_loader_rejection_matches_synthetic_runtime(tmp_path):
    source = 'module.constructor._load("rick-professor", {paths: module.paths});'
    production = tmp_path / 'apps/web/src/sample.tsx'
    production.parent.mkdir(parents=True)
    production.write_text(source)
    dependency = tmp_path / 'node_modules/rick-professor/index.js'
    dependency.parent.mkdir(parents=True)
    dependency.write_text('console.log("SYNTHETIC_LEGACY_EXECUTED"); module.exports={};\n')
    script = tmp_path / 'observe.cjs'
    script.write_text(source)
    result = subprocess.run(['node', str(script)], capture_output=True, text=True, timeout=10)
    assert result.returncode == 0, result.stderr
    assert 'SYNTHETIC_LEGACY_EXECUTED' in result.stdout
    assert any('legacy import rick-professor' in error
               for error in check_boundaries.check_source_boundaries(tmp_path))


@pytest.mark.parametrize('source,loads', [
    # Execution order and skipped initializers must retain the CJS loaders.
    ('require("rick-professor"); var require=(name:string)=>name;', True),
    ('module.require("rick-professor"); var module={require:(name:string)=>name};', True),
    ('if(false) { var require=(name:string)=>name; } require("rick-professor");', True),
    ('if(false) { var module={require:(name:string)=>name}; } module.require("rick-professor");', True),
    # Harmless declarations and uninitialized redeclarations preserve replacements.
    ('var require; require=(name:string)=>name; const marker=1; require("rick-professor");', False),
    ('let load=require; load=(name:string)=>name; const marker=1; load("rick-professor");', False),
    ('var module; module={require:(name:string)=>name}; const marker=1; module.require("rick-professor");', False),
    ('var require=(name:string)=>name; var require; require("rick-professor");', False),
    ('var module={require:(name:string)=>name}; var module; module.require("rick-professor");', False),
    ('var load=require; load=(name:string)=>name; var load; load("rick-professor");', False),
    ('let load=require; load("rick-professor"); load=(name:string)=>name;', True),
    ('var require=(name:string)=>name; const value=require("rick-professor");', False),
    ('var require; if(true) { require("rick-professor"); var require=(name:string)=>name; }', True),
    ('var require=(name:string)=>name; function restore(){require=module.require.bind(module);} restore(); require("rick-professor");', True),
    ('let load=require; load=(name:string)=>name; if(true) load=require; load("rick-professor");', True),
    ('var require!: NodeJS.Require; require("rick-professor");', True),
    ('var module!: NodeJS.Module; module.require("rick-professor");', True),
    ('var require: NodeJS.Require = require; require("rick-professor");', True),
    ('var module: NodeJS.Module = module; module.require("rick-professor");', True),
    ('var require = (name:string) => name; require("rick-professor");', False),
    ('var module = {require:(name:string)=>name}; module.require("rick-professor");', False),
    ('var require; require = (name:string)=>name; require("rick-professor");', False),
    ('var module; module = {require:(name:string)=>name}; module.require("rick-professor");', False),
    ('let load = require; load = (name:string)=>name; load("rick-professor");', False),
    ('var require; require("rick-professor"); require = (name:string)=>name;', True),
    ('var require; if (false) require = (name:string)=>name; require("rick-professor");', True),
    ('let load = require; if (false) load = (name:string)=>name; load("rick-professor");', True),
    ('var require; const replace = () => { require = (name:string)=>name; }; require("rick-professor");', True),
    ('let load = require; const replace = () => { load = (name:string)=>name; }; load("rick-professor");', True),
    ('var require; { let require = (name:string)=>name; } require("rick-professor");', True),
    ('function local(require:(name:string)=>string) { var require; return require("rick-professor"); } local(name=>name);', False),
    ('function local() { var require = (name:string)=>name; return require("rick-professor"); } local();', False),
])
def test_cjs_var_redeclaration_matches_emitted_runtime(tmp_path, source, loads):
    production = tmp_path / 'apps/web/src/sample.tsx'
    production.parent.mkdir(parents=True)
    production.write_text(source)
    dependency = tmp_path / 'node_modules/rick-professor/index.js'
    dependency.parent.mkdir(parents=True)
    dependency.write_text('console.log("SYNTHETIC_LEGACY_EXECUTED"); module.exports={};\n')
    compiler = check_boundaries.ROOT / 'apps/web/node_modules/typescript'
    transpiler = tmp_path / 'transpile.cjs'
    transpiler.write_text('const fs=require("node:fs"), ts=require(' + json.dumps(str(compiler)) + ');'
                          'process.stdout.write(ts.transpileModule(fs.readFileSync(0,"utf8"),'
                          '{compilerOptions:{module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2022}}).outputText);')
    emitted = subprocess.run(['node', str(transpiler)], input=source, capture_output=True,
                             text=True, check=True, timeout=10)
    script = tmp_path / 'observe.cjs'
    script.write_text(emitted.stdout)
    observed = subprocess.run(['node', str(script)], capture_output=True, text=True, timeout=10)
    assert observed.returncode == 0, observed.stderr
    assert ('SYNTHETIC_LEGACY_EXECUTED' in observed.stdout) is loads
    errors = check_boundaries.check_source_boundaries(tmp_path)
    assert bool(errors) is loads, errors
    if loads:
        assert any('legacy import rick-professor' in error for error in errors)
