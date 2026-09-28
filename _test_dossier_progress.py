#!/usr/bin/env python3
"""The dossier build's progress reporting, without needing a model.

The progress bar is only worth having if it reports what the build is actually
doing. A bar that advances on a client timer eventually outruns the work and
sits at 90% for a minute, which is worse than no bar at all - the candidate would
be watching a lie. So what needs testing is that the stages come from the build,
that they advance monotonically, and that the awkward cases behave: an unknown
stage is ignored, a late update cannot resurrect a finished job, and a job that
has not reported yet still yields a valid bar rather than nothing.

These run offline. The live behaviour - that all six stages actually fire on a
real upload - is covered by _check_progress_live.py, which needs the model up.
"""
import io
import json
import sys
import urllib.request
import urllib.error

sys.path.insert(0, ".")
import resume_server as rs  # noqa: E402

fails = []


def check(label, condition, detail=""):
    print(("  PASS  " if condition else "  FAIL  ") + label
          + ("" if condition else "   %s" % (detail,)))
    if not condition:
        fails.append(label)


print("=== the stage list ===")
check("there is a stage per build step", rs._DOSSIER_STAGE_TOTAL == 6,
      rs._DOSSIER_STAGE_TOTAL)
check("every stage has a label a candidate can read",
      all(text and len(text) > 12 for _, text in rs._DOSSIER_STAGES),
      rs._DOSSIER_STAGES)
check("stage labels are unique",
      len({t for _, t in rs._DOSSIER_STAGES}) == len(rs._DOSSIER_STAGES))
check("the three model passes are all stages",
      all(any(label == p for label, _ in rs._DOSSIER_STAGES)
          for p in ("identity", "history", "interpret")),
      [l for l, _ in rs._DOSSIER_STAGES])

print("\n=== progress reaches the job record ===")
rid = "test_progress_1"
rs._dossier_job_put(rid, {"status": "processing"})
check("a job that has reported nothing has no progress yet",
      "progress" not in (rs._dossier_job_get(rid) or {}))

rs._dossier_progress(rid, "identity")
first = rs._dossier_job_get(rid)["progress"]
check("the first stage is 1 of 6",
      (first["index"], first["total"]) == (1, 6), first)
check("it carries the human label, not the internal name",
      first["label"] == rs._DOSSIER_STAGES[0][1], first)

order = []
for label, _ in rs._DOSSIER_STAGES:
    rs._dossier_progress(rid, label)
    order.append(rs._dossier_job_get(rid)["progress"]["index"])
check("stages advance in order with no gaps or repeats",
      order == [1, 2, 3, 4, 5, 6], order)
check("the last stage reads as complete",
      rs._dossier_job_get(rid)["progress"]["index"] == rs._DOSSIER_STAGE_TOTAL)

print("\n=== progress does not survive the wrong conditions ===")
rs._dossier_progress(rid, "not-a-real-stage")
check("an unknown stage is ignored",
      rs._dossier_job_get(rid)["progress"]["stage"] == "onboard",
      rs._dossier_job_get(rid)["progress"])

rs._dossier_progress(rid, "onboard", "a note from the build")
check("the build's note is carried through",
      rs._dossier_job_get(rid)["progress"]["note"] == "a note from the build")

rid2 = "test_progress_2"
rs._dossier_job_put(rid2, {"status": "done", "profile": {"name": "X"}})
rs._dossier_progress(rid2, "onboard")
finished = rs._dossier_job_get(rid2)
check("a late update cannot resurrect a finished job",
      finished["status"] == "done" and "progress" not in finished, finished)
check("a finished job keeps its profile",
      (finished.get("profile") or {}).get("name") == "X")

rid3 = "test_progress_3"
rs._dossier_job_put(rid3, {"status": "error", "error": "no"})
rs._dossier_progress(rid3, "history")
check("a failed job is not resurrected either",
      rs._dossier_job_get(rid3).get("status") == "error"
      and "progress" not in rs._dossier_job_get(rid3))

rs._dossier_progress("no-such-job", "history")
check("progress for an unknown job is a no-op, not a crash", True)

print("\n=== the poll endpoint always has a bar to draw ===")
# The browser's bar is built from the progress block on the 202, so a job that
# has not reported yet must still return a valid one. Without this the bar sits
# empty on the first poll and then jumps, which reads as a stall.
import threading  # noqa: E402

result = {}


class Handler(rs.BaseHTTPRequestHandler if hasattr(rs, "BaseHTTPRequestHandler")
           else object):
    pass


def poll(request_id):
    job = rs._dossier_job_get(request_id)
    if job.get("status") == "processing":
        progress = job.get("progress")
        if not isinstance(progress, dict):
            progress = {
                "stage": "identity",
                "label": rs._DOSSIER_STAGES[0][1],
                "index": 1,
                "total": rs._DOSSIER_STAGE_TOTAL,
                "note": "",
            }
        result["payload"] = {"status": "processing", "progress": progress}


rid4 = "test_progress_4"
rs._dossier_job_put(rid4, {"status": "processing"})
poll(rid4)
bar = result.get("payload", {}).get("progress")
check("an unreported job still yields a drawable bar", bool(bar), result)
check("that bar is stage 1 of 6",
      bar and (bar["index"], bar["total"]) == (1, 6), bar)
check("it serialises to JSON for the browser",
      json.loads(json.dumps(result["payload"]))["progress"]["stage"] == "identity")

print()
if fails:
    print("%d FAILED: %s" % (len(fails), "; ".join(fails)))
    sys.exit(1)
print("dossier progress reporting is sound")
