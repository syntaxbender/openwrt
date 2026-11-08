import copy
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import build
import dsl_variants as dsl


class DSLVariants(unittest.TestCase):
    def test_four_identities_and_payload_refusals(self):
        self.assertEqual({dsl.identity(build.CONFIG, f, d) for f, d in dsl.variants(build.CONFIG)},
                         {'normal-stock', 'normal-avm', 'lite-stock', 'lite-avm'})
        for f, d in [('normal', 'other'), ('other', 'avm')]:
            with self.assertRaises(ValueError):dsl.identity(build.CONFIG, f, d)
        for mode in ['stock', 'avm']:
            cfg = copy.deepcopy(build.CONFIG)
            data = b'SYNTHETIC DSL TEST INPUT'
            cfg['dsl_variants'][mode].update(bytes=len(data), sha256=hashlib.sha256(data).hexdigest())
            dsl.verify_firmware(cfg, mode, data)
            for bad in [data[:-1], b'X' * len(data)]:
                with self.assertRaises(ValueError):dsl.verify_firmware(cfg, mode, bad)

    def test_provenance_must_match_locked_payload(self):
        lock = json.loads((build.ROOT / 'p2812-dsl/inputs.lock.json').read_text())
        self.assertIn(lock['firmware']['sha256'].encode(), dsl.provenance(build.CONFIG, lock))
        for field, value in [('sha256', 'a' * 64), ('version', 'other'), ('bytes', 1)]:
            changed = copy.deepcopy(lock);changed['firmware'][field] = value
            with self.assertRaises(ValueError):dsl.provenance(build.CONFIG, changed)

    def run_firstboot(self, mode, fault=None):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp);binpath = root / 'bin';binpath.mkdir()
            fw = root / 'firmware';fw.mkdir();data = b'SYNTHETIC DSL TEST INPUT'
            cfg = copy.deepcopy(build.CONFIG)
            cfg['dsl_variants'][mode].update(bytes=len(data), sha256=hashlib.sha256(data).hexdigest())
            spec = dsl.firmware(cfg, mode);payload = fw / Path(spec['path']).name
            if fault != 'missing':payload.write_bytes(b'X' * len(data) if fault == 'corrupt' else data)
            board = root / 'board';board.write_text('another,board\n' if fault == 'board' else cfg['board'] + '\n')
            original = {'network.dsl': 'absent' if fault == 'section' else 'dsl',
                        'network.dsl.firmware': '/old.bin', 'network.dsl.vectoring': '2',
                        'network.wan.password': 'SYNTHETIC-TEST-ONLY', 'network.lan.ipaddr': '192.0.2.1',
                        'wireless.radio0.disabled': '0'}
            state = root / 'state.json';state.write_text(json.dumps(original))
            # Run the actual generated POSIX shell. Only absolute read paths are
            # redirected into this private synthetic root; no device is accessed.
            script = dsl.firstboot(cfg, mode).decode().replace('/tmp/sysinfo/board_name', str(board)).replace('/lib/firmware/', str(fw) + '/')
            path = root / 'firstboot';path.write_text(script)
            programs = {
                'uci': '''import json,os,sys
from pathlib import Path
p=Path(os.environ['DSL_TEST_STATE']);s=json.loads(p.read_text());a=sys.argv[1:]
if a==['-q','get','network.dsl']:
 print(s['network.dsl']);sys.exit(0)
if a!=['-q','batch']:sys.exit(2)
lines=sys.stdin.read().splitlines()
for line in lines:
 if line=='commit network':continue
 if not line.startswith('set network.dsl.'):sys.exit(3)
 k,v=line[4:].split('=',1);s[k]=v.strip("'")
p.write_text(json.dumps(s))
''',
                'sha256sum': '''import hashlib,sys
row=sys.stdin.read().strip();expected,name=row.split(None,1)
try:
 with open(name,'rb') as f:actual=hashlib.sha256(f.read()).hexdigest()
except OSError:sys.exit(1)
sys.exit(0 if actual==expected else 1)
''',
                'logger': 'import sys\nsys.exit(0)\n',
            }
            for name, code in programs.items():
                tool = binpath / name;tool.write_text('#!' + sys.executable + '\n' + code);tool.chmod(0o755)
            env = dict(os.environ, PATH=str(binpath) + os.pathsep + os.environ['PATH'], DSL_TEST_STATE=str(state))
            subprocess.run(['/bin/sh', '-n', str(path)], check=True)
            result = subprocess.run(['/bin/sh', str(path)], env=env, capture_output=True)
            after = json.loads(state.read_text())
            if fault:
                self.assertEqual(result.returncode, 0 if fault == 'board' else 1)
                self.assertEqual(after, original)
            else:
                self.assertEqual(result.returncode, 0, result.stderr)
                expected = dict(original, **{'network.dsl.firmware': str(payload),
                                             'network.dsl.vectoring': str(spec['vectoring'])})
                self.assertEqual(after, expected)

    def test_firstboot_changes_only_two_DSL_options(self):
        for mode in ['stock', 'avm']:
            with self.subTest(mode=mode):self.run_firstboot(mode)

    def test_firstboot_refuses_bad_payload_and_wrong_board(self):
        for mode in ['stock', 'avm']:
            for fault in ['missing', 'corrupt', 'board', 'section']:
                with self.subTest(mode=mode, fault=fault):self.run_firstboot(mode, fault)


if __name__ == '__main__':unittest.main()
