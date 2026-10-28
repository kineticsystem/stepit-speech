# The image that builds the Android app of android-ui and runs its unit tests:
# a JDK, the Android SDK's command-line tools, one platform and its build tools.
# No emulator and no phone: the unit tests run on the JVM, against a fake bridge.
# ./docker/dock.sh android runs Gradle in it, with the repo mounted at /app.

FROM eclipse-temurin:17-jdk-noble

ENV ANDROID_HOME=/opt/android-sdk
ENV PATH=$PATH:$ANDROID_HOME/cmdline-tools/latest/bin:$ANDROID_HOME/platform-tools

RUN apt-get update && apt-get install -y --no-install-recommends unzip \
    && rm -rf /var/lib/apt/lists/*

# Command-line tools 12.0.
RUN curl -fsSL -o /tmp/tools.zip \
        https://dl.google.com/android/repository/commandlinetools-linux-11076708_latest.zip \
    && mkdir -p $ANDROID_HOME/cmdline-tools \
    && unzip -q /tmp/tools.zip -d $ANDROID_HOME/cmdline-tools \
    && mv $ANDROID_HOME/cmdline-tools/cmdline-tools $ANDROID_HOME/cmdline-tools/latest \
    && rm /tmp/tools.zip

# The platform and build tools of compileSdk in android-ui/app/build.gradle.kts.
RUN yes | sdkmanager --licenses > /dev/null \
    && sdkmanager --install "platforms;android-35" "build-tools;35.0.0" "platform-tools" > /dev/null \
    && chmod -R a+rX $ANDROID_HOME

# Gradle, only to write the wrapper; the build uses the wrapper's own.
RUN curl -fsSL -o /tmp/gradle.zip https://services.gradle.org/distributions/gradle-8.10.2-bin.zip \
    && unzip -q /tmp/gradle.zip -d /opt \
    && ln -s /opt/gradle-8.10.2/bin/gradle /usr/local/bin/gradle \
    && rm /tmp/gradle.zip

WORKDIR /app/android-ui
