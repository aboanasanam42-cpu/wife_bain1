# Binance Spot Cloud Trading Bot — wife_bain1

بوت تداول فوري لـ Binance Spot باستخدام Python وCCXT، مع دورة تنفيذ على Vercel.

## ما تم تصحيحه
- إزالة إعادة توجيه كل مسارات الموقع إلى `/api/trade`؛ التداول أصبح على مساره الطبيعي فقط.
- إضافة حماية `TRADE_TRIGGER_TOKEN` لطلبات التداول.
- إضافة `LIVE_TRADING=false` كافتراضي آمن؛ عند الاختبار لا تُرسل أوامر حقيقية.
- عند الجاهزية للتداول الحقيقي يتم ضبط `LIVE_TRADING=true` في Vercel فقط.
- ضبط `maxDuration` لدالة Vercel.
- تحديث نموذج متغيرات البيئة.

## متغيرات Vercel
`BINANCE_API_KEY`, `BINANCE_API_SECRET`, `TRADE_TRIGGER_TOKEN`, `LIVE_TRADING` وبقية إعدادات الاستراتيجية الموجودة في `.env.example`.

لا تضع مفاتيح Binance أو السر داخل GitHub.

## التشغيل الدوري
Vercel Serverless ليس عملية Python دائمة، لذلك `main.py` يبقى للتشغيل على عامل/خادم طويل التشغيل. أما `api/trade.py` فهي دورة واحدة عند استدعائها.

على خطة Vercel Hobby لا تعتمد على Cron كل 5 دقائق؛ استخدم مشغلاً خارجياً/‏GitHub Actions إذا كنت تحتاج دورية أعلى. خطة Vercel الحالية تميز بين دقة Cron حسب الخطة.

## تحذير
لا توجد استراتيجية تضمن الربح. اختبر أولاً مع `LIVE_TRADING=false` وحساب/مفتاح API بصلاحيات Spot المطلوبة فقط، ثم فعّل التداول الحقيقي بعد التأكد من السجلات والإعدادات.
