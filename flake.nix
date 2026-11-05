{
  description = "MCP server for Seerr, the request front-end for Jellyfin and the *arrs";

  inputs.nixpkgs.url = "github:NixOS/nixpkgs/nixos-26.05";

  outputs =
    { self, nixpkgs }:
    let
      system = "x86_64-linux";
      pkgs = nixpkgs.legacyPackages.${system};
      server = pkgs.callPackage ./package.nix { };
    in
    {
      packages.${system} = {
        default = server;
        seerr-mcp = server;
      };

      checks.${system} = {
        # Building the package runs the whole test suite.
        default = server;
        lint =
          pkgs.runCommand "seerr-mcp-lint"
            {
              nativeBuildInputs = [
                pkgs.ruff
                pkgs.nixfmt
              ];
            }
            ''
              cd ${self}
              ruff check --no-cache src tests
              ruff format --no-cache --check src tests
              nixfmt --check flake.nix package.nix
              touch $out
            '';
      };

      formatter.${system} = pkgs.nixfmt;
    };
}
