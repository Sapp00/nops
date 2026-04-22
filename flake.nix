{
  description = "nops - Simple SOPS key management";

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

        nops-app = mkPoetryApplication {
          projectDir = ./.;
          python = pkgs.python311;
          propagatedBuildInputs = [ pkgs.age pkgs.sops ];
        };
      in {
        packages.default = nops-app;

        devShells.default = pkgs.mkShell {
          packages = [ pkgs.poetry pkgs.age pkgs.sops ];
          inputsFrom = [ nops-app ];

          shellHook = ''
            export EDITOR="vim"
          '';
        };
      }
    );
}
