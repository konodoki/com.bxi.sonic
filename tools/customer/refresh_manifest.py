#!/usr/bin/env python3
"""Refresh release fingerprints after reviewing and testing intentional changes."""
import hashlib
import json
from pathlib import Path

from delivery_inventory import REPO, files


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    for sums in sorted(REPO.rglob('SHA256SUMS'), key=lambda p: len(p.parts), reverse=True):
        if '.git' in sums.relative_to(REPO).parts:
            continue
        lines = []
        for line in sums.read_text().splitlines():
            if not line.strip():
                continue
            _, name = line.split(maxsplit=1)
            name = name.lstrip('*')
            path = (sums.parent/name).resolve(strict=True)
            if not path.is_relative_to(REPO):
                raise ValueError('Checksum references outside repository: '+name)
            lines.append(digest(path)+'  '+name)
        sums.write_text('\n'.join(lines)+'\n')
    manifest = dict(release='20261027-mm-v17-resident-recovery',
                    files={p.relative_to(REPO).as_posix(): digest(p) for p in files()})
    (REPO/'tools/customer/DELIVERY_MANIFEST.json').write_text(json.dumps(manifest, indent=2)+'\n')
    print('MANIFEST_FILES='+str(len(manifest['files'])))


if __name__ == '__main__':
    main()
