# Quang Đông Japan

Blog tiếng Việt để chia sẻ trải nghiệm sống ở Nhật. Trang quản trị hỗ trợ tạo,
chỉnh sửa, lưu nháp và xuất bản bài viết, kèm ảnh/video và thông tin blog.

## Chạy trên máy cá nhân

Yêu cầu Python 3.9 trở lên.

```sh
cd quang-dong-japan-blog
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
flask --app app create-admin
python app.py
```

Mở `http://127.0.0.1:8080`. Lệnh `create-admin` sẽ hỏi tên đăng nhập và mật khẩu
tối thiểu 12 ký tự. Tài khoản admin chỉ được tạo một lần; ứng dụng không cung
cấp đăng ký công khai. Đăng nhập quản trị trực tiếp tại `/admin/login`; liên kết
quản trị không hiển thị trên giao diện công khai.

Để thêm quản trị viên hoặc đặt lại mật khẩu, chạy `python manage_admins.py`,
chọn thao tác `a` (thêm) hoặc `r` (đặt lại), rồi nhập tên đăng nhập và mật khẩu
theo lời nhắc. Mật khẩu chỉ được lưu dưới dạng hash; không truyền mật khẩu trên
dòng lệnh.

Nếu hosting không cấp Shell, có thể dùng biến môi trường: đặt
`BLOG_ADMIN_USERNAME` và `BLOG_ADMIN_PASSWORD` trong phần Environment của dịch
vụ rồi deploy/restart app. Sau khi khởi động, đăng nhập tại `/admin/login`.
Giữ biến mật khẩu nếu filesystem/database của gói hosting không bền vững qua
các lần restart; xóa biến này sau khi dùng chỉ khi database được lưu bền vững.

Trong VS Code, chọn interpreter `.venv/bin/python` (Python: Select Interpreter)
để Pylance dùng đúng Flask/Werkzeug đã cài trong môi trường dự án.

## Cấu hình

Sao chép `.env.example` thành `.env` rồi đặt các biến môi trường cần thiết. `.env`
không được đưa lên Git:

- `BLOG_SECRET_KEY`: khóa bí mật ngẫu nhiên dài, giữ nguyên qua các lần cập nhật.
  Nếu để trống, ứng dụng tạo khóa trong `BLOG_DATA_DIR/.secret-key`.
- `BLOG_DATA_DIR`: thư mục lưu SQLite, khóa bí mật tự sinh và nội dung upload.
  Mặc định là thư mục `data/` trong project; trên VPS hãy trỏ tới ổ đĩa bền vững
  riêng bên ngoài thư mục release.
- `BLOG_ADMIN_USERNAME` và `BLOG_ADMIN_PASSWORD`: tùy chọn để tạo/cập nhật tài
  khoản admin khi app khởi động. Chỉ đặt mật khẩu trong phần biến môi trường
  bảo mật của hosting, không ghi vào source code. Nếu đặt `BLOG_ADMIN_PASSWORD`,
  app sẽ đảm bảo tài khoản này có mật khẩu đó mỗi lần worker khởi động.
- `BLOG_HOST` và `BLOG_PORT`: địa chỉ bind và cổng khi chạy `python app.py`.
- `BLOG_COOKIE_SECURE=true`: bật cookie chỉ gửi qua HTTPS. Chỉ bật khi reverse
  proxy HTTPS đã được cấu hình.

Ứng dụng chấp nhận ảnh JPG, PNG, WEBP, GIF và video MP4, WEBM, MOV; mỗi lần
request tối đa 60 MB và tối đa 12 tệp media mới cho một bài. Trong trình soạn
thảo, đặt con trỏ tại vị trí cần chèn rồi bấm nút Ảnh hoặc Video để nhúng media
ngay trong nội dung, hoặc dùng nút Ảnh URL, Video URL, Nhúng web để hiển thị
media từ URL HTTPS bên ngoài mà không tải file đó về máy chủ. URL video tệp
trực tiếp dùng thẻ video; URL trang web dùng iframe sandbox và cần website nguồn
cho phép nhúng (một số nền tảng yêu cầu URL embed riêng hoặc chặn iframe). Ảnh
chèn bằng URL có thể đặt mô tả alt/title và chú thích hiển thị bên dưới ảnh; chọn
ảnh trong editor rồi bấm “Sửa tiêu đề/chú thích ảnh” để thay đổi. Ảnh tĩnh JPG,
PNG và WEBP được tự xoay theo EXIF, thu nhỏ tối đa còn 1920 px mỗi
chiều và nén sang WEBP chất lượng 82 trước khi lưu; nếu bản nén lớn hơn ảnh gốc
thì ảnh gốc được giữ nguyên. GIF và ảnh động được giữ nguyên để không làm mất
hoạt ảnh; video tải lên không bị chuyển đổi.

## Triển khai VPS bằng Gunicorn

Tạo virtual environment, cài dependencies và tạo admin như phần chạy local.
Sau đó cấu hình biến môi trường (hoặc nạp file env bằng service manager), trỏ
`BLOG_DATA_DIR` tới thư mục dữ liệu bền vững mà user chạy ứng dụng có quyền ghi,
và chạy:

```sh
gunicorn --workers 2 --bind 127.0.0.1:8080 app:app
```

Với Caddy, thêm site block riêng cho domain blog để Caddy tự cấp HTTPS:

```caddy
zenligai.online {
    reverse_proxy 127.0.0.1:8080
}
```

Khối trên chỉ phục vụ domain gốc `zenligai.online`; giữ nguyên site block hiện
có của `callback.zenligai.online` để bot tiếp tục hoạt động. Nếu dùng Nginx, cấu
hình tương tự để proxy domain blog tới `127.0.0.1:8080`. Không mở trực tiếp cổng
ứng dụng ra Internet. Bật `BLOG_COOKIE_SECURE=true` khi HTTPS hoạt động. Nên chạy
ứng dụng bằng user hệ thống riêng, hạn chế quyền ghi
vào thư mục dữ liệu, và cấu hình tự khởi động/giám sát bằng systemd hoặc process
manager hiện có.

## Sao lưu và cập nhật

Sao lưu cả file SQLite `blog.sqlite3` và thư mục `uploads/`; nên dừng ứng dụng
hoặc tạo bản sao nhất quán bằng SQLite backup API trước khi sao chép DB đang
chạy. Bảo quản cả `.secret-key` (hoặc giá trị `BLOG_SECRET_KEY`) để phiên đăng
nhập không bị vô hiệu sau khôi phục.

Khi cập nhật code, giữ nguyên `BLOG_DATA_DIR`, database, uploads và secret key.
Chỉ cập nhật dependencies theo `requirements.txt`, sau đó restart service. Không
xóa thư mục dữ liệu khi deploy phiên bản mới.
