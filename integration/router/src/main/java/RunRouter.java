import com.hsbc.cranker.mucranker.CrankerRouter;
import com.hsbc.cranker.mucranker.CrankerRouterBuilder;
import io.muserver.ContentTypes;
import io.muserver.Http2ConfigBuilder;
import io.muserver.Method;
import io.muserver.MuServer;
import io.muserver.MuServerBuilder;

import java.util.List;
import java.util.concurrent.TimeUnit;

public class RunRouter {
    public static void main(String[] args) {
        CrankerRouter router = CrankerRouterBuilder.crankerRouter()
            .withSupportedCrankerProtocols(List.of("cranker_3.0", "cranker_1.0"))
            .withIdleTimeout(5, TimeUnit.MINUTES)
            .withRegistrationIpValidator(ip -> true)
            .start();

        MuServer registrationServer = MuServerBuilder.httpsServer()
            .withHttpsPort(12001)
            .addHandler(Method.GET, "/health", (request, response, pathParams) -> {
                response.contentType(ContentTypes.TEXT_PLAIN_UTF8);
                response.write("ok");
            })
            .addHandler(Method.GET, "/health/connectors", (request, response, pathParams) -> {
                response.contentType("application/json");
                response.write(router.collectInfo().toMap().toString());
            })
            .addHandler(router.createRegistrationHandler())
            .start();

        MuServer httpServer = MuServerBuilder.httpsServer()
            .withHttpsPort(12000)
            .withHttp2Config(Http2ConfigBuilder.http2EnabledIfAvailable())
            .addHandler(router.createHttpHandler())
            .start();

        System.out.println("Registration URL is ws" + registrationServer.uri().toString().substring(4));
        System.out.println("The HTTP endpoint for clients is available at " + httpServer.uri());

        Runtime.getRuntime().addShutdownHook(new Thread(() -> {
            httpServer.stop();
            registrationServer.stop();
            router.stop();
        }));
    }
}
