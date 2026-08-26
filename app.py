from flask import Flask, request, render_template_string
import sqlite3
import json
import os

app = Flask(__name__)
DB = os.environ.get("PLANTYOU_DB", "plantyou.db")

SCHEMA = """
CREATE TABLE IF NOT EXISTS recipes (
    recipe_id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    url TEXT UNIQUE NOT NULL,
    description TEXT,
    author TEXT,
    servings INTEGER,
    prep_minutes INTEGER,
    cook_minutes INTEGER,
    total_minutes INTEGER,
    image_url TEXT,
    date_published TEXT,
    date_modified TEXT,
    rating REAL,
    rating_count INTEGER,
    keywords TEXT,
    categories TEXT,
    cuisine TEXT,
    raw_json TEXT,
    parser_warnings TEXT,
    scraped_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS ingredients (
    ingredient_id INTEGER PRIMARY KEY,
    recipe_id INTEGER NOT NULL,
    position INTEGER NOT NULL,
    original_text TEXT NOT NULL,
    quantity REAL,
    unit TEXT,
    ingredient TEXT,
    preparation TEXT,
    convenience_replacement TEXT
);

CREATE TABLE IF NOT EXISTS instructions (
    instruction_id INTEGER PRIMARY KEY,
    recipe_id INTEGER NOT NULL,
    position INTEGER NOT NULL,
    step TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS analysis (
    recipe_id INTEGER PRIMARY KEY,
    practical_prep_min INTEGER,
    practical_prep_max INTEGER,
    hands_on_min INTEGER,
    hands_on_max INTEGER,
    passive_min INTEGER,
    passive_max INTEGER,
    cleanup_min INTEGER,
    cleanup_max INTEGER,
    prep_effort REAL,
    mess REAL,
    cleanup_burden REAL,
    weeknight_friendliness REAL,
    dirty_dish_estimate INTEGER,
    convenience_assumptions TEXT,
    reasons TEXT,
    confidence REAL,
    warnings TEXT
);
"""

def conn():
    c = sqlite3.connect(DB)
    c.row_factory = sqlite3.Row
    c.executescript(SCHEMA)
    return c

@app.route("/")
def index():
    q = request.args.get("q", "").strip()
    maxprep = request.args.get("maxprep", "")
    maxmess = request.args.get("maxmess", "")

    c = conn()

    sql = """
        SELECT r.recipe_id, r.name, r.total_minutes, a.*
        FROM recipes r
        JOIN analysis a ON a.recipe_id = r.recipe_id
        WHERE 1=1
    """
    params = []

    if q:
        sql += """
            AND (
                lower(r.name) LIKE ?
                OR r.recipe_id IN (
                    SELECT recipe_id
                    FROM ingredients
                    WHERE lower(original_text) LIKE ?
                )
            )
        """
        params += [f"%{q.lower()}%", f"%{q.lower()}%"]

    if maxprep.isdigit():
        sql += " AND a.practical_prep_min <= ?"
        params.append(int(maxprep))

    if maxmess.isdigit():
        sql += " AND a.mess <= ?"
        params.append(int(maxmess))

    sql += """
        ORDER BY
            a.weeknight_friendliness DESC,
            a.practical_prep_min ASC
        LIMIT 100
    """

    rows = c.execute(sql, params).fetchall()
    c.close()

    html = """
    <!doctype html>
    <meta name="viewport" content="width=device-width,initial-scale=1">

    <title>PlantYou Practical Recipes</title>

    <style>
    body {
        font-family: -apple-system, BlinkMacSystemFont, sans-serif;
        max-width: 900px;
        margin: auto;
        padding: 18px;
        background: #fafafa;
        color: #222;
    }

    input, select {
        font-size: 16px;
        padding: 10px;
        border: 1px solid #ccc;
        border-radius: 8px;
        margin-bottom: 8px;
    }

    button {
        font-size: 16px;
        padding: 10px 14px;
        border: 0;
        border-radius: 8px;
    }

    .card {
        background: white;
        padding: 16px;
        margin: 12px 0;
        border-radius: 12px;
        box-shadow: 0 1px 5px #ddd;
    }

    a {
        text-decoration: none;
        color: inherit;
    }

    .muted {
        color: #666;
    }

    .pill {
        display: inline-block;
        background: #eee;
        padding: 4px 8px;
        border-radius: 12px;
        margin: 2px;
        font-size: 13px;
    }
    </style>

    <h1>PlantYou Recipes</h1>

    <form>
        <input
            name="q"
            value="{{ q }}"
            placeholder="Search ingredients or recipe"
        >

        <select name="maxprep">
            <option value="">Any prep</option>
            {% for x in [5,10,15,20,30] %}
            <option value="{{x}}">
                ≤ {{x}} min prep
            </option>
            {% endfor %}
        </select>

        <select name="maxmess">
            <option value="">Any mess</option>
            {% for x in [1,2,3,4,5] %}
            <option value="{{x}}">
                Mess ≤ {{x}}/5
            </option>
            {% endfor %}
        </select>

        <button>Search</button>
    </form>

    {% if not rows %}
    <div class="card">
        <h2>No recipes loaded yet</h2>
        <p>
            The website is working, but we haven't loaded the PlantYou
            recipes yet.
        </p>
    </div>
    {% endif %}

    {% for r in rows %}
    <a href="/recipe/{{r.recipe_id}}">
        <div class="card">
            <h2>{{r.name}}</h2>

            <div class="muted">
                {{r.total_minutes or "?"}} min published ·
                practical {{r.practical_prep_min}}–{{r.practical_prep_max}} min
            </div>

            <p>
                <span class="pill">
                    Prep {{r.prep_effort}}/5
                </span>

                <span class="pill">
                    Mess {{r.mess}}/5
                </span>

                <span class="pill">
                    Cleanup {{r.cleanup_burden}}/5
                </span>

                <span class="pill">
                    Weeknight {{r.weeknight_friendliness}}/5
                </span>
            </p>
        </div>
    </a>
    {% endfor %}
    """

    return render_template_string(
        html,
        rows=rows,
        q=q,
        maxprep=maxprep,
        maxmess=maxmess
    )

@app.route("/health")
def health():
    return "ok", 200

if __name__ == "__main__":
    app.run(
        host="0.0.0.0",
        port=int(os.environ.get("PORT", 5000))
    )