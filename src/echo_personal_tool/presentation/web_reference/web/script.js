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
    c.innerHTML = "";
    topics.forEach(function (topic) {
        var btn = document.createElement("button");
        btn.className = "topic-btn" + (state.selectedTopic === topic.slug ? " active" : "");
        btn.innerHTML =
            '<span class="topic-icon">' + escapeHtml(topic.label || topic.name.substring(0, 4)) + '</span>' +
            '<span>' + escapeHtml(topic.name) + '</span>' +
            '<span class="topic-badge">' + topic.n_params + '</span>';
        btn.addEventListener("click", function () { selectTopic(topic.slug); });
        c.appendChild(btn);
    });
    // Stats
    var totalParams = topics.reduce(function (s, t) { return s + t.n_params; }, 0);
    var totalImages = topics.reduce(function (s, t) { return s + t.n_images; }, 0);
    $("#statsText").textContent = topics.length + " тем · " + totalParams + " параметров · " + totalImages + " изображений";
}

async function selectTopic(slug) {
    state.selectedTopic = slug;
    state.selectedPathology = null;
    renderTopics(state.topics);
    var data = await bridge.getTopicDetail(slug);
    if (data.error) return;
    renderPathologies(data.pathologies || [], data.name);
    clearContent();
}

/* ===== Pathologies ===== */
function renderPathologies(pathologies, topicName) {
    var bar = $("#pathologyBar");
    bar.innerHTML = "";
    if (!pathologies || !pathologies.length) {
        bar.innerHTML = '<span class="empty-hint">Нет патологий</span>';
        return;
    }
    pathologies.forEach(function (patho) {
        var btn = document.createElement("button");
        btn.className = "patho-btn" + (state.selectedPathology === patho.slug ? " active" : "");
        var label = escapeHtml(patho.name);
        if (patho.image_count > 0) {
            label += ' <span class="patho-badge">🖼' + patho.image_count + '</span>';
        }
        btn.innerHTML = label;
        btn.title = patho.description || patho.name;
        btn.addEventListener("click", function () { selectPathology(patho.slug); });
        bar.appendChild(btn);
    });
}

async function selectPathology(slug) {
    state.selectedPathology = slug;
    var topicData = await bridge.getTopicDetail(state.selectedTopic);
    if (!topicData.error) renderPathologies(topicData.pathologies || [], topicData.name);

    var data = await bridge.getPathology(state.selectedTopic, slug);
    if (data.error) return;

    // Description panel
    renderDescription(data.description);

    // Parameters
    state.currentParams = data.parameters || [];
    renderParams(data);

    // Images
    renderImages(data.images || []);
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
    var empty = $("#emptyState");
    var area = $("#paramsArea");
    var head = $("#paramHead");
    var body = $("#paramBody");
    var legend = $("#gradationLegend");
    var source = $("#sourceBar");

    if (!data.parameters || !data.parameters.length) {
        empty.hidden = false;
        area.hidden = true;
        source.hidden = true;
        return;
    }
    empty.hidden = true;
    area.hidden = false;

    // Gradation legend
    legend.innerHTML = "";
    if (data.grad_names && data.grad_names.length) {
        var classes = ["grad-normal", "grad-mild", "grad-moderate", "grad-severe"];
        data.grad_names.forEach(function (gn, i) {
            var tag = document.createElement("span");
            tag.className = "grad-tag " + (classes[i % classes.length]);
            tag.textContent = gn;
            legend.appendChild(tag);
        });
    }

    // Table header
    head.innerHTML = "";
    var hr = document.createElement("tr");
    ["Показатель", "Норм М", "Норм Ж"].forEach(function (h) {
        var th = document.createElement("th");
        th.textContent = h;
        hr.appendChild(th);
    });
    if (data.grad_names) {
        data.grad_names.forEach(function (gn) {
            var th = document.createElement("th");
            th.textContent = gn;
            hr.appendChild(th);
        });
    }
    head.appendChild(hr);

    // Table body
    body.innerHTML = "";
    data.parameters.forEach(function (param) {
        var tr = document.createElement("tr");

        // Name cell with unit and pathology desc
        var tdName = document.createElement("td");
        tdName.className = "param-name";
        var nameHtml = escapeHtml(param.name);
        if (param.unit) nameHtml += ' <span style="color:var(--text-muted);font-weight:normal;">(' + escapeHtml(param.unit) + ')</span>';
        tdName.innerHTML = nameHtml;
        if (param.pathology_desc) {
            tdName.title = param.pathology_desc;
        }
        tr.appendChild(tdName);

        // Norm male
        var tdM = document.createElement("td");
        tdM.className = "norm-value";
        tdM.textContent = param.norm_male || "\u2014";
        tr.appendChild(tdM);

        // Norm female
        var tdF = document.createElement("td");
        tdF.className = "norm-value";
        tdF.textContent = param.norm_female || "\u2014";
        tr.appendChild(tdF);

        // Gradation cells
        if (param.gradations) {
            param.gradations.forEach(function (gv) {
                var td = document.createElement("td");
                td.className = "grad-cell";
                td.textContent = gv || "\u2014";
                if (gv && gv !== "\u2014") {
                    var cls = gradCellClass(gv);
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

        body.appendChild(tr);

        // Pathology description sub-row
        if (param.pathology_desc) {
            var descTr = document.createElement("tr");
            descTr.className = "desc-row";
            var descTd = document.createElement("td");
            descTd.className = "patho-desc";
            descTd.colSpan = 3 + (data.grad_names ? data.grad_names.length : 0);
            descTd.textContent = param.pathology_desc;
            descTr.appendChild(descTd);
            body.appendChild(descTr);
        }
    });

    // Source from first param with source
    var firstWithSource = data.parameters.find(function (p) { return p.source; });
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
    $("#emptyState").hidden = false;
    $("#paramsArea").hidden = true;
    $("#descPanel").hidden = true;
    $("#sourceBar").hidden = true;
    clearImages();
}

function gradCellClass(value) {
    var lower = value.toLowerCase();
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
    thumbs.innerHTML = "";
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
        thumbs.appendChild(thumb);
    });

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
                res.innerHTML = '<div class="search-result-item"><span class="search-result-name">Ничего не найдено</span></div>';
                res.hidden = false;
                return;
            }
            res.innerHTML = "";
            var labels = { topic: "\u{1F4CB} Тема", pathology: "\u{1F4C4} Патология", parameter: "\u{1F4CA} Параметр" };
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
                res.appendChild(el);
            });
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
async function init() {
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
