# Reference Redesign — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Redesign the Reference (Справочник) module — add gradations for all parameters, improve table UI (color coding, no-scroll, adjustable columns), remove sex radio buttons, and add Excel-like constructor editor.

**Architecture:** Three independent phases (Data → UI → Constructor). Each phase produces working, testable software. Phase 1 extends the YAML data model and populates gradation data. Phase 2 rewrites the table rendering in `StructuredReferenceWidget`. Phase 3 adds Excel-like editing to `ParameterTableEditor`.

**Tech Stack:** Python 3.10–3.11, PySide6, PyYAML, pytest

## Global Constraints

- Python 3.10+ (use `X | None` union syntax, `list[T]` generics)
- PySide6 for all Qt widgets
- Dark theme via `get_theme_palette()` — all colors from palette, never hardcoded
- i18n via `tr()` for all user-visible strings
- Follow existing code conventions: no comments unless asked, dataclasses for models
- YAML backward-compatible: old format (pathology-level gradations) must still parse

---

## Phase 1: Data Model + YAML

### Task 1: Add ParameterGradationRef to data model

**Files:**
- Modify: `src/echo_personal_tool/domain/services/reference_data_store.py`
- Test: `tests/unit/test_reference_data_store.py`

**Interfaces:**
- Produces: `ParameterGradationRef` dataclass with fields `name: str`, `range_male: NormRange | None`, `range_female: NormRange | None`
- Produces: `ParameterRef.gradations: list[ParameterGradationRef]`

- [ ] **Step 1: Write the failing test**

```python
# Add to tests/unit/test_reference_data_store.py

def test_parameter_gradations_loaded(store_with_param_gradations):
    patho = store_with_param_gradations.get_pathology("left_ventricle", "lv_mass")
    assert patho is not None
    param = patho.parameters[0]
    assert param.id == "lvm"
    assert len(param.gradations) == 4
    assert param.gradations[0].name == "Норма"
    assert param.gradations[0].range_male.low == 88
    assert param.gradations[0].range_male.high == 224
    assert param.gradations[1].name == "Лёгкое увеличение"
    assert param.gradations[1].range_male.low == 225
    assert param.gradations[2].range_male.low == 259
    assert param.gradations[3].range_male.low == 293
```

Add a new fixture:

```python
_SAMPLE_YAML_PARAM_GRADATIONS = """
topics:
  - name: Левый желудочек
    slug: left_ventricle
    pathologies:
      - name: Масса миокарда ЛЖ
        slug: lv_mass
        parameters:
          - id: lvm
            name: Масса миокарда ЛЖ (LVM)
            unit: г
            norm_male: {low: 88, high: 224}
            norm_female: {low: 66, high: 150}
            gradations:
              - name: Норма
                range_male: {low: 88, high: 224}
                range_female: {low: 66, high: 150}
              - name: Лёгкое увеличение
                range_male: {low: 225, high: 258}
                range_female: {low: 151, high: 171}
              - name: Умеренное увеличение
                range_male: {low: 259, high: 292}
                range_female: {low: 172, high: 193}
              - name: Тяжёлое увеличение
                range_male: {low: 293}
                range_female: {low: 194}
            source: "ASE 2015"
"""


@pytest.fixture
def store_with_param_gradations(tmp_path):
    path = tmp_path / "test_param_grads.yaml"
    path.write_text(_SAMPLE_YAML_PARAM_GRADATIONS, encoding="utf-8")
    return ReferenceDataStore(str(path)).load()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_reference_data_store.py::test_parameter_gradations_loaded -v`
Expected: FAIL — `ParameterRef` has no `gradations` attribute

- [ ] **Step 3: Add ParameterGradationRef dataclass and extend ParameterRef**

```python
# In reference_data_store.py, add after NormRange:

@dataclass
class ParameterGradationRef:
    name: str = ""
    range_male: NormRange | None = None
    range_female: NormRange | None = None


# In ParameterRef, add field:
@dataclass
class ParameterRef:
    id: str = ""
    name: str = ""
    unit: str = ""
    norm_male: NormRange | None = None
    norm_female: NormRange | None = None
    pathology_desc: str | None = None
    source: str | None = None
    gradations: list[ParameterGradationRef] = field(default_factory=list)
```

Update `_parse_parameters()`:

```python
def _parse_parameter_gradations(raw: list[dict] | None) -> list[ParameterGradationRef]:
    if not raw:
        return []
    return [
        ParameterGradationRef(
            name=g["name"],
            range_male=_parse_norm_range(g.get("range_male")),
            range_female=_parse_norm_range(g.get("range_female")),
        )
        for g in raw
    ]


def _parse_parameters(raw: list[dict]) -> list[ParameterRef]:
    return [
        ParameterRef(
            id=p["id"],
            name=p["name"],
            unit=p.get("unit", ""),
            norm_male=_parse_norm_range(p.get("norm_male")),
            norm_female=_parse_norm_range(p.get("norm_female")),
            pathology_desc=p.get("pathology_desc"),
            source=p.get("source"),
            gradations=_parse_parameter_gradations(p.get("gradations")),
        )
        for p in raw
    ]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/test_reference_data_store.py::test_parameter_gradations_loaded -v`
Expected: PASS

- [ ] **Step 5: Run all existing tests to verify no regression**

Run: `uv run pytest tests/unit/test_reference_data_store.py -v`
Expected: All PASS (backward-compatible — old YAML without `gradations` key parses with empty list)

- [ ] **Step 6: Commit**

```bash
git add src/echo_personal_tool/domain/services/reference_data_store.py tests/unit/test_reference_data_store.py
git commit -m "feat(data): add ParameterGradationRef to ParameterRef model"
```

---

### Task 2: Extend ParameterModel (constructor) with gradations

**Files:**
- Modify: `src/echo_personal_tool/constructor/models/reference_model.py`
- Test: `tests/unit/test_reference_model.py` (create if not exists)

**Interfaces:**
- Produces: `ParameterGradationModel` dataclass with `name`, `range_male`, `range_female`
- Produces: `ParameterModel.gradations: list[ParameterGradationModel]`
- Produces: `ParameterModel.to_dict()` includes `gradations`
- Produces: `ParameterModel.from_dict()` parses `gradations`

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_reference_model.py`:

```python
"""Tests for constructor reference models."""

from echo_personal_tool.constructor.models.reference_model import (
    NormRangeModel,
    ParameterGradationModel,
    ParameterModel,
    ReferenceModel,
)


def test_parameter_gradation_model_roundtrip():
    param = ParameterModel(
        id="lvm",
        name="LVM",
        unit="г",
        norm_male=NormRangeModel(low=88, high=224),
        gradations=[
            ParameterGradationModel(
                name="Норма",
                range_male=NormRangeModel(low=88, high=224),
                range_female=NormRangeModel(low=66, high=150),
            ),
            ParameterGradationModel(
                name="Лёгкое увеличение",
                range_male=NormRangeModel(low=225, high=258),
                range_female=NormRangeModel(low=151, high=171),
            ),
        ],
    )
    d = param.to_dict()
    assert d["gradations"][0]["name"] == "Норма"
    assert d["gradations"][0]["range_male"]["low"] == 88
    assert d["gradations"][1]["range_female"]["low"] == 151


def test_parameter_gradation_from_dict():
    d = {
        "id": "lvm",
        "name": "LVM",
        "unit": "г",
        "gradations": [
            {"name": "Норма", "range_male": {"low": 88, "high": 224}},
            {"name": "Тяжёлое", "range_male": {"low": 293}},
        ],
    }
    param = ParameterModel.from_dict(d)
    assert len(param.gradations) == 2
    assert param.gradations[0].name == "Норма"
    assert param.gradations[1].range_male.low == 293


def test_reference_model_yaml_roundtrip():
    model = ReferenceModel.from_yaml(
        """topics:
- name: Test
  slug: test
  pathologies:
  - name: P1
    slug: p1
    parameters:
    - id: param1
      name: Param 1
      gradations:
      - name: Норма
        range_male: {low: 1, high: 10}
"""
    )
    topic = model.topics[0]
    param = topic.pathologies[0].parameters[0]
    assert len(param.gradations) == 1
    assert param.gradations[0].range_male.low == 1

    yaml_out = model.to_yaml()
    assert "gradations" in yaml_out
    assert "range_male" in yaml_out
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_reference_model.py -v`
Expected: FAIL — `ParameterGradationModel` not found

- [ ] **Step 3: Add ParameterGradationModel and extend ParameterModel**

In `reference_model.py`, add after `NormRangeModel`:

```python
@dataclass
class ParameterGradationModel:
    name: str = ""
    range_male: NormRangeModel | None = None
    range_female: NormRangeModel | None = None

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {"name": self.name}
        if self.range_male:
            d["range_male"] = self.range_male.to_dict()
        if self.range_female:
            d["range_female"] = self.range_female.to_dict()
        return d

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> ParameterGradationModel:
        return cls(
            name=d.get("name", ""),
            range_male=NormRangeModel.from_dict(d.get("range_male")),
            range_female=NormRangeModel.from_dict(d.get("range_female")),
        )
```

In `ParameterModel`, add field:

```python
@dataclass
class ParameterModel:
    id: str = ""
    name: str = ""
    unit: str = ""
    norm_male: NormRangeModel | None = None
    norm_female: NormRangeModel | None = None
    pathology_desc: str | None = None
    source: str | None = None
    gradations: list[ParameterGradationModel] = field(default_factory=list)
```

Update `ParameterModel.to_dict()`:

```python
def to_dict(self) -> dict[str, Any]:
    d: dict[str, Any] = {
        "id": self.id,
        "name": self.name,
        "unit": self.unit,
    }
    if self.norm_male:
        d["norm_male"] = self.norm_male.to_dict()
    if self.norm_female:
        d["norm_female"] = self.norm_female.to_dict()
    if self.pathology_desc:
        d["pathology_desc"] = self.pathology_desc
    if self.source:
        d["source"] = self.source
    if self.gradations:
        d["gradations"] = [g.to_dict() for g in self.gradations]
    return d
```

Update `ParameterModel.from_dict()`:

```python
@classmethod
def from_dict(cls, d: dict[str, Any]) -> ParameterModel:
    return cls(
        id=d.get("id", ""),
        name=d.get("name", ""),
        unit=d.get("unit", ""),
        norm_male=NormRangeModel.from_dict(d.get("norm_male")),
        norm_female=NormRangeModel.from_dict(d.get("norm_female")),
        pathology_desc=d.get("pathology_desc"),
        source=d.get("source"),
        gradations=[ParameterGradationModel.from_dict(g) for g in d.get("gradations", [])],
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/test_reference_model.py -v`
Expected: All PASS

- [ ] **Step 5: Run all existing tests**

Run: `uv run pytest tests/unit/ -v`
Expected: All PASS

- [ ] **Step 6: Commit**

```bash
git add src/echo_personal_tool/constructor/models/reference_model.py tests/unit/test_reference_model.py
git commit -m "feat(constructor): add ParameterGradationModel to reference model"
```

---

### Task 3: Populate YAML with gradations for all parameters

**Files:**
- Modify: `src/echo_personal_tool/resources/references/references_structured.yaml`
- Modify: `src/echo_personal_tool/resources/references/references_schema.json`

**Interfaces:**
- Consumes: `ParameterGradationRef` structure from Task 1
- Produces: gradation data for all parameters in the YAML file

- [ ] **Step 1: Add gradations for Левый желудочек — Масса миокарда**

In `references_structured.yaml`, find the `lv_mass` pathology (lines 5–37) and add `gradations` to each parameter:

```yaml
    - id: lvm
      name: Масса миокарда ЛЖ (LVM)
      unit: г
      norm_male: {low: 88, high: 224}
      norm_female: {low: 66, high: 150}
      gradations:
      - name: Норма
        range_male: {low: 88, high: 224}
        range_female: {low: 66, high: 150}
      - name: Лёгкое увеличение
        range_male: {low: 225, high: 258}
        range_female: {low: 151, high: 171}
      - name: Умеренное увеличение
        range_male: {low: 259, high: 292}
        range_female: {low: 172, high: 193}
      - name: Тяжёлое увеличение
        range_male: {low: 293}
        range_female: {low: 194}
      source: 2015, ASE, Guidelines for the Standardization in Echocardiography
    - id: lvmi
      name: Индекс массы миокарда (LVMI)
      unit: г/м²
      norm_male: {low: 49, high: 115}
      norm_female: {low: 43, high: 95}
      gradations:
      - name: Норма
        range_male: {low: 49, high: 115}
        range_female: {low: 43, high: 95}
      - name: Лёгкое увеличение
        range_male: {low: 116, high: 131}
        range_female: {low: 96, high: 108}
      - name: Умеренное увеличение
        range_male: {low: 132, high: 148}
        range_female: {low: 109, high: 121}
      - name: Тяжёлое увеличение
        range_male: {low: 149}
        range_female: {low: 122}
      source: 2015, ASE, Guidelines for the Standardization in Echocardiography
```

- [ ] **Step 2: Add gradations for Размеры ЛЖ — LVEDD, LVESD, LVEDVi, LVESVi, LVPWd, IVSd**

For each parameter in the `lv_dimensions` pathology, add gradations. Example for LVEDD:

```yaml
    - id: lvedd
      name: Конечно-диастолический диаметр (LVEDD)
      unit: мм
      norm_male: {low: 42, high: 59}
      norm_female: {low: 36, high: 51}
      gradations:
      - name: Норма
        range_male: {low: 42, high: 59}
        range_female: {low: 36, high: 51}
      - name: Лёгкое увеличение
        range_male: {low: 60, high: 63}
        range_female: {low: 52, high: 56}
      - name: Умеренное увеличение
        range_male: {low: 64, high: 68}
        range_female: {low: 57, high: 61}
      - name: Тяжёлое увеличение
        range_male: {low: 69}
        range_female: {low: 62}
```

Repeat pattern for: `lvesd`, `lvedvi`, `lvesvi`, `lvpwd`, `ivsd`.

- [ ] **Step 3: Add gradations for Систолическая функция ЛЖ — LVEF, FAC**

```yaml
    - id: lvef
      name: Фракция выброса ЛЖ (LVEF)
      unit: "%"
      norm_male: {low: 52, high: 72}
      norm_female: {low: 54, high: 74}
      gradations:
      - name: Норма
        range_male: {low: 52, high: 72}
        range_female: {low: 54, high: 74}
      - name: Лёгкое снижение
        range_male: {low: 41, high: 51}
        range_female: {low: 41, high: 51}
      - name: Умеренное снижение
        range_male: {low: 30, high: 40}
        range_female: {low: 30, high: 40}
      - name: Тяжёлое снижение
        range_male: {high: 29}
        range_female: {high: 29}
```

- [ ] **Step 4: Add gradations for ПЖ — TAPSE, RV S', RV FAC**

```yaml
    - id: tapse
      name: TAPSE
      unit: мм
      norm_male: {low: 17}
      norm_female: {low: 17}
      gradations:
      - name: Норма
        range_male: {low: 17}
        range_female: {low: 17}
      - name: Лёгкое снижение
        range_male: {low: 15, high: 16}
        range_female: {low: 15, high: 16}
      - name: Умеренное снижение
        range_male: {low: 10, high: 14}
        range_female: {low: 10, high: 14}
      - name: Тяжёлое снижение
        range_male: {high: 9}
        range_female: {high: 9}
```

- [ ] **Step 5: Add gradations for remaining parameters (ЛП, ПП, клапаны, аорта)**

Apply the same pattern to all remaining parameters in the YAML. For parameters where official gradation thresholds are not established, leave `gradations` empty (the table will show "—").

- [ ] **Step 6: Update JSON Schema**

In `references_schema.json`, add to the parameter definition:

```json
"gradations": {
  "type": "array",
  "items": {
    "type": "object",
    "required": ["name"],
    "properties": {
      "name": {"type": "string"},
      "range_male": {"$ref": "#/$defs/norm_range"},
      "range_female": {"$ref": "#/$defs/norm_range"}
    }
  }
}
```

- [ ] **Step 7: Verify YAML loads correctly**

Run: `uv run python -c "from echo_personal_tool.domain.services.reference_data_store import ReferenceDataStore; s = ReferenceDataStore().load(); print(f'Loaded {len(s.get_topics())} topics'); p = s.get_topics()[0].pathologies[0].parameters[0]; print(f'{p.id}: {len(p.gradations)} gradations')"`
Expected: Shows topic count and gradation count for first parameter

- [ ] **Step 8: Commit**

```bash
git add src/echo_personal_tool/resources/references/
git commit -m "feat(data): add gradation data for all parameters in YAML"
```

---

## Phase 2: UI Tables

### Task 4: Remove sex radio buttons from left panel

**Files:**
- Modify: `src/echo_personal_tool/presentation/structured_reference_widget.py:419-457`
- Modify: `src/echo_personal_tool/presentation/structured_reference_widget.py:692-694`

**Interfaces:**
- Removes: `self._male_radio`, `self._female_radio`, `self._sex_male`, `_on_sex_changed()`
- Keeps: `_format_norm()` (used by cards), `_format_norm_range()` (used by tables)

- [ ] **Step 1: Remove sex toggle widget from `_build_ui()`**

Delete lines 419–438 (sex_widget creation, sex_group, male_radio, female_radio, sex_label, sex_layout).

- [ ] **Step 2: Remove `_on_sex_changed()` method**

Delete the method at line 692–694.

- [ ] **Step 3: Remove `self._sex_male` from `__init__`**

Delete `self._sex_male: bool = True` from `__init__` (line 283).

- [ ] **Step 4: Update `_format_norm()` to always show both norms**

```python
def _format_norm(self, param) -> str:
    """Format both norms for card view: 'М: 88–224 / Ж: 66–150'."""
    parts = []
    if param.norm_male:
        parts.append(f"М: {self._format_norm_range(param.norm_male)}")
    if param.norm_female:
        parts.append(f"Ж: {self._format_norm_range(param.norm_female)}")
    return " / ".join(parts) if parts else ""
```

- [ ] **Step 5: Verify app launches and table shows both norm columns**

Run: `uv run sonoforge` — open Reference dialog, verify:
- No radio buttons in left panel
- Table shows both Норм М and Норм Ж columns
- Card view shows "М: ... / Ж: ..." format

- [ ] **Step 6: Commit**

```bash
git add src/echo_personal_tool/presentation/structured_reference_widget.py
git commit -m "feat(ui): remove sex radio buttons, show both norm columns always"
```

---

### Task 5: Rewrite table rendering — unified method with color coding

**Files:**
- Modify: `src/echo_personal_tool/presentation/structured_reference_widget.py`

**Interfaces:**
- Removes: `_render_flat_table()`, `_render_gradation_table()`, `_flatten_gradation_parameters()`
- Produces: `_render_parameter_table()` — unified method handling both flat and gradation parameters
- Produces: color-coded cells using `_GRADATION_COLORS` mapping

- [ ] **Step 1: Add gradation color mapping constant**

```python
_GRADATION_COLORS: dict[str, tuple[str, str]] = {
    # keyword -> (bg_rgba, text_hex)
    "норм": ("rgba(34, 197, 94, 0.12)", "#22c55e"),
    "лёгк": ("rgba(234, 179, 8, 0.12)", "#eab308"),
    "умерен": ("rgba(249, 115, 22, 0.12)", "#f97316"),
    "тяжёл": ("rgba(239, 68, 68, 0.12)", "#ef4444"),
}


def _gradation_color(name: str) -> tuple[str, str] | None:
    """Return (bg, text) colors for a gradation name, or None."""
    lower = name.lower()
    for keyword, colors in _GRADATION_COLORS.items():
        if keyword in lower:
            return colors
    return None
```

- [ ] **Step 2: Write `_render_parameter_table()` method**

```python
def _render_parameter_table(self) -> None:
    """Unified table: Показатель | Норм М | Норм Ж | [Градации...]."""
    if self._current_pathology is None:
        return

    params = self._current_pathology.parameters or []
    if not params:
        # Fallback: flatten gradation params (old format)
        if self._current_pathology.gradations:
            params = self._flatten_gradation_parameters(self._current_pathology)
        if not params:
            return

    # Determine if any parameter has gradations
    has_gradations = any(p.gradations for p in params)
    # Collect unique gradation names from all parameters
    grad_names: list[str] = []
    if has_gradations:
        seen: set[str] = set()
        for p in params:
            for g in p.gradations:
                if g.name not in seen:
                    grad_names.append(g.name)
                    seen.add(g.name)

    p = get_theme_palette()
    n_cols = 3 + len(grad_names)  # name + norm_m + norm_f + gradations
    n_rows = len(params)

    table = QTableWidget(n_rows, n_cols)
    table.verticalHeader().hide()
    table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
    table.setSelectionMode(QTableWidget.SelectionMode.NoSelection)
    table.setFocusPolicy(Qt.FocusPolicy.NoFocus)
    table.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
    table.setAlternatingRowColors(True)

    # Column resize: first column stretches, rest are interactive
    header = table.horizontalHeader()
    header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
    for c in range(1, n_cols):
        header.setSectionResizeMode(c, QHeaderView.ResizeMode.Interactive)
        header.resizeSection(c, 100)

    # Headers
    headers = [tr("ref_table.col_param"), tr("ref_table.col_norm_male"), tr("ref_table.col_norm_female")]
    headers.extend(grad_names)
    table.setHorizontalHeaderLabels(headers)

    # Header style
    header_style = (
        f"background: {p['bg_control']}; font-weight: bold; font-size: 12px; "
        f"color: {p['text']}; border-bottom: 2px solid {p['accent_tab']};"
    )
    header.setStyleSheet(f"QHeaderView::section {{ {header_style} padding: 4px 8px; }}")

    # Table style with alternating rows
    table.setStyleSheet(
        f"QTableWidget {{ border: 1px solid {p['border']}; gridline-color: {p['border']}; "
        f"font-size: 13px; background: {p['bg_panel']}; color: {p['text']}; "
        f"alternate-background-color: {p.get('bg_panel_alt', p['bg_control'])}; }}"
        f"QTableWidget::item {{ padding: 4px 8px; border: none; }}"
    )

    # Monospace font for norm/gradation columns
    mono_font = table.font()
    mono_font.setStyleHint(QFont.StyleHint.Monospace)

    # Fill rows
    for r, param in enumerate(params):
        # Column 0: name + unit
        name_text = param.name
        if param.unit:
            name_text += f" ({param.unit})"
        name_item = QTableWidgetItem(name_text)
        name_item.setForeground(QColor(p["text"]))
        font = name_item.font()
        font.setBold(True)
        name_item.setFont(font)
        table.setItem(r, 0, name_item)

        # Column 1: norm male
        norm_m = self._format_norm_range(param.norm_male)
        norm_m_item = QTableWidgetItem(norm_m)
        norm_m_item.setFont(mono_font)
        norm_m_item.setForeground(QColor(p["accent_tab"]))
        table.setItem(r, 1, norm_m_item)

        # Column 2: norm female
        norm_f = self._format_norm_range(param.norm_female)
        norm_f_item = QTableWidgetItem(norm_f)
        norm_f_item.setFont(mono_font)
        norm_f_item.setForeground(QColor(p["accent_tab"]))
        table.setItem(r, 2, norm_f_item)

        # Gradation columns
        grad_map = {g.name: g for g in param.gradations}
        for g_idx, g_name in enumerate(grad_names):
            col = 3 + g_idx
            grad = grad_map.get(g_name)
            if grad:
                # Format range
                parts = []
                if grad.range_male:
                    parts.append(self._format_norm_range(grad.range_male))
                if grad.range_female:
                    parts.append(self._format_norm_range(grad.range_female))
                value = " / ".join(parts) if parts else "—"
            else:
                value = "—"

            item = QTableWidgetItem(value)
            item.setFont(mono_font)

            # Color code by gradation name
            colors = _gradation_color(g_name)
            if colors and value != "—":
                bg, text = colors
                item.setBackground(QColor(bg))
                item.setForeground(QColor(text))
            else:
                item.setForeground(QColor(p["text_dim"]))

            table.setItem(r, col, item)

    # Auto-resize rows to fit available height
    self._cards_layout.insertWidget(self._cards_layout.count() - 1, table)
    # Delayed row height adjustment after layout
    QTimer.singleShot(0, lambda: self._adjust_table_row_height(table, n_rows))
```

- [ ] **Step 3: Add `_adjust_table_row_height()` helper**

```python
def _adjust_table_row_height(self, table: QTableWidget, n_rows: int) -> None:
    """Adjust row heights so table fills available space without scroll."""
    if n_rows == 0:
        return
    available = table.viewport().height()
    if available < 10:
        return
    row_height = max(24, available // n_rows)
    table.verticalHeader().setDefaultSectionSize(row_height)
```

- [ ] **Step 4: Update `_refresh_table()` to use new unified method**

```python
def _refresh_table(self) -> None:
    self._clear_cards()
    if self._current_pathology is None:
        return
    self._render_parameter_table()
```

- [ ] **Step 5: Add `QTimer` import**

Add to imports at top of file:
```python
from PySide6.QtCore import QTimer
```

- [ ] **Step 6: Verify table rendering**

Run: `uv run sonoforge` — open Reference dialog:
- Parameters with gradations show color-coded columns
- Parameters without gradations show "—" in gradation columns
- Both norm columns always visible
- Table fills panel height without scrollbar

- [ ] **Step 7: Commit**

```bash
git add src/echo_personal_tool/presentation/structured_reference_widget.py
git commit -m "feat(ui): unified table with color-coded gradations and no-scroll"
```

---

### Task 6: Linter and type check

**Files:**
- No new files

- [ ] **Step 1: Run ruff check**

Run: `uv run ruff check src/echo_personal_tool/domain/services/reference_data_store.py src/echo_personal_tool/constructor/models/reference_model.py src/echo_personal_tool/presentation/structured_reference_widget.py`

- [ ] **Step 2: Fix any lint errors**

- [ ] **Step 3: Run ruff format**

Run: `uv run ruff format src/echo_personal_tool/domain/services/reference_data_store.py src/echo_personal_tool/constructor/models/reference_model.py src/echo_personal_tool/presentation/structured_reference_widget.py`

- [ ] **Step 4: Run all tests**

Run: `uv run pytest tests/ -v`
Expected: All PASS

- [ ] **Step 5: Commit if any formatting changes**

```bash
git add -u
git commit -m "chore: lint and format reference redesign files"
```

---

## Phase 3: Constructor

### Task 7: Add Excel-like context menu to ParameterTableEditor

**Files:**
- Modify: `src/echo_personal_tool/constructor/editors/parameter_table_editor.py`

**Interfaces:**
- Extends: `_context_menu()` with insert/delete row/col, merge/split actions
- Produces: `_insert_row_above()`, `_insert_row_below()`, `_insert_col_left()`, `_insert_col_right()`, `_merge_cells()`, `_split_cells()`

- [ ] **Step 1: Extend `_context_menu()` with new actions**

```python
def _context_menu(self, pos: Any) -> None:
    p = get_theme_palette()
    from PySide6.QtWidgets import QMenu

    menu = QMenu(self)
    menu.setStyleSheet(
        f"QMenu {{ color: {p['text']}; background: {p['bg_control']}; border: 1px solid {p['border']}; }}"
        f"QMenu::item:selected {{ background: {p['accent']}; }}"
    )

    # Row operations
    menu.addAction(tr("constructor.param.insert_row_above"), self._insert_row_above)
    menu.addAction(tr("constructor.param.insert_row_below"), self._insert_row_below)
    menu.addSeparator()

    # Column operations
    menu.addAction(tr("constructor.param.insert_col_left"), self._insert_col_left)
    menu.addAction(tr("constructor.param.insert_col_right"), self._insert_col_right)
    menu.addSeparator()

    # Delete
    menu.addAction(tr("constructor.param.delete_selected"), self.delete_selected)
    menu.addAction(tr("constructor.param.delete_column"), self._delete_column)
    menu.addSeparator()

    # Merge/Split
    menu.addAction(tr("constructor.param.merge_cells"), self._merge_cells)
    menu.addAction(tr("constructor.param.split_cells"), self._split_cells)
    menu.addSeparator()

    # Add new
    menu.addAction(tr("constructor.param.add_param"), self._add_parameter)
    menu.addAction(tr("constructor.param.add_column"), self._add_column)

    menu.exec(self._table.mapToGlobal(pos))
```

- [ ] **Step 2: Implement `_insert_row_above()` and `_insert_row_below()`**

```python
def _insert_row_above(self) -> None:
    row = self._table.currentRow()
    if row < 0:
        row = 0
    new_param = ParameterModel(id=f"param_{len(self._parameters) + 1}", name=tr("constructor.param.new_param"))
    self._parameters.insert(row, new_param)
    self._all_params.append(new_param)
    self._refresh_table()
    self.parameters_changed.emit()

def _insert_row_below(self) -> None:
    row = self._table.currentRow()
    if row < 0:
        row = len(self._parameters) - 1
    new_param = ParameterModel(id=f"param_{len(self._parameters) + 1}", name=tr("constructor.param.new_param"))
    self._parameters.insert(row + 1, new_param)
    self._all_params.append(new_param)
    self._refresh_table()
    self.parameters_changed.emit()
```

- [ ] **Step 3: Implement `_insert_col_left()` and `_insert_col_right()`**

```python
def _insert_col_left(self) -> None:
    col = self._table.currentColumn()
    if col < 0:
        col = 0
    from PySide6.QtWidgets import QInputDialog
    name, ok = QInputDialog.getText(
        self, tr("constructor.param.new_column_title"), tr("constructor.param.new_column_label")
    )
    if ok and name:
        slug = name.lower().replace(" ", "_")
        self._columns.insert(col, (slug, name))
        self._refresh_table()
        self.parameters_changed.emit()

def _insert_col_right(self) -> None:
    col = self._table.currentColumn()
    if col < 0:
        col = len(self._columns) - 1
    from PySide6.QtWidgets import QInputDialog
    name, ok = QInputDialog.getText(
        self, tr("constructor.param.new_column_title"), tr("constructor.param.new_column_label")
    )
    if ok and name:
        slug = name.lower().replace(" ", "_")
        self._columns.insert(col + 1, (slug, name))
        self._refresh_table()
        self.parameters_changed.emit()
```

- [ ] **Step 4: Implement `_merge_cells()` and `_split_cells()`**

```python
def _merge_cells(self) -> None:
    indexes = self._table.selectedIndexes()
    if len(indexes) < 2:
        return
    rows = sorted(set(idx.row() for idx in indexes))
    cols = sorted(set(idx.column() for idx in indexes))
    if len(rows) == 1 and len(cols) == 1:
        return
    # Merge: set span on top-left cell
    top, left = rows[0], cols[0]
    row_span = rows[-1] - top + 1
    col_span = cols[-1] - left + 1
    self._table.setSpan(top, left, row_span, col_span)
    # Combine text from all cells
    texts = []
    for r in rows:
        for c in cols:
            item = self._table.item(r, c)
            if item and item.text():
                texts.append(item.text())
    merged_item = self._table.item(top, left)
    if merged_item:
        merged_item.setText(" | ".join(texts))
    self.parameters_changed.emit()

def _split_cells(self) -> None:
    row = self._table.currentRow()
    col = self._table.currentColumn()
    if row < 0 or col < 0:
        return
    # Clear span (split back to 1x1)
    self._table.setSpan(row, col, 1, 1)
    self.parameters_changed.emit()
```

- [ ] **Step 5: Add toolbar buttons for insert/delete row/col**

In `_build_ui()`, after existing buttons, add:

```python
for text, slot in [
    (tr("constructor.param.insert_row_above"), self._insert_row_above),
    (tr("constructor.param.insert_row_below"), self._insert_row_below),
    (tr("constructor.param.insert_col_left"), self._insert_col_left),
    (tr("constructor.param.insert_col_right"), self._insert_col_right),
]:
    btn = QPushButton(text)
    btn.setFixedHeight(26)
    btn.setCursor(Qt.CursorShape.PointingHandCursor)
    btn.setStyleSheet(
        f"QPushButton {{ border: 1px solid {p['border']}; border-radius: 3px; "
        f"padding: 2px 8px; color: {p['text']}; background: {p['bg_panel']}; font-size: 11px; }}"
        f"QPushButton:hover {{ background: {p['bg_button_hover']}; }}"
    )
    btn.clicked.connect(slot)
    btn_row.addWidget(btn)
```

- [ ] **Step 6: Add i18n keys**

Add to the appropriate i18n file (check `infrastructure/i18n/` for the translation system):

```
constructor.param.insert_row_above = Insert row above
constructor.param.insert_row_below = Insert row below
constructor.param.insert_col_left = Insert column left
constructor.param.insert_col_right = Insert column right
constructor.param.merge_cells = Merge cells
constructor.param.split_cells = Split cells
```

- [ ] **Step 7: Verify constructor functionality**

Run: `uv run sonoforge` — open Constructor:
- Right-click on table shows full context menu
- Insert row above/below works
- Insert column left/right works
- Merge/split works
- Toolbar buttons work

- [ ] **Step 8: Commit**

```bash
git add src/echo_personal_tool/constructor/editors/parameter_table_editor.py
git commit -m "feat(constructor): add Excel-like context menu with insert/delete/merge/split"
```

---

### Task 8: Update constructor preview for gradations

**Files:**
- Modify: `src/echo_personal_tool/constructor/preview/reference_preview.py`

- [ ] **Step 1: Update HTML preview to show gradation data**

In `reference_preview.py`, update the parameter rendering to show gradations if present:

```python
# When rendering a parameter in the preview HTML:
if param.gradations:
    html += '<table class="gradations"><tr>'
    for g in param.gradations:
        html += f'<th>{g.name}</th>'
    html += '</tr><tr>'
    for g in param.gradations:
        parts = []
        if g.range_male:
            parts.append(f"М: {_fmt_range(g.range_male)}")
        if g.range_female:
            parts.append(f"Ж: {_fmt_range(g.range_female)}")
        html += f'<td>{" / ".join(parts) if parts else "—"}</td>'
    html += '</tr></table>'
```

- [ ] **Step 2: Verify preview shows gradations**

Run: `uv run sonoforge` — open Constructor, select a parameter with gradations, verify preview shows gradation table.

- [ ] **Step 3: Commit**

```bash
git add src/echo_personal_tool/constructor/preview/reference_preview.py
git commit -m "feat(constructor): update preview to show parameter gradations"
```

---

### Task 9: Final verification and cleanup

- [ ] **Step 1: Run all tests**

Run: `uv run pytest tests/ -v`
Expected: All PASS

- [ ] **Step 2: Run linter**

Run: `uv run ruff check src/ tests/`

- [ ] **Step 3: Run formatter**

Run: `uv run ruff format src/ tests/`

- [ ] **Step 4: Manual smoke test**

1. Open Reference dialog — verify table with gradations, color coding, no scrollbar
2. Open Constructor — verify Excel-like editing works
3. Add a new parameter with gradations in Constructor — verify save/load
4. Search for a parameter — verify results show both norms

- [ ] **Step 5: Final commit**

```bash
git add -u
git commit -m "chore: final cleanup for reference redesign"
```
