# Pinned upstream helper assets for macosvm / iosvm — no Apple binaries in here.
#   osx-kvm/   kholia/OSX-KVM: OpenCore.qcow2 (BSD), OVMF (BSD-2), fetch-macOS-v2.py (pulls recovery from Apple)
#   darwin-vm/ jprx/darwin-vm: dt_fixup.py, build_tc.py, nvram.bin, sysroot tarballs, get_files.sh, fix_perms.sh
# nix-build nix/apple-assets.nix -o ~/.local/share/vmtools/apple/assets
{ pkgs ? import <nixpkgs> { }, lib ? pkgs.lib, stdenvNoCC ? pkgs.stdenvNoCC, fetchFromGitHub ? pkgs.fetchFromGitHub }:
let
  osx-kvm = fetchFromGitHub {
    owner = "kholia"; repo = "OSX-KVM";
    rev = "4c378a4b5e0b219783683012bec680325eb40719";
    hash = "sha256-BmMWWGkNtZwEH9utoc3Mj5gGCjlgIicGsTEPxAxG7hw=";
  };
  darwin-vm = fetchFromGitHub {
    owner = "jprx"; repo = "darwin-vm";
    rev = "edfc19433da8d04d5927a7b1932acce4034f307c";
    hash = "sha256-JjvpjhxVJXM2DuVEy+3sT3PuuiSU6CNR0RB1Hk+tMQU=";
  };
in
stdenvNoCC.mkDerivation {
  pname = "vmtools-apple-assets";
  version = "2026-10-20";
  dontUnpack = true;
  installPhase = ''
    mkdir -p $out/osx-kvm/OpenCore $out/darwin-vm
    cp ${osx-kvm}/{OVMF_CODE_4M.fd,OVMF_VARS.fd,OVMF_VARS-1920x1080.fd,OVMF_VARS-1024x768.fd,fetch-macOS-v2.py,LICENSE,README.md} $out/osx-kvm/ 2>/dev/null || true
    cp ${osx-kvm}/OpenCore/{OpenCore.qcow2,config.plist} $out/osx-kvm/OpenCore/
    cp -r ${darwin-vm}/{dt_fixup.py,build_tc.py,nvram.bin,get_files.sh,fix_perms.sh,run.sh,launchdaemons,sysroot,LICENSE,README.md} $out/darwin-vm/
    chmod -R u+w $out
  '';
  meta = { description = "OSX-KVM + darwin-vm helper assets for vmtools macosvm/iosvm"; platforms = lib.platforms.linux; };
}
