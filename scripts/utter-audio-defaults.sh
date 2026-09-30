#!/bin/bash
# Keep the LG TV as default output and the RNNoise source as default input,
# restoring them after any PipeWire restart. Idempotent; loops forever.
# Volume is intentionally NOT forced (only unmute when we (re)set the default).
SINK="alsa_output.pci-0000_01_00.1.hdmi-stereo"
SRC="DualSense_Denoised"
CODECS="pcm;ac3-iec61937;eac3-iec61937;truehd-iec61937"

while true; do
    if pactl list short sinks 2>/dev/null | grep -q "$SINK"; then
        if [ "$(pactl get-default-sink 2>/dev/null)" != "$SINK" ]; then
            pactl set-default-sink "$SINK" >/dev/null 2>&1
            pactl set-sink-mute "$SINK" 0 >/dev/null 2>&1
        fi
        pactl set-sink-formats "$SINK" "$CODECS" >/dev/null 2>&1
    fi
    if pactl list short sources 2>/dev/null | grep -q "$SRC"; then
        if [ "$(pactl get-default-source 2>/dev/null)" != "$SRC" ]; then
            pactl set-default-source "$SRC" >/dev/null 2>&1
        fi
    fi
    sleep 10
done
