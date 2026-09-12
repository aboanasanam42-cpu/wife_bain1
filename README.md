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
   - حفظ واسترجاع الصفقات المفتوحة في ملف محلي `positions.json` لضمان عدم ضياع الصفقات عند إعادة تشغيل السيرفر.

3. **الاستقرار السحابي 24/7:**
   - حلقة تشغيل متواصلة `while True` مع فترات انتظار مدروسة لمنع حظر الـ IP.
   - معالجة شاملة لكافة استثناءات الشبكة (`RateLimitExceeded`, `NetworkError`, `RequestTimeout`, `InsufficientFunds`).
   - سجل مباشر مفصل (Console Logs) يوضح الأرصدة، السعر اللحظي، وحالة الصفقات المفتوحة ونسبة أرباحها.

---

## 📁 هيكلية الملفات الأساسية

- `main.py`: كود البوت التنفيذي المتكامل.
- `requirements.txt`: الحزم والمكتبات المطلوبة (`ccxt`, `python-dotenv`).
- `.env.example`: نموذج للمتغيرات البيئية المطلوبة.
- `.gitignore`: لمنع رفع المفاتيح وملف الصفقات والملفات المؤقتة إلى GitHub.

---

## 🚀 أوامر Git السريعة لرفع المشروع إلى مستودعك (aboanasanam42-cpu/wife_bain1)

افتح الطرفية (Terminal) في مجلد المشروع ونفذ الأوامر التالية مباشرة:

```bash
# 1. تهيئة مستودع Git محلي
git init

# 2. إضافة جميع الملفات المطلوبة وملفات GitHub Actions
git add main.py requirements.txt .env.example .gitignore README.md .github/

# 3. حفظ التغييرات الأولى
git commit -m "Initial commit: Binance Spot 24/7 Cloud Trading Bot"

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
