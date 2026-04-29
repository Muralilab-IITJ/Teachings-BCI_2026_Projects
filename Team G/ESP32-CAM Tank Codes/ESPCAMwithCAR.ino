#include "esp_camera.h"
#include <WiFi.h>
#include "esp_http_server.h"
#include <WiFiUdp.h>

const char* ssid = "Lucky";
const char* password = "vishal...";
const unsigned int localUdpPort = 4210;
WiFiUDP udp;
char incomingPacket[255]; 

#define MOTOR_L_IN1 12
#define MOTOR_L_IN2 13
#define MOTOR_R_IN1 14
#define MOTOR_R_IN2 15

const int pulseDuration = 300; 
unsigned long stopTime = 0;
bool moving = false;

// AI-Thinker Pins
#define PWDN_GPIO_NUM     32
#define RESET_GPIO_NUM    -1
#define XCLK_GPIO_NUM      0
#define SIOD_GPIO_NUM     26
#define SIOC_GPIO_NUM     27
#define Y9_GPIO_NUM       35
#define Y8_GPIO_NUM       34
#define Y7_GPIO_NUM       39
#define Y6_GPIO_NUM       36
#define Y5_GPIO_NUM       21
#define Y4_GPIO_NUM       19
#define Y3_GPIO_NUM       18
#define Y2_GPIO_NUM        5
#define VSYNC_GPIO_NUM    25
#define HREF_GPIO_NUM     23
#define PCLK_GPIO_NUM     22

httpd_handle_t stream_httpd = NULL;

void stopMotors() {
  digitalWrite(MOTOR_L_IN1, LOW); digitalWrite(MOTOR_L_IN2, LOW);
  digitalWrite(MOTOR_R_IN1, LOW); digitalWrite(MOTOR_R_IN2, LOW);
  moving = false;
}

void moveCar(char cmd) {
  if (cmd == 's') { stopMotors(); return; }
  if (cmd == 'f') { digitalWrite(MOTOR_L_IN1, HIGH); digitalWrite(MOTOR_R_IN1, HIGH); } 
  else if (cmd == 'b') { digitalWrite(MOTOR_L_IN2, HIGH); digitalWrite(MOTOR_R_IN2, HIGH); } 
  else if (cmd == 'l') { digitalWrite(MOTOR_L_IN2, HIGH); digitalWrite(MOTOR_R_IN1, HIGH); } 
  else if (cmd == 'r') { digitalWrite(MOTOR_L_IN1, HIGH); digitalWrite(MOTOR_R_IN2, HIGH); }
  stopTime = millis() + pulseDuration;
  moving = true;
}

static esp_err_t stream_handler(httpd_req_t *req) {
  camera_fb_t * fb = NULL;
  esp_err_t res = ESP_OK;
  char * part_buf[64];
  static const char* _STREAM_BOUNDARY = "123456789000000000000987654321";
  static const char* _STREAM_PART = "Content-Type: image/jpeg\r\nContent-Length: %u\r\n\r\n";

  httpd_resp_set_type(req, "multipart/x-mixed-replace;boundary=123456789000000000000987654321");

  while(true) {
    fb = esp_camera_fb_get();
    if (!fb) {
      vTaskDelay(10 / portTICK_PERIOD_MS);
      continue;
    }
    size_t hlen = snprintf((char *)part_buf, 64, _STREAM_PART, fb->len);
    res = httpd_resp_send_chunk(req, (const char *)part_buf, hlen);
    if(res == ESP_OK) res = httpd_resp_send_chunk(req, (const char *)fb->buf, fb->len);
    if(res == ESP_OK) res = httpd_resp_send_chunk(req, "\r\n--123456789000000000000987654321\r\n", 37);
    esp_camera_fb_return(fb);
    if(res != ESP_OK) break;
  }
  return res;
}

void setup() {
  Serial.begin(115200);
  pinMode(MOTOR_L_IN1, OUTPUT); pinMode(MOTOR_L_IN2, OUTPUT);
  pinMode(MOTOR_R_IN1, OUTPUT); pinMode(MOTOR_R_IN2, OUTPUT);
  stopMotors();

  camera_config_t config;
  config.ledc_channel = LEDC_CHANNEL_0;
  config.ledc_timer = LEDC_TIMER_0;
  config.pin_d0 = Y2_GPIO_NUM; config.pin_d1 = Y3_GPIO_NUM;
  config.pin_d2 = Y4_GPIO_NUM; config.pin_d3 = Y5_GPIO_NUM;
  config.pin_d4 = Y6_GPIO_NUM; config.pin_d5 = Y7_GPIO_NUM;
  config.pin_d6 = Y8_GPIO_NUM; config.pin_d7 = Y9_GPIO_NUM;
  config.pin_xclk = XCLK_GPIO_NUM; config.pin_pclk = PCLK_GPIO_NUM;
  config.pin_vsync = VSYNC_GPIO_NUM; config.pin_href = HREF_GPIO_NUM;
  config.pin_sscb_sda = SIOD_GPIO_NUM; config.pin_sscb_scl = SIOC_GPIO_NUM;
  config.pin_pwdn = PWDN_GPIO_NUM; config.pin_reset = RESET_GPIO_NUM;
  config.xclk_freq_hz = 20000000;
  config.pixel_format = PIXFORMAT_JPEG;
  config.frame_size = FRAMESIZE_QVGA; 
  config.jpeg_quality = 12;
  config.fb_count = 1;

  esp_camera_init(&config);
  WiFi.begin(ssid, password);
  while (WiFi.status() != WL_CONNECTED) delay(500);
  
  udp.begin(localUdpPort);
  httpd_config_t server_config = HTTPD_DEFAULT_CONFIG();
  httpd_uri_t stream_uri = { .uri = "/stream", .method = HTTP_GET, .handler = stream_handler };
  httpd_start(&stream_httpd, &server_config);
  httpd_register_uri_handler(stream_httpd, &stream_uri);
  Serial.println(WiFi.localIP());
}

void loop() {
  int packetSize = udp.parsePacket();
  if (packetSize) {
    int len = udp.read(incomingPacket, 255);
    if (len > 0) moveCar(incomingPacket[0]);
  }
  if (moving && millis() > stopTime) stopMotors();
  delay(1);
}