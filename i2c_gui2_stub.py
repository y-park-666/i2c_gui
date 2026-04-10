"""
Minimal i2c_gui2 stub for local browser testing without hardware.
Inject this before importing helpers:
    import i2c_gui2_stub  # noqa: F401
It replaces sys.modules['i2c_gui2'] with a no-op implementation.
"""
import sys
import types

_mod = types.ModuleType("i2c_gui2")


class USB_ISS_Helper:
    def __init__(self, port, clock, dummy_connect=False):
        self.port = port
        self.clock = clock


class ETROC2_Chip:
    """No-op chip stub — all reads return 1, writes are ignored."""

    def __init__(self, chip_address, ws_address, conn, logger=None):
        self.chip_address = chip_address
        self.ws_address = ws_address
        self.row = 0
        self.col = 0
        self.broadcast = False
        self._store = {}

    def read_all_block(self, *a, **kw):
        pass

    def write_all_block(self, *a, **kw):
        pass

    def read_register(self, *a, **kw):
        pass

    def write_register(self, *a, **kw):
        pass

    def read_decoded_value(self, *a, **kw):
        pass

    def write_decoded_value(self, *a, **kw):
        pass

    def get_decoded_value(self, *a, **kw):
        return 1

    def set_decoded_value(self, *a, **kw):
        pass

    def __getitem__(self, key):
        return self._store.get(str(key), 0)

    def __setitem__(self, key, value):
        self._store[str(key)] = value


_mod.USB_ISS_Helper = USB_ISS_Helper
_mod.ETROC2_Chip = ETROC2_Chip

sys.modules["i2c_gui2"] = _mod
