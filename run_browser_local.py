"""
Local dev launcher for the browser GUI.
Replaces i2c_gui2 and i2c_rpi_helper with stubs so the server starts
without hardware or a display attached.
"""
import sys
import types

# --- stub i2c_gui2 (old tkinter package in repo shadows the real one) ---
import i2c_gui2_stub  # noqa: F401  applies sys.modules patch as a side effect

# --- stub i2c_rpi_helper (smbus2 / Pi hardware not available here) ---
_rpi = types.ModuleType("i2c_rpi_helper")


class _RPI_I2C_Helper:
    pass


_rpi.RPI_I2C_Helper = _RPI_I2C_Helper
sys.modules["i2c_rpi_helper"] = _rpi

# --- start uvicorn ---
import uvicorn

if __name__ == "__main__":
    uvicorn.run(
        "helpers.browser_gui:app",
        host="127.0.0.1",
        port=8000,
        reload=False,
    )
