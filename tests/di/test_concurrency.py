"""Thread-safety of singleton construction.

Two threads racing to resolve the same singleton must end up with one
instance whose ``__init__`` ran exactly once. The class deliberately
holds a small ``time.sleep`` so the race window is wide enough to
distinguish proper locking from the no-lock alternative.
"""

import threading
import time

from ajolopy.di import Container


class _Slow:
    counter = 0
    lock = threading.Lock()

    def __init__(self) -> None:
        with type(self).lock:
            type(self).counter += 1
        # Widen the race window so two unlocked threads would
        # consistently double-build.
        time.sleep(0.05)


def test_singleton_init_runs_exactly_once_under_thread_race() -> None:
    _Slow.counter = 0
    container = Container()
    container.register(_Slow)

    results: list[_Slow] = []
    barrier = threading.Barrier(2)

    def resolve() -> None:
        barrier.wait()
        results.append(container.resolve(_Slow))

    threads = [threading.Thread(target=resolve) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert _Slow.counter == 1
    assert len(results) == 2
    assert results[0] is results[1]
