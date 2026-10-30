# Báo cáo triển khai dịch vụ karaoke phiên bản 0.3.0

## Trạng thái hiện tại

**Điều chỉnh kế hoạch 28/10/2026:** người dùng đã bỏ ràng buộc trần RAM 35% cho phương án Google Cloud. Kế hoạch mới không áp trần RAM mặc định; thay đổi mã/launcher/image sẽ thực hiện sau khi duyệt triển khai. Các phần trăm và số đo bên dưới là chính sách/kết quả lịch sử, không phải yêu cầu mới.

**Cập nhật hạ tầng 28/10/2026:** theo báo cáo mới, máy dịch vụ chuyển sang Google Cloud VM `moodify-server` (`136.85.101.19`, 2 vCPU/8 GB RAM/đĩa 35 GB). Kho nhạc gốc trong báo cáo vẫn trỏ Oracle; chưa xác nhận di chuyển file. [Kế hoạch Google Cloud](KE_HOACH_KARAOKE_GOOGLE_CLOUD.md) đang chờ duyệt, karaoke chưa được xác nhận triển khai trên VM mới. Số đo cũ bên dưới không phải benchmark Google Cloud.

Kiến trúc 0.3.0 tách việc chuẩn bị bài hát khỏi API chấm điểm: lệnh local chạy ở foreground để tạo nhạc nền, stem giọng hát và pitch reference; backend tải các file lên kho Oracle, ghi metadata vào MongoDB; FastAPI chỉ chấm điểm sau khi người dùng hát xong. Xem [hướng dẫn local](KARAOKE_LOCAL_PREPARATION.md) và [schema MongoDB đề xuất](KARAOKE_MONGODB_SCHEMA.md).

Ba image 0.3.0 đã được push và xác nhận manifest trong lần phát hành trước; digest được ghi bên dưới. Image score-only và prep CPU hỗ trợ AMD64/ARM64; prep GPU hỗ trợ AMD64. Tag `0.2.0` và `0.2.0-gpu` cũ được giữ nguyên để rollback. Các kết quả phát hành này không xác nhận container đang chạy trên VM Google Cloud.

| Image | Nền tảng | Digest đã xác nhận |
|---|---|---|
| `dreayrt/audio_separator_for_karaoke:0.3.0-score` | `linux/amd64`, `linux/arm64` | `sha256:888e03611b17143ee1a0d5a96502d388b772157a7a1bfef418bb4cef10c0f368` |
| `dreayrt/audio_separator_for_karaoke:0.3.0-prep-cpu` | `linux/amd64`, `linux/arm64` | `sha256:d3ed190a73b63aafef9f73dbd462a0e6c57df108acaeba37738029430e112fc8` |
| `dreayrt/audio_separator_for_karaoke:0.3.0-prep-gpu` | `linux/amd64` | `sha256:34fa3f180a9a66d825395708d807193c980493f85760254ab8a1f0d37a3901e3` |

Phần tiếp theo giữ lại kết quả đo và kiểm chứng của bản **0.2.0** làm tài liệu lịch sử. Các endpoint tách âm, cấu hình dev/production và số đo cũ ở dưới không mô tả kiến trúc 0.3.0 hiện tại.

Ngày cập nhật: 27/10/2026. Phiên bản mã dịch vụ: **0.2.0**. Số đo CPU ban đầu phía dưới thuộc bản 0.1.0; không đổi nhãn chúng thành kết quả GPU hoặc production mới.

Yêu cầu mới đã triển khai: **dev mặc định GPU NVIDIA, tối đa 30% RAM; production CPU, tối đa 35% RAM**. Host production: **http://158.178.247.33**, URL FastAPI mặc định **http://158.178.247.33:8000**; URL không có cổng cần proxy cổng 80 hoặc chọn --port 80. Chưa thực hiện triển khai từ xa lên server này.

## 1. Phạm vi đã thực hiện

Đã xây dựng dịch vụ **FastAPI** (framework Python tạo API — Application Programming Interface, giao diện để phần mềm gọi nhau) trong [services/karaoke](../services/karaoke/). Dịch vụ nhận file, tính toán và trả file hoặc JSON (JavaScript Object Notation — dữ liệu có cấu trúc).

| Chức năng | Kết quả |
|---|---|
| Tách nhạc | POST /v1/separate trả instrumental.wav, vocals.wav và metadata.json trong ZIP |
| Tạo tham chiếu | POST /v1/references tạo cao độ theo thời gian, phiên bản và thông tin chất lượng |
| Chấm sau bài | POST /v1/score trả cao độ, nhịp, mức hoàn thành và điểm tổng thử nghiệm |
| Vận hành | Kiểm tra sống/sẵn sàng, xác thực backend, một tác vụ âm thanh nặng mỗi lượt |
| Đóng gói | Một Dockerfile, hai tag CPU/CUDA, cùng code/model/FFmpeg/config/manifest |
| Dev/production | Dev mặc định CUDA, RAM tối đa 30%; production CPU, RAM tối đa 35%; launcher tự tính theo máy |
| Tích hợp | Client mẫu stream upload/download và hướng dẫn trách nhiệm backend/player |

Không có SQLite hoặc cơ sở dữ liệu khác trong dịch vụ mới. Không quản lý bền vững bài hát, người dùng, phiên hát hay hàng đợi công việc. Backend hiện có quản lý các phần đó, lưu file và điểm.

## 2. Model được đóng gói

| Thuộc tính | Giá trị |
|---|---|
| Hồ sơ xử lý | karaoke-v1 |
| Kiến trúc | MelBand RoFormer, chạy qua adapter MDXC của audio-separator |
| Checkpoint | mel_band_roformer_karaoke_aufr33_viperx_sdr_10.1956.ckpt |
| Tác giả checkpoint được ghi nhận | aufr33/viperx |
| Dung lượng checkpoint | 913.096.801 byte |
| Thiết bị | Production: CPU (Central Processing Unit — bộ xử lý trung tâm); dev: GPU (Graphics Processing Unit — bộ xử lý đồ họa) NVIDIA qua CUDA |
| Âm thanh tách | Stereo 44.100 mẫu/giây |
| Cấu hình đã đo | segment_size=128; overlap=2; batch_size=1; chunk_seconds=30 |
| Số luồng | Đã thử 1 và 2; tùy chỉnh bằng launcher |

Model dùng trọng số đã huấn luyện, không huấn luyện lại. Nó ước lượng phần giọng hát và nhạc nền từ nhạc trộn. **Model này không tự chấm điểm karaoke**. Phần chấm mới dùng pYIN (probabilistic YIN — thuật toán ước lượng cao độ theo xác suất) của librosa và công thức xử lý tín hiệu.

SHA-256 (Secure Hash Algorithm 256-bit — mã kiểm tra nội dung):

```text
checkpoint: 1de20d459332fe8869aeb01327a31df0032262706e1365114e852dc271779813
config:     b35077d94861f068097cce1a5e54633c055e7dcc2613eade4e4dc7c7c9c3f48b
profile 0.1.0: e8e1a111e1f83cce711c09473b6b9dd8dcac287c73f4d5c65a5f1a9977bc5654
```

Profile hash kết hợp hash cấu hình gốc và các tham số xử lý thực tế. Từ bản 0.2.0, hash bao gồm cả device và precision=float32, nên CPU/GPU có config_version khác nhau và cũng khác hash bản 0.1.0. Backend dùng source_hash + model_version + config_version để nhận diện kết quả có thể dùng lại; lấy giá trị hiện hành từ /v1/info.

Build tải model/config và kiểm tra hash cố định; runtime dùng bundle.json nội bộ và không tự tải model mới. Đã chạy suy luận trong container với --network none. Nguồn và thông báo bản quyền phần mềm nằm trong [NOTICE](../services/karaoke/NOTICE.md); không khẳng định trọng số có cùng giấy phép với code.

Segment và overlap hiện tại thấp hơn cấu hình mặc định của checkpoint để giảm chi phí CPU/bộ nhớ. Chất lượng tách ở cấu hình này cần được nghe thử trên kho nhạc sử dụng thực tế; không lấy con số 10.1956 trong tên file làm kết quả benchmark mới.

## 3. Chính sách RAM theo môi trường

RAM (Random Access Memory — bộ nhớ truy cập ngẫu nhiên) được giới hạn cho **toàn bộ container**, gồm Python, model, bộ đệm và tiến trình con.

Launcher đọc RAM Docker Engine ngay trên máy chạy và tính:

```text
dev:        trần = RAM Docker Engine × 30%; hard limit mặc định gần 27%
production: trần = RAM Docker Engine × 35%; hard limit mặc định gần 31,5%
hard limit mặc định = làm tròn xuống MiB(RAM Docker Engine × trần phần trăm × 90%)
```

MiB là mebibyte, GiB là gibibyte, đều theo cơ số 2. Hard limit — giới hạn cứng — chừa 10% phần ngân sách làm đệm dưới trần của môi trường. Có thể cấp cụ thể bằng --memory-mib tới trần; không cấp vượt trần qua launcher.

--memory và --memory-swap bằng nhau nên không cấp thêm swap. Ứng dụng kiểm tra giới hạn cgroup — cơ chế quản lý tài nguyên container của hệ điều hành — lúc khởi động; không cho chạy không giới hạn trong dev/production. Nếu các môi trường dùng chung máy, launcher kiểm tra tổng mức cấp theo trần chặt hơn trong các container karaoke do nó quản lý; có dev thì tổng không vượt 30%.

| Máy dev đã đo | Giá trị |
|---|---:|
| RAM Docker Engine báo | 16.625.385.472 byte |
| Hard limit container | 4.487.905.280 byte, khoảng 4,18 GiB |
| Tỷ lệ cấp | 26,994% |
| Ngân sách thời gian CPU | 2 CPU |
| Luồng suy luận đã thử | 1 và 2 |

Không gắn cứng mức 4,18 GiB vào launcher hoặc cấu hình production. Với máy báo 24 GB, production mặc định cấp gần 7,56 GB, dưới trần 8,40 GB (35%). Dung lượng thực tế được tính từ Docker Engine trên máy đó. Dev GPU vẫn giữ trần RAM 30%; VRAM (Video Random Access Memory — bộ nhớ GPU) là tài nguyên khác, đặt ngân sách allocator PyTorch mặc định 85%, không coi đó là hard limit toàn bộ GPU.

## 4. Kết quả đo CPU với model thật

Đo trên **Docker Desktop Linux/WSL2, x86_64**, không phải server Oracle. Máy Docker báo 12 CPU; container được giới hạn ngân sách 2 CPU. Không suy ra tốc độ của Oracle từ những số này.

| Bài đo | Thời lượng âm thanh | Thời gian xử lý | Bộ nhớ đỉnh |
|---|---:|---:|---:|
| Tách âm, 1 luồng, chặn mạng | 20,006 giây | 220,075 giây; nạp model 6,764 giây | cgroup: 2.127.622.144 byte, khoảng 1,98 GiB |
| HTTP đầu cuối, 2 luồng | 20,006 giây | 148,717 giây từ client | cgroup cao nhất trong lượt chạy: 2.160.107.520 byte, khoảng 2,01 GiB |
| Tạo tham chiếu từ giọng đã tách | Khoảng 20 giây | 7,038 giây | Chung container HTTP trên |
| So chính giọng tham chiếu với nó | Khoảng 20 giây | 3,389 giây | Chung container HTTP trên |
| Âm thanh dài, 2 luồng, chia 6 đoạn | 180 giây | 1.413,635 giây, khoảng 23 phút 34 giây; nạp model 8,249 giây | cgroup: 2.159.636.480 byte, khoảng 2,01 GiB |

RTF (Real-Time Factor — thời gian xử lý chia thời lượng âm thanh) của bài đo 1 luồng là **11,0**: cần khoảng 11 giây tính cho một giây audio trong phép đo đó. Thời gian HTTP có thêm truyền file/đóng ZIP; các lượt đo không phải thí nghiệm so sánh tốc độ hoàn toàn cô lập.

**Hệ quả:** hiện chưa đáp ứng việc tách bài mới ngay khi bấm phát với độ trễ thấp. Backend nên chuẩn bị nhạc trước, lưu lại hai stem — các phần âm thanh đã tách — và tham chiếu, rồi phát lại từ kho hiện có. Nhiều người phát bài đã chuẩn bị không cần chạy model tách âm lại cho từng người.

Kiểm thử âm thanh dài 180 giây đã **đạt**, trả đủ hai stem đúng timeline sau khi ghép 6 đoạn; RTF 7,854. Mẫu lặp từ đoạn nhạc thử, phục vụ kiểm tra chia đoạn/bộ nhớ, không thay thế đánh giá chất lượng trên một bài đầy đủ của sản phẩm. Lượt đo chạy đồng thời với build image trên máy dev nên thời gian chịu ảnh hưởng của tải máy; hard limit vẫn 4,18 GiB và không tăng ngân sách.

### 4.1. Kiểm chứng bản 0.2.0 theo môi trường mới

| Thuộc tính | Production CPU, thử cục bộ | Dev GPU NVIDIA RTX 4050 Laptop |
|---|---:|---:|
| Thời lượng mẫu | 20,006 giây | 20,006 giây |
| Tách và trả ZIP qua HTTP | 193,429 giây | 26,806 giây |
| Tạo tham chiếu | 15,371 giây | 8,295 giây |
| Chấm tự so sánh | 4,592 giây | 3,177 giây |
| Trần RAM theo môi trường | 35% | 30% |
| Hard limit | 5.236.588.544 byte, 31,498% | 4.487.905.280 byte, 26,994% |
| Đỉnh RAM cgroup | 2.141.683.712 byte | 2.157.641.728 byte |
| Thiết bị model do API xác nhận | cpu | cuda, NVIDIA GeForce RTX 4050 Laptop GPU |
| Độ chính xác tính toán | float32 | float32 |
| Số luồng CPU đã đặt | 2 | 2 |

Cả hai lượt đều đạt **12 kiểm tra HTTP**, điểm tự so sánh 100, im lặng 0. Không ghi nhận sự kiện chạm trần RAM hoặc bị dừng do thiếu RAM. Các build image chạy cùng máy trong lúc đo, nên đây không phải phép so sánh hiệu năng cô lập hoặc cam kết độ trễ trên Oracle.

Dev GPU chỉ chuyển phần model tách âm sang GPU; FFmpeg và bộ chấm pYIN vẫn dùng CPU. Phép đo không chứng minh có thể tách trực tiếp đồng thời với phát nhạc. Model và điểm thử nghiệm vẫn có các giới hạn chất lượng đã nêu.

Config version 0.2.0 đã đo:

```text
CPU:  b89ece526e40bc7eec9d99aa16ecf35b149fb06dd18457802fba1caeea536c58
CUDA: c2b879edca7e513a20fcc1ce73cc873066b0c63945a4bd7a02f5ac276221521a
```

Kết quả thô: [production CPU](benchmarks/http-production-0.2.0.json), [dev CUDA](benchmarks/http-dev-gpu-0.2.0.json).

## 5. Kiểm thử đã đạt

**45 kiểm thử tự động đạt** sau khi bổ sung cấu hình GPU/35%, gồm:

- Xác thực, hợp đồng API, file ZIP và dọn thư mục tạm.
- Giới hạn tổng request, kể cả body truyền từng phần; từ chối dữ liệu quá lớn.
- Một tác vụ nặng mỗi lượt; yêu cầu khác nhận 503 và có thể thử lại từ backend.
- Khi client ngắt kết nối, tiếp tục giữ lượt xử lý và file đến khi CPU thật sự tính xong.
- Hash/phiên bản/schema tham chiếu, giá trị không hợp lệ và metadata thời gian.
- Hát đúng/sai nốt, sai thời gian, thiếu đoạn, im lặng, lệch quãng tám; trích cao độ thật từ tín hiệu kiểm thử.
- Chính sách RAM dev 30%/production 35%, kiểm tra tổng mức cấp khi dùng chung máy và giữ lại khóa riêng khi chạy lại launcher.
- Chọn đúng thiết bị/tag/--gpus, dev có thể chọn CPU; production từ chối CUDA dù máy có GPU; thiếu CUDA báo lỗi rõ ràng.

**12 kiểm tra HTTP với model thật bản 0.1.0 đạt**: sẵn sàng, xác thực, CPU, hard limit, nhận ZIP theo luồng, hash hai stem, từ chối xử lý đồng thời, health vẫn trả trong lúc suy luận, tạo tham chiếu, API chấm điểm, tự so sánh và im lặng.

So cùng một file được **100**, bản thu im lặng được **0**. Đây là kiểm tra tính nhất quán và tránh thưởng cho im lặng, **không phải độ chính xác chấm giọng hát**. Chưa có tập bản thu người hát thật đã gán nhãn để hiệu chỉnh thang điểm.

Kiểm tra giải mã thực tế thêm: WAV, FLAC, MP3, OGG, M4A và WebM đều đạt; định dạng playlist concat bị từ chối. Phép thử này chạy không cần nạp model trong container riêng có giới hạn 256 MiB.

Bản **0.2.0 production** đã vượt qua lại đủ 12 kiểm tra HTTP với model thật, trong container CPU được cấp **5.236.588.544 byte**, bằng **31,498%** RAM Docker Engine trên máy thử, dưới trần 35%. Đỉnh cgroup **2.141.683.712 byte**, khoảng 1,99 GiB. Tách mẫu 20,006 giây mất 193,429 giây; tham chiếu 15,371 giây; chấm tự so sánh 4,592 giây. Lượt chạy đồng thời với build image, không phải số đo Oracle. Model giữ file chỉ đọc đối với tài khoản chạy dịch vụ. Kết quả: [http-production-0.2.0.json](benchmarks/http-production-0.2.0.json).

Kết quả thô nằm ở [docs/benchmarks](benchmarks/). Audio đầu ra và file khóa riêng không được đưa vào Git hoặc Docker image.

## 6. Image và nền tảng

Repository do người dùng chỉ định: **dreayrt/audio_separator_for_karaoke**. Tag mới: **0.2.0** cho CPU và **0.2.0-gpu** cho dev CUDA. Hai biến thể dùng chung một Dockerfile, không phải hai dịch vụ hoặc hai máy chủ.

Tag CPU cũ **0.1.0** đã push thành công cho linux/amd64 và linux/arm64; digest: sha256:c0487b9b98b9a0f1fac7759922245f65a92dc9f0990c7bf27e3885dacde9824b. Bản cũ có chính sách CPU/30%, không dùng nó để kỳ vọng cấu hình mới.

Bản CPU **0.2.0 đã push và kiểm tra manifest trực tiếp từ Docker Hub thành công**, hỗ trợ linux/amd64 và linux/arm64. Digest:

```text
sha256:f8831a8b2ba10b3bbf96b6d4f8efff3236fa3601ff5b48df16f6847bf5479a13
```

Bản **0.2.0-gpu đã push và kiểm tra manifest trực tiếp từ Docker Hub thành công**, hỗ trợ linux/amd64. Digest:

```text
sha256:f21ee4a8cbbbfd400e61823f05f626b3adaa3bb3d1d29c919dfbb73c23e9cbcf
```

Bản GPU đã chạy đủ API với model thật trên **NVIDIA GeForce RTX 4050 Laptop GPU, 6141 MiB**. Bản CPU đã kiểm thử model thật trên amd64; build/import Arm qua giả lập không thay thế benchmark trên Oracle Arm thực tế.

Cả hai tag đều có trong [repository Docker Hub](https://hub.docker.com/r/dreayrt/audio_separator_for_karaoke/tags). Có thể pin image bằng digest tương ứng để giữ đúng nội dung đã xác nhận. Dev GPU hiện chạy cục bộ ở http://127.0.0.1:18000/docs, container karaoke-ai-dev, trạng thái healthy và hard limit 4.487.905.280 byte; không cấp thêm swap. Container kiểm thử production cục bộ đã dọn sau kiểm thử. Chưa chạy container trên Oracle.

Đã khai báo host production theo yêu cầu; URL có thể ghi đè bằng --url/KARAOKE_API_URL trong client. --image, --env, --env-file, --bind và --port dùng để chạy theo từng môi trường. Python launcher trên host chỉ cần thư viện chuẩn; model và thư viện AI nằm trong container.

## 7. Những phần còn phụ thuộc hệ thống của bạn

| Phần | Nội dung cần thực hiện ở hệ thống thực tế |
|---|---|
| Oracle | Pull/run image, xác nhận CPU/kiến trúc, đo tốc độ và ảnh hưởng lên backend trên máy đó |
| Backend | Gọi API từ tác vụ nền, quản lý trạng thái/chống trùng/retry, lưu output/tham chiếu/điểm |
| Player | Lấy nhạc và lời có thời gian, thu giọng riêng, ghi đúng mốc bắt đầu và độ trễ |
| Lời bài hát | Cần nguồn lời đã có thời gian đúng bản phối; tách âm không tự sinh lời dạng chữ |
| Chất lượng | Nghe thử nhạc nền/giọng tham chiếu trên kho nhạc mục tiêu |
| Điểm sản phẩm | Thu thập bản thu chuẩn/sai có người đánh giá, hiệu chỉnh công thức và ngưỡng |

Repo này không có quyền truy cập server Oracle hoặc toàn bộ backend/frontend đang dùng, nên chưa triển khai trực tiếp các phần đó. Dịch vụ và client mẫu đã sẵn để tích hợp theo [hướng dẫn sử dụng](HUONG_DAN_TICH_HOP_KARAOKE.md).

Phiên bản đầu chấm một giọng trên timeline gốc. Chưa hỗ trợ chấm trực tiếp khi hát, tua/đổi tông/đổi tốc độ, song ca hoặc đánh giá phát âm/cảm xúc. Module chấm có phiên bản **pitch-rhythm-v1-experimental** để backend không nhầm với thang điểm đã kiểm chứng.
