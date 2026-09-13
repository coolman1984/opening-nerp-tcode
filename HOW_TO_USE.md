# استخدام G-MES

المسار المدعوم هو محرك واحد داخل `src/gmes`. شغّل `GMES_Workflow.bat` من
دون أوامر لأسئلة موجهة، أو شغّل `gmes.bat` للأوامر المباشرة. الاسم القديم
`run_gmes_workflow.py` يصل إلى نفس المحرك؛ لا توجد نسخة تنفيذ ثانية.

## قبل أول تشغيل

```powershell
python -m pip install -r requirements.txt
.\gmes.bat credentials set
.\gmes.bat doctor
```

الأمر `credentials set` يحفظ بيانات الدخول محليًا باستخدام Windows DPAPI.
الأمر `doctor` فحص قراءة فقط ولا يغيّر الملفات أو المتصفح.

## تشغيل تقرير

للواجهة السهلة اضغط مرتين على:

```powershell
.\GMES_Workflow.bat
```

أو استخدم الأمر المباشر نفسه عند الحاجة:

```powershell
.\GMES_Workflow.bat run P1112UM00 --division VD --from 20260909 --to 20260909 --verify planYmd
```

- استخدم `--export xlsx` أو `csv` أو `both` أو `none`.
- استخدم `--output-dir "D:\Reports"` لاختيار مكان الحفظ.
- استخدم `--dry-run` لضبط الشاشة فقط من دون تنفيذ الاستعلام.
- عند تحديد تاريخ، `--verify` إلزامي حتى لا يُصدَّر تقرير قديم أو بتاريخ مختلف.
- إذا وُجد أكثر من جدول نتائج أو أكثر من شجرة للقسم، حدّد `--grid` أو `--tree` بدل التخمين.

مثال لقراءة البيانات دون تصدير:

```powershell
.\gmes.bat data forms
.\gmes.bat data read P1112WM00 dsMasterProdPlan --limit 20
```

## ما الذي يحدث عند الخطأ

البرنامج يتوقف عند أي عدم يقين في الشاشة أو المرشحات أو التاريخ أو التصدير.
لا يشغّل التقرير التالي بعد فشل تقرير سابق. تُحفظ السجلات ولقطات الفشل تحت:

```text
%LOCALAPPDATA%\GMES\
```

لا يغلق البرنامج متصفح Chrome الشخصي؛ يستعمل نسخة CDP منفصلة من ملف التعريف.
