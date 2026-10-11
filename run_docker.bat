@echo off
echo ========================================================
echo  Starting Forsaken Music with Nginx Load Balancer
echo ========================================================

docker compose down
docker compose up --build -d

echo.
echo Application started successfully!
echo --------------------------------------------------------
echo Desktop Web Player:  http://localhost/desktop
echo Android Mobile UI:   http://localhost/mobile
echo Admin Portal:        http://localhost/admin
echo --------------------------------------------------------
pause
