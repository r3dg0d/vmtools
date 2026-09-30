# Verification

States: `VERIFIED AGAINST PUBLISHER`, `VERIFIED AGAINST USER HASH`, `LOCAL HASH ONLY`, `UNVERIFIED`.

The source URL and every followed redirect must use HTTPS. Redirects to HTTP
are rejected before contacting the target; existing staging files are preserved.
HTTPS redirects (including relative redirects to the same HTTPS origin) work
normally.

Downloads stage as `*.iso.part` until complete. Advertised response lengths and
resume ranges are checked before the file is promoted. Incomplete transfers retain
the staging file for retry and exit with download error code `4`.

A new partial download records the server's strong ETag and hashed requested/final
URLs in a private `*.iso.part.json` sidecar. A retry sends `Range` and `If-Range`
only when this metadata matches the requested source, or when a supplied SHA-256
will verify the assembled file. Matching partial responses must retain the ETag
and final source URL. A changed, missing or weak validator on a resumed response
stops the transfer without appending or changing the saved partial.

A full HTTP 200 response starts fresh and replaces the saved validator. Without
a strong ETag or supplied SHA-256, retries start from zero. This also applies to
legacy partial files without metadata. Weak ETags and Last-Modified dates alone
are not used to prove byte identity. Malformed metadata is treated as unavailable.
Hash-backed legacy resumes do not acquire an ETag from a partial response: the
old prefix must first pass the supplied whole-file hash. Metadata is removed
after successful promotion or checksum failure.

If a server repeatedly sends an inconsistent partial response, keep the partial
for inspection or remove the `.part` file and retry to request the full image.

An HTTP 416 range rejection only promotes the staging file when its supplied SHA-256
matches. Without a matching hash, the download restarts without a Range header.
Servers that ignore Range also restart the staging file rather than appending.

SHA-256 verification happens before replacing an existing destination. Failed
checksums delete only the staging file and exit with code `5`, preserving the
previous destination. Length and ETag checks detect incomplete transfers and
help prevent mixing source versions; they do not establish image authenticity.
Use a trusted publisher or user SHA-256 whenever available.
