import os

os.environ.setdefault("CATALOG_SOURCE", "excel")

from app.config import get_settings

get_settings.cache_clear()
