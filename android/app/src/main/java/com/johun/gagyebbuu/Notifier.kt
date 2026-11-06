package com.johun.gagyebbuu

import android.Manifest
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import android.os.Build
import androidx.core.app.NotificationCompat
import androidx.core.app.NotificationManagerCompat
import androidx.core.content.ContextCompat

object Notifier {
    private const val CHANNEL_DETECTED = "detected"
    private const val CHANNEL_PARTNER = "partner"

    fun ensureChannels(context: Context) {
        val nm = context.getSystemService(NotificationManager::class.java)
        nm.createNotificationChannel(
            NotificationChannel(CHANNEL_DETECTED, "감지된 입출금", NotificationManager.IMPORTANCE_HIGH).apply {
                description = "문자·카드앱 알림에서 찾은 입출금을 알려드려요"
            }
        )
        nm.createNotificationChannel(
            NotificationChannel(CHANNEL_PARTNER, "가계부 알림", NotificationManager.IMPORTANCE_DEFAULT).apply {
                description = "상대방이 내역을 등록·수정·삭제하면 알려드려요"
            }
        )
    }

    fun canNotify(context: Context) = Build.VERSION.SDK_INT < 33 ||
        ContextCompat.checkSelfPermission(context, Manifest.permission.POST_NOTIFICATIONS) == PackageManager.PERMISSION_GRANTED

    /** 상대방 활동 알림. 누르면 웹앱의 해당 화면(url)이 열린다. */
    fun showPartner(context: Context, id: Long, title: String, body: String, url: String) {
        if (!canNotify(context)) return
        ensureChannels(context)
        val intent = Intent(context, MainActivity::class.java)
            .putExtra(MainActivity.EXTRA_PATH, url)
            .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_SINGLE_TOP)
        val pi = PendingIntent.getActivity(context, (id % Int.MAX_VALUE).toInt(), intent,
            PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE)
        val n = NotificationCompat.Builder(context, CHANNEL_PARTNER)
            .setSmallIcon(R.drawable.ic_stat_coin)
            .setColor(0xFF4F5BD5.toInt())
            .setContentTitle(title)
            .setContentText(body)
            .setStyle(NotificationCompat.BigTextStyle().bigText(body))
            .setContentIntent(pi)
            .setAutoCancel(true)
            .build()
        NotificationManagerCompat.from(context).notify("partner", (id % Int.MAX_VALUE).toInt(), n)
    }

    /** 감지 알림. 누르면 웹앱의 등록 화면(url)이 열린다. */
    fun showDetected(context: Context, id: Int, title: String, body: String, url: String) {
        if (!canNotify(context)) return
        ensureChannels(context)
        val intent = Intent(context, MainActivity::class.java)
            .putExtra(MainActivity.EXTRA_PATH, url)
            .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_SINGLE_TOP)
        val pi = PendingIntent.getActivity(context, id, intent,
            PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE)
        val n = NotificationCompat.Builder(context, CHANNEL_DETECTED)
            .setSmallIcon(R.drawable.ic_stat_coin)
            .setColor(0xFF4F5BD5.toInt())
            .setContentTitle(title)
            .setContentText(body)
            .setStyle(NotificationCompat.BigTextStyle().bigText(body))
            .setContentIntent(pi)
            .setAutoCancel(true)
            .setPriority(NotificationCompat.PRIORITY_HIGH)
            .build()
        NotificationManagerCompat.from(context).notify(1000 + id, n)
    }
}
