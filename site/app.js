/* SonoForge landing page — progressive enhancement only.
   Everything on the page works without this file; the script adds:
   language toggle, release asset links (GitHub Releases API), OS-aware tabs, copy buttons,
   poster→video media facade with GIF fallback, feature GIFs, lightbox, reveal-on-scroll. */
(function () {
  "use strict";

  var REPO = "areatu/SonoForge";
  var API = "https://api.github.com/repos/" + REPO;
  var RELEASES_URL = "https://github.com/" + REPO + "/releases";
  var doc = document;
  var root = doc.documentElement;

  /* ---------------- Motion preferences ---------------- */
  var motionOK = !(window.matchMedia && matchMedia("(prefers-reduced-motion: reduce)").matches);
  var finePointer = window.matchMedia && matchMedia("(hover: hover) and (pointer: fine)").matches;
  var raf = window.requestAnimationFrame ? window.requestAnimationFrame.bind(window) : function (fn) { return setTimeout(fn, 16); };

  /* ---------------- Language ---------------- */
  var STRINGS = {
    en: {
      title: "SonoForge — Open-source desktop echocardiography analysis",
      description: "SonoForge is a free, open-source desktop application for echocardiography analysis: DICOM viewer, cardiac and Doppler measurements, AI segmentation, PACS connectivity and clinical PDF reports. Windows, Linux, macOS. Works offline.",
      pausePreviews: "Pause previews", resumePreviews: "Resume previews",
      help: "https://github.com/" + REPO + "/blob/main/docs/HELP_EN.md",
      presenter: "https://github.com/" + REPO + "/blob/main/build/presenter/README.md",
      copied: "Copied", copy: "Copy", gifFallback: "GIF preview", published: "released"
    },
    ru: {
      title: "SonoForge — открытая платформа для анализа эхокардиографии",
      description: "SonoForge — бесплатное открытое десктопное приложение для анализа эхокардиографии: просмотр DICOM, кардиологические и допплеровские измерения, AI-сегментация, подключение к PACS и клинические PDF-отчёты. Windows, Linux, macOS. Работает офлайн.",
      pausePreviews: "Остановить анимации", resumePreviews: "Включить анимации",
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
    var changed = currentLang !== lang && doc.body;
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
    updateFeatureMotionLabel();
    if (lastReleases) applyReleases(lastReleases);
    if (persist) {
      try { localStorage.setItem("sonoforge.lang", lang); } catch (e) { /* ignore */ }
    }
    if (changed && motionOK) { // soft cross-fade of the page copy when the language changes
      doc.body.classList.remove("lang-switching");
      void doc.body.offsetWidth;
      doc.body.classList.add("lang-switching");
      setTimeout(function () { doc.body.classList.remove("lang-switching"); }, 400);
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
  /* ---------------- Tabs ---------------- */
  doc.querySelectorAll("[data-tabs]").forEach(function (tabs) {
    var list = tabs.querySelectorAll('[role="tab"]');
    var panels = tabs.querySelectorAll('[role="tabpanel"]');
    var glider = tabs.querySelector(".tab-glider");

    function moveGlider(tab) {
      if (!glider || !tab) return;
      // The pill only makes sense while the tabs share one row; on narrow screens
      // they wrap and each tab simply highlights itself.
      var wrapped = list.length > 1 && list[0].offsetTop !== list[list.length - 1].offsetTop;
      if (wrapped) { glider.classList.remove("is-ready"); return; }
      var listRect = glider.parentElement.getBoundingClientRect();
      var r = tab.getBoundingClientRect();
      glider.style.width = r.width + "px";
      glider.style.transform = "translateX(" + (r.left - listRect.left) + "px)";
      glider.classList.add("is-ready");
    }
    function select(tab, animate) {
      list.forEach(function (t) { t.setAttribute("aria-selected", String(t === tab)); t.tabIndex = t === tab ? 0 : -1; });
      panels.forEach(function (p) { p.hidden = p.id !== tab.getAttribute("aria-controls"); });
      if (animate === false && glider) glider.style.transition = "none";
      moveGlider(tab);
      if (animate === false && glider) { void glider.offsetWidth; glider.style.transition = ""; }
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
    if (detected) detected.classList.add("detected");
    select(detected || list[0], false);
    var relayout = function () { moveGlider(tabs.querySelector('[role="tab"][aria-selected="true"]')); };
    window.addEventListener("resize", relayout, { passive: true });
    if (doc.fonts && doc.fonts.ready && doc.fonts.ready.then) doc.fonts.ready.then(relayout);
    setTimeout(relayout, 300);
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

  /* ---------------- Feature previews: GIFs only while visible ----------------
     Posters are the no-JS / reduced-motion default. Swapping back to a poster also
     stops decoding off-screen GIFs; the small animations are cached by the browser. */
  var featureMotionQuery = window.matchMedia && matchMedia("(prefers-reduced-motion: reduce)");
  var featureMotionBtn = doc.querySelector("[data-feature-motion]");
  var featurePaused = false;
  var featurePreviews = Array.prototype.map.call(doc.querySelectorAll("[data-feature-gif]"), function (img) {
    return { img: img, poster: img.getAttribute("src"), gif: img.getAttribute("data-feature-gif"), visible: false, failed: false };
  });

  function updateFeatureMotionLabel() {
    if (!featureMotionBtn) return;
    var label = featureMotionBtn.querySelector("[data-feature-motion-label]");
    var icon = featureMotionBtn.querySelector("use");
    if (label) label.textContent = STRINGS[currentLang][featurePaused ? "resumePreviews" : "pausePreviews"];
    if (icon) icon.setAttribute("href", featurePaused ? "#i-play" : "#i-pause");
  }

  function syncFeaturePreviews() {
    var allowed = !(featureMotionQuery && featureMotionQuery.matches);
    featurePreviews.forEach(function (preview) {
      var playing = allowed && !featurePaused && !doc.hidden && preview.visible && !preview.failed;
      var src = playing ? preview.gif : preview.poster;
      if (preview.img.getAttribute("src") !== src) preview.img.setAttribute("src", src);
    });
    if (featureMotionBtn) featureMotionBtn.hidden = !allowed || !featurePreviews.length;
    updateFeatureMotionLabel();
  }

  featurePreviews.forEach(function (preview) {
    preview.img.addEventListener("error", function () {
      if (preview.img.getAttribute("src") !== preview.gif) return;
      preview.failed = true;
      syncFeaturePreviews(); // a missing GIF must never replace the usable poster with a broken image
    });
  });
  if (featurePreviews.length && "IntersectionObserver" in window) {
    var featureIO = new IntersectionObserver(function (entries) {
      entries.forEach(function (entry) {
        featurePreviews.forEach(function (preview) {
          if (preview.img === entry.target) preview.visible = entry.isIntersecting;
        });
      });
      syncFeaturePreviews();
    }, { threshold: 0.15 });
    featurePreviews.forEach(function (preview) { featureIO.observe(preview.img); });
  } else {
    featurePreviews.forEach(function (preview) { preview.visible = true; });
  }
  if (featureMotionBtn) featureMotionBtn.addEventListener("click", function () {
    featurePaused = !featurePaused;
    syncFeaturePreviews();
  });
  if (featureMotionQuery) {
    if (featureMotionQuery.addEventListener) featureMotionQuery.addEventListener("change", syncFeaturePreviews);
    else if (featureMotionQuery.addListener) featureMotionQuery.addListener(syncFeaturePreviews);
  }
  doc.addEventListener("visibilitychange", syncFeaturePreviews);
  syncFeaturePreviews();

  /* ---------------- Lightbox ---------------- */
  var lb = doc.getElementById("lightbox");
  if (lb && typeof lb.showModal === "function") {
    var lbImg = lb.querySelector("img");
    var lbCap = lb.querySelector(".lightbox-cap");
    var shots = Array.prototype.slice.call(doc.querySelectorAll("[data-lightbox]"));
    var shotIndex = -1;

    function openShot(a, dir) {
      var thumb = a.querySelector("img");
      lbImg.style.opacity = "0";
      var next = new Image();
      var apply = function () {
        lbImg.src = a.href; lbImg.alt = thumb ? thumb.alt : "";
        var cap = a.querySelector('.shot-cap [lang="' + currentLang + '"]') || a.querySelector(".shot-cap");
        lbCap.textContent = cap ? cap.textContent : "";
        lbImg.style.opacity = "1";
        lbImg.style.transform = dir ? "translateX(" + (dir > 0 ? 18 : -18) + "px)" : "";
        raf(function () { lbImg.style.transform = ""; });
      };
      next.onload = apply;
      next.onerror = apply;
      next.src = a.href;
      setTimeout(apply, 120); // belt and braces: the image may already be in the browser cache
      shotIndex = shots.indexOf(a);
    }

    shots.forEach(function (a) {
      a.addEventListener("click", function (e) {
        if (e.metaKey || e.ctrlKey || e.shiftKey || e.button === 1) return; // let "open in new tab" work
        e.preventDefault();
        openShot(a, 0);
        if (!lb.open) lb.showModal();
      });
    });

    function step(dir) {
      if (shotIndex < 0 || !shots.length) return;
      var next = shots[(shotIndex + dir + shots.length) % shots.length];
      openShot(next, dir);
    }
    var prevBtn = lb.querySelector("[data-lb-prev]");
    var nextBtn = lb.querySelector("[data-lb-next]");
    if (prevBtn) prevBtn.addEventListener("click", function () { step(-1); });
    if (nextBtn) nextBtn.addEventListener("click", function () { step(1); });
    if (shots.length < 2) {
      if (prevBtn) prevBtn.hidden = true;
      if (nextBtn) nextBtn.hidden = true;
    }

    lb.querySelector(".lightbox-close").addEventListener("click", function () { lb.close(); });
    lb.addEventListener("click", function (e) {
      var nav = e.target.closest ? e.target.closest("[data-lb-prev],[data-lb-next]") : null;
      if (nav) return; // handled above
      if (e.target === lb) lb.close();
    });
    doc.addEventListener("keydown", function (e) {
      if (!lb.open) return;
      if (e.key === "ArrowRight") { e.preventDefault(); step(1); }
      else if (e.key === "ArrowLeft") { e.preventDefault(); step(-1); }
    });
    lb.addEventListener("close", function () { lbImg.removeAttribute("src"); });
  }

  /* ---------------- Reveal bookkeeping ----------------
     `pending` holds everything still waiting to animate in. IntersectionObserver does the
     regular work; the catch-up below covers the case where an element is jumped past
     faster than the observer can report it (scrollbar drag, anchor link, restored scroll). */
  var pending = [];
  function revealNow(el) { el.classList.add("in"); }
  function catchUpPending() {
    if (!pending.length) return;
    var vh = window.innerHeight || root.clientHeight;
    pending = pending.filter(function (el) {
      var r = el.getBoundingClientRect();
      if (r.top < vh * 0.98) { revealNow(el); return false; }
      return true;
    });
  }

  /* ---------------- Scroll state: progress bar, header, back-to-top ---------------- */
  var navEl = doc.querySelector("[data-nav]");
  var topBtn = doc.querySelector("[data-to-top]");
  var ticking = false;

  function onScrollFrame() {
    ticking = false;
    catchUpPending();
    var y = window.pageYOffset || root.scrollTop || 0;
    var max = Math.max(1, (root.scrollHeight || doc.body.scrollHeight) - window.innerHeight);
    var p = Math.min(1, Math.max(0, y / max));
    root.style.setProperty("--scroll", p.toFixed(4));
    if (navEl) navEl.classList.toggle("is-scrolled", y > 8);
    if (topBtn) topBtn.classList.toggle("is-visible", y > window.innerHeight * 0.8);
  }
  function onScroll() { if (!ticking) { ticking = true; raf(onScrollFrame); } }
  window.addEventListener("scroll", onScroll, { passive: true });
  window.addEventListener("resize", onScroll, { passive: true });
  onScrollFrame();

  /* ---------------- Section rail (desktop) ---------------- */
  var rail = null;
  if (finePointer && motionOK) {
    var railLinks = Array.prototype.slice.call(doc.querySelectorAll(".nav-links a[href^='#']"))
      .filter(function (l) { return doc.querySelector(l.getAttribute("href")); });
    if (railLinks.length > 2) {
      rail = doc.createElement("nav");
      rail.className = "rail";
      rail.setAttribute("aria-label", "Section navigation");
      railLinks.forEach(function (l) {
        var a = doc.createElement("a");
        a.href = l.getAttribute("href");
        var span = doc.createElement("span");
        span.innerHTML = l.innerHTML; // keeps both language variants, so it follows the language toggle
        a.appendChild(span);
        rail.appendChild(a);
      });
      doc.body.appendChild(rail);
      var railItems = Array.prototype.slice.call(rail.querySelectorAll("a"));
      if ("IntersectionObserver" in window) {
        var railIO = new IntersectionObserver(function (entries) {
          entries.forEach(function (en) {
            if (!en.isIntersecting) return;
            railItems.forEach(function (a) { a.classList.toggle("is-active", a.getAttribute("href") === "#" + en.target.id); });
          });
        }, { rootMargin: "-45% 0px -50% 0px" });
        railItems.forEach(function (a) {
          var s = doc.querySelector(a.getAttribute("href"));
          if (s) railIO.observe(s);
        });
      }
    }
  }

  /* ---------------- Counters in the hero facts ---------------- */
  doc.querySelectorAll("[data-count]").forEach(function (el) {
    var target = parseFloat(el.getAttribute("data-count"));
    if (!motionOK || !isFinite(target)) return;
    el.textContent = "0";
    var started = false;
    function run() {
      if (started) return;
      started = true;
      var t0 = performance.now(), dur = 1300;
      (function step(now) {
        var k = Math.min(1, (now - t0) / dur);
        var eased = 1 - Math.pow(1 - k, 3); // ease-out cubic
        el.textContent = Math.round(target * eased).toLocaleString(currentLang === "ru" ? "ru-RU" : "en-US");
        if (k < 1) raf(step);
      })(t0);
    }
    if ("IntersectionObserver" in window) {
      var cio = new IntersectionObserver(function (entries) {
        entries.forEach(function (en) { if (en.isIntersecting) { run(); cio.disconnect(); } });
      }, { threshold: 0.4 });
      cio.observe(el);
    } else { run(); }
  });

  /* ---------------- Hero: cursor parallax + media tilt ---------------- */
  var heroScope = doc.querySelector("[data-tilt-scope]");
  if (heroScope && finePointer && motionOK) {
    heroScope.querySelectorAll("[data-parallax]").forEach(function (el) {
      el.style.setProperty("--d", String(parseFloat(el.getAttribute("data-parallax")) * 90));
    });
    var tiltCard = heroScope.querySelector("[data-tilt]");
    var target = { px: 0, py: 0, tx: 0, ty: 0 };
    var current = { px: 0, py: 0, tx: 0, ty: 0 };
    var running = false;
    function spring() {
      var settled = true;
      ["px", "py", "tx", "ty"].forEach(function (k) {
        current[k] += (target[k] - current[k]) * 0.12;
        if (Math.abs(target[k] - current[k]) > 0.001) settled = false;
      });
      heroScope.style.setProperty("--px", current.px.toFixed(3));
      heroScope.style.setProperty("--py", current.py.toFixed(3));
      if (tiltCard) {
        tiltCard.style.setProperty("--tx", current.tx.toFixed(3));
        tiltCard.style.setProperty("--ty", current.ty.toFixed(3));
      }
      if (settled) { running = false; return; }
      raf(spring);
    }
    function kick() { if (!running) { running = true; raf(spring); } }
    heroScope.addEventListener("pointermove", function (e) {
      var r = heroScope.getBoundingClientRect();
      var nx = ((e.clientX - r.left) / r.width) * 2 - 1;
      var ny = ((e.clientY - r.top) / r.height) * 2 - 1;
      target.px = Math.max(-1, Math.min(1, nx)) * -18;
      target.py = Math.max(-1, Math.min(1, ny)) * -14;
      if (tiltCard) {
        var tr = tiltCard.getBoundingClientRect();
        var overMedia = e.clientX >= tr.left && e.clientX <= tr.right && e.clientY >= tr.top && e.clientY <= tr.bottom;
        var mx = ((e.clientX - tr.left) / tr.width) * 2 - 1;
        var my = ((e.clientY - tr.top) / tr.height) * 2 - 1;
        target.tx = overMedia ? Math.max(-1, Math.min(1, mx)) : 0;
        target.ty = overMedia ? Math.max(-1, Math.min(1, my)) : 0;
        tiltCard.classList.toggle("is-tilting", overMedia);
      }
      kick();
    }, { passive: true });
    heroScope.addEventListener("pointerleave", function () {
      target.px = target.py = target.tx = target.ty = 0;
      if (tiltCard) tiltCard.classList.remove("is-tilting");
      kick();
    }, { passive: true });
  }

  /* ---------------- Cards: cursor spotlight ---------------- */
  if (finePointer) {
    var spotCard = null;
    doc.addEventListener("pointermove", function (e) {
      var card = e.target && e.target.closest ? e.target.closest(".card") : null;
      if (card !== spotCard) spotCard = card;
      if (!card) return;
      var r = card.getBoundingClientRect();
      card.style.setProperty("--mx", (e.clientX - r.left).toFixed(1) + "px");
      card.style.setProperty("--my", (e.clientY - r.top).toFixed(1) + "px");
    }, { passive: true });
  }

  /* ---------------- Gallery: gentle 3D tilt on the thumbnails ---------------- */
  if (finePointer && motionOK) {
    doc.querySelectorAll("[data-shot]").forEach(function (shot) {
      shot.addEventListener("pointermove", function (e) {
        var r = shot.getBoundingClientRect();
        var mx = ((e.clientX - r.left) / r.width - 0.5) * 2;
        var my = ((e.clientY - r.top) / r.height - 0.5) * 2;
        shot.style.transform = "perspective(900px) rotateX(" + (-my * 2.2).toFixed(2) + "deg) rotateY(" + (mx * 2.6).toFixed(2) + "deg) translateY(-4px)";
      }, { passive: true });
      shot.addEventListener("pointerleave", function () { shot.style.removeProperty("transform"); });
      shot.addEventListener("blur", function () { shot.style.removeProperty("transform"); });
    });
  }

  /* ---------------- Reveal on scroll (staggered) + active nav ---------------- */
  var reveals = doc.querySelectorAll(".reveal");
  reveals.forEach(function (el) {
    var parent = el.parentElement;
    if (!parent) return;
    var siblings = Array.prototype.filter.call(parent.children, function (c) { return c.classList.contains("reveal"); });
    var i = siblings.indexOf(el);
    if (i > 0 && siblings.length > 1) el.style.setProperty("--reveal-delay", Math.min(i, 6) * 70 + "ms");
  });
  reveals.forEach(function (el) {
    el.addEventListener("animationend", function () { el.style.removeProperty("--reveal-delay"); });
  });

  var stepBlocks = doc.querySelectorAll("[data-steps]");
  pending = Array.prototype.slice.call(reveals).concat(Array.prototype.slice.call(stepBlocks));
  if ("IntersectionObserver" in window && motionOK) {
    var io = new IntersectionObserver(function (entries) {
      entries.forEach(function (en) {
        if (!en.isIntersecting) return;
        revealNow(en.target);
        io.unobserve(en.target);
        var k = pending.indexOf(en.target);
        if (k >= 0) pending.splice(k, 1);
      });
    }, { rootMargin: "0px 0px -8% 0px", threshold: 0.08 });
    pending.forEach(function (el) { io.observe(el); });
    catchUpPending(); // anything already above the fold on load (deep links) shows at once

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
    pending.forEach(revealNow);
    pending = [];
  }

  /* ---------------- Init ---------------- */
  setLang(detectLang(), false);
})();