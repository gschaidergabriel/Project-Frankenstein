#!/usr/bin/env python3
"""
Test script for deep system info endpoints.
Run: python3 test_deep_system.py
"""

import json
import urllib.request
from typing import Any, Dict

TOOLBOX_URL = "http://127.0.0.1:8096"


def post_json(endpoint: str) -> Dict[str, Any]:
    """POST to an endpoint and return JSON response."""
    url = f"{TOOLBOX_URL}{endpoint}"
    req = urllib.request.Request(
        url,
        data=b"{}",
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=10) as resp:
        return json.loads(resp.read().decode("utf-8"))


def test_drivers():
    """Test /sys/drivers endpoint."""
    print("\n=== /sys/drivers ===")
    data = post_json("/sys/drivers")
    assert data["ok"], f"Failed: {data}"
    print(f"✓ Kernel: {data.get('kernel', '')[:60]}...")
    print(f"✓ Module count: {data.get('module_count')}")

    # Show some notable drivers
    modules = data.get("modules", [])
    notable = ["amdgpu", "nvidia", "i915", "r8169", "mt7921e", "nvme", "bluetooth"]
    found = [m for m in modules if m["name"] in notable]
    if found:
        print("  Notable drivers:")
        for m in found:
            print(f"    - {m['name']}: {m.get('version', 'n/a')} ({m.get('description', '')[:40]})")
    return True


def test_usb():
    """Test /sys/usb endpoint."""
    print("\n=== /sys/usb ===")
    data = post_json("/sys/usb")
    assert data["ok"], f"Failed: {data}"
    print(f"✓ Device count: {data.get('device_count')}")

    # Show connected devices (not root hubs)
    devices = [d for d in data.get("devices", [])
               if d.get("product") and "Host Controller" not in d.get("product", "")]
    if devices:
        print("  Connected devices:")
        for d in devices[:5]:
            print(f"    - {d.get('product', '?')}: {d.get('manufacturer', '')} ({d.get('speed_mbps', '?')} Mbps)")
    return True


def test_network():
    """Test /sys/network endpoint."""
    print("\n=== /sys/network ===")
    data = post_json("/sys/network")
    assert data["ok"], f"Failed: {data}"
    print(f"✓ Interface count: {data.get('interface_count')}")
    print(f"✓ Default gateway: {data.get('default_gateway')}")

    interfaces = data.get("interfaces", [])
    for iface in interfaces:
        if iface.get("state") == "up" or iface.get("name") == "lo":
            addrs = iface.get("addresses", [])
            ipv4 = next((a["address"] for a in addrs if a.get("family") == "inet"), None)
            print(f"  {iface['name']}: {iface.get('type', '?')} - {ipv4 or 'no ip'} ({iface.get('driver', 'n/a')})")
            if iface.get("ssid"):
                print(f"    SSID: {iface['ssid']}")
    return True


def test_hardware_deep():
    """Test /sys/hardware_deep endpoint."""
    print("\n=== /sys/hardware_deep ===")
    data = post_json("/sys/hardware_deep")
    assert data["ok"], f"Failed: {data}"

    # DMI/BIOS info
    dmi = data.get("dmi", {})
    if dmi:
        print(f"✓ BIOS: {dmi.get('bios_vendor', '?')} v{dmi.get('bios_version', '?')} ({dmi.get('bios_date', '?')})")
        print(f"✓ Board: {dmi.get('board_vendor', '?')} {dmi.get('board_name', '?')}")
        print(f"✓ System: {dmi.get('sys_vendor', '?')} {dmi.get('product_name', '?')}")

    # CPU cache
    cpu = data.get("cpu_deep", {})
    cache_topo = cpu.get("cache_topology", [])
    if cache_topo:
        print(f"✓ CPU Cache: {cpu.get('cache_size', 'n/a')}")
        for c in cache_topo:
            print(f"    L{c.get('level', '?')} {c.get('type', '?')}: {c.get('size', '?')}")

    print(f"✓ CPU Flags: {cpu.get('flag_count', 0)} total")
    print(f"✓ Microcode: {cpu.get('microcode', 'n/a')}")

    # GPU
    gpus = data.get("gpu", [])
    if gpus:
        print(f"✓ GPUs: {len(gpus)}")
        for g in gpus:
            print(f"    {g.get('device', '?')}: driver={g.get('driver', '?')}")

    # Memory modules
    mem_modules = data.get("memory_modules", [])
    if mem_modules:
        print(f"✓ RAM Modules: {len(mem_modules)}")
        for m in mem_modules:
            print(f"    {m.get('Locator', '?')}: {m.get('Size', '?')} {m.get('Type', '')} @ {m.get('Speed', '')}")

    return True


def test_extended():
    """Test /sys/extended endpoint (combined)."""
    print("\n=== /sys/extended ===")
    data = post_json("/sys/extended")
    assert data["ok"], f"Failed: {data}"

    sections = [k for k in data.keys() if k not in ("ok", "ts")]
    print(f"✓ Sections: {', '.join(sections)}")

    # Check each section has data
    for section in sections:
        section_data = data.get(section, {})
        if isinstance(section_data, dict):
            is_ok = section_data.get("ok", True)
            print(f"  {section}: {'✓' if is_ok else '✗'}")

    return True


def main():
    print("=" * 50)
    print("Testing Deep System Info Endpoints")
    print("=" * 50)

    tests = [
        test_drivers,
        test_usb,
        test_network,
        test_hardware_deep,
        test_extended,
    ]

    passed = 0
    failed = 0

    for test in tests:
        try:
            test()
            passed += 1
        except AssertionError as e:
            print(f"✗ {test.__name__}: {e}")
            failed += 1
        except Exception as e:
            print(f"✗ {test.__name__}: Exception: {e}")
            failed += 1

    print("\n" + "=" * 50)
    print(f"Results: {passed} passed, {failed} failed")
    print("=" * 50)

    return failed == 0


if __name__ == "__main__":
    import sys
    success = main()
    sys.exit(0 if success else 1)
