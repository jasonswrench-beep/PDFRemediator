# Fresh-PC install test and publisher signing

Both of these need a person and a computer that is not the development PC, or the owner's sign-in to the signing service. Nothing here was run
by the program's test suite. Tick each box in `TESTING-TODO.md` only after doing it, with the date and who did it.

## 1. Fresh-PC install test

**Purpose.** Show that a person who has never seen the program can install it, open it, process one PDF and remove it, on a Windows
computer that has none of the development tools. The development PC and the first spare PC already have Microsoft's Visual C++
Redistributable and the Edge WebView2 Runtime, so they cannot show what a truly bare PC does.

**What counts as "fresh".** A computer, or a virtual machine restored from a snapshot, with a clean 64-bit Windows 10 or 11, no Python,
no Java, no Visual Studio, no previous copy of PDF Remediator, and the installing person signed in as an ordinary (non-administrator) user.
Record which of these is true on the day; a virtual machine counts only if it was restored from a snapshot taken before anything was installed.

**Before you start (on the development PC).**

1. Take the installer from the build you intend to give out. Record its name and SHA-256
   (`Get-FileHash "<installer>.exe"`).
2. Copy the installer and one ordinary text PDF to the fresh PC with a USB stick or a network folder. Do not email them or upload them.

**Run, in order. Write down what you see at every step; a surprise is a result, not a mistake.**

| # | Do | What should happen | Seen |
|---|---|---|---|
| 1 | Check the hash of the installer on the fresh PC. | It matches the recorded value. | |
| 2 | Open the installer. | The screen Windows shows: a SmartScreen box, a signature line, or nothing. Write down the publisher name it shows. | |
| 3 | If Microsoft's Visual C++ Redistributable is missing: read the message. | The installer says what is missing and offers Microsoft's page. It downloads nothing. | |
| 4 | Install into a new folder (the suggested name is fine). | "Installed" and a folder with `PDF Remediator.exe`. No administrator prompt is needed for a folder in your own profile. | |
| 5 | If WebView2 is missing (older Windows 10): open `PDF Remediator.exe`. | A plain message that Microsoft's WebView2 Runtime is needed, with Microsoft's page. | |
| 6 | Open `PDF Remediator.exe`. | The program's own window opens in 10 to 20 seconds. Note any firewall question exactly as worded before answering. | |
| 7 | Choose the PDF, leave the options alone, press Process. | A finished result or a review draft with plain-words status. | |
| 8 | Close the window. Look in Task Manager. | Nothing from PDF Remediator is left running. | |
| 9 | Open the program again, then end it from Task Manager (not Stop), then open it a third time. | It recovers from the stale session file. | |
| 10 | Uninstall from Settings > Apps, once keeping saved reviews and once deleting them (on a second install). | The program files are gone; saved reviews stay or go as chosen. | |

**Record (copy into the evidence note):** date; person; computer or virtual machine, Windows edition and build number; which of the
prerequisites were missing at the start; installer name and SHA-256; the SmartScreen/signature text word for word; every message seen;
anything that took more than one attempt; the person's own words about what confused them.

**Pass.** Steps 4, 6, 7, 8 and 10 behave as written on a computer that really lacked the Redistributable or WebView2 (at least once each, or the
box stays open in `TESTING-TODO.md`), and nothing needed the development tools. A step that only worked after help is a finding, not a pass.

## 2. Third-party notices

The notice file is `THIRD-PARTY-NOTICES.md`; its "Still to do" list is the checklist. Items that are the owner's or a reviewer's to do are
in `TESTING-TODO.md`: counsel's review, the WebView2 SDK licence text, and a recheck of each licence on the day of release.

## 3. Signing the installer and the program files

**What it does.** `scripts/package-windows.py --sign` signs every program file in the package, the uninstaller and the installer through
`scripts/sign_windows.py`, with a trusted timestamp. A signature proves who published the file and that it has not changed since; it does
not say the program is safe or accessible, and Windows SmartScreen still builds its reputation for a new publisher over time.

**Makers' signatures are kept.** A program its makers already signed keeps that signature, including one that Windows no longer calls
Valid because the maker's certificate has expired (it shows as `UnknownError`). Replacing such a signature is not harmless: in alpha 8 and
alpha 9 the build replaced the signatures on `tesseract.exe` and `libtesseract-5.dll` (Universität Mannheim), and the re-signed
`tesseract.exe` returned exit code 0 with no output on about 1 to 3 percent of launches, so scanned-page OCR failed at random. Only a file
with no signature at all, one whose signature no longer matches the file (`HashMismatch`), or one with an invalid signature of ours is
signed by the build. The files kept are listed in `build-summary.json` as `makers_signatures_kept_not_validating_now` (for the current
locked inputs: exactly those two Tesseract files). `ArtifactSigner.sign_programs` in `scripts/package-windows.py` does this; `sign_windows.py`
itself is unchanged because the other OpenStage tools share it.

**What the owner needs.** A verified publisher identity at the signing service, `signtool.exe` from the Windows SDK (10.0.22621 or later),
Microsoft's signing library, the .NET 8 runtime, and a sign-in. The account details are kept outside the repository (`dist/` is not
tracked); they are passed in the environment variables `OPENSTAGE_SIGN_ENDPOINT`, `OPENSTAGE_SIGN_ACCOUNT` and `OPENSTAGE_SIGN_PROFILE`.

**Steps (a person does these; the sign-in cannot be done by the program).**

```powershell
# 1. See what is missing; this signs nothing.
python scripts/sign_windows.py --ready
# 2. Sign in once (a browser opens).
az login
# 3. Name the account (values from the owner's own record; do not commit them).
$env:OPENSTAGE_SIGN_ENDPOINT  = "<the account's regional address>"
$env:OPENSTAGE_SIGN_ACCOUNT   = "<account name>"
$env:OPENSTAGE_SIGN_PROFILE   = "<Public Trust certificate profile name>"
$env:OPENSTAGE_SIGN_PUBLISHER = "<the name the signature must show>"
# 4. Make the input plan once (scripts/make-windows-plan.py, see docs/WINDOWS-DISTRIBUTION.md), then build with signing.
#    Run the builder as an ordinary script (not python -I): it imports sign_windows from beside itself.
python scripts/package-windows.py --inputs <plan file> --output <new folder> --sign
# 5. Check every file the installer carries and the installer itself.
python scripts/sign_windows.py --check "<installer>.exe" "<folder>\PDF Remediator.exe"
# 6. After installing (or on the build's payload folder): the bundled Tesseract must start and answer every time. Use the .NET Process
#    class; Start-Process -PassThru in Windows PowerShell 5.1 loses the exit code. Expect 0 failures out of 400.
$exe = "<install folder>\runtime\tesseract\tesseract.exe"; $failed = 0
1..400 | ForEach-Object {
  $psi = New-Object Diagnostics.ProcessStartInfo $exe, '--version'
  $psi.RedirectStandardOutput = $psi.RedirectStandardError = $true; $psi.UseShellExecute = $false; $psi.CreateNoWindow = $true
  $p = [Diagnostics.Process]::Start($psi); $o = $p.StandardOutput.ReadToEndAsync(); $e = $p.StandardError.ReadToEndAsync(); $p.WaitForExit()
  if ($p.ExitCode -ne 0 -or ($o.Result + $e.Result) -notmatch 'tesseract') { $failed++ } }
"$failed of 400 launches failed"
```

**Verify by hand.** On a computer that did not build it: right-click the installer, Properties, Digital Signatures: one signature, the
expected publisher name, "This digital signature is OK", and a timestamp. Install, then check `PDF Remediator.exe` and the uninstaller the
same way. Record the publisher text exactly and compare it with the name on the signing account.

**Record:** date; person; build name; installer SHA-256 before and after signing; the output of step 5; what SmartScreen showed on the fresh PC
(section 1, step 2).

**Not covered here.** Making a signing account, choosing the publisher's legal name, paying for it and any renewal are the owner's decisions.
Until the box in `TESTING-TODO.md` is ticked, builds are unsigned and `docs/WINDOWS-DISTRIBUTION.md` keeps saying so.
