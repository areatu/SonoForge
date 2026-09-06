"use strict";

var state = {
    topics: [],
    selectedTopic: null,
    selectedPathology: null,
    currentImages: [],
    currentImageIndex: 0,
    currentParams: [],
    ui: {},
    renderSeq: 0,
};

var $ = function (s) { return document.querySelector(s); };
var $$ = function (s) { return document.querySelectorAll(s); };

/* UI strings from the Python bridge (localized); fall back to English defaults. */
function t(key, def) {
    return (state.ui && state.ui[key]) ? state.ui[key] : (def || key);
}

function escapeHtml(s) {
    if (!s) return "";
    var d = document.createElement("div");
    d.textContent = s;
    return d.innerHTML;
}

function escapeAttr(s) {
    return String(s == null ? "" : s)
        .replace(/&/g, "&amp;")
        .replace(/"/g, "&quot;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;");
}

/* ===== Static UI text ===== */
function applyUi() {
    var el;
    el = $("#searchInput"); if (el) el.placeholder = t("search_placeholder", "Search...");
    el = $("#editToggle"); if (el) { el.textContent = "\u270F\uFE0F " + t("edit", "Edit"); el.title = t("edit_title", "Edit mode"); }
    el = $("#saveBtn"); if (el) el.textContent = "\uD83D\uDCBE " + t("save", "Save");
    el = $("#cancelBtn"); if (el) el.textContent = "\u2715 " + t("cancel", "Cancel");
    el = $("#topicsHeader"); if (el) el.textContent = t("anatomy", "Anatomy");
    el = $("#pathoHint"); if (el) el.textContent = t("select_topic", "Select a topic on the left");
    el = $("#imageEmptyText"); if (el) el.textContent = t("no_images", "No images");
    el = $("#modalPrev"); if (el) el.title = t("previous", "Previous");
    el = $("#modalNext"); if (el) el.title = t("next", "Next");
    el = $("#modalClose"); if (el) el.title = t("close", "Close (Esc)");
}

/* ===== Topics ===== */
function renderTopics(topics) {
    state.topics = topics;
    var c = $("#topicsList");
    var fragment = document.createDocumentFragment();
    topics.forEach(function (topic) {
        var btn = document.createElement("button");
        btn.className = "topic-btn" + (state.selectedTopic === topic.slug ? " active" : "");
        var label = topic.label || "";
        btn.innerHTML =
            (label ? '<span class="topic-icon">' + escapeHtml(label) + '</span>' : '') +
            '<span>' + escapeHtml(topic.name) + '</span>' +
            '<span class="topic-badge">' + topic.n_params + '</span>';
        btn.addEventListener("click", function () { selectTopic(topic.slug); });
        fragment.appendChild(btn);
    });
    c.innerHTML = "";
    c.appendChild(fragment);
    // Stats
    var totalParams = topics.reduce(function (s, x) { return s + x.n_params; }, 0);
    var totalImages = topics.reduce(function (s, x) { return s + x.n_images; }, 0);
    $("#statsText").textContent = t(
        "stats",
        "{topics} topics · {params} parameters · {images} images"
    ).replace("{topics}", topics.length).replace("{params}", totalParams).replace("{images}", totalImages);
}

function loadPathologyContent(topicSlug, pathoSlug) {
    var token = ++state.renderSeq;
    var split = $(".content-split");
    split.classList.add("fading-out");
    return bridge.getPathology(topicSlug, pathoSlug).then(function (data) {
        return new Promise(function (resolve) {
            requestAnimationFrame(function () {
                requestAnimationFrame(function () {
                    if (token !== state.renderSeq) {
                        // A newer transition owns the cross-fade; do nothing.
                        resolve();
                        return;
                    }
                    if (!data || data.error) {
                        split.classList.remove("fading-out");
                        resolve();
                        return;
                    }
                    renderDescription(data.description);
                    state.currentParams = data.parameters || [];
                    renderParams(data, true);
                    renderImages(data.images || []);
                    split.classList.remove("fading-out");
                    resolve();
                });
            });
        });
    });
}

async function selectTopic(slug, preferredPathology) {
    state.selectedTopic = slug;
    state.selectedPathology = null;
    var topicToken = ++state.renderSeq;   // invalidate in-flight topic/content requests
    renderTopics(state.topics);
    var data = await bridge.getTopicDetail(slug);
    if (topicToken !== state.renderSeq) return;
    if (!data || data.error) return;
    var pathos = data.pathologies || [];
    if (pathos.length > 0) {
        var target = pathos[0].slug;
        if (preferredPathology && pathos.some(function (p) { return p.slug === preferredPathology; })) {
            target = preferredPathology;
        }
        state.selectedPathology = target;
        renderPathologies(pathos, data.name);
        await loadPathologyContent(slug, target);
    } else {
        renderPathologies(pathos, data.name);
        clearContent();
    }
}

/* ===== Pathologies ===== */
/* ===== Pathology Tab Indicator ===== */
function moveTabIndicator() {
    var bar = $("#pathologyBar");
    var activeBtn = bar.querySelector(".patho-btn.active");
    if (activeBtn) {
        var rect = activeBtn.getBoundingClientRect();
        var barRect = bar.getBoundingClientRect();
        bar.style.setProperty("--indicator-left", (rect.left - barRect.left + bar.scrollLeft) + "px");
        bar.style.setProperty("--indicator-width", rect.width + "px");
        // Track the active tab's row so the underline stays correct on wrap.
        bar.style.setProperty("--indicator-top", (rect.bottom - barRect.top - 2) + "px");
    } else {
        bar.style.setProperty("--indicator-left", "0px");
        bar.style.setProperty("--indicator-width", "0px");
        bar.style.setProperty("--indicator-top", "0px");
    }
}

function renderPathologies(pathologies, topicName) {
    var bar = $("#pathologyBar");
    if (!pathologies || !pathologies.length) {
        bar.innerHTML = '<span class="empty-hint">' + escapeHtml(t("no_pathologies", "No pathologies")) + '</span>';
        moveTabIndicator();
        return;
    }
    var fragment = document.createDocumentFragment();
    pathologies.forEach(function (patho) {
        var btn = document.createElement("button");
        btn.className = "patho-btn" + (state.selectedPathology === patho.slug ? " active" : "");
        btn.setAttribute("data-slug", patho.slug);
        var label = escapeHtml(patho.name);
        if (patho.image_count > 0) {
            label += ' <span class="patho-badge">\uD83D\uDDBC' + patho.image_count + '</span>';
        }
        btn.innerHTML = label;
        btn.title = patho.description || patho.name;
        btn.addEventListener("click", function () { selectPathology(patho.slug); });
        fragment.appendChild(btn);
    });
    bar.innerHTML = "";
    bar.appendChild(fragment);
    requestAnimationFrame(moveTabIndicator);
}

async function selectPathology(slug) {
    state.selectedPathology = slug;
    state.renderSeq++;   // invalidate any in-flight content transition
    $$(".patho-btn").forEach(function (btn) {
        btn.classList.toggle("active", btn.getAttribute("data-slug") === slug);
    });
    moveTabIndicator();
    await loadPathologyContent(state.selectedTopic, slug);
}

/* ===== Description ===== */
function renderDescription(desc) {
    var panel = $("#descPanel");
    var text = $("#descText");
    if (!desc) {
        panel.hidden = true;
        return;
    }
    text.textContent = desc;
    panel.hidden = false;
}

/* ===== Parameters ===== */
function renderParams(data, animateStagger) {
    var area = $("#paramsArea");
    var head = $("#paramHead");
    var body = $("#paramBody");
    var source = $("#sourceBar");

    area.hidden = false;

    var params = data.parameters || [];
    var gradNames = data.grad_names || [];
    var hasGradsAny = gradNames.length > 0;
    // Norm columns show when at least one parameter has no gradations
    // (covers both pure-flat and mixed pathologies).
    var hasFlatAny = params.some(function (p) { return !p.has_gradations; });
    var showNorm = !hasGradsAny || hasFlatAny;

    var headers = [t("col_param", "Parameter")];
    if (showNorm) {
        headers.push(t("col_norm_male", "Norm M"));
        headers.push(t("col_norm_female", "Norm F"));
    }
    if (hasGradsAny) headers = headers.concat(gradNames);

    // Reuse existing header structure when unchanged (avoids a jump).
    var existingHeaders = [];
    head.querySelectorAll("th").forEach(function (th) { existingHeaders.push(th.textContent); });
    if (JSON.stringify(existingHeaders) !== JSON.stringify(headers)) {
        head.innerHTML = "";
        var hr = document.createElement("tr");
        headers.forEach(function (h) {
            var th = document.createElement("th");
            th.textContent = h;
            hr.appendChild(th);
        });
        head.appendChild(hr);
    }

    var colCount = headers.length;
    var fragment = document.createDocumentFragment();

    if (!params.length) {
        var emptyTr = document.createElement("tr");
        var emptyTd = document.createElement("td");
        emptyTd.colSpan = colCount;
        emptyTd.textContent = t("no_parameters", "No parameters for this pathology");
        emptyTd.className = "patho-desc";
        emptyTd.style.textAlign = "center";
        emptyTr.appendChild(emptyTd);
        fragment.appendChild(emptyTr);
    } else {
        var rowIndex = 0;
        params.forEach(function (param) {
            var rowHasGrads = !!(param.has_gradations && param.gradations && param.gradations.length);
            var tr = document.createElement("tr");
            tr.style.setProperty("--row-index", rowIndex++);
            tr.setAttribute("data-param", param.id);

            // Name cell with unit
            var tdName = document.createElement("td");
            tdName.className = "param-name";
            var nameHtml = '<span class="param-title" data-field="name" data-param="' + escapeAttr(param.id) + '">' + escapeHtml(param.name) + '</span>';
            if (param.unit) {
                nameHtml += ' <span class="param-unit" data-field="unit" data-param="' + escapeAttr(param.id) + '">(' + escapeHtml(param.unit) + ')</span>';
            }
            tdName.innerHTML = nameHtml;
            tdName.setAttribute("data-full", param.full_name || param.name);
            if (param.unit) tdName.setAttribute("data-unit", param.unit);
            tr.appendChild(tdName);

            // Norm male / female columns (only where the row has no gradations;
            // placeholder cells for gradation rows keep the grid aligned).
            if (showNorm) {
                if (!rowHasGrads) {
                    var tdM = document.createElement("td");
                    tdM.className = "norm-value";
                    tdM.textContent = param.norm_male || "\u2014";
                    tdM.setAttribute("data-field", "norm_male");
                    tdM.setAttribute("data-param", param.id);
                    tr.appendChild(tdM);

                    var tdF = document.createElement("td");
                    tdF.className = "norm-value";
                    tdF.textContent = param.norm_female || "\u2014";
                    tdF.setAttribute("data-field", "norm_female");
                    tdF.setAttribute("data-param", param.id);
                    tr.appendChild(tdF);
                } else {
                    for (var n = 0; n < 2; n++) {
                        var tdEmptyNorm = document.createElement("td");
                        tdEmptyNorm.className = "norm-value norm-empty";
                        tdEmptyNorm.textContent = "\u2014";
                        tr.appendChild(tdEmptyNorm);
                    }
                }
            }

            // Gradation cells
            if (hasGradsAny) {
                var gvals = param.gradations || [];
                gradNames.forEach(function (gn, gi) {
                    var gv = gvals[gi] || "\u2014";
                    var td = document.createElement("td");
                    if (rowHasGrads) {
                        td.className = "grad-cell";
                        td.setAttribute("data-field", "gradation");
                        td.setAttribute("data-param", param.id);
                        td.setAttribute("data-grad", gn);
                        if (gv && gv !== "\u2014") {
                            var cls = gradClassForName(gn);
                            if (cls) td.classList.add(cls);
                        }
                    } else {
                        td.className = "grad-cell grad-empty";
                    }
                    td.textContent = gv;
                    tr.appendChild(td);
                });
            }

            // Row click → select row + show its source
            tr.addEventListener("click", function () {
                $$(".param-table tr.selected").forEach(function (r) { r.classList.remove("selected"); });
                tr.classList.add("selected");
                showSource(param.source);
            });

            fragment.appendChild(tr);

            // Pathology description sub-row
            if (param.pathology_desc) {
                var descTr = document.createElement("tr");
                descTr.className = "desc-row";
                var descTd = document.createElement("td");
                descTd.className = "patho-desc";
                descTd.colSpan = colCount;
                descTd.textContent = param.pathology_desc;
                descTr.appendChild(descTd);
                fragment.appendChild(descTr);
            }
        });
    }

    // Single DOM replacement to avoid micro-jumps
    body.innerHTML = "";
    body.classList.toggle("stagger", !!animateStagger);
    body.appendChild(fragment);

    // Source from first param with source
    var firstWithSource = params.find(function (p) { return p.source; });
    if (firstWithSource) {
        showSource(firstWithSource.source);
    } else {
        source.hidden = true;
    }
}

function showSource(source) {
    var bar = $("#sourceBar");
    if (source) {
        bar.textContent = "\uD83D\uDCD6 " + source;
        bar.hidden = false;
    } else {
        bar.hidden = true;
    }
}

function clearContent() {
    $("#paramsArea").hidden = true;
    $("#descPanel").hidden = true;
    $("#sourceBar").hidden = true;
    $(".content-split").classList.remove("fading-out");
    clearImages();
}

function gradClassForName(name) {
    if (!name) return "";
    var lower = name.toLowerCase();
    if (lower.indexOf("\u043d\u043e\u0440\u043c") >= 0 || lower.indexOf("normal") >= 0) return "grad-normal-cell";
    if (lower.indexOf("\u043b\u0451\u0433\u043a") >= 0 || lower.indexOf("\u043b\u0435\u0433\u043a") >= 0 || lower.indexOf("mild") >= 0) return "grad-mild-cell";
    if (lower.indexOf("\u0443\u043c\u0435\u0440\u0435\u043d") >= 0 || lower.indexOf("moderate") >= 0) return "grad-moderate-cell";
    if (lower.indexOf("\u0442\u044f\u0436\u0451\u043b") >= 0 || lower.indexOf("\u0442\u044f\u0436\u0435\u043b") >= 0 || lower.indexOf("severe") >= 0) return "grad-severe-cell";
    return "";
}

/* ===== Images ===== */
function renderImages(images) {
    var empty = $("#imageEmpty");
    var mainArea = $("#imageMain");
    var thumbs = $("#imageThumbs");
    var nav = $("#imageNav");

    state.currentImages = images.filter(function (i) { return i.exists; });
    state.currentImageIndex = 0;

    if (!state.currentImages.length) {
        empty.hidden = false;
        mainArea.hidden = true;
        thumbs.hidden = true;
        nav.hidden = true;
        return;
    }
    empty.hidden = true;
    mainArea.hidden = false;
    nav.hidden = false;

    // Render thumbnails
    var thumbFragment = document.createDocumentFragment();
    thumbs.hidden = state.currentImages.length <= 1;
    state.currentImages.forEach(function (img, idx) {
        var thumb = document.createElement("div");
        thumb.className = "image-thumb" + (idx === 0 ? " active" : "");
        var imgEl = document.createElement("img");
        imgEl.src = img.url;
        imgEl.alt = img.name;
        imgEl.loading = "lazy";
        thumb.appendChild(imgEl);
        thumb.addEventListener("click", function () {
            state.currentImageIndex = idx;
            showCurrentImage();
        });
        thumbFragment.appendChild(thumb);
    });
    thumbs.innerHTML = "";
    thumbs.appendChild(thumbFragment);

    showCurrentImage();
}

function showCurrentImage() {
    var img = $("#mainImage");
    var counter = $("#imageCounter");
    var prev = $("#btnImgPrev");
    var next = $("#btnImgNext");
    var thumbs = $$(".image-thumb");
    var images = state.currentImages;
    var idx = state.currentImageIndex;

    if (!images.length) return;
    img.src = images[idx].url;
    img.alt = images[idx].name;
    counter.textContent = (idx + 1) + " / " + images.length;
    prev.disabled = idx === 0;
    next.disabled = idx === images.length - 1;

    // Update thumbnail active state
    thumbs.forEach(function (th, i) {
        th.classList.toggle("active", i === idx);
    });
}

function clearImages() {
    $("#imageEmpty").hidden = false;
    $("#imageMain").hidden = true;
    $("#imageThumbs").hidden = true;
    $("#imageNav").hidden = true;
    state.currentImages = [];
    state.currentImageIndex = 0;
}

/* ===== Image Lightbox ===== */
function openModal(index) {
    if (!state.currentImages.length) return;
    state.currentImageIndex = index;
    renderModalImage();
    showCurrentImage();
    $("#imageModal").hidden = false;
}

function closeModal() {
    $("#imageModal").hidden = true;
}

function renderModalImage() {
    var images = state.currentImages;
    var idx = state.currentImageIndex;
    if (!images.length) return;
    $("#modalImage").src = images[idx].url;
    $("#modalImage").alt = images[idx].name;
    $("#modalCounter").textContent = (idx + 1) + " / " + images.length;
    $("#modalPrev").disabled = idx === 0;
    $("#modalNext").disabled = idx === images.length - 1;
}

$("#modalPrev").addEventListener("click", function () {
    if (state.currentImageIndex > 0) {
        state.currentImageIndex--;
        renderModalImage();
        showCurrentImage();
    }
});
$("#modalNext").addEventListener("click", function () {
    if (state.currentImageIndex < state.currentImages.length - 1) {
        state.currentImageIndex++;
        renderModalImage();
        showCurrentImage();
    }
});
$("#modalClose").addEventListener("click", closeModal);
$("#imageModal").addEventListener("click", function (e) {
    if (e.target === this || e.target === $("#modalImage")) closeModal();
});
$("#mainImage").addEventListener("click", function () {
    openModal(state.currentImageIndex);
});

$("#btnImgPrev").addEventListener("click", function () {
    if (state.currentImageIndex > 0) {
        state.currentImageIndex--;
        showCurrentImage();
    }
});
$("#btnImgNext").addEventListener("click", function () {
    if (state.currentImageIndex < state.currentImages.length - 1) {
        state.currentImageIndex++;
        showCurrentImage();
    }
});

/* ===== Tooltip ===== */
var tooltipTimer = null;
var tooltipCell = null;

function positionTooltip(x, y) {
    var tip = $("#tooltip");
    var pad = 12;
    var left = x + pad;
    var top = y + pad;
    if (left + tip.offsetWidth > innerWidth - pad) left = x - tip.offsetWidth - pad;
    if (top + tip.offsetHeight > innerHeight - pad) top = y - tip.offsetHeight - pad;
    tip.style.left = Math.max(pad, left) + "px";
    tip.style.top = Math.max(pad, top) + "px";
}

function hideTooltip() {
    clearTimeout(tooltipTimer);
    tooltipTimer = null;
    tooltipCell = null;
    $("#tooltip").hidden = true;
}

document.addEventListener("mouseover", function (e) {
    var cell = e.target.closest ? e.target.closest(".param-name") : null;
    if (!cell || cell === tooltipCell) return;
    tooltipCell = cell;
    var full = cell.getAttribute("data-full") || cell.textContent;
    var unit = cell.getAttribute("data-unit");
    if (unit) full += " (" + unit + ")";
    clearTimeout(tooltipTimer);
    tooltipTimer = setTimeout(function () {
        var tip = $("#tooltip");
        tip.textContent = full;
        tip.hidden = false;
        positionTooltip(e.clientX, e.clientY);
    }, 1500);
});

document.addEventListener("mouseout", function (e) {
    if (e.target.closest && e.target.closest(".param-name")) {
        hideTooltip();
    }
});

document.addEventListener("mousemove", function (e) {
    var tip = $("#tooltip");
    if (!tip.hidden && e.target.closest && e.target.closest(".param-name")) {
        positionTooltip(e.clientX, e.clientY);
    }
});

/* ===== Edit Mode ===== */
var editMode = false;

function enterEditMode() {
    editMode = true;
    $("#editToggle").classList.add("active");
    $("#editActions").hidden = false;
    $("#editStatus").textContent = "";
    var editable = document.querySelectorAll(
        '#paramBody .param-title, #paramBody .param-unit, ' +
        '#paramBody td.norm-value[data-field], #paramBody td.grad-cell[data-field]'
    );
    editable.forEach(function (el) {
        el.setAttribute("contenteditable", "true");
    });
}

function exitEditMode() {
    editMode = false;
    $("#editToggle").classList.remove("active");
    $("#editActions").hidden = true;
    document.querySelectorAll('#paramBody [contenteditable="true"]').forEach(function (el) {
        el.removeAttribute("contenteditable");
        el.classList.remove("dirty");
    });
}

function refreshPathology() {
    if (!state.selectedTopic || !state.selectedPathology) return Promise.resolve();
    return bridge.getPathology(state.selectedTopic, state.selectedPathology).then(function (data) {
        if (!data || data.error) return;
        renderDescription(data.description);
        state.currentParams = data.parameters || [];
        renderParams(data, false);
        renderImages(data.images || []);
    });
}

/* Parse a gradation cell like "♂ 60–63 / ♀ 52–56" into {male, female}. */
function parseGradationText(text) {
    var male = null;
    var female = null;
    String(text || "").split("/").forEach(function (p) {
        p = p.trim();
        if (!p) return;
        var isMale = p.indexOf("\u2642") >= 0;
        var isFemale = p.indexOf("\u2640") >= 0;
        var val = p.replace(/[\u2642\u2640]/g, "").trim();
        if (!val || val === "\u2014") val = "";
        if (isMale) male = val;
        else if (isFemale) female = val;
        else if (male === null) male = val;   // legacy: first unmarked part
        else female = val;                    // legacy: second unmarked part
    });
    return { male: male, female: female };
}

async function saveDirtyCells() {
    var dirty = Array.from(document.querySelectorAll('#paramBody [contenteditable="true"].dirty'));
    if (!dirty.length) {
        exitEditMode();
        return;
    }
    var results = [];
    for (var i = 0; i < dirty.length; i++) {
        var el = dirty[i];
        var paramId = el.getAttribute("data-param");
        var field = el.getAttribute("data-field");
        var text = el.textContent.trim();
        if (field === "name") {
            results.push(await bridge.updateParam(state.selectedTopic, state.selectedPathology, paramId, "name", text));
        } else if (field === "unit") {
            var unit = text.replace(/^\(/, "").replace(/\)$/, "").trim();
            results.push(await bridge.updateParam(state.selectedTopic, state.selectedPathology, paramId, "unit", unit));
        } else if (field === "norm_male" || field === "norm_female") {
            results.push(await bridge.updateParam(state.selectedTopic, state.selectedPathology, paramId, field, text || "\u2014"));
        } else if (field === "gradation") {
            var parsed = parseGradationText(text);
            results.push(await bridge.updateGradation(
                state.selectedTopic, state.selectedPathology, paramId,
                el.getAttribute("data-grad") || "",
                parsed.male === null ? "\u2014" : parsed.male,
                parsed.female === null ? "\u2014" : parsed.female
            ));
        }
    }
    var errors = results.filter(function (r) { return r && r.error; });
    if (errors.length) {
        $("#editStatus").textContent = errors[0].error;
        return;
    }
    exitEditMode();
    await refreshPathology();
}

/* ===== Age Filter ===== */
function setupAgeFilter() {
    var inp = $("#ageInput");
    if (!inp) return;
    inp.addEventListener("input", function () {
        // Reserved for age-specific reference ranges when the data supports it.
    });
}

$("#editToggle").addEventListener("click", function () {
    if (editMode) { exitEditMode(); } else { enterEditMode(); }
});
$("#saveBtn").addEventListener("click", saveDirtyCells);
$("#cancelBtn").addEventListener("click", function () {
    exitEditMode();
    refreshPathology();
});
$("#paramBody").addEventListener("input", function (e) {
    if (!editMode) return;
    var el = e.target.closest ? e.target.closest("[contenteditable]") : null;
    if (el) el.classList.add("dirty");
});

/* ===== Search ===== */
var searchTimeout = null;
function highlightParam(paramId) {
    requestAnimationFrame(function () {
        var tr = document.querySelector('.param-table tbody tr[data-param="' + paramId + '"]');
        if (!tr) return;
        tr.scrollIntoView({ block: "center", behavior: "smooth" });
        $$(".param-table tr.selected").forEach(function (r) { r.classList.remove("selected"); });
        tr.classList.add("selected", "highlight");
        setTimeout(function () { tr.classList.remove("highlight"); }, 1600);
    });
}

function setupSearch() {
    var inp = $("#searchInput");
    var res = $("#searchResults");
    inp.addEventListener("input", function () {
        clearTimeout(searchTimeout);
        var q = inp.value.trim();
        if (!q) { res.hidden = true; return; }
        searchTimeout = setTimeout(async function () {
            var hits = await bridge.search(q);
            if (!hits || hits.error) return;
            if (!hits.length) {
                res.innerHTML = '<div class="search-result-item"><span class="search-result-name">' +
                    escapeHtml(t("nothing_found", "Nothing found")) + '</span></div>';
                res.hidden = false;
                return;
            }
            var labels = {
                topic: "\uD83D\uDCCB " + t("type_topic", "Topic"),
                pathology: "\uD83D\uDCC4 " + t("type_pathology", "Pathology"),
                parameter: "\uD83D\uDCCA " + t("type_parameter", "Parameter")
            };
            var fragment = document.createDocumentFragment();
            hits.forEach(function (h) {
                var el = document.createElement("div");
                el.className = "search-result-item";
                var html = '<div class="search-result-type">' + (labels[h.type] || h.type) + '</div>';
                html += '<div class="search-result-name">' + escapeHtml(h.name) + '</div>';
                if (h.parent) {
                    html += '<div class="search-result-parent">' + escapeHtml(h.parent) + '</div>';
                }
                el.innerHTML = html;
                el.addEventListener("click", function () {
                    res.hidden = true;
                    inp.value = "";
                    if (h.type === "topic") {
                        selectTopic(h.topic_slug);
                    } else if (h.type === "pathology") {
                        selectTopic(h.topic_slug, h.patho_slug);
                    } else if (h.type === "parameter") {
                        selectTopic(h.topic_slug, h.patho_slug).then(function () {
                            highlightParam(h.param_id);
                        });
                    }
                });
                fragment.appendChild(el);
            });
            res.innerHTML = "";
            res.appendChild(fragment);
            res.hidden = false;
        }, 200);
    });
    inp.addEventListener("blur", function () { setTimeout(function () { res.hidden = true; }, 200); });
}

/* ===== Keyboard Shortcuts ===== */
function isTypingTarget(e) {
    var el = e.target;
    if (!el) return false;
    var tag = (el.tagName || "").toLowerCase();
    if (tag === "input" || tag === "textarea" || tag === "select") return true;
    return !!el.isContentEditable;
}

function setupKeyboard() {
    document.addEventListener("keydown", function (e) {
        // Modal navigation (takes priority)
        if (!$("#imageModal").hidden) {
            if (e.key === "Escape") { closeModal(); return; }
            if (e.key === "ArrowLeft") { e.preventDefault(); $("#modalPrev").click(); return; }
            if (e.key === "ArrowRight") { e.preventDefault(); $("#modalNext").click(); return; }
        }
        // Focus search on Ctrl+F
        if (e.ctrlKey && e.key === "f") {
            e.preventDefault();
            $("#searchInput").focus();
            return;
        }
        // Don't hijack arrows/escape while typing or editing a cell
        if (isTypingTarget(e)) return;
        if (e.key === "Escape") {
            $("#searchInput").value = "";
            $("#searchResults").hidden = true;
            $("#searchInput").blur();
        }
        // Arrow keys for image navigation
        if (e.key === "ArrowLeft" && state.currentImages.length > 0) {
            if (state.currentImageIndex > 0) {
                state.currentImageIndex--;
                showCurrentImage();
            }
        }
        if (e.key === "ArrowRight" && state.currentImages.length > 0) {
            if (state.currentImageIndex < state.currentImages.length - 1) {
                state.currentImageIndex++;
                showCurrentImage();
            }
        }
    });
}

/* ===== Resizable left panel ===== */
function setupResize() {
    var handle = $(".resize-handle");
    var left = $("#panelTopics");
    var container = $(".main-container");
    handle.addEventListener("mousedown", function (e) {
        e.preventDefault();
        document.body.classList.add("resizing");
        function onMove(ev) {
            var rect = container.getBoundingClientRect();
            var w = ev.clientX - rect.left;
            w = Math.max(130, Math.min(420, w));
            left.style.width = w + "px";
        }
        function onUp() {
            document.removeEventListener("mousemove", onMove);
            document.removeEventListener("mouseup", onUp);
            document.body.classList.remove("resizing");
            moveTabIndicator();
        }
        document.addEventListener("mousemove", onMove);
        document.addEventListener("mouseup", onUp);
    });
    window.addEventListener("resize", moveTabIndicator);
}

/* ===== Init ===== */
var _setupDone = false;
var _initDone = false;
function setupOnce() {
    if (_setupDone) return;
    _setupDone = true;
    setupSearch();
    setupAgeFilter();
    setupKeyboard();
    setupResize();
}

async function init(force) {
    if (_initDone && !force) return;
    _initDone = true;
    await bridge.whenReady();
    setupOnce();

    var ui = await bridge.getUiStrings();
    if (ui && !ui.error) state.ui = ui;
    applyUi();

    var topics = await bridge.getTopics();
    if (!topics || topics.error) return;
    renderTopics(topics);

    if (topics.length) {
        var slug = topics[0].slug;
        if (state.selectedTopic && topics.some(function (x) { return x.slug === state.selectedTopic; })) {
            slug = state.selectedTopic;
        }
        await selectTopic(slug, state.selectedPathology);
    } else {
        clearContent();
    }
}

document.addEventListener("DOMContentLoaded", init);
