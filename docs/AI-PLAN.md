# AI plan: local first, on the shared runtime (C8)

**Decided 2026-11-15 in the OpenStage and Prism development lists; recorded here 2026-11-16.** This replaces the "AI architecture proposal"
that `docs/STATUS.md` carried until then (API first, with hosted providers the person chooses, and a local model later). The order is now
the other way round. Nothing in this plan is built beyond what the program already does; the shared runtime it depends on (C8, "the local
AI runtime and assistant server") is agreed in the core's roadmap but not yet specified or scheduled.

## The promise

* **AI is optional.** Every feature of PDF Remediator works with no model. Nothing is slower, hidden or refused because AI is off, and the
  program never asks for it to be switched on.
* **Local by default.** If a person turns AI on, it is a model on their own computer. Nothing leaves the computer unless the person turns
  that on, for that document, after being told what would be sent.
* **A model suggests; a person decides.** A suggestion is a pending draft. A model never writes a PDF object, never sets a language or a
  title or a description by itself, never approves a review item and never sets any other tool's data.
* **Automatic is not human.** The explicitly chosen Auto-fix mode may apply a model's best guess and label it `auto-accepted`. That label is
  never a named person's approval and never counts towards `verified`.

## What exists today

`src/pdf_remediator/assistance.py` is an optional client for a model server that is already running on the same computer. It accepts only
a literal loopback address (`localhost` is pinned to `127.0.0.1` with no name lookup), refuses redirects, credentials in the address,
compressed or oversized replies, and any model the person did not name or that is not installed; it downloads nothing; it records
the model, its settings, the prompt and schema versions and exactly what was sent (`data_sent`) with every value; it caches by exact
context; and a human edit always wins. It has **no** hosted-provider route, no key store and no model download, and `remediator.example.toml`
says no key belongs in configuration. `tests/test_assistance.py` and `tests/test_local_ai_first.py` hold these as tests.

## The plan, in order

1. **Now.** Keep that client as it is. Do not add a hosted provider, an API key field, a model download or a bundled model. (The earlier
   proposal to do so first is withdrawn.)
2. **When the core's C8 is specified.** Read it against `CORE-REQUESTS.md` (C8-1a to C8-2). If it meets them, replace PDF Remediator's own
   model client with C8's, so a person installs a model once for the whole suite. Do this with every existing test of "AI off", "loopback
   only", "pending draft", "human edit wins" and "`auto-accepted` is not a human approval" still passing and none weakened. If C8 cannot meet a
   rule, the rule stays and the program keeps its own client for that part.
3. **After that, and only if the owner decides to.** A hosted provider as an additional choice behind C8, with a per-document opt-in, a
   summary of what would be sent (the kind and amount of content, no sensitive snippets), an estimated cost, bounded retries and spend,
   private credentials held by C8 and not by this program, visible provider and status, and Cancel. Not before the owner asks.

## What AI is used for, and not

| Use | Status |
|---|---|
| A draft document title | exists, optional, pending draft |
| A draft description for a figure, from its picture and nearby text | exists, optional, pending draft |
| Heading suggestions | not built; only after the structured decision and its deterministic application are tested |
| Logo wording, colour-only meaning, wrong-character repair, OCR review | **no model needed**; the deterministic workflows are the product. A model could later offer a draft the person reviews like any other |
| Reading order, table meaning, language, anything that approves | never decided by a model |

## Limits to keep in view

* A model's description of a picture is a guess about the picture. It does not know the document's purpose unless the surrounding text says
  so. It can be fluent and wrong.
* "Local" does not mean private to other programs on the same computer; the loopback server is whatever the person installed.
* A model's output is treated as untrusted data: checked against a schema and the allowed object references, never as an instruction.
* Model weights and runtimes have their own licences. None is bundled, and none will be without a licence review.

## Not authorized by this plan

No hosted account, API key, paid request, external transfer of a document or model download is authorized by writing this down.
