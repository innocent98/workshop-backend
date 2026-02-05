#!/usr/bin/env python3
"""
Test wallet endpoints
"""
import requests

BASE_URL = "http://localhost:8000/api/v1"

# Test credentials
ARTISAN_EMAIL = "artisan2@test.com"
ARTISAN_PASSWORD = "Test123!"
CLIENT_EMAIL = "client2@test.com"
CLIENT_PASSWORD = "Test123!"

# Color codes
GREEN = '\033[92m'
RED = '\033[91m'
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
    print_info("Testing Wallet Endpoints...")
    print_info(f"Base URL: {BASE_URL}\n")

    # Login as artisan
    artisan_token, artisan_user = login(ARTISAN_EMAIL, ARTISAN_PASSWORD)
    if not artisan_token:
        print_error("Artisan login failed")
        return

    print_success(f"Logged in as {artisan_user['full_name']} (artisan)")

    # =================================================================
    # TEST 1: Get Wallet Balance
    # =================================================================
    print_section("TEST 1: Get Wallet Balance")

    response = requests.get(
        f"{BASE_URL}/wallet/balance",
        headers={"Authorization": f"Bearer {artisan_token}"}
    )

    if response.status_code == 200:
        balance = response.json()
        print_success("Wallet balance retrieved")
        print_info(f"  Total Earned: ₦{balance['total_earned']}")
        print_info(f"  Pending Release: ₦{balance['pending_release']}")
        print_info(f"  Jobs Completed: {balance['total_jobs_completed']}")
        print_info(f"  Jobs Paid: {balance['total_jobs_paid']}")
        print_info(f"  Lifetime Earnings: ₦{balance['lifetime_earnings']}")
    else:
        print_error(f"Failed: {response.status_code}")
        print_error(response.text)

    # =================================================================
    # TEST 2: Get Earnings History
    # =================================================================
    print_section("TEST 2: Get Earnings History")

    response = requests.get(
        f"{BASE_URL}/wallet/earnings",
        headers={"Authorization": f"Bearer {artisan_token}"}
    )

    if response.status_code == 200:
        earnings = response.json()
        print_success(f"Found {earnings['total']} earning(s)")
        print_info(f"  Total Amount: ₦{earnings['summary']['total_amount']}")

        for earning in earnings['earnings'][:3]:  # Show first 3
            print_info(f"  - {earning['payment_reference']}: ₦{earning['amount']} ({earning['status']})")
    else:
        print_error(f"Failed: {response.status_code}")
        print_error(response.text)

    # =================================================================
    # TEST 3: Get Payout History
    # =================================================================
    print_section("TEST 3: Get Payout History")

    response = requests.get(
        f"{BASE_URL}/wallet/payouts",
        headers={"Authorization": f"Bearer {artisan_token}"}
    )

    if response.status_code == 200:
        payouts = response.json()
        print_success(f"Found {payouts['total']} payout(s)")

        for payout in payouts['payouts']:
            print_info(f"  - {payout['payout_reference']}: ₦{payout['amount']}")
    else:
        print_error(f"Failed: {response.status_code}")
        print_error(response.text)

    # =================================================================
    # TEST 4: Get Wallet Stats
    # =================================================================
    print_section("TEST 4: Get Wallet Stats")

    response = requests.get(
        f"{BASE_URL}/wallet/stats",
        headers={"Authorization": f"Bearer {artisan_token}"}
    )

    if response.status_code == 200:
        stats = response.json()
        print_success("Wallet stats retrieved")
        print_info(f"  Total Earnings: ₦{stats['total_earnings']}")
        print_info(f"  Average Job Value: ₦{stats['average_job_value']}")
        print_info(f"  Highest Earning: ₦{stats['highest_earning']}")
        print_info(f"  Lowest Earning: ₦{stats['lowest_earning']}")
        print_info(f"  Total Transactions: {stats['total_transactions']}")
    else:
        print_error(f"Failed: {response.status_code}")
        print_error(response.text)

    # =================================================================
    # TEST 5: Test Customer Cannot Access Wallet
    # =================================================================
    print_section("TEST 5: Customer Access (Should Fail)")

    client_token, client_user = login(CLIENT_EMAIL, CLIENT_PASSWORD)
    if client_token:
        response = requests.get(
            f"{BASE_URL}/wallet/balance",
            headers={"Authorization": f"Bearer {client_token}"}
        )

        if response.status_code == 403:
            print_success("Correctly blocked customer from accessing wallet")
        else:
            print_error(f"Unexpected response: {response.status_code}")

    # =================================================================
    # SUMMARY
    # =================================================================
    print_section("TEST SUMMARY")
    print_success("All wallet endpoint tests completed!")

if __name__ == "__main__":
    main()
