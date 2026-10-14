/*
  esp32code.ino  (BAN CO OLED + BUZZER)
  --------------------
  Web server tren ESP32 nhan lenh qua Wi-Fi:
    /light/on        -> bat den LED (GPIO 2)
    /light/off       -> tat den LED
    /buzzer/emergency-> coi bao KHAN CAP (bip nhanh lien tuc, 3 giay)
    /buzzer/nurse    -> coi GOI Y TA (2 tieng bip cham)
    /buzzer/off      -> tat coi ngay
    /oled?l1=abc&l2=xyz -> hien 2 dong chu tuy y len OLED (chi ASCII, khong dau)

  DAU DAY:
    OLED SSD1306 (I2C): GND->GND, VCC->3V3, SDA->GPIO 21, SCL->GPIO 22
    Buzzer: chan (+) -> GPIO 18, chan (-) -> GND
    LED: GPIO 2 nhu cu

  THU VIEN CAN CAI (Tools > Manage Libraries): Adafruit SSD1306, Adafruit GFX
*/

#include <WiFi.h>
#include <WebServer.h>
#include <Wire.h>
#include <Adafruit_GFX.h>
#include <Adafruit_SSD1306.h>

// ==== CAU HINH WI-FI (doi thanh Wi-Fi that cua ban) ====
const char* WIFI_SSID = "TEN_WIFI_CUA_BAN";
const char* WIFI_PASSWORD = "MAT_KHAU_WIFI";

// ==== CHAN GPIO ====
const int LED_PIN = 2;
const int BUZZER_PIN = 18;   // KHONG dung GPIO 4 (DHT11) va GPIO 5 (IR)

// true = buzzer THU DONG (passive, can tao tan so); false = buzzer CHU DONG (active)
// Meo: cap dien truc tiep 3.3V cho buzzer, neu no TU KEU = chu dong (active).
const bool BUZZER_PASSIVE = false;
const int BUZZER_FREQ = 2000;

// ==== OLED ====
const int OLED_W = 128;
const int OLED_H = 64;
const uint8_t OLED_ADDR = 0x3C;   // neu khong len hinh, thu 0x3D
Adafruit_SSD1306 display(OLED_W, OLED_H, &Wire, -1);
bool oledOk = false;

WebServer server(80);
bool lightOn = false;

// ==================== BUZZER (khong chan loop) ====================
// Mau am thanh: day thoi gian (ms), phan tu chan = KEU, phan tu le = IM.
const uint16_t PATTERN_EMERGENCY[] = {120,100,120,100,120,100,120,100,120,100,120,100,120,100,120,100,120,100,120,100};
const uint16_t PATTERN_NURSE[]     = {500,350,500,350};
const uint16_t* curPattern = nullptr;
int curLen = 0;
int curIdx = 0;
unsigned long stepStart = 0;
String alertName = "";

void buzzerHw(bool on) {
  if (BUZZER_PASSIVE) {
#if defined(ESP_ARDUINO_VERSION_MAJOR) && ESP_ARDUINO_VERSION_MAJOR >= 3
    ledcWriteTone(BUZZER_PIN, on ? BUZZER_FREQ : 0);
#else
    ledcWriteTone(0, on ? BUZZER_FREQ : 0);
#endif
  } else {
    digitalWrite(BUZZER_PIN, on ? HIGH : LOW);
  }
}

void buzzerSetup() {
  if (BUZZER_PASSIVE) {
#if defined(ESP_ARDUINO_VERSION_MAJOR) && ESP_ARDUINO_VERSION_MAJOR >= 3
    ledcAttach(BUZZER_PIN, BUZZER_FREQ, 8);
#else
    ledcSetup(0, BUZZER_FREQ, 8);
    ledcAttachPin(BUZZER_PIN, 0);
#endif
  } else {
    pinMode(BUZZER_PIN, OUTPUT);
  }
  buzzerHw(false);
}

void startPattern(const uint16_t* p, int len, const char* name) {
  curPattern = p; curLen = len; curIdx = 0;
  stepStart = millis();
  alertName = name;
  buzzerHw(true);
}

void stopBuzzer() {
  curPattern = nullptr;
  buzzerHw(false);
}

// Goi lien tuc trong loop(): chuyen buoc KEU/IM khi het thoi gian
void updateBuzzer() {
  if (curPattern == nullptr) return;
  if (millis() - stepStart >= curPattern[curIdx]) {
    curIdx++;
    if (curIdx >= curLen) { stopBuzzer(); return; }
    stepStart = millis();
    buzzerHw(curIdx % 2 == 0);
  }
}

// ==================== OLED ====================
String customL1 = "", customL2 = "";
unsigned long customUntil = 0;
String lastScreen = "";

void drawScreen() {
  if (!oledOk) return;
  String key;
  display.clearDisplay();
  display.setTextColor(SSD1306_WHITE);

  if (curPattern != nullptr) {                       // dang bao dong
    key = "ALERT" + alertName;
    display.setTextSize(2);
    display.setCursor(0, 8);
    display.println(alertName == "EMERGENCY" ? "KHAN CAP!" : "GOI Y TA");
    display.setTextSize(1);
    display.setCursor(0, 44);
    display.println(alertName == "EMERGENCY" ? "Can ho tro NGAY" : "Dang goi ho tro...");
  } else if (millis() < customUntil) {               // chu tuy y tu Python
    key = "C" + customL1 + customL2;
    display.setTextSize(2);
    display.setCursor(0, 8);  display.println(customL1);
    display.setCursor(0, 36); display.println(customL2);
  } else {                                           // man hinh trang thai
    key = "S" + String(lightOn) + WiFi.localIP().toString();
    display.setTextSize(1);
    display.setCursor(0, 0);  display.println("TOUCHLESS IoT");
    display.setCursor(0, 16); display.print("IP: "); display.println(WiFi.localIP());
    display.setCursor(0, 32); display.print("DEN: "); display.println(lightOn ? "BAT" : "TAT");
    display.setCursor(0, 48); display.println("San sang nhan lenh");
  }
  if (key == lastScreen) { display.clearDisplay(); return; }  // khong doi -> khoi ve lai
  lastScreen = key;
  display.display();
}

// ==================== HANDLER ====================
void handleLightOn()  { lightOn = true;  digitalWrite(LED_PIN, HIGH); server.send(200, "text/plain", "Light ON"); }
void handleLightOff() { lightOn = false; digitalWrite(LED_PIN, LOW);  server.send(200, "text/plain", "Light OFF"); }

void handleEmergency() {
  startPattern(PATTERN_EMERGENCY, sizeof(PATTERN_EMERGENCY) / 2, "EMERGENCY");
  server.send(200, "text/plain", "Buzzer EMERGENCY");
}
void handleNurse() {
  startPattern(PATTERN_NURSE, sizeof(PATTERN_NURSE) / 2, "NURSE");
  server.send(200, "text/plain", "Buzzer NURSE");
}
void handleBuzzerOff() { stopBuzzer(); server.send(200, "text/plain", "Buzzer OFF"); }

void handleOled() {
  customL1 = server.arg("l1"); customL1 = customL1.substring(0, 10);   // size 2 -> toi da ~10 ky tu/dong
  customL2 = server.arg("l2"); customL2 = customL2.substring(0, 10);
  customUntil = millis() + 4000;
  server.send(200, "text/plain", "OLED OK");
}

void setup() {
  Serial.begin(115200);
  pinMode(LED_PIN, OUTPUT);
  digitalWrite(LED_PIN, LOW);
  buzzerSetup();

  Wire.begin(21, 22);
  oledOk = display.begin(SSD1306_SWITCHCAPVCC, OLED_ADDR);
  Serial.println(oledOk ? "OLED OK" : "KHONG tim thay OLED (kiem tra day SDA/SCL, dia chi 0x3C/0x3D)");
  if (oledOk) {
    display.clearDisplay();
    display.setTextColor(SSD1306_WHITE);
    display.setTextSize(1);
    display.setCursor(0, 0);
    display.println("Dang ket noi WiFi...");
    display.display();
  }

  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
  Serial.print("Dang ket noi WiFi");
  while (WiFi.status() != WL_CONNECTED) { delay(500); Serial.print("."); }
  Serial.println();
  Serial.print("Da ket noi WiFi! IP cua ESP32: ");
  Serial.println(WiFi.localIP());

  server.on("/light/on", handleLightOn);
  server.on("/light/off", handleLightOff);
  server.on("/buzzer/emergency", handleEmergency);
  server.on("/buzzer/nurse", handleNurse);
  server.on("/buzzer/off", handleBuzzerOff);
  server.on("/oled", handleOled);
  server.begin();
  Serial.println("Web server san sang.");
  lastScreen = "";
}

void loop() {
  server.handleClient();
  updateBuzzer();
  drawScreen();
}
