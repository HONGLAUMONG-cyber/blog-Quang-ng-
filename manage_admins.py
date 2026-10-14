from __future__ import annotations

import getpass
import re
import sqlite3

import app
from werkzeug.security import generate_password_hash


def add_admin(username: str, password: str) -> None:
    username = username.strip()
    if not re.fullmatch(r"[A-Za-z0-9_.-]{3,40}", username):
        raise ValueError(
            "Tên đăng nhập phải có 3-40 ký tự: chữ, số, _, . hoặc -."
        )
    if len(password) < 12:
        raise ValueError("Mật khẩu phải có ít nhất 12 ký tự.")

    app.init_db()
    connection = sqlite3.connect(app.DATABASE)
    try:
        connection.execute(
            "INSERT INTO admins(username,password_hash,created_at) VALUES(?,?,?)",
            (
                username,
                generate_password_hash(password, method="pbkdf2:sha256"),
                app.utc_now(),
            ),
        )
        connection.commit()
    except sqlite3.IntegrityError as error:
        connection.rollback()
        raise ValueError("Tên đăng nhập admin này đã tồn tại.") from error
    finally:
        connection.close()


def main() -> None:
    username = input("Tên đăng nhập admin mới: ").strip()
    password = getpass.getpass("Mật khẩu (ít nhất 12 ký tự): ")
    confirmation = getpass.getpass("Nhập lại mật khẩu: ")
    if password != confirmation:
        raise SystemExit("Hai lần nhập mật khẩu không khớp.")
    try:
        add_admin(username, password)
    except ValueError as error:
        raise SystemExit(str(error)) from error
    print(f"Đã tạo tài khoản admin “{username}”.")


if __name__ == "__main__":
    main()