# VM Tools

Sibling CLI/TUI suite for personal VMs on NixOS, matching the look and feel of `iosvm` / `macosvm`.

| Command | Role |
|---------|------|
| `vmtools` | Umbrella TUI / doctor / list (this repo) |
| `windowsvm` | Windows Construct — QEMU/KVM/libvirt |
| `linuxvm` | Linux Construct — QEMU/KVM/libvirt |
| `androidvm` | Android Construct — Docker-Android-Pro |
| `iosvm` | iOS virtualization (apple-vm-tools) |
| `macosvm` | macOS QEMU/KVM (apple-vm-tools) |

## Quick start

```bash
vmtools doctor          # read-only host checks (does not stop VMs)
vmtools list
vmtools                 # interactive suite menu (or: vmtools tui)

windowsvm tui           # Windows Construct menu
linuxvm tui
androidvm tui

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

## TUI / GUI

- **Terminal menus** (stdlib, no extra deps): bare `windowsvm` / `linuxvm` / `androidvm` / `vmtools`, or the explicit `tui` subcommand.
- **Desktop entries** (Matrix-ish Construct names): `VM Construct`, `Windows Construct`, `Linux Construct`, `Android Construct` under `share/applications/` (also `~/.local/share/applications/` on this host). They launch `ghostty -e <tool> tui`.
- Guest GUIs stay as before: `windowsvm gui` / `linuxvm gui` → virt-manager; `androidvm gui` → noVNC.

## Install (this machine)

System package (NixOS): `windowsvm` / `linuxvm` / `androidvm` on PATH via `apple-virtualization` → `packages/vmtools`. After a rebuild that picks up ≥0.1.1, `vmtools` is on PATH too.

Dev wrappers (no rebuild):

```bash
export PATH="$HOME/.local/bin:$PATH"   # → Projects/vmtools via bin/run-tool.py
```

## Android / Docker-Android-Pro

`androidvm` manages the Pro backend. Credentials must be provided legitimately:

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
