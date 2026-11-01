"""Explicit, source-bound removal of one C2PA associated file on a new copy.

This does not verify credentials, execute attachments, or authorize arbitrary
attachment deletion. Ordinary remediation of the credentialed input stays blocked.
"""
from __future__ import annotations
from datetime import datetime
from pathlib import Path
import copy
import hashlib
import json
import re
import shutil
import stat
import uuid
import xml.etree.ElementTree as ET
from urllib.parse import urlsplit
import pikepdf

POLICY = 'bounded-c2pa-associated-file-1'
CONSENT_POLICY = 'remove-content-credentials-1'
LINEAGE_SCHEMA = 'content-credentials-lineage-1'
MAX_PAYLOAD = 16 * 1024**2
FILES = ('original.pdf', 'credential-payload.bin', 'credential-encoded.bin',
         'credential-free.pdf', 'consent.json', 'verification.json')
_SHA = re.compile(r'[a-f0-9]{64}')
_SCOPE = ('A separate working copy has no Content Credentials; the original '
          'credential was not verified and does not apply to this copy.')


class CredentialError(ValueError):
    pass


def _need(value, message):
    if not value: raise CredentialError(message)


def _tick(cancel):
    if cancel is not None and cancel.is_set(): raise InterruptedError('Credential copy cancelled; original preserved.')


def _path(value):
    path = Path(value).absolute()
    for part in (path, *path.parents):
        if part.exists():
            info = part.lstat()
            _need(not stat.S_ISLNK(info.st_mode) and not getattr(info, 'st_file_attributes', 0) & 1024,
                  'Redirected credential evidence paths are unsupported.')
    return path.resolve()


def _sha(path):
    digest = hashlib.sha256()
    with _path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1048576), b''): digest.update(block)
    return digest.hexdigest()


def _digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
        allow_nan=False, separators=(',', ':')).encode('utf-8')).hexdigest()


def _bind(path): return {'path': str(_path(path)), 'sha256': _sha(path)}


def _save(path, value):
    with _path(path).open('x', encoding='utf-8', newline='\n') as stream:
        json.dump(value, stream, indent=2, ensure_ascii=False, allow_nan=False); stream.write('\n')


def _read(path):
    path = _path(path); _need(path.stat().st_size <= 16 * 1024**2, 'Credential evidence JSON exceeds its limit.')
    return json.loads(path.read_text(encoding='utf-8'))


def _consent(value, source_sha256):
    _need(isinstance(value, dict) and set(value) == {'policy', 'source_sha256', 'reviewer', 'reviewed_at', 'allow_remove'}
          and value['policy'] == CONSENT_POLICY and value['source_sha256'] == source_sha256
          and value['allow_remove'] is True, 'Explicit human consent must match the exact credentialed original.')
    for key in ('reviewer', 'reviewed_at'):
        _need(isinstance(value[key], str) and value[key].strip() == value[key] and 0 < len(value[key]) <= 200
              and all(ord(c) >= 32 and not 0xD800 <= ord(c) <= 0xDFFF for c in value[key]), 'A named reviewer and dated consent are required.')
    try: date = datetime.fromisoformat(value['reviewed_at'].replace('Z', '+00:00'))
    except ValueError: raise CredentialError('Consent date must be an ISO date with a timezone.') from None
    _need(date.utcoffset() is not None, 'Consent date must include a timezone.')
    return copy.deepcopy(value)


def has_attachment_signals(pdf, *, cancel=None):
    """Conservative presence only; empty/unknown containers are not waived."""
    queue = [(pdf.Root, 0)] + [(obj, 0) for obj in pdf.objects]; seen = set(); count = 0
    while queue:
        value, depth = queue.pop(); count += 1
        _tick(cancel)
        if count > 1000000 or depth > 200: return True
        try: ident = tuple(value.objgen) if value.is_indirect else None
        except (AttributeError, TypeError, ValueError): ident = None
        if ident:
            if ident in seen: continue
            seen.add(ident); depth = 0
        if isinstance(value, (pikepdf.Dictionary, pikepdf.Stream)):
            if (any(key in value for key in ('/AF', '/EmbeddedFiles', '/Collection'))
                    or value.get('/Type') == pikepdf.Name.EmbeddedFile
                    or value.get('/Type') == pikepdf.Name.Filespec and '/EF' in value
                    or value.get('/Subtype') == pikepdf.Name.FileAttachment): return True
            queue.extend((child, depth+1) for child in value.values())
        elif isinstance(value, pikepdf.Array): queue.extend((child, depth+1) for child in value)
    return False


def _metadata_without_claims(value):
    _need(isinstance(value, pikepdf.Stream) and value.get('/Type') == pikepdf.Name.Metadata
          and value.get('/Subtype') == pikepdf.Name.XML, 'Metadata must be an ordinary explicit Metadata/XML stream.')
    data = value.read_bytes(); _need(len(data) <= 8*1024**2, 'Metadata exceeds the bounded XML scope.')
    try:
        if data.startswith((b'\xff\xfe\x00\x00', b'\x00\x00\xfe\xff')): text = data.decode('utf-32')
        elif data.startswith((b'\xff\xfe', b'\xfe\xff')): text = data.decode('utf-16')
        elif data.startswith(b'<\x00\x00\x00'): text = data.decode('utf-32-le')
        elif data.startswith(b'\x00\x00\x00<'): text = data.decode('utf-32-be')
        elif data.startswith(b'<\x00'): text = data.decode('utf-16-le')
        elif data.startswith(b'\x00<'): text = data.decode('utf-16-be')
        else: text = data.decode('utf-8-sig')
        _need(not any(token in text.casefold() for token in ('<!doctype', '<!entity')),
              'DTD/entity authority is unsupported in credential-removal metadata.')
        root = ET.fromstring(text)
    except (UnicodeError, ET.ParseError, ValueError) as exc:
        if isinstance(exc, CredentialError): raise
        raise CredentialError('Metadata XML could not be independently parsed without external authority.') from None
    fragments = [''.join(root.itertext())]; count = 0
    for element in root.iter():
        count += 1; _need(count <= 100000, 'Metadata XML exceeds its bounded node census.')
        fragments.append(str(element.tag)); fragments.extend(str(k)+str(v) for k,v in element.attrib.items())
    normalized = '\n'.join(fragments).casefold()
    _need(not any(token in normalized for token in ('c2pa', 'contentcredentials', 'content-credentials')),
          'Additional Content Credentials metadata requires a separately proven removal scope.')


def _proof(pdf, cancel=None):
    from . import structure_edits as graph
    from .form_edits import _form_signal_scan
    _tick(cancel)
    _need(not pdf.is_encrypted and '/Perms' not in pdf.Root and float(pdf.pdf_version) < 2,
          'Encrypted, signed or PDF 2.x inputs require separate source handling.')
    _need(not any(key in pdf.Root for key in ('/AcroForm', '/Collection', '/OCProperties', '/OpenAction', '/AA')),
          'Forms, portfolios, layers and document actions remain unsupported for this copy.')
    if '/Metadata' in pdf.Root: _metadata_without_claims(pdf.Root['/Metadata'])
    af = pdf.Root.get('/AF')
    _need(isinstance(af, pikepdf.Array) and len(af) == 1, 'Only one catalog-associated C2PA manifest is supported.')
    spec = af[0]
    _need(isinstance(spec, pikepdf.Dictionary) and graph._id(spec)
          and set(map(str, spec)) <= {'/Type', '/F', '/UF', '/Desc', '/AFRelationship', '/EF'}
          and spec.get('/Type') == pikepdf.Name.Filespec
          and spec.get('/AFRelationship') == pikepdf.Name('/C2PA_Manifest'), 'The sole associated file is not a proven C2PA-labelled Filespec.')
    _need(all(isinstance(spec.get(key), pikepdf.String) for key in ('/F', '/UF')),
          'Both original credential filenames must be ordinary strings.')
    filename = str(spec['/F'])
    _need(filename == str(spec['/UF']) and 0 < len(filename) <= 255 and filename.casefold().endswith('.c2pa')
          and not any(ord(c) < 32 or 0xD800 <= ord(c) <= 0xDFFF or c in '/\\:' for c in filename),
          'The credential filenames are ambiguous or unsupported.')
    _need('/Desc' not in spec or isinstance(spec['/Desc'], pikepdf.String) and len(str(spec['/Desc'])) <= 4000,
          'Credential description has an unsupported representation.')
    ef = spec.get('/EF')
    _need(isinstance(ef, pikepdf.Dictionary) and set(map(str, ef)) == {'/F'}, 'The credential embedded-file map is unsupported.')
    stream = ef['/F']
    _need(isinstance(stream, pikepdf.Stream) and graph._id(stream)
          and set(map(str, stream)) == {'/Type', '/Subtype', '/Length'}
          and stream.get('/Type') == pikepdf.Name.EmbeddedFile
          and stream.get('/Subtype') in (pikepdf.Name('/application/x-c2pa-manifest-store'),
              pikepdf.Name('/application#2Fx-c2pa-manifest-store'))
          and type(stream.get('/Length')) is int and 0 < stream['/Length'] <= MAX_PAYLOAD,
          'Only a bounded unfiltered C2PA manifest-store stream is supported.')
    raw = stream.read_raw_bytes()
    _need(len(raw) == stream['/Length'] and raw == stream.read_bytes(), 'Credential payload length or encoding is inconsistent.')
    scan = _form_signal_scan(pdf)
    _need(scan['complete'] and not scan['active'], 'Control/signature or unproved object signals remain unsupported.')
    for carrier in (af, spec, ef, stream):
        ident = graph._id(carrier)
        _need(not ident or scan['incoming'][ident] == 1, 'A credential carrier is shared or aliased outside the selected association.')
    names = pdf.Root.get('/Names')
    _need(names is None or isinstance(names, pikepdf.Dictionary) and not any(key in names for key in ('/EmbeddedFiles', '/JavaScript')),
          'Additional embedded-file or JavaScript name trees remain unsupported.')
    allowed_actions = set(); allowed_owners = set(); page_ids = {graph._id(page.obj) for page in pdf.pages}
    for page in pdf.pages:
        for annotation in page.obj.get('/Annots', []):
            _need(isinstance(annotation, pikepdf.Dictionary), 'Malformed annotations are unsupported.')
            _need(annotation.get('/Subtype') != pikepdf.Name.FileAttachment, 'A separate file-attachment annotation exists.')
            action = annotation.get('/A')
            if action is None: continue
            _need(annotation.get('/Subtype') == pikepdf.Name.Link and graph._id(annotation) and isinstance(action, pikepdf.Dictionary)
                  and set(map(str, action)) <= {'/Type', '/S', '/URI', '/D', '/IsMap'} and action.get('/Type', pikepdf.Name.Action) == pikepdf.Name.Action,
                  'Only ordinary unchanged Link actions are supported.')
            kind = action.get('/S')
            if kind == pikepdf.Name.URI:
                _need(set(map(str, action)) <= {'/Type', '/S', '/URI', '/IsMap'}
                      and ('/IsMap' not in action or action['/IsMap'] is False)
                      and isinstance(action.get('/URI'), pikepdf.String), 'The Link URI is unsupported.')
                uri = str(action['/URI']); parsed = urlsplit(uri)
                _need(0 < len(uri) <= 8192 and all(ord(c) >= 32 for c in uri)
                      and parsed.scheme.lower() in {'http', 'https', 'mailto'}
                      and (parsed.scheme.lower() == 'mailto' or bool(parsed.netloc)), 'The Link URI scheme or shape is unsupported.')
            elif kind == pikepdf.Name.GoTo:
                dest = action.get('/D')
                _need(set(map(str, action)) <= {'/Type', '/S', '/D'} and isinstance(dest, pikepdf.Array)
                      and len(dest) >= 2 and graph._id(dest[0]) in page_ids
                      and isinstance(dest[1], pikepdf.Name) and str(dest[1]) in {'/Fit', '/FitB', '/FitH', '/FitV', '/FitBH', '/FitBV', '/XYZ', '/FitR'},
                      'Only an existing local page destination is supported.')
            else: raise CredentialError('Scripts, launch, external-document and other action types remain unsupported.')
            allowed_owners.add(graph._id(annotation))
            if graph._id(action): allowed_actions.add(graph._id(action))
    seen = set(); queue = [(pdf.Root, None, None, 0)] + [(obj, None, None, 0) for obj in pdf.objects]
    count = 0
    while queue:
        value, parent, edge, depth = queue.pop(); count += 1
        _tick(cancel)
        _need(count <= 1000000 and depth <= 200, 'Credential object census exceeds its bound.')
        ident = graph._id(value)
        if ident:
            if ident in seen: continue
            seen.add(ident); depth = 0
        if isinstance(value, (pikepdf.Dictionary, pikepdf.Stream)):
            _need(not any(key in value for key in ('/AA', '/JS', '/OpenAction', '/ByteRange', '/XFA', '/Lock', '/SV'))
                  and value.get('/Type') != pikepdf.Name.Sig and value.get('/FT') != pikepdf.Name.Sig,
                  'Scripts, signatures or dynamic authority remain unsupported.')
            if '/A' in value:
                _need(ident in allowed_owners and value.get('/Subtype') == pikepdf.Name.Link,
                      'An unproved action or attribute owner is outside the bounded credential-removal scope.')
            if '/AF' in value: _need(graph._id(value) == graph._id(pdf.Root), 'An additional associated-file array exists.')
            _need('/EmbeddedFiles' not in value and not any('c2pa' in str(key).casefold() for key in value),
                  'Additional attachment containers or Content Credentials claims are unsupported.')
            if '/AFRelationship' in value: _need(ident == graph._id(spec), 'An additional associated-file relationship exists.')
            if '/EF' in value or value.get('/Type') == pikepdf.Name.Filespec:
                _need(ident == graph._id(spec), 'An additional or unrooted file specification exists.')
            if value.get('/Type') == pikepdf.Name.EmbeddedFile:
                _need(ident == graph._id(stream), 'An additional or unrooted embedded payload exists.')
            if value.get('/Subtype') == pikepdf.Name.FileAttachment:
                raise CredentialError('A file-attachment annotation exists outside the catalog association.')
            if value.get('/Type') == pikepdf.Name.Action or str(value.get('/S', '')) in {
                    '/GoTo', '/GoToR', '/GoToE', '/Launch', '/Thread', '/URI', '/Sound', '/Movie', '/Hide', '/Named',
                    '/SubmitForm', '/ResetForm', '/ImportData', '/JavaScript', '/SetOCGState', '/Rendition', '/Trans', '/GoTo3DView'}:
                _need(ident in allowed_actions or edge == '/A' and isinstance(parent, pikepdf.Dictionary)
                      and parent.get('/Subtype') == pikepdf.Name.Link, 'An unselected or unrooted action is unsupported.')
            if isinstance(value, pikepdf.Stream) and value.get('/Type') == pikepdf.Name.Metadata:
                _metadata_without_claims(value)
            queue.extend((child, value, str(key), depth+1) for key, child in value.items())
        elif isinstance(value, pikepdf.Array): queue.extend((child, value, None, depth+1) for child in value)
    snapshot = graph._snapshot(pdf, cancel)
    displayed = {'filespec': graph._id(spec), 'stream': graph._id(stream), 'filename': filename,
        'unicode_filename': str(spec['/UF']), 'relationship': '/C2PA_Manifest',
        'mime_subtype': str(stream['/Subtype']),
        'decoded_sha256': hashlib.sha256(raw).hexdigest(), 'decoded_bytes': len(raw)}
    context = _digest({'snapshot': snapshot, 'file': displayed, 'policy': POLICY})
    return displayed, snapshot, raw, context


def inspect_credentials(pdf, *, cancel=None):
    result = {'policy': POLICY, 'status': 'not-applicable', 'supported': False, 'files': [],
        'context_sha256': None, 'credentials_verified': False, 'limitations': []}
    if '/AF' not in pdf.Root: return result
    result['status'] = 'unsupported'
    try:
        displayed, _, _, context = _proof(pdf, cancel)
        result.update(status='supported', supported=True, files=[displayed], context_sha256=context)
        result['limitations'] = ['The association is labelled C2PA; cryptographic validity was not verified.',
            'Editing requires explicit consent to a separate copy without these credentials; ordinary Fix/OCR remains blocked.']
        if displayed['mime_subtype'] == '/application#2Fx-c2pa-manifest-store':
            result['limitations'].append('This producer used the exact known double-encoded MIME name; its original value is preserved in evidence, not normalized or treated as credential verification.')
    except InterruptedError: raise
    except Exception as exc: result['limitations'] = [str(exc)[:1000]]
    return result


def _verify(source, output, *, cancel=None):
    from . import structure_edits as graph
    from .inspection import compare_fidelity
    with pikepdf.open(source) as pdf:
        displayed, expected, _, context = _proof(pdf, cancel)
        version = (str(pdf.pdf_version), str(pdf.Root.get('/Version', '')))
        expected = copy.deepcopy(expected)
        root = graph._resolve_encoded(expected, expected['root'])
        del root['v']['/AF']; expected = graph._prune(expected)
        expected = graph._canonical(expected)
    with pikepdf.open(output) as pdf:
        _need(not has_attachment_signals(pdf, cancel=cancel), 'The derivative retains an attachment signal.')
        _need((str(pdf.pdf_version), str(pdf.Root.get('/Version', ''))) == version,
              'The credential-free copy changed the original PDF version.')
        actual = graph._canonical(graph._snapshot(pdf, cancel))
    _need(actual == expected, 'The derivative changed objects outside the exact credential-removal projection.')
    fidelity = compare_fidelity(source, output, dpi=96, max_changed_fraction=0.0, pixel_delta=0, cancel=cancel)
    feature_checks = [row for row in fidelity.get('checks', []) if row['id'] == 'special-features-preservation']
    _need(not fidelity.get('error') and len(feature_checks) == 1
          and feature_checks[0]['status'] == 'fail'
          and feature_checks[0]['evidence'] == {'attachments': {'before': True, 'after': False}}
          and all(row['status'] == 'pass' for row in fidelity['checks'] if row['id'] != 'special-features-preservation')
          and fidelity.get('text', {}).get('ordered_status') == 'pass',
          'Exact all-page text, pixels or navigation preservation could not be established.')
    return {'schema_version': 'content-credentials-removal-proof-1', 'status': 'pass-exact-selected-credential-removal',
        'source_sha256': _sha(source), 'output_sha256': _sha(output), 'context_sha256': context,
        'credential': displayed, 'graph_sha256': _digest(actual), 'fidelity': fidelity,
        'pdf_version_preserved': True,
        'authorized_attachment_transition': {'before': True, 'after': False},
        'credential_validity_verified': False, 'accessibility_approved': False, 'AI_calls': 0, 'OCR_calls': 0}


def create_derivative(source, output, evidence_dir, *, consent, cancel=None):
    source, output, directory = _path(source), _path(output), _path(evidence_dir)
    _need(source.is_file() and output != source and not output.exists() and not directory.exists()
          and output.parent.is_dir() and directory.parent.is_dir() and output.suffix.lower() == '.pdf'
          and directory not in output.parents and directory != output, 'Choose a fresh separate PDF and fresh evidence directory.')
    original_hash = _sha(source); accepted = _consent(consent, original_hash)
    with pikepdf.open(source) as pdf: displayed, _, raw, context = _proof(pdf, cancel)
    _tick(cancel)
    # No output/evidence is written before source eligibility and human consent.
    directory.mkdir(); staging = output.with_name('.credential-copy-'+uuid.uuid4().hex+'.pdf')
    original = directory/'original.pdf'; shutil.copyfile(source, original)
    (directory/'credential-payload.bin').write_bytes(raw); (directory/'credential-encoded.bin').write_bytes(raw)
    _save(directory/'consent.json', accepted)
    with pikepdf.open(original) as pdf:
        _need(_proof(pdf, cancel)[3] == context, 'The exact credential context changed before writing.')
        del pdf.Root['/AF']
        with staging.open('xb') as stream: pdf.save(stream, deterministic_id=True, fix_metadata_version=False)
    proof = _verify(original, staging, cancel=cancel)
    _need(_sha(source) == original_hash and _sha(original) == original_hash, 'The credentialed original changed during copying.')
    _tick(cancel)
    retained = directory/'credential-free.pdf'; shutil.copyfile(staging, retained)
    _save(directory/'verification.json', proof)
    value = {'schema_version': LINEAGE_SCHEMA, 'policy': CONSENT_POLICY,
        'status': 'credentials-removed-original-not-verified', 'source_name': source.name,
        'original': _bind(original), 'current_source': _bind(retained),
        'payload': _bind(directory/'credential-payload.bin'), 'encoded_payload': _bind(directory/'credential-encoded.bin'),
        'consent': _bind(directory/'consent.json'), 'verification': _bind(directory/'verification.json'),
        'context_sha256': context, 'credential': displayed, 'credential_validity_verified': False,
        'accessibility_approved': False, 'AI_calls': 0, 'OCR_calls': 0, 'required_review': True}
    value['binding_sha256'] = _digest(value)
    lineage = directory/'credential-lineage.json'; _save(lineage, value)
    # Exclusive publication: never replace a concurrently created destination.
    with staging.open('rb') as incoming, output.open('xb') as outgoing: shutil.copyfileobj(incoming, outgoing)
    _need(_sha(output) == value['current_source']['sha256'], 'Credential-free publication copy differs.')
    return {'source_path': str(output), 'source_sha256': _sha(output), 'lineage_path': str(lineage),
        'lineage_sha256': _sha(lineage), 'policy': CONSENT_POLICY, 'status': value['status']}


def validate_lineage_bindings(lineage_path, source_path, expected_sha256=None, cancel=None):
    path, source = _path(lineage_path), _path(source_path); digest = _sha(path)
    _need(expected_sha256 is None or expected_sha256 == digest, 'Credential lineage changed.')
    value = _read(path)
    keys = {'schema_version', 'policy', 'status', 'source_name', 'original', 'current_source', 'payload', 'encoded_payload',
        'consent', 'verification', 'context_sha256', 'credential', 'credential_validity_verified', 'accessibility_approved',
        'AI_calls', 'OCR_calls', 'required_review', 'binding_sha256'}
    _need(isinstance(value, dict) and set(value) == keys and value['schema_version'] == LINEAGE_SCHEMA
          and value['policy'] == CONSENT_POLICY and value['status'] == 'credentials-removed-original-not-verified'
          and value['binding_sha256'] == _digest({k:v for k,v in value.items() if k != 'binding_sha256'})
          and value['credential_validity_verified'] is value['accessibility_approved'] is False
          and type(value['AI_calls']) is type(value['OCR_calls']) is int
          and value['AI_calls'] == value['OCR_calls'] == 0 and value['required_review'] is True,
          'Unknown or altered credential lineage.')
    _need(isinstance(value['source_name'], str) and 0 < len(value['source_name']) <= 255
          and all(ord(c) >= 32 and not 0xD800 <= ord(c) <= 0xDFFF for c in value['source_name'])
          and isinstance(value['credential'], dict), 'Credential ancestry summary is malformed.')
    _need(path.name == 'credential-lineage.json', 'Credential lineage must use its fixed inert evidence filename.')
    evidence_root = _path(value['original']['path']).parent
    expected_names = dict(zip(('original', 'payload', 'encoded_payload', 'current_source', 'consent', 'verification'), FILES))
    watched = {}
    for key, name in expected_names.items():
        _tick(cancel); row = value[key]
        _need(isinstance(row, dict) and set(row) == {'path', 'sha256'} and isinstance(row['path'], str)
              and isinstance(row['sha256'], str) and _SHA.fullmatch(row['sha256'])
              and _path(row['path']) == evidence_root/name and _sha(row['path']) == row['sha256'],
              'A retained credential dependency is missing, moved or changed.')
        watched[row['path']] = row['sha256']
    _need(_sha(source) == value['current_source']['sha256'],
          'Credential ancestry requires the exact separate source; OCR-editor chaining is not yet supported.')
    consent = _consent(_read(value['consent']['path']), value['original']['sha256'])
    proof = _read(value['verification']['path'])
    _need(proof.get('schema_version') == 'content-credentials-removal-proof-1'
          and proof.get('status') == 'pass-exact-selected-credential-removal'
          and proof.get('source_sha256') == value['original']['sha256'] and proof.get('output_sha256') == value['current_source']['sha256']
          and proof.get('context_sha256') == value['context_sha256'] and proof.get('credential') == value['credential']
          and value['payload']['sha256'] == value['encoded_payload']['sha256'] == value['credential']['decoded_sha256'],
          'Credential proof dependencies do not agree.')
    _need(_sha(path) == digest and all(_sha(file) == sha for file, sha in watched.items()), 'Credential evidence changed during checking.')
    return {'binding_verified': True, 'policy': CONSENT_POLICY, 'summary': {
        'status': value['status'], 'original': {'name': value['source_name'], 'sha256': value['original']['sha256']},
        'source_sha256': value['current_source']['sha256'], 'credential_filename': value['credential']['filename'],
        'reviewer': consent['reviewer'], 'reviewed_at': consent['reviewed_at'], 'scope': _SCOPE}}


def validate_lineage(lineage_path, source_path, expected_sha256=None, cancel=None):
    result = validate_lineage_bindings(lineage_path, source_path, expected_sha256, cancel)
    value = _read(lineage_path)
    proof = _verify(value['original']['path'], value['current_source']['path'], cancel=cancel)
    _need(proof == _read(value['verification']['path']), 'Independent credential-removal proof changed on replay.')
    validate_lineage_bindings(lineage_path, source_path, expected_sha256, cancel)
    return result


def retain_lineage(binding, staging, source, cancel=None):
    result = validate_lineage_bindings(binding['path'], source, binding['sha256'], cancel)
    origin = _path(binding['path']); directory = Path(staging)/'credential-lineage'; directory.mkdir()
    value = _read(origin)
    expected = {Path(value[key]['path']).name: value[key]['sha256']
        for key in ('original', 'payload', 'encoded_payload', 'current_source', 'consent', 'verification')}
    expected['credential-lineage.json'] = binding['sha256']
    # Preserve JSON byte-for-byte, outside generic evidence path rewriting.
    for name in (*FILES, 'credential-lineage.json'):
        _tick(cancel); incoming = origin.parent/name; outgoing = directory/name
        _need(_sha(incoming) == expected[name], 'Local retained credential evidence changed.')
        shutil.copyfile(incoming, outgoing); _need(_sha(incoming) == _sha(outgoing) == expected[name], 'Credential evidence retention differs.')
    return {'path': str(directory/'credential-lineage.json'), 'sha256': binding['sha256']}, result['summary']
