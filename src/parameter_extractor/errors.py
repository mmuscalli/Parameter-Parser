"""
Every failure a user can hit during a run, as a named exception with a
plain-language message. Front ends (CLI now, desktop GUI later) catch
PipelineError and show `str(e)` directly -- no tracebacks, no need to know
which library raised what.
"""
from __future__ import annotations


class PipelineError(Exception):
    """Base class: anything that stops a run for a reason the user can act on."""


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
