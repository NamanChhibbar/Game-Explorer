/* =========================================================================
   Game Explorer - frontend logic
   Vanilla JavaScript only. Every request goes to our own Flask /api/*
   endpoints; the browser never talks to IGDB, Twitch or CheapShark.
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
  results: [],
  scrollY: 0,
};

// ---------- DOM references ----------
const $ = (id) => document.getElementById(id);

const els = {
  form: $("search-form"),
  query: $("query"),
  genre: $("genre"),
  mode: $("mode"),
  ordering: $("ordering"),
  formError: $("form-error"),
  status: $("status"),
  results: $("results"),
  loader: $("loader"),
  loadMore: $("load-more"),
  browseView: $("browse-view"),
  detailView: $("detail-view"),
  detailContent: $("detail-content"),
  backBtn: $("back-btn"),
};

// ---------- Helpers ----------

/**
 * GET a JSON endpoint on our own backend.
 * Throws an Error carrying the server's {"error": "..."} message on failure.
 */
async function apiGet(path, params = {}) {
  const query = new URLSearchParams(
    Object.entries(params).filter(([, value]) => value !== "" && value != null)
  );
  const url = query.toString() ? `${path}?${query}` : path;

  const response = await fetch(url);
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

/** Show or hide an element. */
function show(el, visible) {
  el.hidden = !visible;
}

// ---------- Initialisation ----------

function init() {
  // Search form, filters, Load more, detail view and lightbox handlers
  // are added as each feature is built.
  console.log("Game Explorer loaded");
}

document.addEventListener("DOMContentLoaded", init);
