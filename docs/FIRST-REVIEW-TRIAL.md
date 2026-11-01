# First-review trial: one document, start to finish

Private. For one colleague (not the developer) to try the review screen on one real document while someone watches and
takes notes. Nothing here makes a document accessible; the point is to find where a first-time reviewer gets stuck.

## Before the trial (about 5 minutes, done by the person running it)
1. Process the document with the options it needs (see `REPAIR-OPTIONS.md`), for example `fix document.pdf -o results --title "Real title" --lang en-US --remove-cidset`.
2. Start the review app (`serve --import-bundle <the result folder>`), open the address it prints, and leave the first screen showing "Your documents".
3. Start a stopwatch. Do not explain the screen; answer only "what would you do next?".

## What the reviewer is asked to do
1. Open the document. (Note: how long until the review appears, and whether they clicked again while waiting.)
2. Say, in their own words, what the "What still needs attention" box is telling them.
3. Type their name where the screen asks for it.
4. Give the first three figures a real description. For each, use "Show this picture" to see which image it is. (Note: did they find the picture without help? Did they understand "Save edit" versus "Accept this value"?)
5. Mark one figure that is only decoration as decorative, if there is one.
6. Choose "Apply accepted edits". (Note: did they understand what would happen? How long did it take?)
7. Read the result's checks. Say which ones they could finish alone and which ones they would hand to someone else.

## What the person watching writes down
- Time to open the review the first time; time to open it again.
- Every moment the reviewer stopped, re-read, or said "what does that mean?", with the exact words on screen.
- Any button they expected that was not there, and any they never noticed.
- Whether they trusted the result enough to send it on, and why or why not.

## What this trial cannot show
It does not show that the document is accessible. A screen-reader pass (NVDA, run only when the owner is away) and checks
by people who use assistive technology are separate steps.
