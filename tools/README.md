# Tools

> [Русская версия](README_RU.md)

Development and CI helper tools (not part of the application).

| File | Description |
|------|-------------|
| `ste_fixture_export.py` | Export compact fixtures from real STE clips into `tests/fixtures/for_pero/` (frames as JPEG + de-identified headers). Run by the [`ste-fixtures.yml`](../.github/workflows/ste-fixtures.yml) workflow |
| `migrate_for_pero.sh` | One-off migration of the `data/dicom/For_pero` clips from the public repository to the private `areatu/Sonoforge_data` (see [`../data/README.md`](../data/README.md)) |
| `qtstub/mkstub.py` | Generate GL/EGL/dbus library stubs to run PySide6 in "bare" containers without a GPU (prebuilt libraries are local, `qtstub/lib/` is in `.gitignore`) |
