/* =========================================================================
   Game Explorer - frontend logic
   Vanilla JavaScript only. Every request goes to our own Flask /api/*
   endpoints; the browser never talks to IGDB, Twitch or CheapShark.

   All API data is inserted with textContent / DOM nodes (see h()), never
   innerHTML, so a game title can't inject markup into the page.
   ========================================================================= */

"use strict";

// ---------- App state ----------
// Kept in one object so the Back button can restore results, filters and
// scroll position without re-fetching anything.
const state = {
  query: "",
  genre: "",
  mode: "",
  ordering: "",
  page: 1,
  hasNext: false,
  count: null,
  searched: false,   // filter changes only re-run a search after the first one
  scrollY: 0,        // browse-view scroll position saved when opening a game
  lastCard: null,    // card that opened the detail view (focus returns to it)
  screenshots: [],   // screenshots of the game shown in the detail view
  lightboxIndex: 0,
};

// Aborting the previous request means a slow, outdated response can never
// overwrite a newer one (e.g. changing the sort twice quickly).
let searchController = null;
let detailController = null;

// ---------- DOM references ----------
const $ = (id) => document.getElementById(id);

const els = {
  form: $("search-form"),
  query: $("query"),
  genre: $("genre"),
  mode: $("mode"),
  ordering: $("ordering"),
  formError: $("form-error"),
  meta: $("results-meta"),
  status: $("status"),
  results: $("results"),
  loadMore: $("load-more"),
  loadMoreError: $("load-more-error"),
  browseView: $("browse-view"),
  detailView: $("detail-view"),
  detailContent: $("detail-content"),
  backBtn: $("back-btn"),
  lightbox: $("lightbox"),
  lightboxImg: $("lightbox-img"),
  lightboxPrev: $("lightbox-prev"),
  lightboxNext: $("lightbox-next"),
  lightboxClose: $("lightbox-close"),
  lightboxCounter: $("lightbox-counter"),
};

// ===========================================================================
// Helpers
// ===========================================================================

/**
 * GET a JSON endpoint on our own backend.
 * Throws an Error carrying the server's {"error": "..."} message on failure.
 * Pass an AbortSignal to be able to cancel the request.
 */
async function apiGet(path, params = {}, signal) {
  const query = new URLSearchParams(
    Object.entries(params).filter(([, value]) => value !== "" && value != null)
  );
  const url = query.toString() ? `${path}?${query}` : path;

  let response;
  try {
    response = await fetch(url, { signal });
  } catch (err) {
    if (err.name === "AbortError") throw err;
    throw new Error("Can't reach the server. Check your connection and try again.");
  }

  let body = null;
  try {
    body = await response.json();
  } catch {
    // Non-JSON body (e.g. a proxy error page); handled below.
  }

  if (!response.ok) {
    throw new Error(body?.error || `Request failed (${response.status}).`);
  }
  return body;
}

/**
 * Create an element safely. Text is always added as text nodes.
 *   h("a", { class: "x", href: url, onclick: fn }, "label", childNode)
 * Attributes that are null/undefined/false are skipped; null children too.
 */
function h(tag, attrs = {}, ...children) {
  const el = document.createElement(tag);
  for (const [key, value] of Object.entries(attrs)) {
    if (value == null || value === false) continue;
    if (key === "class") el.className = value;
    else if (key === "text") el.textContent = value;
    else if (key.startsWith("on")) el.addEventListener(key.slice(2), value);
    else el.setAttribute(key, value === true ? "" : value);
  }
  // flat(Infinity): children may be nested arrays, e.g. [[dt, dd], [dt, dd]].
  for (const child of children.flat(Infinity)) {
    if (child == null || child === false) continue;
    el.append(child instanceof Node ? child : String(child));
  }
  return el;
}

/** Show or hide an element. */
function show(el, visible) {
  el.hidden = !visible;
}

const money = new Intl.NumberFormat("en-US", { style: "currency", currency: "USD" });
const longDate = new Intl.DateTimeFormat("en-US", {
  year: "numeric", month: "long", day: "numeric", timeZone: "UTC",
});
const shortDate = new Intl.DateTimeFormat("en-US", {
  year: "numeric", month: "short", day: "numeric", timeZone: "UTC",
});
const number = new Intl.NumberFormat("en-US");

/** "2017-02-24" -> "February 24, 2017" (dates are UTC, like the backend). */
function formatDate(iso, formatter = longDate) {
  return iso ? formatter.format(new Date(`${iso}T00:00:00Z`)) : null;
}

/** Colour band for a 0-100 score. */
function scoreClass(score) {
  if (score >= 75) return "score-high";
  if (score >= 50) return "score-mid";
  return "score-low";
}

// Static icon markup (not API data), so innerHTML is safe here.
const GAMEPAD_SVG = `
  <svg viewBox="0 0 24 24" width="48" height="48" fill="none" stroke="currentColor"
       stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
    <path d="M6 11h4M8 9v4M15 12h.01M18 10h.01"/>
    <path d="M17.32 5H6.68a4 4 0 0 0-3.98 3.59l-.9 7.1A3 3 0 0 0 4.78 19c1 0 1.9-.55 2.37-1.42L8 16h8l.85 1.58A2.7 2.7 0 0 0 19.22 19a3 3 0 0 0 2.98-3.31l-.9-7.1A4 4 0 0 0 17.32 5z"/>
  </svg>`;

function placeholderArt() {
  const div = h("div", { class: "art-placeholder", "aria-hidden": "true" });
  div.innerHTML = GAMEPAD_SVG;
  return div;
}

/** An <img> that swaps itself for a placeholder if there's no URL or it fails to load. */
function artwork(src, alt = "") {
  if (!src) return placeholderArt();
  const img = h("img", { src, alt, loading: "lazy", decoding: "async" });
  img.addEventListener("error", () => img.replaceWith(placeholderArt()), { once: true });
  return img;
}

/** Spinner with a caption. */
function loader(label) {
  return h("div", { class: "loader-block", role: "status" },
    h("div", { class: "spinner", "aria-hidden": "true" }),
    h("p", { text: label }));
}

/** Empty / error message box with an optional retry button. */
function messageBox(message, kind = "empty", onRetry = null) {
  return h("div", { class: `message-box message-${kind}`, role: kind === "error" ? "alert" : null },
    h("p", { text: message }),
    onRetry && h("button", { type: "button", class: "btn btn-secondary", onclick: onRetry }, "Try again"));
}

// ===========================================================================
// Filters
// ===========================================================================

async function loadFilters() {
  els.genre.disabled = true;
  els.mode.disabled = true;
  try {
    const { genres, modes } = await apiGet("/api/filters");
    fillSelect(els.genre, genres);
    fillSelect(els.mode, modes);
  } catch (err) {
    // Searching still works without the filters, so just explain.
    showFormError(`Couldn't load the genre and mode filters: ${err.message}`);
  } finally {
    els.genre.disabled = false;
    els.mode.disabled = false;
  }
}

function fillSelect(select, options) {
  for (const option of options) {
    select.append(new Option(option.name, option.id));
  }
}

function showFormError(message) {
  els.formError.textContent = message;
  show(els.formError, true);
}

function hideFormError() {
  show(els.formError, false);
}

// ===========================================================================
// Search
// ===========================================================================

function onSearchSubmit(event) {
  event.preventDefault();
  const query = els.query.value.trim();
  if (!query) {
    showFormError("Please enter a game name or keyword to search.");
    els.query.focus();
    return;
  }
  hideFormError();
  startSearch(query);
}

/** Changing genre / mode / sort re-runs the search from page 1. */
function onFilterChange() {
  if (!state.searched) return;
  // Use what's in the box, or fall back to the last keyword if it was cleared.
  const query = els.query.value.trim() || state.query;
  els.query.value = query;
  hideFormError();
  startSearch(query);
}

function startSearch(query) {
  Object.assign(state, {
    query,
    genre: els.genre.value,
    mode: els.mode.value,
    ordering: els.ordering.value,
    page: 1,
    searched: true,
  });
  fetchPage({ append: false });
}

function onLoadMore() {
  state.page += 1;
  fetchPage({ append: true });
}

/** Fetch state.page. append=false replaces the grid, true adds to it. */
async function fetchPage({ append }) {
  searchController?.abort();
  const controller = new AbortController();
  searchController = controller;

  setSearchLoading(true, append);
  try {
    const data = await apiGet("/api/search", {
      query: state.query,
      genre: state.genre,
      mode: state.mode,
      ordering: state.ordering,
      page: state.page,
    }, controller.signal);

    state.hasNext = data.has_next;
    state.count = data.count;
    renderResults(data.results, append);
  } catch (err) {
    if (err.name === "AbortError") return;  // a newer search replaced this one
    if (append) {
      state.page -= 1;  // so "Load more" retries the same page
      els.loadMoreError.textContent = err.message;
      show(els.loadMoreError, true);
    } else {
      renderSearchError(err.message);
    }
  } finally {
    // Only the latest request may change the loading state.
    if (searchController === controller) setSearchLoading(false, append);
  }
}

function setSearchLoading(loading, append) {
  if (append) {
    els.loadMore.disabled = loading;
    els.loadMore.classList.toggle("is-loading", loading);
    els.loadMore.textContent = loading ? "Loading…" : "Load more";
    if (loading) show(els.loadMoreError, false);
    return;
  }

  if (loading) {
    // Skeleton cards keep the layout stable while results load.
    show(els.status, false);
    show(els.loadMore, false);
    show(els.loadMoreError, false);
    els.meta.textContent = `Searching for “${state.query}”…`;
    els.results.setAttribute("aria-busy", "true");
    els.results.replaceChildren(...Array.from({ length: 12 }, skeletonCard));
  } else {
    els.results.removeAttribute("aria-busy");
  }
}

function renderResults(results, append) {
  if (!append) els.results.replaceChildren();

  if (!append && results.length === 0) {
    els.meta.textContent = "";
    els.status.replaceChildren(messageBox("No games found. Try a different search term."));
    show(els.status, true);
    show(els.loadMore, false);
    return;
  }

  els.results.append(...results.map(renderCard));
  els.meta.textContent = state.count != null
    ? `${number.format(state.count)} ${state.count === 1 ? "game" : "games"} found for “${state.query}”`
    : `Results for “${state.query}”`;
  show(els.loadMore, state.hasNext);
}

function renderSearchError(message) {
  els.results.replaceChildren();
  els.meta.textContent = "";
  els.status.replaceChildren(messageBox(message, "error", () => fetchPage({ append: false })));
  show(els.status, true);
  show(els.loadMore, false);
}

function skeletonCard() {
  return h("div", { class: "card skeleton", "aria-hidden": "true" },
    h("div", { class: "card-art" }),
    h("div", { class: "card-body" },
      h("div", { class: "sk-line sk-title" }),
      h("div", { class: "sk-line sk-short" }),
      h("div", { class: "sk-line" })));
}

// ---------- Cards ----------

const MAX_CARD_GENRES = 3;
const MAX_CARD_PLATFORMS = 5;

function renderCard(game) {
  const open = (event) => openDetail(game.id, event.currentTarget);

  return h("article", {
    class: "card",
    tabindex: "0",
    role: "button",
    "aria-label": `View details for ${game.name}`,
    onclick: open,
    onkeydown: (event) => {
      if (event.key === "Enter" || event.key === " ") {
        event.preventDefault();
        open(event);
      }
    },
  },
    h("div", { class: "card-art" },
      artwork(game.image),
      game.critics != null && h("span", {
        class: `critic-badge ${scoreClass(game.critics)}`,
        title: "Critic score (out of 100)",
      }, h("small", { text: "Critic" }), String(game.critics))),
    h("div", { class: "card-body" },
      h("h3", { class: "card-title", title: game.name, text: game.name }),
      h("div", { class: "card-meta" },
        h("span", { class: "card-year", text: game.year ?? "N/A" }),
        playerScore(game.rating)),
      chipList(game.genres.slice(0, MAX_CARD_GENRES), "chip"),
      game.modes.length > 0 && h("p", { class: "card-modes", text: game.modes.join(", ") }),
      platformChips(game.platforms)));
}

function playerScore(rating) {
  if (rating == null) return h("span", { class: "player-score muted", text: "No player score" });
  return h("span", { class: `player-score ${scoreClass(rating)}`, title: "Player score" },
    `★ ${rating}% of players`);
}

function chipList(items, className) {
  if (!items.length) return null;
  return h("ul", { class: "chips" }, items.map((item) => h("li", { class: className, text: item })));
}

function platformChips(platforms) {
  if (!platforms.length) return null;
  const visible = platforms.slice(0, MAX_CARD_PLATFORMS);
  const hidden = platforms.length - visible.length;
  const list = chipList(visible, "chip chip-platform");
  if (hidden > 0) {
    list.append(h("li", {
      class: "chip chip-platform chip-more",
      title: platforms.slice(MAX_CARD_PLATFORMS).join(", "),
      text: `+${hidden}`,
    }));
  }
  return list;
}

// ===========================================================================
// Detail view
// ===========================================================================

function openDetail(gameId, card) {
  // Save where we were. The browse view is hidden, not destroyed, so the
  // cards, filters and Load more state are all still there on Back.
  state.scrollY = window.scrollY;
  state.lastCard = card ?? null;

  show(els.browseView, false);
  show(els.detailView, true);
  window.scrollTo(0, 0);
  loadDetail(gameId);
}

async function loadDetail(gameId) {
  detailController?.abort();
  const controller = new AbortController();
  detailController = controller;

  els.detailContent.replaceChildren(loader("Loading game details…"));
  try {
    const game = await apiGet(`/api/game/${encodeURIComponent(gameId)}`, {}, controller.signal);
    renderDetail(game);
  } catch (err) {
    if (err.name === "AbortError") return;
    els.detailContent.replaceChildren(messageBox(err.message, "error", () => loadDetail(gameId)));
  }
}

function backToResults() {
  detailController?.abort();
  closeLightbox();
  show(els.detailView, false);
  show(els.browseView, true);
  els.detailContent.replaceChildren();

  // While hidden, the browse view had no height, so scrolling now would be
  // clamped to 0. Reading offsetHeight forces a layout first.
  void document.body.offsetHeight;
  window.scrollTo(0, state.scrollY);
  state.lastCard?.focus({ preventScroll: true });
}

function renderDetail(game) {
  state.screenshots = game.screenshots;

  els.detailContent.replaceChildren(
    renderHero(game),
    h("div", { class: "detail-layout" },
      h("div", { class: "detail-main" },
        detailSection("About", h("p", {
          class: "description",
          text: game.description || "No description available for this game.",
        })),
        game.screenshots.length > 0 &&
          detailSection(`Screenshots (${game.screenshots.length})`, renderGallery(game.screenshots)),
        detailSection("Prices", renderPrices(game.deals, game.deals_error))),
      h("aside", { class: "detail-side" },
        renderScores(game),
        renderFacts(game))));
}

function detailSection(title, ...content) {
  return h("section", { class: "detail-section" }, h("h3", { text: title }), ...content);
}

function renderHero(game) {
  const released = formatDate(game.released);
  return h("div", { class: "hero" },
    h("div", { class: "hero-image" }, artwork(game.image, `${game.name} artwork`)),
    h("div", { class: "hero-content" },
      game.cover && h("img", { class: "hero-cover", src: game.cover, alt: `${game.name} cover` }),
      h("div", { class: "hero-text" },
        h("h2", { class: "hero-title", text: game.name }),
        h("p", { class: "hero-date", text: released ? `Released ${released}` : "Release date unknown" }))));
}

function renderScores(game) {
  const box = (label, score, detail) => h("div", { class: "score-box" },
    h("span", { class: "score-label", text: label }),
    score != null
      ? h("span", { class: `score-value ${scoreClass(score)}`, text: detail.format(score) })
      : h("span", { class: "score-value muted", text: "N/A" }),
    h("span", { class: "score-detail", text: score != null ? detail.caption : detail.none }));

  return h("div", { class: "scores" },
    box("Player score", game.rating, {
      format: (s) => `${s}%`,
      caption: `${number.format(game.rating_count)} player ratings`,
      none: "Not enough ratings",
    }),
    box("Critic score", game.critics, {
      format: (s) => String(s),
      caption: `${number.format(game.critics_count)} critic ${game.critics_count === 1 ? "review" : "reviews"}`,
      none: "No critic reviews",
    }));
}

function renderFacts(game) {
  const list = (items) => (items.length ? items.join(", ") : "Unknown");
  const rows = [
    ["Developers", list(game.developers)],
    ["Publishers", list(game.publishers)],
    ["Genres", list(game.genres)],
    ["Platforms", list(game.platforms)],
    ["Game modes", list(game.modes)],
    ["ESRB rating", game.esrb ? h("span", { class: "esrb", text: game.esrb }) : "Not rated"],
  ];
  if (game.website) {
    rows.push(["Website", h("a", {
      href: game.website, target: "_blank", rel: "noopener noreferrer", text: "Official site ↗",
    })]);
  }
  return h("dl", { class: "facts" },
    rows.map(([label, value]) => [h("dt", { text: label }), h("dd", {}, value)]));
}

function renderGallery(screenshots) {
  return h("div", { class: "gallery" },
    screenshots.map((shot, index) => h("button", {
      type: "button",
      class: "thumb",
      "aria-label": `Open screenshot ${index + 1} of ${screenshots.length}`,
      onclick: () => openLightbox(index),
    }, artwork(shot.thumb || shot.image))));
}

// ---------- Prices ----------

function renderPrices(deals, dealsError) {
  if (dealsError) return messageBox("Prices unavailable right now.", "warning");
  if (!deals) return messageBox("No price data available for this game.");

  // The backend already sorts; sorting a copy here keeps the table correct
  // even if that ever changes.
  const offers = [...deals.offers].sort((a, b) => a.price - b.price);
  const lowest = deals.cheapest_ever;

  return h("div", { class: "prices" },
    lowest && h("p", { class: "all-time-low" },
      "All-time lowest price: ",
      h("strong", { text: money.format(lowest.price) }),
      lowest.date && ` on ${formatDate(lowest.date, shortDate)}`),
    h("div", { class: "table-wrap" },
      h("table", { class: "price-table" },
        h("thead", {}, h("tr", {},
          ["Store", "Sale price", "Regular price", "Savings", ""].map((label) => h("th", { scope: "col", text: label })))),
        h("tbody", {}, offers.map(renderOfferRow)))));
}

function renderOfferRow(offer) {
  const discounted = offer.retail_price != null && offer.retail_price > offer.price;
  const storeIcon = offer.icon && h("img", { class: "store-icon", src: offer.icon, alt: "", width: 16, height: 16 });
  storeIcon?.addEventListener("error", () => storeIcon.remove(), { once: true });

  return h("tr", { class: offer.is_cheapest ? "cheapest" : null },
    h("td", {},
      h("span", { class: "store" }, storeIcon, offer.store),
      offer.is_cheapest && h("span", { class: "best-tag", text: "Best price" })),
    h("td", { class: "price", text: money.format(offer.price) }),
    h("td", { class: discounted ? "retail strike" : "retail" },
      offer.retail_price != null ? money.format(offer.retail_price) : "—"),
    h("td", {}, offer.savings ? h("span", { class: "savings", text: `-${offer.savings}%` }) : "—"),
    h("td", { class: "buy-cell" },
      h("a", {
        class: "btn btn-primary btn-small",
        href: offer.url,
        target: "_blank",
        rel: "noopener noreferrer",
        "aria-label": `Buy at ${offer.store} (opens in a new tab)`,
        text: "Buy",
      })));
}

// ===========================================================================
// Lightbox
// ===========================================================================

let lightboxOpener = null;  // thumbnail to refocus when the lightbox closes

function openLightbox(index) {
  if (!state.screenshots.length) return;
  lightboxOpener = document.activeElement;
  state.lightboxIndex = index;
  updateLightbox();
  show(els.lightbox, true);
  document.body.classList.add("no-scroll");
  els.lightboxClose.focus();
}

function closeLightbox() {
  if (els.lightbox.hidden) return;
  show(els.lightbox, false);
  document.body.classList.remove("no-scroll");
  els.lightboxImg.removeAttribute("src");
  lightboxOpener?.focus?.();
}

function stepLightbox(delta) {
  const total = state.screenshots.length;
  state.lightboxIndex = (state.lightboxIndex + delta + total) % total;  // wrap around
  updateLightbox();
}

function updateLightbox() {
  const total = state.screenshots.length;
  const shot = state.screenshots[state.lightboxIndex];
  els.lightboxImg.src = shot.image;
  els.lightboxImg.alt = `Screenshot ${state.lightboxIndex + 1} of ${total}`;
  els.lightboxCounter.textContent = `${state.lightboxIndex + 1} / ${total}`;
  show(els.lightboxPrev, total > 1);
  show(els.lightboxNext, total > 1);
}

// Attached once at start-up. It does nothing while the lightbox is closed,
// so opening it many times never stacks up duplicate handlers.
function onKeyDown(event) {
  if (els.lightbox.hidden) return;
  if (event.key === "Escape") closeLightbox();
  else if (event.key === "ArrowLeft") stepLightbox(-1);
  else if (event.key === "ArrowRight") stepLightbox(1);
  else return;
  event.preventDefault();
}

// ===========================================================================
// Initialisation
// ===========================================================================

function init() {
  els.form.addEventListener("submit", onSearchSubmit);
  els.query.addEventListener("input", hideFormError);
  for (const select of [els.genre, els.mode, els.ordering]) {
    select.addEventListener("change", onFilterChange);
  }
  els.loadMore.addEventListener("click", onLoadMore);
  els.backBtn.addEventListener("click", backToResults);

  els.lightboxClose.addEventListener("click", closeLightbox);
  els.lightboxPrev.addEventListener("click", () => stepLightbox(-1));
  els.lightboxNext.addEventListener("click", () => stepLightbox(1));
  els.lightbox.addEventListener("click", (event) => {
    if (event.target === els.lightbox) closeLightbox();  // click on the backdrop
  });
  document.addEventListener("keydown", onKeyDown);

  loadFilters();
  els.query.focus();
}

document.addEventListener("DOMContentLoaded", init);
