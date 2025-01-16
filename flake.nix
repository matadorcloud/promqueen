{
  description = "A simple Prometheus query visualizer";

  inputs = {
    nixpkgs.url = "github:nixos/nixpkgs/release-24.11";
    flake-utils.url = "github:numtide/flake-utils";
  };

  outputs = { self, nixpkgs, flake-utils }:
    flake-utils.lib.eachDefaultSystem (system:
    let
      pkgs = import nixpkgs { inherit system; };
      py = pkgs.python3.withPackages (ps: with ps; [ urwid twisted treq ]);
      promqueen = pkgs.stdenv.mkDerivation {
        name = "promqueen";
        version = "1.0.1";

        src = ./.;

        buildInputs = [ py ];

        installPhase = ''
          mkdir -p $out/bin/
          cp promq.py $out/bin/promq
          chmod +x $out/bin/promq
          patchShebangs $out/bin/promq
        '';
      };
    in {
      packages = {
        inherit promqueen;
        default = promqueen;
      };
      devShells.default = pkgs.mkShell { packages = [ py ]; };
    });
}
