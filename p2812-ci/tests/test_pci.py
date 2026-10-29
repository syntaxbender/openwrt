#!/usr/bin/env python3
"""Exercise production guard failures in temporary files; never opens real sysfs."""
import hashlib
import json
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import tempfile

RECIPE = Path(__file__).resolve().parents[1]


def main():
    source = (RECIPE / 'files/usr/sbin/p2812-pci').read_text()
    for script in ('usr/sbin/p2812-pci', 'etc/init.d/p2812-pci'):
        subprocess.run(['/bin/sh', '-n', str(RECIPE / 'files' / script)], check=True)
    records = []
    cases = ['normal-nand', 'wrong-board', 'missing-metadata', 'invalid-metadata',
             'metadata-symlink', 'missing-calibration', 'short-calibration',
             'wrong-calibration-hash', 'calibration-symlink', 'firmware-dir-symlink',
             'already-present', 'wrong-pci-id', 'once-marker', 'marker-symlink',
             'missing-rescan', 'repeat-invocation']
    for case in cases:
        with tempfile.TemporaryDirectory(prefix='p2812-service-') as temporary:
            root = Path(temporary)
            for directory in ['tmp/sysinfo', 'etc', 'lib/firmware', 'sys/bus/pci/devices', 'bin', 'proc']:
                (root / directory).mkdir(parents=True, exist_ok=True)
            (root / 'tmp/sysinfo/board_name').write_text('zyxel,p-2812hnu-f1\n')
            # Normal NAND OS is intentionally accepted: the old RAM-only guard is gone.
            (root / 'proc/mounts').write_text('/dev/ubi0_1 /overlay ubifs rw 0 0\noverlayfs:/overlay / overlay rw 0 0\n')
            (root / 'proc/mtd').write_text('mtd0: 00040000 00020000 "uboot"\n')
            calibration = root / 'lib/firmware/RT3062.eeprom'
            calibration.write_bytes(bytes(range(256)) * 2)  # Synthetic, never a modem backup.
            metadata = root / 'etc/p2812-pci.sha256'
            metadata.write_text(hashlib.sha256(calibration.read_bytes()).hexdigest() + '\n')
            rescan = root / 'sys/bus/pci/rescan'
            rescan.write_bytes(b'UNTOUCHED\n')
            card = root / 'sys/bus/pci/devices/0000:00:0e.0'
            marker = root / 'tmp/p2812-pci-once'
            if case == 'wrong-board':
                (root / 'tmp/sysinfo/board_name').write_text('zyxel,p-2812hnu-f3\n')
            elif case == 'missing-metadata': metadata.unlink()
            elif case == 'invalid-metadata': metadata.write_text('0' * 64 + ' extra\n')
            elif case == 'metadata-symlink':
                metadata.rename(root / 'metadata-real'); metadata.symlink_to(root / 'metadata-real')
            elif case == 'missing-calibration': calibration.unlink()
            elif case == 'short-calibration': calibration.write_bytes(b'0' * 511)
            elif case == 'wrong-calibration-hash': calibration.write_bytes(b'0' * 512)
            elif case == 'calibration-symlink':
                calibration.rename(root / 'calibration-real'); calibration.symlink_to(root / 'calibration-real')
            elif case == 'firmware-dir-symlink':
                calibration.parent.rename(root / 'firmware-real'); (root / 'lib/firmware').symlink_to(root / 'firmware-real')
            elif case in ('already-present', 'wrong-pci-id'):
                card.mkdir(); (card / 'vendor').write_text('0x1814\n')
                (card / 'device').write_text('0x3062\n' if case == 'already-present' else '0x9999\n')
            elif case == 'once-marker': marker.mkdir()
            elif case == 'marker-symlink': marker.symlink_to(root / 'nonexistent')
            elif case == 'missing-rescan': rescan.unlink()
            logger = root / 'bin/logger'
            logger.write_text('#!/bin/sh\nprintf "%s\\n" "$*" >> ' + shlex.quote(str(root / 'messages')) + '\n')
            logger.chmod(0o755)
            sha_tool = shutil.which('sha256sum') or shutil.which('shasum')
            if sha_tool is None: raise RuntimeError('sha256sum or shasum required')
            sha_wrapper = root / 'bin/checksum'
            sha_wrapper.write_text('#!/bin/sh\nexec ' + shlex.quote(sha_tool) +
                                   (' -a 256' if Path(sha_tool).name == 'shasum' else '') + ' "$@"\n')
            sha_wrapper.chmod(0o755)
            worker = root / 'worker'
            text = source.replace("ROOT=''", 'ROOT=' + shlex.quote(str(root)), 1)
            text = text.replace("SHA256SUM='/usr/bin/sha256sum'", 'SHA256SUM=' + shlex.quote(str(sha_wrapper)), 1)
            worker.write_text(text)
            env = dict(os.environ, PATH=str(root / 'bin') + ':' + os.environ['PATH'])
            result = subprocess.run(['/bin/sh', str(worker)], env=env, capture_output=True, text=True, timeout=10)
            expected_write = case in ('normal-nand', 'repeat-invocation')
            expected_ok = expected_write or case in ('wrong-board', 'already-present', 'once-marker', 'marker-symlink')
            observed = rescan.read_bytes() if rescan.exists() else None
            assert (result.returncode == 0) == expected_ok, (case, result.returncode, result.stderr)
            assert observed == (b'1\n' if expected_write else None if case == 'missing-rescan' else b'UNTOUCHED\n'), case
            if case == 'repeat-invocation':
                rescan.write_bytes(b'SECOND_UNTOUCHED\n')
                second = subprocess.run(['/bin/sh', str(worker)], env=env, capture_output=True, timeout=10)
                assert second.returncode == 0 and rescan.read_bytes() == b'SECOND_UNTOUCHED\n'
            records.append(dict(case=case, passed=True, PCI_rescan_write=expected_write,
                                exit_code=result.returncode))
    print(json.dumps(dict(passed=True, hardware_access=False, tests=records,
                         limit='Isolated shell guard tests; not physical PCI or boot-timing proof.'), indent=2))


import unittest
class PCIWorker(unittest.TestCase):
    def test_production_guard_cases(self):
        main()

if __name__ == '__main__':
    unittest.main()
