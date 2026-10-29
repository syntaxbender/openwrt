#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Plan/publish complete normal+lite releases; no account setup or device access."""
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
 build.need(manifest['identical_rebuilds']==2 and set(manifest['profiles'])=={'normal','lite'},'Both profiles need two matching builds')
 sums={}
 for row in (directory/'SHA256SUMS').read_text().splitlines():
  match=re.fullmatch(r'([0-9a-f]{64})  ([a-zA-Z0-9_.-]+)',row);build.need(match is not None,'Invalid asset checksum row')
  name=match[2];build.need(name not in sums,'Duplicate release asset');sums[name]=match[1]
 actual={p.name for p in directory.iterdir() if p.is_file() and p.name!='SHA256SUMS'}
 build.need(actual==set(sums),'Missing/unaccounted release assets')
 for name,h in sums.items():build.need(build.sha(directory/name)==h,'Release checksum differs: '+name)
 required={'build-manifest.json','p2812-recipes.tar.gz'}
 for flavor in ['normal','lite']:
  prefix='p2812-openwrt-'+plan['version']+'-'+flavor
  required|={prefix+'-sysupgrade.bin',prefix+'-kernel.uImage',prefix+'.manifest'}
  r=manifest['profiles'][flavor]
  build.need(build.sha(directory/(prefix+'-sysupgrade.bin'))==r['sysupgrade_sha256'],'Firmware differs from build evidence')
  build.need(build.validate_kernel((directory/(prefix+'-kernel.uImage')).read_bytes())==r['kernel'],'Kernel differs from build evidence')
  build.need(build.validate_manifest(flavor,(directory/(prefix+'.manifest')).read_text())==r['packages'],'Package manifest differs from build evidence')
 build.need(actual==required,'Unexpected public artifact set');return manifest

def publish(directory,plan_path,commit):
 plan=json.loads(plan_path.read_text());build.need(plan['repository']==build.CONFIG['repository'],'Repository differs from recipe')
 build.need(re.fullmatch('[0-9a-f]{40}',commit),'Exact source commit required')
 m=verify_assets(directory,plan)
 if release_exists(plan['repository'],plan['tag']):return {'already_published':True}
 notes=directory.parent/'release-notes.md'
 notes.write_text('P-2812HNU-F1 — OpenWrt '+plan['version']+'\n\n'
 'Two matching builds of each profile passed image, kernel-size, package and overlay checks.\n\n'
 '- normal: LuCI, stock device packages and the proven late PCI startup worker.\n'
 '- lite: SSH management; Wi-Fi/VDSL/PTM/PPPoE/IPv6 retained, LuCI/USB/ATM omitted.\n'
 '- Stock official kernel, no historical STP/MDIO or experimental CPU/clock patches.\n'
 '- GPL DSM hook included; proprietary AVM DSP and private EEPROM are not embedded. Preserve/provision your own local files before upgrading.\n'
 '- These exact images have not been tested on hardware. Lite is not certified for64MiB RAM. No automatic flashing.\n\n'
 'See P2812-OPENWRT.md for calibration/AVM preservation and first-install limits.\n\n'
 'Recipe: '+commit+'\nImageBuilder: '+m['selection']['imagebuilder_sha256']+'\n'
 'Upstream sources: https://github.com/openwrt/openwrt/tree/v'+plan['version']+'\n')
 args=['gh','release','create',plan['tag'],'--repo',plan['repository'],'--target',commit,
       '--title','P2812 OpenWrt '+plan['version']+' — normal + lite','--notes-file',str(notes),'--draft']
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
