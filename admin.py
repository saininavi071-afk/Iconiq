"""Iconiq admin panel: server-rendered pages under /admin."""
import csv
import html
import io
import json
import os
import time
from datetime import date, datetime, timedelta
from http import cookies
from urllib.parse import parse_qs, quote, urlencode, urlparse

import store

COOKIE = "iconiq_admin"
MAX_FAILS, FAIL_WINDOW = 5, 15 * 60
_fails = {}

MESSAGES = {
    "created": ("Booking added.", "ok"),
    "updated": ("Booking updated.", "ok"),
    "blocked": ("Time blocked. Customers can no longer book it.", "ok"),
    "closed": ("Day closed. Customers can no longer book it.", "ok"),
    "unblocked": ("Reopened for bookings.", "ok"),
    "capacity": ("Booking limit saved.", "ok"),
    "password": ("Password changed.", "ok"),
    "welcome": ("Welcome! Your admin password is set.", "ok"),
    "restore_full": ("That time is already full, so this booking can't be restored.", "error"),
    "cert_revoked": ("Certificate revoked. The Verify page now shows it as not valid.", "ok"),
    "cert_restored": ("Certificate restored.", "ok"),
    "enrol_added": ("Student record added.", "ok"),
    "enrol_deleted": ("Student record deleted.", "ok"),
    "courses_saved": ("Courses and fees saved. The website's Courses page is updated.", "ok"),
    "cert_deleted": ("Certificate deleted. It can no longer be verified.", "ok"),
    "bad_block": ("Couldn't block that time. Please check the date.", "error"),
}

esc = html.escape


# ---------- Formatting ----------

def fmt_date(iso, long=False):
    d = store.parse_date(iso)
    if not d:
        return esc(iso or "")
    return d.strftime("%A, %d %B %Y" if long else "%a, %d %b %Y")


def fmt_created(ts):
    try:
        return datetime.fromisoformat(ts).astimezone(store.IST).strftime("%d %b %Y, %I:%M %p")
    except (TypeError, ValueError):
        return esc(ts or "")


def full_name(r):
    return esc(f"{r['first_name']} {r['last_name']}".strip())


def badge(status):
    return f'<span class="badge badge-{esc(status)}">{esc(store.STATUSES.get(status, status))}</span>'


def wa_link(phone):
    digits = "".join(c for c in phone or "" if c.isdigit())
    if len(digits) == 10:
        digits = "91" + digits
    return f"https://wa.me/{digits}" if len(digits) >= 11 else ""


ICONS = {
    "dashboard": '<path d="M3 13h8V3H3zm0 8h8v-6H3zm10 0h8V11h-8zm0-18v6h8V3z"/>',
    "bookings": '<path d="M19 4h-1V2h-2v2H8V2H6v2H5a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2V6a2 2 0 0 0-2-2zm0 16H5V9h14zM7 11h5v5H7z"/>',
    "schedule": '<path d="M12 2a10 10 0 1 0 0 20 10 10 0 0 0 0-20zm0 18a8 8 0 1 1 0-16 8 8 0 0 1 0 16zm.5-13H11v6l5.2 3.2.8-1.3-4.5-2.7z"/>',
    "new": '<path d="M19 13h-6v6h-2v-6H5v-2h6V5h2v6h6z"/>',
    "certificates": '<path d="M4 3h16a1 1 0 0 1 1 1v11a1 1 0 0 1-1 1h-5v-2h4V5H5v9h4v2H4a1 1 0 0 1-1-1V4a1 1 0 0 1 1-1zm3 4h10v2H7zm0 3h6v2H7zm5 3.5a3 3 0 0 1 2 5.2V22l-2-1-2 1v-3.3a3 3 0 0 1 2-5.2z"/>',
    "courses": '<path d="M12 3 1 9l4 2.2V17c0 1.7 3.1 3 7 3s7-1.3 7-3v-5.8l2-1.1V17h2V9zm6.8 6L12 12.7 5.2 9 12 5.3zM17 16.5c0 .3-1.9 1.5-5 1.5s-5-1.2-5-1.5v-3.2l5 2.7 5-2.7z"/>',
    "settings": '<path d="M19.4 13a7.5 7.5 0 0 0 0-2l2.1-1.6-2-3.5-2.5 1a7 7 0 0 0-1.7-1L15 3.3h-4l-.4 2.6a7 7 0 0 0-1.7 1l-2.5-1-2 3.5L6.6 11a7.5 7.5 0 0 0 0 2l-2.1 1.6 2 3.5 2.5-1a7 7 0 0 0 1.7 1l.4 2.6h4l.4-2.6a7 7 0 0 0 1.7-1l2.5 1 2-3.5zM13 15.5a3.5 3.5 0 1 1 0-7 3.5 3.5 0 0 1 0 7z" transform="translate(-1 0)"/>',
    "site": '<path d="M14 3v2h3.6l-9.8 9.8 1.4 1.4L19 6.4V10h2V3zm5 16H5V5h7V3H5a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7h-2z"/>',
    "logout": '<path d="M10 17l1.4-1.4-2.6-2.6H20v-2H8.8l2.6-2.6L10 7l-5 5zM4 5h8V3H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h8v-2H4z"/>',
}


def icon(name):
    return f'<svg viewBox="0 0 24 24" aria-hidden="true">{ICONS[name]}</svg>'


# ---------- Page shell ----------

def page(title, body, active=None, csrf="", msg=None):
    nav = [
        ("dashboard", "Dashboard", "/admin"),
        ("bookings", "Bookings", "/admin/bookings"),
        ("schedule", "Schedule", "/admin/schedule"),
        ("new", "New booking", "/admin/bookings/new"),
        ("certificates", "Certificates", "/admin/certificates"),
        ("courses", "Courses", "/admin/courses"),
        ("settings", "Settings", "/admin/settings"),
    ]
    flash = ""
    if msg in MESSAGES:
        text, tone = MESSAGES[msg]
        flash = f'<div class="flash flash-{tone}" role="status">{esc(text)}</div>'
    if active is None:
        shell = f'<main class="auth">{body}</main>'
    else:
        current = ' class="active" aria-current="page"'
        links = "".join(
            f'<a href="{href}"{current if key == active else ""}>{icon(key)}<span>{label}</span></a>'
            for key, label, href in nav
        )
        shell = f"""
<div class="app">
  <aside class="side">
    <a class="brand" href="/admin"><span class="brand-mark">ICONIQ</span><span class="brand-sub">Admin</span></a>
    <nav class="nav" aria-label="Admin">{links}</nav>
    <div class="side-foot">
      <a href="/" target="_blank" rel="noopener">{icon("site")}<span>View website</span></a>
      <form method="post" action="/admin/logout"><input type="hidden" name="csrf" value="{esc(csrf)}">
        <button type="submit">{icon("logout")}<span>Log out</span></button></form>
    </div>
  </aside>
  <main class="main">{flash}{body}</main>
</div>"""
    return f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="robots" content="noindex, nofollow">
<meta name="color-scheme" content="light">
<title>{esc(title)} · Iconiq Admin</title>
<link rel="icon" href="/favicon.svg" type="image/svg+xml">
<link rel="preconnect" href="https://fonts.googleapis.com"><link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Montserrat:wght@400;500;600;700&family=Playfair+Display:wght@500;600&display=swap" rel="stylesheet">
<link rel="stylesheet" href="/admin/assets/admin.css?v=3">
</head><body>{shell}</body></html>"""


def header(title, sub="", actions=""):
    sub_html = f'<p class="page-sub">{sub}</p>' if sub else ""
    return f'<header class="page-head"><div><h1>{title}</h1>{sub_html}</div><div class="head-actions">{actions}</div></header>'


def status_buttons(csrf, r, nxt):
    """Buttons for the status changes that make sense from the current status."""
    options = {
        "confirmed": [("completed", "Completed", "btn-soft"), ("no_show", "No-show", "btn-soft"),
                      ("cancelled", "Cancel", "btn-danger")],
        "completed": [("confirmed", "Undo", "btn-soft")],
        "no_show": [("confirmed", "Undo", "btn-soft")],
        "cancelled": [("confirmed", "Restore", "btn-soft")],
    }[r["status"]]
    out = []
    for status, label, cls in options:
        confirm = ' onsubmit="return confirm(\'Cancel this booking? The time will open up for other customers.\')"' if status == "cancelled" else ""
        out.append(
            f'<form method="post" action="/admin/bookings/{r["id"]}/status"{confirm}>'
            f'<input type="hidden" name="csrf" value="{esc(csrf)}"><input type="hidden" name="status" value="{status}">'
            f'<input type="hidden" name="next" value="{esc(nxt)}"><button class="btn btn-sm {cls}" type="submit">{label}</button></form>'
        )
    return f'<div class="row-actions">{"".join(out)}</div>'


def bookings_table(rows, csrf, nxt, show_date=True, actions=True, empty="No bookings found."):
    if not rows:
        return f'<div class="empty">{empty}</div>'
    head = ("<th>Date</th>" if show_date else "") + "<th>Time</th><th>Customer</th><th>Phone</th><th>Service</th><th>Status</th>" + ("<th><span class=\"sr-only\">Actions</span></th>" if actions else "")
    body = []
    for r in rows:
        cells = (f'<td class="nowrap">{fmt_date(r["date"])}</td>' if show_date else "")
        cells += f'<td class="nowrap strong">{esc(r["time"])}</td>'
        cells += f'<td><a class="cust" href="/admin/bookings/{r["id"]}">{full_name(r)}</a>'
        if r["email"]:
            cells += f'<span class="muted small">{esc(r["email"])}</span>'
        cells += "</td>"
        cells += f'<td class="nowrap"><a href="tel:{esc(r["phone"])}">{esc(r["phone"])}</a></td>'
        cells += f'<td>{esc(r["service"])}</td><td>{badge(r["status"])}</td>'
        if actions:
            cells += f'<td>{status_buttons(csrf, r, nxt)}</td>'
        body.append(f"<tr>{cells}</tr>")
    return f'<div class="table-wrap"><table class="table"><thead><tr>{head}</tr></thead><tbody>{"".join(body)}</tbody></table></div>'


# ---------- Pages ----------

def dashboard(s, q):
    st = store.stats()
    today = store.today()
    hour = store.now_ist().hour
    greet = "Good morning" if hour < 12 else "Good afternoon" if hour < 17 else "Good evening"
    todays = store.bookings_on(today.isoformat())
    cards = [
        ("Today", st["today"], "appointments", f"/admin/bookings?from={today}&to={today}"),
        ("Next 7 days", st["week"], "appointments", f"/admin/bookings?from={today}&to={today + timedelta(days=6)}"),
        ("This month", st["month"], "bookings", f"/admin/bookings?from={today.replace(day=1)}&view=all"),
        ("Cancelled", st["cancelled"], "this month", f"/admin/bookings?status=cancelled&from={today.replace(day=1)}"),
    ]
    stat_html = "".join(
        f'<a class="stat" href="{href}"><span class="stat-label">{label}</span><span class="stat-value">{val}</span><span class="stat-note">{note}</span></a>'
        for label, val, note, href in cards
    )
    new_note = f'{st["new_24h"]} new booking{"s" if st["new_24h"] != 1 else ""} in the last 24 hours.'
    closures = store.upcoming_closures()
    closure_html = "".join(
        f'<li><span>{fmt_date(c["date"])}</span><span class="muted">{esc(c["reason"] or "Closed")}</span></li>' for c in closures[:5]
    ) or '<li class="muted">No closed days coming up.</li>'
    up = store.upcoming()
    up_html = "".join(
        f'<li><a href="/admin/bookings/{r["id"]}"><span class="strong">{full_name(r)}</span>'
        f'<span class="muted small">{esc(r["service"])}</span></a><span class="up-when">{fmt_date(r["date"])}<br>{esc(r["time"])}</span></li>'
        for r in up
    ) or '<li class="muted">No upcoming bookings yet.</li>'
    body = header(
        f"{greet}", f"{today.strftime('%A, %d %B %Y')} · {new_note}",
        '<a class="btn btn-primary" href="/admin/bookings/new">' + icon("new") + "New booking</a>",
    )
    body += f'<section class="stats">{stat_html}</section>'
    body += f"""
<section class="card card-gap">
  <div class="card-head"><h2>Today's appointments</h2><a class="link" href="/admin/schedule">Open schedule</a></div>
  {bookings_table(todays, s["csrf"], "/admin", show_date=False, empty="No appointments today.")}
</section>
<div class="grid-even">
    <section class="card">
      <div class="card-head"><h2>Coming up</h2><a class="link" href="/admin/bookings">All bookings</a></div>
      <ul class="list">{up_html}</ul>
    </section>
    <section class="card">
      <div class="card-head"><h2>Closed days</h2><a class="link" href="/admin/schedule">Manage</a></div>
      <ul class="list list-plain">{closure_html}</ul>
    </section>
</div>"""
    return page("Dashboard", body, "dashboard", s["csrf"], q.get("msg"))


def bookings_list(s, q):
    today = store.today().isoformat()
    status, q_text = q.get("status", ""), q.get("q", "").strip()
    date_from, date_to = q.get("from", ""), q.get("to", "")
    view = q.get("view", "")
    if not any(k in q for k in ("status", "q", "from", "to", "view")):
        date_from = today  # default: upcoming
    rows = store.find_bookings(status, date_from, date_to, q_text, order="desc" if view == "past" else "asc")
    if view == "past":
        rows = [r for r in rows if r["date"] < today]
    filters = {"status": status, "q": q_text, "from": date_from, "to": date_to, "view": view}
    qs = urlencode({k: v for k, v in filters.items() if v})
    nxt = "/admin/bookings" + (f"?{qs}" if qs else "")
    chips = [
        ("Upcoming", f"/admin/bookings?from={today}", not view and date_from == today and not date_to and not status and not q_text),
        ("Today", f"/admin/bookings?from={today}&to={today}", date_from == today and date_to == today),
        ("Past", "/admin/bookings?view=past", view == "past"),
        ("All", "/admin/bookings?view=all", view == "all" and not date_from and not date_to and not status and not q_text),
    ]
    chip_html = "".join(f'<a class="chip{" on" if on else ""}" href="{href}">{label}</a>' for label, href, on in chips)
    opts = '<option value="">All statuses</option>' + "".join(
        f'<option value="{k}"{" selected" if k == status else ""}>{v}</option>' for k, v in store.STATUSES.items()
    )
    body = header(
        "Bookings", f"{len(rows)} booking{'s' if len(rows) != 1 else ''} shown",
        f'<a class="btn btn-outline" href="/admin/export.csv{("?" + qs) if qs else ""}">Export CSV</a>'
        f'<a class="btn btn-primary" href="/admin/bookings/new">{icon("new")}New booking</a>',
    )
    body += f"""
<section class="card">
  <div class="chips">{chip_html}</div>
  <form class="filters" method="get" action="/admin/bookings">
    <input type="hidden" name="view" value="{esc(view if view in ("all", "past") else "all")}">
    <label class="f-grow"><span>Search</span><input type="search" name="q" value="{esc(q_text)}" placeholder="Name, phone, email or service"></label>
    <label><span>Status</span><select name="status">{opts}</select></label>
    <label><span>From</span><input type="date" name="from" value="{esc(date_from)}"></label>
    <label><span>To</span><input type="date" name="to" value="{esc(date_to)}"></label>
    <div class="f-actions"><button class="btn btn-dark" type="submit">Apply</button><a class="btn btn-ghost" href="/admin/bookings">Reset</a></div>
  </form>
  {bookings_table(rows, s["csrf"], nxt)}
</section>"""
    return page("Bookings", body, "bookings", s["csrf"], q.get("msg"))


def booking_detail(s, q, r):
    wa = wa_link(r["phone"])
    nxt = f"/admin/bookings/{r['id']}"
    rows = [
        ("Date", fmt_date(r["date"], long=True)),
        ("Time", esc(r["time"])),
        ("Service", esc(r["service"])),
        ("Stylist", esc(r["stylist"] or "First available stylist")),
        ("Phone", f'<a href="tel:{esc(r["phone"])}">{esc(r["phone"])}</a>'
                  + (f' · <a href="{wa}" target="_blank" rel="noopener">WhatsApp</a>' if wa else "")),
        ("Email", f'<a href="mailto:{esc(r["email"])}">{esc(r["email"])}</a>' if r["email"] else '<span class="muted">Not given</span>'),
        ("Notes", esc(r["notes"]).replace("\n", "<br>") if r["notes"] else '<span class="muted">None</span>'),
        ("Booked", f'{fmt_created(r["created_at"])} · {"Website" if r["source"] == "website" else "Added by salon"}'),
    ]
    if r["updated_at"] and r["updated_at"] != r["created_at"]:
        rows.append(("Last updated", fmt_created(r["updated_at"])))
    dl = "".join(f"<div><dt>{k}</dt><dd>{v}</dd></div>" for k, v in rows)
    body = f'<a class="back" href="/admin/bookings">← All bookings</a>'
    body += header(f"{full_name(r)} {badge(r['status'])}", f"Booking #{r['id']}")
    body += f"""
<div class="grid-2 grid-detail">
  <section class="card"><dl class="details">{dl}</dl></section>
  <section class="card">
    <div class="card-head"><h2>Update status</h2></div>
    <p class="muted">Cancelling frees the time for other customers.</p>
    {status_buttons(s["csrf"], r, nxt)}
    <div class="divider"></div>
    <a class="btn btn-outline btn-block" href="/admin/schedule?date={esc(r["date"])}">See this day's schedule</a>
  </section>
</div>"""
    return page(f"Booking #{r['id']}", body, "bookings", s["csrf"], q.get("msg"))


def new_booking(s, q, values=None, error=""):
    v = values or {}
    today = store.today().isoformat()
    svc = "".join(
        f'<option{" selected" if x == v.get("service") else ""}>{esc(x)}</option>' for x in store.SERVICES
    )
    day = v.get("date") or today
    times = "".join(
        f'<option{" selected" if t == v.get("time") else ""}>{t}</option>' for t in store.slots_for(day)
    )
    err = f'<div class="flash flash-error" role="alert">{esc(error)}</div>' if error else ""
    val = lambda k: esc(v.get(k, ""))
    body = header("New booking", "Add a phone or walk-in booking. The same limit per time applies.")
    body += f"""
{err}
<section class="card card-narrow">
  <form method="post" action="/admin/bookings/new" class="form" id="new-booking">
    <input type="hidden" name="csrf" value="{esc(s["csrf"])}">
    <div class="form-grid">
      <label><span>First name *</span><input name="first_name" required value="{val("first_name")}" autocomplete="off"></label>
      <label><span>Last name</span><input name="last_name" value="{val("last_name")}" autocomplete="off"></label>
      <label><span>Phone *</span><input name="phone" type="tel" required value="{val("phone")}" autocomplete="off"></label>
      <label><span>Email</span><input name="email" type="email" value="{val("email")}" autocomplete="off"></label>
      <label class="span-2"><span>Service *</span><select name="service" required>{svc}</select></label>
      <label><span>Date *</span><input name="date" id="nb-date" type="date" required min="{today}" value="{esc(day)}"></label>
      <label><span>Time *</span><select name="time" id="nb-time" required>{times}</select></label>
      <p class="hint span-2" id="nb-hint"></p>
      <label class="span-2"><span>Notes</span><textarea name="notes" rows="3">{val("notes")}</textarea></label>
    </div>
    <div class="form-actions"><a class="btn btn-ghost" href="/admin/bookings">Cancel</a><button class="btn btn-primary" type="submit">Save booking</button></div>
  </form>
</section>
<script>
(function () {{
  var dateEl = document.getElementById("nb-date"), timeEl = document.getElementById("nb-time"), hint = document.getElementById("nb-hint");
  function load() {{
    if (!dateEl.value) return;
    var keep = timeEl.value;
    fetch("/admin/api/day?date=" + encodeURIComponent(dateEl.value), {{ cache: "no-store" }})
      .then(function (r) {{ return r.json(); }})
      .then(function (d) {{
        timeEl.innerHTML = "";
        var open = 0;
        d.slots.forEach(function (s) {{
          var o = document.createElement("option");
          o.value = s.time;
          o.textContent = s.time + (s.blocked ? " — blocked" : " — " + s.booked + "/" + d.max + " booked");
          if (s.blocked || s.booked >= d.max) o.disabled = true; else open++;
          if (s.time === keep && !o.disabled) o.selected = true;
          timeEl.appendChild(o);
        }});
        if (!timeEl.value || timeEl.selectedOptions[0].disabled) {{
          var first = timeEl.querySelector("option:not([disabled])");
          if (first) first.selected = true;
        }}
        hint.textContent = d.closed ? "The salon is marked closed on this day." : open ? open + " times still open on this day." : "This day is fully booked.";
      }});
  }}
  dateEl.addEventListener("change", load);
  load();
}})();
</script>"""
    return page("New booking", body, "new", s["csrf"])


def schedule(s, q):
    d = store.parse_date(q.get("date", "")) or store.today()
    iso = d.isoformat()
    cap = store.capacity()
    rows = store.bookings_on(iso)
    by_time = {}
    for r in rows:
        by_time.setdefault(r["time"], []).append(r)
    blocks = {b["time"]: b for b in store.blocks_for(iso) if b["time"]}
    closed = store.day_block(iso)
    csrf = esc(s["csrf"])
    past = iso < store.today().isoformat()
    nxt = f"/admin/schedule?date={iso}"

    lines = []
    for t in store.slots_for(iso):
        people = by_time.get(t, [])
        active = [p for p in people if p["status"] in store.ACTIVE]
        n = len(active)
        pct = min(100, round(n * 100 / cap))
        names = "".join(
            f'<a class="pill pill-{p["status"]}" href="/admin/bookings/{p["id"]}">{full_name(p)}<span>{esc(p["service"])}</span></a>'
            for p in people
        ) or '<span class="muted small">—</span>'
        blk = blocks.get(t)
        if blk:
            state = '<span class="badge badge-blocked">Blocked</span>'
            action = (f'<form method="post" action="/admin/schedule/unblock"><input type="hidden" name="csrf" value="{csrf}">'
                      f'<input type="hidden" name="id" value="{blk["id"]}"><input type="hidden" name="next" value="{nxt}">'
                      '<button class="btn btn-sm btn-soft" type="submit">Unblock</button></form>')
        else:
            state = f'<span class="cap"><span class="cap-bar"><span style="width:{pct}%" class="{"full" if n >= cap else ""}"></span></span>{n}/{cap}</span>'
            action = "" if (closed or past) else (
                f'<form method="post" action="/admin/schedule/block"><input type="hidden" name="csrf" value="{csrf}">'
                f'<input type="hidden" name="date" value="{iso}"><input type="hidden" name="time" value="{t}">'
                '<button class="btn btn-sm btn-ghost" type="submit">Block</button></form>')
        row_cls = "slot-full" if (n >= cap or blk) else ""
        lines.append(f'<tr class="{row_cls}"><td class="nowrap strong">{t}</td><td class="nowrap">{state}</td><td><div class="pills">{names}</div></td><td class="right">{action}</td></tr>')

    if closed:
        banner = (f'<div class="closed-banner"><div><strong>Salon closed</strong><span>{esc(closed["reason"] or "No online bookings on this day.")}</span></div>'
                  f'<form method="post" action="/admin/schedule/unblock"><input type="hidden" name="csrf" value="{csrf}">'
                  f'<input type="hidden" name="id" value="{closed["id"]}"><input type="hidden" name="next" value="{nxt}">'
                  '<button class="btn btn-outline" type="submit">Reopen day</button></form></div>')
    elif not past:
        banner = (f'<form class="close-day" method="post" action="/admin/schedule/block"><input type="hidden" name="csrf" value="{csrf}">'
                  f'<input type="hidden" name="date" value="{iso}"><input name="reason" placeholder="Reason, e.g. Diwali holiday" maxlength="200">'
                  '<button class="btn btn-outline" type="submit" onclick="return confirm(\'Close this whole day for online bookings?\')">Close this day</button></form>')
    else:
        banner = ""

    prev_d, next_d = (d - timedelta(days=1)).isoformat(), (d + timedelta(days=1)).isoformat()
    active_count = sum(1 for r in rows if r["status"] in store.ACTIVE)
    body = header("Schedule", f"{fmt_date(iso, long=True)} · {active_count} booked · up to {cap} per time")
    body += f"""
<section class="card">
  <div class="day-nav">
    <a class="btn btn-ghost btn-sm" href="/admin/schedule?date={prev_d}" aria-label="Previous day">‹ Prev</a>
    <form method="get" action="/admin/schedule"><input type="date" name="date" value="{iso}" onchange="this.form.submit()" aria-label="Choose date"></form>
    <a class="btn btn-ghost btn-sm" href="/admin/schedule?date={next_d}" aria-label="Next day">Next ›</a>
    <a class="btn btn-soft btn-sm" href="/admin/schedule">Today</a>
  </div>
  {banner}
  <div class="table-wrap"><table class="table table-slots"><thead><tr><th>Time</th><th>Booked</th><th>Customers</th><th><span class="sr-only">Actions</span></th></tr></thead>
  <tbody>{"".join(lines)}</tbody></table></div>
</section>"""
    return page("Schedule", body, "schedule", s["csrf"], q.get("msg"))


def certificates(s, q, values=None, error=""):
    v = values or {}
    issued = store.get_certificate(q.get("issued", "")) if q.get("issued") else None
    q_text = q.get("q", "").strip()
    rows = store.find_certificates(q_text)
    csrf = esc(s["csrf"])
    val = lambda k: esc(v.get(k, ""))
    today = store.today().isoformat()
    courses = "".join(f'<option value="{esc(c)}">' for c in store.course_names())
    err = f'<div class="flash flash-error" role="alert">{esc(error)}</div>' if error else ""
    done = ""
    if issued:
        link = f"/verify?ref={quote(issued['ref'])}"
        done = (f'<div class="flash flash-ok" role="status">Certificate issued to {esc(issued["student_name"])}. '
                f'Reference number: <strong class="ref">{esc(issued["ref"])}</strong> · '
                f'<a href="{link}" target="_blank" rel="noopener">Open on the website</a></div>')
    lines = []
    for r in rows:
        state = ('<span class="badge badge-cancelled">Revoked</span>' if r["revoked"]
                 else '<span class="badge badge-completed">Valid</span>')
        action = (f'<form method="post" action="/admin/certificates/{r["id"]}/revoke"'
                  + ('' if r["revoked"] else ' onsubmit="return confirm(\'Revoke this certificate? The Verify page will show it as not valid.\')"')
                  + f'><input type="hidden" name="csrf" value="{csrf}"><input type="hidden" name="revoked" value="{"0" if r["revoked"] else "1"}">'
                  f'<button class="btn btn-sm {"btn-soft" if r["revoked"] else "btn-danger"}" type="submit">{"Restore" if r["revoked"] else "Revoke"}</button></form>'
                  f'<form method="post" action="/admin/certificates/{r["id"]}/delete" '
                  f'onsubmit="return confirm(\'Delete this certificate permanently? This cannot be undone and the reference number will stop working.\')">'
                  f'<input type="hidden" name="csrf" value="{csrf}"><button class="btn btn-sm btn-danger" type="submit">Delete</button></form>')
        lines.append(
            f'<tr><td class="nowrap strong ref">{esc(r["ref"])}</td><td>{esc(r["student_name"])}</td>'
            f'<td>{esc(r["course"])}' + (f'<span class="muted small">{esc(r["duration"])}</span>' if r["duration"] else "") + '</td>'
            f'<td class="nowrap">{fmt_date(r["completed_on"])}</td><td>{state}</td>'
            f'<td><div class="row-actions"><a class="btn btn-sm btn-ghost" href="/verify?ref={quote(r["ref"])}" target="_blank" rel="noopener">View</a>{action}</div></td></tr>')
    table = (f'<div class="table-wrap"><table class="table"><thead><tr><th>Reference</th><th>Student</th><th>Course</th>'
             f'<th>Completed</th><th>Status</th><th><span class="sr-only">Actions</span></th></tr></thead><tbody>{"".join(lines)}</tbody></table></div>'
             if rows else f'<div class="empty">{"No certificates match your search." if q_text else "No certificates issued yet."}</div>')
    body = header("Certificates", "Issue a certificate when a student completes a course. They can verify it and download it on the website's Verify Certificate page.")
    body += f"""
{err}{done}
<div class="grid-2 grid-detail">
  <section class="card">
    <div class="card-head"><h2>Issued certificates</h2></div>
    <form class="filters" method="get" action="/admin/certificates">
      <label class="f-grow"><span>Search</span><input type="search" name="q" value="{esc(q_text)}" placeholder="Reference, student or course"></label>
      <div class="f-actions"><button class="btn btn-dark" type="submit">Search</button><a class="btn btn-ghost" href="/admin/certificates">Reset</a></div>
    </form>
    {table}
  </section>
  <section class="card">
    <div class="card-head"><h2>Issue a certificate</h2></div>
    <p class="muted">A reference number is created automatically. Check the spelling of the name: it is printed exactly as entered.</p>
    <form method="post" action="/admin/certificates" class="form">
      <input type="hidden" name="csrf" value="{csrf}">
      <label><span>Student's full name *</span><input name="student_name" required maxlength="200" value="{val("student_name")}" autocomplete="off"></label>
      <label><span>Course *</span><input name="course" required maxlength="200" list="course-list" value="{val("course")}" placeholder="e.g. Professional Hair Styling" autocomplete="off"></label>
      <datalist id="course-list">{courses}</datalist>
      <label><span>Duration</span><input name="duration" maxlength="200" value="{val("duration")}" placeholder="e.g. 3 months" autocomplete="off"></label>
      <label><span>Completed on *</span><input name="completed_on" type="date" required max="{today}" value="{val("completed_on") or today}"></label>
      <div class="form-actions"><button class="btn btn-primary" type="submit">Issue certificate</button></div>
    </form>
  </section>
</div>"""
    return page("Certificates", body, "certificates", s["csrf"], q.get("msg"))


def courses_page(s, q, error="", values=None, enrol_error="", enrol_values=None):
    data = store.get_courses()
    rows = [(c["name"], c["fee"]) for c in data["courses"]]
    pkg = data["package_fee"]
    if values:  # redisplay what was typed after a validation error
        rows = [(values.get(f"name_{i}", ""), values.get(f"fee_{i}", "")) for i in range(len(rows) + 2)]
        pkg = values.get("package_fee", pkg)
    else:
        rows += [("", "")] * 2
    csrf = esc(s["csrf"])
    err = f'<div class="flash flash-error" role="alert">{esc(error)}</div>' if error else ""
    existing = len(data["courses"])
    lines = "".join(
        f'<div class="course-row"><label><span>Course name</span><input name="name_{i}" maxlength="60" value="{esc(str(n))}" placeholder="New course"></label>'
        f'<label><span>Fee (₹)</span><input name="fee_{i}" type="number" min="1" step="1" inputmode="numeric" value="{esc(str(f))}"></label>'
        + (f'<button class="btn btn-sm btn-danger" type="button" data-field="name_{i}" data-msg="Delete this course? It will be removed from the website." '
           'onclick="if(confirm(this.dataset.msg)){this.form.elements[this.dataset.field].value=``;this.form.requestSubmit()}">Delete</button>'
           if i < existing else '<span></span>')
        + '</div>'
        for i, (n, f) in enumerate(rows))
    body = header("Courses", "Set the courses and fees shown on the website's Courses page. Students pick from these when they generate a fee receipt.")
    body += f"""
{err}
<section class="card">
  <div class="card-head"><h2>Courses &amp; fees</h2></div>
  <form method="post" action="/admin/courses" class="form">
    <input type="hidden" name="csrf" value="{csrf}">
    {lines}
    <p class="muted small">Use the empty rows to add new courses. Delete removes a course from the website straight away.</p>
    <div class="divider"></div>
    <label><span>Full package fee (₹), when a student takes every course</span><input name="package_fee" type="number" min="1" step="1" inputmode="numeric" required value="{esc(str(pkg))}"></label>
    <div class="form-actions"><button class="btn btn-primary" type="submit">Save courses</button>
      <a class="btn btn-ghost" href="/courses.html" target="_blank" rel="noopener">View Courses page</a></div>
  </form>
</section>"""
    # ---- Student records ----
    q_text = q.get("q", "").strip()
    records = store.list_enrolments(q_text)
    ev = enrol_values or {}
    rlines = []
    for r in records:
        try:
            when = datetime.fromisoformat(r["created"]).strftime("%d %b %Y")
        except (KeyError, ValueError):
            when = ""
        rn = esc(r.get("receipt_no", ""))
        rlines.append(
            f'<tr><td class="nowrap strong ref">{rn}</td><td class="nowrap">{when}</td>'
            f'<td>{esc(r.get("name", ""))}</td>'
            f'<td class="nowrap">{esc(r.get("phone", ""))}' + (f'<span class="muted small">{esc(r["email"])}</span>' if r.get("email") else "") + '</td>'
            f'<td>{esc(", ".join(r.get("courses", [])))}' + ('<span class="muted small">Full package</span>' if r.get("package") else "") + '</td>'
            f'<td class="nowrap strong">₹{int(r.get("total", 0)):,}</td>'
            f'<td><form method="post" action="/admin/courses/records/{rn}/delete" '
            f'onsubmit="return confirm(this.dataset.msg)" data-msg="Delete this student record?"><input type="hidden" name="csrf" value="{csrf}">'
            f'<button class="btn btn-sm btn-danger" type="submit">Delete</button></form></td></tr>')
    total_sum = sum(int(r.get("total", 0)) for r in records)
    if records:
        rtable = (f'<div class="table-wrap"><table class="table"><thead><tr><th>Receipt</th><th>Date</th><th>Student</th><th>Contact</th>'
                  f'<th>Courses</th><th>Total</th><th><span class="sr-only">Actions</span></th></tr></thead><tbody>{"".join(rlines)}</tbody></table></div>'
                  f'<p class="muted small">{len(records)} record{"" if len(records) == 1 else "s"} · ₹{total_sum:,} in total fees</p>')
    else:
        rtable = ('<div class="empty">' + ("No records match your search." if q_text else
                  "No student records yet. They appear here when students generate a receipt on the website, or you can add one below.") + '</div>')
    picks = "".join(
        f'<label class="check"><input type="checkbox" name="course_{i}" value="{esc(c["name"])}"' + (" checked" if ev.get(f"course_{i}") else "") +
        f'> {esc(c["name"])} · ₹{c["fee"]:,}</label>' for i, c in enumerate(data["courses"]))
    eerr = f'<div class="flash flash-error" role="alert">{esc(enrol_error)}</div>' if enrol_error else ""
    body += f"""
<section class="card">
  <div class="card-head"><h2>Student course records</h2></div>
  <form class="filters" method="get" action="/admin/courses">
    <label class="f-grow"><span>Search</span><input type="search" name="q" value="{esc(q_text)}" placeholder="Receipt, student, phone or course"></label>
    <div class="f-actions"><button class="btn btn-dark" type="submit">Search</button><a class="btn btn-ghost" href="/admin/courses">Reset</a></div>
  </form>
  {rtable}
</section>
<section class="card">
  <div class="card-head"><h2>Add a student record</h2></div>
  <p class="muted">For students who enrolled in person. The fee is worked out from the course fees above.</p>
  {eerr}
  <form method="post" action="/admin/courses/records" class="form">
    <input type="hidden" name="csrf" value="{csrf}">
    <div class="form-row">
      <label><span>Student's full name *</span><input name="name" required maxlength="100" value="{esc(ev.get("name", ""))}" autocomplete="off"></label>
      <label><span>Phone *</span><input name="phone" required inputmode="numeric" maxlength="14" value="{esc(ev.get("phone", ""))}" placeholder="10-digit mobile number" autocomplete="off"></label>
    </div>
    <label><span>Email (optional)</span><input name="email" type="email" maxlength="120" value="{esc(ev.get("email", ""))}" autocomplete="off"></label>
    <fieldset class="checks"><legend>Courses *</legend>{picks}</fieldset>
    <div class="form-actions"><button class="btn btn-primary" type="submit">Add record</button></div>
  </form>
</section>"""
    return page("Courses", body, "courses", s["csrf"], q.get("msg"))


def settings(s, q, error="", pw_error=""):
    cap = store.capacity()
    env_pw = bool(os.environ.get("ICONIQ_ADMIN_PASSWORD"))
    csrf = esc(s["csrf"])
    err = f'<div class="flash flash-error" role="alert">{esc(error)}</div>' if error else ""
    pw_err = f'<div class="flash flash-error" role="alert">{esc(pw_error)}</div>' if pw_error else ""
    pw_form = (
        '<p class="muted">The password is set on the server with ICONIQ_ADMIN_PASSWORD, so it can only be changed there.</p>'
        if env_pw else f"""
      {pw_err}
      <form method="post" action="/admin/settings/password" class="form">
        <input type="hidden" name="csrf" value="{csrf}">
        <label><span>Current password</span><input type="password" name="current" required autocomplete="current-password"></label>
        <label><span>New password</span><input type="password" name="new" required minlength="8" autocomplete="new-password"></label>
        <label><span>Confirm new password</span><input type="password" name="confirm" required minlength="8" autocomplete="new-password"></label>
        <div class="form-actions"><button class="btn btn-primary" type="submit">Change password</button></div>
      </form>""")
    body = header("Settings")
    body += f"""
{err}
<div class="grid-2">
  <section class="card">
    <div class="card-head"><h2>Bookings per time</h2></div>
    <p class="muted">How many customers can book the same date and time. When a time reaches this limit, customers see "Please select another time".</p>
    <form method="post" action="/admin/settings/capacity" class="form form-inline">
      <input type="hidden" name="csrf" value="{csrf}">
      <label><span>Limit</span><input type="number" name="capacity" min="1" max="20" value="{cap}" required></label>
      <button class="btn btn-primary" type="submit">Save</button>
    </form>
  </section>
  <section class="card">
    <div class="card-head"><h2>Password</h2></div>
    {pw_form}
    <div class="divider"></div>
    <form method="post" action="/admin/settings/logout-all" onsubmit="return confirm('Log out of the admin panel on every device?')">
      <input type="hidden" name="csrf" value="{csrf}">
      <button class="btn btn-ghost" type="submit">Log out on all devices</button>
    </form>
  </section>
</div>"""
    return page("Settings", body, "settings", s["csrf"], q.get("msg"))


def auth_page(title, intro, action, fields, button, error=""):
    err = f'<div class="flash flash-error" role="alert">{esc(error)}</div>' if error else ""
    body = f"""
<div class="auth-card">
  <div class="brand brand-lg"><span class="brand-mark">ICONIQ</span><span class="brand-sub">Hair &amp; Beauty · Admin</span></div>
  <h1>{title}</h1><p class="muted">{intro}</p>{err}
  <form method="post" action="{action}" class="form">{fields}
    <button class="btn btn-primary btn-block" type="submit">{button}</button></form>
</div>"""
    return page(title, body)


def login_page(error="", nxt=""):
    fields = (f'<input type="hidden" name="next" value="{esc(nxt)}">'
              '<label><span>Password</span><input type="password" name="password" required autofocus autocomplete="current-password"></label>')
    return auth_page("Sign in", "Enter the admin password to manage bookings.", "/admin/login", fields, "Sign in", error)


def setup_page(error=""):
    fields = ('<label><span>New password</span><input type="password" name="new" required minlength="8" autofocus autocomplete="new-password"></label>'
              '<label><span>Confirm password</span><input type="password" name="confirm" required minlength="8" autocomplete="new-password"></label>')
    return auth_page("Create admin password", "First-time setup. Choose a password of at least 8 characters. You'll use it to sign in.",
                     "/admin/setup", fields, "Create password", error)


def export_csv(q):
    rows = store.find_bookings(q.get("status", ""), q.get("from", ""), q.get("to", ""), q.get("q", "").strip())
    if q.get("view") == "past":
        rows = [r for r in rows if r["date"] < store.today().isoformat()]
    buf = io.StringIO()
    w = csv.writer(buf)
    cols = ["id", "date", "time", "service", "first_name", "last_name", "phone", "email", "status", "source", "notes", "created_at"]
    w.writerow([c.replace("_", " ").title() for c in cols])
    for r in rows:
        # Prefix cells that spreadsheet apps would treat as formulas.
        w.writerow(["'" + v if v[:1] in ("=", "+", "-", "@") else v for v in (str(r[c] or "") for c in cols)])
    return ("﻿" + buf.getvalue()).encode("utf-8")


# ---------- Request handling ----------

def send(h, status, body, ctype="text/html; charset=utf-8", extra=()):
    if isinstance(body, str):
        body = body.encode("utf-8")
    h.send_response(status)
    h.send_header("Content-Type", ctype)
    h.send_header("Content-Length", str(len(body)))
    h.send_header("Cache-Control", "no-store")
    h.send_header("X-Frame-Options", "DENY")
    h.send_header("X-Content-Type-Options", "nosniff")
    h.send_header("Referrer-Policy", "same-origin")
    for k, v in extra:
        h.send_header(k, v)
    h.end_headers()
    h.wfile.write(body)


def redirect(h, location, extra=()):
    h.send_response(303)
    h.send_header("Location", location)
    h.send_header("Content-Length", "0")
    h.send_header("Cache-Control", "no-store")
    for k, v in extra:
        h.send_header(k, v)
    h.end_headers()


def safe_next(nxt, default="/admin"):
    return nxt if nxt and nxt.startswith("/admin") and "//" not in nxt and "\\" not in nxt else default


def with_msg(path, msg):
    return path + ("&" if "?" in path else "?") + "msg=" + quote(msg)


def session_cookie(h, token, max_age=None):
    """Sign-in cookie. Without Max-Age the browser keeps it only until it closes,
    so opening the admin panel again always asks for the password.
    max_age=0 is used to delete the cookie on sign-out."""
    secure = "; Secure" if h.headers.get("X-Forwarded-Proto", "").lower() == "https" else ""
    age = f"; Max-Age={max_age}" if max_age is not None else ""
    return ("Set-Cookie", f"{COOKIE}={token}; Path=/admin; HttpOnly; SameSite=Strict{age}{secure}")


def client_ip(h):
    return (h.headers.get("X-Forwarded-For", "").split(",")[0].strip() or h.client_address[0])


def too_many_fails(ip):
    now = time.time()
    _fails[ip] = [t for t in _fails.get(ip, []) if now - t < FAIL_WINDOW]
    return len(_fails[ip]) >= MAX_FAILS


def same_origin(h):
    origin = h.headers.get("Origin")
    if not origin:
        return True
    return urlparse(origin).netloc == h.headers.get("Host", "")


def handle(h, method):
    try:
        return _handle(h, method)
    except store.StoreError as e:
        h.log_error("Supabase error: %s", e)
        return send(h, 503, page("Database unavailable", header("Can't reach the database right now")
                                 + '<p class="muted">Please check your internet connection and try again in a moment.</p>'
                                 + f'<p class="muted">Reason: {esc(str(e)[:200])}</p>'))


def _handle(h, method):
    url = urlparse(h.path)
    path = url.path.rstrip("/") or "/admin"
    q = {k: v[0] for k, v in parse_qs(url.query).items()}

    if path == "/admin/assets/admin.css":
        with open(os.path.join(store.ROOT, "admin", "admin.css"), "rb") as f:
            return send(h, 200, f.read(), "text/css; charset=utf-8")

    form = {}
    if method == "POST":
        if not same_origin(h):
            return send(h, 403, "Forbidden", "text/plain")
        length = min(int(h.headers.get("Content-Length") or 0), 50_000)
        form = {k: v[0] for k, v in parse_qs(h.rfile.read(length).decode("utf-8", "replace"), keep_blank_values=True).items()}

    jar = cookies.SimpleCookie(h.headers.get("Cookie", ""))
    token = jar[COOKIE].value if COOKIE in jar else ""
    s = store.get_session(token)
    if s:
        store.touch_session(s)

    # First run: no password yet.
    if not store.has_password():
        if path != "/admin/setup":
            return redirect(h, "/admin/setup")
        if method == "GET":
            return send(h, 200, setup_page())
        pw, confirm = form.get("new", ""), form.get("confirm", "")
        if len(pw) < 8:
            return send(h, 400, setup_page("Use at least 8 characters."))
        if pw != confirm:
            return send(h, 400, setup_page("The passwords don't match."))
        store.set_password(pw)
        new = store.create_session()
        return redirect(h, "/admin?msg=welcome", [session_cookie(h, new)])

    if path == "/admin/setup":
        return redirect(h, "/admin")

    if path == "/admin/login":
        if s:
            return redirect(h, "/admin")
        if method == "GET":
            return send(h, 200, login_page(nxt=q.get("next", "")))
        ip = client_ip(h)
        if too_many_fails(ip):
            return send(h, 429, login_page("Too many attempts. Please wait 15 minutes and try again."))
        if not store.check_password(form.get("password", "")):
            _fails.setdefault(ip, []).append(time.time())
            return send(h, 401, login_page("That password isn't right.", form.get("next", "")))
        _fails.pop(ip, None)
        new = store.create_session()
        return redirect(h, safe_next(form.get("next")), [session_cookie(h, new)])

    if not s:
        if method == "GET":
            return redirect(h, "/admin/login" + (f"?next={quote(h.path)}" if path != "/admin" else ""))
        return redirect(h, "/admin/login")

    if method == "POST" and form.get("csrf") != s["csrf"]:
        return send(h, 403, "Your session expired. Go back, refresh the page and try again.", "text/plain; charset=utf-8")

    # ----- Signed-in routes -----
    if path == "/admin/logout" and method == "POST":
        store.end_session(token)
        return redirect(h, "/admin/login", [session_cookie(h, "", 0)])

    if path == "/admin" and method == "GET":
        return send(h, 200, dashboard(s, q))

    if path == "/admin/bookings" and method == "GET":
        return send(h, 200, bookings_list(s, q))

    if path == "/admin/bookings/new":
        if method == "GET":
            return send(h, 200, new_booking(s, q, {"date": q.get("date", ""), "time": q.get("time", "")}))
        new_id, err = store.create_booking(form, source="admin")
        if err:
            return send(h, err[0], new_booking(s, q, form, err[1]))
        return redirect(h, f"/admin/bookings/{new_id}?msg=created")

    parts = path.split("/")
    if len(parts) >= 4 and parts[2] == "bookings" and parts[3].isdigit():
        r = store.get_booking(int(parts[3]))
        if not r:
            return send(h, 404, page("Not found", header("Booking not found") + '<a class="btn btn-outline" href="/admin/bookings">Back to bookings</a>', "bookings", s["csrf"]))
        if len(parts) == 4 and method == "GET":
            return send(h, 200, booking_detail(s, q, r))
        if len(parts) == 5 and parts[4] == "status" and method == "POST":
            err = store.set_status(r["id"], form.get("status", ""))
            nxt = safe_next(form.get("next"), f"/admin/bookings/{r['id']}")
            return redirect(h, with_msg(nxt, "restore_full" if err else "updated"))

    if path == "/admin/schedule" and method == "GET":
        return send(h, 200, schedule(s, q))

    if path == "/admin/schedule/block" and method == "POST":
        iso, t = form.get("date", ""), form.get("time") or None
        err = store.add_block(iso, t, form.get("reason", "").strip())
        return redirect(h, with_msg(f"/admin/schedule?date={quote(iso)}", "bad_block" if err else ("blocked" if t else "closed")))

    if path == "/admin/schedule/unblock" and method == "POST":
        if form.get("id", "").isdigit():
            store.remove_block(int(form["id"]))
        return redirect(h, with_msg(safe_next(form.get("next"), "/admin/schedule"), "unblocked"))

    if path == "/admin/api/day" and method == "GET":
        iso = q.get("date", "")
        if not store.parse_date(iso):
            return send(h, 400, '{"error":"bad date"}', "application/json")
        counts, blocked = store.slot_counts(iso), store.blocked_times(iso)
        closed = bool(store.day_block(iso))
        data = {"max": store.capacity(), "closed": closed, "slots": [
            {"time": t, "booked": counts.get(t, 0), "blocked": closed or t in blocked} for t in store.slots_for(iso)]}
        return send(h, 200, json.dumps(data), "application/json")

    if path == "/admin/export.csv" and method == "GET":
        name = f"iconiq-bookings-{store.today().isoformat()}.csv"
        return send(h, 200, export_csv(q), "text/csv; charset=utf-8", [("Content-Disposition", f'attachment; filename="{name}"')])

    if path == "/admin/certificates":
        if method == "GET":
            return send(h, 200, certificates(s, q))
        cert, err = store.create_certificate(form)
        if err:
            return send(h, 400, certificates(s, q, form, err))
        return redirect(h, f"/admin/certificates?issued={quote(cert['ref'])}")

    if len(parts) == 5 and parts[2] == "certificates" and parts[3].isdigit() and parts[4] == "delete" and method == "POST":
        store.delete_certificate(int(parts[3]))
        return redirect(h, "/admin/certificates?msg=cert_deleted")
    if len(parts) == 5 and parts[2] == "certificates" and parts[3].isdigit() and parts[4] == "revoke" and method == "POST":
        revoked = form.get("revoked") == "1"
        store.set_certificate_revoked(int(parts[3]), revoked)
        return redirect(h, "/admin/certificates?msg=" + ("cert_revoked" if revoked else "cert_restored"))

    if path == "/admin/courses/records" and method == "POST":
        names = [form[k] for k in sorted(form) if k.startswith("course_")]
        rec, err = store.create_enrolment(form.get("name"), form.get("phone"), form.get("email"), names)
        if err:
            return send(h, 400, courses_page(s, q, enrol_error=err, enrol_values=form))
        return redirect(h, "/admin/courses?msg=enrol_added")

    if len(parts) == 6 and parts[2] == "courses" and parts[3] == "records" and parts[5] == "delete" and method == "POST":
        store.delete_enrolment(parts[4])
        return redirect(h, "/admin/courses?msg=enrol_deleted")

    if path == "/admin/courses":
        if method == "GET":
            return send(h, 200, courses_page(s, q))
        n = len(store.get_courses()["courses"]) + 2
        err = store.save_courses([(form.get(f"name_{i}"), form.get(f"fee_{i}", "")) for i in range(n)], form.get("package_fee", ""))
        if err:
            return send(h, 400, courses_page(s, q, err, form))
        return redirect(h, "/admin/courses?msg=courses_saved")

    if path == "/admin/settings":
        return send(h, 200, settings(s, q))

    if path == "/admin/settings/capacity" and method == "POST":
        try:
            cap = int(form.get("capacity", ""))
            if not 1 <= cap <= 20:
                raise ValueError
        except ValueError:
            return send(h, 400, settings(s, q, error="Enter a number from 1 to 20."))
        store.set_setting("capacity", cap)
        return redirect(h, "/admin/settings?msg=capacity")

    if path == "/admin/settings/password" and method == "POST":
        if not store.check_password(form.get("current", "")):
            return send(h, 400, settings(s, q, pw_error="Your current password isn't right."))
        new, confirm = form.get("new", ""), form.get("confirm", "")
        if len(new) < 8:
            return send(h, 400, settings(s, q, pw_error="Use at least 8 characters."))
        if new != confirm:
            return send(h, 400, settings(s, q, pw_error="The new passwords don't match."))
        store.set_password(new)
        return redirect(h, "/admin/settings?msg=password")

    if path == "/admin/settings/logout-all" and method == "POST":
        store.end_session(token, everywhere=True)
        return redirect(h, "/admin/login", [session_cookie(h, "", 0)])

    return send(h, 404, page("Not found", header("Page not found") + '<a class="btn btn-outline" href="/admin">Go to dashboard</a>', "dashboard", s["csrf"]))
