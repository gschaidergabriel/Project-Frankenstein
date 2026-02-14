#!/bin/bash
# F.A.S. Popup Hotkey Trigger
# Sends toggle command to the popup daemon

python3 -c "
import socket
import os
sock = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
try:
    sock.sendto(b'toggle', f'/run/user/{os.getuid()}/frank/fas_hotkey.sock')
except Exception as e:
    # Daemon not running, start popup directly
    import subprocess
    subprocess.Popen([
        'python3',
        '/home/ai-core-node/aicore/opt/aicore/ui/fas_popup/main_window.py',
        '--manual'
    ])
sock.close()
" 2>/dev/null
