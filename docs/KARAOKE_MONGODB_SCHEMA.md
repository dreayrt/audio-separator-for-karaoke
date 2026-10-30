# MongoDB schema cho Karaoke

> Cập nhật 29/10/2026. MongoDB production đang dùng database music_streaming. Collection tracks hiện có. Collection karaoke_assets được tạo khi batch công bố bài đầu tiên; karaoke_sessions lưu phiên và kết quả chấm.

## 1. Collection karaoke_assets

Mỗi songId có tối đa một document hiện hành. songId lưu dạng chuỗi để backend tìm theo ID API; originalTrackId lưu đúng BSON ObjectId của tracks._id. Các trường source/assets/processing lấy theo manifest và được upsert chỉ sau khi file upload, hash và mapping gốc đã xác minh.

    {
      "songId": "6a8230b53cccfc45cd626cdf",
      "originalTrackId": ObjectId("6a8230b53cccfc45cd626cdf"),
      "status": "ready",
      "assetVersion": "bb7ae435063f87ea4852146f",
      "source": {
        "filename": "6a8230b53cccfc45cd626cdf.mp3",
        "localPath": "data/audio/xesi-hoaprox/3b2kCFZhX9GYnQ58qL1cAM_vo-tinh.mp3",
        "sha256": "[SHA-256 nguồn]",
        "durationSeconds": 273.90,
        "sampleRate": 44100
      },
      "assets": {
        "instrumental": {
          "storageKey": "karaoke/6a8230b53cccfc45cd626cdf/bb7ae435063f87ea4852146f/instrumental.wav",
          "sha256": "[SHA-256 WAV]",
          "bytes": 48316460,
          "format": "wav",
          "sampleRate": 44100,
          "channels": 2,
          "durationSeconds": 273.90
        },
        "vocals": {
          "storageKey": "karaoke/{songId}/{assetVersion}/vocals.wav",
          "sha256": "[SHA-256 WAV]",
          "bytes": 48316460,
          "format": "wav",
          "sampleRate": 44100,
          "channels": 2,
          "durationSeconds": 273.90
        },
        "pitchReference": {
          "storageKey": "karaoke/{songId}/{assetVersion}/pitch_reference.json",
          "sha256": "[SHA-256 JSON]",
          "bytes": 359269,
          "format": "json",
          "referenceVersion": "[SHA-256 version trong JSON]",
          "extractorVersion": "pyin-v1",
          "sampleRate": 22050,
          "hopLength": 512
        }
      },
      "scoringReference": {
        "status": "sufficient",
        "voicedSeconds": 126.015,
        "warnings": ["Experimental monophonic reference"]
      },
      "lyricTimeline": {
        "version": 1,
        "status": "ready",
        "language": "vi",
        "method": "ctc_forced_alignment",
        "model": "nguyenvulebinh/wav2vec2-base-vi-vlsp2020",
        "sampleRate": 16000,
        "coverage": 1.0,
        "meanConfidence": 0.82,
        "words": [
          {"text": "xin", "startMs": 14520, "endMs": 14880, "lineIndex": 0, "confidence": 0.81}
        ],
        "lines": [
          {"text": "xin chào", "startMs": 14520, "endMs": 15380, "firstWordIndex": 0, "wordCount": 2}
        ]
      },
      "processing": {
        "profile": "karaoke-v1",
        "modelFilename": "mel_band_roformer_karaoke_aufr33_viperx_sdr_10.1956.ckpt",
        "modelVersion": "[SHA-256 checkpoint]",
        "configVersion": "[SHA-256 cấu hình]",
        "device": "cuda",
        "deviceName": "NVIDIA GeForce RTX 4050 Laptop GPU",
        "precision": "float32",
        "parameters": {"segment_size":128,"overlap":2,"chunk_seconds":30,"chunking":"sample-exact-v1"},
        "preparedAt": "[BSON Date]"
      },
      "storage": {
        "provider": "gcp-vm",
        "root": "/srv/moodify/karaoke",
        "baseUrl": "https://moodify.click/"
      },
      "createdAt": "[BSON Date]",
      "updatedAt": "[BSON Date]"
    }

Các hash trong ví dụ là chỗ điền từ report/manifest; backend không nên tự tính ID phiên bản. Asset version được tạo từ hash file nguồn, checkpoint model và cấu hình. Khi một trong ba thứ đổi, batch tạo thư mục phiên bản mới, không ghi đè WAV cũ.

Index duy nhất trên songId được tạo khi upsert:

    db.karaoke_assets.createIndex({ songId: 1 }, { unique: true });

Nguồn gốc vẫn nằm trong các thư mục audio/uploads hiện tại. karaoke_assets chỉ giữ metadata và storageKey, không nhúng WAV vào MongoDB. URL file có dạng https://moodify.click/{storageKey}; manifest không được phục vụ công khai.

## 2. Collection karaoke_sessions

Session liên kết người dùng, bài hát, assetVersion và referenceVersion để không vô tình chấm bằng reference của bản khác. Trạng thái đi theo chuỗi started → scoring → completed; lỗi upstream trả session về started để có thể retry. Bản thu không lưu lại, chỉ lưu SHA-256 để nhận diện retry giống hệt.

Các trường chính:

- _id/sessionId: UUID.
- userId: username từ JWT của backend.
- songId, assetVersion, referenceVersion, referenceSha256, referenceStorageKey: reference đã ghim lúc bắt đầu.
- status: started, scoring hoặc completed.
- createdAt, expiresAt: session có hạn 2 giờ.
- recordingSha256, timingSignature: hỗ trợ retry đúng cùng bản thu/timing.
- scoreResult, scoringVersion, completedAt: kết quả cuối.

MongoDB có index duy nhất trên sessionId + userId và TTL index trên expiresAt. TTL tự dọn session sau khi hết hạn; bộ lọc backend vẫn kiểm tra expiresAt vì MongoDB TTL không xóa tức thời.

    db.karaoke_sessions.createIndex({ sessionId: 1, userId: 1 }, { unique: true });
    db.karaoke_sessions.createIndex({ expiresAt: 1 }, { expireAfterSeconds: 0 });

## 3. Ghi dữ liệu an toàn

1. Batch đọc tracks production qua helper SSH trên VM; private MongoDB credential không chuyển về local.
2. Nguồn tải về local có SHA-256 đối chiếu với bản nguồn trên VM.
3. Model tạo WAV/reference/manifest local; batch kiểm tra songId, model/config version, frame count và hash.
4. File upload vào thư mục staging .incoming; VM xác minh lại file, manifest và mapping local_path chưa đổi.
5. Thư mục staging được đổi tên atomic sang karaoke/{songId}/{assetVersion}/.
6. Upsert karaoke_assets thành ready sau cùng. Nếu lỗi giữa chừng, bài không được báo ready.

## 4. Liên kết với dữ liệu hiện có

Backend trả lyrics_plain và lyrics_synced từ tracks; chúng không được sao chép vào karaoke_assets. Giao diện karaoke hiện dùng timestamp câu có sẵn trong lyrics_synced theo định dạng LRC và đồng bộ với đồng hồ audio. Lời thường không timestamp không được tự chia theo thời lượng. lyricTimeline vẫn là trường tùy chọn trong karaoke_assets dành cho thử nghiệm căn từ ngoại tuyến, nhưng giao diện hiện tại không cần trường này để phát nhạc hoặc hiển thị lời. API tra track theo BSON ObjectId từ songId, sau đó truy vấn karaoke_assets bằng chuỗi songId. Track không có file nguồn hoặc chưa có status ready thì chưa phát karaoke.

Xem [API tích hợp](HUONG_DAN_TICH_HOP_KARAOKE.md), [hướng dẫn chạy batch GPU local](KARAOKE_LOCAL_PREPARATION.md), [trạng thái triển khai](KE_HOACH_KARAOKE_GOOGLE_CLOUD.md).
