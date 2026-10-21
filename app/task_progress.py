from __future__ import annotations

import logging
import math
import threading
import time
from collections import deque
from collections.abc import Callable, Iterable, Iterator
from contextlib import contextmanager
from typing import TypeVar

T = TypeVar("T")
_ACTIVE = threading.local()


def _duration(seconds: float) -> str:
    seconds = max(0, math.ceil(seconds))
    hours, remainder = divmod(seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}"


def _byte_rate(value: float) -> str:
    for unit in ("B/s", "KB/s", "MB/s", "GB/s"):
        if value < 1000 or unit == "GB/s":
            return f"{value:.1f} {unit}"
        value /= 1000
    raise AssertionError("unreachable")


class TaskProgress:
    """Progresso por trabalho concluído, com heartbeat durante chamadas lentas.

    A velocidade usa uma janela de dez segundos. O ETA usa a média desde
    o início da etapa; não há porcentagem/ETA quando o total é desconhecido.
    A thread só observa contadores: nunca faz chamadas de API ou grava dados.
    Com batch_size, informa lotes concluídos e consolida as linhas entre lotes;
    interval mantém atualizações durante esperas sem avanço.
    show_nested permite uma etapa explícita por vez, pausando a barra superior.
    """

    def __init__(
        self,
        label: str,
        total: int | None,
        *,
        unit: str = "contatos",
        byte_count: Callable[[], int] | None = None,
        detail: Callable[[], str] | None = None,
        interval: float = 2.0,
        clock: Callable[[], float] = time.monotonic,
        initial_completed: int = 0,
        batch_size: int | None = None,
        show_nested: bool = False,
    ) -> None:
        if initial_completed < 0 or (total is not None and initial_completed > total):
            raise ValueError("Progresso inicial fora dos limites da tarefa.")
        if batch_size is not None and (type(batch_size) is not int or batch_size <= 0):
            raise ValueError("O tamanho do lote deve ser um inteiro positivo.")
        self.label, self.total, self.unit = label, total, unit
        self.byte_count, self.detail = byte_count, detail
        self.interval, self.clock = interval, clock
        self.batch_size = batch_size
        self.show_nested = show_nested
        self._suspended = 0
        self._last_report: tuple[float, int] | None = None
        self.completed = initial_completed
        self._initial_completed = initial_completed
        self.activity = ""
        self._stop = threading.Event()
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None
        self._samples: deque[tuple[float, int, int]] = deque()

    def __enter__(self) -> TaskProgress:
        # Consultas paginadas de um único contato ficam dentro da barra da
        # preparação; evite abrir milhares de barras auxiliares nessa etapa.
        depth = getattr(_ACTIVE, "depth", 0)
        self._visible = depth == 0 or self.show_nested
        self._parent: TaskProgress | None = getattr(_ACTIVE, "current", None)
        self._pause_parent = self._visible and self._parent is not None
        if self._pause_parent and self._parent is not None:
            with self._parent._lock:
                self._parent._suspended += 1
        if self._visible:
            _ACTIVE.current = self
        _ACTIVE.depth = depth + 1
        try:
            self._started = self.clock()
            self._initial_bytes = self.byte_count() if self.byte_count else 0
            self._samples.append((self._started, self.completed, 0))
            self.report()
            if self._visible:
                self._thread = threading.Thread(target=self._heartbeat, daemon=True)
                self._thread.start()
            return self
        except BaseException:
            self._restore_parent()
            raise

    def _restore_parent(self) -> None:
        _ACTIVE.depth -= 1
        _ACTIVE.current = self._parent
        if self._pause_parent and self._parent is not None:
            with self._parent._lock:
                self._parent._suspended -= 1

    def _heartbeat(self) -> None:
        while True:
            delay = self.interval
            if self.batch_size is not None:
                with self._lock:
                    if not self._suspended and self._last_report is not None:
                        delay = max(
                            0.01,
                            self.interval - (self.clock() - self._last_report[0]),
                        )
            if self._stop.wait(delay):
                return
            self.report()

    def advance(self, count: int = 1) -> None:
        with self._lock:
            previous = self.completed
            self.completed += count
            batch_finished = self.batch_size is not None and (
                self.completed // self.batch_size > previous // self.batch_size
                and self.completed != self.total
            )
        if batch_finished:
            self.report()

    def track(
        self, items: Iterable[T], *, weight: Callable[[T], int] | None = None
    ) -> Iterator[T]:
        for item in items:
            yield item
            # Inclui continue (conflitos/já satisfeitos), mas não itens com falha.
            self.advance(weight(item) if weight else 1)

    def set_activity(self, activity: str) -> str:
        with self._lock:
            previous, self.activity = self.activity, activity
            return previous

    def report(self, *, finished: bool = False, failed: bool = False) -> None:
        if not self._visible:
            return
        with self._lock:
            if self._suspended and not finished:
                return
            now = self.clock()
            elapsed = max(0.0, now - self._started)
            done = self.completed
            if self.batch_size is not None and not finished and self._last_report:
                last_time, last_done = self._last_report
                if (
                    done // self.batch_size == last_done // self.batch_size
                    and now - last_time < self.interval
                ):
                    return
            self._last_report = now, done
            size = (
                max(0, self.byte_count() - self._initial_bytes)
                if self.byte_count
                else 0
            )
            while len(self._samples) > 1 and self._samples[1][0] <= now - 10:
                self._samples.popleft()
            baseline, old_done, old_size = self._samples[0]
            period = now - baseline
            rate = (done - old_done) / period if period > 0 else 0.0
            throughput = (size - old_size) / period if period > 0 else 0.0
            self._samples.append((now, done, size))
            success = (
                finished and not failed and (self.total is None or done == self.total)
            )
            if self.total is None:
                bar = "[coletando]"
                count = f"{done} {self.unit}; total ainda desconhecido"
            else:
                fraction = (
                    min(done / self.total, 1.0)
                    if self.total
                    else (1.0 if success else 0.0)
                )
                percent = 100 if success else min(99, int(fraction * 100))
                filled = 20 if success else min(19, int(fraction * 20))
                bar = f"[{'#' * filled}{'-' * (20 - filled)}] {percent:3d}%"
                count = f"{done}/{self.total} {self.unit}"
            if self.batch_size is not None:
                completed_batches = done // self.batch_size
                if self.total is None:
                    count += f" | lotes concluídos={completed_batches}"
                else:
                    total_batches = math.ceil(self.total / self.batch_size)
                    if success:
                        completed_batches = total_batches
                    count += f" | lotes={completed_batches}/{total_batches}"
            if success:
                eta = "00:00:00"
            elif self.total is not None and done == self.total and done > 0:
                eta = "finalizando"
            elif (
                self.total is not None
                and done > self._initial_completed
                and elapsed > 0
            ):
                eta = _duration(
                    max(0, self.total - done)
                    * elapsed
                    / (done - self._initial_completed)
                )
            else:
                eta = "calculando" if self.total is not None else "indisponível"
            volume = (
                f" | JSONL: {_byte_rate(throughput)}; {size / 1_000_000:.2f} MB gravados"
                if self.byte_count
                else ""
            )
            details = f" | {self.detail()}" if self.detail else ""
            if self.activity:
                details += f" | {self.activity}"
            state = " | interrompido" if failed else (" | concluído" if success else "")
            logging.info(
                "%s %s | %s | %.1f %s/s%s | decorrido=%s | restante estimado=%s%s%s",
                self.label,
                bar,
                count,
                rate,
                self.unit,
                volume,
                _duration(elapsed),
                eta,
                details,
                state,
            )

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join()
        try:
            self.report(finished=True, failed=exc_type is not None)
        finally:
            self._restore_parent()


@contextmanager
def request_progress(label: str) -> Iterator[None]:
    """Observe a blocking request without counting attempts as committed work."""
    active = getattr(_ACTIVE, "current", None)
    if active is not None:
        previous = active.set_activity(f"aguardando API: {label}")
        try:
            yield
        finally:
            active.set_activity(previous)
    else:
        with TaskProgress(label, 1, unit="requisições") as progress:
            progress.set_activity("aguardando resposta da API")
            yield
            progress.set_activity("")
            progress.advance()
