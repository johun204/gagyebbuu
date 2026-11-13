package com.johun.gagyebbuu

import android.app.Notification
import android.content.pm.PackageManager
import android.service.notification.NotificationListenerService
import android.service.notification.StatusBarNotification
import org.json.JSONObject
import java.time.Instant
import java.time.LocalDateTime
import java.time.ZoneId
import java.time.format.DateTimeFormatter

/**
 * 사용자가 고른 앱(문자, 카드앱 등)의 알림을 읽어 입출금 내역인지 기기에서 해석하고(TxParser),
 * 거래로 판단된 것만 서버로 보낸다. 그 밖의 알림은 기기 밖으로 나가지 않는다.
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

        // 서버의 날짜 계산과 맞도록 받은 시각을 한국 시간으로 바꿔 해석한다
        val postedAt = LocalDateTime.ofInstant(Instant.ofEpochMilli(sbn.postTime), SEOUL)
        val parsed = try {
            TxParser.parse(title, text, postedAt)
        } catch (e: Exception) {  // 해석 오류로 알림 수신 서비스가 죽지 않게 한다
            null
        }
        if (parsed == null || parsed.amount > TxParser.MAX_AMOUNT) return
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
            put("parsed", JSONObject().apply {
                put("tx_type", parsed.txType)
                put("amount", parsed.amount)
                put("title", parsed.title)
                put("datetime", parsed.datetime.format(ISO_SECONDS))
            })
        })
        UploadWorker.schedule(this)
    }

    companion object {
        private val SEOUL = ZoneId.of("Asia/Seoul")
        private val ISO_SECONDS = DateTimeFormatter.ofPattern("yyyy-MM-dd'T'HH:mm:ss")
    }
}
