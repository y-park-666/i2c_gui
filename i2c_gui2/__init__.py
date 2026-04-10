#############################################################################
# zlib License
#
# (C) 2023 Cristóvão Beirão da Cruz e Silva <cbeiraod@cern.ch>
#
# This software is provided 'as-is', without any express or implied
# warranty.  In no event will the authors be held liable for any damages
# arising from the use of this software.
#
# Permission is granted to anyone to use this software for any purpose,
# including commercial applications, and to alter it and redistribute it
# freely, subject to the following restrictions:
#
# 1. The origin of this software must not be misrepresented; you must not
#    claim that you wrote the original software. If you use this software
#    in a product, an acknowledgment in the product documentation would be
#    appreciated but is not required.
# 2. Altered source versions must be plainly marked as such, and must not be
#    misrepresented as being the original software.
# 3. This notice may not be removed or altered from any source distribution.
#############################################################################

from __future__ import annotations

__version__ = '0.0.2'
__swap_endian__ = True
__no_connect__ = False
__no_connect_type__ = "check"

from .chips.etroc2_chip import ETROC2_Chip

from .functions import validate_8bit_register
from .functions import validate_variable_bit_register
from .functions import validate_i2c_address
from .functions import validate_pixel_index
from .functions import hex_0fill
from .functions import addLoggingLevel

# USB_ISS_Helper only works when the usb_iss package is installed
try:
    from .usb_iss_helper import USB_ISS_Helper
except ImportError:
    USB_ISS_Helper = None  # type: ignore[assignment,misc]

# Add custom log levels to logging
addLoggingLevel('TRACE', 8)
addLoggingLevel('DETAILED_TRACE', 5)

def get_swap_endian():
    return __swap_endian__

def toggle_swap_endian():
    global __swap_endian__
    __swap_endian__ = not __swap_endian__

def set_swap_endian():
    global __swap_endian__
    __swap_endian__ = True

def unset_swap_endian():
    global __swap_endian__
    __swap_endian__ = False

__all__ = [
    "ETROC2_Chip",
    "USB_ISS_Helper",
    "validate_8bit_register",
    "validate_variable_bit_register",
    "validate_i2c_address",
    "validate_pixel_index",
    "hex_0fill",
    "get_swap_endian",
    "toggle_swap_endian",
    "set_swap_endian",
    "unset_swap_endian",
]
