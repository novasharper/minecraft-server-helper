def compare_versions(a: str, b: str) -> int:
    """Compare two dot-separated version strings.

    Returns -1 if a < b, 0 if a == b, 1 if a > b.
    Non-numeric segments are compared lexicographically.
    """

    def _parts(v: str) -> list[int | str]:
        parts: list[int | str] = []
        for seg in v.split("."):
            try:
                parts.append(int(seg))
            except ValueError:
                parts.append(seg)
        return parts

    pa, pb = _parts(a), _parts(b)
    max_len = max(len(pa), len(pb))
    pa += [0] * (max_len - len(pa))
    pb += [0] * (max_len - len(pb))

    for x, y in zip(pa, pb):
        if type(x) is not type(y):
            x, y = str(x), str(y)
        if x < y:
            return -1
        if x > y:
            return 1
    return 0
