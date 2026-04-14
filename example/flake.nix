{
  description = "My awesome application";

  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";
    
    sops-kdf.url = "github:sapp00/nix-sops-kdf"; 
  };

  outputs = { self, nixpkgs, sops-kdf }:
  let
    system = "x86_64-linux";
    pkgs = nixpkgs.legacyPackages.${system};
    
    kdfTool = sops-kdf.packages.${system}.default;
  in {
    devShells.${system}.default = pkgs.mkShell {
      buildInputs = [
        pkgs.sops
        pkgs.age
      ];

      shellHook = ''
        export EDITOR=vim
        # Dynamically derive and export the SOPS key for this shell
        eval "$(${kdfTool}/bin/sops-kdf-hook)"
      '';
    };
  };
}
