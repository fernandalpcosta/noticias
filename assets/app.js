/* Notícias — lê data/news.json e monta a página */
(function () {
  "use strict";

  const $ = (sel) => document.querySelector(sel);
  const state = { data: null, region: "tudo", query: "", openChip: null };

  const LANG = { en: "EN", es: "ES", fr: "FR", pt: "PT", de: "DE" };

  // ---------- utilidades ----------
  const esc = (s) =>
    String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

  const norm = (s) => String(s || "").normalize("NFD").replace(/[̀-ͯ]/g, "").toLowerCase();

  function highlight(text, q) {
    const safe = esc(text);
    if (!q) return safe;
    const words = q.split(/\s+/).filter((w) => w.length > 1).map((w) => w.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"));
    if (!words.length) return safe;
    return safe.replace(new RegExp("(" + words.join("|") + ")", "gi"), "<mark>$1</mark>");
  }

  const rtf = new Intl.RelativeTimeFormat("pt-BR", { numeric: "auto" });
  function ago(iso) {
    if (!iso) return "";
    const diff = (new Date(iso).getTime() - Date.now()) / 1000;
    const abs = Math.abs(diff);
    if (abs < 60) return "agora";
    if (abs < 3600) return rtf.format(Math.round(diff / 60), "minute");
    if (abs < 86400) return rtf.format(Math.round(diff / 3600), "hour");
    return rtf.format(Math.round(diff / 86400), "day");
  }

  const safeUrl = (u) => (/^https?:\/\//i.test(u || "") ? u : "#");

  // ---------- tema ----------
  try {
    const saved = localStorage.getItem("theme");
    if (saved) document.documentElement.dataset.theme = saved;
  } catch (e) {}
  $("#theme").addEventListener("click", () => {
    const root = document.documentElement;
    const isDark = root.dataset.theme
      ? root.dataset.theme === "dark"
      : matchMedia("(prefers-color-scheme: dark)").matches;
    root.dataset.theme = isDark ? "light" : "dark";
    try { localStorage.setItem("theme", root.dataset.theme); } catch (e) {}
  });

  const today = new Date().toLocaleDateString("pt-BR", {
    weekday: "long", day: "numeric", month: "long", year: "numeric",
  });
  $("#today").textContent = today.charAt(0).toUpperCase() + today.slice(1);

  $("#more").addEventListener("click", () => $("#briefing").classList.remove("collapsed"));

  // ---------- render ----------
  function renderBriefing(b) {
    if (!b || !b.topics || !b.topics.length) return;
    $("#briefing-intro").textContent = b.intro || "";
    $("#briefing-list").innerHTML = b.topics.map((t) => `
      <li>
        <h3>${esc(t.title)}</h3>
        <p>${esc(t.summary)}</p>
        ${t.links && t.links.length ? `<div class="refs">${t.links.map((l) =>
          `<a href="${esc(safeUrl(l.link))}" target="_blank" rel="noopener" title="${esc(l.title)}">${esc(l.source)}</a>`).join("")}</div>` : ""}
      </li>`).join("");
    if (b.topics.length <= 3) $("#briefing").classList.remove("collapsed");
    $("#briefing").hidden = false;
  }

  function renderTrending(list) {
    if (!list || !list.length) return;
    $("#chips").innerHTML = list.map((t, i) => `
      <button class="chip" type="button" role="listitem" aria-expanded="false" data-i="${i}">
        ${esc(t.topic)} <span class="n" title="aparece em ${t.sources} jornais">${t.sources}</span>
      </button>`).join("");
    $("#trending").hidden = false;

    $("#chips").addEventListener("click", (ev) => {
      const btn = ev.target.closest(".chip");
      if (!btn) return;
      const i = Number(btn.dataset.i);
      const panel = $("#chip-panel");
      document.querySelectorAll(".chip").forEach((c) => c.setAttribute("aria-expanded", "false"));
      if (state.openChip === i) {
        state.openChip = null;
        panel.hidden = true;
        return;
      }
      state.openChip = i;
      btn.setAttribute("aria-expanded", "true");
      const t = list[i];
      panel.innerHTML = `<ul>${t.examples.map((e) => `
        <li><a href="${esc(safeUrl(e.link))}" target="_blank" rel="noopener">${esc(e.title)}</a>
        <span class="src">${esc(e.source)}</span></li>`).join("")}</ul>`;
      panel.hidden = false;
    });
  }

  function renderTabs(regions) {
    const all = [{ id: "tudo", label: "Tudo" }, ...regions];
    $("#tabs").innerHTML = all.map((r) => `
      <button class="tab" type="button" role="tab" data-r="${esc(r.id)}" aria-selected="${r.id === state.region}">${esc(r.label)}</button>`).join("");
    $("#tabs").addEventListener("click", (ev) => {
      const btn = ev.target.closest(".tab");
      if (!btn) return;
      state.region = btn.dataset.r;
      document.querySelectorAll(".tab").forEach((t) => t.setAttribute("aria-selected", String(t === btn)));
      renderFeed();
    });
  }

  function storyHTML(it, lead, q) {
    const img = lead && it.image
      ? `<img class="img" src="${esc(safeUrl(it.image))}" alt="" loading="lazy" referrerpolicy="no-referrer" onerror="this.remove()">`
      : "";
    const summary = it.summary && (lead || q) ? `<p class="s">${highlight(it.summary, q)}</p>` : "";
    return `
      <li class="story${lead ? " lead" : ""}">
        <a href="${esc(safeUrl(it.link))}" target="_blank" rel="noopener">
          ${img}
          <h3 class="h">${highlight(it.title, q)}</h3>
          ${summary}
          ${it.published ? `<time class="t" datetime="${esc(it.published)}">${ago(it.published)}</time>` : ""}
        </a>
      </li>`;
  }

  function renderFeed() {
    const d = state.data;
    const q = state.query.trim();
    const nq = norm(q);
    const regions = d.regions.filter((r) => state.region === "tudo" || r.id === state.region);

    let shown = 0;
    const html = regions.map((r) => {
      const papers = d.sources.filter((s) => s.region === r.id).map((s) => {
        const items = nq ? s.items.filter((it) => norm(it.title + " " + it.summary).includes(nq)) : s.items;
        if (!items.length) return "";
        shown += items.length;
        return `
          <article class="paper">
            <header class="paper-head">
              <span class="paper-name">${esc(s.name)}</span>
              <span class="paper-meta">${esc(s.country)}<span class="lang">${esc(LANG[s.lang] || s.lang)}</span></span>
            </header>
            <ul class="stories">${items.map((it, i) => storyHTML(it, i === 0 && !nq, q)).join("")}</ul>
          </article>`;
      }).join("");
      if (!papers.trim()) return "";
      return `<section class="region"><h2 class="region-title">${esc(r.label)}</h2><div class="grid">${papers}</div></section>`;
    }).join("");

    $("#feed").innerHTML = shown
      ? html
      : `<div class="state"><p>Nenhuma manchete encontrada${q ? ` para “${esc(q)}”` : ""}.</p></div>`;
  }

  function renderMeta(d) {
    const total = d.sources.reduce((n, s) => n + s.items.length, 0);
    $("#count").textContent = `${total} manchetes de ${d.sources.length} jornais`;
    $("#updated").textContent = `Atualizado ${ago(d.updated)}`;
    $("#updated").title = new Date(d.updated).toLocaleString("pt-BR");
    if (d.failed && d.failed.length) {
      $("#failed").textContent = `Sem resposta nesta edição: ${d.failed.map((f) => f.name).join(", ")}.`;
    }
  }

  // ---------- busca ----------
  let t;
  $("#q").addEventListener("input", (ev) => {
    clearTimeout(t);
    t = setTimeout(() => { state.query = ev.target.value; renderFeed(); }, 120);
  });

  // ---------- carregar ----------
  fetch("data/news.json?v=" + Date.now(), { cache: "no-store" })
    .then((r) => { if (!r.ok) throw new Error(r.status); return r.json(); })
    .then((d) => {
      state.data = d;
      renderMeta(d);
      renderBriefing(d.briefing);
      renderTrending(d.trending);
      renderTabs(d.regions);
      renderFeed();
    })
    .catch(() => {
      $("#updated").textContent = "Primeira edição a caminho";
      $("#feed").innerHTML = `
        <div class="state">
          <div class="press" aria-hidden="true"></div>
          <p>A primeira edição ainda está sendo impressa.</p>
          <small>O GitHub busca as manchetes automaticamente. Volte em alguns minutos.</small>
        </div>`;
    });
})();
