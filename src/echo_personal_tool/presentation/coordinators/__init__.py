"""Coordinators carved out of ``MainWindow`` (issues 420 and 478).

A coordinator owns one feature of the window — its state, its page and its
reactions — and receives everything else it needs explicitly: the application
facade and a narrow port of the window (callables, not the window itself). It
creates no widgets of the window's chrome and can be tested without a
``QMainWindow``.
"""
