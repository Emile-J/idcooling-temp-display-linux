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

## Installation

First confirm you actually have this device:

```bash
lsusb | grep -i 1a86:e317        # ...QinHeng Electronics IDCOOL-C
```

Requirements: Python 3 (standard library only) and a Linux `hidraw` device.
CPU temperature is read from `/sys/class/hwmon` (AMD `k10temp` / Intel
`coretemp` auto-detected; override with `--temp-path`).

### Try it first (no install)

```bash
sudo ./idcool_display.py --once            # one update, then exit
sudo ./idcool_display.py                   # run continuously (temp, every 1s)
sudo ./idcool_display.py --metric usage    # or: usage / freq
```

`sudo` is only needed because `/dev/hidraw*` is root-only until the udev rule
(below) is installed.

### NixOS (flakes)

Add the repo as an input — no files to copy, the flake carries both the module
and the driver:

```nix
# flake.nix
{
  inputs.idcool-display.url = "github:<you>/idcooling-temp-display-linux";
  # pass inputs through to your nixosSystem (specialArgs / module args), then
  # in a module:  imports = [ inputs.idcool-display.nixosModules.default ];
}
```

```nix
# configuration.nix (or any imported module)
services.idcool-display.enable = true;
services.idcool-display.metric = "temp";   # or "usage" / "freq"
```

`nixos-rebuild switch` and it runs at boot.

### NixOS (without flakes)

```nix
{ ... }:
let
  idcool = builtins.fetchTarball
    "https://github.com/<you>/idcooling-temp-display-linux/archive/main.tar.gz";
in
{
  imports = [ "${idcool}/nix/idcool-display.nix" ];
  services.idcool-display.enable = true;
}
```

### Other distros (systemd)

```bash
sudo install -m0755 idcool_display.py /usr/local/bin/idcool-display
sudo install -m0644 udev/99-idcooling-temp-display.rules /etc/udev/rules.d/
sudo install -m0644 systemd/idcool-display.service /etc/systemd/system/
sudo udevadm control --reload-rules && sudo udevadm trigger --subsystem-match=hidraw
sudo systemctl enable --now idcool-display.service
```

To show a different metric, change `--metric` in the service file, then
`sudo systemctl daemon-reload && sudo systemctl restart idcool-display`.

The udev rule gives the device a stable `/dev/idcool` symlink and group access
for manual testing; the daemon itself resolves the device by USB VID:PID, so it
doesn't depend on the symlink or on start order.

## Troubleshooting

- **`... display (1A86:E317) not found`** — the cooler isn't plugged in, or you
  lack permission for `/dev/hidraw*`. Run as root, or install the udev rule (and
  for manual non-root runs, make sure your user is in its group).
- **Permission denied on `/dev/hidraw*`** — the udev rule ships `GROUP="plugdev"`;
  change it to a group you're in, or just run the service (it runs as root).
- **Wrong temperature** (a GPU/chipset sensor instead of the CPU) —
  auto-detection picked the wrong hwmon. Pass
  `--temp-path /sys/class/hwmon/hwmonN/tempM_input` (find it with `sensors` or
  by reading the `*/name` files under `/sys/class/hwmon`).
- **Screen goes blank after suspend** — `systemctl restart idcool-display`
  (the service also auto-restarts on failure).

## Files

| Path | What |
|------|------|
| `idcool_display.py` | the driver (stdlib only, CLI) |
| `flake.nix` | flake exposing the NixOS module + a `nix run` package |
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
