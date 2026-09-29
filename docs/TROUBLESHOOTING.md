# Troubleshooting

**Permission denied on ~/.local/share/vmtools disks with system URI**  
Use `qemu:///session` (default) or a libvirt pool under `/var/lib/libvirt/images`.

**SSL errors in uv venv**  
Wrappers use system Python. Set `SSL_CERT_FILE=/etc/ssl/certs/ca-certificates.crt` if needed.

**androidvm setup access failure**  
Confirm token is a Docker Hub PAT with read access; rotate if leaked in chat.
