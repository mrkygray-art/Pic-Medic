import unittest
from dashboard import DEMO, answer, get_report
from analyze import analyze
class TestV13(unittest.TestCase):
 def test_demo_findings(self):
  self.assertTrue(analyze(DEMO)['findings'])
 def test_guidance(self):
  self.assertIn('Memory snapshot',answer('why is my pc slow',DEMO)['answer'])
 def test_demo_report(self):
  self.assertEqual(get_report(True)['platform'],'Windows')
if __name__=='__main__':unittest.main()
