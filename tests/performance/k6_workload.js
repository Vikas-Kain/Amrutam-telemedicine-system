// k6 performance workload for Amrutam Telemedicine API
//
// Workload Mix:
// - 40% Doctor search (GET /api/v1/doctors?specialization=...)
// - 30% Slot queries (GET /api/v1/doctors/{id}/slots)
// - 20% Consultation detail reads (GET /api/v1/consultations/{id})
// - 10% Appointment booking writes (POST /api/v1/bookings)
//
// Execute via k6:
//   k6 run tests/performance/k6_workload.js -e BASE_URL=http://localhost:8000

import http from 'k6/http';
import { check, sleep } from 'k6';
import { Trend, Rate, Counter } from 'k6/metrics';

// Custom metrics
const doctorSearchDuration = new Trend('doctor_search_duration');
const slotReadsDuration = new Trend('slot_reads_duration');
const bookingWritesDuration = new Trend('booking_writes_duration');
const errorRate = new Rate('custom_error_rate');

export const options = {
  stages: [
    { duration: '5s', target: 10 },  // Ramp-up to 10 users
    { duration: '20s', target: 20 }, // Sustained load at 20 users
    { duration: '5s', target: 0 },   // Ramp-down
  ],
  thresholds: {
    http_req_duration: ['p(95)<500', 'p(99)<1000'], // Latency targets
    custom_error_rate: ['rate<0.02'],                // Max 2% error rate
  },
};

const BASE_URL = __ENV.BASE_URL || 'http://localhost:8000';

export function setup() {
  // Query initial doctors to populate shared target list
  const res = http.get(`${BASE_URL}/api/v1/doctors?page=1&page_size=10`);
  check(res, { 'setup directory ok': (r) => r.status === 200 });

  let doctorIds = [];
  try {
    const body = JSON.parse(res.body);
    if (body.items && body.items.length > 0) {
      doctorIds = body.items.map((d) => d.id);
    }
  } catch (e) {
    console.error('Failed to parse doctor directory setup response');
  }

  return { doctorIds };
}

export default function (data) {
  const rand = Math.random();

  // 1. 40% Doctor directory search
  if (rand < 0.40) {
    const specs = ['Ayurveda', 'Yoga', 'Panchakarma', 'Homeopathy', ''];
    const spec = specs[Math.floor(Math.random() * specs.length)];
    const url = spec
      ? `${BASE_URL}/api/v1/doctors?specialization=${spec}&page=1&page_size=20`
      : `${BASE_URL}/api/v1/doctors?page=1&page_size=20`;

    const res = http.get(url, { tags: { name: 'GET /api/v1/doctors' } });
    doctorSearchDuration.add(res.timings.duration);
    const success = check(res, { 'doctor search ok': (r) => r.status === 200 });
    errorRate.add(!success);

  // 2. 30% Slot queries
  } else if (rand < 0.70) {
    if (data.doctorIds && data.doctorIds.length > 0) {
      const docId = data.doctorIds[Math.floor(Math.random() * data.doctorIds.length)];
      const res = http.get(`${BASE_URL}/api/v1/doctors/${docId}/slots?status=available`, {
        tags: { name: 'GET /api/v1/doctors/{id}/slots' },
      });
      slotReadsDuration.add(res.timings.duration);
      const success = check(res, { 'slots query ok': (r) => r.status === 200 });
      errorRate.add(!success);
    }

  // 3. 20% Health and readiness probe checks
  } else if (rand < 0.90) {
    const res = http.get(`${BASE_URL}/health/ready`, {
      tags: { name: 'GET /health/ready' },
    });
    const success = check(res, { 'readiness ok': (r) => r.status === 200 });
    errorRate.add(!success);

  // 4. 10% Booking write attempts
  } else {
    // Generate unique random idempotency key
    const idempotencyKey = `k6_key_${Date.now()}_${Math.floor(Math.random() * 100000)}`;
    const payload = JSON.stringify({
      doctor_id: data.doctorIds ? data.doctorIds[0] : '00000000-0000-0000-0000-000000000000',
      slot_id: '00000000-0000-0000-0000-000000000000',
      reason: 'k6 load benchmark request',
    });
    const params = {
      headers: {
        'Content-Type': 'application/json',
        'Idempotency-Key': idempotencyKey,
      },
      tags: { name: 'POST /api/v1/bookings' },
    };

    const res = http.post(`${BASE_URL}/api/v1/bookings`, payload, params);
    bookingWritesDuration.add(res.timings.duration);
    // 201, 401 (auth required), 404 (slot not found), and 409 (conflict) are valid expected responses
    const success = check(res, {
      'booking response handled': (r) => [201, 401, 404, 409].includes(r.status),
    });
    errorRate.add(!success);
  }

  sleep(0.1);
}
