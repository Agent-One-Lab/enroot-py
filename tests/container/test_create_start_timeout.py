"""Integration tests for ``create(timeout=…)`` and ``start(timeout=…)``.

``create`` uses the shell ``timeout`` wrapper via ``run_enroot`` (see ``enroot.utils``).
``start`` uses a poll loop until the container appears in ``enroot list`` with PIDs.
"""
import pytest

from enroot import errors


# Multi‑GB image so ``enroot create`` is likely to exceed a 1s bound on typical hosts.
LARGE_IMAGE_REPO = "pytorch/pytorch"
LARGE_IMAGE_TAG = "2.2.2-cpu"


@pytest.mark.slow
def test_create_raises_timeout_with_tight_limit_and_large_image(client):
    """``create(..., timeout=1)`` should raise ``errors.TimeoutError`` for a heavy rootfs."""
    try:
        img = client.images.pull(LARGE_IMAGE_REPO, LARGE_IMAGE_TAG)
    except Exception as e:
        pytest.skip(f"could not pull {LARGE_IMAGE_REPO}:{LARGE_IMAGE_TAG}: {e}")
    ref = img.tags[0]
    with pytest.raises(errors.TimeoutError, match="timed out"):
        client.containers.create(ref, name=None, timeout=1)


def test_start_raises_timeout_when_container_never_in_list(monkeypatch, client):
    """If ``enroot list`` never shows the container before the deadline, ``start`` times out."""
    ref = client.images.pull("alpine", "latest").tags[0]
    cont = client.containers.create(ref, name=None, command="sleep 3600")
    try:
        monkeypatch.setattr(
            "enroot.container.list_containers_plain",
            lambda **_: {},
        )
        monkeypatch.setattr(
            "enroot.container.list_containers_fancy",
            lambda **_: {},
        )
        with pytest.raises(errors.TimeoutError, match="did not appear in 'enroot list'"):
            cont.start(timeout=2)
    finally:
        try:
            cont.kill()
        except Exception:
            try:
                cont.remove(force=True)
            except Exception:
                pass
