"""Candidate CI artifacts, never production admission or a release signature.

The native OCI statements and the complete archive are retained. A keyless
workflow signature covers their inventory, not an independently reviewed policy.
The existing publication/admission tools deliberately do not accept this schema.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import tarfile
from urllib.parse import parse_qs, unquote

from contracts import ISSUER, REPO, SERVICES, Refusal, immutable, parse
from publish_candidate import bounded_tar_headers, spdx_packages

ROOT = Path(__file__).resolve().parents[2]
OUT = Path('candidate-evidence')
REF = 'refs/heads/phase3/a8a83ca-candidate'
WORKFLOW = f'{REPO}/.github/workflows/quality.yml@{REF}'
JOBS = ('fast', 'unit', 'contract', 'security', 'rag-eval', 'frontend', 'supply-chain')
PROVENANCE = 'https://slsa.dev/provenance/v0.2'
SPDX = 'https://spdx.dev/Document'


def sha256(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def write(path, value):
    with path.open('x') as stream:
        json.dump(value, stream, sort_keys=True, indent=2, allow_nan=False)
        stream.write('\n')


def identity(env, needs, head, dirty):
    source = env.get('GITHUB_SHA', '')
    if (env.get('GITHUB_REPOSITORY') != REPO or env.get('GITHUB_REF') != REF
        or env.get('GITHUB_WORKFLOW_REF') != WORKFLOW
        or env.get('GITHUB_EVENT_NAME') != 'workflow_dispatch'
        or env.get('GITHUB_ACTIONS') != 'true'
        or not re.fullmatch('[0-9a-f]{40}', source) or head != source or dirty
        or not re.fullmatch('[1-9][0-9]*', env.get('GITHUB_RUN_ID', ''))
        or not re.fullmatch('[1-9][0-9]*', env.get('GITHUB_RUN_ATTEMPT', ''))):
        raise Refusal('clean exact-SHA canonical candidate dispatch required')
    if set(needs) != set(JOBS) or any(needs[j].get('result') != 'success' for j in JOBS):
        raise Refusal('all seven same-run code gates must succeed')
    return {'source_sha': source, 'ref': REF, 'repository': REPO,
            'workflow_ref': WORKFLOW, 'run_id': int(env['GITHUB_RUN_ID']),
            'run_attempt': int(env['GITHUB_RUN_ATTEMPT']),
            'code_gates': {j: needs[j]['result'] for j in JOBS},
            'production_safe': False, 'promotion_authorized': False,
            'independent_review': 'MISSING', 'human_release_decision': 'MISSING'}


def prepare():
    head = subprocess.check_output(['git', 'rev-parse', 'HEAD'], text=True).strip()
    dirty = subprocess.check_output(['git', 'status', '--porcelain'], text=True).strip()
    record = identity(os.environ, parse(os.environ['NEEDS_JSON'].encode()), head, dirty)
    tools = parse((ROOT/'infrastructure/vps/candidate-toolchain.json').read_bytes())
    if (tools.get('schema') != 'rick.candidate-toolchain-proposal/v1'
        or tools.get('production_safe') is not False or tools.get('independently_reviewed') is not False):
        raise Refusal('explicitly unapproved toolchain proposal required')
    for key in ('python_image', 'node_image', 'buildkit_image', 'sbom_generator_image', 'trivy_image'):
        immutable(tools[key])
    from buildx_binary import install
    OUT.mkdir(mode=0o700)
    write(OUT/'quality.json', record)
    write(OUT/'toolchain.json', tools)
    # Reuse checksum-before-execution; this is a proposal, not reviewed policy.
    folder = Path(os.environ['RUNNER_TEMP'])/'rick-candidate-buildx'
    evidence = install(tools['buildx_version'], tools['buildx_sha256'], folder)
    write(OUT/'buildx.json', evidence)
    with Path(os.environ['GITHUB_ENV']).open('a') as stream:
        stream.write('DOCKER_CONFIG='+str(folder)+'\n')
        for key in ('python_image', 'node_image', 'buildkit_image', 'sbom_generator_image', 'trivy_image'):
            stream.write(key.upper()+'='+tools[key]+'\n')


def inspect_oci(archive, expected, source, builder, service, output):
    """Read without extracting paths; hash blobs before interpreting metadata.

    This checks construction identity, not reviewed materials/recipe authority,
    layer semantics or production scan admission (those remain in publication).
    """
    if not re.fullmatch('sha256:[0-9a-f]{64}', expected):
        raise Refusal('actual BuildKit digest required')
    if archive.stat().st_size > 4*1024**3:
        raise Refusal('bounded OCI archive required')
    with archive.open('rb') as raw:
        bounded_tar_headers(raw, archive.stat().st_size)
        with tarfile.open(fileobj=raw, mode='r:') as tar:
            members = {}
            end = 0
            for item in tar:
                name = item.name
                if name in members or item.pax_headers or not (item.isfile() or item.isdir()):
                    raise Refusal('duplicate, linked or extended OCI member')
                if item.isdir():
                    if name not in {'blobs', 'blobs/sha256'} or item.size:
                        raise Refusal('unexpected OCI directory')
                elif name not in {'index.json', 'oci-layout'} and not re.fullmatch('blobs/sha256/[0-9a-f]{64}', name):
                    raise Refusal('unexpected OCI file')
                members[name] = item
                end = item.offset_data + ((item.size+511)//512)*512
                if item.isfile() and name.startswith('blobs/'):
                    if hashlib.file_digest(tar.extractfile(item), 'sha256').hexdigest() != name.rsplit('/', 1)[1]:
                        raise Refusal('OCI blob hash mismatch')
            raw.seek(end)
            while chunk := raw.read(65536):
                if any(chunk):
                    raise Refusal('trailing OCI content')

            def read(name):
                item = members.get(name)
                if item is None or not item.isfile() or item.size > 16*1024**2:
                    raise Refusal('bounded OCI metadata required')
                return tar.extractfile(item).read()

            def blob(d):
                digest = d.get('digest', '')
                if not re.fullmatch('sha256:[0-9a-f]{64}', digest):
                    raise Refusal('OCI descriptor SHA256 required')
                data = read('blobs/sha256/'+digest.split(':')[1])
                if len(data) != d.get('size'):
                    raise Refusal('OCI descriptor size mismatch')
                return parse(data)

            if parse(read('oci-layout')) != {'imageLayoutVersion': '1.0.0'}:
                raise Refusal('OCI layout required')
            index_data = read('index.json')
            index = parse(index_data)
            if 'sha256:'+hashlib.sha256(index_data).hexdigest() != expected:
                ds = index.get('manifests', [])
                if len(ds) != 1 or ds[0].get('digest') != expected:
                    raise Refusal('BuildKit/OCI index mismatch')
                index = blob(ds[0])
            ds = index.get('manifests', [])
            apps = [d for d in ds if d.get('platform') == {'os': 'linux', 'architecture': 'amd64'}]
            if index.get('schemaVersion') != 2 or len(ds) != 2 or len(apps) != 1:
                raise Refusal('one application and one attestation manifest required')
            app = apps[0]
            application = blob(app)
            config = blob(application['config'])
            labels = config.get('config', {}).get('Labels', {})
            if (config.get('config', {}).get('User') != '10001:10001'
                or labels.get('org.opencontainers.image.revision') != source
                or labels.get('org.opencontainers.image.source') != 'https://github.com/'+REPO):
                raise Refusal('nonroot exact-SHA image configuration required')
            att = next(d for d in ds if d != app)
            if (att.get('annotations', {}).get('vnd.docker.reference.type') != 'attestation-manifest'
                or att.get('annotations', {}).get('vnd.docker.reference.digest') != app['digest']):
                raise Refusal('attestation must bind the application')
            statements = {}
            for layer in blob(att)['layers']:
                statement = blob(layer)
                kind = statement.get('predicateType')
                subjects = statement.get('subject', [])
                if (kind not in {PROVENANCE, SPDX} or kind in statements
                    or statement.get('_type') not in {'https://in-toto.io/Statement/v0.1', 'https://in-toto.io/Statement/v1'}
                    or len(subjects) != 1 or subjects[0].get('digest') != {'sha256': app['digest'].split(':')[1]}):
                    raise Refusal('unambiguous native statements bound to application required')
                name, _, query = unquote(subjects[0].get('name', '')).partition('?')
                if (name.split('@', 1)[0] != f'pkg:docker/ghcr.io/{REPO}-{service}'
                    or parse_qs(query).get('platform') != ['linux/amd64']):
                    raise Refusal('native statement service/platform identity mismatch')
                statements[kind] = statement
            if set(statements) != {PROVENANCE, SPDX}:
                raise Refusal('native provenance and SBOM required')
            p = statements[PROVENANCE]['predicate']
            context = p.get('invocation', {}).get('configSource', {})
            uri = 'https://github.com/'+REPO+'.git#'+source
            if (context != {'uri': uri, 'digest': {'sha1': source}, 'entryPoint': f'infrastructure/docker/{service}.Dockerfile'}
                or p.get('builder', {}).get('id') != builder
                or p.get('buildType') != 'https://mobyproject.org/buildkit@v1'
                or not any(m.get('uri') == uri and m.get('digest') == {'sha1': source} for m in p.get('materials', []))):
                raise Refusal('exact remote Git source, Dockerfile and builder required')
            packages = spdx_packages(statements[SPDX]['predicate'])
            write(output/'provenance.json', statements[PROVENANCE])
            write(output/'sbom.json', statements[SPDX])
            return {'index_digest': expected, 'application_digest': app['digest'],
                    'configuration_digest': application['config']['digest'], 'sbom_packages': len(packages)}


def scan_result(report, config_digest, service):
    if (report.get('SchemaVersion') != 2 or report.get('ArtifactType') != 'container_image'
        or report.get('Metadata', {}).get('ImageID') != config_digest
        or report.get('Metadata', {}).get('OS', {}).get('Family') != 'alpine'
        or not isinstance(report.get('Results'), list) or not report['Results']):
        raise Refusal('native scan of the exact OCI configuration required')
    covered, findings = set(), 0
    for result in report['Results']:
        kind = (result.get('Class'), result.get('Type'))
        packages = result.get('Packages')
        if (kind not in {('os-pkgs', 'alpine'), ('lang-pkgs', 'python-pkg'), ('lang-pkgs', 'node-pkg')}
            or not isinstance(packages, list) or not packages
            or any(not p.get('Name') or not p.get('Version') for p in packages)):
            raise Refusal('substantive OS/application scan coverage required')
        covered.add(kind)
        vulnerabilities = result.get('Vulnerabilities') or []
        if (not isinstance(vulnerabilities, list)
            or any(not v.get('VulnerabilityID') or not v.get('PkgName')
                   or v.get('Severity') not in {'LOW', 'MEDIUM', 'HIGH', 'CRITICAL', 'UNKNOWN'} for v in vulnerabilities)):
            raise Refusal('complete all-severity vulnerability inventory required')
        findings += len(vulnerabilities)
    language = 'node-pkg' if service == 'web' else 'python-pkg'
    if not {('os-pkgs', 'alpine'), ('lang-pkgs', language)}.issubset(covered):
        raise Refusal('OS and application language scan coverage required')
    return findings


def inventory():
    service = os.environ['SERVICE']
    if service not in SERVICES:
        raise Refusal('known service required')
    quality = parse((OUT/'quality.json').read_bytes())
    source = os.environ['GITHUB_SHA']
    if quality['source_sha'] != source:
        raise Refusal('same-SHA construction record required')
    builder = f'https://github.com/{REPO}/actions/runs/'+os.environ['GITHUB_RUN_ID']
    native = inspect_oci(OUT/'image.tar', os.environ['BUILT_DIGEST'], source, builder, service, OUT)
    report = parse((OUT/'scan.json').read_bytes())
    # Scan status is not inferred from exit-code=0: keep every severity, including UNKNOWN.
    findings = scan_result(report, native['configuration_digest'], service)
    files = {p.name: {'sha256': sha256(p), 'bytes': p.stat().st_size}
             for p in OUT.iterdir() if p.is_file()}
    record = {'schema': 'rick.candidate-build-evidence/v1', 'service': service,
              'source_sha': source, 'builder': builder, **native, 'files': files,
              'scan_findings': findings, 'scan_status': 'NO_FINDINGS' if findings == 0 else 'FINDINGS',
              'production_safe': False, 'promotion_authorized': False,
              'toolchain_review': 'MISSING', 'independent_review': 'MISSING',
              'human_release_decision': 'MISSING', 'signature_scope': 'CI_CONSTRUCTION_INVENTORY_ONLY'}
    write(OUT/'inventory.json', record)


def verify_signature():
    subprocess.run(['cosign', 'verify-blob', '--bundle', str(OUT/'inventory.sigstore.json'),
                    '--certificate-identity', 'https://github.com/'+WORKFLOW,
                    '--certificate-oidc-issuer', ISSUER,
                    '--certificate-github-workflow-sha', os.environ['GITHUB_SHA'],
                    '--certificate-github-workflow-ref', REF,
                    '--certificate-github-workflow-repository', REPO,
                    str(OUT/'inventory.json')], check=True, timeout=180)
    verify_files()


def verify_files():
    record = parse((OUT/'inventory.json').read_bytes())
    if (record.get('schema') != 'rick.candidate-build-evidence/v1'
        or record.get('source_sha') != os.environ['GITHUB_SHA']
        or record.get('service') not in SERVICES
        or record.get('production_safe') is not False
        or record.get('promotion_authorized') is not False
        or record.get('signature_scope') != 'CI_CONSTRUCTION_INVENTORY_ONLY'):
        raise Refusal('exact-SHA nonpromotable construction inventory required')
    expected = {'image.tar', 'scan.json', 'sbom.json', 'provenance.json',
                'quality.json', 'toolchain.json', 'buildx.json'}
    if set(record.get('files', {})) != expected:
        raise Refusal('closed construction file inventory required')
    for name, claimed in record['files'].items():
        path = OUT/name
        if (path.is_symlink() or not path.is_file() or path.stat().st_size != claimed.get('bytes')
            or sha256(path) != claimed.get('sha256')):
            raise Refusal('signed construction file bytes mismatch')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=['prepare', 'inventory', 'verify-signature', 'verify-files', 'require-clean-scan'])
    args = parser.parse_args()
    if args.command == 'prepare':
        prepare()
    elif args.command == 'inventory':
        inventory()
    elif args.command == 'verify-signature':
        verify_signature()
    elif args.command == 'verify-files':
        verify_files()
    elif parse((OUT/'inventory.json').read_bytes())['scan_findings'] != 0:
        raise Refusal('candidate scan findings retained; production remains NO-GO')


if __name__ == '__main__':
    main()
