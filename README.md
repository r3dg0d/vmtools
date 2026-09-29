# VM Tools

Sibling CLI suite for personal VMs on NixOS, matching the look and feel of `iosvm` / `macosvm`.

| Command | Role |
|---------|------|
| `iosvm` | iOS virtualization (existing apple-vm-tools) |
| `macosvm` | macOS QEMU/KVM (existing apple-vm-tools) |
| `windowsvm` | Windows QEMU/KVM/libvirt |
| `linuxvm` | Linux QEMU/KVM/libvirt |
| `androidvm` | Docker-Android-Pro manager |

## Quick start

```bash
windowsvm doctor
linuxvm doctor
androidvm status

windowsvm create --iso /path/to/windows.iso
linuxvm create          # interactive; CachyOS / Debian / Fedora first
androidvm setup         # requires ANDROIDVM_DOCKER_* or ~/.config/vmtools/secrets.env
```

Default libvirt URI is `qemu:///session` so disks under `~/.local/share/vmtools/` work without making `$HOME` world-searchable. Switch to system with:

```bash
windowsvm config libvirt_uri qemu:///system
```

(System URI needs images in a libvirt-accessible pool such as `/var/lib/libvirt/images`.)

## Install (this machine)

Wrappers are on `PATH` via `~/.local/bin/{windowsvm,linuxvm,androidvm}` pointing at this repo.

```bash
export PATH="$HOME/.local/bin:$PATH"
```

## Android / Docker-Android-Pro

`androidvm` is scaffolded for the Pro backend. Credentials must be provided legitimately:

- env: `ANDROIDVM_DOCKER_USER` + `ANDROIDVM_DOCKER_TOKEN`
- or file: `~/.config/vmtools/secrets.env` (mode `0600`, never commit)

`androidvm setup` runs `docker login` only with those credentials. No bypass of sponsor gates.

**Rotate any token that was pasted into chat.**

## Layout

```text
~/.local/share/vmtools/{isos,disks,cache,metadata,logs,android}/
~/.config/vmtools/config.json
~/.config/vmtools/secrets.env   # optional, gitignored location outside repo
```

## Docs

See `docs/` for architecture, per-tool notes, ISO sources, NixOS, verification, and agent handoff.

## License

MIT — see [LICENSE](LICENSE).
