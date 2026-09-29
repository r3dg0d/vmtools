# Architecture

Python 3.11+ stdlib only (same philosophy as apple-vm-tools). Shared package `vmtools` provides UI, paths, config, download/resume, checksums, libvirt wrappers, doctor, menus.

```text
src/
  vmtools/          # shared
  windowsvm/
  linuxvm/providers/# DistroProvider plugins
  androidvm/
```

CLIs share argparse globals (`-v/--debug/-q/--json`), Fail exit codes, and XDG layout under the `vmtools` tool name.

Libvirt is the VM registry. Metadata JSON under `metadata/vm-*.json` tags OS flavor for listing filters.
