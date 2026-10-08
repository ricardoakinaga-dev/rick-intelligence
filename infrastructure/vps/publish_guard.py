"""Same-SHA hosted construction gates and immutable publication inputs."""
from __future__ import annotations
import json
import os
from pathlib import Path
import re
import sys
from urllib.request import Request, urlopen
from contracts import REPO, Refusal, immutable

INPUTS = ('PYTHON_IMAGE','NODE_BUILD_IMAGE','NODE_RUNTIME_IMAGE','BUILDKIT_IMAGE',
          'DOCKERFILE_FRONTEND_IMAGE','SBOM_GENERATOR_IMAGE','TRIVY_IMAGE','SKOPEO_IMAGE')
REQUIRED_JOBS = ('FAST / control and static','UNIT / root packages',
                 'CONTRACT / API and OpenAPI','SECURITY / adversarial and route policy',
                 'RAG-EVAL / deterministic and ACL','FRONTEND / build surface',
                 'SUPPLY-CHAIN / dependency and secret policy',
                 'PHASE3 / capability evidence matrix')

def validate_run(run, jobs, source):
    if (run.get('head_sha') != source or run.get('head_branch') != 'main'
        or run.get('path') != '.github/workflows/quality.yml'
        or run.get('status') != 'completed' or run.get('conclusion') not in {'success', 'failure'}
        or run.get('event') not in {'push','workflow_dispatch'}
        or run.get('head_repository', {}).get('full_name') != REPO):
        raise Refusal('completed same-SHA main quality run required')
    # Production promotion consumes the built images later. Requiring that
    # promotion to succeed before image construction creates a release cycle.
    # Inspect every construction gate in this attempt; the signed candidate
    # predicate remains promotion_authorized=false, including failed releases.
    if len({job['name'] for job in jobs}) != len(jobs):
        raise Refusal('ambiguous duplicate quality jobs')
    observed = {job['name']: job.get('conclusion') for job in jobs}
    for name in REQUIRED_JOBS:
        if observed.get(name) != 'success':
            raise Refusal('required quality job missing, skipped or unsuccessful')

def api(path):
    request = Request('https://api.github.com/repos/'+REPO+'/'+path,
        headers={'Authorization': 'Bearer '+os.environ['GH_TOKEN'], 'Accept':'application/vnd.github+json',
                 'X-GitHub-Api-Version':'2022-11-28'})
    with urlopen(request, timeout=30) as response:
        return json.load(response)

def main():
    source = os.environ['SOURCE_SHA']
    run_id = os.environ['QUALITY_RUN_ID']
    if not re.fullmatch('[0-9a-f]{40}', source) or not re.fullmatch('[1-9][0-9]*', run_id):
        raise Refusal('full source SHA and numeric quality run required')
    if os.environ.get('GITHUB_REPOSITORY') != REPO or os.environ.get('GITHUB_REF') != 'refs/heads/main':
        raise Refusal('publication only from canonical main workflow')
    for name in INPUTS:
        immutable(os.environ.get(name, ''))
    from admission import environment_tools, quality_record
    environment_tools()
    from buildx_binary import inputs
    inputs(os.environ.get('BUILDX_VERSION'),os.environ.get('BUILDX_SHA256'))
    if api('branches/main')['commit']['sha'] != source:
        raise Refusal('candidate source must be the exact current main SHA')
    run = api('actions/runs/'+run_id)
    jobs = []
    page = 1
    while True:
        batch = api(f'actions/runs/{run_id}/attempts/{run["run_attempt"]}/jobs?per_page=100&page={page}')['jobs']
        jobs.extend(batch)
        if len(batch) < 100:
            break
        page += 1
    validate_run(run, jobs, source)
    Path('publication').mkdir(exist_ok=True)
    record = {'run_url':run['html_url'],
        'run_id':int(run_id),'run_attempt':run['run_attempt'],'head_sha':source,
        'conclusion':run['conclusion'],'required_jobs':list(REQUIRED_JOBS),
        'path':run['path'],'event':run['event'],'head_branch':run['head_branch'],
        'head_repository':run['head_repository']['full_name'],'status':run['status'],
        'job_conclusions':{name:'success' for name in REQUIRED_JOBS}}
    quality_record(record,source)
    # Exclusive private creation; existing/shared authority inputs are refused.
    fd = os.open('publication/quality.json', os.O_WRONLY | os.O_CREAT | os.O_EXCL |
                 os.O_NOFOLLOW | os.O_CLOEXEC, 0o600)
    with os.fdopen(fd,'w') as output:
        output.write(json.dumps(record,sort_keys=True)+'\n')
    print('same-SHA quality and immutable publication inputs verified; promotion not authorized')

if __name__ == '__main__':
    try:
        main()
    except Exception:
        print('publication prerequisites refused', file=sys.stderr)
        raise SystemExit(2)
