class NLPSignalError(Exception):
    """Base exception for nlp_signal."""


class ExtractionError(NLPSignalError):
    """Raised when the LLM response cannot be parsed into the expected schema."""


class RefusalError(NLPSignalError):
    """Raised when the LLM refuses to produce a response."""
