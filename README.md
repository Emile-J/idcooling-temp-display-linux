# idcooling-temp-display-linux

Linux driver for **ID-COOLING "Temp Display"** coolers — the little fan/cooler
screens that show your CPU temperature. There's no official Linux software, so
this is a tiny, dependency-free daemon that speaks the vendor's USB-HID
protocol (reverse-engineered and verified on real hardware).

If your cooler's display enumerates as **USB `1a86:e317`** (product string
`IDCOOL-C`), this is for you. Known to cover the ID-COOLING **FX TD** /
**FROZN TD** "Temp Display" series, and rebrands such as the cooler shipped in
some **Aftershock** PCs.

> **Scope / limitation:** this screen is a *fixed-function* display. The
> firmware renders the numbers; the host can only send **CPU temperature,
> frequency, usage, and screen on/off**. It is **not** a framebuffer — you
> cannot draw arbitrary images on it. (Verified: the vendor app has no
> image/upload command.) See [`PROTOCOL.md`](PROTOCOL.md).

## Quick start

```bash
# run it (needs access to /dev/hidraw* -> root, or install the udev rule below)
sudo ./idcool_display.py                  # show CPU temperature, update every 1s
sudo ./idcool_display.py --metric usage   # show CPU usage % instead
sudo ./idcool_display.py --metric freq    # show CPU frequency
./idcool_display.py --once                # one update then exit (handy for testing)
```

Requirements: Python 3 (standard library only) and a Linux `hidraw` device.
CPU temperature is read from `/sys/class/hwmon` (AMD `k10temp` / Intel
`coretemp` auto-detected; override with `--temp-path`).

## Install as a service (any systemd distro)

```bash
sudo install -m0755 idcool_display.py /usr/local/bin/idcool-display
sudo install -m0644 udev/99-idcooling-temp-display.rules /etc/udev/rules.d/
sudo install -m0644 systemd/idcool-display.service /etc/systemd/system/
sudo udevadm control --reload-rules && sudo udevadm trigger --subsystem-match=hidraw
sudo systemctl enable --now idcool-display.service
```

The udev rule gives the device a stable `/dev/idcool` symlink and group access
so you don't need root for manual testing. The daemon itself resolves the
device by USB VID:PID, so it does not depend on the symlink or on start order.

## NixOS

A ready-made module is in [`nix/idcool-display.nix`](nix/idcool-display.nix)
(self-contained: udev rule + systemd service + the daemon inline). Import it
and you're done; it runs as root and feeds `k10temp` Tctl every second.

## Files

| Path | What |
|------|------|
| `idcool_display.py` | the driver (stdlib only, CLI) |
| `PROTOCOL.md` | full HID protocol spec + how it was decoded |
| `udev/99-idcooling-temp-display.rules` | `/dev/idcool` symlink + group access |
| `systemd/idcool-display.service` | systemd unit |
| `nix/idcool-display.nix` | NixOS module |

## Credits

Protocol reverse-engineered from the official ID-COOLING Temp Display app by
reading its (Electron/JavaScript) source — no Windows or Wine required; see
[`PROTOCOL.md`](PROTOCOL.md) for the exact steps so you can verify it yourself.

Not affiliated with or endorsed by ID-COOLING. Trademarks belong to their
owners. Use at your own risk.

## License

MIT — see [`LICENSE`](LICENSE).
