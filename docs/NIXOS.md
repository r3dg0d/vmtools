# NixOS

Host already enables libvirt/QEMU/swtpm/virt-manager via `modules/apple-virtualization.nix`.

User groups: `libvirtd`, `kvm`, `docker`.

Default URI for these tools: `qemu:///session` (home-dir disks). For `qemu:///system`, put disks in `/var/lib/libvirt/images` or make home searchable by the qemu user.

Package integration: see `nix/package.nix` (wire into the system flake similarly to `packages/apple/vm-tools.nix`).
