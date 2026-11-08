# P-2812HNU-F1 OpenWrt builds

This fork carries a small ImageBuilder recipe for **Zyxel P-2812HNU-F1**.
All four variants use the official stable OpenWrt `lantiq/xrx200` device kernel.
The first reviewed baseline is **25.12.6**; the daily check follows stable
**25.12.x** maintenance releases, excluding release candidates and snapshots.
A new major series requires a reviewed config/key/compatibility update.

## Relationship to upstream OpenWrt

The image-generation path follows OpenWrt's supported
[ImageBuilder workflow](https://openwrt.org/docs/guide-user/additional-software/imagebuilder).
All variants select the existing upstream device profile with
`make image PROFILE=zyxel_p-2812hnu-f1`. `normal` and `lite` are package
variants of that one device profile, not new OpenWrt hardware profiles.
The official ImageBuilder supplies the device definition, kernel, image
layout and sysupgrade metadata. `PACKAGES=` selects the variant's packages;
`FILES=` adds the explicitly scoped P2812 startup and preservation files.
CI adds input verification, repeated-build comparison and publication around
that command; it does not replace OpenWrt's image-generation rules.

The fork retains upstream's other device definitions and build system.
The P2812 files are not a global top-level `files/` overlay and are not
automatically included when building another device from the source tree.
Selecting one device in this CI is consistent with upstream's per-device
image workflow; a generic all-device CI is not required for that alignment.

The late PCI worker, optional DSM hook and preservation list remain
downstream customizations, not fixes claimed to be accepted upstream. They
are added only to these P2812 images. The PCI worker also checks the exact
F1 board at runtime; the DSM hook replaces the reviewed package init file
through `FILES=` rather than patching the shared upstream package source.
Sharing a CPU or SoC alone does not enable these customizations on another
board. If a future fix needs a rebuilt package or kernel, use OpenWrt's
package/target patch mechanisms and SDK or source build, rather than treating
this ImageBuilder job as a build of modified fork sources.

| Variant | Management | Selected DSL firmware |
| --- | --- | --- |
| `normal-stock` | LuCI + SSH, official device package defaults | OpenWrt Lantiq 5.8.1.8.1.6 |
| `normal-avm` | LuCI + SSH, official device package defaults | Embedded AVM 5.9.1.4.0.7 |
| `lite-stock` | SSH; LuCI/web/RPC UI, USB and ATM/PPPoA omitted | OpenWrt Lantiq 5.8.1.8.1.6 |
| `lite-avm` | SSH; LuCI/web/RPC UI, USB and ATM/PPPoA omitted | Embedded AVM 5.9.1.4.0.7 |

Both package variants retain Wi-Fi, VDSL/PTM, PPPoE, IPv6, DHCP/DNS and
firewall support. `stock` and `avm` select the DSL DSP, not another kernel.

All carry the same device-proven late PCI worker, which skips the rescan
when RT3062 is already present and otherwise attempts at most one rescan per
boot. It checks the board, the device-local 512-byte EEPROM and its local
checksum before triggering discovery. It does not reset hardware or alter
Wi-Fi/DSL/WAN configuration. The historical STP/MDIO kernel patches and
experimental CPU/PCI clock changes are not included. Use the MDIO1/GPHY1
P2812 U-Boot port; older custom ports that omit this initialization can leave
Ethernet ports unavailable.

`lite` is a reduced feature variant, **not proof of stable operation with
64 MiB RAM**. The development device has 128 MiB. Test normal NAND operation,
DSL/Wi-Fi/NAT load, available memory and OOM behavior before any64MiB claim.

## Builds and releases

The **P2812 OpenWrt normal/lite stock/AVM** workflow runs manually, after recipe
changes on `main`, and daily. It verifies the official checksum signature
using the pinned OpenWrt public key. The verification executable comes from
a separately SHA-256-pinned official ImageBuilder bootstrap. APK feed
signature checks remain enabled; changed keys or init bases fail closed.

The AVM DSP is extracted once per new release from the checksum-locked official
AVM image and checked against its embedded MD5 and final SHA-256. It is copied
only into the AVM variants. Vendor programs are not executed and images are
not mounted. A changed vendor input, DSL payload or init base blocks the build.

Each of the four variants builds twice in fresh ImageBuilder directories
(eight builds total). Package lists,
kernel bytes and sysupgrade bytes must match. The kernel must fit the5MiB
partition and its decoded payload must fit the16MiB bootloader bound.
The packaged rootfs is inspected with `unsquashfs4`, without mounting it.
The helper scripts, startup link, preservation list, first-boot DSL selection
and actual embedded DSP bytes must match the recipe. Stock images must not
contain the AVM DSP; AVM images must contain its exact pinned bytes.

A release contains four sysupgrade images, their kernels and package manifests,
recipe sources, `build-manifest.json`, `AVM-DSL-PROVENANCE.txt` and `SHA256SUMS`
(16 assets total). Publication occurs only after all four variants pass;
interrupted uploads remain drafts.
The source commit and exact ImageBuilder/package-input hashes are recorded.
Feeds may change or retire older packages, so retain the input cache if you
need a future rebuild with exactly the same package versions. Matching local
rebuilds do not establish matching output across every host environment.

GitHub scheduled workflows can be disabled after repository inactivity; check
Actions when returning after a long absence. No PAT, manual bootstrap release,
device credentials, serial connection or automatic flashing is required.

## Calibration and existing installations

Public builds contain **no private EEPROM, MAC addresses, PPPoE account,
Wi-Fi password or modem backup**. A fresh installation needs its own trusted
`/lib/firmware/RT3062.eeprom` (512 bytes) and
`/etc/p2812-pci.sha256` (its lowercase SHA-256 plus newline). Without these,
the PCI worker refuses to scan; do not substitute somebody else's EEPROM.

The image includes `/lib/upgrade/keep.d/p2812` to preserve those local files
on subsequent upgrades. For the **first upgrade from an older image**, the
old running OS must already include the files in its sysupgrade backup list;
a keep file inside the new image cannot retroactively fix the old backup.
Inspect `sysupgrade -l` and keep a separate verified backup before upgrading.
A reset/no-settings upgrade also requires reprovisioning private calibration.

These recipes do not install/flash anything. The P2812 partition migration
and bootloader size constraints must be checked separately. CI success is
not physical validation of the generated sysupgrade images.

## DSL selection and AVM companion

All images include the GPL `dsl_control` DSM hook already verified on the
baseline device. The official25.12.6 init base equals the reviewed25.12.0 base
byte for byte; a changed init base blocks an automatic recipe build.

The AVM variants **embed** the proprietary5.9.1.4.0.7 DSP extracted from the
official FRITZ!Box7490 / FRITZ!OS7.62 image. The source tree contains only the
extraction recipe and hashes; firmware is obtained in the runner. The DSP
remains proprietary and is not relicensed under the recipe's GPL. The vendor
image URL and both input/output hashes are recorded in the release provenance.
This provenance does not claim independently verified redistribution permission
or cryptographic verification of the vendor's outer image signature.

On initial boot after installation or upgrade, the board-checked
`99-p2812-dsl-profile` script verifies the chosen DSP hash and sets only
`network.dsl.firmware` and `network.dsl.vectoring`: stock selects the official
AnnexA path and DSM0; AVM selects the embedded file and DSM1. This also applies
when preserving settings: choosing an image deliberately selects its DSL mode.
WAN credentials, VLAN, LAN and Wi-Fi settings are retained. A wrong board or
missing/corrupt payload cannot trigger the DSL configuration changes.

The preservation list still supports a locally provisioned AVM file. A stock
upgrade may retain that file in overlay, but its first-boot selector chooses
the stock DSP. AVM variants do not require a prior AVM installation; they
still require the device's own EEPROM and checksum. The first-upgrade
calibration backup check described above remains necessary.

The separate **P2812 OpenWrt AVM DSL verification** workflow still uploads
only verification metadata and recipe sources. The integrated image workflow
is responsible for embedding the DSP in its two AVM sysupgrade images.

Vectoring capability/request and the line's negotiated active vectoring are
different facts. The device baseline requested full mode1; active vectoring
was not observed on the tested line.

## Local Linux build

Use Linux x86-64, Python3.10+, zstd and the packages listed in
`p2812-ci/Dockerfile` (or build that optional Linux container). Work outside
this source checkout:

```sh
python3 -B -m unittest discover -s p2812-ci/tests -p 'test_*.py'
python3 -B p2812-ci/build.py prepare --work /tmp/p2812-work --version 25.12.6
python3 -B p2812-ci/build.py prepare-avm --work /tmp/p2812-work
for flavor in normal lite; do
  for dsl in stock avm; do
    for round in r1 r2; do
      python3 -B p2812-ci/build.py build --work /tmp/p2812-work \
        --flavor "$flavor" --dsl "$dsl" --round "$round"
    done
  done
done
python3 -B p2812-ci/build.py bundle --work /tmp/p2812-work
```

The upstream OpenWrt source tree in this fork is not rebuilt by this first
ImageBuilder workflow. The selected stable release's prebuilt kernel/tools
are used. A full source/kernel workflow can be added later if a verified
kernel change becomes necessary. UI configuration such as VLAN35, PPPoE
credentials and software flow offloading stays device-local.
