"use strict";

var state = {
    topics: [],
    selectedTopic: null,
    selectedPathology: null,
    currentImages: [],
    currentImageIndex: 0,
    currentParams: [],
};

var $ = function (s) { return document.querySelector(s); };
var $$ = function (s) { return document.querySelectorAll(s); };

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
    var totalParams = topics.reduce(function (s, t) { return s + t.n_params; }, 0);
    var totalImages = topics.reduce(function (s, t) { return s + t.n_images; }, 0);
    $("#statsText").textContent = topics.length + " topics · " + totalParams + " parameters · " + totalImages + " images";
}

async function selectTopic(slug) {
    state.selectedTopic = slug;
    state.selectedPathology = null;
    renderTopics(state.topics);
    var data = await bridge.getTopicDetail(slug);
    if (data.error) return;
    var pathos = data.pathologies || [];
    if (pathos.length > 0) {
        state.selectedPathology = pathos[0].slug;
    }
    renderPathologies(pathos, data.name);
    if (pathos.length > 0) {
        var pathoData = await bridge.getPathology(slug, pathos[0].slug);
        if (!pathoData.error) {
            var split = $(".content-split");
            split.classList.add("fading-out");
            requestAnimationFrame(function() {
                requestAnimationFrame(function() {
                    renderDescription(pathoData.description);
                    state.currentParams = pathoData.parameters || [];
                    renderParams(pathoData);
                    renderImages(pathoData.images || []);
                    split.classList.remove("fading-out");
                });
            });
        }
    } else {
        clearContent();
    }
}

/* ===== Pathologies ===== */
/* ===== Pathology Tab Indicator ===== */
function moveTabIndicator() {
    var bar = $("#pathologyBar");
    var activeBtn = bar.querySelector(".patho-btn.active");
    var indicator = bar;
    if (activeBtn) {
        var rect = activeBtn.getBoundingClientRect();
        var barRect = bar.getBoundingClientRect();
        bar.style.setProperty("--indicator-left", (rect.left - barRect.left + bar.scrollLeft) + "px");
        bar.style.setProperty("--indicator-width", rect.width + "px");
    } else {
        bar.style.setProperty("--indicator-left", "0px");
        bar.style.setProperty("--indicator-width", "0px");
    }
}

function renderPathologies(pathologies, topicName) {
    var bar = $("#pathologyBar");
    if (!pathologies || !pathologies.length) {
        bar.innerHTML = '<span class="empty-hint">No pathologies</span>';
        return;
    }
    var fragment = document.createDocumentFragment();
    pathologies.forEach(function (patho) {
        var btn = document.createElement("button");
        btn.className = "patho-btn" + (state.selectedPathology === patho.slug ? " active" : "");
        btn.setAttribute("data-slug", patho.slug);
        var label = escapeHtml(patho.name);
        if (patho.image_count > 0) {
            label += ' <span class="patho-badge">🖼' + patho.image_count + '</span>';
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

function updatePathologyActive(newSlug) {
    $$(".patho-btn").forEach(function (btn) {
        var isActive = btn.getAttribute("data-slug") === newSlug;
        btn.classList.toggle("active", isActive);
    });
    moveTabIndicator();
}

async function selectPathology(slug) {
    state.selectedPathology = slug;

    // Synchronously update tab highlight (no DOM rebuild)
    $$(".patho-btn").forEach(function (btn) {
        btn.classList.remove("active");
    });
    // Find the clicked button and mark active by data-slug
    var allBtns = $$(".patho-btn");
    for (var i = 0; i < allBtns.length; i++) {
        if (allBtns[i].getAttribute("data-slug") === slug) {
            allBtns[i].classList.add("active");
            break;
        }
    }
    // Animate indicator to active tab
    moveTabIndicator();

    var data = await bridge.getPathology(state.selectedTopic, slug);
    if (data.error) return;

    // Cross-fade + slide: fade out, swap content, fade in with slide
    var split = $(".content-split");
    split.classList.add("fading-out");
    requestAnimationFrame(function() {
        requestAnimationFrame(function() {
            renderDescription(data.description);
            state.currentParams = data.parameters || [];
            renderParams(data);
            renderImages(data.images || []);
            split.classList.remove("fading-out");
        });
    });
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
function renderParams(data) {
    var area = $("#paramsArea");
    var head = $("#paramHead");
    var body = $("#paramBody");
    var source = $("#sourceBar");

    area.hidden = false;

    // Build new header
    var hasGrads = data.grad_names && data.grad_names.length > 0;
    var headers = hasGrads ? ["Parameter"] : ["Parameter", "Norm M", "Norm F"];
    if (hasGrads) {
        headers = headers.concat(data.grad_names);
    }

    // Check if we can reuse existing structure (same headers = no jump)
    var existingHeaders = [];
    head.querySelectorAll("th").forEach(function(th) { existingHeaders.push(th.textContent); });
    var headersMatch = JSON.stringify(existingHeaders) === JSON.stringify(headers);

    if (!headersMatch) {
        // Only rebuild header when structure changes
        head.innerHTML = "";
        var hr = document.createElement("tr");
        headers.forEach(function (h) {
            var th = document.createElement("th");
            th.textContent = h;
            hr.appendChild(th);
        });
        head.appendChild(hr);
    }

    // Build body fragment (off-DOM for performance)
    var fragment = document.createDocumentFragment();
    if (!data.parameters || !data.parameters.length) {
        var emptyTr = document.createElement("tr");
        var emptyTd = document.createElement("td");
        emptyTd.colSpan = hasGrads ? 1 + data.grad_names.length : 3;
        emptyTd.textContent = "No parameters for this pathology";
        emptyTd.className = "patho-desc";
        emptyTd.style.textAlign = "center";
        emptyTr.appendChild(emptyTd);
        fragment.appendChild(emptyTr);
    } else {
        var rowIndex = 0;
        data.parameters.forEach(function (param) {
            var tr = document.createElement("tr");
            tr.style.setProperty("--row-index", rowIndex++);

            // Name cell with unit
            var tdName = document.createElement("td");
            tdName.className = "param-name";
            var nameHtml = '<span class="param-title" data-field="name" data-param="' + escapeHtml(param.id) + '">' + escapeHtml(param.name) + '</span>';
            if (param.unit) {
                nameHtml += ' <span class="param-unit" data-field="unit" data-param="' + escapeHtml(param.id) + '">(' + escapeHtml(param.unit) + ')</span>';
            }
            tdName.innerHTML = nameHtml;
            tdName.setAttribute("data-full", param.full_name || param.name);
            if (param.unit) tdName.setAttribute("data-unit", param.unit);
            tr.appendChild(tdName);

            // Norm male / female — only when the pathology has no gradations
            if (!hasGrads) {
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
            }

            // Gradation cells
            if (param.gradations) {
                param.gradations.forEach(function (gv, gi) {
                    var td = document.createElement("td");
                    td.className = "grad-cell";
                    td.textContent = gv || "\u2014";
                    td.setAttribute("data-field", "gradation");
                    td.setAttribute("data-param", param.id);
                    if (data.grad_names) td.setAttribute("data-grad", data.grad_names[gi]);
                    if (gv && gv !== "\u2014") {
                        var name = data.grad_names && data.grad_names[gi];
                        var cls = gradClassForName(name);
                        if (cls) td.classList.add(cls);
                    }
                    tr.appendChild(td);
                });
            }

            // Pathology description row (below the main row)
        if (param.pathology_desc) {
            tr.addEventListener("click", function () {
                $$(".param-table tr.selected").forEach(function (r) { r.classList.remove("selected"); });
                tr.classList.add("selected");
                showSource(param.source);
            });
        } else {
            tr.addEventListener("click", function () {
                $$(".param-table tr.selected").forEach(function (r) { r.classList.remove("selected"); });
                tr.classList.add("selected");
                showSource(param.source);
            });
        }

        fragment.appendChild(tr);

        // Pathology description sub-row
        if (param.pathology_desc) {
            var descTr = document.createElement("tr");
            descTr.className = "desc-row";
            var descTd = document.createElement("td");
            descTd.className = "patho-desc";
            descTd.colSpan = 3 + (data.grad_names ? data.grad_names.length : 0);
            descTd.textContent = param.pathology_desc;
            descTr.appendChild(descTd);
            fragment.appendChild(descTr);
        }
    });
    }

    // Single DOM replacement to avoid micro-jumps
    body.innerHTML = "";
    body.appendChild(fragment);

    // Source from first param with source
    var firstWithSource = data.parameters ? data.parameters.find(function (p) { return p.source; }) : null;
    if (firstWithSource) {
        showSource(firstWithSource.source);
    } else {
        source.hidden = true;
    }
}

function showSource(source) {
    var bar = $("#sourceBar");
    if (source) {
        bar.textContent = "\u{1F4D6} " + source;
        bar.hidden = false;
    } else {
        bar.hidden = true;
    }
}

function clearContent() {
    $("#paramsArea").hidden = true;
    $("#descPanel").hidden = true;
    $("#sourceBar").hidden = true;
    clearImages();
}

function gradClassForName(name) {
    if (!name) return "";
    var lower = name.toLowerCase();
    if (lower.indexOf("\u043d\u043e\u0440\u043c") >= 0) return "grad-normal-cell";
    if (lower.indexOf("\u043b\u0451\u0433\u043a") >= 0 || lower.indexOf("\u043b\u0435\u0433\u043a") >= 0) return "grad-mild-cell";
    if (lower.indexOf("\u0443\u043c\u0435\u0440\u0435\u043d") >= 0) return "grad-moderate-cell";
    if (lower.indexOf("\u0442\u044f\u0436\u0451\u043b") >= 0 || lower.indexOf("\u0442\u044f\u0436\u0435\u043b") >= 0) return "grad-severe-cell";
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
    thumbs.forEach(function (t, i) {
        t.classList.toggle("active", i === idx);
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
    }
});
$("#modalNext").addEventListener("click", function () {
    if (state.currentImageIndex < state.currentImages.length - 1) {
        state.currentImageIndex++;
        renderModalImage();
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
        '#paramBody .param-title, #paramBody .param-unit, #paramBody td.norm-value, #paramBody td.grad-cell'
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
        if (data.error) return;
        renderDescription(data.description);
        state.currentParams = data.parameters || [];
        renderParams(data);
        renderImages(data.images || []);
    });
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
            var parts = text.split(" / ");
            results.push(await bridge.updateGradation(
                state.selectedTopic, state.selectedPathology, paramId,
                el.getAttribute("data-grad") || "", parts[0] || "", parts[1] || ""
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

$("#editToggle").addEventListener("click", function () {
    if (editMode) { exitEditMode(); } else { enterEditMode(); }
});
$("#saveBtn").addEventListener("click", saveDirtyCells);
$("#cancelBtn").addEventListener("click", function () {
    exitEditMode();
    refreshPathology();
});
document.querySelector("#paramBody").addEventListener("input", function (e) {
    if (!editMode) return;
    var el = e.target.closest ? e.target.closest("[contenteditable]") : null;
    if (el) el.classList.add("dirty");
});

/* ===== Search ===== */
var searchTimeout = null;
function setupSearch() {
    var inp = $("#searchInput");
    var res = $("#searchResults");
    inp.addEventListener("input", function () {
        clearTimeout(searchTimeout);
        var q = inp.value.trim();
        if (!q) { res.hidden = true; return; }
        searchTimeout = setTimeout(async function () {
            var hits = await bridge.search(q);
            if (!hits || !hits.length) {
                res.innerHTML = '<div class="search-result-item"><span class="search-result-name">Nothing found</span></div>';
                res.hidden = false;
                return;
            }
            var fragment = document.createDocumentFragment();
            var labels = { topic: "\u{1F4CB} Topic", pathology: "\u{1F4C4} Pathology", parameter: "\u{1F4CA} Parameter" };
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
                    if (h.type === "topic") selectTopic(h.topic_slug);
                    else if (h.type === "pathology" || h.type === "parameter") {
                        selectTopic(h.topic_slug).then(function () {
                            if (h.patho_slug) selectPathology(h.patho_slug);
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

/* ===== Age Filter ===== */
function setupAgeFilter() {
    var inp = $("#ageInput");
    inp.addEventListener("input", function () {
        var age = inp.value.trim();
        // Age filter is visual-only for now — could be used to highlight age-specific norms
        // For future: filter parameters by age range if data supports it
    });
}

function escapeHtml(s) {
    if (!s) return "";
    var d = document.createElement("div");
    d.textContent = s;
    return d.innerHTML;
}

/* ===== Keyboard Shortcuts ===== */
function setupKeyboard() {
    document.addEventListener("keydown", function (e) {
        // Modal navigation
        if (!$("#imageModal").hidden) {
            if (e.key === "Escape") { closeModal(); return; }
            if (e.key === "ArrowLeft") { e.preventDefault(); $("#modalPrev").click(); return; }
            if (e.key === "ArrowRight") { e.preventDefault(); $("#modalNext").click(); return; }
        }
        // Focus search on Ctrl+F
        if (e.ctrlKey && e.key === "f") {
            e.preventDefault();
            $("#searchInput").focus();
        }
        // Escape: clear search
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

/* ===== Init ===== */
let _pageInitialized = false;
async function init() {
    if (_pageInitialized) return;
    _pageInitialized = true;
    await bridge.whenReady();
    var topics = await bridge.getTopics();
    renderTopics(topics);
    setupSearch();
    setupAgeFilter();
    setupKeyboard();

    // Auto-select first topic
    if (topics.length > 0) {
        selectTopic(topics[0].slug);
    }
}

document.addEventListener("DOMContentLoaded", init);
