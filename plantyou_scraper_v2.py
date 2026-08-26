
#!/usr/bin/env python3
"""PlantYou crawler v2.

Features:
- discovers recipe URLs from All Recipes pagination AND category pages
- respects a configurable request delay
- parses Schema.org Recipe JSON-LD
- stores original recipe data
- normalizes common ingredient quantities/units
- applies configurable convenience substitutions
- estimates practical prep, hands-on time, passive time, cleanup,
  mess, dirty dishes, and weeknight friendliness
- flags missing/ambiguous source data
- incremental SQLite storage
"""

import argparse, json, re, sqlite3, time
from datetime import datetime, timezone
from fractions import Fraction
from urllib.parse import urljoin, urlparse
import requests
from bs4 import BeautifulSoup

BASE = "https://plantyou.com/"
ALL_RECIPES = "https://plantyou.com/category/all-recipes/"
CATEGORY_INDEX = "https://plantyou.com/recipes/"

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
 ingredient_id INTEGER PRIMARY KEY, recipe_id INTEGER NOT NULL, position INTEGER NOT NULL,
 original_text TEXT NOT NULL, quantity REAL, unit TEXT, ingredient TEXT, preparation TEXT,
 convenience_replacement TEXT, FOREIGN KEY(recipe_id) REFERENCES recipes(recipe_id)
);
CREATE TABLE IF NOT EXISTS instructions(
 instruction_id INTEGER PRIMARY KEY, recipe_id INTEGER NOT NULL, position INTEGER NOT NULL,
 step TEXT NOT NULL, FOREIGN KEY(recipe_id) REFERENCES recipes(recipe_id)
);
CREATE TABLE IF NOT EXISTS analysis(
 recipe_id INTEGER PRIMARY KEY, practical_prep_min INTEGER, practical_prep_max INTEGER,
 hands_on_min INTEGER, hands_on_max INTEGER, passive_min INTEGER, passive_max INTEGER,
 cleanup_min INTEGER, cleanup_max INTEGER, prep_effort REAL, mess REAL,
 cleanup_burden REAL, weeknight_friendliness REAL, dirty_dish_estimate INTEGER,
 convenience_assumptions TEXT, reasons TEXT, confidence REAL, warnings TEXT,
 FOREIGN KEY(recipe_id) REFERENCES recipes(recipe_id)
);
CREATE TABLE IF NOT EXISTS crawl_log(
 url TEXT PRIMARY KEY, status TEXT, http_status INTEGER, error TEXT, crawled_at TEXT
);
"""

UNIT_MAP = {
    "cups":"cup","cup":"cup","tbsp":"tbsp","tablespoon":"tbsp","tablespoons":"tbsp",
    "tsp":"tsp","teaspoon":"tsp","teaspoons":"tsp","oz":"oz","ounce":"oz","ounces":"oz",
    "lb":"lb","lbs":"lb","pound":"lb","pounds":"lb","cloves":"clove","clove":"clove"
}
NUM = {"½":0.5,"⅓":1/3,"⅔":2/3,"¼":0.25,"¾":0.75,"⅛":0.125,"⅜":0.375,"⅝":0.625,"⅞":0.875}

def parse_num(s):
    s=s.strip()
    if s in NUM: return NUM[s]
    if re.fullmatch(r"\d+\s+\d+/\d+",s):
        a,b=s.split(); n,d=b.split("/"); return int(a)+int(n)/int(d)
    if re.fullmatch(r"\d+/\d+",s):
        n,d=s.split("/"); return int(n)/int(d)
    try: return float(s)
    except: return None

def normalize_ingredient(text):
    original=text.strip()
    s=original.lower().replace("–","-").replace("—","-")
    qty=None; unit=None
    m=re.match(r"^\s*(\d+(?:\.\d+)?(?:\s+\d+/\d+)?|\d+/\d+|[½⅓⅔¼¾⅛⅜⅝⅞])\s*",s)
    if m:
        qty=parse_num(m.group(1)); s=s[m.end():].strip()
    for u in sorted(UNIT_MAP, key=len, reverse=True):
        m=re.match(rf"^{re.escape(u)}\b",s)
        if m:
            unit=UNIT_MAP[u]; s=s[m.end():].strip(); break
    s=re.sub(r"^\s*(of|the)\s+","",s)
    preparation=None
    p=re.search(r",\s*(.+)$",s)
    if p:
        preparation=p.group(1).strip()
        ingredient=s[:p.start()].strip()
    else:
        ingredient=s
    return qty, unit, ingredient, preparation

def walk_json(x):
    if isinstance(x,dict):
        yield x
        for v in x.values(): yield from walk_json(v)
    elif isinstance(x,list):
        for v in x: yield from walk_json(v)

def json_recipe(soup):
    for tag in soup.find_all("script", type="application/ld+json"):
        try: data=json.loads(tag.string or tag.get_text())
        except Exception: continue
        for obj in walk_json(data):
            typ=obj.get("@type",[])
            if isinstance(typ,str): typ=[typ]
            if "Recipe" in typ: return obj
    return None

def mins(x):
    if not x: return None
    if isinstance(x,(int,float)): return int(x)
    m=re.match(r"P(?:(\d+)D)?(?:T(?:(\d+)H)?(?:(\d+)M)?)?",str(x))
    if not m: return None
    d,h,mi=m.groups()
    return int(d or 0)*1440+int(h or 0)*60+int(mi or 0)

def yield_num(x):
    if x is None:return None
    m=re.search(r"\d+",str(x))
    return int(m.group()) if m else None

def recipe_links(html, base):
    soup=BeautifulSoup(html,"html.parser"); out=set()
    for a in soup.find_all("a",href=True):
        u=urljoin(base,a["href"]).split("#")[0].rstrip("/")
        p=urlparse(u)
        if p.netloc not in ("plantyou.com","www.plantyou.com"): continue
        path=p.path.rstrip("/")
        if path in ("","/recipes") or path.startswith("/category/") or "/page/" in path: continue
        if any(z in path for z in ("/author/","/tag/","/shop/","/wp-content/")): continue
        if path.count("/")>=1: out.add(u)
    return out

def category_links(html):
    soup=BeautifulSoup(html,"html.parser"); out=set()
    for a in soup.find_all("a",href=True):
        u=urljoin(CATEGORY_INDEX,a["href"]).rstrip("/")
        if urlparse(u).netloc not in ("plantyou.com","www.plantyou.com"): continue
        if "/category/" in urlparse(u).path: out.add(u)
    return out

def get(session,url,delay):
    r=session.get(url,timeout=30)
    time.sleep(delay)
    return r

def discover(session,pages,categories,delay):
    urls=set()
    for page in range(1,pages+1):
        u=ALL_RECIPES if page==1 else f"{ALL_RECIPES.rstrip('/')}/page/{page}/"
        r=get(session,u,delay); r.raise_for_status(); urls |= recipe_links(r.text,u)
    r=get(session,CATEGORY_INDEX,delay); r.raise_for_status()
    cats=list(category_links(r.text))[:categories]
    for cat in cats:
        for page in range(1,4):
            u=cat if page==1 else f"{cat}/page/{page}/"
            try:
                rr=get(session,u,delay); rr.raise_for_status(); urls |= recipe_links(rr.text,u)
            except Exception: break
    return sorted(urls)

def parse_recipe(url,html):
    soup=BeautifulSoup(html,"html.parser"); d=json_recipe(soup); warnings=[]
    if not d: warnings.append("No Recipe JSON-LD.")
    d=d or {}
    inst=[]
    for x in d.get("recipeInstructions",[]) or []:
        if isinstance(x,str): inst.append(x.strip())
        elif isinstance(x,dict) and x.get("text"): inst.append(str(x["text"]).strip())
    image=d.get("image")
    if isinstance(image,list): image=image[0] if image else None
    author=d.get("author")
    if isinstance(author,dict): author=author.get("name")
    rating=d.get("aggregateRating") or {}
    return {
      "name":d.get("name") or (soup.title.get_text(" ",strip=True) if soup.title else url),
      "url":url,"description":d.get("description"),"author":author,
      "servings":yield_num(d.get("recipeYield")),"prep_minutes":mins(d.get("prepTime")),
      "cook_minutes":mins(d.get("cookTime")),"total_minutes":mins(d.get("totalTime")),
      "image_url":image,"date_published":d.get("datePublished"),"date_modified":d.get("dateModified"),
      "rating":rating.get("ratingValue") if isinstance(rating,dict) else None,
      "rating_count":rating.get("ratingCount") if isinstance(rating,dict) else None,
      "keywords":d.get("keywords"),"categories":d.get("recipeCategory") or [],
      "cuisine":d.get("recipeCuisine"),"ingredients":d.get("recipeIngredient") or [],
      "instructions":inst,"raw_json":d,"warnings":warnings
    }

def analyze(recipe,config):
    text=(" ".join(recipe["ingredients"])+" "+" ".join(recipe["instructions"])).lower()
    saved=0; assumptions=[]
    for rule in config["convenience_rules"]:
        if rule["match"] in text:
            saved += rule["minutes_saved"]; assumptions.append(rule["replacement"])
    base=recipe["prep_minutes"] if recipe["prep_minutes"] is not None else 10
    practical=max(2,round(base-saved))
    labor=sum(len(re.findall(rf"\b{re.escape(w)}\b",text)) for w in
              ["peel","dice","chop","mince","slice","shred","grate","julienne","roll","fold","stuff","bread","coat"])
    assembly=sum(len(re.findall(rf"\b{re.escape(w)}\b",text)) for w in ["roll","fold","stuff","layer","fill","assemble"])
    effort=min(5,max(1,round(1+labor*.25+assembly*.6,1)))
    mess=1
    if len(recipe["ingredients"])>12: mess+=.4
    for w in ["fry","deep fry","bread","batter","food processor","blender","stand mixer","marinate"]:
        mess += .35*len(re.findall(rf"\b{re.escape(w)}\b",text))
    if any(w in text for w in ["one pan","one pot","sheet pan"]): mess-=.4
    mess=round(min(5,max(1,mess)),1)
    dishes=1
    for w in ["bowl","food processor","blender","skillet","saucepan","pot","sheet pan"]:
        if w in text: dishes+=1
    dishes=min(6,dishes)
    cleanup=round(3+(dishes-1)*2+max(0,mess-2)*1.5)
    cook=recipe["cook_minutes"] or 0
    hands=max(2,round(practical*.65))
    week=round(min(5,max(1,6-practical/20-hands/30-mess/3-(.7 if (recipe["total_minutes"] or 0)>60 else 0))),1)
    reasons=[]
    if assumptions: reasons.append("Convenience substitutions reduce active prep.")
    if labor: reasons.append(f"{labor} labor-intensive prep actions detected.")
    if assembly: reasons.append(f"{assembly} assembly actions detected.")
    return {
      "practical_prep_min":practical,"practical_prep_max":practical+4,
      "hands_on_min":hands,"hands_on_max":hands+4,
      "passive_min":max(0,cook-hands),"passive_max":max(0,cook-hands+5),
      "cleanup_min":int(cleanup),"cleanup_max":int(cleanup+4),
      "prep_effort":effort,"mess":mess,
      "cleanup_burden":round(min(5,max(1,mess+(dishes-1)*.35)),1),
      "weeknight_friendliness":week,"dirty_dish_estimate":dishes,
      "convenience_assumptions":sorted(set(assumptions)),"reasons":reasons,
      "confidence":.85 if recipe["raw_json"] else .45,"warnings":recipe["warnings"]
    }

def save(conn,r,a):
    c=conn.cursor()
    c.execute("""INSERT INTO recipes(name,url,description,author,servings,prep_minutes,cook_minutes,total_minutes,
    image_url,date_published,date_modified,rating,rating_count,keywords,categories,cuisine,raw_json,parser_warnings,scraped_at)
    VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(url) DO UPDATE SET
    name=excluded.name,description=excluded.description,author=excluded.author,servings=excluded.servings,
    prep_minutes=excluded.prep_minutes,cook_minutes=excluded.cook_minutes,total_minutes=excluded.total_minutes,
    image_url=excluded.image_url,date_modified=excluded.date_modified,raw_json=excluded.raw_json,
    parser_warnings=excluded.parser_warnings,scraped_at=excluded.scraped_at""",
    (r["name"],r["url"],r["description"],r["author"],r["servings"],r["prep_minutes"],r["cook_minutes"],r["total_minutes"],
     r["image_url"],r["date_published"],r["date_modified"],r["rating"],r["rating_count"],json.dumps(r["keywords"]),
     json.dumps(r["categories"]),json.dumps(r["cuisine"]),json.dumps(r["raw_json"]),
     datetime.now(timezone.utc).isoformat()))
    rid=c.execute("SELECT recipe_id FROM recipes WHERE url=?",(r["url"],)).fetchone()[0]
    c.execute("DELETE FROM ingredients WHERE recipe_id=?",(rid,))
    for i,x in enumerate(r["ingredients"],1):
        q,u,ing,prep=normalize_ingredient(str(x))
        c.execute("""INSERT INTO ingredients(recipe_id,position,original_text,quantity,unit,ingredient,preparation,convenience_replacement)
                     VALUES(?,?,?,?,?,?,?,?)""",(rid,i,str(x),q,u,ing,prep,None))
    c.execute("DELETE FROM instructions WHERE recipe_id=?",(rid,))
    for i,x in enumerate(r["instructions"],1): c.execute("INSERT INTO instructions(recipe_id,position,step) VALUES(?,?,?)",(rid,i,x))
    c.execute("""INSERT INTO analysis VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
    ON CONFLICT(recipe_id) DO UPDATE SET practical_prep_min=excluded.practical_prep_min,practical_prep_max=excluded.practical_prep_max,
    hands_on_min=excluded.hands_on_min,hands_on_max=excluded.hands_on_max,passive_min=excluded.passive_min,passive_max=excluded.passive_max,
    cleanup_min=excluded.cleanup_min,cleanup_max=excluded.cleanup_max,prep_effort=excluded.prep_effort,mess=excluded.mess,
    cleanup_burden=excluded.cleanup_burden,weeknight_friendliness=excluded.weeknight_friendliness,
    dirty_dish_estimate=excluded.dirty_dish_estimate,convenience_assumptions=excluded.convenience_assumptions,
    reasons=excluded.reasons,confidence=excluded.confidence,warnings=excluded.warnings""",
    (rid,a["practical_prep_min"],a["practical_prep_max"],a["hands_on_min"],a["hands_on_max"],a["passive_min"],a["passive_max"],
     a["cleanup_min"],a["cleanup_max"],a["prep_effort"],a["mess"],a["cleanup_burden"],a["weeknight_friendliness"],
     a["dirty_dish_estimate"],json.dumps(a["convenience_assumptions"]),json.dumps(a["reasons"]),a["confidence"],json.dumps(a["warnings"])))
    conn.commit()

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--pages",type=int,default=3)
    ap.add_argument("--categories",type=int,default=8)
    ap.add_argument("--max-recipes",type=int,default=30)
    ap.add_argument("--delay",type=float,default=1.0)
    ap.add_argument("--db",default="plantyou.db")
    ap.add_argument("--config",default="scoring_config.json")
    args=ap.parse_args()
    cfg=json.load(open(args.config))
    s=requests.Session(); s.headers["User-Agent"]=cfg.get("user_agent","PlantYouRecipeResearch/1.0")
    urls=discover(s,args.pages,args.categories,args.delay)
    conn=sqlite3.connect(args.db); conn.executescript(SCHEMA)
    print(f"Discovered {len(urls)} unique candidate URLs.")
    saved=0
    for i,u in enumerate(urls,1):
        if saved >= args.max_recipes:
            break
        try:
            r=get(s,u,args.delay); r.raise_for_status()
            rec=parse_recipe(u,r.text)
            if not rec.get("raw_json"):
              print(f"{i:03}/{len(urls)} SKIP non-recipe page {u}")
              continue
            a=analyze(rec,cfg); save(conn,rec,a)
            saved += 1
            print(f"{saved:03}/{args.max_recipes} {rec['name']} | prep {a['practical_prep_min']}-{a['practical_prep_max']}m | mess {a['mess']}/5")        except Exception as e:
            print(f"{i:03}/{len(urls)} ERROR {u}: {e}")
    conn.close()

if __name__=="__main__": main()
