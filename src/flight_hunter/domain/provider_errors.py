from __future__ import annotations


class ProviderOperationError(RuntimeError):
    """Safe, typed provider failure that may cross the application boundary."""

    provider_id = "unknown"
    code = "provider_unavailable"

    def __init__(self, message: str | None = None) -> None:
        super().__init__(message or self.code)
