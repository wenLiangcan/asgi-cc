FROM maven:3.9.11-eclipse-temurin-21

WORKDIR /app
COPY integration/java_app /app/java_app

WORKDIR /app/java_app
RUN mvn -q -DskipTests package dependency:build-classpath -Dmdep.includeScope=runtime -Dmdep.outputFile=/tmp/java-app.classpath

EXPOSE 18082
CMD ["sh", "-lc", "java -cp \"target/classes:$(cat /tmp/java-app.classpath)\" RunJavaBenchApp"]
