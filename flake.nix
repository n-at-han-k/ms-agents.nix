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
    in
    {
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

      formatter = eachSystem (system: pkgsFor.${system}.nixfmt-tree);
    };
}
