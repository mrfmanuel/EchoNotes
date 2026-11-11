# Recovery verification

- App: `http://localhost:8001`  expected commit: `0e67e00332012ce5ae617dda159a8cce5c83c391`
- Started (UTC): 2026-11-11T05:32:39Z

## Recovery checks

| Check | Result | Detail |
|---|---|---|
| health_and_commit | PASS | HTTP 200, commit `0e67e0033201` |
| http_failure_ratio | PASS | 0/20 5xx = 0.0 (threshold 0.2); by kind {'normal': {'201': 12}, 'short': {'201': 8}} |
| prometheus_failure_ratio | PASS | delta 0 failed / 20 total = 0.0 |
| fixed_revision_in_prometheus | PASS | target_info{job="echonotes-api",vcs_ref_head_revision="0e67e0033201..."} present |
| alert_back_to_normal | INFO | Grafana rule state: inactive |

## Smoke test (scripts/smoke.sh)

```text
INFO  base URL: http://localhost:8001  python: python
PASS  health                 HTTP 200 database=ok version=0.1.0 commit=0e67e00 environment=local attempts=1 0.005472s
PASS  spa /                  HTTP 200 0.028711s
PASS  spa /projects/smoke-route HTTP 200 0.005453s
PASS  api unknown path       HTTP 404 0.004151s
PASS  create project         HTTP 201 id=b07d70fe-3d31-4258-b51f-fa0d4faac05e slug=smoke-test-20261111t053251z-2359 0.010571s
PASS  upload audio           HTTP 201 id=1b9f14b0-cdfa-4dd8-8685-a51bebbc8ff7 provider=fake duration=2.0s 0.018304s
PASS  get transcript         HTTP 200 text_chars=41 0.006317s
PASS  upload screenshot      HTTP 201 id=546c7d36-10af-4311-9bf1-95fbebd4e219 size_bytes=73 linked=yes 0.024748s
PASS  export zip             HTTP 200 application/zip bytes=1174 entries=4 tree=ok 0.009810s
PASS  delete project         HTTP 204 0.009223s
SMOKE PASSED
```

**Result: RECOVERED** (checks exit 0, smoke exit 0)
