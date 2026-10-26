"""P1 evidence-only probe: exit 1 when nested Settings aliasing is reproduced.

Run in a fresh process with ``python -m benchmarks.probe_settings_ownership``.
Only temporary YAML is written. This is deliberately not a passing regression
test or a production ownership fix; the boundary contract requires review.
"""
from copy import deepcopy
import json
from pathlib import Path
import subprocess
import sys
import tempfile


def main():
    from run_tests import isolate_settings
    with tempfile.TemporaryDirectory(prefix='p1-settings-ownership-') as directory:
        path = isolate_settings(directory)
        from metrology_app import settings
        initial = deepcopy(settings.load_settings(path))
        exposed = settings.get_settings()
        exposed['trend_overlay']['P0'] = 'uncommitted caller mutation'
        active_changed = settings.get_settings() != initial
        defaults_changed = settings.DEFAULTS['trend_overlay'].get('P0') == exposed['trend_overlay']['P0']
        reloaded_changed = settings.load_settings(path)['trend_overlay'] != initial['trend_overlay']
        result = {'get_settings_nested_mutation_changes_active': active_changed,
                  'missing_file_load_mutates_default_overlay': defaults_changed,
                  'nested_value_survives_reload_without_any_save': reloaded_changed,
                  'disk_created_by_mutation': path.exists(),
                  'scope': 'Public Settings accessor boundary; no actual UI cancellation data loss established'}
        settings.save_settings({'theme': 'light'}, path)
        original = path.read_bytes()
        completed = subprocess.run([sys.executable, '-c',
            "import os,sys; from metrology_app.settings import save_settings; "
            "os.replace=lambda *args: os._exit(17); save_settings({'theme':'dark'},sys.argv[1])", str(path)])
        result['crash_returncode'] = completed.returncode
        result['old_yaml_unchanged_after_crash'] = path.read_bytes() == original
        result['orphan_temporary_names_before_retry'] = [p.name for p in Path(directory).glob('.*.tmp')]
        settings.load_settings(path)
        settings.save_settings({'font_size': 12}, path)
        result['dead_lock_recovered'] = not Path(str(path) + '.lock').exists()
        result['orphan_temporary_names_after_retry'] = [p.name for p in Path(directory).glob('.*.tmp')]
        result['orphan_temporary_bytes'] = sum(p.stat().st_size for p in Path(directory).glob('.*.tmp'))
        print(json.dumps(result, indent=2))
        return int(active_changed or defaults_changed or reloaded_changed)


if __name__ == '__main__':
    raise SystemExit(main())
