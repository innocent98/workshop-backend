#!/usr/bin/env python3
"""
Comprehensive test script for all booking, payment, and review endpoints
"""
import requests
import json
from datetime import datetime, timedelta

BASE_URL = "http://localhost:8000/api/v1"

# Test credentials
CLIENT_EMAIL = "client2@test.com"
CLIENT_PASSWORD = "Test123!"
ARTISAN_EMAIL = "artisan2@test.com"
ARTISAN_PASSWORD = "Test123!"

# Color codes
GREEN = '\033[92m'
RED = '\033[91m'
YELLOW = '\033[93m'
BLUE = '\033[94m'
RESET = '\033[0m'

def print_success(message):
    print(f"{GREEN}✓ {message}{RESET}")

def print_error(message):
    print(f"{RED}✗ {message}{RESET}")

def print_info(message):
    print(f"{BLUE}ℹ {message}{RESET}")

def print_section(title):
    print(f"\n{'='*60}")
    print(f"{BLUE}{title}{RESET}")
    print('='*60)

def login(email, password):
    """Login and return access token"""
    response = requests.post(
        f"{BASE_URL}/auth/login",
        json={"email": email, "password": password}
    )
    if response.status_code == 200:
        data = response.json()
        return data['token'], data['user']
    return None, None

def main():
    print_info("Starting Comprehensive Endpoint Tests...")
    print_info(f"Base URL: {BASE_URL}\n")

    # Login
    client_token, client_user = login(CLIENT_EMAIL, CLIENT_PASSWORD)
    artisan_token, artisan_user = login(ARTISAN_EMAIL, ARTISAN_PASSWORD)

    if not client_token or not artisan_token:
        print_error("Login failed")
        return

    print_success(f"Logged in as {client_user['full_name']} (client)")
    print_success(f"Logged in as {artisan_user['full_name']} (artisan)")

    # Get service ID
    services = requests.get(f"{BASE_URL}/services").json()
    plumbing_service = next((s for s in services if s['name'] == 'Plumbing'), None)

    if not plumbing_service:
        print_error("Service not found")
        return

    service_id = plumbing_service['id']

    # =================================================================
    # TEST 1: Create Booking
    # =================================================================
    print_section("TEST 1: Create Booking")

    booking_data = {
        "artisan_id": artisan_user['id'],
        "service_id": service_id,
        "job_description": "Fix leaking pipe in bathroom",
        "job_date": (datetime.now() + timedelta(days=2)).isoformat(),
        "job_address": "456 Test Avenue, Lagos, Nigeria",
        "job_latitude": 6.5244,
        "job_longitude": 3.3792,
        "budget_min": 8000.00,
        "budget_max": 15000.00
    }

    response = requests.post(
        f"{BASE_URL}/bookings",
        headers={"Authorization": f"Bearer {client_token}"},
        json=booking_data
    )

    if response.status_code != 201:
        print_error(f"Create booking failed: {response.text}")
        return

    booking = response.json()
    booking_id = booking['id']
    print_success(f"Booking created: {booking['booking_reference']}")

    # =================================================================
    # TEST 2: Get Single Booking
    # =================================================================
    print_section("TEST 2: Get Single Booking")

    response = requests.get(
        f"{BASE_URL}/bookings/{booking_id}",
        headers={"Authorization": f"Bearer {client_token}"}
    )

    if response.status_code == 200:
        booking_detail = response.json()
        print_success(f"Retrieved booking: {booking_detail['booking_reference']}")
        print_info(f"Status: {booking_detail['status']}")
    else:
        print_error(f"Failed: {response.text}")

    # =================================================================
    # TEST 3: Reject Booking Test (Create another booking to reject)
    # =================================================================
    print_section("TEST 3: Reject Booking")

    # Create another booking
    reject_booking_data = booking_data.copy()
    reject_booking_data['job_description'] = "This booking will be rejected"

    response = requests.post(
        f"{BASE_URL}/bookings",
        headers={"Authorization": f"Bearer {client_token}"},
        json=reject_booking_data
    )

    if response.status_code == 201:
        reject_booking = response.json()
        reject_booking_id = reject_booking['id']

        # Artisan rejects it
        response = requests.patch(
            f"{BASE_URL}/bookings/{reject_booking_id}/reject",
            headers={"Authorization": f"Bearer {artisan_token}"},
            json={"rejection_reason": "Schedule conflict, not available on this date"}
        )

        if response.status_code == 200:
            rejected = response.json()
            print_success(f"Booking rejected: {rejected['status']}")
            print_info(f"Reason: {rejected['rejection_reason'][:50]}...")
        else:
            print_error(f"Reject failed: {response.text}")

    # =================================================================
    # TEST 4: Accept Booking
    # =================================================================
    print_section("TEST 4: Accept Booking")

    response = requests.patch(
        f"{BASE_URL}/bookings/{booking_id}/accept",
        headers={"Authorization": f"Bearer {artisan_token}"},
        json={"agreed_amount": 12000.00}
    )

    if response.status_code == 200:
        accepted = response.json()
        print_success(f"Booking accepted: ₦{accepted['agreed_amount']}")
        print_info(f"Status: {accepted['status']}")
    else:
        print_error(f"Accept failed: {response.text}")
        return

    # =================================================================
    # TEST 5: Cancel Booking Test (Create another to cancel)
    # =================================================================
    print_section("TEST 5: Cancel Booking")

    cancel_booking_data = booking_data.copy()
    cancel_booking_data['job_description'] = "This booking will be cancelled"

    response = requests.post(
        f"{BASE_URL}/bookings",
        headers={"Authorization": f"Bearer {client_token}"},
        json=cancel_booking_data
    )

    if response.status_code == 201:
        cancel_booking = response.json()
        cancel_booking_id = cancel_booking['id']

        # Customer cancels it
        response = requests.patch(
            f"{BASE_URL}/bookings/{cancel_booking_id}/cancel",
            headers={"Authorization": f"Bearer {client_token}"},
            json={"cancellation_reason": "Changed my mind, will book later"}
        )

        if response.status_code == 200:
            cancelled = response.json()
            print_success(f"Booking cancelled: {cancelled['status']}")
            print_info(f"Reason: {cancelled['cancellation_reason'][:50]}...")
        else:
            print_error(f"Cancel failed: {response.text}")

    # =================================================================
    # TEST 6: Initialize Payment
    # =================================================================
    print_section("TEST 6: Initialize Payment")

    response = requests.post(
        f"{BASE_URL}/payments/initialize",
        headers={"Authorization": f"Bearer {client_token}"},
        json={"booking_id": booking_id}
    )

    if response.status_code != 201:
        print_error(f"Payment init failed: {response.text}")
        return

    payment = response.json()
    payment_id = payment['id']
    payment_reference = payment['payment_reference']
    print_success(f"Payment initialized: {payment_reference}")
    print_info(f"Authorization URL: {payment['authorization_url'][:60]}...")

    # =================================================================
    # TEST 7: Get Payment Details
    # =================================================================
    print_section("TEST 7: Get Payment Details")

    response = requests.get(
        f"{BASE_URL}/payments/{payment_id}",
        headers={"Authorization": f"Bearer {client_token}"}
    )

    if response.status_code == 200:
        payment_detail = response.json()
        print_success(f"Payment details retrieved: {payment_detail['payment_reference']}")
        print_info(f"Amount: ₦{payment_detail['amount']}")
        print_info(f"Status: {payment_detail['status']}")
    else:
        print_error(f"Failed: {response.text}")

    # =================================================================
    # TEST 8: Verify Payment (will be pending since not actually paid)
    # =================================================================
    print_section("TEST 8: Verify Payment")

    response = requests.get(
        f"{BASE_URL}/payments/verify/{payment_reference}",
        headers={"Authorization": f"Bearer {client_token}"}
    )

    if response.status_code == 200:
        verification = response.json()
        print_success(f"Payment verified")
        print_info(f"Status: {verification['status']}")
        print_info(f"Paid: {verification['paid']}")
    else:
        print_error(f"Verification failed: {response.text}")

    # =================================================================
    # TEST 9: Simulate Payment Success (Update booking to PAID manually for testing)
    # =================================================================
    print_section("TEST 9: Simulating Payment Success")

    # We'll manually update the booking to PAID status for testing
    # In real scenario, this would happen via Paystack webhook
    print_info("In production, this happens via Paystack webhook")
    print_info("Manually updating for testing purposes...")

    # Use docker to update booking status directly in DB
    import subprocess
    try:
        subprocess.run([
            "docker", "exec", "workchop-api_db",
            "psql", "-U", "user", "-d", "workchop_db", "-c",
            f"UPDATE bookings SET status='paid', paid_at=NOW() WHERE id={booking_id}; UPDATE payments SET status='success', paid_at=NOW() WHERE booking_id={booking_id};"
        ], check=True, capture_output=True)
        print_success("Booking marked as PAID for testing")
    except:
        print_error("Could not update DB directly, skipping rest of flow tests")
        return

    # =================================================================
    # TEST 10: Start Booking
    # =================================================================
    print_section("TEST 10: Start Booking")

    response = requests.patch(
        f"{BASE_URL}/bookings/{booking_id}/start",
        headers={"Authorization": f"Bearer {artisan_token}"}
    )

    if response.status_code == 200:
        started = response.json()
        print_success(f"Booking started: {started['status']}")
        print_info(f"Started at: {started['started_at'][:19]}")
    else:
        print_error(f"Start failed: {response.text}")

    # =================================================================
    # TEST 11: Complete Booking
    # =================================================================
    print_section("TEST 11: Complete Booking")

    response = requests.patch(
        f"{BASE_URL}/bookings/{booking_id}/complete",
        headers={"Authorization": f"Bearer {artisan_token}"},
        json={
            "completion_notes": "Fixed the leaking pipe and replaced worn gaskets. All working properly now.",
            "completion_images": [
                "https://res.cloudinary.com/demo/image/upload/sample.jpg"
            ]
        }
    )

    if response.status_code == 200:
        completed = response.json()
        print_success(f"Booking completed: {completed['status']}")
        print_info(f"Completed at: {completed['completed_at'][:19]}")
        print_info(f"Images: {len(completed['completion_images'])} uploaded")
    else:
        print_error(f"Complete failed: {response.text}")

    # =================================================================
    # TEST 12: Create Review
    # =================================================================
    print_section("TEST 12: Create Review")

    response = requests.post(
        f"{BASE_URL}/reviews",
        headers={"Authorization": f"Bearer {client_token}"},
        json={
            "booking_id": booking_id,
            "rating": 4.5,
            "review_text": "Great service! Very professional and fixed the issue quickly.",
            "is_anonymous": False
        }
    )

    if response.status_code == 201:
        review = response.json()
        review_id = review['id']
        print_success(f"Review created: {review['rating']} stars")
        print_info(f"Review text: {review['review_text'][:50]}...")
    else:
        print_error(f"Review creation failed: {response.text}")
        review_id = None

    # =================================================================
    # TEST 13: Get Artisan Reviews
    # =================================================================
    print_section("TEST 13: Get Artisan Reviews")

    response = requests.get(
        f"{BASE_URL}/reviews/artisan/{artisan_user['id']}"
    )

    if response.status_code == 200:
        reviews_data = response.json()
        print_success(f"Found {reviews_data['total']} review(s)")
        print_info(f"Average rating: {reviews_data['average_rating']:.1f}")
    else:
        print_error(f"Failed: {response.text}")

    # =================================================================
    # TEST 14: Get Review for Booking
    # =================================================================
    print_section("TEST 14: Get Review for Booking")

    response = requests.get(
        f"{BASE_URL}/reviews/booking/{booking_id}",
        headers={"Authorization": f"Bearer {client_token}"}
    )

    if response.status_code == 200:
        booking_review = response.json()
        print_success(f"Review retrieved: {booking_review['rating']} stars")
    else:
        print_error(f"Failed: {response.text}")

    # =================================================================
    # TEST 15: Artisan Responds to Review
    # =================================================================
    if review_id:
        print_section("TEST 15: Artisan Responds to Review")

        response = requests.patch(
            f"{BASE_URL}/reviews/{review_id}/respond",
            headers={"Authorization": f"Bearer {artisan_token}"},
            json={
                "artisan_response": "Thank you for the kind words! It was a pleasure working with you."
            }
        )

        if response.status_code == 200:
            responded = response.json()
            print_success(f"Response added")
            print_info(f"Response: {responded['artisan_response'][:50]}...")
        else:
            print_error(f"Response failed: {response.text}")

    # =================================================================
    # TEST 16: Get Artisan Review Stats
    # =================================================================
    print_section("TEST 16: Get Artisan Review Stats")

    response = requests.get(
        f"{BASE_URL}/reviews/artisan/{artisan_user['id']}/stats"
    )

    if response.status_code == 200:
        stats = response.json()
        print_success(f"Stats retrieved")
        print_info(f"Total reviews: {stats['total_reviews']}")
        print_info(f"Average rating: {stats['average_rating']:.2f}")
        print_info(f"Jobs completed: {stats['total_jobs_completed']}")
    else:
        print_error(f"Failed: {response.text}")

    # =================================================================
    # SUMMARY
    # =================================================================
    print_section("TEST SUMMARY")
    print_success("All endpoint tests completed!")
    print_info(f"Main Booking ID: {booking_id}")
    print_info(f"Booking Reference: {booking['booking_reference']}")
    print_info(f"Payment Reference: {payment_reference}")
    if review_id:
        print_info(f"Review ID: {review_id}")

if __name__ == "__main__":
    main()
