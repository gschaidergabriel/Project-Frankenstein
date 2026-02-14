#!/bin/bash
# Frank AI - UI Test Starter
cd "$(dirname "$0")"
export DISPLAY="${DISPLAY:-:0}"
python3 simple_launcher.py
