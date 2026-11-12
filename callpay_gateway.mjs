import http from "node:http";

const apiPort = Number(process.env.CALLPAY_API_PORT || "8000");
const nextPort = Number(process.env.CALLPAY_NEXT_PORT || "3001");
const gatewayPort = Number(process.env.CALLPAY_WEB_PORT || "3000");

const server = http.createServer((request, response) => {
  const incoming = new URL(request.url || "/", "http://localhost");
  const isApi = incoming.pathname === "/api" || incoming.pathname.startsWith("/api/");
  if (incoming.pathname === "/api/internal" || incoming.pathname.startsWith("/api/internal/")) {
    response.writeHead(403, { "content-type": "application/json; charset=utf-8" });
    response.end(JSON.stringify({ detail: "internal only" }));
    return;
  }
  const upstreamPort = isApi ? apiPort : nextPort;
  const upstreamPath = isApi
    ? `${incoming.pathname.slice(4) || "/"}${incoming.search}`
    : `${incoming.pathname}${incoming.search}`;
  const upstream = http.request(
    {
      hostname: "127.0.0.1",
      port: upstreamPort,
      path: upstreamPath,
      method: request.method,
      headers: { ...request.headers, host: `127.0.0.1:${upstreamPort}` },
    },
    (upstreamResponse) => {
      response.writeHead(upstreamResponse.statusCode || 502, upstreamResponse.headers);
      upstreamResponse.pipe(response);
    },
  );

  upstream.on("error", () => {
    if (!response.headersSent) {
      response.writeHead(502, { "content-type": "text/plain; charset=utf-8" });
      response.end("CallPay upstream unavailable");
    } else {
      response.destroy();
    }
  });
  request.on("aborted", () => upstream.destroy());
  response.on("close", () => upstream.destroy());
  request.pipe(upstream);
});

server.requestTimeout = 0;
server.timeout = 0;
server.listen(gatewayPort, "0.0.0.0", () => {
  console.log(`CallPay streaming gateway listening on 0.0.0.0:${gatewayPort}`);
});
