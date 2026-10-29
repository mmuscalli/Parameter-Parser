"""
Every failure a user can hit during a run, as a named exception with a
plain-language message. Front ends (CLI now, desktop GUI later) catch
PipelineError and show `str(e)` directly -- no tracebacks, no need to know
which library raised what.
"""
from __future__ import annotations


class PipelineError(Exception):
    """Base class: anything that stops a run for a reason the user can act on."""


class AnswersNeededError(PipelineError):
    """Developer handoff mode (handoff.py): requests were written for answers from a Claude Code
    session; the run stops until they're answered."""
    def __init__(self, folder, keys, invalid=()):
        self.folder, self.keys, self.invalid = folder, list(keys), list(invalid)
        super().__init__(self._message())

    def merge(self, other: "AnswersNeededError") -> "AnswersNeededError":
        self.keys += [k for k in other.keys if k not in self.keys]
        self.invalid += [k for k in other.invalid if k not in self.invalid]
        self.args = (self._message(),)
        return self

    def _message(self) -> str:
        bad = (f" {len(self.invalid)} answer(s) didn't fit their schema (see answers/*.error.txt)."
               if self.invalid else "")
        return (f"Answers needed (developer handoff): {len(self.keys)} request(s) written to {self.folder}/requests "
                f"({', '.join(self.keys)}).{bad} Answer them in Claude Code (see README.md there), then run "
                f"this paper again.")


class ApiKeyMissingError(PipelineError):
    def __init__(self):
        super().__init__(
            "No Anthropic API key was provided. Enter one in the app, or for the command "
            "line copy config/.env.example to config/.env and add ANTHROPIC_API_KEY."
        )


class InvalidApiKeyError(PipelineError):
    def __init__(self):
        super().__init__("The Anthropic API rejected the API key. Check that it was copied "
                         "in full and hasn't been revoked.")


class ModelUnavailableError(PipelineError):
    def __init__(self, model: str):
        self.model = model
        super().__init__(f"The model '{model}' isn't available to this API key. It may have "
                         f"been retired -- update the model names in the settings.")


class RateLimitedError(PipelineError):
    def __init__(self):
        super().__init__("The Anthropic API is rate-limiting this key. Wait a minute and try "
                         "again.")


class NetworkError(PipelineError):
    def __init__(self):
        super().__init__("Couldn't reach the Anthropic API. Check the internet connection.")


class OutOfCreditsError(PipelineError):
    """The account behind the key can't pay for more requests: credit balance used up, a spend
    limit or the monthly spend cap reached, or a billing problem. Says where the run stopped."""
    def __init__(self, stage: str, detail: str, finished: list, run_dir=None):
        done = ", ".join(finished) if finished else "none"
        super().__init__(
            f"Your Anthropic account has run out of credits (or hit a spend limit) during the '{stage}' step, "
            f"so the run stopped there. Steps already finished: {done}. "
            + (f"What was done so far is kept in {run_dir} (the CSV is only written at the end). " if run_dir else "")
            + f"Add credits or raise the limit in the Claude Console (Settings > Billing), then run the paper "
              f"again. The API said: {detail}")
        self.stage, self.finished, self.run_dir = stage, list(finished), run_dir


class BatchExpiredError(PipelineError):
    def __init__(self, stage: str):
        super().__init__(f"The '{stage}' step's batch request wasn't processed within Anthropic's 24-hour batch "
                         f"window (nothing was charged for it). Run the paper again, or without batch mode.")


class ApiRequestError(PipelineError):
    """Any other API-side failure; the message carries the API's own explanation."""


class ModelRefusedError(PipelineError):
    def __init__(self, stage: str, detail: str = ""):
        super().__init__(f"The model declined to complete the '{stage}' step. {detail}".strip())


class OutputTruncatedError(PipelineError):
    def __init__(self, stage: str):
        super().__init__(f"The '{stage}' step's answer was too long and got cut off, twice (the "
                         f"model can occasionally run on without finishing). Running the paper again "
                         f"usually works; if it keeps happening, the paper may need its output split up.")


class MalformedOutputError(PipelineError):
    def __init__(self, stage: str, detail: str):
        super().__init__(f"The '{stage}' step's answer broke off before it was complete, twice "
                         f"({detail}). This happens now and then -- running the paper again usually "
                         f"works.")


class PdfNotReadableError(PipelineError):
    """The PDF can't be parsed into text (missing file, scanned image-only PDF, ...)."""


class RunCancelledError(PipelineError):
    def __init__(self):
        super().__init__("The run was cancelled.")


class PaperSourceError(PipelineError):
    """A paper given by identifier (arXiv ID, DOI, ADS bibcode) couldn't be found or fetched."""
