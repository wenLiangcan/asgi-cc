import com.hsbc.cranker.connector.CrankerConnector;
import com.hsbc.cranker.connector.CrankerConnectorBuilder;
import com.sun.net.httpserver.Headers;
import com.sun.net.httpserver.HttpExchange;
import com.sun.net.httpserver.HttpServer;

import java.io.IOException;
import java.io.InputStream;
import java.io.OutputStream;
import java.net.InetSocketAddress;
import java.net.URI;
import java.net.http.HttpClient;
import java.nio.charset.StandardCharsets;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.TimeUnit;

public class RunJavaBenchApp {
    public static void main(String[] args) throws Exception {
        int appPort = Integer.parseInt(System.getenv().getOrDefault("ASGI_CC_JAVA_APP_PORT", "18082"));
        String routerUrl = System.getenv().getOrDefault("CRANKER_ROUTER_URL", "wss://localhost:12001");
        String route = System.getenv().getOrDefault("CRANKER_ROUTE", "*");

        HttpServer server = HttpServer.create(new InetSocketAddress("0.0.0.0", appPort), 0);
        ExecutorService executor = Executors.newFixedThreadPool(16);
        server.setExecutor(executor);

        server.createContext("/health", exchange -> writeResponse(exchange, 200, "text/plain; charset=utf-8", "ok".getBytes(StandardCharsets.UTF_8)));
        server.createContext("/benchmark/ping", exchange -> writeResponse(exchange, 200, "application/json", "{\"ok\":\"true\"}".getBytes(StandardCharsets.UTF_8)));
        server.createContext("/hello", exchange -> writeResponse(exchange, 200, "application/json", "{\"message\":\"hello through cranker\"}".getBytes(StandardCharsets.UTF_8)));
        server.createContext("/headers", RunJavaBenchApp::handleHeaders);
        server.createContext("/echo", RunJavaBenchApp::handleEcho);
        server.start();

        HttpClient client = CrankerConnectorBuilder.createHttpClient(true).build();
        CrankerConnector connector = CrankerConnectorBuilder.connector()
            .withHttpClient(client)
            .withRouterUris(() -> java.util.List.of(URI.create(routerUrl)))
            .withRoute(route)
            .withComponentName("asgi-cc-java-demo")
            .withTarget(URI.create("http://127.0.0.1:" + appPort))
            .start();

        Runtime.getRuntime().addShutdownHook(new Thread(() -> {
            try {
                connector.stop(10, TimeUnit.SECONDS);
            } catch (Throwable ignored) {
            }
            server.stop(0);
            executor.shutdownNow();
        }));

        Thread.currentThread().join();
    }

    private static void handleEcho(HttpExchange exchange) throws IOException {
        byte[] requestBody = readFully(exchange.getRequestBody());
        String response = "{\"method\":\"" + exchange.getRequestMethod() + "\",\"path\":\"" + exchange.getRequestURI().getPath() + "\",\"body_text\":\"" + escapeJson(new String(requestBody, StandardCharsets.UTF_8)) + "\"}";
        writeResponse(exchange, 200, "application/json", response.getBytes(StandardCharsets.UTF_8));
    }

    private static void handleHeaders(HttpExchange exchange) throws IOException {
        StringBuilder builder = new StringBuilder();
        builder.append("{\"headers\":{");
        boolean first = true;
        Headers headers = exchange.getRequestHeaders();
        for (String key : headers.keySet()) {
            if (!first) builder.append(',');
            first = false;
            String value = headers.getFirst(key);
            builder.append('"').append(escapeJson(key.toLowerCase())).append('"').append(':').append('"').append(escapeJson(value == null ? "" : value)).append('"');
        }
        builder.append("}}");
        writeResponse(exchange, 200, "application/json", builder.toString().getBytes(StandardCharsets.UTF_8));
    }

    private static byte[] readFully(InputStream inputStream) throws IOException {
        return inputStream.readAllBytes();
    }

    private static void writeResponse(HttpExchange exchange, int status, String contentType, byte[] bytes) throws IOException {
        exchange.getResponseHeaders().set("content-type", contentType);
        exchange.sendResponseHeaders(status, bytes.length);
        try (OutputStream outputStream = exchange.getResponseBody()) {
            outputStream.write(bytes);
        } finally {
            exchange.close();
        }
    }

    private static String escapeJson(String value) {
        return value
            .replace("\\", "\\\\")
            .replace("\"", "\\\"")
            .replace("\n", "\\n")
            .replace("\r", "\\r");
    }
}
