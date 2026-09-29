# Wire into the NixOS flake like packages/apple/vm-tools.nix.
# See docs/NIXOS.md. Upstream: https://github.com/r3dg0d/vmtools
{ lib, python3Packages, makeWrapper, qemu_kvm, libvirt, virt-manager, virt-viewer,
  guestfs-tools, swtpm, OVMFFull, docker-client, coreutils, curl }:
python3Packages.buildPythonApplication {
  pname = "vmtools";
  version = "0.1.1";
  pyproject = true;
  src = ../.;
  build-system = [ python3Packages.hatchling ];
  nativeBuildInputs = [ makeWrapper ];
  dependencies = [];
  doCheck = false;
  pythonImportsCheck = [ "vmtools" "windowsvm" "linuxvm" "androidvm" ];
  postInstall = ''
    mkdir -p $out/share/doc/vmtools $out/share/applications
    if [ -d docs ]; then cp -R docs/. $out/share/doc/vmtools/; fi
    if [ -f README.md ]; then install -Dm644 README.md $out/share/doc/vmtools/README.md; fi
    if [ -d share/applications ]; then
      install -Dm644 share/applications/*.desktop -t $out/share/applications/
    fi
  '';
  postFixup = ''
    for prog in windowsvm linuxvm androidvm vmtools; do
      wrapProgram $out/bin/$prog \
        --prefix PATH : ${lib.makeBinPath [
          qemu_kvm libvirt virt-manager virt-viewer guestfs-tools swtpm docker-client coreutils curl
        ]} \
        --set-default VMTOOLS_DOC $out/share/doc/vmtools
    done
  '';
  meta = {
    description = "windowsvm, linuxvm, androidvm, vmtools CLI/TUI suite";
    license = lib.licenses.mit;
    platforms = lib.platforms.linux;
    mainProgram = "vmtools";
  };
}
