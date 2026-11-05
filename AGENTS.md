# PDF Remediator development

Read HANDOFF.md before changing the project. This repository contains the source
backup and development instructions. Local PDF inputs, review workspaces, native
tools, model weights, and full trial evidence are deliberately excluded.

- Keep originals unchanged and publish results into separate immutable bundles.
- Preserve strict validation, supplemental checks, and page fidelity requirements.
- Distinguish automatic choices from named human approval and verified status.
- Protect saved human edits, explicit consent, current revisions, and source bindings.
- Never commit passwords, API keys, session URLs/tokens, private PDFs, document
  extracts/crops, runtime logs, or review states. Retain the Git allowlist.
- Phase 3 actual-user, assistive-technology acceptance, and LMS checker testing
  remains deferred until the user authorizes it.
- For cloud development, use scripts/setup-cloud.sh and scripts/test-cloud.py.
  The portable contract subset is not the prepared Windows full-suite/native proof.
  Do not weaken assertions or describe excluded-fixture failures as successful tests.
- Keep HANDOFF.md current with run commands, tested scope, limitations, and next steps.
