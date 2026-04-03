import inspect

from enroot.container import Container, Containers


def test_async_methods_are_coroutines():
    assert inspect.iscoroutinefunction(Container.start_async)
    assert inspect.iscoroutinefunction(Container.exec_run_async)
    assert inspect.iscoroutinefunction(Containers.create_async)

