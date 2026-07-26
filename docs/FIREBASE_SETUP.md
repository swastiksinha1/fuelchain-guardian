# Firebase Setup for PumpCast

## 1. Create Firebase Project

1. Go to https://console.firebase.google.com
2. Click **Add project** → name it `fuelchain-guardian`
3. Disable Google Analytics (optional)
4. Click **Create project**

---

## 2. Add Apps to Firebase Project

### Android App
1. Click **+ Add app** → Android
2. Package name: `dev.fuelchain.pumpcast`
3. Download `google-services.json`
4. Place it at: `flutter/android/app/google-services.json`

### iOS App
1. Click **+ Add app** → iOS
2. Bundle ID: `dev.fuelchain.pumpcast`
3. Download `GoogleService-Info.plist`
4. Place it at: `flutter/ios/Runner/GoogleService-Info.plist`

---

## 3. Enable Firebase Services

### Authentication
1. Build → Authentication → Get started
2. Sign-in method → Phone → Enable

### Firestore Database
1. Build → Firestore Database → Create database
2. Choose **Production mode**
3. Select region: `asia-south1` (Mumbai)

Deploy security rules:
```bash
cd flutter
firebase deploy --only firestore:rules
```

### Cloud Messaging (Push Notifications)
1. Project Settings → Cloud Messaging
2. Copy **Server key** — add to backend as `FIREBASE_SERVER_KEY`
3. For iOS: upload APNs certificate

---

## 4. Generate Firebase Options

Install FlutterFire CLI and generate `firebase_options.dart`:

```bash
# Install CLI
dart pub global activate flutterfire_cli

# Generate (from flutter/ directory)
cd flutter
flutterfire configure \
  --project=fuelchain-guardian \
  --platforms=android,ios
```

This overwrites the stub `lib/firebase_options.dart` with real values.

---

## 5. Service Account for Backend

1. Project Settings → Service accounts
2. Generate new private key → Download JSON
3. Save as `secrets/firebase-service-account.json`
4. Set in `.env`: `FIREBASE_SERVICE_ACCOUNT_JSON=./secrets/firebase-service-account.json`

The backend uses this to write to Firestore (pump status, panic alerts).

---

## 6. Deploy Cloud Functions

```bash
cd flutter/functions
npm install
firebase deploy --only functions
```

Functions deployed:
- `syncPumpsToFirestore` — runs every 5 min
- `syncPanicAlertsToFirestore` — runs every 2 min
- `aggregateQueueReports` — triggered on new queue reports

---

## 7. Firestore Data Structure

```
firestore/
├── pump_status/
│   ├── PUMP0001/    { id, name, city, status, petrol_pct, diesel_pct, ... }
│   └── PUMP0002/    { ... }
├── panic_alerts/
│   ├── Mumbai/      { city, panic_index, message, issued_at }
│   └── Delhi/       { ... }
└── queue_reports/
    └── {reportId}/  { pumpId, userId, density, createdAt }
```

---

## 8. Test Locally with Emulators

```bash
cd flutter
firebase emulators:start --only auth,firestore,functions

# In another terminal — run the app against emulators
cd flutter
flutter run --dart-define=USE_FIREBASE_EMULATOR=true
```
