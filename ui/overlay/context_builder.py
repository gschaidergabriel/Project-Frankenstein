"""USB/Network/Driver/HW formatting functions extracted from the monolith overlay."""

from __future__ import annotations

import re
from typing import Any, Dict

from overlay.constants import LOG


def _format_usb_context(data: Dict[str, Any]) -> str:
    """Format USB device info for context injection."""
    if not data or not data.get("ok"):
        return ""
    devices = data.get("devices", [])
    # Filter out root hubs
    real_devices = [d for d in devices if d.get("product") and "Host Controller" not in d.get("product", "")]
    if not real_devices:
        return "USB: No external devices connected"

    parts = []
    for d in real_devices[:8]:  # Limit to 8 devices
        name = d.get("product", "Unknown")
        manufacturer = d.get("manufacturer", "")
        speed = d.get("speed_mbps", "?")
        if manufacturer and manufacturer not in name:
            parts.append(f"{manufacturer} {name} ({speed}Mbps)")
        else:
            parts.append(f"{name} ({speed}Mbps)")

    return f"USB devices ({len(real_devices)}): " + ", ".join(parts)


def _format_network_context(data: Dict[str, Any]) -> str:
    """Format network info for context injection."""
    if not data or not data.get("ok"):
        return ""

    interfaces = data.get("interfaces", [])
    gateway = data.get("default_gateway", "")
    parts = []

    for iface in interfaces:
        if iface.get("name") == "lo":
            continue
        name = iface.get("name", "?")
        state = iface.get("state", "?")
        iface_type = iface.get("type", "")

        # Get IPv4 address
        addrs = iface.get("addresses", [])
        ipv4 = next((a["address"] for a in addrs if a.get("family") == "inet"), None)

        info = f"{name}({iface_type}): {state}"
        if ipv4:
            info += f", IP={ipv4}"
        if iface.get("ssid"):
            info += f", SSID={iface['ssid']}"
        if iface.get("driver"):
            info += f", Driver={iface['driver']}"

        parts.append(info)

    result = "Network: " + " | ".join(parts)
    if gateway:
        result += f" | Gateway={gateway}"
    return result


def _format_driver_context(data: Dict[str, Any], limit: int = 10, usb_focus: bool = False) -> str:
    """Format driver/module info for context injection."""
    if not data or not data.get("ok"):
        return ""

    modules = data.get("modules", [])
    kernel = data.get("kernel", "")
    kernel_ver = ""
    if kernel:
        # Extract kernel version like "6.14.0-37-generic"
        m = re.search(r"Linux version (\S+)", kernel)
        if m:
            kernel_ver = m.group(1)

    # Select relevant modules based on context
    if usb_focus:
        # USB-specific modules
        relevant = ["usbhid", "usbcore", "hid", "hid_generic", "btusb", "xhci_hcd", "ehci_hcd", "usb_storage"]
    else:
        # General notable modules
        relevant = ["amdgpu", "nvidia", "i915", "nouveau", "r8169", "iwlwifi", "mt7921e",
                    "nvme", "bluetooth", "snd_hda_intel", "usbhid"]

    found = []
    for mod in modules:
        name = mod.get("name", "")
        if name in relevant:
            ver = mod.get("version", "")
            state = mod.get("state", "")
            if ver:
                found.append(f"{name} v{ver} (active)")
            else:
                # Modules without version use kernel version
                found.append(f"{name} (kernel-integrated, active)")

    parts = []
    if kernel_ver:
        parts.append(f"Kernel {kernel_ver}")

    if found:
        parts.append(f"Relevant drivers: {', '.join(found[:limit])}")

    # Add summary
    live_count = sum(1 for m in modules if m.get("state") == "Live")
    parts.append(f"{live_count}/{len(modules)} modules active")

    return " | ".join(parts)


def _format_hardware_deep_context(data: Dict[str, Any]) -> str:
    """Format deep hardware info for context injection."""
    if not data or not data.get("ok"):
        return ""

    parts = []

    # BIOS
    dmi = data.get("dmi", {})
    if dmi.get("bios_vendor"):
        parts.append(f"BIOS: {dmi.get('bios_vendor', '?')} v{dmi.get('bios_version', '?')}")
    if dmi.get("board_name"):
        parts.append(f"Board: {dmi.get('board_name', '?')}")

    # CPU cache
    cpu = data.get("cpu_deep", {})
    cache = cpu.get("cache_size")
    if cache:
        parts.append(f"CPU-Cache: {cache}")

    # GPU
    gpus = data.get("gpu", [])
    if gpus:
        for g in gpus[:2]:
            driver = g.get("driver", "?")
            parts.append(f"GPU: {driver}")

    return " | ".join(parts) if parts else ""
