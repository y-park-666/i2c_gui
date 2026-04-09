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
cd /home/pyoun/mtd-projects/hybrids_test/i2c_gui_i2c_gui_2
python helpers/i2c_test_with_rpi.py
```

This uses the Raspberry Pi I2C backend (`use_usb_iss=False`) and saves artifacts through the helper layer.

### 2. Run the browser GUI on localhost
Use this when you want to launch measurement from a browser and see results as plots.

Install browser dependencies:
```bash
cd /home/pyoun/mtd-projects/hybrids_test/i2c_gui_i2c_gui_2
python -m pip install -r helpers/browser_requirements.txt
```

Start the server:
```bash
uvicorn helpers.browser_gui:app --host 127.0.0.1 --port 8000
```

Open:
```text
http://127.0.0.1:8000
```

If you want other machines on the same network to access it, run:
```bash
uvicorn helpers.browser_gui:app --host 0.0.0.0 --port 8000
```

Then open:
```text
http://<raspberry-pi-ip>:8000
```

## Python dependencies

### Required for Raspberry Pi I2C measurement
Install:
```bash
python -m pip install smbus2 pandas numpy tqdm
```

### Required for browser GUI
Install:
```bash
python -m pip install fastapi uvicorn jinja2
```

### Required if you want static PNG plot export
The helper still supports saving PNG figures in addition to JSON/CSV/SQLite.

Install:
```bash
python -m pip install matplotlib mplhep hist
```

### Required by the ETROC helper stack
Depending on your environment, you may also need the ETROC/I2C package used by these helpers:
```bash
python -m pip install usb-iss
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

### `ModuleNotFoundError: fastapi`
Install:
```bash
python -m pip install fastapi uvicorn jinja2
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
