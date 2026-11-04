# Stable-Nix entry point: the agent set, without flakes or an overlay.
#
#   nix-build -A merlin
#   (import (fetchTarball "https://github.com/n-at-han-k/ms-agents.nix/archive/main.tar.gz") { }).merlin
{ pkgs ? import <nixpkgs> { } }:
# final = prev = pkgs: applying the overlay directly avoids re-running the whole
# nixpkgs fixpoint (pkgs.extend) just to read one leaf back out.
(import ./overlay.nix pkgs pkgs).ms-agents
