
import sqlite3, sys, json

db=sys.argv[1] if len(sys.argv)>1 else "plantyou.db"
c=sqlite3.connect(db); c.row_factory=sqlite3.Row
rows=c.execute("""
SELECT r.recipe_id,r.name,r.url,r.prep_minutes,r.cook_minutes,r.total_minutes,
       r.parser_warnings,a.*
FROM recipes r LEFT JOIN analysis a ON r.recipe_id=a.recipe_id
WHERE r.prep_minutes IS NULL OR r.cook_minutes IS NULL OR r.total_minutes IS NULL
   OR r.parser_warnings != '[]' OR a.confidence < .7
ORDER BY r.name
""").fetchall()

print(f"{len(rows)} recipes need review.")
for r in rows:
    print("\n",r["name"])
    print(" URL:",r["url"])
    print(" published:",r["prep_minutes"],r["cook_minutes"],r["total_minutes"])
    print(" warnings:",r["parser_warnings"])
    print(" confidence:",r["confidence"])
