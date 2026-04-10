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

from .i2c_connection_helper import I2C_Connection_Helper
from .i2c_messages import I2CMessages

import logging

from usb_iss import UsbIss, defs

class USB_ISS_Helper(I2C_Connection_Helper):
    def __init__(self, port: str, clock: int = 100, dummy_connect: bool = False,
                 max_seq_byte: int = 8, swap_endian: bool = True,
                 successive_i2c_delay_us: int = 10000):
        super().__init__(
            max_seq_byte=max_seq_byte,
            swap_endian=swap_endian,
            successive_i2c_delay_us=successive_i2c_delay_us,
            no_connect=dummy_connect,
        )

        self._port = port
        self._clock = clock

        self._iss = UsbIss()

        if not dummy_connect:
            use_hardware = clock >= 100
            try:
                self._iss.open(port)
                self._iss.setup_i2c(clock_khz=clock, use_i2c_hardware=use_hardware)
                self._is_connected = True
            except Exception as e:
                self._logger.error("Unable to connect to I2C bus on port %s at %d kHz: %s", port, clock, e)
                self._is_connected = False
        else:
            self._is_connected = True  # dummy mode counts as "connected"

    @property
    def port(self):
        return self._port

    @property
    def clk(self):
        return self._clock

    def _check_i2c_device(self, address: int):
        return self._iss.i2c.test(address)

    def _write_i2c_device_memory(self, address: int, memory_address: int, data: list, register_bits: int = 16, write_type: str = 'Normal'):
        if write_type == 'Normal':
            if register_bits == 16:
                self._iss.i2c.write_ad2(address, memory_address, data)
            elif register_bits == 8:
                self._iss.i2c.write_ad1(address, memory_address, data)
            else:
                self._logger.error("Unknown register bit size: %d", register_bits)
        else:
            raise RuntimeError("Unknown write type chosen for the USB ISS: {}".format(write_type))

    def _read_i2c_device_memory(self, address: int, memory_address: int, byte_count: int, register_bits: int = 16, read_type: str = 'Normal') -> list:
        if read_type == 'Normal':
            if register_bits == 16:
                return self._iss.i2c.read_ad2(address, memory_address, byte_count)
            if register_bits == 8:
                return self._iss.i2c.read_ad1(address, memory_address, byte_count)
            else:
                self._logger.error("Unknown register bit size: %d", register_bits)
                return []
        elif read_type == "Repeated Start":
            direct_msg = [defs.I2CDirect.START]

            device_address_byte = address << 1
            if register_bits == 8:
                direct_msg += [
                    defs.I2CDirect.WRITE2,
                    device_address_byte,
                    memory_address & 0xff,
                ]
            elif register_bits == 16:
                direct_msg += [
                    defs.I2CDirect.WRITE3,
                    device_address_byte,
                    (memory_address >> 8) & 0xff,
                    memory_address & 0xff,
                ]
            else:
                self._logger.error("Unknown register bit size: %d", register_bits)
                return []

            direct_msg += [
                defs.I2CDirect.RESTART,
                defs.I2CDirect.WRITE1,
                device_address_byte | 0x01,
            ]

            if byte_count <= 16:
                if byte_count > 1:
                    direct_msg += [
                        getattr(defs.I2CDirect, f"READ{byte_count-1}"),
                    ]
            else:
                raise RuntimeError("USB ISS does not support a block read of more than 16 bytes")

            direct_msg += [
                defs.I2CDirect.NACK,
                defs.I2CDirect.READ1,
                defs.I2CDirect.STOP,
            ]

            retVal = self._iss.i2c.direct(direct_msg)

            if len(retVal) != byte_count:
                raise RuntimeError("Did not receive the expected number of bytes")
            return retVal
        else:
            raise RuntimeError("Unknown read type chosen for the USB ISS: {}".format(read_type))

    def _direct_i2c(self, commands: list) -> list:
        direct_msg = []

        idx = 0
        while True:
            if idx >= len(commands):
                break

            command = commands[idx]
            if command not in I2CMessages:
                raise RuntimeError("Unknown I2C command")

            direct_msg += [command.value]
            if command == I2CMessages.WRITE1:
                direct_msg += [commands[idx+1]]
                idx += 2
            elif command == I2CMessages.WRITE2:
                direct_msg += [commands[idx+1], commands[idx+2]]
                idx += 3
            elif command == I2CMessages.WRITE3:
                direct_msg += [commands[idx+1], commands[idx+2], commands[idx+3]]
                idx += 4
            elif command.name.startswith("WRITE"):
                n = int(command.name[5:])
                direct_msg += [commands[idx+j] for j in range(1, n+1)]
                idx += n + 1
            else:
                idx += 1

        return self._iss.i2c.direct(direct_msg)
