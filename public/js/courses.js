/* Iconiq Hair & Beauty — Courses page
   Picks courses, totals the fee and builds a printable receipt in the browser. */

(function () {
  "use strict";

  var form = document.getElementById("course-form");
  if (!form) return;
  var boxes = Array.prototype.slice.call(form.querySelectorAll("input[name=course]"));
  var full = document.getElementById("c-full");
  var packageFee = Number(full.dataset.fee);
  var totalEl = document.getElementById("c-total");
  var wrap = document.getElementById("receipt-wrap");

  function money(n) { return "₹" + n.toLocaleString("en-IN"); }
  function el(id) { return document.getElementById(id); }

  function text(tag, cls, str) { var n = document.createElement(tag); if (cls) n.className = cls; n.textContent = str; return n; }

  // Fees come from the admin panel; the markup in courses.html is the fallback.
  function applyFees(data) {
    var courses = data.courses, cards = document.querySelector(".course-cards"), pick = form.querySelector(".course-pick"), i;
    packageFee = Number(data.package_fee);
    cards.textContent = "";
    boxes.forEach(function (b) { b.closest("label").remove(); });
    boxes = [];
    var anchor = full.closest("label"), names = [];
    courses.forEach(function (c, idx) {
      names.push(c.name);
      var card = text("div", "card", ""); card.appendChild(text("h3", "", c.name)); card.appendChild(text("p", "price", money(c.fee)));
      cards.appendChild(card);
      var label = document.createElement("label"), box = document.createElement("input");
      label.className = "pick"; box.type = "checkbox"; box.name = "course"; box.value = c.name; box.dataset.fee = c.fee;
      label.appendChild(box); label.appendChild(text("span", "", c.name)); label.appendChild(text("b", "", money(c.fee)));
      pick.insertBefore(label, anchor);
      box.addEventListener("change", refresh);
      boxes.push(box);
    });
    var fc = text("div", "card card-feature", ""); fc.appendChild(text("h3", "", "Full Package"));
    fc.appendChild(text("p", "price", money(packageFee))); fc.appendChild(text("p", "", names.join(" + "))); cards.appendChild(fc);
    anchor.querySelector("small").textContent = "(" + names.join(" + ") + ")";
    anchor.querySelector("b").textContent = money(packageFee);
    refresh();
  }

  function selected() { return boxes.filter(function (b) { return b.checked; }); }
  function total() {
    if (boxes.length && selected().length === boxes.length) return packageFee;
    return selected().reduce(function (a, b) { return a + Number(b.dataset.fee); }, 0);
  }

  function refresh() {
    full.checked = boxes.every(function (b) { return b.checked; });
    totalEl.textContent = money(total());
  }

  full.addEventListener("change", function () {
    boxes.forEach(function (b) { b.checked = full.checked; });
    refresh();
  });
  boxes.forEach(function (b) { b.addEventListener("change", refresh); });

  fetch("/api/courses", { cache: "no-store" }).then(function (r) { return r.ok ? r.json() : null; })
    .then(function (d) { if (d && d.courses && d.courses.length) applyFees(d); }).catch(function () {});

  function normalisePhone(v) {
    var d = v.replace(/[\s\-()]/g, "").replace(/^(\+91|91|0)(?=\d{10}$)/, "");
    return /^[6-9]\d{9}$/.test(d) ? d : null;
  }

  form.addEventListener("submit", function (e) {
    e.preventDefault();
    var name = el("c-name").value.trim(), phone = normalisePhone(el("c-phone").value), email = el("c-email").value.trim();
    ["c-name-err", "c-phone-err", "c-email-err", "c-course-err"].forEach(function (id) { el(id).textContent = ""; });
    var ok = true;
    if (!name) { el("c-name-err").textContent = "Please enter the student's name."; ok = false; }
    if (!phone) { el("c-phone-err").textContent = "Enter a valid 10-digit Indian mobile number."; ok = false; }
    if (email && !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email)) { el("c-email-err").textContent = "Please enter a valid email address."; ok = false; }
    if (!selected().length) { el("c-course-err").textContent = "Please choose at least one course."; ok = false; }
    if (!ok) {
      var bad = form.querySelector(".field-error:not(:empty)");
      if (bad) bad.scrollIntoView({ block: "center", behavior: "smooth" });
      return;
    }

    var submit = form.querySelector("button[type=submit]"), status = el("c-status");
    submit.disabled = true; status.textContent = "Creating your receipt…"; status.className = "form-status";
    fetch("/api/enrol", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name: name, phone: phone, email: email, courses: selected().map(function (b) { return b.value; }) })
    }).then(function (r) { return r.json().catch(function () { return {}; }).then(function (d) { return { ok: r.ok, data: d }; }); })
      .then(function (res) {
        if (!res.ok) { status.textContent = res.data.error || "Sorry, we couldn't create your receipt. Please try again or call us."; status.className = "form-status error"; return; }
        status.textContent = ""; status.className = "form-status";
        showReceipt(res.data);
      })
      .catch(function () { status.textContent = "Couldn't connect. Please check your internet connection and try again."; status.className = "form-status error"; })
      .then(function () { submit.disabled = false; });
  });

  function showReceipt(r) {
    var items = el("rc-items");
    el("rc-no").textContent = r.receipt_no;
    el("rc-date").textContent = new Date(r.created).toLocaleDateString("en-GB", { day: "numeric", month: "long", year: "numeric" });
    el("rc-name").textContent = r.name;
    el("rc-phone").textContent = "+91 " + r.phone;
    el("rc-email").textContent = r.email;
    el("rc-email-row").hidden = !r.email;
    items.textContent = "";
    var rows = r.package ? [["Full Package (" + r.items.map(function (i) { return i.name; }).join(" + ") + ")", r.total]]
                         : r.items.map(function (i) { return [i.name + " course", i.fee]; });
    rows.forEach(function (row) {
      var tr = document.createElement("tr"), a = document.createElement("td"), b = document.createElement("td");
      a.textContent = row[0]; b.textContent = money(row[1]); b.className = "num";
      tr.appendChild(a); tr.appendChild(b); items.appendChild(tr);
    });
    el("rc-total").textContent = money(r.total);
    wrap.hidden = false;
    wrap.scrollIntoView({ behavior: "smooth", block: "start" });
  }

  el("rc-print").addEventListener("click", function () { window.print(); });
  el("rc-new").addEventListener("click", function () {
    wrap.hidden = true; form.reset(); refresh();
    form.scrollIntoView({ behavior: "smooth", block: "start" });
  });

  refresh();
})();
