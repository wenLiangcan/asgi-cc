FROM maven:3.9.11-eclipse-temurin-21

WORKDIR /app
COPY _vendor/mu-cranker-router /app/mu-cranker-router

WORKDIR /app/mu-cranker-router
RUN mvn -q -DskipTests test-compile dependency:build-classpath -Dmdep.includeScope=test -Dmdep.outputFile=/tmp/mu-cranker-router.classpath
EXPOSE 12000 12001

CMD ["sh", "-lc", "java -cp \"target/test-classes:target/classes:$(cat /tmp/mu-cranker-router.classpath)\" RunLocal"]
