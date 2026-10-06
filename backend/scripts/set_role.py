"""
Grant a role to an existing user (e.g. admin, project_manager).
Privileged roles cannot be chosen at /register, so operators assign them here:
    docker exec bim-backend python scripts/set_role.py --email user@example.com --role admin
"""

import argparse
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.core.security import Role
from src.database.models import User
from src.database.session import SessionLocal


def set_role(email: str, role: str) -> int:
    if role not in Role.ALL:
        print(f"❌ Vai trò không hợp lệ: {role}. Chọn: {', '.join(Role.ALL)}")
        return 1

    db = SessionLocal()
    try:
        user = db.query(User).filter(User.email == email).first()
        if not user:
            print(f"❌ Không tìm thấy user: {email}")
            return 1

        old_role = user.role
        user.role = role
        db.commit()
        print(f"✅ {email}: {old_role} → {role}. User cần đăng nhập lại để nhận token mới.")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--email", required=True)
    parser.add_argument("--role", required=True, choices=Role.ALL)
    args = parser.parse_args()
    sys.exit(set_role(args.email, args.role))
