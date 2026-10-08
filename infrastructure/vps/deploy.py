#!/usr/bin/env python3
"""Fail-closed local VPS operations; no remote SSH, promotion or volume deletion."""
from __future__ import annotations
import argparse
import base64
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
from urllib.parse import unquote, urlsplit
from trusted_code import modules as captured_modules, release_errors
from assets import captured_tls, prove_readable, review_inputs, stage
from contracts import IDENTITY, ISSUER, PREDICATE, REPO, Refusal, capture, check_hash, images, immutable, load, parse, postgres_endpoint

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
INFRA = {'POSTGRES_IMAGE':'docker.io/library/postgres','REDIS_IMAGE':'docker.io/library/redis',
    'QDRANT_IMAGE':'docker.io/qdrant/qdrant','MINIO_IMAGE':'docker.io/minio/minio',
    'MC_IMAGE':'docker.io/minio/mc','CADDY_IMAGE':'docker.io/library/caddy'}
FIXED = {'RICK_ENV':'production','RICK_IDENTITY_MODE':'production','RICK_API_CHAT_BACKEND':'professor',
    'RICK_IDENTITY_POLICY':'postgres-local-v1',
    'RICK_API_COMPOSITION':'deployment_composition:build_api_inputs',
    'RICK_WORKER_COMPOSITION':'deployment_composition:build_worker','SESSION_COOKIE_SECURE':'true',
    'SESSION_COOKIE_SAMESITE':'strict','RICK_CLINICAL_CASES_ENABLED':'false','RICK_CLINICAL_CASES_D04_ENABLED':'false',
    'RICK_REDIS_REQUIRE_TLS':'true','RICK_REDIS_REQUIRE_AUTH':'true',
    'RICK_REDIS_VERIFY_TLS':'true','RICK_REDIS_TLS_CA_FILE':'/tls/ca-bundle.crt',
    'RICK_QDRANT_URL':'https://vectors.internal','RICK_OBJECT_STORE_ENDPOINT':'https://objects.internal'}

def read_env(path):
    return parse_env(capture(path, private=True))

def parse_env(data, template=None):
    expected = {line.split('=',1)[0] for line in (template if template is not None else (HERE/'config.env.example').read_bytes()).decode('utf-8').splitlines()
                if line and not line.startswith('#')}
    env = {}
    for line in data.decode('utf-8').splitlines():
        if not line or line.startswith('#'):
            continue
        key, separator, value = line.partition('=')
        if not separator or key not in expected or key in env:
            raise Refusal('config contains unknown or duplicate field')
        # Literal env avoids Compose interpolation of $, newlines, quotes or
        # shell metacharacters. Generate credentials with URL-safe alphabet.
        optional_oidc = key in {'RICK_OIDC_ISSUER','RICK_OIDC_AUDIENCE','RICK_OIDC_JWKS_URL'}
        if (not value and not optional_oidc) or any(c.isspace() or ord(c)<32 for c in value) or any(c in value for c in '$`\'"\\'):
            raise Refusal('missing or invalid config field: '+key)
        env[key] = value
    if set(env) != expected:
        raise Refusal('missing config fields: '+','.join(sorted(expected-set(env))))
    for key, prefix in INFRA.items():
        immutable(env[key], prefix)
    for key, value in FIXED.items():
        if env[key] != value:
            raise Refusal('closed deployment setting required: '+key)
    for key in ('VPS_PROJECT','POSTGRES_DB','POSTGRES_USER'):
        if not re.fullmatch('[a-z][a-z0-9_-]{1,62}',env[key]):
            raise Refusal('invalid config field: '+key)
    for key in ('POSTGRES_VOLUME','REDIS_VOLUME','QDRANT_VOLUME','OBJECT_VOLUME','CADDY_VOLUME'):
        if not re.fullmatch(re.escape(env['VPS_PROJECT'])+r'-[a-z0-9-]+',env[key]):
            raise Refusal('volume names must belong to this VPS project')
    if len({env[k] for k in ('POSTGRES_VOLUME','REDIS_VOLUME','QDRANT_VOLUME','OBJECT_VOLUME','CADDY_VOLUME')}) != 5:
        raise Refusal('persistent volumes must be distinct')
    if not re.fullmatch(r'[a-z0-9](?:[a-z0-9.-]*[a-z0-9])?\.[a-z]{2,}',env['VPS_DOMAIN']):
        raise Refusal('public DNS name required')
    if not re.fullmatch(r'[a-zA-Z0-9._+-]+@[a-zA-Z0-9.-]+',env['VPS_ACME_EMAIL']):
        raise Refusal('ACME email required')
    if any(env[key] for key in ('RICK_OIDC_ISSUER','RICK_OIDC_AUDIENCE','RICK_OIDC_JWKS_URL')):
        raise Refusal('OIDC requires a reviewed identity composition; URLs do not enable the built-in local identity')
    for key in ('LLM_BASE_URL','EMBEDDING_BASE_URL'):
        u = urlsplit(env[key])
        if u.scheme!='https' or not u.hostname or u.username or u.password or u.query or u.fragment:
            raise Refusal('HTTPS endpoint required: '+key)
    if env['LLM_PROVIDER'] not in {'openai','anthropic'} or env['RICK_EMBEDDING_PROVIDER'] != 'openai':
        raise Refusal('native OpenAI/Anthropic chat and independent OpenAI embeddings required')
    if not env['EMBEDDING_DIMENSION'].isdigit() or not 1<=int(env['EMBEDDING_DIMENSION'])<=16384:
        raise Refusal('invalid embedding dimensions')
    if env['CORS_ALLOWED_ORIGINS'] != 'https://'+env['VPS_DOMAIN']:
        raise Refusal('same-origin HTTPS CORS required')
    if env['RICK_OBJECT_STORE_ACCESS_KEY_ID'] == env['MINIO_ROOT_USER']:
        raise Refusal('object application credentials must be scoped, not root')
    for key, scheme, host in (('RICK_EXTERNAL_DATABASE_DSN','postgresql','postgres'),
                              ('RICK_PREFLIGHT_DATABASE_DSN','postgresql','postgres'),
                              ('RICK_MIGRATION_DATABASE_DSN','postgresql','postgres'),
                              ('RICK_REDIS_URL','rediss','redis')):
        u = urlsplit(env[key])
        if (u.scheme != scheme or u.hostname != host or not u.password or u.query or u.fragment
            or (scheme=='postgresql' and (u.path!='/'+env['POSTGRES_DB'] or not u.username
                or u.netloc.rsplit('@',1)[-1] not in {'postgres','postgres:5432'}))
            or (scheme=='rediss' and u.username!='default')):
            raise Refusal('internal credentialed service URL required: '+key)
    for key in ('RICK_EXTERNAL_DATABASE_DSN','RICK_PREFLIGHT_DATABASE_DSN','RICK_MIGRATION_DATABASE_DSN'):
        postgres_endpoint(env[key],env['POSTGRES_DB'])
    redis = urlsplit(env['RICK_REDIS_URL'])
    try:
        password = unquote(redis.password, errors='strict')
        if (redis.netloc.rsplit('@',1)[-1] not in {'redis','redis:6379'}
            or redis.port not in {None,6379} or redis.path != '/0'
            or re.search(r'%(?![0-9a-fA-F]{2})',redis.password)
            or password != env['REDIS_PASSWORD']):
            raise ValueError('Redis identity mismatch')
    except (ValueError,UnicodeError):
        raise Refusal('Redis URL must match reviewed default user, endpoint, database and server password') from None
    if urlsplit(env['RICK_EXTERNAL_DATABASE_DSN']).username == env['POSTGRES_USER']:
        raise Refusal('application database role must differ from bootstrap administrator')
    roles = {urlsplit(env[k]).username for k in ('RICK_EXTERNAL_DATABASE_DSN','RICK_PREFLIGHT_DATABASE_DSN','RICK_MIGRATION_DATABASE_DSN')}
    if len(roles)!=3 or env['POSTGRES_USER'] in roles:
        raise Refusal('distinct application, readonly and migration database roles required')
    for key in ('TLS_STORE_CERT','TLS_STORE_KEY','TLS_STORE_CA'):
        p = Path(env[key])
        if not p.is_absolute() or '..' in p.parts:
            raise Refusal('absolute TLS file required: '+key)
    return env

def run(argv, env=None):
    result = subprocess.run(argv, env=env, text=True, capture_output=True, timeout=900)
    if result.returncode:
        # Command arguments and driver/container output may contain secrets.
        raise Refusal('operation failed; inspect protected local service diagnostics')
    return result.stdout

def attestations(raw, source, ref, policy=None, candidate_checker=None):
    # cosign has already checked certificate identity, issuer, subject and tlog.
    matches = []
    try:
        envelopes = json.loads(raw)
        if isinstance(envelopes, dict):
            envelopes = [envelopes]
    except json.JSONDecodeError:
        envelopes = [json.loads(line) for line in raw.splitlines() if line.strip()]
    for item in envelopes:
        statement = json.loads(base64.b64decode(item['payload'], validate=True))
        predicate = statement.get('predicate',{})
        subjects = statement.get('subject',[])
        if (statement.get('_type') in {'https://in-toto.io/Statement/v0.1','https://in-toto.io/Statement/v1'}
            and statement.get('predicateType')==PREDICATE and predicate.get('source_sha')==source
            and predicate.get('image_ref')==ref and predicate.get('scan_status')=='PASS'
            and predicate.get('promotion_authorized') is False
            and re.fullmatch('[0-9a-f]{64}',str(predicate.get('sbom_sha256','')))
            and re.fullmatch('[0-9a-f]{64}',str(predicate.get('provenance_sha256','')))
            and subjects == [{'name':ref.split('@')[0], 'digest':{'sha256':ref.split('sha256:')[1]}}]):
            if candidate_checker is None:
                from admission import candidate_policy
                candidate_checker = candidate_policy
            candidate_checker(predicate,ref.split('@')[0].rsplit('-',1)[1],policy)
            matches.append(predicate)
    if not matches:
        raise Refusal('signed source/digest/scan/SBOM/provenance binding missing')

def verify(manifest, refs, execute=run, policy=None, candidate_checker=None):
    source = manifest['source_revision']['value']
    for ref in refs.values():
        common = ['--certificate-identity',IDENTITY,'--certificate-oidc-issuer',ISSUER]
        execute(['cosign','verify',*common,ref])
        raw = execute(['cosign','verify-attestation',*common,'--type',PREDICATE,ref])
        attestations(raw,source,ref,policy,candidate_checker)

def execute_operation(args, config, manifest, refs, execute=run):
    if not hasattr(args, 'captured_assets'):
        raise Refusal('captured reviewed assets required before operation effects')
    parse_env(('\n'.join(k+'='+v for k,v in config.items())+'\n').encode(),
              args.captured_assets[1]['infrastructure/vps/config.env.example'])
    authority = captured_modules(*args.captured_assets[:2], ROOT)
    args.authority = authority
    if args.operation != 'validate':
        if not hasattr(args,'admission_inputs'):
            raise Refusal('captured independent deployment admission policy required')
        args.admission = authority['admission'].deployment_policy(
            *args.admission_inputs,manifest,args.captured_assets[1])
    if getattr(args,'fresh_inventory',None):
        if args.operation not in {'preflight','migrate'} or not getattr(args,'trusted_fresh_inventory_sha256',None):
            raise Refusal('fresh absence inventory is only for explicitly authorized preflight/migrate')
        args.fresh = authority['fresh_inventory'].admit(capture(args.fresh_inventory,private=True),
            args.trusted_fresh_inventory_sha256,config,manifest,args.captured_assets[0])
    if args.operation == 'rollback' and (
        manifest.get('rollout',{}).get('rollback',{}).get('migration_compatibility') != 'PASS'
        or not getattr(args,'rollback_policy',None)):
        raise Refusal('reviewed rollback schema compatibility policy required')
    if args.operation == 'migrate':
        authority['db_guard'].validate_migration_plan(parse(capture(args.plan,private=True),args.plan_sha256))
    with stage(args, config, manifest) as (bundle, mounted, op_owner, tls_owner):
        return bundled_operation(args, mounted, manifest, refs, bundle, op_owner, tls_owner, execute)

def bundled_operation(args, config, manifest, refs, bundle, op_owner, tls_owner, execute):
    callback = execute
    def execute(argv, env=None):
        args.bundle_binding.verify()
        return callback(argv,env)
    with tempfile.TemporaryDirectory(prefix='rick-vps-') as folder:
        # Compose must never reopen the operator's mutable original config.
        compose_config = Path(folder)/'compose.env'
        compose_config.write_text('\n'.join(k+'='+v for k,v in config.items() if not k.startswith('VPS_') or k in {'VPS_PROJECT','VPS_DOMAIN','VPS_ACME_EMAIL'})+'\n')
        compose_config.chmod(0o600)
        runtime = Path(folder)/'runtime.env'
        allowed = {k:v for k,v in config.items() if k.startswith(('RICK_','LLM_','EMBEDDING_','ANTHROPIC_','SESSION_','CORS_'))
                   and k not in {'RICK_PREFLIGHT_DATABASE_DSN','RICK_MIGRATION_DATABASE_DSN'}}
        runtime.write_text('\n'.join(k+'='+v for k,v in allowed.items())+'\n')
        runtime.chmod(0o600)
        files = {}
        scopes = {'PREFLIGHT': {'RICK_PREFLIGHT_DATABASE_DSN'},
            'MIGRATION': {'RICK_PREFLIGHT_DATABASE_DSN','RICK_MIGRATION_DATABASE_DSN'},
            'OBJECT': {k for k in config if k.startswith('RICK_OBJECT_STORE_')},
            'VECTOR': {'RICK_QDRANT_URL','RICK_QDRANT_COLLECTION','RICK_QDRANT_API_KEY','EMBEDDING_DIMENSION'}}
        for name,keys in scopes.items():
            path = Path(folder)/(name.lower()+'.env')
            path.write_text('\n'.join(k+'='+config[k] for k in sorted(keys))+'\n')
            path.chmod(0o600)
            files['VPS_'+name+'_FILE']=str(path)
        env = {'PATH':os.environ.get('PATH','/usr/bin:/bin'),'HOME':os.environ.get('HOME','/tmp'),
               **config,**files,'VPS_RUNTIME_FILE':str(runtime),'VPS_PLAN_FILE':str(args.plan or bundle/'private/unused.json'),
               'VPS_PLAN_SHA256':args.plan_sha256 or 'none',
               'VPS_ROLLBACK_POLICY_FILE':str(getattr(args,'rollback_policy',None) or bundle/'private/unused.json'),
               'VPS_ROLLBACK_POLICY_SHA256':getattr(args,'rollback_policy_sha256',None) or 'none',
               'VPS_ROLLBACK_EVIDENCE_FILE':str(getattr(args,'rollback_evidence',None) or bundle/'private/unused.json'),
               'VPS_RETAINED_MIGRATIONS':str(getattr(args,'retained_migrations',None) or bundle/'private/empty-retained'),
               'VPS_RETAINED_SOURCE_SHA':manifest['source_revision']['value'],
               'VPS_SCOPE_SQL':config['VPS_SCOPE_SQL']}
        for service,ref in refs.items():
            env['RICK_'+service.upper()+'_IMAGE']=ref
        base = ['docker','compose','--project-name',config['VPS_PROJECT'],'--env-file',str(compose_config),
                '-f',str(bundle/'infrastructure/vps/compose.yml')]
        def compose(*parts):
            return execute(base+list(parts),env)
        # Host DAC proof uses the actual selected Linux UID, before any effects.
        operation_paths = [bundle/'infrastructure/vps'/name for name in ('db_guard.py','contracts.py','object-bootstrap.sh')]
        operation_paths.append(Path(env['VPS_SCOPE_SQL']))
        operation_paths.append(Path(env['VPS_PLAN_FILE']))
        operation_paths += [getattr(args, name) for name in ('plan','rollback_policy','rollback_evidence') if getattr(args, name, None)]
        if getattr(args, 'retained_migrations', None):
            operation_paths += list(args.retained_migrations.iterdir())
        prove_readable(operation_paths, op_owner)
        prove_readable([Path(config['TLS_STORE_KEY']), Path(config['TLS_STORE_CERT']),
                        bundle/'infrastructure/vps/Caddyfile', bundle/'infrastructure/vps/stores.Caddyfile'], tls_owner)
        # Quiet render before any Docker service effects; suppress expanded secrets.
        compose('--profile','operations','config','--quiet')
        if args.operation=='validate':
            return None
        verify(manifest,refs,execute,getattr(args,'admission',None),args.authority['admission'].candidate_policy)
        # Check declared image tools before infrastructure startup; no stores mounted.
        probes = {'QDRANT_IMAGE':('bash','command -v bash >/dev/null'),
            'MINIO_IMAGE':('sh','command -v curl >/dev/null'),
            'MC_IMAGE':('sh','command -v mc >/dev/null'),
            'POSTGRES_IMAGE':('sh','command -v pg_isready >/dev/null'),
            'REDIS_IMAGE':('sh','command -v redis-cli >/dev/null')}
        for key,(shell,probe) in probes.items():
            execute(['docker','run','--rm','--network','none','--entrypoint',shell,config[key],'-ec',probe],env)
        execute(['docker','run','--rm','--network','none','--env-file',str(runtime),
                 '-v',config['TLS_STORE_CA']+':/tls/ca-bundle.crt:ro',
                 '--entrypoint','python',refs['api'],'-c',
                 'from core.config import ApiSettings; from rick_locking import RedisSettings; '
                 'ApiSettings.from_env(); RedisSettings.from_env()'],env)
        # Image-level DAC proof has no network and executes only Python's file
        # reads, never the captured operation scripts. Same numeric Compose UID.
        bindings = {str(bundle/'infrastructure/vps/db_guard.py'):'/ops/db_guard.py',
                    str(bundle/'infrastructure/vps/contracts.py'):'/ops/contracts.py',
                    env['VPS_SCOPE_SQL']:'/ops/0008-scope-preflight.sql',
                    env['VPS_PLAN_FILE']:'/ops/migration-plan.json',
                    config['TLS_STORE_CA']:'/tls/ca-bundle.crt'}
        for attribute, target in (('plan','/ops/migration-plan.json'),
                                  ('rollback_policy','/ops/rollback-policy.json'),
                                  ('rollback_evidence','/ops/rollback-compatibility.json')):
            if getattr(args, attribute, None):
                bindings[str(getattr(args, attribute))] = target
        if getattr(args, 'retained_migrations', None):
            bindings[str(args.retained_migrations)] = '/ops/retained-migrations'
        probe = ('import os,pathlib; assert (os.geteuid(),os.getegid()) == '+repr(op_owner)+'; '
                 'paths = '+repr([v for v in bindings.values() if v != '/ops/retained-migrations'])+'; '
                 '[pathlib.Path(p).read_bytes() for p in paths]; '
                 + ("[p.read_bytes() for p in pathlib.Path('/ops/retained-migrations').iterdir()]"
                    if getattr(args, 'retained_migrations', None) else ''))
        mounts = [arg for source,target in bindings.items() for arg in ('-v',source+':'+target+':ro')]
        execute(['docker','run','--rm','--network','none','--user',args.operations_user,
                 *mounts,'--entrypoint','python',refs['api'],'-c',probe],env)
        for key in ('REDIS_IMAGE','CADDY_IMAGE'):
            execute(['docker','run','--rm','--network','none','--user',args.tls_user,
                     '-v',config['TLS_STORE_KEY']+':/tls/store.key:ro',
                     '-v',config['TLS_STORE_CERT']+':/tls/store.crt:ro',
                     '--entrypoint','sh',config[key],'-ec',
                     'test -r /tls/store.key && test -r /tls/store.crt'],env)
        # Admit current state before writer stop or any persistent store start.
        # An unavailable database is a refusal, never evidence of absence.
        if getattr(args,'fresh',None):
            names = [config[key] for key in args.authority['fresh_inventory'].VOLUMES]
            volumes = parse(execute(['docker','volume','inspect',*names],env).encode())
            containers = parse(compose('ps','--all','--format','json').encode())
            args.authority['fresh_inventory'].authorize(args.fresh,volumes,containers)
            if args.operation == 'migrate' and load(args.plan,args.plan_sha256)['observed']['database_state'] != 'EMPTY':
                raise Refusal('fresh absence inventory requires an explicitly reviewed EMPTY migration plan')
        else:
            service = ('db-rollback-preflight' if args.operation == 'rollback' else
                       'db-retained-preflight' if getattr(args,'retained_schema_inventory',False) else 'db-preflight')
            current = parse(compose('--profile','operations','run','--rm','--no-deps',service).encode())
            if args.operation == 'migrate':
                args.authority['db_guard'].authorize(load(args.plan,args.plan_sha256),current)
            elif args.operation == 'rollback':
                args.authority['db_guard'].authorize_rollback(load(args.rollback_policy,args.rollback_policy_sha256),current)
            elif args.operation == 'preflight':
                return current
            elif current.get('pending'):
                raise Refusal('pending migrations require reviewed preflight/plan and explicit migrate operation')
        compose('pull','postgres','redis','qdrant','object-store','stores-tls','api','worker','web','edge')
        if args.operation=='migrate' and not getattr(args,'fresh',None):
            compose('stop','edge','web','worker','api')
        compose('up','-d','--wait','--wait-timeout','180','postgres','redis','qdrant','object-store','stores-tls')
        if args.operation=='rollback':
            if (manifest.get('rollout',{}).get('rollback',{}).get('migration_compatibility')!='PASS'
                or not getattr(args,'rollback_policy',None)):
                raise Refusal('reviewed rollback schema compatibility policy required')
            observed = parse(compose('--profile','operations','run','--rm','--no-deps','db-rollback-preflight').encode())
        else:
            service = 'db-retained-preflight' if getattr(args,'retained_schema_inventory',False) else 'db-preflight'
            observed = parse(compose('--profile','operations','run','--rm','--no-deps',service).encode())
        if args.operation=='preflight':
            return observed
        if args.operation=='migrate':
            plan = load(args.plan,args.plan_sha256)
            args.authority['db_guard'].authorize(plan,observed)
            compose('--profile','operations','run','--rm','--no-deps','db-migrate')
            return None
        if observed.get('pending'):
            raise Refusal('pending migrations require reviewed preflight/plan and explicit migrate operation')
        if args.operation=='rollback':
            args.authority['db_guard'].authorize_rollback(load(args.rollback_policy,args.rollback_policy_sha256),observed)
        # Independent, idempotent bootstraps, never user/policy/schema repair.
        compose('--profile','operations','run','--rm','--no-deps','object-bootstrap')
        compose('--profile','operations','run','--rm','--no-deps','vector-bootstrap')
        compose('up','-d','--wait','--wait-timeout','240','api','worker','web','edge')
        return None

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('operation',choices=['validate','preflight','install','upgrade','migrate','rollback'])
    parser.add_argument('--config',type=Path,required=True)
    parser.add_argument('--manifest',type=Path,required=True)
    parser.add_argument('--assets',type=Path,required=True)
    parser.add_argument('--bundle-root',type=Path,required=True,help='pre-provisioned protected directory for retained runtime assets')
    parser.add_argument('--trusted-assets-sha256',required=True)
    parser.add_argument('--reviewed-bundle-id',required=True)
    parser.add_argument('--operations-user',required=True,help='reviewed non-root numeric UID:GID for one-shot jobs')
    parser.add_argument('--tls-user',required=True,help='reviewed numeric UID:GID for Redis and stores TLS key reader')
    parser.add_argument('--trusted-config-sha256',required=True)
    parser.add_argument('--trusted-manifest-sha256',required=True)
    parser.add_argument('--admission-policy',type=Path)
    parser.add_argument('--trusted-admission-policy-sha256')
    parser.add_argument('--fresh-inventory',type=Path)
    parser.add_argument('--trusted-fresh-inventory-sha256')
    parser.add_argument('--plan',type=Path)
    parser.add_argument('--plan-sha256')
    parser.add_argument('--rollback-policy',type=Path)
    parser.add_argument('--rollback-policy-sha256')
    parser.add_argument('--retained-migrations',type=Path)
    parser.add_argument('--rollback-evidence',type=Path)
    parser.add_argument('--retained-schema-inventory',action='store_true',
                        help='preflight only: collect strict current-image retained schema inventory for review')
    args = parser.parse_args()
    if args.retained_schema_inventory and args.operation!='preflight':
        raise Refusal('retained schema collection is only a preflight operation')
    config_data = capture(args.config,private=True)
    check_hash(config_data,args.trusted_config_sha256)
    manifest_data = capture(args.manifest)
    manifest = parse(manifest_data,args.trusted_manifest_sha256)
    refs = images(manifest)
    asset_packet, asset_files = review_inputs(args, config_data, manifest)
    config = parse_env(config_data, asset_files['infrastructure/vps/config.env.example'])
    args.captured_assets = (asset_packet, asset_files, captured_tls(asset_packet, config))
    # Every path passed to validators, Compose or mounted jobs is a private copy
    # of the same captured bytes that were hash checked and parsed above.
    with tempfile.TemporaryDirectory(prefix='rick-reviewed-inputs-') as folder:
        def snapshot(name,data):
            path = Path(folder)/name
            path.write_bytes(data)
            path.chmod(0o600)
            return path
        args.config = snapshot('config.env',config_data)
        args.manifest = snapshot('release.json',manifest_data)
        finish(args,config,manifest,refs,snapshot,folder)

def finish(args,config,manifest,refs,snapshot,folder):
    authority = captured_modules(*args.captured_assets[:2], folder)
    if args.operation != 'validate':
        if not getattr(args,'admission_policy',None) or not args.trusted_admission_policy_sha256:
            raise Refusal('independent admission policy and hash required')
        args.admission_inputs = capture(args.admission_policy,private=True),args.trusted_admission_policy_sha256
        args.admission = authority['admission'].deployment_policy(
            *args.admission_inputs,manifest,args.captured_assets[1])
    if args.operation in {'install','upgrade','migrate','rollback'}:
        # Reuse the existing REC-33 release/rollout checker; build CI cannot satisfy it.
        if release_errors(args,folder):
            raise Refusal('REC-33 release/rollout validation refused')
    if args.operation=='migrate':
        if not args.plan or not args.plan.is_absolute() or not args.plan_sha256:
            raise Refusal('independently reviewed absolute migration plan and hash required')
        plan_data = capture(args.plan,private=True)
        plan = parse(plan_data,args.plan_sha256)
        authority['db_guard'].validate_migration_plan(plan)
        args.plan = snapshot('migration-plan.json',plan_data)
    if args.operation=='rollback' and not manifest.get('rollout',{}).get('rollback',{}).get('evidence'):
        raise Refusal('reviewed rollback manifest required')
    if args.operation=='rollback':
        if not args.rollback_policy or not args.rollback_policy_sha256 or not args.retained_migrations or not args.rollback_evidence:
            raise Refusal('reviewed rollback policy and retained SQL inventory required')
        policy_data = capture(args.rollback_policy,private=True)
        policy = parse(policy_data,args.rollback_policy_sha256)
        authority['db_guard'].validate_rollback_inputs(policy,config,manifest)
        evidence_data = capture(args.rollback_evidence,private=True)
        authority['db_guard'].validate_compatibility(policy,evidence_data)
        args.rollback_evidence = snapshot('rollback-compatibility.json',evidence_data)
        retained = Path(folder)/'retained-migrations'
        retained.mkdir(mode=0o700)
        if not args.retained_migrations.is_absolute() or args.retained_migrations.is_symlink():
            raise Refusal('absolute retained migration directory required')
        for name,checksum in policy['retained_artifacts'].items():
            data = capture(args.retained_migrations/name,private=True)
            check_hash(data,checksum)
            p = retained/name
            p.write_bytes(data)
            p.chmod(0o600)
        args.rollback_policy = snapshot('rollback-policy.json',policy_data)
        args.retained_migrations = retained
    output = execute_operation(args,config,manifest,refs)
    if output is not None:
        print(json.dumps(output,sort_keys=True))
    else:
        print('requested local operation completed; no promotion decision recorded')

if __name__=='__main__':
    try:
        main()
    except Refusal as error:
        print('VPS operation refused: '+str(error),file=sys.stderr)
        raise SystemExit(2)
    except Exception:
        print('VPS operation refused; configuration or reviewed evidence unavailable',file=sys.stderr)
        raise SystemExit(2)
