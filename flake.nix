{
  description = "SOPS KDF Flake";

  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-25.11";
    flake-utils.url = "github:numtide/flake-utils";
    poetry2nix = {
      url = "github:nix-community/poetry2nix";
      inputs.nixpkgs.follows = "nixpkgs";
    };
  };

  outputs = { self, nixpkgs, flake-utils, poetry2nix }:
    flake-utils.lib.eachDefaultSystem (system:
      let
        pkgs = nixpkgs.legacyPackages.${system};
        inherit (poetry2nix.lib.mkPoetry2Nix { inherit pkgs; }) mkPoetryApplication;
        
        sops-kdf-app = mkPoetryApplication {
          projectDir = ./.;
          python = pkgs.python311;
          propagatedBuildInputs = [ pkgs.git pkgs.age ];
        };
      in {
        packages.default = sops-kdf-app;

        devShells.default = pkgs.mkShell {
          packages = [ pkgs.poetry ];
          inputsFrom = [ sops-kdf-app ];

          shellHook = ''
            # Tell SOPS to use vim
            export EDITOR="vim"
          '';
        };
      }
    );
}
