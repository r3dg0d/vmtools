# iosvm — iOS Construct

## Backends and the default

| backend | what you get | needs |
|---|---|---|
| **`qemu-sptm` (default)** | jprx/[darwin-vm](https://github.com/jprx/darwin-vm): QEMU's `-M darwin` boots a real iOS 27 / Apple-silicon kernelcache, SPTM/TXM and a bash-patched restore ramdisk to a **serial root shell**. No screen, GPU, Wi-Fi or SpringBoard. | `nix/qemu-sptm.nix` (built by the package), a firmware set |
| `sim` (Xcode Simulator) | iOS apps in the Simulator inside a macOS guest — the [Docker-OSX guide](https://dev.to/ianito/how-to-emulate-ios-on-linux-with-docker-4gj3) route. `iosvm sim MACVM [simctl args]` runs `xcrun simctl` over SSH. | a `macosvm` guest (`--backend docker-osx` or `qemu`) with Xcode and Remote Login |

Why qemu-sptm is the default: it is the only route that runs actual iOS code under emulation, it is
small (a few hundred MB of firmware, not a 60 GB macOS + Xcode install), it needs neither Docker nor
an Apple ID, and every Apple file is user-supplied or fetched file-by-file from Apple's CDN. The
Simulator route is better for app testing, so it is one command away.

The [WitherOrNot gist](https://gist.github.com/WitherOrNot/71d2d91009ea070d8bfc5ce3e35936bb) (full iOS
restore via patched idevicerestore, APFS edits, companion-VM networking, SSH/TrollStore) builds on the
same idea; it is documented here as a manual follow-on, not automated.

```
iosvm doctor
iosvm import firmware/ [--name ID]       darwin-vm firmware set (bootkc dtree ramdisk.dmg [ramdisk.tc sptm txm info])
iosvm import X_Restore.ipsw              then: iosvm fetch --ipsw ID --device iPhone17,3
iosvm fetch [--device ID] [--url APPLE_CDN_URL | --ipsw ID] [--dry-run]
iosvm create --name iphone [--firmware ID] [--ram 8] [--qemuports]
iosvm start|stop|status|info|console|delete NAME    (start --dry-run prints the QEMU line)
iosvm sim MACVM [simctl ...]
```

## Getting a firmware set on your Mac

`fetch` on Linux downloads and unwraps everything (ipsw + dt_fixup), but the ramdisk patch
(adding bash, ad-hoc signing, building `ramdisk.tc`) uses `hdiutil` and `codesign`, so finish on the Mac:

```bash
brew install ipsw jq
git clone --recursive https://github.com/jprx/darwin-vm && cd darwin-vm
./get_files.sh            # default iPhone17,3 (iPhone 16) iOS 27.0; DEVNAME=… URL=… to change
./fix_perms.sh firmware/ramdisk.dmg
# copy darwin-vm/firmware/ to Linux, then:  iosvm import firmware --name ios27
```

IPSWs come from Apple's CDN (`updates.cdn-apple.com`); `ipsw download ipsw --device iPhone17,3 --latest`
or https://ipsw.me list the official links. `iosvm fetch --url` refuses non-Apple hosts.

## qemu-sptm
`nix/qemu-sptm.nix` builds jprx/qemu-sptm @ bad6336 (the darwin-vm submodule pin) on nixpkgs' qemu,
aarch64-softmmu only, `--disable-pvg`, with the meson subprojects pinned. Dev checkout:
`nix-build -E 'with import <nixpkgs> {}; callPackage ./nix/qemu-sptm.nix {}' -o ~/.local/share/vmtools/apple/qemu-sptm`
then `iosvm config ios_qemu ~/.local/share/vmtools/apple/qemu-sptm/bin/qemu-system-aarch64`.
