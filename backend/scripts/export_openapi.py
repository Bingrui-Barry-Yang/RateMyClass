"""Write the OpenAPI schema to a file without starting a server: used by `make gen-api`."""

import json
import sys
from pathlib import Path

from app.main import create_app

out = Path(sys.argv[1])
out.write_text(json.dumps(create_app().openapi(), indent=2) + "\n")
print(f"wrote {out}")
