"""Unit tests for when exec_run(mem_limit=...) maps host outcome to errors.MemoryError."""

from enroot.container import _should_raise_prlimit_memory_error


def test_normal_tool_failure_exit_1_not_memory_error():
    assert not _should_raise_prlimit_memory_error(1, b"", b"")


def test_normal_tool_failure_with_typical_stderr_not_memory_error():
    assert not _should_raise_prlimit_memory_error(2, b"", b"No such file or directory\n")


def test_sigsegv_style_exit_is_memory_error():
    assert _should_raise_prlimit_memory_error(139, b"", b"")


def test_sigabrt_sigbus_exit_codes_are_memory_error():
    assert _should_raise_prlimit_memory_error(134, b"", b"")
    assert _should_raise_prlimit_memory_error(135, b"", b"")


def test_sigterm_sigpipe_not_memory_error():
    assert not _should_raise_prlimit_memory_error(143, b"", b"")
    assert not _should_raise_prlimit_memory_error(141, b"", b"")


def test_python_negative_sigsegv_returncode_is_memory_error():
    assert _should_raise_prlimit_memory_error(-11, b"", b"")


def test_python_negative_sigterm_not_memory_error():
    assert not _should_raise_prlimit_memory_error(-15, b"", b"")


def test_python_memoryerror_traceback_is_memory_error():
    err = b"Traceback (most recent call last):\n  File \"x.py\", line 1, in <module>\nMemoryError: Unable to allocate array\n"
    assert _should_raise_prlimit_memory_error(1, b"", err)


def test_negated_out_of_memory_phrase_not_matched():
    assert not _should_raise_prlimit_memory_error(1, b"", b"we're not out of memory\n")


def test_reserved_exits_never_memory_error():
    assert not _should_raise_prlimit_memory_error(0, b"", b"")
    assert not _should_raise_prlimit_memory_error(124, b"", b"")
    assert not _should_raise_prlimit_memory_error(137, b"", b"")
