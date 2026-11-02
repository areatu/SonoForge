"""Pure image algorithms shared by domain and infrastructure (QH-4b).

Nothing here performs I/O, touches Qt or logs patient data: the modules under
this package operate on in-memory NumPy arrays only.  Keeping them outside
``infrastructure`` lets the domain call the algorithms without importing an
adapter layer, while adapters and presentation may still reuse them.
"""
