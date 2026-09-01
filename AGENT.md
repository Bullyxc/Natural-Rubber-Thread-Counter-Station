# AGENT.md — Working Rules for Thread Counter Station

เอกสารนี้ใช้เป็นกติกาสำหรับ agent/ผู้พัฒนาที่กลับมาทำงานต่อในโปรเจค
Thread Counter Station

## ก่อนเริ่มงานทุกครั้ง

1. อ่าน `CONTEXT.md` และ `README.md` ให้ครบส่วนที่เกี่ยวข้อง
2. ตรวจ `station_config.json`, `requirements.txt` และสถานะไฟล์ในโฟลเดอร์
3. อ่าน `docs/ADR-001-classical-vision-station.md` ก่อนเปลี่ยนแนวทางหลักของระบบ
4. ตรวจโค้ดจริงก่อนเชื่อบันทึกเก่า เพราะค่าหรือผลทดสอบอาจเปลี่ยนไปแล้ว
5. หากงานเกี่ยวกับภาพ ให้ดูภาพใน `image/` และผล overlay ที่เกี่ยวข้องก่อนปรับ
   algorithm

## ขอบเขตที่ต้องรักษา

- โปรแกรมหลักต้องรองรับ Python 3.10
- runtime หลักใช้ OpenCV และ NumPy ตาม `requirements.txt`
- ห้ามเพิ่ม AI/ML model, neural network, object detector หรือ dependency ของ
  model เว้นแต่ผู้ใช้เปลี่ยนข้อกำหนดอย่างชัดเจน
- ต้องรักษาการทำงานกับกล้อง USB ภายนอก ค่าเริ่มต้น index 1 และการขอภาพ 2K
  2560×1440 ที่ 30 FPS เมื่อ driver รองรับ
- ต้องรักษาการแสดงผล overlay, count, agreement, width, color, product และ
  alignment บนภาพที่ตรวจสอบย้อนกลับได้
- การวัดหน่วย mm ต้องเกิดขึ้นเมื่อ `pixels_per_mm` ถูก calibrate แล้วเท่านั้น
- `products.json` ต้องเป็นกฎที่ผู้ใช้แก้ไขได้ ไม่ hard-code ชนิดสินค้าจริงลงใน
  Python

## แนวทางแก้ไขโค้ด

- ใช้ `thread_counter_station.py` เป็น entry point หลัก
- ใช้ `camera_capture_test.py` เมื่อต้องตรวจกล้อง/บันทึกภาพ โดยไม่ปะปนกับ
  algorithm นับ
- รักษาโครงสร้าง classical CV ที่อธิบายได้: ROI, grayscale/contrast,
  top-hat, gradient, profile, strip voting, Hough/geometry และ rule catalog
- ถ้าแก้การหมุนภาพ ต้องแก้ทั้งขั้นตอนประมวลผลและการแปลง overlay กลับภาพต้นฉบับ
- ถ้าแก้ calibration หรือแกนการนับ ต้องตรวจว่าความหมายของ `x_left`, `x_right`,
  `consensus_xs`, `width_px` และ `count_axis` ยังสอดคล้องกัน
- อย่าทำให้ preview ต้องลดความละเอียดของภาพที่บันทึก: ควรย่อเฉพาะ display copy
- ใช้ `apply_patch` สำหรับการแก้ไฟล์แบบเจาะจง และรักษาการเปลี่ยนแปลงเดิมของผู้ใช้
- หลีกเลี่ยงการแก้ไฟล์ผลลัพธ์หรือการลบข้อมูลที่ผู้ใช้สร้างเองโดยไม่จำเป็น

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

ตรวจกล้อง USB:

```powershell
.\.venv\Scripts\python.exe camera_capture_test.py --list-cameras
.\.venv\Scripts\python.exe camera_capture_test.py --camera 1
```

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

