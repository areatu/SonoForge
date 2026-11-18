"""Composition connects the index to the concrete on-demand reader."""

import time

import numpy as np

from echo_personal_tool.application.composition import make_ctmr_slice_requests
from echo_personal_tool.infrastructure.ctmr_index import index_ctmr_files

pytest_plugins = ("tests.unit.test_ctmr_stacks",)


def test_composed_service_decodes_the_indexed_sop(make_file):
    path = make_file("image", sop="1.2.3.300")
    stack = index_ctmr_files([path]).stacks[0]
    service = make_ctmr_slice_requests()
    try:
        service.select_stack(stack)
        ticket = service.request(0)
        deadline = time.monotonic() + 5
        result = service.poll()
        while result is None and time.monotonic() < deadline:
            time.sleep(0.005)
            result = service.poll()
        assert result is not None and service.claim(result)
        assert result.ticket is ticket and result.ticket.ref.sop_uid == "1.2.3.300"
        assert result.error is None and np.array_equal(result.pixels, np.zeros((16, 24), dtype=np.int16))
    finally:
        service.close()
