# AGENT_HANDOFF — vmtools

## REPOSITORY
`/home/neo/Projects/vmtools` (local; not yet pushed)

Commits: see `git log --oneline`

## BRANCH
master

## GIT STATUS
See repo; ensure `secrets.env` is never committed (lives in `~/.config/vmtools/`).

## EXISTING IOSVM / MACOSVM
Nix package `apple-vm-tools` at `/etc/nixos/packages/apple/vmtools` — Python, shared `applevm` UI. PATH: `/run/current-system/sw/bin/{iosvm,macosvm}`.

## SHARED ARCHITECTURE
Python stdlib sibling under `src/vmtools` + three CLIs. PATH wrappers: `~/.local/bin/{windowsvm,linuxvm,androidvm}`.

## NIXOS CONFIG
`virtualisation.libvirtd` + swtpm + virt-manager already on. Default tool URI: `qemu:///session`.

## KVM / LIBVIRT / VIRT-MANAGER
doctor OK on host.

## ISO CACHE / DOWNLOADER / CHECKSUM
Implemented under `~/.local/share/vmtools/isos/...` with `.part` resume + SHA-256.

## WINDOWSVM
CLI + create wizard + lifecycle + snapshots/clone/gui/doctor. Official Win ISO CDN not hardcoded; `--iso` path works. VirtIO download URL set. UEFI+TPM virt-install smoke tested on session URI.

## LINUXVM
Providers: CachyOS (cdn77 + sha256), Debian (SHA256SUMS), Fedora (releases.json), plus stubs for others. Create wizard present.

## ANDROIDVM
status/doctor/setup work. `docker login` succeeded with secrets.env. Lifecycle commands still scaffolded.

## DOCKER-ANDROID-PRO ACCESS
Configured via `~/.config/vmtools/secrets.env` (0600). **Rotate chat-pasted PAT.**

## TESTS
`python3 -m unittest discover -s tests` — 6 passed (checksum, names, json, ports, access).

## NOT TESTED
Full Windows ISO download; full Linux ISO download + guest boot to desktop; Android container pull/run; shell completions/man pages polish; NixOS flake package install.

## NEXT
1. Wire `nix/package.nix` into system flake (or ask nix megaprompt).
2. Implement androidvm create/launch/adb with localhost ports.
3. Optional Microsoft media resolver when API allows.
4. Live download test for Debian netinst.
5. Desktop entries + completions.

## Status update (2026-09-29 01:57 PT)

### Verified on zionsec
- `linuxvm`: Debian 13.7.0 netinst ISO cached+SHA256-verified; VM `debian-netinst` created (4c/4G/40G), shut off, disk-only snapshot `pre-install` OK.
- UEFI internal snapshots fail (pflash NVRAM); `snapshot_create` falls back to `--disk-only`.
- Default libvirt URI remains `qemu:///session` (home is mode 0700).
- `androidvm`: Docker login as `budtmo2` OK; Pro repo is `budtmo2/docker-android-pro` (not `budtmo/...`).
- Instance `pixel15` defined (`emulator_15.0`, viewer 127.0.0.1:6080, adb 6081); image pull may still be in progress.
- Virtio-win ISO download may still be in progress under `~/.local/share/vmtools/isos/windows/drivers/`.
- Wrappers: `~/.local/bin/{windowsvm,linuxvm,androidvm}` → system python3 + `bin/run-tool.py`.
- Latest commit: `linuxvm noninteractive create + android Pro lifecycle`.

### Secrets
- `~/.config/vmtools/secrets.env` (0600): `ANDROIDVM_DOCKER_USER` / `ANDROIDVM_DOCKER_TOKEN`.
- PAT was pasted in chat earlier — **rotate** and update secrets.env; never commit.

### Still open
1. Finish `emulator_15.0` pull → `androidvm launch pixel15` → gui/adb smoke.
2. Finish virtio-win cache; optional Windows ISO (manual `--iso` / Microsoft page).
3. Wire `nix/package.nix` into system flake (or hand to nix megaprompt).
4. Completions/man; push GitHub if requested.
5. Optional: complete Debian install via `linuxvm gui debian-netinst`.

### Quick checks
```bash
export PATH="$HOME/.local/bin:$PATH"
linuxvm list
androidvm list
androidvm images
tail -f ~/.local/share/vmtools/logs/android-pull-15.log
tail -f ~/.local/share/vmtools/logs/virtio-pull.log
```

### Later (2026-09-29 02:05 PT)
- Virtio-win ISO cached: `~/.local/share/vmtools/isos/windows/drivers/virtio-win.iso` (837 MiB).
- Pulled `budtmo2/docker-android-pro:emulator_15.0` (~10.7 GB).
- `androidvm launch pixel15` → running; ports 127.0.0.1:6080 (noVNC) / :6081 (ADB).

### ADB note (2026-09-29 02:11 PT)
- Emulator booted (Android 15, `sys.boot_completed=1`). noVNC: http://127.0.0.1:6080
- Host `adb connect 127.0.0.1:6081` stays **offline** (Docker-Android local transport). Use `androidvm adb|shell|logcat` → `docker exec … adb`.
- Next `androidvm launch` gets `--shm-size 2g` + paired 5554 publish.

### Publish (2026-09-29 02:17 PT)
- GitHub: https://github.com/r3dg0d/vmtools (public, `master` @ 2fdc1f9+)
- Virtio-win cached; `windowsvm create` will attach it by default.
- NixOS system package: handed to nix megaprompt (wire `nix/package.nix` like apple-vm-tools). Until then use `~/.local/bin` wrappers.
- Rotate Docker Hub PAT that was pasted in chat; refresh `~/.config/vmtools/secrets.env`.
