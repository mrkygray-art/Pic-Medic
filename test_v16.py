import unittest
from unittest.mock import patch
import ai_engine
from dashboard import DEMO

class TestV16(unittest.TestCase):
    def test_sanitization(self):
        report={**DEMO, 'checks':{**DEMO['checks'], 'os':{'status':'ok','data':{'Caption':'SecretDevice','Version':'10'}}, 'recent_system_events':{'status':'ok','data':[{'Id':20,'ProviderName':'Test','Message':'SECRET_EVENT_TEXT'}]}}}
        summary=str(ai_engine.safe_summary(report))
        self.assertNotIn('SecretDevice',summary)
        self.assertNotIn('SECRET_EVENT_TEXT',summary)
    def test_claude_is_not_served_here(self):
        # Claude questions go through assistant.py; ai_engine is only the ChatGPT fallback.
        with self.assertRaises(ValueError):ai_engine.ask('claude','Why is memory high?',DEMO,True)
    def test_missing_key(self):
        with patch.dict('os.environ',{},clear=True):
            with self.assertRaisesRegex(RuntimeError,'OPENAI_API_KEY'):
                ai_engine.ask('openai','Why is memory high?',DEMO,True)
    def test_provider_switch(self):
        with patch.dict('os.environ',{'OPENAI_API_KEY':'test-key'},clear=True):
            with patch('ai_engine.post',return_value={'output':[{'type':'message','content':[{'type':'output_text','text':'Evidence is insufficient'}]}]}) as call:
                answer=ai_engine.ask('openai','Check memory',DEMO,True)
                self.assertEqual(answer['answer'],'Evidence is insufficient')
                self.assertTrue(call.called)
if __name__=='__main__':unittest.main()
