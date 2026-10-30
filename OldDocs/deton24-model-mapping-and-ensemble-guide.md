# Hướng dẫn ánh xạ model Deton24 ↔ Audio-Separator và tạo ensemble

**Ngày:** 2026-03-15
**Tài liệu nguồn:** `OldDocs/deton24-audio-separation-info-2026-03-15.md` (chuyển đổi từ [Google Doc của deton24](https://docs.google.com/document/d/17fjNvJzj8ZGSer7c7OFe_CNfUKbAxEh_OBv94ZdRG5c))

## Mục đích

**Ghi chú:** Các số dòng trong tài liệu này tham chiếu bản tiếng Anh gốc của tài liệu Deton24 để vị trí dẫn chiếu không bị thay đổi bởi bản dịch.

Tài liệu này dùng để:
1. Tra cứu quy ước đặt tên, ánh xạ giữa tên file model trong audio-separator và tên gọi không chính thức trong tài liệu deton24 cũng như cộng đồng tách âm thanh.
2. Tra cứu vị trí các phần, kèm số dòng trong tài liệu deton24 để tìm chủ đề.
3. Làm bản mô tả tác vụ cho các agent Claude triển khai cải tiến cho audio-separator (ensemble preset, model mới, sửa pha).

---

## Mục lục

- [Phần 1: Cách tra cứu tài liệu Deton24](#section-1-how-to-navigate-the-deton24-doc)
- [Phần 2: Bảng tra cứu quy ước tên](#section-2-naming-convention-lookup-table)
- [Phần 3: Giải thích các chỉ số chính](#section-3-key-metrics-explained)
- [Phần 4: Ánh xạ thuật toán ensemble](#section-4-ensemble-algorithm-mapping)
- [Phần 5: Các ensemble preset được đề xuất (có thể triển khai ngay)](#section-5-recommended-ensemble-presets-implementable-now)
- [Phần 6: Model hàng đầu còn thiếu cần bổ sung](#section-6-missing-top-tier-models-to-add)
- [Phần 7: Sửa pha — khái niệm và cách triển khai](#section-7-phase-fix--what-it-is-and-how-to-implement-it)
- [Phần 8: Mô tả tác vụ cho agent](#section-8-agent-task-briefs)

---

<a id="section-1-how-to-navigate-the-deton24-doc"></a>

## Phần 1: Cách tra cứu tài liệu Deton24

Tài liệu deton24 (`OldDocs/deton24-audio-separation-info-2026-03-15.md`) có hơn 27.000 dòng. Dưới đây là các vị trí phần quan trọng:

| Chủ đề | Dòng gần đúng | Tiêu đề phần |
|-------|--------------|--------------|
| **Danh sách model tốt nhất** | 6845 | `### **The best models**` |
| **Model nhạc nền tốt nhất** | 6858 | `###### > for instrumentals` |
| **Ensemble nhạc nền** | 7676 | `###### **>Ensembles**` (cho nhạc nền) |
| **Model giọng hát tốt nhất** | 8352 | `###### **>** ***for vocals***` |
| **Ensemble giọng hát** | 8769 | `###### **Ensembles**` (cho giọng hát) |
| **Khử lẫn/làm sạch** | 9421 | `###### **Debleeding/cleaning vocals/instrumentals/inverts**` |
| **Karaoke** | 9636 | `###### **>Karaoke**` |
| **Chỉ giữ giọng hát chính** | 10034 | `###### >Keeping only **lead vocals**` |
| **Tách trống Drumsep** | 10717 | `###### **>Sep. parts of drums a.k.a. Drumsep**` |
| **Khử vang** | 11220 | `###### **De-reverb**` |
| **Khử nhiễu** | 11538 | `###### **De-noising (vinyl noise/white noise/general)**` |
| **Giải thích thuật toán ensemble** | 12212 | `###### *Ensemble algorithm explanations*` |
| **Quy tắc tối đa 4–5 model** | 12351 | `###### *4-5 max ensemble models rule*` |
| **Bảng xếp hạng SDR** | 13286 | `##### SDR leaderboard` |
| **Xếp hạng nhạc nền theo bleedless** | 13478 | `##### *Instrumental models sorted by instrumental* ***bleedless*** *metric:*` |
| **Xếp hạng giọng hát theo bleedless** | 13558 | `###### Vocal models/ensembles sorted by instrumental **bleedless** metric` |
| **Tách phantom center** | 14731 | `##### Similarity/Phantom Center/Mid channel Extractor` |
| **Drumsep (chi tiết)** | 18938 | `## Drumsep - single percussion instruments separation` |
| **Công cụ sửa/đảo pha** | 27072 | `###### *Phase fixer/swapper*` |

### Mẹo tra cứu

- Tài liệu dùng **biệt danh trong cộng đồng**, không dùng tên file. Ví dụ: “v1e+” = `melband_roformer_inst_v1e_plus.ckpt`, “deux” = Mel-Roformer tách kép giọng hát + nhạc nền của becruily, “Resurrection” = các model BS-Roformer của unwa.
- Tác giả model thường được nhắc bằng tên Discord: **unwa** (pcunwa), **Gabox** (GaboxR67), **becruily**, **aufr33**, **viperx**, **anvuew**, **jarredou**, **Aname** (Aname-Tommy), **mesk** (meskvlla33), **ZFTurbo** (nhà phát triển MVSEP).
- “MVSEP exclusive” nghĩa là model chỉ dùng được trên mvsep.com và không thể tải xuống — không thể thêm các model này vào audio-separator.
- “UVR” là Ultimate Vocal Remover GUI, ứng dụng desktop chính được phần lớn cộng đồng sử dụng.
- “MSST” là Music Source Separation Training, framework dùng để huấn luyện và chạy suy luận trên các model Roformer mới hơn.

---

<a id="section-2-naming-convention-lookup-table"></a>

## Phần 2: Bảng tra cứu quy ước tên

### Roformer — giọng hát

| Tên trong cộng đồng | Tên file audio-separator | Tác giả | Chỉ số chính | Ghi chú |
|---|---|---|---|---|
| Kim (bản gốc) | `vocals_mel_band_roformer.ckpt` | KimberleyJSN | — | Mel-Roformer bản gốc |
| Kim FT | `mel_band_roformer_kim_ft_unwa.ckpt` | unwa | — | Tinh chỉnh từ Kim |
| Kim FT2 | `mel_band_roformer_kim_ft2_unwa.ckpt` | unwa | — | |
| FT2 ít lẫn âm | `mel_band_roformer_kim_ft2_bleedless_unwa.ckpt` | unwa | bleedless 39.30 | Giọng hát rất sạch |
| Kim FT3 (preview) | `mel_band_roformer_kim_ft3_unwa.ckpt` | unwa | — | Được dùng làm tham chiếu sửa pha trong một số thiết lập |
| Giọng hát becruily | `mel_band_roformer_vocals_becruily.ckpt` | becruily | — | Model tham chiếu sửa pha quan trọng; là một phần của model kép “deux” |
| Gabox voc | `mel_band_roformer_vocals_gabox.ckpt` | Gabox | — | |
| Gabox voc v2 | `mel_band_roformer_vocals_v2_gabox.ckpt` | Gabox | — | |
| Gabox voc fv1–fv6 | `mel_band_roformer_vocals_fv1_gabox.ckpt` … `fv6` | Gabox | fv4 tốt nhất cho RVC | fv6 có độ đầy rất cao (24.93) |
| Big Beta 4 | `melband_roformer_big_beta4.ckpt` | unwa | — | |
| Big Beta 5e | `melband_roformer_big_beta5e.ckpt` | unwa | — | |
| Big Beta 6 | `melband_roformer_big_beta6.ckpt` | unwa | — | |
| Big Beta 6X | `melband_roformer_big_beta6x.ckpt` | unwa | SDR 11.12 | Cân bằng tốt |
| Revive | `bs_roformer_vocals_revive_unwa.ckpt` | unwa | — | |
| Revive 2 | `bs_roformer_vocals_revive_v2_unwa.ckpt` | unwa | bleedless 40.07 | Chỉ số bleedless cho giọng hát cao nhất |
| Revive 3e | `bs_roformer_vocals_revive_v3e_unwa.ckpt` | unwa | fullness 21.43 | Giọng hát có độ đầy cao |
| Resurrection (giọng hát) | `bs_roformer_vocals_resurrection_unwa.ckpt` | unwa | SDR 11.34, bleedless 39.99 | Hàng đầu, chỉ 195 MB, chạy nhanh |
| FullnessVocalModel | `mel_band_roformer_vocal_fullness_aname.ckpt` | Aname | — | |
| SYHFT v1-v3 | `MelBandRoformerSYHFT.ckpt`… | — | — | Không được nhắc nhiều trong tài liệu deton24 |

### Roformer — nhạc nền

| Tên trong cộng đồng | Tên file audio-separator | Tác giả | Chỉ số chính | Ghi chú |
|---|---|---|---|---|
| becruily inst | `mel_band_roformer_instrumental_becruily.ckpt` | becruily | SDR 17.55, bleedless 41.36 | Một phần của model kép “deux”; cộng đồng xem là “SOTA” |
| Gabox inst / inst2 / inst3 | `mel_band_roformer_instrumental_gabox.ckpt`… | Gabox | — | |
| Gabox bleedless v1–v3 | `mel_band_roformer_instrumental_bleedless_v1_gabox.ckpt`… | Gabox | — | Tối ưu để giảm âm lọt |
| Gabox fullness v1–v3 | `mel_band_roformer_instrumental_fullness_v1_gabox.ckpt`… | Gabox | — | Tối ưu độ đầy |
| Gabox fullness noise v4 | `mel_band_roformer_instrumental_fullness_noise_v4_gabox.ckpt` | Gabox | fullness 40.40 | Còn gọi là “inst_Fv4Noise” |
| INSTV5 / INSTV5N | `mel_band_roformer_instrumental_instv5_gabox.ckpt` / `instv5n` | Gabox | — | |
| INSTV6 / INSTV6N | `mel_band_roformer_instrumental_instv6_gabox.ckpt` / `instv6n` | Gabox | INSTV6N: fullness 41.68 | Độ đầy rất cao nhưng nhiều nhiễu |
| INSTV7 / INSTV7N | `mel_band_roformer_instrumental_instv7_gabox.ckpt` / `instv7n` | Gabox | — | |
| INSTV8 / INSTV8N | `mel_band_roformer_instrumental_instv8_gabox.ckpt` / `instv8n` | Gabox | — | |
| Inst_GaboxFv7z | `mel_band_roformer_instrumental_fv7z_gabox.ckpt` | Gabox | bleedless 44.61 | **Model nhạc nền ít lẫn âm tốt nhất**, gần như không nhiễu |
| Inst_GaboxFv8 | `mel_band_roformer_instrumental_fv8_gabox.ckpt` | Gabox | — | |
| Inst_GaboxFVX | `mel_band_roformer_instrumental_fvx_gabox.ckpt` | Gabox | — | |
| v1e | `melband_roformer_inst_v1e.ckpt` | unwa | fullness 38.87 | Model tăng độ đầy kinh điển |
| v1e+ | `melband_roformer_inst_v1e_plus.ckpt` | unwa | fullness 37.89 | Cân bằng độ đầy tốt nhất |
| v1+ | `melband_roformer_inst_v1_plus.ckpt` | unwa | — | |
| Resurrection Inst | `bs_roformer_instrumental_resurrection_unwa.ckpt` | unwa | SDR 17.25 | Chỉ 200 MB, dùng đa dụng rất tốt |
| BS-Roformer SW | `BS-Roformer-SW.ckpt` | — | — | Đảo ngược Apple Logic Pro, tách 6 stem |

### Roformer — karaoke

| Tên trong cộng đồng | Tên file audio-separator | Tác giả | Chỉ số chính |
|---|---|---|---|
| Karaoke aufr33/viperx | `mel_band_roformer_karaoke_aufr33_viperx_sdr_10.1956.ckpt` | aufr33/viperx | SDR 10.20 |
| kar_gabox | `mel_band_roformer_karaoke_gabox.ckpt` | Gabox | — |
| Karaoke_GaboxV2 | `mel_band_roformer_karaoke_gabox_v2.ckpt` | Gabox | — |
| Karaoke becruily | `mel_band_roformer_karaoke_becruily.ckpt` | becruily | — |

### Roformer — khử vang/khử nhiễu/đặc biệt

| Tên trong cộng đồng | Tên file audio-separator | Tác giả | Ghi chú |
|---|---|---|---|
| Khử nhiễu Aufr33 (mức trung bình) | `denoise_mel_band_roformer_aufr33_sdr_27.9959.ckpt` | aufr33 | Model khử nhiễu nên thử đầu tiên |
| Khử nhiễu Aufr33 (mạnh) | `denoise_mel_band_roformer_aufr33_aggr_sdr_27.9768.ckpt` | aufr33 | |
| Gabox khử nhiễu và giảm âm lọt | `mel_band_roformer_denoise_debleed_gabox.ckpt` | Gabox | Tiền xử lý |
| anvuew khử vang (stereo) | `dereverb_mel_band_roformer_anvuew_sdr_19.1729.ckpt` | anvuew | |
| anvuew khử vang (ít mạnh hơn) | `dereverb_mel_band_roformer_less_aggressive_anvuew_sdr_18.8050.ckpt` | anvuew | |
| anvuew khử vang mono | `dereverb_mel_band_roformer_mono_anvuew.ckpt` | anvuew | SDR 20.40 |
| Loại bỏ tiếng đám đông | `mel_band_roformer_crowd_aufr33_viperx_sdr_8.7144.ckpt` | aufr33/viperx | |
| Giảm âm lọt | `mel_band_roformer_bleed_suppressor_v1.ckpt` | unwa/97chris | Hậu xử lý cho nhạc nền |
| Tách tiếng chorus | `model_chorus_bs_roformer_ep_267_sdr_24.1275.ckpt` | — | |
| Model tách hơi thở | `aspiration_mel_band_roformer_sdr_18.9845.ckpt`… | — | |

### MDX / MDX23C / VR / Demucs

| Tên trong cộng đồng | Tên file audio-separator | Ghi chú |
|---|---|---|
| UVR-MDX-NET-Inst_HQ_5 | `UVR-MDX-NET-Inst_HQ_5.onnx` | Kiến trúc MDX cũ hơn, vẫn hữu ích để tạo ensemble nhanh, ít tốn tài nguyên |
| MDX23C DrumSep | `MDX23C-DrumSep-aufr33-jarredou.ckpt` | Tách trống thành 5 phần (kick/snare/toms/cymbals/other) |
| MDX23C khử vang | `MDX23C-De-Reverb-aufr33-jarredou.ckpt` | |
| UVR khử vang | `UVR-De-Reverb-aufr33-jarredou.pth` | Kiến trúc VR |
| BVE (tách bè hát) | `UVR-BVE-4B_SN-44100-2.pth` | Kiến trúc VR, tách bè hát |
| htdemucs_ft | `htdemucs_ft.yaml` | Tách 4 stem (vocals/drums/bass/other), nên dùng để tách trống sơ bộ |

---

<a id="section-3-key-metrics-explained"></a>

## Phần 3: Giải thích các chỉ số chính

Cộng đồng dùng ba chỉ số chính để đánh giá model (xem tài liệu deton24 khoảng dòng 6850 và bảng xếp hạng khoảng dòng 13286):

| Chỉ số | Đo lường | Giá trị cao hơn nghĩa là |
|--------|----------|--------------------------|
| **SDR** (Signal-to-Distortion Ratio) | Chất lượng tách tổng thể so với âm thanh chuẩn | Chất lượng tổng thể tốt hơn |
| **Bleedless** | Mức độ các stem *khác* lọt vào stem đích | Đầu ra sạch hơn, nhưng có thể đục/thiếu sáng hơn |
| **Fullness** | Mức độ nội dung của stem đích được giữ lại | Đầu ra đầy/giàu âm hơn, nhưng có thể nhiều nhiễu và âm lọt hơn |

**Lưu ý:** Bleedless và fullness đối nghịch nhau; một model khó tối đa hóa đồng thời cả hai. Cộng đồng chia model thành:
- **Model tăng fullness**: v1e, INSTV6N, inst_Fv4Noise — giữ được nhiều nhạc cụ hơn nhưng có nhiễu/âm giọng hát sót lại.
- **Model ít lẫn âm**: Fv7z, FNO, Revive 2 — sạch hơn nhưng có thể làm mất một số nhạc cụ nhỏ.
- **Model cân bằng**: Resurrection Inst, becruily “deux”, Beta 6X — hướng đến cân bằng cả hai.

Các ensemble tốt thường kết hợp một model tăng fullness với một model ít lẫn âm, dùng thuật toán phù hợp.

---

<a id="section-4-ensemble-algorithm-mapping"></a>

## Phần 4: Ánh xạ thuật toán ensemble

Tài liệu deton24 (dòng 12212–12365) giải thích thuật toán ensemble. Bảng dưới đây ánh xạ thuật ngữ cộng đồng sang lớp `Ensembler` của audio-separator (`audio_separator/separator/ensembler.py`):

| Thuật ngữ cộng đồng / UVR | Thuật toán audio-separator | Tác động | Phù hợp nhất |
|---|---|---|---|
| **Avg Spec** / **Average** | `avg_wave` hoặc `avg_fft` | Lấy trung bình mọi đầu vào | SDR cao nhất, lựa chọn mặc định an toàn |
| **Max Spec** | `uvr_max_spec` hoặc `max_fft` | Giữ các bin tần số có biên độ lớn nhất | Đầu ra đầy hơn, âm lọt nhiều hơn; tốt cho giọng hát |
| **Min Spec** | `uvr_min_spec` hoặc `min_fft` | Giữ các bin tần số có biên độ nhỏ nhất | Đầu ra sạch hơn, ít âm lọt; tốt cho nhạc nền |
| **Max FFT** | `max_fft` | Cùng ý tưởng với Max Spec nhưng trong miền FFT | Trong cộng đồng thường dùng thay cho Max Spec |
| **Min FFT** | `min_fft` | Cùng ý tưởng với Min Spec nhưng trong miền FFT | |
| **Median** | `median_wave` hoặc `median_fft` | Lấy giá trị trung vị | Giảm nhiễu giả bất thường |

### Kinh nghiệm thực tế trong cộng đồng (theo tài liệu deton24 từ dòng 12212)

- **Avg/Avg** thường có SDR cao nhất và là lựa chọn mặc định an toàn nhất.
- Dùng **Max Spec** cho giọng hát (đầy hơn, giữ được nhiều nội dung giọng hát hơn, nhưng âm nhạc cụ lọt vào nhiều hơn).
- Dùng **Min Spec** cho nhạc nền (sạch hơn, ít sót giọng hát hơn, nhưng có thể nghe nghẹt).
- **Max/Min** nghĩa là dùng max cho stem giọng hát và min cho stem nhạc nền (thường được khuyến nghị).
- **Không nên ensemble quá 4–5 model** — SDR giảm khi vượt quá số này (dòng 12351).

---

<a id="section-5-recommended-ensemble-presets-implementable-now"></a>

## Phần 5: Ensemble preset được đề xuất (có thể triển khai ngay)

Các ensemble này **chỉ dùng model đã có trong audio-separator**. Xếp hạng theo mức đồng thuận trong tài liệu deton24.

### Ensemble nhạc nền

#### Preset: `instrumental_clean` — Ít lẫn âm + đa dụng
```
Models:
  - mel_band_roformer_instrumental_fv7z_gabox.ckpt
  - bs_roformer_instrumental_resurrection_unwa.ckpt
Algorithm: uvr_max_spec
```
**Lý do:** Fv7z đứng đầu về giảm âm lọt (44.61), còn Resurrection Inst là model đa dụng rất tốt (SDR 17.25). Max Spec bổ sung phần âm mà Fv7z có thể bỏ sót. Phần ensemble của tài liệu deton24 khoảng dòng 7739 có bàn về Fv7z.

#### Preset: `instrumental_full` — Giữ lại tối đa nhạc cụ
```
Models:
  - melband_roformer_inst_v1e_plus.ckpt
  - mel_band_roformer_instrumental_becruily.ckpt
Algorithm: uvr_max_spec
```
**Lý do:** v1e+ (fullness 37.89) là model tăng fullness kinh điển của cộng đồng. becruily inst được xem là “SOTA” (SDR 17.55). Max Spec giữ lại năng lượng. Dựa trên cách ghép ensemble ở dòng khoảng 7777–7789 của tài liệu deton24.

#### Preset: `instrumental_balanced` — Cân bằng nhiễu và độ đầy
```
Models:
  - mel_band_roformer_instrumental_instv8_gabox.ckpt
  - bs_roformer_instrumental_resurrection_unwa.ckpt
Algorithm: uvr_max_spec
```
**Lý do:** Lấy ý tưởng từ dòng khoảng 7743 của tài liệu deton24 (“Gabox Inst V8 + [model] = cân bằng tốt giữa nhiễu và độ đầy”). Dùng Resurrection Inst làm model thứ hai vì model MVSEP được nhắc đến ở đó không có sẵn để chạy cục bộ.

#### Preset: `instrumental_low_resource` — Nhanh, ít VRAM
```
Models:
  - bs_roformer_instrumental_resurrection_unwa.ckpt
  - UVR-MDX-NET-Inst_HQ_5.onnx
Algorithm: avg_fft
```
**Lý do:** Resurrection Inst chỉ 200 MB và chạy nhanh. HQ_5 dùng kiến trúc MDX nên rất nhanh. Avg là lựa chọn an toàn nhất. Dòng khoảng 7855 của tài liệu deton24 nhắc đến HQ_5 trong các ensemble ít tốn tài nguyên.

### Ensemble giọng hát

#### Preset: `vocal_balanced` — Chất lượng tổng thể tốt nhất
```
Models:
  - bs_roformer_vocals_resurrection_unwa.ckpt
  - melband_roformer_big_beta6x.ckpt
Algorithm: avg_fft
```
**Lý do:** Resurrection (SDR 11.34, bleedless 39.99) + Beta 6X (SDR 11.12). Lấy trung bình hai model hàng đầu để đạt SDR cao. Khuyến nghị của cộng đồng nằm ở dòng khoảng 8789–8791 trong tài liệu deton24.

#### Preset: `vocal_clean` — Hạn chế nhạc cụ lọt vào
```
Models:
  - bs_roformer_vocals_revive_v2_unwa.ckpt
  - mel_band_roformer_kim_ft2_bleedless_unwa.ckpt
Algorithm: min_fft
```
**Lý do:** Revive 2 (bleedless 40.07) + FT2 bleedless (39.30) cho đầu ra sạch nhất. Min FFT loại thêm những gì không xuất hiện ở cả hai model, nhờ đó giảm âm lọt hơn nữa.

#### Preset: `vocal_full` — Thu được tối đa nội dung giọng hát
```
Models:
  - bs_roformer_vocals_revive_v3e_unwa.ckpt
  - mel_band_roformer_vocals_becruily.ckpt
Algorithm: max_fft
```
**Lý do:** Revive 3e (fullness 21.43) + becruily vocal (fullness 23.25). Max FFT giữ lại toàn bộ nội dung giọng hát mà cả hai model phát hiện. Phù hợp để lấy bè và bè nền. Tham khảo các dòng khoảng 8783–8795 trong tài liệu deton24.

#### Preset: `vocal_rvc` — Tối ưu cho RVC/huấn luyện AI
```
Models:
  - melband_roformer_big_beta6x.ckpt
  - mel_band_roformer_vocals_fv4_gabox.ckpt
Algorithm: avg_wave
```
**Lý do:** Được khuyến nghị trực tiếp tại dòng khoảng 8789–8791 của tài liệu deton24 cho RVC: “beta6x + voc_fv4”. Lấy trung bình để có đầu ra sạch, ổn định, phù hợp làm dữ liệu huấn luyện.

### Ensemble karaoke

#### Preset: `karaoke` — Loại bỏ giọng hát chính (3 model)
```
Models:
  - mel_band_roformer_karaoke_aufr33_viperx_sdr_10.1956.ckpt
  - mel_band_roformer_karaoke_gabox_v2.ckpt
  - mel_band_roformer_karaoke_becruily.ckpt
Algorithm: avg_wave
```
**Lý do:** Tài liệu deton24 cho biết ensemble karaoke 3 model đạt SDR khoảng 10.6, so với khoảng 10.2 ở model đơn. Đây là ba model karaoke chính có trong audio-separator.

### Quy trình xử lý tuần tự (không phải ensemble chạy song song)

#### Quy trình: `clean_vocals` — Chuỗi làm sạch giọng hát đầy đủ
```
Step 1: Tách giọng hát (preset vocal_balanced hoặc một model)
Step 2: denoise_mel_band_roformer_aufr33_sdr_27.9959.ckpt (khử nhiễu)
Step 3: dereverb_mel_band_roformer_mono_anvuew.ckpt (khử vang)
```
**Lý do:** Dòng khoảng 8807–8817 trong tài liệu deton24 khuyến nghị quy trình: giọng hát → khử vang → karaoke → khử nhiễu. Thành viên cộng đồng natethegratevhs cũng khuyên nên khử nhiễu trước.

#### Quy trình: `drumsep` — Tách chi tiết các phần trống
```
Step 1: htdemucs_ft.yaml (lấy stem trống từ bản phối)
Step 2: MDX23C-DrumSep-aufr33-jarredou.ckpt (chia trống thành kick/snare/toms/cymbals)
```
**Lý do:** Từ dòng khoảng 10717 trở đi, tài liệu deton24 khuyến nghị tách trống sơ bộ bằng htdemucs_ft rồi dùng Drumsep để tách stem con. Model MDX23C của jarredou là model Drumsep duy nhất có thể tải xuống.

---

<a id="section-6-missing-top-tier-models-to-add"></a>

## Phần 6: Model hàng đầu còn thiếu cần bổ sung

Các model dưới đây được nhắc đến nhiều trong tài liệu deton24, có thể tải công khai và sẽ cải thiện đáng kể chất lượng của audio-separator — đặc biệt khi tạo ensemble.

### Ưu tiên cao (hàng đầu, công khai, thường được nhắc đến)

| Model | Tác giả | Loại | URL HuggingFace | Chỉ số chính | Dòng trong Deton24 |
|---|---|---|---|---|---|
| BS-Roformer HyperACE v2 inst | unwa | nhạc nền | `pcunwa/BS-Roformer-HyperACE` (kiểm tra đường dẫn chính xác) | SDR 17.40, fullness 38.03 | ~7682, 7698, 7702 |
| BS-Roformer HyperACE v2 voc | unwa | giọng hát | cùng repo | SDR 11.40 | ~8777 |
| BS-Roformer-Inst-FNO | unwa | nhạc nền | `pcunwa/` (kiểm tra) | SDR 17.60 (SDR nhạc nền công khai cao nhất) | ~7714, 7755 |
| Mel “deux” (becruily) | becruily | kép (giọng hát + nhạc nền) | `becruily/mel-band-roformer-deux` | SDR nhạc nền 17.55, SDR giọng hát 11.37 | ~7682, 7698, 8773 |
| Big Beta 7 | unwa | giọng hát | `pcunwa/` (kiểm tra) | SDR 11.20 | ~8775 |
| Gabox voc_fv7 + betas | Gabox | giọng hát | `GaboxR67/MelBandRoformers` | SDR 11.16 | ~8826 |
| Gabox inst_gaboxFlowersV10 | Gabox | nhạc nền | cùng repo | SDR 16.95, fullness 37.12 | ~7759 |
| Rifforge | mesk | nhạc nền (metal) | `meskvlla33/rifforge` | — | ~7759 |
| BS-Roformer 1296/1297 | viperx | giọng hát | xem HuggingFace | SDR 12.96/12.97 | ~7753, 7847–7852 |
| anvuew dereverb BS (stereo, SDR 22.50) | anvuew | khử vang | xem HuggingFace | SDR 22.50 | ~100 |
| BS_RoFormer_mag | anvuew | giọng hát | `anvuew/BS_RoFormer_mag` | bleedless 32.17, fullness 22.15 | ~59 |

### Ưu tiên trung bình (hữu ích nhưng ít cấp thiết hơn)

| Model | Tác giả | Loại | Ghi chú |
|---|---|---|---|
| BS-Roformer-Inst-EXP-Value-Residual | unwa | nhạc nền | Thử nghiệm |
| BS-EXP-SiameseRoformer | unwa | giọng hát | Thử nghiệm, cần mã tùy chỉnh |
| gilliaan MonoStereo Dual Beta1/2 | gilliaan | phantom center | Trường hợp sử dụng chuyên biệt |
| Neo_InstVFX | neoculture | nhạc nền | Giữ lại đoạn vocal chop (K-pop) |

### Không thể thêm (chỉ có trên MVSEP)

Các model này thường được nhắc trong tài liệu nhưng **không thể tải xuống** — chỉ dùng được trên mvsep.com:

- BS-Roformer 2025.07, 2025.06, 2024.08, 2024.04 (của ZFTurbo)
- SCNet XL, SCNet Large, SCNet XL IHF và các biến thể SCNet
- Nhiều model tách nhạc cụ riêng (saxophone, trumpet, violin, v.v.)
- VitLarge23
- Model Mel-Roformer và SCNet Drumsep tách 4/5/6 stem

---

<a id="section-7-phase-fix--what-it-is-and-how-to-implement-it"></a>

## Phần 7: Sửa pha — khái niệm và cách triển khai

### Bối cảnh

Kỹ thuật sửa pha (còn gọi là “phase swapper”) do **aufr33** phát triển và được thảo luận chi tiết ở dòng 27072–27170 trong tài liệu deton24. Đây là một trong những kỹ thuật hậu xử lý có tác động lớn nhất đối với việc tách nhạc nền.

### Vấn đề cần giải quyết

Model Roformer huấn luyện với **stem nhạc nền làm mục tiêu** tạo nhạc nền đầy đặn nhưng còn nhiễu giọng hát. Model huấn luyện với **stem giọng hát làm mục tiêu** tạo nhạc nền đục hơn (do phép đảo) nhưng có chỉ số bleedless tốt hơn. Sửa pha kết hợp ưu điểm của cả hai.

### Cách hoạt động (kỹ thuật)

Theo giải thích của jarredou (dòng 27160–27164 trong tài liệu deton24):

> “Trong miền STFT có thông tin pha. Với mỗi bin STFT, thuật toán lấy **dữ liệu biên độ** từ một model [model nhạc nền], còn **dữ liệu pha** lấy từ model khác [đầu ra nhạc nền của model giọng hát], với hy vọng cải thiện kết quả cuối.”

Theo santilli_ (dòng 27166):

> “Script trộn pha STFT của file ‘cho mượn’ vào file đích. Nó dùng các mức trộn khác nhau theo từng tần số để chỉ tác động đến những phần liên quan trực tiếp đến nhiễu nghe được.”

### Thuật toán (mã giả)

```python
import librosa
import numpy as np

def phase_fix(target_audio, reference_audio, sr,
              low_cutoff=500, high_cutoff=5000,
              high_freq_weight=0.8, n_fft=2048):
    """
    Sửa pha của âm thanh đích bằng pha trong âm thanh tham chiếu.

    Args:
        target_audio: Nhạc nền từ model huấn luyện cho stem nhạc nền (đầy nhưng nhiễu)
        reference_audio: Nhạc nền từ model huấn luyện cho stem giọng hát (đục nhưng pha sạch)
        low_cutoff: Tần số dưới ngưỡng này không thay pha (Hz)
        high_cutoff: Tần số trên ngưỡng này, trọng số trộn giảm dần (Hz)
        high_freq_weight: Trọng số trộn cho tần số trên high_cutoff (0.8-2.0)
        n_fft: Kích thước FFT
    Returns:
        Âm thanh đã sửa pha
    """
    # Chuyển sang STFT
    target_stft = librosa.stft(target_audio, n_fft=n_fft)
    reference_stft = librosa.stft(reference_audio, n_fft=n_fft)

    # Lấy biên độ từ target, pha từ reference
    target_magnitude = np.abs(target_stft)
    reference_phase = np.angle(reference_stft)
    target_phase = np.angle(target_stft)

    # Tạo trọng số trộn phụ thuộc vào tần số
    freqs = librosa.fft_frequencies(sr=sr, n_fft=n_fft)
    blend_weights = np.zeros_like(freqs)

    for i, f in enumerate(freqs):
        if f < low_cutoff:
            blend_weights[i] = 0.0  # Giữ pha target dưới low_cutoff
        elif f < high_cutoff:
            # Nội suy tuyến tính giữa hai ngưỡng
            blend_weights[i] = (f - low_cutoff) / (high_cutoff - low_cutoff)
        else:
            blend_weights[i] = high_freq_weight  # Dùng high_freq_weight phía trên high_cutoff

    # Trộn pha: pha_mới = pha_target * (1 - trọng_số) + pha_reference * trọng_số
    blend_weights = blend_weights[:, np.newaxis]  # Điều chỉnh hình dạng để broadcasting
    blended_phase = target_phase * (1 - blend_weights) + reference_phase * blend_weights

    # Dựng lại với biên độ target và pha đã trộn
    fixed_stft = target_magnitude * np.exp(1j * blended_phase)
    fixed_audio = librosa.istft(fixed_stft, length=len(target_audio))

    return fixed_audio
```

### Tham số chính (theo khuyến nghị của cộng đồng)

| Tham số | Mặc định (UVR) | Mặc định (Colab) | Khuyến nghị của santilli_ | Trường hợp sử dụng |
|---|---|---|---|---|
| `low_cutoff` | 500 Hz | 500 Hz | 100–420 Hz | Giá trị thấp hơn = sửa mạnh hơn |
| `high_cutoff` | 5000 Hz | 9000 Hz | 100–4200 Hz | Giá trị thấp hơn = sửa mạnh hơn |
| `high_freq_weight` | 0.8 | 0.8 | **2.0** | “Tăng từ 0.8 lên 2 sẽ có lợi” (dòng 27076) |

### Các cặp model thường dùng để sửa pha

Các cặp target→reference được khuyến nghị trong tài liệu (dòng 27086–27098):

| Target (model nhạc nền) | Reference (model giọng hát cho mượn pha) | Giá trị cutoff |
|---|---|---|
| `melband_roformer_inst_v1e.ckpt` | `mel_band_roformer_vocals_becruily.ckpt` (đầu ra nhạc nền) | 100/100 (mạnh) |
| `melband_roformer_inst_v1e_plus.ckpt` | `mel_band_roformer_vocals_becruily.ckpt` (đầu ra nhạc nền) | 100/100 |
| `bs_roformer_instrumental_resurrection_unwa.ckpt` | `mel_band_roformer_vocals_becruily.ckpt` (đầu ra nhạc nền) | 3000/5000 |
| Model Gabox inst bất kỳ | `mel_band_roformer_vocals_becruily.ckpt` (đầu ra nhạc nền) | 500/5000 |

**Quan trọng:** “reference” là **stem nhạc nền do model hướng đến giọng hát tạo ra**, không phải stem giọng hát. Hãy tách bằng model giọng hát, lấy stem nhạc nền của model đó rồi dùng làm tham chiếu pha.

### Tham khảo mã hiện có

- **Script gốc của Becruily:** https://drive.google.com/drive/folders/1JOa198ALJ0SnEreCq2y2kVj-sktvPePy
- **Colab Phase Fixer (santilli_):** https://colab.research.google.com/drive/1PMQmFRZb_XRIKnBjXhYlxNlZ5XcKMWXm
- **Repo MSST** đã tích hợp sửa pha vào quy trình suy luận.

### Đề xuất triển khai trong audio-separator

Nên thêm sửa pha như một bước hậu xử lý trong lớp `Ensembler` hoặc dưới dạng tiện ích độc lập. Quy trình sẽ là:

1. Người dùng tách bằng model nhạc nền → nhận `instrumental_target.wav`.
2. Người dùng tách bằng model giọng hát → nhận `instrumental_reference.wav` (stem “other”).
3. Sửa pha kết hợp biên độ ở bước 1 với pha ở bước 2.
4. Có thể tiếp tục ensemble kết quả đã sửa pha với đầu ra của các model khác.

Có thể cung cấp chức năng này qua cấu hình pipeline preset:
```yaml
preset: instrumental_phase_fixed
steps:
  - model: melband_roformer_inst_v1e_plus.ckpt
    output: target_instrumental
  - model: mel_band_roformer_vocals_becruily.ckpt
    output: reference_instrumental  # dùng stem nhạc nền
  - phase_fix:
      target: target_instrumental
      reference: reference_instrumental
      low_cutoff: 100
      high_cutoff: 100
      high_freq_weight: 2.0
```

---

<a id="section-8-agent-task-briefs"></a>

## Phần 8: Mô tả tác vụ cho agent

### Tác vụ A: Triển khai cấu hình ensemble preset

**Mục tiêu:** Thêm cấu hình ensemble preset để người dùng gọi theo tên.

**Các file chính cần sửa:**
- `audio_separator/separator/ensembler.py` — đã có các thuật toán ensemble
- `audio_separator/separator/separator.py` — lớp điều phối chính, quản lý nạp model và tách âm thanh
- `audio_separator/utils/cli.py` — giao diện dòng lệnh, cần thêm cờ chọn preset
- File cấu hình mới (ví dụ `audio_separator/ensemble_presets.json`) để khai báo preset

**Các preset cần triển khai:** Xem [Phần 5](#section-5-recommended-ensemble-presets-implementable-now). Trước hết làm các preset cốt lõi sau:
1. `instrumental_clean` — Fv7z + Resurrection Inst (max_spec)
2. `instrumental_full` — v1e+ + becruily inst (max_spec)
3. `vocal_balanced` — Resurrection voc + Beta 6X (avg_fft)
4. `vocal_clean` — Revive 2 + FT2 bleedless (min_fft)
5. `karaoke` — ensemble karaoke 3 model (avg_wave)

**Đề xuất trải nghiệm người dùng:** `audio-separator input.wav --ensemble instrumental_clean`

**Tham khảo:** Xem các kiểm thử ensemble hiện có tại `tests/unit/test_ensembler.py` để nắm quy ước kiểm thử.

### Tác vụ B: Bổ sung model hàng đầu còn thiếu

**Mục tiêu:** Bổ sung các model ưu tiên cao trong [Phần 6](#section-6-missing-top-tier-models-to-add) vào audio-separator.

**Các file chính cần sửa:**
- `audio_separator/models.json` — danh mục model, chứa URL tải và cấu hình
- `audio_separator/separator/separator.py` — phương thức `list_supported_model_files()` (khoảng dòng 440–608)

**Quy trình cho từng model:**
1. Tìm model trên HuggingFace (kiểm tra repo tác giả được liệt kê ở Phần 6).
2. Tìm đúng file cấu hình YAML (đa số Roformer cần file YAML đi kèm).
3. Thêm mục vào `models.json` với URL tải và cấu hình.
4. Kiểm tra model nạp được và tạo ra đầu ra.
5. Xác minh tên stem đầu ra đúng như dự kiến.

**Thứ tự ưu tiên:**
1. BS-Roformer HyperACE v2 (inst + voc) — dùng trong các ensemble tốt nhất hiện tại.
2. Mel “deux” của becruily — SDR nhạc nền hàng đầu, “không cần sửa pha”.
3. BS-Roformer-Inst-FNO — SDR nhạc nền công khai cao nhất.
4. Big Beta 7 — model giọng hát mới nhất.
5. Gabox voc_fv7 + inst_gaboxFlowersV10 — các model Gabox mới nhất.
6. Rifforge — chuyên cho metal, khá đặc thù nhưng được ưa chuộng.
7. BS-Roformer 1296/1297 (viperx) — model kinh điển, vẫn dùng để sửa pha.

**Repo HuggingFace cần kiểm tra:**
- `pcunwa/` (model của unwa)
- `GaboxR67/MelBandRoformers` (model Gabox)
- `becruily/mel-band-roformer-deux` (model kép “deux”)
- `meskvlla33/rifforge` (Rifforge)
- `anvuew/` (model anvuew)

### Tác vụ C: Triển khai hỗ trợ sửa pha

**Mục tiêu:** Thêm sửa pha làm bước hậu xử lý trong audio-separator.

**Tài liệu cần đọc trước:**
- [Phần 7](#section-7-phase-fix--what-it-is-and-how-to-implement-it) của tài liệu này (thuật toán, tham số, mã giả).
- Tài liệu deton24, dòng 27072–27170, để xem đầy đủ thảo luận của cộng đồng.
- Script của Becruily: https://drive.google.com/drive/folders/1JOa198ALJ0SnEreCq2y2kVj-sktvPePy
- Mã nguồn Colab Phase Fixer: https://colab.research.google.com/drive/1PMQmFRZb_XRIKnBjXhYlxNlZ5XcKMWXm

**Cách triển khai đề xuất:**

1. **Thêm lớp `PhaseFixer`** (file mới, ví dụ `audio_separator/separator/phase_fixer.py`):
   - Nhận âm thanh đích (từ model nhạc nền) và âm thanh tham chiếu (stem nhạc nền từ model giọng hát).
   - Tham số: `low_cutoff`, `high_cutoff`, `high_freq_weight`, `n_fft`.
   - Hoạt động trong miền STFT: giữ biên độ của target và trộn pha từ reference.
   - Hỗ trợ stereo (xử lý riêng từng kênh).

2. **Tích hợp với Separator**:
   - Thêm cờ CLI `--phase_fix_reference_model`.
   - Khi cờ được bật, separator chạy model tham chiếu trước và giữ lại stem nhạc nền.
   - Sau đó chạy model đích, dùng nhạc nền tham chiếu để sửa pha.
   - Xuất nhạc nền đã sửa pha.

3. **Tích hợp với ensemble preset**:
   - Một số preset nên có bước sửa pha (xem các pipeline ở Phần 5).
   - Định dạng cấu hình preset cần hỗ trợ pipeline nhiều bước.

**Lưu ý quan trọng:** “reference” cho việc sửa pha là **stem nhạc nền do model huấn luyện cho giọng hát tạo ra**, không phải stem giọng hát. Vì vậy, nếu dùng `mel_band_roformer_vocals_becruily.ckpt` làm tham chiếu, cần lấy đầu ra “Instrumental” / “No Vocals”, không lấy đầu ra “Vocals”.

**Kiểm thử:** So sánh đầu ra v1e đã sửa pha (dùng becruily vocal làm tham chiếu, cutoff 100/100) với đầu ra v1e thông thường. Bản đã sửa pha cần giảm rõ tiếng giọng hát sót/nhiễu ở đoạn nhỏ hoặc im lặng, đồng thời vẫn giữ độ đầy của nhạc cụ.
