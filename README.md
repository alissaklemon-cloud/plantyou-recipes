# PlantYou Recipes

A PlantYou recipe crawler and phone-friendly search prototype.

## Files
- `plantyou_scraper_v2.py` — crawler/parser/analytics
- `scoring_config.json` — convenience-ingredient assumptions
- `app.py` — searchable web interface
- `export_csv.py` — CSV export
- `validate.py` — review report
- `requirements.txt` — Python dependencies

## Local test
```bash
pip install -r requirements.txt
python plantyou_scraper_v2.py --pages 3 --categories 8 --max-recipes 30
python app.py
```

The production deployment will use a persistent database rather than relying on an ephemeral filesystem.
