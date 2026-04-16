FROM maven:3.9.11-eclipse-temurin-21

WORKDIR /app
COPY integration/router /app/router

WORKDIR /app/router
RUN mvn -q -DskipTests package dependency:build-classpath -Dmdep.includeScope=runtime -Dmdep.outputFile=/tmp/router.classpath
EXPOSE 12000 12001

CMD ["sh", "-lc", "java -cp \"target/classes:$(cat /tmp/router.classpath)\" RunRouter"]
