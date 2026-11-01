"""Source-bound credential detachment; no cryptographic or human approval claim."""
from pathlib import Path
import copy
import hashlib
import json
import threading
import pikepdf
import pytest
from pdf_remediator import credentials, inspection


def credential_source(directory, *, hazard=None):
    directory = Path(directory); directory.mkdir(parents=True, exist_ok=True)
    path = directory/'source.pdf'
    with pikepdf.Pdf.new() as pdf:
        page = pdf.add_blank_page(page_size=(300, 400))
        page.obj['/Contents'] = pikepdf.Stream(pdf, b'0 0 0 rg 20 20 60 30 re f\n')
        payload = pikepdf.Stream(pdf, b'\x00\x00\x00\x20jumbsynthetic-unverified-c2pa-payload')
        payload['/Type'] = pikepdf.Name.EmbeddedFile
        payload['/Subtype'] = pikepdf.Name('/application/x-c2pa-manifest-store')
        if hazard == 'producer-mime': payload['/Subtype'] = pikepdf.Name('/application#2Fx-c2pa-manifest-store')
        spec = pdf.make_indirect(pikepdf.Dictionary(Type=pikepdf.Name.Filespec,
            F=pikepdf.String('CAI_Attachment_File.c2pa'), UF=pikepdf.String('CAI_Attachment_File.c2pa'),
            Desc=pikepdf.String('C2PA Manifest'), AFRelationship=pikepdf.Name('/C2PA_Manifest'),
            EF=pikepdf.Dictionary(F=payload)))
        pdf.Root['/AF'] = pikepdf.Array([spec])
        action = pikepdf.Dictionary(S=pikepdf.Name.URI, URI=pikepdf.String('https://example.org/reference'))
        if hazard == 'uri-map-false': action['/IsMap'] = False
        elif hazard == 'uri-map-true': action['/IsMap'] = True
        elif hazard == 'uri-map-integer': action['/IsMap'] = 0
        annotation = pdf.make_indirect(pikepdf.Dictionary(Type=pikepdf.Name.Annot, Subtype=pikepdf.Name.Link,
            Rect=pikepdf.Array([20,20,80,50]), A=action))
        page.obj['/Annots'] = pikepdf.Array([annotation])
        if hazard == 'ordinary': spec['/AFRelationship'] = pikepdf.Name.Data
        elif hazard == 'alias': pdf.Root['/OtherPayload'] = payload
        elif hazard == 'second-af': pdf.Root['/AF'].append(spec)
        elif hazard == 'page-af': page.obj['/AF'] = pikepdf.Array([spec])
        elif hazard == 'name-tree': pdf.Root['/Names'] = pikepdf.Dictionary(EmbeddedFiles=pikepdf.Dictionary(Names=pikepdf.Array([])))
        elif hazard == 'file-annotation': annotation['/Subtype'] = pikepdf.Name.FileAttachment
        elif hazard == 'signature': pdf.Root['/Perms'] = pikepdf.Dictionary()
        elif hazard == 'portfolio': pdf.Root['/Collection'] = pikepdf.Dictionary()
        elif hazard == 'action': action['/S'] = pikepdf.Name.Launch
        elif hazard == 'unknown-page-action': page.obj['/A'] = pikepdf.Dictionary(S=pikepdf.Name('/UnrecognizedAction'))
        elif hazard == 'unknown-annotation-action':
            page.obj['/Annots'].append(pdf.make_indirect(pikepdf.Dictionary(Subtype=pikepdf.Name.Text,
                Rect=pikepdf.Array([90,20,120,50]),A=pikepdf.Dictionary(S=pikepdf.Name('/UnrecognizedAction')))))
        elif hazard == 'unproved-attribute-owner': pdf.Root['/A'] = pikepdf.Dictionary(O=pikepdf.Name.Layout)
        elif hazard == 'empty': pdf.Root['/AF'] = pikepdf.Array([])
        elif hazard == 'wrong-subtype': payload['/Subtype'] = pikepdf.Name('/application/octet-stream')
        elif hazard in {'metadata-claim','metadata-clean','metadata-utf16-clean','metadata-utf16-claim',
                'metadata-entity-claim','metadata-dtd','metadata-malformed','metadata-missing-type','metadata-utf16-dtd'}:
            documents = {'metadata-claim':'<metadata>c2pa:manifest</metadata>',
                'metadata-clean':'<metadata xmlns:d="urn:ordinary"><d:title>Original title</d:title></metadata>',
                'metadata-utf16-clean':'<metadata>Original title</metadata>',
                'metadata-utf16-claim':'<metadata>c2pa:manifest</metadata>',
                'metadata-entity-claim':'<metadata xmlns:cc="urn:c&#50;pa:claim"><cc:manifest>retained claim</cc:manifest></metadata>',
                'metadata-dtd':'<!DOCTYPE metadata [<!ENTITY old "ordinary">]><metadata>&old;</metadata>',
                'metadata-utf16-dtd':'<!DOCTYPE metadata [<!ENTITY old "ordinary">]><metadata>&old;</metadata>',
                'metadata-malformed':'<metadata>broken', 'metadata-missing-type':'<metadata>ordinary</metadata>'}
            metadata = pikepdf.Stream(pdf, documents[hazard].encode('utf-16' if 'utf16' in hazard else 'utf-8'))
            if hazard != 'metadata-missing-type': metadata['/Type'] = pikepdf.Name.Metadata
            metadata['/Subtype'] = pikepdf.Name.XML; pdf.Root['/Metadata'] = metadata
        elif hazard == 'second-payload':
            extra = pikepdf.Stream(pdf, b'preserve this other file'); extra['/Type'] = pikepdf.Name.EmbeddedFile
            pdf.Root['/OtherEmbeddedFile'] = extra
        elif hazard == 'missing-filename': del spec['/UF']
        elif hazard == 'path-filename': spec['/F'] = spec['/UF'] = pikepdf.String('../credential.c2pa')
        elif hazard not in (None, 'filtered', 'producer-mime', 'uri-map-false', 'uri-map-true', 'uri-map-integer'): raise ValueError(hazard)
        pdf.save(path, compress_streams=hazard == 'filtered', fix_metadata_version=False)
    return path


def consent_for(path):
    return {'policy': credentials.CONSENT_POLICY, 'source_sha256': hashlib.sha256(Path(path).read_bytes()).hexdigest(),
        'reviewer': 'Synthetic explicit-consent reviewer', 'reviewed_at': '2026-10-28T12:00:00+00:00', 'allow_remove': True}


def create(source, directory):
    return credentials.create_derivative(source, directory/'new-source.pdf', directory/'private-evidence', consent=consent_for(source))


def test_explicit_copy_preserves_original_and_all_nonselected_objects(tmp_path):
    source = credential_source(tmp_path/'input'); before = source.read_bytes()
    with pikepdf.open(source) as pdf:
        assessment = credentials.inspect_credentials(pdf)
    assert assessment['supported'] and assessment['credentials_verified'] is False
    assert inspection.inspect_pdf(source)['features']['attachments'] is True
    receipt = create(source, tmp_path)
    assert source.read_bytes() == before and Path(receipt['source_path']).read_bytes() != before
    with pikepdf.open(receipt['source_path']) as pdf:
        assert '/AF' not in pdf.Root and not credentials.has_attachment_signals(pdf)
        assert str(pdf.pages[0].obj['/Annots'][0]['/A']['/URI']) == 'https://example.org/reference'
    assert credentials.validate_lineage(receipt['lineage_path'], receipt['source_path'], receipt['lineage_sha256'])['binding_verified']
    value = json.loads(Path(receipt['lineage_path']).read_text(encoding='utf-8'))
    assert value['accessibility_approved'] is value['credential_validity_verified'] is False
    assert Path(value['original']['path']).read_bytes() == before
    assert Path(value['payload']['path']).read_bytes() == Path(value['encoded_payload']['path']).read_bytes()
    copy_path = tmp_path/'app-upload.pdf'; copy_path.write_bytes(Path(receipt['source_path']).read_bytes())
    assert credentials.validate_lineage_bindings(receipt['lineage_path'], copy_path, receipt['lineage_sha256'])['binding_verified']


@pytest.mark.parametrize('hazard', ['ordinary','alias','second-af','page-af','name-tree','file-annotation',
    'signature','portfolio','action','empty','wrong-subtype','metadata-claim','second-payload','missing-filename','path-filename','filtered','uri-map-true','uri-map-integer',
    'metadata-utf16-claim','metadata-entity-claim','metadata-dtd','metadata-malformed','metadata-missing-type','metadata-utf16-dtd',
    'unknown-page-action','unknown-annotation-action','unproved-attribute-owner'])
def test_unsupported_attachment_shapes_refuse_before_publication(tmp_path, hazard):
    source = credential_source(tmp_path/'input', hazard=hazard); before = source.read_bytes()
    with pytest.raises(credentials.CredentialError): create(source, tmp_path)
    assert source.read_bytes() == before and not (tmp_path/'new-source.pdf').exists() and not (tmp_path/'private-evidence').exists()


@pytest.mark.parametrize('field,bad', [('allow_remove',False),('allow_remove',1),('reviewer',''),('reviewer',' AI\n'),
    ('reviewed_at','2026-10-28'),('source_sha256','0'*64),('policy','automatic')])
def test_consent_must_be_explicit_named_dated_and_source_bound(tmp_path, field, bad):
    source = credential_source(tmp_path/'input'); consent = consent_for(source); consent[field] = bad
    with pytest.raises(credentials.CredentialError):
        credentials.create_derivative(source,tmp_path/'copy.pdf',tmp_path/'evidence',consent=consent)
    assert not (tmp_path/'copy.pdf').exists() and not (tmp_path/'evidence').exists()


@pytest.mark.parametrize('key', ['original','payload','encoded_payload','current_source','consent','verification'])
def test_saved_lineage_depends_on_every_retained_evidence_file(tmp_path, key):
    source = credential_source(tmp_path/'input'); receipt = create(source,tmp_path)
    value = json.loads(Path(receipt['lineage_path']).read_text(encoding='utf-8')); target = Path(value[key]['path'])
    target.write_bytes(target.read_bytes()+b'changed')
    with pytest.raises((credentials.CredentialError,ValueError)):
        credentials.validate_lineage_bindings(receipt['lineage_path'],receipt['source_path'],receipt['lineage_sha256'])


def test_changed_source_and_changed_lineage_cannot_gain_old_consent(tmp_path):
    source = credential_source(tmp_path/'input'); receipt = create(source,tmp_path)
    other = tmp_path/'other.pdf'; other.write_bytes(source.read_bytes())
    with pytest.raises(credentials.CredentialError): credentials.validate_lineage_bindings(receipt['lineage_path'],other,receipt['lineage_sha256'])
    Path(receipt['lineage_path']).write_text('{}',encoding='utf-8')
    with pytest.raises(credentials.CredentialError): credentials.validate_lineage_bindings(receipt['lineage_path'],receipt['source_path'],receipt['lineage_sha256'])


def test_pre_cancelled_copy_writes_nothing(tmp_path):
    source = credential_source(tmp_path/'input'); stop = threading.Event(); stop.set()
    with pytest.raises(InterruptedError):
        credentials.create_derivative(source,tmp_path/'copy.pdf',tmp_path/'evidence',consent=consent_for(source),cancel=stop)
    assert not (tmp_path/'copy.pdf').exists() and not (tmp_path/'evidence').exists()


def test_retained_bundle_lineage_remains_bound_and_hash_exact(tmp_path):
    source = credential_source(tmp_path/'input'); receipt = create(source,tmp_path)
    bundle = tmp_path/'bundle'; bundle.mkdir()
    binding, summary = credentials.retain_lineage({'path':receipt['lineage_path'],'sha256':receipt['lineage_sha256']},bundle,receipt['source_path'])
    assert summary['status'] == 'credentials-removed-original-not-verified'
    assert credentials.validate_lineage_bindings(binding['path'],receipt['source_path'],binding['sha256'])['binding_verified']
    assert {p.name for p in (bundle/'credential-lineage').iterdir()} == set(credentials.FILES)|{'credential-lineage.json'}


def test_actual_producer_double_encoded_mime_is_bound_without_normalization(tmp_path):
    source = credential_source(tmp_path/'input', hazard='producer-mime')
    with pikepdf.open(source) as pdf:
        assessment = credentials.inspect_credentials(pdf)
        assert assessment['supported'] is True
        assert assessment['files'][0]['mime_subtype'] == '/application#2Fx-c2pa-manifest-store'
        assert pdf.Root['/AF'][0]['/EF']['/F']['/Subtype'].unparse() == b'/application#232Fx-c2pa-manifest-store'
    receipt = create(source,tmp_path)
    value = json.loads(Path(receipt['lineage_path']).read_text(encoding='utf-8'))
    assert value['credential']['mime_subtype'] == '/application#2Fx-c2pa-manifest-store'
    assert credentials.validate_lineage(receipt['lineage_path'],receipt['source_path'],receipt['lineage_sha256'])['binding_verified']


def test_actual_uri_ismap_false_remains_exact_and_is_never_executed(tmp_path):
    source = credential_source(tmp_path/'input',hazard='uri-map-false'); receipt = create(source,tmp_path)
    with pikepdf.open(receipt['source_path']) as pdf:
        assert pdf.pages[0].obj['/Annots'][0]['/A']['/IsMap'] is False
    assert credentials.validate_lineage(receipt['lineage_path'],receipt['source_path'],receipt['lineage_sha256'])['binding_verified']


@pytest.mark.parametrize('hazard',['metadata-clean','metadata-utf16-clean'])
def test_parsed_ordinary_xmp_is_preserved_without_rewriting(tmp_path,hazard):
    source = credential_source(tmp_path/'input',hazard=hazard)
    with pikepdf.open(source) as pdf: raw = pdf.Root['/Metadata'].read_bytes()
    receipt = create(source,tmp_path)
    with pikepdf.open(receipt['source_path']) as pdf: assert pdf.Root['/Metadata'].read_bytes() == raw
    assert credentials.validate_lineage(receipt['lineage_path'],receipt['source_path'],receipt['lineage_sha256'])['binding_verified']
