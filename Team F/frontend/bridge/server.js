const dgram = require("dgram");
const { WebSocketServer } = require("ws");

// 1. Setup UDP Server (Listens for Python on port 5005)
const udpServer = dgram.createSocket("udp4");
const UDP_PORT = 5005;

// 2. Setup WebSocket Server (Talks to React on port 8080)
const wss = new WebSocketServer({ port: 8080 });

wss.on("connection", (ws) => {
  console.log("🟢 React Frontend Connected!");
});

// 3. The Bridge: Instantly forward Python's UDP data to React
udpServer.on("message", (msg) => {
  wss.clients.forEach((client) => {
    if (client.readyState === 1) {
      client.send(msg.toString());
    }
  });
});

udpServer.bind(UDP_PORT, () => {
  console.log(`🔌 UDP Server listening for Python on port ${UDP_PORT}`);
  console.log(`🔌 WebSocket Server waiting for React on port 8080`);
});
