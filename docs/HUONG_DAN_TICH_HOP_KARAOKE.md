# Hướng dẫn tích hợp API Karaoke

> Cập nhật 30/10/2026. Production đang chạy scorer image 0.4.3 với trọng số cao độ/nhịp/độ phủ 30/20/50; image 0.4.2 được giữ để rollback. Nhạc được tách trước bằng GPU local; request lúc user chọn bài không gọi model tách âm.

## Luồng gọi từ backend/frontend

1. User đã đăng nhập bằng JWT của Moodify. Frontend lấy chi tiết karaoke theo songId.
2. Backend trả instrumentalUrl, vocalsUrl, lyricsSynced, lyricTimeline, assetVersion và scoringAvailable. Player tải WAV qua HTTPS; server hỗ trợ HTTP Range để bắt đầu phát trước khi tải toàn file.
3. Khi người dùng chọn bài có `scoringAvailable=true`, trình duyệt xin quyền micro nếu cần, backend tạo phiên khóa songId, assetVersion và referenceVersion, rồi frontend tự phát bài từ đầu. AudioWorklet phân tích cao độ micro theo từng khung 23 ms trong lúc hát. Cần dùng tai nghe để giảm nhạc nền lọt vào micro.
4. Khi audio phát hết, frontend gửi danh sách khung cao độ gọn tới backend; không gửi cả file thu âm. Backend kiểm tra quyền sở hữu phiên, ghim đúng pitch reference rồi gửi features và reference tới FastAPI.
5. FastAPI đối chiếu features với tham chiếu và tính điểm theo tỷ lệ cao độ 30%, nhịp 20%, độ phủ 50%. Backend chỉ lưu và trả điểm tổng; các điểm thành phần không được gửi tới frontend. Nếu trình duyệt không cấp quyền micro hoặc bài không có scoring reference đủ tin cậy thì không thể chấm điểm.

## API backend

Base URL hiện tại: https://moodify.click

### Lấy dữ liệu karaoke

    GET /api/karaoke/tracks/{songId}
    Authorization: Bearer {JWT người dùng}

Response gồm songId, title, artist, durationMs, lyricsPlain, lyricsSynced, lyricTimeline, instrumentalUrl, vocalsUrl, status, assetVersion, scoringAvailable, scoringReferenceStatus, referenceVersion và warnings. Màn hình hát một mình lấy các mốc câu từ `lyricsSynced` theo định dạng LRC (`[phút:giây.mili-giây]`) và đối chiếu với `currentTime` của audio. Câu trước, câu hiện tại và câu kế tiếp được hiển thị; câu hiện tại chuyển cảnh ngắn để dễ theo dõi. Giao diện không chia lời thường theo thời lượng và không dùng `lyricTimeline` để tô từng từ. Bài chưa có timestamp LRC vẫn phát nhạc nền nhưng báo rõ lời chưa được đồng bộ.

### Timeline từng từ (tùy chọn, không dùng cho giao diện hiện tại)

Script `services/karaoke/tools/align_word_lyrics.py` có thể căn lời theo stem `vocals.wav` bằng CTC forced alignment nếu sau này cần mốc từng từ. Đây là xử lý ngoại tuyến, không tham gia phát karaoke và không cần chạy trên laptop người dùng. Mặc định script chỉ lưu báo cáo JSON, còn `--write-mongodb` ghi `lyricTimeline` vào document hiện hành trong `karaoke_assets` của database được chọn. Ví dụ chạy thử một bài:

    python services/karaoke/tools/align_word_lyrics.py --database music_streaming_1 --limit 1 --output .\word-timing-preview.json

Sau khi xem báo cáo, chạy cả thư viện và ghi MongoDB bằng:

    python services/karaoke/tools/align_word_lyrics.py --database music_streaming_1 --write-mongodb --output .\word-timings.json

Model tiếng Việt mặc định cần tải lần đầu từ Hugging Face. Chỉ chạy khi thật sự cần timestamp từng từ; tính năng lời hiện tại chỉ cần LRC và không yêu cầu chạy model này. Kết quả confidence thấp được lưu thành `needs_review`. Lời sai hoặc thiếu so với phần vocal vẫn cần sửa nội dung nguồn rồi căn lại.

Nếu bài chưa có asset ready, trả 404. Bài có scoringReference không đủ tin cậy vẫn trả hai stem và lyrics nhưng scoringAvailable=false.

### Dữ liệu được gửi và lưu

Trong lúc hát, AudioWorklet trích xuất cao độ, độ tin cậy, RMS và mức clipping; không tạo hay tải lên file âm thanh. Khi hết bài, trình duyệt gửi các mảng features đã giới hạn tối đa 600 giây. Backend không trả các features này cho client khác.

Backend gửi features cùng pitch reference đã ghim cho phiên tới FastAPI qua multipart nội bộ. FastAPI chỉ giữ tệp JSON tạm trong thư mục request dưới `AI_TEMP_DIR` khi xử lý, rồi dọn thư mục. Bản thu giọng nói không được lưu trong MongoDB.

MongoDB `karaoke_sessions` lưu trạng thái phiên, điểm tổng, phiên bản và SHA-256 của payload features để nhận biết retry. Backend vẫn hỗ trợ endpoint multipart cũ cho tương thích; kết quả endpoint đó cũng được lọc để chỉ trả điểm tổng.

### Tạo phiên hát

    POST /api/karaoke/tracks/{songId}/sessions
    Authorization: Bearer {JWT người dùng}

Trả sessionId, songId, assetVersion, referenceVersion và expiresAt. Phiên hết hạn sau 2 giờ. Session chỉ thuộc về tài khoản đã tạo.

### Gửi features chấm điểm

    POST /api/karaoke/sessions/{sessionId}/score/features
    Authorization: Bearer {JWT người dùng}
    Content-Type: application/json

Body gồm `duration_seconds`, `f0_hz`, `voiced_probability`, `rms_dbfs`, `clipped_fraction`, `recording_start_offset_ms`, `capture_latency_ms` và `allow_octave_shift`. Mỗi frame cách nhau 512 mẫu ở 22.050 Hz; số frame phải khớp thời lượng và tối đa 600 giây. Các giá trị được kiểm tra ở backend và FastAPI.

Response chỉ có trạng thái và `score.overall`. Các điểm cao độ, nhịp, độ phủ và cảnh báo chất lượng không được trả ra API người dùng.

Backend gọi FastAPI nội bộ bằng `POST /v1/score/features`; file features và reference chỉ đi qua kết nối backend-to-service, có Bearer API key. FastAPI không nhận JWT người dùng.

Nếu gửi lại cùng features/timing sau khi đã hoàn tất, backend trả điểm tổng đã lưu; payload khác trên cùng session bị từ chối.

### Đọc trạng thái/kết quả phiên

    GET /api/karaoke/sessions/{sessionId}
    Authorization: Bearer {JWT người dùng}

Chỉ người tạo session đọc được trạng thái hoặc điểm. Session hết hạn hoặc đang có request chấm điểm trả conflict nếu gửi request thứ hai.

## FastAPI nội bộ

Public base để health/giám sát: https://moodify.click/api/ai/karaoke. Các route `/v1/score` (tương thích bản thu cũ) và `/v1/score/features` yêu cầu Bearer API key chỉ backend có.

Backend gọi URL riêng trong Docker network: http://karaoke-score-production:8000. Host chỉ bind 127.0.0.1:8003; không mở cổng score API ra Internet bằng firewall. Nginx chuyển HTTPS, giới hạn request 128 MiB và timeout 600 giây.

Score container dùng CPU, tối đa 1 CPU và một tác vụ đồng thời; không có memory limit. Features dài hơn 600 giây hoặc request vượt giới hạn bị từ chối. FastAPI không truy cập MongoDB, không tách bài hát và không giữ lịch sử.

## Ý nghĩa và giới hạn của điểm

Model MelBand RoFormer chỉ tách giọng hát/nhạc nền. Pitch reference được chuẩn bị ngoại tuyến; trình duyệt dùng YIN để trích cao độ micro và backend tính cao độ/nhịp/độ phủ bằng thuật toán thử nghiệm. Đây chưa phải mô hình AI đã huấn luyện để đánh giá phát âm, chất giọng, cảm xúc hoặc chất lượng biểu diễn. Thay đổi bộ trích xuất bản thu có thể làm điểm khác với cách pYIN cũ; cần benchmark trên bản thu thật trước khi deploy production.

## Mã lỗi thường gặp

| HTTP | Ý nghĩa |
|---:|---|
| 401 | JWT người dùng hoặc backend credential không hợp lệ |
| 404 | Không có track/session/asset ready tương ứng |
| 409 | Session hết hạn, đang chấm hoặc đã hoàn tất với recording khác |
| 413 | Recording cũ vượt 80 MiB hoặc JSON/features vượt giới hạn request/frame |
| 422 | Track thiếu scoring reference usable hoặc timing sai |
| 503 | Score service đang xử lý request khác; retry theo Retry-After |
| 502 | Backend không kết nối được FastAPI hoặc upstream gặp lỗi |

## Tài liệu liên quan

- [Chuẩn bị toàn bộ thư viện bằng GPU local](KARAOKE_LOCAL_PREPARATION.md)
- [Schema collection karaoke_assets và karaoke_sessions](KARAOKE_MONGODB_SCHEMA.md)
- [Kế hoạch triển khai đã thực hiện](KE_HOACH_KARAOKE_GOOGLE_CLOUD.md)
- [Báo cáo triển khai](BAO_CAO_KARAOKE_GOOGLE_CLOUD.md)
