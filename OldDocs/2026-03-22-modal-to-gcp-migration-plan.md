# Kế hoạch: Chuyển dịch vụ tách âm thanh từ Modal sang GCP

**Ngày tạo:** 2026-03-22

**Nhánh:** feat/sess-20260321-2314-modal-gcp-migration

**Worktree:** `karaoke-gen-modal-gcp-migration` (hạ tầng + backend), `python-audio-separator-modal-gcp-migration` (server)
**Trạng thái:** Bản nháp → Sẵn sàng triển khai

## Tổng quan

Chuyển dịch vụ tách stem âm thanh từ Modal sang Cloud Run Service với GPU L4 trên GCP. Việc này loại bỏ dependency tính toán bên thứ ba duy nhất, khắc phục lỗi API Modal xảy ra ngắt quãng (“không tải được file”), nâng cấp lên ensemble model mới nhất để có chất lượng tốt hơn, đồng thời tách quy trình tách âm thanh khỏi luồng duyệt lời bài hát quan trọng để người dùng có thể bắt đầu duyệt lời sớm hơn.

### Quyết định kiến trúc: Dịch vụ GPU Cloud Run

| Yếu tố | GPU Cloud Run | VM GCE + tự động dừng |
|-------|---------------|-----------------------|
| Chi phí khi nhàn rỗi | $0 (tự giảm về 0) | $0 (khi đã dừng) |
| Khởi động lạnh | ~30–60 giây (nạp model từ GCS) | ~60–120 giây (khởi động VM + nạp model) |
| Công vận hành | Không đáng kể (serverless) | Trung bình (script bật/tắt, giám sát sức khỏe) |
| GPU khả dụng | L4 (VRAM 24 GB) tại us-central1 | T4/L4/A100 |
| Mở rộng | Tự động | Điều phối thủ công |
| Chi phí/job (~12 phút GPU) | ~$0.13 | ~$0.07–0.10 (T4) |
| Triển khai | Đẩy Docker image | Image Packer + wheel trên GCS + khởi động lại qua SSH |

GPU Cloud Run được chọn vì đơn giản hơn. L4 nhanh hơn T4, thời gian khởi động lạnh chấp nhận được và chi phí mỗi job thấp hơn $1 đáng kể.

### Nâng cấp model: Dùng ensemble preset làm mặc định

**Model hiện tại (mỗi bước dùng một model):**
| Giai đoạn | Model | SDR | Ghi chú |
|----------|-------|-----|---------|
| 1 (nhạc nền) | `model_bs_roformer_ep_317_sdr_12.9755.ckpt` | 12.97 | BS-Roformer đời cũ |
| 1 (stem khác) | `htdemucs_6s.yaml` | — | Demucs 6 stem — **sẽ bỏ** |
| 2 (karaoke/bè nền) | `mel_band_roformer_karaoke_aufr33_viperx_sdr_10.1956.ckpt` | 10.20 | Model karaoke đơn |

**Mặc định mới (dùng ensemble preset):**
| Giai đoạn | Preset | Model | SDR | Ghi chú |
|----------|--------|-------|-----|---------|
| 1 | `instrumental_clean` | Fv7z + Resurrection | ~17.5 | Chất lượng tăng 35%, ít âm lọt |
| 2 | `karaoke` | 3 model karaoke (aufr33+gabox_v2+becruily) | ~10.6 | Chất lượng tăng 4%, ensemble 3 model |

**Thiết kế chính: tham chiếu bằng tên preset, không phải tên file model.** karaoke-gen gọi preset (`instrumental_clean`, `karaoke`). Package audio-separator ánh xạ preset thành danh sách model và thuật toán ensemble. Khi có model tốt hơn, chỉ cần cập nhật preset trong audio-separator và phát hành phiên bản mới — không phải sửa karaoke-gen.

### Tách quy trình: không chặn luồng duyệt lời

**Luồng hiện tại (cả hai bước đều phải xong mới duyệt được):**
```
Tạo job
├── Audio worker (tách âm thanh) ──→ audio_complete=True ──┐
│                                                         ├→ GENERATING_SCREENS → AWAITING_REVIEW
└── Lyrics worker (chuyển lời thành văn bản) → lyrics_complete=True ─┘
```

**Luồng mới (lời bài hát quyết định thời điểm duyệt, tách âm thanh chạy nền):**
```
Tạo job
├── Audio worker (tách âm thanh) ──→ audio_complete=True (chạy nền, không chặn)
│
└── Lyrics worker (chuyển lời thành văn bản) → lyrics_complete=True → GENERATING_SCREENS → AWAITING_REVIEW
                                                                                              │
                                                                                      Người dùng duyệt lời
                                                                                              │
                                                                                      Duyệt nhạc nền
                                                                               (chờ audio_complete nếu
                                                                                   chưa xong)
```

**Vì sao cách này hiệu quả:**
- Màn hình duyệt lời (`/app/jobs#/{jobId}/review`) chỉ cần kết quả nhận diện lời — không cần stem.
- Màn hình duyệt nhạc nền (`/app/jobs#/{jobId}/instrumental`) cần stem, nhưng người dùng thường mất hơn 5 phút duyệt lời, nhờ đó có thêm thời gian để tách âm thanh hoàn tất.
- Nếu người dùng đến màn hình duyệt nhạc nền trước khi tách xong, hiển thị trạng thái “Đang tách âm thanh…” để chờ.
- Worker tạo màn hình chỉ thực sự cần dữ liệu lời bài hát để tạo màn hình tiêu đề/kết thúc.

## Ước tính thời gian

| Kịch bản | Giai đoạn 1 | Giai đoạn 2 | Khởi động lạnh | Tổng |
|---------|-------------|-------------|----------------|------|
| Hiện tại (Modal, model đơn) | 3–5 phút | 2–3 phút | 0 | 7–11 phút |
| Ensemble mới (Cloud Run L4) | ~4–6 phút | ~3–5 phút | ~30–60 giây | ~8–12 phút |
| **Thời gian người dùng cảm nhận phải chờ** (mới) | — | — | — | **0 phút** (đã tách luồng) |

Ensemble khiến thời gian xử lý lâu hơn một chút, nhưng người dùng không phải ngồi chờ — họ duyệt lời trong khi tác vụ tách âm chạy nền.

## Yêu cầu

- [ ] Tách âm thanh chạy trên GCP Cloud Run với GPU L4.
- [ ] Giữ nguyên hợp đồng HTTP API của bản triển khai Modal (endpoint, định dạng request/response).
- [ ] CLI `audio-separator-remote` và `AudioSeparatorAPIClient` tiếp tục hoạt động không cần sửa.
- [ ] Model mặc định dùng ensemble preset (`instrumental_clean` + `karaoke`).
- [ ] karaoke-gen tham chiếu tên preset thay vì tên file model.
- [ ] Bỏ tách 6 stem bằng Demucs khỏi pipeline.
- [ ] Tự giảm về 0 khi không xử lý (không tốn chi phí GPU lúc nhàn rỗi).
- [ ] Khởi động lạnh dưới 60 giây.
- [ ] Chi phí mỗi job dưới $1.
- [ ] Lưu model trên GCS, nạp khi container khởi động.
- [ ] Endpoint truy cập công khai nhưng có token xác thực (dùng lại secret `admin-tokens`).
- [ ] Quản lý hạ tầng bằng Pulumi trong karaoke-gen.
- [ ] Tách quy trình tách âm khỏi luồng duyệt lời quan trọng.
- [ ] Trang duyệt nhạc nền xử lý được trạng thái “đang tách âm”.
- [ ] CI tạo Docker image nằm trong repo python-audio-separator và đẩy lên Artifact Registry.

## Các bước triển khai

### Giai đoạn 1: Server GPU Cloud Run (repo python-audio-separator)

#### Bước 1.1 — Tạo server FastAPI tương thích Cloud Run
- [ ] Tạo `audio_separator/remote/deploy_cloudrun.py`, dựa trên `deploy_modal.py`.
- [ ] Thay mã chỉ dành cho Modal:
  - `modal.Dict` → `dict` trong bộ nhớ (một instance xử lý mỗi lần một job)
  - `modal.Volume` → vùng lưu trữ cục bộ `/tmp` và GCS cho cache model
  - `modal.Function.spawn()` → xử lý đồng bộ (không cần tác vụ nền)
  - `modal.Image` → Dockerfile
  - `modal.App` → FastAPI chuẩn + uvicorn
- [ ] Giữ nguyên tất cả endpoint API:
  - `POST /separate` — gửi job tách âm thanh
  - `GET /status/{task_id}` — trả trạng thái job
  - `GET /download/{task_id}/{file_hash}` — tải file kết quả
  - `GET /models-json`, `GET /models` — liệt kê model
  - `GET /health` — kiểm tra sức khỏe (kèm trạng thái sẵn sàng của model)
  - `GET /` — thông tin gốc
- [ ] Thêm chức năng tải model lúc khởi động từ bucket GCS (`gs://nomadkaraoke-audio-separator-models/`).
- [ ] Thêm hỗ trợ ensemble preset: endpoint `/separate` nhận tham số `preset` rồi ánh xạ thành danh sách model + thuật toán.
- [ ] Thêm endpoint kiểm tra sẵn sàng GPU khi khởi động Cloud Run.

**Thiết kế:** Làm cho `/separate` về cơ bản chạy đồng bộ — xử lý ngay trong request, lưu kết quả trong dict bộ nhớ và hệ thống file cục bộ. Instance Cloud Run tiếp tục hoạt động trong thời gian chờ giảm tải (600 giây), để Giai đoạn 2 dùng lại instance còn nóng. Vẫn giữ hợp đồng API polling bất đồng bộ để client tương thích.

#### Bước 1.2 — Tạo Dockerfile
- [ ] Tạo `Dockerfile.cloudrun` ở thư mục gốc repo.
- [ ] Image nền: `nvidia/cuda:12.6.3-runtime-ubuntu22.04` (tương thích driver L4 của Cloud Run).
- [ ] Cài Python 3.13, FFmpeg, libsndfile, sox và thư viện audio hệ thống.
- [ ] Cài `audio-separator[gpu]` từ repo hiện tại.
- [ ] Entrypoint: `python -m audio_separator.remote.deploy_cloudrun`.
- [ ] Mở cổng 8080.
- [ ] Đặt biến môi trường: `MODEL_DIR=/models`, `STORAGE_DIR=/tmp/storage`.

#### Bước 1.3 — Tải model lên GCS
- [ ] Tạo bucket GCS `nomadkaraoke-audio-separator-models` (us-central1, lưu trữ chuẩn).
- [ ] Tải lên tất cả model cần cho ensemble preset mặc định:
  - `mel_band_roformer_instrumental_fv7z_gabox.ckpt` (preset instrumental_clean)
  - `bs_roformer_instrumental_resurrection_unwa.ckpt` (preset instrumental_clean)
  - `mel_band_roformer_karaoke_aufr33_viperx_sdr_10.1956.ckpt` (preset karaoke)
  - `mel_band_roformer_karaoke_gabox_v2.ckpt` (preset karaoke)
  - `mel_band_roformer_karaoke_becruily.ckpt` (preset karaoke)
- [ ] Tổng dung lượng: khoảng 1–1.5 GB model.

#### Bước 1.4 — Kiểm thử cục bộ
- [ ] Tạo Docker image trên máy cục bộ.
- [ ] Kiểm thử bằng `docker run --gpus all` (nếu có GPU cục bộ) hoặc chạy chế độ CPU.
- [ ] Xác minh API tương thích: gửi job với `preset=instrumental_clean`, truy vấn trạng thái, tải file kết quả.
- [ ] Xác minh định dạng tên file đầu ra khớp mẫu dự kiến: `filename_(StemType)_modelname.ext`.
- [ ] Xác minh tên stem của đầu ra ensemble chính xác.
- [ ] So sánh chất lượng đầu ra với Modal (A/B trên các bài tham chiếu).

#### Bước 1.5 — CI/CD cho Docker image
- [ ] Tạo `.github/workflows/deploy-to-cloudrun.yml` trong repo python-audio-separator.
- [ ] Kích hoạt khi phát hành lên PyPI, khi sửa `Dockerfile.cloudrun`, hoặc chạy thủ công.
- [ ] Các bước: tạo Docker image → đẩy lên Artifact Registry (`us-central1-docker.pkg.dev/nomadkaraoke/audio-separator`).
- [ ] Dùng Workload Identity Federation để xác thực với GCP.

### Giai đoạn 2: Hạ tầng GCP (repo karaoke-gen)

#### Bước 2.1 — Artifact Registry
- [ ] Thêm Docker repository Artifact Registry vào Pulumi.
- [ ] Tên repository: `audio-separator` tại `us-central1`.

#### Bước 2.2 — Bucket model GCS
- [ ] Tạo bucket `nomadkaraoke-audio-separator-models` bằng Pulumi.
- [ ] Dùng lớp lưu trữ Standard, tại us-central1.
- [ ] Cấp quyền đọc bucket cho service account của Cloud Run.

#### Bước 2.3 — Dịch vụ GPU Cloud Run
- [ ] Tạo `infrastructure/modules/audio_separator_service.py`.
- [ ] Cấu hình dịch vụ Cloud Run:
  - Image: lấy từ Artifact Registry
  - GPU: 1 NVIDIA L4
  - CPU: 4 vCPU (mức tối thiểu cần cho L4)
  - Bộ nhớ: 16 GiB
  - Số instance tối thiểu: 0 (tự giảm về 0)
  - Số instance tối đa: 2 (xử lý job đồng thời)
  - Timeout request: 1800 giây (30 phút)
  - Thời gian trì hoãn giảm tải: 600 giây (giữ máy nóng giữa Giai đoạn 1 → Giai đoạn 2)
  - Probe khởi động: HTTP GET `/health`, trễ ban đầu 120 giây, chu kỳ 10 giây
  - Biến môi trường:
    - `MODEL_BUCKET=nomadkaraoke-audio-separator-models`
    - `MODEL_DIR=/models`
    - `ADMIN_TOKEN` (lấy từ Secret Manager, dùng lại `admin-tokens` hiện có)
  - Region: us-central1
  - Ingress: mọi lưu lượng (endpoint công khai có xác thực)

#### Bước 2.4 — Service account và IAM
- [ ] Tạo service account `audio-separator`.
- [ ] Cấp quyền `storage.objectViewer` trên bucket model.
- [ ] Cấp quyền `secretmanager.secretAccessor` cho secret admin-tokens.
- [ ] Cấp quyền `logging.logWriter`, `monitoring.metricWriter`.

#### Bước 2.5 — Nối vào Pulumi
- [ ] Thêm vào `infrastructure/__main__.py`.
- [ ] Thêm hằng số cấu hình vào `infrastructure/config.py`.

### Giai đoạn 3: Tách luồng pipeline và nâng cấp model (repo karaoke-gen)

#### Bước 3.1 — Bỏ yêu cầu tách âm xong mới duyệt lời
- [ ] Trong `backend/services/job_manager.py`:
  - Đổi `check_parallel_processing_complete()` để chỉ kiểm tra `lyrics_complete` (không kiểm tra `audio_complete`).
  - `mark_lyrics_complete()` tự kích hoạt screens worker (không cần đợi audio).
  - `mark_audio_complete()` không còn kích hoạt screens — chỉ cập nhật cờ trạng thái.
- [ ] Trong `backend/workers/screens_worker.py`:
  - Bỏ xác thực yêu cầu `audio_complete` phải là True.
  - Screens chỉ cần dữ liệu lời để tạo màn hình tiêu đề/kết thúc.
  - Bỏ qua bước phân tích nhạc nền nếu audio chưa xong (hoặc không làm gì ở bước đó).
- [ ] Xác minh trang duyệt lời vẫn hoạt động khi chưa có stem.

#### Bước 3.2 — Thêm trạng thái “đang chờ tách âm” vào trang duyệt nhạc nền
- [ ] Trên trang duyệt nhạc nền của frontend (`/app/jobs#/{jobId}/instrumental`):
  - Kiểm tra `state_data.audio_complete` khi mở trang.
  - Nếu false, hiển thị “Đang tách âm thanh…” cùng chỉ báo đang chờ/tiến trình.
  - Hỏi trạng thái job mỗi 5–10 giây đến khi `audio_complete=True`.
  - Khi hoàn tất, tải và hiển thị các lựa chọn nhạc nền như bình thường.
- [ ] Backend: bảo đảm endpoint API duyệt nhạc nền trả về trạng thái tách âm.

#### Bước 3.3 — Chuyển sang cấu hình model theo preset
- [ ] Trong `backend/workers/audio_worker.py`:
  - Thay `DEFAULT_CLEAN_MODEL` bằng `DEFAULT_INSTRUMENTAL_PRESET = "instrumental_clean"`.
  - Thay `DEFAULT_BACKING_MODELS` bằng `DEFAULT_KARAOKE_PRESET = "karaoke"`.
  - Bỏ `DEFAULT_OTHER_MODELS` (đã bỏ Demucs).
  - Truyền tham số `preset=` vào API client thay vì `models=`.
- [ ] Trong `karaoke_gen/audio_processor.py`:
  - Sửa `_process_audio_separation_remote()` để truyền preset.
  - Giai đoạn 1: `api_client.separate_audio_and_wait(audio_file, preset="instrumental_clean", ...)`
  - Giai đoạn 2: `api_client.separate_audio_and_wait(vocals_file, preset="karaoke", ...)`
  - Bỏ tham số `other_stems_models` (hoặc mặc định thành danh sách rỗng).
  - Cập nhật cách sắp xếp kết quả ensemble (tên stem có thể kèm thông tin ensemble).
- [ ] Trong `audio_separator/remote/api_client.py` (repo python-audio-separator):
  - Thêm tham số `preset` vào `separate_audio()` và `separate_audio_and_wait()`.
  - Client gửi trường `preset` trong dữ liệu multipart form tới API.
  - Server API ánh xạ preset thành model và thuật toán.

#### Bước 3.4 — Cập nhật kiểm thử
- [ ] Cập nhật `tests/unit/test_audio_remote.py`:
  - Kiểm thử lệnh tách âm thanh dùng preset.
  - Bỏ tham chiếu đến tách 6 stem bằng Demucs.
  - Kiểm thử tên model/preset mặc định mới.
- [ ] Thêm kiểm thử cho việc tách luồng:
  - Xác minh `mark_lyrics_complete()` kích hoạt screens dù `audio_complete` chưa hoàn tất.
  - Xác minh `mark_audio_complete()` cập nhật cờ nhưng không kích hoạt screens.
- [ ] Thêm kiểm thử frontend cho trạng thái chờ ở trang duyệt nhạc nền.

### Giai đoạn 4: Chuyển dịch vụ và dọn dẹp

#### Bước 4.1 — Triển khai và kiểm thử
- [ ] Triển khai dịch vụ GPU Cloud Run bằng `pulumi up`.
- [ ] Chạy tách âm trên 3–5 bài thử bằng ensemble preset.
- [ ] So sánh chất lượng với Modal (nghe đối chiếu).
- [ ] Xác minh thời gian: ensemble hoàn tất trong khoảng 8–12 phút.
- [ ] Kiểm thử khởi động lạnh (đợi dịch vụ giảm tải rồi gửi job).
- [ ] Kiểm thử job liên tiếp (Giai đoạn 2 dùng lại instance còn nóng sau Giai đoạn 1).
- [ ] Kiểm thử việc tách luồng: trang duyệt lời xuất hiện trước khi tách âm hoàn tất.
- [ ] Kiểm thử trạng thái chờ trên trang duyệt nhạc nền.

#### Bước 4.2 — Cập nhật cấu hình audio worker trên Cloud Run
- [ ] Đổi `AUDIO_SEPARATOR_API_URL` trong `infrastructure/modules/cloud_run.py` từ URL Modal sang URL Cloud Run.
- [ ] Triển khai bằng `pulumi up`.
- [ ] Chạy 5–10 job thực tế và theo dõi lỗi.

#### Bước 4.3 — Theo dõi (1 tuần)
- [ ] Theo dõi log Cloud Run để phát hiện lỗi.
- [ ] Theo dõi thời gian tách âm trong `state_data` của job.
- [ ] Kiểm tra hóa đơn Cloud Run (xác minh chi phí mỗi job dưới $1).
- [ ] Xác minh dịch vụ tự giảm về 0 và không tính phí GPU lúc nhàn rỗi.
- [ ] Theo dõi người dùng có gặp trạng thái “đang chờ tách âm” hay không và đo tần suất.

#### Bước 4.4 — Ngừng Modal
- [ ] Xóa workflow triển khai Modal khỏi repo python-audio-separator.
- [ ] Xóa ứng dụng Modal.
- [ ] Đóng tài khoản Modal.
- [ ] Bỏ `modal` khỏi dependencies của python-audio-separator.
- [ ] Cập nhật biến môi trường `AUDIO_SEPARATOR_API_URL` trong các file `.envrc` cục bộ.

## Các file cần tạo/sửa

### Repo python-audio-separator (`python-audio-separator-modal-gcp-migration` worktree)

| File | Thao tác | Mô tả |
|------|----------|-------|
| `audio_separator/remote/deploy_cloudrun.py` | Tạo | Server FastAPI tương thích Cloud Run (dựa trên deploy_modal.py) |
| `audio_separator/remote/api_client.py` | Sửa | Thêm tham số `preset` vào các phương thức tách âm |
| `Dockerfile.cloudrun` | Tạo | Docker image để triển khai GPU trên Cloud Run |
| `.github/workflows/deploy-to-cloudrun.yml` | Tạo | CI/CD: tạo image rồi đẩy lên Artifact Registry |

### Repo karaoke-gen (`karaoke-gen-modal-gcp-migration` worktree)

| File | Thao tác | Mô tả |
|------|----------|-------|
| `infrastructure/modules/audio_separator_service.py` | Tạo | Pulumi: dịch vụ GPU Cloud Run + bucket model + IAM |
| `infrastructure/__main__.py` | Sửa | Kết nối dịch vụ audio-separator |
| `infrastructure/config.py` | Sửa | Thêm hằng số cấu hình audio-separator |
| `infrastructure/modules/cloud_run.py` | Sửa | Đổi `AUDIO_SEPARATOR_API_URL` sang URL Cloud Run |
| `backend/services/job_manager.py` | Sửa | Tách luồng: chỉ cần lyrics_complete để kích hoạt screens |
| `backend/workers/screens_worker.py` | Sửa | Bỏ điều kiện bắt buộc audio_complete |
| `backend/workers/audio_worker.py` | Sửa | Chuyển sang cấu hình preset, bỏ Demucs |
| `karaoke_gen/audio_processor.py` | Sửa | Truyền preset thay vì tên file model |
| `frontend/` (duyệt nhạc nền) | Sửa | Thêm trạng thái “đang chờ tách âm” |
| `tests/unit/test_audio_remote.py` | Sửa | Cập nhật cho preset, bỏ kiểm thử Demucs |
| `.github/workflows/deploy-audio-separator.yml` | Tạo | CI: triển khai revision Cloud Run khi có image mới |

## Chiến lược kiểm thử

- **Kiểm thử đơn vị:** ánh xạ preset, tách luồng (lời bài hát tự kích hoạt screens), cập nhật tên model.
- **Kiểm thử tích hợp:** triển khai dịch vụ Cloud Run, chạy tách âm đầy đủ bằng ensemble preset, xác minh file đầu ra.
- **So sánh A/B:** chạy cùng bài hát qua Modal (model đơn) và Cloud Run (ensemble) — chất lượng cần tốt hơn.
- **Kiểm thử pipeline:** gửi job, xác minh có thể duyệt lời trước khi tách âm xong.
- **Kiểm thử frontend:** Playwright E2E cho trạng thái chờ trên trang duyệt nhạc nền.
- **Kiểm thử khởi động lạnh:** chờ dịch vụ giảm tải, gửi job và đo tổng thời gian.
- **E2E môi trường thực tế:** sau khi chuyển dịch vụ, chạy 10 job thực tế qua toàn pipeline.

## Ước tính chi phí

| Trường hợp | Chi phí hàng tháng |
|----------|-------------------|
| 10 job/ngày × 12 phút GPU = 2 giờ/ngày | ~$40/tháng |
| 30 job/ngày × 12 phút GPU = 6 giờ/ngày | ~$120/tháng |
| Mỗi job (12 phút L4 ở $0.67/giờ) | ~$0.13 |

Chi phí thấp hơn nhiều so với ngân sách $1/job. Không tốn phí khi nhàn rỗi nhờ tự giảm về 0.

## Các câu hỏi đã giải quyết

- [x] Cloud Run hay VM GCE → **Dịch vụ GPU Cloud Run** (đơn giản nhất, tự giảm về 0)
- [x] Dùng GPU nào → **L4** (lựa chọn duy nhất trên Cloud Run, VRAM 24 GB)
- [x] Nâng cấp model → **Dùng ensemble preset làm mặc định** (ưu tiên chất lượng hơn tốc độ)
- [x] Demucs 6 stem → **Bỏ**
- [x] Xác thực → **Dùng lại secret `admin-tokens` hiện có**
- [x] CI Docker → **Repo python-audio-separator tạo và đẩy image**
- [x] UI ensemble preset → **Chỉ cấu hình ở backend; preset định nghĩa trong package audio-separator**
- [x] Tốc độ hay chất lượng → **Ưu tiên chất lượng; tách luồng để người dùng không phải chờ**

## Kế hoạch quay lui

1. **Quay lui nhanh:** đổi `AUDIO_SEPARATOR_API_URL` về URL Modal trong cấu hình Pulumi rồi chạy `pulumi up`. Mất khoảng 2 phút.
2. **Quay lui pipeline:** hoàn tác thay đổi trong job_manager để screens phải đợi `audio_complete`. Chỉ cần một commit.
3. **Giữ Modal hoạt động** trong thời gian theo dõi (Giai đoạn 4.3). Chỉ ngừng dịch vụ khi đã đủ tin cậy.
4. **Quay lui model:** đổi cấu hình preset về tên file model trực tiếp trong một commit.
