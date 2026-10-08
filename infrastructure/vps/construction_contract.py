"""Offline reviewed construction contract. No policy generation or approval."""
from __future__ import annotations
import argparse
import base64
import binascii
import hashlib
import json
import os
from pathlib import Path
import re
import sys
from contracts import HEX, REPO, SERVICES, Refusal, capture, check_hash, immutable, parse

ROOT = Path(__file__).resolve().parents[2]
META = 'https://mobyproject.org/buildkit@v1#metadata'
BUILD_ARGS = {'PYTHON_IMAGE','NODE_BUILD_IMAGE','NODE_RUNTIME_IMAGE','BUILDKIT_SYNTAX','RICK_API_INTERNAL_URL'}


def canonical_sha256(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':'),ensure_ascii=False,
                                   allow_nan=False).encode('utf-8')).hexdigest()


def material_inventory(materials):
    if not isinstance(materials,list) or not materials:
        raise Refusal('complete reviewed construction materials required')
    entries = []
    for m in materials:
        if (not isinstance(m,dict) or set(m) != {'uri','digest'} or not isinstance(m['uri'],str)
            or not m['uri'] or not isinstance(m['digest'],dict) or len(m['digest']) != 1):
            raise Refusal('exact material URI and immutable digest required')
        algorithm,value = next(iter(m['digest'].items()))
        if algorithm not in {'sha1','sha256'} or not isinstance(value,str) or not re.fullmatch(
            '[0-9a-f]{'+str(40 if algorithm=='sha1' else 64)+'}',value):
            raise Refusal('exact material URI and immutable digest required')
        entries.append(json.dumps(m,sort_keys=True,separators=(',',':')))
    if len(set(entries)) != len(entries) or len({m['uri'] for m in materials}) != len(materials):
        raise Refusal('ambiguous duplicate construction materials')
    return sorted(entries)


def admit_review(data, trusted_sha256, dockerfile_data, *, service, source):
    check_hash(data,trusted_sha256)
    policy = parse(data)
    required = {'schema','service','source_sha','context','dockerfile','dockerfile_sha256',
                'dockerfile_source_name','parameters','materials','base_materials',
                'build_config_sha256','source_mapping_sha256'}
    if (not isinstance(policy,dict) or set(policy) != required
        or policy['schema'] != 'rick.vps.construction-policy/v1'
        or service not in SERVICES or policy['service'] != service
        or not re.fullmatch('[0-9a-f]{40}',source) or policy['source_sha'] != source):
        raise Refusal('independently reviewed service/source construction policy required')
    dockerfile = f'infrastructure/docker/{service}.Dockerfile'
    remote = 'https://github.com/'+REPO+'.git#'+source
    if (policy['context'] != {'uri':remote,'digest':{'sha1':source},'entryPoint':dockerfile}
        or policy['dockerfile'] != dockerfile
        or policy['dockerfile_source_name'] not in {dockerfile,dockerfile.rsplit('/',1)[1]}):
        raise Refusal('reviewed immutable remote Git context and Dockerfile required')
    for key in ('dockerfile_sha256','build_config_sha256','source_mapping_sha256'):
        if not isinstance(policy[key],str) or not HEX.fullmatch(policy[key]):
            raise Refusal('reviewed Dockerfile/recipe/source mapping hashes required')
    check_hash(dockerfile_data,policy['dockerfile_sha256'])
    parameters = policy['parameters']
    if (not isinstance(parameters,dict) or not {'frontend','args'}.issubset(parameters)
        or set(parameters)-{'frontend','args','locals','secrets','ssh','root','compatibilityVersion'}
        or parameters['frontend'] not in {'dockerfile.v0','gateway.v0'}
        or any(parameters.get(k,[]) != [] for k in ('locals','secrets','ssh'))
        or not isinstance(parameters['args'],dict)
        or any(not isinstance(k,str) or not isinstance(v,str) for k,v in parameters['args'].items())):
        raise Refusal('complete secret-free remote construction parameters required')
    if 'compatibilityVersion' in parameters and (
        type(parameters['compatibilityVersion']) is not int or parameters['compatibilityVersion'] <= 0):
        raise Refusal('valid BuildKit compatibility version required')
    if 'root' in parameters:
        root = parameters['root']
        if (not isinstance(root,dict) or not isinstance(root.get('request'),dict)
            or any(root['request'].get(k,[]) != [] for k in ('locals','secrets','ssh'))):
            raise Refusal('secret-free remote root construction request required')
    # Gateway requests can nest frontend requests. Review binds their exact
    # bytes, but no level may introduce a local source, secret or SSH forward.
    pending = [parameters]
    while pending:
        node = pending.pop()
        if isinstance(node,dict):
            if any(k in node and node[k] != [] for k in ('locals','secrets','ssh')):
                raise Refusal('secret-free remote construction required at every request level')
            pending.extend(node.values())
        elif isinstance(node,list):
            pending.extend(node)
    args = parameters['args']
    if {k.removeprefix('build-arg:') for k in args if k.startswith('build-arg:')} != BUILD_ARGS:
        raise Refusal('exact reviewed construction build arguments required')
    for key in BUILD_ARGS-{'RICK_API_INTERNAL_URL'}:
        immutable(args['build-arg:'+key])
    if (args['build-arg:RICK_API_INTERNAL_URL'] != 'http://api:8000'
        or args.get('label:org.opencontainers.image.source') != 'https://github.com/'+REPO
        or args.get('label:org.opencontainers.image.revision') != source):
        raise Refusal('reviewed application URL and source labels required')
    material_inventory(policy['materials'])
    git_material = {'uri':remote,'digest':{'sha1':source}}
    if git_material not in policy['materials']:
        raise Refusal('resolved immutable Git context material required')
    bases = policy['base_materials']
    used = {'BUILDKIT_SYNTAX'} | ({'PYTHON_IMAGE'} if service in {'api','worker'} else {'NODE_BUILD_IMAGE','NODE_RUNTIME_IMAGE'})
    if not isinstance(bases,dict) or set(bases) != used:
        raise Refusal('every used base/frontend must map to a reviewed resolved material')
    for key,binding in bases.items():
        if (not isinstance(binding,dict) or set(binding) != {'image_ref','material'}
            or binding['image_ref'] != args['build-arg:'+key]
            or binding['material'] not in policy['materials']
            or not binding['material']['uri'].startswith('pkg:docker/')
            or set(binding['material']['digest']) != {'sha256'}):
            raise Refusal('reviewed base/frontend reference-to-resolved-material binding required')
    # Multi-platform ref digest can differ from resolved material digest. This
    # mapping is an explicit reviewer input; it is never inferred from env/VCS.
    return policy


def verify_recipe(predicate, policy):
    invocation = predicate.get('invocation',{})
    metadata = predicate.get('metadata',{})
    if (invocation.get('configSource') != policy['context']
        or invocation.get('parameters') != policy['parameters']
        or metadata.get('completeness',{}).get('parameters') is not True
        or metadata.get('completeness',{}).get('materials') is not True):
        raise Refusal('provenance context/arguments/completeness differ from reviewed construction')
    if material_inventory(predicate.get('materials')) != material_inventory(policy['materials']):
        raise Refusal('provenance resolved materials differ from reviewed construction')
    build = predicate.get('buildConfig',{})
    steps = build.get('llbDefinition',[])
    if (not isinstance(steps,list) or not steps or any(not isinstance(s,dict) or not s.get('id')
        or not isinstance(s.get('op'),dict) or not isinstance(s['op'].get('Op'),dict) for s in steps)
        or len({s['id'] for s in steps}) != len(steps)
        or canonical_sha256(build) != policy['build_config_sha256']):
        raise Refusal('provenance LLB recipe differs from reviewed construction')
    mapping = metadata.get(META,{}).get('source',{})
    if not isinstance(mapping,dict) or canonical_sha256(mapping) != policy['source_mapping_sha256']:
        raise Refusal('provenance source mapping differs from reviewed construction')
    infos = mapping.get('infos',[])
    locations = mapping.get('locations',{})
    if (not isinstance(infos,list) or not isinstance(locations,dict) or not locations
        or not set(locations).issubset({s['id'] for s in steps})
        or not any(isinstance(v,dict) and v.get('locations') for v in locations.values())
        or any(not isinstance(v,dict) or set(v)-{'locations'}
               or not isinstance(v.get('locations',[]),list)
               for v in locations.values())):
        raise Refusal('LLB source locations required')
    for wrapper in locations.values():
        for location in wrapper.get('locations',[]):
            if (not isinstance(location,dict) or set(location)-{'sourceIndex','ranges'}
                or type(location.get('sourceIndex',0)) is not int
                or not 0 <= location.get('sourceIndex',0) < len(infos)
                or not isinstance(location.get('ranges'),list) or not location['ranges']):
                raise Refusal('valid LLB source references required')
    matches = [i for i in infos if isinstance(i,dict) and i.get('filename') == policy['dockerfile_source_name']]
    if len(matches) != 1:
        raise Refusal('one reviewed embedded Dockerfile required')
    try:
        dockerfile = base64.b64decode(matches[0]['data'],validate=True)
    except (KeyError,TypeError,ValueError,binascii.Error):
        raise Refusal('BuildKit embedded Dockerfile bytes required') from None
    check_hash(dockerfile,policy['dockerfile_sha256'])
    return {'policy_schema':policy['schema'],'context':invocation['configSource'],
            'dockerfile':policy['dockerfile'],'dockerfile_sha256':hashlib.sha256(dockerfile).hexdigest(),
            'parameters':invocation['parameters'],'materials':predicate['materials'],
            'base_materials':policy['base_materials'],
            'build_config_sha256':canonical_sha256(build),'source_mapping_sha256':canonical_sha256(mapping)}


def environment_review(service, source):
    data = os.environ.get('CONSTRUCTION_POLICY_JSON','').encode()
    trusted = os.environ.get('CONSTRUCTION_POLICY_SHA256','')
    dockerfile = capture(ROOT/f'infrastructure/docker/{service}.Dockerfile')
    policy = admit_review(data,trusted,dockerfile,service=service,source=source)
    # Bind actual workflow args to reviewed inputs before build, independently
    # of the later comparison to evidence from the resulting archive.
    for key in BUILD_ARGS-{'RICK_API_INTERNAL_URL'}:
        env_key = 'DOCKERFILE_FRONTEND_IMAGE' if key == 'BUILDKIT_SYNTAX' else key
        if policy['parameters']['args']['build-arg:'+key] != os.environ.get(env_key):
            raise Refusal('workflow build input differs from construction review')
    return data,trusted,dockerfile


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--policy',type=Path)
    parser.add_argument('--trusted-policy-sha256')
    parser.add_argument('--service',choices=SERVICES)
    parser.add_argument('--source')
    parser.add_argument('--archive',type=Path)
    parser.add_argument('--built-digest')
    parser.add_argument('--builder')
    parser.add_argument('--output',type=Path)
    args = parser.parse_args()
    service = args.service or os.environ['SERVICE']; source = args.source or os.environ['SOURCE_SHA']
    if args.policy:
        review = (capture(args.policy,private=True),args.trusted_policy_sha256,
                  capture(ROOT/f'infrastructure/docker/{service}.Dockerfile'))
        admit_review(*review,service=service,source=source)
    else:
        review = environment_review(service,source)
    if args.archive:
        if not args.output or not args.built_digest or not args.builder:
            raise Refusal('archive check requires exact built digest, builder and output directory')
        import publish_candidate
        publish_candidate.OUT = args.output
        args.output.mkdir(mode=0o700,parents=True,exist_ok=True)
        publish_candidate.oci_evidence(args.archive,args.built_digest,
            image=f'ghcr.io/{REPO}-{service}',source=source,builder=args.builder,review=review)
    print('reviewed construction contract matched; no authentication or release approval conferred')

if __name__ == '__main__':
    try:
        main()
    except Exception:
        print('construction contract refused; reviewed inputs or evidence unavailable',file=sys.stderr)
        raise SystemExit(2)
