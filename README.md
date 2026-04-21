# lit-metrics

Static dashboard fed by daily GitHub Action.

## Local

```
pip install -r requirements.txt
python extract.py --month 2026-04
python -m http.server 8000
```

Open http://localhost:8000
