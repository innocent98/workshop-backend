"""
Seed initial unified services data into the database.

Unified Service Model:
- Artisan selecting a service = "I provide this service"
- Client selecting a service = "I need this service"

This allows easy matching between clients and artisans.
"""
import sys
from pathlib import Path

# Add parent directory to path
sys.path.append(str(Path(__file__).resolve().parents[1]))

from sqlalchemy.orm import Session
from app.db.session import SessionLocal
from app.db.models.service import Service


def seed_services(db: Session) -> None:
    """Seed initial unified services data"""

    # Check if services already exist
    existing_count = db.query(Service).count()
    if existing_count > 0:
        print(f"Services already seeded ({existing_count} services found). Skipping...")
        return

    # Unified services that both artisans and clients can select
    # Context changes based on user type (provide vs need)
    unified_services = [
        {
            "name": "Electrical",
            "description": "Electrical installation, repair, and maintenance services"
        },
        {
            "name": "Plumbing",
            "description": "Plumbing installation, repair, and maintenance services"
        },
        {
            "name": "Carpentry",
            "description": "Woodwork, furniture making, and carpentry services"
        },
        {
            "name": "Cleaning",
            "description": "Home cleaning, office cleaning, and sanitation services"
        },
        {
            "name": "Painting",
            "description": "Interior and exterior painting services"
        },
        {
            "name": "Beauty/Makeup",
            "description": "Makeup artistry, beauty services, and styling"
        },
        {
            "name": "Construction",
            "description": "Building construction and renovation services"
        },
        {
            "name": "Auto Repair",
            "description": "Car repairs, maintenance, and parts services"
        },
        {
            "name": "Electronics Repair",
            "description": "Electronics repair and maintenance services"
        },
        {
            "name": "Dry Cleaning",
            "description": "Laundry, dry cleaning, and garment care services"
        },
        {
            "name": "Fashion/Tailoring",
            "description": "Fashion design, tailoring, and alterations"
        },
        {
            "name": "Home Repair",
            "description": "General home repair and handyman services"
        },
    ]

    services_to_create = []

    # Create unified services
    for service_data in unified_services:
        service = Service(
            name=service_data["name"],
            description=service_data["description"]
        )
        services_to_create.append(service)
        print(f"Preparing to create service: {service_data['name']}")

    # Bulk insert
    db.bulk_save_objects(services_to_create)
    db.commit()

    print(f"\n✅ Successfully seeded {len(services_to_create)} unified services!")
    print("   These services can be selected by both artisans (to provide) and clients (to request)")


def main():
    """Main execution"""
    print("Starting services seed...")
    db = SessionLocal()
    try:
        seed_services(db)
    except Exception as e:
        print(f"❌ Error seeding services: {e}")
        db.rollback()
        raise
    finally:
        db.close()
    print("Seed completed!")


if __name__ == "__main__":
    main()
