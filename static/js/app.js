/*
  app.js -- small improvements on top of the HTML (loaded on every page with
  "defer": it runs after the page's HTML is parsed). The site still works
  without JavaScript; these only make it nicer.

  There is NO inline JavaScript in the templates (no onclick="", no
  onerror=""): everything is attached here with addEventListener. That allows
  a strict Content-Security-Policy (script-src 'self') -- Week 11.
*/

// Tell the CSS that JavaScript is running (used by the mobile menu).
document.documentElement.classList.add("js");


/* 1. Photo fallback -----------------------------------------------------
   If a place photo cannot load (dead link), show "Image unavailable".
   "error" events do not bubble, so we listen in the CAPTURE phase (true). */
function markMissing(img) {
  var box = img.closest(".photo");
  if (box) {
    box.classList.add("is-missing");
  }
}

document.addEventListener("error", function (event) {
  if (event.target.tagName === "IMG") {
    markMissing(event.target);
  }
}, true);

// Images that already failed BEFORE this script ran:
document.querySelectorAll(".photo img").forEach(function (img) {
  if (img.complete && img.naturalWidth === 0) {
    markMissing(img);
  }
});


/* 2. Confirm before destructive actions --------------------------------
   <form data-confirm="Delete this trip?"> asks first; Cancel = not sent. */
document.querySelectorAll("form[data-confirm]").forEach(function (form) {
  form.addEventListener("submit", function (event) {
    if (!window.confirm(form.dataset.confirm)) {
      event.preventDefault();
    }
  });
});


/* 3. Loading state -------------------------------------------------------
   Searching calls external APIs and can take a few seconds. Forms with
   data-loading="Searching…" disable their button and show the text; links
   with data-loading show the progress bar at the top of the page. */
function startLoading() {
  document.body.classList.add("is-loading");
}

document.querySelectorAll("form[data-loading]").forEach(function (form) {
  form.addEventListener("submit", function () {
    var button = form.querySelector("button[type=submit]");
    if (button) {
      button.dataset.label = button.textContent;
      button.textContent = form.dataset.loading;
      button.disabled = true;
    }
    startLoading();
  });
});

document.querySelectorAll("a[data-loading]").forEach(function (link) {
  link.addEventListener("click", startLoading);
});

// Coming back with the browser's Back button can show the page from memory:
// undo the loading state so the button works again.
window.addEventListener("pageshow", function () {
  document.body.classList.remove("is-loading");
  document.querySelectorAll("button[data-label]").forEach(function (button) {
    button.textContent = button.dataset.label;
    button.disabled = false;
  });
});


/* 4. Mobile menu ------------------------------------------------------- */
var toggle = document.querySelector(".nav-toggle");
if (toggle) {
  toggle.addEventListener("click", function () {
    var header = toggle.closest(".nav");
    var open = header.classList.toggle("open");
    toggle.setAttribute("aria-expanded", open ? "true" : "false");
  });
}
