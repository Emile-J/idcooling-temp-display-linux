{
  description = "Linux driver for ID-COOLING 'Temp Display' coolers (USB 1a86:e317)";

  inputs.nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";

  outputs =
    { self, nixpkgs }:
    let
      systems = [
        "x86_64-linux"
        "aarch64-linux"
      ];
      forAllSystems = f: nixpkgs.lib.genAttrs systems (system: f nixpkgs.legacyPackages.${system});
    in
    {
      # NixOS module: services.idcool-display.enable = true;
      nixosModules.default = ./nix/idcool-display.nix;
      nixosModules.idcool-display = ./nix/idcool-display.nix;

      # `nix run github:relf108/idcooling-temp-display-linux -- --once`
      packages = forAllSystems (pkgs: {
        default = pkgs.writeShellScriptBin "idcool-display" ''
          exec ${pkgs.python3}/bin/python3 ${./idcool_display.py} "$@"
        '';
      });
    };
}
