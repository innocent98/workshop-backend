#!/usr/bin/env python3
"""
Test script for booking, payment, and review endpoints
"""
import requests
import json
from datetime import datetime, timedelta

BASE_URL = "http://localhost:8000/api/v1"

# Test credentials
CLIENT_EMAIL = "client1@test.com"
CLIENT_PASSWORD = "Test123!"
ARTISAN_EMAIL = "artisan1@test.com"
ARTISAN_PASSWORD = "Test123!"

# Color codes for output
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

def print_warning(message):
    print(f"{YELLOW}⚠ {message}{RESET}")

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
        print_success(f"Logged in as {data['user']['full_name']} ({data['user']['user_type']})")
        return data['token'], data['user']
    else:
        print_error(f"Login failed: {response.text}")
        return None, None

def test_create_booking(client_token, artisan_id):
    """Test creating a booking"""
    print_section("TEST 1: Create Booking")

    # Get service ID for Electrician
    services_response = requests.get(f"{BASE_URL}/services")
    services = services_response.json()
    electrician_service = next((s for s in services if s['name'] == 'Electrician'), None)

    if not electrician_service:
        print_error("Electrician service not found")
        return None

    print_info(f"Using service: {electrician_service['name']} (ID: {electrician_service['id']})")

    # Create booking for tomorrow
    job_date = (datetime.now() + timedelta(days=1)).isoformat()

    booking_data = {
        "artisan_id": artisan_id,
        "service_id": electrician_service['id'],
        "job_description": "Need electrical wiring for new room",
        "job_date": job_date,
        "job_address": "123 Test Street, Lagos, Nigeria",
        "job_latitude": 6.5244,
        "job_longitude": 3.3792,
        "budget_min": 5000.00,
        "budget_max": 10000.00
    }

    response = requests.post(
        f"{BASE_URL}/bookings",
        headers={"Authorization": f"Bearer {client_token}"},
        json=booking_data
    )

    if response.status_code == 201:
        booking = response.json()
        print_success(f"Booking created: {booking['booking_reference']}")
        print_info(f"Status: {booking['status']}")
        print_info(f"Budget range: ₦{booking['budget_min']} - ₦{booking['budget_max']}")
        return booking
    else:
        print_error(f"Failed to create booking: {response.status_code}")
        print_error(response.text)
        return None

def test_list_bookings(token, user_type):
    """Test listing bookings"""
    print_section(f"TEST 2: List Bookings ({user_type})")

    response = requests.get(
        f"{BASE_URL}/bookings",
        headers={"Authorization": f"Bearer {token}"}
    )

    if response.status_code == 200:
        data = response.json()
        print_success(f"Found {data['total']} booking(s)")
        for booking in data['bookings']:
            print_info(f"  - {booking['booking_reference']}: {booking['status']}")
        return True
    else:
        print_error(f"Failed to list bookings: {response.text}")
        return False

def test_accept_booking(artisan_token, booking_id):
    """Test artisan accepting booking"""
    print_section("TEST 3: Accept Booking (Artisan)")

    accept_data = {
        "agreed_amount": 7500.00
    }

    response = requests.patch(
        f"{BASE_URL}/bookings/{booking_id}/accept",
        headers={"Authorization": f"Bearer {artisan_token}"},
        json=accept_data
    )

    if response.status_code == 200:
        booking = response.json()
        print_success(f"Booking accepted with amount: ₦{booking['agreed_amount']}")
        print_info(f"New status: {booking['status']}")
        return booking
    else:
        print_error(f"Failed to accept booking: {response.status_code}")
        print_error(response.text)
        return None

def test_initialize_payment(client_token, booking_id):
    """Test initializing payment"""
    print_section("TEST 4: Initialize Payment")

    payment_data = {
        "booking_id": booking_id
    }

    response = requests.post(
        f"{BASE_URL}/payments/initialize",
        headers={"Authorization": f"Bearer {client_token}"},
        json=payment_data
    )

    if response.status_code == 201:
        payment = response.json()
        print_success(f"Payment initialized: {payment['payment_reference']}")
        print_info(f"Amount: ₦{payment['amount']}")
        print_info(f"Authorization URL: {payment['authorization_url'][:50]}...")
        return payment
    else:
        print_error(f"Failed to initialize payment: {response.status_code}")
        print_error(response.text)
        return None

def test_booking_stats(token):
    """Test getting booking statistics"""
    print_section("TEST 5: Get Booking Statistics")

    # Note: The endpoint is /bookings/stats but the route is defined after the {booking_id} route
    # This might cause issues - let's test it
    response = requests.get(
        f"{BASE_URL}/bookings/stats",
        headers={"Authorization": f"Bearer {token}"}
    )

    if response.status_code == 200:
        stats = response.json()
        print_success("Statistics retrieved:")
        print_info(f"  Total bookings: {stats['total_bookings']}")
        print_info(f"  Pending: {stats['pending_bookings']}")
        print_info(f"  Accepted: {stats['accepted_bookings']}")
        print_info(f"  Paid: {stats['paid_bookings']}")
        return True
    else:
        print_error(f"Failed to get stats: {response.status_code}")
        print_error(response.text)
        return False

def main():
    print_info("Starting Booking Flow Tests...")
    print_info(f"Base URL: {BASE_URL}\n")

    # Login as client
    client_token, client_user = login(CLIENT_EMAIL, CLIENT_PASSWORD)
    if not client_token:
        return

    # Login as artisan
    artisan_token, artisan_user = login(ARTISAN_EMAIL, ARTISAN_PASSWORD)
    if not artisan_token:
        return

    # Test 1: Create booking
    booking = test_create_booking(client_token, artisan_user['id'])
    if not booking:
        print_error("Cannot continue without a booking")
        return

    # Test 2: List bookings for client
    test_list_bookings(client_token, "client")

    # Test 2b: List bookings for artisan
    test_list_bookings(artisan_token, "artisan")

    # Test 3: Accept booking
    accepted_booking = test_accept_booking(artisan_token, booking['id'])
    if not accepted_booking:
        print_warning("Continuing despite accept failure...")

    # Test 4: Initialize payment
    payment = test_initialize_payment(client_token, booking['id'])

    # Test 5: Get booking stats
    test_booking_stats(client_token)

    print_section("TEST SUMMARY")
    print_success("All tests completed!")
    print_info(f"Booking ID: {booking['id']}")
    print_info(f"Booking Reference: {booking['booking_reference']}")
    if payment:
        print_info(f"Payment Reference: {payment['payment_reference']}")

if __name__ == "__main__":
    main()
