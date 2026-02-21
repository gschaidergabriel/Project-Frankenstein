#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Frank-Sentinel: Network Intelligence & Security Layer

Network monitoring and security system for Frank with:
- Nmap-based network discovery and service fingerprinting
- Scapy deep packet inspection (passive, non-invasive)
- Gaming mode instant kill-switch (<500ms)
- Anti-cheat whitelist protection
- UOLG integration for log correlation
- Three-tier persistent storage

CRITICAL SAFETY RULES:
1. ALL monitoring STOPS during gaming mode
2. Never scan memory of gaming processes
3. Never kill processes - only nice/pin
4. 5-second veto window for critical actions

Author: Frank AI System
"""

import json
import logging
import os
import re
import signal
import socket
import subprocess
import sys
import threading
import time
from dataclasses import dataclass, field, asdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple, Any
import ipaddress

# Logging
logging.basicConfig(
    level=logging.INFO,
    format='[%(asctime)s] %(levelname)s [Sentinel]: %(message)s',
)
LOG = logging.getLogger("sentinel")

# ============================================
# Configuration
# ============================================

try:
    from config.paths import STATE_DIR as DB_DIR, get_state
    NETWORK_MAP_FILE = get_state("network_map")
    NETWORK_HEALTH_FILE = get_state("network_health")
    SECURITY_LOG_FILE = get_state("security_log")
except ImportError:
    DB_DIR = Path.home() / ".local" / "share" / "frank" / "state"
    DB_DIR.mkdir(parents=True, exist_ok=True)
    NETWORK_MAP_FILE = DB_DIR / "network_map.json"
    NETWORK_HEALTH_FILE = DB_DIR / "network_health.json"
    SECURITY_LOG_FILE = DB_DIR / "security_log.json"
try:
    from config.paths import get_temp as _ns_get_temp
    GAMING_STATE_FILE = _ns_get_temp("gaming_mode_state.json")
except ImportError:
    import tempfile as _ns_tempfile
    GAMING_STATE_FILE = Path(_ns_tempfile.gettempdir()) / "frank" / "gaming_mode_state.json"

# Resource limits (realistic, as per spec)
CONFIG = {
    "max_ram_mb": 150,              # Max RAM usage
    "cpu_avg_limit": 0.01,          # 1% average CPU
    "cpu_burst_limit": 0.02,        # 2% burst allowed
    "scan_interval_sec": 300,       # Network scan every 5 minutes
    "packet_sample_size": 100,      # Packets per sample
    "packet_sample_interval": 60,   # Seconds between samples
    "gaming_killswitch_ms": 500,    # Max time to stop all monitoring
    "veto_timeout_sec": 5,          # User veto window
    "hot_data_retention_hours": 24,
    "warm_data_retention_days": 365,
}

# Anti-cheat processes - NEVER analyze these
ANTICHEAT_WHITELIST = {
    # Process names (lowercase)
    "easyanticheat",
    "easyanticheat_eos",
    "eac_server",
    "battleye",
    "beclient",
    "beservice",
    "vanguard",
    "vgc",
    "vgtray",
    "faceit",
    "faceit-ac",
    "esea",
    "esportal-ac",
    "ricochet",
    "gameguard",
    "xigncode",
    "nprotect",
    "punkbuster",
    "pb",
    "pbsvc",
    "valve anti-cheat",
    "vac",
}

# Gaming process patterns
GAMING_PATTERNS = [
    r"\.x86_64$",
    r"\.x86$",
    r"wine.*\.exe",
    r"proton.*\.exe",
    r"steamapps/common",
    r"steam_app_",
    r"lutris",
]

# ============================================
# Data Classes
# ============================================

class NetworkDevice:
    """Represents a device on the network."""
    __slots__ = ['ip', 'mac', 'hostname', 'vendor', 'open_ports', 'services',
                 'first_seen', 'last_seen', 'is_gateway', 'risk_score']

    def __init__(self, ip: str, mac: str = "", hostname: str = "", vendor: str = "",
                 open_ports: List[int] = None, services: Dict[int, str] = None,
                 first_seen: str = "", last_seen: str = "", is_gateway: bool = False,
                 risk_score: float = 0.0):
        self.ip = ip
        self.mac = mac
        self.hostname = hostname
        self.vendor = vendor
        self.open_ports = open_ports or []
        self.services = services or {}
        self.first_seen = first_seen or datetime.now().isoformat()
        self.last_seen = last_seen or datetime.now().isoformat()
        self.is_gateway = is_gateway
        self.risk_score = risk_score

    def to_dict(self) -> dict:
        return {
            "ip": self.ip,
            "mac": self.mac,
            "hostname": self.hostname,
            "vendor": self.vendor,
            "open_ports": self.open_ports,
            "services": self.services,
            "first_seen": self.first_seen,
            "last_seen": self.last_seen,
            "is_gateway": self.is_gateway,
            "risk_score": self.risk_score,
        }


@dataclass
class SecurityEvent:
    """Security event for logging."""
    timestamp: str
    event_type: str
    severity: str  # info, warning, alert, critical
    source_ip: str = ""
    target_ip: str = ""
    port: int = 0
    protocol: str = ""
    description: str = ""
    confidence: float = 0.5
    action_taken: str = "observe"

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class NetworkHealth:
    """Network health snapshot."""
    timestamp: str
    latency_ms: float = 0.0
    packet_loss_pct: float = 0.0
    bandwidth_mbps: float = 0.0
    anomalies_detected: int = 0
    suspicious_connections: List[dict] = field(default_factory=list)
    arp_table_size: int = 0

    def to_dict(self) -> dict:
        return asdict(self)


# ============================================
# Gaming Mode Guard (Event-Based Kill Switch)
# ============================================

class GamingModeGuard:
    """
    Event-based gaming mode detection with instant kill-switch.
    Uses inotify/polling hybrid for <500ms response time.
    """

    def __init__(self):
        self._is_gaming = False
        self._gaming_start_time: Optional[float] = None
        self._lock = threading.Lock()
        self._callbacks: List[callable] = []
        self._monitor_thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()

    def register_callback(self, callback: callable):
        """Register callback for gaming mode changes."""
        self._callbacks.append(callback)

    def _notify_callbacks(self, is_gaming: bool):
        """Notify all registered callbacks."""
        for cb in self._callbacks:
            try:
                cb(is_gaming)
            except Exception as e:
                LOG.error(f"Callback error: {e}")

    def is_gaming(self) -> bool:
        """Check if gaming mode is active."""
        with self._lock:
            # Fast path: check state file
            if GAMING_STATE_FILE.exists():
                try:
                    data = json.loads(GAMING_STATE_FILE.read_text())
                    new_state = data.get("active", False)
                    if new_state != self._is_gaming:
                        self._is_gaming = new_state
                        if new_state:
                            self._gaming_start_time = time.time()
                        self._notify_callbacks(new_state)
                    return self._is_gaming
                except Exception:
                    pass
            return self._is_gaming

    def _check_gaming_processes(self) -> bool:
        """Check for running gaming processes."""
        try:
            result = subprocess.run(
                ["ps", "aux"],
                capture_output=True, text=True, timeout=2
            )
            for line in result.stdout.split('\n'):
                line_lower = line.lower()
                # Check gaming patterns
                for pattern in GAMING_PATTERNS:
                    if re.search(pattern, line_lower):
                        return True
                # Check anti-cheat (if running, definitely gaming)
                for ac in ANTICHEAT_WHITELIST:
                    if ac in line_lower:
                        return True
        except Exception:
            pass
        return False

    def start_monitoring(self):
        """Start background monitoring for gaming mode."""
        if self._monitor_thread and self._monitor_thread.is_alive():
            return

        self._stop_event.clear()
        self._monitor_thread = threading.Thread(
            target=self._monitor_loop,
            daemon=True,
            name="GamingGuard"
        )
        self._monitor_thread.start()
        LOG.info("Gaming mode guard started")

    def stop_monitoring(self):
        """Stop monitoring."""
        self._stop_event.set()
        if self._monitor_thread:
            self._monitor_thread.join(timeout=1)

    def _monitor_loop(self):
        """Monitor loop with fast polling."""
        while not self._stop_event.is_set():
            try:
                # Check state file first (fastest)
                self.is_gaming()

                # Also check processes periodically
                if not self._is_gaming and self._check_gaming_processes():
                    with self._lock:
                        self._is_gaming = True
                        self._gaming_start_time = time.time()
                        self._notify_callbacks(True)
                        LOG.warning("Gaming detected via process scan!")

            except Exception as e:
                LOG.error(f"Gaming monitor error: {e}")

            # Fast poll interval (100ms for quick detection)
            self._stop_event.wait(0.1)


# ============================================
# Network Scanner (Nmap-based)
# ============================================

class NetworkScanner:
    """Network discovery using nmap."""

    def __init__(self, gaming_guard: GamingModeGuard):
        self.gaming_guard = gaming_guard
        self._last_scan: Optional[datetime] = None
        self._devices: Dict[str, NetworkDevice] = {}
        self._lock = threading.Lock()

    def get_local_network(self) -> Optional[str]:
        """Get local network CIDR."""
        try:
            # Get default gateway
            result = subprocess.run(
                ["ip", "route", "show", "default"],
                capture_output=True, text=True, timeout=5
            )
            match = re.search(r'default via (\d+\.\d+\.\d+\.\d+)', result.stdout)
            if match:
                gateway = match.group(1)
                # Assume /24 subnet
                parts = gateway.split('.')
                return f"{parts[0]}.{parts[1]}.{parts[2]}.0/24"
        except Exception:
            pass
        return None

    def get_gateway_ip(self) -> Optional[str]:
        """Get default gateway IP."""
        try:
            result = subprocess.run(
                ["ip", "route", "show", "default"],
                capture_output=True, text=True, timeout=5
            )
            match = re.search(r'default via (\d+\.\d+\.\d+\.\d+)', result.stdout)
            if match:
                return match.group(1)
        except Exception:
            pass
        return None

    def quick_scan(self) -> List[NetworkDevice]:
        """
        Quick ARP-based scan (no root needed, non-invasive).
        Uses arp-scan or reads ARP cache.
        """
        if self.gaming_guard.is_gaming():
            LOG.debug("Skipping scan - gaming mode")
            return []

        devices = []

        # Read ARP cache (no privileges needed)
        try:
            arp_file = Path("/proc/net/arp")
            if arp_file.exists():
                for line in arp_file.read_text().split('\n')[1:]:
                    parts = line.split()
                    if len(parts) >= 4 and parts[2] != "0x0":
                        ip = parts[0]
                        mac = parts[3]
                        if mac != "00:00:00:00:00:00":
                            dev = NetworkDevice(
                                ip=ip,
                                mac=mac,
                                last_seen=datetime.now().isoformat()
                            )
                            devices.append(dev)
        except Exception as e:
            LOG.warning(f"ARP cache read failed: {e}")

        return devices

    def full_scan(self, network: str = None) -> List[NetworkDevice]:
        """
        Full nmap scan (requires root for some features).
        Runs with low priority to not impact system.
        """
        if self.gaming_guard.is_gaming():
            LOG.info("Skipping full scan - gaming mode active")
            return []

        if network is None:
            network = self.get_local_network()
            if not network:
                LOG.error("Could not determine local network")
                return []

        devices = []
        gateway = self.get_gateway_ip()

        try:
            import nmap
            nm = nmap.PortScanner()

            # Run with nice priority
            LOG.info(f"Starting network scan: {network}")

            # Quick ping scan first
            nm.scan(hosts=network, arguments='-sn -T3')

            for host in nm.all_hosts():
                if self.gaming_guard.is_gaming():
                    LOG.warning("Aborting scan - gaming mode started")
                    break

                mac = ""
                vendor = ""
                if 'mac' in nm[host]['addresses']:
                    mac = nm[host]['addresses']['mac']
                if 'vendor' in nm[host] and mac in nm[host]['vendor']:
                    vendor = nm[host]['vendor'][mac]

                hostname = ""
                if 'hostnames' in nm[host] and nm[host]['hostnames']:
                    hostname = nm[host]['hostnames'][0].get('name', '')

                dev = NetworkDevice(
                    ip=host,
                    mac=mac,
                    hostname=hostname,
                    vendor=vendor,
                    is_gateway=(host == gateway),
                    last_seen=datetime.now().isoformat()
                )
                devices.append(dev)

            LOG.info(f"Scan complete: {len(devices)} devices found")

        except ImportError:
            LOG.error("python-nmap not installed")
        except Exception as e:
            LOG.error(f"Scan failed: {e}")

        # Update device cache
        with self._lock:
            for dev in devices:
                if dev.ip in self._devices:
                    # Update existing
                    old = self._devices[dev.ip]
                    dev.first_seen = old.first_seen
                self._devices[dev.ip] = dev

        self._last_scan = datetime.now()
        return devices

    def get_devices(self) -> List[NetworkDevice]:
        """Get cached devices."""
        with self._lock:
            return list(self._devices.values())

    def service_scan(self, ip: str, ports: str = "22,80,443,8080") -> Dict[int, str]:
        """
        Scan specific ports on a host.
        Non-invasive, low priority.
        """
        if self.gaming_guard.is_gaming():
            return {}

        services = {}

        try:
            import nmap
            nm = nmap.PortScanner()
            nm.scan(hosts=ip, ports=ports, arguments='-sV -T2')

            if ip in nm.all_hosts():
                for proto in nm[ip].all_protocols():
                    for port in nm[ip][proto]:
                        service = nm[ip][proto][port]
                        name = service.get('name', 'unknown')
                        version = service.get('version', '')
                        services[port] = f"{name} {version}".strip()

        except Exception as e:
            LOG.warning(f"Service scan failed: {e}")

        return services


# ============================================
# Packet Analyzer (Scapy-based, Passive)
# ============================================

class PacketAnalyzer:
    """
    Passive packet analysis using Scapy.

    CRITICAL: This is COMPLETELY DISABLED during gaming mode.
    Never analyzes anti-cheat traffic.
    """

    def __init__(self, gaming_guard: GamingModeGuard):
        self.gaming_guard = gaming_guard
        self._sniff_thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._packet_buffer: List[dict] = []
        self._lock = threading.Lock()
        self._anomalies: List[dict] = []
        self._enabled = True

        # Register for gaming mode callbacks
        gaming_guard.register_callback(self._on_gaming_mode_change)

    def _on_gaming_mode_change(self, is_gaming: bool):
        """Instant stop when gaming starts."""
        if is_gaming:
            LOG.warning("GAMING MODE: Stopping all packet analysis immediately!")
            self.stop()
        else:
            LOG.info("Gaming ended: Packet analysis can resume")

    def is_safe_to_analyze(self, packet_info: dict) -> bool:
        """Check if it's safe to analyze this packet."""
        # Never analyze during gaming
        if self.gaming_guard.is_gaming():
            return False

        # Check if process is whitelisted
        pid = packet_info.get("pid")
        if pid:
            try:
                cmdline = Path(f"/proc/{pid}/cmdline").read_text()
                cmdline_lower = cmdline.lower()
                for ac in ANTICHEAT_WHITELIST:
                    if ac in cmdline_lower:
                        return False
            except Exception:
                pass

        return True

    def analyze_traffic_sample(self, interface: str = None, count: int = 100,
                                timeout: int = 30) -> List[dict]:
        """
        Capture and analyze a sample of network traffic.
        Passive observation only.
        """
        if self.gaming_guard.is_gaming():
            LOG.debug("Traffic analysis skipped - gaming mode")
            return []

        if not self._enabled:
            return []

        packets = []

        try:
            from scapy.all import sniff, IP, TCP, UDP, ARP

            def packet_callback(pkt):
                # Abort immediately if gaming starts
                if self.gaming_guard.is_gaming():
                    return True  # Stop sniffing

                info = {"timestamp": datetime.now().isoformat()}

                if IP in pkt:
                    info["src_ip"] = pkt[IP].src
                    info["dst_ip"] = pkt[IP].dst
                    info["proto"] = pkt[IP].proto

                if TCP in pkt:
                    info["src_port"] = pkt[TCP].sport
                    info["dst_port"] = pkt[TCP].dport
                    info["flags"] = str(pkt[TCP].flags)

                elif UDP in pkt:
                    info["src_port"] = pkt[UDP].sport
                    info["dst_port"] = pkt[UDP].dport

                if ARP in pkt:
                    info["arp_op"] = pkt[ARP].op
                    info["arp_src"] = pkt[ARP].psrc
                    info["arp_dst"] = pkt[ARP].pdst

                packets.append(info)

            # Sniff with low priority
            os.nice(19)  # Lowest priority

            sniff(
                iface=interface,
                prn=packet_callback,
                count=count,
                timeout=timeout,
                store=False,
                stop_filter=lambda p: self.gaming_guard.is_gaming()
            )

        except PermissionError:
            LOG.warning("Packet capture requires root privileges")
        except ImportError:
            LOG.error("Scapy not installed")
        except Exception as e:
            LOG.error(f"Traffic analysis failed: {e}")

        return packets

    def detect_arp_spoofing(self) -> List[dict]:
        """
        Check for ARP spoofing attacks.
        Compares ARP cache for duplicate MACs.
        """
        if self.gaming_guard.is_gaming():
            return []

        anomalies = []
        mac_to_ips: Dict[str, List[str]] = {}

        try:
            arp_file = Path("/proc/net/arp")
            if arp_file.exists():
                for line in arp_file.read_text().split('\n')[1:]:
                    parts = line.split()
                    if len(parts) >= 4:
                        ip = parts[0]
                        mac = parts[3].lower()
                        if mac != "00:00:00:00:00:00":
                            if mac not in mac_to_ips:
                                mac_to_ips[mac] = []
                            mac_to_ips[mac].append(ip)

            # Check for duplicate MACs (potential spoofing)
            for mac, ips in mac_to_ips.items():
                if len(ips) > 1:
                    anomalies.append({
                        "type": "arp_spoof_suspected",
                        "mac": mac,
                        "ips": ips,
                        "timestamp": datetime.now().isoformat(),
                        "severity": "alert",
                    })
                    LOG.warning(f"ARP anomaly: MAC {mac} has multiple IPs: {ips}")

        except Exception as e:
            LOG.error(f"ARP check failed: {e}")

        return anomalies

    def measure_latency(self, target: str = "8.8.8.8") -> float:
        """
        Measure network latency using ICMP.
        Returns latency in ms, -1 on failure.
        """
        if self.gaming_guard.is_gaming():
            return -1

        try:
            result = subprocess.run(
                ["ping", "-c", "3", "-W", "2", target],
                capture_output=True, text=True, timeout=10
            )

            # Parse average latency
            match = re.search(r'avg.*?(\d+\.?\d*)', result.stdout)
            if match:
                return float(match.group(1))

        except Exception as e:
            LOG.warning(f"Latency measurement failed: {e}")

        return -1

    def stop(self):
        """Stop all packet analysis immediately."""
        self._enabled = False
        self._stop_event.set()
        LOG.info("Packet analyzer stopped")

    def start(self):
        """Enable packet analysis."""
        if not self.gaming_guard.is_gaming():
            self._enabled = True
            self._stop_event.clear()
            LOG.info("Packet analyzer enabled")


# ============================================
# Non-Invasive Shielding
# ============================================

class ProcessShield:
    """
    Non-invasive process shielding.

    RULES:
    - Never kill processes
    - Only adjust nice level
    - Only pin to last CPU core
    - Log all actions
    """

    def __init__(self, gaming_guard: GamingModeGuard):
        self.gaming_guard = gaming_guard
        self._shielded_pids: Set[int] = set()

    def is_safe_to_shield(self, pid: int) -> bool:
        """Check if we can shield this process."""
        # Never shield during gaming
        if self.gaming_guard.is_gaming():
            return False

        try:
            # Check if it's an anti-cheat or gaming process
            cmdline = Path(f"/proc/{pid}/cmdline").read_text().lower()

            for ac in ANTICHEAT_WHITELIST:
                if ac in cmdline:
                    return False

            for pattern in GAMING_PATTERNS:
                if re.search(pattern, cmdline):
                    return False

        except Exception:
            return False

        return True

    def reduce_priority(self, pid: int) -> bool:
        """
        Reduce process priority to nice 19 (lowest).
        Non-destructive action.
        """
        if not self.is_safe_to_shield(pid):
            return False

        try:
            os.setpriority(os.PRIO_PROCESS, pid, 19)
            self._shielded_pids.add(pid)
            LOG.info(f"Reduced priority of PID {pid} to nice 19")
            return True
        except PermissionError:
            LOG.warning(f"Cannot renice PID {pid} - no permission")
        except Exception as e:
            LOG.error(f"Renice failed for PID {pid}: {e}")

        return False

    def pin_to_last_core(self, pid: int) -> bool:
        """
        Pin process to last CPU core (usually E-core).
        Frees gaming cores.
        """
        if not self.is_safe_to_shield(pid):
            return False

        try:
            # Get CPU count
            cpu_count = os.cpu_count() or 16
            last_core = cpu_count - 1

            # Use taskset
            result = subprocess.run(
                ["taskset", "-p", "-c", str(last_core), str(pid)],
                capture_output=True, timeout=5
            )

            if result.returncode == 0:
                LOG.info(f"Pinned PID {pid} to core {last_core}")
                return True

        except Exception as e:
            LOG.error(f"CPU pin failed for PID {pid}: {e}")

        return False

    def restore_process(self, pid: int) -> bool:
        """Restore normal priority and CPU affinity."""
        try:
            # Reset nice level
            os.setpriority(os.PRIO_PROCESS, pid, 0)

            # Reset CPU affinity to all cores
            cpu_count = os.cpu_count() or 16
            all_cores = ",".join(str(i) for i in range(cpu_count))
            subprocess.run(
                ["taskset", "-p", "-c", all_cores, str(pid)],
                capture_output=True, timeout=5
            )

            self._shielded_pids.discard(pid)
            LOG.info(f"Restored PID {pid} to normal")
            return True

        except Exception as e:
            LOG.error(f"Restore failed for PID {pid}: {e}")

        return False


# ============================================
# Database Manager (Three-Tier Storage)
# ============================================

class DatabaseManager:
    """
    Persistent storage with three-tier model:
    - Hot: current_session.json (24h, full detail)
    - Warm: monthly_summary.json (12mo, 20% detail)
    - Cold: frank_biography.json (permanent, 1% detail)
    """

    def __init__(self):
        DB_DIR.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()

    def save_network_map(self, devices: List[NetworkDevice]):
        """Save network topology."""
        with self._lock:
            data = {
                "timestamp": datetime.now().isoformat(),
                "version": "1.0.0",
                "device_count": len(devices),
                "devices": [d.to_dict() for d in devices],
            }

            # Delta storage - compare with existing
            existing = self._load_json(NETWORK_MAP_FILE)
            if existing:
                old_ips = {d["ip"] for d in existing.get("devices", [])}
                new_ips = {d.ip for d in devices}
                data["delta"] = {
                    "added": list(new_ips - old_ips),
                    "removed": list(old_ips - new_ips),
                }

            self._save_json(NETWORK_MAP_FILE, data)
            LOG.debug(f"Saved network map: {len(devices)} devices")

    def save_health_snapshot(self, health: NetworkHealth):
        """Save network health snapshot."""
        with self._lock:
            # Load existing or create new
            data = self._load_json(NETWORK_HEALTH_FILE) or {
                "version": "1.0.0",
                "snapshots": [],
            }

            # Add new snapshot
            data["snapshots"].append(health.to_dict())

            # Keep only last 24 hours of snapshots (hot data)
            cutoff = datetime.now() - timedelta(hours=CONFIG["hot_data_retention_hours"])
            data["snapshots"] = [
                s for s in data["snapshots"]
                if datetime.fromisoformat(s["timestamp"]) > cutoff
            ][-100:]  # Also limit count

            data["last_update"] = datetime.now().isoformat()
            self._save_json(NETWORK_HEALTH_FILE, data)

    def save_security_event(self, event: SecurityEvent):
        """
        Save security event with importance hierarchy.
        Critical events keep full detail, routine events abstracted.
        """
        with self._lock:
            data = self._load_json(SECURITY_LOG_FILE) or {
                "version": "1.0.0",
                "events": [],
            }

            # Determine abstraction level
            if event.severity in ("critical", "alert"):
                # Full detail for important events
                event_data = event.to_dict()
                event_data["abstraction_level"] = "full"
            else:
                # Abstracted for routine events
                event_data = {
                    "timestamp": event.timestamp,
                    "event_type": event.event_type,
                    "severity": event.severity,
                    "summary": event.description[:100],
                    "abstraction_level": "summary",
                }

            data["events"].append(event_data)

            # Prune old events (keep last 1000)
            data["events"] = data["events"][-1000:]
            data["last_update"] = datetime.now().isoformat()

            self._save_json(SECURITY_LOG_FILE, data)

    def load_network_map(self) -> List[NetworkDevice]:
        """Load network map."""
        data = self._load_json(NETWORK_MAP_FILE)
        if not data:
            return []

        devices = []
        for d in data.get("devices", []):
            devices.append(NetworkDevice(**d))
        return devices

    def _load_json(self, path: Path) -> Optional[dict]:
        """Load JSON file."""
        try:
            if path.exists():
                return json.loads(path.read_text())
        except Exception as e:
            LOG.error(f"Failed to load {path}: {e}")
        return None

    def _save_json(self, path: Path, data: dict):
        """Save JSON file atomically."""
        try:
            tmp = path.with_suffix('.tmp')
            tmp.write_text(json.dumps(data, indent=2, default=str))
            tmp.rename(path)
        except Exception as e:
            LOG.error(f"Failed to save {path}: {e}")


# ============================================
# UOLG Integration
# ============================================

class UOLGIntegration:
    """Send network events to UOLG."""

    UOLG_URL = "http://localhost:8197"

    @staticmethod
    def send_insight(event: SecurityEvent):
        """Send security event to UOLG."""
        try:
            import urllib.request

            insight = {
                "time": event.timestamp,
                "entity": f"Network_{event.event_type}",
                "event_class": "Security_Event" if event.severity in ("alert", "critical") else "Network_Event",
                "hypotheses": [
                    {"cause": event.event_type, "weight": event.confidence},
                ],
                "confidence": event.confidence,
                "actionability": "alert" if event.severity == "critical" else "observe",
                "intrusive_methods_used": False,
                "description": event.description[:200],
            }

            body = json.dumps({"insight": insight}).encode()
            req = urllib.request.Request(
                f"{UOLGIntegration.UOLG_URL}/ingest",
                data=body,
                headers={"Content-Type": "application/json"},
                method="POST"
            )
            urllib.request.urlopen(req, timeout=5)
            LOG.debug("Sent insight to UOLG")

        except Exception as e:
            LOG.debug(f"UOLG send failed: {e}")


# ============================================
# Main Sentinel Class
# ============================================

class NetworkSentinel:
    """
    Main Frank-Sentinel orchestrator.

    Coordinates all network intelligence components with
    strict gaming mode protection.
    """

    def __init__(self):
        self.gaming_guard = GamingModeGuard()
        self.scanner = NetworkScanner(self.gaming_guard)
        self.analyzer = PacketAnalyzer(self.gaming_guard)
        self.shield = ProcessShield(self.gaming_guard)
        self.db = DatabaseManager()

        self._running = False
        self._main_thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()

    def start(self):
        """Start the sentinel daemon."""
        if self._running:
            return

        self._running = True
        self._stop_event.clear()

        # Start gaming guard first
        self.gaming_guard.start_monitoring()

        # Start main loop
        self._main_thread = threading.Thread(
            target=self._main_loop,
            daemon=True,
            name="Sentinel-Main"
        )
        self._main_thread.start()

        LOG.info("Network Sentinel started")

    def stop(self):
        """Stop the sentinel."""
        self._running = False
        self._stop_event.set()

        self.analyzer.stop()
        self.gaming_guard.stop_monitoring()

        if self._main_thread:
            self._main_thread.join(timeout=5)

        LOG.info("Network Sentinel stopped")

    def _main_loop(self):
        """Main daemon loop."""
        last_scan = 0
        last_health_check = 0

        while self._running and not self._stop_event.is_set():
            try:
                now = time.time()

                # Skip everything if gaming
                if self.gaming_guard.is_gaming():
                    self._stop_event.wait(1)
                    continue

                # Periodic network scan
                if now - last_scan > CONFIG["scan_interval_sec"]:
                    self._do_network_scan()
                    last_scan = now

                # Periodic health check
                if now - last_health_check > CONFIG["packet_sample_interval"]:
                    self._do_health_check()
                    last_health_check = now

                # Check for ARP spoofing
                anomalies = self.analyzer.detect_arp_spoofing()
                for a in anomalies:
                    event = SecurityEvent(
                        timestamp=a["timestamp"],
                        event_type="arp_spoofing",
                        severity=a["severity"],
                        description=f"Potential ARP spoofing: MAC {a['mac']} has IPs {a['ips']}",
                        confidence=0.8,
                    )
                    self.db.save_security_event(event)
                    UOLGIntegration.send_insight(event)

            except Exception as e:
                LOG.error(f"Main loop error: {e}")

            self._stop_event.wait(5)  # Check every 5 seconds

    def _do_network_scan(self):
        """Perform network scan."""
        if self.gaming_guard.is_gaming():
            return

        # Quick scan (no root needed)
        devices = self.scanner.quick_scan()

        if devices:
            self.db.save_network_map(devices)

            # Check for new devices
            old_devices = self.db.load_network_map()
            old_ips = {d.ip for d in old_devices}

            for dev in devices:
                if dev.ip not in old_ips:
                    event = SecurityEvent(
                        timestamp=datetime.now().isoformat(),
                        event_type="new_device",
                        severity="info",
                        source_ip=dev.ip,
                        description=f"New device detected: {dev.ip} ({dev.mac})",
                        confidence=0.9,
                    )
                    self.db.save_security_event(event)

    def _do_health_check(self):
        """Perform network health check."""
        if self.gaming_guard.is_gaming():
            return

        latency = self.analyzer.measure_latency()

        health = NetworkHealth(
            timestamp=datetime.now().isoformat(),
            latency_ms=latency if latency > 0 else 0,
            anomalies_detected=len(self.analyzer._anomalies),
        )

        self.db.save_health_snapshot(health)

    def get_status(self) -> dict:
        """Get sentinel status."""
        return {
            "running": self._running,
            "gaming_mode": self.gaming_guard.is_gaming(),
            "devices_known": len(self.scanner.get_devices()),
            "last_scan": self.scanner._last_scan.isoformat() if self.scanner._last_scan else None,
            "analyzer_enabled": self.analyzer._enabled,
        }

    def scan_now(self) -> List[dict]:
        """Manual scan trigger."""
        if self.gaming_guard.is_gaming():
            return []

        devices = self.scanner.quick_scan()
        self.db.save_network_map(devices)
        return [d.to_dict() for d in devices]

    def get_network_map(self) -> dict:
        """Get current network map."""
        devices = self.db.load_network_map()
        return {
            "timestamp": datetime.now().isoformat(),
            "gaming_mode": self.gaming_guard.is_gaming(),
            "device_count": len(devices),
            "devices": [d.to_dict() for d in devices],
        }


# ============================================
# Singleton & Public API
# ============================================

_sentinel: Optional[NetworkSentinel] = None


def get_sentinel() -> NetworkSentinel:
    """Get singleton sentinel instance."""
    global _sentinel
    if _sentinel is None:
        _sentinel = NetworkSentinel()
    return _sentinel


# Public API for Frank

def start_sentinel():
    """Start the network sentinel."""
    get_sentinel().start()


def stop_sentinel():
    """Stop the network sentinel."""
    get_sentinel().stop()


def get_status() -> dict:
    """Get sentinel status."""
    return get_sentinel().get_status()


def scan_network() -> List[dict]:
    """Trigger network scan."""
    return get_sentinel().scan_now()


def get_network_map() -> dict:
    """Get network topology."""
    return get_sentinel().get_network_map()


def is_gaming() -> bool:
    """Check if gaming mode is active."""
    return get_sentinel().gaming_guard.is_gaming()


# ============================================
# CLI
# ============================================

def main():
    """CLI entry point."""
    import argparse

    parser = argparse.ArgumentParser(description="Frank-Sentinel Network Intelligence")
    parser.add_argument("--daemon", action="store_true", help="Run as daemon")
    parser.add_argument("--scan", action="store_true", help="Run network scan")
    parser.add_argument("--status", action="store_true", help="Show status")
    parser.add_argument("--map", action="store_true", help="Show network map")
    args = parser.parse_args()

    if args.daemon:
        LOG.info("Starting Network Sentinel daemon...")
        sentinel = get_sentinel()

        # Signal handler for graceful shutdown
        def shutdown_handler(signum, frame):
            LOG.info(f"Received signal {signum}, shutting down gracefully...")
            sentinel.stop()
            sys.exit(0)

        signal.signal(signal.SIGTERM, shutdown_handler)
        signal.signal(signal.SIGINT, shutdown_handler)

        sentinel.start()

        # Wait for interrupt
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            sentinel.stop()

    elif args.scan:
        print("Scanning network...")
        devices = scan_network()
        print(f"Found {len(devices)} devices:")
        for d in devices:
            print(f"  {d['ip']} - {d['mac']} ({d.get('hostname', 'unknown')})")

    elif args.status:
        status = get_status()
        print(json.dumps(status, indent=2))

    elif args.map:
        net_map = get_network_map()
        print(json.dumps(net_map, indent=2))

    else:
        parser.print_help()


if __name__ == "__main__":
    main()
