"""Iconiq website server.

Serves the static site (public/), the booking API and the admin panel.
This is the local development server; in production Vercel serves public/
from its CDN and runs api/index.py for /api/* and /admin (see vercel.json).
Bookings are stored in Supabase (see store.py and supabase/schema.sql);
admin.py is the admin panel.

Run:   python server.py            -> http://localhost:8080
Admin: http://localhost:8080/admin  (first visit asks you to create a password)

Settings come from environment variables or a .env file next to this one:
  SUPABASE_URL               https://<project>.supabase.co          (required)
  SUPABASE_SERVICE_ROLE_KEY  service_role key, keep it secret        (required)
  PORT                       port to listen on (default 8080)
  ICONIQ_ADMIN_PASSWORD      fixed admin password (otherwise set on first visit)
"""
import json
import os
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

import admin
import store

PORT = int(os.environ.get("PORT", "8080"))
PRIVATE = (".db", ".db-journal", ".py", ".pyc", ".md")


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=store.STATIC_ROOT, **kwargs)

    def send_json(self, status, payload):
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def is_admin(self, path):
        return path == "/admin" or path.startswith("/admin/")

    def do_GET(self):
        url = urlparse(self.path)
        if self.is_admin(url.path):
            return admin.handle(self, "GET")
        if url.path == "/api/slots":
            day = (parse_qs(url.query).get("date") or [""])[0]
            if not store.parse_date(day):
                return self.send_json(400, {"error": "Invalid date."})
            try:
                return self.send_json(200, store.public_availability(day))
            except store.StoreError as e:
                self.log_error("Supabase error: %s", e)
                return self.send_json(503, {"error": "Booking is temporarily unavailable. Please call us."})
        if url.path == "/api/courses":
            try:
                return self.send_json(200, store.get_courses())
            except store.StoreError as e:
                self.log_error("Supabase error: %s", e)
                return self.send_json(200, store.DEFAULT_COURSES)
        if url.path == "/api/certificate":
            ref = (parse_qs(url.query).get("ref") or [""])[0]
            try:
                cert = store.public_certificate(ref)
            except store.StoreError as e:
                self.log_error("Supabase error: %s", e)
                return self.send_json(503, {"error": "Verification is temporarily unavailable. Please try again later."})
            if not cert:
                return self.send_json(404, {"error": "No certificate was found with this reference number."})
            return self.send_json(200, cert)
        # Never serve server-side files, the database or hidden folders.
        lower = url.path.lower()
        if lower.endswith(PRIVATE) or "/." in lower or "__pycache__" in lower:
            return self.send_error(404)
        return super().do_GET()

    def do_HEAD(self):
        if self.is_admin(urlparse(self.path).path):
            return self.send_error(405)
        return super().do_HEAD()

    def do_POST(self):
        path = urlparse(self.path).path
        if self.is_admin(path):
            return admin.handle(self, "POST")
        if path not in ("/api/book", "/api/enrol"):
            return self.send_error(404)
        try:
            length = int(self.headers.get("Content-Length", "0"))
            data = json.loads(self.rfile.read(min(length, 20000)) or b"{}")
        except (ValueError, json.JSONDecodeError):
            return self.send_json(400, {"error": "Invalid request."})
        if path == "/api/enrol":
            try:
                rec, err = store.create_enrolment(data.get("name"), data.get("phone"), data.get("email"),
                                                  [c for c in data.get("courses") or [] if isinstance(c, str)][:20])
            except store.StoreError as e:
                self.log_error("Supabase error: %s", e)
                return self.send_json(503, {"error": "Sorry, we couldn't create your receipt right now. Please try again or call us."})
            if err:
                return self.send_json(400, {"error": err})
            return self.send_json(201, {k: rec[k] for k in ("receipt_no", "created", "name", "phone", "email", "items", "total", "package")})
        try:
            booking_id, err = store.create_booking({
                "date": data.get("date"), "time": data.get("time"), "service": data.get("service"),
                "stylist": data.get("stylist"), "first_name": data.get("first"), "last_name": data.get("last"),
                "email": data.get("email"), "phone": data.get("phone"), "notes": data.get("notes"),
            })
        except store.StoreError as e:
            self.log_error("Supabase error: %s", e)
            return self.send_json(503, {"error": "Sorry, we couldn't save your booking right now. Please try again or call us."})
        if err:
            status, message = err
            return self.send_json(status, {"error": message, "full": status == 409})
        return self.send_json(201, {"ok": True, "id": booking_id})


if __name__ == "__main__":
    store.init_db()
    print(f"Iconiq site running at http://localhost:{PORT}")
    print(f"Admin panel:           http://localhost:{PORT}/admin")
    ThreadingHTTPServer(("", PORT), Handler).serve_forever()
