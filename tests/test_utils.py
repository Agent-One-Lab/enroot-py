import unittest
from enroot.utils import random_name, parse_list, systemd_prefix
import shutil

class TestUtils(unittest.TestCase):
    def test_random_name(self):
        name = random_name()
        self.assertTrue(name.startswith("cnt-"))
        self.assertEqual(len(name), 12) # "cnt-" + 8 hex chars

        name = random_name(prefix="test")
        self.assertTrue(name.startswith("test-"))
        self.assertEqual(len(name), 13) # "test-" + 8 hex chars

    def test_parse_list_simple(self):
        text = """
        container1
        container2
        """
        parsed = parse_list(text)
        self.assertEqual(list(parsed.keys()), ["container1", "container2"])

    def test_parse_list_fancy(self):
        text = """
NAME      PID       STATE     STARTED      TIME      MNTNS      USERNS    COMMAND
my-cont   12345     running   2 hours ago  0.01s     402653     402653    /bin/bash
        """
        parsed = parse_list(text)
        self.assertIn("my-cont", parsed)
        self.assertEqual(parsed["my-cont"]["pids"], [12345])
        self.assertEqual(parsed["my-cont"]["state"], "running")

    def test_systemd_prefix_no_limits(self):
        self.assertEqual(systemd_prefix(None, None), [])

    @unittest.skipIf(shutil.which("systemd-run") is None, "systemd-run not found")
    def test_systemd_prefix_with_limits(self):
        prefix = systemd_prefix(2, "1G")
        self.assertIn("systemd-run", prefix)
        self.assertIn("CPUQuota=200%", prefix)
        self.assertIn("MemoryMax=1G", prefix)

    @unittest.skipIf(shutil.which("systemd-run") is None, "systemd-run not found")
    def test_systemd_prefix_with_only_cpu(self):
        prefix = systemd_prefix(0.5, None)
        self.assertIn("systemd-run", prefix)
        self.assertIn("CPUQuota=50%", prefix)
        self.assertNotIn("MemoryMax=1G", ' '.join(prefix))
        
    @unittest.skipIf(shutil.which("systemd-run") is None, "systemd-run not found")
    def test_systemd_prefix_with_only_mem(self):
        prefix = systemd_prefix(None, 512)
        self.assertIn("systemd-run", prefix)
        self.assertNotIn("CPUQuota", ' '.join(prefix))
        self.assertIn("MemoryMax=512", prefix)

if __name__ == '__main__':
    unittest.main()
