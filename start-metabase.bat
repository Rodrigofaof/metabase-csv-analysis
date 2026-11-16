@echo off
REM Starts Metabase (JAR, no Docker) on http://localhost:3000 - keep this window open.
REM Requires Java 21+ on PATH (or JAVA_HOME set) and metabase\metabase.jar (see README).
cd /d "%~dp0metabase"
set MB_DB_FILE=%~dp0metabase\metabase.db
set MB_JETTY_PORT=3000
if defined JAVA_HOME (set "JAVA=%JAVA_HOME%\bin\java.exe") else (set "JAVA=java")
"%JAVA%" -Xmx2g --add-opens java.base/java.nio=ALL-UNNAMED -jar metabase.jar
