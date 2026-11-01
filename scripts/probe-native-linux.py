"""Reproduce a bounded native tagging/preservation probe; not qualification.

Requires explicit Linux TOML paths and a preinstalled pinned ODL JAR. No tools
are downloaded, no OCR or models run, and no candidate/verification is published.
The strict validator remains mandatory for a separate end-to-end qualification.
"""
from pathlib import Path
import argparse
import importlib.util
import json
import platform
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from pdf_remediator.checks import assess
from pdf_remediator.config import load_config
from pdf_remediator.doctor import odl_identity, sha
from pdf_remediator.engines import tag
from pdf_remediator.inspection import compare_fidelity, inspect_pdf
from pdf_remediator.preservation import preserve_painting
from pdf_remediator.processors import normalize_catalog


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if sys.platform != "linux":
        parser.error("This bounded probe is for Linux; prepared Windows evidence remains separate.")
    config = load_config(args.config)
    if config.ocr_mode != "off":
        parser.error("OCR must remain off for this probe.")
    identity = odl_identity(config.odl_jar)
    if identity["status"] != "available":
        parser.error("Pinned ODL JAR unavailable: " + identity["status"])
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    result = {"scope": "native-tagging-preservation-probe-only", "qualified": False,
              "candidate_published": False, "human_verified": False,
              "strict_validation": "not-run; required separately", "ocr": "off", "ai": "off",
              "python": platform.python_version(), "platform": platform.platform(),
              "odl_identity": identity, "status": "failed"}

    def save(name, value):
        (output / name).write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")

    try:
        spec = importlib.util.spec_from_file_location("native_probe_corpus", ROOT / "eval/build_corpus.py")
        corpus = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(corpus)
        result["font_provenance"] = corpus.register_fonts(output)
        source = output / "simple.pdf"
        corpus.simple(source)
        original_sha = sha(source)
        engine = output / "engine.pdf"
        tagging = tag(source, engine, config, output / "tag")
        save("tag-result.json", tagging)
        if tagging["status"] != "completed":
            raise RuntimeError("Native tagging did not complete: " + tagging["status"])
        preserved = output / "preserved.pdf"
        preservation = preserve_painting(source, engine, preserved)
        save("preservation.json", preservation)
        if preservation["status"] != "pass":
            raise RuntimeError("Preservation refused: " + preservation["status"])
        normalized = output / "normalized.pdf"
        save("normalization.json", normalize_catalog(preserved, normalized))
        fidelity = compare_fidelity(source, normalized)
        save("fidelity.json", fidelity)
        supplemental = assess(inspect_pdf(normalized))
        save("supplemental.json", supplemental)
        if fidelity["status"] != "pass" or supplemental["status"] != "pass":
            raise RuntimeError("Fidelity or supplemental gate failed")
        if sha(source) != original_sha:
            raise RuntimeError("Original source changed")
        result.update(status="preflight-completed", original_sha256=original_sha,
                      assessed_sha256=sha(normalized), original_unchanged=True,
                      all_pages_compared=len(fidelity["pages"]))
    except Exception as exc:
        result["error"] = {"type": type(exc).__name__, "message": str(exc)}
        raise
    finally:
        save("probe-result.json", result)
    print("Native preflight completed; strict validation and qualification remain outstanding.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
