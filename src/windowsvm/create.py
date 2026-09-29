"""Windows VM creation via virt-install."""

from __future__ import annotations

from pathlib import Path

from vmtools import libvirt as lv
from vmtools.config import validate_name
from vmtools.layout import LAYOUT, config, ensure
from vmtools.menu import confirm, prompt
from vmtools.ui import EXIT_USAGE, Fail, OUT

from .catalog import VIRTIO_WIN, catalog


def interactive_create(args) -> int:
    ensure()
    cfg = config()
    OUT.say()
    OUT.say("Create Windows VM")
    OUT.say("─" * 28)

    name = validate_name(getattr(args, "name", None) or prompt("VM Name", "win11-dev"))
    if lv.domain_exists(name):
        raise Fail(f"VM already exists: {name}", EXIT_USAGE)

    medias = catalog()
    OUT.say("Choose Windows Media")
    for i, m in enumerate(medias, 1):
        tag = " (90-DAY EVALUATION)" if m.evaluation else ""
        OUT.say(f"  {i}. {m.title}{tag}")
    OUT.say(f"  {len(medias)+1}. Existing ISO")
    OUT.say(f"  {len(medias)+2}. Custom ISO URL (checksum required for publisher verify)")
    choice = prompt("Selection", "1")
    iso: Path | None = None
    media_id = "custom"
    expected_hash = None

    try:
        idx = int(choice)
    except ValueError:
        idx = len(medias) + 1

    if 1 <= idx <= len(medias):
        media = medias[idx - 1]
        media_id = media.id
        OUT.note(media.notes)
        OUT.note(f"Source page: {media.source_page}")
        if getattr(args, "iso", None):
            iso = Path(args.iso).expanduser().resolve()
        else:
            existing = prompt("Path to ISO (leave empty to abort download automation)", "")
            if not existing:
                OUT.warn(
                    "Automated Microsoft CDN resolution is not hardcoded. "
                    "Download from the official page, then re-run with --iso."
                )
                OUT.say(media.source_page)
                if confirm("Open source page with xdg-open?", default=True):
                    import subprocess
                    subprocess.Popen(["xdg-open", media.source_page], start_new_session=True)
                raise Fail("no ISO provided", EXIT_USAGE, "download the ISO officially, then: windowsvm create --iso PATH")
            iso = Path(existing).expanduser().resolve()
    elif idx == len(medias) + 1:
        path = getattr(args, "iso", None) or prompt("ISO path")
        iso = Path(path).expanduser().resolve()
        media_id = "existing-iso"
    else:
        url = prompt("HTTPS ISO URL")
        from vmtools.download import download
        dest = LAYOUT.data / "isos/windows" / Path(url).name
        sha = prompt("Expected SHA-256 (required for verify, empty = LOCAL HASH ONLY)")
        iso = download(url, dest, expected_sha256=sha or None, label="Custom Windows ISO")
        media_id = "custom-url"
        expected_hash = sha or None

    if not iso or not iso.is_file():
        raise Fail(f"ISO not found: {iso}", EXIT_USAGE)
    if iso.suffix.lower() != ".iso":
        OUT.warn("file does not end in .iso — continuing anyway")

    from vmtools.checksum import sha256_file, verification_label
    OUT.step("Computing local SHA-256")
    actual = sha256_file(iso)
    OUT.say(f"  SHA-256: {actual}")
    OUT.say(f"  Status:  {verification_label(local_only=True)}")

    cpus = int(getattr(args, "cpus", None) or prompt("CPU cores", str(cfg.get("windows_default_cpus"))))
    ram = int(getattr(args, "ram", None) or prompt("RAM GiB", str(cfg.get("windows_default_ram_gib"))))
    disk = int(getattr(args, "disk", None) or prompt("Disk GiB", str(cfg.get("windows_default_disk_gib"))))
    network = prompt("Network (default|vm-lab|bridge:<name>)", "default")
    attach_virtio = confirm("Attach Fedora virtio-win driver ISO?", default=True)
    tpm = confirm("Enable TPM 2.0 (swtpm)?", default=True)
    launch = confirm("Start installer when done?", default=True)

    if not confirm(f"Create VM {name} with {cpus} vCPU / {ram} GiB / {disk} GiB?", default=True):
        OUT.warn("cancelled")
        return 0

    disk_path = LAYOUT.data / "disks" / f"{name}.qcow2"
    lv.qemu_img_create(disk_path, disk)

    virtio_path = None
    if attach_virtio:
        virtio_path = _ensure_virtio()

    if network == "vm-lab":
        lv.ensure_lab_network()

    args_vi: list[str] = [
        "--name", name,
        "--memory", str(ram * 1024),
        "--vcpus", str(cpus),
        "--cpu", "host-passthrough",
        "--disk", f"path={disk_path},format=qcow2,bus=virtio",
        "--cdrom", str(iso),
        "--osinfo", "detect=on,require=off",
        "--boot", "uefi,firmware.feature0.name=secure-boot,firmware.feature0.enabled=no",
        "--graphics", "spice,listen=none",
        "--video", "virtio",
        "--sound", "ich9",
        "--channel", "spicevmc,target_type=virtio",
        "--controller", "type=usb,model=qemu-xhci",
        "--network", _network_arg(network),
        "--noautoconsole",
    ]
    if not launch:
        args_vi.append("--noreboot")
    if tpm:
        args_vi.extend(["--tpm", "backend.type=emulator,backend.version=2.0,model=tpm-crb"])
    if virtio_path:
        args_vi.extend(["--disk", f"path={virtio_path},device=cdrom,bus=sata"])

    OUT.step("Creating libvirt domain via virt-install")
    try:
        lv.virt_install(args_vi)
    except Fail:
        # fallback simpler boot uefi
        OUT.warn("retrying with simpler --boot uefi")
        args_vi = [a for a in args_vi if not str(a).startswith("uefi") and a != "--boot"]
        # re-insert boot
        idx_b = args_vi.index("--osinfo") if "--osinfo" in args_vi else 0
        args_vi[idx_b:idx_b] = ["--boot", "uefi"]
        # clean previous failed define if any
        if lv.domain_exists(name):
            lv.undefine(name, remove_storage=False, keep_disk=True)
        lv.virt_install(args_vi)

    # tag metadata
    from vmtools.config import write_json
    meta = {
        "name": name,
        "os": "windows",
        "media_id": media_id,
        "iso": str(iso),
        "sha256": actual,
        "disk": str(disk_path),
        "cpus": cpus,
        "ram_gib": ram,
        "tpm": tpm,
        "network": network,
    }
    write_json(LAYOUT.data / "metadata" / f"vm-{name}.json", meta)
    OUT.ok(f"VM {name} created")
    if launch:
        lv.open_gui(name)
    return 0


def _network_arg(network: str) -> str:
    from vmtools.layout import config as _cfg
    uri = str(_cfg().get("libvirt_uri", "qemu:///session"))
    if network in ("default",) and "session" in uri:
        return "user,model=virtio"
    if network == "default":
        return "network=default,model=virtio"
    if network in ("vm-lab", "isolated"):
        if "session" in uri:
            # session has no shared lab net by default; fall back to user
            return "user,model=virtio"
        return "network=vm-lab,model=virtio"
    if network.startswith("bridge:"):
        return f"bridge={network.split(':', 1)[1]},model=virtio"
    return f"network={network},model=virtio"


def _ensure_virtio() -> Path:
    from vmtools.download import download
    ensure()
    dest = LAYOUT.data / "isos/windows/drivers" / "virtio-win.iso"
    if dest.is_file():
        OUT.ok(f"using cached virtio-win: {dest}")
        return dest
    OUT.note(VIRTIO_WIN.source_page)
    return download(VIRTIO_WIN.download_url, dest, label="virtio-win")
