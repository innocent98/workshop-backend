"""
Script to create test accounts for the Workchop platform.

Creates:
- 10 Artisans (5 verified, 5 unverified)
- 10 Clients (all with completed profiles)

All accounts have:
- Completed 5-step registration
- Email verified
- Services selected
- Profile completed with bio
- Location set (Lagos area for artisans)
"""

import sys
import os
from pathlib import Path

# Add parent directory to path
sys.path.append(str(Path(__file__).parent.parent))

from sqlalchemy.orm import Session
from app.db.session import SessionLocal
from app.db.models.user import User, UserType
from app.db.models.artisan_profile import ArtisanProfile, AvailabilityStatus
from app.db.models.service import UserService
from app.core.security import get_password_hash
from app.utils.location import create_point
from geoalchemy2.elements import WKTElement
from datetime import datetime, timezone
import random


def create_artisan_account(
    db: Session,
    email: str,
    full_name: str,
    phone: str,
    password: str,
    service_ids: list,
    is_verified: bool,
    latitude: float,
    longitude: float,
    hourly_rate_min: int,
    hourly_rate_max: int,
    specialization: str,
    bio: str,
    years_of_experience: int
):
    """Create a complete artisan account"""

    # Check if already exists
    existing = db.query(User).filter(User.email == email).first()
    if existing:
        print(f"  ⚠️  Account {email} already exists, skipping...")
        return

    # Create user
    user = User(
        full_name=full_name,
        email=email.lower(),
        phone_number=phone,
        user_type=UserType.ARTISAN,
        hashed_password=get_password_hash(password),
        is_email_verified=True,
        registration_completed=True,
        bio=bio,
        is_active=True,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc)
    )

    db.add(user)
    db.flush()

    # Add services
    for service_id in service_ids:
        user_service = UserService(
            user_id=user.id,
            service_id=service_id
        )
        db.add(user_service)

    # Create artisan profile
    location = create_point(latitude, longitude)
    location_wkt = WKTElement(location, srid=4326)

    profile = ArtisanProfile(
        user_id=user.id,
        location=location_wkt,
        location_address=f"Lagos, Nigeria",
        service_radius_km=25.0,
        hourly_rate_min=hourly_rate_min,
        hourly_rate_max=hourly_rate_max,
        years_of_experience=years_of_experience,
        specialization=specialization,
        is_verified=is_verified,
        availability_status=AvailabilityStatus.AVAILABLE,
        average_rating=round(random.uniform(3.5, 5.0), 1),
        total_ratings=random.randint(5, 50),
        total_jobs_completed=random.randint(10, 100),
        response_time_avg_minutes=random.randint(30, 240),
        acceptance_rate=round(random.uniform(0.7, 0.95), 2)
    )

    db.add(profile)
    db.commit()

    verification_status = "✓ Verified" if is_verified else "✗ Unverified"
    print(f"  ✓ Created artisan: {email} - {full_name} ({verification_status})")


def create_client_account(
    db: Session,
    email: str,
    full_name: str,
    phone: str,
    password: str,
    service_ids: list,
    bio: str
):
    """Create a complete client account"""

    # Check if already exists
    existing = db.query(User).filter(User.email == email).first()
    if existing:
        print(f"  ⚠️  Account {email} already exists, skipping...")
        return

    # Create user
    user = User(
        full_name=full_name,
        email=email.lower(),
        phone_number=phone,
        user_type=UserType.CLIENT,
        hashed_password=get_password_hash(password),
        is_email_verified=True,
        registration_completed=True,
        bio=bio,
        is_active=True,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc)
    )

    db.add(user)
    db.flush()

    # Add services (services client needs)
    for service_id in service_ids:
        user_service = UserService(
            user_id=user.id,
            service_id=service_id
        )
        db.add(user_service)

    db.commit()

    print(f"  ✓ Created client: {email} - {full_name}")


def main():
    """Create all test accounts"""
    print("\n🚀 Creating test accounts...\n")

    db = SessionLocal()

    try:
        # Common password for all test accounts
        password = "Test123!"

        # Lagos coordinates with variations
        lagos_base_lat = 6.5244
        lagos_base_lon = 3.3792

        print("📋 Creating Verified Artisans (5)...")

        # Verified Artisans
        artisans_verified = [
            {
                "email": "artisan1@test.com",
                "full_name": "John Electrician",
                "phone": "+2348011111001",
                "service_ids": [14],  # Electrician
                "specialization": "Residential & Commercial Electrical Work",
                "bio": "Licensed electrician with 8 years experience. Specializing in home wiring, installations, and repairs.",
                "years_of_experience": 8,
                "hourly_rate_min": 5000,
                "hourly_rate_max": 10000,
                "lat": lagos_base_lat + 0.02,
                "lon": lagos_base_lon + 0.01
            },
            {
                "email": "artisan2@test.com",
                "full_name": "Sarah Plumber",
                "phone": "+2348011111002",
                "service_ids": [15],  # Plumbing
                "specialization": "Plumbing Installation & Repair",
                "bio": "Professional plumber serving Lagos for 10 years. Expert in pipe installations and leak repairs.",
                "years_of_experience": 10,
                "hourly_rate_min": 4500,
                "hourly_rate_max": 9000,
                "lat": lagos_base_lat - 0.01,
                "lon": lagos_base_lon + 0.02
            },
            {
                "email": "artisan3@test.com",
                "full_name": "David Carpenter",
                "phone": "+2348011111003",
                "service_ids": [16],  # Carpentry
                "specialization": "Custom Furniture & Woodwork",
                "bio": "Skilled carpenter creating custom furniture and handling all woodwork projects.",
                "years_of_experience": 12,
                "hourly_rate_min": 6000,
                "hourly_rate_max": 12000,
                "lat": lagos_base_lat + 0.03,
                "lon": lagos_base_lon - 0.01
            },
            {
                "email": "artisan4@test.com",
                "full_name": "Grace Painter",
                "phone": "+2348011111004",
                "service_ids": [18],  # Painting
                "specialization": "Interior & Exterior Painting",
                "bio": "Professional painter with an eye for detail. Residential and commercial projects welcome.",
                "years_of_experience": 6,
                "hourly_rate_min": 3500,
                "hourly_rate_max": 7000,
                "lat": lagos_base_lat - 0.02,
                "lon": lagos_base_lon - 0.01
            },
            {
                "email": "artisan5@test.com",
                "full_name": "Michael Mechanic",
                "phone": "+2348011111005",
                "service_ids": [21],  # Auto Repair
                "specialization": "Auto Repair & Maintenance",
                "bio": "Certified auto mechanic with expertise in all vehicle types. Fast and reliable service.",
                "years_of_experience": 15,
                "hourly_rate_min": 7000,
                "hourly_rate_max": 15000,
                "lat": lagos_base_lat + 0.01,
                "lon": lagos_base_lon + 0.03
            }
        ]

        for artisan in artisans_verified:
            create_artisan_account(
                db=db,
                email=artisan["email"],
                full_name=artisan["full_name"],
                phone=artisan["phone"],
                password=password,
                service_ids=artisan["service_ids"],
                is_verified=True,
                latitude=artisan["lat"],
                longitude=artisan["lon"],
                hourly_rate_min=artisan["hourly_rate_min"],
                hourly_rate_max=artisan["hourly_rate_max"],
                specialization=artisan["specialization"],
                bio=artisan["bio"],
                years_of_experience=artisan["years_of_experience"]
            )

        print("\n📋 Creating Unverified Artisans (5)...")

        # Unverified Artisans
        artisans_unverified = [
            {
                "email": "artisan6@test.com",
                "full_name": "Mary Cleaner",
                "phone": "+2348011111006",
                "service_ids": [17],  # Cleaning
                "specialization": "Home & Office Cleaning",
                "bio": "Professional cleaning services for homes and offices. Thorough and reliable.",
                "years_of_experience": 3,
                "hourly_rate_min": 2500,
                "hourly_rate_max": 5000,
                "lat": lagos_base_lat - 0.03,
                "lon": lagos_base_lon + 0.02
            },
            {
                "email": "artisan7@test.com",
                "full_name": "James Tailor",
                "phone": "+2348011111007",
                "service_ids": [24],  # Fashion/Tailoring
                "specialization": "Custom Tailoring & Alterations",
                "bio": "Expert tailor for custom clothing and alterations. Quality work guaranteed.",
                "years_of_experience": 7,
                "hourly_rate_min": 3000,
                "hourly_rate_max": 8000,
                "lat": lagos_base_lat + 0.02,
                "lon": lagos_base_lon - 0.02
            },
            {
                "email": "artisan8@test.com",
                "full_name": "Lucy Hairstylist",
                "phone": "+2348011111008",
                "service_ids": [19],  # Beauty/Makeup
                "specialization": "Hair Styling & Treatment",
                "bio": "Creative hairstylist offering cuts, styling, and treatments for all hair types.",
                "years_of_experience": 5,
                "hourly_rate_min": 4000,
                "hourly_rate_max": 10000,
                "lat": lagos_base_lat - 0.01,
                "lon": lagos_base_lon - 0.03
            },
            {
                "email": "artisan9@test.com",
                "full_name": "Peter Constructor",
                "phone": "+2348011111009",
                "service_ids": [20],  # Construction
                "specialization": "Building & Construction",
                "bio": "Experienced in construction and building projects of all sizes.",
                "years_of_experience": 9,
                "hourly_rate_min": 5500,
                "hourly_rate_max": 11000,
                "lat": lagos_base_lat + 0.04,
                "lon": lagos_base_lon + 0.01
            },
            {
                "email": "artisan10@test.com",
                "full_name": "Rita Electronics",
                "phone": "+2348011111010",
                "service_ids": [22],  # Electronics Repair
                "specialization": "Electronics Repair & Maintenance",
                "bio": "Professional electronics repair specialist. Quick turnaround time.",
                "years_of_experience": 4,
                "hourly_rate_min": 6000,
                "hourly_rate_max": 12000,
                "lat": lagos_base_lat - 0.02,
                "lon": lagos_base_lon + 0.03
            }
        ]

        for artisan in artisans_unverified:
            create_artisan_account(
                db=db,
                email=artisan["email"],
                full_name=artisan["full_name"],
                phone=artisan["phone"],
                password=password,
                service_ids=artisan["service_ids"],
                is_verified=False,
                latitude=artisan["lat"],
                longitude=artisan["lon"],
                hourly_rate_min=artisan["hourly_rate_min"],
                hourly_rate_max=artisan["hourly_rate_max"],
                specialization=artisan["specialization"],
                bio=artisan["bio"],
                years_of_experience=artisan["years_of_experience"]
            )

        print("\n📋 Creating Clients (10)...")

        # Clients
        clients = [
            {
                "email": "client1@test.com",
                "full_name": "Alice Customer",
                "phone": "+2348022222001",
                "service_ids": [14, 15],  # Needs electrician and plumbing
                "bio": "Homeowner looking for reliable artisans for home maintenance."
            },
            {
                "email": "client2@test.com",
                "full_name": "Bob Johnson",
                "phone": "+2348022222002",
                "service_ids": [16, 18],  # Needs carpentry and painting
                "bio": "Renovating my house and need skilled professionals."
            },
            {
                "email": "client3@test.com",
                "full_name": "Carol Williams",
                "phone": "+2348022222003",
                "service_ids": [17],  # Needs cleaning
                "bio": "Looking for regular cleaning services for my office."
            },
            {
                "email": "client4@test.com",
                "full_name": "Daniel Brown",
                "phone": "+2348022222004",
                "service_ids": [21],  # Needs auto repair
                "bio": "Car owner seeking reliable auto maintenance services."
            },
            {
                "email": "client5@test.com",
                "full_name": "Emma Davis",
                "phone": "+2348022222005",
                "service_ids": [19, 24],  # Needs beauty and tailoring
                "bio": "Fashion enthusiast looking for styling services."
            },
            {
                "email": "client6@test.com",
                "full_name": "Frank Miller",
                "phone": "+2348022222006",
                "service_ids": [20],  # Needs construction
                "bio": "Business owner needing construction for shop renovations."
            },
            {
                "email": "client7@test.com",
                "full_name": "Grace Wilson",
                "phone": "+2348022222007",
                "service_ids": [25],  # Needs home repair
                "bio": "Homeowner looking for general home repair services."
            },
            {
                "email": "client8@test.com",
                "full_name": "Henry Moore",
                "phone": "+2348022222008",
                "service_ids": [14, 15, 16],  # Multiple needs
                "bio": "Property manager maintaining several buildings."
            },
            {
                "email": "client9@test.com",
                "full_name": "Ivy Taylor",
                "phone": "+2348022222009",
                "service_ids": [18, 17],  # Needs painting and cleaning
                "bio": "New homeowner preparing to move in."
            },
            {
                "email": "client10@test.com",
                "full_name": "Jack Anderson",
                "phone": "+2348022222010",
                "service_ids": [21, 22],  # Needs auto repair and electronics repair
                "bio": "Auto shop owner looking for skilled professionals."
            }
        ]

        for client in clients:
            create_client_account(
                db=db,
                email=client["email"],
                full_name=client["full_name"],
                phone=client["phone"],
                password=password,
                service_ids=client["service_ids"],
                bio=client["bio"]
            )

        print("\n✅ Test account creation completed!\n")

    except Exception as e:
        print(f"\n❌ Error creating test accounts: {e}")
        db.rollback()
        raise
    finally:
        db.close()


if __name__ == "__main__":
    main()
