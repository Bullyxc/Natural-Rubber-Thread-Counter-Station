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

ข้อกำหนดสำคัญ: ต้องรันด้วย Python 3.10 บนคอมพิวเตอร์, ไม่ใช้โมเดล AI/ML,
และควรใช้เฉพาะ classical image-processing ที่ตรวจสอบ overlay ได้

## แหล่งอ้างอิงหลัก

อ่านตามลำดับนี้เมื่อกลับมาทำงาน:

1. `AGENT.md` — กติกาการทำงานกับ repository นี้
2. `CONTEXT.md` — สถานะและสมมติฐานล่าสุดของโปรเจค
3. `README.md` — วิธีติดตั้ง รัน ใช้งาน และตั้งค่า
4. `station_config.json` — ค่าปฏิบัติการที่ใช้จริง
5. `docs/ADR-001-classical-vision-station.md` — เหตุผลเชิงสถาปัตยกรรม
6. `docs/IMAGE-001-observation.md` — ข้อสังเกตจากภาพตัวอย่างจริง
7. `thread_counter_station.py` / `camera_stream.py` — implementation ปัจจุบัน

## โครงสร้างและ entry points

- `thread_counter_station.py` — โปรแกรมหลักสำหรับ live station และประมวลผลภาพ
  เดี่ยว ใช้ OpenCV + NumPy, แสดงผลเต็มจอได้ และบันทึกภาพ overlay/JSON
- `thread_counter.py` — wrapper ที่เรียกโปรแกรมหลัก
- `camera_capture_test.py` — โปรแกรมแยกสำหรับ preview กล้องและกดบันทึกภาพดิบ
  โดยไม่เรียกอัลกอริทึมนับ
- `camera_stream.py` — backend กล้อง UVC, การขอ MJPG, latest-frame reader และ
  การย่อเฉพาะภาพ preview เพื่อให้ UI ลื่นขึ้น
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

## ข้อจำกัด/ความเสี่ยงที่ทราบ

- ROI เต็มความสูงมีพื้นหลังปะปน ทำให้ agreement ของภาพจริงต่ำกว่าการใช้ ROI
  เฉพาะแถบ ต้องแก้ด้วยแท่นและแสงก่อนผ่อน threshold
- Auto alignment เป็นการแก้ rotation ในระนาบภาพเท่านั้น ไม่แก้ perspective,
  ความโค้งของชิ้นงาน, เส้นทับซ้อน หรือ motion blur
- การนับ/ความกว้างยังไวต่อแสงสะท้อนจากซิลิโคน/แป้ง, focus, exposure, gain,
  white balance และพื้นหลังที่มีลายคล้ายเส้น
- `pixels_per_mm` ยังเป็น 0 จึงแสดงความกว้างเป็น pixel จนกว่าจะ calibrate ด้วย
  แผ่นอ้างอิงที่ทราบขนาด
- `products.json` ว่าง ผลจึงเป็น `UNMATCHED` จนกว่าผู้ใช้จะเพิ่มกฎสินค้าจริง
- กล้อง 2K ใช้ MJPG และแยกการอ่าน frame จาก preview ใน utility กล้อง แต่
  ความละเอียด/FPS จริงต้องดูจากข้อความที่โปรแกรมพิมพ์และขึ้นกับ driver/USB 2.0

## งานต่อที่ควรทำ

1. เก็บภาพจริงจากกล้อง USB ในหลายมุมเอียงและหลายผลิตภัณฑ์ พร้อมนับด้วยมือ
2. ปรับแสงแบบ diffuse backlight หรือ dark-field ให้ขอบแต่ละเส้นแยกชัด
3. ทดสอบ `count_axis`, `num_strips`, `edge_weight`, ROI และ `max_side` กับชุดภาพ
   ที่มี ground truth
4. ตั้งค่า `pixels_per_mm` จากภาพอ้างอิง แล้วเพิ่มกฎใน `products.json`
5. กำหนดเกณฑ์ acceptance เช่น count error, width error และ minimum agreement
   ก่อนนำไปใช้กับงาน production

