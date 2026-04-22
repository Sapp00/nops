{
  description = "My awesome application";

  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";

    #nops.url = "path:..";
    nops.url = "github:sapp00/nops";
  };

  outputs = { self, nixpkgs, nops }:
  let
    system = "x86_64-linux";
    pkgs = nixpkgs.legacyPackages.${system};
  in {
    devShells.${system}.default = pkgs.mkShell {
      buildInputs = [
        nops.packages.${system}.default
        pkgs.sops
        pkgs.age
      ];

      shellHook = ''
        export EDITOR=vim

        # nops is now available as a CLI tool:
        # nops init                    - Initialize project
        # nops create <name>           - Create new key
        # nops <file>                  - Edit encrypted file
        # nops encrypt <file>          - Encrypt file
        # nops export <name>           - Export key
      '';
    };
  };
}
