"""Inventory first; authorize exact pending SQL, never historical auto-repair."""
from __future__ import annotations
import importlib.util
import hashlib
import json
import os
from pathlib import Path
import re
import sys
from contracts import HEX, Refusal, images, load, parse, postgres_endpoint

MIGRATIONS = Path('/opt/rick/infrastructure/migrations')
RUNNER = Path('/opt/rick/infrastructure/scripts/migrate.py')

# Definitions only; never user rows. Bind retained schema structure as well as
# the history claim. Stable ordering and serialization make this reviewable.
ROLLBACK_CATALOG = """/* rollback_catalog */
SELECT kind, identity, definition FROM (
 SELECT 'column'::text AS kind, c.oid::regclass::text || '.' || a.attname AS identity,
        concat_ws('|',c.relkind,a.attnum,format_type(a.atttypid,a.atttypmod),
          a.attnotnull,a.attidentity,a.attgenerated,pg_get_expr(d.adbin,d.adrelid)) AS definition
 FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
 JOIN pg_attribute a ON a.attrelid=c.oid AND a.attnum>0 AND NOT a.attisdropped
 LEFT JOIN pg_attrdef d ON d.adrelid=c.oid AND d.adnum=a.attnum
 WHERE n.nspname='public'
 UNION ALL SELECT 'constraint', c.conrelid::regclass::text || '.' || c.conname,
   pg_get_constraintdef(c.oid) FROM pg_constraint c JOIN pg_namespace n ON n.oid=c.connamespace WHERE n.nspname='public'
 UNION ALL SELECT 'index', c.oid::regclass::text, pg_get_indexdef(c.oid)
   FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname='public' AND c.relkind='i'
 UNION ALL SELECT 'routine', p.oid::regprocedure::text, pg_get_functiondef(p.oid)
   FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace WHERE n.nspname='public' AND p.prokind IN ('f','p')
 UNION ALL SELECT 'trigger', t.tgrelid::regclass::text || '.' || t.tgname, pg_get_triggerdef(t.oid)
   FROM pg_trigger t JOIN pg_class c ON c.oid=t.tgrelid JOIN pg_namespace n ON n.oid=c.relnamespace
   WHERE n.nspname='public' AND NOT t.tgisinternal
 UNION ALL SELECT 'view', c.oid::regclass::text, pg_get_viewdef(c.oid)
   FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname='public' AND c.relkind IN ('v','m')
) inventory ORDER BY kind, identity, definition"""

def catalog_digest(rows):
    if not rows or any(len(row)!=3 or not all(isinstance(v,str) for v in row) for row in rows):
        raise Refusal('retained schema definition inventory required')
    return hashlib.sha256(json.dumps(rows,separators=(',',':'),ensure_ascii=False).encode()).hexdigest()

def runner():
    spec = importlib.util.spec_from_file_location('canonical_migrate', RUNNER)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module

def validate_rollback_inputs(policy, config, manifest):
    validate_rollback_policy(policy)
    if policy['target_source_sha'] != manifest['source_revision']['value'] or policy['target_images'] != images(manifest):
        raise Refusal('rollback policy target release mismatch')
    expected = {key: config[key] for key in ('VPS_PROJECT','POSTGRES_DB','POSTGRES_VOLUME',
                'REDIS_VOLUME','QDRANT_VOLUME','OBJECT_VOLUME','CADDY_VOLUME')}
    if policy.get('deployment') != expected:
        raise Refusal('rollback policy database/volume identity mismatch')

def validate_rollback_policy(policy):
    if (policy.get('schema') != 'rick.vps.rollback-policy/v1'
        or policy.get('authorization') != 'RETAIN_SCHEMA_IMAGE_ROLLBACK'
        or not re.fullmatch('[0-9a-f]{40}',str(policy.get('target_source_sha','')))
        or not re.fullmatch('[0-9a-f]{40}',str(policy.get('retained_source_sha','')))):
        raise Refusal('explicit reviewed rollback provenance policy required')
    compatibility = policy.get('compatibility',{})
    if (compatibility.get('status') != 'PASS' or not isinstance(compatibility.get('evidence'),str)
        or not compatibility['evidence'].strip()
        or not isinstance(compatibility.get('evidence_sha256'),str)
        or not HEX.fullmatch(compatibility['evidence_sha256'])
        or not re.fullmatch('[0-9]{4}',str(compatibility.get('target_schema_version','')))
        or not re.fullmatch('[0-9]{4}',str(compatibility.get('retained_schema_version','')))
        or compatibility['target_schema_version'] > compatibility['retained_schema_version']):
        raise Refusal('reviewed rollback schema compatibility evidence required')
    artifacts = policy.get('retained_artifacts',{})
    if not isinstance(artifacts,dict) or not artifacts or any(
        not re.fullmatch(r'[0-9]{4}_[a-z0-9][a-z0-9_-]*\.sql(?:\.inc)?',name)
        or not isinstance(checksum,str) or not HEX.fullmatch(checksum) for name,checksum in artifacts.items()
    ):
        raise Refusal('known retained migration artifact checksums required')
    if not isinstance(policy.get('observed'),dict):
        raise Refusal('reviewed retained database inventory required')

def validate_compatibility(policy, data):
    evidence = parse(data,policy['compatibility']['evidence_sha256'])
    if (evidence.get('schema') != 'rick.vps.schema-compatibility/v1'
        or evidence.get('decision') != 'RETAIN_SCHEMA_IMAGE_ROLLBACK'
        or any(not isinstance(evidence.get(k),str) or not evidence[k].strip() for k in ('reviewer','analysis'))
        or any(evidence.get(k) != policy[k] for k in ('target_source_sha','retained_source_sha','retained_artifacts','target_images'))
        or any(evidence.get(k) != policy['compatibility'][k] for k in ('target_schema_version','retained_schema_version'))):
        raise Refusal('hash-bound reviewed schema compatibility evidence mismatch')

def authorize_rollback(policy, observed):
    validate_rollback_policy(policy)
    if (observed != policy['observed'] or observed.get('schema') != 'rick.vps.rollback-preflight/v1'
        or observed.get('read_only') is not True or observed.get('database_state') != 'EXISTING'
        or observed.get('pending') != []):
        raise Refusal('rollback retained inventory changed or unreviewed')

def rollback_rows(module, rows, policy, directory):
    """Accept newer SQL only from the separately reviewed retained release."""
    validate_rollback_policy(policy)
    names = {p.name for p in directory.iterdir() if p.is_file()}
    if names != set(policy['retained_artifacts']):
        raise Refusal('retained migration provenance inventory mismatch')
    from contracts import digest
    if any(digest(directory/name) != checksum for name,checksum in policy['retained_artifacts'].items()):
        raise Refusal('retained migration artifact checksum mismatch')
    retained = module.migration_files(directory)
    old = [(v,p.name,h) for v,p,h in rows]
    current = [(v,p.name,h) for v,p,h in retained]
    compatibility = policy['compatibility']
    if (old != current[:len(old)] or rows[-1][0] != compatibility['target_schema_version']
        or retained[-1][0] != compatibility['retained_schema_version']):
        raise Refusal('retained release must extend exact older image migration inventory')
    return retained

def inspect_database(connection, module, directory=MIGRATIONS, *, rollback_policy=None, retained_directory=None,
                     compatibility_evidence=None, retained_source_sha=None):
    rows = module.migration_files(directory)
    if rollback_policy is not None:
        validate_rollback_policy(rollback_policy)
        if compatibility_evidence is None:
            raise Refusal('hash-bound reviewed schema compatibility evidence required')
        validate_compatibility(rollback_policy,compatibility_evidence.read_bytes())
        rows = rollback_rows(module,rows,rollback_policy,retained_directory)
        retained_source_sha = rollback_policy['retained_source_sha']
    if retained_source_sha is not None and not re.fullmatch('[0-9a-f]{40}',retained_source_sha):
        raise Refusal('exact retained source revision required')
    with connection.cursor() as cur:
        cur.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY')
        cur.execute("SET LOCAL statement_timeout = '15s'")
        cur.execute("SET LOCAL lock_timeout = '5s'")
        cur.execute("SELECT current_setting('transaction_read_only')")
        if cur.fetchone() != ('on',):
            raise Refusal('READ ONLY preflight was not enforced')
        cur.execute('SELECT current_schema()')
        if cur.fetchone() != ('public',):
            raise Refusal('reviewed public schema search path required')
        cur.execute("SELECT count(*) FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname NOT IN ('pg_catalog','information_schema') AND n.nspname NOT LIKE 'pg_toast%' AND c.relkind IN ('r','p','v','m','S','f')")
        relation_count = cur.fetchone()[0]
        cur.execute("SELECT to_regclass('rick_schema_migrations') IS NOT NULL")
        has_history = cur.fetchone()[0]
        history = []
        if has_history:
            cur.execute('SELECT version, checksum, application FROM rick_schema_migrations ORDER BY version')
            history = cur.fetchall()
        module.validate_history(rows, history)
        # The canonical runner recognizes old checksums and may auto-repair.
        # VPS execution explicitly refuses that path, even if recognized.
        exact = {version: checksum for version, _, checksum in rows}
        if any(exact[version] != checksum for version, checksum, _ in history):
            raise Refusal('historical migration requires separate reviewed repair')
        if relation_count and not history:
            raise Refusal('existing database without history requires inventory/restore review')
        applied = {version for version, _, _ in history}
        if applied and '0008' not in applied and '0007' not in applied:
            raise Refusal('older populated schema requires staged upgrade and scope review')
        pending = [{'version': v, 'sha256': h} for v, _, h in rows if v not in applied]
        if retained_source_sha is not None and (pending or not history):
            raise Refusal('rollback requires complete known retained migration history')
        if retained_source_sha is not None:
            cur.execute(ROLLBACK_CATALOG)
            schema_catalog_sha256 = catalog_digest(cur.fetchall())
        # Avoid duplicating the canonical scope SQL: the reviewed release must
        # carry the repository preflight file, mounted separately by Compose.
        if '0007' in applied and '0008' not in applied:
            sql = Path('/ops/0008-scope-preflight.sql').read_text()
            cur.execute(sql)
            counts = cur.fetchall()
            if len(counts) != 4 or any(type(count) is not int or count != 0 for _, count in counts):
                raise Refusal('scope conflicts require explicit data remediation review')
    relations = None
    if retained_source_sha is None:
        with connection.cursor() as cur:
            # Still in the same repeatable-read, read-only transaction.
            cur.execute(module.AUTHORIZATION_RELATIONS_SQL)
            relations = [list(row) for row in cur.fetchall()]
        if len(relations) != relation_count:
            raise Refusal('migration relation inventory mismatch')
    observed = {'schema': 'rick.vps.preflight/v1', 'read_only': True,
            'database_state': 'EMPTY' if relation_count == 0 else 'EXISTING',
            'history': [{'version': v, 'sha256': h} for v, h, _ in history], 'pending': pending}
    if relations is not None:
        observed['relation_count'] = relation_count
        observed['relations'] = relations
    if retained_source_sha is not None:
        observed['schema'] = 'rick.vps.rollback-preflight/v1'
        observed['relation_count'] = relation_count
        observed['retained_source_sha'] = retained_source_sha
        observed['schema_catalog_sha256'] = schema_catalog_sha256
    if rollback_policy is not None:
        authorize_rollback(rollback_policy,observed)
    return observed

def validate_migration_plan(plan, *, allow_noop=False):
    required = {'schema','authorization','observed','maintenance_window','verified_backup_id','backward_compatible'}
    if (not isinstance(plan,dict) or set(plan) != required
        or plan.get('schema') != 'rick.vps.migration-plan/v1'
        or plan.get('authorization') != 'APPLY_REVIEWED_SQL'):
        raise Refusal('reviewed explicit migration authorization required')
    observed = plan['observed']
    if (not isinstance(observed,dict)
        or set(observed) != {'schema','read_only','database_state','history','pending','relation_count','relations'}
        or observed['schema'] != 'rick.vps.preflight/v1' or observed['read_only'] is not True
        or observed['database_state'] not in {'EMPTY','EXISTING'}):
        raise Refusal('complete READ ONLY migration inventory required')
    relations = observed['relations']
    if (type(observed['relation_count']) is not int or observed['relation_count'] < 0
        or not isinstance(relations,list) or len(relations) != observed['relation_count']
        or any(not isinstance(row,list) or len(row)!=3
               or not all(isinstance(v,str) and v for v in row)
               or row[2] not in {'r','p','v','m','S','f'} for row in relations)
        or relations != sorted(relations) or len({tuple(row) for row in relations}) != len(relations)
        or (observed['database_state']=='EMPTY') != (not relations)):
        raise Refusal('exact ordered migration relation inventory required')
    for key in ('history','pending'):
        rows = observed[key]
        if not isinstance(rows,list) or any(
            not isinstance(row,dict) or set(row) != {'version','sha256'}
            or not isinstance(row['version'],str) or not re.fullmatch('[0-9]{4}',row['version'])
            or not isinstance(row['sha256'],str) or not HEX.fullmatch(row['sha256']) for row in rows):
            raise Refusal('exact ordered migration versions and checksums required')
    versions = [row['version'] for row in observed['history']+observed['pending']]
    if (not observed['pending'] and not allow_noop) or not versions or versions != [f'{i:04d}' for i in range(1,len(versions)+1)]:
        raise Refusal('contiguous history and nonempty pending SQL required')
    if (type(plan['maintenance_window']) is not bool or plan['backward_compatible'] is not True
        or not isinstance(plan['verified_backup_id'],str)
        or plan['verified_backup_id'] != plan['verified_backup_id'].strip()
        or any(ord(c)<32 for c in plan['verified_backup_id'])):
        raise Refusal('explicit maintenance, backup and compatibility decisions required')
    if observed['database_state'] == 'EMPTY':
        if observed['history'] or plan['maintenance_window'] is not False or plan['verified_backup_id'] != '':
            raise Refusal('fresh database requires empty history and explicit no-maintenance/no-backup decisions')
    elif (not observed['history'] or observed['history'][-1]['version'] < '0007'
          or plan['maintenance_window'] is not True or not plan['verified_backup_id']):
        raise Refusal('existing data requires maintenance, verified backup and compatibility review')
    return observed

def authorize(plan, observed, *, allow_noop=False):
    validate_migration_plan(plan, allow_noop=allow_noop)
    if plan.get('observed') != observed:
        raise Refusal('database inventory changed or migration plan mismatch')

def main():
    readonly = postgres_endpoint(os.environ['RICK_PREFLIGHT_DATABASE_DSN'])
    if sys.argv[1] == 'apply':
        postgres_endpoint(os.environ['RICK_MIGRATION_DATABASE_DSN'],readonly.path[1:])
    import psycopg
    module = runner()
    rollback_policy = None
    retained_directory = None
    compatibility_evidence = None
    if sys.argv[1] == 'inspect-rollback':
        rollback_policy = load(Path('/ops/rollback-policy.json'),os.environ['VPS_ROLLBACK_POLICY_SHA256'])
        retained_directory = Path('/ops/retained-migrations')
        compatibility_evidence = Path('/ops/rollback-compatibility.json')
    with psycopg.connect(os.environ['RICK_PREFLIGHT_DATABASE_DSN'], connect_timeout=5) as connection:
        observed = inspect_database(connection, module, rollback_policy=rollback_policy,retained_directory=retained_directory,
                                    compatibility_evidence=compatibility_evidence,
                                    retained_source_sha=os.environ['VPS_RETAINED_SOURCE_SHA'] if sys.argv[1]=='inspect-retained' else None)
    if sys.argv[1] in {'inspect','inspect-rollback','inspect-retained'}:
        print(json.dumps(observed, sort_keys=True))
        return 0
    if sys.argv[1] != 'apply':
        raise Refusal('unsupported operation')
    plan = load(Path('/ops/migration-plan.json'), os.environ['VPS_PLAN_SHA256'])
    authorize(plan, observed, allow_noop=True)
    # API/worker must already be stopped by deploy.py; re-inventory immediately
    # before invoking the canonical checksum/history/transaction-locked runner.
    return module.apply(MIGRATIONS, os.environ['RICK_MIGRATION_DATABASE_DSN'],
                        authorization=json.dumps(plan,sort_keys=True,separators=(',',':')).encode())

if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except Exception:
        print('database operation refused; inspect protected database diagnostics', file=sys.stderr)
        raise SystemExit(2)
