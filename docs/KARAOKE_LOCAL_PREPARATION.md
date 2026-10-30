# Chuẩn bị thư viện karaoke trên máy local

> Cập nhật 29/10/2026. Việc tách chạy foreground trên máy Windows local có NVIDIA GPU; nguồn được đọc trực tiếp từ kho Google Cloud và metadata MongoDB production. FastAPI trên VM chỉ chấm điểm bản thu sau khi hát.

## Luồng thực hiện

1. Script SSH vào VM, đọc danh sách tracks production và tìm file nguồn dưới /opt/music-data-collector/data/audio hoặc /opt/moodify/uploads.
2. Script tải nguồn về artifacts/karaoke/library/sources/ trên máy local và kiểm tra SHA-256.
3. Docker chạy image dreayrt/audio_separator_for_karaoke:0.4.1-prep-gpu, dùng CUDA/GPU local để tạo instrumental.wav, vocals.wav, pitch_reference.json và manifest.
4. Script kiểm tra hash/định dạng, upload asset vào /srv/moodify/karaoke/{songId}/{assetVersion}/, xác minh lại hash trên VM, rồi upsert document karaoke_assets.
5. Backend GET stem và lyrics. Trong khi user hát, trình duyệt trích pitch features; hết bài backend gửi features cùng đúng reference version tới score API, không tải file giọng hát lên.

Không có SQLite. File nguồn không bị xóa hoặc sửa. File output là WAV không nén.

## Thiết lập một lần

1. Cài Docker Desktop, bật GPU support/CUDA cho container và xác nhận nvidia-smi thấy GPU.
2. Tạo môi trường Python và cài dependency theo hướng dẫn của project. Môi trường .venv-karaoke đã dùng cho script này.
3. Tạo file config riêng, không đưa private key vào repo:

    New-Item -ItemType Directory -Force artifacts/karaoke | Out-Null
    Copy-Item services/karaoke/cloud.example.json artifacts/karaoke/cloud-config.json

4. Trong artifacts/karaoke/cloud-config.json, điền SSH target, đường dẫn private key .ppk đã dùng để SSH vào GCP và fingerprint host đã xác nhận. Giữ nguyên thư mục output nếu muốn dùng mặc định artifacts/karaoke/library.
5. Đảm bảo Docker Hub đã tải được tag 0.4.1-prep-gpu và SSH user có thể đọc file audio nguồn, ghi /srv/moodify/karaoke qua helper đã cài trên VM.

Config thực tế, key, bản tải nhạc và báo cáo nằm trong artifacts/karaoke/ và bị Git bỏ qua.

## Chuẩn bị thêm bài khi chủ dự án mở rộng phạm vi

Mở PowerShell tại repo và chạy:

    .\services\karaoke\tools\prepare_library.ps1 --report full-library-report.json

Để kiểm tra trước một vài bài:

    .\services\karaoke\tools\prepare_library.ps1 --limit 3 --report sample-report.json

Có thể chọn bài cụ thể bằng ID:

    .\services\karaoke\tools\prepare_library.ps1 --song-id 6a8230b53cccfc45cd626cdf --report one-song.json

Lệnh trên có thể xử lý tiếp các bài còn lại trong inventory; hiện tại phạm vi test được giới hạn ở 33 bài đã publish. Không chạy lệnh này cho đến khi chủ dự án yêu cầu mở rộng số lượng. Khi được yêu cầu, batch chạy lần lượt, không chạy nền hoặc song song; script kiểm tra hash nguồn/output và dùng lại output đã có. Không xóa file cache khi batch còn chạy.

## Theo dõi và kết quả

- Báo cáo: artifacts/karaoke/library/{report-name}.
- Log từng bài: artifacts/karaoke/library/{songId}.prepare.log.
- Asset tạo tại artifacts/karaoke/library/prepared/.
- Nguồn tải về lưu tại artifacts/karaoke/library/sources/ để resume.
- Status ready: audio/reference đã tạo, hash khớp và document đã ghi.
- missing_mapping: track không có local_path; missing_source: mapping có nhưng file không tồn tại.
- reference_unreliable: vẫn có thể phát instrumental/vocals, nhưng không bật chấm điểm cho bài đó vì vocal tham chiếu không đủ tin cậy.
- failed: xem log của songId tương ứng; sau khi sửa nguyên nhân, chạy lại batch.
- Script dừng an toàn khi kho đích sắp vượt 80% dung lượng filesystem; nó không tự tăng disk.

## Kiểm tra sau khi hoàn tất

    $r = Get-Content artifacts/karaoke/library/full-library-report.json -Raw | ConvertFrom-Json
    $r.counts | Format-List
    $r.songs | Where-Object status -in @('failed','missing_mapping','missing_source','capacity_blocked') | Select-Object songId,name,status,error

Production inventory được khảo sát có 154 track: 105 nguồn tồn tại để chuẩn bị, 42 thiếu mapping và 7 đường dẫn không có file. Batch sẽ ghi lại số thực tế tại thời điểm chạy; chỉ các bài ready mới có thể phát trong karaoke.

Trạng thái hiện tại: có đúng 33 bài ready trên VM/MongoDB để thử nghiệm. Bài 34 có file nguồn trong cache local nhưng chưa tách hoặc upload. `complete=false` nghĩa là inventory lớn chưa được xử lý hết; đây là trạng thái chủ đích trong giai đoạn test. Việc resume batch có thể upload tiếp các bài khác, vì vậy chỉ thực hiện khi chủ dự án quyết định mở rộng phạm vi.

## Tài liệu liên quan

- [Schema MongoDB](KARAOKE_MONGODB_SCHEMA.md)
- [API integration](HUONG_DAN_TICH_HOP_KARAOKE.md)
- [Báo cáo triển khai](BAO_CAO_TRIEN_KHAI_KARAOKE.md)
