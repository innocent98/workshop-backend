"""
Seed comprehensive, categorized services data into the database.

Unified service model:
- Artisan selecting a service = "I provide this service"
- Client selecting a service = "I need this service"
"""
import argparse
import sys
from pathlib import Path

# Add parent directory to path
sys.path.append(str(Path(__file__).resolve().parents[1]))

from sqlalchemy.orm import Session

from app.db.models.service import Service, UserService
from app.db.models.service_category import ServiceCategory
from app.db.session import SessionLocal


CATEGORY_DEFINITIONS = [
    {
        "name": "Construction & Building Trades",
        "description": "Construction, installation, repairs, and household/structural services",
        "icon": "construction",
        "display_order": 1,
        "image": "https://res.cloudinary.com/dlw4um9gc/image/upload/v1769783411/construction_mt2zp8.png",
        "services": [
            "Bricklayers / Block Moulders",
            "Carpenters / Furniture Makers",
            "Aluminium Fabricators",
            "Roofing Specialists",
            "Tilers",
            "POP Ceiling Installers",
            "Painters / Decorative Finishers",
            "Welders / Metal Fabricators",
            "Scaffolders",
            "Land Survey Assistants",
            "Plumbers",
            "Water Treatment Technicians",
            "Borehole Drilling Technicians",
            "AC Installation & Repair Technicians",
            "Home Appliance Repairers (Fridge, Washing Machine)",
            "Satellite Dish Installers",
            "Interlocking Paving Installers",
            "Gardeners",
            "Pest Control Technicians",
            "Lock Installation & Key Replacement",
            "CCTV Installation Technicians",
            "Wallpaper Installation",
        ],
    },
    {
        "name": "Mechanical & Automotive Trades",
        "description": "Automotive maintenance, diagnostics, transport support, and roadside services",
        "icon": "directions_car",
        "display_order": 2,
        "image": "https://res.cloudinary.com/dlw4um9gc/image/upload/v1769783410/car_repairs_mjsx70.png",
        "services": [
            "Auto Mechanics",
            "Auto Electricians",
            "Panel Beaters",
            "Auto Spray Painters",
            "Motorcycle (Okada) Mechanics",
            "Vulcanizers (Tyre Repair)",
            "Car AC Technicians",
            "Battery Technicians",
            "Car Upholstery Specialists",
            "Car Hire Services",
            "Vehicle Towing Services",
        ],
    },
    {
        "name": "Electrical & Electronics Trades",
        "description": "Power systems, electronics diagnostics, and digital equipment maintenance",
        "icon": "bolt",
        "display_order": 3,
        "image": "https://res.cloudinary.com/dlw4um9gc/image/upload/v1769783640/electronics_kqfajq.png",
        "services": [
            "Electricians (Residential/Commercial)",
            "Generator Repair Technicians",
            "Solar Panel Installers",
            "Inverter Technicians",
            "Electronics Repairers (TV, Radio, Speakers)",
            "Mobile Phone Repair Technicians",
            "Computer Hardware Technicians",
        ],
    },
    {
        "name": "Fashion & Personal Care Trades",
        "description": "Fashion production, grooming, beauty, and personal care services",
        "icon": "style",
        "display_order": 4,
        "image": "https://res.cloudinary.com/dlw4um9gc/image/upload/v1769783641/fashion_design_mupfnt.png",
        "services": [
            "Tailors / Fashion Designers",
            "Shoe Makers / Cobblers",
            "Leather Bag Makers",
            "Barbers",
            "Hairdressers / Hair Stylists",
            "Makeup Artists",
            "Nail Technicians",
            "Bead Makers",
            "Wig Makers",
            "Spa Services",
            "Henna Artists",
        ],
    },
    {
        "name": "Food Production & Catering Trades",
        "description": "Food preparation, catering, snacks, and local beverage production",
        "icon": "restaurant",
        "display_order": 5,
        "image": "https://images.unsplash.com/photo-1517248135467-4c7edcad34c4?auto=format&fit=crop&w=1200&q=80",
        "services": [
            "Bakers",
            "Local Food Caterers",
            "Small Chops Producers",
            "Palm Oil Processors",
            "Garri Processors",
            "Suya Vendors",
            "Grillers / BBQ Vendors",
            "Local Drink Producers (Zobo, Kunu, Tigernut)",
            "Ice Cream / Yogurt Producers",
        ],
    },
    {
        "name": "Wood & Craft Production",
        "description": "Traditional and modern handcrafted wood/craft production services",
        "icon": "handyman",
        "display_order": 6,
        "image": "https://images.unsplash.com/photo-1452860606245-08befc0ff44b?auto=format&fit=crop&w=1200&q=80",
        "services": [
            "Wood Carvers",
            "Cane Furniture Makers",
            "Basket Weavers",
            "Drum / Traditional Instrument Makers",
            "Frame Makers",
            "Wooden Door & Window Makers",
            "Handmade Decor Artisans",
        ],
    },
    {
        "name": "Printing & Creative Production",
        "description": "Print, branding, signage, and creative production services",
        "icon": "print",
        "display_order": 7,
        "image": "https://images.unsplash.com/photo-1455390582262-044cdead277a?auto=format&fit=crop&w=1200&q=80",
        "services": [
            "Screen Printers",
            "Graphic Design & Print Shop Operators",
            "Signage Makers",
            "Flex Banner Printers",
            "Engraving Specialists",
            "Stamp Makers",
            "T-Shirt Branding",
            "Sticker / Vinyl Branding",
        ],
    },
    {
        "name": "Cleaning Services",
        "description": "Residential, industrial, and laundry-focused cleaning services",
        "icon": "cleaning_services",
        "display_order": 8,
        "image": "https://res.cloudinary.com/dlw4um9gc/image/upload/v1769783410/cleaner_wizbgr.png",
        "services": [
            "Residential Cleaning",
            "Industrial Cleaning",
            "Laundry Services",
            "Dry Cleaning Services",
        ],
    },
]

LEGACY_SERVICE_CATEGORY_MAP = {
    "Electrician": "Electrical & Electronics Trades",
    "Plumbing": "Construction & Building Trades",
    "Carpentry": "Construction & Building Trades",
    "Cleaning": "Cleaning Services",
    "Painting": "Construction & Building Trades",
    "Beauty/Makeup": "Fashion & Personal Care Trades",
    "Construction": "Construction & Building Trades",
    "Auto Repair": "Mechanical & Automotive Trades",
    "Electronics Repair": "Electrical & Electronics Trades",
    "Dry Cleaning": "Cleaning Services",
    "Fashion/Tailoring": "Fashion & Personal Care Trades",
    "Home Repair": "Construction & Building Trades",
}

DEFAULT_LEGACY_CATEGORY = "Construction & Building Trades"


def _service_description(service_name: str, category_name: str) -> str:
    return (
        f"Professional {service_name.lower()} services under {category_name.lower()}."
    )


def seed_services(db: Session, reset_user_services: bool = False) -> None:
    """Create or update categories and services."""
    created_categories = 0
    updated_categories = 0
    created_services = 0
    updated_services = 0
    categorized_legacy = 0
    reset_user_services_count = 0

    for category_data in CATEGORY_DEFINITIONS:
        category = (
            db.query(ServiceCategory)
            .filter(ServiceCategory.name == category_data["name"])
            .first()
        )
        if category is None:
            category = ServiceCategory(
                name=category_data["name"],
                description=category_data["description"],
                icon=category_data["icon"],
                display_order=category_data["display_order"],
                is_active=True,
            )
            db.add(category)
            db.flush()
            created_categories += 1
        else:
            category.description = category_data["description"]
            category.icon = category_data["icon"]
            category.display_order = category_data["display_order"]
            category.is_active = True
            updated_categories += 1

        for service_name in category_data["services"]:
            service = db.query(Service).filter(Service.name == service_name).first()
            if service is None:
                service = Service(
                    name=service_name,
                    description=_service_description(service_name, category_data["name"]),
                    image=category_data["image"],
                    category_id=category.id,
                )
                db.add(service)
                created_services += 1
            else:
                service.description = _service_description(service_name, category_data["name"])
                service.image = category_data["image"]
                service.category_id = category.id
                updated_services += 1

    # Ensure no service remains uncategorized.
    categories_by_name = {
        category.name: category.id for category in db.query(ServiceCategory).all()
    }
    fallback_category_id = categories_by_name[DEFAULT_LEGACY_CATEGORY]

    uncategorized_services = db.query(Service).filter(Service.category_id.is_(None)).all()
    for service in uncategorized_services:
        mapped_category = LEGACY_SERVICE_CATEGORY_MAP.get(service.name, DEFAULT_LEGACY_CATEGORY)
        service.category_id = categories_by_name.get(mapped_category, fallback_category_id)
        categorized_legacy += 1

    if reset_user_services:
        reset_user_services_count = db.query(UserService).delete(synchronize_session=False)

    db.commit()

    print("\n✅ Services and categories seeding completed.")
    print(f"   Categories created: {created_categories}")
    print(f"   Categories updated: {updated_categories}")
    print(f"   Services created: {created_services}")
    print(f"   Services updated: {updated_services}")
    print(f"   Legacy services categorized: {categorized_legacy}")
    if reset_user_services:
        print(f"   User-service links deleted: {reset_user_services_count}")
    print(f"   Total configured categories: {len(CATEGORY_DEFINITIONS)}")


def main():
    parser = argparse.ArgumentParser(
        description="Seed categorized services and optionally reset user service selections.",
    )
    parser.add_argument(
        "--reset-user-services",
        action="store_true",
        help="Delete all existing user_services rows so users can reselect services.",
    )
    args = parser.parse_args()

    print("Starting categories + services seed...")
    db = SessionLocal()
    try:
        seed_services(db, reset_user_services=args.reset_user_services)
    except Exception as exc:
        print(f"❌ Error seeding categories/services: {exc}")
        db.rollback()
        raise
    finally:
        db.close()
    print("Seed completed!")


if __name__ == "__main__":
    main()
