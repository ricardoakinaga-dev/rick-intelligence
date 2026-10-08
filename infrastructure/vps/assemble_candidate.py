"""Assemble actual hosted fragments into the existing REC-33 construction packet.

Rollout remains NOT_RUN; this command cannot approve a release.
"""
from __future__ import annotations
import argparse
import json
from pathlib import Path
from contracts import REPO, SERVICES, Refusal, immutable, load

ROOT = Path(__file__).resolve().parents[2]

def assemble(folder):
    fragments = {service:load(folder/service/'candidate.json') for service in SERVICES}
    sources = {fragment['source_sha'] for fragment in fragments.values()}
    if len(sources)!=1:
        raise Refusal('candidate sources differ')
    publication_runs = {f['publication']['workflow_run'] for f in fragments.values()}
    if len(publication_runs)!=1:
        raise Refusal('candidate publication runs differ')
    manifest = load(ROOT/'infrastructure/docker/release-manifest.json')
    manifest['status']='CANDIDATE'
    manifest['release_id']='ghcr-'+next(iter(sources))
    manifest['source_revision']={'value':next(iter(sources)),'status':'CAPTURED'}
    manifest['build']['status']='PASS'
    manifest['images']=[]
    for service,fragment in fragments.items():
        if fragment['status']!='CANDIDATE' or fragment['service']!=service:
            raise Refusal('candidate construction fragment invalid')
        immutable(fragment['image_ref'],f'ghcr.io/{REPO}-{service}')
        manifest['images'].append({k:v for k,v in fragment.items() if k not in {'source_sha','status'}})
    bases = fragments['api']['publication']['base_images']
    for fragment in fragments.values():
        if fragment['publication']['base_images']!=bases:
            raise Refusal('base image inputs differ')
    for base in manifest['base_images']:
        base['ref']=immutable(bases[base['argument']])
        base['status']='CAPTURED'
    # Preserve canary/rollback NOT_RUN from the canonical prepared template.
    if manifest['rollout']['canary']['status']!='NOT_RUN' or manifest['rollout']['rollback']['status']!='NOT_RUN':
        raise Refusal('construction template must not carry rollout authority')
    return manifest

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('evidence',type=Path)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    try:
        manifest=assemble(args.evidence)
        with args.output.open('x') as stream:
            json.dump(manifest,stream,indent=2,sort_keys=True)
            stream.write('\n')
    except Exception:
        raise SystemExit('candidate assembly refused')
