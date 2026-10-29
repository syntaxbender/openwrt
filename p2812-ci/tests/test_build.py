import hashlib,io,json,lzma,struct,sys,tarfile,tempfile,unittest,zlib
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import build
import release

def kernel(raw=b'SYNTHETIC-TEST-ONLY'):
 packed=lzma.compress(raw,format=lzma.FORMAT_ALONE)
 h=struct.pack('>7I4B32s',0x27051956,0,0,len(packed),0x80002000,0x80002000,zlib.crc32(packed),5,5,2,3,b'TEST ONLY')
 return h[:4]+struct.pack('>I',zlib.crc32(h))+h[8:]+packed

def manifest(flavor):
 names=set(build.CONFIG['required_packages'])
 if flavor=='normal':names|={'luci-base','uhttpd'}
 return ''.join(x+' - 1\n' for x in sorted(names))

class BuildChecks(unittest.TestCase):
 def test_stable_series_selection_excludes_RC_and_other_series(self):
  html=''.join('<a href="'+x+'/">' for x in ['25.12.6','25.12.11','25.12.12-rc1','26.1.0','25.12-SNAPSHOT','evil'])
  self.assertEqual(build.latest(html),'25.12.11')
  for x in ['25.12.6-rc1','../../other','26.1.0','25.12.6\n']:
   self.assertFalse(build.version_ok(x))
 def test_signed_checksum_parser_rejects_duplicates_and_html(self):
  h='a'*64;self.assertEqual(build.checksum_map(h+' *file\n'),{'file':h})
  for bad in ['<html>error</html>',h+' *file\n'+h+' *file\n','bad file']:
   with self.assertRaises(RuntimeError):build.checksum_map(bad)
 def test_kernel_crc_and_decompression_bounds(self):
  good=kernel();self.assertEqual(build.validate_kernel(good)['decoded_bytes'],19)
  for bad in [good[:-1],good[:8]+bytes([good[8]^1])+good[9:],good[:64]+bytes([good[64]^1])+good[65:]]:
   with self.assertRaises((RuntimeError,lzma.LZMAError)):build.validate_kernel(bad)
  cfg=dict(build.CONFIG,max_decoded_kernel_bytes=1024)
  with patch.object(build,'CONFIG',cfg):
   with self.assertRaises(RuntimeError):build.validate_kernel(kernel(b'X'*1025))
 def test_required_and_removed_packages(self):
  for flavor in ['normal','lite']:build.validate_manifest(flavor,manifest(flavor))
  for bad in [manifest('lite')+'uhttpd - 1\n',manifest('lite').replace('ppp-mod-pppoe - 1\n',''),manifest('lite')+'kmod-atm - 1\n']:
   with self.assertRaises(RuntimeError):build.validate_manifest('lite',bad)
 def test_archive_traversal_symlink_and_device_refused(self):
  for case in ['traversal','absolute','escaping-symlink','device','safe']:
   b=io.BytesIO()
   with tarfile.open(fileobj=b,mode='w') as t:
    root=tarfile.TarInfo('root');root.type=tarfile.DIRTYPE;t.addfile(root)
    n=tarfile.TarInfo({'traversal':'../outside','absolute':'/outside'}.get(case,'root/file'))
    if case=='escaping-symlink':n.type=tarfile.SYMTYPE;n.linkname='../../outside'
    elif case=='device':n.type=tarfile.CHRTYPE
    else:n.size=1
    t.addfile(n,io.BytesIO(b'x') if n.isfile() else None)
   class Decoder:
    def __init__(self,*a,**k):self.stdout=io.BytesIO(b.getvalue())
    def wait(self):return 0
   with tempfile.TemporaryDirectory() as temp,patch.object(build.subprocess,'Popen',Decoder):
    if case=='safe':self.assertEqual(build.safe_extract(Path('unused'),Path(temp)/'out').name,'root')
    else:
     with self.assertRaises(RuntimeError):build.safe_extract(Path('unused'),Path(temp)/'out')

class PublicationChecks(unittest.TestCase):
 def test_tag_cannot_inject_gh_options(self):
  s={'version':'25.12.6','recipe_sha256':'b'*64};self.assertEqual(release.tag_for(s),'p2812-openwrt-v25.12.6-bbbbbbbbbbbb')
  for bad in [dict(s,version='--evil'),dict(s,recipe_sha256='bad')]:
   with self.assertRaises(RuntimeError):release.tag_for(bad)
 def test_HTTP_auth_failure_not_inferred_as_missing_release(self):
  class Result:returncode=1;stdout='';stderr='HTTP403 forbidden'
  with patch.object(release.subprocess,'run',lambda *a,**k:Result()):
   with self.assertRaises(RuntimeError):release.release_exists('repo/name','tag')
 def test_public_asset_set_and_payload_hashes(self):
  with tempfile.TemporaryDirectory() as tmp:
   d=Path(tmp);selection=dict(version='25.12.6',recipe_sha256='b'*64);plan=dict(version='25.12.6',tag=release.tag_for(selection));records={}
   for flavor in ['normal','lite']:
    prefix='p2812-openwrt-25.12.6-'+flavor;fw=b'NOT REAL FIRMWARE';k=kernel();text=manifest(flavor)
    (d/(prefix+'-sysupgrade.bin')).write_bytes(fw);(d/(prefix+'-kernel.uImage')).write_bytes(k);(d/(prefix+'.manifest')).write_text(text)
    records[flavor]=dict(sysupgrade_sha256=hashlib.sha256(fw).hexdigest(),kernel=build.validate_kernel(k),packages=build.validate_manifest(flavor,text))
   build.write_json(d/'build-manifest.json',dict(selection=selection,profiles=records,identical_rebuilds=2));(d/'p2812-recipes.tar.gz').write_bytes(b'TEST')
   (d/'SHA256SUMS').write_text(''.join(build.sha(p)+'  '+p.name+'\n' for p in sorted(d.iterdir())))
   release.verify_assets(d,plan)
   (d/'private-eeprom.bin').write_bytes(b'FAKE')
   with self.assertRaises(RuntimeError):release.verify_assets(d,plan)
   (d/'private-eeprom.bin').unlink();p=d/'p2812-openwrt-25.12.6-lite-sysupgrade.bin';p.write_bytes(b'CORRUPTED')
   with self.assertRaises(RuntimeError):release.verify_assets(d,plan)
if __name__=='__main__':unittest.main()
