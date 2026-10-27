#!/usr/bin/env python3
"""Build a complete relocatable tar; no installation or network operations."""
import argparse
import hashlib
import io
import json
from pathlib import Path
import tarfile
from delivery_inventory import REPO, files
from check_delivery import check

if __name__ == '__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('output_dir', type=Path)
    a=p.parse_args()
    if check(): raise SystemExit('Fix delivery checks before building')
    output=a.output_dir.expanduser().resolve()
    if output == REPO or REPO in output.parents: raise SystemExit('output must be outside source repo')
    output.mkdir(parents=True,exist_ok=True)
    target=output/'sonic_customer_20261027_mm_v17_resident_recovery.tar.gz'
    if target.exists(): raise SystemExit('refusing to overwrite '+str(target))
    inventory={}
    selected=files()
    included={p.relative_to(REPO).as_posix() for p in selected}
    overrides={}
    for checksum in sorted((p for p in selected if p.name=='SHA256SUMS'),key=lambda p:len(p.parts),reverse=True):
        lines=[]
        for line in checksum.read_text().splitlines():
            if not line.strip(): continue
            _, name=line.split(maxsplit=1)
            name=name.lstrip('*')
            full=(checksum.parent/name).relative_to(REPO).as_posix()
            if full not in included: continue
            content=overrides.get(full)
            if content is None: content=(REPO/full).read_bytes()
            lines.append(hashlib.sha256(content).hexdigest()+'  '+name)
        overrides[checksum.relative_to(REPO).as_posix()]=('\n'.join(lines)+'\n').encode()
    with tarfile.open(target, 'x:gz') as tar:
        for src in selected:
            name=src.relative_to(REPO).as_posix()
            data=src.read_bytes()
            data=overrides.get(name,data)
            info=tar.gettarinfo(str(src),arcname='com.bxi.sonic/'+name)
            info.uid=info.gid=0;info.uname=info.gname='';info.mode=0o755 if src.suffix=='.sh' or src.name in ('RoboticsServiceProcess','mediamtx','usb_cam_node_exe') else 0o644
            # Preserve binary executable mode for additional vendor helpers.
            if data[:4]==b'\x7fELF' and not src.name.endswith('.so'): info.mode=0o755
            info.size=len(data);tar.addfile(info,io.BytesIO(data))
            inventory[name]=hashlib.sha256(data).hexdigest()
        data=(json.dumps(dict(release='20261027-mm-v17-resident-recovery',files=inventory),indent=2)+'\n').encode()
        info=tarfile.TarInfo('com.bxi.sonic/tools/customer/DELIVERY_MANIFEST.json');info.size=len(data);info.mode=0o644
        tar.addfile(info,io.BytesIO(data))
    digest=hashlib.file_digest(target.open('rb'),'sha256').hexdigest() if hasattr(hashlib,'file_digest') else hashlib.sha256(target.read_bytes()).hexdigest()
    target.with_name(target.name+'.sha256').write_text(digest+'  '+target.name+'\n')
    print(target)
