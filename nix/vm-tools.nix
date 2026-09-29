{ lib, python3Packages, makeWrapper, qemu_kvm, libvirt, virt-manager, virt-viewer,
  guestfs-tools, swtpm, OVMFFull, docker-client, coreutils, curl }:
python3Packages.buildPythonApplication {
  pname = "vmtools";
  version = "0.1.0";
  pyproject = true;
  src = ../.;
  build-system = [ python3Packages.hatchling ];
  nativeBuildInputs = [ makeWrapper ];
  dependencies = [];
  doCheck = false;
  postFixup = ''
    for prog in windowsvm linuxvm androidvm; do
      wrapProgram $out/bin/$prog \
        --prefix PATH : ${lib.makeBinPath [
          qemu_kvm libvirt virt-manager virt-viewer guestfs-tools swtpm docker-client coreutils curl
        ]} \
        --set-default VMTOOLS_DOC $out/share/doc/vmtools
    done
  '';
  meta = {
    description = "windowsvm, linuxvm, androidvm CLI suite";
    license = lib.licenses.mit;
    platforms = lib.platforms.linux;
  };
}
