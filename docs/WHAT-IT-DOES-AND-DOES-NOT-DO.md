# What PDF Remediator does and does not do

A plain-language page for the people who will use it. It is written from the project's own status notes; where the notes
say something is not established, this page says so too.

## What it is

PDF Remediator is a helper. It makes a **separate draft copy** of a PDF with accessibility repairs, shows you what it did,
and lists what a person still has to check. **Your original PDF is never changed.**

Nothing it produces is called "verified accessible". A draft is a starting point for a person who reviews it, not a finished,
certified document. It runs on your own computer; your PDFs are not sent anywhere, and no AI service is used unless it has
been switched on.

## What it can help with

- **Ordinary text PDFs** (readings, book chapters): it adds the hidden structure (tags) that screen readers use, and runs strict checks on the result.
- **Scanned pages**: it can read the page pictures (OCR, set up for English) and place the recognised text back on the original page, so the page looks the same.
  - **Pages stored sideways or upside down**: choose that scan layout; it tries the four turns and keeps the one that reads best (slower).
  - **Faint or blurry scans** are read less well. The program lists the pages it was least sure of, and a person should compare the text with those pages.
- **Text that copies out as odd symbols** (fonts with no letter dictionary): it can rebuild the dictionary from a reading of the pages. This is an inference, not a fact, so a person compares the text with the pages.
- **Designed PDFs** with repeated headers, footers and backgrounds: it repairs the structure links that those cause.
- **Review work**: picture descriptions, headings, bookmarks, language, document title, tables, links and reading order are shown as items for a person to finish.

## What it does not do

- It does **not** make a document accessible on its own. A person must still check reading order, picture descriptions, headings, tables and language. The program does not test reading order automatically.
- It does **not** guess picture descriptions. A placeholder such as "image 33" is flagged for a person to replace.
- **Slide decks and equations** are handled manually; choosing those content types tells you so.
- **Fillable forms**: only simple, static form fields are screened. Complex or active forms (scripts, dynamic forms) are not repaired.
- **Complex tables**: there is no general repair; simple tables are checked and the rest are left for a person.
- **Signed or encrypted (password-protected) PDFs**, **damaged PDFs** and **PDF 2.0** files are outside what it supports.
- **Content Credentials** (provenance labels): a file that carries them is refused unless you ask for a separate copy without them and confirm.
- **Reading scanned text in other languages**: the setup is for English. Other languages are not established.
- **Whole books** have been tried only on a made-up test book; expect a very large number of review items.
- **Other computers**: it is built and tried on Windows. Linux and other systems are not established.

## What to expect

- A first scan of a long PDF takes minutes; a scan with sideways-page reading takes longer.
- Every result has a review list. Plan time for a person to go through it. Items marked required are not optional.
- If a result says it needs manual handling, that is the program being careful, not failing: the original had something it could not repair safely.
