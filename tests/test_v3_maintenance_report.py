import json
import subprocess
import sys

from ombrebrain.app.legacy_runtime import LegacyRuntime
from ombrebrain.maintenance.report import V3MaintenanceReportBuilder


def test_maintenance_report_combines_architecture_resilience_and_decisions(tmp_path) -> None:
    runtime = LegacyRuntime.from_config({"buckets_dir": str(tmp_path / "buckets")})
    runtime.record_tool_event("breath", {"query": "x"})

    report = V3MaintenanceReportBuilder(runtime).build()

    assert report["ok"] is True
    assert report["architecture"]["ok"] is True
    assert report["resilience"]["ok"] is True
    assert report["decisions"]["count"] == 1
    assert report["runtime"]["root"].endswith(".ombrebrain-v3")


def test_v3_health_report_cli_prints_json(tmp_path) -> None:
    result = subprocess.run(
        [sys.executable, "tools/v3_health_report.py", "--buckets-dir", str(tmp_path / "buckets")],
        check=False,
        capture_output=True,
        text=True,
    )
    data = json.loads(result.stdout)

    assert result.returncode == 0
    assert data["architecture"]["ok"] is True
    assert "resilience" in data
    assert "decisions" in data


def test_v3_health_report_cli_can_write_output_file(tmp_path) -> None:
    output = tmp_path / "report.json"

    result = subprocess.run(
        [
            sys.executable,
            "tools/v3_health_report.py",
            "--buckets-dir",
            str(tmp_path / "buckets"),
            "--output",
            str(output),
        ],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0
    assert output.exists()
    assert json.loads(output.read_text(encoding="utf-8"))["architecture"]["ok"] is True
