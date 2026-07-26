// test/widget_test.dart
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

// Model tests — no Firebase needed
import 'package:pumpcast/models/pump_model.dart';

void main() {
  group('PumpModel', () {
    test('parses GeoJSON feature correctly', () {
      final json = {
        'type': 'Feature',
        'geometry': {
          'type': 'Point',
          'coordinates': [72.877, 19.076],
        },
        'properties': {
          'id': 'PUMP0001',
          'name': 'Mumbai Pump 1',
          'city': 'Mumbai',
          'state': 'Maharashtra',
          'status': 'YELLOW',
          'petrol_pct': 42.5,
          'diesel_pct': 67.2,
          'hours_to_empty_petrol': 18.5,
          'panic_multiplier': 1.3,
          'queue_density': 2,
        },
      };

      final pump = PumpModel.fromJson(json);
      expect(pump.id, 'PUMP0001');
      expect(pump.name, 'Mumbai Pump 1');
      expect(pump.lat, closeTo(19.076, 0.001));
      expect(pump.lon, closeTo(72.877, 0.001));
      expect(pump.status, 'YELLOW');
      expect(pump.petrolPct, 42.5);
      expect(pump.panicMultiplier, 1.3);
    });

    test('parses flat JSON (Redis format) correctly', () {
      final json = {
        'id': 'PUMP0002',
        'name': 'Delhi Pump',
        'city': 'Delhi',
        'lat': 28.704,
        'lon': 77.102,
        'status': 'RED',
        'petrol_pct': 8.0,
        'diesel_pct': 12.0,
      };

      final pump = PumpModel.fromJson(json);
      expect(pump.status, 'RED');
      expect(pump.lat, 28.704);
    });

    test('statusLabel returns correct string for RED', () {
      final pump = PumpModel(
        id: 'P1', name: 'Test', city: 'Mumbai',
        lat: 0, lon: 0, status: 'RED',
      );
      expect(pump.statusLabel, contains('Critical'));
    });

    test('statusLabel returns correct string for GREEN', () {
      final pump = PumpModel(
        id: 'P1', name: 'Test', city: 'Mumbai',
        lat: 0, lon: 0, status: 'GREEN',
      );
      expect(pump.statusLabel, contains('Available'));
    });

    test('queueLabel maps densities correctly', () {
      final pumps = [1, 2, 3, 4].map((d) => PumpModel(
        id: 'P', name: 'T', city: 'C', lat: 0, lon: 0,
        status: 'GREEN', queueDensity: d,
      )).toList();

      expect(pumps[0].queueLabel, 'No queue');
      expect(pumps[1].queueLabel, '1–5 cars');
      expect(pumps[2].queueLabel, '5–15 cars');
      expect(pumps[3].queueLabel, '15+ cars');
    });
  });
}
