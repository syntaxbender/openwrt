#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Official ImageBuilder + public P2812 overlay. No device or flash access."""
import argparse,gzip,hashlib,io,json,lzma,os,re,shutil,stat,struct,subprocess,sys,tarfile,urllib.request,zlib
from pathlib import Path
import dsl_variants
HERE=Path(__file__).resolve().parent
ROOT=HERE.parent
CONFIG=json.loads((HERE/'config.json').read_text())
DOWNLOADS='https://downloads.openwrt.org/releases/'

def need(ok,message):
 if not ok:raise RuntimeError(message)
def digest(data):return hashlib.sha256(data).hexdigest()
def sha(path):return digest(path.read_bytes())
def write_json(path,data):path.write_text(json.dumps(data,indent=2,sort_keys=True)+'\n')
def run(args,**kwargs):return subprocess.run([str(x) for x in args],check=True,**kwargs)
def version_ok(v):return re.fullmatch(re.escape(CONFIG['series'])+r'\.[0-9]+',v) is not None

def fetch(url,path,expected=None,limit=128*1024*1024):
 need(url.startswith('https://downloads.openwrt.org/'),'Unexpected download host')
 if not path.exists():
  path.parent.mkdir(parents=True,exist_ok=True);tmp=path.with_suffix(path.suffix+'.partial')
  req=urllib.request.Request(url,headers={'User-Agent':'P2812-OpenWrt-CI/1'})
  with urllib.request.urlopen(req,timeout=90) as response,tmp.open('xb') as out:
   need(response.url.startswith('https://downloads.openwrt.org/'),'Unexpected redirect')
   total=0
   while True:
    block=response.read(1024*1024)
    if not block:break
    total+=len(block);need(total<=limit,'Download too large');out.write(block)
  if expected:need(sha(tmp)==expected,'Downloaded checksum differs: '+path.name)
  tmp.rename(path)
 if expected:need(sha(path)==expected,'Cached checksum differs: '+path.name)
 need(path.stat().st_size<=limit,'Cached file too large')
 return path

def latest(html):
 versions={v for v in re.findall(r'href="([0-9]+\.[0-9]+\.[0-9]+)/"',html) if version_ok(v)}
 need(versions,'No compatible stable release');return max(versions,key=lambda v:tuple(map(int,v.split('.'))))

def checksum_map(text):
 entries={}
 for row in text.splitlines():
  match=re.fullmatch(r'([0-9a-f]{64}) [ *](.+)',row)
  need(match is not None,'Malformed signed checksum row')
  key=match[2];need(key not in entries,'Duplicate checksum entry');entries[key]=match[1]
 return entries

def safe_extract(archive,destination):
 """Allow ordinary files and internal links only, without root/owner restore."""
 need(not destination.exists(),'Extraction destination already exists');destination.mkdir(parents=True)
 decoder=subprocess.Popen(['zstd','-dc',str(archive)],stdout=subprocess.PIPE);links=[];skipped=[]
 try:
  with tarfile.open(fileobj=decoder.stdout,mode='r|') as stream:
   for member in stream:
    name=Path(member.name);need(not name.is_absolute() and '..' not in name.parts,'Unsafe archive path')
    target=destination/name;need(target.resolve().is_relative_to(destination.resolve()),'Archive path escaped via link')
    if member.isdir():target.mkdir(parents=True,exist_ok=True)
    elif member.isfile():
     need(not target.is_symlink(),'Refuse file over symlink');target.parent.mkdir(parents=True,exist_ok=True)
     with stream.extractfile(member) as source,target.open('wb') as out:shutil.copyfileobj(source,out)
     target.chmod(member.mode&0o777)
    elif member.issym():
     link=Path(member.linkname)
     if link.is_absolute():
      # Official IB archives contain stale buildbot-host tool links. Drop
      # only host/bin links; OpenWrt prerequisites regenerate local tools.
      need(len(name.parts)==5 and name.parts[1:4]==('staging_dir','host','bin'),'Absolute archive symlink outside host tools')
      skipped.append(str(name));continue
     need((target.parent/link).resolve().is_relative_to(destination.resolve()),'Escaping archive symlink')
     target.parent.mkdir(parents=True,exist_ok=True);target.symlink_to(member.linkname)
    elif member.islnk():links.append((target,destination/member.linkname))
    else:raise RuntimeError('Unsupported archive member')
  for target,source in links:
   need(source.resolve().is_relative_to(destination.resolve()) and source.is_file(),'Unsafe hardlink')
   target.parent.mkdir(parents=True,exist_ok=True);os.link(source,target)
 finally:
  failed=sys.exc_info()[0] is not None
  if not failed:
   tail=decoder.stdout.read(16*1024*1024+1)
   failed_tail=len(tail)>16*1024*1024
  decoder.stdout.close();rc=decoder.wait()
  if not failed:need(not failed_tail and rc==0,'zstd extraction failed or excess tar padding')
 roots=list(destination.iterdir());need(len(roots)==1 and roots[0].is_dir(),'Unexpected archive root')
 write_json(destination.parent/(destination.name+'-extraction.json'),{'skipped_buildbot_host_absolute_links':skipped})
 return roots[0]

def recipe_hash():
 rows=[]
 for base in [HERE,ROOT/'p2812-dsl']:
  for p in sorted(base.rglob('*')):
   if p.is_file() and not any(x in p.parts for x in ['__pycache__']):rows.append((str(p.relative_to(ROOT)),sha(p)))
 return digest(json.dumps(rows,separators=(',',':')).encode())

def prepare(work,selected):
 need(not work.exists(),'Work directory must be fresh');work.mkdir(parents=True)
 cache=work/'inputs';cache.mkdir();boot=CONFIG['bootstrap'];base=DOWNLOADS+boot['version']+'/targets/'+CONFIG['target']+'/'
 archive=fetch(base+boot['archive'],cache/boot['archive'],boot['sha256'])
 bootstrap=safe_extract(archive,work/'bootstrap');usign=bootstrap/'staging_dir/host/bin/usign'
 if selected=='latest':selected=latest(fetch(DOWNLOADS,cache/'releases.html',limit=1024*1024).read_text())
 need(version_ok(selected),'Only stable '+CONFIG['series']+'.x is supported')
 base=DOWNLOADS+selected+'/targets/'+CONFIG['target']+'/'
 sums=fetch(base+'sha256sums',cache/'sha256sums',limit=16*1024*1024)
 signature=fetch(base+'sha256sums.sig',cache/'sha256sums.sig',limit=8192)
 need(sha(HERE/'keys/openwrt-checksums.pub')=='d7ac10f9ed1b38033855f3d27c9327d558444fca804c685b17d9dcfb0648228f','Checksum trust anchor changed')
 run([usign,'-V','-m',sums,'-p',HERE/'keys/openwrt-checksums.pub','-x',signature])
 sums_map=checksum_map(sums.read_text());name=f'openwrt-imagebuilder-{selected}-lantiq-xrx200.Linux-x86_64.tar.zst'
 need(name in sums_map and 'profiles.json' in sums_map,'Missing signed target inputs')
 ib=fetch(base+name,cache/name,sums_map[name]);profiles_path=fetch(base+'profiles.json',cache/'profiles.json',sums_map['profiles.json'],limit=8*1024*1024)
 profiles=json.loads(profiles_path.read_text());need(profiles['version_number']==selected and profiles['target']==CONFIG['target'] and CONFIG['profile'] in profiles['profiles'],'Target/profile metadata mismatch')
 epoch=profiles['source_date_epoch'];need(isinstance(epoch,int) and epoch>0,'Missing reproducible timestamp')
 # Verify compatibility of the GPL DSM hook with the selected official release.
 url=f'https://raw.githubusercontent.com/openwrt/openwrt/v{selected}/package/network/config/ltq-vdsl-vr9-app/files/dsl_control'
 with urllib.request.urlopen(url,timeout=30) as response:dsl=response.read(65536)
 need(digest(dsl)==CONFIG['dsl_init_base_sha256'],'DSL init changed upstream; review companion compatibility before building')
 (cache/'dsl_control').write_bytes(dsl)
 need(sha(HERE/'files/etc/init.d/dsl_control')==CONFIG['dsl_init_patched_sha256'],'Proven DSM hook differs')
 need(sha(HERE/'files/usr/sbin/p2812-pci')==CONFIG['proven_worker_sha256'] and sha(HERE/'files/etc/init.d/p2812-pci')==CONFIG['proven_init_sha256'],'Proven PCI helper changed')
 selection={'version':selected,'target':CONFIG['target'],'profile':CONFIG['profile'],'source_date_epoch':epoch,'imagebuilder_path':str(ib.resolve()),'imagebuilder_sha256':sha(ib),'checksums_signature_verified':True,'recipe_sha256':recipe_hash(),'profiles_sha256':sha(profiles_path),'bootstrap_sha256':boot['sha256']}
 write_json(work/'selection.json',selection);return selection

def prepare_avm(work):
 selection=json.loads((work/'selection.json').read_text());need(selection['recipe_sha256']==recipe_hash(),'Recipe changed after preparation')
 output=work/'avm';need(not output.exists(),'AVM verification output must be fresh')
 with (work/'avm.log').open('wb') as log:
  run([sys.executable,'-B',ROOT/'p2812-dsl/verify_avm.py','--cache',work/'dsl-inputs','--work',output],stdout=log,stderr=subprocess.STDOUT)
 lock=json.loads((ROOT/'p2812-dsl/inputs.lock.json').read_text());dsl_variants.provenance(CONFIG,lock)
 result=json.loads((output/'verification.json').read_text());spec=dsl_variants.firmware(CONFIG,'avm')
 need(result['verified'] and result['embedded_MD5_match'],'AVM extraction verification failed')
 dsl_variants.verify_firmware(CONFIG,'avm',(output/'files'/spec['rootfs_file']).read_bytes())
 need(sha(output/'files/etc/init.d/dsl_control')==CONFIG['dsl_init_patched_sha256'],'Extracted companion init differs')
 return {'verified':True,'firmware_sha256':spec['sha256'],'firmware_bytes':spec['bytes']}

def package_names(manifest):
 names=[]
 for line in manifest.splitlines():
  match=re.fullmatch(r'([^\s]+) - (.+)',line)
  need(match is not None,'Unexpected manifest format');names.append(match[1])
 need(len(names)==len(set(names)),'Duplicate package names');return set(names)

def validate_manifest(flavor,manifest):
 names=package_names(manifest)
 need(set(CONFIG['required_packages'])<=names,'Required DSL/WiFi/router package missing')
 if flavor=='normal':need('luci-base' in names and 'uhttpd' in names,'Normal UI stack missing')
 else:
  forbidden={x[1:] for x in CONFIG['profiles']['lite']['packages'] if x.startswith('-')}
  need(not(forbidden&names) and not any(x.startswith('luci-') for x in names),'Lite still includes removed UI/USB/ATM packages')
 return sorted(names)

def validate_kernel(data):
 need(len(data)>=64 and len(data)<=CONFIG['kernel_partition_bytes'],'Kernel outside5MiB partition')
 magic,hcrc,stamp,size,load,entry,dcrc,osid,arch,kind,compression,name=struct.unpack('>7I4B32s',data[:64])
 header=data[:4]+bytes(4)+data[8:64];need(magic==0x27051956 and zlib.crc32(header)==hcrc,'Invalid uImage header')
 need(size==len(data)-64 and zlib.crc32(data[64:])==dcrc,'Kernel data CRC mismatch')
 need((osid,arch,kind,compression)==(5,5,2,3) and load==entry==0x80002000,'Unexpected P2812 kernel format')
 decoder=lzma.LZMADecompressor(format=lzma.FORMAT_ALONE);raw=decoder.decompress(data[64:],max_length=CONFIG['max_decoded_kernel_bytes']+1)
 need(decoder.eof and not decoder.unused_data and len(raw)<=CONFIG['max_decoded_kernel_bytes'],'Kernel decode exceeds16MiB or trailingdata')
 return {'compressed_bytes':len(data),'decoded_bytes':len(raw),'sha256':digest(data),'CRC32':f'{dcrc:08x}'}

def validate_output(builder,out,flavor,dsl,selection):
 images=list(out.glob('*zyxel_p-2812hnu-f1*sysupgrade.bin'));need(len(images)==1,'Expected exactly one P2812 sysupgrade image')
 image=images[0];manifest=list(out.glob('*.manifest'));need(len(manifest)==1,'Expected one package manifest')
 names=validate_manifest(flavor,manifest[0].read_text())
 with tarfile.open(image) as archive:
  kernels=[m for m in archive if m.name.endswith('/kernel')];need(len(kernels)==1 and kernels[0].isfile(),'Kernel member missing')
  kernel=archive.extractfile(kernels[0]).read(CONFIG['kernel_partition_bytes']+1)
  roots=[m for m in archive if m.name.endswith('/root')];need(len(roots)==1 and roots[0].isfile() and roots[0].size<128*1024*1024,'Root member missing/oversize')
  rootfs=out/'rootfs.check';rootfs.write_bytes(archive.extractfile(roots[0]).read())
 info=validate_kernel(kernel)
 tool=builder/'staging_dir/host/bin/unsquashfs4'
 paths=['usr/sbin/p2812-pci','etc/init.d/p2812-pci','etc/init.d/dsl_control','lib/upgrade/keep.d/p2812','etc/p2812-ci.json','etc/uci-defaults/99-p2812-dsl-profile']
 for name in paths:
  actual=subprocess.check_output([str(tool),'-cat',str(rootfs),name],stderr=subprocess.DEVNULL)
  need(actual==(out/'overlay'/name).read_bytes(),'Rootfs overlay differs: '+name)
 listing=subprocess.check_output([str(tool),'-ll',str(rootfs)],stderr=subprocess.DEVNULL).decode()
 need(re.search(r'S99p2812-pci -> (?:\.\./init.d/p2812-pci|/etc/init.d/p2812-pci)',listing),'Startup symlink missing')
 need(not re.search(r'/RT3062\.eeprom$',listing,re.M),'Private calibration embedded')
 avm_present='avm-vrx200-a-5.9.1.4.0.7.bin' in listing
 need(avm_present==(dsl=='avm'),'Wrong DSL companion presence for '+dsl)
 spec=dsl_variants.firmware(CONFIG,dsl)
 payload=subprocess.check_output([str(tool),'-cat',str(rootfs),spec['rootfs_file']],stderr=subprocess.DEVNULL)
 dsl_variants.verify_firmware(CONFIG,dsl,payload)
 need('lantiq-vrx200-a.bin -> xcpe_581816_580B11.bin' in listing,'Stock firmware alias differs')
 (out/'kernel.uImage').write_bytes(kernel);rootfs.unlink()
 return {'version':selection['version'],'flavor':flavor,'dsl':dsl,'variant':dsl_variants.identity(CONFIG,flavor,dsl),'dsl_firmware':spec,'hardware_tested':False,'stable_64MiB_proven':False,'kernel':info,'sysupgrade_sha256':sha(image),'sysupgrade_bytes':image.stat().st_size,'packages':names,'overlay_verified':True,'PCI_worker_same_as_device_proven':True,'own_EEPROM_embedded':False,'AVM_companion_embedded':dsl=='avm','NAND_or_device_access':False}

def build(work,flavor,dsl,round_id):
 selection=json.loads((work/'selection.json').read_text());need(selection['recipe_sha256']==recipe_hash(),'Recipe changed after preparation')
 need(flavor in CONFIG['profiles'] and re.fullmatch(r'[a-zA-Z0-9_-]+',round_id),'Unknown build profile/run')
 variant=dsl_variants.identity(CONFIG,flavor,dsl)
 out=work/(variant+'-'+round_id);need(not out.exists(),'Build output must be fresh');out.mkdir()
 builder=safe_extract(Path(selection['imagebuilder_path']),out/'builder')
 text=(builder/'.config').read_text();need('CONFIG_SIGNATURE_CHECK=y' in text and 'CONFIG_USE_APK=y' in text,'Signed APK verification not enabled')
 overlay=out/'overlay';shutil.copytree(HERE/'files',overlay,symlinks=True)
 spec=dsl_variants.firmware(CONFIG,dsl)
 if dsl=='avm':
  verified=json.loads((work/'avm/verification.json').read_text());need(verified['verified'] and verified['embedded_MD5_match'],'Run prepare-avm before AVM builds')
  source=work/'avm/files'/spec['rootfs_file'];dsl_variants.verify_firmware(CONFIG,dsl,source.read_bytes())
  target=overlay/spec['rootfs_file'];target.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(source,target);target.chmod(0o644)
 firstboot=overlay/'etc/uci-defaults/99-p2812-dsl-profile';firstboot.parent.mkdir(parents=True,exist_ok=True);firstboot.write_bytes(dsl_variants.firstboot(CONFIG,dsl));firstboot.chmod(0o755)
 write_json(overlay/'etc/p2812-ci.json',{'version':selection['version'],'flavor':flavor,'dsl':dsl,'variant':variant,'dsl_firmware':spec,'AVM_companion_embedded':dsl=='avm','recipe_sha256':selection['recipe_sha256'],'private_calibration':'Provision or preserve your own RT3062.eeprom and checksum locally.','stable_64MiB_proven':False})
 epoch=selection['source_date_epoch']
 for p in overlay.rglob('*'):
  if not p.is_symlink():os.utime(p,(epoch,epoch))
 env=dict(os.environ,SOURCE_DATE_EPOCH=str(epoch),LC_ALL='C.UTF-8',TZ='UTC')
 args=['make','image','PROFILE='+CONFIG['profile'],'PACKAGES='+' '.join(CONFIG['profiles'][flavor]['packages']),
       'FILES='+str(overlay.resolve()),'BIN_DIR='+str(out.resolve()),'EXTRA_IMAGE_NAME=p2812-'+variant]
 with (out/'build.log').open('wb') as log:run(args,cwd=builder,env=env,stdout=log,stderr=subprocess.STDOUT)
 result=validate_output(builder,out,flavor,dsl,selection)
 result['package_inputs_sha256']={str(p.relative_to(builder)):sha(p) for p in sorted((builder/'dl').rglob('*')) if p.is_file() and p.suffix in ['.apk','.adb']}
 write_json(out/'result.json',result);return result

def bundle(work,rounds):
 need(len(rounds)==2 and len(set(rounds))==2,'Two distinct build rounds are required')
 selection=json.loads((work/'selection.json').read_text());assets=work/'release-assets';need(not assets.exists(),'Release assets already exist');assets.mkdir()
 results={}
 for flavor,dsl in dsl_variants.variants(CONFIG):
  variant=dsl_variants.identity(CONFIG,flavor,dsl)
  dirs=[work/(variant+'-'+r) for r in rounds];records=[json.loads((d/'result.json').read_text()) for d in dirs]
  need(all(r['version']==selection['version'] and r['flavor']==flavor and r['dsl']==dsl and r['variant']==variant and r['overlay_verified'] and r['dsl_firmware']==dsl_variants.firmware(CONFIG,dsl) and r['AVM_companion_embedded']==(dsl=='avm') and not r['own_EEPROM_embedded'] for r in records),'Build evidence identity differs')
  need(all(r['kernel']==records[0]['kernel'] and r['sysupgrade_sha256']==records[0]['sysupgrade_sha256'] and r['packages']==records[0]['packages'] for r in records),'Repeated build differs: '+variant)
  out=dirs[0];prefix='p2812-openwrt-'+selection['version']+'-'+variant
  image=next(out.glob('*zyxel_p-2812hnu-f1*sysupgrade.bin'));shutil.copy2(image,assets/(prefix+'-sysupgrade.bin'))
  shutil.copy2(out/'kernel.uImage',assets/(prefix+'-kernel.uImage'))
  shutil.copy2(next(out.glob('*.manifest')),assets/(prefix+'.manifest'))
  results[variant]=records[0]
 need(len({r['kernel']['sha256'] for r in results.values()})==1,'Unexpected kernel difference between profiles')
 report={'selection':{k:v for k,v in selection.items() if not k.endswith('_path')},'profiles':results,'identical_rebuilds':len(rounds),
         'scope':'Official ImageBuilder; no kernel patches or NAPI changes. Four normal/lite x stock/AVM images. AVM variants embed the verified proprietary DSP; no private calibration or credentials. Firmware builds, not hardware validation.'}
 write_json(assets/'build-manifest.json',report)
 (assets/'AVM-DSL-PROVENANCE.txt').write_bytes(dsl_variants.provenance(CONFIG,json.loads((ROOT/'p2812-dsl/inputs.lock.json').read_text())))
 paths=[p for base in [HERE,ROOT/'p2812-dsl'] for p in base.rglob('*') if p.is_file() and '__pycache__' not in p.parts]
 paths += [ROOT/'P2812-OPENWRT.md',ROOT/'.github/workflows/p2812-openwrt.yml',ROOT/'.github/workflows/p2812-dsl-avm.yml']
 buffer=io.BytesIO()
 with tarfile.open(fileobj=buffer,mode='w') as archive:
  for p in sorted(paths):
   info=archive.gettarinfo(p,arcname=str(p.relative_to(ROOT)))
   info.uid=info.gid=0;info.uname=info.gname='root';info.mtime=selection['source_date_epoch']
   if info.isfile():
    with p.open('rb') as data:archive.addfile(info,data)
   else:archive.addfile(info)
 (assets/'p2812-recipes.tar.gz').write_bytes(gzip.compress(buffer.getvalue(),mtime=0))
 sums=''.join(sha(p)+'  '+p.name+'\n' for p in sorted(assets.iterdir()) if p.is_file());(assets/'SHA256SUMS').write_text(sums)
 return report

def main():
 p=argparse.ArgumentParser(description=__doc__);sub=p.add_subparsers(dest='command',required=True)
 a=sub.add_parser('prepare');a.add_argument('--work',type=Path,required=True);a.add_argument('--version',default='latest')
 a=sub.add_parser('prepare-avm');a.add_argument('--work',type=Path,required=True)
 a=sub.add_parser('build');a.add_argument('--work',type=Path,required=True);a.add_argument('--flavor',choices=CONFIG['profiles'],required=True);a.add_argument('--dsl',choices=CONFIG['dsl_variants'],required=True);a.add_argument('--round',default='r1')
 a=sub.add_parser('bundle');a.add_argument('--work',type=Path,required=True);a.add_argument('--rounds',nargs='+',default=['r1','r2'])
 a=p.parse_args();work=a.work.resolve();need(not work.is_relative_to(ROOT),'Build outside repository')
 if a.command=='prepare':result=prepare(work,a.version)
 elif a.command=='prepare-avm':result=prepare_avm(work)
 elif a.command=='build':result=build(work,a.flavor,a.dsl,a.round)
 else:result=bundle(work,a.rounds)
 print(json.dumps(result,indent=2,sort_keys=True))
if __name__=='__main__':main()
