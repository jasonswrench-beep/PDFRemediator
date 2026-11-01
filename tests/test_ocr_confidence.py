"""How surely each scanned page was read: word-confidence counts, the fixed hook, the OCR step and the review item.

Tesseract's confidence is a mechanical guide to where misread words are likely. These tests check the counting, the grades, that
bad or unbound numbers are set aside without stopping the reading, that the hook only observes, and that the review names the
right pages. Real OCR is not run: the OCR child process is an explicit stub that writes the numbers the hook would write.
"""
import importlib.util
import json
import shutil
import sys
import types
from pathlib import Path

import pikepdf
import pytest
from PIL import Image

from pdf_remediator import ocr
from pdf_remediator import ocr_confidence as oc
from pdf_remediator import ocr_turns as turns

from test_designed_pdf import tagged_pdf
from test_designed_pdf_pipeline import process
from test_pipeline import fast_validator  # noqa: F401  (fixture)

SOURCE = 'a' * 64
BINDING = {'plugin_sha256': 'b' * 64, 'algorithm_sha256': 'c' * 64}


def hocr(*words):
    body = ''.join("<span class='ocrx_word' id='word_1_%d' title='bbox 1 2 3 4; x_wconf %s'>%s</span>" % (i, conf, text) for i, (conf, text) in enumerate(words))
    return "<div class='ocr_page'><span class='ocr_line' title='bbox 1 2 3 4'>%s</span></div>" % body


def tsv(*rows):
    head = 'level\tpage_num\tblock_num\tpar_num\tline_num\tword_num\tleft\ttop\twidth\theight\tconf\ttext'
    return '\n'.join([head] + ['%s\t1\t1\t1\t1\t1\t10\t10\t50\t20\t%s\t%s' % (level, conf, text) for level, conf, text in rows])


def reading(words, sure, mean=None):
    return {'words': words, 'sure_words': sure, 'mean_confidence': mean}


# --- counting ----------------------------------------------------------------------------------------------------

def test_hocr_words_give_each_words_text_and_confidence():
    page = hocr((96, 'Accessible'), (59, 'maybe'), (80, '<strong>Bold</strong>'), (75, 'caf&#233;'))
    assert oc.hocr_words(page) == [('Accessible', 96.0), ('maybe', 59.0), ('Bold', 80.0), ('café', 75.0)]
    assert oc.hocr_words('') == []
    assert oc.hocr_words("<span class='ocr_line' title='x_wconf 99'>line</span>") == [], 'Only words count, not lines.'
    assert oc.hocr_words("<span class='ocrx_word' title='bbox 1 2 3 4'>no confidence</span>") == []


def test_tsv_words_use_only_word_rows_with_a_real_confidence():
    page = tsv((1, -1, ''), (4, 90, 'whole line of words'), (3, 88, 'paragraph'), (5, 96.4, 'Hello'), (5, -1, 'ghost'), (5, 'abc', 'bad'), (5, 0, 'zero'))
    assert oc.tsv_words(page) == [('Hello', 96.4), ('zero', 0.0)]
    assert oc.tsv_words('') == [] and oc.tsv_words('level\tonly') == []
    assert oc.tsv_words('header\n5\tshort\trow') == []


def test_only_words_of_three_letters_count_and_eighty_is_sure():
    words = [('Accessible', 96), ('to', 99), ('12', 99), ('maybe', 79.9), ('Edge', 80), ('café', 40), ('a1b', 90), ('The', 85)]
    assert oc.measure(words) == {'words': 5, 'sure_words': 3, 'mean_confidence': 76.2}
    assert oc.measure([]) == {'words': 0, 'sure_words': 0, 'mean_confidence': None}
    assert oc.measure([('to', 90), ('1999', 90)])['words'] == 0


@pytest.mark.parametrize('words, sure, expected', [
    (0, 0, 'no-words'), (7, 7, 'little-text'), (1, 0, 'little-text'), (8, 8, 'confident'), (8, 0, 'poor'),
    (100, 59, 'poor'), (100, 60, 'check'), (100, 89, 'check'), (100, 90, 'confident'), (100, 100, 'confident'), (20, 18, 'confident'), (20, 17, 'check'),
])
def test_grades_change_exactly_at_the_stated_thresholds(words, sure, expected):
    assert oc.grade(reading(words, sure)) == expected


# --- the numbers the hook leaves ---------------------------------------------------------------------------------

def proof(page=1, **changes):
    value = {'schema': oc.SCHEMA, 'version': oc.VERSION, 'page': page, 'adapter_source_sha256': SOURCE, **BINDING,
             'reading': {'words': 100, 'sure_words': 90, 'mean_confidence': 88.0}}
    value.update(changes)
    return value


def put(folder, value, name=None):
    folder.mkdir(exist_ok=True)
    (folder / (name or '%06d.json' % value['page'])).write_text(value if isinstance(value, str) else json.dumps(value), encoding='utf-8')


def checked(folder, required=(1, 2), count=3):
    return oc.validate_pages(folder, list(required), BINDING, SOURCE, count)


def test_bound_numbers_are_accepted_and_only_required_pages_are_returned(tmp_path):
    put(tmp_path / 'ev', proof(1))
    put(tmp_path / 'ev', proof(2, reading={'words': 10, 'sure_words': 3, 'mean_confidence': None}))
    put(tmp_path / 'ev', proof(3))
    result = checked(tmp_path / 'ev')
    assert result['problems'] == []
    assert [(p['page'], p['reading']['words']) for p in result['pages']] == [(1, 100), (2, 10)]


@pytest.mark.parametrize('name, change', [
    ('schema', {'schema': 'other'}), ('version', {'version': 'local-reading-confidence-0'}), ('source', {'adapter_source_sha256': 'f' * 64}),
    ('plugin', {'plugin_sha256': 'd' * 64}), ('algorithm', {'algorithm_sha256': 'd' * 64}), ('page-outside-document', {'page': 9}),
    ('more-sure-than-words', {'reading': {'words': 5, 'sure_words': 6, 'mean_confidence': 50}}),
    ('negative', {'reading': {'words': -1, 'sure_words': 0, 'mean_confidence': 50}}),
    ('text-count', {'reading': {'words': '100', 'sure_words': 90, 'mean_confidence': 88}}),
    ('boolean-count', {'reading': {'words': True, 'sure_words': 1, 'mean_confidence': 88}}),
    ('confidence-over-100', {'reading': {'words': 100, 'sure_words': 90, 'mean_confidence': 101}}),
    ('no-reading', {'reading': None}), ('page-not-a-number', {'page': '2'}),
])
def test_unbound_or_impossible_numbers_are_set_aside_and_named_while_good_pages_survive(tmp_path, name, change):
    put(tmp_path / 'ev', proof(2))
    bad = {**proof(1), **change}
    put(tmp_path / 'ev', bad, name='000001.json')
    result = checked(tmp_path / 'ev')
    assert [p['page'] for p in result['pages']] == [2], name
    assert len(result['problems']) == 1 and result['problems'][0].startswith('000001.json'), name


def test_numbers_for_a_page_the_document_does_not_have_are_named_as_a_problem(tmp_path):
    put(tmp_path / 'ev', proof(2))
    put(tmp_path / 'ev', proof(9))
    result = checked(tmp_path / 'ev')
    assert [p['page'] for p in result['pages']] == [2]
    assert len(result['problems']) == 1 and result['problems'][0].startswith('000009.json')


def test_wrong_file_names_malformed_or_oversized_files_never_raise(tmp_path):
    folder = tmp_path / 'ev'
    put(folder, proof(2))
    put(folder, proof(1), name='000002-copy.json')
    put(folder, proof(1), name='1.json')
    put(folder, '{not json', name='000003.json')
    put(folder, '[]', name='000004.json')
    put(folder, json.dumps(proof(1)) + ' ' * (oc.MAX_EVIDENCE_BYTES + 1), name='000001.json')
    result = checked(folder)
    assert [p['page'] for p in result['pages']] == [2]
    assert len(result['problems']) == 5
    assert oc.validate_pages(tmp_path / 'nothing-here', [1], BINDING, SOURCE, 3) == {'pages': [], 'problems': []}


# --- summary and the review item ----------------------------------------------------------------------------------

def summary_of(readings, required=None, layout='standard'):
    measured = [{'page': page, 'reading': value} for page, value in readings.items()]
    return oc.summarise(measured, required if required is not None else list(readings), layout)


MIXED = {1: reading(200, 195), 2: reading(200, 60), 3: reading(200, 150), 4: reading(5, 5), 5: reading(0, 0)}


def test_the_summary_orders_the_pages_to_look_at_worst_first_and_names_unmeasured_ones():
    summary = summary_of(MIXED, required=[1, 2, 3, 4, 5, 6])
    assert summary['status'] == 'partial' and summary['not_measured_pages'] == [6]
    assert summary['flagged_pages'] == [5, 4, 2, 3]
    assert {row['page']: row['grade'] for row in summary['pages']} == {1: 'confident', 2: 'poor', 3: 'check', 4: 'little-text', 5: 'no-words'}
    assert next(row for row in summary['pages'] if row['page'] == 2)['share_sure'] == 0.3
    assert summary['rule']['sure_at_least'] == oc.SURE and 'never a check' in summary['scope']
    json.dumps(summary, allow_nan=False)


def test_the_summary_says_when_everything_or_nothing_was_measured():
    assert summary_of({1: reading(50, 50), 2: reading(50, 49)})['status'] == 'measured'
    nothing = oc.summarise([], [1, 2], 'standard')
    assert nothing['status'] == 'unavailable' and nothing['not_measured_pages'] == [1, 2] and nothing['pages'] == []
    assert oc.summarise([], [], 'standard')['not_measured_pages'] == []


def test_pages_in_order_of_the_poorest_share_first_within_a_grade():
    summary = summary_of({1: reading(100, 50), 2: reading(100, 10), 3: reading(100, 30)})
    assert summary['flagged_pages'] == [2, 3, 1]


def test_no_item_when_every_page_was_read_with_confidence_or_when_not_measured_by_design():
    assert oc.review_item(summary_of({1: reading(100, 100), 2: reading(100, 90)})) is None
    assert oc.review_item({'status': 'not-measured', 'pages': [], 'flagged_pages': [], 'not_measured_pages': []}) is None
    assert oc.review_item(None) is None and oc.review_item('measured') is None and oc.review_item({}) is None
    assert oc.review_item(oc.summarise([], [], 'standard')) is None


def test_the_item_is_required_names_the_pages_and_does_not_claim_accuracy():
    item = oc.review_item(summary_of(MIXED, required=[1, 2, 3, 4, 5, 6]))
    assert item['id'] == 'ocr-pages-read-unsurely' and item['category'] == 'image-and-ocr'
    assert item['required'] is True and item['status'] == 'pending' and item['page'] == 5
    detail = item['detail']
    assert 'Many words were unsure: page 2 (30% of its words were read confidently).' in detail
    assert 'Some words were unsure: page 3 (75% of its words were read confidently).' in detail
    assert 'Too little text to judge: page 4 (5 words).' in detail and 'No words were found: page 5.' in detail
    assert 'Reading confidence could not be measured: page 6.' in detail
    assert 'page 1' not in detail, 'A confidently read page is not listed.'
    assert 'still not a check that they are right' in detail
    assert [row['page'] for row in item['evidence']['flagged']] == [5, 4, 2, 3] and item['evidence']['not_measured_pages'] == [6]
    json.dumps(item, allow_nan=False)


def test_one_word_is_singular_and_a_long_list_is_cut_with_the_rest_in_the_evidence():
    assert 'page 2 (1 word)' in oc.review_item(summary_of({1: reading(100, 100), 2: reading(1, 1)}))['detail']
    long = oc.review_item(summary_of({n: reading(100, 10 + n) for n in range(1, 41)}))
    assert long['detail'].count('(') == oc.MAX_LISTED + 1  # one parenthesis per listed page, plus "(see the evidence)"
    assert 'and 25 more (see the evidence)' in long['detail'] and len(long['evidence']['flagged']) == 40
    assert long['page'] == 1


def test_a_page_just_under_the_line_never_reads_as_sitting_on_it():
    item = oc.review_item(summary_of({1: reading(2000, 1799)}))
    assert 'page 1 (89% of its words were read confidently)' in item['detail']
    assert 'page 1 (29% of its words' in oc.review_item(summary_of({1: reading(100, 29)}))['detail'], 'Whole numbers must not lose a point to floating-point error.'


def test_when_nothing_could_be_measured_the_review_still_says_so():
    item = oc.review_item(oc.summarise([], [2, 3], 'standard'))
    assert item['required'] is True and item['page'] == 2
    assert 'Reading confidence could not be measured: page 2, page 3.' in item['detail']


# --- the hook ------------------------------------------------------------------------------------------------------

PLUGIN = Path(ocr.__file__).resolve().with_name('ocr_confidence_plugin.py')


@pytest.fixture
def plugin(monkeypatch):
    package, spec = types.ModuleType('ocrmypdf'), types.ModuleType('ocrmypdf.pluginspec')
    package.hookimpl = lambda **kwargs: (lambda function: function)
    spec.OcrEngine = type('OcrEngine', (), {})
    monkeypatch.setitem(sys.modules, 'ocrmypdf', package)
    monkeypatch.setitem(sys.modules, 'ocrmypdf.pluginspec', spec)
    loaded = importlib.util.spec_from_file_location('confidence_plugin_under_test', PLUGIN)
    module = importlib.util.module_from_spec(loaded)
    loaded.loader.exec_module(module)
    return module


class Native:
    """Stands in for the built-in Tesseract engine: remembers calls, writes a given hOCR page."""
    def __init__(self, page=None):
        self.page, self.calls = page, []

    def version(self):
        return '5.5.0'

    def creator_tag(self, options):
        return 'Tesseract OCR 5.5.0'

    def __str__(self):
        return 'Tesseract OCR 5.5.0'

    def languages(self, options):
        return {'eng'}

    def get_orientation(self, input_file, options):
        self.calls.append('orientation')
        return 'orientation'

    def get_deskew(self, input_file, options):
        self.calls.append('deskew')
        return 0.5

    def generate_hocr(self, input_file, output_hocr, output_text, options):
        self.calls.append(('hocr', Path(input_file).name))
        if self.page is not None:
            Path(output_hocr).write_text(self.page, encoding='utf-8')

    def generate_pdf(self, input_file, output_pdf, output_text, options):
        self.calls.append(('pdf', Path(input_file).name))


def bind(monkeypatch, folder, sha=SOURCE):
    folder.mkdir(exist_ok=True)
    monkeypatch.setenv(oc.ENV_KEYS[0], str(folder))
    monkeypatch.setenv(oc.ENV_KEYS[1], sha)
    return folder


def test_the_hook_hands_everything_to_the_native_engine_unchanged_and_records_the_counts(plugin, monkeypatch, tmp_path):
    folder = bind(monkeypatch, tmp_path / 'ev')
    native = Native(hocr(*([(96, 'Accessible')] * 9), (40, 'blurred'), (95, 'ok')))
    engine = plugin.MeasuringEngine(native)
    engine.generate_hocr(tmp_path / '000003_ocr.png', tmp_path / 'page.hocr', tmp_path / 'page.txt', object())
    assert native.calls == [('hocr', '000003_ocr.png')]
    assert (tmp_path / 'page.hocr').read_text(encoding='utf-8') == native.page, 'The hOCR page is not touched.'
    binding = {'plugin_sha256': oc.digest(PLUGIN), 'algorithm_sha256': oc.digest(Path(oc.__file__))}
    result = oc.validate_pages(folder, [3], binding, SOURCE, 5)
    assert result['problems'] == [] and result['pages'] == [{'page': 3, 'reading': {'words': 10, 'sure_words': 9, 'mean_confidence': 90.4}}]
    assert oc.grade(result['pages'][0]['reading']) == 'confident'


def test_the_hook_changes_nothing_about_the_engine_the_pdf_or_the_other_calls(plugin):
    native = Native()
    engine = plugin.MeasuringEngine(native)
    assert (engine.version(), engine.creator_tag(None), str(engine), engine.languages(None)) == ('5.5.0', 'Tesseract OCR 5.5.0', 'Tesseract OCR 5.5.0', {'eng'})
    assert engine.get_orientation('x', None) == 'orientation' and engine.get_deskew('x', None) == 0.5
    engine.generate_pdf('000001_ocr.png', 'a.pdf', 'a.txt', None)
    assert native.calls == ['orientation', 'deskew', ('pdf', '000001_ocr.png')]
    with pytest.raises(ValueError):
        plugin.MeasuringEngine(None)


def test_the_hook_wraps_the_native_engine(plugin):
    native = Native()
    wrapper = plugin.get_ocr_engine(None)
    next(wrapper)
    with pytest.raises(StopIteration) as stop:
        wrapper.send(native)
    assert isinstance(stop.value.value, plugin.MeasuringEngine) and stop.value.value.native is native


@pytest.mark.parametrize('case', ['no-environment', 'relative-folder', 'folder-missing', 'bad-hash', 'odd-file-name', 'page-zero', 'no-hocr-written', 'folder-unwritable'])
def test_a_problem_while_measuring_never_stops_the_reading(plugin, monkeypatch, tmp_path, case):
    monkeypatch.delenv(oc.ENV_KEYS[0], raising=False)
    monkeypatch.delenv(oc.ENV_KEYS[1], raising=False)
    folder, name, page = tmp_path / 'ev', '000001_ocr.png', hocr((96, 'Accessible'))
    if case == 'relative-folder':
        bind(monkeypatch, folder)
        monkeypatch.chdir(tmp_path)
        monkeypatch.setenv(oc.ENV_KEYS[0], 'ev')
    elif case == 'folder-missing':
        bind(monkeypatch, folder)
        monkeypatch.setenv(oc.ENV_KEYS[0], str(tmp_path / 'missing'))
    elif case == 'bad-hash':
        bind(monkeypatch, folder, sha='nothex')
    elif case == 'folder-unwritable':
        bind(monkeypatch, folder)
        (folder / '000001.json').mkdir()
    elif case != 'no-environment':
        bind(monkeypatch, folder)
    if case == 'odd-file-name':
        name = 'page.png'
    if case == 'page-zero':
        name = '000000_ocr.png'
    native = Native(None if case == 'no-hocr-written' else page)
    plugin.MeasuringEngine(native).generate_hocr(tmp_path / name, tmp_path / 'page.hocr', tmp_path / 'page.txt', object())
    assert native.calls == [('hocr', name)]
    assert not list(folder.glob('*.json')) if folder.is_dir() and case != 'folder-unwritable' else True


# --- the OCR step -------------------------------------------------------------------------------------------------

def scan(path, resolution=300.0):
    Image.new('L', (400, 500), 255).save(path, 'PDF', resolution=resolution)
    return path


def hidden_text(source, destination):
    with pikepdf.open(source) as pdf:
        page = pdf.pages[0]
        page.Resources.Font = pikepdf.Dictionary(FNamed=pikepdf.Dictionary(Type=pikepdf.Name.Font, Subtype=pikepdf.Name.Type1, BaseFont=pikepdf.Name.Helvetica))
        addition = pdf.make_stream(b'BT /FNamed 8 Tf 3 Tr 10 10 Td (Named synthetic added text) Tj ET')
        existing = page.obj.Contents
        page.obj.Contents = pikepdf.Array(list(existing) + [addition]) if isinstance(existing, pikepdf.Array) else pikepdf.Array([existing, addition])
        pdf.save(destination, deterministic_id=True)


def run_stubbed(tmp_path, monkeypatch, profile, leave):
    """Run the OCR step with an explicit child-process stub. leave(env, command, source_sha) writes the evidence that child would write."""
    seen = []
    version = tmp_path / 'version.txt'
    version.write_text('17.13.0\n', encoding='utf-8')
    source = scan(tmp_path / 'scan.pdf')

    def double(command, directory, timeout, memory, cancel, env):
        if '--version' in command:
            return {'status': 'completed', 'stdout': str(version)}
        command = list(map(str, command))
        seen.append((command, dict(env)))
        hidden_text(command[-2], command[-1])
        leave(env, command, ocr.sha(source))
        return {'status': 'completed', 'returncode': 0}

    monkeypatch.setattr(ocr, 'run', double)
    monkeypatch.setattr(ocr, 'ocr_availability', lambda settings: {'available': True, 'message': 'test double'})
    result = ocr.run_ocr(source, tmp_path / 'out.pdf', {'project_root': tmp_path / 'project', 'ocr_profile': profile}, tmp_path / 'evidence', mode='textless')
    return result, seen


def leave_numbers(readings, claimed=None):
    def leave(env, command, source_sha):
        folder = Path(env[oc.ENV_KEYS[0]])
        assert env[oc.ENV_KEYS[1]] == source_sha
        binding = {'plugin_sha256': oc.digest(PLUGIN), 'algorithm_sha256': oc.digest(Path(oc.__file__))}
        for page, value in readings.items():
            (folder / ('%06d.json' % page)).write_text(json.dumps({'schema': oc.SCHEMA, 'version': oc.VERSION, 'page': page, 'adapter_source_sha256': claimed or source_sha,
                                                                   **binding, 'reading': value}), encoding='utf-8')
    return leave


def test_the_standard_layout_asks_for_the_hook_and_reports_how_surely_each_page_was_read(tmp_path, monkeypatch):
    result, seen = run_stubbed(tmp_path, monkeypatch, 'standard', leave_numbers({1: reading(200, 100, 70.0)}))
    command, env = seen[0]
    assert result['status'] == 'completed', result.get('error')
    assert command.count('--plugin') == 1 and Path(command[command.index('--plugin') + 1]) == PLUGIN
    assert env[oc.ENV_KEYS[0]] == str(tmp_path / 'evidence' / 'confidence')
    summary = result['reading_confidence']
    assert summary['status'] == 'measured' and summary['flagged_pages'] == [1] and summary['layout'] == 'standard'
    assert summary['pages'][0]['grade'] == 'poor' and summary['pages'][0]['share_sure'] == 0.5


def test_a_page_without_valid_numbers_is_reported_not_measured_and_the_reading_still_completes(tmp_path, monkeypatch):
    result, _ = run_stubbed(tmp_path, monkeypatch, 'standard', lambda *a: None)
    assert result['status'] == 'completed' and result['preservation']['status'] == 'pass'
    assert result['reading_confidence']['status'] == 'unavailable' and result['reading_confidence']['not_measured_pages'] == [1]


def test_numbers_for_a_different_document_are_not_believed(tmp_path, monkeypatch):
    def leave(env, command, source_sha):
        leave_numbers({1: reading(200, 200)}, claimed='f' * 64)(env, command, source_sha)
    result, _ = run_stubbed(tmp_path, monkeypatch, 'standard', leave)
    assert result['reading_confidence']['status'] == 'unavailable' and result['reading_confidence']['problems']


def test_the_ruled_table_layout_keeps_its_own_plugin_first_and_adds_the_hook_after_it(tmp_path, monkeypatch):
    result, seen = run_stubbed(tmp_path, monkeypatch, 'table-lines', lambda *a: None)
    command = seen[0][0]
    plugins = [Path(command[i + 1]).name for i, part in enumerate(command) if part == '--plugin']
    assert plugins == ['ocr_table_plugin.py', 'ocr_confidence_plugin.py']
    assert result['status'] == 'error', 'Without its own evidence the table layout still fails as before.'
    assert 'reading_confidence' not in result


def turn_proofs(readings, scores=None):
    def leave(env, command, source_sha):
        folder = Path(env['PDF_REMEDIATOR_TURN_EVIDENCE'])
        binding = {'plugin_sha256': ocr.sha(Path(ocr.__file__).with_name('ocr_turn_plugin.py')), 'algorithm_sha256': ocr.sha(Path(turns.__file__))}
        for page, value in readings.items():
            body = {'schema': turns.SCHEMA, 'profile': 'turns', 'version': turns.VERSION, 'page': page, 'adapter_source_sha256': source_sha, **binding,
                    'turn_ccw': 0, 'reason': 'kept', 'trial_scores': scores or {'0': 200, '90': 34, '180': 34, '270': 200}, 'image_size': [400, 500], 'dpi': [300, 300],
                    'reading': value}
            (folder / ('%06d.json' % page)).write_text(json.dumps(body), encoding='utf-8')
    return leave


def test_the_turn_layout_asks_tesseract_for_word_confidences_and_reports_them(tmp_path, monkeypatch):
    result, seen = run_stubbed(tmp_path, monkeypatch, 'turns', turn_proofs({1: reading(300, 297, 95.0)}))
    command = seen[0][0]
    assert result['status'] == 'completed', result.get('error')
    config = Path(command[command.index('--tesseract-config') + 1])
    assert config == tmp_path / 'evidence' / 'word-confidence.cfg' and config.read_bytes() == b'tessedit_create_tsv 1\n'
    assert command.count('--plugin') == 1 and Path(command[command.index('--plugin') + 1]).name == 'ocr_turn_plugin.py'
    summary = result['reading_confidence']
    assert summary['status'] == 'measured' and summary['layout'] == 'turns' and summary['flagged_pages'] == [] and summary['pages'][0]['grade'] == 'confident'


def test_turn_numbers_that_are_missing_or_impossible_leave_the_page_unmeasured_but_do_not_fail_the_reading(tmp_path, monkeypatch):
    for case, value in (('missing', None), ('impossible', {'words': 5, 'sure_words': 9, 'mean_confidence': 1})):
        folder = tmp_path / case
        folder.mkdir()
        result, _ = run_stubbed(folder, monkeypatch, 'turns', turn_proofs({1: value}))
        assert result['status'] == 'completed', (case, result.get('error'))
        assert result['reading_confidence']['status'] == 'unavailable' and result['reading_confidence']['not_measured_pages'] == [1], case


def test_a_crash_while_reading_the_numbers_cannot_fail_the_reading(tmp_path, monkeypatch):
    def explode(*args):
        raise RuntimeError('explicit test crash')
    monkeypatch.setattr(oc, 'validate_pages', explode)
    result, _ = run_stubbed(tmp_path, monkeypatch, 'standard', leave_numbers({1: reading(200, 200)}))
    assert result['status'] == 'completed' and result['preservation']['status'] == 'pass'
    assert result['reading_confidence']['status'] == 'unavailable' and 'RuntimeError' in result['reading_confidence']['problems'][0]


def test_layouts_that_do_not_report_confidence_say_so_and_a_failed_reading_reports_nothing(tmp_path, monkeypatch):
    summary = ocr._reading_confidence('angles', [1], 1, SOURCE)
    assert summary['status'] == 'not-measured' and oc.review_item(summary) is None
    monkeypatch.setattr(ocr, 'run', lambda command, *a, **k: {'status': 'completed', 'stdout': str(tmp_path / 'version.txt')} if '--version' in command
                        else {'status': 'error', 'returncode': 1, 'error': 'explicit test stub'})
    (tmp_path / 'version.txt').write_text('17.13.0\n', encoding='utf-8')
    monkeypatch.setattr(ocr, 'ocr_availability', lambda settings: {'available': True, 'message': 'test double'})
    result = ocr.run_ocr(scan(tmp_path / 'scan.pdf'), tmp_path / 'out.pdf', {'project_root': tmp_path / 'project'}, tmp_path / 'evidence', mode='textless')
    assert result['status'] == 'error' and 'reading_confidence' not in result


# --- inside the whole pipeline -------------------------------------------------------------------------------------

def run_pipeline(tmp_path, monkeypatch, summary):
    (tmp_path / 'input').mkdir()
    source = tagged_pdf(tmp_path / 'input' / 'scan-like.pdf', [dict(role='P', mcids=[0]), dict(role='P', mcids=[1]), dict(role='P', mcids=[2])])

    def stub(input, output, *args, **kwargs):
        shutil.copyfile(input, output)
        return {'status': 'completed', 'preservation': {'status': 'pass'}, 'reading_confidence': summary, 'scope': 'Explicit OCR stub'}
    monkeypatch.setattr(ocr, 'run_ocr', stub)
    return process(source, tmp_path, ocr_mode='skip')


def listed(report):
    return [item for item in report['manual_review']['items'] if item['id'] == 'ocr-pages-read-unsurely']


def test_the_review_lists_the_unsure_pages_as_a_required_item_and_keeps_the_general_scan_review(tmp_path, monkeypatch, fast_validator):
    report = run_pipeline(tmp_path, monkeypatch, summary_of({1: reading(200, 60)}))
    item, = listed(report)
    assert item['required'] is True and item['page'] == 1 and 'page 1 (30% of its words were read confidently)' in item['detail']
    assert report['manual_review']['complete'] is False
    assert [p for p in report['processors'] if p['name'] == 'ocr'][0]['reading_confidence']['flagged_pages'] == [1]


@pytest.mark.parametrize('summary', [summary_of({1: reading(200, 199)}), {'status': 'not-measured', 'pages': [], 'flagged_pages': [], 'not_measured_pages': []}])
def test_a_confidently_read_scan_adds_no_extra_item(tmp_path, monkeypatch, fast_validator, summary):
    assert listed(run_pipeline(tmp_path, monkeypatch, summary)) == []


def test_numbers_that_could_not_be_measured_are_still_surfaced_to_the_reviewer(tmp_path, monkeypatch, fast_validator):
    item, = listed(run_pipeline(tmp_path, monkeypatch, oc.summarise([], [1], 'standard')))
    assert item['required'] is True and 'could not be measured: page 1' in item['detail']


# --- the turn hook ---------------------------------------------------------------------------------------------------

TURN_PLUGIN = Path(ocr.__file__).resolve().with_name('ocr_turn_plugin.py')


@pytest.fixture
def turn_plugin(monkeypatch):
    package, spec = types.ModuleType('ocrmypdf'), types.ModuleType('ocrmypdf.pluginspec')
    package.hookimpl = lambda **kwargs: (lambda function: function)
    spec.OcrEngine = type('OcrEngine', (), {})
    monkeypatch.setitem(sys.modules, 'ocrmypdf', package)
    monkeypatch.setitem(sys.modules, 'ocrmypdf.pluginspec', spec)
    loaded = importlib.util.spec_from_file_location('turn_plugin_under_test', TURN_PLUGIN)
    module = importlib.util.module_from_spec(loaded)
    loaded.loader.exec_module(module)
    return module


class TurnNative(Native):
    """Writes a readable hOCR page for the four trials and a small text page (and, when asked, its tab-separated page) for the final read."""
    def __init__(self, tab_page):
        super().__init__(hocr(*([(96, 'Accessible')] * 8)))
        self.tab_page = tab_page

    def generate_pdf(self, input_file, output_pdf, output_text, options):
        with pikepdf.new() as pdf:
            pdf.add_blank_page(page_size=(200, 100))
            font = pdf.make_indirect(pikepdf.Dictionary(Type=pikepdf.Name.Font, Subtype=pikepdf.Name.Type0, BaseFont=pikepdf.Name.Test,
                                                        ToUnicode=pdf.make_stream(b'placeholder')))
            pdf.pages[0].Resources = pikepdf.Dictionary(Font=pikepdf.Dictionary(F1=font))
            pdf.pages[0].Contents = pdf.make_stream(b'BT /F1 12 Tf <0041> Tj ET')
            pdf.save(output_pdf)
        if self.tab_page is not None:
            Path(output_pdf).with_suffix('.tsv').write_text(self.tab_page, encoding='utf-8')


@pytest.mark.parametrize('tab_page, expected', [
    (tsv((5, 96, 'Accessible'), (5, 96, 'reading'), (5, 40, 'blurred'), (5, 95, 'ok')), {'words': 3, 'sure_words': 2, 'mean_confidence': 77.3}),
    (None, None),
])
def test_the_turn_hook_keeps_the_counts_from_the_final_read_or_none_when_tesseract_wrote_no_tab_page(turn_plugin, monkeypatch, tmp_path, tab_page, expected):
    folder = tmp_path / 'turns'
    folder.mkdir()
    monkeypatch.setenv('PDF_REMEDIATOR_TURN_EVIDENCE', str(folder))
    monkeypatch.setenv('PDF_REMEDIATOR_TURN_SOURCE_SHA256', SOURCE)
    picture = tmp_path / '000001_ocr.png'
    Image.new('L', (60, 40), 255).save(picture, dpi=(300, 300))
    engine = turn_plugin.FixedTurnEngine(TurnNative(tab_page))
    engine.generate_pdf(picture, tmp_path / 'page.pdf', tmp_path / 'page.txt', types.SimpleNamespace(pdf_renderer='sandwich'))
    written = json.loads((folder / '000001.json').read_text(encoding='utf-8'))
    assert written['reading'] == expected and written['turn_ccw'] == 0 and written['version'] == turns.VERSION
    assert (tmp_path / 'page.pdf').is_file()
