# P-2812HNU-F1 OpenWrt builds

This fork carries a small ImageBuilder recipe for **Zyxel P-2812HNU-F1**.
Both profiles use the official stable OpenWrt `lantiq/xrx200` device kernel.
The first reviewed baseline is **25.12.6**; the daily check follows stable
**25.12.x** maintenance releases, excluding release candidates and snapshots.
A new major series requires a reviewed config/key/compatibility update.

| Profile | Management | Retained | Removed |
| --- | --- | --- | --- |
| `normal` | LuCI + SSH | Official device defaults, VDSL/PTM, PPPoE, Wi-Fi, IPv6, USB/ATM support | None from official defaults |
| `lite` | SSH | VDSL/PTM, PPPoE, Wi-Fi, IPv6, DHCP/DNS, firewall | LuCI/web/RPC UI stack, USB host/LED support, ATM/PPPoA |

Both carry the same device-proven late PCI worker, which skips the rescan
when RT3062 is already present and otherwise attempts at most one rescan per
boot. It checks the board, the device-local 512-byte EEPROM and its local
checksum before triggering discovery. It does not reset hardware or alter
Wi-Fi/DSL/WAN configuration. The historical STP/MDIO kernel patches and
experimental CPU/PCI clock changes are not included. Use the MDIO1/GPHY1
P2812 U-Boot port; older custom ports that omit this initialization can leave
Ethernet ports unavailable.

`lite` is a reduced feature profile, **not proof of stable operation with
64 MiB RAM**. The development device has 128 MiB. Test normal NAND operation,
DSL/Wi-Fi/NAT load, available memory and OOM behavior before any64MiB claim.

## Builds and releases

The **P2812 OpenWrt normal and lite** workflow runs manually, after recipe
changes on `main`, and daily. It verifies the official checksum signature
using the pinned OpenWrt public key. The verification executable comes from
a separately SHA-256-pinned official ImageBuilder bootstrap. APK feed
signature checks remain enabled; changed keys or init bases fail closed.

Each profile builds twice in fresh ImageBuilder directories. Package lists,
kernel bytes and sysupgrade bytes must match. The kernel must fit the5MiB
partition and its decoded payload must fit the16MiB bootloader bound.
The packaged rootfs is inspected with `unsquashfs4`, without mounting it.
The helper scripts, startup link and preservation list must match the recipe.

A release contains the two sysupgrade images, their kernels and package
manifests, recipe sources, `build-manifest.json` and `SHA256SUMS`. Publication
occurs only after both profiles pass; interrupted uploads remain drafts.
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

## AVM DSL companion

Both images include the GPL `dsl_control` DSM hook already verified on the
baseline device. The official25.12.6 init base equals the reviewed25.12.0 base
byte for byte; a changed init base blocks an automatic recipe build.

The proprietary AVM5.9.1.4.0.7 DSP is **not embedded in public images**.
`p2812-dsl/` retains the checksum-locked official AVM extraction recipe and
its independent verification workflow. It never publishes the DSP or vendor
images. The preservation list includes a locally installed
`/lib/firmware/avm-vrx200-a-5.9.1.4.0.7.bin`; the first upgrade needs the same
old-backup-list check described above. Preserve the existing DSL selection
only when that firmware file is also preserved. Fresh images use stock
OpenWrt DSL packages until AVM is deliberately provisioned locally.

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
python3 -B p2812-ci/build.py build --work /tmp/p2812-work --flavor normal --round r1
python3 -B p2812-ci/build.py build --work /tmp/p2812-work --flavor normal --round r2
python3 -B p2812-ci/build.py build --work /tmp/p2812-work --flavor lite --round r1
python3 -B p2812-ci/build.py build --work /tmp/p2812-work --flavor lite --round r2
python3 -B p2812-ci/build.py bundle --work /tmp/p2812-work
```

The upstream OpenWrt source tree in this fork is not rebuilt by this first
ImageBuilder workflow. The selected stable release's prebuilt kernel/tools
are used. A full source/kernel workflow can be added later if a verified
kernel change becomes necessary. UI configuration such as VLAN35, PPPoE
credentials and software flow offloading stays device-local.
