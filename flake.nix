{
  description = "Agentic Delivery Template development environment";

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
          name = "agentic-template";

          packages = with nixpkgs.legacyPackages.${system}; [
            actionlint
            bash
            cachix
            deadnix
            git
            nixfmt
            shellcheck
            statix
            uv
          ];

          shellHook = ''
            echo "agentic-template dev shell"
            echo "  nix flake check     run Nix and repository checks"
            echo "  nix fmt             format Nix files"
            echo "  cachix push ...     publish a built closure (CACHIX_AUTH_TOKEN required)"
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
            pkgs.runCommand "agentic-template-formatting"
              {
                nativeBuildInputs = [ pkgs.nixfmt ];
              }
              ''
                nixfmt --check ${source}/flake.nix
                touch $out
              '';

          shell-lint =
            pkgs.runCommand "agentic-template-shell-lint"
              {
                nativeBuildInputs = [ pkgs.shellcheck ];
              }
              ''
                shellcheck "${source}/scripts/"*.sh
                touch $out
              '';

          workflow-lint =
            pkgs.runCommand "agentic-template-workflow-lint"
              {
                nativeBuildInputs = [ pkgs.actionlint ];
              }
              ''
                actionlint "${source}/.github/workflows/"*.yml
                touch $out
              '';

          nix-lint =
            pkgs.runCommand "agentic-template-nix-lint"
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
            pkgs.runCommand "agentic-template-repository-validation"
              {
                nativeBuildInputs = [ pkgs.bash ];
              }
              ''
                cd ${source}
                bash scripts/test-portable-validation.sh
                bash scripts/test-delivery-contract.sh
                touch $out
              '';
        }
      );
    };
}
