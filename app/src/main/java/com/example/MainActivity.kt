package com.example

import android.content.ClipData
import android.content.ClipboardManager
import android.content.Context
import android.os.Bundle
import android.widget.Toast
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import androidx.compose.foundation.background
import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.*
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.example.ui.theme.MyApplicationTheme

class MainActivity : ComponentActivity() {
  override fun onCreate(savedInstanceState: Bundle?) {
    super.onCreate(savedInstanceState)
    enableEdgeToEdge()
    setContent {
      MyApplicationTheme {
        Scaffold(
          modifier = Modifier.fillMaxSize(),
          topBar = {
            BotTopAppBar()
          }
        ) { innerPadding ->
          BotDashboardScreen(modifier = Modifier.padding(innerPadding))
        }
      }
    }
  }
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun BotTopAppBar() {
  TopAppBar(
    title = {
      Row(verticalAlignment = Alignment.CenterVertically) {
        Icon(
          imageVector = Icons.Default.CloudQueue,
          contentDescription = "Cloud Bot",
          tint = MaterialTheme.colorScheme.primary,
          modifier = Modifier.size(28.dp)
        )
        Spacer(modifier = Modifier.width(10.dp))
        Column {
          Text(
            text = "Binance Spot Bot",
            style = MaterialTheme.typography.titleMedium,
            fontWeight = FontWeight.Bold
          )
          Text(
            text = "BTC/USDT • 24/7 Cloud Trading",
            style = MaterialTheme.typography.bodySmall,
            color = MaterialTheme.colorScheme.onSurfaceVariant
          )
        }
      }
    },
    colors = TopAppBarDefaults.topAppBarColors(
      containerColor = MaterialTheme.colorScheme.surfaceContainer
    )
  )
}

@Composable
fun BotDashboardScreen(modifier: Modifier = Modifier) {
  var selectedTab by remember { mutableIntStateOf(0) }
  val tabs = listOf("نظرة عامة والمراقبة", "ملفات المشروع", "طريقة الرفع والاستضافة")

  Column(
    modifier = modifier
      .fillMaxSize()
      .background(MaterialTheme.colorScheme.background)
  ) {
    TabRow(
      selectedTabIndex = selectedTab,
      containerColor = MaterialTheme.colorScheme.surfaceContainer
    ) {
      tabs.forEachIndexed { index, title ->
        Tab(
          selected = selectedTab == index,
          onClick = { selectedTab = index },
          text = {
            Text(
              text = title,
              fontWeight = if (selectedTab == index) FontWeight.Bold else FontWeight.Normal,
              fontSize = 13.sp
            )
          },
          modifier = Modifier.testTag("tab_$index")
        )
      }
    }

    Box(
      modifier = Modifier
        .fillMaxSize()
        .padding(16.dp)
    ) {
      when (selectedTab) {
        0 -> OverviewTab()
        1 -> FilesTab()
        2 -> DeploymentTab()
      }
    }
  }
}

@Composable
fun OverviewTab() {
  val scrollState = rememberScrollState()

  Column(
    modifier = Modifier
      .fillMaxSize()
      .verticalScroll(scrollState)
  ) {
    // Status Banner
    Card(
      colors = CardDefaults.cardColors(
        containerColor = MaterialTheme.colorScheme.primaryContainer
      ),
      shape = RoundedCornerShape(16.dp),
      modifier = Modifier.fillMaxWidth()
    ) {
      Row(
        modifier = Modifier.padding(16.dp),
        verticalAlignment = Alignment.CenterVertically
      ) {
        Icon(
          imageVector = Icons.Default.CheckCircle,
          contentDescription = "Active Status",
          tint = MaterialTheme.colorScheme.primary,
          modifier = Modifier.size(36.dp)
        )
        Spacer(modifier = Modifier.width(14.dp))
        Column {
          Text(
            text = "جاهز للتشغيل السحابي 24/7",
            fontWeight = FontWeight.Bold,
            style = MaterialTheme.typography.titleSmall,
            color = MaterialTheme.colorScheme.onPrimaryContainer
          )
          Text(
            text = "تم تجهيز main.py و requirements.txt و .env.example للرفع المباشر",
            style = MaterialTheme.typography.bodySmall,
            color = MaterialTheme.colorScheme.onPrimaryContainer.copy(alpha = 0.85f)
          )
        }
      }
    }

    Spacer(modifier = Modifier.height(16.dp))

    // Parameters Grid
    Text(
      text = "المحددات الفنية وإدارة المخاطر",
      fontWeight = FontWeight.Bold,
      style = MaterialTheme.typography.titleMedium
    )
    Spacer(modifier = Modifier.height(8.dp))

    Row(modifier = Modifier.fillMaxWidth()) {
      MetricCard(
        title = "السوق والزوج",
        value = "BTC/USDT",
        sub = "Binance Spot حصراً",
        modifier = Modifier.weight(1f)
      )
      Spacer(modifier = Modifier.width(8.dp))
      MetricCard(
        title = "أقصى صفقات متزامنة",
        value = "2 صفقات فقط",
        sub = "Max 2 Concurrent",
        modifier = Modifier.weight(1f)
      )
    }

    Spacer(modifier = Modifier.height(8.dp))

    Row(modifier = Modifier.fillMaxWidth()) {
      MetricCard(
        title = "جني الأرباح (TP)",
        value = "+1.5%",
        sub = "أمر بيع فوري بالسوق",
        valueColor = Color(0xFF2E7D32),
        modifier = Modifier.weight(1f)
      )
      Spacer(modifier = Modifier.width(8.dp))
      MetricCard(
        title = "وقف الخسارة (SL)",
        value = "-1.0%",
        sub = "حماية فورية من الهبوط",
        valueColor = Color(0xFFC62828),
        modifier = Modifier.weight(1f)
      )
    }

    Spacer(modifier = Modifier.height(8.dp))

    Row(modifier = Modifier.fillMaxWidth()) {
      MetricCard(
        title = "فحص Min Notional",
        value = ">= 5 USDT تلقائياً",
        sub = "عبر load_markets() لمنع الرفض",
        modifier = Modifier.weight(1f)
      )
      Spacer(modifier = Modifier.width(8.dp))
      MetricCard(
        title = "الأمان المطبق",
        value = "متغيرات البيئة",
        sub = "os.environ بدون مفاتيح مكشوفة",
        modifier = Modifier.weight(1f)
      )
    }

    Spacer(modifier = Modifier.height(20.dp))

    // Console logs preview
    Text(
      text = "شكل مخرجات السجل المباشر (Console Logs)",
      fontWeight = FontWeight.Bold,
      style = MaterialTheme.typography.titleMedium
    )
    Spacer(modifier = Modifier.height(8.dp))

    Card(
      colors = CardDefaults.cardColors(
        containerColor = Color(0xFF1E1E1E)
      ),
      shape = RoundedCornerShape(12.dp),
      modifier = Modifier.fillMaxWidth()
    ) {
      Column(modifier = Modifier.padding(14.dp)) {
        Text(
          text = """[2026-09-12 16:30:00] [INFO] Binance Spot Bot Active
[مراقبة لحظية] السعر الفوري لـ BTC/USDT: $64,280.50
الرصيد: 54.20 USDT | 0.000150 BTC (~$63.84)
الصفقات النشطة حالياً: 1 / 2
  └─ صفقة #1 | سعر الدخول: $63,400.00 | الكمية: 0.000085 BTC | الربح/الخسارة: +1.38%
[INFO] في انتظار الوصول لهدف جني الأرباح (+1.50%)...
""",
          fontFamily = FontFamily.Monospace,
          fontSize = 11.sp,
          color = Color(0xFF81C784),
          lineHeight = 16.sp
        )
      }
    }
  }
}

@Composable
fun MetricCard(
  title: String,
  value: String,
  sub: String,
  modifier: Modifier = Modifier,
  valueColor: Color = MaterialTheme.colorScheme.onSurface
) {
  Card(
    modifier = modifier,
    shape = RoundedCornerShape(12.dp),
    colors = CardDefaults.cardColors(
      containerColor = MaterialTheme.colorScheme.surfaceVariant
    )
  ) {
    Column(modifier = Modifier.padding(12.dp)) {
      Text(
        text = title,
        style = MaterialTheme.typography.labelSmall,
        color = MaterialTheme.colorScheme.onSurfaceVariant
      )
      Spacer(modifier = Modifier.height(4.dp))
      Text(
        text = value,
        style = MaterialTheme.typography.titleSmall,
        fontWeight = FontWeight.Bold,
        color = valueColor
      )
      Spacer(modifier = Modifier.height(2.dp))
      Text(
        text = sub,
        style = MaterialTheme.typography.bodySmall,
        fontSize = 10.sp,
        color = MaterialTheme.colorScheme.onSurfaceVariant.copy(alpha = 0.8f)
      )
    }
  }
}

@Composable
fun FilesTab() {
  val context = LocalContext.current
  val scrollState = rememberScrollState()

  Column(
    modifier = Modifier
      .fillMaxSize()
      .verticalScroll(scrollState)
  ) {
    Text(
      text = "الملفات التي تم توليدها بالكامل في المشروع",
      fontWeight = FontWeight.Bold,
      style = MaterialTheme.typography.titleMedium
    )
    Text(
      text = "تم إنشاء هذه الملفات وجاهزة للرفع والتنفيذ المباشر:",
      style = MaterialTheme.typography.bodySmall,
      color = MaterialTheme.colorScheme.onSurfaceVariant
    )

    Spacer(modifier = Modifier.height(14.dp))

    FileItemCard(
      fileName = "main.py",
      description = "الكود التنفيذي الكامل للبوت في سوق Binance Spot مع مكتبة ccxt، إدارة المخاطر، وفحص min_notional و TP/SL و try/except الشاملة.",
      onCopy = {
        copyToClipboard(context, "main.py path", "تم إنشاء /main.py بنجاح داخل المشروع!")
      }
    )

    Spacer(modifier = Modifier.height(10.dp))

    FileItemCard(
      fileName = "requirements.txt",
      description = "مكتبات التشغيل المطلوبة لمنصة Bot-Hosting.net:\nccxt>=4.2.0\npython-dotenv>=1.0.0",
      onCopy = {
        copyToClipboard(context, "requirements.txt", "ccxt>=4.2.0\npython-dotenv>=1.0.0")
      }
    )

    Spacer(modifier = Modifier.height(10.dp))

    FileItemCard(
      fileName = ".env.example",
      description = "أسماء المتغيرات البيئية الإجبارية:\nBINANCE_API_KEY=\nBINANCE_API_SECRET=\nSYMBOL=BTC/USDT\nMAX_POSITIONS=2\nTAKE_PROFIT_PCT=1.5\nSTOP_LOSS_PCT=1.0",
      onCopy = {
        copyToClipboard(context, ".env.example", "BINANCE_API_KEY=\nBINANCE_API_SECRET=\nSYMBOL=BTC/USDT\nMAX_POSITIONS=2\nTAKE_PROFIT_PCT=1.5\nSTOP_LOSS_PCT=1.0")
      }
    )

    Spacer(modifier = Modifier.height(10.dp))

    FileItemCard(
      fileName = "README.md",
      description = "دليل التوثيق والتشغيل الكامل وخطوات الاستضافة على Bot-Hosting.net وأوامر Git السريعة.",
      onCopy = {
        copyToClipboard(context, "README.md", "README.md جاهز في المجلد الرئيسي")
      }
    )
  }
}

@Composable
fun FileItemCard(
  fileName: String,
  description: String,
  onCopy: () -> Unit
) {
  Card(
    shape = RoundedCornerShape(12.dp),
    colors = CardDefaults.cardColors(
      containerColor = MaterialTheme.colorScheme.surfaceVariant
    ),
    modifier = Modifier.fillMaxWidth()
  ) {
    Column(modifier = Modifier.padding(14.dp)) {
      Row(
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.SpaceBetween,
        modifier = Modifier.fillMaxWidth()
      ) {
        Row(verticalAlignment = Alignment.CenterVertically) {
          Icon(
            imageVector = Icons.Default.Description,
            contentDescription = null,
            tint = MaterialTheme.colorScheme.primary,
            modifier = Modifier.size(20.dp)
          )
          Spacer(modifier = Modifier.width(8.dp))
          Text(
            text = fileName,
            fontWeight = FontWeight.Bold,
            style = MaterialTheme.typography.titleSmall
          )
        }

        IconButton(
          onClick = onCopy,
          modifier = Modifier.size(32.dp).testTag("copy_$fileName")
        ) {
          Icon(
            imageVector = Icons.Default.ContentCopy,
            contentDescription = "Copy",
            tint = MaterialTheme.colorScheme.primary,
            modifier = Modifier.size(18.dp)
          )
        }
      }

      Spacer(modifier = Modifier.height(6.dp))

      Text(
        text = description,
        style = MaterialTheme.typography.bodySmall,
        color = MaterialTheme.colorScheme.onSurfaceVariant
      )
    }
  }
}

@Composable
fun DeploymentTab() {
  val context = LocalContext.current
  val scrollState = rememberScrollState()

  val gitCommands = """git init
git add main.py requirements.txt .env.example .gitignore README.md .github/
git commit -m "Initial commit: Binance Spot 24/7 Cloud Trading Bot"
git branch -M main
git remote add origin https://github.com/aboanasanam42-cpu/wife_bain1.git
git push -u origin main"""

  Column(
    modifier = Modifier
      .fillMaxSize()
      .verticalScroll(scrollState)
  ) {
    Text(
      text = "أوامر Git السريعة للرفع إلى GitHub",
      fontWeight = FontWeight.Bold,
      style = MaterialTheme.typography.titleMedium
    )
    Spacer(modifier = Modifier.height(8.dp))

    Card(
      colors = CardDefaults.cardColors(containerColor = Color(0xFF1E1E1E)),
      shape = RoundedCornerShape(12.dp),
      modifier = Modifier.fillMaxWidth()
    ) {
      Column(modifier = Modifier.padding(14.dp)) {
        Row(
          modifier = Modifier.fillMaxWidth(),
          horizontalArrangement = Arrangement.SpaceBetween,
          verticalAlignment = Alignment.CenterVertically
        ) {
          Text(
            text = "Terminal Bash",
            color = Color.Gray,
            fontSize = 11.sp,
            fontFamily = FontFamily.Monospace
          )
          IconButton(
            onClick = { copyToClipboard(context, "Git Commands", gitCommands) },
            modifier = Modifier.size(28.dp).testTag("copy_git_commands")
          ) {
            Icon(
              imageVector = Icons.Default.ContentCopy,
              contentDescription = "Copy Git Commands",
              tint = Color.White,
              modifier = Modifier.size(16.dp)
            )
          }
        }

        Spacer(modifier = Modifier.height(4.dp))

        Text(
          text = gitCommands,
          fontFamily = FontFamily.Monospace,
          fontSize = 11.sp,
          color = Color(0xFF81D4FA),
          lineHeight = 17.sp,
          modifier = Modifier.horizontalScroll(rememberScrollState())
        )
      }
    }

    Spacer(modifier = Modifier.height(20.dp))

    Text(
      text = "خطوات الاستضافة على منصة Bot-Hosting.net",
      fontWeight = FontWeight.Bold,
      style = MaterialTheme.typography.titleMedium
    )
    Spacer(modifier = Modifier.height(8.dp))

    DeployStepItem(
      number = "1",
      title = "تسجيل الدخول",
      body = "ادخل إلى حسابك في موقع Bot-Hosting.net واضغط زر 'Deploy a new bot'."
    )
    DeployStepItem(
      number = "2",
      title = "اختيار البيئة",
      body = "اختر لغة Python ثم حدد خيار ربط واستيراد الكود من GitHub Repository."
    )
    DeployStepItem(
      number = "3",
      title = "إضافة المتغيرات البيئية (Environment Variables)",
      body = "أضف BINANCE_API_KEY و BINANCE_API_SECRET في لوحة الإعدادات لحماية حسابك."
    )
    DeployStepItem(
      number = "4",
      title = "أمر التشغيل والإطلاق",
      body = "تأكد من أن أمر التشغيل هو: python main.py ثم اضغط Deploy ليعمل البوت على مدار 24/7 دون انقطاع!"
    )
  }
}

@Composable
fun DeployStepItem(number: String, title: String, body: String) {
  Row(
    modifier = Modifier
      .fillMaxWidth()
      .padding(vertical = 6.dp),
    verticalAlignment = Alignment.Top
  ) {
    Surface(
      color = MaterialTheme.colorScheme.primary,
      shape = RoundedCornerShape(50),
      modifier = Modifier.size(26.dp)
    ) {
      Box(contentAlignment = Alignment.Center) {
        Text(
          text = number,
          color = MaterialTheme.colorScheme.onPrimary,
          fontSize = 12.sp,
          fontWeight = FontWeight.Bold
        )
      }
    }
    Spacer(modifier = Modifier.width(10.dp))
    Column {
      Text(
        text = title,
        fontWeight = FontWeight.Bold,
        style = MaterialTheme.typography.bodyMedium
      )
      Text(
        text = body,
        style = MaterialTheme.typography.bodySmall,
        color = MaterialTheme.colorScheme.onSurfaceVariant
      )
    }
  }
}

fun copyToClipboard(context: Context, label: String, text: String) {
  val clipboard = context.getSystemService(Context.CLIPBOARD_SERVICE) as ClipboardManager
  val clip = ClipData.newPlainText(label, text)
  clipboard.setPrimaryClip(clip)
  Toast.makeText(context, "تم النسخ إلى الحافظة بنجاح", Toast.LENGTH_SHORT).show()
}

@Composable
fun Greeting(name: String, modifier: Modifier = Modifier) {
  Text(text = "Hello $name!", modifier = modifier)
}
