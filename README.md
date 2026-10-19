# VideoDub

Tool tự động cho video Trung có hardsub: **làm mờ sub gốc → đọc và dịch theo ngữ cảnh → lồng tiếng nhiều giọng → chèn phụ đề Việt → xuất mp4 hoàn thiện**.

## Luồng xử lý

| Bước | Công nghệ | Ghi chú |
|---|---|---|
| 1. Đọc sub gốc | RapidOCR (offline) | Bỏ qua frame trống hoặc trùng; lọc chữ không nằm trên dòng sub (chữ trên xe, biển hiệu...) |
| 2. Dịch | Gemini | Phân tích cả kịch bản trước (nhân vật, tên riêng, xưng hô), sau đó dịch theo lô kèm người nói và giới tính của từng câu |
| 3. Lồng tiếng | Supertonic 3 (offline) | Mỗi nhân vật 1 giọng (M1–M5 / F1–F5); gộp câu ngắn liền nhau; câu dài thì model tự đọc nhanh hơn. Câu lỗi dùng Edge-TTS, rồi gTTS |
| 4. Xuất video | ffmpeg | Khung mờ ôm từng câu sub gốc, phụ đề Việt đặt đúng trên khung mờ, giọng gốc vặn nhỏ |

Đầu ra trong `output\`:
- `<tên>_vi.mp4`: video hoàn thiện.
- `<tên>.vi.srt`: phụ đề Việt.
- `<tên>.segments.json`: câu gốc, bản dịch, người nói. Sửa tay được rồi chạy lại.
- `<tên>.glossary.json`: bảng nhân vật và tên riêng do Gemini phân tích. Sửa tay được.

## Cài đặt (Windows)

1. Cài Python 3.10 trở lên. ffmpeg đã có sẵn trong `bin\`.
2. Double-click `install.bat`. Lần chạy đầu Supertonic sẽ tự tải model khoảng 400MB.
3. Dán Gemini API key (lấy tại https://aistudio.google.com/apikey) vào `secrets.yaml`. Không chia sẻ file này.

## Sử dụng

| Việc | Cách làm |
|---|---|
| **🌐 Mở Giao diện Web Studio (Khuyên dùng)** | Double-click `run_web.bat` (tự động mở trình duyệt tại `http://127.0.0.1:7860`) |
| **Mở giao diện kéo thả Desktop** | Double-click `run_app.bat` (hoặc lệnh `.venv\Scripts\python -m videodub.gui`) |
| Xử lý mọi video trong `input\` | `run_batch.bat` (video đã xong sẽ được bỏ qua) |
| Chạy chế độ Chỉ Vietsub (CLI) | `.venv\Scripts\python -m videodub run input\x.mp4 -o output -m vietsub` |
| Chạy chế độ Chỉ Lồng tiếng (CLI) | `.venv\Scripts\python -m videodub run input\x.mp4 -o output -m dubbing` |
| Giữ kết quả OCR, chỉ dịch lại | `run_retranslate.bat` |
| Làm lại từ đầu | thêm `--fresh` |
| Nghe thử tốc độ giọng | `.venv\Scripts\python calibrate_voice.py [M1 F2 ...]` |

### Tính Năng Mới Trên Giao Diện Web Studio:
1. **Gắn Link Trực Tiếp**: Hỗ trợ dán link Douyin, TikTok, YouTube Shorts, Kuaishou, Facebook Reels tự động tải và edit luôn không cần tải về máy trước.
2. **Đa Ngôn Ngữ**: Chọn dịch sang **Tiếng Việt 🇻🇳** hoặc **Tiếng Anh (English) 🇺🇸**.
3. **Tùy Chọn Sub Cũ**:
   - *Làm mờ sub gốc*: Phụ đề mới hiển thị đè lên đúng dải đã làm mờ.
   - *Để nguyên sub gốc*: Không làm mờ, phụ đề mới tự động định vị **bên dưới sub gốc** (hoặc bên trên nếu sub gốc ở sát đáy).
4. **Xử Lý Watermark & Logo**:
   - Che logo / watermark gốc ở 1 trong 4 góc (hoặc custom).
   - Dán logo thương hiệu riêng (PNG/JPG) vào 1 trong 4 góc và nhập kích thước pixel tùy ý.
5. **Tiến Trình Trực Quan 6 Ô Tròn**: Ô chưa chạy để tối, ô đang chạy nhấp nháy phát sáng, ô xong fill màu kèm dấu tick `✓`.
6. **Bảng Log Lệnh Trực Tiếp (Live Console)**: Hiển thị dòng lệnh và sự kiện theo thời gian thực ngay dưới thanh tiến trình.
7. **Popup Xem Video Ngay**: Khi xong video sẽ tự động bật popup xem video, nút tải MP4, tải SRT và mở thư mục.

Kết quả từng bước đều được lưu cache, nên lỗi ở bước sau thì chạy lại không phải làm lại các bước trước.

## Tuỳ chỉnh thường dùng (`config.yaml`)

| Mục | Ý nghĩa |
|---|---|
| `ocr.region` | Vùng tìm sub gốc. Mặc định `[0.6, 1.0]` là 40% phía dưới video |
| `blur.cover_new_sub` | `false`: khung mờ chỉ bao sub cũ; `true`: nới khung cho vừa cả phụ đề Việt |
| `translate.context` / `glossary` | Mô tả thêm về video và tên riêng bắt buộc. Tên trong `glossary` áp dụng cho MỌI video |
| `tts.supertonic.speed` | Tốc độ đọc, đang để 1.65 (đã chọn qua `calibrate_voice.py`) |
| `tts.speaker_voices` | Gán tay giọng cho nhân vật, ví dụ `{"Tôn Ngộ Không": "M2"}` |
| `tts.provider` | `supertonic` / `edge` |
| `original_audio.mode` | `duck` (vặn nhỏ giọng gốc) / `mute` (tắt hẳn) / `remove_voice` (tách giọng, cần demucs, chậm) |

## Giới hạn hiện tại

- Gemini miễn phí: model `gemini-3.8-flash` chỉ đủ khoảng 2 video mỗi ngày, sau đó tool tự chuyển sang `gemini-3.5-flash-lite`.
- OCR chỉ quét phần dưới video. Chữ hiệu ứng ở giữa màn hình không được xử lý.
- Repo Supertonic đã bị archive (không còn bản cập nhật). Model dùng giấy phép OpenRAIL-M.
