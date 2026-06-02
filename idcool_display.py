#!/usr/bin/env python3
"""idcool-display - drive an ID-COOLING "Temp Display" cooler on Linux.

Shows the CPU temperature on ID-COOLING coolers whose little screen enumerates
as USB HID 1a86:e317 - e.g. the FX TD / FROZN TD "Temp Display" series, also
sold rebranded (the USB product string reads "IDCOOL-C", as shipped in some
Aftershock PCs).

The screen is a write-only USB-HID device: the host pushes a value and the
device firmware renders the number. There is no official Linux software, so
this daemon replicates the vendor protocol (decoded from the vendor Electron
app and verified on real hardware). Pure Python standard library - no deps.

Protocol - every command is a 64-byte HID output report:

    byte 0   : 0x55             header
    byte 1   : 0xBB             header
    byte 2   : 0x02             payload length
    byte 3   : command          1=CPU_TEMP, 2=CPU_FREQ, 3=CPU_USAGE, 4=SHOW
    byte 4   : value >> 8        16-bit big-endian
    byte 5   : value & 0xFF
    byte 6   : checksum = (0x55 + 0xBB + 0x02 + cmd + hi + lo) & 0xFF
    byte 7-63: 0x00 padding

The report is written to /dev/hidrawN prefixed with a 0x00 report-id byte
(the device uses unnumbered reports; the kernel strips the leading byte).

NOTE: this hardware can ONLY display the numbers its firmware knows how to
draw (temp / frequency / usage). It is not a framebuffer - arbitrary images
are not possible.

Usage:
    sudo ./idcool_display.py                 # show CPU temp, updated every 1s
    sudo ./idcool_display.py --metric usage  # show CPU usage % instead
    ./idcool_display.py --once --metric temp # one update and exit (for testing)

License: MIT.
"""
import argparse
import glob
import os
import time

USB_VENDOR = "1A86"   # QinHeng/WCH, as it appears in HID_ID (hex)
USB_PRODUCT = "E317"  # IDCOOL-C / ID-COOLING Temp Display
REPORT_LEN = 64

CMD_CPU_TEMPERATURE = 1
CMD_CPU_FREQUENCY = 2
CMD_CPU_USAGE = 3
CMD_SHOW = 4


# --------------------------------------------------------------------------- #
# Device
# --------------------------------------------------------------------------- #
def find_device():
    """Resolve the hidraw node by USB VID:PID from sysfs.

    Independent of any /dev symlink or udev/service ordering: the hidraw node
    exists as soon as the kernel enumerates the device. HID_ID looks like
    "0003:00001A86:0000E317".
    """
    for hd in glob.glob("/sys/class/hidraw/hidraw*"):
        try:
            with open(os.path.join(hd, "device/uevent")) as fh:
                uevent = fh.read()
        except OSError:
            continue
        for line in uevent.splitlines():
            if not line.startswith("HID_ID="):
                continue
            parts = line.strip().split(":")
            if (
                len(parts) == 3
                and parts[1][-4:].upper() == USB_VENDOR
                and parts[2][-4:].upper() == USB_PRODUCT
            ):
                return "/dev/" + os.path.basename(hd)
    return None


def wait_for_device(timeout):
    """Wait up to `timeout` seconds for the device to appear; return its path."""
    while timeout > 0:
        dev = find_device()
        if dev:
            return dev
        time.sleep(1.0)
        timeout -= 1
    raise SystemExit(
        f"ID-COOLING display ({USB_VENDOR}:{USB_PRODUCT}) not found. "
        "Is it plugged in, and do you have permission for /dev/hidraw*? "
        "(run as root or install the udev rule)"
    )


# --------------------------------------------------------------------------- #
# Protocol
# --------------------------------------------------------------------------- #
def frame(cmd, value):
    """Encode one 64-byte command report."""
    value = max(0, min(0xFFFF, int(value)))
    hi, lo = (value >> 8) & 0xFF, value & 0xFF
    cks = (0x55 + 0xBB + 0x02 + cmd + hi + lo) & 0xFF
    buf = bytearray(REPORT_LEN)
    buf[0:7] = bytes([0x55, 0xBB, 0x02, cmd, hi, lo, cks])
    return bytes(buf)


def write_report(fd, report):
    # hidraw expects the report number as the first byte; this device uses
    # unnumbered reports, so prefix 0x00 (the kernel strips it).
    os.write(fd, b"\x00" + report)


# --------------------------------------------------------------------------- #
# Sensors (stdlib only, via /sys/class/hwmon)
# --------------------------------------------------------------------------- #
def find_temp_path():
    """Best-effort CPU temperature source in /sys/class/hwmon.

    Prefers AMD k10temp (Tctl) then Intel coretemp (Package), else any temp
    input. Override with --temp-path if auto-detection picks the wrong one.
    """
    hwmons = {}
    for hw in glob.glob("/sys/class/hwmon/hwmon*"):
        try:
            hwmons[hw] = open(os.path.join(hw, "name")).read().strip()
        except OSError:
            continue

    def labelled(hw, want):
        for label in glob.glob(os.path.join(hw, "temp*_label")):
            try:
                if open(label).read().strip() == want:
                    return label.replace("_label", "_input")
            except OSError:
                pass
        return None

    for hw, name in hwmons.items():
        if name == "k10temp":  # AMD
            return labelled(hw, "Tctl") or os.path.join(hw, "temp1_input")
    for hw, name in hwmons.items():
        if name == "coretemp":  # Intel
            return labelled(hw, "Package id 0") or os.path.join(hw, "temp1_input")
    for hw in hwmons:  # anything with a temperature
        inputs = sorted(glob.glob(os.path.join(hw, "temp*_input")))
        if inputs:
            return inputs[0]
    raise SystemExit("no CPU temperature sensor found in /sys/class/hwmon")


def read_temp_c(path):
    with open(path) as fh:
        return int(fh.read().strip()) / 1000.0


def read_cpu_usage():
    """Whole-system CPU usage % over a short sample, from /proc/stat."""
    def snap():
        with open("/proc/stat") as fh:
            f = [float(x) for x in fh.readline().split()[1:]]
        idle = f[3] + (f[4] if len(f) > 4 else 0)
        return sum(f), idle

    t0, i0 = snap()
    time.sleep(0.2)
    t1, i1 = snap()
    dt = t1 - t0
    return 0.0 if dt <= 0 else max(0.0, min(100.0, 100.0 * (1 - (i1 - i0) / dt)))


def read_cpu_freq_mhz():
    """Average current CPU frequency in MHz from cpufreq, if available."""
    freqs = []
    for f in glob.glob("/sys/devices/system/cpu/cpu*/cpufreq/scaling_cur_freq"):
        try:
            freqs.append(int(open(f).read().strip()) / 1000.0)  # kHz -> MHz
        except OSError:
            pass
    return sum(freqs) / len(freqs) if freqs else 0.0


# --------------------------------------------------------------------------- #
# Main
# --------------------------------------------------------------------------- #
def make_sample(metric, temp_path):
    """Return (command, value) for the chosen metric."""
    if metric == "temp":
        return CMD_CPU_TEMPERATURE, round(read_temp_c(temp_path))
    if metric == "usage":
        return CMD_CPU_USAGE, round(read_cpu_usage())
    if metric == "freq":
        return CMD_CPU_FREQUENCY, round(read_cpu_freq_mhz())
    raise ValueError(metric)


def main():
    ap = argparse.ArgumentParser(description="ID-COOLING Temp Display driver")
    ap.add_argument("--metric", choices=["temp", "usage", "freq"], default="temp")
    ap.add_argument("--interval", type=float, default=1.0, help="seconds between updates")
    ap.add_argument("--temp-path", help="override hwmon temperature input path")
    ap.add_argument("--device", help="override hidraw path (else auto by VID:PID)")
    ap.add_argument("--wait", type=int, default=60, help="seconds to wait for the device")
    ap.add_argument("--once", action="store_true", help="send one update and exit")
    args = ap.parse_args()

    temp_path = args.temp_path or (find_temp_path() if args.metric == "temp" else None)
    dev = args.device or wait_for_device(args.wait)
    fd = os.open(dev, os.O_WRONLY)
    try:
        write_report(fd, frame(CMD_SHOW, 1))  # turn the screen on
        while True:
            cmd, value = make_sample(args.metric, temp_path)
            write_report(fd, frame(cmd, value))
            if args.once:
                break
            time.sleep(args.interval)
    finally:
        os.close(fd)


if __name__ == "__main__":
    main()
