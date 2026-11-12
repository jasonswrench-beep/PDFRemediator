#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Signs Windows program files with Azure Artifact Signing, and timestamps every signature.

  python tools/sign_windows.py FILE...              sign each file that is not signed yet, then check it
  python tools/sign_windows.py --description TEXT FILE...   the same, with the program name written into the signature
  python tools/sign_windows.py --leave-list LIST FILE...   the same, but a file named in LIST (one place per line, such as
                                                    python/Lib/site-packages/pip/_vendor/distlib/t64.exe) is left unsigned on purpose
  python tools/sign_windows.py --check FILE...      only check: each file must carry a valid signature and a timestamp
  python tools/sign_windows.py --ready              say whether everything signing needs is here, and sign nothing

The same file is used by each OpenStage tool's installer build: for the programs it packs, and, one file at a time through Tauri's
bundle.windows.signCommand or Inno Setup's SignTool, for the program itself, the installer's plugins, the uninstaller and the setup file.
In OpenStage Author, tools/build_installer.py --sign does all of that.

Why the timestamp is not optional: an Artifact Signing certificate is valid for three days. A signature without a timestamp stops validating when its
certificate runs out, so a file is only counted as signed here when its signature is valid AND timestamped.

The account details come from environment variables, so they never go into the repository:
  OPENSTAGE_SIGN_ENDPOINT   the account's regional address, for example https://eus.codesigning.azure.net/
  OPENSTAGE_SIGN_ACCOUNT    the Artifact Signing account's name
  OPENSTAGE_SIGN_PROFILE    the certificate profile's name (a Public Trust profile)
  OPENSTAGE_SIGN_PUBLISHER  optional: the name the signature must show (the verified identity); a file signed by anyone else fails the check
  OPENSTAGE_SIGN_DLIB       optional: Microsoft's Azure.CodeSigning.Dlib.dll (x64), from the NuGet package Microsoft.ArtifactSigning.Client;
                            by default <your folder>\\Tools\\artifact-signing\\bin\\x64\\Azure.CodeSigning.Dlib.dll
  OPENSTAGE_SIGNTOOL        optional: signtool.exe (x64); by default the newest one in the Windows SDK, 10.0.22621 or later
  OPENSTAGE_SIGN_DRY_RUN=1  print the commands instead of running them, and check nothing (for tests)

Signing in: Microsoft's signing library finds the sign-in itself (Azure's DefaultAzureCredential). On a person's own computer that is `az login`,
once; nothing secret is stored by this script.
"""

import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
METADATA = ROOT / "dist" / "signing" / "metadata.json"  # dist/ is not in the repository
TIMESTAMP_URL = "http://timestamp.acs.microsoft.com"  # Microsoft's RFC 3161 timestamp service for Artifact Signing
SDK_BIN = Path(r"C:\Program Files (x86)\Windows Kits\10\bin")
LOWEST_SDK = (10, 0, 22621)  # Microsoft asks for SignTool 10.0.22621.755 or later with its signing library
REFUSED_SDK = (10, 0, 20348)  # "20348 Windows SDK version isn't supported with our dlib" (Microsoft's page)
TRIES = 3
WAITS = (5, 15)  # seconds before the second and the third try
PROGRAM_FILES = (".exe", ".dll", ".pyd")


class SignError(Exception):
    pass


def dry_run():
    return os.environ.get("OPENSTAGE_SIGN_DRY_RUN") == "1"


def settings():
    """The three account details, from the environment. Missing ones are named, so the message says what to set."""
    names = {"Endpoint": "OPENSTAGE_SIGN_ENDPOINT", "CodeSigningAccountName": "OPENSTAGE_SIGN_ACCOUNT", "CertificateProfileName": "OPENSTAGE_SIGN_PROFILE"}
    found = {key: os.environ.get(var, "").strip() for key, var in names.items()}
    missing = [names[key] for key, value in found.items() if not value]
    if missing:
        raise SignError("these are not set: " + ", ".join(missing) + ". They name the Artifact Signing account (see the top of tools/sign_windows.py).")
    if not re.fullmatch(r"https://[a-z0-9]+\.codesigning\.azure\.net/?", found["Endpoint"]):
        raise SignError(f"OPENSTAGE_SIGN_ENDPOINT should look like https://eus.codesigning.azure.net/ (it is {found['Endpoint']!r}).")
    return found


def write_metadata():
    METADATA.parent.mkdir(parents=True, exist_ok=True)
    METADATA.write_text(json.dumps(settings(), indent=2) + "\n", encoding="utf-8")
    return METADATA


def sdk_version(path):
    """The Windows SDK version a signtool.exe belongs to, from its folder name (...\\bin\\10.0.26100.0\\x64\\signtool.exe), or None."""
    for part in Path(path).parts:
        if re.fullmatch(r"\d+\.\d+\.\d+\.\d+", part):
            return tuple(int(n) for n in part.split("."))
    return None


def usable_sdk(version):
    return version is not None and version[:3] >= LOWEST_SDK and version[:3] != REFUSED_SDK


def find_signtool():
    chosen = os.environ.get("OPENSTAGE_SIGNTOOL")
    if chosen:
        if not Path(chosen).is_file():
            raise SignError(f"OPENSTAGE_SIGNTOOL names a file that is not there: {chosen}")
        return Path(chosen)
    found = sorted((p for p in SDK_BIN.glob("*/x64/signtool.exe") if usable_sdk(sdk_version(p))), key=sdk_version)
    if not found:
        raise SignError("no signtool.exe from Windows SDK 10.0.22621 or later was found (an older one does not work with Microsoft's signing library). "
                        "Install the Windows SDK, or set OPENSTAGE_SIGNTOOL.")
    return found[-1]


def find_dlib():
    chosen = os.environ.get("OPENSTAGE_SIGN_DLIB")
    path = Path(chosen) if chosen else Path.home() / "Tools" / "artifact-signing" / "bin" / "x64" / "Azure.CodeSigning.Dlib.dll"
    if not path.is_file():
        raise SignError(f"Microsoft's signing library is not at {path}. It comes in the NuGet package Microsoft.ArtifactSigning.Client (bin\\x64); "
                        "set OPENSTAGE_SIGN_DLIB if it is somewhere else.")
    return path


def sign_command(signtool, dlib, metadata, path, description=None):
    command = [str(signtool), "sign", "/v", "/fd", "SHA256", "/tr", TIMESTAMP_URL, "/td", "SHA256", "/dlib", str(dlib), "/dmdf", str(metadata)]
    if description:
        command += ["/d", description]
    return command + [str(path)]


def timestamp_command(signtool, path):
    """Adds the timestamp to a file that was signed but not timestamped (it does not sign again)."""
    return [str(signtool), "timestamp", "/tr", TIMESTAMP_URL, "/td", "SHA256", str(path)]


# Windows' own check of each file (the same one File Properties > Digital Signatures shows), in one PowerShell for all the files. The paths go in
# through the environment, so no quoting of a path can go wrong.
_CHECK_SCRIPT = (
    "$ErrorActionPreference = 'Stop'; "
    "$paths = $env:OPENSTAGE_SIGN_PATHS | ConvertFrom-Json; "
    "$out = foreach ($p in $paths) { "
    "  $s = Get-AuthenticodeSignature -LiteralPath $p; "
    "  $name = $null; if ($s.SignerCertificate) { $name = $s.SignerCertificate.GetNameInfo([System.Security.Cryptography.X509Certificates.X509NameType]::SimpleName, $false) }; "
    "  [pscustomobject]@{ path = $p; status = [string]$s.Status; signer = $name; timestamped = [bool]$s.TimeStamperCertificate } "
    "}; "
    "ConvertTo-Json -InputObject @($out) -Compress"
)


def signatures(paths):
    """For each file: {path, status ('Valid', 'NotSigned', ...), signer (the certificate's name or None), timestamped}."""
    paths = [str(Path(p).resolve()) for p in paths]
    if not paths:
        return []
    env = dict(os.environ, OPENSTAGE_SIGN_PATHS=json.dumps(paths))
    done = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", _CHECK_SCRIPT], capture_output=True, text=True, encoding="utf-8", env=env)
    if done.returncode != 0:
        raise SignError("Windows could not read the signatures:\n" + done.stdout + done.stderr)
    return json.loads(done.stdout)


def problem(info, publisher=None):
    """Why a file does not count as signed here, or None when it does."""
    if info["status"] != "Valid":
        return "not signed" if info["status"] == "NotSigned" else f"signature not valid ({info['status']})"
    if not info["timestamped"]:
        return "signed but not timestamped (it would stop validating when its three-day certificate runs out)"
    if publisher and info["signer"] != publisher:
        return f"signed by {info['signer']!r}, not {publisher!r}"
    return None


def read_leave_list(path):
    """The places in a list of files to leave unsigned: one per line, with / between folders; empty lines and lines starting with # do not count."""
    entries = []
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        line = line.strip().replace("\\", "/").strip("/")
        if line and not line.startswith("#"):
            entries.append(line)
    return entries


def left_on_purpose(path, entries):
    """Whether a file is one of the places in the list: its full path ends with the place (whole folder names only)."""
    full = "/" + str(Path(path).resolve()).replace("\\", "/").strip("/")
    return any(full.lower().endswith("/" + entry.lower()) for entry in entries)


def run(command):
    if dry_run():
        print("would run: " + subprocess.list2cmdline(command), flush=True)
        return 0, ""
    done = subprocess.run(command, capture_output=True, text=True, encoding="utf-8", errors="replace")
    return done.returncode, done.stdout + done.stderr


def sign_one(path, signtool, dlib, metadata, description=None, publisher=None):
    """Signs and timestamps one file, trying again when the service does not answer. Returns what was done, in words."""
    if dry_run():
        run(sign_command(signtool, dlib, metadata, path, description))
        return "signed (dry run)"
    before = signatures([path])[0]
    if before["status"] == "Valid":
        if before["timestamped"]:
            return f"already signed by {before['signer']}, left as it is"
        if publisher and before["signer"] != publisher:
            raise SignError(f"{path} is signed by {before['signer']!r} without a timestamp; it is not ours to change.")
    log = ""
    for attempt in range(1, TRIES + 1):
        info = signatures([path])[0]
        if info["status"] == "Valid" and not info["timestamped"]:
            code, out = run(timestamp_command(signtool, path))  # signed, but the timestamp did not come: add only that
        elif info["status"] != "Valid":
            code, out = run(sign_command(signtool, dlib, metadata, path, description))
        else:
            code, out = 0, ""
        log += out
        info = signatures([path])[0]
        why = problem(info, publisher)
        if why is None:
            return "signed and timestamped"
        if attempt < TRIES:
            time.sleep(WAITS[attempt - 1])
    raise SignError(f"{path} was not signed: {why}.\nWhat signtool said:\n{log.strip()}")


def ready():
    """Everything signing needs, each with whether it is here. Signs nothing and asks Azure nothing."""
    lines, ok = [], True

    def note(good, text):
        nonlocal ok
        ok = ok and good
        lines.append(("  ok      " if good else "  MISSING ") + text)

    try:
        values = settings()
        note(True, f"account {values['CodeSigningAccountName']}, profile {values['CertificateProfileName']}, at {values['Endpoint']}")
    except SignError as e:
        note(False, str(e))
    for label, finder in (("signtool", find_signtool), ("Microsoft's signing library", find_dlib)):
        try:
            note(True, f"{label}: {finder()}")
        except SignError as e:
            note(False, str(e))
    try:
        runtimes = subprocess.run(["dotnet", "--list-runtimes"], capture_output=True, text=True, encoding="utf-8").stdout
        note("Microsoft.NETCore.App 8." in runtimes, ".NET 8 runtime (the signing library needs it)")
    except OSError:
        note(False, ".NET 8 runtime (the signing library needs it): dotnet was not found")
    return ok, lines


def main(argv):
    args = list(argv)
    if args == ["--ready"]:
        ok, lines = ready()
        print("Signing needs:\n" + "\n".join(lines))
        return 0 if ok else 1
    check_only = "--check" in args
    if check_only:
        args.remove("--check")
    description = None
    if "--description" in args:
        at = args.index("--description")
        if at + 1 >= len(args):
            print("--description needs the text after it.")
            return 2
        description = args[at + 1]
        del args[at:at + 2]
    leave = []
    if "--leave-list" in args:
        at = args.index("--leave-list")
        if at + 1 >= len(args) or not Path(args[at + 1]).is_file():
            print("--leave-list needs the file that lists what to leave unsigned after it.")
            return 2
        leave = read_leave_list(args[at + 1])
        del args[at:at + 2]
    if not args:
        print(__doc__)
        return 2
    files = [Path(a) for a in args]
    for f in files:
        if not f.is_file():
            print(f"There is no file at {f}.")
            return 1
    publisher = os.environ.get("OPENSTAGE_SIGN_PUBLISHER") or None
    try:
        if check_only:
            bad = [(info["path"], problem(info, publisher)) for info in signatures(files)]
            bad = [(p, why) for p, why in bad if why]
            for p, why in bad:
                print(f"{p}: {why}")
            if not bad:
                print(f"All {len(files)} signed and timestamped.")
            return 1 if bad else 0
        kept = [f for f in files if left_on_purpose(f, leave)]
        for f in kept:
            # Tauri's bundler offers every unsigned program among the bundled files; the ones in the list are declined here.
            print(f"{f.name}: left unsigned on purpose", flush=True)
        files = [f for f in files if f not in kept]
        if not files:
            return 0
        signtool, dlib, metadata = find_signtool(), find_dlib(), write_metadata()
        for f in files:
            print(f"{f.name}: {sign_one(f, signtool, dlib, metadata, description, publisher)}", flush=True)
        return 0
    except SignError as e:
        print("Signing stopped: " + str(e), flush=True)
        return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
