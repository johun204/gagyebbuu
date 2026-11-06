package com.johun.gagyebbuu

import android.net.Uri
import android.os.Bundle
import androidx.work.WorkManager
import com.google.androidbrowserhelper.trusted.LauncherActivity

/**
 * 웹앱(BASE_URL)을 크롬 Trusted Web Activity 로 띄운다. 크롬 그대로라 웹 푸시·카카오 로그인·파일 저장 등
 * 브라우저 기능이 모두 동작하고, 푸시 알림은 이 앱의 이름/아이콘으로 표시된다.
 * 사이트의 /.well-known/assetlinks.json 이 이 앱의 서명 키를 가리켜야 주소창 없이 열린다.
 *
 * 시작 주소에 gb_app=앱버전 을 붙여 웹이 앱 안에서 열렸음을 알 수 있게 한다 (앱 전용 메뉴, 업데이트 안내).
 * 감지 알림을 누르면 EXTRA_PATH 의 화면(예: /notifications?detected=12)이 열린다.
 */
class MainActivity : LauncherActivity() {

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        // v1.1 의 상대방 알림 주기 확인 작업은 웹 푸시로 바뀌어 없어졌다
        WorkManager.getInstance(this).cancelUniqueWork("partner-poll")
        Notifier.ensureChannels(this)
    }

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
    }
}
