# Meaning that may be carried by color alone

This describes the **color-meaning screen** (policy `bounded-color-meaning-1`), added for WCAG 2.1 success criterion
1.4.1, Use of Color: color must not be the only visual way to convey information, indicate an action, prompt a
response or distinguish an element.

## What it is, and what it is not

Whether color is the *only* carrier of meaning depends on what the color is for. A PDF does not say that. So the
screen **finds candidates for a person to look at**. It never decides that color is the only carrier, never decides
that it is not, never recolors or marks a page, and never approves anything.

- A candidate is a place to look, listed with its page and the facts that made it a candidate.
- A clean result means only that this bounded screen found no candidate. It is **not** a Use of Color result, a
  WCAG conformance claim or an LMS checker result.
- The screen is advisory. It never blocks a result (`blocking` is false) and is separate from the strict PDF/UA
  validation, the other supplemental checks and the page-fidelity gate. It does not change any of them.
- Whenever the screen finds a candidate, cannot measure part of the document, or its record is missing or not
  recognised, the result carries a **required, pending human review** (category `color-meaning`). A complete screen
  with no candidates adds no review of its own; the existing reviews of reading order, figure descriptions and
  contrast still apply.

## What is screened

Every record has a `kind`, a `page` and `status: needs-review`.

| Kind | What makes it a candidate |
|---|---|
| `colored-text` | Selectable text drawn in a **chromatic** fill color that differs clearly (RGB distance of at least 60) from the document's dominant body-text color. Reported once per page and color, with the run count, character count, up to five samples, up to eight boxes, and whether the difference is `hue-only` (luminance ratio to body text below 3:1) or `hue-and-lightness`. Text inside link rectangles is reported under `link-color-only` instead. A page that uses both red and green (or orange and green) text is marked `red_green_confusable_pair_on_page`. |
| `link-color-only` | Link text in a chromatic color that differs clearly from the body text, with **no underline-like line under it** (a thin horizontal path at least 60 percent as wide as the text, not more than 2.5 points tall, near its baseline) and **no visible link border** (`/Border` or `/BS` width above zero and a non-empty color; the default border counts as visible). The luminance ratio to body text is recorded, with `meets_3_to_1_with_body`, as evidence only. |
| `multi-hue-graphic` | Painted vector paths (fills and strokes) that lie within 72 points of each other, number at least 3 and use at least 2 different chromatic hues: a chart, legend or diagram-like area. Records the box (in page space, including enclosing Form XObject matrices), the hues, up to eight colors, the number of paths and how much text lies inside the box and within 72 points of it, so a reviewer can see whether labels are present. Labels nearby do not remove the candidate: whether they carry the same information is a human judgment. |
| `colored-annotation` | Markup annotations (highlights, underlines, squiggles, strike-outs, shapes, lines, ink, free text, carets, stamps, notes) whose own `/C` color is chromatic, counted by page, subtype and color, with how many also carry comment text. |
| `color-reference-text` | Text that points the reader at a color (the phrase patterns below). Reports the matched phrase and about 60 characters of context each side. |

A color is **chromatic** when its HSV saturation is at least 0.35 and its value at least 0.25. Black, white, grays,
near-black and pale tints are never candidates. Hue names are red (345 to 15 degrees), orange (15 to 45), yellow
(45 to 70), green (70 to 170), cyan (170 to 200), blue (200 to 260), purple (260 to 300) and pink (300 to 345).
Luminance ratios use the same WCAG relative-luminance formula as the contrast screen
(`contrast.contrast_ratio`).

Skipped on purpose: a filled shape that covers more than half of the page (a background); objects whose larger
dimension is under 1 point; invisible text (render modes 3 and 7, such as an OCR layer); content marked as an
Artifact (counted in `artifact_graphics_skipped`; whether a graphic is decorative is a human judgment); hidden or
not-viewable links; pop-up annotations.

### The phrase patterns (exact)

Matching is case-insensitive on the page text with whitespace collapsed. A pattern needs a pointing phrase, so
"The Red Cross", "blue lagoon" and "greenhouse" are not candidates. The color words are:

`red`, `orange`, `yellow`, `green`, `blue`, `purple`, `violet`, `pink`, `brown`, `gray`, `grey`, `teal`, `magenta`,
`cyan`.

| Pattern id | Regular expression (`C` is a color word above, `N` a noun below) | Example |
|---|---|---|
| `color-coded` | `\bcolou?r[- ]?cod(?:ed\|ing\|e)\b` | "color-coded", "colour coding" |
| `color-key` | `\bcolou?r[- ]?(?:key\|legend)\b` | "color key" |
| `the-color-noun` | `\b(?:the\|all\|any\|each\|every)\s+(?:(?:bright\|dark\|light\|bold)\s+)?C\s+N\b` | "the red items" |
| `shown-in-color` | `\b(?:highlighted\|shaded\|marked\|underlined\|circled\|outlined\|printed\|shown\|indicated\|labell?ed\|displayed\|written\|colou?red\|filled\|flagged)\s+(?:in\|with\|by)\s+(?:(?:bright\|dark\|light)\s+)?C\b` | "highlighted in yellow" |
| `act-on-color` | `\b(?:click\|press\|select\|choose\|tap\|use\|follow\|see\|refer to\|look for)\s+the\s+(?:(?:bright\|dark\|light)\s+)?C\b` | "click the green button" |
| `noun-in-color` | `\b(?:items?\|text\|words?\|cells?\|rows?\|columns?\|areas?\|bars?\|lines?\|sections?\|links?\|entries)\s+in\s+C\b` | "items in red" |
| `color-means` | `\bC\s+(?:indicates?\|means?\|shows?\|represents?\|denotes?\|signals?\|signifies\|marks)\b` | "red means stop" |
| `the-colors-mean` | `\b(?:the\s+)?colou?rs?\s+(?:indicates?\|shows?\|means?\|represents?\|denotes?\|signals?)\b` | "the colors indicate" |

`N` is: items, text, words, lines, areas, boxes, box, buttons, links, labels, bars, columns, rows, cells, sections,
squares, circles, dots, marks, markers, icons, fields, entries, headings, sentences, ones, slices, arrows, shapes,
triangles, lights (singular and plural forms). The complete expressions are in `color_meaning.PHRASE_PATTERNS` and
are copied into every saved record (`phrase_patterns`), so a record shows which patterns produced it.

Up to ten phrase candidates are listed per page. Page text is read up to 250,000 characters per document.

## What is not screened

Each is listed in the record's `coverage.not_assessed`, and a page with such content stays `needs-review` with the
reason named, so it can never earn a clean result:

- **Pictures** (`raster-image-color-not-assessed`). Color in photographs, scans and chart images is not measured.
  A chart saved as a picture is exactly the case that needs a person.
- **Shading and pattern paint** (`shading-color-not-assessed`, `pattern-paint-color-not-assessed`), including those
  used inside Form XObjects.
- **Annotation and form-field appearance streams** (`annotation-appearance-color-not-assessed`).
- **Type3 glyph color** (`type3-glyph-color-not-assessed`), and **outlined or clipping text**
  (`stroked-or-clipping-text-color-not-assessed`).
- Text whose fill color PDFium cannot resolve (`text-color-unresolved`), unreadable link rectangles
  (`unknown-link-rectangle`), and paint, bounds or marks it cannot read (`pattern-or-unresolved-paint-color`,
  `unknown-graphic-bounds`, `unknown-path-paint`, `unknown-artifact-marks`, `unknown-character-bounds`,
  `unknown-annotation-structure`, `unsupported-page-rotation`).
- **Optional content** (layers) in the document.
- **Meaning carried by position, shape, size or context**, and whether a tagged alternative text covers a graphic.
  Compare a candidate graphic with its figure description during the figure review.

Bounds: 100 pages, 250,000 characters, 400 records, 5,000 objects and 2,000 colored paths per page, 500
annotations per page, 20 graphic regions per page. A bound that is reached is recorded
(`character-limit`, `object-limit`, `chromatic-path-limit`, `record-limit`, `page-limit`, `region-limit`,
`region-work-limit`, `annotation-limit`, `phrase-limit`) and prevents a clean result. PDFium parses a page before these counters apply,
so they do not bound the native engine's own memory or time.

## Source repair

This program never recolors, adds marks to, or rewrites a page: that would change visible content and cannot pass
the exact visual-fidelity gate. For a candidate where color really is the only carrier:

1. Repair the **original authoring document** so the same information is also available another way:
   - text: say in words what a color means (the legend or key is not enough on its own); put the status, category or
     warning in the text ("Overdue", "Passed");
   - links: keep the underline, or give links a second cue (an icon, bold, a border) and a contrast ratio of at least
     3:1 with the surrounding text (W3C technique G183);
   - charts and diagrams: add direct labels, patterns, textures or different marker shapes to series, and put the
     values or conclusion in the text or in the figure description (G14, G182);
   - highlights: add a text note or a visible mark that says why the passage is highlighted;
   - instructions: refer to an item by its label, position or shape as well as by color.
2. Export a new **tagged PDF** from the source.
3. Process it again. The saved review of the original is kept; a new result starts its own reviews.

The same text is stored with every record as `fix_path` and shown in the review window.

## Where it shows up

- `inspection.inspect_pdf` adds `color_meaning` beside `small_font` and `empty_tags`.
- The supplemental profile adds a check row `color-meaning` (advisory, never blocking, listed in
  `coverage.automated`) and, when the screen is not clean, a required pending manual item with id and category
  `color-meaning`, its page numbers and the whole record as evidence. The profile string gains `+color-meaning-1`.
- A missing, unrecognised, forged-clean or incomplete screen record still produces the review (the same rule as the
  small-text and empty-tag screens), so an older inspection cannot lose the review by lacking the field.
- The review window shows a card, "Meaning that may depend on color needs review", with each candidate in plain
  words, the page buttons, the limits and the repair path. The card has no editing action.
- Saved reviews and result bundles from earlier builds are not re-assessed or rewritten: the assessment is made when
  a result is produced. Opening an older review shows only what that review already recorded.

## Checks

`tests/test_color_meaning.py` builds every PDF at run time and covers each candidate kind, its negatives (all-black
text, gray and pale colors, underlined and bordered links, single-hue, gray, distant and background shapes,
Artifact-marked shapes, invisible text, ordinary color words), shapes and text inside scaled Form XObjects,
unsupported content, the bounds, cancellation, source immutability and determinism, the end-to-end check profile and
the repair-finding view. `scripts/test-web-assets.cjs` covers the card. The test file also checks that this page lists
every phrase pattern, color word and threshold used by the code.

What only a person can check is in `TESTING-TODO.md`: looking at the card in the real window, and judging whether
the candidates and the repair guidance are right on real documents.

References: [WCAG 2.1 Understanding 1.4.1](https://www.w3.org/WAI/WCAG21/Understanding/use-of-color.html),
[G14](https://www.w3.org/WAI/WCAG21/Techniques/general/G14),
[G182](https://www.w3.org/WAI/WCAG21/Techniques/general/G182),
[G183](https://www.w3.org/WAI/WCAG21/Techniques/general/G183).
