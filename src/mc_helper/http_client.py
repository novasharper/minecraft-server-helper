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

_HASHERS = {
    "sha1": hashlib.sha1,
    "sha256": hashlib.sha256,
    "sha512": hashlib.sha512,
}


def get_json(session: requests.Session, url: str) -> object:
    """GET *url* and return the parsed JSON body. Raises on non-2xx."""
    resp = session.get(url, timeout=30)
    resp.raise_for_status()
    return resp.json()


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
    checksums: dict[str, str] = {}
    if expected_sha1:
        checksums["sha1"] = expected_sha1
    if expected_sha256:
        checksums["sha256"] = expected_sha256
    if expected_sha512:
        checksums["sha512"] = expected_sha512

    if session is None:
        session = build_session()

    dest.parent.mkdir(parents=True, exist_ok=True)

    hashers = {alg: _HASHERS[alg]() for alg in checksums}

    with session.get(url, stream=True, timeout=60) as resp:
        resp.raise_for_status()
        total = int(resp.headers.get("Content-Length", 0)) or None
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
                for h in hashers.values():
                    h.update(chunk)

    _alg_label = {"sha1": "SHA-1", "sha256": "SHA-256", "sha512": "SHA-512"}
    for alg, expected in checksums.items():
        actual = hashers[alg].hexdigest()
        if actual != expected.lower():
            dest.unlink(missing_ok=True)
            label = _alg_label.get(alg, alg.upper())
            raise ValueError(f"{label} mismatch for {dest.name}: expected {expected}, got {actual}")

    return dest


def download_with_mirrors(
    primary_url: str,
    mirrors: list[str],
    dest: Path,
    session: requests.Session,
    expected_sha1: str | None = None,
) -> None:
    """Try *primary_url* then each mirror in order. Raises RuntimeError if all fail."""
    urls = [primary_url, *mirrors]
    last_exc: Exception | None = None
    for url in urls:
        try:
            download_file(
                url, dest, session=session, expected_sha1=expected_sha1, show_progress=False
            )
            return
        except Exception as exc:
            last_exc = exc
            dest.unlink(missing_ok=True)
    raise RuntimeError(f"All download URLs failed for {dest.name}") from last_exc
