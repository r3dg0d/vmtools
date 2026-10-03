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

1. Call `nix/package.nix`. That file is the only package definition
   (version string lives there; currently 0.1.2). `nix/vm-tools.nix`
   only re-exports it. Do not paste a second expression with its own
   version:

   ```nix
   # modules/apple-virtualization.nix (or a new modules/vmtools.nix)
   vmTools = pkgs.callPackage /home/neo/Projects/vmtools/nix/package.nix { };
   # ...
   environment.systemPackages = [
     # ...
     vmTools
   ];
   ```

   For a flake pin, `fetchFromGitHub` the tag you want and override `src`.
   Prefetch the narHash; do not invent it. A local path is enough while
   developing.

2. `nixos-rebuild switch`. Confirm:

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
