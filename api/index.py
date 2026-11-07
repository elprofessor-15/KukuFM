from __future__ import annotations

import os
import shutil
import tempfile
import zipfile
from pathlib import Path

from fastapi import FastAPI, File, UploadFile
from fastapi.responses import JSONResponse

from promofinder.pipeline import run_pipeline
from promofinder.upload import extract_episode_zip

app = FastAPI(title="KukuFM PromoFinder API", docs_url=None, redoc_url=None)


@app.get("/api/health")
def health():
    keys = sum(bool(os.getenv(name)) for name in ("GROQ_API_KEY", "GROQ_API_KEY2", "GROQ_API_KEY3"))
    return {"status": "ok", "service": "KukuFM PromoFinder", "groq_keys_configured": keys}


@app.post("/api/run")
async def run(file: UploadFile = File(...), heuristics_only: bool = False):
    if not file.filename.lower().endswith(".zip"):
        return JSONResponse(status_code=400, content={"error": "Upload a ZIP containing screenplay episode files."})

    workspace = Path(tempfile.mkdtemp(prefix="kukufm-"))
    zip_path = workspace / "episodes.zip"
    try:
        content = await file.read()
        if not content:
            return JSONResponse(status_code=400, content={"error": "The uploaded file is empty."})
        if len(content) > 50 * 1024 * 1024:
            return JSONResponse(status_code=413, content={"error": "The ZIP must be smaller than 50 MB."})
        zip_path.write_bytes(content)

        try:
            with zipfile.ZipFile(zip_path) as archive:
                archive.testzip()
            data_dir = extract_episode_zip(content)
        except (zipfile.BadZipFile, ValueError) as exc:
            return JSONResponse(status_code=400, content={"error": str(exc)})

        output_dir = workspace / "outputs"
        outcome = run_pipeline(
            data_dir,
            output=output_dir,
            heuristics_only=heuristics_only,
        )
        return {
            "report": outcome["report"],
            "promos": outcome["promos"],
            "episodes_parsed": outcome["report"]["episodes_parsed"],
        }
    except Exception as exc:
        return JSONResponse(
            status_code=500,
            content={"error": "Analysis could not be completed.", "type": type(exc).__name__},
        )
    finally:
        shutil.rmtree(workspace, ignore_errors=True)
