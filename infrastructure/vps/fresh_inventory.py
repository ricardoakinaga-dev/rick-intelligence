"""Explicit reviewed offline absence inventory for a fresh database bootstrap."""
from __future__ import annotations
from contracts import HEX, Refusal, check_hash, parse

DEPLOYMENT = ('VPS_PROJECT','POSTGRES_DB','POSTGRES_VOLUME','REDIS_VOLUME','QDRANT_VOLUME','OBJECT_VOLUME','CADDY_VOLUME')
VOLUMES = DEPLOYMENT[2:]


def admit(data, trusted, config, manifest, assets):
    check_hash(data,trusted)
    packet = parse(data)
    if (not isinstance(packet,dict) or set(packet) != {'schema','authorization','source_sha','config_sha256',
        'deployment','database_state','absence_evidence','observed'}
        or packet['schema'] != 'rick.vps.fresh-inventory/v1'
        or packet['authorization'] != 'CREATE_REVIEWED_EMPTY_DATABASE'
        or packet['source_sha'] != manifest['source_revision']['value']
        or packet['config_sha256'] != assets['config_sha256']
        or packet['deployment'] != {key:config[key] for key in DEPLOYMENT}
        or packet['database_state'] != 'ABSENT'):
        raise Refusal('explicit independently authorized fresh database absence inventory required')
    evidence = packet['absence_evidence']
    observed = packet['observed']
    if (not isinstance(evidence,dict) or set(evidence) != {'reference','sha256'}
        or not isinstance(evidence['reference'],str) or not evidence['reference'].strip()
        or not isinstance(evidence['sha256'],str) or not HEX.fullmatch(evidence['sha256'])
        or not isinstance(observed,dict) or set(observed) != {'volumes','containers'}
        or observed['containers'] != [] or not isinstance(observed['volumes'],list)
        or len(observed['volumes']) != len(VOLUMES)
        or any(not isinstance(v,dict) or not isinstance(v.get('Name'),str) for v in observed['volumes'])
        or sorted(v['Name'] for v in observed['volumes']) != sorted(config[key] for key in VOLUMES)):
        raise Refusal('reviewed empty prepared volumes, absent containers and absence evidence required')
    return packet


def authorize(packet, volumes, containers):
    if (not isinstance(volumes,list) or any(not isinstance(v,dict) or not isinstance(v.get('Name'),str) for v in volumes)
        or sorted(volumes,key=lambda v:v['Name']) != sorted(packet['observed']['volumes'],key=lambda v:v['Name'])
        or containers != packet['observed']['containers']):
        raise Refusal('current fresh volume/container inventory differs from reviewed absence inventory')
