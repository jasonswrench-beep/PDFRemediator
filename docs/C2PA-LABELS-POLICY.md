# Content Credentials (C2PA) files: what the program does

This page describes what the program does today with PDFs that carry Content Credentials (C2PA provenance labels). It is the working policy; the
project owner can change it.

## The rule

1. **The original is never changed.** A PDF that carries Content Credentials is protected: ordinary Fix and OCR refuse it rather than quietly
   dropping or breaking the credential.
2. **Removal is a separate, deliberate action.** On a review of such a file, "Create separate copy without credentials and recheck" makes a new working
   copy after you tick an explicit removal choice and name the reviewer. The unchanged original, the exact credential payload, your consent and the
   proof of what was removed are kept with the review.
3. **The copy starts fresh.** It has a new source identity, carries no old accessibility approvals, and starts a new review with AI and OCR off. All pages,
   text, links and bookmarks must remain exactly as in the original before the copy is accepted.
4. **No claims about the credential.** The program does not verify the credential, its signer or its claims, does not re-sign anything, and never says a
   copy is authentic. A copy without credentials is a different file.

## What is covered

The first supported case is one unfiltered C2PA-associated file with no extra attachment, alias, signature, active action or unproved metadata claim.
Other attachments stay guarded and the file is refused. Ordinary link destinations are kept without being run. There is no general attachment stripping.

## For a person using it

Keep the original file. If the label matters (for example for provenance), decide before making the copy whether a copy without it is acceptable
for your purpose. Using the copy for accessibility work does not make the original less authentic; it is simply not the same file.
