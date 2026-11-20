"""Non-actuating hook for an ALREADY CONNECTED existing LeRobot observation loop.

No hardware import, no bus connect, no motor calls, no database/disk in publisher's loop.
"""
from __future__ import annotations

import json
import math
import queue
import threading
from pathlib import Path
from typing import Any

from .generic import SAMPLE_SCHEMA
from .timebase import host_clock_domain, source_receive_stamp


class TelemetryJSONL:
    def __init__(
        self, path: str | Path, *, source_id: str, reference_frame_id: str,
        producer: str = "external-observation-loop/hook", queue_max: int = 512,
    ) -> None:
        self.path = Path(path).expanduser()
        if not source_id or not reference_frame_id:
            raise ValueError("Source and frame IDs required")
        self.source_id = source_id
        self.reference_frame_id = reference_frame_id
        self.producer = producer
        self.clock_domain = host_clock_domain()  # read /proc just once during setup
        self.next_sequence = 0
        self.queue: queue.Queue[dict | None] = queue.Queue(maxsize=queue_max)
        self.dropped = 0
        self.closed = False
        self.write_errors: list[str] = []
        self.thread = threading.Thread(target=self._write, daemon=True)
        self.thread.start()

    @staticmethod
    def sanitize_numeric_observation(observation: dict[str, Any]) -> dict[str, Any]:
        """Extract motor telemetry scalars only; NEVER images or bytes.

        Units are declared unknown unless separately calibrated/documented.
        A LeRobot *.pos property may use normalized units, percentages or degrees;
        do not assume radians or meter-scale positions.
        """
        values = {}
        for k, v in observation.items():
            if not isinstance(k, str) or not k.endswith((".pos", ".vel", ".torque")):
                continue
            if type(v) not in (float, int) or not math.isfinite(float(v)):
                continue
            values[k] = {"value": float(v), "unit_str": "SOURCE_NATIVE_UNSPECIFIED"}
        return {"measurements": values}

    def publish(self, observation: dict[str, Any]) -> None:
        if self.closed:
            raise RuntimeError("Publisher closed")
        # Called immediately after existing get_observation(). No robot calls here.
        stamp = source_receive_stamp(method="userspace_after_existing_robot_observation",
                                     clock_domain=self.clock_domain)
        sample = {
            "schema_ref_str": SAMPLE_SCHEMA,
            "producer_str": self.producer,
            "source": {
                "source_id_str": self.source_id,
                "modality_str": "joint_state",
                "reference_frame_id_str": self.reference_frame_id,
                "sample_sequence_uint": self.next_sequence,
            },
            "temporal_binding": stamp,
            "payload": self.sanitize_numeric_observation(observation),
        }
        if not sample["payload"]["measurements"]:
            raise ValueError("No numeric .pos/.vel/.torque telemetry in supplied observation")
        self.next_sequence += 1
        try:
            self.queue.put_nowait(sample)
        except queue.Full:
            self.dropped += 1

    def _write(self) -> None:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            # Exclusive, creation only: never append to a previous session.
            with self.path.open("x", encoding="utf-8") as writer:
                while True:
                    item = self.queue.get()
                    if item is None:
                        self.queue.task_done()
                        break
                    writer.write(json.dumps(item, sort_keys=True, allow_nan=False) + "\n")
                    self.queue.task_done()
                writer.flush()
        except Exception as exc:
            self.write_errors.append(repr(exc))

    def close(self) -> None:
        if self.closed:
            return
        self.closed = True
        # Drain queued observations and ask background worker to exit.
        try:
            self.queue.put(None, timeout=2)
        except queue.Full:
            self.write_errors.append("Telemetry writer queue remained full on shutdown")
        self.thread.join(timeout=10)
        if self.thread.is_alive():
            self.write_errors.append("Telemetry writer did not finish within 10 seconds")
        if self.write_errors:
            raise RuntimeError("Telemetry writer errors: " + ", ".join(self.write_errors))
