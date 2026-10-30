// SPDX-License-Identifier: AGPL-3.0-or-later — NetInv, Copyright (C) 2026 Bill Farmer, Jr. See LICENSE.
(() => {
  "use strict";
  const $ = (s, el = document) => el.querySelector(s);
  const $$ = (s, el = document) => Array.from(el.querySelectorAll(s));

  // ---- timestamps: server renders UTC, show local time with relative tooltip
  const pad = (n) => String(n).padStart(2, "0");
  const fmtLocal = (d) =>
    `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`;
  function relative(d) {
    const s = (Date.now() - d.getTime()) / 1000;
    if (s < 60) return "just now";
    if (s < 3600) return `${Math.floor(s / 60)} min ago`;
    if (s < 86400) return `${Math.floor(s / 3600)} h ago`;
    return `${Math.floor(s / 86400)} d ago`;
  }
  function localizeTimes(root = document) {
    $$("time.ts", root).forEach((t) => {
      const d = new Date(t.getAttribute("datetime"));
      if (isNaN(d)) return;
      t.textContent = fmtLocal(d) + (t.classList.contains("secs") ? `:${pad(d.getSeconds())}` : "");
      t.title = `${relative(d)} · ${t.getAttribute("datetime")}`;
    });
  }
  function timeEl(iso) {
    const t = document.createElement("time");
    t.className = "ts";
    t.setAttribute("datetime", iso);
    localizeTimes({ querySelectorAll: () => [t] });
    return t;
  }

  // ---- theme: follow the system unless the toggle picked the other theme
  const systemDark = window.matchMedia("(prefers-color-scheme: dark)");
  $$("[data-theme-toggle]").forEach((btn) => {
    btn.addEventListener("click", () => {
      const root = document.documentElement;
      const system = systemDark.matches ? "dark" : "light";
      const next = (root.dataset.theme || system) === "dark" ? "light" : "dark";
      try {
        if (next === system) {
          delete root.dataset.theme; // back to following the system
          localStorage.removeItem("netinv-theme");
        } else {
          root.dataset.theme = next;
          localStorage.setItem("netinv-theme", next);
        }
      } catch (e) {
        root.dataset.theme = next;
      }
    });
  });

  // ---- toast
  let toastTimer;
  function toast(msg, kind = "") {
    const el = $("#toast");
    if (!el) return;
    el.textContent = msg;
    el.className = `show ${kind}`;
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => (el.className = ""), 1600);
  }

  async function postJSON(url, body) {
    const r = await fetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/json", Accept: "application/json" },
      body: JSON.stringify(body),
    });
    if (!r.ok) throw new Error(`HTTP ${r.status}`);
    return r.json();
  }

  // ---- check state segmented controls
  function paintCheck(li, state) {
    li.dataset.state = state;
    $$(".seg-btn", li).forEach((b) => b.setAttribute("aria-pressed", String(b.value === state)));
  }
  $$("form[data-check]").forEach((form) => {
    form.addEventListener("click", async (e) => {
      const btn = e.target.closest("button[name=state]");
      if (!btn) return;
      e.preventDefault();
      const li = form.closest(".check");
      const prev = li.dataset.state;
      const state = btn.value;
      if (state === prev || li.classList.contains("saving")) return;
      paintCheck(li, state);
      li.classList.add("saving");
      try {
        const data = await postJSON(form.action, { state });
        paintCheck(li, data.state);
        const ts = $(".check-ts", li);
        if (ts && data.changed_at) ts.replaceChildren("changed ", timeEl(data.changed_at));
        const prog = $("#node-progress");
        if (prog && data.progress_html) prog.innerHTML = data.progress_html;
        toast(`Marked ${btn.textContent.trim()}`);
      } catch (err) {
        paintCheck(li, prev);
        toast("Could not save — try again", "err");
      } finally {
        li.classList.remove("saving");
      }
    });
  });

  // ---- config matrices: save each checkbox as it changes
  $$("table.matrix[data-endpoint]").forEach((tbl) => {
    tbl.addEventListener("change", async (e) => {
      const cb = e.target;
      if (!cb.matches("input[type=checkbox]")) return;
      cb.disabled = true;
      try {
        await postJSON(tbl.dataset.endpoint, { row: +cb.dataset.row, col: +cb.dataset.col, on: cb.checked });
        toast(cb.checked ? "Linked" : "Unlinked");
      } catch (err) {
        cb.checked = !cb.checked;
        toast("Could not save — try again", "err");
      } finally {
        cb.disabled = false;
      }
    });
  });

  // ---- bulk select + delete on config lists
  $$("form[data-bulk]").forEach((form) => {
    const boxes = $$(`input.bulk-cb[form="${form.id}"]`);
    const all = $("[data-bulk-all]", form);
    const btn = $("[data-bulk-submit]", form);
    const noun = form.dataset.noun;
    function update() {
      const n = boxes.filter((b) => b.checked).length;
      btn.disabled = n === 0;
      btn.textContent = n ? `Delete ${n} selected` : "Delete selected";
      all.checked = n > 0 && n === boxes.length;
      all.indeterminate = n > 0 && n < boxes.length;
      boxes.forEach((b) => b.closest(".item").classList.toggle("selected", b.checked));
    }
    boxes.forEach((b) => b.addEventListener("change", update));
    all.addEventListener("change", () => { boxes.forEach((b) => (b.checked = all.checked)); update(); });
    form.addEventListener("submit", (e) => {
      const n = boxes.filter((b) => b.checked).length;
      if (!window.confirm(`Delete ${n} ${noun}${n === 1 ? "" : "s"}? This cannot be undone.`)) {
        e.preventDefault();
        e.stopImmediatePropagation();
      }
    });
    update();
  });

  // ---- confirm replace-mode imports
  $$("form[data-import]").forEach((form) => {
    form.addEventListener("submit", (e) => {
      if (form.mode.value === "replace" &&
          !window.confirm("Replace ALL current data and history with the contents of this file?")) {
        e.preventDefault();
      }
    });
  });

  // ---- confirmations (on a form, or on the submit button that was used)
  document.addEventListener("submit", (e) => {
    const src = e.submitter && e.submitter.dataset.confirm ? e.submitter : e.target;
    const msg = src.dataset && src.dataset.confirm;
    if (msg && !window.confirm(msg)) e.preventDefault();
  });

  // ---- clickable table rows
  $$("tr[data-href]").forEach((tr) => {
    tr.addEventListener("click", (e) => {
      if (e.target.closest("a, button, input")) return;
      window.location = tr.dataset.href;
    });
  });

  $$("[data-print]").forEach((b) => b.addEventListener("click", () => window.print()));

  // ---- role dropdown offers only the tags currently in the form's tag input
  $$("select[data-role-select]").forEach((sel) => {
    const src = sel.form && sel.form.elements[sel.dataset.tagsFrom];
    if (!src) return;
    src.addEventListener("tagschange", (e) => {
      const current = sel.value.toLowerCase();
      sel.replaceChildren(new Option("No role", ""), ...e.detail.map((t) => new Option(t, t)));
      sel.value = e.detail.find((t) => t.toLowerCase() === current) || "";
    });
  });

  $$("select[data-autosubmit]").forEach((sel) => sel.addEventListener("change", () => sel.form.submit()));

  // ---- tag chip input (enhances a comma-separated text input)
  $$("input[data-tag-input]").forEach((input) => {
    const norm = (s) => s.replace(/\s+/g, " ").trim();
    let tags = input.value.split(",").map(norm).filter(Boolean);
    const box = document.createElement("div");
    box.className = "tag-input";
    const entry = document.createElement("input");
    entry.type = "text";
    entry.placeholder = input.placeholder;
    entry.autocapitalize = "off";
    entry.setAttribute("aria-label", "Add tag");
    // Offer only tags that aren't applied yet: keep the full list and rebuild the datalist on each change.
    const list = input.list;
    const known = list ? $$("option", list).map((o) => o.value) : [];
    if (list) entry.setAttribute("list", list.id);
    input.removeAttribute("list");
    input.type = "hidden";
    input.after(box);
    box.addEventListener("click", (e) => { if (e.target === box) entry.focus(); });

    function sync() {
      input.value = tags.join(", ");
      input.dispatchEvent(new CustomEvent("tagschange", { detail: tags.slice() }));
      box.replaceChildren(
        ...tags.map((t, i) => {
          const chip = document.createElement("span");
          chip.className = "chip";
          chip.textContent = t;
          const x = document.createElement("button");
          x.type = "button";
          x.textContent = "×";
          x.setAttribute("aria-label", `Remove ${t}`);
          x.addEventListener("click", () => { tags.splice(i, 1); sync(); entry.focus(); });
          chip.append(x);
          return chip;
        }),
        entry
      );
      entry.placeholder = tags.length ? "" : input.placeholder;
      if (list) {
        const applied = new Set(tags.map((t) => t.toLowerCase()));
        list.replaceChildren(...known.filter((t) => !applied.has(t.toLowerCase())).map((t) => new Option(t)));
      }
    }
    function add(raw) {
      raw.split(",").map(norm).filter(Boolean).forEach((t) => {
        if (!tags.some((x) => x.toLowerCase() === t.toLowerCase())) tags.push(t);
      });
      entry.value = "";
      sync();
      entry.focus();
    }
    entry.addEventListener("keydown", (e) => {
      if (e.key === "Enter" || e.key === ",") {
        if (entry.value.trim()) { e.preventDefault(); add(entry.value); }
        else if (e.key === ",") e.preventDefault();
      } else if (e.key === "Backspace" && !entry.value && tags.length) {
        tags.pop();
        sync();
        entry.focus();
      }
    });
    // datalist pick fires an input event without a keypress
    entry.addEventListener("input", (e) => {
      if (!e.inputType || e.inputType === "insertReplacementText") {
        if (entry.value.trim()) add(entry.value);
      }
    });
    entry.addEventListener("blur", () => { if (entry.value.trim()) add(entry.value); });
    input.form && input.form.addEventListener("submit", () => {
      if (entry.value.trim()) { tags.push(...entry.value.split(",").map(norm).filter(Boolean)); input.value = tags.join(", "); }
    });
    sync();
  });

  // ---- summary page chart style (remembered per browser)
  const summary = $("#summary");
  if (summary) {
    const btns = $$(".view-switch [data-view]");
    const show = (view) => {
      if (!btns.some((b) => b.dataset.view === view)) view = btns[0].dataset.view;
      summary.dataset.view = view;
      btns.forEach((b) => b.setAttribute("aria-pressed", String(b.dataset.view === view)));
    };
    btns.forEach((b) => b.addEventListener("click", () => {
      show(b.dataset.view);
      try { localStorage.setItem("netinv-summary-view", b.dataset.view); } catch (e) {}
    }));
    show(summary.dataset.view);
  }

  // ---- admin info: live preview rendered by the server (same renderer as the header)
  $$("textarea[data-admin-input]").forEach((ta) => {
    const preview = $("[data-admin-preview]");
    const errEl = $("[data-admin-error]");
    const unsaved = $("[data-admin-unsaved]");
    const saved = ta.value;
    let timer, seq = 0;
    ta.addEventListener("input", () => {
      clearTimeout(timer);
      unsaved.hidden = ta.value.trim() === saved.trim();
      timer = setTimeout(async () => {
        const mine = ++seq;
        try {
          const data = await postJSON(ta.dataset.previewUrl, { text: ta.value });
          if (mine !== seq) return; // a newer request is on its way
          preview.innerHTML = data.html;
          errEl.textContent = data.error || "";
          errEl.hidden = !data.error;
          ta.closest(".field").classList.toggle("has-error", !!data.error);
        } catch (e) { /* keep the last preview */ }
      }, 200);
    });
  });

  // ---- copy-to-clipboard for read-only command lines
  $$("[data-copy]").forEach((btn) => {
    const src = $("[data-copy-src]", btn.parentElement);
    src.addEventListener("focus", () => src.select());
    btn.addEventListener("click", async () => {
      try {
        await navigator.clipboard.writeText(src.value);
      } catch (e) {
        src.select(); // clipboard API needs HTTPS; fall back to the old way
        if (!document.execCommand("copy")) { toast("Select the text and copy it", "err"); return; }
      }
      toast("Copied");
    });
  });

  localizeTimes();
  const tz = $(".tz-note");
  if (tz) {
    try { tz.textContent = ` (${Intl.DateTimeFormat().resolvedOptions().timeZone})`; } catch (e) {}
  }
})();
