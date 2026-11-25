"""Development staging errors; never treat a conflict as source authorization."""


class StagingConflict(ValueError):
    """A selected staging concurrency or replay-integrity conflict; no automatic retry."""
