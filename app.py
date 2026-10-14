from __future__ import annotations

import argparse
import getpass
import html
from html.parser import HTMLParser
from io import BytesIO
import json
import os
from pathlib import Path
import re
import secrets
import sqlite3
import threading
import unicodedata
import uuid
from datetime import datetime, timezone
from functools import wraps
from urllib.parse import urlparse

from flask import (
    Flask,
    abort,
    flash,
    g,
    redirect,
    render_template,
    request,
    session,
    url_for,
)
from PIL import Image, ImageOps, UnidentifiedImageError
from werkzeug.security import check_password_hash, generate_password_hash


ROOT = Path(__file__).resolve().parent
DATA_DIR = Path(os.environ.get("BLOG_DATA_DIR", ROOT / "data")).resolve()
UPLOAD_DIR = DATA_DIR / "uploads"
DATABASE = DATA_DIR / "blog.sqlite3"
MAX_UPLOAD_BYTES = 60 * 1024 * 1024
MAX_FILES_PER_POST = 12
MAX_IMAGE_DIMENSION = 1920
IMAGE_QUALITY = 82
COMPRESSIBLE_IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp"}
ALLOWED_EXTENSIONS = {
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".webp": "image/webp",
    ".gif": "image/gif",
    ".mp4": "video/mp4",
    ".webm": "video/webm",
    ".mov": "video/quicktime",
}
CATEGORIES = [
    "Cuộc sống ở Nhật",
    "Kinh nghiệm đi Nhật",
    "Việc làm",
    "Học tập & tiếng Nhật",
    "Văn hóa Nhật",
    "Du lịch",
    "Ăn uống",
    "Chia sẻ khác",
]
ALLOWED_HTML_TAGS = {
    "a", "blockquote", "br", "code", "em", "figcaption", "figure", "h2",
    "h3", "iframe", "img", "li", "ol", "p", "pre", "strong", "u", "ul",
    "video",
}
VOID_TAGS = {"br", "img"}
DANGEROUS_TAGS = {"object", "script", "style", "svg"}


def _load_secret() -> str:
    configured = os.environ.get("BLOG_SECRET_KEY", "").strip()
    if configured:
        return configured
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    secret_file = DATA_DIR / ".secret-key"
    try:
        descriptor = os.open(
            secret_file,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL,
            0o600,
        )
    except FileExistsError:
        return secret_file.read_text(encoding="utf-8").strip()
    value = secrets.token_urlsafe(48)
    with os.fdopen(descriptor, "w", encoding="utf-8") as secret_stream:
        secret_stream.write(value)
    return value


app = Flask(__name__)
app.config.update(
    SECRET_KEY=_load_secret(),
    MAX_CONTENT_LENGTH=MAX_UPLOAD_BYTES,
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE=os.environ.get("BLOG_COOKIE_SECURE", "").lower()
    in {"1", "true", "yes"},
)
_admin_bootstrap_lock = threading.Lock()
_admin_bootstrap_applied = False


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def get_db() -> sqlite3.Connection:
    if "db" not in g:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(DATABASE)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA journal_mode = WAL")
        g.db = connection
    return g.db


@app.teardown_appcontext
def close_db(_error: BaseException | None) -> None:
    connection = g.pop("db", None)
    if connection is not None:
        connection.close()


def init_db() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(DATABASE)
    connection.execute("PRAGMA foreign_keys = ON")
    connection.executescript(
        """
        CREATE TABLE IF NOT EXISTS admins (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT NOT NULL UNIQUE,
            password_hash TEXT NOT NULL,
            created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS posts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            slug TEXT NOT NULL UNIQUE,
            excerpt TEXT NOT NULL DEFAULT '',
            body_html TEXT NOT NULL DEFAULT '',
            category TEXT NOT NULL,
            status TEXT NOT NULL CHECK(status IN ('draft','published')),
            cover_media_id INTEGER,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            published_at TEXT,
            FOREIGN KEY(cover_media_id) REFERENCES media(id) ON DELETE SET NULL
        );
        CREATE TABLE IF NOT EXISTS media (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            post_id INTEGER NOT NULL,
            filename TEXT NOT NULL UNIQUE,
            original_name TEXT NOT NULL,
            mime_type TEXT NOT NULL,
            size_bytes INTEGER NOT NULL,
            created_at TEXT NOT NULL,
            FOREIGN KEY(post_id) REFERENCES posts(id) ON DELETE CASCADE
        );
        CREATE TABLE IF NOT EXISTS login_attempts (
            ip TEXT PRIMARY KEY,
            failures INTEGER NOT NULL DEFAULT 0,
            last_failure REAL NOT NULL DEFAULT 0
        );
        """
    )
    connection.execute(
        "INSERT OR IGNORE INTO settings(key,value) VALUES"
        "('site_title','Quang Đông Japan'),"
        "('tagline','Chuyện đời thường, kinh nghiệm thật ở Nhật Bản.'),"
        "('author','Quang Đông'),"
        "('about','Xin chào, mình là Quang Đông. Đây là nơi mình chia sẻ những điều đã trải qua trong cuộc sống ở Nhật.'),"
        "('contact_url','')"
    )
    connection.commit()
    connection.close()


def site_settings() -> dict[str, str]:
    rows = get_db().execute("SELECT key,value FROM settings").fetchall()
    return {row["key"]: row["value"] for row in rows}


@app.context_processor
def inject_site_data() -> dict[str, object]:
    if not DATABASE.exists():
        init_db()
    if "csrf_token" not in session:
        session["csrf_token"] = secrets.token_urlsafe(32)
    return {"site": site_settings(), "csrf_token": session["csrf_token"]}


@app.before_request
def ensure_schema() -> None:
    global _admin_bootstrap_applied
    if not DATABASE.exists():
        init_db()
    configured_password = os.environ.get("BLOG_ADMIN_PASSWORD", "")
    if configured_password and not _admin_bootstrap_applied:
        with _admin_bootstrap_lock:
            if not _admin_bootstrap_applied:
                username = os.environ.get(
                    "BLOG_ADMIN_USERNAME", "QUANGDONGADMIN"
                ).strip()
                if not re.fullmatch(r"[A-Za-z0-9_.-]{3,40}", username):
                    raise RuntimeError(
                        "BLOG_ADMIN_USERNAME must be 3-40 characters using "
                        "letters, numbers, underscores, dots, or hyphens."
                    )
                if len(configured_password) < 12:
                    raise RuntimeError(
                        "BLOG_ADMIN_PASSWORD must contain at least 12 characters."
                    )
                init_db()
                connection = sqlite3.connect(DATABASE)
                try:
                    admin = connection.execute(
                        "SELECT id FROM admins WHERE username=?", (username,)
                    ).fetchone()
                    password_hash = generate_password_hash(
                        configured_password, method="pbkdf2:sha256"
                    )
                    if admin:
                        connection.execute(
                            "UPDATE admins SET password_hash=? WHERE id=?",
                            (password_hash, admin[0]),
                        )
                    else:
                        connection.execute(
                            "INSERT INTO admins(username,password_hash,created_at) "
                            "VALUES(?,?,?)",
                            (username, password_hash, utc_now()),
                        )
                    connection.commit()
                finally:
                    connection.close()
                _admin_bootstrap_applied = True
    if request.method == "POST":
        submitted = request.form.get("csrf_token", "")
        expected = session.get("csrf_token", "")
        if not expected or not secrets.compare_digest(submitted, expected):
            abort(400, description="Phiên biểu mẫu không hợp lệ. Hãy tải lại trang.")


@app.errorhandler(413)
def too_large(_error):
    return (
        render_template(
            "error.html",
            title="Tệp quá lớn",
            message="Tổng dung lượng tải lên tối đa là 60 MB mỗi lần.",
        ),
        413,
    )


def admin_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not session.get("admin_id"):
            return redirect(url_for("admin_login", next=request.path))
        return view(*args, **kwargs)

    return wrapped


def slugify(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value)
    ascii_value = normalized.encode("ascii", "ignore").decode("ascii").lower()
    slug = re.sub(r"[^a-z0-9]+", "-", ascii_value).strip("-")
    return slug[:90] or f"bai-viet-{uuid.uuid4().hex[:10]}"


def is_safe_https_url(value: str | None) -> bool:
    if not value or value != value.strip() or any(
        ord(character) < 32 or ord(character) == 127 for character in value
    ):
        return False
    try:
        parsed = urlparse(value)
        if not (
            parsed.scheme.lower() == "https"
            and bool(parsed.hostname)
            and parsed.username is None
            and parsed.password is None
            and not any(
                character.isspace() or character == "\\"
                for character in parsed.netloc
            )
        ):
            return False
        parsed.port
        return True
    except ValueError:
        return False


class ArticleSanitizer(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.output: list[str] = []
        self.open_tags: list[str] = []
        self.skip_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in DANGEROUS_TAGS:
            self.skip_depth += 1
            return
        if self.skip_depth or tag not in ALLOWED_HTML_TAGS:
            return
        if tag == "iframe":
            src = next((value for key, value in attrs if key == "src"), None)
            title = next((value for key, value in attrs if key == "title"), None)
            if src and is_safe_https_url(src):
                self.output.append(
                    f'<iframe src="{html.escape(src, quote=True)}" '
                    f'title="{html.escape(title or "Nội dung nhúng", quote=True)}" '
                    'loading="lazy" referrerpolicy="strict-origin-when-cross-origin" '
                    'sandbox="allow-scripts allow-presentation" '
                    'allowfullscreen></iframe>'
                )
            return
        if tag in VOID_TAGS:
            if tag == "br":
                self.output.append("<br>")
                return
            src = next((value for key, value in attrs if key == "src"), None)
            alt = next((value for key, value in attrs if key == "alt"), "")
            local_image = bool(
                src
                and re.fullmatch(
                    r"/media/[a-f0-9]{32}\.(jpg|jpeg|png|webp|gif)", src
                )
            )
            if src and (local_image or is_safe_https_url(src)):
                self.output.append(
                    f'<img src="{html.escape(src, quote=True)}" '
                    f'alt="{html.escape(alt or "", quote=True)}" loading="lazy">'
                )
            return
        if tag == "video":
            src = next((value for key, value in attrs if key == "src"), None)
            local_video = bool(
                src
                and re.fullmatch(
                    r"/media/[a-f0-9]{32}\.(mp4|webm|mov)", src
                )
            )
            if src and (local_video or is_safe_https_url(src)):
                self.output.append(
                    f'<video src="{html.escape(src, quote=True)}" '
                    'controls playsinline preload="metadata">'
                )
                self.open_tags.append("video")
            return
        if tag == "a":
            href = next((value for key, value in attrs if key == "href"), None)
            title = next((value for key, value in attrs if key == "title"), None)
            if href and urlparse(href).scheme.lower() in {"https", "http", "mailto"}:
                safe_href = html.escape(href, quote=True)
                safe_title = (
                    f' title="{html.escape(title, quote=True)}"' if title else ""
                )
                self.output.append(
                    f'<a href="{safe_href}" rel="nofollow noopener" '
                    f'target="_blank"{safe_title}>'
                )
                self.open_tags.append("a")
            else:
                self.output.append("<span>")
                self.open_tags.append("span")
            return
        self.output.append(f"<{tag}>")
        self.open_tags.append(tag)

    def handle_endtag(self, tag: str) -> None:
        if tag in DANGEROUS_TAGS:
            self.skip_depth = max(0, self.skip_depth - 1)
            return
        if self.skip_depth or tag not in ALLOWED_HTML_TAGS or tag in VOID_TAGS:
            return
        safe_tag = (
            "span"
            if tag == "a" and self.open_tags and self.open_tags[-1] == "span"
            else tag
        )
        if safe_tag in self.open_tags:
            while self.open_tags:
                current = self.open_tags.pop()
                self.output.append(f"</{current}>")
                if current == safe_tag:
                    break

    def handle_data(self, data: str) -> None:
        if not self.skip_depth:
            self.output.append(html.escape(data))

    def finish(self) -> str:
        self.close()
        while self.open_tags:
            self.output.append(f"</{self.open_tags.pop()}>")
        return "".join(self.output)


def sanitize_article_html(source: str) -> str:
    parser = ArticleSanitizer()
    parser.feed(source[:200_000])
    return parser.finish()


def file_signature_matches(data: bytes, extension: str) -> bool:
    signatures = {
        ".jpg": data.startswith(b"\xff\xd8\xff"),
        ".jpeg": data.startswith(b"\xff\xd8\xff"),
        ".png": data.startswith(b"\x89PNG\r\n\x1a\n"),
        ".webp": len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WEBP",
        ".gif": data.startswith((b"GIF87a", b"GIF89a")),
        ".mp4": len(data) >= 12 and data[4:8] == b"ftyp",
        ".mov": len(data) >= 12 and data[4:8] == b"ftyp",
        ".webm": data.startswith(b"\x1a\x45\xdf\xa3"),
    }
    return signatures.get(extension, False)


def compress_image(
    data: bytes, extension: str, original_name: str
) -> tuple[bytes, str]:
    if extension not in COMPRESSIBLE_IMAGE_EXTENSIONS:
        return data, extension

    try:
        with Image.open(BytesIO(data)) as source:
            if getattr(source, "n_frames", 1) > 1:
                return data, extension
            source.load()
            has_alpha = "A" in source.getbands() or "transparency" in source.info
            image = ImageOps.exif_transpose(source)
            image.thumbnail(
                (MAX_IMAGE_DIMENSION, MAX_IMAGE_DIMENSION),
                Image.Resampling.LANCZOS,
            )
            image = image.convert("RGBA" if has_alpha else "RGB")
            output = BytesIO()
            save_options = {
                "format": "WEBP",
                "quality": IMAGE_QUALITY,
                "method": 6,
            }
            icc_profile = source.info.get("icc_profile")
            if icc_profile:
                save_options["icc_profile"] = icc_profile
            image.save(output, **save_options)
    except (Image.DecompressionBombError, OSError, UnidentifiedImageError) as error:
        raise ValueError(f"Không thể đọc ảnh “{original_name}”.") from error

    compressed = output.getvalue()
    if len(compressed) >= len(data):
        return data, extension
    return compressed, ".webp"


def save_upload(upload, post_id: int, role: str) -> int | None:
    if not upload or not upload.filename:
        return None
    original_name = Path(upload.filename).name[:180]
    extension = Path(original_name).suffix.lower()
    mime_type = ALLOWED_EXTENSIONS.get(extension)
    if not mime_type:
        raise ValueError("Chỉ nhận ảnh JPG, PNG, WEBP, GIF và video MP4, WEBM, MOV.")
    data = upload.stream.read(MAX_UPLOAD_BYTES + 1)
    if not data:
        return None
    if len(data) > MAX_UPLOAD_BYTES:
        raise ValueError("Tệp tải lên vượt quá giới hạn 60 MB.")
    if not file_signature_matches(data, extension):
        raise ValueError(f"Tệp “{original_name}” không đúng định dạng khai báo.")
    data, extension = compress_image(data, extension, original_name)
    mime_type = ALLOWED_EXTENSIONS[extension]
    filename = f"{uuid.uuid4().hex}{extension}"
    (UPLOAD_DIR / filename).write_bytes(data)
    g.setdefault("saved_uploads", []).append(filename)
    cursor = get_db().execute(
        "INSERT INTO media(post_id,filename,original_name,mime_type,size_bytes,created_at) "
        "VALUES(?,?,?,?,?,?)",
        (post_id, filename, original_name, mime_type, len(data), utc_now()),
    )
    media_id = int(cursor.lastrowid)
    if role == "cover":
        get_db().execute(
            "UPDATE posts SET cover_media_id=? WHERE id=?", (media_id, post_id)
        )
    return media_id


def _inline_media_refs(files) -> list[str]:
    raw_refs = request.form.get("inline_media_refs", "[]")
    try:
        refs = json.loads(raw_refs)
    except json.JSONDecodeError as error:
        raise ValueError("Danh sách ảnh/video chèn trong bài không hợp lệ.") from error
    if (
        not isinstance(refs, list)
        or any(
            not isinstance(ref, str) or not re.fullmatch(r"[a-f0-9]{32}", ref)
            for ref in refs
        )
        or len(refs) != len(files)
        or len(set(refs)) != len(refs)
    ):
        raise ValueError("Không khớp ảnh/video được chọn với vị trí chèn trong bài.")
    return refs


def _save_inline_media(post_id: int, body_html: str, files, refs: list[str]) -> str:
    for ref, upload in zip(refs, files):
        media_id = save_upload(upload, post_id, "inline")
        row = get_db().execute(
            "SELECT filename,mime_type,original_name FROM media WHERE id=?",
            (media_id,),
        ).fetchone()
        if not row:
            raise ValueError("Không lưu được ảnh/video chèn trong bài.")
        safe_filename = row["filename"]
        safe_name = html.escape(row["original_name"])
        if row["mime_type"].startswith("video/"):
            embedded = (
                f'<video src="/media/{safe_filename}" controls '
                'playsinline preload="metadata"></video>'
            )
        else:
            embedded = (
                f'<img src="/media/{safe_filename}" '
                f'alt="{safe_name}" loading="lazy">'
            )
        marker = re.compile(
            r'<span\b(?=[^>]*\bdata-inline-media-ref=["\']'
            + re.escape(ref)
            + r'["\'])[^>]*>.*?</span\s*>',
            flags=re.IGNORECASE | re.DOTALL,
        )
        body_html, replacements = marker.subn(embedded, body_html, count=1)
        if replacements != 1:
            raise ValueError("Không tìm thấy vị trí chèn của một ảnh/video.")
    return sanitize_article_html(body_html)


def discard_saved_uploads() -> None:
    for filename in g.pop("saved_uploads", []):
        try:
            (UPLOAD_DIR / filename).unlink(missing_ok=True)
        except OSError:
            app.logger.exception("Không thể dọn tệp tải lên chưa được lưu: %s", filename)


def remove_media(media_id: int, post_id: int) -> None:
    row = get_db().execute(
        "SELECT filename FROM media WHERE id=? AND post_id=?",
        (media_id, post_id),
    ).fetchone()
    if not row:
        return
    body_row = get_db().execute(
        "SELECT body_html FROM posts WHERE id=?", (post_id,)
    ).fetchone()
    if body_row:
        media_src = re.escape(f"/media/{row['filename']}")
        body_html = re.sub(
            r'<img\b(?=[^>]*\bsrc=["\']'
            + media_src
            + r'["\'])[^>]*>',
            "",
            body_row["body_html"],
            flags=re.IGNORECASE,
        )
        body_html = re.sub(
            r'<video\b(?=[^>]*\bsrc=["\']'
            + media_src
            + r'["\'])[^>]*>.*?</video\s*>',
            "",
            body_html,
            flags=re.IGNORECASE | re.DOTALL,
        )
        get_db().execute(
            "UPDATE posts SET body_html=? WHERE id=?", (body_html, post_id)
        )
    get_db().execute(
        "UPDATE posts SET cover_media_id=NULL WHERE cover_media_id=?",
        (media_id,),
    )
    get_db().execute("DELETE FROM media WHERE id=?", (media_id,))
    try:
        (UPLOAD_DIR / row["filename"]).unlink(missing_ok=True)
    except OSError:
        app.logger.exception("Không thể xóa tệp media %s", media_id)


def get_post(slug: str):
    return get_db().execute(
        "SELECT p.*,m.filename AS cover_filename,m.mime_type AS cover_mime "
        "FROM posts p LEFT JOIN media m ON m.id=p.cover_media_id "
        "WHERE p.slug=? AND p.status='published'",
        (slug,),
    ).fetchone()


def get_post_media(post_id: int):
    return get_db().execute(
        "SELECT * FROM media WHERE post_id=? ORDER BY id", (post_id,)
    ).fetchall()


def _form_values() -> dict[str, str]:
    return {
        "title": request.form.get("title", "").strip()[:180],
        "excerpt": request.form.get("excerpt", "").strip()[:500],
        "category": request.form.get("category", "").strip(),
        "body_html": request.form.get("body_html", "")[:200_000],
        "status": "published"
        if request.form.get("status") == "published"
        else "draft",
    }


@app.get("/")
def home():
    category = request.args.get("category", "").strip()
    search = request.args.get("q", "").strip()[:100]
    query = (
        "SELECT p.*,m.filename AS cover_filename,m.mime_type AS cover_mime "
        "FROM posts p LEFT JOIN media m ON m.id=p.cover_media_id "
        "WHERE p.status='published'"
    )
    params: list[str] = []
    if category in CATEGORIES:
        query += " AND p.category=?"
        params.append(category)
    if search:
        query += " AND (p.title LIKE ? OR p.excerpt LIKE ? OR p.body_html LIKE ?)"
        term = f"%{search}%"
        params.extend([term, term, term])
    query += " ORDER BY COALESCE(p.published_at,p.created_at) DESC LIMIT 24"
    posts = get_db().execute(query, params).fetchall()
    post_count = get_db().execute(
        "SELECT COUNT(*) FROM posts WHERE status='published'"
    ).fetchone()[0]
    return render_template(
        "home.html",
        posts=posts,
        categories=CATEGORIES,
        active_category=category,
        search=search,
        post_count=post_count,
    )


@app.get("/lien-he")
def contact():
    return render_template("contact.html")


@app.get("/bai-viet/<slug>")
def article(slug: str):
    post = get_post(slug)
    if not post:
        abort(404)
    return render_template("article.html", post=post, media=get_post_media(post["id"]))


@app.get("/media/<path:filename>")
def media_file(filename: str):
    if not re.fullmatch(
        r"[a-f0-9]{32}\.(jpg|jpeg|png|webp|gif|mp4|webm|mov)", filename
    ):
        abort(404)
    from flask import send_from_directory

    return send_from_directory(
        UPLOAD_DIR, filename, conditional=True, max_age=86400
    )


@app.route("/admin/login", methods=["GET", "POST"])
def admin_login():
    if session.get("admin_id"):
        return redirect(url_for("admin_dashboard"))
    if request.method == "POST":
        ip = request.remote_addr or "unknown"
        attempt = get_db().execute(
            "SELECT failures,last_failure FROM login_attempts WHERE ip=?", (ip,)
        ).fetchone()
        now = datetime.now().timestamp()
        if attempt and attempt["failures"] >= 8 and now - attempt["last_failure"] < 900:
            flash("Đăng nhập tạm khóa 15 phút do nhập sai nhiều lần.", "error")
            return render_template("login.html"), 429
        username = request.form.get("username", "").strip()[:80]
        password = request.form.get("password", "")
        admin = get_db().execute(
            "SELECT id,username,password_hash FROM admins WHERE username=?",
            (username,),
        ).fetchone()
        if admin and check_password_hash(admin["password_hash"], password):
            get_db().execute("DELETE FROM login_attempts WHERE ip=?", (ip,))
            get_db().commit()
            session.clear()
            session["admin_id"] = admin["id"]
            session["admin_username"] = admin["username"]
            session["csrf_token"] = secrets.token_urlsafe(32)
            return redirect(url_for("admin_dashboard"))
        failures = (
            attempt["failures"] + 1
            if attempt and now - attempt["last_failure"] < 900
            else 1
        )
        get_db().execute(
            "INSERT INTO login_attempts(ip,failures,last_failure) VALUES(?,?,?) "
            "ON CONFLICT(ip) DO UPDATE SET failures=excluded.failures,"
            "last_failure=excluded.last_failure",
            (ip, failures, now),
        )
        get_db().commit()
        flash("Tên đăng nhập hoặc mật khẩu không đúng.", "error")
    return render_template("login.html")


@app.post("/admin/logout")
@admin_required
def admin_logout():
    session.clear()
    flash("Bạn đã đăng xuất.", "success")
    return redirect(url_for("home"))


@app.get("/admin")
@admin_required
def admin_dashboard():
    posts = get_db().execute(
        "SELECT p.*,m.filename AS cover_filename FROM posts p "
        "LEFT JOIN media m ON m.id=p.cover_media_id "
        "ORDER BY p.updated_at DESC"
    ).fetchall()
    published_count = sum(post["status"] == "published" for post in posts)
    return render_template(
        "dashboard.html",
        posts=posts,
        published_count=published_count,
        draft_count=len(posts) - published_count,
    )


@app.route("/admin/bai-viet/moi", methods=["GET", "POST"])
@admin_required
def new_post():
    if request.method == "POST":
        values = _form_values()
        if not values["title"] or values["category"] not in CATEGORIES:
            flash("Hãy nhập tiêu đề và chọn danh mục hợp lệ.", "error")
            return render_template("editor.html", post=None, categories=CATEGORIES)
        now = utc_now()
        cursor = get_db().execute(
            "INSERT INTO posts(title,slug,excerpt,body_html,category,status,"
            "created_at,updated_at,published_at) VALUES(?,?,?,?,?,?,?,?,?)",
            (
                values["title"],
                f"{slugify(values['title'])}-{uuid.uuid4().hex[:6]}",
                values["excerpt"],
                values["body_html"],
                values["category"],
                values["status"],
                now,
                now,
                now if values["status"] == "published" else None,
            ),
        )
        post_id = int(cursor.lastrowid)
        try:
            save_upload(request.files.get("cover"), post_id, "cover")
            media_files = [
                item for item in request.files.getlist("media")
                if item and item.filename
            ]
            inline_files = [
                item for item in request.files.getlist("inline_media")
                if item and item.filename
            ]
            refs = _inline_media_refs(inline_files)
            cover = request.files.get("cover")
            upload_count = len(media_files) + len(inline_files) + bool(
                cover and cover.filename
            )
            if upload_count > MAX_FILES_PER_POST:
                raise ValueError(f"Mỗi bài tối đa {MAX_FILES_PER_POST} tệp mới.")
            for item in media_files:
                save_upload(item, post_id, "media")
            body_html = _save_inline_media(
                post_id, values["body_html"], inline_files, refs
            )
            get_db().execute(
                "UPDATE posts SET body_html=? WHERE id=?", (body_html, post_id)
            )
            get_db().commit()
        except (ValueError, OSError) as error:
            get_db().rollback()
            discard_saved_uploads()
            get_db().execute("DELETE FROM posts WHERE id=?", (post_id,))
            get_db().commit()
            flash(str(error), "error")
            return render_template("editor.html", post=None, categories=CATEGORIES)
        flash("Đã tạo bài viết.", "success")
        return redirect(url_for("admin_edit_post", post_id=post_id))
    return render_template("editor.html", post=None, categories=CATEGORIES)


@app.route("/admin/bai-viet/<int:post_id>/sua", methods=["GET", "POST"])
@admin_required
def admin_edit_post(post_id: int):
    post = get_db().execute(
        "SELECT * FROM posts WHERE id=?", (post_id,)
    ).fetchone()
    if not post:
        abort(404)
    if request.method == "POST":
        values = _form_values()
        if not values["title"] or values["category"] not in CATEGORIES:
            flash("Hãy nhập tiêu đề và chọn danh mục hợp lệ.", "error")
            return render_template(
                "editor.html", post=post, categories=CATEGORIES,
                media=get_post_media(post_id),
            )
        now = utc_now()
        published_at = post["published_at"]
        if values["status"] == "published" and not published_at:
            published_at = now
        elif values["status"] == "draft":
            published_at = None
        get_db().execute(
            "UPDATE posts SET title=?,excerpt=?,body_html=?,category=?,status=?,"
            "updated_at=?,published_at=? WHERE id=?",
            (
                values["title"], values["excerpt"], values["body_html"],
                values["category"], values["status"], now, published_at, post_id,
            ),
        )
        files_added = 0
        try:
            cover = request.files.get("cover")
            if cover and cover.filename:
                save_upload(cover, post_id, "cover")
                files_added += 1
            media_files = [
                item for item in request.files.getlist("media")
                if item and item.filename
            ]
            inline_files = [
                item for item in request.files.getlist("inline_media")
                if item and item.filename
            ]
            refs = _inline_media_refs(inline_files)
            if len(media_files) + len(inline_files) + files_added > MAX_FILES_PER_POST:
                raise ValueError(f"Mỗi lần tối đa {MAX_FILES_PER_POST} tệp mới.")
            for item in media_files:
                save_upload(item, post_id, "media")
            body_html = _save_inline_media(
                post_id, values["body_html"], inline_files, refs
            )
            get_db().execute(
                "UPDATE posts SET body_html=? WHERE id=?", (body_html, post_id)
            )
            get_db().commit()
        except (ValueError, OSError) as error:
            get_db().rollback()
            discard_saved_uploads()
            flash(str(error), "error")
            return redirect(url_for("admin_edit_post", post_id=post_id))
        flash("Đã lưu bài viết.", "success")
        return redirect(url_for("admin_edit_post", post_id=post_id))
    return render_template(
        "editor.html", post=post, categories=CATEGORIES,
        media=get_post_media(post_id),
    )


@app.post("/admin/bai-viet/<int:post_id>/xoa")
@admin_required
def delete_post(post_id: int):
    media = get_db().execute(
        "SELECT filename FROM media WHERE post_id=?", (post_id,)
    ).fetchall()
    cursor = get_db().execute("DELETE FROM posts WHERE id=?", (post_id,))
    if cursor.rowcount == 0:
        abort(404)
    get_db().commit()
    for item in media:
        try:
            (UPLOAD_DIR / item["filename"]).unlink(missing_ok=True)
        except OSError:
            app.logger.exception("Không xóa được media của bài %s", post_id)
    flash("Đã xóa bài viết.", "success")
    return redirect(url_for("admin_dashboard"))


@app.post("/admin/media/<int:media_id>/xoa")
@admin_required
def delete_media(media_id: int):
    row = get_db().execute(
        "SELECT post_id FROM media WHERE id=?", (media_id,)
    ).fetchone()
    if not row:
        abort(404)
    post_id = row["post_id"]
    remove_media(media_id, post_id)
    get_db().commit()
    flash("Đã xóa tệp.", "success")
    return redirect(url_for("admin_edit_post", post_id=post_id))


@app.route("/admin/cai-dat", methods=["GET", "POST"])
@admin_required
def admin_settings():
    if request.method == "POST":
        values = {
            "site_title": request.form.get("site_title", "").strip()[:100],
            "tagline": request.form.get("tagline", "").strip()[:240],
            "author": request.form.get("author", "").strip()[:80],
            "about": request.form.get("about", "").strip()[:3000],
            "contact_url": request.form.get("contact_url", "").strip()[:300],
        }
        contact = urlparse(values["contact_url"]) if values["contact_url"] else None
        if contact and (
            contact.scheme not in {"http", "https"} or not contact.netloc
        ):
            flash("Liên kết liên hệ cần bắt đầu bằng http:// hoặc https://.", "error")
            return render_template("settings.html", values=values)
        if not values["site_title"]:
            flash("Tên blog không được để trống.", "error")
            return render_template("settings.html", values=values)
        get_db().executemany(
            "INSERT INTO settings(key,value) VALUES(?,?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            values.items(),
        )
        get_db().commit()
        flash("Đã cập nhật thông tin blog.", "success")
        return redirect(url_for("admin_settings"))
    return render_template("settings.html", values=site_settings())


@app.cli.command("create-admin")
def create_admin() -> None:
    """Tạo tài khoản quản trị đầu tiên bằng lời nhắc tương tác."""
    init_db()
    username = input("Tên đăng nhập admin: ").strip()
    if not re.fullmatch(r"[A-Za-z0-9_.-]{3,40}", username):
        raise SystemExit("Tên đăng nhập phải có 3-40 ký tự: chữ, số, _, . hoặc -.")
    connection = sqlite3.connect(DATABASE)
    exists = connection.execute("SELECT 1 FROM admins LIMIT 1").fetchone()
    if exists:
        connection.close()
        raise SystemExit("Đã có tài khoản admin. Không tạo thêm bằng lệnh này.")
    password = getpass.getpass("Mật khẩu (ít nhất 12 ký tự): ")
    confirmation = getpass.getpass("Nhập lại mật khẩu: ")
    if len(password) < 12 or password != confirmation:
        connection.close()
        raise SystemExit("Mật khẩu phải từ 12 ký tự và hai lần nhập phải trùng nhau.")
    connection.execute(
        "INSERT INTO admins(username,password_hash,created_at) VALUES(?,?,?)",
        (
            username,
            generate_password_hash(password, method="pbkdf2:sha256"),
            utc_now(),
        ),
    )
    connection.commit()
    connection.close()
    print("Đã tạo tài khoản admin.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Quang Đông Japan Blog")
    parser.add_argument("--host", default=os.environ.get("BLOG_HOST", "127.0.0.1"))
    parser.add_argument(
        "--port", type=int, default=int(os.environ.get("BLOG_PORT", "8080"))
    )
    args = parser.parse_args()
    init_db()
    app.run(host=args.host, port=args.port, debug=False)