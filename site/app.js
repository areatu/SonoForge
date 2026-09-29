/* SonoForge landing page — progressive enhancement only.
   Everything on the page works without this file; the script adds:
   language toggle, OS-aware download buttons (GitHub Releases API), copy buttons,
   tabs, poster→video media facade with GIF fallback, lightbox, reveal-on-scroll. */
(function () {
  "use strict";

  var REPO = "areatu/SonoForge";
  var API = "https://api.github.com/repos/" + REPO;
  var RELEASES_URL = "https://github.com/" + REPO + "/releases";
  var doc = document;
  var root = doc.documentElement;

  /* ---------------- Language ---------------- */
  var STRINGS = {
    en: {
      title: "SonoForge — Open-source desktop echocardiography analysis",
      description: "SonoForge is a free, open-source desktop application for echocardiography analysis: DICOM viewer, cardiac and Doppler measurements, AI segmentation, PACS connectivity and clinical PDF reports. Windows, Linux, macOS. Works offline.",
      downloadFor: { linux: "Download for Linux", windows: "Download for Windows", macos: "Download for macOS", generic: "Download" },
      help: "https://github.com/" + REPO + "/blob/main/docs/HELP_EN.md",
      presenter: "https://github.com/" + REPO + "/blob/main/build/presenter/README.md",
      copied: "Copied", copy: "Copy", gifFallback: "GIF preview", published: "released"
    },
    ru: {
      title: "SonoForge — открытая платформа для анализа эхокардиографии",
      description: "SonoForge — бесплатное открытое десктопное приложение для анализа эхокардиографии: просмотр DICOM, кардиологические и допплеровские измерения, AI-сегментация, подключение к PACS и клинические PDF-отчёты. Windows, Linux, macOS. Работает офлайн.",
      downloadFor: { linux: "Скачать для Linux", windows: "Скачать для Windows", macos: "Скачать для macOS", generic: "Скачать" },
      help: "https://github.com/" + REPO + "/blob/main/docs/HELP_RU.md",
      presenter: "https://github.com/" + REPO + "/blob/main/build/presenter/README_RU.md",
      copied: "Скопировано", copy: "Копировать", gifFallback: "GIF-превью", published: "выпущен"
    }
  };

  function detectLang() {
    var q = new URLSearchParams(location.search).get("lang");
    if (q === "en" || q === "ru") return q;
    try {
      var saved = localStorage.getItem("sonoforge.lang");
      if (saved === "en" || saved === "ru") return saved;
    } catch (e) { /* storage disabled */ }
    var nav = (navigator.languages && navigator.languages[0]) || navigator.language || "en";
    return /^ru\b/i.test(nav) ? "ru" : "en";
  }

  var currentLang = "en";
  var lastReleases = null; // re-render release metadata (dates, labels) when the language changes
  function setLang(lang, persist) {
    currentLang = lang;
    root.setAttribute("data-lang", lang);
    root.setAttribute("lang", lang);
    doc.title = STRINGS[lang].title;
    var meta = doc.querySelector('meta[name="description"]');
    if (meta) meta.setAttribute("content", STRINGS[lang].description);
    doc.querySelectorAll("[data-set-lang]").forEach(function (b) {
      b.setAttribute("aria-pressed", String(b.getAttribute("data-set-lang") === lang));
    });
    doc.querySelectorAll("[data-doc-help]").forEach(function (a) { a.href = STRINGS[lang].help; });
    doc.querySelectorAll("[data-doc-presenter]").forEach(function (a) { a.href = STRINGS[lang].presenter; });
    updateCtaLabel();
    if (lastReleases) applyReleases(lastReleases);
    if (persist) {
      try { localStorage.setItem("sonoforge.lang", lang); } catch (e) { /* ignore */ }
    }
  }
  doc.querySelectorAll("[data-set-lang]").forEach(function (b) {
    b.addEventListener("click", function () { setLang(b.getAttribute("data-set-lang"), true); });
  });

  /* ---------------- OS detection ---------------- */
  function detectOS() {
    var ua = navigator.userAgent || "";
    var plat = (navigator.userAgentData && navigator.userAgentData.platform) || navigator.platform || "";
    var s = (plat + " " + ua).toLowerCase();
    if (/android|iphone|ipad|ipod/.test(s)) return "generic"; // no desktop build for mobile
    if (/win/.test(s)) return "windows";
    if (/mac/.test(s)) return "macos";
    if (/linux|x11|cros/.test(s)) return "linux";
    return "generic";
  }
  var os = detectOS();
  var osToAsset = { linux: "deb", windows: "windows", macos: "macos" };

  var ctaLabelEl = doc.querySelector("[data-cta-label]");
  function updateCtaLabel() {
    if (!ctaLabelEl) return;
    var labels = STRINGS[currentLang].downloadFor;
    ctaLabelEl.textContent = labels[os] || labels.generic;
  }

  /* ---------------- Tabs ---------------- */
  doc.querySelectorAll("[data-tabs]").forEach(function (tabs) {
    var list = tabs.querySelectorAll('[role="tab"]');
    var panels = tabs.querySelectorAll('[role="tabpanel"]');
    function select(tab) {
      list.forEach(function (t) { t.setAttribute("aria-selected", String(t === tab)); t.tabIndex = t === tab ? 0 : -1; });
      panels.forEach(function (p) { p.hidden = p.id !== tab.getAttribute("aria-controls"); });
    }
    list.forEach(function (t, i) {
      t.addEventListener("click", function () { select(t); });
      t.addEventListener("keydown", function (e) {
        var dir = e.key === "ArrowRight" ? 1 : e.key === "ArrowLeft" ? -1 : 0;
        if (!dir) return;
        e.preventDefault();
        var next = list[(i + dir + list.length) % list.length];
        next.focus(); select(next);
      });
    });
    var detected = tabs.querySelector('[role="tab"][data-os="' + os + '"]');
    if (detected) { detected.classList.add("detected"); select(detected); }
  });

  /* ---------------- Copy buttons ---------------- */
  doc.querySelectorAll("[data-code]").forEach(function (box) {
    var btn = box.querySelector(".copy");
    var code = box.querySelector("code");
    if (!btn || !code) return;
    btn.title = STRINGS[currentLang].copy;
    btn.addEventListener("click", function () {
      var text = code.innerText.replace(/\n{3,}/g, "\n\n");
      var done = function () {
        btn.classList.add("copied");
        btn.innerHTML = '<svg class="ic ic-xs"><use href="#i-check"/></svg>';
        btn.setAttribute("aria-label", STRINGS[currentLang].copied);
        setTimeout(function () {
          btn.classList.remove("copied");
          btn.innerHTML = '<svg class="ic ic-xs"><use href="#i-copy"/></svg>';
          btn.setAttribute("aria-label", STRINGS[currentLang].copy);
        }, 1600);
      };
      if (navigator.clipboard && navigator.clipboard.writeText) {
        navigator.clipboard.writeText(text).then(done, function () { legacyCopy(text); done(); });
      } else { legacyCopy(text); done(); }
    });
  });
  function legacyCopy(text) {
    var ta = doc.createElement("textarea");
    ta.value = text; ta.setAttribute("readonly", ""); ta.style.position = "fixed"; ta.style.opacity = "0";
    doc.body.appendChild(ta); ta.select();
    try { doc.execCommand("copy"); } catch (e) { /* ignore */ }
    doc.body.removeChild(ta);
  }

  /* ---------------- GitHub API (releases, stars) ---------------- */
  function cachedJSON(url, ttlMs) {
    var key = "sonoforge.cache:" + url;
    try {
      var hit = JSON.parse(sessionStorage.getItem(key) || "null");
      if (hit && Date.now() - hit.t < ttlMs) return Promise.resolve(hit.v);
    } catch (e) { /* ignore */ }
    return fetch(url, { headers: { Accept: "application/vnd.github+json" } }).then(function (r) {
      if (!r.ok) throw new Error("HTTP " + r.status);
      return r.json();
    }).then(function (v) {
      try { sessionStorage.setItem(key, JSON.stringify({ t: Date.now(), v: v })); } catch (e) { /* ignore */ }
      return v;
    });
  }

  var matchers = {
    deb: function (n) { return /\.deb$/i.test(n); },
    windows: function (n) { return /\.exe$/i.test(n) && !/presenter/i.test(n); },
    macos: function (n) { return /\.(dmg|zip)$/i.test(n) && /mac/i.test(n); },
    "presenter-win": function (n) { return /presenter/i.test(n) && /\.exe$/i.test(n); },
    "presenter-linux": function (n) { return /presenter/i.test(n) && /\.appimage$/i.test(n); }
  };

  function fmtSize(bytes) {
    if (!bytes) return "";
    var mb = bytes / 1048576;
    return (mb >= 100 ? Math.round(mb) : mb.toFixed(1)) + " MB";
  }
  function fmtDate(iso) {
    try { return new Date(iso).toLocaleDateString(currentLang === "ru" ? "ru-RU" : "en-GB", { year: "numeric", month: "short", day: "numeric" }); }
    catch (e) { return iso.slice(0, 10); }
  }

  function applyReleases(releases) {
    lastReleases = releases;
    var stable = releases.filter(function (r) { return !r.draft && !r.prerelease; });
    var latest = stable[0] || releases[0];
    if (!latest) return;

    doc.querySelectorAll("[data-release-tag]").forEach(function (el) { el.textContent = latest.tag_name; });
    doc.querySelectorAll("[data-release-date]").forEach(function (el) {
      el.textContent = "(" + STRINGS[currentLang].published + " " + fmtDate(latest.published_at || latest.created_at) + ")";
    });

    // Find each asset kind: prefer the latest stable release, then walk back through newer→older releases
    // (the Presenter build may be attached to a dedicated release).
    var found = {};
    Object.keys(matchers).forEach(function (kind) {
      var list = [latest].concat(releases.filter(function (r) { return r !== latest && !r.draft; }));
      for (var i = 0; i < list.length && !found[kind]; i++) {
        var a = (list[i].assets || []).filter(function (x) { return matchers[kind](x.name); })[0];
        if (a) found[kind] = { asset: a, release: list[i] };
      }
    });

    doc.querySelectorAll("[data-asset]").forEach(function (a) {
      var hit = found[a.getAttribute("data-asset")];
      var meta = a.querySelector("[data-asset-meta]");
      if (hit) {
        a.href = hit.asset.browser_download_url;
        a.setAttribute("download", "");
        a.title = hit.asset.name;
        if (meta) meta.textContent = hit.release.tag_name + " · " + fmtSize(hit.asset.size);
      } else {
        a.href = RELEASES_URL;
      }
    });

    // Hero CTA follows the detected OS.
    var cta = doc.getElementById("cta-download");
    var kind = osToAsset[os];
    var hit = kind && found[kind];
    if (cta) {
      var m = cta.querySelector("[data-cta-meta]");
      if (hit) {
        cta.href = hit.asset.browser_download_url;
        cta.title = hit.asset.name;
        if (m) m.textContent = hit.release.tag_name + " · " + fmtSize(hit.asset.size);
      } else {
        cta.href = latest.html_url || RELEASES_URL;
        if (m) m.textContent = latest.tag_name;
      }
    }

    // Exact wget line for the .deb snippet.
    var debCmd = doc.querySelector('[data-asset-cmd="deb"]');
    if (debCmd && found.deb) {
      debCmd.textContent = "wget " + found.deb.asset.browser_download_url;
      debCmd.classList.remove("c");
    }
  }

  cachedJSON(API + "/releases?per_page=20", 30 * 60 * 1000).then(applyReleases).catch(function () { /* static links stay */ });

  cachedJSON(API, 30 * 60 * 1000).then(function (repo) {
    var el = doc.getElementById("star-count");
    if (!el || typeof repo.stargazers_count !== "number") return;
    el.querySelector("[data-stars]").textContent = String(repo.stargazers_count);
    el.hidden = false;
  }).catch(function () { /* stay hidden */ });

  /* ---------------- Media facade: poster → <video>, GIF fallback ---------------- */
  doc.querySelectorAll(".media[data-video]").forEach(function (fig) {
    var btn = fig.querySelector(".media-play");
    var img = fig.querySelector("img");
    if (!btn || !img) return;
    btn.addEventListener("click", function () {
      btn.disabled = true;
      var video = doc.createElement("video");
      video.muted = true; video.loop = true; video.autoplay = true; video.playsInline = true; video.controls = true;
      video.preload = "auto"; video.poster = img.currentSrc || img.src;
      video.width = img.width; video.height = img.height;
      video.setAttribute("aria-label", img.alt);
      var src = doc.createElement("source");
      src.src = fig.getAttribute("data-video"); src.type = "video/mp4";
      var fellBack = false;
      function fallbackToGif() {
        if (fellBack) return;
        fellBack = true;
        var gif = doc.createElement("img");
        gif.src = fig.getAttribute("data-gif"); gif.alt = img.alt;
        gif.width = img.width; gif.height = img.height;
        var note = doc.createElement("span");
        note.className = "fallback-note"; note.textContent = STRINGS[currentLang].gifFallback;
        video.replaceWith(gif); fig.appendChild(note);
      }
      src.addEventListener("error", fallbackToGif);   // fires when the MP4 is missing (404)
      video.addEventListener("error", fallbackToGif);
      video.appendChild(src);
      img.replaceWith(video);
      btn.remove();
      fig.classList.add("is-playing");
      var p = video.play();
      if (p && p.catch) p.catch(function () { video.controls = true; });
    });
  });

  /* ---------------- Lightbox ---------------- */
  var lb = doc.getElementById("lightbox");
  if (lb && typeof lb.showModal === "function") {
    var lbImg = lb.querySelector("img");
    var lbCap = lb.querySelector(".lightbox-cap");
    doc.querySelectorAll("[data-lightbox]").forEach(function (a) {
      a.addEventListener("click", function (e) {
        if (e.metaKey || e.ctrlKey || e.shiftKey || e.button === 1) return; // let "open in new tab" work
        e.preventDefault();
        var thumb = a.querySelector("img");
        lbImg.src = a.href; lbImg.alt = thumb ? thumb.alt : "";
        var cap = a.querySelector('.shot-cap [lang="' + currentLang + '"]') || a.querySelector(".shot-cap");
        lbCap.textContent = cap ? cap.textContent : "";
        lb.showModal();
      });
    });
    lb.querySelector(".lightbox-close").addEventListener("click", function () { lb.close(); });
    lb.addEventListener("click", function (e) { if (e.target === lb) lb.close(); });
    lb.addEventListener("close", function () { lbImg.removeAttribute("src"); });
  }

  /* ---------------- Reveal on scroll + active nav ---------------- */
  var reveals = doc.querySelectorAll(".reveal");
  if ("IntersectionObserver" in window && !matchMedia("(prefers-reduced-motion: reduce)").matches) {
    var io = new IntersectionObserver(function (entries) {
      entries.forEach(function (en) { if (en.isIntersecting) { en.target.classList.add("in"); io.unobserve(en.target); } });
    }, { rootMargin: "0px 0px -8% 0px", threshold: 0.08 });
    reveals.forEach(function (el) { io.observe(el); });

    var links = Array.prototype.slice.call(doc.querySelectorAll(".nav-links a[href^='#']"));
    var sections = links.map(function (l) { return doc.querySelector(l.getAttribute("href")); }).filter(Boolean);
    var nav = new IntersectionObserver(function (entries) {
      entries.forEach(function (en) {
        if (!en.isIntersecting) return;
        links.forEach(function (l) { l.classList.toggle("active", l.getAttribute("href") === "#" + en.target.id); });
      });
    }, { rootMargin: "-40% 0px -55% 0px" });
    sections.forEach(function (s) { nav.observe(s); });
  } else {
    reveals.forEach(function (el) { el.classList.add("in"); });
  }

  /* ---------------- Init ---------------- */
  setLang(detectLang(), false);
})();