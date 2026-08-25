{
  description = "Rygor development environment";

  inputs.nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";

  outputs =
    { self, nixpkgs }:
    let
      systems = [
        "x86_64-linux"
        "aarch64-linux"
        "x86_64-darwin"
        "aarch64-darwin"
      ];
      forAllSystems = nixpkgs.lib.genAttrs systems;
    in
    {
      devShells = forAllSystems (system: {
        default = nixpkgs.legacyPackages.${system}.mkShell {
          name = "rygor";

          packages = with nixpkgs.legacyPackages.${system}; [
            actionlint
            cachix
            deadnix
            git
            nixfmt
            statix
            python314
            uv
          ];

          shellHook = ''
            echo "rygor dev shell"
            echo "  nix flake check     run Nix and repository checks"
            echo "  nix fmt             format Nix files"
            echo "  cachix push ...     publish a built closure (CACHIX_AUTH_TOKEN required)"
            echo "  uv sync --all-groups --locked     install locked source dependencies"
            echo "  uv tool install copier   install the template updater"
          '';
        };
      });

      formatter = forAllSystems (
        system:
        let
          pkgs = nixpkgs.legacyPackages.${system};
        in
        pkgs.writeShellScriptBin "nixfmt" ''
          if [ "$#" -gt 0 ]; then
            exec ${pkgs.nixfmt}/bin/nixfmt "$@"
          fi
          exec ${pkgs.nixfmt}/bin/nixfmt flake.nix
        ''
      );

      checks = forAllSystems (
        system:
        let
          pkgs = nixpkgs.legacyPackages.${system};
          source = self;
        in
        {
          formatting =
            pkgs.runCommand "rygor-formatting"
              {
                nativeBuildInputs = [ pkgs.nixfmt ];
              }
              ''
                nixfmt --check ${source}/flake.nix
                touch $out
              '';

          workflow-lint =
            pkgs.runCommand "rygor-workflow-lint"
              {
                nativeBuildInputs = [ pkgs.actionlint ];
              }
              ''
                actionlint "${source}/.github/workflows/"*.yml
                touch $out
              '';

          nix-lint =
            pkgs.runCommand "rygor-nix-lint"
              {
                nativeBuildInputs = [
                  pkgs.deadnix
                  pkgs.statix
                ];
              }
              ''
                deadnix --fail ${source}/flake.nix
                statix check ${source}/flake.nix
                touch $out
              '';

          repository-validation =
            pkgs.runCommand "rygor-repository-validation" { nativeBuildInputs = [ pkgs.python314 ]; }
              ''
                cd ${source}
                # The portable bare-python lane: template-contract tests need
                # the declared runtime dependencies (pydantic) and run under
                # the uv pytest suite instead (template-ci python-source job).
                if [ -f tests/test_project_readiness.py ]; then python3.14 tests/test_project_readiness.py; fi
                if [ -f tests/test_repository_validation.py ]; then python3.14 tests/test_repository_validation.py; fi
                if [ -f tests/test_delivery_contract.py ]; then python3.14 tests/test_delivery_contract.py; fi
                touch $out
              '';
        }
      );
    };
}
