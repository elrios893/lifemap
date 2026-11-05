"""Utilidades geoespaciales sin dependencias externas."""
_BASE32 = "0123456789bcdefghjkmnpqrstuvwxyz"


def geohash(lat: float, lon: float, precision: int = 5) -> str:
    """Codifica (lat, lon) en geohash. Precisión 5 ~ celdas de 4,9 x 4,9 km."""
    lat_rng, lon_rng = [-90.0, 90.0], [-180.0, 180.0]
    out, bits, bit, even = [], 0, 0, True
    while len(out) < precision:
        rng, val = (lon_rng, lon) if even else (lat_rng, lat)
        mid = (rng[0] + rng[1]) / 2
        if val >= mid:
            bits = (bits << 1) | 1
            rng[0] = mid
        else:
            bits <<= 1
            rng[1] = mid
        even = not even
        bit += 1
        if bit == 5:
            out.append(_BASE32[bits])
            bits, bit = 0, 0
    return "".join(out)


def geohash_bbox(gh: str):
    """(lat_min, lat_max, lon_min, lon_max) de una celda; sirve para guardar su polígono en las ventanas (E2)."""
    lat_rng, lon_rng, even = [-90.0, 90.0], [-180.0, 180.0], True
    for ch in gh:
        v = _BASE32.index(ch)
        for i in range(4, -1, -1):
            rng = lon_rng if even else lat_rng
            mid = (rng[0] + rng[1]) / 2
            if (v >> i) & 1:
                rng[0] = mid
            else:
                rng[1] = mid
            even = not even
    return lat_rng[0], lat_rng[1], lon_rng[0], lon_rng[1]
