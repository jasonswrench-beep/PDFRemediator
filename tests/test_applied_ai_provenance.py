"""Accepted AI attribution stays portable while processing performs no inference."""
import json
from pathlib import Path
from pdf_remediator import pipeline
from pdf_remediator.config import RuntimeConfig
from pdf_remediator.sidecar import bind_approval,write_sidecar
from test_pipeline import input_pdf, fast_validator, tagged_control


def test_accepted_prior_draft_is_attributed_in_the_new_pdf_bundle(input_pdf,tmp_path,fast_validator):
    config=RuntimeConfig();prior=pipeline.process_file(input_pdf,tmp_path/'first',config)
    decisions=json.loads((Path(prior['bundle_path'])/'decisions.json').read_text())
    title=next(item for item in decisions['decisions'] if item['kind']=='title')
    title['value']='A synthetic title used by an explicit attribution regression'
    origin={'schema_version':'phase2-ai-origin-1','suggestion_id':'fixture-only','model':'TEST STUB: no actual inference',
        'provider':'local-test-fixture','context_sha256':title['context_sha256']}
    title['ai_origin']=origin;bind_approval(title,'Synthetic fixture test author','2026-10-16')
    sidecar=tmp_path/'accepted.json';write_sidecar(decisions,sidecar)
    report=pipeline.process_file(input_pdf,tmp_path/'next',config,sidecar=sidecar,decision_bundle=prior['bundle_path'])
    assert report['status']=='candidate' and report['data_sent']['document_api_calls']==0
    assert report['data_sent']['prior_assistance']==[{'decision_id':title['id'],'origin':origin}]
    saved=json.loads((Path(report['bundle_path'])/'decisions.json').read_text())
    assert next(item for item in saved['decisions'] if item['id']==title['id'])['ai_origin']==origin
    assert pipeline.verify_bundle(report['bundle_path'])
