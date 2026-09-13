# Binance Spot 24/7 Cloud Trading Bot (BTC/USDT)

بوت تداول فوري سحابي يعمل على مدار الساعة 24/7 على منصة **Binance Spot** لزوج **BTC/USDT** ومجهز للرفع المباشر إلى **GitHub** والاستضافة الفورية على منصة **Bot-Hosting.net**.

---

## 🌟 المميزات والمواصفات البرمجية

1. **الربط الآمن عبر CCXT:**
   - تفعيل وضع التداول الفوري حصراً `options: {'defaultType': 'spot'}`.
   - تفعيل `enableRateLimit: True` و `adjustForTimeDifference: True` لمزامنة الوقت بدقة.
   - قراءة المفاتيح السرية إجبارياً من متغيرات البيئة (`os.environ`) دون أي تخزين نصي في الكود.

2. **إدارة رأس المال والمخاطر وميكانيكية تتبع السعر اللحظي:**
   - **تتبع السعر اللحظي (Trailing Take Profit):**
     - تتبع القمة اللحظية (`highest_price`) في كل دورة تحديث.
     - تفعيل التتبع التلقائي عند تحقيق ربح مبدئي (+1.0% افتراضياً `TRAILING_ACTIVATION_PCT`).
     - إغلاق الصفقة وحجز أقصى أرباح إذا ارتد السعر بمقدار (-0.35% افتراضياً `TRAILING_CALLBACK_PCT`) من أعلى قمة مسجلة.
     - هدف جني أرباح سريع مباشر (`Hard Take Profit`) بنسبة **+2.0%** لاقتناص القفزات اللحظية العنيفة.
   - **معيار منع تجمد العملة (Anti-Stagnation Criteria):**
     - **أثناء الاحتفاظ بالصفقة:** إذا مرت مدة زمنية محددة (`MAX_HOLD_TIME_SEC` ساعتان افتراضياً) وظل السعر راكداً في نطاق ضيق دون تحقيق الهدف، يتم تسييل الصفقة تلقائياً لتحرير رأس المال ومنع حبس السيولة في عملة ميتة.
     - **قبل فتح الصفقة:** فحص الفارق السعري (`MAX_SPREAD_PCT` 0.15%) وفحص تقلب الشموع اللحظية 15 دقيقة (`MIN_VOLATILITY_PCT` 0.15%)؛ إذا كانت العملة متجمدة دون فوليوم أو حركة حية يتم الامتناع عن الشراء فوراً.
   - **اقتناص الحركة السريعة اللحظية المربحة (Momentum Scalping):**
     - التحقق اللحظي عبر شموع 1m والتأكد من وجود زخم صاعد (السعر متماسك أو أعلى من متوسط الحركة السريع SMA-5 ومؤشر RSI في نطاق ارتداد صحي).
   - **وقف الخسارة الصارم (Stop Loss):** بيع فوري بالسوق عند هبوط السعر **-1.0%**.
   - **التحكم بالصفقات المتزامنة:** حد أقصى **صفقتان متزامنتان (Max 2 Positions)**.

3. **الاستقرار السحابي 24/7:**
   - حلقة تشغيل متواصلة `while True` عند تشغيل `main.py` على VPS/استضافة عملية مستمرة. أما Vercel Serverless فيعمل كدورة منفصلة ويُستدعى عبر Cron كل 5 دقائق.
   - معالجة شاملة لكافة استثناءات الشبكة (`RateLimitExceeded`, `NetworkError`, `RequestTimeout`, `InsufficientFunds`).
   - سجل مباشر مفصل (Console Logs) يوضح الأرصدة، السعر اللحظي، وحالة الصفقات المفتوحة ونسبة أرباحها.

---

## 📁 هيكلية الملفات الأساسية

- `api/trade.py`: دالة Vercel Serverless Function لمعالجة دورة تداول فورية وإرجاع JSON.
- `vercel.json`: تكوين توجيه الطلبات إلى `/api/trade` تلقائياً.
- `requirements.txt`: الحزم والمكتبات المطلوبة (`ccxt`, `python-dotenv`).
- `main.py`: كود البوت التنفيذي المتواصل (لحلقة 24/7 على Bot-Hosting أو الخوادم الخاصة).
- `.env.example`: نموذج للمتغيرات البيئية المطلوبة.
- `.gitignore`: لمنع رفع المفاتيح وملف الصفقات والملفات المؤقتة إلى GitHub.

---

## ⚡ التشغيل على Vercel (Serverless Function)

1. اربط مستودع GitHub `aboanasanam42-cpu/wife_bain1` بمنصة [Vercel](https://vercel.com).
2. أضف متغيرات البيئة في إعدادات المشروع (Settings > Environment Variables):
   - `BINANCE_API_KEY`: مفتاح API من بينانس.
   - `BINANCE_API_SECRET`: المفتاح السري من بينانس.
   - `SYMBOL`: زوج العملات (افتراضياً: `BTC/USDT`).
   - `TARGET_ORDER_USD`: قيمة الصفقة بالدولار (افتراضياً: `5.5`).
   - `MAX_POSITIONS`: الحد الأقصى للصفقات المتزامنة (افتراضياً: `2`).
   - `TAKE_PROFIT_PCT`: جني الأرباح السريع المباشر (افتراضياً: `2.0` أي +2%).
   - `STOP_LOSS_PCT`: وقف الخسارة الصارم (افتراضياً: `1.0` أي -1%).
   - `TRAILING_STOP_ENABLED`: تفعيل تتبع السعر اللحظي (افتراضياً: `true`).
   - `TRAILING_ACTIVATION_PCT`: نسبة الربح لتفعيل التتبع (افتراضياً: `1.0` أي +1%).
   - `TRAILING_CALLBACK_PCT`: نسبة الارتداد من القمة للبيع وجني الأرباح (افتراضياً: `0.35`%).
   - `MAX_HOLD_TIME_SEC`: معيار منع تجمد العملة بالثواني (افتراضياً: `7200` أي ساعتان).
   - `MAX_SPREAD_PCT`: أقصى فارق سبريد مسموح به لمنع الشراء في عملة متجمدة السيولة (افتراضياً: `0.15`%).
   - `MIN_VOLATILITY_PCT`: أدنى تقلب مطلوب لآخر 15 دقيقة للتأكد من وجود حركة حية (افتراضياً: `0.15`%).
3. بعد النشر، يمكنك استدعاء الدالة عبر الرابط المباشر `https://your-project.vercel.app/` أو عبر أي خدمة Cron خارجية مجانية (مثل cron-job.org أو EasyCron أو GitHub Actions) لتشغيلها تلقائياً كل دقيقة أو 5 دقائق!

---

## 🚀 أوامر Git السريعة لرفع المشروع إلى مستودعك (aboanasanam42-cpu/wife_bain1)

افتح الطرفية (Terminal) في مجلد المشروع ونفذ الأوامر التالية مباشرة:

```bash
# 1. تهيئة مستودع Git محلي
git init

# 2. إضافة جميع الملفات المطلوبة وملفات Vercel و GitHub Actions
git add requirements.txt vercel.json api/trade.py main.py README.md .env.example .gitignore .github/

# 3. حفظ التغييرات
git commit -m "feat: configure vercel serverless function with ccxt binance spot bot"

# 4. تغيير اسم الفرع الرئيسي إلى main
git branch -M main

# 5. ربط المستودع بمستودعك على GitHub
git remote add origin https://github.com/aboanasanam42-cpu/wife_bain1.git

# 6. رفع الكود مباشرة إلى مستودعك
git push -u origin main
```

---

## 🌐 خطوات الاستضافة على منصة Bot-Hosting.net

1. سجل الدخول إلى [Bot-Hosting.net](https://bot-hosting.net/).
2. اضغط على خيار **"Deploy a new bot"**.
3. اختر نوع البوت: **Python**.
4. اختر استيراد الكود عبر **GitHub Repository** واختر المستودع الذي رفعته للتو.
5. في قسم **Environment Variables (المتغيرات البيئية)**، أضف المتغيرات التالية:
   - `BINANCE_API_KEY`: مفتاح الـ API الخاص بحسابك في بينانس.
   - `BINANCE_API_SECRET`: المفتاح السري الخاص بالـ API.
   - `SYMBOL`: `BTC/USDT` (اختياري، مبرمج افتراضياً).
   - `TARGET_ORDER_USD`: `5.5` (اختياري).
   - `TAKE_PROFIT_PCT`: `1.5` (اختياري).
   - `STOP_LOSS_PCT`: `1.0` (اختياري).
6. تأكد من أن أمر التشغيل (Startup Command) هو:
   ```bash
   python main.py
   ```
7. اضغط **Deploy / Start** لمشاهدة سجلات البوت الحية وهو يعمل 24/7 بنجاح!

## ملاحظات مهمة بعد التدقيق

- Vercel Serverless لا يشغّل `while True` بشكل مستمر؛ تم إضافة Cron كل 5 دقائق إلى `vercel.json` لدورات التنفيذ. للتداول المستمر بفواصل 10 ثوانٍ استخدم `python main.py` على VPS/استضافة عملية طويلة التشغيل.
- تم تحديث الرصيد بعد عمليات TP/SL قبل أي شراء جديد لتجنب الاعتماد على رصيد قديم.
- تمت إضافة فحص CI لتثبيت الاعتمادات وتجميع ملفات Python قبل الدمج.
- لا تضع مفاتيح Binance داخل GitHub أو داخل `.env.example`; استخدم Environment Variables في منصة الاستضافة.
