"""Fail-closed validator parser regressions, including bounded detail reports."""
import json
from pathlib import Path
import tempfile
import unittest

from validate import parse_json_report, parse_xml_report


class ValidatorReports(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.directory=Path(self.temp.name)
        self.addCleanup(self.temp.cleanup)

    def xml(self, failed=3, listed=1, compliant='false', profile='PDF/UA-1 validation profile'):
        rules=(f'<rule specification="ISO 14289-1:2014" clause="7.4.2" testNumber="1" status="failed" failedChecks="{failed}">'
               + '<check status="failed"><context>known context</context></check>'*listed+'</rule>') if failed else ''
        value=(f'<report><buildInformation><releaseDetails id="core" version="1.30.3"/></buildInformation>'
               f'<jobs><job><item><name>control.pdf</name></item><validationReport jobEndStatus="normal" profileName="{profile}" isCompliant="{compliant}">'
               f'<details passedRules="105" failedRules="{int(bool(failed))}" passedChecks="100" failedChecks="{failed}">{rules}</details>'
               '</validationReport></job></jobs><batchSummary totalJobs="1" failedToParse="0" encrypted="0" outOfMemory="0" veraExceptions="0">'
               f'<validationReports compliant="{int(compliant=="true")}" nonCompliant="{int(compliant!="true")}" failedJobs="0">1</validationReports>'
               '</batchSummary></report>')
        path=self.directory/'report.xml';path.write_text(value,encoding='utf-8');return path

    def test_partial_detail_with_nonzero_failures_is_fail_with_warning(self):
        report=parse_xml_report(self.xml())
        self.assertEqual(report['status'],'fail')
        self.assertEqual(report['counts']['failedChecks'],3)
        self.assertEqual(report['assertion_detail_coverage']['status'],'partial')
        self.assertEqual(report['assertion_detail_coverage']['listed_failed_checks'],1)
        self.assertTrue(report['warnings'])

    def test_no_listed_detail_does_not_erase_failure(self):
        report=parse_xml_report(self.xml(listed=0))
        self.assertEqual(report['status'],'fail')
        self.assertEqual(report['assertion_detail_coverage']['assertions_without_separate_listed_detail'],3)

    def test_true_flag_with_nonzero_failure_counts_is_error(self):
        with self.assertRaises(ValueError):parse_xml_report(self.xml(compliant='true'))

    def test_zero_failure_report_is_pass_without_warning(self):
        report=parse_xml_report(self.xml(failed=0,listed=0,compliant='true'))
        self.assertEqual(report['status'],'pass')
        self.assertEqual(report['warnings'],[])

    def test_more_listed_details_than_assertion_count_is_error(self):
        with self.assertRaises(ValueError):parse_xml_report(self.xml(failed=1,listed=2))

    def test_wrong_profile_is_error(self):
        with self.assertRaises(ValueError):parse_xml_report(self.xml(profile='PDF/A-1b validation profile'))

    def test_missing_report_is_error(self):
        with self.assertRaises(FileNotFoundError):parse_xml_report(self.directory/'missing.xml')

    def test_partial_json_detail_still_fails(self):
        value={'report':{'buildInformation':{'releaseDetails':[{'id':'core','version':'1.30.3'}]},
            'jobs':[{'itemDetails':{'name':'control.pdf'},'validationResult':[{'jobEndStatus':'normal',
                'profileName':'PDF/UA-1 validation profile','compliant':False,'details':{
                    'passedRules':105,'failedRules':1,'passedChecks':100,'failedChecks':3,
                    'ruleSummaries':[{'specification':'ISO 14289-1:2014','clause':'7.4.2','testNumber':1,
                        'status':'failed','failedChecks':3,'checks':[{'status':'failed','context':'known context'}]}]}}]}],
            'batchSummary':{'totalJobs':1,'failedParsingJobs':0,'failedEncryptedJobs':0,'outOfMemory':0,'veraExceptions':0,
                'validationSummary':{'failedJobCount':0,'compliantPdfaCount':0,'nonCompliantPdfaCount':1}}}}
        path=self.directory/'report.json';path.write_text(json.dumps(value),encoding='utf-8')
        report=parse_json_report(path)
        self.assertEqual(report['status'],'fail')
        self.assertEqual(report['assertion_detail_coverage']['status'],'partial')
        self.assertEqual(report['counts']['failedChecks'],3)


if __name__=='__main__':unittest.main()
