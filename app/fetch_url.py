"""Fetch a document from a share link.

Share links from the common drives don't point at the file itself — they point
at a viewer page — so they are rewritten to their direct-download form before
fetching. Only http(s) is allowed, the download is size-capped, and the file
type must be one the ingester supports.
"""
from __future__ import annotations

import ipaddress
import re
import socket
import urllib.parse
import urllib.request
from pathlib import Path

MAX_BYTES = 60 * 1024 * 1024          # generous for a scanned contract, bounded
TIMEOUT = 45
_UA = "Mozilla/5.0 (compatible; ContractRAG/1.0)"

_GDRIVE_ID = re.compile(r"/file/d/([A-Za-z0-9_-]{10,})|[?&]id=([A-Za-z0-9_-]{10,})")


def _validate_public_url(url: str) -> str:
    """Mitigate common local/private targets before a server-side download.

    URL ingestion is an SSRF boundary. Every address seen during preflight must
    be globally routable, and redirects pass through the same check. A hardened
    deployment should also enforce outbound network policy because DNS can
    change between validation and connection.
    """
    try:
        parsed = urllib.parse.urlparse(url)
        port = parsed.port
    except ValueError as exc:
        raise ValueError("The link is not a valid URL.") from exc
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        raise ValueError("Only public http and https links are supported.")
    if parsed.username or parsed.password:
        raise ValueError("Links containing embedded credentials are not supported.")
    if port not in (None, 80, 443):
        raise ValueError("Only standard web ports are supported.")

    host = parsed.hostname.rstrip(".")
    try:
        addresses = [ipaddress.ip_address(host)]
    except ValueError:
        try:
            info = socket.getaddrinfo(host, port or 443, type=socket.SOCK_STREAM)
        except socket.gaierror as exc:
            raise ValueError("The link hostname could not be resolved.") from exc
        addresses = []
        for row in info:
            try:
                addresses.append(ipaddress.ip_address(row[4][0]))
            except ValueError:
                continue
    if not addresses or any(not address.is_global for address in addresses):
        raise ValueError("The link must resolve only to public internet addresses.")
    return url


class _PublicRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        _validate_public_url(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def direct_url(url: str) -> str:
    """Rewrite a viewer/share URL to the underlying file where we know how."""
    host = urllib.parse.urlparse(url).netloc.lower()
    if "drive.google.com" in host or "docs.google.com" in host:
        m = _GDRIVE_ID.search(url)
        if m:
            fid = m.group(1) or m.group(2)
            return f"https://drive.google.com/uc?export=download&id={fid}"
    if "dropbox.com" in host:
        u = re.sub(r"[?&]dl=0", "", url)
        sep = "&" if "?" in u else "?"
        return f"{u}{sep}dl=1"
    if "1drv.ms" in host or "onedrive.live.com" in host:
        sep = "&" if "?" in url else "?"
        return f"{url}{sep}download=1"
    # GitHub blob pages have a raw equivalent
    if host == "github.com" and "/blob/" in url:
        return url.replace("github.com", "raw.githubusercontent.com").replace("/blob/", "/", 1)
    return url


def _filename_from(resp, url: str) -> str:
    disp = resp.headers.get("Content-Disposition", "")
    m = re.search(r"filename\*?=(?:UTF-8'')?\"?([^\";]+)", disp)
    if m:
        return Path(urllib.parse.unquote(m.group(1))).name
    return Path(urllib.parse.unquote(urllib.parse.urlparse(url).path)).name


def fetch(url: str, allowed_suffixes: set[str]) -> tuple[bytes, str]:
    """Return (bytes, filename). Raises ValueError with a user-facing message."""
    url = url.strip()
    if not urllib.parse.urlparse(url).scheme:
        url = "https://" + url
    _validate_public_url(url)

    download_url = direct_url(url)
    _validate_public_url(download_url)
    req = urllib.request.Request(download_url, headers={"User-Agent": _UA})
    opener = urllib.request.build_opener(_PublicRedirectHandler())
    try:
        with opener.open(req, timeout=TIMEOUT) as resp:
            _validate_public_url(resp.geturl() or download_url)
            declared = resp.headers.get("Content-Length")
            if declared and int(declared) > MAX_BYTES:
                raise ValueError(f"File is larger than {MAX_BYTES // 1024 // 1024} MB.")
            data = resp.read(MAX_BYTES + 1)
            name = _filename_from(resp, resp.geturl() or url)
            ctype = (resp.headers.get("Content-Type") or "").lower()
    except ValueError:
        raise
    except Exception as e:
        raise ValueError(f"Could not download the link ({e}).") from e

    if len(data) > MAX_BYTES:
        raise ValueError(f"File is larger than {MAX_BYTES // 1024 // 1024} MB.")
    if not data:
        raise ValueError("The link returned an empty file.")

    suffix = Path(name).suffix.lower()
    if suffix not in allowed_suffixes:
        # Fall back to the content type when the URL carries no useful filename.
        by_type = {"application/pdf": ".pdf", "text/plain": ".txt",
                   "application/vnd.openxmlformats-officedocument.wordprocessingml.document": ".docx"}
        guess = next((v for k, v in by_type.items() if k in ctype), None)
        if guess is None:
            if "text/html" in ctype:
                raise ValueError(
                    "That link returned a web page, not a file. Use a direct "
                    "download link, or make sure the file is shared publicly."
                )
            raise ValueError(f"Unsupported file type {suffix or ctype or 'unknown'!r}.")
        name, suffix = (Path(name).stem or "document") + guess, guess

    return data, Path(name).name
