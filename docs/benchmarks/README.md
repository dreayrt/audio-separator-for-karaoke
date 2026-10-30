# Dữ liệu kiểm chứng karaoke CPU

Các JSON ở đây là kết quả thử nghiệm trên Docker Desktop Linux/WSL2 x86_64 ngày 27/10/2026. Không phải số đo Oracle hoặc dữ liệu đánh giá chất lượng giọng hát.

- cpu-1-thread-20s.json: model thật, một luồng, --network none, ngân sách 2 CPU, hard limit 4.487.905.280 byte.
- http-2-thread-20s.json: gọi ba API thật với hai luồng; kiểm tra xác thực, đồng thời, tham chiếu và điểm.
- http-production-0.2.0.json: kiểm tra lại ba API thật bản 0.2.0, production CPU, trần 35%, hard limit gần 31,5% trên máy dev. Thời gian chịu ảnh hưởng của các build image chạy cùng máy.
- http-dev-gpu-0.2.0.json: ba API thật bản 0.2.0 dev, model chạy CUDA trên RTX 4050 Laptop, trần RAM 30%, hard limit gần 27%. pYIN chấm điểm vẫn chạy CPU. Thời gian chịu ảnh hưởng của build image chạy cùng máy.
- cpu-2-thread-long180.json: đã đạt với tín hiệu 180 giây lặp từ tests/inputs/mardy20s.flac, hai luồng, chia 6 đoạn 30 giây. Dùng kiểm tra tải/bộ nhớ và ghép output; không dùng suy ra chất lượng trên bài hát đầy đủ. Lượt này chạy đồng thời với build image nên thời gian chịu ảnh hưởng của tải máy.

RTF (Real-Time Factor — thời gian xử lý chia thời lượng audio) càng thấp thì suy luận càng nhanh trong cùng điều kiện. Đỉnh cgroup tính bộ nhớ container; RSS (Resident Set Size — số trang bộ nhớ vật lý của tiến trình) cộng nhiều tiến trình có thể đếm lặp trang dùng chung, nên không thay thế số đo cgroup.

Mỗi kết quả ghi phiên bản model/config và các tham số thực tế. So một file với chính nó chỉ kiểm tra tính nhất quán; điểm 100 không chứng minh thang điểm đã được hiệu chỉnh.

Audio gốc/output và khóa gọi API không được sao chép vào thư mục này. Xem [báo cáo triển khai](../BAO_CAO_TRIEN_KHAI_KARAOKE.md) để hiểu giới hạn của kết quả.
