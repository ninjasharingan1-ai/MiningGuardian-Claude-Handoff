def format_hashrate(hashrate_hs: float | None) -> str:
    if hashrate_hs is None:
        return "unavailable"
    units = (
        (1e15, "PH/s"),
        (1e12, "TH/s"),
        (1e9, "GH/s"),
        (1e6, "MH/s"),
        (1e3, "kH/s"),
        (1.0, "H/s"),
    )
    absolute = abs(hashrate_hs)
    for factor, suffix in units:
        if absolute >= factor:
            return f"{hashrate_hs / factor:.2f} {suffix}"
    return f"{hashrate_hs:.2f} H/s"
