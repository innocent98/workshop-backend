#!/usr/bin/env python3
"""
Analyze current payment data to understand what wallet endpoints we need
"""
import requests

BASE_URL = "http://localhost:8000/api/v1"
ARTISAN_EMAIL = "artisan2@test.com"
ARTISAN_PASSWORD = "Test123!"

# Login
response = requests.post(
    f"{BASE_URL}/auth/login",
    json={"email": ARTISAN_EMAIL, "password": ARTISAN_PASSWORD}
)
token = response.json()['token']
artisan_id = response.json()['user']['id']

print("="*60)
print("CURRENT DATA AVAILABLE FOR WALLET")
print("="*60)

# Check what we can get from bookings
print("\n1. Bookings (to find payments):")
bookings_response = requests.get(
    f"{BASE_URL}/bookings",
    headers={"Authorization": f"Bearer {token}"}
)
bookings = bookings_response.json()['bookings']
print(f"   Total bookings: {len(bookings)}")

completed_bookings = [b for b in bookings if b['status'] == 'completed']
print(f"   Completed bookings: {len(completed_bookings)}")

# We don't have a direct endpoint to get all payments for an artisan!
print("\n2. Payments (per booking):")
print("   ❌ No endpoint to list all payments for an artisan")
print("   ❌ Must fetch each payment individually by payment_id")
print("   ❌ No way to get payment_id from booking response")

print("\n" + "="*60)
print("MISSING WALLET ENDPOINTS")
print("="*60)
print("\n✗ GET /wallet/balance - Get earnings summary")
print("  - total_earned: Sum of all RELEASED payments")
print("  - available: Amount available for withdrawal")
print("  - pending: Sum of SUCCESS payments (paid but not released)")
print("  - lifetime_earnings: Total of all time")
print()
print("✗ GET /wallet/earnings - List earnings history")
print("  - List all payments/earnings with booking details")
print("  - Filter by status, date range")
print("  - Pagination support")
print()
print("✗ GET /wallet/payouts - List payout history")
print("  - List all payouts/withdrawals")
print("  - Show bank details, status, dates")
print()
print("✗ POST /wallet/payout/request - Request payout")
print("  - Request withdrawal to bank account")
print("  - Minimum amount validation")
print("  - Bank account details")

print("\n" + "="*60)
print("RECOMMENDATION")
print("="*60)
print("""
We should create new wallet endpoints that:
1. Aggregate payment data for the artisan
2. Provide clear financial summary
3. Allow viewing earning/payout history
4. Support payout requests (if not auto-payout)

These can be built on top of existing Payment and Booking tables,
no new database tables needed!
""")
