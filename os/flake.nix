{
  description = "Lunar OS - see what's on the other side of the moon";

  inputs.nixpkgs.url = "git+https://github.com/NixOS/nixpkgs?ref=nixos-26.05&shallow=1";

  outputs = { self, nixpkgs }:
    let
      system = "x86_64-linux";
      overlay = import ./pkgs;
      lunarSystem = extra: nixpkgs.lib.nixosSystem {
        inherit system;
        specialArgs = { inherit self nixpkgs; };
        modules = [
          { nixpkgs.overlays = [ overlay ]; }
          ./modules
        ] ++ extra;
      };
      pkgs = import nixpkgs { inherit system; overlays = [ overlay ]; };
    in
    {
      overlays.default = overlay;

      # Installed on a disk (lunar-install, then ltxs, use this one).
      nixosConfigurations.lunar = lunarSystem [ ./hosts/installed.nix ];
      # The USB stick.
      nixosConfigurations.live = lunarSystem [ ./hosts/live.nix ];

      packages.${system} = pkgs.lunar // {
        iso = self.nixosConfigurations.live.config.system.build.isoImage;
        default = self.packages.${system}.iso;
      };
    };
}
