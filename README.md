# Thread Counter Station

โปรแกรมต้นแบบสำหรับแท่นกล้อง USB ของโปรเจค Thread Counter Station ใช้
Python 3.10–3.13, OpenCV และ NumPy เท่านั้น ไม่มีโมเดล AI/ML โปรแกรมจะทำงานกับ
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

## Raspberry Pi 5 RAM 2 GB แบบไม่มีพัดลม

เป้าหมายบน Pi คือ Raspberry Pi OS 64-bit, standard CPython 3.13.5 (ไม่ใช่รุ่น
free-threaded `3.13t`) และ runtime profile `rpi5-passive` ซึ่งจะถูกเลือกอัตโนมัติ
เมื่อพบ Raspberry Pi 5 การติดตั้งบน Pi ใช้ Python, OpenCV และ NumPy ของระบบ
โดยตรง ไม่สร้าง virtual environment และไม่ใช้ pip:

ฮาร์ดแวร์ปัจจุบันใช้อะแดปเตอร์ 5V/3A และจอ 7 นิ้วรับไฟจาก Pi จึงใช้ low-power
profile บังคับ: คงความละเอียด 2K แต่ลดกล้องเป็น 15 FPS, จอเป็น 10 FPS,
OpenCV 1 thread และจำกัดโปรเซสไว้ที่ CPU 0–1 เพื่อลดกระแสพุ่ง
กล้องจะตั้ง UVC `power_line_frequency` เป็น 50 Hz อัตโนมัติเพื่อลดภาพสว่าง–มืด
สลับจากไฟบ้าน/LED ในไทย หากกล้องไม่รองรับ โปรแกรมจะแจ้ง warning แต่ยังทำงานต่อ

```bash
chmod +x install_pi5_system.sh run_pi5.sh
./install_pi5_system.sh
./run_pi5.sh
```

สคริปต์รองรับการสั่งผ่าน SSH โดยค้นหา Wayland session ของ desktop ที่กำลังแสดง
บน HDMI แล้วตั้ง `XDG_RUNTIME_DIR`, `WAYLAND_DISPLAY` และ Qt backend ให้อัตโนมัติ
หากขึ้น `No graphical desktop session` ให้เปิด desktop auto-login ด้วย
`sudo raspi-config` แล้ว reboot; โปรแกรม OpenCV ไม่สามารถวาดบน HDMI ได้ถ้ายัง
บูตอยู่ใน console mode และไม่มี graphical session

สคริปต์ติดตั้งเรียก `apt` เพื่อลง `python3`, `python3-numpy`, `python3-opencv` และ
`v4l-utils` ลงในระบบ Raspberry Pi OS จากนั้นตรวจ environment ให้อัตโนมัติ
หากต้องการติดตั้งด้วยคำสั่งเองให้ใช้:

```bash
sudo apt update
sudo apt install -y python3 python3-numpy python3-opencv v4l-utils
/usr/bin/python3 pi5_preflight.py
```

`/usr/bin/python3 --version` ต้องเป็น 3.13.5 หรือ patch ที่ใหม่กว่าในตระกูล 3.13
ห้ามใช้ `sudo pip`, `--break-system-packages` หรือ OpenCV แบบ headless เพราะอาจ
ชนกับแพ็กเกจของระบบและแบบ headless ไม่สามารถเปิดหน้าต่าง station เต็มจอได้
รันโปรแกรมตรงด้วย system Python ได้ดังนี้:

```bash
/usr/bin/python3 pi5_usb_hdmi_station.py --runtime-profile rpi5-passive
```

`run_pi5.sh` ใช้ `/usr/bin/python3` และเรียก `pi5_preflight.py` อัตโนมัติก่อนเปิดโปรแกรม เพื่อตรวจ Python,
64-bit, NumPy, OpenCV GUI, แพ็กเกจ OpenCV ซ้ำ และอุปกรณ์ `/dev/video*` ถ้าตรวจ
ส่วนที่จำเป็นไม่ผ่าน โปรแกรมจะหยุดพร้อมข้อความสาเหตุแทนการเปิด station ต่อ

โปรแกรม Pi เปิดกล้อง USB แบบ V4L2/MJPG ที่ 2560×1440, ขอ 15 FPS และแสดง
หน้าต่างเต็มจอขนาด 1024×600 สำหรับจอ HDMI 7 นิ้ว จากนั้นเริ่มตรวจอัตโนมัติ
โดยไม่ต้องกดปุ่ม ใช้ `Q` หรือ `ESC` เฉพาะตอนบำรุงรักษาเพื่อออกจากโปรแกรม
ถ้ากล้องไม่ได้อยู่ที่ `/dev/video0` ให้ระบุ index เช่น:

```bash
./run_pi5.sh --camera 2
```

## ส่งไฟล์จาก VS Code ไป Raspberry Pi ด้วย SFTP

ในโปรเจคมีไฟล์ `.vscode/sftp.json` เตรียมไว้แล้ว ให้ติดตั้ง extension `SFTP`
(Natizyskunk) ใน VS Code
จากนั้นแก้ค่า `host` เป็น IP หรือ hostname ของ Pi เช่น
`192.168.1.50` แล้วกด `Ctrl+S` ไฟล์ที่แก้จะถูกอัปโหลดไปที่
`/home/rpi5/NRTcounter` อัตโนมัติ ค่า `username` คือ `rpi5` และใช้ SSH port
`22` โดยไม่เก็บ password ไว้ในไฟล์ config; extension จะถาม password ตอนเชื่อมต่อ
ครั้งแรก

บน Pi ต้องเปิด SSH และสร้างโฟลเดอร์ปลายทางก่อน:

```bash
sudo apt install -y openssh-server
sudo systemctl enable --now ssh
sudo mkdir -p /home/rpi5/NRTcounter
sudo chown -R rpi5:rpi5 /home/rpi5/NRTcounter
hostname -I
```

นำ IP ที่ได้ไปใส่ใน `host` แล้วทดสอบจาก PowerShell:

```powershell
ssh rpi5@<PI5_IP>
```

ครั้งแรกให้ใช้คำสั่ง `SFTP: Upload Project` จาก Command Palette เพื่อส่งไฟล์
ทั้งโปรเจคขึ้นไปก่อน หลังจากนั้นการกด `Ctrl+S` จะส่งเฉพาะไฟล์ที่กำลังบันทึก
ไฟล์ `.vscode`, `.git`, `image` และ `results` ถูกตั้งให้ไม่อัปโหลด

ถ้ากล้อง USB ไม่ใช่ index `1` ให้ตรวจและ override ก่อน โดยบน Pi กล้องตัวแรก
มักเป็น `/dev/video0` หรือ index `0`:

```bash
/usr/bin/python3 camera_capture_test.py --list-cameras
/usr/bin/python3 camera_capture_test.py --camera 0 \
  --runtime-profile rpi5-passive
```

โปรแกรม Pi ไม่ลดภาพดิบจากกล้อง: ยังคงขอ 2560x1440 MJPG 15 FPS แต่ย่อสำเนา
ที่ใช้แสดงผลเป็น 1024×600/10 FPS ตัวค้นหา seam และ Dynamic ROI ใช้ภาพย่อ
ด้านยาวสูงสุด 1024 px แล้วกลับไปสร้าง profile บน ROI ของภาพเต็ม ใช้ burst
5 เฟรม, IQR 1.5× และ median ตามกติกาที่ตกลงไว้ พร้อม OpenCV 1 thread และ
เว้น 120 ms ระหว่างเฟรมวิเคราะห์ หลังได้ผลแล้วจะพักจนตรวจพบว่าชิ้นงานขยับ
เพื่อลดความร้อนและกระแสไฟสูงสุด

HUD จะแสดง `CPU` และ `RAM` เมื่อรันบน Pi ถ้าอุณหภูมิถึง 70°C โปรแกรมจะลด
preview ถ้าถึง 75°C หรือ RAM ว่างต่ำกว่า 512 MB จะไม่เริ่มการวัดรอบใหม่จนกว่า
จะกลับมาปลอดภัย ค่าเหล่านี้แก้ได้ในส่วน
`runtime.rpi5_passive` ของ `station_config.json`
โปรแกรมอ่าน `vcgencmd get_throttled` ทุกหนึ่งวินาที หากพบไฟตก/ถูก throttle
ในขณะนั้นจะหยุดนับและลดจอเหลือ 3 FPS จนสถานะกลับมาปกติ

ห้ามใช้ `thread_counter_station.py` เปิด live camera บน Pi รุ่นนี้ เพราะเป็น
entry point เดิมและถูกปิด live mode บน Pi ไว้แล้ว ให้ใช้ `./run_pi5.sh` เท่านั้น

ไม่มีพัดลมยังควรติดฮีตซิงก์ passive ขนาดเหมาะสม เปิดทางให้อากาศไหล และใช้
แหล่งจ่ายไฟ USB-C ที่จ่ายกระแสได้พอ ห้าม overclock สำหรับ station นี้ ทั้งหมดนี้
ช่วยลดโหลดแต่ไม่สามารถเพิ่มกำลังของอะแดปเตอร์ 5V/3A ได้ ตรวจสถานะจริงระหว่าง
burn-in ด้วย:

```bash
watch -n 1 'vcgencmd measure_temp; vcgencmd measure_clock arm; vcgencmd get_throttled'
```

ทดสอบต่อเนื่องอย่างน้อย 30–60 นาทีในกล่อง/อุณหภูมิห้องจริงก่อนใช้งาน production
เพราะ software guard ลดภาระได้ แต่ไม่สามารถทดแทนการระบายความร้อนทางกายภาพได้

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

## ตัวนับพื้นหลังสองสี — Phase 1

ภาพชุดใหม่วางแพเส้นยางในแนวตั้งบนพื้นหลังครึ่งบนสีขาวและครึ่งล่างสีดำ
อัลกอริทึมทดลองอยู่ใน `dual_background_counter.py` โดยตรวจ seam อัตโนมัติ,
เว้น safety band, หา Dynamic ROI จากภาพเต็ม, ประเมิน pitch แยกทุกภาพ และรวม
หลักฐานจากสองโซนได้ โปรแกรมประเมินภาพที่มี ground truth คือ:

```powershell
.\.venv\Scripts\python.exe evaluate_reference_images.py
```

ผล overlay ถูกบันทึกใน `results/reference/` และป้ายกำกับอยู่ใน
`image/ground_truth.json` ช่วงจำนวน `30–50` เป็นข้อจำกัดชั่วคราวสำหรับการทดลอง
ครั้งนี้ ไม่ใช่สเปกผลิตภัณฑ์ถาวร การจำแนกสียังไม่รวมใน Phase 1 ส่วน live loop,
5-frame burst และการจับคู่สินค้าด้วยช่วง pitch ถูกเชื่อมไว้ใน
`pi5_usb_hdmi_station.py` แล้ว การแปลง pitch เป็นมิลลิเมตรจะทำงานเมื่อกำหนด
`processing.pixels_per_mm`; อ่านการตัดสินใจทั้งหมดใน
`docs/ADR-004-dual-background-phase-one.md`

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

สำหรับโปรแกรม Pi ให้แก้ `products.json` ด้วยช่วง pitch ที่ไม่ทับกัน ระบบจะ match
เมื่อมีกฎตรงเพียงหนึ่งกฎเท่านั้น หากไม่ตรงหรือทับกันจะยังแสดง `COUNT` พร้อม
`PRODUCT NO_MATCH` โดยไม่เดาสินค้า:

```json
{
  "products": [
    {
      "id": "EXAMPLE_PRODUCT_40",
      "name": "EXAMPLE PRODUCT 40",
      "nominal_count": 40,
      "pitch_mm_min": 0.95,
      "pitch_mm_max": 1.05
    }
  ]
}
```

ค่าในตัวอย่างไม่ใช่สเปกสินค้าจริง ต้องแทนด้วยช่วงที่วัดและยืนยันแล้ว ถ้ายังไม่
calibrate สามารถใช้ `pitch_px_min`/`pitch_px_max` ชั่วคราวแทนช่วง mm ได้ แต่จะ
ต้องคงระยะกล้องและ zoom เดิม

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

ไฟล์ `thread_counter_original.py` เป็นโค้ดอ้างอิงเดิมที่มี SciPy,
`thread_counter_station.py` เป็นโปรแกรมรุ่นเดิม และ `pi5_usb_hdmi_station.py`
เป็น entry point หลักสำหรับ Pi 5 + จอ HDMI 1024×600 โดยไม่ใช้ SciPy

รายละเอียดจากภาพตัวอย่างจริงและค่าตั้งต้นที่ทดลองแล้วอยู่ใน
`docs/IMAGE-001-observation.md` โดยภาพนี้ใช้เส้นแนวนอนและ `count_axis: "y"`
