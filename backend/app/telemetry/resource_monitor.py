"""Asynchronous resource monitor collecting CPU and memory samples."""

from __future__ import annotations

import asyncio
import contextlib
import math
import os
import sys
import time
from typing import Callable, Sequence

try:  # pragma: no cover - psutil is optional at runtime
    import psutil  # type: ignore
except Exception:  # pragma: no cover - gracefully handle missing dependency
    psutil = None  # type: ignore[assignment]

try:  # pragma: no cover - ``resource`` is not present on all platforms
    import resource as resource_mod  # type: ignore
except Exception:  # pragma: no cover - gracefully handle missing dependency
    resource_mod = None  # type: ignore[assignment]


Sampler = Callable[[], tuple[float | None, float | None]]


class _PsutilSampler:
    """Process resource sampler backed by :mod:`psutil`."""

    def __init__(self) -> None:
        process = psutil.Process()  # type: ignore[call-arg]
        # Prime ``cpu_percent`` to establish a baseline for delta calculations.
        process.cpu_percent(interval=None)
        self._process = process

    def __call__(self) -> tuple[float | None, float | None]:
        cpu_percent = float(self._process.cpu_percent(interval=None))
        memory_info = self._process.memory_info()
        memory_mb = float(memory_info.rss) / (1024.0 * 1024.0)
        return cpu_percent, memory_mb


class _ResourceSampler:
    """Fallback sampler using the built-in :mod:`resource` module."""

    def __init__(self) -> None:
        if resource_mod is None:  # pragma: no cover - defensive check
            raise RuntimeError("resource module is unavailable on this platform")
        self._last_cpu_time: float | None = None
        self._last_wall_time: float | None = None

    def __call__(self) -> tuple[float | None, float | None]:
        usage = resource_mod.getrusage(resource_mod.RUSAGE_SELF)  # type: ignore[arg-type]
        cpu_time = float(usage.ru_utime + usage.ru_stime)
        now = time.perf_counter()

        cpu_percent: float | None = None
        if self._last_cpu_time is not None and self._last_wall_time is not None:
            delta_cpu = max(cpu_time - self._last_cpu_time, 0.0)
            delta_wall = max(now - self._last_wall_time, sys.float_info.min)
            cpu_count = os.cpu_count() or 1
            cpu_percent = (delta_cpu / (delta_wall * cpu_count)) * 100.0

        self._last_cpu_time = cpu_time
        self._last_wall_time = now

        rss_mb: float | None = None
        if hasattr(usage, "ru_maxrss"):
            rss = float(usage.ru_maxrss)
            # macOS reports ``ru_maxrss`` in bytes whereas Linux uses kilobytes.
            if sys.platform == "darwin":
                rss_bytes = rss
            else:
                rss_bytes = rss * 1024.0
            rss_mb = rss_bytes / (1024.0 * 1024.0)

        return cpu_percent, rss_mb


class _NullSampler:
    """Sampler placeholder used when no metrics are available."""

    def __call__(self) -> tuple[float | None, float | None]:  # pragma: no cover - trivial
        return None, None


class ProcessSampler:
    """Factory selecting the most capable resource sampler for the host."""

    def __init__(self) -> None:
        if psutil is not None:  # pragma: no branch - straight-forward selection
            self._impl: Sampler = _PsutilSampler()
        elif resource_mod is not None:
            self._impl = _ResourceSampler()
        else:
            self._impl = _NullSampler()

    def __call__(self) -> tuple[float | None, float | None]:
        return self._impl()


class ResourceMonitor:
    """Asynchronous context manager capturing resource utilisation samples."""

    def __init__(
        self,
        *,
        interval: float = 0.5,
        cpu_threshold: float | None = None,
        memory_threshold_mb: float | None = None,
        sampler: Sampler | None = None,
    ) -> None:
        self._interval = max(0.01, float(interval))
        self._sampler = sampler or ProcessSampler()
        self._task: asyncio.Task[None] | None = None
        self._stop_event = asyncio.Event()
        self._condition = asyncio.Condition()
        self._sample_counter = 0

        self.cpu_threshold = cpu_threshold
        self.memory_threshold_mb = memory_threshold_mb

        self.cpu_samples: list[float] = []
        self.memory_samples: list[float] = []
        self.peakCpu: float | None = None
        self.peakMemoryMb: float | None = None
        self.throttleCount: int = 0

        self._cpu_sum = 0.0
        self._cpu_count = 0
        self._memory_sum = 0.0
        self._memory_count = 0

        self._last_cpu: float | None = None
        self._last_memory: float | None = None

    async def __aenter__(self) -> "ResourceMonitor":
        self._task = asyncio.create_task(self._run())
        await self.wait_for_sample()
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        self._stop_event.set()
        if self._task is not None:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task

    async def _run(self) -> None:
        try:
            while not self._stop_event.is_set():
                cpu_percent, memory_mb = await asyncio.to_thread(self._sampler)
                self._ingest_sample(cpu_percent, memory_mb)
                async with self._condition:
                    self._sample_counter += 1
                    self._condition.notify_all()
                try:
                    await asyncio.wait_for(self._stop_event.wait(), timeout=self._interval)
                except asyncio.TimeoutError:
                    continue
        except asyncio.CancelledError:  # pragma: no cover - cooperative cancellation
            pass
        finally:  # pragma: no cover - defensive wake-up for waiting tasks
            async with self._condition:
                self._condition.notify_all()

    def _ingest_sample(self, cpu_percent: float | None, memory_mb: float | None) -> None:
        if cpu_percent is not None and not math.isnan(cpu_percent):
            value = float(cpu_percent)
            self.cpu_samples.append(value)
            self._cpu_sum += value
            self._cpu_count += 1
            self._last_cpu = value
            if self.peakCpu is None or value > self.peakCpu:
                self.peakCpu = value

        if memory_mb is not None and not math.isnan(memory_mb):
            value = float(memory_mb)
            self.memory_samples.append(value)
            self._memory_sum += value
            self._memory_count += 1
            self._last_memory = value
            if self.peakMemoryMb is None or value > self.peakMemoryMb:
                self.peakMemoryMb = value

    @property
    def average_cpu(self) -> float | None:
        if self._cpu_count == 0:
            return None
        return self._cpu_sum / self._cpu_count

    @property
    def average_memory_mb(self) -> float | None:
        if self._memory_count == 0:
            return None
        return self._memory_sum / self._memory_count

    async def wait_for_sample(self, last_counter: int | None = None) -> int:
        """Await the availability of a new resource sample."""

        async with self._condition:
            if last_counter is None:
                while self._sample_counter == 0 and not self._stop_event.is_set():
                    await self._condition.wait()
                return self._sample_counter

            while self._sample_counter <= last_counter and not self._stop_event.is_set():
                await self._condition.wait()
            return self._sample_counter

    def check_thresholds(
        self,
        *,
        cpu_threshold: float | None,
        memory_threshold_mb: float | None,
    ) -> tuple[bool, list[str]]:
        """Evaluate the latest sample against guardrail thresholds."""

        reasons: list[str] = []
        if (
            cpu_threshold is not None
            and self._last_cpu is not None
            and self._last_cpu >= cpu_threshold
        ):
            reasons.append("cpu")
        if (
            memory_threshold_mb is not None
            and self._last_memory is not None
            and self._last_memory >= memory_threshold_mb
        ):
            reasons.append("memory")
        return (bool(reasons), reasons)

    def record_throttle(self, _reasons: Sequence[str] | None = None) -> None:
        """Increment the throttle counter for summary reporting."""

        self.throttleCount += 1


__all__ = ["ProcessSampler", "ResourceMonitor"]
