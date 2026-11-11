"""Stand-in for collect_evidence.py in the pipeline tests (no Grafana, no app needed)."""

import argparse
import json
import subprocess

parser = argparse.ArgumentParser()
parser.add_argument("--incident-id")
parser.add_argument("--out")
parser.add_argument("--repo")
parser.add_argument("--alert")
args = parser.parse_args()
commit = subprocess.run(
    ["git", "-C", args.repo, "rev-parse", "HEAD"], capture_output=True, text=True, check=True
).stdout.strip()
evidence = {
    "incident_id": args.incident_id,
    "alert": {"alertname": "EchoNotes transcription failure ratio high"},
    "deployment": {
        "http_status": 200,
        "commit": commit,
        "version": "0.0.0",
        "environment": "local",
    },
    "metrics": {"failure_ratio_2m": {"series": [{"labels": {}, "value": 0.4}]}},
    "logs": {
        "source": "stub",
        "lines": [
            {
                "level": "ERROR",
                "exc_type": "ZeroDivisionError",
                "stack_trace": 'File "app/calc.py", line 2, in ratio',
                "trace_id": "a" * 32,
                "authorization": "Bearer abcdefghijklmnop",
            }
        ],
    },
    "traces": [],
    "git": {"recent_commits": []},
    "collection_errors": [],
}
with open(args.out, "w", encoding="utf-8") as fh:
    json.dump(evidence, fh)
