import hashlib
from pathlib import Path

import requests
from requests.adapters import HTTPAdapter
from tqdm import tqdm
from urllib3.util.retry import Retry

_USER_AGENT = "mc-helper/0.1.0 (github.com/novasharper/minecraft-server-helper)"

_RETRY = Retry(
    total=5,
    backoff_factor=1.0,
    status_forcelist=[429, 500, 502, 503, 504],
    allowed_methods=["GET", "HEAD"],
)


def build_session(extra_headers: dict[str, str] | None = None) -> requests.Session:
    """Return a requests.Session with retry logic and a standard User-Agent."""
    session = requests.Session()
    session.headers["User-Agent"] = _USER_AGENT
    if extra_headers:
        session.headers.update(extra_headers)
    adapter = HTTPAdapter(max_retries=_RETRY)
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    return session


def download_file(
    url: str,
    dest: Path,
    session: requests.Session | None = None,
    expected_sha1: str | None = None,
    expected_sha256: str | None = None,
    expected_sha512: str | None = None,
    show_progress: bool = True,
) -> Path:
    """Download *url* to *dest*, showing a tqdm progress bar.

    Optionally verify SHA-1, SHA-256, or SHA-512 after download.
    Returns *dest*.
    """
    if session is None:
        session = build_session()

    dest.parent.mkdir(parents=True, exist_ok=True)

    with session.get(url, stream=True, timeout=60) as resp:
        resp.raise_for_status()
        total = int(resp.headers.get("Content-Length", 0)) or None
        sha1 = hashlib.sha1() if expected_sha1 else None
        sha256 = hashlib.sha256() if expected_sha256 else None
        sha512 = hashlib.sha512() if expected_sha512 else None

        with (
            open(dest, "wb") as fh,
            tqdm(
                total=total,
                unit="B",
                unit_scale=True,
                unit_divisor=1024,
                desc=dest.name,
                disable=not show_progress,
            ) as bar,
        ):
            for chunk in resp.iter_content(chunk_size=65536):
                fh.write(chunk)
                bar.update(len(chunk))
                if sha1:
                    sha1.update(chunk)
                if sha256:
                    sha256.update(chunk)
                if sha512:
                    sha512.update(chunk)

    if expected_sha1 and sha1:
        actual = sha1.hexdigest()
        if actual != expected_sha1.lower():
            dest.unlink(missing_ok=True)
            raise ValueError(
                f"SHA-1 mismatch for {dest.name}: expected {expected_sha1}, got {actual}"
            )

    if expected_sha256 and sha256:
        actual = sha256.hexdigest()
        if actual != expected_sha256.lower():
            dest.unlink(missing_ok=True)
            raise ValueError(
                f"SHA-256 mismatch for {dest.name}: expected {expected_sha256}, got {actual}"
            )

    if expected_sha512 and sha512:
        actual = sha512.hexdigest()
        if actual != expected_sha512.lower():
            dest.unlink(missing_ok=True)
            raise ValueError(
                f"SHA-512 mismatch for {dest.name}: expected {expected_sha512}, got {actual}"
            )

    return dest
