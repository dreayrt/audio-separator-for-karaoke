# Hạ tầng runner GPU cho CI

Tài liệu này giải thích cách hạ tầng kiểm thử tích hợp dùng GPU của repo hoạt động.

## Tổng quan

Kiểm thử tích hợp cần phần cứng GPU để chạy suy luận mô hình ML. Máy ảo GPU tốn kém, vì vậy đội runner **chỉ tồn tại tạm thời**: mỗi tác vụ CI đang chờ sẽ tạo một máy ảo GCE mới, dùng một lần, từ image đã chuẩn bị sẵn. Máy ảo tự xóa sau khi tác vụ hoàn tất. Khi CI không chạy thì không có máy nào hoạt động hoặc phát sinh chi phí.

> **Lịch sử**: trước ngày 2026-05-18, đây là một nhóm máy ảo chạy lâu dài (`github-gpu-runner-{1,2,3}`) được bật/tắt theo yêu cầu. Giai đoạn 4 của đợt triển khai runner dùng một lần (karaoke-gen PR #780) đã xóa nhóm đó. Nếu gặp hướng dẫn bật/tắt máy ảo runner thì hướng dẫn đó đã cũ.

## Kiến trúc

```
Webhook của tổ chức GitHub (workflow_job.queued)
    │
    ▼
Cloud Function (github-runner-manager)
    │
    ├── chọn nhóm image dựa trên nhãn của job:
    │     gpu          → gha-runner-gpu         (Linux, n1-standard-4 + T4)
    │     docker-build → gha-runner-build       (Linux, e2-standard-8)
    │     mặc định     → gha-runner-general     (Linux, e2-standard-4)
    │     windows+gpu  → gha-runner-gpu-windows (Windows Server + T4; đang triển khai)
    │
    ├── tạo cấu hình runner tạm thời JIT (just-in-time) qua GitHub API
    └── tạo một máy ảo GCE dùng một lần từ nhóm image
            │
            ▼
        Máy ảo khởi động, chạy MỘT job (`run.sh --jitconfig`), hủy đăng ký,
        rồi tự tắt (đĩa khởi động tự bị xóa khi xóa máy ảo)

Cloud Scheduler (mỗi 15 phút)
    │
    ▼
Cloud Function (?action=cleanup_orphans)
    │
    ├── xóa máy ảo không còn runner (tuổi > 30 phút) hoặc bị treo (tuổi > 120 phút)
    └── hủy đăng ký runner mồ côi không còn máy ảo hoạt động
```

### Các thành phần (đều nằm trong repo karaoke-gen)

| Thành phần | Vị trí | Mục đích |
|-----------|--------|----------|
| Điều phối và dọn dẹp | `karaoke-gen/infrastructure/functions/runner_manager/ephemeral.py` | Chọn nhóm image, tạo cấu hình JIT, tạo máy ảo, dọn máy ảo mồ côi |
| Điểm nhận webhook | `karaoke-gen/infrastructure/functions/runner_manager/main.py` | Xác minh chữ ký, định tuyến sự kiện |
| Quy trình tạo image | `karaoke-gen/.github/workflows/build-runner-images.yml` | Tạo các nhóm image `gha-runner-<variant>` (lịch hàng tháng và chạy thủ công) |
| Cài đặt image | `karaoke-gen/infrastructure/scripts/runner-image-provision.sh` | Cài driver NVIDIA, Python, Poetry, binary runner và bộ nhớ đệm model khoảng 14 GB |
| Webhook GitHub | Cấp tổ chức (`nomadkaraoke`) | Gửi sự kiện `workflow_job` đến Cloud Function |

### Máy ảo runner GPU (dùng một lần)

- **Mẫu tên**: `gha-gpu-<hex>` (cùng dạng với `gha-general-<hex>`, `gha-build-<hex>`)
- **Loại máy**: n1-standard-4 (4 vCPU, RAM 15 GB) + 1 GPU NVIDIA T4
- **Vùng**: ưu tiên us-central1-a, dự phòng us-east4-c khi hết tài nguyên
- **Image**: nhóm `gha-runner-gpu` — driver NVIDIA và khoảng 14 GB model tại
  `/opt/audio-separator-models` được cài sẵn để job khởi động nhanh
- **Thời gian chạy**: một job CI (thường khoảng 7 phút), sau đó tự hủy

### Nhãn runner và `runs-on`

Runner GPU Linux có các nhãn: `self-hosted, linux, x64, gcp, gpu`.
Runner GPU Windows (đang triển khai) có các nhãn: `self-hosted, windows, x64, gcp, gpu`.

**Luôn ghi nhãn hệ điều hành trong `runs-on`** (ví dụ:
`[self-hosted, linux, gpu]`). GitHub gán job cho runner có tập nhãn bao gồm toàn bộ nhãn job yêu cầu. Nếu chỉ ghi `[self-hosted, gpu]`, job có thể được giao cho runner GPU Windows.

## Kiểm thử trên Windows

Có hai tầng (được thêm vào tháng 7/2026 để hỗ trợ RoFormer/DirectML, issue #292):

1. **`windows-cpu-integration`** — dùng runner `windows-latest` do GitHub cung cấp (miễn phí), chạy kiểm thử đầu cuối trên CPU với một model cho mỗi kiến trúc liên quan đến DirectML (RoFormer, MDX, VR). Model được lưu cache bằng `actions/cache`. Dùng Python 3.12 (torch-directml chưa có wheel cho 3.13 và các job DML phải dùng cùng phiên bản).
2. **`windows-directml`** (thử nghiệm, `continue-on-error`) — dùng máy ảo Windows Server + T4 tạm thời, tự quản lý (nhóm `gha-runner-gpu-windows`). Job chạy tách RoFormer/MDX/VR với `--use_directml`, kiểm tra chất lượng so với đầu ra tham chiếu, đầu ra hữu hạn và không im lặng, đồng thời xác nhận RoFormer nạp bằng phần triển khai mới (không âm thầm chuyển về nhánh cũ). Image dùng driver NVIDIA **GRID** (chế độ WDDM): driver trung tâm dữ liệu đặt T4 ở chế độ TCC, không hỗ trợ DirectX và làm DirectML không hoạt động. Job cài torch-directml qua pip (bản lock của Poetry giải extra `dml` thành torch-directml đời torch 1.13 không dùng được, trong khi bản hiện đại ghim `torch==2.4.1`).

## Các kiểm tra bắt buộc trong quy tắc bảo vệ nhánh GitHub

Ruleset `Protect main` (ID: 529535) yêu cầu các kiểm tra sau phải đạt trước khi merge:

- `unit-tests` — từ `run-unit-tests.yaml` (runner do GitHub cung cấp)
- `ensemble-presets` — từ `run-integration-tests.yaml` (runner GPU)
- `core-models` — từ `run-integration-tests.yaml` (runner GPU)
- `stems-and-quality` — từ `run-integration-tests.yaml` (runner GPU)

Hiện tại, `windows-cpu-integration` và `windows-directml` **chưa bắt buộc**. Sau giai đoạn ổn định, các job này sẽ được thêm vào ruleset và điều kiện thất bại của job kiểm soát.

**QUAN TRỌNG**: Nếu đổi tên job kiểm thử tích hợp (ví dụ tách job hoặc đặt tên khác), BẮT BUỘC cập nhật ruleset cho khớp. Ruleset được cấu hình tại:
https://github.com/nomadkaraoke/python-audio-separator/settings/rules/529535

Cập nhật qua API:
```bash
gh api repos/nomadkaraoke/python-audio-separator/rulesets/529535 \
  --method PUT --input - <<'EOF'
{
  "name": "Protect main",
  "enforcement": "active",
  "target": "branch",
  "conditions": {"ref_name": {"include": ["~DEFAULT_BRANCH"], "exclude": []}},
  "rules": [
    {"type": "deletion"},
    {"type": "pull_request", "parameters": {
      "required_approving_review_count": 0,
      "allowed_merge_methods": ["squash"]
    }},
    {"type": "required_status_checks", "parameters": {
      "required_status_checks": [
        {"context": "unit-tests", "integration_id": 15368},
        {"context": "JOB_NAME_HERE", "integration_id": 15368}
      ]
    }}
  ]
}
EOF
```

## Khắc phục sự cố

### Kiểm thử tích hợp bị kẹt ở trạng thái "queued"

**Triệu chứng**: các kiểm tra PR vẫn ở trạng thái `pending` cho `ensemble-presets`, `core-models`, `stems-and-quality`.

**Các bước chẩn đoán**:

1. Kiểm tra phản hồi của Cloud Function với webhook — đây là điểm lỗi phổ biến nhất. Lỗi 503 kèm `{"error": "HTTP Error 403"}` thường có nghĩa secret `github-runner-pat` đã hết hạn hoặc không được cấp quyền (secret này dùng để tạo cấu hình JIT). Xem toàn bộ lỗi trong log của function để loại trừ nguyên nhân do chính sách tổ chức hoặc giới hạn tốc độ. Kiểm tra các lần gửi gần đây của webhook tổ chức:
   ```bash
   gh api orgs/nomadkaraoke/hooks   # tìm ID webhook workflow_job
   hook_id=123456                   # thay bằng ID tìm được ở trên
   gh api "orgs/nomadkaraoke/hooks/${hook_id}/deliveries" --paginate | head -50
   ```
   Cách sửa: luân chuyển PAT và thêm phiên bản secret mới:
   ```bash
   echo -n "<new-pat>" | gcloud secrets versions add github-runner-pat \
     --project=nomadkaraoke --data-file=-
   ```

2. Kiểm tra máy ảo tạm thời đã được tạo chưa:
   ```bash
   gcloud compute instances list --project=nomadkaraoke \
     --filter='labels.purpose="gha-ephemeral-runner"'
   ```

3. Kiểm tra log Cloud Function để tìm lỗi điều phối:
   ```bash
   gcloud logging read 'resource.labels.service_name="github-runner-manager"' \
     --project=nomadkaraoke --limit=20 \
     --format="value(timestamp,textPayload,jsonPayload.message)"
   ```

4. Kiểm tra trạng thái đăng ký runner trên GitHub:
   ```bash
   gh api orgs/nomadkaraoke/actions/runners \
     --jq '.runners[] | {name, status, busy, labels: [.labels[].name]}'
   ```

### Máy ảo khởi động nhưng job không chạy

Trước khi xóa máy ảo chưa đăng ký, quy trình dọn dẹp runner mồ côi sẽ ghi log cổng serial của máy đó — hãy kiểm tra log Cloud Function (ở trên). Để tự kiểm tra máy ảo đang chạy:

```bash
# Dùng đúng vùng nơi máy ảo được tạo (ưu tiên us-central1-a,
# dự phòng us-east4-c khi hết tài nguyên — xem `gcloud compute instances list`).
gcloud compute instances get-serial-port-output <vm-name> \
  --zone=us-central1-a --project=nomadkaraoke --port=1 | tail -100
```

### Sự cố với image (lỗi driver, thiếu model)

Image được tạo lại hàng tháng (hoặc theo yêu cầu) bằng workflow `Build GHA Runner Images` trong karaoke-gen. Để chỉ tạo lại image GPU:

```bash
gh workflow run build-runner-images.yml --repo nomadkaraoke/karaoke-gen \
  -f variants=gpu
```

Các lỗi driver NVIDIA đã biết (không khớp kernel header, lỗi DKMS) được xử lý trong script cài image:
`karaoke-gen/infrastructure/scripts/runner-image-provision.sh`.

## Chi phí

| Trường hợp | Chi phí |
|----------|--------|
| Mỗi giờ máy ảo GPU Linux | ~$0.54/giờ (n1-standard-4 + T4, theo nhu cầu) |
| 3 job chạy song song × khoảng 10 phút | ~$0.27 mỗi lượt CI |
| Mỗi giờ máy ảo GPU Windows (dự kiến) | ~$0.72/giờ (cộng giấy phép Windows Server) |
| Thời gian nhàn rỗi | $0 (không có máy ảo giữa các job) |
