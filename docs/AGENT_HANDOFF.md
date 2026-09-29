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
