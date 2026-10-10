package dev.aster.companion

import android.Manifest
import android.app.Activity
import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.content.Intent
import android.content.pm.PackageManager
import android.graphics.Color
import android.os.Build
import android.os.Bundle
import android.view.View
import android.widget.Button
import android.widget.EditText
import android.widget.LinearLayout
import android.widget.ScrollView
import android.widget.TextView
import java.util.UUID

/** Source prototype: every invitation is generated locally by a visible button. */
class MainActivity : Activity() {
    private val gate = InvitationGate("offline-demo-device")
    private var pendingId: String? = null
    private lateinit var status: TextView
    private lateinit var answer: Button
    private lateinit var endpoint: EditText
    private val notifications get() = getSystemService(NotificationManager::class.java)
    private fun now() = System.currentTimeMillis() / 1000
    private fun dp(value: Int) = (value * resources.displayMetrics.density).toInt()

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        notifications.cancel(1) // process/activity restart invalidates in-memory invitations
        notifications.createNotificationChannel(NotificationChannel(
            "offline-demo", "Aster demo invitations", NotificationManager.IMPORTANCE_DEFAULT
        ).apply { description = "Locally generated prototype notifications, not actual calls" })
        val content = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            setPadding(dp(24), dp(32), dp(24), dp(32))
            setBackgroundColor(Color.rgb(246, 243, 250))
        }
        fun text(value: String, size: Float = 16f): TextView = TextView(this).apply {
            text = value; textSize = size; setTextColor(Color.rgb(37, 31, 48))
            setPadding(0, dp(8), 0, dp(12)); content.addView(this)
        }
        fun button(label: String, action: () -> Unit): Button = Button(this).apply {
            text = label; isAllCaps = false; setOnClickListener { action() }; content.addView(this)
        }
        text("Aster", 34f)
        text("Your workstation companion", 20f)
        text("OFFLINE PROTOTYPE · NO SERVICE FEES", 12f)
        status = text("Waiting for NewBrain. This prototype can show a local invitation; it cannot connect to the workstation or carry voice.")
        text("Connection preview", 20f)
        endpoint = EditText(this).apply {
            hint = "https://workstation.example:8443"
            inputType = android.text.InputType.TYPE_CLASS_TEXT or android.text.InputType.TYPE_TEXT_VARIATION_URI
            setSingleLine(); content.addView(this)
        }
        button("Validate address (does not connect)") {
            status.text = if (InvitationGate.validEndpoint(endpoint.text.toString().trim()))
                "HTTPS address format accepted. Not paired or connected. A future transport must verify trusted TLS and the enrolled workstation identity."
            else "Use an HTTPS origin with no username, password, path, query, or fragment. No connection was attempted."
        }
        text("Pairing is unavailable. No credentials are created or stored. Network access is disabled in this build.", 14f)
        button("Create a local demo invitation") { createDemo() }
        answer = button("Open demo session") { openSession() }.apply { visibility = View.GONE }
        button("Dismiss / end demo") {
            gate.dismiss(); pendingId = null; notifications.cancel(1)
            answer.visibility = View.GONE
            status.text = "Demo ended. Microphone off. No network connection."
        }
        text("Voice", 20f)
        text("Microphone: OFF\nNewBrain: unavailable\nRemote calling: disabled\nPaid services: none\n\nReal phone ringing, pairing, and two-way audio are future work. The workstation must be awake and running Aster for a future live session.", 15f)
        setContentView(ScrollView(this).apply { addView(content) })
    }

    private fun createDemo() {
        gate.dismiss(); notifications.cancel(1)
        val id = UUID.randomUUID().toString()
        val issuedAt = now()
        if (!gate.receive(InvitationGate.Invite(id, "offline-demo-device", issuedAt, issuedAt + 60), issuedAt)) {
            status.text = "Demo invitation rejected. Restart the demo if its in-memory replay budget is full."
            return
        }
        pendingId = id; answer.visibility = View.VISIBLE
        status.text = "Local demo invitation ready for 60 seconds. Open the notification or the button below. No call has been placed."
        if (Build.VERSION.SDK_INT >= 33 && checkSelfPermission(Manifest.permission.POST_NOTIFICATIONS) != PackageManager.PERMISSION_GRANTED) {
            // Requested only after the user's explicit demo button tap, never on launch.
            requestPermissions(arrayOf(Manifest.permission.POST_NOTIFICATIONS), 11)
        } else postDemo()
    }

    private fun postDemo() {
        if (pendingId == null) return
        if (Build.VERSION.SDK_INT >= 33 && checkSelfPermission(Manifest.permission.POST_NOTIFICATIONS) != PackageManager.PERMISSION_GRANTED) return
        val tap = PendingIntent.getActivity(this, 1,
            Intent(this, MainActivity::class.java).setAction("dev.aster.companion.OPEN_DEMO").addFlags(Intent.FLAG_ACTIVITY_SINGLE_TOP),
            PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE)
        notifications.notify(1, Notification.Builder(this, "offline-demo")
            .setSmallIcon(android.R.drawable.ic_dialog_info)
            .setContentTitle("Aster · local demo")
            .setContentText("Tap to view the invitation. Voice is not connected.")
            .setContentIntent(tap).setAutoCancel(true).setTimeoutAfter(60_000).build())
    }

    override fun onRequestPermissionsResult(requestCode: Int, permissions: Array<out String>, grantResults: IntArray) {
        super.onRequestPermissionsResult(requestCode, permissions, grantResults)
        if (requestCode == 11) {
            if (grantResults.firstOrNull() == PackageManager.PERMISSION_GRANTED) postDemo()
            else status.text = "Notifications remain off. You can still open the local demo with the button. No microphone or network access."
        }
    }

    override fun onNewIntent(intent: Intent) {
        super.onNewIntent(intent)
        // An external intent can bring UI forward, never authorize a call or microphone.
        if (pendingId != null) status.text = "Review the local demo invitation, then tap Open demo session. No microphone will start."
    }

    private fun openSession() {
        val id = pendingId
        if (id == null || !gate.answer(id, now())) {
            status.text = "Invitation expired, already opened, or no longer available. Create a new local demo."
            answer.visibility = View.GONE
            return
        }
        notifications.cancel(1); answer.visibility = View.GONE
        status.text = "Demo session opened. Waiting for NewBrain. There is no assistant reply, microphone capture, audio playback, or network connection."
    }
}
