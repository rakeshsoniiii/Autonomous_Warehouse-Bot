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

  Serial.println("\n" + WiFi.localIP().toString());
  lcd.clear(); lcd.print(WiFi.localIP());
  delay(2000);

  server.on("/drive", handleDrive);
  server.on("/stop",  handleStop);
  server.on("/auto",  handleAutoMode);
  server.on("/distance", handleDistance);
  server.begin();

  lcd.clear(); lcd.print("READY!");
}

void loop() {
  server.handleClient();
  if (autoMode) {
    autoAvoid();
    lcd.clear();
    lcd.setCursor(0, 0); lcd.print("AUTO:");
    lcd.setCursor(6, 0); lcd.print(lastDistance); lcd.print("cm");
  }
}
