# YardScout Android app

This directory contains the Capacitor wrapper for the YardScout web app. It
loads the production site at `https://yardscout.me`, so the Android app and
the PWA share the same backend, login, listings, routes, and notifications.

## Requirements

- Android Studio with an Android SDK and emulator or physical device
- JDK 21
- Node.js 20 or newer

## Setup

From this directory:

```powershell
npm install
npm run android:add
npm run android:sync
npm run android:open
```

Use Android Studio to choose an emulator or connected device and run the
`app` configuration. For a repeatable local build and checks:

```powershell
npm run android:build:debug
npm run android:test
npm run android:lint
```

The wrapper targets SDK 35, blocks cleartext traffic, and excludes private
app data from Android backup and device transfer. Before publishing, replace
the development icon and configure the release signing key in Android Studio.

The app intentionally uses HTTPS only. Do not enable cleartext traffic or
point the release build at a local development server.
