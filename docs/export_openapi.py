"""Export OpenAPI spec from FastAPI app."""
import json
import sys
import os

# Ensure project root is on the path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.main import create_app

app = create_app()
spec = app.openapi()

output_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "openapi.json")
with open(output_path, "w", encoding="utf-8") as f:
    json.dump(spec, f, indent=2, ensure_ascii=False)

print(f"Exported OpenAPI spec: {len(spec['paths'])} paths → {output_path}")
