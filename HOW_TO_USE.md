# استخدام G-MES

المحرك المعتمد الوحيد هو الملفات المسطحة في جذر المشروع، مثل
`gmes_core.py` و`gmes_login.py` و`gmes_report.py`. حزمة `src/gmes` القديمة
حُذفت ولا يجوز تشغيلها أو إعادتها؛ توجد فقط في تاريخ Git عند `59eb838`.

## المداخل المعتمدة

`GMES_Workflow.bat` هو المدخل الأساسي على Windows:

```text
بدون معاملات  -> python run_gmes_workflow.py
مع معاملات     -> python gmes_report.py run %*
```

لتخزين بيانات الدخول في مخزن DPAPI الخاص بالمحرك المعتمد:

```powershell
python gmes_credentials.py set
```

لا تنقل أو تحذف أو تفحص ملفات بيانات الدخول. المسار النشط هو
`%LOCALAPPDATA%\\GMES_Automation\\credentials.dat`. المسار
`%LOCALAPPDATA%\\GMES\\credentials.dat` يخص الحزمة المحذوفة تاريخياً ويبقى
محمياً أيضاً؛ لا توجد هجرة أو دمج مصرح به.

## تشغيل تقرير

```powershell
.\\GMES_Workflow.bat
python gmes_report.py run P1112UM00 --division VD --from 20260909 --to 20260909 --verify planYmd
python gmes_open_screen.py --find "production"
python gmes_data.py forms
```

اقرأ `GMES_SKILL.md` قبل تغيير الأتمتة. لا تشغّل جلسة G-MES حية أو تصديراً
أو أي إجراء يغيّر بيانات العمل دون تفويض صريح.
