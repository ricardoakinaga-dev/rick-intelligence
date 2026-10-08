"""Install a reviewed Linux amd64 Buildx release; hash before executing bytes."""
from __future__ import annotations
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
from urllib.request import urlopen
from contracts import HEX, Refusal

def inputs(version, checksum):
    if not isinstance(version,str) or not re.fullmatch(r'v(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)',version):
        raise Refusal('exact reviewed Buildx vMAJOR.MINOR.PATCH required')
    if not isinstance(checksum,str) or not HEX.fullmatch(checksum):
        raise Refusal('reviewed Linux amd64 Buildx binary SHA256 required')
    return f'https://github.com/docker/buildx/releases/download/{version}/buildx-{version}.linux-amd64'

def fetch(url):
    with urlopen(url,timeout=60) as response:
        data = response.read(128*1024*1024+1)
    if len(data)>128*1024*1024:
        raise Refusal('oversized Buildx release binary')
    return data

def execute(argv):
    return subprocess.check_output(argv,text=True,timeout=120).strip()

def install(version, checksum, folder, *, download=fetch, run=execute):
    url = inputs(version,checksum)
    data = download(url)
    if not data or hashlib.sha256(data).hexdigest()!=checksum:
        raise Refusal('Buildx binary checksum mismatch before execution')
    plugin = folder/'cli-plugins'/'docker-buildx'
    plugin.parent.mkdir(mode=0o700,parents=True)
    with plugin.open('xb') as stream:
        stream.write(data)
    plugin.chmod(0o500)
    reported = run([str(plugin),'version'])
    if not re.fullmatch(r'github\.com/docker/buildx '+re.escape(version)+r' [0-9a-f]{7,40}',reported):
        raise Refusal('Buildx binary reported version mismatch')
    return {'version':version,'sha256':checksum,'url':url,'platform':'linux/amd64',
            'reported_version':reported}

def main():
    folder = Path(tempfile.mkdtemp(prefix='rick-buildx-',dir=os.environ['RUNNER_TEMP']))
    evidence = install(os.environ['BUILDX_VERSION'],os.environ['BUILDX_SHA256'],folder)
    # Isolated Docker config makes this verified plugin win over runner plugins.
    # No registry credential is needed until the later copy/sign operation.
    with Path(os.environ['GITHUB_ENV']).open('a') as stream:
        stream.write('DOCKER_CONFIG='+str(folder)+'\n')
    Path('publication/buildx.json').write_text(json.dumps(evidence,sort_keys=True)+'\n')

if __name__=='__main__':
    try:
        main()
    except Exception:
        print('reviewed Buildx installation refused',file=sys.stderr)
        raise SystemExit(2)
