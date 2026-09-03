# AGENT.md — Working Rules for Thread Counter Station

เอกสารนี้ใช้เป็นกติกาสำหรับ agent/ผู้พัฒนาที่กลับมาทำงานต่อในโปรเจค
Thread Counter Station

## ก่อนเริ่มงานทุกครั้ง

1. อ่าน `CONTEXT.md` และ `README.md` ให้ครบส่วนที่เกี่ยวข้อง
2. ตรวจ `station_config.json`, `requirements.txt` และสถานะไฟล์ในโฟลเดอร์
   รวมถึง `.vscode/sftp.json` หากงานเกี่ยวกับการ deploy ไป Pi
3. อ่าน `docs/ADR-001-classical-vision-station.md` ก่อนเปลี่ยนแนวทางหลักของระบบ,
   อ่าน `docs/ADR-002-rpi5-passive-runtime.md` ก่อนเปลี่ยนข้อจำกัด Pi และอ่าน
   `docs/ADR-003-python-313-pi5.md` ก่อนเปลี่ยน interpreter/dependency บน Pi
   และอ่าน `docs/ADR-004-dual-background-phase-one.md` กับ `docs/glossary.md`
   ก่อนแก้ตัวนับพื้นหลังสองสีหรือ live burst ใหม่
4. ตรวจโค้ดจริงก่อนเชื่อบันทึกเก่า เพราะค่าหรือผลทดสอบอาจเปลี่ยนไปแล้ว
5. หากงานเกี่ยวกับภาพ ให้ดูภาพใน `image/` และผล overlay ที่เกี่ยวข้องก่อนปรับ
   algorithm

## ขอบเขตที่ต้องรักษา

- โปรแกรมหลักต้องรองรับ Python 3.10 บนคอมพิวเตอร์เดิม และ standard CPython
  `>=3.13.5,<3.14` บน Raspberry Pi 5 64-bit
- ไม่รองรับ free-threaded CPython `3.13t` จนกว่า NumPy/OpenCV และ workload นี้จะ
  ผ่านการทดสอบบน Pi จริง
- runtime หลักใช้ OpenCV และ NumPy ตาม `requirements.txt`
- ห้ามเพิ่ม AI/ML model, neural network, object detector หรือ dependency ของ
  model เว้นแต่ผู้ใช้เปลี่ยนข้อกำหนดอย่างชัดเจน
- ต้องรักษาการทำงานกับกล้อง USB ภายนอก บน Pi ใช้ค่าเริ่มต้น index 0 และการขอ
  ภาพ 2K 2560×1440 ที่ 15 FPS เมื่อ driver รองรับ
- ต้องรักษาการแสดงผล overlay, count, agreement, width, color, product และ
  alignment บนภาพที่ตรวจสอบย้อนกลับได้
- การวัดหน่วย mm ต้องเกิดขึ้นเมื่อ `pixels_per_mm` ถูก calibrate แล้วเท่านั้น
- `products.json` ต้องเป็นกฎที่ผู้ใช้แก้ไขได้ ไม่ hard-code ชนิดสินค้าจริงลงใน
  Python

## แนวทางแก้ไขโค้ด

- ใช้ `pi5_usb_hdmi_station.py` เป็น entry point หลักบน Pi 5 + จอ 1024×600;
  `thread_counter_station.py` เป็นรุ่นเดิมสำหรับภาพเดี่ยว/desktop
- ใช้ `camera_capture_test.py` เมื่อต้องตรวจกล้อง/บันทึกภาพ โดยไม่ปะปนกับ
  algorithm นับ
- รักษาโครงสร้าง classical CV ที่อธิบายได้: ROI, grayscale/contrast,
  top-hat, gradient, profile, strip voting, Hough/geometry และ rule catalog
- ถ้าแก้การหมุนภาพ ต้องแก้ทั้งขั้นตอนประมวลผลและการแปลง overlay กลับภาพต้นฉบับ
- ถ้าแก้ calibration หรือแกนการนับ ต้องตรวจว่าความหมายของ `x_left`, `x_right`,
  `consensus_xs`, `width_px` และ `count_axis` ยังสอดคล้องกัน
- อย่าทำให้ preview ต้องลดความละเอียดของภาพที่บันทึก: ควรย่อเฉพาะ display copy
- บน Pi ต้องรักษา latest-frame buffer แบบไม่สะสม queue, thermal/RAM guard และ
  ห้ามเพิ่ม polling loop ที่หมุน CPU ขณะรอเฟรม
- ห้ามเปิด legacy live mode ของ `thread_counter_station.py` บน Pi 5 ให้ใช้
  `run_pi5.sh` เท่านั้น และต้องคง 5V/3A safe profile: 1 OpenCV thread,
  CPU 0–1, HDMI 10 FPS, กล้อง 2K/15 FPS, analysis gap 120 ms, หยุดประมวลผล
  ที่ 75°C/RAM ว่างต่ำกว่า 512 MB/เมื่อพบ current power-limit และพักหลังจบหนึ่ง
  burst จนกว่า scene จะเปลี่ยน
- บน Pi ให้ติดตั้ง Python/NumPy/OpenCV ลงระบบด้วย apt ผ่าน
  `install_pi5_system.sh` ห้ามใช้ virtual environment, `sudo pip`,
  `--break-system-packages` หรือ OpenCV แบบ headless
- อย่าลด `alignment_max_side` ของ Pi โดยไม่ทดสอบภาพเอียงหลายมุม ค่า 720–900 px
  เคยทำให้ประมาณมุมผิดใน smoke test ขณะที่ 1200 px ให้ผลเสถียรกว่า
- ใช้ `apply_patch` สำหรับการแก้ไฟล์แบบเจาะจง และรักษาการเปลี่ยนแปลงเดิมของผู้ใช้
- หลีกเลี่ยงการแก้ไฟล์ผลลัพธ์หรือการลบข้อมูลที่ผู้ใช้สร้างเองโดยไม่จำเป็น
- `.vscode/sftp.json` เป็นค่าการเชื่อมต่อเฉพาะเครื่อง ห้ามใส่ password หรือ
  private key ลงใน repository

## การตรวจสอบขั้นต่ำหลังแก้

เปิด PowerShell ที่โฟลเดอร์โปรเจคแล้วรันด้วย Python 3.10:

```powershell
py -3.10 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

ตรวจ syntax:

```powershell
Get-ChildItem -File -Filter '*.py' | ForEach-Object {
  .\.venv\Scripts\python.exe -W error -m py_compile $_.FullName
}
```

ตรวจภาพจริงแบบไม่เปิดหน้าต่าง:

```powershell
.\.venv\Scripts\python.exe thread_counter_station.py `
  --image image\WIN_20260730_04_26_07_Pro.jpg --no-display
```

ตรวจ regression พื้นหลังสองสีและ ground truth:

```powershell
.\.venv\Scripts\python.exe evaluate_reference_images.py
```

คำสั่งนี้ต้องดูทั้ง count, pitch, width, quality, source zone และไฟล์ overlay ใน
`results/reference/` ปัจจุบัน baseline ที่ต้องผ่านคือ `40/40 QC PASS`,
`37/40 QC FAIL` และ `40/40 QC PASS` ตามลำดับ

ตรวจ logic ของ live station โดยไม่เปิดกล้อง:

```powershell
.\.venv\Scripts\python.exe pi5_usb_hdmi_station.py --self-test
```

ตรวจกล้อง USB:

```powershell
.\.venv\Scripts\python.exe camera_capture_test.py --list-cameras
.\.venv\Scripts\python.exe camera_capture_test.py --camera 1
```

ตรวจ profile Pi บนเครื่องพัฒนา:

```powershell
.\.venv\Scripts\python.exe thread_counter_station.py `
  --runtime-profile rpi5-passive `
  --image image\WIN_20260730_04_26_07_Pro.jpg --no-display
```

ผลเวลาจากคำสั่งนี้เป็นเพียง regression test ของ profile ห้ามรายงานเป็นความเร็ว
ของ Raspberry Pi จนกว่าจะรันบนฮาร์ดแวร์จริง

ตรวจ environment จริงบน Raspberry Pi ก่อนเปิด station:

```bash
./install_pi5_system.sh
/usr/bin/python3 pi5_preflight.py
./run_pi5.sh
```

`pi5_preflight.py` ต้องผ่านด้วย Python 3.13.5+, Python/OS 64-bit, NumPy 2.1+,
OpenCV 4.8+ ที่มี GUI backend และมี OpenCV distribution เพียงชนิดเดียว

ถ้าแก้ alignment หรือ overlay ให้ทดสอบอย่างน้อย:

- ภาพปกติที่ไม่เอียง
- ภาพเอียงทั้งทิศบวกและทิศลบ
- ภาพที่ `alignment.mode=none` และ `manual` เมื่อเกี่ยวข้อง
- ตรวจว่าเส้น overlay อยู่บนเส้นยางจริง ไม่ใช่แค่ค่า count ดูสมเหตุผล

## การอ่านผลและการตัดสินใจ

- อย่าใช้ count เพียงตัวเดียวเป็นหลักฐานว่าระบบถูกต้อง ให้ดู `agreement`,
  `pitch`, `width`, `color`, ภาพ overlay และภาพต้นฉบับร่วมกัน
- `UNMATCHED` เป็นผลที่ปลอดภัยเมื่อไม่มี rule สินค้าที่ตรง ไม่ควรเดาชนิดสินค้า
- agreement ต่ำหรือ `NO RESULT` ให้ตรวจ focus, exposure, lighting, ROI,
  direction และพื้นหลังก่อนเพิ่มความซับซ้อนของ algorithm
- ผลจากภาพตัวอย่างเดิมและภาพจำลองเอียงใน `CONTEXT.md` เป็น smoke test เท่านั้น
  ห้ามอ้างเป็น production accuracy
- หากต้องเปลี่ยนค่า default เช่น ROI, count axis, alignment หรือกล้อง ต้อง
  อัปเดต `station_config.json`, `README.md` และ `CONTEXT.md` ให้สอดคล้องกัน

## การบันทึกบริบทเมื่อจบงาน

เมื่อมีการเปลี่ยนแปลงที่มีสาระสำคัญ ให้ปรับ `CONTEXT.md` โดยบันทึก:

- วันที่และสิ่งที่เปลี่ยน
- ไฟล์หลักที่แก้
- คำสั่ง/ภาพที่ใช้ตรวจ
- ผลทดสอบและข้อจำกัดที่ยังเหลือ
- งานถัดไปที่ควรทำ

หากเอกสารกับโค้ดไม่ตรงกัน ให้แก้เอกสารในรอบเดียวกัน หรือระบุความไม่ตรงกัน
อย่างชัดเจนในคำตอบสุดท้าย เพื่อให้ agent คนถัดไปไม่เริ่มจากสมมติฐานเก่า
