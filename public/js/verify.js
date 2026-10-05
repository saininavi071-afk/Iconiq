/* Iconiq Hair & Beauty — Verify Certificate page
   Looks up a reference number with /api/certificate, then draws the
   certificate on a canvas so the student can download it as a PDF or image.
   No libraries: the PDF is a one-page A4 file with the certificate as a JPEG. */

(function () {
  "use strict";

  var SITE = "https://www.iconiqsalon.com";
  var W = 3508, H = 2480;          // A4 landscape at 300 dpi
  var GOLD = "#8a6a2f", GOLD_SOFT = "#c9a66b", INK = "#22201e", MUTED = "#5e5750";
  var DISPLAY = '"Playfair Display", Georgia, serif', BODY = '"Montserrat", Arial, sans-serif';

  var form = document.getElementById("verify-form");
  if (!form) return;
  var input = document.getElementById("ref");
  var button = form.querySelector("button[type=submit]");
  var status = document.getElementById("verify-status");
  var result = document.getElementById("verify-result");
  var canvas = document.getElementById("cert-canvas");
  var current = null;
  var sig = null;                    // signature image, loaded once (falls back to no signature if it can't load)

  function loadSignature() {
    if (sig) return sig;
    sig = new Promise(function (resolve) {
      var img = new Image();
      img.onload = function () { resolve(img); };
      img.onerror = function () { resolve(null); };
      img.src = "img/signature.png";
    });
    return sig;
  }

  function show(msg, tone) {
    status.textContent = msg;
    status.className = "form-status" + (tone ? " " + tone : "");
  }

  function fmtDate(iso) {
    var p = iso.split("-");
    var d = new Date(Date.UTC(+p[0], +p[1] - 1, +p[2]));
    return d.toLocaleDateString("en-GB", { day: "numeric", month: "long", year: "numeric", timeZone: "UTC" });
  }

  function verifyUrl(ref) {
    // A phone can't open localhost, so local previews point at the live site instead.
    var local = /^(localhost|127\.|\[::1\]$)/.test(location.hostname);
    return (local ? SITE : location.origin) + "/verify?ref=" + encodeURIComponent(ref);
  }

  function lookup(ref) {
    ref = ref.trim();
    if (!ref) {
      input.setAttribute("aria-invalid", "true");
      show("Please enter your certificate reference number.", "error");
      input.focus();
      return;
    }
    input.removeAttribute("aria-invalid");
    result.hidden = true;
    button.disabled = true;
    show("Checking…");
    fetch("/api/certificate?ref=" + encodeURIComponent(ref), { cache: "no-store" })
      .then(function (r) {
        return r.json().catch(function () { return {}; }).then(function (d) { return { ok: r.ok, status: r.status, data: d }; });
      })
      .then(function (res) {
        if (res.status === 404) return show("No certificate was found with this reference number. Please check it and try again.", "error");
        if (!res.ok) return show(res.data.error || "Verification is temporarily unavailable. Please try again later.", "error");
        var c = res.data;
        try { history.replaceState(null, "", "?ref=" + encodeURIComponent(c.ref)); } catch (e) {}
        if (c.revoked) return show("Certificate " + c.ref + " has been revoked and is no longer valid. Please contact the salon.", "error");
        show("");
        render(c);
      })
      .catch(function () { show("Couldn't connect. Please check your internet connection and try again.", "error"); })
      .then(function () { button.disabled = false; });
  }

  function render(c) {
    current = c;
    document.getElementById("r-name").textContent = c.student_name;
    document.getElementById("r-course").textContent = c.course;
    document.getElementById("r-date").textContent = fmtDate(c.completed_on);
    document.getElementById("r-ref").textContent = c.ref;
    var dur = document.getElementById("r-duration-row");
    dur.hidden = !c.duration;
    document.getElementById("r-duration").textContent = c.duration || "";
    result.hidden = false;
    var fonts = document.fonts ? Promise.all([
      document.fonts.load("500 200px " + DISPLAY), document.fonts.load("italic 500 200px " + DISPLAY),
      document.fonts.load("600 200px " + DISPLAY), document.fonts.load("400 60px " + BODY),
      document.fonts.load("600 60px " + BODY), document.fonts.load("700 60px " + BODY)
    ]).catch(function () {}) : Promise.resolve();
    Promise.all([fonts, loadSignature()]).then(function (r) { draw(c, r[1]); });
    result.scrollIntoView({ behavior: "smooth", block: "start" });
    document.getElementById("result-heading").focus({ preventScroll: true });
  }

  /* ---------- Drawing ---------- */

  function spaced(ctx, text, x, y, spacing) {
    // Letter-spaced text centred on x (canvas letterSpacing isn't everywhere yet).
    var chars = text.split(""), widths = chars.map(function (ch) { return ctx.measureText(ch).width; });
    var total = widths.reduce(function (a, b) { return a + b; }, 0) + spacing * (chars.length - 1);
    var cx = x - total / 2, align = ctx.textAlign;
    ctx.textAlign = "left";
    chars.forEach(function (ch, i) { ctx.fillText(ch, cx, y); cx += widths[i] + spacing; });
    ctx.textAlign = align;
  }

  function fit(ctx, text, font, size, maxW) {
    // Largest font size (up to `size`) at which text fits in maxW.
    do { ctx.font = font.replace("{s}", size + "px"); size -= 4; } while (ctx.measureText(text).width > maxW && size > 40);
  }

  function rule(ctx, x1, x2, y, color, width) {
    ctx.strokeStyle = color; ctx.lineWidth = width;
    ctx.beginPath(); ctx.moveTo(x1, y); ctx.lineTo(x2, y); ctx.stroke();
  }

  function diamond(ctx, x, y, r) {
    ctx.beginPath(); ctx.moveTo(x, y - r); ctx.lineTo(x + r, y); ctx.lineTo(x, y + r); ctx.lineTo(x - r, y); ctx.closePath(); ctx.fill();
  }

  function corner(ctx, x, y, sx, sy) {
    // L-shaped ornament with a diamond, mirrored into each corner.
    ctx.save(); ctx.translate(x, y); ctx.scale(sx, sy);
    ctx.strokeStyle = GOLD; ctx.lineWidth = 8;
    ctx.beginPath(); ctx.moveTo(0, 190); ctx.lineTo(0, 0); ctx.lineTo(190, 0); ctx.stroke();
    ctx.lineWidth = 3;
    ctx.beginPath(); ctx.moveTo(30, 150); ctx.lineTo(30, 30); ctx.lineTo(150, 30); ctx.stroke();
    ctx.fillStyle = GOLD; diamond(ctx, 30, 30, 16);
    ctx.restore();
  }

  function seal(ctx, x, y) {
    var r = 190;
    ctx.save();
    ctx.translate(x, y); ctx.scale(0.84, 0.84); x = 0; y = 0;
    ctx.fillStyle = GOLD;
    // Scalloped rosette edge
    ctx.beginPath();
    for (var i = 0; i <= 72; i++) {
      var a = (i / 72) * Math.PI * 2, rr = i % 2 ? r : r - 16;
      ctx[i ? "lineTo" : "moveTo"](x + Math.cos(a) * rr, y + Math.sin(a) * rr);
    }
    ctx.fill();
    ctx.strokeStyle = "#f6ecd6"; ctx.lineWidth = 5;
    ctx.beginPath(); ctx.arc(x, y, r - 40, 0, Math.PI * 2); ctx.stroke();
    ctx.lineWidth = 2;
    ctx.beginPath(); ctx.arc(x, y, r - 54, 0, Math.PI * 2); ctx.stroke();
    ctx.fillStyle = "#fffaf0"; ctx.textAlign = "center"; ctx.textBaseline = "middle";
    ctx.font = "600 64px " + DISPLAY; spaced(ctx, "ICONIQ", x, y - 12, 6);
    ctx.font = "700 24px " + BODY; spaced(ctx, "CERTIFIED", x, y + 46, 8);
    diamond(ctx, x, y - 72, 9);
    ctx.restore();
  }

  function draw(c, signature) {
    canvas.width = W; canvas.height = H;
    var ctx = canvas.getContext("2d"), cx = W / 2;

    // Paper with a soft vignette
    var bg = ctx.createRadialGradient(cx, H / 2, 200, cx, H / 2, W * 0.7);
    bg.addColorStop(0, "#fffdf8"); bg.addColorStop(1, "#f4ebdc");
    ctx.fillStyle = bg; ctx.fillRect(0, 0, W, H);

    // Borders
    ctx.strokeStyle = INK; ctx.lineWidth = 26; ctx.strokeRect(70, 70, W - 140, H - 140);
    ctx.strokeStyle = GOLD; ctx.lineWidth = 6; ctx.strokeRect(128, 128, W - 256, H - 256);
    ctx.strokeStyle = GOLD_SOFT; ctx.lineWidth = 2; ctx.strokeRect(150, 150, W - 300, H - 300);
    corner(ctx, 190, 190, 1, 1); corner(ctx, W - 190, 190, -1, 1);
    corner(ctx, 190, H - 190, 1, -1); corner(ctx, W - 190, H - 190, -1, -1);

    ctx.textAlign = "center"; ctx.textBaseline = "alphabetic";

    // Brand
    ctx.fillStyle = INK; ctx.font = "600 150px " + DISPLAY; spaced(ctx, "ICONIQ", cx, 470, 34);
    ctx.fillStyle = GOLD; ctx.font = "600 42px " + BODY; spaced(ctx, "HAIR & BEAUTY UNISEX STUDIO", cx, 555, 16);
    rule(ctx, cx - 420, cx - 40, 625, GOLD_SOFT, 3); rule(ctx, cx + 40, cx + 420, 625, GOLD_SOFT, 3);
    ctx.fillStyle = GOLD; diamond(ctx, cx, 625, 14);

    // Title
    ctx.fillStyle = INK; ctx.font = "italic 500 150px " + DISPLAY; ctx.fillText("Certificate of Completion", cx, 850);

    ctx.fillStyle = MUTED; ctx.font = "500 50px " + BODY; spaced(ctx, "THIS IS TO CERTIFY THAT", cx, 1010, 10);

    // Student name
    ctx.fillStyle = INK; fit(ctx, c.student_name, "500 {s} " + DISPLAY, 190, W - 900);
    ctx.fillText(c.student_name, cx, 1230);
    rule(ctx, cx - 900, cx + 900, 1300, GOLD, 4);

    ctx.fillStyle = MUTED; ctx.font = "400 54px " + BODY;
    ctx.fillText("has successfully completed the professional course", cx, 1410);

    // Course
    ctx.fillStyle = GOLD; fit(ctx, c.course, "600 {s} " + DISPLAY, 110, W - 900);
    ctx.fillText(c.course, cx, 1560);
    if (c.duration) {
      ctx.fillStyle = MUTED; ctx.font = "500 46px " + BODY;
      ctx.fillText("Course duration: " + c.duration, cx, 1650);
    }

    // Footer: date · seal · signature (low enough to leave room for the QR code above the date)
    var fy = 2050, left = 900, right = W - 900;

    // QR code above the date: scanning it opens this certificate's verification page
    if (window.IconiqQR) {
      var qr = IconiqQR.matrix(verifyUrl(c.ref)), q = 4, cell = Math.floor(260 / (qr.length + q * 2)), side = cell * (qr.length + q * 2);
      var qx = left - side / 2, qy = fy - 115 - side;
      ctx.fillStyle = "#ffffff"; ctx.fillRect(qx, qy, side, side);
      ctx.strokeStyle = GOLD_SOFT; ctx.lineWidth = 3; ctx.strokeRect(qx, qy, side, side);
      ctx.fillStyle = INK;
      qr.forEach(function (row, y) { row.forEach(function (dark, x) {
        if (dark) ctx.fillRect(qx + (x + q) * cell, qy + (y + q) * cell, cell, cell);
      }); });
    }

    ctx.fillStyle = INK; ctx.font = "600 56px " + BODY; ctx.fillText(fmtDate(c.completed_on), left, fy - 30);
    rule(ctx, left - 330, left + 330, fy, INK, 3);
    ctx.fillStyle = MUTED; ctx.font = "600 34px " + BODY; spaced(ctx, "DATE OF COMPLETION", left, fy + 60, 6);

    if (signature) {
      var sh = 150, sw = sh * signature.width / signature.height;
      if (sw > 620) { sw = 620; sh = sw * signature.height / signature.width; }
      ctx.drawImage(signature, right - sw / 2, fy - 12 - sh, sw, sh);
    }
    rule(ctx, right - 330, right + 330, fy, INK, 3);
    ctx.fillStyle = MUTED; ctx.font = "600 34px " + BODY; spaced(ctx, "AUTHORISED SIGNATORY", right, fy + 60, 6);

    seal(ctx, cx, fy - 20);

    ctx.fillStyle = MUTED; ctx.font = "500 36px " + BODY;
    ctx.fillText("Certificate No. " + c.ref, cx, H - 215);
  }

  /* ---------- Downloads ---------- */

  function fileBase() { return "Iconiq-Certificate-" + current.ref; }

  function save(blob, name) {
    var a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = name;
    document.body.appendChild(a);
    a.click();
    setTimeout(function () { URL.revokeObjectURL(a.href); a.remove(); }, 1000);
  }

  function pdfFromJpeg(jpeg, imgW, imgH, title) {
    // Minimal PDF 1.4: one A4 landscape page showing one JPEG full-bleed.
    var enc = new TextEncoder(), parts = [], offsets = [], size = 0;
    function add(x) { var b = typeof x === "string" ? enc.encode(x) : x; parts.push(b); size += b.length; }
    function obj(n, body) { offsets[n] = size; add(n + " 0 obj\n" + body + "\nendobj\n"); }
    var pw = 841.89, ph = 595.28, content = "q " + pw + " 0 0 " + ph + " 0 0 cm /Im0 Do Q";
    var safeTitle = title.replace(/[^\x20-\x7e]/g, "").replace(/([()\\])/g, "\\$1");
    add("%PDF-1.4\n%\xe2\xe3\xcf\xd3\n");
    obj(1, "<< /Type /Catalog /Pages 2 0 R >>");
    obj(2, "<< /Type /Pages /Kids [3 0 R] /Count 1 >>");
    obj(3, "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 " + pw + " " + ph + "] /Resources << /XObject << /Im0 4 0 R >> >> /Contents 5 0 R >>");
    offsets[4] = size;
    add("4 0 obj\n<< /Type /XObject /Subtype /Image /Width " + imgW + " /Height " + imgH +
        " /ColorSpace /DeviceRGB /BitsPerComponent 8 /Filter /DCTDecode /Length " + jpeg.length + " >>\nstream\n");
    add(jpeg); add("\nendstream\nendobj\n");
    obj(5, "<< /Length " + content.length + " >>\nstream\n" + content + "\nendstream");
    obj(6, "<< /Title (" + safeTitle + ") /Author (Iconiq Hair & Beauty) /Creator (www.iconiqsalon.com) >>");
    var xref = size, lines = "xref\n0 7\n0000000000 65535 f \n";
    for (var i = 1; i <= 6; i++) lines += String(offsets[i]).padStart(10, "0") + " 00000 n \n";
    add(lines + "trailer\n<< /Size 7 /Root 1 0 R /Info 6 0 R >>\nstartxref\n" + xref + "\n%%EOF\n");
    return new Blob(parts, { type: "application/pdf" });
  }

  document.getElementById("dl-pdf").addEventListener("click", function () {
    if (!current) return;
    canvas.toBlob(function (blob) {
      blob.arrayBuffer().then(function (buf) {
        save(pdfFromJpeg(new Uint8Array(buf), W, H, "Certificate " + current.ref + " - " + current.student_name), fileBase() + ".pdf");
      });
    }, "image/jpeg", 0.92);
  });

  document.getElementById("dl-png").addEventListener("click", function () {
    if (!current) return;
    canvas.toBlob(function (blob) { save(blob, fileBase() + ".png"); }, "image/png");
  });

  form.addEventListener("submit", function (e) {
    e.preventDefault();
    lookup(input.value);
  });

  var initial = new URLSearchParams(location.search).get("ref");
  if (initial) {
    input.value = initial;
    lookup(initial);
  }
})();
