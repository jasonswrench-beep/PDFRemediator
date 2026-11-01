"""Correction resources participate in the normal preparation/cache identity."""
from pdf_remediator import pipeline
from pdf_remediator.config import RuntimeConfig


def test_changing_editor_font_invalidates_preparation_identity(tmp_path, monkeypatch):
    package = tmp_path / 'authored-package'
    data = package / 'data'
    data.mkdir(parents=True)
    module = package / 'pipeline.py'
    module.write_text('# Authored fingerprint fixture; not executable product code.\n')
    font = data / 'NotoSans-Regular.ttf'
    original = b'Authored font-identity fixture; no real font is parsed.'
    font.write_bytes(original)
    monkeypatch.setattr(pipeline, '__file__', str(module))
    config = RuntimeConfig()
    before = pipeline.implementation_digest(config)
    font.write_bytes(original + b' Different font bytes.')
    assert pipeline.implementation_digest(config) != before
    font.write_bytes(original)
    assert pipeline.implementation_digest(config) == before
