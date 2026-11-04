# Every mirrored Microsoft Agent character, as a nixpkgs overlay.
#
# This file is the source of truth for the package set; flake.nix re-exports it.
# It takes only `final`/`prev`, so stable (non-flake) Nix works too:
#
#   import <nixpkgs> { overlays = [ (import ./overlay.nix) ]; }
#
# Nothing is vendored. agents.json carries a url and a sha256 per agent, and
# each package is a `fetchurl` of exactly one file, so adding this repo as a
# flake input costs a manifest -- not the 34 GB of characters behind it. Only
# the agents you actually build are ever downloaded.
final: _prev:
let
  inherit (final) lib;

  # Written by the download-agents workflow. Absent on a fresh checkout that
  # has never mirrored, and an empty set is a better failure than an eval error.
  index = if builtins.pathExists ./agents.json then lib.importJSON ./agents.json else { };

  mkAgent =
    id: agent:
    let
      # The release asset is canonical; upstream is a fallback for an agent
      # mirrored but not yet released. fetchurl walks the list in order, and
      # the sha256 makes it safe to take whichever answers first.
      urls = lib.filter (u: u != null && u != "") [ (agent.url or null) (agent.upstream or null) ];
    in
    final.runCommand "ms-agent-${id}"
      {
        src = final.fetchurl {
          name = "${id}.acs";
          inherit urls;
          inherit (agent) sha256;
        };
        passthru = { inherit (agent) sha256; agentFile = agent.file; };
        meta = {
          description = "Microsoft Agent character ${agent.file}";
          homepage = "https://tmafe.com/${agent.dir}/";
          # Plain data: no platform or licence claim is ours to make. These are
          # third-party uploads mirrored from a community archive.
          platforms = lib.platforms.all;
        };
      }
      ''
        install -Dm444 "$src" "$out/share/ms-agents/${agent.file}"
      '';

  agents = lib.mapAttrs mkAgent index;
in
{
  ms-agents = agents;

  # The selection helper: one package holding just the agents named, so a
  # consumer writes `ms-agentsWith [ "merlin" "peedy" ]` and downloads two
  # files rather than the whole archive.
  ms-agentsWith =
    ids:
    let
      missing = lib.filter (id: !(agents ? ${id})) ids;
    in
    assert lib.assertMsg (missing == [ ])
      "ms-agentsWith: unknown agent(s): ${lib.concatStringsSep ", " missing}";
    final.symlinkJoin {
      name = "ms-agents-selection-${toString (lib.length ids)}";
      paths = map (id: agents.${id}) ids;
    };
}
