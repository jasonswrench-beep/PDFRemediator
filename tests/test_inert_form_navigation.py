"""An empty form container beside ordinary page links and bookmarks is not an interactive form.

A plain jump inside the document or a web or mail link cannot run, open, send or change anything, so it no longer makes a
document look like a fillable form. Every other kind of action, any extra key, and any action that is shared or sits outside
the page links and bookmarks still does. The two independent checkers must agree on every case."""
from __future__ import annotations

import pikepdf
import pytest

from pdf_remediator import form_edits as forms, inspection, sidecar
from test_form_edits import inert_layout_pdf, inert_pdf, inventory


def verdicts(path):
    with pikepdf.open(path) as pdf:
        return forms.has_form_signals(pdf), inspection._inert_empty_acroform(pdf)


NOT_A_FORM = (False, True)
STILL_A_FORM = (True, False)


def goto(pdf, destination=None):
    page = pdf.pages[0].obj
    return pikepdf.Dictionary(S=pikepdf.Name.GoTo, D=destination if destination is not None
                              else pikepdf.Array([page, pikepdf.Name.XYZ, 0, 400, None]))


def uri(address='https://example.org/page?x=1'):
    return pikepdf.Dictionary(S=pikepdf.Name.URI, URI=pikepdf.String(address))


def link(pdf, action):
    return pdf.make_indirect(pikepdf.Dictionary(Type=pikepdf.Name.Annot, Subtype=pikepdf.Name.Link,
        Rect=pikepdf.Array([10, 10, 100, 30]), Border=pikepdf.Array([0, 0, 0]), A=action))


def bookmarks(pdf, *actions):
    outlines = pdf.make_indirect(pikepdf.Dictionary(Type=pikepdf.Name.Outlines))
    items = [pdf.make_indirect(pikepdf.Dictionary(Title=pikepdf.String('Section %d' % number), Parent=outlines, A=action))
             for number, action in enumerate(actions, 1)]
    for first, second in zip(items, items[1:]):
        first.Next = second; second.Prev = first
    outlines.First = items[0]; outlines.Last = items[-1]; outlines.Count = len(items)
    pdf.Root.Outlines = outlines
    return outlines, items


def navigation_pdf(path, variant):
    source = inert_pdf(path.parent / ('base-' + path.name))
    with pikepdf.open(source) as pdf:
        page = pdf.pages[0].obj
        def annotate(*annotations): page.Annots = pikepdf.Array(list(annotations))
        indirect = lambda action: pdf.make_indirect(action)
        # ---- ordinary navigation: not a form
        if variant == 'goto-page-link': annotate(link(pdf, goto(pdf)))
        elif variant == 'goto-named-link': annotate(link(pdf, goto(pdf, pikepdf.String('chapter-1'))))
        elif variant == 'goto-name-object-link': annotate(link(pdf, goto(pdf, pikepdf.Name.Chapter1)))
        elif variant == 'goto-fit-link': annotate(link(pdf, goto(pdf, pikepdf.Array([page, pikepdf.Name.Fit]))))
        elif variant == 'goto-fith-link': annotate(link(pdf, goto(pdf, pikepdf.Array([page, pikepdf.Name.FitH, 300]))))
        elif variant == 'uri-https-link': annotate(link(pdf, uri()))
        elif variant == 'uri-mailto-link': annotate(link(pdf, uri('mailto:someone@example.org')))
        elif variant == 'indirect-actions': annotate(link(pdf, indirect(goto(pdf))), link(pdf, indirect(uri())))
        elif variant == 'typed-action': annotate(link(pdf, pikepdf.Dictionary(Type=pikepdf.Name.Action, S=pikepdf.Name.URI, URI=pikepdf.String('https://example.org/'))))
        elif variant == 'bookmark-goto': bookmarks(pdf, goto(pdf))
        elif variant == 'bookmark-uri': bookmarks(pdf, uri())
        elif variant == 'bookmarks-in-a-chain': bookmarks(pdf, goto(pdf), indirect(goto(pdf)), uri())
        elif variant == 'links-and-bookmarks-together':
            annotate(link(pdf, indirect(goto(pdf))), link(pdf, uri())); bookmarks(pdf, indirect(goto(pdf)))
        elif variant == 'nested-bookmark':
            outlines, items = bookmarks(pdf, goto(pdf))
            child = pdf.make_indirect(pikepdf.Dictionary(Title=pikepdf.String('Child'), Parent=items[0], A=goto(pdf)))
            items[0].First = child; items[0].Last = child; items[0].Count = 1
        # ---- every other kind of action is still a form signal
        elif variant == 'link-javascript': annotate(link(pdf, pikepdf.Dictionary(S=pikepdf.Name.JavaScript, JS=pikepdf.String('app.alert(1)'))))
        elif variant == 'link-launch': annotate(link(pdf, pikepdf.Dictionary(S=pikepdf.Name.Launch, F=pikepdf.String('tool.exe'))))
        elif variant == 'link-submit-form': annotate(link(pdf, pikepdf.Dictionary(S=pikepdf.Name.SubmitForm, F=pikepdf.String('https://example.org/'))))
        elif variant == 'link-reset-form': annotate(link(pdf, pikepdf.Dictionary(S=pikepdf.Name.ResetForm)))
        elif variant == 'link-import-data': annotate(link(pdf, pikepdf.Dictionary(S=pikepdf.Name.ImportData, F=pikepdf.String('data.fdf'))))
        elif variant == 'link-named-action': annotate(link(pdf, pikepdf.Dictionary(S=pikepdf.Name.Named, N=pikepdf.Name.NextPage)))
        elif variant == 'link-remote-goto': annotate(link(pdf, pikepdf.Dictionary(S=pikepdf.Name.GoToR, F=pikepdf.String('other.pdf'), D=pikepdf.Array([0, pikepdf.Name.Fit]))))
        elif variant == 'link-hide': annotate(link(pdf, pikepdf.Dictionary(S=pikepdf.Name.Hide, T=pikepdf.String('field'))))
        elif variant == 'link-optional-content': annotate(link(pdf, pikepdf.Dictionary(S=pikepdf.Name.SetOCGState, State=pikepdf.Array())))
        elif variant == 'bookmark-launch': bookmarks(pdf, pikepdf.Dictionary(S=pikepdf.Name.Launch, F=pikepdf.String('tool.exe')))
        elif variant == 'bookmark-javascript': bookmarks(pdf, goto(pdf), pikepdf.Dictionary(S=pikepdf.Name.JavaScript, JS=pikepdf.String('1')))
        # ---- a navigation-looking action that is not plain navigation
        elif variant == 'uri-javascript-scheme': annotate(link(pdf, uri('javascript:app.alert(1)')))
        elif variant == 'uri-file-scheme': annotate(link(pdf, uri('file:///C:/Windows/System32/calc.exe')))
        elif variant == 'uri-no-host': annotate(link(pdf, uri('https:')))
        elif variant == 'uri-control-character': annotate(link(pdf, uri('https://example.org/a\nb')))
        elif variant == 'uri-map-image': annotate(link(pdf, pikepdf.Dictionary(S=pikepdf.Name.URI, URI=pikepdf.String('https://example.org/'), IsMap=True)))
        elif variant == 'uri-with-destination': annotate(link(pdf, pikepdf.Dictionary(S=pikepdf.Name.URI, URI=pikepdf.String('https://example.org/'), D=pikepdf.String('x'))))
        elif variant == 'uri-chained-action':
            annotate(link(pdf, pikepdf.Dictionary(S=pikepdf.Name.URI, URI=pikepdf.String('https://example.org/'), Next=goto(pdf))))
        elif variant == 'goto-chained-action':
            action = goto(pdf); action.Next = uri(); annotate(link(pdf, action))
        elif variant == 'goto-extra-key': action = goto(pdf); action.NewWindow = True; annotate(link(pdf, action))
        elif variant == 'goto-destination-is-not-a-page': annotate(link(pdf, goto(pdf, pikepdf.Array([pdf.Root, pikepdf.Name.Fit]))))
        elif variant == 'goto-destination-too-short': annotate(link(pdf, goto(pdf, pikepdf.Array([page]))))
        elif variant == 'goto-unknown-view': annotate(link(pdf, goto(pdf, pikepdf.Array([page, pikepdf.Name.Developer]))))
        elif variant == 'goto-text-in-coordinates': annotate(link(pdf, goto(pdf, pikepdf.Array([page, pikepdf.Name.XYZ, pikepdf.String('x'), 0, 0]))))
        elif variant == 'goto-boolean-coordinate': annotate(link(pdf, goto(pdf, pikepdf.Array([page, pikepdf.Name.XYZ, False, 0, 0]))))
        elif variant == 'goto-empty-name': annotate(link(pdf, goto(pdf, pikepdf.String(''))))
        elif variant == 'goto-with-address': annotate(link(pdf, pikepdf.Dictionary(S=pikepdf.Name.GoTo, D=pikepdf.String('x'), URI=pikepdf.String('https://example.org/'))))
        elif variant == 'action-wrong-type': annotate(link(pdf, pikepdf.Dictionary(Type=pikepdf.Name.Developer, S=pikepdf.Name.URI, URI=pikepdf.String('https://example.org/'))))
        elif variant == 'action-is-a-stream': annotate(link(pdf, pikepdf.Stream(pdf, b'', S=pikepdf.Name.URI, URI=pikepdf.String('https://example.org/'))))
        elif variant == 'action-is-an-array': annotate(link(pdf, pikepdf.Array([goto(pdf)])))
        # ---- plain navigation in the wrong place, or something else attached
        elif variant == 'link-has-additional-actions':
            annotation = link(pdf, goto(pdf)); annotation.AA = pikepdf.Dictionary(E=pikepdf.Dictionary(S=pikepdf.Name.GoTo, D=pikepdf.String('x'))); annotate(annotation)
        elif variant == 'link-outside-the-page-links': pdf.Root.Loose = link(pdf, goto(pdf))
        elif variant == 'direct-link-annotation':
            page.Annots = pikepdf.Array([pikepdf.Dictionary(Type=pikepdf.Name.Annot, Subtype=pikepdf.Name.Link, Rect=pikepdf.Array([0, 0, 1, 1]), A=goto(pdf))])
        elif variant == 'other-annotation-with-navigation':
            annotation = link(pdf, goto(pdf)); annotation.Subtype = pikepdf.Name.Text; annotate(annotation)
        elif variant == 'widget-with-navigation':
            annotation = link(pdf, goto(pdf)); annotation.Subtype = pikepdf.Name.Widget; annotation.FT = pikepdf.Name.Tx; annotate(annotation)
        elif variant == 'action-also-used-elsewhere':
            shared = indirect(goto(pdf)); annotate(link(pdf, shared)); pdf.Root.Shared = shared
        elif variant == 'action-also-inside-a-widget':
            shared = indirect(goto(pdf)); annotate(link(pdf, shared))
            pdf.Root.Hidden = pikepdf.Dictionary(Subtype=pikepdf.Name.Widget, A=shared)
        elif variant == 'document-open-action': pdf.Root.OpenAction = goto(pdf)
        elif variant == 'bookmark-with-unknown-key':
            outlines, items = bookmarks(pdf, goto(pdf)); items[0].Developer = pikepdf.String('unknown')
        elif variant == 'bookmark-outside-the-outline': pdf.Root.Loose = pdf.make_indirect(pikepdf.Dictionary(Title=pikepdf.String('x'), A=goto(pdf)))
        elif variant == 'bookmark-with-additional-actions':
            outlines, items = bookmarks(pdf, goto(pdf)); items[0].AA = pikepdf.Dictionary()
        elif variant == 'bookmark-chain-through-a-direct-first-item':
            outlines = pdf.make_indirect(pikepdf.Dictionary(Type=pikepdf.Name.Outlines))
            child = pdf.make_indirect(pikepdf.Dictionary(Title=pikepdf.String('c'), A=goto(pdf)))
            outlines.First = pikepdf.Dictionary(Title=pikepdf.String('d'), Next=child); pdf.Root.Outlines = outlines
        elif variant == 'bookmark-chain-through-a-direct-next-item':
            outlines, items = bookmarks(pdf, goto(pdf))
            child = pdf.make_indirect(pikepdf.Dictionary(Title=pikepdf.String('c'), A=goto(pdf)))
            items[0].Next = pikepdf.Dictionary(Title=pikepdf.String('d'), Next=child)
        elif variant == 'direct-bookmark-with-navigation':
            outlines = pdf.make_indirect(pikepdf.Dictionary(Type=pikepdf.Name.Outlines))
            outlines.First = pikepdf.Dictionary(Title=pikepdf.String('d'), A=goto(pdf)); pdf.Root.Outlines = outlines
        elif variant.startswith('stray-action-'):
            pdf.Root.Stray = pikepdf.Dictionary(Holder=pikepdf.Dictionary(S=pikepdf.Name('/' + variant.split('-')[-1])))
        elif variant == 'outline-loop':
            outlines, items = bookmarks(pdf, goto(pdf), uri(), pikepdf.Dictionary(S=pikepdf.Name.Launch, F=pikepdf.String('x')))
            items[-1].Next = items[0]
        else: raise ValueError('Unknown navigation fixture')
        out = path
        with out.open('xb') as stream: pdf.save(stream, deterministic_id=True)
    return out


PLAIN = ['goto-page-link', 'goto-named-link', 'goto-name-object-link', 'goto-fit-link', 'goto-fith-link', 'uri-https-link',
         'uri-mailto-link', 'indirect-actions', 'typed-action', 'bookmark-goto', 'bookmark-uri', 'bookmarks-in-a-chain',
         'links-and-bookmarks-together', 'nested-bookmark']
REFUSED = ['link-javascript', 'link-launch', 'link-submit-form', 'link-reset-form', 'link-import-data', 'link-named-action',
           'link-remote-goto', 'link-hide', 'link-optional-content', 'bookmark-launch', 'bookmark-javascript',
           'uri-javascript-scheme', 'uri-file-scheme', 'uri-no-host', 'uri-control-character', 'uri-map-image',
           'uri-with-destination', 'uri-chained-action', 'goto-chained-action', 'goto-extra-key',
           'goto-destination-is-not-a-page', 'goto-destination-too-short', 'goto-unknown-view', 'goto-text-in-coordinates',
           'goto-boolean-coordinate', 'goto-empty-name', 'goto-with-address', 'action-wrong-type', 'action-is-a-stream',
           'action-is-an-array', 'link-has-additional-actions', 'link-outside-the-page-links', 'direct-link-annotation',
           'other-annotation-with-navigation', 'widget-with-navigation', 'action-also-used-elsewhere',
           'action-also-inside-a-widget', 'document-open-action', 'bookmark-with-unknown-key',
           'bookmark-chain-through-a-direct-first-item', 'bookmark-chain-through-a-direct-next-item', 'direct-bookmark-with-navigation',
           'stray-action-GoToDp', 'stray-action-RichMediaExecute', 'stray-action-SetState', 'stray-action-NoOp',
           'bookmark-outside-the-outline', 'bookmark-with-additional-actions', 'outline-loop']


@pytest.mark.parametrize('variant', PLAIN)
def test_plain_page_links_and_bookmarks_do_not_make_an_empty_form_container_a_form(tmp_path, variant):
    source = navigation_pdf(tmp_path / 'source.pdf', variant); raw = source.read_bytes()
    assert verdicts(source) == NOT_A_FORM
    with pikepdf.open(source) as pdf:
        assert forms.is_inert_acroform(pdf)
    assert source.read_bytes() == raw


@pytest.mark.parametrize('variant', REFUSED)
def test_every_other_action_extra_key_or_misplaced_action_still_counts_as_a_form(tmp_path, variant):
    source = navigation_pdf(tmp_path / 'source.pdf', variant); raw = source.read_bytes()
    assert verdicts(source) == STILL_A_FORM
    assert source.read_bytes() == raw


def test_without_an_empty_form_container_nothing_changes_for_links(tmp_path):
    source = navigation_pdf(tmp_path / 'source.pdf', 'goto-page-link')
    with pikepdf.open(source) as pdf:
        del pdf.Root['/AcroForm']; pdf.save(tmp_path / 'no-form.pdf')
    with pikepdf.open(tmp_path / 'no-form.pdf') as pdf:
        assert not forms.has_form_signals(pdf) and not inspection._raw_form_signals(pdf)


def test_a_real_field_beside_plain_links_is_still_a_form(tmp_path):
    source = navigation_pdf(tmp_path / 'source.pdf', 'goto-page-link')
    with pikepdf.open(source) as pdf:
        pdf.Root.AcroForm.Fields.append(pdf.make_indirect(pikepdf.Dictionary(FT=pikepdf.Name.Tx, T=pikepdf.String('Name'))))
        pdf.save(tmp_path / 'field.pdf')
    assert verdicts(tmp_path / 'field.pdf') == STILL_A_FORM


def test_links_and_bookmarks_are_kept_exactly_when_a_reviewed_decision_is_applied(tmp_path):
    source = inert_layout_pdf(tmp_path / 'layout.pdf')
    with pikepdf.open(source) as pdf:
        page = pdf.pages[0].obj
        page.Annots = pikepdf.Array([link(pdf, pdf.make_indirect(goto(pdf))), link(pdf, uri())])
        bookmarks(pdf, goto(pdf)); pdf.save(tmp_path / 'with-links.pdf', deterministic_id=True)
    linked = tmp_path / 'with-links.pdf'
    assert verdicts(linked) == NOT_A_FORM
    data = inventory(linked)
    assert not any(row['kind'] == 'form-controls' for row in data['decisions'])
    title = next(row for row in data['decisions'] if row['kind'] == 'title')
    title['value'] = 'Reviewed title'; sidecar.bind_approval(title, 'Reviewer', '2026-10-31')
    out = tmp_path / 'reviewed.pdf'; sidecar.apply_decisions(linked, out, data, data['source_sha256'])
    with pikepdf.open(out) as pdf:
        assert forms.is_inert_acroform(pdf) and not forms.has_form_signals(pdf)
        assert [str(a.A.S) for a in pdf.pages[0].obj.Annots] == ['/GoTo', '/URI']
        assert str(pdf.Root.Outlines.First.A.S) == '/GoTo' and len(pdf.Root.AcroForm.Fields) == 0
    assert verdicts(out) == NOT_A_FORM


# ---- the standard, passive structure attributes that Word and a desktop PDF program write
def layout_variant(path, variant):
    source = inert_layout_pdf(path.parent / ('base-' + path.name))
    with pikepdf.open(source) as pdf:
        tree = pdf.Root.StructTreeRoot
        figure = tree.K[0].K[0]; attributes = figure.A
        header = lambda **extra: pikepdf.Dictionary(O=pikepdf.Name.Table, **extra)
        if variant == 'placement-block': attributes.Placement = pikepdf.Name.Block
        elif variant == 'placement-inline': attributes.Placement = pikepdf.Name.Inline
        elif variant == 'placement-unknown': attributes.Placement = pikepdf.Name.Developer
        elif variant == 'placement-text': attributes.Placement = pikepdf.String('Block')
        elif variant == 'table-layout': figure.S = pikepdf.Name.Table
        elif variant == 'header-row-scope': figure.S = pikepdf.Name.TH; figure.A = header(Scope=pikepdf.Name.Row)
        elif variant == 'header-column-scope': figure.S = pikepdf.Name.TH; figure.A = header(Scope=pikepdf.Name.Column)
        elif variant == 'header-both-scope': figure.S = pikepdf.Name.TH; figure.A = header(Scope=pikepdf.Name.Both)
        elif variant == 'header-spans': figure.S = pikepdf.Name.TH; figure.A = header(Scope=pikepdf.Name.Column, RowSpan=2, ColSpan=3)
        elif variant == 'cell-spans': figure.S = pikepdf.Name.TD; figure.A = header(RowSpan=2, ColSpan=2)
        elif variant == 'untyped-element': del figure['/Type']
        elif variant == 'list-decimal': figure.S = pikepdf.Name.L; figure.A = pikepdf.Dictionary(O=pikepdf.Name.List, ListNumbering=pikepdf.Name.Decimal)
        elif variant == 'list-bullets': figure.S = pikepdf.Name.L; figure.A = pikepdf.Dictionary(O=pikepdf.Name.List, ListNumbering=pikepdf.Name.Disc)
        elif variant == 'list-none': figure.S = pikepdf.Name.L; figure.A = pikepdf.Dictionary(O=pikepdf.Name.List, ListNumbering=pikepdf.Name('/None'))
        elif variant == 'list-continued':
            figure.S = pikepdf.Name.L
            figure.A = pikepdf.Dictionary(O=pikepdf.Name.List, ListNumbering=pikepdf.Name.Decimal, ContinuedList=True, ContinuedFrom=pikepdf.String('360'))
        elif variant == 'list-numbering-unknown': figure.S = pikepdf.Name.L; figure.A = pikepdf.Dictionary(O=pikepdf.Name.List, ListNumbering=pikepdf.Name.Developer)
        elif variant == 'list-numbering-text': figure.S = pikepdf.Name.L; figure.A = pikepdf.Dictionary(O=pikepdf.Name.List, ListNumbering=pikepdf.String('Decimal'))
        elif variant == 'list-extra-key': figure.S = pikepdf.Name.L; figure.A = pikepdf.Dictionary(O=pikepdf.Name.List, Developer=1)
        elif variant == 'list-with-box': figure.S = pikepdf.Name.L; figure.A = pikepdf.Dictionary(O=pikepdf.Name.List, BBox=pikepdf.Array([0, 0, 1, 1]))
        elif variant == 'list-wrong-owner-kind': figure.S = pikepdf.Name.L; figure.A = pikepdf.Dictionary(O=pikepdf.Name.Layout, ListNumbering=pikepdf.Name.Decimal)
        elif variant == 'list-continued-not-boolean': figure.S = pikepdf.Name.L; figure.A = pikepdf.Dictionary(O=pikepdf.Name.List, ContinuedList=1)
        elif variant == 'list-continued-from-number': figure.S = pikepdf.Name.L; figure.A = pikepdf.Dictionary(O=pikepdf.Name.List, ContinuedFrom=360)
        elif variant == 'list-continued-from-empty': figure.S = pikepdf.Name.L; figure.A = pikepdf.Dictionary(O=pikepdf.Name.List, ContinuedFrom=pikepdf.String(''))
        elif variant == 'list-continued-from-control': figure.S = pikepdf.Name.L; figure.A = pikepdf.Dictionary(O=pikepdf.Name.List, ContinuedFrom=pikepdf.String('a\nb'))
        elif variant == 'role-map-moves-list': figure.S = pikepdf.Name.L; figure.A = pikepdf.Dictionary(O=pikepdf.Name.List, ListNumbering=pikepdf.Name.Decimal); tree.RoleMap = pikepdf.Dictionary(L=pikepdf.Name.P)
        elif variant == 'header-unknown-scope': figure.S = pikepdf.Name.TH; figure.A = header(Scope=pikepdf.Name.Developer)
        elif variant == 'header-extra-key': figure.S = pikepdf.Name.TH; figure.A = header(Scope=pikepdf.Name.Row, Developer=1)
        elif variant == 'header-with-box': figure.S = pikepdf.Name.TH; figure.A = header(Scope=pikepdf.Name.Row, BBox=pikepdf.Array([0, 0, 1, 1]))
        elif variant == 'header-wrong-owner-kind': figure.S = pikepdf.Name.TH; figure.A = pikepdf.Dictionary(O=pikepdf.Name.PrintField, Scope=pikepdf.Name.Row)
        elif variant == 'header-without-owner-kind': figure.S = pikepdf.Name.TH; figure.A = pikepdf.Dictionary(Scope=pikepdf.Name.Row)
        elif variant == 'header-span-zero': figure.S = pikepdf.Name.TH; figure.A = header(RowSpan=0)
        elif variant == 'header-span-huge': figure.S = pikepdf.Name.TH; figure.A = header(ColSpan=100000)
        elif variant == 'header-span-boolean': figure.S = pikepdf.Name.TH; figure.A = header(ColSpan=True)
        elif variant == 'header-span-text': figure.S = pikepdf.Name.TH; figure.A = header(RowSpan=pikepdf.String('2'))
        elif variant == 'header-scope-text': figure.S = pikepdf.Name.TH; figure.A = header(Scope=pikepdf.String('Row'))
        elif variant == 'table-without-box': figure.S = pikepdf.Name.Table; del attributes['/BBox']
        elif variant == 'table-table-attributes': figure.S = pikepdf.Name.Table; figure.A = header(Scope=pikepdf.Name.Row)
        elif variant == 'unlisted-role': figure.S = pikepdf.Name.TR
        elif variant == 'role-map-moves-header': figure.S = pikepdf.Name.TH; figure.A = header(Scope=pikepdf.Name.Row); tree.RoleMap = pikepdf.Dictionary(TH=pikepdf.Name.P)
        elif variant == 'role-map-moves-table': figure.S = pikepdf.Name.Table; tree.RoleMap = pikepdf.Dictionary(Table=pikepdf.Name.P)
        elif variant == 'role-map-moves-cell': figure.S = pikepdf.Name.TD; figure.A = header(RowSpan=2); tree.RoleMap = pikepdf.Dictionary(TD=pikepdf.Name.P)
        elif variant == 'role-map-only-values': tree.RoleMap = pikepdf.Dictionary(Chart=pikepdf.Name.Figure, Footnote=pikepdf.Name.Note)
        elif variant == 'untyped-lookalike': del figure['/Type']; del figure['/P']
        elif variant == 'untyped-without-role': del figure['/Type']; del figure['/S']
        elif variant == 'untyped-wrong-parent': del figure['/Type']; figure.P = tree
        else: raise ValueError('Unknown attribute fixture')
        out = path
        with out.open('xb') as stream: pdf.save(stream, deterministic_id=True)
    return out


ACCEPTED_ATTRIBUTES = ['placement-block', 'placement-inline', 'table-layout', 'header-row-scope', 'header-column-scope',
                       'header-both-scope', 'header-spans', 'cell-spans', 'untyped-element', 'role-map-only-values',
                       'list-decimal', 'list-bullets', 'list-none', 'list-continued']
REFUSED_ATTRIBUTES = ['placement-unknown', 'placement-text', 'header-unknown-scope', 'header-extra-key', 'header-with-box',
                      'header-wrong-owner-kind', 'header-without-owner-kind', 'header-span-zero', 'header-span-huge',
                      'header-span-boolean', 'header-span-text', 'header-scope-text', 'table-without-box',
                      'table-table-attributes', 'unlisted-role', 'role-map-moves-header', 'role-map-moves-table',
                      'role-map-moves-cell', 'untyped-lookalike', 'untyped-without-role', 'untyped-wrong-parent',
                      'list-numbering-unknown', 'list-numbering-text', 'list-extra-key', 'list-with-box', 'list-wrong-owner-kind',
                      'list-continued-not-boolean', 'list-continued-from-number', 'list-continued-from-empty',
                      'list-continued-from-control', 'role-map-moves-list']


@pytest.mark.parametrize('variant', ACCEPTED_ATTRIBUTES)
def test_standard_passive_figure_table_and_cell_attributes_keep_an_empty_form_container_inert(tmp_path, variant):
    source = layout_variant(tmp_path / 'source.pdf', variant); raw = source.read_bytes()
    assert verdicts(source) == NOT_A_FORM
    assert source.read_bytes() == raw


@pytest.mark.parametrize('variant', REFUSED_ATTRIBUTES)
def test_unproved_or_lookalike_structure_attributes_still_count_as_a_form(tmp_path, variant):
    source = layout_variant(tmp_path / 'source.pdf', variant); raw = source.read_bytes()
    assert verdicts(source) == STILL_A_FORM
    assert source.read_bytes() == raw
