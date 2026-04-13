# Kick start
```
  cd ~/i2c_gui                                                                                                                                                                                                                              
  source /opt/python-envs/i2c_etroc/bin/activate
  uvicorn helpers.browser_gui:app --host 0.0.0.0 --port 8000     
```


# Helpers README

This folder contains the Raspberry Pi measurement helpers and the browser-based localhost GUI for ETROC2 baseline and noise-width measurements.

## What is here
- `i2c_gui2_helpers.py`: measurement and save/export helper layer
- `i2c_rpi_helper.py`: Raspberry Pi I2C backend using `smbus2`
- `i2c_test_with_rpi.py`: example script for direct Raspberry Pi measurement
- `browser_gui.py`: FastAPI-based local browser GUI
- `browser_requirements.txt`: Python packages needed for the browser GUI

## Main workflows

### 1. Run direct measurement from Python
Use this when you want script-based measurement without the browser UI.

Example:
```bash
cd <repo root>
source .venv/bin/activate   # activate venv if not already active
python helpers/i2c_test_with_rpi.py
```

This uses the Raspberry Pi I2C backend (`use_usb_iss=False`) and saves artifacts through the helper layer.

### 2. Run the browser GUI on localhost
Use this when you want to launch measurement from a browser and see results as plots.

**First-time setup — create a virtual environment** (required on Raspberry Pi OS Bookworm and any system with an externally-managed Python):
```bash
cd <repo root>
python3 -m venv .venv
source .venv/bin/activate
pip install -r helpers/browser_requirements.txt
```

`i2c_gui2` is not on PyPI — you need to install it from wherever it already lives on your Pi:
```bash
# Find it first
find ~ -name "i2c_gui2" -type d 2>/dev/null

# Then install from its parent site-packages directory, e.g.:
pip install --no-deps <path-to-site-packages-containing-i2c_gui2>
# e.g. pip install --no-deps ~/tamalero/lib/python3.8/site-packages/i2c_gui2
```

Or if it is already installed system-wide, recreate the venv with access to system packages:
```bash
python3 -m venv --system-site-packages .venv
```

> The `.venv` folder is gitignored. You only need to create it once.
> On subsequent sessions just run `source .venv/bin/activate` before starting the server.

Start the server (venv must be active):
```bash
uvicorn helpers.browser_gui:app --host 127.0.0.1 --port 8000
```

Open:
```text
http://127.0.0.1:8000
```

If you want other machines on the same network to access it (e.g. view from your laptop while the Pi runs the measurement):
```bash
uvicorn helpers.browser_gui:app --host 0.0.0.0 --port 8000
```

Then open on your laptop:
```text
http://<raspberry-pi-ip>:8000
```

## Python dependencies

### One-step install for the browser GUI (recommended)

Install everything the browser GUI needs in one command:

```bash
pip install -r helpers/browser_requirements.txt
```

This installs:
- `fastapi` — web framework
- `uvicorn` — ASGI server
- `jinja2` — HTML templating
- `python-multipart` — required for FastAPI form parsing (the `/start` endpoint will crash without this)
- `pandas` — measurement DataFrames
- `numpy` — numeric operations
- `tqdm` — progress bars during calibration

### Required for Raspberry Pi I2C backend
```bash
pip install smbus2
```

### Required if you want static PNG plot export
The helper supports saving PNG figures in addition to JSON/CSV/SQLite. These are **not** included in `browser_requirements.txt` because they are large and only needed for archival PNGs.

```bash
pip install matplotlib mplhep hist
```

### Required by the ETROC helper stack
Depending on your environment, you may also need the ETROC/I2C package used by these helpers:
```bash
pip install usb-iss
```

If `i2c_gui2` is not installed from pip because it is a local package in your environment, make sure the Python environment you use on the Pi can import it.

Quick check:
```bash
python -c "import i2c_gui2; print('i2c_gui2 import ok')"
```

## Raspberry Pi system dependencies

Enable I2C on the Pi:
```bash
sudo raspi-config
```
Then:
- `Interface Options`
- `I2C`
- enable it

Install system I2C tools:
```bash
sudo apt update
sudo apt install -y i2c-tools python3-pip
```

Optional check:
```bash
i2cdetect -y 1
```

## If it does not work

### `error: externally-managed-environment` when running pip
Raspberry Pi OS Bookworm (and recent Debian/Ubuntu) blocks system-wide pip installs.
Use a virtual environment instead:
```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r helpers/browser_requirements.txt
```

### `ModuleNotFoundError: fastapi`
Install:
```bash
pip install fastapi uvicorn jinja2 python-multipart
```

### `RuntimeError: Form data requires "python-multipart" to be installed`
FastAPI cannot parse the `/start` form without this package:
```bash
pip install python-multipart
```

### `ModuleNotFoundError: smbus2`
Install:
```bash
python -m pip install smbus2
```

### `ModuleNotFoundError: i2c_gui2`
Your environment cannot find the ETROC helper package used by `helpers/i2c_gui2_helpers.py`.

Try:
```bash
python -c "import i2c_gui2"
```

If that fails, use the Python environment where `i2c_gui2` is already installed, or install/configure that package first.

### `ModuleNotFoundError: matplotlib`, `mplhep`, or `hist`
Install:
```bash
python -m pip install matplotlib mplhep hist
```

### `OSError` or device not found on Raspberry Pi I2C
Check:
- I2C is enabled in `raspi-config`
- wiring and power are correct
- the bus number is correct
- the device appears in:
```bash
i2cdetect -y 1
```

### Browser page opens but measurement fails
Check:
- chip names and chip addresses have the same count
- waveform sampler address count matches chip count, or use `None`
- the selected transport is correct:
  - `USB-ISS` for USB adapter
  - `Raspberry Pi I2C` for direct Pi bus access

## Output locations

The browser GUI saves output under:
```text
helpers/output/browser_batches/
```

Each batch gets its own directory:
- `raw/` for per-chip CSV files
- `figures/` for PNG plots
- `json/` for browser-ready batch summary

The SQLite history file is stored at:
```text
helpers/output/browser_batches/BaselineHistory.sqlite
```

## Typical browser GUI usage
1. Start the server with `uvicorn`.
2. Open `http://127.0.0.1:8000`.
3. Enter a batch name.
4. Enter chip names and chip addresses.
5. Choose `USB-ISS` or `Raspberry Pi I2C`.
6. Start the batch.
7. Wait for the job page to refresh automatically.
8. Review plots and download CSV/JSON/PNG artifacts.
