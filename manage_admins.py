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


def reset_admin_password(username: str, password: str) -> None:
    username = username.strip()
    if len(password) < 12:
        raise ValueError("Mật khẩu phải có ít nhất 12 ký tự.")

    app.init_db()
    connection = sqlite3.connect(app.DATABASE)
    try:
        cursor = connection.execute(
            "UPDATE admins SET password_hash=? WHERE username=?",
            (generate_password_hash(password, method="pbkdf2:sha256"), username),
        )
        if cursor.rowcount == 0:
            connection.rollback()
            raise ValueError(f"Không tìm thấy tài khoản admin “{username}”.")
        connection.commit()
    finally:
        connection.close()


def main() -> None:
    action = input("Chọn thao tác: [a] thêm admin, [r] đặt lại mật khẩu: ")
    username = input("Tên đăng nhập admin: ").strip()
    password = getpass.getpass("Mật khẩu (ít nhất 12 ký tự): ")
    confirmation = getpass.getpass("Nhập lại mật khẩu: ")
    if password != confirmation:
        raise SystemExit("Hai lần nhập mật khẩu không khớp.")
    try:
        if action.strip().lower() == "r":
            reset_admin_password(username, password)
        elif action.strip().lower() == "a":
            add_admin(username, password)
        else:
            raise ValueError("Hãy chọn a để thêm admin hoặc r để đặt lại mật khẩu.")
    except ValueError as error:
        raise SystemExit(str(error)) from error
    message = "Đã đặt lại mật khẩu" if action.strip().lower() == "r" else "Đã tạo"
    print(f"{message} tài khoản admin “{username}”.")


if __name__ == "__main__":
    main()