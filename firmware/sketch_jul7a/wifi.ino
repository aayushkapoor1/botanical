#include <WiFi.h>
#include <PubSubClient.h>

const char* ssid = "Hespeler WiFi 1101";
const char* password = "RogersHespeler";
const char* mqtt_server = "10.40.227.209";

WiFiClient espClient;
PubSubClient client(espClient);

void callback(char* topic, byte* payload, unsigned int length) {
  // Print Pi's message to Serial (shows in Serial Monitor)
  for (unsigned int i = 0; i < length; i++) {
    Serial.write(payload[i]);
  }
  Serial.println();
}

void setup() {
  Serial.begin(115200);
  Serial.println("Connecting to WiFi...");
  WiFi.begin(ssid, password);
  while (WiFi.status() != WL_CONNECTED) {
    delay(500);
    Serial.print(".");
  }
  Serial.println("\nWiFi connected");

  client.setServer(mqtt_server, 1883);
  client.setCallback(callback);
  Serial.println("Type here to send to Pi. Messages from Pi appear above.");
  Serial.println("----------------------------------------");
}

void reconnect() {
  while (!client.connected()) {
    if (client.connect("ESP32_Master")) {
      client.subscribe("esp32/commands");
    } else {
      delay(5000);
    }
  }
}

void loop() {
  if (!client.connected()) reconnect();
  client.loop();

  // Read from Serial and publish to Pi
  if (Serial.available()) {
    String line = Serial.readStringUntil('\n');
    line.trim();
    if (line.length() > 0) {
      client.publish("esp32/output", line.c_str());
    }
  }
}
