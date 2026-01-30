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
            "name": "Electrician",
            "description": "Professional electrical services including installation, wiring, repairs, and safety inspections",
            "image": "https://res.cloudinary.com/dlw4um9gc/image/upload/v1769783311/electrician_asjxug.png"
        },
        {
            "name": "Plumbing",
            "description": "Plumbing installation, repair, and maintenance services",
            "image": "https://res.cloudinary.com/dlw4um9gc/image/upload/v1769783357/plumber_xxipw0.png"
        },
        {
            "name": "Carpentry",
            "description": "Woodwork, furniture making, and carpentry services",
            "image": "https://res.cloudinary.com/dlw4um9gc/image/upload/v1769783410/carpenter_es8sps.png"
        },
        {
            "name": "Cleaning",
            "description": "Home cleaning, office cleaning, and sanitation services",
            "image": "https://res.cloudinary.com/dlw4um9gc/image/upload/v1769783410/cleaner_wizbgr.png"
        },
        {
            "name": "Painting",
            "description": "Interior and exterior painting services",
            "image": "https://res.cloudinary.com/dlw4um9gc/image/upload/v1769783413/painter_y0xj45.png"
        },
        {
            "name": "Beauty/Makeup",
            "description": "Makeup artistry, beauty services, and styling",
            "image": "https://res.cloudinary.com/dlw4um9gc/image/upload/v1769783412/makeup_artist_qwd8hv.png"
        },
        {
            "name": "Construction",
            "description": "Building construction and renovation services",
            "image": "https://res.cloudinary.com/dlw4um9gc/image/upload/v1769783411/construction_mt2zp8.png"
        },
        {
            "name": "Auto Repair",
            "description": "Car repairs, maintenance, and parts services",
            "image": "https://res.cloudinary.com/dlw4um9gc/image/upload/v1769783410/car_repairs_mjsx70.png"
        },
        {
            "name": "Electronics Repair",
            "description": "Electronics repair and maintenance services",
            "image": "https://res.cloudinary.com/dlw4um9gc/image/upload/v1769783640/electronics_kqfajq.png"
        },
        {
            "name": "Dry Cleaning",
            "description": "Laundry, dry cleaning, and garment care services",
            "image": "https://res.cloudinary.com/dlw4um9gc/image/upload/v1769783639/dry_cleaning_pmkzik.png"
        },
        {
            "name": "Fashion/Tailoring",
            "description": "Custom tailoring, alterations, and fashion design services",
            "image": "https://res.cloudinary.com/dlw4um9gc/image/upload/v1769783641/fashion_design_mupfnt.png"
        },
        {
            "name": "Home Repair",
            "description": "General handyman and home repair services for all household fixes",
            "image": "https://res.cloudinary.com/dlw4um9gc/image/upload/v1769784095/home_repair_placeholder.png"
        },
    ]

    services_to_create = []

    # Create unified services
    for service_data in unified_services:
        service = Service(
            name=service_data["name"],
            description=service_data["description"],
            image=service_data.get("image")
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
