/* Live directory client: every filter, sort and page change hits the API. */
(function () {
  "use strict";

  var PAGE = 50;
  var $ = function (id) { return document.getElementById(id); };
  var q = $("q"), fSource = $("source"), fSector = $("sector"), fCountry = $("country");
  var body = $("body"), empty = $("empty"), count = $("count"), pos = $("pos");
  var table = body.closest("table");

  var sortKey = "n", sortAsc = true, page = 0, total = 0, grand = 0;
  var inflight = null, timer = null;

  function esc(s) {
    return String(s == null ? "" : s).replace(/[&<>"]/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c];
    });
  }

  function fill(sel, values) {
    var frag = document.createDocumentFragment();
    values.forEach(function (v) {
      var o = document.createElement("option");
      o.value = v;
      o.textContent = v;
      frag.appendChild(o);
    });
    sel.appendChild(frag);
  }

  function query() {
    var params = new URLSearchParams({
      q: q.value.trim(),
      source: fSource.value,
      sector: fSector.value,
      country: fCountry.value,
      sort: sortKey,
      dir: sortAsc ? "asc" : "desc",
      page: String(page),
      per_page: String(PAGE)
    });

    // Supersede any request still in flight - the newest keystroke wins.
    if (inflight) { inflight.abort(); }
    var controller = new AbortController();
    inflight = controller;
    table.classList.add("loading");

    fetch("/api/companies?" + params.toString(), { signal: controller.signal })
      .then(function (r) {
        if (!r.ok) { throw new Error("Request failed: " + r.status); }
        return r.json();
      })
      .then(function (data) {
        inflight = null;
        table.classList.remove("loading");
        total = data.total;
        render(data.rows);
      })
      .catch(function (err) {
        if (err.name === "AbortError") { return; }
        table.classList.remove("loading");
        body.innerHTML = "";
        empty.hidden = false;
        empty.textContent = "Could not reach the database. Is the server running?";
      });
  }

  function render(rows) {
    empty.hidden = rows.length > 0;
    empty.textContent = "No companies match those filters.";

    body.innerHTML = rows.map(function (r) {
      var name = r.w
        ? '<a href="' + esc(r.w) + '" target="_blank" rel="noopener noreferrer">' + esc(r.n) + "</a>"
        : esc(r.n);
      var tags = (r.src || []).map(function (s) {
        return '<span class="tag">' + esc(s) + "</span>";
      }).join("");
      return "<tr>" +
        '<td class="name">' + name + "</td>" +
        '<td class="sector">' + esc(r.s || "—") + "</td>" +
        '<td class="country">' + esc(r.c || "—") + "</td>" +
        '<td class="num">' + (r.e == null ? "—" : r.e) + "</td>" +
        "<td>" + (tags || "—") + "</td>" +
        "</tr>";
    }).join("");

    count.innerHTML = "<b>" + total.toLocaleString() + "</b> of " + grand.toLocaleString() + " companies";

    var pages = Math.max(1, Math.ceil(total / PAGE));
    var from = total ? page * PAGE + 1 : 0;
    var to = Math.min(total, (page + 1) * PAGE);
    pos.textContent = from + "–" + to + " of " + total.toLocaleString();
    $("prev").disabled = page === 0;
    $("next").disabled = page >= pages - 1;

    document.querySelectorAll("th[data-key]").forEach(function (th) {
      var base = th.textContent.replace(/[↑↓]\s*$/, "").trim();
      th.innerHTML = esc(base) + (th.dataset.key === sortKey
        ? ' <span class="dir">' + (sortAsc ? "↑" : "↓") + "</span>"
        : "");
    });
  }

  function reload(resetPage) {
    if (resetPage) { page = 0; }
    query();
  }

  document.querySelectorAll("th[data-key]").forEach(function (th) {
    th.addEventListener("click", function () {
      var k = th.dataset.key;
      if (k === sortKey) { sortAsc = !sortAsc; } else { sortKey = k; sortAsc = true; }
      reload(true);
    });
  });

  q.addEventListener("input", function () {
    clearTimeout(timer);
    timer = setTimeout(function () { reload(true); }, 180);
  });
  [fSource, fSector, fCountry].forEach(function (s) {
    s.addEventListener("change", function () { reload(true); });
  });
  $("reset").addEventListener("click", function () {
    q.value = ""; fSource.value = ""; fSector.value = ""; fCountry.value = "";
    reload(true);
  });
  $("prev").addEventListener("click", function () {
    if (page > 0) { page--; query(); window.scrollTo({ top: 0, behavior: "smooth" }); }
  });
  $("next").addEventListener("click", function () {
    page++; query(); window.scrollTo({ top: 0, behavior: "smooth" });
  });

  fetch("/api/facets")
    .then(function (r) { return r.json(); })
    .then(function (f) {
      grand = f.total;
      fill(fSource, f.sources);
      fill(fSector, f.sectors);
      fill(fCountry, f.countries);
      if (f.updated_at) {
        var when = new Date(f.updated_at);
        var foot = document.querySelector("footer");
        foot.append(" · " + f.total.toLocaleString() + " companies · last write " +
          when.toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" }));
      }
      query();
    })
    .catch(function () { query(); });
})();
