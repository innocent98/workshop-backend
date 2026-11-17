from app.core.security import verify_password
from app.db.models.user import User, UserType
from scripts.create_admin import ensure_admin
from tests.admin.conftest import make_user


def test_creates_admin_then_is_idempotent(db):
    assert ensure_admin(db, "Boss@Example.test", "pw-one-placeholder") == "created"
    u = db.query(User).one()
    assert u.is_admin and u.is_email_verified and u.is_active
    assert u.email == "boss@example.test" and u.user_type == UserType.CLIENT
    assert verify_password("pw-one-placeholder", u.hashed_password)

    # re-run with a different env password: user kept, password NOT overwritten
    assert ensure_admin(db, "boss@example.test", "pw-two-placeholder") == "updated"
    db.expire_all()
    assert db.query(User).count() == 1
    assert verify_password("pw-one-placeholder", db.query(User).one().hashed_password)

    # explicit reset overwrites
    ensure_admin(db, "boss@example.test", "pw-two-placeholder", reset_password=True)
    db.expire_all()
    assert verify_password("pw-two-placeholder", db.query(User).one().hashed_password)


def test_refuses_to_silently_promote_existing_user(db):
    user = make_user(db, email="Existing@Example.test")
    old_hash = user.hashed_password
    assert ensure_admin(db, "existing@example.test", "irrelevant-placeholder") == "refused"
    db.expire_all()
    u = db.query(User).one()
    assert not u.is_admin and u.hashed_password == old_hash  # untouched


def test_explicit_promotion_takes_over_the_account(db):
    make_user(db, email="existing@example.test", is_email_verified=False)
    assert (
        ensure_admin(db, "EXISTING@example.test", "pw-new-placeholder", promote_existing=True)
        == "updated"
    )
    db.expire_all()
    u = db.query(User).one()
    assert u.is_admin and u.is_email_verified
    assert verify_password("pw-new-placeholder", u.hashed_password)  # previous password is gone
