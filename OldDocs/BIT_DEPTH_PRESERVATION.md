# Triển khai bảo toàn độ sâu bit

## Tóm tắt

Phần triển khai này giúp file âm thanh đầu ra của audio-separator giữ nguyên độ sâu bit của file đầu vào, tránh giảm chất lượng khi xử lý file âm thanh 24-bit hoặc 32-bit.

## Các thay đổi

### 1. Thêm `soundfile` vào dependencies (`pyproject.toml`)
- Thêm `soundfile >= 0.12` để đọc metadata của file âm thanh.

### 2. Sửa lớp `CommonSeparator` (`audio_separator/separator/common_separator.py`)

#### Thêm theo dõi độ sâu bit
- Thêm thuộc tính `self.input_bit_depth` để lưu độ sâu bit được nhận diện (16, 24 hoặc 32).
- Thêm thuộc tính `self.input_subtype` để lưu subtype của file âm thanh.

#### Sửa phương thức `prepare_mix()`
- Thêm đoạn mã đọc metadata file âm thanh bằng `soundfile.info()` trước khi nạp file bằng librosa.
- Nhận diện và lưu độ sâu bit của file đầu vào dựa trên subtype:
  - PCM_16, PCM_S8 → 16-bit
  - PCM_24 → 24-bit
  - PCM_32, FLOAT, DOUBLE → 32-bit
- Mặc định dùng 16-bit cho mảng numpy hoặc định dạng không xác định.
- Ghi nhật ký độ sâu bit được nhận diện để hỗ trợ gỡ lỗi.

#### Sửa phương thức `write_audio_pydub()`
- Xác định độ sâu bit đầu ra từ `self.input_bit_depth`.
- Điều chỉnh tỷ lệ dữ liệu âm thanh phù hợp với từng độ sâu bit:
  - 16-bit: nhân với 32767, dùng int16, sample_width=2
  - 24-bit: nhân với 8388607, dùng int32, sample_width=3
  - 32-bit: nhân với 2147483647, dùng int32, sample_width=4
- Truyền tham số codec ffmpeg phù hợp cho file WAV:
  - 16-bit: `pcm_s16le`
  - 24-bit: `pcm_s24le`
  - 32-bit: `pcm_s32le`

#### Sửa phương thức `write_audio_soundfile()`
- Xác định subtype đầu ra từ `self.input_subtype` hoặc `self.input_bit_depth`.
- Truyền subtype vào `sf.write()` để giữ nguyên độ sâu bit.
- Bỏ thao tác đan xen kênh thủ công (soundfile tự xử lý âm thanh nhiều kênh).

## Các kiểm thử đã tạo

### Kiểm thử đơn vị

#### `tests/unit/test_bit_depth_detection.py`
Kiểm thử logic nhận diện độ sâu bit:
- `test_16bit_detection`: Xác minh file 16-bit được nhận diện chính xác.
- `test_24bit_detection`: Xác minh file 24-bit được nhận diện chính xác.
- `test_32bit_detection`: Xác minh file 32-bit được nhận diện chính xác.
- `test_numpy_array_input_defaults_to_16bit`: Xác minh mảng numpy mặc định dùng 16-bit.
- `test_bit_depth_preserved_across_multiple_files`: Xác minh độ sâu bit được cập nhật khi xử lý lần lượt nhiều file.

#### `tests/unit/test_bit_depth_writing.py`
Kiểm thử khả năng bảo toàn độ sâu bit trong các hàm ghi file:
- `test_write_16bit_with_pydub`: Kiểm thử đầu ra 16-bit với backend pydub.
- `test_write_24bit_with_pydub`: Kiểm thử đầu ra 24-bit với backend pydub.
- `test_write_32bit_with_pydub`: Kiểm thử đầu ra 32-bit với backend pydub.
- `test_write_24bit_with_soundfile`: Kiểm thử đầu ra 24-bit với backend soundfile.
- `test_write_16bit_with_soundfile`: Kiểm thử đầu ra 16-bit với backend soundfile.

### Kiểm thử tích hợp

#### `tests/integration/test_bit_depth_e2e.py`
Kiểm thử toàn bộ quy trình tách âm thanh:
- `test_e2e_24bit_preservation`: Kiểm thử đầy đủ với đầu vào 24-bit.
- `test_e2e_16bit_preservation`: Kiểm thử đầy đủ với đầu vào 16-bit.

#### `tests/integration/test_bit_depth_preservation.py`
Bộ kiểm thử tích hợp toàn diện (bỏ qua nếu package chưa được cài đặt):
- Kiểm thử bảo toàn 16-bit, 24-bit và 32-bit.
- Kiểm thử với định dạng đầu ra FLAC.
- Kiểm thử với backend soundfile.
- Kiểm thử nhiều file có độ sâu bit khác nhau.

## Kết quả kiểm thử

Tất cả kiểm thử đơn vị đều đạt:
- 5/5 kiểm thử nhận diện độ sâu bit ✅
- 5/5 kiểm thử ghi file ✅
- Tổng cộng 10/10 kiểm thử đơn vị ✅

## Hành vi

### Trước đây
- Tất cả file đầu ra đều được ghi dưới dạng PCM 16-bit, bất kể độ sâu bit của đầu vào.
- Việc này làm giảm chất lượng khi xử lý file âm thanh 24-bit hoặc 32-bit.

### Hiện tại
- Độ sâu bit đầu ra tự động khớp với đầu vào.
- Đầu vào 16-bit → đầu ra 16-bit
- Đầu vào 24-bit → đầu ra 24-bit
- Đầu vào 32-bit → đầu ra 32-bit
- Không giảm chất lượng khi xử lý file âm thanh chất lượng cao.
- Tương thích ngược - đầu vào 16-bit vẫn tạo đầu ra 16-bit.

## Các định dạng được hỗ trợ

Bảo toàn độ sâu bit hoạt động với:
- **File WAV**: Hỗ trợ đầy đủ 16, 24 và 32-bit.
- **File FLAC**: Hỗ trợ đầy đủ 16, 24 và 32-bit.
- **Định dạng khác**: Phụ thuộc vào khả năng hỗ trợ của ffmpeg thông qua pydub.

Cả hai backend đầu ra đều được hỗ trợ:
- **pydub/ffmpeg** (mặc định): Dùng tham số codec để cố định độ sâu bit.
- **soundfile**: Dùng tham số subtype để cố định độ sâu bit.

## Ghi chú

- Tương thích ngược - không cần thay đổi API.
- Độ sâu bit được tự động nhận diện từ file đầu vào.
- Nhật ký giúp theo dõi độ sâu bit được nhận diện và ghi ra.
- Nếu định dạng không xác định hoặc xảy ra lỗi, chương trình chuyển về 16-bit.
- Hoạt động chính xác khi xử lý nhiều file có độ sâu bit khác nhau.
