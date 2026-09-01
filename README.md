# Thread Counter Station

โปรแกรมต้นแบบสำหรับแท่นกล้อง USB ของโปรเจค Thread Counter Station ใช้
Python 3.10, OpenCV และ NumPy เท่านั้น ไม่มีโมเดล AI/ML โปรแกรมจะทำงานกับ
ภาพจากกล้องแบบคงที่ โดยใช้ ROI, การปรับ contrast, white/black top-hat,
gradient ตามแกนภาพ และการโหวตผลจากหลายแถบภาพเพื่อประเมินจำนวนเส้นยางที่เห็น
ซ้ำกันในแนวขวาง

## ติดตั้งและรัน

ติดตั้ง Python 3.10 ก่อน แล้วเปิด PowerShell ในโฟลเดอร์นี้:

```powershell
py -3.10 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

เปิดกล้องแบบเต็มจอ:

```powershell
.\.venv\Scripts\python.exe thread_counter_station.py
```

ค่าเริ่มต้นใน `station_config.json` ใช้ camera index `1` ซึ่งโดยทั่วไปเป็น
กล้อง USB ภายนอก ส่วนกล้อง laptop มักเป็น index `0` หาก Windows จัดลำดับไม่ตรง
ให้ตรวจสอบด้วย:

```powershell
.\.venv\Scripts\python.exe camera_capture_test.py --list-cameras
```

แล้วเลือก index ของกล้อง USB เช่น:

```powershell
.\.venv\Scripts\python.exe camera_capture_test.py --camera 1
```

## โปรแกรมทดสอบรับภาพจากกล้อง

ใช้ `camera_capture_test.py` เมื่อต้องการดูภาพจากกล้องและเก็บภาพดิบสำหรับ
ทดสอบ โดยไม่เรียกอัลกอริทึมนับเส้น:

```powershell
.\.venv\Scripts\python.exe camera_capture_test.py
```

กด `SPACE` หรือ `S` เพื่อบันทึกภาพ JPG ลงโฟลเดอร์ `image`, กด `F` เพื่อสลับ
เต็มจอ/หน้าต่าง และกด `Q` หรือ `ESC` เพื่อออก หากต้องการบันทึก ROI เพิ่มด้วย
ให้ใช้:

```powershell
.\.venv\Scripts\python.exe camera_capture_test.py --save-roi
```

โปรแกรมยังคงรับและบันทึกภาพเต็มความละเอียด 2K แต่ย่อเฉพาะภาพ preview เป็น
ค่าเริ่มต้น 1600 พิกเซลเพื่อให้แสดงผลลื่นขึ้น สามารถปรับด้วย
`--preview-width 1920` หรือแก้ `capture.preview_width` ได้
ภาพดิบ 2K จะถูกอ่านใน thread แยกจาก UI และ HUD จะแสดง `CAP` กับ `DISPLAY`
FPS ที่วัดได้จริง เพื่อแยกปัญหาระหว่างกล้อง/USB กับการแสดงผล

ใช้ `--camera 1`, `--width`, `--height`, `--fps`, `--windowed` หรือ
`--save-dir <folder>` เพื่อ override ค่าเฉพาะการทดสอบครั้งนั้น

ทดสอบกับภาพโดยไม่เปิดหน้าต่าง:

```powershell
.\.venv\Scripts\python.exe thread_counter_station.py `
  --image samples\white_band.jpg --no-display --save
```

ทางลัด `thread_counter.py` เรียกโปรแกรมเดียวกันได้เช่นกัน

```text
SPACE  จับภาพต่อเนื่องสั้น ๆ แล้วเลือกเฟรมที่คมที่สุดเพื่อประมวลผล
R      ล้าง calibration ที่ปรับตามภาพล่าสุด
S      บันทึกภาพ overlay และไฟล์ JSON ผลลัพธ์
Q/ESC  ออกจากโปรแกรม
```

## ตั้งค่า ROI และการวัด

แก้ไฟล์ `station_config.json`:

- `processing.roi` เป็นสัดส่วนของภาพเต็มจอ (`x`, `y`, `width`, `height`) ช่วง
  0 ถึง 1 ต้องวางแท่น/เส้นยางให้แนวเส้นที่ต้องนับอยู่ในกรอบนี้
- ค่าเริ่มต้นปัจจุบันใช้ ROI กึ่งกลางภาพกว้าง `0.40` (`x=0.30`) และสูงเต็มภาพ
  (`y=0`, `height=1.0`) ตามการทดลองล่าสุดกับภาพตัวอย่าง
- `processing.max_side` เป็นขนาดภาพสูงสุดที่ส่งเข้า algorithm ถ้าเพิ่มจะได้
  รายละเอียดมากขึ้นแต่ใช้เวลาประมวลผลมากขึ้น
- `processing.count_axis` เป็นแกนที่ใช้เรียงเส้นซ้ำ: `y` สำหรับเส้นแนวนอนแบบ
  ภาพตัวอย่างนี้ และ `x` สำหรับเส้นแนวตั้ง
- `alignment.mode` ตั้งเป็น `auto` เพื่อให้โปรแกรมตรวจมุมเอียงจากเส้นขอบด้วย
  Hough line และตรวจความสม่ำเสมอของลายซ้ำเป็น fallback แล้วหมุน ROI ชั่วคราว
  ก่อนนับ ค่า `alignment.max_tilt_deg` (ค่าเริ่มต้น ±45 องศา) เป็นขอบเขตการค้นหา
  จากนั้น overlay จะถูกหมุนกลับไปวาดบนภาพจริง ถ้าต้องการปิดใช้ `none` หรือกำหนด
  มุมชดเชยเองด้วย `manual` และใส่ค่า `alignment.angle_deg`
- `processing.edge_weight` ผสานความเข้มจาก top-hat กับ gradient ตามแกนที่นับ
  ค่ามากเหมาะเมื่อเห็นขอบชัดกว่าความแตกต่างของสี
- `processing.polarity` ใช้ `auto`, `white` หรือ `black` หากรู้ว่าวัตถุสว่างหรือ
  มืดกว่าพื้นหลัง การระบุเองช่วยให้ calibration นิ่งขึ้น
- `processing.pixels_per_mm` ให้ใส่ค่า pixel ต่อมิลลิเมตรจากการถ่ายแผ่นอ้างอิง
  ขนาดที่รู้แน่นอน ถ้าเป็น `0` จะแสดงความกว้างเป็นพิกเซลอย่างเดียว
- `color.white_l_min` และ `color.black_l_max` เป็น threshold ค่า lightness
  ของ LAB ควรปรับจากภาพจริงหลังล็อกแสงและ white balance แล้ว

สูตรวัดความกว้างคือ `width_mm = width_px / pixels_per_mm` การวัดในรุ่นนี้เป็น
ความกว้างตามแกนการนับภายใน ROI เช่นภาพตัวอย่างใช้แกน Y จึงวัดความสูงของแถบ
เส้นยางในภาพ ระบบ auto alignment ช่วยแก้กรณีเส้นยางเอียงได้ แต่ยังควรจัดแสง
และวางชิ้นงานให้อยู่ใน ROI เพื่อให้การตรวจมุมและการนับมีความเสถียร
ถ้าใช้ `manual` ค่า `angle_deg` คือมุมที่ใช้หมุนแก้ ROI ไม่ใช่มุมเอียงของชิ้นงาน
โดยตรง เช่นภาพที่เอียงไปทางหนึ่ง 15 องศาอาจต้องใส่ `-15` องศา

## กำหนดชนิดสินค้า

แก้ `products.json` ตามชนิดสินค้าจริง โดยเรียงกฎจากเฉพาะเจาะจงไปกว้างที่สุด
กฎแรกที่ตรงจะถูกใช้:

```json
{
  "products": [
    {
      "id": "BRIEF_WHITE_18_32MM",
      "name": "BRIEF_WHITE_18_32MM",
      "colors": ["white"],
      "count_min": 18,
      "count_max": 18,
      "width_mm_min": 31.5,
      "width_mm_max": 32.5
    },
    {
      "id": "BRIEF_BLACK_18_32MM",
      "name": "BRIEF_BLACK_18_32MM",
      "colors": ["black"],
      "count_min": 18,
      "count_max": 18,
      "width_mm_min": 31.5,
      "width_mm_max": 32.5
    }
  ]
}
```

ถ้ากฎมี `width_mm_min` หรือ `width_mm_max` ต้องตั้ง `pixels_per_mm` ก่อน
มิฉะนั้นกฎนั้นจะไม่ match เพื่อป้องกันการระบุชนิดสินค้าผิดจากหน่วยที่ยังไม่ได้
calibrate

## แนวทางแท่นและการจัดแสง

กล้อง NEOCoolcam NE-82534053 เป็นกล้อง UVC ที่ใช้เลนส์ manual 2.8--12 mm:

1. ยึดกล้องให้ตั้งฉากกับชิ้นงานและล็อก zoom/focus ด้วยกาวหรือ ring lock หลัง
   ตั้งคมแล้ว ระยะติดตั้งจริงควรเลือกให้เส้นยางเต็มความกว้าง ROI แต่ไม่ชิดขอบ
2. ใช้ backlight แบบแผ่น LED diffuse เมื่อเส้นยางต้องการ silhouette/ขอบชัด หรือ
   ใช้ dark-field light เฉียงต่ำเมื่อผิวมี texture และต้องการให้ขอบแต่ละเส้นเด่น
3. ใส่ diffuser และฉากบังแสงภายนอก ลดแสงสะท้อนจากซิลิโคน/แป้ง อย่าให้ hotspot
   ตกตรงกลางเส้นยาง
4. หลังได้แสงแล้ว ให้ล็อก exposure, gain และ white balance ถ้า driver รองรับ
   เพราะ threshold สีขาว/ดำและความแรงของขอบไวต่อการเปลี่ยนแสง
5. USB 2.0 อาจรับภาพความละเอียดสูงแบบไม่บีบอัดไม่ไหว โค้ดจึงขอ MJPG ก่อนและ
   ตั้งค่าเริ่มต้น 2560x1440; ตรวจสอบความละเอียดจริงที่พิมพ์ใน console ถ้าภาพ
   กระตุกให้ลด `camera.width/height` เป็น 1280x720
6. ใช้ภาพตัวอย่างจริงอย่างน้อย 20--30 ภาพต่อชนิดสินค้า ทดสอบตำแหน่งที่ต่างกัน
   และทั้งเส้นยางดำ/ขาว ก่อนนำไปกำหนดช่วง `count`/`width_mm` ใน catalog

## ข้อจำกัดของต้นแบบ

อัลกอริทึมนี้เหมาะกับเส้น/ขอบที่ขนานกันและชิ้นงานอยู่ในระนาบคงที่ ถ้ามีการ
เอียงมาก, เส้นทับซ้อน, เงาสะท้อนแรง หรือพื้นหลังมีลายคล้ายเส้น อาจได้ผลลัพธ์
`NO RESULT` หรือค่า agreement ต่ำ ควรแก้ด้วยแท่น, ROI และแสงก่อนปรับ threshold
ในโค้ด ผลลัพธ์ทุกครั้งจะบอก `agreement` และมีเส้น overlay เพื่อให้ตรวจสอบภาพ
ที่นับได้ก่อนใช้เป็นข้อมูล production

ไฟล์ `thread_counter_original.py` เป็นโค้ดอ้างอิงเดิมที่มี SciPy ส่วนไฟล์
`thread_counter_station.py` เป็น entry point ที่ปรับสำหรับสถานีนี้และไม่ใช้ SciPy

รายละเอียดจากภาพตัวอย่างจริงและค่าตั้งต้นที่ทดลองแล้วอยู่ใน
`docs/IMAGE-001-observation.md` โดยภาพนี้ใช้เส้นแนวนอนและ `count_axis: "y"`
