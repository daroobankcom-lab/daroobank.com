"""Development staging errors; never treat a conflict as source authorization."""


class StagingConflict(ValueError):
    """A selected database concurrency error rolled back this staging boundary."""
