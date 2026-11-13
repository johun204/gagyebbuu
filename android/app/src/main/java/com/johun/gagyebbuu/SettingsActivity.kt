package com.johun.gagyebbuu

import android.Manifest
import android.app.AlertDialog
import android.content.ComponentName
import android.content.Intent
import android.content.pm.PackageManager
import android.graphics.Typeface
import android.graphics.drawable.Drawable
import android.net.Uri
import android.os.Build
import android.os.Bundle
import android.provider.Settings
import android.provider.Telephony
import android.text.Editable
import android.text.TextWatcher
import android.util.TypedValue
import android.view.Gravity
import android.view.View
import android.view.ViewGroup
import android.widget.BaseAdapter
import android.widget.Button
import android.widget.CheckBox
import android.widget.EditText
import android.widget.ImageView
import android.widget.LinearLayout
import android.widget.ListView
import android.widget.TextView
import android.widget.Toast
import androidx.activity.ComponentActivity
import androidx.activity.result.contract.ActivityResultContracts
import androidx.core.app.NotificationManagerCompat
import androidx.core.content.ContextCompat
import org.json.JSONObject
import java.net.HttpURLConnection
import java.net.URL
import kotlin.concurrent.thread

/**
 * 알림 접근 권한 안내 + 어떤 앱의 알림을 읽을지 고르는 화면 (앱 안의 유일한 네이티브 화면).
 * 웹앱의 '알림 자동 감지' 메뉴가 gagyebbuu://settings?token=... 로 열면서 로그인 토큰을 넘겨준다.
 */
class SettingsActivity : ComponentActivity() {
    private class AppItem(val pkg: String, val label: String, val icon: Drawable, val suggested: Boolean)

    private lateinit var prefs: Prefs
    private lateinit var listenerStatus: TextView
    private lateinit var notifyStatus: TextView
    private lateinit var loginStatus: TextView
    private lateinit var countText: TextView
    private val adapter = AppAdapter()
    private var allApps = listOf<AppItem>()
    private var query = ""
    private val askNotifications = registerForActivityResult(ActivityResultContracts.RequestPermission()) { updateStatus() }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        prefs = Prefs(this)
        title = "알림 자동 감지"

        val list = ListView(this).apply {
            fitsSystemWindows = true
            divider = null
            clipToPadding = false
        }
        list.addHeaderView(buildHeader(), null, false)
        list.adapter = adapter
        setContentView(list)

        thread {
            val apps = loadApps()
            runOnUiThread { allApps = apps; refreshList() }
        }
        if (savedInstanceState == null) receiveToken(intent)
        if (Build.VERSION.SDK_INT >= 33 && !Notifier.canNotify(this)) askNotifications.launch(Manifest.permission.POST_NOTIFICATIONS)
    }

    override fun onNewIntent(intent: Intent) {
        super.onNewIntent(intent)
        receiveToken(intent)
    }

    /**
     * 웹이 넘겨준 로그인 토큰을 저장한다. 다른 사이트가 남의 토큰을 넘겨 이 기기의 카드 알림을 가로채지 못하도록,
     * 서버에서 토큰 주인을 확인하고, 전에 연결했던 계정이 아니면(처음 연결 포함) 사용자에게 한 번 더 묻는다.
     */
    private fun receiveToken(intent: Intent?) {
        val token = intent?.data?.takeIf { it.scheme == "gagyebbuu" }?.getQueryParameter("token")
        if (token.isNullOrBlank() || token == prefs.token) return
        thread {
            val me = fetchMe(token)
            runOnUiThread {
                if (me == null) {
                    Toast.makeText(this, "로그인 정보를 확인하지 못했어요. 가계쀼에서 다시 열어주세요.", Toast.LENGTH_LONG).show()
                    return@runOnUiThread
                }
                val userId = me.optLong("user_id", -1)
                val save = {
                    prefs.token = token
                    prefs.userId = userId
                    UploadWorker.schedule(this)
                    updateStatus()
                }
                if (prefs.userId == userId) {
                    save()
                } else {
                    AlertDialog.Builder(this)
                        .setTitle("계정 연결")
                        .setMessage("'${me.optString("nickname")}'님 (${me.optString("ledger")}) 계정으로 알림 자동 감지를 연결할까요?\n감지한 내역이 이 계정으로 보내져요.")
                        .setPositiveButton("연결") { _, _ -> save() }
                        .setNegativeButton("취소", null)
                        .show()
                }
            }
        }
    }

    private fun fetchMe(token: String): JSONObject? = try {
        val conn = URL("${BuildConfig.BASE_URL}/api/me").openConnection() as HttpURLConnection
        try {
            conn.connectTimeout = 10_000
            conn.readTimeout = 10_000
            conn.setRequestProperty("Accept", "application/json")
            conn.setRequestProperty("X-Requested-With", "XMLHttpRequest")
            conn.setRequestProperty("Authorization", "Bearer $token")
            if (conn.responseCode == 200) JSONObject(conn.inputStream.bufferedReader().use { it.readText() }) else null
        } finally {
            conn.disconnect()
        }
    } catch (e: Exception) {
        null
    }

    override fun onResume() {
        super.onResume()
        updateStatus()
    }

    private fun dp(v: Int) = TypedValue.applyDimension(TypedValue.COMPLEX_UNIT_DIP, v.toFloat(), resources.displayMetrics).toInt()

    private fun text(s: String, size: Float = 14f, bold: Boolean = false, muted: Boolean = false) = TextView(this).apply {
        text = s
        textSize = size
        if (bold) setTypeface(typeface, Typeface.BOLD)
        if (muted) alpha = 0.7f
        setPadding(0, dp(4), 0, dp(4))
    }

    private fun button(s: String, onClick: () -> Unit) = Button(this).apply {
        text = s
        isAllCaps = false
        setOnClickListener { onClick() }
    }

    private fun buildHeader(): View = LinearLayout(this).apply {
        orientation = LinearLayout.VERTICAL
        setPadding(dp(20), dp(16), dp(20), dp(8))

        addView(text("1. 알림 접근 허용", 17f, bold = true))
        listenerStatus = text("")
        addView(listenerStatus)
        addView(button("알림 접근 설정 열기") { openListenerSettings() })
        if (Build.VERSION.SDK_INT >= 33) {
            addView(text("목록에서 '가계쀼'가 흐리게 표시되어 켤 수 없다면: 아래 '앱 정보 열기' → 오른쪽 위 ⋮ → '제한된 설정 허용'을 누른 뒤 다시 시도하세요. (스토어 밖에서 설치한 앱이라 한 번 필요해요)", 13f, muted = true))
            addView(button("앱 정보 열기") {
                startActivity(Intent(Settings.ACTION_APPLICATION_DETAILS_SETTINGS, Uri.parse("package:$packageName")))
            })
        }
        notifyStatus = text("")
        addView(notifyStatus)
        loginStatus = text("")
        addView(loginStatus)

        addView(text("2. 읽을 앱 선택", 17f, bold = true).apply { setPadding(0, dp(20), 0, dp(4)) })
        addView(text("고른 앱의 알림을 이 기기에서 살펴보고, 입출금 내역으로 판단된 것만 서버로 보내요. 그 밖의 알림은 기기 밖으로 나가지 않아요. 감지된 내역은 7일 동안 보관되고, 앱의 알림 화면에서 등록하거나 삭제할 수 있어요.", 13f, muted = true))
        if (Build.VERSION.SDK_INT >= 35) {
            addView(text("참고: Android 15부터는 인증번호처럼 보이는 숫자(예: '(1234)' 같은 4자리 번호)가 든 알림은 시스템이 내용을 가려서 읽을 수 없어요. 이런 알림은 감지되지 않을 수 있어요.", 13f, muted = true))
        }
        countText = text("", 13f, bold = true)
        addView(countText)
        addView(EditText(context).apply {
            hint = "앱 이름 검색"
            setSingleLine()
            addTextChangedListener(object : TextWatcher {
                override fun beforeTextChanged(s: CharSequence?, a: Int, b: Int, c: Int) {}
                override fun onTextChanged(s: CharSequence?, a: Int, b: Int, c: Int) {}
                override fun afterTextChanged(s: Editable?) { query = s?.toString().orEmpty().trim(); refreshList() }
            })
        })
    }

    private fun updateStatus() {
        val enabled = NotificationManagerCompat.getEnabledListenerPackages(this).contains(packageName)
        listenerStatus.text = if (enabled) "✅ 허용됨" else "⚠️ 아직 허용되지 않았어요. 아래 버튼을 눌러 '가계쀼'를 켜주세요."
        val canNotify = Build.VERSION.SDK_INT < 33 ||
            ContextCompat.checkSelfPermission(this, Manifest.permission.POST_NOTIFICATIONS) == PackageManager.PERMISSION_GRANTED
        notifyStatus.text = if (canNotify) "✅ 감지 알림 표시 허용됨" else "⚠️ 알림 표시가 꺼져 있어 감지해도 알림이 뜨지 않아요 (내역은 앱의 알림 화면에 모여요)."
        notifyStatus.setOnClickListener(if (canNotify) null else View.OnClickListener {
            startActivity(Intent(Settings.ACTION_APP_NOTIFICATION_SETTINGS).putExtra(Settings.EXTRA_APP_PACKAGE, packageName))
        })
        loginStatus.text = if (prefs.token != null) "✅ 가계쀼 계정 연결됨" else "⚠️ 가계쀼 계정이 연결되지 않았어요. 가계쀼 앱의 설정 > 알림 자동 감지에서 이 화면을 열어주세요."
        countText.text = "선택한 앱 ${prefs.watchedPackages.size}개"
    }

    private fun openListenerSettings() {
        val detail = if (Build.VERSION.SDK_INT >= 30)
            Intent(Settings.ACTION_NOTIFICATION_LISTENER_DETAIL_SETTINGS)
                .putExtra(Settings.EXTRA_NOTIFICATION_LISTENER_COMPONENT_NAME, ComponentName(this, TxListenerService::class.java).flattenToString())
        else null
        try {
            startActivity(detail ?: Intent(Settings.ACTION_NOTIFICATION_LISTENER_SETTINGS))
        } catch (e: Exception) {
            startActivity(Intent(Settings.ACTION_NOTIFICATION_LISTENER_SETTINGS))
        }
    }

    private fun loadApps(): List<AppItem> {
        val pm = packageManager
        val smsPkg = Telephony.Sms.getDefaultSmsPackage(this)
        val launcher = Intent(Intent.ACTION_MAIN).addCategory(Intent.CATEGORY_LAUNCHER)
        return pm.queryIntentActivities(launcher, 0)
            .map { it.activityInfo.applicationInfo }
            .distinctBy { it.packageName }
            .filter { it.packageName != packageName }
            .map { ai ->
                val label = pm.getApplicationLabel(ai).toString()
                val hay = "$label ${ai.packageName}".lowercase()
                AppItem(ai.packageName, label, pm.getApplicationIcon(ai),
                    ai.packageName == smsPkg || SUGGEST_WORDS.any { it in hay })
            }
    }

    private fun refreshList() {
        val watched = prefs.watchedPackages
        val q = query.lowercase()
        adapter.items = allApps
            .filter { q.isEmpty() || it.label.lowercase().contains(q) || it.pkg.contains(q) }
            .sortedWith(compareBy<AppItem>({ it.pkg !in watched }, { !it.suggested }, { it.label }))
        adapter.notifyDataSetChanged()
        countText.text = "선택한 앱 ${watched.size}개" + if (allApps.isEmpty()) " · 앱 목록 불러오는 중…" else ""
    }

    private inner class AppAdapter : BaseAdapter() {
        var items = listOf<AppItem>()
        override fun getCount() = items.size
        override fun getItem(position: Int) = items[position]
        override fun getItemId(position: Int) = position.toLong()

        override fun getView(position: Int, convertView: View?, parent: ViewGroup): View {
            val row = (convertView as? LinearLayout) ?: LinearLayout(this@SettingsActivity).apply {
                orientation = LinearLayout.HORIZONTAL
                gravity = Gravity.CENTER_VERTICAL
                setPadding(dp(20), dp(10), dp(12), dp(10))
                addView(ImageView(context), LinearLayout.LayoutParams(dp(40), dp(40)))
                addView(LinearLayout(context).apply {
                    orientation = LinearLayout.VERTICAL
                    setPadding(dp(14), 0, dp(8), 0)
                    addView(TextView(context).apply { textSize = 15f })
                    addView(TextView(context).apply { textSize = 12f; alpha = 0.6f })
                }, LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f))
                addView(CheckBox(context).apply { isClickable = false; isFocusable = false })
            }
            val item = items[position]
            val texts = row.getChildAt(1) as LinearLayout
            (row.getChildAt(0) as ImageView).setImageDrawable(item.icon)
            (texts.getChildAt(0) as TextView).text = item.label
            (texts.getChildAt(1) as TextView).text = if (item.suggested) "추천 · ${item.pkg}" else item.pkg
            val check = row.getChildAt(2) as CheckBox
            check.isChecked = item.pkg in prefs.watchedPackages
            row.setOnClickListener {
                val set = prefs.watchedPackages.toMutableSet()
                if (!set.add(item.pkg)) set.remove(item.pkg)
                prefs.watchedPackages = set
                check.isChecked = item.pkg in set
                countText.text = "선택한 앱 ${set.size}개"
            }
            return row
        }
    }

    companion object {
        // 문자/카드/은행/간편결제 앱으로 보이는 이름 (특정 앱 목록이 아니라 일반적인 단어로 추천)
        private val SUGGEST_WORDS = listOf(
            "카드", "은행", "뱅크", "뱅킹", "페이", "문자", "메시지", "증권", "머니", "토스",
            "card", "bank", "pay", "sms", "mms", "messag", "money", "wallet", "finance",
        )
    }
}
