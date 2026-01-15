import unittest
from unittest.mock import patch, MagicMock, call
from enroot.container import Containers, Container
from enroot.client import EnrootClient
from enroot import ENROOT_HOME
import pathlib
import subprocess

class TestContainers(unittest.TestCase):
    def setUp(self):
        self.client = EnrootClient()
        self.containers = Containers(self.client)

    @patch('enroot.container.parse_list')
    @patch('enroot.container.run_enroot')
    def test_list(self, mock_run_enroot, mock_parse_list):
        mock_parse_list.return_value = {"cont1": {}, "cont2": {}}
        container_list = self.containers.list()
        self.assertEqual(len(container_list), 2)
        self.assertIsInstance(container_list[0], Container)
        self.assertEqual(container_list[0].name, "cont1")

    @patch('enroot.container.parse_list')
    def test_get_found(self, mock_parse_list):
        mock_parse_list.return_value = {"cont1": {}}
        container = self.containers.get("cont1")
        self.assertIsInstance(container, Container)
        self.assertEqual(container.name, "cont1")

    @patch('enroot.container.parse_list')
    def test_get_not_found(self, mock_parse_list):
        mock_parse_list.return_value = {}
        with self.assertRaises(RuntimeError):
            self.containers.get("cont1")
    
    @patch('time.sleep', return_value=None)
    @patch('enroot.container.subprocess.Popen')
    @patch('enroot.container.allocate_free_port', return_value='12345')
    @patch('enroot.container.systemd_prefix', return_value=[])
    @patch('enroot.container.random_name', return_value='test-container')
    @patch('pathlib.Path.exists', return_value=True)
    @patch('enroot.container.parse_list')
    @patch('enroot.container.run_enroot')
    def test_run(self, mock_run_enroot, mock_parse_list, mock_path_exists, mock_random_name, mock_systemd_prefix, mock_allocate_port, mock_popen, mock_sleep):
        # Mocking the Popen process
        mock_process = MagicMock()
        mock_process.poll.return_value = 0
        mock_popen.return_value = mock_process
        
        # Mocks for container creation and running status
        mock_parse_list.side_effect = [
            {}, # First call in `run` to check if container exists
            {"test-container": {"pids": [123]}}, # Call in `run` while loop checking for running container
            {"test-container": {"pids": [123]}} # Call from `reload` in Container.__init__
        ]
        
        container = self.containers.run("ubuntu", name="test-container", detach=True, ports={'8080/tcp': '8080'})
        
        self.assertEqual(container.name, "test-container")
        
        # Check create call
        img_path = f"{ENROOT_HOME}/images/ubuntu.sqsh"
        mock_run_enroot.assert_any_call(["create", "--name", "test-container", img_path], capture=False)

        # Check start call
        mock_popen.assert_called_once()
        start_cmd = mock_popen.call_args[0][0]
        self.assertIn("enroot", start_cmd)
        self.assertIn("start", start_cmd)
        self.assertIn("--rw", start_cmd)
        self.assertIn("test-container", start_cmd)
        
        # Check port mapping
        self.assertEqual(container._port_map, {'8080/tcp': '12345'})

class TestContainer(unittest.TestCase):
    def setUp(self):
        self.client = EnrootClient()
        self.container = Container(self.client, "test-cont", {})

    @patch('enroot.container.run_enroot')
    def test_kill(self, mock_run_enroot):
        self.container.kill()
        mock_run_enroot.assert_called_once_with(["remove", "--force", "test-cont"], capture=False)
        self.assertEqual(self.container.status, "exited")

    @patch('enroot.container.run_enroot')
    def test_remove(self, mock_run_enroot):
        self.container.remove()
        mock_run_enroot.assert_called_once_with(["remove", "", "test-cont"], capture=False)
        self.assertEqual(self.container.status, "exited")
        
    @patch('enroot.container.run_enroot')
    def test_remove_force(self, mock_run_enroot):
        self.container.remove(force=True)
        mock_run_enroot.assert_called_once_with(["remove", "--force", "test-cont"], capture=False)
        self.assertEqual(self.container.status, "exited")

    @patch('enroot.container.subprocess.run')
    @patch('enroot.container.parse_list')
    def test_exec_run(self, mock_parse_list, mock_subprocess_run):
        # Mock container status to be running
        mock_parse_list.return_value = {"test-cont": {"pids": [123]}}
        
        # Mock subprocess.run to return a result with stdout and returncode
        # First call is from reload() via run_enroot, second is from exec_run
        mock_proc = MagicMock()
        mock_proc.stdout = b"output"
        mock_proc.stderr = b""
        mock_proc.returncode = 0
        mock_subprocess_run.return_value = mock_proc
        
        result = self.container.exec_run("echo hello")
        # Should be called twice: once for reload() and once for exec_run
        self.assertEqual(mock_subprocess_run.call_count, 2)
        # Check the exec call (second call)
        exec_call = mock_subprocess_run.call_args_list[1]
        self.assertEqual(exec_call[0][0][:3], ["enroot", "exec", "test-cont"])
        self.assertEqual(result.exit_code, 0)
        self.assertEqual(result.output, "output")

    @patch('enroot.container.parse_list')
    def test_exec_run_not_running(self, mock_parse_list):
        # Mock container status to be exited
        mock_parse_list.return_value = {"test-cont": {}}
        with self.assertRaises(RuntimeError) as cm:
            self.container.exec_run("echo hello")
        self.assertIn("not running", str(cm.exception))
        self.assertIn("test-cont", str(cm.exception))

    @patch('enroot.container.parse_list')
    def test_reload_running(self, mock_parse_list):
        mock_parse_list.return_value = {"test-cont": {"pids": [123]}}
        self.container.reload()
        self.assertEqual(self.container.status, "running")

    @patch('enroot.container.parse_list')
    def test_reload_exited(self, mock_parse_list):
        mock_parse_list.return_value = {"test-cont": {}}
        self.container.reload()
        self.assertEqual(self.container.status, "exited")

if __name__ == '__main__':
    unittest.main()
