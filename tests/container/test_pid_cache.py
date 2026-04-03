from enroot.container import Container


def test_meta_uses_class_pid_cache_on_hit(monkeypatch):
    c = Container(None, "c1", {}, _created_only=False)
    c._PID_CACHE.clear()
    c._PID_CACHE["c1"] = [1234]

    def should_not_be_called(*args, **kwargs):
        raise AssertionError("list function should not be called on cache hit")

    monkeypatch.setattr("enroot.container.list_containers_plain", should_not_be_called)
    monkeypatch.setattr("enroot.container.list_containers_fancy", should_not_be_called)

    meta = c._meta()
    assert meta.get("pids") == [1234]


def test_meta_populates_cache_on_miss(monkeypatch):
    c = Container(None, "c2", {}, _created_only=False)
    c._PID_CACHE.clear()

    monkeypatch.setattr("enroot.container.list_containers_plain", lambda **_: {"c2": {}})
    monkeypatch.setattr("enroot.container.list_containers_fancy", lambda **_: {"c2": {"pids": [2222]}})

    meta = c._meta()
    assert meta.get("pids") == [2222]
    assert c._PID_CACHE["c2"] == [2222]

