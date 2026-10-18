# Mớn nước: quản trị rủi ro chứng khoán, chỉ đọc

Dashboard cá nhân giúp thấy ngay hai điều mỗi sáng: **còn cách bị gọi ký quỹ bao xa** và **hôm nay phải làm gì với từng mã**.
Dữ liệu lấy từ API của công ty chứng khoán (TCBS iFlash, DNSE LightSpeed), tính toán theo bộ luật kỷ luật trong
[docs/trading-rules.md](docs/trading-rules.md), và cảnh báo khi một luật bị chạm.

**Ứng dụng này chỉ đọc dữ liệu. Không có chức năng đặt, sửa, hủy lệnh hay chuyển tiền.** Quyết định bán vẫn là của bạn, thực hiện trên app của công ty chứng khoán.

## Chạy thử ngay bằng dữ liệu mẫu

```bash
make setup     # lần đầu: tạo venv, cài thư viện backend và frontend
make demo      # build frontend, chạy backend với dữ liệu mẫu
```

Mở http://127.0.0.1:8000. Dữ liệu mẫu có đủ các trạng thái: chạm cắt lỗ, hàng kẹt, cảnh báo, tới mốc chốt lời, RTT gần ngưỡng.

Phát triển: `make backend` và `make frontend` ở hai terminal, mở http://localhost:5173.

## Dùng với tài khoản thật

Sao chép `backend/.env.example` thành `backend/.env` rồi điền khóa. Khóa chỉ nằm trên máy chủ, không bao giờ gửi tới trình duyệt.

| Broker | Lấy khóa ở đâu | Cần nhập hằng ngày |
|---|---|---|
| **TCBS** | TCInvest, Tiện ích, iFlash Open API (miễn phí). Điền `TCBS_API_KEY` và `TCBS_CUSTODY_CODE` (số lưu ký, dạng 105C…) | Mã **iOTP** từ app TCInvest, nhập ở trang Thiết lập. Token sống tối đa 8 giờ |
| **DNSE** | Entrade X, Họ tên, Thông tin tài khoản, LightSpeed API. Điền `DNSE_API_KEY` và `DNSE_API_SECRET` (Secret chỉ hiện một lần) | Không. Đọc dữ liệu không cần OTP |

Đặt `BROKERS=tcbs`, `BROKERS=dnse` hoặc `BROKERS=tcbs,dnse`. Chọn broker và tiểu khoản ở thanh trên cùng.
Nếu mở truy cập từ máy khác, đặt `APP_ACCESS_TOKEN` để mọi request phải kèm mã. **Không đưa ứng dụng ra Internet công cộng.** Mặc định chỉ lắng nghe `127.0.0.1`.

## Bảng giá và từng lần mua

- **Bảng giá** chỉ hiện các mã trong danh mục đang chọn, đủ cột như bảng điện (trần, sàn, tham chiếu, ba bước giá mua và bán, khớp lệnh, khối ngoại) kèm khối lượng đang giữ, giá vốn và lãi lỗ của bạn. Giá cập nhật trực tiếp: backend giữ một kết nối WebSocket chỉ đọc tới bảng giá TCBS và đẩy xuống trình duyệt qua Server-Sent Events. Nếu luồng lỗi, trang tự làm mới mỗi 5 giây. DNSE chưa có luồng trực tiếp.
- **Các lần mua** ở trang chi tiết mã: ngày mua, số lượng, giá mua, lãi lỗ từng lô. Lô mới được tự phát hiện khi khối lượng tăng (TCBS, DNSE), lấy từ lệnh mua trong Sổ danh mục, hoặc ghi tay từ lịch sử lệnh. API của TCBS chỉ trả lệnh trong ngày, nên lịch sử cũ phải ghi tay.
- **Lô mua thêm khi đang lỗ** có mức cắt lỗ và hạn riêng (mục 3.5 bộ luật). Khi phải bán, cảnh báo không tắt được bằng nút "đã xem", trang Tổng quan có dải đỏ, và ứng dụng đếm số phiên chần chừ cùng tiền mất thêm.

## Khuyến nghị chốt lời

Mỗi mã đang lãi có một khuyến nghị duy nhất cho hôm nay ở trang chi tiết mã, kèm số cổ phiếu cần bán. Khuyến nghị được rút ra từ ba nhánh: chốt theo bậc giá mục tiêu, bán vào sức mạnh khi có từ hai dấu hiệu tăng cao trào, và bán khi yếu đi để giữ lãi. Trang có bảng kiểm từng dấu hiệu kèm số liệu để bạn tự đối chiếu. Thứ tự ưu tiên và nguồn tham khảo nằm ở mục 4b của [docs/trading-rules.md](docs/trading-rules.md). Trang Tổng quan có khối "Cơ hội chốt lời".

## Đảo hàng khi hồi (mã đang lỗ)

Với mã đang lỗ, trang chi tiết có mục "Đảo hàng khi hồi". Ứng dụng đo nhịp hồi từ đáy 20 phiên và khuyên bán 30% khi hồi 10% hoặc lấy lại 38,2% đoạn giảm, thêm 20% khi hồi 20% hoặc lấy lại 50%. Tổng không quá một nửa lượng đang giữ. Sau khi bạn ghi lệnh bán đã khớp, ứng dụng theo dõi vùng mua lại: giá thấp hơn giá bán từ 7%, vẫn trên đáy cũ, có phiên đảo chiều, tiền đã về. Mua lại không bao giờ vượt số đã bán. Hàng kẹt nhóm B và tài khoản margin sát ngưỡng chỉ được bán, không được mua lại. Lô mua thêm đã tới luật bán (mục 3.5) luôn được nhắc trước. Luật và nguồn ở mục 6b của [docs/trading-rules.md](docs/trading-rules.md).

## Sổ danh mục tổng (SSI, VPS và các công ty chưa có API)

Trang **Sổ danh mục** gom mọi tài khoản về một chỗ. Mỗi công ty là một tiểu danh mục:

- **Nhập tay** cho công ty chưa có API: ghi lệnh mua bằng số lượng cùng giá mỗi cổ phiếu hoặc tổng tiền (mua thêm tự tính lại giá vốn bình quân), ghi khoản nợ margin, tiền mặt, ngưỡng duy trì và giải chấp. Ô số tiền hiểu được `28.000`, `28tr`, `1,2 tỷ`.
- **Đồng bộ** từ broker có API (TCBS, DNSE): chép danh mục, tiền, khoản vay và RTT hiện tại. Phần đồng bộ không sửa tay, muốn cập nhật thì đồng bộ lại. Trang TCBS gốc vẫn là dữ liệu trực tiếp.

Chọn **Danh mục tổng** ở ô broker để xem toàn bộ rủi ro: cùng một mã ở nhiều công ty được gộp, còn ký quỹ tính riêng từng công ty vì mỗi công ty gọi ký quỹ độc lập. Giá thị trường lấy từ TCBS khi đã đăng nhập, nếu không thì dùng giá ghi trong sổ.
Tỷ lệ ký quỹ của tiểu danh mục nhập tay có hai cách: tự tính vốn chủ trên giá trị tài sản từ dữ liệu bạn nhập, hoặc nhập RTT đang hiện trên app (kiểu TCBS) và để ứng dụng quy đổi theo giá mới.

## Bảo đảm chỉ đọc ở nhiều lớp

1. Giao diện `BrokerAdapter` không có phương thức nào liên quan tới lệnh hay tiền.
2. `ReadOnlyHttp` chỉ có `get`. Duy nhất `auth_post` tồn tại để lấy token, và chỉ tới những đường dẫn trong danh sách cho phép (TCBS: một đường dẫn đăng nhập; DNSE: không có).
3. Test quét mã nguồn adapter tìm lời gọi ghi và đường dẫn lệnh, và đếm mọi request ra ngoài thực tế (chỉ `GET` và một `POST` lấy token).
4. Test kiểm tra mọi route ghi của API chỉ phục vụ sổ sách của chính ứng dụng (cảnh báo, kế hoạch, luật, snapshot, sổ danh mục). Đồng bộ sổ chỉ đọc từ broker.

## Cấu trúc

```
backend/
  app/brokers/    adapter TCBS, DNSE, demo + ReadOnlyHttp
  app/risk/       risk engine thuần túy: chỉ báo (TA-Lib), cắt lỗ, chốt lời, margin, cảnh báo
  app/services/   điều phối, cache ngắn, luật có thể chỉnh
  app/storage/    SQLite: kế hoạch từng mã, cảnh báo, snapshot, nhật ký đổi luật
  rules/default.yaml   bộ luật (nguồn sự thật cho tham số)
  fixtures/demo/       dữ liệu mẫu
frontend/         React + Vite + TypeScript + Tailwind; biểu đồ bằng lightweight-charts
docs/             bảng tính năng dashboard và bộ luật giao dịch (kèm nguồn tham khảo)
```

Thêm một công ty chứng khoán: viết một lớp kế thừa `BrokerAdapter` trả về các model chuẩn hoá trong `app/models.py`, đăng ký trong `registry.py`. Risk engine và giao diện không phải sửa.
Khác biệt lớn nhất giữa các broker là margin: TCBS tính một tỷ lệ cho cả tài khoản, DNSE tính riêng từng Deal (mã và gói vay). Model `MarginBucket` chứa cả hai.

## Mức độ kiểm chứng với dữ liệu thật

**TCBS: đã chạy với một tài khoản thật ngày 16/10/2026.** Ba chỗ phản hồi thật khác OpenAPI spec và đã được sửa, có test giữ nguyên cấu trúc thật:

- Danh mục (`/aion/.../se`) trả mảng `stock` với `totalQtty`, `costPrice`, `currentPrice`, không phải `assets`.
- Tỷ lệ ký quỹ (`/hydros/.../risk`) trả **một đối tượng**, không phải mảng.
- Danh sách khoản vay: endpoint trong spec (`margin-info`) trả rỗng và đòi tham số `todate` chữ thường. Dữ liệu thật nằm ở `/khaos/v1/loan/{tiểu khoản}`. Tổng gốc còn lại khớp dư nợ gốc của `/risk`, tổng lãi khớp lãi dồn.

**RTT của TCBS là tài sản đảm bảo trên dư nợ**, không phải vốn chủ trên giá trị tài sản (ban đầu 100, duy trì 85, giải chấp 80). Khoảng cách tới gọi ký quỹ của TCBS tính theo `x = 1 − duy trì / RTT`. Công thức giả định toàn bộ tài sản đảm bảo giảm đều theo giá, nên hãy đối chiếu con số "Giảm thêm X% là bị gọi ký quỹ" với app TCInvest trước khi dựa vào nó.

**DNSE: chưa chạy với tài khoản thật.** Adapter viết theo spec và kiểm tra bằng phản hồi mô phỏng. Rất có thể có khác biệt tương tự. Các lỗi cấu trúc được báo rõ ràng ("phản hồi không đúng cấu trúc dự kiến") thay vì làm sập trang. Giả định hiện tại: tỷ lệ của DNSE là vốn chủ trên giá trị tài sản theo từng Deal.

Còn lại cần để ý:

- **Đơn vị tỷ lệ.** Giá trị từ 1,5 trở xuống được coi là phân số. Giá trị gốc nằm trong trường `raw` của mỗi nhóm ký quỹ.
- **Thang giá.** Mã tự phát hiện khi giá vốn, giá thị trường và nến lệch nhau ~1000 lần và ghi chú ở trang Danh mục.
- **TCBS không công bố rate limit.** Backend cache dữ liệu 30 giây, nến ngày 30 phút, và giới hạn 4 request nến chạy song song.
- **Ngày mua và bậc chốt lời đã bán không có trong API.** Bạn khai báo ở trang chi tiết từng mã. Khi chưa khai báo, đỉnh lãi được ước lượng theo 20 phiên gần nhất và được ghi rõ là ước lượng.
- **Tiểu khoản thường của TCBS** trả mã 403 cho endpoint ký quỹ và khoản vay. Ứng dụng coi đó là "không áp dụng", không phải hết phiên.
- **Token TCBS** quan sát thấy sống khoảng 24 giờ (đọc từ trường hết hạn trong token), dài hơn 8 giờ trong tài liệu.

## Chưa làm (nhóm P1 và P2 trong docs/dashboard-features.md)

Stream giá realtime (giao diện đang làm mới mỗi 20 giây trong giờ giao dịch), nhắc qua Telegram, báo cáo sáng, kịch bản từng mã giảm sàn (6.4), đối chiếu kỷ luật từ lịch sử khớp lệnh, tự hiệu chỉnh cắt lỗ theo Minervini (cần nhật ký lệnh đã đóng), xem gộp nhiều broker.

## Thông báo, giá gọi ký quỹ, sao lưu

- **Thông báo Telegram:** cảnh báo mới được gửi vào Telegram của bạn, cài ở trang Thiết lập. Chỉ gửi tin, không đặt lệnh.
- **Giá gọi ký quỹ từng mã:** trang Danh mục và trang chi tiết ghi rõ "tài khoản bị gọi ký quỹ nếu mã này đóng cửa dưới X", giả định các mã khác đứng giá.
- **Sao lưu:** SQLite được sao lưu mỗi đêm trên web-01 và kéo về dev-01.
- **Bản tin đầu và cuối phiên:** 8:45 và 15:20 các ngày thường, gửi qua Telegram: ký quỹ, giá gọi ký quỹ, tối đa ba việc cần làm; cuối phiên thêm biến động trong ngày.
- **Trước khi mua:** trang Trước khi mua, hoặc nhắn `/kiemtra PDR 2000` cho bot. App đối chiếu lệnh mua dự định với bộ luật
  (thị trường, vốn, số mã, mua bình quân giá xuống, ký quỹ, giai đoạn xu hướng, tín hiệu vào lệnh, số lệnh mỗi ngày) và trả lời được mua, cân nhắc hay không nên mua.

## Triển khai

App đang chạy trên web-01, ra internet qua Cloudflare Tunnel ở `stock.pdk.one`. Cách cập nhật và cấu hình: [docs/deploy.md](docs/deploy.md).

## Kiểm thử

```bash
make test
```

Backend: luật cắt lỗ, chốt lời, 8 tuần, hàng kẹt, công thức margin, cảnh báo, ánh xạ dữ liệu của hai adapter, API, tính chỉ đọc. Frontend: hình học thước mớn nước, định dạng số, câu kết luận, thành phần chính.

Giao diện dùng [Lightweight Charts](https://github.com/tradingview/lightweight-charts) của TradingView (Apache-2.0), logo ghi nhận nguồn nằm ở góc biểu đồ theo yêu cầu giấy phép.
Công cụ chỉ phục vụ kỷ luật cá nhân, không phải khuyến nghị đầu tư.
