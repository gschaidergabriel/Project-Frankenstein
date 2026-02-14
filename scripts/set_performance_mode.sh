#!/bin/bash
# Set CPU to performance mode for maximum LLM inference speed
# Run with: sudo bash set_performance_mode.sh

echo "Setting CPU governor to performance mode..."

for cpu in /sys/devices/system/cpu/cpu*/cpufreq/scaling_governor; do
    echo "performance" > "$cpu" 2>/dev/null
done

echo "Current governors:"
cat /sys/devices/system/cpu/cpu*/cpufreq/scaling_governor | sort | uniq -c

echo ""
echo "Current frequencies:"
cat /sys/devices/system/cpu/cpu*/cpufreq/scaling_cur_freq | sort -n | tail -4 | while read f; do
    echo "  $(( f / 1000 )) MHz"
done

echo ""
echo "Done! CPU should now run at maximum frequency."
