@echo off
pip install -r requirements.txt
pyinstaller --onefile --windowed --name 3rdScreen --icon=assets\icon.ico --add-data "assets\icon.ico;assets" app.py
echo.
echo Exe is in dist\3rdScreen.exe
