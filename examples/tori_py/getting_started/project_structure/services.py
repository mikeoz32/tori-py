"""Application services are ordinary explicit provider classes."""


class ClockService:
    def greeting(self) -> str:
        return "Keep module composition explicit."
