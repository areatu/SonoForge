class IncompleteCineError(RuntimeError):
    """Raised when speckle tracking requires full cine but frames were evicted."""


class TrackingIncompleteError(RuntimeError):
    """Raised when too few kernels tracked successfully."""
