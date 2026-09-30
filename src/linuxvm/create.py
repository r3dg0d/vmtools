"""Linux VM creation via virt-install."""

from __future__ import annotations

from pathlib import Path

from vmtools import libvirt as lv
from vmtools.config import validate_name, write_json
from vmtools.download import download
from vmtools.layout import LAYOUT, config, ensure
from vmtools.menu import confirm, prompt
from vmtools.ui import EXIT_USAGE, OUT, Fail

from .providers import get, list_providers


def interactive_create(args) -> int:
    ensure()
    cfg = config()
    noninteractive = bool(getattr(args, "yes", False) or getattr(args, "iso", None) and getattr(args, "name", None) and getattr(args, "distro", None))

    OUT.say()
    OUT.say("Create Linux VM")
    OUT.say("─" * 28)

    providers = sorted(list_providers(), key=lambda p: (p.priority, p.id))
    distro_arg = getattr(args, "distro", None)
    if distro_arg:
        prov = get(distro_arg)
    elif noninteractive:
        raise Fail("--distro required in noninteractive mode", EXIT_USAGE)
    else:
        OUT.say("Distribution")
        for i, p in enumerate(providers, 1):
            OUT.say(f"  {i}. {p.name}")
        choice = prompt("Selection", "1")
        try:
            prov = providers[int(choice) - 1]
        except (ValueError, IndexError):
            prov = get(choice)

    editions = list(prov.editions())
    edition = getattr(args, "edition", None) or editions[0]
    if not getattr(args, "edition", None) and not noninteractive and len(editions) > 1:
        OUT.say("Edition: " + ", ".join(editions))
        edition = prompt("Edition", editions[0])

    arch = getattr(args, "arch", None) or "x86_64"
    if not noninteractive and not getattr(args, "arch", None):
        arch = prompt("Architecture", arch)

    name = validate_name(getattr(args, "name", None) or (None if noninteractive else prompt("VM Name", f"{prov.id}-test")))
    if not name:
        raise Fail("VM name required", EXIT_USAGE)
    if lv.domain_exists(name):
        raise Fail(f"VM already exists: {name}", EXIT_USAGE)

    iso_path = getattr(args, "iso", None)
    media = None
    if iso_path:
        iso = Path(iso_path).expanduser().resolve()
    elif getattr(args, "offline", False):
        raise Fail("--offline requires --iso", EXIT_USAGE)
    else:
        OUT.step(f"Resolving {prov.name} media metadata")
        media = prov.latest(edition, arch)
        OUT.ok(f"{media.filename} ({media.version})")
        if media.source_page:
            OUT.note(media.source_page)
        dest = LAYOUT.data / "isos/linux" / media.filename
        if not media.url:
            raise Fail("no download URL", EXIT_USAGE, "use --iso")
        iso = download(media.url, dest, expected_sha256=media.sha256, label=media.filename)

    if not iso.is_file():
        raise Fail(f"ISO not found: {iso}", EXIT_USAGE)

    cpus = int(getattr(args, "cpus", None) or (cfg.get("linux_default_cpus") if noninteractive else prompt("CPU cores", str(cfg.get("linux_default_cpus")))))
    ram = int(getattr(args, "ram", None) or (cfg.get("linux_default_ram_gib") if noninteractive else prompt("RAM GiB", str(cfg.get("linux_default_ram_gib")))))
    disk = int(getattr(args, "disk", None) or (cfg.get("linux_default_disk_gib") if noninteractive else prompt("Disk GiB", str(cfg.get("linux_default_disk_gib")))))
    network = getattr(args, "network", None) or ("default" if noninteractive else prompt("Network (default|vm-lab|isolated)", "default"))
    launch = not getattr(args, "no_launch", False)
    if noninteractive:
        launch = not bool(getattr(args, "no_launch", False))
    elif not getattr(args, "yes", False):
        launch = confirm("Start installer when done?", default=True)

    if not getattr(args, "yes", False):
        if not confirm(f"Create {name}?", default=True):
            OUT.warn("cancelled")
            return 0
    else:
        OUT.note(f"Creating {name}: {cpus} vCPU / {ram} GiB / {disk} GiB")

    if network in ("vm-lab", "isolated"):
        lv.ensure_lab_network()
        network = "vm-lab"

    disk_path = LAYOUT.data / "disks" / f"{name}.qcow2"
    lv.qemu_img_create(disk_path, disk)

    from vmtools.layout import config as _cfg
    uri = str(_cfg().get("libvirt_uri", "qemu:///session"))
    if network in ("default",) and "session" in uri:
        net_arg = "user,model=virtio"
    else:
        net_arg = f"network={network},model=virtio"

    args_vi = [
        "--name", name,
        "--memory", str(ram * 1024),
        "--vcpus", str(cpus),
        "--cpu", "host-passthrough",
        "--disk", f"path={disk_path},format=qcow2,bus=virtio",
        "--cdrom", str(iso),
        "--osinfo", "detect=on,require=off",
        "--boot", "uefi",
        "--graphics", "spice,listen=none",
        "--video", "virtio",
        "--sound", "ich9",
        "--channel", "spicevmc,target_type=virtio",
        "--network", net_arg,
        "--noautoconsole",
    ]
    if not launch:
        args_vi.append("--noreboot")

    OUT.step("Creating libvirt domain")
    lv.virt_install(args_vi)

    write_json(
        LAYOUT.data / "metadata" / f"vm-{name}.json",
        {
            "name": name,
            "os": "linux",
            "distro": prov.id,
            "edition": edition,
            "iso": str(iso),
            "media_id": media.id if media else None,
            "disk": str(disk_path),
            "cpus": cpus,
            "ram_gib": ram,
            "network": network,
        },
    )
    OUT.ok(f"VM {name} created")
    if launch:
        lv.open_gui(name)
    return 0
