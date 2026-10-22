"""Regenera entrega-3/swagger-api-nacional.json desde la app (con la URL pública de Render como servidor).

    python scripts/exportar_openapi.py
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.main import app  # noqa: E402

DESTINO = Path(__file__).resolve().parents[2] / "entrega-3" / "swagger-api-nacional.json"
SERVIDOR = {"url": "https://rescuesync-nacional.onrender.com", "description": "API en la nube (Render)"}

if __name__ == "__main__":
    documento = {**app.openapi(), "servers": [SERVIDOR]}
    DESTINO.write_text(json.dumps(documento, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"{DESTINO}: {len(documento['paths'])} paths")
