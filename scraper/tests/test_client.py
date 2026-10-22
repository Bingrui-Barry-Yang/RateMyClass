import httpx
import pytest

from oxy_scraper.client import CountsClient, FetchError


class FakeClock:
    def __init__(self) -> None:
        self.now = 100.0
        self.sleeps: list[float] = []

    def time(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds


def make_client(
    responses: list[httpx.Response],
    clock: FakeClock,
    *,
    min_interval: float = 1.0,
    max_attempts: int = 4,
) -> CountsClient:
    queue = list(responses)

    def handler(request: httpx.Request) -> httpx.Response:
        return queue.pop(0)

    return CountsClient(
        transport=httpx.MockTransport(handler),
        sleep=clock.sleep,
        clock=clock.time,
        min_interval=min_interval,
        max_attempts=max_attempts,
    )


def test_requests_are_spaced_by_min_interval() -> None:
    clock = FakeClock()
    client = make_client([httpx.Response(200, text="a"), httpx.Response(200, text="b")], clock)
    assert client.home() == "a"
    clock.now += 0.25  # the first response took 0.25 s
    assert client.home() == "b"
    assert clock.sleeps == [pytest.approx(0.75)]
    assert client.requests_made == 2


def test_retries_server_errors_with_exponential_backoff() -> None:
    clock = FakeClock()
    responses = [httpx.Response(500), httpx.Response(503), httpx.Response(200, text="ok")]
    client = make_client(responses, clock, min_interval=0)
    assert client.home() == "ok"
    assert clock.sleeps == [2.0, 4.0]


def test_honours_retry_after() -> None:
    clock = FakeClock()
    responses = [httpx.Response(429, headers={"Retry-After": "30"}), httpx.Response(200, text="ok")]
    client = make_client(responses, clock, min_interval=0)
    assert client.home() == "ok"
    assert clock.sleeps == [30.0]


def test_gives_up_after_max_attempts() -> None:
    clock = FakeClock()
    client = make_client([httpx.Response(500)] * 3, clock, min_interval=0, max_attempts=3)
    with pytest.raises(FetchError, match="HTTP 500 after 3 attempts"):
        client.home()


def test_client_errors_are_not_retried() -> None:
    clock = FakeClock()
    client = make_client([httpx.Response(404)], clock, min_interval=0)
    with pytest.raises(FetchError, match="HTTP 404"):
        client.home()
    assert clock.sleeps == []
