from __future__ import annotations

import random
import time

import httpx

USER_AGENT = "Mozilla/5.0 (X11; Linux x86_64; rv:130.0) Gecko/20100101 Firefox/130.0"


class SourceError(Exception):
    pass


class SourceBlocked(Exception):
    def __init__(self, status: int):
        super().__init__(f"сайт ограничил доступ (HTTP {status})")
        self.status = status


class PoliteClient:
    def __init__(self, delay: tuple[float, float] = (1.0, 2.0), timeout: float = 30,
                 retries: int = 2, headers: dict | None = None,
                 transport: httpx.BaseTransport | None = None, sleep=time.sleep):
        self._delay = delay
        self._retries = retries
        self._sleep = sleep
        self.requests = 0
        self._first = True
        self._client = httpx.Client(
            timeout=timeout, transport=transport, follow_redirects=True,
            headers={"User-Agent": USER_AGENT, **(headers or {})})

    def get(self, url: str, params: dict | None = None,
            headers: dict | None = None) -> httpx.Response:
        if not self._first:
            self._sleep(random.uniform(*self._delay))
        self._first = False
        last = "нет ответа"
        for attempt in range(self._retries + 1):
            if attempt:
                self._sleep(2 ** (attempt - 1))
            self.requests += 1
            try:
                r = self._client.get(url, params=params, headers=headers)
            except httpx.HTTPError as e:
                last = f"{type(e).__name__}: {e}"
                continue
            if r.status_code in (429, 403):
                raise SourceBlocked(r.status_code)
            if r.status_code >= 500:
                last = f"HTTP {r.status_code}"
                continue
            if r.status_code >= 400:
                raise SourceError(f"HTTP {r.status_code} для {url}")
            return r
        raise SourceError(f"{url}: {last}")

    def close(self) -> None:
        self._client.close()
