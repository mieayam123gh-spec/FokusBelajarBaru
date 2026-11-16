package com.example.fokusbelajar

import android.app.Activity
import android.content.Intent
import android.os.Bundle
import android.view.Gravity
import android.widget.Button
import android.widget.LinearLayout
import android.widget.TextView

class BlockActivity : Activity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)

        val message = TextView(this).apply {
            text = "Waktunya belajar!\n\nAplikasi ini diblokir selama sesi fokus."
            textSize = 22f
            gravity = Gravity.CENTER
            setPadding(60, 60, 60, 60)
        }

        val backHome = Button(this).apply {
            text = "Kembali ke layar utama"
            setOnClickListener { goHome() }
        }

        val layout = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            gravity = Gravity.CENTER
            addView(message)
            addView(backHome)
        }
        setContentView(layout)
    }

    private fun goHome() {
        startActivity(
            Intent(Intent.ACTION_MAIN)
                .addCategory(Intent.CATEGORY_HOME)
                .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
        )
        finish()
    }
}
