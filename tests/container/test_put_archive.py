"""Tests for Container.put_archive()."""
import io
import tarfile
import pytest
from enroot.container import Container
from enroot import errors


def _make_tar_single_file(filename: str, content: bytes) -> bytes:
    """Build a tar archive containing one file with the given content."""
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w") as tar:
        info = tarfile.TarInfo(name=filename)
        info.size = len(content)
        tar.addfile(info, io.BytesIO(content))
    buf.seek(0)
    return buf.read()


def _make_tar_two_files(files: dict[str, bytes]) -> bytes:
    """Build a tar archive with multiple files (names and contents)."""
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w") as tar:
        for name, content in files.items():
            info = tarfile.TarInfo(name=name)
            info.size = len(content)
            tar.addfile(info, io.BytesIO(content))
    buf.seek(0)
    return buf.read()


def test_put_archive_bytes(running_container: Container):
    """put_archive(path, data) with bytes extracts file into container."""
    path = "/tmp"
    content = b"hello from put_archive"
    tar_data = _make_tar_single_file("testfile.txt", content)
    result = running_container.put_archive(path, tar_data)
    assert result is True
    out = running_container.exec_run(["cat", "/tmp/testfile.txt"])
    assert out.exit_code == 0
    assert out.output.strip() == content


def test_put_archive_filelike(running_container: Container):
    """put_archive(path, data) with file-like object works."""
    path = "/tmp"
    content = b"content from BytesIO"
    tar_data = _make_tar_single_file("from_io.txt", content)
    result = running_container.put_archive(path, io.BytesIO(tar_data))
    assert result is True
    out = running_container.exec_run(["cat", "/tmp/from_io.txt"])
    assert out.exit_code == 0
    assert out.output.strip() == content


def test_put_archive_multiple_files(running_container: Container):
    """put_archive can extract an archive with multiple files."""
    path = "/tmp"
    files = {"a.txt": b"file a", "b.txt": b"file b"}
    tar_data = _make_tar_two_files(files)
    result = running_container.put_archive(path, tar_data)
    assert result is True
    for name, expected in files.items():
        out = running_container.exec_run(["cat", f"/tmp/{name}"])
        assert out.exit_code == 0
        assert out.output.strip() == expected


def test_put_archive_subdir(running_container: Container):
    """put_archive extracts into the given path (e.g. /var/tmp)."""
    running_container.exec_run(["mkdir", "-p", "/tmp/put_archive_subdir"])
    path = "/tmp/put_archive_subdir"
    content = b"inside subdir"
    tar_data = _make_tar_single_file("sub.txt", content)
    result = running_container.put_archive(path, tar_data)
    assert result is True
    out = running_container.exec_run(["cat", "/tmp/put_archive_subdir/sub.txt"])
    assert out.exit_code == 0
    assert out.output.strip() == content


def test_put_archive_not_running_raises(client):
    """put_archive on a created-but-not-started container raises APIError."""
    ref = client.images.pull("alpine", "latest").tags[0]
    cont = client.containers.create(ref, name=None)
    try:
        tar_data = _make_tar_single_file("x.txt", b"x")
        with pytest.raises(errors.APIError, match="not running"):
            cont.put_archive("/tmp", tar_data)
    finally:
        cont.kill()
