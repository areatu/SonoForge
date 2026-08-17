"use strict";

var state = {
    topics: [],
    selectedTopic: null,
    selectedPathology: null,
    currentImages: [],
    currentImageIndex: 0,
};

var $ = function (s) { return document.querySelector(s); };

/* ===== Topics ===== */
function renderTopics(topics) {
    state.topics = topics;
    var c = $("#topicsList");
    c.innerHTML = "";
    var topicIcons = {
        left_ventricle: "🫀", left_atrium: "🫀", right_ventricle: "🫀",
        right_atrium: "🫀", mitral_valve: "❤️", aortic_valve: "❤️",
        tricuspid_valve: "❤️", pulmonary_valve: "❤️", aorta: "🩸",
        prosthetic_valve: "⚙️", other: "📁",
    };
    topics.forEach(function (topic) {
        var btn = document.createElement("button");
        btn.className = "topic-btn" + (state.selectedTopic === topic.slug ? " active" : "");
        var icon = topicIcons[topic.slug] || "📁";
        btn.innerHTML = '<span class="topic-icon">' + icon + '</span>' + escapeHtml(topic.name);
        btn.addEventListener("click", function () { selectTopic(topic.slug); });
        c.appendChild(btn);
    });
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
    $("#pathologyTitle").textContent = topicName || "Патологии";
    if (!pathologies || !pathologies.length) {
        bar.innerHTML = '<span style="color:var(--text-muted);font-size:12px;">Нет патологий</span>';
        return;
    }
    pathologies.forEach(function (patho) {
        var btn = document.createElement("button");
        btn.className = "patho-btn" + (state.selectedPathology === patho.slug ? " active" : "");
        btn.textContent = patho.name + " (" + patho.param_count + ")";
        btn.addEventListener("click", function () { selectPathology(patho.slug); });
        bar.appendChild(btn);
    });
}

async function selectPathology(slug) {
    state.selectedPathology = slug;
    // Re-render pathologies to update active state
    var topicData = await bridge.getTopicDetail(state.selectedTopic);
    if (!topicData.error) renderPathologies(topicData.pathologies || [], topicData.name);

    var data = await bridge.getPathology(state.selectedTopic, slug);
    if (data.error) return;
    renderParams(data);
    renderImages(data.images || []);
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
        return;
    }
    empty.hidden = true;
    area.hidden = false;

    // Gradation legend
    if (data.grad_names && data.grad_names.length) {
        legend.hidden = false;
        legend.innerHTML = "";
        var classes = ["grad-normal", "grad-mild", "grad-moderate", "grad-severe"];
        data.grad_names.forEach(function (gn, i) {
            var tag = document.createElement("span");
            tag.className = "grad-tag " + (classes[i % classes.length]);
            tag.textContent = gn;
            legend.appendChild(tag);
        });
    } else {
        legend.hidden = true;
    }

    // Table header
    var nCols = 3 + (data.grad_names ? data.grad_names.length : 0);
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

        // Name cell
        var tdName = document.createElement("td");
        tdName.className = "param-name";
        tdName.textContent = param.name + (param.unit ? " (" + param.unit + ")" : "");
        tdName.title = param.pathology_desc || "";
        tr.appendChild(tdName);

        // Norm male
        var tdM = document.createElement("td");
        tdM.className = "norm-value";
        tdM.textContent = param.norm_male || "—";
        tr.appendChild(tdM);

        // Norm female
        var tdF = document.createElement("td");
        tdF.className = "norm-value";
        tdF.textContent = param.norm_female || "—";
        tr.appendChild(tdF);

        // Gradation cells
        if (param.gradations) {
            param.gradations.forEach(function (gv) {
                var td = document.createElement("td");
                td.className = "grad-cell";
                td.textContent = gv || "—";
                if (gv && gv !== "—") {
                    var cls = gradCellClass(gv);
                    if (cls) td.classList.add(cls);
                }
                tr.appendChild(td);
            });
        }

        tr.addEventListener("click", function () {
            $$(".param-table tr.selected").forEach(function (r) { r.classList.remove("selected"); });
            tr.classList.add("selected");
            if (param.source) {
                source.textContent = "Источник: " + param.source;
                source.hidden = false;
            } else {
                source.hidden = true;
            }
        });

        body.appendChild(tr);
    });

    // Source from first param with source
    var firstWithSource = data.parameters.find(function (p) { return p.source; });
    if (firstWithSource) {
        source.textContent = "Источник: " + firstWithSource.source;
        source.hidden = false;
    } else {
        source.hidden = true;
    }
}

function clearContent() {
    $("#emptyState").hidden = false;
    $("#paramsArea").hidden = true;
    $("#sourceBar").hidden = true;
    clearImages();
}

function gradCellClass(value) {
    var lower = value.toLowerCase();
    if (lower.indexOf("норм") >= 0) return "grad-normal-cell";
    if (lower.indexOf("лёгк") >= 0 || lower.indexOf("легк") >= 0) return "grad-mild-cell";
    if (lower.indexOf("умерен") >= 0) return "grad-moderate-cell";
    if (lower.indexOf("тяжёл") >= 0 || lower.indexOf("тяжел") >= 0) return "grad-severe-cell";
    return "";
}

/* ===== Images ===== */
function renderImages(images) {
    var area = $("#imageArea");
    var empty = $("#imageEmpty");
    var img = $("#mainImage");
    var nav = $("#imageNav");

    state.currentImages = images.filter(function (i) { return i.exists; });
    state.currentImageIndex = 0;

    if (!state.currentImages.length) {
        empty.hidden = false;
        img.hidden = true;
        nav.hidden = true;
        return;
    }
    empty.hidden = true;
    img.hidden = false;
    nav.hidden = false;
    showCurrentImage();
}

function showCurrentImage() {
    var img = $("#mainImage");
    var counter = $("#imageCounter");
    var prev = $("#btnImgPrev");
    var next = $("#btnImgNext");
    var images = state.currentImages;
    var idx = state.currentImageIndex;

    if (!images.length) return;
    img.src = images[idx].url;
    img.alt = images[idx].name;
    counter.textContent = (idx + 1) + " / " + images.length;
    prev.disabled = idx === 0;
    next.disabled = idx === images.length - 1;
}

function clearImages() {
    $("#imageEmpty").hidden = false;
    $("#mainImage").hidden = true;
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
            var labels = { topic: "Тема", pathology: "Патология", parameter: "Параметр" };
            hits.forEach(function (h) {
                var el = document.createElement("div");
                el.className = "search-result-item";
                el.innerHTML = '<div class="search-result-type">' + (labels[h.type] || h.type) + '</div><div class="search-result-name">' + escapeHtml(h.name) + '</div>';
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
        }, 250);
    });
    inp.addEventListener("blur", function () { setTimeout(function () { res.hidden = true; }, 200); });
}

function escapeHtml(s) {
    if (!s) return "";
    var d = document.createElement("div");
    d.textContent = s;
    return d.innerHTML;
}

/* ===== Init ===== */
async function init() {
    await bridge.whenReady();
    var topics = await bridge.getTopics();
    renderTopics(topics);
    setupSearch();

    // Auto-select first topic
    if (topics.length > 0) {
        selectTopic(topics[0].slug);
    }
}

document.addEventListener("DOMContentLoaded", init);
