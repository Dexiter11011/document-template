# Reference documents

- `espd.docx` — оболочка ЕСПД (титул + `%MAINTEXT%` + ЛРИ) и база стилей для MD→OOXML.
  База: [gostdown](https://gitlab.iaaras.ru/iaaras/gostdown) `demo-template-espd.docx`.
- `espd.styles.json` — кэш стилей/defaults (генерируется `template_profile.py extract`).

Плейсхолдеры в шаблоне (подставляются из `doc.yaml` при сборке):

| Плейсхолдер | Назначение |
| --- | --- |
| `{ProductName}` | Наименование изделия |
| `{Version}` | Версия («Версия …» под наименованием) |
| `{DocType}` | Вид документа (титул) |
| `{DecimalNumber}` | Обозначение документа (+ ячейка «Инв. № подл.») |
| `{Year}` | Год (если не задан — текущий) |
| `%MAINTEXT%` | Точка вставки тела Markdown |
| NUMPAGES (поле Word) | Число листов (вместо `%NPAGES%`) |

Первичная подготовка шаблона (идемпотентно):

```bash
python3 scripts/patch_espd_template.py
```
