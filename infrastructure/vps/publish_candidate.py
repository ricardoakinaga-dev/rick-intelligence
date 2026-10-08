"""Scan exact local OCI artifact, then publish/sign/verify a hosted candidate."""
from __future__ import annotations
import base64
import hashlib
from datetime import datetime
from contextlib import contextmanager
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tarfile
import tempfile
import stat
import zlib
from urllib.parse import parse_qs, unquote
from construction_contract import admit_review, environment_review, verify_recipe
from contracts import IDENTITY, ISSUER, PREDICATE, REPO, Refusal, immutable, parse

OUT = Path('publication').resolve()
MAX_ARCHIVE_BYTES = 8 * 1024**3
MAX_MEMBER_BYTES = 2 * 1024**3
MAX_MEMBERS = 4096
MAX_METADATA_BYTES = 16 * 1024**2
MAX_LAYER_BYTES = 2 * 1024**3
MAX_ROOTFS_BYTES = 8 * 1024**3
MAX_LAYER_MEMBERS = 100000
MAX_ROOTFS_MEMBERS = 200000
MAX_LAYER_EXTENSION_BYTES = 1024**2


def reviewed_runtime_user(dockerfile):
    """Closed interpretation of the reviewed final stage's explicit USER.

    No inherited, named, variable, heredoc or ONBUILD identity is inferred.
    The construction policy already binds these exact Dockerfile bytes.
    """
    try:
        text = dockerfile.decode('utf-8')
    except UnicodeError:
        raise Refusal('reviewed runtime Dockerfile encoding required') from None
    if '<<' in text or re.search(r'^\s*#\s*escape\s*=',text,re.I|re.M):
        raise Refusal('unsupported reviewed runtime Dockerfile syntax')
    pending = ''
    user = None
    stage = False
    for line in text.splitlines():
        if not line.strip() or line.lstrip().startswith('#'):
            continue
        pending += line.strip()
        if pending.endswith('\\'):
            pending = pending[:-1]+' '
            continue
        instruction, _, value = pending.partition(' ')
        pending = ''
        if instruction.upper() == 'FROM':
            stage = True; user = None
        elif instruction.upper() == 'USER':
            user = value.strip()
        elif instruction.upper() == 'ONBUILD':
            raise Refusal('unproved ONBUILD runtime identity refused')
    if pending or not stage or user != '10001:10001':
        raise Refusal('reviewed final-stage runtime UID:GID 10001:10001 required')
    return user


class LayerTarInventory:
    """Streaming structural check only: never extract layer paths or links."""
    def __init__(self):
        self.header = bytearray()
        self.remaining = self.padding = self.members = self.zeros = 0
        self.extension = None
        self.extension_pending = False

    def feed(self, chunk):
        view = memoryview(chunk)
        while view:
            if self.remaining:
                take = min(self.remaining,len(view))
                if self.extension is not None:
                    self.extension.extend(view[:take])
                self.remaining -= take; view = view[take:]
                if not self.remaining and self.extension is not None:
                    self.check_extension()
                continue
            if self.padding:
                take = min(self.padding,len(view))
                if any(view[:take]):
                    raise Refusal('nonzero layer member padding refused')
                self.padding -= take; view = view[take:]
                continue
            take = min(512-len(self.header),len(view))
            self.header.extend(view[:take]); view = view[take:]
            if len(self.header) < 512:
                continue
            header = bytes(self.header); self.header.clear()
            if header == bytes(512):
                self.zeros += 1
                continue
            if self.zeros:
                raise Refusal('nonzero content after layer terminator refused')
            try:
                member = tarfile.TarInfo.frombuf(header,'utf-8','strict')
            except (tarfile.HeaderError,UnicodeError,ValueError):
                raise Refusal('invalid application layer tar header') from None
            self.members += 1
            if self.members > MAX_LAYER_MEMBERS or not 0 <= member.size <= MAX_LAYER_BYTES:
                raise Refusal('application layer member work exceeds bound')
            extensions = {tarfile.XHDTYPE,tarfile.GNUTYPE_LONGNAME,tarfile.GNUTYPE_LONGLINK}
            if member.type not in extensions | {tarfile.REGTYPE,tarfile.AREGTYPE,tarfile.DIRTYPE,
                    tarfile.SYMTYPE,tarfile.LNKTYPE,tarfile.CHRTYPE,tarfile.BLKTYPE,tarfile.FIFOTYPE}:
                raise Refusal('unsupported application layer tar member format')
            if member.type in extensions:
                if not 0 < member.size <= MAX_LAYER_EXTENSION_BYTES:
                    raise Refusal('application layer extension exceeds bound')
                self.extension = bytearray(); self.extension_type = member.type
                self.extension_pending = True
            else:
                self.extension_pending = False
                if member.type not in {tarfile.REGTYPE,tarfile.AREGTYPE} and member.size:
                    raise Refusal('non-file layer payload refused')
            self.remaining = member.size
            self.padding = (-member.size) % 512

    def check_extension(self):
        payload = bytes(self.extension); self.extension = None
        if self.extension_type != tarfile.XHDTYPE:
            if not payload.endswith(b'\0'):
                raise Refusal('invalid layer long-name metadata')
            return
        offset = 0
        while offset < len(payload):
            space = payload.find(b' ',offset,min(len(payload),offset+24))
            try:
                length_text = payload[offset:space]
                if space < 0 or not length_text.isdigit():
                    raise ValueError
                length = int(length_text)
                if length <= space-offset+1 or offset+length > len(payload):
                    raise ValueError
                record = payload[space+1:offset+length]
                key,sep,_ = record[:-1].partition(b'=')
                if not sep or not key or not record.endswith(b'\n'):
                    raise ValueError
            except ValueError:
                raise Refusal('invalid bounded layer PAX metadata') from None
            if key == b'size' or b'sparse' in key.lower() or key == b'SCHILY.realsize':
                raise Refusal('unsupported layer PAX size/sparse semantics')
            offset += length

    def finish(self):
        if (self.header or self.remaining or self.padding or self.zeros < 2
            or self.extension_pending):
            raise Refusal('complete application layer tar required')


def layer_diff_id(stream, media, budget):
    """Hash uncompressed tar bytes; cap output, chunks and member work."""
    if media not in {'application/vnd.oci.image.layer.v1.tar',
                     'application/vnd.oci.image.layer.v1.tar+gzip'}:
        raise Refusal('unsupported/unproved application layer compression')
    decoder = zlib.decompressobj(31) if media.endswith('+gzip') else None
    inventory = LayerTarInventory()
    h = hashlib.sha256(); size = 0
    def consume(chunk):
        nonlocal size
        size += len(chunk); budget['bytes'] += len(chunk)
        if size > MAX_LAYER_BYTES or budget['bytes'] > MAX_ROOTFS_BYTES:
            raise Refusal('decompressed application rootfs exceeds bound')
        h.update(chunk); inventory.feed(chunk)
        if budget['members']+inventory.members > MAX_ROOTFS_MEMBERS:
            raise Refusal('application rootfs member work exceeds bound')
    try:
        while chunk := stream.read(65536):
            if decoder is None:
                consume(chunk)
                continue
            if decoder.eof:
                raise Refusal('concatenated/trailing application gzip bytes refused')
            pending = chunk
            while pending:
                consume(decoder.decompress(pending,65536))
                if decoder.unused_data:
                    raise Refusal('concatenated/trailing application gzip bytes refused')
                pending = decoder.unconsumed_tail
        if decoder is not None and not decoder.eof:
            raise Refusal('truncated application gzip stream refused')
    except zlib.error:
        raise Refusal('invalid application gzip stream') from None
    inventory.finish(); budget['members'] += inventory.members
    return 'sha256:'+h.hexdigest()

def command(argv):
    result = subprocess.run(argv,capture_output=True,text=True,timeout=1200)
    if result.returncode:
        raise Refusal('publication tool failed; candidate is not admitted')
    return result.stdout

def statement_evidence(statement, kind, application, image, source, builder, policy):
    if (statement.get('_type') not in {'https://in-toto.io/Statement/v0.1','https://in-toto.io/Statement/v1'}
        or statement.get('predicateType') != kind):
        raise Refusal('OCI attestation type mismatch')
    subjects = statement.get('subject',[])
    # BuildKit derives purl subjects from the explicit exporter name; do not
    # accept the unnamed '_' default or a well-hashed unrelated named image.
    if not isinstance(subjects,list) or len(subjects) != 1:
        raise Refusal('OCI attestation application subject required')
    for subject in subjects:
        name = unquote(subject.get('name',''))
        path,sep,query = name.partition('?')
        target = path.removeprefix('pkg:docker/').split('@',1)[0]
        if (not path.startswith('pkg:docker/') or target != image
            or parse_qs(query).get('platform') != ['linux/amd64']
            or subject.get('digest') != {'sha256':application.split(':')[1]}):
            raise Refusal('OCI attestation subject does not describe intended application/platform/name')
    predicate = statement.get('predicate',{})
    if kind == 'https://spdx.dev/Document':
        spdx_packages(predicate)
        return
    metadata = predicate.get('metadata',{})
    if (kind != 'https://slsa.dev/provenance/v0.2'
        or predicate.get('buildType') != 'https://mobyproject.org/buildkit@v1'
        or predicate.get('builder',{}).get('id') != builder):
        raise Refusal('source/recipe/builder-bound BuildKit provenance required')
    binding = verify_recipe(predicate,policy)
    try:
        started = datetime.fromisoformat(metadata['buildStartedOn'].replace('Z','+00:00'))
        finished = datetime.fromisoformat(metadata['buildFinishedOn'].replace('Z','+00:00'))
        if started.tzinfo is None or finished.tzinfo is None or finished < started:
            raise ValueError('invalid build timestamps')
    except (TypeError,ValueError):
        raise Refusal('valid provenance build timestamps required')
    return binding

def spdx_packages(document):
    """Validate native SPDX structure without treating an aggregate as a package."""
    def text(value):
        return isinstance(value,str) and bool(value.strip()) and value not in {'NOASSERTION','NONE'}
    if (not isinstance(document,dict) or document.get('SPDXID') != 'SPDXRef-DOCUMENT'
        or document.get('spdxVersion') not in {'SPDX-2.2','SPDX-2.3'}
        or not text(document.get('name')) or not text(document.get('documentNamespace'))
        or not isinstance(document.get('creationInfo'),dict)
        or not document['creationInfo'].get('creators') or not document['creationInfo'].get('created')):
        raise Refusal('substantive SPDX SBOM required')
    packages, files, relationships = (document.get(k) for k in ('packages','files','relationships'))
    if any(not isinstance(items,list) or not items for items in (packages,files,relationships)):
        raise Refusal('substantive SPDX packages, files and relationships required')
    nodes = {'SPDXRef-DOCUMENT'}
    for item in packages+files:
        if (not isinstance(item,dict) or not isinstance(item.get('SPDXID'),str)
            or not item['SPDXID'].startswith('SPDXRef-') or item['SPDXID'] in nodes):
            raise Refusal('unique SPDX package/file identities required')
        nodes.add(item['SPDXID'])
    for file in files:
        checksums = file.get('checksums')
        if (not text(file.get('fileName')) or not isinstance(checksums,list) or not checksums
            or any(not isinstance(c,dict) or c.get('algorithm') not in {'SHA1','SHA256','SHA512'}
                or not isinstance(c.get('checksumValue'),str)
                or not re.fullmatch('[0-9a-fA-F]{'+str({'SHA1':40,'SHA256':64,'SHA512':128}[c['algorithm']])+'}',c['checksumValue'])
                for c in checksums)):
            raise Refusal('SPDX file content identities required')
    graph = {node:set() for node in nodes}
    described = set()
    for rel in relationships:
        if (not isinstance(rel,dict) or rel.get('spdxElementId') not in nodes
            or rel.get('relatedSpdxElement') not in nodes or not text(rel.get('relationshipType'))):
            raise Refusal('closed SPDX relationships required')
        start,end,kind = rel['spdxElementId'],rel['relatedSpdxElement'],rel['relationshipType']
        if kind in {'DESCRIBES','CONTAINS','DEPENDS_ON'}:
            graph[start].add(end)
        elif kind == 'DEPENDENCY_OF':
            graph[end].add(start)
        if start == 'SPDXRef-DOCUMENT' and kind == 'DESCRIBES':
            described.add(end)
    reached, pending = set(), ['SPDXRef-DOCUMENT']
    while pending:
        node = pending.pop()
        if node not in reached:
            reached.add(node); pending.extend(graph[node]-reached)
    versioned = []
    for package in packages:
        if not text(package.get('name')) or package['SPDXID'] not in reached:
            raise Refusal('described SPDX package identities required')
        if text(package.get('versionInfo')):
            versioned.append(package)
        elif (package['SPDXID'] not in described or package.get('primaryPackagePurpose') != 'FILE'
              or package.get('externalRefs') or not graph[package['SPDXID']]):
            raise Refusal('versioned SPDX package identity required; only described file aggregates may omit version')
    file_ids = {f['SPDXID'] for f in files}
    if not versioned or not any(graph[p['SPDXID']] & file_ids for p in versioned):
        raise Refusal('SPDX must connect versioned packages to file evidence')
    return versioned

def package_identity(kind, name, version):
    if not all(isinstance(v,str) and v and v == v.strip() and v not in {'UNKNOWN','NOASSERTION','NONE'} for v in (name,version)):
        raise Refusal('unambiguous runtime package name/version required')
    if kind == 'pypi':
        if not re.fullmatch('[A-Za-z0-9][A-Za-z0-9._-]*',name):
            raise Refusal('unsupported Python package identity')
        name = re.sub('[-_.]+','-',name).lower()
    return kind,name,version

def purl_identity(value):
    # Do not strip epochs/revisions, infer aliases or collapse ecosystems.
    # Native extension subpaths are not independent installed distributions.
    if not isinstance(value,str) or not value.startswith('pkg:') or re.search('%(?![0-9a-fA-F]{2})',value):
        raise Refusal('supported package URL identity required')
    body, _, subpath = value[4:].partition('#')
    body = body.partition('?')[0]
    path, sep, version = body.rpartition('@')
    if not sep:
        raise Refusal('versioned package URL required for runtime coverage')
    kind, sep, name = path.partition('/')
    name, version = unquote(name),unquote(version)
    if kind in {'deb','apk'}:
        namespace, sep, name = name.partition('/')
        if not sep or namespace != {'deb':'debian','apk':'alpine'}[kind] or '/' in name:
            raise Refusal('unsupported OS package URL namespace')
    elif kind == 'pypi':
        if '/' in name:
            raise Refusal('unsupported Python package URL namespace')
    elif kind == 'npm':
        if '/' in name and not re.fullmatch('@[^/]+/[^/]+',name):
            raise Refusal('unsupported npm package URL namespace')
    else:
        raise Refusal('unsupported runtime package URL ecosystem')
    return package_identity(kind,name,version), bool(subpath)

def reconcile_sbom(report, statement):
    """Every admitted runtime package needs a versioned SPDX distribution identity."""
    packages = spdx_packages(statement.get('predicate',{}))
    identities = set()
    for package in packages:
        refs = package.get('externalRefs',[])
        if not isinstance(refs,list) or any(not isinstance(r,dict) for r in refs):
            raise Refusal('SPDX external package references malformed')
        for ref in refs:
            if ref.get('referenceType') != 'purl':
                continue
            value = ref.get('referenceLocator')
            # Supplementary generic/embedded packages remain valid SPDX, but
            # cannot substitute for the runtime ecosystems admitted by Trivy.
            if not isinstance(value,str):
                raise Refusal('SPDX package URL malformed')
            if value.split('/',1)[0] not in {'pkg:deb','pkg:apk','pkg:pypi','pkg:npm'}:
                continue
            identity, subpath = purl_identity(value)
            if subpath:
                # A bundled component may have its own version while the purl
                # names its parent distribution. It cannot cover that parent.
                continue
            if identity[2] != package['versionInfo']:
                raise Refusal('SPDX package URL/version disagreement')
            if not subpath:
                if identity != package_identity(identity[0],package['name'],package['versionInfo']):
                    raise Refusal('SPDX package URL/name disagreement')
                identities.add(identity)
    kinds = {'debian':'deb','alpine':'apk','python-pkg':'pypi','node-pkg':'npm'}
    scanned = set()
    for result in report['Results']:
        kind = kinds[result['Type']]
        for package in result['Packages']:
            identity = package_identity(kind,package['Name'],package['Version'])
            identifier = package.get('PkgIdentifier',{})
            if not isinstance(identifier,dict):
                raise Refusal('scanner package identifier malformed')
            locator = identifier.get('PURL',package.get('PURL'))
            if locator is not None:
                explicit, subpath = purl_identity(locator)
                if subpath or explicit != identity:
                    raise Refusal('scanner package URL/name/version disagreement')
            if identity not in identities:
                raise Refusal('SPDX omitted admitted runtime package identity/version')
            scanned.add(identity)
    if identities != scanned:
        raise Refusal('scanner omitted SPDX runtime distribution coverage')

def bounded_tar_headers(raw, size):
    """Reject extension/sparse headers before tarfile can allocate their body."""
    offset = count = total = 0
    while offset+512 <= size:
        raw.seek(offset)
        header = raw.read(512)
        if header == bytes(512):
            if raw.read(512) != bytes(512):
                raise Refusal('complete OCI archive terminator required')
            raw.seek(0)
            return
        count += 1
        if count > MAX_MEMBERS:
            raise Refusal('OCI archive member count exceeds bounded inventory')
        try:
            member = tarfile.TarInfo.frombuf(header,'utf-8','strict')
        except (tarfile.HeaderError,UnicodeError,ValueError):
            raise Refusal('invalid OCI tar header') from None
        if member.type not in {tarfile.REGTYPE,tarfile.AREGTYPE,tarfile.DIRTYPE}:
            raise Refusal('OCI archive extension, sparse or linked header refused')
        if member.size < 0 or member.size > MAX_MEMBER_BYTES:
            raise Refusal('OCI member exceeds bounded inventory')
        total += member.size
        if total > MAX_ARCHIVE_BYTES:
            raise Refusal('OCI archive content exceeds bounded inventory')
        offset += 512+((member.size+511)//512)*512
        if offset > size:
            raise Refusal('truncated OCI member refused')
    raise Refusal('complete bounded OCI tar inventory required')


def oci_evidence(archive: Path, expected: str, *, image: str, source: str, builder: str, review=None, writer=None):
    if review is None:
        raise Refusal('independently hash-bound reviewed construction inputs required')
    policy = admit_review(*review,service=image.rsplit('-',1)[1],source=source)
    found = {}
    binding = None
    fd = os.open(archive,os.O_RDONLY|os.O_NOFOLLOW|os.O_CLOEXEC|os.O_NONBLOCK)
    with os.fdopen(fd,'rb') as raw:
        info = os.fstat(raw.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_size > MAX_ARCHIVE_BYTES:
            raise Refusal('bounded sole-link regular OCI archive required')
        bounded_tar_headers(raw,info.st_size)
        return _oci_inventory(raw,info,expected,image,source,builder,review,policy,writer)

def _oci_inventory(raw,info,expected,image,source,builder,review,policy,writer=None):
    found = {}
    binding = None
    used = {'index.json','oci-layout'}
    with tarfile.open(fileobj=raw,mode='r:') as tar:
        members = {}
        total = 0
        last_end = 0
        for member in tar:
            if len(members) >= MAX_MEMBERS:
                raise Refusal('OCI archive member count exceeds bounded inventory')
            name = member.name
            if name in members:
                raise Refusal('duplicate OCI archive entries')
            if member.pax_headers or not (member.isfile() or member.isdir()):
                raise Refusal('OCI archive links or unsupported member metadata refused')
            if member.isdir():
                if name not in {'blobs','blobs/sha256'} or member.size != 0:
                    raise Refusal('extraneous OCI archive directory')
            elif name not in {'index.json','oci-layout'} and not re.fullmatch(r'blobs/sha256/[0-9a-f]{64}',name):
                raise Refusal('extraneous OCI archive member')
            if member.size < 0 or member.size > MAX_MEMBER_BYTES:
                raise Refusal('OCI member exceeds bounded inventory')
            total += member.size
            if total > MAX_ARCHIVE_BYTES:
                raise Refusal('OCI archive content exceeds bounded inventory')
            members[name] = member
            last_end = member.offset_data + ((member.size+511)//512)*512
        # tarfile stops at the first terminator; reject concatenated archives or
        # opaque trailing bytes as well as visible extraneous members.
        raw.seek(last_end)
        while chunk := raw.read(65536):
            if any(chunk):
                raise Refusal('extraneous bytes after OCI archive inventory')
        for name,member in members.items():
            if member.isfile() and name.startswith('blobs/'):
                h = hashlib.sha256()
                stream = tar.extractfile(member)
                while chunk := stream.read(65536):
                    h.update(chunk)
                if h.hexdigest() != name.rsplit('/',1)[1]:
                    raise Refusal('OCI inventory member hash mismatch')
        def read(name):
            if name not in members:
                raise Refusal('OCI inventory metadata missing')
            member = members[name]
            if not member.isfile() or member.size > MAX_METADATA_BYTES:
                raise Refusal('invalid OCI metadata')
            used.add(name)
            return tar.extractfile(member).read(MAX_METADATA_BYTES+1)
        if parse(read('oci-layout')) != {'imageLayoutVersion':'1.0.0'}:
            raise Refusal('supported exact OCI layout metadata required')
        def blob(descriptor):
            d = descriptor['digest']
            if not re.fullmatch('sha256:[0-9a-f]{64}',d):
                raise Refusal('invalid OCI descriptor digest')
            content = read('blobs/sha256/'+d.split(':')[1])
            if 'sha256:'+hashlib.sha256(content).hexdigest()!=d or descriptor.get('size')!=len(content):
                raise Refusal('OCI metadata hash mismatch')
            return content,parse(content)
        index_data = read('index.json')
        index = parse(index_data)
        selected_application = None
        if 'sha256:'+hashlib.sha256(index_data).hexdigest() != expected:
            matches = [m for m in index.get('manifests',[]) if m.get('digest')==expected]
            if len(matches)!=1:
                raise Refusal('OCI build/archive digest mismatch')
            _, selected = blob(matches[0])
            if 'manifests' in selected:
                if len(index.get('manifests',[])) != 1:
                    raise Refusal('OCI transport wrapper contains unpublished/unscanned siblings')
                index = selected
            else:
                selected_application = matches[0]['digest']
        descriptors = index.get('manifests',[])
        if (index.get('schemaVersion') != 2 or not isinstance(descriptors,list) or not descriptors
            or len({d['digest'] for d in descriptors}) != len(descriptors)):
            raise Refusal('unambiguous OCI index inventory required')
        apps = [d for d in descriptors if d.get('annotations',{}).get('vnd.docker.reference.type') != 'attestation-manifest']
        if (len(apps) != 1 or apps[0].get('platform') != {'os':'linux','architecture':'amd64'}
            or apps[0].get('mediaType') != 'application/vnd.oci.image.manifest.v1+json'):
            raise Refusal('closed OCI inventory requires exactly one linux/amd64 runnable member')
        app = apps[0]
        if selected_application is not None and selected_application!=app['digest']:
            raise Refusal('build digest is neither the intended application nor its index')
        _, application = blob(app)
        if (application.get('schemaVersion')!=2 or not application.get('layers')
            or application.get('subject') is not None or application.get('artifactType') is not None
            or application.get('config',{}).get('mediaType') != 'application/vnd.oci.image.config.v1+json'):
            raise Refusal('substantive application manifest required')
        _, config = blob(application['config'])
        runtime = config.get('config')
        if not isinstance(runtime,dict) or not isinstance(runtime.get('Labels'),dict):
            raise Refusal('application runtime configuration required')
        labels = runtime['Labels']
        if (config.get('architecture')!='amd64' or config.get('os')!='linux'
            or labels.get('org.opencontainers.image.source')!='https://github.com/'+REPO
            or labels.get('org.opencontainers.image.revision')!=source):
            raise Refusal('application config source/revision/platform mismatch')
        runtime_user = reviewed_runtime_user(review[2])
        if runtime.get('User') != runtime_user:
            raise Refusal('application runtime UID:GID differs from reviewed Dockerfile')
        rootfs = config.get('rootfs')
        layers = application['layers']
        if (not isinstance(rootfs,dict) or set(rootfs) != {'type','diff_ids'}
            or rootfs['type'] != 'layers' or not isinstance(rootfs['diff_ids'],list)
            or not isinstance(layers,list) or len(layers) > MAX_MEMBERS
            or len(rootfs['diff_ids']) != len(layers)
            or any(not isinstance(d,str) or not re.fullmatch('sha256:[0-9a-f]{64}',d)
                   for d in rootfs['diff_ids'])):
            raise Refusal('ordered rootfs diff-id inventory must match application layer count')
        # Close content identity as well as descriptor inventory. Layers may be
        # large: stream them without the metadata size limit or extraction.
        rootfs_budget = {'bytes':0,'members':0}
        for position,layer in enumerate(layers):
            if not isinstance(layer,dict):
                raise Refusal('application layer descriptor required')
            d = layer.get('digest','')
            if (not isinstance(d,str) or not re.fullmatch('sha256:[0-9a-f]{64}',d)
                or layer.get('mediaType') not in {'application/vnd.oci.image.layer.v1.tar',
                    'application/vnd.oci.image.layer.v1.tar+gzip','application/vnd.oci.image.layer.v1.tar+zstd'}):
                raise Refusal('supported immutable application layer required')
            name = 'blobs/sha256/'+d.split(':')[1]
            used.add(name)
            if name not in members:
                raise Refusal('OCI application layer missing')
            member = members[name]
            if not member.isfile() or member.size != layer.get('size'):
                raise Refusal('application layer size/type mismatch')
            h = hashlib.sha256()
            stream = tar.extractfile(member)
            while chunk := stream.read(65536):
                h.update(chunk)
            if 'sha256:'+h.hexdigest() != d:
                raise Refusal('application layer content mismatch')
            actual_diff_id = layer_diff_id(tar.extractfile(member),layer['mediaType'],rootfs_budget)
            if actual_diff_id != rootfs['diff_ids'][position]:
                raise Refusal('application layer material differs from ordered rootfs diff-id')
        for descriptor in descriptors:
            annotations = descriptor.get('annotations',{})
            if descriptor == app:
                continue
            if (annotations.get('vnd.docker.reference.digest')!=app['digest']
                or descriptor.get('platform')!={'os':'unknown','architecture':'unknown'}):
                raise Refusal('attestation manifest targets a different application')
            if descriptor.get('mediaType') != 'application/vnd.oci.image.manifest.v1+json':
                raise Refusal('supported attestation manifest required')
            _, obj = blob(descriptor)
            if obj.get('schemaVersion') != 2 or not obj.get('layers'):
                raise Refusal('nonempty attestation manifest required')
            if (obj.get('artifactType') not in {None,'application/vnd.docker.attestation.manifest.v1+json'}
                or obj['config'].get('mediaType') not in {'application/vnd.oci.image.config.v1+json',
                                                          'application/vnd.oci.empty.v1+json'}):
                raise Refusal('supported non-runnable attestation configuration required')
            _, att_config = blob(obj['config'])
            if (att_config.get('os') not in {None,'unknown'}
                or att_config.get('architecture') not in {None,'unknown'}
                or att_config.get('rootfs',{}).get('diff_ids',[])):
                raise Refusal('attestation descriptor disguises runnable configuration')
            if obj.get('subject') is not None and any(
                obj['subject'].get(k) != app[k] for k in ('digest','size','mediaType')):
                raise Refusal('OCI artifact subject mismatch')
            for layer in obj.get('layers',[]):
                kind = layer.get('annotations',{}).get('in-toto.io/predicate-type','')
                if kind not in {'https://slsa.dev/provenance/v0.2','https://spdx.dev/Document'}:
                    raise Refusal('unknown or unsupported attestation layer in closed inventory')
                if layer.get('mediaType')!='application/vnd.in-toto+json':
                    raise Refusal('OCI in-toto media type required')
                payload,statement = blob(layer)
                validated = statement_evidence(statement,kind,app['digest'],image,source,builder,policy)
                key = 'sbom' if kind=='https://spdx.dev/Document' else 'provenance'
                if key in found:
                    raise Refusal('ambiguous duplicate OCI evidence')
                found[key] = payload
                if key == 'provenance':
                    binding = validated
        if {name for name,m in members.items() if m.isfile()} != used:
            raise Refusal('unreferenced OCI archive content refused')
        member_inventory = {name:({'type':'file','size':m.size,'sha256':name.rsplit('/',1)[1] if name.startswith('blobs/') else
                            hashlib.sha256(read(name)).hexdigest()} if m.isfile() else
                            {'type':'directory','size':0,'sha256':None}) for name,m in members.items()}
        after = os.fstat(raw.fileno())
        if any(getattr(info,k) != getattr(after,k) for k in
               ('st_dev','st_ino','st_size','st_mtime_ns','st_ctime_ns','st_nlink')):
            raise Refusal('OCI archive changed during admission')
    if set(found) != {'sbom','provenance'}:
        raise Refusal('OCI must include SBOM and provenance')
    if writer is None:
        writer = lambda name, data: (OUT/name).write_bytes(data)
    for key,content in found.items():
        writer(key+'.json',content)
    binding['policy_sha256'] = review[1]
    inventory = {'schema':'rick.vps.oci-inventory/v1','build_digest':expected,
        'runnable':[{'digest':app['digest'],'platform':app['platform'],
                     'config_digest':application['config']['digest']}],
        'attestations':[d['digest'] for d in descriptors if d != app],
        'members':member_inventory}
    writer('construction-binding.json',(json.dumps(binding,sort_keys=True)+'\n').encode())
    writer('oci-inventory.json',(json.dumps(inventory,sort_keys=True)+'\n').encode())
    return app['digest']

def scan_coverage(report, inventory, requirements=None):
    # Trivy must emit package inventories even for clean scans.
    # Empty Results, skipped/unsupported analyses and malformed reports are
    # unknown coverage, never equivalent to no vulnerabilities.
    if (not isinstance(report,dict) or report.get('SchemaVersion') != 2
        or report.get('ArtifactType') != 'container_image' or not report.get('ArtifactName')
        or not isinstance(report.get('Results'),list) or not report['Results']
        or report.get('Metadata',{}).get('ImageID') != inventory['runnable'][0]['config_digest']):
        raise Refusal('substantive scanner report must cover sole admitted runnable config digest')
    system = report.get('Metadata',{}).get('OS',{})
    if system.get('Family') not in {'debian','alpine'} or not isinstance(system.get('Name'),str) or not system['Name']:
        raise Refusal('supported detected runtime OS required for scan coverage')
    if (any(key in system and system[key] is not False for key in ('EOSL','EOL','Unsupported'))
        or ('Supported' in system and system['Supported'] is not True)):
        raise Refusal('end-of-life, unsupported or unknown runtime OS coverage refused')
    if requirements is None:
        requirements = {'os_family':system['Family'],'language_types':[]}
    if system['Family'] != requirements['os_family']:
        raise Refusal('scanner OS differs from independently reviewed runtime coverage')
    covered = set()
    for result in report['Results']:
        if (not isinstance(result,dict) or not isinstance(result.get('Target'),str) or not result['Target']
            or (result.get('Class'),result.get('Type')) not in {
                ('os-pkgs',system['Family']),('lang-pkgs','python-pkg'),('lang-pkgs','node-pkg')}
            or not isinstance(result.get('Packages'),list) or not result['Packages']
            or any(not isinstance(p,dict) or any(not isinstance(p.get(k),str) or not p[k] for k in ('Name','Version'))
                   for p in result['Packages'])):
            raise Refusal('substantive supported OS/application package analysis required')
        covered.add((result['Class'],result['Type']))
        vulnerabilities = result.get('Vulnerabilities')
        if vulnerabilities is None:
            vulnerabilities = []
        if not isinstance(vulnerabilities,list):
            raise Refusal('scanner vulnerability inventory malformed')
        for vulnerability in vulnerabilities:
            if (not isinstance(vulnerability,dict) or not vulnerability.get('VulnerabilityID')
                or not vulnerability.get('PkgName') or vulnerability.get('Severity') not in
                {'LOW','MEDIUM','HIGH','CRITICAL','UNKNOWN'}):
                raise Refusal('scanner vulnerability inventory unsupported')
            if vulnerability['Severity'] in {'HIGH','CRITICAL','UNKNOWN'}:
                raise Refusal('scan report contains blocked or unknown vulnerabilities')
    required = {('os-pkgs',requirements['os_family'])} | {('lang-pkgs',kind) for kind in requirements['language_types']}
    if not required.issubset(covered):
        raise Refusal('scanner omitted reviewed runtime OS/application coverage')
    return {'os_family':system['Family'],'language_types':sorted(kind for cls,kind in covered if cls == 'lang-pkgs')}

@contextmanager
def registry_auth():
    with tempfile.TemporaryDirectory(prefix='registry-auth-') as folder:
        auth = Path(folder)/'auth.json'
        auth.write_text(json.dumps({'auths':{'ghcr.io':{'auth':base64.b64encode(
            (os.environ['GITHUB_ACTOR']+':'+os.environ['GH_TOKEN']).encode()).decode()}}}))
        auth.chmod(0o600)
        yield auth


@contextmanager
def cosign_auth():
    # Host signing authority is trusted, unlike the delegated containers.
    names = ('COSIGN_DOCKER_MEDIA_TYPES', 'DOCKER_CONFIG')
    previous = {name:os.environ.get(name) for name in names}
    try:
        os.environ['COSIGN_DOCKER_MEDIA_TYPES']='1'
        with tempfile.TemporaryDirectory(prefix='cosign-auth-') as folder:
            auth = Path(folder)/'config.json'
            auth.write_text(json.dumps({'auths':{'ghcr.io':{'auth':base64.b64encode(
                (os.environ['GITHUB_ACTOR']+':'+os.environ['GH_TOKEN']).encode()).decode()}}}))
            auth.chmod(0o600)
            os.environ['DOCKER_CONFIG']=folder
            yield
    finally:
        for name,value in previous.items():
            if value is None: os.environ.pop(name,None)
            else: os.environ[name]=value


def main():
    from publication_capture import PublicationCapture
    from construction_contract import BUILD_ARGS
    keys = {'SERVICE','SOURCE_SHA','BUILT_DIGEST','GITHUB_RUN_ID','GITHUB_RUN_ATTEMPT',
        'BUILDX_VERSION','BUILDX_SHA256','CONSTRUCTION_POLICY_JSON','CONSTRUCTION_POLICY_SHA256',
        'TOOL_POLICY_JSON','TOOL_POLICY_SHA256','BUILDKIT_IMAGE','DOCKERFILE_FRONTEND_IMAGE',
        'SBOM_GENERATOR_IMAGE','TRIVY_IMAGE','SKOPEO_IMAGE'} | (BUILD_ARGS-{'BUILDKIT_SYNTAX'})
    try:
        with PublicationCapture({key:os.environ.get(key) for key in keys}) as captured:
            _publish(captured)
    except OSError:
        raise Refusal('publication files unavailable, changed or already exist') from None


def _publish(captured):
    service = os.environ['SERVICE']
    source = os.environ['SOURCE_SHA']
    built = os.environ['BUILT_DIGEST']
    if service not in {'api','worker','web'} or not re.fullmatch('[0-9a-f]{40}',source):
        raise Refusal('invalid candidate identity')
    if not re.fullmatch('sha256:[0-9a-f]{64}',built):
        raise Refusal('captured build digest required')
    image = f'ghcr.io/{REPO}-{service}'
    archive = captured.retain('image.tar', OUT/'image.tar', MAX_ARCHIVE_BYTES).path
    builder = f'https://github.com/{REPO}/actions/runs/'+os.environ['GITHUB_RUN_ID']
    from admission import environment_tools, quality_record
    from construction_contract import canonical_sha256
    tools, tool_identity = environment_tools()
    quality = quality_record(parse(captured.retain('quality.json', OUT/'quality.json', private=True).read()),source)
    review = environment_review(service,source)
    import construction_contract
    dockerfile = captured.retain('reviewed.Dockerfile', construction_contract.ROOT/f'infrastructure/docker/{service}.Dockerfile')
    if dockerfile.read() != review[2]:
        raise Refusal('reviewed Dockerfile changed before publication capture')
    from buildx_binary import inputs
    buildx = parse(captured.retain('buildx.json', OUT/'buildx.json').read())
    url = inputs(os.environ['BUILDX_VERSION'],os.environ['BUILDX_SHA256'])
    if (buildx.get('version')!=os.environ['BUILDX_VERSION'] or buildx.get('sha256')!=os.environ['BUILDX_SHA256']
        or buildx.get('url')!=url or buildx.get('platform')!='linux/amd64'):
        raise Refusal('reviewed Buildx binary construction evidence required')
    def evidence_writer(name, data):
        captured.write(name, data)
        captured.export(name, OUT/name)
    evidence_writer('construction-policy.json', review[0])
    evidence_writer('tool-policy.json', os.environ['TOOL_POLICY_JSON'].encode())
    captured.verify()
    application = oci_evidence(archive,built,image=image,source=source,builder=builder,review=review,writer=evidence_writer)
    captured.verify()
    construction = parse(captured.retained['construction-binding.json'].read())
    inventory = parse(captured.retained['oci-inventory.json'].read())
    scanner = immutable(os.environ['TRIVY_IMAGE'])
    copier = immutable(os.environ['SKOPEO_IMAGE'])
    # Scanner execution/DB failure blocks copy. Emit all severities; admission
    # rejects HIGH/CRITICAL/UNKNOWN while allowing LOW/MEDIUM. No hosted effect
    # occurs before both coverage and SBOM reconciliation succeed.
    def checked_command(argv):
        captured.verify()
        try:
            return command(argv)
        finally:
            # Also check tool failures/returns, before any next effect or signing.
            captured.verify()
    mounts = ['--user',f'{os.geteuid()}:{os.getegid()}',
              '--cap-drop=ALL','--security-opt=no-new-privileges',
              '-v',str(captured.inputs)+':/input:ro','-v',str(captured.outputs)+':/output:rw']
    scan_identity = captured.prepare_output('scan.json')
    checked_command(['docker','run','--rm',*mounts,scanner,'image','--input','/input/image.tar',
        '--cache-dir','/output/trivy-cache','--scanners','vuln','--list-all-pkgs',
        '--exit-code','0','--format','json','--output','/output/scan.json'])
    scan = captured.retain_output('scan.json', scan_identity)
    captured.export('scan.json', OUT/'scan.json')
    report = parse(scan.read())
    scan_coverage(report,inventory,tools['scan'][service])
    reconcile_sbom(report,parse(captured.retained['sbom.json'].read()))
    captured.verify()
    with registry_auth() as auth:
        captured.verify()
        tag = image+':candidate-'+source+'-'+os.environ['GITHUB_RUN_ID']+'-'+os.environ['GITHUB_RUN_ATTEMPT']
        digest_identity = captured.prepare_output('registry.digest')
        checked_command(['docker','run','--rm',*mounts,'-v',str(auth)+':/auth/auth.json:ro',copier,
            'copy','--all','--preserve-digests','--authfile','/auth/auth.json','--digestfile','/output/registry.digest',
            'oci-archive:/input/image.tar','docker://'+tag])
    hosted_input = captured.retain_output('registry.digest', digest_identity)
    captured.export('registry.digest', OUT/'registry.digest')
    hosted = hosted_input.read().decode().strip()
    if hosted != built:
        raise Refusal('hosted digest differs from scanned build; unsigned candidate refused')
    ref = immutable(image+'@'+hosted,image)
    predicate = {'source_sha':source,'image_ref':ref,'promotion_authorized':False,'scan_status':'PASS',
        'application_digest':application,'builder_id':builder,'buildx_binary':buildx,
        'scan_sha256':captured.retained['scan.json'].sha256,'sbom_sha256':captured.retained['sbom.json'].sha256,
        'provenance_sha256':captured.retained['provenance.json'].sha256,'oci_sha256':captured.retained['image.tar'].sha256,
        'quality':quality,'quality_sha256':canonical_sha256(quality),
        'tool_policy_sha256':tool_identity,'scan_requirements':tools['scan'][service],
        'workflow_run':f'https://github.com/{REPO}/actions/runs/'+os.environ['GITHUB_RUN_ID'],
        'construction':construction,'scan_coverage':inventory['runnable'],
        'base_images':{k:construction['parameters']['args']['build-arg:'+k] for k in ('PYTHON_IMAGE','NODE_BUILD_IMAGE','NODE_RUNTIME_IMAGE')},
        'configured_build_tools':{k:os.environ[k] for k in ('BUILDKIT_IMAGE','DOCKERFILE_FRONTEND_IMAGE','SBOM_GENERATOR_IMAGE','TRIVY_IMAGE','SKOPEO_IMAGE')}}
    evidence_writer('predicate.json', (json.dumps(predicate,sort_keys=True)+'\n').encode())
    path = captured.retained['predicate.json'].path
    captured.verify()
    with cosign_auth():
        signature_identity = captured.prepare_output('signature.bundle.json')
        checked_command(['cosign','sign','--yes','--bundle',str(captured.outputs/'signature.bundle.json'),ref])
        captured.retain_output('signature.bundle.json', signature_identity)
        captured.export('signature.bundle.json', OUT/'signature.bundle.json')
        attestation_identity = captured.prepare_output('attestation.bundle.json')
        checked_command(['cosign','attest','--yes','--type',PREDICATE,'--predicate',str(path),
            '--bundle',str(captured.outputs/'attestation.bundle.json'),ref])
        captured.retain_output('attestation.bundle.json', attestation_identity)
        captured.export('attestation.bundle.json', OUT/'attestation.bundle.json')
        common = ['--certificate-identity',IDENTITY,'--certificate-oidc-issuer',ISSUER]
        signature = checked_command(['cosign','verify',*common,ref])
        attestation = checked_command(['cosign','verify-attestation',*common,'--type',PREDICATE,ref])
    evidence_writer('signature-verification.json', signature.encode())
    evidence_writer('attestation-verification.jsonl', attestation.encode())
    fragment = {'service':service,'source_sha':source,'image_ref':ref,'digest':hosted,
        'build_status':'PASS','digest_status':'PASS','context':'.',
        'dockerfile':f'infrastructure/docker/{service}.Dockerfile',
        'scan':{'status':'PASS','tool':'trivy','critical':0,'high':0,'report':f'{service}/scan.json','sbom':f'{service}/sbom.json'},
        'signature':{'status':'PASS','tool':'cosign','bundle':f'{service}/signature.bundle.json',
                     'identity':IDENTITY,'issuer':ISSUER},
        'publication':predicate,'status':'CANDIDATE'}
    captured.verify()
    evidence_writer('candidate.json', (json.dumps(fragment,indent=2,sort_keys=True)+'\n').encode())
    print('hosted candidate digest, signature and attestation verified; promotion not authorized')

if __name__=='__main__':
    try:
        main()
    except Exception:
        print('candidate construction failed; no deployable release admitted',file=sys.stderr)
        raise SystemExit(2)
