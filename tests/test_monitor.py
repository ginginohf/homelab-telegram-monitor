import unittest
from bot import Bot,authorized,cpu_percent
from gpu_metrics import GpuSampler
class Tests(unittest.TestCase):
 def test_access(self):
  m={'from':{'id':42},'chat':{'id':42,'type':'private'}}
  self.assertTrue(authorized(m,42));self.assertFalse(authorized(m,43));m['chat']['type']='group';self.assertFalse(authorized(m,42))
 def test_thresholds(self):
  b=Bot.__new__(Bot);b.state={};sent=[];b.send=sent.append;b.update=lambda **v:b.state.update(v)
  for value,t in [(95,1),(96,2),(99,12),(None,22),(94,32)]:b.check_resource_alerts({'gpu':value},t)
  self.assertEqual(len(sent),1);b.check_resource_alerts({'gpu':90},42);self.assertEqual(len(sent),2)
 def test_pmu(self):
  self.assertEqual(GpuSampler.percent((0,0,0),(48,100,50)),96)
  self.assertIsNone(GpuSampler.percent((0,0,0),(0,0,0)))
 def test_redaction_no_proxy(self):
  b=Bot.__new__(Bot);b.config={'token':'synthetic-test-value','proxy':''};self.assertEqual(b.redact('hello'),'hello')
