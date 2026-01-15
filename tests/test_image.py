import unittest
from unittest.mock import patch, MagicMock
from enroot.image import Images, Image
from enroot.client import EnrootClient
from enroot import ENROOT_HOME
import pathlib

class TestImages(unittest.TestCase):
    def setUp(self):
        self.client = EnrootClient()
        self.images = Images(self.client)

    @patch('enroot.image.run_enroot')
    @patch('pathlib.Path.exists')
    @patch('enroot.image.Images.get')
    def test_pull(self, mock_get, mock_exists, mock_run_enroot):
        mock_exists.return_value = True
        mock_get.return_value = Image(id="my+image.sqsh", tags=["my+image"])
        
        image = self.images.pull("my/image", "latest")

        ref = "my+image"
        expected_path = str(pathlib.Path(ENROOT_HOME + "/images", f"{ref}.sqsh"))
        mock_run_enroot.assert_called_once_with(
            ["import", "--output", expected_path, "docker://docker.io#my/image:latest"],
            capture=True
        )
        self.assertEqual(image.id, "my+image.sqsh")

    @patch('pathlib.Path.glob')
    def test_list(self, mock_glob):
        mock_glob.return_value = [
            pathlib.Path(ENROOT_HOME + "/images/image1.sqsh"),
            pathlib.Path(ENROOT_HOME + "/images/image2.sqsh"),
        ]
        images = self.images.list()
        self.assertEqual(len(images), 2)
        self.assertEqual(images[0].tags, ["image1"])
        self.assertEqual(images[1].tags, ["image2"])

    @patch('pathlib.Path.exists', return_value=True)
    def test_get_exists(self, mock_exists):
        image = self.images.get("myimage")
        self.assertEqual(image.id, str(pathlib.Path(ENROOT_HOME + "/images/myimage.sqsh")))
        self.assertEqual(image.tags, ["myimage"])

    @patch('pathlib.Path.exists', side_effect=[False, False])
    @patch('enroot.image.Images.list')
    def test_get_not_exists_found_in_list(self, mock_list, mock_exists):
        mock_list.return_value = [
            Image(id="path/to/image1.sqsh", tags=["image1"]),
            Image(id="path/to/myimage.sqsh", tags=["myimage"]),
        ]
        image = self.images.get("myimage")
        self.assertEqual(image.id, "path/to/myimage.sqsh")

    @patch('pathlib.Path.exists', return_value=False)
    @patch('enroot.image.Images.list', return_value=[])
    def test_get_not_found(self, mock_list, mock_exists):
        with self.assertRaises(RuntimeError):
            self.images.get("nonexistent")

if __name__ == '__main__':
    unittest.main()
