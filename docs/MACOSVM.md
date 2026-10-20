# macosvm — macOS Construct

Two backends:

| backend | what runs | when |
|---|---|---|
| `qemu` (default) | QEMU/KVM + OpenCore + OVMF, the [OSX-KVM](https://github.com/kholia/OSX-KVM) recipe, headless with VNC on 127.0.0.1 | full control, uses your own media, no Docker |
| `docker-osx` | [sickcodes/docker-osx](https://github.com/sickcodes/Docker-OSX) (QEMU inside a container; the route in [this dev.to guide](https://dev.to/ianito/how-to-emulate-ios-on-linux-with-docker-4gj3)) on rootless Docker, X11 window | quickest path to Xcode + iOS Simulator |

```
macosvm doctor                         host, tools, OpenCore/OVMF, imported media, Docker
macosvm import PATH [--kind K] [--name ID] [--move|--link] [--no-hash]
macosvm imports [--rm ID]
macosvm extract ID                     best-effort BaseSystem out of InstallAssistant.pkg / SharedSupport.dmg (7-Zip)
macosvm fetch-recovery sonoma          recovery from osrecovery.apple.com (OSX-KVM fetch-macOS-v2.py)
macosvm create --name mac [--version V] [--media ID|none] [--backend qemu|docker-osx] [--cpus/--ram/--disk] [--dry-run]
macosvm start|stop|shutdown|status|info|display|console|delete NAME     (start --dry-run prints the QEMU line)
macosvm config [KEY [VALUE]]           macos_* keys in ~/.config/vmtools/config.json
```

Data: `~/.local/share/vmtools/apple/macos/{imports,vms}`; every import is sha256-hashed into `imports/manifest.json`.

## What `import` accepts

| file | kind | used as |
|---|---|---|
| `BaseSystem.dmg` / `RecoveryImage.dmg` (or `.img`) | `basesystem` | recovery boot → online install (converted with dmg2img) |
| `*.img` / `.cdr` / `.dmg` / `.iso` from `createinstallmedia` + `hdiutil convert` | `installer-image` | offline full install |
| `Install macOS *.app` | `installer-app` | BaseSystem pulled out if present (≤ Catalina); otherwise convert (below) |
| `InstallAssistant.pkg`, `SharedSupport.dmg` | `installer-pkg` / `shared-support` | `macosvm extract` (best effort) or convert on the Mac |
| `OpenCore.qcow2` / OpenCore `.img` / EFI folder | `opencore` | boot disk (default: OSX-KVM's) |
| `config.plist` | `opencore-config` | recorded; rebuild the disk with OSX-KVM `opencore-image-ng.sh` |
| `OVMF_CODE*.fd`, `OVMF_VARS*.fd` | `ovmf-code` / `ovmf-vars` | firmware + per-VM NVRAM template |
| `*.ipsw` | `ipsw` | Apple-silicon only: not bootable under x86 KVM, see iosvm |

## Getting the files on your Mac

```bash
# full installer (lands in /Applications/Install macOS <Name>.app)
softwareupdate --list-full-installers
softwareupdate --fetch-full-installer --full-installer-version 14.7.1

# a) bootable offline installer image (most reliable)
hdiutil create -o ~/Desktop/sonoma -size 18g -layout GPTSPUD -fs HFS+J
hdiutil attach ~/Desktop/sonoma.dmg -noverify -mountpoint /Volumes/install_build
sudo "/Applications/Install macOS Sonoma.app/Contents/Resources/createinstallmedia" --volume /Volumes/install_build --nointeraction
hdiutil detach "/Volumes/Install macOS Sonoma"
hdiutil convert ~/Desktop/sonoma.dmg -format UDTO -o ~/Desktop/sonoma.cdr   # raw image -> import this
# b) or just the recovery BaseSystem (small; installs over the network)
#    Big Sur+: it is inside SharedSupport.dmg ->  com_apple_MobileAsset_MacSoftwareUpdate/*.zip -> AssetData/Restore/BaseSystem.dmg
hdiutil attach "/Applications/Install macOS Sonoma.app/Contents/SharedSupport/SharedSupport.dmg"
```

The InstallAssistant.pkg from Apple's catalog (e.g. via [Mr. Macintosh's list](https://mrmacintosh.com/macos-sonoma-full-installer-database-download-directly-from-apple/), all `swcdn.apple.com` links) can be copied as-is and run through `macosvm extract`.

Copy to Linux with LocalSend, `scp`, or a USB disk, then `macosvm import <file>`. `--link` avoids a copy when the file is on a mounted share.

## Notes
* `kvm ignore_msrs=1` avoids guest panics: `boot.extraModprobeConfig = "options kvm ignore_msrs=1 report_ignored_msrs=0";`
* CPU model: `penryn` up to Sonoma, `modern` (Skylake-Client) for Sequoia/Tahoe; `--cpu-model` overrides.
* Apple's licence allows macOS VMs only on Apple hardware; this tool just runs what you supply.
