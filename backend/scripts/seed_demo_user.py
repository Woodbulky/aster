"""Demo account for the PRODUCT.md demo script (M6 acceptance, reused by M9): "Aarav Sunil Patil",
family income 1,20,000 (the specimen income certificate says 1,48,000: the seeded contradiction).
Idempotent. A non-deliverable example.com address: sign in with --link (no email is sent).

cd backend && uv run python -m scripts.seed_demo_user [--link http://localhost:3000]
"""

import sys

from app.db import supabase as repo

EMAIL = "aarav.demo@example.com"
PROFILE = {
    "full_name": "Aarav Sunil Patil",
    "dob": "2005-05-12",
    "gender": "Male",
    "domicile_state": "Maharashtra",
    "district": "Pune",
    "taluka": "Haveli",
    "category": "Open",
    "annual_family_income": 120000,
    "ssc_board": "Maharashtra State Board",
    "ssc_year": 2021,
    "ssc_percentage": 87.4,
    "hsc_year": 2023,
    "hsc_percentage": 82.5,
    "current_course": "B.E. Computer Engineering",
    "current_year": 2,
    "institute_name": "Specimen College of Engineering, Pune",
    "aadhaar_last4": "4417",
}


def user_id(db) -> str:
    for u in db.auth.admin.list_users(per_page=1000):
        if u.email == EMAIL:
            return u.id
    return db.auth.admin.create_user({"email": EMAIL, "email_confirm": True}).user.id


def main() -> None:
    db = repo.get_db()
    uid = user_id(db)
    repo.update_profile(db, uid, PROFILE, "manual", {"seed": "demo_user"})
    print(f"demo user {EMAIL} -> {uid}")
    if "--link" in sys.argv:
        origin = sys.argv[sys.argv.index("--link") + 1].rstrip("/")
        link = db.auth.admin.generate_link({"type": "magiclink", "email": EMAIL})
        token = link.properties.hashed_token
        url = f"{origin}/auth/callback?token_hash={token}&type=magiclink&next=/chat"
        print(f"sign in (one use, expires soon): {url}")


if __name__ == "__main__":
    main()
