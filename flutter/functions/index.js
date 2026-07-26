/**
 * Firebase Cloud Functions
 * 
 * sync_pumps_to_firestore: Periodically calls the FuelChain backend API
 * and writes pump status + panic alerts to Firestore for the Flutter app.
 * 
 * Deploy:
 *   cd flutter/functions
 *   npm install
 *   firebase deploy --only functions
 */
const functions = require('firebase-functions')
const admin = require('firebase-admin')
const axios = require('axios')

admin.initializeApp()
const db = admin.firestore()

// TODO: Set this to your deployed backend URL
const BACKEND_URL = functions.config().backend?.url || 'http://your-backend:8000'

/**
 * Runs every 5 minutes — syncs pump statuses to Firestore.
 * Flutter app listens to these documents in real-time.
 */
exports.syncPumpsToFirestore = functions.pubsub
  .schedule('every 5 minutes')
  .onRun(async () => {
    try {
      const resp = await axios.get(`${BACKEND_URL}/api/v1/pumps`, { timeout: 10000 })
      const pumps = resp.data.pumps || []

      const batch = db.batch()
      for (const pump of pumps) {
        const ref = db.collection('pump_status').doc(pump.id)
        batch.set(ref, {
          ...pump,
          syncedAt: admin.firestore.FieldValue.serverTimestamp(),
        })
      }
      await batch.commit()
      console.log(`Synced ${pumps.length} pumps to Firestore`)
    } catch (err) {
      console.error('Failed to sync pumps:', err.message)
    }
  })

/**
 * Syncs panic alerts every 2 minutes.
 */
exports.syncPanicAlertsToFirestore = functions.pubsub
  .schedule('every 2 minutes')
  .onRun(async () => {
    const cities = [
      'Mumbai', 'Delhi', 'Bangalore', 'Chennai', 'Kolkata',
      'Hyderabad', 'Pune', 'Ahmedabad',
    ]

    const batch = db.batch()
    let updated = 0

    for (const city of cities) {
      try {
        const resp = await axios.get(
          `${BACKEND_URL}/api/v1/panic/${city}`,
          { timeout: 5000 }
        )
        const data = resp.data

        if (data.alert) {
          const ref = db.collection('panic_alerts').doc(city)
          batch.set(ref, {
            city,
            panic_index: data.panic_index,
            message: data.alert.message,
            issued_at: data.alert.issued_at,
            syncedAt: admin.firestore.FieldValue.serverTimestamp(),
          })
          updated++
        } else {
          // Clear stale alert
          const ref = db.collection('panic_alerts').doc(city)
          batch.delete(ref)
        }
      } catch (err) {
        console.warn(`Failed to sync panic for ${city}:`, err.message)
      }
    }

    await batch.commit()
    console.log(`Synced panic alerts for ${updated} cities`)
  })

/**
 * Aggregates queue reports from Firestore and writes back
 * the current average queue density per pump.
 */
exports.aggregateQueueReports = functions.firestore
  .document('queue_reports/{reportId}')
  .onCreate(async (snap) => {
    const report = snap.data()
    const pumpId = report.pumpId
    if (!pumpId) return

    // Count recent reports (last 15 min)
    const cutoff = new Date(Date.now() - 15 * 60 * 1000)
    const recent = await db.collection('queue_reports')
      .where('pumpId', '==', pumpId)
      .where('createdAt', '>=', cutoff)
      .get()

    if (recent.empty) return

    const densities = recent.docs.map(d => d.data().density).filter(Boolean)
    const avg = densities.reduce((a, b) => a + b, 0) / densities.length

    await db.collection('pump_status').doc(pumpId).update({
      queue_density: Math.round(avg),
      queue_report_count: densities.length,
      queue_updated_at: admin.firestore.FieldValue.serverTimestamp(),
    })
  })
