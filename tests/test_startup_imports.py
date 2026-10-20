"""The real home screen must not pay for unopened analysis tools."""
import json
from pathlib import Path
import subprocess
import sys
import unittest


class StartupImportTests(unittest.TestCase):
    def test_first_responsive_shell_defers_analysis_dependencies(self):
        result = subprocess.run(
            [sys.executable, "-X", "utf8", "-m", "benchmarks.benchmark_startup"],
            cwd=Path(__file__).resolve().parents[1], capture_output=True,
            text=True, encoding="utf-8", timeout=30, check=True,
        )
        sample = json.loads(result.stdout.splitlines()[0])
        self.assertEqual(sample["analysis_modules_loaded"], [])
        self.assertEqual(sample["deferred_dependencies_loaded"], [])
