"""Native prerequisites: never silently skip or emulate a missing pinned JAR.

Select an explicit Linux runtime TOML with PDF_REMEDIATOR_NATIVE_CONFIG.
Absent configuration retains the prepared-machine defaults and fails if missing.
This identity check alone does not qualify end-to-end native processing.
"""
import os
from pdf_remediator.config import load_config
from pdf_remediator.doctor import odl_identity, resolve_tools


def test_local_jar_identity_comes_from_actual_artifact():
    config = load_config(os.environ.get("PDF_REMEDIATOR_NATIVE_CONFIG"))
    result = odl_identity(resolve_tools(settings=config)["odl_jar"])
    assert result["status"] == "available"
    assert result["version"] == "2.5.13"
    assert len(result["sha256"]) == 64

