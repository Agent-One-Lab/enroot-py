import unittest
from unittest.mock import patch
from enroot.client import EnrootClient, from_env

class TestClient(unittest.TestCase):
    def test_from_env(self):
        client = from_env()
        self.assertIsInstance(client, EnrootClient)

    @patch('enroot.client.run_enroot')
    def test_ping_success(self, mock_run_enroot):
        mock_run_enroot.return_value = "enroot version 1.0.0"
        client = EnrootClient()
        self.assertTrue(client.ping())
        mock_run_enroot.assert_called_once_with(["version"])

    @patch('enroot.client.run_enroot')
    def test_ping_fail(self, mock_run_enroot):
        mock_run_enroot.side_effect = Exception("enroot not found")
        client = EnrootClient()
        self.assertFalse(client.ping())
        mock_run_enroot.assert_called_once_with(["version"])

if __name__ == '__main__':
    unittest.main()
