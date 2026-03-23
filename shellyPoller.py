import asyncio
import threading
import time
from typing import Any

import httpx


class ShellySnapshotStore:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._data: dict[str, Any] | None = None
        self._updated_monotonic: float | None = None

    def set(self, data: dict[str, Any]) -> None:
        with self._lock:
            self._data = data
            self._updated_monotonic = time.perf_counter()

    def get(self) -> dict[str, Any] | None:
        with self._lock:
            if self._data is None:
                return None
            return self._data.copy()

    def age_seconds(self) -> float | None:
        with self._lock:
            if self._updated_monotonic is None:
                return None
            return time.perf_counter() - self._updated_monotonic

    def has_fresh_data(self, max_age_seconds: float) -> bool:
        age = self.age_seconds()
        return age is not None and age <= max_age_seconds


class ShellyPoller:
    def __init__(
        self,
        url: str,
        username: str,
        password: str,
        store: ShellySnapshotStore,
        interval: float = 0.1,
        timeout: float = 1.0,
        reconnect_delay: float = 0.2,
        log_enabled: bool = True,
        on_new_snapshot=None,
    ) -> None:
        self.url = url
        self.auth = httpx.BasicAuth(username, password)
        self.store = store
        self.interval = interval
        self.timeout = timeout
        self.reconnect_delay = reconnect_delay
        self.log_enabled = log_enabled
        self.on_new_snapshot = on_new_snapshot

    def _log(self, text: str) -> None:
        if self.log_enabled:
            print(text)

    async def run_forever(self) -> None:
        while True:
            try:
                limits = httpx.Limits(max_connections=1, max_keepalive_connections=1)

                async with httpx.AsyncClient(
                    auth=self.auth,
                    timeout=httpx.Timeout(self.timeout),
                    limits=limits,
                    http2=False,
                ) as client:
                    warmup = await client.get(self.url)
                    warmup.raise_for_status()
                    warmup_data = warmup.json()
                    self.store.set(warmup_data)
                    if self.on_new_snapshot is not None:
                        self.on_new_snapshot(warmup_data)
                    self._log(f"Shelly warm-up ok: {warmup.status_code}")

                    next_time = time.perf_counter()

                    while True:
                        now = time.perf_counter()
                        remaining = next_time - now
                        if remaining > 0:
                            await asyncio.sleep(remaining)

                        planned_time = next_time
                        send_time = time.perf_counter()

                        try:
                            response = await client.get(self.url)
                            response.raise_for_status()
                            data = response.json()
                            done_time = time.perf_counter()

                            self.store.set(data)
                            if self.on_new_snapshot is not None:
                                self.on_new_snapshot(data)

                            if self.log_enabled:
                                emeters = data.get("emeters", [])
                                power_sum = sum(float(m.get("power", 0.0)) for m in emeters)

                                self._log(
                                    f"Shelly geplant={planned_time:.6f} "
                                    f"gesendet={send_time:.6f} "
                                    f"delta_ms={(send_time - planned_time) * 1000:+.3f} "
                                    f"dauer_ms={(done_time - send_time) * 1000:.1f} "
                                    f"status={response.status_code} "
                                    f"power_sum={power_sum:.2f}W"
                                )

                        except (httpx.TimeoutException, httpx.TransportError) as e:
                            self._log(f"Shelly Request-Fehler: {type(e).__name__}: {e}")
                            break
                        except Exception as e:
                            self._log(f"Shelly anderer Fehler: {type(e).__name__}: {e}")
                            break

                        # Relativer Takt, aber ohne Aufstauen alter Sollzeiten
                        next_time = max(next_time + self.interval, time.perf_counter())

            except Exception as e:
                self._log(f"Shelly Client-Fehler: {type(e).__name__}: {e}")

            await asyncio.sleep(self.reconnect_delay)