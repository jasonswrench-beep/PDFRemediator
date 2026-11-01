# Repair options added on the `a1-turn-first-ocr` branch

Nothing here makes a document accessible. Every result is a draft: the strict
validator, the inspector, the all-page fidelity check and a person still decide, and nothing is called "verified accessible".

Every option below keeps the original PDF unchanged, writes a separate result and records what it did in the run report.
A repair that cannot prove it left every page picture, page box and annotation identical (and added or removed no text token
where it should not) publishes nothing.

## Scans stored sideways or upside down

```
fix scan.pdf -o out --ocr textless --ocr-profile turns
```

Tries the four right-angle turns of each page, keeps the turn that reads best, and places the recognised text back on the
original page. The page picture is never changed. `--ocr redo` is refused with this profile. It is slower than the standard
profile because it reads each page up to four times.

In the web workspace choose "Pages stored sideways or upside down" under Scan layout (it needs "wholly scanned pages" or "scan-only" OCR, like the command line).

## Fonts with no Unicode map ("bad OCR" text layers)

```
fix document.pdf -o out --repair-ocr-mappings
```

Some PDFs draw visible text with embedded two-byte fonts that carry no ToUnicode map, so a screen reader receives control
characters. The option lines every drawn glyph up with the word Tesseract reads at that spot, votes per font and code, and
writes the missing map only where the votes agree, a held-back fifth of the words is predicted at 95 % or better and a
round-trip check reads the words back. It must be used on its own (not with OCR or `--repair-source-mappings`). The result is
an inference from OCR, not an authority: a required review item asks a person to compare the extracted text with the pages.
Fonts that stay partly unmapped are named in that item.

In the web workspace the same choice is the checkbox "Rebuild a missing letter dictionary by reading each page" under Processing options. Ticking it opens a dialog
that explains the repair; the box stays ticked only if you answer "Rebuild the dictionary". While it is on, the scanned-text option is set to off and the
character-mapping checkbox is unticked and locked, because the repair must be its own operation. It needs the OCR components; without them the box is switched off.
Retry keeps the saved choice.

## Designed (publisher-made) PDFs: automatic

No option is needed. When the tagging engine runs, two steps wrap it:

* **Before the engine, repeated page parts are unshared.** A header, footer or background drawn as one Form XObject on many
  pages is tagged once but claimed once per page, which breaks the structure links and fails PDF/UA 7.20-2. Each repeated use
  now gets its own byte-identical copy. Files without repeated forms, and files that already have a structure tree, are left
  alone.
* **After the engine, the structure links are repaired.**
  * Structure references to marked content that does not exist are removed. A reference is never moved to nearby content, and
    a reference whose content exists in a different stream is reported and left for review.
  * An emptied element that carries only a placeholder description such as "image 33" is set aside and noted in a required
    review item ("Check content whose placeholder description was set aside"). It does not stop the file. An emptied element
    that carries real replacement text still refuses, and the report says why.
  * A structure-element ID that nothing refers to, in a file with no IDTree, is dropped. (One such ID made the table-header
    check fail for every table in the file.) An ID named by a table cell's `Headers` list is never dropped.

Each step is recorded in the report (`unshared-forms`, `tagged-repairs`), followed by the same all-page fidelity gate.

## Optional font character lists (CIDSet): only with your consent

```
fix document.pdf -o out --remove-cidset
```

In the web workspace the same choice is the checkbox "Remove the optional font character lists (CIDSet)" under Processing
options. Ticking it opens a dialog that explains the removal; the box stays ticked only if you answer "Remove the lists".

Many PDF programs write an optional list, called a CIDSet, inside each embedded font. It names the characters the font
contains. When that list is wrong or incomplete, the strict PDF/UA-1 check fails even though the page looks right and reads
right. Allowing the removal deletes the list from every embedded font that has one. No page picture, text or character drawing
changes; PDF readers and screen readers work from the font itself. The removal is recorded in the report (`cidset_removed`).
Leave the option off if you need the fonts exactly as the originating program wrote them.

Interactive forms are retained exactly, so a form file with this option on is refused ("needs manual") rather than quietly
ignored. Repeated-form unsharing is skipped when `--repair-source-mappings` is chosen.

## Low-resolution scans are enlarged for reading (automatic)

Text recognition reads small page pictures badly. A scan whose page picture is under 250 dpi is now read from a 300 dpi
enlargement of that picture (OCRmyPDF `--oversample 300`); the page itself is never changed, and the all-page fidelity check
still decides. On a test scan stored at 80 dpi, the same passage went from 48% of words right to 85%; a 200 dpi faint scan
gained about ten points. A page that would need more than 64 megapixels at 300 dpi is read as it is. Applies to the standard
and the sideways/upside-down (`turns`) scan layouts; the ruled-table and tilted-text layouts are unchanged. The report keeps
the decision (`oversample`: the lowest estimated dpi, the pages below 250 and the reason). Enlarging makes reading a little
slower for those pages.

## Scanned pages the text recognition read least surely are listed (automatic)

Tesseract rates every word it reads from 0 to 100. After reading, the app counts for each page how many words (of three letters
or more) were read at 80 or above, and the review gets a required item, "Compare the scanned pages the text recognition read
least surely", that names the pages worth a closer look, worst first:

| What the page shows | Named as |
|---|---|
| fewer than 60% of its words read at 80 or above | many words were unsure |
| 60% up to (not including) 90% | some words were unsure |
| fewer than 8 words counted | too little text to judge |
| no words found | no words were found |
| the numbers for a page could not be read | could not be measured |

A page read at 90% or more is not listed. This is a guide to where misread words are likely, not a check: a confident word can
still be wrong, so the general review of scanned text stays required. On test scans, a faint page at 80 dpi read with 5–15% of
its words at 80 or above before it was enlarged for reading, and 76–91% after; clean scans were at 92–100%; a faint 20-page scan was at 29–77% on every page. The item is
produced for the standard, ruled-table and sideways/upside-down (`turns`) layouts. The tilted-text layout does not report word
confidence, so it says "not measured" in the report and adds no item. The counts are kept in the report under the OCR step
(`reading_confidence`); the page picture, the text layer and the fidelity check are not affected, and a problem while counting
can never stop the reading (the page is then named as not measured).

## Documents that already have an author's tags: kept, not rebuilt (automatic)

Tagged files made by Word or a browser used to be rebuilt by the tagging engine whenever even one picture was outside the
author's tags, and the author's real picture descriptions were replaced by the engine's "image 1". Now:

* **A few unmarked pictures or drawings** (no more than 25, never text) are marked as page decoration so the author's tags
  stay (`covered-graphics`). The review gets a required item, "Confirm the graphics outside the existing tags are only
  decoration", naming the pages. Unmarked text, a form that paints text or more than 25 pieces still send the file to the
  engine, as before.
* **Small fixes to the author's tags** (`author-tag-repairs`): browser-style `Strong` and `Em` types are mapped to the standard
  `Span` in the RoleMap; a Figure that only wraps another Figure (a browser's picture-plus-caption) becomes a Div; a visible
  Link with no `/Contents` gets the words printed under it, or its address when nothing is printed there. These run on every
  route and are recorded with what was changed.
* **When the tags cannot be kept**, the real picture descriptions that were in them are listed in a required review item,
  "Re-enter the picture descriptions written in the original tags" (`author-descriptions-not-carried`), because the rebuilt
  tags start from the engine's placeholders.

Each step ends in the all-page fidelity gate (every page picture, box and annotation identical; no text token added or
removed) and, for covering, the linkage and coverage checks. Still not repaired: a table whose rows have different numbers of
cells (a browser leaves out empty cells), reading order and heading levels.

## Reviews made with these options

A review made with `--repair-ocr-mappings` can be adopted for accepted edits like any other (the reference policy
`ocr-derived-character-mapping` is accepted). The settings record includes `remove_cidset`; reviews made before the setting
existed are still accepted when it is off.
