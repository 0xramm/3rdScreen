@echo off
pip install -r requirements.txt
pyinstaller --onefile --windowed --name ScreenCanvas --icon=assets\icon.ico --add-data "assets\icon.ico;assets" app.py
echo.
echo Exe is in dist\ScreenCanvas.exe
