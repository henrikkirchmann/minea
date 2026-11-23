"""Encode the paper's DaRA observation intervals from the two v1 sensor archives."""

import csv
import math
from dataclasses import dataclass
from pathlib import Path
from zipfile import ZipFile

import numpy as np
import pandas as pd


HERE = Path(__file__).resolve().parent
DATASET = HERE.parents[2] / "datasets/dara-retrieval"
BLE_ZIP = "BLE__Data_and_Revised_Annotations.zip"
IMU_ZIP = "IMU__Data_and_Revised_Annotations.zip"
BEACONS = [*range(1, 43), *range(44, 59)]
BLE_COLUMNS = [f"{site}_{beacon}" for site in "LTR" for beacon in BEACONS]
IMU_COLUMNS = [f"{sensor}{axis}_{site}" for site in "LTR"
               for sensor in ("Acc", "Gyr") for axis in "XYZ"]


@dataclass(frozen=True)
class Observation:
    id: str
    worker: str
    session: int
    case: str
    start: int
    end: int
    label: str


def load_observations(log_path):
    with log_path.open(newline="", encoding="utf-8") as stream:
        rows = [Observation(r["dara:observation_id"], r["case:dara:worker"],
                            int(r["case:dara:session"]), r["case:concept:name"],
                            int(r["dara:start_frame"]), int(r["dara:end_frame"]),
                            r["dara:activity_id"]) for r in csv.DictReader(stream)]
    # This is also the training-row order used to break equal distances.
    rows.sort(key=lambda r: (r.worker, r.start))
    if len(rows) != 4984 or len({r.id for r in rows}) != len(rows):
        raise ValueError("Expected 4,984 unique DaRA retrieval observations")
    return rows


def sample_range(row, anchors, sensor):
    """Map [start, end) video frames to sensor rows using Table 8.1's anchors."""
    start, end = int(anchors["video_first"]), int(anchors["video_last"])
    if not start <= row.start < row.end <= end:
        raise ValueError(f"{row.id} falls outside the synchronization anchors")
    count = int(anchors[f"{sensor}_last"]) - int(anchors[f"{sensor}_first"])
    # The first data row is already at the initial synchronization movement.
    return tuple(-(-((frame - start) * count) // (end - start)) for frame in (row.start, row.end))


def read_device(archive, sensor, worker, wearable_set, dtype):
    suffix = f"__{worker}__{wearable_set}__{sensor}_Data.csv"
    members = [name for name in archive.namelist() if name.endswith(suffix)]
    if len(members) != 1:
        raise ValueError(f"Expected one archive member ending in {suffix}")
    with archive.open(members[0]) as stream:
        return pd.read_csv(stream, dtype=dtype)


def encode_radio(window):
    finite = np.isfinite(window)
    count = finite.sum(axis=0)
    total = np.where(finite, window, 0).sum(axis=0, dtype=np.float64)
    means = np.full(len(BLE_COLUMNS), -110.0)
    np.divide(total, count, where=count > 0, out=means)
    fraction = count / len(window) if len(window) else np.zeros_like(means)
    return np.r_[means, fraction]


def encode_motion(window):
    magnitudes = np.linalg.norm(window.reshape(-1, 6, 3), axis=2)
    return np.r_[window.mean(axis=0), window.std(axis=0), magnitudes.mean(axis=0),
                 magnitudes.std(axis=0), np.percentile(magnitudes, 90, axis=0)]


def extract(raw_dir, rows):
    radio = np.empty((len(rows), 343), dtype=np.float32)
    motion = np.empty((len(rows), 54), dtype=np.float64)
    with (HERE / "sync_anchors.csv").open(newline="", encoding="utf-8") as stream:
        clocks = {r["worker"]: r for r in csv.DictReader(stream)}
    workers = sorted({r.worker for r in rows})
    with ZipFile(raw_dir / BLE_ZIP) as ble_zip, ZipFile(raw_dir / IMU_ZIP) as imu_zip:
        for worker in workers:
            a = clocks[worker]
            device = a["wearable_set"]
            ble = read_device(ble_zip, "BLE", worker, device, np.float32)
            if [s.removeprefix("# ").strip() for s in ble.columns] != BLE_COLUMNS:
                raise ValueError(f"Unexpected BLE channel order for {worker}")
            if abs(len(ble) - (int(a["ble_last"]) - int(a["ble_first"]))) > 1:
                raise ValueError(f"Unexpected BLE sample count for {worker}")
            signal = ble.to_numpy()
            imu = read_device(imu_zip, "IMU", worker, device, np.int32)
            if list(imu.columns) != ["Time", *IMU_COLUMNS]:
                raise ValueError(f"Unexpected IMU channel order for {worker}")
            clock = imu["Time"].to_numpy()
            if (len(imu) != int(a["imu_last"]) - int(a["imu_first"])
                    or clock[0] != int(a["imu_first"]) * 10 or not np.all(np.diff(clock) == 10)):
                raise ValueError(f"Unexpected IMU clock for {worker}")
            axes = imu[IMU_COLUMNS].to_numpy(dtype=np.float32)
            for i, row in enumerate(rows):
                if row.worker != worker:
                    continue
                lo, hi = sample_range(row, a, "ble")
                if not 0 <= lo <= hi <= len(signal):
                    raise ValueError(f"BLE sample range outside the archive for {row.id}")
                radio[i, :-1] = encode_radio(signal[lo:hi])
                radio[i, -1] = math.log1p((row.end - row.start) * 100 / 2997)
                lo, hi = sample_range(row, a, "imu")
                if not 0 <= lo < hi <= len(axes):
                    raise ValueError(f"IMU sample range outside the archive for {row.id}")
                motion[i] = encode_motion(axes[lo:hi])
            print(f"{worker}: encoded BLE, IMU and duration", flush=True)
    if not (np.isfinite(radio).all() and np.isfinite(motion).all()):
        raise ValueError("The observation feature matrix contains nonfinite values")
    return radio, motion
