"""Execute only authenticated captured application admission source bytes.

The independently installed launch bootstrap (deploy/assets/contracts), Python
and PyYAML are host trust roots. Shared repository modules are never imported.
"""
from __future__ import annotations
import builtins
from pathlib import Path
from types import ModuleType
from contracts import Refusal, check_hash

ORDER = (
    ('contracts','infrastructure/vps/contracts.py'),
    ('json_boundary','scripts/state_of_art/json_boundary.py'),
    ('construction_contract','infrastructure/vps/construction_contract.py'),
    ('publish_guard','infrastructure/vps/publish_guard.py'),
    ('buildx_binary','infrastructure/vps/buildx_binary.py'),
    ('admission','infrastructure/vps/admission.py'),
    ('db_guard','infrastructure/vps/db_guard.py'),
    ('fresh_inventory','infrastructure/vps/fresh_inventory.py'),
    ('check_release','infrastructure/docker/check_release.py'),
)


def modules(packet, files, folder):
    for name, data in files.items():
        check_hash(data,packet['files'][name])
    loaded = {}
    def captured_import(name, globals=None, locals=None, fromlist=(), level=0):
        if name == 'scripts.state_of_art.json_boundary':
            if not fromlist:
                raise Refusal('unsupported captured package import')
            return loaded['json_boundary']
        if name in loaded:
            return loaded[name]
        if name in {n for n,_ in ORDER} or name.startswith(('scripts.','infrastructure.')):
            raise Refusal('uncaptured executable import refused')
        return builtins.__import__(name,globals,locals,fromlist,level)
    for name, relative in ORDER:
        if relative not in files:
            raise Refusal('complete captured executable admission closure required')
        module = ModuleType('rick_captured_'+name)
        module.__file__ = str(Path(folder)/relative)
        module.__dict__['__builtins__'] = {**vars(builtins),'__import__':captured_import}
        exec(compile(files[relative],module.__file__,'exec'),module.__dict__)
        if name == 'contracts':
            # A single stable, redacted refusal type across the bootstrap seam.
            module.Refusal = Refusal
        loaded[name] = module
    return loaded


def release_errors(args, folder):
    packet, files, _ = args.captured_assets
    folder = Path(folder)
    # The existing checker reads Dockerfiles/policy relative to its __file__.
    # Only authenticated snapshots are supplied; its shared code is unchanged.
    for relative, data in files.items():
        path = folder/relative
        path.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
        with path.open('xb') as stream:
            stream.write(data)
        path.chmod(0o400)
    loaded = modules(packet,files,folder)
    checker = loaded['check_release']
    # Close JSON reads in memory as well: the checker cannot reopen any live
    # repository policy or an alternate name chosen by the manifest.
    allowed = {folder/'infrastructure/docker/rollout-policy.json':
               files['infrastructure/docker/rollout-policy.json'],args.manifest:args.manifest.read_bytes()}
    def captured_json(path):
        if path not in allowed:
            raise Refusal('release checker requested uncaptured policy')
        return loaded['json_boundary'].loads_json(allowed[path])
    checker.load_json = captured_json
    return checker.validate_release(args.manifest,mode='candidate')
