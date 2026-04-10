import datetime
import json
import logging
import re
import sys
import time

import i2c_gui2
import numpy as np
import pandas as pd

from pathlib import Path
from tqdm import tqdm

try:
    from .i2c_rpi_helper import RPI_I2C_Helper
except ImportError:
    from i2c_rpi_helper import RPI_I2C_Helper


class i2c_connection():
    _chips = None

    def __init__(self, port, chip_addresses, ws_addresses, chip_names, clock=100, use_usb_iss=True):
        self.chip_addresses = chip_addresses
        self.ws_addresses = ws_addresses
        self.chip_names = chip_names

        self.fc_clk_delay = {chip_address: 1 for chip_address in self.chip_addresses}
        self.fc_data_delay = {chip_address: 1 for chip_address in self.chip_addresses}

        log_level = 10
        logging.basicConfig(format='%(asctime)s - %(levelname)s:%(name)s:%(message)s', stream=sys.stdout, force=True)
        logger = logging.getLogger("Script_Logger")
        self.chip_logger = logging.getLogger("Chip_Logger")
        if use_usb_iss:
            if i2c_gui2.USB_ISS_Helper is None:
                raise RuntimeError(
                    "USB-ISS transport selected but the 'usb_iss' package is not installed. "
                    "Run: pip install usb-iss"
                )
            self.conn = i2c_gui2.USB_ISS_Helper(port, clock, dummy_connect=False)
        else:
            self.conn = RPI_I2C_Helper()
        logger.setLevel(log_level)

        self.BL_df = {}
        for chip_address in chip_addresses:
            self.BL_df[chip_address] = pd.DataFrame()

        self._batch_metadata = None

    def config_chips(self,
                     do_pixel_check: bool = False,
                     do_basic_peripheral_register_check: bool = False,
                     do_set_chip_peripherals: bool = True,
                     do_disable_all_pixels: bool = False,
                     do_auto_calibration: bool = False,
                     do_disable_and_calibration: bool = False,
                     do_prepare_ws_testing: bool = False,
                     ):

        for chip_address, chip_name, ws_address in zip(self.chip_addresses, self.chip_names, self.ws_addresses):

            chip: i2c_gui2.ETROC2_Chip = self.get_chip_i2c_connection(chip_address, ws_address)

            if do_pixel_check:
                self.pixel_check(chip_address, chip)
            if do_basic_peripheral_register_check:
                self.basic_peripheral_register_check(chip_address, chip)
            if do_set_chip_peripherals:
                self.set_chip_peripherals(chip_address, chip)
            if do_disable_all_pixels:
                self.disable_all_pixels(chip_address, chip)
            if do_auto_calibration:
                self.auto_calibration(chip_address, chip_name, chip)
            if do_disable_and_calibration:
                self.disable_all_pixels(chip_address, chip)
                self.auto_calibration(chip_address, chip_name, chip)
            if do_prepare_ws_testing:
                self.prepare_ws_testing(chip_address, ws_address, chip)

    def __del__(self):
        del self.conn

    def _slugify(self, value: str) -> str:
        slug = re.sub(r"[^A-Za-z0-9]+", "-", value.strip()).strip("-").lower()
        return slug or "batch"

    def _now(self) -> datetime.datetime:
        return datetime.datetime.now().astimezone()

    def _format_timestamp(self, value):
        if isinstance(value, pd.Timestamp):
            return value.isoformat()
        if isinstance(value, datetime.datetime):
            return value.isoformat()
        return value

    def _require_batch_metadata(self):
        if self._batch_metadata is None:
            raise RuntimeError("Batch metadata is not initialized. Call start_batch(batch_name, note=None) before saving results.")
        return dict(self._batch_metadata)

    def _get_chip_name(self, chip_address: int) -> str:
        idx = self.chip_addresses.index(chip_address)
        return self.chip_names[idx]

    def _build_chip_measurement_df(self, chip_address: int) -> pd.DataFrame:
        current_df = self.BL_df.get(chip_address)
        if current_df is None or len(current_df) == 0:
            return pd.DataFrame(columns=[
                "row",
                "col",
                "baseline",
                "noise_width",
                "timestamp",
                "chip_name",
                "chip_address",
                "batch_name",
                "batch_id",
                "batch_started_at",
                "save_notes",
            ])

        batch = self._require_batch_metadata()
        df = current_df.copy()
        df["timestamp"] = df["timestamp"].map(self._format_timestamp)
        df["chip_name"] = self._get_chip_name(chip_address)
        df["chip_address"] = chip_address
        df["batch_name"] = batch["batch_name"]
        df["batch_id"] = batch["batch_id"]
        df["batch_started_at"] = batch["batch_started_at"]
        df["save_notes"] = batch["note"]
        return df

    def _build_pivot_frame(self, input_df: pd.DataFrame) -> pd.DataFrame:
        pivot_df = input_df.pivot(index=["row"], columns=["col"], values=["baseline", "noise_width"])
        pivot_df = pivot_df.sort_index(axis=0).sort_index(axis=1)
        return pivot_df

    def _matrix_from_pivot(self, pivot_df: pd.DataFrame, value_name: str) -> list[list[int]]:
        matrix = pivot_df[value_name].reindex(index=range(16), columns=range(16))
        return matrix.astype(object).where(pd.notnull(matrix), None).values.tolist()

    def _build_stats(self, input_df: pd.DataFrame, column_name: str) -> dict:
        values = input_df[column_name].to_numpy()
        return {
            "count": int(values.size),
            "min": float(values.min()) if values.size else None,
            "max": float(values.max()) if values.size else None,
            "mean": float(values.mean()) if values.size else None,
            "std": float(values.std()) if values.size else None,
        }

    def _build_chip_result(self, chip_address: int) -> dict:
        current_df = self._build_chip_measurement_df(chip_address)
        if len(current_df) == 0:
            return {
                "chip_name": self._get_chip_name(chip_address),
                "chip_address": chip_address,
                "records": [],
                "heatmaps": {"baseline": [], "noise_width": []},
                "stats": {"baseline": {}, "noise_width": {}},
            }

        pivot_df = self._build_pivot_frame(current_df)
        return {
            "chip_name": self._get_chip_name(chip_address),
            "chip_address": chip_address,
            "records": current_df.to_dict(orient="records"),
            "heatmaps": {
                "baseline": self._matrix_from_pivot(pivot_df, "baseline"),
                "noise_width": self._matrix_from_pivot(pivot_df, "noise_width"),
            },
            "stats": {
                "baseline": self._build_stats(current_df, "baseline"),
                "noise_width": self._build_stats(current_df, "noise_width"),
            },
        }

    def _ensure_sqlite_columns(self, sqlconn, table_name: str, required_columns: list[str]):
        cursor = sqlconn.cursor()
        cursor.execute(f"CREATE TABLE IF NOT EXISTS {table_name} (row INTEGER)")
        existing = {row[1] for row in cursor.execute(f"PRAGMA table_info({table_name})")}
        for column in required_columns:
            if column not in existing:
                cursor.execute(f"ALTER TABLE {table_name} ADD COLUMN {column} TEXT")
        sqlconn.commit()

    def start_batch(self, batch_name: str, note: str = None) -> dict:
        started_at = self._now()
        timestamp = started_at.strftime("%Y%m%d_%H%M%S")
        batch_id = f"{timestamp}_{self._slugify(batch_name)}"
        self._batch_metadata = {
            "batch_name": batch_name,
            "batch_started_at": started_at.isoformat(),
            "batch_id": batch_id,
            "note": note or "",
        }
        return dict(self._batch_metadata)

    def get_batch_metadata(self) -> dict | None:
        if self._batch_metadata is None:
            return None
        return dict(self._batch_metadata)

    def get_batch_results(self) -> dict:
        batch = self._require_batch_metadata()
        chips = []
        for chip_address in self.chip_addresses:
            chips.append(self._build_chip_result(chip_address))
        return {
            "batch": batch,
            "chips": chips,
        }

    def run_auto_calibration_batch(self, batch_name: str, note: str = None, **config_chip_kwargs) -> dict:
        self.start_batch(batch_name=batch_name, note=note)
        self.config_chips(
            do_pixel_check=False,
            do_basic_peripheral_register_check=False,
            do_set_chip_peripherals=True,
            do_disable_all_pixels=False,
            do_auto_calibration=False,
            do_disable_and_calibration=True,
            do_prepare_ws_testing=False,
            **config_chip_kwargs,
        )
        return self.get_batch_results()

    def get_chip_i2c_connection(self, chip_address, ws_address=None):
        if self._chips is None:
            self._chips = {}

        if chip_address not in self._chips:
            self._chips[chip_address] = i2c_gui2.ETROC2_Chip(chip_address, ws_address, self.conn, self.chip_logger)

        return self._chips[chip_address]

    def get_bl_nw_map(self):
        return self.BL_df

    def auto_cal_single_pixel(self, chip_address: list[int], row: int, col: int, bl_nw_output: dict,
                              chip: i2c_gui2.ETROC2_Chip = None, verbose: bool = False):

        if chip is None and chip_address is not None:
            chip: i2c_gui2.ETROC2_Chip = self.get_chip_i2c_connection(chip_address)

        elif chip is None and chip_address is None:
            print("Need chip address to make a new chip in disable pixel!")
            return

        chip.row = row
        chip.col = col

        chip.read_all_block("ETROC2", "Pixel Config")

        chip.set_decoded_value("ETROC2", "Pixel Config", "enable_TDC", 0)
        chip.set_decoded_value("ETROC2", "Pixel Config", "CLKEn_THCal", 1)
        chip.set_decoded_value("ETROC2", "Pixel Config", "BufEn_THCal", 1)
        chip.set_decoded_value("ETROC2", "Pixel Config", "Bypass_THCal", 0)

        chip.write_all_block("ETROC2", "Pixel Config")

        chip.set_decoded_value("ETROC2", "Pixel Config", "RSTn_THCal", 0)
        chip.write_decoded_value("ETROC2", "Pixel Config", "RSTn_THCal")
        chip.set_decoded_value("ETROC2", "Pixel Config", "RSTn_THCal", 1)
        chip.write_decoded_value("ETROC2", "Pixel Config", "RSTn_THCal")

        chip.set_decoded_value("ETROC2", "Pixel Config", "ScanStart_THCal", 1)
        chip.write_decoded_value("ETROC2", "Pixel Config", "ScanStart_THCal")
        chip.set_decoded_value("ETROC2", "Pixel Config", "ScanStart_THCal", 0)
        chip.write_decoded_value("ETROC2", "Pixel Config", "ScanStart_THCal")

        retry_counter = 0
        chip.read_decoded_value("ETROC2", "Pixel Status", "ScanDone")
        while chip.get_decoded_value("ETROC2", "Pixel Status", "ScanDone") != 1:
            time.sleep(0.01)
            chip.read_decoded_value("ETROC2", "Pixel Status", "ScanDone")
            retry_counter += 1
            if retry_counter == 5 and chip.get_decoded_value("ETROC2", "Pixel Status", "ScanDone") != 1:
                print(f"Retry counter reaches at 5! // Auto_Calibration Scan has failed for row {row}, col {col}!!")
                break

        chip.read_all_block("ETROC2", "Pixel Status")

        bl_nw_output['row'].append(row)
        bl_nw_output['col'].append(col)
        bl_nw_output['baseline'].append(chip.get_decoded_value("ETROC2", "Pixel Status", "BL"))
        bl_nw_output['noise_width'].append(chip.get_decoded_value("ETROC2", "Pixel Status", "NW"))
        bl_nw_output['timestamp'].append(self._now())

        chip.set_decoded_value("ETROC2", "Pixel Config", "enable_TDC", 0)
        chip.set_decoded_value("ETROC2", "Pixel Config", "CLKEn_THCal", 0)
        chip.set_decoded_value("ETROC2", "Pixel Config", "BufEn_THCal", 0)
        chip.set_decoded_value("ETROC2", "Pixel Config", "Bypass_THCal", 1)
        chip.set_decoded_value("ETROC2", "Pixel Config", "DAC", 0x3ff)

        chip.write_all_block("ETROC2", "Pixel Config")

        if verbose:
            print(f"Auto calibration done (enTDC=0 + DAC=1023) for pixel ({row},{col}) on chip: {hex(chip_address)}")

    def config_TDC_window_ranges_in_memory(self, chip: i2c_gui2.ETROC2_Chip, window_dict: dict = None):
        if window_dict is None:
            window = {
                "upperTOATrig": 0x3ff,
                "lowerTOATrig": 0x000,
                "upperTOTTrig": 0x1ff,
                "lowerTOTTrig": 0x000,
                "upperCalTrig": 0x3ff,
                "lowerCalTrig": 0x000,
                "upperTOA": 0x3ff,
                "lowerTOA": 0x000,
                "upperTOT": 0x1ff,
                "lowerTOT": 0x000,
                "upperCal": 0x3ff,
                "lowerCal": 0x000,
            }
        else:
            window = window_dict

        for key, value in window.items():
            chip.set_decoded_value("ETROC2", "Pixel Config", key, value)

    def config_single_pixel(
            self, row: int, col: int,
            chip_address=None,
            Qsel: int = None,
            QInjEn: bool = False,
            Bypass_THCal: bool = True,
            power_mode: str = "high",
            chip: i2c_gui2.ETROC2_Chip = None,
            verbose: bool = False,
        ):

        valid_power_modes = ['low', '010', '101', 'high']

        if power_mode not in valid_power_modes:
            power_mode = "low"
        if chip is None and chip_address is not None:
            chip: i2c_gui2.ETROC2_Chip = self.get_chip_i2c_connection(chip_address)
        elif chip is None and chip_address is None:
            print("Need chip address to make a new chip in disable pixel!")
            return

        chip.row = row
        chip.col = col
        chip.read_all_block("ETROC2", "Pixel Config")

        pixel_config_dict = {
            'disDataReadout': 0,
            'QInjEn': 1 if QInjEn else 0,
            'disTrigPath': 0,
            'L1Adelay': 0x01f5,
            'Bypass_THCal': 1 if Bypass_THCal else 0,
            'TH_offset': 0x14,
            'QSel': Qsel if Qsel is not None else 0x1e,
            'DAC': 0x3ff,
            'enable_TDC': 1,
            'IBSel': 0b111,
        }

        self.config_TDC_window_ranges_in_memory(chip=chip)

        if power_mode == "high":
            pixel_config_dict['IBSel'] = 0b000
        elif power_mode == "010":
            pixel_config_dict['IBSel'] = 0b010
        elif power_mode == "101":
            pixel_config_dict['IBSel'] = 0b101
        elif power_mode == "low":
            pixel_config_dict['IBSel'] = 0b111

        for key, value in pixel_config_dict.items():
            chip.set_decoded_value("ETROC2", "Pixel Config", key, value)
        chip.write_all_block("ETROC2", "Pixel Config")

        if verbose:
            print(f"Enabled pixel ({row},{col}) for chip: {hex(chip_address)}")

    def config_single_pixel_offset(self, chip_address, row: int, col: int, offset: int = 20, chip: i2c_gui2.ETROC2_Chip = None, verbose=False):

        if chip is None and chip_address is not None:
            chip: i2c_gui2.ETROC2_Chip = self.get_chip_i2c_connection(chip_address)

        elif chip is None and chip_address is None:
            print("Need chip address to make a new chip in disable pixel!")
            return

        tmp_df = self.BL_df[chip_address]
        bl = tmp_df.loc[(tmp_df['row'] == row) & (tmp_df['col'] == col)]['baseline'].values[0]

        chip.row = row
        chip.col = col

        chip.read_decoded_value("ETROC2", "Pixel Config", "DAC")
        old_DAC = chip.get_decoded_value("ETROC2", "Pixel Config", "DAC")

        chip.set_decoded_value("ETROC2", "Pixel Config", "DAC", bl + offset)
        chip.write_decoded_value("ETROC2", "Pixel Config", "DAC")
        new_DAC = chip.get_decoded_value("ETROC2", "Pixel Config", "DAC")

        if verbose:
            print(f'Old DAC value: {old_DAC} is changed to New DAC value: {new_DAC} with offset {offset} for pixel ({row},{col}) (BL={bl}) for chip: {hex(chip_address)}')

    def config_power_mode(self, chip_address: int, scan_list: list[tuple], power_mode: str = 'high', verbose: bool = False):

        valid_power_modes = ['low', '010', '101', 'high']

        if power_mode not in valid_power_modes:
            power_mode = "low"

        chip: i2c_gui2.ETROC2_Chip = self.get_chip_i2c_connection(chip_address)

        IBSel = 0b111

        if power_mode == "high":
            IBSel = 0b000
        elif power_mode == "010":
            IBSel = 0b010
        elif power_mode == "101":
            IBSel = 0b101
        elif power_mode == "low":
            IBSel = 0b111

        for row, col in scan_list:
            chip.row = row
            chip.col = col

            chip.set_decoded_value("ETROC2", "Pixel Config", "IBSel", IBSel)
            chip.write_decoded_value("ETROC2", "Pixel Config", "IBSel")

            if verbose:
                print(f"Set pixel ({row},{col}) to power mode: {IBSel}")

    def config_fc_data_delay(self, chip_address: int, fc_clk_delay: int, fc_data_delay: int):
        if fc_clk_delay > 1 or fc_clk_delay < 0:
            raise ValueError('fc_clk_delay value must be 0 or 1')

        if fc_data_delay > 1 or fc_data_delay < 0:
            raise ValueError('fc_data_delay value must be 0 or 1')

        self.fc_clk_delay[chip_address] = fc_clk_delay
        self.fc_data_delay[chip_address] = fc_data_delay

        chip: i2c_gui2.ETROC2_Chip = self.get_chip_i2c_connection(chip_address)

        chip.read_register("ETROC2", "Peripheral Config", "PeriCfg18")

        chip.set_decoded_value("ETROC2", "Peripheral Config", "fcClkDelayEn", fc_clk_delay)
        chip.set_decoded_value("ETROC2", "Peripheral Config", "fcDataDelayEn", fc_data_delay)

        chip.write_register("ETROC2", "Peripheral Config", "PeriCfg18")

        print(f"FC delays has been changed for the chip: {hex(chip_address)}")

    def pixel_check(self, chip_address, chip: i2c_gui2.ETROC2_Chip = None):
        pixel_flag_fail = False

        if chip is None:
            chip: i2c_gui2.ETROC2_Chip = self.get_chip_i2c_connection(chip_address)

        for row in range(16):
            for col in range(16):
                chip.row = row
                chip.col = col

                chip.read_decoded_value("ETROC2", "Pixel Status", 'PixelID')
                fetched_row = chip.get_decoded_value("ETROC2", "Pixel Status", 'PixelID-Row')
                fetched_col = chip.get_decoded_value("ETROC2", "Pixel Status", 'PixelID-Col')

                if row != fetched_row or col != fetched_col:
                    print(chip_address, f"Pixel ({row}, {col}) returned ({fetched_row}, {fetched_col}), failed consistency check!")
                    pixel_flag_fail = True

        if not pixel_flag_fail:
            print(f"Passed pixel check for chip: {hex(chip_address)}")

    def basic_peripheral_register_check(self, chip_address, chip: i2c_gui2.ETROC2_Chip = None):

        if chip is None:
            chip: i2c_gui2.ETROC2_Chip = self.get_chip_i2c_connection(chip_address)

        peri_flag_fail = False
        peripheralRegisterKeys = [i for i in range(32)]

        chip.read_all_block("ETROC2", "Peripheral Config")

        for peripheralRegisterKey in peripheralRegisterKeys:
            data_PeriCfgX = chip["ETROC2", "Peripheral Config", f"PeriCfg{peripheralRegisterKey}"]

            data_modified_PeriCfgX = data_PeriCfgX ^ 0xff

            chip["ETROC2", "Peripheral Config", f"PeriCfg{peripheralRegisterKey}"] = data_modified_PeriCfgX
            chip.write_register("ETROC2", "Peripheral Config", f"PeriCfg{peripheralRegisterKey}")

            data_new_1_PeriCfgX = chip["ETROC2", "Peripheral Config", f"PeriCfg{peripheralRegisterKey}"]
            chip.read_register("ETROC2", "Peripheral Config", f"PeriCfg{peripheralRegisterKey}")
            data_new_2_PeriCfgX = chip["ETROC2", "Peripheral Config", f"PeriCfg{peripheralRegisterKey}"]

            chip["ETROC2", "Peripheral Config", f"PeriCfg{peripheralRegisterKey}"] = data_PeriCfgX
            chip.write_register("ETROC2", "Peripheral Config", f"PeriCfg{peripheralRegisterKey}")
            data_recover_PeriCfgX = chip["ETROC2", "Peripheral Config", f"PeriCfg{peripheralRegisterKey}"]

            if(data_new_1_PeriCfgX != data_new_2_PeriCfgX or data_new_2_PeriCfgX != data_modified_PeriCfgX or data_recover_PeriCfgX != data_PeriCfgX):
                print(f"{chip_address}, PeriCfg{peripheralRegisterKey:2}", "FAILURE")
                peri_flag_fail = True

        if not peri_flag_fail:
            print(f"Passed peripheral write check for chip: {hex(chip_address)}")

        del peripheralRegisterKeys

    def set_chip_peripherals(self, chip_address, chip: i2c_gui2.ETROC2_Chip = None):

        if chip is None:
            chip: i2c_gui2.ETROC2_Chip = self.get_chip_i2c_connection(chip_address)

        chip.read_all_block("ETROC2", "Peripheral Config")

        chip.set_decoded_value("ETROC2", "Peripheral Config", "EFuse_Prog", 0x00017f0f)
        chip.set_decoded_value("ETROC2", "Peripheral Config", "singlePort", 1)
        chip.set_decoded_value("ETROC2", "Peripheral Config", "serRateLeft", 0b00)
        chip.set_decoded_value("ETROC2", "Peripheral Config", "serRateRight", 0b00)
        chip.set_decoded_value("ETROC2", "Peripheral Config", "onChipL1AConf", 0b00)
        chip.set_decoded_value("ETROC2", "Peripheral Config", "PLL_ENABLEPLL", 1)
        chip.set_decoded_value("ETROC2", "Peripheral Config", "chargeInjectionDelay", 0x0a)
        chip.set_decoded_value("ETROC2", "Peripheral Config", "triggerGranularity", 0x01)
        chip.set_decoded_value("ETROC2", "Peripheral Config", "fcClkDelayEn", self.fc_clk_delay[chip_address])
        chip.set_decoded_value("ETROC2", "Peripheral Config", "fcDataDelayEn", self.fc_data_delay[chip_address])

        chip.write_all_block("ETROC2", "Peripheral Config")

        print(f"Peripherals set for chip: {hex(chip_address)}")

    def disable_all_pixels(self, chip_address, chip: i2c_gui2.ETROC2_Chip = None):

        if chip is None:
            chip: i2c_gui2.ETROC2_Chip = self.get_chip_i2c_connection(chip_address)

        chip.row = 0
        chip.col = 0
        chip.read_all_block("ETROC2", "Pixel Config")

        pixel_config = {
            "disDataReadout": 1,
            "QInjEn": 0,
            "disTrigPath": 1,
            "upperTOATrig": 0x000,
            "lowerTOATrig": 0x000,
            "upperTOTTrig": 0x1ff,
            "lowerTOTTrig": 0x1ff,
            "upperCalTrig": 0x3ff,
            "lowerCalTrig": 0x3ff,
            "upperTOA": 0x000,
            "lowerTOA": 0x000,
            "upperTOT": 0x1ff,
            "lowerTOT": 0x1ff,
            "upperCal": 0x3ff,
            "lowerCal": 0x3ff,
            "enable_TDC": 0,
            "IBSel": 0,
            "Bypass_THCal": 1,
            "TH_offset": 0x3f,
            "DAC": 0x3ff,
        }

        for key, value in pixel_config.items():
            chip.set_decoded_value("ETROC2", "Pixel Config", key, value)

        chip.broadcast = True
        chip.write_all_block("ETROC2", "Pixel Config")
        chip.broadcast = False
        print(f"Disabled pixels (Bypass, TH-3f DAC-3ff) for chip: {hex(chip_address)}")

    def auto_calibration(self, chip_address, chip_name, chip: i2c_gui2.ETROC2_Chip = None, ver_on: bool = False):

        if chip is None:
            chip: i2c_gui2.ETROC2_Chip = self.get_chip_i2c_connection(chip_address)

        bl_nw_dict = {
            'row': [],
            'col': [],
            'baseline': [],
            'noise_width': [],
            'timestamp': [],
        }

        for row in tqdm(range(16), desc="Calibrating row", position=0):
            for col in range(16):
                self.auto_cal_single_pixel(chip_address=chip_address, row=row, col=col, bl_nw_output=bl_nw_dict, chip=chip, verbose=ver_on)

        bl_nw_df = pd.DataFrame(data=bl_nw_dict)
        bl_nw_df['chip_name'] = chip_name

        self.BL_df[chip_address] = bl_nw_df
        del bl_nw_dict, bl_nw_df

        print(f"Auto calibration finished for chip: {hex(chip_address)}")

    def prepare_ws_testing(self, chip_address, ws_address, chip: i2c_gui2.ETROC2_Chip = None, RFSel=0, QSel=30, QInjDelay=0x0a):

        if chip is None and chip_address is not None and ws_address is not None:
            chip: i2c_gui2.ETROC2_Chip = self.get_chip_i2c_connection(chip_address, ws_address)
        elif chip is None and (chip_address is None or ws_address is None):
            print("Need either a chip or chip+ws address to access registers!")

        chip.read_decoded_value("ETROC2", "Peripheral Config", "chargeInjectionDelay")
        chip.set_decoded_value("ETROC2", "Peripheral Config", "chargeInjectionDelay", QInjDelay)
        chip.write_decoded_value("ETROC2", "Peripheral Config", "chargeInjectionDelay")
        print("chargeInjectionDelay", chip.get_decoded_value("ETROC2", "Peripheral Config", "chargeInjectionDelay"))

        chip.row = 0
        chip.col = 14

        chip.read_decoded_value("ETROC2", "Pixel Config", "TH_offset")
        chip.set_decoded_value("ETROC2", "Pixel Config", "TH_offset", 20)
        chip.write_decoded_value("ETROC2", "Pixel Config", "TH_offset")
        print("TH_Offset", chip.get_decoded_value("ETROC2", "Pixel Config", "TH_offset"))

        chip.read_decoded_value("ETROC2", "Pixel Config", "RFSel")
        print("Before RFsel", chip.get_decoded_value("ETROC2", "Pixel Config", "RFSel"))
        chip.set_decoded_value("ETROC2", "Pixel Config", "RFSel", RFSel)
        chip.write_decoded_value("ETROC2", "Pixel Config", "RFSel")
        print("After RFsel", chip.get_decoded_value("ETROC2", "Pixel Config", "RFSel"))

        chip.read_decoded_value("ETROC2", "Pixel Config", "QSel")
        chip.set_decoded_value("ETROC2", "Pixel Config", "QSel", QSel)
        chip.write_decoded_value("ETROC2", "Pixel Config", "QSel")
        print("QSel", chip.get_decoded_value("ETROC2", "Pixel Config", "QSel"))

        print(f"WS Pixel (R0,C14) has been initialized TH_Offset = 20, RFSel = {RFSel}, QSel = {QSel} for chip: {hex(chip_address)}")

    def disable_ws_testing():
        pass

    def make_BL_NW_2D_maps(self, input_df: pd.DataFrame, given_chip_name: str, note: str, save_path, timestamp):

        from mpl_toolkits.axes_grid1 import make_axes_locatable
        import matplotlib.pyplot as plt
        import mplhep as hep
        hep.style.use('CMS')

        fig = plt.figure(dpi=200, figsize=(20, 10))
        gs = fig.add_gridspec(1, 2)
        ax0 = fig.add_subplot(gs[0, 0])
        ax0.set_title(f"{given_chip_name}: BL (DAC LSB)\n{note}", size=17, loc="right")
        img0 = ax0.imshow(input_df.baseline, interpolation='none', vmin=input_df.baseline.to_numpy().reshape(-1).min(), vmax=input_df.baseline.to_numpy().reshape(-1).max())
        ax0.set_aspect("equal")
        ax0.invert_xaxis()
        ax0.invert_yaxis()
        plt.xticks(range(16), range(16), rotation="vertical")
        plt.yticks(range(16), range(16))
        hep.cms.text(loc=0, ax=ax0, fontsize=17, text="ETL ETROC")
        divider = make_axes_locatable(ax0)
        cax = divider.append_axes('right', size="5%", pad=0.05)
        fig.colorbar(img0, cax=cax, orientation="vertical")

        ax1 = fig.add_subplot(gs[0, 1])
        ax1.set_title(f"{given_chip_name}: NW (DAC LSB)\n{note}", size=17, loc="right")
        img1 = ax1.imshow(input_df.noise_width, interpolation='none', vmin=0, vmax=16)
        ax1.set_aspect("equal")
        ax1.invert_xaxis()
        ax1.invert_yaxis()
        plt.xticks(range(16), range(16), rotation="vertical")
        plt.yticks(range(16), range(16))
        hep.cms.text(loc=0, ax=ax1, fontsize=17, text="ETL ETROC")
        divider = make_axes_locatable(ax1)
        cax = divider.append_axes('right', size="5%", pad=0.05)
        fig.colorbar(img1, cax=cax, orientation="vertical")

        bl_threshold = 0.55 * (input_df.baseline.values.max() - input_df.baseline.values.min()) + input_df.baseline.values.min()

        for col in range(16):
            for row in range(16):
                bl_value = int(input_df.baseline[col][row])
                nw_value = int(input_df.noise_width[col][row])
                bl_text_color = 'black' if bl_value > bl_threshold else 'white'
                nw_text_color = 'black' if nw_value > 9 else 'white'

                ax0.text(col, row, bl_value, c=bl_text_color, size=10, rotation=45, fontweight="bold", ha="center", va="center")
                ax1.text(col, row, nw_value, c=nw_text_color, size=11, rotation=45, fontweight="bold", ha="center", va="center")

        plt.tight_layout()
        fig.savefig(save_path / f'{given_chip_name}_BL_NW_2D_map_{timestamp}.png')
        plt.close(fig)

    def make_BL_NW_1D_hists(self, input_df: pd.DataFrame, given_chip_name: str, note: str, save_path, timestamp):
        import hist
        import matplotlib.pyplot as plt
        import matplotlib.ticker as ticker
        import mplhep as hep
        hep.style.use('CMS')

        fig, axes = plt.subplots(1, 2, figsize=(20, 10))
        hep.cms.text(loc=0, ax=axes[0], fontsize=17, text="ETL ETROC")
        axes[0].set_title(f"{given_chip_name}: BL (DAC LSB)\n{note}", size=17, loc="right")
        bl_array = input_df['baseline'].to_numpy().flatten()
        bl_hist = hist.Hist(hist.axis.Regular(128, 0, 1024, name='bl', label='BL [DAC]'))
        bl_hist.fill(bl_array)
        mean, std = bl_array.mean(), bl_array.std()
        bl_hist.plot1d(ax=axes[0], yerr=False, label=f'Mean: {mean:.2f}, Std: {std:.2f}')
        axes[0].legend()

        hep.cms.text(loc=0, ax=axes[1], fontsize=17, text="ETL ETROC")
        axes[1].set_title(f"{given_chip_name}: NW (DAC LSB)\n{note}", size=17, loc="right")
        nw_hist = hist.Hist(hist.axis.Regular(16, 0, 16, name='nw', label='NW [DAC]'))
        nw_array = input_df['noise_width'].to_numpy().flatten()
        nw_hist.fill(nw_array)
        mean, std = nw_array.mean(), nw_array.std()
        nw_hist.plot1d(ax=axes[1], yerr=False, label=f'Mean: {mean:.2f}, Std: {std:.2f}')
        axes[1].xaxis.set_major_locator(ticker.MultipleLocator(1))
        axes[1].xaxis.set_minor_locator(ticker.NullLocator())
        axes[1].legend()

        plt.tight_layout()
        fig.savefig(save_path / f'{given_chip_name}_BL_NW_1D_hist_{timestamp}.png')
        plt.close(fig)

    def save_batch_results(
            self,
            output_dir: str,
            save_sqlite: bool = True,
            save_csv: bool = True,
            save_png: bool = True,
            save_json: bool = True,
        ) -> dict:
        import sqlite3

        batch = self._require_batch_metadata()
        output_root = Path(output_dir)
        output_root.mkdir(exist_ok=True, parents=True)

        batch_dir = output_root / batch["batch_id"]
        raw_dir = batch_dir / "raw"
        figure_dir = batch_dir / "figures"
        json_dir = batch_dir / "json"
        raw_dir.mkdir(exist_ok=True, parents=True)
        figure_dir.mkdir(exist_ok=True, parents=True)
        json_dir.mkdir(exist_ok=True, parents=True)

        sqlite_path = output_root / "BaselineHistory.sqlite"
        summary = self.get_batch_results()
        timestamp = batch["batch_started_at"].replace(":", "-")

        required_columns = [
            "row",
            "col",
            "baseline",
            "noise_width",
            "timestamp",
            "chip_name",
            "chip_address",
            "batch_name",
            "batch_id",
            "batch_started_at",
            "save_notes",
        ]

        for chip_address in self.chip_addresses:
            current_df = self._build_chip_measurement_df(chip_address)
            if len(current_df) == 0:
                continue

            chip_name = self._get_chip_name(chip_address)
            pivot_df = self._build_pivot_frame(current_df)

            if save_sqlite:
                with sqlite3.connect(sqlite_path) as sqlconn:
                    self._ensure_sqlite_columns(sqlconn, "baselines", required_columns)
                    current_df.to_sql("baselines", sqlconn, if_exists='append', index=False)

            if save_csv:
                current_df.to_csv(raw_dir / f"{chip_name}_{batch['batch_id']}.csv", index=False)

            if save_png:
                try:
                    self.make_BL_NW_2D_maps(pivot_df, chip_name, batch["note"] or batch["batch_name"], figure_dir, timestamp)
                    self.make_BL_NW_1D_hists(current_df, chip_name, batch["note"] or batch["batch_name"], figure_dir, timestamp)
                except ImportError as exc:
                    logging.getLogger(__name__).warning("PNG export skipped — optional dependency missing: %s", exc)

        if save_json:
            with open(json_dir / "batch_summary.json", "w", encoding="utf-8") as outfile:
                json.dump(summary, outfile, indent=2)

        summary["artifacts"] = {
            "batch_dir": str(batch_dir),
            "sqlite_path": str(sqlite_path) if save_sqlite else None,
            "raw_dir": str(raw_dir) if save_csv else None,
            "figure_dir": str(figure_dir) if save_png else None,
            "json_path": str(json_dir / "batch_summary.json") if save_json else None,
        }
        return summary

    def save_baselines(
            self,
            hist_dir: str = "../ETROC-History",
            save_notes: str = "",
            batch_name: str = None,
        ):
        if self._batch_metadata is None:
            default_batch_name = batch_name or save_notes or f"batch_{datetime.date.today().isoformat()}"
            self.start_batch(default_batch_name, note=save_notes)
        else:
            if batch_name is not None and batch_name != self._batch_metadata["batch_name"]:
                self.start_batch(batch_name, note=save_notes)
            elif save_notes and self._batch_metadata.get("note") != save_notes:
                self._batch_metadata["note"] = save_notes

        return self.save_batch_results(
            output_dir=hist_dir,
            save_sqlite=True,
            save_csv=True,
            save_png=True,
            save_json=True,
        )

    def enable_select_pixels_in_chips(
            self,
            pixel_list: list[tuple],
            Qsel: int = None,
            QInjEn: bool = True,
            Bypass_THCal: bool = True,
            power_mode: str = "high",
            verbose: bool = False,
        ):
        valid_power_modes = ['low', '010', '101', 'high']

        if power_mode not in valid_power_modes:
            power_mode = "low"

        for chip_address in self.chip_addresses:
            chip: i2c_gui2.ETROC2_Chip = self.get_chip_i2c_connection(chip_address)

            for row, col in tqdm(pixel_list):
                self.config_single_pixel(row=row, col=col, chip_address=chip_address, Qsel=Qsel, QInjEn=QInjEn,
                                         Bypass_THCal=Bypass_THCal, power_mode=power_mode, chip=chip, verbose=verbose)

    def set_chip_offsets(self, chip_address, pixel_list: list[tuple] = None, offset: int = 20, chip: i2c_gui2.ETROC2_Chip = None, verbose=False):

        if chip is None:
            chip: i2c_gui2.ETROC2_Chip = self.get_chip_i2c_connection(chip_address)

        if pixel_list is None:
            raise ValueError('Please specify the pixel of interests in the input argument')

        for row, col in pixel_list:
            self.config_single_pixel_offset(chip_address=chip_address, row=row, col=col, offset=offset, chip=chip, verbose=verbose)

        print(f"Offset set to {hex(offset)} for chip: {hex(chip_address)}")

    def set_chip_offsets_broadcast(self, chip_address, offset: int = 20, chip: i2c_gui2.ETROC2_Chip = None):

        if chip is None:
            chip: i2c_gui2.ETROC2_Chip = self.get_chip_i2c_connection(chip_address)

        chip.row = 0
        chip.col = 0

        chip.read_decoded_value("ETROC2", "Pixel Config", "TH_offset")
        chip.set_decoded_value("ETROC2", "Pixel Config", "TH_offset", offset)

        try:
            chip.broadcast = True
            chip.write_decoded_value("ETROC2", "Pixel Config", "TH_offset")
            chip.broadcast = False

            print('Verifying Broadcast results')
            for row in tqdm(range(16), desc="Checking broadcast for row", position=0):
                for col in range(16):
                    chip.row = row
                    chip.col = col

                    chip.read_decoded_value("ETROC2", "Pixel Config", "TH_offset")
                    if chip.get_decoded_value("ETROC2", "Pixel Config", "TH_offset") != offset:
                        raise RuntimeError("Failed to verify broadcast results")

        except RuntimeError as err:
            print(err)
            col_list, row_list = np.meshgrid(np.arange(16), np.arange(16))
            scan_list = list(zip(row_list.flatten(), col_list.flatten()))
            for row, col in scan_list:
                self.config_single_pixel_offset(chip_address=chip_address, row=row, col=col, offset=offset, chip=chip)

        print(f"Offset set to {hex(offset)} for chip: {hex(chip_address)}")

    def onchipL1A(self, chip_address, chip: i2c_gui2.ETROC2_Chip = None, comm='00'):

        if chip is None:
            chip: i2c_gui2.ETROC2_Chip = self.get_chip_i2c_connection(chip_address)

        chip.read_decoded_value("ETROC2", "Peripheral Config", 'onChipL1AConf')
        chip.set_decoded_value("ETROC2", "Peripheral Config", 'onChipL1AConf', int(comm, base=2))
        chip.write_decoded_value("ETROC2", "Peripheral Config", 'onChipL1AConf')

        print(f"OnChipL1A action {comm} done for chip: {hex(chip_address)}")

    def asyAlignFastcommand(self, chip_address, chip: i2c_gui2.ETROC2_Chip = None):

        if chip is None:
            chip: i2c_gui2.ETROC2_Chip = self.get_chip_i2c_connection(chip_address)

        chip.read_decoded_value("ETROC2", "Peripheral Config", 'asyAlignFastcommand')
        chip.set_decoded_value("ETROC2", "Peripheral Config", 'asyAlignFastcommand', 1)
        chip.write_decoded_value("ETROC2", "Peripheral Config", 'asyAlignFastcommand')
        time.sleep(0.1)
        chip.set_decoded_value("ETROC2", "Peripheral Config", 'asyAlignFastcommand', 0)
        chip.write_decoded_value("ETROC2", "Peripheral Config", 'asyAlignFastcommand')

        print(f"asyAlignFastcommand action done for chip: {hex(chip_address)}")

    def asyResetGlobalReadout(self, chip_address, chip: i2c_gui2.ETROC2_Chip = None):

        if chip is None:
            chip: i2c_gui2.ETROC2_Chip = self.get_chip_i2c_connection(chip_address)

        chip.read_decoded_value("ETROC2", "Peripheral Config", 'asyResetGlobalReadout')
        chip.set_decoded_value("ETROC2", "Peripheral Config", 'asyResetGlobalReadout', 0)
        chip.write_decoded_value("ETROC2", "Peripheral Config", 'asyResetGlobalReadout')
        time.sleep(0.1)
        chip.set_decoded_value("ETROC2", "Peripheral Config", 'asyResetGlobalReadout', 1)
        chip.write_decoded_value("ETROC2", "Peripheral Config", 'asyResetGlobalReadout')

        print(f"Reset Global Readout done for chip: {hex(chip_address)}")

    def calibratePLL(self, chip_address, chip: i2c_gui2.ETROC2_Chip = None):

        if chip is None:
            chip: i2c_gui2.ETROC2_Chip = self.get_chip_i2c_connection(chip_address)

        chip.read_decoded_value("ETROC2", "Peripheral Config", 'asyPLLReset')
        chip.set_decoded_value("ETROC2", "Peripheral Config", 'asyPLLReset', 0)
        chip.write_decoded_value("ETROC2", "Peripheral Config", 'asyPLLReset')
        time.sleep(0.1)
        chip.set_decoded_value("ETROC2", "Peripheral Config", 'asyPLLReset', 1)
        chip.write_decoded_value("ETROC2", "Peripheral Config", 'asyPLLReset')

        chip.read_decoded_value("ETROC2", "Peripheral Config", 'asyStartCalibration')
        chip.set_decoded_value("ETROC2", "Peripheral Config", 'asyStartCalibration', 0)
        chip.write_decoded_value("ETROC2", "Peripheral Config", 'asyStartCalibration')
        time.sleep(0.1)
        chip.set_decoded_value("ETROC2", "Peripheral Config", 'asyStartCalibration', 1)
        chip.write_decoded_value("ETROC2", "Peripheral Config", 'asyStartCalibration')

        print(f"PLL Calibrated for chip: {hex(chip_address)}")

    def i2c_dumping(
        self,
        chip_address: int,
        ws_address: int,
        outdir: Path,
        chip_name: str,
        fname: str,
        full: bool,
    ):
        chip: i2c_gui2.ETROC2_Chip = self.get_chip_i2c_connection(chip_address, ws_address)
        start_time = time.time()

        if full:
            chip.read_all()
        else:
            chip.read_all_efficient()

        end_time = time.time()
        chip.save_config(outdir / f"{chip_name}_{fname}{'_full' if full else ''}.pckl")

        print("--- %s seconds ---" % (end_time - start_time))

    def i2c_loading(
        self,
        chip_address: int,
        ws_address: int,
        outdir: Path,
        chip_name: str,
        fname: str,
        full: bool,
    ):
        chip: i2c_gui2.ETROC2_Chip = self.get_chip_i2c_connection(chip_address, ws_address)
        chip.load_config(outdir / f"{chip_name}_{fname}{'_full' if full else ''}.pckl")

        start_time = time.time()

        if full:
            chip.write_all()
        else:
            chip.write_all_efficient()

        end_time = time.time()

        print("--- %s seconds ---" % (end_time - start_time))
