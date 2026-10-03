# Compatibility path. Nothing in this repo imports this file.
# nix/package.nix is the only package definition. Re-export it so a
# copied callPackage follows that version instead of installing the
# old 0.1.0 expression. Do not add a second version pin here.
import ./package.nix
