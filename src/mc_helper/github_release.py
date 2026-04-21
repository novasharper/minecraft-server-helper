"""GitHub release asset resolution."""

import fnmatch

import requests

_GITHUB_API = "https://api.github.com"


def resolve_github_url(
    session: requests.Session,
    repo: str,
    tag: str,
    asset_glob: str | None,
) -> str:
    """Return the browser_download_url for the matching release asset."""
    if tag.upper() == "LATEST":
        url = f"{_GITHUB_API}/repos/{repo}/releases/latest"
    else:
        url = f"{_GITHUB_API}/repos/{repo}/releases/tags/{tag}"

    resp = session.get(url, timeout=30)
    resp.raise_for_status()
    release = resp.json()

    assets: list[dict] = release.get("assets", [])
    if not assets:
        raise ValueError(f"No assets found in GitHub release {repo}@{tag}")

    if asset_glob:
        matched = [a for a in assets if fnmatch.fnmatch(a["name"], asset_glob)]
        if not matched:
            names = [a["name"] for a in assets]
            raise ValueError(
                f"No asset matching '{asset_glob}' in {repo}@{tag}. Available: {names}"
            )
        return matched[0]["browser_download_url"]

    return assets[0]["browser_download_url"]
