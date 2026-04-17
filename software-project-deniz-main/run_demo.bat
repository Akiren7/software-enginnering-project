@echo off
start "Server" cmd /k "cd /d %~dp0 && python -m server.main --id my-server --reset --gui"
start "Client 1" cmd /k "cd /d %~dp0 && python -m client.main --id my-server --login-id student1 --password secret1 --no-record"
start "Client 2" cmd /k "cd /d %~dp0 && python -m client.main --id my-server --login-id student2 --password secret2 --no-record"
start "Client 3" cmd /k "cd /d %~dp0 && python -m client.main --id my-server --login-id student3 --password secret3 --no-record"
