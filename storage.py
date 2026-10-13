"""Where uploaded photos and videos live.

With SUPABASE_URL and SUPABASE_SERVICE_KEY set, uploads go to a public Supabase Storage
bucket (SUPABASE_BUCKET, default "uploads"), so they survive redeploys. Without them,
files are saved under static/uploads for local trials.
The sample photos (seed-*) always ship with the app in static/uploads.
"""
import mimetypes
import os
import urllib.request
from urllib.parse import quote

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
LOCAL_DIR = os.path.join(BASE_DIR, "static", "uploads")


def _supabase():
    url = os.environ.get("SUPABASE_URL", "").rstrip("/")
    key = os.environ.get("SUPABASE_SERVICE_KEY", "")
    bucket = os.environ.get("SUPABASE_BUCKET", "uploads")
    return (url, key, bucket) if url and key else None


def save(file_storage, name):
    """Store an uploaded file under `name`."""
    sb = _supabase()
    if sb is None:
        os.makedirs(LOCAL_DIR, exist_ok=True)
        file_storage.save(os.path.join(LOCAL_DIR, name))
        return
    url, key, bucket = sb
    content_type = file_storage.mimetype or mimetypes.guess_type(name)[0] or "application/octet-stream"
    req = urllib.request.Request(
        f"{url}/storage/v1/object/{bucket}/{quote(name)}",
        data=file_storage.stream.read(),
        method="POST",
        headers={"Authorization": f"Bearer {key}", "apikey": key,
                 "Content-Type": content_type, "x-upsert": "true",
                 "Cache-Control": "max-age=31536000"},
    )
    with urllib.request.urlopen(req, timeout=300) as resp:
        resp.read()


def url(name):
    """Public URL path for a stored file."""
    if not name:
        return ""
    sb = _supabase()
    if sb is None or name.startswith("seed-"):
        return f"/static/uploads/{quote(name)}"
    base, _key, bucket = sb
    return f"{base}/storage/v1/object/public/{bucket}/{quote(name)}"
