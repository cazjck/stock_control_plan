# Bảng tính năng Dashboard quản trị rủi ro

Phạm vi: **read-only**. Hệ thống chỉ đọc dữ liệu tài khoản và thị trường qua broker adapter (TCBS iFlash, DNSE LightSpeed), tính toán và cảnh báo. Không có bất kỳ chức năng đặt, sửa, hủy lệnh hay chuyển tiền.

Mức ưu tiên: **P0** = MVP phải có, **P1** = ngay sau MVP, **P2** = khi rảnh.

## 1. Tổng quan rủi ro (màn hình mở đầu mỗi sáng)

| # | Tính năng | Mô tả | Nguồn dữ liệu | Ưu tiên |
|---|---|---|---|---|
| 1.1 | Đồng hồ RTT | Tỷ lệ ký quỹ hiện tại so với 3 ngưỡng initial / maintenance / liquidation, tô màu xanh-vàng-đỏ | TCBS `/hydros/v1/account/{acc}/risk`; DNSE gói vay + vị thế theo Deal | P0 |
| 1.2 | Khoảng cách đến call margin | Thị trường giảm thêm bao nhiêu % thì chạm maintenance, bao nhiêu % thì bị giải chấp | Tính từ 1.1 + giá trị danh mục | P0 |
| 1.3 | Tổng quan tài sản | NAV, tổng giá trị cổ phiếu, tiền mặt, tổng dư nợ, lãi lỗ chưa thực hiện | TCBS `/aion/v1/accounts/{acc}/se`, `/cashInvestments`; DNSE balances + positions | P0 |
| 1.4 | Chi phí gồng mỗi ngày | Lãi margin phải trả mỗi ngày và luỹ kế tháng, đổi ra % NAV | TCBS `/erebos/v2/digital/margin-info`; DNSE loan packages interestRate | P0 |
| 1.5 | Thẻ cảnh báo nổi bật | 3 cảnh báo nghiêm trọng nhất đang mở (xem mục 5) | Risk engine | P0 |
| 1.6 | Trạng thái kết nối | Broker đang dùng, token còn hiệu lực bao lâu, dữ liệu cập nhật lúc nào, phiên giao dịch đang ở trạng thái nào | Adapter session + market session | P0 |
| 1.7 | Lịch sử RTT 30 ngày | Biểu đồ đường RTT theo ngày để thấy xu hướng rủi ro | Snapshot lưu SQLite mỗi ngày | P1 |

## 2. Danh mục nắm giữ

| # | Tính năng | Mô tả | Nguồn dữ liệu | Ưu tiên |
|---|---|---|---|---|
| 2.1 | Bảng vị thế | Mã, khối lượng, giá vốn, giá thị trường, lãi lỗ tiền và %, tỷ trọng trong danh mục | Positions + quote | P0 |
| 2.2 | Mức cắt lỗ đề xuất | Mỗi mã có mức cắt lỗ tính từ quy tắc: max(đỉnh 20 phiên × (1 − X%), close − k × ATR14); X, k cấu hình được | OHLCV + TA-Lib | P0 |
| 2.3 | Nhãn trạng thái | "An toàn", "Cảnh báo" (close < SMA20 và RSI < 40), "Chạm cắt lỗ" (close < mức 2.2) | Indicators | P0 |
| 2.4 | Chỉ báo tóm tắt | RSI14, vị trí so với SMA20/SMA50, ATR14 %, MACD histogram dấu | TA-Lib | P0 |
| 2.5 | Sắp xếp theo mức khẩn | Mặc định xếp mã gần/đã chạm cắt lỗ lên trên, mã lỗ nặng nhất tiếp theo | Client | P0 |
| 2.6 | Margin theo Deal (DNSE) | Với DNSE hiển thị tỷ lệ từng Deal và ngưỡng riêng; với TCBS gộp một dòng | MarginBucket model | P1 |
| 2.7 | Đóng góp rủi ro | Nếu bán mã này thì RTT cải thiện bao nhiêu, bao nhiêu tiền lãi/ngày giảm | Risk engine | P1 |
| 2.8 | Cập nhật giá trong phiên | Giá và lãi lỗ nhảy theo WebSocket, không cần tải lại | Stream quotes | P1 |

## 3. Chi tiết một mã

| # | Tính năng | Mô tả | Nguồn dữ liệu | Ưu tiên |
|---|---|---|---|---|
| 3.1 | Biểu đồ nến | Nến ngày với SMA20, SMA50, EMA20, đường cắt lỗ đề xuất, đường giá vốn | OHLCV D | P0 |
| 3.2 | Chỉ báo phụ | RSI14, MACD, ATR14 dưới biểu đồ chính | TA-Lib | P0 |
| 3.3 | Đổi khung thời gian | 15 phút, 1 giờ, ngày, tuần | TCBS bars + bars-long-term; DNSE /price/ohlc | P1 |
| 3.4 | Sổ lệnh và khối ngoại | Top bid/ask, khối ngoại mua bán ròng trong ngày, room còn lại | TCBS WS kênh 1/2/3, `/tartarus/v1/tickerSnaps`; DNSE top_price, foreign | P1 |
| 3.5 | Cung cầu | Mua chủ động / bán chủ động theo ngày và 15 phút | TCBS `/nyx/v1/intraday/{t}/bsa*`; DNSE tick_extra | P2 |
| 3.6 | Lịch sử cảnh báo của mã | Các lần mã này chạm cảnh báo trước đây | SQLite | P2 |

## 4. Margin và nợ vay

| # | Tính năng | Mô tả | Nguồn dữ liệu | Ưu tiên |
|---|---|---|---|---|
| 4.1 | Danh sách khoản vay | Ngày giải ngân, ngày đáo hạn, gốc, lãi dồn, lãi suất, số ngày đã vay | TCBS `/erebos/v2/digital/margin-info`, `/khaos/v1/loan/{acc}`; DNSE loans | P0 |
| 4.2 | Lịch đáo hạn | Khoản nào đến hạn trong 7 / 14 / 30 ngày tới, số tiền cần chuẩn bị | Tính từ 4.1 | P0 |
| 4.3 | Tiền cần nộp để về an toàn | Nộp thêm bao nhiêu tiền thì RTT về trên maintenance với biên 5% | Risk engine | P0 |
| 4.4 | Chính sách margin theo mã | Tỷ lệ cho vay từng mã, mã nào bị cắt margin | TCBS `/hydros/v1/account/{acc}/pricing-policy`; DNSE loan packages | P1 |
| 4.5 | Sao kê tiền | Lịch sử nộp, rút, lãi đã trả theo tháng | TCBS `/erebos/v2/digital/trans-hist-cashStatements` | P2 |

## 5. Cảnh báo

| # | Tính năng | Mô tả | Nguồn dữ liệu | Ưu tiên |
|---|---|---|---|---|
| 5.1 | Quy tắc cắt lỗ theo mã | Bắn khi giá đóng cửa (hoặc giá hiện tại nếu bật trong phiên) thấp hơn mức 2.2 | Indicators + quote | P0 |
| 5.2 | Quy tắc RTT | Bắn khi RTT cách maintenance dưới N điểm %, mức N cấu hình | Margin | P0 |
| 5.3 | Quy tắc đáo hạn | Bắn trước ngày đáo hạn 7 ngày và 1 ngày | Loans | P0 |
| 5.4 | Quy tắc lỗ danh mục | Bắn khi tổng lỗ chưa thực hiện vượt ngưỡng % NAV do người dùng đặt | Positions | P0 |
| 5.5 | Trung tâm cảnh báo | Danh sách cảnh báo mở, đã xem, đã xử lý; mỗi cảnh báo có lý do và số liệu tại thời điểm bắn | SQLite | P0 |
| 5.6 | Gửi Telegram | Đẩy cảnh báo P0 lên Telegram bot của bạn | Telegram Bot API | P1 |
| 5.7 | Báo cáo sáng | Tin nhắn tóm tắt 8:30 mỗi ngày giao dịch: RTT, lãi/ngày, mã cần chú ý, khoản sắp đáo hạn | Scheduler | P1 |
| 5.8 | Chống nhiễu | Một quy tắc chỉ bắn lại sau khoảng cooldown, không spam trong phiên | Risk engine | P1 |

## 6. Kịch bản giả định (stress test)

| # | Tính năng | Mô tả | Nguồn dữ liệu | Ưu tiên |
|---|---|---|---|---|
| 6.1 | Thị trường giảm X% | Kéo thanh trượt −5% / −10% / −15%, xem RTT, lãi lỗ, tiền cần nộp | Risk engine | P1 |
| 6.2 | Bán thử một phần | Chọn mã và khối lượng giả định bán, xem RTT và lãi/ngày sau đó | Risk engine | P1 |
| 6.3 | Nộp thêm tiền giả định | Nhập số tiền, xem RTT mới | Risk engine | P1 |
| 6.4 | Kịch bản từng mã giảm sàn | Mã lớn nhất giảm sàn 2 phiên liên tiếp thì chuyện gì xảy ra | Risk engine | P2 |

## 7. Nhật ký kỷ luật

| # | Tính năng | Mô tả | Nguồn dữ liệu | Ưu tiên |
|---|---|---|---|---|
| 7.1 | Snapshot hằng ngày | Tự lưu danh mục, RTT, dư nợ cuối mỗi ngày | Scheduler + SQLite | P0 |
| 7.2 | Ghi chú quyết định | Khi một cảnh báo được đánh dấu "đã xử lý", ghi lại bạn đã làm gì và vì sao | SQLite | P1 |
| 7.3 | Đối chiếu kỷ luật | So sánh mức cắt lỗ đề xuất với giá bạn thực sự bán (đọc từ lịch sử khớp lệnh), đếm số lần không tuân thủ | TCBS `/aion/v1/accounts/{acc}/matching-details`; DNSE order history | P2 |
| 7.4 | Báo cáo tháng | Lãi lỗ thực hiện, lãi margin đã trả, số cảnh báo, tỷ lệ tuân thủ | SQLite | P2 |

## 8. Thiết lập

| # | Tính năng | Mô tả | Ưu tiên |
|---|---|---|---|
| 8.1 | Chọn broker | Bật TCBS, DNSE hoặc cả hai; mỗi broker có trang nhập key riêng, key lưu `.env` phía server | P0 |
| 8.2 | Nhập OTP buổi sáng | Form nhập iOTP (TCBS) để lấy token, hiển thị hạn token; DNSE không cần | P0 |
| 8.3 | Tham số rủi ro | X% cắt lỗ từ đỉnh, hệ số k × ATR, biên RTT, ngưỡng lỗ danh mục, số ngày báo trước đáo hạn | P0 |
| 8.4 | Kênh cảnh báo | Bật tắt Telegram, giờ gửi báo cáo sáng | P1 |
| 8.5 | Chế độ dữ liệu mẫu | Chạy dashboard bằng fixture JSON để phát triển hoặc demo không cần token | P0 |

## Ràng buộc chung

- Mọi màn hình có nhãn **READ-ONLY** cố định ở header. Không có nút mua, bán, hủy ở bất kỳ đâu.
- Số liệu luôn kèm thời điểm lấy dữ liệu; dữ liệu cũ hơn 5 phút trong phiên bị tô xám.
- Tiền hiển thị theo VND, làm tròn nghìn; tỷ lệ hiển thị 1 chữ số thập phân.
- Thiết kế mobile-first cho màn hình 1, 2, 5 vì bạn sẽ xem trên điện thoại trong phiên.

## Trạng thái triển khai (16/10/2026)

Toàn bộ nhóm **P0** đã có trong ứng dụng (backend FastAPI, frontend React/Vite). Xem README để chạy.

| Mục | Trạng thái | Ghi chú |
|---|---|---|
| 1.1 đến 1.6 Tổng quan | Có | Thước mớn nước thay cho đồng hồ RTT dạng tròn |
| 2.1 đến 2.5 Danh mục | Có | Trạng thái thêm "Hàng kẹt" theo mục 6 của bộ luật |
| 3.1 đến 3.2 Chi tiết mã | Có | Khung ngày và tuần; khung 15 phút và 1 giờ (3.3) để sau |
| 4.1 đến 4.3 Margin và nợ | Có | |
| 5.1 đến 5.5 Cảnh báo | Có | Có ghi chú "đã xử lý"; điều kiện còn thì cảnh báo mở lại như vi phạm mới |
| 7.1 Snapshot hằng ngày | Có | Tự chạy 15:15 các ngày giao dịch, chụp tay được |
| 8.1, 8.2, 8.3, 8.5 Thiết lập | Có | Đổi luật khi đang có vị thế phải xác nhận, mọi lần đổi vào nhật ký |
| 6.1 đến 6.3 Kịch bản giả định | Có | Trang `/scenarios`, giả định ghi rõ trên trang |
| Máy tính khối lượng mua (mục 1 của bộ luật) | Có | Ở trang chi tiết mã, vốn = tiền mặt thực có |
| Các mục P1 và P2 còn lại | Chưa | Danh sách trong README |
