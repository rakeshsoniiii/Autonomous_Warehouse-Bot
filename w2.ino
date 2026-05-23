#include <WiFi.h>
#include <WebServer.h>
#include <Wire.h>
#include <LiquidCrystal_I2C.h>

const char* ssid     = "Rak";
const char* password = "@1212@#1";

WebServer server(80);
LiquidCrystal_I2C lcd(0x27, 16, 2);

bool autoMode = false;
int lastDistance = 0;
// RSSI localization
const char* beaconSSID = "BEACON"; // default beacon SSID (changeable on beacon ESP32)
int targetBox = 0; // 0 = none, 1..3 = box ids
int expectedRSSI[] = {0, -15, -40, -65}; // expected RSSI values for boxes 1..3
int rssiTolerance = 15; // +/- tolerance in dBm for considered "reached"
bool navActive = false;

#define IN1 4
#define IN2 5
#define ENA 14
#define IN3 18
#define IN4 19
#define ENB 13
#define TRIG_PIN 26
#define ECHO_PIN 27

void setMotors(int l, int r) {
  if (l >= 0) { digitalWrite(IN1, HIGH); digitalWrite(IN2, LOW); }
  else        { digitalWrite(IN1, LOW);  digitalWrite(IN2, HIGH); l = -l; }
  if (r >= 0) { digitalWrite(IN3, HIGH); digitalWrite(IN4, LOW); }
  else        { digitalWrite(IN3, LOW);  digitalWrite(IN4, HIGH); r = -r; }
  ledcWrite(0, constrain(l, 0, 255));
  ledcWrite(1, constrain(r, 0, 255));
}

void stopBot() {
  digitalWrite(IN1, LOW); digitalWrite(IN2, LOW);
  digitalWrite(IN3, LOW); digitalWrite(IN4, LOW);
  ledcWrite(0, 0); ledcWrite(1, 0);
}

long getDistance() {
  long duration;
  float distance;
  float total = 0;

  // Take 5 readings for stability
  for(int i = 0; i < 5; i++) {
    digitalWrite(TRIG_PIN, LOW);
    delayMicroseconds(2);
    digitalWrite(TRIG_PIN, HIGH);
    delayMicroseconds(10);
    digitalWrite(TRIG_PIN, LOW);
    
    duration = pulseIn(ECHO_PIN, HIGH, 30000);
    distance = duration * 0.0343 / 2;
    total += distance;
    delay(20);
  }
  
  return total / 5.0;
}

void autoAvoid() {
  lastDistance = getDistance();
  
  if (lastDistance < 15) {
    stopBot();
    delay(300);
    setMotors(-150, -150);
    delay(400);
    setMotors(-100, 150);
    delay(600);
  } else if (lastDistance < 25) {
    setMotors(100, 100);
    delay(50);
  } else {
    setMotors(150, 150);
  }
}

void handleDrive() {
  int l = server.hasArg("l") ? server.arg("l").toInt() : 0;
  int r = server.hasArg("r") ? server.arg("r").toInt() : 0;
  setMotors(l, r);
  lcd.clear();
  lcd.setCursor(0, 0); lcd.print("L:"); lcd.print(l);
  lcd.setCursor(8, 0); lcd.print("R:"); lcd.print(r);
  server.send(200, "text/plain", "OK");
}

void handleStop() {
  stopBot();
  autoMode = false;
  lcd.clear(); lcd.print("STOP");
  server.send(200, "text/plain", "Stop");
}

void handleAutoMode() {
  if (server.hasArg("mode")) {
    autoMode = server.arg("mode").toInt() == 1;
  }
  server.send(200, "text/plain", autoMode ? "Auto ON" : "Auto OFF");
}

void handleDistance() {
  long dist = getDistance();
  String response = "{\"distance\":" + String(dist) + "}";
  server.send(200, "application/json", response);
}

int getBeaconRSSI() {
  int n = WiFi.scanNetworks();
  for (int i = 0; i < n; i++) {
    if (WiFi.SSID(i) == String(beaconSSID)) {
      return WiFi.RSSI(i);
    }
  }
  return -1000; // not found
}

int getBeaconRSSIAvg(int samples = 3) {
  long sum = 0;
  int found = 0;
  for (int i = 0; i < samples; i++) {
    int r = getBeaconRSSI();
    if (r != -1000) { sum += r; found++; }
    delay(60);
  }
  if (found == 0) return -1000;
  return (int)(sum / found);
}

void handleRSSI() {
  int r = getBeaconRSSIAvg(3);
  String resp = "{\"rssi\":" + String(r) + "}";
  server.send(200, "application/json", resp);
}

bool isAtTarget() {
  if (targetBox < 1 || targetBox > 3) return false;
  int rssi = getBeaconRSSI();
  if (rssi == -1000) return false;
  return abs(rssi - expectedRSSI[targetBox]) <= rssiTolerance;
}

void navStep() {
  if (targetBox < 1 || targetBox > 3) return;
  if (isAtTarget()) {
    stopBot();
    navActive = false;
    autoMode = false;
    lcd.clear(); lcd.print("REACHED");
    return;
  }

  int center = getBeaconRSSI();

  // quick left probe
  setMotors(-100, 100);
  delay(300);
  int left = getBeaconRSSI();

  // quick right probe (rotate past center)
  setMotors(100, -100);
  delay(600);
  int right = getBeaconRSSI();

  // return to approximate center
  setMotors(-100, 100);
  delay(300);

  // decide rotation direction based on stronger signal (larger value = stronger, less negative)
  if (left > right) {
    // steer left then move forward
    setMotors(-120, 120);
    delay(300);
  } else if (right > left) {
    setMotors(120, -120);
    delay(300);
  }

  // move forward while checking obstacle distance
  setMotors(150, 150);
  unsigned long t0 = millis();
  while (millis() - t0 < 600) {
    if (getDistance() < 20) {
      stopBot();
      // simple avoidance: backup and turn
      setMotors(-150, -150);
      delay(300);
      setMotors(-100, 150);
      delay(400);
      break;
    }
    delay(50);
  }
  stopBot();
}

void handleSetTarget() {
  if (server.hasArg("box")) {
    int b = server.arg("box").toInt();
    if (b >= 1 && b <= 3) {
      targetBox = b;
      navActive = true;
      autoMode = true;
      lcd.clear(); lcd.print("TGT:"); lcd.print(b);
      server.send(200, "text/plain", "OK");
      return;
    }
  }
  server.send(400, "text/plain", "Bad");
}

void handleID1() { targetBox = 1; navActive = true; autoMode = true; lcd.clear(); lcd.print("TGT:1"); server.send(200, "text/plain", "Going to ID 1"); }
void handleID2() { targetBox = 2; navActive = true; autoMode = true; lcd.clear(); lcd.print("TGT:2"); server.send(200, "text/plain", "Going to ID 2"); }
void handleID3() { targetBox = 3; navActive = true; autoMode = true; lcd.clear(); lcd.print("TGT:3"); server.send(200, "text/plain", "Going to ID 3"); }



void setup() {
  Serial.begin(115200);

  Wire.begin(21, 22);
  lcd.init();
  lcd.backlight();
  lcd.clear();
  lcd.print("Warehouse Bot");

  pinMode(IN1, OUTPUT); pinMode(IN2, OUTPUT);
  pinMode(IN3, OUTPUT); pinMode(IN4, OUTPUT);
  pinMode(TRIG_PIN, OUTPUT); pinMode(ECHO_PIN, INPUT);

  ledcSetup(0, 1000, 8);
  ledcSetup(1, 1000, 8);
  ledcAttachPin(ENA, 0);
  ledcAttachPin(ENB, 1);
  stopBot();

  WiFi.begin(ssid, password);
  lcd.clear(); lcd.print("Connecting WiFi");
  while (WiFi.status() != WL_CONNECTED) { delay(500); Serial.print("."); }

  Serial.println(WiFi.localIP());
  lcd.clear(); lcd.print(WiFi.localIP());
  delay(2000);

  server.on("/drive", handleDrive);
  server.on("/stop",  handleStop);
  server.on("/auto",  handleAutoMode);
  server.on("/distance", handleDistance);
  server.on("/settarget", handleSetTarget);
  server.on("/id1", handleID1);
  server.on("/id2", handleID2);
  server.on("/id3", handleID3);
  server.on("/rssi", handleRSSI);
  server.begin();

  lcd.clear(); lcd.print("READY!");
}

void loop() {
  server.handleClient();
  if (autoMode) {
    if (navActive && targetBox > 0) {
      navStep();
      lcd.clear();
      lcd.setCursor(0, 0); lcd.print("NAV T"); lcd.print(targetBox);
      lcd.setCursor(6, 0); lcd.print(lastDistance); lcd.print("cm");
    } else {
      autoAvoid();
      lcd.clear();
      lcd.setCursor(0, 0); lcd.print("AUTO:");
      lcd.setCursor(6, 0); lcd.print(lastDistance); lcd.print("cm");
    }
  }
}
