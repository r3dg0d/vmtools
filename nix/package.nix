# Wire into the NixOS flake like packages/apple/vm-tools.nix.
# See docs/NIXOS.md. Upstream: https://github.com/r3dg0d/vmtools
{ lib, python3Packages, makeWrapper, qemu_kvm, libvirt, virt-manager, virt-viewer,
  guestfs-tools, swtpm, OVMFFull, docker-client, coreutils, curl,
  callPackage, ipsw, jq, dmg2img, _7zz, socat, openssh }:
let
  qemu-sptm = callPackage ./qemu-sptm.nix { };
  apple-assets = callPackage ./apple-assets.nix { };
in
python3Packages.buildPythonApplication {
  pname = "vmtools";
  version = "0.1.2";
  pyproject = true;
  src = ../.;
  build-system = [ python3Packages.hatchling ];
  nativeBuildInputs = [ makeWrapper ];
  dependencies = [];
  doCheck = false;
  pythonImportsCheck = [ "vmtools" "windowsvm" "linuxvm" "androidvm" "iosvm" "macosvm" ];
  postInstall = ''
    mkdir -p $out/share/doc/vmtools $out/share/applications
    if [ -d docs ]; then cp -R docs/. $out/share/doc/vmtools/; fi
    if [ -f README.md ]; then install -Dm644 README.md $out/share/doc/vmtools/README.md; fi
    ln -s ${qemu-sptm}/bin/qemu-system-aarch64 $out/bin/qemu-system-aarch64-sptm
    if [ -d completions ]; then install -Dm644 completions/*.bash -t $out/share/bash-completion/completions/; fi
    if [ -d share/applications ]; then
      install -Dm644 share/applications/*.desktop -t $out/share/applications/
    fi
  '';
  postFixup = ''
    for prog in windowsvm linuxvm androidvm vmtools iosvm macosvm; do
      wrapProgram $out/bin/$prog \
        --prefix PATH : ${lib.makeBinPath [
          qemu_kvm libvirt virt-manager virt-viewer guestfs-tools swtpm docker-client coreutils curl
          ipsw jq dmg2img _7zz socat openssh
        ]} \
        --set-default VMTOOLS_DOC $out/share/doc/vmtools \
        --set-default VMTOOLS_SHARE ${apple-assets} \
        --set-default VMTOOLS_QEMU_SPTM ${qemu-sptm}/bin/qemu-system-aarch64
    done
  '';
  meta = {
    description = "windowsvm, linuxvm, androidvm, iosvm, macosvm, vmtools CLI/TUI suite";
    license = lib.licenses.mit;
    platforms = lib.platforms.linux;
    mainProgram = "vmtools";
  };
}
