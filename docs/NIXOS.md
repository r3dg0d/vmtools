# NixOS

Host already enables libvirt / QEMU / swtpm / virt-manager via
`modules/apple-virtualization.nix`.

User groups: `libvirtd`, `kvm`, `docker`.

Default URI for these tools: `qemu:///session` (disks under `~/.local/share`).
For `qemu:///system`, put disks in `/var/lib/libvirt/images` (or make `$HOME`
searchable by the qemu user — mode `0700` home will break system URI).

## Package (`nix/package.nix`)

Stdlib-only Python app with three entry points: `windowsvm`, `linuxvm`,
`androidvm`. PATH wrappers should expose:

- qemu_kvm, libvirt (`virsh`, `virt-install`), virt-manager, virt-viewer
- guestfs-tools, swtpm, docker-client, curl, coreutils

OVMF comes from the QEMU package on this host (already verified by
`windowsvm doctor`).

## Suggested system wire-up (mirror apple-vm-tools)

1. Vendor or fetch the src. Easiest while developing: point `src` at
   `/home/neo/Projects/vmtools`. For a clean flake, pin a GitHub fetch:

   ```nix
   # packages/vmtools/default.nix  (drop next to packages/apple/)
   { lib, python3Packages, makeWrapper, qemu_kvm, libvirt, virt-manager,
     virt-viewer, guestfs-tools, swtpm, docker-client, coreutils, curl }:
   python3Packages.buildPythonApplication {
     pname = "vmtools";
     version = "0.1.0";
     pyproject = true;
     src = /home/neo/Projects/vmtools;  # or fetchFromGitHub { owner="r3dg0d"; repo="vmtools"; ... }
     build-system = [ python3Packages.hatchling ];
     nativeBuildInputs = [ makeWrapper ];
     dependencies = [];
     doCheck = false;
     postFixup = ''
       for prog in windowsvm linuxvm androidvm; do
         wrapProgram $out/bin/$prog \
           --prefix PATH : ${lib.makeBinPath [
             qemu_kvm libvirt virt-manager virt-viewer guestfs-tools
             swtpm docker-client coreutils curl
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
   ```

2. In `modules/apple-virtualization.nix` (or a new `modules/vmtools.nix`
   imported by the host flake):

   ```nix
   vmTools = pkgs.callPackage ../packages/vmtools { };
   # ...
   environment.systemPackages = [
     # ...
     vmTools
   ];
   ```

3. `nixos-rebuild switch`. Confirm:

   ```bash
   which windowsvm linuxvm androidvm
   windowsvm doctor
   linuxvm doctor
   androidvm doctor
   ```

Until wired, the repo installs user wrappers at `~/.local/bin/{windowsvm,linuxvm,androidvm}`
pointing at system `python3` + `bin/run-tool.py`.

## Android Pro secrets

Keep out of the Nix store and out of git:

```bash
install -m 600 /dev/null ~/.config/vmtools/secrets.env
# ANDROIDVM_DOCKER_USER=...
# ANDROIDVM_DOCKER_TOKEN=...
```

`androidvm setup` / `doctor` load that file.
