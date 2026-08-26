
import sqlite3, csv, json, sys

db = sys.argv[1] if len(sys.argv)>1 else "plantyou.db"
out = sys.argv[2] if len(sys.argv)>2 else "plantyou_recipes.csv"

con=sqlite3.connect(db); con.row_factory=sqlite3.Row
rows=con.execute("""
SELECT r.recipe_id,r.name,r.url,r.servings,r.prep_minutes,r.cook_minutes,r.total_minutes,
       a.practical_prep_min,a.practical_prep_max,a.hands_on_min,a.hands_on_max,
       a.passive_min,a.passive_max,a.cleanup_min,a.cleanup_max,a.prep_effort,a.mess,
       a.cleanup_burden,a.weeknight_friendliness,a.dirty_dish_estimate,
       a.convenience_assumptions,a.reasons,a.warnings
FROM recipes r JOIN analysis a ON r.recipe_id=a.recipe_id
ORDER BY a.weeknight_friendliness DESC,a.practical_prep_min
""").fetchall()
with open(out,"w",newline="",encoding="utf-8") as f:
    w=csv.writer(f); w.writerow(rows[0].keys() if rows else [])
    for r in rows: w.writerow([r[k] for k in r.keys()])
print(f"Wrote {len(rows)} recipes to {out}")
