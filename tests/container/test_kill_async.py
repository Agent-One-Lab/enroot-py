import inspect

from enroot.container import Container


def test_kill_async_is_coroutine_function():
    assert inspect.iscoroutinefunction(Container.kill_async)

