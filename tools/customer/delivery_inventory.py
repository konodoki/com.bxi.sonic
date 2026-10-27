"""Explicit customer distribution boundary; no development machine resources."""
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
R7 = 'tools/pico_collection/sonic_pico_collection_20261019_r7/'
EXCLUDED_PARTS = {'.git', '__pycache__', '.pytest_cache', '.runtime'}
EXCLUDED_FILES = {
 R7+'collector/export_lerobot_v21.py', R7+'collector/validate_lerobot_v21.py',
 R7+'collector/requirements-export.txt',  # legacy 33/mimic training interface

 'tools/customer/site.local.json', 'tools/customer/DELIVERY_MANIFEST.json',
 R7+'build.py', R7+'install_service.py', R7+'elf3_pico_collection.service',
 'tools/tracking_eval/tracking_eval.sh', 'tools/tracking_eval/recording/install.py',
 'tools/tracking_eval/recording/baseline_policy.py.txt', 'tools/tracking_eval/recording/legacy_policy.py.txt',
 'tools/tracking_eval/evaluation/export_kinematic.py', R7+'control.sh',
}
EXCLUDED_PREFIXES = ('docs/history/', 'tools/pico_collection/field_test01_20261020/',
                      'tools/tracking_eval/packages/', R7+'collector/tests/')

def deliverable(relative):
    p = Path(relative)
    s = p.as_posix()
    if any(part in EXCLUDED_PARTS for part in p.parts) or s in EXCLUDED_FILES or s.startswith(EXCLUDED_PREFIXES):
        return False
    if s.startswith('tools/pico_collection/') and len(p.parts) == 3 and s not in {'tools/pico_collection/README.md', 'tools/pico_collection/RECOVERY_V17.md'}:
        return False  # frozen test-01 upload packages/installers, not customer entries
    return not s.endswith(('.pyc', '.tgz', '.tgz.sha256'))

def files(root=REPO):
    return [p for p in sorted(root.rglob('*')) if (p.is_file() or p.is_symlink()) and deliverable(p.relative_to(root))]
