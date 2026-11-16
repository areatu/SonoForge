- `fix(comparison)`: #562 — идентичность пациента в сравнении подтверждается по `PatientID` + `IssuerOfPatientID`, а не по одной фамилии; без пары идентификаторов статус остаётся «не подтверждено».

**Что изменено**

- `InstanceMetadata` читает `PatientID`, `IssuerOfPatientID`, `PatientBirthDate` и `PatientSex` из заголовка. Это RAM-поля: `repr=False`, как и фамилия; в отчёты, историю и диагностику они не попадают.
- `StudyIdentity` хранит эти четыре поля, `application.study_comparison` собирает только однозначные значения по всем instance исследования. Противоречивые значения не угадываются и не выбираются «первым»: поле становится пустым.
- `ComparisonIdentity.patient_match` сравнивает `PatientID` и issuer как case-sensitive идентификаторы (пробелы нормализуются). `SAME` возможен только при совпадающих непустых ID и issuer и отсутствии противоречий в фамилии, дате рождения и поле; разные ID внутри одного issuer дают `DIFFERENT`; неполные, отсутствующие или несопоставимые идентификаторы — `UNVERIFIED`.
- Конфликт даты рождения, пола или фамилии доказывает `DIFFERENT` даже без ID. Совпадение фамилии само по себе больше никогда не даёт `SAME`.
- Локали RU/EN: статусы «подтверждён по PatientID и issuer», «данные различаются», «не подтверждено: нужен одинаковый PatientID с issuer»; справка RU/EN обновлена.

**Почему так**

Одинаковая фамилия — распространённое совпадение, а не доказательство. `PatientID` уникален только внутри issuer, поэтому один ID без issuer не считается доказательством; case-sensitive сравнение не склеивает разные ID из-за регистра. Дополнительные поля используются только как доказательство несовпадения, чтобы не выдавать вероятностное сходство за подтверждённую идентичность.

**Прогоны**

- `tests/unit/test_study_comparison.py` — 20 тестов: совпадение ID+issuer, фамилия без ID, ID без issuer, разные issuer, конфликт ID, даты рождения, пола, case-sensitive ID, агрегация по исследованию, отсутствие ID в repr.
- `tests/unit/test_dicom_metadata_mapper.py` — тест чтения PatientID/issuer/даты/пола и отсутствия их в repr.
- `tests/unit/test_study_comparison_dialog.py`, `test_comparison_coordinator.py`, `test_study_comparison_action.py` — обновлены под новый статус; все зелёные.
- `ruff check`/`format`, `mypy` (416 файлов), ратчеты class-size/function-length/private-access/type-ignore/untranslated/layer-directions/doc-links — проходят.
