"""Performance benchmarks excluded from the regression suite.

Module entry points isolate every persistence path before application imports.
Individual probes may use their own scratch paths within this safe environment.
"""
from tempfile import TemporaryDirectory

from run_tests import isolate_settings

_scratch = TemporaryDirectory(prefix="metrology-benchmarks-")
isolate_settings(_scratch.name)
