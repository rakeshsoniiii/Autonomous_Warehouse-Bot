#include <WiFi.h>
#include <WebServer.h>
#include <Wire.h>
#include <LiquidCrystal_I2C.h>

const char* ssid     = "iPhone";
const char* password = "887766554433";

WebServer server(80);

LiquidCrystal_I2C lcd(0x27, 16, 2);

// ===================== PINS =====================

#define IN1 4
#define IN2 5
#define ENA 14

#define IN3 18
#define IN4 19
#define ENB 13

#define TRIG_PIN 26
#define ECHO_PIN 27

// ===================== VARIABLES =====================

String currentMessage = "READY!";

int lastID = 0;

bool obstacleHandled = false;

// ===================== MOTOR =====================

void setMotors(int l, int r) {

  float leftBoost  = 1.18;
  float rightBoost = 1.00;

  l = l * leftBoost;
  r = r * rightBoost;

  if (l >= 0) {

    digitalWrite(IN1, HIGH);
    digitalWrite(IN2, LOW);

  } else {

    digitalWrite(IN1, LOW);
    digitalWrite(IN2, HIGH);

    l = -l;
  }

  if (r >= 0) {

    digitalWrite(IN3, HIGH);
    digitalWrite(IN4, LOW);

  } else {

    digitalWrite(IN3, LOW);
    digitalWrite(IN4, HIGH);

    r = -r;
  }

  l = constrain(l, 0, 255);
  r = constrain(r, 0, 255);

  ledcWrite(ENA, l);
  ledcWrite(ENB, r);
}

// ===================== LCD =====================

void showLCD(String line1, String line2 = "") {

  lcd.clear();

  lcd.setCursor(0,0);
  lcd.print(line1);

  lcd.setCursor(0,1);
  lcd.print(line2);

  currentMessage = line1;
}

// ===================== STOP =====================

void stopBot() {

  digitalWrite(IN1, LOW);
  digitalWrite(IN2, LOW);

  digitalWrite(IN3, LOW);
  digitalWrite(IN4, LOW);

  ledcWrite(ENA, 0);
  ledcWrite(ENB, 0);
}

// ===================== DISTANCE =====================

long getDistance() {

  digitalWrite(TRIG_PIN, LOW);
  delayMicroseconds(2);

  digitalWrite(TRIG_PIN, HIGH);
  delayMicroseconds(10);

  digitalWrite(TRIG_PIN, LOW);

  long duration = pulseIn(ECHO_PIN, HIGH, 18000);

  long distance = duration * 0.034 / 2;

  if(distance <= 0 || distance > 200){

    return 999;
  }

  return distance;
}

// ===================== LOADING =====================

void loadingAnimation(String text){

  lcd.clear();

  lcd.setCursor(0,0);
  lcd.print(text);

  for(int i=0;i<16;i++){

    lcd.setCursor(i,1);

    lcd.print((char)255);

    delay(50);
  }
}

// ===================== SMART BYPASS =====================

void bypassObstacle(){

  obstacleHandled = true;

  showLCD(
    "BYPASSING",
    "OBJECT..."
  );

  setMotors(-200,-200);
  delay(500);

  stopBot();
  delay(100);

  setMotors(250,-250);
  delay(600);

  stopBot();
  delay(100);

  setMotors(200,200);
  delay(1000);

  stopBot();
  delay(100);

  setMotors(-250,250);
  delay(520);

  stopBot();
  delay(100);

  setMotors(220,220);
  delay(1000);

  stopBot();
  delay(100);

  setMotors(-250,250);
  delay(520);

  stopBot();
  delay(100);

  setMotors(150,150);
  delay(1000);

  stopBot();
  delay(100);

  setMotors(220,-220);
  delay(520);

  stopBot();
  delay(100);

  showLCD(
    "FINAL MOVE",
    ""
  );

  setMotors(150,150);
  delay(1000);

  stopBot();

  showLCD(
    "ID REACHED",
    "SUCCESS"
  );

  delay(2000);
}

// ===================== ID1 =====================

void goID1(){

  lastID = 1;

  obstacleHandled = false;

  loadingAnimation("GO TO ID1");

  showLCD(
    "BALL DETECTED",
    "GOING ID1"
  );

  showLCD(
    "LEFT TURN",
    ""
  );

  setMotors(-270,270);
  delay(510);

  stopBot();
  delay(120);

  showLCD(
    "SMALL FORWARD",
    ""
  );

  long start1 = millis();

  setMotors(200,200);

  while(millis() - start1 < 1500){

    long d = getDistance();

    if(d > 5 && d < 10){

      stopBot();

      showLCD(
        "OBJECT",
        "DETECTED"
      );

      delay(500);

      bypassObstacle();

      return;
    }

    delay(20);
  }

  stopBot();
  delay(120);

  showLCD(
    "RIGHT TURN",
    ""
  );

  setMotors(250,-250);
  delay(550);

  stopBot();
  delay(120);

  showLCD(
    "FORWARD",
    ""
  );

  long start2 = millis();

  setMotors(250,250);

  while(millis() - start2 < 1500){

    long d = getDistance();

    if(d > 0 && d < 15){

      stopBot();

      showLCD(
        "OBJECT",
        "DETECTED"
      );

      delay(500);

      bypassObstacle();

      return;
    }

    delay(20);
  }

  stopBot();
  delay(120);

  showLCD(
    "NO OBJECT",
    "STRAIGHT"
  );

  long start3 = millis();

  setMotors(120,120);

  while(millis() - start3 < 1800){

    long d = getDistance();

    if(d > 0 && d < 15){

      stopBot();

      showLCD(
        "OBJECT",
        "DETECTED"
      );

      delay(500);

      bypassObstacle();

      return;
    }

    delay(20);
  }

  stopBot();

  showLCD(
    "ID REACHED",
    "SUCCESS"
  );

  delay(2000);

  // RETURN HOME

  showLCD(
    "RETURNING",
    "HOME..."
  );

  setMotors(280,-280);
  delay(1250);

  stopBot();
  delay(150);

  setMotors(280,280);
  delay(3000);

  stopBot();
  delay(120);

  setMotors(-250,250);
  delay(520);

  stopBot();
  delay(120);

  setMotors(200,200);
  delay(1500);

  stopBot();
  delay(120);

  setMotors(-220,220);
  delay(520);

  stopBot();
  delay(120);


  stopBot();

  showLCD(
    "HOME",
    "REACHED"
  );

  delay(2000);
}

// ===================== ID2 =====================

void goID2(){

  lastID = 2;

  obstacleHandled = false;

  loadingAnimation("GO TO ID2");

  showLCD(
    "GOING",
    "ID2"
  );

  long start4 = millis();

  setMotors(200,200);

  while(millis() - start4 < 2500){

    long d = getDistance();

    if(d > 0 && d < 15){

      stopBot();

      showLCD(
        "OBJECT",
        "DETECTED"
      );

      delay(500);

      bypassObstacle();

      return;
    }

    delay(20);
  }

  stopBot();

  showLCD(
    "ID2 REACHED",
    "SUCCESS"
  );

  delay(2000);

  // RETURN HOME

  showLCD(
    "RETURNING",
    "HOME..."
  );

  setMotors(250,-250);
  delay(1100);

  stopBot();
  delay(150);

  setMotors(200,200);
  delay(2700);

  setMotors(-250,250);
  delay(520);

  stopBot();

  showLCD(
    "HOME",
    "REACHED"
  );

  delay(2000);
}

// ===================== ID3 =====================

void goID3(){

  lastID = 3;

  obstacleHandled = false;

  loadingAnimation("GO TO ID3");

  showLCD(
    "GOING",
    "ID3"
  );

  showLCD(
    "RIGHT TURN",
    ""
  );

  setMotors(250,-250);
  delay(520);

  stopBot();
  delay(120);

  showLCD(
    "FORWARD",
    ""
  );

  long start5 = millis();

  setMotors(150,150);

  while(millis() - start5 < 2000){

    long d = getDistance();

    if(d > 0 && d < 15){

      stopBot();

      showLCD(
        "OBJECT",
        "DETECTED"
      );

      delay(500);

      bypassObstacle();

      return;
    }

    delay(20);
  }

  stopBot();
  delay(120);

  showLCD(
    "LEFT TURN",
    ""
  );

  setMotors(-220,220);
  delay(520);

  stopBot();
  delay(120);

  showLCD(
    "FINAL MOVE",
    ""
  );

  long start6 = millis();

  setMotors(180,180);

  while(millis() - start6 < 2000){

    long d = getDistance();

    if(d > 0 && d < 15){

      stopBot();

      showLCD(
        "OBJECT",
        "DETECTED"
      );

      delay(500);

      bypassObstacle();

      return;
    }

    delay(20);
  }

  stopBot();

  showLCD(
    "ID3 REACHED",
    "SUCCESS"
  );

  delay(2000);

  // RETURN HOME

  showLCD(
    "RETURNING",
    "HOME..."
  );

  setMotors(220,-220);
  delay(1050);

  stopBot();
  delay(150);

  setMotors(180,180);
  delay(2200);

  stopBot();
  delay(120);

  setMotors(220,-220);
  delay(520);

  stopBot();
  delay(120);

  setMotors(150,150);
  delay(2200);

  stopBot();
  delay(120);

  setMotors(-220,220);
  delay(520);

  stopBot();
  delay(120);

  setMotors(150,150);
  delay(1500);

  stopBot();

  showLCD(
    "HOME",
    "REACHED"
  );

  delay(2000);
}

// ===================== ARUCO STEERING =====================

void handleAruco(){

  String dir = server.hasArg("dir")
               ? server.arg("dir")
               : "stop";

  if(dir == "left"){

    showLCD(
      "ARUCO",
      "GO LEFT"
    );

    setMotors(-180, 180);

  } else if(dir == "right"){

    showLCD(
      "ARUCO",
      "GO RIGHT"
    );

    setMotors(180, -180);

  } else if(dir == "forward"){

    showLCD(
      "ARUCO",
      "FORWARD"
    );

    setMotors(180, 180);

  } else if(dir == "stop"){

    stopBot();

    showLCD(
      "ARUCO",
      "REACHED!"
    );

  }

  server.send(
    200,
    "text/plain",
    "OK"
  );
}

// ===================== MANUAL =====================

void handleDrive(){

  int l = server.hasArg("l")
          ? server.arg("l").toInt()
          : 0;

  int r = server.hasArg("r")
          ? server.arg("r").toInt()
          : 0;

  setMotors(l, r);

  showLCD(
    "MANUAL MODE",
    "RUNNING..."
  );

  server.send(
    200,
    "text/plain",
    "OK"
  );
}

// ===================== STOP =====================

void handleStop(){

  stopBot();

  showLCD(
    "STOPPED",
    ""
  );

  server.send(
    200,
    "text/plain",
    "STOP"
  );
}

// ===================== ID HANDLERS =====================

void handleID1(){

  goID1();

  server.send(
    200,
    "text/plain",
    "ID1 DONE"
  );
}

void handleID2(){

  goID2();

  server.send(
    200,
    "text/plain",
    "ID2 DONE"
  );
}

void handleID3(){

  goID3();

  server.send(
    200,
    "text/plain",
    "ID3 DONE"
  );
}

// ===================== HOME PAGE =====================

void handleHome(){

  String html = R"rawliteral(

  <!DOCTYPE html>
  <html>

  <head>

    <title>Warehouse Bot</title>

    <meta name="viewport" content="width=device-width, initial-scale=1">

    <style>

      body{
        font-family: Arial;
        text-align: center;
        background: #111;
        color: white;
        margin-top: 50px;
      }

      h1{
        margin-bottom: 40px;
      }

      button{
        width: 220px;
        height: 70px;
        margin: 15px;
        font-size: 24px;
        border: none;
        border-radius: 15px;
        cursor: pointer;
        font-weight: bold;
      }

      .id1{
        background: #00b894;
        color: white;
      }

      .id2{
        background: #0984e3;
        color: white;
      }

      .id3{
        background: #6c5ce7;
        color: white;
      }

      .stop{
        background: red;
        color: white;
      }

    </style>

  </head>

  <body>

    <h1>WAREHOUSE BOT</h1>

    <button class="id1" onclick="goID1()">
      GO ID 1
    </button>

    <br>

    <button class="id2" onclick="goID2()">
      GO ID 2
    </button>

    <br>

    <button class="id3" onclick="goID3()">
      GO ID 3
    </button>

    <br>

    <button class="stop" onclick="stopBot()">
      STOP
    </button>

    <script>

      function goID1(){
        fetch('/id1');
      }

      function goID2(){
        fetch('/id2');
      }

      function goID3(){
        fetch('/id3');
      }

      function stopBot(){
        fetch('/stop');
      }

    </script>

  </body>

  </html>

  )rawliteral";

  server.send(
    200,
    "text/html",
    html
  );
}

// ===================== SETUP =====================

void setup() {

  Serial.begin(115200);

  Wire.begin(21,22);

  lcd.init();
  lcd.backlight();

  showLCD(
    "WAREHOUSE BOT",
    "STARTING..."
  );

  pinMode(IN1, OUTPUT);
  pinMode(IN2, OUTPUT);

  pinMode(IN3, OUTPUT);
  pinMode(IN4, OUTPUT);

  pinMode(TRIG_PIN, OUTPUT);
  pinMode(ECHO_PIN, INPUT);

  ledcAttach(ENA, 1000, 8);
  ledcAttach(ENB, 1000, 8);

  stopBot();

  WiFi.begin(ssid, password);

  showLCD(
    "CONNECTING",
    "WIFI..."
  );

  while (WiFi.status() != WL_CONNECTED) {

    delay(500);

    Serial.print(".");
  }

  Serial.println("");

  Serial.println(WiFi.localIP());

  showLCD(
    "BOT IP",
    WiFi.localIP().toString()
  );

  delay(3000);

  server.on("/", handleHome);

  server.on("/drive", handleDrive);

  server.on("/id1", handleID1);

  server.on("/id2", handleID2);

  server.on("/id3", handleID3);

  server.on("/stop", handleStop);

  server.on("/aruco", handleAruco);

  server.begin();

  showLCD(
    "READY!",
    ""
  );
}

// ===================== LOOP =====================

void loop() {

  server.handleClient();
}
