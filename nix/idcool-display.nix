# NixOS module for the ID-COOLING Temp Display (USB 1a86:e317).
#
# Usage: import this file and set
#   services.idcool-display.enable = true;
#
# It runs idcool_display.py (the canonical driver in this repo) as a systemd
# service. Runs as root to open the hidraw node directly; the udev rule adds a
# stable /dev/idcool symlink + uaccess for manual use.
{
  config,
  lib,
  pkgs,
  ...
}:
let
  cfg = config.services.idcool-display;
  daemon = pkgs.writeShellScriptBin "idcool-display" ''
    exec ${pkgs.python3}/bin/python3 ${../idcool_display.py} \
      --metric ${cfg.metric} --interval ${toString cfg.interval} "$@"
  '';
in
{
  options.services.idcool-display = {
    enable = lib.mkEnableOption "ID-COOLING Temp Display CPU feed";
    metric = lib.mkOption {
      type = lib.types.enum [
        "temp"
        "usage"
        "freq"
      ];
      default = "temp";
      description = "Which CPU metric to show on the display.";
    };
    interval = lib.mkOption {
      type = lib.types.number;
      default = 1;
      description = "Seconds between display updates.";
    };
  };

  config = lib.mkIf cfg.enable {
    # Stable name + access for manual poking; the daemon resolves the device by
    # VID:PID itself, so it does not depend on this.
    services.udev.extraRules = ''
      SUBSYSTEM=="hidraw", ATTRS{idVendor}=="1a86", ATTRS{idProduct}=="e317", MODE="0660", TAG+="uaccess", SYMLINK+="idcool"
    '';

    systemd.services.idcool-display = {
      description = "ID-COOLING Temp Display temperature feed";
      wantedBy = [ "multi-user.target" ];
      serviceConfig = {
        ExecStart = "${daemon}/bin/idcool-display";
        Restart = "on-failure";
        RestartSec = 5;
        User = "root";
        NoNewPrivileges = true;
        ProtectHome = true;
        ProtectKernelTunables = true;
        RestrictAddressFamilies = [ "AF_UNIX" ];
      };
    };
  };
}
