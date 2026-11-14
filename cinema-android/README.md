# BRO CINEMA Focus · experimental Android viewer

Native WebView prototype. BRO CINEMA opens inside the app. A user-selected TVWiki episode loads as a top-level page in a separate in-app WebView, rather than an iframe within another website. Optional focus mode attempts to show only #playerArea by hiding unrelated page sections.

This does NOT decode media, bypass sessions, modify signatures or copy and redistribute streams. Third-party playback compatibility is unverified and cannot be guaranteed.

Build with JDK 17, Android SDK 35 and Gradle 8.7:
`gradle :app:assembleDebug`
APK: `app/build/outputs/apk/debug/app-debug.apk`
