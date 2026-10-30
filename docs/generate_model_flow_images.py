"""Generate Vietnamese PNG flow diagrams for the model documentation.

Run from the repository root with Pillow installed:
    python docs/generate_model_flow_images.py
"""

from pathlib import Path
from PIL import Image, ImageDraw, ImageFont


ROOT = Path(__file__).resolve().parent
OUT = ROOT / "images"
W, H = 1800, 1040
BG = "#F3F7FB"
INK = "#15334B"
MUTED = "#536B7F"
WHITE = "#FFFFFF"
PALE = "#E9F3FA"
COLORS = ["#168AAD", "#3979C6", "#745AC8", "#D87824", "#25917A", "#36566F"]
FONT_REGULAR = r"C:\Windows\Fonts\segoeui.ttf"
FONT_BOLD = r"C:\Windows\Fonts\segoeuib.ttf"


def font(size: int, bold: bool = False):
    return ImageFont.truetype(FONT_BOLD if bold else FONT_REGULAR, size)


def wrap(draw, text: str, fnt, max_width: int):
    lines = []
    for paragraph in text.split("\n"):
        words = paragraph.split()
        if not words:
            lines.append("")
            continue
        line = words[0]
        for word in words[1:]:
            candidate = f"{line} {word}"
            if draw.textbbox((0, 0), candidate, font=fnt)[2] <= max_width:
                line = candidate
            else:
                lines.append(line)
                line = word
        lines.append(line)
    return lines


def draw_centered(draw, text, x, y, width, fnt, fill, line_gap=7):
    lines = wrap(draw, text, fnt, width)
    heights = [draw.textbbox((0, 0), line or "Ag", font=fnt)[3] for line in lines]
    total = sum(heights) + line_gap * max(0, len(lines) - 1)
    cy = y - total / 2
    for line, line_height in zip(lines, heights):
        box = draw.textbbox((0, 0), line, font=fnt)
        line_width = box[2] - box[0]
        draw.text((x + (width - line_width) / 2, cy), line, font=fnt, fill=fill)
        cy += line_height + line_gap


def arrow(draw, x1, y, x2, color=INK, width=6):
    draw.line((x1, y, x2 - 15, y), fill=color, width=width)
    draw.polygon([(x2 - 17, y - 11), (x2, y), (x2 - 17, y + 11)], fill=color)


def header(draw, title, subtitle, badge):
    draw.rectangle((0, 0, W, 16), fill=INK)
    draw.rounded_rectangle((62, 42, 335, 84), radius=20, fill="#DDECF6")
    draw.text((84, 49), badge.upper(), font=font(19, True), fill=INK)
    draw.text((62, 103), title, font=font(43, True), fill=INK)
    draw.text((66, 164), subtitle, font=font(22), fill=MUTED)
    draw.line((62, 217, W - 62, 217), fill="#D5E1EA", width=2)


def node(draw, rect, number, title, body, color):
    x1, y1, x2, y2 = rect
    draw.rounded_rectangle(rect, radius=24, fill=WHITE, outline="#D5E1EA", width=3)
    draw.rounded_rectangle((x1 + 2, y1 + 2, x2 - 2, y1 + 12), radius=5, fill=color)
    draw.ellipse((x1 + 18, y1 + 22, x1 + 57, y1 + 61), fill=color)
    number_text = str(number)
    bb = draw.textbbox((0, 0), number_text, font=font(20, True))
    draw.text((x1 + 37.5 - (bb[2] - bb[0]) / 2, y1 + 29), number_text, font=font(20, True), fill=WHITE)
    title_lines = wrap(draw, title, font(25, True), x2 - x1 - 30)
    title_y = y1 + 83
    for line in title_lines:
        bb = draw.textbbox((0, 0), line, font=font(25, True))
        tw = bb[2] - bb[0]
        draw.text((x1 + (x2 - x1 - tw) / 2, title_y), line, font=font(25, True), fill=INK)
        title_y += bb[3] - bb[1] + 4
    body_top = max(title_y + 12, y1 + 160)
    draw_centered(draw, body, x1 + 17, (body_top + y2 - 22) / 2, x2 - x1 - 34, font(20), MUTED, line_gap=7)


def footer(draw, title, text, y=725, height=210):
    draw.rounded_rectangle((62, y, W - 62, y + height), radius=24, fill=PALE)
    draw.text((88, y + 25), title, font=font(24, True), fill=INK)
    lines = wrap(draw, text, font(21), W - 190)
    ty = y + 71
    for line in lines:
        draw.text((89, ty), line, font=font(21), fill=MUTED)
        ty += 32
    draw.text((64, H - 42), "Sơ đồ giải thích luồng suy luận ở mức khái quát; cấu hình chi tiết phụ thuộc checkpoint.", font=font(17), fill=MUTED)


def flow_png(filename, title, subtitle, nodes, note, badge="LUỒNG MODEL"):
    image = Image.new("RGB", (W, H), BG)
    draw = ImageDraw.Draw(image)
    header(draw, title, subtitle, badge)
    count = len(nodes)
    margin = 60
    box_w = 240
    gap = (W - 2 * margin - count * box_w) // (count - 1)
    y1, y2 = 315, 650
    for i, item in enumerate(nodes):
        x = margin + i * (box_w + gap)
        node(draw, (x, y1, x + box_w, y2), i + 1, item[0], item[1], item[2] if len(item) > 2 else COLORS[i % len(COLORS)])
        if i < count - 1:
            arrow(draw, x + box_w + 7, (y1 + y2) // 2, x + box_w + gap - 7)
    footer(draw, "Đọc sơ đồ", note)
    image.save(OUT / filename, format="PNG", optimize=True)


def training_png():
    image = Image.new("RGB", (W, 1320), BG)
    draw = ImageDraw.Draw(image)
    header(draw, "Model học ra sao và project chạy thế nào?", "Huấn luyện tạo checkpoint; project dùng checkpoint đó để tách file mới.", "HUẤN LUYỆN VS SUY LUẬN")

    draw.rounded_rectangle((62, 250, W - 62, 298), radius=22, fill="#E8E2FA")
    draw.text((88, 260), "A. HUẤN LUYỆN MODEL  •  diễn ra trước, thường do tác giả checkpoint thực hiện", font=font(21, True), fill="#5946A5")
    training_nodes = [
        ("Bản phối + stem chuẩn", "Ví dụ: bản phối gốc và các stem giọng, trống, bass."),
        ("Model dự đoán", "Mạng thử ước lượng stem từ bản phối."),
        ("Tính sai số", "So dự đoán với stem chuẩn bằng loss."),
        ("Cập nhật trọng số", "Lặp lại nhiều lượt để giảm sai số."),
        ("Lưu checkpoint", "Trọng số đã học được lưu thành file model."),
    ]
    x0, box_w, gap, y1, y2 = 63, 300, 30, 340, 600
    for i, (t, b) in enumerate(training_nodes):
        x = x0 + i * (box_w + gap)
        node(draw, (x, y1, x + box_w, y2), i + 1, t, b, ["#745AC8", "#745AC8", "#D87824", "#D87824", "#25917A"][i])
        if i < len(training_nodes) - 1:
            arrow(draw, x + box_w + 5, (y1 + y2) // 2, x + box_w + gap - 5)

    draw.rounded_rectangle((62, 685, W - 62, 733), radius=22, fill="#DDEEF7")
    draw.text((88, 695), "B. SUY LUẬN  •  đây là luồng chính trong python-audio-separator", font=font(21, True), fill=INK)
    inference_nodes = [
        ("Nạp model", "Đọc checkpoint và config đã có."),
        ("Đưa audio mới vào", "Chuẩn bị và chia đoạn theo model."),
        ("Chạy inference", "Model ước lượng stem; không tự học lại."),
        ("Xuất các stem", "Chuẩn hóa và ghi file đầu ra."),
    ]
    x0, box_w, gap, y1, y2 = 110, 360, 50, 775, 1035
    for i, (t, b) in enumerate(inference_nodes):
        x = x0 + i * (box_w + gap)
        node(draw, (x, y1, x + box_w, y2), i + 1, t, b, ["#168AAD", "#3979C6", "#3979C6", "#25917A"][i])
        if i < len(inference_nodes) - 1:
            arrow(draw, x + box_w + 5, (y1 + y2) // 2, x + box_w + gap - 5)

    draw.rounded_rectangle((62, 1090, W - 62, 1235), radius=22, fill="#FFF1E3")
    note = "Repo không có dữ liệu/lịch sử huấn luyện đầy đủ cho từng checkpoint. Dataset, loss và số epoch tùy tác giả; tên file không đủ để khẳng định các chi tiết đó."
    for i, line in enumerate(wrap(draw, note, font(20), W - 190)):
        draw.text((88, 1120 + i * 31), line, font=font(20), fill="#76502C")
    image.save(OUT / "flow-huan-luyen-va-suy-luan.png", format="PNG", optimize=True)


def mdxc_branches_png():
    image = Image.new("RGB", (W, 1300), BG)
    draw = ImageDraw.Draw(image)
    header(draw, "MDXC: cùng adapter, hai nhánh model", "Code chọn nhánh dựa trên loại checkpoint/config đã nạp.", "MDXC • MODEL ROUTER")
    top_nodes = [
        ("Audio + config", "Đọc waveform và cấu hình model."),
        ("Chia thành chunk", "Độ dài và overlap theo config."),
        ("Kiểm tra họ model", "RoFormer hay TFC-TDF/MDX23C?"),
    ]
    x0, box_w, gap, y1, y2 = 63, 500, 75, 285, 500
    for i, (t, b) in enumerate(top_nodes):
        x = x0 + i * (box_w + gap)
        node(draw, (x, y1, x + box_w, y2), i + 1, t, b, ["#168AAD", "#3979C6", "#745AC8"][i])
        if i < len(top_nodes) - 1:
            arrow(draw, x + box_w + 7, (y1 + y2) // 2, x + box_w + gap - 7)

    # Two branch panels
    draw.rounded_rectangle((62, 560, 875, 1015), radius=26, fill=WHITE, outline="#B9D6EA", width=3)
    draw.rounded_rectangle((925, 560, W - 62, 1015), radius=26, fill=WHITE, outline="#D7C8F1", width=3)
    draw.rounded_rectangle((88, 580, 480, 626), radius=20, fill="#DDEEF7")
    draw.text((108, 589), "NHÁNH A • RoFormer", font=font(20, True), fill=INK)
    draw.rounded_rectangle((950, 580, 1470, 626), radius=20, fill="#E8E2FA")
    draw.text((970, 589), "NHÁNH B • TFC-TDF / MDX23C", font=font(20, True), fill="#5946A5")

    left_nodes = [
        ("STFT", "Đưa audio sang phổ thời gian–tần số."),
        ("Band split + attention", "Chia dải rồi học quan hệ thời gian/tần số."),
        ("Mask → ISTFT", "Ước lượng stem, áp mask và dựng waveform."),
    ]
    right_nodes = [
        ("STFT + đặc trưng", "Chuẩn bị phổ theo YAML của model."),
        ("Mạng TFC-TDF", "Chạy mạng convolution/linear theo cấu hình."),
        ("ISTFT + stem", "Dựng waveform và ánh xạ stem đầu ra."),
    ]
    for j, panel_nodes in enumerate((left_nodes, right_nodes)):
        sx = 86 if j == 0 else 949
        col = ["#168AAD", "#3979C6", "#25917A"] if j == 0 else ["#745AC8", "#D87824", "#25917A"]
        w = 220
        g = 34
        for i, (t, b) in enumerate(panel_nodes):
            x = sx + i * (w + g)
            node(draw, (x, 690, x + w, 930), i + 1, t, b, col[i])
            if i < len(panel_nodes) - 1:
                arrow(draw, x + w + 5, 810, x + w + g - 5)

    draw.rounded_rectangle((62, 1060, W - 62, 1215), radius=24, fill=PALE)
    note = "MDXC là lớp điều phối chung. Nhánh RoFormer dùng STFT, band split và attention; nhánh MDX23C trong code nạp mạng TFC-TDF. TFC-TDF là tên lớp trong code, tài liệu repo không khai triển chữ viết tắt này."
    for i, line in enumerate(wrap(draw, note, font(20), W - 190)):
        draw.text((88, 1090 + i * 31), line, font=font(20), fill=MUTED)
    image.save(OUT / "flow-mdxc-hai-nhanh.png", format="PNG", optimize=True)


def main():
    OUT.mkdir(parents=True, exist_ok=True)

    flow_png(
        "flow-tong-quat.png",
        "Luồng chung khi tách âm thanh",
        "Tất cả model đi qua các bước chung, sau đó được chuyển tới adapter riêng theo kiến trúc.",
        [
            ("Audio đầu vào", "File âm thanh, danh sách file hoặc thư mục."),
            ("Đọc & chuẩn bị", "Giải mã, kiểm tra, chọn kênh và sample rate."),
            ("Nạp model", "Checkpoint + config; tải về nếu chưa có cache."),
            ("Chia đoạn", "Segment/chunk theo giới hạn của model và input."),
            ("Model suy luận", "Chọn MDX, VR, Demucs hoặc MDXC; ensemble nếu yêu cầu."),
            ("Ghi các stem", "Dựng waveform, chuẩn hóa rồi xuất từng file."),
        ],
        "Model đã được huấn luyện từ trước. Khi chạy, project nạp checkpoint rồi ước lượng stem cho input mới; ensemble chỉ bật khi người dùng chọn nhiều model/preset.",
        "TOÀN HỆ THỐNG",
    )

    flow_png(
        "flow-mdx.png",
        "MDX: suy luận trên phổ bằng ONNX",
        "Luồng adapter MDX trong repository: STFT → model ONNX → inverse STFT.",
        [
            ("Audio + chuẩn bị", "Đọc input, chuẩn hóa và tạo stereo nếu cần."),
            ("STFT", "Chuyển waveform thành các khung phổ."),
            ("Segment", "Đệm biên, chia đoạn và chồng lấp theo config."),
            ("Model ONNX", "Dự đoán phổ của stem mục tiêu."),
            ("Inverse STFT", "Dựng dự đoán phổ về waveform."),
            ("Stem + export", "Xuất stem đích và phần còn lại theo cấu hình."),
        ],
        "ONNX = Open Neural Network Exchange (định dạng mở biểu diễn model). Một số model tạo stem phụ bằng residual hoặc phép đảo phổ; cách cụ thể phụ thuộc checkpoint và tùy chọn.",
        "HỌ MDX",
    )

    flow_png(
        "flow-vr.png",
        "VR: chia phổ thành các dải rồi dự đoán mask",
        "VR (Vocal Remover) chạy mạng UVR trên các cửa sổ đặc trưng phổ.",
        [
            ("Audio + model params", "Đọc sample rate và tham số band của model."),
            ("Nhiều dải tần", "Tạo phổ ở các band/tần số tương ứng."),
            ("Cửa sổ phổ", "Cắt spectrogram thành các patch nhỏ."),
            ("Mạng VR", "Mạng dự đoán mask cho từng vùng phổ."),
            ("Áp mask", "Tách phổ mục tiêu và phần bù, giữ pha."),
            ("Dựng & xuất", "Đổi phổ về waveform rồi lưu stem."),
        ],
        "Mask là hệ số giữ/giảm từng vùng tần số. Cấu hình aggression, TTA và hậu xử lý (nếu bật) có thể thay đổi kết quả và thời gian chạy.",
        "HỌ VR",
    )

    flow_png(
        "flow-demucs.png",
        "Demucs: dự đoán nhiều stem cùng lượt",
        "Sơ đồ khái quát cho các model HTDemucs/Hybrid Demucs được dùng trong repo.",
        [
            ("Waveform input", "Audio gốc được chuẩn bị thành tensor."),
            ("Chuẩn hóa + segment", "Chia đoạn; có thể áp dụng shifts/overlap."),
            ("Hybrid encoder", "HTDemucs phân tích waveform và đặc trưng phổ."),
            ("Transformer/decoder", "Kết hợp thông tin để ước lượng từng nguồn."),
            ("Nhiều nguồn", "Model tạo vocals, drums, bass, other... cùng lượt."),
            ("Ghép & đặt tên", "Ghép segment rồi map ra stem theo config."),
        ],
        "Số stem do model config quyết định. Ví dụ model 4 stem thường có vocals/drums/bass/other; htdemucs_6s có thêm guitar và piano.",
        "HỌ DEMUCS",
    )

    flow_png(
        "flow-roformer.png",
        "RoFormer: attention trên dải tần và thời gian",
        "Nhánh RoFormer trong adapter MDXC; BS-RoFormer và MelBand RoFormer có cách chia dải khác nhau.",
        [
            ("Waveform + config", "Nạp checkpoint, sample rate và thông số STFT."),
            ("STFT", "Chuyển audio sang phổ phức theo thời gian."),
            ("Chia band", "Tổ chức phổ thành các dải đặc trưng."),
            ("Attention", "Học quan hệ giữa thời điểm và vùng tần số."),
            ("Ước lượng mask", "Tạo dự đoán cho một hoặc nhiều stem."),
            ("ISTFT + export", "Áp mask lên phổ, dựng waveform và ghi file."),
        ],
        "RoFormer = Rotary Position Embedding Transformer. Đây là luồng riêng cho checkpoint RoFormer; adapter MDXC còn có nhánh TFC-TDF/MDX23C với cấu trúc khác.",
        "MDXC • ROFORMER",
    )

    flow_png(
        "flow-mdx23c.png",
        "MDX23C: mạng phổ TFC-TDF trong adapter MDXC",
        "Checkpoint MDX23C dùng cấu hình YAML và mạng TFC-TDF; đây không phải nhánh RoFormer.",
        [
            ("Audio + YAML", "Đọc input và tham số phổ của model."),
            ("STFT", "Biến waveform thành biểu diễn phổ."),
            ("Chunk phổ", "Cắt/đệm phổ theo độ dài segment."),
            ("Mạng TFC-TDF", "Ước lượng stem từ đặc trưng thời gian–tần số."),
            ("ISTFT", "Dựng phổ dự đoán về waveform."),
            ("Stem + export", "Map tên stem và ghi output theo config."),
        ],
        "MDX23C là tên họ model; repo không khai triển chữ viết tắt. TFC-TDF là tên lớp mạng trong code; repo cũng không định nghĩa đầy đủ tên các chữ đó.",
        "MDXC • MDX23C",
    )

    training_png()


if __name__ == "__main__":
    main()
