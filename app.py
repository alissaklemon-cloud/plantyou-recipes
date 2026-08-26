
"""
Optional lightweight API/UI starter for the PlantYou SQLite database.

Run:
  pip install flask
  python app.py

Then open the displayed local URL in a browser.

This is a phone-friendly prototype. It searches the local database and exposes
recipe details plus practical analytics.
"""
from flask import Flask, request, render_template_string
import sqlite3, json, os

app = Flask(__name__)
DB = os.environ.get("PLANTYOU_DB", "plantyou.db")

INDEX = """
<!doctype html>
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>PlantYou Practical Recipes</title>
<style>
body{font-family:-apple-system,BlinkMacSystemFont,sans-serif;max-width:900px;margin:auto;padding:18px;background:#fafafa;color:#222}
input,select{font-size:16px;padding:10px;border:1px solid #ccc;border-radius:8px}
button{font-size:16px;padding:10px 14px;border:0;border-radius:8px}
.card{background:white;padding:16px;margin:12px 0;border-radius:12px;box-shadow:0 1px 5px #ddd}
a{text-decoration:none;color:inherit}.muted{color:#666}.pill{display:inline-block;background:#eee;padding:4px 8px;border-radius:12px;margin:2px;font-size:13px}
</style>
<h1>PlantYou Recipes</h1>
<form>
<input name="q" value="{{q}}" placeholder="Search ingredients or recipe">
<select name="maxprep"><option value="">Any prep</option>{% for x in [5,10,15,20,30] %}<option value="{{x}}" {% if maxprep==x|string %}selected{% endif %}>≤ {{x}} min prep</option>{% endfor %}</select>
<select name="maxmess"><option value="">Any mess</option>{% for x in [1,2,3,4,5] %}<option value="{{x}}" {% if maxmess==x|string %}selected{% endif %}>Mess ≤ {{x}}/5</option>{% endfor %}</select>
<button>Search</button>
</form>
{% for r in rows %}
<a href="/recipe/{{r.recipe_id}}"><div class="card">
<h2>{{r.name}}</h2>
<div class="muted">{{r.total_minutes or "?"}} min published · practical {{r.practical_prep_min}}–{{r.practical_prep_max}} min</div>
<p><span class="pill">Prep {{r.prep_effort}}/5</span><span class="pill">Mess {{r.mess}}/5</span><span class="pill">Cleanup {{r.cleanup_burden}}/5</span><span class="pill">Weeknight {{r.weeknight_friendliness}}/5</span></p>
</div></a>
{% endfor %}
"""

DETAIL = """
<!doctype html>
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{{r.name}}</title>
<style>
body{font-family:-apple-system,BlinkMacSystemFont,sans-serif;max-width:800px;margin:auto;padding:18px}
.card{padding:16px;background:#f6f6f6;border-radius:12px;margin:14px 0}
li{margin:8px 0}.pill{display:inline-block;background:#eee;padding:5px 8px;border-radius:12px;margin:3px}
</style>
<a href="/">← Back</a>
<h1>{{r.name}}</h1>
<p>{{r.description or ""}}</p>
<div class="card">
<b>Practical analysis</b><br>
Practical prep: {{r.practical_prep_min}}–{{r.practical_prep_max}} min<br>
Hands-on: {{r.hands_on_min}}–{{r.hands_on_max}} min<br>
Passive: {{r.passive_min}}–{{r.passive_max}} min<br>
Cleanup: {{r.cleanup_min}}–{{r.cleanup_max}} min<br><br>
<span class="pill">Prep {{r.prep_effort}}/5</span>
<span class="pill">Mess {{r.mess}}/5</span>
<span class="pill">Cleanup {{r.cleanup_burden}}/5</span>
<span class="pill">Weeknight {{r.weeknight_friendliness}}/5</span>
<span class="pill">{{r.dirty_dish_estimate}} dishes</span>
</div>
{% if assumptions %}<div class="card"><b>Convenience assumptions</b><ul>{% for x in assumptions %}<li>{{x}}</li>{% endfor %}</ul></div>{% endif %}
<h2>Ingredients</h2><ul>{% for x in ingredients %}<li>{{x.original_text}}</li>{% endfor %}</ul>
<h2>Instructions</h2><ol>{% for x in instructions %}<li>{{x.step}}</li>{% endfor %}</ol>
"""

SCHEMA = """
CREATE TABLE IF NOT EXISTS recipes(
 recipe_id INTEGER PRIMARY KEY,
 name TEXT NOT NULL, url TEXT UNIQUE NOT NULL, description TEXT, author TEXT,
 servings INTEGER, prep_minutes INTEGER, cook_minutes INTEGER, total_minutes INTEGER,
 image_url TEXT, date_published TEXT, date_modified TEXT, rating REAL, rating_count INTEGER,
 keywords TEXT, categories TEXT, cuisine TEXT, raw_json TEXT, parser_warnings TEXT,
 scraped_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS ingredients(
 ingredient_id INTEGER PRIMARY KEY,
 recipe_id INTEGER NOT NULL, position INTEGER NOT NULL,
 original_text TEXT NOT NULL, quantity REAL, unit TEXT, ingredient TEXT, preparation TEXT,
 convenience_replacement TEXT
);
CREATE TABLE IF NOT EXISTS instructions(
 instruction_id INTEGER PRIMARY KEY,
 recipe_id INTEGER NOT NULL, position INTEGER NOT NULL, step TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS analysis(
 recipe_id INTEGER PRIMARY KEY,
 practical_prep_min INTEGER, practical_prep_max INTEGER,
 hands_on_min INTEGER, hands_on_max INTEGER,
 passive_min INTEGER, passive_max INTEGER,
 cleanup_min INTEGER, cleanup_max INTEGER,
 prep_effort REAL, mess REAL, cleanup_burden REAL,
 weeknight_friendliness REAL, dirty_dish_estimate INTEGER,
 convenience_assumptions TEXT, reasons TEXT, confidence REAL, warnings TEXT
);
"""

def conn():
    c = sqlite3.connect(DB)
    c.row_factory = sqlite3.Row
    c.executescript(SCHEMA)
    return c
    
@app.route("/")
def index():
    q=request.args.get("q","").strip()
    maxprep=request.args.get("maxprep","")
    maxmess=request.args.get("maxmess","")
    sql="""SELECT r.recipe_id,r.name,r.total_minutes,a.* FROM recipes r JOIN analysis a ON a.recipe_id=r.recipe_id WHERE 1=1"""
    params=[]
    if q:
        sql += """ AND (lower(r.name) LIKE ? OR r.recipe_id IN
                    (SELECT recipe_id FROM ingredients WHERE lower(original_text) LIKE ?))"""
        params += [f"%{q.lower()}%",f"%{q.lower()}%"]
    if maxprep.isdigit():
        sql += " AND a.practical_prep_min <= ?"; params.append(int(maxprep))
    if maxmess.isdigit():
        sql += " AND a.mess <= ?"; params.append(int(maxmess))
    sql += " ORDER BY a.weeknight_friendliness DESC,a.practical_prep_min ASC LIMIT 100"
    rows=conn().execute(sql,params).fetchall()
    return render_template_string(INDEX,rows=rows,q=q,maxprep=maxprep,maxmess=maxmess)

@app.route("/recipe/<int:rid>")
def recipe(rid):
    c=conn()
    r=c.execute("""SELECT r.*,a.* FROM recipes r JOIN analysis a ON r.recipe_id=a.recipe_id
                   WHERE r.recipe_id=?""",(rid,)).fetchone()
    if not r: return "Not found",404
    ingredients=c.execute("SELECT * FROM ingredients WHERE recipe_id=? ORDER BY position",(rid,)).fetchall()
    instructions=c.execute("SELECT * FROM instructions WHERE recipe_id=? ORDER BY position",(rid,)).fetchall()
    assumptions=json.loads(r["convenience_assumptions"] or "[]")
    return render_template_string(DETAIL,r=r,ingredients=ingredients,instructions=instructions,assumptions=assumptions)

if __name__=="__main__":
    app.run(debug=True)
