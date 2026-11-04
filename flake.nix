{
  description = "Every Microsoft Agent character on tmafe.com, as a Nix flake";

  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixpkgs-unstable";
    systems.url = "github:nix-systems/default";
  };

  outputs =
    { self, nixpkgs, systems }:
    let
      inherit (nixpkgs) lib;
      eachSystem = lib.genAttrs (import systems);
      pkgsFor = eachSystem (system: nixpkgs.legacyPackages.${system});

      # overlay.nix holds the package set; this flake only re-exports it.
      overlay = import ./overlay.nix;
      setFor = system: overlay pkgsFor.${system} pkgsFor.${system};
    in
    {
      overlays.default = overlay;

      # Every mirrored agent, by id. This lives in legacyPackages rather than
      # packages so `nix flake show` doesn't try to enumerate ~40k derivations;
      # `nix build .#<id>` resolves here all the same, and the attribute values
      # are lazy, so building one agent fetches one file.
      legacyPackages = eachSystem (system: (setFor system).ms-agents);

      devShells = eachSystem (
        system:
        let
          pkgs = pkgsFor.${system};
          python = pkgs.python3.withPackages (ps: [
            ps.pyyaml
            # Only needed for the browser-driven harvest; the default scraper
            # is stdlib-only. See bin/download-agent-links.
            ps.playwright
          ]);
        in
        {
          default = pkgs.mkShell {
            packages = [
              python
              pkgs.playwright-driver.browsers
              pkgs.curl
              pkgs.gh
              pkgs.oras
              pkgs.git
              pkgs.git-lfs
              pkgs.yq-go
              pkgs.jq
              pkgs.nixfmt-rfc-style
            ];

            # Point playwright at the nix-built browsers instead of letting it
            # download its own, which fails on NixOS.
            env = {
              PLAYWRIGHT_BROWSERS_PATH = "${pkgs.playwright-driver.browsers}";
              PLAYWRIGHT_SKIP_VALIDATE_HOST_REQUIREMENTS = "true";
            };

            shellHook = ''
              echo "ms-agents.nix dev shell"
              echo "  ./bin/download-agent-links            # harvest -> agents.yaml"
              echo "  ./bin/download-agent-links --validate # HEAD every url"
            '';
          };
        }
      );

      # Deliberately small: a flake-show-able handful plus the selection
      # helper. The full set is in legacyPackages.
      packages = eachSystem (
        system:
        let
          set = setFor system;
          classics = lib.filterAttrs (
            id: _: lib.hasSuffix "-classic-ms-agents" id
          ) set.ms-agents;
        in
        classics
        // lib.optionalAttrs (classics != { }) {
          default = set.ms-agentsWith (lib.attrNames classics);
        }
      );

      # nix run .#update -- re-harvest agents.yaml from tmafe.com.
      apps = eachSystem (system: {
        update = {
          type = "app";
          program = lib.getExe (
            pkgsFor.${system}.writeShellApplication {
              name = "update";
              runtimeInputs = [ (pkgsFor.${system}.python3.withPackages (ps: [ ps.pyyaml ])) ];
              text = ''exec ./bin/download-agent-links "$@"'';
            }
          );
        };
      });

      formatter = eachSystem (system: pkgsFor.${system}.nixfmt-tree);
    };
}
