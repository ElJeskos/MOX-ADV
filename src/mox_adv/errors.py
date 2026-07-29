"""Expected safe failures for the bootstrap run."""


class RunRejectedError(ValueError):
    """An input or policy failed closed before execution."""

    def __init__(self, code: str, stage: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.stage = stage
        self.safe_message = message


class RunAlreadyExistsError(FileExistsError):
    """The requested immutable run workspace already exists."""
