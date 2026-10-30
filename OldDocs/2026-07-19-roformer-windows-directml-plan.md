# Kế hoạch: RoFormer trên Windows / DirectML (issue #292)

**Ngày:** 2026-07-19

**Nhánh:** `feat/sess-20260719-2104-roformer-windows-directml`
**Issue:** https://github.com/nomadkaraoke/python-audio-separator/issues/292

## Mục tiêu

Giúp các model RoFormer (BSRoformer + MelBandRoformer) chạy với `--use_directml` trên GPU AMD/Intel của Windows, đồng thời **không thay đổi hành vi** của người dùng CUDA, MPS và CPU trên mọi nền tảng. Thêm kiểm thử Windows + DirectML vào CI để Windows thực sự được hỗ trợ lâu dài.

Demucs trên DirectML **nằm ngoài phạm vi**: lỗi tại `aten::_thnn_fused_lstm_cell` do torch-directml thiếu toán tử này. Không có gì để vá ở phía project; cần ghi rõ không hỗ trợ trong bảng tương thích của README.

## Phân tích nguyên nhân gốc (từ báo cáo issue và đọc mã nguồn)

Người báo lỗi (torch-directml 0.2.5, audio-separator 0.44.2) gặp hai lỗi riêng biệt:

### Lỗi 1: `'>=' not supported between instances of 'torch.device' and 'int'`

`RoformerLoader._load_with_new_implementation` gọi
`torch.load(model_path, map_location=device)` (`roformer_loader.py:98`), trong đó
`device` là `str(self.torch_device)` = `"privateuseone:0"` (truyền từ
`mdxc_separator.py:92`). torch-directml đăng ký hook giải tuần tự cho backend
`privateuseone`, hook này cần mã định danh thiết bị dạng số nguyên. Truyền một
`torch.device` gây TypeError bên trong phép so sánh
`device_id >= device_count()` của `torch_directml.device()`.

Hậu quả: phần triển khai **mới** luôn lỗi trên DML rồi âm thầm quay về đường xử lý cũ (đường cũ nạp với `map_location='cpu'`, nên chạy tiếp được). Vì vậy người dùng DML hiện không bao giờ dùng được phần triển khai mới.

Lưu ý, đường MDXC không dùng Roformer đã biết kiểu vấn đề này — `mdxc_separator.py:~108` nạp state dict TFC_TDF với `map_location="cpu"` và chú thích: “nạp state trực tiếp lên thiết bị tăng tốc phần cứng gây lỗi”.

### Lỗi 2: `Invalid or unsupported data type ComplexFloat`

torch-directml không hỗ trợ tensor phức. Lượt forward của Roformer chạy các phép toán phức trên thiết bị model (`uvr_lib_v5/roformer/bs_roformer.py`, tương tự trong `mel_band_roformer.py`):

- `torch.stft(..., return_complex=True)` trên đầu vào (bs_roformer.py:453)
- `torch.view_as_complex` + nhân mask phức (bs_roformer.py:503–506)
- `torch.istft` (bs_roformer.py:512)

Trong codebase đã có hai tiền lệ cho cách sửa:

- **Kiến trúc MDX** (`uvr_lib_v5/stft.py:22`): nếu `is_non_standard_device` (loại thiết bị khác cpu/cuda) thì chuyển tensor hop sang CPU để chạy STFT/ISTFT, rồi chuyển kết quả về. Đây chính là lý do MDX **đang chạy được** trên DML.
- **Đường MPS của Roformer** (bs_roformer.py:512): khi `x_is_mps`, chạy istft trên CPU.

### Lỗi có thể có thứ 3 (chưa phát hiện — đang bị lỗi 2 che khuất)

`Attend.flash_attn` (`uvr_lib_v5/roformer/attend.py`) gọi
`F.scaled_dot_product_attention` bên trong context
`torch.backends.cuda.sdp_kernel`; loader mặc định đặt `flash_attn=True`.
Khả năng SDPA hoạt động trên torch-directml còn thấp. Nếu lỗi, `Attend.forward`
đã có đường tính thuần einsum/softmax để chuyển tensor DML sang dùng. Chỉ biết
được sau khi sửa lỗi phép toán phức và inference chạy tới transformer — job CI
DML (Giai đoạn 4) cùng người báo lỗi sẽ giúp xác nhận.

## Thiết kế sửa lỗi — mọi thay đổi chỉ áp dụng khi `device.type == "privateuseone"`

Nguyên tắc: mỗi thay đổi phải nằm sau điều kiện DirectML rõ ràng để các đường CUDA/MPS/CPU **giống hệt từng byte** trước và sau. Nhánh istft MPS vẫn dùng cờ `x_is_mps` riêng — KHÔNG gộp MPS vào nhánh chung “thiết bị không chuẩn”, vì hiện tại MPS chạy STFT forward trên thiết bị và hành vi đó không được đổi.

Thêm một helper nhỏ (ví dụ trong `uvr_lib_v5/roformer/` hoặc `common_separator`):

```python
def is_dml_device(device) -> bool:
    return torch.device(device).type == "privateuseone"
```

(`privateuseone` là khe backend chung của PyTorch cho backend bên ngoài, nên về lý thuyết backend khác cũng có thể dùng. Tuy nhiên nhánh này chỉ tới được khi chính Separator đặt thiết bị bằng `torch_directml.device()` với `use_directml=True`, vì vậy nó không thể kích hoạt nhầm cho người dùng cuda/mps/cpu.)

### Giai đoạn 2a: Sửa loader (khắc phục lỗi 1)

Trong `RoformerLoader._load_with_new_implementation`:

```python
map_loc = 'cpu' if is_dml_device(device) else device
state_dict = torch.load(model_path, map_location=map_loc)
...
model.to(device)   # giữ nguyên; torch.device("privateuseone:0") hợp lệ sau khi import torch_directml
```

Chỉ bật nhánh này cho DML (cách làm thận trọng), dù nạp CPU rồi gọi `.to()` có ý nghĩa tương đương trên mọi nền tảng. Phần `_load_with_legacy_implementation` vốn đã dùng cách tương tự (luôn dùng `'cpu'`) — không đổi phần đó. Giữ nguyên cơ chế fallback về legacy.

Đồng thời xác minh `model.to("privateuseone:0")` hoạt động khi truyền *chuỗi* — đường legacy vốn đã gọi `.to(device)` với cùng chuỗi và log của người báo lỗi cho thấy đã tới được inference, nên điều này được xem là đã xác nhận.

### Giai đoạn 2b: Chuyển phép toán phức sang CPU trong `bs_roformer.py` + `mel_band_roformer.py`

Trong `forward()`, tính `x_is_dml = original_device.type == "privateuseone"` bên cạnh cờ `x_is_mps` hiện có:

1. **STFT forward**: nếu `x_is_dml`, chạy `torch.stft` trên CPU
   (`raw_audio.cpu()`, cửa sổ CPU), gọi `view_as_real`, rồi chuyển tensor giờ chỉ còn số thực lên thiết bị DML. Band-split và transformer stack (phần tính toán nặng, tức phần đáng tăng tốc) vẫn chạy trên DML.
2. **Điều chế mask + iSTFT**: nếu `x_is_dml`, chuyển `stft_repr` và `mask` sang CPU trước khi gọi `view_as_complex`; thực hiện phép nhân phức và `torch.istft` trên CPU, rồi chuyển `recon_audio` về thiết bị. Vòng lặp demix vốn chuyển đầu ra sang CPU ngay sau đó, nên chi phí này gần như không đáng kể.
3. Điều kiện `x_is_mps` hiện tại ở lệnh gọi istft được đổi thành `x_is_mps or x_is_dml` **chỉ tại lệnh gọi istft vốn đã chuyển MPS sang CPU** — các bước chuyển riêng cho DML (STFT, phép nhân phức) không tác động đến nhánh MPS.

Áp dụng giống nhau cho cả hai file model; lượt forward của chúng gần như giống hệt.

### Giai đoạn 2c: Fallback cho attention (chỉ làm nếu lỗi 3 thực sự xảy ra)

Nếu SDPA lỗi trên DML: trong `Attend.forward`, chuyển
`q.device.type == "privateuseone"` sang đường einsum không dùng flash hiện có
(einsum/softmax là các toán tử cơ bản được torch-directml hỗ trợ). Không thay đổi
hành vi flash trên cuda/cpu/mps.

## Kế hoạch kiểm thử và CI

### Hiện trạng

- `run-unit-tests.yaml`: ubuntu + macos + **windows-latest** (CPU, `-E cpu`),
  Python 3.10–3.13 — đã có kiểm thử đơn vị trên Windows.
- `run-integration-tests.yaml`: 3 job trên runner GCP T4 tự quản lý **Linux**
  (`[self-hosted, gpu]`), model được cache sẵn tại
  `/opt/audio-separator-models`. Ruleset bảo vệ nhánh 529535 yêu cầu
  `ensemble-presets`, `core-models`, `stems-and-quality`, `unit-tests`
  — **mọi tên job bắt buộc mới phải được thêm vào ruleset** (lưu ý trong
  OldDocs/CI-GPU-RUNNERS.md).

### Tầng CI mới 1 — Smoke test tích hợp Windows CPU (miễn phí, mỗi PR)

Thêm job `windows-cpu-integration` dùng `windows-latest` vào
`run-integration-tests.yaml` (lọc theo đường dẫn giống các job khác):

- `poetry install -E cpu`; cài ffmpeg qua choco hoặc `FedericoCarboni/setup-ffmpeg`.
- Chạy một tập con E2E với fixture ngắn: một model Roformer nhỏ (chọn checkpoint
  mel-band nhỏ nhất trong các kiểm thử hiện có) và một model MDX, xử lý clip
  dài vài giây. Roformer CPU trên 4 lõi chạy chậm — độ dài fixture là yếu tố
  điều chỉnh chính; mục tiêu là dưới 10 phút thực tế.
- Cache model tải về bằng `actions/cache`, khóa theo tên file model
  (runner do GitHub cung cấp không có sẵn thư mục model).
- Mục đích: bắt lỗi riêng Windows (đường dẫn, soundfile/ffmpeg, libsamplerate)
  ở mỗi PR và duy trì lâu dài. Đây là mức nền để tuyên bố “Windows được hỗ trợ”,
  độc lập với DirectML.
- Đưa job này vào trước (trước khi sửa code) để có baseline Windows đạt trước.

### Tầng CI mới 2 — Windows DirectML trên nhóm runner hiện có

**Quyết định (Andrew, 2026-07-19):** theo mô hình runner tự quản lý dùng một
lần hiện tại và mở rộng để hỗ trợ Windows, thay vì dùng runner GPU lớn do
GitHub lưu trữ. Khi đã ổn định, job mới sẽ trở thành một trong các kiểm tra
tích hợp bắt buộc hiện có (ruleset 529535).

#### Cách nhóm runner hiện tại hoạt động (hạ tầng karaoke-gen)

- Webhook tổ chức `workflow_job.queued` → Cloud Function
  `github-runner-manager`
  (`karaoke-gen/infrastructure/functions/runner_manager/{main,ephemeral}.py`)
  tạo cấu hình JIT và khởi tạo **một máy ảo GCE chỉ dùng một lần** từ họ image
  đã chuẩn bị sẵn. VM chạy một job (`./run.sh --jitconfig`), tự tắt qua EXIT
  trap; bộ dọn mồ côi chạy mỗi 15 phút để xóa VM đã dừng và hủy đăng ký runner
  mồ côi.
- Các họ image khai báo trong `FAMILIES` của `ephemeral.py`
  (`general`/`build`/`gpu`), được chọn từ nhãn job
  (`resolve_family`, thứ tự ưu tiên gpu → build → general). Nhãn runner
  quảng bá được tạo bởi `runner_labels_for()` — hiện đang **ghi cứng linux**.
- Image được tạo bởi
  `karaoke-gen/.github/workflows/build-runner-images.yml`
  (cron hàng tháng và chạy thủ công): VM tạm từ `debian-12` chạy
  `infrastructure/scripts/runner-image-provision.sh`, sau đó snapshot đĩa
  khởi động thành họ image `gha-runner-<variant>`. Image GPU cài sẵn driver
  NVIDIA cùng khoảng 14 GB model trên đĩa 200 GB.

#### Mở rộng hỗ trợ Windows (cần sửa trong repo karaoke-gen)

1. **Thêm họ mới** `gpu-windows` vào `FAMILIES` trong `ephemeral.py`:
   - `machine_type="n1-standard-4"`, accelerator T4, `disk_size_gb=200`,
     `image_family="gha-runner-gpu-windows"`.
   - Thêm trường `os_label` vào `FamilySpec` (mặc định `"linux"`, họ mới
     đặt `"windows"`) để `runner_labels_for()` không còn ghi cứng `linux`.
     Nhãn quảng bá: `self-hosted, windows, x64, gcp, gpu`.
   - `resolve_family`: kiểm tra `windows` trước — nhãn `windows` + `gpu`
     chọn `gpu-windows` (Windows không có gpu có thể trả 404/không khớp; hiện
     chưa có họ Windows thường).
   - VM Windows nhận startup script qua metadata
     `windows-startup-script-ps1`, không phải `startup-script` — cần thêm
     nhánh PowerShell tương ứng với `STARTUP_SCRIPT` trong
     `_build_instance`: lấy `jit-config` từ instance metadata, chạy
     `cd C:\actions-runner`, `\.\run.cmd --jitconfig $jit`, rồi
     `shutdown /s` trong khối finally.
   - Chi phí: T4 + n1-standard-4 (~$0.54/giờ) + giấy phép Windows Server
     (~$0.18/giờ) ≈ **$0.72/giờ → ~$0.18 cho mỗi lượt 15 phút**. Cách tự giảm
     về 0 không đổi; dọn mồ côi vẫn dùng được (không phụ thuộc hệ điều hành:
     đối chiếu danh sách VM với runner đã đăng ký ở cấp tổ chức).
   - Cập nhật `test_ephemeral.py` để kiểm thử họ runner/nhãn/metadata mới.

2. **Thêm biến thể tạo image** vào `build-runner-images.yml` và
   `runner-image-provision.ps1`:
   - Image nền: `windows-cloud/windows-server-2022-dc` (không dùng debian).
   - **Lưu ý về driver:** cài **driver NVIDIA GRID/virtual-workstation**
     (Google Cloud lưu installer ở `gs://nvidia-drivers-us-public`), KHÔNG
     dùng driver trung tâm dữ liệu/CUDA. T4 với driver trung tâm dữ liệu chạy ở
     chế độ tính toán TCC, không có hỗ trợ DirectX/WDDM — DirectML sẽ không
     thấy GPU. Driver GRID → WDDM → DX12 → DirectML hoạt động.
   - Cài Python **3.12** (torch-directml chưa có wheel cho 3.13 — môi trường
     hoạt động của người báo lỗi là 3.12.8; cần kiểm tra lại khi triển khai),
     git, ffmpeg, Poetry, gói actions-runner **win-x64** tại
     `C:\actions-runner`, và cache model dựng sẵn (cùng tập model với image
     GPU Linux) tại `C:\audio-separator-models`.
   - Báo hiệu sẵn sàng: luồng Linux dò `/opt/runner-image-ready` qua SSH;
     trên Windows, ghi một dòng đánh dấu ra serial console rồi dò bằng
     `gcloud compute instances get-serial-port-output` (không phụ thuộc
     SSH/WinRM — phù hợp quy ước của repo rằng “serial console là kênh chẩn
     đoán duy nhất đáng tin cậy”).

#### Thay đổi workflow (repo python-audio-separator)

- **Sửa định tuyến nhãn (phải có trước hoặc cùng lúc với runner Windows):**
  ba job hiện tại dùng `runs-on: [self-hosted, gpu]`. GitHub có thể phân job
  cho runner có tập nhãn *bao gồm* nhãn yêu cầu — runner GPU Windows
  (`self-hosted, windows, x64, gcp, gpu`) có thể nhận nhầm job Linux. Đổi job
  hiện có thành `runs-on: [self-hosted, linux, gpu]` (runner Linux đã có nhãn
  `linux`, nên hiện tại không thay đổi kết quả).
- **Job mới `windows-directml`**, dùng
  `runs-on: [self-hosted, windows, gpu]`,
  `AUDIO_SEPARATOR_MODEL_DIR: C:\audio-separator-models`, Python 3.12,
  `poetry install -E dml`. Ban đầu đặt `continue-on-error: true` và chưa
  đưa vào job kiểm soát; sau khi ổn định mới chuyển thành bắt buộc.
- Nội dung job:
  - Xác nhận `--env_info` báo Torch có DirectML và ONNX Runtime có
    `DmlExecutionProvider`.
  - Ma trận các kiến trúc hỗ trợ DML, bật `use_directml=True`: MDX
    (`UVR-MDX-NET-Inst_HQ_3.onnx`) và VR (`5_HP-Karaoke-UVR.pth`) làm
    kiểm thử hồi quy cho các đường vốn đã chạy được; BSRoformer
    (`model_bs_roformer_ep_317_sdr_12.9755.ckpt` — model chính xác từ issue)
    và một MelBandRoformer để bổ sung kiểm thử mới.
  - **Xác nhận đã nạp phần triển khai MỚI** (không có log “Fell back to
    legacy” hoặc kiểm tra `ModelLoadingResult`); nếu không, lỗi
    `map_location` có thể âm thầm tái xuất hiện trong khi job vẫn “đạt” nhờ
    fallback.
  - **Kiểm tra chất lượng, không chỉ kiểm tra không crash**: tách cùng fixture
    trên CPU và DML trong một job; xác nhận (a) độ tương quan / độ giống kiểu
    SDR với đầu ra CPU, (b) các chỉ số hữu hạn (không NaN/Inf), và (c) ngưỡng
    năng lượng RMS/peak tối thiểu rõ ràng trên đầu ra DML — đầu ra im lặng hoặc
    gần im lặng phải bị đánh trượt kể cả khi chỉ số tương đồng suy biến.
    Tái sử dụng/mở rộng helper trong `test_roformer_audio_quality.py`.
- Lưu ý: T4/NVIDIA xác minh đường code DirectML (DX12), là proxy CI phù hợp dù
  người báo lỗi dùng iGPU AMD — việc xác nhận cuối trên AMD cần người báo lỗi
  thử nghiệm (xem bên dưới).

### Kiểm thử đơn vị (mọi nền tảng, miễn phí)

- `RoformerLoader`: `map_location` phải là `'cpu'` khi thiết bị là
  `privateuseone:*`; với `cpu`/`cuda:0`/`mps` thì giữ nguyên giá trị
  `device` (mock `torch.load`, xác minh tham số gọi).
- Bảng giá trị kiểm thử cho `is_dml_device()`.
- Kiểm tra điều kiện ở lượt forward: dùng thiết bị giả để xác nhận nhánh DML
  chuyển phép toán phức sang CPU, còn nhánh MPS/CUDA/CPU không đổi (kiểm thử
  cấu trúc quanh helper; không thể kiểm thử tensor DML thực trên máy không phải
  Windows).
- Kiểm thử hồi quy: MPS chỉ chuyển sang CPU ở bước istft.

## Trình tự phát hành / PR

Thay đổi qua hai repo: PR hạ tầng vào **karaoke-gen** (bộ điều phối + tạo
image), PR code/workflow vào **python-audio-separator**.

1. **PR 1 (audio-separator) — job kiểm thử tích hợp Windows CPU** (chỉ CI,
   không đổi code). Baseline xanh xác nhận E2E Windows trước khi thay đổi hành
   vi. Thêm cả sửa nhãn `runs-on: [self-hosted, linux, gpu]` cho ba job hiện
   có vào PR này (hiện là thay đổi an toàn không đổi hành vi, nhưng cần thiết
   trước khi runner Windows tồn tại).
2. **PR 2 (karaoke-gen) — hạ tầng runner Windows**: thêm họ `gpu-windows`
   vào `ephemeral.py` (+ `test_ephemeral.py`), script khởi động PowerShell,
   `runner-image-provision.ps1`, biến thể trong `build-runner-images.yml`.
   Sau đó chạy thủ công workflow tạo image đầu tiên
   `gha-runner-gpu-windows` và xác minh một job thử chạy được. (Nhớ chạy
   `pulumi up` cục bộ trước khi merge theo quy ước karaoke-gen nếu có tài
   nguyên do Pulumi quản lý bị đổi — function điều phối sẽ được triển khai
   lại.)
3. **PR 3 (audio-separator) — sửa loader `map_location`** + kiểm thử đơn vị +
   job `windows-directml` đặt `continue-on-error`. Từ đây nhận phản hồi DML
   thực sau mỗi lần push.
4. **PR 4 (audio-separator) — chuyển phép toán phức sang CPU** trong cả hai
   model Roformer (+ fallback attention nếu lần chạy DML phát hiện lỗi SDPA) +
   kiểm thử đơn vị.
5. **PR 5 (audio-separator) — chuyển thành job bắt buộc**: thêm
   `windows-directml` (và `windows-cpu-integration`) vào job kiểm soát và
   ruleset 529535; cập nhật bảng tương thích DirectML trong README
   (RoFormer ✅, Demucs ❌ kèm lý do) và cập nhật OldDocs/CI-GPU-RUNNERS.md cho
   họ Windows.
6. **Xác nhận từ cộng đồng**: bình luận trong #292, cung cấp nhánh hoặc wheel
   pre-release và nhờ Vageesha-Gupta chạy lại ma trận trên iGPU AMD; kết quả
   của họ sẽ là xác nhận AMD mà CI NVIDIA không thể thay thế.

## Lưới an toàn hồi quy (vì sao nền tảng khác không bị ảnh hưởng)

- Mọi thay đổi hành vi đều nằm sau điều kiện
  `device.type == "privateuseone"`, chỉ truy cập được khi
  `use_directml=True` **và** đã cài torch_directml (extra tùy chọn, chỉ dành
  cho Windows).
- Bộ kiểm thử tích hợp GPU Linux hiện có (3 job, CUDA) phải tiếp tục đạt — bộ
  này bao phủ các file Roformer đang sửa trên nền tảng chính.
- Kiểm thử đơn vị macOS hiện có cùng các xác nhận dành riêng cho MPS bao phủ
  nhánh MPS.
- Job kiểm thử tích hợp Windows CPU mới bao phủ đường CPU trên Windows.

## Quyết định (Andrew, 2026-07-19)

1. **Hạ tầng runner**: mở rộng nhóm runner tự quản lý dùng một lần hiện có
   (runner_manager và quy trình tạo image trong karaoke-gen) với họ GPU Windows
   — KHÔNG dùng runner lớn do GitHub cung cấp.
2. **Kiểm tra bắt buộc**: sau giai đoạn ổn định với
   `continue-on-error`, các job Windows mới sẽ tham gia nhóm kiểm tra tích hợp
   bắt buộc trước khi merge (ruleset 529535).

## Danh sách cần xác minh lúc triển khai

- Giới hạn phiên bản Python của torch-directml (dự kiến 3.12; chưa có wheel
  3.13 tại thời điểm viết).
- Đường dẫn installer driver GRID trong `gs://nvidia-drivers-us-public` cho
  Windows Server 2022 + T4, và xác minh `dxdiag`/torch_directml nhận thấy bộ
  điều hợp WDDM DX12.
- `model.to("privateuseone:0")` có hoạt động khi truyền chuỗi thuần hay
  không (log đường legacy của người báo lỗi cho thấy có, nhưng vẫn cần xác
  nhận trong job CI DML).
- SDPA có chạy được trên torch-directml không (để quyết định có cần Giai đoạn
  2c).
