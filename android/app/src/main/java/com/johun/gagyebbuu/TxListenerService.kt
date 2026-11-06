package com.johun.gagyebbuu

import android.app.Notification
import android.content.pm.PackageManager
import android.service.notification.NotificationListenerService
import android.service.notification.StatusBarNotification
import org.json.JSONObject

/**
 * 사용자가 고른 앱(문자, 카드앱 등)의 알림을 읽어 서버로 보낸다.
 * 해석(금액/가맹점 추출)은 서버가 하므로 규칙이 바뀌어도 앱을 업데이트할 필요가 없다.
 */
class TxListenerService : NotificationListenerService() {

    override fun onNotificationPosted(sbn: StatusBarNotification) {
        if (sbn.packageName == packageName) return
        val prefs = Prefs(this)
        if (sbn.packageName !in prefs.watchedPackages) return
        val n = sbn.notification ?: return
        if (n.flags and Notification.FLAG_GROUP_SUMMARY != 0) return

        val extras = n.extras
        val title = extras.getCharSequence(Notification.EXTRA_TITLE)?.toString().orEmpty()
        val text = (extras.getCharSequence(Notification.EXTRA_BIG_TEXT)
            ?: extras.getCharSequence(Notification.EXTRA_TEXT))?.toString().orEmpty()
        val all = "$title\n$text"

        // 개인 메시지가 서버로 가지 않도록 금액/입출금 단서가 있는 알림만 보낸다 (정밀한 판단은 서버가 한다)
        if (!LOOKS_LIKE_MONEY.containsMatchIn(all)) return
        if (prefs.seenRecently("${sbn.packageName}|${all.hashCode()}", System.currentTimeMillis())) return

        val label = try {
            packageManager.getApplicationLabel(packageManager.getApplicationInfo(sbn.packageName, 0)).toString()
        } catch (e: PackageManager.NameNotFoundException) {
            sbn.packageName
        }
        prefs.enqueue(JSONObject().apply {
            put("qid", "${sbn.postTime}|${all.hashCode()}")
            put("package", sbn.packageName)
            put("app_label", label)
            put("title", title)
            put("text", text)
            put("posted_at", sbn.postTime)
        })
        UploadWorker.schedule(this)
    }

    companion object {
        private val LOOKS_LIKE_MONEY = Regex("""\d[\d,]*\s*원|입금|출금|승인|결제""")
    }
}
