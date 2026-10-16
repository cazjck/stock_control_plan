# Bộ luật giao dịch kỷ luật (phiên bản 2, đã đối chiếu với các phương pháp chuẩn)

Mục đích: thay cảm tính bằng con số. App chỉ **tính và nhắc** theo bộ luật này; việc bấm lệnh vẫn do bạn làm trên app công ty chứng khoán. Mọi tham số đều cấu hình được trong màn hình Thiết lập, nhưng **chỉ được đổi khi không có vị thế mở** để tránh sửa luật giữa chừng cho hợp với cảm xúc.

Phiên bản 2 đối chiếu từng luật với các trường phái quản trị rủi ro đã được kiểm chứng (O'Neil/IBD, Minervini, Elder, Van Tharp, Turtle, Chandelier Exit, nghiên cứu học thuật). Phần **Cơ sở tham khảo** ở cuối ghi rõ luật nào lấy từ đâu, luật nào là của riêng dự án. Các thay đổi so với phiên bản 1 được đánh dấu **[v2]**.

Bối cảnh thị trường Việt Nam ảnh hưởng đến con số:
- Biên độ HOSE ±7%/ngày, HNX ±10%, UPCOM ±15%. Một phiên giảm sàn HOSE là mất 7%.
- Cổ phiếu mua ngày T về tài khoản **chiều ngày T+2** (áp dụng từ 29/08/2022). Nghĩa là gần 2 ngày rưỡi đầu không thể cắt lỗ, nên khối lượng vào lệnh đầu phải nhỏ.
- Lô chẵn 100 cổ phiếu.

---

## 0. Hai chế độ, không trộn lẫn

| | Lướt sóng (swing) | Tích luỹ (DCA) |
|---|---|---|
| Mục tiêu | Lãi 10–25% trong 2–8 tuần | Nắm giữ 1 năm trở lên |
| Cách vào | Theo tín hiệu kỹ thuật, chia 4 lần | Theo **lịch** cố định, không nhìn giá |
| Trung bình giá xuống | **Cấm** | Cho phép, nhưng theo lịch |
| Cắt lỗ | Bắt buộc, theo % và ATR | Chỉ khi vi phạm luận điểm hoặc rơi quá ngưỡng thảm hoạ |
| Margin | Cấm | Cấm |

Mỗi mã khi mua phải được gắn một chế độ. Mã swing không được "chuyển thành đầu tư dài hạn" khi đang lỗ. Đây là lỗi phổ biến nhất và là nguồn gốc của kẹt hàng. Hiện tượng này có tên trong tài chính hành vi là **disposition effect**: nhà đầu tư cá nhân bán mã lãi quá sớm và giữ mã lỗ quá lâu, và các mã lỗ họ giữ lại sau đó sinh lời kém hơn các mã lãi họ đã bán (Odean 1998, xem mục tham khảo).

---

## 1. Quy mô vị thế (áp dụng cả hai chế độ)

| Tham số | Giá trị mặc định | Giải thích |
|---|---|---|
| Vốn giao dịch (`capital`) | Tiền mặt thực có, **không tính margin** | Margin chỉ dùng lại sau 6 tháng tuân thủ 90% luật |
| Rủi ro tối đa mỗi mã (`risk_per_trade`) | **1,5% capital** | Nằm giữa mức 1% của Minervini/Turtle và trần 2% của Elder. Số tiền chấp nhận mất nếu dính cắt lỗ |
| Tỷ trọng tối đa một mã (`max_weight`) | **20% capital** | Không mã nào được quá 1/5 vốn |
| Số mã tối đa (`max_positions`) | **5** | Nhiều hơn là không theo dõi nổi |
| Tổng rủi ro đang mở + lỗ đã thực hiện trong tháng (`monthly_risk_budget`) | **6% capital** **[v2]** | Luật 6% của Elder: khi (lỗ đã chốt trong tháng + tổng khoảng cách đến cắt lỗ của mọi vị thế mở) chạm 6%, **ngừng mở vị thế mới đến hết tháng** |

**Công thức khối lượng kế hoạch cho một mã:**

```
risk_money      = capital × risk_per_trade
stop_distance   = giá vào dự kiến − giá cắt lỗ dự kiến   (xem mục 3)
qty_plan        = risk_money / stop_distance, làm tròn xuống lô 100
giới hạn        = qty_plan × giá ≤ capital × max_weight
```

Đây là cách tính "1R" của Van Tharp: mỗi lệnh có rủi ro ban đầu cố định bằng tiền, mọi kết quả sau đó đo bằng bội số R. App ghi R-multiple cho từng lệnh để sau 30 lệnh tính được **kỳ vọng** (expectancy) thực của bạn.

Ví dụ: capital 200 triệu, risk 1,5% = 3 triệu. Mã giá 40.000, cắt lỗ 37.000 (cách 3.000). qty_plan = 3.000.000 / 3.000 = 1.000 cổ phiếu = 40 triệu = 20% capital, vừa chạm trần tỷ trọng. Đây là **tổng** khối lượng cho mã đó, sẽ chia 4 lần vào.

---

## 2. Luật vào lệnh

### 2.1 Chế độ lướt sóng: chia 4 lần, chỉ mua thêm khi đang lãi (pyramiding)

| Lần | Tỷ lệ của `qty_plan` | Điều kiện | Lý do |
|---|---|---|---|
| 1 | **25%** | Có tín hiệu vào (2.3) và bộ lọc thị trường (2.4) ở mức "mua được" | Thăm dò. Nếu sai chỉ mất 1/4 rủi ro |
| 2 | **25%** | Giá đóng cửa cao hơn giá lần 1 ít nhất **max(+3%, 1×ATR14)** **[v2]**, và cổ phiếu lần 1 đã về tài khoản | Thị trường xác nhận bạn đúng. Khoảng cách theo ATR lấy từ Turtle (thêm đơn vị mỗi 0,5–1N) |
| 3 | **25%** | Giá đóng cửa cao hơn giá lần 2 ít nhất max(+3%, 1×ATR14) | Chỉ thêm vốn vào thứ đang hoạt động |
| 4 | **25%** | Như trên, hoặc **bỏ qua** nếu giá đã cách giá vào trung bình quá 10% | Mua đuổi quá cao làm giá vốn xấu |

Luật cứng:
- **Không mua lần 2 nếu lần 1 đang lỗ.** Đây là khác biệt giữa pyramiding (thêm vào mã đang thắng, Livermore và Turtle đều làm vậy) và trung bình giá xuống (thêm vào mã đang thua, Livermore cảnh báo từ 100 năm trước).
- Mỗi lần mua cách nhau tối thiểu 1 phiên.
- Giá cắt lỗ của cả vị thế tính lại theo giá vốn trung bình mới sau mỗi lần mua, nhưng **không bao giờ thấp hơn** mức cắt lỗ cũ.
- Tuỳ chọn nâng cao (tắt mặc định): chia theo tỷ lệ giảm dần 40/30/20/10 như Livermore, để phần vốn lớn nhất vào ở giá tốt nhất.

### 2.2 Chế độ DCA: mua theo lịch, 25% mỗi kỳ

| Tham số | Mặc định |
|---|---|
| Số tiền dự kiến cho mã (`dca_budget`) | Tối đa 20% capital |
| Số kỳ | **4 kỳ × 25%** |
| Khoảng cách giữa các kỳ | **1 tháng**, cùng một ngày trong tháng |
| Điều kiện bỏ kỳ | **Tắt mặc định** **[v2]**. Có thể bật: bỏ kỳ nếu giá cao hơn giá vốn trung bình +15% |
| Điều kiện tăng kỳ | **Không có.** Giá giảm không phải lý do mua gấp đôi |

Lưu ý trung thực về DCA: nghiên cứu của Vanguard (1976–2022) cho thấy đầu tư một lần thắng DCA khoảng **68%** số trường hợp, vì thị trường tăng nhiều hơn giảm. DCA thua về lợi nhuận kỳ vọng nhưng **giảm hối tiếc và giảm rủi ro vào sai thời điểm**, và Vanguard kết luận nó phù hợp với nhà đầu tư sợ thua lỗ. Với tình trạng hiện tại của bạn, DCA là lựa chọn hành vi đúng, không phải lựa chọn tối ưu lợi nhuận. Vì vậy luật "bỏ kỳ khi giá cao" bị tắt mặc định: lịch là lịch, không nhìn giá.

DCA chỉ dành cho mã bạn đã viết ra được **luận điểm cơ bản** (ngành, lợi nhuận, cổ tức) bằng 3 câu. Không có luận điểm thì không được xếp vào DCA, mà phải vào chế độ swing với luật cắt lỗ.

### 2.3 Tín hiệu vào lệnh swing (cần đủ cả 3)

1. Giá đóng cửa **trên SMA20 và SMA20 đang hướng lên** (SMA20 hôm nay > SMA20 cách 5 phiên).
2. **RSI14 trong khoảng 45–65.** Dưới 45 là chưa có lực, trên 65 là đã chạy quá, mua dễ đu đỉnh.
3. Khối lượng phiên tín hiệu **≥ 1,2 lần** trung bình 20 phiên.

Cấm mua trong các trường hợp sau dù đủ 3 điều kiện:
- Phiên hôm đó tăng trần hoặc tăng trên 5%. Chờ phiên điều chỉnh. (O'Neil: không mua đuổi quá 5% trên điểm mua chuẩn.)
- Giá cách SMA20 trên 8%. Quá căng, chờ về gần SMA20.

### 2.4 Bộ lọc thị trường chung, ba mức **[v2]**

| Trạng thái VN-Index (đóng cửa) | Mở vị thế swing mới | Chốt lời |
|---|---|---|
| Trên SMA50 **và** trên SMA200 | Được, đủ quy mô | Theo bậc chuẩn (mục 4) |
| Trên SMA200 nhưng dưới SMA50 | **Không**, chỉ quản lý vị thế đang có | Theo bậc chuẩn |
| Dưới SMA200 | **Không** | **Chế độ thị trường yếu**: chốt toàn bộ ở +10 đến +15%, cắt lỗ siết về 5% |

Lý do có hai đường: SMA200 (tương đương đường 30 tuần của Weinstein và quy tắc 10 tháng của Faber) phân biệt môi trường tốt/xấu rất tốt nhưng chậm; SMA50 phản ứng nhanh hơn để tránh mua mới ngay đầu nhịp giảm. Các nghiên cứu về SMA200 cho thấy lọc kiểu này **giảm mạnh mức sụt giảm tối đa** dù lợi nhuận thô không cao hơn mua-và-giữ, và với người đang kẹt hàng thì giảm sụt giảm quan trọng hơn lợi nhuận. Chế độ thị trường yếu lấy từ hướng dẫn của O'Neil/IBD: thị trường khó thì chốt 10–15% và cắt lỗ 3–5%.

---

## 3. Luật cắt lỗ (quan trọng nhất)

### 3.1 Mức cắt lỗ ban đầu

```
stop_pct   = giá vốn × (1 − 7%)
stop_atr   = giá vốn − 2 × ATR14
stop_init  = max(stop_pct, stop_atr)      → lấy mức GẦN giá hơn
```

Mặc định `stop_loss_pct = 7%`, `atr_multiplier = 2`. Con số 7% khớp với quy tắc 7–8% của O'Neil (được AAII xếp vào nhóm chiến lược thành công nhất trong 40 chiến lược theo dõi) và với trần 10% của Minervini. 2×ATR là mức dừng của Turtle. Lấy mức gần hơn để không bao giờ lỗ quá 7% cộng trượt giá. Nếu 7% không đủ chỗ cho biến động bình thường của mã đó thì **mã đó không hợp để lướt sóng**, không phải lý do nới cắt lỗ.

**Tự hiệu chỉnh theo Minervini [v2]:** sau khi nhật ký có ≥ 20 lệnh đã đóng, app tính lãi trung bình của các lệnh thắng và đề xuất `stop_loss_pct = min(7%, lãi thắng trung bình / 2)`. Minervini: mức cắt lỗ tối ưu bằng một nửa lãi trung bình, và không bao giờ quá 10%. Nếu lãi thắng trung bình của bạn chỉ 10% thì cắt lỗ phải là 5%, không phải 7%.

### 3.2 Khi nào thực hiện

- Tín hiệu kích hoạt khi **giá đóng cửa** dưới `stop`. Không dùng giá trong phiên để tránh bị quét.
- Hành động: **bán toàn bộ bằng lệnh ATO hoặc MP trong 15 phút đầu phiên kế tiếp.** Không chờ hồi, không bán một nửa, không đặt lệnh LO cao hơn giá thị trường.
- Nếu mã giảm sàn trắng bên mua: đặt lệnh bán sàn ngay ATO mỗi ngày đến khi khớp.

### 3.3 Luật bất biến

- **Cắt lỗ chỉ được dời lên, không bao giờ dời xuống.**
- Không có khái niệm "cắt lỗ tạm hoãn vì có tin tốt".
- App ghi lại mọi lần giá đóng cửa dưới cắt lỗ mà hôm sau danh mục vẫn còn mã đó. Đó là **vi phạm**, hiện lên nhật ký kỷ luật.

Bằng chứng học thuật: Kaminski và Lo (2014) chứng minh quy tắc cắt lỗ **làm giảm** lợi nhuận kỳ vọng nếu giá đi ngẫu nhiên, nhưng **làm tăng** lợi nhuận và giảm biến động khi thị trường có quán tính (momentum). Thị trường Việt Nam do nhà đầu tư cá nhân chi phối, quán tính mạnh, nên cắt lỗ có cơ sở ở đây. Han, Zhou và Zhu (2014) cho thấy một mức dừng 10% chồng lên danh mục momentum giúp tránh các cú sập.

### 3.4 Cắt lỗ theo thời gian

Vị thế swing sau **10 phiên** kể từ lần mua 1 mà lãi chưa đạt **+3%**: bán toàn bộ. Vốn nằm chết ở mã không chạy là chi phí cơ hội, và vị thế đi ngang lâu thường kết thúc bằng giảm. *(Luật của dự án, không có nguồn chuẩn; đánh giá lại sau 30 lệnh.)*

### 3.5 Lô mua thêm khi đang lỗ **[v3]**

Mua thêm khi mã đang lỗ bị cấm khi còn margin (mục 2.1, mục 6). Nếu vẫn xảy ra, mỗi lần mua đó là **một lô riêng** với luật riêng, vì giá vốn bình quân làm khoản lỗ trông nhỏ đi và che mất việc lô mới đang sai:

| Luật | Mặc định |
|---|---|
| Mức cắt lỗ của lô | Cao hơn trong hai mức: đáy phiên mua − 1%, giá mua − 5%. Thủng đáy của chính phiên bắt đáy nghĩa là bắt đáy sai |
| Hạn thời gian | Sau 3 phiên kể từ khi cổ phiếu về tài khoản (T+2) mà lô chưa lãi 3% thì bán lô |
| Hành động | Bán đúng số cổ phiếu của lô bằng ATO phiên kế tiếp. Chưa về tài khoản thì bán ngay chiều T+2 |
| Bán ra | Trừ vào lô mua gần nhất trước, vì lô mua thêm là lô luật yêu cầu bán trước |

Ứng dụng tự phát hiện lô mua thêm khi khối lượng tăng (giá mua suy ra từ chênh lệch giá vốn), nhận lô nhập tay từ lịch sử lệnh, và lấy lô từ lệnh mua trong Sổ danh mục. Cảnh báo bán lô **không có nút "đã xem"**: chỉ đóng khi số cổ phiếu giảm đúng bằng lô, hoặc khi bạn ghi lý do không bán. Ứng dụng đếm số phiên chần chừ và tiền mất thêm kể từ phiên luật yêu cầu bán. *(Luật của dự án, dựa trên nguyên tắc không trung bình giá xuống của Livermore và Turtle; xem lại sau 30 lệnh.)*


---

## 4. Luật chốt lời theo bậc (câu hỏi "tăng 15% thì bán bao nhiêu")

Chốt lời từng phần để vừa khoá lợi nhuận vừa giữ phần còn lại cho sóng lớn. Mốc tính trên **giá vốn trung bình**.

| Mốc lãi (đóng cửa) | Hành động với khối lượng còn lại | Dời cắt lỗ lên | Kết quả tích luỹ |
|---|---|---|---|
| **+7%** | Chưa bán | **Về giá vốn** (hoà vốn) | Từ đây không thể lỗ |
| **+10%** | Bán **25%** khối lượng ban đầu | Giá vốn × 1,03 | Đã khoá 2,5% lợi nhuận |
| **+15%** | Bán thêm **25%** (tổng 50%) | Giá vốn × 1,07 | Đã khoá thêm 3,75% |
| **+25%** | Bán thêm **25%** (tổng 75%) | Giá vốn × 1,15 | Đã khoá thêm 6,25% |
| 25% cuối | Không bán theo mốc | **Chandelier trailing** **[v2]**: max(đỉnh đóng cửa − 3×ATR22 ; SMA20) | Cưỡi sóng đến khi gãy xu hướng |

Bậc này khớp với O'Neil: "chốt phần lớn lợi nhuận ở 20–25%", vì đến mốc 25% ta đã bán 75%. Trong thị trường thuận, O'Neil cũng khuyên bán một phần (1/3 hoặc 1/2) chứ không bán hết.

**Ngoại lệ 8 tuần của O'Neil [v2]:** nếu mã đạt **+20% trong vòng 3 tuần** kể từ lần mua 1, đó là dấu hiệu siêu cổ phiếu. Khi đó **tạm dừng các bậc bán 15% và 25%**, giữ ít nhất 8 tuần kể từ ngày mua, chỉ bán nếu đóng cửa dưới trailing stop. Hết 8 tuần thì áp lại bậc chuẩn.

**Phần trailing (Chandelier Exit của Chuck LeBeau):** mỗi phiên tính `trail = max(highest_close_since_entry − 3 × ATR22, SMA20)`, và `stop = max(stop_cũ, trail)` (ratchet, chỉ lên không xuống). Hệ số 3×ATR là mặc định chuẩn, dải thường dùng 2,5–3,5. Phiên bản 1 dùng "8% dưới đỉnh" cố định; đổi sang ATR vì cổ phiếu biến động khác nhau, 8% là quá chặt với mã dao động mạnh và quá lỏng với mã ổn định.

Vì sao bậc đầu đặt ở +10% mà không phải +15%: cắt lỗ là 7%, nếu chờ +15% mới bán lần đầu thì tỷ lệ thắng phải cao hơn 50% mới có lãi kỳ vọng. Chốt một phần ở +10% kéo điểm hoà vốn của hệ thống xuống, phù hợp với người đang xây lại kỷ luật.

**Trung thực về chốt lời từng phần:** các mô phỏng (Bandy, Passamonte) cho thấy bán từng phần **làm giảm lợi nhuận trung bình trên mỗi lệnh thắng** so với giữ nguyên và thoát một lần theo trailing stop, vì phần bán sớm không được hưởng sóng lớn. Đổi lại nó làm đường vốn mượt hơn và dễ tuân thủ hơn. Với người đang có vấn đề về kỷ luật, mượt và dễ tuân thủ quan trọng hơn vài % kỳ vọng. Sau 30 lệnh, app sẽ tính thử cả hai cách trên dữ liệu thật của bạn (mục 7.5) để bạn quyết định có bỏ bớt bậc không.

**Kỳ vọng toán học** với luật này: thua tối đa 7% trên 100% vốn mã đó. Thắng trung bình (nếu đi hết các bậc) khoảng 2,5 + 3,75 + 6,25 + phần trailing, tức trên 12,5% trên vốn mã. Tỷ lệ lời/lỗ gần 2:1, nên chỉ cần thắng **trên 35% số lệnh** là hệ thống có lãi.

---

## 4b. Khuyến nghị chốt lời mỗi ngày **[v3]**

Mục 4 cho các mốc. Mục này biến chúng thành **một khuyến nghị duy nhất cho hôm nay**, kèm giá và số cổ phiếu cụ thể, và bổ sung hai nhánh mà chuyên gia dùng ngoài các mốc phần trăm: bán vào sức mạnh và bán khi yếu đi.

### Thứ tự ưu tiên (dừng ở điều kiện đầu tiên đúng)

| # | Điều kiện | Hành động | Nguồn |
|---|---|---|---|
| 0 | Giá đã thủng mức cắt lỗ hoặc trailing stop | Theo luật cắt lỗ (mục 3), không xét chốt lời | Mục 3 |
| 1 | Chưa có lãi | Không bán; hiện mục tiêu đầu tiên | |
| 2 | Thị trường yếu (VN-Index dưới SMA200) và lãi từ 10% | Bán toàn bộ | O'Neil/IBD |
| 3 | Đang lãi từ 5% nhưng **đóng cửa dưới SMA50** | Bán phần còn lại | IBD (đường 10 tuần), Minervini (SMA50 làm trailing) |
| 4 | **Từ 2 dấu hiệu tăng cao trào** trở lên (bảng dưới) | Bán **một nửa** phần đang giữ vào sức mạnh | O'Neil/IBD climax top; Minervini "khi nghi ngờ thì bán một nửa" |
| 5 | Đang lãi từ 5% và **thủng EMA21 với khối lượng từ 1,5× TB20** | Bán một nửa | IBD (ví dụ ALGM 2021) |
| 6 | Chạm bậc chốt lời chưa bán (+10%, +15%, +25%) | Bán 25% khối lượng ban đầu, dời cắt lỗ | Mục 4 |
| 7 | Có đúng 1 dấu hiệu cao trào | Theo dõi, chuẩn bị bán | |
| 8 | Không có gì | Giữ, hiện mục tiêu tiếp theo | |

Trong 8 tuần giữ của luật O'Neil, tín hiệu EMA21 bị bỏ qua (cho phép rung lắc bình thường), nhưng SMA50 và cao trào vẫn áp dụng.

### Dấu hiệu tăng cao trào (bán vào sức mạnh)

| Dấu hiệu | Ngưỡng mặc định | Ghi chú |
|---|---|---|
| Tăng nhanh | +25% từ đáy 15 phiên (khoảng 3 tuần) | IBD: tăng 25–50% trong 1–3 tuần sau một đợt tăng dài |
| Chuỗi phiên tăng | Ít nhất 7 trong 8 phiên gần nhất là phiên tăng | IBD: "chuỗi ngày tăng" |
| Phiên cao trào | Phiên tăng mạnh nhất 60 phiên rơi vào 5 phiên gần nhất, khối lượng từ 2× TB20 | IBD: biên độ và khối lượng lớn nhất của cả đợt |
| Khoảng trống kiệt sức | Giá thấp nhất phiên cao hơn giá cao nhất phiên trước, sau khi đã tăng 20% | IBD: exhaustion gap |
| Kéo căng | Giá cách SMA50 từ 25% | Của dự án, thay cho mức 70–100% trên SMA200 mà chính O'Neil hiếm khi dùng |
| RSI14 từ 80 | Chỉ tính khi đã có ít nhất một dấu hiệu khác | Tín hiệu phụ: chưa có kiểm định nghiêm túc, RSI có thể ở vùng cao rất lâu trong xu hướng mạnh |

### Mục tiêu tham chiếu theo R

1R = giá vốn − mức cắt lỗ ban đầu (mục 3.1). Ứng dụng hiện giá ở 2R và 3R và lãi hiện tại tính bằng R (Van Tharp). Đây chỉ là tham chiếu, không tự sinh lệnh bán: các bậc phần trăm vẫn là luật chính để giữ đơn giản.

### Khối lượng bán

- Bậc chốt lời: 25% **khối lượng ban đầu**. Khối lượng ban đầu được suy ra từ khối lượng đang giữ và số bậc bạn khai báo đã bán.
- Bán một nửa: 50% khối lượng **đang giữ**.
- Làm tròn xuống lô 100, tối thiểu 100 cổ phiếu. Dưới 100 cổ phiếu (lô lẻ) thì bán hết.

### Cảnh báo trung thực

Nghiên cứu về hiệu ứng disposition (Shefrin & Statman 1985, Odean 1998) cho thấy nhà đầu tư cá nhân có xu hướng **bán mã lãi quá sớm**. Vì vậy các nhánh trên ưu tiên bán **một phần** và để phần còn lại chạy theo trailing stop, thay vì bán hết ngay khi có lãi. Các ngưỡng cao trào lấy từ thị trường Mỹ, chưa kiểm định trên dữ liệu Việt Nam; xem lại sau 30 lệnh.

---

## 5. Luật margin

| Luật | Giá trị |
|---|---|
| Mở vị thế mới bằng margin | **Cấm** cho đến khi nhật ký cho thấy 6 tháng liên tục tuân thủ ≥ 90% |
| RTT tối thiểu để được giữ nguyên danh mục | maintenance + **10 điểm %** |
| RTT dưới ngưỡng trên | Bán mã lỗ nặng nhất cho đến khi RTT về ngưỡng, **ngay phiên hôm sau** |
| Lãi margin / ngày vượt 0,1% NAV | Cảnh báo đỏ, phải giảm nợ trong tuần |

### 5b. Kế hoạch hạ margin mỗi ngày **[v4]**

Mỗi tài khoản có nợ được lập một lộ trình bán, tính lại mỗi ngày theo giá mới. Mỗi bước ghi rõ mã, số cổ phiếu, tiền thu về, RTT sau khi bán và tiền lãi tiết kiệm mỗi ngày.

**Giai đoạn 1: về vùng an toàn** (RTT ≥ duy trì + 10 điểm %). Làm ngay phiên kế tiếp, theo thứ tự:
1. Các lô mua thêm đã tới luật bán (mục 3.5).
2. Mã đã thủng mức cắt lỗ.
3. Hàng kẹt nhóm B: bán 50% (mục 6.2).
4. Phần bán đảo hàng đang tới vùng bán (mục 6b).
5. Nếu vẫn chưa đủ: bán tiếp mã lỗ nặng nhất (mục 5), vừa đủ số cổ phiếu để RTT lên mục tiêu.

Bốn bước đầu là việc luật đã yêu cầu, nên được liệt kê kể cả khi tài khoản đã an toàn. Thay cho bước 5, có thể nộp thêm tiền mặt; app ghi số tiền tương đương.

**Giai đoạn 2: hết nợ** (mục 6.4). Bán tiếp mã lỗ nặng nhất cho tới khi dư nợ bằng 0. Không bắt buộc làm ngay, nhưng mỗi bước cho biết tiền lãi tiết kiệm được mỗi ngày để bạn so với kỳ vọng hồi giá.

**Quy ước tính:**
- Tiền bán trừ phí và thuế bán khoảng 0,25%, phần còn lại trả nợ ngay. Trả khoản có lãi suất cao nhất trước, cùng lãi suất thì khoản đáo hạn sớm trước.
- RTT sau khi bán tính đúng cách đo của từng công ty (mục Cách TCBS đo RTT bên dưới; SSI, VPS dùng vốn chủ / giá trị).
- Khoản vay đáo hạn trong 30 ngày tới được cộng thành số tiền phải có trước ngày đó.
- Mỗi công ty tính ký quỹ riêng: tiền bán ở công ty này không cứu được tài khoản ở công ty khác, trừ khi bạn tự chuyển tiền.

### Cách TCBS đo RTT (theo trang hỗ trợ chính thức của TCBS)

- **RTT = tài sản đảm bảo / dư nợ.**
- **Tài sản đảm bảo** = tổng của số lượng thực có × tỷ lệ tính tài sản × giá tính tài sản, theo từng mã. Giá tính tài sản là giá thấp hơn giữa giá tham chiếu và giá trần cho vay. Tỷ lệ và giá trần do TCBS công bố theo danh mục cho vay.
- **Dư nợ** = nợ đã giải ngân + nợ phí + dư nợ chờ giải ngân − tiền mặt − tiền chờ về. Vì vậy tiền nộp vào làm giảm dư nợ ngay.
- **Ngưỡng:** ban đầu 100%, duy trì 85%, xử lý tài sản 80%.
- **Mốc bán xử lý:** RTT dưới 85% nhưng trên 80% trong 3 ngày làm việc liên tiếp thì bị bán vào ngày làm việc thứ 3 kể từ thông báo gọi ký quỹ đầu tiên. RTT dưới 80% thì bị bán vào ngày làm việc kế tiếp.
- **Cách app dùng:** RTT và ngưỡng lấy thẳng từ API của TCBS. Tỷ lệ tính tài sản từng mã không có trong API, nên khi giả định giá giảm hoặc bán bớt, app suy ra hệ số tài sản đảm bảo / giá trị thị trường từ RTT hiện tại và giữ hệ số đó. Tiền cần nộp tính trên dư nợ gồm cả lãi dồn, nên hơi cao hơn thực tế, nghiêng về an toàn.

---

## 6. Giao thức thoát hàng kẹt (áp dụng cho danh mục hiện tại)

Hàng kẹt là mã mua không theo luật nào, đang lỗ sâu. Không áp luật cắt lỗ 7% được nữa vì đã lỗ quá rồi, nên dùng giao thức riêng, chạy một lần:

1. **Phân loại từng mã**: có luận điểm cơ bản viết ra được không? Có thì vào nhóm A (giữ có điều kiện), không thì nhóm B (thoát).
2. **Nhóm B**: bán **50% ngay** phiên tới bằng MP, 50% còn lại bán khi giá chạm SMA20 hoặc sau 10 phiên, tuỳ cái nào đến trước. Không chờ về bờ. (Odean: mã lỗ bạn đang giữ, trung bình, sẽ tiếp tục kém hơn mã bạn đã bán.)
3. **Nhóm A**: đặt cắt lỗ mới = min(giá hiện tại × 0,90 ; đáy 20 phiên × 0,97). Thủng là bán hết. Không mua thêm để trung bình giá chừng nào còn margin.
4. **Ưu tiên giảm margin trước mọi thứ**: bán cho đến khi dư nợ bằng 0 hoặc RTT ≥ maintenance + 10 điểm %. Tiền lãi margin mỗi ngày đang là khoản lỗ chắc chắn, còn kỳ vọng hồi là không chắc chắn.
5. Tiền thu về **không được mua lại trong 10 phiên**. Để nguội. Ngoại lệ duy nhất là phần bán theo mục 6b, có luật mua lại riêng và chặt hơn.

## 6b. Đảo hàng khi hồi: bán một phần lúc hồi, mua lại lúc chỉnh **[v4]**

Đây là cách giảm giá vốn cho mã đang lỗ mà **không tăng tổng số cổ phiếu nắm giữ**. Phương pháp có tên trong tài liệu nước ngoài là *trading around a core position*: giữ phần lõi, bán bớt một phần khi giá hồi lên vùng kháng cự, mua lại đúng số đó khi giá chỉnh xuống. Ở Việt Nam gọi là đảo hàng hay lướt T+ hạ giá vốn. Nó khác bình quân giá xuống ở chỗ: bán trước, mua sau, và không bao giờ mua nhiều hơn số đã bán.

### Vì sao nhịp hồi 10–20% là vùng bán
- Trong xu hướng giảm, nhịp hồi thường chỉ lấy lại khoảng một nửa đoạn vừa giảm rồi giảm tiếp. Các mức 38,2% và 50% của đoạn giảm (Fibonacci) là kháng cự thường gặp. Hồi quá 61,8% và đóng cửa trên SMA50 thì có thể không còn là nhịp hồi trong xu hướng giảm.
- Theo luật vùng RSI của Constance Brown và Andrew Cardwell, trong xu hướng giảm RSI14 thường dừng ở vùng 55–60.
- Nhịp hồi kỹ thuật (dead cat bounce) thường dài 5–25% trong 1–10 phiên.

### Ai được áp dụng
- Mã đang lỗ so với giá vốn, chế độ lướt sóng. Không áp cho chế độ DCA.
- Hàng kẹt **nhóm B** (không có luận điểm): chỉ dùng phần bán. Bán vào nhịp hồi là cách thoát giá tốt hơn, **không mua lại**.
- Hàng kẹt **nhóm A** và mã chưa phân loại: dùng cả bán và mua lại.

### Bán (vùng bán)
Đo từ đáy 20 phiên gần nhất, so với đỉnh 60 phiên trước đó:

| Đợt | Điều kiện (một trong hai) | Bán thêm | Cộng dồn |
|---|---|---|---|
| 1 | hồi từ đáy ≥ 10%, hoặc lấy lại ≥ 38,2% đoạn giảm | 30% lượng gốc | 30% |
| 2 | hồi ≥ 20%, hoặc lấy lại ≥ 50% đoạn giảm, hoặc đã đạt đợt 1 và RSI14 ≥ 60 | 20% lượng gốc | 50% |

- Phải hồi tối thiểu 5% từ đáy mới xét, để đoạn giảm nhỏ không sinh tín hiệu giả.
- Không bao giờ đảo quá **50%** lượng đang giữ (chuyên gia VPS khuyên 30–50%). Phần lõi giữ lại để không lỡ nếu mã đảo chiều thật.
- Lấy lại quá 61,8% đoạn giảm **và** đóng cửa trên SMA50: coi là có thể đã đổi xu hướng, không bán đảo hàng thêm, quay về luật thường.
- **Đang dùng margin**: tiền bán được trả nợ trước (mục 6.4). Khi đó phần mua lại bị khoá cho tới khi tỷ lệ ký quỹ về vùng an toàn.

### Mua lại (vùng mua lại), cần đủ cả sáu điều kiện
1. Giá thấp hơn giá bán bình quân của chu kỳ ít nhất **7%**. Phí hai chiều cộng thuế bán khoảng 0,4%, nên chênh lệch nhỏ hơn không đáng.
2. Giá **vẫn trên đáy cũ** (đáy cao hơn). Thủng đáy cũ nghĩa là xu hướng giảm tiếp: **không mua lại**, phần lõi đi theo cắt lỗ nhóm A.
3. Có phiên đảo chiều: giá đóng cửa trên giá cao nhất của phiên trước.
4. Đã qua ít nhất **3 phiên** kể từ lần bán, vì tiền bán về tài khoản sau T+2.
5. Thị trường chung không ở trạng thái yếu (VN-Index không dưới SMA200).
6. Tài khoản không vay margin, hoặc tỷ lệ ký quỹ đã cách ngưỡng duy trì từ 10 điểm % trở lên.

- Mua lại tối đa đúng số đã bán, chỉ bằng tiền của lần bán đó, không dùng margin.
- Lô mua lại là **lô mua thêm khi đang lỗ** và chịu luật mục 3.5: cắt lỗ riêng, hạn T+2 cộng 3 phiên.
- Giá vượt giá bán từ 5% trở lên và đóng cửa trên SMA50: **không mua đuổi**. Phần đã bán coi như chốt, giữ phần lõi.
- Quá **20 phiên** không có điểm mua lại: chu kỳ kết thúc, coi như đã bán hẳn.

### Cảnh báo trung thực
- Giá vốn chỉ giảm khi giá mua lại thấp hơn giá bán. Nếu mã tăng một mạch, bạn còn ít cổ phiếu hơn và lỡ phần tăng đó.
- Chuyên gia Yuanta lưu ý: đảo hàng nhiều làm tăng phí, thuế và chi phí vay; xu hướng đảo chiều khó đoán. Chưa có nghiên cứu học thuật nào kiểm chứng cách làm này trên thị trường Việt Nam.
- Đảo hàng **không thay thế cắt lỗ**. Mục đích chính của phần bán là lấy giá thoát tốt hơn và giảm nợ, không phải để có cớ mua thêm.

## 6c. Gồng có kế hoạch **[v4]**

Đây là lựa chọn của người dùng, **trái với** mục 5 và mục 6.4 của bộ luật (ưu tiên giảm margin). Bộ luật không khuyến nghị cách này. Mục này tồn tại để khi đã chọn gồng thì gồng có điều kiện, không gồng vô hạn.

Mỗi mã chọn gồng phải ghi một quyết định gồm:

| Mục | Mặc định | Ý nghĩa |
|---|---|---|
| Giá thoát cứng (đóng cửa dưới) | mức vô hiệu của mục 6d; chưa có thì đáy 20 phiên × 0,97 | Giả định "đây là đáy" sai khi giá đóng cửa thủng đáy. Lúc đó bán theo kế hoạch hạ margin, không gia hạn. |
| Sàn tỷ lệ ký quỹ | ngưỡng duy trì của tài khoản | Chạm sàn này thì phải nộp tiền hoặc bán ngay, vì sau đó là bị gọi ký quỹ và có thể bị bán cưỡng bức. |
| Ngày xem lại | 30 ngày sau | Tới ngày này mà chưa hồi thì xem lại quyết định, ghi lý do nếu tiếp tục. |
| Lý do | bắt buộc | Viết bằng lời vì sao tin mã này sẽ hồi. |

**Khi đang gồng:**
- App vẫn tính kế hoạch hạ margin. Các lệnh bán mã lỗ nặng nhất của mã đang gồng được ghi là **hoãn theo quyết định gồng**, không bị xoá. Lệnh của các luật khác (lô mua thêm, thủng cắt lỗ) vẫn hiện như cũ.
- Mỗi ngày app ghi số ngày đã gồng và tiền lãi margin ước tính đã trả cho phần của mã đó, theo tỷ trọng mã trong tài khoản.
- Khi nhịp hồi tới vùng bán đảo hàng (mục 6b), app báo **thời điểm cơ cấu**: bán phần đảo hàng, dùng tiền trả nợ trước, rồi mới tính chuyện mua lại để hạ giá vốn.

**Ba tín hiệu kết thúc gồng** (cảnh báo khẩn, không tắt được, chỉ đóng khi bán hoặc sửa quyết định):
1. Giá đóng cửa dưới giá thoát cứng.
2. Tỷ lệ ký quỹ của tài khoản chạm sàn.
3. Tới ngày xem lại.

## 6d. Kế hoạch theo kỹ thuật: vùng giá, giai đoạn, xác nhận đáy **[v5]**

Thay các mốc phần trăm cố định bằng các mức giá mà nhiều công cụ kỹ thuật cùng chỉ ra. Mỗi mã có một kế hoạch tính lại mỗi ngày: đang ở giai đoạn nào, giá sẽ gặp cản ở đâu, đáy đã được xác nhận chưa, và làm gì trong từng kịch bản.

### Giai đoạn xu hướng (Stan Weinstein, *Secrets for Profiting in Bull and Bear Markets*, 1988)
Dùng đường trung bình 30 tuần, quy ra 150 phiên ngày, và độ dốc của nó trong 20 phiên:
| Giai đoạn | Điều kiện | Ý nghĩa với kế hoạch |
|---|---|---|
| 4: đang giảm | giá dưới đường 150 phiên, đường dốc xuống | Nhịp hồi là để bán bớt, không mua thêm |
| 1: tạo nền | đường đi ngang (dốc trong ±0,5%) sau một đoạn giảm | Bán ít hơn ở các vùng cản, chờ xác nhận |
| 2: đang tăng | giá trên đường 150 phiên, đường dốc lên | Ngừng bán đảo hàng, chuyển sang luật chốt lời và trailing |
| 3: tạo đỉnh | đường đi ngang sau một đoạn tăng | Siết cắt lỗ |

### Vùng cản và vùng đỡ (hội tụ nhiều công cụ)
Mỗi công cụ cho ra một mức giá; các mức nằm gần nhau (trong 0,5×ATR14) được gộp thành một vùng. Vùng có càng nhiều công cụ thì càng mạnh.
- **Đường trung bình SMA20, SMA50, SMA200.** Theo Granville, giá nằm dưới đường trung bình đang dốc xuống thì nhịp hồi thường gặp cản ở đường đó.
- **Fibonacci 38,2%, 50%, 61,8%** của đoạn giảm gần nhất (đỉnh 120 phiên tới đáy 60 phiên).
- **Đỉnh và đáy cũ** (đỉnh, đáy cục bộ: cao hoặc thấp hơn 3 phiên mỗi bên trong 120 phiên). Theo Murphy, *Technical Analysis of the Financial Markets*, đáy cũ bị thủng trở thành cản.
- **Vùng giá giao dịch nhiều nhất** (điểm kiểm soát của hồ sơ khối lượng, Market Profile của Steidlmayer) trong 120 phiên.
- **Dải Bollinger** trên và dưới (20 phiên, 2 độ lệch chuẩn).

Chỉ dùng vùng cản trong phạm vi 40% trên giá hiện tại, tối đa ba vùng gần nhất có từ 2 công cụ trở lên.

### Bán ở vùng cản (thay các mốc 10% và 20% của mục 6b)
- Mỗi vùng cản bán **10%** lượng đang giữ, tối đa ba vùng, tổng **30%**.
- Nếu tài khoản đang sát ngưỡng ký quỹ, vùng cản đầu tiên bán **vừa đủ để tài khoản về vùng an toàn**, nhưng không ít hơn 10%. Khi đó tổng tối đa là 50%. Tính giả định cả danh mục hồi cùng tỷ lệ với mã đó.
- Giai đoạn 2 thì không bán đảo hàng nữa (giữ quy tắc đổi xu hướng của mục 6b).
- Chu kỳ mua lại, điều kiện mua lại và nhật ký vẫn theo mục 6b.

### Xác nhận đáy (sáu dấu hiệu, chỉ để biết giả định "đây là đáy" đúng tới đâu)
1. Đáy sau cao hơn đáy trước (Dow).
2. Giá đóng cửa trên SMA20 và SMA20 đã quay lên.
3. RSI14 trên 50: chuyển sang vùng của xu hướng tăng (Cardwell, Brown).
4. Phân kỳ dương: giá làm đáy thấp hơn nhưng RSI làm đáy cao hơn, hoặc histogram MACD đã dương.
5. Tích luỹ: trong 20 phiên, khối lượng phiên tăng lớn hơn khối lượng phiên giảm.
6. Thị trường chung có ngày bùng nổ xác nhận (follow-through day của O'Neil): từ phiên thứ 4 của nhịp hồi, VN-Index tăng từ 1,25% với khối lượng cao hơn phiên trước, và chưa thủng đáy của nhịp hồi.

0–2 dấu hiệu: **chưa có bằng chứng đáy**. 3–4: **đáy đang hình thành**. 5–6: **đáy được xác nhận**. Kiểm định độc lập cho thấy ngày bùng nổ chỉ đúng khoảng một nửa đến hai phần ba số lần, nên đây là bằng chứng, không phải lời hứa.

### Ba kịch bản cho mỗi mã
- **Nếu hồi:** các vùng cản, số cổ phiếu bán ở mỗi vùng, tỷ lệ ký quỹ sau khi bán.
- **Nếu đi ngang:** bao lâu thì xem lại (theo ngày xem lại của quyết định gồng, hoặc 20 phiên).
- **Nếu giảm:** mức vô hiệu = vùng đỡ mạnh nhất gần nhất trừ 0,5×ATR14. Đóng cửa dưới mức này thì giả định đáy sai, làm theo kế hoạch hạ margin.

---

## 7. Luật hành vi

- Mỗi lệnh mua phải có **kế hoạch viết trước** trong app: chế độ, giá vào, cắt lỗ, các mốc chốt lời, lý do (3 câu). Không có kế hoạch thì app đánh dấu lệnh đó là "mua cảm tính".
- Tối đa **1 lệnh mua mới mỗi ngày**, tối đa **2 mã mới mỗi tuần**. (Barber và Odean: nhà đầu tư cá nhân giao dịch càng nhiều, lợi nhuận càng kém.)
- Không xem bảng điện ngoài hai khung: 9:15–9:45 và 14:00–14:30. App gửi tóm tắt lúc 8:30 và 15:15 là đủ.
- Sau 2 lần cắt lỗ liên tiếp: **nghỉ 5 phiên** không mua mới.
- Ngân sách rủi ro tháng 6% (mục 1) chạm là nghỉ mua mới đến hết tháng. **[v2, thay cho luật "lỗ 5% nghỉ tháng sau"]**
- **7.5 Đối chiếu sau 30 lệnh [v2]:** app tính expectancy (R trung bình), tỷ lệ thắng, lãi thắng trung bình, và mô phỏng lại 30 lệnh đó theo hai cách thoát (bậc chuẩn và chỉ trailing) để bạn quyết định chỉnh tham số. Đây cũng là lúc duy nhất được đổi tham số.

---

## 8. Tham số cấu hình (để app dùng)

```yaml
capital_mode: cash_only          # không tính margin vào vốn
risk_per_trade_pct: 1.5          # dải chuẩn 1–2% (Minervini/Turtle 1%, Elder trần 2%)
max_weight_pct: 20
max_positions: 5
monthly_risk_budget_pct: 6       # Elder 6%: lỗ đã chốt trong tháng + rủi ro mở ≥ 6% → ngừng mua mới

entry:
  tranches: [25, 25, 25, 25]
  tranches_alt_livermore: [40, 30, 20, 10]   # tuỳ chọn, tắt mặc định
  add_only_if_up: {pct: 3, atr_mult: 1, rule: max}   # thêm khi tăng ≥ max(3%, 1×ATR14)
  skip_tranche_if_above_avg_pct: 10
  rsi_min: 45
  rsi_max: 65
  volume_ratio_min: 1.2
  max_distance_to_sma20_pct: 8
  no_buy_if_day_gain_pct_above: 5
  market_filter:
    index: VNINDEX
    fast_ma: 50
    slow_ma: 200
    # above both → normal; above slow only → no new buys; below slow → weak_market mode

dca:
  tranches: [25, 25, 25, 25]
  interval_days: 30
  skip_if_above_avg_pct: {enabled: false, pct: 15}

stop_loss:
  pct: 7
  atr_multiplier: 2
  atr_period: 14
  trigger: close
  minervini_autotune: {enabled: true, min_trades: 20, max_pct: 7}   # stop = min(7%, avg_win/2)
  time_stop_sessions: 10
  time_stop_min_gain_pct: 3
  weak_market_pct: 5

take_profit:
  ladder:
    - {gain_pct: 7,  sell_pct: 0,  move_stop_to_gain_pct: 0}
    - {gain_pct: 10, sell_pct: 25, move_stop_to_gain_pct: 3}
    - {gain_pct: 15, sell_pct: 25, move_stop_to_gain_pct: 7}
    - {gain_pct: 25, sell_pct: 25, move_stop_to_gain_pct: 15}
  weak_market_ladder:
    - {gain_pct: 10, sell_pct: 100}
  eight_week_rule: {enabled: true, gain_pct: 20, within_sessions: 15, hold_sessions: 40}
  trailing:
    method: chandelier
    atr_period: 22
    atr_multiplier: 3        # dải 2.5–3.5
    floor: sma20
    ratchet: true

rotation:
  # Đảo hàng khi hồi (mục 6b): bán một phần lúc hồi, mua lại lúc chỉnh. Không bao giờ mua nhiều hơn số đã bán.
  enabled: true
  low_lookback_sessions: 20       # đáy gần nhất
  high_lookback_sessions: 60      # đỉnh trước đoạn giảm
  min_rebound_pct: 5              # hồi dưới mức này: chưa xét
  sell_tiers:
    - {rebound_pct: 10, retrace_pct: 38.2, sell_pct: 30}
    - {rebound_pct: 20, retrace_pct: 50, sell_pct: 20}
  bear_rsi_ceiling: 60            # Brown/Cardwell: RSI trong xu hướng giảm thường dừng 55–60
  trend_change_retrace_pct: 61.8  # quá mức này và đóng cửa trên SMA50: thôi đảo hàng
  max_rotation_pct: 50            # chuyên gia VPS: 30–50% lượng đang giữ
  rebuy_drop_pct: 7               # mua lại khi giá thấp hơn giá bán ít nhất 7%
  rebuy_min_sessions: 3           # tiền bán về sau T+2
  rebuy_window_sessions: 20       # quá hạn: coi như đã bán hẳn
  no_chase_above_sell_pct: 5      # giá vượt giá bán 5% và trên SMA50: không mua đuổi

technical:
  # Kế hoạch theo kỹ thuật (mục 6d)
  stage_ma: 150                 # 30 tuần quy ra phiên ngày (Weinstein)
  stage_slope_sessions: 20
  stage_flat_pct: 0.5
  lookback: 120                 # đoạn để tìm đỉnh, đáy cục bộ, Fibonacci, hồ sơ khối lượng
  pivot_bars: 3
  merge_atr: 0.5                # gộp các mức cách nhau dưới 0,5×ATR14
  max_zone_distance_pct: 40
  min_strength: 2
  max_zones: 3
  sell_pct_per_zone: 10
  max_total_pct: 30
  margin_max_total_pct: 50
  invalidation_atr: 0.5
  ftd_min_gain_pct: 1.25        # O'Neil/IBD
  ftd_window: 25

margin:
  new_positions: forbidden
  rtt_buffer_pct_points: 10
  interest_alert_pct_nav_per_day: 0.1
  sell_cost_pct: 0.25            # phí bán + thuế 0,1%, dùng khi tính tiền bán trả nợ

behavior:
  max_new_buys_per_day: 1
  max_new_symbols_per_week: 2
  cooldown_after_consecutive_stops: {count: 2, sessions: 5}
  review_after_trades: 30
```

File chạy thực tế là `backend/rules/default.yaml`, có thêm vài khoá phục vụ ứng dụng mà đoạn trên chưa liệt kê:
`trapped.*` (ngưỡng và tỷ lệ của giao thức hàng kẹt, mục 6), `dca.catastrophe_stop_pct: 25` (ngưỡng thảm hoạ của chế độ DCA,
**của dự án**), và `alerts.*` (RTT cách duy trì bao nhiêu điểm thì cảnh báo, báo trước đáo hạn 7 và 1 ngày, lỗ danh mục 10% NAV,
của dự án). Các tham số vào lệnh (`entry.*`) đã có trong file nhưng ứng dụng chưa dùng, vì máy tính khối lượng mua thuộc nhóm P1.

---

## 9. Ví dụ hoàn chỉnh

Capital 200 triệu. Mã X giá 40.000, ATR14 = 1.200, ATR22 = 1.300.

- Cắt lỗ ban đầu: max(40.000 × 0,93 = 37.200 ; 40.000 − 2.400 = 37.600) = **37.600**. Khoảng cách 2.400.
- qty_plan = 3.000.000 / 2.400 = 1.250 → 1.200 cổ phiếu (48 triệu, 24% capital, vượt 20%) → cắt về **1.000 cổ phiếu** (40 triệu).
- Lần 1: mua 250 cổ phiếu tại 40.000. Lần 2 khi đóng cửa ≥ 40.000 + max(1.200, 1.200) = 41.200, lần 3 khi ≥ 42.400, lần 4 khi ≥ 43.700 hoặc bỏ nếu đã quá 44.000.
- Giả sử mua đủ 1.000 cổ phiếu, giá vốn trung bình 41.800.
- +7% (44.700): dời cắt lỗ về 41.800.
- +10% (46.000): bán 250, cắt lỗ lên 43.050.
- +15% (48.100): bán 250, cắt lỗ lên 44.700.
- +25% (52.250): bán 250, cắt lỗ lên 48.070.
- 250 cuối: Chandelier. Nếu đỉnh đóng cửa 56.000 và ATR22 lúc đó 1.500, trail = max(56.000 − 4.500 = 51.500 ; SMA20) → bán khi đóng cửa dưới 51.500.

Nếu ngay sau lần 1 giá đóng cửa dưới 37.600: bán 250 cổ phiếu, lỗ khoảng 600.000 đồng, tức **0,3% capital**. Đây là lý do chia 4 lần: sai lầm đầu tiên rất rẻ.

---

## 10. Cơ sở tham khảo: luật nào từ đâu

| Luật trong tài liệu | Nguồn gốc | Mức độ kiểm chứng |
|---|---|---|
| Cắt lỗ 7% cứng, không ngoại lệ | William O'Neil, *How to Make Money in Stocks*; quy tắc 7–8% của IBD | Phương pháp thực hành lâu năm, AAII xếp CAN SLIM vào nhóm chiến lược hiệu quả nhất |
| Cắt lỗ = ½ lãi thắng trung bình, trần 10% | Mark Minervini, *Trade Like a Stock Market Wizard* | Vô địch US Investing Championship 1997, 2021 |
| Cắt lỗ 2×ATR, thêm vị thế theo bước ATR, tối đa 4 đơn vị | Hệ thống Turtle (Richard Dennis), *Way of the Turtle* | Hệ thống có kết quả thực tế được ghi nhận thập niên 1980 |
| Rủi ro 1–2% mỗi lệnh, ngân sách 6%/tháng | Alexander Elder, *The New Trading for a Living* (luật 2% và 6%) | Chuẩn mực được dạy rộng rãi |
| Tính khối lượng theo 1R, đo kết quả bằng R-multiple, expectancy sau 30 lệnh | Van Tharp, *Trade Your Way to Financial Freedom* | Khung đo lường chuẩn ngành |
| Chốt lời phần lớn ở 20–25%; thị trường yếu chốt 10–15%, cắt lỗ 3–5% | O'Neil / IBD | Thực hành lâu năm |
| Luật 8 tuần | O'Neil / IBD | Thực hành lâu năm |
| Bán vào sức mạnh khi có dấu hiệu cao trào; khi nghi ngờ bán một nửa | O'Neil/IBD (climax top), Minervini | Thực hành lâu năm, chưa có kiểm định công bố |
| Bán giữ lãi khi thủng EMA21 với khối lượng lớn, hoặc dưới SMA50 | IBD | Thực hành |
| Mục tiêu 2R, 3R | Van Tharp; thực hành swing trading | Tham chiếu |
| Chandelier trailing 3×ATR22, ratchet | Chuck LeBeau, phổ biến qua Elder *Come Into My Trading Room* | Chỉ báo chuẩn trên mọi nền tảng |
| Chỉ thêm vào mã đang thắng, không trung bình giá xuống | Jesse Livermore; Turtle | Nhất quán giữa mọi trường phái theo xu hướng |
| Bộ lọc SMA200 / 10 tháng / 30 tuần | Weinstein *Secrets for Profiting in Bull and Bear Markets*; Faber (2007); Siegel | Nhiều backtest: giảm sụt giảm tối đa, lợi nhuận thô tương đương hoặc thấp hơn mua-giữ sau phí |
| Cắt lỗ có ích khi thị trường có quán tính | Kaminski & Lo, *Journal of Financial Markets* 2014; Han, Zhou & Zhu 2014 | Nghiên cứu học thuật bình duyệt |
| Giữ lỗ bán lãi là sai lầm hệ thống | Odean 1998, *Journal of Finance*; Barber & Odean về giao dịch quá mức | Nghiên cứu học thuật bình duyệt trên 10.000 tài khoản |
| DCA kém lợi nhuận kỳ vọng nhưng hợp người sợ lỗ | Vanguard, Finlay & Zorn 2023 | Nghiên cứu của tổ chức, 1976–2022 |
| Chốt lời từng phần làm giảm R trung bình | Mô phỏng của Bandy, Passamonte | Mô phỏng thực hành, chưa bình duyệt |
| Bậc 10/15/25 và tỷ lệ 25% mỗi bậc | **Của dự án**, nội suy từ O'Neil cho người mới xây kỷ luật | Chưa kiểm chứng, xem lại sau 30 lệnh |
| Cắt lỗ theo thời gian 10 phiên | **Của dự án** | Chưa kiểm chứng |
| RSI 45–65, khối lượng 1,2 lần, cách SMA20 ≤ 8% | **Của dự án**, tổng hợp thực hành phổ biến | Chưa kiểm chứng |
| Giao thức thoát hàng kẹt | **Của dự án**, dựa trên Odean và nguyên tắc giảm đòn bẩy trước | Chưa kiểm chứng |
| Đảo hàng quanh vị thế lõi: bán một phần khi hồi, mua lại khi chỉnh | TD Ameritrade *Ticker Tape* "Trading Around a Core Position"; Jim Cramer (CNBC); chuyên gia VPS trên Tin nhanh chứng khoán (đảo 30–50% lượng hàng) | Thực hành lâu năm, chưa có kiểm định công bố |
| Nhịp hồi trong xu hướng giảm thường dừng ở 38,2–50% đoạn giảm; quá 61,8% là dấu hiệu đổi xu hướng | Phân tích Fibonacci (StockCharts, Real Investment Advice) | Quy ước kỹ thuật, ý kiến chuyên gia |
| RSI dừng ở 55–60 trong xu hướng giảm | Constance Brown, *Technical Analysis for the Trading Professional*; Andrew Cardwell | Quy ước kỹ thuật |
| Ngưỡng 10%/20%, bán 30%+20%, mua lại khi thấp hơn 7%, 20 phiên | **Của dự án** | Chưa kiểm chứng |
| Giai đoạn 1–4 theo đường 30 tuần | Stan Weinstein, *Secrets for Profiting in Bull and Bear Markets* (1988) | Thực hành lâu năm |
| Giá dưới đường trung bình dốc xuống thì hồi gặp cản ở đường đó | Joseph Granville, quy tắc đường trung bình | Thực hành lâu năm |
| Đáy cũ bị thủng thành cản, hội tụ nhiều công cụ thì vùng mạnh hơn | John Murphy, *Technical Analysis of the Financial Markets* | Quy ước kỹ thuật, chưa có kiểm định công bố cho phần hội tụ |
| Điểm kiểm soát của hồ sơ khối lượng | Peter Steidlmayer, Market Profile | Quy ước kỹ thuật |
| Ngày bùng nổ xác nhận đáy thị trường | William O'Neil / IBD | Kiểm định độc lập: đúng khoảng 50–67% số lần |
| Bán 10% mỗi vùng cản, tối đa 30%; vừa đủ an toàn ký quỹ ở vùng đầu | **Của dự án**, theo đề xuất của người dùng | Chưa kiểm chứng |

Những gì **không** áp dụng dù có trong tài liệu chuẩn: tiêu chí Kelly (kể cả ½ Kelly) vì cần ước lượng xác suất thắng chính xác và giả định các lệnh độc lập, trong khi cổ phiếu Việt Nam tương quan cao; có thể xem lại sau 100 lệnh có số liệu.

Chưa tìm được nghiên cứu nào kiểm chứng quy tắc 7–8% trên dữ liệu thị trường Việt Nam với biên độ ±7% và chu kỳ T+2. Các nguồn tiếng Việt hiện có là bản dịch và tổng hợp từ O'Neil và Minervini. Đây là khoảng trống mà nhật ký của chính bạn sẽ lấp dần.

---

*Bộ luật này là khung kỷ luật, không phải khuyến nghị đầu tư. Các con số là điểm xuất phát dựa trên các phương pháp đã công bố, cần được xem lại sau mỗi 30 lệnh dựa trên nhật ký của chính bạn, và chỉ sửa khi không có vị thế mở.*
