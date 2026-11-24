"""Imported before any test module: keep unit tests away from the working gateway's state.

traces/ holds the quota ledger and trace log of the gateway that is actually running (the directory is
mounted into its container). Tests that build an app without their own quota manager used to write into
it (found 2026-11-24: dozens of fake 503 events and a few hundred tiny ledger rows per test run, which
made the 503 monitoring rule unusable). HARNESS_TRACES_DIR moves every default to a throwaway directory.

Holds only when the test modules are imported as `tests.test_x` (unittest discovery, scripts/verify.py).
Running one file directly (`python tests/test_x.py`) skips this file; test_state_isolation fails loudly then.
"""
import atexit
import os
import shutil
import tempfile

# Unconditional on purpose: a value exported for the lab instance must not be shared with tests either.
_state_dir = tempfile.mkdtemp(prefix="harness-test-traces-")
os.environ["HARNESS_TRACES_DIR"] = _state_dir
atexit.register(lambda: shutil.rmtree(_state_dir, ignore_errors=True))
