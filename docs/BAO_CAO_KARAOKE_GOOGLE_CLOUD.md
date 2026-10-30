# Báo cáo triển khai Karaoke trên Google Cloud

> Cập nhật 29/10/2026. Score service, HTTPS routes và backend đã triển khai. FastAPI score đang chạy bản 0.4.2; bản 0.4.1 được giữ dưới dạng rollback. Đợt thử nghiệm hiện giới hạn ở 33 bài đã publish; không tiếp tục xử lý/upload từ bài 34 trở đi.

## Tóm tắt

| Hạng mục | Trạng thái |
|---|---|
| FastAPI score-only 0.4.2 | Đang chạy trên VM, CPU 1, không giới hạn RAM Docker |
| Spring Karaoke backend | Đã bổ sung và khởi động từ image backend gốc |
| Nginx HTTPS/API/audio | Đã cấu hình, kiểm tra health, auth và HTTP Range |
| MongoDB karaoke_assets | Đã tạo và upsert asset theo songId/version |
| MongoDB karaoke_sessions | Đã tạo index ownership và TTL hết hạn |
| 3 bài smoke | Đã tách/upload; 2 reference đủ tin cậy, 1 reference không đủ |
| Bộ bài thử nghiệm | 33 asset ready; bài 34 chỉ có nguồn trong cache local, chưa tách/upload. 71 nguồn khác đang pending, 42 track thiếu mapping và 7 mapping không có file |

Báo cáo inventory nằm ở `artifacts/karaoke/library/full-library-report.json` (`complete=false` vì chưa xử lý hết inventory). Đây là trạng thái có chủ đích cho đợt thử nghiệm 33 bài. Không chạy lại batch toàn thư viện trong khi phạm vi thử nghiệm chưa được mở rộng.

## Hạ tầng

- Google Cloud VM: moodify-server, Ubuntu 24.04 AMD64, 2 vCPU, khoảng 8 GB RAM, boot disk 70 GB.
- HTTPS: https://moodify.click; IP VM 136.85.101.19.
- Track metadata: MongoDB music_streaming.tracks.
- Audio source hiện nằm ở /opt/music-data-collector/data/audio và /opt/moodify/uploads.
- File karaoke nằm ở /srv/moodify/karaoke/{songId}/{assetVersion}/.
- Docker network private dùng giữa moodify-backend và karaoke-score-production: moodify_moodify-net.
- Score container chỉ publish 127.0.0.1:8003:8000, dùng --cpus=1 và không có --memory limit. Docker inspect báo memory limit 0; FastAPI /v1/info xác nhận no-default-memory-cap, hard_limit_bytes=null và ceiling_percent=null.
- API key nằm ở /opt/moodify-karaoke/karaoke.env với quyền 0600; không được đưa xuống client.

Disk snapshot lúc 21 asset ready: total 71,686,545,408 bytes; used 23,941,087,232; free 47,728,680,960. VM helper ngăn upload mới nếu disk usage vượt 80%. Không nén WAV và không thay đổi kích thước disk thêm.

## Docker Hub images

Repository: dreayrt/audio_separator_for_karaoke.

| Tag | Vai trò | Digest |
|---|---|---|
| 0.4.0-score | FastAPI chấm điểm, CPU-only | sha256:d94aef98940eef2e05d60294395c508ea45fbd753991ddf6e5bd8873a169bfcc |
| 0.4.0-prep-gpu | Tách audio bằng GPU local | sha256:939db4c6e72a52d317d20b034308b4207a8895be5da2ffe0d2394cd5ff21dbdf |
| 0.4.1-score | FastAPI chấm điểm; sửa kiểm tra frame ở ranh giới hop | sha256:a86e308e05aefcd39aefc0be4a5f438d516b5ee4a9900ef46a827063aed87aa9 |
| 0.4.1-prep-gpu | Tách audio bằng GPU local; tương thích kiểm tra frame mới | sha256:3d5d4fe89215e6dd9afa895ba3a72cb13c6254e4cae5bd33e79e25b6317d8fca |
| 0.4.2-score | FastAPI nhận pitch features; chấm 50% cao độ, 30% nhịp, 20% độ phủ | sha256:ff7b95439754e37983b4634dafe17b03485a36c9da021d80a73e6021a319ac19 |

Các tag 0.4.0, 0.4.1 và 0.4.2 đã push thành công; VM đang chạy score 0.4.2. Container cũ được giữ ở trạng thái dừng với tên `karaoke-score-production-rollback-0.4.1`; image 0.4.1 cũng còn sẵn để rollback.

## Backend và API

Backend source bổ sung nằm trong E:/moodify-backend/src/main/java/com/laphuth/moodify/karaoke/KaraokeController.java; image đang chạy là moodify-backend-karaoke:2026-10-29-hardening, overlay compile từ JAR production gốc và chỉ thêm controller. Các thay đổi chưa commit khác trong backend không được lấy vào image.

- GET /api/karaoke/tracks/{songId}: trả instrumental/vocals URL, lyrics hiện có, assetVersion và trạng thái chấm.
- POST /api/karaoke/tracks/{songId}/sessions: tạo session gắn với username/JWT và khóa reference version.
- POST /api/karaoke/sessions/{sessionId}/score: nhận file recording tối đa 80 MiB cùng timing; backend tự lấy reference đúng version và gọi FastAPI nội bộ.
- POST /api/karaoke/sessions/{sessionId}/score/features: nhận pitch features lấy trong lúc hát; backend kiểm tra session/reference rồi gọi FastAPI `/v1/score/features`. Luồng solo mới không tải file giọng hát lên server.
- GET /api/karaoke/sessions/{sessionId}: lấy trạng thái/kết quả cho chính user đã tạo session.
- Score base: https://moodify.click/api/ai/karaoke; /v1/score cần secret backend-to-service.
- Static WAV: https://moodify.click/karaoke/{songId}/{assetVersion}/...; Nginx hỗ trợ byte ranges và không phục vụ manifest.

Collection karaoke_assets lưu hash, metadata, storageKey, model/config version và trạng thái scoring. Collection karaoke_sessions lưu session, hash bản thu, timing signature và score result; không lưu recording bytes. Index TTL tự dọn session sau expiresAt.

## Kiểm tra đã chạy

- Docker Hub push score 0.4.2 thành công; VM đã thay riêng score container, health/readiness trả 200, CPU quota 1, Docker memory limit 0, bind localhost 127.0.0.1:8003 và giữ private network alias.
- FastAPI health/ready trả 200; /v1/info không có secret trả 401.
- Đã gửi stem vocals cùng reference của chính stem qua API: request completed, overall/pitch/rhythm/coverage đều 100.
- Đã gửi request multipart chunked nhỏ: API parse request và trả EMPTY_FILE cho file rỗng (422), chứng minh framing chunked được nhận.
- HTTPS health trả 200; request score không auth trả 401.
- GET WAV với Range bytes=0-31 trả 206; manifest trả 404.
- Backend báo Started MoodifyApplication; route được gọi không có JWT trả 401 theo cấu hình auth mặc định.
- 5 container hiện hữu ngoài backend/score giữ nguyên ID qua deploy: MongoDB, MySQL, frontend, OCR, emotion detection.
- MongoDB xác nhận 154 tracks; unique index karaoke_assets.songId; session indexes sessionId+userId unique và TTL expiresAt.
- Kiểm tra cuối: backend/score cùng network và DNS alias; score memory limit Docker 0, CPU quota 1; HTTPS health 200, score info không auth 401, backend không JWT 401, WAV Range 206, manifest 404.
- Score API giới hạn request 128 MiB, audio 600 giây và một tác vụ đồng thời.

### Xác minh lại bộ 33 bài thử nghiệm

- MongoDB có đúng 33 document `karaoke_assets` trạng thái `ready`; 32 bài có scoring reference `sufficient`, 1 bài `reference_unreliable`. Chưa có karaoke session nào được tạo.
- Đã gửi HTTP Range `bytes=0-0` tới cả `instrumental.wav` và `vocals.wav` của toàn bộ 33 bài: 66/66 phản hồi `206 Partial Content`.
- Score API readiness `200`; endpoint không có backend key và backend endpoint không có JWT đều trả `401` như yêu cầu bảo vệ. Manifest không được public (`404`).
- HTTPS `POST /api/ai/karaoke/v1/score/features` trả `200` cho request tổng hợp 8 giây, `scoring_version=pitch-rhythm-v2-50-30-20`, điểm tổng `100`. Request kiểm tra thiếu file trả `422 MISSING_FILE` thay vì `404`, xác nhận public proxy route đã tới FastAPI.
- Disk VM tại lần xác minh: tổng 71,686,545,408 byte; đã dùng 24,902,500,352 byte; còn trống 46,767,267,840 byte. Guard upload vẫn dừng trước khi filesystem vượt 80%.

Trong batch, hai bài cho thấy sai lệch một frame ở thời lượng đúng ranh giới hop do số thực dấu phẩy động. Bản 0.4.1 trừ sai số biểu diễn rất nhỏ trước phép `ceil`; ngưỡng frame vẫn dựa trên timeline mẫu âm thanh. Batch được dừng có kiểm soát, các asset đã publish và cache được giữ nguyên, sau đó chạy lại bằng 0.4.1.

Smoke score 100 dùng cùng vocal/reference nên chỉ kiểm tra decode, reference hash, API và thuật toán chạy được. Nó không đo độ chính xác với ca sĩ thật. Scoring version pitch-rhythm-v1-experimental là thuật toán thử nghiệm dựa pYIN, không phải model đã huấn luyện để chấm phát âm/chất giọng.

## Mẫu đầu tiên

| Bài | songId | Kết quả reference |
|---|---|---|
| Vô Tình | 6a8230b53cccfc45cd626cdf | sufficient |
| Cánh Hoa Héo Tàn - Domino Remix | 6a8230b53cccfc45cd626ce6 | sufficient |
| TINH VE | 6a8230b53cccfc45cd626ced | reference_unreliable |

Bài thứ ba vẫn có stems để phát; endpoint từ chối tạo session chấm vì pitch reference không đạt ngưỡng.

## Rollback

- Backend image gốc giữ nguyên moodify-backend:latest và được gắn thêm moodify-backend-karaoke-base:rollback-20261029.
- Compose override chỉ đổi image/environment cho service moodify-backend. Rollback bằng Compose gốc /opt/moodify/docker-compose.yml cho riêng service đó.
- Nginx backup ở /opt/moodify-karaoke/nginx-default.pre-karaoke.20261029; đã test nginx -t trước khi reload.
- Karaoke source, các file khác và version cũ không bị xóa.

## Phần còn lại của đợt thử nghiệm

Phần chuẩn bị và kiểm tra khả năng tải asset đã xong cho đúng 33 bài. Bước còn lại cần thao tác trong ứng dụng bằng tài khoản thử nghiệm: đăng nhập, gọi GET chi tiết bài, phát và nghe đồng bộ hai stem với lyrics, tạo karaoke session, ghi một đoạn hát, gửi score và xem kết quả. Hiện chưa có session hoặc bản thu người dùng để xác nhận chất lượng chấm thực tế. Bài có reference `reference_unreliable` vẫn phát được nhưng không bật chức năng chấm điểm.

Chỉ mở rộng số bài sau khi người dùng quyết định. Inventory đầy đủ còn 71 nguồn có mapping/file chưa xử lý; 42 track thiếu mapping và 7 mapping trỏ tới file không tồn tại. Không chạy lệnh batch toàn thư viện trong giai đoạn test này.

## Phát hành scorer 0.4.3 — 30/10/2026

- Docker Hub image: `dreayrt/audio_separator_for_karaoke:0.4.3-score`.
- Digest: `sha256:a2572573fbfb9ac25612ee22b70bea2c18ee147e5c2d2e92b0f7acf142a866a5`.
- Scoring version: `pitch-rhythm-v3-30-20-50`; trọng số là 30% cao độ, 20% nhịp và 50% độ phủ.
- VM `moodify-server` đã cập nhật; container mới healthy trên `moodify_moodify-net`, giữ alias `karaoke-score-production` và bind `127.0.0.1:8003`.
- HTTPS `/api/ai/karaoke/health/ready` trả `ready`; `/v1/info` xác nhận service 0.4.3 và scoring version mới.
- Container 0.4.2 được giữ ở trạng thái dừng với tên `karaoke-score-production-rollback-0.4.2-20261030`; container rollback 0.4.1 vẫn còn.
