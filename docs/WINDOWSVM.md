# windowsvm

Manages Windows guests via libvirt + virt-install.

- Catalog: Win11 25H2, Enterprise Eval, LTSC Eval, IoT Enterprise LTSC 2024 Eval, custom ISO
- Microsoft CDN URLs are **not** hardcoded forever; consumer downloads fall back to official pages + `--iso`
- VirtIO drivers: `windowsvm iso download --virtio` (Fedora virtio-win)
- Defaults: UEFI, TPM 2.0 (swtpm), Q35-ish via virt-install, VirtIO disk/net, SPICE

```bash
windowsvm create --iso ~/Downloads/Win11.iso
windowsvm launch win11-dev
windowsvm gui
windowsvm snapshot win11-dev clean
windowsvm doctor
```
