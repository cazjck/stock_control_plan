# Triển khai lên web-01

App chạy trên web-01 (VM 100, `192.168.1.20`, user `pdk`) bằng **dịch vụ systemd cấp user**, không cần root,
nghe **chỉ trong máy** ở `127.0.0.1:8010`. Ra internet qua nginx của aaPanel và Cloudflare Tunnel, tên miền `stock.pdk.one`.

| Thành phần | Vị trí |
|---|---|
| Code | `~/apps/stock_control_plan` (git, nhánh `main`) |
| Giao diện đã build | `~/apps/stock_control_plan/frontend/dist` (build ở dev-01 rồi rsync) |
| Cấu hình, khoá API | `~/apps/stock_control_plan/backend/.env` (quyền 600, không nằm trong git) |
| Dữ liệu (SQLite, phiên TCBS) | `~/apps/stock_control_plan/backend/data` (quyền 700) |
| Dịch vụ | `~/.config/systemd/user/stockctl.service`, user `pdk` đã bật linger nên tự chạy khi máy khởi động |

## Cập nhật phiên bản mới
Commit và push lên `main`, rồi ở dev-01:
```bash
./scripts/deploy-web01.sh
```
Script không bao giờ ghi đè `.env` hay `data` trên máy chủ. Lần đầu dùng `--init` để chép dữ liệu và tạo `.env`.

## Xem trạng thái, log
```bash
ssh pdk@192.168.1.20 systemctl --user status stockctl
ssh pdk@192.168.1.20 journalctl --user -u stockctl -n 100
```

## Mã truy cập
`.env` trên máy chủ có `APP_ACCESS_TOKEN` ngẫu nhiên. Mọi request `/api` phải gửi mã này. Lần đầu mở app, các trang báo thiếu mã; nhập mã ở trang Thiết lập, trình duyệt sẽ nhớ.
Xem mã:
```bash
ssh pdk@192.168.1.20 grep APP_ACCESS_TOKEN apps/stock_control_plan/backend/.env
```

## Đưa ra internet (làm một lần)
Theo quy ước trong runbook homelab ("Thêm website khách trên web-01"):
1. **aaPanel** → Website → Add site `stock.pdk.one`, không bật SSL. Vào site → Reverse proxy → thêm: target `http://127.0.0.1:8010`,
   gửi host `$host`, tắt cache. Luồng giá realtime dùng Server-Sent Events; backend đã gửi `X-Accel-Buffering: no`
   nên nginx không gom bộ đệm.
2. **Cloudflare Zero Trust** → tunnel CT 200 → Public Hostname: `stock.pdk.one` → `HTTP` `192.168.1.20:80`.
3. **Nên thêm Cloudflare Access** cho `stock.pdk.one` với policy `homelab-owner-only` như `pve.pdk.one`.
   App chứa danh mục, dư nợ và khoá API TCBS; mã truy cập của app là lớp thứ hai, không nên là lớp duy nhất.
4. Thêm URL vào uptime check trên VPS nếu muốn (`/api/health` không cần mã).

## Lưu ý
- web-01 và dev-01 mỗi máy một bản dữ liệu. Sau khi chuyển sang web-01, chỉ ghi Sổ danh mục, kế hoạch, quyết định gồng ở web-01.
- Phiên TCBS (JWT) sống khoảng 24 giờ. Khi hết hạn, nhập iOTP lại trên giao diện ở `stock.pdk.one`.
- Tài nguyên: dịch vụ giới hạn 600 MB RAM (`MemoryMax`); web-01 có 2,8 GB dùng chung với aaPanel, MySQL, Redis.
