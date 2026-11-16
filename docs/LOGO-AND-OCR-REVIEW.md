# Logo and branding, and the scanned-page sample

Two review aids for the two places where a program cannot decide for a person: what a repeated logo should say to a screen
reader, and whether recognized text really matches a scan. Both work without any AI model. Both only organize a person's own
decisions; neither approves anything, and neither can make a result "verified".

## 1. Logo and branding

### What it does

A logo is usually one picture repeated on many pages. Deciding it page by page is slow and invites inconsistent answers; deciding
it for all of them at once would hide pages where the picture means something different. **Logo and branding** (in the review's
*Document edits* panel) lists the places a logo probably appears, together, so one choice can be made once and still be applied to
each occurrence on purpose.

Press **Find logos and repeated branding**. The program reads the exact PDF the review's decisions are about (it is never changed) and
lists a figure as a likely logo when any of these is true (policy `bounded-logo-branding-1`; the limits are recorded in the evidence):

- the same picture (identical pixels, whatever its size on the page) is a figure on **two or more pages** and takes up **at most
  15 percent** of the page;
- it takes up **at most 6 percent** of the page and sits in the **top or bottom band** (the outer 12 percent) or a **side margin**
  (the outer 8 percent);
- its existing description already calls it a logo, brand mark, wordmark, emblem, crest or seal.

Pictures that are the same picture on several pages form one group. Other candidates are listed one by one. Each occurrence shows its
page, where it sits, how much of the page it fills, why it was listed, its present description, and a button that opens that page.

### What you decide

For the occurrences you **select** (none is selected for you):

| Choice | What it saves | What it means |
|---|---|---|
| **Save this description for the selected** | The same description on each selected occurrence | The picture carries meaning. A screen reader will say your words. |
| **Save as decorative for the selected** | The existing "mark decorative" choice on each selected occurrence | The picture stays visible; assistive technology skips it. Use it when the same name is already written beside the picture. |

Saving keeps a **draft**. **Accept the saved choice for the selected** records your name, and the date, on each selected
occurrence. The PDF changes only after **Apply accepted edits**, which runs the program's usual checks. This is the same path the
ordinary figure list uses, so the draft, the acceptance and the Apply step behave exactly as they do there:

- a changed description or a changed purpose takes back an acceptance that was already given;
- a new description and decorative marking cannot apply to the same figure, so saving one withdraws the other;
- decorative marking is offered only where the review already offers it for that figure (it needs the document and section structure
  the program can prove); where it is not offered, you can still describe the picture;
- a figure tag that appears on several pages must get one description everywhere, so it cannot be split across a selection;
- if the group's membership, a decision's context or the review's revision changed since you looked, the action is refused;
- accepting an occurrence that has nothing saved is refused, not skipped.

### Writing a logo description

Name the organisation or product as the logo shows it. Add "logo" only if that helps, and leave out slogans and marketing words. A line
of roughly 3 to 10 words is usually enough. If the same name is already written next to the picture, decorative is usually the better
choice, so a screen reader does not repeat it on every page. Look at the page before choosing.

### Guidance for authors (the lasting fix)

Make the fix where the document is written. In the word processor or layout program, give the logo alternative text once, or mark it
decorative when its name is written beside it, and place it in the page header or footer so it repeats as a page artifact rather than as
content. Then export a new tagged PDF and process that.

### What it does not prove

- Candidates come from size, position and repetition only. The program does not read the picture and cannot tell what it shows. A
  picture that is not listed can still be a logo; use the ordinary figure list for it.
- Pictures inside Form XObjects, logos drawn as vector shapes, and pictures the page content does not tie to a figure are not matched.
  Two copies of a logo stored as different image files are treated as different pictures even if they look alike.
- Listing a picture decides nothing. Accepting a description does not establish that it is a good one.
- Text read from a figure by OCR is not used as a signal: the program has no per-figure OCR text to use.

## 2. The scanned-page sample

### What it does

The text recognition measures how sure it was of each word. That says where misread words are likely; it never says a page is right.
For a document that has scanned or recognized pages, **Review checks** shows **Scanned pages to compare**: a small set of pages for a
person to compare, one by one, with the scan.

### How the pages are chosen

Only the run's own record is used (its page classification, the recognition's per-page measurements, the policy `bounded-ocr-review-sample-1`
and the exact result's SHA-256), so the same document always gives the same pages, each with the reason it was chosen.

- **Size.** Documents with up to 3 scanned pages are sampled whole. Larger ones: about one page in five, at least 3 and at most 10.
- **Order of choice.** The pages the recognition read least surely come first (no words found, then too little text, then many unsure
  words, then some), up to half the sample; then the first and the last scanned page; then the page or pages with the most recognized
  words; then the rest are drawn using the result's fingerprint, so the choice cannot be steered.
- A page that qualifies for more than one reason shows every reason.
- A scanned page that has **no text at all in the result** (nothing was recognized and there is no recognition measurement) has nothing to
  compare. It is named in the panel, not sampled, and the existing scanned-text check keeps blocking it until it gets text recognition or
  a clearer source.
- Pages that were only photographs on digital pages are not part of this sample; they stay in the general review of scanned text and
  image meaning.

### What you record

For each sampled page, mark each of three checks as **Pass**, **Problem** or **Not checked**, and write notes (required if you mark a
problem):

1. **The words are accurate.**
2. **Nothing is missing.**
3. **The reading order is right.**

The page picture is next to the recognition's own evidence (how many words it read confidently). You type your own name; machine,
automatic or unnamed labels are refused. A record is bound to the exact PDF, the exact sample and the page.

If you mark a **Problem**: if words are wrong or missing, show the recognized text for that page, correct it, and create a corrected copy to
check again. If part of the scan is cut off, faint or unreadable, **the program cannot recreate the missing content from the page's
pixels**. Get a clearer scan or the original document and process that instead.

### How it gates the review

The required review **Scanned text and image meaning** can be approved only after every sampled page has a record with all three checks
marked Pass. A **Problem** or **Not checked** keeps it from being approved (marking it *blocked* is always allowed). Recording a problem
after approving withdraws that approval. Complete records do not approve the review: a person still approves it, by name, afterwards.

When the PDF or any bound evidence changes, records stop counting. They remain as notes ("kept as notes, not as approval") and do not
carry over to a new result.

### Export and the ledger

The exported review record (`review.json`) carries the sample and the records, each marked `human-entered`. Adding a verification
record to the ledger for a document with scanned pages is refused unless the exported review carries complete records for this exact
sample, and the record keeps them as human-entered evidence. A ledger record still also needs the strict validator result, the supplemental
checks, preservation, the person's other approvals and an actual LMS checker score; nothing here replaces any of those.

### What it does not prove

- The sample is a guide to where to look. A page not in it has not been checked.
- Pass on every sampled page is the reviewer's judgment about those pages only. It is not a measure of accuracy for the document, not a
  statement about accessibility, and not verification.
- Sampling, the recognition's confidence and the page picture are tools for a person; they are never accepted in place of the person.
- A corrected-copy review (a document whose recognized text was already corrected) has no scanned pages left in its own classification, so it
  is not sampled again; the earlier review's records stay with the earlier review.
