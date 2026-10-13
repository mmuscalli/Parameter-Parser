"""
Runs the pipeline on a background thread so the window stays responsive
during the ~2 minutes a paper takes. Results, progress and errors come back
to the GUI thread as Qt signals.
"""
from __future__ import annotations
import threading
import traceback
from pathlib import Path

from PySide6.QtCore import QObject, Signal, Slot

from parameter_extractor.config.run_config import RunConfig
from parameter_extractor.errors import PipelineError, RunCancelledError
from parameter_extractor.pipeline import run_pipeline


class PipelineWorker(QObject):
    progress = Signal(int, int, str)   # step, total_steps, message
    succeeded = Signal(object)         # RunResult
    failed = Signal(str)               # message written for the user
    cancelled = Signal()
    done = Signal()                    # always emitted last, whatever the outcome

    def __init__(self, pdf_path: Path, config: RunConfig):
        super().__init__()
        self.pdf_path = pdf_path
        self.config = config
        self._cancel = threading.Event()

    def cancel(self) -> None:
        """Takes effect before the next step starts (an API call already in
        flight finishes first)."""
        self._cancel.set()

    @Slot()
    def run(self) -> None:
        try:
            result = run_pipeline(
                self.pdf_path, self.config, cancel_event=self._cancel,
                on_progress=lambda e: self.progress.emit(e.step, e.total_steps, e.message),
            )
        except RunCancelledError:
            self.cancelled.emit()
        except PipelineError as e:
            self.failed.emit(str(e))
        except Exception as e:  # a bug, not a user error -- keep the details for a report
            traceback.print_exc()
            self.failed.emit(f"Unexpected error ({type(e).__name__}): {e}\n\nThis is a bug in "
                             f"the app; the full details were printed to the console.")
        else:
            self.succeeded.emit(result)
        finally:
            self.done.emit()
