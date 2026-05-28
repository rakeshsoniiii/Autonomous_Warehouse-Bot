#include <WiFi.h>
#include <WebServer.h>
#include <Wire.h>
#include <LiquidCrystal_I2C.h>

const char* ssid     = "Rak";
const char* password = "@1212@#1";

WebServer server(80);
LiquidCrystal_I2C lcd(0x27, 16, 2);

bool autoMode = false;
bool followMode = false;  // New mode flag for tracking target marker
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
  
  // ESP32 Arduino Core 2.x/3.x compatibility adjustment for LEDC PWM
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

  for(int i = 0; i < 5; i++) {
    digitalWrite(TRIG_PIN, LOW);
    delayMicroseconds(2);
    digitalWrite(TRIG_PIN, HIGH);
    delayMicroseconds(10);
    digitalWrite(TRIG_PIN, LOW);
    
    duration = pulseIn(ECHO_PIN, HIGH, 30000);
    distance = duration * 0.0343 / 2;
    // Filter bad sensor spikes (0 means timeout)
    if(distance > 0) total += distance; 
    else total += 400; 
    delay(10);
  }
  return total / 5.0;
}

// Safety overriding loop: Stops the bot if it is about to hit something physically
void checkEmergencySafety() {
  lastDistance = getDistance();
  if (lastDistance < 12) { // 12 cm wall buffer
    stopBot();
    lcd.clear();
    lcd.setCursor(0, 0); lcd.print("EMERGENCY STOP");
    lcd.setCursor(0, 1); lcd.print("Obj: "); lcd.print(lastDistance); lcd.print("cm");
    followMode = false; // Disengage follow loop automatically
  }
}

void handleDrive() {
  autoMode = false;
  int l = server.hasArg("l") ? server.arg("l").toInt() : 0;
  int r = server.hasArg("r") ? server.arg("r").toInt() : 0;
  
  // Run safety check before applying power
  lastDistance = getDistance();
  if (lastDistance < 12 && (l > 0 || r > 0)) {
    stopBot();
    server.send(200, "text/plain", "BLOCKED BY OBSTACLE");
    return;
  }
  
  setMotors(l, r);
  lcd.clear();
  lcd.setCursor(0, 0); lcd.print("L:"); lcd.print(l);
  lcd.setCursor(8, 0); lcd.print("R:"); lcd.print(r);
  server.send(200, "text/plain", "OK");
}

void handleFollowCommand() {
  autoMode = false;
  followMode = true;
  
  int l = server.hasArg("l") ? server.arg("l").toInt() : 0;
  int r = server.hasArg("r") ? server.arg("r").toInt() : 0;
  
  setMotors(l, r);
  
  lcd.clear();
  lcd.setCursor(0, 0); lcd.print("FOLLOW MODE");
  lcd.setCursor(0, 1); lcd.print("L:"); lcd.print(l); lcd.print(" R:"); lcd.print(r);
  server.send(200, "text/plain", "TRACKING");
}

void handleStop() {
  stopBot();
  autoMode = false;
  followMode = false;
  lcd.clear(); lcd.print("STOP");
  server.send(200, "text/plain", "Stop");
}

void handleAutoMode() {
  if (server.hasArg("mode")) {
    autoMode = server.arg("mode").toInt() == 1;
    if(autoMode) followMode = false;
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

  // Setup PWM parameters
  ledcSetup(0, 1000, 8);
  ledcSetup(1, 1000, 8);
  ledcAttachPin(ENA, 0);
  ledcAttachPin(ENB, 1);
  stopBot();

  WiFi.begin(ssid, password);
  lcd.clear(); lcd.print("Connecting WiFi");
  while (WiFi.status() != WL_CONNECTED) { delay(500); Serial.print("."); }

  Serial.println("\nConnected! IP: " + WiFi.localIP().toString());
  lcd.clear(); lcd.print(WiFi.localIP());
  delay(2000);

  server.on("/drive",    handleDrive);
  server.on("/follow",   handleFollowCommand); // New dedicated route for python updates
  server.on("/stop",     handleStop);
  server.on("/auto",     handleAutoMode);
  server.on("/distance", handleDistance);
  server.begin();

  lcd.clear(); lcd.print("READY!");
}

void loop() {
  server.handleClient();
  
  if (followMode) {
    checkEmergencySafety();
  }
}
