# Kế hoạch triển khai Karaoke trên Google Cloud — trạng thái thực hiện

> Snapshot triển khai ngày 29/10/2026. API, container chấm điểm, HTTPS/Nginx và quy trình chuẩn bị asset đã triển khai. Ngày 30/10 scorer production được nâng lên 0.4.3 với trọng số 30/20/50; xem [báo cáo triển khai](BAO_CAO_KARAOKE_GOOGLE_CLOUD.md#phát-hành-scorer-043). Phạm vi asset vẫn giữ ở 33 bài để thử nghiệm; không xử lý/upload các bài tiếp theo.

## 1. Mục tiêu đã triển khai

- Tách sẵn nhạc nền và giọng hát từ các file gốc đang lưu trên VM Google Cloud, dùng GPU NVIDIA trên máy local.
- Lưu hai file WAV, pitch reference và metadata trong thư mục karaoke riêng trên VM; ghi liên kết và metadata vào MongoDB collection karaoke_assets.
- Backend trả asset và lyrics đã có cho app; tạo phiên hát gắn với người dùng, songId và đúng phiên bản pitch reference.
- Sau khi hát, backend chuyển bản thu cùng timing sang FastAPI để chấm điểm. FastAPI không tách âm và không truy cập MongoDB.
- Không dùng SQLite, không nén WAV, không đặt trần RAM cho score container.

## 2. Hạ tầng đã xác minh

| Thành phần | Giá trị hiện tại |
|---|---|
| VM | moodify-server, GCP Compute Engine, Ubuntu 24.04, AMD64 |
| Địa chỉ | 136.85.101.19; HTTPS https://moodify.click |
| Tài nguyên | 2 vCPU, khoảng 8 GB RAM; boot disk đã nâng lên 70 GB |
| File nhạc gốc | /opt/music-data-collector/data/audio và /opt/moodify/uploads |
| Audio karaoke | /srv/moodify/karaoke/{songId}/{assetVersion}/ |
| MongoDB | music_streaming; collection tracks hiện hữu và karaoke_assets mới |
| Docker network | moodify_moodify-net |
| HTTPS media | https://moodify.click/karaoke/{songId}/{assetVersion}/... |

Hệ thống giữ nguyên các dịch vụ frontend, MongoDB, MySQL, OCR và emotion detection. Khi triển khai backend, chỉ container moodify-backend được thay; năm container khác vẫn giữ nguyên ID và trạng thái.

## 3. Luồng tổng thể

1. Batch local SSH vào VM để đọc mapping production, tải file nguồn và xác minh SHA-256.
2. Container prep chạy trên GPU local bằng model MelBand RoFormer đã huấn luyện sẵn; tạo instrumental.wav, vocals.wav, pitch_reference.json và manifest.
3. Batch xác minh đầu ra rồi upload theo thư mục phiên bản. VM kiểm tra lại mọi hash và file nguồn trước khi công bố trạng thái ready trong karaoke_assets.
4. Ứng dụng gọi backend GET /api/karaoke/tracks/{songId}; backend trả URL hai stem, lyrics, assetVersion và tình trạng scoring.
5. Backend POST /api/karaoke/tracks/{songId}/sessions để ghim reference/version vào phiên người dùng.
6. Trong khi hát, trình duyệt trích pitch features; khi hết bài backend nhận features tại POST /api/karaoke/sessions/{sessionId}/score/features, xác thực quyền sở hữu phiên, tải đúng reference và gửi tới FastAPI nội bộ.
7. Điểm và trạng thái phiên được lưu trong karaoke_sessions; file recording không được lưu trong MongoDB hoặc thư mục asset.

## 4. Dịch vụ, API và cấu hình

### Backend

- GET /api/karaoke/tracks/{songId}: trả title/artist/duration, lyrics hiện có, instrumentalUrl, vocalsUrl, assetVersion, referenceVersion và scoringAvailable.
- POST /api/karaoke/tracks/{songId}/sessions: tạo session có thời hạn 2 giờ, gắn với tài khoản JWT đang đăng nhập.
- POST /api/karaoke/sessions/{sessionId}/score: nhận recording multipart, giới hạn 80 MiB, timing và trả kết quả; một session không thể chấm bằng recording khác sau khi đã hoàn tất.
- POST /api/karaoke/sessions/{sessionId}/score/features: nhận pitch features từ luồng solo mới; backend chỉ trả và lưu điểm tổng.
- GET /api/karaoke/sessions/{sessionId}: đọc trạng thái/kết quả thuộc về chính người dùng.
- Collection karaoke_sessions lưu kết quả và hash bản thu; collection tracks hiện hữu không bị chỉnh sửa.

### FastAPI

- Docker Hub image hiện tại: dreayrt/audio_separator_for_karaoke:0.4.2-score (0.4.1-score được giữ để rollback)
- Public base URL: https://moodify.click/api/ai/karaoke
- Chỉ mở host loopback 127.0.0.1:8003 và private Docker network; backend gọi karaoke-score-production:8000.
- Chạy CPU, tối đa 1 CPU, một tác vụ score tại một thời điểm. Container không có memory limit.
- Nginx cho phép request tối đa 128 MiB và timeout 600 giây; backend giới hạn recording 80 MiB để còn chỗ cho reference/multipart.
- API key chỉ nằm trong /opt/moodify-karaoke/karaoke.env trên VM, quyền 0600; không gửi xuống browser.

### Chuẩn bị nguồn

- Image: dreayrt/audio_separator_for_karaoke:0.4.1-prep-gpu
- Tag CPU/GPU dev cũ không được sửa.
- Script services/karaoke/tools/prepare_library.ps1 chạy toàn bộ nguồn theo thứ tự, có report, resume, cache local và kiểm tra hash.
- Output giữ WAV PCM không nén. Guard dừng batch nếu disk usage vượt 80%; disk không tự tăng.

## 5. Model và cách diễn giải điểm

Model tách âm là MelBand RoFormer checkpoint karaoke đã huấn luyện sẵn; model này tạo stem, không chấm giọng người hát. Pitch reference được trích từ stem vocals bằng pYIN. Score hiện là thuật toán thử nghiệm pitch/rhythm/coverage, không phải mô hình AI đã huấn luyện để đánh giá giọng hát, phát âm, cảm xúc hoặc tính nhạc. API chỉ nhận phiên có scoringReference.status = sufficient; bài có reference không tin cậy vẫn có thể phát karaoke nhưng không mở session chấm điểm.

Smoke check dùng chính stem vocals làm recording cho cùng reference và đạt score 100. Đây chỉ chứng minh định dạng, hash và đường xử lý API hoạt động; không phải bằng chứng score đã được hiệu chỉnh trên người hát thật.

## 6. Đã kiểm tra

- Image score 0.4.2 đã push thành công lên Docker Hub và thay riêng container scoring; 0.4.1-score được giữ để rollback.
- FastAPI container chạy và readiness trả 200; memory limit Docker bằng 0 (không đặt giới hạn).
- Nginx HTTPS readiness trả 200; score info không có backend key trả 401.
- `POST /v1/score/features` hiện có trên production; request tổng hợp qua HTTPS được chấm thành công với scoring version `pitch-rhythm-v2-50-30-20`.
- File WAV qua Nginx hỗ trợ Range trả 206; manifest bị chặn trả 404.
- Backend từ image production gốc cộng thêm controller karaoke đã khởi động; chỉ moodify-backend được thay. Backend/score dùng chung network private.
- Ba bài mẫu đã tách GPU và upload; hai bài có reference sufficient, một bài reference_unreliable.
- Đợt test hiện có đúng 33 asset ready trong MongoDB: 32 reference đủ tin cậy để chấm, 1 reference không đủ tin cậy. Bài 34 chỉ được tải vào cache local, chưa tách/upload. Còn 71 nguồn đủ mapping/file đang pending, 42 track thiếu mapping và 7 không tìm thấy file. Không chạy batch tiếp cho tới khi chủ dự án muốn mở rộng phạm vi.
- Đã xác minh HTTP Range cho 66/66 file WAV của 33 bài; tất cả trả `206`. MongoDB ghi nhận 33 asset ready và 0 session; vì vậy bước kế tiếp là thử luồng có đăng nhập và bản thu thật trong ứng dụng.

## 7. Rollback và khôi phục

- Backend gốc vẫn được giữ dưới image moodify-backend:latest và moodify-backend-karaoke-base:rollback-20261029.
- Nginx có bản sao /opt/moodify-karaoke/nginx-default.pre-karaoke.20261029; script chỉ reload sau nginx -t thành công.
- Assets source và version cũ không bị xóa. Báo cáo inventory và cache local được giữ nguyên; chỉ mở rộng batch theo quyết định sau khi đánh giá xong bộ test 33 bài.
- Nếu cần rollback backend: chạy Compose gốc /opt/moodify/docker-compose.yml cho riêng service moodify-backend. Nếu cần rollback Nginx: khôi phục bản backup rồi nginx -t và reload.
- Không chạy docker compose down trên toàn project; thao tác đó có thể dừng các app hiện có.

## 8. Tệp tài liệu và lệnh chạy

- Hướng dẫn batch/local: KARAOKE_LOCAL_PREPARATION.md
- Báo cáo triển khai và số liệu thực tế: BAO_CAO_KARAOKE_GOOGLE_CLOUD.md
- Schema metadata: KARAOKE_MONGODB_SCHEMA.md
- Báo cáo hiện trạng bộ test 33 bài: `artifacts/karaoke/library/full-library-report.json`.
- Các bước test người dùng: đăng nhập ứng dụng, mở một bài có reference `sufficient`, kiểm tra đồng bộ playback, tạo session, gửi bản thu ngắn và xem điểm. Không dùng lệnh batch toàn thư viện trong giai đoạn thử nghiệm hiện tại.
