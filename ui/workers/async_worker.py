import asyncio
import threading
from typing import Any, Callable, Coroutine, Optional
from PySide6.QtCore import QObject, QThread, Signal


class AsyncRunnerWorker(QThread):
    """
    Dedicated background QThread that runs an asyncio event loop.
    Enables running Telethon / aiohttp async operations from Qt UI
    without blocking the GUI main thread.
    """

    task_finished = Signal(str, object)   # task_id, result
    task_error = Signal(str, str)         # task_id, error_message
    task_progress = Signal(str, int, int) # task_id, current, total

    def __init__(self, parent: Optional[QObject] = None):
        super().__init__(parent)
        self.loop: Optional[asyncio.AbstractEventLoop] = None
        self._running = True

    def run(self):
        """Thread main loop: creates and runs a dedicated asyncio event loop."""
        self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.loop)
        try:
            self.loop.run_forever()
        finally:
            self.loop.close()

    def stop(self):
        """Stops the event loop and waits for thread exit."""
        if self.loop and self.loop.is_running():
            self.loop.call_soon_threadsafe(self.loop.stop)
        self.wait(2000)

    def dispatch(
        self,
        task_id: str,
        coro_func: Callable[..., Coroutine[Any, Any, Any]],
        *args,
        **kwargs,
    ):
        """
        Dispatches a coroutine to be executed on the worker's asyncio loop.
        Emits task_finished or task_error signals upon completion.
        """
        if not self.loop or not self.loop.is_running():
            self.task_error.emit(task_id, "Async worker loop chưa được khởi chạy.")
            return

        async def _wrapper():
            try:
                result = await coro_func(*args, **kwargs)
                self.task_finished.emit(task_id, result)
            except Exception as e:
                self.task_error.emit(task_id, str(e))

        asyncio.run_coroutine_threadsafe(_wrapper(), self.loop)

