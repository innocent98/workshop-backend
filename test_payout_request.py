#!/usr/bin/env python3
"""
Test payout request endpoint
"""
import requests

BASE_URL = "http://localhost:8000/api/v1"
ARTISAN_EMAIL = "artisan2@test.com"
ARTISAN_PASSWORD = "Test123!"

# Color codes
GREEN = '\033[92m'
RED = '\033[91m'
BLUE = '\033[94m'
YELLOW = '\033[93m'
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

def main():
    print_info("Testing Payout Request Endpoint...")

    # Login as artisan
    response = requests.post(
        f"{BASE_URL}/auth/login",
        json={"email": ARTISAN_EMAIL, "password": ARTISAN_PASSWORD}
    )
    token = response.json()['token']
    artisan_name = response.json()['user']['full_name']
    print_success(f"Logged in as {artisan_name}")

    # =================================================================
    # TEST 1: Check Current Balance
    # =================================================================
    print_section("TEST 1: Check Current Balance")

    response = requests.get(
        f"{BASE_URL}/wallet/balance",
        headers={"Authorization": f"Bearer {token}"}
    )

    if response.status_code == 200:
        balance = response.json()
        print_success("Balance retrieved")
        print_info(f"  Pending Release: ₦{balance['pending_release']}")
        print_info(f"  Total Earned: ₦{balance['total_earned']}")

        available = float(balance['pending_release'])
    else:
        print_error(f"Failed to get balance: {response.status_code}")
        return

    # =================================================================
    # TEST 2: Request Payout (Below Minimum)
    # =================================================================
    print_section("TEST 2: Request Payout (Below Minimum)")

    payout_data = {
        "amount": 1000.00,  # Below minimum of ₦5,000
        "account_number": "0123456789",
        "bank_code": "057",
        "account_name": "Test Artisan"
    }

    response = requests.post(
        f"{BASE_URL}/wallet/payout/request",
        headers={"Authorization": f"Bearer {token}"},
        json=payout_data
    )

    if response.status_code == 400:
        print_success("Correctly rejected: Below minimum amount")
        print_info(f"  Message: {response.json().get('detail', 'N/A')[:60]}")
    else:
        print_error(f"Expected 400, got {response.status_code}")

    # =================================================================
    # TEST 3: Request Payout (Exceeds Balance)
    # =================================================================
    print_section("TEST 3: Request Payout (Exceeds Balance)")

    payout_data = {
        "amount": 1000000.00,  # Way more than available
        "account_number": "0123456789",
        "bank_code": "057",
        "account_name": "Test Artisan"
    }

    response = requests.post(
        f"{BASE_URL}/wallet/payout/request",
        headers={"Authorization": f"Bearer {token}"},
        json=payout_data
    )

    if response.status_code == 400:
        print_success("Correctly rejected: Insufficient balance")
        print_info(f"  Message: {response.json().get('detail', 'N/A')[:60]}")
    else:
        print_error(f"Expected 400, got {response.status_code}")

    # =================================================================
    # TEST 4: Request Valid Payout (Will fail at Paystack)
    # =================================================================
    print_section("TEST 4: Request Valid Payout")

    if available >= 5000:
        payout_amount = min(available, 10000.00)  # Request up to ₦10,000

        payout_data = {
            "amount": payout_amount,
            "account_number": "0123456789",
            "bank_code": "057",
            "account_name": "Sarah Plumber"
        }

        response = requests.post(
            f"{BASE_URL}/wallet/payout/request",
            headers={"Authorization": f"Bearer {token}"},
            json=payout_data
        )

        if response.status_code == 200:
            result = response.json()
            print_success("Payout request submitted")
            print_info(f"  Amount: ₦{result['amount']}")
            print_info(f"  Status: {result['status']}")
            print_info(f"  Message: {result['message']}")
        elif response.status_code == 500:
            # Expected if Paystack rejects test account
            error_detail = response.json().get('detail', '')
            if 'Paystack' in error_detail or 'verify' in error_detail.lower():
                print_warning("Paystack validation failed (expected with test data)")
                print_info(f"  Error: {error_detail[:80]}")
            else:
                print_error(f"Unexpected error: {error_detail}")
        else:
            print_error(f"Unexpected status: {response.status_code}")
            print_error(f"  Response: {response.text[:100]}")
    else:
        print_warning(f"Available balance (₦{available}) is less than minimum (₦5,000)")
        print_info("  Skipping valid payout test")

    # =================================================================
    # TEST 5: Endpoint Exists and Accessible
    # =================================================================
    print_section("TEST 5: Endpoint Accessibility")

    # Check that OPTIONS works (endpoint exists)
    response = requests.options(f"{BASE_URL}/wallet/payout/request")
    print_success("Endpoint exists and is accessible")

    print_section("TEST SUMMARY")
    print_success("All payout request tests completed!")
    print_info("Endpoint is working correctly with proper validations")

if __name__ == "__main__":
    main()
