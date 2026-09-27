import re
from typing import Any

import httpx

from ..logging import get_logger
from ..models import MinerDeviceIdentity, MinerHealth, MinerSnapshot, MinerStats, MinerWorkload

logger = get_logger(__name__)

_UNIT_FACTORS = {
    "h/s": 1.0,
    "kh/s": 1e3,
    "mh/s": 1e6,
    "gh/s": 1e9,
    "th/s": 1e12,
    "ph/s": 1e15,
}

_SRBMINER_HASHRATE_WINDOWS = ("1min", "1hr", "6hr", "12hr")


def _number(value: Any) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    try:
        return float(str(value).strip())
    except (TypeError, ValueError):
        return None


def _integer(value: Any) -> int | None:
    number = _number(value)
    return int(number) if number is not None else None


def _text(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    stripped = value.strip()
    return stripped or None


def _first(data: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        if key in data:
            return data[key]
    return None


def _numeric_mapping(value: Any, *, exclude: set[str] | None = None) -> dict[str, float]:
    if not isinstance(value, dict):
        return {}
    excluded = exclude or set()
    result: dict[str, float] = {}
    for key, raw_value in value.items():
        key_text = str(key)
        if key_text in excluded:
            continue
        number = _number(raw_value)
        if number is not None:
            result[key_text] = number
    return result


def _integer_mapping(value: Any) -> dict[str, int]:
    if not isinstance(value, dict):
        return {}
    result: dict[str, int] = {}
    for key, raw_value in value.items():
        number = _integer(raw_value)
        if number is not None:
            result[str(key)] = number
    return result


def _structured_hashrate(
    data: dict[str, Any],
) -> tuple[dict[str, float], float | None, dict[str, float]]:
    raw_hashrate = data.get("hashrate")
    if not isinstance(raw_hashrate, dict):
        return {}, None, {}

    windows: dict[str, float] = {}
    for window in _SRBMINER_HASHRATE_WINDOWS:
        value = _number(raw_hashrate.get(window))
        if value is not None:
            windows[window] = value

    raw_gpu = raw_hashrate.get("gpu")
    gpu_total_hs: float | None = None
    if isinstance(raw_gpu, dict):
        gpu_total_hs = _number(raw_gpu.get("total"))
    gpu_hashrates_hs = _numeric_mapping(raw_gpu, exclude={"total"})
    return windows, gpu_total_hs, gpu_hashrates_hs


def _hashrate_hs(data: dict[str, Any]) -> float | None:
    windows, _, _ = _structured_hashrate(data)
    if "1min" in windows:
        return windows["1min"]

    explicit_hs_keys = (
        "hashrate_hs",
        "hash_rate_hs",
        "HashRateHs",
        "HashRateHps",
        "hashrateHps",
    )
    for key in explicit_hs_keys:
        value = _number(data.get(key))
        if value is not None:
            return value

    for key in ("hashrate", "HashRate", "hash_rate"):
        raw = data.get(key)
        if isinstance(raw, str):
            match = re.fullmatch(r"\s*([0-9]+(?:\.[0-9]+)?)\s*([kKmMgGtTpP]?[hH]/s)\s*", raw)
            if match:
                return float(match.group(1)) * _UNIT_FACTORS[match.group(2).casefold()]
        value = _number(raw)
        unit = data.get("hashrate_unit") or data.get("HashRateUnit") or data.get("unit")
        if value is not None and isinstance(unit, str):
            factor = _UNIT_FACTORS.get(unit.strip().casefold())
            if factor is not None:
                return value * factor

    unit_key_pairs = (
        ("hashrate_khs", 1e3),
        ("hashrate_mhs", 1e6),
        ("hashrate_ghs", 1e9),
        ("hashrate_ths", 1e12),
        ("hashrate_phs", 1e15),
    )
    for key, factor in unit_key_pairs:
        value = _number(data.get(key))
        if value is not None:
            return value * factor
    return None


def _miner_device_names(
    gpu_hashrates_hs: dict[str, float],
    gpu_compute_errors: dict[str, int],
    gpu_efficiency_raw: dict[str, float],
) -> list[str]:
    names = [
        *gpu_hashrates_hs,
        *gpu_compute_errors,
        *gpu_efficiency_raw,
    ]
    return list(dict.fromkeys(names))


def _parse_workload(data: dict[str, Any], fallback_algorithm: Any = None) -> MinerWorkload | None:
    raw_algorithm = _first(
        data,
        "raw_algorithm_name",
        "algorithm",
        "Algorithm",
        "algo",
        "AlgorithmName",
        "name",
    )
    if raw_algorithm is None:
        raw_algorithm = fallback_algorithm
    if not isinstance(raw_algorithm, str) or not raw_algorithm.strip():
        return None

    shares = _first(data, "shares", "Shares")
    shares = shares if isinstance(shares, dict) else {}
    total = _first(data, "total_shares", "TotalShares", "total", "Total")
    accepted = _first(data, "accepted_shares", "AcceptedShares", "accepted", "Accepted")
    rejected = _first(data, "rejected_shares", "RejectedShares", "rejected", "Rejected")
    invalid = _first(data, "invalid_shares", "InvalidShares", "invalid", "Invalid")
    if total is None:
        total = _first(shares, "total", "Total")
    if accepted is None:
        accepted = _first(shares, "accepted", "Accepted")
    if rejected is None:
        rejected = _first(shares, "rejected", "Rejected")
    if invalid is None:
        invalid = _first(shares, "invalid", "Invalid")

    raw_devices = _first(data, "device_ids", "gpu_ids", "devices", "GPUs")
    device_ids: list[int] = []
    if isinstance(raw_devices, list):
        for item in raw_devices:
            candidate = item.get("index") if isinstance(item, dict) else item
            device_id = _integer(candidate)
            if device_id is not None:
                device_ids.append(device_id)

    hashrate_windows_hs, gpu_hashrate_total_hs, gpu_hashrates_hs = _structured_hashrate(data)
    gpu_compute_errors = _integer_mapping(data.get("gpu_compute_errors"))
    gpu_efficiency_raw = _numeric_mapping(data.get("gpu_efficiency"))

    return MinerWorkload(
        raw_algorithm_name=raw_algorithm,
        hashrate_hs=_hashrate_hs(data),
        hashrate_windows_hs=hashrate_windows_hs,
        gpu_hashrate_total_hs=gpu_hashrate_total_hs,
        gpu_hashrates_hs=gpu_hashrates_hs,
        gpu_compute_errors=gpu_compute_errors,
        gpu_efficiency_raw=gpu_efficiency_raw,
        miner_device_names=_miner_device_names(
            gpu_hashrates_hs,
            gpu_compute_errors,
            gpu_efficiency_raw,
        ),
        total_shares=_integer(total),
        accepted_shares=_integer(accepted),
        rejected_shares=_integer(rejected),
        invalid_shares=_integer(invalid),
        device_ids=device_ids,
        raw_data=data,
    )


def _parse_devices(payload: dict[str, Any]) -> list[MinerDeviceIdentity]:
    raw_devices = payload.get("gpu_devices")
    if not isinstance(raw_devices, list):
        return []

    devices: list[MinerDeviceIdentity] = []
    for item in raw_devices:
        if not isinstance(item, dict):
            continue
        devices.append(
            MinerDeviceIdentity(
                miner_device_id=_integer(item.get("id")),
                device_name=_text(item.get("device")),
                bus_id=_integer(item.get("bus_id")),
                topology_id=_text(item.get("topology_id")),
                vendor=_text(item.get("vendor")),
                model=_text(item.get("model")),
                raw_data=item,
            )
        )
    return devices


def parse_srbminer_payload(payload: dict[str, Any]) -> MinerSnapshot:
    uptime = _number(
        _first(
            payload,
            "uptime_seconds",
            "UptimeSeconds",
            "uptime",
            "Uptime",
            "mining_time",
        )
    )
    miner_version = _text(_first(payload, "miner_version", "MinerVersion", "version"))
    gpu_errors = _integer(_first(payload, "gpu_errors", "GPUErrors", "GpuErrors"))
    fallback_algorithm = _first(payload, "algorithm", "Algorithm", "algo", "AlgorithmName")

    workload_container = _first(payload, "workloads", "Workloads", "algorithms", "Algorithms")
    workloads: list[MinerWorkload] = []

    if isinstance(workload_container, list):
        for item in workload_container:
            if isinstance(item, dict):
                workload = _parse_workload(item)
                if workload is not None:
                    workloads.append(workload)
    elif isinstance(workload_container, dict):
        for name, item in workload_container.items():
            if isinstance(item, dict):
                workload = _parse_workload(item, fallback_algorithm=name)
                if workload is not None:
                    workloads.append(workload)

    if not workloads:
        single = _parse_workload(payload, fallback_algorithm=fallback_algorithm)
        if single is not None:
            workloads.append(single)

    return MinerSnapshot(
        miner="srbminer",
        miner_version=miner_version,
        uptime_seconds=uptime,
        workloads=workloads,
        devices=_parse_devices(payload),
        gpu_errors=gpu_errors,
        raw_data=payload,
    )


class SRBMinerClient:
    """Read-only SRBMiner HTTP client. Only GET requests are exposed."""

    def __init__(
        self,
        host: str = "127.0.0.1",
        port: int = 21550,
        timeout: float = 5.0,
        api_path: str = "/",
        transport: httpx.AsyncBaseTransport | None = None,
    ):
        self.host = host
        self.port = port
        self.timeout = timeout
        self.api_path = "/" + api_path.lstrip("/")
        self.base_url = f"http://{host}:{port}"
        self._transport = transport

    async def _fetch(self) -> dict[str, Any] | None:
        try:
            async with httpx.AsyncClient(
                timeout=self.timeout,
                transport=self._transport,
                trust_env=False,
            ) as client:
                response = await client.get(f"{self.base_url}{self.api_path}")
            if response.status_code != 200:
                logger.warning("miner_api_http_error", status=response.status_code)
                return None
            payload = response.json()
            if not isinstance(payload, dict):
                logger.warning("miner_api_schema_error", reason="top-level JSON is not an object")
                return None
            return payload
        except (httpx.HTTPError, ValueError) as exc:
            logger.warning("miner_api_error", error=str(exc))
            return None

    async def snapshot(self) -> MinerSnapshot | None:
        payload = await self._fetch()
        if payload is None:
            return None
        try:
            return parse_srbminer_payload(payload)
        except (TypeError, ValueError) as exc:
            logger.warning("miner_parse_error", error=str(exc))
            return None

    async def health(self) -> MinerHealth:
        snapshot = await self.snapshot()
        if snapshot is None:
            return MinerHealth(is_alive=False, error_message="SRBMiner API unavailable or invalid")
        return MinerHealth(is_alive=True, uptime_seconds=snapshot.uptime_seconds)

    async def stats(self) -> MinerStats | None:
        snapshot = await self.snapshot()
        if snapshot is None or not snapshot.workloads:
            return None
        workload = snapshot.workloads[0]
        return MinerStats(
            algorithm=workload.raw_algorithm_name,
            local_hashrate_hs=workload.hashrate_hs,
            accepted_shares=workload.accepted_shares,
            rejected_shares=workload.rejected_shares,
            invalid_shares=workload.invalid_shares,
            gpu_errors=snapshot.gpu_errors,
        )

    async def local_hashrate_hs(self) -> float | None:
        stats = await self.stats()
        return stats.local_hashrate_hs if stats else None

    async def accepted_shares(self) -> int | None:
        stats = await self.stats()
        return stats.accepted_shares if stats else None

    async def rejected_shares(self) -> int | None:
        stats = await self.stats()
        return stats.rejected_shares if stats else None
