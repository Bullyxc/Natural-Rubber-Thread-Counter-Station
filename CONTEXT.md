# Thread Counter Station — Project Context

อัปเดตล่าสุด: 2026-09-02

ไฟล์นี้เป็น snapshot ของบริบทและสถานะงาน เพื่อใช้เริ่มงานต่อหลังจากพักหรือ
ปิดคอมพิวเตอร์ โดยต้องอ่านคู่กับ `README.md` และตรวจโค้ด/ค่า config จริงทุกครั้ง
หากมีความขัดแย้ง ให้ยึดโค้ดและ `station_config.json` ปัจจุบันเป็นหลัก แล้วอัปเดต
ไฟล์นี้เมื่อมีการเปลี่ยนแปลงที่มีสาระสำคัญ

## เป้าหมายของโปรเจค

สร้าง Thread Counter Station สำหรับแท่นยึดกล้อง USB webcam NEOCoolcam รุ่น
NE-82534053 เลนส์ manual 2.8–12 mm เพื่อถ่ายภาพผลิตภัณฑ์เส้นยางที่ใช้ทำขอบ
กางเกงใน/ชุดชั้นใน แล้วประมวลผลด้วยอัลกอริทึม computer vision ทั่วไปใน Python
เพื่อ:

- นับจำนวนเส้น/ขอบซ้ำที่เห็นในภาพ
- แสดงเส้น overlay และผลบนหน้าต่างเต็มจอ
- วัดความกว้างของแถบผลิตภัณฑ์
- จำแนกสีขาว/ดำ
- จับคู่ชนิดผลิตภัณฑ์จากกฎที่ผู้ใช้กำหนดใน `products.json`

ข้อกำหนดสำคัญ: ต้องรันด้วย Python 3.10 บนคอมพิวเตอร์เดิม และ standard CPython
3.13.5 บน Raspberry Pi 5 64-bit, ไม่ใช้ free-threaded `3.13t`, ไม่ใช้โมเดล
AI/ML และควรใช้เฉพาะ classical image-processing ที่ตรวจสอบ overlay ได้

## แหล่งอ้างอิงหลัก

อ่านตามลำดับนี้เมื่อกลับมาทำงาน:

1. `AGENT.md` — กติกาการทำงานกับ repository นี้
2. `CONTEXT.md` — สถานะและสมมติฐานล่าสุดของโปรเจค
3. `README.md` — วิธีติดตั้ง รัน ใช้งาน และตั้งค่า
4. `station_config.json` — ค่าปฏิบัติการที่ใช้จริง
5. `docs/ADR-001-classical-vision-station.md` — เหตุผลเชิงสถาปัตยกรรม
6. `docs/ADR-002-rpi5-passive-runtime.md` — runtime profile สำหรับ Pi 5 ไม่มีพัดลม
7. `docs/ADR-003-python-313-pi5.md` — interpreter/dependency contract สำหรับ Pi
8. `docs/ADR-004-dual-background-phase-one.md` — ตัวนับแพแนวตั้งบนพื้นหลังสองสี
9. `docs/glossary.md` — คำจำกัดความและกติกาที่ผู้ใช้ยืนยันในการ grilling
10. `docs/IMAGE-001-observation.md` — ข้อสังเกตจากภาพตัวอย่างเดิม
11. `pi5_usb_hdmi_station.py` / `camera_stream.py` — live implementation บน Pi
12. `dual_background_counter.py` — implementation ตัวนับ Phase 1

## โครงสร้างและ entry points

- `pi5_usb_hdmi_station.py` — entry point หลักบน Raspberry Pi 5: กล้อง USB,
  continuous inspection, 5-frame burst และจอ HDMI เต็มจอ 1024×600
- `thread_counter_station.py` — โปรแกรมหลักสำหรับ live station และประมวลผลภาพ
  เดี่ยวรุ่นเดิม ใช้ OpenCV + NumPy และบันทึกภาพ overlay/JSON
- `thread_counter.py` — wrapper ที่เรียกโปรแกรมหลัก
- `camera_capture_test.py` — โปรแกรมแยกสำหรับ preview กล้องและกดบันทึกภาพดิบ
  โดยไม่เรียกอัลกอริทึมนับ
- `camera_stream.py` — backend กล้อง UVC, การขอ MJPG, latest-frame reader และ
  การย่อเฉพาะภาพ preview เพื่อให้ UI ลื่นขึ้น
- `runtime_control.py` — ตรวจ Pi 5, จำกัด native/OpenCV threads, อ่านอุณหภูมิ
  และ RAM พร้อม thermal/memory guard
- `pi5_preflight.py` — ตรวจ Python 3.13.5, 64-bit, NumPy/OpenCV GUI และกล้อง
  ก่อนเปิด station บน Pi
- `install_pi5_system.sh` — ติดตั้ง Python/NumPy/OpenCV ลง Raspberry Pi OS
  โดยตรงด้วย apt โดยไม่สร้าง virtual environment
- `run_pi5.sh` — เรียก preflight แล้วเปิด `pi5_usb_hdmi_station.py`
- `.vscode/sftp.json` — ค่า VS Code SFTP สำหรับอัปโหลดไฟล์ที่กด Save ไปยัง
  `/home/rpi5/NRTcounter` (เก็บไฟล์นี้ใน `.gitignore` เพราะเป็นค่าเฉพาะเครื่อง)
- `station_config.json` — config กล้อง, ROI, การนับ, alignment, สี และ output
- `products.json` — catalog สินค้าจริง ปัจจุบันว่างไว้เพื่อไม่ให้เดาชนิดสินค้า
- `products.example.json` — ตัวอย่างรูปแบบกฎสินค้า
- `thread_counter_original.py` — โค้ดอ้างอิงเดิม ไม่ใช่ entry point หลัก และมี
  dependency SciPy แยกจากรุ่น station
- `image/` — ภาพตัวอย่าง/ภาพที่บันทึกจากกล้อง
- `results/` — ผลลัพธ์ที่สร้างจากการรัน ไม่ควรใช้เป็น source code
- `docs/` — ADR, glossary และบันทึกการสังเกตภาพ

## ค่าปัจจุบันที่ต้องจำ

จาก `station_config.json`:

```text
camera.index       = 1       # กล้อง USB ภายนอกโดยทั่วไป; laptop มักเป็น 0
camera.width       = 2560
camera.height      = 1440
camera.fps         = 30
processing.max_side = 1280
processing.count_axis = y
processing.num_strips = 12
processing.edge_weight = 0.20
processing.roi     = x=0.30, y=0.00, width=0.40, height=1.00
alignment.mode     = auto
alignment.max_tilt_deg = 45.0
capture.preview_width = 1600
runtime.profile      = auto
pi5_hdmi_station.camera_index = 0
pi5_hdmi_station.camera_width/height/fps = 2560/1440/15
pi5_hdmi_station.screen_width/height = 1024/600
pi5_hdmi_station.display_fps = 15
pi5_hdmi_station.burst_frames/stable_frames = 5/3
```

ความหมายของ ROI ปัจจุบันคือเลือกความกว้างตรงกลางภาพ 40% และใช้ความสูงเต็มภาพ
ตามคำขอล่าสุดของผู้ใช้ ไม่ใช่ ROI เฉพาะแถบผลิตภัณฑ์

ภาพตัวอย่างจริง `image/WIN_20260730_04_26_07_Pro.jpg` มีขนาด 1920×1080,
เส้นยางสีดำเป็นเส้นซ้ำแนวนอน และพื้นหลังมีร่องโลหะแนวตั้ง ดังนั้นตัวอย่างนี้ใช้
`count_axis=y` เพื่อวัด profile ตามแกน Y

## พฤติกรรมการแก้ภาพเอียง

เมื่อ `alignment.mode=auto` โปรแกรมจะ:

1. ตรวจแนวขอบใน ROI ด้วย Hough line
2. ใช้การค้นหาความสม่ำเสมอของ profile เป็น fallback หาก Hough พบแนวที่กำกวม
3. หมุน ROI ชั่วคราวให้เส้นซ้ำกลับมาอยู่ในแกนที่นับ
4. นับ/วัด/จำแนกสีบน ROI ที่จัดแนวแล้ว
5. แปลงเส้นผลลัพธ์กลับไปวาดบนภาพต้นฉบับตามมุมเอียงจริง

HUD แสดงมุมที่ใช้แก้ในบรรทัด `ALIGN`. ค่า `alignment.angle_deg` ในโหมด
`manual` คือมุมที่ใช้หมุนแก้ ROI ไม่ใช่มุมเอียงของชิ้นงานโดยตรง เช่นภาพที่
เอียงประมาณ +15° อาจต้องใช้ `-15°`

## สถานะการทดสอบล่าสุด

### Phase 1 พื้นหลังสองสีและแพแนวตั้ง

- ภาพอ้างอิงใหม่อยู่ใน `image/dual_background_sample_01.jpg` ถึง `_03.jpg`
  โดย sample 01/03 เป็นภาพนับสะอาด 40 เส้น ส่วน sample 02 เป็นชิ้นงาน QC FAIL
  ที่ nominal ต้องมี 40 แต่ขอบซ้ายหรือขวาฉีกจนผลที่ยอมรับคือ visible `COUNT=37`;
  metadata อยู่ใน `image/ground_truth.json`
- `dual_background_counter.py` ตรวจ seam และ safety band อัตโนมัติ, หา Dynamic
  ROI, ประเมิน pitch ต่อภาพ, รวม bounds/pitch/groove evidence ข้ามโซน และสร้าง
  centerline/bounding box หนึ่งชุดต่อเส้น
- `evaluate_reference_images.py` เป็น regression entry point และบันทึก overlay
  ลง `results/reference/`
- ผลล่าสุดบนเครื่องพัฒนา: sample 01 = 40, sample 02 = 37, sample 03 = 40;
  regression ผ่าน 3/3: `40/40 PASS`, `37/40 FAIL`, `40/40 PASS`
- sample 02 ให้ pitch ประมาณ 26.8 px อย่างสม่ำเสมอจากทั้งสองโซน ค่า 37 จึงอาจ
  เป็นจำนวนเส้นที่ยังเห็นหลังฉีก ไม่ควรบังคับเป็น nominal 40 โดยไม่มีหลักฐานภาพ
- ช่วง count 30–50 เป็นข้อจำกัดทดลองชั่วคราว สี, mm และ product lookup ถูกเลื่อน
  ไปหลัง count/overlay/width_px ผ่านภาพอ้างอิง

รายละเอียดข้อกำหนด continuous 5-frame burst, IQR, scene-change reset, latency
หนึ่งวินาที และกติกาเติมร่องถูกบันทึกใน `docs/glossary.md` และเชื่อมเข้า live
loop ใหม่ใน `pi5_usb_hdmi_station.py` แล้ว

ค่า `EXPECTED` ในงานจริงต้องมาจากการจับคู่กฎใน `products.json` โดยอัตโนมัติ
ผู้ใช้ไม่ต้องกดเลือกสินค้าและห้าม hard-code nominal count ใน Python โปรแกรม Pi
จับคู่จากช่วง `pitch_mm` ที่ไม่ทับกัน หรือใช้ `pitch_px` ชั่วคราวก่อน calibrate

HUD แบบชั่วคราวใช้ count-first hierarchy: `COUNT` ใหญ่ที่สุด, width/pitch/quality
เป็นบรรทัดรอง และ product/expected/QC เป็นบรรทัดเล็ก หากไม่พบกฎสินค้ายังคงแสดง
count ตามปกติพร้อม `PRODUCT NO_MATCH` โดยไม่ทิ้งผลวัด

- ตรวจ syntax ของไฟล์ Python และ JSON config/catalog ผ่านแล้ว
- ภาพตัวอย่างจริงภายใต้ ROI เต็มความสูงให้ผลเบื้องต้นประมาณ 37 เส้น,
  agreement 38%, สีดำ, span ประมาณ 278 px; ค่านี้ยังไม่ใช่ production ground
  truth และควรปรับแสง/ROI/algorithm ด้วยภาพที่นับด้วยมือ
- ภาพจำลองจากภาพเดียวกันที่หมุน +15°, -12°, +22°, +30° และ -30° ตรวจมุมชดเชย
  ได้ประมาณ -15°, +11°, -21.5°, -29.5° และ +30.5° ตามลำดับ
- ภาพเอียงจำลองดังกล่าวนับได้ประมาณ 36–39 เส้น โดย agreement ราว 55–75%
  ในกรณีทดสอบล่าสุด และ overlay ถูกวาดกลับเป็นแนวเอียงบนภาพจริง
- ตัวเลขข้างต้นเป็น smoke test ของ algorithm ไม่ใช่เกณฑ์รับรองความแม่นยำ
  สำหรับใช้งานผลิตจริง ต้องมีภาพจริงหลายชนิด หลายตำแหน่ง และ ground truth

## Raspberry Pi 5 RAM 2 GB แบบไม่มีพัดลม

เพิ่มโปรไฟล์ `rpi5-passive` เมื่อ 2026-09-02 โดย `auto` จะเลือกโปรไฟล์นี้เมื่อ
ตรวจพบ Raspberry Pi 5:

```text
OpenCV threads         = 1; process affinity = CPU 0-1
HDMI canvas            = 1024 x 600 / 10 FPS
camera request         = 2560 x 1440 MJPG / 15 FPS
ROI locator max side   = 1024 px; profile ใช้ ROI จากภาพเต็ม
burst/stable frames    = 5 / 3
analysis gap           = 120 ms ระหว่างผลแต่ละเฟรม
temperature warm/hot/critical = 65/70/75 C
minimum available RAM  = 512 MB
```

เป้าหมาย interpreter ปัจจุบันคือ standard CPython `>=3.13.5,<3.14` บน
Raspberry Pi OS 64-bit การ deploy จริงติดตั้ง `python3-numpy` และ
`python3-opencv` ลงระบบด้วย apt ผ่าน `install_pi5_system.sh` ไม่ใช้ virtual
environment, `sudo pip` หรือ `--break-system-packages` และห้ามใช้ OpenCV
headless เพราะ station ต้องแสดงผลเต็มจอ `run_pi5.sh` เรียก `/usr/bin/python3`
และบังคับผ่าน `pi5_preflight.py` ก่อนเริ่มโปรแกรม

การอ่านกล้องใช้ latest-frame buffer เพียงหนึ่งเฟรมและ V4L2 บน Linux โปรแกรม
ย่อภาพก่อนวาด HUD และเก็บเฉพาะผลวัด 5 ค่า ไม่เก็บภาพทั้ง burst ใน RAM เมื่อ
หลังยอมรับผลหนึ่ง burst โปรแกรมพัก worker จน scene เปลี่ยน CPU ร้อนจะลด display
FPS และหยุดเริ่มงานนับรอบใหม่เมื่อถึง 75°C หรือ RAM ว่างต่ำกว่า 512 MB

วันที่ 2026-09-02 ผู้ใช้รายงานว่า Pi 5 RAM 2 GB ไม่มีพัดลมดับทั้งเครื่องหลังรัน
`thread_counter_station.py` ระยะหนึ่งและต้องกดเปิดเอง ยังไม่ทราบสาเหตุจาก log;
อาการดับทั้งเครื่องชี้ไปที่ไฟเลี้ยง/ความร้อนมากกว่า OOM เพียงอย่างเดียว จึงปิด
legacy live mode บน Pi และกำหนดให้ใช้ `run_pi5.sh` เท่านั้น

ฮาร์ดแวร์ที่ยืนยันแล้วคืออะแดปเตอร์ 5V/3A และจอ 7 นิ้วรับไฟจาก Pi ร่วมกับกล้อง
USB จึงเพิ่ม power guard จาก `vcgencmd get_throttled`; เมื่อพบ current
undervoltage/throttling จะหยุด worker และลด display เหลือ 3 FPS

`run_pi5.sh` ค้นหา Wayland socket ใน `/run/user/<uid>/wayland-*` เพื่อให้สั่งจาก
SSH แล้วเปิดหน้าต่างบน HDMI desktop ได้ หากไม่มี Wayland/X11 session จะหยุดด้วย
ข้อความให้เปิด Desktop Autologin แทนการปล่อยให้ Qt `xcb` abort

กล้อง Pi live ตั้ง `power_line_frequency=1` ผ่าน `v4l2-ctl` ซึ่งหมายถึง
anti-flicker 50 Hz หาก UVC control นี้มีอยู่ เพื่อลด brightness flicker จากไฟ
บ้าน/LED; ความสว่างรวมถูกตัดออกจาก motion score ก่อนตรวจความนิ่งด้วย

ผลทดสอบบังคับโปรไฟล์ Pi บนเครื่องพัฒนา (ไม่ใช่ benchmark ของ Pi จริง) กับภาพ
ตัวอย่างเดิมได้ 37 เส้น, agreement 86%, width ประมาณ 277 px และเวลาประมวลผล
ประมาณ 190–230 ms เทียบกับ desktop profile ที่ได้ 37 เส้น, agreement 38% ในรอบ
ตรวจเดียวกัน ต้องทำ burn-in 30–60 นาทีบน Pi, กล้อง, จอ, ฮีตซิงก์ และ enclosure
จริงก่อนสรุป performance/temperature

วันที่ 2026-09-02 ทดสอบ dependency ที่ล็อกสำหรับ Pi (NumPy 2.2.6 และ OpenCV
4.12.0.88) บน Python 3.12 ของเครื่องพัฒนา: ภาพเดิมยังได้ 37 เส้น, agreement
86%, width 276.8 px และใช้เวลาประมาณ 261 ms การทดสอบนี้ยืนยัน regression ของ
dependency pair เท่านั้น ไม่ใช่ผลจาก Python 3.13.5 หรือ Raspberry Pi

## ข้อจำกัด/ความเสี่ยงที่ทราบ

- ROI เต็มความสูงมีพื้นหลังปะปน ทำให้ agreement ของภาพจริงต่ำกว่าการใช้ ROI
  เฉพาะแถบ ต้องแก้ด้วยแท่นและแสงก่อนผ่อน threshold
- Auto alignment เป็นการแก้ rotation ในระนาบภาพเท่านั้น ไม่แก้ perspective,
  ความโค้งของชิ้นงาน, เส้นทับซ้อน หรือ motion blur
- การนับ/ความกว้างยังไวต่อแสงสะท้อนจากซิลิโคน/แป้ง, focus, exposure, gain,
  white balance และพื้นหลังที่มีลายคล้ายเส้น
- `pixels_per_mm` ยังเป็น 0 จึงแสดงความกว้างเป็น pixel จนกว่าจะ calibrate ด้วย
  แผ่นอ้างอิงที่ทราบขนาด
- `products.json` ว่าง ผลจึงเป็น `PRODUCT NO_MATCH` แต่ยังแสดง COUNT จนกว่า
  ผู้ใช้จะเพิ่มช่วง pitch และ nominal count ของสินค้าจริง
- กล้อง 2K ใช้ MJPG และแยกการอ่าน frame จาก preview ใน utility กล้อง แต่
  ความละเอียด/FPS จริงต้องดูจากข้อความที่โปรแกรมพิมพ์และขึ้นกับ driver/USB 2.0
- Software thermal guard ไม่ทดแทนฮีตซิงก์ passive, airflow และแหล่งจ่ายไฟที่ดี
  และยังไม่มีผลวัดอุณหภูมิจาก Raspberry Pi 5 ตัวจริง
- ยังไม่ได้รัน regression/burn-in บน CPython 3.13.5 และ Pi 5 ตัวจริง การตรวจใน
  เครื่องพัฒนายืนยันได้เพียง syntax/logic และ dependency contract

## งานต่อที่ควรทำ

1. เก็บภาพจริงจากกล้อง USB ในหลายมุมเอียงและหลายผลิตภัณฑ์ พร้อมนับด้วยมือ
2. ปรับแสงแบบ diffuse backlight หรือ dark-field ให้ขอบแต่ละเส้นแยกชัด
3. ทดสอบ `count_axis`, `num_strips`, `edge_weight`, ROI และ `max_side` กับชุดภาพ
   ที่มี ground truth
4. ตั้งค่า `pixels_per_mm` จากภาพอ้างอิง แล้วเพิ่มกฎใน `products.json`
5. กำหนดเกณฑ์ acceptance เช่น count error, width error และ minimum agreement
   ก่อนนำไปใช้กับงาน production
