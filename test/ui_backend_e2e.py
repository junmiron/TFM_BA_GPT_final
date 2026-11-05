"""End-to-end check of the FastAPI web backend with a real model run.



Mirrors what the React UI does: POST a task, follow the WebSocket, then verify

the deliverables on disk. Run with SIMULATE_HUMAN=true so the interview is

answered by the simulated stakeholder.

"""

import json

import os

import sys

import time

from pathlib import Path



import httpx

BASE = os.getenv("UI_E2E_BASE", "http://127.0.0.1:8000")

ROOT = Path(__file__).resolve().parent.parent



TASK = (

    "# Laundry Shop Staff App v1\n\n"

    "## 1. Product Overview\nA staff app for laundry shops.\n\n"

    "## 4. Functional Requirements\n| ID | Requirement |\n|----|-------------|\n"

    "| FR-1 | QR tag per order bag |\n| FR-2 | Status lifecycle |\n"

)





def request(client, method, path, **kwargs):

    """HTTP with retry: uvicorn's h11 keep-alive drops idle connections now and then."""

    last = None

    attempts = 5 if method.upper() in {"GET", "HEAD"} else 1

    for attempt in range(attempts):

        try:

            r = client.request(method, f"{BASE}{path}", **kwargs)

            r.raise_for_status()

            return r

        except (httpx.RemoteProtocolError, httpx.ConnectError, httpx.ReadTimeout) as exc:

            last = exc

            print(f"[retry {attempt + 1}] {method} {path}: {type(exc).__name__}", flush=True)

            time.sleep(3)

    raise SystemExit(f"backend unreachable after 5 attempts: {last}")





def main() -> int:

    client = httpx.Client(timeout=30.0)

    print("health:", request(client, "GET", "/api/health").json())



    sid = request(client, "POST", "/api/sessions", json={"task": TASK}).json()["session_id"]

    print("session:", sid)



    seen, d = 0, {}

    while True:

        d = request(client, "GET", f"/api/sessions/{sid}").json()

        events = d.get("events", [])

        if len(events) > seen:

            for e in events[seen:]:

                kind = e["type"]

                if kind in ("message", "info"):

                    text = (e.get("content") or "").strip().replace("\n", " ")

                    print(f"[{kind}] {e.get('source', '')}: {text[:100]}")

                elif kind in ("complete", "error"):

                    print(f"[{kind}] {str(e)[:200]}")

            seen = len(events)

        if d["status"] in ("done", "failed", "stopped"):

            break

        time.sleep(2)



    print("\nfinal status:", d["status"], "messages:", d.get("messages"), "error:", d.get("error"))

    print("stages:", [(s["label"], s["state"]) for s in d["stages"]])

    print("artifacts:", [a["name"] for a in d.get("artifacts", [])])



    sess_dir = ROOT / "conversation" / sid

    ok = True

    import pymupdf as fitz



    pdf = sess_dir / "functional_specification.pdf"

    html = sess_dir / "functional_specification.html"

    md = sess_dir / "functional_specification.md"

    png = sess_dir / "process_diagram.png"



    for f in (md, pdf, html, png):

        exists = f.is_file()

        print(f"{f.name} exists: {exists}")

        ok = ok and exists



    if pdf.is_file():

        doc = fitz.open(str(pdf))

        imgs = sum(len(p.get_images()) for p in doc)

        toc = doc.get_toc()

        raw = sum(1 for marker in ("flowchart TD", "```mermaid", "sequenceDiagram")

                  if any(marker in p.get_text() for p in doc))

        print(f"pdf: pages={doc.page_count} images={imgs} bookmarks={len(toc)} raw_mermaid={raw}")

        ok = ok and doc.page_count > 3 and imgs > 0 and len(toc) > 0 and raw == 0

        doc.close()



    if html.is_file():

        body = html.read_text(encoding="utf-8")

        print(f"html: bytes={len(body)} figures={body.count('<figure')} details={body.count('<details')}")

        ok = ok and "<!DOCTYPE html>" in body



    print("\nRESULT:", "PASS" if ok and d["status"] == "done" else "FAIL")

    return 0 if ok and d["status"] == "done" else 1





if __name__ == "__main__":

    raise SystemExit(main())

