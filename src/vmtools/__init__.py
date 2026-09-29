"""Shared foundation for windowsvm, linuxvm and androidvm.

Sibling tools to iosvm/macosvm (apple-vm-tools). Same UX: colours, --json,
--verbose/--debug/--quiet, XDG layouts, atomic JSON config, clean Fail exits.
Windows/Linux use libvirt+QEMU/KVM; Android scaffolds Docker-Android-Pro.
"""

__version__ = "0.1.1"
