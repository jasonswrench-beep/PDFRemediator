# Wrong characters, Unicode maps and fonts

This page says what PDF Remediator checks about the *characters* a reader extracts from a PDF, what a reviewer can
correct, what it refuses, and what stays with the authoring source. Extracted text is what screen readers speak, what
copy and paste yields and what search finds, so a character that looks right on the page can still be wrong underneath.

**Nothing here proves a character is right.** A text extraction that looks plausible, a mapping that passes every check
and a rerun of OCR are all unable to show what a glyph means. Only a person comparing the visible page with the
extracted text can. No model is used; everything below works with AI off.

## 1. The screen: "Some characters may be extracted wrongly"

Every scan now reads the page programs (and the Form XObjects they use) and records, for each font that shows text,
which character codes are used and what text a reader gets for them. It is an advisory screen: it can add a required
review item, and it never blocks a result by itself.

| It reports | What it means |
|---|---|
| Private-use characters (U+E000 to U+F8FF and the supplementary planes) | The font maps a code to a character with no agreed meaning. A reader speaks nothing or a wrong sound. |
| Replacement character (U+FFFD), control characters, noncharacters, unassigned code points | The text is not a letter, digit or symbol. |
| Codes with no entry in an incomplete ToUnicode map | The code used on a page is missing from the map. |
| No Unicode map and no standard encoding | Nothing in the file says what the codes mean. |
| A mapping that disagrees with the glyph name | The font's own `Differences` names the glyph `e` but the map says another character. Compared after compatibility normalisation, so a ligature `fi` is not a disagreement. |
| Text that disagrees with its `ActualText` | The mapped text and the declared replacement text of the same marked content differ. A reader that honours ActualText uses one, a reader that does not uses the other. |
| A word that mixes Latin letters with look-alike Cyrillic or Greek letters | A typical sign of OCR or mapping damage, found in the extracted page text. |
| Suspect characters in the extracted page text | Private-use, replacement or control characters on a page, when no font-level finding already explains them. |

Each record gives the font, the code (with its width in bytes), how often it is used, the first page, the text it
extracts as, the glyph name if one exists and a short piece of the surrounding text with every suspicious character
shown as `U+XXXX`. Lists are bounded (40 codes per record, 400 records, 500 pages, 3,000,000 operations). If a bound is
reached, or a font cannot be decoded, the screen says so and never reports a clean pass.

**Limits of the screen.** It reads page content and nested Form XObjects only; annotation appearances, patterns and
Type 3 glyph programs are not scanned. Fonts that use a named two-byte CMap other than Identity-H/V are listed as not
checked. A code with no flag can still carry the wrong meaning.

## 2. Unembedded fonts: guidance, not repair

Fonts that are used but not embedded are listed with their name, type and whether they are one of the 14 standard
fonts. A reader then draws glyphs from a font of its own, so the file does not fix what a code looks like.

**This program does not embed a font, substitute a font or guess a character, and it never will to clear a validator.**
The strict validator already stops a PDF with an unembedded font from becoming a candidate. The repair is in the
authoring source: export a new tagged PDF with the fonts embedded (or use a font with proper Unicode mapping), then
process that copy.

## 3. Reviewed correction of an existing Unicode map (embedded fonts)

When an embedded font already has a ToUnicode map but a code names the wrong character, a reviewer who has compared the
page can state the intended text for that code and create a **separate corrected copy**. The original is never changed.

### What a correction changes

Only the `ToUnicode` map of each named font. The copy keeps every other object exactly: page programs, font programs,
widths, encodings, structure, annotations and navigation. Every other entry of the map keeps its meaning.

### Workflow (command line)

```powershell
# 1. Read-only: what does each used code extract as?
remediator characters inventory .\chapter.pdf -o .\inventory.json

# 2. A reviewer who has compared the page names the intended text per row and signs the plan.
remediator characters plan .\chapter.pdf --accepted-by "Ada Reviewer" --accepted-at 2026-11-16 `
    --set 8:0:65=e --set 8:0:66=U+00E9 -o .\plan.json

# 3. A separate copy plus its evidence file. Nothing is ever overwritten.
remediator characters apply .\chapter.pdf --plan .\plan.json --plan-sha256 <hash of plan.json> -o .\chapter-corrected.pdf
```

`--set ID=TEXT` takes a row id from the inventory (`font:generation:code`) and the intended text, written out or as
`U+XXXX` code points. The plan carries the reviewer's name and the date: **named acceptance is part of the plan, and
apply refuses a plan without it.** The save, accept and apply steps stay separate, as in the other reviewed edits.

The window shows the screen's findings in plain words and points here; it does not yet offer a correction editor
(see section 6).

### What must be proved before the copy is published

All of these are checked on the saved bytes, independently of the code that wrote the map. If any fails, nothing is
published and no partial file is left.

1. **Binding.** The plan names this exact PDF (SHA-256) and this exact inventory; every row still has the same font,
   code, previous text, map hash and fingerprint. A different file, a changed font or a stale plan is refused.
2. **Object graph.** Everything reachable from the catalog is identical to the source, compared without regard to object
   numbering, except the `ToUnicode` entry of each edited font.
3. **Map read-back.** Each rewritten map reads back as the old entries plus exactly the reviewed ones, with the same code
   space.
4. **Pixels and page furniture.** Every page renders identically (PDFium, exact pixels) and keeps its page boxes,
   annotations, bookmarks, named destinations and page labels.
5. **Extracted text.** Text extracted from the copy differs from the source only where an edited font drew an edited
   code.
6. **Fresh review.** The copy is a new document. It inherits no approval, and the evidence file lists the pending human
   review: compare every corrected character with the visible page in context.

### What is refused, and why

| Refused | Reason |
|---|---|
| Encrypted, signed (permissions or signature) and PDF 2.x documents; documents with an interactive form | Their values, appearances and signatures are kept exactly by other workflows. |
| Fonts that are not embedded | The visible character is not fixed by the file; see section 2. |
| Fonts with no readable ToUnicode map | A map for every used code would have to be invented; supplying all of them is not supported yet. |
| Composite fonts other than Identity-H/V with an embedded CID font; direct (non-indirect) font dictionaries | The codes cannot be decoded, or one edit cannot be bound to the font. |
| A code whose current text is more than one character | Extraction cannot show which of several characters changed. |
| Two used codes of one font that extract as the same text, corrected differently or only one of them | Extraction names a font, not a code, so the change could not be proved. Correct all of them to the same text, or none. |
| A same-named font object (another subset of the same font) that extracts the same text | Same reason. |
| Intended text that is empty, longer than 16 characters, or holds a control, format, private-use, surrogate, unassigned or replacement character | Such text cannot be what a code means. |
| A correction that repeats the current text, a repeated code, an unknown row, a stale fingerprint | Nothing to change, or the plan no longer matches the file. |
| Incomplete page reading (page, operation or font limit reached) | The inventory would not be complete. |

## 4. Text that came from OCR

The OCR text editor (Document edits, OCR text corrections) remains the place to correct a wrong OCR word, and its
existing checks and named acceptance apply. The screen adds a pointer: the mixed-script and suspect-character findings
name the pages to look at first. Running OCR again changes the text, not the certainty: a second reading can be wrong in a
new place. A scan that is cut off or unreadable needs a better source.

## 5. Source-repair guidance

When the visible character is right but its text is wrong, and a correction here is not available or not enough:

1. Re-export the authoring document with fonts **embedded** and a font that has real Unicode mapping.
2. Avoid symbol or decorative fonts for ordinary letters, and avoid printing to PDF through drivers that replace text
   with their own glyph codes.
3. For mathematics, export from a source that writes Unicode (or use ActualText on the whole expression).
4. Process the new PDF; the old one and its review stay as they were.

## 6. What is not built yet

* A correction editor in the program window (inventory, draft, named acceptance, separate Apply, and the corrected copy
  entering the ordinary review as a new source with a recorded lineage, as the OCR corrected copy does). The checked
  library and the command line above are the foundation; the window and the lineage record are the next step.
* Fonts without a ToUnicode map, Type 3 glyph programs and named two-byte CMaps are screened or listed, not repaired.
* Embedding or replacing an unembedded font, in any form.
* Any claim that a corrected character is right. A named human review of the corrected copy stays required.

Related: [what it does and does not do](WHAT-IT-DOES-AND-DOES-NOT-DO.md), [repair options](REPAIR-OPTIONS.md).
