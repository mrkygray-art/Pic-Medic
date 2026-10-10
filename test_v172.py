import unittest
from ai_engine import sanitize_investigation
class TestInvestigation(unittest.TestCase):
 def test_allowlist(self):
  r=sanitize_investigation({'performance_samples':[{'cpu_percent':20,'process_name':'secret','memory_used_percent':69,'pid':42}]})
  self.assertEqual(r['performance_samples'],[{'cpu_percent':20,'memory_used_percent':69}])
 def test_reject_oversized(self):
  with self.assertRaises(ValueError):sanitize_investigation({'performance_samples':[{}]*21})
 def test_missing(self):self.assertIsNone(sanitize_investigation(None))
if __name__=='__main__':unittest.main()
