#!/usr/bin/env python3
"""
Comprehensive system test for all booking, payment, review, and wallet endpoints
"""
import requests
import subprocess
from datetime import datetime, timedelta

BASE_URL = "http://localhost:8000/api/v1"

# Test credentials
CLIENT_EMAIL = "client3@test.com"
CLIENT_PASSWORD = "Test123!"
ARTISAN_EMAIL = "artisan3@test.com"
ARTISAN_PASSWORD = "Test123!"

# Color codes
GREEN = '\033[92m'
RED = '\033[91m'
YELLOW = '\033[93m'
BLUE = '\033[94m'
CYAN = '\033[96m'
RESET = '\033[0m'

test_results = {"passed": 0, "failed": 0, "errors": []}

def print_success(message):
    print(f"{GREEN}✓ {message}{RESET}")
    test_results["passed"] += 1

def print_error(message):
    print(f"{RED}✗ {message}{RESET}")
    test_results["failed"] += 1
    test_results["errors"].append(message)

def print_info(message):
    print(f"{BLUE}ℹ {message}{RESET}")

def print_warning(message):
    print(f"{YELLOW}⚠ {message}{RESET}")

def print_section(title):
    print(f"\n{'='*70}")
    print(f"{CYAN}{title}{RESET}")
    print('='*70)

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

def test_endpoint(name, method, url, headers=None, json=None, expected_status=200):
    """Generic endpoint tester"""
    try:
        if method.upper() == "GET":
            response = requests.get(url, headers=headers)
        elif method.upper() == "POST":
            response = requests.post(url, headers=headers, json=json)
        elif method.upper() == "PATCH":
            response = requests.patch(url, headers=headers, json=json)
        else:
            print_error(f"{name}: Unsupported method {method}")
            return None

        if response.status_code == expected_status:
            print_success(f"{name} - Status {response.status_code}")
            return response.json() if response.content else None
        else:
            print_error(f"{name} - Expected {expected_status}, got {response.status_code}")
            print(f"  Response: {response.text[:100]}")
            return None
    except Exception as e:
        print_error(f"{name} - Exception: {str(e)}")
        return None

def main():
    print_info("Starting Comprehensive System Test...")
    print_info(f"Base URL: {BASE_URL}\n")

    # ====================================================================
    # SETUP: Login
    # ====================================================================
    print_section("SETUP: Authentication")

    client_token, client_user = login(CLIENT_EMAIL, CLIENT_PASSWORD)
    if not client_token:
        print_error("Client login failed - cannot continue")
        return
    print_success(f"Client logged in: {client_user['full_name']}")

    artisan_token, artisan_user = login(ARTISAN_EMAIL, ARTISAN_PASSWORD)
    if not artisan_token:
        print_error("Artisan login failed - cannot continue")
        return
    print_success(f"Artisan logged in: {artisan_user['full_name']}")

    # Get service
    services = requests.get(f"{BASE_URL}/services").json()
    service = next((s for s in services if 'Carpentry' in s['name']), services[0])
    service_id = service['id']
    print_info(f"Using service: {service['name']} (ID: {service_id})")

    # ====================================================================
    # BOOKING MODULE TESTS
    # ====================================================================
    print_section("MODULE 1: BOOKING OPERATIONS")

    # Test 1: Create Booking
    booking_data = {
        "artisan_id": artisan_user['id'],
        "service_id": service_id,
        "job_description": "Build custom wooden shelves",
        "job_date": (datetime.now() + timedelta(days=3)).isoformat(),
        "job_address": "789 Carpenter Lane, Lagos, Nigeria",
        "job_latitude": 6.5244,
        "job_longitude": 3.3792,
        "budget_min": 10000.00,
        "budget_max": 20000.00
    }

    booking = test_endpoint(
        "Create Booking",
        "POST",
        f"{BASE_URL}/bookings",
        headers={"Authorization": f"Bearer {client_token}"},
        json=booking_data,
        expected_status=201
    )

    if not booking:
        print_error("Cannot continue without booking")
        return

    booking_id = booking['id']
    print_info(f"  Booking ID: {booking_id}, Reference: {booking['booking_reference']}")

    # Test 2: Get Single Booking
    test_endpoint(
        "Get Booking Details",
        "GET",
        f"{BASE_URL}/bookings/{booking_id}",
        headers={"Authorization": f"Bearer {client_token}"}
    )

    # Test 3: List Bookings (Client)
    bookings_list = test_endpoint(
        "List Bookings (Client)",
        "GET",
        f"{BASE_URL}/bookings",
        headers={"Authorization": f"Bearer {client_token}"}
    )
    if bookings_list:
        print_info(f"  Found {bookings_list['total']} booking(s)")

    # Test 4: List Bookings (Artisan)
    test_endpoint(
        "List Bookings (Artisan)",
        "GET",
        f"{BASE_URL}/bookings",
        headers={"Authorization": f"Bearer {artisan_token}"}
    )

    # Test 5: Get Booking Stats
    stats = test_endpoint(
        "Get Booking Stats",
        "GET",
        f"{BASE_URL}/bookings/stats",
        headers={"Authorization": f"Bearer {client_token}"}
    )
    if stats:
        print_info(f"  Total: {stats['total_bookings']}, Pending: {stats['pending_bookings']}")

    # Test 6: Accept Booking
    accept_data = {"agreed_amount": 15000.00}
    accepted_booking = test_endpoint(
        "Accept Booking",
        "PATCH",
        f"{BASE_URL}/bookings/{booking_id}/accept",
        headers={"Authorization": f"Bearer {artisan_token}"},
        json=accept_data
    )

    if accepted_booking:
        print_info(f"  Agreed Amount: ₦{accepted_booking['agreed_amount']}")

    # ====================================================================
    # PAYMENT MODULE TESTS
    # ====================================================================
    print_section("MODULE 2: PAYMENT OPERATIONS")

    # Test 7: Initialize Payment
    payment_data = {"booking_id": booking_id}
    payment = test_endpoint(
        "Initialize Payment",
        "POST",
        f"{BASE_URL}/payments/initialize",
        headers={"Authorization": f"Bearer {client_token}"},
        json=payment_data,
        expected_status=201
    )

    if not payment:
        print_warning("Payment initialization failed - skipping payment tests")
        payment_id = None
        payment_reference = None
    else:
        payment_id = payment['id']
        payment_reference = payment['payment_reference']
        print_info(f"  Payment ID: {payment_id}, Reference: {payment_reference}")
        print_info(f"  Authorization URL: {payment['authorization_url'][:50]}...")

        # Test 8: Get Payment Details
        test_endpoint(
            "Get Payment Details",
            "GET",
            f"{BASE_URL}/payments/{payment_id}",
            headers={"Authorization": f"Bearer {client_token}"}
        )

        # Test 9: Verify Payment
        test_endpoint(
            "Verify Payment",
            "GET",
            f"{BASE_URL}/payments/verify/{payment_reference}",
            headers={"Authorization": f"Bearer {client_token}"}
        )

    # ====================================================================
    # SIMULATE PAYMENT SUCCESS
    # ====================================================================
    print_section("SETUP: Simulate Payment Success")

    try:
        subprocess.run([
            "docker", "exec", "workchop-api_db",
            "psql", "-U", "user", "-d", "workchop_db", "-c",
            f"UPDATE bookings SET status='paid', paid_at=NOW() WHERE id={booking_id}; UPDATE payments SET status='success', paid_at=NOW() WHERE booking_id={booking_id};"
        ], check=True, capture_output=True)
        print_success("Booking marked as PAID")
    except:
        print_warning("Could not simulate payment - continuing anyway")

    # Test 10: Start Booking
    test_endpoint(
        "Start Booking",
        "PATCH",
        f"{BASE_URL}/bookings/{booking_id}/start",
        headers={"Authorization": f"Bearer {artisan_token}"}
    )

    # Test 11: Complete Booking
    complete_data = {
        "completion_notes": "Shelves built and installed successfully",
        "completion_images": ["https://res.cloudinary.com/demo/image/upload/sample.jpg"]
    }
    test_endpoint(
        "Complete Booking",
        "PATCH",
        f"{BASE_URL}/bookings/{booking_id}/complete",
        headers={"Authorization": f"Bearer {artisan_token}"},
        json=complete_data
    )

    # ====================================================================
    # REVIEW MODULE TESTS
    # ====================================================================
    print_section("MODULE 3: REVIEW OPERATIONS")

    # Test 12: Create Review
    review_data = {
        "booking_id": booking_id,
        "rating": 5.0,
        "review_text": "Amazing craftsmanship! Very professional and detail-oriented.",
        "is_anonymous": False
    }
    review = test_endpoint(
        "Create Review",
        "POST",
        f"{BASE_URL}/reviews",
        headers={"Authorization": f"Bearer {client_token}"},
        json=review_data,
        expected_status=201
    )

    review_id = review['id'] if review else None
    if review:
        print_info(f"  Review ID: {review_id}, Rating: {review['rating']} stars")

    # Test 13: Get Review for Booking
    test_endpoint(
        "Get Review for Booking",
        "GET",
        f"{BASE_URL}/reviews/booking/{booking_id}",
        headers={"Authorization": f"Bearer {client_token}"}
    )

    # Test 14: Get Artisan Reviews
    reviews_list = test_endpoint(
        "Get Artisan Reviews",
        "GET",
        f"{BASE_URL}/reviews/artisan/{artisan_user['id']}"
    )
    if reviews_list:
        print_info(f"  Total Reviews: {reviews_list['total']}, Avg Rating: {reviews_list['average_rating']:.1f}")

    # Test 15: Get Artisan Review Stats
    test_endpoint(
        "Get Artisan Review Stats",
        "GET",
        f"{BASE_URL}/reviews/artisan/{artisan_user['id']}/stats"
    )

    # Test 16: Artisan Responds to Review
    if review_id:
        response_data = {
            "artisan_response": "Thank you! It was a pleasure working on your project."
        }
        test_endpoint(
            "Respond to Review",
            "PATCH",
            f"{BASE_URL}/reviews/{review_id}/respond",
            headers={"Authorization": f"Bearer {artisan_token}"},
            json=response_data
        )

    # ====================================================================
    # WALLET MODULE TESTS
    # ====================================================================
    print_section("MODULE 4: WALLET OPERATIONS")

    # Test 17: Get Wallet Balance
    balance = test_endpoint(
        "Get Wallet Balance",
        "GET",
        f"{BASE_URL}/wallet/balance",
        headers={"Authorization": f"Bearer {artisan_token}"}
    )
    if balance:
        print_info(f"  Total Earned: ₦{balance['total_earned']}")
        print_info(f"  Pending Release: ₦{balance['pending_release']}")
        print_info(f"  Jobs Completed: {balance['total_jobs_completed']}")

    # Test 18: Get Earnings History
    earnings = test_endpoint(
        "Get Earnings History",
        "GET",
        f"{BASE_URL}/wallet/earnings",
        headers={"Authorization": f"Bearer {artisan_token}"}
    )
    if earnings:
        print_info(f"  Total Earnings: {earnings['total']}")
        print_info(f"  Summary Amount: ₦{earnings['summary']['total_amount']}")

    # Test 19: Get Payout History
    payouts = test_endpoint(
        "Get Payout History",
        "GET",
        f"{BASE_URL}/wallet/payouts",
        headers={"Authorization": f"Bearer {artisan_token}"}
    )
    if payouts:
        print_info(f"  Total Payouts: {payouts['total']}")

    # Test 20: Get Wallet Stats
    stats = test_endpoint(
        "Get Wallet Stats",
        "GET",
        f"{BASE_URL}/wallet/stats",
        headers={"Authorization": f"Bearer {artisan_token}"}
    )
    if stats:
        print_info(f"  Average Job Value: ₦{stats['average_job_value']}")
        print_info(f"  Total Transactions: {stats['total_transactions']}")

    # Test 21: Customer Cannot Access Wallet
    wallet_fail = requests.get(
        f"{BASE_URL}/wallet/balance",
        headers={"Authorization": f"Bearer {client_token}"}
    )
    if wallet_fail.status_code == 403:
        print_success("Customer Blocked from Wallet - Status 403")
        test_results["passed"] += 1
    else:
        print_error(f"Customer Access Not Blocked - Status {wallet_fail.status_code}")

    # ====================================================================
    # EDGE CASES & VALIDATION TESTS
    # ====================================================================
    print_section("MODULE 5: EDGE CASES & VALIDATION")

    # Test 22: Reject Booking (Create new one)
    new_booking_data = booking_data.copy()
    new_booking_data['job_description'] = "This will be rejected"
    new_booking = requests.post(
        f"{BASE_URL}/bookings",
        headers={"Authorization": f"Bearer {client_token}"},
        json=new_booking_data
    ).json()

    reject_data = {"rejection_reason": "Schedule is fully booked for that week"}
    reject_response = requests.patch(
        f"{BASE_URL}/bookings/{new_booking['id']}/reject",
        headers={"Authorization": f"Bearer {artisan_token}"},
        json=reject_data
    )
    if reject_response.status_code == 200:
        print_success("Reject Booking - Status 200")
        test_results["passed"] += 1
    else:
        print_error(f"Reject Booking Failed - Status {reject_response.status_code}")

    # Test 23: Cancel Booking (Create new one)
    cancel_booking_data = booking_data.copy()
    cancel_booking_data['job_description'] = "This will be cancelled"
    cancel_booking = requests.post(
        f"{BASE_URL}/bookings",
        headers={"Authorization": f"Bearer {client_token}"},
        json=cancel_booking_data
    ).json()

    cancel_data = {"cancellation_reason": "Found another artisan closer to me"}
    cancel_response = requests.patch(
        f"{BASE_URL}/bookings/{cancel_booking['id']}/cancel",
        headers={"Authorization": f"Bearer {client_token}"},
        json=cancel_data
    )
    if cancel_response.status_code == 200:
        print_success("Cancel Booking - Status 200")
        test_results["passed"] += 1
    else:
        print_error(f"Cancel Booking Failed - Status {cancel_response.status_code}")

    # Test 24: Invalid Budget Range
    invalid_booking = booking_data.copy()
    invalid_booking['budget_max'] = 5000.00
    invalid_booking['budget_min'] = 10000.00

    invalid_response = requests.post(
        f"{BASE_URL}/bookings",
        headers={"Authorization": f"Bearer {client_token}"},
        json=invalid_booking
    )
    if invalid_response.status_code == 422:
        print_success("Invalid Budget Validation - Status 422")
        test_results["passed"] += 1
    else:
        print_error(f"Budget Validation Failed - Status {invalid_response.status_code}")

    # Test 25: Duplicate Review
    duplicate_review = requests.post(
        f"{BASE_URL}/reviews",
        headers={"Authorization": f"Bearer {client_token}"},
        json=review_data
    )
    if duplicate_review.status_code == 400:
        print_success("Duplicate Review Blocked - Status 400")
        test_results["passed"] += 1
    else:
        print_error(f"Duplicate Review Not Blocked - Status {duplicate_review.status_code}")

    # ====================================================================
    # FINAL SUMMARY
    # ====================================================================
    print_section("TEST SUMMARY")

    total_tests = test_results["passed"] + test_results["failed"]
    pass_rate = (test_results["passed"] / total_tests * 100) if total_tests > 0 else 0

    print(f"\n{CYAN}Total Tests: {total_tests}{RESET}")
    print(f"{GREEN}Passed: {test_results['passed']}{RESET}")
    print(f"{RED}Failed: {test_results['failed']}{RESET}")
    print(f"{CYAN}Pass Rate: {pass_rate:.1f}%{RESET}\n")

    if test_results["failed"] > 0:
        print(f"{RED}Failed Tests:{RESET}")
        for error in test_results["errors"]:
            print(f"  - {error}")
    else:
        print(f"{GREEN}🎉 All tests passed! System is working perfectly!{RESET}")

if __name__ == "__main__":
    main()
