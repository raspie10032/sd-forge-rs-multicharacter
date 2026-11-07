# SPDX-License-Identifier: GPL-3.0-only
"""Cooperative cancellation without requiring ComfyUI for standalone tests."""

import time


def is_interruption(error):
    try:
        from modules.sd_samplers_common import InterruptedException as InterruptProcessingException
    except ImportError:
        return False
    return isinstance(error, InterruptProcessingException)


def check_interrupted():
    try:
        from ..host import check_interrupted as throw_exception_if_processing_interrupted
    except ImportError:
        return
    throw_exception_if_processing_interrupted()


def wait_until(deadline):
    while True:
        check_interrupted()
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return
        time.sleep(min(remaining, 0.1))
