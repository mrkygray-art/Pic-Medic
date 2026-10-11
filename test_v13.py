import unittest
from dashboard import DEMO, get_report
from analyze import analyze
class TestV13(unittest.TestCase):
 def test_demo_findings(self):
  self.assertTrue(analyze(DEMO)['findings'])
 def test_demo_report(self):
  self.assertEqual(get_report(True)['platform'],'Windows')
if __name__=='__main__':unittest.main()
