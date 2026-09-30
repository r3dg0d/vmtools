# Verification

States: `VERIFIED AGAINST PUBLISHER`, `VERIFIED AGAINST USER HASH`, `LOCAL HASH ONLY`, `UNVERIFIED`.

The source URL and every followed redirect must use HTTPS. Redirects to HTTP
are rejected before contacting the target; existing staging files are preserved.
HTTPS redirects (including relative redirects to the same HTTPS origin) work
normally.

Downloads stage as `*.iso.part` until complete. Advertised response lengths and
resume ranges are checked before the file is promoted. Incomplete transfers retain
the staging file for retry and exit with download error code `4`.

An HTTP 416 range rejection only promotes the staging file when its supplied SHA-256
matches. Without a matching hash, the download restarts without a Range header.
Servers that ignore Range also restart the staging file rather than appending.

SHA-256 verification happens before replacing an existing destination. Failed
checksums delete only the staging file and exit with code `5`, preserving the
previous destination. Without a publisher or user hash, length checks detect
truncation but do not establish image authenticity or protect against content
changing between resumptions; use a trusted SHA-256 whenever available.
