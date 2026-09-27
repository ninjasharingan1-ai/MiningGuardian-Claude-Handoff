# Mining Guardian - M0/M1 Implementation

A long-session adaptive cryptocurrency mining optimization agent for Windows.

## Overview

Mining Guardian monitors, protects, and gradually optimizes long-running mining sessions. This is **not** an aggressive profitability switcher — session stability is a first-class optimization objective.

**Current Status:** M0 (Skeleton) + M1 (Observe) complete
- Read-only telemetry collection only
- No GPU modifications
- No miner process control
- Safe failure mode if adapters unavailable

## Quick Start

### 1. Environment Setup

Make sure you have Python 3.12+ and the virtual environment is activated:

```powershell
cd c:\MiningGuardian
.venv\Scripts\Activate.ps1
```

Verify the environment:

```powershell
python --version  # Should show Python 3.12+
pip list | Select-String pydantic,httpx,sqlalchemy,nvidia-ml
```

### 2. Install Mining Guardian in Development Mode

```powershell
cd c:\MiningGuardian
pip install -e .
```

This makes the `mining-guardian` command available and links to the source code.

### 3. Configuration

Copy the example environment file:

```powershell
copy .env.example .env
```

The default configuration connects to:
- SRBMiner API: `http://127.0.0.1:21550`
- GPU Index: 0
- Observation interval: 10 seconds
- Database: `./mining_guardian.db`

Edit `.env` if your setup differs.

## CLI Commands

### probe-gpu

Read GPU information and probe NVIDIA driver capabilities.

```powershell
python -m mining_guardian.cli.commands probe-gpu
```

Output:
- GPU name and index
- Supported capabilities (temperature, clocks, power, utilization, throttle reasons)
- Current GPU telemetry

### probe-miner

Check SRBMiner API connectivity and read current mining stats.

```powershell
python -m mining_guardian.cli.commands probe-miner
```

Output:
- Miner reachability status
- Current algorithm and hashrate
- Share statistics
- Miner uptime

### observe

Start continuous read-only telemetry collection.

```powershell
python -m mining_guardian.cli.commands observe
```

or with a time limit (in seconds):

```powershell
python -m mining_guardian.cli.commands observe --duration 300
```

Features:
- Collects GPU telemetry every `OBSERVE_INTERVAL_SECONDS`
- Collects miner statistics from local API
- Persists data to SQLite
- Safe to interrupt with Ctrl+C
- **OBSERVE MODE IS READ-ONLY** — no GPU clocks changed, no miner restarted

### status

Display current session and latest telemetry from the database.

```powershell
python -m mining_guardian.cli.commands status
```

Output:
- Latest session ID, algorithm, and duration
- Most recent hardware telemetry (temperature, power, clocks)
- Most recent miner telemetry (hashrate, accepted/rejected shares)
- Recent events

## Architecture

```
CLI (Commands)
     ↓
Collectors (Hardware, Miner)
     ↓
Adapters (NVML, SRBMiner API)
     ↓
SQLite Database
```

### Modules

- **adapters/**: Read-only API clients
  - `srbminer.py`: Local JSON API client for SRBMiner
  - `nvml.py`: NVIDIA GPU telemetry via nvidia-ml-py
  
- **collectors/**: Telemetry aggregators
  - `hardware.py`: GPU temperature, clocks, power, utilization
  - `miner.py`: Hashrate, shares, errors from SRBMiner
  
- **storage/**: SQLite persistence
  - `schema.py`: Table definitions
  - `database.py`: Connection management
  - `repository.py`: Data access layer

- **core/**: Session management
  - `session_guardian.py`: Session lifecycle

- **cli/**: Command-line interface
  - `commands.py`: All CLI commands (probe-gpu, probe-miner, observe, status)
  - `main.py`: Entry point

- **models/**: Data models (Pydantic)
  - Session records, hardware/miner samples, events, profiles

- **enums/**: Type-safe enumerations
  - Session states, health states, event types, capability states

### Configuration

Configuration loads from environment variables (`.env` file or shell environment).

Key variables:

```
SRBMINER_API_HOST=127.0.0.1
SRBMINER_API_PORT=21550
GPU_INDEX=0
OBSERVE_INTERVAL_SECONDS=10
DATABASE_PATH=./mining_guardian.db
LOG_LEVEL=info
```

## Database

SQLite database at `./mining_guardian.db` contains:

- **sessions**: Session metadata and lifecycle
- **hardware_samples**: GPU telemetry (temperature, clocks, power, utilization)
- **miner_samples**: Mining stats (hashrate, shares)
- **pool_samples**: Pool data (future M2)
- **events**: Structured events
- **profiles**: Hardware profiles (future M3+)
- **experiments**: Optimization experiments (future M4+)

All hashrates are stored internally in **H/s** (not MH/s or GH/s).

## Running Tests

Run the full test suite:

```powershell
pytest
```

Run tests with verbose output:

```powershell
pytest -v
```

Run specific test file:

```powershell
pytest tests/unit/test_models.py -v
```

Run tests with coverage:

```powershell
pytest --cov=src/mining_guardian tests/
```

Test suites:

- **tests/unit/**: Model and adapter tests (no real hardware required)
- **tests/integration/**: Database persistence and component integration
- **tests/fixtures/**: Fake adapters for testing without real GPU/miner

## Safety Guarantees (M0/M1)

✓ **NO GPU clock modifications**
✓ **NO miner restart or stop**
✓ **NO algorithm switching**
✓ **NO wallet changes**
✓ **NO shell execution**
✓ **Read-only mode only**

Failure modes:
- If NVML unavailable → logs warning, continues
- If SRBMiner API unavailable → logs warning, continues
- If database unavailable → logs error, exits safely

## Hashrate Units

All internal hashrate values use **H/s** (hashes per second).

Example:
- Internal: `27_400_000` = 27.4 MH/s = 27,400,000 H/s
- Database stores: `27400000.0` (in H/s)
- Display/CLI formats as: `27.4 MH/s`

This prevents unit-comparison errors between algorithms.

## Example Workflow

### 1. Probe your GPU

```powershell
python -m mining_guardian.cli.commands probe-gpu
```

Verify:
- NVIDIA driver is installed
- NVML can read temperature, clocks, power, utilization

### 2. Probe SRBMiner

Start SRBMiner first with API enabled:

```powershell
# In another terminal, with SRBMiner installed
SRBMiner-MULTI.exe --api-enable --api-rig-name GuardianRig
```

Then probe:

```powershell
python -m mining_guardian.cli.commands probe-miner
```

Verify:
- Mining Guardian can connect
- Miner stats are readable
- Hashrate and shares are reported

### 3. Collect Observation Data

```powershell
python -m mining_guardian.cli.commands observe --duration 3600
```

This collects 1 hour of baseline data (GPU + miner telemetry) into the database.

### 4. Check Status

```powershell
python -m mining_guardian.cli.commands status
```

View:
- Session summary
- Latest telemetry
- Recent events

## Logging

Structured logging to console in JSON format. Set `LOG_LEVEL` environment variable:

```powershell
$env:LOG_LEVEL='debug'
python -m mining_guardian.cli.commands observe
```

Log levels: debug, info, warning, error, critical

## Future Milestones

- **M2**: unMineable pool integration (profitability shadow mode)
- **M3**: Health engine and state machine
- **M4**: Optimizer shadow mode (simulate optimization decisions)
- **M5**: Bounded live tuning (one parameter at a time, small steps)
- **M6**: AI advisor (read-only analysis and recommendations)
- **M7**: Agent-assisted experiments
- **M8**: Next-session intelligence

## Troubleshooting

### SRBMiner API not reachable

```
ERROR: Miner unreachable
```

1. Verify SRBMiner is running
2. Verify SRBMiner started with `--api-enable`
3. Check `SRBMINER_API_HOST` and `SRBMINER_API_PORT` in `.env`
4. Verify firewall allows localhost:21550

### NVML not initialized

```
WARNING: NVML not initialized. Check NVIDIA driver installation.
```

1. Verify NVIDIA driver is installed
2. Try: `nvidia-smi` from PowerShell
3. If that fails, install latest NVIDIA drivers for your GPU model

### Database errors

```
ERROR: database readonly
```

1. Check file permissions on `./mining_guardian.db`
2. Ensure database path is writable
3. Try deleting stale database: `rm mining_guardian.db`

## Development Notes

### Code Structure

- Type hints throughout (PEP 484)
- Pydantic models for validation
- Dependency injection for testability
- Structured logging for observability
- Read-only philosophy in M1

### Testing

- Unit tests for models and adapters
- Integration tests for database and collectors
- Fake adapters for testing without real hardware
- Async tests with pytest-asyncio

### Adding New Commands

See `mining_guardian/cli/commands.py` for examples.

1. Create a `@cli.command()` decorated function
2. Use Click decorators for arguments/options
3. Instantiate adapters and repositories
4. Make it read-only (M1 only)

## License

MIT

## Contact

This is an early-stage implementation. For issues or questions, see the project documentation.
