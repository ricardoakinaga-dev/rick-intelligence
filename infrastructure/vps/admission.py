"""Independent candidate policies; consumes authority inputs, never creates them."""
from __future__ import annotations
import json
import os
import re
from contracts import REPO, SERVICES, Refusal, check_hash, immutable, parse
from construction_contract import admit_review, canonical_sha256
from publish_guard import INPUTS, REQUIRED_JOBS
from buildx_binary import inputs as buildx_url

TOOLS = ('BUILDKIT_IMAGE','DOCKERFILE_FRONTEND_IMAGE','SBOM_GENERATOR_IMAGE','TRIVY_IMAGE','SKOPEO_IMAGE')


def reviewed(entry):
    if not isinstance(entry,dict) or set(entry) != {'json','sha256'} or not isinstance(entry['json'],str):
        raise Refusal('independent policy bytes and identity required')
    data = entry['json'].encode('utf-8')
    check_hash(data,entry['sha256'])
    return parse(data), data


def tool_policy(data, trusted):
    check_hash(data,trusted)
    policy = parse(data)
    if (not isinstance(policy,dict) or set(policy) != {'schema','images','buildx','cosign_version','scan'}
        or policy['schema'] != 'rick.vps.tool-policy/v1' or set(policy['images']) != set(INPUTS)
        or set(policy['buildx']) != {'version','sha256'} or policy['cosign_version'] != 'v2.5.3'
        or set(policy['scan']) != set(SERVICES)):
        raise Refusal('complete independently reviewed publication tool policy required')
    for ref in policy['images'].values():
        immutable(ref)
    buildx_url(policy['buildx']['version'],policy['buildx']['sha256'])
    for service, scan in policy['scan'].items():
        expected = {'os_family':'debian','language_types':['python-pkg']} if service in {'api','worker'} else {
            'os_family':'alpine','language_types':['node-pkg']}
        if scan != expected:
            raise Refusal('reviewed scanner must cover runtime OS and application packages')
    return policy


def environment_tools():
    data = os.environ.get('TOOL_POLICY_JSON','').encode()
    trusted = os.environ.get('TOOL_POLICY_SHA256','')
    policy = tool_policy(data,trusted)
    if (any(os.environ.get(key) != value for key,value in policy['images'].items())
        or os.environ.get('BUILDX_VERSION') != policy['buildx']['version']
        or os.environ.get('BUILDX_SHA256') != policy['buildx']['sha256']):
        raise Refusal('workflow inputs differ from independent publication tool policy')
    return policy, trusted


def quality_record(record, source):
    required = {'run_url','run_id','run_attempt','head_sha','conclusion','required_jobs',
                'path','event','head_branch','head_repository','status','job_conclusions'}
    if (not isinstance(record,dict) or set(record) != required
        or type(record['run_id']) is not int or record['run_id'] <= 0
        or type(record['run_attempt']) is not int or record['run_attempt'] <= 0
        or record['run_url'] != f'https://github.com/{REPO}/actions/runs/{record["run_id"]}'
        or record['head_sha'] != source or record['path'] != '.github/workflows/quality.yml'
        or record['head_branch'] != 'main' or record['head_repository'] != REPO
        or record['event'] not in {'push','workflow_dispatch'} or record['status'] != 'completed'
        or record['conclusion'] not in {'success','failure'}
        or record['required_jobs'] != list(REQUIRED_JOBS)
        or record['job_conclusions'] != {name:'success' for name in REQUIRED_JOBS}):
        raise Refusal('exact completed same-source quality attempt and successful construction jobs required')
    return record


def deployment_policy(data, trusted, manifest, files):
    check_hash(data,trusted)
    policy = parse(data)
    source = manifest['source_revision']['value']
    if (not isinstance(policy,dict) or set(policy) != {'schema','source_sha','construction','tool_policy','quality'}
        or policy['schema'] != 'rick.vps.admission-policy/v1' or policy['source_sha'] != source
        or set(policy['construction']) != set(SERVICES)):
        raise Refusal('independent source-bound deployment admission policy required')
    for service,entry in policy['construction'].items():
        _, raw = reviewed(entry)
        admit_review(raw,entry['sha256'],files[f'infrastructure/docker/{service}.Dockerfile'],
                     service=service,source=source)
    _, raw = reviewed(policy['tool_policy'])
    tools = tool_policy(raw,policy['tool_policy']['sha256'])
    for entry in policy['construction'].values():
        construction,_ = reviewed(entry)
        arguments = construction['parameters']['args']
        for key in ('PYTHON_IMAGE','NODE_BUILD_IMAGE','NODE_RUNTIME_IMAGE','BUILDKIT_SYNTAX'):
            image_key = 'DOCKERFILE_FRONTEND_IMAGE' if key == 'BUILDKIT_SYNTAX' else key
            if arguments['build-arg:'+key] != tools['images'][image_key]:
                raise Refusal('construction and independent tool/base identities differ')
    quality_record(policy['quality'],source)
    return policy


def candidate_policy(predicate, service, policy):
    if policy is None:
        raise Refusal('independent deployment admission policy required')
    reviewed_construction,_ = reviewed(policy['construction'][service])
    expected = {key:reviewed_construction[key] for key in (
        'context','dockerfile','dockerfile_sha256','parameters','materials','base_materials',
        'build_config_sha256','source_mapping_sha256')}
    expected.update(policy_schema=reviewed_construction['schema'],
                    policy_sha256=policy['construction'][service]['sha256'])
    if predicate.get('construction') != expected:
        raise Refusal('signed construction differs from independent reviewed identity')
    tools,_ = reviewed(policy['tool_policy'])
    buildx = predicate.get('buildx_binary',{})
    version = tools['buildx']['version']; checksum = tools['buildx']['sha256']
    if (predicate.get('tool_policy_sha256') != policy['tool_policy']['sha256']
        or predicate.get('configured_build_tools') != {key:tools['images'][key] for key in TOOLS}
        or predicate.get('base_images') != {key:tools['images'][key] for key in
                                          ('PYTHON_IMAGE','NODE_BUILD_IMAGE','NODE_RUNTIME_IMAGE')}
        or set(buildx) != {'version','sha256','url','platform','reported_version'}
        or buildx['version'] != version or buildx['sha256'] != checksum
        or buildx['url'] != buildx_url(version,checksum) or buildx['platform'] != 'linux/amd64'
        or not re.fullmatch(r'github\.com/docker/buildx '+re.escape(version)+r' [0-9a-f]{7,40}',
                            str(buildx.get('reported_version','')))):
        raise Refusal('signed tool/base/Buildx identity differs from independently reviewed policy')
    if (predicate.get('quality') != policy['quality']
        or predicate.get('quality_sha256') != canonical_sha256(policy['quality'])):
        raise Refusal('signed quality attempt differs from independently reviewed evidence')
    quality_record(predicate['quality'],policy['source_sha'])
    workflow = predicate.get('workflow_run','')
    if (not re.fullmatch(re.escape(f'https://github.com/{REPO}/actions/runs/')+r'[1-9][0-9]*',workflow)
        or predicate.get('builder_id') != workflow):
        raise Refusal('signed builder/publication run identity required')
    coverage = predicate.get('scan_coverage')
    if (not isinstance(coverage,list) or len(coverage) != 1
        or coverage[0].get('digest') != predicate.get('application_digest')
        or coverage[0].get('platform') != {'os':'linux','architecture':'amd64'}
        or not re.fullmatch('sha256:[0-9a-f]{64}',str(coverage[0].get('config_digest','')))
        or predicate.get('scan_requirements') != tools['scan'][service]):
        raise Refusal('signed substantive scanner coverage and policy binding required')
    for key in ('scan_sha256','oci_sha256','sbom_sha256','provenance_sha256'):
        if not re.fullmatch('[0-9a-f]{64}',str(predicate.get(key,''))):
            raise Refusal('signed candidate evidence hash missing')
