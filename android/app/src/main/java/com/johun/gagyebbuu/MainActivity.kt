package com.johun.gagyebbuu

import android.content.ActivityNotFoundException
import android.content.Intent
import android.content.pm.PackageManager
import android.net.Uri
import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.widget.Toast
import androidx.browser.customtabs.CustomTabsIntent
import androidx.work.WorkManager
import com.google.androidbrowserhelper.trusted.LauncherActivity
import com.google.androidbrowserhelper.trusted.TwaLauncher

/**
 * 웹앱(BASE_URL)을 크롬 Trusted Web Activity 로 띄운다. 크롬 그대로라 웹 푸시·카카오 로그인·파일 저장 등
 * 브라우저 기능이 모두 동작하고, 푸시 알림은 이 앱의 이름/아이콘으로 표시된다.
 * 사이트의 /.well-known/assetlinks.json 이 이 앱의 서명 키를 가리켜야 주소창 없이 열린다.
 *
 * 시작 주소에 gb_app=앱버전 을 붙여 웹이 앱 안에서 열렸음을 알 수 있게 한다 (앱 전용 메뉴, 업데이트 안내).
 * 감지 알림을 누르면 EXTRA_PATH 의 화면(예: /notifications?detected=12)이 열린다.
 */
class MainActivity : LauncherActivity() {

    private val handler = Handler(Looper.getMainLooper())

    /**
     * TWA 는 브라우저의 서비스에 연결된 뒤에야 열리는데, 브라우저가 응답하지 않으면(삼성 인터넷이 백그라운드에서
     * 멈춰 있을 때 등) 끝없이 기다리며 빈 화면만 보인다. 잠시 기다려도 안 열리면 일반 브라우저 탭으로 연다.
     */
    private val fallback = Runnable {
        try {
            val tab = CustomTabsIntent.Builder().build()
            // 패키지를 정하지 않으면 이 주소를 여는 앱인 이 앱이 다시 열린다
            tab.intent.setPackage(browserPackage())
            tab.launchUrl(this, launchingUrl)
        } catch (e: ActivityNotFoundException) {
            Toast.makeText(this, R.string.no_browser, Toast.LENGTH_LONG).show()
        }
        finish()
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        // v1.1 의 상대방 알림 주기 확인 작업은 웹 푸시로 바뀌어 없어졌다
        WorkManager.getInstance(this).cancelUniqueWork("partner-poll")
        Notifier.ensureChannels(this)
        if (!isFinishing) handler.postDelayed(fallback, LAUNCH_TIMEOUT_MS)
    }

    // 브라우저가 떠서 이 화면이 가려지면 기다릴 필요가 없다
    override fun onPause() {
        super.onPause()
        handler.removeCallbacks(fallback)
    }

    override fun onDestroy() {
        handler.removeCallbacks(fallback)
        super.onDestroy()
    }

    /**
     * 크롬이 있으면 기본 브라우저와 상관없이 크롬으로 연다 (기본 브라우저가 바뀌어도 로그인·웹 푸시 구독이 유지된다).
     * 크롬이 없으면 TWA 를 지원하는 기본 브라우저(삼성 인터넷 등)로 연다.
     */
    override fun createTwaLauncher(): TwaLauncher =
        if (hasChrome()) TwaLauncher(this, CHROME) else super.createTwaLauncher()

    private fun hasChrome(): Boolean =
        try { packageManager.getApplicationInfo(CHROME, 0).enabled } catch (e: PackageManager.NameNotFoundException) { false }

    /** 크롬, 없으면 기기의 기본 브라우저 */
    private fun browserPackage(): String? =
        if (hasChrome()) CHROME
        else packageManager.resolveActivity(Intent(Intent.ACTION_VIEW, Uri.parse("https://example.com")),
            PackageManager.MATCH_DEFAULT_ONLY)?.activityInfo?.packageName

    override fun getLaunchingUrl(): Uri {
        val base = Uri.parse(BuildConfig.BASE_URL)
        val path = intent?.getStringExtra(EXTRA_PATH)
        val data = intent?.data
        val target = when {
            path != null && path.startsWith("/") && !path.startsWith("//") -> Uri.parse(BuildConfig.BASE_URL + path)
            data != null && data.scheme == "https" && data.host == base.host -> data
            else -> super.getLaunchingUrl()
        }
        return target.buildUpon().appendQueryParameter("gb_app", BuildConfig.VERSION_NAME).build()
    }

    companion object {
        const val EXTRA_PATH = "path"
        private const val LAUNCH_TIMEOUT_MS = 4000L
        private const val CHROME = "com.android.chrome"
    }
}
