package com.johun.gagyebbuu

import android.Manifest
import android.annotation.SuppressLint
import android.app.AlertDialog
import android.content.ActivityNotFoundException
import android.content.ContentValues
import android.content.Intent
import android.content.res.Configuration
import android.net.Uri
import android.os.Build
import android.os.Bundle
import android.provider.MediaStore
import android.webkit.JavascriptInterface
import android.webkit.ValueCallback
import android.webkit.WebChromeClient
import android.webkit.WebResourceRequest
import android.webkit.WebView
import android.webkit.WebViewClient
import android.widget.FrameLayout
import android.widget.Toast
import androidx.activity.ComponentActivity
import androidx.activity.OnBackPressedCallback
import androidx.activity.result.contract.ActivityResultContracts
import androidx.core.view.ViewCompat
import androidx.core.view.WindowCompat
import androidx.core.view.WindowInsetsCompat
import org.json.JSONTokener

/**
 * 웹앱(BASE_URL)을 그대로 보여주는 얇은 껍데기. 화면과 기능은 모두 웹에 있으므로 웹이 바뀌어도
 * 이 앱은 업데이트할 필요가 없다. 앱이 하는 일은 (1) 로그인 토큰을 알림 감지 서비스와 공유하고
 * (2) 웹에서 부를 수 있는 몇 가지 기기 기능(window.GagyebbuuAndroid)을 제공하는 것뿐이다.
 */
class MainActivity : ComponentActivity() {
    private lateinit var webView: WebView
    private lateinit var prefs: Prefs
    private var fileCallback: ValueCallback<Array<Uri>>? = null

    private val pickFile = registerForActivityResult(ActivityResultContracts.GetContent()) { uri ->
        fileCallback?.onReceiveValue(if (uri != null) arrayOf(uri) else null)
        fileCallback = null
    }
    private val askNotifications = registerForActivityResult(ActivityResultContracts.RequestPermission()) { }

    @SuppressLint("SetJavaScriptEnabled")
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        prefs = Prefs(this)
        Notifier.ensureChannels(this)

        val night = (resources.configuration.uiMode and Configuration.UI_MODE_NIGHT_MASK) == Configuration.UI_MODE_NIGHT_YES
        WindowCompat.setDecorFitsSystemWindows(window, false)
        WindowCompat.getInsetsController(window, window.decorView).apply {
            isAppearanceLightStatusBars = !night
            isAppearanceLightNavigationBars = !night
        }

        val root = FrameLayout(this).apply { setBackgroundColor(if (night) 0xFF0F1115.toInt() else 0xFFF4F5F8.toInt()) }
        webView = WebView(this).apply { setBackgroundColor(if (night) 0xFF0F1115.toInt() else 0xFFF4F5F8.toInt()) }
        root.addView(webView, FrameLayout.LayoutParams(FrameLayout.LayoutParams.MATCH_PARENT, FrameLayout.LayoutParams.MATCH_PARENT))
        setContentView(root)
        // 상태바/내비게이션바/키보드 영역만큼 안쪽으로 (웹 화면이 시스템 바 아래로 들어가지 않게)
        ViewCompat.setOnApplyWindowInsetsListener(root) { v, insets ->
            val bars = insets.getInsets(WindowInsetsCompat.Type.systemBars() or WindowInsetsCompat.Type.displayCutout())
            val ime = insets.getInsets(WindowInsetsCompat.Type.ime())
            v.setPadding(bars.left, bars.top, bars.right, maxOf(bars.bottom, ime.bottom))
            WindowInsetsCompat.CONSUMED
        }

        webView.settings.apply {
            javaScriptEnabled = true
            domStorageEnabled = true
            userAgentString = "$userAgentString GagyebbuuApp/${BuildConfig.VERSION_NAME}"
        }
        webView.addJavascriptInterface(Bridge(), "GagyebbuuAndroid")
        webView.webViewClient = object : WebViewClient() {
            override fun shouldOverrideUrlLoading(view: WebView, request: WebResourceRequest): Boolean =
                handleExternalUrl(request.url)

            override fun onPageFinished(view: WebView, url: String?) = syncToken()
        }
        webView.webChromeClient = object : WebChromeClient() {
            override fun onShowFileChooser(view: WebView, callback: ValueCallback<Array<Uri>>, params: FileChooserParams): Boolean {
                fileCallback?.onReceiveValue(null)
                fileCallback = callback
                return try {
                    pickFile.launch("*/*"); true
                } catch (e: ActivityNotFoundException) {
                    fileCallback = null; false
                }
            }
        }

        onBackPressedDispatcher.addCallback(this, object : OnBackPressedCallback(true) {
            override fun handleOnBackPressed() {
                if (webView.canGoBack()) webView.goBack() else finish()
            }
        })

        if (savedInstanceState != null) webView.restoreState(savedInstanceState)
        else webView.loadUrl(urlFor(intent))

        if (Build.VERSION.SDK_INT >= 33) askNotifications.launch(Manifest.permission.POST_NOTIFICATIONS)
        if (!prefs.introShown) showIntro()
    }

    override fun onNewIntent(intent: Intent) {
        super.onNewIntent(intent)
        if (intent.getStringExtra(EXTRA_PATH) != null || intent.data != null) webView.loadUrl(urlFor(intent))
    }

    override fun onPause() {
        super.onPause()
        syncToken()
    }

    override fun onSaveInstanceState(outState: Bundle) {
        super.onSaveInstanceState(outState)
        webView.saveState(outState)
    }

    private fun urlFor(intent: Intent?): String {
        val path = intent?.getStringExtra(EXTRA_PATH)
        if (path != null && path.startsWith("/") && !path.startsWith("//")) return BuildConfig.BASE_URL + path
        val data = intent?.data
        if (data != null && data.scheme == "https" && data.host == Uri.parse(BuildConfig.BASE_URL).host) return data.toString()
        return BuildConfig.BASE_URL + "/"
    }

    /** 웹앱/카카오 로그인 주소는 앱 안에서, 그 밖의 링크와 앱 호출(intent://, kakaotalk:// 등)은 밖으로. */
    private fun handleExternalUrl(uri: Uri): Boolean {
        val host = uri.host.orEmpty()
        if (uri.scheme == "http" || uri.scheme == "https") {
            val ours = host == Uri.parse(BuildConfig.BASE_URL).host
            val kakao = host == "kakao.com" || host.endsWith(".kakao.com")
            if (ours || kakao) return false
            openOutside(Intent(Intent.ACTION_VIEW, uri))
            return true
        }
        if (uri.scheme == "intent") {
            try {
                val intent = Intent.parseUri(uri.toString(), Intent.URI_INTENT_SCHEME)
                try {
                    startActivity(intent)
                } catch (e: ActivityNotFoundException) {
                    val fallback = intent.getStringExtra("browser_fallback_url")
                    when {
                        fallback != null -> webView.loadUrl(fallback)
                        intent.`package` != null -> openOutside(Intent(Intent.ACTION_VIEW, Uri.parse("market://details?id=${intent.`package`}")))
                    }
                }
            } catch (e: Exception) { /* 잘못된 intent 주소는 무시 */ }
            return true
        }
        openOutside(Intent(Intent.ACTION_VIEW, uri))
        return true
    }

    private fun openOutside(intent: Intent) {
        try { startActivity(intent) } catch (e: ActivityNotFoundException) { }
    }

    /** 웹앱이 저장한 로그인 토큰을 알림 감지 서비스가 쓸 수 있게 옮겨 둔다. */
    private fun syncToken() {
        if (!::webView.isInitialized) return
        val origin = Uri.parse(BuildConfig.BASE_URL).host
        if (Uri.parse(webView.url ?: return).host != origin) return
        webView.evaluateJavascript("localStorage.getItem('jwt_token')") { raw ->
            val token = try { JSONTokener(raw).nextValue() as? String } catch (e: Exception) { null }
            val changed = token != prefs.token
            prefs.token = token
            if (token != null && (changed || prefs.queue().length() > 0)) UploadWorker.schedule(this)
        }
    }

    private fun showIntro() {
        prefs.introShown = true
        AlertDialog.Builder(this)
            .setTitle("문자·카드 알림으로 자동 기록")
            .setMessage("문자나 카드앱 알림에서 지출·입금을 찾아 바로 등록할 수 있게 도와드려요.\n\n어떤 앱의 알림을 읽을지 지금 고를까요? (나중에 설정 > 알림 자동 감지에서도 할 수 있어요)")
            .setPositiveButton("설정하기") { _, _ -> startActivity(Intent(this, SettingsActivity::class.java)) }
            .setNegativeButton("나중에", null)
            .show()
    }

    /** 웹에서 window.GagyebbuuAndroid.xxx() 로 부르는 기능. 웹 쪽은 이 객체가 있을 때만 앱 전용 메뉴를 보여준다. */
    inner class Bridge {
        @JavascriptInterface
        fun openSettings() = runOnUiThread { startActivity(Intent(this@MainActivity, SettingsActivity::class.java)) }

        @JavascriptInterface
        fun appVersion(): String = BuildConfig.VERSION_NAME

        /** blob 다운로드 대신: 텍스트 파일을 다운로드 폴더에 저장한다. */
        @JavascriptInterface
        fun saveText(content: String, fileName: String, mime: String) {
            val ok = try {
                if (Build.VERSION.SDK_INT >= 29) {
                    val values = ContentValues().apply {
                        put(MediaStore.Downloads.DISPLAY_NAME, fileName.replace('/', '_'))
                        put(MediaStore.Downloads.MIME_TYPE, mime)
                    }
                    val uri = contentResolver.insert(MediaStore.Downloads.EXTERNAL_CONTENT_URI, values)
                    uri != null && contentResolver.openOutputStream(uri)?.use {
                        it.write(byteArrayOf(0xEF.toByte(), 0xBB.toByte(), 0xBF.toByte())) // 엑셀에서 한글이 깨지지 않게 BOM
                        it.write(content.toByteArray(Charsets.UTF_8))
                    } != null
                } else {
                    shareText(content, fileName, mime); true
                }
            } catch (e: Exception) { false }
            runOnUiThread {
                Toast.makeText(this@MainActivity, if (ok) "다운로드 폴더에 $fileName 을(를) 저장했어요" else "파일을 저장하지 못했어요", Toast.LENGTH_LONG).show()
            }
        }
    }

    private fun shareText(content: String, fileName: String, mime: String) {
        val send = Intent(Intent.ACTION_SEND).setType(mime)
            .putExtra(Intent.EXTRA_TITLE, fileName).putExtra(Intent.EXTRA_TEXT, content)
        runOnUiThread { openOutside(Intent.createChooser(send, fileName)) }
    }

    companion object {
        const val EXTRA_PATH = "path"
    }
}
