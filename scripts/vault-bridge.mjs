import http from "node:http";

const listenHost = "127.0.0.1";
const listenPort = Number(process.env.LISTEN_PORT || 8792);
const upstream = new URL(process.env.UPSTREAM_URL || "http://127.0.0.1:3000");

const server = http.createServer((request, response) => {
  const upstreamRequest = http.request(
    {
      protocol: upstream.protocol,
      hostname: upstream.hostname,
      port: upstream.port,
      method: request.method,
      path: request.url,
      headers: request.headers,
    },
    (upstreamResponse) => {
      response.writeHead(upstreamResponse.statusCode || 502, upstreamResponse.headers);
      upstreamResponse.pipe(response);
    },
  );

  upstreamRequest.on("error", () => {
    if (!response.headersSent) {
      response.writeHead(502, { "content-type": "text/plain; charset=utf-8" });
    }
    response.end("Bad Gateway");
  });

  request.on("aborted", () => upstreamRequest.destroy());
  request.pipe(upstreamRequest);
});

server.listen(listenPort, listenHost, () => {
  console.log(
    `attn vault bridge listening on http://${listenHost}:${listenPort} -> ${upstream.origin}`,
  );
});
