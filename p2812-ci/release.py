#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Publish all four package/DSL variants together; no device access."""
import argparse,json,os,re,subprocess
from pathlib import Path
import build

def tag_for(selection):
 build.need(build.version_ok(selection['version']) and re.fullmatch('[0-9a-f]{64}',selection['recipe_sha256']),'Invalid release identity')
 return 'p2812-openwrt-v'+selection['version']+'-'+selection['recipe_sha256'][:12]

def release_exists(repo,tag):
 p=subprocess.run(['gh','api','repos/'+repo+'/releases/tags/'+tag],capture_output=True,text=True)
 if p.returncode==0:
  r=json.loads(p.stdout);build.need(r['tag_name']==tag,'Existing release tag differs');return not r['draft']
 build.need('404' in p.stderr,'GitHub lookup failed; do not infer missing release');return False

def plan(work,query):
 s=json.loads((work/'selection.json').read_text());tag=tag_for(s)
 r={'repository':build.CONFIG['repository'],'tag':tag,'build':not(query and release_exists(build.CONFIG['repository'],tag)),
    'version':s['version'],'recipe_sha256':s['recipe_sha256']}
 build.write_json(work/'release-plan.json',r)
 if os.environ.get('GITHUB_OUTPUT'):
  with open(os.environ['GITHUB_OUTPUT'],'a') as f:
   for k,v in r.items():f.write(k+'='+('true' if v is True else 'false' if v is False else str(v))+'\n')
 return r

def verify_assets(directory,plan):
 manifest=json.loads((directory/'build-manifest.json').read_text())
 build.need(tag_for(manifest['selection'])==plan['tag'],'Published tag/manifest differs')
 variants={build.dsl_variants.identity(build.CONFIG,f,d) for f,d in build.dsl_variants.variants(build.CONFIG)}
 build.need(manifest['identical_rebuilds']==2 and set(manifest['profiles'])==variants,'All four variants need two matching builds')
 sums={}
 for row in (directory/'SHA256SUMS').read_text().splitlines():
  match=re.fullmatch(r'([0-9a-f]{64})  ([a-zA-Z0-9_.-]+)',row);build.need(match is not None,'Invalid asset checksum row')
  name=match[2];build.need(name not in sums,'Duplicate release asset');sums[name]=match[1]
 actual={p.name for p in directory.iterdir() if p.is_file() and p.name!='SHA256SUMS'}
 build.need(actual==set(sums),'Missing/unaccounted release assets')
 for name,h in sums.items():build.need(build.sha(directory/name)==h,'Release checksum differs: '+name)
 required={'build-manifest.json','p2812-recipes.tar.gz','AVM-DSL-PROVENANCE.txt'}
 lock=json.loads((build.ROOT/'p2812-dsl/inputs.lock.json').read_text())
 build.need((directory/'AVM-DSL-PROVENANCE.txt').read_bytes()==build.dsl_variants.provenance(build.CONFIG,lock),'AVM provenance differs')
 for flavor,dsl in build.dsl_variants.variants(build.CONFIG):
  variant=build.dsl_variants.identity(build.CONFIG,flavor,dsl)
  prefix='p2812-openwrt-'+plan['version']+'-'+variant
  required|={prefix+'-sysupgrade.bin',prefix+'-kernel.uImage',prefix+'.manifest'}
  r=manifest['profiles'][variant]
  build.need(r['flavor']==flavor and r['dsl']==dsl and r['variant']==variant and r['dsl_firmware']==build.dsl_variants.firmware(build.CONFIG,dsl),'DSL variant metadata differs')
  build.need(r['AVM_companion_embedded']==(dsl=='avm') and not r['own_EEPROM_embedded'] and r['overlay_verified'],'DSL payload/private calibration evidence differs')
  build.need(build.sha(directory/(prefix+'-sysupgrade.bin'))==r['sysupgrade_sha256'],'Firmware differs from build evidence')
  build.need(build.validate_kernel((directory/(prefix+'-kernel.uImage')).read_bytes())==r['kernel'],'Kernel differs from build evidence')
  build.need(build.validate_manifest(flavor,(directory/(prefix+'.manifest')).read_text())==r['packages'],'Package manifest differs from build evidence')
 build.need(len({r['kernel']['sha256'] for r in manifest['profiles'].values()})==1,'Variants must share the same official kernel')
 build.need(actual==required,'Unexpected public artifact set');return manifest

def publish(directory,plan_path,commit):
 plan=json.loads(plan_path.read_text());build.need(plan['repository']==build.CONFIG['repository'],'Repository differs from recipe')
 build.need(re.fullmatch('[0-9a-f]{40}',commit),'Exact source commit required')
 m=verify_assets(directory,plan)
 if release_exists(plan['repository'],plan['tag']):return {'already_published':True}
 notes=directory.parent/'release-notes.md'
 notes.write_text('P-2812HNU-F1 — OpenWrt '+plan['version']+'\n\n'
 'Two matching builds of all four variants passed image, kernel-size, package and DSL payload checks.\n\n'
 '- normal: LuCI, stock device packages and the proven late PCI startup worker.\n'
 '- lite: SSH management; Wi-Fi/VDSL/PTM/PPPoE/IPv6 retained, LuCI/USB/ATM omitted.\n'
 '- Stock official kernel, no historical STP/MDIO or experimental CPU/clock patches.\n'
 '- normal-stock / lite-stock: official OpenWrt DSL firmware 5.8.1.8.1.6.\n'
 '- normal-avm / lite-avm: embedded AVM DSL DSP 5.9.1.4.0.7, extracted from the hash-locked official AVM image.\n'
 '- First boot selects the variant firmware and DSM mode, including when preserving settings; WAN credentials, LAN and Wi-Fi configuration are retained.\n'
 '- AVM DSP remains proprietary; see AVM-DSL-PROVENANCE.txt. No private EEPROM or account data is embedded.\n'
 '- These exact images have not been tested on hardware. Lite is not certified for64MiB RAM. No automatic flashing.\n\n'
 'See P2812-OPENWRT.md for calibration/AVM preservation and first-install limits.\n\n'
 'Recipe: '+commit+'\nImageBuilder: '+m['selection']['imagebuilder_sha256']+'\n'
 'Upstream sources: https://github.com/openwrt/openwrt/tree/v'+plan['version']+'\n')
 args=['gh','release','create',plan['tag'],'--repo',plan['repository'],'--target',commit,
       '--title','P2812 OpenWrt '+plan['version']+' — normal/lite, stock/AVM','--notes-file',str(notes),'--draft']
 args += [str(p) for p in sorted(directory.iterdir()) if p.is_file()]
 existing=subprocess.run(['gh','api','repos/'+plan['repository']+'/releases/tags/'+plan['tag']],capture_output=True,text=True)
 if existing.returncode==0:
  build.need(json.loads(existing.stdout)['draft'],'Only an interrupted draft may be resumed')
  build.run(['gh','release','upload',plan['tag'],'--repo',plan['repository'],'--clobber',*[str(p) for p in sorted(directory.iterdir()) if p.is_file()]])
 else:
  build.need('404' in existing.stderr,'GitHub draft lookup failed');build.run(args)
 # A failed asset upload leaves a draft, never a seemingly complete release.
 build.run(['gh','release','edit',plan['tag'],'--repo',plan['repository'],'--draft=false'])
 return {'published':True,'tag':plan['tag']}

def main():
 p=argparse.ArgumentParser();sub=p.add_subparsers(dest='command',required=True)
 a=sub.add_parser('plan');a.add_argument('--work',type=Path,required=True);a.add_argument('--query-github',action='store_true')
 a=sub.add_parser('publish');a.add_argument('--assets',type=Path,required=True);a.add_argument('--plan',type=Path,required=True);a.add_argument('--commit',required=True)
 a=p.parse_args();r=plan(a.work,a.query_github) if a.command=='plan' else publish(a.assets,a.plan,a.commit);print(json.dumps(r,indent=2))
if __name__=='__main__':main()
