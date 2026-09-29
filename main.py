import os
from pathlib import Path
import sqlite3
from datetime import datetime

from fastapi import FastAPI, Request
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles

from questions import QUESTIONS

app = FastAPI(title="Business Talks")
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")
DB_FILE = os.getenv("DB_FILE", "data/business_talks.db")
Path(DB_FILE).parent.mkdir(parents=True, exist_ok=True)

def init_db():
    connection = sqlite3.connect(DB_FILE)
    connection.execute("""
        CREATE TABLE IF NOT EXISTS submissions (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            name       TEXT,
            created_at TEXT
        )
    """)
    connection.execute("""
        CREATE TABLE IF NOT EXISTS answers (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            submission_id INTEGER,
            question_id   TEXT,
            value         TEXT
        )
    """)
    connection.commit()
    connection.close()


init_db()


@app.get("/")
def survey(request: Request):
    sections = {}
    for i, q in enumerate(QUESTIONS, start=1):
        sections.setdefault(q["section"], []).append({**q, "number": i})
    return templates.TemplateResponse(
        request, "survey.html",
        {"sections": sections, "total": len(QUESTIONS)},
    )


@app.post("/submit")
async def submit(request: Request):
    form = await request.form()
    name = (form.get("respondent_name") or "").strip() or None

    connection = sqlite3.connect(DB_FILE)
    cursor = connection.cursor()
    cursor.execute(
        "INSERT INTO submissions (name, created_at) VALUES (?, ?)",
        (name, datetime.now().isoformat(timespec="seconds")),
    )
    submission_id = cursor.lastrowid

    for q in QUESTIONS:
        if q["type"] == "multi":
            values = form.getlist(q["id"])                 # every ticked box
        else:
            single = (form.get(q["id"]) or "").strip()
            values = [single] if single else []

        for value in values:
            cursor.execute(
                "INSERT INTO answers (submission_id, question_id, value) VALUES (?, ?, ?)",
                (submission_id, q["id"], value),
            )

    connection.commit()
    connection.close()
    return RedirectResponse(url="/thanks", status_code=303)


@app.get("/results")
def results(request: Request):
    connection = sqlite3.connect(DB_FILE)
    connection.row_factory = sqlite3.Row
    cursor = connection.cursor()

    total_submissions = cursor.execute(
        "SELECT COUNT(*) FROM submissions").fetchone()[0]

    sections = {}
    for i, q in enumerate(QUESTIONS, start=1):
        rows = cursor.execute(
            """
            SELECT a.value AS value, s.name AS name
            FROM answers a
            JOIN submissions s ON s.id = a.submission_id
            WHERE a.question_id = ?
            """,
            (q["id"],),
        ).fetchall()

        if q["type"] in ("single", "multi"):
            counts = {}
            for row in rows:
                counts[row["value"]] = counts.get(row["value"], 0) + 1
            total_votes = sum(counts.values())
            tallies = []
            for option, count in sorted(counts.items(), key=lambda kv: kv[1], reverse=True):
                pct = round(100 * count / total_votes) if total_votes else 0
                tallies.append({"option": option, "count": count, "pct": pct})
            item = {"question": q, "number": i, "kind": "poll",
                    "tallies": tallies, "total_votes": total_votes}
        else:
            responses = [{"text": row["value"], "name": row["name"] or "Anonymous"}
                         for row in rows]
            item = {"question": q, "number": i,
                    "kind": "text", "responses": responses}

        sections.setdefault(q["section"], []).append(item)

    connection.close()
    return templates.TemplateResponse(
        request, "results.html",
        {"sections": sections, "total_submissions": total_submissions},
    )


@app.get("/thanks")
def thanks(request: Request):
    return templates.TemplateResponse(request, "thanks.html", {})
