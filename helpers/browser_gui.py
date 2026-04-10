from __future__ import annotations

import json
import threading
import traceback
import uuid

from dataclasses import dataclass
from pathlib import Path

from fastapi import FastAPI, Form, HTTPException, Request
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

try:
    from .i2c_gui2_helpers import i2c_connection
except ImportError as _exc:
    # Only fall back to the non-relative import when the helpers module itself
    # wasn't found (i.e. running as a script rather than as a package).
    # Re-raise for any other ImportError so dependency problems surface clearly.
    if "i2c_gui2_helpers" not in str(_exc):
        raise
    from i2c_gui2_helpers import i2c_connection


BASE_DIR = Path(__file__).resolve().parent
TEMPLATE_DIR = BASE_DIR / "templates"
ARTIFACT_ROOT = BASE_DIR / "output" / "browser_batches"
ARTIFACT_ROOT.mkdir(parents=True, exist_ok=True)

DEFAULT_CHIP_NAMES = "ET2p03_Bare19,ET2p03_Bare20,ET2p03_Bare21,ET2p03_Bare22"
DEFAULT_CHIP_ADDRESSES = "0x60,0x61,0x62,0x63"
DEFAULT_WS_ADDRESSES = "None,None,None,None"


@dataclass
class JobConfig:
    batch_name: str
    note: str
    port: str
    clock: int
    use_usb_iss: bool
    chip_names: list[str]
    chip_addresses: list[int]
    ws_addresses: list[int | None]


app = FastAPI(title="ETROC2 Measurement GUI")
templates = Jinja2Templates(directory=str(TEMPLATE_DIR))
app.mount("/artifacts", StaticFiles(directory=str(ARTIFACT_ROOT)), name="artifacts")

_jobs: dict[str, dict] = {}
_jobs_lock = threading.Lock()


def _split_csv(value: str) -> list[str]:
    return [item.strip() for item in value.split(",") if item.strip()]


def _parse_chip_addresses(value: str) -> list[int]:
    addresses = []
    for item in _split_csv(value):
        addresses.append(int(item, 0))
    return addresses


def _parse_ws_addresses(value: str, expected_count: int) -> list[int | None]:
    if not value.strip():
        return [None] * expected_count

    raw_items = _split_csv(value)
    if len(raw_items) != expected_count:
        raise ValueError("Waveform sampler address count must match chip count.")

    ws_addresses: list[int | None] = []
    for item in raw_items:
        if item.lower() in {"none", "null", ""}:
            ws_addresses.append(None)
        else:
            ws_addresses.append(int(item, 0))
    return ws_addresses


def _build_job_config(
    batch_name: str,
    note: str,
    port: str,
    clock: int,
    use_usb_iss: bool,
    chip_names: str,
    chip_addresses: str,
    ws_addresses: str,
) -> JobConfig:
    parsed_chip_names = _split_csv(chip_names)
    parsed_chip_addresses = _parse_chip_addresses(chip_addresses)

    if not parsed_chip_names:
        raise ValueError("At least one chip name is required.")
    if len(parsed_chip_names) != len(parsed_chip_addresses):
        raise ValueError("Chip names and chip addresses must have the same count.")

    parsed_ws_addresses = _parse_ws_addresses(ws_addresses, len(parsed_chip_addresses))

    return JobConfig(
        batch_name=batch_name.strip(),
        note=note.strip(),
        port=port.strip(),
        clock=clock,
        use_usb_iss=use_usb_iss,
        chip_names=parsed_chip_names,
        chip_addresses=parsed_chip_addresses,
        ws_addresses=parsed_ws_addresses,
    )


def _relative_artifact_url(path_value: str | None) -> str | None:
    if not path_value:
        return None
    path = Path(path_value).resolve()
    try:
        relative = path.relative_to(ARTIFACT_ROOT.resolve())
    except ValueError:
        return None
    return f"/artifacts/{relative.as_posix()}"


def _decorate_result(summary: dict | None) -> dict | None:
    if summary is None:
        return None

    decorated = json.loads(json.dumps(summary))
    artifacts = decorated.get("artifacts", {})
    artifacts["batch_dir_url"] = _relative_artifact_url(artifacts.get("batch_dir"))
    artifacts["json_url"] = _relative_artifact_url(artifacts.get("json_path"))

    raw_dir = artifacts.get("raw_dir")
    if raw_dir:
        raw_path = Path(raw_dir)
        artifacts["csv_files"] = [
            {
                "name": csv_file.name,
                "url": _relative_artifact_url(str(csv_file)),
            }
            for csv_file in sorted(raw_path.glob("*.csv"))
        ]
    else:
        artifacts["csv_files"] = []

    figure_dir = artifacts.get("figure_dir")
    if figure_dir:
        figure_path = Path(figure_dir)
        artifacts["figure_files"] = [
            {
                "name": figure_file.name,
                "url": _relative_artifact_url(str(figure_file)),
            }
            for figure_file in sorted(figure_path.glob("*.png"))
        ]
    else:
        artifacts["figure_files"] = []

    decorated["artifacts"] = artifacts
    return decorated


def _run_job(job_id: str, config: JobConfig):
    with _jobs_lock:
        _jobs[job_id]["status"] = "running"
        _jobs[job_id]["message"] = "Connecting to hardware"

    try:
        connection = i2c_connection(
            config.port,
            config.chip_addresses,
            config.ws_addresses,
            config.chip_names,
            clock=config.clock,
            use_usb_iss=config.use_usb_iss,
        )

        with _jobs_lock:
            _jobs[job_id]["message"] = "Starting batch"

        connection.start_batch(config.batch_name, note=config.note)

        with _jobs_lock:
            _jobs[job_id]["message"] = "Running PLL and fast-command calibration"

        for chip_address in config.chip_addresses:
            connection.calibratePLL(chip_address, chip=None)
            connection.asyResetGlobalReadout(chip_address, chip=None)
            connection.asyAlignFastcommand(chip_address, chip=None)

        with _jobs_lock:
            _jobs[job_id]["message"] = "Running baseline and noise width measurement"

        connection.config_chips(
            do_pixel_check=False,
            do_basic_peripheral_register_check=False,
            do_set_chip_peripherals=True,
            do_disable_all_pixels=False,
            do_auto_calibration=False,
            do_disable_and_calibration=True,
            do_prepare_ws_testing=False,
        )

        with _jobs_lock:
            _jobs[job_id]["message"] = "Saving batch artifacts"

        summary = connection.save_batch_results(
            output_dir=str(ARTIFACT_ROOT),
            save_sqlite=True,
            save_csv=True,
            save_png=False,
            save_json=True,
        )

        with _jobs_lock:
            _jobs[job_id]["status"] = "completed"
            _jobs[job_id]["message"] = "Measurement completed"
            _jobs[job_id]["result"] = summary

    except Exception:
        with _jobs_lock:
            _jobs[job_id]["status"] = "error"
            _jobs[job_id]["message"] = "Measurement failed"
            _jobs[job_id]["error"] = traceback.format_exc()


def _job_snapshot(job_id: str) -> dict:
    with _jobs_lock:
        if job_id not in _jobs:
            raise HTTPException(status_code=404, detail="Unknown job id")
        return json.loads(json.dumps(_jobs[job_id]))


@app.get("/")
def index(request: Request):
    jobs = []
    with _jobs_lock:
        for job_id, job in _jobs.items():
            jobs.append({
                "job_id": job_id,
                "status": job["status"],
                "message": job["message"],
                "batch_name": job["config"]["batch_name"],
            })
    jobs.sort(key=lambda item: item["job_id"], reverse=True)

    return templates.TemplateResponse(
        request,
        "index.html",
        {
            "defaults": {
                "port": "/dev/ttyACM0",
                "clock": 100,
                "chip_names": DEFAULT_CHIP_NAMES,
                "chip_addresses": DEFAULT_CHIP_ADDRESSES,
                "ws_addresses": DEFAULT_WS_ADDRESSES,
            },
            "jobs": jobs[:10],
        },
    )


@app.post("/start")
def start_measurement(
    batch_name: str = Form(...),
    note: str = Form(""),
    port: str = Form("/dev/ttyACM0"),
    clock: int = Form(100),
    chip_names: str = Form(DEFAULT_CHIP_NAMES),
    chip_addresses: str = Form(DEFAULT_CHIP_ADDRESSES),
    ws_addresses: str = Form(DEFAULT_WS_ADDRESSES),
    transport: str = Form("usb_iss"),
):
    if not batch_name.strip():
        raise HTTPException(status_code=400, detail="Batch name is required.")

    try:
        config = _build_job_config(
            batch_name=batch_name,
            note=note,
            port=port,
            clock=clock,
            use_usb_iss=(transport != "rpi"),
            chip_names=chip_names,
            chip_addresses=chip_addresses,
            ws_addresses=ws_addresses,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    job_id = uuid.uuid4().hex[:12]
    job_payload = {
        "job_id": job_id,
        "status": "queued",
        "message": "Queued",
        "error": None,
        "result": None,
        "config": {
            "batch_name": config.batch_name,
            "note": config.note,
            "port": config.port,
            "clock": config.clock,
            "use_usb_iss": config.use_usb_iss,
            "chip_names": config.chip_names,
            "chip_addresses": [hex(address) for address in config.chip_addresses],
            "ws_addresses": [None if address is None else hex(address) for address in config.ws_addresses],
        },
    }

    with _jobs_lock:
        _jobs[job_id] = job_payload

    thread = threading.Thread(target=_run_job, args=(job_id, config), daemon=True)
    thread.start()

    return RedirectResponse(url=f"/jobs/{job_id}", status_code=303)


@app.get("/jobs/{job_id}")
def job_detail(request: Request, job_id: str):
    job = _job_snapshot(job_id)
    decorated_result = _decorate_result(job.get("result"))
    chart_payload = json.dumps(decorated_result) if decorated_result else None

    return templates.TemplateResponse(
        request,
        "job.html",
        {
            "job": job,
            "decorated_result": decorated_result,
            "chart_payload": chart_payload,
        },
    )


@app.get("/api/jobs/{job_id}")
def job_api(job_id: str):
    job = _job_snapshot(job_id)
    job["result"] = _decorate_result(job.get("result"))
    return job
