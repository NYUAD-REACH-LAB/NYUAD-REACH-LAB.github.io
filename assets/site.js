/* REACH Lab — theme toggle, mobile navigation, publication filter, copy BibTeX. Nothing else. */
(function () {
  var root = document.documentElement;

  // Theme: an explicit choice is stored; otherwise the system setting applies.
  var themeButton = document.querySelector(".theme-toggle");
  if (themeButton) {
    var media = window.matchMedia("(prefers-color-scheme: dark)");
    var current = function () {
      return root.getAttribute("data-theme") || (media.matches ? "dark" : "light");
    };
    var label = function () {
      themeButton.setAttribute("aria-label", current() === "dark" ? "Switch to light theme" : "Switch to dark theme");
    };
    themeButton.hidden = false;
    label();
    themeButton.addEventListener("click", function () {
      var next = current() === "dark" ? "light" : "dark";
      root.setAttribute("data-theme", next);
      try { localStorage.setItem("reach-theme", next); } catch (err) {}
      label();
    });
    media.addEventListener("change", label);
  }

  // Mobile navigation.
  var navButton = document.querySelector(".nav-toggle");
  var nav = document.getElementById("site-nav");
  if (navButton && nav) {
    root.classList.add("nav-ready");
    navButton.hidden = false;
    navButton.addEventListener("click", function () {
      var open = nav.classList.toggle("is-open");
      navButton.setAttribute("aria-expanded", open ? "true" : "false");
    });
    document.addEventListener("keydown", function (event) {
      if (event.key === "Escape" && nav.classList.contains("is-open")) {
        nav.classList.remove("is-open");
        navButton.setAttribute("aria-expanded", "false");
        navButton.focus();
      }
    });
  }

  // Publication filter (publications page only; the full list reads without it).
  var filter = document.querySelector("[data-pub-filter]");
  if (filter) {
    filter.hidden = false;
    var items = document.querySelectorAll(".pub[data-fields]");
    var groups = document.querySelectorAll("[data-year-group]");
    var status = document.querySelector("[data-pub-count]");
    filter.addEventListener("change", function (event) {
      var value = event.target.value;
      var shown = 0;
      items.forEach(function (item) {
        var match = value === "all" || (" " + item.getAttribute("data-fields") + " ").indexOf(" " + value + " ") !== -1;
        item.hidden = !match;
        if (match) shown += 1;
      });
      groups.forEach(function (group) {
        group.hidden = !group.querySelector(".pub:not([hidden])");
      });
      if (status) status.textContent = shown + (shown === 1 ? " publication" : " publications");
    });
  }
  // Copy BibTeX (publications page only): each entry carries its BibTeX in a hidden <pre data-bib>;
  // the button is added here, so without the script the page has no dead control.
  document.querySelectorAll(".pub > pre[data-bib]").forEach(function (pre) {
    var item = pre.parentNode;
    var list = item.querySelector(".pub-links");
    if (!list) {
      list = document.createElement("ul");
      list.className = "pub-links";
      pre.parentNode.insertBefore(list, pre);
    }
    var title = item.querySelector(".pub-title");
    var button = document.createElement("button");
    button.type = "button";
    button.className = "link-badge pub-copy";
    button.textContent = "Copy BibTeX";
    if (title) button.setAttribute("aria-label", "Copy BibTeX for " + title.textContent);
    var li = document.createElement("li");
    li.appendChild(button);
    list.appendChild(li);
    var reset;
    var done = function (ok) {
      button.textContent = ok ? "Copied" : "Copy failed";
      clearTimeout(reset);
      reset = setTimeout(function () { button.textContent = "Copy BibTeX"; }, 2000);
    };
    var fallback = function () {
      var area = document.createElement("textarea");
      area.value = pre.textContent;
      area.setAttribute("readonly", "");
      area.style.position = "fixed";
      area.style.opacity = "0";
      document.body.appendChild(area);
      area.select();
      var ok = false;
      try { ok = document.execCommand("copy"); } catch (err) {}
      document.body.removeChild(area);
      done(ok);
    };
    button.addEventListener("click", function () {
      if (navigator.clipboard && window.isSecureContext) {
        navigator.clipboard.writeText(pre.textContent).then(function () { done(true); }, fallback);
      } else {
        fallback();
      }
    });
  });
})();
