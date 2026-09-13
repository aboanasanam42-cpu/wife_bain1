# Binance Spot 24/7 Cloud Trading Bot (BTC/USDT)

بوت تداول فوري سحابي يعمل على مدار الساعة 24/7 على منصة **Binance Spot** لزوج **BTC/USDT** ومجهز للرفع المباشر إلى **GitHub** والاستضافة الفورية على منصة **Bot-Hosting.net**.

---

## 🌟 المميزات والمواصفات البرمجية

1. **الربط الآمن عبر CCXT:**
   - تفعيل وضع التداول الفوري حصراً `options: {'defaultType': 'spot'}`.
   - تفعيل `enableRateLimit: True` و `adjustForTimeDifference: True` لمزامنة الوقت بدقة.
   - قراءة المفاتيح السرية إجبارياً من متغيرات البيئة (`os.environ`) دون أي تخزين نصي في الكود.

2. **إدارة رأس المال والمخاطر الصارمة:**
   - حد أقصى **صفقتان متزامنتان (Max 2 Positions)**.
   - فحص الحد الأدنى الفعلي لصفقات بينانس الفورية (`min_notional` 5 USDT) تلقائياً عبر `exchange.load_markets()`.
   - جني الأرباح التلقائي: بيع فوري بالسوق عند ارتفاع السعر **+1.5%**.
   - وقف الخسارة الصارم: بيع فوري بالسوق عند هبوط السعر **-1.0%**.
   - حفظ واسترجاع الصفقات المفتوحة في `positions.json` عند التشغيل المستمر. أما Vercel Serverless فيستخدم `/tmp` فقط، لذلك لا يُعتبر مخزناً دائماً للحالة.

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
   - `BINANCE_API_KEY`
   - `BINANCE_API_SECRET`
   - `SYMBOL` (افتراضياً: BTC/USDT)
   - `TARGET_ORDER_USD` (افتراضياً: 5.5)
   - `MAX_POSITIONS` (افتراضياً: 2)
   - `TAKE_PROFIT_PCT` (افتراضياً: 1.5)
   - `STOP_LOSS_PCT` (افتراضياً: 1.0)
3. بعد النشر، يمكنك استدعاء الدالة عبر الرابط المباشر `https://your-project.vercel.app/` أو ضبط Vercel Cron لتشغيلها تلقائياً كل دقيقة أو 5 دقائق!

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
