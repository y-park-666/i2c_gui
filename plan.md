# Step 1 Plan: Batch Metadata and Browser-Ready Measurement Data

## Summary
Implement the first step in `/helpers` by standardizing baseline/noise-width measurement output, adding explicit batch metadata at measurement start, and reshaping saved results so they are ready for a future `localhost` browser UI on the Raspberry Pi.

This step does **not** build the browser app yet. It prepares the measurement layer so the later FastAPI + Plotly UI can call a stable API and render results without reworking the Raspberry Pi I2C logic.

## Key Changes
- Extend the helper measurement flow in `helpers/i2c_gui2_helpers.py` so each measurement run is represented as a named batch with explicit metadata, not only `save_notes`.
- Introduce a batch metadata object carried through the whole run with these required fields:
  - `batch_name` from the user before measurement starts
  - `batch_started_at` as ISO timestamp
  - `batch_id` as a filesystem-safe unique identifier derived from timestamp plus batch name
- Keep existing chip-level measurement behavior unchanged:
  - per-pixel `row`, `col`, `baseline`, `noise_width`, `timestamp`
  - per-chip DataFrame storage in `self.BL_df`
  - Raspberry Pi I2C path via `RPI_I2C_Helper`
- Add a structured run result interface in the helper layer:
  - one method to run calibration and return raw per-chip DataFrames
  - one method to package browser-ready plot data
  - one method to persist batch outputs to disk and SQLite
- Replace loose `save_notes` usage as the primary identifier with explicit batch columns added to every saved row:
  - `batch_name`
  - `batch_id`
  - `batch_started_at`
  - `chip_name`
  - `chip_address`
- Preserve backward compatibility by allowing `save_notes` to remain as an optional free-text note field, but stop relying on it for batch identity.
- Standardize output directory layout under a caller-provided root, keyed by `batch_id`, with:
  - raw per-chip CSV files
  - SQLite append to history
  - optional static PNG exports from existing Matplotlib helpers
  - a single JSON summary file for future FastAPI consumption
- Define the browser-ready JSON shape now so the web layer can use it later without changing helper logic:
  - batch metadata
  - per-chip measurement table
  - per-chip heatmap matrices for `baseline` and `noise_width`
  - per-chip summary statistics for histogram display
- Keep plotting on the Raspberry Pi as the default architecture for later steps.
- Design the data contract for a future FastAPI + Plotly app, but do not implement HTTP routes in this step.

## Public Interfaces / Behavior
- Update the baseline-saving API in helpers so callers provide explicit batch metadata before persistence.
- Add a helper entrypoint that looks conceptually like:
  - `start_batch(batch_name, note=None)`
  - `run_auto_calibration_batch(...)`
  - `save_batch_results(output_dir, save_sqlite=True, save_csv=True, save_png=True, save_json=True)`
- The returned in-memory batch result should contain:
  - batch metadata
  - per-chip raw records
  - per-chip pivoted `baseline` and `noise_width` matrices
  - per-chip plot stats
- Existing scripts such as `helpers/chip_config.py` and `helpers/i2c_test_with_rpi.py` should be updated in a later implementation pass to call the new batch-oriented API, but the measurement semantics should remain unchanged.

## Test Plan
- Verify a full Raspberry Pi measurement run still completes for one chip and for multiple chips.
- Verify every saved row in SQLite contains:
  - `batch_name`
  - `batch_id`
  - `batch_started_at`
  - `chip_name`
  - `chip_address`
- Verify per-chip CSV output matches the in-memory DataFrame columns and row count.
- Verify pivoted matrices are always 16x16 and align correctly with `row` and `col`.
- Verify JSON output contains enough data to build:
  - baseline heatmap
  - noise-width heatmap
  - baseline histogram
  - noise-width histogram
- Verify batch names with spaces or punctuation still produce a safe `batch_id`.
- Verify existing Matplotlib PNG generation still works when enabled.
- Verify helper behavior remains usable with `use_usb_iss=False` on Raspberry Pi.

## Assumptions and Defaults
- Default plotting target for the product is the Raspberry Pi browser UI on `localhost`, not an external plotting server.
- Future web stack will be FastAPI + Plotly.
- SQLite remains the default historical store for now.
- Static PNG export remains supported for archival, but JSON becomes the primary handoff format for the future browser UI.
- No schema migration of old SQLite rows is required in this first step; new rows may simply include the added batch columns.
