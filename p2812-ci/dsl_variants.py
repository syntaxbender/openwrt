#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Explicit DSL selections for the existing upstream P2812 device profile."""
import hashlib
import re


def variants(config):
    return [(flavor, dsl) for flavor in config['profiles'] for dsl in config['dsl_variants']]


def identity(config, flavor, dsl):
    if flavor not in config['profiles'] or dsl not in config['dsl_variants']:
        raise ValueError('Unknown package/DSL variant')
    return flavor + '-' + dsl


def firmware(config, dsl):
    if dsl not in config['dsl_variants']:
        raise ValueError('Unknown DSL selection')
    spec = dict(config['dsl_variants'][dsl])
    if (not re.fullmatch(r'[0-9a-f]{64}', spec['sha256']) or
            not re.fullmatch(r'/lib/firmware/[a-zA-Z0-9_.-]+', spec['path']) or
            not re.fullmatch(r'lib/firmware/[a-zA-Z0-9_.-]+', spec['rootfs_file']) or
            spec['vectoring'] not in (0, 1) or not 0 < spec['bytes'] < 4 * 1024 * 1024):
        raise ValueError('Invalid DSL firmware specification')
    return spec


def verify_firmware(config, dsl, data):
    spec = firmware(config, dsl)
    if len(data) != spec['bytes'] or hashlib.sha256(data).hexdigest() != spec['sha256']:
        raise ValueError('Unexpected ' + dsl + ' DSL payload; review upstream firmware changes')
    return spec


def firstboot(config, dsl):
    spec = firmware(config, dsl)
    board = config['board']
    if not re.fullmatch(r'[a-zA-Z0-9,_-]+', board):
        raise ValueError('Invalid board identity')
    # Runs once on initial installation or upgrade, including preserved config.
    # Select only the DSL firmware and DSM mode; retain WAN account/LAN/Wi-Fi.
    return (f'''#!/bin/sh
# P2812 DSL selection: {dsl}; do not restart services during uci-defaults.
p2812_board="$(cat /tmp/sysinfo/board_name 2>/dev/null)"
[ "$p2812_board" = '{board}' ] || exit 0
if ! printf '%s  %s\\n' '{spec['sha256']}' '{spec['path']}' | sha256sum -c - >/dev/null 2>&1; then
    logger -t p2812-dsl 'Expected {dsl} DSL firmware missing or checksum differs'
    exit 1
fi
[ "$(uci -q get network.dsl)" = dsl ] || exit 1
uci -q batch <<'P2812_DSL_EOF'
set network.dsl.firmware='{spec['path']}'
set network.dsl.vectoring='{spec['vectoring']}'
commit network
P2812_DSL_EOF
''').encode()


def provenance(config, lock):
    spec = firmware(config, 'avm')
    if (lock['firmware']['sha256'] != spec['sha256'] or
            lock['firmware']['bytes'] != spec['bytes'] or
            lock['firmware']['version'] != spec['version']):
        raise ValueError('AVM lock and selected DSP disagree')
    return ('AVM DSL DSP provenance\n\n'
            'Firmware: ' + spec['version'] + '\n'
            'Vendor image: ' + lock['vendor_image']['url'] + '\n'
            'Vendor image SHA256: ' + lock['vendor_image']['sha256'] + '\n'
            'Extracted DSP SHA256: ' + spec['sha256'] + '\n'
            'Extracted DSP bytes: ' + str(spec['bytes']) + '\n\n'
            'The AVM variants embed this proprietary DSP unchanged. It is not GPL\n'
            'source code; inclusion does not change its original vendor terms.\n'
            'Extraction checks the pinned image, embedded MD5 and DSP SHA256.\n'
            'The outer vendor signature is not independently verified.\n'
            'See p2812-dsl/inputs.lock.json and verify_avm.py in the recipe archive.\n'
            'No vendor OS, private EEPROM, MAC address or account backup is included.\n').encode()
